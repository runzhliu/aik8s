#!/usr/bin/env python3
"""Disposable CubeSandbox process-memory snapshot acceptance.

Uses CUBE_* SDK connection variables. No secrets or backend object IDs are
included in the emitted report. Creates at most two sandboxes concurrently.
The worker never loads its progress or identity from a file.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import time
from datetime import datetime, timezone
from importlib.metadata import version

from cubesandbox import Sandbox


WORKER = r'''
import hashlib
import json
import os
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

lock = threading.Lock()
counter = 0
held = False
identity = uuid.uuid4().hex  # Generated once; never saved or loaded as a checkpoint.

def value():
    return {"counter": counter, "held": held, "identity": identity,
            "pid": os.getpid(),
            "digest": hashlib.sha256((identity + ":" + str(counter)).encode()).hexdigest()}

def work():
    global counter
    while True:
        with lock:
            if not held:
                counter += 1
        time.sleep(0.1)

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        if self.path != "/state":
            self.send_error(404)
            return
        self.reply()

    def do_POST(self):
        global held
        if self.path not in ("/hold", "/run"):
            self.send_error(404)
            return
        with lock:
            held = self.path == "/hold"
        self.reply()

    def reply(self):
        with lock:
            data = json.dumps(value()).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

threading.Thread(target=work, daemon=True).start()
ThreadingHTTPServer(("127.0.0.1", 18181), Handler).serve_forever()
'''


def run(sandbox, command):
    result = sandbox.commands.run(command, timeout=15)
    if result.exit_code:
        raise RuntimeError("guest_command_failed")
    return (result.stdout or "").strip()


def state(sandbox, action="state"):
    # A fresh loopback connection on every read; no restored external socket.
    script = (
        "import urllib.request; "
        "r=urllib.request.Request('http://127.0.0.1:18181/" + action + "', "
        + ("method='GET'" if action == "state" else "method='POST'")
        + "); print(urllib.request.urlopen(r, timeout=3).read().decode())"
    )
    return json.loads(run(sandbox, "python3 -c " + shlex.quote(script)))


def wait_counter(sandbox, minimum):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        current = state(sandbox)
        if current["counter"] >= minimum:
            return state(sandbox, "hold")
        time.sleep(0.2)
    raise AssertionError("worker_did_not_advance")


def public_state(value):
    # A short one-way identity tag is enough for comparison, not a resource ID.
    return {
        "counter": value["counter"], "held": value["held"],
        "identity_tag": hashlib.sha256(value["identity"].encode()).hexdigest()[:12],
        "pid": value["pid"], "digest": value["digest"],
    }


def require(condition, name):
    if not condition:
        raise AssertionError(name)


def snapshots():
    result, token = Sandbox.list_snapshots()
    identifiers = {item.snapshot_id for item in result}
    while token:
        result, token = Sandbox.list_snapshots(next_token=token)
        identifiers.update(item.snapshot_id for item in result)
    return identifiers


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", default="lab")
    parser.add_argument("--backend-version", default="v0.7.3")
    parser.add_argument("--rounds", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.rounds <= 5:
        parser.error("rounds must be between 1 and 5")
    baseline_sandboxes = {item.get("sandboxID") for item in Sandbox.list()}
    baseline_snapshots = snapshots()
    report = {
        "schema_version": 1,
        "environment": args.environment,
        "backend_version": args.backend_version,
        "sdk_version": version("cubesandbox"),
        "tested_at": datetime.now(timezone.utc).isoformat(),
        "worker_source_sha256": hashlib.sha256(WORKER.encode()).hexdigest(),
        "scope": "SDK process-memory restore; no application checkpoint, no external volume",
        "rounds": [], "result": "FAIL",
    }
    resources = []
    snapshot_ids = []
    try:
        for number in range(1, args.rounds + 1):
            row = {"round": number, "checks": {}, "states": {}, "timings_ms": {}}
            report["rounds"].append(row)
            checks = row["checks"]
            source = Sandbox.create(
                template=os.environ.get("CUBE_TEMPLATE_ID", "sandbox-code"),
                timeout=600, allow_internet_access=False,
                metadata={"purpose": "process-memory-snapshot-acceptance"},
            )
            resources.append(source)
            source.files.write("/tmp/process-memory-probe.py", WORKER)
            run(source, "nohup setsid python3 /tmp/process-memory-probe.py </dev/null >/tmp/process-memory-probe.log 2>&1 &")
            # Startup probes are read-only and have a bounded wait.
            for attempt in range(30):
                try:
                    state(source)
                    break
                except RuntimeError:
                    if attempt == 29:
                        raise
                    time.sleep(0.2)
            captured = wait_counter(source, 10)
            row["states"]["captured"] = public_state(captured)
            source.files.write("/tmp/process-memory-root-marker", "before-snapshot")
            started = time.monotonic()
            snapshot_id = source.create_snapshot().snapshot_id
            snapshot_ids.append(snapshot_id)
            row["timings_ms"]["snapshot"] = round((time.monotonic() - started) * 1000, 2)
            require(state(source) == captured, "snapshot_changed_held_process")
            checks["snapshot_preserved_live_process"] = "PASS"

            state(source, "run")
            advanced = wait_counter(source, captured["counter"] + 10)
            row["states"]["advanced_before_rollback"] = public_state(advanced)
            source.files.write("/tmp/process-memory-root-marker", "after-snapshot")
            # Deliberately kill the guest workload, not the VM or any host process.
            run(source, "kill -KILL " + str(captured["pid"]))
            try:
                state(source)
            except RuntimeError:
                pass
            else:
                raise AssertionError("worker_not_stopped")
            checks["original_worker_killed_before_rollback"] = "PASS"
            started = time.monotonic()
            source.rollback(snapshot_id)
            row["timings_ms"]["rollback"] = round((time.monotonic() - started) * 1000, 2)
            rolled_back = state(source)
            row["states"]["after_rollback"] = public_state(rolled_back)
            require(rolled_back == captured, "rollback_memory_mismatch")
            require(run(source, "cat /tmp/process-memory-root-marker") == "before-snapshot", "rootfs_not_rolled_back")
            checks["rollback_resurrected_same_pid_identity_counter_digest"] = "PASS"
            state(source, "run")
            resumed = wait_counter(source, captured["counter"] + 5)
            require(resumed["identity"] == captured["identity"], "rollback_restarted_worker")
            row["states"]["after_rollback_continued"] = public_state(resumed)
            checks["rollback_worker_continued"] = "PASS"

            source.kill()
            resources.remove(source)
            checks["source_vm_deleted_before_restore"] = "PASS"
            started = time.monotonic()
            restored = Sandbox.create(
                template=snapshot_id, timeout=600, allow_internet_access=False,
                metadata={"purpose": "process-memory-snapshot-restore"},
            )
            resources.append(restored)
            row["timings_ms"]["restore_after_source_deleted"] = round((time.monotonic() - started) * 1000, 2)
            recovered = state(restored)
            row["states"]["new_vm_from_snapshot"] = public_state(recovered)
            require(recovered == captured, "restore_memory_mismatch")
            checks["new_vm_restored_same_pid_identity_counter_digest"] = "PASS"
            state(restored, "run")
            continued = wait_counter(restored, captured["counter"] + 5)
            require(continued["identity"] == captured["identity"], "restore_restarted_worker")
            row["states"]["new_vm_continued"] = public_state(continued)
            checks["new_vm_worker_continued"] = "PASS"
            restored.kill()
            resources.remove(restored)
            Sandbox.delete_snapshot(snapshot_id)
            snapshot_ids.remove(snapshot_id)
            checks["round_resources_deleted"] = "PASS"
        report["result"] = "PASS"
    except Exception as error:
        # Exception text can contain private URLs and IDs. Never emit it publicly.
        report["failure"] = {"type": type(error).__name__}
        if isinstance(error, AssertionError):
            report["failure"]["assertion"] = str(error)
    finally:
        cleanup_errors = []
        for sandbox in reversed(resources):
            try:
                sandbox.kill()
            except Exception as error:
                cleanup_errors.append({"kind": "sandbox", "type": type(error).__name__})
        for snapshot_id in snapshot_ids:
            try:
                Sandbox.delete_snapshot(snapshot_id)
            except Exception as error:
                cleanup_errors.append({"kind": "snapshot", "type": type(error).__name__})
        try:
            final_sandboxes = {item.get("sandboxID") for item in Sandbox.list()}
            final_snapshots = snapshots()
            report["cleanup"] = {
                "errors": cleanup_errors,
                "new_sandboxes_remaining": len(final_sandboxes - baseline_sandboxes),
                "new_snapshots_remaining": len(final_snapshots - baseline_snapshots),
                "baseline_sandboxes_retained": baseline_sandboxes <= final_sandboxes,
                "baseline_snapshots_retained": baseline_snapshots <= final_snapshots,
            }
            if cleanup_errors or final_sandboxes - baseline_sandboxes or final_snapshots - baseline_snapshots:
                report["result"] = "FAIL"
        except Exception as error:
            report["cleanup"] = {"errors": cleanup_errors, "inventory_error": type(error).__name__}
            report["result"] = "FAIL"
        print(json.dumps(report, indent=2, sort_keys=True), flush=True)
    raise SystemExit(0 if report["result"] == "PASS" else 1)


if __name__ == "__main__":
    main()
