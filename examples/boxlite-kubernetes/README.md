# BoxLite on Kubernetes laboratory

This example accompanies the [Chinese article](../../docs/ai-k8s/rag-agent/boxlite-kubernetes-practice.md) and its [full English translation](../../translations/en/ai-k8s/rag-agent/boxlite-kubernetes-practice.md). It was exercised with BoxLite **0.10.7**, Kubernetes **1.30.4**, Linux amd64, and **cgroup v1**. It uses the published Python wheel and does not rebuild the hypervisor.

The page in `index.html` displays real SDK test records. It is an article-specific lab page, **not the upstream BoxLite Console**. Kubernetes sees one runner Pod; the SDK manages the microVMs inside it.

## Requirements and deployment

Choose one node with usable KVM, `/dev/fuse`, and `/dev/vhost-vsock`. This laboratory deliberately uses a privileged container and a 10 GiB PVC. It does not modify host networking, the container runtime, or existing virtualization workloads. The resource exporter in this version targets the tested cgroup v1 mount layout; its container metrics need adapting and validating before use on cgroup v2.

```bash
docker build --platform linux/amd64 -t registry.example.com/lab/boxlite:0.10.7 examples/boxlite-kubernetes
docker push registry.example.com/lab/boxlite:0.10.7
python3 examples/boxlite-kubernetes/render.py \
  --test-node worker-lab --storage-class local-lvm \
  --image registry.example.com/lab/boxlite:0.10.7 \
  --output .local/boxlite-lab
kubectl create namespace boxlite-lab --dry-run=client -o yaml | kubectl apply -f -
kubectl apply --dry-run=server -f .local/boxlite-lab/install.json
kubectl apply -f .local/boxlite-lab/install.json
kubectl -n boxlite-lab rollout status deployment/boxlite-lab
kubectl -n boxlite-lab port-forward service/boxlite-lab 18940:9108
```

Use `--guest-image` for an accessible guest mirror, independently of the runner image. TLS verification is enabled by default. `--registry-skip-verify` is an explicit, host-scoped laboratory exception for a known self-signed registry; prefer a trusted CA chain for a real integration. Rendered manifests contain environment-specific choices and belong in an ignored local directory.

Open <http://127.0.0.1:18940/>. In a separate terminal:

```bash
curl -X POST http://127.0.0.1:18940/api/suite
curl http://127.0.0.1:18940/api/state
```

The suite runs ten cached starts, twenty short executions, file isolation/transfer, a two-second command deadline, four 90-second CPU workloads, and persistence preparation. A `202` response is only an acknowledgement. Wait for `busy=false` and inspect every record; failure of one check does not turn later independent checks into successes or prevent them from being attempted. Records are immutable JSON files on the PVC. Use a new `--attempt` when changing comparison conditions; retain earlier evidence.

After `persistence_prepare` passes, save the Pod UID, recreate the Deployment, verify a different Pod UID, and reconnect port-forward:

```bash
kubectl -n boxlite-lab get pod -l app=boxlite-lab -o jsonpath='{.items[0].metadata.uid}'
kubectl -n boxlite-lab rollout restart deployment/boxlite-lab
kubectl -n boxlite-lab rollout status deployment/boxlite-lab
kubectl -n boxlite-lab port-forward service/boxlite-lab 18940:9108
```

Submit `POST /api/persistence-verify` in another terminal. It verifies the same Box ID and file marker but a different guest boot ID, then removes that verification Box. This is disk recovery on the same local-volume node, not a memory checkpoint or node-loss recovery test.

## Monitoring

The supplied scrape resource assumes an existing VictoriaMetrics Operator in namespace `victoriametrics` with matching service-scrape discovery. The dashboard uses datasource UID `VictoriaMetrics` and the dashboard sidecar label `victoriametrics_dashboard=1`; adapt these to the local installation.

```bash
kubectl apply -f examples/boxlite-kubernetes/monitoring.yaml
python3 examples/boxlite-kubernetes/dashboard.py --output .local/boxlite-lab/dashboard.json
kubectl apply -f .local/boxlite-lab/dashboard.json
curl -X POST http://127.0.0.1:18940/api/resource-run
```

The last request repeats the four-box CPU workload to provide a continuous resource window. The exporter bridges SDK data and the current container's cgroup accounting. It does not read host-root accounting. SDK `num_running_boxes` is counter-derived in 0.10.7 and was one short after restoring/stopping an older Box; the article preserves and explains the original curve. Do not use this count alone for inventory or billing.

These endpoints are intended for a controlled laboratory behind localhost forwarding. They are not an authenticated multitenant API. The guest CPU/memory configuration, outer container limits, and per-Box host cgroup limits are distinct; the experiment did not validate per-Box host resource enforcement on cgroup v1.

## Evidence and cleanup

`results.json` contains anonymized second-attempt measurements and a summary of earlier preparation/harness failures. Private endpoints, registry credentials, and actual deployment manifests are excluded. Screenshots in the article come from the running lab page and real Grafana data; screenshot pixels have not been translated.

The suite stops its transient Boxes, with the named persistence Box deliberately retained until verification. Confirm zero running instances and inspect failures before deleting resources. To remove the laboratory, delete only its Deployment, Service, ConfigMap, and monitoring objects. Keep the PVC while evidence or disk recovery is still needed; deleting the PVC removes the experiment's data.
