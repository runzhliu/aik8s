# Microsandbox Kubernetes lab

[简体中文](README.md) · [Chinese article](../../docs/ai-k8s/rag-agent/microsandbox-kubernetes-practice.md) · [English article](../../translations/en/ai-k8s/rag-agent/microsandbox-kubernetes-practice.md)

A real Microsandbox 0.7.8 experiment covering execution, separation, four concurrent guests, Live Fork, and full/disk snapshots across hosting-Pod recreation. `results.json` retains the initial two managed-job rejections and the corrected, separate attempt. Not every attempt succeeded.

Requires Linux x86_64, working KVM, an existing device plugin exposing `devices.kubevirt.io/kvm`, and a usable storage class. This example does not install a device plugin, change host networking, or deploy the official cloud service. The page is an article-specific SDK workbench.

```bash
docker build --platform linux/amd64 -t registry.example.org/lab/microsandbox:0.7.8 examples/microsandbox-kubernetes
docker push registry.example.org/lab/microsandbox:0.7.8
python3 examples/microsandbox-kubernetes/render.py \
  --test-node kvm-worker --storage-class local-test \
  --image registry.example.org/lab/microsandbox:0.7.8 \
  --output .local/microsandbox-install
kubectl apply --dry-run=server -f .local/microsandbox-install/install.json
kubectl apply -f .local/microsandbox-install/install.json
```

The image pins the SDK and runtime and verifies the official `msb-metrics` artifact. Guests use only Microsandbox's local image cache by default, with no automatic registry pull. Prepare and import an image first:

```bash
docker pull --platform linux/amd64 python:3.12-slim
docker save -o /tmp/microsandbox-guest.tar python:3.12-slim
kubectl -n microsandbox-lab get pods
# Replace POD with the actual Pod name; kubectl cp does not accept deployment/name.
kubectl -n microsandbox-lab cp /tmp/microsandbox-guest.tar POD:/data/guest.tar
kubectl -n microsandbox-lab exec deploy/microsandbox-lab -- msb load --input /data/guest.tar --tag python-lab:local
kubectl -n microsandbox-lab exec deploy/microsandbox-lab -- msb doctor
kubectl -n microsandbox-lab port-forward svc/microsandbox-lab 18950:9118
```

Open <http://127.0.0.1:18950/> or request `POST /api/suite`. Acceptance is not completion: poll `GET /api/state` and verify each assertion result. Once full and disk snapshot preparation has passed:

```bash
kubectl -n microsandbox-lab rollout restart deploy/microsandbox-lab
kubectl -n microsandbox-lab rollout status deploy/microsandbox-lab
# Reestablish port-forward in another terminal after the old Pod exits.
curl -X POST http://127.0.0.1:18950/api/restore
```

`POST /api/capture` runs only Fork and snapshot preparation, allowing a separate attempt after correcting invocation behavior. `POST /api/resource-run` repeats the four-guest, 90-second CPU check. Before rerunning the entire suite, choose a new `--attempt`, render, and update the deployment, retaining old records and archives rather than overwriting results under the same identifier. The default data directory is `/data`; `MSB_HOME=/data/runtime` selects the runtime home.

For monitoring, pass `--otel-endpoint` when rendering, using the full OTLP HTTP metrics receiver URL. `monitoring.yaml` and `dashboard.py` target namespace `victoriametrics` and datasource UID `VictoriaMetrics` by default. Adapt these to your actual monitoring installation before applying. This example does not upgrade a shared Helm release or replace existing scrape settings.

```bash
python3 examples/microsandbox-kubernetes/dashboard.py --output .local/microsandbox-dashboard.json
kubectl apply --dry-run=server -f examples/microsandbox-kubernetes/monitoring.yaml
kubectl apply -f examples/microsandbox-kubernetes/monitoring.yaml
kubectl apply -f .local/microsandbox-dashboard.json
```

Official guest metrics are exported through `msb-metrics`; the outer-container sampler has only been validated against the cgroup v1 layout used here. The workbench has no authentication and is intended for a controlled lab network with localhost forwarding. Every guest has a maximum lifetime and is stopped and removed after normal completion. The PVC retains image cache, metadata, archives, and evidence. Its 8 GiB size fits this small experiment, not arbitrary production tasks.

Public data excludes internal addresses, credentials, and actual node identifiers. `monitoring-evidence.json` includes queries, two-second time series, and peaks for the four-guest compute window. CPU, guest used memory, host resident memory, configured RAM, and container working set are different accounting measures.
