#!/usr/bin/env python3
"""Deterministic article visuals for the Qwen3.8 2.4T A95B Day-0 run."""
from pathlib import Path
import json
import shutil

from PIL import Image, ImageDraw, ImageFont

from generate_glm53_day1_assets import font, BG, INK, MUTED, LINE

ROOT = Path(__file__).resolve().parents[1]
DOC_OUT = ROOT / "docs/assets/practices/qwen38-a95b-h20"
WECHAT_OUT = ROOT / "articles/wechat/assets/qwen38-a95b-h20"
BLUE = "#0A2EFE"
BLUE_LIGHT = "#E8EBFF"
PURPLE = "#7057D9"
PURPLE_LIGHT = "#EFEAFE"
TEAL = "#00A6A6"
ORANGE = "#F28C28"
ORANGE_LIGHT = "#FFF1E1"
SUMMARY = DOC_OUT / "benchmark-summary.json"


def txt(draw, x, y, value, size=24, fill=INK, bold=False, latin=False):
    f = font(size, bold=bold, latin=latin)
    if bold and latin:
        f = ImageFont.truetype("/System/Library/Fonts/HelveticaNeue.ttc", size, index=1)
    box = draw.textbbox((0, 0), value, font=f)
    assert x + box[2] - box[0] <= draw._image.width - 12, value
    draw.text((x - box[0], y - box[1]), value, font=f, fill=fill)


def center(draw, box, value, size=24, fill=INK, bold=False, latin=False):
    f = font(size, bold=bold, latin=latin or value.isascii())
    if bold and (latin or value.isascii()):
        f = ImageFont.truetype("/System/Library/Fonts/HelveticaNeue.ttc", size, index=1)
    measured = draw.textbbox((0, 0), value, font=f)
    assert measured[2] - measured[0] <= box[2] - box[0], value
    x = (box[0] + box[2] - measured[2] - measured[0]) / 2
    y = (box[1] + box[3] - measured[3] - measured[1]) / 2
    draw.text((x, y), value, font=f, fill=fill)


def footer(draw, value):
    draw.rounded_rectangle((48, 605, 1152, 656), 15, fill="white", outline=LINE, width=1)
    center(draw, (57, 608, 1143, 652), value, 20, fill=MUTED)


def topology():
    image = Image.new("RGB", (1200, 675), BG)
    draw = ImageDraw.Draw(image)
    txt(draw, 48, 34, "2.4T MoE 如何铺到 32 张 H20-3e", 34, bold=True)
    txt(draw, 50, 93, "四节点 · 节点内 TP8 · 节点间 PP4 · 每节点保存完整 NVMe 权重", 21, fill=MUTED)

    card_w, card_gap = 252, 22
    start_x = 48
    for rank in range(4):
        x = start_x + rank * (card_w + card_gap)
        color = BLUE if rank % 2 == 0 else PURPLE
        light = BLUE_LIGHT if rank % 2 == 0 else PURPLE_LIGHT
        draw.rounded_rectangle((x, 161, x + card_w, 455), 18, fill="white", outline=LINE, width=2)
        draw.rounded_rectangle((x, 161, x + card_w, 220), 18, fill=light)
        draw.rectangle((x, 201, x + card_w, 220), fill=light)
        txt(draw, x + 20, 177, f"Pipeline Stage {rank}", 22, fill=color, bold=True, latin=True)
        for gpu in range(8):
            gx = x + 18 + (gpu % 4) * 56
            gy = 251 + (gpu // 4) * 72
            draw.rounded_rectangle((gx, gy, gx + 48, gy + 55), 7, fill=light, outline=color, width=2)
            center(draw, (gx, gy, gx + 48, gy + 55), str(gpu), 20, fill=color, bold=True, latin=True)
        center(draw, (x + 12, 401, x + card_w - 12, 438), "8×H20-3e · TP8", 20, fill=INK, bold=True, latin=True)
        if rank < 3:
            ax = x + card_w + 3
            draw.line((ax, 307, ax + card_gap - 6, 307), fill=TEAL, width=4)
            draw.polygon([(ax + card_gap - 6, 300), (ax + card_gap + 2, 307), (ax + card_gap - 6, 314)], fill=TEAL)

    draw.rounded_rectangle((48, 480, 1152, 575), 18, fill=INK)
    center(draw, (65, 490, 1135, 531), "每台节点：完整 FP8 权重约 2.27 TiB", 29, fill="white", bold=True)
    center(draw, (65, 533, 1135, 566), "本地 NVMe 降低共享存储启动流量；RDMA 承担跨 Stage 激活传输", 20, fill="#C8D4E8")
    footer(draw, "拓扑示意 · 公开图不包含节点、集群、私有镜像或存储路径")
    path = DOC_OUT / "topology.png"
    image.save(path, optimize=True)
    return path


def covers():
    for square, name in ((False, "cover.png"), (True, "cover-square.png")):
        width, height = (900, 900) if square else (900, 383)
        image = Image.new("RGB", (width, height), "#F6F7FF")
        draw = ImageDraw.Draw(image)
        rail = 14 if square else 11
        for y in range(height):
            ratio = y / max(1, height - 1)
            start, end = (10, 46, 254), (112, 87, 217)
            color = tuple(round(a + (b - a) * ratio) for a, b in zip(start, end))
            draw.line((0, y, rail, y), fill=color)
        x = 62 if square else 45
        txt(draw, x, 65 if square else 35, "AI-K8S · DAY 0", 25 if square else 17, fill=BLUE, bold=True, latin=True)
        txt(draw, x, 171 if square else 92, "Qwen3.8", 74 if square else 49, fill=BLUE, bold=True, latin=True)
        txt(draw, x, 285 if square else 157, "2.4T MoE 上线实测", 53 if square else 34, bold=True)
        txt(draw, x, 382 if square else 214, "32×H20-3e · SGLang × vLLM", 30 if square else 20, fill=PURPLE, bold=True, latin=True)
        txt(draw, x, 454 if square else 260, "部署 · 吞吐 · 延迟 · RDMA", 27 if square else 19, fill=MUTED)

        if square:
            gx0, gy0, cell_w, cell_h = 66, 564, 91, 70
            for i in range(32):
                col, row = i % 8, i // 8
                gx, gy = gx0 + col * cell_w, gy0 + row * cell_h
                draw.rounded_rectangle((gx, gy, gx + cell_w - 12, gy + cell_h - 14), 7,
                                       fill="white", outline=BLUE if row % 2 == 0 else PURPLE, width=2)
                center(draw, (gx, gy, gx + cell_w - 12, gy + cell_h - 14), "H20", 15,
                       fill=BLUE if row % 2 == 0 else PURPLE, bold=True, latin=True)
        else:
            for node in range(4):
                col, row = node % 2, node // 2
                gx, gy = 635 + col * 112, 76 + row * 103
                color = BLUE if node % 2 == 0 else PURPLE
                draw.rounded_rectangle((gx, gy, gx + 100, gy + 88), 10, fill="white", outline=color, width=2)
                center(draw, (gx, gy + 6, gx + 100, gy + 50), f"Stage {node}", 15, fill=color, bold=True, latin=True)
                center(draw, (gx, gy + 42, gx + 100, gy + 80), "8×H20", 17, fill=color, bold=True, latin=True)
        if square:
            txt(draw, x, 831, "AIK8S.RUN", 20, fill=MUTED, latin=True)
        image.save(WECHAT_OUT / name, optimize=True)


def panel(draw, box, title, subtitle=""):
    draw.rounded_rectangle(box, 18, fill="white", outline=LINE, width=2)
    txt(draw, box[0] + 22, box[1] + 18, title, 24, bold=True)
    if subtitle:
        txt(draw, box[0] + 22, box[1] + 53, subtitle, 17, fill=MUTED)


def short_chart(summary):
    engines = summary["engines"]
    cases = {name: {case["case_id"]: case for case in payload["cases"]} for name, payload in engines.items()}
    concurrencies = [1, 4, 8, 16, 32]
    throughput = {name: [cases[name][f"short-128-128-c{value}"]["metrics"]["output_throughput"]["median"] for value in concurrencies] for name in engines}
    ttft = {name: [cases[name][f"short-128-128-c{value}"]["metrics"]["p95_ttft_ms"]["median"] for value in concurrencies] for name in engines}

    image = Image.new("RGB", (1200, 675), BG)
    draw = ImageDraw.Draw(image)
    txt(draw, 48, 34, "128 → 128：同一组请求下的双引擎表现", 34, bold=True)
    txt(draw, 50, 91, "固定 Token · request-rate=inf · 全部数值为三轮中位数", 19, fill=MUTED)
    left, right = (48, 140, 579, 585), (603, 140, 1152, 585)
    panel(draw, left, "输出吞吐（Token/s）")
    panel(draw, right, "P95 延迟")

    baseline, bar_top = 526, 258
    max_tps = 700
    plot_left, plot_right = 108, 548
    for step, tick in enumerate((700, 525, 350, 175, 0)):
        y = bar_top + step * (baseline - bar_top) / 4
        draw.line((plot_left, y, plot_right, y), fill="#E7EAF1", width=1)
        label_x = 72 if tick >= 100 else 79
        txt(draw, label_x, y - 9, str(tick), 13, fill=MUTED, latin=True)
    for idx, concurrency in enumerate(concurrencies):
        x = 104 + idx * 90
        for offset, (name, color) in enumerate((("sglang", BLUE), ("vllm", ORANGE))):
            value = throughput[name][idx]
            height = (value / max_tps) * (baseline - bar_top)
            xx = x + offset * 30
            draw.rounded_rectangle((xx, baseline - height, xx + 25, baseline), 5, fill=color)
            center(draw, (xx - 14, baseline - height - 27, xx + 39, baseline - height - 1), f"{value:.0f}", 13, fill=color, bold=True, latin=True)
        center(draw, (x - 5, baseline + 12, x + 60, baseline + 42), f"C{concurrency}", 17, fill=MUTED, bold=True, latin=True)
    draw.line((plot_left, baseline, plot_right, baseline), fill=LINE, width=2)

    # Keep the legend in one fixed row. The previous labels were placed above
    # the lines without visual anchors, which made them look like loose marks.
    draw.rounded_rectangle((728, 194, 1092, 230), 12, fill="#F7F8FC", outline=LINE, width=1)
    draw.line((751, 212, 781, 212), fill=BLUE, width=4)
    draw.ellipse((760, 206, 772, 218), fill=BLUE)
    txt(draw, 792, 200, "SGLang", 15, fill=BLUE, bold=True, latin=True)
    draw.line((910, 212, 940, 212), fill=ORANGE, width=4)
    draw.ellipse((919, 206, 931, 218), fill=ORANGE)
    txt(draw, 951, 200, "vLLM", 15, fill=ORANGE, bold=True, latin=True)

    plot_top = 258
    x_values = [658 + idx * 99 for idx in range(5)]
    for step in range(5):
        y = plot_top + step * (baseline - plot_top) / 4
        draw.line((650, y, 1062, y), fill="#E7EAF1", width=1)
    points = {}
    for name, color in (("sglang", BLUE), ("vllm", ORANGE)):
        points[name] = [(x, baseline - first / 1400 * (baseline - plot_top)) for x, first in zip(x_values, ttft[name])]
        draw.line(points[name], fill=color, width=4, joint="curve")
        for point in points[name]:
            draw.ellipse((point[0] - 6, point[1] - 6, point[0] + 6, point[1] + 6), fill=color)
    for idx, x in enumerate(x_values):
        center(draw, (x - 34, baseline + 12, x + 34, baseline + 42), f"C{concurrencies[idx]}", 17, fill=MUTED, bold=True, latin=True)
    txt(draw, 626, 246, "1.4 s", 14, fill=MUTED, latin=True)
    txt(draw, 638, 510, "0", 14, fill=MUTED, latin=True)
    footer(draw, "vLLM 在短请求吞吐上更高；TTFT 在 C4–C32 高于本次 SGLang 配置")
    path = DOC_OUT / "short-throughput.png"
    image.save(path, optimize=True)
    return path


def workload_chart(summary):
    cases = {name: {case["case_id"]: case for case in payload["cases"]} for name, payload in summary["engines"].items()}
    picks = [
        ("Agent 8K → 1K", "agent-8k-1k-c8", BLUE_LIGHT, BLUE),
        ("RAG 4K → 256", "rag-4k-256-c4", PURPLE_LIGHT, PURPLE),
        ("RAG 16K → 256", "rag-16k-256-c8", "#E5F8F7", TEAL),
        ("Decode 128 → 2K", "decode-128-2k-c8", "#FFF2DE", "#C46C00"),
    ]
    image = Image.new("RGB", (1200, 675), BG)
    draw = ImageDraw.Draw(image)
    txt(draw, 48, 34, "四类请求，瓶颈落在不同位置", 34, bold=True)
    txt(draw, 50, 91, "选择每类有三轮完整结果的代表并发 · 数值均为三轮中位数", 20, fill=MUTED)
    for idx, (title, case_id, light, color) in enumerate(picks):
        col, row = idx % 2, idx // 2
        x, y = 48 + col * 557, 146 + row * 205
        box = (x, y, x + 533, y + 181)
        draw.rounded_rectangle(box, 18, fill="white", outline=LINE, width=2)
        draw.rounded_rectangle((x, y, x + 16, y + 181), 8, fill=color)
        s_case, v_case = cases["sglang"][case_id], cases["vllm"][case_id]
        txt(draw, x + 34, y + 20, title, 24, bold=True)
        txt(draw, x + 383, y + 23, f"C{s_case['concurrency']} · 3 ROUNDS", 14, fill=color, bold=True, latin=True)
        txt(draw, x + 34, y + 72, "引擎", 14, fill=MUTED)
        txt(draw, x + 132, y + 72, "输出吞吐", 14, fill=MUTED)
        txt(draw, x + 272, y + 72, "P95 TTFT", 14, fill=MUTED)
        txt(draw, x + 401, y + 72, "P95 E2E", 14, fill=MUTED)
        for row_idx, (label, case, row_color) in enumerate((("SGLang", s_case, BLUE), ("vLLM", v_case, ORANGE))):
            metrics = case["metrics"]; yy = y + 105 + row_idx * 31
            txt(draw, x + 34, yy, label, 15, fill=row_color, bold=True, latin=True)
            txt(draw, x + 132, yy, f"{metrics['output_throughput']['median']:.1f} tok/s", 15, fill=INK, bold=True, latin=True)
            txt(draw, x + 272, yy, f"{metrics['p95_ttft_ms']['median'] / 1000:.2f} s", 15, fill=INK, bold=True, latin=True)
            txt(draw, x + 401, yy, f"{metrics['p95_e2el_ms']['median'] / 1000:.2f} s", 15, fill=INK, bold=True, latin=True)
        draw.rounded_rectangle((x + 32, y + 151, x + 500, y + 160), 4, fill=light)
    footer(draw, "vLLM 的 Decode 更快；16K RAG 高并发下，本次 SGLang 的 TTFT 与吞吐更占优")
    path = DOC_OUT / "workload-profile.png"
    image.save(path, optimize=True)
    return path


def context_chart(summary):
    image = Image.new("RGB", (1200, 675), BG)
    draw = ImageDraw.Draw(image)
    txt(draw, 48, 34, "262K 上下文：配置上限、真实输入、召回结果分开记", 34, bold=True)
    txt(draw, 50, 91, "每档重启服务 · Needle 位于文档 50% 位置 · Token 数以服务端 Usage 为准", 20, fill=MUTED)
    contexts = {name: {row["configured_context_tokens"]: row for row in engine["contexts"]} for name, engine in summary["engines"].items()}
    colors = ((BLUE_LIGHT, BLUE), (PURPLE_LIGHT, PURPLE), ("#E5F8F7", TEAL))
    for idx, (context_value, (light, color)) in enumerate(zip((65536, 131072, 262144), colors)):
        x = 48 + idx * 368
        draw.rounded_rectangle((x, 161, x + 344, 547), 18, fill="white", outline=LINE, width=2)
        draw.rounded_rectangle((x, 161, x + 344, 230), 18, fill=light)
        draw.rectangle((x, 208, x + 344, 230), fill=light)
        context_labels = {65536: "64K Context", 131072: "128K Context", 262144: "262K Context"}
        context_label = context_labels[context_value]
        center(draw, (x + 10, 169, x + 334, 220), context_label, 27, fill=color, bold=True, latin=True)
        for row_idx, (name, label, row_color) in enumerate((("sglang", "SGLang", BLUE), ("vllm", "vLLM", ORANGE))):
            row = contexts[name][context_value]; yy = 270 + row_idx * 104
            txt(draw, x + 29, yy, label, 19, fill=row_color, bold=True, latin=True)
            status = row["status"]
            status_label = "PASS" if status == "PASS" else ("START FAILED" if status == "FAILED" else "NOT RUN")
            status_fill = row_color if status == "PASS" else ("#C0392B" if status == "FAILED" else MUTED)
            draw.rounded_rectangle((x + 139, yy - 2, x + 310, yy + 39), 12, fill=status_fill)
            center(draw, (x + 139, yy - 2, x + 310, yy + 39), status_label, 17, fill="white", bold=True, latin=True)
            detail = f"Prompt {row['server_prompt_tokens']:,}" if status == "PASS" else ("NCCL 初始化失败" if status == "FAILED" else "前序重启失败后跳过")
            txt(draw, x + 29, yy + 50, detail, 17, fill=MUTED, bold=status != "PASS", latin=status == "PASS")
    footer(draw, "SGLang 验证到 262K；vLLM 64K 通过，128K 在本次重启时遇到 NCCL 初始化失败")
    path = DOC_OUT / "context-ladder.png"
    image.save(path, optimize=True)
    return path


def main():
    DOC_OUT.mkdir(parents=True, exist_ok=True)
    WECHAT_OUT.mkdir(parents=True, exist_ok=True)
    source = topology()
    shutil.copy2(source, WECHAT_OUT / source.name)
    summary = json.loads(SUMMARY.read_text())
    for source in (short_chart(summary), workload_chart(summary), context_chart(summary)):
        shutil.copy2(source, WECHAT_OUT / source.name)
    covers()
    (WECHAT_OUT / "visual-metadata.json").write_text(json.dumps({
        "style_reference": "MiniMax M3 body visuals",
        "palette": {"qwen_blue": BLUE, "purple": PURPLE, "accent": TEAL},
        "body_size": [1200, 675],
        "cover_sizes": [[900, 383], [900, 900]],
        "evidence_policy": "Covers are editorial; measured charts must read archived JSON. Public UI and Grafana derivatives are crop-only copies of archived screenshots; no chart data or interface content is altered.",
        "visual_review": {
            "short_chart": "axis titles, scales, legend, markers and mobile readability checked",
            "workload_chart": "labels, values and panel boundaries checked",
            "context_chart": "64K, 128K and 262K display labels checked against configured contexts",
            "topology": "stage count, GPU count and storage labels checked"
        }
    }, ensure_ascii=False, indent=2) + "\n")
    print(DOC_OUT)
    print(WECHAT_OUT)


if __name__ == "__main__":
    main()
