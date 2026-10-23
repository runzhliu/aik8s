[简体中文](README.md) | [English](README.en.md)

# CubeSandbox multi-replica failover experiment

Companion article: [component failure and recovery](../../translations/en/ai-k8s/rag-agent/cubesandbox-failure-recovery-practice.md). These scripts scale components and delete selected control-component Pods. Use only an idle, recoverable test installation whose experiment scope you exclusively control. This is neither a production inspection tool nor a complete high-availability deployment template.

Measured configuration: CubeSandbox / SDK 0.7.3; temporarily two API, Master and Proxy replicas, deleting one Pod at a time while keeping the other, **on the same physical node**. Both Master Pods mount the original RWO (ReadWriteOnce, single-node read/write) volume on that node; this does not establish cross-node shared storage. No host, compute Pod, CNI, database or existing virtual machine was stopped, and no Helm release was changed. See [results.json](results.json) and the 691 read probes in [probes.csv](probes.csv).

| File | Purpose |
| --- | --- |
| `run.py` | Save replica counts, validate two replicas, create independent Nginx listeners, inject serial faults and restore |
| `guest.py` | Random guest identity and in-memory counter; port 18080 is read through guest loopback only |
| `watchdog.py` | Independently restore original replica counts when the controller expires |
| `dashboard.py` | Generate separate Grafana dashboard ConfigMaps |
| `export.py` | Whitelist measurement fields, excluding internal addresses, Pod names and raw responses |

## Preconditions and request paths

The installation must use Helm release name `cube`, with `cube-api`, `cube-master`, `cube-proxy` and their Services. Only disposable sandboxes created by this experiment may run. The template must bind a verified v0.7.3 Rust Shim and expose envd command port 49983. An image tag does not establish the actual runtime version. Export full workloads, original VMI UIDs / Ready state and volume information before running; compare them afterward.

The independent front end uses OpenResty from the existing CubeProxy image, without the product Proxy's Lua routing configuration. Actual L4 listeners use Nginx `stream`; actual L7 listeners use Nginx `http`. API backends use round robin. Proxy backends use primary/backup so both pre-fault streams traverse the selected victim. Static backends are the Pod IPs observed during preparation; they are refreshed and reloaded before each case but do not track replacement Pod IPs within a case. Passive removal uses `max_fails=1`, `fail_timeout=60s` and a 1-second connect timeout. Request replay is disabled in the front LB.

API list probes open new HTTP connections and require the known sandbox ID in the JSON response. Command probes use the SDK's connection pool to read guest loopback state and verify identity. A serial create→command→delete workflow also runs during the fault; mutations are not retried. The two long streams are envd `application/connect+json` command-output streams, not WebSocket or native gRPC. A separate successful command validates L4 TLS passthrough. Certificate verification is disabled for that request because the lab uses a self-signed certificate; this is not a production TLS recommendation.

## Configure and run

Raw settings, manifests, logs and output must stay in a Git-ignored directory. Replace these example values with your dedicated test installation. `observer` is an existing stable lab bridge, which can be prepared using the previous directory's `observer.py`; that buffering bridge is not used to measure long streams.

```json
{
  "context": "lab-cluster",
  "namespace": "cube-system",
  "lab_namespace": "cube-fault-lab",
  "node": "REPLACE_TEST_NODE",
  "lb_image": "REPLACE_APPROVED_CUBE_PROXY_IMAGE:v0.7.3",
  "template": "REPLACE_VERIFIED_TEMPLATE",
  "observer": "http://127.0.0.1:18971",
  "observer_port": 18971,
  "required_shim_sha256": "REPLACE_ACTUAL_RUNTIME_SHA256",
  "vm_url": "http://127.0.0.1:18928"
}
```

`vm_url` is optional. When set, the controller imports **actual timestamped observations** into VictoriaMetrics; these are not native CubeSandbox metrics. Never publish unsanitized run output, template materials or environment settings.

```bash
python3 -m venv .local/cube-ha/venv
.local/cube-ha/venv/bin/pip install cubesandbox==0.7.3 requests websocket-client

# Start the independent watchdog first; run the controller in another terminal.
.local/cube-ha/venv/bin/python examples/cubesandbox-ha-drill/watchdog.py \
  --config .local/cube-ha/private/settings.json
.local/cube-ha/venv/bin/python examples/cubesandbox-ha-drill/run.py \
  --config .local/cube-ha/private/settings.json
```

The controller refuses to overwrite `run.json`. The watchdog checks its lease every 2 seconds; the controller renews every 5 seconds. It restores original replica counts after 70 seconds without renewal or a 20-minute total deadline. It does not migrate VMs, repair networks or terminate unknown processes. Pod deletion uses a 1-second grace period: this is not host power loss or direct process SIGKILL. Failed baselines prevent injection. `MEASURED` means the measurements completed, not zero errors or a complete HA qualification.

## View, export and restore

```bash
python3 examples/cubesandbox-ha-drill/dashboard.py --view control \
  --output .local/cube-ha/private/dashboard-control.json
python3 examples/cubesandbox-ha-drill/dashboard.py --view proxy \
  --output .local/cube-ha/private/dashboard-proxy.json
python3 examples/cubesandbox-ha-drill/export.py \
  --private-dir .local/cube-ha/private --output-dir .local/cube-ha/public
```

Use your own datasource UID and existing dashboard-sidecar labels. The generator does not alter shared monitoring authentication or scrape configuration. The lab front LB has one replica; LB-tier failover itself was not tested. WebSocket, native gRPC, HTTP/2 stream balancing, node power loss, cross-node Master storage, Redis / database elections and snapshot migration were not tested.

The original one-replica API / Master / Proxy configuration has been restored. The temporary LB was deleted, no experiment sandboxes remain, fresh create/command/delete validation passed, and all five original VMIs retained their UIDs and Ready state. The previous compute-Pod experiment's retained snapshot was untouched. An early port-18080 preflight returned 404 and a separate template-preparation attempt failed its health probe; neither reached fault injection or enters the formal result denominator.
