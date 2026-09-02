#!/usr/bin/env python3
"""Generate WeChat-ready PNG assets for the DeepSeek V4 RDMA training article."""

from __future__ import annotations

import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
RESULT_PATH = (
    ROOT
    / "examples/llm-sft-lab/meaningful-sft/results"
    / "h20-deepseek-v4-rdma-tcp-20260825.json"
)
CONVERGENCE_PATH = (
    ROOT
    / "examples/llm-sft-lab/meaningful-sft/results"
    / "h20-deepseek-v4-convergence-20260825.json"
)
OUTPUT_DIR = ROOT / "articles/wechat/assets"

WIDTH = 1200
BG = "#F7F9FC"
INK = "#172033"
MUTED = "#5E6B82"
LINE = "#CBD5E1"
WHITE = "#FFFFFF"
NAVY = "#071B3C"
BLUE = "#2563EB"
BLUE_DARK = "#1746A2"
BLUE_LIGHT = "#EAF2FF"
CYAN = "#06B6D4"
CYAN_LIGHT = "#E6FAFD"
GREEN = "#0F9D8A"
GREEN_LIGHT = "#E7F8F5"
ORANGE = "#F37726"
ORANGE_LIGHT = "#FFF1E8"

FONT_CN = Path("/System/Library/Fonts/Hiragino Sans GB.ttc")
FONT_LATIN = Path("/System/Library/Fonts/HelveticaNeue.ttc")


def font(size: int, *, bold: bool = False, latin: bool = False) -> ImageFont.FreeTypeFont:
    path = FONT_LATIN if latin else FONT_CN
    index = 1 if bold and path == FONT_CN else 0
    if not path.exists():
        raise FileNotFoundError(f"font not found: {path}")
    return ImageFont.truetype(str(path), size=size, index=index)


def canvas(height: int, *, color: str = BG) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (WIDTH, height), color)
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


def centered_text(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    text_font: ImageFont.FreeTypeFont,
    fill: str = INK,
    *,
    spacing: int = 7,
) -> None:
    left, top, right, bottom = box
    bounds = draw.multiline_textbbox((0, 0), text, font=text_font, spacing=spacing, align="center")
    text_width = bounds[2] - bounds[0]
    text_height = bounds[3] - bounds[1]
    x = (left + right - text_width) / 2
    y = (top + bottom - text_height) / 2 - bounds[1]
    draw.multiline_text(
        (x, y), text, font=text_font, fill=fill, spacing=spacing, align="center"
    )


def figure_title(draw: ImageDraw.ImageDraw, heading: str, subheading: str) -> None:
    draw.text((55, 36), heading, font=font(34, bold=True), fill=INK)
    draw.text((57, 86), subheading, font=font(18), fill=MUTED)


def arrow(
    draw: ImageDraw.ImageDraw,
    start: tuple[int, int],
    end: tuple[int, int],
    *,
    color: str,
    width: int = 4,
) -> None:
    draw.line((start, end), fill=color, width=width)
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    size = 13
    left = (
        end[0] - size * math.cos(angle - math.pi / 6),
        end[1] - size * math.sin(angle - math.pi / 6),
    )
    right = (
        end[0] - size * math.cos(angle + math.pi / 6),
        end[1] - size * math.sin(angle + math.pi / 6),
    )
    draw.polygon((end, left, right), fill=color)


def gpu_grid(
    draw: ImageDraw.ImageDraw,
    left: int,
    top: int,
    *,
    cell: int = 22,
    gap: int = 7,
    color: str = BLUE,
) -> None:
    for index in range(8):
        x = left + (index % 4) * (cell + gap)
        y = top + (index // 4) * (cell + gap)
        draw.rounded_rectangle((x, y, x + cell, y + cell), radius=5, fill=color)


def save(image: Image.Image, name: str) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    image.save(OUTPUT_DIR / name, format="PNG", optimize=True)


def generate_cover(summary: dict) -> None:
    image = Image.new("RGB", (900, 383), NAVY)
    draw = ImageDraw.Draw(image, "RGBA")

    draw.ellipse((600, -180, 1040, 260), fill=(37, 99, 235, 120))
    draw.ellipse((690, 170, 1010, 490), fill=(6, 182, 212, 65))
    draw.rectangle((0, 0, 900, 383), fill=(2, 12, 29, 28))

    draw.rounded_rectangle(
        (48, 34, 300, 68), radius=17, fill=(19, 57, 112, 220), outline=(89, 191, 255, 120)
    )
    centered_text(
        draw,
        (48, 34, 300, 68),
        "AI-K8S技术工程 · 训练实测",
        font(16, bold=True),
        "#B9E7FF",
    )
    draw.rectangle((48, 99, 55, 222), fill=CYAN)
    draw.text((73, 91), "DeepSeek V4 × RDMA", font=font(35, bold=True), fill=WHITE)
    draw.text((73, 143), "双机 16 卡，吞吐 +47%", font=font(32, bold=True), fill="#DDF7FF")
    draw.text((73, 221), "6 轮 A/B · 正负对照 · SwanLab", font=font(18, bold=True), fill="#9FD7FF")
    draw.text((73, 330), "aik8s.run", font=font(15, bold=True, latin=True), fill="#7DD3FC")

    node_boxes = [(575, 78, 720, 208), (726, 174, 871, 304)]
    for index, box in enumerate(node_boxes, start=1):
        rounded(draw, box, fill="#0C2B5C", outline="#75C8FF", radius=18, width=2)
        centered_text(draw, (box[0], box[1] + 8, box[2], box[1] + 37), f"Node {index}", font(15, bold=True, latin=True), "#D9F3FF")
        gpu_grid(draw, box[0] + 17, box[1] + 52, cell=20, gap=7, color=BLUE if index == 1 else CYAN)

    arrow(draw, (704, 201), (747, 185), color="#7DD3FC", width=7)
    arrow(draw, (744, 199), (701, 216), color="#7DD3FC", width=7)
    draw.rounded_rectangle((668, 303, 810, 337), radius=17, fill=(6, 182, 212, 215))
    centered_text(draw, (668, 303, 810, 337), "GDRDMA", font(16, bold=True, latin=True), WHITE)

    # Keep the exact value in the source while displaying a compact cover figure.
    assert round(summary["rdma_throughput_gain_percent"]) == 47
    save(image, "deepseek-v4-rdma-training-cover.png")


def draw_node(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    label: str,
    *,
    color: str,
) -> None:
    rounded(draw, box, fill=BLUE_LIGHT, outline="#9CB8EE", radius=16)
    centered_text(draw, (box[0], box[1] + 6, box[2], box[1] + 35), label, font(15, bold=True, latin=True), BLUE_DARK)
    gpu_grid(draw, box[0] + 21, box[1] + 47, cell=18, gap=6, color=color)


def generate_topology(result: dict) -> None:
    image, draw = canvas(700)
    figure_title(
        draw,
        "同一套 RDMA，为什么一组无收益，另一组快了 32%？",
        "决定因素不是“有没有高速网”，而是关键 Collective 是否真正跨节点",
    )

    cards = [
        {
            "x": 55,
            "title": "负对照：PP=2 / EP=8",
            "line1": "EP 与 DP 通信组留在节点内",
            "line2": "跨机主要传 Pipeline Activation",
            "result": "RDMA 慢 0.35% · 无可测收益",
            "color": ORANGE,
            "result_fill": ORANGE_LIGHT,
            "link": "PP",
        },
        {
            "x": 620,
            "title": "正向案例：PP=1 / EP=16",
            "line1": "EP 与 Dense DP 都跨两节点",
            "line2": "All-to-All 与同步进入跨机路径",
            "result": "Step -32.08% · 吞吐 +47.23%",
            "color": BLUE,
            "result_fill": GREEN_LIGHT,
            "link": "EP / DP",
        },
    ]
    for card in cards:
        x = card["x"]
        rounded(draw, (x, 135, x + 525, 640), fill=WHITE, outline=LINE, radius=22)
        draw.text((x + 28, 165), card["title"], font=font(24, bold=True), fill=INK)
        draw_node(draw, (x + 38, 245, x + 230, 380), "Node 1", color=BLUE)
        draw_node(draw, (x + 295, 245, x + 487, 380), "Node 2", color=CYAN)

        if card["link"] == "PP":
            draw.line((x + 230, 312, x + 295, 312), fill=ORANGE, width=5)
        else:
            for offset in (-20, 0, 20):
                draw.line((x + 230, 312 + offset, x + 295, 312 + offset), fill=CYAN, width=5)
        centered_text(draw, (x + 230, 213, x + 295, 252), card["link"], font(14, bold=True, latin=True), card["color"])

        centered_text(draw, (x + 28, 418, x + 497, 452), card["line1"], font(18, bold=True), INK)
        centered_text(draw, (x + 28, 456, x + 497, 490), card["line2"], font(17), MUTED)
        rounded(draw, (x + 28, 525, x + 497, 596), fill=card["result_fill"], outline=card["color"], radius=15)
        centered_text(draw, (x + 28, 525, x + 497, 596), card["result"], font(21, bold=True), card["color"])

    draw.text((55, 670), "示意图每个节点只画部分 GPU；真实实验为 2 节点 × 8 GPU。", font=font(15), fill=MUTED)
    save(image, "deepseek-v4-rdma-training-topology.png")


def generate_bandwidth(result: dict) -> None:
    image, draw = canvas(690)
    figure_title(
        draw,
        "NCCL 微基准：链路快很多，但不能直接等于训练加速比",
        "World Size 16 · 256 MiB/Rank · 三轮中位数 · 算法带宽 GB/s",
    )
    median = result["collective_microbenchmark"]["median_at_256_mib_per_rank"]
    panels = [
        ("AllReduce", median["all_reduce"], "DP / FSDP / ZeRO 常见"),
        ("All-to-All", median["all_to_all"], "MoE Expert Parallel 常见"),
    ]

    for index, (name, values, note) in enumerate(panels):
        x = 55 + index * 570
        rounded(draw, (x, 145, x + 520, 585), fill=WHITE, outline=LINE, radius=22)
        draw.text((x + 30, 177), name, font=font(27, bold=True, latin=True), fill=INK)
        draw.text((x + 30, 218), note, font=font(17), fill=MUTED)

        max_value = values["rdma_GBps"]
        rows = [
            ("TCP", values["tcp_GBps"], ORANGE, 292),
            ("RDMA", values["rdma_GBps"], CYAN, 397),
        ]
        for label, value, color, y in rows:
            draw.text((x + 30, y), label, font=font(18, bold=True, latin=True), fill=INK)
            draw.rounded_rectangle((x + 125, y - 3, x + 480, y + 34), radius=17, fill="#E8EDF4")
            bar_width = max(9, round(355 * value / max_value))
            draw.rounded_rectangle((x + 125, y - 3, x + 125 + bar_width, y + 34), radius=17, fill=color)
            value_text = f"{value:.3f}" if value < 10 else f"{value:.2f}"
            value_box = draw.textbbox((0, 0), value_text, font=font(18, bold=True, latin=True))
            text_x = min(x + 125 + bar_width + 12, x + 480 - (value_box[2] - value_box[0]))
            draw.text((text_x, y + 45), value_text, font=font(18, bold=True, latin=True), fill=color)

        rounded(draw, (x + 95, 500, x + 425, 557), fill=GREEN_LIGHT, outline="#87D7CA", radius=25)
        centered_text(
            draw,
            (x + 95, 500, x + 425, 557),
            f'RDMA / TCP = {values["rdma_to_tcp_ratio"]:.2f}×',
            font(22, bold=True, latin=True),
            GREEN,
        )

    rounded(draw, (135, 615, 1065, 665), fill=ORANGE_LIGHT, outline="#F5B183", radius=16)
    centered_text(draw, (135, 615, 1065, 665), "144.81× 是通信能力差距，不是端到端训练快 144.81×", font(20, bold=True), ORANGE)
    save(image, "deepseek-v4-rdma-training-bandwidth.png")


def generate_step_time(result: dict) -> None:
    image, draw = canvas(720)
    figure_title(
        draw,
        "真实 MoE SFT：三轮 A/B 的方向完全一致",
        "DeepSeek V4 Flash · 2 节点 × 8 GPU · PP=1 / EP=16 / Dense DP=16 · Step 6–20",
    )
    runs = result["positive_case"]["runs"]
    summary = result["positive_case"]["median_of_run_means"]
    tcp_values = [item["stable_mean_seconds_per_step"] for item in runs["tcp"]]
    rdma_values = [item["stable_mean_seconds_per_step"] for item in runs["rdma"]]

    x0, x1 = 235, 1080
    chart_top = 170
    maximum = 5.0
    for tick in range(6):
        x = x0 + (x1 - x0) * tick / 5
        draw.line((x, chart_top, x, 535), fill=LINE, width=1)
        centered_text(draw, (int(x - 20), 542, int(x + 20), 570), str(tick), font(14, latin=True), MUTED)

    for index, (tcp, rdma) in enumerate(zip(tcp_values, rdma_values), start=1):
        base_y = 200 + (index - 1) * 110
        centered_text(draw, (65, base_y, 155, base_y + 80), f"第 {index} 轮", font(18, bold=True), INK)
        for row, (label, value, color) in enumerate((("TCP", tcp, ORANGE), ("RDMA", rdma, CYAN))):
            y = base_y + row * 42
            draw.text((165, y + 3), label, font=font(15, bold=True, latin=True), fill=INK)
            width = (x1 - x0) * value / maximum
            draw.rounded_rectangle((x0, y, x0 + width, y + 27), radius=9, fill=color)
            draw.text((x0 + width + 12, y + 2), f"{value:.3f}s", font=font(15, bold=True, latin=True), fill=color)

    rounded(draw, (55, 600, 1145, 685), fill=NAVY, outline=NAVY, radius=18)
    draw.text((90, 622), f'TCP {summary["tcp_seconds_per_step"]:.3f}s  vs  RDMA {summary["rdma_seconds_per_step"]:.3f}s', font=font(25, bold=True, latin=True), fill=WHITE)
    centered_text(draw, (705, 610, 1110, 674), f'步耗时 -{summary["rdma_step_time_reduction_percent"]:.2f}%  ·  吞吐 +{summary["rdma_throughput_gain_percent"]:.2f}%', font(23, bold=True), "#7DE3F4")
    save(image, "deepseek-v4-rdma-training-step-time.png")


def generate_convergence(convergence: dict) -> None:
    image, draw = canvas(720)
    figure_title(
        draw,
        "网络快了，不代表最后一个 Checkpoint 最好",
        "同一双机 GDRDMA 拓扑 · 60-Step LoRA · 每 10 Step 验证一次",
    )
    metrics = convergence["metrics"]
    values = metrics["validation_loss"]
    best_step = metrics["best_validation_step"]
    increase = metrics["validation_loss_increase_best_to_step60_percent"]

    x0, y0, chart_w, chart_h = 120, 165, 980, 380
    max_loss = 0.60
    for tick in range(7):
        loss = tick * 0.10
        y = y0 + chart_h - chart_h * loss / max_loss
        draw.line((x0, y, x0 + chart_w, y), fill=LINE, width=1)
        draw.text((60, y - 10), f"{loss:.1f}", font=font(14, latin=True), fill=MUTED)

    points: list[tuple[float, float]] = []
    for item in values:
        x = x0 + chart_w * (item["step"] - 10) / 50
        y = y0 + chart_h - chart_h * item["loss"] / max_loss
        points.append((x, y))
        draw.line((x, y0, x, y0 + chart_h), fill=(203, 213, 225, 150), width=1)
        centered_text(draw, (int(x - 28), y0 + chart_h + 10, int(x + 28), y0 + chart_h + 38), str(item["step"]), font(14, latin=True), MUTED)

    best_x = x0 + chart_w * (best_step - 10) / 50
    draw.rectangle((best_x, y0, x0 + chart_w, y0 + chart_h), fill=(255, 241, 232, 115))
    draw.line(points, fill=BLUE, width=6, joint="curve")
    for item, (x, y) in zip(values, points):
        color = GREEN if item["step"] == best_step else BLUE
        radius = 10 if item["step"] == best_step else 7
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color, outline=WHITE, width=3)
        label = f'{item["loss"]:.4f}'
        centered_text(draw, (int(x - 48), int(y - 45), int(x + 48), int(y - 17)), label, font(14, bold=True, latin=True), INK)

    draw.text((best_x + 20, y0 + 25), f"Step {best_step} 后开始回升", font=font(18, bold=True), fill=ORANGE)
    rounded(draw, (155, 620, 1045, 682), fill=ORANGE_LIGHT, outline="#F5B183", radius=17)
    centered_text(draw, (155, 620, 1045, 682), f"最佳 Validation 在 Step {best_step}；到 Step 60 回升 {increase:.2f}%", font(22, bold=True), ORANGE)
    save(image, "deepseek-v4-rdma-training-convergence.png")


def main() -> None:
    result = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
    convergence = json.loads(CONVERGENCE_PATH.read_text(encoding="utf-8"))
    summary = result["positive_case"]["median_of_run_means"]
    generate_cover(summary)
    generate_topology(result)
    generate_bandwidth(result)
    generate_step_time(result)
    generate_convergence(convergence)
    print(f"generated DeepSeek RDMA WeChat assets in {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
