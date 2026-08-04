---
title: Kubernetes 跨集群与大规模 GPU
description: 从 Federation 演进到 MultiKueue、Karmada、OCM、MCS 和 Liqo，并结合大规模 GPU 训练与推理设计
status: evolving
last_reviewed: 2026-08-03
---

# Kubernetes 跨集群与大规模 GPU

Kubernetes 跨集群不是把多个集群简单拼成一个更大的集群。它至少包含集群生命周期、资源清单、工作负载放置、服务发现、网络互通、流量治理、数据复制和统一策略等不同问题。

对大规模 GPU 平台，最重要的边界是：

> 跨集群选择“整项工作在哪个集群运行”已经较实用；让同一次同步训练或同一个低延迟推理副本横跨多个远距离集群，仍是高约束场景。

如果忽略 GPU 拓扑、RDMA、数据位置和模型预热，只聚合各集群的空闲卡数，跨集群调度很容易得到一个“容量数字正确、任务却无法运行”的平台。

## 1. 为什么 AI 平台会走向多集群

常见驱动力包括：

- 单个集群的 API Server、调度器、网络或运维 Blast Radius 不应继续扩大；
- 训练、生产推理和交互开发需要不同的升级与安全边界；
- GPU 型号、驱动、OS、RDMA Fabric 或云厂商不同；
- GPU 容量分布在多个地域、数据中心或云账号；
- 数据主权、租户合规和网络隔离要求工作负载留在指定区域；
- 在线推理需要靠近用户，训练需要靠近数据与大规模算力；
- 本地容量不足时，希望把可恢复的批任务弹到公有云或合作集群；
- 边缘站点需要断网自治，不能依赖一个远端控制面持续在线。

多集群的收益主要是隔离、选择和独立故障，而不是免费获得一个更大的低延迟计算域。每新增一个集群，也会增加版本、身份、策略、Secret、镜像、模型、观测和灾备的一致性成本。

## 2. 从 Federation 到可组合多集群

### 2016—2017：Federation v1

Kubernetes 1.3 引入 Cluster Federation，1.5 又增加 `kubefed` 和更多联邦资源。早期思路是在一个 Federation Control Plane 中提供类似 Kubernetes 的 API，把 Deployment、Service、ConfigMap 等对象复制或分布到成员集群。

它证明了跨区域资源分发、服务发现和高可用的需求，但也暴露出问题：

- Kubernetes 本身 API 演进很快，联邦层难以同步覆盖全部资源；
- 一个对象跨集群后的副本、覆盖、冲突和状态聚合语义复杂；
- 集群注册、网络、身份、数据和流量并不能由资源复制自动解决；
- 用户容易把“联邦控制面可见”误认为“所有集群是一个调度域”。

参考：[Cluster Federation in Kubernetes 1.5](https://kubernetes.io/blog/2016/12/Cluster-Federation-In-Kubernetes-1-5/)

### 2018—2020：Federation v2 / KubeFed

Federation v2 转向可扩展的类型配置、放置和覆盖策略，并支持 Namespace 级联邦。上游当时已经明确，多集群问题空间太大，不存在一个适合所有场景的单一模型。

这段历史留下的关键经验不是“联邦失败，所以不能多集群”，而是：集群生命周期、应用分发、网络互通和请求路由应该解耦，各层以清晰 API 组合。

参考：[Kubernetes Federation Evolution](https://kubernetes.io/blog/2018/12/12/kubernetes-federation-evolution/)

### 2019—2023：能力按职责分化

生态逐步形成多条路线：

- Cluster API 用声明式资源管理集群创建、扩缩、升级和销毁；
- Open Cluster Management（OCM）使用 Hub-Agent、`ManagedCluster`、`Placement` 和 `ManifestWork` 管理成员集群与资源分发；
- Karmada 使用独立控制面、`PropagationPolicy`、集群调度和 Override 表达应用放置、分发与故障迁移；
- GitOps 控制器按集群或环境持续同步应用配置；
- Submariner、Cilium ClusterMesh、服务网格等解决不同范围的跨集群连接与服务发现；
- Liqo 把远端资源抽象为 Virtual Node，并提供 Offloading、网络和存储 Fabric；
- SIG Multicluster 推进 Cluster ID、Multicluster Services、Work 和 ClusterProfile 等通用 API。

### 2023—2026：从应用复制走向 Workload 放置

AI、HPC 和大规模批处理需要的不是简单复制 Deployment，而是让一个 Job 在合适的集群中整体获得配额和拓扑。

MultiKueue 采用 Manager Cluster + Worker Cluster：Manager 接收 Job，在候选 Worker 中创建远端 Workload，由最先满足准入条件的集群执行整项任务，再同步状态。它支持 Job、JobSet、Kubeflow Trainer、KubeRay、MPIJob、LeaderWorkerSet 等多类工作负载。

截至本页复核日期，MultiKueue 为 Beta 且默认启用。它的主要语义是**把一项工作派发到一个成员集群**，不是自动把一个分布式 Job 的 Worker 拆到多个集群。

参考：[MultiKueue](https://kueue.sigs.k8s.io/docs/concepts/multikueue/)、[MultiKueue TrainJob](https://kueue.sigs.k8s.io/docs/tasks/run/multikueue/trainjob/)

### 截至 2026 年的现状

多集群仍不是 Kubernetes 核心中的一个总开关，也没有一个上游实现同时成为集群生命周期、应用分发、网络和 Job 调度的唯一标准。SIG Multicluster 更侧重 Cluster Identity、MCS、Work、ClusterProfile 等互操作 API；具体数据面和高级策略由不同项目实现。生产平台的主流方向是按职责组合少量组件，并让成员集群保留自治能力。

## 3. 先把七个平面拆开

| 平面 | 需要回答的问题 | 常见能力/项目 | 不负责什么 |
| --- | --- | --- | --- |
| 集群生命周期 | 谁创建、升级、修复和销毁集群 | Cluster API、云托管集群 API | Job 放置和请求路由 |
| 清单与身份 | 有哪些集群、由谁管理、能力和健康如何 | ClusterProfile、OCM ManagedCluster、自建 Inventory | 保证实时可调度容量 |
| 应用与策略分发 | 哪些对象进入哪些集群，差异如何覆盖 | Karmada、OCM ManifestWork、Argo CD/Flux | 跨集群数据一致性 |
| 批作业派发 | 一个 Job 应进入哪个队列和集群 | MultiKueue、自建 Fleet Scheduler | 把同步 Job 自动拆跨 WAN |
| 服务发现与网络 | 服务如何被其他集群解析和访问 | MCS API、Submariner、Cilium ClusterMesh、Service Mesh、Liqo | 全局容量和模型感知路由 |
| 流量调度 | 用户请求进入哪个地域、集群和模型池 | DNS/GSLB、Anycast、Global Gateway、Inference Gateway | 创建 GPU 容量 |
| 数据与制品 | 数据、模型和 Checkpoint 在哪里、如何复制 | 对象存储、Registry、数据目录、缓存系统 | Collective 通信和 Gang Scheduling |

不要只按“多集群产品”选型。先确定需要哪几个平面，再决定每个平面的唯一权威来源和控制器所有权。

## 4. 当前常见架构模式

### 模式 A：Fleet / Hub-Spoke

```text
管理集群 / Hub
  ├── 集群清单、策略、GitOps
  ├── 全局队列或放置控制器
  └── 统一观测入口
        │
        ├── GPU Cluster A
        ├── GPU Cluster B
        └── GPU Cluster C
```

Hub 决定对象或任务进入哪个集群，成员集群保留自己的 API Server、调度器、队列和故障自治。OCM、Karmada、MultiKueue 和许多商业 Fleet Manager 都属于这类思路，但各自关注点不同。

这是大规模 GPU 平台最常见的起点。Hub 不应成为已运行训练进程或在线推理请求的同步数据路径；Hub 短时不可用时，成员集群内已经运行的服务应继续工作。

### 模式 B：GitOps 多目标部署

每个集群仍是独立环境，由 Git 中的基线、Overlay 和集群标签决定安装内容。它适合版本化平台组件、Runtime、策略和推理服务，但 GitOps 本身通常不会根据实时 GPU 空闲量选择训练目标。

### 模式 C：应用级跨集群

Karmada/OCM 等把应用副本、策略和状态分发到多个集群，适合区域级 Active-Active、灾备和统一发布。对于自定义 AI CRD，需要验证控制器能否理解资源需求、状态、依赖和健康语义；仅复制 CRD 对象不代表上层 Operator 已正确工作。

### 模式 D：资源 Offloading / Virtual Node

Liqo 等系统把远端集群资源抽象到本地调度视图，并提供资源反射和网络连接。它对云边协同、临时资源共享和不修改应用的 Offload 很有吸引力。

GPU 场景必须额外验证扩展资源、设备属性、Gang、拓扑、网络性能和故障语义。一个显示 `nvidia.com/gpu: 32` 的 Virtual Node，不能自动表达这 32 张卡是否位于同一 NVLink/RDMA 域。

### 模式 E：跨站点拉伸单集群

让一个 Kubernetes Control Plane 或 Node 集合跨多个远距离站点，表面上最简单，但会把 API、etcd、CNI、DNS、Webhook 和调度都暴露给 WAN 延迟与分区。

除非站点之间具备经过验证的低延迟专网、明确故障模型和厂商支持，否则不建议把跨地域 GPU 资源做成一个拉伸集群。多个自治集群通常更容易定义故障边界。

## 5. 主流能力怎样组合

| 能力 | 适合场景 | 对 GPU 平台的价值 | 关键限制 |
| --- | --- | --- | --- |
| Cluster API | 多集群创建、扩缩和版本生命周期 | 统一 GPU 集群模板和升级批次 | 不调度 Job，不复制模型 |
| MultiKueue | 批 Job 在多个集群间排队和派发 | TrainJob/JobSet/KubeRay 整体选择目标集群 | 默认不是跨集群 Worker 调度器 |
| Karmada | 应用传播、Override、跨集群放置与故障迁移 | 多地域推理副本、集群级容量放置 | AI CRD 可能需要 Resource Interpreter |
| OCM | 集群注册、Placement、ManifestWork、Policy | Fleet 清单、治理和应用分发 | 训练队列与 GPU 拓扑需其他组件 |
| Liqo | 远端资源 Offload、跨集群网络与存储 | 云边或合作集群的资源借用 | GPU 拓扑与高性能网络需单独证明 |
| MCS API | 标准化 ServiceExport/ServiceImport | 跨集群控制服务和内部服务发现 | SIG 不提供统一参考实现，也不是全局流量调度器 |
| ClusterMesh/Submariner | Pod/Service 跨集群连接 | 控制流、服务发现、区域级访问 | 不等于 RDMA/NCCL Fabric |
| GitOps | 多集群配置与版本收敛 | 驱动栈、Operator、Runtime 和服务发布 | 不理解实时 GPU 队列和请求负载 |

通常不需要把整张表全部安装。一个实用组合可能只是：GitOps 管平台基线，MultiKueue 派发训练，Global Gateway 调度推理；只有出现真实的跨集群 Service 访问需求时再引入 MCS/ClusterMesh。

参考：[Cluster API](https://cluster-api.sigs.k8s.io/)、[OCM Architecture](https://open-cluster-management.io/docs/concepts/architecture/)、[Karmada Concepts](https://karmada.io/docs/core-concepts/concepts/)、[Liqo](https://docs.liqo.io/)、[MCS API](https://multicluster.sigs.k8s.io/concepts/multicluster-services-api/)

## 6. Karmada 怎样与 AI/GPU 结合

Karmada 的核心定位是：使用 Kubernetes 风格的 API，把资源模板按策略放置和传播到多个自治集群，并汇总状态、处理差异和故障迁移。它不是集群创建工具、跨集群 CNI，也不是把所有成员集群变成一个 Node/GPU 调度域。

### 控制链路

```text
Resource Template
  Deployment / Job / KServe / TrainJob / LWS ...
        +
PropagationPolicy / ClusterPropagationPolicy
        +
OverridePolicy / ClusterOverridePolicy
        ▼
ResourceBinding
        ▼  karmada-scheduler 选择成员集群
每个目标集群一个 Work
        ▼
Push：控制面写成员集群 API
Pull：成员集群 karmada-agent 拉取并执行
        ▼
成员集群本地 Controller / Scheduler / Kueue
        ▼
健康、状态和副本信息聚合回 Karmada 控制面
```

Karmada Scheduler 做的是集群级决策；资源进入成员集群后，Pod 仍由该集群的 kube-scheduler、Kueue、Volcano 和设备插件完成节点与 GPU 分配。

参考：[Karmada Architecture](https://karmada.io/docs/core-concepts/architecture/)

### 核心对象与 AI 平台用途

| 对象/能力 | 作用 | AI/GPU 场景 |
| --- | --- | --- |
| `PropagationPolicy` | 选择资源和目标集群，定义副本分布、Spread 与 Failover | 把推理服务放到指定地域/GPU 集群，或将完整离线任务放到候选集群 |
| `ClusterPropagationPolicy` | 集群范围的传播策略 | 平台管理员分发公共 Runtime、监控和设备相关资源 |
| `OverridePolicy` | 按目标集群修改字段 | 覆盖镜像 Registry、StorageClass、模型 URI、ServiceAccount 或 GPU Flavor |
| `ResourceBinding` | 保存资源模板与集群调度结果 | 审计某个模型/任务最终进入了哪些集群 |
| `Work` | 面向一个成员集群的待执行 Manifest | 连接 Karmada 控制面与成员集群实际对象 |
| Resource Interpreter | 解释自定义资源的副本、组件、依赖、健康和状态 | 让 TrainJob、RayCluster、KServe/LWS 等 CRD 可被准确估算和汇总 |
| Cluster Resource Modeling | 汇总或建模成员集群可用资源 | 在集群级初筛 CPU、内存、Pod 和扩展资源容量 |

`OverridePolicy` 很适合处理“逻辑应用相同、成员集群细节不同”的情况。例如同一个模型服务在私有集群使用内部 Registry 和本地对象存储，在云集群使用云 Workload Identity 和另一种 StorageClass。差异应由策略表达，不要复制多份逐渐漂移的完整 YAML。

参考：[Propagation Policy](https://karmada.io/docs/userguide/scheduling/propagation-policy/)、[Override Policy](https://karmada.io/docs/userguide/scheduling/override-policy/)

### GPU 集群放置仍需二次准入

Karmada 可以根据成员集群标签、Taint、地域和资源模型筛选目标，也可以按集群可用资源分配副本。但平台不能只让它读取聚合的 `nvidia.com/gpu` 余量就直接承诺大型任务。

GPU 场景还要处理：

- 16 张空闲卡是否集中在同一 NVSwitch、Rack 或 RDMA Block；
- 本地 Kueue 队列是否已有更高优先级 Workload；
- GPU 型号、显存、MIG Profile、驱动和 CUDA/ROCm 是否匹配；
- 数据、模型缓存和 Checkpoint 是否在该集群可达；
- 成员集群状态上报到 Karmada 期间是否已经产生容量竞争。

因此推荐把 Karmada 的集群选择看成候选放置，再由成员集群的队列和调度器最终准入。默认 Cluster Resource Summary 也可能隐藏节点碎片；当前 Customized Cluster Resource Modeling 只支持 CPU、内存、存储和临时存储等基础资源分级，并不能直接描述 GPU/NVLink/RDMA 拓扑。AI 能力仍需要稳定的集群标签、Resource Interpreter、传播策略和本地拓扑调度共同表达。

参考：[Karmada Cluster Resource Modeling](https://karmada.io/docs/userguide/scheduling/cluster-resources/)

### AI CRD 为什么需要 Resource Interpreter

对原生 Deployment、Job 等对象，Karmada 内置了资源结构知识；对 TrainJob、RayCluster、RayJob、KServe 或自定义推理 CRD，Karmada 默认只看到一个普通自定义对象，不一定知道其中有多少 Worker、每个组件需要多少 GPU、依赖哪些 Secret，以及什么状态代表 Healthy。

Resource Interpreter 可以为 CRD 补充：

- `InterpretReplica`：提取单 Pod Template 的副本与资源需求；
- `InterpretComponent`：分别提取 Leader/Worker、Head/Worker 等多组件需求；
- `InterpretDependency`：找出 ServiceAccount、Secret、ConfigMap、PVC 等依赖；
- `InterpretHealth`：定义何时健康，可供状态和 Failover 使用；
- `AggregateStatus`：把成员集群状态汇总到控制面；
- `Retain`：保留由成员集群 HPA/Controller 管理的字段，避免双方反复覆盖。

截至本页复核日期，Karmada v1.16+ 的 `InterpretComponent` 和 `MultiplePodTemplatesScheduling` 仍为 Alpha、默认关闭。它虽然面向 TrainJob、RayCluster 等多组件 AI/大数据工作负载，但生产使用前必须固定版本、编写或确认 Interpreter、用 `karmadactl interpret` 验证，并测试容量估算、依赖传播和状态聚合。

参考：[Karmada Resource Interpreter](https://karmada.io/docs/userguide/globalview/customizing-resource-interpreter/)

### Karmada 适合推理，也能传播训练任务

**多地域推理**是更自然的 Karmada 场景：

1. 用 PropagationPolicy 选择地域、云厂商和 GPU 能力；
2. 用 Duplicate/Spread 让完整模型服务进入多个故障域；
3. 用 OverridePolicy 设置每个集群的模型 URI、身份和存储；
4. 由成员集群内 KServe/LWS/Deployment 创建并预热模型副本；
5. 全局 Gateway 只把流量发到模型 Ready 且有容量的集群；
6. 集群内 EPP/Router 再完成模型、KV Cache 和队列感知路由。

Karmada 也可以传播 Job 或 TrainJob，但要先明确语义：

- 如果目标是“同一个离线任务在多个集群各执行一份”，应用传播模型很合适；
- 如果目标是“多个候选集群中只选一个运行，并遵守租户队列与公平共享”，MultiKueue 的 Job Dispatch 语义通常更直接；
- 如果目标是“一个分布式训练的 Rank 横跨多个集群”，Karmada 不会自动提供 Gang、Rendezvous、NCCL/RDMA 和统一故障恢复。

### Karmada 与 MultiKueue 不是二选一

| 维度 | Karmada | MultiKueue |
| --- | --- | --- |
| 主要对象 | 通用 Kubernetes 资源与 CRD | Kueue Workload 和受支持 Job 类型 |
| 主要目标 | 应用传播、跨集群放置、Override、状态与 Failover | 批任务在多个 Worker Cluster 中排队并择一派发 |
| 多集群副本 | 可 Duplicate、Divide、Spread | 通常由一个目标集群执行完整 Job |
| 配额与公平共享 | 不是其主要队列模型 | 复用 Kueue ClusterQueue、Flavor 和准入 |
| AI CRD | 可能需要 Resource Interpreter | 需要对应 Job 类型的 MultiKueue 集成 |
| 适合推理 | 多地域发布和故障域放置 | 不是请求流量路由系统 |
| 适合训练 | 复制/放置完整资源，适合明确的传播语义 | 更适合队列驱动的整 Job 择一派发 |

两者可以在同一平台承担不同职责，例如 Karmada/GitOps 分发成员集群的 Trainer Runtime、推理服务和策略，MultiKueue 单独负责训练 Job 派发。但必须明确字段所有权，避免两个控制器同时创建或迁移同一 Job。

### Failover 不等于 GPU 进程热迁移

Karmada 能根据 Cluster 或 Application 健康触发迁移，也提供 Purge 和 Graceful Eviction 等策略。对于训练和有状态 AI 工作负载，真正可恢复仍依赖外部 Checkpoint、模型/数据可达和应用恢复入口。

Karmada 的 Application State Preservation 可以在故障迁移时提取并重新注入部分状态字段，但相关 Stateful Failover Injection 仍是 Alpha。它不能复制 GPU HBM、NCCL Communicator 或进程内训练状态。因此应把训练容灾表述为“由 Karmada 触发重新放置，再由应用从 Checkpoint 恢复”，而不是 Live Migration。

参考：[Karmada Application-level Failover](https://karmada.io/docs/userguide/failover/application-failover)

## 7. 跨集群 GPU 训练：优先整作业放置

### 推荐数据流

```text
用户提交 TrainJob
      ▼
全局队列：租户、优先级、预算、候选集群
      ▼
选择一个满足整组资源的 GPU 集群
      ▼
集群内 Kueue/Volcano：配额、Gang、拓扑
      ▼
JobSet/Trainer/KubeRay：创建所有 Rank
      ▼
NCCL/RDMA Fabric 内训练
      ▼
Checkpoint 写入跨集群可访问的对象存储
```

全局层负责选择集群，本地层负责精确的节点和设备调度。两层不要同时修改同一个 Pod 的放置结果。

### 集群选择不能只看空闲 GPU 总数

一个训练作业的目标集群至少要满足：

- 加速器厂商、型号、显存、精度和驱动/Runtime 版本；
- 完整 Gang 的 GPU 数，而不是最终一致的汇总空闲量；
- GPU 是否集中在可接受的 NVLink、NVSwitch、Rack 或 Network Block；
- RDMA、NCCL、MTU、带宽和 Oversubscription 等级；
- 本地队列能否准入，租户配额和优先级是否允许；
- 数据集、基础模型和容器镜像是否已就近可用；
- Checkpoint 位置、恢复带宽和对象存储出口成本；
- Spot/按需类型、价格、维护窗口和预期中断率；
- 数据地域、租户权限和合规约束。

建议由集群 Inventory 发布稳定的能力标签与容量摘要，本地调度器仍以实时状态做最终准入。全局层的缓存必然有延迟，因此“先提名候选集群，再由本地队列确认”比直接承诺节点更稳健。

### MultiKueue 的适用方式

Manager Cluster 保存用户 Job 和全局准入策略；每个 Worker Cluster 运行自己的 Kueue 和训练控制器。目标 Worker 完成 Workload 准入后，MultiKueue 在该集群创建 Job 镜像并同步状态。

平台还需保证：

- Namespace、LocalQueue、ResourceFlavor 与 Runtime 在成员集群存在且语义一致；
- 镜像、Secret、ServiceAccount、数据 URI 和模型 URI 在目标集群有效；
- Job 的最终状态、日志、指标和制品可回到统一门户；
- Manager 与 Worker 的配额口径不会长期制造虚假可用容量；
- 取消、超时和重试不会在两个集群同时运行同一任务。

### 哪些训练天然适合跨集群并行

以下工作单元通信松散，可以各自在一个集群内运行：

- 超参数搜索和多随机种子实验；
- 数据预处理、合成数据、Embedding 和离线评估；
- 多模型或多数据分片批推理；
- 可独立聚合结果的 Ensemble；
- 使用应用级协议且允许异步、低频聚合的 Federated Learning；
- Pipeline 中彼此通过对象存储交换制品的 Stage。

这类任务的最佳跨集群粒度通常是 Trial、Shard 或 Pipeline Stage，而不是单个 GPU 进程。

### 为什么同步训练通常不跨地域集群

DDP/FSDP、Tensor Parallel、Expert Parallel 会频繁执行 All-Reduce、All-Gather 或 All-to-All。它们的 Step Time 受最慢 Rank、链路时延和有效带宽约束。WAN 的延迟、抖动、丢包和带宽成本会在每个训练 Step 反复出现。

以下条件同时成立时，才值得评估单 Job 跨集群：

- 两个集群实际位于同一园区或同一低延迟高速 Fabric；
- 集群边界主要是管理边界，而不是物理网络边界；
- Pod/进程能获得稳定可路由地址、端口、身份和 Rendezvous；
- NCCL/RDMA 路径、MTU、QoS 和故障恢复有基准与支持矩阵；
- 训练框架支持弹性成员变化，或平台能整体重启全部 Rank；
- 收益通过端到端训练吞吐验证，而不是由链路标称带宽推断。

即便如此，也应先比较“合并为一个专用训练集群”或“整作业排队等待”的复杂度。

### 跨集群迁移不是 Live Migration

长训练从 Cluster A 切到 Cluster B，通常是：停止或失败 → 保存/选择 Checkpoint → 在 B 重新排队 → 恢复。平台应显式定义 RPO、RTO、Checkpoint 兼容性和数据可达性，不应把它描述成无损 Pod 迁移。

## 8. 跨集群 GPU 推理：复制服务，调度请求

### 推荐架构

```text
Client
  ▼
Global DNS / Anycast / Global Gateway
  ├── Cluster A：Gateway → InferencePool → GPU Pods
  ├── Cluster B：Gateway → InferencePool → GPU Pods
  └── Cluster C：Gateway → InferencePool → GPU Pods
          │
          └── 每个集群内完成模型并行、KV-aware Routing 和 P/D 配对

Model Registry / Object Storage
  └── 向各集群分发权重，并由节点缓存预热
```

每个推理集群都应是完整、可独立服务的故障域。全局层选择地域或集群，本地 Gateway/EPP 再根据模型、队列、KV Cache 和 Endpoint 状态选择具体副本。

### 全局路由与集群内路由分层

全局层适合使用：

- 用户地域、网络延迟和数据主权；
- 模型版本是否已部署并 Ready；
- 集群级可用容量、错误率、排队和熔断状态；
- 租户、成本、云厂商和故障域策略；
- 会话可迁移性与灾备优先级。

集群内层适合使用：

- 实时 Endpoint 队列和 Batch；
- Prefix/KV Cache 命中；
- LoRA/Adapter 是否已加载；
- Prefill/Decode 池平衡；
- 单副本 GPU、显存和健康状态。

不要把每次请求的高频 Endpoint 状态都同步到全球控制面后再决策。状态延迟会抵消智能路由收益，并把 WAN 变成请求关键路径。

### 模型与容量必须先于流量到达

区域故障切换不是只修改 DNS。目标集群还需要：

- 足够的保底 GPU 或可接受的扩容时间；
- 已复制并校验的模型、Tokenizer、Adapter 和配置；
- 节点本地模型缓存或可预测的下载带宽；
- 与源集群兼容的 Gateway、Runtime、Engine 和模型版本；
- 对象存储、KMS、Registry、身份和依赖服务可用；
- 长连接 Drain、请求重试和幂等策略。

冷集群可以降低成本，但其模型下载、节点供给和编译时间必须进入 RTO。严格 SLO 通常需要 Warm Standby 或 Active-Active 容量。

### 不要轻易把 TP/PP、P/D 或 KV 跨 WAN

一个模型副本内部的 Tensor/Pipeline/Expert Parallel 应尽量留在同一高速网络域。Prefill/Decode 分离需要传输大量 KV Cache，也通常应在同一数据中心或经过验证的低延迟网络中完成。

跨地域更合适的边界是完整请求或异步任务，而不是 Token 生成的内部阶段。只有经过 KV 大小、传输时间、取消、版本兼容和网络分区测试后，才考虑跨集群 P/D；“网络能通”远远不够。

### 多集群服务发现不等于智能推理路由

MCS、ClusterMesh 或 Service Mesh 可以让服务在多个集群中被发现和访问，但它们通常不了解模型、KV Cache、Token 队列和 TTFT。生产 LLM 平台仍需把全局流量选择与集群内 Inference-aware Routing 分层。

## 9. 训练与推理的结论并不相同

| 问题 | 大规模训练 | 在线推理 |
| --- | --- | --- |
| 推荐跨集群粒度 | 整个 Job/Trial/Pipeline Stage | 完整模型服务副本和单次请求 |
| 全局调度目标 | 找到可整体准入的 GPU + Fabric + 数据 | 地域、模型 Ready、容量、SLO 和合规 |
| 本地调度目标 | Gang、拓扑、队列、节点与设备 | Endpoint、队列、KV、Batch 和 Adapter |
| 故障恢复 | 从 Checkpoint 在原/其他集群重启 | 流量切走，Warm/Active-Active 接管 |
| 跨集群数据 | 数据集、Checkpoint、模型制品 | 模型、配置、Adapter，必要时会话状态 |
| 最不适合跨 WAN 的部分 | 每 Step Collective | TP/PP、KV 传输、P/D 内部链路 |

## 10. 一个可落地的分层参考架构

```text
全局管理层（不在同步数据路径）
  Cluster Inventory / GitOps / Policy / Cost / Global Queue
          │
          ├── 训练 Fleet
          │     MultiKueue Manager
          │       ├── Cluster A：Kueue + Trainer + RDMA
          │       └── Cluster B：Kueue + Trainer + RDMA
          │
          └── 推理 Fleet
                Global Gateway / DNS
                  ├── Region A：Gateway + EPP + Model Pool
                  └── Region B：Gateway + EPP + Model Pool

共享但不强耦合的基础设施
  Identity / Registry / Model Registry / Object Storage / Telemetry Backend
```

关键设计原则：

1. **全局粗粒度，本地细粒度。** 全局选集群，本地选节点、GPU 或 Endpoint。
2. **成员集群能自治。** WAN 或 Hub 故障不应立即中断已运行训练和在线推理。
3. **状态按用途分层。** Inventory 保存相对稳定能力，本地调度器掌握实时容量。
4. **数据先行。** Job 或流量迁移前先验证数据、模型、身份和依赖可达。
5. **故障域显式。** 集群、区域、网络 Block 和存储故障要有不同恢复策略。
6. **版本是一组制品。** Kubernetes、驱动、Runtime、Operator、CRD、模型和 Connector 一起发布。

## 11. 跨集群故障语义

| 故障 | 训练平台应如何处理 | 推理平台应如何处理 |
| --- | --- | --- |
| 管理 Hub 不可用 | 已运行 Job 继续；暂停新派发；恢复后对账 | 成员集群继续服务；全局配置冻结或降级 |
| Worker Cluster API 不可达 | 不重复派发同一 Job；确认租约/状态后再恢复 | 从全局健康池移除，但区分控制面与数据面状态 |
| 整个集群失效 | 从外部 Checkpoint 在其他集群重启 | 把请求切到有模型和容量的集群 |
| 跨集群网络分区 | 不让双边同时认为自己拥有任务 | 保持本地服务；停止依赖远端同步状态的路由 |
| 对象存储/Registry 不可用 | 已缓存任务可继续，否则停止准入 | 已加载模型继续；阻止需要冷加载的新版本 |
| 全局状态陈旧 | 由本地队列最终拒绝/准入 | 本地熔断和 Endpoint 健康覆盖全局建议 |
| 凭据或策略不同步 | 快速失败并给出目标集群差异 | 不把流量发往身份/策略未就绪版本 |

跨集群控制器必须有唯一任务身份、幂等创建、Lease/Ownership 和最终对账机制。网络分区后最危险的情况不是“暂时看不到”，而是同一个训练或发布在两个集群被重复执行。

## 12. 常见反模式

- 把 4 个集群各 8 张空闲 GPU 当成一个可运行 32 卡同步任务的资源池；
- 全局调度器直接依赖几秒甚至几分钟之前的 GPU 空闲数承诺容量；
- Karmada/OCM/MultiKueue/GitOps 同时管理同一对象字段，导致控制器互相覆盖；
- 先打通 Pod CIDR，再假定 NCCL、GPUDirect RDMA 或 KV 传输已经可用；
- 把 etcd、API Server 或单个推理副本跨远距离站点拉伸；
- 复制 Deployment，却没有复制模型、Secret、身份、Runtime、队列和 NetworkPolicy；
- 灾备集群没有 GPU 保底和模型预热，只在事故时才开始拉权重；
- 训练切换没有外部 Checkpoint，仍承诺集群级自动容灾；
- 把 MCS/Service Mesh 当作全局 GPU 调度或 LLM 智能路由；
- 只做正常路径 Demo，没有演练 Hub 失联、双写、取消和状态对账。

## 13. 怎样选择起点

| 需求 | 建议起点 |
| --- | --- |
| 统一创建和升级多个 GPU 集群 | Cluster API 或云厂商 Fleet/Lifecycle API + GitOps |
| 训练 Job 在多个集群中择一运行 | MultiKueue + 每集群本地 Kueue/Trainer |
| 多地域推理副本统一发布 | GitOps；需要复杂放置/Override 时评估 Karmada/OCM |
| 多集群应用治理与策略 | OCM/Karmada，明确其与 GitOps 的字段所有权 |
| 跨集群 Service 访问 | MCS 实现、Submariner、ClusterMesh 或 Service Mesh，按网络边界选型 |
| 借用远端集群并保持 Kubernetes 调度体验 | 评估 Liqo，并单独验证 GPU/拓扑/RDMA |
| 大规模同步训练 | 先建设单集群/单 Fabric 的拓扑与队列；跨集群只做整 Job 放置 |
| 全球 LLM 推理 | 各区域完整 Serving Stack + Global Gateway/GSLB + 模型预热 |

### 建议的演进顺序

1. 为所有集群统一 Cluster ID、标签、身份、版本和观测维度。
2. 用 GitOps 或 Fleet Manager 统一平台基线，不先打通跨集群 Pod 网络。
3. 建立模型、数据和 Checkpoint 的可复制与校验机制。
4. 对训练引入整 Job 跨集群派发，本地继续负责 Gang 和拓扑。
5. 对推理建立区域级完整副本、模型预热和全局流量故障切换。
6. 只有出现明确应用依赖时再增加 MCS、ClusterMesh 或 Offloading。
7. 最后才评估跨集群同步训练、P/D 或 KV 传输等高耦合方案。

## 14. 上线检查清单

- [ ] 每个集群有稳定唯一 ID、所有者、地域、故障域和版本信息。
- [ ] Inventory 能表达 GPU 型号、显存、互联、RDMA、数据和价格，不只表达卡数。
- [ ] 全局放置和本地调度的职责、字段所有权与最终准入者明确。
- [ ] Hub/WAN 中断时，已运行训练和在线推理能按设计自治。
- [ ] 同一 Job 不会在网络分区或重试时被两个集群重复执行。
- [ ] 训练以整 Job 进入单个满足拓扑的集群，或跨集群通信已有实测依据。
- [ ] Checkpoint、数据和模型使用不可变版本并能在目标集群校验。
- [ ] 推理故障切换包含 GPU 容量、模型预热、依赖和长连接处理。
- [ ] 全局路由与集群内模型/KV-aware 路由分层。
- [ ] 跨集群网络已分别验证普通 Service、存储、RDMA/NCCL 或 KV 所需路径。
- [ ] Secret 和身份不靠无边界复制，权限在每个成员集群可审计。
- [ ] 观测数据包含 `cluster_id`、Job UID、模型版本、请求 ID 和故障域。
- [ ] 所有 CRD、Controller 和 Runtime 有兼容矩阵、Canary 和回滚方法。
- [ ] 演练过 Hub 失联、成员集群失联、对象存储故障和全局状态陈旧。

## 延伸阅读

- [SIG Multicluster](https://multicluster.sigs.k8s.io/)
- [ClusterProfile API](https://multicluster.sigs.k8s.io/concepts/cluster-profile-api/)
- [Work API](https://multicluster.sigs.k8s.io/concepts/work-api/)
- [Multicluster Services API](https://multicluster.sigs.k8s.io/concepts/multicluster-services-api/)
- [Cluster API](https://cluster-api.sigs.k8s.io/)
- [MultiKueue](https://kueue.sigs.k8s.io/docs/concepts/multikueue/)
- [Karmada Propagation Policy](https://karmada.io/docs/userguide/scheduling/propagation-policy/)
- [Open Cluster Management Architecture](https://open-cluster-management.io/docs/concepts/architecture/)
- [Liqo Architecture and Offloading](https://docs.liqo.io/)

与本页配套的集群内细节见：[AI 集群架构设计](architecture.md)、[分布式训练平台](../distributed-training.md)、[多机与分离式 LLM 推理](../inference/distributed-serving.md) 和 [边缘 AI 与云边协同](../edge-ai.md)。

跨地域模型权重不应由每个 Pod 直接跨 WAN 回源；区域副本、P2P、节点 NVMe 预热和发布门禁见：[模型格式、制品供应链与分发](../data/model-artifacts.md)。
