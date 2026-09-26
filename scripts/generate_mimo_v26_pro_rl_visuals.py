#!/usr/bin/env python3
"""Render MiMo-V2.6-Pro-RL figures from the public benchmark summary."""

import json
import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs/assets/practices/mimo-v26-pro-rl-h20"
WECHAT = ROOT / "articles/wechat/assets/mimo-v26-pro-rl-h20"
DATA = json.loads((DOC / "benchmark-summary.json").read_text())
W, H = 1200, 675
BG, WHITE, INK, MUTED, LINE = "#F7F9FD", "#FFFFFF", "#27324D", "#758098", "#DCE4F0"
ORANGE, SOFT, BLUE, GREEN = "#FF6900", "#FFF1E8", "#2457E6", "#159B6B"
CN = "/System/Library/Fonts/Hiragino Sans GB.ttc"
EN = "/System/Library/Fonts/HelveticaNeue.ttc"


def font(size, number=False):
    return ImageFont.truetype(EN if number else CN, size)


def label(draw, xy, value, size=22, color=INK, number=False, anchor=None):
    draw.text(xy, value, font=font(size, number), fill=color, anchor=anchor)


def card(draw, box, color=WHITE):
    draw.rounded_rectangle(box, radius=18, fill=color, outline=LINE, width=2)


def frame(title, subtitle):
    image = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(image)
    label(draw, (62, 39), title, 34)
    label(draw, (62, 94), subtitle, 19, MUTED)
    return image, draw


def save(image, filename):
    DOC.mkdir(parents=True, exist_ok=True)
    WECHAT.mkdir(parents=True, exist_ok=True)
    image.save(DOC / filename, optimize=True)
    shutil.copy2(DOC / filename, WECHAT / filename)


def row(case, concurrency):
    return next(x for x in DATA["workloads"] if x["case"] == case and x["concurrency"] == concurrency)


def overview():
    image, draw = frame("MiMo-V2.6-Pro-RL：旗舰 MoE 的部署轮廓", "模型规模来自官方模型卡；运行范围来自本轮八卡实测")
    values = [("1.02T", "总参数"), ("42B", "每 Token 激活"), ("70", "主干层数"), ("384", "路由专家"), ("1M", "官方上下文")]
    for i, (value, caption) in enumerate(values):
        x = 62 + i * 218
        card(draw, (x, 156, x + 198, 322))
        label(draw, (x + 18, 186), value, 44, ORANGE, True)
        label(draw, (x + 18, 258), caption, 20, MUTED)
    card(draw, (62, 359, 1138, 570), SOFT)
    label(draw, (92, 389), "这轮实际验证", 27, ORANGE)
    label(draw, (92, 444), "8 × H20-3e · TP8 · 32K 服务窗口", 31, INK)
    label(draw, (92, 511), "文本 / 工具 / 图片验收；未启用推测解码", 22, MUTED)
    label(draw, (62, 618), "官方 1M 能力与本轮 32K 服务窗口是不同口径。", 20, MUTED)
    save(image, "model-overview.png")


def throughput():
    image, draw = frame("八卡 vLLM：并发提高后的输出吞吐", "固定合成输入 · 每档三轮正式测试中位数 · 输出 Token/s")
    for idx, (case, title, max_value) in enumerate((("short", "1K 输入 → 128 输出", 1150), ("decode", "1K 输入 → 512 输出", 1150))):
        left = 62 + idx * 552
        card(draw, (left, 153, left + 524, 566))
        label(draw, (left + 28, 178), title, 26)
        chart_bottom, chart_top = 481, 249
        for tick in (0, 500, 1000):
            y = chart_bottom - tick / max_value * (chart_bottom - chart_top)
            draw.line((left + 68, y, left + 490, y), fill=LINE, width=1)
            label(draw, (left + 16, y - 13), str(tick), 15, MUTED, True)
        for i, concurrency in enumerate((1, 8, 32)):
            value = row(case, concurrency)["output_token_throughput"]
            x = left + 111 + i * 143
            bar_height = value / max_value * (chart_bottom - chart_top)
            draw.rounded_rectangle((x, chart_bottom - bar_height, x + 57, chart_bottom), radius=7, fill=ORANGE)
            label(draw, (x + 28, chart_bottom - bar_height - 31), f"{value:.0f}", 23, ORANGE, True, "mm")
            label(draw, (x + 28, 505), f"C{concurrency}", 19, MUTED, True, "mm")
    label(draw, (62, 610), "36/36 轮、1056/1056 请求成功；C32 的吞吐提升伴随更长的首 Token 等待。", 21, MUTED)
    save(image, "core-throughput.png")


def long_context():
    image, draw = frame("24K 输入：全部完成，等待时间却急剧扩大", "24,576 → 128 Token · 八卡 vLLM · 三轮 P95 中位数 · 秒")
    card(draw, (62, 150, 1138, 562))
    label(draw, (95, 180), "首 Token 等待（TTFT）", 21, BLUE)
    label(draw, (471, 180), "完整响应（E2E）", 21, ORANGE)
    bottom, top, scale = 471, 241, 220
    for tick in (0, 50, 100, 150, 200):
        y = bottom - tick / scale * (bottom - top)
        draw.line((175, y, 1086, y), fill=LINE, width=1)
        label(draw, (105, y - 13), str(tick), 17, MUTED, True)
    for i, concurrency in enumerate((1, 8, 32)):
        r = row("long", concurrency)
        x = 258 + i * 290
        for dx, metric, color in ((0, "ttft_s_p95", BLUE), (82, "token_e2e_s_p95", ORANGE)):
            value = r[metric]
            height = value / scale * (bottom - top)
            draw.rounded_rectangle((x + dx, bottom - max(height, 3), x + dx + 68, bottom), radius=6, fill=color)
            label(draw, (x + dx + 34, bottom - max(height, 3) - 29), f"{value:.1f}", 20, color, True, "mm")
        label(draw, (x + 76, 504), f"C{concurrency}", 21, MUTED, True, "mm")
    label(draw, (62, 608), "C32：192/192 请求完成，但 P95 TTFT 约 96 秒，P95 E2E 约 196 秒。", 21, MUTED)
    save(image, "long-context.png")


def covers():
    WECHAT.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (900, 383), "#FFF7F2")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 14, 383), fill=ORANGE)
    label(draw, (51, 33), "AI-K8S · 首测", 19, ORANGE)
    label(draw, (51, 91), "MiMo-V2.6-Pro-RL", 42, ORANGE)
    label(draw, (51, 169), "八张 H20-3e 的实测", 34, INK)
    label(draw, (51, 268), "部署 · 正确性 · 吞吐与长上下文", 23, MUTED)
    for i in range(8):
        x, y = 657 + i % 4 * 52, 71 + i // 4 * 91
        draw.rounded_rectangle((x, y, x + 42, y + 64), radius=8, fill=WHITE, outline="#F3C3A7", width=2)
        label(draw, (x + 21, y + 32), "H20", 10, ORANGE, True, "mm")
    image.save(WECHAT / "cover.png", optimize=True)

    image = Image.new("RGB", (900, 900), "#FFF7F2")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 16, 900), fill=ORANGE)
    label(draw, (64, 66), "AI-K8S · 首测", 26, ORANGE)
    label(draw, (64, 170), "MiMo-V2.6", 66, ORANGE)
    label(draw, (64, 265), "Pro-RL", 66, ORANGE)
    label(draw, (64, 407), "八张 H20-3e", 52, INK)
    label(draw, (64, 493), "部署与性能实测", 43, INK)
    for i in range(8):
        x, y = 66 + i % 4 * 196, 645 + i // 4 * 82
        draw.rounded_rectangle((x, y, x + 159, y + 62), radius=9, fill=WHITE, outline="#F3C3A7", width=2)
        label(draw, (x + 80, y + 31), "H20-3e", 20, ORANGE, True, "mm")
    image.save(WECHAT / "cover-square.png", optimize=True)


if __name__ == "__main__":
    overview()
    throughput()
    long_context()
    covers()
