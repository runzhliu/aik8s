# Observability and resource accounting

Kubernetes container metrics do not include the complete cost of a
Kata/Firecracker sandbox. Capacity decisions must reconcile at least three
layers:

```text
payload metrics (kubectl/cAdvisor)
        + Kata shim and Firecracker VMM host processes
        + devmapper, network, and sandbox-control-plane state
```

## Point-in-time result

Four agent Pods and one retained workbench were running when the sample was
taken.

| Signal | Observation |
| --- | --- |
| Payload memory from `kubectl top` | OpenClaw 193 MiB, DSH 419 MiB, Hermes 131 MiB, Codex 351 MiB |
| Payload subtotal | 1,094 MiB, about 1.07 GiB |
| Host VMM count | Five Firecracker processes |
| Aggregate VMM RSS | 2,812,964 KiB, about 2.68 GiB |
| Host memory at sample | 12,128 MiB used, 227,135 MiB available |
| Host load average | 1.75 / 1.07 / 1.05 |
| Devmapper | Pool writable with low utilization |
| Adapter lifecycle | `cube_adapter_active_leases` was zero after the tasks |

These are point-in-time smoke observations, not capacity benchmarks. The key
finding is the accounting gap: adding the four payload readings would omit the
Firecracker VMM working sets and other host-side runtime costs.

![Sanitized resource evidence](assets/evidence/observability-light.jpg)

## Collection checklist

Use timestamps or a run identifier to correlate these sources:

```bash
kubectl top pod -n agent-runtime
kubectl get pod -n agent-runtime -o wide

# On the dedicated worker:
ps -eo pid,ppid,rss,etimes,args | grep '[f]irecracker'
dmsetup status fc-devpool
ctr -n k8s.io snapshots --snapshotter devmapper ls
```

Also retain:

- Kata shim CPU/RSS and its cgroup path;
- VMM CPU/RSS and thread count;
- CNI/TAP counters and packet drops;
- devmapper data and metadata utilization;
- Firecracker API, block, network, latency, and seccomp metrics;
- Adapter request latency, error count, active leases, and release outcomes.

Firecracker metrics are configured before boot and are not automatically
restored with snapshot state. A restore launcher must recreate its metrics and
logger endpoints before loading the snapshot.
