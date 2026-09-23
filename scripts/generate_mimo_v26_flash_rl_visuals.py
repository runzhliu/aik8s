#!/usr/bin/env python3
"""Generate deterministic MiMo-V2.6-Flash-RL article visuals."""
from pathlib import Path
import shutil
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs/assets/practices/mimo-v26-flash-rl-h20-day0"
WECHAT = ROOT / "articles/wechat/assets/mimo-v26-flash-rl-h20-day0"

W, H = 1200, 675
BG = "#F7F9FD"
WHITE = "#FFFFFF"
INK = "#27324D"
MUTED = "#7A849D"
LINE = "#D9E1F0"
BLUE = "#2457E6"
BLUE_SOFT = "#EAF0FF"
ORANGE = "#F59E0B"
ORANGE_SOFT = "#FFF4DC"
XIAOMI = "#FF6900"
GREEN = "#159B6B"
RED = "#E25555"
PURPLE = "#7B5CE1"
CN_FONT = "/System/Library/Fonts/Hiragino Sans GB.ttc"
EN_FONT = "/System/Library/Fonts/HelveticaNeue.ttc"


def font(size, numeric=False):
    return ImageFont.truetype(EN_FONT if numeric else CN_FONT, size)


def text(draw, xy, value, size=24, color=INK, numeric=False, anchor=None):
    draw.text(xy, value, font=font(size, numeric), fill=color, anchor=anchor)


def centered(draw, box, value, size=24, color=INK, numeric=False):
    x1, y1, x2, y2 = box
    f = font(size, numeric)
    b = draw.textbbox((0, 0), value, font=f)
    draw.text(((x1 + x2 - (b[2]-b[0]))/2, (y1 + y2 - (b[3]-b[1]))/2-b[1]), value, font=f, fill=color)


def canvas(title, subtitle):
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    text(d, (62, 38), title, 34)
    text(d, (62, 91), subtitle, 19, MUTED)
    return im, d


def card(draw, box, fill=WHITE, outline=LINE, radius=18, width=2):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def save(im, name):
    DOC.mkdir(parents=True, exist_ok=True)
    WECHAT.mkdir(parents=True, exist_ok=True)
    path = DOC / name
    im.save(path, optimize=True)
    shutil.copy2(path, WECHAT / name)


def model_card():
    im, d = canvas("MiMo-V2.6-Flash-RL：一个模型，四类输入", "官方模型卡参数 · 稀疏 MoE · 原生文本、图片、视频与音频")
    card(d, (62, 145, 1138, 550))
    text(d, (95, 177), "309B", 54, XIAOMI, True)
    text(d, (95, 240), "总参数", 21, MUTED)
    text(d, (310, 177), "15B", 54, XIAOMI, True)
    text(d, (310, 240), "每 Token 激活参数", 21, MUTED)
    text(d, (545, 177), "48", 54, XIAOMI, True)
    text(d, (545, 240), "Transformer 层", 21, MUTED)
    text(d, (735, 177), "1M", 54, XIAOMI, True)
    text(d, (735, 240), "官方上下文长度", 21, MUTED)
    text(d, (930, 177), "7", 54, XIAOMI, True)
    text(d, (930, 240), "MTP 单次预测 Token", 21, MUTED)

    items = [("文本", BLUE, "推理 / 工具"), ("图片", ORANGE, "视觉理解"), ("视频", PURPLE, "时序理解"), ("音频", GREEN, "语音输入")]
    for i, (name, color, desc) in enumerate(items):
        x = 95 + i * 258
        card(d, (x, 323, x+222, 493), fill="#FBFCFF")
        d.ellipse((x+20, 345, x+70, 395), fill=color)
        text(d, (x+88, 345), name, 27, color)
        text(d, (x+88, 385), desc, 18, MUTED)
        text(d, (x+20, 446), "原生统一接口", 18, INK)
    centered(d, (62, 576, 1138, 635), "256 个专家 · Top-8 路由 · 39 层滑窗注意力 + 9 层全局注意力", 22, INK)
    save(im, "model-overview.png")


def deployment_profiles():
    im, d = canvas("两套部署画像：卡数和并行策略不同", "这是两种可运行配置，不是同卡数的引擎排行榜")
    specs = [
        ("SGLang", BLUE, BLUE_SOFT, "8 × H20-3e", ["TP8 · DP2", "上下文 32K", "Max Running Requests 64", "Prefix Cache：关闭"]),
        ("vLLM", ORANGE, ORANGE_SOFT, "4 × H20-3e", ["TP4", "上下文 32K", "GPU Memory Utilization 0.90", "Prefix Cache：关闭"]),
    ]
    for i, (name, color, soft, gpu, rows) in enumerate(specs):
        x = 62 + i * 552
        card(d, (x, 145, x+524, 555), fill=WHITE)
        d.rounded_rectangle((x+1, 146, x+523, 225), radius=17, fill=soft)
        text(d, (x+30, 168), name, 31, color)
        text(d, (x+310, 168), gpu, 27, color, True)
        for j, row in enumerate(rows):
            y = 270 + j*62
            d.ellipse((x+32, y+7, x+46, y+21), fill=color)
            text(d, (x+66, y), row, 23, INK)
        text(d, (x+30, 506), "正式压测均保留三轮与失败分母", 18, MUTED)
    centered(d, (62, 584, 1138, 635), "总吞吐受 GPU 数量、TP/DP、调度与 Kernel 共同影响；本文同时报告资源配置。", 21, MUTED)
    save(im, "deployment-profiles.png")


def throughput_chart():
    im, d = canvas("三类负载的输出吞吐", "三轮有效结果中位数 · Token/s · 蓝色 SGLang 8 卡，橙色 vLLM 4 卡")
    panels = [
        ("1K → 128", [76.9, 490.3, 970.4], [156.8, 469.4, 657.7], 1050),
        ("8K → 128", [57.6, 169.4, 224.0], [85.5, 132.0, 144.4], 250),
        ("1K → 512", [78.4, 609.9, 1528.8], [183.3, 653.8, 1042.4], 1650),
    ]
    for p, (title, s, v, ymax) in enumerate(panels):
        x0 = 62 + p*365
        card(d, (x0, 145, x0+340, 570))
        centered(d, (x0+10, 160, x0+330, 200), title, 25, INK)
        plot_top, plot_bottom = 235, 495
        d.line((x0+44, plot_bottom, x0+314, plot_bottom), fill=LINE, width=2)
        for j, c in enumerate(["C1", "C8", "C32"]):
            cx = x0 + 74 + j*86
            bh_s = (s[j]/ymax)*230
            bh_v = (v[j]/ymax)*230
            d.rounded_rectangle((cx-20, plot_bottom-bh_s, cx, plot_bottom), radius=4, fill=BLUE)
            d.rounded_rectangle((cx+4, plot_bottom-bh_v, cx+24, plot_bottom), radius=4, fill=ORANGE)
            text(d, (cx-10, plot_bottom-bh_s-14), f"{s[j]:.0f}", 15, BLUE, True, "ms")
            text(d, (cx+14, plot_bottom-bh_v-14), f"{v[j]:.0f}", 15, ORANGE, True, "ms")
            centered(d, (cx-28, 510, cx+32, 542), c, 17, MUTED, True)
    d.rounded_rectangle((420, 600, 446, 616), radius=5, fill=BLUE)
    text(d, (458, 594), "SGLang 8 卡", 18, MUTED)
    d.rounded_rectangle((645, 600, 671, 616), radius=5, fill=ORANGE)
    text(d, (683, 594), "vLLM 4 卡", 18, MUTED)
    save(im, "core-throughput.png")


def long_context():
    im, d = canvas("24K 输入：能完成，与适合交互，是两件事", "输入 24,576 Token、输出 128 Token · TTFT 为三轮 P95 中位数")
    # SGLang panel
    card(d, (62, 145, 575, 565))
    text(d, (92, 174), "SGLang · 8 卡", 28, BLUE)
    rows = [("C1", "24/24", "1.88 s", GREEN), ("C8", "8/32", "无有效整轮", RED), ("C32", "未执行", "—", MUTED)]
    for i, (c, ok, ttft, color) in enumerate(rows):
        y = 250+i*90
        text(d, (98, y), c, 23, INK, True)
        text(d, (205, y), ok, 28, color, ok[0].isdigit())
        text(d, (360, y), ttft, 22, color, ttft[0].isdigit() or ttft == "—")
        if i < 2: d.line((95, y+56, 540, y+56), fill=LINE, width=1)
    text(d, (98, 506), "C8 两轮各有 12/16 失败，保留原分母", 18, MUTED)

    card(d, (625, 145, 1138, 565))
    text(d, (655, 174), "vLLM · 4 卡", 28, ORANGE)
    rows = [("C1", "24/24", 2.64), ("C8", "48/48", 19.54), ("C32", "192/192", 74.42)]
    maxv = 80
    for i, (c, ok, sec) in enumerate(rows):
        y = 245+i*92
        text(d, (660, y), c, 23, INK, True)
        text(d, (748, y), ok, 23, GREEN, True)
        bx = 855
        width = 225*sec/maxv
        d.rounded_rectangle((bx, y+3, bx+width, y+28), radius=6, fill=ORANGE)
        text(d, (1125, y), f"{sec:.2f}s", 19, ORANGE, True, "ra")
    text(d, (660, 506), "C32 完成，但 P95 首 Token 等待约 74.4 秒", 18, MUTED)
    centered(d, (62, 595, 1138, 635), "服务窗口设为 32K；官方 1M 上下文没有在本轮验证。", 21, INK)
    save(im, "long-context.png")


def slo_chart():
    im, d = canvas("SGLang 限速扫描：请求率上升，首 Token 等待加速扩大", "8K → 128 · 每档 3 轮 · 所有 2,397 个请求完成")
    card(d, (62, 145, 1138, 565))
    xs = [200, 560, 920]
    achieved = [0.866, 1.379, 1.644]
    ttft = [1.94, 3.55, 26.85]
    labels = ["0.5×", "0.8×", "1.1×"]
    # Throughput bars
    for i, x in enumerate(xs):
        h = achieved[i]/1.8*220
        d.rounded_rectangle((x-45, 470-h, x+5, 470), radius=8, fill=BLUE)
        text(d, (x-20, 450-h), f"{achieved[i]:.2f}", 21, BLUE, True, "ms")
        centered(d, (x-75, 485, x+75, 520), labels[i], 20, MUTED, True)
    # TTFT line on right scale, normalized to 30 s
    pts = []
    for i, x in enumerate(xs):
        y = 470-ttft[i]/30*250
        pts.append((x+35, y))
    d.line(pts, fill=PURPLE, width=5)
    for (x, y), v in zip(pts, ttft):
        d.ellipse((x-8, y-8, x+8, y+8), fill=PURPLE)
        text(d, (x, y-22), f"{v:.2f}s", 19, PURPLE, True, "ms")
    text(d, (105, 188), "蓝柱：达成请求率（req/s）", 19, BLUE)
    text(d, (420, 188), "紫线：P95 TTFT（秒）", 19, PURPLE)
    text(d, (105, 540), "0.5× / 0.8× / 1.1× 以 8K/C32 校准吞吐为基准；不是生产容量百分比。", 18, MUTED)
    save(im, "sglang-slo.png")


def covers():
    WECHAT.mkdir(parents=True, exist_ok=True)
    # Horizontal
    im = Image.new("RGB", (900, 383), "#FFF7F2")
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, 13, 383), fill=XIAOMI)
    text(d, (46, 34), "AI-K8S · DAY 0", 18, XIAOMI)
    text(d, (46, 93), "MiMo-V2.6-Flash-RL", 43, XIAOMI)
    text(d, (46, 169), "4 卡与 8 卡，两种部署画像", 34, INK)
    text(d, (46, 266), "SGLang / vLLM · H20-3e", 24, XIAOMI)
    text(d, (46, 316), "多模态验证 · 核心压测 · 长上下文", 19, MUTED)
    for i in range(8):
        x = 672 + (i%4)*49; y = 80+(i//4)*82
        d.rounded_rectangle((x, y, x+39, y+58), radius=7, fill=WHITE, outline="#F3C3A7", width=2)
        centered(d, (x, y, x+39, y+58), "H20", 10, XIAOMI)
    im.save(WECHAT / "cover.png", optimize=True)

    im = Image.new("RGB", (900, 900), "#FFF7F2")
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, 15, 900), fill=XIAOMI)
    text(d, (65, 66), "AI-K8S · DAY 0", 25, XIAOMI)
    text(d, (65, 170), "MiMo-V2.6", 68, XIAOMI)
    text(d, (65, 263), "Flash-RL", 68, XIAOMI)
    text(d, (65, 390), "4 卡与 8 卡", 54, INK)
    text(d, (65, 475), "两种部署画像", 47, INK)
    for i in range(8):
        x = 68 + (i%4)*190; y = 605+(i//4)*82
        d.rounded_rectangle((x, y, x+155, y+62), radius=9, fill=WHITE, outline="#F3C3A7", width=2)
        centered(d, (x, y, x+155, y+62), "H20-3e", 22, XIAOMI)
    text(d, (65, 805), "SGLang / vLLM · 多模态 · 长上下文", 25, MUTED)
    im.save(WECHAT / "cover-square.png", optimize=True)


def main():
    model_card()
    deployment_profiles()
    throughput_chart()
    long_context()
    slo_chart()
    covers()
    for source, name in [
        (ROOT / ".local/mimo-v26-flash-rl-day0/evidence/grafana/raw/sglang-resource-light.png", "grafana-sglang-light.png"),
        (ROOT / ".local/mimo-v26-flash-rl-day0/evidence/grafana/raw/vllm-no-prefix-node6-light.png", "grafana-vllm-light.png"),
        (ROOT / ".local/mimo-v26-flash-rl-day0/evidence/openwebui/mimo-v26-model-selector-light.png", "openwebui-registration-light.png"),
    ]:
        if source.exists():
            shutil.copy2(source, DOC / name)
            shutil.copy2(source, WECHAT / name)
    print(DOC)
    print(WECHAT)


if __name__ == "__main__":
    main()
