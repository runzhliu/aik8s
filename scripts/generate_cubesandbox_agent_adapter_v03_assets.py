#!/usr/bin/env python3
"""Generate light-mode visuals for the CubeSandbox Agent Adapter v0.3 articles."""

from __future__ import annotations

import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
ARTICLE_DIR = ROOT / "articles/wechat/assets/cubesandbox-agent-adapter-v03"
DOC_DIR = ROOT / "docs/assets/rag-agent/cubesandbox-agent-adapter-v03"
LANDSCAPE_COVER = ROOT / "articles/wechat/assets/cubesandbox-agent-adapter-v03-cover.png"
SQUARE_COVER = ROOT / "articles/wechat/assets/cubesandbox-agent-adapter-v03-cover-square.png"
SOURCE_EVIDENCE = ROOT.parent / "cubesandbox-agent-adapter/docs/assets/v0.3-acceptance"

CHINESE = Path("/System/Library/Fonts/Hiragino Sans GB.ttc")
LATIN = Path("/System/Library/Fonts/HelveticaNeue.ttc")

INK = (17, 35, 61)
MUTED = (77, 96, 121)
BLUE = (37, 99, 235)
CYAN = (6, 166, 193)
VIOLET = (108, 81, 221)
GREEN = (25, 150, 104)
ORANGE = (235, 124, 43)
RED = (215, 74, 74)
PAPER = (247, 250, 253)
WHITE = (255, 255, 255)
LINE = (207, 221, 237)
PALE_BLUE = (231, 240, 255)
PALE_CYAN = (227, 247, 250)
PALE_VIOLET = (240, 235, 255)
PALE_GREEN = (231, 248, 239)
PALE_ORANGE = (255, 241, 229)


def font(path: Path, size: int, index: int = 0) -> ImageFont.FreeTypeFont:
    if not path.exists():
        raise FileNotFoundError(f"font not found: {path}")
    return ImageFont.truetype(str(path), size=size, index=index)


def text_width(draw: ImageDraw.ImageDraw, text: str, face: ImageFont.FreeTypeFont) -> int:
    box = draw.textbbox((0, 0), text, font=face)
    return box[2] - box[0]


def centered(
    draw: ImageDraw.ImageDraw,
    center_x: float,
    y: float,
    text: str,
    face: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int],
) -> None:
    draw.text((center_x - text_width(draw, text, face) / 2, y), text, font=face, fill=fill)


def grid(draw: ImageDraw.ImageDraw, width: int, height: int, step: int) -> None:
    color = (229, 236, 245)
    for x in range(0, width, step):
        draw.line((x, 0, x, height), fill=color, width=1)
    for y in range(0, height, step):
        draw.line((0, y, width, y), fill=color, width=1)


def rounded_card(
    draw: ImageDraw.ImageDraw,
    bounds: tuple[int, int, int, int],
    *,
    fill: tuple[int, int, int] = WHITE,
    outline: tuple[int, int, int] = LINE,
    width: int = 2,
    radius: int = 20,
) -> None:
    draw.rounded_rectangle(bounds, radius=radius, fill=fill, outline=outline, width=width)


def arrow(
    draw: ImageDraw.ImageDraw,
    start: tuple[int, int],
    end: tuple[int, int],
    color: tuple[int, int, int] = BLUE,
    width: int = 4,
) -> None:
    draw.line((*start, *end), fill=color, width=width)
    direction = 1 if end[0] >= start[0] else -1
    draw.polygon(
        [
            end,
            (end[0] - direction * 13, end[1] - 8),
            (end[0] - direction * 13, end[1] + 8),
        ],
        fill=color,
    )


def pill(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    label: str,
    *,
    fill: tuple[int, int, int] = PALE_BLUE,
    outline: tuple[int, int, int] = BLUE,
    size: int = 15,
) -> int:
    face = font(CHINESE, size)
    width = text_width(draw, label, face) + 30
    height = size + 25
    draw.rounded_rectangle((x, y, x + width, y + height), radius=height // 2, fill=fill, outline=outline)
    draw.text((x + 15, y + 8), label, font=face, fill=outline)
    return width


def cube_icon(draw: ImageDraw.ImageDraw, cx: int, cy: int, scale: float = 1.0) -> None:
    top = [(cx, cy - int(54 * scale)), (cx + int(58 * scale), cy - int(24 * scale)), (cx, cy + int(7 * scale)), (cx - int(58 * scale), cy - int(24 * scale))]
    left = [(cx - int(58 * scale), cy - int(24 * scale)), (cx, cy + int(7 * scale)), (cx, cy + int(74 * scale)), (cx - int(58 * scale), cy + int(42 * scale))]
    right = [(cx, cy + int(7 * scale)), (cx + int(58 * scale), cy - int(24 * scale)), (cx + int(58 * scale), cy + int(42 * scale)), (cx, cy + int(74 * scale))]
    draw.polygon(top, fill=PALE_CYAN, outline=CYAN)
    draw.polygon(left, fill=(84, 140, 244), outline=BLUE)
    draw.polygon(right, fill=BLUE, outline=(24, 78, 190))
    draw.line((cx, cy + int(7 * scale), cx, cy + int(74 * scale)), fill=WHITE, width=max(2, int(3 * scale)))
    centered(draw, cx, cy - int(15 * scale), ">_", font(LATIN, max(14, int(22 * scale)), 1), INK)


def agent_node(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    label: str,
    short: str,
    color: tuple[int, int, int],
    pale: tuple[int, int, int],
    *,
    width: int = 132,
) -> None:
    rounded_card(draw, (x, y, x + width, y + 66), fill=pale, outline=color, radius=15)
    draw.ellipse((x + 13, y + 16, x + 47, y + 50), fill=color)
    centered(draw, x + 30, y + 23, short, font(LATIN, 13, 1), WHITE)
    draw.text((x + 56, y + 21), label, font=font(LATIN, 14, 1), fill=INK)


def cover_landscape() -> Path:
    image = Image.new("RGB", (900, 383), PAPER)
    draw = ImageDraw.Draw(image)
    grid(draw, 900, 383, 42)
    rounded_card(draw, (28, 24, 872, 359), radius=28)
    draw.rectangle((28, 24, 40, 359), fill=BLUE)
    draw.text((70, 48), "v0.3.0 · 4 Clients · 13 Tools", font=font(LATIN, 15, 1), fill=BLUE)
    draw.text((67, 88), "CubeSandbox Agent Adapter", font=font(LATIN, 31, 1), fill=INK)
    draw.text((70, 137), "长任务、回滚和分支都进了控制面", font=font(CHINESE, 26), fill=INK)
    offset = 70
    for label, color, pale in [
        ("Persistent", BLUE, PALE_BLUE),
        ("Job / PTY", CYAN, PALE_CYAN),
        ("Fork", VIOLET, PALE_VIOLET),
    ]:
        offset += pill(draw, offset, 205, label, fill=pale, outline=color, size=14) + 10
    draw.text((70, 280), "OpenClaw · DSH · Hermes · Codex", font=font(LATIN, 16, 1), fill=MUTED)
    draw.text((70, 322), "AIK8S.RUN", font=font(LATIN, 12, 1), fill=CYAN)

    agent_node(draw, 565, 55, "OpenClaw", "O", BLUE, PALE_BLUE, width=142)
    agent_node(draw, 714, 55, "DSH", "D", CYAN, PALE_CYAN, width=124)
    agent_node(draw, 565, 286, "Hermes", "H", VIOLET, PALE_VIOLET, width=142)
    agent_node(draw, 714, 286, "Codex", "C", GREEN, PALE_GREEN, width=124)
    cube_icon(draw, 702, 184, 0.86)
    for start, end, color in [
        ((635, 121), (671, 145), BLUE),
        ((776, 121), (735, 145), CYAN),
        ((635, 286), (671, 226), VIOLET),
        ((776, 286), (735, 226), GREEN),
    ]:
        draw.line((*start, *end), fill=color, width=3)
    centered(draw, 702, 250, "CubeSandbox", font(LATIN, 14, 1), INK)
    image.save(LANDSCAPE_COVER, format="PNG", optimize=True)
    return LANDSCAPE_COVER


def cover_square() -> Path:
    image = Image.new("RGB", (900, 900), PAPER)
    draw = ImageDraw.Draw(image)
    grid(draw, 900, 900, 54)
    rounded_card(draw, (52, 46, 848, 854), radius=42)
    draw.rectangle((52, 46, 848, 59), fill=BLUE)
    draw.text((92, 100), "v0.3.0 · 4 Clients · 13 Tools", font=font(LATIN, 21, 1), fill=BLUE)
    draw.text((87, 158), "CubeSandbox", font=font(LATIN, 64, 1), fill=INK)
    draw.text((90, 239), "Agent Adapter", font=font(LATIN, 58, 1), fill=INK)
    draw.text((91, 322), "长任务 · 回滚 · 分支", font=font(CHINESE, 40), fill=INK)
    cube_icon(draw, 450, 512, 1.35)
    nodes = [
        (135, 442, "OpenClaw", "O", BLUE, PALE_BLUE),
        (618, 442, "DSH", "D", CYAN, PALE_CYAN),
        (135, 622, "Hermes", "H", VIOLET, PALE_VIOLET),
        (618, 622, "Codex", "C", GREEN, PALE_GREEN),
    ]
    for x, y, label, short, color, pale in nodes:
        agent_node(draw, x, y, label, short, color, pale, width=150)
    for start, end, color in [
        ((285, 475), (366, 500), BLUE),
        ((618, 475), (535, 500), CYAN),
        ((285, 655), (377, 572), VIOLET),
        ((618, 655), (523, 572), GREEN),
    ]:
        draw.line((*start, *end), fill=color, width=4)
    centered(draw, 450, 625, "CubeSandbox MicroVM", font(LATIN, 18, 1), INK)
    centered(draw, 450, 752, "Persistent · Job / PTY · Checkpoint / Fork", font(LATIN, 19, 1), MUTED)
    draw.text((712, 814), "AIK8S.RUN", font=font(LATIN, 13, 1), fill=CYAN)
    image.save(SQUARE_COVER, format="PNG", optimize=True)
    return SQUARE_COVER


def canvas(title: str, subtitle: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (1200, 675), PAPER)
    draw = ImageDraw.Draw(image)
    rounded_card(draw, (42, 38, 1158, 637), radius=28)
    draw.rectangle((42, 38, 54, 637), fill=BLUE)
    draw.text((88, 68), title, font=font(CHINESE, 35), fill=INK)
    draw.text((90, 120), subtitle, font=font(CHINESE, 18), fill=MUTED)
    return image, draw


def architecture() -> Path:
    image, draw = canvas(
        "四种 Agent，共用一个策略控制面",
        "模型只选择动作；身份、Profile、租约、凭据与回收由 Adapter 管理",
    )

    agents = [
        (82, 190, "OpenClaw", "Tool Plugin", BLUE, PALE_BLUE),
        (82, 284, "DSH", "Cordis Plugin", CYAN, PALE_CYAN),
        (82, 378, "Hermes", "Native Plugin", VIOLET, PALE_VIOLET),
        (82, 472, "Codex", "MCP stdio", GREEN, PALE_GREEN),
    ]
    for x, y, name, detail, color, pale in agents:
        rounded_card(draw, (x, y, x + 235, y + 72), fill=pale, outline=color, radius=16)
        draw.text((x + 20, y + 13), name, font=font(LATIN, 18, 1), fill=INK)
        draw.text((x + 20, y + 42), detail, font=font(LATIN, 14), fill=MUTED)
        arrow(draw, (x + 235, y + 36), (385, y + 36), color, 3)

    rounded_card(draw, (386, 190, 765, 544), fill=(246, 249, 255), outline=BLUE, width=3, radius=24)
    draw.text((420, 215), "CubeSandbox Agent Adapter", font=font(LATIN, 24, 1), fill=INK)
    blocks = [
        (420, 270, 710, 322, "多租户认证 · Profile 配额", PALE_BLUE, BLUE),
        (420, 337, 710, 389, "加密租约 · Redis 分布式锁", PALE_CYAN, CYAN),
        (420, 404, 710, 456, "Job / PTY · 文件 · Checkpoint", PALE_VIOLET, VIOLET),
        (420, 471, 710, 523, "脱敏审计 · Metrics · GC", PALE_GREEN, GREEN),
    ]
    for x1, y1, x2, y2, label, pale, color in blocks:
        rounded_card(draw, (x1, y1, x2, y2), fill=pale, outline=color, radius=12)
        centered(draw, (x1 + x2) / 2, y1 + 14, label, font(CHINESE, 16), INK)

    arrow(draw, (765, 367), (838, 367), BLUE, 4)
    rounded_card(draw, (840, 190, 1118, 544), fill=PALE_ORANGE, outline=ORANGE, width=3, radius=24)
    centered(draw, 979, 216, "CubeSandbox", font(LATIN, 26, 1), INK)
    cube_icon(draw, 979, 341, 1.08)
    centered(draw, 979, 444, "Cube SDK  to  MicroVM", font(LATIN, 17, 1), MUTED)
    centered(draw, 979, 480, "Full ID / Traffic Token", font(LATIN, 14), MUTED)
    centered(draw, 979, 509, "只留在控制面", font(CHINESE, 15), ORANGE)

    draw.text((84, 588), "Fail closed", font=font(LATIN, 15, 1), fill=RED)
    draw.text((184, 588), "·", font=font(LATIN, 15, 1), fill=MUTED)
    draw.text((201, 588), "无可用后端或策略校验失败时，不回退宿主 Shell", font=font(CHINESE, 16), fill=MUTED)
    path = ARTICLE_DIR / "architecture.png"
    image.save(path, format="PNG", optimize=True)
    return path


def trusted_execution_boundary() -> Path:
    image, draw = canvas(
        "本地 Code Agent 不进生产，动作进入受控沙箱",
        "把 VPN、SSH 与长期凭据，收敛为可认证、可授权、可隔离、可审计的执行请求",
    )

    rounded_card(draw, (78, 178, 326, 535), fill=PALE_BLUE, outline=BLUE, radius=22)
    centered(draw, 202, 202, "办公网 / 开发者本地", font(CHINESE, 19), BLUE)
    draw.rounded_rectangle((118, 265, 286, 372), radius=12, fill=WHITE, outline=BLUE, width=3)
    draw.rectangle((133, 281, 271, 348), fill=(239, 244, 251))
    centered(draw, 202, 297, "Code Agent", font(LATIN, 20, 1), INK)
    centered(draw, 202, 326, "OpenClaw · DSH · Codex", font(LATIN, 11), MUTED)
    draw.polygon([(104, 389), (300, 389), (274, 411), (130, 411)], fill=(205, 220, 242), outline=BLUE)
    centered(draw, 202, 443, "模型与会话留在本地", font(CHINESE, 16), INK)
    centered(draw, 202, 477, "不持有生产 SSH / 长期凭据", font(CHINESE, 14), MUTED)

    rounded_card(draw, (382, 178, 742, 535), fill=(248, 251, 255), outline=CYAN, width=3, radius=22)
    centered(draw, 562, 202, "公司批准的窄入口", font(CHINESE, 19), CYAN)
    rounded_card(draw, (420, 256, 704, 319), fill=PALE_CYAN, outline=CYAN, radius=14)
    centered(draw, 562, 270, "HTTPS · Zero Trust · API Gateway", font(LATIN, 15, 1), INK)
    rounded_card(draw, (420, 350, 704, 454), fill=WHITE, outline=BLUE, width=3, radius=16)
    centered(draw, 562, 367, "CubeSandbox Agent Adapter", font(LATIN, 18, 1), INK)
    centered(draw, 562, 401, "身份 · Profile · 配额 · 审计", font(CHINESE, 15), MUTED)
    centered(draw, 562, 428, "凭据由控制面注入", font(CHINESE, 14), BLUE)
    centered(draw, 562, 483, "请求是动作，不是任意网络隧道", font(CHINESE, 15), MUTED)

    rounded_card(draw, (798, 178, 1122, 535), fill=PALE_ORANGE, outline=ORANGE, width=3, radius=22)
    centered(draw, 960, 202, "生产网络", font(CHINESE, 19), ORANGE)
    rounded_card(draw, (842, 254, 1078, 354), fill=WHITE, outline=ORANGE, radius=16)
    cube_icon(draw, 892, 295, 0.38)
    draw.text((938, 272), "CubeSandbox", font=font(LATIN, 17, 1), fill=INK)
    draw.text((938, 302), "MicroVM", font=font(LATIN, 15), fill=MUTED)
    draw.text((938, 326), "按租约创建与回收", font=font(CHINESE, 13), fill=MUTED)
    rounded_card(draw, (842, 386, 952, 454), fill=WHITE, outline=ORANGE, radius=13)
    centered(draw, 897, 399, "Kubernetes", font(LATIN, 13, 1), INK)
    centered(draw, 897, 425, "运维 API", font(CHINESE, 13), MUTED)
    rounded_card(draw, (968, 386, 1078, 454), fill=WHITE, outline=ORANGE, radius=13)
    centered(draw, 1023, 399, "Artifact", font(LATIN, 13, 1), INK)
    centered(draw, 1023, 425, "数据 / 服务", font(CHINESE, 13), MUTED)
    centered(draw, 960, 483, "资源和原始数据留在生产网", font(CHINESE, 15), MUTED)

    arrow(draw, (326, 355), (382, 355), BLUE, 4)
    centered(draw, 354, 322, "结构化动作", font(CHINESE, 12), BLUE)
    arrow(draw, (742, 355), (798, 355), ORANGE, 4)
    centered(draw, 770, 322, "租约", font(CHINESE, 12), ORANGE)

    draw.rounded_rectangle((80, 565, 1120, 611), radius=11, fill=(241, 245, 249))
    centered(
        draw,
        600,
        578,
        "只回传受限输出与审计引用 · 不绕过办公网 / 生产网隔离 · 接入路径必须经过企业审批",
        font(CHINESE, 15),
        MUTED,
    )
    path = ARTICLE_DIR / "trusted-execution-boundary.png"
    image.save(path, format="PNG", optimize=True)
    return path


def comparison() -> Path:
    image, draw = canvas(
        "v0.2 到 v0.3：不是多几个接口，而是补齐状态与边界",
        "v0.2 证明三种 Agent 能共用沙箱；v0.3 把它推进到可恢复、可分租户的控制面",
    )
    x_positions = (80, 370, 735)
    widths = (280, 355, 385)
    headers = [
        ("维度", MUTED, (241, 245, 249)),
        ("v0.2", BLUE, PALE_BLUE),
        ("v0.3.0", VIOLET, PALE_VIOLET),
    ]
    for (label, color, fill), x, width in zip(headers, x_positions, widths):
        rounded_card(draw, (x, 180, x + width, 228), fill=fill, outline=color, radius=12)
        centered(draw, x + width / 2, 193, label, font(CHINESE, 17), color)

    rows = [
        ("客户端", "OpenClaw / DSH / Hermes", "+ Codex / 通用 MCP Host"),
        ("租约状态", "进程内存", "加密 Redis · 可恢复 · 分布式锁"),
        ("工具面", "exec / read / write / release", "13 个 Agent 工具 · 34 条 API 路径"),
        ("任务形态", "同步命令", "异步 Job · SSE · 取消 · PTY"),
        ("工作区", "临时", "按 Session 持久化 · retain_on_kill"),
        ("实验流", "单一路径", "Checkpoint · Rollback · Fork"),
        ("治理", "共享 Token · JSONL", "租户/OIDC/mTLS · 配额 · Metrics/GC"),
    ]
    row_y = 240
    for index, (dimension, old, new) in enumerate(rows):
        top = row_y + index * 50
        fill = WHITE if index % 2 == 0 else (248, 250, 253)
        draw.rectangle((80, top, 1120, top + 47), fill=fill)
        draw.text((98, top + 13), dimension, font=font(CHINESE, 15), fill=INK)
        draw.text((390, top + 13), old, font=font(CHINESE, 14), fill=MUTED)
        draw.text((755, top + 13), new, font=font(CHINESE, 14), fill=INK)
        draw.line((80, top + 47, 1120, top + 47), fill=LINE, width=1)
    draw.line((360, 180, 360, 587), fill=LINE, width=2)
    draw.line((725, 180, 725, 587), fill=LINE, width=2)
    path = ARTICLE_DIR / "v02-v03-comparison.png"
    image.save(path, format="PNG", optimize=True)
    return path


def workflows() -> Path:
    image, draw = canvas(
        "v0.3 的三种新玩法",
        "同一个不透明 lease_ref，把长任务、持久工作区和可分支实验串成完整生命周期",
    )
    lanes = [
        (
            180,
            "持久工作区",
            ["Acquire", "写入 /workspace", "Kill", "再次 Acquire", "继续工作"],
            BLUE,
            PALE_BLUE,
            "per-session-volume · retain_on_kill",
        ),
        (
            320,
            "长任务与交互",
            ["Start Job", "SSE / Offset", "Cancel", "Create PTY", "Resize / Input"],
            CYAN,
            PALE_CYAN,
            "断线后查状态和增量输出，不把 HTTP 请求挂到任务结束",
        ),
        (
            460,
            "可回滚实验",
            ["Acquire", "Checkpoint", "执行方案 A", "Rollback", "Fork 方案 B"],
            VIOLET,
            PALE_VIOLET,
            "适合依赖升级、代码修复与 Agent 方案 A/B；挂载卷时默认禁用",
        ),
    ]
    for y, label, steps, color, pale, note in lanes:
        rounded_card(draw, (80, y, 1120, y + 112), fill=(250, 252, 254), outline=LINE, radius=18)
        rounded_card(draw, (98, y + 20, 255, y + 68), fill=pale, outline=color, radius=13)
        centered(draw, 176, y + 33, label, font(CHINESE, 16), color)
        start_x = 284
        step_width = 136
        gap = 23
        for index, step in enumerate(steps):
            x = start_x + index * (step_width + gap)
            rounded_card(draw, (x, y + 17, x + step_width, y + 64), fill=WHITE, outline=color, radius=11)
            centered(draw, x + step_width / 2, y + 30, step, font(CHINESE, 13), INK)
            if index < len(steps) - 1:
                arrow(draw, (x + step_width + 3, y + 41), (x + step_width + gap - 4, y + 41), color, 2)
        draw.text((285, y + 79), note, font=font(CHINESE, 14), fill=MUTED)
    path = ARTICLE_DIR / "new-workflows.png"
    image.save(path, format="PNG", optimize=True)
    return path


def copy_for_docs(paths: list[Path]) -> None:
    for source in paths:
        shutil.copyfile(source, DOC_DIR / source.name)


def copy_evidence() -> None:
    evidence = {
        "10-openclaw-application.jpg": "openclaw-application-light.jpg",
        "11-dsh-application.png": "dsh-application-light.png",
        "12-hermes-application.png": "hermes-application-light.png",
        "13-codex-application.png": "codex-application-light.png",
    }
    for source_name, destination_name in evidence.items():
        source = SOURCE_EVIDENCE / source_name
        if not source.exists():
            raise FileNotFoundError(f"evidence image not found: {source}")
        shutil.copyfile(source, ARTICLE_DIR / destination_name)
        shutil.copyfile(source, DOC_DIR / destination_name)


def main() -> None:
    ARTICLE_DIR.mkdir(parents=True, exist_ok=True)
    DOC_DIR.mkdir(parents=True, exist_ok=True)
    outputs = [architecture(), trusted_execution_boundary(), comparison(), workflows()]
    copy_for_docs(outputs)
    copy_evidence()
    outputs.extend([cover_landscape(), cover_square()])
    for output in outputs:
        print(output.relative_to(ROOT))


if __name__ == "__main__":
    main()
