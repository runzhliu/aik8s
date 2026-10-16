---
title: "What Real Value Does Kubernetes 1.37 Deliver for AI/LLMs: An Item-by-Item Comparison with 1.35"
date: 2026-08-27
authors:
  - runzhliu
categories:
  - Kubernetes
  - AI Infrastructure
description: "From Gang Scheduling, DRA, GPU scale-to-zero, NUMA and observability, this analysis examines the real benefits and adoption boundaries of Kubernetes 1.37 versus 1.35 for training and inference platforms."
---

# What Real Value Does Kubernetes 1.37 Deliver for AI/LLMs: An Item-by-Item Comparison with 1.35

Kubernetes 1.37 (Garhwal) was released on August 26, 2026, with a total of 67 enhancements: 16 moved to Stable, 23 moved to Beta, 27 moved to Alpha, and 1 was deprecated or removed. That is a substantial number, but if the question is "will LLMs run faster right after the upgrade," the answer remains: **Kubernetes version changes alone will not automatically improve Token throughput, NCCL bandwidth, or GPU compute utilization.**

What is genuinely worth the attention of AI platform teams in 1.37 is that Kubernetes has begun to progressively consolidate capabilities previously scattered across Device Plugins, third-party Gang Schedulers, device labels, and custom controllers into native Workload and DRA semantics. Compared with 1.35, the main improvements are in "whether an entire group of GPUs can be obtained together," "whether GPUs and NICs can be matched by topology," "whether bad cards can be isolated," "whether idle inference instances can scale to zero," and "whether controllers are more reliable in large clusters."

## Conclusions First

| Capability | Kubernetes 1.35 | Kubernetes 1.37 | Real Value for AI/LLM |
| --- | --- | --- | --- |
| Native Gang Scheduling | Alpha, first version of Workload API | Beta, includes PodGroup queueing and improved livelock handling | Multi-node training no longer occupies a portion of GPUs first and then waits on each other |
| Workload-aware Preemption | Still a future goal | Beta | Preemption targets whether the entire group of tasks can make progress, reducing ineffective evictions |
| Workload-shared DRA Claims | Lacks full workload semantics | Beta | A group of Pods can share NIC or other device Claims |
| Traditional extended resources integrated with DRA | Alpha | Stable | Existing `vendor.example/gpu: N` workloads can migrate incrementally to DRA drivers |
| Device Taint/Toleration | Early stage | Stable | Bad, degraded, and reserved cards can be isolated at device granularity |
| Device status and health information | Capability still evolving | Multiple capabilities moved to Stable/Beta | Pod status can indicate which device was allocated and whether the device is abnormal |
| NUMA device attributes | Each driver expresses its own | Standard `resource.kubernetes.io/numaNode` Stable | Cross-driver devices such as GPU and NIC have a unified NUMA alignment foundation |
| HPA scale to 0 | Alpha | Beta, enabled by default | Low-frequency GPU inference or queue consumers no longer need to keep idle replicas resident |
| Memory QoS | Alpha | Beta, enabled by default | Reduces memory pressure interference on model serving under cgroup v2 |
| In-place Pod Resize | Stable | Stable, with Alpha extensions for preemption and dynamic expansion of memory-backed volumes | CPU, memory, and tmpfs adjustments rely less on Pod recreation |
| Job/JobSet/TrainJob/LWS/RayJob native WAS integration | Each controller adapts on its own | Common integration framework enters Alpha | Long term, may reduce duplicated scheduling logic implemented by each training controller |

The items most worth investing in for validation are the first three, the Stable DRA capabilities, and HPA scale-to-zero. Capabilities marked Alpha in the table are suitable for experimental environments and should not be enabled directly in production merely because "1.37 supports them."

## 1. From "Scheduling Pods One by One" to "Scheduling One Training Job"

Kubernetes 1.35 first introduced the `Workload` API and native Gang Scheduling, but both were in Alpha. The fundamental problem they solve is: if a training job requiring 16 Workers only gets 8 scheduled successfully, the 8 Pods already running will occupy GPUs without doing useful work, and may deadlock with another job that also only obtained half of its resources.

1.37 advances native Gang Scheduling to Beta. The scheduler performs all-or-nothing scheduling through Workload and PodGroup, and adds PodGroup queueing, workload-aware preemption, and livelock fixes when multiple workloads are scheduled concurrently. For synchronous data-parallel, tensor-parallel training, and MPI/HPC tasks, this is more valuable than shaving tens of milliseconds off a single Pod's scheduling latency: **either the entire group starts, or not a single card is occupied.**

Another change is that Workload-level DRA ResourceClaims enter Beta. Some devices are not "one per Pod" but rather a group of Workers sharing the same set of resource semantics; 1.37 allows a PodGroup to associate with a ResourceClaim or ResourceClaimTemplate, without requiring the training controller to manually fabricate a Claim for each Pod.

However, this does not mean Kubernetes 1.37 has already replaced Volcano or Kueue. Quota borrowing, fair sharing, queue admission, multi-cluster dispatch, and mature topology policies remain the strengths of existing batch scheduling systems. In particular, Kueue's official documentation explicitly provides capabilities such as ClusterQueue, ResourceFlavor, multi-level topology, and MultiKueue. A more realistic adoption path is:

1. New clusters first validate the native WAS Beta in an isolated environment;
2. Existing production queues continue to be managed by Kueue or Volcano;
3. Wait until the common WAS integration framework for TrainJob, JobSet, LeaderWorkerSet, and RayJob leaves Alpha before evaluating the reduction of third-party scheduling extensions, rather than rewriting the platform immediately.

## 2. DRA Goes from "New API" to an Incrementally Migratable Device Foundation

The core DRA API was already GA in Kubernetes 1.34, so it cannot simply be stated that "DRA is only supported in 1.37." What changed in 1.37 is that several peripheral capabilities that directly affect GPU platform adoption have become more mature.

### Legacy Workloads Do Not Need a One-Time Rewrite

DRA Extended Resource Support enters Stable in 1.37. Administrators can map traditional extended resource names to a DeviceClass, and existing Pods continue to request resources similar to the following:

```yaml
resources:
  limits:
    accelerator.example/gpu: 8
```

Actual device allocation can then be handled by the DRA driver, without requiring every business team to immediately learn and rewrite ResourceClaims. What this solves is not GPU compute performance but platform migration cost: the infrastructure layer can switch device management backends first, and business YAML can then progressively adopt DRA selectors, Claims, and sharing semantics.

The prerequisite is that the vendor DRA driver already supports the target hardware and the corresponding features. The Kubernetes API reaching Stable does not mean that a given GPU, NPU, or RDMA driver is automatically compatible.

### Bad Cards and Reserved Cards Can Be Isolated at Device Level Without Tainting the Entire Machine

Device-level Taint/Toleration enters Stable in 1.37. In the past, when a GPU experienced ECC, Xid, or link anomalies, the common practice was to Taint the entire Node, which also made other healthy GPUs on the same machine unschedulable. DRA Device Taint allows the driver or administrator to mark only the specific device, use `NoSchedule` to block new allocations, and if necessary use `NoExecute` to evict Pods currently using it.

This provides a better primitive for automated fault closed-loop handling, but it does not replace DCGM, driver logs, or out-of-band hardware monitoring. The correct pipeline remains: "monitoring detects anomaly → controller writes device status or Taint → scheduling and recovery systems take action."

### GPU, NIC, and NUMA Alignment Gain a Common Language

1.37 defines `resource.kubernetes.io/numaNode` as a Stable standard device attribute. Different DRA drivers can use the same attribute to describe which NUMA Node a GPU, RDMA NIC, or other device resides on, avoiding each driver inventing its own fields.

1.37 also introduces two related Alpha capabilities:

- Derived Attributes can convert fields exposed by different drivers into comparable virtual attributes, used for selecting GPUs and NICs on the same NUMA node;
- Device Compatibility Groups can express in advance device configurations such as MIG and vGPU that cannot coexist, avoiding failures at the device preparation stage after scheduling has already completed.

These two are very relevant to multi-node training and GDRDMA, but they are still Alpha. What they provide is a **mechanism for correctly selecting topology**; they do not conjure GPUDirect RDMA out of thin air. Actual benefits still depend on PCIe/NVLink/NIC topology, IOMMU, drivers, firmware, NCCL, and network configuration.

### Observability Begins to Answer "What Happened to the Device This Pod Got"

In 1.37, the `.status.devices` of ResourceClaim enters Stable, allowing drivers to report the status of allocated devices, such as the IP assigned to a network device. Device health information can also enter the container's `status.allocatedResourcesStatus`, enabling controllers and troubleshooting personnel to correlate Pod failures with specific devices.

Two boundaries need to be noted: health reporting depends on the driver implementing the corresponding interface; and after a Pod terminates, device health status is no longer updated. So it is suitable for fault correlation, not as a complete historical GPU metrics database.

## 3. Native Scale-to-Zero Finally Becomes More Practical for Low-Frequency GPU Inference

HPA Scale to Zero enters Beta and is enabled by default in 1.37. When HPA uses Object Metrics or External Metrics, `minReplicas: 0` can be set to scale expensive GPU replicas to zero when there is no work, and then recover based on queue depth or external request metrics.

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: gpu-inference
spec:
  minReplicas: 0
  maxReplicas: 4
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: gpu-inference
  metrics:
    - type: External
      external:
        metric:
          name: pending_inference_requests
        target:
          type: AverageValue
          averageValue: "1"
```

It is suitable for offline generation, low-frequency experimental models, and queueable workloads, but not for online low-latency endpoints without request buffering. Model weight pulling, GPU initialization, CUDA Graph Capture, and KV Cache warm-up can take tens of seconds or even minutes; if the gateway cannot queue, health-check, and retry on timeout, scale-to-zero will simply convert GPU cost savings into first-request failures.

Additionally, scale-to-zero cannot use CPU/Memory Resource Metrics because with zero replicas there are no Pods to sample. Production solutions still require Prometheus Adapter, external metrics systems, or event sources similar to KEDA, as well as model caching and cold-start governance.

## 4. Indirect Benefits from Memory, Monitoring, and Control-Plane Reliability

These capabilities do not directly change GPU kernels, but they do affect whether LLM serving remains stable.

### Memory QoS Enters Beta

1.37 uses `memory.min`, `memory.low`, and `memory.high` on cgroup v2 to provide memory protection and throttling, and enables the `MemoryQoS` Feature Gate by default. For inference Pods that heavily use Page Cache, Pinned Host Memory, shared memory, or CPU Offload, this has the potential to reduce memory-reclaim jitter caused by neighboring workloads.

However, overly aggressive `memory.high` configuration can also create latency spikes. After upgrading, container working set, PSI, OOM, throttling, and TTFT should be observed together, rather than assuming optimization is complete simply because the Feature Gate is enabled by default.

### metrics.k8s.io Stable and Native Histogram Beta

`metrics.k8s.io/v1` enters Stable in 1.37, and Native Histogram support enters Beta. The former stabilizes the CPU/memory interface used by HPA and `kubectl top`; the latter improves storage efficiency and quantile accuracy for Kubernetes control-plane Histograms.

Neither of these means Kubernetes natively understands GPU utilization, TTFT, TPOT, or KV Cache. Model serving metrics still need to be provided by the inference engine, DCGM Exporter, and gateway; Native Histogram also only becomes meaningful once the Prometheus 3.x scraping pipeline supports the corresponding protocol.

### Large-Cluster Controllers Are Less Likely to Overwhelm etcd

1.37 completes the stabilization of Resilient Watch Cache Initialization: during cache initialization or recovery, expensive List/Watch requests no longer hit etcd in a concentrated burst, and requests beyond the protection scope receive 429. For clusters carrying large numbers of Jobs, Pods, ResourceClaims, and custom training CRDs, this is a control-plane reliability benefit.

Correspondingly, self-developed Operators must correctly handle `Retry-After` and exponential backoff. Upgrading the control plane while retaining controllers that immediately retry on 429 can instead turn the protection mechanism into a new retry storm.

## 5. Capabilities in 1.37 with Strong Potential but Not Worth Production Bets Yet

The following Alpha features are highly relevant to AI scenarios but are better suited for PoCs:

| Alpha Capability | Possible AI Scenario | Current Limitations |
| --- | --- | --- |
| CompositePodGroup | Expressing hierarchical Gang for P/D, Controller/Worker, multi-role training | API and controller ecosystem will still change |
| WAS Controller API | Unifying JobSet, TrainJob, LWS, RayJob into scheduling semantics | Integration framework not yet mature |
| `Job.spec.scheduling` | Ordinary Jobs directly declaring Gang, topology, Disruption, and Claims | Alpha and requires the relevant Feature Gate |
| Pod Checkpoint/Restore | Spot recovery, long-task migration, inference process warm-up | Requires CRI Runtime to implement new RPCs; does not mean GPU state is migratable |
| Dynamically resizing memory-backed `emptyDir` | Expanding `/dev/shm` and tmpfs Cache without restart | Alpha, limited to explicitly resized memory volumes |
| In-place Resize Preemption | Proactively freeing node capacity for CPU/memory expansion of critical Pods | Alpha; incorrect priority may evict other important tasks |

In particular, Pod Checkpoint/Restore should not be described as "hot-migrating LLM GPU processes." Kubernetes only defines Pod-level CRI interfaces; CUDA Context, GPU memory, RDMA Queue Pairs, and distributed training consistency still require joint support from the runtime, drivers, and upper-layer frameworks.

## 6. What to Answer Before Upgrading from 1.35

### Clusters Where the Upgrade Has Clear Value

- Running large numbers of multi-node training jobs concurrently, frequently experiencing partial Worker card-occupancy waiting;
- Complex device types such as GPU, NIC, MIG/vGPU, and evaluating DRA;
- Wanting to converge fault isolation from Node granularity to Device granularity;
- Having low-frequency, queueable GPU inference services that want native HPA scale-to-zero;
- The control plane carries large numbers of Jobs, Pods, and CRDs with visible List/Watch pressure.

### Goals That Should Not Justify an Upgrade to 1.37

- Increasing vLLM/SGLang Token/s;
- Increasing NCCL or RDMA bandwidth;
- Automatically solving GPU fragmentation and quota fair sharing;
- Automatically replacing Volcano, Kueue, GPU Operator, DCGM, or inference gateways;
- Obtaining full DRA capabilities without changing Drivers, Runtime, or monitoring.

### Upgrade Checklist

1. **Do not skip from 1.35 to 1.37, bypassing 1.36.** Kubernetes' version skew policy does not support
   `kube-apiserver` skipping minor versions; upgrade step by step following 1.35 → 1.36 → 1.37.
2. Confirm nodes use cgroup v2. Since 1.35, `failCgroupV1` defaults to `true`; temporarily disabling it is not a long-term
   solution, as new capabilities such as Memory QoS also depend on cgroup v2.
3. Verify that managed Kubernetes, CNI, CSI, GPU/NPU drivers, DRA drivers, and monitoring stacks declare support for 1.37;
   an upstream release does not mean cloud vendors can upgrade on the same day.
4. Reproduce real training queues, Device Plugin/DRA, node maintenance, and model cold starts in a test cluster; do not just run
   `nginx` Smoke Test.
5. Roll out Beta capabilities one by one with canary; Alpha Feature Gates are disabled by default, and prepare rollback paths for API and behavior changes.

## My assessment

If 1.35 is the "starting point" for Kubernetes-native Workload-aware Scheduling, 1.37 is the first Beta version that can be seriously
evaluated; if 1.34's DRA GA is the "foundation" of the device API, 1.37 fills in the walls and doors that affect production adoption:
legacy resource compatibility, device isolation, status, and NUMA.

Therefore, the value of 1.37 for AI platforms is mainly **reducing resource waste, device management complexity, and failure uncertainty**, not
making individual inference faster out of thin air. Production clusters can begin controlled comparison experiments with DRA and native WAS, but the
safest path at this stage remains combining Kubernetes-native capabilities with mature Kueue/Volcano, device drivers, monitoring, and inference gateways.

## References

- [Kubernetes v1.37 release announcement](https://kubernetes.io/blog/2026/08/26/kubernetes-v1-37-release/)
- [Kubernetes 1.37 version status](https://kubernetes.io/releases/1.37/)
- [Kubernetes v1.35 release announcement](https://kubernetes.io/blog/2025/12/17/kubernetes-v1-35-release/)
- [Kubernetes v1.35: Workload-aware Scheduling](https://kubernetes.io/blog/2025/12/29/kubernetes-v1-35-introducing-workload-aware-scheduling/)
- [Kubernetes v1.36: Subsequent evolution of Workload-aware Scheduling](https://kubernetes.io/blog/2026/05/13/kubernetes-v1-36-advancing-workload-aware-scheduling/)
- [Kubernetes v1.36: DRA updates](https://kubernetes.io/blog/2026/05/07/kubernetes-v1-36-dra-136-updates/)
- [DRA device status and health observability](https://kubernetes.io/docs/concepts/resource-management/dynamic-resource-allocation/dra-observability/)
- [DRA Device Taints and Tolerations](https://kubernetes.io/docs/concepts/resource-management/dynamic-resource-allocation/device-taints/)
- [HPA scale-from-zero](https://kubernetes.io/docs/concepts/workloads/autoscaling/horizontal-pod-autoscale/#scaling-to-and-from-zero)
- [Kubernetes Version Skew Policy](https://kubernetes.io/releases/version-skew-policy/)
- [Kueue Topology-aware Scheduling](https://kueue.sigs.k8s.io/docs/concepts/topology_aware_scheduling/)
- [Kueue All-or-nothing Scheduling](https://kueue.sigs.k8s.io/docs/concepts/all_or_nothing/)
