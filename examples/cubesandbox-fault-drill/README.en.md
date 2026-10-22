[简体中文](README.md) | [English](README.en.md)

# CubeSandbox component failure drills

Companion article: [failure drills and recovery](../../translations/en/ai-k8s/rag-agent/cubesandbox-failure-recovery-practice.md). These programs suspend components, scale services down, or delete the compute Pod in a dedicated, idle, recoverable test installation. They are not read-only diagnostics and should not be run against active business workloads.

`results.json` contains 13 verified-v0.7.3 attempts covering 12 profiles, plus 10 explicitly separated historical attempts. Eleven profiles reached fault injection; the HTTP path-rule profile did not because its allowed baseline failed. Compute Pod recreation failed twice. `MEASURED` does not mean business acceptance passed: inspect `controller_result`, `task_recovered`, cleanup, and `manual_recovery_attempts`. `receiver-events.csv` contains 5296 sanitized per-request records, with window counts cross-checked during export.

## Files

| File | Purpose |
| --- | --- |
| `render.py` | Render separate receivers and an optional VMServiceScrape; no CubeSandbox installation changes |
| `observer.py` | Independent HTTP receivers, metrics, and a lab-only API / CubeProxy bridge |
| `guest_probe.py` | In-memory counter, random identity, snapshot hold, and A/B requests |
| `run_drill.py` | Run one case sequentially; save private evidence and source hashes |
| `process_guard.py` | Exact process identity; forbid PID 1; verify start time and command hash |
| `watchdog.py` | Independent recovery of only the currently armed resources |
| `dashboard.py` | Render a separate Grafana dashboard ConfigMap |
| `export_results.py` | Allowlist-based sanitization, count cross-checks, public JSON / CSV |
| `index.html` | Bilingual custom evidence viewer, not the official Console |

## Installation and receivers

Requirements: a working CubeSandbox 0.7.3 installation, matching SDK, `requests`, `kubectl`, Python 3, KVM access, and exclusive use of the fault scope. The installation must have no other sandboxes. Save original workloads and replica counts and record existing virtual-machine UIDs. Preserve existing templates and volumes. No production upgrade automation is provided.

```bash
python3 -m venv .local/cube-drill/venv
.local/cube-drill/venv/bin/pip install cubesandbox==0.7.3 requests
python3 examples/cubesandbox-fault-drill/render.py \
  --image python:3.12-slim --node REPLACE_TEST_NODE \
  --scrape-namespace victoriametrics \
  --output .local/cube-drill/receivers.json
kubectl --context lab-cluster apply -f .local/cube-drill/receivers.json
kubectl --context lab-cluster -n cube-fault-lab rollout status deploy/cube-fault-allow
kubectl --context lab-cluster -n cube-fault-lab rollout status deploy/cube-fault-deny
```

Use an environment-approved image with Python 3 and its standard library. The actual experiment reused an existing cached lab image. Without the VictoriaMetrics Operator, omit `--scrape-namespace` and add an equivalent Prometheus scrape. Do not overwrite shared monitoring Helm values.

Run these forwards in separate terminals and retain them until evidence is exported:

```bash
kubectl --context lab-cluster -n cube-fault-lab port-forward svc/cube-fault-allow 18971:8080
kubectl --context lab-cluster -n cube-fault-lab port-forward svc/cube-fault-deny 18972:8080
```

The observer forwards `/cubeapi/` and requests preserving a `*.cube.app` Host to installation Services, keeping the local SDK endpoint stable while control Pods change IPs. This unauthenticated bridge is for the isolated lab only; never expose it publicly. Its timeout is 8 seconds. A timed-out operation may already have had server-side effects, so cleanup must inspect resource inventory.

## Private configuration and version verification

Save `.local/cube-drill/private/settings.json` with the two actual receiver Pod IPs, not Service ClusterIPs:

```json
{
  "context": "lab-cluster",
  "namespace": "cube-system",
  "observer": "http://127.0.0.1:18971",
  "deny_observer": "http://127.0.0.1:18972",
  "observer_port": 18971,
  "template": "REPLACE_VERIFIED_TEMPLATE_ALIAS",
  "ips": {"allow": "192.0.2.10", "deny": "192.0.2.11"},
  "variant": "describe-your-actual-installation",
  "required_shim_sha256": "REPLACE_ACTUAL_EXECUTABLE_SHA256"
}
```

Image tags, template bindings, and the actual executable are separate checks. First create a sandbox and verify its Rust Shim manifest and SHA-256. The program refuses injection when the executable hash differs. The official package hash used here is in `results.json`; a separately built package need not share it. Record any guest-versus-egress CIDR configuration differences independently.

## Execution, watchdog, and stop conditions

Start the independent watchdog first, then run one case in another terminal. Supported cases are `api`, `master`, `ops`, `proxy`, `cubelet`, `vmm`, `mysql`, `redis`, `minio`, `egress`, and `pod`. Use a new attempt each time; existing records are never overwritten.

```bash
.local/cube-drill/venv/bin/python examples/cubesandbox-fault-drill/watchdog.py \
  --config .local/cube-drill/private/settings.json
```

```bash
.local/cube-drill/venv/bin/python examples/cubesandbox-fault-drill/run_drill.py \
  --config .local/cube-drill/private/settings.json --case vmm --attempt a01
.local/cube-drill/venv/bin/python examples/cubesandbox-fault-drill/run_drill.py \
  --config .local/cube-drill/private/settings.json --case egress --policy l3 --attempt a02
```

Before running the fault program, independently verify that A and B are both reachable when both are allowed, recording the runtime and configuration. `run_drill.py` itself performs only a restricted baseline per case; it does not remove rules and repeat an unrestricted control. Injection requires at least 10 seconds of observation, at least 3 cumulative A receipts, and 0 B receipts. This experiment's separate unrestricted preflight did not record runtime hashes equivalent to the formal matrix, a limitation now explicit in the article. HTTP path-rule mode uses `--case egress --policy l7`, comparing allowed and denied paths on port 80 of the same receiver Pod A. No fault is injected if the allowed-path baseline fails. In Pod-network mode, `--case pod` is destructive and should run last. Add `--retain-failed-snapshot` when preserving a failure for manual investigation, with separate cleanup arranged. The watchdog restores replica counts and exact suspended processes; it cannot restore a vanished namespace or fix snapshot registration.

After each case, inspect component recovery, task continuity, receiver records, new-task execution and deletion, and cleanup. Stop further injection if baseline health cannot be restored. Never automatically clear bpffs, CNI, or OVS. Orphan-map cleanup in this experiment was a manual operation after confirming no CubeSandbox VMs remained, not a generic online repair script.

## Export and view

```bash
.local/cube-drill/venv/bin/python examples/cubesandbox-fault-drill/export_results.py \
  --evidence-dir .local/cube-drill --output .local/cube-drill/public
```

The exporter has version and follow-up filename conventions specific to this experiment. Review these for a new run, preserve private originals, and do not overwrite the repository's measured results. Serve `index.html` beside the exported JSON using `python3 -m http.server`. To inspect the committed results directly:

```bash
python3 -m http.server 18975 --bind 127.0.0.1 --directory examples/cubesandbox-fault-drill
```

Open `http://127.0.0.1:18975/?group=runtime`; append `#en` for English. Real Grafana screenshots are in the article. Change the generator's datasource UID to your actual UID and import using your existing dashboard-sidecar labels. The generator does not change shared Grafana access permissions.

At completion, components and temporary configuration were restored, no experimental VM was running, and the original five VMs retained their UIDs. Failed-snapshot cleanup remains outstanding because its replica references an obsolete Pod endpoint. This is explicitly retained in the results and does not constitute successful Pod-recreation recovery.
