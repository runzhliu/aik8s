---
title: "Eight GPUs free, yet the inference Pod waits: Five Volcano scheduling experiments"
description: "Two eight-device workers reveal how GPU placement, node-group caps, gang eviction, failure domains and DRA device selection determine which Pods can run."
status: tested
last_reviewed: 2026-11-23
applicable_versions: "Volcano v1.16.0, Fake GPU Operator 0.2.1"
tested_environment: "Kubernetes v1.37.2, 2 workers × 8 simulated B300 GPUs"
---

# Eight GPUs free, yet the inference Pod waits: Five Volcano scheduling experiments

Each worker had four free GPUs. The cluster had eight available, but the eight-GPU inference Pod never bound to a node. Moving the same two background allocations onto the first worker left the total unchanged and the inference Pod started on the second worker. For capacity planning, the useful question is whether the next workload can fit in the space that is actually available.

We tested five questions in the same cluster: where small jobs land, how much training can borrow from serving, which workloads give way under contention, whether replicas of the same model can share a failure domain, and how to claim and verify one specific device. The earlier lab covered queue admission, historical fairness and cache wakeups. Here we follow the individual Pods through binding and eviction. [Previous lab](volcano-116-gpu-scheduling.md)

## How to read the results

Kubernetes v1.37.2, Volcano v1.16.0 and Fake GPU Operator 0.2.1. Each of the two workers advertised eight simulated B300s. The same container image requested whole GPUs and slept after startup. Explicit PodGroups and bare Pods let us track original victims without a controller replacing them. A and B are worker aliases in the screenshots. Running is the observed Pod phase and unbound means no node has been assigned. This measures placement, container startup and eviction. Time to first token, training recovery time and NCCL bandwidth require real workloads.

![Workers A and B each advertise eight simulated B300s. In experiment five, A additionally advertises two independent 80 GiB DRA devices.](../../assets/practices/volcano-gpu-placement/design-overview.svg)

*The same two workers host all five tests. The fifth follows the separate DRA device inventory.*

The reproducibility bundle includes step-by-step commands, workload manifests and the complete scheduler configuration for each round. Eviction actions change scheduler behavior cluster-wide, so use a dedicated idle test cluster. Between rounds we removed experimental Pods and PodGroups and changed one condition. Each challenger arrived only after the initial workload was Running. [Download the lab](../../assets/practices/volcano-gpu-placement/lab.zip) · [Download the anonymized observations](../../assets/practices/volcano-gpu-placement/results.txt) · [Volcano v1.16.0 release](https://github.com/volcano-sh/volcano/releases/tag/v1.16.0)

## 1. Eight free devices or one free eight-device worker?

We started two background Pods requesting four GPUs apiece. A node selector placed one on each worker in round one and both on A in round two. We then submitted the same single Pod requesting eight `nvidia.com/gpu` devices. Both rounds started with 16 devices and the background workload used eight.

![The same eight-GPU Pod arrives after two background Pods use four devices on each node or all eight on A. Open squares are GPUs free before arrival.](../../assets/practices/volcano-gpu-placement/design-packing.svg)

*Each square represents one GPU. Read each row just before the eight-device Pod arrives.*

| Background use A / B | Free on A / B | Eight-GPU Pod |
| --- | --- | --- |
| 4 / 4 | 4 / 4 | Unbound throughout the 14-second observation |
| 8 / 0 | 0 / 8 | Bound to B and reached Running |

![Terminal observations for pinned and unpinned placement, with running Pod counts on A and B](../../assets/practices/volcano-gpu-placement/packing.png)

Node filtering tests whether one worker can fit the entire Pod. If every worker has fewer than eight available devices there is nothing left to score. We then removed the pins and submitted eight independent single-device Pods one at a time. With the default configuration and with an explicit GPU scoring weight, all eight landed on A and the large Pod started on B. Default binpack scores CPU and memory, and other scoring plugins were active. The pinned experiment shows the cost of fragmentation. The unpinned comparison found no incremental benefit from the added weight in this run. [v1.16.0 binpack implementation](https://github.com/volcano-sh/volcano/blob/v1.16.0/pkg/scheduler/plugins/binpack/binpack.go)

```yaml
- name: binpack
  arguments:
    binpack.resources: nvidia.com/gpu
    binpack.resources.nvidia.com/gpu: 10
```

A serving platform can track both total free GPUs and the number of nodes that can accept an eight-device Pod. The first metric reads eight in both rounds. The second changes from zero to one. A service that supports cross-node tensor parallelism needs a distributed deployment and network validation of its own. The scheduler cannot split the original Pod specification.

## 2. Cap training at two borrowed serving GPUs

We labeled A as training and B as serving. One training queue could use both groups, with a two-GPU limit on the serving group. A single eight-device Pod filled A, then three single-device Pods arrived from the same queue. The first two ran on B. The third remained unbound while B still had six free GPUs. Changing only the annotation from two to three let that same waiting Pod start on B. [Node-group limit configuration](https://github.com/volcano-sh/volcano/blob/v1.16.0/docs/user-guide/how_to_use_nodegroup_plugin.md)

![A stays full and the first two borrowers stay on B. Only the serving cap changes from two to three while the same Pod waits.](../../assets/practices/volcano-gpu-placement/design-borrow.svg)

*The green square is the device that the third Pod obtained after the cap increased.*

```sh
kubectl annotate queue v116-lab-burst \
  'volcano.sh/nodegroup-resource-limits={"v116-lab-serve":{"nvidia.com/gpu":"3"}}' \
  --overwrite
```

![The same borrowing Pod is unbound at a cap of two and running on B at three](../../assets/practices/volcano-gpu-placement/borrow.png)

This answers how much of the serving pool one training queue may occupy. Other queues eligible for B follow their own policies. Even a single borrowed device prevents an eight-device serving Pod from starting immediately on that worker. Size whole-node reserves and borrowing caps against the actual serving replica footprint and startup latency budget.

## 3. Under pressure, evict one process or a whole group?

This case exposed the clearest policy difference. Each of two low-priority jobs had two four-device Pods and needed both members. Together they filled all 16 GPUs. A new high-priority four-device Pod needed just one incumbent's slot. We rebuilt the same workload for each round, kept the incumbents eligible for eviction, and changed the preemption action or its whole-group setting.

![Two original groups each contain two four-device Pods. Three policies evicted one, two and zero incumbents when the same challenger arrived.](../../assets/practices/volcano-gpu-placement/design-eviction.svg)

*Read across to count surviving members in each group. Read down to compare the policies.*

| Within-queue policy | Running incumbents per original group (two each initially) | Incoming Pod | Distinct incumbents with eviction events |
| --- | --- | --- | --- |
| Classic preemption | 1, 2 | Running | 1 |
| Gang-aware, whole-group eviction enabled | 2, 0 | Running | 2 |
| Gang-aware, whole-group eviction disabled | 2, 2 | Unbound | 0 |

![Surviving original Pods, distinct eviction targets and event messages from three actions](../../assets/practices/volcano-gpu-placement/eviction.png)

Classic preemption left a lone member Running. An application requiring all ranks to synchronize could still occupy four GPUs with that member. We ran no training process, so the test cannot convert that loss into training time. Whole-group eviction retired a complete pair, admitted the four-device arrival and left four devices available for other work. Disabling whole-group eviction kept both pairs intact and the arrival waiting. Counting evicted Pods alone misses the cost of a surviving rank that cannot make progress. [Gang preemption implementation](https://github.com/volcano-sh/volcano/blob/v1.16.0/pkg/scheduler/actions/gangpreempt/gangpreempt.go)

```yaml
configurations:
- name: gangpreempt
  arguments:
    allowWholeBundle: false
```

Three controls helped interpret this. We counted distinct original Pod UIDs and checked surviving Pods against Evict events. We used the plugin tiers from the upstream v1.16.0 tests, including capacity in tier one, and enabled only the eviction action under test in each round. [Upstream preemption and reclaim tests](https://github.com/volcano-sh/volcano/blob/v1.16.0/test/e2e/gangevict/gangevict.go)

- **Surplus in the incumbent group.** Four four-device Pods needed only two members. A higher-priority group in the same queue requested two four-device Pods. Classic and gang-aware preemption each evicted two incumbents, preserved two and admitted both arrivals.
- **A challenger larger than the cluster.** Five four-device Pods needed 20 GPUs in a single gang. In the 16-second observation for each action, neither evicted a Pod and all five arrivals remained unbound.
- **Cross-queue reclaim.** Two queues each deserved eight devices. One used all 16 first. The other submitted two four-device Pods at equal priority. With gangreclaim, the borrower went from four members to two, both arriving Pods ran, and both victim events named gangreclaim. This case exercised queue entitlement. The earlier borrowing cap governs admission on a particular node group.

## 4. Can two domains host three two-Pod replicas?

Two leaf HyperNodes represented logical racks containing A and B, under one parent. Each inference replica was modeled as a PodGroup containing two one-device Pods that had to stay in one rack. A selector matched the PodGroup labels of the service. We submitted three groups in order. The third needed only two GPUs and 12 were still free after the first two groups started. The only policy difference was the strength of anti-affinity between groups. [PodGroup anti-affinity guide](https://github.com/volcano-sh/volcano/blob/v1.16.0/docs/user-guide/how_to_use_podgroup_anti_affinity.md)

![The required rule leaves the third group waiting while the first two occupy different racks. With the preferred rule, groups one and three share A.](../../assets/practices/volcano-gpu-placement/design-domains.svg)

*Each group inside a rack contains two one-GPU Pods. Only the rule between groups changes.*

```yaml
spec:
  minMember: 2
  networkTopology:
    mode: hard
    highestTierName: rack
  topologyAffinity:
    podGroupAntiAffinity:
      required:
      - podGroupSelector:
          matchLabels:
            workload: placement-demo
        topologyTierName: rack
```

![Two pending members under the hard rule and both members of the third group on A under the soft rule](../../assets/practices/volcano-gpu-placement/domains.png)

With required anti-affinity the first two groups occupied separate racks and neither member of the third group bound. With the preferred rule, the first two still separated and the third landed on A alongside the first. The within-group topology stayed hard throughout. Only the between-replica rule became a preference with weight 80. Two Pods on one rack supply no additional rack-level redundancy. Three independent placements need three eligible domains. Each domain here contained one node. We tested the declared topology and placement. Physical power failures, link failures and serving failover were outside the experiment.

## 5. What if a Pod needs a particular device? Testing DRA

The earlier Pods expressed their needs as a count under `nvidia.com/gpu`. If two devices on a worker differ and a workload needs at least 80 GiB on one device or requires a particular device index, the scheduler needs more information. Kubernetes Dynamic Resource Allocation (DRA) lets a driver publish an inventory with device attributes and lets Pods express requirements through claims. We tested selection, exclusive allocation, reuse and consumption inside a running container. [Kubernetes DRA](https://kubernetes.io/docs/concepts/scheduling-eviction/dynamic-resource-allocation/) · [Volcano DRA configuration](https://volcano.sh/docs/v1.16.0/userguide/user_guide_how_to_enable_dra/)

**The two simulations have separate inventories.** We kept all 16 simulated B300s on the original two workers and installed the Kubernetes SIGs example DRA driver v0.5.0 on A only. It advertised two additional synthetic devices with 80 GiB each. The API server already served stable `resource.k8s.io/v1`. We explicitly set `predicate.DynamicResourceAllocationEnable: true` on Volcano's predicates plugin. The DRA Pods selected Volcano and requested devices solely through claims. The inventories are accounted separately, and the results below apply to the example driver. [Pinned example driver](https://github.com/kubernetes-sigs/dra-example-driver/tree/v0.5.0)

Four objects explain the path. The **ResourceSlice** advertised gpu-0 and gpu-1 on A, with indices 0 and 1 and a declared capacity of 80 GiB each. The **DeviceClass** selected the driver. A **ResourceClaimTemplate** generated a separate ResourceClaim for each Pod, with CEL selectors attached to the device request. The **Pod** referenced its claim at both the Pod and container levels. After scheduling, the claim reported the device and request name. The kubelet asked the driver to prepare the device and the runtime applied its CDI configuration. We could then read the device name from the container logs.

![Both Pods target index one on a worker with two 80 GiB devices. Removing the holder releases gpu-1 to the original waiting Pod while gpu-0 remains free.](../../assets/practices/volcano-gpu-placement/design-devices.svg)

*Each Pod has its own claim. Follow the gpu-1 column to see when ownership passes from holder to waiter.*

```yaml
# ResourceClaimTemplate.spec.spec.devices.requests
- name: accel
  exactly:
    deviceClassName: gpu.example.com
    allocationMode: ExactCount
    count: 1
    selectors:
    - cel:
        expression: "device.capacity['gpu.example.com'].memory.compareTo(quantity('80Gi')) >= 0"
    - cel:
        expression: "device.attributes['gpu.example.com'].index == 1"
```

| Request submitted | Observed allocation and execution |
| --- | --- |
| At least 96 GiB on one device | The Pod was unbound and the claim had no allocation. Two 80 GiB devices could not satisfy a single-device request by adding their capacities. |
| At least 80 GiB and index 1 | The holder ran on A with gpu-1 in its claim and `GPU_DEVICE_1=gpu-1` in its container. |
| Another Pod using the same template while the holder ran | The new Pod waited with an unallocated claim, even though gpu-0 was free. After the holder was deleted, the waiting Pod retained its UID and received gpu-1. |
| Prefer 96 GiB, then accept 80 GiB | We listed the alternatives under `firstAvailable`. With gpu-1 still occupied, the claim recorded `accel/standard` and gpu-0. The container reported `GPU_DEVICE_0=gpu-0`. |

![DRA inventory, contention for one index, reuse after release and fallback to the second request](../../assets/practices/volcano-gpu-placement/dra.png)

**Allocation succeeded before the container could start.** On the first installation the driver passed its health check, Volcano had bound the holder to A, and its claim already named gpu-1. The kubelet emitted `FailedPrepareDynamicResources` because it had no registered driver. The chart put the registration socket in its default `/var/lib/kubelet/plugins_registry` while the node used a custom kubelet root. We corrected `kubeletPlugin.kubeletRegistrarDirectoryPath` and `kubeletPlugin.kubeletPluginsDirectoryPath` to match the node and let the driver register again. The original Pod and claim both kept their UIDs. The container started with its originally allocated device.

![The same Pod and claim before and after correcting the registration directory, including the kubelet event](../../assets/practices/volcano-gpu-placement/dra-registration.png)

When serving needs selection by device attributes or an explicit fallback, DRA can express conditions on individual devices that a node label cannot capture. For troubleshooting, start with inventory, selector matches and device ownership while a claim has no allocation. Once the claim names a device and the Pod is bound, inspect kubelet events, plugin socket paths and CDI, then check what the container sees. The 80 GiB figure here is a capacity advertised by the example driver. Actual B300 memory, isolation when sharing hardware and recovery after device failure require hardware and a vendor driver.

## Choosing a policy for the platform

| Operational question | What to measure first | Trade-off observed |
| --- | --- | --- |
| Can another whole-node replica start immediately? | Nodes able to fit the complete replica | Packing shapes remaining capacity. Extra GPU scoring weight added no benefit in this run. |
| How much can training borrow from serving? | Queue usage in the serving group and the next replica footprint | A cap bounded borrowing. Reserve whole-node capacity separately for immediate startups. |
| Who should give way at saturation? | Original victims, intact incumbent groups and arrivals that actually start | Whole-group eviction can free devices otherwise held by stranded ranks, at the cost of stopping more original Pods. |
| Is the replica count or fault independence more important? | Domain per replica and count of independent eligible domains | A hard rule waits. A soft rule allowed the third replica to share a rack and correlated failure risk. |
| Does a Pod need a specific capacity or index, and may it fall back? | Allocated device, matched request and in-container evidence | A strict selector can skip an idle device. Ordered alternatives admitted the Pod with its second choice. |

Before adopting these policies with physical GPUs, I would measure a week of waits where the fleet had enough free GPUs but lacked a complete placement for a production replica. I would also time recovery from a real training checkpoint. Those measurements tell you whether packing changes are worth making and how much disruption you can afford when making room for urgent inference.
