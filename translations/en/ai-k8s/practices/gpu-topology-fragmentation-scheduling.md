---
title: "How to Avoid Getting Cross-NUMA Fragmented GPUs for a 4-GPU Task on an 8-GPU Node"
description: "From NVIDIA Device Plugin, Topology Manager, Volcano, Koordinator, HAMi to Kubernetes DRA: evaluating the real capabilities and production adoption paths of GPU device topology-aware scheduling"
status: evolving
last_reviewed: 2026-08-26
---

# How to Avoid Getting Cross-NUMA Fragmented GPUs for a 4-GPU Task on an 8-GPU Node

An 8-GPU server still has 4 GPUs free, and a 4-GPU inference task starts successfully — yet performance is worse than normal. Only after entering the container do you discover that the task did not receive 4 GPUs from the same high-speed interconnect domain, but rather a fragmented combination spanning NUMA domains and PCIe Root Complexes.

This is not a simple "number of free GPUs" problem. It is because Kubernetes node selection and GPU device selection happen at different stages. The traditional scheduler sees that the node still has 4 `nvidia.com/gpu`, but it does not necessarily know the UUIDs, NUMA domains, PCIe topology, or NVLink relationships of the specific free GPUs.

As of August 2026, the community has multiple topology-aware approaches, but their capability boundaries differ significantly:

- NVIDIA Device Plugin can **prefer** topologically closer devices, but cannot guarantee that a Pod will wait when no complete 4-GPU group exists;
- Kubelet Topology Manager can enforce strict admission on the node side, but the scheduler may not know in advance that the node cannot satisfy the requirement;
- Volcano's `numa-aware` currently mainly handles CPU NUMA and has not yet fully solved NUMA scheduling for standard full-GPU allocations;
- Koordinator can already express same-NUMA, same-PCIe, or strict GPU Partition constraints at the scheduling stage, and is currently the open-source solution closest to this requirement;
- Kubernetes DRA can express "4 GPUs must share the same NUMA attribute" at the API layer, which is the most standards-aligned direction, but the NVIDIA GPU DRA Driver still needs to be validated for maturity against the target version.

This article evaluates community-public capabilities and does not represent measured conclusions from any specific cluster. Before production selection, fault injection and regression testing should still be performed on the target Kubernetes, GPU Driver, and hardware topology.

## 1. First, Describe the Problem Accurately

Assume the actual topology of a server is:

```text
NUMA 0 / PCIe Island A       NUMA 1 / PCIe Island B
GPU 0  GPU 1  GPU 2  GPU 3   GPU 4  GPU 5  GPU 6  GPU 7
```

The ideal allocation for a 4-GPU task is:

```text
GPU 0-3
或
GPU 4-7
```

As different inference instances exit at different times, the node may be left with only the following four free GPUs:

```text
占用  占用  空闲  空闲   空闲  空闲  占用  占用
GPU0  GPU1  GPU2  GPU3   GPU4  GPU5  GPU6  GPU7
```

From a resource-count perspective, the node indeed still has 4 GPUs; from a communication-topology perspective, the only combination `GPU 2-5` spans two NUMA or PCIe domains. For tasks with Tensor Parallel, frequent Collectives, or P2P communication, this can add traffic on Host Bridge and UPI/CPU Interconnect paths, degrading throughput and tail latency.

### 1.1 "Consecutive Indexes" Do Not Equal "Topologically Adjacent"

`GPU 0-3` cannot be permanently equated with a single NUMA domain. GPU Index can be affected by driver enumeration order, `CUDA_DEVICE_ORDER`, MIG, and in-container remapping. The judgment basis should be GPU UUID and the real topology:

```bash
nvidia-smi -L
nvidia-smi topo -m
nvidia-smi topo -p2p r
```

Platform policy should express "same NUMA domain," "same PCIe Switch," or "belongs to the same validated Partition," rather than merely checking whether indexes are consecutive.

### 1.2 This Is Two Decisions, Not One

In the traditional Device Plugin model, the chain is roughly:

```text
Pod 请求 nvidia.com/gpu: 4
          │
          ▼
kube-scheduler 选择一个还剩 4 张卡的节点
          │  此时主要看到整数容量
          ▼
kubelet 调用 Device Plugin
          │
          ▼
Device Plugin 从该节点空闲 UUID 中选择 4 张
          │
          ▼
容器获得 CUDA_VISIBLE_DEVICES / CDI Devices
```

If topology constraints are only discovered at the kubelet or Device Plugin stage, the scheduler has already completed node binding. This is the root cause of "total count is sufficient, but the combination is bad."

## 2. What to Evaluate When Assessing a Solution

Simply writing "NUMA-aware" is meaningless. At minimum, five questions must be answered:

| Evaluation Dimension | Key Question |
| --- | --- |
| Device Visibility | Does the component see an integer GPU count, or per-GPU UUID, NUMA, PCIe, and NVLink attributes? |
| Decision Timing | Is the decision made before the scheduler selects a node, or after the Pod is bound to a node? |
| Constraint Semantics | Is it `Preferred` best-effort, or `Required/Restricted` wait if not satisfied? |
| Fragmentation Governance | Can it only avoid new fragmentation, or can it recover complete groups through reservation, preemption, or rescheduling? |
| Production Cost | Does it require replacing the scheduler, Device Plugin, and resource API? How are upgrade, rollback, and observability handled? |

The most important thing in this scenario is not "whether good GPUs can be selected," but:

> When only `GPU 2-5` remains, can the system reject this degraded combination, keep the 4-GPU task Pending, and look for a complete topology domain on other nodes.

## 3. NVIDIA Device Plugin: Lowest-Cost Topology Preference

The current NVIDIA Device Plugin implements `GetPreferredAllocation`. Its GPU Allocator references device PCIe and NVLink topology, prefers combinations with closer relationships among available devices, and considers preserving better combinations for subsequent same-scale requests. The relevant implementation can be viewed directly in the [NVIDIA Device Plugin allocation service](https://github.com/NVIDIA/k8s-device-plugin/blob/main/internal/plugin/server.go) and [NVIDIA go-gpuallocator](https://github.com/NVIDIA/go-gpuallocator).

It is suitable as a first-layer low-cost optimization: when both `GPU 0-3` and `GPU 4-7` are fully free, it prefers selecting a better 4-GPU set rather than randomly splitting the two sets apart.

But it cannot alone provide the hard guarantee this scenario needs:

- kube-scheduler still selects nodes primarily based on `nvidia.com/gpu: 4`;
- `GetPreferredAllocation` is device preference applied after the node has already been selected;
- If the node only has `GPU 2-5` left, the Allocator is not equivalent to a cluster-level topology scheduler;
- Different Device Plugins, MIG modes, and hardware reporting quality affect actual results; the existence of an interface alone does not mean it is effective.

Therefore, a more accurate assessment of NVIDIA Device Plugin is: **it can reduce unnecessary bad allocations, but it cannot replace strict device topology scheduling.**

## 4. Kubelet Topology Manager: Can Be Strict, but Rejects Too Late

Kubernetes Topology Manager aggregates topology hints from CPU Manager, Memory Manager, and Device Manager in the kubelet. The `restricted` and `single-numa-node` policies can reject Pods that do not satisfy alignment conditions; Device Plugins can also report the NUMA Node associated with a device via `TopologyInfo`. [Kubernetes Topology Manager](https://kubernetes.io/docs/tasks/administer-cluster/topology-manager/) and [Device Plugin API](https://kubernetes.io/docs/concepts/extend-kubernetes/compute-storage-net/device-plugins/) describe this chain.

It is suitable for single-machine HPC workloads where CPU, HugePages, memory, and GPU must all reside on the same NUMA domain, but it has an architectural limitation: Topology Manager is a kubelet component, not a scheduler plugin. The official documentation also notes that Pods rejected by topology admission will not be automatically rebound to another node by the scheduler; a higher-level Deployment or Job may keep creating replacement Pods that repeatedly hit the wrong node.

| Advantages | Limitations |
| --- | --- |
| Native Kubernetes capability | Decision happens after node binding |
| Can use strict admission policies | Scheduler lacks per-device topology inventory |
| Can coordinate CPU, memory, and device NUMA | Mishandling can create a create-reject-retry loop |

So it is suitable as a **last line of defense on the node side**, but should not be the only GPU topology scheduling solution for a large-scale cluster.

## 5. Volcano: Right Direction, but Do Not Overestimate Current Capability

When people see this scenario, the first reaction of many is Volcano `numa-aware`. This judgment is not unreasonable: Volcano is inherently good at Gang, Queue, DRF, preemption, and AI/HPC-oriented batch scheduling, and it does have a NUMA-aware plugin.

The problem is that CPU NUMA-aware does not equal GPU Device NUMA-aware. The Volcano community's publicly disclosed [GPU NUMA topology-aware scheduling Issue](https://github.com/volcano-sh/volcano/issues/4998) in 2026 explicitly states that the current `numa-aware` mainly supports CPU NUMA and does not yet consider GPU NUMA when scheduling GPU workloads. The example in the Issue is also an 8-GPU node divided into two 4-GPU NUMA domains, hoping to avoid getting a cross-domain 4-GPU combination.

Volcano vGPU provides annotations such as `volcano.sh/vgpu-use-gpuuuid` and `volcano.sh/vgpu-nouse-gpuuuid` to specify or exclude GPU UUIDs; see [Volcano vGPU usage documentation](https://github.com/volcano-sh/volcano/blob/master/docs/user-guide/how_to_use_volcano_vgpu.md). But this is closer to manual device binding and does not equal automatically finding a complete 4-GPU topology domain for standard full-GPU requests.

Additionally, Volcano's [Network Topology-aware Scheduling](https://github.com/volcano-sh/volcano/blob/master/docs/design/Network%20Topology%20Aware%20Scheduling.md) mainly handles placement across nodes, racks, and network domains, and cannot be directly inferred as "will select which four GPUs within a node."

Therefore, as of this article's review date:

> Volcano can continue to handle queues, Gang scheduling, and cross-node topology scheduling, but enabling `numa-aware` does not mean this scenario is already solved.

## 6. Koordinator: The Open-Source Implementation Closest to This Requirement Today

Koordinator reports per-device information as `Device` objects, including device ID, Bus ID, NUMA Node, and PCIe ID, and then `koord-scheduler` performs device selection at the scheduling stage. This avoids the time gap where "the scheduler blindly selects a node first, and the kubelet discovers the topology mismatch later." [Koordinator Device architecture](https://koordinator.sh/docs/next/architecture/device) and its [NUMA-aware Scheduling design](https://github.com/koordinator-sh/koordinator/blob/main/docs/proposals/scheduling/20230415-numa-topology-scheduling.md) explain this mechanism.

Koordinator has publicly supported:

- GPUs must reside on the same NUMA Node;
- GPUs must reside in the same PCIe topology domain;
- NUMA alignment of CPU, memory, and GPU;
- Predefined GPU Partitions;
- Joint topology allocation of GPU and RDMA NICs.

Taking same-NUMA as an example, its public configuration approach is as follows:

```yaml
metadata:
  annotations:
    scheduling.koordinator.sh/device-allocate-hint: |
      {
        "gpu": {
          "requiredTopologyScope": "NUMANode"
        }
      }
spec:
  schedulerName: koord-scheduler
  containers:
    - name: inference
      resources:
        limits:
          koordinator.sh/gpu: "400"
```

The resource name and `400` metering method here come from Koordinator's public examples, representing four full GPUs; actual deployment must be adjusted according to the version in use, device plugin, and resource protocol, and cannot be copied directly into an existing cluster. For a full capability example, see [Koordinator v1.6 release notes](https://koordinator.sh/blog/release-v1.6.0).

For topologically stable 8-GPU nodes, a more easily verifiable and explainable approach is to predefine two GPU Partitions:

```text
Partition A = GPU 0、1、2、3 对应的四个 UUID
Partition B = GPU 4、5、6、7 对应的四个 UUID
```

The 4-GPU workload uses `Restricted` allocation semantics: it runs only when a complete Partition exists; it stays Pending when only four cross-domain fragmented GPUs remain. This not only protects the current task but also lets the scheduler continue searching for other nodes across the cluster.

Koordinator's cost must also be stated clearly: it is not something that takes effect automatically by adding one annotation to an existing Pod. The platform needs to deploy and maintain `koord-scheduler`, `koordlet`, Device CRDs, and the corresponding device allocation chain, and verify compatibility with the current NVIDIA Device Plugin, GPU Operator, MIG, monitoring, and quota systems.

Overall, if the goal is to **obtain strict GPU NUMA/PCIe constraints at the scheduling stage in a traditional Kubernetes cluster as quickly as possible**, Koordinator is currently the most worthwhile solution for a PoC.

## 7. Kubernetes DRA: The Cleanest API Semantics for the Long Term

Dynamic Resource Allocation no longer represents a GPU as just an integer; instead, the Driver publishes each device and its attributes. `ResourceClaim` can use `matchAttribute` constraints to require that multiple devices in a single request share the same attribute. Kubernetes' standard NUMA attribute design provides exactly the expression for same-NUMA device allocation; see [ResourceClaim API](https://kubernetes.io/docs/reference/kubernetes-api/resource/resource-claim-v1/) and the [DRA standard NUMA Node attribute KEP](https://github.com/kubernetes/enhancements/blob/master/keps/sig-node/6072-dra-standard-numanode/README.md).

Conceptually, four GPUs on the same NUMA domain can be expressed as:

```yaml
devices:
  requests:
    - name: gpu
      exactly:
        deviceClassName: gpu.nvidia.com
        count: 4
  constraints:
    - requests:
        - gpu
      matchAttribute: resource.kubernetes.io/numaNode
```

When no four GPUs with the same NUMA attribute exist, the Claim cannot complete allocation and the Pod stays Pending. This aligns better with how the scheduler works than "select a node first, then let the kubelet reject."

But production evaluation cannot stop at whether the API looks clean. The NVIDIA GPU DRA Driver is still evolving rapidly; its repository currently still warns that some GPU allocation capabilities are not yet officially supported or enabled by default, and deployment depends on the corresponding Kubernetes and GPU Operator versions. Before upgrading, you need to verify the Driver Release, Feature Gates, Resource API version, Claim reclamation, and failure recovery; see [NVIDIA GPU DRA Driver](https://github.com/kubernetes-sigs/dra-driver-nvidia-gpu).

Therefore, DRA is suitable for the medium-to-long-term technical roadmap, with PoC on a dedicated node pool; for production clusters with an established Device Plugin chain, a full replacement should not be done solely for this one problem at this time.

## 8. HAMi: Suitable for Clusters That Already Have vGPU Requirements

[HAMi](https://github.com/Project-HAMi/HAMi) provides GPU sharing, GPU memory isolation, and topology-aware capabilities, and completes device allocation through collaboration among Scheduler Extender, Webhook, and Device Plugin. If the platform is already evaluating vGPU, GPU memory partitioning, and improving development-cluster utilization, it is worth validating together.

But for the single requirement of "exclusive full-GPU 4-GPU inference must reside on the same hardware island," introducing the full HAMi device stack is usually heavier than Koordinator Partition. Community discussions about NUMA selection, device accounting, and state consistency also indicate this area is still evolving; for example, [HAMi NUMA-related Issue](https://github.com/Project-HAMi/HAMi/issues/2080).

A more prudent positioning is: clusters already using HAMi should validate its topology policy; clusters that only need strict full-GPU grouping do not need to introduce a GPU sharing system just for this capability.

## 9. No Scheduler Can Losslessly "Rearrange" GPUs in Active Use

Topology awareness can prevent further fragmentation, but it cannot live-migrate a running ordinary CUDA process from GPU 6 to GPU 2. To regain a complete 4-GPU partition, the only options are to combine:

- Wait for short tasks to finish naturally;
- Drain traffic, then evict and rebuild small inference Pods;
- Use PriorityClass and topology-aware preemption;
- Reserve a complete Partition or dedicated node pool for four-GPU tasks;
- Let 1-GPU and 2-GPU tasks Binpack preferentially within one Partition, avoiding contaminating both four-GPU domains at the same time;
- For resumable training tasks, pair with Checkpoint; for online inference, pair with multiple replicas and graceful shutdown.

Do not manually set `CUDA_VISIBLE_DEVICES=0,1,2,3` to bypass Device Plugin resource accounting. When the scheduler is unaware that these GPUs are already in use, it may assign the same device to another Pod. Directly using `nodeName` to pin nodes only solves node selection, not the safe allocation of device UUIDs.

## 10. Recommended Implementation Path

### Phase One: First Confirm Whether the Existing Pipeline Is Wasting Capability

Without changing cluster policies, complete a read-only audit first:

1. Use GPU UUIDs to build the actual NUMA, PCIe, and NVLink/NVSwitch topology map;
2. Record the Kubernetes, Driver, GPU Operator, and NVIDIA Device Plugin versions;
3. Confirm whether Device Plugin's Preferred Allocation is being invoked;
4. Repeatedly create four-GPU Pods on an idle 8-GPU node and record the actual UUIDs allocated;
5. Construct the two states of "two complete four-GPU domains" and "only cross-domain four GPUs remaining" respectively;
6. Record Pod events, device allocation results, and business performance — do not rely only on `nvidia-smi` screenshots.

This phase determines whether the problem is "capability not enabled," "topology reporting errors," or whether scheduling-time hard constraints are genuinely needed.

### Phase Two: Validate Koordinator with One Node Pool

The PoC must include at least four acceptance cases:

| Case | Expected Result |
| --- | --- |
| 8 GPUs idle, submit two four-GPU tasks | Each gets two complete topology domains |
| Only same-domain four GPUs remain | The task gets that complete group |
| Only cross-domain four GPUs remain | Restricted task stays Pending |
| Release one complete group | The Pending task automatically obtains that group and runs |

Also validate scheduler restart, koordlet restart, node NotReady, forced Pod deletion, MIG toggling, and Device CRD state recovery. A successful normal path alone does not prove production readiness.

### Phase Three: Govern Fragmentation Caused by Small Tasks

It is recommended to define three service classes explicitly:

| Workload | Recommended Policy |
| --- | --- |
| 1/2-GPU development and general inference | Binpack within Partition, allow Preferred |
| 4/8-GPU communication-sensitive inference | Same NUMA/PCIe or strict Partition |
| Interruptible training and batch tasks | Checkpoint + low priority + preemptable |

If four-GPU online services have clear SLOs, reserve one complete four-GPU domain rather than expecting the scheduler to automatically piece together contiguous resources on a fully loaded node at any time.

### Phase Four: Track DRA Instead of Making a One-Time Bet

Validate on an isolated test node:

- Whether the NVIDIA Driver correctly reports the standard NUMA attributes for each GPU;
- Whether `matchAttribute` rejects cross-NUMA combinations at the scheduling stage;
- Whether ResourceClaim is correctly reclaimed after Pod deletion, node failure, and Driver restart;
- Whether DRA can close the loop with GPU Operator, monitoring, billing, queues, and autoscalers;
- Whether rolling back from Device Plugin requires modifying all workload APIs.

## 11. Final Assessment

| Requirement | Recommendation |
| --- | --- |
| Only want to reduce random assignment to poor topology | First validate NVIDIA Device Plugin Preferred Allocation |
| CPU, memory, and devices must share the same NUMA | Add Kubelet Topology Manager as node-side protection |
| Four-GPU tasks must be complete NUMA/PCIe groups | Prioritize validating Koordinator Device Topology / GPU Partition |
| Already using Volcano to manage batch tasks | Keep Queue/Gang capabilities, but do not treat the existing `numa-aware` as a GPU NUMA solution |
| Already using HAMi for GPU sharing | Validate its topology policy and strict semantics within the existing stack |
| Want to adopt the Kubernetes standard device attribute API | Track DRA, and first validate the NVIDIA Driver on an isolated node pool |

The platform contract this problem truly needs is not "try to pick contiguous GPUs," but rather the following two semantics that users can understand:

```text
Preferred：有好拓扑就用，没有也允许退化运行。
Restricted：没有完整拓扑域就等待，绝不静默退化。
```

For communication-sensitive four-GPU inference or training, adopting `Restricted` by default makes performance predictability easier to guarantee; for throughput-first, topology-insensitive small tasks, `Preferred` can be traded for higher resource utilization. Explicitly exposing these two policies is more aligned with production reality than disguising all GPUs as completely homogeneous integer resources.

Further reading: [GPU and Heterogeneous Resource Scheduling](../gpu-scheduling.md), [Why Pods Remain Pending When GPUs Are Idle](gpu-pending.md), [GPU Resource Bank and Tidal Inference Platform Practice Blueprint](gpu-resource-bank-tidal-platform.md)
