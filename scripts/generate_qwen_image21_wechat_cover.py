#!/usr/bin/env python3
"""Generate Qwen-Image-2.1 covers in the Qwen3.8/Kimi K3 house style."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


CHINESE = Path("/System/Library/Fonts/Hiragino Sans GB.ttc")
LATIN = Path("/System/Library/Fonts/HelveticaNeue.ttc")

INK = (14, 28, 48)
MUTED = (75, 97, 125)
BLUE = (10, 46, 254)
PURPLE = (112, 87, 217)
PAPER = (246, 248, 255)
WHITE = (255, 255, 255)
LINE = (211, 220, 237)
PALE_BLUE = (232, 235, 255)
PALE_PURPLE = (239, 234, 254)


def font(size: int, *, bold: bool = False, latin: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(
        str(LATIN if latin else CHINESE), size=size, index=1 if bold else 0
    )


def add_grid(draw: ImageDraw.ImageDraw, width: int, height: int, step: int) -> None:
    for x in range(0, width, step):
        draw.line((x, 0, x, height), fill=(228, 233, 246), width=1)
    for y in range(0, height, step):
        draw.line((0, y, width, y), fill=(228, 233, 246), width=1)


def text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    value: str,
    size: int,
    *,
    fill=INK,
    bold: bool = False,
    latin: bool = False,
) -> None:
    draw.text(xy, value, font=font(size, bold=bold, latin=latin), fill=fill)


def center(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    value: str,
    size: int,
    *,
    fill=INK,
    bold: bool = False,
    latin: bool = False,
) -> None:
    fnt = font(size, bold=bold, latin=latin)
    measured = draw.textbbox((0, 0), value, font=fnt)
    width = measured[2] - measured[0]
    height = measured[3] - measured[1]
    x = box[0] + (box[2] - box[0] - width) / 2 - measured[0]
    y = box[1] + (box[3] - box[1] - height) / 2 - measured[1]
    draw.text((x, y), value, font=fnt, fill=fill)


def pill(draw: ImageDraw.ImageDraw, xy: tuple[int, int], label: str, size: int) -> None:
    fnt = font(size, bold=True, latin=True)
    measured = draw.textbbox((0, 0), label, font=fnt)
    width = measured[2] - measured[0] + 34
    height = measured[3] - measured[1] + 18
    left, top = xy
    draw.rounded_rectangle(
        (left, top, left + width, top + height),
        radius=height // 2,
        fill=PALE_BLUE,
        outline=(161, 177, 255),
    )
    draw.text(
        (left + 17, top + 9 - measured[1]), label, font=fnt, fill=BLUE
    )


def runtime_diagram(
    draw: ImageDraw.ImageDraw,
    bounds: tuple[int, int, int, int],
    *,
    scale: float,
) -> None:
    left, top, right, bottom = bounds
    width = right - left
    engine_w = round(132 * scale)
    engine_h = round(58 * scale)
    gap = round(30 * scale)
    first_x = left + (width - (engine_w * 2 + gap)) // 2
    second_x = first_x + engine_w + gap
    engine_y = top + round(10 * scale)

    for x, label, color, pale in (
        (first_x, "SGLang", BLUE, PALE_BLUE),
        (second_x, "vLLM-Omni", PURPLE, PALE_PURPLE),
    ):
        draw.rounded_rectangle(
            (x, engine_y, x + engine_w, engine_y + engine_h),
            radius=round(12 * scale),
            fill=pale,
            outline=color,
            width=max(2, round(2 * scale)),
        )
        center(
            draw,
            (x, engine_y, x + engine_w, engine_y + engine_h),
            label,
            max(12, round(15 * scale)),
            fill=color,
            bold=True,
            latin=True,
        )

    model_w = round(166 * scale)
    model_h = round(78 * scale)
    model_x = left + (width - model_w) // 2
    model_y = top + round(103 * scale)
    model_center = model_x + model_w // 2
    for x, color in (
        (first_x + engine_w // 2, BLUE),
        (second_x + engine_w // 2, PURPLE),
    ):
        draw.line(
            (x, engine_y + engine_h, x, model_y - round(12 * scale)),
            fill=color,
            width=max(2, round(2 * scale)),
        )
        draw.line(
            (x, model_y - round(12 * scale), model_center, model_y),
            fill=color,
            width=max(2, round(2 * scale)),
        )
    draw.rounded_rectangle(
        (model_x, model_y, model_x + model_w, model_y + model_h),
        radius=round(16 * scale),
        fill=INK,
    )
    center(
        draw,
        (model_x, model_y + round(3 * scale), model_x + model_w, model_y + round(42 * scale)),
        "Qwen Image",
        max(13, round(17 * scale)),
        fill=WHITE,
        bold=True,
        latin=True,
    )
    center(
        draw,
        (model_x, model_y + round(38 * scale), model_x + model_w, model_y + model_h - round(3 * scale)),
        "7B DiT",
        max(11, round(13 * scale)),
        fill=(206, 216, 245),
        bold=True,
        latin=True,
    )

    branch_y = model_y + model_h + round(17 * scale)
    draw.line(
        (model_center, model_y + model_h, model_center, branch_y),
        fill=MUTED,
        width=max(2, round(2 * scale)),
    )
    centers = [
        left + round(width * 0.22),
        left + round(width * 0.50),
        left + round(width * 0.78),
    ]
    output_specs = [
        ("1:1", round(54 * scale), round(54 * scale), BLUE),
        ("4:3", round(66 * scale), round(50 * scale), PURPLE),
        ("9:16", round(40 * scale), round(70 * scale), BLUE),
    ]
    draw.line(
        (centers[0], branch_y, centers[-1], branch_y),
        fill=MUTED,
        width=max(1, round(2 * scale)),
    )
    output_top = branch_y + round(14 * scale)
    for output_center, (label, card_w, card_h, color) in zip(centers, output_specs):
        draw.line(
            (output_center, branch_y, output_center, output_top),
            fill=MUTED,
            width=max(1, round(2 * scale)),
        )
        x0 = output_center - card_w // 2
        draw.rounded_rectangle(
            (x0, output_top, x0 + card_w, output_top + card_h),
            radius=max(5, round(8 * scale)),
            fill=WHITE,
            outline=color,
            width=max(1, round(2 * scale)),
        )
        center(
            draw,
            (x0, output_top, x0 + card_w, output_top + card_h),
            label,
            max(10, round(12 * scale)),
            fill=color,
            bold=True,
            latin=True,
        )
def wide(output: Path) -> None:
    image = Image.new("RGB", (900, 383), PAPER)
    draw = ImageDraw.Draw(image)
    add_grid(draw, 900, 383, 42)
    draw.rounded_rectangle((30, 24, 870, 359), radius=26, fill=WHITE, outline=LINE, width=2)
    draw.rectangle((30, 24, 42, 359), fill=BLUE)
    text(draw, (72, 48), "7B DiT · 单卡 L20 · 原生 2K", 16, fill=BLUE, bold=True)
    text(draw, (68, 87), "Qwen-Image-2.1", 43, bold=True, latin=True)
    text(draw, (70, 143), "双引擎实测", 37, bold=True)
    pill(draw, (70, 211), "SGLang × vLLM-Omni", 18)
    text(draw, (70, 273), "7 种画幅 · 图片编辑 · 性能数据", 17, fill=MUTED)
    text(draw, (70, 319), "AIK8S.RUN", 13, fill=PURPLE, bold=True, latin=True)
    runtime_diagram(draw, (500, 48, 836, 329), scale=0.78)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG", optimize=True)


def square(output: Path) -> None:
    image = Image.new("RGB", (900, 900), PAPER)
    draw = ImageDraw.Draw(image)
    add_grid(draw, 900, 900, 56)
    draw.rounded_rectangle((52, 46, 848, 854), radius=42, fill=WHITE, outline=LINE, width=2)
    draw.rectangle((52, 46, 64, 854), fill=BLUE)
    text(draw, (90, 93), "7B DiT · 单卡 L20 · 原生 2K", 22, fill=BLUE, bold=True)
    text(draw, (86, 151), "Qwen-Image-2.1", 59, bold=True, latin=True)
    text(draw, (90, 241), "双引擎实测", 58, bold=True)
    runtime_diagram(draw, (132, 365, 768, 674), scale=1.12)
    pill(draw, (90, 743), "SGLang × vLLM-Omni", 23)
    text(draw, (486, 757), "7 种画幅 · 图片编辑", 20, fill=MUTED)
    text(draw, (714, 811), "AIK8S.RUN", 13, fill=PURPLE, bold=True, latin=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG", optimize=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    # Retained for compatibility with the previous photo-cover command.
    parser.add_argument("--primary", type=Path)
    parser.add_argument("--secondary", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    wide(args.output_dir / "cover.png")
    square(args.output_dir / "cover-square.png")
    print(args.output_dir)


if __name__ == "__main__":
    main()
