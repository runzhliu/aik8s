#!/usr/bin/env python3
"""Render diagrams for the distributed-training recovery guide."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/assets/training/distributed-training-recovery"
FONT_PATH = Path("/System/Library/Fonts/Hiragino Sans GB.ttc")
WIDTH, HEIGHT = 1200, 675

BG = "#F7F8FC"
WHITE = "#FFFFFF"
INK = "#172033"
MUTED = "#667085"
LINE = "#D9DFEA"
PURPLE = "#6D4AFF"
PURPLE_LIGHT = "#F0ECFF"
BLUE = "#246BFD"
BLUE_LIGHT = "#EAF1FF"
GREEN = "#15966A"
GREEN_LIGHT = "#E7F7F0"
ORANGE = "#F26B38"
ORANGE_LIGHT = "#FFF0E9"
RED = "#D64545"
RED_LIGHT = "#FDECEC"


def font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_PATH), size=size, index=1 if bold else 0)


def canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (WIDTH, HEIGHT), BG)
    return image, ImageDraw.Draw(image, "RGBA")


def rounded(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    *,
    fill: str = WHITE,
    outline: str = LINE,
    radius: int = 18,
    width: int = 2,
) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def heading(draw: ImageDraw.ImageDraw, title: str, subtitle: str) -> None:
    draw.text((48, 28), title, font=font(31, bold=True), fill=INK)
    draw.text((50, 75), subtitle, font=font(16), fill=MUTED)


def center_text(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    face: ImageFont.FreeTypeFont,
    color: str = INK,
) -> None:
    bounds = draw.textbbox((0, 0), text, font=face)
    tw, th = bounds[2] - bounds[0], bounds[3] - bounds[1]
    x1, y1, x2, y2 = box
    draw.text(((x1 + x2 - tw) / 2, (y1 + y2 - th) / 2 - bounds[1]), text, font=face, fill=color)


def arrow(
    draw: ImageDraw.ImageDraw,
    start: tuple[int, int],
    end: tuple[int, int],
    *,
    color: str = PURPLE,
    width: int = 4,
) -> None:
    draw.line((start, end), fill=color, width=width)
    ex, ey = end
    draw.polygon([(ex, ey), (ex - 11, ey - 7), (ex - 11, ey + 7)], fill=color)


def pill(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    *,
    fill: str,
    color: str,
) -> None:
    rounded(draw, box, fill=fill, outline=fill, radius=14, width=1)
    center_text(draw, box, text, font(16, bold=True), color)


def footer(draw: ImageDraw.ImageDraw, text: str) -> None:
    draw.line((48, 627, 1152, 627), fill=LINE, width=2)
    draw.text((50, 640), text, font=font(14), fill=MUTED)


def render_training_stack() -> None:
    image, draw = canvas()
    heading(
        draw,
        "多机多卡训练：四层能力共同决定能否恢复",
        "框架负责计算语义，平台负责重建资源，Checkpoint 负责找回训练状态",
    )

    rows = [
        (
            "训练与并行",
            "模型如何切分、如何通信",
            [("DDP / FSDP", BLUE_LIGHT, BLUE), ("DeepSpeed", BLUE_LIGHT, BLUE), ("Megatron / JAX", BLUE_LIGHT, BLUE)],
            BLUE,
        ),
        (
            "启动与执行",
            "建立 Rank、World 与重试",
            [("torchrun", PURPLE_LIGHT, PURPLE), ("Ray Train", PURPLE_LIGHT, PURPLE), ("MPI Launcher", PURPLE_LIGHT, PURPLE)],
            PURPLE,
        ),
        (
            "控制与调度",
            "整组准入、拓扑与重建",
            [("Kubeflow / JobSet", GREEN_LIGHT, GREEN), ("Kueue / Volcano", GREEN_LIGHT, GREEN), ("Slurm", GREEN_LIGHT, GREEN)],
            GREEN,
        ),
        (
            "状态与存储",
            "保存完整状态并原子发布",
            [("DCP / Orbax", ORANGE_LIGHT, ORANGE), ("本地 NVMe 副本", ORANGE_LIGHT, ORANGE), ("对象 / 共享存储", ORANGE_LIGHT, ORANGE)],
            ORANGE,
        ),
    ]

    for index, (title, description, items, accent) in enumerate(rows):
        y1 = 116 + index * 119
        y2 = y1 + 91
        rounded(draw, (48, y1, 1152, y2), fill=WHITE, outline=LINE, radius=17)
        draw.rounded_rectangle((48, y1, 58, y2), radius=5, fill=accent)
        draw.text((78, y1 + 17), title, font=font(22, bold=True), fill=INK)
        draw.text((78, y1 + 53), description, font=font(14), fill=MUTED)

        start_x = 390
        for item_index, (label, fill_color, text_color) in enumerate(items):
            x1 = start_x + item_index * 244
            pill(draw, (x1, y1 + 25, x1 + 216, y1 + 67), label, fill=fill_color, color=text_color)

        if index < len(rows) - 1:
            x = 340
            draw.line((x, y2 + 3, x, y2 + 24), fill=MUTED, width=3)
            draw.polygon([(x, y2 + 29), (x - 7, y2 + 18), (x + 7, y2 + 18)], fill=MUTED)

    footer(draw, "恢复闭环：发现故障 → 停止旧 World → 排除故障域 → 重建完整 Worker Group → 加载有效 Checkpoint")
    OUT.mkdir(parents=True, exist_ok=True)
    image.save(OUT / "training-stack.png", optimize=True)


def render_failure_recovery() -> None:
    image, draw = canvas()
    heading(
        draw,
        "一台机器故障后，怎样恢复一组同步训练",
        "安全默认值是重建整个 Worker Group，再从最近的完整恢复点继续",
    )

    steps = [
        ("1", "故障检测", "进程 / XID / 网络", BLUE, BLUE_LIGHT),
        ("2", "停止旧 World", "防止残留 Rank 写入", RED, RED_LIGHT),
        ("3", "隔离与重排", "避开故障节点", ORANGE, ORANGE_LIGHT),
        ("4", "加载并校验", "Manifest / Shard / Step", PURPLE, PURPLE_LIGHT),
        ("5", "恢复训练", "核对 Loss 与数据游标", GREEN, GREEN_LIGHT),
    ]
    x_positions = [48, 278, 508, 738, 968]
    for index, ((number, title, note, accent, light), x1) in enumerate(zip(steps, x_positions)):
        x2 = x1 + 184
        rounded(draw, (x1, 127, x2, 258), fill=WHITE, outline=LINE, radius=18)
        draw.ellipse((x1 + 16, 143, x1 + 52, 179), fill=light, outline=accent, width=2)
        center_text(draw, (x1 + 16, 143, x1 + 52, 179), number, font(17, bold=True), accent)
        draw.text((x1 + 16, 190), title, font=font(19, bold=True), fill=INK)
        draw.text((x1 + 16, 225), note, font=font(13), fill=MUTED)
        if index < len(steps) - 1:
            arrow(draw, (x2 + 8, 193), (x_positions[index + 1] - 10, 193), color=MUTED, width=3)

    draw.text((49, 299), "Checkpoint 分层", font=font(21, bold=True), fill=INK)
    draw.text((270, 303), "保存越快越靠近训练，保存越可靠越远离单节点故障域", font=font(15), fill=MUTED)

    storage = [
        (48, "节点本地 NVMe", "高频 · 低延迟", "节点损坏时可能丢失", ORANGE, ORANGE_LIGHT),
        (400, "跨节点局部副本", "覆盖单节点故障", "需要避开同一故障域", PURPLE, PURPLE_LIGHT),
        (752, "对象 / 共享存储", "正式持久恢复点", "Manifest 完成后才发布", GREEN, GREEN_LIGHT),
    ]
    for index, (x1, title, subtitle, detail, accent, light) in enumerate(storage):
        x2 = x1 + 304
        rounded(draw, (x1, 350, x2, 493), fill=WHITE, outline=accent, radius=18, width=2)
        draw.rounded_rectangle((x1 + 18, 369, x1 + 286, 403), radius=12, fill=light)
        center_text(draw, (x1 + 18, 369, x1 + 286, 403), title, font(18, bold=True), accent)
        draw.text((x1 + 22, 421), subtitle, font=font(16, bold=True), fill=INK)
        draw.text((x1 + 22, 456), detail, font=font(14), fill=MUTED)
        if index < len(storage) - 1:
            arrow(draw, (x2 + 11, 422), (storage[index + 1][0] - 10, 422), color=MUTED, width=3)

    rounded(draw, (48, 526, 1152, 612), fill=WHITE, outline=LINE, radius=16)
    draw.text((70, 546), "RPO", font=font(17, bold=True), fill=BLUE)
    draw.text((124, 546), "最多丢失多少训练进度", font=font(15), fill=INK)
    draw.line((370, 541, 370, 593), fill=LINE, width=2)
    draw.text((400, 546), "RTO", font=font(17, bold=True), fill=PURPLE)
    draw.text((454, 546), "多久恢复到稳定产出 Step", font=font(15), fill=INK)
    draw.line((738, 541, 738, 593), fill=LINE, width=2)
    draw.text((768, 546), "验收", font=font(17, bold=True), fill=GREEN)
    draw.text((830, 546), "Step、Loss、数据 Watermark 一致", font=font(15), fill=INK)

    footer(draw, "目录存在不等于恢复点有效：全部 Shard 写完、校验通过并发布完成标志后才能用于恢复")
    OUT.mkdir(parents=True, exist_ok=True)
    image.save(OUT / "failure-recovery.png", optimize=True)


def main() -> None:
    render_training_stack()
    render_failure_recovery()


if __name__ == "__main__":
    main()
