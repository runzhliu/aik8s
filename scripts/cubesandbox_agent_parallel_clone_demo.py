#!/usr/bin/env python3
"""Clone one prepared CubeSandbox into parallel Agent workspaces."""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List

from cubesandbox import Sandbox


def main() -> None:
    base = None
    clones: List[Sandbox] = []
    result: Dict[str, Any] = {}

    try:
        base = Sandbox.create(
            template=os.environ["CUBE_TEMPLATE_ID"],
            timeout=300,
            allow_internet_access=False,
            metadata={
                "runtime": "openclaw-or-dsh",
                "purpose": "parallel-agent-demo",
            },
        )
        base.files.write("/tmp/plan.txt", "baseline")
        base.run_code("score = 0")

        started_at = time.perf_counter()
        snapshot = base.create_snapshot("before-parallel-agents")
        result["snapshot_ms"] = round((time.perf_counter() - started_at) * 1000)
        result["snapshot_ref"] = snapshot.snapshot_id[:8]

        base.files.write("/tmp/plan.txt", "unsafe-change")
        started_at = time.perf_counter()
        base.rollback(snapshot.snapshot_id)
        result["rollback_ms"] = round((time.perf_counter() - started_at) * 1000)
        result["base_after_rollback"] = base.files.read("/tmp/plan.txt")

        started_at = time.perf_counter()
        clones = base.clone(n=2, concurrency=2)
        result["clone_two_ms"] = round((time.perf_counter() - started_at) * 1000)

        strategies = ["minimal-fix", "refactor"]
        clone_results = []
        for clone, strategy in zip(clones, strategies):
            clone.files.write("/tmp/plan.txt", strategy)
            output = clone.commands.run("cat /tmp/plan.txt").stdout
            clone_results.append(output)

        result["clone_results"] = clone_results
        result["base_after_clones"] = base.files.read("/tmp/plan.txt")
        result["isolated"] = (
            result["base_after_rollback"] == "baseline"
            and clone_results == strategies
            and result["base_after_clones"] == "baseline"
        )
    finally:
        for clone in clones:
            clone.kill()
        if base is not None:
            base.kill()
        result["cleanup"] = "destroyed"

    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
