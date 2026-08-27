#!/usr/bin/env python3
"""Generate exact-data figures for the Qwen3.8-Flash-Next H20 Day-0 article."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


OUT = Path("articles/wechat/assets")
DOCS_OUT = Path("docs/assets/practices/qwen38-flash-next-sglang")
WIDTH = 1200
CHINESE = Path("/System/Library/Fonts/Hiragino Sans GB.ttc")
LATIN = Path("/System/Library/Fonts/HelveticaNeue.ttc")

NAVY = "#0B1F44"
BLUE = "#2563EB"
CYAN = "#0891B2"
TEAL = "#0F9F8F"
ORANGE = "#F97316"
RED = "#DC2626"
GREEN = "#16A34A"
INK = "#0F172A"
MUTED = "#64748B"
GRID = "#CBD5E1"
BG = "#F8FAFC"
WHITE = "#FFFFFF"


def font(size: int, *, latin: bool = False, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = LATIN if latin else CHINESE
    index = 1 if latin and bold else 0
    return ImageFont.truetype(str(path), size=size, index=index)


def canvas(height: int = 675) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (WIDTH, height), BG)
    return image, ImageDraw.Draw(image, "RGBA")


def header(draw: ImageDraw.ImageDraw, heading: str, subtitle: str) -> None:
    draw.rectangle((0, 0, WIDTH, 124), fill=NAVY)
    draw.text((58, 24), heading, font=font(38, bold=True), fill=WHITE)
    draw.text((60, 80), subtitle, font=font(19), fill="#BFDBFE")


def save(image: Image.Image, name: str, *, copy_to_docs: bool = False) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    image.save(path, format="PNG", optimize=True)
    print(f"generated: {path}")
    if copy_to_docs:
        DOCS_OUT.mkdir(parents=True, exist_ok=True)
        docs_path = DOCS_OUT / name
        image.save(docs_path, format="PNG", optimize=True)
        print(f"generated: {docs_path}")


def center_text(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    value: str,
    text_font: ImageFont.FreeTypeFont,
    fill: str,
) -> None:
    left, top, right, bottom = box
    bounds = draw.textbbox((0, 0), value, font=text_font)
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    x = (left + right - width) / 2 - bounds[0]
    y = (top + bottom - height) / 2 - bounds[1]
    draw.text((x, y), value, font=text_font, fill=fill)


def cover() -> None:
    image = Image.new("RGB", (900, 383), NAVY)
    draw = ImageDraw.Draw(image, "RGBA")
    draw.ellipse((650, -180, 1040, 210), fill=BLUE)
    draw.ellipse((525, 205, 990, 640), fill="#123D8B")
    draw.text((56, 36), "AIK8S  ·  DAY 0 推理实测", font=font(19), fill="#93C5FD")
    draw.text((56, 82), "Qwen3.8-Flash-Next", font=font(39, latin=True, bold=True), fill=WHITE)
    draw.text((56, 137), "4×H20 跑通原生 262K", font=font(31, bold=True), fill="#DBEAFE")
    draw.text((56, 196), "BF16 / FP8 · PLE · MTP · 长短混部", font=font(20), fill="#BFDBFE")
    button = (56, 266, 364, 322)
    draw.rounded_rectangle(button, radius=28, fill=BLUE)
    center_text(draw, button, "SGLang Day-0 实战", font(18, bold=True), WHITE)

    draw.rounded_rectangle((682, 94, 844, 256), radius=24, fill="#0F2F66", outline="#60A5FA", width=2)
    nodes = [(700, 112), (776, 112), (700, 181), (776, 181)]
    draw.line((738, 133, 776, 133), fill="#60A5FA", width=3)
    draw.line((738, 202, 776, 202), fill="#60A5FA", width=3)
    draw.line((719, 154, 719, 181), fill="#60A5FA", width=3)
    draw.line((795, 154, 795, 181), fill="#60A5FA", width=3)
    for x, y in nodes:
        draw.rounded_rectangle((x, y, x + 38, y + 42), radius=8, fill="#1D4ED8", outline="#93C5FD", width=2)
        draw.ellipse((x + 12, y + 14, x + 26, y + 28), fill="#DBEAFE")
    draw.text((790, 229), "H20", font=font(14, latin=True, bold=True), fill=WHITE)
    save(image, "qwen38-flash-next-h20-cover.png")


def topology() -> None:
    image, draw = canvas()
    header(draw, "Day-0 实测路径", "官方 BF16 / FP8 Checkpoint 与 SGLang 专用镜像；不使用官方 H200/B200 数字代替")
    cards = [
        (50, 192, 290, 508, "模型", ["176B Serving Body", "约 6B Active / Token", "BF16 335 / FP8 173 GiB", "原生 262K Context"], BLUE, "#EFF6FF"),
        (335, 192, 575, 508, "框架", ["SGLang Day-0", "QSA + GDN", "PLE Offload", "OpenAI-compatible"], CYAN, "#ECFEFF"),
        (620, 192, 860, 508, "硬件", ["4 × H20 141 GB", "TP4 / EP4", "单机 SM90", "约 15.25 GiB 余量"], ORANGE, "#FFF7ED"),
        (905, 192, 1150, 508, "验证", ["Thinking / Tool", "Vision / OpenWebUI", "250K Needle 9/9", "PLE / MTP A/B"], TEAL, "#F0FDFA"),
    ]
    for left, top, right, bottom, title, lines, color, tint in cards:
        draw.rounded_rectangle((left, top, right, bottom), radius=22, fill=WHITE, outline=GRID, width=2)
        draw.rounded_rectangle((left, top, right, top + 64), radius=22, fill=tint)
        draw.rectangle((left, top + 42, right, top + 64), fill=tint)
        draw.rectangle((left, top, left + 7, bottom), fill=color)
        draw.text((left + 25, top + 15), title, font=font(26, bold=True), fill=INK)
        for idx, line in enumerate(lines):
            draw.text((left + 25, top + 94 + idx * 48), line, font=font(19), fill=MUTED)
    for x in (306, 591, 876):
        draw.line((x, 350, x + 18, 350), fill="#94A3B8", width=4)
        draw.polygon(((x + 18, 350), (x + 7, 342), (x + 7, 358)), fill="#94A3B8")
    draw.text((52, 584), "边界：H20 不在官方首日签字矩阵；L20 只能通过慢速兼容回退生成。", font=font(20), fill=MUTED)
    save(image, "qwen38-flash-next-h20-topology.png")


def short_throughput() -> None:
    image, draw = canvas()
    header(draw, "短请求吞吐", "128 输入 / 64 输出；稳定态 Output Throughput，单位 tok/s")
    labels = ["C1", "C4", "C8", "C16", "C32", "C64"]
    values = [90.32, 334.95, 578.77, 864.16, 1393.73, 1860.09]
    left, top, right, bottom = 86, 180, 1138, 548
    max_value = 2000
    for tick in range(0, 2001, 500):
        y = bottom - tick / max_value * (bottom - top)
        draw.line((left, y, right, y), fill=GRID, width=1)
        draw.text((30, y - 11), str(tick), font=font(16, latin=True), fill=MUTED)
    group = (right - left) / len(values)
    for idx, value in enumerate(values):
        x1 = left + idx * group + 38
        x2 = x1 + 95
        y1 = bottom - value / max_value * (bottom - top)
        color = ORANGE if idx == len(values) - 1 else BLUE
        draw.rounded_rectangle((x1, y1, x2, bottom), radius=10, fill=color)
        label = f"{value:,.0f}"
        bounds = draw.textbbox((0, 0), label, font=font(17, latin=True, bold=True))
        draw.text(((x1 + x2 - (bounds[2] - bounds[0])) / 2, y1 - 30), label, font=font(17, latin=True, bold=True), fill=INK)
        center_text(draw, (x1 - 12, bottom + 14, x2 + 12, bottom + 52), labels[idx], font(17, latin=True, bold=True), MUTED)
    draw.rounded_rectangle((748, 139, 1138, 174), radius=17, fill="#FFF7ED")
    center_text(draw, (748, 139, 1138, 174), "C64 吞吐最高，但 P95 TTFT 已到 1.32s", font(17), ORANGE)
    draw.text((86, 616), "request-rate=inf 用于找短时饱和点，不等于生产可承诺 QPS。", font=font(18), fill=MUTED)
    save(image, "qwen38-flash-next-h20-throughput.png")


def long_context() -> None:
    image, draw = canvas()
    header(draw, "原生 262K：容量、延迟与正确性要分开看", "单并发 128 输出的 P95 TTFT；250K 另做精确 Tokenizer 单针检索")
    labels = ["4K", "32K", "64K", "128K", "261K"]
    values = [0.254, 1.862, 3.722, 7.948, 19.164]
    left, top, right, bottom = 84, 184, 756, 530
    max_value = 20
    for tick in (0, 5, 10, 15, 20):
        y = bottom - tick / max_value * (bottom - top)
        draw.line((left, y, right, y), fill=GRID, width=1)
        draw.text((40, y - 10), f"{tick}s", font=font(15, latin=True), fill=MUTED)
    points = []
    gap = (right - left) / (len(values) - 1)
    for idx, value in enumerate(values):
        x = left + idx * gap
        y = bottom - value / max_value * (bottom - top)
        points.append((x, y))
    draw.line(points, fill=ORANGE, width=6)
    for (x, y), label, value in zip(points, labels, values):
        draw.ellipse((x - 8, y - 8, x + 8, y + 8), fill=ORANGE)
        center_text(draw, (int(x - 55), int(y - 42), int(x + 55), int(y - 12)), f"{value:.2f}s", font(15, latin=True, bold=True), INK)
        center_text(draw, (int(x - 45), bottom + 14, int(x + 45), bottom + 49), label, font(16, latin=True, bold=True), MUTED)

    draw.rounded_rectangle((820, 176, 1144, 548), radius=24, fill=WHITE, outline="#86EFAC", width=2)
    draw.text((856, 205), "Needle Smoke", font=font(28, latin=True, bold=True), fill=GREEN)
    draw.text((856, 254), "精确 Prompt Token", font=font(19), fill=MUTED)
    for idx, (length, elapsed) in enumerate((("32,768", "≈2.02s"), ("131,072", "≈8.40s"), ("250,000", "≈18.90s"))):
        y = 310 + idx * 62
        draw.ellipse((856, y + 5, 874, y + 23), fill=GREEN)
        draw.text((890, y), length, font=font(20, latin=True, bold=True), fill=INK)
        draw.text((1032, y + 2), elapsed, font=font(16, latin=True), fill=MUTED)
    draw.text((856, 502), "9 / 9 正确", font=font(26, bold=True), fill=GREEN)
    draw.text((84, 620), "“能装下”不等于低 TTFT；单针通过也不等于复杂长文档推理通过。", font=font(18), fill=MUTED)
    save(image, "qwen38-flash-next-h20-long-context.png", copy_to_docs=True)


def mixed_workload() -> None:
    image, draw = canvas()
    header(draw, "长短混部的代价", "前台 128/64 @ 4 req/s；后台叠加 2 路 65K Prefill")
    draw.rounded_rectangle((70, 176, 1130, 536), radius=24, fill=WHITE, outline=GRID, width=2)
    groups = [
        ("P95 TTFT", 0.782, 7.748, "9.9×"),
        ("P95 E2E", 3.769, 10.727, "2.85×"),
    ]
    for idx, (label, base, mixed, multiple) in enumerate(groups):
        x = 116 + idx * 534
        draw.text((x, 205), label, font=font(28, latin=True, bold=True), fill=INK)
        draw.text((x, 250), "短请求独立", font=font(18), fill=MUTED)
        draw.rounded_rectangle((x + 150, 250, x + 150 + int(base / 11 * 230), 284), radius=8, fill=BLUE)
        draw.text((x + 410, 250), f"{base:.2f}s", font=font(19, latin=True, bold=True), fill=BLUE)
        draw.text((x, 322), "+ 65K Prefill", font=font(18), fill=MUTED)
        draw.rounded_rectangle((x + 150, 322, x + 150 + int(mixed / 11 * 230), 356), radius=8, fill=RED)
        draw.text((x + 410, 322), f"{mixed:.2f}s", font=font(19, latin=True, bold=True), fill=RED)
        draw.rounded_rectangle((x + 150, 405, x + 330, 468), radius=31, fill="#FEF2F2")
        center_text(draw, (x + 150, 405, x + 330, 468), multiple, font(31, latin=True, bold=True), RED)
    draw.line((590, 205, 590, 494), fill="#E2E8F0", width=2)
    draw.text((72, 594), "结论：长上下文与短 Chat 不应进入同一个无差别队列。", font=font(21, bold=True), fill=RED)
    save(image, "qwen38-flash-next-h20-mixed-workload.png", copy_to_docs=True)


def ple_mtp() -> None:
    image, draw = canvas(850)
    header(draw, "PLE 与 MTP：两个优化解决的是不同问题", "PLE 主要换容量；MTP 的收益取决于输出长度与并发")
    draw.rounded_rectangle((54, 158, 1146, 420), radius=24, fill=WHITE, outline=GRID, width=2)
    draw.text((82, 184), "PLE Offload", font=font(29, latin=True, bold=True), fill=TEAL)
    draw.text((82, 229), "把 N-gram Embedding 放到 CPU Pinned Memory", font=font(18), fill=MUTED)
    rows = [
        ("每 Rank 权重", "43.86 GiB", "32.20 GiB", "-11.66 GiB"),
        ("Token Pool", "3.179M", "3.680M", "+15.8%"),
        ("Running Requests", "507", "587", "+15.8%"),
    ]
    for idx, (label, off, on, change) in enumerate(rows):
        y = 278 + idx * 44
        draw.text((82, y), label, font=font(18), fill=INK)
        draw.text((370, y), f"Off  {off}", font=font(17, latin=True), fill=MUTED)
        draw.text((610, y), f"On  {on}", font=font(17, latin=True, bold=True), fill=TEAL)
        draw.rounded_rectangle((912, y - 4, 1088, y + 31), radius=17, fill="#ECFDF5")
        center_text(draw, (912, y - 4, 1088, y + 31), change, font(17, latin=True, bold=True), TEAL)

    draw.rounded_rectangle((54, 448, 1146, 770), radius=24, fill=WHITE, outline=GRID, width=2)
    draw.text((82, 474), "MTP / NEXTN", font=font(29, latin=True, bold=True), fill=ORANGE)
    draw.text((82, 519), "Output tok/s：普通路径 vs MTP（显式 FP32 SSM State）", font=font(18), fill=MUTED)
    cases = [("64 · C1", 90.32, 137.60), ("64 · C8", 535.12, 278.27), ("1K · C1", 114.11, 180.32), ("1K · C8", 702.56, 823.35)]
    max_value = 850
    for idx, (label, base, mtp) in enumerate(cases):
        y = 570 + idx * 45
        draw.text((82, y + 4), label, font=font(17, latin=True, bold=True), fill=INK)
        width_base = int(base / max_value * 650)
        width_mtp = int(mtp / max_value * 650)
        draw.rounded_rectangle((230, y, 230 + width_base, y + 14), radius=5, fill="#94A3B8")
        draw.rounded_rectangle((230, y + 20, 230 + width_mtp, y + 34), radius=5, fill=ORANGE)
        draw.text((905, y + 5), f"{base:.0f} vs {mtp:.0f}", font=font(16, latin=True, bold=True), fill=ORANGE if mtp >= base else RED)
    draw.text((82, 806), "MTP：低并发 / 长生成收益明显；短输出高并发可能退化。", font=font(19, bold=True), fill=ORANGE)
    save(image, "qwen38-flash-next-h20-ple-mtp.png", copy_to_docs=True)


def precision_ab() -> None:
    image, draw = canvas(900)
    header(draw, "BF16 与 FP8：容量优势不等于所有负载都更快", "同一套 4×H20、SGLang 与 TP4/EP4；短时合成 A/B，不是质量评测")

    cards = [
        (54, 158, 388, 334, "权重加载", "88.11s", "149.24s", "FP8 快 40.9%"),
        (433, 158, 767, 334, "Token Pool", "3.680M", "2.458M", "FP8 多 49.7%"),
        (812, 158, 1146, 334, "Running Requests", "587", "392", "FP8 多 49.7%"),
    ]
    for left, top, right, bottom, title, fp8, bf16, note in cards:
        draw.rounded_rectangle((left, top, right, bottom), radius=22, fill=WHITE, outline=GRID, width=2)
        center_text(draw, (left + 18, top + 15, right - 18, top + 51), title, font(20, bold=True), INK)
        draw.text((left + 30, top + 70), "FP8", font=font(17, latin=True, bold=True), fill=BLUE)
        draw.text((left + 102, top + 65), fp8, font=font(27, latin=True, bold=True), fill=BLUE)
        draw.text((left + 30, top + 111), "BF16", font=font(17, latin=True, bold=True), fill=ORANGE)
        draw.text((left + 102, top + 106), bf16, font=font(27, latin=True, bold=True), fill=ORANGE)
        draw.rounded_rectangle((left + 86, top + 143, right - 28, bottom - 10), radius=14, fill="#ECFDF5")
        center_text(draw, (left + 86, top + 143, right - 28, bottom - 10), note, font(15, bold=True), TEAL)

    draw.rounded_rectangle((54, 364, 1146, 812), radius=24, fill=WHITE, outline=GRID, width=2)
    draw.text((82, 392), "实测吞吐", font=font(27, bold=True), fill=INK)
    draw.text((82, 433), "场景", font=font(18, bold=True), fill=MUTED)
    draw.text((500, 433), "FP8", font=font(18, latin=True, bold=True), fill=BLUE)
    draw.text((680, 433), "BF16", font=font(18, latin=True, bold=True), fill=ORANGE)
    draw.text((860, 433), "观察", font=font(18, bold=True), fill=MUTED)
    rows = [
        ("128/64 · C1 输出 tok/s", "90.32", "97.16", "BF16 +7.6%"),
        ("128/64 · C8 输出 tok/s", "535.12", "531.38", "基本持平"),
        ("128/64 · C64 输出 tok/s", "1,860.09", "1,999.76", "BF16 +7.5%"),
        ("128/1K · C1 输出 tok/s", "114.11", "123.43", "BF16 +8.2%"),
        ("128/1K · C8 输出 tok/s", "702.56", "750.18", "BF16 +6.8%"),
        ("32K/128 · C1 输入 tok/s", "10,668.22", "10,329.37", "FP8 +3.3%"),
    ]
    for idx, (case, fp8, bf16, note) in enumerate(rows):
        y = 478 + idx * 51
        if idx % 2 == 0:
            draw.rounded_rectangle((76, y - 8, 1122, y + 34), radius=8, fill="#F8FAFC")
        draw.text((86, y), case, font=font(17), fill=INK)
        draw.text((500, y), fp8, font=font(17, latin=True, bold=True), fill=BLUE)
        draw.text((680, y), bf16, font=font(17, latin=True, bold=True), fill=ORANGE)
        draw.text((860, y), note, font=font(17, bold=True), fill=TEAL if "FP8" in note or "持平" in note else ORANGE)
    draw.text((58, 852), "结论：FP8 的确定性收益是容量与启动；Decode 吞吐需按业务实测，不能从精度名称直接推断。", font=font(19, bold=True), fill=MUTED)
    save(image, "qwen38-flash-next-h20-precision.png", copy_to_docs=True)


def framework_status() -> None:
    image, draw = canvas()
    header(draw, "发布当天，两个框架处于不同阶段", "截至 2026-08-27；这是带日期的上游状态，不是永久结论")
    cards = [
        (58, 174, 574, 552, "SGLang", "DAY-0 可运行", GREEN, "#F0FDF4", ["专用官方镜像", "Qwen4Exp 模型实现", "PLE / QSA / GDN", "高吞吐与低延迟配方"]),
        (626, 174, 1142, 552, "vLLM", "适配仍在进行", ORANGE, "#FFF7ED", ["模型支持 PR Open", "PLE PR Open", "Qwen4 Kernel PR Open", "不应注册为稳定生产模型"]),
    ]
    for left, top, right, bottom, name, state, color, tint, lines in cards:
        draw.rounded_rectangle((left, top, right, bottom), radius=26, fill=WHITE, outline=color, width=2)
        draw.rounded_rectangle((left + 26, top + 24, left + 205, top + 70), radius=23, fill=tint)
        center_text(draw, (left + 26, top + 24, left + 205, top + 70), state, font(18, bold=True), color)
        draw.text((left + 28, top + 102), name, font=font(42, latin=True, bold=True), fill=INK)
        for idx, line in enumerate(lines):
            y = top + 180 + idx * 48
            draw.ellipse((left + 30, y + 6, left + 44, y + 20), fill=color)
            draw.text((left + 62, y), line, font=font(20), fill=MUTED)
    draw.text((60, 612), "结论：本次 H20 Day-0 实战选择 SGLang，是当日可用性选择，不是框架永久排名。", font=font(20), fill=MUTED)
    save(image, "qwen38-flash-next-framework-status.png")


def main() -> None:
    cover()
    topology()
    short_throughput()
    long_context()
    mixed_workload()
    ple_mtp()
    precision_ab()
    framework_status()


if __name__ == "__main__":
    main()
