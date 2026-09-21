#!/usr/bin/env python3
"""Generate public Qwen-Image-2.1 benchmark figures from retained evidence."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


ROOT = Path(__file__).resolve().parents[1]
FONT = "/System/Library/Fonts/Hiragino Sans GB.ttc"
OUT = ROOT / "docs/assets/practices/qwen-image21-l20"
BG = "#f6f8fc"
PANEL = "#ffffff"
INK = "#18233b"
MUTED = "#66728a"
GRID = "#dfe5f0"
BLUE = "#1769e0"
ORANGE = "#ed8a22"


def font(size: int, bold: bool = False):
    return ImageFont.truetype(FONT, size, index=1 if bold else 0)


def text(draw, xy, value, size=24, fill=INK, anchor=None, bold=False):
    draw.text(xy, value, font=font(size, bold), fill=fill, anchor=anchor)


def read_summary(root: Path, concurrency: int) -> dict:
    path = root / f"primary-1024-c{concurrency}" / "summary.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    measured = value["measured"]
    return {
        "engine": value["engine"],
        "concurrency": concurrency,
        "attempted": measured["attempted"],
        "succeeded": measured["succeeded"],
        "failed": measured["failed"],
        "wall_seconds": measured["wall_seconds"],
        "images_per_minute": measured["successful_images_per_minute"],
        "p50_seconds": measured["latency_seconds"]["p50"],
        "p90_seconds": measured["latency_seconds"]["p90"],
        "p95_seconds": measured["latency_seconds"]["p95"],
        "p99_seconds": measured["latency_seconds"]["p99"],
    }


def rounded_panel(draw, box):
    draw.rounded_rectangle(box, radius=20, fill=PANEL, outline=GRID, width=2)


def comparison_chart(rows: list[dict], output: Path):
    by_key = {(row["engine"], row["concurrency"]): row for row in rows}
    image = Image.new("RGB", (1200, 675), BG)
    draw = ImageDraw.Draw(image)
    text(draw, (54, 34), "单卡 L20：并发增加后，吞吐为什么没有上升", 37, bold=True)
    text(draw, (55, 88), "Qwen-Image-2.1 · 1024×1024 · 40 步 · 每档 10 个正式样本", 20, MUTED)

    left_box = (50, 135, 575, 575)
    right_box = (600, 135, 1150, 575)
    rounded_panel(draw, left_box)
    rounded_panel(draw, right_box)
    text(draw, (78, 162), "成功吞吐", 25, bold=True)
    text(draw, (78, 197), "images/min", 17, MUTED)
    text(draw, (628, 162), "P95 端到端延迟", 25, bold=True)
    text(draw, (628, 197), "秒", 17, MUTED)

    concurrencies = [1, 2, 4]
    engines = [("sglang", "SGLang", BLUE), ("vllm-omni", "vLLM-Omni", ORANGE)]
    # Throughput bars.
    plot_left, plot_right, plot_top, plot_bottom = 100, 535, 245, 505
    for tick in (0, 1, 2, 3):
        y = plot_bottom - tick / 3 * (plot_bottom - plot_top)
        draw.line((plot_left, y, plot_right, y), fill=GRID, width=1)
        text(draw, (88, y), str(tick), 16, MUTED, anchor="rm")
    for i, concurrency in enumerate(concurrencies):
        center = 170 + i * 145
        for j, (engine, _name, color) in enumerate(engines):
            value = by_key[(engine, concurrency)]["images_per_minute"]
            x = center + (-27 if j == 0 else 27)
            y = plot_bottom - value / 3 * (plot_bottom - plot_top)
            draw.rounded_rectangle((x - 20, y, x + 20, plot_bottom), radius=7, fill=color)
            text(draw, (x, y - 11), f"{value:.2f}", 17, color, anchor="mb", bold=True)
        text(draw, (center, 525), f"C{concurrency}", 18, INK, anchor="mm")

    # P95 lines.
    p_left, p_right, p_top, p_bottom = 680, 1095, 245, 505
    for tick in (0, 40, 80, 120):
        y = p_bottom - tick / 120 * (p_bottom - p_top)
        draw.line((p_left, y, p_right, y), fill=GRID, width=1)
        text(draw, (668, y), str(tick), 16, MUTED, anchor="rm")
    xs = [730, 875, 1020]
    for engine, _name, color in engines:
        points = []
        for x, concurrency in zip(xs, concurrencies):
            value = by_key[(engine, concurrency)]["p95_seconds"]
            y = p_bottom - value / 120 * (p_bottom - p_top)
            points.append((x, y))
        draw.line(points, fill=color, width=4)
        for (x, y), concurrency in zip(points, concurrencies):
            value = by_key[(engine, concurrency)]["p95_seconds"]
            draw.ellipse((x - 6, y - 6, x + 6, y + 6), fill=color)
            if engine == "sglang":
                text(draw, (x - 12, y - 11), f"{value:.1f}", 16, color, anchor="rb", bold=True)
            else:
                text(draw, (x + 12, y + 11), f"{value:.1f}", 16, color, anchor="lt", bold=True)
    for x, concurrency in zip(xs, concurrencies):
        text(draw, (x, 525), f"C{concurrency}", 18, INK, anchor="mm")

    for i, (_engine, name, color) in enumerate(engines):
        x = 370 + i * 210
        draw.rounded_rectangle((x, 600, x + 25, 618), radius=4, fill=color)
        text(draw, (x + 38, 608), name, 18, INK, anchor="lm")
    text(draw, (600, 647), "服务端均为单活动请求；并发升高主要增加排队时间。", 18, MUTED, anchor="mm")
    image.save(output)


def checker(size):
    tile = 16
    image = Image.new("RGBA", size, "white")
    draw = ImageDraw.Draw(image)
    for y in range(0, size[1], tile):
        for x in range(0, size[0], tile):
            if (x // tile + y // tile) % 2:
                draw.rectangle((x, y, x + tile - 1, y + tile - 1), fill="#e7eaf0")
    return image


def tile_image(path: Path, size=(204, 204)):
    with Image.open(path) as source:
        source.load()
        fitted = ImageOps.fit(source.convert("RGBA"), size, method=Image.Resampling.LANCZOS)
    background = checker(size)
    background.alpha_composite(fitted)
    return background.convert("RGB")


def sample_contact_sheet(sglang_root: Path, vllm_root: Path, output: Path):
    image = Image.new("RGB", (1200, 675), BG)
    draw = ImageDraw.Draw(image)
    text(draw, (50, 28), "同一组 Prompt 与 Seed，两套引擎的实际输出", 36, bold=True)
    text(draw, (51, 80), "从左到右：街景、中文排版、英文排版、产品摄影、透明背景", 19, MUTED)
    starts = [105, 323]
    roots = [(sglang_root, "SGLang"), (vllm_root, "vLLM-Omni")]
    for row, ((root, name), y) in enumerate(zip(roots, starts)):
        text(draw, (137, y + 102), name, 19, BLUE if row == 0 else ORANGE, anchor="rm", bold=True)
        for index in range(5):
            path = root / "primary-1024-c1" / "measured" / f"measured-{index:04d}-0.png"
            thumb = tile_image(path)
            x = 150 + index * 205
            image.paste(thumb, (x, y))
            draw.rectangle((x, y, x + 203, y + 203), outline="#cad3e1", width=1)
    text(draw, (50, 558), "检查范围", 20, INK, bold=True)
    text(draw, (150, 558), "主体与构图、指定文字、产品质感、PNG Alpha 通道", 19, MUTED)
    text(draw, (50, 610), "说明", 20, INK, bold=True)
    text(draw, (150, 610), "相同 Seed 不保证跨引擎逐像素一致；样例用于验证功能链路和可用性。", 19, MUTED)
    image.save(output)


def gallery(root: Path, engine: str, color: str, output: Path):
    image = Image.new("RGB", (1200, 675), BG)
    draw = ImageDraw.Draw(image)
    text(draw, (48, 28), f"{engine} 实际生成样例", 36, bold=True)
    text(draw, (49, 80), "1024×1024 · 40 步 · 固定 Prompt 与 Seed · 原始 PNG", 19, MUTED)
    items = [
        (0, "写实街景", "雨后街角\n红色复古自行车"),
        (1, "中文排版", "指定文字\n“让想象发生”"),
        (3, "产品摄影", "半透明玻璃\n影棚灯光与焦散"),
        (4, "透明 PNG", "剪纸龙主体\nAlpha 0–255"),
    ]
    for column, (index, name, description) in enumerate(items):
        path = root / "primary-1024-c1" / "measured" / f"measured-{index:04d}-0.png"
        thumb = tile_image(path, (270, 270))
        x = 30 + column * 285
        image.paste(thumb, (x, 126))
        draw.rectangle((x, 126, x + 269, 395), outline="#cbd5e5", width=2)
        draw.rounded_rectangle((x + 55, 417, x + 215, 461), radius=20, fill=color)
        text(draw, (x + 135, 439), name, 18, "white", anchor="mm", bold=True)
        for line, value in enumerate(description.splitlines()):
            text(draw, (x + 135, 500 + line * 31), value, 17, MUTED, anchor="mm")
    text(draw, (600, 641), "图片来自正式压测输出；透明素材使用棋盘格显示 Alpha 通道。", 17, MUTED, anchor="mm")
    image.save(output)


def crop_grafana(source: Path, output: Path, replacement_title: str | None = None):
    with Image.open(source) as image:
        image = image.convert("RGB")
        # Overview screenshots are 1600×1000. The top 900 px contain the complete
        # dashboard title, stat cards and the useful parts of all four trend panels.
        cropped = image.crop((0, 0, image.width, min(900, image.height)))
        cropped = cropped.resize((1200, 675), Image.Resampling.LANCZOS)
        if replacement_title:
            draw = ImageDraw.Draw(cropped)
            draw.rectangle((12, 96, 610, 127), fill="white")
            text(draw, (18, 100), replacement_title, 19, "#1b1f23", bold=False)
        cropped.save(output)


def crop_workbench(source: Path, output: Path):
    with Image.open(source) as image:
        image = image.convert("RGB")
        # Keep the batch controls and the beginning of the results gallery.
        cropped = image.crop((180, 120, 1260, 728))
        canvas = Image.new("RGB", (1200, 675), BG)
        draw = ImageDraw.Draw(canvas)
        text(draw, (42, 25), "Qwen-Image-2.1 图像工作台", 30, INK, bold=True)
        text(draw, (43, 66), "批量 1–200 张 · 客户端并行度 1–10 · 随机或递增 Seed", 17, MUTED)
        fitted = ImageOps.contain(cropped, (1120, 560), Image.Resampling.LANCZOS)
        canvas.paste(fitted, ((1200 - fitted.width) // 2, 100))
        canvas.save(output)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_data(rows: list[dict], sglang_root: Path, vllm_root: Path):
    csv_path = OUT / "benchmark-results.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    sources = []
    for engine, root in (("sglang", sglang_root), ("vllm-omni", vllm_root)):
        for concurrency in (1, 2, 4):
            path = root / f"primary-1024-c{concurrency}" / "summary.json"
            sources.append({
                "engine": engine,
                "case": f"1024-c{concurrency}",
                "sha256": sha256(path),
            })
    payload = {
        "schema": 1,
        "model": "Qwen/Qwen-Image-2.1",
        "hardware": "1x NVIDIA L20 48 GB per engine run",
        "request": {"width": 1024, "height": 1024, "steps": 40, "warmup": 2, "measured": 10},
        "results": rows,
        "resource_peaks": {
            "sglang": {"gpu_util_percent": 100, "framebuffer_gb": 32.8, "power_w": 351, "temperature_c": 79},
            "vllm-omni": {"gpu_util_percent": 100, "framebuffer_gb": 40.4, "power_w": 355, "temperature_c": 78},
        },
        "source_summary_sha256": sources,
    }
    (OUT / "benchmark-summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sglang-root", type=Path, required=True)
    parser.add_argument("--vllm-root", type=Path, required=True)
    parser.add_argument("--sglang-grafana", type=Path, required=True)
    parser.add_argument("--vllm-grafana", type=Path, required=True)
    parser.add_argument("--workbench", type=Path, required=True)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    rows = [read_summary(root, concurrency) for root in (args.sglang_root, args.vllm_root) for concurrency in (1, 2, 4)]
    comparison_chart(rows, OUT / "engine-comparison.png")
    sample_contact_sheet(args.sglang_root, args.vllm_root, OUT / "sample-comparison.png")
    gallery(args.sglang_root, "SGLang", BLUE, OUT / "generated-samples-sglang.png")
    gallery(args.vllm_root, "vLLM-Omni", ORANGE, OUT / "generated-samples-vllm.png")
    crop_grafana(
        args.sglang_grafana,
        OUT / "grafana-sglang-overview-light.png",
        "Qwen-Image-2.1 · SGLang · 单卡 L20",
    )
    crop_grafana(args.vllm_grafana, OUT / "grafana-vllm-overview-light.png")
    crop_workbench(args.workbench, OUT / "batch-workbench.png")
    write_data(rows, args.sglang_root, args.vllm_root)
    print(OUT)


if __name__ == "__main__":
    main()
