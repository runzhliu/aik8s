#!/usr/bin/env python3
"""Fail a benchmark gate on partial success or truncated forced-length output."""
import json
from pathlib import Path
import sys


def validate(path: Path, prompts: int, output_tokens: int) -> dict:
    result = json.loads(path.read_text())
    if result.get("completed") != prompts:
        raise ValueError(f"completed={result.get('completed')}, expected={prompts}")
    if result.get("failed", 0) != 0:
        raise ValueError("benchmark contains failed requests")
    expected_tokens = prompts * output_tokens
    if result.get("total_output_tokens") != expected_tokens:
        raise ValueError(f"output tokens={result.get('total_output_tokens')}, expected={expected_tokens}")
    if any(result.get("errors") or []):
        raise ValueError("benchmark contains request errors")
    return {"status": "PASS", "file": path.name, "completed": prompts,
            "total_output_tokens": expected_tokens}


if __name__ == "__main__":
    print(json.dumps(validate(Path(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]))))
