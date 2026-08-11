#!/usr/bin/env python3
"""Generate figures for the DeepSeek V4 Flash H20 and P/D article."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


WIDTH = 1200
BG = "#F7F9FC"
INK = "#172033"
MUTED = "#5E6B82"
BLUE = "#2563EB"
BLUE_DARK = "#1749B5"
BLUE_LIGHT = "#EAF2FF"
TEAL = "#0F9D8A"
TEAL_LIGHT = "#E7F8F5"
ORANGE = "#F37726"
ORANGE_LIGHT = "#FFF1E8"
RED = "#D94B5B"
LINE = "#C9D4E6"
WHITE = "#FFFFFF"

FONT_CN = Path("/System/Library/Fonts/Hiragino Sans GB.ttc")
FONT_LATIN = Path("/System/Library/Fonts/HelveticaNeue.ttc")


def font(size: int, *, bold: bool = False, latin: bool = False) -> ImageFont.FreeTypeFont:
    path = FONT_LATIN if latin else FONT_CN
    index = 1 if bold and path == FONT_CN else 0
    return ImageFont.truetype(str(path), size=size, index=index)


def canvas(height: int) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (WIDTH, height), BG)
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


def center_text(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    text_font: ImageFont.FreeTypeFont,
    fill: str = INK,
    spacing: int = 7,
) -> None:
    left, top, right, bottom = box
    bounds = draw.multiline_textbbox((0, 0), text, font=text_font, spacing=spacing, align="center")
    text_width = bounds[2] - bounds[0]
    text_height = bounds[3] - bounds[1]
    draw.multiline_text(
        ((left + right - text_width) / 2, (top + bottom - text_height) / 2 - bounds[1]),
        text,
        font=text_font,
        fill=fill,
        spacing=spacing,
        align="center",
    )


def title(draw: ImageDraw.ImageDraw, heading: str, subheading: str) -> None:
    draw.text((55, 38), heading, font=font(34, bold=True), fill=INK)
    draw.text((57, 88), subheading, font=font(19), fill=MUTED)


def arrow(
    draw: ImageDraw.ImageDraw,
    start: tuple[int, int],
    end: tuple[int, int],
    *,
    color: str = BLUE,
    width: int = 4,
) -> None:
    draw.line((start, end), fill=color, width=width)
    ex, ey = end
    draw.polygon(((ex, ey), (ex - 12, ey - 8), (ex - 12, ey + 8)), fill=color)


def gpu_row(draw: ImageDraw.ImageDraw, left: int, top: int, *, count: int = 8) -> None:
    for gpu in range(count):
        x = left + gpu * 43
        draw.rounded_rectangle((x, top, x + 34, top + 34), radius=6, fill=BLUE_DARK)
        center_text(draw, (x, top, x + 34, top + 34), str(gpu), font(12, bold=True, latin=True), WHITE)


def architecture(output: Path) -> None:
    image, draw = canvas(680)
    title(draw, "同一模型，两种资源拓扑", "普通 TP=8 用一套权重完成 Prefill/Decode；P/D 用两套 TP=8 隔离阶段并传输 KV Cache")

    rounded(draw, (55, 145, 555, 600), fill=WHITE, outline="#AFC8F7")
    draw.text((85, 170), "普通 TP=8", font=font(27, bold=True), fill=INK)
    rounded(draw, (110, 230, 500, 290), fill=BLUE_LIGHT, outline="#AFC8F7", radius=14)
    center_text(draw, (110, 230, 500, 290), "OpenAI Client → vLLM API", font(19, bold=True), BLUE_DARK)
    arrow(draw, (305, 292), (305, 335))
    rounded(draw, (110, 345, 500, 440), fill="#F1F5FF", outline="#8FB1F0", radius=16)
    center_text(draw, (110, 345, 500, 440), "Combined Engine\nPrefill + Decode · TP=8", font(23, bold=True), INK)
    gpu_row(draw, 132, 475)
    center_text(draw, (105, 525, 505, 565), "8 × H20 · 866.61 tok/s", font(19, bold=True, latin=True), BLUE_DARK)

    rounded(draw, (645, 145, 1145, 600), fill=WHITE, outline="#8FD6CA")
    draw.text((675, 170), "AIBrix P/D", font=font(27, bold=True), fill=INK)
    rounded(draw, (790, 215, 1000, 270), fill=TEAL_LIGHT, outline="#8FD6CA", radius=14)
    center_text(draw, (790, 215, 1000, 270), "AIBrix Gateway", font(19, bold=True, latin=True), TEAL)
    draw.line((895, 270, 895, 305), fill=TEAL, width=4)
    draw.line((755, 305, 1035, 305), fill=TEAL, width=4)
    draw.line((755, 305, 755, 335), fill=TEAL, width=4)
    draw.line((1035, 305, 1035, 335), fill=TEAL, width=4)
    rounded(draw, (675, 345, 835, 425), fill=BLUE_LIGHT, outline="#8FB1F0", radius=14)
    rounded(draw, (955, 345, 1115, 425), fill=TEAL_LIGHT, outline="#8FD6CA", radius=14)
    center_text(draw, (675, 345, 835, 425), "Prefill\nTP=8", font(21, bold=True), BLUE_DARK)
    center_text(draw, (955, 345, 1115, 425), "Decode\nTP=8", font(21, bold=True), TEAL)
    arrow(draw, (840, 385), (945, 385), color=ORANGE)
    draw.text((858, 347), "NIXL", font=font(15, bold=True, latin=True), fill=ORANGE)
    draw.text((855, 403), "KV Cache", font=font(13, latin=True), fill=MUTED)
    center_text(draw, (675, 455, 1115, 500), "8 × H20  +  8 × H20", font(19, bold=True, latin=True), TEAL)
    center_text(draw, (670, 515, 1120, 560), "16 GPUs · 817.95 tok/s · p95 TTFT -47.3%", font(18, bold=True, latin=True), TEAL)

    center_text(draw, (120, 620, 1080, 665), "P/D 买到的是阶段隔离和更低尾延迟，不是凭空增加的算力", font(20, bold=True), INK)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG", optimize=True)


def warmup(output: Path) -> None:
    image, draw = canvas(565)
    title(draw, "端口 Ready，不等于推理已经稳态", "同一模型、GPU 和请求形状，只因 TileLang JIT 与预热状态不同，结果相差超过 10 倍")

    rounded(draw, (65, 155, 520, 470), fill=ORANGE_LIGHT, outline="#F6B58A")
    draw.text((105, 185), "首次直接压测", font=font(26, bold=True), fill=INK)
    draw.text((105, 250), "33.4 s", font=font(58, bold=True, latin=True), fill=ORANGE)
    draw.text((110, 325), "p95 TTFT", font=font(19, bold=True, latin=True), fill=MUTED)
    draw.text((110, 370), "约 92 tok/s", font=font(22, bold=True), fill=INK)
    rounded(draw, (105, 415, 475, 450), fill="#FFE3D2", outline="#F6B58A", radius=10)
    center_text(draw, (105, 415, 475, 450), "请求期间触发 TileLang JIT", font(16, bold=True), ORANGE)

    arrow(draw, (535, 315), (655, 315), color=BLUE)
    center_text(draw, (520, 250, 670, 295), "同形状预热", font(18, bold=True), BLUE)

    rounded(draw, (680, 155, 1135, 470), fill=TEAL_LIGHT, outline="#8FD6CA")
    draw.text((720, 185), "预热后复跑", font=font(26, bold=True), fill=INK)
    draw.text((720, 250), "233 ms", font=font(58, bold=True, latin=True), fill=TEAL)
    draw.text((725, 325), "p95 TTFT", font=font(19, bold=True, latin=True), fill=MUTED)
    draw.text((725, 370), "约 934 tok/s", font=font(22, bold=True), fill=INK)
    rounded(draw, (720, 415, 1090, 450), fill="#D4F2ED", outline="#8FD6CA", radius=10)
    center_text(draw, (720, 415, 1090, 450), "模型运行时进入稳态", font(16, bold=True), TEAL)

    center_text(draw, (120, 495, 1080, 545), "性能测试顺序：Ready → 真实形状预热 → 稳态复跑 → 记录指标", font(19, bold=True), INK)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG", optimize=True)


def metric_row(
    draw: ImageDraw.ImageDraw,
    top: int,
    label: str,
    baseline: float,
    pd_value: float,
    unit: str,
    maximum: float,
) -> None:
    draw.text((80, top), label, font=font(20, bold=True), fill=INK)
    bar_left, bar_width = 335, 560
    draw.text((230, top + 45), "TP=8", font=font(15, bold=True, latin=True), fill=BLUE_DARK)
    draw.rounded_rectangle((bar_left, top + 43, bar_left + bar_width, top + 67), radius=12, fill="#E4EAF4")
    draw.rounded_rectangle(
        (bar_left, top + 43, bar_left + int(bar_width * baseline / maximum), top + 67),
        radius=12,
        fill=BLUE,
    )
    draw.text((925, top + 39), f"{baseline:g} {unit}", font=font(17, bold=True, latin=True), fill=BLUE_DARK)
    draw.text((230, top + 85), "P/D", font=font(15, bold=True, latin=True), fill=TEAL)
    draw.rounded_rectangle((bar_left, top + 83, bar_left + bar_width, top + 107), radius=12, fill="#E4EAF4")
    draw.rounded_rectangle(
        (bar_left, top + 83, bar_left + int(bar_width * pd_value / maximum), top + 107),
        radius=12,
        fill=TEAL,
    )
    draw.text((925, top + 79), f"{pd_value:g} {unit}", font=font(17, bold=True, latin=True), fill=TEAL)


def performance(output: Path) -> None:
    image, draw = canvas(760)
    title(draw, "并发 8：尾延迟改善，单位 GPU 效率下降", "128-token 输入 / 64-token 输出；普通 TP=8 使用 8 张 H20，AIBrix P/D 使用 16 张 H20")

    rounded(draw, (65, 145, 1135, 650), fill=WHITE, outline=LINE)
    metric_row(draw, 175, "p95 TTFT ↓", 264.86, 139.56, "ms", 300)
    metric_row(draw, 295, "p95 E2E ↓", 856.39, 681.91, "ms", 900)
    metric_row(draw, 415, "总输出吞吐 ↑", 866.61, 817.95, "tok/s", 900)
    metric_row(draw, 535, "单位 GPU 吞吐 ↑", 108.3, 51.1, "tok/s/GPU", 115)

    rounded(draw, (120, 680, 515, 730), fill=TEAL_LIGHT, outline="#8FD6CA", radius=14)
    rounded(draw, (685, 680, 1080, 730), fill=ORANGE_LIGHT, outline="#F6B58A", radius=14)
    center_text(draw, (120, 680, 515, 730), "p95 TTFT 改善 47.3%", font(19, bold=True), TEAL)
    center_text(draw, (685, 680, 1080, 730), "tok/s/GPU 下降 52.8%", font(19, bold=True), ORANGE)

    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG", optimize=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    architecture(args.output_dir / "01-topology-comparison.png")
    warmup(args.output_dir / "02-warmup-pitfall.png")
    performance(args.output_dir / "03-performance-tradeoff.png")
    print(f"generated figures in: {args.output_dir}")


if __name__ == "__main__":
    main()
