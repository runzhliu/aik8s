#!/usr/bin/env python3
"""Generate deterministic Kimi K3 WeChat covers and benchmark figures."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "articles/wechat/assets/kimi-k3-h20"
LANDSCAPE_BACKGROUND = ASSET_DIR / "cover-background-landscape-3d.png"
SQUARE_BACKGROUND = ASSET_DIR / "cover-background-square-3d.png"
LANDSCAPE_OUTPUT = ROOT / "articles/wechat/assets/kimi-k3-h20-cover.png"
SQUARE_OUTPUT = ROOT / "articles/wechat/assets/kimi-k3-h20-cover-square.png"

CHINESE = Path("/System/Library/Fonts/Hiragino Sans GB.ttc")
LATIN = Path("/System/Library/Fonts/HelveticaNeue.ttc")

WHITE = (242, 248, 255)
SECONDARY = (158, 188, 226)
CYAN = (48, 210, 255)
BLUE = (65, 130, 255)
VIOLET = (151, 90, 255)
ORANGE = (255, 155, 68)
NAVY = (3, 13, 35)
PANEL = (8, 26, 58)
GRID = (46, 70, 105)


def font(path: Path, size: int, index: int = 0) -> ImageFont.FreeTypeFont:
    if not path.exists():
        raise FileNotFoundError(f"font not found: {path}")
    return ImageFont.truetype(str(path), size=size, index=index)


def add_horizontal_panel(image: Image.Image) -> Image.Image:
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for x in range(570):
        alpha = 244 if x <= 330 else round(244 * (1 - (x - 330) / 240) ** 1.7)
        draw.line((x, 0, x, image.height), fill=(*NAVY, max(alpha, 0)))
    return Image.alpha_composite(image.convert("RGBA"), overlay)


def add_square_panel(image: Image.Image) -> Image.Image:
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for y in range(575):
        alpha = 235 if y <= 345 else round(235 * (1 - (y - 345) / 230) ** 1.6)
        draw.line((0, y, image.width, y), fill=(*NAVY, max(alpha, 0)))
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
        fill=(*CYAN, 30),
        outline=(*CYAN, 170),
        width=1,
    )
    box = draw.textbbox((0, 0), label, font=label_font)
    y = bounds[1] + (bounds[3] - bounds[1] - (box[3] - box[1])) // 2 - box[1]
    draw.text((bounds[0] + 17, y), label, font=label_font, fill=(*WHITE, 255))


def compose_landscape() -> Path:
    with Image.open(LANDSCAPE_BACKGROUND) as source:
        fitted = ImageOps.fit(
            source.convert("RGB"),
            (900, 383),
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5),
        )
    image = add_horizontal_panel(fitted)
    draw = ImageDraw.Draw(image, "RGBA")
    x = 48
    draw.rounded_rectangle((x, 31, x + 8, 48), radius=4, fill=(*CYAN, 255))
    draw.text(
        (x + 19, 31),
        "2.8T MoE  ·  16×H20  ·  RDMA",
        font=font(LATIN, 14, 1),
        fill=(*SECONDARY, 255),
    )
    draw.text((x, 73), "Kimi K3", font=font(LATIN, 45, 1), fill=(*WHITE, 255))
    draw.text((x, 128), "双引擎实测", font=font(CHINESE, 39), fill=(*WHITE, 255))
    pill(draw, (x, 199, x + 216, 238), "SGLang × vLLM", font(LATIN, 19, 1))
    draw.text(
        (x, 261),
        "4,796 请求  ·  0 失败",
        font=font(CHINESE, 15),
        fill=(*SECONDARY, 255),
    )
    draw.line((x, 306, x + 250, 306), fill=(*ORANGE, 220), width=3)
    draw.text((x, 327), "AIK8S.RUN", font=font(LATIN, 12, 1), fill=(*SECONDARY, 235))
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
    draw.rounded_rectangle((x, 49, x + 11, 72), radius=5, fill=(*CYAN, 255))
    draw.text(
        (x + 26, 48),
        "2.8T MoE  ·  16×H20  ·  RDMA",
        font=font(LATIN, 22, 1),
        fill=(*SECONDARY, 255),
    )
    draw.text((x, 107), "Kimi K3", font=font(LATIN, 76, 1), fill=(*WHITE, 255))
    draw.text((x, 198), "双引擎实测", font=font(CHINESE, 62), fill=(*WHITE, 255))
    pill(draw, (x, 302, x + 324, 358), "SGLang × vLLM", font(LATIN, 29, 1))
    draw.text(
        (x, 390),
        "4,796 请求  ·  0 失败",
        font=font(CHINESE, 23),
        fill=(*SECONDARY, 255),
    )
    draw.line((x, 444, x + 365, 444), fill=(*ORANGE, 220), width=5)
    draw.text((x, 470), "AIK8S.RUN", font=font(LATIN, 18, 1), fill=(*SECONDARY, 235))
    image.convert("RGB").save(SQUARE_OUTPUT, format="PNG", optimize=True)
    return SQUARE_OUTPUT


def figure(title: str, subtitle: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (1200, 675), NAVY)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((42, 36, 52, 62), radius=5, fill=CYAN)
    draw.text((69, 31), title, font=font(CHINESE, 35), fill=WHITE)
    draw.text((69, 78), subtitle, font=font(CHINESE, 17), fill=SECONDARY)
    draw.line((42, 113, 1158, 113), fill=GRID, width=2)
    return image, draw


def save_topology() -> Path:
    image, draw = figure(
        "16×H20 跨节点推理拓扑",
        "两台 8×141GB H20 · 本地 NVMe 权重 · NCCL NET/IB",
    )

    def node(x: int, name: str, engine: str) -> None:
        draw.rounded_rectangle((x, 158, x + 410, 552), radius=24, fill=PANEL, outline=BLUE, width=2)
        draw.text((x + 28, 181), name, font=font(CHINESE, 25), fill=WHITE)
        draw.text((x + 28, 221), engine, font=font(LATIN, 18, 1), fill=SECONDARY)
        for row in range(2):
            for col in range(4):
                gx = x + 29 + col * 90
                gy = 276 + row * 82
                draw.rounded_rectangle((gx, gy, gx + 70, gy + 52), radius=9, fill=(12, 43, 82), outline=CYAN)
                draw.text((gx + 16, gy + 14), f"H20", font=font(LATIN, 17, 1), fill=WHITE)
        draw.rounded_rectangle((x + 29, 462, x + 381, 517), radius=12, fill=(18, 37, 67), outline=VIOLET)
        draw.text((x + 54, 477), "NVMe  ·  Kimi K3 MXFP4", font=font(LATIN, 18, 1), fill=WHITE)

    node(58, "节点 A", "8×H20 141GB")
    node(732, "节点 B", "8×H20 141GB")

    draw.rounded_rectangle((500, 224, 700, 475), radius=26, fill=(9, 31, 66), outline=CYAN, width=3)
    draw.text((544, 254), "RDMA", font=font(LATIN, 31, 1), fill=WHITE)
    draw.text((532, 302), "NCCL NET/IB", font=font(LATIN, 18, 1), fill=CYAN)
    for index in range(8):
        y = 345 + index * 13
        color = CYAN if index % 2 == 0 else VIOLET
        draw.line((468, y, 500, y), fill=color, width=3)
        draw.line((700, y, 732, y), fill=color, width=3)
    draw.text((531, 449), "8 条 RoCE rail", font=font(CHINESE, 17), fill=SECONDARY)
    draw.text((54, 606), "SGLang: TP16 / EP16", font=font(LATIN, 17, 1), fill=SECONDARY)
    draw.text((475, 606), "跨节点 AllReduce 预检通过", font=font(CHINESE, 17), fill=WHITE)
    draw.text((939, 606), "vLLM: TP16", font=font(LATIN, 17, 1), fill=SECONDARY)

    output = ASSET_DIR / "topology-rdma.png"
    image.save(output, format="PNG", optimize=True)
    return output


def legend(draw: ImageDraw.ImageDraw, x: int, y: int) -> None:
    draw.rounded_rectangle((x, y, x + 20, y + 20), radius=4, fill=CYAN)
    draw.text((x + 30, y - 2), "SGLang", font=font(LATIN, 17, 1), fill=WHITE)
    draw.rounded_rectangle((x + 145, y, x + 165, y + 20), radius=4, fill=ORANGE)
    draw.text((x + 175, y - 2), "vLLM", font=font(LATIN, 17, 1), fill=WHITE)


def save_short_throughput() -> Path:
    image, draw = figure(
        "短请求输出吞吐：两者基本同档",
        "128 Token 输入 → 64 Token 输出 · 数值为重复轮次中位数 · tok/s",
    )
    cases = ["C1", "C4", "C8", "C16"]
    sglang = [32.99, 104.59, 168.88, 259.01]
    vllm = [32.61, 104.03, 170.84, 263.78]
    left, top, bottom, right = 100, 175, 565, 1138
    max_value = 300
    for tick in range(0, max_value + 1, 50):
        y = bottom - (bottom - top) * tick / max_value
        draw.line((left, y, right, y), fill=GRID, width=1)
        label = str(tick)
        box = draw.textbbox((0, 0), label, font=font(LATIN, 14))
        draw.text((left - 16 - (box[2] - box[0]), y - 8), label, font=font(LATIN, 14), fill=SECONDARY)
    group_width = (right - left) / len(cases)
    for index, case in enumerate(cases):
        center = left + group_width * (index + 0.5)
        for offset, value, color in [(-37, sglang[index], CYAN), (9, vllm[index], ORANGE)]:
            x0 = int(center + offset)
            x1 = x0 + 32
            y0 = int(bottom - (bottom - top) * value / max_value)
            draw.rounded_rectangle((x0, y0, x1, bottom), radius=6, fill=color)
            text = f"{value:.1f}"
            box = draw.textbbox((0, 0), text, font=font(LATIN, 14, 1))
            draw.text((x0 + 16 - (box[2] - box[0]) / 2, y0 - 23), text, font=font(LATIN, 14, 1), fill=WHITE)
        box = draw.textbbox((0, 0), case, font=font(LATIN, 17, 1))
        draw.text((center - (box[2] - box[0]) / 2, bottom + 18), case, font=font(LATIN, 17, 1), fill=WHITE)
    legend(draw, 830, 132)
    draw.text((100, 627), "结论：C1/C4 几乎相同；C8/C16 vLLM 领先约 1%–2%。", font=font(CHINESE, 17), fill=SECONDARY)
    output = ASSET_DIR / "short-throughput.png"
    image.save(output, format="PNG", optimize=True)
    return output


def save_context_ttft() -> Path:
    image, draw = figure(
        "长上下文 P50 TTFT：优势随并发发生反转",
        "首 Token 延迟，越低越好 · 数值为重复轮次中位数 · 秒",
    )
    cases = ["4K C4", "4K C8", "16K C4", "16K C8", "32K C1"]
    sglang = [6.145, 10.432, 18.280, 30.912, 12.817]
    vllm = [4.427, 5.843, 13.397, 51.335, 12.016]
    left, top, right = 190, 180, 1115
    max_value = 55
    row_gap = 77
    for tick in range(0, max_value + 1, 10):
        x = left + (right - left) * tick / max_value
        draw.line((x, top - 20, x, 568), fill=GRID, width=1)
        draw.text((x - 7, 574), str(tick), font=font(LATIN, 14), fill=SECONDARY)
    for index, case in enumerate(cases):
        y = top + index * row_gap
        box = draw.textbbox((0, 0), case, font=font(LATIN, 17, 1))
        draw.text((left - 25 - (box[2] - box[0]), y + 13), case, font=font(LATIN, 17, 1), fill=WHITE)
        for offset, value, color in [(0, sglang[index], CYAN), (30, vllm[index], ORANGE)]:
            width = int((right - left) * value / max_value)
            draw.rounded_rectangle((left, y + offset, left + width, y + offset + 22), radius=6, fill=color)
            draw.text((left + width + 10, y + offset + 1), f"{value:.2f}", font=font(LATIN, 14, 1), fill=WHITE)
    legend(draw, 830, 130)
    draw.text((72, 626), "16K C8：vLLM KV Cache 较小并出现排队；SGLang 的 P50 TTFT 低 20.42 秒。", font=font(CHINESE, 17), fill=SECONDARY)
    output = ASSET_DIR / "context-ttft.png"
    image.save(output, format="PNG", optimize=True)
    return output


def main() -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    for output in [
        compose_landscape(),
        compose_square(),
        save_topology(),
        save_short_throughput(),
        save_context_ttft(),
    ]:
        print(f"generated: {output}")


if __name__ == "__main__":
    main()
