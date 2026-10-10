---
title: 大规模 Kubernetes 调度器优化：从队列积压到并行调度架构
description: 结合 Kubernetes 源码、阿里与字节公开实践，解释串行决策与节点并行、插件和重试优化、多调度器分片、并发冲突与效果验收
status: stable
last_reviewed: 2026-10-10
---

# 大规模 Kubernetes 调度器优化：从队列积压到并行调度架构

大集群里出现大量 Pending Pod，第一反应往往是给 kube-scheduler 增加 CPU、调高客户端请求额度，或者再部署几个副本。这些动作能解决部分问题，但也可能放大重试、API Server 写入和抢占压力。

调度优化要同时回答两个问题：**Pod 能否及时找到位置，以及找到的位置是否值得。** 前者关注排队、吞吐和尾延迟，后者关注资源碎片、故障域、租户公平性和作业整体成功率。只提高每秒绑定的 Pod 数，可能把训练任务更快地分散到无法组成完整作业的节点上。

本文结合上游机制、阿里与字节的公开材料，给出一套生产评估和调整方法。配置示例以 Kubernetes **v1.30.4** 为基线；涉及新版功能时单独说明版本。社区案例保留其原始环境边界，本文没有把它们改写成本地万节点压测成绩。

## 1. 先把“启动慢”拆成四段

从提交工作负载到容器 Ready，至少经过四段：

| 阶段 | 起点与终点 | 常见瓶颈 |
| --- | --- | --- |
| 工作负载生成 Pod | 提交 Job/Deployment → Pod 创建 | 控制器积压、准入 Webhook、API 请求限流 |
| 调度排队与决策 | Pod 进入队列 → 找到节点 | 资源不足、队列重试、Filter/Score 插件开销 |
| 绑定与相关准备 | 选中节点 → 绑定完成 | Permit 等待、卷绑定、API 写入、外部扩展服务 |
| 节点执行 | Pod 已绑定 → Ready | 镜像拉取、挂盘、网络、设备分配、应用初始化 |

这里的 Filter 是节点可行性过滤，Score 是可行节点打分，Permit 是允许继续绑定或等待的扩展点。Pod 已经有 `spec.nodeName`，却仍处于 Pending，通常要转向 kubelet、存储或设备链路，继续调 scheduler 参数很难奏效。

<img src="/assets/practices/large-scale-kubernetes-scheduler/scheduling-path.png" alt="Pod 从队列经过串行调度周期、可并发绑定周期到节点启动；分别测量排队、决策、绑定和启动" width="1200">

上游调度框架中，**调度周期串行运行，绑定周期可以并发运行**。节点级 Filter/Score 工作可以并行，但不等于多个 Pod 的完整调度周期同时执行。同一份领导者选举配置下，多副本提供的是高可用，只有领导者负责调度；一个进程中的多个 profile 也不是多个独立调度执行器。[Kubernetes 调度框架](https://v1-34.docs.kubernetes.io/docs/concepts/scheduling-eviction/scheduling-framework/)、[调度器多 Profile](https://kubernetes.io/docs/reference/scheduling/config/#multiple-profiles)

### 1.1 “Pod 串行调度”到底是哪一段

可以把调度器想成分配会议室的前台。前台依次处理预约，但有多位助手同时检查不同会议室；确定房间并登记占用后，办理门禁的人可以继续处理上一份预约，前台则开始下一份。会议室检查、预约决策和后续办理，是三个不同层次的并发。

| 层次 | 上游机制 | 优化含义 |
| --- | --- | --- |
| 不同 Pod 的选节点决策 | 同一 scheduler 的调度周期串行 | 缩短每次决策，或者采用独立调度分片 |
| 一个 Pod 对多个节点的计算 | 节点级 Filter/Score 可以并行 | `parallelism` 与可用 CPU 共同影响耗时 |
| 已选定节点后的绑定工作 | 不同 Pod 的绑定周期可以并发 | 后端写入、卷和 Permit 等待可能成为瓶颈 |
| 同一选举组的多个副本 | 一个领导者工作，其余备用 | 改善故障恢复，不直接增加决策吞吐 |
| 一个进程中的多个 profile | 共享队列和缓存，使用不同策略 | 支持策略区分，不增加独立决策执行器 |

这也解释了为什么把 `parallelism` 调成 32，不能描述为“同时调度 32 个 Pod”。它主要改变一份申请在节点计算阶段可以使用的并行度。[调度配置定义](https://kubernetes.io/docs/reference/config-api/kube-scheduler-config.v1/#kubescheduler-config-k8s-io-v1-KubeSchedulerConfiguration)、[多 Profile 与多实例的区别](https://kubernetes.io/docs/concepts/scheduling-eviction/running-multiple-schedulers/)

### 1.2 为什么绑定还没完成，就能处理下一个 Pod

在 v1.30.4 源码里，选定节点后，scheduler 先通过 `AssumePod` 在本地缓存中计入这份资源占用，再执行 Reserve、Permit 判断，随后异步推进绑定周期。下一个 Pod 的决策会看到本进程已经预占的资源，而不必等待 API Server 的绑定结果回来。绑定失败时，再清理缓存和插件预留状态。[v1.30.4 调度与绑定源码](https://github.com/kubernetes/kubernetes/blob/v1.30.4/pkg/scheduler/schedule_one.go)

这里的本地资源预占缓存（assumed cache）属于当前 scheduler 进程，并不是不同 scheduler 自动共享的全局账本。因此，直接让多个独立进程向同一节点池放置 Pod，会引入资源竞争；后文的分片和并行架构需要专门解决这个问题。

### 1.3 用串行耗时估算决策能力

一个便于评估的模型是：

```text
串行决策吞吐的粗略上界 ≈ 1 / 平均串行周期耗时
有效调度吞吐 ≈ 调度尝试吞吐 × 成功尝试比例
队列增长速率 ≈ 新增可调度需求 − 有效调度吞吐
```

例如，假设串行阶段平均耗时 20 ms，即使绑定可以并发，串行阶段的量级也只有约 50 次/秒。如果减少搜索和重复计算，把平均耗时降到 5 ms，决策能力的量级就变成约 200 次/秒，串行结构仍然可以获得明显提升。这是解释瓶颈的算术示例，不是 kube-scheduler 的固定性能上限或本文实测结果。这里应使用平均串行耗时估算，不能拿包含绑定的 P99 直接代入。若一半尝试都因资源不足失败，再增加 CPU 也不会自动产生新的可用节点。

## 2. 建立能解释原因的调度看板

我会先把队列、尝试结果、扩展点耗时和后端 API 放在同一个时间轴上，再看 CPU。否则容易把“资源不足反复重试”误判为“调度器算得太慢”。

以下名称与标签已按 [Kubernetes v1.30.4 调度器指标源码](https://github.com/kubernetes/kubernetes/blob/v1.30.4/pkg/scheduler/metrics/metrics.go) 核对；插件相关 Alpha 指标和后续版本的标签仍应以实际 `/metrics` 为准。

| 指标 | 观察什么 | 容易误读的地方 |
| --- | --- | --- |
| `scheduler_pending_pods{queue=...}` | active、backoff、unschedulable、gated 队列 | gated 是尚未放行，不等于节点筛选失败 |
| `scheduler_schedule_attempts_total{result,profile}` | 成功、不可调度、内部错误的速率 | 尝试次数不是唯一 Pod 数，失败重试也计数 |
| `scheduler_scheduling_attempt_duration_seconds` | 单次尝试耗时，包含算法和绑定 | 不包含一个 Pod 的全部排队等待 |
| `scheduler_pod_scheduling_sli_duration_seconds` | Pod 进入调度队列后的调度延迟 | 只在完成调度后形成观测，长期卡住的 Pod 不能靠它反映 |
| `scheduler_framework_extension_point_duration_seconds` | Filter、Score、PreBind 等阶段耗时 | 各阶段分位数不能直接相加成为总 P99 |
| `scheduler_plugin_execution_duration_seconds` | 具体插件耗时 | 1.30 的标签不含 profile；可能采样，先看实际观测频率 |
| `scheduler_queue_incoming_pods_total{queue,event}` | 哪类事件导致大量重新入队 | 要与对象更新和失败插件一起判断 |
| `scheduler_preemption_attempts_total` | 抢占尝试速率 | 尝试抢占不保证最终能运行 |
| `scheduler_unschedulable_pods{plugin,profile}` | 各插件拒绝的 Pod | 一个 Pod 可以被多个插件计入，不可直接求和当总数 |

`scheduler_pod_scheduling_duration_seconds` 在这个版本已经标记弃用，新看板应优先用 SLI 指标。SLI 是 Service Level Indicator，即服务水平指标；如果业务目标是“提交后 30 秒内 Ready”，仍需从提交、Pod 创建和 Ready 时间构建端到端指标，不能直接拿 scheduler 的直方图替代。

典型查询如下。多集群应保留 `cluster`，并按自己的采集标签增加 job/实例过滤。

```promql
# 成功调度吞吐：Pod/s
sum by (cluster, profile) (
  rate(scheduler_schedule_attempts_total{result="scheduled"}[5m])
)

# 队列构成
sum by (cluster, queue) (scheduler_pending_pods)

# 单次成功尝试 P99：秒
histogram_quantile(0.99,
  sum by (cluster, profile, le) (
    rate(scheduler_scheduling_attempt_duration_seconds_bucket{
      result="scheduled"
    }[5m])
  )
)

# 分阶段 P99：秒
histogram_quantile(0.99,
  sum by (cluster, profile, extension_point, le) (
    rate(scheduler_framework_extension_point_duration_seconds_bucket[5m])
  )
)
```

不能把各实例的 P99 再平均。直方图需要先按同一口径汇总 bucket，再计算分位数。还要显示观测次数；五分钟只有两次调度时，P99 的解释能力很有限。

| 同时出现的现象 | 优先检查 |
| --- | --- |
| active 持续增长、Filter/Score 升高、CPU 忙 | 节点搜索范围、插件算法、锁竞争、CPU 配额 |
| unschedulable 多、CPU 不高 | requests、GPU 类型、亲和性、污点、卷、配额 |
| backoff 与重新入队速率暴涨 | 无效事件唤醒、失败重试、控制器批量更新 |
| PreBind/Bind 慢、API 429/延迟升高 | 卷控制器、API Priority and Fairness（API 优先级与公平性，APF）、准入、etcd |
| 领导者切换后队列突然增长 | 选举时间、缓存同步、LIST/WATCH 与绑定恢复 |
| Pod 很快绑定、训练迟迟没开始 | Gang 完整性、设备拓扑、镜像、网络、模型加载 |

## 3. 节点搜索：少找一些，但要找到足够好的位置

`percentageOfNodesToScore` 是最常讨论、也最容易解释错的参数。它控制的是**找到多少个可行节点后可以停止搜索**，不是“无论如何只检查全体节点的 10%”。

自动值随规模变化：官方文档给出的量级是 100 节点约 50%、5000 节点约 10%，自动比例下限 5%，同时存在最少可行节点数的限制。显式配置 `0` 表示使用自动策略。节点很少时，调低比例通常收益不大。[Scheduler Performance Tuning](https://kubernetes.io/docs/concepts/scheduling-eviction/scheduler-perf-tuning/)

假设集群有 10000 个节点，但只有 30 个节点满足某种 GPU、网络和本地盘要求。即使阈值是 10%，也找不到 1000 个可行节点，搜索仍可能遍历大量节点。低比例无法直接解决候选节点稀疏的问题。

<img src="/assets/practices/large-scale-kubernetes-scheduler/search-and-quality.png" alt="节点搜索阈值减少可行节点打分，但稀疏 GPU 约束可能仍需搜索全部节点；吞吐与放置质量需要共同验收" width="1200">

调整时可以比较自动值、10%、20% 和 50%，但同一轮必须同时记录：

- Filter/Score 时间、成功 Pod/s 和排队 P99；
- CPU、内存、GPU 的剩余碎片；
- 跨可用区、跨 NUMA 和网络拓扑分布；
- 调度后的应用延迟、训练通信效率和抢占量。

NUMA 是 Non-Uniform Memory Access，即非统一内存访问架构。GPU 作业即使满足“有四张空卡”，也可能被放到跨 NUMA 或互联较弱的组合中。**放得快和跑得快需要分别验收。**

节点池、稳定的型号标签和简洁的硬约束可以减少无关候选。实现了候选集合索引的插件还能提前收敛节点；但上游 `nodeSelector` 并不保证完全跳过全量节点迭代，不能把标签治理宣传成固定的十倍加速。

## 4. parallelism、CPU 与客户端 QPS：分别解决不同问题

以 v1.30.4 为例，上游默认 `parallelism` 为 16，scheduler 客户端默认 QPS 为 50、burst 为 100。[v1.30.4 配置默认值](https://github.com/kubernetes/kubernetes/blob/v1.30.4/pkg/scheduler/apis/config/v1/defaults.go)

下面用于明确基线，**本身没有做性能提升**：

```yaml
apiVersion: kubescheduler.config.k8s.io/v1
kind: KubeSchedulerConfiguration
parallelism: 16
percentageOfNodesToScore: 0
clientConnection:
  qps: 50
  burst: 100
profiles:
  - schedulerName: default-scheduler
```

生产中保留现有 leaderElection、插件、证书和 kubeconfig 等配置，只调整经过验证的字段。不要用这份最小示例覆盖已有配置。

| 调整项 | 可能有效的条件 | 增大后的代价 |
| --- | --- | --- |
| CPU request / CPU 配额 | CPU 饱和或 CFS 配额限制导致节流 | 主机竞争、预算增加；算法低效仍存在 |
| `parallelism` | 节点级计算有足够并行工作和 CPU | 内存分配、锁竞争、上下文切换增加 |
| 客户端 `qps` / `burst` | 证实 client-go 限流拖慢写入 | 更大 API 突发、APF 排队、etcd 压力 |
| 调度副本数 | 需要领导者故障恢复 | 更多进程与缓存开销，不直接增加有效吞吐 |

QPS 是 Queries/Requests Per Second，这里表示客户端每秒请求额度。先区分 client-go 自身限流、API Server 返回 429、网络延迟和 etcd 提交慢，再决定增加哪一侧容量。把 qps 从 50 调到 500，不能修复一个执行 300 ms 的 Filter 插件。

生产 Profile 要用 Go 的性能剖析工具 pprof 区分：计算热点、锁阻塞、垃圾回收、内存分配和等待远端服务。剖析端点限制在运维网络，短时间采样；不要把调试接口直接暴露给所有租户。

### 4.1 节点并行度如何做对照

我会先固定搜索比例、插件和工作负载，确认 scheduler 是否有足够 CPU，再比较默认 16 与较低或较高并行度，例如 8、32。数值是测试档位，不是所有集群的推荐配置。

如果 Filter/Score 时间下降、成功 Pod/s 提高，而且排队尾延迟改善，可以继续扩大验证；如果 CPU 更忙、锁等待和垃圾回收增加，但成功吞吐不变，增加 worker 就没有达到目的。CPU 配额导致的节流也要先排除，否则工作被拆得更多，却仍争用同一份算力。

绑定慢时，先检查 client-go 限流、API 写入、卷准备和 Permit 等待。此时节点计算变快，可能只是让更多绑定请求同时积压。配置改变应配合第 9 节的完整验收，不能只比较一个扩展点的耗时。

## 5. 插件优化：把重复计算移出逐节点路径

大集群中，一个插件单次增加几十微秒，乘上几千节点、多个插件和持续重试，就会变成明显成本。

我会按以下顺序审查扩展实现：

1. **优先使用 informer/lister 缓存。** 不在每个 Pod、每个节点的 Filter 调用中实时 GET/LIST API Server。
2. **把共享计算放到 PreFilter / PreScore。** 同一 Pod 的需求、标签选择器和拓扑计数一次计算，通过 CycleState 复用。
3. **失败尽早返回。** 已经确定节点不可能满足硬条件，不继续执行昂贵逻辑；涉及插件顺序时确认没有改变诊断和状态语义。
4. **减少临时对象和大锁。** CPU Profile 之外同时检查 heap、mutex、block Profile，避免所有节点 worker 争用一个互斥锁。
5. **给外部 Extender 明确延迟和故障语义。** HTTP 调用设置超时，判断失败是放行还是拒绝；不能悄悄降级 GPU 拓扑和安全约束。

调度框架插件是编译到 scheduler 进程中的扩展；Extender 则是外部接口。两者的缓存、网络成本和升级方式不同。[Scheduling Framework 设计](https://github.com/kubernetes/enhancements/blob/master/keps/sig-scheduling/624-scheduling-framework/README.md)、[Scheduler Extender 配置](https://kubernetes.io/docs/reference/config-api/kube-scheduler-config.v1/#kubescheduler-config-k8s-io-v1-Extender)

Pod 间亲和性、反亲和性在大集群中尤其要谨慎。跨大量命名空间的复杂选择器、高 Pod 密度和频繁变动会增加计算负担。优先把需求说明白：必须同节点、只需同可用区，还是希望尽量分散？可以表达为简单拓扑分布的需求，不必全部写成复杂的 Pod 间关系；转换前必须验证语义一致。[Pod 间亲和性与规模限制](https://kubernetes.io/docs/concepts/scheduling-eviction/assign-pod-node/#inter-pod-affinity-and-anti-affinity)

### 5.1 一个能落到代码上的例子：重复解析选择器

假设自定义 Filter 插件会为每个节点重新解析同一 Pod 的选择器、计算设备需求，甚至调用 API 查询节点附加信息。检查几千个节点时，这些重复工作会累积在单次调度路径上。

| 原实现的工作 | 调整后的放置位置 | 需要保留的语义 |
| --- | --- | --- |
| 每个节点都解析同一份 Pod 需求 | PreFilter 中一次解析，写入 CycleState | 解析失败仍按原规则拒绝，不能忽略硬条件 |
| Filter 内实时 GET/LIST 节点附加对象 | informer/lister 缓存 | 明确缓存同步、更新和失效条件 |
| 每个节点重复计算与节点无关的打分参数 | PreScore 一次准备 | 节点资源和拓扑变化仍按正确状态计算 |
| 所有节点 worker 共用一把大锁 | 只读状态或缩小锁范围 | 并行调用仍须保持线程安全 |

CycleState 是本次 Pod 调度周期的状态容器；它不会自动保证自定义对象的线程安全。Filter/Score 并行读取的数据应按只读方式设计，也不要修改 informer 返回的共享对象。跨 Pod 复用结果还需要额外的等价判断和失效机制，不能把本周期缓存直接当成长期缓存。[调度框架扩展点](https://kubernetes.io/docs/concepts/scheduling-eviction/scheduling-framework/)

这是代码审查画像，并非本文已经测得的加速结果。验证时保持相同节点快照和 Pod 集合，比较插件 CPU、内存分配、API 调用量、成功吞吐，并逐项检查节点选择是否仍满足原约束。只缓存静态标签，却错误复用动态可用资源，会把性能优化变成错误放置。

### 5.2 GPU 碎片治理：给打分一个可检验的目标

训练资源池可以评估 NodeResourcesFit 的装箱打分。例如，把 GPU 纳入 `MostAllocated`，倾向于在满足 requests 的节点中使用已经分配较多资源的节点，尽量保留完整空闲节点。[Kubernetes Resource Bin Packing](https://kubernetes.io/docs/concepts/scheduling-eviction/resource-bin-packing/)

下面是 **profile 内的一段候选配置**，权重用于展示写法，不是推荐所有环境使用 4：

```yaml
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

节点资源打分基于请求与可分配资源，不等于 GPU 实际利用率；其他 Score 插件的权重仍会影响最终结果。这个配置也不了解卡间 NVLink、PCIe 与 NUMA 组合，不能代替设备拓扑插件或节点侧分配校验。

灰度时比较一组真实作业：同样的四卡、八卡请求，优化前后有多少完整八卡节点仍可用、多少作业因碎片等待、通信性能是否下降，以及故障域是否过度集中。CPU 微服务常需要分散部署，不能把训练池的装箱策略不加区分地应用到全部在线服务。

## 6. 重试治理：不要让无解的 Pod 消耗全部调度能力

假设某个租户提交 10000 个需要特定 GPU 的 Pod，资源只能容纳 1000 个。如果剩余 Pod 被频繁节点更新唤醒，调度器就会持续重复证明同一件事：资源不够。

应先在作业准入和队列层限制进入调度器的需求。Kubernetes 的 `schedulingGates` 可以把尚不具备条件的 Pod 留在 gated 状态；配合 Kueue 等作业准入组件，先判断配额和资源，再移除 gate。Gate 本身不会分配资源，也不会自动完成 Gang 调度。[Pod Scheduling Readiness](https://kubernetes.io/docs/concepts/scheduling-eviction/pod-scheduling-readiness/)、[Kueue 工作机制](https://kueue.sigs.k8s.io/docs/overview/)

重试侧还可以利用 QueueingHint：根据上次失败的插件，判断某个事件是否可能让 Pod 变得可调度。它在 v1.32 默认启用，在 **v1.34 成为稳定功能**。早期实现曾因内存问题关闭过默认开关，因此旧集群不能直接照抄新版 feature gate。[v1.32 QueueingHint 说明](https://kubernetes.io/blog/2024/12/12/scheduler-queueinghint/)、[v1.34 QueueingHint 状态](https://v1-34.docs.kubernetes.io/docs/concepts/scheduling-eviction/scheduling-framework/#queueinghint)

实践中的目标是减少无效尝试，而不是一味延长 backoff。Backoff 是失败后的退避；过长会让资源释放后本应立即运行的 Pod 继续等待，过短又会形成重试风暴。调整要同时观察重新入队事件和资源释放后的恢复延迟。

### 6.1 用成功比例判断队列治理是否有效

例如，假设一次测试每秒有 100 次调度尝试，其中 80 次因资源不足失败，只有 20 次成功。调度器 CPU 很忙，但业务得到的是约 20 Pod/s。若准入与相关事件唤醒减少了无效尝试，应进一步观察成功吞吐和正常业务等待是否改善；不能因为尝试次数下降，就判定调度能力下降。

比较时分别保留 scheduled、unschedulable、error 三类尝试数量，以及未完成 Pod 的等待年龄。成功尝试占比按三类尝试的相同统计窗口计算，不能用当前 Pending 数去除以累计尝试数。还应在释放资源后验证作业能及时恢复，避免通过长时间退避制造“队列变安静”的表面效果。[QueueingHint 的队列与重试机制](https://kubernetes.io/blog/2024/12/12/scheduler-queueinghint/)

`schedulingGates` 在 v1.30 成为稳定功能，QueueingHint 则在 v1.34 稳定；v1.20 集群不能直接照搬这些配置。旧集群需要结合已有作业队列、提交控制和对应版本的事件唤醒机制评估，也可以把版本升级纳入优化路线。[Scheduling Readiness 版本说明](https://kubernetes.io/docs/concepts/scheduling-eviction/pod-scheduling-readiness/)

抢占也要算进这本账。高优先级 Pod 不一定能通过抢占满足硬亲和性、拓扑或卷条件；大量重复抢占会制造驱逐、重建和 Event。PDB 是 Pod Disruption Budget，即 Pod 中断预算，上游抢占对它的保护是尽力而为，不能承诺绝不违反。优先约束高优先级的使用范围，给长训练作业配合可恢复 checkpoint。[Pod Priority and Preemption](https://kubernetes.io/docs/concepts/scheduling-eviction/pod-priority-preemption/)

## 7. 阿里的实践：吞吐之外还要解决配额与作业完整性

阿里 2019 年万节点控制面分享把 10000 Node、200000 Pod 和百万对象作为测试画像，发现存储、控制器恢复和调度同时受到压力。它的价值在于把 scheduler 放回整个控制循环：后端 API 慢、缓存冷启动和对象风暴会一起拖慢调度。文章年代较早，其中改进不能直接当作当前版本仍缺失的功能。[阿里巴巴万级规模控制面优化](https://developer.aliyun.com/article/719079)

阿里工程师在 Kubernetes 调度扩展分享中进一步讨论 Capacity Scheduling 和批作业调度。对应的生产问题是：一个租户是否长期占住闲置额度，以及多进程作业能否一起拿到资源。[阿里：扩展 Kubernetes 调度器支持 AI 和大数据作业](https://www.cncf.io/wp-content/uploads/2020/08/%E9%98%BF%E9%87%8C%E5%B7%B4%E5%B7%B4%E5%A6%82%E4%BD%95%E6%89%A9%E5%B1%95Kubernetes-%E8%B0%83%E5%BA%A6%E5%99%A8%E6%94%AF%E6%8C%81-AI-%E5%92%8C%E5%A4%A7%E6%95%B0%E6%8D%AE%E4%BD%9C%E4%B8%9A%EF%BC%9F1-xi-jiang.pdf)

Koordinator 的 ElasticQuota（弹性配额）支持层级额度及借用/归还，Coscheduling 支持 Gang，也就是一组 Pod 满足最低就绪条件后一起推进。这些能力可以改善共享资源池的使用方式，但增加了 quota、PodGroup、Reservation 等对象和状态管理，仍需测量插件耗时与失败恢复。[Koordinator v1.6 弹性配额](https://koordinator.sh/docs/v1.6/user-manuals/capacity-scheduling)、[Koordinator 组件与调度插件](https://koordinator.sh/docs/developer-guide/component-guide)

对于一个八进程训练作业，我更关心“八个进程全部可运行用了多久”，而不是第一个 Pod 多快绑定。否则容易出现四个作业各拿到两张卡，GPU 都被占用，却没有一个作业能开始。

这类问题适合在作业层解决：先准入，再 Gang/预留，最后进行节点与设备放置。给默认 scheduler 增加 CPU 不能替代这层资源管理。

## 8. 多个 Pod 如何并行：分片与共享池架构

单个 Pod 的计算已经优化后，如果串行决策仍无法承接提交峰值，就要区分两个方向：拆分独立资源池，或者在共享资源池上设计并发决策与冲突处理。

<img src="/assets/practices/large-scale-kubernetes-scheduler/parallelism-and-sharding.png" alt="左侧为一个 Pod 的节点过滤与打分并行，右侧为不同 Pod 通过独立调度器进入互斥节点池；两者优化不同层次" width="1200">

### 8.1 独立节点池：多个调度器分别决策

在线服务、训练作业和批处理如果已经有明确的资源边界，可以评估独立 scheduler 进程。Pod 使用不同 `spec.schedulerName`，每个调度器有独立选举锁，并以硬约束限定自己的节点池。

| 工作负载 | schedulerName 示例 | 节点边界 | 主要目标 |
| --- | --- | --- | --- |
| 在线服务 | `online-scheduler` | 在线节点池 | 减少批量提交对在线扩容的干扰 |
| GPU 训练 | `training-scheduler` | GPU 训练节点池 | 独立处理设备、配额和作业约束 |
| CPU 批处理 | `batch-scheduler` | CPU 批处理节点池 | 承接突发任务并评估装箱策略 |

这是候选架构，不是本文已经实施的三分片部署。各个进程可以同时执行自己的调度周期，每个进程内部仍按上游方式串行决策。每个分片再配置备用副本，解决的是该分片的高可用。

灰度需要双方都遵守资源边界：给训练 scheduler 限定 GPU 池，还要确保其他 scheduler 不会把业务放到同一池里。仅给 Pod 换一个 `schedulerName`，或只增加单向节点亲和性，不能保证隔离。一个进程内配置多个 profile，也不能代替多个独立分片。[多调度器部署原则](https://kubernetes.io/docs/concepts/scheduling-eviction/running-multiple-schedulers/)、[独立调度器与选举锁配置](https://kubernetes.io/docs/tasks/extend-kubernetes/configure-multiple-schedulers/)

分片的代价包括更多缓存与 Watch、分片负载不均，以及池间借用资源更复杂。三个分片不保证三倍吞吐：如果都被同一 API 写入瓶颈限制，最终提升仍可能很小。验收要看每片和整体的成功吞吐、排队时间、资源碎片及 API/etcd 压力。

### 8.2 共享节点池：为什么不能简单多开几个 worker

假设节点只剩 8 核，两个各申请 8 核的 Pod 同时读取了这份空闲状态，就可能都选中该节点。API Server 的绑定操作不是全局资源容量校验，两个独立 scheduler 的 assumed cache 也不共享。

因此，共享池的并行调度至少要回答：决策提交时如何重新校验资源、谁记录预占、冲突由谁拒绝、失败后如何回收，以及抢占和亲和性等跨节点约束如何保持一致。把选节点函数放到多个 goroutine 里，只完成了并行计算的一部分。

字节的 Gödel 是这条路线的公开案例：Dispatcher 分发调度单元，多个 Scheduler 分片计算放置方案，Binder 检查冲突并执行绑定；有冲突的单元重新调度。它采用乐观并发，即允许先并行计算，再在提交环节检测冲突。这里的计算、校验和恢复共同组成优化方案。[Gödel 的架构与冲突处理](https://www.cncf.io/blog/2024/04/02/godel-scheduler-open-sourced-a-unified-scheduler-for-online-and-offline-workloads/)

### 8.3 字节的实践与适配边界

字节 2024 年公开 Gödel Scheduler 时报告：其内部定制环境下，单分片超过 **2000 Pod/s**，多分片超过 **5000 Pod/s**，最大生产集群超过 **20000 节点、100 万 Pod**。这些数字来自字节的公开案例，不是本文复测，也不能与一个简单空 Pod 测试直接比较。[字节发布 Gödel Scheduler](https://www.cncf.io/blog/2024/04/02/godel-scheduler-open-sourced-a-unified-scheduler-for-online-and-offline-workloads/)

还有一个现实边界：检索时，Gödel 仓库 Quick Start 明确列出的 Kubernetes 兼容范围是 **1.21.4–1.24.6**。这不证明新版本必然不能适配，但对 1.30 集群不能承诺拿来即用；需要确认分支、API、插件和维护策略。[Gödel 项目与兼容说明](https://github.com/kubewharf/godel-scheduler)

对这类架构，我会设置三个采用条件：

- 已经用真实画像证明单领导者的串行决策路径是主要瓶颈；
- 参数、插件和重试治理之后仍无法满足需求；
- 团队能维护兼容性、冲突恢复、故障测试和上游升级。

如果主要问题只是训练配额和 Gang 完整性，先引入相应作业管理能力通常更直接，不必立刻替换整个调度体系。

### 8.4 批处理复用：相似 Pod 不必从头计算

另一条路线是复用相似 Pod 的计算结果。一个工作负载连续提交大量具有等价调度约束的 Pod 时，反复执行相同 Filter/Score 会产生重复成本。字节公开实践包含同类调度单元结果缓存；上游 Kubernetes v1.35 的 Opportunistic Batching（机会式批处理）也提供了受条件限制的结果复用机制。

它没有把多个 Pod 的完整调度周期改成并行，而是降低连续周期的重复计算量。v1.35 文档将其列为默认启用的 Beta 功能，但可获益画像受到限制，包括 Pod 间亲和性、拓扑分布和动态资源申请等；默认拓扑分布配置也会影响是否可用。自定义插件需要支持相应的签名扩展点（Signature），才能表达复用条件。不能为了命中缓存直接删除业务需要的拓扑约束。[v1.35 批处理条件](https://v1-35.docs.kubernetes.io/docs/concepts/scheduling-eviction/scheduler-perf-tuning/#enabling-opportunistic-batching)、[机会式批处理设计](https://github.com/kubernetes/enhancements/blob/master/keps/sig-scheduling/5598-opportunistic-batching/README.md)

v1.20、v1.30 的部署无法通过新增同名参数直接获得这项能力。评估升级或自定义实现时，需要一起验证调度约束的等价判断、资源状态变化、缓存失效和自定义插件兼容性。

## 9. 如何压测，才能说明优化有效

上游有 `scheduler_perf` 集成性能测试，适合比较版本、插件和配置开销；Kubemark 能模拟更大规模控制面。两者都不能自动代替 GPU、卷和真实训练启动验收。[scheduler_perf](https://github.com/kubernetes/kubernetes/tree/v1.30.4/test/integration/scheduler_perf)、[Kubemark](https://github.com/kubernetes/kubernetes/tree/v1.30.4/test/kubemark)

我会准备以下几类画像，并保持同一组 Pod、节点快照、顺序分布和资源占用：

| 场景 | 目的 | 除吞吐外的验收 |
| --- | --- | --- |
| 大量小 CPU Pod | 测量基础串行路径 | 排队 P99、API bind 速率 |
| Pod 密集且含亲和性 | 放大关系计算 | Filter 插件、锁、内存 |
| GPU / RDMA / 拓扑约束 | 测量稀疏候选和放置质量 | 可用整机数量、跨拓扑通信 |
| 部分请求确定不可调度 | 验证重试治理 | 无效尝试比例、在线 Pod 是否饥饿 |
| PVC 与延迟绑定 | 验证存储链路 | PreBind、卷就绪与超时 |
| 大批 Job 同时提交 | 验证准入和 Gang | 整个作业启动时间、半占用资源 |
| scheduler 切主、节点批量变化 | 验证故障恢复 | 缓存同步、重试、重复/冲突绑定 |

RDMA 是 Remote Direct Memory Access，即远程直接内存访问；PVC 是 PersistentVolumeClaim，即持久卷声明。这里列的是评估场景，不是本文已经执行的压测结果。

每次只改一类变量。例如先固定插件与资源，比较搜索比例；再固定比例，比较 parallelism；最后才测客户端 QPS。发布量应同时覆盖稳态和突发，记录所有创建 Pod 的分母，不把超时和失败样本从报表中删掉。

看板中至少放两类延迟：**成功样本的直方图**和**仍在等待的 Pod 年龄**。后者可以通过 Pod 创建时间、PodScheduled condition 与 Watch 记录计算，不要虚构一个在当前版本并不存在的“队列最老年龄”指标。

### 9.1 把优化动作与验收结果对应起来

一份有用的生产复盘，应能从业务现象一路追到具体变更。下面四类画像适合分别记录，避免只写“调了参数，调度变快了”。

| 画像 | 瓶颈证据 | 候选改动 | 必须同时验收 |
| --- | --- | --- | --- |
| 大批 Pod 提交后 active 队列积压 | Filter/Score 高，CPU 或插件热点明显 | 搜索比例、节点并行度、预处理和缓存 | 成功 Pod/s、等待 P95/P99、节点选择与碎片 |
| 资源不足的训练 Pod 持续重试 | unschedulable 与无效重新入队多 | 作业准入、配额、相关事件唤醒 | 正常业务等待、失败占比、资源释放后的恢复速度 |
| 在线与批处理提交互相干扰 | 分业务排队时间差异明显 | 独立调度分片与互斥节点池 | 每片吞吐、整体利用率、池间闲置与故障恢复 |
| 基础优化后串行决策仍达不到目标 | 相同画像下的决策耗时与队列增长 | 并行架构或满足条件的批处理复用 | 冲突率、重新计算成本、约束正确性和后端压力 |

记录基线时写清楚节点数、Pod 密度、每秒提交量、突发批次、亲和性、卷与设备条件，以及不可调度请求比例。同样是 1000 个 Pod，没有约束的 pause Pod 与带卷、拓扑和 Gang 的训练 Pod，计算与绑定成本会相差很大。

改动前后使用相同分母、相同观察窗口，并保留超时样本。效果用实测数值填写：成功吞吐从多少到多少、等待尾延迟是否下降、未完成 Pod 有多少、资源放置是否退化。再记录资源释放、scheduler 切主和绑定失败时的恢复表现，才能判断收益是否能留在生产环境里。

复盘记录随着定位、灰度和恢复验证逐步完善；每项结论附带对应的原始数据、配置版本和观察窗口，方便后续复查与继续优化。

## 10. 灰度、回滚与故障恢复

建议采用“离线重放 → 隔离节点池 → 小比例工作负载 → 扩大覆盖”的顺序。第二个 scheduler 使用独立 `schedulerName`，让试验 Pod 明确选择它；节点池用双方都遵守的选择约束与污点隔离，不能只给新 scheduler 增加一条单向亲和性。

两个独立调度器同时向相同节点放 Pod，各自的 assumed cache 不共享。API Server 不负责原子检查所有资源是否够用，因此不能把“绑定 API 成功”当成没有资源竞争。若要共享池，应评估协调/预留机制和失败恢复，而不是简单启动双活。

上线前把以下证据放在同一份变更记录中：

| 项目 | 要保留的内容 |
| --- | --- |
| 基线 | 版本、镜像 digest、完整配置、插件与节点画像 |
| 调整 | 单项变化、理由、Profile 与 Pod 范围 |
| 性能 | 有效 Pod/s、排队与尝试延迟、失败分母 |
| 放置质量 | 碎片、作业完整性、跨拓扑比例、业务延迟 |
| 后端影响 | API 429、绑定延迟、etcd、Event、Informer 重连 |
| 恢复 | 主实例故障、Permit 超时、绑定失败、预留回收 |
| 回滚 | 恢复配置的方法，以及已创建 Pod 如何转交 |

`schedulerName` 不是可以随时修改的迁移开关。灰度回滚要有控制器层的重建或接管方案，不能只把新 scheduler 缩到零，让已经归它负责的 Pod 永久 Pending。

我选择优化路线时，通常遵循这个顺序：先消除无解需求和无效重试，再压缩候选与插件成本，随后校正 CPU 和 API 额度，最后评估并行调度架构。每一步都要求有效吞吐提升，同时没有把资源碎片、在线业务干扰或恢复时间推到更差的位置。

## 延伸阅读

- [万节点 Kubernetes 控制面、etcd 与网络优化](large-scale-kubernetes-optimization.md)
- [大规模 Kubernetes 监控与时序数据库选型](large-scale-kubernetes-monitoring-tsdb.md)
- [四卡 GPU 作业如何避免跨 NUMA 碎片](gpu-topology-fragmentation-scheduling.md)
- [Koordinator 与在线离线混部](../scheduling/koordinator-colocation.md)
