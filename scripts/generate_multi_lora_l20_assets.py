#!/usr/bin/env python3
"""Generate third-edition (V3) bilingual figures for multi-lora-l20-aibrix-vs-llmd.

Follows V3 style (scripts/generate_dsv41_vllm032_research_assets.py):
- White background, clean whitespace, flat solid fills, light axes
- Chinese: Hiragino Sans GB W3 (face 0); Latin/digits: Helvetica Neue Light (face 7) / Regular (face 0)
- Default muted green (#78B5A3), neutral gray (#D4D4D8), charcoal slate (#475569), amber (#B45309)
- 1200x675 (16:9) rendered at 2x supersampling with LANCZOS downsampling
- ASCII-safe English labels (no Unicode arrows in Helvetica Neue)
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
CN_DIR = ROOT / "docs/assets/practices/multi-lora-l20-aibrix-vs-llmd"
EN_DIR = ROOT / "translations/en-assets/assets/practices/multi-lora-l20-aibrix-vs-llmd"
CN_DIR.mkdir(parents=True, exist_ok=True)
EN_DIR.mkdir(parents=True, exist_ok=True)

W, H = 1200, 675
S = 2

INK = "#202020"
MUTED = "#6B7280"
GRID = "#EAEAEA"
AXIS = "#C8C8C8"
GRAY = "#D4D4D8"
GREEN = "#78B5A3"
GREEN_DARK = "#2F6F5E"
GREEN_BG = "#F4FAF8"
SLATE = "#475569"
FREE_BG = "#F5F5F6"
AMBER = "#B45309"


def face(value, size, light=False):
    if any("\u3400" <= ch <= "\u9fff" for ch in value):
        path = "/System/Library/Fonts/Hiragino Sans GB.ttc"
        index = 0  # W3
    else:
        path = "/System/Library/Fonts/HelveticaNeue.ttc"
        index = 7 if light else 0
    return ImageFont.truetype(path, round(size * S), index=index)


def text(d, x, y, value, size=20, color=INK, align="left", light=False):
    f = face(value, size, light)
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


def new_canvas(title, subtitle):
    im = Image.new("RGB", (W * S, H * S), "white")
    d = ImageDraw.Draw(im)
    text(d, 56, 38, title, 32, INK, light=True)
    text(d, 56, 88, subtitle, 17, MUTED, light=True)
    return im, d


def arrow(d, x1, y1, x2, y2, color=SLATE, width=1.8, head=7):
    import math
    line(d, x1, y1, x2, y2, color=color, width=width)
    ang = math.atan2(y2 - y1, x2 - x1)
    p1 = (round((x2 - head * math.cos(ang - 0.45)) * S), round((y2 - head * math.sin(ang - 0.45)) * S))
    p2 = (round((x2 - head * math.cos(ang + 0.45)) * S), round((y2 - head * math.sin(ang + 0.45)) * S))
    d.polygon([(round(x2 * S), round(y2 * S)), p1, p2], fill=color)


def dashed_line(d, x1, y1, x2, y2, color=MUTED, width=1.6, dash=6):
    import math
    dist = math.hypot(x2 - x1, y2 - y1)
    steps = max(1, int(dist / (dash * 1.6)))
    for i in range(steps):
        t0 = i / steps
        t1 = min(1.0, (i + 0.55) / steps)
        line(d, x1 + (x2 - x1) * t0, y1 + (y2 - y1) * t0, x1 + (x2 - x1) * t1, y1 + (y2 - y1) * t1, color=color, width=width)


def fig0_architecture(cn=True):
    title = "AIBrix v0.8.0 与 CNCF llm-d EPP v1.0.0 多 LoRA 路由原理" if cn else "How AIBrix v0.8.0 and CNCF llm-d EPP v1.0.0 route multi-LoRA traffic"
    sub = (
        "核心差异：AIBrix 由控制面提前把 LoRA 固定分配到卡再直发；llm-d EPP 通过每 100ms 抓取引擎指标动态打分选卡"
        if cn
        else "Core split: AIBrix pins LoRAs to pods ahead of time via CRDs; llm-d EPP scrapes live vLLM metrics every 100 ms to score pods"
    )
    im, d = new_canvas(title, sub)

    # ===== LEFT PANEL: AIBrix v0.8.0 =====
    lx0 = 56
    text(d, lx0, 142, "路线 A：AIBrix v0.8.0（提前排班分桌 · 硬绑定）" if cn else "Path A: AIBrix v0.8.0 (Pre-assigned pinning)", 21, INK, light=True)
    text(d, lx0, 172, "用 ModelAdapter CRD 预先把 20 个 LoRA 均分到两张卡，网关照表直发" if cn else "ModelAdapter CRDs place 10 LoRAs per GPU; gateway routes by map", 14, MUTED)
    line(d, lx0, 198, lx0 + 510, 198, color=GRID)

    # Step 1: Control plane box (top)
    rect(d, lx0, 214, 510, 74, fill=GREEN_BG, outline=GREEN, width=1.2)
    text(d, lx0 + 16, 224, "1. 控制面：ModelAdapter Controller (replicas: 1)" if cn else "1. Control Plane: ModelAdapter Controller (replicas: 1)", 15, GREEN_DARK)
    text(d, lx0 + 16, 248, "按最空闲原则自动放 10 个到卡 A、10 个到卡 B，调 vLLM 加载并写路由表" if cn else "Places 10 LoRAs on Pod A and 10 on Pod B, loads via vLLM API, writes route map", 13, MUTED)

    # Step 2: Data plane Gateway + Redis
    rect(d, lx0, 314, 318, 86, fill=FREE_BG, outline=SLATE, width=1.2)
    text(d, lx0 + 14, 324, "2. 网关：Envoy + AIBrix Plugin" if cn else "2. Gateway: Envoy + AIBrix Plugin", 15, INK)
    text(d, lx0 + 14, 348, "读请求体 model: lora-01 → 查归属表" if cn else "Reads model: lora-01 -> lookup table", 13, MUTED)
    text(d, lx0 + 14, 370, "固定直发对应卡（100% 亲和命中）" if cn else "Pins directly to owner pod (100% hit)", 13, GREEN_DARK)

    rect(d, lx0 + 344, 314, 166, 86, fill="#FFFBEB", outline=AMBER, width=1.1)
    text(d, lx0 + 427, 326, "Redis 租户限流" if cn else "Redis Quota", 14, AMBER, align="center")
    text(d, lx0 + 427, 350, "按 user 查 RPM/TPM" if cn else "Per-user RPM/TPM", 12, MUTED, align="center")
    text(d, lx0 + 427, 370, "超额即刻 429 拒单" if cn else "Instant HTTP 429", 12, AMBER, align="center")
    arrow(d, lx0 + 318, 357, lx0 + 344, 357, color=AMBER, width=1.5)

    # Arrow from Controller down to Gateway
    arrow(d, lx0 + 159, 288, lx0 + 159, 314, color=GREEN_DARK, width=1.6)

    # Step 3: Two L20 Pods (bottom left)
    rect(d, lx0, 444, 242, 86, fill=GREEN, outline=GREEN_DARK, width=1.0)
    text(d, lx0 + 121, 456, "L20 Pod A（10 槽位）" if cn else "L20 Pod A (10 slots)", 15, "white", align="center")
    text(d, lx0 + 121, 480, "只装 lora-01 ~ lora-10" if cn else "Loads only lora-01..10", 13, "#ECFDF5", align="center")
    text(d, lx0 + 121, 502, "无换入换出抖动" if cn else "Zero slot eviction", 12, "#ECFDF5", align="center")

    rect(d, lx0 + 268, 444, 242, 86, fill=SLATE, outline=SLATE, width=1.0)
    text(d, lx0 + 389, 456, "L20 Pod B（10 槽位）" if cn else "L20 Pod B (10 slots)", 15, "white", align="center")
    text(d, lx0 + 389, 480, "只装 lora-11 ~ lora-20" if cn else "Loads only lora-11..20", 13, "#E2E8F0", align="center")
    text(d, lx0 + 389, 502, "热点需移除 replicas:1 扩容" if cn else "Hotspot needs all-pod scale", 12, "#E2E8F0", align="center")

    arrow(d, lx0 + 121, 400, lx0 + 121, 444, color=GREEN_DARK, width=1.8)
    arrow(d, lx0 + 260, 400, lx0 + 345, 444, color=SLATE, width=1.6)
    text(d, lx0 + 114, 412, "lora-01..10", 12, GREEN_DARK, align="right")
    text(d, lx0 + 318, 412, "lora-11..20", 12, SLATE, align="left")

    text(d, lx0, 552, "特点：稳态 P99 最稳（零错配），但单卡爆单时需放开副本数。" if cn else "Trait: lowest steady P99 (0 miss); scale hot adapters to all pods.", 14, GREEN_DARK)

    # Center divider
    line(d, 594, 142, 594, 586, color=GRID, width=1.2)

    # ===== RIGHT PANEL: CNCF llm-d EPP v1.0.0 =====
    rx0 = 626
    text(d, rx0, 142, "路线 B：CNCF llm-d EPP v1.0.0（看表叫号 · 指标打分）" if cn else "Path B: CNCF llm-d EPP v1.0.0 (Live-metrics scoring)", 21, INK, light=True)
    text(d, rx0, 172, "不预先绑定模型归属，靠每 100ms 抓取引擎指标动态排队并打分选卡" if cn else "No static pinning; scrapes live vLLM metrics every 100 ms to score", 14, MUTED)
    line(d, rx0, 198, rx0 + 518, 198, color=GRID)

    # Step 1: Envoy Proxy + EPP ext_proc side by side
    rect(d, rx0, 214, 176, 186, fill=FREE_BG, outline=SLATE, width=1.2)
    text(d, rx0 + 88, 228, "1. Envoy Proxy" if cn else "1. Envoy Proxy", 15, INK, align="center")
    text(d, rx0 + 88, 254, "接收 OpenAI 请求" if cn else "Receives API call", 12, MUTED, align="center")
    text(d, rx0 + 88, 276, "通过 ext_proc" if cn else "Calls ext_proc", 12, MUTED, align="center")
    text(d, rx0 + 88, 296, "向 EPP 询问目标卡" if cn else "asks EPP for pod", 12, MUTED, align="center")
    line(d, rx0 + 18, 324, rx0 + 158, 324, color=GRAY)
    text(d, rx0 + 88, 336, "按返回头直连目标" if cn else "Forwards via header", 12, GREEN_DARK, align="center")
    text(d, rx0 + 88, 356, "ORIGINAL_DST", 12, SLATE, align="center")
    text(d, rx0 + 88, 374, "x-gateway-dest...", 11, MUTED, align="center")

    # EPP Brain box
    ex0 = rx0 + 206
    rect(d, ex0, 214, 312, 186, fill=GREEN_BG, outline=GREEN, width=1.3)
    text(d, ex0 + 14, 224, "2. EPP v1.0.0 调度大脑" if cn else "2. EPP v1.0.0 Picker Brain", 15, GREEN_DARK)

    rect(d, ex0 + 12, 250, 288, 42, fill="white", outline=GREEN, width=1.0)
    text(d, ex0 + 22, 256, "① 优先级流控 (InferenceObjective)" if cn else "1. Priority Queue (InferenceObjective)", 13, INK)
    text(d, ex0 + 22, 274, "高优 +10 插队，低优 -10 趁闲跑（不丢单）" if cn else "Critical +10 jumps ahead; -10 uses idle cycles", 11, MUTED)

    rect(d, ex0 + 12, 300, 288, 42, fill="white", outline=GREEN, width=1.0)
    text(d, ex0 + 22, 306, "② 多维打分 (Filter -> Score -> Pick)" if cn else "2. Scorer Pipeline (Filter -> Score -> Pick)", 13, INK)
    text(d, ex0 + 22, 324, "LoRA 亲和 + 等待队列 + KV Cache 余量" if cn else "LoRA affinity + queue depth + KV headroom", 11, MUTED)

    rect(d, ex0 + 12, 350, 288, 40, fill="white", outline=GRAY, width=1.0)
    text(d, ex0 + 22, 356, "③ 指标缓存 (每 100ms 刷新)" if cn else "3. Metrics Cache (100 ms refresh)", 13, SLATE)
    text(d, ex0 + 22, 373, "跟踪各 Pod 活跃 LoRA / 队列 / KV 占比" if cn else "Tracks active LoRAs, queue, KV per pod", 11, MUTED)

    # Bidirectional arrows between Envoy and EPP
    arrow(d, rx0 + 176, 272, ex0, 272, color=SLATE, width=1.6)
    arrow(d, ex0, 344, rx0 + 176, 344, color=GREEN_DARK, width=1.6)

    # Step 3: Two L20 Pods (bottom right)
    rect(d, rx0, 444, 242, 86, fill=GREEN, outline=GREEN_DARK, width=1.0)
    text(d, rx0 + 121, 456, "L20 Pod A（10 热槽）" if cn else "L20 Pod A (10 hot slots)", 15, "white", align="center")
    text(d, rx0 + 121, 480, "CPU 缓存全部 20 LoRA" if cn else "CPU caches all 20 LoRAs", 13, "#ECFDF5", align="center")
    text(d, rx0 + 121, 502, "暴露 /metrics 活跃列表" if cn else "Exposes /metrics active list", 12, "#ECFDF5", align="center")

    rect(d, rx0 + 276, 444, 242, 86, fill=SLATE, outline=SLATE, width=1.0)
    text(d, rx0 + 397, 456, "L20 Pod B（10 热槽）" if cn else "L20 Pod B (10 hot slots)", 15, "white", align="center")
    text(d, rx0 + 397, 480, "CPU 缓存全部 20 LoRA" if cn else "CPU caches all 20 LoRAs", 13, "#E2E8F0", align="center")
    text(d, rx0 + 397, 502, "暴露 /metrics 活跃列表" if cn else "Exposes /metrics active list", 12, "#E2E8F0", align="center")

    # Forward arrows from Envoy to Pods
    arrow(d, rx0 + 76, 400, rx0 + 76, 444, color=GREEN_DARK, width=1.8)
    arrow(d, rx0 + 124, 400, rx0 + 318, 444, color=SLATE, width=1.5)

    # Metrics scrape dashed feedback arrow from Pods up to EPP Metrics Cache
    dashed_line(d, rx0 + 444, 444, rx0 + 444, 400, color=AMBER, width=1.6)
    arrow(d, rx0 + 444, 408, rx0 + 444, 400, color=AMBER, width=1.6)
    text(d, rx0 + 454, 412, "100ms\n/metrics" if False else "100ms scrape", 12, AMBER, align="left")

    text(d, rx0, 552, "特点：无需人工分片，天然保核心且不浪费算力；注意选对负载指标。" if cn else "Trait: zero manual sharding, work-conserving; pick right load scorer.", 14, GREEN_DARK)

    foot = (
        "两套方案在本次实测中指向完全相同的 2 台 L20 vLLM 后端，可零侵入并行部署在同一个 Kubernetes 集群中。"
        if cn
        else "Both paths target the exact same two L20 vLLM pods and can run side-by-side in one Kubernetes cluster with zero interference."
    )
    text(d, 56, 622, foot, 15, MUTED)
    return im


def fig1_single_gpu_sweep(cn=True):
    title = "单张 L20 扛 20 个 LoRA：--max-loras 槽位扫点实测" if cn else "Single L20 serving 20 LoRAs: --max-loras slot sweep"
    sub = (
        "Qwen3-8B BF16（r=16, 单适配器 87.4 MB）· 16 并发 100 请求全 20-LoRA 轮询 · 全部 100/100 完整流成功"
        if cn
        else "Qwen3-8B BF16 (r=16, 87.4 MB per adapter) / C=16, 100 requests across 20 LoRAs / 100/100 complete streams"
    )
    im, d = new_canvas(title, sub)

    # Left panel: TTFT P50 & P99 (ms, 0-13000)
    lx0, l_left, l_right = 56, 128, 558
    top, bottom = 248, 520
    text(d, lx0, 152, "首 Token 延迟（TTFT，越低越好）" if cn else "Time to first token (TTFT, lower is better)", 21, INK, light=True)
    text(d, lx0, 182, "纵轴 0 - 13,000 ms · 槽位不足导致严重排队换入" if cn else "Y-axis 0-13,000 ms / slot shortage triggers severe queuing", 15, MUTED)
    # Legend left
    rect(d, 376, 212, 14, 14, fill=GREEN)
    text(d, 396, 210, "P50", 15, MUTED)
    rect(d, 456, 212, 14, 14, fill=SLATE)
    text(d, 476, 210, "P99", 15, MUTED)

    vmax_l = 13000.0
    for tick in [0, 3000, 6000, 9000, 12000]:
        y = bottom - (tick / vmax_l) * (bottom - top)
        line(d, l_left, y, l_right, y, color=AXIS if tick == 0 else GRID)
        lbl = f"{tick//1000}s" if tick else "0"
        text(d, l_left - 12, y - 9, lbl, 14, MUTED, align="right")

    data_l = [
        ("max=4", 10913, 11782),
        ("max=8", 4117, 5235),
        ("max=20", 774, 1956),
    ]
    bw = 48
    gap = 12
    centers = [205, 345, 485]
    for cx, (lbl, p50, p99) in zip(centers, data_l):
        x1 = cx - bw - gap / 2
        x2 = cx + gap / 2
        h1 = (p50 / vmax_l) * (bottom - top)
        h2 = (p99 / vmax_l) * (bottom - top)
        rect(d, x1, bottom - h1, bw, h1, fill=GREEN)
        rect(d, x2, bottom - h2, bw, h2, fill=SLATE)
        t1 = f"{p50/1000:.1f}s" if p50 >= 1000 else f"{p50}ms"
        t2 = f"{p99/1000:.1f}s" if p99 >= 1000 else f"{p99}ms"
        text(d, x1 + bw / 2, bottom - h1 - 21, t1, 14, INK, align="center", light=True)
        text(d, x2 + bw / 2, bottom - h2 - 21, t2, 14, SLATE, align="center", light=True)
        text(d, cx, bottom + 14, lbl, 16, INK, align="center")

    text(d, lx0, 574, "max-loras 从 4 提到 20：TTFT P50 下降 92.9%（10.91s 到 0.77s）。" if cn else "Raising max-loras 4 to 20 cuts TTFT P50 by 92.9% (10.91s to 0.77s).", 15, GREEN_DARK)

    line(d, 594, 152, 594, 596, color=GRID, width=1.2)

    # Right panel: Output Throughput (tok/s, 0-220) + KV Cache callout
    rx0, r_left, r_right = 626, 694, 1140
    text(d, rx0, 152, "输出吞吐（tok/s）与显存代价" if cn else "Output throughput (tok/s) and KV cost", 21, INK, light=True)
    text(d, rx0, 182, "纵轴 0 - 220 tok/s · 下方标注对应可用 KV Cache" if cn else "Y-axis 0-220 tok/s / available KV cache noted below bars", 15, MUTED)

    vmax_r = 220.0
    for tick in [0, 50, 100, 150, 200]:
        y = bottom - (tick / vmax_r) * (bottom - top)
        line(d, r_left, y, r_right, y, color=AXIS if tick == 0 else GRID)
        text(d, r_left - 12, y - 9, str(tick), 14, MUTED, align="right")

    data_r = [
        ("max=4", 71.2, "KV 24.03G", GRAY),
        ("max=8", 126.9, "KV 23.66G", GRAY),
        ("max=20", 195.7, "KV 22.58G", GREEN),
    ]
    rbw = 78
    rcenters = [775, 920, 1065]
    for cx, (lbl, tps, kv, col) in zip(rcenters, data_r):
        h = (tps / vmax_r) * (bottom - top)
        rect(d, cx - rbw / 2, bottom - h, rbw, h, fill=col)
        text(d, cx, bottom - h - 24, f"{tps:.1f}", 19, INK, align="center", light=True)
        text(d, cx, bottom + 10, lbl, 16, INK, align="center")
        text(d, cx, bottom + 31, kv, 13, MUTED, align="center")

    text(d, rx0, 574, "仅多占 1.44 GiB 显存（KV 仅少 6.0%），吞吐提升 2.75 倍。" if cn else "Only 1.44 GiB extra VRAM (-6.0% KV cache) yields 2.75x throughput.", 15, GREEN_DARK)

    foot = (
        "注：左右面板纵轴量纲不同（左 ms、右 tok/s）；同时观察到 TPOT P50 由 53.0 ms 温和升至 62.3 ms（多 LoRA SGMV 计算开销）。"
        if cn
        else "Note: Y-axes differ by metric (ms left, tok/s right); TPOT P50 rose modestly from 53.0 ms to 62.3 ms due to multi-LoRA SGMV batching."
    )
    text(d, 56, 622, foot, 15, MUTED)
    return im


def fig2_uniform_routing(cn=True):
    title = "双卡 L20 均匀 20-LoRA 路由对照：RR vs llm-d EPP vs AIBrix" if cn else "2xL20 uniform 20-LoRA routing: RR vs. llm-d EPP vs. AIBrix"
    sub = (
        "2×1 L20（每卡 --max-loras=10，合计 20 槽位）· 24 并发 160 请求同随机种子 · 测 TTFT 尾延迟、吞吐与主节点亲和率"
        if cn
        else "2x1 L20 (--max-loras=10 per GPU = 20 total slots) / C=24, 160 requests, fixed seed / TTFT, throughput, and locality"
    )
    im, d = new_canvas(title, sub)

    # Left panel: TTFT P50 / P95 / P99 (0-6000 ms)
    lx0, l_left, l_right = 56, 128, 578
    top, bottom = 248, 520
    text(d, lx0, 152, "首 Token 延迟（TTFT P50 / P95 / P99）" if cn else "Time to first token (TTFT P50 / P95 / P99)", 21, INK, light=True)
    text(d, lx0, 182, "纵轴 0 - 6,000 ms · 越低越好" if cn else "Y-axis 0-6,000 ms / lower is better", 15, MUTED)
    for lx, lbl, col in [(336, "P50", GRAY), (412, "P95", GREEN), (488, "P99", SLATE)]:
        rect(d, lx, 212, 14, 14, fill=col)
        text(d, lx + 20, 210, lbl, 14, MUTED)

    vmax_l = 6000.0
    for tick in [0, 1500, 3000, 4500, 6000]:
        y = bottom - (tick / vmax_l) * (bottom - top)
        line(d, l_left, y, l_right, y, color=AXIS if tick == 0 else GRID)
        text(d, l_left - 12, y - 9, f"{tick/1000:.1f}s" if tick else "0", 14, MUTED, align="right")

    groups = [
        ("Round-Robin", 473, 4936, 5197),
        ("llm-d EPP v1.0", 267, 4154, 4177),
        ("AIBrix v0.8 (r=1)", 408, 986, 1117),
    ]
    bw = 34
    gap = 6
    centers = [206, 356, 506]
    for cx, (lbl, p50, p95, p99) in zip(centers, groups):
        xs = [cx - bw * 1.5 - gap, cx - bw / 2, cx + bw / 2 + gap]
        for x, val, col in zip(xs, [p50, p95, p99], [GRAY, GREEN, SLATE]):
            h = (val / vmax_l) * (bottom - top)
            rect(d, x, bottom - h, bw, h, fill=col)
            txt = f"{val/1000:.1f}s" if val >= 1000 else f"{val}"
            text(d, x + bw / 2, bottom - h - 19, txt, 12, INK if col != SLATE else SLATE, align="center")
        text(d, cx, bottom + 14, lbl, 14, INK, align="center")

    text(d, lx0, 562, "AIBrix 10/10 硬绑定消除换入抖动，TTFT P99 较 RR 降 78.5%。" if cn else "AIBrix 10/10 pinning eliminates swaps, cutting TTFT P99 by 78.5%.", 15, GREEN_DARK)

    line(d, 608, 152, 608, 588, color=GRID, width=1.2)

    # Right panel: Throughput (top half) & Locality Hit Rate (bottom half) as clean horizontal bars!
    rx0 = 640
    text(d, rx0, 152, "集群输出吞吐（tok/s）与主节点亲和率" if cn else "Cluster output throughput (tok/s) and locality", 21, INK, light=True)
    text(d, rx0, 182, "对比三套方案的吞吐与单模型主节点命中比例" if cn else "Throughput and dominant-pod per-LoRA locality across routers", 15, MUTED)

    # Sub-chart A: Throughput (0-400 tok/s)
    text(d, rx0, 222, "输出吞吐（tok/s，越高越好）" if cn else "Output throughput (tok/s, higher is better)", 16, INK)
    rows_t = [
        ("Round-Robin", 272.9, GRAY),
        ("llm-d EPP v1.0", 351.8, GREEN),
        ("AIBrix v0.8 (r=1)", 357.8, GREEN_DARK),
    ]
    bx0, bx1 = 790, 1082
    for i, (lbl, val, col) in enumerate(rows_t):
        y = 258 + i * 38
        text(d, bx0 - 12, y + 3, lbl, 14, MUTED, align="right")
        w = (val / 400.0) * (bx1 - bx0)
        rect(d, bx0, y, w, 24, fill=col)
        text(d, bx0 + w + 10, y + 2, f"{val:.1f}", 16, INK, light=True)

    line(d, rx0, 386, 1144, 386, color=GRID)

    # Sub-chart B: Dominant-pod LoRA locality (0-100%)
    text(d, rx0, 404, "单 LoRA 主节点亲和命中率（%）" if cn else "Per-LoRA dominant-pod affinity rate (%)", 16, INK)
    rows_a = [
        ("Round-Robin", 63.5, GRAY),
        ("llm-d EPP v1.0", 82.5, GREEN),
        ("AIBrix v0.8 (r=1)", 100.0, GREEN_DARK),
    ]
    for i, (lbl, val, col) in enumerate(rows_a):
        y = 440 + i * 38
        text(d, bx0 - 12, y + 3, lbl, 14, MUTED, align="right")
        w = (val / 100.0) * (bx1 - bx0)
        rect(d, bx0, y, w, 24, fill=col)
        text(d, bx0 + w + 10, y + 2, f"{val:.1f}%", 16, INK, light=True)

    text(d, rx0, 562, "llm-d EPP 无需预绑定即可提速 28.9%，但冷启动仍有 17.5% 跨卡回退。" if cn else "llm-d EPP boosts throughput 28.9% dynamically; 17.5% miss stays.", 15, MUTED)

    foot = (
        "注：Round-Robin 出现 1/160 次 503（159/160 成功）；llm-d EPP 与 AIBrix 均为 160/160 完整成功。E2E P99 分别为 9.86s / 7.43s / 4.53s。"
        if cn
        else "Note: Round-Robin had 1/160 HTTP 503 (159/160 complete); llm-d EPP and AIBrix achieved 160/160. E2E P99: 9.86s / 7.43s / 4.53s."
    )
    text(d, 56, 622, foot, 15, MUTED)
    return im


def fig3_hotspot_comparison(cn=True):
    title = "70% 热点倾斜实战：单卡硬绑定瓶颈 vs 热点双卡扩展" if cn else "70% hotspot skew: single-GPU pin bottleneck vs. multi-replica"
    sub = (
        "2×1 L20（--max-loras=10）· 70% 流量集中打向 lora-01（87/120 条），24 并发 · 全部 120/120 完整成功"
        if cn
        else "2x1 L20 (--max-loras=10) / 70% traffic targeting lora-01 (87/120 requests), C=24 / 120/120 complete streams"
    )
    im, d = new_canvas(title, sub)

    rows = [
        ("AIBrix (r=1 单卡硬绑)" if cn else "AIBrix (replicas=1)", 331.7, 1354, "lora-01: 87 / 0", GRAY),
        ("llm-d EPP (w=4:2)" if cn else "llm-d EPP (w=4:2)", 336.4, 1338, "lora-01: 87 / 0", GRAY),
        ("Round-Robin 轮询" if cn else "Round-Robin", 380.8, 795, "lora-01: 46 / 41", SLATE),
        ("AIBrix (热点全副本)" if cn else "AIBrix (hot=all pods)", 450.6, 186, "lora-01: 46 / 41", GREEN),
    ]

    # Left panel: Throughput (0-500 tok/s)
    lx0, l_left, l_right = 56, 250, 562
    top, bottom = 216, 486
    text(d, lx0, 152, "输出吞吐（tok/s，越高越好）" if cn else "Output throughput (tok/s, higher is better)", 21, INK, light=True)
    text(d, lx0, 182, "横轴 0 - 500 tok/s · 下方标注 lora-01 双卡分布" if cn else "X-axis 0-500 tok/s / lora-01 Pod A/B split shown", 15, MUTED)

    vmax_t = 500.0
    for tick in [0, 100, 200, 300, 400, 500]:
        x = l_left + (tick / vmax_t) * (l_right - l_left)
        line(d, x, top - 6, x, bottom + 6, color=AXIS if tick == 0 else GRID)
        text(d, x, bottom + 12, str(tick), 13, MUTED, align="center")

    row_h = (bottom - top) / len(rows)
    for i, (lbl, tps, p99, split, col) in enumerate(rows):
        cy = top + (i + 0.5) * row_h
        text(d, l_left - 14, cy - 16, lbl, 15, INK, align="right")
        text(d, l_left - 14, cy + 4, split, 12, MUTED, align="right")
        w = (tps / vmax_t) * (l_right - l_left)
        rect(d, l_left, cy - 14, w, 28, fill=col)
        text(d, l_left + w + 8, cy - 9, f"{tps:.1f}", 16, INK, light=True)

    line(d, 616, 152, 616, 526, color=GRID, width=1.2)

    # Right panel: TTFT P99 (0-1600 ms)
    rx0, r_left, r_right = 648, 678, 1084
    text(d, rx0, 152, "首 Token 尾延迟（TTFT P99，越低越好）" if cn else "TTFT P99 latency (ms, lower is better)", 21, INK, light=True)
    text(d, rx0, 182, "横轴 0 - 1,600 ms · 热点跨双卡后 P99 骤降 86.2%" if cn else "X-axis 0-1,600 ms / hotspot split cuts P99 by 86.2%", 15, MUTED)

    vmax_p = 1600.0
    for tick in [0, 400, 800, 1200, 1600]:
        x = r_left + (tick / vmax_p) * (r_right - r_left)
        line(d, x, top - 6, x, bottom + 6, color=AXIS if tick == 0 else GRID)
        text(d, x, bottom + 12, f"{tick}", 13, MUTED, align="center")

    for i, (lbl, tps, p99, split, col) in enumerate(rows):
        cy = top + (i + 0.5) * row_h
        w = (p99 / vmax_p) * (r_right - r_left)
        rect(d, r_left, cy - 14, w, 28, fill=col)
        text(d, r_left + w + 10, cy - 9, f"{p99} ms", 16, INK, light=True)

    # Insight strip
    rect(d, 56, 536, 1088, 62, fill=GREEN_BG, outline=GREEN, width=1.1)
    insight = (
        "关键发现：当 --max-num-seqs=32 大于并发 24 时，vLLM 等待队列为 0，EPP 的 queue-scorer 无法感知单卡满载，导致热点仍 87/0 粘在单卡；"
        if cn
        else "Key finding: with --max-num-seqs=32 > C=24, waiting queue stays 0 so EPP queue-scorer ties and pins 87/0 requests on one GPU;"
    )
    insight2 = (
        "将热点 ModelAdapter（lora-01）切为全副本部署、其余 19 个长尾保持单副本硬绑，可兼得双卡并发（450.6 tok/s）与零长尾换入抖动（186 ms）。"
        if cn
        else "promoting only hot lora-01 to all pods while pinning the 19 tail LoRAs achieves 450.6 tok/s and 186 ms P99 with zero tail swaps."
    )
    text(d, 74, 546, insight, 14, INK)
    text(d, 74, 570, insight2, 14, GREEN_DARK)

    foot = (
        "注：AIBrix（热点全副本）通过移除 lora-01 的 replicas: 1 字段在 5 秒内自动扩展至双卡，使用 least-request 策略分发。"
        if cn
        else "Note: AIBrix (hot=all pods) scales lora-01 across both L20s in 5 s by removing spec.replicas: 1 and routing with least-request."
    )
    text(d, 56, 622, foot, 15, MUTED)
    return im


def fig4_noisy_neighbor(cn=True):
    title = "防噪邻实测：恶邻 4K 轰炸下其余 19 个在线 LoRA 的延迟保护" if cn else "Noisy neighbor isolation: protecting 19 live LoRAs under 4K flood"
    sub = (
        "2×1 L20 · 19 个正常 LoRA（C=8, 450 tok 短请求）+ 1 个恶邻 lora-20（C=16, 3,300 tok 长上下文）· 19 个正常业务全 64/64 成功"
        if cn
        else "2x1 L20 / 19 normal LoRAs (C=8, 450 tok) + 1 noisy lora-20 (C=16, 3,300 tok) / all 19 normal LoRAs 64/64 complete"
    )
    im, d = new_canvas(title, sub)

    # Left panel: Normal 19 LoRAs TTFT P50 / P95 / P99 (0-5500 ms)
    lx0, l_left, l_right = 56, 128, 578
    top, bottom = 248, 514
    text(d, lx0, 152, "正常 19 个 LoRA 的 TTFT（越低越好）" if cn else "Normal 19 LoRAs TTFT (lower is better)", 21, INK, light=True)
    text(d, lx0, 182, "纵轴 0 - 5,500 ms · 对比无保护、EPP 优先级与 AIBrix 限流" if cn else "Y-axis 0-5,500 ms / unprotected vs. EPP priority vs. AIBrix", 15, MUTED)
    for lx, lbl, col in [(336, "P50", GRAY), (412, "P95", GREEN), (488, "P99", SLATE)]:
        rect(d, lx, 212, 14, 14, fill=col)
        text(d, lx + 20, 210, lbl, 14, MUTED)

    vmax_l = 5500.0
    for tick in [0, 1000, 2000, 3000, 4000, 5000]:
        y = bottom - (tick / vmax_l) * (bottom - top)
        line(d, l_left, y, l_right, y, color=AXIS if tick == 0 else GRID)
        text(d, l_left - 12, y - 9, f"{tick/1000:.0f}s" if tick else "0", 14, MUTED, align="right")

    groups = [
        ("无保护 RR" if cn else "Unprotected RR", 363, 4606, 4826),
        ("llm-d 优先级" if cn else "llm-d Priority", 810, 1875, 1933),
        ("AIBrix 限流" if cn else "AIBrix RateLimit", 202, 579, 2514),
    ]
    bw = 34
    gap = 6
    centers = [206, 356, 506]
    for cx, (lbl, p50, p95, p99) in zip(centers, groups):
        xs = [cx - bw * 1.5 - gap, cx - bw / 2, cx + bw / 2 + gap]
        for x, val, col in zip(xs, [p50, p95, p99], [GRAY, GREEN, SLATE]):
            h = (val / vmax_l) * (bottom - top)
            rect(d, x, bottom - h, bw, h, fill=col)
            txt = f"{val/1000:.1f}s" if val >= 1000 else f"{val}"
            text(d, x + bw / 2, bottom - h - 19, txt, 12, INK if col != SLATE else SLATE, align="center")
        text(d, cx, bottom + 14, lbl, 14, INK, align="center")

    text(d, lx0, 560, "两种治理都将正常业务 P95/P99 从 ~4.8s 压回 0.6s - 2.5s 区间。" if cn else "Both protections cut normal tail TTFT from ~4.8s down to 0.6-2.5s.", 15, GREEN_DARK)

    line(d, 608, 152, 608, 588, color=GRID, width=1.2)

    # Right panel: Top = Normal E2E P99 (ms); Bottom = Mechanism Contrast Cards (Work-conserving vs Hard Quota)
    rx0 = 640
    text(d, rx0, 152, "正常业务 E2E P99 与恶邻处置机制对比" if cn else "Normal E2E P99 and noisy-tenant handling", 21, INK, light=True)
    text(d, rx0, 182, "横轴 0 - 14s · 对比“保吞吐排队”与“网关硬拒 429”" if cn else "X-axis 0-14s / work-conserving queue vs. hard 429 quota", 15, MUTED)

    bx0, bx1 = 782, 1084
    e2es = [
        ("无保护 RR" if cn else "Unprotected RR", 12.06, GRAY),
        ("llm-d 优先级" if cn else "llm-d Priority", 7.11, GREEN),
        ("AIBrix 限流" if cn else "AIBrix RateLimit", 6.11, GREEN_DARK),
    ]
    for i, (lbl, val, col) in enumerate(e2es):
        y = 226 + i * 38
        text(d, bx0 - 12, y + 3, lbl, 14, MUTED, align="right")
        w = (val / 14.0) * (bx1 - bx0)
        rect(d, bx0, y, w, 24, fill=col)
        text(d, bx0 + w + 10, y + 2, f"{val:.2f} s", 16, INK, light=True)

    line(d, rx0, 356, 1144, 356, color=GRID)

    # Card 1: llm-d EPP Priority Flow Control
    rect(d, rx0, 376, 504, 84, fill=GREEN_BG, outline=GREEN, width=1.1)
    text(d, rx0 + 14, 386, "llm-d EPP v1.0.0（Work-Conserving 优先级流控）" if cn else "llm-d EPP v1.0.0 (Work-conserving priority queue)", 15, GREEN_DARK)
    text(d, rx0 + 14, 412, "恶邻标 priority=-10，0 次 429（80/80 趁闲完成）；" if cn else "Noisy marked priority=-10: 0 HTTP 429 (80/80 completed);", 14, INK)
    text(d, rx0 + 14, 434, "正常业务插队调度，TTFT P99 降 59.9%（1,933 ms）。" if cn else "normal LoRAs jump queue, cutting TTFT P99 59.9% (1,933 ms).", 14, MUTED)

    # Card 2: AIBrix Redis RateLimit
    rect(d, rx0, 474, 504, 84, fill="#F9FAFB", outline=GRAY, width=1.1)
    text(d, rx0 + 14, 484, "AIBrix v0.8.0（Redis 租户 RPM / TPM 硬限流）" if cn else "AIBrix v0.8.0 (Redis per-user RPM/TPM hard cap)", 15, SLATE)
    text(d, rx0 + 14, 510, "恶邻超额即刻网关硬拒（8,553 次 429，仅放行 6 次）；" if cn else "Excess noisy calls hard-blocked (8,553 HTTP 429, 6 admitted);", 14, INK)
    text(d, rx0 + 14, 532, "正常业务 P50 202 ms / P95 579 ms（-87.4%）；首波 6 条致 P99 2.5s。" if cn else "normal P50 202 ms / P95 579 ms (-87.4%), 1st 6 burst gives 2.5s P99.", 13, MUTED)

    foot = (
        "注：llm-d EPP 通过 x-gateway-inference-objective 映射 priority=+10/-10；AIBrix 通过 user 头匹配 Redis 配额（6 RPM / 20k TPM）。"
        if cn
        else "Note: llm-d EPP maps x-gateway-inference-objective to priority +10/-10; AIBrix enforces Redis user quota (6 RPM / 20k TPM)."
    )
    text(d, 56, 622, foot, 15, MUTED)
    return im


def main():
    figs = [
        ("aibrix-vs-llmd-architecture.png", fig0_architecture),
        ("single-gpu-max-loras-sweep.png", fig1_single_gpu_sweep),
        ("uniform-affinity-routing.png", fig2_uniform_routing),
        ("hotspot-skew-comparison.png", fig3_hotspot_comparison),
        ("noisy-neighbor-isolation.png", fig4_noisy_neighbor),
    ]
    for fname, fn in figs:
        for cn, dest_dir in [(True, CN_DIR), (False, EN_DIR)]:
            im = fn(cn=cn).resize((W, H), Image.Resampling.LANCZOS)
            out = dest_dir / fname
            im.save(out, optimize=True)
            print("Saved", out)


if __name__ == "__main__":
    main()
