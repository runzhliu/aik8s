#!/usr/bin/env python3
"""Generate exact-data figures for the Qwen3.8-27B WeChat article."""

from __future__ import annotations

import argparse
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


WIDTH = 1200
HEIGHT = 675
FONT_PATH = Path("/System/Library/Fonts/Hiragino Sans GB.ttc")

BG = "#F8FAFC"
INK = "#0F172A"
MUTED = "#64748B"
GRID = "#CBD5E1"
BLUE = "#2563EB"
BLUE_LIGHT = "#DBEAFE"
TEAL = "#0F9F8F"
TEAL_LIGHT = "#CCFBF1"
WHITE = "#FFFFFF"


def font(size: int, index: int = 0) -> ImageFont.FreeTypeFont:
    if not FONT_PATH.exists():
        raise FileNotFoundError(f"font not found: {FONT_PATH}")
    return ImageFont.truetype(str(FONT_PATH), size=size, index=index)


def canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (WIDTH, HEIGHT), BG)
    return image, ImageDraw.Draw(image, "RGBA")


def title(draw: ImageDraw.ImageDraw, heading: str, subtitle: str) -> None:
    draw.text((56, 42), heading, font=font(38), fill=INK)
    draw.text((58, 96), subtitle, font=font(20), fill=MUTED)


def card(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    heading: str,
    lines: list[str],
    *,
    accent: str,
    tint: str,
) -> None:
    left, top, right, bottom = box
    draw.rounded_rectangle(box, radius=20, fill=WHITE, outline=GRID, width=2)
    draw.rounded_rectangle((left, top, right, top + 58), radius=20, fill=tint)
    draw.rectangle((left, top + 38, right, top + 58), fill=tint)
    draw.rectangle((left, top, left + 7, bottom), fill=accent)
    draw.text((left + 26, top + 14), heading, font=font(23), fill=INK)
    for index, line in enumerate(lines):
        draw.text((left + 27, top + 84 + index * 43), line, font=font(19), fill=MUTED)


def arrow(draw: ImageDraw.ImageDraw, start: tuple[int, int], end: tuple[int, int]) -> None:
    draw.line((start, end), fill="#94A3B8", width=4)
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
    draw.polygon((end, left, right), fill="#94A3B8")


def generate_topology(output: Path) -> None:
    image, draw = canvas()
    title(draw, "测试口径", "固定模型、GPU 与客户端，仅切换推理后端")

    card(
        draw,
        (50, 190, 325, 535),
        "模型与硬件",
        ["Qwen3.8-27B-FP8", "1 × NVIDIA L20", "TP=1 · 32K", "FP8 KV · MTP Off", "相同 Model Revision"],
        accent=BLUE,
        tint=BLUE_LIGHT,
    )
    card(
        draw,
        (405, 145, 735, 345),
        "vLLM 0.26.0",
        ["Text-only", "Max Seqs = 8", "Prefix Cache On"],
        accent=BLUE,
        tint=BLUE_LIGHT,
    )
    card(
        draw,
        (405, 390, 735, 590),
        "SGLang 0.5.16",
        ["完整多模态", "Running Slots = 6", "Prefill Graph Off"],
        accent=TEAL,
        tint=TEAL_LIGHT,
    )
    card(
        draw,
        (815, 190, 1150, 535),
        "统一测试客户端",
        ["vllm bench serve", "固定 Tokenizer / Seed", "128/64 · C1/C4/C8", "4096/128 · C4", "448 / 448 成功"],
        accent="#7C3AED",
        tint="#EDE9FE",
    )

    arrow(draw, (325, 315), (405, 245))
    arrow(draw, (325, 410), (405, 490))
    arrow(draw, (735, 245), (815, 315))
    arrow(draw, (735, 490), (815, 410))

    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG", optimize=True)


SCENARIOS = ["128/64 · C1", "128/64 · C4", "128/64 · C8", "4096/128 · C4"]
VLLM_THROUGHPUT = [17.41, 70.84, 134.35, 42.79]
SGLANG_THROUGHPUT = [19.26, 80.12, 112.04, 45.17]
VLLM_TTFT = [116.81, 268.06, 431.89, 4688.75]
SGLANG_TTFT = [225.45, 216.67, 3631.79, 5239.00]


def legend(draw: ImageDraw.ImageDraw, y: int = 134) -> None:
    draw.rounded_rectangle((830, y, 856, y + 18), radius=4, fill=BLUE)
    draw.text((866, y - 5), "vLLM", font=font(18), fill=MUTED)
    draw.rounded_rectangle((965, y, 991, y + 18), radius=4, fill=TEAL)
    draw.text((1001, y - 5), "SGLang", font=font(18), fill=MUTED)


def generate_throughput(output: Path) -> None:
    image, draw = canvas()
    title(draw, "输出吞吐", "相同 vllm bench serve 客户端；单位：token/s")
    legend(draw)

    chart = (90, 185, 1135, 565)
    left, top, right, bottom = chart
    maximum = 150
    for tick in range(0, maximum + 1, 30):
        y = bottom - (tick / maximum) * (bottom - top)
        draw.line((left, y, right, y), fill=GRID, width=1)
        label = str(tick)
        box = draw.textbbox((0, 0), label, font=font(16))
        draw.text((left - 18 - (box[2] - box[0]), y - 10), label, font=font(16), fill=MUTED)

    group_width = (right - left) / len(SCENARIOS)
    bar_width = 68
    for index, scenario in enumerate(SCENARIOS):
        center = left + group_width * (index + 0.5)
        for offset, value, color in (
            (-bar_width - 6, VLLM_THROUGHPUT[index], BLUE),
            (6, SGLANG_THROUGHPUT[index], TEAL),
        ):
            x1 = center + offset
            x2 = x1 + bar_width
            y1 = bottom - (value / maximum) * (bottom - top)
            draw.rounded_rectangle((x1, y1, x2, bottom), radius=8, fill=color)
            label = f"{value:.2f}"
            box = draw.textbbox((0, 0), label, font=font(16))
            draw.text((x1 + (bar_width - (box[2] - box[0])) / 2, y1 - 28), label, font=font(16), fill=INK)
        box = draw.textbbox((0, 0), scenario, font=font(17))
        draw.text((center - (box[2] - box[0]) / 2, bottom + 24), scenario, font=font(17), fill=MUTED)

    draw.text((90, 625), "请求到达率设为 inf，用于观察短时饱和吞吐，不代表线上容量。", font=font(16), fill=MUTED)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG", optimize=True)


def log_x(value: float, left: int, right: int) -> float:
    low = math.log10(100)
    high = math.log10(6000)
    return left + (math.log10(value) - low) / (high - low) * (right - left)


def generate_ttft(output: Path) -> None:
    image, draw = canvas()
    title(draw, "p95 TTFT", "对数坐标；单位：ms，越靠左表示首 Token 等待越短")
    legend(draw)

    left, right = 310, 1120
    top, bottom = 195, 565
    ticks = [100, 300, 1000, 3000, 6000]
    for tick in ticks:
        x = log_x(tick, left, right)
        draw.line((x, top - 20, x, bottom), fill=GRID, width=1)
        label = f"{tick / 1000:g}s" if tick >= 1000 else f"{tick}ms"
        box = draw.textbbox((0, 0), label, font=font(16))
        draw.text((x - (box[2] - box[0]) / 2, bottom + 20), label, font=font(16), fill=MUTED)

    row_gap = 90
    for index, scenario in enumerate(SCENARIOS):
        y = top + index * row_gap + 20
        draw.text((70, y - 14), scenario, font=font(19), fill=INK)
        draw.line((left, y, right, y), fill="#E2E8F0", width=2)
        for offset, value, color in (
            (-13, VLLM_TTFT[index], BLUE),
            (13, SGLANG_TTFT[index], TEAL),
        ):
            x = log_x(value, left, right)
            draw.line((left, y + offset, x, y + offset), fill=color, width=5)
            draw.ellipse((x - 8, y + offset - 8, x + 8, y + offset + 8), fill=color)
            label = f"{value:.2f}"
            label_box = draw.textbbox((0, 0), label, font=font(15))
            label_width = label_box[2] - label_box[0]
            label_x = x + 12 if x + label_width + 12 < right else x - label_width - 12
            label_y = y + offset - 25 if offset < 0 else y + offset + 7
            draw.text((label_x, label_y), label, font=font(15), fill=color)

    draw.text((70, 625), "C8 时 SGLang 只有 6 个 Running Slots；4096/128 测试关闭了 Prefill CUDA Graph。", font=font(16), fill=MUTED)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG", optimize=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    generate_topology(args.output_dir / "qwen38-27b-test-topology.png")
    generate_throughput(args.output_dir / "qwen38-27b-throughput.png")
    generate_ttft(args.output_dir / "qwen38-27b-ttft.png")
    print(f"generated Qwen3.8 WeChat figures in {args.output_dir}")


if __name__ == "__main__":
    main()
