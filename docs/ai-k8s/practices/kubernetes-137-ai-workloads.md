---
title: Kubernetes 1.37 对 AI/大模型有何实际价值：与 1.35 的逐项对比
date: 2026-08-27
authors:
  - runzhliu
categories:
  - Kubernetes
  - AI 基础设施
description: 从 Gang Scheduling、DRA、GPU 缩零、NUMA 与可观测性出发，分析 Kubernetes 1.37 相比 1.35 对训练和推理平台的真实收益与采用边界。
---

# Kubernetes 1.37 对 AI/大模型有何实际价值：与 1.35 的逐项对比

Kubernetes 1.37（Garhwal）于 2026 年 8 月 26 日发布，共包含 67 项增强：16 项进入
Stable、23 项进入 Beta、27 项进入 Alpha，另有 1 项废弃或移除。数字不少，但如果问题是
“升级后大模型会不会直接跑得更快”，答案仍然是：**不会因为 Kubernetes 版本变化就自动
提高 Token 吞吐、NCCL 带宽或 GPU 算力利用率。**

1.37 真正值得 AI 平台关注的，是 Kubernetes 开始把过去散落在 Device Plugin、第三方
Gang Scheduler、设备标签和自定义控制器里的能力，逐步收敛为原生 Workload 与 DRA
语义。与 1.35 相比，它主要改善的是“整组 GPU 能否一起拿到”“GPU 和网卡能否按拓扑
匹配”“坏卡能否被隔离”“空闲推理实例能否缩到零”以及“控制器在大集群里是否更可靠”。

## 先看结论

| 能力 | Kubernetes 1.35 | Kubernetes 1.37 | 对 AI/LLM 的实际价值 |
| --- | --- | --- | --- |
| 原生 Gang Scheduling | Alpha，第一版 Workload API | Beta，包含 PodGroup 排队并改善 livelock | 多机训练不再先占一部分 GPU 后互相等待 |
| Workload-aware Preemption | 尚是后续目标 | Beta | 抢占以整组任务能否推进为目标，减少无效驱逐 |
| Workload 共享 DRA Claim | 尚未具备完整工作负载语义 | Beta | 一组 Pod 可共享网卡或其他设备 Claim |
| 传统扩展资源接入 DRA | Alpha | Stable | 旧的 `vendor.example/gpu: N` 工作负载可渐进迁移到 DRA 驱动 |
| 设备 Taint/Toleration | 早期阶段 | Stable | 坏卡、降级卡、保留卡可以在设备粒度隔离 |
| 设备状态与健康信息 | 能力仍在演进 | 多项能力进入 Stable/Beta | Pod 状态可以说明分配了哪块设备、设备是否异常 |
| NUMA 设备属性 | 各驱动自行表达 | 标准 `resource.kubernetes.io/numaNode` Stable | GPU、NIC 等跨驱动设备有统一的 NUMA 对齐基础 |
| HPA 缩到 0 | Alpha | Beta，默认启用 | 低频 GPU 推理或队列消费者可以不再常驻空闲副本 |
| Memory QoS | Alpha | Beta，默认启用 | 在 cgroup v2 上降低内存压力对模型服务的干扰 |
| In-place Pod Resize | Stable | Stable，并增加抢占和内存盘动态扩容的 Alpha 延伸 | CPU、内存和 tmpfs 调整更少依赖重建 Pod |
| Job/JobSet/TrainJob/LWS/RayJob 原生接入 WAS | 各控制器自行适配 | 通用接入框架进入 Alpha | 长期有望减少各训练控制器重复实现调度逻辑 |

这里最值得投入验证的是前三项、DRA 的 Stable 能力和 HPA 缩零。表中标记为 Alpha 的
能力适合实验环境，不应仅因为“1.37 已支持”就直接开启到生产。

## 1. 从“逐个调 Pod”走向“调一个训练任务”

Kubernetes 1.35 首次引入 `Workload` API 和原生 Gang Scheduling，但二者都处于 Alpha。
它解决的基本问题是：一个需要 16 个 Worker 的训练任务，如果只调度成功 8 个，已经运行的
8 个 Pod 会白占 GPU，而且可能与另一个同样只拿到一半资源的任务形成死锁。

1.37 将原生 Gang Scheduling 推进到 Beta。调度器通过 Workload 和 PodGroup 执行
all-or-nothing 调度，并加入 PodGroup 排队、workload-aware preemption，以及多个工作负载
并发调度时的 livelock 修复。对同步数据并行、张量并行训练和 MPI/HPC 任务来说，这比某个
单 Pod 的调度延迟快几十毫秒更有价值：**要么整组开始，要么一张卡也不占。**

另一个变化是 Workload 级 DRA ResourceClaim 进入 Beta。某些设备不是“每个 Pod 一份”，
而是整组 Worker 共享同一组资源语义；1.37 可以让 PodGroup 关联 ResourceClaim 或
ResourceClaimTemplate，而不必由训练控制器为每个 Pod 手工制造 Claim。

不过这不等于 Kubernetes 1.37 已经替代 Volcano 或 Kueue。配额借用、公平共享、队列准入、
多集群派发和成熟的拓扑策略仍然是现有批调度系统的强项。特别是 Kueue 的官方文档明确提供
ClusterQueue、ResourceFlavor、多层拓扑和 MultiKueue 等能力。更现实的采用方式是：

1. 新集群先在隔离环境验证原生 WAS Beta；
2. 现有生产队列继续由 Kueue 或 Volcano 管理；
3. 等 TrainJob、JobSet、LeaderWorkerSet 和 RayJob 的通用 WAS 接入框架离开 Alpha，
   再评估减少第三方调度扩展，而不是立即重写平台。

## 2. DRA 从“新 API”变成可渐进迁移的设备底座

DRA 的核心 API 在 Kubernetes 1.34 已经 GA，因此不能简单写成“1.37 才支持 DRA”。
1.37 的变化在于，几项直接影响 GPU 平台落地的外围能力变得更成熟。

### 旧工作负载不用一次性改写

DRA Extended Resource Support 在 1.37 进入 Stable。管理员可以把传统扩展资源名映射到
DeviceClass，原有 Pod 继续请求类似下面的资源：

```yaml
resources:
  limits:
    accelerator.example/gpu: 8
```

实际设备分配则可以由 DRA 驱动完成，不要求每个业务团队立即学会并改写成 ResourceClaim。
这解决的不是 GPU 计算性能，而是平台迁移成本：基础设施可以先换设备管理后端，业务 YAML
再逐步采用 DRA 的选择器、Claim 和共享语义。

前提是厂商 DRA 驱动已经支持目标硬件和相应特性。Kubernetes API 进入 Stable，不代表
某个 GPU、NPU、RDMA 驱动已经自动兼容。

### 坏卡和保留卡可以只隔离设备，不必封整台机器

设备级 Taint/Toleration 在 1.37 进入 Stable。过去一块 GPU 出现 ECC、Xid 或链路异常时，
常见做法是给整个 Node 加 Taint，结果同机其他健康 GPU 也无法调度。DRA Device Taint
允许驱动或管理员只标记具体设备，并用 `NoSchedule` 阻止新分配，必要时用 `NoExecute`
驱逐正在使用它的 Pod。

这为自动故障闭环提供了更好的原语，但它不会取代 DCGM、驱动日志和带外硬件监控。正确的
链路仍然是“监控发现异常 → 控制器写设备状态或 Taint → 调度与恢复系统采取动作”。

### GPU、NIC 与 NUMA 对齐有了共同语言

1.37 将 `resource.kubernetes.io/numaNode` 定义为 Stable 的标准设备属性。不同 DRA 驱动
可以用同一个属性描述 GPU、RDMA NIC 或其他设备位于哪个 NUMA Node，避免各自发明字段。

1.37 还引入两个相关的 Alpha 能力：

- Derived Attributes 可以把不同驱动暴露的字段转换成可比较的虚拟属性，用于选择同 NUMA
  的 GPU 与 NIC；
- Device Compatibility Groups 可以提前表达 MIG、vGPU 等不能同时存在的设备配置，
  避免调度完成后才在设备准备阶段失败。

这两项很贴近多机训练和 GDRDMA，但目前仍是 Alpha。它们提供的是**正确选择拓扑的机制**，
并不会凭空产生 GPUDirect RDMA；实际收益仍取决于 PCIe/NVLink/NIC 拓扑、IOMMU、驱动、
固件、NCCL 与网络配置。

### 可观测性开始能回答“这个 Pod 拿到的设备怎么了”

1.37 中 ResourceClaim 的 `.status.devices` 进入 Stable，驱动可以报告已分配设备的状态，
例如网络设备分配的 IP。设备健康信息也可以进入容器的
`status.allocatedResourcesStatus`，让控制器和排障人员把 Pod 故障与具体设备关联起来。

需要注意两条边界：健康上报依赖驱动实现相应接口；Pod 终止后，设备健康状态不会继续更新。
所以它适合故障关联，不是完整的 GPU 历史指标数据库。

## 3. 原生缩零终于对低频 GPU 推理更实用

HPA Scale to Zero 在 1.37 进入 Beta 并默认启用。当 HPA 使用 Object Metric 或 External
Metric 时，可以设置 `minReplicas: 0`，在没有工作时把昂贵的 GPU 副本缩到零，再根据队列
深度或外部请求指标恢复。

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: gpu-inference
spec:
  minReplicas: 0
  maxReplicas: 4
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: gpu-inference
  metrics:
    - type: External
      external:
        metric:
          name: pending_inference_requests
        target:
          type: AverageValue
          averageValue: "1"
```

它适合离线生成、低频实验模型和可排队业务，不适合没有请求缓冲的在线低延迟接口。模型权重
拉取、GPU 初始化、CUDA Graph Capture 和 KV Cache 预热可能需要数十秒甚至数分钟；若网关
不能排队、探活和超时重试，缩零只会把省下的 GPU 成本变成首请求失败。

此外，缩零不能使用 CPU/内存 Resource Metric，因为零副本时没有 Pod 可以采样。生产方案
仍需要 Prometheus Adapter、外部指标系统或类似 KEDA 的事件源，以及模型缓存和冷启动治理。

## 4. 内存、监控和控制面可靠性的间接收益

这些能力不会直接改变 GPU Kernel，却会影响大模型服务是否稳定。

### Memory QoS 进入 Beta

1.37 在 cgroup v2 上使用 `memory.min`、`memory.low` 和 `memory.high` 提供内存保护与节流，
并默认启用 `MemoryQoS` Feature Gate。对大量使用 Page Cache、Pinned Host Memory、共享内存
或 CPU Offload 的推理 Pod，它有机会降低相邻负载造成的内存回收抖动。

但 `memory.high` 配置过激也可能制造延迟尖刺。升级后应同时观察容器工作集、PSI、OOM、
throttling 与 TTFT，而不是只看到 Feature Gate 默认开启就认为已经优化完成。

### metrics.k8s.io Stable 与 Native Histogram Beta

`metrics.k8s.io/v1` 在 1.37 进入 Stable，Native Histogram 支持进入 Beta。前者稳定了 HPA
与 `kubectl top` 使用的 CPU/内存接口；后者能改善 Kubernetes 控制面 Histogram 的存储效率
和分位数精度。

两者都不等于 Kubernetes 原生理解 GPU 利用率、TTFT、TPOT 或 KV Cache。模型服务指标仍要
由推理引擎、DCGM Exporter 和网关提供；Native Histogram 也要求 Prometheus 3.x 抓取链路
支持对应协议后才有意义。

### 大集群控制器更不容易把 etcd 拖垮

1.37 完成 Resilient Watch Cache Initialization 的稳定化：缓存初始化或恢复时，不再让昂贵
的 List/Watch 请求集中冲击 etcd，超出保护范围的请求会收到 429。对拥有大量 Job、Pod、
ResourceClaim 和自定义训练 CRD 的集群，这是控制面可靠性收益。

相应地，自研 Operator 必须正确处理 `Retry-After` 和指数退避。升级控制面但保留会对 429
立即重试的控制器，反而可能把保护机制变成新的重试风暴。

## 5. 1.37 里很有想象力、但暂时不要生产押注的能力

下面这些 Alpha 功能与 AI 场景关系很强，却更适合 PoC：

| Alpha 能力 | 可能的 AI 场景 | 当前限制 |
| --- | --- | --- |
| CompositePodGroup | 表达 P/D、Controller/Worker、多角色训练的层级 Gang | API 与控制器生态仍会变化 |
| WAS Controller API | 让 JobSet、TrainJob、LWS、RayJob 统一接入调度语义 | 接入框架尚未成熟 |
| `Job.spec.scheduling` | 普通 Job 直接声明 Gang、拓扑、Disruption 与 Claim | Alpha 且需要相关 Feature Gate |
| Pod Checkpoint/Restore | Spot 恢复、长任务迁移、推理进程预热 | 需要 CRI Runtime 实现新 RPC；不等于 GPU 状态可迁移 |
| 动态调整 Memory-backed `emptyDir` | 不重启扩容 `/dev/shm`、tmpfs Cache | Alpha、仅限显式调整的内存卷 |
| In-place Resize Preemption | 为关键 Pod 的 CPU/内存扩容主动释放节点容量 | Alpha，错误优先级可能驱逐其他重要任务 |

尤其要避免把 Pod Checkpoint/Restore 写成“可以热迁移大模型 GPU 进程”。Kubernetes 只定义
Pod 级 CRI 接口，CUDA Context、GPU 显存、RDMA Queue Pair 和分布式训练一致性仍需要运行时、
驱动和上层框架共同支持。

## 6. 从 1.35 升级前应先回答什么

### 升级有明确价值的集群

- 同时运行大量多机训练，经常出现部分 Worker 占卡等待；
- GPU、NIC、MIG/vGPU 等设备类型复杂，正在评估 DRA；
- 希望把故障隔离从 Node 粒度收敛到 Device 粒度；
- 有低频、可排队的 GPU 推理服务，希望原生 HPA 缩零；
- 控制面承载大量 Job、Pod 和 CRD，List/Watch 压力明显。

### 不应只为 1.37 升级的目标

- 提高 vLLM/SGLang 的 Token/s；
- 提高 NCCL 或 RDMA 带宽；
- 自动解决 GPU 碎片与配额公平共享；
- 自动替换 Volcano、Kueue、GPU Operator、DCGM 或推理网关；
- 在不改 Driver、Runtime 和监控的前提下获得完整 DRA 能力。

### 升级检查单

1. **不要从 1.35 跳过 1.36 直升 1.37。** Kubernetes 的版本偏差策略不支持
   `kube-apiserver` 跳过次要版本，应按 1.35 → 1.36 → 1.37 逐级升级。
2. 确认节点使用 cgroup v2。1.35 起 `failCgroupV1` 默认已经为 `true`；临时关闭它不是长期
   方案，Memory QoS 等新能力也依赖 cgroup v2。
3. 核对托管 Kubernetes、CNI、CSI、GPU/NPU 驱动、DRA 驱动和监控栈是否声明支持 1.37；
   上游发布不代表云厂商当天即可升级。
4. 在测试集群复现真实训练队列、Device Plugin/DRA、节点维护和模型冷启动，不要只运行
   `nginx` Smoke Test。
5. Beta 能力逐项灰度；Alpha Feature Gate 默认关闭，并准备 API 与行为变化的回滚路径。

## 我的判断

如果 1.35 是 Kubernetes 原生 Workload-aware Scheduling 的“起点”，1.37 就是第一次出现
可认真评估的 Beta 版本；如果 1.34 的 DRA GA 是设备 API 的“地基”，1.37 则补上了旧资源
兼容、设备隔离、状态和 NUMA 这些影响生产采用的墙和门。

因此，1.37 对 AI 平台的价值主要是**降低资源浪费、设备管理复杂度和故障不确定性**，不是
让单次推理凭空加速。生产集群可以开始做 DRA 与原生 WAS 的对照实验，但现阶段最稳妥的
路线仍是 Kubernetes 原生能力与成熟的 Kueue/Volcano、设备驱动、监控和推理网关组合使用。

## 参考资料

- [Kubernetes v1.37 发布公告](https://kubernetes.io/blog/2026/08/26/kubernetes-v1-37-release/)
- [Kubernetes 1.37 版本状态](https://kubernetes.io/releases/1.37/)
- [Kubernetes v1.35 发布公告](https://kubernetes.io/blog/2025/12/17/kubernetes-v1-35-release/)
- [Kubernetes v1.35：Workload-aware Scheduling](https://kubernetes.io/blog/2025/12/29/kubernetes-v1-35-introducing-workload-aware-scheduling/)
- [Kubernetes v1.36：Workload-aware Scheduling 的后续演进](https://kubernetes.io/blog/2026/05/13/kubernetes-v1-36-advancing-workload-aware-scheduling/)
- [Kubernetes v1.36：DRA 更新](https://kubernetes.io/blog/2026/05/07/kubernetes-v1-36-dra-136-updates/)
- [DRA 设备状态与健康可观测性](https://kubernetes.io/docs/concepts/resource-management/dynamic-resource-allocation/dra-observability/)
- [DRA Device Taints and Tolerations](https://kubernetes.io/docs/concepts/resource-management/dynamic-resource-allocation/device-taints/)
- [HPA 从零扩缩容](https://kubernetes.io/docs/concepts/workloads/autoscaling/horizontal-pod-autoscale/#scaling-to-and-from-zero)
- [Kubernetes Version Skew Policy](https://kubernetes.io/releases/version-skew-policy/)
- [Kueue Topology-aware Scheduling](https://kueue.sigs.k8s.io/docs/concepts/topology_aware_scheduling/)
- [Kueue All-or-nothing Scheduling](https://kueue.sigs.k8s.io/docs/concepts/all_or_nothing/)
