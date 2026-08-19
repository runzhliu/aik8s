#!/usr/bin/env python3
"""Summarize repeated vllm bench serve results and optional A/B deltas."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


def number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def integer(value: Any) -> int | None:
    parsed = number(value)
    return int(parsed) if parsed is not None else None


def metadata_value(data: dict[str, Any], key: str) -> Any:
    if key in data:
        return data[key]
    metadata = data.get("metadata")
    if isinstance(metadata, dict):
        return metadata.get(key)
    return None


def mean(values: Iterable[float | None]) -> float | None:
    clean = [value for value in values if value is not None]
    return statistics.fmean(clean) if clean else None


def fmt(value: float | None, digits: int = 1) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def fmt_mean_std(values: Iterable[float | None], digits: int = 1) -> str:
    clean = [value for value in values if value is not None]
    if not clean:
        return "-"
    avg = statistics.fmean(clean)
    if len(clean) == 1:
        return fmt(avg, digits)
    spread = statistics.stdev(clean)
    return f"{avg:.{digits}f} ± {spread:.{digits}f}"


def load_gpu_counts(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as handle:
        return {
            row["profile_id"]: int(row["gpu_count"])
            for row in csv.DictReader(handle)
            if row.get("profile_id") and row.get("gpu_count")
        }


def infer_identity(path: Path, data: dict[str, Any]) -> tuple[str, str]:
    profile = metadata_value(data, "profile")
    case_id = metadata_value(data, "case_id")
    parts = path.stem.split("__")
    if not profile and len(parts) >= 2:
        profile = parts[0]
    if not case_id and len(parts) >= 2:
        case_id = parts[1]
    return str(profile or "unknown"), str(case_id or path.stem)


def load_results(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    results: list[dict[str, Any]] = []
    skips: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"warning: ignoring {path}: {exc}")
            continue
        if data.get("status") == "SKIP_UNSUPPORTED" or path.name.endswith(".skip.json"):
            skips.append(data)
            continue
        profile, case_id = infer_identity(path, data)
        data["_profile"] = profile
        data["_case_id"] = case_id
        results.append(data)
    return results, skips


def aggregate(results: list[dict[str, Any]], gpu_counts: dict[str, int]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        grouped[(result["_profile"], result["_case_id"])].append(result)

    rows: list[dict[str, Any]] = []
    for (profile, case_id), runs in sorted(grouped.items()):
        output_tps = [number(run.get("output_throughput")) for run in runs]
        gpu_count = gpu_counts.get(profile) or integer(metadata_value(runs[0], "gpu_count"))
        avg_output_tps = mean(output_tps)
        rows.append(
            {
                "profile": profile,
                "case_id": case_id,
                "runs": len(runs),
                "completed": sum(integer(run.get("completed")) or 0 for run in runs),
                "failed": sum(integer(run.get("failed")) or 0 for run in runs),
                "request_tps_values": [number(run.get("request_throughput")) for run in runs],
                "output_tps_values": output_tps,
                "output_tps": avg_output_tps,
                "tokens_per_gpu": avg_output_tps / gpu_count if avg_output_tps is not None and gpu_count else None,
                "p95_ttft_values": [number(run.get("p95_ttft_ms")) for run in runs],
                "p95_tpot_values": [number(run.get("p95_tpot_ms")) for run in runs],
                "p95_e2el_values": [number(run.get("p95_e2el_ms")) for run in runs],
            }
        )
    return rows


def render_summary(rows: list[dict[str, Any]], skips: list[dict[str, Any]]) -> str:
    lines = [
        "# Benchmark summary",
        "",
        "| Profile | Case | Runs | Completed / Failed | Req/s | Output tok/s | Output tok/s/GPU | p95 TTFT ms | p95 TPOT ms | p95 E2E ms |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        request_tps_text = fmt_mean_std(row["request_tps_values"], 3)
        output_tps_text = fmt_mean_std(row["output_tps_values"], 1)
        tokens_per_gpu_text = fmt(row["tokens_per_gpu"], 2)
        ttft_text = fmt_mean_std(row["p95_ttft_values"], 1)
        tpot_text = fmt_mean_std(row["p95_tpot_values"], 1)
        e2el_text = fmt_mean_std(row["p95_e2el_values"], 1)
        lines.append(
            f"| {row['profile']} | {row['case_id']} | {row['runs']} | "
            f"{row['completed']} / {row['failed']} | {request_tps_text} | "
            f"{output_tps_text} | {tokens_per_gpu_text} | {ttft_text} | "
            f"{tpot_text} | {e2el_text} |"
        )
    if skips:
        lines.extend(["", "## Unsupported cases", "", "| Profile | Case | Required context | Configured max |", "|---|---|---:|---:|"])
        for skip in skips:
            lines.append(
                f"| {skip.get('profile', '-')} | {skip.get('case_id', '-')} | {skip.get('required_context', '-')} | {skip.get('max_context', '-')} |"
            )
    return "\n".join(lines) + "\n"


def reduction(baseline: float | None, candidate: float | None) -> float | None:
    if baseline in (None, 0) or candidate is None:
        return None
    return (baseline - candidate) / baseline * 100


def increase(baseline: float | None, candidate: float | None) -> float | None:
    if baseline in (None, 0) or candidate is None:
        return None
    return (candidate / baseline - 1) * 100


def render_comparison(rows: list[dict[str, Any]], baseline: str, candidate: str) -> str:
    by_key = {(row["profile"], row["case_id"]): row for row in rows}
    cases = sorted(
        case_id for profile, case_id in by_key
        if profile == baseline and (candidate, case_id) in by_key
    )
    lines = [
        f"## A/B: `{candidate}` vs `{baseline}`",
        "",
        "Positive throughput means faster. Positive latency reduction means lower latency.",
        "",
        "| Case | Output tok/s Δ | Output tok/s/GPU Δ | p95 TTFT reduction | p95 TPOT reduction | p95 E2E reduction |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for case_id in cases:
        base = by_key[(baseline, case_id)]
        cand = by_key[(candidate, case_id)]
        lines.append(
            "| {case_id} | {throughput} | {per_gpu} | {ttft} | {tpot} | {e2el} |".format(
                case_id=case_id,
                throughput=fmt(increase(base["output_tps"], cand["output_tps"]), 1) + "%",
                per_gpu=fmt(increase(base["tokens_per_gpu"], cand["tokens_per_gpu"]), 1) + "%",
                ttft=fmt(reduction(mean(base["p95_ttft_values"]), mean(cand["p95_ttft_values"])), 1) + "%",
                tpot=fmt(reduction(mean(base["p95_tpot_values"]), mean(cand["p95_tpot_values"])), 1) + "%",
                e2el=fmt(reduction(mean(base["p95_e2el_values"]), mean(cand["p95_e2el_values"])), 1) + "%",
            )
        )
    if not cases:
        lines.append("| _No matching cases_ | - | - | - | - | - |")
    return "\n".join(lines) + "\n"


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = ["profile", "case_id", "runs", "completed", "failed", "request_throughput", "output_throughput", "output_tokens_per_gpu", "p95_ttft_ms", "p95_tpot_ms", "p95_e2el_ms"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "profile": row["profile"], "case_id": row["case_id"],
                    "runs": row["runs"], "completed": row["completed"], "failed": row["failed"],
                    "request_throughput": mean(row["request_tps_values"]),
                    "output_throughput": row["output_tps"], "output_tokens_per_gpu": row["tokens_per_gpu"],
                    "p95_ttft_ms": mean(row["p95_ttft_values"]), "p95_tpot_ms": mean(row["p95_tpot_values"]),
                    "p95_e2el_ms": mean(row["p95_e2el_values"]),
                }
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result_dir", type=Path)
    parser.add_argument("--profiles", type=Path, default=Path(__file__).with_name("profiles.csv"))
    parser.add_argument("--baseline", help="baseline profile for A/B table")
    parser.add_argument("--candidate", help="candidate profile for A/B table")
    parser.add_argument("--output", type=Path, help="write Markdown to this file")
    parser.add_argument("--csv", type=Path, help="also write aggregate CSV")
    args = parser.parse_args()

    if bool(args.baseline) != bool(args.candidate):
        parser.error("--baseline and --candidate must be used together")
    if not args.result_dir.exists():
        parser.error(f"result directory does not exist: {args.result_dir}")

    results, skips = load_results(args.result_dir)
    rows = aggregate(results, load_gpu_counts(args.profiles))
    markdown = render_summary(rows, skips)
    if args.baseline and args.candidate:
        markdown += "\n" + render_comparison(rows, args.baseline, args.candidate)
    if args.output:
        args.output.write_text(markdown, encoding="utf-8")
    else:
        print(markdown, end="")
    if args.csv:
        write_csv(args.csv, rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
