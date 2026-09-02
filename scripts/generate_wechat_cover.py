#!/usr/bin/env python3
"""Generate the default DeepSeek V4 Flash WeChat cover."""

from __future__ import annotations

import argparse
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


WIDTH = 900
HEIGHT = 383
LATIN_BOLD = Path("/System/Library/Fonts/HelveticaNeue.ttc")
CHINESE = Path("/System/Library/Fonts/Hiragino Sans GB.ttc")


def font(path: Path, size: int, index: int = 0) -> ImageFont.FreeTypeFont:
    if not path.exists():
        raise FileNotFoundError(f"font not found: {path}")
    return ImageFont.truetype(str(path), size=size, index=index)


def gradient() -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT))
    pixels = image.load()
    start = (8, 20, 38)
    end = (21, 94, 239)
    for y in range(HEIGHT):
        for x in range(WIDTH):
            ratio = min(1.0, (x / WIDTH) * 0.8 + (y / HEIGHT) * 0.2)
            pixels[x, y] = tuple(round(a + (b - a) * ratio) for a, b in zip(start, end))
    return image


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--kicker", default="AIK8S · 推理工程实战")
    parser.add_argument("--headline", default="DeepSeek V4 Flash × H20")
    parser.add_argument("--subheadline", default="首 Token 快 47%，代价是什么？")
    parser.add_argument("--tags", default="TP=8  ·  P/D 分离  ·  NIXL  ·  AIBrix")
    parser.add_argument("--footer", default="aik8s.run")
    parser.add_argument(
        "--gpu-count",
        type=int,
        choices=(4, 8),
        default=4,
        help="number of accelerator tiles drawn in the cover panel",
    )
    args = parser.parse_args()

    image = gradient()
    draw = ImageDraw.Draw(image, "RGBA")

    draw.ellipse((660, -120, 920, 140), fill=(56, 189, 248, 30))
    draw.ellipse((490, 245, 850, 605), fill=(29, 78, 216, 60))
    for offset in (0, 22, 44):
        points = []
        for x in range(0, WIDTH + 1, 12):
            y = 308 + offset + 18 * math.sin((x - 80) / 95)
            points.append((x, y))
        draw.line(points, fill=(147, 197, 253, 35), width=2)

    draw.text((62, 50), args.kicker, font=font(CHINESE, 20), fill=(147, 197, 253))
    draw.text((58, 105), args.headline, font=font(LATIN_BOLD, 42), fill="white")
    draw.text((62, 169), args.subheadline, font=font(CHINESE, 26), fill=(219, 234, 254))
    draw.text((62, 228), args.tags, font=font(CHINESE, 18), fill=(191, 219, 254))
    draw.rounded_rectangle((62, 279, 348, 282), radius=2, fill=(96, 165, 250))
    draw.text((62, 306), args.footer, font=font(LATIN_BOLD, 16), fill=(147, 197, 253))

    panel = (665, 92, 842, 276)
    draw.rounded_rectangle(panel, radius=20, fill=(7, 17, 31, 185), outline=(96, 165, 250, 150), width=2)
    rows = 2 if args.gpu_count == 4 else 4
    block_height = 54 if rows == 2 else 29
    row_step = 78 if rows == 2 else 39
    start_top = 116 if rows == 2 else 110
    for row in range(rows):
        for column in range(2):
            left = 688 + column * 77
            top = start_top + row * row_step
            right = left + 57
            bottom = top + block_height
            draw.rounded_rectangle(
                (left, top, right, bottom),
                radius=9 if rows == 2 else 7,
                fill=(37, 99, 235, 155),
                outline=(191, 219, 254, 160),
                width=2,
            )
            center = ((left + right) // 2, (top + bottom) // 2)
            draw.ellipse(
                (
                    center[0] - (10 if rows == 2 else 5),
                    center[1] - (10 if rows == 2 else 5),
                    center[0] + (10 if rows == 2 else 5),
                    center[1] + (10 if rows == 2 else 5),
                ),
                fill=(224, 242, 254),
            )
    if rows == 2:
        draw.line((745, 143, 765, 143), fill=(125, 211, 252, 200), width=2)
        draw.line((745, 221, 765, 221), fill=(125, 211, 252, 200), width=2)
        draw.line((716, 170, 716, 194), fill=(125, 211, 252, 200), width=2)
        draw.line((793, 170, 793, 194), fill=(125, 211, 252, 200), width=2)
    else:
        for row in range(rows):
            y = start_top + row * row_step + block_height // 2
            draw.line((745, y, 765, y), fill=(125, 211, 252, 200), width=2)
        for column in range(2):
            x = 716 + column * 77
            for row in range(rows - 1):
                top = start_top + row * row_step + block_height
                bottom = start_top + (row + 1) * row_step
                draw.line((x, top, x, bottom), fill=(125, 211, 252, 200), width=2)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    image.save(args.output, format="PNG", optimize=True)
    print(f"generated: {args.output}")


if __name__ == "__main__":
    main()
