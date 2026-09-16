#!/usr/bin/env python3
"""Generate deterministic figures for the OpenTelemetry Kubernetes practice article."""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "docs/assets/practices/opentelemetry-kubernetes"
DATA = ASSET_DIR / "results.json"
WIDTH, HEIGHT = 1200, 675
FONT_PATH = Path("/System/Library/Fonts/Hiragino Sans GB.ttc")

BG = "#F7F8FC"
INK = "#172033"
MUTED = "#667085"
LINE = "#D9DFEA"
WHITE = "#FFFFFF"
PURPLE = "#6D4AFF"
PURPLE_LIGHT = "#F0ECFF"
ORANGE = "#F26B38"
ORANGE_LIGHT = "#FFF0E9"
BLUE = "#246BFD"
BLUE_LIGHT = "#EAF1FF"
GREEN = "#15966A"
GREEN_LIGHT = "#E7F7F0"
RED = "#D64545"
RED_LIGHT = "#FDECEC"


def font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_PATH), size=size, index=1 if bold else 0)


def canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (WIDTH, HEIGHT), BG)
    return image, ImageDraw.Draw(image, "RGBA")


def rounded(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    *,
    fill: str = WHITE,
    outline: str = LINE,
    radius: int = 18,
    width: int = 2,
) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def heading(draw: ImageDraw.ImageDraw, title: str, subtitle: str) -> None:
    draw.text((56, 32), title, font=font(34, bold=True), fill=INK)
    draw.text((58, 82), subtitle, font=font(18), fill=MUTED)


def center(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    face: ImageFont.FreeTypeFont,
    fill: str = INK,
) -> None:
    x1, y1, x2, y2 = box
    bounds = draw.textbbox((0, 0), text, font=face)
    tw, th = bounds[2] - bounds[0], bounds[3] - bounds[1]
    draw.text(((x1 + x2 - tw) / 2, (y1 + y2 - th) / 2 - bounds[1]), text, font=face, fill=fill)


def arrow(
    draw: ImageDraw.ImageDraw,
    start: tuple[int, int],
    end: tuple[int, int],
    *,
    color: str = PURPLE,
    width: int = 4,
) -> None:
    draw.line((start, end), fill=color, width=width)
    ex, ey = end
    draw.polygon([(ex, ey), (ex - 12, ey - 7), (ex - 12, ey + 7)], fill=color)


def architecture() -> None:
    image, draw = canvas()
    heading(draw, "OpenTelemetry 在 Kubernetes 的信号路径", "应用只发送 OTLP；Collector 统一补充元数据、执行策略并分流到不同后端")

    rounded(draw, (45, 126, 1155, 620), fill="#FBFCFF", outline="#BEC8DA", radius=24)
    draw.rounded_rectangle((65, 145, 235, 180), radius=16, fill=PURPLE_LIGHT)
    center(draw, (65, 145, 235, 180), "Kubernetes Cluster", font(16, bold=True), PURPLE)

    rounded(draw, (78, 220, 312, 508), outline="#C9D2E3")
    center(draw, (95, 238, 295, 272), "业务 Deployment", font(22, bold=True))
    for y, label in [(300, "App Pod A"), (390, "App Pod B")]:
        rounded(draw, (112, y, 278, y + 62), fill=BLUE_LIGHT, outline="#A9C0F4", radius=14)
        center(draw, (112, y, 278, y + 62), label, font(18, bold=True), BLUE)
    center(draw, (98, 468, 292, 492), "Trace · Metric · Log", font(15), MUTED)

    rounded(draw, (424, 204, 758, 526), fill=WHITE, outline="#BCAEFF", radius=22, width=3)
    center(draw, (445, 222, 737, 262), "Collector Gateway", font(25, bold=True), PURPLE)
    stages = [
        (292, "Receiver", "OTLP HTTP / gRPC"),
        (368, "Processor", "memory · k8s attributes · batch"),
        (444, "Exporter", "按信号分流与鉴权"),
    ]
    for y, name, detail in stages:
        rounded(draw, (468, y, 714, y + 55), fill=PURPLE_LIGHT, outline="#D4CAFF", radius=12)
        draw.text((486, y + 8), name, font=font(17, bold=True), fill=INK)
        draw.text((486, y + 31), detail, font=font(13), fill=MUTED)
    arrow(draw, (312, 365), (424, 365))
    center(draw, (320, 324, 420, 352), "OTLP", font(16, bold=True), PURPLE)

    backends = [
        (150, ORANGE_LIGHT, ORANGE, "Langfuse / Tempo", "Trace · 调用链与根因"),
        (316, BLUE_LIGHT, BLUE, "Prometheus / Grafana", "Metric · 趋势与告警"),
        (482, GREEN_LIGHT, GREEN, "Loki / Elasticsearch", "Log · 事件与检索"),
    ]
    for y, fill, color, name, detail in backends:
        rounded(draw, (866, y, 1118, y + 105), fill=fill, outline=color, radius=18)
        draw.text((888, y + 20), name, font=font(19, bold=True), fill=color)
        draw.text((888, y + 58), detail, font=font(15), fill=INK)
        arrow(draw, (758, y + 52), (866, y + 52), color=color)

    draw.text((65, 636), "原则：OTel 统一遥测格式与管道，不替代存储、查询、告警和 LLM 评估后端。", font=font(16), fill=MUTED)
    image.save(ASSET_DIR / "architecture.png", optimize=True)


def deployment_patterns() -> None:
    image, draw = canvas()
    heading(draw, "Sidecar、DaemonSet 与 Gateway 怎么选", "采集位置决定故障域、元数据完整度、资源成本和中心策略能力")
    cards = [
        (55, "Sidecar", ORANGE, ORANGE_LIGHT, ["每个 Pod 一套 Collector", "隔离强，升级跟随应用", "成本高，配置容易分裂", "适合少量强隔离工作负载"]),
        (420, "DaemonSet Agent", BLUE, BLUE_LIGHT, ["每个节点一套 Collector", "采 stdout、kubelet 与宿主指标", "天然靠近数据源", "适合节点级日志与基础指标"]),
        (785, "Gateway Deployment", PURPLE, PURPLE_LIGHT, ["集群内提供统一 OTLP 入口", "集中鉴权、过滤与采样", "需做高可用和背压保护", "适合应用 Trace 与统一出口"]),
    ]
    for x, name, color, light, lines in cards:
        rounded(draw, (x, 150, x + 330, 510), fill=WHITE, outline=color, radius=22, width=3)
        draw.rounded_rectangle((x + 24, 174, x + 306, 229), radius=14, fill=light)
        center(draw, (x + 24, 174, x + 306, 229), name, font(23, bold=True), color)
        y = 270
        for idx, line in enumerate(lines):
            draw.ellipse((x + 33, y + 7, x + 43, y + 17), fill=color)
            draw.text((x + 57, y), line, font=font(17), fill=INK if idx < 3 else color)
            y += 58
    rounded(draw, (76, 552, 1124, 630), fill="#EEF2FF", outline="#C8D1F3", radius=18)
    center(draw, (92, 562, 1108, 594), "生产常用组合：DaemonSet Agent → Gateway → 多后端", font(21, bold=True), PURPLE)
    center(draw, (92, 596, 1108, 622), "节点附近收集日志与 kubelet 指标，Gateway 集中处理 Trace、凭据、采样和路由", font(16), MUTED)
    image.save(ASSET_DIR / "deployment-patterns.png", optimize=True)


def lab_evidence(data: dict) -> None:
    image, draw = canvas()
    heading(draw, "本次 Kubernetes 实测：一条链路同时进入两类后端", "20 正常 + 1 慢请求 + 1 错误请求 · 两副本应用 · 健康探针已排除")
    cards = [
        (55, "22", "业务 Trace", PURPLE),
        (335, "87", "有效 Span", BLUE),
        (615, "UP", "Prometheus Target", GREEN),
        (895, "0", "探针 Trace", ORANGE),
    ]
    for x, value, label, color in cards:
        rounded(draw, (x, 132, x + 250, 242), outline="#D6DCE8", radius=18)
        draw.text((x + 22, 148), value, font=font(34, bold=True), fill=color)
        draw.text((x + 22, 202), label, font=font(16), fill=MUTED)

    # Request count panel.
    rounded(draw, (55, 270, 390, 595), radius=20)
    draw.text((78, 292), "请求结果", font=font(21, bold=True), fill=INK)
    request_rows = [("正常", 20, BLUE), ("慢请求", 1, ORANGE), ("错误", 1, RED)]
    for i, (label, value, color) in enumerate(request_rows):
        y = 352 + i * 72
        draw.text((80, y), label, font=font(17), fill=INK)
        draw.rounded_rectangle((156, y + 3, 344, y + 26), radius=10, fill="#EDF0F6")
        width = max(12, int(188 * value / 20))
        draw.rounded_rectangle((156, y + 3, 156 + width, y + 26), radius=10, fill=color)
        draw.text((350, y - 1), str(value), font=font(17, bold=True), fill=color)

    # Average latency panel.
    rounded(draw, (415, 270, 785, 595), radius=20)
    draw.text((438, 292), "Prometheus 平均延迟", font=font(21, bold=True), fill=INK)
    avgs = data["prometheus"]["average_latency_ms"]
    latency_rows = [("正常", avgs["normal"], BLUE), ("慢请求", avgs["slow"], ORANGE), ("错误", avgs["error"], RED)]
    for i, (label, value, color) in enumerate(latency_rows):
        y = 352 + i * 72
        draw.text((438, y), label, font=font(17), fill=INK)
        draw.rounded_rectangle((520, y + 3, 708, y + 26), radius=10, fill="#EDF0F6")
        width = max(12, int(188 * value / 1000))
        draw.rounded_rectangle((520, y + 3, 520 + width, y + 26), radius=10, fill=color)
        draw.text((715, y - 1), f"{value:.1f} ms", font=font(15, bold=True), fill=color)

    # Trace evidence panel.
    rounded(draw, (810, 270, 1145, 595), radius=20)
    draw.text((833, 292), "Langfuse Trace 证据", font=font(21, bold=True), fill=INK)
    trace = data["traces"]
    trace_rows = [
        ("Trace 数", f"{trace['trace_count']}"),
        ("普通调用", f"{trace['normal_trace_observations']} Span / Trace"),
        ("错误调用", f"{trace['error_trace_observations']} Span / Trace"),
        ("最慢链路", f"{trace['maximum_latency_ms']} ms"),
    ]
    for i, (label, value) in enumerate(trace_rows):
        y = 348 + i * 56
        draw.text((835, y), label, font=font(16), fill=MUTED)
        bounds = draw.textbbox((0, 0), value, font=font(17, bold=True))
        draw.text((1118 - (bounds[2] - bounds[0]), y), value, font=font(17, bold=True), fill=PURPLE)
        if i < len(trace_rows) - 1:
            draw.line((835, y + 37, 1120, y + 37), fill=LINE, width=1)

    draw.text((58, 632), "数据来源：Collector 导出摘要、Prometheus API 与 Langfuse Public API；已移除 IP、Pod UID、Trace ID 与凭据。", font=font(15), fill=MUTED)
    image.save(ASSET_DIR / "lab-evidence.png", optimize=True)


def main() -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    data = json.loads(DATA.read_text(encoding="utf-8"))
    architecture()
    deployment_patterns()
    lab_evidence(data)


if __name__ == "__main__":
    main()
