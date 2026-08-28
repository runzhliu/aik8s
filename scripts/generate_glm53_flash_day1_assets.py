#!/usr/bin/env python3
"""Generate exact-data figures for the public GLM-5.3-Flash H20 report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


WIDTH = 1200
HEIGHT = 675
WECHAT_DIR = Path("articles/wechat/assets")
BG = "#F7F9FC"
INK = "#172033"
MUTED = "#64748B"
LINE = "#D7DEE9"
WHITE = "#FFFFFF"
BLUE = "#2563EB"
BLUE_LIGHT = "#EAF1FF"
ORANGE = "#F97316"
ORANGE_LIGHT = "#FFF1E8"
TEAL = "#0F9D8A"
TEAL_LIGHT = "#E7F8F5"
RED = "#DC2626"

FONT_CN = Path("/System/Library/Fonts/Hiragino Sans GB.ttc")
FONT_LATIN = Path("/System/Library/Fonts/HelveticaNeue.ttc")


def font(size: int, *, bold: bool = False, latin: bool = False) -> ImageFont.FreeTypeFont:
    path = FONT_LATIN if latin else FONT_CN
    index = 1 if bold and path == FONT_CN else 0
    if not path.exists():
        raise FileNotFoundError(f"font not found: {path}")
    return ImageFont.truetype(str(path), size=size, index=index)


def canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (WIDTH, HEIGHT), BG)
    return image, ImageDraw.Draw(image, "RGBA")


def rounded(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    *,
    fill: str = WHITE,
    outline: str = LINE,
    radius: int = 20,
    width: int = 2,
) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def title(draw: ImageDraw.ImageDraw, heading: str, subheading: str) -> None:
    draw.text((58, 36), heading, font=font(34, bold=True), fill=INK)
    draw.text((60, 86), subheading, font=font(18), fill=MUTED)


def centered_text(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    text_font: ImageFont.FreeTypeFont,
    fill: str,
) -> None:
    left, top, right, bottom = box
    bounds = draw.textbbox((0, 0), text, font=text_font)
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    draw.text(((left + right - width) / 2, (top + bottom - height) / 2 - bounds[1]), text, font=text_font, fill=fill)


def generate_short_throughput(data: dict, output: Path) -> None:
    image, draw = canvas()
    title(draw, "128/64 短请求：三轮中位数", "vLLM 高并发更快；新 Shape 首轮波动明显 · 随机 Token ID · 固定长度")

    rows = data["short_128_64_three_run_medians"]
    plot = (92, 164, 1128, 548)
    left, top, right, bottom = plot
    maximum = 1250
    for value in range(0, 1251, 250):
        y = bottom - (bottom - top) * value / maximum
        draw.line((left, y, right, y), fill=LINE, width=1)
        label = f"{value:,}"
        bounds = draw.textbbox((0, 0), label, font=font(15, latin=True))
        draw.text((left - 14 - (bounds[2] - bounds[0]), y - 9), label, font=font(15, latin=True), fill=MUTED)

    group_width = (right - left) / len(rows)
    bar_width = 54
    for index, row in enumerate(rows):
        center = left + group_width * (index + 0.5)
        values = [(row["sglang_output_tps"], BLUE), (row["vllm_output_tps"], ORANGE)]
        for side, (value, color) in enumerate(values):
            x1 = center - 64 + side * 72
            x2 = x1 + bar_width
            y1 = bottom - (bottom - top) * value / maximum
            draw.rounded_rectangle((x1, y1, x2, bottom), radius=8, fill=color)
            label = f"{value:.0f}"
            bounds = draw.textbbox((0, 0), label, font=font(16, bold=True, latin=True))
            draw.text(((x1 + x2 - (bounds[2] - bounds[0])) / 2, y1 - 25), label, font=font(16, bold=True, latin=True), fill=color)
        centered_text(draw, (int(center - 60), bottom + 14, int(center + 60), bottom + 50), f"C={row['concurrency']}", font(17, bold=True, latin=True), INK)

    draw.rounded_rectangle((745, 35, 893, 73), radius=18, fill=BLUE_LIGHT)
    draw.rectangle((762, 49, 790, 60), fill=BLUE)
    draw.text((800, 42), "SGLang", font=font(16, bold=True, latin=True), fill=INK)
    draw.rounded_rectangle((912, 35, 1065, 73), radius=18, fill=ORANGE_LIGHT)
    draw.rectangle((930, 49, 958, 60), fill=ORANGE)
    draw.text((968, 42), "vLLM", font=font(16, bold=True, latin=True), fill=INK)

    rounded(draw, (70, 592, 1130, 642), fill=WHITE, outline=LINE, radius=14)
    centered_text(draw, (80, 596, 1120, 638), "注意：中位数没有隐藏首次 JIT；vLLM C=8 的三轮 Output TPS 为 162 / 411 / 257", font(17), RED)

    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG", optimize=True)


def generate_long_context(data: dict, output: Path) -> None:
    image, draw = canvas()
    title(draw, "接近 1M Token：两套引擎均完成冷 Prefill", "并发 1 · 输出 128 Token · 每轮前清 Cache · 纵轴为 TTFT（秒）")

    rows = data["cold_long_context"]
    labels = ["32K", "64K", "128K", "257K", "512K", "1.04M"]
    plot = (112, 165, 1110, 535)
    left, top, right, bottom = plot
    maximum = 180
    for value in range(0, 181, 30):
        y = bottom - (bottom - top) * value / maximum
        draw.line((left, y, right, y), fill=LINE, width=1)
        label = str(value)
        bounds = draw.textbbox((0, 0), label, font=font(15, latin=True))
        draw.text((left - 18 - (bounds[2] - bounds[0]), y - 9), label, font=font(15, latin=True), fill=MUTED)

    xs = [left + (right - left) * i / (len(rows) - 1) for i in range(len(rows))]
    series = [
        ("sglang_ttft_seconds", BLUE, -13),
        ("vllm_ttft_seconds", ORANGE, 13),
    ]
    for key, color, x_offset in series:
        points = [(x, bottom - (bottom - top) * row[key] / maximum) for x, row in zip(xs, rows)]
        draw.line(points, fill=color, width=5, joint="curve")
        for index, ((x, y), row) in enumerate(zip(points, rows)):
            draw.ellipse((x - 7, y - 7, x + 7, y + 7), fill=color, outline=WHITE, width=2)
            if index >= 3:
                value = f"{row[key]:.1f}s"
                bounds = draw.textbbox((0, 0), value, font=font(15, bold=True, latin=True))
                label_x = x + x_offset - (bounds[2] - bounds[0]) / 2
                label_y = y - 28 if key == "sglang_ttft_seconds" else y + 13
                draw.text((label_x, label_y), value, font=font(15, bold=True, latin=True), fill=color)

    for x, label in zip(xs, labels):
        centered_text(draw, (int(x - 55), bottom + 13, int(x + 55), bottom + 49), label, font(17, bold=True, latin=True), INK)

    draw.rounded_rectangle((745, 35, 893, 73), radius=18, fill=BLUE_LIGHT)
    draw.line((762, 54, 792, 54), fill=BLUE, width=5)
    draw.text((802, 42), "SGLang", font=font(16, bold=True, latin=True), fill=INK)
    draw.rounded_rectangle((912, 35, 1065, 73), radius=18, fill=ORANGE_LIGHT)
    draw.line((930, 54, 960, 54), fill=ORANGE, width=5)
    draw.text((970, 42), "vLLM", font=font(16, bold=True, latin=True), fill=INK)

    rounded(draw, (70, 592, 1130, 642), fill=WHITE, outline=LINE, radius=14)
    centered_text(draw, (80, 596, 1120, 638), "vLLM 首次 32K 新 Shape TTFT 14.60s；图中使用 Warmup 后 3.43s，并未把首轮删除出原始 CSV", font(16), MUTED)

    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG", optimize=True)


def cache_card(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    *,
    engine: str,
    metric: str,
    cold: float,
    warm: float,
    hit_text: str,
    color: str,
    light: str,
    footnote: str,
) -> None:
    left, top, right, bottom = box
    rounded(draw, box, fill=WHITE, outline=color, radius=22)
    draw.rounded_rectangle((left, top, right, top + 76), radius=22, fill=light)
    draw.rectangle((left, top + 52, right, top + 76), fill=light)
    draw.text((left + 28, top + 20), engine, font=font(25, bold=True, latin=True), fill=color)
    draw.text((left + 28, top + 93), metric, font=font(18, bold=True), fill=INK)

    maximum = max(cold, warm) * 1.12
    bar_left, bar_right = left + 148, right - 38
    rows = [("冷请求", cold, top + 158), ("热中位数", warm, top + 240)]
    for label, value, y in rows:
        draw.text((left + 30, y + 8), label, font=font(17), fill=MUTED)
        draw.rounded_rectangle((bar_left, y, bar_right, y + 36), radius=16, fill="#E8EDF4")
        width = max(12, round((bar_right - bar_left) * value / maximum))
        draw.rounded_rectangle((bar_left, y, bar_left + width, y + 36), radius=16, fill=color)
        draw.text((bar_left + width + 10, y + 4), f"{value:.1f}ms", font=font(17, bold=True, latin=True), fill=color)

    draw.rounded_rectangle((left + 28, top + 318, right - 28, top + 375), radius=16, fill=light)
    centered_text(draw, (left + 38, top + 324, right - 38, top + 369), hit_text, font(19, bold=True), color)
    centered_text(draw, (left + 28, top + 397, right - 28, bottom - 17), footnote, font(15), MUTED)


def generate_prefix_cache(data: dict, output: Path) -> None:
    image, draw = canvas()
    title(draw, "Prefix Cache：两套 Runtime 都有命中，但客户端口径不同", "相同约 4,400 Token Prompt · 第 1 次冷请求 + 5 次完全重复")

    cache = data["prefix_cache"]
    sglang = cache["sglang"]
    vllm = cache["vllm"]
    cache_card(
        draw,
        (55, 145, 575, 615),
        engine="SGLang",
        metric="流式 TTFT",
        cold=sglang["cold_ttft_ms"],
        warm=sglang["warm_ttft_median_ms"],
        hit_text=f"TTFT -{sglang['ttft_reduction_percent']:.1f}%  ·  Hit Rate {sglang['server_cache_hit_rate_after'] * 100:.2f}%",
        color=BLUE,
        light=BLUE_LIGHT,
        footnote="首块内容稳定，客户端 TTFT 与服务端 Hit Rate 可互相验证",
    )
    cache_card(
        draw,
        (625, 145, 1145, 615),
        engine="vLLM Preview",
        metric="端到端 E2E",
        cold=vllm["cold_e2e_ms"],
        warm=vllm["warm_e2e_median_ms"],
        hit_text=f"Hit {vllm['hit_token_delta']:,} / Query {vllm['query_token_delta']:,} Token",
        color=ORANGE,
        light=ORANGE_LIGHT,
        footnote="流式可见首块不稳定，故只发布 E2E 与服务端 Metrics，不横比 TTFT",
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG", optimize=True)


def generate_wechat_cover(output: Path) -> None:
    image = Image.new("RGB", (900, 383), "#0B1F44")
    draw = ImageDraw.Draw(image, "RGBA")
    draw.ellipse((650, -175, 1035, 210), fill=BLUE)
    draw.ellipse((545, 205, 1010, 650), fill="#123D8B")
    draw.text((52, 34), "AIK8S  ·  DAY 1 推理实测", font=font(18), fill="#93C5FD")
    draw.text((52, 78), "GLM-5.3-Flash", font=font(42, bold=True, latin=True), fill=WHITE)
    draw.text((52, 139), "4×H20 跑通 1M 上下文", font=font(30, bold=True), fill="#DBEAFE")
    draw.text((52, 196), "SGLang / vLLM · Prefix Cache · OpenWebUI", font=font(18), fill="#BFDBFE")

    button = (52, 264, 358, 320)
    draw.rounded_rectangle(button, radius=28, fill=ORANGE)
    centered_text(draw, button, "部署 + 功能 + 压测", font(18, bold=True), WHITE)

    draw.rounded_rectangle((678, 89, 844, 257), radius=24, fill="#0F2F66", outline="#60A5FA", width=2)
    nodes = [(698, 110), (772, 110), (698, 181), (772, 181)]
    draw.line((736, 132, 772, 132), fill="#60A5FA", width=3)
    draw.line((736, 203, 772, 203), fill="#60A5FA", width=3)
    draw.line((717, 152, 717, 181), fill="#60A5FA", width=3)
    draw.line((791, 152, 791, 181), fill="#60A5FA", width=3)
    for x, y in nodes:
        draw.rounded_rectangle((x, y, x + 38, y + 42), radius=8, fill="#1D4ED8", outline="#93C5FD", width=2)
        draw.ellipse((x + 12, y + 14, x + 26, y + 28), fill="#DBEAFE")
    draw.text((792, 230), "H20", font=font(13, bold=True, latin=True), fill=WHITE)

    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG", optimize=True)


def copy_for_wechat(source: Path, target_name: str) -> None:
    WECHAT_DIR.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        image.convert("RGB").save(WECHAT_DIR / target_name, format="PNG", optimize=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data",
        type=Path,
        default=Path("examples/glm53-flash-day1/results/h20-fp8-summary-20260828.json"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("docs/assets/practices/glm53-flash-day1"),
    )
    args = parser.parse_args()

    data = json.loads(args.data.read_text(encoding="utf-8"))
    short_path = args.output_dir / "short-throughput-median.png"
    long_path = args.output_dir / "long-context-ttft.png"
    cache_path = args.output_dir / "prefix-cache-evidence.png"
    generate_short_throughput(data, short_path)
    generate_long_context(data, long_path)
    generate_prefix_cache(data, cache_path)
    generate_wechat_cover(WECHAT_DIR / "glm53-flash-day1-cover.png")
    copy_for_wechat(short_path, "glm53-flash-day1-short-throughput.png")
    copy_for_wechat(long_path, "glm53-flash-day1-long-context.png")
    copy_for_wechat(cache_path, "glm53-flash-day1-prefix-cache.png")


if __name__ == "__main__":
    main()
