#!/usr/bin/env python3
"""Generate third-edition (V3) bilingual figures for kubernetes-137-dra-topology-sharing-health.

Follows V3 style (scripts/generate_dsv41_vllm032_research_assets.py):
- White background, crisp whitespace, flat solid fills, light axes
- Chinese: Hiragino Sans GB W3 (face 0); Latin/digits: Helvetica Neue Light (face 7) / Regular (face 0)
- Default muted green (#78B5A3), neutral gray (#D4D4D8), charcoal slate (#475569), ink (#202020)
- 1200x675 (16:9) rendered at 2x supersampling with LANCZOS downsampling
- ASCII-safe English labels (no Unicode arrows in Helvetica Neue)
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
CN_DIR = ROOT / "docs/assets/practices/kubernetes-137-dra-topology-sharing-health"
EN_DIR = ROOT / "translations/en-assets/assets/practices/kubernetes-137-dra-topology-sharing-health"
CN_DIR.mkdir(parents=True, exist_ok=True)
EN_DIR.mkdir(parents=True, exist_ok=True)

W, H = 1200, 675
S = 2

INK = "#202020"
MUTED = "#6B7280"
LIGHT_MUTED = "#9CA3AF"
GRID = "#EAEAEA"
AXIS = "#C8C8C8"
GRAY = "#D4D4D8"
GREEN = "#78B5A3"
GREEN_DARK = "#2F6F5E"
GREEN_BG = "#F4FAF8"
SLATE = "#475569"
FREE_BG = "#F5F5F6"
AMBER = "#B45309"


def face(value, size, light=False, mono=False):
    if mono:
        path = "/System/Library/Fonts/Menlo.ttc"
        index = 0
    elif any("\u3400" <= ch <= "\u9fff" for ch in value):
        path = "/System/Library/Fonts/Hiragino Sans GB.ttc"
        index = 0  # W3
    else:
        path = "/System/Library/Fonts/HelveticaNeue.ttc"
        index = 7 if light else 0
    return ImageFont.truetype(path, round(size * S), index=index)


def text(d, x, y, value, size=20, color=INK, align="left", light=False, mono=False):
    f = face(value, size, light, mono)
    b = d.textbbox((0, 0), value, font=f)
    tw, th = b[2] - b[0], b[3] - b[1]
    xx = x * S - (tw / 2 if align == "center" else tw if align == "right" else 0)
    assert -2 <= xx and xx + tw <= W * S + 2, f"x out of bounds: {value} ({xx/S}, {(xx+tw)/S})"
    assert -2 <= y * S and y * S + th <= H * S + 2, f"y out of bounds: {value}"
    d.text((xx - b[0], y * S - b[1]), value, font=f, fill=color)
    return tw / S, th / S


def line(d, x1, y1, x2, y2, color=GRID, width=1):
    d.line((round(x1 * S), round(y1 * S), round(x2 * S), round(y2 * S)), fill=color, width=round(width * S))


def dashed_line(d, x1, y1, x2, y2, color=AMBER, width=2, dash=8):
    import math
    dist = math.hypot(x2 - x1, y2 - y1)
    steps = max(1, int(dist / (dash * 1.6)))
    for i in range(steps):
        t0 = i / steps
        t1 = min(1.0, (i + 0.55) / steps)
        line(d, x1 + (x2 - x1) * t0, y1 + (y2 - y1) * t0, x1 + (x2 - x1) * t1, y1 + (y2 - y1) * t1, color=color, width=width)


def rect(d, x, y, w, h, fill=None, outline=None, width=1):
    d.rectangle(
        (round(x * S), round(y * S), round((x + w) * S), round((y + h) * S)),
        fill=fill,
        outline=outline,
        width=round(width * S) if outline else 0,
    )


def new_canvas(title, subtitle):
    im = Image.new("RGB", (W * S, H * S), "white")
    d = ImageDraw.Draw(im)
    text(d, 56, 40, title, 33, INK, light=True)
    text(d, 56, 92, subtitle, 18, MUTED, light=True)
    return im, d


def fig1_pcie_alignment(cn=True):
    title = "跨驱动 PCIe Root 拓扑绑定：无约束错配 vs matchAttribute 对齐" if cn else "Cross-driver PCIe root alignment: unaligned vs. matchAttribute"
    sub = (
        "Kubernetes v1.37.2 + dra-example-driver v0.5.0（gpu.example.com ×4 + net.example.com ×2）· 同节点双 PCIe Root"
        if cn
        else "Kubernetes v1.37.2 + dra-example-driver v0.5.0 (4 GPUs + 2 NICs across two PCIe roots on one worker)"
    )
    im, d = new_canvas(title, sub)

    # Legend
    legs = (
        [(650, "GPU (gpu.example.com)", GREEN), (885, "RDMA NIC (net.example.com)", SLATE)]
        if cn
        else [(665, "GPU (gpu.example.com)", GREEN), (900, "RDMA NIC (net.example.com)", SLATE)]
    )
    for lx, lbl, col in legs:
        rect(d, lx, 140, 15, 15, fill=col)
        text(d, lx + 23, 138, lbl, 17, MUTED)

    # Left panel: Without matchAttribute
    lx0 = 56
    text(d, lx0, 184, "对照组：未配 matchAttribute" if cn else "Control: No matchAttribute", 23, INK, light=True)
    text(d, lx0, 217, "跨 PCIe Root 错配仍静默 Running（1.43 s）" if cn else "Cross-socket mismatch runs silently (1.43 s)", 16, MUTED)
    line(d, lx0, 248, lx0 + 500, 248, color=GRID)

    # Socket 0 box (left)
    rect(d, lx0, 266, 500, 114, fill=FREE_BG, outline=GRAY, width=1.2)
    text(d, lx0 + 16, 276, "PCIe Root A · pci0000:00", 16, MUTED, mono=True)
    rect(d, lx0 + 16, 310, 134, 52, fill="white", outline=GRAY, width=1.2)
    text(d, lx0 + 83, 327, "gpu-0", 17, LIGHT_MUTED, align="center")
    rect(d, lx0 + 164, 310, 134, 52, fill="white", outline=GRAY, width=1.2)
    text(d, lx0 + 231, 327, "gpu-2", 17, LIGHT_MUTED, align="center")
    rect(d, lx0 + 344, 310, 140, 52, fill=SLATE)
    text(d, lx0 + 414, 319, "nic-0 (25G)", 16, "white", align="center")
    text(d, lx0 + 414, 340, "s1a-unaligned", 13, "#E2E8F0", align="center")

    # Socket 1 box (left)
    rect(d, lx0, 422, 500, 118, fill=FREE_BG, outline=GRAY, width=1.2)
    text(d, lx0 + 16, 430, "PCIe Root B · pci0000:80", 16, MUTED, mono=True)
    rect(d, lx0 + 16, 472, 138, 52, fill=GREEN)
    text(d, lx0 + 85, 481, "gpu-1 (80Gi)", 16, "white", align="center")
    text(d, lx0 + 85, 502, "s1a-unaligned", 13, "#ECFDF5", align="center")
    rect(d, lx0 + 168, 472, 130, 52, fill="white", outline=GRAY, width=1.2)
    text(d, lx0 + 233, 489, "gpu-3", 17, LIGHT_MUTED, align="center")
    rect(d, lx0 + 344, 472, 140, 52, fill="white", outline=GRAY, width=1.2)
    text(d, lx0 + 414, 489, "nic-1", 17, LIGHT_MUTED, align="center")

    # Orthogonal cross-root dashed mismatch connector (zero text or box overlap)
    cx = lx0 + 321
    dashed_line(d, lx0 + 112, 472, lx0 + 112, 458, color=AMBER, width=2.2, dash=6)
    dashed_line(d, lx0 + 112, 458, cx, 458, color=AMBER, width=2.2, dash=7)
    dashed_line(d, cx, 458, cx, 336, color=AMBER, width=2.2, dash=7)
    dashed_line(d, cx, 336, lx0 + 344, 336, color=AMBER, width=2.2, dash=6)
    # Clean white pill in the 42px whitespace channel between Root A and Root B
    pill_lbl = "跨 Socket 流量" if cn else "Cross-socket path"
    rect(d, cx - 76, 388, 152, 26, fill="white", outline=AMBER, width=1.0)
    text(d, cx, 392, pill_lbl, 14, AMBER, align="center")
    text(d, lx0, 554, "结果：gpu-1(pci0000:80) + nic-0(pci0000:00) 错配" if cn else "Result: gpu-1 (0000:80) + nic-0 (0000:00) mismatched", 17, AMBER)

    line(d, 594, 184, 594, 585, color=GRID, width=1.2)

    # Right panel: With matchAttribute
    rx0 = 626
    text(d, rx0, 184, "治理组：matchAttribute: pcieRoot" if cn else "Aligned: matchAttribute: pcieRoot", 23, INK, light=True)
    text(d, rx0, 217, "4/4 Pod 100% 同 Root 配对；Volcano v1.16.0 同样生效" if cn else "4/4 Pods 100% same-root; Volcano v1.16.0 verified (2.06 s)", 16, MUTED)
    line(d, rx0, 248, rx0 + 518, 248, color=GRID)

    # Socket 0 box (right)
    rect(d, rx0, 268, 518, 118, fill=GREEN_BG, outline=GREEN, width=1.2)
    text(d, rx0 + 16, 280, "PCIe Root A · pci0000:00", 16, GREEN_DARK, mono=True)
    rect(d, rx0 + 16, 314, 126, 52, fill=GREEN)
    text(d, rx0 + 79, 323, "gpu-0", 16, "white", align="center")
    text(d, rx0 + 79, 344, "pod-0", 13, "#ECFDF5", align="center")
    rect(d, rx0 + 154, 314, 126, 52, fill=GREEN)
    text(d, rx0 + 217, 323, "gpu-2", 16, "white", align="center")
    text(d, rx0 + 217, 344, "pod-2", 13, "#ECFDF5", align="center")
    line(d, rx0 + 280, 340, rx0 + 340, 340, color=GREEN_DARK, width=2.2)
    rect(d, rx0 + 342, 314, 160, 52, fill=SLATE)
    text(d, rx0 + 422, 323, "nic-0 (25G x2)", 16, "white", align="center")
    text(d, rx0 + 422, 344, "pod-0 + pod-2", 13, "#E2E8F0", align="center")

    # Socket 1 box (right)
    rect(d, rx0, 418, 518, 118, fill=GREEN_BG, outline=GREEN, width=1.2)
    text(d, rx0 + 16, 430, "PCIe Root B · pci0000:80", 16, GREEN_DARK, mono=True)
    rect(d, rx0 + 16, 464, 126, 52, fill=GREEN)
    text(d, rx0 + 79, 473, "gpu-1", 16, "white", align="center")
    text(d, rx0 + 79, 494, "pod-1", 13, "#ECFDF5", align="center")
    rect(d, rx0 + 154, 464, 126, 52, fill=GREEN)
    text(d, rx0 + 217, 473, "gpu-3", 16, "white", align="center")
    text(d, rx0 + 217, 494, "pod-3", 13, "#ECFDF5", align="center")
    line(d, rx0 + 280, 490, rx0 + 340, 490, color=GREEN_DARK, width=2.2)
    rect(d, rx0 + 342, 464, 160, 52, fill=SLATE)
    text(d, rx0 + 422, 473, "nic-1 (25G x2)", 16, "white", align="center")
    text(d, rx0 + 422, 494, "pod-1 + pod-3", 13, "#E2E8F0", align="center")

    text(d, rx0, 554, "硬约束验证：污点隔离 nic-1 后拒绝错配（Pending），解封 1.48 s 恢复" if cn else "Strict check: tainting nic-1 holds Pending; untaint heals in 1.48 s", 16, GREEN_DARK)

    foot = (
        "所有配对结果均核对自 ResourceClaim.status.allocation 与容器内 CDI 环境变量（GPU_DEVICE_* / NET_DEVICE_*）。"
        if cn
        else "All pairings verified from ResourceClaim.status.allocation and injected container CDI environment variables."
    )
    text(d, 56, 622, foot, 16, MUTED)
    return im


def fig2_consumable_capacity(cn=True):
    title = "DRA 可消耗容量切分：单卡显存准入与 Volcano 队列配额" if cn else "DRA consumable capacity: per-GPU admission and Volcano queue quota"
    sub = (
        "每个 Pod 申请 24 GiB 显存 + 30 算力 · 实测独立 ShareID、硬件上限拦截与 Volcano 队列级配额"
        if cn
        else "Each Pod requests 24 GiB memory + 30 compute / verifying distinct ShareIDs, device cap, and Volcano queue cap"
    )
    im, d = new_canvas(title, sub)

    # Legend
    legs = (
        [(635, "已分配切片（Running）", GREEN), (865, "超限被拒（Pending）", GRAY), (1055, "剩余容量", FREE_BG)]
        if cn
        else [(610, "Allocated slice (Running)", GREEN), (855, "Blocked (Pending)", GRAY), (1045, "Free capacity", FREE_BG)]
    )
    for lx, lbl, col in legs:
        rect(d, lx, 140, 15, 15, fill=col, outline=AXIS if col == FREE_BG else None, width=1)
        text(d, lx + 23, 138, lbl, 16, MUTED)

    # Left panel: Single GPU gpu-0 (0-100 GiB scale so 96 GiB attempt is clearly visible above 80 GiB cap!)
    lx0, l_left, l_right = 56, 128, 535
    text(d, lx0, 184, "实验 2A：单卡 gpu-0（总容量 80 GiB）" if cn else "Exp 2A: Single GPU gpu-0 (80 GiB cap)", 22, INK, light=True)
    text(d, lx0, 216, "纵轴刻度 0–100 GiB · 独立 ShareID 切分" if cn else "Y-axis 0-100 GiB / distinct ShareID per slice", 16, MUTED)

    top, bottom = 264, 526
    vmax_l = 100.0
    for tick in [0, 20, 40, 60, 80, 100]:
        y = bottom - (tick / vmax_l) * (bottom - top)
        line(d, l_left, y, l_right, y, color=AXIS if tick == 0 else GRID)
        text(d, l_left - 14, y - 9, f"{tick}G", 15, MUTED, align="right")

    # 80Gi hardware limit dashed line (drawn before bars, labeled in clear right margin)
    y_cap_l = bottom - (80.0 / vmax_l) * (bottom - top)
    dashed_line(d, l_left, y_cap_l, l_right, y_cap_l, color=AMBER, width=1.8)

    # Stacked bar 1: 3 running slices (72Gi)
    bx1, bw = 160, 114
    for idx in range(3):
        y1 = bottom - ((idx + 1) * 24 / vmax_l) * (bottom - top)
        y0 = bottom - (idx * 24 / vmax_l) * (bottom - top)
        rect(d, bx1, y1 + 1, bw, (y0 - y1) - 2, fill=GREEN)
        text(d, bx1 + bw / 2, (y0 + y1) / 2 - 9, f"Pod {idx}: 24Gi", 14, "white", align="center")
    text(d, bx1 + bw / 2, bottom + 14, "3 个 Running (72 GiB)" if cn else "3 Running (72 GiB)", 15, INK, align="center")

    # Stacked bar 2: Adding Pod 3 (96Gi > 80Gi)
    bx2 = 314
    y_72 = bottom - (72 / vmax_l) * (bottom - top)
    y_96 = bottom - (96 / vmax_l) * (bottom - top)
    rect(d, bx2, y_72, bw, bottom - y_72, fill=GREEN)
    text(d, bx2 + bw / 2, (bottom + y_72) / 2 - 9, "72 GiB", 16, "white", align="center")
    rect(d, bx2, y_96, bw, y_72 - y_96 - 1, fill=GRAY, outline=AMBER, width=1.2)
    text(d, bx2 + bw / 2, (y_72 + y_96) / 2 - 9, "Pod 3: +24Gi", 13, INK, align="center")
    text(d, bx2 + bw / 2, y_96 - 24, "96 GiB", 18, AMBER, align="center", light=True)
    text(d, bx2 + bw / 2, bottom + 14, "Pod 3 Pending", 15, AMBER, align="center")

    # Right-margin cap label with full clearance (bx2+bw = 428, l_right = 548)
    text(d, bx2 + bw + 12, y_cap_l - 22, "上限 80 GiB" if cn else "Cap 80 GiB", 14, AMBER, align="left")

    text(d, lx0, 568, "删掉 Pod 0 后，Pod 3 在 3.81 秒内自动拿到释放的 24 GiB 切片。" if cn else "Deleting Pod 0 lets Pod 3 claim the freed 24 GiB slice in 3.81 s.", 15, MUTED)

    line(d, 594, 184, 594, 592, color=GRID, width=1.2)

    # Right panel: Volcano v1.16.0 Queue Quota (48 GiB cap on 320 GiB node)
    rx0, r_left, r_right = 626, 704, 1144
    text(d, rx0, 184, "实验 2B：Volcano 队列配额（上限 48 GiB）" if cn else "Exp 2B: Volcano queue cap (48 GiB)", 22, INK, light=True)
    text(d, rx0, 216, "纵轴刻度 0–320 GiB · 节点 4 卡共 320 GiB" if cn else "Y-axis 0-320 GiB / 4-GPU node has 320 GiB", 16, MUTED)

    vmax_r = 320.0
    for tick in [0, 80, 160, 240, 320]:
        y = bottom - (tick / vmax_r) * (bottom - top)
        line(d, r_left, y, r_right, y, color=AXIS if tick == 0 else GRID)
        text(d, r_left - 14, y - 9, f"{tick}G", 15, MUTED, align="right")

    # 48Gi queue cap line (drawn before bars, labeled in clear right margin)
    y_qcap = bottom - (48.0 / vmax_r) * (bottom - top)
    dashed_line(d, r_left, y_qcap, r_right, y_qcap, color=AMBER, width=1.8)

    # Bar 1: Node free vs allocated (320Gi total: 48Gi used + 272Gi free!)
    rbx1, rbw = 738, 118
    y_48 = bottom - (48.0 / vmax_r) * (bottom - top)
    y_320 = top
    rect(d, rbx1, y_48, rbw, bottom - y_48, fill=GREEN)
    rect(d, rbx1, y_320, rbw, y_48 - y_320, fill=FREE_BG, outline=GRAY, width=1.1)
    text(d, rbx1 + rbw / 2, (y_320 + y_48) / 2 - 10, "节点空余 272 GiB" if cn else "272 GiB free", 14, MUTED, align="center")
    text(d, rbx1 + rbw / 2, (bottom + y_48) / 2 - 8, "48 GiB", 14, "white", align="center")
    text(d, rbx1 + rbw / 2, bottom + 14, "节点可用显存" if cn else "Node capacity", 15, INK, align="center")

    # Bar 2: Queue request (2 Running 48Gi + qpod-2 +24Gi blocked at 72Gi)
    rbx2 = 900
    y_72r = bottom - (72.0 / vmax_r) * (bottom - top)
    rect(d, rbx2, y_48, rbw, bottom - y_48, fill=GREEN)
    rect(d, rbx2, y_72r, rbw, y_48 - y_72r - 1, fill=GRAY, outline=AMBER, width=1.2)
    text(d, rbx2 + rbw / 2, y_72r - 24, "72 GiB", 18, AMBER, align="center", light=True)
    text(d, rbx2 + rbw / 2, bottom + 14, "qpod-2 Pending", 15, AMBER, align="center")

    # Right-margin queue cap label with full clearance (rbx2+rbw = 1018, r_right = 1144)
    text(d, rbx2 + rbw + 12, y_qcap - 22, "配额 48 GiB" if cn else "Cap 48 GiB", 14, AMBER, align="left")

    text(d, rx0, 568, "节点虽空余 272 GiB，仍被配额拦截；删 qpod-0 后 1.91 秒放行。" if cn else "Blocked by queue quota despite 272 GiB free; heals in 1.91 s.", 15, MUTED)

    foot = (
        "左右面板纵轴刻度不同（左 0–100 GiB、右 0–320 GiB），各面板内对比使用相同刻度。"
        if cn
        else "Y-axis scales differ between panels (left 0-100 GiB, right 0-320 GiB); bars within each panel share one scale."
    )
    text(d, 56, 622, foot, 16, MUTED)
    return im


def fig3_health_quarantine(cn=True):
    title = "KEP-4680 故障上报与单卡 DeviceTaintRule 自愈耗时" if cn else "KEP-4680 health reporting and single-GPU quarantine latency"
    sub = (
        "Kubernetes v1.37.2 · 2 副本在线服务（同节点 gpu-0 / gpu-1）· 向 gpu-1 注入模拟过温故障"
        if cn
        else "Kubernetes v1.37.2 / 2-replica serving Deployment on one worker (gpu-0, gpu-1) / fault injected on gpu-1"
    )
    im, d = new_canvas(title, sub)

    # Top half: Measured timeline horizontal bars (0 - 2.5 s)
    rows = [
        ("Unknown 失联上报至 Pod 状态" if cn else "Unknown state to Pod status", 0.52, GRAY, "driver lost contact"),
        ("DeviceTaintRule 触发驱逐" if cn else "DeviceTaintRule eviction trigger", 0.86, GREEN, "DeviceTaintManagerEviction"),
        ("过温 Unhealthy 上报至 Pod 状态" if cn else "Unhealthy fault to Pod status", 1.62, GRAY, "80C warning threshold"),
        ("替代 Pod 在健康备卡 gpu-2 就绪" if cn else "Replacement Pod Healthy on gpu-2", 1.85, GREEN, "Running + Healthy (51C)"),
    ]
    left, right = 415, 1085
    top, bottom = 165, 378
    vmax = 2.5

    for tick in [0.0, 0.5, 1.0, 1.5, 2.0, 2.5]:
        x = left + (tick / vmax) * (right - left)
        line(d, x, top - 6, x, bottom + 6, color=AXIS if tick == 0 else GRID, width=1.2 if tick == 0 else 1)
        text(d, x, bottom + 12, f"{tick:.1f}s", 15, MUTED, align="center")

    row_h = (bottom - top) / len(rows)
    bar_h = 28
    for i, (lbl, val, col, note) in enumerate(rows):
        cy = top + (i + 0.5) * row_h
        text(d, left - 18, cy - 15, lbl, 17, INK, align="right")
        text(d, left - 18, cy + 6, note, 13, MUTED, align="right")
        bw = (val / vmax) * (right - left)
        rect(d, left, cy - bar_h / 2, bw, bar_h, fill=col)
        text(d, left + bw + 12, cy - 10, f"{val:.2f} s", 20, INK, align="left", light=True)

    # Bottom half: Blast radius comparison (Single-GPU Quarantine vs Node Drain)
    line(d, 56, 424, 1144, 424, color=GRID, width=1.2)
    text(d, 56, 442, "故障爆炸半径对比：同节点 4 卡实测（gpu-1 故障，gpu-0 跑健康同机兄弟副本）" if cn else "Blast-radius comparison on the same 4-GPU node (gpu-1 faulty, gpu-0 running healthy sibling)", 19, INK)

    # Box A: DRA Single-GPU DeviceTaintRule
    rect(d, 56, 480, 530, 112, fill=GREEN_BG, outline=GREEN, width=1.2)
    text(d, 74, 494, "DRA 单卡隔离（DeviceTaintRule · 实测）" if cn else "DRA Single-GPU Quarantine (Measured)", 18, GREEN_DARK)
    slots_a = [("gpu-0", "兄弟 Pod 无感", GREEN), ("gpu-1", "已隔离", GRAY), ("gpu-2", "替代 Pod 就绪", SLATE), ("gpu-3", "健康备卡", FREE_BG)]
    slots_a_en = [("gpu-0", "0 restarts", GREEN), ("gpu-1", "Tainted", GRAY), ("gpu-2", "Healed Pod", SLATE), ("gpu-3", "Healthy spare", FREE_BG)]
    for si, (gn, st, col) in enumerate(slots_a if cn else slots_a_en):
        sx = 74 + si * 124
        rect(d, sx, 528, 114, 48, fill=col, outline=AXIS if col == FREE_BG else None, width=1)
        tc = "white" if col in (GREEN, SLATE) else INK
        text(d, sx + 57, 534, gn, 14, tc, align="center")
        text(d, sx + 57, 553, st, 12, tc, align="center")

    # Box B: Traditional Node Drain / Node Taint
    rect(d, 614, 480, 530, 112, fill="#F9FAFB", outline=GRAY, width=1.2)
    text(d, 632, 494, "传统整机驱逐（kubectl drain / 节点污点）" if cn else "Traditional Node Drain / Node Taint", 18, AMBER)
    text(d, 632, 528, "1 张卡故障需驱逐整机全部健康副本（8 卡机波及 7 张健康卡）" if cn else "1 bad GPU forces eviction of all healthy Pods on the node", 15, MUTED)
    text(d, 632, 556, "DRA 单卡隔离将故障爆炸半径从整机 8 卡收敛为精确 1 卡。" if cn else "DRA DeviceTaintRule narrows blast radius from 8 GPUs to 1 GPU.", 15, INK)

    foot = (
        "实测证明：KEP-4680 仅在 Pod 状态上报 Unhealthy（观测 10 秒不会自动驱逐），需联动 DeviceTaintRule 才能形成自愈闭环。"
        if cn
        else "Measured: KEP-4680 only reports Unhealthy in Pod status (0 auto-evictions over 10 s); pair with DeviceTaintRule to self-heal."
    )
    text(d, 56, 622, foot, 16, MUTED)
    return im


def main():
    figs = [
        ("pcie-root-alignment.png", fig1_pcie_alignment),
        ("consumable-capacity-quota.png", fig2_consumable_capacity),
        ("device-health-quarantine.png", fig3_health_quarantine),
    ]
    for fname, fn in figs:
        for cn, dest_dir in [(True, CN_DIR), (False, EN_DIR)]:
            im = fn(cn=cn).resize((W, H), Image.Resampling.LANCZOS)
            out = dest_dir / fname
            im.save(out, optimize=True)
            print("Saved", out)


if __name__ == "__main__":
    main()
