---
title: "Kubernetes v1.37 DRA Advanced Trio in Practice: Cross-Driver PCIe Alignment, Consumable Capacity, and Single-GPU Fault Quarantine"
description: "Hands-on tests on Kubernetes v1.37.2 and Volcano v1.16.0 covering cross-driver PCIe root alignment, AllowMultipleAllocations fractional GPU sharing with Volcano queue quotas, and KEP-4680 device health reporting paired with single-GPU DeviceTaintRule self-healing."
date: 2026-11-24
last_reviewed: 2026-11-24
status: tested
applicable_versions: "Kubernetes v1.37.2, Volcano v1.16.0, dra-example-driver v0.5.0"
---

# Kubernetes v1.37 DRA Advanced Trio in Practice: Cross-Driver PCIe Alignment, Consumable Capacity, and Single-GPU Fault Quarantine

In our previous lab [Lending an inference GPU overnight with KEDA, Volcano and DRA](keda-volcano-tidal-gpu.md), we compared exclusive whole-GPU DRA claims against `nvidia.com/gpu` for tidal borrowing. What actually makes DRA (Dynamic Resource Allocation) transformative for production AI infrastructure, however, is not a new syntax for requesting whole GPUs, but three capabilities matured across Kubernetes 1.35–1.37 that **legacy Device Plugins fundamentally cannot express**:

1. **Cross-driver PCIe topology co-scheduling**: Binding a GPU from `gpu.example.com` and an RDMA NIC from `net.example.com` onto the same `resource.kubernetes.io/pcieRoot`, eliminating cross-socket UPI/xGMI detours.
2. **Native Consumable Capacity sharing + queue quotas**: Using `allowMultipleAllocations: true` so multiple Pods share one physical GPU by memory and compute slices (each with a distinct `ShareID`), while enforcing queue-level VRAM/compute caps directly in Volcano `v1.16.0`.
3. **KEP-4680 device health reporting + single-GPU `DeviceTaintRule` quarantine**: Surfacing GPU overheating or lost-contact faults directly into Pod `allocatedResourcesStatus`, then shrinking the fault blast radius from draining an entire 8-GPU node with `kubectl drain` down to evicting only the single faulty GPU.

We executed three suites (8 controlled experiments in total) on a local 3-node Kubernetes `v1.37.2` cluster (`Volcano v1.16.0` + `dra-example-driver v0.5.0`). Here are the measured results:

- **Cross-driver PCIe root alignment (`matchAttribute`)**: Without a constraint, the control Pod `s1a-unaligned` silently reached `Running` in **1.43 s** while mismatched across sockets onto `gpu-1` (`pci0000:80`) + `nic-0` (`pci0000:00`). Adding `matchAttribute: resource.kubernetes.io/pcieRoot` yielded **100% same-root pairings across 4/4 Pods**. Tainting `nic-1` held a pinned Pod `Pending` rather than silently mis-pairing across sockets, and removing the taint healed it in **1.48 s**. Switching to **Volcano `v1.16.0`** also delivered aligned cross-driver pairing in **2.06 s**.
- **Consumable Capacity slicing and Volcano queue VRAM quota**: On single GPU `gpu-0` (80 GiB memory / 100 compute), three Pods requesting `24Gi` + `30` packed cleanly onto the card with **3 distinct `ShareID`s** (`72Gi / 80Gi`, `90 / 100`). A 4th Pod (`96Gi > 80Gi`) and an over-range claim (`90Gi > 80Gi`) were both blocked `Pending`; deleting Pod 0 let Pod 3 acquire the freed slice in **3.81 s**. On Volcano `v1.16.0`, capping queue `dra-vgpu-q` at `memory.deviceclass/gpu.example.com: 48Gi` blocked a 3rd Pod (`Queue <dra-vgpu-q> DRA resource insufficient`) even with **272 GiB** still free on the node; deleting one Pod let it run in **1.91 s**.
- **KEP-4680 reporting boundary and single-GPU self-healing**: Injecting an overheat fault on `gpu-1` propagated to Pod `allocatedResourcesStatus` as `Unhealthy` in **1.62 s** (`Unknown` lost-contact propagated in **0.52 s**), yet observing for **10 s** confirmed `kubelet` does not auto-evict the Pod—**KEP-4680 is reporting-only**. Applying a single-GPU `DeviceTaintRule` (`NoExecute`) targeting `gpu-1` triggered eviction in **0.86 s**; the Deployment's replacement Pod avoided the faulty card, landed on healthy spare `gpu-2`, and reached `Running` + `Healthy` in **1.85 s**, while the healthy sibling Pod on `gpu-0` on the same node suffered **0 restarts and kept its original UID**.

> All workloads in this lab run on simulated DRA GPU/NIC devices provided by `dra-example-driver v0.5.0`. The timings measure real Kubernetes `v1.37.2` and Volcano `v1.16.0` **control-plane topology matching, capacity accounting, CDI injection, health propagation, and eviction self-healing**; physical PCIe throughput gains and runtime VRAM hard isolation still depend on vendor DRA drivers and hardware runtimes (MIG, MPS, or RDMA SR-IOV).

---

## Lab Environment and DRA Resource Topology

The testbed is a 3-node Kubernetes `v1.37.2` cluster (1 control-plane node + 2 workers). Both DRA drivers were pinned to `Worker A` so topology and single-GPU packing tests stayed deterministic without multi-node spread noise. Alongside the default scheduler, we ran an isolated Volcano `v1.16.0` scheduler pair (`dra-volcano` + `dra-pg-controller`):

| Component / Driver | Version / Role | Devices and Topology Published on `Worker A` |
| --- | --- | --- |
| `gpu.example.com` | `dra-example-driver v0.5.0` (GPU instance) | `4` GPUs (`allowMultipleAllocations: true`, each `memory: 80Gi`, `compute: 100`): `gpu-0` / `gpu-2` on `pci0000:00`, `gpu-1` / `gpu-3` on `pci0000:80` |
| `net.example.com` | `dra-example-driver v0.5.0` (NIC instance) | `2` NICs (`allowMultipleAllocations: true`, each `ingressBandwidth: 100G`, `egressBandwidth: 100G`, `vfs: 100`): `nic-0` on `pci0000:00`, `nic-1` on `pci0000:80` |
| `dra-volcano` | Isolated Volcano `v1.16.0` scheduler | Enabled `predicate.DynamicResourceAllocationEnable: true`, `capacity.DynamicResourceAllocationEnable: true`, `capacity.DRAConsumableCapacityEnable: true` |

One practical deployment detail when installing `dra-example-driver`: if your cluster uses a non-default `kubelet` root directory instead of `/var/lib/kubelet`, you must explicitly set `kubeletRegistrarDirectoryPath` and `kubeletPluginsDirectoryPath` in Helm values; otherwise the plugin never registers with `kubelet` and zero `ResourceSlice` objects appear.

---

## Practice 1: Cross-Driver PCIe Root Topology Alignment (GPU + RDMA NIC)

With traditional Device Plugins, `nvidia.com/gpu` and `rdma/roce_gdr` are independent integer counters. The scheduler only knows a node has a free GPU and a free NIC, with no guarantee they sit behind the same CPU PCIe Root Complex. When mismatched, GPUDirect RDMA traffic detours over cross-socket interconnects (UPI/xGMI), introducing subtle tail-latency regressions in multi-node training or disaggregated P/D KV-cache transfers (for whole-GPU NUMA alignment, see [For a 4-GPU Task on an 8-GPU Node, How to Avoid Getting Fragmented GPUs Across NUMA](gpu-topology-fragmentation-scheduling.md)).

A DRA `ResourceClaimTemplate` can request devices from two separate `DeviceClass` drivers in a **single claim** and bind them to the same `resource.kubernetes.io/pcieRoot` via `constraints[].matchAttribute`:

```yaml
apiVersion: resource.k8s.io/v1
kind: ResourceClaimTemplate
metadata:
  name: gpu-nic-pcie-aligned
spec:
  spec:
    devices:
      requests:
      - name: gpu
        exactly:
          deviceClassName: gpu.example.com
          capacity:
            requests:
              memory: 80Gi
              compute: "100"
      - name: nic
        exactly:
          deviceClassName: net.example.com
          capacity:
            requests:
              ingressBandwidth: 25G
              egressBandwidth: 25G
              vfs: "1"
      constraints:
      - requests: ["gpu", "nic"]
        matchAttribute: resource.kubernetes.io/pcieRoot
```

We ran four progressive tests (1A–1D), double-checking both `ResourceClaim.status.allocation` and the CDI environment variables (`GPU_DEVICE_*` / `NET_DEVICE_*`) injected inside each running container:

![Cross-driver PCIe root alignment comparison: without matchAttribute the control Pod runs silently in 1.43 s with mismatched gpu-1 (pci0000:80) and nic-0 (pci0000:00); with matchAttribute 4/4 Pods pair 100% on the same root, and Volcano v1.16.0 honors the same constraint.](../../assets/practices/kubernetes-137-dra-topology-sharing-health/pcie-root-alignment.png)

| Experiment | Scheduler & Constraint | Allocated Devices & PCIe Roots | Outcome & Latency | Operational Meaning |
| --- | --- | --- | --- | --- |
| 1A Control | `default-scheduler`, no `matchAttribute`, pinned `gpu` to `gpu-1` and `nic` to `nic-0` | `gpu-1` (`pci0000:80`) + `nic-0` (`pci0000:00`) | `Running` (**1.43 s**), `pcie_matched: false` | Without a constraint, cross-PCIe-root mismatches succeed silently with degraded dataplane performance |
| 1B Full Alignment | `default-scheduler` + `matchAttribute: resource.kubernetes.io/pcieRoot`, 4 concurrent Pods | `pod-0`: `gpu-0`+`nic-0` (`0000:00`); `pod-1`: `gpu-1`+`nic-1` (`0000:80`); `pod-2`: `gpu-2`+`nic-0` (`0000:00`); `pod-3`: `gpu-3`+`nic-1` (`0000:80`) | **4/4 `Running`** (`1.42 s` / `0.07 s` / `0.09 s` / `0.12 s`), **100% same-root matched** | Each 100G NIC automatically serves two `25G × 2` slices for the two GPUs on its own PCIe root |
| 1C Strict Guard | Tainted `nic-1` (`0000:80`) with `DeviceTaintRule` (`NoSchedule`), pinned Pod to `gpu-1` (`0000:80`) | Held `Pending` (`2 cannot allocate all claims`); untainting placed it on `gpu-1` + `nic-1` (`0000:80`) | Refused cross-socket fallback; healed to `Running` in **1.48 s** | `matchAttribute` is a strict hard constraint and will not silently degrade across sockets |
| 1D Volcano Check | Switched to `dra-volcano` (Volcano `v1.16.0`) with the same `matchAttribute` | `gpu-1` (`pci0000:80`) + `nic-1` (`pci0000:80`) | `Running` (**2.06 s**), `pcie_matched: true` | Volcano `v1.16.0` inherits Kubernetes DRA cross-driver topology solving cleanly |

Inspecting CDI environment variables inside `s1a-unaligned` and `s1b-aligned-0` confirmed both independent drivers injected device identity, memory, and bandwidth parameters into the same container:

```text
# s1b-aligned-0 container CDI env (gpu-0 + nic-0, both on pci0000:00)
GPU_DEVICE_0=gpu-0
GPU_DEVICE_0_COMPUTE=100
GPU_DEVICE_0_MEMORY=80Gi
GPU_DEVICE_0_SHARING_STRATEGY=TimeSlicing
NET_DEVICE_0_INGRESS_RATE=25000000000
NET_DEVICE_0_EGRESS_RATE=25000000000
```

> **Production pitfall**: `matchAttribute` performs exact string equality. If your GPU DRA driver advertises `pci0000:00` while your RDMA NIC driver advertises `0000:00` or a custom domain prefix, every Pod with `matchAttribute` stays `Pending` indefinitely. Always inspect `kubectl get resourceslices -o yaml` first to verify both drivers emit identical attribute keys and value formats.

---

## Practice 2: DRA Consumable Capacity Slicing and Volcano Queue VRAM Quotas

Because `nvidia.com/gpu` only counts whole integer `1` units, fractional GPU sharing traditionally relied on third-party webhooks (such as HAMi or custom device plugins), splitting state across scheduler extensions, node plugins, and quota admission. Kubernetes DRA **Consumable Capacity** (KEP-5075) brings fractional accounting into the core API:

- Drivers mark devices with `allowMultipleAllocations: true` in `ResourceSlice` and publish `requestPolicy.validRange` bounds and step sizes (here `gpu-0` offers `1Gi–80Gi` in `1Gi` steps and compute `1–100` in steps of `1`).
- The scheduler assigns each shared allocation a unique `shareID` (UUID) and records exact deductions in `ResourceClaim.status.allocation.devices.results[].consumedCapacity`.
- Volcano `v1.16.0`'s `capacity` plugin extends this to **queue-level quotas**, letting platform teams cap total VRAM and compute per tenant queue in `Queue.spec.capability` using `<capacityName>.deviceclass/<deviceClassName>`.

![DRA consumable capacity measurements: left panel packs three 24 GiB slices (72 GiB, distinct ShareIDs) onto single GPU gpu-0 while blocking Pod 3 (96 GiB > 80 GiB); right panel shows Volcano queue dra-vgpu-q capping usage at 48 GiB and blocking qpod-2 despite 272 GiB free on the node.](../../assets/practices/kubernetes-137-dra-topology-sharing-health/consumable-capacity-quota.png)

### 2A. Single-GPU `gpu-0` Distinct `ShareID` Slicing and Hardware Cap Enforcement

Using the CEL selector `device.attributes["gpu.example.com"].index == 0`, we pinned all test Pods onto `gpu-0` (`80Gi` memory, `100` compute), each requesting `24Gi` memory + `30` compute:

| Pod | Requested Capacity | Status & Latency | Assigned `shareID` (first 8 chars) | Container CDI Injection |
| --- | --- | --- | --- | --- |
| `s2a-slice-0` | `24Gi` + `30` | `Running` (**1.40 s**) | `1c426a4c` | `GPU_DEVICE_0_MEMORY=24Gi`, `GPU_DEVICE_0_COMPUTE=30` |
| `s2a-slice-1` | `24Gi` + `30` | `Running` (**0.07 s**) | `21a8516a` | `GPU_DEVICE_0_MEMORY=24Gi`, `GPU_DEVICE_0_COMPUTE=30` |
| `s2a-slice-2` | `24Gi` + `30` | `Running` (**0.13 s**) | `d9e11e1b` | `GPU_DEVICE_0_MEMORY=24Gi`, `GPU_DEVICE_0_COMPUTE=30` |
| `s2a-slice-3` | `24Gi` + `30` (total `96Gi > 80Gi`) | Blocked `Pending` | None (`cannot allocate all claims`) | — |
| `s2a-overmax` | `90Gi` (exceeds `validRange.max: 80Gi`) | Blocked `Pending` | None (`cannot allocate all claims`) | — |
| `s2a-slice-3` after deleting `s2a-slice-0` | Reclaims freed `24Gi` + `30` | `Running` in **3.81 s** | `054ff523` (fresh `ShareID`) | `GPU_DEVICE_0_MEMORY=24Gi`, `GPU_DEVICE_0_COMPUTE=30` |

One subtle observation from the run: at the moment each Pod transitioned to `Running`, `shareID`, `consumedCapacity` inside `ResourceClaim.status.allocation.devices.results`, and container CDI env vars were all populated immediately, whereas `dra-example-driver`'s `ResourceClaim.status.devices` array sampled as `null`. Production accounting and monitoring should therefore read `ResourceClaim.status.allocation` as the source of truth rather than relying solely on `status.devices`.

### 2B. Volcano `v1.16.0` Queue-Level VRAM and Compute Quota Enforcement

Device-level caps prevent oversubscribing a single card, but multi-tenant platforms also need to stop a tenant from consuming more than 48 GiB even when 272 GiB remain idle on the node. We created queue `dra-vgpu-q` in Volcano `v1.16.0`:

```yaml
apiVersion: scheduling.volcano.sh/v1beta1
kind: Queue
metadata:
  name: dra-vgpu-q
spec:
  weight: 1
  reclaimable: true
  deserved:
    cpu: "10"
    memory: 16Gi
    memory.deviceclass/gpu.example.com: 48Gi
    compute.deviceclass/gpu.example.com: "60"
  capability:
    cpu: "20"
    memory: 32Gi
    memory.deviceclass/gpu.example.com: 48Gi
    compute.deviceclass/gpu.example.com: "60"
```

With 4 × 80 GiB GPUs (**320 GiB** total) available on `Worker A`, we submitted three `24Gi` + `30` Pods to `dra-vgpu-q`:

- `s2b-qpod-0` (**1.83 s**) and `s2b-qpod-1` (**0.85 s**) reached `Running`, consuming `48Gi` memory and `60` compute in the queue;
- `s2b-qpod-2` (which would push the queue to `72Gi > 48Gi`) was held `Pending` by Volcano's `capacity` plugin despite **272 GiB** remaining free on the node;
- Deleting `s2b-qpod-0` allowed `s2b-qpod-2` to acquire the freed queue quota and reach `Running` in **1.91 s**.

The Volcano scheduler logs confirm the rejection came directly from the DRA consumable-capacity ledger rather than node exhaustion:

```text
I1124 11:16:28.049636 1 capacity.go:1709] Queue <dra-vgpu-q> DRA resource insufficient for candidate <s2b-qpod-2>
I1124 11:16:28.049654 1 allocate.go:952] Queue <dra-vgpu-q> is overused when considering task <s2b-qpod-2>, ignore it.
```

> **Enforcement boundary**: DRA Consumable Capacity governs **control-plane scheduling accounting, queue quotas, and CDI parameter delivery**. Turning `GPU_DEVICE_0_MEMORY=24Gi` into an unbreakable runtime VRAM wall still requires hardware/driver enforcement underneath (such as NVIDIA MIG, MPS memory limits, or vendor vGPU CUDA interceptors).

---

## Practice 3: KEP-4680 Device Health Reporting and Single-GPU `DeviceTaintRule` Self-Healing

On 8-GPU servers, single-card XID errors, thermal throttling, or PCIe drop-offs happen routinely. Traditional recovery relies on Node Problem Detector tainting the **entire node** with `NoExecute` or running `kubectl drain`, which evicts 7 healthy GPUs' worth of live inference or training jobs just to isolate 1 faulty card.

Kubernetes `v1.37` supplies two complementary building blocks:

- **KEP-4680 (DRA Device Health)**: A DRA driver streams per-device health (`Healthy` / `Unhealthy` / `Unknown`) to `kubelet` via gRPC `NodeWatchResources`, and `kubelet` writes it directly into `status.containerStatuses[].allocatedResourcesStatus` on the Pod using that device.
- **`DeviceTaintRule` (`resource.k8s.io/v1alpha3`)**: An operator or watchdog controller can apply a `NoSchedule` or `NoExecute` taint to one specific device (`driver` + `pool` + `device`), letting the control-plane `DeviceTaintManager` evict only the Pod bound to that faulty GPU without touching sibling Pods on the same node.

We deployed a 2-replica serving Deployment `dra-serving` onto `Worker A` (4 GPUs: `gpu-0` through `gpu-3`). At baseline, the victim replica ran on `gpu-1` (`53°C`, `Healthy`), the sibling replica ran on `gpu-0` (`53°C`, `Healthy`), and `gpu-2` / `gpu-3` stood ready as healthy spares.

![KEP-4680 health reporting and single-GPU DeviceTaintRule self-healing timings: Unknown lost-contact 0.52 s, Unhealthy overheat 1.62 s, DeviceTaintRule eviction trigger 0.86 s, replacement Pod Running and Healthy on spare gpu-2 in 1.85 s, with 0 restarts on the same-node gpu-0 sibling.](../../assets/practices/kubernetes-137-dra-topology-sharing-health/device-health-quarantine.png)

### 3A. Measuring the KEP-4680 State Machine and `kubelet` Boundary

We injected simulated overheat and lost-contact faults via annotations `health.example.com/gpu-1=unhealthy` and `unknown` on the `dra-example-driver` Pod, observing `status.containerStatuses[0].allocatedResourcesStatus` on the victim Pod:

1. **Overheat `Unhealthy` propagation took `1.62 s`**: The Pod status surfaced the exact faulty card and thermal message:

```text
name: claim:gpu
resources:
- health: Unhealthy
  message: "gpu-1 temperature: 80°C (warning threshold exceeded, safe limit is 85°C)"
  resourceID: k8s.gpu.example.com/gpu=common
```

2. **Critical boundary test (10 s observation)**: With no external watchdog active, the victim Pod remained `phase: Running` with `restarts: 0`. `kubelet` does **not** automatically restart or evict a Pod when `allocatedResourcesStatus` transitions to `Unhealthy`.
3. **Lost-contact `Unknown` propagation took `0.52 s`**: Switching the annotation to `health.example.com/gpu-1=unknown` updated the Pod status to `health: Unknown` (`Health of device gpu-1 cannot be determined (driver lost contact with the device)`) in half a second.

This separation is intentional: `kubelet` cannot know whether a serving workload wants immediate termination or graceful traffic draining first. **KEP-4680 standardizes per-device health telemetry in the Pod API, leaving remediation policy to a controller.**

### 3B. Single-GPU `DeviceTaintRule` Quarantine and 1.85 s Replacement Recovery

Next, acting as a fault watchdog reacting to `Unhealthy`, we applied a `DeviceTaintRule` scoped strictly to `gpu-1`:

```yaml
apiVersion: resource.k8s.io/v1alpha3
kind: DeviceTaintRule
metadata:
  name: quarantine-gpu-1
spec:
  deviceSelector:
    driver: gpu.example.com
    device: gpu-1
  taint:
    key: health.example.com/gpu-fault
    value: unhealthy
    effect: NoExecute
```

End-to-end measured results:

| Stage | Measured Timing / State | Verified Evidence |
| --- | --- | --- |
| `DeviceTaintRule` eviction trigger | **0.86 s** | Victim Pod (bound to `gpu-1`) entered deletion with reason `DeviceTaintManagerEviction` |
| Replacement Pod scheduled & healthy | **1.85 s** | New replica avoided tainted `gpu-1`, landed on healthy spare **`gpu-2`**, and reached `Running` + `Healthy` (`temperature: 51°C`) |
| Same-node sibling impact | **0 disruption, 0 restarts** | Sibling `dra-serving-58f799f5b4-r87vk` on **`gpu-0`** kept the exact same UID, `restarts: 0`, and `Healthy` (`53°C`) |

Compared to `kubectl drain` or node-level taints, single-GPU `DeviceTaintRule` narrows the blast radius of a single bad GPU from **an entire 8-GPU host down to 1 GPU**. In production, teams can tier remediation by fault severity:

- **Soft faults (thermal warnings, rising correctable ECC)**: Apply a `DeviceTaintRule` with `effect: NoSchedule` first to block new placements while draining live inference traffic gracefully before recreating the Pod.
- **Hard faults (uncorrectable ECC, XID 79 fallen off bus, driver `Unknown`)**: Apply `effect: NoExecute` (or short `tolerationSeconds`) for second-level failover, then delete the `DeviceTaintRule` once hardware repair and burn-in pass to return the GPU to the pool.

---

## Production Rollout Checklist and Pitfalls

| Capability | Recommended Production Setup | Key Boundaries and Pitfalls to Verify First |
| --- | --- | --- |
| Cross-driver GPU + RDMA NIC alignment | Put both device requests in one `ResourceClaimTemplate` with `matchAttribute: resource.kubernetes.io/pcieRoot` | Both DRA drivers must emit identical `pcieRoot` attribute keys and value formats; `matchAttribute` is a hard constraint and holds Pods `Pending` if same-root NICs are unavailable |
| Fractional GPU sharing & queue quota | Enable `allowMultipleAllocations: true` in driver; enable `capacity.DynamicResourceAllocationEnable` and `capacity.DRAConsumableCapacityEnable` in Volcano `v1.16.0` | Queue quota keys follow `<capacity>.deviceclass/<class>`; DRA handles scheduling ledger and CDI injection, while runtime VRAM hard isolation still needs MIG/MPS/vGPU |
| Single-GPU fault visibility & self-healing | Run KEP-4680-capable `kubelet` + DRA driver plus a lightweight watchdog watching `allocatedResourcesStatus` to reconcile `DeviceTaintRule` | KEP-4680 does not auto-evict faulty Pods; `DeviceTaintRule` currently lives in `resource.k8s.io/v1alpha3` (verify the API group is enabled in your cluster) |
| Custom `kubelet` root directory | Pass `kubeletRegistrarDirectoryPath` and `kubeletPluginsDirectoryPath` explicitly when installing DRA drivers | Mismatched paths silently prevent plugin registration and leave the cluster with zero `ResourceSlice` objects |

---

## Reproducible Lab Kit and Raw Measurements

All automation scripts, core YAML manifests, and sanitized raw JSON outputs from the three suites are packaged below and can be reproduced and auto-cleaned on any Kubernetes `v1.36+` (recommended `v1.37+`) cluster:

- **Reproducible Lab Kit**: [lab.zip](../../assets/practices/kubernetes-137-dra-topology-sharing-health/lab.zip) (includes `README.md`, `pcie-aligned-claim-template.yaml`, `volcano-dra-queue.yaml`, `quarantine-device-taint-rule.yaml`, and `run_dra_suite.py`)
- **Sanitized Raw Results JSON**: [results.json](../../assets/practices/kubernetes-137-dra-topology-sharing-health/results.json) (contains every `ShareID`, CDI env dump, Volcano scheduler log excerpt, `allocatedResourcesStatus` payload, and measured timing)

Further reading:

- [Lending an inference GPU overnight with KEDA, Volcano and DRA](keda-volcano-tidal-gpu.md)
- [For a 4-GPU Task on an 8-GPU Node, How to Avoid Getting Fragmented GPUs Across NUMA](gpu-topology-fragmentation-scheduling.md)
- [Kubernetes Documentation: Dynamic Resource Allocation (DRA)](https://kubernetes.io/docs/concepts/scheduling-eviction/dynamic-resource-allocation/)
- [Kubernetes KEP-4680: Add Resource Health Status to Pod Status](https://github.com/kubernetes/enhancements/tree/master/keps/sig-node/4680-add-resource-health-status-to-pod-status)
- [Volcano DRA Integration Guide](https://volcano.sh/en/docs/dra/)
