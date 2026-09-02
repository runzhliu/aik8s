#!/usr/bin/env python3
"""Generate Light-mode OpenClaw 2.0 WeChat landscape and square covers."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


LATIN_BOLD = Path("/System/Library/Fonts/HelveticaNeue.ttc")
CHINESE = Path("/System/Library/Fonts/Hiragino Sans GB.ttc")

INK = (20, 27, 45)
MUTED = (82, 92, 113)
RED = (235, 58, 63)
RED_DARK = (194, 38, 45)
CYAN = (21, 168, 189)
PAPER = (249, 248, 244)
WHITE = (255, 255, 255)
LINE = (221, 224, 230)


def font(path: Path, size: int, index: int = 0) -> ImageFont.FreeTypeFont:
    if not path.exists():
        raise FileNotFoundError(f"font not found: {path}")
    return ImageFont.truetype(str(path), size=size, index=index)


def rounded_label(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    *,
    fill: tuple[int, int, int],
    foreground: tuple[int, int, int],
    size: int = 18,
    padding_x: int = 16,
    padding_y: int = 8,
) -> tuple[int, int, int, int]:
    label_font = font(CHINESE, size)
    box = draw.textbbox((0, 0), text, font=label_font)
    width = box[2] - box[0] + padding_x * 2
    height = box[3] - box[1] + padding_y * 2
    left, top = xy
    bounds = (left, top, left + width, top + height)
    draw.rounded_rectangle(bounds, radius=height // 2, fill=fill)
    draw.text(
        (left + padding_x, top + padding_y - box[1]),
        text,
        font=label_font,
        fill=foreground,
    )
    return bounds


def paste_icon(canvas: Image.Image, icon_path: Path, box: tuple[int, int, int, int]) -> None:
    icon = Image.open(icon_path).convert("RGBA")
    width = box[2] - box[0]
    height = box[3] - box[1]
    icon.thumbnail((width, height), Image.Resampling.LANCZOS)
    left = box[0] + (width - icon.width) // 2
    top = box[1] + (height - icon.height) // 2
    canvas.alpha_composite(icon, (left, top))


def add_grid(draw: ImageDraw.ImageDraw, width: int, height: int, step: int) -> None:
    for x in range(0, width, step):
        draw.line((x, 0, x, height), fill=(226, 225, 220, 105), width=1)
    for y in range(0, height, step):
        draw.line((0, y, width, y), fill=(226, 225, 220, 105), width=1)


def draw_landscape(icon_path: Path, output: Path) -> None:
    image = Image.new("RGBA", (900, 383), PAPER + (255,))
    draw = ImageDraw.Draw(image, "RGBA")
    add_grid(draw, 900, 383, 48)

    draw.rounded_rectangle((34, 28, 866, 355), radius=28, fill=WHITE + (235,), outline=LINE, width=2)
    draw.rectangle((34, 28, 46, 355), fill=RED + (255,))

    draw.text((72, 55), "AIK8S · OPENCLAW 实测", font=font(CHINESE, 18), fill=RED_DARK)
    draw.text((68, 101), "OpenClaw 2.0", font=font(LATIN_BOLD, 49), fill=INK)
    draw.text((72, 166), "从聊天 Gateway 到 Agent 协调平面", font=font(CHINESE, 26), fill=INK)
    draw.text((72, 214), "1.x 对比 · Workboard · Headless Agent · 迁移风险", font=font(CHINESE, 17), fill=MUTED)

    rounded_label(draw, (72, 276), "2026.7.1  →  2026.8.1", fill=(254, 233, 233), foreground=RED_DARK)
    draw.text((430, 286), "aik8s.run", font=font(LATIN_BOLD, 16), fill=CYAN)

    draw.rounded_rectangle((640, 65, 828, 257), radius=44, fill=(255, 242, 241), outline=(248, 191, 190), width=2)
    draw.ellipse((670, 91, 800, 221), fill=(255, 255, 255, 230))
    paste_icon(image, icon_path, (677, 95, 795, 225))

    for y, color in ((285, RED), (309, CYAN), (333, INK)):
        draw.ellipse((673, y, 685, y + 12), fill=color + (255,))
        draw.line((693, y + 6, 807, y + 6), fill=color + (110,), width=3)

    output.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(output, format="PNG", optimize=True)


def draw_square(icon_path: Path, output: Path) -> None:
    image = Image.new("RGBA", (900, 900), PAPER + (255,))
    draw = ImageDraw.Draw(image, "RGBA")
    add_grid(draw, 900, 900, 60)

    draw.rounded_rectangle((54, 48, 846, 852), radius=46, fill=WHITE + (238,), outline=LINE, width=2)
    draw.rounded_rectangle((91, 84, 367, 128), radius=22, fill=(254, 233, 233), outline=None)
    draw.text((111, 94), "AIK8S · OPENCLAW 实测", font=font(CHINESE, 19), fill=RED_DARK)

    draw.text((88, 176), "OpenClaw", font=font(LATIN_BOLD, 76), fill=INK)
    draw.text((584, 169), "2.0", font=font(LATIN_BOLD, 88), fill=RED)
    draw.text((92, 281), "它已经不只是", font=font(CHINESE, 35), fill=MUTED)
    draw.text((92, 332), "一个聊天 Gateway", font=font(CHINESE, 46), fill=INK)

    draw.rounded_rectangle((258, 427, 642, 717), radius=72, fill=(255, 242, 241), outline=(248, 191, 190), width=3)
    draw.ellipse((331, 472, 569, 710), fill=(255, 255, 255, 235))
    paste_icon(image, icon_path, (344, 476, 556, 712))

    x = 92
    for text, fill, foreground in (
        ("1.x 对比", (254, 233, 233), RED_DARK),
        ("实操", (226, 247, 250), (13, 116, 133)),
        ("迁移风险", (235, 237, 241), INK),
    ):
        bounds = rounded_label(draw, (x, 759), text, fill=fill, foreground=foreground, size=18)
        x = bounds[2] + 14
    draw.text((700, 773), "aik8s.run", font=font(LATIN_BOLD, 16), fill=CYAN)

    output.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(output, format="PNG", optimize=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--icon", type=Path, required=True)
    parser.add_argument("--landscape", type=Path, required=True)
    parser.add_argument("--square", type=Path, required=True)
    args = parser.parse_args()

    draw_landscape(args.icon, args.landscape)
    draw_square(args.icon, args.square)
    print(f"generated: {args.landscape}")
    print(f"generated: {args.square}")


if __name__ == "__main__":
    main()
