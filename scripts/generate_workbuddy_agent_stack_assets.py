#!/usr/bin/env python3
"""Generate diagrams for the WorkBuddy enterprise Agent stack article."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


WIDTH = 1200
HEIGHT = 675
BACKGROUND = (246, 248, 252)
INK = (15, 23, 42)
MUTED = (71, 85, 105)
BLUE = (37, 99, 235)
CYAN = (8, 145, 178)
GREEN = (22, 163, 74)
ORANGE = (234, 88, 12)
PURPLE = (124, 58, 237)
RED = (220, 38, 38)
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
    draw.text((72, 50), headline, font=font(38, bold=True), fill=INK)
    draw.text((72, 106), subtitle, font=font(21), fill=MUTED)


def rounded_card(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    fill: tuple[int, int, int] = CARD,
    outline: tuple[int, int, int] = (226, 232, 240),
) -> None:
    draw.rounded_rectangle(box, radius=22, fill=fill, outline=outline, width=2)


def centered_text(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    text_font: ImageFont.FreeTypeFont,
    color: tuple[int, int, int] | str,
    spacing: int = 7,
) -> None:
    bounds = draw.multiline_textbbox((0, 0), text, font=text_font, spacing=spacing, align="center")
    text_width = bounds[2] - bounds[0]
    text_height = bounds[3] - bounds[1]
    x = box[0] + (box[2] - box[0] - text_width) / 2
    y = box[1] + (box[3] - box[1] - text_height) / 2 - bounds[1]
    draw.multiline_text((x, y), text, font=text_font, fill=color, spacing=spacing, align="center")


def arrow(draw: ImageDraw.ImageDraw, start: tuple[int, int], end: tuple[int, int]) -> None:
    draw.line((*start, *end), fill=(148, 163, 184), width=5)
    draw.polygon(
        [(end[0] - 13, end[1] - 8), end, (end[0] - 13, end[1] + 8)],
        fill=(148, 163, 184),
    )


def save(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG", optimize=True)
    print(f"generated: {path}")


def workbuddy_map(output: Path) -> None:
    image, draw = canvas()
    title(draw, "从 WorkBuddy 公开能力映射企业 Agent 平台", "产品概念背后，是一套完整的控制面与运行数据面")

    center = (440, 210, 760, 470)
    draw.rounded_rectangle(center, radius=28, fill=INK)
    centered_text(draw, (440, 225, 760, 335), "WorkBuddy\nEnterprise", font(32, bold=True), "white")
    centered_text(draw, (470, 355, 730, 430), "可执行、可管理、\n可评测的 Agent", font(21), (203, 213, 225))

    left_cards = [
        ((70, 190, 340, 300), "Agent + Manifest", "模型、角色、能力与边界", BLUE),
        ((70, 350, 340, 460), "Skill + 专家", "能力、经验与协作流程", PURPLE),
        ((70, 510, 340, 620), "Trace + Evals", "轨迹、数据集与质量基线", GREEN),
    ]
    right_cards = [
        ((860, 190, 1130, 300), "Runtime", "Linux 沙箱与持久工作区", ORANGE),
        ((860, 350, 1130, 460), "Session", "上下文与任务执行状态", CYAN),
        ((860, 510, 1130, 620), "MCP + Connector", "工具、凭据与权限网关", RED),
    ]

    for box, heading, desc, color in left_cards + right_cards:
        rounded_card(draw, box)
        draw.rounded_rectangle((box[0] + 18, box[1] + 17, box[0] + 26, box[3] - 17), radius=4, fill=color)
        draw.text((box[0] + 45, box[1] + 23), heading, font=font(23, bold=True), fill=color)
        draw.text((box[0] + 45, box[1] + 66), desc, font=font(17), fill=MUTED)

    for y in (245, 405, 565):
        arrow(draw, (355, y), (420, y))
        arrow(draw, (780, y), (845, y))

    draw.rounded_rectangle((382, 535, 818, 610), radius=22, fill=(219, 234, 254))
    centered_text(draw, (382, 535, 818, 610), "核心判断：Runtime 与 Connector\n和模型同等重要", font(22, bold=True), BLUE)
    save(image, output)


def enterprise_stack(output: Path) -> None:
    image, draw = canvas()
    title(draw, "企业 Agent 不是一个框架，而是一套分层系统", "模型与编排只是中间两层，生产差距主要来自运行、治理和质量闭环")

    layers = [
        ("入口与交付", "Web · IM · API · 事件 · 文档/工单", (219, 234, 254), BLUE),
        ("Agent 控制面", "Manifest · Catalog · 版本 · 发布 · 预算", (237, 233, 254), PURPLE),
        ("模型与编排", "Model Gateway · Agent Harness · Workflow", (207, 250, 254), CYAN),
        ("工具与知识", "Skill · MCP · Connector · RAG · Memory", (220, 252, 231), GREEN),
        ("执行数据面", "Runtime · Session · Queue · Sandbox", (255, 237, 213), ORANGE),
        ("横向治理", "Identity · Policy · Approval · Trace · Evals · Cost", (254, 226, 226), RED),
    ]

    top = 170
    height = 66
    gap = 13
    for index, (heading, detail, fill, color) in enumerate(layers):
        y1 = top + index * (height + gap)
        y2 = y1 + height
        rounded_card(draw, (95, y1, 1105, y2), fill=fill, outline=fill)
        draw.rounded_rectangle((115, y1 + 13, 325, y2 - 13), radius=15, fill=color)
        centered_text(draw, (115, y1 + 13, 325, y2 - 13), heading, font(21, bold=True), "white")
        draw.text((365, y1 + 21), detail, font=font(22), fill=INK)

    draw.text((96, 646), "选型原则：按业务副作用决定层级，不要为只读问答配置一台完整云电脑", font=font(19, bold=True), fill=MUTED)
    save(image, output)


def adoption_path(output: Path) -> None:
    image, draw = canvas()
    title(draw, "企业 Agent 建设顺序", "先证明业务闭环，再逐步增加自主性、隔离强度与组织规模")

    steps = [
        ("1", "任务", "边界明确\n结果可验收", BLUE),
        ("2", "身份", "真实用户\n只读工具", CYAN),
        ("3", "闭环", "模型网关\n单 Agent", PURPLE),
        ("4", "运行", "按副作用\n选择沙箱", ORANGE),
        ("5", "质量", "Trace\n回归评测", GREEN),
        ("6", "扩展", "多 Agent\n长期记忆", RED),
    ]

    left = 48
    top = 225
    card_width = 165
    gap = 31
    for index, (number, heading, detail, color) in enumerate(steps):
        x1 = left + index * (card_width + gap)
        x2 = x1 + card_width
        rounded_card(draw, (x1, top, x2, 485))
        draw.ellipse((x1 + 54, top + 23, x1 + 111, top + 80), fill=color)
        centered_text(draw, (x1 + 54, top + 23, x1 + 111, top + 80), number, font(24, bold=True, latin=True), "white")
        centered_text(draw, (x1 + 15, top + 100, x2 - 15, top + 155), heading, font(25, bold=True), INK)
        centered_text(draw, (x1 + 15, top + 165, x2 - 15, top + 235), detail, font(19), MUTED)
        if index < len(steps) - 1:
            arrow(draw, (x2 + 5, top + 130), (x2 + 25, top + 130))

    draw.rounded_rectangle((177, 550, 1023, 620), radius=20, fill=(219, 234, 254))
    centered_text(
        draw,
        (177, 550, 1023, 620),
        "停止条件：没有成功指标、身份边界和失败样本时，不进入下一阶段",
        font(22, bold=True),
        BLUE,
    )
    save(image, output)


def main() -> None:
    output_dir = Path("docs/assets/rag-agent/workbuddy-enterprise-agent-stack")
    workbuddy_map(output_dir / "01-workbuddy-map.png")
    enterprise_stack(output_dir / "02-enterprise-stack.png")
    adoption_path(output_dir / "03-adoption-path.png")


if __name__ == "__main__":
    main()
