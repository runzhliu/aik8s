#!/usr/bin/env python3
"""Draw measured client outcomes; source is the public APF results.json."""
import json
from pathlib import Path
from PIL import Image, ImageDraw
from generate_kubernetes_flow_control_visuals import text, box, BG, INK, MUTED, BLUE, ORANGE

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/assets/kubernetes-apf-case"
DATA = json.loads((OUT / "results.json").read_text())
LABELS = {"normal": "正常 / 5 份额 Queue", "reject": "0 份额 Reject", "queue": "0 份额 Queue", "recovered": "恢复 / 5 份额 Queue"}


def draw(mobile=False):
    im = Image.new("RGB", (720, 1080) if mobile else (1200, 675), BG)
    d = ImageDraw.Draw(im)
    text(d, 36, 30, "APF 实测：拒绝来自哪里？", 32)
    text(d, 38, 80, "Kubernetes 1.30.4 · 每阶段 90 秒 · 批量 5 req/s", 21, MUTED)
    text(d, 38, 116, "蓝：HTTP 200     橙：HTTP 429", 23)
    rows = [r for r in DATA["summary"] if r["actor"] == "batch"]
    for i, row in enumerate(rows):
        y = 171 + i * (170 if mobile else 86)
        label = LABELS[row["phase"]]
        good = row["status_counts"].get("200", 0)
        bad = row["status_counts"].get("429", 0)
        x1, x2 = (40, 675) if mobile else (367, 810)
        if mobile:
            text(d, 40, y, label, 27)
            y += 43
        else:
            text(d, 40, y + 12, label, 25, width=310)
        d.rounded_rectangle((x1, y, x2, y + 37), radius=5, fill=ORANGE if bad else BLUE)
        if good:
            d.rectangle((x1, y + 2, x1 + (x2-x1) * good / row["requests"], y + 35), fill=BLUE)
        if mobile:
            text(d, 42, y + 53, f"200: {good} / 450     429: {bad}", 26, bold=True)
        else:
            text(d, 842, y + 10, f"200: {good}   /   429: {bad}", 25, bold=True)
    foot_y = 883 if mobile else 533
    box(d, (36, foot_y, im.width - 36, im.height - 25))
    control = [r for r in DATA["summary"] if r["actor"] == "control"]
    total = sum(r["requests"] for r in control)
    assert all(r["status_counts"] == {"200": r["requests"]} for r in control)
    text(d, 55, foot_y + 23, f"独立对照：{total}/{total} 请求成功", 27, BLUE)
    text(d, 55, foot_y + 72, "Queue 阶段的 2 个请求在恢复后成功。", 22, MUTED)
    if mobile:
        text(d, 55, foot_y + 112, "柱长表示各阶段的状态码比例。", 22, MUTED)
    im.save(OUT / ("client-outcomes-mobile.png" if mobile else "client-outcomes.png"), optimize=True)


if __name__ == "__main__":
    draw()
    draw(True)
