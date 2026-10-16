---
title: "Volcano has many features, so why is it still hard to tune in enterprises?"
description: "Discussing the business prerequisites for Volcano scheduling and rescheduling adoption, from resource views, task grading, cross-department preemption consensus, and pre-deployment instrumentation"
status: evolving
last_reviewed: 2026-10-11
---

# Volcano has many features, so why is it still hard to tune in enterprises?

Imagine an enterprise putting training, inference, and offline workloads into the same GPU cluster. The platform team is drawn to Volcano's Gang, Queue, fair sharing, preemption, and reclamation: they want eight workers to no longer run only two, idle GPUs to be lendable to other departments, and resources to be recoverable when high-priority tasks arrive. The feature list looks like it hits the pain points squarely.

Before actual rollout, however, the business asks several harder questions: who do these H20s actually belong to, and which portion can be lent out? Between online inference scaling and a training job that is currently running, whose priority is higher? If department B borrows cards from department A, and A needs them back, which class of B's tasks may be interrupted, how much notice is given in advance, and who bears the loss of training progress?

Without answers to these questions, even if the scheduler correctly executes preemption, the business may still classify it as an incident. **Volcano can enforce resource rules; it cannot decide for the enterprise which rules are fair, acceptable, and recoverable.** That is the adoption threshold this article discusses, not just how to configure some plugin.

The departments and task scenarios below are used to explain design trade-offs; they are not production incidents that occurred, and no throughput or utilization gains are fabricated. Configuration checks involving Volcano behavior are based on the **v1.15.3** release tag; actual effects still need to be validated against the target cluster's workloads and configuration.

## Before the feature list, draw a map of the business and resources

Volcano's capabilities are real: PodGroup and Gang can prevent multi-Pod jobs from starting only partially, Queue can carry resource sharing policies, and scheduling actions and plugins can combine priority, backfill, reclamation, and other mechanisms. The [Volcano scheduling configuration documentation](https://github.com/volcano-sh/volcano/blob/v1.15.3/docs/user-guide/how_to_configure_scheduler.md) describes how actions, tiers, and plugins work together. But the input to these mechanisms cannot just be "how many GPUs we have in total."

A resource view that can support decision-making needs to distinguish at least the following:

| Facts that need to be known | What happens when unclear | Who provides or maintains |
| --- | --- | --- |
| GPU model, UUID, MIG/full-card status, failure and maintenance status | Mistaking sufficient quantity for guaranteed task execution | Hardware, node, and device management teams |
| CPU, memory, RDMA, NUMA, rack, storage, and image reachability | Job lands on a node with GPUs, but the application fails to start or runs slowly | Platform and infrastructure teams |
| Allocatable amount per resource pool, department guarantee, borrowed amount, hard cap | "Idle and lendable" and "this department needs it at any time" both hold at once | Capacity owners and department Owners |
| Pod/Job → Queue → department/cost center → business service ownership | Can see cards are occupied, but cannot explain who is using them or why | Submission platform, business systems, and FinOps |
| Task minimum resources, latest start time, runtime duration, and recovery capability | Cannot judge which of waiting, backfill, or reclamation costs less | Business and training/inference owners |

The "view" here is not a demand to build another omnipotent CMDB. The minimal viable approach is to link node and device inventory, Queue/Job ownership, resource requests, and actual usage with stable IDs, and to record data update and expiration times. `nvidia.com/gpu: 4` only represents integer resource requests; it does not automatically indicate which four cards they are or whether they are in the same NUMA domain. The Volcano community's [GPU NUMA Issue #4998](https://github.com/volcano-sh/volcano/issues/4998) discusses exactly this kind of boundary for standard full-card GPUs within node topology; see [four-card tasks and GPU fragmentation](gpu-topology-fragmentation-scheduling.md) for details.

More importantly, the resource view must be **understandable to the business side as well**: has a Queue been waiting because GPU quantity is insufficient, because the specified model is insufficient, or because this department's quota is exhausted? These three causes lead to different scaling, borrowing, and budgeting decisions. Without explainable inventory and ownership, the more plugins there are, the harder disputes become to untangle.

## Priority is not an integer, but a business commitment

A common first step is to label tasks as "online / training / development" and set online tasks to the highest priority. Such classification helps, but it is still not enough to directly enable preemption: does the online service already have sufficient redundancy? Does production training also have delivery deadlines? Can a small urgent experiment interrupt a job that has been running for six hours and has not yet saved a checkpoint?

It is recommended that business, platform, and capacity owners jointly define a decision table, rather than letting each submitter fill in `PriorityClass` on their own:

| Example task category | How long it may wait | Whether it can be interrupted | Recovery prerequisite | Requirements for borrowed resources |
| --- | --- | --- | --- | --- |
| Online inference with a clear SLO | Derived backward from the service SLO | Usually must maintain available replicas and a capacity floor | Replicas can migrate, traffic can be drained | Must not rely on cards that can be reclaimed at any time as the only capacity |
| Distributed training with a delivery deadline | Based on delivery time and full-group startup time | After business confirmation, may be interruptible during certain windows | Checkpoint is usable and recovery has been validated | Minimum full-group resources must be obtainable |
| Offline/development tasks without a clear deadline | Can tolerate longer waits | Can serve as candidates for borrowing and reclamation | Data and intermediate state can be rebuilt | Marked as borrowed capacity with possible interruption shown |

This is a discussion template, **not a recommendation that all enterprises preempt in this order**. Ultimately, "urgent" must be defined as a service level with approval, validity period, budget, and audit records, to prevent every department from marking all its tasks as highest priority. Different departments also need to agree on: the borrowable ratio, recall conditions, notification window, weekday vs. non-workday rules, compensation or cost attribution, and who has the authority to pause automatic reclamation during incidents.

Volcano can perform Queue ordering, preemption, and reclamation based on configuration and object state, but it cannot use `priority: 1000` alone to determine whether this task commitment has received business approval. **A technically legal eviction is not the same as an organizationally reasonable eviction.**

## Borrowing cards and rescheduling: discuss interruption losses first, then utilization

Suppose department A's GPUs are temporarily idle, and department B's training borrows them to run. When A's demand returns, the platform has the ability to reclaim the cards. The capacity dashboard may look great, but for B, the real cost of one eviction is: progress already trained but not yet persisted, checkpoint write time, re-queueing, image and data reloading, distributed communication re-establishment, and whether recovery still lands within the effective delivery window.

Therefore, "supporting reclamation" must be decomposed into a mutually agreed contract:

1. **Which cards can be borrowed?** What are the guaranteed amount, the lendable surplus, the untouchable online safety floor, and the maintenance reservation?
2. **Which tasks can be borrowed?** Are only recoverable batch tasks allowed into reclaimable capacity? Can long training borrow within specified time windows?
3. **When must they be returned?** What level of demand from the original department triggers reclamation, how much notice is given in advance, and what is the maximum grace period for waiting on a checkpoint?
4. **What if they cannot be returned?** When checkpoint fails, storage is unavailable, or the evicted task cannot recover, who handles it, and is automatic reclamation disabled?
5. **How are gains accounted?** Beyond GPU-hours, effective training time, recomputation losses, and SLO violations must also be compared; cluster utilization alone cannot prove a policy is successful.

In the Volcano v1.15.3 Helm default configuration, the actions are `enqueue, allocate, backfill`, and the plugins include `proportion`, but **the `reclaim` or `preempt` actions are not enabled by default**. See [default scheduling configuration](https://github.com/volcano-sh/volcano/blob/v1.15.3/installer/helm/chart/volcano/config/volcano-scheduler.conf). The official [Capacity plugin guide](https://github.com/volcano-sh/volcano/blob/v1.15.3/docs/user-guide/how_to_use_capacity_plugin.md) requires using `capacity` to replace the conflicting `proportion` and enabling `reclaim` before quota borrowing and returning can be demonstrated per that guide; the interaction between `enqueue` and reclamation/preemption also needs item-by-item validation. See [v1.15 Actions documentation](https://github.com/volcano-sh/website/blob/master/versioned_docs/version-v1.15.0/Scheduler/Actions.md).

This is not "append `reclaim` to a string and the product requirement is done." Even if the technical rules are in effect, if the business has not defined reclaimable tasks, grace periods, and recovery responsibilities, the more efficient the reclamation, the more frequent the business conflicts it may create.

## For advanced features to run smoothly, instrumentation must be in place before rollout

Many teams discover only after the scheduling policy goes live that their dashboards can only show Pod Pending and GPU utilization; by the time they ask "who preempted whom, why, and what was lost," the necessary correlated data is missing. Scheduling, rescheduling, and heterogeneous resource scheduling should share one auditable decision chain:

```text
业务请求与 Owner → 任务类别 / SLO / 可中断性 → Queue / 配额 / 优先级
        → 调度与设备分配 → 运行状态 → 回收/重启 → 业务结果
```

At minimum, unify workload ID, department/cost center, resource type and model, task minimum member count, deadline or SLO, checkpoint capability, and recovery entry point at the submission entry (without recording sensitive data paths). At the scheduling stage, record enqueue, rejection, node selection, PodGroup status, and the trigger and affected parties of preemption/reclamation; at the runtime stage, correlate GPU UUID, actual usage, and full-group Ready time; at the recovery stage, record checkpoint success rate, recovery duration, and the effective compute that had to be recomputed. **Metering does not mean stuffing every business field into Prometheus labels**: use low-cardinality labels for queues and resource pools, and route per-job IDs, operators, and approval reasons into structured events or audit logs.

Volcano v1.15.3's source code provides metrics such as `volcano_schedule_attempts_total{result}`, action/plugin durations, and Queue scalar resource allocation: [scheduler metrics definitions](https://github.com/volcano-sh/volcano/blob/v1.15.3/pkg/scheduler/metrics/metrics.go), [Queue metrics definitions](https://github.com/volcano-sh/volcano/blob/v1.15.3/pkg/scheduler/metrics/queue.go). These metrics can explain scheduler workload, but they cannot by themselves answer the business question "how long from submission to actual training start," let alone compute the effective training time lost to checkpoint failures. The target cluster must still be checked against real `/metrics` for exposure and label conventions.

Likewise, heterogeneous resources are not done by simply adding a model name to a Queue: GPU model, MIG/full-card, RDMA, and NUMA capabilities need a consistent inventory and demand expression, and the actual device allocation after a Pod is placed on a node should also be written back to the observability chain. When there is a hard constraint requiring the same GPU topology domain, it must also be verified whether the device allocation component can strictly satisfy it; cross-node topology policies must not be mistaken for in-node GPU allocation guarantees.

## Difficult troubleshooting is sometimes because the policy was never defined

When a task is Pending, technical troubleshooting needs to check, in order: `schedulerName`, the Job/PodGroup minimum members and status, Queue quota and status, the scheduler's active actions/plugins, node and device inventory, PVC and taint constraints, and then the scheduler logs, events, and autoscaler behavior. The official [PodGroup condition reason design](https://github.com/volcano-sh/volcano/blob/v1.15.3/docs/design/podgroup-condition-reason.md) specifically distinguishes not-enqueued from scheduling failure; both look like "did not run" on the surface, but the responsibility and resolution differ.

The v1.15.3 [scheduler configuration guide](https://github.com/volcano-sh/volcano/blob/v1.15.3/docs/user-guide/how_to_configure_scheduler.md) also explains that the order of actions and the judgment functions registered by plugins in a tier affect the result, and one rejection judgment can cause subsequent plugins to stop executing. This is the cost of composability; you cannot just look at one Pod Event and conclude "Volcano does not work."

But the other half of troubleshooting is not in the logs: if no one has defined in advance the waiting cap, who can borrow cards, whether preemption is permitted, and how applications recover, then **figuring out "which policy blocked it" is still not enough to judge "whether this policy should exist at all."** The platform needs to place business rule versions, approval records, and effective configuration on the same timeline as scheduling events; otherwise teams end up arguing about algorithms when what they are actually arguing about is the organization's resource contract.

## What platform leads should deliver first, and what to enable later

A pragmatic rollout order is:

1. **Take stock of resources and the business profile.** Build a resource view queryable by model, topology, health, and department ownership; measure queue waits, job lengths, and online load peaks without first assuming everyone is a good fit for preemption.
2. **Sign off on priority and borrow/return rules.** Confirm guaranteed amounts, borrowing caps, protected workloads, notification/grace periods, and incident arbitration with business departments. Without cross-department consensus, start with visualization and manually approved borrowing rather than enabling automatic eviction directly.
3. **Make recoverability an admission condition.** Long tasks without validated checkpoints should not be placed into preemptable queues first; validate save, restart, model/data state recovery, and worst-case loss separately for each framework.
4. **Instrument first, optimize later.** Preserve the timeline from submission → enqueue → full-group running → completion, and from reclamation → re-enqueue → recovery; measure results by business completion time, effective GPU-hours, SLO, and losses.
5. **Enable capabilities at small scope.** First use Gang for tasks that genuinely require full-group resources, then pilot borrowing/returning between two departments that have reached consensus; choose Proportion or Capacity, reclamation actions, and heterogeneous device solutions based on real demand, rather than switching the entire "advanced plugin" suite on for the whole company at once.
6. **Rehearse undesirable outcomes.** Seven members have resources but the eighth does not, borrowed cards suddenly need to be returned, the specified model is out of stock, checkpoint fails, scheduler or device plugin upgrades; accept correct waiting, correct alerting, and recoverability, not just Pods eventually Running.

Teams that are primarily concerned with job admission and quotas, and want to keep using the existing kube-scheduler, can compare Kueue; for large numbers of batch tasks and multi-Pod jobs where unified Gang and scheduling policies are genuinely needed, Volcano may still be a suitable core component. This is not a replacement list, and it certainly does not mean that switching components lets you skip business governance. The [Kueue vs. Volcano comparison experiment design](kueue-vs-volcano.md) only provides test dimensions, not a measured ranking of merits. Platforms that already run Volcano also do not need to hastily replace the entire scheduling system because of one GPU topology gap; they can add device-level allocation and observability chains after clarifying object ownership.

**The mistake platform leads most easily make is treating the scheduler's advanced features as a substitute for business design.** Volcano can make Queue, Gang, backfill, and reclamation more controllable; but resource ownership, priority consensus, interruption costs, and device facts must be defined by the enterprise itself, and formed into a verifiable data chain in advance. If the lead time is spent there, the subsequent scheduling, rescheduling, and heterogeneous resource management will have a real chance of running smoothly.

References:

Volcano v1.15.3 default scheduling configuration: https://github.com/volcano-sh/volcano/blob/v1.15.3/installer/helm/chart/volcano/config/volcano-scheduler.conf

Volcano Scheduler configuration guide: https://github.com/volcano-sh/volcano/blob/v1.15.3/docs/user-guide/how_to_configure_scheduler.md

Volcano Capacity plugin usage guide: https://github.com/volcano-sh/volcano/blob/v1.15.3/docs/user-guide/how_to_use_capacity_plugin.md

Volcano Scheduling Gates Queue Admission: https://github.com/volcano-sh/volcano/blob/v1.15.3/docs/user-guide/how_to_use_scheduling_gates_queue_admission.md

Kubernetes Pod Priority and preemption: https://kubernetes.io/docs/concepts/scheduling-eviction/pod-priority-preemption/

Further reading: [GPU resource bank and tidal inference platform practice blueprint](gpu-resource-bank-tidal-platform.md), [GPU and heterogeneous resource scheduling](../gpu-scheduling.md).
