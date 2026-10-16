---
title: "Queues, Fair Sharing, and Multi-Tenancy"
description: "Kueue queues, ResourceFlavor, Cohort, priority, preemption, and tenant governance"
status: evolving
last_reviewed: 2026-08-02
---

# Queues, Fair Sharing, and Multi-Tenancy

Multi-tenancy on a GPU platform is not simply a matter of creating a namespace for each team. What really needs governance is: who can submit jobs, how much scarce resources they can occupy, whether idle quotas can be borrowed, how urgent tasks preempt others, and how different hardware and topologies are priced.

This chapter uses Kueue's model as the main thread, while also explaining its boundaries with Kubernetes scheduling, RBAC, and network isolation.

API request flow control and model interface rate limiting belong to a different governance layer; see the [Kubernetes flow control guide](cluster/flow-control.md).

## 1. Multi-Tenancy Has at Least Five Layers

| Layer | Problem Solved | Common Mechanisms |
| --- | --- | --- |
| Identity | Who is operating | OIDC, ServiceAccount, RBAC |
| API and Policy | What can be created | Admission, Kyverno/Gatekeeper, ResourceQuota |
| Resource Admission | When it can start, how much it can get | Kueue, Volcano |
| Runtime Isolation | Whether Pods affect each other | Namespace, NetworkPolicy, Pod Security, RuntimeClass |
| Cost and Audit | Who is accountable for resources | Labels, OpenCost, audit logs, budgets |

Namespace is part of the boundary, but it does not provide fair queuing, nor does it automatically prevent one team from occupying all GPUs for an extended period.

## 2. Kueue Object Relationships

```text
用户提交 Job
    │ queueName
    ▼
LocalQueue（namespace 内入口）
    │ 指向
    ▼
ClusterQueue（集群配额与策略）
    │ 使用
    ├── ResourceFlavor（GPU 型号、节点池、价格或区域）
    └── Cohort（多个队列之间借用空闲配额）
```

- `LocalQueue` gives tenants a stable entry point within a namespace;
- `ClusterQueue` defines nominal quota, borrowing, preemption, and queue policies;
- `ResourceFlavor` links resource quantities to node labels/taints;
- `Cohort` lets multiple ClusterQueues share temporarily idle quota;
- `Workload` is Kueue's unified representation of a workload awaiting admission.

Kueue only handles admission and quota; it does not replace kube-scheduler's Pod-to-Node placement. Reference: [Kueue Overview](https://kueue.sigs.k8s.io/docs/overview/)

## 3. Quotas Should Express Business Commitments

It is recommended to split quotas into three parts:

1. **Nominal quota**: the baseline a team can rely on long-term;
2. **Borrowing**: the upper limit that can be temporarily borrowed when other teams are not using their resources;
3. **Lending limit**: the maximum that can be lent out, to protect the queue's own future demand.

Nominal quota is not a static slice of machines. Reasonable sharing improves utilization, but borrowed workloads must accept the risk of waiting, being scaled down, or being preempted.

## 4. ResourceFlavor Is More Than Just a GPU Model

A Flavor can express:

- `h100`, `a100`, `l4` and other GPU models;
- On-demand, reserved, or Spot nodes;
- Nodes with RDMA or only standard Ethernet;
- Different regions, racks, or power domains;
- MIG, full-card, or other device partitioning schemes;
- Node pools where data is already pre-warmed.

Do not let users bind directly to specific node names. Let users declare performance or capability levels, and let queues and scheduling policies map those to hardware.

## 5. A Minimal Kueue Configuration

```yaml
apiVersion: kueue.x-k8s.io/v1beta1
kind: ResourceFlavor
metadata:
  name: a100-rdma
spec:
  nodeLabels:
    accelerator.example.com/class: a100-rdma
---
apiVersion: kueue.x-k8s.io/v1beta1
kind: ClusterQueue
metadata:
  name: research
spec:
  namespaceSelector: {}
  resourceGroups:
    - coveredResources: ["cpu", "memory", "nvidia.com/gpu"]
      flavors:
        - name: a100-rdma
          resources:
            - name: nvidia.com/gpu
              nominalQuota: 32
---
apiVersion: kueue.x-k8s.io/v1beta1
kind: LocalQueue
metadata:
  name: gpu
  namespace: team-a
spec:
  clusterQueue: research
```

Production configurations also need to specify the ratios of CPU, memory, and GPU, to avoid a workload getting GPUs but being unable to start due to insufficient CPU or memory quota.

## 6. Fairness Is Not FIFO

Strict FIFO can easily be blocked by one large unsatisfiable workload. Common strategies include:

- `StrictFIFO`: predictable ordering, but obvious head-of-line blocking;
- `BestEffortFIFO`: allows later satisfiable workloads to run first;
- Fair Sharing: adjusts admission order based on queue history or current resource share;
- Priority: gives production recovery, urgent training, or classroom assignments different levels;
- Aging: gradually increases weight the longer a workload waits, to avoid long-term starvation.

Kueue's Admission Fair Sharing considers the historical usage of LocalQueues and preferentially admits workloads from queues that have used less. Reference: [Admission Fair Sharing](https://kueue.sigs.k8s.io/docs/concepts/admission_fair_sharing/)

## 7. Preemption Needs an Explicit Contract

Preemption is not a free scheduling action; it can lose hours of training progress. The platform should specify:

- Which priorities can preempt which workloads;
- Whether workloads on borrowed quota are preemptible by default;
- How much time a workload has to save a Checkpoint after receiving a termination signal;
- Whether preemption frequency has an upper limit;
- Whether preempted workloads retain their age when re-queued;
- Whether online inference shares a preemption domain with training.

High priority should not be arbitrarily filled in by ordinary users; it should be granted through admission policies, dedicated queues, or controlled templates.

## 8. Gang and All-or-Nothing

A training workload that needs 8 Workers, if only 5 start, can neither train nor release resources. The platform must guarantee:

- Required Pods or PodSets are admitted simultaneously;
- GPUs are not consumed prematurely when any critical role cannot start;
- The cluster autoscaler sees the full demand;
- No orphaned Workers remain after failure;
- Minimum parallel scale and elastic scale are expressed separately.

Kueue, JobSet, Kubeflow Trainer, and KubeRay can be combined to express workload-level admission; Volcano provides Gang capability more within the scheduler itself.

## 9. Topology-Aware Admission

Multi-node training can still be slow even with the correct number of GPUs, because resources are scattered across different racks, network blocks, or availability zones. Topology policies should answer:

- Whether resources must be on the same host, rack, or network domain;
- Whether it is `Required` or `Preferred`;
- Whether different PodSets of the same workload need different topologies;
- The maximum time to wait for a compact topology;
- Whether the performance gain outweighs the waiting cost.

Kueue's `Topology` and `ResourceFlavor` can link quota admission to data center topology. Reference: [Kueue Concepts](https://kueue.sigs.k8s.io/docs/concepts/)

## 10. Namespace and RBAC Design

Recommended patterns:

- Each team has at least one namespace, with production and experimentation separated;
- Ordinary users can only use existing LocalQueues;
- ClusterQueue, ResourceFlavor, and priorities are maintained by platform administrators;
- The ServiceAccount that submits Jobs is separate from the identity that reads models/data;
- Platform controllers use least-privilege RBAC, and tenants cannot modify webhooks or CRDs;
- Cross-namespace access to Secrets, PVCs, and Services is explicitly designed.

Shared Jupyter environments require particular care: a user who can execute arbitrary code in a Notebook often effectively has the permissions of that Pod's ServiceAccount.

## 11. Whether Online Inference and Training Share a Pool

Sharing a pool improves utilization, but the following must hold:

- Online inference has reserved capacity or a non-lendable floor;
- Training scale-out does not exhaust the CPU, memory, and network needed by inference;
- Node maintenance does not simultaneously take down multiple inference replicas;
- Scheduling and cost systems can distinguish online, offline, and development usage;
- Replacement inference replicas can be warmed up before preemption.

Smaller platforms usually find it easier to operate with separate pools first; after achieving stable SLOs and observability, they can gradually move to workload colocation.

## 12. What to Monitor

| Object | Metric or Status |
| --- | --- |
| LocalQueue | Number of pending Workloads, wait time, historical usage |
| ClusterQueue | Nominal quota, borrowed, lent, reserved, actual occupancy |
| Workload | Pending reason, admission time, preemption count |
| Flavor | Available quantity per hardware pool, unschedulable nodes, scale-out latency |
| Tenant | GPU-hours, success rate, queueing P50/P95, preemption loss |

"Pending" must be decomposed into insufficient quota, unsatisfied topology, failed admission checks, and Pod scheduling failure; otherwise users only see a vague status.

## 13. Governance Checklist

- [ ] Every tenant has explicit nominal quota and borrowing rules;
- [ ] Priority creation and usage permissions are controlled;
- [ ] Multi-Pod workloads do not partially occupy GPUs;
- [ ] Checkpoints can be saved before preemption, and lost time is monitored;
- [ ] Flavors distinguish hardware, network, region, and price tiers;
- [ ] Capacity protection policies for training and online inference are explicit;
- [ ] Users can see queueing reasons and approximate wait status;
- [ ] Cost, quota, and actual GPU usage can be reconciled per tenant;
- [ ] Queue policy changes have audit and rollback mechanisms.

## Further Reading

- [Kueue Overview](https://kueue.sigs.k8s.io/docs/overview/)
- [Kueue Concepts](https://kueue.sigs.k8s.io/docs/concepts/)
- [Kueue Admission Fair Sharing](https://kueue.sigs.k8s.io/docs/concepts/admission_fair_sharing/)
- [Kubernetes Multi-tenancy](https://kubernetes.io/docs/concepts/security/multi-tenancy/)
