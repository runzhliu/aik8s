---
title: Volcano 调度器不是万能钥匙：企业落地的配置、边界与排障
description: 从 Gang、Queue、设备拓扑和扩容联动出发，解释 Volcano 能解决什么、哪些企业问题还需其他组件，以及如何验证调度配置与故障路径
status: evolving
last_reviewed: 2026-10-11
---

# Volcano 调度器不是万能钥匙：企业落地的配置、边界与排障

一个训练平台接入 Volcano 后，八个 Worker 终于可以按 Gang 语义一起争取资源，不再由几个先启动的 Pod 长时间占着 GPU 等其他成员。接着业务提出三个要求：四卡任务必须拿到同一 NUMA 域的 GPU；队列没有额度时别让自动扩容器盲目加机器；借用的 GPU 要能收回，但被收回的训练作业不能丢掉几个小时的进度。

这三个要求都和“调度”有关，却不是装上 Volcano 就自然满足。第一个要求要看**逐设备拓扑信息和最终设备分配**；第二个涉及**队列状态怎样传递给扩容器**；第三个还涉及**驱逐后的训练恢复**。Volcano 擅长批作业、Queue 和 Gang，但它不是训练平台所有控制回路的总开关。

下面的场景是架构分析，不是本仓库已经完成的 Volcano 生产事故复盘或性能测试。功能与配置举例依据 Volcano **v1.15.3** 发布标签（2026 年 9 月 30 日发布）的文档和 Helm 默认配置；其他版本、发行版与插件组合需单独核对。

## 它真正解决了什么

Volcano 是一套面向批处理、AI 与 HPC 的 Kubernetes 调度系统，不只是替 kube-scheduler 改个 Score。其 Job、PodGroup、Queue 和调度器共同描述：**一组任务什么时候有资格开始、资源怎样在队列之间分配、每个 Pod 落到哪里。**

| 企业问题 | Volcano 提供的抓手 | 成立的前提 |
| --- | --- | --- |
| 八个 Worker 不能只跑两个 | PodGroup 最小成员/资源要求与 `gang` 插件 | 所有成员正确归组，最小资源定义符合训练真实需求 |
| 部门之间共享 GPU | Queue、DRF/Proportion 或 Capacity 策略、Reclaim | 明确借用与回收规则，作业能承受被驱逐 |
| 批任务与在线任务争资源 | Priority、Preempt、Reclaim、节点约束 | 显式保护在线工作负载，量化抢占影响 |
| 节点/机架网络局部性 | 拓扑相关能力及其数据源 | 目标版本和部署确实提供所需拓扑标签/数据 |

这也是 Volcano 值得用的地方：在大量多 Pod 作业、队列借用和批调度策略已经成为平台核心需求时，统一的调度控制面可以比逐个 Job 拼接临时规则更清晰。问题不在于“功能少”，而在于**功能覆盖的层，与企业想保证的最终结果经常不是同一层**。[Volcano 官方概览](https://volcano.sh/docs/)；[v1.15.3 调度配置说明](https://github.com/volcano-sh/volcano/blob/v1.15.3/docs/user-guide/how_to_configure_scheduler.md)。

## 第一处边界：Gang 不等于作业一定能跑完

Gang 的目标是避免一组 Pod 只有一部分被调度占用资源。可是“八个 Pod 能一起获得调度机会”与“八个训练进程都健康启动、完成通信并持续训练”之间，还隔着镜像拉取、存储挂载、设备插件分配、RDMA 网络、NCCL/HCCL 初始化和失败恢复。

假设一组八个 Worker 满足 PodGroup 的最小成员要求，随后一个节点上的容器因驱动异常退出。Gang 不能替应用保存 checkpoint，也不会替训练框架修复通信状态。平台仍要确定：整组重启还是局部重启、什么时候释放其他 Worker 的 GPU、多久恢复、恢复后是否重复计算已完成的数据。Volcano Job 的策略可以响应部分作业事件，但“调度成功”不能直接写成“训练可靠性已解决”。[Volcano Job Policy](https://volcano.sh/docs/v1.13.0/userguide/user_guide_how_to_use_job_policy/)；[训练框架与恢复专题](../training/distributed-training-frameworks-recovery.md)。

更容易忽略的是 `minMember` 与真实启动门槛不一定相同。如果最小成员数配小，形式上能进队列，应用仍因缺少必要 Rank 而等待；配得过大，又可能在资源短缺时长期排队。检验时记录**作业提交→整组就绪时间**和已占用但未开始计算的 GPU 时间，而不是只看第一个 Pod 的 `Running`。

## 第二处边界：选到了节点，不等于拿到了对的 GPU

例如一台八卡节点分成两个四卡 NUMA 域，空闲 GPU 分散为每域两张。四卡任务在整数资源视角仍可能看到 `nvidia.com/gpu: 4`；如果实际拿到跨域设备，通信性能可能退化。传统 Device Plugin 模式下，调度器选节点与 kubelet 分配具体 GPU 是两个决策。**Queue 和 Gang 都不能自动给出“同一 NUMA 域四张卡”的硬保证。**

Volcano 社区的 [GPU NUMA topology-aware scheduling Issue #4998](https://github.com/volcano-sh/volcano/issues/4998)说明其 `numa-aware` 插件主要处理 CPU NUMA，对标准 GPU 设备 NUMA 的处理仍有待补齐；[v1.15.3 调度配置说明](https://github.com/volcano-sh/volcano/blob/v1.15.3/docs/user-guide/how_to_configure_scheduler.md)也把 `numaaware` 的作用描述为 CPU NUMA。这个结论针对所讨论的**标准整卡 GPU 同 NUMA 硬约束**，并非断言 Volcano 不支持 GPU、没有 vGPU 能力或不能处理跨节点网络拓扑。

可选择的补充路径包括：由 Device Plugin 尽量优选设备、由 kubelet Topology Manager 作节点侧准入，或评估具有逐设备拓扑信息的调度/分配方案与 DRA；每条路径都要验证“只有跨域四张空卡时，任务会不会拒绝退化组合”。具体能力和版本差异见[四卡任务与 NUMA 碎片分析](gpu-topology-fragmentation-scheduling.md)。

## 第三处边界：队列等待与扩容，未必说着同一种语言

企业常见规则是：租户没额度时只排队，节点确实不足且有额度时才扩容。这需要扩容器区分“队列策略拒绝”和“当前节点库存不足”，不能把所有 Pending 都当成需要买机器。

Volcano v1.15 的 [Scheduling Gates Queue Admission 指南](https://github.com/volcano-sh/volcano/blob/v1.15.3/docs/user-guide/how_to_use_scheduling_gates_queue_admission.md)写明了问题：队列额度不足也可能使 Pod 被标记为 Unschedulable，触发不必要的扩容。它提供基于 Kubernetes `schedulingGates` 的改进，但要求 v1.15+、启用 `SchedulingGatesQueueAdmission` Alpha feature gate、Webhook 与调度器配合、配置 `capacity` 插件，并对 Pod 显式 opt-in。这个官方方案本身就说明：**调度器内部知道队列状态，不代表 Cluster Autoscaler/Karpenter 已正确理解。**

该指南还标出了一个生产边界：移除 Gate 后，如果 Pod 仍因节点不足而无法调度，它会继续持有预留的队列容量；当时没有为这份预留实现超时。因此不能简单宣称“开了 Gate 就解决了所有无效扩容和额度占用”。没有满足这些前提的老版本，不应抄 v1.15 的配置当成已生效功能。

## 功能丰富，为什么配置会变成排障成本

Volcano 的调度配置不是一个“开启 Gang”开关。v1.15.3 Helm 默认调度配置按顺序执行 `enqueue, allocate, backfill` 三个 action，加载 `priority`、`gang`、`conformance`、`overcommit`、`drf`、`predicates`、`proportion`、`nodeorder`、`binpack` 等插件，并分为两个 tier。[发布标签中的默认配置](https://github.com/volcano-sh/volcano/blob/v1.15.3/installer/helm/chart/volcano/config/volcano-scheduler.conf)。

顺序和组合会影响结果。官方[配置指南](https://github.com/volcano-sh/volcano/blob/v1.15.3/docs/user-guide/how_to_configure_scheduler.md)解释：action 决定调度流水线，插件在 session 中注册函数；多个插件可以注册同类判断函数，一个拒绝结果可能令后续判断不再执行。`backfill`、`preempt`、`reclaim` 也不是同一种动作。看见 Queue 有 `deserved`，并不能推断当前已启用 `capacity` 和 `reclaim`。

具体到“两个部门借卡并归还”：v1.15.3 的 [Capacity 插件指南](https://github.com/volcano-sh/volcano/blob/v1.15.3/docs/user-guide/how_to_use_capacity_plugin.md)要求启用 `capacity`、移除与之冲突的 `proportion`，并启用 `reclaim` action，才能按其示例实现回收。默认 Helm 配置是 `proportion` 且没有 `reclaim`；`preempt` 也没有默认启用。**照着 Capacity Queue 字段填额度，却不改调度流水线，不会得到文档中的借用与回收行为。** 而且加入 `reclaim` 也不是“一定能抢回”：还要考虑 Job 是否已经入队、队列和作业是否具备被回收条件、驱逐后能否重新推进。[v1.15 Actions 指南](https://github.com/volcano-sh/website/blob/master/versioned_docs/version-v1.15.0/Scheduler/Actions.md)还提示 `enqueue` 与 `preempt`/`reclaim` 的交互可能改变预期行为。不同发行版可能修改默认配置，上线应以实际 ConfigMap 与镜像为准。

| 看到的现象 | 不要立即下结论 | 先核对 |
| --- | --- | --- |
| Pod Pending、节点还有 GPU | “Gang 算法坏了” | `schedulerName`、Queue、PodGroup 最小门槛、节点硬约束、设备库存 |
| 借用可以，归还不发生 | “Queue 配置没有用” | 使用 Capacity 还是 Proportion、`reclaim` 是否启用、队列 `reclaimable` |
| 一提交任务就扩容 | “加节点是正确的” | 是队列额度限制还是节点真的不足、目标版本是否支持 Gate 联动 |
| 高优先级任务迟迟不运行 | “PriorityClass 不生效” | 抢占 action/插件、可驱逐对象、Gang 完整性、目标节点是否可行 |
| 调度成功、训练性能下降 | “调度器已经做了拓扑感知” | 实际 GPU UUID/NUMA/NVLink、设备分配方、网络与应用指标 |

这里的复杂性是**自由组合带来的验证成本**，不是说 Volcano 完全不可观测，也不是“多配置几个 YAML 就一定出错”。官方提供 PodGroup/Queue 状态、事件、调度器日志和指标；但一个 Pending 作业可能同时受队列、整组门槛、节点过滤、卷和设备约束影响，单看 `kubectl describe pod` 的最后一条 Event 不一定能定责。官方的 [PodGroup condition reason 设计](https://github.com/volcano-sh/volcano/blob/v1.15.3/docs/design/podgroup-condition-reason.md)专门区分入队拒绝与调度失败，正说明诊断原因需要在不同阶段准确表达。

## 排查一个 Pending 作业，按四层收集证据

第一层是**路由与对象关系**。记录 Pod 的 `spec.schedulerName`、所属 Job/PodGroup、Queue，列出 `kubectl get pod -A -o wide`、`kubectl get podgroups.scheduling.volcano.sh -A` 和 `kubectl get queues.scheduling.volcano.sh`；对具体 Pod/PodGroup/Queue 执行 `kubectl describe`，查看 condition、Event 与最小成员数。CRD 名称和字段用当前集群 `kubectl api-resources` 核实。一个 Gang 因只满足七个而等待，可能正是预期行为，不应把所有 Pending 都视为调度器故障。

第二层是**生效配置**。读取部署所用的调度器 ConfigMap（官方默认 Helm release 名为 `volcano` 时常见名称是 `volcano-system/volcano-scheduler-configmap`），核对 `actions`、`tiers`、插件参数与当前调度器镜像版本；不要用 GitHub `main` 分支的示例替代实际部署版本。Helm 模板的 ConfigMap 名称取决于 release 名，也可能通过 override 或自定义 `--scheduler-conf` 换成另一份配置，应先检查实际挂载。[v1.15.3 Helm 调度器模板](https://github.com/volcano-sh/volcano/blob/v1.15.3/installer/helm/chart/volcano/templates/scheduler.yaml)。对“借用/回收”尤其要检查 `capacity` 与 `proportion` 是否误混、`reclaim` 是否开启、队列额度和优先级对象是否匹配。[v1.15.3 Capacity 指南](https://github.com/volcano-sh/volcano/blob/v1.15.3/docs/user-guide/how_to_use_capacity_plugin.md)。

第三层是**真实供给与绑定**。检查节点 allocatable/requests、污点、亲和性、PVC 拓扑、设备插件与资源声明；区分“八个 Pod 的总卡数够”与“满足每个 Pod 的节点和拓扑组合存在”。Pod 有了 `spec.nodeName` 但应用没 Ready，应转向 kubelet、容器运行时、卷、驱动与训练通信排查，不能继续把所有耗时算给 scheduler。

第四层是**控制循环**。按时间线关联调度器日志、PodGroup/Queue condition、Pod Event、扩容器日志与 Volcano `/metrics`。重点观察入队拒绝、调度失败、成功绑定的数量，按 Queue 的资源请求/分配、action/session 耗时及抢占/回收事件复原决策。v1.15.3 源码定义了 `volcano_schedule_attempts_total{result}`、`volcano_action_scheduling_latency_milliseconds{action}`、`volcano_plugin_scheduling_latency_milliseconds{plugin,OnSession}` 和 `volcano_queue_allocated_scalar_resources{queue_name,resource}` 等指标；前几项反映的是尝试、action、插件耗时，不能当成提交到应用 Ready 的端到端时间，毫秒单位也不能直接按秒画图。[调度器指标定义](https://github.com/volcano-sh/volcano/blob/v1.15.3/pkg/scheduler/metrics/metrics.go)；[Queue 指标定义](https://github.com/volcano-sh/volcano/blob/v1.15.3/pkg/scheduler/metrics/queue.go)。指标是否暴露、标签与采集范围仍以目标版本真实 `/metrics` 为准，不把[早期 metrics 设计文档](https://github.com/volcano-sh/volcano/blob/v1.15.3/docs/design/metrics.md)中的全部指标当作现成监控承诺。

## 怎么决定要不要用、怎么安全落地

如果企业主要是单 Pod 在线服务或简单 GPU Job，已经能用 Kubernetes 节点亲和性、PriorityClass 与现有调度器解决，先别为“以后也许需要 Gang”切换所有业务。若核心需求是作业准入、租户配额而不想替换 Pod 放置链路，可以评估 Kueue 与现有调度器组合；若确实需要统一的批作业 Gang、队列和抢占策略，再认真评估 Volcano。**Kueue 与 Volcano 不是所有场景的一对一替代品**；两者组合时必须明确谁负责准入、Suspend、PodGroup 和抢占，避免重复控制。[Kueue Overview](https://kueue.sigs.k8s.io/docs/overview/)；[对比实验设计](kueue-vs-volcano.md)。

真正的验收应覆盖这些反例：

1. 一个八成员任务只具备七个成员的资源时，不能让先启动的成员长期占卡；整组资源可用后要按时启动。
2. 两个部门互借 GPU 后回收，量化被驱逐作业的 checkpoint 损失、重新排队与恢复时间，而不是只统计队列用量。
3. 节点已满、队列额度耗尽和缺指定 GPU 型号时，分别触发正确的等待或扩容行为。
4. 节点只有跨 NUMA 的碎片 GPU 时，硬拓扑需求不得被“节点上有四张卡”掩盖。
5. 调度器、Webhook 或扩容器故障和升级期间，PodGroup/Queue 不会卡在无人处理的状态；能回滚到已验证的配置。

每项测试保存提交时间、队列状态、PodGroup 条件、Pod Event、调度配置快照和作业实际启动/恢复时间。先在单个队列与专用节点池灰度，明确 `schedulerName` 及应用模板的切换范围。回退前处理仍由 Volcano 管理的 Pending Pod；换掉新任务模板不会自动让旧 Pod 改由默认调度器接管。

已经稳定运行 Volcano Job/Queue 的平台，也不必因一个设备拓扑用例就整体迁移调度系统。让 Volcano 保留 Queue/Gang 职责，单独补齐设备级信息和分配约束，可能比替换整个控制面更稳妥；但组合方案也要验证对象所有权、版本兼容与失败恢复。

Volcano 的价值不在于替企业把所有复杂性抹掉，而是给批调度提供一套可组合的控制面。**它能解决一组 Pod 怎样竞争资源，但不能独自保证具体设备拓扑、扩容策略、训练容错和业务公平契约。** 把这些边界写清，再用真实任务验证插件组合和失败路径，才是让调度器服务企业问题，而不是让企业问题迁就调度器。

参考资料：

Volcano v1.15.3 调度器默认配置：https://github.com/volcano-sh/volcano/blob/v1.15.3/installer/helm/chart/volcano/config/volcano-scheduler.conf

Volcano 调度器配置指南：https://github.com/volcano-sh/volcano/blob/v1.15.3/docs/user-guide/how_to_configure_scheduler.md

Volcano Capacity 插件指南：https://github.com/volcano-sh/volcano/blob/v1.15.3/docs/user-guide/how_to_use_capacity_plugin.md

Volcano Scheduling Gates Queue Admission：https://github.com/volcano-sh/volcano/blob/v1.15.3/docs/user-guide/how_to_use_scheduling_gates_queue_admission.md

Volcano GPU NUMA Issue #4998：https://github.com/volcano-sh/volcano/issues/4998

延伸阅读：[Kubernetes 调度器扩展](../scheduling/kubernetes-scheduler-extensions.md)、[GPU 与异构资源调度](../gpu-scheduling.md)。
