#!/usr/bin/env python3
"""Conceptual scheduler diagram using the existing M3 article visual system."""
import hashlib
import json
from pathlib import Path

from generate_large_scale_kubernetes_visuals import (
    BLUE, LINE, MUTED, ORANGE, arrow, canvas, centered,
)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/assets/practices/large-scale-kubernetes-scheduler'


def tile(draw, box, label, color=BLUE, size=23):
    draw.rounded_rectangle(box, radius=10, fill='white', outline=LINE, width=2)
    centered(draw, (box[0] + 8, box[1] + 7, box[2] - 8, box[3] - 7), label, size, color)


def main():
    image, draw = canvas(
        '两种并行，优化的是不同层次',
        '节点计算并行：缩短一次决策；独立调度分片：同时处理不同资源池的 Pod',
        'parallelism 控制节点计算；独立调度分片需要明确资源边界',
    )
    for box in [(48, 150, 582, 582), (610, 150, 1152, 582)]:
        draw.rounded_rectangle(box, radius=16, fill='white', outline=LINE, width=2)
    centered(draw, (70, 169, 560, 205), '一个 Pod，节点计算并行', 25, BLUE, True)
    tile(draw, (95, 225, 535, 279), '当前 Pod 的调度周期', BLUE, 25)
    draw.line([(315, 279), (315, 305)], fill=MUTED, width=3)
    draw.line([(154, 305), (476, 305)], fill=MUTED, width=3)
    for left, label in [(93, '节点 A'), (254, '节点 B'), (415, '节点 C')]:
        middle = left + 61
        arrow(draw, [(middle, 305), (middle, 333)])
        tile(draw, (left, 333, left + 122, 394), label)
        draw.line([(middle, 394), (middle, 421)], fill=MUTED, width=3)
    draw.line([(154, 421), (476, 421)], fill=MUTED, width=3)
    arrow(draw, [(315, 421), (315, 445)])
    tile(draw, (95, 445, 535, 499), '汇总结果，选择一个节点', BLUE, 23)
    centered(draw, (70, 527, 560, 565), '下一 Pod 等待本次决策完成', 22, MUTED)

    centered(draw, (632, 169, 1130, 205), '不同 Pod，按资源池分片', 25, ORANGE, True)
    for y, workload, scheduler, pool in [
        (225, '在线 Pod', '调度器 A', '在线节点池'),
        (335, '训练 Pod', '调度器 B', '训练节点池'),
        (445, '批处理 Pod', '调度器 C', '批处理池'),
    ]:
        tile(draw, (632, y, 766, y + 54), workload, ORANGE, 22)
        arrow(draw, [(773, y + 27), (791, y + 27)], ORANGE)
        tile(draw, (799, y, 935, y + 54), scheduler, ORANGE, 22)
        arrow(draw, [(942, y + 27), (959, y + 27)], ORANGE)
        tile(draw, (967, y, 1130, y + 54), pool, ORANGE, 22)
    centered(draw, (632, 527, 1130, 565), '每片内仍串行；节点池互斥', 22, MUTED)

    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / 'parallelism-and-sharding.png'
    image.save(target, optimize=True)
    (OUT / 'parallelism-visual-manifest.json').write_text(json.dumps({
        'kind': 'conceptual diagram; no benchmark values',
        'path': str(target.relative_to(ROOT)),
        'size': list(image.size),
        'sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
        'generator': str(Path(__file__).relative_to(ROOT)),
        'sources': [
            'https://kubernetes.io/docs/concepts/scheduling-eviction/scheduling-framework/',
            'https://kubernetes.io/docs/concepts/scheduling-eviction/running-multiple-schedulers/',
        ],
    }, ensure_ascii=False, indent=2) + '\n')
    print(target)


if __name__ == '__main__':
    main()
