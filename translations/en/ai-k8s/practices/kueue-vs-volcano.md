---
title: "Kueue vs. Volcano Comparison Experiment"
description: "Validate admission queues, Gang, fair sharing, preemption, and topology capabilities with identical training workloads"
status: lab
last_reviewed: 2026-08-04
---

# Kueue vs. Volcano Comparison Experiment

Kueue and Volcano are not simple substitutes for one another. Kueue emphasizes workload admission and composition with existing schedulers; Volcano provides a batch-oriented scheduler, Job, Queue, PodGroup, and multiple scheduling policies. Experiments should be designed around the control points required by the platform.

## 1. Identical Test Set

Prepare the following workloads:

1. Short single-Pod, single-GPU tasks;
2. 8-Pod Gang training;
3. Multi-GPU tasks requiring same-node or same-rack topology;
4. Mixed high- and low-priority workloads;
5. Two tenants borrowing and reclaiming quotas;
6. One oversized workload that cannot be satisfied;
7. GPU nodes added while workloads are waiting.

## 2. Observation Dimensions

| Dimension | Question |
| --- | --- |
| Admission | Does waiting occur before or after Pod creation? |
| Gang | Do incomplete resource groups occupy partial GPUs? |
| Fairness | How do long/short tasks, tenants, and priorities share resources? |
| Preemption | Who gets preempted, how much is lost, and can recovery occur? |
| Topology | Do queue decisions understand node/rack/device domains? |
| Elasticity | How do Pending/Admitted states drive node provisioning? |
| Ecosystem | How do Trainer, JobSet, RayJob, etc. integrate? |
| Operations | Are status, events, metrics, and upgrades clear? |

## 3. Result Recording

Record submission-to-admission, admission-to-Running, completion time, GPU fragmentation, idle time, preemption loss, queue fairness deviation, and recovery after controller failure. Do not merely compare YAML length.

## 4. Combined Scenarios

Some platforms use Kueue for quota admission and then rely on kube-scheduler or other schedulers for Pod placement; other platforms use Volcano independently for batch scheduling. If combining the two, ownership of PodGroup, Suspend, Priority, and preemption must be validated—two controllers must not admit or recover the same workload redundantly.

Further reading: [GPU Scheduling](../gpu-scheduling.md), [Queues and Multi-Tenancy](../queue-multitenancy.md)
