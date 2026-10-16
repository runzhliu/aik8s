---
title: "Koordinator and Online-Offline Workload Colocation: From Resource Reclamation to Production Deployment"
description: "Understanding Koordinator through resource accounting, QoS, interference governance, and large-scale community practice, and how to safely advance Kubernetes online-offline workload colocation"
status: reviewed
last_reviewed: 2026-09-21
---

# Koordinator and Online-Offline Workload Colocation: From Resource Reclamation to Production Deployment

Online services request resources based on peak usage, while offline tasks can tolerate queuing, throttling, and retries. Placing both types of workloads into the same set of machines can convert resources that online services do not actually use into batch processing throughput, but it also brings CPU, memory, cache, disk, and network contention into the same failure domain.

Therefore, colocation is not "squeezing in more Pods," nor is it simply raising Kubernetes resource overcommitment ratios. A usable colocation system must answer at least three questions simultaneously:

1. **How much resource can still be borrowed?** The resource ledger must distinguish between requested amounts, actual usage, safety margins, and capacity already lent out.
2. **Where should tasks be placed?** The scheduler must understand not only resource requests but also current node load, NUMA (Non-Uniform Memory Access) topology, and quotas.
3. **What if the prediction is wrong?** The node side must be able to throttle or evict lower-priority tasks within seconds to return resources to online services.

The value of Koordinator lies precisely in connecting these three questions into a closed control loop. On top of Kubernetes, it adds resource profiling, load-aware scheduling, differentiated QoS (Quality of Service), fine-grained CPU orchestration, elastic quotas, and safe rescheduling capabilities. This article is based on the community stable documentation v1.8; the in-development `next` documentation is used only to observe direction and is not a basis for production configuration.

![Colocation resource model: identifying the safety margin from online service requests and allocating it to yieldable workloads](../../assets/koordinator-colocation/resource-model.svg)

## 1. Why Clusters Are "Fully Allocated" While Machines Are Not Running at Full Capacity

The Kubernetes scheduler primarily performs admission and placement based on a Pod's `requests`. To withstand traffic peaks, release jitter, and single-machine failures, online services typically configure request values higher than actual usage during most time periods. This practice guarantees capacity, but it also produces three distinct resource curves:

- **Limit / Request**: the upper bound declared by the business, or the scheduling reservation;
- **Usage**: current real consumption, varying with traffic;
- **Reservation**: the predicted reserved amount derived from historical usage, recent trends, and safety factors.

`Request - Usage` cannot all be lent out. Starting Pods, traffic bursts, metric latency, system processes, and prediction errors all require safety margins. A more reasonable approximation of reclaimable resources is:

```text
可回收资源 = 节点可分配资源
           - 在线业务预测保留
           - 系统与故障余量
           - 已借给低优先级负载的资源
```

This value changes over time. CPU can be throttled, and recovery from incorrect predictions is usually fast; memory is incompressible, and overly aggressive predictions can trigger a full-machine OOM (Out of Memory). Disk I/O, network bandwidth, last-level cache, and memory bandwidth can also create hidden bottlenecks where "CPU does not look saturated, yet online latency degrades."

The Google Borg paper provides a highly representative production signal: in its median cell, approximately 20% of workloads run on reclaimed resources; when predictions are inaccurate, the system throttles or terminates non-production tasks rather than sacrificing production tasks. This shows that the premise of reclaimed capacity is not that predictions are always correct, but that **errors must be quickly reversible, and borrowers must be able to yield**.

## 2. The Object of Colocation Is Not the Two Labels "Online" and "Offline"

Production environments must decompose workloads into at least four dimensions:

| Dimension | Question to Answer | Common Examples |
| --- | --- | --- |
| Business priority | When resources are insufficient, who gets resources first? | Core transactions, general online, training, batch processing, testing |
| Runtime QoS | When contending on the same machine, how are CPU, memory, and I/O allocated? | Dedicated cores, shared cores, throttleable, evictable |
| Recoverability | Can the workload continue after interruption? How costly is recovery? | Stateless retry, sharded rerun, checkpoint, uninterruptible |
| Interference profile | Which resource does it primarily contend for? | CPU, memory bandwidth, LLC, disk, network, GPU |

Kubernetes native QoS classifies Pods into `Guaranteed`, `Burstable`, and `BestEffort` based on CPU and memory request/limit, primarily affecting eviction order under node pressure. It cannot fully express colocation semantics such as "online services can share CPU but need tail latency protection" or "batch tasks can use idle cores but must yield at any time."

Koordinator therefore separates **Priority** from **QoS (Quality of Service)** into two dimensions: priority determines queuing, preemption, and resource guarantee order; QoS determines how a Pod uses CPU, memory, cache, and bandwidth after landing on a node.

### Koordinator QoS

| QoS Class | Typical Target | Core Semantics |
| --- | --- | --- |
| `SYSTEM` | Node system services, critical DaemonSets | Guarantee latency while limiting unbounded consumption by system processes |
| `LSE` | Extremely sensitive middleware | Dedicated resources, emphasizing isolation |
| `LSR` | Core online services requiring determinism | Reserve and bind CPU, allowing more explicit guarantees |
| `LS` | General microservices | Shared resources with burst elasticity retained |
| `BE` | Retryable batch tasks | Use idle resources, allow throttling and eviction |

### Koordinator Priority

| PriorityClass | Positioning | Suitable for Borrowing Resources |
| --- | --- | --- |
| `koord-prod` | Production online, guaranteed within quota | No |
| `koord-mid` | Mid-priority compute with budget | Can use relatively stable long-term margins |
| `koord-batch` | Regular batch processing | Can borrow and return when needed |
| `koord-free` | Testing or opportunistic tasks | No quota guarantee, varies with idle resources |

If a low-priority task lacks retry, checkpoint, or idempotency, merely labeling it with `BE` does not automatically make it suitable for colocation. Classification must come from business contracts, not unilateral guesses by the platform team.

## 3. How Koordinator Forms a Closed Control Loop

![Koordinator's closed control loop: profiling, computation, scheduling, execution, and feedback](../../assets/koordinator-colocation/control-loop.svg)

Koordinator's core components each handle problems at different time scales:

| Component | Runtime Location | Primary Responsibility |
| --- | --- | --- |
| `koord-manager` | Cluster control plane | Compute reclaimable resources, generate `NodeSLO`, manage elastic quotas, Reservation, and admission policies |
| `koord-scheduler` | Cluster control plane | Load-aware placement, NUMA/CPU topology, Gang, elastic quotas, Reservation, and preemption |
| `koordlet` | Each node | Collect `NodeMetric`, configure cgroups, execute CPU throttling, memory eviction, and QoS policies |
| `koord-descheduler` | Cluster control plane | Safely migrate Pods after load or resource distribution imbalance |
| Runtime Hook / NRI | Node runtime path | Timely write cgroup, CPUSet, resctrl, and other parameters during container creation and updates |

The closed loop sequence can be summarized as:

1. `koordlet` collects real usage of nodes and Pods, forming `NodeMetric`;
2. `koord-manager` computes `batch-cpu`, `batch-memory`, and other borrowable resources based on usage, safety thresholds, and configuration, then issues `NodeSLO`;
3. `koord-scheduler` selects nodes using the resource ledger, real-time load, and topology information;
4. `koordlet` and Runtime Hook implement CPU, memory, cache, I/O, and other isolation on the node;
5. When online load rises or node pressure exceeds bounds, throttle first, then evict low-priority workloads;
6. New usage and interference metrics feed into the next round of decisions.

This also explains why installing only `koord-scheduler` cannot be called complete colocation: the scheduler only decides the initial placement; load changes hours after running must be handled by node-side feedback control.

For how the node side implements policies into cgroups, `resctrl`, and the container runtime, continue reading [Koordlet and Runtime Hooks: Node Resource Isolation](koordinator-node-qos-runtime-hooks.md).

## 4. Four Key Mechanisms

### 4.1 Dynamic Resource Ledger

Koordinator converts the portion of online Pod resources that have been requested but are predicted to go unused into batch resources. Batch tasks use a separate extended resource rather than continuing to consume the ordinary `cpu` and `memory` ledgers. This avoids double-counting the same capacity across two scheduling paths.

Resource profiling must be handled conservatively:

- Recent usage peaks and longer-window quantiles;
- Metric sampling latency and Pod startup period estimates;
- System overhead of kubelet, kernel, runtime, and DaemonSets;
- Capacity margins for single-machine failures, online scaling, and rolling releases;
- Different compressibility of CPU versus memory.

The official resource model distinguishes short-term from long-term Reservation: tasks with short lifecycles that are easy to retry can use more aggressive short-term margins; tasks with high recovery costs such as training and stream computing should use more stable long-term margins or explicit quotas.

### 4.2 Load-Aware and Topology-Aware Scheduling

The native scheduler sees request-allocated amounts; Koordinator's LoadAwareScheduling can additionally read `NodeMetric` and filter and score nodes by current or historical quantile load. When a new Pod has not yet produced metrics, the scheduler uses request, limit, and estimation coefficients to avoid misjudging a starting low-load Pod as idle.

For CPU-sensitive, GPU, RDMA (Remote Direct Memory Access), or high-throughput tasks, the following must also be handled:

- CPU physical cores and hyperthread sibling relationships;
- CPU, memory, and device alignment within NUMA;
- PCIe, GPU, NIC, and network topology;
- Resource fragmentation and schedulability of subsequent large-spec tasks.

Load balancing and Binpack are not contradictory: at the cluster level, low-load nodes can be packed as tightly as possible to free up entire machines, but hotspot filtering, safety thresholds, and topology constraints must be given higher priority.

### 4.3 Node-Side Isolation and the "Last Line of Defense"

Successful scheduling only means the workload could be placed at that moment. Production colocation relies more heavily on continuous node-side protection:

- **CPU**: CPUSet, CPU Burst, shared pool, dynamic throttling, Core Scheduling, or Group Identity;
- **Memory**: Memory QoS, asynchronous reclamation, priority-based reclamation, and threshold eviction;
- **Cache/Bandwidth**: Linux `resctrl`, LLC (Last Level Cache), and MBA (Memory Bandwidth Allocation);
- **Disk and Network**: rate limiting or guarantees by QoS class, preventing batch tasks from exhausting queues and bandwidth;
- **Exception recovery**: when throttling low-priority tasks still fails to relieve pressure, execute controlled eviction.

Memory protection in particular cannot simply copy CPU policy. When CPU is overestimated, it can be throttled; when memory is overestimated, synchronous reclamation and jitter may occur first, ultimately letting the kernel OOM Killer choose processes. The official documentation therefore recommends treating MemoryEvict as the last line of defense against node OOM in production colocation, and considering `MemoryAllocatableEvict` when using the batch resource ledger.

### 4.4 Quotas, Jobs, and Rescheduling

Colocation capacity is not "first come, first served until exhausted." Multi-team environments additionally require:

- `ElasticQuota` to express organizational hierarchy, minimum guarantees, maximum limits, and borrow-return relationships;
- Gang Scheduling to ensure distributed tasks are admitted as a group;
- `Reservation` to reserve resources for scaling, migration, scheduled jobs, or device tasks;
- Descheduler to migrate workloads after hotspots, topology changes, and long-term fragmentation;
- PodMigrationJob, PDB (Pod Disruption Budget), and migration rate limiting to jointly constrain disruption.

Without quota governance, low-priority tasks can still form "starvation within batch tasks" even when resources are abundant; without job semantics, distributed tasks may start only a subset of Workers, occupying resources while being unable to make progress.

## 5. What Large-Scale Enterprise Practice Tells Us

Public case studies differ in environment, hardware, business, and metric definitions; one company's utilization rate cannot be directly taken as one's own commitment value. What is more valuable is extracting common engineering constraints.

| Public Practice | Publicly Disclosed Facts | Implications for Colocation Design |
| --- | --- | --- |
| Google Borg | The paper states that in the median cell, approximately 20% of workloads run on reclaimed resources; when predictions are wrong, non-production tasks are throttled or terminated first | A reclamation system must design "yieldability" as a runtime contract; protection mechanisms matter more than prediction accuracy |
| Alibaba Sigma + Fuxi | The publicly released 2017 Trace covers approximately 1,300 machines, and the 2018 Trace approximately 4,000; online and batch tasks are coordinated by different schedulers | Two schedulers must share capacity and allocation ledgers, otherwise double allocation occurs; microarchitecture interference also requires observation |
| ByteDance Gödel Scheduler | Official CNCF article discloses over 2,000 Pod/s in a single shard, over 5,000 Pod/s across multiple shards, and the largest production cluster exceeding 20,000 nodes and 1 million Pods | As clusters grow, Job-level semantics, scheduling throughput, sharding, and preemption storms become independent problems |
| Xiaohongshu + Koordinator YARN Copilot | Koordinator official design document states the solution is widely used in production; YARN NodeManager and Kubernetes Pods share batch resources and QoS | Legacy YARN ecosystems need not be migrated to Pods all at once, but both sides must synchronize borrowable resources and allocation results |
| Koordinator Adopters | The community adopter list is self-reported by users; Xiaohongshu, iQiyi, 360, Xiaomi, Dewu, and others mark production maturity as Stable | Production demand concentrates on online/offline colocation, fine-grained CPU/GPU scheduling, Flink/YARN, and load-aware migration |

The boundaries of these solutions should also be noted: Gödel is a scheduler built by ByteDance for unified scheduling and ultra-large-scale Job semantics, not production data for Koordinator; the Koordinator Adopters list is a community self-reported inventory, not an independent audit. When citing these materials, the type of evidence should be stated, avoiding writing "has been used" as "has been proven suitable for all environments."

### Common Pattern One: Define Who Can Be Sacrificed First

Borg, Alibaba's dual schedulers, and Koordinator's BE class all rest on the same premise: batch tasks accept longer startup times, resource fluctuation, or retries. The platform must implement this in job templates, retry budgets, checkpoint cycles, and business SLOs, rather than leaving it at priority numbers.

### Common Pattern Two: Resource Ledgers Must Be Unified; Execution Can Be Layered

Kubernetes, YARN, or standalone batch schedulers can each retain their own submission entry points, but available capacity, allocated amounts, and return actions must converge on a single source of truth. The focus of YARN Copilot is not "putting NodeManager into a container," but having YARN use the batch resources computed by Koordinator, with both sides knowing who has occupied which resources.

### Common Pattern Three: Utilization Is Not the Only Outcome

Real benefits must be observed simultaneously across:

- Online business P99/P999 latency, error rate, and throughput;
- Batch task completion time, queueing time, retry and eviction rate;
- Node CPU, memory, PSI (Pressure Stall Information), LLC, disk, and network;
- Predicted values, actual usage values, and fulfillment rate of reclaimable resources;
- Saved machine costs, additional platform costs, and failure costs.

A chart showing "average CPU rising from 20% to 55%" cannot prove that colocation succeeded. If online P99 degrades, batch tasks rerun every day, or the operations team frequently intervenes manually, the higher the book utilization, the greater the actual cost may be.

## 6. A More Reliable Production Rollout Path

![Koordinator's five-stage production rollout path for workload colocation](../../assets/koordinator-colocation/rollout-ladder.svg)

### Stage 0: Establish a Baseline Without Colocation

First, observe continuously for at least one complete business cycle and record:

- Online service request, usage, P50/P90/P99/P999, and peak/valley patterns;
- Node CPU, memory, PSI, disk, network, OOM, and Eviction;
- Batch task queue, runtime, failure rate, and retry cost;
- Special windows such as releases, scaling, failover, and major sales events.

If there is no baseline at all, after colocation you cannot determine whether latency fluctuations come from the new policy or from the business itself.

### Stage 1: Online Protection Only, No Resource Reclamation

First validate QoS classification, CPU/NUMA orchestration, Memory QoS, metrics, and alerts. Select a small number of nodes and confirm that Koordinator's Runtime Hook and cgroup are compatible with the existing kubelet policy. This stage can surface differences in kernel, cgroup v1/v2, CPU Manager, container runtime, and operating system.

### Stage 2: Let the Easiest-to-Recover Batch Tasks Enter the Pilot

Start with stateless, idempotent, short-running CPU batch tasks:

- Restrict to a dedicated node pool and a business whitelist;
- Set a maximum batch resource ratio for the pilot;
- Open CPU reclamation only, keep memory conservative;
- Clearly define suppression, eviction, retry, and exit conditions;
- Automatically stop new batch tasks when the online SLO is breached, and reclaim borrowed capacity.

### Stage 3: Establish Resource Fulfillment Rate and Interference Matrix

Validate CPU-intensive, memory-intensive, disk-intensive, and network-intensive tasks category by category. Combine online services and batch tasks into an interference matrix, and record P99, PSI, cache hit rate, memory bandwidth, and task completion time before and after co-location on the same machine. Only combinations that have been validated may be expanded in scope.

### Stage 4: Extend to Stateful Computing and Multiple Schedulers

Training, Spark, Flink, YARN, and similar tasks require additional Checkpoint, Gang, elastic quota, and unified accounting. Only at this point should you introduce YARN Copilot, Reservation, or more complex rescheduling policies, to avoid changing too many control loops at once in the first stage.

### Stage 5: Turn Colocation into Continuous Capacity Engineering

Recalibrate thresholds according to business cycles; incorporate node hardware, kernel versions, and workload profiles into grouping; perform canary, rollback, and benefit review for every policy change. Colocation is not a one-time switch but a long-running feedback control system.

## 7. Which Metrics Should Production Acceptance Look At

### Online Business Red Lines

| Metric | Purpose |
| --- | --- |
| P99/P999 latency and error rate | Primary stop condition for colocation |
| CPU throttling, Run Queue, context switches | Determine CPU contention and quota limits |
| CPU/Memory/IO PSI | Detect waiting that average utilization cannot show |
| OOM, direct memory reclamation, Major Page Fault | Determine whether memory reclamation harms online services |
| Disk queue, throughput, latency, and network packet loss | Locate non-CPU interference |

### Batch Task Experience

| Metric | Purpose |
| --- | --- |
| Queueing time and completion time percentiles | Determine whether borrowed resources are available and whether they fluctuate frequently |
| Suppression seconds, eviction rate, retry rate | Calculate the cost colocation imposes on batch tasks |
| Checkpoint success rate and recovery time | Verify whether long tasks are truly preemptible |
| Resource satisfaction | Distinguish between "Pod Running" and "task making effective progress" |

### Platform Control Plane

| Metric | Purpose |
| --- | --- |
| NodeMetric freshness | Stale data should not continue to guide load-aware scheduling |
| Scheduler queue, scheduling throughput, P99 latency | Observe the impact of plugins and large-scale Jobs on the scheduler |
| Webhook latency, errors, and rejections | Prevent the admission path from amplifying control plane failures |
| Reclaimable resources, allocated batch resources, and actual batch usage | Verify whether the ledger closes |
| Suppress/Evict trigger count and reasons | Determine whether thresholds are too aggressive or protection is actually effective |

A simple but practical benefit formula is:

```text
净收益 = 节省的机器与能耗成本
       - 在线性能回退成本
       - 批任务重试与 Checkpoint 成本
       - 混部平台和运维成本
```

## 8. Common Failure Modes

### Only Looking at Average Utilization

Averages mask instantaneous hotspots and tail latency. Colocation thresholds should at minimum combine high-percentile usage, PSI, and online business SLOs.

### Using the Same Oversell Ratio for CPU and Memory

CPU can be throttled, but memory pressure can cause synchronous reclamation and OOM. Memory policy should be more conservative, with a verifiable eviction path prepared.

### Treating Running as Effective Throughput

A BE Pod may be in Running state but throttled to very little CPU. You should also look at task progress, resource satisfaction, and completion time.

### Enabling Across the Entire Cluster at Once

Node hardware, kernel, cgroup, and workload profiles differ. Use node labels and layered SLO configuration for canary rollout, and keep a non-colocated control group.

### Two Schedulers Each Calculating Idle Resources Separately

If Kubernetes and YARN, or online and batch schedulers, do not share a unified ledger, the same surplus can be allocated twice. Synchronization must cover total amount, allocated amount, Pod/Container exit, and abnormal recovery.

### Only Limiting CPU Without Observing Cache, Memory Bandwidth, and I/O

Online latency can degrade even when CPU utilization is not high. Passing a CPU-intensive pilot does not mean disk- or network-intensive tasks are safe either.

### Letting Non-Recoverable Tasks Bear Concession Semantics

A long task without idempotency, retry, or Checkpoint can lose hours of computation from a single eviction. It is better suited for guaranteed `mid` capacity than opportunistic `free` capacity.

## 9. When Is Koordinator Suitable

| Scenario | Fit Level | Reason |
| --- | --- | --- |
| Online services have obvious long-term reservations while retryable batch tasks exist | High | There is stable reclaimable space and a clear concession party |
| Big data, training, and microservices share physical resources | High | Resource ledger, job scheduling, and node QoS must work together |
| Only queue admission and department quotas are needed | Medium | Lighter solutions such as Kueue may already be sufficient |
| Only Binpack for ordinary Pods is needed | Medium | Native Scheduler Plugin or Descheduler may be simpler |
| Workloads are all uninterruptible and extremely latency-sensitive | Low | Without concession-capable workloads, colocation gains are small |
| Kernel, runtime, and node configuration are highly uncontrollable | Low | Node-side QoS and Hook are hard to form a reliable closed loop |
| Cluster lacks online SLO, node PSI, and task progress metrics | Low | Cannot prove safety or automatically stop losses |

Koordinator is not a simple replacement for Kueue, Volcano, or Cluster Autoscaler: Kueue handles workload admission and quotas, Volcano excels at batch scheduling and Gang, and Cluster Autoscaler/Karpenter handles adding or reclaiming nodes. Koordinator focuses more on fine-grained scheduling, overselling, QoS, and interference governance over the same set of resources, and in production the two can be combined by boundary.

## 10. Minimal Viable Pilot Checklist

- [ ] Online services already have clear P99/P999, error rate, and capacity baselines;
- [ ] Batch tasks have idempotency, retry, or Checkpoint;
- [ ] Priority and QoS are confirmed by business owners;
- [ ] Pilot node pool, maximum borrowing ratio, and rollback method are clearly defined;
- [ ] A conservative policy is used when NodeMetric expires;
- [ ] CPU Suppress, Memory Evict, and node OOM paths have been through failure drills;
- [ ] Prometheus collects key metrics from both the control plane and pilot nodes;
- [ ] Online SLO breaches can automatically stop admission and release batch capacity;
- [ ] At least one group of control nodes without colocation enabled is retained;
- [ ] Net benefit is recalculated before every scope expansion, not just utilization.

## 11. Conclusion

The essence of colocation is turning idle capacity into a resource that can be borrowed, returned, and audited. Koordinator provides complete building blocks from resource profiling and scheduling to ledger, QoS, and eviction, but the tool itself will not define business priorities for the team, nor will it add recovery capability to batch tasks.

Large-scale practice has repeatedly validated the same thing: a successful colocation system does not require predictions to never be wrong, but requires hard protection for online services, concession capability for low-priority tasks, a closed resource ledger, and observability and rollback for every policy change. Get these four things solid first, then talk about utilization improvement — only then does colocation turn from a one-time cost experiment into a long-running capacity capability.

## References

- [Koordinator: Architecture Overview](https://koordinator.sh/docs/architecture/overview)
- [Koordinator: Resource Model](https://koordinator.sh/docs/architecture/resource-model)
- [Koordinator: QoS](https://koordinator.sh/docs/architecture/qos)
- [Koordinator: Batch Colocation Quick Start](https://koordinator.sh/docs/best-practices/batch-colocation-quick-start)
- [Koordinator: Load-Aware Scheduling](https://koordinator.sh/docs/user-manuals/load-aware-scheduling)
- [Koordinator: Memory Resource Eviction](https://koordinator.sh/docs/user-manuals/memory-evict)
- [Koordinator: Fine-Grained CPU Orchestration Practice](https://koordinator.sh/docs/best-practices/fine-grained-cpu-orchestration)
- [Koordinator YARN Copilot Design](https://koordinator.sh/docs/designs/koordinator-yarn)
- [Koordinator Adopters](https://github.com/koordinator-sh/koordinator/blob/main/ADOPTERS.md)
- [Kubernetes: Pod QoS Classes](https://kubernetes.io/docs/concepts/workloads/pods/pod-qos/)
- [Google: Large-scale cluster management at Google with Borg](https://research.google/pubs/large-scale-cluster-management-at-google-with-borg/)
- [Alibaba Cluster Trace Program](https://github.com/alibaba/clusterdata)
- [CNCF: Gödel Scheduler open-sourced](https://www.cncf.io/blog/2024/04/02/godel-scheduler-open-sourced-a-unified-scheduler-for-online-and-offline-workloads/)
