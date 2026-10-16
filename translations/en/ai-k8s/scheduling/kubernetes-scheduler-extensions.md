---
title: "Extending the Kubernetes Scheduler: From a GPU Placement Requirement to a Plugin"
description: "Using GPU node pool placement as an example, this explains the Scheduling Framework extension points, Profiles, the boundaries between Extender and standalone schedulers, and validation and rollback methods"
status: evolving
last_reviewed: 2026-10-11
---

# Extending the Kubernetes Scheduler: From a GPU Placement Requirement to a Plugin

Suppose the inference team has two classes of nodes: one class has high-speed networking and is suitable for cross-node inference; the other does not. When a Pod requests a GPU, the platform wants it to **must** land on a node with the corresponding network capability, while also packing scattered single-card tasks as much as possible, leaving complete nodes for multi-card training.

This sounds like "write a scheduling plugin." But the real question to answer first is: is high-speed networking a hard condition or a soft preference? Can existing node labels, affinity, and resource scoring express this? If extension is needed, where in the scheduler should the logic go?

This article discusses kube-scheduler scheduling extensions and does not conflate queue admission, node scaling, and device allocation. The strategies and configurations below are **design examples, not implemented cluster stress tests**; before going live, they must be validated against the target Kubernetes version and the actual GPU node topology.

## First Determine Which Layer the Problem Belongs To

| Requirement | Consider First | Do Not Mistakenly Assume |
| --- | --- | --- |
| Specify GPU node pool, high-speed network labels | `nodeSelector`, node affinity, Taint/Toleration | Writing a plugin is the only way to achieve "custom scheduling" |
| Pack or spread Pods as much as possible | Built-in `NodeResourcesFit`, topology spread constraints and their weights | Adjusting scores can change hard resource constraints |
| Decide which training Job enters the cluster first by queue quota | Workload admission such as Kueue | Pod Score can replace job-level quotas |
| A group of training Pods must reach a minimum count before proceeding | Gang/Coscheduling mechanisms | Giving a single Pod high priority guarantees the whole group starts |
| Select a specific GPU by device-level attributes | DRA Driver, Device Plugin, and node-side allocation capabilities | Selecting a node means a specific card is selected |
| Node placement requires custom state or algorithms | Scheduling Framework plugins | Calling an external service in Filter has no latency cost |

For example, when network capability is represented by reliable node labels, using **required node affinity** to constrain the available node pool is often simpler than maintaining a custom plugin that only checks labels. If the goal is to preserve complete eight-card nodes, you can first evaluate the bin packing strategy of `NodeResourcesFit` on a dedicated GPU node pool; it scores by requested versus allocatable amounts, does not know actual GPU utilization, and cannot guarantee NVLink/NUMA device combinations within the same node.

Note: the Pod's `schedulerName` determines which scheduler handles it; it does not by itself restrict the node pool. The queue controller, cluster autoscaler, and kubelet remain separately responsible for admission, provisioning, and final device usage.

## What Gates a Scheduling Cycle Passes Through

You can think of the scheduler as a front desk that finds a seat in the machine room for a Pod. First decide who enters the queue, then filter out seats that do not satisfy hard conditions, and sort the remaining seats; after selection, first record it in the local ledger, complete the necessary confirmation, and then actually perform the binding.

```text
Pod 入队 → QueueSort
             ↓
PreFilter → Filter → PostFilter（没有可用节点时）
             ↓
PreScore → Score → NormalizeScore → 选定节点
             ↓
Reserve → Permit → PreBind → Bind → PostBind
             ↘ 失败时按阶段回滚 / Unreserve
```

The diagram above omits extension points such as PreEnqueue, and it does not mean every cycle reaches PostFilter: it is only invoked when no feasible node is found. In the scheduling framework, the **scheduling cycle executes serially, while the binding cycle allows concurrency**; node-level filtering and scoring can also run in parallel. Therefore, if a plugin performs expensive remote queries in per-node Filter, it will directly slow down decision-making as the number of candidate nodes and pending Pods grows.

Several extension points are most commonly misused:

- **PreFilter / Filter**: the former prepares shared inputs for this Pod; the latter determines whether a node satisfies hard conditions. If placement is definitely not possible, return an unschedulable status in Filter; do not disguise a hard constraint with an extremely low Score.
- **PreScore / Score**: establish preferences for nodes that are already feasible. Scoring can only affect priority; it cannot make a node excluded by Filter become usable again.
- **Reserve / Unreserve**: record the plugin's own temporary reservation before actual binding; subsequent failures must be undoable. The scheduler's local assumed cache and the plugin's custom resource ledger are not the same thing.
- **Permit**: allow binding, deny binding, or wait for external conditions. Waiting has timeouts and deny/cancel paths; it is not a lock that holds resources forever. When using it to implement Gang, you must also handle in-group failures, timeouts, rollback, and controller state.
- **PreBind / Bind / PostBind**: pre-binding validation, executing the binding, and post-binding notification have different responsibilities. To customize Bind, you must clearly define the enablement and fallback relationship with the default binding plugin; two components must not both assume the other completed the binding.

An example: the platform has an independent network capacity controller. Labels can only indicate "this node is connected to high-speed networking," not "whether there is currently bandwidth available for new Pods." A plugin can parse Pod requirements in PreFilter, use a synchronized read-only capacity snapshot in Filter to exclude ineligible nodes, and prefer more suitable nodes in Score. If cross-Pod exclusive use of a finite network slot is also required, Reserve and Unreserve must maintain the same revocable reservation state. **You cannot just look at capacity in Filter and not handle concurrent changes before binding.**

There is also a consistency boundary here: the informer cache is not a linearly consistent global lock. Multiple independent scheduler processes also do not share the assumed cache. If network slots must be strictly mutually exclusive, the final allocating party needs atomic validation or an explicit conflict retry mechanism; node filtering alone cannot provide strong guarantees.

## Extension Approaches Are Not All the Same "Plugin"

| Approach | Runtime Location and Characteristics | Suitable Scenarios | Main Costs |
| --- | --- | --- | --- |
| Built-in configuration and Pod constraints | Reuses existing kube-scheduler plugins | Labels, affinity, topology spread, resource bin packing | Cannot express proprietary external state |
| Scheduling Framework plugins | Compiled into the scheduler process, invoked through extension points | Custom filtering, scoring, reservation, or permit needed | Maintaining custom images, version upgrades, and crash isolation |
| Scheduler Extender | Scheduler delegates part of filtering/scoring/binding through an external HTTP interface | Existing external decision service and acceptable call overhead | Network round trips, timeouts, failure degradation, and compatibility |
| Multiple Profiles | One scheduler process shares the queue and cache; different `schedulerName` use different policies | Distinguishing online and batch Pods within the same process | Not independent scheduling throughput; queue policies have shared constraints |
| Standalone scheduler | Separate process, cache, and leader election configuration | Strong isolation or independently evolving workloads | More Watches, resource contention, and operational costs |

**A Profile is not a second scheduler replica.** Multiple Profiles can use different plugin configurations, but they share the same process queue; when configuring multiple Profiles, the `QueueSort` plugin and its configuration for all Profiles must be identical. When multiple replicas share the same leader election group, only the Leader performs scheduling; deploying more standby replicas does not increase single-process throughput.

An Extender is an external HTTP extension interface and is not equivalent to a framework plugin. Even if existing policies can be reused through an external service, you should first calculate the network and failure costs of each scheduling cycle, and clearly define whether to reject, retry, or degrade within a risk scope when timeouts or unreachability occur. For hard constraints such as security isolation or device topology, you cannot default to "allow on external service timeout."

## Validate the Policy with Profiles First; Do Not Replace the Default Scheduler Wholesale

If the requirement is only "network node pool + GPU bin packing," the first round does not need to write Go plugins. The Pod expresses the network hard condition with required node affinity, and the Profile used by that workload is configured with node resource scoring. For example:

```yaml
# 仅展示 Profile 片段：应并入目标集群现有的 KubeSchedulerConfiguration。
profiles:
  - schedulerName: gpu-packing-scheduler
    pluginConfig:
      - name: NodeResourcesFit
        args:
          scoringStrategy:
            type: MostAllocated
            resources:
              - name: cpu
                weight: 1
              - name: memory
                weight: 1
              - name: nvidia.com/gpu
                weight: 4
```

```yaml
# 仅展示 Pod spec 片段；标签值由平台维护，不能由租户任意自报。
spec:
  schedulerName: gpu-packing-scheduler
  affinity:
    nodeAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        nodeSelectorTerms:
          - matchExpressions:
              - key: infra.example.com/high-speed-network
                operator: In
                values: ["true"]
  containers:
    - name: inference
      image: example.invalid/inference:replace-me
      resources:
        limits:
          nvidia.com/gpu: 1
```

`MostAllocated` will prefer nodes with more already-allocated resources among feasible nodes; the example weight **4 is not a recommended production value**. Actual placement is still affected by other Score plugins, request sizes, and the feasible node set, and "four cards remaining on the node" does not mean there are contiguous devices satisfying the specified NUMA/NVLink domain. The example image is a placeholder, not a runnable deployment manifest.

The "ignored" in `requiredDuringSchedulingIgnoredDuringExecution` means that node label changes after the Pod is running will not automatically evict it solely because of this rule; this also reminds us that passing scheduling does not mean the network and devices remain healthy during runtime. The Profile name must match the Pod's `schedulerName`, and other Profiles and plugin configurations should remain unchanged; do not overwrite existing production configuration with the fragment above.

If built-in policies truly cannot express network capacity state, only then begin implementing Framework plugins: clearly define which data each extension point reads, when state expires, how failures are rejected or retried, and how version matching is maintained during upgrades. Plugins are linked with kube-scheduler and typically require building a corresponding binary image for the target Kubernetes version, rather than hot-loading an arbitrary version of `.so` into a running process.

## Before Going Live, Also Run Through the Failure Paths

Testing is not just about "Pod eventually Running." At minimum, construct the following scenarios and verify the actual `spec.nodeName`, events, and application readiness results:

1. **Hard condition validation**: when only GPU nodes without network labels are idle, the Pod should remain unschedulable rather than falling back to the wrong node to improve success rate.
2. **Capacity and fragmentation**: when one-card, four-card, and eight-card jobs arrive mixed, check the remaining count of complete eight-card nodes, training job wait times, and actual device topology; do not just look at bin packing scores.
3. **Cache changes**: after node labels change, devices go offline, or Pods are deleted, the plugin should promptly retry Pods that may have become schedulable; event wake-ups and failure reasons must also correspond.
4. **Concurrency and rollback**: after Reserve, simulate Permit timeout, PreBind failure, or binding failure, and confirm that Unreserve does not leak custom slots; test conflict handling when multiple instances or multiple schedulers share a pool.
5. **Dependency failures**: when the network controller or Extender times out, or the API Server slows down, clarify which jobs wait and which can safely degrade, and do not let Pods that do not satisfy hard conditions slip through silently.
6. **Policy isolation**: switching `schedulerName` only affects the canary workload; the original default scheduler, node affinity, Taints, and resource pool boundaries must still work as expected.

Observability must also distinguish measurement scopes: `scheduler_pending_pods` looks at queue composition, `scheduler_schedule_attempts_total` looks at success and retries by result, and `scheduler_framework_extension_point_duration_seconds` looks at phase latency; the availability and labels of plugin-level execution time metrics should follow the target version's `/metrics`. The wait from Pod creation to binding and the startup time from binding to Ready must also be recorded separately. A single successful scheduling cannot be treated as the overall successful startup of a training job.

The rollback plan should be determined before traffic switching: keep the original Profile/original scheduler available, first stop new Pods from pointing to the new `schedulerName`, handle old Pods that are not yet bound, and then roll back the plugin image or configuration. **Already-bound Pods will not automatically migrate because the scheduler is switched**; if the new scheduler stops, Pending Pods still pointing to it will not automatically be taken over by the default scheduler either. After modifying the Pod template, verify how existing Pending Pods are handled to avoid leaving a batch of unscheduled workloads.

The goal of scheduler extension is not to cram all decisions into one plugin, but to place **hard constraints, soft preferences, job admission, and device allocation** in the layers each can be responsible for. Only after proving that built-in capabilities are insufficient, and then designing consistency, failure, and rollback for the newly added state, can a scheduling policy move from "selecting a node" to "making the entire group of workloads run reliably."

References:

Kubernetes Scheduling Framework: https://kubernetes.io/docs/concepts/scheduling-eviction/scheduling-framework/

Kubernetes Scheduler Configuration: https://kubernetes.io/docs/reference/scheduling/config/

Kubernetes Scheduler Configuration API: https://kubernetes.io/docs/reference/config-api/kube-scheduler-config.v1/

Kubernetes Resource Bin Packing: https://kubernetes.io/docs/concepts/scheduling-eviction/resource-bin-packing/

Kubernetes Dynamic Resource Allocation: https://kubernetes.io/docs/concepts/scheduling-eviction/dynamic-resource-allocation/

Running Multiple Schedulers in Kubernetes: https://kubernetes.io/docs/tasks/extend-kubernetes/configure-multiple-schedulers/

Further reading: [Large-Scale Kubernetes Scheduler Optimization](../practices/large-scale-kubernetes-scheduler-optimization.md), [GPU and Heterogeneous Resource Scheduling](../gpu-scheduling.md).
