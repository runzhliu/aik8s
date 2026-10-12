#!/usr/bin/env python3
"""Render source-based OpenClaw Enterprise diagrams; no runtime data is depicted."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/assets/rag-agent/openclaw-enterprise"
SIZE = (1200, 675)
BG, WHITE, INK = "#F6F8FC", "#FFFFFF", "#172033"
MUTED, LINE = "#68748B", "#D7DEEA"
BLUE, VIOLET, TEAL, ORANGE = "#2F6BFF", "#7B61E8", "#0B9B8A", "#E98122"


def font(size, bold=False):
    candidates = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc" if bold else "/System/Library/Fonts/STHeiti Light.ttc",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size, index=1 if bold and "PingFang" in candidate else 0)
    raise RuntimeError("A Chinese font is required to render these diagrams.")


def label(d, x, y, value, size=19, color=INK, bold=False, width=None):
    f = font(size, bold)
    if width is not None and d.textlength(value, font=f) > width:
        raise ValueError(f"Text exceeds its container: {value}")
    d.text((x, y), value, font=f, fill=color)


def canvas(title, subtitle):
    im = Image.new("RGB", SIZE, BG)
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((28, 24, 1172, 651), radius=22, fill=WHITE, outline=LINE, width=2)
    d.rounded_rectangle((58, 55, 65, 119), radius=3, fill=BLUE)
    label(d, 84, 52, title, size=33, bold=True, width=1040)
    label(d, 84, 101, subtitle, size=18, color=MUTED, width=1040)
    return im, d


def card(d, box, title, lines, accent, title_size=22):
    x1, y1, x2, y2 = box
    d.rounded_rectangle(box, radius=14, fill="#FBFCFF", outline=LINE, width=2)
    d.rounded_rectangle((x1, y1 + 15, x1 + 6, y2 - 15), radius=3, fill=accent)
    label(d, x1 + 18, y1 + 15, title, size=title_size, color=accent, bold=True, width=x2-x1-36)
    y = y1 + 56
    for line in lines:
        label(d, x1 + 18, y, line, size=18, color=MUTED, width=x2-x1-36)
        y += 29
    if y - 29 + 25 > y2 - 10:
        raise ValueError(f"Card height is insufficient: {title}")


def arrow(d, points, color=MUTED):
    d.line(points, fill=color, width=3)
    (x0, y0), (x, y) = points[-2:]
    if x == x0:
        dy = 1 if y > y0 else -1
        head = [(x, y), (x - 6, y - dy * 10), (x + 6, y - dy * 10)]
    else:
        dx = 1 if x > x0 else -1
        head = [(x, y), (x - dx * 10, y - 6), (x - dx * 10, y + 6)]
    d.polygon(head, fill=color)


def architecture():
    im, d = canvas(
        "OpenClaw Enterprise：管理 Agent 的控制面",
        "HTTP API 接受变更，Worker 异步部署；对话、模型调用与工具执行留在运行时",
    )
    label(d, 60, 145, "控制面  ·  OpenClaw Control Plane（OCC）", size=18, bold=True)
    specs = [
        (60, "API / Console", ["身份认证与权限校验", "Agent 与 Revision", "CLI / 浏览器入口"], BLUE),
        (348, "PostgreSQL", ["资源与部署状态", "持久化工作队列", "独立审计记录"], VIOLET),
        (636, "Worker", ["领取任务与续租", "检查授权和归属", "执行与重试协调"], TEAL),
        (924, "Drivers", ["由安装管理员选定", "对接计算与凭据", "生成基础设施资源"], ORANGE),
    ]
    for x, title, lines, accent in specs:
        card(d, (x, 178, x + 216, 333), title, lines, accent)
    for left, right in [(276, 348), (564, 636), (852, 924)]:
        arrow(d, [(left + 5, 251), (right - 5, 251)])
    label(d, 60, 364, "数据面  ·  每个 Agent 独立 Gateway", size=18, bold=True)
    card(d, (60, 406, 564, 566), "Embedded OpenClaw", [
        "Gateway 与 Harness 合并在一个工作负载中",
        "接收消息、调用模型、执行工具",
        "私有 Gateway 状态卷；模型凭据进入合并运行时",
    ], BLUE)
    card(d, (636, 406, 1140, 566), "Dedicated Codex", [
        "Gateway 通过认证 WebSocket 连接 Codex Harness",
        "Gateway 与 Harness 分开；模型凭据只给 Harness",
        "Gateway 状态卷与 Harness 工作区卷分别挂载",
    ], TEAL)
    d.line([(1032, 333), (1032, 390), (312, 390)], fill=ORANGE, width=3)
    arrow(d, [(312, 390), (312, 402)], ORANGE)
    arrow(d, [(888, 390), (888, 402)], ORANGE)
    label(d, 60, 601, "架构依据：源码与当前部署契约；图中两种模式均指 Kubernetes 的标准部署路径。", size=17, color=MUTED)
    im.save(OUT / "architecture.png", optimize=True)


def lifecycle():
    im, d = canvas(
        "从 Agent 草稿到可用运行时",
        "不可变 Revision 固定部署配置；持久化队列恢复控制操作，业务动作仍需独立验证",
    )
    xs = [60, 348, 636, 924]
    specs = [
        ("1  创建 Agent", ["定义配置与身份", "尚未启动进程", "修改草稿可复用"], BLUE),
        ("2  提交 Deploy", ["生成配置快照", "创建 AgentRevision", "进入持久化队列"], VIOLET),
        ("3  Worker 协调", ["领取任务并续租", "准备、激活、清理", "有限重试与归属检查"], TEAL),
        ("4  验证结果", ["操作终态与 Pod 就绪", "实际模型响应", "工具与工作区检查"], ORANGE),
    ]
    for x, (title, lines, accent) in zip(xs, specs):
        card(d, (x, 185, x + 216, 344), title, lines, accent, title_size=21)
    for left, right in [(276, 348), (564, 636), (852, 924)]:
        arrow(d, [(left + 5, 263), (right - 5, 263)])
    label(d, 60, 374, "升级与恢复的两个边界", size=19, bold=True)
    card(d, (60, 413, 564, 573), "有状态替换会产生中断", [
        "Gateway 单副本，使用 Recreate 替换策略",
        "私有 RWO 卷不等于物理进程互斥",
        "节点分区时仍需存储与节点隔离措施",
    ], ORANGE)
    card(d, (636, 413, 1140, 573), "历史版本不等于一键回滚", [
        "当前没有公开的通用 rollback 操作",
        "恢复旧配置后，应提交新的部署",
        "数据库、工作区和凭据需要各自的恢复方案",
    ], VIOLET)
    label(d, 60, 606, "activeRevisionId 是控制面指针；它本身不能证明运行时持续健康或业务任务已经完成。", size=17, color=MUTED)
    im.save(OUT / "lifecycle.png", optimize=True)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    architecture()
    lifecycle()
    print(f"Generated 2 source-based diagrams in {OUT}")
