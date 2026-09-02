#!/usr/bin/env python3
"""Generate the GLM-5.2 P/D RDMA WeChat cover and exact-data figures."""

from __future__ import annotations

import argparse
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


WIDTH = 1200
BG = "#F7F9FC"
INK = "#172033"
MUTED = "#5E6B82"
LINE = "#CBD5E1"
WHITE = "#FFFFFF"
BLUE = "#1677FF"
BLUE_DARK = "#124AA3"
BLUE_LIGHT = "#E8F2FF"
CYAN = "#06B6D4"
CYAN_LIGHT = "#E6FAFD"
TEAL = "#0F9D8A"
TEAL_LIGHT = "#E7F8F5"
ORANGE = "#F37726"
ORANGE_LIGHT = "#FFF1E8"
RED = "#D94B5B"

FONT_CN = Path("/System/Library/Fonts/Hiragino Sans GB.ttc")
FONT_LATIN = Path("/System/Library/Fonts/HelveticaNeue.ttc")


def font(size: int, *, bold: bool = False, latin: bool = False) -> ImageFont.FreeTypeFont:
    path = FONT_LATIN if latin else FONT_CN
    index = 1 if bold and path == FONT_CN else 0
    if not path.exists():
        raise FileNotFoundError(f"font not found: {path}")
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
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    size = 14
    left = (
        end[0] - size * math.cos(angle - math.pi / 6),
        end[1] - size * math.sin(angle - math.pi / 6),
    )
    right = (
        end[0] - size * math.cos(angle + math.pi / 6),
        end[1] - size * math.sin(angle + math.pi / 6),
    )
    draw.polygon((end, left, right), fill=color)


def gpu_row(draw: ImageDraw.ImageDraw, left: int, top: int, *, color: str) -> None:
    for gpu in range(8):
        x = left + gpu * 22
        draw.rounded_rectangle((x, top, x + 17, top + 17), radius=4, fill=color)


def generate_cover(background: Path, output: Path) -> None:
    source = Image.open(background).convert("RGB")
    image = ImageOps.fit(source, (900, 383), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    overlay_pixels = overlay.load()
    for x in range(650):
        ratio = x / 650
        alpha = round(205 * (1 - ratio) ** 1.8)
        for y in range(383):
            overlay_pixels[x, y] = (3, 13, 29, alpha)
    image = Image.alpha_composite(image.convert("RGBA"), overlay)
    draw = ImageDraw.Draw(image, "RGBA")

    draw.rounded_rectangle((48, 34, 275, 66), radius=16, fill=(8, 44, 78, 210), outline=(80, 207, 232, 150), width=1)
    draw.text((65, 41), "AIK8S · 推理工程实测", font=font(16, bold=True), fill="#A5F3FC")
    draw.rectangle((48, 93, 54, 196), fill=CYAN)
    draw.text((70, 88), "KV 传输快了 22 倍", font=font(34, bold=True), fill=WHITE)
    draw.text((70, 139), "短请求却更慢？", font=font(32, bold=True), fill="#D8F7FF")
    draw.text((70, 213), "GLM-5.2 · P/D 分离 · TCP vs RDMA", font=font(19, bold=True), fill="#A5D8FF")
    draw.text((70, 253), "长 Prompt 吞吐 +22%  ·  p95 TTFT -28%", font=font(18), fill="#DCEBFA")
    draw.text((70, 326), "aik8s.run", font=font(15, bold=True, latin=True), fill="#83D9EE")

    output.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(output, format="PNG", optimize=True)


def generate_topology(output: Path) -> None:
    image, draw = canvas(650)
    title(draw, "同一套 P/D Engine，只切换 KV 数据面", "模型、节点、TP、路由和请求集保持不变；TCP 与 RDMA 串行 A/B")

    rounded(draw, (45, 215, 205, 445), fill=WHITE, outline="#AFC8F7")
    center_text(draw, (55, 235, 195, 315), "Benchmark\nClient", font(22, bold=True), BLUE_DARK)
    center_text(draw, (55, 330, 195, 405), "固定 Tokenizer\nSeed / 长度 / 并发", font(16), MUTED)

    rounded(draw, (255, 215, 445, 445), fill="#F3F0FF", outline="#C4B5FD")
    center_text(draw, (265, 235, 435, 315), "AIBrix\nP/D Router", font(22, bold=True), "#6D28D9")
    center_text(draw, (265, 330, 435, 405), "选择 Prefill\n与 Decode", font(17), MUTED)

    rounded(draw, (500, 175, 715, 485), fill=BLUE_LIGHT, outline="#8FB1F0")
    center_text(draw, (520, 195, 695, 285), "Prefill\nTP=8", font(28, bold=True), BLUE_DARK)
    center_text(draw, (520, 300, 695, 350), "8 × H20 141 GB", font(17, bold=True), BLUE_DARK)
    gpu_row(draw, 520, 385, color=BLUE)
    center_text(draw, (520, 420, 695, 460), "生成 KV Cache", font(17), MUTED)

    rounded(draw, (985, 175, 1165, 485), fill=TEAL_LIGHT, outline="#8FD6CA")
    center_text(draw, (1000, 195, 1150, 285), "Decode\nTP=8", font(28, bold=True), TEAL)
    center_text(draw, (1000, 300, 1150, 350), "8 × H20 141 GB", font(17, bold=True), TEAL)
    gpu_row(draw, 990, 385, color=TEAL)
    center_text(draw, (1000, 420, 1150, 460), "继续生成 Token", font(17), MUTED)

    arrow(draw, (205, 330), (245, 330), color="#94A3B8")
    arrow(draw, (445, 330), (490, 330), color="#94A3B8")

    draw.rounded_rectangle((750, 245, 950, 315), radius=14, fill=ORANGE_LIGHT, outline="#F5B183", width=2)
    draw.text((770, 260), "TCP 对照", font=font(18, bold=True), fill=ORANGE)
    draw.text((770, 286), "0.241 GB/s", font=font(17, bold=True, latin=True), fill=INK)
    arrow(draw, (715, 280), (975, 280), color=ORANGE, width=4)

    draw.rounded_rectangle((750, 355, 950, 425), radius=14, fill=CYAN_LIGHT, outline="#77D9E8", width=2)
    draw.text((770, 370), "RDMA", font=font(18, bold=True), fill="#078AA2")
    draw.text((770, 396), "5.28 GB/s", font=font(17, bold=True, latin=True), fill=INK)
    arrow(draw, (715, 390), (975, 390), color=CYAN, width=7)

    rounded(draw, (120, 535, 1080, 605), fill=WHITE, outline=LINE, radius=16)
    center_text(draw, (130, 545, 1070, 595), "唯一实验变量：UCX 传输层  ·  两种路径均完成全部请求且没有传输失败", font(19, bold=True), INK)

    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG", optimize=True)


def generate_kv_rate(output: Path) -> None:
    image, draw = canvas(650)
    title(draw, "KV Cache 传输：RDMA 的 Rank 聚合有效速率约为 TCP 的 21.9 倍", "NIXL 同规模完整轮次；单位 GB/s，数值用于同拓扑 A/B，不是单网卡物理线速")

    rounded(draw, (60, 145, 1140, 470), fill=WHITE, outline=LINE)
    bar_left, bar_right = 260, 1080
    maximum = 5.5
    rows = [("TCP", 0.241, ORANGE, 245), ("RDMA", 5.28, CYAN, 365)]
    for label, value, color, y in rows:
        draw.text((105, y - 9), label, font=font(24, bold=True, latin=True), fill=INK)
        draw.rounded_rectangle((bar_left, y, bar_right, y + 42), radius=20, fill="#E8EDF4")
        width = max(14, round((bar_right - bar_left) * value / maximum))
        draw.rounded_rectangle((bar_left, y, bar_left + width, y + 42), radius=20, fill=color)
        draw.text((bar_left + width + 16, y + 2), f"{value:.3f}" if value < 1 else f"{value:.2f}", font=font(22, bold=True, latin=True), fill=color)

    draw.rounded_rectangle((835, 165, 1085, 218), radius=24, fill="#DDF8FC", outline="#7BDDEB", width=2)
    center_text(draw, (835, 165, 1085, 218), "21.9×", font(28, bold=True, latin=True), "#078AA2")

    checks = [
        ("NIXL", "两种路径均 0 失败"),
        ("RDMA 计数器", "RDMA 轮次同步增长"),
        ("TCP 隔离", "TCP 轮次完全不增长"),
    ]
    for index, (heading, body) in enumerate(checks):
        left = 60 + index * 360
        rounded(draw, (left, 505, left + 330, 610), fill=CYAN_LIGHT if index == 1 else WHITE, outline="#9FDDE8" if index == 1 else LINE, radius=16)
        draw.ellipse((left + 22, 529, left + 54, 561), fill=TEAL)
        draw.line((left + 31, 545, left + 37, 552), fill=WHITE, width=3)
        draw.line((left + 37, 552, left + 48, 537), fill=WHITE, width=3)
        draw.text((left + 70, 521), heading, font=font(18, bold=True), fill=INK)
        draw.text((left + 70, 556), body, font=font(16), fill=MUTED)

    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG", optimize=True)


def metric_chip(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    label: str,
    value: str,
    *,
    good: bool,
) -> None:
    fill = TEAL_LIGHT if good else ORANGE_LIGHT
    outline = "#8FD6CA" if good else "#F5B183"
    color = TEAL if good else ORANGE
    rounded(draw, box, fill=fill, outline=outline, radius=14)
    left, top, right, bottom = box
    draw.text((left + 18, top + 13), label, font=font(17, bold=True), fill=MUTED)
    value_box = draw.textbbox((0, 0), value, font=font(25, bold=True, latin=True))
    draw.text((right - 18 - (value_box[2] - value_box[0]), top + 8), value, font=font(25, bold=True, latin=True), fill=color)


def generate_tradeoff(output: Path) -> None:
    image, draw = canvas(735)
    title(draw, "同样打开 RDMA，为什么一个场景变快、另一个却变慢？", "两轮均值；吞吐越高越好，TTFT / E2E 越低越好")

    rounded(draw, (55, 145, 570, 620), fill=WHITE, outline="#F5B183")
    draw.rounded_rectangle((55, 145, 570, 220), radius=20, fill=ORANGE_LIGHT)
    draw.rectangle((55, 200, 570, 220), fill=ORANGE_LIGHT)
    draw.text((85, 166), "短 Prompt · 128/64 · C=8", font=font(24, bold=True), fill=INK)
    draw.text((85, 244), "当前 RDMA 配置回退", font=font(20, bold=True), fill=ORANGE)
    metric_chip(draw, (85, 300, 540, 360), "输出吞吐", "-11.1%", good=False)
    metric_chip(draw, (85, 385, 540, 445), "p95 TTFT", "+257.2%", good=False)
    metric_chip(draw, (85, 470, 540, 530), "p95 E2E", "+96.5%", good=False)
    center_text(draw, (85, 552, 540, 600), "KV 较小，排队与 P/D 协调覆盖网络收益", font(17), MUTED)

    rounded(draw, (630, 145, 1145, 620), fill=WHITE, outline="#8FD6CA")
    draw.rounded_rectangle((630, 145, 1145, 220), radius=20, fill=TEAL_LIGHT)
    draw.rectangle((630, 200, 1145, 220), fill=TEAL_LIGHT)
    draw.text((660, 166), "长 Prompt · 4096/128 · C=4", font=font(24, bold=True), fill=INK)
    draw.text((660, 244), "两轮方向一致，RDMA 获益", font=font(20, bold=True), fill=TEAL)
    metric_chip(draw, (660, 300, 1115, 360), "输出吞吐", "+22.0%", good=True)
    metric_chip(draw, (660, 385, 1115, 445), "p95 TTFT", "-27.8%", good=True)
    metric_chip(draw, (660, 470, 1115, 530), "p95 E2E", "-19.2%", good=True)
    center_text(draw, (660, 552, 1115, 600), "KV 更大，传输进入端到端关键路径", font(17), MUTED)

    rounded(draw, (250, 660, 950, 712), fill="#EEF2FF", outline="#C7D2FE", radius=16)
    center_text(draw, (250, 660, 950, 712), "KV 传输更快  ≠  每一种请求都更快", font(22, bold=True), "#4338CA")

    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG", optimize=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cover-background", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    generate_cover(args.cover_background, args.output_dir / "glm52-pd-rdma-cover.png")
    generate_topology(args.output_dir / "glm52-pd-rdma-topology.png")
    generate_kv_rate(args.output_dir / "glm52-pd-rdma-kv-rate.png")
    generate_tradeoff(args.output_dir / "glm52-pd-rdma-workload-tradeoff.png")
    print(f"generated GLM-5.2 P/D RDMA assets in {args.output_dir}")


if __name__ == "__main__":
    main()
