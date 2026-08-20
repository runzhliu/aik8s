#!/usr/bin/env python3
"""Extract the final ms-swift metrics from an output directory."""

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir")
    parser.add_argument("--world-size", type=int, required=True)
    parser.add_argument("--global-batch", type=int, required=True)
    args = parser.parse_args()

    logs = sorted(Path(args.output_dir).glob("**/logging.jsonl"))
    if not logs:
        raise FileNotFoundError(f"logging.jsonl not found under {args.output_dir}")

    records = [json.loads(line) for line in logs[-1].read_text().splitlines() if line]
    final = next(row for row in reversed(records) if "train_runtime" in row)
    result = {
        "event": "SFT_BENCH_RESULT",
        "world_size": args.world_size,
        "global_batch": args.global_batch,
        "train_runtime_seconds": final["train_runtime"],
        "samples_per_second": final["train_samples_per_second"],
        "steps_per_second": final["train_steps_per_second"],
        "train_loss": final["train_loss"],
        "memory_gib": final.get("memory(GiB)"),
        "logging_file": str(logs[-1]),
    }
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
