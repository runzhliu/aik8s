#!/usr/bin/env python3
"""Compose the landscape and square GLM-5.3 Day 1 WeChat covers."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "articles/wechat/assets/glm53-day1"
LANDSCAPE_BACKGROUND = ASSET_DIR / "cover-background-landscape-3d.png"
SQUARE_BACKGROUND = ASSET_DIR / "cover-background-square-3d.png"
LANDSCAPE_OUTPUT = ROOT / "articles/wechat/assets/glm53-day1-cover-3d.png"
SQUARE_OUTPUT = ROOT / "articles/wechat/assets/glm53-day1-cover-square-3d.png"
X_ARTICLE_OUTPUT = ROOT / "articles/wechat/assets/glm53-day1-cover-x-article.png"

CHINESE = Path("/System/Library/Fonts/Hiragino Sans GB.ttc")
LATIN = Path("/System/Library/Fonts/HelveticaNeue.ttc")

WHITE = (246, 250, 255)
SECONDARY = (166, 210, 255)
CYAN = (64, 220, 255)
ORANGE = (255, 158, 66)
NAVY = (2, 12, 34)


def font(path: Path, size: int, index: int = 0) -> ImageFont.FreeTypeFont:
    if not path.exists():
        raise FileNotFoundError(f"font not found: {path}")
    return ImageFont.truetype(str(path), size=size, index=index)


def add_horizontal_panel(image: Image.Image) -> Image.Image:
    """Keep the left-side headline readable while retaining the 3D lab."""
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    solid_until = 305
    fade_until = 545
    for x in range(fade_until):
        if x <= solid_until:
            alpha = 243
        else:
            progress = (x - solid_until) / (fade_until - solid_until)
            alpha = round(243 * (1.0 - progress) ** 1.7)
        draw.line((x, 0, x, image.height), fill=(*NAVY, alpha))
    return Image.alpha_composite(image.convert("RGBA"), overlay)


def add_square_panel(image: Image.Image) -> Image.Image:
    """Reserve the upper area for a phone-legible square-cover title."""
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    solid_until = 335
    fade_until = 565
    for y in range(fade_until):
        if y <= solid_until:
            alpha = 232
        else:
            progress = (y - solid_until) / (fade_until - solid_until)
            alpha = round(232 * (1.0 - progress) ** 1.6)
        draw.line((0, y, image.width, y), fill=(*NAVY, alpha))
    return Image.alpha_composite(image.convert("RGBA"), overlay)


def draw_pill(
    draw: ImageDraw.ImageDraw,
    bounds: tuple[int, int, int, int],
    label: str,
    label_font: ImageFont.FreeTypeFont,
) -> None:
    draw.rounded_rectangle(
        bounds,
        radius=(bounds[3] - bounds[1]) // 2,
        fill=(*CYAN, 31),
        outline=(*CYAN, 156),
        width=1,
    )
    draw.text((bounds[0] + 16, bounds[1] + 7), label, font=label_font, fill=(*WHITE, 255))


def compose_landscape() -> Path:
    with Image.open(LANDSCAPE_BACKGROUND) as source:
        fitted = ImageOps.fit(
            source.convert("RGB"),
            (900, 383),
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.51),
        )
    image = add_horizontal_panel(fitted)
    draw = ImageDraw.Draw(image, "RGBA")

    x = 48
    draw.rounded_rectangle((x, 33, x + 8, 49), radius=4, fill=(*CYAN, 255))
    draw.text(
        (x + 18, 32),
        "NATIVE FP8  ·  8×H20  ·  TP8",
        font=font(LATIN, 14, index=1),
        fill=(*SECONDARY, 255),
    )
    draw.text((x, 78), "GLM-5.3", font=font(LATIN, 43, index=1), fill=(*WHITE, 255))
    draw.text((x, 130), "双引擎实测", font=font(CHINESE, 40), fill=(*WHITE, 255))

    draw_pill(draw, (x, 201, x + 210, 238), "SGLang × vLLM", font(LATIN, 19, index=1))
    draw.text(
        (x, 260),
        "54 轮  ·  7,680 请求  ·  0 失败",
        font=font(CHINESE, 15),
        fill=(*SECONDARY, 255),
    )
    draw.line((x, 304, x + 250, 304), fill=(*ORANGE, 210), width=3)
    draw.text((x, 326), "AIK8S.RUN", font=font(LATIN, 12, index=1), fill=(*SECONDARY, 235))

    image.convert("RGB").save(LANDSCAPE_OUTPUT, format="PNG", optimize=True)
    return LANDSCAPE_OUTPUT


def compose_square() -> Path:
    with Image.open(SQUARE_BACKGROUND) as source:
        fitted = ImageOps.fit(
            source.convert("RGB"),
            (900, 900),
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5),
        )
    image = add_square_panel(fitted)
    draw = ImageDraw.Draw(image, "RGBA")

    x = 58
    draw.rounded_rectangle((x, 51, x + 11, 74), radius=5, fill=(*CYAN, 255))
    draw.text(
        (x + 25, 50),
        "NATIVE FP8  ·  8×H20  ·  TP8",
        font=font(LATIN, 22, index=1),
        fill=(*SECONDARY, 255),
    )
    draw.text((x, 107), "GLM-5.3", font=font(LATIN, 73, index=1), fill=(*WHITE, 255))
    draw.text((x, 196), "双引擎实测", font=font(CHINESE, 62), fill=(*WHITE, 255))

    draw_pill(draw, (x, 296, x + 315, 350), "SGLang × vLLM", font(LATIN, 29, index=1))
    draw.text(
        (x, 381),
        "54 轮  ·  7,680 请求  ·  0 失败",
        font=font(CHINESE, 22),
        fill=(*SECONDARY, 255),
    )
    draw.line((x, 431, x + 360, 431), fill=(*ORANGE, 220), width=5)
    draw.text((x, 455), "AIK8S.RUN", font=font(LATIN, 18, index=1), fill=(*SECONDARY, 235))

    image.convert("RGB").save(SQUARE_OUTPUT, format="PNG", optimize=True)
    return SQUARE_OUTPUT


def compose_x_article() -> Path:
    """Compose the 5:2 cover recommended by the X Article editor."""
    with Image.open(LANDSCAPE_BACKGROUND) as source:
        fitted = ImageOps.fit(
            source.convert("RGB"),
            (1250, 500),
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.51),
        )
    image = add_horizontal_panel(fitted)
    draw = ImageDraw.Draw(image, "RGBA")

    x = 60
    draw.rounded_rectangle((x, 43, x + 10, 64), radius=5, fill=(*CYAN, 255))
    draw.text(
        (x + 23, 42),
        "NATIVE FP8  ·  8×H20  ·  TP8",
        font=font(LATIN, 18, index=1),
        fill=(*SECONDARY, 255),
    )
    draw.text((x, 96), "GLM-5.3", font=font(LATIN, 58, index=1), fill=(*WHITE, 255))
    draw.text((x, 164), "双引擎实测", font=font(CHINESE, 50), fill=(*WHITE, 255))

    draw_pill(draw, (x, 260, x + 280, 309), "SGLang × vLLM", font(LATIN, 25, index=1))
    draw.text(
        (x, 339),
        "54 轮  ·  7,680 请求  ·  0 失败",
        font=font(CHINESE, 19),
        fill=(*SECONDARY, 255),
    )
    draw.line((x, 399, x + 330, 399), fill=(*ORANGE, 220), width=4)
    draw.text((x, 424), "AIK8S.RUN", font=font(LATIN, 15, index=1), fill=(*SECONDARY, 235))

    image.convert("RGB").save(X_ARTICLE_OUTPUT, format="PNG", optimize=True)
    return X_ARTICLE_OUTPUT


def main() -> None:
    print(f"generated landscape: {compose_landscape()}")
    print(f"generated square: {compose_square()}")
    print(f"generated X Article cover: {compose_x_article()}")


if __name__ == "__main__":
    main()
