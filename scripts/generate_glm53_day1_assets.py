#!/usr/bin/env python3
"""Generate exact-data figures for the public GLM-5.3 H20 benchmark report."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


WIDTH = 1200
HEIGHT = 675
BG = "#F7F9FC"
INK = "#172033"
MUTED = "#64748B"
LINE = "#D7DEE9"
WHITE = "#FFFFFF"
BLUE = "#2563EB"
BLUE_LIGHT = "#EAF1FF"
ORANGE = "#F97316"
ORANGE_LIGHT = "#FFF1E8"

FONT_CN = Path("/System/Library/Fonts/Hiragino Sans GB.ttc")
FONT_LATIN = Path("/System/Library/Fonts/HelveticaNeue.ttc")


def font(size: int, *, bold: bool = False, latin: bool = False) -> ImageFont.FreeTypeFont:
    path = FONT_LATIN if latin else FONT_CN
    index = 1 if bold and path == FONT_CN else 0
    if not path.exists():
        raise FileNotFoundError(f"font not found: {path}")
    return ImageFont.truetype(str(path), size=size, index=index)


def canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (WIDTH, HEIGHT), BG)
    return image, ImageDraw.Draw(image, "RGBA")


def rounded(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    *,
    fill: str = WHITE,
    outline: str = LINE,
    radius: int = 20,
    width: int = 2,
) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def title(draw: ImageDraw.ImageDraw, heading: str, subheading: str) -> None:
    draw.text((58, 35), heading, font=font(34, bold=True), fill=INK)
    draw.text((60, 86), subheading, font=font(18), fill=MUTED)


def centered_text(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    text_font: ImageFont.FreeTypeFont,
    fill: str,
) -> None:
    left, top, right, bottom = box
    bounds = draw.textbbox((0, 0), text, font=text_font)
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    x = (left + right - width) / 2
    y = (top + bottom - height) / 2 - bounds[1]
    draw.text((x, y), text, font=text_font, fill=fill)


def centered_multiline_text(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    text_font: ImageFont.FreeTypeFont,
    fill: str,
    *,
    spacing: int = 3,
) -> None:
    left, top, right, bottom = box
    bounds = draw.multiline_textbbox((0, 0), text, font=text_font, spacing=spacing, align="center")
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    x = (left + right - width) / 2
    y = (top + bottom - height) / 2 - bounds[1]
    draw.multiline_text((x, y), text, font=text_font, fill=fill, spacing=spacing, align="center")


def legend(draw: ImageDraw.ImageDraw) -> None:
    draw.rounded_rectangle((744, 34, 895, 74), radius=19, fill=BLUE_LIGHT)
    draw.rectangle((762, 49, 790, 60), fill=BLUE)
    draw.text((800, 42), "SGLang", font=font(16, bold=True, latin=True), fill=INK)
    draw.rounded_rectangle((912, 34, 1067, 74), radius=19, fill=ORANGE_LIGHT)
    draw.rectangle((930, 49, 958, 60), fill=ORANGE)
    draw.text((968, 42), "vLLM", font=font(16, bold=True, latin=True), fill=INK)


def load_rows(path: Path) -> dict[tuple[str, str], dict[str, float | int | str]]:
    numeric_ints = {
        "input_tokens",
        "output_tokens",
        "concurrency",
        "prompts_per_repeat",
        "repeats",
        "completed_requests",
        "failed_requests",
    }
    rows: dict[tuple[str, str], dict[str, float | int | str]] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for raw in csv.DictReader(handle):
            parsed: dict[str, float | int | str] = {}
            for key, value in raw.items():
                if key in {"engine", "case_id"}:
                    parsed[key] = value
                elif key in numeric_ints:
                    parsed[key] = int(value)
                else:
                    parsed[key] = float(value)
            lookup = (str(parsed["engine"]), str(parsed["case_id"]))
            if lookup in rows:
                raise ValueError(f"duplicate aggregate row: {lookup}")
            rows[lookup] = parsed
    expected_cases = {
        "short-128-64-c1",
        "short-128-64-c4",
        "short-128-64-c8",
        "short-128-64-c16",
        "short-128-64-c32",
        "rag-4k-128-c4",
        "rag-4k-128-c8",
        "rag-16k-256-c4",
        "rag-16k-256-c8",
    }
    expected = {(engine, case_id) for engine in ("sglang", "vllm") for case_id in expected_cases}
    if set(rows) != expected:
        raise ValueError(f"unexpected aggregate rows: missing={expected - set(rows)}, extra={set(rows) - expected}")
    if any(row["repeats"] != 3 or row["failed_requests"] != 0 for row in rows.values()):
        raise ValueError("figures require three complete zero-failure repeats per engine/case")
    return rows


def draw_y_grid(
    draw: ImageDraw.ImageDraw,
    plot: tuple[int, int, int, int],
    *,
    maximum: float,
    ticks: list[float],
    suffix: str = "",
) -> None:
    left, top, right, bottom = plot
    for value in ticks:
        y = bottom - (bottom - top) * value / maximum
        draw.line((left, y, right, y), fill=LINE, width=1)
        label = f"{value:g}{suffix}"
        bounds = draw.textbbox((0, 0), label, font=font(15, latin=True))
        draw.text((left - 14 - (bounds[2] - bounds[0]), y - 9), label, font=font(15, latin=True), fill=MUTED)


def generate_short_throughput(rows: dict, output: Path) -> None:
    image, draw = canvas()
    title(draw, "短请求输出吞吐：SGLang 全并发领先", "GLM-5.3 Native FP8 · 8×H20-3e · TP8 · 输入/输出 128/64 · 三轮中位数")
    legend(draw)

    concurrencies = [1, 4, 8, 16, 32]
    plot = (92, 162, 1128, 535)
    left, top, right, bottom = plot
    maximum = 1100
    draw_y_grid(draw, plot, maximum=maximum, ticks=[0, 200, 400, 600, 800, 1000])

    group_width = (right - left) / len(concurrencies)
    bar_width = 54
    for index, concurrency in enumerate(concurrencies):
        case_id = f"short-128-64-c{concurrency}"
        center = left + group_width * (index + 0.5)
        sglang = float(rows[("sglang", case_id)]["output_throughput"])
        vllm = float(rows[("vllm", case_id)]["output_throughput"])
        for side, (value, color) in enumerate(((sglang, BLUE), (vllm, ORANGE))):
            x1 = center - 64 + side * 72
            x2 = x1 + bar_width
            y1 = bottom - (bottom - top) * value / maximum
            draw.rounded_rectangle((x1, y1, x2, bottom), radius=8, fill=color)
            label = f"{value:.0f}"
            bounds = draw.textbbox((0, 0), label, font=font(16, bold=True, latin=True))
            draw.text(((x1 + x2 - (bounds[2] - bounds[0])) / 2, y1 - 25), label, font=font(16, bold=True, latin=True), fill=color)
        delta = (sglang / vllm - 1) * 100
        centered_text(draw, (int(center - 64), bottom + 10, int(center + 64), bottom + 39), f"C={concurrency}", font(17, bold=True, latin=True), INK)
        centered_text(draw, (int(center - 64), bottom + 38, int(center + 64), bottom + 66), f"S +{delta:.1f}%", font(14, bold=True, latin=True), BLUE)

    rounded(draw, (70, 605, 1130, 650), fill=WHITE, outline=LINE, radius=14)
    centered_text(draw, (82, 608, 1118, 647), "Output Token Throughput（tok/s）· MTP / Prefix Cache / HiCache 关闭", font(16), MUTED)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG", optimize=True)


def generate_short_ttft(rows: dict, output: Path) -> None:
    image, draw = canvas()
    title(draw, "短请求首 Token：SGLang 延迟更低", "GLM-5.3 Native FP8 · 8×H20-3e · TP8 · 输入/输出 128/64 · P50 TTFT")
    legend(draw)

    concurrencies = [1, 4, 8, 16, 32]
    plot = (102, 165, 1110, 535)
    left, top, right, bottom = plot
    maximum = 900
    draw_y_grid(draw, plot, maximum=maximum, ticks=[0, 150, 300, 450, 600, 750, 900], suffix="ms")
    xs = [left + (right - left) * index / (len(concurrencies) - 1) for index in range(len(concurrencies))]

    for engine, color, y_offset in (("sglang", BLUE, -28), ("vllm", ORANGE, -28)):
        values = [float(rows[(engine, f"short-128-64-c{concurrency}")]["p50_ttft_ms"]) for concurrency in concurrencies]
        points = [(x, bottom - (bottom - top) * value / maximum) for x, value in zip(xs, values)]
        draw.line(points, fill=color, width=5, joint="curve")
        for (x, y), value in zip(points, values):
            draw.ellipse((x - 7, y - 7, x + 7, y + 7), fill=color, outline=WHITE, width=2)
            label = f"{value:.0f}ms"
            bounds = draw.textbbox((0, 0), label, font=font(15, bold=True, latin=True))
            draw.text((x - (bounds[2] - bounds[0]) / 2, y + y_offset), label, font=font(15, bold=True, latin=True), fill=color)

    for x, concurrency in zip(xs, concurrencies):
        centered_text(draw, (int(x - 58), bottom + 13, int(x + 58), bottom + 49), f"C={concurrency}", font(17, bold=True, latin=True), INK)

    rounded(draw, (70, 592, 1130, 642), fill=WHITE, outline=LINE, radius=14)
    centered_text(draw, (82, 596, 1118, 638), "P50 TTFT 越低越好 · SGLang 相对 vLLM 低 46.0%～75.4%", font(17), MUTED)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG", optimize=True)


def draw_latency_panel(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    *,
    heading: str,
    badge: str,
    badge_color: str,
    badge_fill: str,
    maximum: float,
    ticks: list[float],
    cases: list[str],
    labels: list[str],
    metric: str,
    rows: dict,
) -> None:
    left, top, right, bottom = box
    rounded(draw, box, fill=WHITE, outline=LINE, radius=20)
    draw.text((left + 24, top + 20), heading, font=font(21, bold=True), fill=INK)
    draw.rounded_rectangle((right - 165, top + 16, right - 22, top + 52), radius=17, fill=badge_fill)
    centered_text(draw, (right - 159, top + 18, right - 28, top + 50), badge, font(15, bold=True), badge_color)

    plot = (left + 50, top + 78, right - 20, bottom - 76)
    plot_left, plot_top, plot_right, plot_bottom = plot
    for value in ticks:
        y = plot_bottom - (plot_bottom - plot_top) * value / maximum
        draw.line((plot_left, y, plot_right, y), fill=LINE, width=1)
        label = f"{value:g}"
        bounds = draw.textbbox((0, 0), label, font=font(13, latin=True))
        draw.text((plot_left - 10 - (bounds[2] - bounds[0]), y - 8), label, font=font(13, latin=True), fill=MUTED)

    group_width = (plot_right - plot_left) / len(cases)
    bar_width = 32
    for index, (case_id, label) in enumerate(zip(cases, labels)):
        center = plot_left + group_width * (index + 0.5)
        for side, (engine, color) in enumerate((("sglang", BLUE), ("vllm", ORANGE))):
            value = float(rows[(engine, case_id)][metric]) / 1000
            x1 = center - 38 + side * 43
            x2 = x1 + bar_width
            y1 = plot_bottom - (plot_bottom - plot_top) * value / maximum
            draw.rounded_rectangle((x1, y1, x2, plot_bottom), radius=6, fill=color)
            value_label = f"{value:.1f}"
            bounds = draw.textbbox((0, 0), value_label, font=font(13, bold=True, latin=True))
            draw.text(((x1 + x2 - (bounds[2] - bounds[0])) / 2, y1 - 21), value_label, font=font(13, bold=True, latin=True), fill=color)
        centered_multiline_text(draw, (int(center - 52), plot_bottom + 10, int(center + 52), bottom - 10), label, font(13, bold=True), INK)


def generate_rag_tradeoff(rows: dict, output: Path) -> None:
    image, draw = canvas()
    title(draw, "RAG：首 Token 与完成时间的取舍", "GLM-5.3 Native FP8 · 8×H20-3e · TP8 · 4K/16K 输入 · 三轮中位数")
    legend(draw)

    cases = ["rag-4k-128-c4", "rag-4k-128-c8", "rag-16k-256-c4", "rag-16k-256-c8"]
    labels = ["4K/128\nC4", "4K/128\nC8", "16K/256\nC4", "16K/256\nC8"]
    draw_latency_panel(
        draw,
        (48, 137, 585, 595),
        heading="P50 TTFT（秒）",
        badge="vLLM 更低",
        badge_color=ORANGE,
        badge_fill=ORANGE_LIGHT,
        maximum=24,
        ticks=[0, 6, 12, 18, 24],
        cases=cases,
        labels=labels,
        metric="p50_ttft_ms",
        rows=rows,
    )
    draw_latency_panel(
        draw,
        (615, 137, 1152, 595),
        heading="P50 E2E（秒）",
        badge="SGLang 更低",
        badge_color=BLUE,
        badge_fill=BLUE_LIGHT,
        maximum=42,
        ticks=[0, 10, 20, 30, 40],
        cases=cases,
        labels=labels,
        metric="p50_e2e_ms",
        rows=rows,
    )
    rounded(draw, (160, 613, 1040, 655), fill=WHITE, outline=LINE, radius=14)
    centered_text(draw, (170, 616, 1030, 652), "固定输出长度 · 左图看首 Token，右图看完整请求 · 单位：秒", font(16), MUTED)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG", optimize=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data",
        type=Path,
        default=Path("examples/glm53-day1/results/h20-fp8-baseline-median-20260830.csv"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("docs/assets/practices/glm53-day1"),
    )
    args = parser.parse_args()

    rows = load_rows(args.data)
    generate_short_throughput(rows, args.output_dir / "short-throughput-median.png")
    generate_short_ttft(rows, args.output_dir / "short-ttft-median.png")
    generate_rag_tradeoff(rows, args.output_dir / "rag-latency-tradeoff.png")


if __name__ == "__main__":
    main()
