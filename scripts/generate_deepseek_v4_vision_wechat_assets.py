#!/usr/bin/env python3
"""Generate deterministic WeChat assets for the DeepSeek V4 Vision Day 0 article."""

from __future__ import annotations

from pathlib import Path
from shutil import copyfile

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "articles/wechat/assets/deepseek-v4-vision-day0"
LANDSCAPE = ROOT / "articles/wechat/assets/deepseek-v4-vision-day0-cover.png"
SQUARE = ROOT / "articles/wechat/assets/deepseek-v4-vision-day0-cover-square.png"
SCREENSHOT_SOURCE = (
    ROOT
    / "docs/assets/practices/deepseek-v4-flash-vision-exp-day0"
    / "openwebui-multimodal-light.png"
)

CHINESE = Path("/System/Library/Fonts/Hiragino Sans GB.ttc")
LATIN = Path("/System/Library/Fonts/HelveticaNeue.ttc")

INK = (14, 28, 48)
MUTED = (75, 97, 125)
BLUE = (32, 112, 231)
CYAN = (18, 176, 201)
ORANGE = (247, 137, 47)
PAPER = (246, 249, 253)
WHITE = (255, 255, 255)
LINE = (210, 221, 235)


def font(path: Path, size: int, index: int = 0) -> ImageFont.FreeTypeFont:
    if not path.exists():
        raise FileNotFoundError(f"font not found: {path}")
    return ImageFont.truetype(str(path), size=size, index=index)


def add_grid(draw: ImageDraw.ImageDraw, width: int, height: int, step: int) -> None:
    for x in range(0, width, step):
        draw.line((x, 0, x, height), fill=(201, 216, 234, 65), width=1)
    for y in range(0, height, step):
        draw.line((0, y, width, y), fill=(201, 216, 234, 65), width=1)


def pill(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    label: str,
    *,
    size: int,
    fill: tuple[int, int, int],
    color: tuple[int, int, int],
) -> tuple[int, int, int, int]:
    label_font = font(CHINESE, size)
    box = draw.textbbox((0, 0), label, font=label_font)
    width = box[2] - box[0] + 30
    height = box[3] - box[1] + 16
    left, top = xy
    bounds = (left, top, left + width, top + height)
    draw.rounded_rectangle(bounds, radius=height // 2, fill=fill)
    draw.text((left + 15, top + 8 - box[1]), label, font=label_font, fill=color)
    return bounds


def draw_vision_pipeline(
    image: Image.Image,
    bounds: tuple[int, int, int, int],
    *,
    scale: float = 1.0,
) -> None:
    draw = ImageDraw.Draw(image, "RGBA")
    left, top, right, bottom = bounds
    draw.rounded_rectangle(bounds, radius=round(30 * scale), fill=WHITE + (238,), outline=LINE, width=2)

    photo = (
        left + round(30 * scale),
        top + round(36 * scale),
        left + round(180 * scale),
        top + round(176 * scale),
    )
    draw.rounded_rectangle(photo, radius=round(18 * scale), fill=(228, 244, 251), outline=(148, 207, 222), width=2)
    draw.ellipse(
        (
            photo[0] + round(42 * scale),
            photo[1] + round(28 * scale),
            photo[0] + round(108 * scale),
            photo[1] + round(94 * scale),
        ),
        fill=(41, 156, 184, 220),
    )
    draw.polygon(
        [
            (photo[0] + round(51 * scale), photo[1] + round(38 * scale)),
            (photo[0] + round(65 * scale), photo[1] + round(13 * scale)),
            (photo[0] + round(77 * scale), photo[1] + round(41 * scale)),
        ],
        fill=(41, 156, 184, 220),
    )
    draw.polygon(
        [
            (photo[0] + round(77 * scale), photo[1] + round(41 * scale)),
            (photo[0] + round(96 * scale), photo[1] + round(13 * scale)),
            (photo[0] + round(102 * scale), photo[1] + round(43 * scale)),
        ],
        fill=(41, 156, 184, 220),
    )
    draw.text(
        (photo[0] + round(26 * scale), photo[3] - round(36 * scale)),
        "IMAGE",
        font=font(LATIN, round(17 * scale), index=1),
        fill=MUTED,
    )

    chip_left = left + round(250 * scale)
    chip_top = top + round(35 * scale)
    for index in range(4):
        y = chip_top + round(index * 54 * scale)
        chip = (chip_left, y, chip_left + round(132 * scale), y + round(39 * scale))
        draw.rounded_rectangle(chip, radius=round(8 * scale), fill=(16, 54, 94), outline=(46, 153, 227), width=2)
        draw.text(
            (chip[0] + round(16 * scale), chip[1] + round(8 * scale)),
            f"H20  GPU {index + 1}",
            font=font(LATIN, round(14 * scale), index=1),
            fill=WHITE,
        )

    start_x = photo[2] + round(10 * scale)
    end_x = chip_left - round(10 * scale)
    for offset in (48, 70, 92):
        y = top + round(offset * scale)
        draw.line((start_x, y, end_x, y), fill=(*CYAN, 180), width=max(2, round(3 * scale)))
        draw.polygon(
            [
                (end_x, y),
                (end_x - round(9 * scale), y - round(5 * scale)),
                (end_x - round(9 * scale), y + round(5 * scale)),
            ],
            fill=(*CYAN, 210),
        )

    draw.text(
        (left + round(31 * scale), bottom - round(48 * scale)),
        "VISION TOKENS / TP4 / OPENAI API",
        font=font(LATIN, round(14 * scale), index=1),
        fill=BLUE,
    )


def compose_landscape() -> None:
    image = Image.new("RGBA", (900, 383), PAPER + (255,))
    draw = ImageDraw.Draw(image, "RGBA")
    add_grid(draw, 900, 383, 42)
    draw.rounded_rectangle((30, 24, 870, 359), radius=26, fill=WHITE + (226,), outline=LINE, width=2)
    draw.rectangle((30, 24, 42, 359), fill=BLUE)

    draw.text((72, 48), "DAY 0 · MULTIMODAL", font=font(LATIN, 16, index=1), fill=BLUE)
    draw.text((68, 88), "DeepSeek-V4", font=font(LATIN, 40, index=1), fill=INK)
    draw.text((68, 133), "Flash-Vision-Exp", font=font(LATIN, 35, index=1), fill=INK)
    draw.text((70, 187), "4 张 H20 跑通多模态", font=font(CHINESE, 29), fill=INK)
    pill(draw, (70, 242), "SGLang Preview", size=16, fill=(224, 239, 255), color=BLUE)
    draw.text((70, 300), "3,856 请求 · 0 失败", font=font(CHINESE, 18), fill=MUTED)
    draw.text((298, 304), "AIK8S.RUN", font=font(LATIN, 13, index=1), fill=CYAN)

    draw_vision_pipeline(image, (490, 54, 836, 326), scale=0.78)
    image.convert("RGB").save(LANDSCAPE, format="PNG", optimize=True)


def compose_square() -> None:
    image = Image.new("RGBA", (900, 900), PAPER + (255,))
    draw = ImageDraw.Draw(image, "RGBA")
    add_grid(draw, 900, 900, 56)
    draw.rounded_rectangle((52, 46, 848, 854), radius=42, fill=WHITE + (232,), outline=LINE, width=2)
    draw.rectangle((52, 46, 848, 58), fill=BLUE)

    draw.text((90, 93), "DAY 0 · MULTIMODAL", font=font(LATIN, 22, index=1), fill=BLUE)
    draw.text((86, 151), "DeepSeek-V4", font=font(LATIN, 68, index=1), fill=INK)
    draw.text((86, 228), "Flash-Vision-Exp", font=font(LATIN, 53, index=1), fill=INK)
    draw.text((90, 314), "4 张 H20 跑通多模态", font=font(CHINESE, 43), fill=INK)
    draw_vision_pipeline(image, (121, 413, 779, 723), scale=1.05)
    pill(draw, (90, 770), "SGLang Preview", size=20, fill=(224, 239, 255), color=BLUE)
    draw.text((337, 781), "3,856 请求 · 0 失败", font=font(CHINESE, 21), fill=MUTED)
    draw.text((704, 786), "AIK8S.RUN", font=font(LATIN, 14, index=1), fill=CYAN)
    image.convert("RGB").save(SQUARE, format="PNG", optimize=True)


def chart_frame(title: str, subtitle: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (1200, 675), PAPER)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((42, 38, 1158, 637), radius=28, fill=WHITE, outline=LINE, width=2)
    draw.rectangle((42, 38, 54, 637), fill=BLUE)
    draw.text((90, 76), title, font=font(CHINESE, 38), fill=INK)
    draw.text((92, 132), subtitle, font=font(CHINESE, 20), fill=MUTED)
    return image, draw


def startup_chart() -> None:
    image, draw = chart_frame(
        "首次冷启动：权重读取不是大头",
        "4×H20 · NVMe · SGLang Vision Preview · 总计 13 分 52 秒",
    )
    labels = ["NVMe 读取 48 分片", "MHC 首次编译", "Target CUDA Graph", "Draft CUDA Graph"]
    values = [18.0, 192.8, 36.7, 90.2]
    colors = [CYAN, BLUE, ORANGE, (126, 87, 194)]
    max_value = 210.0
    left = 330
    top = 215
    width = 690
    for index, (label, value, color) in enumerate(zip(labels, values, colors)):
        y = top + index * 88
        draw.text((92, y + 7), label, font=font(CHINESE, 23), fill=INK)
        draw.rounded_rectangle((left, y, left + width, y + 46), radius=12, fill=(229, 236, 245))
        bar_width = round(width * value / max_value)
        draw.rounded_rectangle((left, y, left + bar_width, y + 46), radius=12, fill=color)
        draw.text((left + bar_width + 14, y + 8), f"{value:g}s", font=font(LATIN, 21, index=1), fill=INK)
    draw.text((91, 575), "结论：需要持久化编译缓存，并让 Startup Probe 覆盖真实冷启动窗口。", font=font(CHINESE, 20), fill=BLUE)
    image.save(ASSET_DIR / "startup-stages.png", format="PNG", optimize=True)


def throughput_chart() -> None:
    image, draw = chart_frame(
        "720p：同图复用让 C16 输出吞吐接近翻倍",
        "每点三轮中位数 · 固定输出 64 Token · Output tok/s",
    )
    concurrency = [1, 4, 8, 16]
    cold = [80.09, 126.96, 150.34, 175.06]
    warm = [106.09, 198.70, 259.62, 332.52]
    chart_left, chart_top, chart_right, chart_bottom = 115, 205, 1090, 530
    max_value = 360
    for tick in range(0, 361, 60):
        y = chart_bottom - round((chart_bottom - chart_top) * tick / max_value)
        draw.line((chart_left, y, chart_right, y), fill=(224, 231, 240), width=1)
        draw.text((55, y - 11), str(tick), font=font(LATIN, 16), fill=MUTED)
    group_width = (chart_right - chart_left) / len(concurrency)
    bar_width = 62
    for index, value in enumerate(concurrency):
        center = chart_left + group_width * (index + 0.5)
        for offset, metric, color in ((-38, cold[index], ORANGE), (38, warm[index], BLUE)):
            height = round((chart_bottom - chart_top) * metric / max_value)
            x0 = round(center + offset - bar_width / 2)
            x1 = x0 + bar_width
            y0 = chart_bottom - height
            draw.rounded_rectangle((x0, y0, x1, chart_bottom), radius=9, fill=color)
            label = f"{metric:.2f}"
            box = draw.textbbox((0, 0), label, font=font(LATIN, 16, index=1))
            draw.text((x0 + (bar_width - (box[2] - box[0])) / 2, y0 - 27), label, font=font(LATIN, 16, index=1), fill=INK)
        label = f"C{value}"
        box = draw.textbbox((0, 0), label, font=font(LATIN, 19, index=1))
        draw.text((center - (box[2] - box[0]) / 2, chart_bottom + 18), label, font=font(LATIN, 19, index=1), fill=INK)
    draw.rounded_rectangle((750, 159, 774, 183), radius=6, fill=ORANGE)
    draw.text((783, 160), "Cold：不同图片", font=font(CHINESE, 17), fill=MUTED)
    draw.rounded_rectangle((925, 159, 949, 183), radius=6, fill=BLUE)
    draw.text((958, 160), "Warm：同图复用", font=font(CHINESE, 17), fill=MUTED)
    draw.text((115, 586), "C16 P99 TTFT：Cold 3.86s → Warm 1.10s；唯一图片业务应以 Cold 为基线。", font=font(CHINESE, 20), fill=BLUE)
    image.save(ASSET_DIR / "throughput-720p.png", format="PNG", optimize=True)


def main() -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    compose_landscape()
    compose_square()
    startup_chart()
    throughput_chart()
    copyfile(SCREENSHOT_SOURCE, ASSET_DIR / "openwebui-multimodal-light.png")
    print(f"generated: {LANDSCAPE}")
    print(f"generated: {SQUARE}")
    print(f"generated assets: {ASSET_DIR}")


if __name__ == "__main__":
    main()
