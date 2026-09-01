#!/usr/bin/env python3
"""Aggregate vLLM benchmark JSON files without third-party dependencies."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any


METRICS = (
    "request_throughput",
    "output_throughput",
    "total_token_throughput",
    "p50_ttft_ms",
    "p95_ttft_ms",
    "p50_tpot_ms",
    "p95_tpot_ms",
    "p50_e2el_ms",
    "p95_e2el_ms",
)


def load_runs(paths: list[Path], excluded_names: set[str]) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    for root in paths:
        candidates = [root] if root.is_file() else sorted(root.rglob("*.json"))
        for candidate in candidates:
            if candidate.name in excluded_names:
                continue
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict) or not data.get("case_id"):
                continue
            data["source"] = str(candidate)
            runs.append(data)
    return runs


def median_number(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [float(row[key]) for row in rows if isinstance(row.get(key), (int, float))]
    return statistics.median(values) if values else None


def aggregate(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for run in runs:
        key = (
            str(run.get("engine", "unknown")),
            str(run.get("run_label", "unknown")),
            str(run["case_id"]),
        )
        grouped[key].append(run)

    summary: list[dict[str, Any]] = []
    for (engine, run_label, case_id), rows in sorted(grouped.items()):
        item: dict[str, Any] = {
            "engine": engine,
            "run_label": run_label,
            "case_id": case_id,
            "repeats": len(rows),
            "successful_requests": sum(int(row.get("completed", 0)) for row in rows),
            "failed_requests": sum(int(row.get("failed", 0)) for row in rows),
        }
        for metric in METRICS:
            item[f"median_{metric}"] = median_number(rows, metric)
        summary.append(item)
    return summary


def format_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0]) if rows else ["engine", "run_label", "case_id"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = (
        "engine",
        "case_id",
        "repeats",
        "successful_requests",
        "failed_requests",
        "median_output_throughput",
        "median_total_token_throughput",
        "median_p50_ttft_ms",
        "median_p95_ttft_ms",
        "median_p50_tpot_ms",
        "median_p50_e2el_ms",
    )
    labels = (
        "Engine",
        "Case",
        "N",
        "OK",
        "Failed",
        "Output tok/s",
        "Total tok/s",
        "P50 TTFT ms",
        "P95 TTFT ms",
        "P50 TPOT ms",
        "P50 E2E ms",
    )
    lines = ["| " + " | ".join(labels) + " |", "|" + "---|" * len(columns)]
    for row in rows:
        lines.append("| " + " | ".join(format_value(row.get(column)) for column in columns) + " |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--exclude", action="append", default=[], metavar="FILENAME")
    parser.add_argument("--csv", type=Path)
    parser.add_argument("--markdown", type=Path)
    args = parser.parse_args()

    rows = aggregate(load_runs(args.paths, set(args.exclude)))
    if args.csv:
        write_csv(args.csv, rows)
    if args.markdown:
        write_markdown(args.markdown, rows)
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
