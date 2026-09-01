#!/usr/bin/env python3
"""Compose landscape and square Hy4-preview WeChat covers."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "articles/wechat/assets/hy4-preview-h20"
BACKGROUND = ASSET_DIR / "cover-background-3d.png"
LANDSCAPE_OUTPUT = ROOT / "articles/wechat/assets/hy4-preview-h20-cover.png"
SQUARE_OUTPUT = ROOT / "articles/wechat/assets/hy4-preview-h20-cover-square.png"

CHINESE = Path("/System/Library/Fonts/Hiragino Sans GB.ttc")
LATIN = Path("/System/Library/Fonts/HelveticaNeue.ttc")

WHITE = (246, 250, 255)
SECONDARY = (172, 211, 255)
BLUE = (58, 148, 255)
ORANGE = (255, 151, 60)
NAVY = (2, 11, 31)


def font(path: Path, size: int, index: int = 0) -> ImageFont.FreeTypeFont:
    if not path.exists():
        raise FileNotFoundError(f"font not found: {path}")
    return ImageFont.truetype(str(path), size=size, index=index)


def horizontal_panel(image: Image.Image) -> Image.Image:
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    solid_until = 350
    fade_until = 610
    for x in range(fade_until):
        if x <= solid_until:
            alpha = 246
        else:
            progress = (x - solid_until) / (fade_until - solid_until)
            alpha = round(246 * (1.0 - progress) ** 1.7)
        draw.line((x, 0, x, image.height), fill=(*NAVY, alpha))
    return Image.alpha_composite(image.convert("RGBA"), overlay)


def square_panel(image: Image.Image) -> Image.Image:
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    solid_until = 390
    fade_until = 650
    for y in range(fade_until):
        if y <= solid_until:
            alpha = 238
        else:
            progress = (y - solid_until) / (fade_until - solid_until)
            alpha = round(238 * (1.0 - progress) ** 1.7)
        draw.line((0, y, image.width, y), fill=(*NAVY, alpha))
    return Image.alpha_composite(image.convert("RGBA"), overlay)


def pill(
    draw: ImageDraw.ImageDraw,
    bounds: tuple[int, int, int, int],
    label: str,
    label_font: ImageFont.FreeTypeFont,
) -> None:
    draw.rounded_rectangle(
        bounds,
        radius=(bounds[3] - bounds[1]) // 2,
        fill=(*BLUE, 35),
        outline=(*BLUE, 170),
        width=1,
    )
    draw.text(
        (bounds[0] + 16, bounds[1] + 7),
        label,
        font=label_font,
        fill=(*WHITE, 255),
    )


def compose_landscape() -> Path:
    with Image.open(BACKGROUND) as source:
        fitted = ImageOps.fit(
            source.convert("RGB"),
            (900, 383),
            method=Image.Resampling.LANCZOS,
            centering=(0.50, 0.54),
        )
    image = horizontal_panel(fitted)
    draw = ImageDraw.Draw(image, "RGBA")

    x = 45
    draw.rounded_rectangle((x, 30, x + 8, 47), radius=4, fill=(*ORANGE, 255))
    draw.text(
        (x + 18, 29),
        "BF16  ·  16×H20  ·  RDMA",
        font=font(LATIN, 15, index=1),
        fill=(*SECONDARY, 255),
    )
    draw.text((x, 72), "Hy4-preview", font=font(LATIN, 38, index=1), fill=(*WHITE, 255))
    draw.text((x, 119), "双机 H20 实测", font=font(CHINESE, 37), fill=(*WHITE, 255))

    pill(draw, (x, 190, x + 218, 229), "SGLang × vLLM", font(LATIN, 20, index=1))
    draw.text(
        (x, 252),
        "6,728 请求  ·  0 失败",
        font=font(CHINESE, 17),
        fill=(*SECONDARY, 255),
    )
    draw.line((x, 303, x + 245, 303), fill=(*ORANGE, 220), width=3)
    draw.text((x, 326), "AIK8S.RUN", font=font(LATIN, 12, index=1), fill=(*SECONDARY, 235))

    image.convert("RGB").save(LANDSCAPE_OUTPUT, format="PNG", optimize=True)
    return LANDSCAPE_OUTPUT


def compose_square() -> Path:
    with Image.open(BACKGROUND) as source:
        fitted = ImageOps.fit(
            source.convert("RGB"),
            (900, 900),
            method=Image.Resampling.LANCZOS,
            centering=(0.62, 0.50),
        )
    image = square_panel(fitted)
    draw = ImageDraw.Draw(image, "RGBA")

    x = 58
    draw.rounded_rectangle((x, 52, x + 11, 75), radius=5, fill=(*ORANGE, 255))
    draw.text(
        (x + 25, 50),
        "BF16  ·  16×H20  ·  RDMA",
        font=font(LATIN, 22, index=1),
        fill=(*SECONDARY, 255),
    )
    draw.text((x, 109), "Hy4-preview", font=font(LATIN, 67, index=1), fill=(*WHITE, 255))
    draw.text((x, 191), "双机 H20 实测", font=font(CHINESE, 57), fill=(*WHITE, 255))

    pill(draw, (x, 288, x + 322, 344), "SGLang × vLLM", font(LATIN, 29, index=1))
    draw.text(
        (x, 380),
        "6,728 请求  ·  0 失败",
        font=font(CHINESE, 25),
        fill=(*SECONDARY, 255),
    )
    draw.line((x, 441, x + 374, 441), fill=(*ORANGE, 220), width=5)
    draw.text((x, 468), "AIK8S.RUN", font=font(LATIN, 18, index=1), fill=(*SECONDARY, 235))

    image.convert("RGB").save(SQUARE_OUTPUT, format="PNG", optimize=True)
    return SQUARE_OUTPUT


def main() -> None:
    print(f"generated landscape: {compose_landscape()}")
    print(f"generated square: {compose_square()}")


if __name__ == "__main__":
    main()
