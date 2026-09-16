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


def beginner_mental_model() -> None:
    image, draw = canvas()
    heading(draw, "先记住一条主线：产生 → 传输 → 处理 → 存储", "OpenTelemetry 负责前三段；查询、看板和长期保存由可观测后端完成")

    stages = [
        (55, 160, 260, "应用与基础设施", "SDK · 自动埋点\nKubelet · 容器日志", BLUE, BLUE_LIGHT),
        (330, 160, 535, "OTLP", "Trace · Metric · Log\n统一传输协议", ORANGE, ORANGE_LIGHT),
        (605, 160, 810, "Collector", "接收 · 加工 · 采样\n补标签 · 批量 · 路由", PURPLE, PURPLE_LIGHT),
        (880, 160, 1085, "可观测后端", "存储 · 查询 · 看板\n告警 · 关联分析", GREEN, GREEN_LIGHT),
    ]
    for x1, y1, x2, name, detail, color, light in stages:
        rounded(draw, (x1, y1, x2, 390), fill=WHITE, outline=color, radius=22, width=3)
        draw.rounded_rectangle((x1 + 18, y1 + 20, x2 - 18, y1 + 78), radius=14, fill=light)
        center(draw, (x1 + 18, y1 + 20, x2 - 18, y1 + 78), name, font(22, bold=True), color)
        lines = detail.split("\n")
        for index, line in enumerate(lines):
            center(draw, (x1 + 12, y1 + 122 + index * 48, x2 - 12, y1 + 158 + index * 48), line, font(16), INK)

    for start, end, color in [((260, 274), (330, 274), ORANGE), ((535, 274), (605, 274), PURPLE), ((810, 274), (880, 274), GREEN)]:
        arrow(draw, start, end, color=color, width=4)

    rounded(draw, (80, 455, 1120, 610), fill="#FBFCFF", outline="#CBD3E3", radius=20)
    draw.text((110, 480), "一个常见误解", font=font(20, bold=True), fill=RED)
    draw.text((110, 522), "Collector 收到 Span，并不等于数据已经可查询。", font=font(20, bold=True), fill=INK)
    draw.text((110, 564), "还要继续检查 Exporter、后端入库、索引和查询链路。", font=font(17), fill=MUTED)
    image.save(ASSET_DIR / "beginner-mental-model.png", optimize=True)


def trace_span_context() -> None:
    image, draw = canvas()
    heading(draw, "Trace、Span 与 Context：一次请求怎样串成完整链路", "Trace ID 全程不变；每一步有自己的 Span ID；下游通过 traceparent 识别父子关系")

    services = [(80, "Frontend", BLUE), (315, "Order", PURPLE), (550, "Payment", ORANGE), (785, "Database", GREEN)]
    for x, name, color in services:
        rounded(draw, (x, 145, x + 175, 202), fill=WHITE, outline=color, radius=14, width=2)
        center(draw, (x, 145, x + 175, 202), name, font(19, bold=True), color)
        draw.line((x + 87, 202, x + 87, 515), fill="#D0D7E5", width=2)

    bars = [
        (167, 242, 1038, 286, BLUE, "Span A · POST /checkout · 820 ms"),
        (402, 312, 950, 356, PURPLE, "Span B · create-order · 510 ms"),
        (637, 382, 900, 426, ORANGE, "Span C · charge · 190 ms"),
        (872, 452, 1065, 496, GREEN, "Span D · INSERT · 80 ms"),
    ]
    for x1, y1, x2, y2, color, label in bars:
        draw.rounded_rectangle((x1, y1, x2, y2), radius=12, fill=color)
        draw.text((x1 + 12, y1 + 12), label, font=font(14, bold=True), fill=WHITE)

    for start, end, color in [((254, 264), (402, 334), PURPLE), ((489, 334), (637, 404), ORANGE), ((724, 404), (872, 474), GREEN)]:
        draw.line((start, end), fill=color, width=3)

    rounded(draw, (80, 545, 1120, 625), fill="#EEF2FF", outline="#CAD2EF", radius=16)
    draw.text((108, 563), "同一个 Trace ID", font=font(17, bold=True), fill=PURPLE)
    draw.text((275, 563), "7f3a…9c21", font=font(17, bold=True), fill=INK)
    draw.text((445, 563), "不同 Span ID", font=font(17, bold=True), fill=ORANGE)
    draw.text((590, 563), "a1… / b2… / c3… / d4…", font=font(17), fill=INK)
    draw.text((108, 594), "跨进程传递", font=font(16, bold=True), fill=BLUE)
    draw.text((235, 594), "traceparent: version-trace-id-parent-id-flags", font=font(16), fill=MUTED)
    image.save(ASSET_DIR / "trace-span-context.png", optimize=True)


def kubernetes_collector_roles() -> None:
    image, draw = canvas()
    heading(draw, "Kubernetes 中常见的两层 Collector", "DaemonSet 靠近节点采数据，Gateway 集中执行平台策略和后端路由")

    rounded(draw, (45, 128, 760, 615), fill="#FBFCFF", outline="#BEC8DA", radius=22)
    draw.rounded_rectangle((65, 146, 230, 180), radius=15, fill=BLUE_LIGHT)
    center(draw, (65, 146, 230, 180), "Kubernetes Cluster", font(16, bold=True), BLUE)

    for x, node in [(78, "Node A"), (330, "Node B")]:
        rounded(draw, (x, 210, x + 218, 524), fill=WHITE, outline="#CAD3E4", radius=18)
        center(draw, (x + 18, 226, x + 200, 258), node, font(19, bold=True), INK)
        rounded(draw, (x + 28, 280, x + 190, 337), fill=BLUE_LIGHT, outline="#AFC4F5", radius=12)
        center(draw, (x + 28, 280, x + 190, 337), "Application Pod", font(16, bold=True), BLUE)
        rounded(draw, (x + 28, 370, x + 190, 446), fill=GREEN_LIGHT, outline="#A6D9C5", radius=12)
        center(draw, (x + 28, 370, x + 190, 402), "Collector Agent", font(16, bold=True), GREEN)
        center(draw, (x + 28, 406, x + 190, 438), "filelog · kubeletstats", font(13), MUTED)
        arrow(draw, (x + 109, 337), (x + 109, 370), color=GREEN, width=3)

    rounded(draw, (582, 268, 730, 470), fill=PURPLE_LIGHT, outline="#B9A9FF", radius=18, width=3)
    center(draw, (594, 288, 718, 330), "Gateway", font(21, bold=True), PURPLE)
    for i, text_value in enumerate(["鉴权", "过滤", "采样", "批量", "路由"]):
        center(draw, (596, 340 + i * 25, 716, 362 + i * 25), text_value, font(14), INK)
    draw.line(((187, 446), (187, 552), (548, 552)), fill=PURPLE, width=3)
    arrow(draw, (548, 552), (582, 445), color=PURPLE, width=3)
    arrow(draw, (520, 408), (582, 420), color=PURPLE, width=3)

    backends = [
        (830, 180, ORANGE_LIGHT, ORANGE, "Trace Backend", "调用链与慢点"),
        (830, 330, BLUE_LIGHT, BLUE, "Metrics Backend", "趋势、SLO 与告警"),
        (830, 480, GREEN_LIGHT, GREEN, "Log Backend", "事件与全文检索"),
    ]
    for x, y, light, color, name, detail in backends:
        rounded(draw, (x, y, 1125, y + 103), fill=light, outline=color, radius=18)
        draw.text((855, y + 18), name, font=font(20, bold=True), fill=color)
        draw.text((855, y + 58), detail, font=font(16), fill=INK)
        arrow(draw, (730, y + 51), (830, y + 51), color=color, width=3)

    draw.text((65, 635), "节点日志和 Kubelet 指标适合 Agent；应用 OTLP、统一采样与跨后端凭据适合 Gateway。", font=font(15), fill=MUTED)
    image.save(ASSET_DIR / "kubernetes-collector-roles.png", optimize=True)


def main() -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    data = json.loads(DATA.read_text(encoding="utf-8"))
    architecture()
    deployment_patterns()
    lab_evidence(data)
    beginner_mental_model()
    trace_span_context()
    kubernetes_collector_roles()


if __name__ == "__main__":
    main()
