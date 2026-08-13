#!/usr/bin/env python3
"""Generate body charts for the GPU monitor Exit 139 WeChat article."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


WIDTH = 1200
HEIGHT = 675
BACKGROUND = (246, 248, 252)
INK = (15, 23, 42)
MUTED = (71, 85, 105)
BLUE = (37, 99, 235)
RED = (220, 38, 38)
GREEN = (22, 163, 74)
CARD = (255, 255, 255)
CHINESE = Path("/System/Library/Fonts/Hiragino Sans GB.ttc")
LATIN = Path("/System/Library/Fonts/HelveticaNeue.ttc")


def font(size: int, bold: bool = False, latin: bool = False) -> ImageFont.FreeTypeFont:
    path = LATIN if latin else CHINESE
    index = 1 if bold and path == CHINESE else 0
    return ImageFont.truetype(str(path), size=size, index=index)


def canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
    return image, ImageDraw.Draw(image, "RGBA")


def title(draw: ImageDraw.ImageDraw, headline: str, subtitle: str) -> None:
    draw.text((72, 55), headline, font=font(38, bold=True), fill=INK)
    draw.text((72, 112), subtitle, font=font(22), fill=MUTED)


def rounded_card(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int]) -> None:
    draw.rounded_rectangle(box, radius=24, fill=CARD, outline=(226, 232, 240), width=2)


def save(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG", optimize=True)
    print(f"generated: {path}")


def nvitop_role(output: Path) -> None:
    image, draw = canvas()
    title(draw, "nvitop 在平台里承担两层能力", "同一套 NVML 采集栈，同时服务平台监控与业务现场排障")

    rounded_card(draw, (72, 220, 310, 475))
    draw.text((112, 270), "GPU / Driver", font=font(25, bold=True), fill=INK)
    draw.text((112, 328), "NVML 数据源", font=font(22), fill=MUTED)
    draw.rounded_rectangle((112, 385, 270, 430), radius=16, fill=(219, 234, 254))
    draw.text((141, 396), "节点侧", font=font(20, bold=True), fill=BLUE)

    draw.line((328, 347, 390, 347), fill=(148, 163, 184), width=5)
    draw.polygon([(390, 337), (408, 347), (390, 357)], fill=(148, 163, 184))

    draw.rounded_rectangle((410, 220, 705, 475), radius=24, fill=(15, 23, 42))
    draw.text((467, 265), "nvitop / NVML", font=font(29, bold=True), fill="white")
    draw.text((466, 328), "统一 GPU 查询能力", font=font(22), fill=(203, 213, 225))
    draw.rounded_rectangle((466, 385, 649, 430), radius=16, fill=(30, 64, 175))
    draw.text((493, 396), "同一调用栈", font=font(20, bold=True), fill="white")

    draw.line((723, 285, 774, 285), fill=(148, 163, 184), width=5)
    draw.polygon([(774, 275), (792, 285), (774, 295)], fill=(148, 163, 184))
    draw.line((723, 410, 774, 410), fill=(148, 163, 184), width=5)
    draw.polygon([(774, 400), (792, 410), (774, 420)], fill=(148, 163, 184))

    draw.rounded_rectangle((794, 185, 1128, 340), radius=24, fill=CARD, outline=(226, 232, 240), width=2)
    draw.text((826, 215), "平台监控层", font=font(24, bold=True), fill=BLUE)
    draw.text((826, 257), "nvitop-exporter → Prometheus", font=font(20), fill=INK)
    draw.text((826, 295), "补充、替代部分 DCGM 指标", font=font(19), fill=MUTED)

    draw.rounded_rectangle((794, 370, 1128, 525), radius=24, fill=CARD, outline=(226, 232, 240), width=2)
    draw.text((826, 400), "业务排障层", font=font(24, bold=True), fill=GREEN)
    draw.text((826, 442), "登录环境 → 执行 nvitop", font=font(20), fill=INK)
    draw.text((826, 480), "定位进程、显存和 GPU 利用率", font=font(19), fill=MUTED)

    draw.rounded_rectangle((207, 575, 993, 630), radius=20, fill=(254, 226, 226))
    draw.text((248, 589), "组件反复崩溃 = 平台指标断点 + 现场查询能力不可信", font=font(22, bold=True), fill=RED)
    save(image, output)


def incident_scope(output: Path) -> None:
    image, draw = canvas()
    title(draw, "故障边界不是随机的", "相同镜像，问题几乎全部集中在 H20 / 580 驱动节点")

    cards = [(72, 175, 560, 555), (640, 175, 1128, 555)]
    for box in cards:
        rounded_card(draw, box)

    draw.text((112, 220), "RTX Ada / 570", font=font(28, bold=True), fill=INK)
    draw.text((112, 274), "99", font=font(66, bold=True, latin=True), fill=BLUE)
    draw.text((210, 306), "个 Pod", font=font(23), fill=MUTED)
    draw.rounded_rectangle((112, 375, 505, 425), radius=18, fill=(219, 234, 254))
    draw.text((132, 385), "有重启：0", font=font(22, bold=True), fill=BLUE)
    draw.text((112, 463), "累计重启  0", font=font(25, bold=True), fill=GREEN)

    draw.text((680, 220), "H20 / 580", font=font(28, bold=True), fill=INK)
    draw.text((680, 274), "108", font=font(66, bold=True, latin=True), fill=RED)
    draw.text((824, 306), "个 Pod", font=font(23), fill=MUTED)
    draw.rounded_rectangle((680, 375, 1073, 425), radius=18, fill=(254, 226, 226))
    draw.text((700, 385), "有重启：106", font=font(22, bold=True), fill=RED)
    draw.text((680, 463), "累计重启  11,648", font=font(25, bold=True), fill=RED)

    draw.text((72, 610), "证据方向：GPU 类型 → 驱动 → NVML / Python Binding", font=font(21), fill=MUTED)
    save(image, output)


def investigation_timeline(output: Path) -> None:
    image, draw = canvas()
    title(draw, "两次修复为什么都没有闭环", "每一次失败都必须转化成下一步可以验证的证据")

    steps = [
        ("假设 1", "旧组件不兼容", "升级依赖", RED),
        ("反证 1", "pip 是新版本", "进程仍加载旧源码", BLUE),
        ("假设 2", "修正导入路径", "5 分钟 Canary 通过", RED),
        ("反证 2", "全量再次 Exit 139", "短测覆盖不足", BLUE),
        ("关键证据", "Core Dump\n+ GDB", "NVLink 查询触发", GREEN),
    ]

    left = 60
    top = 205
    card_width = 200
    gap = 30
    for index, (label, line1, line2, color) in enumerate(steps):
        x1 = left + index * (card_width + gap)
        x2 = x1 + card_width
        rounded_card(draw, (x1, top, x2, 500))
        draw.rounded_rectangle((x1 + 20, top + 25, x2 - 20, top + 68), radius=16, fill=color)
        label_box = draw.textbbox((0, 0), label, font=font(20, bold=True))
        label_width = label_box[2] - label_box[0]
        draw.text((x1 + (card_width - label_width) / 2, top + 32), label, font=font(20, bold=True), fill="white")
        draw.multiline_text((x1 + 24, top + 112), line1, font=font(22, bold=True), fill=INK, spacing=8)
        draw.multiline_text((x1 + 24, top + 202), line2, font=font(19), fill=MUTED, spacing=8)
        if index < len(steps) - 1:
            arrow_x = x2 + 8
            arrow_y = top + 145
            draw.line((arrow_x, arrow_y, arrow_x + 15, arrow_y), fill=(148, 163, 184), width=4)
            draw.polygon(
                [(arrow_x + 15, arrow_y - 7), (arrow_x + 27, arrow_y), (arrow_x + 15, arrow_y + 7)],
                fill=(148, 163, 184),
            )

    draw.rounded_rectangle((253, 555, 947, 615), radius=20, fill=(220, 252, 231))
    draw.text((284, 570), "最终策略：绕开高风险查询，保留核心 GPU 指标，并持续观察", font=font(22, bold=True), fill=(21, 128, 61))
    save(image, output)


def main() -> None:
    output_dir = Path("articles/wechat/assets/gpu-monitor-incident")
    nvitop_role(output_dir / "00-nvitop-role.png")
    incident_scope(output_dir / "01-incident-scope.png")
    investigation_timeline(output_dir / "02-investigation-timeline.png")


if __name__ == "__main__":
    main()
