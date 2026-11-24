#!/usr/bin/env python3
"""Generate third-edition (V3) bilingual research figures for keda-volcano-tidal-gpu.

Style follows scripts/generate_dsv41_vllm032_research_assets.py:
- White background, crisp whitespace, flat solid fills, light axes
- Chinese: Hiragino Sans GB W3 (face 0); Latin/digits: Helvetica Neue Light (face 7) / Regular (face 0)
- Default muted green (#78B5A3) + neutral gray (#D4D4D8) + charcoal ink (#202020)
- 1200x675 (16:9) rendered at 2x supersampling with LANCZOS downsampling
- No gradients, no drop shadows, no decorative cards, no watermarks, no error bars
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
CN_DIR = ROOT / "docs/assets/practices/keda-volcano-tidal-gpu"
EN_DIR = ROOT / "translations/en-assets/assets/practices/keda-volcano-tidal-gpu"
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
SLATE = "#475569"
FREE_BG = "#F5F5F6"
FREE_BORDER = "#D4D4D8"
RED_MUTED = "#B45309"


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


def rect(d, x, y, w, h, fill=None, outline=None, width=1):
    d.rectangle(
        (round(x * S), round(y * S), round((x + w) * S), round((y + h) * S)),
        fill=fill,
        outline=outline,
        width=round(width * S) if outline else 0,
    )


def arrow_right(d, x1, y, x2, color=MUTED, width=1.6):
    line(d, x1, y, x2 - 6, y, color=color, width=width)
    pts = [((x2) * S, y * S), ((x2 - 9) * S, (y - 5) * S), ((x2 - 9) * S, (y + 5) * S)]
    d.polygon(pts, fill=color)


def new_canvas(title, subtitle):
    im = Image.new("RGB", (W * S, H * S), "white")
    d = ImageDraw.Draw(im)
    text(d, 56, 40, title, 34, INK, light=True)
    text(d, 56, 94, subtitle, 18, MUTED, light=True)
    return im, d


def fig1_reclaim_latency(cn=True):
    title = "不同还卡机制下的在线恢复耗时" if cn else "Online recovery latency across GPU reclaim paths"
    sub = (
        "Kubernetes v1.37.2 · Volcano v1.16.0 · KEDA v2.21.1 · 轻量模拟负载（不含模型加载与预热）"
        if cn
        else "Kubernetes v1.37.2 / Volcano v1.16.0 / KEDA v2.21.1 / lightweight workers (excluding model load)"
    )
    im, d = new_canvas(title, sub)

    # Legend
    leg_items = (
        [(770, "可控退让 / 正常路径", GREEN), (995, "僵死兜底 (SIGKILL)", GRAY)]
        if cn
        else [(720, "Graceful / controlled path", GREEN), (985, "Rogue SIGKILL cap", GRAY)]
    )
    for lx, lbl, col in leg_items:
        rect(d, lx, 142, 15, 15, fill=col)
        text(d, lx + 24, 140, lbl, 18, MUTED)

    rows = [
        (
            "DRA DeviceTaintRule (2s 宽限)" if cn else "DRA DeviceTaintRule (2s tol.)",
            5.39,
            GREEN,
            "2.79s 驱逐 → 5.39s 接管" if cn else "evicted 2.79s, running 5.39s",
        ),
        (
            "Volcano reclaim (优雅 SIGTERM, 2 卡)" if cn else "Volcano reclaim (SIGTERM, 2 GPUs)",
            5.96,
            GREEN,
            "1.97s 驱逐 → 3.56s 调度 → 5.96s" if cn else "evicted 1.97s, sched 3.56s",
        ),
        (
            "Volcano reclaim (12 卡 Gang, RestartJob)" if cn else "Volcano reclaim (12-GPU Gang)",
            7.12,
            GREEN,
            "2.48s 整组重启 → 7.12s 4 卡就绪" if cn else "restarting 2.48s, 4 GPUs 7.12s",
        ),
        (
            "KEDA 突发入队 → 4 卡就绪并产出" if cn else "KEDA burst enqueue to 4 serving",
            13.10,
            GREEN,
            "含 KEDA 轮询 + 4 卡回收 + 首产出" if cn else "incl. KEDA poll + 4-GPU reclaim",
        ),
        (
            "僵死离线容器 (忽略 SIGTERM, 15s 宽限)" if cn else "Rogue worker (ignores SIGTERM, 15s)",
            20.63,
            GRAY,
            "2.96s 驱逐 + 15s 宽限 → SIGKILL" if cn else "2.96s evict + 15s grace, SIGKILL",
        ),
    ]

    left, right = 420, 1085
    top, bottom = 195, 555
    vmax = 25.0

    # Vertical gridlines & x-axis labels
    for tick in [0, 5, 10, 15, 20, 25]:
        x = left + (tick / vmax) * (right - left)
        line(d, x, top - 10, x, bottom + 6, color=AXIS if tick == 0 else GRID, width=1.2 if tick == 0 else 1)
        text(d, x, bottom + 16, f"{tick}s", 17, MUTED, align="center")

    row_h = (bottom - top) / len(rows)
    bar_h = 34
    for i, (label, val, col, note) in enumerate(rows):
        cy = top + (i + 0.5) * row_h
        text(d, left - 20, cy - 18, label, 19, INK, align="right")
        text(d, left - 20, cy + 7, note, 15, MUTED, align="right")
        bw = (val / vmax) * (right - left)
        rect(d, left, cy - bar_h / 2, bw, bar_h, fill=col)
        text(d, left + bw + 12, cy - 12, f"{val:.2f} s", 22, INK, align="left", light=True)

    foot = (
        "横轴从 0 秒起算；生产环境端到端首 Token 恢复时间还需叠加镜像拉取、模型权重加载与引擎预热。"
        if cn
        else "X-axis starts at 0 s. Production time to first token must also add image pull, weight loading, and engine warmup."
    )
    text(d, 56, 622, foot, 16, MUTED)
    return im


def fig2_fragmentation(cn=True):
    title = "16 卡双节点：碎片化阻塞与 binpack 治理对比" if cn else "16-GPU two-node lab: fragmentation trap vs. binpack governance"
    sub = (
        "双节点各 8 张模拟 B300 · 夜间在线保留 6 卡（集群共空余 10 卡）· 提交 8 卡单机任务"
        if cn
        else "Two 8-GPU workers / 6 online GPUs kept overnight (10 free total) / submitting one 8-GPU single-node job"
    )
    im, d = new_canvas(title, sub)

    # Legend
    legs = (
        [(620, "在线推理 Pod", GREEN), (805, "8 卡单机训练 vcjob", SLATE), (1035, "空闲 GPU", FREE_BG)]
        if cn
        else [(610, "Online serving Pod", GREEN), (825, "8-GPU single-node vcjob", SLATE), (1060, "Free GPU", FREE_BG)]
    )
    for lx, lbl, col in legs:
        rect(d, lx, 144, 15, 15, fill=col, outline=FREE_BORDER if col == FREE_BG else None, width=1)
        text(d, lx + 23, 142, lbl, 17, MUTED)

    def draw_panel(x0, heading, subhead, nodes_spec, result_text, result_ok):
        text(d, x0, 198, heading, 24, INK, light=True)
        text(d, x0, 232, subhead, 17, MUTED)
        line(d, x0, 265, x0 + 510, 265, color=GRID)

        slot_w, slot_h, gap = 52, 46, 8
        for ni, (nlabel, slots, cap_note) in enumerate(nodes_spec):
            ny = 290 + ni * 118
            text(d, x0, ny, nlabel, 18, INK)
            text(d, x0 + 510, ny + 1, cap_note, 16, MUTED, align="right")
            sy = ny + 32
            for si, kind in enumerate(slots):
                sx = x0 + si * (slot_w + gap)
                if kind == "online":
                    rect(d, sx, sy, slot_w, slot_h, fill=GREEN)
                    text(d, sx + slot_w / 2, sy + 14, f"G{si}", 15, "white", align="center")
                elif kind == "train":
                    rect(d, sx, sy, slot_w, slot_h, fill=SLATE)
                    text(d, sx + slot_w / 2, sy + 14, f"G{si}", 15, "white", align="center")
                else:
                    rect(d, sx, sy, slot_w, slot_h, fill=FREE_BG, outline=FREE_BORDER, width=1.2)
                    text(d, sx + slot_w / 2, sy + 14, f"G{si}", 15, LIGHT_MUTED, align="center")

        line(d, x0, 526, x0 + 510, 526, color=GRID)
        badge_col = GREEN_DARK if result_ok else RED_MUTED
        text(d, x0, 545, result_text, 20, badge_col)

    draw_panel(
        56,
        "对照组：默认打散（Spread）" if cn else "Control: Default spread",
        "10 张空卡拆成 5 + 5，缺少整机 8 卡连续槽位" if cn else "10 free GPUs split 5 + 5; no node has 8 contiguous GPUs",
        [
            ("Worker A (8 GPU)", ["online"] * 3 + ["free"] * 5, "在线 3 / 空闲 5" if cn else "3 online / 5 free"),
            ("Worker B (8 GPU)", ["online"] * 3 + ["free"] * 5, "在线 3 / 空闲 5" if cn else "3 online / 5 free"),
        ],
        "8 卡单机任务：Pending（Insufficient nvidia.com/gpu）" if cn else "8-GPU job: Pending (Insufficient nvidia.com/gpu)",
        False,
    )

    line(d, 600, 198, 600, 580, color=GRID, width=1.2)

    draw_panel(
        634,
        "治理组：binpack + pod-deletion-cost" if cn else "Governed: binpack + pod-deletion-cost",
        "白天 8 + 2 紧致装箱，夜间优先删稀疏节点腾出整机" if cn else "Daytime 8 + 2 binpack; scale-down drains sparse node first",
        [
            ("Worker A (8 GPU)", ["online"] * 6 + ["free"] * 2, "在线 6 / 空闲 2" if cn else "6 online / 2 free"),
            ("Worker B (8 GPU)", ["train"] * 8, "离线 8 卡整机 Running" if cn else "8-GPU vcjob Running"),
        ],
        "8 卡单机任务：Running（5.32 秒落地 Worker B）" if cn else "8-GPU job: Running on Worker B in 5.32 s",
        True,
    )

    foot = (
        "两对照组在线副本总数均为 6 卡、集群总空闲均为 10 卡；仅靠调度装箱与缩容排序消除跨机碎片。"
        if cn
        else "Both runs keep 6 online GPUs and 10 free GPUs cluster-wide; binpacking plus deletion-cost ordering clears a full 8-GPU node."
    )
    text(d, 56, 622, foot, 16, MUTED)
    return im


def fig3_architecture_matrix(cn=True):
    title = "声明式潮汐调度架构与两类设备实测边界" if cn else "Declarative tidal GPU architecture and measured boundaries"
    sub = (
        "基于实测验证的职责分工：nvidia.com/gpu 走 Volcano reclaim，DRA 走 K8s v1.37 DeviceTaintRule"
        if cn
        else "Verified control-plane split: Volcano reclaim for nvidia.com/gpu, K8s v1.37 DeviceTaintRule for DRA"
    )
    im, d = new_canvas(title, sub)

    def box(x, y, w, h, head, body, fill="#FFFFFF", border=AXIS, head_col=INK):
        rect(d, x, y, w, h, fill=fill, outline=border, width=1.3)
        text(d, x + 16, y + 14, head, 18, head_col)
        for idx, b in enumerate(body):
            text(d, x + 16, y + 44 + idx * 24, b, 15, MUTED)

    # Row 1: nvidia.com/gpu declarative track
    text(d, 56, 148, "路径 A · nvidia.com/gpu（Device Plugin）— Volcano v1.16.0 实测全自动回收通过" if cn else "Track A · nvidia.com/gpu (Device Plugin) — Automated Volcano v1.16.0 reclaim verified", 19, GREEN_DARK)
    y1, bh1 = 184, 120
    box(56, y1, 235, bh1, "1. KEDA 触发扩容" if cn else "1. KEDA Scale-Up",
        ["Cron 窗口 + Redis 队列" if cn else "Cron window + Redis list", "elastic 0 → 4 副本" if cn else "elastic 0 to 4 replicas", "配置 group-min-member=4" if cn else "group-min-member=4"],
        fill="#F4FAF8", border=GREEN)
    arrow_right(d, 293, y1 + bh1 / 2, 333, GREEN_DARK)

    box(335, y1, 275, bh1, "2. Volcano capacity+reclaim" if cn else "2. Volcano capacity+reclaim",
        ["tide-online (不可回收, 8 卡)" if cn else "tide-online (deserved 8)", "tide-offline (可回收, 借至 12 卡)" if cn else "tide-offline (borrowed 12)", "关闭 overcommit 防拦截" if cn else "disable overcommit plugin"],
        fill="#F4FAF8", border=GREEN)
    arrow_right(d, 612, y1 + bh1 / 2, 652, GREEN_DARK)

    box(654, y1, 244, bh1, "3. 精准驱逐 4 个离线 Pod" if cn else "3. Evict 4 Offline Pods",
        ["SIGTERM 落盘当前项后退出" if cn else "SIGTERM checkpoint & exit", "其余 8 卡离线任务无感续跑" if cn else "8 other pods keep running", "vcjob 设 maxRetry=50" if cn else "vcjob maxRetry=50"],
        fill="#FFFFFF", border=AXIS)
    arrow_right(d, 900, y1 + bh1 / 2, 938, GREEN_DARK)

    box(940, y1, 204, bh1, "4. 实测闭环结果" if cn else "4. Measured Result",
        ["13.10s 全 4 卡产出" if cn else "13.10s all 4 serving", "400/400 在线零丢单" if cn else "400/400 online served", "720/720 离线零重复" if cn else "720/720 offline exact-1"],
        fill="#F4FAF8", border=GREEN, head_col=GREEN_DARK)

    # Row 2: DRA track
    text(d, 56, 332, "路径 B · DRA ResourceClaim — Volcano v1.16.0 实测不自动回收，改由 K8s v1.37 DeviceTaintRule 补齐" if cn else "Track B · DRA ResourceClaim — Volcano v1.16.0 does not reclaim; K8s v1.37 DeviceTaintRule bridges the gap", 19, SLATE)
    y2, bh2 = 368, 120
    box(56, y2, 310, bh2, "Volcano v1.16.0 实测边界" if cn else "Volcano v1.16.0 Limit",
        ["capacity 支持 deviceclass 配额准入" if cn else "capacity enforces deviceclass quota", "但 reclaim 阶段满卡节点被 DRA 过滤" if cn else "but reclaim filters out full DRA nodes", "实测 35s 内未触发驱逐" if cn else "0 evictions observed over 35s"],
        fill="#F9FAFB", border=GRAY, head_col=RED_MUTED)
    arrow_right(d, 368, y2 + bh2 / 2, 412, SLATE)

    box(414, y2, 335, bh2, "K8s v1.37 DeviceTaintRule" if cn else "K8s v1.37 DeviceTaintRule",
        ["按 driver / pool / device 精准打污点" if cn else "Target exact driver / pool / device", "NoExecute + 离线 tolerationSeconds=2" if cn else "NoExecute + offline tolerationSeconds=2", "在线 Claim 携带匹配 Toleration" if cn else "Online Claim carries matching toleration"],
        fill="#FFFFFF", border=SLATE, head_col=SLATE)
    arrow_right(d, 751, y2 + bh2 / 2, 795, SLATE)

    box(797, y2, 347, bh2, "原生设备级还卡实测" if cn else "Native DRA Recall Result",
        ["2.79s 触发 DeviceTaintManagerEviction" if cn else "2.79s DeviceTaintManagerEviction", "4.53s 离线 Pod 释放并解绑 Claim" if cn else "4.53s offline Pod & Claim released", "5.39s 在线 Pod 获配 gpu-1 并 Running" if cn else "5.39s online Pod Running on gpu-1"],
        fill="#F4FAF8", border=GREEN, head_col=GREEN_DARK)

    # Row 3: Always-on Guardrail
    y3, bh3 = 516, 82
    rect(d, 56, y3, 1088, bh3, fill="#F8FAFC", outline=AXIS, width=1.2)
    text(d, 76, y3 + 14, "硬隔离保底基线（不可由 KEDA 缩零）" if cn else "Hard Baseline Guardrail (Never Managed by KEDA Scale-to-Zero)", 18, INK)
    text(
        d,
        76,
        y3 + 44,
        "base Deployment 独立于 KEDA，配 Volcano guarantee=4（reclaimable=false）；实测 KEDA 缩零态下指标源宕机不会触发 fallback 唤醒。"
        if cn
        else "Keep base Deployment outside KEDA with Volcano guarantee=4 (reclaimable=false); measured KEDA fallback never wakes from 0 replicas on outage.",
        15,
        MUTED,
    )

    foot = (
        "所有行为均在本地 3 节点集群（16×模拟 B300 + 4×DRA 示例设备）实测核验。"
        if cn
        else "Every path and boundary was empirically verified on a 3-node lab (16 simulated B300 GPUs + 4 DRA example devices)."
    )
    text(d, 56, 624, foot, 16, MUTED)
    return im


def main():
    figs = [
        ("reclaim-latency-comparison.png", fig1_reclaim_latency),
        ("fragmentation-binpack-comparison.png", fig2_fragmentation),
        ("reclaim-mechanism-matrix.png", fig3_architecture_matrix),
    ]
    for fname, fn in figs:
        for cn, dest_dir in [(True, CN_DIR), (False, EN_DIR)]:
            im = fn(cn=cn).resize((W, H), Image.Resampling.LANCZOS)
            out = dest_dir / fname
            im.save(out, optimize=True)
            print("Saved", out)


if __name__ == "__main__":
    main()
