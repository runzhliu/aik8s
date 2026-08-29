#!/usr/bin/env python3
"""Run user-supplied Python code in a short-lived CubeSandbox MicroVM."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict

from cubesandbox import Sandbox


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--python-code")
    source.add_argument("--python-file", type=Path)
    parser.add_argument("--hold-seconds", type=int, default=0, choices=range(0, 61))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    code = args.python_code
    if args.python_file is not None:
        code = args.python_file.read_text(encoding="utf-8")

    sandbox = None
    result: Dict[str, Any] = {
        "executor": "cubesandbox-microvm",
    }

    try:
        started_at = time.perf_counter()
        sandbox = Sandbox.create(
            timeout=120,
            allow_internet_access=False,
            network={"allow_public_traffic": False},
            metadata={
                "runtime": "dsh",
                "purpose": "agent-skill-task",
            },
        )
        result["create_ms"] = round((time.perf_counter() - started_at) * 1000)
        result["sandbox_ref"] = sandbox.sandbox_id[:8]

        sandbox.files.write("/tmp/dsh-agent-task.py", code)
        execution = sandbox.commands.run("python3 /tmp/dsh-agent-task.py")
        result["exit_code"] = execution.exit_code
        result["stdout"] = execution.stdout
        result["stderr"] = execution.stderr

        network = sandbox.commands.run(
            "python3 -c \"import socket; "
            "s=socket.socket(); s.settimeout(1); "
            "s.connect(('1.1.1.1', 80))\"",
        )
        result["internet_blocked"] = network.exit_code != 0
        result["hold_seconds"] = args.hold_seconds
        if args.hold_seconds:
            time.sleep(args.hold_seconds)
    finally:
        if sandbox is not None:
            sandbox.kill()
            result["cleanup"] = "destroyed"

    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
