#!/usr/bin/env python3
"""Render reference designs, not measured or company-internal diagrams.

Run with a Pillow environment on macOS, using the project's article fonts.
"""
from pathlib import Path
from PIL import Image, ImageDraw
from generate_kubernetes_flow_control_visuals import (
    BG, BLUE, MUTED, ORANGE, box, canvas, footer, text,
)

OUT = Path(__file__).resolve().parents[1] / "docs/assets/kubernetes-fleet-reliability"


def down(d, x, start, end):
    d.line((x, start, x, end - 8), fill=BLUE, width=3)
    d.polygon([(x, end), (x - 6, end - 9), (x + 6, end - 9)], fill=BLUE)


def mobile(title, subtitle):
    im = Image.new("RGB", (720, 1080), BG)
    d = ImageDraw.Draw(im)
    text(d, 32, 36, title, 32, width=656)
    text(d, 34, 99, subtitle, 23, MUTED, width=652)
    return im, d


def boundaries():
    im, d = canvas("统一管理，保持故障域独立", "参考设计 · 中央提供版本与策略，各组独立限制执行范围")
    box(d, (48, 150, 1152, 250), "#EAF1FF")
    text(d, 72, 173, "中央管理：集群库存 · 版本组合 · 策略 · 审计", 28, BLUE)
    text(d, 72, 218, "失联时暂停新增高风险变更", 21, MUTED)
    for x1, x2, name in [(48, 574, "A"), (626, 1152, "B")]:
        cx = (x1 + x2) // 2
        down(d, cx, 257, 285)
        box(d, (x1, 292, x2, 402))
        text(d, x1 + 24, 314, f"分组 {name}：独立发布与维护预算", 26, BLUE, width=x2-x1-48)
        text(d, x1 + 24, 362, "批次 · 停止条件 · 业务验证", 23, MUTED)
        down(d, cx, 409, 440)
        box(d, (x1, 447, x2, 562))
        text(d, x1 + 24, 470, f"组内集群：本地执行与协调", 26, width=x2-x1-48)
        text(d, x1 + 24, 518, "流控 · 容量 · 修复 · 证据", 23, MUTED)
    footer(d, "隔离目标需要演练：中央失联后，既有业务与本地协调仍可工作")
    im.save(OUT / "fleet-boundaries.png", optimize=True)

    im, d = mobile("统一管理，保持故障域独立", "参考设计 · 管理集中，执行按故障域隔离")
    box(d, (32, 165, 688, 330), "#EAF1FF")
    text(d, 56, 191, "中央管理", 30, BLUE)
    text(d, 56, 242, "库存 · 版本 · 策略 · 审计", 26)
    text(d, 56, 287, "失联：暂停新增高风险变更", 24, MUTED)
    for x1, x2, name in [(32, 336, "A"), (384, 688, "B")]:
        cx = (x1+x2)//2
        down(d, cx, 337, 372)
        box(d, (x1, 380, x2, 582))
        text(d, x1+22, 405, f"分组 {name}", 28, BLUE)
        for i, s in enumerate(["独立执行预算", "分批发布", "停止与验证"]):
            text(d, x1+22, 459+i*34, s, 25, width=x2-x1-44)
        down(d, cx, 590, 627)
        box(d, (x1, 636, x2, 850))
        text(d, x1+22, 662, "组内集群", 28)
        for i, s in enumerate(["本地协调", "流控与修复", "保留执行证据"]):
            text(d, x1+22, 718+i*35, s, 25, width=x2-x1-44)
    text(d, 34, 930, "需要验证：中央失联后既有业务是否继续", 25, MUTED)
    text(d, 34, 980, "共享 Webhook 等依赖仍可能传播故障", 25, MUTED)
    im.save(OUT / "fleet-boundaries-mobile.png", optimize=True)


def rollout():
    stages = [(2, "实验环境", "验证流程与恢复"), (8, "非关键业务", "观察真实流量"),
              (30, "代表性生产组", "覆盖主要组合"), (60, "分组扩大", "核对容量预算"),
              (200, "剩余集群", "继续拆成小批")]
    assert sum(n for n, _, _ in stages) == 300
    im, d = canvas("跨集群发布：验证一批，再推进一批", "假设算例 · 300 个集群分组，数字为各阶段新增数量，不是实测")
    for i, (n, name, condition) in enumerate(stages):
        x = 48 + i*224
        box(d, (x, 171, x+208, 427))
        text(d, x+18, 197, name, 24, BLUE, width=172)
        text(d, x+18, 252, str(n), 52, BLUE, bold=True)
        text(d, x+18, 321, "个集群", 23, MUTED)
        text(d, x+18, 376, condition, 21, width=172)
    box(d, (48, 464, 1152, 575), "#FFF1E8")
    text(d, 72, 487, "异常或观测缺失：停止新增动作，评估恢复", 29, ORANGE)
    text(d, 72, 535, "每个阶段都有推进条件；关键业务与同一副本组另设约束", 23)
    footer(d, "2 + 8 + 30 + 60 + 200 = 300 · 停止推进不会自动撤销已生效的变更")
    im.save(OUT / "rollout-gates.png", optimize=True)

    im, d = mobile("跨集群发布：逐批验证", "假设 300 集群 · 各阶段新增数量，非实测")
    for i, (n, name, condition) in enumerate(stages):
        y = 156+i*153
        box(d, (32, y, 688, y+128))
        text(d, 54, y+27, str(n), 43, BLUE, bold=True, width=107)
        text(d, 54, y+85, "个集群", 21, MUTED)
        text(d, 185, y+25, name, 29, BLUE)
        text(d, 185, y+79, condition, 25)
        if i < 4:
            down(d, 360, y+131, y+150)
    box(d, (32, 944, 688, 1044), "#FFF1E8")
    text(d, 52, 964, "异常或观测缺失：停止新增动作", 27, ORANGE)
    text(d, 52, 1009, "评估恢复后再继续；最后 200 个仍拆小批", 23)
    im.save(OUT / "rollout-gates-mobile.png", optimize=True)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    boundaries()
    rollout()
