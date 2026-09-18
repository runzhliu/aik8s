#!/usr/bin/env python3
"""Generate deterministic figures for the large-scale Kubernetes guide.

All figures are engineering diagrams, not measured benchmark charts.  The
numbers in the pressure diagram are explicitly labelled as arithmetic based on
the Kubernetes default node lease renewal interval.
"""

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/assets/practices/large-scale-kubernetes-optimization"
W, H = 1200, 675

BG = "#F6F8FC"
PANEL = "#FFFFFF"
INK = "#172033"
MUTED = "#667085"
LINE = "#D8DFEA"
BLUE = "#2457E6"
TEAL = "#07867D"
PURPLE = "#7654D8"
ORANGE = "#D97812"
RED = "#C43D4D"

FONT_PATH = "/System/Library/Fonts/Hiragino Sans GB.ttc"


def font(size: int, bold: bool = False):
    # Hiragino Sans GB has regular/bold faces in the collection.
    return ImageFont.truetype(FONT_PATH, size=size, index=1 if bold else 0)


def text(draw, xy, value, size, color=INK, bold=False, anchor=None):
    draw.text(xy, value, font=font(size, bold), fill=color, anchor=anchor)


def rounded(draw, box, fill=PANEL, outline=LINE, radius=18, width=2):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def arrow(draw, start, end, color=MUTED, width=4):
    draw.line([start, end], fill=color, width=width)
    x2, y2 = end
    x1, y1 = start
    if abs(x2 - x1) >= abs(y2 - y1):
        points = [(x2, y2), (x2 - 13 if x2 > x1 else x2 + 13, y2 - 8),
                  (x2 - 13 if x2 > x1 else x2 + 13, y2 + 8)]
    else:
        points = [(x2, y2), (x2 - 8, y2 - 13 if y2 > y1 else y2 + 13),
                  (x2 + 8, y2 - 13 if y2 > y1 else y2 + 13)]
    draw.polygon(points, fill=color)


def canvas(title, subtitle):
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    text(draw, (52, 38), title, 31, INK, True)
    text(draw, (52, 83), subtitle, 18, MUTED)
    return img, draw


def box(draw, bounds, title, lines, accent=BLUE, tint="#EEF3FF"):
    x1, y1, x2, y2 = bounds
    rounded(draw, bounds, fill=PANEL)
    draw.rounded_rectangle((x1 + 14, y1 + 14, x1 + 22, y2 - 14), 4, fill=accent)
    text(draw, (x1 + 40, y1 + 26), title, 22, accent, True)
    for idx, line in enumerate(lines):
        text(draw, (x1 + 40, y1 + 61 + idx * 26), line, 17, MUTED)


def pressure_model():
    img, d = canvas(
        "万节点集群的压力，来自被放大的控制循环",
        "工程推导 · 节点数只是入口，对象数、写入频率、Watch 消费者与突发变更共同决定压力",
    )
    box(d, (52, 136, 330, 318), "10,000 个节点", [
        "默认每 10 秒续租一次 Lease",
        "算术基线约 1,000 次写入/秒",
        "尚未计入 Pod、Event 与业务对象",
    ], BLUE)
    box(d, (458, 136, 742, 318), "API Server", [
        "认证、准入、APF 与序列化",
        "LIST / WATCH 缓存与分发",
        "突发加节点会集中放大请求",
    ], PURPLE)
    box(d, (870, 136, 1148, 318), "控制器与节点 Agent", [
        "每个副本可能建立完整 Watch",
        "DaemonSet 数量随节点线性增长",
        "无缓存轮询会再次打回控制面",
    ], ORANGE)
    box(d, (458, 388, 742, 542), "etcd", [
        "Raft 提交依赖多数派与磁盘 fsync",
        "写放大、碎片与慢 Range 会累积",
        "增加成员不能增加写入容量",
    ], TEAL)
    arrow(d, (330, 226), (446, 226))
    arrow(d, (742, 226), (858, 226))
    arrow(d, (600, 318), (600, 376))
    arrow(d, (858, 279), (754, 424), color=ORANGE)
    rounded(d, (52, 580, 1148, 640), fill="#EAF0FF", outline="#C7D5FF")
    text(d, (600, 610), "容量模型 = 对象数量 × 变更频率 × Watch 扇出 × 单次请求成本 × 峰值系数", 23, BLUE, True, "mm")
    img.save(OUT / "control-plane-pressure.png", quality=95)


def choice_model():
    img, d = canvas(
        "把一万节点当成架构选择，而不是调参目标",
        "三条路线的责任边界不同；选型前先验证故障域、资源利用率、作业形态和平台能力",
    )
    cards = [
        (52, BLUE, "多个受控规模集群", "默认选择", [
            "落在上游验证范围内",
            "升级与故障域更容易隔离",
            "代价是容量碎片与跨集群调度",
        ]),
        (426, TEAL, "托管超大规模能力", "供应商边界", [
            "控制面和存储可能已做专用分片",
            "规模数字不等于上游默认能力",
            "需要核对配额、SLA 与迁移路径",
        ]),
        (800, PURPLE, "定制单一超大集群", "高投入路线", [
            "适合大作业共享整池资源",
            "需要专用压测、分片和恢复工程",
            "故障半径与升级成本最高",
        ]),
    ]
    for x, color, title_, tag, lines in cards:
        rounded(d, (x, 142, x + 348, 406), fill=PANEL)
        d.rounded_rectangle((x + 24, 166, x + 132, 201), 15, fill=color)
        text(d, (x + 78, 184), tag, 16, "#FFFFFF", True, "mm")
        text(d, (x + 24, 230), title_, 23, INK, True)
        for i, line in enumerate(lines):
            d.ellipse((x + 24, 281 + i * 39, x + 34, 291 + i * 39), fill=color)
            text(d, (x + 48, 273 + i * 39), line, 17, MUTED)
    rounded(d, (52, 454, 1148, 628), fill="#FFFFFF")
    text(d, (76, 484), "进入单集群万节点路线前，我会要求同时回答四个问题", 22, INK, True)
    gates = [
        ("作业形态", "少 Pod/节点", "调度约束可控"),
        ("控制面", "写入、LIST/WATCH", "和扩容峰值有预算"),
        ("故障恢复", "etcd 和整集群", "恢复做过演练"),
        ("收益", "容量收益明显", "且能接受故障半径"),
    ]
    for i, (name, detail1, detail2) in enumerate(gates):
        x = 76 + i * 268
        d.rounded_rectangle((x, 530, x + 244, 600), 12, fill="#F3F6FC", outline=LINE)
        text(d, (x + 14, 541), name, 16, BLUE, True)
        text(d, (x + 14, 565), detail1, 13, MUTED)
        text(d, (x + 14, 584), detail2, 13, MUTED)
    img.save(OUT / "ten-thousand-node-choice.png", quality=95)


def etcd_loop():
    img, d = canvas(
        "etcd 优化顺序：先减负，再维护，最后才分片",
        "生产闭环 · 每一步都用指标和恢复演练验证，不能用扩大 quota 掩盖对象泄漏",
    )
    steps = [
        ("1  减少写放大", "只在状态变化时更新；治理 Event、Lease、CRD status", BLUE),
        ("2  隔离关键资源", "专用 NVMe、稳定低延迟网络、保证 CPU 与内存", PURPLE),
        ("3  压缩与碎片整理", "compact 清历史；defrag 逐成员执行并观察阻塞", ORANGE),
        ("4  备份与恢复演练", "校验快照；恢复时处理 revision 与 informer 缓存", TEAL),
        ("5  按资源拆分", "Event 优先；仅在测量证明确有需要时使用", RED),
    ]
    y = 132
    for i, (name, detail, color) in enumerate(steps):
        rounded(d, (52, y, 680, y + 76), fill=PANEL)
        d.rounded_rectangle((68, y + 14, 83, y + 62), 7, fill=color)
        text(d, (104, y + 18), name, 20, color, True)
        text(d, (104, y + 46), detail, 15, MUTED)
        if i < len(steps) - 1:
            arrow(d, (366, y + 76), (366, y + 92), color=LINE, width=3)
        y += 94
    rounded(d, (724, 132, 1148, 602), fill="#17233E", outline="#17233E")
    text(d, (752, 162), "每一步都要看的信号", 23, "#FFFFFF", True)
    metrics = [
        ("磁盘", "WAL fsync / backend commit P99"),
        ("Raft", "pending / failed proposal、leader 变化"),
        ("容量", "DB total、in-use 与 quota 比例"),
        ("网络", "peer RTT 与收发失败"),
        ("业务", "API LIST/WATCH/WRITE 延迟和失败率"),
        ("恢复", "快照年龄、校验结果、实测 RPO/RTO"),
    ]
    for i, (name, detail) in enumerate(metrics):
        yy = 212 + i * 59
        d.rounded_rectangle((752, yy, 1120, yy + 44), 10, fill="#243454")
        text(d, (768, yy + 12), name, 16, "#8FB2FF", True)
        text(d, (833, yy + 12), detail, 14, "#E4EAF6")
    text(d, (936, 574), "指标 → 判断 → 动作 → 复测", 16, "#FFFFFF", True, "mm")
    img.save(OUT / "etcd-optimization-loop.png", quality=95)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    pressure_model()
    choice_model()
    etcd_loop()
    print(f"generated assets in {OUT}")
