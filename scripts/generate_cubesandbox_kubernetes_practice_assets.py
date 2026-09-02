#!/usr/bin/env python3
"""Generate sanitized figures for the CubeSandbox Kubernetes practice guide."""

from __future__ import annotations

import html
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "docs/assets/rag-agent/cubesandbox-kubernetes-practice"
WIDTH = 1600
HEIGHT = 900


def esc(value: str) -> str:
    return html.escape(value, quote=True)


def text(
    x: int,
    y: int,
    value: str,
    *,
    size: int = 28,
    color: str = "#172033",
    weight: int = 400,
    family: str = "PingFang SC, Hiragino Sans GB, sans-serif",
    anchor: str = "start",
) -> str:
    return (
        f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" '
        f'font-weight="{weight}" fill="{color}" text-anchor="{anchor}">'
        f"{esc(value)}</text>"
    )


def rect(
    x: int,
    y: int,
    width: int,
    height: int,
    *,
    fill: str = "#FFFFFF",
    stroke: str = "#CBD5E1",
    radius: int = 22,
    stroke_width: int = 2,
) -> str:
    return (
        f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="{radius}" '
        f'fill="{fill}" stroke="{stroke}" stroke-width="{stroke_width}"/>'
    )


def line(x1: int, y1: int, x2: int, y2: int, *, color: str = "#2563EB", width: int = 4) -> str:
    return (
        f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
        f'stroke="{color}" stroke-width="{width}" marker-end="url(#arrow)"/>'
    )


def multiline(
    x: int,
    y: int,
    lines: list[str],
    *,
    size: int = 24,
    leading: int = 38,
    color: str = "#172033",
    weight: int = 400,
    family: str = "PingFang SC, Hiragino Sans GB, sans-serif",
) -> str:
    return "".join(
        text(x, y + index * leading, value, size=size, color=color, weight=weight, family=family)
        for index, value in enumerate(lines)
    )


def base(title_value: str, subtitle: str) -> list[str]:
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">',
        "<defs>",
        '<marker id="arrow" markerWidth="12" markerHeight="12" refX="10" refY="6" orient="auto">',
        '<path d="M0,0 L12,6 L0,12 Z" fill="context-stroke"/>',
        "</marker>",
        '<filter id="shadow" x="-10%" y="-10%" width="120%" height="130%">',
        '<feDropShadow dx="0" dy="8" stdDeviation="12" flood-color="#13213C" flood-opacity="0.10"/>',
        "</filter>",
        "</defs>",
        '<rect width="1600" height="900" fill="#F7F9FC"/>',
        text(64, 68, title_value, size=38, weight=700),
        text(66, 110, subtitle, size=20, color="#5E6B82"),
        '<rect x="64" y="134" width="1472" height="2" fill="#D8E0EB"/>',
        text(1536, 865, "aik8s.run · CubeSandbox v0.7.0 实测", size=17, color="#718096", anchor="end"),
    ]


def topology_svg() -> str:
    s = base(
        "CubeSandbox 在 Kubernetes 上的真实落点",
        "Kubernetes 交付控制面和节点运行时；Agent 沙箱由 Cubelet 在 KVM MicroVM 中创建",
    )

    s += [
        rect(70, 175, 455, 580, fill="#EDF4FF", stroke="#9CB8EE"),
        text(105, 220, "控制面 · Deployments", size=28, color="#1746A2", weight=700),
        rect(105, 255, 175, 82, fill="#FFFFFF", stroke="#A9BFE8", radius=15),
        text(192, 288, "WebUI", size=23, weight=700, anchor="middle"),
        text(192, 316, "JWT 管理界面", size=16, color="#5E6B82", anchor="middle"),
        rect(315, 255, 175, 82, fill="#FFFFFF", stroke="#A9BFE8", radius=15),
        text(402, 288, "CubeAPI", size=23, weight=700, anchor="middle"),
        text(402, 316, "E2B 兼容 API", size=16, color="#5E6B82", anchor="middle"),
        line(192, 352, 192, 385, color="#7B98D1", width=3),
        line(402, 352, 402, 385, color="#7B98D1", width=3),
        rect(105, 385, 385, 92, fill="#DCEAFF", stroke="#7FA3E6", radius=17),
        text(297, 423, "CubeMaster", size=27, color="#1746A2", weight=700, anchor="middle"),
        text(297, 454, "模板 · 调度 · 沙箱生命周期", size=18, color="#48658F", anchor="middle"),
        line(297, 492, 297, 522, color="#7B98D1", width=3),
        rect(105, 522, 110, 92, fill="#FFFFFF", stroke="#A9BFE8", radius=15),
        rect(242, 522, 110, 92, fill="#FFFFFF", stroke="#A9BFE8", radius=15),
        rect(379, 522, 110, 92, fill="#FFFFFF", stroke="#A9BFE8", radius=15),
        text(160, 563, "MySQL", size=20, weight=700, anchor="middle"),
        text(297, 563, "Redis", size=20, weight=700, anchor="middle"),
        text(434, 563, "MinIO", size=20, weight=700, anchor="middle"),
        text(160, 590, "状态", size=15, color="#5E6B82", anchor="middle"),
        text(297, 590, "缓存", size=15, color="#5E6B82", anchor="middle"),
        text(434, 590, "制品", size=15, color="#5E6B82", anchor="middle"),
        rect(105, 652, 385, 65, fill="#FFFFFF", stroke="#A9BFE8", radius=15),
        text(297, 693, "PVC / StorageClass", size=20, color="#48658F", weight=700, anchor="middle"),
        rect(570, 255, 255, 165, fill="#FFF5E9", stroke="#F0B378"),
        text(697, 300, "数据入口", size=27, color="#C26313", weight=700, anchor="middle"),
        text(697, 342, "CubeProxy", size=24, weight=700, anchor="middle"),
        text(697, 375, "TLS · HTTP · gRPC", size=18, color="#7C5C3B", anchor="middle"),
        line(525, 430, 570, 345, color="#F37726", width=4),
        line(825, 345, 875, 345, color="#F37726", width=4),
        rect(875, 175, 655, 580, fill="#EAF9F6", stroke="#8FD6CA"),
        text(915, 220, "计算节点 · DaemonSets + 宿主机能力", size=28, color="#087F70", weight=700),
        rect(915, 255, 175, 85, fill="#FFFFFF", stroke="#85CCBF", radius=15),
        rect(1115, 255, 175, 85, fill="#FFFFFF", stroke="#85CCBF", radius=15),
        rect(1315, 255, 175, 85, fill="#FFFFFF", stroke="#85CCBF", radius=15),
        text(1002, 290, "installer", size=20, weight=700, anchor="middle"),
        text(1002, 318, "安装节点产物", size=15, color="#5E6B82", anchor="middle"),
        text(1202, 290, "bootstrap", size=20, weight=700, anchor="middle"),
        text(1202, 318, "检查宿主条件", size=15, color="#5E6B82", anchor="middle"),
        text(1402, 290, "cube-node", size=20, weight=700, anchor="middle"),
        text(1402, 318, "Cubelet 运行时", size=15, color="#5E6B82", anchor="middle"),
        line(1402, 355, 1402, 392, color="#0F9D8A", width=4),
        rect(940, 392, 540, 125, fill="#D9F5EF", stroke="#63BFAF", radius=19),
        text(1210, 435, "KVM MicroVM Sandbox", size=29, color="#087F70", weight=700, anchor="middle"),
        text(1210, 472, "独立 Guest Kernel · envd · 用户代码", size=19, color="#356F68", anchor="middle"),
        text(1210, 498, "创建/暂停/快照/恢复/销毁", size=17, color="#527E79", anchor="middle"),
        rect(915, 562, 175, 105, fill="#FFFFFF", stroke="#85CCBF", radius=15),
        rect(1115, 562, 175, 105, fill="#FFFFFF", stroke="#85CCBF", radius=15),
        rect(1315, 562, 175, 105, fill="#FFFFFF", stroke="#85CCBF", radius=15),
        text(1002, 605, "/dev/kvm", size=21, weight=700, anchor="middle"),
        text(1002, 635, "原生 KVM", size=16, color="#5E6B82", anchor="middle"),
        text(1202, 605, "/data/cubelet", size=21, weight=700, anchor="middle"),
        text(1202, 635, "XFS / reflink", size=16, color="#5E6B82", anchor="middle"),
        text(1402, 605, "bpffs / eBPF", size=21, weight=700, anchor="middle"),
        text(1402, 635, "CubeVS 网络", size=16, color="#5E6B82", anchor="middle"),
        rect(915, 690, 575, 45, fill="#FFF3F4", stroke="#E8A2AA", radius=12),
        text(1202, 720, "privileged + hostPID + hostPath：等同宿主机级集成", size=18, color="#B23443", weight=700, anchor="middle"),
    ]
    s.append("</svg>")
    return "".join(s)


def evidence_svg() -> str:
    s = base(
        "安装验收：不是 Pod Running，而是 8 组测试全部通过",
        "真实命令输出摘录（已脱敏）；版本、测试名称与计数保持原始结果",
    )
    s += [
        rect(65, 170, 930, 630, fill="#0B1220", stroke="#26344D", radius=24),
        '<circle cx="105" cy="210" r="9" fill="#FF6B6B"/>',
        '<circle cx="135" cy="210" r="9" fill="#F7C948"/>',
        '<circle cx="165" cy="210" r="9" fill="#52C77B"/>',
        text(205, 217, "deployment-evidence.txt", size=18, color="#94A3B8", family="Menlo, monospace"),
        multiline(100, 272, [
            "$ helm status cube -n cube-system",
            "STATUS: deployed    REVISION: 1",
            "",
            "$ kubectl get deploy,statefulset,daemonset,pvc",
            "Deployment    7/7 Ready",
            "StatefulSet   3/3 Ready",
            "DaemonSet     3/3 Ready",
            "PVC           4/4 Bound",
        ], size=21, leading=34, color="#D8E4F5", family="Menlo, monospace"),
        multiline(100, 575, [
            "$ helm test cube -n cube-system --logs",
            "cube-health-test              Succeeded",
            "cube-cubemastercli-test       Succeeded",
            "cube-cubeopscli-test          Succeeded",
            "cube-mysql-test               Succeeded",
            "cube-redis-test               Succeeded",
            "cube-proxy-control-test       Succeeded",
            "cube-node-image-test          Succeeded",
            "cube-node-runtime-test        Succeeded",
        ], size=20, leading=29, color="#D8E4F5", family="Menlo, monospace"),
        rect(1040, 170, 495, 630, fill="#FFFFFF", stroke="#CBD5E1", radius=24),
        text(1080, 225, "验收结论", size=28, weight=700),
        rect(1080, 260, 415, 86, fill="#E7F8F5", stroke="#8FD6CA", radius=16),
        text(1110, 298, "1 / 1", size=30, color="#087F70", weight=700),
        text(1210, 297, "计算节点健康", size=21, color="#356F68", weight=700),
        text(1210, 325, "HOST_STATUS = RUNNING", size=16, color="#527E79"),
        rect(1080, 370, 415, 86, fill="#EDF4FF", stroke="#9CB8EE", radius=16),
        text(1110, 408, "bm", size=30, color="#1746A2", weight=700),
        text(1210, 407, "普通内核模式", size=21, color="#48658F", weight=700),
        text(1210, 435, "PVM 未启用 · 无宿主机重启", size=16, color="#5E6B82"),
        rect(1080, 480, 415, 86, fill="#FFF7E8", stroke="#EDC075", radius=16),
        text(1110, 518, "0", size=30, color="#C26313", weight=700),
        text(1210, 517, "验收后残留沙箱", size=21, color="#7C5C3B", weight=700),
        text(1210, 545, "测试实例已销毁", size=16, color="#7C6A55"),
        rect(1080, 590, 415, 150, fill="#F8FAFC", stroke="#CBD5E1", radius=16),
        text(1110, 628, "共存检查", size=21, weight=700),
        text(1110, 665, "✓ 原有 KubeVirt VMI 继续 Running", size=18, color="#087F70"),
        text(1110, 698, "✓ 节点未添加 NoSchedule 污点", size=18, color="#087F70"),
        text(1110, 731, "✓ 初始依赖竞态重试后保持稳定", size=18, color="#087F70"),
    ]
    s.append("</svg>")
    return "".join(s)


def lifecycle_svg() -> str:
    s = base(
        "端到端验证：模板 Ready 后，沙箱必须真的能执行并清理",
        "真实生命周期输出摘录（标识符已脱敏）；模板镜像、节点地址和仓库信息不在图中展示",
    )

    stages = [
        (85, "PULLING", "拉取镜像", "#EDF4FF", "#2563EB"),
        (330, "UNPACKING", "解包 rootfs", "#EAF9F6", "#0F9D8A"),
        (575, "DISTRIBUTING", "分发到 1/1 节点", "#FFF7E8", "#F37726"),
        (820, "CREATING", "启动临时 MicroVM", "#F3F0FF", "#7C3AED"),
        (1065, "READY", "探针与快照完成", "#E7F8F5", "#087F70"),
    ]
    for index, (x, heading, body, fill, color) in enumerate(stages):
        s.append(rect(x, 190, 205, 112, fill=fill, stroke=color, radius=18))
        s.append(text(x + 102, 235, heading, size=22, color=color, weight=700, anchor="middle"))
        s.append(text(x + 102, 272, body, size=17, color="#5E6B82", anchor="middle"))
        if index < len(stages) - 1:
            s.append(line(x + 210, 246, x + 238, 246, color="#94A3B8", width=3))

    s += [
        rect(1305, 190, 210, 112, fill="#D9F5EF", stroke="#087F70", radius=18),
        text(1410, 235, "100%", size=29, color="#087F70", weight=700, anchor="middle"),
        text(1410, 272, "模板可用", size=18, color="#356F68", anchor="middle"),
        rect(85, 355, 925, 390, fill="#0B1220", stroke="#26344D", radius=24),
        '<circle cx="125" cy="395" r="9" fill="#FF6B6B"/>',
        '<circle cx="155" cy="395" r="9" fill="#F7C948"/>',
        '<circle cx="185" cy="395" r="9" fill="#52C77B"/>',
        text(225, 402, "sandbox-smoke.log", size=18, color="#94A3B8", family="Menlo, monospace"),
        multiline(125, 460, [
            "$ POST /sandboxes  { templateID: \"<redacted>\" }",
            "created=sb-<redacted>",
            "state=running",
            "",
            "$ cubecli exec sb-<redacted> sh -lc '<smoke>'",
            "cube-smoke-ok",
            "x86_64",
            "guest-kernel=6.6.1199-0009-03_2.0.1",
            "rootfs=overlay",
            "",
            "$ DELETE /sandboxes/sb-<redacted>",
            "destroyed=sb-<redacted>    SANDBOX_COUNT=0",
        ], size=21, leading=29, color="#D8E4F5", family="Menlo, monospace"),
        rect(1055, 355, 460, 390, fill="#FFFFFF", stroke="#CBD5E1", radius=24),
        text(1095, 410, "这一步证明了什么？", size=27, weight=700),
        rect(1095, 448, 380, 60, fill="#E7F8F5", stroke="#8FD6CA", radius=14),
        text(1123, 487, "✓ KVM MicroVM 能启动", size=20, color="#087F70", weight=700),
        rect(1095, 528, 380, 60, fill="#E7F8F5", stroke="#8FD6CA", radius=14),
        text(1123, 567, "✓ Guest 命令能执行", size=20, color="#087F70", weight=700),
        rect(1095, 608, 380, 60, fill="#E7F8F5", stroke="#8FD6CA", radius=14),
        text(1123, 647, "✓ 生命周期能清理", size=20, color="#087F70", weight=700),
        text(1095, 706, "Pod Ready 只证明组件活着；", size=18, color="#5E6B82"),
        text(1095, 733, "Create → Exec → Destroy 才是最小业务闭环。", size=18, color="#5E6B82", weight=700),
    ]
    s.append("</svg>")
    return "".join(s)


def render_png(name: str, svg: str) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output = OUTPUT_DIR / f"{name}.png"
    with tempfile.TemporaryDirectory(prefix="cubesandbox-visual-") as temp_dir:
        source = Path(temp_dir) / f"{name}.svg"
        source.write_text(svg, encoding="utf-8")
        subprocess.run(
            ["qlmanage", "-t", "-s", str(WIDTH), "-o", temp_dir, str(source)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        rendered = Path(temp_dir) / f"{source.name}.png"
        if not rendered.is_file():
            raise FileNotFoundError(f"Quick Look did not render {source}")
        shutil.copyfile(rendered, output)


def main() -> None:
    render_png("01-kubernetes-topology", topology_svg())
    render_png("02-deployment-evidence", evidence_svg())
    render_png("03-sandbox-lifecycle", lifecycle_svg())


if __name__ == "__main__":
    main()
