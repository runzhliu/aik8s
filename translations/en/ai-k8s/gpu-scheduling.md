---
title: "GPU and Heterogeneous Resource Scheduling"
description: "Full-GPU, MIG, sharing, topology, affinity, and resource fragmentation governance"
status: evolving
last_reviewed: 2026-08-02
---

# GPU and Heterogeneous Resource Scheduling

The hardest part of a GPU cluster is usually not "installing CUDA," but keeping drivers, runtimes, device plugins, scheduling policies, and monitoring data mutually compatible over the long term. This page explains how Kubernetes manages GPUs from a platform engineering perspective, and when to use sharing, Kueue, Volcano, and DRA.

For full-GPU, MIG, Time-Slicing, GPU memory estimation, user specifications, and idle reclamation in interactive R&D environments, see [GPU Notebook Platforms and Storage Selection in the Large Model Era](development/gpu-notebook-platform.md).

## 1. Responsibility Boundaries of the GPU Software Stack

```text
训练或推理容器
    │ CUDA / ROCm / XPU Runtime
    ▼
Container Toolkit 与 CDI
    │ 把设备、库和环境注入容器
    ▼
Device Plugin 或 DRA Driver
    │ 发布设备库存并完成分配
    ▼
kubelet / scheduler / Kueue
    │ 节点放置、队列准入、配额和拓扑
    ▼
内核驱动 / GPU / NVLink / RDMA 网络
```

NVIDIA GPU Operator manages drivers, Container Toolkit, Device Plugin, GPU Feature Discovery, MIG Manager, and DCGM Exporter as a software stack that can be upgraded in a coordinated manner. It reduces manual installation, but it does not mean all components can be freely combined across versions; production upgrades still require checking the support matrix for Kubernetes, OS, kernel, driver, and GPU Operator.

Reference: [NVIDIA GPU Operator](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/)

## 2. Four Ways to Use GPUs

| Mode | Isolation | Suitable Scenarios | Main Limitations |
| --- | --- | --- | --- |
| Full-GPU exclusive | GPU memory and compute are exclusive | Training, large model inference, performance benchmarks | Small tasks may have very low utilization |
| MIG | Hardware-level GPU memory and fault isolation | Multi-tenant inference, stable partitioning of MIG-capable GPUs such as A100/H100 | Configuration profiles are fixed; changing geometry may require draining workloads or even rebooting nodes |
| Time-Slicing | Time-multiplexing only, no GPU memory or fault isolation | Notebooks, development and testing, low-intensity inference | One task OOM or failure can affect other tasks on the same GPU; per-container attribution is more difficult |
| MPS | CUDA process-level concurrent sharing | Small tasks in the same trust domain with low compute utilization | Operations and isolation model are more complex; not all workloads benefit |

NVIDIA official documentation explicitly states that Time-Slicing does not provide the GPU memory or fault isolation of MIG; requesting multiple shared resources also does not mean getting proportional compute. Therefore, do not mistake `nvidia.com/gpu: 4` shared GPUs for four exclusive GPUs.

References: [Time-Slicing vs. MIG Comparison](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/25.3/gpu-sharing.html), [GPU Operator MIG](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/gpu-operator-mig.html)

### Recommended Principles

- Use full-GPU by default for training and latency-sensitive large model inference.
- Use MIG when strong tenant isolation is required and the GPU supports it.
- Development environments can use Time-Slicing, but namespace, concurrency, and GPU memory usage should be limited.
- In the same resource pool, do not rely on verbal agreements for "exclusive" vs. "shared"; use node pools, labels, RuntimeClass, or different ResourceFlavors to isolate them explicitly.

## 3. From Node Labels to Device Attributes

Traditional Device Plugin exposes GPUs as integer extended resources:

```yaml
resources:
  limits:
    nvidia.com/gpu: 1
```

It is simple and stable, but has limited expressiveness. If workloads require a specific GPU model, GPU memory, or network topology, they typically also rely on node labels:

```yaml
nodeSelector:
  nvidia.com/gpu.product: NVIDIA-H100-80GB-HBM3
```

This model describes "a node has a certain type of device," not each individual device. Dynamic Resource Allocation (DRA) adds `DeviceClass`, `ResourceSlice`, and `ResourceClaim`, allowing Drivers to publish device-level attributes and workloads to request specific devices by capability.

Situations suitable for gradually introducing DRA:

- The cluster contains multiple generations, models, or partitionable devices;
- You want to express GPU memory minimums, candidate device fallback, or device-level health status;
- You need to model fabric-attached devices, GPU partitions, and shared capacity;
- The vendor DRA Driver already covers current hardware and upgrade scenarios.

Situations where keeping Device Plugin is appropriate for now:

- A single GPU model with full-GPU exclusive already meets requirements;
- The vendor Driver does not yet provide production support;
- Existing monitoring, billing, and admission policies strongly depend on extended resources;
- The team has not yet tested Driver restart, node drain, Claim reclamation, and rollback.

Reference: [Kubernetes DRA](https://kubernetes.io/docs/concepts/scheduling-eviction/dynamic-resource-allocation/)

## 4. Pod Scheduling, Queue Admission, and Cluster Scaling Are Not the Same Thing

| Decision | Common Components | Question Answered |
| --- | --- | --- |
| Workload admission | Kueue | Which Job is now eligible to use how much quota? |
| Pod placement | kube-scheduler / Volcano | Which node does the Pod actually land on? |
| Node provisioning | Cluster Autoscaler / Karpenter | Should GPU nodes be created or deleted? |
| Device allocation | Device Plugin / DRA Driver | Which device does the container ultimately get? |

If the boundaries between these four layers are unclear, problems frequently arise such as "the queue has admitted the workload, but nodes cannot scale out," "nodes have been created, but the distributed job is only half scheduled," or "the Pod is running, but got the wrong GPU model."

## 5. How to Choose Between Kueue and Volcano

### Kueue

Kueue does not replace kube-scheduler. It performs workload-level admission before Pod creation or running, providing:

- `ClusterQueue` and `LocalQueue`;
- Multi-tenant quotas, borrowing, fair sharing, and preemption;
- `ResourceFlavor` to express resource types such as H100, A100, and Spot;
- All-or-Nothing, partial admission, and dynamic return;
- Topology-Aware Scheduling and MultiKueue;
- Integration with Job, JobSet, Kubeflow Trainer, KubeRay, and LeaderWorkerSet.

Kueue is suitable for teams that want to keep the native Kubernetes scheduling chain and only add queue and quota governance.

### Volcano

Volcano provides an independent batch scheduler, with strengths including:

- PodGroup and Gang Scheduling;
- Queue, DRF, fairness, priority, preemption, and backfill;
- Support for mixed workloads such as AI, HPC, Spark, Flink, and Ray;
- More controllable scheduler plugin chains and online/offline workload colocation policies.

Volcano is suitable for clusters that already have a large number of batch jobs, need a unified scheduling algorithm, or require stronger control over Gang/preemption behavior.

### Simple Decision Guide

| Requirement | Evaluate First |
| --- | --- |
| Add quotas and Job queues on standard Kubernetes | Kueue |
| Complex Gang, DRF, backfill, and batch scheduling policies | Volcano |
| Already have stable kube-scheduler extensions and do not want to introduce a second scheduler | Kueue |
| AI, HPC, and big data all managed by a dedicated batch scheduler | Volcano |

References: [Kueue Overview](https://kueue.sigs.k8s.io/docs/overview/), [Kueue Topology-Aware Scheduling](https://kueue.sigs.k8s.io/docs/concepts/topology_aware_scheduling/), [Volcano Architecture](https://volcano.sh/docs/home/architecture/)

## 6. Why Topology Directly Affects Training Cost

Multi-node training All-Reduce or All-to-All exchanges large amounts of data. With the same number of GPUs, actual training time can differ significantly between cross-rack, cross-switch, and same-node NVLink placements. Therefore, scheduling cannot only satisfy "32 GPUs in total"; it must also consider:

- Whether GPUs are on the same node and in the same NVLink Domain;
- Whether nodes are in the same rack or network Block;
- RDMA / RoCE interfaces, NUMA, and CPU affinity;
- Whether data is on local NVMe or in the same availability zone storage;
- Whether Spot and On-Demand nodes are mixed in the same distributed job.

It is recommended to maintain stable topology labels for nodes, and let Kueue TAS or the scheduler decide whether a Pod group needs to be "as concentrated as possible" or "must be in the same topology domain." Do not let training scripts guess physical topology themselves.

Topology fragmentation can also exist within a node: for example, an 8-GPU node may still have 4 GPUs free, but the idle devices span two NUMA or PCIe domains. Traditional extended resources only express quantity and cannot guarantee that a 4-GPU task gets a complete high-speed interconnect group. For the capability boundaries and deployment choices of NVIDIA Device Plugin, Topology Manager, Volcano, Koordinator, HAMi, and DRA, see [How to Avoid Getting Cross-NUMA Fragmented GPUs for a 4-GPU Task on an 8-GPU Node](practices/gpu-topology-fragmentation-scheduling.md).

## 7. Capacity and Quota Models

A GPU platform needs at least three accounting dimensions:

1. **Physical capacity**: Actual GPUs, MIG instances, and available GPU memory.
2. **Allocatable capacity**: Capacity after deducting failures, maintenance, and platform reservations.
3. **Committed capacity**: Each team's nominal quota, plus the upper limit allowed for borrowing.

Recommended operational metrics to record:

| Metric | Purpose |
| --- | --- |
| GPU allocation ratio | Allocated GPUs / allocatable GPUs, measures scheduling occupancy |
| SM utilization | Determines whether tasks are actually using compute capacity |
| Framebuffer memory | Detects insufficient GPU memory or long-term idle occupancy |
| Queue wait time | Measures whether quota and capacity match demand |
| Admission failure reason | Distinguishes missing quota, missing model, missing topology, or scaling failure |
| Job completion / retry rate | Determines platform stability and waste |

DCGM Exporter can expose GPU, MIG, and some DRA attribution information to Prometheus; when using Time-Slicing, note the limitations of per-container metric attribution.

Reference: [DCGM Exporter](https://docs.nvidia.com/datacenter/dcgm/latest/installation/install-dcgm-exporter.html)

## 8. Production Checklist

- [ ] Pin and record the version matrix for Kubernetes, kernel, driver, Toolkit, and GPU Operator.
- [ ] Group node pools by GPU model, sharing policy, and network capability.
- [ ] Set dedicated taints for GPU workloads to prevent ordinary Pods from occupying expensive nodes.
- [ ] Define queues, nominal quotas, borrowing, and preemption policies for each team.
- [ ] Use Gang/All-or-Nothing for distributed jobs to avoid partial startup occupying GPUs for long periods.
- [ ] Incorporate rack, Block, and NVLink/RDMA capabilities into topology scheduling.
- [ ] Monitor XID, temperature, power, GPU memory, SM, queue wait time, and failure reasons.
- [ ] Validate node drain, driver upgrade, MIG reconfiguration, and DRA Driver restart procedures.
- [ ] Make isolation commitments explicit for shared GPUs; do not present Time-Slicing as strong isolation.
- [ ] Bill using both requested amount, occupied time, and effective utilization, not just Pod count.

Next: [RDMA and AI High-Speed Networks](rdma-networking.md) will further explain how GPUs, NICs, RoCE/InfiniBand, and Kubernetes networking components connect.
