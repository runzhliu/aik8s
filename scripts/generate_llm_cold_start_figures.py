#!/usr/bin/env python3
"""Generate explanatory figures for the LLM cold-start article."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


WIDTH = 1200
BG = "#F7F9FC"
WHITE = "#FFFFFF"
INK = "#172033"
MUTED = "#5E6B82"
LINE = "#C9D4E6"
BLUE = "#2563EB"
BLUE_DARK = "#1749B5"
BLUE_LIGHT = "#EAF2FF"
TEAL = "#0F9D8A"
TEAL_LIGHT = "#E7F8F5"
ORANGE = "#F37726"
ORANGE_LIGHT = "#FFF1E8"
PURPLE = "#7C3AED"
PURPLE_LIGHT = "#F1EAFF"
RED = "#D94B5B"

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


def heading(draw: ImageDraw.ImageDraw, title: str, subtitle: str) -> None:
    draw.text((55, 38), title, font=font(42, bold=True), fill=INK)
    draw.text((57, 100), subtitle, font=font(24), fill=MUTED)


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


def cold_start_pipeline(output: Path) -> None:
    image, draw = canvas(1020)
    heading(draw, "大模型冷启动不是一次下载", "模型到达节点以后，权重处理、现场编译和 CUDA Graph 仍可能轮流成为关键路径")

    stages = [
        ("调度与镜像", "Pod 调度\nRuntime Image", BLUE_LIGHT, BLUE_DARK),
        ("模型准备", "远端模型\n节点本地缓存", TEAL_LIGHT, TEAL),
        ("权重加载", "读取与解析\n重排 / H2D", ORANGE_LIGHT, ORANGE),
        ("运行时准备", "NCCL / KV Cache\n显存 Profile", PURPLE_LIGHT, PURPLE),
        ("编译与预热", "Kernel JIT\nCUDA Graph", "#FFF4E5", "#C96A12"),
        ("业务可用", "确定性请求通过\nGateway 接流量", "#E8F7EC", "#18864B"),
    ]

    left, top, card_w, card_h, gap_x, gap_y = 60, 175, 330, 255, 45, 65
    for index, (label, body, fill, color) in enumerate(stages):
        row, logical_column = divmod(index, 3)
        column = logical_column if row == 0 else 2 - logical_column
        x = left + column * (card_w + gap_x)
        y = top + row * (card_h + gap_y)
        rounded(draw, (x, y, x + card_w, y + card_h), fill=WHITE, outline=color, radius=18, width=3)
        draw.rounded_rectangle((x + 40, y + 22, x + card_w - 40, y + 72), radius=14, fill=fill)
        center_text(draw, (x + 40, y + 22, x + card_w - 40, y + 72), label, font(24, bold=True), color)
        center_text(draw, (x + 25, y + 92, x + card_w - 25, y + 188), body, font(26, bold=True), INK)
        center_text(draw, (x + 120, y + 202, x + 210, y + 238), f"T{index * 2}", font(21, bold=True, latin=True), MUTED)
        if row == 0 and column < 2:
            arrow(draw, (x + card_w + 6, y + 128), (x + card_w + gap_x - 8, y + 128), color=LINE, width=5)
        elif row == 1 and logical_column < 2:
            start_x = x - 6
            end_x = x - gap_x + 8
            draw.line((start_x, y + 128, end_x, y + 128), fill=LINE, width=5)
            draw.polygon(((end_x, y + 128), (end_x + 12, y + 120), (end_x + 12, y + 136)), fill=LINE)
        elif row == 0:
            draw.line((x + card_w / 2, y + card_h + 6, x + card_w / 2, y + card_h + gap_y - 10), fill=LINE, width=5)
            ey = y + card_h + gap_y - 10
            ex = x + card_w / 2
            draw.polygon(((ex, ey), (ex - 8, ey - 12), (ex + 8, ey - 12)), fill=LINE)

    rounded(draw, (60, 830, 1140, 945), fill=WHITE, outline=LINE)
    draw.text((90, 858), "优化原则", font=font(27, bold=True), fill=INK)
    principles = [
        ("缓存", "消除重复下载", BLUE),
        ("预分片", "减少无效读取与转换", TEAL),
        ("预编译", "复用 CUBIN / SO", ORANGE),
        ("收敛形状", "减少 Graph 形状", PURPLE),
        ("热副本", "RTO 与冷启动解耦", RED),
    ]
    for index, (label, detail, color) in enumerate(principles):
        x = 245 + index * 178
        draw.ellipse((x, 858, x + 26, 884), fill=color)
        draw.text((x + 36, 851), label, font=font(21, bold=True), fill=INK)
        center_text(draw, (x - 18, 895, x + 165, 930), detail, font(18), MUTED)

    center_text(draw, (80, 958, 1120, 1005), "目标不是某个最快数字，而是让每个阶段都有可观测、可缓存、可回退的时间预算", font(23, bold=True), INK)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG", optimize=True)


def storage_ab(output: Path) -> None:
    image, draw = canvas(760)
    heading(draw, "根盘与 NVMe：存储收益要和编译缓存分开看", "同规格 8×H20、SGLang Combined TP=8；模型约 166.9 GB，均已命中节点缓存")

    rounded(draw, (55, 145, 1145, 610), fill=WHITE, outline=LINE)
    draw.text((95, 180), "框架内部权重加载", font=font(30, bold=True), fill=INK)
    draw.text((96, 230), "这个阶段更接近存储 A/B 的可信边界", font=font(22), fill=MUTED)

    bar_left, bar_right = 360, 1040
    scale = (bar_right - bar_left) / 300
    rows = [
        ("双盘 NVMe 条带", 246.7, TEAL, TEAL_LIGHT),
        ("系统根盘 /tmp", 275.8, BLUE, BLUE_LIGHT),
    ]
    for index, (label, value, color, light) in enumerate(rows):
        y = 285 + index * 105
        draw.text((95, y + 8), label, font=font(25, bold=True), fill=INK)
        draw.rounded_rectangle((bar_left, y, bar_right, y + 48), radius=15, fill="#E8EDF5")
        draw.rounded_rectangle((bar_left, y, bar_left + int(value * scale), y + 48), radius=15, fill=color)
        draw.rounded_rectangle((915, y + 4, 1110, y + 44), radius=12, fill=light)
        center_text(draw, (915, y + 4, 1110, y + 44), f"{value:.1f} 秒", font(23, bold=True), color)

    rounded(draw, (95, 500, 550, 570), fill=TEAL_LIGHT, outline="#8FD6CA", radius=14)
    center_text(draw, (95, 500, 550, 570), "NVMe 快约 29.1 秒 · 10.5%", font(25, bold=True), TEAL)
    rounded(draw, (585, 500, 1105, 570), fill=ORANGE_LIGHT, outline="#F6B58A", radius=14)
    center_text(draw, (585, 500, 1105, 570), "Load weight 还包含解析、转换与 H2D", font(22, bold=True), ORANGE)

    rounded(draw, (55, 640, 1145, 725), fill="#111A2E", outline="#111A2E", radius=16)
    center_text(
        draw,
        (85, 650, 1115, 713),
        "整体 Ready：NVMe 320 秒，根盘 700 秒\n但 CUDA Graph Cache 状态不同，这 380 秒不能全部算作 NVMe 收益",
        font(23, bold=True),
        WHITE,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG", optimize=True)


def optimization_ladder(output: Path) -> None:
    image, draw = canvas(720)
    heading(draw, "从半小时到分钟级，再到秒级恢复", "不同目标对应不同技术起点，不能把热恢复包装成完整冷启动")

    levels = [
        ("10–30 分钟", "完整冷启动", "远端模型、镜像、编译缓存均未命中", RED, 0),
        ("7–11 分钟", "节点缓存命中", "模型在本地，但仍现场转换、JIT 与 Graph", ORANGE, 55),
        ("2–5 分钟", "工程优化目标", "NVMe + 预分片 + 编译缓存 + 收敛 Graph", BLUE, 110),
        ("45–120 秒", "激进加载路径", "充分流水、流式 Loader、GDS 或 P2P", TEAL, 165),
        ("数秒级", "热恢复", "热副本、Sleep Mode 或 GPU 状态快照", PURPLE, 220),
    ]

    for index, (time, label, detail, color, indent) in enumerate(levels):
        y = 155 + index * 98
        x = 70 + indent
        width = 1060 - indent * 2
        rounded(draw, (x, y, x + width, y + 72), fill=WHITE, outline=color, radius=16, width=3)
        draw.rounded_rectangle((x + 18, y + 14, x + 205, y + 58), radius=12, fill=color)
        center_text(draw, (x + 18, y + 14, x + 205, y + 58), time, font(22, bold=True), WHITE)
        draw.text((x + 230, y + 8), label, font=font(24, bold=True), fill=INK)
        draw.text((x + 230, y + 42), detail, font=font(19), fill=MUTED)

    rounded(draw, (160, 660, 1040, 705), fill="#111A2E", outline="#111A2E", radius=14)
    center_text(draw, (160, 660, 1040, 705), "完整冷启动时间不能直接成为业务 RTO", font(25, bold=True), WHITE)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG", optimize=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    cold_start_pipeline(args.output_dir / "01-cold-start-pipeline.png")
    storage_ab(args.output_dir / "02-root-disk-vs-nvme.png")
    optimization_ladder(args.output_dir / "03-optimization-ladder.png")
    print(f"generated figures in: {args.output_dir}")


if __name__ == "__main__":
    main()
