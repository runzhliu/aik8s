#!/usr/bin/env python3
"""Generate light-mode WeChat visuals for CubeSandbox Agent Adapter v0.5.0."""

from __future__ import annotations

import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
ARTICLE_DIR = ROOT / "articles/wechat/assets/cubesandbox-agent-adapter-v05"
LANDSCAPE_COVER = ROOT / "articles/wechat/assets/cubesandbox-agent-adapter-v05-cover.png"
SQUARE_COVER = ROOT / "articles/wechat/assets/cubesandbox-agent-adapter-v05-cover-square.png"
SOURCE_ROOT = ROOT.parent / "cubesandbox-agent-adapter/docs/assets"

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
PALE_RED = (255, 237, 237)


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
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    if abs(dx) >= abs(dy):
        direction = 1 if dx >= 0 else -1
        points = [end, (end[0] - direction * 12, end[1] - 7), (end[0] - direction * 12, end[1] + 7)]
    else:
        direction = 1 if dy >= 0 else -1
        points = [end, (end[0] - 7, end[1] - direction * 12), (end[0] + 7, end[1] - direction * 12)]
    draw.polygon(points, fill=color)


def pill(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    label: str,
    *,
    fill: tuple[int, int, int] = PALE_BLUE,
    outline: tuple[int, int, int] = BLUE,
    size: int = 14,
) -> int:
    face = font(CHINESE, size)
    width = text_width(draw, label, face) + 28
    height = size + 24
    draw.rounded_rectangle((x, y, x + width, y + height), radius=height // 2, fill=fill, outline=outline)
    draw.text((x + 14, y + 7), label, font=face, fill=outline)
    return width


def cube_icon(draw: ImageDraw.ImageDraw, cx: int, cy: int, scale: float = 1.0) -> None:
    top = [
        (cx, cy - int(54 * scale)),
        (cx + int(58 * scale), cy - int(24 * scale)),
        (cx, cy + int(7 * scale)),
        (cx - int(58 * scale), cy - int(24 * scale)),
    ]
    left = [
        (cx - int(58 * scale), cy - int(24 * scale)),
        (cx, cy + int(7 * scale)),
        (cx, cy + int(74 * scale)),
        (cx - int(58 * scale), cy + int(42 * scale)),
    ]
    right = [
        (cx, cy + int(7 * scale)),
        (cx + int(58 * scale), cy - int(24 * scale)),
        (cx + int(58 * scale), cy + int(42 * scale)),
        (cx, cy + int(74 * scale)),
    ]
    draw.polygon(top, fill=PALE_CYAN, outline=CYAN)
    draw.polygon(left, fill=(84, 140, 244), outline=BLUE)
    draw.polygon(right, fill=BLUE, outline=(24, 78, 190))
    draw.line((cx, cy + int(7 * scale), cx, cy + int(74 * scale)), fill=WHITE, width=max(2, int(3 * scale)))
    centered(draw, cx, cy - int(15 * scale), ">_", font(LATIN, max(13, int(21 * scale)), 1), INK)


def shield(draw: ImageDraw.ImageDraw, cx: int, cy: int, scale: float = 1.0) -> None:
    w = int(38 * scale)
    h = int(48 * scale)
    points = [
        (cx, cy - h),
        (cx + w, cy - int(0.62 * h)),
        (cx + int(0.82 * w), cy + int(0.34 * h)),
        (cx, cy + h),
        (cx - int(0.82 * w), cy + int(0.34 * h)),
        (cx - w, cy - int(0.62 * h)),
    ]
    draw.polygon(points, fill=PALE_GREEN, outline=GREEN)
    draw.line((cx - int(13 * scale), cy, cx - int(2 * scale), cy + int(12 * scale)), fill=GREEN, width=max(3, int(4 * scale)))
    draw.line((cx - int(2 * scale), cy + int(12 * scale), cx + int(18 * scale), cy - int(15 * scale)), fill=GREEN, width=max(3, int(4 * scale)))


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
    height: int = 58,
    label_size: int = 13,
) -> None:
    rounded_card(draw, (x, y, x + width, y + height), fill=pale, outline=color, radius=14)
    diameter = min(30, height - 20)
    top = y + (height - diameter) // 2
    draw.ellipse((x + 11, top, x + 11 + diameter, top + diameter), fill=color)
    centered(draw, x + 11 + diameter / 2, top + 7, short, font(LATIN, 11, 1), WHITE)
    draw.text((x + 49, y + (height - label_size) // 2 - 2), label, font=font(LATIN, label_size, 1), fill=INK)


def canvas(title: str, subtitle: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (1200, 675), PAPER)
    draw = ImageDraw.Draw(image)
    rounded_card(draw, (42, 38, 1158, 637), radius=28)
    draw.rectangle((42, 38, 54, 637), fill=BLUE)
    draw.text((88, 68), title, font=font(CHINESE, 35), fill=INK)
    draw.text((90, 120), subtitle, font=font(CHINESE, 18), fill=MUTED)
    return image, draw


def cover_landscape() -> Path:
    image = Image.new("RGB", (900, 383), PAPER)
    draw = ImageDraw.Draw(image)
    grid(draw, 900, 383, 42)
    rounded_card(draw, (28, 24, 872, 359), radius=28)
    draw.rectangle((28, 24, 40, 359), fill=BLUE)
    draw.text((70, 48), "v0.5.0 · 5 Clients · Fail Closed", font=font(LATIN, 15, 1), fill=BLUE)
    draw.text((67, 88), "CubeSandbox Agent Adapter", font=font(LATIN, 30, 1), fill=INK)
    draw.text((70, 137), "不记账，就不执行", font=font(CHINESE, 29), fill=INK)
    offset = 70
    for label, color, pale in [
        ("强审计", BLUE, PALE_BLUE),
        ("可信任务", VIOLET, PALE_VIOLET),
        ("失败闭锁", RED, PALE_RED),
    ]:
        offset += pill(draw, offset, 205, label, fill=pale, outline=color) + 10
    draw.text((70, 280), "OpenClaw · DSH · Hermes · Codex · Claude", font=font(LATIN, 14, 1), fill=MUTED)
    draw.text((70, 322), "AIK8S.RUN", font=font(LATIN, 12, 1), fill=CYAN)

    agent_node(draw, 563, 54, "OpenClaw", "O", BLUE, PALE_BLUE, width=136, height=52, label_size=12)
    agent_node(draw, 718, 54, "DSH", "D", CYAN, PALE_CYAN, width=112, height=52, label_size=12)
    agent_node(draw, 540, 292, "Hermes", "H", VIOLET, PALE_VIOLET, width=120, height=48, label_size=11)
    agent_node(draw, 665, 292, "Codex", "C", GREEN, PALE_GREEN, width=105, height=48, label_size=11)
    agent_node(draw, 775, 292, "Claude", "C", ORANGE, PALE_ORANGE, width=90, height=48, label_size=10)
    cube_icon(draw, 704, 180, 0.78)
    shield(draw, 795, 190, 0.62)
    for start, end, color in [
        ((630, 106), (675, 145), BLUE),
        ((768, 106), (730, 145), CYAN),
        ((600, 292), (665, 229), VIOLET),
        ((716, 292), (704, 241), GREEN),
        ((820, 292), (750, 226), ORANGE),
    ]:
        draw.line((*start, *end), fill=color, width=3)
    centered(draw, 704, 247, "CubeSandbox", font(LATIN, 13, 1), INK)
    centered(draw, 795, 237, "Audit", font(LATIN, 11, 1), GREEN)
    image.save(LANDSCAPE_COVER, format="PNG", optimize=True)
    return LANDSCAPE_COVER


def cover_square() -> Path:
    image = Image.new("RGB", (900, 900), PAPER)
    draw = ImageDraw.Draw(image)
    grid(draw, 900, 900, 54)
    rounded_card(draw, (52, 46, 848, 854), radius=42)
    draw.rectangle((52, 46, 848, 59), fill=BLUE)
    draw.text((92, 100), "v0.5.0 · 5 Clients · Fail Closed", font=font(LATIN, 21, 1), fill=BLUE)
    draw.text((87, 158), "CubeSandbox", font=font(LATIN, 64, 1), fill=INK)
    draw.text((90, 239), "Agent Adapter", font=font(LATIN, 58, 1), fill=INK)
    draw.text((91, 322), "不记账，就不执行", font=font(CHINESE, 43), fill=INK)

    cube_icon(draw, 390, 512, 1.22)
    shield(draw, 545, 515, 1.18)
    centered(draw, 468, 632, "MicroVM + Durable Audit", font(LATIN, 19, 1), MUTED)

    labels = [
        (92, 690, "OpenClaw", BLUE, PALE_BLUE),
        (244, 690, "DSH", CYAN, PALE_CYAN),
        (357, 690, "Hermes", VIOLET, PALE_VIOLET),
        (494, 690, "Codex", GREEN, PALE_GREEN),
        (622, 690, "Claude", ORANGE, PALE_ORANGE),
    ]
    for x, y, label, color, pale in labels:
        face = font(LATIN, 15, 1)
        width = text_width(draw, label, face) + 34
        draw.rounded_rectangle((x, y, x + width, y + 43), radius=20, fill=pale, outline=color)
        centered(draw, x + width / 2, y + 12, label, face, color)
    centered(draw, 450, 774, "Trusted Tasks · Fail-closed Audit · Signed Receipt", font(LATIN, 18, 1), MUTED)
    draw.text((712, 814), "AIK8S.RUN", font=font(LATIN, 13, 1), fill=CYAN)
    image.save(SQUARE_COVER, format="PNG", optimize=True)
    return SQUARE_COVER


def architecture() -> Path:
    image, draw = canvas(
        "五种 Agent，共用一个可信执行控制面",
        "客户端保留自己的模型与界面；身份、任务、MicroVM、回收和强审计由 Adapter 统一",
    )
    agents = [
        ("OpenClaw", "Tool Plugin", BLUE, PALE_BLUE),
        ("DSH", "Cordis Plugin", CYAN, PALE_CYAN),
        ("Hermes", "Native Plugin", VIOLET, PALE_VIOLET),
        ("Codex", "MCP stdio", GREEN, PALE_GREEN),
        ("Claude Code", "MCP stdio", ORANGE, PALE_ORANGE),
    ]
    for index, (name, detail, color, pale) in enumerate(agents):
        y = 174 + index * 80
        rounded_card(draw, (78, y, 330, y + 62), fill=pale, outline=color, radius=15)
        draw.ellipse((94, y + 15, 126, y + 47), fill=color)
        centered(draw, 110, y + 23, name[0], font(LATIN, 12, 1), WHITE)
        draw.text((140, y + 10), name, font=font(LATIN, 17, 1), fill=INK)
        draw.text((140, y + 35), detail, font=font(LATIN, 13), fill=MUTED)
        arrow(draw, (330, y + 31), (395, y + 31), color, 3)

    rounded_card(draw, (397, 174, 780, 556), fill=(246, 249, 255), outline=BLUE, width=3, radius=24)
    centered(draw, 588, 199, "CubeSandbox Agent Adapter", font(LATIN, 23, 1), INK)
    blocks = [
        (252, "Tenant / OIDC / mTLS · Action Scope", PALE_BLUE, BLUE),
        (318, "TaskTemplate · Schema · Independent Approval", PALE_VIOLET, VIOLET),
        (384, "Lease / Job / Output Policy · Cleanup", PALE_CYAN, CYAN),
        (450, "Durable Intent + Result · Signed Receipt", PALE_GREEN, GREEN),
    ]
    for y, label, pale, color in blocks:
        rounded_card(draw, (430, y, 746, y + 48), fill=pale, outline=color, radius=12)
        centered(draw, 588, y + 14, label, font(LATIN, 14, 1), INK)
    centered(draw, 588, 520, "No audit, no guarded execution", font(LATIN, 14, 1), RED)

    arrow(draw, (780, 349), (838, 349), BLUE, 4)
    rounded_card(draw, (840, 174, 1120, 420), fill=PALE_ORANGE, outline=ORANGE, width=3, radius=24)
    centered(draw, 980, 199, "CubeSandbox", font(LATIN, 25, 1), INK)
    cube_icon(draw, 980, 298, 0.92)
    centered(draw, 980, 382, "Per-task MicroVM", font(LATIN, 16, 1), MUTED)

    arrow(draw, (980, 420), (980, 464), GREEN, 3)
    rounded_card(draw, (840, 466, 1120, 556), fill=PALE_GREEN, outline=GREEN, width=3, radius=19)
    shield(draw, 888, 511, 0.42)
    draw.text((929, 483), "Audit authority", font=font(LATIN, 17, 1), fill=INK)
    draw.text((929, 510), "SQLite + persistent outbox", font=font(LATIN, 13), fill=MUTED)
    draw.text((929, 533), "single writer · RWO", font=font(LATIN, 12), fill=GREEN)

    path = ARTICLE_DIR / "architecture.png"
    image.save(path, format="PNG", optimize=True)
    return path


def evolution() -> Path:
    image, draw = canvas(
        "从 v0.3 到 v0.5：状态、任务与证据",
        "三次升级不是简单增加接口，而是逐层收紧本地 Agent 使用生产资源的边界",
    )
    columns = [
        (
            80,
            "v0.3.0",
            "状态可恢复",
            BLUE,
            PALE_BLUE,
            ["持久租约 / Redis", "Job / PTY", "工作区与 Checkpoint", "多租户身份"],
            "任务怎么继续？",
        ),
        (
            425,
            "v0.4.0",
            "任务受约束",
            VIOLET,
            PALE_VIOLET,
            ["命名 TaskTemplate", "JSON Schema / Scope", "独立审批", "清理 + 签名回执"],
            "任务允许做什么？",
        ),
        (
            770,
            "v0.5.0",
            "证据可核对",
            GREEN,
            PALE_GREEN,
            ["先持久化 Intent", "再执行外部效果", "结果同步提交", "未知结果失败闭锁"],
            "故障后如何证明？",
        ),
    ]
    for x, version, heading, color, pale, bullets, question in columns:
        rounded_card(draw, (x, 182, x + 310, 558), fill=WHITE, outline=color, width=3, radius=22)
        rounded_card(draw, (x + 22, 204, x + 288, 259), fill=pale, outline=color, radius=13)
        draw.text((x + 40, 216), version, font=font(LATIN, 20, 1), fill=color)
        draw.text((x + 145, 216), heading, font=font(CHINESE, 18), fill=INK)
        for index, bullet in enumerate(bullets):
            y = 294 + index * 52
            draw.ellipse((x + 36, y + 8, x + 47, y + 19), fill=color)
            draw.text((x + 62, y), bullet, font=font(CHINESE, 16), fill=INK)
        draw.line((x + 30, 505, x + 280, 505), fill=LINE, width=1)
        centered(draw, x + 155, 522, question, font(CHINESE, 16), color)
    arrow(draw, (392, 370), (420, 370), MUTED, 3)
    arrow(draw, (737, 370), (765, 370), MUTED, 3)
    draw.rounded_rectangle((136, 582, 1064, 615), radius=12, fill=(241, 245, 249))
    centered(draw, 600, 588, "执行控制面 = 可恢复状态 + 受约束任务 + 故障时仍可信的证据", font(CHINESE, 15), MUTED)
    path = ARTICLE_DIR / "evolution.png"
    image.save(path, format="PNG", optimize=True)
    return path


def durable_audit_flow() -> Path:
    image, draw = canvas(
        "v0.5.0：先持久化，再执行",
        "权威记录不可用时返回 503；发现未知结果时保持阻断，不自动重放外部操作",
    )
    stages = [
        (76, "01", "认证请求", "主体 / Action", PALE_BLUE, BLUE),
        (288, "02", "提交 Intent", "SQLite 同步落盘", PALE_GREEN, GREEN),
        (500, "03", "受控执行", "MicroVM / 状态修改", PALE_ORANGE, ORANGE),
        (712, "04", "提交 Result", "事件 + Outbox 同事务", PALE_GREEN, GREEN),
        (924, "05", "返回成功", "结果 / Receipt", PALE_VIOLET, VIOLET),
    ]
    for x, number, heading, detail, pale, color in stages:
        rounded_card(draw, (x, 200, x + 176, 324), fill=pale, outline=color, width=2, radius=18)
        draw.ellipse((x + 18, 217, x + 52, 251), fill=color)
        centered(draw, x + 35, 225, number, font(LATIN, 12, 1), WHITE)
        centered(draw, x + 88, 260, heading, font(CHINESE, 18), INK)
        centered(draw, x + 88, 291, detail, font(CHINESE, 13), MUTED)
    for x in (252, 464, 676, 888):
        arrow(draw, (x, 262), (x + 31, 262), BLUE, 3)

    rounded_card(draw, (76, 376, 465, 538), fill=PALE_RED, outline=RED, width=2, radius=20)
    draw.text((104, 401), "写入失败", font=font(CHINESE, 20), fill=RED)
    draw.text((104, 441), "• HTTP 503 audit_unavailable", font=font(LATIN, 15, 1), fill=INK)
    draw.text((104, 474), "• readiness 失败，受控调用停止", font=font(CHINESE, 15), fill=INK)
    draw.text((104, 507), "• 不降级为无审计执行", font=font(CHINESE, 15), fill=INK)
    arrow(draw, (376, 324), (286, 374), RED, 3)

    rounded_card(draw, (492, 376, 849, 538), fill=PALE_ORANGE, outline=ORANGE, width=2, radius=20)
    draw.text((520, 401), "重启发现未决操作", font=font(CHINESE, 20), fill=ORANGE)
    draw.text((520, 441), "• 保留原 Intent，不盲目重试", font=font(CHINESE, 15), fill=INK)
    draw.text((520, 474), "• 核对 CubeSandbox / Redis / 外部任务", font=font(CHINESE, 15), fill=INK)
    draw.text((520, 507), "• 人工追加 reconciled，不伪造成功", font=font(CHINESE, 15), fill=INK)
    arrow(draw, (610, 324), (664, 374), ORANGE, 3)

    rounded_card(draw, (876, 376, 1100, 538), fill=PALE_CYAN, outline=CYAN, width=2, radius=20)
    centered(draw, 988, 401, "持久化 Outbox", font(CHINESE, 19), CYAN)
    centered(draw, 988, 443, "JSONL · stdout · HTTP", font(LATIN, 14, 1), INK)
    centered(draw, 988, 477, "at-least-once", font(LATIN, 15, 1), INK)
    centered(draw, 988, 507, "按 event_id 去重", font(CHINESE, 14), MUTED)
    arrow(draw, (800, 324), (954, 374), CYAN, 3)

    draw.rounded_rectangle((138, 578, 1062, 615), radius=12, fill=(241, 245, 249))
    centered(draw, 600, 586, "外部效果与审计库不是同一事务：未知就是未知，必须停下来核对", font(CHINESE, 15), MUTED)
    path = ARTICLE_DIR / "durable-audit-flow.png"
    image.save(path, format="PNG", optimize=True)
    return path


def trusted_execution_boundary() -> Path:
    image, draw = canvas(
        "本地 Code Agent 不进生产，任务进入受控沙箱",
        "把宽泛远程权限收敛为命名任务、最小权限身份、独立审批和可持久核对的执行证据",
    )
    rounded_card(draw, (78, 178, 326, 535), fill=PALE_BLUE, outline=BLUE, radius=22)
    centered(draw, 202, 202, "办公网 / 开发者本地", font(CHINESE, 19), BLUE)
    draw.rounded_rectangle((118, 265, 286, 372), radius=12, fill=WHITE, outline=BLUE, width=3)
    draw.rectangle((133, 281, 271, 348), fill=(239, 244, 251))
    centered(draw, 202, 296, "Code Agent", font(LATIN, 20, 1), INK)
    centered(draw, 202, 326, "Codex · Claude · OpenClaw", font(LATIN, 11), MUTED)
    draw.polygon([(104, 389), (300, 389), (274, 411), (130, 411)], fill=(205, 220, 242), outline=BLUE)
    centered(draw, 202, 443, "模型与会话留在本地", font(CHINESE, 16), INK)
    centered(draw, 202, 477, "不持有生产 SSH / kubeconfig", font(CHINESE, 14), MUTED)

    rounded_card(draw, (382, 178, 742, 535), fill=(248, 251, 255), outline=CYAN, width=3, radius=22)
    centered(draw, 562, 202, "公司批准的窄入口", font(CHINESE, 19), CYAN)
    rounded_card(draw, (420, 252, 704, 307), fill=PALE_CYAN, outline=CYAN, radius=14)
    centered(draw, 562, 266, "HTTPS · mTLS / OIDC · Tenant", font(LATIN, 15, 1), INK)
    rounded_card(draw, (420, 334, 704, 443), fill=WHITE, outline=BLUE, width=3, radius=16)
    centered(draw, 562, 350, "CubeSandbox Agent Adapter", font(LATIN, 18, 1), INK)
    centered(draw, 562, 384, "TaskTemplate · Schema · Action Scope", font(LATIN, 13), MUTED)
    centered(draw, 562, 411, "独立审批 · 强审计 · 清理 / Receipt", font(CHINESE, 14), BLUE)
    centered(draw, 562, 476, "传递的是结构化任务，不是任意网络隧道", font(CHINESE, 15), MUTED)

    rounded_card(draw, (798, 178, 1122, 535), fill=PALE_ORANGE, outline=ORANGE, width=3, radius=22)
    centered(draw, 960, 202, "生产网络", font(CHINESE, 19), ORANGE)
    rounded_card(draw, (842, 252, 1078, 352), fill=WHITE, outline=ORANGE, radius=16)
    cube_icon(draw, 892, 294, 0.38)
    draw.text((938, 270), "CubeSandbox", font=font(LATIN, 17, 1), fill=INK)
    draw.text((938, 300), "MicroVM", font=font(LATIN, 15), fill=MUTED)
    draw.text((938, 325), "按任务创建与回收", font=font(CHINESE, 13), fill=MUTED)
    rounded_card(draw, (842, 382, 952, 450), fill=WHITE, outline=ORANGE, radius=13)
    centered(draw, 897, 395, "Training", font(LATIN, 13, 1), INK)
    centered(draw, 897, 421, "GPU / 队列", font(CHINESE, 13), MUTED)
    rounded_card(draw, (968, 382, 1078, 450), fill=WHITE, outline=ORANGE, radius=13)
    centered(draw, 1023, 395, "Data", font(LATIN, 13, 1), INK)
    centered(draw, 1023, 421, "清洗 / 制品", font(CHINESE, 13), MUTED)
    centered(draw, 960, 482, "数据、身份与原始结果留在生产侧", font(CHINESE, 15), MUTED)

    arrow(draw, (326, 355), (382, 355), BLUE, 4)
    centered(draw, 354, 322, "任务参数", font(CHINESE, 12), BLUE)
    arrow(draw, (742, 355), (798, 355), ORANGE, 4)
    centered(draw, 770, 322, "授权执行", font(CHINESE, 12), ORANGE)
    draw.rounded_rectangle((80, 565, 1120, 611), radius=11, fill=(241, 245, 249))
    centered(draw, 600, 578, "可信执行 ≠ 机密计算 TEE · 仍需企业网关、网络白名单、DLP 与最小权限身份", font(CHINESE, 15), MUTED)
    path = ARTICLE_DIR / "trusted-execution-boundary.png"
    image.save(path, format="PNG", optimize=True)
    return path


def copy_evidence() -> list[Path]:
    evidence = {
        "audit-durability-acceptance/01-runtime-clients.png": "runtime-clients.png",
        "audit-durability-acceptance/02-persistence-restart.png": "persistence-restart.png",
        "audit-durability-acceptance/03-fail-closed-recovery.png": "fail-closed-recovery.png",
        "trusted-execution-apps/05-claude-code-trusted-task.png": "claude-code-trusted-task.png",
    }
    outputs: list[Path] = []
    for source_name, destination_name in evidence.items():
        source = SOURCE_ROOT / source_name
        destination = ARTICLE_DIR / destination_name
        if not source.exists():
            raise FileNotFoundError(f"evidence image not found: {source}")
        shutil.copyfile(source, destination)
        outputs.append(destination)
    return outputs


def main() -> None:
    ARTICLE_DIR.mkdir(parents=True, exist_ok=True)
    outputs = [architecture(), evolution(), durable_audit_flow(), trusted_execution_boundary()]
    outputs.extend(copy_evidence())
    outputs.extend([cover_landscape(), cover_square()])
    for output in outputs:
        print(output.relative_to(ROOT))


if __name__ == "__main__":
    main()
