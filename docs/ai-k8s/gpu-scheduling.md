---
title: GPU 与异构资源调度
description: 整卡、MIG、共享、拓扑、亲和性和资源碎片治理
status: evolving
last_reviewed: 2026-08-02
---

# GPU 与异构资源调度

GPU 集群最难的部分通常不是“安装 CUDA”，而是长期保持驱动、运行时、设备插件、调度策略和监控数据彼此兼容。本页从平台工程视角说明 Kubernetes 如何管理 GPU，以及什么时候应使用共享、Kueue、Volcano 和 DRA。

## 一、GPU 软件栈的职责边界

```text
训练或推理容器
    │ CUDA / ROCm / XPU Runtime
    ▼
Container Toolkit 与 CDI
    │ 把设备、库和环境注入容器
    ▼
Device Plugin 或 DRA Driver
    │ 发布设备库存并完成分配
    ▼
kubelet / scheduler / Kueue
    │ 节点放置、队列准入、配额和拓扑
    ▼
内核驱动 / GPU / NVLink / RDMA 网络
```

NVIDIA GPU Operator 将驱动、Container Toolkit、Device Plugin、GPU Feature Discovery、MIG Manager 和 DCGM Exporter 作为一个可协调升级的软件栈管理。它减少了手工安装，但不意味着所有组件都可以随意跨版本组合；生产升级仍要核对 Kubernetes、操作系统、内核、驱动和 GPU Operator 的支持矩阵。

参考：[NVIDIA GPU Operator](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/)

## 二、四种 GPU 使用方式

| 方式 | 隔离 | 适合场景 | 主要限制 |
| --- | --- | --- | --- |
| 整卡独占 | 显存和计算独占 | 训练、大模型推理、性能基准 | 小任务利用率可能很低 |
| MIG | 硬件级显存和故障隔离 | 多租户推理、稳定切分 A100/H100 等支持 MIG 的 GPU | 配置档位固定；切换几何形状可能需要清空任务甚至重启节点 |
| Time-Slicing | 仅时间复用，没有显存和故障隔离 | Notebook、开发测试、低强度推理 | 一个任务 OOM 或异常可能影响同卡其他任务；单容器归因更困难 |
| MPS | CUDA 进程级并发共享 | 同一信任域、计算利用率不高的小任务 | 运维和隔离模型更复杂，并非所有负载都收益 |

NVIDIA 官方文档明确指出，Time-Slicing 不提供 MIG 的显存或故障隔离；申请多个共享资源也不代表获得成比例的算力。因此不要把 `nvidia.com/gpu: 4` 的共享卡误解为四张独占卡。

参考：[Time-Slicing 与 MIG 对比](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/25.3/gpu-sharing.html)、[GPU Operator MIG](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/gpu-operator-mig.html)

### 推荐原则

- 训练和延迟敏感的大模型推理默认使用整卡。
- 需要强租户隔离且 GPU 支持时使用 MIG。
- 开发环境可以使用 Time-Slicing，但要限制命名空间、并发和显存使用。
- 同一资源池不要让“独占”和“共享”只靠口头约定，应该用节点池、标签、RuntimeClass 或不同 ResourceFlavor 明确隔离。

## 三、从节点标签到设备属性

传统 Device Plugin 将 GPU 暴露为整数扩展资源：

```yaml
resources:
  limits:
    nvidia.com/gpu: 1
```

它简单稳定，但表达能力有限。工作负载若要求特定 GPU 型号、显存或网络拓扑，通常还要依赖节点标签：

```yaml
nodeSelector:
  nvidia.com/gpu.product: NVIDIA-H100-80GB-HBM3
```

这种模型描述的是“节点上有某种设备”，而不是每块设备本身。Dynamic Resource Allocation（DRA）增加了 `DeviceClass`、`ResourceSlice` 和 `ResourceClaim`，让 Driver 发布设备级属性，工作负载再按能力申请具体设备。

适合逐步引入 DRA 的情况：

- 同一集群包含多代、多型号或可分区设备；
- 希望表达显存下限、候选设备回退或设备级健康状态；
- 需要对 fabric-attached device、GPU 分区和共享容量建模；
- 厂商 DRA Driver 已覆盖当前硬件和升级场景。

暂时保留 Device Plugin 的情况：

- GPU 型号单一、整卡独占已经满足需求；
- 厂商 Driver 尚未提供生产支持；
- 现有监控、计费和准入策略强依赖扩展资源；
- 团队还没有测试 Driver 重启、节点 drain、Claim 回收和回滚。

参考：[Kubernetes DRA](https://kubernetes.io/docs/concepts/scheduling-eviction/dynamic-resource-allocation/)

## 四、Pod 调度、队列准入和集群扩容不是一件事

| 决策 | 常见组件 | 回答的问题 |
| --- | --- | --- |
| 工作负载准入 | Kueue | 哪个 Job 现在有资格使用多少配额？ |
| Pod 放置 | kube-scheduler / Volcano | Pod 具体落到哪个节点？ |
| 节点供给 | Cluster Autoscaler / Karpenter | 是否要创建或删除 GPU 节点？ |
| 设备分配 | Device Plugin / DRA Driver | 容器最终获得哪一块设备？ |

如果这四层边界不清楚，经常会出现“队列已经准入，但节点扩不出来”“节点已经创建，但分布式任务只调度了一半”或“Pod 在运行，却拿错 GPU 型号”等问题。

## 五、Kueue 与 Volcano 怎么选

### Kueue

Kueue 不替代 kube-scheduler。它在 Pod 创建或运行前做工作负载级准入，提供：

- `ClusterQueue` 与 `LocalQueue`；
- 多租户配额、借用、公平共享和抢占；
- `ResourceFlavor` 表达 H100、A100、Spot 等资源类型；
- All-or-Nothing、部分准入和动态归还；
- Topology-Aware Scheduling 与 MultiKueue；
- 对 Job、JobSet、Kubeflow Trainer、KubeRay 和 LeaderWorkerSet 的集成。

Kueue 适合希望保留 Kubernetes 原生调度链，只增加队列和配额治理的团队。

### Volcano

Volcano 提供独立批调度器，强项包括：

- PodGroup 与 Gang Scheduling；
- Queue、DRF、公平、优先级、抢占和回填；
- 面向 AI、HPC、Spark、Flink、Ray 等混合负载；
- 更可控的调度插件链和在线/离线混部策略。

Volcano 适合已有大量批任务、需要统一调度算法或对 Gang/抢占行为有更强控制的集群。

### 简单决策

| 需求 | 优先评估 |
| --- | --- |
| 在标准 Kubernetes 上增加配额和 Job 队列 | Kueue |
| 复杂 Gang、DRF、回填和批调度策略 | Volcano |
| 已有稳定 kube-scheduler 扩展，不想再引入第二调度器 | Kueue |
| AI、HPC、大数据统一由专用批调度器管理 | Volcano |

参考：[Kueue Overview](https://kueue.sigs.k8s.io/docs/overview/)、[Kueue Topology-Aware Scheduling](https://kueue.sigs.k8s.io/docs/concepts/topology_aware_scheduling/)、[Volcano Architecture](https://volcano.sh/docs/home/architecture/)

## 六、拓扑为什么直接影响训练成本

多机训练的 All-Reduce 或 All-to-All 会大量交换数据。GPU 数量相同，跨机架、跨交换机与同机 NVLink 的实际训练时间可能完全不同。因此调度不能只满足“总共有 32 张 GPU”，还要考虑：

- GPU 是否在同一节点、同一 NVLink Domain；
- 节点是否位于同一机架或网络 Block；
- RDMA / RoCE 接口、NUMA 和 CPU 亲和；
- 数据是否在本地 NVMe 或同可用区存储；
- Spot 与 On-Demand 节点是否混在同一分布式任务中。

建议给节点维护稳定的拓扑标签，由 Kueue TAS 或调度器决定 Pod 组需要“尽量集中”还是“必须位于同一拓扑域”。不要让训练脚本自己猜测物理拓扑。

## 七、容量与配额模型

GPU 平台至少需要三种口径：

1. **物理容量**：实际 GPU、MIG 实例和可用显存。
2. **可分配容量**：扣除故障、维护、平台预留后的容量。
3. **承诺容量**：各团队的 nominal quota，以及允许借用的上限。

推荐记录的运营指标：

| 指标 | 用途 |
| --- | --- |
| GPU allocation ratio | 已分配 GPU / 可分配 GPU，衡量调度占用 |
| SM utilization | 判断任务是否真正使用计算能力 |
| Framebuffer memory | 发现显存不足或长期空占 |
| Queue wait time | 衡量配额和容量是否匹配需求 |
| Admission failure reason | 区分缺配额、缺型号、缺拓扑还是扩容失败 |
| Job completion / retry rate | 判断平台稳定性和浪费 |

DCGM Exporter 可以把 GPU、MIG 和部分 DRA 归属信息暴露给 Prometheus；使用 Time-Slicing 时要注意单容器指标归因限制。

参考：[DCGM Exporter](https://docs.nvidia.com/datacenter/dcgm/latest/installation/install-dcgm-exporter.html)

## 八、生产检查清单

- [ ] 固定并记录 Kubernetes、内核、驱动、Toolkit、GPU Operator 版本矩阵。
- [ ] 节点池按 GPU 型号、共享策略和网络能力分组。
- [ ] 设置 GPU 工作负载专用 taint，避免普通 Pod 占用昂贵节点。
- [ ] 为每个团队定义队列、nominal quota、借用与抢占策略。
- [ ] 分布式任务使用 Gang/All-or-Nothing，避免部分启动长期占卡。
- [ ] 将机架、Block、NVLink/RDMA 能力纳入拓扑调度。
- [ ] 监控 XID、温度、功耗、显存、SM、队列等待时间和失败原因。
- [ ] 验证节点 drain、驱动升级、MIG 重配和 DRA Driver 重启流程。
- [ ] 对共享 GPU 明确隔离承诺，不把 Time-Slicing 宣称为强隔离。
- [ ] 计费同时使用申请量、占用时间和有效利用率，避免只按 Pod 数计费。

下一篇：[RDMA 与 AI 高速网络](rdma-networking.md) 会进一步解释 GPU、NIC、RoCE/InfiniBand 和 Kubernetes 网络组件如何连接起来。
