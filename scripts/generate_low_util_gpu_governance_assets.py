#!/usr/bin/env python3
"""Generate third-edition (V3) bilingual figures for low-util-gpu-serving-governance.

Follows V3 style (scripts/generate_dsv41_vllm032_research_assets.py):
- White background, generous whitespace, flat solid bars, light axes, no error bars
- Chinese: Hiragino Sans GB W3 (face 0); Latin/digits: Helvetica Neue Light (face 7) / Regular (face 0)
- Palette: neutral gray (#D4D4D8), muted green (#78B5A3), deep green (#2F6F5E), slate (#475569), amber (#B45309)
- 1200x675 (16:9) rendered at 2x supersampling with LANCZOS downsampling
"""
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
CN_DIR = ROOT / "docs/assets/practices/low-util-gpu-serving-governance"
EN_DIR = ROOT / "translations/en-assets/assets/practices/low-util-gpu-serving-governance"
CN_DIR.mkdir(parents=True, exist_ok=True)
EN_DIR.mkdir(parents=True, exist_ok=True)

DATA = json.loads((CN_DIR / "audit_summary.json").read_text())

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
# Figure 1: Anatomy of a "Fake 100%" GPU Service (SVC-03, 24x 72G PCIe without NVLink)
# ---------------------------------------------------------------------------
def fig1_fake_100_anatomy(cn=True):
    if cn:
        im, d = new_canvas(
            "解剖“假 100% 饱和”：表象 GPU_UTIL vs 五维底层硬件真相",
            "样板服务 SVC-03（双活 24×72G PCIe 卡 · 无 NVLink · 9 GB FP8 强开 TP=2）· 7 天线上采集",
        )
    else:
        im, d = new_canvas(
            "Anatomy of a Fake 100%: Surface GPU_UTIL vs. Hardware Reality",
            "Case Study SVC-03 (Dual-AZ 24x 72G PCIe GPUs, no NVLink / 9 GB FP8 on TP=2) / 7-day prod data",
        )

    # Left panel: horizontal bar comparison of 6 normalized indicators (0-100%)
    l_bar, r_bar = 276, 700
    top, row_h = 152, 66
    text(d, 56, 124, "同服务 6 维实测水位（0% - 100%）" if cn else "Six-Metric Hardware & Engine Profile (0% - 100%)", 19, INK, light=True)

    rows = [
        ("DCGM GPU_UTIL (Max)" if not cn else "表象 GPU_UTIL 峰值", 100.0, "100.0%", AMBER),
        ("PROF_SM_ACTIVE (Peak)" if not cn else "真实 SM 活跃度峰值", 19.5, "19.5%", GREEN_DARK),
        ("PIPE_TENSOR (Peak)" if not cn else "Tensor Core 峰值", 5.9, "5.9%", GREEN),
        ("Avg Power / 300W TDP" if not cn else "均功耗占 TDP 比例", 28.3, "28.3% (85W)", GRAY),
        ("vLLM KV Cache (Peak)" if not cn else "vLLM KV 缓存峰值", 1.2, "1.18%", GREEN),
        ("vLLM Waiting Queue" if not cn else "vLLM 7 天最大排队", 0.0, "0 reqs", GREEN_DARK),
    ]

    # Grid lines at 0, 25, 50, 75, 100
    for pct in [0, 25, 50, 75, 100]:
        gx = l_bar + pct / 100.0 * (r_bar - l_bar)
        line(d, gx, top - 8, gx, top + len(rows) * row_h - 14, color=AXIS if pct == 0 else GRID, width=1.2 if pct == 0 else 1)
        text(d, gx, top + len(rows) * row_h - 4, f"{pct}%", 14.5, MUTED, align="center")

    for i, (lbl, val, txt_val, col) in enumerate(rows):
        cy = top + i * row_h + 10
        text(d, l_bar - 16, cy + 5, lbl, 16, AMBER if i == 0 else INK, align="right")
        bw = max(4, val / 100.0 * (r_bar - l_bar)) if val > 0 else 3
        rect(d, l_bar, cy, bw, 32, fill=col)
        tx = l_bar + bw + 12
        if val >= 85:
            text(d, l_bar + bw - 14, cy + 5, txt_val, 16.5, "white", align="right")
        else:
            text(d, tx, cy + 5, txt_val, 16.5, AMBER if i == 0 else INK, align="left", light=True)

    # Right panel: Root cause & remediation box
    rx, ry, rw, rh = 744, 152, 400, 412
    rect(d, rx, ry, rw, rh, fill=LIGHT_BG, outline="#E2E8F0", width=1)
    text(d, rx + 22, ry + 20, "根因定位：PCIe TP=2 自旋忙等" if cn else "Root Cause: PCIe TP=2 Spin-Wait", 18.5, INK)

    items_cn = [
        ("1. 显存与并行错配", [
            "FP8 权重仅约 9 GB，却在无 NVLink 的",
            "72G PCIe 卡上强开 TP=2（占 144 GB）。",
        ]),
        ("2. 假 100% 来源", [
            "每层跨 PCIe 走 NCCL AllReduce 自旋等待",
            "拉高 GPU_UTIL 至 100%，同分钟 SM 仅 7–15%。",
        ]),
        ("3. 真实负载极轻", [
            "单可用区峰值仅 17.9 QPS（每 Pod 2.6），",
            "7 天零排队，Prefix Cache 命中 83%。",
        ]),
        ("4. 治本降本收益", [
            "灰度切 TP=1 消除 PCIe AllReduce 后，",
            "双活仅需 12–14 卡（直接省 10–12 张卡）。",
        ]),
    ]
    items_en = [
        ("1. Parallelism Mismatch", [
            "9 GB FP8 weights split across 2x 72G PCIe",
            "GPUs (144 GB total) without NVLink.",
        ]),
        ("2. Fake 100% Mechanism", [
            "Per-layer PCIe NCCL AllReduce spin-wait",
            "pushes GPU_UTIL to 100% at 7-15% SM.",
        ]),
        ("3. Real Load Is Tiny", [
            "Peak 17.9 QPS/AZ (2.6 QPS/Pod), 0 queued",
            "requests over 7 days, 83% PC hit rate.",
        ]),
        ("4. Remediation ROI", [
            "Switching TP=2 -> TP=1 removes AllReduce,",
            "cutting 24 -> 12-14 GPUs (-10 to -12 GPUs).",
        ]),
    ]
    iy = ry + 62
    for heading, lines in (items_cn if cn else items_en):
        text(d, rx + 22, iy, heading, 15.5, GREEN_DARK if heading.startswith("4") else INK)
        ly = iy + 24
        for ln in lines:
            text(d, rx + 22, ly, ln, 13.8, SLATE)
            ly += 20
        iy = ly + 16

    text(
        d, 56, 616,
        "注：GPU_UTIL 仅代表“采样窗口内有任意 CUDA Kernel 在跑”，无法区分有效矩阵计算与通信自旋忙等；缩容评审必须穿透 SM_ACTIVE + Waiting + KV%。"
        if cn else
        "Note: GPU_UTIL only reports whether any CUDA kernel ran (including NCCL spin-wait); scale-down reviews must inspect SM_ACTIVE, Waiting, and KV%.",
        14.0, MUTED,
    )
    save_fig(im, "fake-100-anatomy.png", cn)


# ---------------------------------------------------------------------------
# Figure 2: 25 Production Services Four-Category Governance & GPU Reclaim
# ---------------------------------------------------------------------------
def fig2_four_quadrant_portfolio(cn=True):
    cats = DATA["categories"]
    if cn:
        im, d = new_canvas(
            "25 个低利用率 GPU 推理服务四象限盘点与可回收算力",
            "原登记 313 张 GPU · 首轮已释放 56 卡，当前在线 257 卡 · 按四类成因预计可继续回收 94–126 卡",
        )
    else:
        im, d = new_canvas(
            "25 Low-Utilization Production GPU Services: 4-Category Reclaim Plan",
            "313 initial GPUs / 56 reclaimed in round 1 (257 active) / 94-126 more GPUs reclaimable by root cause",
        )

    # Legend
    lx = 56
    for lbl, col in [
        ("当前在线卡数" if cn else "Current Active GPUs", GRAY),
        ("预计可回收（保守下限）" if cn else "Reclaimable (conservative)", GREEN),
        ("预计可回收（上限区间）" if cn else "Reclaimable (upper bound)", GREEN_DARK),
    ]:
        rect(d, lx, 126, 15, 15, fill=col)
        tw, _ = text(d, lx + 23, 124, lbl, 15.5, MUTED)
        lx += tw + 42

    left, right, top, bottom = 104, 1144, 194, 496
    axis(d, left, right, top, bottom, 160, [0, 40, 80, 120, 160])
    text(d, left, 164, "GPU 卡数（0 - 160）" if cn else "GPU Count (0 - 160)", 15.5, MUTED)

    step = (right - left) / len(cats)
    bw, gap = 54, 14
    for i, c in enumerate(cats):
        cx = left + (i + 0.5) * step
        cur_g = c["current_gpus"]
        r_lo, r_hi = c["reclaim_low"], c["reclaim_high"]

        # Bar 1: Current Active
        x1 = cx - bw - gap / 2
        h1 = cur_g / 160.0 * (bottom - top)
        rect(d, x1, bottom - h1, bw, h1, fill=GRAY)
        text(d, x1 + bw / 2, bottom - h1 - 26, f"{cur_g}", 19, INK, align="center", light=True)

        # Bar 2: Reclaimable (stacked conservative + upper increment)
        x2 = cx + gap / 2
        if r_hi > 0:
            h_lo = r_lo / 160.0 * (bottom - top)
            h_hi = r_hi / 160.0 * (bottom - top)
            rect(d, x2, bottom - h_lo, bw, h_lo, fill=GREEN)
            if h_hi > h_lo:
                rect(d, x2, bottom - h_hi, bw, h_hi - h_lo, fill=GREEN_DARK)
            text(d, x2 + bw / 2, bottom - h_hi - 26, f"{r_lo}-{r_hi}", 18.5, GREEN_DARK, align="center", light=True)
        else:
            rect(d, x2, bottom - 4, bw, 4, fill=AXIS)
            text(d, x2 + bw / 2, bottom - 28, "0", 17, MUTED, align="center")

        # X labels (title + service count + action)
        lbl = c["cn"] if cn else c["en"]
        act = c["action_cn"] if cn else c["action_en"]
        svc_str = f"（{c['services']} 个服务）" if cn else f"({c['services']} services)"
        text(d, cx, bottom + 14, lbl, 15.5, INK, align="center")
        text(d, cx, bottom + 38, svc_str, 14, MUTED, align="center")
        text(d, cx, bottom + 60, act, 13.8, GREEN_DARK if r_hi > 0 else MUTED, align="center")

    text(
        d, 56, 616,
        "重点聚焦：第一类仅 5 个服务就占当前 257 卡中的 140 卡（54.5%），预计可回收 66–88 卡；全表高价值 72G 顶配卡可回收 68–84 张。"
        if cn else
        "Concentration: Just 5 Category-1 services hold 140 of 257 active GPUs (54.5%), yielding 66-88 GPUs; 68-84 high-value 72G GPUs are reclaimable overall.",
        14.2, MUTED,
    )
    save_fig(im, "four-quadrant-portfolio.png", cn)


# ---------------------------------------------------------------------------
# Figure 3: Hardware Fingerprints Across 3 Distinct Low-Util Archetypes
# ---------------------------------------------------------------------------
def fig3_hardware_fingerprints(cn=True):
    fps = DATA["fingerprints"]
    if cn:
        im, d = new_canvas(
            "同样是“低均值 + 高 Max”，三类服务的硬件指纹截然不同",
            "横向对比 9 个脱敏线上代表服务：表象 GPU_UTIL Max vs 真实 SM 峰值 vs Tensor Core 峰值（%）",
        )
    else:
        im, d = new_canvas(
            "Same Low-Avg / High-Max Illusion, Three Distinct Hardware Fingerprints",
            "9 anonymized production services: GPU_UTIL Max vs. SM_ACTIVE Peak vs. Tensor Core Peak (%)",
        )

    # Legend
    lx = 56
    for lbl, col in [
        ("表象 GPU_UTIL Max" if cn else "Surface GPU_UTIL Max", GRAY),
        ("真实 SM_ACTIVE 峰值" if cn else "True SM_ACTIVE Peak", GREEN_DARK),
        ("Tensor Core 峰值" if cn else "Tensor Core Peak", AMBER),
    ]:
        rect(d, lx, 126, 15, 15, fill=col)
        tw, _ = text(d, lx + 23, 124, lbl, 15.5, MUTED)
        lx += tw + 42

    left, right, top, bottom = 96, 1148, 214, 514
    axis(d, left, right, top, bottom, 100, [0, 25, 50, 75, 100], fmt=lambda v: f"{v}%")

    # Group background shading & headers (3 services per group)
    gstep = (right - left) / 3.0
    group_meta = [
        ("一类：假 100% / 可安全缩容" if cn else "Cat 1: Fake 100% / Safe Rightsize", "#F8FAFC", SLATE),
        ("二类：真排队 / 真脉冲（不可硬缩）" if cn else "Cat 2: Real Queue / Burst (Protect SLA)", GREEN_BG, GREEN_DARK),
        ("三类：Tensor=0% 非算力瓶颈" if cn else "Cat 3: Tensor=0% Non-GPU Bound", AMBER_BG, AMBER),
    ]
    for gi, (glbl, gbg, gcol) in enumerate(group_meta):
        gx0 = left + gi * gstep + 4
        gx1 = left + (gi + 1) * gstep - 4
        rect(d, gx0, top - 38, gx1 - gx0, 30, fill=gbg, outline=None)
        text(d, (gx0 + gx1) / 2, top - 30, glbl, 14.5, gcol, align="center")
        if gi > 0:
            line(d, left + gi * gstep, top - 38, left + gi * gstep, bottom + 56, color="#D8DEE6", width=1.2)

    sstep = (right - left) / len(fps)
    bw, gap = 22, 5
    for i, fp in enumerate(fps):
        cx = left + (i + 0.5) * sstep
        vals = [(fp["util_max"], GRAY), (fp["sm_peak"], GREEN_DARK), (fp["tensor_peak"], AMBER)]
        for j, (v, col) in enumerate(vals):
            bx = cx + (j - 1) * (bw + gap) - bw / 2
            bh = v / 100.0 * (bottom - top)
            if bh > 0:
                rect(d, bx, bottom - bh, bw, bh, fill=col)
            else:
                rect(d, bx, bottom - 3, bw, 3, fill=AMBER)
            # Label SM and Tensor cleanly (skip cluttered 100 on gray unless != 100)
            if j == 0 and v < 100:
                text(d, bx + bw / 2, bottom - bh - 18, f"{v:.0f}", 12.5, MUTED, align="center")
            elif j == 1:
                text(d, bx + bw / 2, bottom - bh - 19, f"{v:.0f}", 13.5, GREEN_DARK, align="center")
            elif j == 2:
                text(d, bx + bw / 2, bottom - bh - 19, f"{v:.0f}", 13.5, AMBER, align="center")

        lbl_lines = (fp["cn"] if cn else fp["en"]).split("\n")
        text(d, cx, bottom + 12, lbl_lines[0], 14, INK, align="center")
        text(d, cx, bottom + 32, lbl_lines[1], 12.5, MUTED, align="center")

    text(
        d, 56, 616,
        "读图要点：第一类 GPU_UTIL 虽达 100%，但 SM/Tensor 极低且 0 排队；第二类 SM 达 79–95% 确系真负载；第三类 Tensor 恒为 0%，缩容超时源于并发/CPU 瓶颈。"
        if cn else
        "Takeaway: Cat 1 hits 100% GPU_UTIL with low SM/Tensor and 0 queue; Cat 2 hits 79-95% SM (real load); Cat 3 sits at 0% Tensor (CPU/concurrency bound).",
        14.0, MUTED,
    )
    save_fig(im, "sm-vs-tensor-diagnosis.png", cn)


def main():
    for cn in (True, False):
        fig1_fake_100_anatomy(cn)
        fig2_four_quadrant_portfolio(cn)
        fig3_hardware_fingerprints(cn)


if __name__ == "__main__":
    main()
