#!/usr/bin/env python3
"""Anonymous network diagrams in the existing M3 article style.

These are explanations, not product screenshots. Example addresses and VLANs
are synthetic; no internal environment data or raw evidence is an input.
"""
import hashlib
import json
from pathlib import Path

from generate_large_scale_kubernetes_visuals import (
    BLUE, LINE, MUTED, ORANGE, arrow, canvas, centered, text,
)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/assets/practices/contiv-ovs-cilium-network"
MANIFEST = []


def tile(d, box, title, detail="", color=BLUE):
    d.rounded_rectangle(box, radius=12, fill="white", outline=LINE, width=2)
    if detail:
        centered(d, (box[0] + 10, box[1] + 10, box[2] - 10, box[1] + 49), title, 25, color, True)
        centered(d, (box[0] + 10, box[1] + 57, box[2] - 10, box[3] - 9), detail, 22, MUTED)
    else:
        centered(d, (box[0] + 10, box[1] + 8, box[2] - 10, box[3] - 8), title, 24, color, True)


def save(im, filename, description):
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / filename
    im.save(p, optimize=True)
    MANIFEST.append({
        "path": str(p.relative_to(ROOT)), "kind": "explanatory diagram, not screenshot",
        "description": description, "size": list(im.size),
        "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
    })


def responsibilities():
    im, d = canvas(
        "CNI 串联与报文转发，是两条不同的线",
        "匿名案例 · Contiv 保留 VLAN 网络；Cilium 接入现有 veth 并提供 Service 能力",
        "CNI 在创建网络时执行；正常转发不逐次调用 CNI 插件",
    )
    text(d, 48, 151, "创建 Pod 网络", 24, BLUE, True)
    for x, title, detail in [(48, "Contiv CNI", "地址、veth、OVS 端口"),
                              (432, "Cilium CNI", "识别 veth，注册端点"),
                              (816, "自定义后置插件", "环境专用的网络扩展")]:
        tile(d, (x, 198, x + 336, 304), title, detail)
    arrow(d, [(393, 250), (422, 250)], BLUE)
    arrow(d, [(777, 250), (806, 250)], BLUE)
    text(d, 48, 347, "本次普通 Pod 的 TCP 路径", 24, ORANGE, True)
    boxes = [(48, 397, 277, 503), (340, 397, 571, 503),
             (634, 397, 865, 503), (928, 397, 1152, 503)]
    for box, title, detail in zip(boxes,
            ["Pod / Socket LB", "veth / Cilium TC", "OVS VLAN 交换", "物理网络"],
            ["连接时选定后端", "端点报文与策略", "端口 tag / 二层", "交换 / 网关路由"]):
        tile(d, box, title, detail, ORANGE)
    for left, right in zip(boxes, boxes[1:]):
        arrow(d, [(left[2] + 10, 450), (right[0] - 10, 450)], ORANGE)
    centered(d, (48, 530, 1152, 582), "跨 VLAN 请求走网络网关；节点自身有独立的管理网络接口", 23, MUTED)
    save(im, "responsibilities.png", "Observed chaining and division of responsibilities; gateway plugin details are environment-specific.")


def netfilter_paths():
    im, d = canvas(
        "规则能写进去，报文也未必经过它",
        "iptables kube-proxy 依赖主机 netfilter；OVS system 端口的二层交换可以绕过这条路径",
        "是否进入主机 IP 栈，由端口、流表和路由共同决定；不能仅凭组件名称判断",
    )
    for box in [(48, 151, 582, 585), (610, 151, 1152, 585)]:
        d.rounded_rectangle(box, 16, fill="white", outline=LINE, width=2)
    centered(d, (70, 169, 560, 207), "Pod 经 OVS 二层交换", 26, ORANGE, True)
    for y, title, detail in [(230, "Pod → veth system 端口", "目的地址仍是 Service VIP"),
                              (355, "OVS NORMAL → VLAN 上联", "报文可直接去网络网关")]:
        tile(d, (82, y, 548, y + 93), title, detail, ORANGE)
    arrow(d, [(315, 328), (315, 347)], ORANGE)
    centered(d, (78, 475, 552, 515), "没有进入主机 IP 栈", 25, ORANGE, True)
    centered(d, (78, 525, 552, 565), "主机 KUBE-SERVICES 不会处理该报文", 22, MUTED)
    centered(d, (632, 169, 1130, 207), "经过主机 IP 栈的请求", 26, BLUE, True)
    for y, title, detail in [(230, "主机本地请求 / 有效的 L3 入口", "进入 OUTPUT 或 PREROUTING"),
                              (355, "netfilter → Service 转换", "kube-proxy 规则选择后端并 DNAT")]:
        tile(d, (644, y, 1118, y + 93), title, detail)
    arrow(d, [(881, 328), (881, 347)], BLUE)
    centered(d, (640, 475, 1122, 515), "规则才有机会命中", 25, BLUE, True)
    centered(d, (640, 525, 1122, 565), "主机可访问 ≠ 所有 Pod 路径都可访问", 22, MUTED)
    save(im, "netfilter-paths.png", "Conditional packet paths explaining iptables compatibility, not a reproduced kube-proxy incident.")


def socket_evidence():
    im, d = canvas(
        "这次请求，在 Socket 层就选好了后端",
        "基于实测的脱敏示意 · HTTP 请求成功；地址、VLAN 与接口名称均已替换",
        "Pod 内看不到 Service VIP，可以是 Socket LB 的正常结果；不等于丢包",
    )
    for y, title, detail, color in [
        (150, "应用发起连接", "Service：10.120.0.80:80", BLUE),
        (273, "Pod eth0 抓包", "后端：10.244.20.31:3000", ORANGE),
        (396, "物理上联抓包", "同一后端 + VLAN 200；源 Pod IP 保留", ORANGE),
    ]:
        tile(d, (48, y, 603, y + 100), title, detail, color)
    arrow(d, [(325, 254), (325, 268)], BLUE)
    arrow(d, [(325, 377), (325, 392)], ORANGE)
    d.rounded_rectangle((662, 150, 1152, 496), 16, fill="white", outline=LINE, width=2)
    centered(d, (682, 170, 1132, 210), "运行状态交叉验证", 26, BLUE, True)
    for y, label in [(236, "KubeProxyReplacement = True"),
                     (291, "Socket LB = Enabled / Full"),
                     (346, "BPF Map：Service → Backend"),
                     (401, "主机无 KUBE-SERVICES 链")]:
        centered(d, (681, y, 1133, y + 36), label, 22, MUTED)
    centered(d, (48, 525, 1152, 581), "TC 程序也挂在现有 veth 上；但不能把这次 TCP 改写误归因于 TC", 23, MUTED)
    save(im, "socket-lb-evidence.png", "Sanitized explanation of request log, runtime status, BPF map and actual packet-header observations.")


def main():
    responsibilities()
    netfilter_paths()
    socket_evidence()
    (OUT / "visual-manifest.json").write_text(json.dumps({
        "generator": str(Path(__file__).relative_to(ROOT)),
        "privacy": "Only synthetic example identifiers; no raw evidence embedded.",
        "figures": MANIFEST,
        "sources": ["https://docs.openvswitch.org/en/latest/faq/issues/",
                    "https://docs.cilium.io/en/stable/network/kubernetes/kubeproxy-free/"],
    }, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"figures": len(MANIFEST), "output": str(OUT.relative_to(ROOT))}))


if __name__ == "__main__":
    main()
