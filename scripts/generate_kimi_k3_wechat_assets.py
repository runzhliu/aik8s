#!/usr/bin/env python3
"""Generate light-mode Kimi K3 WeChat covers and benchmark figures."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "articles/wechat/assets/kimi-k3-h20"
LANDSCAPE_OUTPUT = ROOT / "articles/wechat/assets/kimi-k3-h20-cover.png"
SQUARE_OUTPUT = ROOT / "articles/wechat/assets/kimi-k3-h20-cover-square.png"

CHINESE = Path("/System/Library/Fonts/Hiragino Sans GB.ttc")
LATIN = Path("/System/Library/Fonts/HelveticaNeue.ttc")

INK = (14, 28, 48)
MUTED = (75, 97, 125)
BLUE = (32, 112, 231)
CYAN = (18, 176, 201)
ORANGE = (247, 137, 47)
VIOLET = (126, 87, 194)
PAPER = (246, 249, 253)
WHITE = (255, 255, 255)
LINE = (210, 221, 235)
PALE_BLUE = (224, 239, 255)
PALE_CYAN = (226, 247, 249)


def font(path: Path, size: int, index: int = 0) -> ImageFont.FreeTypeFont:
    if not path.exists():
        raise FileNotFoundError(f"font not found: {path}")
    return ImageFont.truetype(str(path), size=size, index=index)


def add_grid(draw: ImageDraw.ImageDraw, width: int, height: int, step: int) -> None:
    for x in range(0, width, step):
        draw.line((x, 0, x, height), fill=(224, 232, 242), width=1)
    for y in range(0, height, step):
        draw.line((0, y, width, y), fill=(224, 232, 242), width=1)


def pill(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    label: str,
    *,
    size: int,
) -> tuple[int, int, int, int]:
    label_font = font(LATIN, size, 1)
    box = draw.textbbox((0, 0), label, font=label_font)
    width = box[2] - box[0] + 34
    height = box[3] - box[1] + 18
    left, top = xy
    bounds = (left, top, left + width, top + height)
    draw.rounded_rectangle(bounds, radius=height // 2, fill=PALE_BLUE, outline=(156, 198, 246))
    draw.text((left + 17, top + 9 - box[1]), label, font=label_font, fill=BLUE)
    return bounds


def cover_topology(
    draw: ImageDraw.ImageDraw,
    bounds: tuple[int, int, int, int],
    *,
    scale: float,
) -> None:
    left, top, right, bottom = bounds
    width = right - left
    node_width = round(144 * scale)
    node_height = round(186 * scale)
    node_y = top + round(38 * scale)
    node_positions = [left, right - node_width]
    for node_index, node_x in enumerate(node_positions):
        draw.rounded_rectangle(
            (node_x, node_y, node_x + node_width, node_y + node_height),
            radius=round(18 * scale),
            fill=WHITE,
            outline=BLUE,
            width=max(2, round(2 * scale)),
        )
        draw.text(
            (node_x + round(20 * scale), node_y + round(14 * scale)),
            f"NODE {node_index + 1}",
            font=font(LATIN, round(13 * scale), 1),
            fill=BLUE,
        )
        for row in range(2):
            for col in range(4):
                gx = node_x + round((17 + col * 29) * scale)
                gy = node_y + round((57 + row * 42) * scale)
                draw.rounded_rectangle(
                    (gx, gy, gx + round(22 * scale), gy + round(26 * scale)),
                    radius=round(4 * scale),
                    fill=PALE_CYAN,
                    outline=CYAN,
                )
        draw.rounded_rectangle(
            (
                node_x + round(17 * scale),
                node_y + round(149 * scale),
                node_x + node_width - round(17 * scale),
                node_y + round(173 * scale),
            ),
            radius=round(6 * scale),
            fill=PALE_BLUE,
        )
        draw.text(
            (node_x + round(31 * scale), node_y + round(153 * scale)),
            "NVMe · 8×H20",
            font=font(LATIN, round(11 * scale), 1),
            fill=INK,
        )

    center_x = left + width // 2
    rdma_y = top + round(87 * scale)
    radius = round(48 * scale)
    draw.ellipse(
        (center_x - radius, rdma_y, center_x + radius, rdma_y + 2 * radius),
        fill=PALE_BLUE,
        outline=BLUE,
        width=max(2, round(2 * scale)),
    )
    draw.text(
        (center_x - round(29 * scale), rdma_y + round(29 * scale)),
        "RDMA",
        font=font(LATIN, round(17 * scale), 1),
        fill=BLUE,
    )
    for index in range(8):
        y = rdma_y + round((5 + index * 11) * scale)
        color = CYAN if index % 2 == 0 else VIOLET
        draw.line((left + node_width, y, center_x - radius, y), fill=color, width=max(1, round(2 * scale)))
        draw.line((center_x + radius, y, right - node_width, y), fill=color, width=max(1, round(2 * scale)))
    draw.text(
        (center_x - round(52 * scale), bottom - round(28 * scale)),
        "NCCL NET/IB",
        font=font(LATIN, round(13 * scale), 1),
        fill=MUTED,
    )


def compose_landscape() -> Path:
    image = Image.new("RGB", (900, 383), PAPER)
    draw = ImageDraw.Draw(image)
    add_grid(draw, 900, 383, 42)
    draw.rounded_rectangle((30, 24, 870, 359), radius=26, fill=WHITE, outline=LINE, width=2)
    draw.rectangle((30, 24, 42, 359), fill=BLUE)
    draw.text((72, 48), "2.8T MoE · 16×H20 · RDMA", font=font(LATIN, 16, 1), fill=BLUE)
    draw.text((68, 87), "Kimi K3", font=font(LATIN, 46, 1), fill=INK)
    draw.text((70, 143), "双引擎实测", font=font(CHINESE, 37), fill=INK)
    pill(draw, (70, 211), "SGLang × vLLM", size=18)
    draw.text((70, 273), "4,796 请求 · 0 失败", font=font(CHINESE, 17), fill=MUTED)
    draw.text((70, 319), "AIK8S.RUN", font=font(LATIN, 13, 1), fill=CYAN)
    cover_topology(draw, (500, 48, 836, 329), scale=0.76)
    image.save(LANDSCAPE_OUTPUT, format="PNG", optimize=True)
    return LANDSCAPE_OUTPUT


def compose_square() -> Path:
    image = Image.new("RGB", (900, 900), PAPER)
    draw = ImageDraw.Draw(image)
    add_grid(draw, 900, 900, 56)
    draw.rounded_rectangle((52, 46, 848, 854), radius=42, fill=WHITE, outline=LINE, width=2)
    draw.rectangle((52, 46, 848, 58), fill=BLUE)
    draw.text((90, 93), "2.8T MoE · 16×H20 · RDMA", font=font(LATIN, 22, 1), fill=BLUE)
    draw.text((86, 151), "Kimi K3", font=font(LATIN, 73, 1), fill=INK)
    draw.text((90, 241), "双引擎实测", font=font(CHINESE, 58), fill=INK)
    cover_topology(draw, (122, 365, 778, 674), scale=1.08)
    pill(draw, (90, 743), "SGLang × vLLM", size=23)
    draw.text((387, 757), "4,796 请求 · 0 失败", font=font(CHINESE, 20), fill=MUTED)
    draw.text((714, 763), "AIK8S.RUN", font=font(LATIN, 13, 1), fill=CYAN)
    image.save(SQUARE_OUTPUT, format="PNG", optimize=True)
    return SQUARE_OUTPUT


def figure(title: str, subtitle: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (1200, 675), PAPER)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((42, 38, 1158, 637), radius=28, fill=WHITE, outline=LINE, width=2)
    draw.rectangle((42, 38, 54, 637), fill=BLUE)
    draw.text((90, 72), title, font=font(CHINESE, 36), fill=INK)
    draw.text((92, 126), subtitle, font=font(CHINESE, 19), fill=MUTED)
    return image, draw


def save_topology() -> Path:
    image, draw = figure(
        "16×H20 跨节点推理拓扑",
        "两台 8×141GB H20 · 本地 NVMe 权重 · NCCL NET/IB",
    )

    def node(x: int, name: str) -> None:
        draw.rounded_rectangle((x, 187, x + 390, 539), radius=24, fill=PAPER, outline=BLUE, width=2)
        draw.text((x + 26, 208), name, font=font(CHINESE, 25), fill=INK)
        draw.text((x + 26, 246), "8×H20 141GB", font=font(LATIN, 17, 1), fill=BLUE)
        for row in range(2):
            for col in range(4):
                gx = x + 27 + col * 84
                gy = 300 + row * 70
                draw.rounded_rectangle((gx, gy, gx + 64, gy + 46), radius=9, fill=PALE_CYAN, outline=CYAN)
                draw.text((gx + 15, gy + 12), "H20", font=font(LATIN, 16, 1), fill=INK)
        draw.rounded_rectangle((x + 27, 455, x + 363, 505), radius=11, fill=PALE_BLUE, outline=(156, 198, 246))
        draw.text((x + 57, 470), "NVMe · Kimi K3 MXFP4", font=font(LATIN, 17, 1), fill=INK)

    node(74, "节点 A")
    node(736, "节点 B")
    draw.rounded_rectangle((500, 248, 700, 474), radius=26, fill=PALE_BLUE, outline=BLUE, width=3)
    draw.text((545, 281), "RDMA", font=font(LATIN, 30, 1), fill=BLUE)
    draw.text((532, 329), "NCCL NET/IB", font=font(LATIN, 18, 1), fill=INK)
    for index in range(8):
        y = 376 + index * 11
        color = CYAN if index % 2 == 0 else VIOLET
        draw.line((464, y, 500, y), fill=color, width=3)
        draw.line((700, y, 736, y), fill=color, width=3)
    draw.text((537, 444), "8 条 RoCE rail", font=font(CHINESE, 16), fill=MUTED)
    draw.text((86, 579), "SGLang: TP16 / EP16", font=font(LATIN, 17, 1), fill=MUTED)
    draw.text((483, 579), "跨节点 AllReduce 预检通过", font=font(CHINESE, 17), fill=BLUE)
    draw.text((948, 579), "vLLM: TP16", font=font(LATIN, 17, 1), fill=MUTED)
    output = ASSET_DIR / "topology-rdma.png"
    image.save(output, format="PNG", optimize=True)
    return output


def legend(draw: ImageDraw.ImageDraw, x: int, y: int) -> None:
    draw.rounded_rectangle((x, y, x + 22, y + 22), radius=5, fill=BLUE)
    draw.text((x + 31, y - 1), "SGLang", font=font(LATIN, 17, 1), fill=INK)
    draw.rounded_rectangle((x + 145, y, x + 167, y + 22), radius=5, fill=ORANGE)
    draw.text((x + 176, y - 1), "vLLM", font=font(LATIN, 17, 1), fill=INK)


def save_short_throughput() -> Path:
    image, draw = figure(
        "短请求输出吞吐：两者基本同档",
        "128 Token 输入 → 64 Token 输出 · 重复轮次中位数 · tok/s",
    )
    cases = ["C1", "C4", "C8", "C16"]
    sglang = [32.99, 104.59, 168.88, 259.01]
    vllm = [32.61, 104.03, 170.84, 263.78]
    left, top, bottom, right = 110, 200, 545, 1115
    max_value = 300
    for tick in range(0, max_value + 1, 50):
        y = bottom - (bottom - top) * tick / max_value
        draw.line((left, y, right, y), fill=(224, 231, 240), width=1)
        text = str(tick)
        box = draw.textbbox((0, 0), text, font=font(LATIN, 14))
        draw.text((left - 16 - (box[2] - box[0]), y - 8), text, font=font(LATIN, 14), fill=MUTED)
    group_width = (right - left) / len(cases)
    for index, case in enumerate(cases):
        center = left + group_width * (index + 0.5)
        for offset, value, color in [(-37, sglang[index], BLUE), (9, vllm[index], ORANGE)]:
            x0 = int(center + offset)
            x1 = x0 + 32
            y0 = int(bottom - (bottom - top) * value / max_value)
            draw.rounded_rectangle((x0, y0, x1, bottom), radius=6, fill=color)
            text = f"{value:.1f}"
            box = draw.textbbox((0, 0), text, font=font(LATIN, 14, 1))
            draw.text((x0 + 16 - (box[2] - box[0]) / 2, y0 - 23), text, font=font(LATIN, 14, 1), fill=INK)
        box = draw.textbbox((0, 0), case, font=font(LATIN, 17, 1))
        draw.text((center - (box[2] - box[0]) / 2, bottom + 17), case, font=font(LATIN, 17, 1), fill=INK)
    legend(draw, 827, 161)
    draw.text((100, 591), "结论：C1/C4 几乎相同；C8/C16 vLLM 领先约 1%–2%。", font=font(CHINESE, 17), fill=BLUE)
    output = ASSET_DIR / "short-throughput.png"
    image.save(output, format="PNG", optimize=True)
    return output


def save_context_ttft() -> Path:
    image, draw = figure(
        "长上下文 P50 TTFT：优势随并发反转",
        "首 Token 延迟，越低越好 · 重复轮次中位数 · 秒",
    )
    cases = ["4K C4", "4K C8", "16K C4", "16K C8", "32K C1"]
    sglang = [6.145, 10.432, 18.280, 30.912, 12.817]
    vllm = [4.427, 5.843, 13.397, 51.335, 12.016]
    left, top, right = 190, 205, 1100
    max_value = 55
    row_gap = 70
    for tick in range(0, max_value + 1, 10):
        x = left + (right - left) * tick / max_value
        draw.line((x, top - 18, x, 555), fill=(224, 231, 240), width=1)
        draw.text((x - 7, 560), str(tick), font=font(LATIN, 14), fill=MUTED)
    for index, case in enumerate(cases):
        y = top + index * row_gap
        box = draw.textbbox((0, 0), case, font=font(LATIN, 17, 1))
        draw.text((left - 25 - (box[2] - box[0]), y + 12), case, font=font(LATIN, 17, 1), fill=INK)
        for offset, value, color in [(0, sglang[index], BLUE), (27, vllm[index], ORANGE)]:
            width = int((right - left) * value / max_value)
            draw.rounded_rectangle((left, y + offset, left + width, y + offset + 20), radius=6, fill=color)
            draw.text((left + width + 10, y + offset), f"{value:.2f}", font=font(LATIN, 14, 1), fill=INK)
    legend(draw, 827, 159)
    draw.text((72, 594), "16K C8：vLLM KV Cache 较小并出现排队；SGLang 的 P50 TTFT 低 20.42 秒。", font=font(CHINESE, 17), fill=BLUE)
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
