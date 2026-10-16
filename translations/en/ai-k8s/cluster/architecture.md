---
title: "AI Kubernetes Cluster Architecture Design"
description: "Plan training and inference clusters from failure domains, node pools, control plane, network, and storage"
status: stable
last_reviewed: 2026-08-03
---

# AI Kubernetes Cluster Architecture Design

AI cluster design does not start with installing a chain of Operators. It starts with clarifying workloads, failure domains, performance paths, and team boundaries. With the same number of GPUs, the wrong node pool, network, or capacity model can yield very different throughput, availability, and cost.

## 1. Start from Workloads

First, collect four categories of profiles:

| Profile | Questions to answer |
| --- | --- |
| Training | Single-node or multi-node, GPU count, maximum runtime, Checkpoint, Spot tolerance |
| Online inference | Model size, context length, TTFT/TPOT, traffic peaks, availability |
| Batch inference and data | Data volume, concurrency, completion deadlines, CPU/GPU ratio, read/write patterns |
| Interactive development | Notebook count, trust level, idle time, external network and data permissions |

Do not design capacity using averages. Training cares about the full set of GPUs requested at once, online inference cares about peaks and failure redundancy, while Notebooks are more likely to produce long-duration low-utilization occupancy.

## 2. Recommended Logical Layering

```text
入口层
  Gateway / SSO / API / GitOps
        │
平台控制层
  Kueue / Trainer / KServe / Policy / Observability
        │
通用计算池        GPU 训练池        GPU 推理池        高隔离池
  CPU Job          RDMA + 大块 GPU    稳定型号 + 缓存    Kata/独立节点
        │               │                │                │
集群网络、存储、Registry、对象存储、身份与密钥服务
```

Control components do not necessarily need to run on expensive GPU nodes. Reserving a general-purpose node pool for system components reduces the impact of GPU node maintenance and autoscaling on the control plane.

## 3. One Cluster or Multiple Clusters

### Conditions favoring one cluster

- Limited number of teams with similar identity and quota models;
- Training and inference can be isolated via node pools and queues;
- Same Kubernetes, driver, and Operator versions are used;
- A single control plane and failure domain meet business objectives;
- Data locality and compliance requirements are consistent.

### Conditions favoring multiple clusters

- Production inference and experimental training need independent upgrade windows;
- Different GPU/ASIC types require incompatible drivers or OS versions;
- Cross-region, data sovereignty, or network boundaries are explicit;
- Single-cluster scale already affects API Server, scheduling, or Blast Radius;
- Untrusted execution environments require stronger isolation;
- Edge sites must operate autonomously under weak network conditions.

Multiple clusters do not automatically solve governance problems. Each additional cluster requires replicating identity, policy, Registry, Secret, observability, version management, and disaster recovery capabilities.

For the history of multi-cluster, control plane layering, and specific combinations for GPU training and inference, see: [Kubernetes Cross-Cluster and Large-Scale GPU](multi-cluster-ai.md).

## 4. How to Partition Node Pools

Node pools should express hardware and operational boundaries, not every small team in the organizational structure.

At minimum, it is recommended to distinguish:

| Node pool | Typical capability | Key policy |
| --- | --- | --- |
| system | CPU, stable, on-demand | Hosts system controllers, avoid Spot |
| general | Balanced CPU/memory | Data processing, gateways, general services |
| gpu-training | High-speed interconnect, full GPUs, batch jobs | Kueue, topology, Checkpoint |
| gpu-inference | Stable models, local model cache | PDB, Canary, scaling protection |
| gpu-shared | MIG/Time-Slicing | Development only or explicit isolation commitments |
| sandbox | Kata/gVisor/confidential computing | Restrict network, devices, and identity |

Common node pool dimensions: accelerator model, GPU memory, interconnect type, CPU architecture, network, storage, local cache, purchase method, availability zone, and isolation level.

## 5. Labels, Taints, and ResourceFlavor

Stable labels represent platform commitments; auto-discovered labels represent hardware facts. The two should not be conflated.

```yaml
metadata:
  labels:
    platform.example.com/accelerator-class: h100-80g
    platform.example.com/network-class: roce-400g
    platform.example.com/lifecycle: on-demand
    topology.kubernetes.io/zone: zone-a
```

GPU nodes should have Taints set so that only workloads explicitly requesting GPUs tolerate them:

```yaml
spec:
  taints:
    - key: accelerator
      value: nvidia-h100
      effect: NoSchedule
```

Kueue `ResourceFlavor` can combine node labels, Taint tolerations, and quotas into user-understandable resource types, such as `h100-rdma` and `a100-spot`.

## 6. Control Plane Capacity

AI clusters tend to generate large numbers of short-lived Pods, Events, Jobs, and CRs. The control plane needs attention on:

- API request rate and object count;
- etcd database size, fragmentation, and backups;
- scheduler Pending Pod count and scheduling latency;
- Webhook latency, failure policy, and availability;
- Controller workqueue depth and Reconcile errors;
- Log and Event retention time;
- Resource cleanup after large numbers of Jobs complete.

Do not let a single unavailable non-critical Webhook block Pod creation across the entire cluster. For every Admission Webhook, define `timeoutSeconds`, `failurePolicy`, and high-availability deployment explicitly.

## 7. Network Planes

At minimum, distinguish the following traffic types:

| Traffic | Characteristics | Design focus |
| --- | --- | --- |
| Kubernetes control traffic | Small packets, requires stability | API Server, DNS, CNI reliability |
| Training Collective | High bandwidth, low latency, synchronous | RDMA, lossless network, topology |
| Data and models | High throughput, bursty | Object storage, cache, egress capacity |
| Inference ingress | Long connections, streaming, tail latency | Gateway, connection timeouts, load balancing |
| Observability | High cardinality, continuous writes | Independent budget, sampling and retention |

The RDMA network should not be the only channel for ordinary Service traffic. Multi-network solutions must validate DNS, NetworkPolicy, MTU, Host Network, and failover behavior.

## 8. Storage Planes

It is recommended to choose by data type rather than using one shared file system for everything:

- Object storage: datasets, model archives, Checkpoints, and long-term artifacts;
- Shared/parallel file systems: training requiring POSIX, concurrent metadata, and low-latency reads;
- Block storage: databases, Notebook workspaces;
- Local NVMe: model cache, dataset cache, temporary Shuffle;
- Registry: container images and OCI model artifacts.

Local cache is regenerable data and should not be the only copy. The cost and throughput of cross-availability-zone reads must also enter the scheduling and capacity model.

## 9. Capacity and Redundancy

Usable GPU capacity is not the physical total:

```text
可分配容量 = 物理容量
            - 故障隔离
            - 节点维护
            - 系统预留
            - 拓扑碎片
            - 在线服务冗余
```

Training clusters commonly face the situation where "total capacity is sufficient but full groups are not." For example, 32 idle GPUs scattered across multiple network Blocks may not satisfy a 32-GPU job that requires a single high-speed domain.

Online inference should reserve redundancy for at least a single node, a single availability zone, or one rolling upgrade, depending on the SLO. Do not count training-borrowable capacity as inference failure redundancy.

## 10. Identity and Tenant Boundaries

It is recommended to draw the identity path clearly:

```text
人员 OIDC 身份
  → 平台 API / Git 变更
  → Kubernetes ServiceAccount
  → 云 Workload Identity
  → 对象存储、Registry、KMS、数据库
```

Training, inference, pipelines, and Notebooks use different ServiceAccounts. Cloud permissions are mapped through short-lived identities; long-term Access Keys are not stored in images or Git.

## 11. Environment and Release Strategy

At minimum, prepare:

- An integration environment without real production data;
- Canary nodes or small node pools for each production GPU type;
- Reproducible node image, driver, and Operator installation methods;
- Representative training, inference, RDMA, storage, and failure tests;
- A version matrix and rollback thresholds for each upgrade.

Development, pre-production, and production do not necessarily each need a full copy of an expensive GPU cluster. They can share a small amount of hardware, but must retain independent configuration, queues, and release gates.

## 12. Three Starting Architectures

### Small: 1–8 GPUs

- One cluster, with system and GPU node types;
- Device Plugin, basic monitoring, object storage;
- Minimal combination of Deployment/Job or KServe/Kueue;
- Do not deploy complex multi-cluster and split inference in advance.

### Medium: 8–128 GPUs

- Training, inference, and shared development node pools;
- Kueue, topology labels, autoscaling;
- Model cache, unified gateway, full observability;
- Canary nodes, version matrix, and cost attribution.

### Large: Hundreds of GPUs or more

- Plan by network Block, region, and failure domain;
- Workload-level topology, MultiKueue, or dedicated batch scheduling;
- Distributed model cache and inference request scheduling;
- Multi-cluster placement, capacity reservation, automatic failure isolation;
- Control plane and telemetry scale testing.

## 13. Architecture Review Checklist

- [ ] Real workload profiles exist for training, inference, batch processing, and Notebooks.
- [ ] Node pools express hardware, network, purchase method, and isolation boundaries.
- [ ] system controllers do not depend on GPU nodes that can scale to zero at any time.
- [ ] Control, training, storage, inference, and observability traffic boundaries are clear.
- [ ] Data, models, Checkpoints, and caches each have a chosen storage tier.
- [ ] Quota model accounts for topology fragmentation and inference redundancy.
- [ ] Identity is auditable end-to-end from personnel to cloud resources.
- [ ] Single-node, single-network-domain, and single-availability-zone failures have expected behavior.
- [ ] All critical components have Canary, upgrade, and rollback plans.
- [ ] Multi-cluster is driven by explicit failure domain or compliance requirements.

## Further Reading

- [Kubernetes Cluster Architecture](https://kubernetes.io/docs/concepts/architecture/)
- [Kubernetes Large Clusters](https://kubernetes.io/docs/setup/best-practices/cluster-large/)
- [Node Autoscaling](https://kubernetes.io/docs/concepts/cluster-administration/node-autoscaling/)
- [Kubernetes Multi-tenancy](https://kubernetes.io/docs/concepts/security/multi-tenancy/)
- [Kueue ResourceFlavor](https://kueue.sigs.k8s.io/docs/concepts/resource_flavor/)
