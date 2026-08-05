---
title: GPU 资源银行与潮汐推理平台实践蓝图
description: 用 Kueue 或 Volcano 实现业务组 GPU 配额互借，结合 KServe、AIBrix、KEDA 与 vLLM 构建实时和定时弹性，并建立从硬件健康到单位 Token 成本的可观测闭环
status: blueprint
last_reviewed: 2026-08-05
---

# GPU 资源银行与潮汐推理平台实践蓝图

企业 GPU 平台最难的不是列出多少张卡，而是在三个目标之间持续做可解释的取舍：业务组需要确定性的资源保障，空闲 GPU 又不能长期躺在部门孤岛里，在线推理还必须在流量到达前拿到容量。

这要求平台同时具备：

- 业务组保证配额、借入上限、借出底线与公平共享；
- 训练任务的 Gang、优先级、Checkpoint 与有序回收；
- 推理服务基于请求队列、TTFT、KV Cache 等指标扩缩容；
- 白天推理、夜间训练等潮汐策略；
- GPU 健康、任务效率、推理 SLO、配额账本与成本的统一观测；
- 策略自助、平台保护线、审批、审计和复盘。

平台不应重新开发一个 GPU 调度器。更合适的做法是定义稳定的企业策略 API，再由 Controller 把它翻译成 Kueue、Volcano、KServe、AIBrix、KEDA、PriorityClass 和监控规则。

这篇文章不只罗列组件。实践中最有价值的工作往往发生在组件接缝处：DCGM 指标怎样稳定归属到用户和团队，为什么不能在每次 Prometheus Scrape 时查询 API Server，怎样定时扫描“占着 GPU 但长期低利用”的工作负载，以及怎样把结果变成可解释的个人/部门 Showback，而不是一张没有行动入口的 Grafana 图。

## 1. 目标、非目标与成功标准

### 1.1 目标

平台需要回答以下问题：

1. 每个业务组至少保证多少 H100、A100 或其他 GPU？
2. 空闲时最多允许其他组借走多少，原业务组能保留多少安全余量？
3. 借出容量被需要时，先停止谁、通知多久、怎样保存进度？
4. 某个推理服务当前需要几个副本，扩容是否有完整 GPU 拓扑？
5. 每天固定流量高峰前，应该提前多久预热模型？
6. GPU 看起来很忙时，训练和推理是否真的产生有效吞吐？
7. 每个业务组、模型和服务消耗了多少 GPU-hours，换来了什么业务 SLO？

### 1.2 非目标

- 不让业务组直接修改节点标签、调度器配置或全局 PriorityClass；
- 不用一个百分比承诺所有 GPU 型号都达到相同利用率；
- 不把 Time-Slicing 当作显存和故障隔离；
- 不假设 HPA 增加副本就一定存在可用 GPU；
- 不以强制删除 Pod 代替 Checkpoint、请求排空和回收协议；
- 不在 Prometheus 标签中保存 Prompt、用户原始身份或 Request ID。

### 1.3 成功标准

MVP 至少证明：

- 两个业务组能够在保证量之上互借 GPU，且不突破平台上限；
- 原业务组恢复需求时，借用任务按规则让出容量并能从 Checkpoint 恢复；
- 一个 vLLM 推理服务能根据真实服务指标扩容和安全缩容；
- 潮汐策略能提前预热，并在低谷释放 GPU 给训练队列；
- 每次准入、借用、回收、抢占和扩缩容都有事件、指标和审计记录；
- Dashboard 能从业务组下钻到 Queue、Workload、Pod、GPU UUID 和模型版本。

### 1.4 实践记录要保留什么证据

为了让结论可复查，每次试点都应保留：

- Kubernetes、GPU Driver、DCGM Exporter、Device Plugin/DRA、调度器和推理引擎版本；
- GPU 型号、UUID、MIG 状态、节点、Pod UID、业务组和用户的映射样本；
- 原始 `/metrics` 样本、PromQL、Dashboard 截图和告警消息；
- 低利用扫描命中时间、过滤原因、通知对象和用户反馈；
- 借用、回收、Checkpoint、恢复、扩容和排空的事件时间线；
- API Server QPS、Prometheus Series 数和 Exporter 内存等监控开销；
- 错误归属、漏告、重复告警和人工豁免，不能只保存成功截图。

文章中的阈值是策略示例，不是所有集群的生产答案。真正的阈值必须从目标业务两到四周基线、模型冷启动、训练阶段和团队工作方式中得到。

## 2. 目标架构

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

这里有四个不同控制点：

| 控制点 | 回答的问题 | 典型组件 |
| --- | --- | --- |
| 资源发现与切分 | 节点上有哪些卡、MIG 或 DRA Device | GPU Operator、Device Plugin、DRA Driver、NFD |
| 工作负载准入 | 哪个业务组的哪个任务现在有资格用多少配额 | Kueue 或 Volcano Queue |
| Pod 放置 | 已准入的 Pod 落在哪个节点和拓扑域 | kube-scheduler、Volcano、拓扑插件 |
| 服务弹性 | 推理服务此刻需要多少个完整副本 | KServe、AIBrix、HPA、KEDA、WVA |

不要让四层各自拥有不一致的容量上限。例如推理 `maxReplicas: 8`、每副本 TP=4，就可能需要 32 张 GPU；队列、节点池和扩容器都必须理解这个最大需求。

## 3. 先建立 GPU 资源池与 Flavor

不能只用 `nvidia.com/gpu` 表达所有卡。平台至少要区分：

- GPU 型号、显存和代际；
- 整卡、MIG Profile、vGPU 或时间共享；
- NVLink/NVSwitch、PCIe 和 RDMA 拓扑；
- 训练池、在线推理池与开发测试池；
- 按需、预留、Spot 和故障隔离状态；
- 驱动、CUDA、固件与健康基线。

建议维护稳定的平台标签：

```text
accelerator.aik8s.run/vendor=nvidia
accelerator.aik8s.run/model=h100-80gb
accelerator.aik8s.run/fabric=nvlink-rdma
accelerator.aik8s.run/pool=h100-rdma-training
accelerator.aik8s.run/lifecycle=reserved
```

Kueue 可通过 `ResourceFlavor` 把节点标签、Taint 容忍和配额组织成用户可理解的资源类型；Volcano 则可以通过 Queue、Node 标签、调度插件和扩展资源组合实现。业务组只选择平台发布的 Flavor，不直接拼接任意 NodeSelector。

开发环境可以评估 MIG 或共享 GPU，提高小任务密度；核心在线推理和多卡训练默认使用整卡或经过验证的 MIG Profile。Time-Slicing 能提高并发，却没有等价的显存隔离和性能保证，不能与整卡 SLO 混在同一个口径中。

## 4. 业务组 GPU 资源互借

### 4.1 五个基本配额量

每个业务组在每个 GPU Flavor 上都需要以下策略：

| 字段 | 含义 |
| --- | --- |
| `guaranteed` / `nominalQuota` | 正常情况下受保护的基准配额 |
| `borrowLimit` | 最多可以从 Cohort 或公共池借入多少 |
| `lendingLimit` | 自己最多允许借出多少，间接定义保留底线 |
| `maxCapacity` | 防止单一业务组占满全池的硬上限 |
| `fairShareWeight` | 多个借用方竞争空闲资源时的长期权重 |

Kueue 的 `ClusterQueue` 和 `Cohort` 原生支持 Nominal Quota、Borrowing、Lending Limit、层级 Cohort 与 Fair Sharing。借用方必须先在对应 Flavor 上声明配额，即使 Nominal Quota 为零；Lending Limit 用来避免本组全部保证量都被借走。参见 [Kueue Cohort](https://kueue.sigs.k8s.io/docs/concepts/cohort/)和 [ClusterQueue](https://kueue.sigs.k8s.io/docs/concepts/cluster_queue/)。

Volcano 的层级 Queue 使用 `deserved`、`guarantee`、`capability` 和 `reclaimable` 表达权益、保留、上限与跨队列回收，并由 Capacity Plugin 与 Reclaim Action 执行。参见 [Volcano Hierarchical Queue](https://volcano.sh/docs/keyfeatures/hierarchicalqueue/)。

### 4.2 平台策略 API

可以向业务组提供一个稳定的自助 API：

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

这不是现成的 Kueue 或 Volcano CRD，而是企业平台 API 示例。Controller 负责将它转换成实际 Queue、Cohort、Priority 和策略对象。

业务组可以自定义：

- 允许范围内的借入上限；
- 本组低优先级任务的排序；
- 夜间批任务窗口；
- 最大 24 小时一类的临时保护租约；
- 借用任务是否允许被回收。

平台必须固定：

- GPU Pool 和全局总量；
- 每组最小保障和最大上限；
- 能创建哪些 Priority；
- 哪些工作负载允许抢占；
- 最大宽限期和租约时长；
- 在线推理、监管任务和关键训练的保护级别。

Admission Webhook 要拒绝越权业务组、未知 Flavor、无限租约、借用上限超标和伪造高 Priority。所有策略变更通过 GitOps 或审计 API 留痕，并在执行前显示影响预览。

### 4.3 借用和回收状态机

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

推荐回收顺序：

1. 未开始运行、仍在 Queue 中的借用任务；
2. 可快速重试的短任务；
3. 已验证 Checkpoint 的训练任务；
4. 低优先级开发环境；
5. 最后才考虑无法保存状态的长任务。

在线推理副本不应成为常规借用回收对象。推理的缩容由服务控制器完成请求排空；训练的回收由队列和训练控制器完成 Checkpoint。两者不能共用一个粗暴的 `kubectl delete pod` 动作。

### 4.4 Kueue 还是 Volcano

| 当前基础 | 推荐起点 |
| --- | --- |
| 已使用 kube-scheduler，希望增加工作负载准入和 Cohort 配额 | Kueue |
| 已有稳定 Volcano Job/Queue 和批调度运维经验 | Volcano 层级 Queue |
| 复杂 Gang、DRF、回填和统一 AI/HPC 批调度 | Volcano |
| Trainer、JobSet、RayJob 等 Kubernetes 原生集成优先 | Kueue |

不要让 Kueue 与 Volcano 同时拥有同一个 Workload 的准入、Suspend、PodGroup 恢复和抢占所有权。组合部署时要明确一个负责准入、另一个只负责已准入 Pod 的放置，并通过故障实验验证状态机。

## 5. 推理服务实时弹性

### 5.1 不要只看 CPU

大模型推理的扩缩容信号至少包括：

| 指标 | 说明 | 适合动作 |
| --- | --- | --- |
| 等待请求数与排队时间 | 最直接的容量不足信号 | 快速扩容 |
| TTFT P95/P99 | 用户等待首 Token 的体验 | 扩容、路由或 Prefill 优化 |
| TPOT/ITL P95/P99 | 流式生成是否顺畅 | 并发、批处理和 Decode 优化 |
| KV Cache 使用率 | 是否接近并发容量上限 | 扩容或调整批处理参数 |
| Running/Waiting 请求 | 当前批次和队列压力 | 扩缩容与负载均衡 |
| Prompt/Generation tokens/s | 真实工作吞吐 | 容量和成本核算 |
| GPU 显存、SM 与功耗 | 硬件侧负载 | 验证应用指标与硬件状态 |
| 错误、超时和拒绝率 | 是否发生过载或依赖故障 | 降载、熔断、回滚 |

vLLM 通过 `/metrics` 暴露 Running/Waiting Request、KV Cache、TTFT、Inter-token Latency、Queue Time、Token Counter 和 Request Success 等指标，参见 [vLLM Metrics](https://docs.vllm.ai/en/stable/design/metrics/)。

### 5.2 推理扩缩容策略

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

这同样是平台 API 示例。Controller 可把它翻译成：

- KServe Standard Mode 的 HPA/KEDA；
- KServe Knative Mode 的请求弹性与 Scale-to-zero；
- KServe LLMInferenceService 的 HPA、KEDA 或 Workload Variant Autoscaler；
- AIBrix Autoscaler 与路由策略；
- Ray Serve AutoscalingConfig；
- 普通 Deployment + KEDA Prometheus Scaler。

KServe Standard Mode 可使用 HPA 和可选 KEDA，Knative Mode 支持请求驱动和 Scale-to-zero；两种模式在冷启动、网络复杂度和运行开销上不同。参见 [KServe Control Plane](https://kserve.github.io/website/docs/concepts/architecture/control-plane)。AIBrix 同时设计了响应式和基于历史预测、离线 Profiling 的主动扩容路径，参见 [AIBrix Autoscaler](https://aibrix.readthedocs.io/latest/designs/aibrix-autoscaler.html)。

### 5.3 一个副本不一定是一张 GPU

如果模型副本使用 TP=4，则 `1 → 2` 副本需要一次新增四张满足拓扑约束的 GPU。TP=8 或多机 Prefill/Decode 分离还需要 Gang、机架、RDMA 和 Worker 角色约束。弹性控制器必须把副本 Shape 传给容量与调度层，不能只把 HPA Desired Replicas 当作容量已经存在。

在线推理至少需要三类容量：

- `serving-floor`：当前最小副本真实占用的 GPU；
- `burst-headroom`：为快速扩容保留或预热的 GPU；
- `borrowable-cold-capacity`：可以暂借给训练，但回收速度无法满足秒级扩容。

如果全部空闲 GPU 都借给不可中断训练，推理扩容只能等待训练结束或新节点到达，平台就没有真正的在线 SLO 保证。

### 5.4 安全缩容

缩容顺序应是：

```text
选择候选副本
  → Router 将权重降为 0
  → 停止接收新请求
  → 等待流式请求和长上下文 Decode 结束
  → 达到 drainTimeout 后按策略终止或迁移
  → 删除 Pod，释放完整 Replica Shape
```

还要验证模型加载、CUDA Graph、Compile Cache 和本地模型缓存。大型模型从零启动可能需要数分钟，核心服务通常保留至少一个热副本；只有冷启动成本和业务等待可接受的低频模型才适合 Scale-to-zero。

## 6. 潮汐与定时扩缩容

潮汐策略解决可预测的日周期，实时指标处理预测之外的突发流量：

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

KEDA Cron Scaler 定义的是时间窗口和窗口内的 Desired Replicas，窗口外可结合 `minReplicaCount` 与其他 Trigger 缩容，参见 [KEDA Cron Scaler](https://keda.sh/docs/latest/scalers/cron/)。平台应采用：

```text
实际副本下限 = max(潮汐最低副本, 实时流量计算结果)
```

而不是让 Cron 固定副本、屏蔽实时流量。

平台可以定义：

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

这不是简单的 CronJob。Tidal Controller 需要检查模型平均加载时间、当前请求、训练剩余时间、Checkpoint 状态、GPU 健康和可用拓扑；如果预热失败，要保护现有副本并告警，不能为了满足计划数字先缩掉健康服务。

## 7. GPU 监控、可视化与可观测性

### 7.1 观测架构

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

NVIDIA 推荐在 Kubernetes GPU 节点部署 DCGM Exporter，并由 Prometheus 抓取、Grafana 展示。Exporter 可以借助 Kubelet PodResources 把 GPU/MIG 指标关联到 Pod、Namespace、Container，也支持 GPU UUID、MIG、DRA Claim、XID 和健康标签。参见 [DCGM Exporter](https://docs.nvidia.com/datacenter/dcgm/latest/gpu-telemetry/dcgm-exporter.html)和 [Metrics Reference](https://docs.nvidia.com/datacenter/dcgm/latest/reference/dcgm-exporter-metrics.html)。

### 7.2 统一标签契约

没有标签归属，GPU 指标只能回答“哪张卡很忙”，无法回答“哪个业务组为什么借了它”。平台对象至少统一以下低基数标签：

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

DCGM 指标原生归属到 Pod 后，再通过 Kube State Metrics、控制器指标或 Recording Rule 关联业务组、Queue 和模型。不要把 Prompt、Request ID、原始用户 ID、完整 Pod 标签集合都复制到 Prometheus；高基数和敏感字段进入 Trace 或结构化日志。

### 7.3 为什么二开 DCGM Exporter 做用户和团队归属

DCGM Exporter 能通过 Kubelet PodResources 把 GPU 或 MIG Device 映射到 Kubernetes Pod、Namespace 和 Container。较新版本还可以选择性增加 Pod Label、DRA Claim 和 HPC Job 等归属信息。但企业资源治理通常还需要稳定的 `business_group`、`owner`、`cost_center`、`queue` 和平台 Workload UID；这些字段未必都存在于 DCGM 原生映射里，或者名称与公司组织模型不一致。

一个直接想法是在 Exporter 生成每条指标时，根据 Pod 名称调用 Kubernetes API 查询 Label。这个方案在小集群演示时能工作，规模上来后风险很大：

- Prometheus 每 15—30 秒抓取一次，每个 GPU 节点和大量 Metric 都可能放大查询；
- `/metrics` 延迟与 API Server 延迟耦合，控制面抖动会让 GPU 监控一起丢失；
- 每个节点上的 Exporter 都需要 Pod 读取权限，扩大 RBAC 和 Token 暴露面；
- API Server 故障时最需要硬件指标，Exporter 却可能因为补标签失败而不可用；
- Pod 名称会复用，异步查询和缓存失效可能把旧用户归属到新 Pod；
- 把任意 Pod Label 全量加入指标会造成 Prometheus Cardinality 爆炸。

实践中更稳定的原则是：**禁止在 `/metrics` 热路径同步查询 API Server，归属数据必须先进入内存或本地快照。**

### 7.4 一种经过工程化的归属增强链路

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

中心同步器仍会访问 API Server，但它使用共享 Informer 和本地缓存，把读取压力集中、去重并与 Exporter Scrape 解耦；这和每个节点每次 Scrape 发起即时 GET 有本质区别。进一步严格的环境可以让节点 Agent 从受控消息流或签名快照获取映射，不给 Exporter 任何 Kubernetes API 凭据。

Exporter 二开点通常放在“设备已经映射到 Pod/Container”之后、“Prometheus Label 最终编码”之前：

```text
GPU UUID / MIG GI-CI
  → PodResources 找到 Pod UID、Namespace、Container
  → ownershipCache.Lookup(podUID)
  → 追加 business_group、owner_id、cost_center、queue、workload_uid
  → Prometheus exposition
```

建议只允许以下受控字段进入 GPU Metric：

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

工程细节决定归属是否可信：

- 以 Pod UID 为主键，Pod Name 只用于展示；
- 映射快照原子替换，禁止读到半份文件；
- Pod 删除后保留短暂 Tombstone，避免最后几个 Sample 失去归属；
- Cache 未命中时输出 `mapping_status="unknown"`，不能丢弃硬件指标；
- 组织关系变化要记录生效时间，历史账单不能被新部门关系重写；
- MIG 同时保存 GPU UUID、GI/CI 或 Profile，不能只按节点和 GPU Index；
- Exporter 重启、Metadata Sync 中断和 API Server 不可用时继续输出最近快照；
- 限制允许的 Label Value 长度和字符，防止指标注入与基数失控。

一条增强后的指标示意：

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

这条指标的价值不是 Label 看起来更丰富，而是后续低利用扫描、部门报表和配额回收只查询 Prometheus，不再为每次分析重新访问 Kubernetes API。

### 7.5 归属增强怎样验收

不要只看一条带标签的指标。至少验证：

1. Pod 启动、重建、跨节点调度后，GPU UUID 与 Pod UID 的归属及时变化；
2. 两个同名但不同 UID 的 Pod 不会串用户；
3. MIG、多容器 Pod 和多 GPU Pod 的每个 Device 都能正确归属；
4. 删除 Pod 后最后一段指标仍归到原 Workload，Tombstone 到期后正常清理；
5. API Server 暂时不可用时，Exporter `/metrics` 延迟和可用性不受影响；
6. Metadata Sync 恢复后，快照能追平且不会批量生成重复 Series；
7. Exporter 没有不必要的 Cluster-wide Secret、ConfigMap 和 Pod 写权限；
8. 开启归属 Label 前后，Prometheus Active Series、内存和查询时间增长在预算内。

可以先检查原始指标：

```bash
kubectl -n gpu-monitoring port-forward daemonset/dcgm-exporter 9400:9400
curl -s http://127.0.0.1:9400/metrics | grep '^DCGM_FI_DEV_GPU_UTIL' | head
```

再用 PromQL 检查未知归属和一张卡多重归属：

```promql
count by (mapping_status) (DCGM_FI_DEV_GPU_UTIL)
```

```promql
count by (cluster, UUID, pod, business_group, owner_id) (
  DCGM_FI_DEV_GPU_UTIL
)
```

指标名、UUID Label 大小写和 Pod Label 名称取决于 DCGM Exporter 版本，必须以实际 `/metrics` 为准。NVIDIA 当前文档列出的 Kubernetes、Pod UID、Pod Label、MIG、vGPU 与 DRA Label 能力可参考 [DCGM Exporter Metrics](https://docs.nvidia.com/datacenter/dcgm/latest/reference/dcgm-exporter-metrics.html)。

### 7.6 六层核心指标

#### 硬件健康

- GPU、显存、SM、Tensor、功耗和温度；
- SM/Memory Clock 与降频原因；
- PCIe、NVLink、NVSwitch 流量和链路状态；
- ECC SBE/DBE、XID、Driver 和 GPU Health；
- GPU UUID、MIG Profile、DRA Device 与节点；
- DCGM Exporter、Device Plugin 和 Driver 是否正常。

#### Kubernetes 与容量

- 按 GPU 型号、Pool、节点和 MIG Profile 的总量、可分配、已申请；
- Pending Pod/Workload 数、等待时间和不可调度原因；
- GPU 碎片：总空闲足够但无法组成 TP/Gang Shape；
- 不可调度节点、Taint、Device Plugin 和 DRA Claim 状态；
- 节点加入、初始化、预热、隔离和恢复时间。

#### 配额与互借

- 业务组 Guaranteed、Used、Borrowed、Lent、Borrowable；
- Cohort/父子 Queue 使用和 Fair Share；
- 借用持续时间、借用 GPU-hours 和即将回收容量；
- Admission Wait、Reclaim、Preemption 和恢复次数；
- Checkpoint 成功率、耗时和被抢占后的有效损失。

#### 训练效率

- Step Time、Samples/s、Tokens/s 和 GPU-hours；
- MFU 或经过定义的近似有效计算率；
- DataLoader/Storage Wait、CPU Feed 与网络等待；
- Rank 间 GPU 利用率、显存和 Step Time 偏斜；
- NCCL Collective 时延、错误与重试；
- Checkpoint 大小、写入吞吐、间隔和恢复耗时。

GPU 利用率高不等于训练有效。错误的数据流水线、重复计算、频繁重算或通信 Busy 也可能让设备保持高负载，必须同时观察训练进度与有效吞吐。

#### 推理 SLO

- RPS、并发、成功率、超时和拒绝；
- TTFT、TPOT/ITL、Queue Time 和端到端延迟的 P50/P95/P99；
- Running/Waiting Request、Batch 大小和调度抢占；
- Prompt/Generation tokens/s 与 tokens/GPU/s；
- KV Cache 使用率、Prefix Cache 命中和驱逐；
- 副本期望/实际数量、扩容耗时、冷启动和排空耗时；
- 模型版本、量化、TP/PP/DP/EP 和 Router 后端分布。

#### FinOps 与业务价值

- 业务组、Queue、模型、服务的 GPU-hours；
- 已申请但低利用率的 Idle GPU-hours；
- 满足 SLO 的有效 GPU-hours；
- 每百万输入/输出 Token 的 GPU 成本；
- 每个训练 Run、成功 Checkpoint 和有效 Token 的成本；
- 借用带来的额外完成任务数和避免采购的峰值容量。

### 7.7 定时扫描低利用工作负载

实时 Alertmanager 适合 XID、温度、推理 SLO 等立即故障；“谁占着 GPU 很久但利用率低”更适合定时治理扫描。原因是训练会经历模型加载、数据预处理、Checkpoint、验证和阶段切换，短时间 GPU Util 为零不代表浪费。

推荐扫描链路：

```text
CronJob / Governance Controller 每 15—30 分钟运行
  → 查询 Prometheus，而不是逐 Pod 查询 API Server
  → 按 business_group / owner_id / workload_uid 聚合
  → 检查连续时间窗、显存、功耗、训练进度和应用指标
  → 应用白名单、启动宽限、Checkpoint 与推理保底例外
  → 写入告警状态，完成去重和升级
  → 发送个人通知、团队汇总和平台治理事件
```

策略示例：

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

这也是平台策略示例。真正实现时，至少组合以下判断：

| 信号 | 为什么需要 |
| --- | --- |
| GPU 已分配时长 | 排除刚启动和短任务 |
| GPU Util 时间窗 | 识别持续低计算负载，而不是瞬时空闲 |
| 显存使用与功耗 | 区分模型常驻、错误空占和真实计算 |
| 训练 Step/Token 是否前进 | GPU 低但任务可能仍在 CPU/Data 阶段 |
| vLLM Waiting/Running Request | 在线保底副本低利用可能是正常 SLO 成本 |
| Checkpoint/评估状态 | 避免在保存和验证阶段误报 |
| 借用或保证配额 | 借用资源和本组保证资源可采用不同阈值 |
| 显式保护租约 | 为夜间任务提供有期限、可审计的例外 |

扫描结果必须有状态，不能每 15 分钟重复轰炸同一个用户：

```text
Detected
  → 首次通知 Owner，附 Dashboard 与自查建议
  → 用户恢复利用率：Resolved
  → 持续 2h：Escalated，通知团队管理员
  → 使用借用 GPU 且超过策略：ReclaimCandidate
  → Checkpoint 成功并经过审批：回收或降级
```

告警消息至少包含：业务组、用户、Workload、GPU 型号/数量、已运行时间、连续低利用时长、平均 GPU/显存利用率、是否借用配额、Dashboard 链接、建议动作和例外申请入口。只发“GPU 利用率低于 10%”几乎不会产生有效行动。

### 7.8 部门和个人排名怎样才公平

GPU 使用透明后，可以按部门和个人展示：

- Allocated GPU-hours；
- Effective GPU-hours；
- Low-utilization GPU-hours；
- Borrowed/Lent GPU-hours；
- Queue Wait 和被回收后的重算损失；
- 训练有效吞吐或推理单位 Token 成本；
- 低利用告警次数、持续时间和处理完成率。

排名对资源控制很有帮助：平台能找到“申请很多但长期不跑”的规格，部门管理员能看到内部不均衡，配额评审也从印象变为证据。但排名必须先做公平过滤：

- 在线推理 `serving-floor` 单独统计为 SLO 保有成本；
- 模型加载、编译、Checkpoint、评估和故障恢复窗口不计入普通浪费；
- MIG、Time-Slicing 和整卡分开比较；
- 不同 GPU 型号按 GPU-hours 和成本分别展示，不能把一张 L20 与一张 H100 简单相加；
- 设置最小样本量，避免运行十分钟的用户排在极端位置；
- 同时展示绝对浪费量和低利用比例，避免小用户因比例高被过度放大；
- 排名首先用于 Showback、辅导和规格优化，处罚与硬配额调整需要人工复核和申诉入口。

推荐生成两份结果：

1. **团队公开榜**：部门级 GPU-hours、有效率、借用贡献和改进趋势；
2. **管理员明细榜**：到 Owner/Workload 的证据，只向本人、部门管理员和平台团队开放。

这样既能形成资源治理压力，也不会把监控平台变成无上下文的“点名系统”。

### 7.9 PromQL 示例

vLLM TTFT P95：

```promql
histogram_quantile(
  0.95,
  sum by (le, model_name) (
    rate(vllm:time_to_first_token_seconds_bucket[5m])
  )
)
```

按模型统计等待请求：

```promql
sum by (model_name) (vllm:num_requests_waiting)
```

GPU 节点最高温度：

```promql
max by (Hostname) (DCGM_FI_DEV_GPU_TEMP)
```

实际 Metric 名称和 Label 会随 DCGM、vLLM 与部署配置变化。上线前以目标版本 `/metrics` 输出为准，Dashboard 和告警通过 Recording Rule 使用平台稳定名称，避免上游升级直接破坏所有查询。

### 7.10 六类 Grafana Dashboard

1. **GPU NOC**：XID、ECC、温度、功耗、降频、NVLink 和故障节点；
2. **容量与碎片**：按型号、Pool、拓扑、MIG、节点展示容量和不可组成的 Shape；
3. **业务组资源银行**：Guaranteed、Borrowed、Lent、Wait、Reclaim 与 Fair Share；
4. **训练任务**：队列、Gang、吞吐、Rank 倾斜、NCCL 和 Checkpoint；
5. **推理 SLO**：TTFT、TPOT、Queue、KV Cache、tokens/s、扩缩容和模型版本；
6. **FinOps**：GPU-hours、Idle Waste、单位 Token 成本、业务组 Showback/Chargeback。

每张图都应能从 Cluster → Pool → Business Group → Queue/Service → Workload/Pod → GPU UUID 下钻，同时保留时间范围和变更事件。

### 7.11 告警分级

| 级别 | 示例 |
| --- | --- |
| P0 | 致命 XID、ECC DBE、大面积 GPU 掉卡、核心推理不可用、配额控制面停止准入 |
| P1 | TTFT/TPOT 持续违反 SLO、队列快速增长、扩容无可用 GPU、NVLink/RDMA 故障、回收失败 |
| P2 | GPU 已分配但长期低利用率、碎片严重、训练排队超时、借用接近回收窗口 |
| 治理 | 越过借用上限、保护租约将过期、策略漂移、缺少 Owner/Cost Center、审计写入失败 |

告警要带业务影响和处置入口。例如“GPU Util 低”不是 P1；“核心服务 TTFT 超标，同时 Waiting Request 增长且扩容因 H100 拓扑不足失败”才是可行动告警。

## 8. 企业价值与 KPI

### 8.1 价值链

| 企业价值 | 平台机制 | 可量化指标 |
| --- | --- | --- |
| 提高昂贵 GPU 有效使用率 | 配额互借、潮汐、空闲回收 | Effective GPU Util、Idle GPU-hours、借用 GPU-hours |
| 减少部门资源孤岛 | Cohort/层级 Queue 与共享池 | 共享池命中率、峰值容量复用率 |
| 保证关键推理 SLO | 服务保有量、Headroom、应用指标弹性 | TTFT/TPOT、错误率、无容量扩容失败率 |
| 降低推理成本 | 低谷缩容、模型路由、单位 Token 核算 | 每百万 Token 成本、tokens/GPU/s |
| 缩短训练交付周期 | Gang、配额准入、借用和 Checkpoint | Queue Wait、Job Completion、抢占恢复时间 |
| 提高硬件可靠性 | DCGM 健康、XID/ECC 和自动隔离 | 故障发现时间、隔离时间、重复故障率 |
| 建立成本责任 | 业务组 Showback/Chargeback | GPU-hours、Idle Waste、预算偏差 |
| 加强治理 | 策略保护线、租约与完整审计 | 越权阻断、策略漂移、审计覆盖率 |

### 8.2 建议公式

```text
分配率 = 已分配 GPU-hours / 可提供 GPU-hours

有效利用率 = 产生有效训练或满足推理 SLO 的 GPU-hours
             / 已分配 GPU-hours

借用率 = 借用 GPU-hours / 可借 GPU-hours

推理单位成本 = 推理 GPU 成本 / 百万有效 Token

空闲浪费 = 已分配但低利用且无有效任务进展的 GPU-hours
```

不要先承诺“GPU 利用率达到 80%”。先按 GPU Pool 和工作负载采集两到四周基线，再制定目标。交互式开发、训练、在线推理和离线推理的合理利用率与 SLO 完全不同。

## 9. 分阶段实施

### P0：数据和标签基线

- 部署或核对 GPU Operator、DCGM Exporter、Prometheus 和 Grafana；
- 建立业务组、Cost Center、Queue、模型和 GPU Pool 标签；
- 接入 Kube State Metrics、队列、训练和推理指标；
- 只观测两到四周，不改变生产调度；
- 输出 GPU-hours、排队、SLO、碎片和故障基线。

### P1：配额互借 MVP

- Kueue 与 Volcano 二选一完成控制权验证；
- 接入两个业务组和一个 GPU Flavor；
- 配置保证量、借用上限、借出底线和硬上限；
- 只允许可 Checkpoint 的低优先级任务使用借入容量；
- 完成借用账本、通知、回收和恢复演练。

### P2：推理实时弹性

- 选择一个冷启动较短、一个大模型服务试点；
- 接入 Gateway、vLLM 与 DCGM 指标；
- 用 Queue、TTFT 和 KV Cache 驱动扩容；
- 验证无容量、模型加载失败、长请求排空和回滚；
- 建立服务 SLO 与容量 Headroom。

### P3：潮汐协同

- 建立工作日白天推理、夜间训练策略；
- 按模型加载时间提前预热；
- 在高峰前停止长训练准入并触发 Checkpoint；
- 比较预测容量与实际流量，逐步调整窗口和余量；
- 保留人工冻结和一键回退到固定副本的能力。

### P4：自助与 FinOps

- 业务组在保护线内自助调整借用和潮汐策略；
- 提供影响预览、审批、租约和审计；
- 输出 Showback/Chargeback 与单位 Token 成本；
- 根据排队、碎片、SLO 和成本指导采购与模型优化。

## 10. 必做故障实验

| 实验 | 验证目标 |
| --- | --- |
| 两组同时借用最后一批 GPU | Fair Share 和上限是否按策略工作 |
| 原业务组突然恢复保证量需求 | 回收、Checkpoint、通知和恢复是否完整 |
| Checkpoint 失败或超时 | 是否停止抢占并正确告警，而不是直接删除任务 |
| 推理 Waiting Request 快速增长 | Autoscaler 是否及时扩容且获得完整 Replica Shape |
| HPA 有 Desired Replica 但集群无 GPU | UI 和告警能否区分服务弹性与容量不足 |
| 潮汐预热模型下载失败 | 是否保留旧副本并停止危险缩容 |
| 长流式请求遇到缩容 | Router 是否先摘流量并等待排空 |
| GPU 出现 XID/ECC DBE | 是否隔离节点、终止错误分配并关联受影响任务 |
| Prometheus 或 Controller 重启 | 策略状态、计数和审计能否恢复 |
| 业务组伪造高 Priority 或标签 | Admission 是否拒绝并记录安全事件 |
| API Server 中断但 DCGM Exporter 正常 | `/metrics` 是否继续使用本地快照，Scrape 不受控制面影响 |
| Pod 同名重建或跨节点调度 | User/Team 归属是否按 Pod UID 更新且不串账 |
| 训练处于加载、Checkpoint 或评估阶段 | 低利用扫描是否正确过滤并避免误报 |
| 同一低利用任务连续命中多次 | 告警是否去重、升级并在恢复后关闭 |

## 11. 常见反模式

- 只做“GPU 总量和利用率”Dashboard，没有业务组、Queue、模型和成本归属；
- 每次 Prometheus Scrape 都从 Exporter 同步查询 API Server 补充 Pod Label；
- 把所有 Pod Label 无差别加入 DCGM 指标，造成 Series 和查询成本爆炸；
- 只按 Pod Name 归属用户，Pod 重建后出现串账；
- 低利用扫描没有启动、模型加载、Checkpoint 和推理保底例外；
- 每次扫描都重复通知，没有告警状态、去重、升级和恢复；
- 用 CPU HPA 扩缩容 vLLM，却不看请求队列、TTFT 和 KV Cache；
- 把所有空闲推理 GPU 借给不可中断训练，导致突发流量无法扩容；
- 业务组可以创建任意 PriorityClass，最终谁都声明最高优先级；
- 抢占前不 Checkpoint，互借节省的 GPU-hours 小于重算损失；
- Cron 直接覆盖副本数，导致真实流量 Autoscaler 失效；
- 缩容直接删除有长请求的推理 Pod；
- Prometheus 使用 Request ID、User ID 和完整 Pod Label，造成高基数；
- Time-Slicing、MIG 和整卡使用同一份性能 SLO；
- 同一 Workload 同时由 Kueue、Volcano 和自研 Controller 修改 Suspend/Priority；
- 以最新文档字段直接操作旧集群，未固定版本和验证 Feature Gate。

## 12. 上线验收清单

- [ ] GPU Pool、Flavor、拓扑、驱动和健康状态有统一来源；
- [ ] 每个业务组都有保证量、借入上限、借出底线、硬上限和 Owner；
- [ ] Kueue 或 Volcano 的准入与抢占所有权唯一；
- [ ] 借用资源只承载允许回收的工作负载；
- [ ] Checkpoint 成功后才执行训练回收，失败路径已经演练；
- [ ] 在线推理有明确 Floor、Burst Headroom 和最大 Replica Shape；
- [ ] 扩缩容使用 Queue、TTFT、KV Cache 等应用指标，而不只看 CPU/GPU Util；
- [ ] 缩容前 Router 摘流量并完成请求排空；
- [ ] 潮汐策略不会覆盖实时 Autoscaler，预热失败能安全回退；
- [ ] DCGM 指标能关联到 Pod、业务组、Queue、模型和 GPU UUID；
- [ ] Exporter `/metrics` 热路径不会同步查询 API Server，控制面故障时仍能输出硬件指标；
- [ ] User/Team 映射以 Pod UID 和本地原子快照为基础，具备 Unknown、Tombstone 和恢复语义；
- [ ] 归属 Label 使用允许列表，并验证 Prometheus Active Series 与内存增长；
- [ ] 低利用扫描使用连续时间窗、应用进度、例外策略和告警状态，不按瞬时 GPU Util 点名；
- [ ] 部门/个人排名区分推理保底、启动、Checkpoint、GPU 型号与最小样本量；
- [ ] 训练吞吐、推理 SLO、配额账本和 FinOps 分别有 Dashboard；
- [ ] XID、ECC、无容量扩容、SLO 和治理事件具备分级告警；
- [ ] Prompt、用户身份和 Request ID 不进入 Prometheus 高基数标签；
- [ ] 策略变更、借入借出、回收、抢占、租约和人工操作均可审计；
- [ ] 已采集基线，并用可量化 KPI 验证平台价值。

## 13. 延伸阅读

- [GPU 调度、共享与 DRA](../gpu-scheduling.md)
- [队列、多租户与配额](../queue-multitenancy.md)
- [弹性伸缩与 GPU 容量供给](../scheduling/autoscaling.md)
- [分布式训练](../distributed-training.md)
- [LLM 推理](../llm-inference.md)
- [GPU、训练与推理可观测性](../observability.md)
- [Kueue 与 Volcano 对比实验](kueue-vs-volcano.md)
- [Spot GPU 与 Checkpoint 恢复实验](spot-checkpoint.md)
