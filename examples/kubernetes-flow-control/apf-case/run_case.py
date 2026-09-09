#!/usr/bin/env python3
"""Bounded APF isolation exercise. Requires kubectl and requests; changes a cluster.

Creates only the reserved apf-case namespace and apf-case-batch APF objects.
Refuses pre-existing names; cleans up its resources in finally.
The independent control reader aborts the exercise after three bad probes.
"""
import argparse
import base64
import concurrent.futures
import json
import math
from pathlib import Path
import subprocess
import tempfile
import threading
import time

import requests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--phase-seconds", type=int, default=90)
    args = parser.parse_args()
    if not 30 <= args.phase_seconds <= 180:
        parser.error("phase-seconds must be between 30 and 180")
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    if (out / "requests.jsonl").exists():
        parser.error("output directory already contains a run")
    manifests = Path(__file__).resolve().parent

    def kubectl(*words):
        return subprocess.check_output(
            ["kubectl", "--context", args.context, "--request-timeout=20s", *words],
            text=True, timeout=30,
        ).strip()

    for kind, name in [("namespace", "apf-case"),
                       ("flowschema", "apf-case-batch"),
                       ("prioritylevelconfiguration", "apf-case-batch")]:
        if kubectl("get", kind, name, "--ignore-not-found", "-o", "name"):
            raise RuntimeError(f"Refusing existing object: {kind}/{name}")
    events, records = [], []
    stop = threading.Event()
    lock = threading.Lock()
    phase = ["setup"]
    slots = threading.BoundedSemaphore(8)
    workers = concurrent.futures.ThreadPoolExecutor(max_workers=9)
    local = threading.local()
    created = False
    log = (out / "requests.jsonl").open("w")

    def event(name, **extra):
        row = {"time": time.time(), "event": name, **extra}
        events.append(row)
        (out / "events.json").write_text(json.dumps(events, indent=2))
        print(json.dumps(row), flush=True)

    try:
        kubectl("create", "namespace", "apf-case")
        created = True
        kubectl("apply", "-f", str(manifests / "fixtures.yaml"))
        kubectl("apply", "-f", str(manifests / "normal.yaml"))
        fs_uid = kubectl("get", "flowschema", "apf-case-batch", "-o", "jsonpath={.metadata.uid}")
        pl_uid = kubectl("get", "prioritylevelconfiguration", "apf-case-batch", "-o", "jsonpath={.metadata.uid}")
        tokens = {actor: kubectl("-n", "apf-case", "create", "token", sa, "--duration=1h")
                  for actor, sa in [("batch", "batch-reader"), ("control", "control-reader")]}
        server = kubectl("config", "view", "--minify", "-o", "jsonpath={.clusters[0].cluster.server}")
        ca_data = kubectl("config", "view", "--raw", "--minify", "-o",
                          "jsonpath={.clusters[0].cluster.certificate-authority-data}")
        if not ca_data:
            raise RuntimeError("This example requires embedded CA data in kubeconfig")
        with tempfile.TemporaryDirectory(prefix="apf-case-") as temp:
            ca = Path(temp) / "ca.crt"
            ca.write_bytes(base64.b64decode(ca_data))
            url = server.rstrip("/") + "/api/v1/namespaces/apf-case/configmaps/fixture?timeout=20s"

            def request(actor, record=True):
                if not hasattr(local, "session"):
                    local.session = requests.Session()
                    local.session.trust_env = False
                started = time.time()
                row = {"start": started, "actor": actor, "phase": phase[0]}
                try:
                    r = local.session.get(url, headers={"Authorization": "Bearer " + tokens[actor],
                                          "User-Agent": "apf-case/1.0"}, verify=str(ca), timeout=(3, 25))
                    row.update(status=r.status_code,
                               matched_case=r.headers.get("X-Kubernetes-PF-FlowSchema-UID") == fs_uid,
                               matched_priority=r.headers.get("X-Kubernetes-PF-PriorityLevel-UID") == pl_uid,
                               retry_after=r.headers.get("Retry-After"))
                except requests.RequestException as exc:
                    row.update(status=0, error=type(exc).__name__)
                row.update(end=time.time(), latency_ms=(time.time() - started) * 1000)
                if record:
                    with lock:
                        records.append(row)
                        log.write(json.dumps(row) + "\n")
                        log.flush()
                return row

            # Confirm actual matching; object creation alone does not prove it.
            for _ in range(15):
                a, b = request("batch", False), request("control", False)
                if a["status"] == b["status"] == 200 and a["matched_case"] and a["matched_priority"] and not b["matched_case"]:
                    break
                time.sleep(1)
            else:
                raise RuntimeError("Actual APF classification did not match the intended boundary")
            event("classification_verified", batch_matches=True, control_matches=False)

            def batch_request():
                try:
                    request("batch")
                finally:
                    slots.release()

            def control_loop():
                bad = 0
                while not stop.is_set():
                    start = time.monotonic()
                    row = request("control")
                    bad = bad + 1 if row["status"] != 200 or row["latency_ms"] > 2000 else 0
                    if bad >= 3:
                        event("guard_abort", reason="three consecutive bad control probes")
                        stop.set()
                    stop.wait(max(0, 1 - (time.monotonic() - start)))

            workers.submit(control_loop)
            for name, filename in [("normal", "normal.yaml"), ("reject", "reject.yaml"),
                                   ("queue", "queue.yaml"), ("recovered", "normal.yaml")]:
                if stop.is_set():
                    raise RuntimeError("Control probe guard aborted the experiment")
                event("policy_apply_begin", phase=name)
                kubectl("apply", "-f", str(manifests / filename))
                phase[0] = name
                event("phase_start", phase=name)
                deadline, next_request = time.monotonic() + args.phase_seconds, time.monotonic()
                while time.monotonic() < deadline and not stop.is_set():
                    if slots.acquire(blocking=False):
                        workers.submit(batch_request)
                    else:
                        event("client_capacity_skip", phase=name)
                    next_request += 0.2  # Offered batch load is capped at 5 req/s; no automatic retries.
                    stop.wait(max(0, next_request - time.monotonic()))
                event("phase_end", phase=name)
            stop.set()
            workers.shutdown(wait=True)
            if any(e["event"] == "guard_abort" for e in events):
                raise RuntimeError("Control guard fired")
            event("experiment_completed")
    finally:
        stop.set()
        # Restoring seats releases queued experiment requests before cleanup.
        if created:
            try:
                kubectl("apply", "-f", str(manifests / "normal.yaml"))
            finally:
                workers.shutdown(wait=True)
                kubectl("delete", "-f", str(manifests / "normal.yaml"), "--ignore-not-found")
                kubectl("delete", "namespace", "apf-case", "--wait=false")
                event("cleanup_requested")
        else:
            workers.shutdown(wait=True)
        log.close()
        summary = []
        for ph in ["normal", "reject", "queue", "recovered"]:
            for actor in ["batch", "control"]:
                rows = [r for r in records if r["phase"] == ph and r["actor"] == actor]
                latencies = sorted(r["latency_ms"] for r in rows)
                counts = {}
                for row in rows:
                    counts[str(row["status"])] = counts.get(str(row["status"]), 0) + 1
                summary.append({"phase": ph, "actor": actor, "requests": len(rows), "status_counts": counts,
                                "client_p50_ms": latencies[math.ceil(len(latencies) * .5) - 1] if latencies else None,
                                "client_p95_ms": latencies[math.ceil(len(latencies) * .95) - 1] if latencies else None,
                                "classification_matches": sum(r.get("matched_case", False) for r in rows)})
        (out / "summary.json").write_text(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
