#!/usr/bin/env python3
"""Build sanitized, reproducible summaries from the archived Qwen3.8 run."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from statistics import mean, median


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUN = ROOT / ".local/qwen38-night/runs/day-0912-a5"
DEFAULT_OUT = ROOT / "docs/assets/practices/qwen38-a95b-h20"
METRICS = (
    "request_throughput",
    "output_throughput",
    "total_token_throughput",
    "mean_ttft_ms",
    "p95_ttft_ms",
    "mean_tpot_ms",
    "p95_tpot_ms",
    "mean_e2el_ms",
    "p95_e2el_ms",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def finite_values(payload: dict) -> list[float]:
    values: list[float] = []
    for series in payload.get("data", {}).get("result", []):
        for _, raw in series.get("values", []):
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            if math.isfinite(value):
                values.append(value)
    return values


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] * (high - position) + ordered[high] * (position - low)


def stats(values: list[float], scale: float = 1.0) -> dict:
    scaled = [value / scale for value in values]
    if not scaled:
        return {"samples": 0}
    return {
        "samples": len(scaled),
        "mean": mean(scaled),
        "p50": percentile(scaled, 0.50),
        "p95": percentile(scaled, 0.95),
        "max": max(scaled),
    }


def aggregate_case(rows: list[dict]) -> dict:
    first = rows[0]
    summary = {
        "case_id": first["case_id"],
        "stage": first["stage"],
        "input_tokens": first["input_tokens"],
        "output_tokens": first["output_tokens"],
        "concurrency": first["concurrency"],
        "rounds": len(rows),
        "completed_requests": sum(row["completed"] for row in rows),
        "metrics": {},
    }
    for metric in METRICS:
        values = [row[metric] for row in rows if row.get(metric) is not None]
        summary["metrics"][metric] = {
            "median": median(values),
            "min": min(values),
            "max": max(values),
        }
    return summary


def build(run: Path, output: Path) -> dict:
    result_root = run / "evidence/client/results/sglang"
    suite_path = result_root / "suite-status.json"
    suite = json.loads(suite_path.read_text())
    public_rows: list[dict] = []
    grouped: dict[str, list[dict]] = {}

    for row in suite["rows"]:
        if row["status"] != "PASS":
            continue
        result_path = result_root / row["stage"] / row["id"] / "measurement/result.json"
        result = json.loads(result_path.read_text())
        record = {
            "case_id": row["case_id"],
            "stage": row["stage"],
            "repeat": row["repeat"],
            "input_tokens": row["input_tokens"],
            "output_tokens": row["output_tokens"],
            "concurrency": row["concurrency"],
            "completed": result["completed"],
            "failed": result["failed"],
            "duration_seconds": result["duration"],
            **{metric: result.get(metric) for metric in METRICS},
            "result_sha256": sha256(result_path),
        }
        public_rows.append(record)
        grouped.setdefault(row["case_id"], []).append(record)

    contexts = []
    context_root = run / "evidence/client/contexts/sglang"
    for context_dir in sorted(context_root.iterdir(), key=lambda path: int(path.name)):
        path = context_dir / "needle.json"
        payload = json.loads(path.read_text())
        usage = payload["usage"]
        contexts.append({
            "configured_context_tokens": payload["max_context"],
            "server_prompt_tokens": usage["prompt_tokens"],
            "completion_tokens": usage["completion_tokens"],
            "reasoning_tokens": usage.get("reasoning_tokens"),
            "needle_depth": payload["depth"],
            "status": payload["status"],
            "result_sha256": sha256(path),
        })

    grafana = run / "evidence/sglang/grafana"
    gpu_metrics = {}
    gpu_definitions = {
        "utilization_percent": ("panel1", 1.0),
        "framebuffer_used_mib": ("panel2", 1024 * 1024),
        "power_watts": ("panel3", 1.0),
        "sm_clock_mhz": ("panel4", 1_000_000),
    }
    for name, (panel, scale) in gpu_definitions.items():
        values = []
        for rank in range(4):
            payload = json.loads((grafana / f"sglang-gpu-rank-{rank}-{panel}.json").read_text())
            values.extend(finite_values(payload))
        gpu_metrics[name] = stats(values, scale)

    client_metrics = {}
    client_definitions = {
        "sliding_p95_ttft_seconds": "panel1",
        "sliding_p95_tpot_seconds": "panel2",
        "successful_output_tokens_per_second": "panel3",
        "sliding_p95_e2e_seconds": "panel4",
    }
    for name, panel in client_definitions.items():
        payload = json.loads((grafana / f"sglang-client-rank-0-{panel}.json").read_text())
        client_metrics[name] = stats(finite_values(payload))

    rdma_metrics = {}
    for name, panel in (("transmit_bytes_per_second", "panel1"), ("receive_bytes_per_second", "panel2")):
        payload = json.loads((grafana / f"sglang-rdma-rank-0-{panel}.json").read_text())
        rdma_metrics[name] = stats(finite_values(payload), 1024 ** 3)
        rdma_metrics[name]["unit"] = "GiB/s per sampled node series"

    status_counts = {key: int(value) for key, value in suite["counts"].items()}
    summary = {
        "model": "Qwen3.8-2.4T-A95B-FP8",
        "engine": "SGLang",
        "hardware": "4 nodes x 8 NVIDIA H20-3e (32 GPUs)",
        "parallelism": "TP8 x PP4",
        "result_scope": {
            "planned_rounds": sum(status_counts.values()),
            "passed_rounds": status_counts.get("PASS", 0),
            "failed_rounds": status_counts.get("FAILED", 0),
            "not_executed_rounds": status_counts.get("NOT_EXECUTED", 0),
            "context_limited_rows": status_counts.get("SKIPPED", 0),
            "completed_formal_requests": sum(row["completed"] for row in public_rows),
            "vllm": "NOT_EXECUTED_BY_SCOPE",
        },
        "cases": [aggregate_case(rows) for rows in grouped.values()],
        "contexts": contexts,
        "telemetry": {
            "window": "full SGLang performance-suite window",
            "gpu": gpu_metrics,
            "client": client_metrics,
            "rdma": rdma_metrics,
        },
        "source_receipts": {
            "suite_status_sha256": sha256(suite_path),
            "grafana_evidence_sha256": sha256(grafana / "grafana-evidence.json"),
        },
    }

    output.mkdir(parents=True, exist_ok=True)
    (output / "benchmark-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    )
    with (output / "benchmark-rounds.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(public_rows[0]))
        writer.writeheader()
        writer.writerows(public_rows)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    print(json.dumps(build(args.run, args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
