#!/usr/bin/env python3
"""Send a dependency-free OTLP/HTTP JSON trace demo to an OTel Collector."""

from __future__ import annotations

import argparse
import json
import secrets
import time
import urllib.request


def string_attr(key: str, value: str) -> dict:
    return {"key": key, "value": {"stringValue": value}}


def int_attr(key: str, value: int) -> dict:
    return {"key": key, "value": {"intValue": str(value)}}


def span(
    *,
    trace_id: str,
    span_id: str,
    parent_span_id: str | None,
    name: str,
    kind: int,
    start_ns: int,
    duration_ms: int,
    attributes: list[dict],
    error: str | None = None,
) -> dict:
    item = {
        "traceId": trace_id,
        "spanId": span_id,
        "name": name,
        "kind": kind,
        "startTimeUnixNano": str(start_ns),
        "endTimeUnixNano": str(start_ns + duration_ms * 1_000_000),
        "attributes": attributes,
        "status": {"code": 2 if error else 1, "message": error or ""},
    }
    if parent_span_id:
        item["parentSpanId"] = parent_span_id
    if error:
        item["events"] = [
            {
                "timeUnixNano": str(start_ns + max(1, duration_ms - 10) * 1_000_000),
                "name": "exception",
                "attributes": [
                    string_attr("exception.type", "DeploymentRejected"),
                    string_attr("exception.message", error),
                ],
            }
        ]
    return item


def build_payload(count: int, cluster: str) -> tuple[dict, list[str]]:
    now = time.time_ns()
    spans: list[dict] = []
    trace_ids: list[str] = []

    for index in range(count):
        trace_id = secrets.token_hex(16)
        trace_ids.append(trace_id)
        root_id = secrets.token_hex(8)
        start = now - (count - index) * 2_000_000_000
        failed = index % 7 == 6
        root_duration = 420 + (index % 5) * 135
        if failed:
            root_duration = 310

        spans.append(
            span(
                trace_id=trace_id,
                span_id=root_id,
                parent_span_id=None,
                name="POST /releases",
                kind=2,
                start_ns=start,
                duration_ms=root_duration,
                attributes=[
                    string_attr("http.request.method", "POST"),
                    string_attr("http.route", "/releases"),
                    int_attr("http.response.status_code", 500 if failed else 200),
                    string_attr("release.strategy", "rolling-update"),
                ],
                error="deployment quota exceeded" if failed else None,
            )
        )

        validate_id = secrets.token_hex(8)
        spans.append(
            span(
                trace_id=trace_id,
                span_id=validate_id,
                parent_span_id=root_id,
                name="validate-manifest",
                kind=1,
                start_ns=start + 12_000_000,
                duration_ms=28 + index % 9,
                attributes=[
                    string_attr("k8s.resource.kind", "Deployment"),
                    string_attr("validation.result", "accepted"),
                ],
            )
        )

        apply_id = secrets.token_hex(8)
        spans.append(
            span(
                trace_id=trace_id,
                span_id=apply_id,
                parent_span_id=root_id,
                name="kubernetes.client APPLY deployment",
                kind=3,
                start_ns=start + 58_000_000,
                duration_ms=145 if failed else 82 + (index % 4) * 13,
                attributes=[
                    string_attr("server.address", "kubernetes.default.svc"),
                    string_attr("k8s.resource.kind", "Deployment"),
                    string_attr("k8s.namespace.name", "otel-k8s-monitoring"),
                    string_attr("k8s.operation", "apply"),
                ],
                error="deployment quota exceeded" if failed else None,
            )
        )

        if not failed:
            watch_id = secrets.token_hex(8)
            spans.append(
                span(
                    trace_id=trace_id,
                    span_id=watch_id,
                    parent_span_id=root_id,
                    name="wait-deployment-ready",
                    kind=1,
                    start_ns=start + 175_000_000,
                    duration_ms=max(120, root_duration - 250),
                    attributes=[
                        string_attr("k8s.watch.resource", "deployments"),
                        string_attr("rollout.status", "available"),
                    ],
                )
            )

            spans.append(
                span(
                    trace_id=trace_id,
                    span_id=secrets.token_hex(8),
                    parent_span_id=root_id,
                    name="readiness-check",
                    kind=3,
                    start_ns=start + (root_duration - 68) * 1_000_000,
                    duration_ms=42,
                    attributes=[
                        string_attr("http.request.method", "GET"),
                        string_attr("url.path", "/readyz"),
                        int_attr("http.response.status_code", 200),
                    ],
                )
            )

    payload = {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        string_attr("service.name", "otel-k8s-span-demo"),
                        string_attr("service.namespace", "platform-observability"),
                        string_attr("service.version", "1.0.0"),
                        string_attr("deployment.environment.name", "lab"),
                        string_attr("k8s.cluster.name", cluster),
                        string_attr("k8s.namespace.name", "otel-k8s-monitoring"),
                    ]
                },
                "scopeSpans": [
                    {
                        "scope": {"name": "aik8s.otel-span-demo", "version": "1.0.0"},
                        "spans": spans,
                    }
                ],
            }
        ]
    }
    return payload, trace_ids


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--endpoint",
        default="http://127.0.0.1:4318/v1/traces",
        help="OTLP/HTTP JSON traces endpoint",
    )
    parser.add_argument("--count", type=int, default=12)
    parser.add_argument("--cluster", default="kubernetes")
    args = parser.parse_args()

    payload, trace_ids = build_payload(args.count, args.cluster)
    request = urllib.request.Request(
        args.endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        body = response.read().decode("utf-8")
        print(f"HTTP {response.status}: {body or '{}'}")
    print("trace_ids:")
    for trace_id in trace_ids:
        print(trace_id)


if __name__ == "__main__":
    main()
