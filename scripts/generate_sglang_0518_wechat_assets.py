#!/usr/bin/env python3
"""Generate exact, source-based figures for the SGLang v0.5.18 article."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


OUT_DIR = Path("articles/wechat/assets")
WIDTH = 1200
CHINESE = Path("/System/Library/Fonts/Hiragino Sans GB.ttc")
LATIN = Path("/System/Library/Fonts/HelveticaNeue.ttc")


def font(size: int, *, bold: bool = False, latin: bool = False) -> ImageFont.FreeTypeFont:
    path = LATIN if latin else CHINESE
    index = 1 if bold and path == LATIN else 0
    return ImageFont.truetype(str(path), size=size, index=index)


def canvas(height: int) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (WIDTH, height), "#f8fafc")
    return image, ImageDraw.Draw(image, "RGBA")


def save(image: Image.Image, name: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / name
    image.save(path, format="PNG", optimize=True)
    print(f"generated: {path}")


def claim_audit() -> None:
    image, draw = canvas(700)
    draw.rectangle((0, 0, WIDTH, 118), fill="#0f172a")
    draw.text((58, 31), "SGLang v0.5.18：标题与证据之间还差哪些限定词？", font=font(38, bold=True), fill="white")

    cards = [
        ("推理速度暴涨", "部分成立", "3 组特定模型/硬件/路径数据\n不能外推到全模型端到端吞吐", "#f59e0b"),
        ("全模型适配", "表述过度", "Release 明列 7 个新增模型\nCookbook 扩大 ≠ 任意权重都能运行", "#ef4444"),
        ("多硬件全域优化", "方向成立", "NVIDIA / AMD / NPU / XPU / MLX\n均有更新，但能力矩阵并不对称", "#2563eb"),
    ]
    for idx, (claim, verdict, detail, color) in enumerate(cards):
        left = 48 + idx * 384
        right = left + 352
        draw.rounded_rectangle((left, 158, right, 600), radius=24, fill="white", outline="#cbd5e1", width=2)
        draw.rounded_rectangle((left + 24, 188, left + 164, 230), radius=21, fill=color)
        draw.text((left + 42, 196), verdict, font=font(20, bold=True), fill="white")
        draw.text((left + 24, 272), claim, font=font(30, bold=True), fill="#0f172a")
        y = 352
        for line in detail.split("\n"):
            draw.text((left + 24, y), line, font=font(21), fill="#475569")
            y += 42
        draw.line((left + 24, 492, right - 24, 492), fill="#e2e8f0", width=2)
        footer = ["看 TTFT / TPOT / 吞吐", "看模型 × 精度 × API", "看后端独立 Cookbook"][idx]
        draw.text((left + 24, 526), footer, font=font(19, bold=True), fill=color)

    draw.text((58, 645), "依据：SGLang v0.5.18 官方 Release（2026-08-22）", font=font(18), fill="#64748b")
    save(image, "sglang-0518-claim-audit.png")


def bar(draw: ImageDraw.ImageDraw, x: int, y: int, width: int, label: str, value: str, color: str) -> None:
    draw.rounded_rectangle((x, y, x + width, y + 38), radius=8, fill=color)
    draw.text((x + 12, y + 5), label, font=font(18, bold=True), fill="white")
    draw.text((x + width + 14, y + 4), value, font=font(20, bold=True, latin=True), fill="#0f172a")


def official_numbers() -> None:
    image, draw = canvas(860)
    draw.rectangle((0, 0, WIDTH, 120), fill="#0f172a")
    draw.text((58, 28), "官方性能数字：每一个都有明确适用范围", font=font(40, bold=True), fill="white")

    draw.rounded_rectangle((50, 154, 1150, 372), radius=22, fill="white", outline="#cbd5e1", width=2)
    draw.text((82, 180), "01  启动时间｜Qwen3-32B · H100", font=font(27, bold=True), fill="#0f172a")
    bar(draw, 82, 244, 610, "默认", "84.8 s", "#94a3b8")
    bar(draw, 82, 302, 256, "Overlap", "35.6 s  ·  2.38×", "#2563eb")

    draw.rounded_rectangle((50, 400, 760, 758), radius=22, fill="white", outline="#cbd5e1", width=2)
    draw.text((82, 427), "02  Decode｜DeepSeek-V4-Pro · B200", font=font(27, bold=True), fill="#0f172a")
    draw.text((82, 489), "LMHead", font=font(21, bold=True), fill="#475569")
    bar(draw, 82, 530, 460, "优化前", "320 μs", "#94a3b8")
    bar(draw, 82, 588, 243, "优化后", "169 μs  ·  -47.2%", "#0ea5e9")
    draw.text((82, 662), "端到端 TPOT：36.97 → 35.67 ms（约 -3.5%）", font=font(22, bold=True), fill="#0f172a")
    draw.text((82, 706), "局部 Kernel 加速 ≠ 端到端等比例加速", font=font(20), fill="#64748b")

    draw.rounded_rectangle((790, 400, 1150, 758), radius=22, fill="#eff6ff", outline="#93c5fd", width=2)
    draw.text((822, 430), "03  Pure AllReduce", font=font(25, bold=True), fill="#1e3a8a")
    draw.text((822, 484), "DeepSeek-V4-Flash", font=font(21), fill="#334155")
    draw.text((822, 522), "TP4 · Blackwell", font=font(21), fill="#334155")
    draw.text((822, 560), "Decode · 小 Batch", font=font(21), fill="#334155")
    draw.text((822, 626), "最多", font=font(20), fill="#64748b")
    draw.text((822, 662), "+6.9%", font=font(52, bold=True, latin=True), fill="#2563eb")

    draw.text((58, 810), "不要把启动、Kernel 微基准与端到端吞吐混成一个“全面暴涨”结论", font=font(19), fill="#64748b")
    save(image, "sglang-0518-official-numbers.png")


def measured_benchmark() -> None:
    image, draw = canvas(1120)
    draw.rectangle((0, 0, WIDTH, 126), fill="#0f172a")
    draw.text((58, 25), "同卡实测｜SGLang 0.5.16 / 0.5.17 / 0.5.18", font=font(40, bold=True), fill="white")
    draw.text((60, 82), "单张 L20 · Qwen3.8-27B-FP8 · 官方 cu129 runtime", font=font(20), fill="#cbd5e1")

    colors = {"0.5.16": "#64748b", "0.5.17": "#f59e0b", "0.5.18": "#2563eb"}
    throughput = {
        "C1": {"0.5.16": 18.92, "0.5.17": 18.89, "0.5.18": 18.83},
        "C4": {"0.5.16": 79.59, "0.5.17": 79.64, "0.5.18": 80.20},
        "C8": {"0.5.16": 110.83, "0.5.17": 95.61, "0.5.18": 111.71},
    }

    draw.rounded_rectangle((48, 154, 812, 646), radius=22, fill="white", outline="#cbd5e1", width=2)
    draw.text((78, 180), "128 输入 / 64 输出｜Output Throughput", font=font(28, bold=True), fill="#0f172a")
    draw.text((78, 220), "C1、C4 基本持平；C8 暴露 0.5.17 容量下降", font=font(19), fill="#64748b")

    x0 = 176
    max_width = 500
    scale = max_width / 115
    for group_idx, (concurrency, values) in enumerate(throughput.items()):
        group_y = 274 + group_idx * 118
        draw.text((78, group_y + 28), concurrency, font=font(24, bold=True, latin=True), fill="#334155")
        for version_idx, version in enumerate(("0.5.16", "0.5.17", "0.5.18")):
            y = group_y + version_idx * 30
            value = values[version]
            width = int(value * scale)
            draw.rounded_rectangle((x0, y, x0 + width, y + 22), radius=6, fill=colors[version])
            draw.text((x0 + width + 10, y - 1), f"{value:.2f}", font=font(17, bold=True, latin=True), fill="#0f172a")

    legend_x = 84
    for version in ("0.5.16", "0.5.17", "0.5.18"):
        draw.rounded_rectangle((legend_x, 600, legend_x + 20, 620), radius=4, fill=colors[version])
        draw.text((legend_x + 28, 597), version, font=font(17, latin=True), fill="#475569")
        legend_x += 150

    draw.rounded_rectangle((838, 154, 1152, 646), radius=22, fill="#fff7ed", outline="#fdba74", width=2)
    draw.text((870, 184), "实际运行槽", font=font(27, bold=True), fill="#9a3412")
    slots = [("0.5.16", "6"), ("0.5.17", "5"), ("0.5.18", "6")]
    for idx, (version, value) in enumerate(slots):
        y = 252 + idx * 94
        draw.text((870, y + 11), version, font=font(21, bold=True, latin=True), fill="#475569")
        draw.text((1052, y), value, font=font(42, bold=True, latin=True), fill=colors[version])
    draw.line((870, 532, 1120, 532), fill="#fed7aa", width=2)
    draw.text((870, 554), "0.5.17：5 个运行", font=font(19, bold=True), fill="#9a3412")
    draw.text((870, 588), "C8 吞吐约低 14%", font=font(19, bold=True), fill="#9a3412")

    draw.rounded_rectangle((48, 678, 1152, 1032), radius=22, fill="white", outline="#cbd5e1", width=2)
    draw.text((78, 706), "4096 输入 / 128 输出 · C4｜P95 TPOT", font=font(28, bold=True), fill="#0f172a")
    draw.text((78, 746), "整体吞吐均约 44 tok/s，但新两版出现更长的请求级调度停顿", font=font(19), fill="#64748b")
    long_tpot = [("0.5.16", 60.75, "两轮均值"), ("0.5.17", 71.45, "单轮"), ("0.5.18", 70.97, "两轮均值")]
    long_scale = 760 / 75
    for idx, (version, value, note) in enumerate(long_tpot):
        y = 808 + idx * 62
        draw.text((78, y + 7), version, font=font(20, bold=True, latin=True), fill="#334155")
        width = int(value * long_scale)
        draw.rounded_rectangle((190, y, 190 + width, y + 34), radius=8, fill=colors[version])
        draw.text((202 + width, y + 3), f"{value:.2f} ms · {note}", font=font(18, bold=True), fill="#0f172a")

    draw.text((58, 1070), "固定模型、GPU、参数、Tokenizer、seed 与压测客户端；全部请求成功", font=font(18), fill="#64748b")
    save(image, "sglang-0518-l20-benchmark.png")
    docs_path = Path("docs/assets/practices/sglang-0518-l20/version-benchmark.png")
    docs_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(docs_path, format="PNG", optimize=True)
    print(f"generated: {docs_path}")


def cover() -> None:
    image = Image.new("RGB", (900, 383), "#0b1f44")
    draw = ImageDraw.Draw(image, "RGBA")
    draw.ellipse((650, -180, 1040, 210), fill="#2563eb")
    draw.ellipse((500, 190, 980, 610), fill="#123d8b")
    draw.text((58, 40), "AIK8S  ·  推理框架同卡实测", font=font(20), fill="#93c5fd")
    draw.text((58, 91), "SGLang 0.5.16 / 0.5.17 / 0.5.18", font=font(38, bold=True, latin=True), fill="white")
    draw.text((58, 151), "一张 L20，升级真的更快吗？", font=font(30, bold=True), fill="#dbeafe")
    draw.text((58, 213), "短请求吞吐  ·  实际运行槽  ·  4K 尾延迟", font=font(20), fill="#bfdbfe")
    button = (58, 272, 360, 326)
    button_label = "官方镜像 · 固定客户端"
    button_font = font(18, bold=True)
    draw.rounded_rectangle(button, radius=27, fill="#2563eb")
    text_box = draw.textbbox((0, 0), button_label, font=button_font)
    text_width = text_box[2] - text_box[0]
    text_height = text_box[3] - text_box[1]
    text_x = (button[0] + button[2] - text_width) / 2 - text_box[0]
    text_y = (button[1] + button[3] - text_height) / 2 - text_box[1]
    draw.text((text_x, text_y), button_label, font=button_font, fill="white")
    draw.rounded_rectangle((674, 92, 842, 260), radius=24, fill="#0f2f66", outline="#60a5fa", width=2)
    nodes = [(692, 110), (774, 110), (692, 178), (774, 178)]
    draw.line((736, 132, 774, 132), fill="#60a5fa", width=3)
    draw.line((736, 200, 774, 200), fill="#60a5fa", width=3)
    draw.line((714, 154, 714, 178), fill="#60a5fa", width=3)
    draw.line((796, 154, 796, 178), fill="#60a5fa", width=3)
    for x, y in nodes:
        draw.rounded_rectangle((x, y, x + 44, y + 44), radius=9, fill="#1d4ed8", outline="#93c5fd", width=2)
        draw.ellipse((x + 15, y + 15, x + 29, y + 29), fill="#dbeafe")
    draw.text((791, 232), "SGL", font=font(15, bold=True, latin=True), fill="white")
    path = OUT_DIR / "sglang-0518-cover.png"
    image.save(path, format="PNG", optimize=True)
    print(f"generated: {path}")


def main() -> None:
    cover()
    claim_audit()
    official_numbers()
    measured_benchmark()


if __name__ == "__main__":
    main()
