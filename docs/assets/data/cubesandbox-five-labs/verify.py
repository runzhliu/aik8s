"""Recalculate the published checks. Run beside the downloaded JSON files."""
import json
import math
import re
import sqlite3
import statistics
import sys
from pathlib import Path


def prewarm(data):
    rows = data["rows"]
    print("SQLite FTS5  |  16,000 documents  |  20 alternating pairs\n")
    print("Cumulative latency (ms)    Lazy P50   Warm P50   Lazy P95   Warm P95")
    for field, name in [("create_ms", "Create returned"), ("ready_ms", "Tool ready"),
                        ("first_result_ms", "First valid result")]:
        groups = [sorted(row[field] for row in rows if row["mode"] == mode)
                  for mode in ("lazy", "warm")]
        assert all(len(values) == 20 for values in groups)
        quantiles = [statistics.median(values) for values in groups]
        quantiles += [values[math.ceil(.95 * len(values)) - 1] for values in groups]
        print(f"{name:24}" + "".join(f"{x:11.1f}" for x in quantiles))
    assert not data["errors"] and all(row["hits"] == 19 for row in rows)
    assert len(data["model_checks"]) == 2 and all(v["matches"] for v in data["model_checks"])
    print("\n40/40 queries returned 19 hits. Both follow-up model replies matched.")
    paired = {}
    for row in rows:
        modes = paired.setdefault(row["round"], {})
        assert row["mode"] not in modes
        modes[row["mode"]] = row["first_result_ms"]
    assert len(paired) == 20 and all(set(modes) == {"lazy", "warm"} for modes in paired.values())
    savings = [modes["lazy"] - modes["warm"] for modes in paired.values()]
    print(f"Paired first-result saving: median {statistics.median(savings):.1f} ms, mean {statistics.mean(savings):.1f} ms")
    for mode in ("lazy", "warm"):
        group = [r for r in rows if r["mode"] == mode]
        ready = statistics.median(r["ready_ms"] - r["create_ms"] for r in group)
        query = statistics.median(r["first_result_ms"] - r["ready_ms"] for r in group)
        print(f"{mode}: median create-to-ready {ready:.1f} ms, ready-to-result {query:.1f} ms")
        for limit in (500, 600, 1000):
            count = sum(r["first_result_ms"] <= limit for r in group)
            print(f"  within {limit} ms: {count}/{len(group)}")


def edits(data):
    print("Baseline: fee(12345) = 0  |  inputs: 0, 99, 100, 12345 cents\n")
    for item, rate in zip(data["agents"], (5, 8)):
        assert item["fees"] == [x * rate // 100 for x in (0, 99, 100, 12345)]
        assert item["base_clean"]
        patch = item["patch"]
        paths = [line.split(" b/")[1] for line in patch.splitlines() if line.startswith("diff --git")]
        print(f"Agent {item['branch']} / {rate}%    {item['fees']}")
        print("  " + ", ".join(paths) + "\n")
        shared_expected = [0, 4, 5, 617]
        passed = sum(actual == expected for actual, expected in zip(item["fees"], shared_expected))
        print(f"  Shared 5% acceptance policy: {passed}/{len(shared_expected)}")
    assert data["accepted"] == "A" and data["conflicting_patch_rejected"] and data["parent_base_clean"]
    print("Review: patch A applied; legacy.txt removed; fee(12345) = 617")
    print("git apply --check: patch B rejected against A; base still clean.")


def skills(data):
    print(f"Saved input: {data['input']}  |  first action: {data['initial_action']}\n")
    for item in data["sessions"]:
        print(f"Session {item['name']} / {item['opened']:16}  v{item['installed']}  {item['output']}")
    a, b, c = [s["output"] for s in data["sessions"]]
    assert a == c == "total=42" and json.loads(b) == {"schema": 2, "total": 42}
    assert data["same_a_input_after_switch"] == data["input"] and data["b_after_rollback"] == b
    print("\nAfter rollback: C used v1; the v2 result in B was still readable.")
    for label, output in (("A", a), ("B", b), ("C", c)):
        match = re.fullmatch(r"total=(-?[0-9]+)", output)
        try:
            obj = json.loads(output)
        except json.JSONDecodeError:
            obj = None
        json_ok = isinstance(obj, dict) and obj.get("schema") == 2 and type(obj.get("total")) is int
        legacy_result = int(match[1]) if match else None
        json_result = obj["total"] if json_ok else None
        expected = (None, 42) if label == "B" else (42, None)
        assert (legacy_result, json_result) == expected
        print(f"Session {label}: legacy reader={legacy_result}, JSON v2 reader={json_result}")


def observability(data):
    print(f"Release {data['release']}  /  isolated source {data['source']}\n")
    assert data["same_sandbox_in_log_query_and_deliveries"]
    print(f"Log query       {data['log_records']} records     {', '.join(data['log_fields'])}")
    assert data["event_id_stable"] and data["distinct_delivery_ids"] == 2
    assert data["receiver_http"] == [503, 204]
    print(f"Webhook         {data['event_type']}   HTTP 503 -> 204")
    print("                same event ID; different delivery IDs\n")
    for span in data["otel"]:
        print(f"{span['name']:40} {span['status']}")
    print(f"\nSeparate receiver-timeout test: {data['timeout_test_attempts']} attempts.")
    db = sqlite3.connect(":memory:")
    try:
        db.execute("""CREATE TABLE work_inbox (
            consumer TEXT NOT NULL, event_id TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'pending', PRIMARY KEY (consumer, event_id))""")
        for _ in range(2):
            with db:
                db.execute("""INSERT INTO work_inbox (consumer, event_id) VALUES (?, ?)
                    ON CONFLICT (consumer, event_id) DO NOTHING""", ("inventory", "example-event-1"))
        pending = db.execute("SELECT count(*) FROM work_inbox WHERE state = 'pending'").fetchone()[0]
        assert pending == 1
        print(f"Local SQLite example: two receipts of one synthetic event -> {pending} pending task.")
    finally:
        db.close()


if __name__ == "__main__":
    checks = {"prewarm": prewarm, "edits": edits, "skills": skills, "observability": observability}
    name = sys.argv[1]
    checks[name](json.loads(Path(__file__).with_name(name + ".json").read_text()))
