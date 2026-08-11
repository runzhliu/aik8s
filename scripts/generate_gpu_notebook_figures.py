#!/usr/bin/env python3
"""Generate diagrams for the GPU Notebook platform evolution article."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


WIDTH = 1200
BG = "#F7F9FC"
INK = "#172033"
MUTED = "#5E6B82"
BLUE = "#2563EB"
BLUE_LIGHT = "#EAF2FF"
TEAL = "#0F9D8A"
TEAL_LIGHT = "#E7F8F5"
ORANGE = "#F37726"
RED = "#D94B5B"
LINE = "#C9D4E6"
WHITE = "#FFFFFF"

FONT_CN = Path("/System/Library/Fonts/Hiragino Sans GB.ttc")
FONT_LATIN = Path("/System/Library/Fonts/HelveticaNeue.ttc")


def font(size: int, *, bold: bool = False, latin: bool = False) -> ImageFont.FreeTypeFont:
    path = FONT_LATIN if latin else FONT_CN
    index = 1 if bold and path == FONT_CN else 0
    return ImageFont.truetype(str(path), size=size, index=index)


def canvas(height: int) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (WIDTH, height), BG)
    return image, ImageDraw.Draw(image, "RGBA")


def rounded(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], *, fill: str = WHITE,
            outline: str = LINE, radius: int = 20, width: int = 2) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def center_text(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], text: str,
                text_font: ImageFont.FreeTypeFont, fill: str = INK, spacing: int = 8) -> None:
    left, top, right, bottom = box
    bounds = draw.multiline_textbbox((0, 0), text, font=text_font, spacing=spacing, align="center")
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    draw.multiline_text(
        ((left + right - width) / 2, (top + bottom - height) / 2 - bounds[1]),
        text,
        font=text_font,
        fill=fill,
        spacing=spacing,
        align="center",
    )


def paste_contain(base: Image.Image, path: Path, box: tuple[int, int, int, int]) -> None:
    icon = Image.open(path).convert("RGBA")
    left, top, right, bottom = box
    max_width, max_height = right - left, bottom - top
    icon.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
    x = left + (max_width - icon.width) // 2
    y = top + (max_height - icon.height) // 2
    base.paste(icon, (x, y), icon)


def arrow(draw: ImageDraw.ImageDraw, start: tuple[int, int], end: tuple[int, int], color: str = BLUE) -> None:
    draw.line((start, end), fill=color, width=4)
    ex, ey = end
    draw.polygon(((ex, ey), (ex - 12, ey - 8), (ex - 12, ey + 8)), fill=color)


def title(draw: ImageDraw.ImageDraw, heading: str, subheading: str) -> None:
    draw.text((55, 38), heading, font=font(34, bold=True), fill=INK)
    draw.text((57, 88), subheading, font=font(19), fill=MUTED)


def evolution(output: Path, logos: Path) -> None:
    image, draw = canvas(600)
    title(draw, "GPU 开发入口与控制面的演进", "从 Jupyter Server 启动器，演进为同时管理 IDE、容器和虚拟机的 Workspace 控制面")

    cards = [
        (45, 150, 285, 435),
        (345, 150, 585, 435),
        (645, 150, 885, 435),
        (945, 150, 1185, 435),
    ]
    for box in cards:
        rounded(draw, box)

    paste_contain(image, logos / "jupyterhub.png", (75, 175, 255, 250))
    center_text(draw, (60, 250, 270, 300), "JupyterHub", font(25, bold=True, latin=True))
    center_text(draw, (60, 305, 270, 410), "KubeSpawner\n标准 Jupyter Server", font(18), MUTED)

    paste_contain(image, logos / "code-server.png", (425, 170, 505, 250))
    center_text(draw, (360, 250, 570, 300), "code-server", font(25, bold=True, latin=True))
    center_text(draw, (360, 305, 570, 410), "代码仓库、终端、插件\nCoding Agent 工作区", font(18), MUTED)

    draw.regular_polygon((765, 213, 46), n_sides=6, rotation=30, fill=BLUE, outline="#1749B5")
    center_text(draw, (730, 180, 800, 245), "OP", font(22, bold=True, latin=True), WHITE)
    center_text(draw, (660, 250, 870, 300), "Workspace Operator", font(22, bold=True, latin=True))
    center_text(draw, (660, 305, 870, 410), "统一管理规格、存储\n生命周期与访问入口", font(18), MUTED)

    paste_contain(image, logos / "kubevirt.png", (1025, 170, 1105, 250))
    center_text(draw, (960, 250, 1170, 300), "KubeVirt", font(25, bold=True, latin=True))
    center_text(draw, (960, 305, 1170, 410), "完整 guest 根盘\n停止后释放计算资源", font(18), MUTED)

    arrow(draw, (290, 292), (335, 292))
    arrow(draw, (590, 292), (635, 292))
    arrow(draw, (890, 292), (935, 292))

    rounded(draw, (210, 475, 990, 555), fill=TEAL_LIGHT, outline="#9DDDD3", radius=16)
    paste_contain(image, logos / "ceph.png", (230, 489, 320, 540))
    draw.text((345, 490), "Ceph RBD 保存个人 Home / VM 根盘", font=font(20, bold=True), fill=INK)
    draw.text((345, 522), "CephFS 只承载明确的团队共享目录", font=font(18), fill=MUTED)

    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG", optimize=True)


def gpu_sharing(output: Path) -> None:
    image, draw = canvas(650)
    title(draw, "组级八卡开发机共享", "资源边界放到团队；用户通过实时归因看板发现资源大户并在组内协商")

    rounded(draw, (45, 145, 250, 555), fill=WHITE)
    draw.text((85, 170), "算法组用户", font=font(24, bold=True), fill=INK)
    user_colors = [BLUE, TEAL, ORANGE, RED]
    for index, color in enumerate(user_colors):
        y = 245 + index * 70
        draw.ellipse((75, y, 115, y + 40), fill=color)
        draw.text((130, y + 6), f"用户 {chr(65 + index)}", font=font(18), fill=INK)

    rounded(draw, (320, 145, 790, 555), fill=BLUE_LIGHT, outline="#8BB4FF")
    draw.text((430, 170), "团队 GPU 资源池", font=font(26, bold=True), fill=INK)
    for node_index, top in enumerate((235, 385), 1):
        rounded(draw, (355, top, 755, top + 115), fill=WHITE, outline="#AFC8F7", radius=14)
        draw.text((375, top + 16), f"8-GPU 开发机 A{node_index}", font=font(20, bold=True), fill=INK)
        for gpu in range(8):
            x = 375 + gpu * 44
            draw.rounded_rectangle((x, top + 58, x + 34, top + 91), radius=6, fill="#2459B8")
            center_text(draw, (x, top + 58, x + 34, top + 91), str(gpu), font(13, bold=True, latin=True), WHITE)

    rounded(draw, (850, 145, 1155, 555), fill=WHITE)
    draw.text((900, 170), "实时资源归因", font=font(24, bold=True), fill=INK)
    metrics = [("CPU", 0.78, BLUE), ("Memory", 0.62, TEAL), ("GPU", 0.91, ORANGE), ("GPU Mem", 0.84, RED)]
    for index, (label, value, color) in enumerate(metrics):
        y = 245 + index * 62
        draw.text((885, y), label, font=font(16, latin=True), fill=INK)
        draw.rounded_rectangle((970, y, 1125, y + 22), radius=11, fill="#E7ECF5")
        draw.rounded_rectangle((970, y, 970 + int(155 * value), y + 22), radius=11, fill=color)
        draw.text((1085, y + 28), f"用户 {chr(65 + index)}", font=font(14), fill=MUTED)
    center_text(draw, (875, 485, 1135, 535), "可见 → 归因 → 组内协商", font(18, bold=True), BLUE)

    arrow(draw, (255, 350), (310, 350))
    arrow(draw, (795, 350), (840, 350))
    center_text(draw, (80, 580, 1120, 630), "适合可信团队的突发式开发；正式训练和性能压测仍进入队列或独占资源", font(18), MUTED)

    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG", optimize=True)


def final_architecture(output: Path, logos: Path) -> None:
    image, draw = canvas(780)
    title(draw, "最终工作区与存储分层", "容器保证标准化和密度；KubeVirt 提供完整环境恢复；RBD 与 CephFS 按访问语义分工")

    rounded(draw, (410, 135, 790, 220), fill=BLUE, outline="#1749B5")
    center_text(draw, (410, 135, 790, 220), "Workspace Operator", font(26, bold=True, latin=True), WHITE)

    rounded(draw, (75, 300, 520, 510), fill=WHITE, outline="#91B5F5")
    paste_contain(image, logos / "code-server.png", (105, 325, 175, 395))
    draw.text((195, 330), "Container Workspace", font=font(23, bold=True, latin=True), fill=INK)
    draw.text((195, 370), "code-server / JupyterLab", font=font(18, latin=True), fill=MUTED)
    draw.text((110, 425), "启动快 · 密度高 · 基础镜像标准化", font=font(18), fill=INK)
    rounded(draw, (110, 465, 485, 495), fill=BLUE_LIGHT, outline="#AEC8F8", radius=10)
    center_text(draw, (110, 465, 485, 495), "Personal Home → Ceph RBD PVC", font(16, bold=True, latin=True), BLUE)

    rounded(draw, (680, 300, 1125, 510), fill=WHITE, outline="#7DD6C8")
    paste_contain(image, logos / "kubevirt.png", (710, 325, 780, 395))
    draw.text((800, 330), "KubeVirt Workspace", font=font(23, bold=True, latin=True), fill=INK)
    draw.text((800, 370), "完整 Linux / 任意安装路径", font=font(18), fill=MUTED)
    draw.text((715, 425), "停止释放计算 · 重启恢复完整系统", font=font(18), fill=INK)
    rounded(draw, (715, 465, 1090, 495), fill=TEAL_LIGHT, outline="#9CDDD3", radius=10)
    center_text(draw, (715, 465, 1090, 495), "Root Disk → Ceph RBD", font(16, bold=True, latin=True), TEAL)

    draw.line((600, 220, 600, 260), fill=BLUE, width=4)
    draw.line((300, 260, 900, 260), fill=BLUE, width=4)
    draw.line((300, 260, 300, 290), fill=BLUE, width=4)
    draw.line((900, 260, 900, 290), fill=BLUE, width=4)
    draw.polygon(((300, 300), (292, 286), (308, 286)), fill=BLUE)
    draw.polygon(((900, 300), (892, 286), (908, 286)), fill=BLUE)

    rounded(draw, (75, 580, 1125, 725), fill="#F1F5F9", outline=LINE, radius=18)
    paste_contain(image, logos / "ceph.png", (100, 605, 210, 695))
    blocks = [
        (245, "CephFS /shared", "团队共享 · RWX · ACL"),
        (505, "Object / Registry", "模型 · 数据 · Checkpoint"),
        (805, "Local NVMe", "模型缓存 · Scratch"),
    ]
    for x, heading, detail in blocks:
        draw.text((x, 615), heading, font=font(19, bold=True, latin=True), fill=INK)
        draw.text((x, 660), detail, font=font(16), fill=MUTED)

    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG", optimize=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--logos-dir", type=Path, required=True)
    args = parser.parse_args()

    evolution(args.output_dir / "01-platform-evolution.png", args.logos_dir)
    gpu_sharing(args.output_dir / "02-gpu-team-sharing.png")
    final_architecture(args.output_dir / "03-final-architecture.png", args.logos_dir)
    print(f"generated figures in: {args.output_dir}")


if __name__ == "__main__":
    main()
