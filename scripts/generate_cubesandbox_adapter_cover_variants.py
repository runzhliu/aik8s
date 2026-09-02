#!/usr/bin/env python3
"""Compose three CubeSandbox Agent Adapter WeChat cover variants."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "articles/wechat/assets/cubesandbox-agent-adapter"
OUTPUT_DIR = ROOT / "articles/wechat/assets"
WIDTH = 900
HEIGHT = 383
CHINESE = Path("/System/Library/Fonts/Hiragino Sans GB.ttc")
LATIN = Path("/System/Library/Fonts/HelveticaNeue.ttc")


@dataclass(frozen=True)
class Variant:
    name: str
    background: str
    output: str
    foreground: tuple[int, int, int]
    secondary: tuple[int, int, int]
    accent: tuple[int, int, int]
    overlay: tuple[int, int, int]
    overlay_alpha: int
    font_index: int = 0


VARIANTS = (
    Variant(
        name="3D 微型实验室",
        background="cover-background-3d.png",
        output="cubesandbox-agent-adapter-cover-3d.png",
        foreground=(246, 250, 255),
        secondary=(164, 207, 255),
        accent=(71, 218, 255),
        overlay=(3, 15, 45),
        overlay_alpha=238,
    ),
    Variant(
        name="复古丝网印刷",
        background="cover-background-screenprint.png",
        output="cubesandbox-agent-adapter-cover-screenprint.png",
        foreground=(7, 37, 68),
        secondary=(35, 79, 94),
        accent=(243, 83, 47),
        overlay=(250, 240, 216),
        overlay_alpha=236,
    ),
    Variant(
        name="技术蓝图线路图",
        background="cover-background-blueprint.png",
        output="cubesandbox-agent-adapter-cover-blueprint.png",
        foreground=(244, 250, 255),
        secondary=(137, 204, 255),
        accent=(65, 211, 255),
        overlay=(2, 18, 42),
        overlay_alpha=244,
    ),
)


def font(path: Path, size: int, index: int = 0) -> ImageFont.FreeTypeFont:
    if not path.exists():
        raise FileNotFoundError(f"font not found: {path}")
    return ImageFont.truetype(str(path), size=size, index=index)


def add_left_readability_panel(image: Image.Image, variant: Variant) -> Image.Image:
    """Add an opaque-to-transparent panel without covering the core illustration."""
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    solid_until = 300
    fade_until = 510
    for x in range(fade_until):
        if x <= solid_until:
            alpha = variant.overlay_alpha
        else:
            progress = (x - solid_until) / (fade_until - solid_until)
            alpha = round(variant.overlay_alpha * (1.0 - progress) ** 1.6)
        draw.line((x, 0, x, HEIGHT), fill=(*variant.overlay, alpha))
    return Image.alpha_composite(image.convert("RGBA"), overlay)


def draw_label(draw: ImageDraw.ImageDraw, variant: Variant) -> None:
    x = 48
    kicker_font = font(LATIN, 14, index=1)
    headline_font = font(CHINESE, 37, index=variant.font_index)
    product_font = font(LATIN, 18, index=1)
    tags_font = font(CHINESE, 14, index=variant.font_index)
    footer_font = font(LATIN, 12, index=1)

    draw.rounded_rectangle((x, 33, x + 8, 49), radius=4, fill=(*variant.accent, 255))
    draw.text(
        (x + 18, 33),
        "OPENCLAW  ·  DSH  ·  HERMES",
        font=kicker_font,
        fill=(*variant.secondary, 255),
    )

    draw.text((x, 82), "三种 Agent", font=headline_font, fill=(*variant.foreground, 255))
    draw.text((x, 132), "一条安全执行链", font=headline_font, fill=(*variant.foreground, 255))

    draw.rounded_rectangle(
        (x, 202, x + 282, 237),
        radius=17,
        fill=(*variant.accent, 36),
        outline=(*variant.accent, 150),
        width=1,
    )
    draw.text(
        (x + 14, 209),
        "CubeSandbox Agent Adapter",
        font=product_font,
        fill=(*variant.foreground, 255),
    )

    draw.text(
        (x, 260),
        "MicroVM  ·  统一策略  ·  脱敏审计",
        font=tags_font,
        fill=(*variant.secondary, 255),
    )
    draw.line((x, 304, x + 250, 304), fill=(*variant.accent, 190), width=3)
    draw.text((x, 326), "AIK8S.RUN", font=footer_font, fill=(*variant.secondary, 230))


def compose(variant: Variant) -> Path:
    source = ASSET_DIR / variant.background
    if not source.exists():
        raise FileNotFoundError(f"background not found: {source}")
    with Image.open(source) as background:
        fitted = ImageOps.fit(
            background.convert("RGB"),
            (WIDTH, HEIGHT),
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5),
        )
    image = add_left_readability_panel(fitted, variant)
    draw = ImageDraw.Draw(image, "RGBA")
    draw_label(draw, variant)

    output = OUTPUT_DIR / variant.output
    image.convert("RGB").save(output, format="PNG", optimize=True)
    return output


def main() -> None:
    for variant in VARIANTS:
        output = compose(variant)
        print(f"generated {variant.name}: {output}")


if __name__ == "__main__":
    main()
