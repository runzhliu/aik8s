#!/usr/bin/env python3
"""Deterministic capability and integration diagrams, not product screenshots."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/assets/rag-agent/chatgpt-dots"
BG, INK, MUTED, LINE = "#F7F9FC", "#172033", "#64748B", "#D7DEE9"
BLUE, ORANGE = "#2563EB", "#C96A16"


def font(size, bold=False, latin=False):
    path = "/System/Library/Fonts/HelveticaNeue.ttc" if latin else "/System/Library/Fonts/Hiragino Sans GB.ttc"
    return ImageFont.truetype(path, size=size, index=1 if bold else 0)


def text(d, x, y, value, size=24, color=INK, bold=False):
    f = font(size, bold)
    a, b, right, bottom = d.textbbox((0, 0), value, font=f)
    assert x + right - a <= 1164 and y + bottom - b <= 653, value
    d.text((x - a, y - b), value, font=f, fill=color)


def center(d, box, value, size=24, color=INK, bold=False):
    f = font(size, bold)
    a, b, right, bottom = d.textbbox((0, 0), value, font=f)
    assert right - a <= box[2] - box[0] - 16, value
    assert bottom - b <= box[3] - box[1], value
    d.text(((box[0] + box[2] - right - a) / 2,
            (box[1] + box[3] - bottom - b) / 2), value, font=f, fill=color)


def canvas(title, subtitle):
    im = Image.new("RGB", (1200, 675), BG)
    d = ImageDraw.Draw(im)
    text(d, 48, 38, title, 34, bold=True)
    text(d, 48, 99, subtitle, 21, MUTED)
    return im, d


def card(d, box, title, lines, color=BLUE):
    d.rounded_rectangle(box, radius=15, fill="white", outline=LINE, width=2)
    x, y, r, bottom = box
    center(d, (x + 8, y + 18, r - 8, y + 55), title, 26, color, True)
    for i, value in enumerate(lines):
        top = y + 72 + i * 35
        assert top + 30 <= bottom - 10
        center(d, (x + 8, top, r - 8, top + 30), value, 23, MUTED)


def arrow(d, start, end, color=MUTED):
    d.line((start, end), width=3, fill=color)
    x, y = end
    assert start[0] == x or start[1] == y
    points = [(x, y), (x - 10, y - 6), (x - 10, y + 6)] if start[1] == y else [(x, y), (x - 6, y - 10), (x + 6, y - 10)]
    d.polygon(points, fill=color)


def footer(d, value):
    d.rounded_rectangle((48, 606, 1152, 648), radius=11, fill="#EAF1FF")
    center(d, (58, 607, 1142, 647), value, 21, BLUE)


def capability():
    im, d = canvas("Dot 持续跟进，任务在不同环境执行", "依据官方公开能力整理；表示逻辑关系，不代表服务端内部实现。")
    card(d, (48, 159, 342, 349), "沟通入口", ["ChatGPT / Slack", "桌面与移动应用", "持续补充目标与约束"])
    card(d, (414, 159, 786, 349), "Dot：协调长期职责", ["上下文与已有记忆", "拆分任务 / 跟进结果", "等待输入 / 调整优先级"])
    card(d, (858, 159, 1152, 349), "进度、产物与决策", ["文件 / 报告 / 代码", "汇总执行结果", "需要判断时请求输入"])
    arrow(d, (346, 250), (408, 250))
    arrow(d, (790, 250), (852, 250))
    d.line((600, 353, 600, 376), fill=MUTED, width=3)
    d.line((213, 376, 987, 376), fill=MUTED, width=3)
    for x in (213, 600, 987):
        arrow(d, (x, 376), (x, 406))
    card(d, (48, 410, 378, 570), "云端电脑", ["浏览器 / 文件 / 软件", "本地设备关机仍可工作"])
    card(d, (435, 410, 765, 570), "已连接的应用", ["插件与获准工具", "使用各自账号权限"])
    card(d, (822, 410, 1152, 570), "已连接的本地电脑", ["本地文件 / Work / Codex", "需要在线且应用保持打开"])
    footer(d, "消息渠道、应用授权、本地电脑连接是三种独立连接；不是同一种权限。")
    im.save(OUT / "capability-map.png", optimize=True)


def integration():
    im, d = canvas("接入 Kubernetes：查询与变更分别设计", "企业接入建议；不是 Dot 内置架构，也不是已经运行的实验。")
    boxes = [(48, 176, 294, 337), (334, 176, 580, 337), (620, 176, 866, 337), (906, 176, 1152, 337)]
    text(d, 48, 139, "只读分析路径", 24, BLUE, True)
    for box, title, lines in zip(boxes, ["Dot", "企业插件 / MCP", "受控只读查询", "证据与报告"],
        [["提出查询与分析", "跟进结果"], ["身份与权限检查", "限定工具和目标"], ["K8s / 指标 API", "结果按权限过滤"], ["固定时间与口径", "关联日志和指标"]]):
        card(d, box, title, lines)
    for a, b in zip(boxes, boxes[1:]):
        arrow(d, (a[2] + 3, 251), (b[0] - 4, 251))
    boxes = [(48, 412, 294, 574), (334, 412, 580, 574), (620, 412, 866, 574), (906, 412, 1152, 574)]
    text(d, 48, 373, "变更执行路径", 24, ORANGE, True)
    for box, title, lines in zip(boxes, ["方案与 Diff", "代码与校验", "独立审批", "受控执行器"],
        [["生成修复建议", "说明依据和影响"], ["Pull Request / CI", "校验变更条件"], ["核对范围和身份", "明确放行操作"], ["执行获准变更", "回传结果与回执"]]):
        card(d, box, title, lines, ORANGE)
    for a, b in zip(boxes, boxes[1:]):
        arrow(d, (a[2] + 3, 491), (b[0] - 4, 491), ORANGE)
    footer(d, "可达性、最小权限和操作审计由企业接入端落实；连接 Dot 不等于开放整个集群。")
    im.save(OUT / "kubernetes-integration.png", optimize=True)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    capability()
    integration()
    print("Generated 2 conceptual diagrams at 1200 x 675.")
