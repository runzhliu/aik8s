---
title: Kubernetes 调度器扩展：从一个 GPU 放置需求到插件落地
description: 以 GPU 节点池放置为例，解释 Scheduling Framework 扩展点、Profile、Extender 与独立调度器的边界，以及验证和回滚方法
status: evolving
last_reviewed: 2026-10-11
---

# Kubernetes 调度器扩展：从一个 GPU 放置需求到插件落地

假设推理团队有两类节点：一类有高速网络，适合跨机推理；另一类没有。Pod 申请一张 GPU 时，平台希望它**必须**落在具备相应网络能力的节点上，同时尽量把零散的一卡任务装箱，留出完整节点给多卡训练。

这听起来像“写一个调度插件”。但真正要先回答的是：高速网络是硬条件，还是软偏好？现有的节点标签、亲和性与资源打分能否表达？如果要扩展，应该把逻辑放在调度器的哪个环节？

本文讨论 kube-scheduler 的调度扩展，不把队列准入、节点扩容和设备分配混为一谈。下面的策略和配置是**设计示例，不是已实施的集群压测**；上线前需要按目标 Kubernetes 版本与 GPU 节点实际拓扑验证。

## 先确定问题属于哪一层

| 诉求 | 优先考虑 | 不要误以为 |
| --- | --- | --- |
| 指定 GPU 节点池、高速网络标签 | `nodeSelector`、节点亲和性、Taint/Toleration | 写插件才算“自定义调度” |
| 尽量装箱或分散 Pod | 内置 `NodeResourcesFit`、拓扑分布约束及其权重 | 调整打分就能改变硬性资源约束 |
| 按队列配额决定哪个训练 Job 先进入集群 | Kueue 等工作负载准入 | Pod 的 Score 能替代作业级配额 |
| 一组训练 Pod 要达到最低数量才推进 | Gang/Coscheduling 机制 | 给单个 Pod 加高优先级就能保证整组启动 |
| 按设备级属性选择具体 GPU | DRA Driver、Device Plugin 与节点侧分配能力 | 选中节点就等于选中了某张卡 |
| 节点放置需要自定义状态或算法 | Scheduling Framework 插件 | 在 Filter 中调用外部服务就没有延迟成本 |

例如，网络能力由可靠的节点标签表示时，用**必需节点亲和性**约束可用节点池，往往比维护一个只检查标签的自定义插件更简单。若希望保留完整的八卡节点，可以先在专用 GPU 节点池评估 `NodeResourcesFit` 的装箱策略；它按申请量与可分配量打分，不知道 GPU 实际利用率，也不能保证同一节点内的 NVLink/NUMA 设备组合。

需要注意：Pod 的 `schedulerName` 决定由哪个调度器处理；它本身不会限制节点池。队列控制器、节点自动扩容器和 kubelet 仍分别负责准入、供给与最终设备使用。

## 一次调度会经过哪些关口

可以把调度器看成给 Pod 找机房座位的前台。先决定谁进队列，再筛掉不满足硬条件的座位，对剩余座位排序；选中后先在本地账本记一笔，完成必要确认，再真正办理绑定。

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

上图省略了 PreEnqueue 等扩展点，也不是说每次都会走到 PostFilter：只有找不到可行节点时才会调用它。调度框架中的**调度周期串行执行，绑定周期允许并发**；节点级过滤和打分也可以并行。因此插件如果在逐节点 Filter 中做昂贵的远程查询，会随着候选节点和待调度 Pod 数增长，直接拖慢决策。

几个扩展点最容易被用错：

- **PreFilter / Filter**：前者准备本 Pod 的共享输入，后者判断节点是否满足硬条件。确定不能放置，就在 Filter 返回不可调度状态；不要靠极低的 Score 伪装硬约束。
- **PreScore / Score**：对已经可行的节点建立偏好。打分只能影响优先级，不能让被 Filter 排除的节点重新变成可用。
- **Reserve / Unreserve**：在真正绑定前记录插件自己的临时预留；后续失败要能撤销。调度器本地 assumed cache 与插件自定义的资源账本不是同一份东西。
- **Permit**：允许绑定、拒绝绑定或等待外部条件。等待有超时及拒绝/取消路径，不是永久持有资源的锁；用它实现 Gang 时还要处理组内失败、超时、回滚与控制器状态。
- **PreBind / Bind / PostBind**：绑定前校验、执行绑定和绑定后通知有不同责任。要自定义 Bind，必须明确与默认绑定插件的启用和回退关系，不能让两个组件都以为对方完成了绑定。

一个例子：平台有一个独立的网络容量控制器，标签只能说明“这个节点接了高速网络”，不能说明“当前是否还有可供新 Pod 使用的带宽”。插件可以在 PreFilter 解析 Pod 需求，在 Filter 用已同步的只读容量快照排除不合格节点，在 Score 优先选择更合适的节点。如果还需要跨 Pod 独占某个有限网络槽位，Reserve 与 Unreserve 必须维护同一份可撤销的预留状态。**不能只在 Filter 看一眼容量，绑定前却不处理并发变化。**

这里还有一致性边界：informer 缓存不是线性一致的全局锁。多个独立调度器进程也不共享 assumed cache。若网络槽位必须严格互斥，最终分配方需要原子校验或明确的冲突重试机制；仅靠节点过滤无法给出强保证。

## 扩展方式不是同一种“插件”

| 方式 | 运行位置与特点 | 适合场景 | 主要代价 |
| --- | --- | --- | --- |
| 内置配置与 Pod 约束 | 复用 kube-scheduler 现有插件 | 标签、亲和性、拓扑分布、资源装箱 | 表达不了专有外部状态 |
| Scheduling Framework 插件 | 编译进调度器进程，通过扩展点调用 | 需要定制过滤、打分、预留或许可 | 维护自定义镜像、版本升级与崩溃隔离 |
| Scheduler Extender | 调度器通过外部 HTTP 接口委托部分过滤/优选/绑定 | 已有外部决策服务且可接受调用开销 | 网络往返、超时、故障降级和兼容性 |
| 多 Profile | 一个调度器进程共享队列与缓存，不同 `schedulerName` 使用不同策略 | 同一进程内区分在线与批量 Pod | 不是独立调度吞吐；队列策略有共享约束 |
| 独立调度器 | 单独进程、缓存和选举配置 | 强隔离或独立演进的工作负载 | 更多 Watch、资源竞争与运维成本 |

**Profile 不是第二个调度器副本。** 多个 Profile 可以使用不同插件配置，但共享同一进程的队列；配置多 Profile 时，所有 Profile 的 `QueueSort` 插件及其配置必须一致。多个副本共享同一选举组时也只有 Leader 执行调度，不会因为多部署几个备用副本就增加单进程吞吐。

Extender 是外部 HTTP 扩展接口，不等同于框架插件。即使能通过外部服务复用已有策略，也应先算清每次调度的网络和失败成本，明确超时及不可达时究竟拒绝、重试还是按风险范围降级。对安全隔离或设备拓扑这种硬约束，不能默认“外部服务超时就放行”。

## 先用 Profile 验证策略，不要整套替换默认调度器

如果需求只是“网络节点池 + GPU 装箱”，第一轮可以不用写 Go 插件。Pod 用必需节点亲和性表达网络硬条件，再给该工作负载使用的 Profile 配置节点资源打分。例如：

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

`MostAllocated` 会在可行节点中倾向已分配资源更多的节点；示例权重 **4 不是推荐生产值**。实际放置仍受其他 Score 插件、请求量和可行节点集合影响，且节点上“剩余四张卡”不代表一定有满足指定 NUMA/NVLink 域的连续设备。示例镜像为占位符，不是可运行部署清单。

`requiredDuringSchedulingIgnoredDuringExecution` 的“ignored”表示 Pod 运行后节点标签变化不会仅因这条规则自动驱逐；这也提醒我们，调度时通过并不等于运行期间网络和设备始终健康。Profile 的名称要与 Pod `schedulerName` 对上，其他 Profile 与插件配置仍应保留原样；不能用上述片段覆盖现有生产配置。

如果内置策略确实无法表达网络容量状态，才开始实现 Framework 插件：明确每个扩展点读取哪份数据、状态何时过期、失败如何拒绝或重试，以及升级时如何保持版本匹配。插件与 kube-scheduler 链接，通常要按目标 Kubernetes 版本构建对应的二进制镜像，而不是把一个任意版本的 `.so` 热加载进正在运行的进程。

## 上线前，把失败路径也跑一遍

测试不只看“Pod 最终 Running”。至少构造以下场景，并核对实际 `spec.nodeName`、事件和应用就绪结果：

1. **硬条件验证**：只有无网络标签的 GPU 节点空闲时，Pod 应保持不可调度，而非为了提高成功率退到错误节点。
2. **容量与碎片**：一卡、四卡、八卡作业混合到达时，检查完整八卡节点剩余数、训练作业等待时间和实际设备拓扑；别只看装箱分数。
3. **缓存变化**：节点标签改变、设备下线、Pod 删除后，插件应及时重试有希望变得可调度的 Pod；事件唤醒和失败原因也要能对应。
4. **并发与回滚**：在 Reserve 后模拟 Permit 超时、PreBind 失败或绑定失败，确认 Unreserve 没有泄漏自定义槽位；多实例或多调度器共享池时检验冲突处理。
5. **依赖故障**：网络控制器或 Extender 超时、API Server 变慢时，明确哪些作业等待、哪些可以安全降级，不让不满足硬条件的 Pod 悄悄通过。
6. **策略隔离**：切换 `schedulerName` 的只是灰度工作负载；原默认调度器、节点亲和性、Taint 和资源池边界仍按预期工作。

观测也要分清口径：`scheduler_pending_pods` 看队列构成，`scheduler_schedule_attempts_total` 按结果看成功和重试，`scheduler_framework_extension_point_duration_seconds` 看阶段耗时；插件级执行耗时指标的可用性与标签应以目标版本的 `/metrics` 为准。Pod 创建到绑定的等待、绑定到 Ready 的启动耗时还需分别记录。不能把一次成功调度当作训练作业整体启动成功。

回滚预案应在切流前就确定：保留原 Profile/原调度器可用，先停止新 Pod 指向新 `schedulerName`，处理尚未绑定的旧 Pod，再回退插件镜像或配置。**已绑定 Pod 不会因为切换调度器而自动迁移**；如果新的调度器停掉，仍指向它的 Pending Pod 也不会自动被默认调度器接管。修改 Pod 模板后要核对存量 Pending Pod 的处理方式，避免留下一批无人调度的工作负载。

调度器扩展的目标不是把所有决策塞进一个插件，而是把**硬约束、软偏好、作业准入和设备分配**放在各自能负责的层。先证明内置能力不够，再为新增状态设计一致性、故障与回滚，调度策略才能从“选中一个节点”走到“让整组业务可靠运行”。

参考资料：

Kubernetes Scheduling Framework：https://kubernetes.io/docs/concepts/scheduling-eviction/scheduling-framework/

Kubernetes Scheduler Configuration：https://kubernetes.io/docs/reference/scheduling/config/

Kubernetes Scheduler Configuration API：https://kubernetes.io/docs/reference/config-api/kube-scheduler-config.v1/

Kubernetes Resource Bin Packing：https://kubernetes.io/docs/concepts/scheduling-eviction/resource-bin-packing/

Kubernetes Dynamic Resource Allocation：https://kubernetes.io/docs/concepts/scheduling-eviction/dynamic-resource-allocation/

Kubernetes 运行多个调度器：https://kubernetes.io/docs/tasks/extend-kubernetes/configure-multiple-schedulers/

延伸阅读：[大规模 Kubernetes 调度器优化](../practices/large-scale-kubernetes-scheduler-optimization.md)、[GPU 与异构资源调度](../gpu-scheduling.md)。
