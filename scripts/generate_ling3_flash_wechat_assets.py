#!/usr/bin/env python3
"""Generate light-mode Ling-3.0-flash WeChat covers and benchmark figures."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "examples/ling3-flash-h20/results/2026-09-03-h20-bf16"
ASSET_DIR = ROOT / "articles/wechat/assets/ling3-flash-h20"
LANDSCAPE_OUTPUT = ROOT / "articles/wechat/assets/ling3-flash-h20-cover.png"
SQUARE_OUTPUT = ROOT / "articles/wechat/assets/ling3-flash-h20-cover-square.png"

CHINESE = Path("/System/Library/Fonts/Hiragino Sans GB.ttc")
LATIN = Path("/System/Library/Fonts/HelveticaNeue.ttc")

INK = (15, 29, 50)
MUTED = (74, 96, 124)
BLUE = (37, 99, 235)
CYAN = (9, 166, 190)
ORANGE = (235, 82, 45)
VIOLET = (113, 78, 202)
PAPER = (247, 250, 253)
WHITE = (255, 255, 255)
LINE = (211, 222, 236)
PALE_BLUE = (229, 239, 255)
PALE_CYAN = (226, 247, 249)
PALE_ORANGE = (255, 238, 231)
GREEN = (28, 151, 103)


def font(path: Path, size: int, index: int = 0) -> ImageFont.FreeTypeFont:
    if not path.exists():
        raise FileNotFoundError(f"font not found: {path}")
    return ImageFont.truetype(str(path), size=size, index=index)


def text_width(draw: ImageDraw.ImageDraw, value: str, face: ImageFont.FreeTypeFont) -> int:
    box = draw.textbbox((0, 0), value, font=face)
    return box[2] - box[0]


def centered_text(
    draw: ImageDraw.ImageDraw,
    center_x: float,
    y: float,
    value: str,
    face: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int],
) -> None:
    draw.text((center_x - text_width(draw, value, face) / 2, y), value, font=face, fill=fill)


def add_grid(draw: ImageDraw.ImageDraw, width: int, height: int, step: int) -> None:
    for x in range(0, width, step):
        draw.line((x, 0, x, height), fill=(229, 236, 245), width=1)
    for y in range(0, height, step):
        draw.line((0, y, width, y), fill=(229, 236, 245), width=1)


def pill(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    label: str,
    *,
    size: int,
) -> tuple[int, int, int, int]:
    label_font = font(LATIN, size, 1)
    width = text_width(draw, label, label_font) + 34
    box = draw.textbbox((0, 0), label, font=label_font)
    height = box[3] - box[1] + 18
    left, top = xy
    bounds = (left, top, left + width, top + height)
    draw.rounded_rectangle(bounds, radius=height // 2, fill=PALE_BLUE, outline=(153, 193, 245))
    draw.text((left + 17, top + 9 - box[1]), label, font=label_font, fill=BLUE)
    return bounds


def cover_hardware(
    draw: ImageDraw.ImageDraw,
    bounds: tuple[int, int, int, int],
    *,
    scale: float,
) -> None:
    left, top, right, bottom = bounds
    draw.rounded_rectangle(bounds, radius=round(24 * scale), fill=PAPER, outline=LINE, width=2)
    draw.text(
        (left + round(20 * scale), top + round(18 * scale)),
        "SINGLE NODE",
        font=font(LATIN, round(13 * scale), 1),
        fill=BLUE,
    )
    for index in range(4):
        x = left + round((20 + index * 60) * scale)
        y = top + round(57 * scale)
        draw.rounded_rectangle(
            (x, y, x + round(45 * scale), y + round(70 * scale)),
            radius=round(7 * scale),
            fill=WHITE,
            outline=CYAN,
            width=max(1, round(2 * scale)),
        )
        centered_text(
            draw,
            x + round(22.5 * scale),
            y + round(20 * scale),
            "H20",
            font(LATIN, round(12 * scale), 1),
            INK,
        )
        centered_text(
            draw,
            x + round(22.5 * scale),
            y + round(43 * scale),
            "141G",
            font(LATIN, round(9 * scale)),
            MUTED,
        )
    draw.rounded_rectangle(
        (
            left + round(20 * scale),
            top + round(146 * scale),
            right - round(20 * scale),
            top + round(184 * scale),
        ),
        radius=round(8 * scale),
        fill=PALE_CYAN,
        outline=(167, 222, 227),
    )
    centered_text(
        draw,
        (left + right) / 2,
        top + round(155 * scale),
        "BF16 · TP4",
        font(LATIN, round(13 * scale), 1),
        INK,
    )
    draw.line(
        (
            left + round(35 * scale),
            top + round(205 * scale),
            right - round(35 * scale),
            top + round(205 * scale),
        ),
        fill=LINE,
        width=max(1, round(2 * scale)),
    )
    centered_text(
        draw,
        (left + right) / 2,
        bottom - round(34 * scale),
        "KDA × 35  +  MLA × 7",
        font(LATIN, round(12 * scale), 1),
        VIOLET,
    )


def compose_landscape() -> Path:
    image = Image.new("RGB", (900, 383), PAPER)
    draw = ImageDraw.Draw(image)
    add_grid(draw, 900, 383, 42)
    draw.rounded_rectangle((30, 24, 870, 359), radius=26, fill=WHITE, outline=LINE, width=2)
    draw.rectangle((30, 24, 42, 359), fill=BLUE)
    draw.text((72, 48), "124B MoE · 约 5B 激活 · 256K", font=font(CHINESE, 16), fill=BLUE)
    draw.text((68, 87), "Ling-3.0-flash", font=font(LATIN, 39, 1), fill=INK)
    draw.text((70, 140), "4×H20 双引擎实测", font=font(CHINESE, 31), fill=INK)
    pill(draw, (70, 207), "SGLang × vLLM · MTP", size=17)
    draw.text((70, 270), "9,022 请求 · 0 失败", font=font(CHINESE, 17), fill=MUTED)
    draw.text((70, 319), "AIK8S.RUN", font=font(LATIN, 13, 1), fill=CYAN)
    cover_hardware(draw, (565, 56, 828, 327), scale=0.88)
    image.save(LANDSCAPE_OUTPUT, format="PNG", optimize=True)
    return LANDSCAPE_OUTPUT


def compose_square() -> Path:
    image = Image.new("RGB", (900, 900), PAPER)
    draw = ImageDraw.Draw(image)
    add_grid(draw, 900, 900, 56)
    draw.rounded_rectangle((52, 46, 848, 854), radius=42, fill=WHITE, outline=LINE, width=2)
    draw.rectangle((52, 46, 848, 58), fill=BLUE)
    draw.text((90, 93), "124B MoE · 约 5B 激活 · 256K", font=font(CHINESE, 22), fill=BLUE)
    draw.text((86, 151), "Ling-3.0-flash", font=font(LATIN, 58, 1), fill=INK)
    draw.text((90, 230), "4×H20 双引擎实测", font=font(CHINESE, 45), fill=INK)
    cover_hardware(draw, (220, 344, 680, 706), scale=1.15)
    pill(draw, (90, 758), "SGLang × vLLM · MTP", size=21)
    draw.text((498, 766), "9,022 请求 · 0 失败", font=font(CHINESE, 18), fill=MUTED)
    draw.text((696, 816), "AIK8S.RUN", font=font(LATIN, 13, 1), fill=CYAN)
    image.save(SQUARE_OUTPUT, format="PNG", optimize=True)
    return SQUARE_OUTPUT


def figure(title: str, subtitle: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (1200, 675), PAPER)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((42, 38, 1158, 637), radius=28, fill=WHITE, outline=LINE, width=2)
    draw.rectangle((42, 38, 54, 637), fill=BLUE)
    draw.text((90, 72), title, font=font(CHINESE, 36), fill=INK)
    draw.text((92, 126), subtitle, font=font(CHINESE, 19), fill=MUTED)
    return image, draw


def legend(draw: ImageDraw.ImageDraw, x: int, y: int) -> None:
    draw.rounded_rectangle((x, y, x + 22, y + 22), radius=5, fill=BLUE)
    draw.text((x + 31, y - 1), "SGLang", font=font(LATIN, 17, 1), fill=INK)
    draw.rounded_rectangle((x + 145, y, x + 167, y + 22), radius=5, fill=ORANGE)
    draw.text((x + 176, y - 1), "vLLM", font=font(LATIN, 17, 1), fill=INK)


def load_summary(name: str) -> dict[str, dict[str, float]]:
    values: dict[str, dict[str, float]] = {}
    with (RESULTS / name).open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            values[row["case_id"]] = {
                key: float(value)
                for key, value in row.items()
                if key.startswith("median_") and value is not None
            }
    return values


def save_topology() -> Path:
    image, draw = figure(
        "单机 4×H20：同一模型、同一客户端、两套运行时",
        "Ling-3.0-flash BF16 · TP4 · Context 262,144 · 正式轮次前清理 Prefix Cache",
    )
    draw.rounded_rectangle((85, 208, 300, 475), radius=22, fill=PAPER, outline=VIOLET, width=2)
    draw.text((119, 239), "Ling-3.0", font=font(LATIN, 29, 1), fill=INK)
    draw.text((119, 278), "flash BF16", font=font(LATIN, 22, 1), fill=VIOLET)
    draw.text((119, 343), "124B 总参数", font=font(CHINESE, 19), fill=MUTED)
    draw.text((119, 378), "约 5B 激活", font=font(CHINESE, 19), fill=MUTED)
    draw.text((119, 413), "512 路由专家", font=font(CHINESE, 19), fill=MUTED)

    draw.line((300, 340, 374, 340), fill=BLUE, width=4)
    draw.polygon([(374, 340), (360, 331), (360, 349)], fill=BLUE)
    draw.rounded_rectangle((374, 188, 716, 497), radius=24, fill=PALE_CYAN, outline=CYAN, width=2)
    draw.text((422, 214), "单节点 · TP4", font=font(CHINESE, 26), fill=INK)
    for index in range(4):
        x = 407 + index * 72
        draw.rounded_rectangle((x, 285, x + 55, 390), radius=9, fill=WHITE, outline=CYAN, width=2)
        centered_text(draw, x + 27.5, 308, "H20", font(LATIN, 17, 1), INK)
        centered_text(draw, x + 27.5, 342, "141G", font(LATIN, 13), MUTED)
    draw.rounded_rectangle((407, 421, 683, 465), radius=10, fill=WHITE, outline=(167, 222, 227))
    centered_text(draw, 545, 432, "相同 Checkpoint 与 Case", font(CHINESE, 17), BLUE)

    for y, color in [(277, BLUE), (407, ORANGE)]:
        draw.line((716, y, 785, y), fill=color, width=4)
        draw.polygon([(785, y), (771, y - 9), (771, y + 9)], fill=color)
    draw.rounded_rectangle((785, 204, 1112, 333), radius=20, fill=PALE_BLUE, outline=BLUE, width=2)
    draw.text((823, 228), "SGLang", font=font(LATIN, 25, 1), fill=BLUE)
    draw.text((823, 270), "Baseline / NEXTN", font=font(LATIN, 18, 1), fill=INK)
    draw.rounded_rectangle((785, 354, 1112, 483), radius=20, fill=PALE_ORANGE, outline=ORANGE, width=2)
    draw.text((823, 378), "vLLM", font=font(LATIN, 25, 1), fill=ORANGE)
    draw.text((823, 420), "Baseline / MTP", font=font(LATIN, 18, 1), fill=INK)
    draw.rounded_rectangle((85, 548, 1112, 603), radius=13, fill=(237, 243, 250))
    centered_text(
        draw,
        598,
        563,
        "同一个 vllm bench serve 客户端 · 相同长度、并发、Seed、重复次数",
        font(CHINESE, 18),
        MUTED,
    )
    output = ASSET_DIR / "test-topology.png"
    image.save(output, format="PNG", optimize=True)
    return output


def grouped_bars(
    draw: ImageDraw.ImageDraw,
    *,
    cases: list[str],
    sglang: list[float],
    vllm: list[float],
    top: int,
    bottom: int,
    max_value: float,
) -> None:
    left, right = 120, 1115
    for tick_index in range(6):
        tick = max_value * tick_index / 5
        y = bottom - (bottom - top) * tick / max_value
        draw.line((left, y, right, y), fill=(224, 231, 240), width=1)
        label = f"{tick:.0f}"
        draw.text((left - 18 - text_width(draw, label, font(LATIN, 14)), y - 8), label, font=font(LATIN, 14), fill=MUTED)
    group_width = (right - left) / len(cases)
    for index, case in enumerate(cases):
        center = left + group_width * (index + 0.5)
        for offset, value, color in [(-42, sglang[index], BLUE), (8, vllm[index], ORANGE)]:
            x0 = int(center + offset)
            x1 = x0 + 36
            y0 = int(bottom - (bottom - top) * value / max_value)
            draw.rounded_rectangle((x0, y0, x1, bottom), radius=6, fill=color)
            label = f"{value:.1f}"
            centered_text(draw, x0 + 18, y0 - 25, label, font(LATIN, 14, 1), INK)
        centered_text(draw, center, bottom + 17, case, font(LATIN, 16, 1), INK)


def save_baseline() -> Path:
    sglang = load_summary("sglang-baseline-summary.csv")
    vllm = load_summary("vllm-baseline-summary.csv")
    ids = ["short-128-64-c16", "rag-4k-128-c8", "long-16k-256-c8", "decode-128-1k-c8"]
    labels = ["Short C16", "RAG 4K C8", "Long 16K C8", "Decode 1K C8"]
    sg_values = [sglang[item]["median_output_throughput"] for item in ids]
    vl_values = [vllm[item]["median_output_throughput"] for item in ids]
    image, draw = figure(
        "常规负载：SGLang 的输出吞吐全面领先",
        "BF16 · TP4 · 重复轮次中位数 · 输出 token/s（越高越好）",
    )
    grouped_bars(
        draw,
        cases=labels,
        sglang=sg_values,
        vllm=vl_values,
        top=205,
        bottom=535,
        max_value=1800,
    )
    legend(draw, 824, 160)
    draw.text((96, 592), "10 组常规对比中，SGLang 全部领先 13.7%～36.5%。", font=font(CHINESE, 18), fill=BLUE)
    output = ASSET_DIR / "baseline-throughput.png"
    image.save(output, format="PNG", optimize=True)
    return output


def save_long_context() -> Path:
    sglang = load_summary("sglang-baseline-summary.csv")
    vllm = load_summary("vllm-baseline-summary.csv")
    ids = ["ctx-32k-128-c1", "ctx-64k-128-c1", "ctx-128k-128-c1", "ctx-256k-128-c1"]
    labels = ["32K", "64K", "128K", "256K"]
    sg_values = [sglang[item]["median_output_throughput"] for item in ids]
    vl_values = [vllm[item]["median_output_throughput"] for item in ids]
    image, draw = figure(
        "长上下文：128K 后，吞吐优势转向 vLLM",
        "单请求 · 128 Token 输出 · 输出 token/s（越高越好）",
    )
    grouped_bars(
        draw,
        cases=labels,
        sglang=sg_values,
        vllm=vl_values,
        top=205,
        bottom=535,
        max_value=110,
    )
    legend(draw, 824, 160)
    draw.text(
        (96, 586),
        "32K/64K：SGLang +20.1%/+13.7%   ·   128K/256K：vLLM +10.2%/+12.6%",
        font=font(CHINESE, 17),
        fill=VIOLET,
    )
    output = ASSET_DIR / "long-context-throughput.png"
    image.save(output, format="PNG", optimize=True)
    return output


def save_correctness() -> Path:
    counts: dict[str, dict[int, int]] = {}
    for engine in ("sglang", "vllm"):
        grouped = {32768: 0, 65536: 0, 131072: 0, 262144: 0}
        with (RESULTS / f"{engine}-needle.jsonl").open(encoding="utf-8") as handle:
            for line in handle:
                record = json.loads(line)
                if record["pass"]:
                    grouped[int(record["context_target"])] += 1
        counts[engine] = grouped
    image, draw = figure(
        "32K～256K Needle：两套引擎均为 12 / 12 PASS",
        "每档放置 10% / 50% / 90% 三个 Needle · 唯一字符串精确匹配",
    )
    legend(draw, 824, 160)
    contexts = [(32768, "32K"), (65536, "64K"), (131072, "128K"), (262144, "256K")]
    for row, (value, label) in enumerate(contexts):
        y = 207 + row * 88
        draw.rounded_rectangle((90, y, 225, y + 65), radius=14, fill=INK)
        centered_text(draw, 157.5, y + 15, label, font(LATIN, 27, 1), WHITE)
        for column, engine in enumerate(("sglang", "vllm")):
            x = 257 + column * 430
            color = BLUE if engine == "sglang" else ORANGE
            draw.rounded_rectangle((x, y, x + 400, y + 65), radius=14, fill=WHITE, outline=LINE, width=2)
            draw.ellipse((x + 22, y + 16, x + 55, y + 49), fill=color)
            draw.line((x + 30, y + 33, x + 36, y + 40), fill=WHITE, width=3)
            draw.line((x + 36, y + 40, x + 48, y + 25), fill=WHITE, width=3)
            draw.text((x + 76, y + 16), f"{counts[engine][value]} / 3 PASS", font=font(LATIN, 22, 1), fill=INK)
    draw.rounded_rectangle((90, 573, 1087, 613), radius=10, fill=(237, 243, 250))
    centered_text(
        draw,
        588,
        582,
        "Models · Thinking On/Off · Streaming · Multi-turn · Tool Call：两边全部通过",
        font(CHINESE, 16),
        MUTED,
    )
    output = ASSET_DIR / "correctness-gates.png"
    image.save(output, format="PNG", optimize=True)
    return output


def save_speculative() -> Path:
    sg_base = load_summary("sglang-baseline-summary.csv")
    sg_spec = load_summary("sglang-nextn-summary.csv")
    vl_base = load_summary("vllm-baseline-summary.csv")
    vl_spec = load_summary("vllm-mtp-summary.csv")
    cases = [
        ("Short C1", "short-128-64-c1"),
        ("Short C4", "short-128-64-c4"),
        ("Short C8", "short-128-64-c8"),
        ("Short C16", "short-128-64-c16"),
        ("RAG 4K C4", "rag-4k-128-c4"),
        ("RAG 4K C8", "rag-4k-128-c8"),
        ("Decode 1K C1", "decode-128-1k-c1"),
        ("Decode 1K C8", "decode-128-1k-c8"),
    ]

    def delta(spec: dict[str, dict[str, float]], base: dict[str, dict[str, float]], case_id: str) -> float:
        after = spec[case_id]["median_output_throughput"]
        before = base[case_id]["median_output_throughput"]
        return (after / before - 1) * 100

    image, draw = figure(
        "Speculative Decoding：低并发 Decode 获益，高并发可能倒退",
        "相对各自 Off 基线的输出吞吐变化 · SGLang NEXTN / vLLM MTP",
    )
    chart_left, chart_right, center = 310, 1090, 700
    scale = (chart_right - chart_left) / 120
    for tick in range(-60, 61, 20):
        x = center + tick * scale
        draw.line((x, 178, x, 568), fill=(224, 231, 240) if tick else MUTED, width=2 if tick == 0 else 1)
        centered_text(draw, x, 575, f"{tick:+d}%", font(LATIN, 13), MUTED)
    for row, (label, case_id) in enumerate(cases):
        y = 190 + row * 47
        draw.text((98, y + 7), label, font=font(LATIN, 15, 1), fill=MUTED)
        values = [delta(sg_spec, sg_base, case_id), delta(vl_spec, vl_base, case_id)]
        for offset, value, color in [(0, values[0], BLUE), (19, values[1], ORANGE)]:
            x_end = center + value * scale
            left, right = sorted((center, x_end))
            draw.rounded_rectangle((left, y + offset, right, y + offset + 13), radius=4, fill=color)
            label_value = f"{value:+.1f}%"
            if value >= 0:
                label_x = right + 7
            else:
                label_x = left - text_width(draw, label_value, font(LATIN, 12, 1)) - 7
            draw.text((label_x, y + offset - 1), label_value, font=font(LATIN, 12, 1), fill=INK)
    legend(draw, 824, 146)
    draw.text((92, 609), "结论：MTP/NEXTN 应按流量分池，不应作为全局默认开关。", font=font(CHINESE, 17), fill=VIOLET)
    output = ASSET_DIR / "speculative-delta.png"
    image.save(output, format="PNG", optimize=True)
    return output


def main() -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    outputs = [
        compose_landscape(),
        compose_square(),
        save_topology(),
        save_baseline(),
        save_long_context(),
        save_correctness(),
        save_speculative(),
    ]
    for output in outputs:
        print(f"generated: {output}")


if __name__ == "__main__":
    main()
