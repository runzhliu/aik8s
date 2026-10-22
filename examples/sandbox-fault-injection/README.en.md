# Sandbox fault and network-restriction experiment

[简体中文](README.md) · [Public article](../../translations/en/ai-k8s/rag-agent/sandbox-runtime-failure-network-policy.md)

Dedicated fault Pods run Microsandbox 0.7.8 / BoxLite 0.10.7. Cases kill a detached SDK client, kill the KVM-owning VMM, or recreate its hosting Pod. Independent receivers represent allowed and denied destinations. `results.json` retains formal measurements, controls, failed/interrupted attempts, and untested scope.

Prepare the images, namespaces, and PVCs from the earlier Microsandbox / BoxLite labs first (defaults: `microsandbox-data` / `boxlite-data`). The new Deployment is named `fault-runtime`, uses a separate home, and leaves the original workbench unchanged. BoxLite retains the earlier privileged lab device-access configuration; Microsandbox uses an existing KVM device plugin. Do not share a runtime directory with other active sandboxes.

```bash
python3 examples/sandbox-fault-injection/render.py \
  --node kvm-worker \
  --microsandbox-image registry.example.org/lab/microsandbox:0.7.8 \
  --boxlite-image registry.example.org/lab/boxlite:0.10.7 \
  --output .local/sandbox-fault-install
kubectl create namespace sandbox-fault-lab
kubectl apply --dry-run=server -f .local/sandbox-fault-install/install.json
kubectl apply -f .local/sandbox-fault-install/install.json
```

Prepare `/data/guest.tar` as described in the earlier article, then import it into the new Microsandbox fault Pod's own `MSB_HOME`:

```bash
kubectl -n microsandbox-lab exec deploy/fault-runtime -- msb load --input /data/guest.tar --tag python-lab:local
```

Keep both forwards running in separate terminals:

```bash
kubectl -n sandbox-fault-lab port-forward svc/fault-allow 18960:8080
kubectl -n sandbox-fault-lab port-forward svc/fault-deny 18961:8080
```

First use `control` to establish reachability to both targets, then run `sdk`, `vmm`, and `pod`. Run cases sequentially for each runtime and choose a fresh attempt each time; do not operate on the same fault Pod concurrently. The script kills only identity-checked PIDs inside the dedicated container, retains approximately 12 seconds of complete post-action observation, and cleans up its guest.

```bash
python3 examples/sandbox-fault-injection/run_case.py microsandbox control --context lab-cluster --attempt a01 --evidence-dir .local/sandbox-fault-evidence
python3 examples/sandbox-fault-injection/run_case.py microsandbox sdk --context lab-cluster --attempt a01 --evidence-dir .local/sandbox-fault-evidence
```

Replace the engine with `boxlite` as appropriate. Neither tested local version exposed an independent network-proxy process, so no command pretends that proxy termination is an additional measured case. Probes run for at most 240 seconds; workers for at most 290 seconds. Controller kubectl calls have deadlines and cleanup runs in `finally`. If interruption leaves incomplete state, inspect and reclaim that case before starting another.

`opensandbox_fault.py` is an additional ordinary-container control-plane check. It requires an idle OpenSandbox test installation, the Python SDK, and `KUBE_CONTEXT`, `EVIDENCE_DIR`, `OPENSANDBOX_API_KEY_FILE`, `GUEST_IMAGE`, `ALLOW_URL`, and `DENY_URL`. `ATTEMPT` is optional. It waits for all API / Controller Pods to disappear, observes for 15 seconds, and restores original replica counts and removes the task in `finally`. No egress restriction is configured for this group; it establishes no network-policy security result.

`monitoring.yaml` adds a VMServiceScrape; `dashboard.py --output FILE` renders a Grafana ConfigMap, defaulting to namespace `victoriametrics` and datasource UID `VictoriaMetrics`. Dashboard selectors are pinned to this experiment's formal cases; update them for your own attempts. Only add lab resources, rather than replacing existing Helm values.

Remove the fault runtime Deployments afterward:

```bash
kubectl -n microsandbox-lab delete deploy fault-runtime
kubectl -n boxlite-lab delete deploy fault-runtime
```

The receiver UI is at <http://127.0.0.1:18960/>, with `?group=sdk` and `?group=platform` views and a language switch. It is an article-specific evidence viewer, not an official Console. It shows uploaded measurements. Upload results through `/record`; this unauthenticated lab endpoint belongs only on a controlled network with localhost forwarding. Do not commit private inventories, keys, or raw internal addresses.

`receiver-events.csv` contains deduplicated receiver timestamps, destination roles, and case identifiers. Every published before/after count for formal cases has been cross-checked against the CSV.
