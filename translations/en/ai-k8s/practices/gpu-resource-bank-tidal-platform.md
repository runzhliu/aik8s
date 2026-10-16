---
title: "GPU Resource Bank and Tidal Inference Platform Practice Blueprint"
description: "Use Kueue or Volcano to implement GPU quota borrowing between business groups, combine KServe, AIBrix, KEDA and vLLM to build real-time and scheduled elasticity, and establish an observability closed loop from hardware health to per-token cost"
status: blueprint
last_reviewed: 2026-08-05
---

# GPU Resource Bank and Tidal Inference Platform Practice Blueprint

The hardest part of an enterprise GPU platform is not listing how many cards are available, but continuously making explainable trade-offs among three goals: business groups need deterministic resource guarantees, idle GPUs cannot sit idle indefinitely in departmental silos, and online inference must obtain capacity before traffic arrives.

This requires the platform to simultaneously provide:

- Guaranteed quotas, borrowing caps, lending floors, and fair sharing for business groups;
- Gang scheduling, priorities, Checkpoints, and orderly reclamation for training jobs;
- Inference service scaling based on request queues, TTFT, KV Cache, and other metrics;
- Tidal strategies such as inference during the day and training at night;
- Unified observability of GPU health, job efficiency, inference SLO, quota ledger, and cost;
- Self-service policies, platform guardrails, approval, auditing, and post-mortem review.

The platform should not re-develop a GPU scheduler from scratch. A better approach is to define a stable enterprise policy API, and let Controllers translate it into Kueue, Volcano, KServe, AIBrix, KEDA, PriorityClass, and monitoring rules.

This article does more than list components. The most valuable work in practice often happens at the seams between components: how DCGM metrics are stably attributed to users and teams, why the API Server should not be queried on every Prometheus scrape, how to periodically scan for "GPU-occupying but persistently low-utilization" workloads, and how to turn results into explainable per-person/per-department Showback rather than a Grafana chart with no action entry point.

## 1. Goals, Non-Goals, and Success Criteria

### 1.1 Goals

The platform needs to answer the following questions:

1. How many H100, A100, or other GPUs is each business group guaranteed at minimum?
2. When idle, how much can other groups borrow at most, and how much safety margin can the owning group retain?
3. When borrowed capacity is needed back, who gets stopped first, how much notice is given, and how is progress saved?
4. How many replicas does a given inference service currently need, and does the scale-out have complete GPU topology?
5. Before the fixed daily traffic peak, how far in advance should models be warmed up?
6. When GPUs look busy, are training and inference actually producing useful throughput?
7. How many GPU-hours did each business group, model, and service consume, and what business SLO was achieved in return?

### 1.2 Non-Goals

- Business groups cannot directly modify node labels, scheduler configuration, or global PriorityClass;
- No single percentage is used to promise the same utilization across all GPU models;
- Time-Slicing is not treated as GPU memory and fault isolation;
- No assumption that increasing replicas via HPA guarantees available GPUs;
- No forced Pod deletion as a substitute for Checkpoint, request draining, and reclamation protocols;
- No storage of Prompts, raw user identities, or Request IDs in Prometheus labels.

### 1.3 Success Criteria

The MVP must at least demonstrate:

- Two business groups can borrow GPUs from each other above their guarantees without exceeding platform caps;
- When the owning group needs capacity back, borrowed jobs yield capacity according to policy and can recover from Checkpoint;
- One vLLM inference service can scale out based on real service metrics and scale in safely;
- Tidal strategies can warm up in advance and release GPUs to the training queue during low-demand periods;
- Every admission, borrowing, reclamation, preemption, and scaling event has events, metrics, and audit records;
- The Dashboard can drill down from business group to Queue, Workload, Pod, GPU UUID, and model version.

### 1.4 What Evidence Should Practice Records Retain

To make conclusions reviewable, each pilot should retain:

- Kubernetes, GPU Driver, DCGM Exporter, Device Plugin/DRA, scheduler, and inference engine versions;
- Mapping samples of GPU model, UUID, MIG state, node, Pod UID, business group, and user;
- Raw `/metrics` samples, PromQL, Dashboard screenshots, and alert messages;
- Low-utilization scan hit times, filtering reasons, notified parties, and user feedback;
- Event timelines for borrowing, reclamation, Checkpoint, recovery, scale-out, and draining;
- Monitoring overhead such as API Server QPS, Prometheus Series count, and Exporter memory;
- Misattribution, missed alerts, duplicate alerts, and manual exemptions — not just successful screenshots.

The thresholds in this article are policy examples, not production answers for every cluster. Real thresholds must be derived from two to four weeks of baseline from the target business, model cold-start behavior, training phases, and team working patterns.

## 2. Target Architecture

```text
业务组用户 / 平台管理员 / FinOps
  ├─ 提交训练任务
  ├─ 发布推理服务
  ├─ 调整允许范围内的借用和潮汐策略
  └─ 查看配额账本、SLO 与成本
                         │
                         ▼
GPU Platform API / Portal
  ├─ GPUQuotaPolicy          组配额、互借与回收
  ├─ InferenceScalingPolicy  实时扩缩容与排空
  ├─ TidalPolicy             定时预热与容量切换
  └─ CapacityLease           有期限的保护与例外
                         │
                         ▼
Policy Controller + Admission Webhook
  ├─ 校验业务组权限和平台保护线
  ├─ 生成 Queue/Cohort/Priority/Autoscaler
  ├─ 协调借用回收、Checkpoint 与排空
  └─ 记录期望、决策原因和实际结果
            │                    │
            ▼                    ▼
训练与批任务控制面              在线推理控制面
Kueue 或 Volcano               KServe / AIBrix / Ray Serve
Trainer / JobSet / RayJob      vLLM / SGLang / TensorRT-LLM
Gang / TAS / Priority          HPA / KEDA / WVA / Router
            │                    │
            └─────────┬──────────┘
                      ▼
GPU 资源与节点层
GPU Operator / Device Plugin 或 DRA / MIG / RDMA / NFD
  ├─ h100-rdma-training
  ├─ h100-inference
  ├─ l40s-inference
  └─ mig-or-shared-development
                      │
                      ▼
可观测与成本平面
DCGM Exporter + Prometheus/Thanos + Grafana
Kube State Metrics + Queue/Serving Metrics
OpenTelemetry + Loki + Tempo/Jaeger
GPU-hours / 单位 Token 成本 / 配额与 SLO 报表
```

There are four distinct control points here:

| Control Point | Question Answered | Typical Components |
| --- | --- | --- |
| Resource Discovery and Partitioning | Which cards, MIG, or DRA Devices exist on the node | GPU Operator, Device Plugin, DRA Driver, NFD |
| Workload Admission | Which business group's job is eligible for how much quota right now | Kueue or Volcano Queue |
| Pod Placement | Which node and topology domain does an admitted Pod land on | kube-scheduler, Volcano, topology plugins |
| Service Elasticity | How many full replicas does the inference service need right now | KServe, AIBrix, HPA, KEDA, WVA |

Do not let the four layers each hold inconsistent capacity caps. For example, inference `maxReplicas: 8` with TP=4 per replica may require 32 GPUs; the queue, node pool, and autoscaler must all understand this maximum demand.

## 3. Establish the GPU Resource Pool and Flavors First

Do not express all cards with only `nvidia.com/gpu`. The platform should at minimum distinguish:

- GPU model, GPU memory, and generation;
- Full card, MIG Profile, vGPU, or time-sharing;
- NVLink/NVSwitch, PCIe, and RDMA topology;
- Training pool, online inference pool, and development/testing pool;
- On-demand, reserved, Spot, and fault-isolation states;
- Driver, CUDA, firmware, and health baselines.

It is recommended to maintain stable platform labels:

```text
accelerator.aik8s.run/vendor=nvidia
accelerator.aik8s.run/model=h100-80gb
accelerator.aik8s.run/fabric=nvlink-rdma
accelerator.aik8s.run/pool=h100-rdma-training
accelerator.aik8s.run/lifecycle=reserved
```

Kueue can organize node labels, Taint tolerations, and quotas into user-understandable resource types via `ResourceFlavor`; Volcano can achieve the same through Queue, Node labels, scheduling plugins, and extended resources. Business groups only select platform-published Flavors and do not directly compose arbitrary NodeSelectors.

Development environments can evaluate MIG or shared GPUs to increase small-job density; core online inference and multi-GPU training should default to full cards or validated MIG Profiles. Time-Slicing can increase concurrency but provides no equivalent GPU memory isolation or performance guarantees, and must not be mixed into the same accounting basis as full-card SLOs.

### 3.1 Is It Meaningful to Fork the NVIDIA Device Plugin to Expose Resources by GPU Model

It is meaningful, but not all heterogeneous clusters need it. First distinguish two hardware forms:

| Node Form | Default Problem | Recommended Solution |
| --- | --- | --- |
| GPU models are uniform within each node, but differ across nodes | `nvidia.com/gpu` does not express model, but the node itself can be accurately labeled | GFD Node Label + NodeSelector/Affinity + Kueue ResourceFlavor, usually no fork needed |
| Same node mixes H100, A100, L40S and other models | Scheduler only sees the same `nvidia.com/gpu` count; after node selection, the Device Plugin may allocate the wrong model | Split Extended Resources by model, use DRA that can express attributes, or avoid mixing models within a node |

GPU Feature Discovery adds labels such as Product, Memory, Compute Capability, and MIG Strategy to nodes. For "one card type per node," Pods still request the standard resource and select the model via node labels:

```yaml
spec:
  containers:
    - name: trainer
      resources:
        limits:
          nvidia.com/gpu: 8
  nodeSelector:
    nvidia.com/gpu.product: NVIDIA-H100-80GB-HBM3
```

The actual Product Label depends on the target node; do not guess strings from examples. The NVIDIA GPU Operator includes GFD for automatic discovery and labeling of GPU nodes; the Device Plugin is responsible for reporting counts, health, and container device allocation. The two have different responsibilities; see [NVIDIA GPU Operator](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/) and [NVIDIA Device Plugin](https://github.com/NVIDIA/k8s-device-plugin).

When different models are mixed on the same node, Node Labels can only state "what is in the node," but the standard Device Plugin still exposes a homogeneous `nvidia.com/gpu` resource pool. The Scheduler cannot express "must select two H100s from this node's eight cards, not the adjacent A100s" before Pod binding. In this case, forking the Device Plugin to classify by stable model has direct scheduling value, for example:

```text
accelerator.aik8s.run/h100-80gb: 4
accelerator.aik8s.run/a100-80gb: 4
accelerator.aik8s.run/l40s-48gb: 2
```

Workloads request explicit resources:

```yaml
resources:
  limits:
    accelerator.aik8s.run/h100-80gb: 2
```

This approach lets the Scheduler, ResourceQuota, Kueue/Volcano, and monitoring all see independent counts per model, avoiding the situation where scheduling lands on the correct node but the Kubelet allocates the wrong device.

### 3.2 Key Implementation Points for Device Plugin Forking

The traditional Device Plugin's Resource Name is determined at registration time with the Kubelet. Splitting by model typically means running multiple logical Device Plugin Servers within the same node plugin process:

```text
NVML 枚举 GPU
  → UUID、Product、Memory、Compute Capability、MIG 状态
  → 使用版本化规则归一为平台 Device Class
      ├─ h100-80gb → accelerator.aik8s.run/h100-80gb
      ├─ a100-80gb → accelerator.aik8s.run/a100-80gb
      └─ unknown   → 隔离或只进入管理员测试池
  → 每个 Resource Name 独立执行 Register/ListAndWatch/Allocate
  → Allocate 只返回属于本 Resource Class 的 Device ID/CDI Device
```

The following must be specifically guaranteed:

- The same exclusive GPU can only be counted in one Extended Resource; it must not appear simultaneously in both `nvidia.com/gpu` and a custom resource;
- Model mapping is fixed through configuration and testing, and must not include volatile fields such as Driver or VBIOS;
- Device IDs use UUIDs, not Indexes that may change across reboots;
- Health changes in `ListAndWatch` only affect the corresponding model resource;
- `Allocate` re-validates that the Device ID belongs to the requested Resource Class, rejecting rather than degrading to an arbitrary GPU on failure;
- CDI, environment variables, Mount, and Device Spec behavior remain consistent with the upstream version;
- Unrecognized new cards enter `unknown/quarantine` and must not be silently treated as the lowest or highest model;
- GFD Labels, node Capacity, Exporter metrics, and platform Flavors use the same model normalization rules;
- The fork retains upstream Commits, patch sets, image Digests, compatibility matrices, and regression pipelines.

The real difficulty in forking is not reading the Product Name from NVML, but maintaining a long-term stable resource API. Once resource names enter Deployments, Queues, Quotas, and Helm Charts, renaming causes large numbers of Workloads to go Pending. It is recommended that business users request platform Flavors such as `gpu-training-high`, with Admission/templates mapping to underlying resource names, so that not every project directly depends on GPU marketing names.

### 3.3 Conflicts Between MIG, Time-Slicing, and Custom Model Resources

With `MIG_STRATEGY=mixed`, the NVIDIA Device Plugin already exposes resources such as `nvidia.com/mig-<slice>g.<memory>gb` by MIG Profile. The `renameByDefault` for Time-Slicing/MPS can also rename shared resources to `.shared`; these are existing upstream semantics and should not be re-split again with another set of rules in a fork. See [NVIDIA Device Plugin MIG and Sharing Configuration](https://github.com/NVIDIA/k8s-device-plugin).

It is recommended to keep resource naming dimensions orthogonal:

```text
物理型号：h100-80gb / a100-80gb
切分规格：full / mig-1g.10gb / mig-3g.40gb
共享语义：exclusive / shared
```

But it is not necessary to turn the full Cartesian product of all three dimensions into Extended Resources. Too many resource names cause Queues, Quotas, and application templates to bloat rapidly. The platform should only publish combinations that are actually used and validated for capacity and performance.

Time-Slicing also has a limitation that directly affects the observability discussed in the previous section: NVIDIA documentation explicitly states that when using NVIDIA Device Plugin Time-Slicing, the DCGM Exporter cannot accurately attribute metrics to individual shared containers. Shared development cards cannot use the same per-person utilization ranking and resource reclamation evidence as exclusive inference; see [NVIDIA GPU Time-Slicing Limitations](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/gpu-sharing.html).

### 3.4 When Should You Move to DRA

Extended Resources compress devices into "resource name + integer count," making it difficult to express GPU memory, Compute Capability, NUMA, Fabric, health, and other device attributes. Kubernetes DRA exposes concrete devices and attributes through `ResourceSlice`, and `DeviceClass`/`ResourceClaim` can use CEL to select devices that satisfy conditions. Compared to continuously adding resource names per model, it is better suited for long-term heterogeneous device modeling. [Kubernetes DRA](https://kubernetes.io/docs/concepts/scheduling-eviction/dynamic-resource-allocation/)

NVIDIA also provides a DRA Driver for GPUs; the GPU Operator documentation requires disabling the traditional NVIDIA Kubernetes Device Plugin when using DRA GPU Allocation, to avoid conflicts between the two allocators. See [NVIDIA DRA Driver for GPUs](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/dra-gpus.html).

Before migrating, the following practical boundaries must still be verified:

- Kubernetes and NVIDIA DRA Driver versions and Feature Gates;
- Kueue/Volcano, monitoring, billing, and platform template support for ResourceClaims;
- MIG, sharing, CDI, and topology capabilities;
- The Preemption limitations listed in the current Kubernetes DRA documentation; if resource borrowing depends on high-priority jobs automatically preempting GPUs, full validation must be done first;
- No double-reporting of the same physical GPU during the Device Plugin to DRA transition.

Therefore, forking the Device Plugin by model can be a pragmatic transitional solution for older clusters or mixed-node environments; for new platforms with newer versions, DRA should be evaluated first to avoid maintaining an ever-growing set of custom Extended Resources.

### 3.5 Acceptance Matrix for Scheduling Fork Validation

| Experiment | Expected Evidence |
| --- | --- |
| Mixed node requests H100 and A100 separately | In-container `nvidia-smi -L` UUID and model match the request |
| Request two custom GPU types simultaneously | Scheduler, Allocate, and container CDI injection are all correct |
| One GPU reports a Health Error | It is removed only from the corresponding Resource Class's Allocatable |
| Device Plugin restart | Capacity/Allocatable recovers, no duplicate devices, and running Pods are not disrupted |
| New unrecognized model added | Enters Unknown/Quarantine with an alert, and is not allocated to normal jobs |
| MIG or Sharing configuration switch | Node is Cordoned/Drained first, resource names and counts match expectations, and no double-reporting occurs |
| Kueue/Volcano quota exhausted | Workload waits in the correct Flavor/Queue with observable reasons |
| Rollback to upstream Device Plugin | Custom resource Workloads are safely blocked, and standard resources have no duplicate counting |
| Metrics and billing reconciliation | Resource Name, actual GPU UUID, model, and Owner can be fully correlated |

One final hard constraint to verify: for exclusive full-GPU resources, the sum of Allocatable across all custom models on a node must equal the actual number of allocatable physical GPUs, rather than adding it again while also keeping `nvidia.com/gpu`.

## 4. GPU Resource Borrowing Between Business Groups

### 4.1 Five Basic Quota Quantities

Each business group needs the following policies on each GPU Flavor:

| Field | Meaning |
| --- | --- |
| `guaranteed` / `nominalQuota` | Protected baseline quota under normal conditions |
| `borrowLimit` | Maximum that can be borrowed from the Cohort or the shared pool |
| `lendingLimit` | Maximum this group is allowed to lend out, indirectly defining the retention floor |
| `maxCapacity` | Hard cap preventing a single business group from filling the entire pool |
| `fairShareWeight` | Long-term weight when multiple borrowers compete for idle resources |

Kueue's `ClusterQueue` and `Cohort` natively support Nominal Quota, Borrowing, Lending Limit, hierarchical Cohorts, and Fair Sharing. Borrowers must first declare a quota on the corresponding Flavor, even if the Nominal Quota is zero; the Lending Limit prevents the group's entire guaranteed amount from being lent out. See [Kueue Cohort](https://kueue.sigs.k8s.io/docs/concepts/cohort/) and [ClusterQueue](https://kueue.sigs.k8s.io/docs/concepts/cluster_queue/).

Volcano's hierarchical Queue uses `deserved`, `guarantee`, `capability`, and `reclaimable` to express entitlement, reservation, caps, and cross-queue reclamation, enforced by the Capacity Plugin and Reclaim Action. See [Volcano Hierarchical Queue](https://volcano.sh/docs/keyfeatures/hierarchicalqueue/).

### 4.2 Platform Policy API

A stable self-service API can be provided to business groups:

```yaml
apiVersion: platform.aik8s.run/v1alpha1
kind: GPUQuotaPolicy
metadata:
  name: search-team-h100
spec:
  businessGroup: search
  resourcePool: h100-rdma-training
  guaranteed: 32
  borrowLimit: 16
  lendingLimit: 8
  maxCapacity: 48
  fairShareWeight: 2
  reclaimPolicy:
    gracePeriod: 10m
    onlyPreempt:
      - batch
      - checkpointable
```

This is not an off-the-shelf Kueue or Volcano CRD, but an example enterprise platform API. A Controller is responsible for translating it into actual Queue, Cohort, Priority, and policy objects.

Business groups can customize:

- Borrowing caps within the allowed range;
- Ordering of the group's low-priority tasks;
- Nightly batch task windows;
- Temporary protection leases such as a maximum of 24 hours;
- Whether borrowed tasks are allowed to be reclaimed.

The platform must fix:

- GPU Pool and global totals;
- Minimum guarantee and maximum cap for each group;
- Which Priorities can be created;
- Which workloads are allowed to preempt;
- Maximum grace period and lease duration;
- Protection levels for online inference, regulated tasks, and critical training.

The Admission Webhook must reject unauthorized business groups, unknown Flavors, unbounded leases, borrowing caps exceeded, and forged high Priorities. All policy changes are recorded through GitOps or an audit API, and an impact preview is shown before execution.

### 4.3 Borrowing and Reclamation State Machine

```text
业务组 B 有空闲保证配额
  → B 在 lendingLimit 之内提供可借容量
  → 业务组 A 的低优先级训练借入
  → 账本记录 lender、borrower、Flavor、GPU 数和开始时间

业务组 B 恢复需求
  → 停止向 A 准入新的借用任务
  → 选出超过 A 保证量且优先级最低的候选任务
  → 发送回收事件，进入 gracePeriod
  → 训练 Controller 请求 Checkpoint
  → Checkpoint 成功后停止任务并释放 GPU
  → B 的 Workload 准入
  → A 以后从 Checkpoint 恢复
```

Recommended reclamation order:

1. Borrowed tasks that have not started running and are still in the Queue;
2. Short tasks that can be retried quickly;
3. Training tasks with verified Checkpoints;
4. Low-priority development environments;
5. Only last, long-running tasks that cannot save state.

Online inference replicas should not be regular targets of borrowed-resource reclamation. Inference scale-down is handled by the service controller performing request draining; training reclamation is handled by the queue and training controllers performing Checkpoint. The two must not share a single crude `kubectl delete pod` action.

### 4.4 Kueue or Volcano

| Current foundation | Recommended starting point |
| --- | --- |
| Already using kube-scheduler and wants to add workload admission and Cohort quotas | Kueue |
| Already has stable Volcano Job/Queue and batch scheduling operations experience | Volcano hierarchical Queue |
| Complex Gang, DRF, backfill, and unified AI/HPC batch scheduling | Volcano |
| Kubernetes-native integration with Trainer, JobSet, RayJob, etc. takes priority | Kueue |

Do not let Kueue and Volcano both own admission, Suspend, PodGroup recovery, and preemption for the same Workload. In combined deployments, clearly designate one as responsible for admission and the other only for placement of already-admitted Pods, and validate the state machine through failure experiments.

## 5. Real-Time Elasticity for Inference Services

### 5.1 Don't Look Only at CPU

Scaling signals for large-model inference include at least:

| Metric | Description | Suitable action |
| --- | --- | --- |
| Waiting request count and queue time | Most direct signal of insufficient capacity | Rapid scale-out |
| TTFT P95/P99 | User experience waiting for the first token | Scale-out, routing, or Prefill optimization |
| TPOT/ITL P95/P99 | Whether streaming generation is smooth | Concurrency, batching, and Decode optimization |
| KV Cache utilization | Whether approaching the concurrency capacity limit | Scale-out or adjust batching parameters |
| Running/Waiting requests | Current batch and queue pressure | Scale in/out and load balancing |
| Prompt/Generation tokens/s | Real workload throughput | Capacity and cost accounting |
| GPU memory, SM, and power consumption | Hardware-side load | Validate application metrics against hardware state |
| Error, timeout, and rejection rates | Whether overload or dependency failure occurred | Load shedding, circuit breaking, rollback |

vLLM exposes metrics such as Running/Waiting Request, KV Cache, TTFT, Inter-token Latency, Queue Time, Token Counter, and Request Success through `/metrics`; see [vLLM Metrics](https://docs.vllm.ai/en/stable/design/metrics/).

### 5.2 Inference Scaling Strategies

```yaml
apiVersion: platform.aik8s.run/v1alpha1
kind: InferenceScalingPolicy
metadata:
  name: customer-service-llm
spec:
  workloadRef:
    kind: InferenceService
    name: customer-service-llm
  replicaShape:
    tensorParallelSize: 4
    gpuPerReplica: 4
  minReplicas: 1
  maxReplicas: 8
  scaleUp:
    queueDepthPerReplica: 8
    ttftP95: 1500ms
    kvCacheHighWatermark: 85
    stabilizationWindow: 30s
  scaleDown:
    queueDepthPerReplica: 1
    stabilizationWindow: 10m
    drainTimeout: 20m
```

This is likewise an example platform API. A Controller can translate it into:

- HPA/KEDA for KServe Standard Mode;
- Request-driven elasticity and Scale-to-zero for KServe Knative Mode;
- HPA, KEDA, or Workload Variant Autoscaler for KServe LLMInferenceService;
- AIBrix Autoscaler and routing policies;
- Ray Serve AutoscalingConfig;
- Plain Deployment + KEDA Prometheus Scaler.

KServe Standard Mode can use HPA and optional KEDA, while Knative Mode supports request-driven scaling and Scale-to-zero; the two modes differ in cold start, network complexity, and runtime overhead. See [KServe Control Plane](https://kserve.github.io/website/docs/concepts/architecture/control-plane). AIBrix also designs both reactive and proactive scaling paths based on historical prediction and offline Profiling; see [AIBrix Autoscaler](https://aibrix.readthedocs.io/latest/designs/aibrix-autoscaler.html).

### 5.3 One Replica Is Not Necessarily One GPU

If a model replica uses TP=4, then `1 → 2` replicas require adding four GPUs at once that satisfy topology constraints. TP=8 or multi-node Prefill/Decode separation also requires Gang, rack, RDMA, and Worker role constraints. The elasticity controller must pass the replica Shape to the capacity and scheduling layers; it cannot treat HPA Desired Replicas alone as if the capacity already exists.

Online inference needs at least three types of capacity:

- `serving-floor`: GPUs actually occupied by the current minimum replicas;
- `burst-headroom`: GPUs reserved or pre-warmed for rapid scale-out;
- `borrowable-cold-capacity`: GPUs that can be temporarily lent to training, but whose reclamation speed cannot satisfy second-level scale-out.

If all idle GPUs are lent to non-preemptible training, inference scale-out can only wait for training to finish or new nodes to arrive, and the platform has no real online SLO guarantee.

### 5.4 Safe Scale-In

The scale-in order should be:

```text
选择候选副本
  → Router 将权重降为 0
  → 停止接收新请求
  → 等待流式请求和长上下文 Decode 结束
  → 达到 drainTimeout 后按策略终止或迁移
  → 删除 Pod，释放完整 Replica Shape
```

Also verify model loading, CUDA Graph, Compile Cache, and local model cache. Large models may take minutes to start from zero; core services typically keep at least one hot replica; only low-frequency models where cold-start cost and business wait time are acceptable are suitable for Scale-to-zero.

## 6. Tidal and Scheduled Scaling

Tidal strategies address predictable daily cycles, while real-time metrics handle burst traffic beyond predictions:

```text
工作日 07:30
  → 停止准入新的低优先级长训练
  → 通知借用方并触发 Checkpoint

工作日 08:30
  → 提前加载白天模型与 Compile Cache
  → 推理最小副本由 2 提高到 6
  → 收紧训练池可借出的推理预留容量

工作日 09:00—20:00
  → 实时弹性继续根据 Queue/TTFT 在 6—12 副本之间变化

工作日 20:00
  → 推理最小副本降到 1—2
  → 空闲 GPU 进入可借池
  → 夜间训练队列开始准入
```

KEDA Cron Scaler defines time windows and the Desired Replicas within each window; outside the window, it can be combined with `minReplicaCount` and other Triggers to scale in; see [KEDA Cron Scaler](https://keda.sh/docs/latest/scalers/cron/). The platform should adopt:

```text
实际副本下限 = max(潮汐最低副本, 实时流量计算结果)
```

rather than letting Cron fix the replica count and suppress real-time traffic.

The platform can define:

```yaml
apiVersion: platform.aik8s.run/v1alpha1
kind: TidalPolicy
metadata:
  name: weekday-serving-training
spec:
  timezone: Asia/Shanghai
  windows:
    - name: daytime-serving
      start: "30 8 * * 1-5"
      end: "0 20 * * 1-5"
      inferenceReplicaFloor: 6
      prewarmBefore: 30m
      trainingBorrowLimit: 8
    - name: nighttime-training
      start: "0 20 * * 1-5"
      end: "30 7 * * 2-6"
      inferenceReplicaFloor: 1
      trainingBorrowLimit: 40
  reclaim:
    checkpointBefore: 30m
    gracePeriod: 10m
```

This is not a simple CronJob. The Tidal Controller needs to check average model loading time, current requests, remaining training time, Checkpoint status, GPU health, and available topology; if pre-warming fails, it must protect existing replicas and alert, and must not scale down healthy services just to meet a planned number.

## 7. GPU Monitoring, Visualization, and Observability

### 7.1 Observability Architecture

```text
GPU/节点
  DCGM Exporter / 厂商 Exporter / Node Exporter
                        │
Kubernetes 与控制器     │
  kube-state-metrics / Kueue / Volcano / KServe / KEDA
                        │
训练与推理应用           │
  Trainer / NCCL / vLLM / AIBrix / Gateway Metrics
                        ▼
Prometheus per cluster → Thanos/Mimir 长期存储
                        │
                        ├→ Grafana Dashboard
                        ├→ Alertmanager
                        └→ 容量与 FinOps Recording Rules

Gateway / Controller / Model Server Logs
  → OpenTelemetry Collector
      ├→ Loki/Elasticsearch
      └→ Tempo/Jaeger
```

NVIDIA recommends deploying DCGM Exporter on Kubernetes GPU nodes, with Prometheus scraping and Grafana displaying. The Exporter can use Kubelet PodResources to associate GPU/MIG metrics with Pod, Namespace, and Container, and also supports GPU UUID, MIG, DRA Claim, XID, and health labels. See [DCGM Exporter](https://docs.nvidia.com/datacenter/dcgm/latest/gpu-telemetry/dcgm-exporter.html) and [Metrics Reference](https://docs.nvidia.com/datacenter/dcgm/latest/reference/dcgm-exporter-metrics.html).

### 7.2 Unified Label Contract

Without label attribution, GPU metrics can only answer "which card is busy," not "which business group borrowed it and why." Platform objects should at least unify the following low-cardinality labels:

```text
cluster
region
environment
business_group
cost_center
owner_team
queue
priority_class
workload_type        # training / inference / notebook / batch
workload_uid
service
model
model_version
resource_pool
gpu_model
gpu_uuid
mig_profile
```

After DCGM metrics are natively attributed to Pods, associate business group, Queue, and model through Kube State Metrics, controller metrics, or Recording Rules. Do not copy Prompt, Request ID, raw user ID, or the full Pod label set into Prometheus; high-cardinality and sensitive fields go into Traces or structured logs.

### 7.3 Why Fork DCGM Exporter for User and Team Attribution

DCGM Exporter can map GPU or MIG Devices to Kubernetes Pod, Namespace, and Container through Kubelet PodResources. Newer versions can optionally add attribution information such as Pod Labels, DRA Claims, and HPC Jobs. However, enterprise resource governance usually also needs stable `business_group`, `owner`, `cost_center`, `queue`, and platform Workload UID; these fields may not all exist in DCGM's native mapping, or their names may not match the company's organizational model.

A direct idea is to call the Kubernetes API to query Labels by Pod name when the Exporter generates each metric. This approach works for small-cluster demos, but becomes very risky at scale:

- Prometheus scrapes every 15–30 seconds, and each GPU node and the large number of Metrics can amplify queries;
- `/metrics` latency is coupled to API Server latency; control-plane jitter can take GPU monitoring down with it;
- The Exporter on every node needs Pod read permissions, expanding the RBAC and Token exposure surface;
- Hardware metrics are most needed when the API Server fails, yet the Exporter may become unavailable because label enrichment fails;
- Pod names are reused; asynchronous queries and cache invalidation can attribute old users to new Pods;
- Adding arbitrary Pod Labels in full to metrics causes Prometheus Cardinality explosion.

A more stable principle in practice is: **forbid synchronous API Server queries on the `/metrics` hot path; attribution data must first enter memory or a local snapshot.**

### 7.4 An Engineered Attribution Enrichment Pipeline

```text
Admission Webhook
  → 校验并写入受控标签：business_group / owner_id / cost_center

中心 Metadata Sync Controller
  → 使用一次共享 Informer/List-Watch 读取必要 Pod 元数据
  → 以 Pod UID 为主键生成每节点映射快照
  → 只保留允许进入指标的字段

节点上的 DCGM Exporter 二开版本
  → Kubelet PodResources：GPU UUID/MIG Device → Pod/Container
  → 本地映射快照：Pod UID → Team/User/Queue/Workload
  → 在 Prometheus Sample 输出前追加受控 Label
  → Scrape 全程不访问 API Server
```

The central synchronizer still accesses the API Server, but it uses a shared Informer and local cache to centralize and deduplicate read pressure and decouple it from Exporter Scrapes; this is fundamentally different from each node issuing an immediate GET on every Scrape. In even stricter environments, a node Agent can obtain the mapping from a controlled message stream or signed snapshot, giving the Exporter no Kubernetes API credentials at all.

The Exporter fork point is usually placed after "device already mapped to Pod/Container" and before "final Prometheus Label encoding":

```text
GPU UUID / MIG GI-CI
  → PodResources 找到 Pod UID、Namespace、Container
  → ownershipCache.Lookup(podUID)
  → 追加 business_group、owner_id、cost_center、queue、workload_uid
  → Prometheus exposition
```

It is recommended to allow only the following controlled fields into GPU Metrics:

```text
business_group
owner_id          # 稳定账号 ID，不使用姓名或邮件
cost_center
queue
workload_type
workload_uid
model
model_version
```

Engineering details determine whether attribution is trustworthy:

- Use Pod UID as the primary key; Pod Name is for display only;
- Replace the mapping snapshot atomically; never read a half-written file;
- Keep a short Tombstone after Pod deletion so the last few Samples do not lose attribution;
- On cache miss, output `mapping_status="unknown"`; do not drop hardware metrics;
- Record effective time for organizational relationship changes; historical billing must not be rewritten by new department relationships;
- For MIG, save GPU UUID, GI/CI, or Profile together; do not rely only on node and GPU Index;
- Continue outputting the latest snapshot across Exporter restarts, Metadata Sync interruptions, and API Server unavailability;
- Limit allowed Label Value length and characters to prevent metric injection and cardinality runaway.

An example of an enriched metric:

```text
DCGM_FI_DEV_GPU_UTIL{
  UUID="GPU-<uuid>",
  namespace="training",
  pod="train-job-worker-0",
  business_group="search",
  owner_id="u-1042",
  cost_center="cc-ai-search",
  queue="search-training",
  workload_uid="wl-7d8f"
} 7
```

The value of this metric is not that the Labels look richer, but that subsequent low-utilization scans, department reports, and quota reclamation only query Prometheus, without re-accessing the Kubernetes API for every analysis.

### 7.5 How to Validate Attribution Enrichment

Do not just look at a single labeled metric. At least verify:

1.  After Pod startup, recreation, or cross-node scheduling, the ownership mapping between GPU UUID and Pod UID changes in a timely manner;
2.  Two Pods with the same name but different UIDs never mix user attribution;
3.  Every Device in MIG, multi-container Pods, and multi-GPU Pods is correctly attributed;
4.  After a Pod is deleted, the final segment of metrics is still attributed to the original Workload, and cleanup proceeds normally after the Tombstone expires;
5.  When the API Server is temporarily unavailable, Exporter `/metrics` latency and availability are unaffected;
6.  After Metadata Sync recovers, the snapshot catches up without generating duplicate Series in bulk;
7.  The Exporter has no unnecessary Cluster-wide Secret, ConfigMap, or Pod write permissions;
8.  Before and after enabling attribution Labels, Prometheus Active Series, memory, and query time growth stay within budget.

You can first inspect the raw metrics:

```bash
kubectl -n gpu-monitoring port-forward daemonset/dcgm-exporter 9400:9400
curl -s http://127.0.0.1:9400/metrics | grep '^DCGM_FI_DEV_GPU_UTIL' | head
```

Then use PromQL to check for unknown attribution and one card with multiple attributions:

```promql
count by (mapping_status) (DCGM_FI_DEV_GPU_UTIL)
```

```promql
count by (cluster, UUID, pod, business_group, owner_id) (
  DCGM_FI_DEV_GPU_UTIL
)
```

Metric names, UUID Label casing, and Pod Label names depend on the DCGM Exporter version and must follow the actual `/metrics` output. The Kubernetes, Pod UID, Pod Label, MIG, vGPU, and DRA Label capabilities currently documented by NVIDIA can be referenced in [DCGM Exporter Metrics](https://docs.nvidia.com/datacenter/dcgm/latest/reference/dcgm-exporter-metrics.html).

### 7.6 Six Layers of Core Metrics

#### Hardware Health

- GPU, GPU memory, SM, Tensor, power, and temperature;
- SM/Memory Clock and downclocking reasons;
- PCIe, NVLink, NVSwitch traffic and link status;
- ECC SBE/DBE, XID, Driver, and GPU Health;
- GPU UUID, MIG Profile, DRA Device, and node;
- Whether DCGM Exporter, Device Plugin, and Driver are healthy.

#### Kubernetes and Capacity

- Total, allocatable, and requested capacity by GPU model, Pool, node, and MIG Profile;
- Pending Pod/Workload count, wait time, and unschedulable reasons;
- GPU fragmentation: total idle capacity is sufficient but cannot form a TP/Gang Shape;
- Unschedulable nodes, Taints, Device Plugin, and DRA Claim status;
- Node join, initialization, warm-up, isolation, and recovery time.

#### Quota and Borrowing

- Business group Guaranteed, Used, Borrowed, Lent, Borrowable;
- Cohort/parent-child Queue usage and Fair Share;
- Borrow duration, borrowed GPU-hours, and capacity about to be reclaimed;
- Admission Wait, Reclaim, Preemption, and recovery counts;
- Checkpoint success rate, duration, and effective loss after preemption.

#### Training Efficiency

- Step Time, Samples/s, Tokens/s, and GPU-hours;
- MFU or a defined approximate effective compute ratio;
- DataLoader/Storage Wait, CPU Feed, and network wait;
- GPU utilization, GPU memory, and Step Time skew across ranks;
- NCCL Collective latency, errors, and retries;
- Checkpoint size, write throughput, interval, and recovery duration.

High GPU utilization does not equal effective training. A faulty data pipeline, redundant computation, frequent recomputation, or communication busy-wait can also keep devices at high load; training progress and effective throughput must be observed simultaneously.

#### Inference SLO

- RPS, concurrency, success rate, timeout, and rejection;
- TTFT, TPOT/ITL, Queue Time, and end-to-end latency P50/P95/P99;
- Running/Waiting Requests, Batch size, and scheduling preemption;
- Prompt/Generation tokens/s and tokens/GPU/s;
- KV Cache usage, Prefix Cache hit rate, and eviction;
- Desired/actual replica count, scale-out duration, cold start, and drain duration;
- Model version, quantization, TP/PP/DP/EP, and Router backend distribution.

#### FinOps and Business Value

- GPU-hours by business group, Queue, model, and service;
- Idle GPU-hours that are allocated but underutilized;
- Effective GPU-hours that meet SLO;
- GPU cost per million input/output tokens;
- Cost per training Run, successful Checkpoint, and effective token;
- Additional completed tasks enabled by borrowing and peak capacity that avoided procurement.

### 7.7 Scheduled Scans for Low-Utilization Workloads

Real-time Alertmanager suits immediate failures such as XID, temperature, and inference SLO; "who has been occupying a GPU for a long time with low utilization" is better handled by scheduled governance scans. The reason is that training goes through model loading, data preprocessing, Checkpoint, validation, and phase transitions; a short window of zero GPU Util does not imply waste.

Recommended scan pipeline:

```text
CronJob / Governance Controller 每 15—30 分钟运行
  → 查询 Prometheus，而不是逐 Pod 查询 API Server
  → 按 business_group / owner_id / workload_uid 聚合
  → 检查连续时间窗、显存、功耗、训练进度和应用指标
  → 应用白名单、启动宽限、Checkpoint 与推理保底例外
  → 写入告警状态，完成去重和升级
  → 发送个人通知、团队汇总和平台治理事件
```

Policy example:

```yaml
apiVersion: platform.aik8s.run/v1alpha1
kind: LowUtilizationPolicy
metadata:
  name: training-default
spec:
  match:
    workloadType: training
  window: 60m
  thresholds:
    averageGpuUtilization: 10
    averageMemoryUtilization: 15
  startupGracePeriod: 30m
  checkpointGracePeriod: 20m
  notify:
    first: owner
    after: 2h
    escalateTo: business-group-admin
    repeatInterval: 6h
  excludeWhen:
    - label: platform.aik8s.run/capacity-role
      value: serving-floor
    - annotation: platform.aik8s.run/keep-running-until
```

This is also a platform policy example. In a real implementation, at minimum combine the following judgments:

| Signal | Why it is needed |
| --- | --- |
| GPU allocated duration | Excludes just-started and short tasks |
| GPU Util time window | Identifies sustained low compute load, not transient idle |
| GPU memory usage and power | Distinguishes resident models, erroneous idle occupation, and real compute |
| Whether training Step/Token is advancing | GPU low but the task may still be in CPU/Data phase |
| vLLM Waiting/Running Requests | Low utilization of online standby replicas may be a normal SLO cost |
| Checkpoint/evaluation status | Avoids false positives during save and validation phases |
| Borrowed or guaranteed quota | Borrowed resources and the group's guaranteed resources can use different thresholds |
| Explicit protection lease | Provides time-limited, auditable exceptions for nightly tasks |

Scan results must carry state; do not repeatedly bombard the same user every 15 minutes:

```text
Detected
  → 首次通知 Owner，附 Dashboard 与自查建议
  → 用户恢复利用率：Resolved
  → 持续 2h：Escalated，通知团队管理员
  → 使用借用 GPU 且超过策略：ReclaimCandidate
  → Checkpoint 成功并经过审批：回收或降级
```

Alert messages must include at least: business group, user, Workload, GPU model/count, running duration, continuous low-utilization duration, average GPU/GPU memory utilization, whether borrowed quota is used, Dashboard link, suggested action, and exception application entry. Sending only "GPU utilization below 10%" will almost never produce effective action.

### 7.8 How Department and Individual Rankings Can Be Fair

Once GPU usage is transparent, rankings can be shown by department and individual:

- Allocated GPU-hours;
- Effective GPU-hours;
- Low-utilization GPU-hours;
- Borrowed/Lent GPU-hours;
- Queue Wait and recomputation loss after reclamation;
- Effective training throughput or per-token inference cost;
- Low-utilization alert count, duration, and resolution completion rate.

Rankings are very helpful for resource control: the platform can find specifications that "request a lot but never run," department administrators can see internal imbalance, and quota reviews shift from impressions to evidence. But rankings must first apply fairness filters:

- Online inference `serving-floor` is counted separately as SLO retention cost;
- Model loading, compilation, Checkpoint, evaluation, and failure recovery windows are not counted as ordinary waste;
- MIG, Time-Slicing, and full cards are compared separately;
- Different GPU models are displayed separately by GPU-hours and cost; one L20 cannot be simply added to one H100;
- Set a minimum sample size so users who ran for ten minutes do not land at extreme positions;
- Display both absolute waste and low-utilization ratio simultaneously, so small users are not over-amplified by a high ratio;
- Rankings are primarily used for Showback, coaching, and specification optimization; penalties and hard quota adjustments require human review and an appeal channel.

Two outputs are recommended:

1.  **Team public leaderboard**: department-level GPU-hours, efficiency rate, borrowing contribution, and improvement trends;
2.  **Administrator detail list**: evidence down to Owner/Workload, visible only to the individual, department administrators, and the platform team.

This creates resource governance pressure without turning the monitoring platform into a context-free "naming and shaming system."

### 7.9 PromQL Examples

vLLM TTFT P95:

```promql
histogram_quantile(
  0.95,
  sum by (le, model_name) (
    rate(vllm:time_to_first_token_seconds_bucket[5m])
  )
)
```

Waiting requests by model:

```promql
sum by (model_name) (vllm:num_requests_waiting)
```

Highest GPU node temperature:

```promql
max by (Hostname) (DCGM_FI_DEV_GPU_TEMP)
```

Actual metric names and Labels vary with DCGM, vLLM, and deployment configuration. Before going live, use the target version `/metrics` output as the source of truth; Dashboards and alerts use stable platform names through Recording Rules so upstream upgrades do not break all queries directly.

### 7.10 Six Categories of Grafana Dashboards

1.  **GPU NOC**: XID, ECC, temperature, power, downclocking, NVLink, and failed nodes;
2.  **Capacity and Fragmentation**: capacity by model, Pool, topology, MIG, and node, plus Shapes that cannot be composed;
3.  **Business Group Resource Bank**: Guaranteed, Borrowed, Lent, Wait, Reclaim, and Fair Share;
4.  **Training Jobs**: queue, Gang, throughput, rank skew, NCCL, and Checkpoint;
5.  **Inference SLO**: TTFT, TPOT, Queue, KV Cache, tokens/s, scaling, and model version;
6.  **FinOps**: GPU-hours, Idle Waste, per-token cost, and business group Showback/Chargeback.

Every chart should support drill-down from Cluster → Pool → Business Group → Queue/Service → Workload/Pod → GPU UUID, while retaining the time range and change events.

### 7.11 Alert Severity Levels

| Level | Example |
| --- | --- |
| P0 | Fatal XID, ECC DBE, large-scale GPU loss, core inference unavailable, quota control plane stops admission |
| P1 | TTFT/TPOT persistently violating SLO, queue growing rapidly, scale-out with no available GPU, NVLink/RDMA failure, reclamation failure |
| P2 | GPU allocated but persistently underutilized, severe fragmentation, training queue timeout, borrowing near the reclamation window |
| Governance | Borrowing cap exceeded, protection lease about to expire, policy drift, missing Owner/Cost Center, audit write failure |

Alerts must carry business impact and a handling entry point. For example, "low GPU Util" is not P1; "core service TTFT exceeding threshold, Waiting Requests growing, and scale-out failing due to insufficient H100 topology" is an actionable alert.

## 8. Enterprise Value and KPIs

### 8.1 Value Chain

| Enterprise Value | Platform Mechanism | Quantifiable Metric |
| --- | --- | --- |
| Improve effective utilization of expensive GPUs | Quota borrowing, tidal scheduling, idle reclamation | Effective GPU Util, Idle GPU-hours, borrowed GPU-hours |
| Reduce departmental resource silos | Cohort/hierarchical Queue and shared pool | Shared pool hit rate, peak capacity reuse rate |
| Guarantee critical inference SLO | Service retention, Headroom, application metric elasticity | TTFT/TPOT, error rate, scale-out failure rate due to no capacity |
| Reduce inference cost | Off-peak scale-down, model routing, per-token accounting | Cost per million tokens, tokens/GPU/s |
| Shorten training delivery cycle | Gang, quota admission, borrowing, and Checkpoint | Queue Wait, Job Completion, preemption recovery time |
| Improve hardware reliability | DCGM health, XID/ECC, and automatic isolation | Fault detection time, isolation time, repeat fault rate |
| Establish cost accountability | Business group Showback/Chargeback | GPU-hours, Idle Waste, budget variance |
| Strengthen governance | Policy guardrails, leases, and full audit | Override blocking, policy drift, audit coverage |

### 8.2 Suggested Formulas

```text
分配率 = 已分配 GPU-hours / 可提供 GPU-hours

有效利用率 = 产生有效训练或满足推理 SLO 的 GPU-hours
             / 已分配 GPU-hours

借用率 = 借用 GPU-hours / 可借 GPU-hours

推理单位成本 = 推理 GPU 成本 / 百万有效 Token

空闲浪费 = 已分配但低利用且无有效任务进展的 GPU-hours
```

Do not commit to "GPU utilization reaching 80%" up front. First collect a two-to-four-week baseline by GPU Pool and workload, then set targets. The reasonable utilization and SLO for interactive development, training, online inference, and offline inference are completely different.

## 9. Phased Implementation

### P0: Data and Label Baseline

- Deploy or verify GPU Operator, DCGM Exporter, Prometheus, and Grafana;
- Establish business group, Cost Center, Queue, model, and GPU Pool labels;
- Integrate Kube State Metrics, queue, training, and inference metrics;
- Observe only for two to four weeks without changing production scheduling;
- Output baselines for GPU-hours, queuing, SLO, fragmentation, and faults.

### P1: Quota Borrowing MVP

- Choose either Kueue or Volcano and complete control-plane validation;
- Integrate two business groups and one GPU Flavor;
- Configure guaranteed amounts, borrowing caps, lending floors, and hard limits;
- Only allow checkpointable low-priority tasks to use borrowed capacity;
- Complete borrowing ledger, notification, reclamation, and recovery drills.

### P2: Real-Time Inference Elasticity

- Select one service with short cold start and one large-model service as pilots;
- Integrate Gateway, vLLM, and DCGM metrics;
- Drive scale-out using Queue, TTFT, and KV Cache;
- Validate no-capacity, model loading failure, long-request drain, and rollback;
- Establish service SLO and capacity Headroom.

### P3: Tidal Coordination

- Establish weekday daytime inference and nighttime training policies;
- Pre-warm based on model loading time;
- Stop long-training admission and trigger Checkpoint before peak hours;
- Compare predicted capacity with actual traffic, and gradually adjust windows and margins;
- Retain manual freeze and one-click rollback to fixed replicas.

### P4: Self-Service and FinOps

- Business groups self-adjust borrowing and tidal policies within guardrails;
- Provide impact preview, approval, lease, and audit;
- Output Showback/Chargeback and per-token cost;
- Guide procurement and model optimization based on queuing, fragmentation, SLO, and cost.

## 10. Mandatory Failure Experiments

| Experiment | Validation Goal |
| --- | --- |
| Two groups simultaneously borrow the last batch of GPUs | Whether Fair Share and caps work per policy |
| The original business group suddenly restores guaranteed demand | Whether reclamation, Checkpoint, notification, and recovery are complete |
| Checkpoint fails or times out | Whether preemption is stopped and alerts are raised correctly, rather than deleting the task outright |
| Inference Waiting Requests grow rapidly | Whether the Autoscaler scales out in time and obtains the full Replica Shape |
| HPA has Desired Replica but the cluster has no GPU | Whether UI and alerts can distinguish service elasticity from capacity shortage |
| Tidal pre-warm model download fails | Whether old replicas are retained and dangerous scale-down is stopped |
| Long streaming requests encounter scale-down | Whether the Router first drains traffic and waits for drain completion |
| GPU experiences XID/ECC DBE | Whether the node is isolated, erroneous allocations are terminated, and affected tasks are correlated |
| Prometheus or Controller restarts | Whether policy state, counters, and audit can recover |
| Business group forges high Priority or labels | Whether Admission rejects and records a security event |
| API Server outage but DCGM Exporter healthy | Whether `/metrics` continues using the local snapshot and Scrape is unaffected by the control plane |
| Pod recreated with the same name or scheduled across nodes | Whether User/Team attribution updates by Pod UID without mixing accounts |
| Training is in loading, Checkpoint, or evaluation phase | Whether the low-utilization scan filters correctly and avoids false positives |
| The same low-utilization task hits multiple times consecutively | Whether alerts are deduplicated, escalated, and closed after recovery |

## 11. Common Anti-Patterns

- Only building a "GPU total and utilization" Dashboard, without business group, Queue, model, and cost attribution;
- Every Prometheus scrape synchronously queries the API Server from the Exporter to supplement Pod Labels;
- Adding all Pod Labels indiscriminately to DCGM metrics, causing Series and query cost explosion;
- Attributing users only by Pod Name, causing misattribution after Pod recreation;
- Low-utilization scanning without exceptions for startup, model loading, Checkpoint, and inference floor;
- Repeated notifications on every scan, without alert state, deduplication, escalation, and recovery;
- Using CPU HPA to scale vLLM, without looking at request queues, TTFT, and KV Cache;
- Lending all idle inference GPUs to non-preemptible training, causing burst traffic to be unable to scale;
- Business groups can create arbitrary PriorityClass, eventually everyone declares the highest priority;
- No Checkpoint before preemption; the GPU-hours saved by mutual lending is less than the recomputation loss;
- Cron directly overrides replica count, causing the real-traffic Autoscaler to fail;
- Scaling down directly deletes inference Pods with long-running requests;
- Prometheus uses Request ID, User ID, and full Pod Labels, causing high cardinality;
- Time-Slicing, MIG, and full-GPU use the same performance SLO;
- Mixing different models within a node while exposing only one `nvidia.com/gpu`, mistakenly believing Node Labels can select a specific physical GPU;
- The same GPU reported simultaneously through upstream resource names, custom resource names, or DRA, causing capacity doubling;
- Custom resource names directly contain volatile Product Strings, causing many Workloads to go Pending after upgrades;
- The same Workload has Suspend/Priority modified by Kueue, Volcano, and a self-developed Controller simultaneously;
- Operating old clusters with the latest documentation fields, without pinning versions and verifying Feature Gates.

## 12. Go-Live Acceptance Checklist

- [ ] GPU Pool, Flavor, topology, driver, and health status have a unified source;
- [ ] Same-model nodes prioritize GFD + ResourceFlavor; only develop a custom Device Plugin for mixed models or explicit device-level selection needs;
- [ ] Custom Extended Resources and `nvidia.com/gpu`/DRA do not report the same physical GPU repeatedly;
- [ ] Verify requested model matches container actual device by UUID, covering Health, restart, MIG, sharing, and rollback;
- [ ] Custom resource names are versioned platform APIs; applications prioritize referencing stable Flavor over volatile Product Strings;
- [ ] Each business group has guaranteed quota, borrowing ceiling, lending floor, hard ceiling, and Owner;
- [ ] Kueue or Volcano admission and preemption ownership is unique;
- [ ] Borrowed resources only carry workloads allowed to be reclaimed;
- [ ] Training reclamation only executes after successful Checkpoint; failure paths have been rehearsed;
- [ ] Online inference has clear Floor, Burst Headroom, and maximum Replica Shape;
- [ ] Scaling uses Queue, TTFT, KV Cache, and other application metrics, not just CPU/GPU Util;
- [ ] Router removes traffic and completes request draining before scaling down;
- [ ] Tidal strategy does not override the real-time Autoscaler; warm-up failure can safely fall back;
- [ ] DCGM metrics can be associated with Pod, business group, Queue, model, and GPU UUID;
- [ ] Exporter `/metrics` hot path does not synchronously query the API Server; it can still output hardware metrics during control plane failure;
- [ ] User/Team mapping is based on Pod UID and local atomic snapshots, with Unknown, Tombstone, and recovery semantics;
- [ ] Attribution Labels use an allowlist, and Prometheus Active Series and memory growth are verified;
- [ ] Low-utilization scanning uses continuous time windows, application progress, exception policies, and alert state, not instantaneous GPU Util naming;
- [ ] Department/personal rankings distinguish inference floor, startup, Checkpoint, GPU model, and minimum sample size;
- [ ] Training throughput, inference SLO, quota ledger, and FinOps each have separate Dashboards;
- [ ] XID, ECC, no-capacity scaling, SLO, and governance events have tiered alerts;
- [ ] Prompt, user identity, and Request ID do not enter Prometheus high-cardinality labels;
- [ ] Policy changes, borrowing/lending, reclamation, preemption, leases, and manual operations are all auditable;
- [ ] Baseline has been collected, and platform value is verified with quantifiable KPIs.

## 13. Further Reading

- [GPU Scheduling, Sharing, and DRA](../gpu-scheduling.md)
- [Queues, Multi-Tenancy, and Quotas](../queue-multitenancy.md)
- [Elastic Scaling and GPU Capacity Provisioning](../scheduling/autoscaling.md)
- [Distributed Training](../distributed-training.md)
- [LLM Inference](../llm-inference.md)
- [GPU, Training, and Inference Observability](../observability.md)
- [Kueue vs. Volcano Comparison Experiment](kueue-vs-volcano.md)
- [Spot GPU and Checkpoint Recovery Experiment](spot-checkpoint.md)
