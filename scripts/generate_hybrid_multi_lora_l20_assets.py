#!/usr/bin/env python3
"""Generate third-edition (V3) bilingual figures for hybrid-multi-lora-l20-prefix-cache.

Follows V3 style (scripts/generate_dsv41_vllm032_research_assets.py):
- White background, clean whitespace, flat solid fills, light axes, no error bars
- Chinese: Hiragino Sans GB W3 (face 0); Latin/digits: Helvetica Neue Light (face 7) / Regular (face 0)
- Palette: neutral gray (#D4D4D8), muted green (#78B5A3), deep green (#2F6F5E), slate (#475569), amber (#B45309)
- 1200x675 (16:9) rendered at 2x supersampling with LANCZOS downsampling
- ASCII-safe English labels (no Unicode arrows in Helvetica Neue)
"""
import json
import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
CN_DIR = ROOT / "docs/assets/practices/hybrid-multi-lora-l20-prefix-cache"
EN_DIR = ROOT / "translations/en-assets/assets/practices/hybrid-multi-lora-l20-prefix-cache"
CN_DIR.mkdir(parents=True, exist_ok=True)
EN_DIR.mkdir(parents=True, exist_ok=True)

DATA = json.loads((CN_DIR / "results.json").read_text())

W, H = 1200, 675
S = 2

INK = "#202020"
MUTED = "#6B7280"
GRID = "#EAEAEA"
AXIS = "#C8C8C8"
GRAY = "#D4D4D8"
GRAY_DARK = "#9CA3AF"
GREEN = "#78B5A3"
GREEN_DARK = "#2F6F5E"
GREEN_BG = "#F4FAF8"
SLATE = "#475569"
LIGHT_BG = "#F6F7F8"
AMBER = "#B45309"
AMBER_BG = "#FEF7EC"


def face(value, size, light=False, mono=False):
    if mono:
        return ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", round(size * S), index=0)
    if any("\u3400" <= ch <= "\u9fff" for ch in value):
        return ImageFont.truetype("/System/Library/Fonts/Hiragino Sans GB.ttc", round(size * S), index=0)
    return ImageFont.truetype("/System/Library/Fonts/HelveticaNeue.ttc", round(size * S), index=7 if light else 0)


def text(d, x, y, value, size=20, color=INK, align="left", light=False, mono=False):
    f = face(value, size, light=light, mono=mono)
    b = d.textbbox((0, 0), value, font=f)
    tw, th = b[2] - b[0], b[3] - b[1]
    xx = x * S - (tw / 2 if align == "center" else tw if align == "right" else 0)
    assert -4 <= xx and xx + tw <= W * S + 4, f"x out of bounds: {value} ({xx/S:.1f}, {(xx+tw)/S:.1f})"
    assert -4 <= y * S and y * S + th <= H * S + 4, f"y out of bounds: {value} ({y:.1f})"
    d.text((xx - b[0], y * S - b[1]), value, font=f, fill=color)
    return tw / S, th / S


def line(d, x1, y1, x2, y2, color=GRID, width=1):
    d.line((round(x1 * S), round(y1 * S), round(x2 * S), round(y2 * S)), fill=color, width=round(width * S))


def dashed_line(d, x1, y1, x2, y2, color=AMBER, width=1.5, dash=8, gap=6):
    dist = math.hypot(x2 - x1, y2 - y1)
    if dist < 1e-6:
        return
    ux, uy = (x2 - x1) / dist, (y2 - y1) / dist
    cur = 0.0
    while cur < dist:
        nxt = min(dist, cur + dash)
        line(d, x1 + ux * cur, y1 + uy * cur, x1 + ux * nxt, y1 + uy * nxt, color=color, width=width)
        cur += dash + gap


def rect(d, x, y, w, h, fill=None, outline=None, width=1):
    d.rectangle(
        (round(x * S), round(y * S), round((x + w) * S), round((y + h) * S)),
        fill=fill,
        outline=outline,
        width=round(width * S) if outline else 0,
    )


def circle(d, cx, cy, r, fill, outline=None, width=1.5):
    d.ellipse(
        (round((cx - r) * S), round((cy - r) * S), round((cx + r) * S), round((cy + r) * S)),
        fill=fill,
        outline=outline,
        width=round(width * S) if outline else 0,
    )


def new_canvas(title, subtitle):
    im = Image.new("RGB", (W * S, H * S), "white")
    d = ImageDraw.Draw(im)
    text(d, 56, 36, title, 31, INK, light=True)
    text(d, 56, 84, subtitle, 17, MUTED, light=True)
    return im, d


def axis(d, left, right, top, bottom, maximum, ticks, fmt=None):
    for v in ticks:
        y = bottom - v / maximum * (bottom - top)
        line(d, left, y, right, y, color=AXIS if v == 0 else GRID, width=1.2 if v == 0 else 1)
        lbl = fmt(v) if fmt else str(v)
        text(d, left - 14, y - 9, lbl, 16, MUTED, align="right")


def save_fig(im, name, cn):
    dest = (CN_DIR if cn else EN_DIR) / name
    im.resize((W, H), Image.Resampling.LANCZOS).save(dest, optimize=True)
    print(f"Saved {dest}")


# ---------------------------------------------------------------------------
# Figure 1: Hybrid Architecture & 544-Token Unified Page Alignment Schematic
# ---------------------------------------------------------------------------
def fig1_architecture(cn=True):
    if cn:
        im, d = new_canvas(
            "Qwen3.5-2B 混合架构与 vLLM 544-Token 统一页对齐机制",
            "24 层 3:1 混合栈（18 层 GDN 线性注意力 + 6 层全注意力）· 186 个权重支持在线 Punica LoRA",
        )
    else:
        im, d = new_canvas(
            "Qwen3.5-2B Hybrid Stack and vLLM 544-Token Unified Page Alignment",
            "24-layer 3:1 hybrid stack (18 GDN linear + 6 full attention) / 186 linear weights with online Punica LoRA",
        )

    # Left section: 3:1 Hybrid Layer Stack + Online Multi-LoRA
    lx, ly, lw, lh = 56, 140, 520, 448
    rect(d, lx, ly, lw, lh, fill=LIGHT_BG, outline="#E2E8F0", width=1)
    text(
        d, lx + 24, ly + 20,
        "1. 模型层栈与在线 Multi-LoRA 覆盖面" if cn else "1. Hybrid Layer Stack & Online Multi-LoRA Coverage",
        19, INK, light=False,
    )
    text(
        d, lx + 24, ly + 50,
        "每 4 层重复 1 组（共 6 组 = 24 层），底座仅 4.18 GiB BF16" if cn else "Repeated 6x (24 layers total), base weights only 4.18 GiB BF16",
        15, MUTED,
    )

    # Draw 4 stacked layers representing 1 repeating group
    layers = [
        ("Layer 4k+1 · Linear Attn (GDN) + MLP" if not cn else "第 4k+1 层 · GDN 线性注意力 + MLP", GREEN_BG, GREEN),
        ("Layer 4k+2 · Linear Attn (GDN) + MLP" if not cn else "第 4k+2 层 · GDN 线性注意力 + MLP", GREEN_BG, GREEN),
        ("Layer 4k+3 · Linear Attn (GDN) + MLP" if not cn else "第 4k+3 层 · GDN 线性注意力 + MLP", GREEN_BG, GREEN),
        ("Layer 4k+4 · Full Attention (GQA 4:1) + MLP" if not cn else "第 4k+4 层 · 全注意力 (GQA 4:1) + MLP", "#EEF2F6", SLATE),
    ]
    by = ly + 92
    for lbl, bg, bd in layers:
        rect(d, lx + 24, by, lw - 48, 46, fill=bg, outline=bd, width=1.2)
        text(d, lx + 40, by + 13, lbl, 15.5, INK)
        by += 56

    # LoRA attachment summary box
    rect(d, lx + 24, by + 12, lw - 48, 108, fill="white", outline=GREEN_DARK, width=1.2)
    text(
        d, lx + 40, by + 24,
        "Punica 在线 Multi-LoRA（r=16, alpha=32, 32.1 MB/份）" if cn else "Punica Online Multi-LoRA (r=16, alpha=32, 32.1 MB/adapter)",
        15.5, GREEN_DARK,
    )
    rows = [
        ("Full Attn (6 层): q / k / v / o_proj = 24 权重" if cn else "Full Attn (6 layers): q/k/v/o_proj = 24 weights"),
        ("GDN Linear (18 层): in_proj_{qkv,z,a,b}, out_proj = 90 权重" if cn else "GDN Linear (18 layers): in_proj_{qkv,z,a,b}, out_proj = 90 weights"),
        ("MLP (24 层): gate / up / down_proj = 72 权重 · 合计 186 权重" if cn else "MLP (24 layers): gate/up/down_proj = 72 weights (186 total)"),
    ]
    ry = by + 52
    for r in rows:
        text(d, lx + 40, ry, r, 13.8, SLATE)
        ry += 22

    # Right section: Why Block Size = 544 Tokens (Unified Paged Allocator)
    rx, ry0, rw, rh = 612, 140, 532, 448
    rect(d, rx, ry0, rw, rh, fill=LIGHT_BG, outline="#E2E8F0", width=1)
    text(
        d, rx + 24, ry0 + 20,
        "2. 为什么混合 Prefix Cache 块大小涨到 544 Tokens？" if cn else "2. Why Hybrid Block Size Expands to 544 Tokens",
        19, INK,
    )
    text(
        d, rx + 24, ry0 + 50,
        "vLLM 0.33.0 默认 mamba_cache_mode=align，统一页池要求页字节相等" if cn else "vLLM 0.33.0 defaults to mamba=align; unified pool matches page bytes",
        14.0, MUTED,
    )

    # Pure Transformer bar
    y1 = ry0 + 96
    text(d, rx + 24, y1, "纯 Transformer（Qwen3-8B）：16 tokens/块，任意前缀可复用" if cn else "Pure Transformer (Qwen3-8B): 16 tokens/block, fine-grained", 14.2, SLATE)
    for k in range(12):
        rect(d, rx + 24 + k * 39, y1 + 26, 33, 28, fill=GRAY, outline=None)
    text(d, rx + 24, y1 + 60, "每 16 tokens 即可切出一个缓存块" if cn else "1 cacheable block every 16 tokens", 13.5, MUTED)

    # Hybrid Qwen3.5 bar
    y2 = ry0 + 194
    text(d, rx + 24, y2, "混合架构（Qwen3.5-2B）：1 块 = 544 tok（含 GDN 快照 + 2.64% 填充）" if cn else "Hybrid (Qwen3.5-2B): 544 tok/block (GDN state + 2.64% pad)", 14.0, GREEN_DARK)
    # Draw two 544-token blocks + partial tail
    rect(d, rx + 24, y2 + 28, 196, 48, fill=GREEN, outline=GREEN_DARK, width=1.2)
    text(d, rx + 122, y2 + 43, "Block 1 · 544 tok (HIT)" if not cn else "块 1 · 544 tok（命中）", 14.5, "white", align="center")
    rect(d, rx + 226, y2 + 28, 196, 48, fill=GREEN, outline=GREEN_DARK, width=1.2)
    text(d, rx + 324, y2 + 43, "Block 2 · 544 tok (HIT)" if not cn else "块 2 · 544 tok（命中）", 14.5, "white", align="center")
    rect(d, rx + 428, y2 + 28, 80, 48, fill=AMBER_BG, outline=AMBER, width=1.2)
    text(d, rx + 468, y2 + 43, "尾块重算" if cn else "Tail", 14, AMBER, align="center")

    # Sawtooth cliff callout inside right box
    rect(d, rx + 24, y2 + 98, rw - 48, 134, fill="white", outline=AMBER, width=1.2)
    text(d, rx + 40, y2 + 110, "实测隐藏悬崖：凑不满整块 = 整段前缀退化重算" if cn else "Measured Cliff: Falling Short of 544 / 1,088 Drops Hit Rate", 14.8, AMBER)
    notes = [
        ("· 输入 533 tok（< 544）-> 命中率 0.0%，完全无法复用" if cn else "- 533 tok (< 544) -> 0.0% hit; entire prefix recomputed"),
        ("· 输入 1,110 tok（差 16 到 1,088）-> 命中跌至 49.0%，TTFT +47%" if cn else "- 1,110 tok (16 short of 1,088) -> 49.0% hit, TTFT +47%"),
        ("· 补齐至 1,284 tok（> 1,088）-> 命中跳回 84.8%，QPS 反涨 +40%" if cn else "- 1,284 tok (> 1,088) -> 84.8% hit, QPS rebounds +40%"),
        ("· 显存代价：开启 align 后同 33.83 GiB 槽位数减少 13.6%" if cn else "- VRAM trade-off: align trims token slots by 13.6%"),
    ]
    ny = y2 + 138
    for n in notes:
        text(d, rx + 40, ny, n, 13.0, SLATE)
        ny += 22

    # Footer
    text(
        d, 56, 622,
        "数据来源：NVIDIA L20 (46 GB) · vLLM 0.33.0b1 · Qwen3.5-2B BF16 启动日志与受控实测。" if cn else "Source: NVIDIA L20 (46 GB) / vLLM 0.33.0b1 / Qwen3.5-2B BF16 startup logs and controlled measurements.",
        15, MUTED,
    )
    save_fig(im, "hybrid-architecture-544-block.png", cn)


# ---------------------------------------------------------------------------
# Figure 2: Single-L20 Multi-LoRA Limit Sweep (Exp 2A + Exp 2B)
# ---------------------------------------------------------------------------
def fig2_multi_lora_scaling(cn=True):
    exp2 = DATA["exp2_limit_sweep"]
    if cn:
        im, d = new_canvas(
            "单张 L20 多任务 Multi-LoRA 极限吞吐与扩展代价",
            "Qwen3.5-2B BF16 · vLLM 0.33.0b1 · 关闭 Prefix Cache · 420 tok 唯一输入 · 三轮中位数",
        )
    else:
        im, d = new_canvas(
            "Single-L20 Multi-LoRA Saturation Curve and Scaling Overhead",
            "Qwen3.5-2B BF16 / vLLM 0.33.0b1 / Prefix Cache OFF / 420-tok unique input / 3-round median",
        )

    # Left panel: Line chart of QPS across C=1,8,16,32,64 (2A short output)
    left, right, top, bottom = 104, 624, 210, 520
    text(d, left, 138, "短输出判定场景（420 tok -> 4 tok）" if cn else "Short Classification (420 -> 4 tok)", 21, INK, light=True)
    text(d, left, 170, "吞吐 QPS（0 - 80）· 并发 C=32 达饱和拐点" if cn else "Throughput QPS (0-80) / saturates at C=32", 15.5, MUTED)
    axis(d, left, right, top, bottom, 80, [0, 20, 40, 60, 80])

    concs = [1, 8, 16, 32, 64]
    xs = [left + (i + 0.35) / (len(concs) - 0.3) * (right - left) for i in range(len(concs))]
    for i, c in enumerate(concs):
        text(d, xs[i], bottom + 14, f"C={c}", 16, INK, align="center")
    # Vertical dashed knee line at C=32
    dashed_line(d, xs[3], top + 10, xs[3], bottom, color=AXIS, width=1.2, dash=5, gap=5)
    text(d, xs[3], top - 6, "饱和拐点" if cn else "Knee", 13.5, MUTED, align="center")

    series = [
        ("base", "Base (无 LoRA)" if cn else "Base (no LoRA)", SLATE, 2.4),
        ("lora_1", "1 LoRA", GREEN_DARK, 2.2),
        ("lora_4", "4 LoRAs", GREEN, 2.2),
        ("lora_8", "8 LoRAs", AMBER, 2.2),
    ]
    # Legend row for left panel
    lx_cur = left
    for _, lbl, col, _ in series:
        rect(d, lx_cur, bottom + 50, 14, 14, fill=col)
        tw, _ = text(d, lx_cur + 20, bottom + 48, lbl, 14.5, MUTED)
        lx_cur += tw + 38

    sc = exp2["short_classification"]
    for key, _, col, lw in series:
        pts = [(xs[i], bottom - sc[key][f"c{c}"]["qps"] / 80.0 * (bottom - top)) for i, c in enumerate(concs)]
        for i in range(len(pts) - 1):
            line(d, pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1], color=col, width=lw)
        for px, py in pts:
            circle(d, px, py, 4.2, fill=col)

    # Direct clean callouts at C=32 and C=64 (zero overlap with lines)
    b32 = sc["base"]["c32"]["qps"]
    l1_32 = sc["lora_1"]["c32"]["qps"]
    l8_32 = sc["lora_8"]["c32"]["qps"]
    text(d, xs[3], bottom - b32 / 80.0 * (bottom - top) - 24, f"{b32:.1f}", 16, SLATE, align="center")
    text(d, xs[4], bottom - sc["base"]["c64"]["qps"] / 80.0 * (bottom - top) - 24, f"{sc['base']['c64']['qps']:.1f}", 16, SLATE, align="center")
    text(d, xs[4], bottom - sc["lora_1"]["c64"]["qps"] / 80.0 * (bottom - top) - 22, f"{sc['lora_1']['c64']['qps']:.1f}", 15.5, GREEN_DARK, align="center")
    text(d, xs[3] + 14, bottom - l8_32 / 80.0 * (bottom - top) + 12, f"{l8_32:.1f}", 15.5, AMBER, align="left")
    text(d, xs[4], bottom - sc["lora_8"]["c64"]["qps"] / 80.0 * (bottom - top) + 12, f"{sc['lora_8']['c64']['qps']:.1f}", 15.5, AMBER, align="center")

    # Right panel: Bar chart for Standard Generation (2B, C=32)
    r_left, r_right = 716, 1140
    text(d, r_left, 138, "标准生成吞吐（420 -> 64 tok, C=32）" if cn else "Standard Generation (420 -> 64 tok, C=32)", 21, INK, light=True)
    text(d, r_left, 170, "总输出 tok/s（0 - 2,400）· 标注含 TPOT P50" if cn else "Output tok/s (0-2,400) with TPOT P50", 15.5, MUTED)
    axis(d, r_left, r_right, top, bottom, 2400, [0, 600, 1200, 1800, 2400])

    sg = exp2["standard_generation"]
    bars = [
        ("base", "Base", GRAY, SLATE),
        ("lora_1", "1 LoRA", GREEN, GREEN_DARK),
        ("lora_4", "4 LoRAs", GREEN, GREEN_DARK),
        ("lora_8", "8 LoRAs", GREEN, GREEN_DARK),
    ]
    bw = 66
    step = (r_right - r_left) / len(bars)
    for i, (key, lbl, fill_c, txt_c) in enumerate(bars):
        val = sg[key]["c32"]["output_tok_s"]
        tpot = sg[key]["c32"]["tpot_p50_ms"]
        cx = r_left + (i + 0.5) * step
        bh = val / 2400.0 * (bottom - top)
        rect(d, cx - bw / 2, bottom - bh, bw, bh, fill=fill_c)
        text(d, cx, bottom - bh - 44, f"{val:,.0f}", 20, INK, align="center", light=True)
        text(d, cx, bottom - bh - 20, f"{tpot:.1f} ms", 13.5, MUTED, align="center")
        text(d, cx, bottom + 14, lbl, 16, INK, align="center")

    # Insight footnote
    text(
        d, 56, 622,
        "注：开启首个 LoRA 产生约 13% 固定 Punica 算子开销；但从 1 LoRA 扩展到 8 LoRA 同卡并发，吞吐仅额外下降 4.7%（短输出）至 7.9%（64-tok 生成）。"
        if cn else
        "Note: Enabling LoRA adds ~13% fixed Punica kernel overhead; scaling from 1 to 8 concurrent LoRAs costs only 4.7% (short) to 7.9% (64-tok gen) extra.",
        14.8, MUTED,
    )
    save_fig(im, "single-l20-multi-lora-scaling.png", cn)


# ---------------------------------------------------------------------------
# Figure 3: Hybrid Prefix Cache Speedup (Exp 3: PC-Off vs align vs align+ckpt)
# ---------------------------------------------------------------------------
def fig3_prefix_cache_speedup(cn=True):
    exp3 = DATA["exp3_hybrid_prefix_cache"]
    if cn:
        im, d = new_canvas(
            "混合架构 Prefix Cache 实测收益（1,294 Token 共享规则提示词）",
            "Qwen3.5-2B · 1×L20 · 并发 C=32 · 3 轮中位数 · mamba_cache_mode=align 实测命中率 84.1%",
        )
    else:
        im, d = new_canvas(
            "Hybrid Prefix Cache Speedup (1,294-Token Shared System Prompt)",
            "Qwen3.5-2B / 1xL20 / Concurrency C=32 / 3-round median / 84.1% measured cache hit rate",
        )

    # Top shared legend
    leg_items = [
        ("PC-Off（关闭）" if cn else "PC-Off (disabled)", GRAY),
        ("PC-On (mamba=align)", GREEN),
        ("PC-On + Shared Prefix Ckpt" if not cn else "PC-On + 共享前缀检查点", GREEN_DARK),
    ]
    lx_cur = 56
    for lbl, col in leg_items:
        rect(d, lx_cur, 126, 15, 15, fill=col)
        tw, _ = text(d, lx_cur + 23, 124, lbl, 16, MUTED)
        lx_cur += tw + 46

    groups = [
        ("base", "Base"),
        ("lora_1", "1 LoRA"),
        ("lora_4", "4 LoRAs"),
    ]
    modes = [("pc_off", GRAY), ("pc_align", GREEN), ("pc_align_ckpt", GREEN_DARK)]

    # Left panel: QPS at C=32 (0 - 120)
    l1, r1, top, bottom = 104, 578, 224, 536
    text(d, l1, 168, "吞吐对比（QPS · 越高越好）" if cn else "Throughput (QPS, higher is better)", 20, INK, light=True)
    text(d, l1, 196, "QPS · 0 - 120" if cn else "QPS / 0-120", 15, MUTED)
    axis(d, l1, r1, top, bottom, 120, [0, 30, 60, 90, 120])

    bw, gap = 36, 8
    gstep = (r1 - l1) / len(groups)
    for gi, (gkey, glbl) in enumerate(groups):
        gcx = l1 + (gi + 0.5) * gstep
        for mi, (mkey, col) in enumerate(modes):
            val = exp3[mkey]["workloads"][gkey]["c32"]["qps"]
            bx = gcx + (mi - 1) * (bw + gap) - bw / 2
            bh = val / 120.0 * (bottom - top)
            rect(d, bx, bottom - bh, bw, bh, fill=col)
            text(d, bx + bw / 2, bottom - bh - 24, f"{val:.1f}", 15.5, INK, align="center", light=True)
        text(d, gcx, bottom + 14, glbl, 17, INK, align="center")

    # Right panel: TTFT P50 at C=32 (0 - 1500 ms)
    l2, r2 = 678, 1144
    text(d, l2, 168, "首字延迟 P50 TTFT（ms · 越低越好）" if cn else "P50 TTFT Latency (ms, lower is better)", 20, INK, light=True)
    text(d, l2, 196, "ms · 0 - 1,500" if cn else "ms / 0-1,500", 15, MUTED)
    axis(d, l2, r2, top, bottom, 1500, [0, 300, 600, 900, 1200, 1500])

    gstep2 = (r2 - l2) / len(groups)
    for gi, (gkey, glbl) in enumerate(groups):
        gcx = l2 + (gi + 0.5) * gstep2
        for mi, (mkey, col) in enumerate(modes):
            val = exp3[mkey]["workloads"][gkey]["c32"]["ttft_p50_ms"]
            bx = gcx + (mi - 1) * (bw + gap) - bw / 2
            bh = val / 1500.0 * (bottom - top)
            rect(d, bx, bottom - bh, bw, bh, fill=col)
            text(d, bx + bw / 2, bottom - bh - 24, f"{val:.0f}", 15.5, INK, align="center", light=True)
        text(d, gcx, bottom + 14, glbl, 17, INK, align="center")

    text(
        d, 56, 618,
        "4-LoRA 开启 Hybrid Prefix Cache 后吞吐 20.1 -> 81.7 QPS（4.07x），P50 TTFT 1,316 -> 305 ms（-76.9%）；Base 加检查点达 104.35 QPS。"
        if cn else
        "4-LoRA Hybrid Prefix Cache: 20.1 -> 81.7 QPS (4.07x), P50 TTFT 1,316 -> 305 ms (-76.9%); Base + checkpoint reaches 104.35 QPS.",
        14.0, MUTED,
    )
    save_fig(im, "hybrid-prefix-cache-speedup.png", cn)


# ---------------------------------------------------------------------------
# Figure 4: 544-Token Hybrid Block Sawtooth Cliff (Exp 3 Probe)
# ---------------------------------------------------------------------------
def fig4_sawtooth_cliff(cn=True):
    probe = DATA["exp3_hybrid_prefix_cache"]["pc_align"]["prefix_length_probe"]
    keys = ["len_450", "len_560", "len_980", "len_1140"]
    items = [probe[k] for k in keys]

    if cn:
        im, d = new_canvas(
            "544-Token 混合块边界探针：为什么加长提示词反而快了 40%？",
            "Qwen3.5-2B · lora-01 · mamba_cache_mode=align · C=4 · 跨过 544 / 1,088 边界的实测锯齿效应",
        )
    else:
        im, d = new_canvas(
            "544-Token Hybrid Block Cliff: Why a Longer Prompt Runs 40% Faster",
            "Qwen3.5-2B / lora-01 / mamba_cache_mode=align / C=4 / sawtooth hit-rate across 544 and 1,088 boundaries",
        )

    # Left panel: Prefix Cache Hit Rate (%)
    l1, r1, top, bottom = 104, 576, 212, 514
    text(d, l1, 144, "Prefix Cache 实测命中率（%）" if cn else "Measured Prefix Cache Hit Rate (%)", 20, INK, light=True)
    text(d, l1, 174, "命中率 = floor(共享前缀 / 544) x 544 / 总输入" if cn else "Hit rate = floor(shared_prefix / 544) * 544 / total_input", 14.8, MUTED)
    axis(d, l1, r1, top, bottom, 100, [0, 25, 50, 75, 100], fmt=lambda v: f"{v}%")

    step1 = (r1 - l1) / len(items)
    bw = 68
    x_labels_cn = ["533 tok\n(<544)", "654 tok\n(>544)", "1,110 tok\n(差16到1088)", "1,284 tok\n(>1,088)"]
    x_labels_en = ["533 tok\n(<544)", "654 tok\n(>544)", "1,110 tok\n(16 short)", "1,284 tok\n(>1,088)"]
    x_labels = x_labels_cn if cn else x_labels_en

    for i, it in enumerate(items):
        cx = l1 + (i + 0.5) * step1
        val = it["pc_hit_rate_pct"]
        col = GRAY if val == 0 else (AMBER if i == 2 else GREEN)
        bh = val / 100.0 * (bottom - top)
        if bh > 0:
            rect(d, cx - bw / 2, bottom - bh, bw, bh, fill=col)
        else:
            rect(d, cx - bw / 2, bottom - 4, bw, 4, fill=AMBER)
        text(d, cx, bottom - bh - 28, f"{val:.1f}%", 19, AMBER if i in (0, 2) else INK, align="center", light=True)
        for li, part in enumerate(x_labels[i].split("\n")):
            text(d, cx, bottom + 14 + li * 20, part, 14.5 if li == 0 else 13.5, INK if li == 0 else MUTED, align="center")

    # Right panel: Paired QPS (bars) and TTFT P50 annotations
    l2, r2 = 678, 1144
    text(d, l2, 144, "同组实测吞吐 QPS 与 P50 TTFT" if cn else "Measured QPS and P50 TTFT (same probe)", 20, INK, light=True)
    text(d, l2, 174, "QPS（0 - 35）· 柱顶副标为 P50 TTFT 延迟" if cn else "QPS (0-35) / sub-label shows P50 TTFT latency", 14.8, MUTED)
    axis(d, l2, r2, top, bottom, 35, [0, 10, 20, 30])

    step2 = (r2 - l2) / len(items)
    for i, it in enumerate(items):
        cx = l2 + (i + 0.5) * step2
        qps = it["qps"]
        ttft = it["ttft_p50_ms"]
        col = AMBER if i == 2 else (GRAY if i == 0 else GREEN_DARK)
        bh = qps / 35.0 * (bottom - top)
        rect(d, cx - bw / 2, bottom - bh, bw, bh, fill=col)
        text(d, cx, bottom - bh - 46, f"{qps:.1f}", 20, AMBER if i == 2 else INK, align="center", light=True)
        text(d, cx, bottom - bh - 22, f"{ttft:.0f} ms", 13.8, AMBER if i == 2 else MUTED, align="center")
        for li, part in enumerate(x_labels[i].split("\n")):
            text(d, cx, bottom + 14 + li * 20, part, 14.5 if li == 0 else 13.5, INK if li == 0 else MUTED, align="center")

    text(
        d, 56, 616,
        "工程启示：在 Qwen3.5 混合架构上，将共享系统提示词精简或补齐至 544 的整数倍以上（如 >= 544 / 1,088 tok），可彻底避开 49% 命中率低谷。"
        if cn else
        "Takeaway: On Qwen3.5 hybrid models, pad or organize shared system prompts past multiples of 544 tokens (544, 1,088, ...) to avoid the 49% hit-rate valley.",
        14.5, MUTED,
    )
    save_fig(im, "hybrid-544-block-sawtooth.png", cn)


def main():
    for cn in (True, False):
        fig1_architecture(cn)
        fig2_multi_lora_scaling(cn)
        fig3_prefix_cache_speedup(cn)
        fig4_sawtooth_cliff(cn)


if __name__ == "__main__":
    main()
