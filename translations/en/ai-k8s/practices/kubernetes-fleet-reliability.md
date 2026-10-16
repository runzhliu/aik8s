---
title: "Building Stability for Hundreds of Kubernetes Clusters"
description: "Starting from configuration differences, batch changes, and failure recovery in multi-cluster operations, sharing design trade-offs and implementation methods for stability building"
status: evolving
last_reviewed: 2026-09-09
---

# Building Stability for Hundreds of Kubernetes Clusters

After the number of clusters increases, small problems in daily operations gradually become platform problems. A component upgrade needs to face different kernels and runtimes, a node maintenance needs to coordinate business replicas and remaining capacity, and a unified configuration may simultaneously change the behavior of multiple clusters. Work that could originally be completed by engineers checking machine by machine needs to gradually become processes that can be executed in batch, stopped at any time, and retain results.

Stability building also changes accordingly: after an anomaly is discovered, who stops subsequent releases, which nodes are allowed to continue maintenance, how backlogged requests recover, and who accepts the business. If these decisions are left until the failure scene, the more clusters there are, the higher the coordination cost. Writing them into the platform's execution logic in advance is the only way to let monitoring truly participate in failure control.

This article draws on public practices from Uber, LinkedIn, and Google, as well as this site's APF testing, to organize design trade-offs and implementation methods in multi-cluster stability building. Content involving enterprise implementations includes sources; release batches and metric calculations use clearly labeled calculation examples to illustrate mechanisms.

If the question is how a single cluster continues to expand and how API Server, etcd, scheduling, and networking cross conventional scale boundaries, you can read [Optimizing Kubernetes Clusters with Ten Thousand Nodes](large-scale-kubernetes-optimization.md).

## 1. After Scaling Up, Address Differences and Shared Dependencies First

300 small clusters and 3 large clusters face different primary constraints. The former is more likely to encounter version combinations, configuration drift, credential management, and batch operation problems; the latter may encounter single-cluster API, scheduling, and network capacity limits first. Comparing only cluster counts masks these differences.

| Risk | Typical manifestation with hundreds of clusters | Controls that need to be established |
| --- | --- | --- |
| Configuration and version divergence | The same CNI upgrade fails on some kernel or runtime combinations | Asset inventory, compatibility matrix, baseline and exception management |
| Simultaneous failures | Central release system syncs incorrect configuration to all clusters | Batched release, independent stop switches, failure domain constraints |
| Shared dependency failure | Image registry, identity service, or shared webhook affects multiple clusters | Dependency map, regional isolation, explicit disconnection behavior |
| Growth in manual operations | Every certificate update and node maintenance requires individual handling | Stateful, recoverable automated workflows |
| Metrics masking local failures | Normal traffic of large clusters masks small clusters being completely unavailable | Three observation dimensions: single cluster, business tier, and global |

The value of the cluster inventory is most evident during changes and troubleshooting: selecting canary targets requires knowing version and hardware combinations, regional failures require knowing business ownership, and recovery requires finding backups and responsible parties. Therefore, in addition to environment, region, node, and Pod scale, the inventory should also record business tier, failure domain, version combination, shared dependencies, backup location, most recent recovery verification, and ongoing changes.

The inventory needs continuous reconciliation with actual state. For exception configurations retained due to historical compatibility issues, record the reason, responsible party, and exit conditions; otherwise, a unified configuration sync may overwrite differences that are still useful as drift.

**The platform most needs to avoid letting the same error propagate to multiple independent clusters simultaneously.** Therefore, the multi-cluster management platform itself is also an object that requires isolation and drills.

## 2. Extract Reusable Practices from Industry Experience

### Uber: Scale Validation and Controlled Scaling

Uber introduced version integration and performance validation systems in its Kubernetes migration article, and conducted benchmark validation in an environment of 7,500 nodes and 200,000 Pods; on the runtime side, APF is used to manage high-cost API calls, and scaling is split into small batches, continuing only after the previous batch succeeds. This shows that release validation and execution cadence need dedicated construction and cannot rely solely on component default parameters. [Uber Engineering Article](https://www.uber.com/ca/en/blog/migrating-ubers-compute-platform-to-kubernetes-a-technical-journey/)

### LinkedIn: Maintenance Operations Need to Understand Application State

LinkedIn's Stateful Workload Operator collaborates with the Application Cluster Manager to check whether applications can withstand interruption before deployment, maintenance, and scaling—for example, whether shards have sufficient replicas. The platform orchestrates actions uniformly, and applications provide domain-related safety judgments. [LinkedIn Engineering Article](https://www.linkedin.com/blog/engineering/infrastructure/stateful-workload-operator-stateful-systems-on-kubernetes-at-linkedin)

### Google: Phased Cluster Upgrades and Engineering Time Guarantees

GKE's rollout sequencing supports grouping clusters, upgrading in order with observation periods; its custom phase capability allows covering a small number of production clusters first, then expanding scope. What can be borrowed is the organizational approach to cross-cluster upgrades, not treating a specific observation duration as a universal standard. [GKE Official Documentation](https://docs.cloud.google.com/kubernetes-engine/docs/concepts/rollout-sequencing/about-rollout-sequencing)

At the organizational level, the Google SRE book proposes keeping repetitive operational work below 50% of SRE time, reserving time for engineering projects. This is an organizational goal described by Google, not a staffing ratio standard for all companies. It illustrates that stability investment needs to be scheduled into development work and cannot rely entirely on handling issues opportunistically during on-call shifts. [Google SRE: Eliminating Toil](https://sre.google/sre-book/eliminating-toil/)

These practices share a common point: converting the steps that rely on human judgment in release, maintenance, and recovery processes into explicit execution conditions. Below, we expand along the daily work of a multi-cluster platform to discuss how these conditions are implemented.

## 3. Unified Management, Independent Failure Domains

Unified management can reduce duplicate configuration, but it also expands the impact scope of central components. A viable division is: the center is responsible for inventory, versions, and policies; regional or business groups are responsible for execution budgets and release batches; within clusters, local coordination, flow control, and evidence collection. This separates "deciding what to release" from "whether execution is currently allowed." When the central management platform loses connectivity, already-running workloads should continue working as much as possible, and new high-risk changes should be paused.

<picture>
  <source media="(max-width: 600px)" srcset="/assets/kubernetes-fleet-reliability/fleet-boundaries-mobile.png">
  <img src="/assets/kubernetes-fleet-reliability/fleet-boundaries.png" alt="Multi-cluster reference architecture: central policy, group execution budgets, and in-cluster autonomy" width="1200" style="max-width:100%;height:auto">
</picture>

This is a design goal that needs to be validated through disconnection drills. If Pod admission still synchronously calls central webhooks, or if every business authentication must access the same identity service, clusters deployed in different locations may also be affected simultaneously.

Disconnection drills need to cover both disconnection and reconnection processes. During disconnection, check existing services; after reconnection, check whether backlogged tasks are executed in batches; if the old executor has not exited and the new executor has already taken over, also confirm that the same task will not be executed repeatedly. Tasks need idempotency keys, execution leases, or equivalent anti-duplication mechanisms, and the target cluster identity and configuration version must be fixed, not relying solely on the current kubeconfig context.

For external webhooks, restrict match scope, set bounded timeouts, and eliminate circular dependencies. `failurePolicy` needs to be decided item by item based on security and availability requirements, and cannot be uniformly set to `Ignore` for availability. The Kubernetes official documentation also recommends evaluating replacing some external calls with built-in admission capabilities. [Webhook Best Practices](https://kubernetes.io/docs/concepts/cluster-administration/admission-webhooks-good-practices/)

## 4. Turn Changes into Processes That Can Be Stopped and Verified

### Release Validated Version Combinations

A component's successful upgrade in a test cluster only validates the environment combination at that time. If production clusters use different kernels, network configurations, or storage plugins, problems may still appear after expanding coverage. The selection of canary objects therefore needs to consider representativeness, not just choosing the most idle and easiest-to-operate clusters.

A release unit should include version and configuration summaries for Kubernetes, etcd, container runtime, kernel, CNI, CSI, and key controllers; GPU clusters also need to include drivers, device plugins, and related runtimes. Save image digests, configuration diffs, compatibility conditions, and recovery entry points to avoid "the same version name with different actual content."

Validation should cover at least resource creation, DNS, cross-node networking, Service, volume mounting, scheduling, and representative business. Component startup success, Pod Ready, and business request success are different acceptance levels. Even if a CNI upgrade has all DaemonSets Ready, cross-node connectivity and behavior of existing connections still need to be checked.

### Control Cluster Batches and Node Batches Simultaneously

The following is a **hypothetical 300-cluster release calculation example**, with non-overlapping clusters at each stage, totaling 300. Batches are not fixed production recommendations; the first validation should cover major version and hardware combinations, and core business should have separate advancement conditions.

| Stage | New clusters in this stage | Primary purpose | Advancement conditions |
| --- | ---: | --- | --- |
| Experimental environment | 2 | Validate process and recovery entry points | Functional validation and recovery checks pass |
| Non-critical business | 8 | Observe real business behavior | Business metrics pass within the effective observation window |
| Representative production group | 30 | Cover major components and hardware combinations | Each combination passes individually, no new severe failures |
| Group expansion | 60 | Validate broader coverage | Both group capacity and change budget allow |
| Remaining clusters | 200 | Complete coverage | Further split into several small batches; core business validated separately |

<picture>
  <source media="(max-width: 600px)" srcset="/assets/kubernetes-fleet-reliability/rollout-gates-mobile.png">
  <img src="/assets/kubernetes-fleet-reliability/rollout-gates.png" alt="Hypothetical 300-cluster batch release, advancing after validation at each stage, stopping on anomaly or missing observation" width="1200" style="max-width:100%;height:auto">
</picture>

Cluster batch count is only one dimension. The number of nodes maintained simultaneously in the same region, the same business replica group, and within a single cluster should also be separately limited. Three small clusters and three large clusters may have completely different business impacts, so risk budgets cannot be calculated by count alone.

The release workflow can be expressed as: `预检 → 固定目标与版本 → 执行一批 → 业务验证 → 观察 → 下一批`. On anomaly, missing metrics, or unclear execution state, first stop new actions, then determine whether to withdraw configuration, repair components, or migrate business. **Pausing a release cannot automatically undo changes that have already propagated.**

"Rollback" also needs to be defined by object: applications or components can restore validated configurations; Kubernetes control plane downgrades, etcd data recovery, and CRD storage version changes have independent constraints and cannot be promised entirely by a single Git revert.

## 5. During Operation: Limit Abnormal Requests and Resource Contention

Control plane protection needs to govern both clients and servers. Clients use caching, reasonable LIST/WATCH scopes, retry backoff, and request budgets; servers use APF classification and share constraints to reduce mutual interference. Ordinary GET, higher-cost LIST, long-lived connections, and writes should be distinguished, and capacity should be evaluated in combination with object count, response size, and processing latency. Mechanism details are in [Kubernetes Flow Control Guide](../cluster/flow-control.md).

This site's [APF Isolation Testing](apf-isolation-case.md) provides a small-scale piece of evidence: on Kubernetes 1.30.4, among 450 batch requests in the zero-seat Queue phase, 448 returned 429, and the other 2 succeeded after share recovery; throughout, 359 control requests succeeded. Zero-seat Reject still allowed low-concurrency requests through, and the article explains the boundary against the source code.

In this test, the key to troubleshooting was first checking the response headers to verify the FlowSchema and priority actually hit by the requests, then comparing against rejection counters, client status codes, and version source code. Looking only at zero seats in the configuration makes it easy to mistake "rule created" for "request blocked." When promoting such policies to other clusters, the same validation process needs to be preserved, covering target versions, business request categories, controller retries, and high-load behavior. APF also does not handle rate limiting for business HTTP requests.

On the resource side, ordinary business, platform components, and offline tasks should be considered separately: CPU, memory, ephemeral storage, PID, IP addresses, and storage throughput may all be exhausted before total node compute capacity. Resource quotas and priorities need to be validated against actual reserved capacity, and critical components cannot be assumed to run based on PriorityClass alone.

## 6. Capacity Assurance: Whether It Can Absorb After Failures

Node maintenance and failure migration both consume remaining capacity. Even if average utilization is not high during normal operation, workloads may not be migratable due to topology or storage conditions. Capacity evaluation needs to go from "how many resources remain" to "where these tasks can migrate," and be calculated separately by critical resource:

```text
故障后的容量余量
= 满足拓扑和依赖条件的健康可分配容量
− 峰值需求
− 已批准的维护占用与安全预留
```

This is a capacity evaluation framework, not a scheduler formula. CPU, memory, GPU, Pod IP, volume mount count, storage, and network each need to satisfy their own constraints; different dimensions cannot be added together.

For example, 16 idle GPUs in total does not guarantee the ability to accommodate a task requiring 8 cards on the same machine. Cross-region remaining capacity may also be unusable due to data, local disks, network latency, or quota limits. For distributed training, node sets, RDMA, and restart costs also need to be checked.

Capacity validation should include node failures, regional capacity reduction, batch Pod recreation, and traffic from image or model re-downloads. Only steady-state load testing after startup cannot reveal image registry congestion and control plane burst pressure during recovery. This can be evaluated in conjunction with [Model Cold Start Optimization](llm-cold-start-optimization.md) and [GPU Topology Scheduling Case](gpu-topology-fragmentation-scheduling.md).

## 7. Node Maintenance and Auto-Repair: First Determine Whether Interruption Is Allowed

The most easily overlooked aspect of node maintenance is intermediate states: the node has been cordoned, Pods have only partially migrated, and the executor has exited. If re-run from the beginning, it may repeatedly evict or skip necessary checks. Therefore, the maintenance process needs to persist the state of each step: check business and capacity → isolate new scheduling → orderly eviction or application migration → maintenance → node validation → business validation → re-admission.

`cordon` mainly prevents new ordinary scheduling and does not automatically migrate existing Pods. `drain` respects PDBs when working through the Eviction API, but PDBs cannot guarantee avoidance of all types of interruption, nor can they replace judgments about database shards or training checkpoints. When maintenance encounters PDB blocking, replicas and capacity should be checked first, and eviction protection should not be bypassed by default. [Safely Draining Nodes in Kubernetes](https://kubernetes.io/docs/tasks/administer-cluster/safely-drain-node/)

Auto-repair needs to clearly define "diagnostic signals" and "actions allowed to execute." For example, a single node with consecutive failures can enter the isolation process; when a large number of nodes in the same region are simultaneously unreachable, network or shared dependency anomalies should be considered first and batch recreation paused. Increasing retry counts may amplify failures.

| Control | Recommended behavior |
| --- | --- |
| Failure confirmation | Combine duration, multiple signals, and recent changes to avoid a single collection gap triggering restart |
| Repair budget | Set limits separately for the entire platform, region, cluster, and business replicas |
| Abort conditions | Stop new actions when the abnormal node ratio expands, critical probes fail, or observation loses connectivity |
| Recovery cooldown | Keep an observation period after repair, limit repeated restarts of the same object |
| State and audit | Record reason, object UID, execution version, result of each step, and manual takeover |

Auto-repair also needs validation: after creating a controlled failure, in addition to checking that the failed node was handled, confirm that normal nodes were not mistakenly operated on, executor restarts do not repeat operations, and the stop switch is actually effective.

## 8. Disaster Recovery: Restore Objects, Data, and Business Chains

Recovery work often gets stuck outside snapshots: the backup is available, but the decryption key is missing; the control plane is up, but business volumes are not restored; Pods are running, but ingress and identity dependencies are still unavailable. The disaster recovery process needs to be checked along the business access chain, not ending when snapshot import succeeds. Recovery materials and acceptance can be divided into three scopes:

| Scope | Recovery materials | Acceptance content |
| --- | --- | --- |
| Control plane | etcd snapshot, configuration, certificates, encryption configuration, and external key dependencies | API available, controllers reconcile correctly, resource state consistent |
| Application data | Database backups, volume data, object storage, and application consistency information | Data readable and writable, loss scope meets target |
| Business chain | Images, configuration, ingress, DNS, identity, and dependent services | Representative business completes requests from ingress to data layer |

etcd snapshots cannot replace business volume backups. Restoring old snapshots may also cause revision rollback, affecting caches that depend on Watch; the official etcd 3.6 recovery documentation discusses revision bump and compact markers. Recovery processes should be validated against the actual version, and a single version's commands cannot be used as a universal script for all clusters. [etcd Disaster Recovery Documentation](https://etcd.io/docs/v3.6/op-guide/recovery/)

RPO describes the acceptable data loss window, and RTO describes the target recovery duration. When reporting actual results, the start and end points should be explicit: from failure occurrence to business recovery, versus from executing the recovery command to API availability, measure different capabilities. The storage where backups reside, decryption keys, and operational credentials should also be reachable during failures.

For GPU training, you must also verify that checkpoints are complete, that training can resume from them, and how many effective GPU hours were lost; for inference, you need to verify model loading, readiness checks, request quality, and latency—not merely container liveness.

## 9. Let Monitoring Drive Decisions and Keep Metric Definitions Clear

A correspondence must be established between platform-side metrics and business-level experience. An API request succeeding does not mean the application has finished deploying; a Pod being created successfully can still leave it waiting on volume mounting for a long time. Beyond API success rate, you also need to observe the completion rate of qualifying deployments, Pod startup time, PVC mount success rate, and DNS and service connectivity success rate. When excluding cases such as user-initiated cancellations or invalid specifications, rules should be defined in advance, and the raw totals should be retained, so that results are not made to look better by changing the denominator.

Multi-cluster dashboards should display at least three perspectives simultaneously: traffic-weighted global metrics, per-cluster metrics, and the count of non-compliant clusters grouped by business tier. Probe loss should be displayed as unknown or an observation failure, not defaulted to success; low-traffic clusters need to be combined with active probes.

| Metric | Auditable Definition Example | Corresponding Action |
| --- | --- | --- |
| Release success rate | Successful changes within window / completed changes, with failures and cancellations listed separately | Halt rollout of the problematic version |
| Change failure rate | Changes causing incidents of the specified severity / total changes, with a clear attribution window | Improve pre-checks and canary coverage |
| Recovery time | From incident start to business acceptance, report median, P95, and sample count | Optimize the slowest recovery step |
| Recovery verification coverage | Key clusters or applications verified as required / total that should be verified | Fill in objects lacking recovery evidence |
| Manual operation cost | Repeated operation hours per 100 clusters per month | Decide which steps to automate first |

Error budgets can connect SLOs to release decisions. For example, **assuming** a request success rate target of 99.9%, the allowed failure ratio is 0.1%; if the failure rate within a window reaches 1%, the consumption rate is 10 times the budget-corresponding rate. Actual alerting should combine long and short windows, traffic, and business importance, avoiding fixation on a single instantaneous value. This approach references [Google SRE's SLO alerting design](https://sre.google/workbook/alerting-on-slos/).

Dashboards need to support answering "after which batch of changes did anomalies occur, which clusters were affected, whether rollout was stopped, and whether recovery passed." Release IDs, versions, and stage events can be added to the timeline, connecting metrics to tickets and execution records. Simply adding more panels will not automatically shorten recovery time.

## 10. What Open Source Components Can Cover

When selecting tools, capability boundaries should be determined first. The following are reference components, not a checklist requiring simultaneous deployment; feature status and APIs should be verified against the intended version.

| Component or Mechanism | What It Can Cover | What the Platform Still Needs to Fill In |
| --- | --- | --- |
| [Argo CD ApplicationSet Progressive Syncs](https://argo-cd.readthedocs.io/en/stable/operator-manual/applicationset/Progressive-Syncs/) | Progress Application updates in groups | The official page still marks this as experimental; business acceptance, cross-failure-domain budgets, and recovery processes need separate design |
| [Cluster API health checking](https://cluster-api.sigs.k8s.io/tasks/automated-machine-management/healthchecking.html) | Detect Machine health within Cluster API management scope and connect remediation | Must match the provider and version; integrating with existing bare metal is not accomplished merely by installing a component |
| [Node Problem Detector](https://github.com/kubernetes/node-problem-detector) | Report node problem signals | Who is allowed to restart, when to isolate, and batch remediation limits |
| [Velero](https://velero.io/docs/main/disaster-case/) | Kubernetes resources and supporting data protection processes | Storage plugins, application consistency, external dependencies, and real recovery acceptance |
| [Kubernetes APF](https://kubernetes.io/docs/concepts/cluster-administration/flow-control/) | API request classification, concurrency shares, and queuing | Client governance, version verification, and business traffic rate limiting |

GitOps can help preserve declarative configuration and diffs, but sync success does not equal business health; node problem detection also does not equal full self-healing. Platform engineering effort typically falls between components: identity, state, execution budgets, acceptance, and auditing need to be connected.

## 11. Put Stability Work into Continuous Development

The platform team can centrally maintain the entry point and execution framework, but whether a database shard allows interruption, or when a training job completes its checkpoint, still requires application-side judgment. Responsibility division should land on concrete interfaces: the platform is responsible for infrastructure standards, execution budgets, and control-plane capabilities; the business provides service tiers, data consistency, and interruption conditions; both sides jointly confirm maintenance and disaster-recovery acceptance criteria. Shared services such as network, storage, and identity must also have clear fault contacts and recovery owners.

Priorities can be determined from existing incident and operation records: first find problems that recur, have broad impact, and take long to recover from, then choose engineering changes that can repeatedly reduce risk. Do not equate "installing more components" with maturity.

| Current Gap | Priority Deliverable | Acceptance Method |
| --- | --- | --- |
| Cluster differences unclear | Inventory, version matrix, exception list | Sampling matches actual state; key objects have owners |
| Batch releases cannot be stopped | Batch executor, stop switch, configuration archival | After an anomaly in drills, subsequent batches are no longer touched |
| Backups never restored | Independent environment recovery process and evidence | API, data, and business accepted separately with recorded duration |
| Node failures all handled manually | Budgeted isolation and remediation process | Can handle mid-process failures; healthy nodes are not mis-operated |
| Every incident re-investigated from scratch | Automatic evidence retention, diagnostic entry point, acceptable remediation | Subsequent drills can reproduce and verify protection effectiveness |

Stability investment includes development time, validation environments, spare resources, and drill time. Whether it is worthwhile should be judged by business impact, recovery cost, and the degree of risk reduction; there is no one-size-fits-all answer of "how many people per 100 clusters" for every enterprise.

## 12. Make One Troubleshooting Session the Basis for Subsequent Operations

After incident handling concludes, what is worth keeping is not just the fix command, but also why the command worked, which versions it applies to, and which symptoms cannot be used as judgment criteria. Feeding this information into pre-checks, release validation, and routine inspections allows the next problem to be found earlier.

The APF field test provides a concrete example: zero-seat Reject still allowed requests through, and the explanation was ultimately obtained through response headers, client records, and source code verification. This result can be consolidated into a policy validation test case for the target version, to be re-checked after modifying rules or upgrading Kubernetes. The same experiment also found that the label semantics and bucket precision of the waiting histogram affect chart interpretation, so monitoring documentation also needs to be maintained together with configuration.

For multi-cluster platforms, remediation can be implemented along three positions: add checks at the release entry point that can identify problems early, add controls during runtime that can limit blast radius, and fill in previously missing materials and verification steps in the recovery process. Each remediation should record its scope of applicability, owner, and acceptance result, to avoid a single local fix being treated as resolved across all clusters.

Routine operations can also produce such improvement leads: conditions repeatedly confirmed manually are suitable for pre-checks, maintenance steps that frequently get stuck need clear state and takeover entry points, and files temporarily sought during recovery need to be archived in advance. By continuously eliminating these concrete obstacles, the platform can remain operable as cluster count grows.

Further reading: [APF isolation field test](apf-isolation-case.md), [Incident retrospective methods](incident-review.md), [AI platform reliability](../reliability.md), [Platform operations](../platform-operations.md).
