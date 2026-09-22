#!/usr/bin/env python3
"""Build a publishable Qwen-Image-2.1 extended-matrix data set.

The input directories are the runner ``results`` directories.  The generated
CSV and JSON keep default and VAE-tiling attempts separate, preserve failed
requests in the denominator, and include hashes of every source summary.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_cases(engine: str, profile: str, root: Path) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    rows: list[dict[str, Any]] = []
    sources: list[dict[str, str]] = []
    for path in sorted(root.glob("*/summary.json")):
        summary = json.loads(path.read_text(encoding="utf-8"))
        case = summary["case"]
        measured = summary.get("measured", {})
        latency = measured.get("latency_seconds", {})
        rows.append(
            {
                "engine": engine,
                "profile": profile,
                "case": case["id"],
                "kind": case["kind"],
                "size": case["size"],
                "references": len(case.get("references", [])),
                "status": summary["status"],
                "warmup_succeeded": summary.get("warmup", {}).get("succeeded", 0),
                "attempted": measured.get("attempted", 0),
                "succeeded": measured.get("succeeded", 0),
                "failed": measured.get("failed", 0),
                "images_per_minute": measured.get("successful_images_per_minute"),
                "p50_seconds": latency.get("p50"),
                "p95_seconds": latency.get("p95"),
                "wall_seconds": measured.get("wall_seconds"),
            }
        )
        sources.append(
            {
                "engine": engine,
                "profile": profile,
                "case": case["id"],
                "sha256": sha256(path),
            }
        )
    return rows, sources


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sglang-default", type=Path, required=True)
    parser.add_argument("--vllm-default", type=Path, required=True)
    parser.add_argument("--sglang-tiling", type=Path, required=True)
    parser.add_argument("--vllm-tiling", type=Path, required=True)
    parser.add_argument("--sglang-tiling-extra", type=Path)
    parser.add_argument("--vllm-tiling-extra", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    inputs = [
        ("SGLang", "default", args.sglang_default),
        ("vLLM-Omni Preview", "default", args.vllm_default),
        ("SGLang", "vae-tiling", args.sglang_tiling),
        ("vLLM-Omni Preview", "vae-tiling", args.vllm_tiling),
    ]
    if args.sglang_tiling_extra:
        inputs.append(("SGLang", "vae-tiling", args.sglang_tiling_extra))
    if args.vllm_tiling_extra:
        inputs.append(("vLLM-Omni Preview", "vae-tiling", args.vllm_tiling_extra))
    rows: list[dict[str, Any]] = []
    sources: list[dict[str, str]] = []
    for engine, profile, root in inputs:
        loaded_rows, loaded_sources = load_cases(engine, profile, root)
        rows.extend(loaded_rows)
        sources.extend(loaded_sources)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = args.output_dir / "extended-matrix.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    payload = {
        "schema": 1,
        "model": "Qwen/Qwen-Image-2.1",
        "hardware": "1x NVIDIA L20 48 GB per serving process",
        "request": {
            "steps": 40,
            "guidance_scale": 1,
            "warmups_per_case": 1,
            "measured_per_case": 3,
            "client_concurrency": 1,
        },
        "profiles": {
            "default": "Runtime defaults used by the original serving baseline",
            "vae-tiling": "Same request matrix with runtime VAE tiling enabled",
        },
        "results": rows,
        "source_summary_sha256": sources,
    }
    (args.output_dir / "extended-matrix.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"rows": len(rows), "csv": str(csv_path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
