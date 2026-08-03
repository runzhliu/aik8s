---
title: GPU 工作负载与节点自动扩缩容
description: 协调 HPA、KEDA、Kueue、Cluster Autoscaler 和 Karpenter，处理 GPU 冷启动、碎片和中断
status: evolving
last_reviewed: 2026-08-02
---

# GPU 工作负载与节点自动扩缩容

AI 平台的扩缩容不是一个 HPA。一次流量变化可能依次触发推理副本扩容、Pending Pod、GPU 节点创建、驱动和设备组件就绪、镜像拉取、模型下载以及缓存预热。任何一层缺少时间预算，自动扩容都可能在容量到达前超时。

## 一、四层弹性

```text
请求层
  并发、Token、优先级、排队和拒绝
        │
Pod/Workload 层
  HPA、KEDA、WVA、训练弹性、队列准入
        │
节点层
  Cluster Autoscaler、Karpenter、云厂商自动供给
        │
容量层
  预留、Spot、配额、区域库存和裸金属交付
```

Kueue 不创建节点，HPA 也不理解 GPU 是否能从云厂商获得。每层要有独立 SLO 和失败原因。

## 二、扩容时间线

```text
T0  流量或排队增长
T1  Autoscaler 生成新副本
T2  Pod Pending
T3  Node Autoscaler 决定创建节点
T4  云实例获得容量并启动
T5  kubelet、CNI、CSI、GPU Driver/Plugin Ready
T6  镜像和模型下载
T7  GPU 权重加载、图编译和预热
T8  Pod Ready，Gateway 开始送流量
```

记录每个阶段的时间。只监控 T0 到 T1 会严重低估大型模型的冷启动。

## 三、工作负载扩缩容信号

### 传统 HPA

CPU 对 LLM 推理通常不是主要瓶颈。HPA 更适合：

- 网关、Tokenizer、Embedding 或 CPU 服务；
- 已通过 Metrics Adapter 暴露的自定义指标；
- 保持至少一个副本的稳定在线服务。

### KEDA

KEDA 可以根据 Prometheus、消息队列等外部信号生成 HPA，并负责 0 到 1 的激活。适合：

- 批推理队列；
- 异步 Embedding；
- 请求队列或 Token 指标；
- 允许缩到零且能接受冷启动的模型。

### 推理专用信号

优先考虑：

- Waiting Requests / Queue Depth；
- Running Requests 与安全并发；
- Prompt/Generation Token Rate；
- TTFT、TPOT 和拒绝率；
- KV Cache 使用率；
- 模型加载状态；
- 预测的请求持续时间。

只使用 GPU Utilization 容易误判：Decode 可能显存带宽受限但 SM 利用率不高，长 Prompt 又会让 Prefill 出现短时尖峰。

## 四、一个 KEDA 思路示例

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: llm-server
spec:
  scaleTargetRef:
    name: llm-server
  minReplicaCount: 1
  maxReplicaCount: 8
  cooldownPeriod: 300
  triggers:
    - type: prometheus
      metadata:
        serverAddress: http://prometheus.monitoring.svc:9090
        metricName: llm_waiting_requests
        query: sum(llm_waiting_requests{model="example-model"})
        threshold: "8"
```

指标名是平台契约示例，应根据实际引擎指标和聚合方式调整。扩容前需要处理缺失指标、Prometheus 不可用和高基数问题。

## 五、Cluster Autoscaler 与 Karpenter

| 能力 | Cluster Autoscaler | Karpenter |
| --- | --- | --- |
| 节点来源 | 预定义 Node Group | 根据 NodePool 约束动态选择 Node |
| 云厂商覆盖 | 广 | 取决于 Provider 实现 |
| 节点生命周期 | 主要关注扩缩容 | 同时覆盖供给、过期、漂移和整合 |
| 实例选择 | 从已配置组中选择 | 根据 Pending Pod 和约束选择实例 |
| 适合 | 稳定节点组、多云一致模式 | 云上动态实例和快速迭代节点池 |

Kubernetes 官方将二者都列为 SIG Autoscaling 相关的 Node Autoscaler。具体能力和支持云以目标 Provider 文档为准。

参考：[Kubernetes Node Autoscaling](https://kubernetes.io/docs/concepts/cluster-administration/node-autoscaling/)

## 六、GPU NodePool 约束

一个 GPU NodePool 至少限制：

- 允许的实例/GPU 型号；
- 区域和可用区；
- On-Demand、Spot 或预留容量；
- 总 GPU/CPU/内存上限；
- 节点 Taint 与平台标签；
- OS/AMI/节点镜像；
- 过期、整合和中断预算；
- DaemonSet 资源开销；
- 本地盘和网络能力。

Karpenter 概念示例：

```yaml
apiVersion: karpenter.sh/v1
kind: NodePool
metadata:
  name: gpu-inference
spec:
  limits:
    nvidia.com/gpu: 32
  disruption:
    consolidationPolicy: WhenEmpty
    budgets:
      - nodes: "1"
  template:
    spec:
      taints:
        - key: accelerator
          value: gpu
          effect: NoSchedule
      requirements:
        - key: karpenter.sh/capacity-type
          operator: In
          values: ["on-demand"]
```

Provider 还需要 NodeClass 等云资源配置，本例不能直接作为完整安装清单。

## 七、Scale from Zero 的前提

Node Autoscaler 必须在节点不存在时仍能推断：

- 节点将提供什么扩展资源；
- 节点标签、Taint 和可用区；
- DaemonSet 会消耗多少 CPU、内存和 Pod Slot；
- DRA Driver/Device Plugin 与自动扩容是否兼容；
- 多节点任务是否需要原子拓扑；
- 云配额和实例库存是否允许供给。

如果自动扩容器看不到未来 GPU 资源，Pending Pod 不会触发节点创建。厂商托管 Kubernetes 常通过节点模板或 NodePool 元数据补充这些信息。

## 八、队列与节点供给

Kueue 通常只在配额可用时准入 Workload。常见策略：

### 先准入再扩节点

优点：简单，Pending Pod 触发 Node Autoscaler。风险：配额有但云容量不足，已准入任务长期等待。

### ProvisioningRequest

先由 Kueue/Autoscaler 协调容量供给，再完成准入。适合昂贵、稀缺或需要预留的整组容量，但组件集成和状态机更复杂。

### 保留最小容量

在线推理保留 Warm Pool，训练和批处理再弹性扩容。它牺牲少量空闲成本换取可预测延迟。

必须让用户看见“等待配额”“等待云容量”“等待节点启动”和“等待模型预热”的区别。

## 九、多节点任务与原子扩容

一个 16 节点任务不能接受只创建 9 个节点后无限等待。需要考虑：

- Gang/All-or-Nothing 准入；
- 云供应商是否能原子获得整组容量；
- 同一网络 Block/Placement Group/TPU Slice；
- 部分容量失败后的释放；
- 超时后是否换区域、型号或队列；
- 创建后未及时启动任务的成本泄漏。

对于 TPU Slice、UltraServer 或高带宽网络域，节点数量和拓扑是同一个资源请求的一部分。

## 十、缩容与中断

节点缩容不应只看“GPU 利用率低”。先判断工作负载是否可安全移动：

- 在线推理是否有其他 Ready 副本；
- 模型缓存重建需要多久；
- 训练是否完成 Checkpoint；
- 本地 NVMe 是否只有唯一数据；
- PDB、Kueue 和终止宽限期是否一致；
- DRA Claim、RDMA 连接和多机组如何释放；
- Canary/发布期间是否允许扰动。

在线 GPU 节点建议使用保守整合策略，批处理节点可以在 Job 完成后更积极地缩容。

## 十一、Spot 与抢占

适合 Spot：

- 有可靠 Checkpoint 的训练；
- 可重试的批推理和数据处理；
- 低优先级实验；
- 可以跨型号或区域迁移的任务。

不适合仅依赖 Spot：

- 没有冗余的在线模型；
- 长时间无法保存状态的训练；
- 严格拓扑且很难重新获得整组容量的任务；
- 冷启动远大于平均可用窗口的工作负载。

中断通知要同时触发停止准入、Checkpoint/Drain 和指标记录。

## 十二、防止弹性控制器打架

典型冲突：

- HPA 扩副本，KEDA 同时管理同一个 Scale Target；
- VPA 重建 Pod，影响推理可用性；
- Karpenter 整合节点，Kueue 刚准入训练；
- Canary 流量变化触发 HPA，破坏实验比例；
- Prefill/Decode 两个 Autoscaler 失去平衡；
- Model Cache DaemonSet 尚未完成，Pod 已被判定 Ready。

每个可扩对象只能有一个最终写入者。不同控制器之间通过明确指标和保护窗口协调。

## 十三、容量保护

建议分层：

```text
硬下限：系统和生产推理最小容量
保护容量：单故障域、升级和突发预留
可借用容量：训练/实验可临时使用
弹性容量：云上按需或 Spot 扩展
```

当生产流量上升时，应先停止训练借用或新任务准入，而不是直接抢占已加载但低流量的推理副本。

## 十四、必须监控的指标

| 层级 | 指标 |
| --- | --- |
| 请求 | 到达率、排队、拒绝、TTFT/TPOT |
| Pod | Desired/Ready、扩容决策、Pending 原因 |
| 队列 | Admission、等待时间、配额、Flavor |
| 节点 | Provision 时间、失败、NotReady、整合 |
| 模型 | 下载、加载、预热和缓存命中时间 |
| 云容量 | 配额、库存不足、Spot 中断、价格 |
| 成本 | 空闲时间、冷启动浪费、单位 Token/Job 成本 |

端到端扩容 SLO 应从信号产生算到新增 Ready 容量，而不是只统计 Autoscaler Reconcile。

## 十五、故障模式

| 现象 | 常见原因 |
| --- | --- |
| HPA 已扩容但没有新容量 | GPU Pod Pending，节点未创建 |
| 节点创建后 Pod 仍 Pending | DaemonSet 开销、标签/Taint、Device Plugin 未就绪 |
| Pod Running 但未接流量 | 模型下载/加载、Readiness 或 Gateway 状态 |
| 扩缩容来回震荡 | 指标延迟、阈值过近、冷却不足 |
| 无法缩容 | PDB、本地数据、长训练、do-not-disrupt |
| 选择错误 GPU 型号 | NodePool 约束太宽或平台标签不一致 |
| 成本异常增长 | 创建后未准入、模型加载失败、整合被永久阻止 |

## 十六、生产检查清单

- [ ] 已记录从扩容信号到模型 Ready 的完整时间线。
- [ ] 推理扩容基于队列、Token 或延迟，而不是只看 CPU。
- [ ] Node Autoscaler 能识别未来 GPU 节点的资源和标签。
- [ ] Kueue 准入与节点容量不足有不同状态和告警。
- [ ] 多节点任务不会只供给部分容量后无限占用。
- [ ] 在线推理有 Warm Pool 和故障冗余。
- [ ] 缩容尊重 Checkpoint、PDB、本地缓存和 DRA Claim。
- [ ] Spot 中断路径经过真实演练。
- [ ] 每个 Scale Target 只有一个最终控制器。
- [ ] 端到端扩缩容 SLO 和成本可以持续回归。

## 延伸阅读

- [Kubernetes Node Autoscaling](https://kubernetes.io/docs/concepts/cluster-administration/node-autoscaling/)
- [Kubernetes Workload Autoscaling](https://kubernetes.io/docs/concepts/workloads/autoscaling/)
- [KEDA Scaling Deployments](https://keda.sh/docs/latest/concepts/scaling-deployments/)
- [Karpenter NodePools](https://karpenter.sh/docs/concepts/nodepools/)
- [Kueue ProvisioningRequest](https://kueue.sigs.k8s.io/docs/admission-check-controllers/provisioning/)
- [KServe Autoscaling with KEDA](https://kserve.github.io/website/docs/model-serving/predictive-inference/autoscaling/keda-autoscaler)
