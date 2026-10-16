---
title: "GPU Node Failure Atlas"
description: "Locate GPU failures using XID, ECC, NVLink, device loss, NCCL, RDMA, and kubelet evidence"
status: evolving
last_reviewed: 2026-08-08
---

# GPU Node Failure Atlas

The same "CUDA error" can originate from the application, driver, GPU, PCIe, NVLink, NIC, switching fabric, or node power. The purpose of the failure atlas is to preserve evidence and narrow down the failure domain, not to automatically restart the node upon seeing an error code.

## 1. Symptom Matrix

| Symptom | Possible Failure Domain | First Batch of Evidence |
| --- | --- | --- |
| GPU disappears from Allocatable | Device Plugin, driver, PCIe | kubelet, plugin logs, `nvidia-smi` |
| XID/ECC growth | GPU/GPU memory/driver | DCGM, kernel logs, XID timestamps |
| NCCL Timeout | Slow rank, GPU, NIC, Fabric | Per-rank logs, NCCL, RDMA metrics |
| NVLink degradation | Link, topology, hardware | NVLink counters, topology graph |
| Container cannot see CUDA | Runtime/CDI/mounts | CDI Spec, Runtime, device nodes |
| Sudden performance drop | Clock, temperature, power, links | DCGM, power consumption, PCIe/NIC rates |
| Node repeatedly NotReady | OS, kubelet, disk, network | Node Condition, system logs |

## 2. Evidence Order

```text
保存 Pod/Job/Node UID 和时间
  → 采集 Kubernetes Event 与调度状态
  → 采集 kubelet、Runtime、Device Plugin
  → 采集 DCGM/nvidia-smi/内核日志
  → 采集 NIC/RDMA/NCCL 与交换网络
  → 再决定隔离、复位、重启或维修
```

## 3. Automatic Isolation Principles

Transient errors can block new workloads and be observed; repeated XID, uncorrectable ECC, GPU loss, or hard link failures should trigger Taint/node isolation. Whether an in-flight training job is terminated must be decided in conjunction with Checkpoint and distributed framework semantics, and must not be blindly deleted by the node health controller.

## 4. Runbook Fields

Failure signature, first occurrence time, affected GPUs/nodes/jobs, firmware/driver versions, reproduction conditions, diagnostic commands, temporary mitigation, recovery verification, repair conclusion, and threshold for recurrence.

Further reading: [Troubleshooting Host Memory OOM Behind NCCL Errors](nccl-unhandled-cuda-error-host-memory-oom.md), [GPU Node Software Stack](../cluster/gpu-node-stack.md), [Observability](../observability.md), [Reliability](../reliability.md)

## 5. Real-World Case: GPU Metrics Exporter Repeatedly Segfaults on Nodes with New Drivers

### 5.1 Symptoms

A node-level metrics Exporter in a production GPU cluster runs as a DaemonSet. The cluster has 207 instances in total, of which 106 have experienced restarts, 26 instances have restarted more than 100 times, and a single instance has exceeded 1,200 restarts; one instance remains persistently in `CrashLoopBackOff`. The container exit code is uniformly `139`, and the application log, after discovering 8 GPUs and starting the HTTP metrics endpoint, shows:

```text
free(): invalid next size (normal)
double free or corruption (!prev)
```

This signature indicates heap memory corruption in native code followed by receipt of `SIGSEGV`. It is not a Kubernetes probe failure, nor a container OOM. This DaemonSet has no health probes configured, so being in `Running/Ready` only proves the process was alive at that moment, not that the metrics endpoint remained continuously available.

### 5.2 Cross-Comparison

After aggregating the same image by node model, the failure shows a clear boundary:

| Node Group | GPU/Driver Characteristics | Pods | Pods with Restarts | Cumulative Restarts |
| --- | --- | ---: | ---: | ---: |
| General-purpose compute GPU nodes | RTX Ada, 570 driver branch | 99 | 0 | 0 |
| High-performance GPU nodes | H20/H20-3e, 580 driver branch | 108 | 106 | 11,648 |

The in-container versions are `nvitop 1.5.0`, `nvitop-exporter 1.5.0`, and `nvidia-ml-py 12.575.51`, while the H20 sample nodes use the 580.126 driver. `nvitop` upstream only added CUDA 13/NVML 580 support in 1.5.3, and only added `nvidia-ml-py 13.580.126` to the supported list in 1.6.2; 1.7.1 further fixed a race between NVML queries in a background thread and `nvmlShutdown()` that caused intermittent `SIGSEGV`. This set of evidence formed the primary hypothesis of "old collection stack incompatibility"; subsequent core dumps and corrected upgrade verification further narrowed the failure scope.

### 5.3 Inaccessible Endpoint Is a Separate Problem

An "inaccessible domain" also existed on site, but it must not be conflated with the process crash:

- The DaemonSet only uses `hostNetwork` to expose node port `5050`, with no Service or Ingress.
- The business domain in the configuration is only a Pod annotation and environment variable; on-site DNS queries return `NXDOMAIN`.
- Direct connections from the operations terminal to the node port also time out, indicating that network ACL/routing does not provide a path to the node port.

Even after fixing the process crash, a clear access path must still be established via a ClusterIP Service, Prometheus service discovery, or a controlled Ingress; do not rely on annotations to automatically generate an accessible domain.

### 5.4 Recommended Mitigation and Verification

1. First build a canary image, upgrading `nvitop` and `nvitop-exporter` to at least 1.7.1, and use the `nvidia-ml-py 13.580.126` corresponding to the 580.126 driver or the current upstream-compatible version.
2. Canary on only 1–2 H20 nodes, continuously collect for 24 hours, and observe exit codes, restart counts, metrics scrape success rate, and scrape latency; do not roll out the full DaemonSet first.
3. Add `startupProbe`, `readinessProbe`, and `livenessProbe` to probe the local `/metrics`, so that Ready state reflects actual service capability.
4. Use an explicit Service/service discovery configuration for Prometheus; page-access needs should be served by a separately deployed Grafana or controlled dashboard, rather than exposing the node Exporter directly to a browser.
5. If the new version still exhibits heap corruption, keep the failed node and collect core dumps, driver logs, and a minimal NVML reproduction, then submit a defect report upstream that includes GPU model, driver, Python binding version, and stack trace.

Upstream references: [nvitop v1.5.3](https://github.com/XuehaiPan/nvitop/releases/tag/v1.5.3), [nvitop v1.6.2](https://github.com/XuehaiPan/nvitop/releases/tag/v1.6.2), [nvitop v1.7.1](https://github.com/XuehaiPan/nvitop/releases/tag/v1.7.1), [SIGSEGV fix notes](https://github.com/XuehaiPan/nvitop/issues/222)

### 5.5 Candidate Image Build and Counter-Evidence Record

On site, a Python dependency upgrade layer was added on top of the original `linux/amd64` image, preserving the CUDA, system, and Python runtime environments, and the default entrypoint was corrected to `python -m nvitop_exporter`. Local verification results: target platform is correct, `pip check` has no dependency conflicts, and the exporter CLI can start.

The first push used the builder's default OCI image index with provenance attestation attached. The legacy sync Jobservice misreported it as "source repository does not exist." After using `--provenance=false` to re-emit a single Docker schema v2 manifest, the same tag completed production image sync successfully. This issue is unrelated to the application-layer NVML crash, but it blocked delivery of the fix image.

The reusable build files are located in the `examples/nvitop-exporter-fix/` directory of the repository.

The first candidate image installed `nvitop 1.7.1`, `nvitop-exporter 1.7.1`, and `nvidia-ml-py 13.580.126` and completed a full rollout. After all 207 Pods were updated, at least 24 H20/HCC nodes again exited with 139 within minutes; RTX Ada nodes still had zero restarts. The `/proc/1/maps` of the failed Pods proved that the process loaded the host's 580.126 `libnvidia-ml.so`, not a stale library left inside the container.

However, further verification revealed that this rollout did not actually run nvitop 1.7.1. The original base image's working directory was `/nvitop` and retained the 1.5.0 source code; Python's module search order caused it to import from the current directory first, rather than the new package in site-packages. Checking only `pip show` therefore produced a false conclusion; the actual process was a mixed stack of "nvitop API 1.5.0 + exporter 1.7.1 + nvidia-ml-py 13.580.126".

After mounting `/apps/logs` on a single H20 node and enabling unlimited core dumps, the old candidate image reproduced the crash in about 33 seconds and left an approximately 50 MiB core. GDB analysis with CPython symbols traced the Python call stack to 1.5.0's `nvitop.api.device.query_nvlink_throughput_counters()`, with the upper frames being the NVLink aggregate throughput property and the exporter's device metrics collection. The main thread ultimately triggered `double free or corruption (!prev)` on the free path after a ctypes/NVML call. This conclusion indicates the trigger is in the old NVLink query path, but it does not by itself prove whether the memory corruption occurred in the Python binding or the driver implementation.

The second image explicitly set `WORKDIR /` to ensure nvitop 1.7.1 is loaded from site-packages at runtime. Locally, the current directory, `nvitop.__version__`, and `nvitop.__file__` were all verified to avoid being fooled again by `pip show`. A single-H20 canary identified 8 GPUs, all 60 consecutive `/metrics` calls succeeded, and it ran for more than 5 minutes without restarts; however, after all 207 instances were updated, H20-3e nodes still reproduced `double free or corruption (!prev)`. The runtime module path of the failed Pods confirmed the real 1.7.1. Within a short period, production instances accumulated 111 restarts, and 35 Pods had a final exit code of 139, indicating that the old source shadowing was not the only cause, and a short single-node canary was insufficient to cover this failure.

The third image kept the real 1.7.1 and only used a Python `.pth` startup hook to make `Device.nvlink_throughput()` return an empty list, thereby bypassing the NVML NVLink field-value query that the core dump had already pointed to. This change causes NVLink total, average, and per-link throughput metrics to be missing or NaN, but does not change GPU, GPU memory, power, temperature, PCIe, or process metrics. The switch is enabled by default and can be explicitly restored via an environment variable, making it easy to re-verify after upstream or driver fixes.

The H20-3e canary completed 1,180 active `/metrics` requests within 5 minutes, including 1,000 concurrent requests, with 0 restarts and no core dumps. The production DaemonSet was then updated: 207/207 instances all Ready; continuous observation for 5 minutes from the zero baseline after rollout completion showed total restarts still at 0, with no exit 139 or `CrashLoopBackOff`. Spot-checking a H20-3e node that had previously actually exited with 139 confirmed the guard was active and the production metrics endpoint returned normally.

This is a stability workaround with a clear metrics loss and should not be written up as an NVML root cause fix. Production should still be continuously observed for at least 24 hours, and dashboards and alerts that depend on NVLink throughput should be adjusted. If this metric must be restored, the new driver, NVML Python binding, or upstream implementation should be verified on an isolated node; if the business prioritizes complete hardware telemetry, the already-verified stable DCGM Exporter can continue to be used.
