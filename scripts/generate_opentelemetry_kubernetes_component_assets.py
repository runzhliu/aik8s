#!/usr/bin/env python3
"""Fetch sanitized OTel/Prometheus/Tempo evidence and render article figures."""

from __future__ import annotations

import argparse
import base64
import json
import math
import netrc
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "docs/assets/practices/opentelemetry-kubernetes"
DATA_FILE = ASSET_DIR / "k8s-components-observability-results.json"
FONT_PATH = Path("/System/Library/Fonts/Hiragino Sans GB.ttc")
WIDTH, HEIGHT = 1200, 675

BG = "#F7F8FC"
WHITE = "#FFFFFF"
INK = "#172033"
MUTED = "#667085"
LINE = "#D9DFEA"
GRID = "#E9EDF4"
PURPLE = "#6D4AFF"
PURPLE_LIGHT = "#F0ECFF"
BLUE = "#246BFD"
BLUE_LIGHT = "#EAF1FF"
GREEN = "#15966A"
GREEN_LIGHT = "#E7F7F0"
ORANGE = "#F26B38"
ORANGE_LIGHT = "#FFF0E9"
RED = "#D64545"
RED_LIGHT = "#FDECEC"
CYAN = "#0D91A8"
PALETTE = [BLUE, PURPLE, GREEN, ORANGE, CYAN, RED, "#8A63D2", "#4C78A8"]


PROMQL = {
    "api_qps": 'sum by (verb) (rate(otel_k8s_apiserver_request_total{telemetry_pipeline="otel-k8s-components"}[5m]))',
    "api_p95": 'histogram_quantile(0.95, sum by (le, verb) (rate(otel_k8s_apiserver_request_duration_seconds_bucket{telemetry_pipeline="otel-k8s-components",verb!~"WATCH|CONNECT"}[5m])))',
    "apf_queue": 'sum by (priority_level) (otel_k8s_apiserver_flowcontrol_current_inqueue_requests{telemetry_pipeline="otel-k8s-components"})',
    "scheduler_pending": 'sum by (queue) (otel_k8s_scheduler_pending_pods{telemetry_pipeline="otel-k8s-components"})',
    "scheduler_p95": 'histogram_quantile(0.95, sum by (le, result) (rate(otel_k8s_scheduler_scheduling_attempt_duration_seconds_bucket{telemetry_pipeline="otel-k8s-components"}[5m])))',
    "controller_queue": 'topk(8, otel_k8s_workqueue_depth{telemetry_pipeline="otel-k8s-components",job="otel-kube-controller-manager"})',
    "etcd_pending": 'max(otel_k8s_etcd_server_proposals_pending{telemetry_pipeline="otel-k8s-components"})',
    "etcd_failed": 'sum(rate(otel_k8s_etcd_server_proposals_failed_total{telemetry_pipeline="otel-k8s-components"}[5m]))',
    "coredns_qps": 'sum(rate(otel_k8s_coredns_dns_requests_total{telemetry_pipeline="otel-k8s-components"}[5m]))',
    "coredns_errors": 'sum(rate(otel_k8s_coredns_dns_responses_total{telemetry_pipeline="otel-k8s-components",rcode!~"NOERROR|NXDOMAIN"}[5m]))',
    "deployment_desired": 'sum(otel_k8s_k8s_deployment_desired{telemetry_pipeline="otel-k8s-components"})',
    "deployment_available": 'sum(otel_k8s_k8s_deployment_available{telemetry_pipeline="otel-k8s-components"})',
    "pod_pending": 'count(otel_k8s_k8s_pod_phase{telemetry_pipeline="otel-k8s-components"} == 1)',
    "pod_running": 'count(otel_k8s_k8s_pod_phase{telemetry_pipeline="otel-k8s-components"} == 2)',
    "pod_failed": 'count(otel_k8s_k8s_pod_phase{telemetry_pipeline="otel-k8s-components"} == 4)',
    "collector_accepted": 'sum(rate(otel_k8s_otelcol_receiver_accepted_metric_points_total{telemetry_pipeline="otel-k8s-components",job="otel-collector-self"}[5m]))',
    "collector_rss": 'max(otel_k8s_otelcol_process_memory_rss{telemetry_pipeline="otel-k8s-components",job="otel-collector-self"}) / 1024 / 1024',
}

LABEL_KEYS = ("verb", "priority_level", "queue", "result", "name")


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
    draw.text((48, 28), title, font=font(31, bold=True), fill=INK)
    draw.text((50, 73), subtitle, font=font(16), fill=MUTED)


def center_text(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    face: ImageFont.FreeTypeFont,
    color: str = INK,
) -> None:
    bounds = draw.textbbox((0, 0), text, font=face)
    tw, th = bounds[2] - bounds[0], bounds[3] - bounds[1]
    x1, y1, x2, y2 = box
    draw.text(((x1 + x2 - tw) / 2, (y1 + y2 - th) / 2 - bounds[1]), text, font=face, fill=color)


def arrow(draw: ImageDraw.ImageDraw, start: tuple[int, int], end: tuple[int, int], color: str = PURPLE) -> None:
    draw.line((start, end), fill=color, width=4)
    ex, ey = end
    draw.polygon([(ex, ey), (ex - 11, ey - 7), (ex - 11, ey + 7)], fill=color)


def basic_auth_header(url: str, netrc_path: Path) -> dict[str, str]:
    host = urllib.parse.urlparse(url).hostname
    auth = netrc.netrc(str(netrc_path)).authenticators(host or "")
    if not auth:
        raise RuntimeError(f"no netrc entry for {host}")
    login, _, password = auth
    token = base64.b64encode(f"{login}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def get_json(url: str, headers: dict[str, str] | None = None) -> dict:
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def label_for(metric: dict[str, str]) -> str:
    for key in LABEL_KEYS:
        if metric.get(key):
            return metric[key]
    return "total"


def sanitize_range(result: list[dict]) -> list[dict]:
    by_label: dict[str, dict] = {}
    for item in result:
        points = []
        for timestamp, value in item.get("values", []):
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(number):
                points.append([round(float(timestamp), 3), round(number, 6)])
        if points:
            label = label_for(item.get("metric", {}))
            candidate = {"label": label, "points": points}
            current = by_label.get(label)
            # A target restart can leave two otherwise identical series in one
            # query window. Keep the series with the freshest sample so a
            # historical instance is not presented as a second live queue.
            if current is None or points[-1][0] > current["points"][-1][0]:
                by_label[label] = candidate
    series = list(by_label.values())
    series.sort(key=lambda item: max(point[1] for point in item["points"]), reverse=True)
    return series[:8]


def sanitize_trace(payload: dict) -> dict:
    raw_spans = []
    service_name = "unknown"
    for batch in payload.get("batches", []):
        attrs = batch.get("resource", {}).get("attributes", [])
        for attr in attrs:
            if attr.get("key") == "service.name":
                service_name = attr.get("value", {}).get("stringValue", "unknown")
        for scope in batch.get("scopeSpans", []):
            raw_spans.extend(scope.get("spans", []))
    if not raw_spans:
        raise RuntimeError("trace contains no spans")

    min_start = min(int(item["startTimeUnixNano"]) for item in raw_spans)
    id_to_index = {item["spanId"]: index for index, item in enumerate(raw_spans)}
    spans = []
    for item in sorted(raw_spans, key=lambda value: int(value["startTimeUnixNano"])):
        attributes = {}
        for attr in item.get("attributes", []):
            value = attr.get("value", {})
            for field in ("stringValue", "intValue", "doubleValue", "boolValue"):
                if field in value:
                    attributes[attr["key"]] = value[field]
                    break
        start = int(item["startTimeUnixNano"])
        end = int(item["endTimeUnixNano"])
        status = item.get("status", {}).get("code", "STATUS_CODE_UNSET")
        spans.append(
            {
                "name": item["name"],
                "kind": item.get("kind", "SPAN_KIND_UNSPECIFIED").replace("SPAN_KIND_", ""),
                "parent_index": id_to_index.get(item.get("parentSpanId")),
                "start_ms": round((start - min_start) / 1_000_000, 3),
                "duration_ms": round((end - start) / 1_000_000, 3),
                "status": "ERROR" if status == "STATUS_CODE_ERROR" else "OK",
                "attributes": {
                    key: attributes[key]
                    for key in (
                        "http.request.method",
                        "http.route",
                        "http.response.status_code",
                        "k8s.operation",
                        "k8s.resource.kind",
                        "rollout.status",
                        "url.path",
                    )
                    if key in attributes
                },
            }
        )
    total = max(item["start_ms"] + item["duration_ms"] for item in spans)
    return {"service": service_name, "duration_ms": round(total, 3), "spans": spans}


def fetch(args: argparse.Namespace) -> dict:
    end = time.time()
    start = end - args.minutes * 60
    headers = basic_auth_header(args.grafana_url, args.netrc)
    metrics = {}
    for name, query in PROMQL.items():
        params = urllib.parse.urlencode(
            {"query": query, "start": f"{start:.3f}", "end": f"{end:.3f}", "step": "60"}
        )
        url = (
            args.grafana_url.rstrip("/")
            + f"/api/datasources/proxy/uid/{urllib.parse.quote(args.prometheus_datasource_uid, safe='')}/api/v1/query_range?"
            + params
        )
        body = get_json(url, headers)
        if body.get("status") != "success":
            raise RuntimeError(f"Prometheus query failed: {name}")
        metrics[name] = sanitize_range(body["data"].get("result", []))

    traces = []
    for trace_id in args.trace_id:
        url = args.tempo_url.rstrip("/") + "/api/traces/" + trace_id
        traces.append(sanitize_trace(get_json(url)))

    data = {
        "window_minutes": args.minutes,
        "metrics": metrics,
        "traces": traces,
        "cardinality": {
            "before_bytes": 30_760_596,
            "after_bytes": 2_146_284,
            "active_series": 7_338,
        },
    }
    args.data.parent.mkdir(parents=True, exist_ok=True)
    args.data.write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return data


def all_values(series: list[dict]) -> list[float]:
    return [point[1] for item in series for point in item["points"]]


def last_values(series: list[dict]) -> list[tuple[str, float]]:
    return [(item["label"], item["points"][-1][1]) for item in series if item["points"]]


def line_chart(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    title: str,
    series: list[dict],
    *,
    unit: str = "",
    scale: float = 1.0,
    max_series: int = 5,
) -> None:
    rounded(draw, box)
    x1, y1, x2, y2 = box
    draw.text((x1 + 18, y1 + 14), title, font=font(19, bold=True), fill=INK)
    plot = (x1 + 52, y1 + 54, x2 - 18, y2 - 56)
    values = [value * scale for value in all_values(series[:max_series])]
    ymax = max(values, default=1.0)
    if ymax <= 0:
        ymax = 1.0
    ymax *= 1.12
    px1, py1, px2, py2 = plot
    for index in range(4):
        y = py1 + (py2 - py1) * index / 3
        draw.line((px1, y, px2, y), fill=GRID, width=1)
        value = ymax * (3 - index) / 3
        label = f"{value:.1f}{unit}" if value < 100 else f"{value:.0f}{unit}"
        draw.text((x1 + 8, y - 8), label, font=font(11), fill=MUTED)
    draw.text((px1, py2 + 7), "-60m", font=font(11), fill=MUTED)
    center_text(draw, (px1, py2 + 4, px2, py2 + 28), "-30m", font(11), MUTED)
    right = draw.textbbox((0, 0), "now", font=font(11))[2]
    draw.text((px2 - right, py2 + 7), "now", font=font(11), fill=MUTED)

    legend_x = x1 + 18
    for index, item in enumerate(series[:max_series]):
        points = item["points"]
        if len(points) < 2:
            continue
        color = PALETTE[index % len(PALETTE)]
        tmin, tmax = points[0][0], points[-1][0]
        if tmax <= tmin:
            tmax = tmin + 1
        coords = []
        for timestamp, value in points:
            x = px1 + (timestamp - tmin) / (tmax - tmin) * (px2 - px1)
            y = py2 - (value * scale / ymax) * (py2 - py1)
            coords.append((x, y))
        draw.line(coords, fill=color, width=3, joint="curve")
        if coords:
            x, y = coords[-1]
            draw.ellipse((x - 3, y - 3, x + 3, y + 3), fill=color)
        legend = item["label"][:17]
        draw.rounded_rectangle((legend_x, y2 - 30, legend_x + 12, y2 - 18), radius=3, fill=color)
        draw.text((legend_x + 17, y2 - 33), legend, font=font(12), fill=MUTED)
        legend_x += min(135, 28 + draw.textbbox((0, 0), legend, font=font(12))[2])


def bars(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    title: str,
    values: list[tuple[str, float]],
    *,
    unit: str = "",
    max_items: int = 6,
) -> None:
    rounded(draw, box)
    x1, y1, x2, y2 = box
    draw.text((x1 + 18, y1 + 14), title, font=font(19, bold=True), fill=INK)
    values = sorted(values, key=lambda item: item[1], reverse=True)[:max_items]
    vmax = max((value for _, value in values), default=1.0) or 1.0
    available = max(1, y2 - y1 - 62)
    row_height = max(20, available // max(1, len(values)))
    for index, (label, value) in enumerate(values):
        y = y1 + 50 + index * row_height
        label = label[:22]
        draw.text((x1 + 18, y), label, font=font(13), fill=INK)
        bar_x = x1 + 255
        bar_w = max(2, int((x2 - bar_x - 68) * value / vmax))
        draw.rounded_rectangle((bar_x, y + 2, bar_x + bar_w, y + 18), radius=7, fill=PALETTE[index % len(PALETTE)])
        value_text = f"{value:.2f}{unit}" if value < 10 else f"{value:.0f}{unit}"
        draw.text((x2 - 58, y), value_text, font=font(12, bold=True), fill=MUTED)
    if not values:
        center_text(draw, (x1, y1 + 60, x2, y2), "当前窗口无非零数据", font(16), MUTED)


def footer(draw: ImageDraw.ImageDraw, text: str) -> None:
    draw.text((50, 642), text, font=font(13), fill=MUTED)


def architecture() -> None:
    image, draw = canvas()
    heading(draw, "Kubernetes 组件：Metric 与 Trace 的两条观测路径", "指标回答整体趋势；Trace 与 Span 解释一次请求内部每一步花在哪里")
    rounded(draw, (45, 120, 1155, 610), fill="#FBFCFF", outline="#BEC8DA", radius=24)

    components = ["API Server", "Scheduler", "Controller", "etcd", "CoreDNS", "Cluster State"]
    for index, name in enumerate(components):
        y = 152 + index * 67
        rounded(draw, (76, y, 280, y + 46), fill=BLUE_LIGHT, outline="#A9C0F4", radius=12)
        center_text(draw, (76, y, 280, y + 46), name, font(17, bold=True), BLUE)
        arrow(draw, (280, y + 23), (390, y + 23), BLUE)
    center_text(draw, (305, 306, 385, 342), "/metrics", font(15, bold=True), BLUE)

    rounded(draw, (390, 182, 680, 415), fill=PURPLE_LIGHT, outline="#BAACFF", radius=20)
    center_text(draw, (410, 202, 660, 245), "OpenTelemetry Collector", font(23, bold=True), PURPLE)
    for y, line in [(270, "Prometheus receiver"), (315, "k8s_cluster receiver"), (360, "过滤 · 聚合 · 资源属性")]:
        center_text(draw, (420, y, 650, y + 30), line, font(16), INK)

    arrow(draw, (680, 255), (800, 255), PURPLE)
    rounded(draw, (800, 190, 1105, 315), fill=GREEN_LIGHT, outline="#8FD4BB", radius=18)
    center_text(draw, (820, 207, 1085, 250), "Prometheus → Grafana", font(22, bold=True), GREEN)
    center_text(draw, (820, 258, 1085, 294), "QPS · P95 · 队列 · 错误率", font(15), INK)

    rounded(draw, (390, 472, 680, 558), fill=ORANGE_LIGHT, outline="#F6B99F", radius=18)
    center_text(draw, (410, 486, 660, 520), "业务 / kube-apiserver", font(19, bold=True), ORANGE)
    center_text(draw, (410, 522, 660, 548), "OTLP Trace", font(15), MUTED)
    arrow(draw, (680, 515), (800, 515), ORANGE)
    rounded(draw, (800, 450, 1105, 575), fill=PURPLE_LIGHT, outline="#BAACFF", radius=18)
    center_text(draw, (820, 468, 1085, 510), "Tempo → Grafana Explore", font(21, bold=True), PURPLE)
    center_text(draw, (820, 518, 1085, 552), "Trace 搜索 · Span 瀑布 · 属性", font(15), INK)
    footer(draw, "Prometheus 指标不会自动变成 Span；要查看 Span，数据源必须实际发送 OTLP Trace。")
    image.save(ASSET_DIR / "k8s-components-metrics-traces-architecture.png", optimize=True)


def api_server(data: dict) -> None:
    metrics = data["metrics"]
    image, draw = canvas()
    heading(draw, "API Server 与 APF：流量、尾延迟和排队要一起看", "同一小时窗口 · P95 排除 WATCH / CONNECT 长连接")
    line_chart(draw, (45, 116, 575, 431), "请求速率（按 verb）", metrics["api_qps"], unit="/s")
    line_chart(draw, (595, 116, 1155, 431), "P95 延迟（按 verb）", metrics["api_p95"], unit=" ms", scale=1000)
    bars(draw, (45, 451, 760, 625), "APF 当前排队（按 PriorityLevel）", last_values(metrics["apf_queue"]), max_items=4)
    total_qps = sum(value for _, value in last_values(metrics["api_qps"]))
    rounded(draw, (780, 451, 1155, 625), fill=PURPLE_LIGHT, outline="#BAACFF")
    draw.text((805, 473), "读图结论", font=font(20, bold=True), fill=PURPLE)
    draw.text((805, 516), f"当前总请求约 {total_qps:.1f} req/s", font=font(18, bold=True), fill=INK)
    draw.text((805, 553), "排队为 0 不代表没有限流", font=font(15), fill=MUTED)
    draw.text((805, 582), "还需联查 rejected_requests_total", font=font(15), fill=MUTED)
    footer(draw, "数据来源：Grafana 所用 Prometheus 数据源；图中仅保留 verb 与 priority_level 等必要维度。")
    image.save(ASSET_DIR / "k8s-components-apiserver-apf.png", optimize=True)


def scheduler_controller(data: dict) -> None:
    metrics = data["metrics"]
    image, draw = canvas()
    heading(draw, "Scheduler 与 Controller Manager：积压发生在哪里", "Pending Queue 解释调度入口；Workqueue Depth 解释控制循环积压")
    line_chart(draw, (45, 116, 575, 430), "Scheduler 等待队列", metrics["scheduler_pending"])
    line_chart(draw, (595, 116, 1155, 430), "Scheduler 调度 P95", metrics["scheduler_p95"], unit=" ms", scale=1000)
    bars(draw, (45, 450, 1155, 625), "Controller Manager Workqueue Top 4", last_values(metrics["controller_queue"]), max_items=4)
    footer(draw, "队列深度需要结合 add rate 与处理延迟；单个瞬时值不能区分短时抖动和持续积压。")
    image.save(ASSET_DIR / "k8s-components-scheduler-controller.png", optimize=True)


def etcd_dns(data: dict) -> None:
    metrics = data["metrics"]
    image, draw = canvas()
    heading(draw, "etcd 与 CoreDNS：控制面存储和服务发现", "proposal、leader、DNS QPS 与错误 rcode 是两条关键依赖链")
    line_chart(draw, (45, 116, 575, 430), "etcd Pending Proposals", metrics["etcd_pending"])
    line_chart(draw, (595, 116, 1155, 430), "etcd Failed Proposals / s", metrics["etcd_failed"])
    line_chart(draw, (45, 450, 760, 625), "CoreDNS 请求速率", metrics["coredns_qps"], unit="/s")
    error = last_values(metrics["coredns_errors"])
    error_value = error[0][1] if error else 0.0
    rounded(draw, (780, 450, 1155, 625), fill=GREEN_LIGHT if error_value == 0 else RED_LIGHT, outline="#8FD4BB" if error_value == 0 else "#EEA6A6")
    draw.text((805, 475), "CoreDNS 非预期错误", font=font(19, bold=True), fill=GREEN if error_value == 0 else RED)
    draw.text((805, 520), f"{error_value:.4f} req/s", font=font(32, bold=True), fill=INK)
    draw.text((805, 573), "排除 NOERROR 与 NXDOMAIN", font=font(14), fill=MUTED)
    footer(draw, "etcd leader 另以 Stat 面板检查；DNS 错误需结合上游解析、网络策略和超时一起定位。")
    image.save(ASSET_DIR / "k8s-components-etcd-coredns.png", optimize=True)


def cluster_pipeline(data: dict) -> None:
    metrics = data["metrics"]
    image, draw = canvas()
    heading(draw, "集群状态与 Collector 自监控：观测管道也要被观测", "Deployment、Pod Phase、接收点数与 RSS 放在同一页，避免看板静默失真")
    replicas = []
    for name, label in (("deployment_desired", "desired"), ("deployment_available", "available")):
        if metrics[name]:
            item = dict(metrics[name][0])
            item["label"] = label
            replicas.append(item)
    line_chart(draw, (45, 116, 575, 430), "Deployment 副本", replicas)
    phase_values = []
    for name, label in (("pod_running", "Running"), ("pod_pending", "Pending"), ("pod_failed", "Failed")):
        values = last_values(metrics[name])
        phase_values.append((label, values[0][1] if values else 0.0))
    bars(draw, (595, 116, 1155, 430), "Pod Phase", phase_values, max_items=3)
    line_chart(draw, (45, 450, 760, 625), "Collector 接收 Metric Points / s", metrics["collector_accepted"], unit="/s")
    rss = last_values(metrics["collector_rss"])
    rss_value = rss[0][1] if rss else 0.0
    rounded(draw, (780, 450, 1155, 625), fill=PURPLE_LIGHT, outline="#BAACFF")
    draw.text((805, 475), "Collector 当前 RSS", font=font(19, bold=True), fill=PURPLE)
    draw.text((805, 520), f"{rss_value:.0f} MiB", font=font(32, bold=True), fill=INK)
    draw.text((805, 573), "同时检查 refused / send_failed", font=font(14), fill=MUTED)
    footer(draw, "Collector Running 只说明进程存活；accepted、refused、send_failed 与下游 target 必须一起验收。")
    image.save(ASSET_DIR / "k8s-components-cluster-collector.png", optimize=True)


def cardinality(data: dict) -> None:
    item = data["cardinality"]
    before = item["before_bytes"] / 1024 / 1024
    after = item["after_bytes"] / 1024 / 1024
    reduction = (1 - after / before) * 100
    image, draw = canvas()
    heading(draw, "指标基数治理：白名单之后，还要减少标签组合", "同一个 Collector、同一批看板需求；聚合发生在导出 Prometheus 之前")
    rounded(draw, (45, 120, 760, 610))
    chart_left, chart_right = 130, 690
    baseline_y = 530
    max_height = 330
    max_value = before * 1.1
    for index, (label, value, color) in enumerate((("仅过滤指标名", before, ORANGE), ("再聚合标签", after, PURPLE))):
        x = chart_left + index * 300
        height = max(18, value / max_value * max_height)
        draw.rounded_rectangle((x, baseline_y - height, x + 160, baseline_y), radius=14, fill=color)
        center_text(draw, (x - 20, baseline_y - height - 55, x + 180, baseline_y - height - 10), f"{value:.2f} MiB", font(25, bold=True), color)
        center_text(draw, (x - 30, baseline_y + 15, x + 190, baseline_y + 55), label, font(17, bold=True), INK)
    draw.line((105, baseline_y, 720, baseline_y), fill=LINE, width=2)

    rounded(draw, (790, 120, 1155, 610), fill=PURPLE_LIGHT, outline="#BAACFF")
    draw.text((825, 160), "结果", font=font(20, bold=True), fill=PURPLE)
    draw.text((825, 215), f"下降 {reduction:.1f}%", font=font(35, bold=True), fill=INK)
    draw.text((825, 282), f"活跃序列 {item['active_series']:,}", font=font(20, bold=True), fill=INK)
    draw.text((825, 343), "保留维度", font=font(16, bold=True), fill=PURPLE)
    for index, text in enumerate(("verb / code", "priority_level / reason", "result / rcode")):
        draw.text((825, 382 + index * 39), "• " + text, font=font(16), fill=INK)
    draw.text((825, 520), "代价：被聚合的 resource", font=font(14), fill=MUTED)
    draw.text((825, 548), "等维度不能再用于排障", font=font(14), fill=MUTED)
    footer(draw, "体积按 Collector /metrics 响应字节数计算；标签删减必须从 Dashboard、告警和排障查询反推。")
    image.save(ASSET_DIR / "k8s-components-cardinality-reduction.png", optimize=True)


def trace_panel(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    trace: dict,
    title: str,
) -> None:
    rounded(draw, box)
    x1, y1, x2, y2 = box
    draw.text((x1 + 18, y1 + 14), title, font=font(19, bold=True), fill=INK)
    draw.text((x2 - 150, y1 + 17), f"{trace['duration_ms']:.0f} ms", font=font(16, bold=True), fill=PURPLE)
    spans = trace["spans"]
    total = max(trace["duration_ms"], 1)
    label_width = 290
    bar_left, bar_right = x1 + label_width, x2 - 22
    row_height = min(55, (y2 - y1 - 66) // max(1, len(spans)))
    for index, item in enumerate(spans):
        y = y1 + 55 + index * row_height
        parent = item.get("parent_index")
        depth = 0 if parent is None else 1
        display_name = item["name"].replace("kubernetes.client ", "")
        label = ("CHILD  " if depth else "ROOT   ") + display_name
        if len(label) > 34:
            label = label[:32] + "…"
        draw.text((x1 + 16, y + 5), label, font=font(13, bold=item["status"] == "ERROR"), fill=RED if item["status"] == "ERROR" else INK)
        bx1 = bar_left + item["start_ms"] / total * (bar_right - bar_left)
        bx2 = bx1 + max(4, item["duration_ms"] / total * (bar_right - bar_left))
        color = RED if item["status"] == "ERROR" else PALETTE[index % 5]
        draw.rounded_rectangle((bx1, y + 3, min(bx2, bar_right), y + 27), radius=7, fill=color)
        duration = f"{item['duration_ms']:.0f}ms"
        if bx2 - bx1 >= 58:
            width = draw.textbbox((0, 0), duration, font=font(11, bold=True))[2]
            draw.text((min(bx2, bar_right) - width - 7, y + 6), duration, font=font(11, bold=True), fill=WHITE)
        else:
            draw.text((min(bx2 + 7, bar_right - 48), y + 6), duration, font=font(11), fill=MUTED)


def spans(data: dict) -> None:
    traces = data.get("traces", [])
    if not traces:
        return
    image, draw = canvas()
    heading(draw, "Span 怎么看：先看瀑布，再点最慢或报错的那一段", "真实 OTLP 父子 Span · Tempo 存储 · Grafana Explore 可按 service.name 与 status 搜索")
    trace_panel(draw, (45, 116, 1155, 392), traces[0], "成功发布：父 Span 与四个子 Span")
    if len(traces) > 1:
        trace_panel(draw, (45, 412, 830, 625), traces[1], "失败发布：错误落在哪个 Span")
        rounded(draw, (850, 412, 1155, 625), fill=RED_LIGHT, outline="#EEA6A6")
        draw.text((875, 438), "排查顺序", font=font(19, bold=True), fill=RED)
        for index, line in enumerate(("1. Root Span 总耗时", "2. ERROR Span 与事件", "3. 属性：kind / operation", "4. 同时段 Metrics 与 Log")):
            draw.text((875, 482 + index * 34), line, font=font(14), fill=INK)
    footer(draw, "Span 是一次请求中的一个步骤；父子关系说明调用结构，横条位置和长度说明开始时间与耗时。")
    image.save(ASSET_DIR / "k8s-components-span-waterfall.png", optimize=True)


def render(data: dict) -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    architecture()
    api_server(data)
    scheduler_controller(data)
    etcd_dns(data)
    cluster_pipeline(data)
    cardinality(data)
    spans(data)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=DATA_FILE)
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--grafana-url")
    parser.add_argument("--tempo-url")
    parser.add_argument("--netrc", type=Path)
    parser.add_argument("--prometheus-datasource-uid", default="prometheus")
    parser.add_argument("--trace-id", action="append", default=[])
    parser.add_argument("--minutes", type=int, default=60)
    args = parser.parse_args()
    if args.fetch:
        if not all((args.grafana_url, args.tempo_url, args.netrc, args.trace_id)):
            parser.error("--fetch requires --grafana-url, --tempo-url, --netrc, and --trace-id")
        data = fetch(args)
    else:
        data = json.loads(args.data.read_text(encoding="utf-8"))
    render(data)
    print(args.data)


if __name__ == "__main__":
    main()
