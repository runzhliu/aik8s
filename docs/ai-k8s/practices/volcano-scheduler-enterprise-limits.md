---
title: Volcano 功能很多，为什么企业里还是调不顺？
description: 从资源视图、任务分级、跨部门抢占共识与前置埋点出发，讨论 Volcano 调度和重调度落地的业务前提
status: evolving
last_reviewed: 2026-10-11
---

# Volcano 功能很多，为什么企业里还是调不顺？

设想一家企业把训练、推理和离线作业放进同一个 GPU 集群。平台团队看中 Volcano 的 Gang、Queue、公平共享、抢占和回收：希望八个 Worker 不再只跑两个，空闲 GPU 可以借给别的部门，高优先级任务来时还能拿回资源。功能清单看起来正中痛点。

真正上线前，业务却问了几个更难的问题：这批 H20 到底属于谁，哪部分可以借？在线推理扩容与正在跑的训练作业，谁的优先级更高？部门 B 借了部门 A 的卡，A 要用时允许中断 B 的哪类任务、提前多久通知、损失的训练进度谁承担？

这些问题没有答案，调度器就算正确执行了抢占，也可能被业务认定为一次事故。**Volcano 能执行资源规则，不能替企业决定什么规则是公平、可接受、可恢复的。** 这才是本文要讨论的落地门槛，而不只是某个插件如何配置。

以下部门和任务场景用于解释设计取舍，不是发生过的生产事故，也没有虚构吞吐或利用率收益。涉及 Volcano 行为的配置核对以 **v1.15.3** 发布标签为基线；具体效果仍以目标集群的工作负载和配置验证。

## 功能清单之前，先画出业务和资源的地图

Volcano 的能力是真实的：PodGroup 与 Gang 可以避免多 Pod 作业只启动一部分，Queue 能承载资源共享策略，调度 action 和插件还能组合优先级、回填、回收等机制。[Volcano 调度配置说明](https://github.com/volcano-sh/volcano/blob/v1.15.3/docs/user-guide/how_to_configure_scheduler.md)列出了 action、tier、plugin 的工作关系。但这些机制的输入，不能只是“我们一共有多少张 GPU”。

一个能做决策的资源视图至少需要分清：

| 需要知道的事实 | 不清楚时会发生什么 | 谁提供或维护 |
| --- | --- | --- |
| GPU 型号、UUID、MIG/整卡状态、故障与维护状态 | 把数量够误判为任务一定能运行 | 硬件、节点与设备管理团队 |
| CPU、内存、RDMA、NUMA、机架、存储与镜像可达性 | 调到有卡的节点，应用却启动失败或跑得慢 | 平台与基础设施团队 |
| 每个资源池的可分配量、部门保证量、借用量、硬上限 | “空闲可借”与“本部门随时要用”同时成立 | 容量负责人和部门 Owner |
| Pod/Job → Queue → 部门/成本中心 → 业务服务的归属 | 看得到卡被占，解释不了谁在用、为何占用 | 提交平台、业务系统与 FinOps |
| 任务的最低资源、最晚开始时间、运行时长与恢复能力 | 无法判断等待、回填或回收哪个代价更小 | 业务和训练/推理负责人 |

这里的“视图”不是要求另造一个万能 CMDB。最小可用做法是把节点与设备库存、Queue/Job 归属、资源申请和实际占用用稳定 ID 串起来，并记录数据更新与失效时间。`nvidia.com/gpu: 4` 只表示整数资源需求；它不自动表示是哪四张卡、是否在同一个 NUMA 域。Volcano 社区的 [GPU NUMA Issue #4998](https://github.com/volcano-sh/volcano/issues/4998)就讨论了标准整卡 GPU 在节点内拓扑上的这类边界；具体见[四卡任务与 GPU 碎片](gpu-topology-fragmentation-scheduling.md)。

更重要的是，资源视图必须让**业务侧也看得懂**：一个 Queue 等了多久，是 GPU 数量不足、指定型号不足，还是本部门额度已满？这三种原因会产生不同的扩容、借用和预算决策。没有可解释的库存和归属，插件越多，争议越难厘清。

## 优先级不是一个整数，而是一份业务承诺

常见的第一步是给任务打上“在线 / 训练 / 开发”标签，再把在线任务设成最高优先级。这样的分类有帮助，但仍不足以直接打开抢占：在线服务是否已有足够冗余？生产训练是不是也有交付截止时间？小规模紧急实验能否打断一项已运行六小时、尚未保存 checkpoint 的作业？

建议由业务、平台和容量负责人共同确定一张决策表，而不是让每个提交者自行填 `PriorityClass`：

| 任务类别示例 | 允许等待多久 | 能否被中断 | 可恢复前提 | 对借用资源的要求 |
| --- | --- | --- | --- | --- |
| 有明确 SLO 的在线推理 | 由服务 SLO 倒推 | 通常要保持可用副本与容量底线 | 副本可迁移、流量能摘除 | 不以依赖可随时被回收的卡作为唯一容量 |
| 有交付期限的分布式训练 | 结合交付时间与整组启动时间 | 经业务确认后，部分时段可中断 | Checkpoint 可用且恢复经验证 | 最低整组资源必须可获得 |
| 无明确截止时间的离线/开发任务 | 可接受较长等待 | 可作为借用与回收候选 | 数据和中间状态可重建 | 标记为借入容量并展示可能的中断 |

这是讨论模板，**不是推荐所有企业都按这个顺序抢占**。最终要把“紧急”定义成有审批、有有效期、有预算和审计记录的服务等级，防止所有部门把自己的任务都标成最高优先级。不同部门还需约定：可借用比例、召回条件、通知窗口、工作日与非工作日规则、补偿或成本归属，以及谁有权在事故中暂停自动回收。

Volcano 能依据配置和对象状态做 Queue 排序、抢占与回收，但无法凭 `priority: 1000` 判断这份任务承诺是否已得到业务认可。**技术上的合法驱逐，不等于组织上的合理驱逐。**

## 借卡与重调度，先谈中断损失，再谈利用率

假设部门 A 的 GPU 暂时空闲，部门 B 的训练借来跑。A 恢复需求时，平台有能力把卡收回。容量看板可能因此很漂亮，但对 B 来说，一次驱逐的真实代价是：已训练但尚未落盘的进度、Checkpoint 写入时间、重新排队、镜像和数据重新加载、分布式通信重新建立，以及恢复后是否还在有效交付窗口内。

因此，“支持回收”要拆成一份双方认可的契约：

1. **哪些卡能借？** 保证量、可借余量、不可动用的在线安全底线和维护预留分别是多少？
2. **哪些任务能借？** 是否只允许可恢复的批任务进入可回收容量；长训练能否在指定时间窗内借用？
3. **什么时候还？** 原部门提交什么级别的需求才触发回收，多久前通知，等待 checkpoint 的最长宽限期是多少？
4. **还不了怎么办？** Checkpoint 失败、存储不可用或被驱逐任务无法恢复时，由谁处置、是否停用自动回收？
5. **怎么核算收益？** 除 GPU-hours 外，还要比较有效训练时间、重算损失和 SLO 违约；不能只靠集群利用率证明策略成功。

在 Volcano v1.15.3 Helm 默认配置中，actions 是 `enqueue, allocate, backfill`，插件包含 `proportion`，但**没有默认启用 `reclaim` 或 `preempt` action**。[默认调度配置](https://github.com/volcano-sh/volcano/blob/v1.15.3/installer/helm/chart/volcano/config/volcano-scheduler.conf)。官方 [Capacity 插件指南](https://github.com/volcano-sh/volcano/blob/v1.15.3/docs/user-guide/how_to_use_capacity_plugin.md)要求用 `capacity` 替代冲突的 `proportion`，并启用 `reclaim`，才能按该指南演示额度借还；`enqueue` 与回收/抢占的相互作用也需要逐项验证。[v1.15 Actions 说明](https://github.com/volcano-sh/website/blob/master/versioned_docs/version-v1.15.0/Scheduler/Actions.md)。

这不是“把 `reclaim` 加到字符串里就完成产品需求”。即使技术规则已生效，业务没有定义可回收任务、宽限期和恢复责任，越高效的回收反而可能制造越频繁的业务冲突。

## 要让高级特性丝滑，埋点必须在上线前

很多团队是在调度策略上线后，才发现报表只能显示 Pod Pending 和 GPU 利用率；到时再追问“谁抢了谁、为什么、损失多少”，缺少必要的关联数据。调度、重调度与异构资源调度应共享一条可审计的决策链：

```text
业务请求与 Owner → 任务类别 / SLO / 可中断性 → Queue / 配额 / 优先级
        → 调度与设备分配 → 运行状态 → 回收/重启 → 业务结果
```

至少在提交入口统一工作负载 ID、部门/成本中心、资源类型与型号、任务最小成员数、截止时间或 SLO、Checkpoint 能力和恢复入口（不记录敏感的数据路径）。调度阶段记录入队、拒绝、节点选择、PodGroup 状态、抢占/回收的触发方与受影响方；运行阶段关联 GPU UUID、实际使用和整组 Ready 时间；恢复阶段记录 checkpoint 成功率、恢复耗时和被迫重算的有效计算量。**计量不等于把所有业务字段都塞进 Prometheus 标签**：队列和资源池用低基数标签，逐作业 ID、操作人和审批理由进入结构化事件或审计日志。

Volcano v1.15.3 的源码提供 `volcano_schedule_attempts_total{result}`、action/plugin 耗时以及 Queue 标量资源分配等指标：[调度器指标定义](https://github.com/volcano-sh/volcano/blob/v1.15.3/pkg/scheduler/metrics/metrics.go)、[Queue 指标定义](https://github.com/volcano-sh/volcano/blob/v1.15.3/pkg/scheduler/metrics/queue.go)。这些指标能解释调度器工作量，却不能单独回答业务的“从提交到训练真正开始用了多久”，更不能替业务计算 checkpoint 丢失的有效训练时间。目标集群仍要以真实 `/metrics` 核对是否暴露和标签口径。

同样，异构资源不是在 Queue 里多加一个型号名字就完成：GPU 型号、MIG/整卡、RDMA 与 NUMA 能力要有一致的库存与需求表达，Pod 被选中节点后的实际设备分配也应回写观测链路。需要同一 GPU 拓扑域的硬约束时，还要验证设备分配组件能否严格满足；不能把跨节点拓扑策略误当成节点内 GPU 分配保证。

## 排障难，有时是策略没定义清楚

一个任务 Pending，技术排查需要依次确认 `schedulerName`、Job/PodGroup 的最小成员与状态、Queue 额度和状态、调度器生效的 action/plugin、节点与设备库存、PVC 和污点约束，再看调度器日志、事件与扩容器行为。官方 [PodGroup condition reason 设计](https://github.com/volcano-sh/volcano/blob/v1.15.3/docs/design/podgroup-condition-reason.md)专门区分未入队与调度失败；二者表面都是“没跑起来”，责任和解决方式却不同。

v1.15.3 的 [调度器配置指南](https://github.com/volcano-sh/volcano/blob/v1.15.3/docs/user-guide/how_to_configure_scheduler.md)还说明：action 的顺序和插件在 tier 中注册的判断函数会影响结果，一个拒绝判断可能让后续插件不再执行。这是可组合能力的代价，不能只翻一条 Pod Event 就判断“Volcano 不行”。

但排障还有另一半不在日志里：如果没有人事先定义等待上限、谁能借卡、是否准许抢占、应用怎样恢复，**排出“被哪条策略挡住”仍不足以判断“这条策略应不应该存在”。** 平台需要把业务规则版本、审批记录和生效配置与调度事件放在同一条时间线上，否则团队最终只能争论算法，不知道争论的其实是组织内的资源契约。

## 平台负责人先交付什么，再启用什么

一个务实的落地顺序是：

1. **盘清资源与业务画像。** 建立按型号、拓扑、健康与部门归属可查询的资源视图；统计队列等待、作业长度和在线负载波峰，不先假设大家都适合抢占。
2. **签下优先级和借还规则。** 与业务部门确认保证量、借用上限、受保护工作负载、通知/宽限期和事故仲裁方式。没有跨部门共识时，先做可视化和手动审批借用，而不是直接开自动驱逐。
3. **把可恢复性做成准入条件。** 未验证 checkpoint 的长任务先别放入可抢占队列；对不同框架分别验证保存、重启、模型/数据状态恢复与最坏损失。
4. **先埋点后优化。** 保留提交→入队→整组运行→完成，以及回收→重新入队→恢复的时间线；用业务完成时间、有效 GPU-hours、SLO 和损失衡量结果。
5. **小范围打开能力。** 先用 Gang 处理确有整组资源要求的任务，再在两个达成共识的部门试点借还；根据真实需求选择 Proportion 或 Capacity、回收 action 和异构设备方案，不把整套“高级插件”一次性切给全公司。
6. **演练不理想的结果。** 七个成员有资源而第八个没有、借出的卡突然要归还、指定型号缺货、checkpoint 失败、调度器或设备插件升级；验收正确等待、正确告警和可恢复，而不只是 Pod 最终 Running。

主要是作业准入与配额、且希望沿用现有 kube-scheduler 的团队，可以对比 Kueue；大量批任务和多 Pod 作业、确实需要统一 Gang 与调度策略时，Volcano 仍可能是合适的核心组件。这不是替换名单，更不意味着换一个组件就可以跳过业务治理。[Kueue 与 Volcano 对比实验设计](kueue-vs-volcano.md)只给出测试维度，不是已测得的优劣排名。已有 Volcano 的平台，也无需因某个 GPU 拓扑缺口贸然更换整套调度系统；可以在明确对象所有权后补上设备级分配与观测链路。

**平台负责人最容易犯的错，是把调度器的高级特性当作业务设计的替代品。** Volcano 可以让 Queue、Gang、回填和回收更可控；但资源归属、优先级共识、中断成本和设备事实必须由企业自己定义，并提前形成可验证的数据链。提前量花在这些地方，后面的调度、重调度和异构资源管理，才有机会真正顺滑。

参考资料：

Volcano v1.15.3 默认调度配置：https://github.com/volcano-sh/volcano/blob/v1.15.3/installer/helm/chart/volcano/config/volcano-scheduler.conf

Volcano Scheduler 配置指南：https://github.com/volcano-sh/volcano/blob/v1.15.3/docs/user-guide/how_to_configure_scheduler.md

Volcano Capacity 插件使用指南：https://github.com/volcano-sh/volcano/blob/v1.15.3/docs/user-guide/how_to_use_capacity_plugin.md

Volcano Scheduling Gates Queue Admission：https://github.com/volcano-sh/volcano/blob/v1.15.3/docs/user-guide/how_to_use_scheduling_gates_queue_admission.md

Kubernetes Pod Priority 与抢占：https://kubernetes.io/docs/concepts/scheduling-eviction/pod-priority-preemption/

延伸阅读：[GPU 资源银行与潮汐推理平台实践蓝图](gpu-resource-bank-tidal-platform.md)、[GPU 与异构资源调度](../gpu-scheduling.md)。
