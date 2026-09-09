#!/usr/bin/env python3
"""Draw conceptual flow-control figures in the MiniMax M3 article style.

All numbers are illustrative calculations, never cluster measurements.
Run with the repository's WeChat Python environment (Pillow required).
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/assets/kubernetes-flow-control"
BG, INK, MUTED = "#F7F9FC", "#172033", "#64748B"
LINE, BLUE, ORANGE = "#D7DEE9", "#2563EB", "#F97316"
CN = "/System/Library/Fonts/Hiragino Sans GB.ttc"
LATIN = "/System/Library/Fonts/HelveticaNeue.ttc"


def text(d, x, y, value, size=24, color=INK, bold=False, width=None):
    latin = value.isascii()
    f = ImageFont.truetype(LATIN if latin else CN, size, index=1 if latin and bold else 0)
    box = d.textbbox((0, 0), value, font=f)
    w, h = box[2] - box[0], box[3] - box[1]
    assert x + w <= d._image.width - 24 and y + h <= d._image.height - 18, (value, x, y, w, h)
    if width is not None:
        assert w <= width, (value, w, width)
    d.text((x - box[0], y - box[1]), value, font=f, fill=color)


def box(d, bounds, fill="white"):
    d.rounded_rectangle(bounds, radius=16, fill=fill, outline=LINE, width=1)


def arrow(d, x1, x2, y):
    d.line((x1, y, x2 - 8, y), fill=BLUE, width=3)
    d.polygon([(x2, y), (x2 - 10, y - 6), (x2 - 10, y + 6)], fill=BLUE)


def canvas(title, subtitle):
    im = Image.new("RGB", (1200, 675), BG)
    d = ImageDraw.Draw(im)
    text(d, 48, 36, title, 34)
    text(d, 50, 96, subtitle, 21, MUTED)
    return im, d


def footer(d, value):
    box(d, (48, 607, 1152, 657))
    text(d, 68, 625, value, 20, MUTED)


def layers():
    im, d = canvas("三条流量路径，分别治理", "控制面请求、GPU 任务和模型访问，需要不同的保护机制")
    rows = [
        ("API 调用", "Controller / kubectl", "APF + 客户端限速", "分类、并发与公平排队", "保护控制面", "API Server / etcd"),
        ("GPU 任务", "训练 / 批处理", "队列 + 资源配额", "准入、公平共享与抢占", "控制资源占用", "GPU / CPU / 内存"),
        ("模型请求", "对话 / RAG / Agent", "网关 + 引擎并发控制", "速率、Token 与排队预算", "保护推理服务", "首 Token / 生成延迟"),
    ]
    for i, row in enumerate(rows):
        y = 160 + i * 143
        for x1, x2, a, b in [(48, 328, row[0], row[1]), (394, 786, row[2], row[3]), (852, 1152, row[4], row[5])]:
            box(d, (x1, y, x2, y + 113), "#EAF1FF" if x1 == 394 else "white")
            text(d, x1 + 20, y + 24, a, 27, BLUE if x1 == 394 else INK, width=x2-x1-40)
            text(d, x1 + 20, y + 73, b, 20, MUTED, width=x2-x1-40)
        arrow(d, 340, 381, y + 57)
        arrow(d, 799, 839, y + 57)
    footer(d, "架构示意 · APF 不处理模型 HTTP 请求，任务队列也不限制 API QPS")
    im.save(OUT / "01-three-layers.png", optimize=True)


def apf():
    im, d = canvas("APF：先分类，再分配执行机会", "识别调用方与请求类型，用独立并发预算和公平队列隔离干扰")
    cards = [
        (48, "FlowSchema", ["谁发起请求", "访问哪些资源与操作", "决定流的划分方式"]),
        (426, "PriorityLevel", ["分配名义并发份额", "配置队列或直接拒绝", "约束份额借用与借出"]),
        (804, "Execute / Reject", ["容量允许：执行请求", "有界队列：等待机会", "超出边界：拒绝请求"]),
    ]
    for x, title, lines in cards:
        box(d, (x, 164, x + 348, 420))
        text(d, x + 22, 191, title, 27, BLUE, bold=True, width=304)
        for i, line in enumerate(lines):
            text(d, x + 22, 257 + i * 47, line, 24, width=304)
    arrow(d, 404, 418, 292)
    arrow(d, 782, 796, 292)
    box(d, (48, 454, 1152, 577), "#EAF1FF")
    text(d, 72, 480, "匹配优先级：决定命中哪条规则", 26, BLUE)
    text(d, 72, 527, "并发份额：决定同时执行工作的容量", 26)
    footer(d, "机制示意 · 席位不等于 QPS；大 LIST 可能占多个席位；队列满会拒绝")
    im.save(OUT / "02-apf-request-path.png", optimize=True)


def concurrency():
    im, d = canvas("相同 RPS，耗时越长，并发越高", "稳态算例：平均在途请求 ≈ 实际接纳速率 × 平均耗时")
    for i, (duration, count) in enumerate([(0.2, 4), (2, 40), (10, 200)]):
        x = 48 + 378 * i
        box(d, (x, 162, x + 348, 474))
        color = ORANGE if i == 2 else BLUE
        text(d, x + 24, 190, "接纳速率", 23, MUTED)
        text(d, x + 24, 235, "20 req/s", 34, bold=True)
        text(d, x + 24, 299, f"平均耗时 {duration:g} 秒", 25)
        text(d, x + 24, 353, str(count), 55, color, bold=True)
        text(d, x + 24, 429, "个平均在途请求", 23, MUTED)
    text(d, 50, 518, "速率限制、并发上限、等待队列，需要配合设置。", 27)
    text(d, 50, 562, "若后端承载不了接纳流量，队列会持续增长，稳态条件失效。", 22, MUTED)
    footer(d, "假设算例，非实测 · 未计突发、重试和服务时间分布 · 不代表推荐阈值")
    im.save(OUT / "03-rate-and-concurrency.png", optimize=True)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for render in [layers, apf, concurrency]:
        render()
    mobile()
    print(OUT)


def mobile():
    """Recompose the diagrams for phone screens; do not shrink a desktop grid."""
    specs = [
        ("01-three-layers-mobile.png", "三条流量路径，分别治理", "找到拥堵发生在哪一层", [
            ("01  API 调用", ["APF + 客户端限速", "分类、并发预算、公平排队", "保护 API Server 与 etcd"]),
            ("02  GPU 任务", ["任务队列 + 资源配额", "准入、公平共享、资源抢占", "治理 GPU / CPU / 内存占用"]),
            ("03  模型请求", ["网关 + 引擎并发控制", "速率、Token、等待预算", "保护首 Token 与持续生成延迟"]),
        ], ["架构示意，不是集群实测。", "三层分别配置，不能相互替代。"]),
        ("02-apf-request-path-mobile.png", "APF：分类与公平排队", "沿请求路径理解执行容量", [
            ("01  FlowSchema", ["识别调用方与资源操作", "决定命中规则及流的划分", "匹配顺序不等于执行份额"]),
            ("02  PriorityLevel", ["设置名义并发份额", "配置借入、借出与队列", "席位不是固定的 QPS"]),
            ("03  Execute / Reject", ["容量允许时执行", "有界队列等待机会", "超出边界时拒绝"]),
        ], ["机制示意；大 LIST 可能占多个席位。", "WATCH 有专门的席位核算规则。"]),
        ("03-rate-and-concurrency-mobile.png", "相同速率，不同并发", "稳态：平均在途请求 ≈ 速率 × 耗时", [
            ("平均耗时 0.2 秒", ["20 req/s", "4", "个平均在途请求"]),
            ("平均耗时 2 秒", ["20 req/s", "40", "个平均在途请求"]),
            ("平均耗时 10 秒", ["20 req/s", "200", "个平均在途请求"]),
        ], ["假设算例，非实测，也不是推荐阈值。", "队列持续增长时，稳态条件不成立。"]),
    ]
    for filename, title, subtitle, cards, notes in specs:
        im = Image.new("RGB", (720, 1080), BG)
        d = ImageDraw.Draw(im)
        text(d, 36, 34, title, 36)
        text(d, 38, 96, subtitle, 24, MUTED)
        is_numbers = filename.startswith("03")
        for i, (heading, lines) in enumerate(cards):
            y = 153 + i * 260
            box(d, (32, y, 688, y + 234))
            text(d, 55, y + 23, heading, 29, BLUE)
            if is_numbers:
                text(d, 55, y + 78, lines[0], 28, bold=True)
                text(d, 389, y + 83, lines[1], 57, ORANGE if i == 2 else BLUE, bold=True)
                text(d, 55, y + 171, lines[2], 25, MUTED)
            else:
                for j, line in enumerate(lines):
                    text(d, 55, y + 82 + j * 47, line, 27, INK if j == 0 else MUTED)
        box(d, (32, 952, 688, 1058))
        for i, line in enumerate(notes):
            text(d, 52, 973 + i * 40, line, 24, MUTED)
        im.save(OUT / filename, optimize=True)


if __name__ == "__main__":
    main()
