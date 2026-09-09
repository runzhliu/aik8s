---
title: Karmada 与 Virtual Kubelet：架构、调度与生产选型
description: 从应用对象的归属出发，对比 Karmada 多集群编排与 Virtual Kubelet 虚拟节点，分析副本、容量、网络、存储、故障恢复及 GPU 场景，并给出配置示例和观测方法
status: evolving
last_reviewed: 2026-09-09
---

# Karmada 与 Virtual Kubelet：架构、调度与生产选型

建设多集群平台时，常见的两个诉求是：把同一个应用发布到多个地域，以及让已有集群使用外部计算资源。它们都涉及跨集群或跨云，但控制对象、调度过程和故障边界并不相同。

**Karmada 管理应用在多个 Kubernetes 集群中的放置与分发；Virtual Kubelet（下文简称 VK）提供构建虚拟节点代理的框架，把外部执行后端接入 Kubernetes 的 Node/Pod 模型。** 前者的核心决策是“哪些集群各运行多少副本”，后者的核心适配是“调度到这个虚拟节点的 Pod，如何在外部创建、观测和删除”。[Karmada Concepts](https://karmada.io/docs/core-concepts/concepts/)、[Virtual Kubelet Architecture](https://virtual-kubelet.io/docs/architecture/)

比较时应分清三个层次：**Karmada 项目、VK 核心库、基于 VK 的具体 Provider 或完整产品**。例如 Liqo 在虚拟节点之外还提供资源协商、网络和存储等机制，不能把这些能力都算到 VK 核心库上；也不能把某个云 Provider 的限制推广到所有 VK 实现。

本文以核对时的 Karmada **v1.18 官方文档**、VK 项目文档及具名 Provider 文档为依据。架构图和配置是教学示例，生产选型部分是基于这些机制的工程分析，**不包含两套方案的实测性能排名**。安装前仍需核对实际版本、功能开关及 Provider 的支持矩阵。

## 1. 把两者放到正确的管理层次

<picture>
  <source media="(max-width: 600px)" srcset="/assets/cluster/karmada-vs-virtual-kubelet/architecture-mobile.svg">
  <img src="/assets/cluster/karmada-vs-virtual-kubelet/architecture.svg" alt="Karmada 的集群级编排与 Virtual Kubelet 的节点级适配">
</picture>

| 对比项 | Karmada | Virtual Kubelet 核心及 Provider |
| --- | --- | --- |
| 主要抽象 | 成员集群、资源模板、分发策略、资源绑定 | 虚拟 Node、分配给该节点的 Pod、外部执行实例 |
| 典型输入 | Deployment 等资源，加 PropagationPolicy、OverridePolicy | 普通 Kubernetes 工作负载产生的 Pod，加节点选择和 Provider 配置 |
| 调度单位 | 资源及其副本在成员集群之间的放置 | 上游调度器先把 Pod 绑定到虚拟节点；后端可能还有一次调度 |
| Deployment 控制器通常在哪里 | 各成员集群分别协调收到的 Deployment | 上游集群协调 Deployment，Provider 通常处理由它产生的 Pod |
| 执行后端 | Kubernetes 成员集群 | 容器云 API、远端 Kubernetes、其他受支持的执行系统 |
| 是否保留成员集群治理边界 | 明确保留，成员集群继续有自己的控制面与调度器 | 取决于后端；上游看到的是节点，远端可能仍是独立集群 |
| 外部资源呈现方式 | Cluster 与聚合状态，不把所有成员节点直接变成一套 Node | Provider 注册的 Node，可以代表一组外部资源 |
| 网络和存储 | 需结合成员集群基础设施及跨集群方案 | 需由 Provider/产品实现语义映射，支持程度不同 |
| 主要集成工作 | 放置策略、依赖、差异配置、解释器、健康与状态聚合 | Pod 生命周期、容量、状态、网络、卷、身份及调试接口适配 |
| 常见运维成本 | 联邦控制面、成员接入、分发规模、策略和多集群故障管理 | Provider 进程、外部 API、双端对象一致性及功能兼容 |

这张表反映职责边界，不表示 VK 方案一定轻量。一个需要完整网络、存储、配额和容灾能力的 VK 产品，可能比只做资源分发的 Karmada 部署更复杂。主要机制可参考 [Karmada Components](https://karmada.io/docs/core-concepts/components/) 和 [VK 项目说明](https://github.com/virtual-kubelet/virtual-kubelet)。

### 1.1 为什么 VK 更容易理解

如果需求是“让已有集群借用远端算力”，VK 的入口确实更直观：业务继续提交 Deployment，由本集群创建 Pod，调度器把 Pod 放到虚拟 Node，Provider 负责远端执行。业务用户可以继续沿用熟悉的 Node、Pod、标签和污点概念。

Karmada 要表达的决策更多：发布到哪些集群、总副本如何分配、不同地域使用什么配置、故障时是否迁移。它把这些决策拆成独立对象，因此增加了学习和排障成本。下面五类对象可以帮助理解最常见的控制链路；其中 **Cluster 是聚合 API 资源，不是 CRD**。[Karmada Components](https://karmada.io/docs/core-concepts/components/)

| 对象 | 用一句话理解 | 通常由谁维护 |
| --- | --- | --- |
| Cluster | 有哪些成员集群可供选择 | 平台接入流程及集群管理组件 |
| PropagationPolicy | 这个应用去哪里、各放多少副本 | 平台模板或应用交付配置 |
| OverridePolicy | 到不同集群后，哪些配置需要不同 | 有差异需求时由平台或应用方配置 |
| ResourceBinding | 调度结果选中了哪些集群 | 控制器生成并由调度链路更新，排障时查看 |
| Work | 向某个成员集群交付的资源内容 | 控制器生成，排障时查看分发与反馈状态 |

这不是要求业务用户手写五份对象。平台可以通过发布表单生成策略，并隐藏 ResourceBinding、Work 等内部对象。但运维人员仍然需要能沿着“模板 → 策略 → 绑定 → 分发 → 成员工作负载”定位故障，这部分复杂度不能仅靠界面封装消除。

VK 的清晰主要体现在业务入口。远端配额、资源碎片、网络、存储、身份、状态同步及删除失败等问题，仍要由 Provider 或完整产品处理。VK 核心沿用 Node/Pod，不代表所有 VK 产品都不引入 CRD；例如 Liqo 的资源协商和卸载机制就包含额外的自定义资源。[VK Architecture](https://virtual-kubelet.io/docs/architecture/)、[Liqo Offloading](https://docs.liqo.io/en/latest/features/offloading.html)

因此，选型时应把复杂度拆成业务学习成本、平台实现成本和故障处置成本分别评估。**只需要远端执行时，优先评估满足兼容性要求的 VK Provider；需要显式管理多地域放置、副本和差异策略时，再评估 Karmada 的收益。** 这是基于职责边界的工程建议；“管理几百个集群”本身不足以决定采用哪套方案。

## 2. 同一个 Deployment，实际经过两条不同路径

### 2.1 Karmada：先选择集群，再由成员集群创建 Pod

以总共 6 个副本的 Web 服务为例，典型流程是：

1. 用户把 Deployment 资源模板和分发策略提交给 Karmada API Server。
2. 控制器为匹配的资源建立 ResourceBinding；调度器根据策略选择成员集群并给出副本分配。
3. 分发链路生成 Work，并把经过差异覆盖的资源写入目标成员集群。
4. 成员集群的 Deployment/ReplicaSet 控制器创建 Pod；成员集群调度器再选择具体节点。
5. 成员状态回传，Karmada 根据资源类型及解释器规则聚合状态。

在常规配置中，Karmada API 中的 Deployment 是资源模板，不会在联邦控制面中由 Deployment 控制器直接创建执行 Pod。实际执行发生在成员集群。[Karmada Architecture](https://karmada.io/docs/core-concepts/architecture/)、[Karmada Components](https://karmada.io/docs/core-concepts/components/)

这也解释了“模板提交成功”“资源分发成功”“成员 Pod Ready”为什么是三个不同的状态。平台不能把前两个状态当作应用已经可用。

### 2.2 VK：先产生 Pod，再把执行交给 Provider

典型的 VK 路径是：

1. 用户把 Deployment 提交给普通 Kubernetes API Server。
2. 本集群的 Deployment/ReplicaSet 控制器创建 Pod。
3. kube-scheduler 根据 Node 容量、标签、污点等信息，将部分 Pod 绑定到虚拟节点。
4. VK/Provider 处理这些 Pod 的生命周期，在外部后端创建对应实例，并回报状态。
5. 若后端也是 Kubernetes，远端通常还要为对应 Pod 选择物理节点；若是容器云，实例创建由云服务负责。

VK 提供生命周期与节点代理相关接口；具体后端如何实现日志、exec、指标、配置传递等能力，需要检查 Provider。不能从“kubectl 能看到 Pod”推断所有原生 kubelet 行为都已实现。[VK Providers](https://virtual-kubelet.io/docs/providers/)

例如 Liqo 使用本地 Pod 与远端对象的映射，并通过 ShadowPod 等机制支持远端协调；这是 Liqo 的具体实现，其他 Provider 未必复制这套设计。[Liqo Offloading](https://docs.liqo.io/en/latest/features/offloading.html)

## 3. 副本语义：全局 6 个，还是每个集群 6 个

Karmada 的 `Duplicated` 与 `Divided` 会产生不同的资源账单：

| 模板与策略 | 两个集群均被选中时的示意结果 | 平台需要说明的语义 |
| --- | --- | --- |
| `replicas: 6` + `Duplicated` | A 为 6，B 为 6，总共 12 | 每个目标集群都获得完整副本数 |
| `replicas: 6` + `Divided` + 权重 2:1 | A 为 4，B 为 2，总共 6 | 在选定集群之间分配总副本数 |
| 普通 Deployment 为 6，部分 Pod 调度到 VK | 上游期望总数仍为 6 | Pod 被分配到不同节点，不因此把 Deployment 复制为两份 |

前两行假定集群满足选择条件，调度及分发完成，没有其他控制器改变副本数。`clusterNames` 定义候选集群，实际选择数量还应结合传播策略的约束；不要仅凭列出了两个名字就推断副本落点。[Karmada Propagation Policy](https://karmada.io/docs/userguide/scheduling/propagation-policy/)

VK 方案中，上游 Pod 与远端 Pod 可能是同一次执行的两个对象。统计业务实例和成本时应关联它们的身份，避免重复计数；同样，重试后暂时出现的重复后端实例也不能被普通的 Ready 数掩盖。

## 4. 调度与容量：总量充足，单个任务仍可能放不下

<picture>
  <source media="(max-width: 600px)" srcset="/assets/cluster/karmada-vs-virtual-kubelet/capacity-mobile.svg">
  <img src="/assets/cluster/karmada-vs-virtual-kubelet/capacity.svg" alt="两阶段放置、资源碎片与真实可执行容量">
</picture>

### 4.1 Karmada 的两阶段调度

Karmada 负责集群层放置，成员调度器负责节点层放置。为了避免只看集群资源总量而忽略节点碎片，Karmada 提供 scheduler-estimator 等组件，估算特定副本需求在成员集群中的可调度数量。[Karmada Components](https://karmada.io/docs/core-concepts/components/)

但估算与最终绑定之间仍有时间差。平台还要考虑成员集群的本地任务、队列准入、镜像可达性、PVC 拓扑和调度插件约束。一次成功的集群级放置不能承诺已经预留 GPU，也不能自动替代训练任务的 Gang 调度。

### 4.2 VK 的容量是 Provider 承诺给上游的视图

VK 节点的 `capacity` / `allocatable` 可以表示外部配额或协商出来的资源切片，未必对应一台物理机。Liqo 就会将协商资源映射到虚拟节点，并结合远端配额管理资源使用。[Liqo Resources Sharing and Reservation](https://docs.liqo.io/en/latest/usage/resource-reservation.html)

因此需要回答四个问题：容量是实时可用量还是额度上限？多久更新？后端拒绝时如何回报？资源申请与后端创建之间是否有预留或准入机制？只有 API 中的数字，没有这些约束，就可能发生“上游已调度、后端一直排队”。

### 4.3 GPU 场景尤其不能只比较卡数

假设外部两台机器各剩 4 张 GPU，某个 Pod 需要同一台机器上的 8 张 GPU。把它们汇总为虚拟节点的 `8 GPU`，可能使上游认为资源满足，但后端不存在可执行的单机布局。这个例子说明的是抽象丢失拓扑的风险，并非所有 Provider 都会这样上报。

对于 AI 平台，容量描述至少还要包含卡型、显存、单机可用卡数、NUMA/PCIe/NVLink 布局、RDMA 域、宿主内存和本地模型缓存。物理拓扑和设备分配必须由最终执行层验证，不能靠给虚拟节点添加 `nvidia.com/gpu` 数字解决。详见 [GPU 拓扑与资源碎片](../practices/gpu-topology-fragmentation-scheduling.md)。

## 5. 配置、CRD 与控制器归属

### 5.1 Karmada 更接近“分发应用对象”

Karmada 可以传播 Kubernetes 资源及自定义资源，但“能分发 CR”与“理解 CR”是两个层次。对 Ray、Flink 或训练作业，可能需要自定义资源解释器，说明如何提取副本和资源需求、聚合状态、判断健康、保留成员字段及解析依赖。相关 CRD 和负责执行的 Operator 也需要在目标集群可用。[Customizing Resource Interpreter](https://karmada.io/docs/userguide/globalview/customizing-resource-interpreter/)

差异配置可通过 OverridePolicy 表达，例如集群使用不同的镜像仓库地址或 StorageClass。依赖分发可结合策略和解释器实现；它不会自动发现应用目录里的所有对象，传播 PVC 声明也不代表卷内数据已经同步。[Override Policy](https://karmada.io/docs/userguide/scheduling/override-policy/)、[Propagate Dependencies](https://karmada.io/docs/userguide/scheduling/propagate-dependencies/)

### 5.2 VK 更接近“适配 Pod 执行”

VK 核心不为任意 Operator 自动提供跨集群语义。例如把某个 Operator 留在上游，而把它产生的 Pod 放到虚拟节点上，还需要确认 Operator 是否依赖本地 Node、PVC、Pod IP、exec、ServiceAccount 或特定节点代理。

Provider 对 Secret、ConfigMap 和 Service 等附属资源的处理，也要逐项检查。Liqo 的 resource reflection 提供了这些资源的同步能力，这是完整方案在 Pod 执行之外补充的部分。[Liqo Offloading](https://docs.liqo.io/en/latest/features/offloading.html)

### 5.3 每个字段只能有一个明确的写入责任方

以下是生产设计建议，而非产品默认配置：

| 资源或字段 | 建议明确的责任方 | 避免的冲突 |
| --- | --- | --- |
| 应用镜像、配置版本 | GitOps 或发布平台 | 人工、GitOps、传播控制器循环覆盖 |
| 跨集群放置与副本分配 | Karmada 策略及选定的扩缩容体系 | 成员 HPA 与联邦控制器争写 replicas |
| 上游 Deployment 副本 | 上游 HPA 或发布平台 | Provider 擅自创建第二套业务副本控制器 |
| 远端执行实例 | 选定 Provider 或成员 Operator | 同一作业同时经 Karmada 和 VK 重复投递 |
| 数据恢复位置与主写权 | 应用恢复协议及存储系统 | 两边都认为自己是主实例 |

Karmada 提供 Retain 等机制处理特定成员字段的保留，但仍需按工作负载和扩缩容方案配置，不能默认所有副本控制器会自动协商。[Resource Interpreter：Retain](https://karmada.io/docs/userguide/globalview/customizing-resource-interpreter/)

### 5.4 Karmada 到底有多少个 CRD

本文固定检查 **Karmada v1.18.0** 的源码清单，以实际 YAML 中 `kind: CustomResourceDefinition` 的 `metadata.name` 去重计数。结果为：**主安装清单 19 个，可选 Operator 另有 1 个；两部分合计 20 种定义。** 主清单中的 19 个包含 **17 个 Karmada API 组的 CRD，以及 2 个 `multicluster.x-k8s.io` 多集群服务标准 CRD**。[主安装清单](https://github.com/karmada-io/karmada/blob/v1.18.0/charts/karmada/_crds/kustomization.yaml)、[Operator CRD](https://github.com/karmada-io/karmada/blob/v1.18.0/operator/config/crds/operator.karmada.io_karmadas.yaml)

| 统计范围 | 数量 | 含义 |
| --- | ---: | --- |
| 主清单中的 `*.karmada.io` | 17 | 策略、绑定、分发、解释器及扩展功能 |
| 主清单中的 `multicluster.x-k8s.io` | 2 | ServiceExport、ServiceImport |
| 主清单合计 | **19** | `charts/karmada/_crds/bases/` 中的定义 |
| 可选 Operator | **1** | `operator/config/crds/` 中的 Karmada 定义 |
| 两部分定义的并集 | **20** | 不表示一个 API Server 必定安装 20 个 |

安装位置也要区分：例如 Helm 的 host 安装模式通过初始化 Job，将主清单应用到 **Karmada API Server**；Operator 的 CRD 则用于安装了 Operator 的宿主 Kubernetes。连接宿主集群执行 `kubectl get crd`，不能据此断言联邦控制面只有多少 CRD。[安装 Job 源码](https://github.com/karmada-io/karmada/blob/v1.18.0/charts/karmada/templates/karmada-static-resource-job.yaml)

以下是主清单的完整 19 项。作用域中的“集群级”表示在该 API Server 内不属于某个命名空间，不表示每接入一个成员集群就新增一种 CRD。用途为功能摘要，实际启用还需配套控制器和配置。

| # | Kind | API 组 | 作用域 | 用途 |
| --- | --- | --- | --- | --- |
| 1 | WorkloadRebalancer | apps.karmada.io | 集群级 | 对选定工作负载触发重新调度 |
| 2 | CronFederatedHPA | autoscaling.karmada.io | 命名空间级 | 按时间计划调整联邦扩缩容目标 |
| 3 | FederatedHPA | autoscaling.karmada.io | 命名空间级 | 根据指标进行联邦水平扩缩容 |
| 4 | ResourceInterpreterCustomization | config.karmada.io | 集群级 | 声明资源解释规则，如副本提取和状态聚合 |
| 5 | ResourceInterpreterWebhookConfiguration | config.karmada.io | 集群级 | 配置外部资源解释器 Webhook |
| 6 | ServiceExport | multicluster.x-k8s.io | 命名空间级 | 声明服务向多集群范围导出 |
| 7 | ServiceImport | multicluster.x-k8s.io | 命名空间级 | 表示导入的多集群服务信息 |
| 8 | MultiClusterIngress | networking.karmada.io | 命名空间级 | 描述多集群服务的入口路由 |
| 9 | MultiClusterService | networking.karmada.io | 命名空间级 | 描述跨成员集群的服务抽象 |
| 10 | ClusterOverridePolicy | policy.karmada.io | 集群级 | 配置集群级资源差异覆盖策略 |
| 11 | ClusterPropagationPolicy | policy.karmada.io | 集群级 | 配置集群级资源分发策略 |
| 12 | ClusterTaintPolicy | policy.karmada.io | 集群级 | 根据条件管理成员集群污点 |
| 13 | FederatedResourceQuota | policy.karmada.io | 命名空间级 | 管理联邦命名空间资源配额 |
| 14 | OverridePolicy | policy.karmada.io | 命名空间级 | 配置命名空间内资源的差异覆盖 |
| 15 | PropagationPolicy | policy.karmada.io | 命名空间级 | 配置命名空间内资源的放置和分发 |
| 16 | Remedy | remedy.karmada.io | 集群级 | 根据集群条件触发管理动作，如 TrafficControl |
| 17 | ClusterResourceBinding | work.karmada.io | 集群级 | 保存集群级资源的目标集群及调度结果 |
| 18 | ResourceBinding | work.karmada.io | 命名空间级 | 保存命名空间级资源的目标集群及调度结果 |
| 19 | Work | work.karmada.io | 命名空间级 | 承载发往成员集群的资源及执行反馈 |

名称、作用域和 API 版本均来自该版本的 [CRD 定义目录](https://github.com/karmada-io/karmada/tree/v1.18.0/charts/karmada/_crds/bases)。其中 Remedy 的条件和动作可核对 [API 类型定义](https://github.com/karmada-io/karmada/blob/v1.18.0/pkg/apis/remedy/v1alpha1/remedy_types.go)。可选的第 20 项为 **Karmada**，API 组 `operator.karmada.io`，作用域为命名空间级，用于声明由 Operator 管理的 Karmada 控制面实例。

计数时有四个容易混淆的地方：

- **API 资源不等于 CRD。** Cluster 由聚合 API Server 提供；Deployment、Pod、Node 是原生资源，均不计入上表。不能用 `kubectl api-resources` 的行数代替 CRD 数量。
- **多个版本仍然是一种 CRD。** 此版本的 ResourceBinding 和 ClusterResourceBinding 都提供 `v1alpha1`、`v1alpha2`，各计 1 个。其余清单项提供 `v1alpha1`。
- **安装定义不等于启用功能。** 存在 FederatedHPA 或 MultiClusterIngress 的 CRD，并不表示扩缩容和跨集群入口已经配置完成。
- **定义数量不等于对象数量或学习量。** 一种 Work CRD 可以对应很多 Work 实例；普通发布往往只需接触工作负载、传播策略及按需使用的覆盖策略。扩缩容、服务治理和解释器等按需求再引入。

完整机器可读清单包含每项的资源名、版本和源码链接，可下载 [v1.18.0 CRD 核对结果](../../assets/cluster/karmada-vs-virtual-kubelet/crd-inventory-v1.18.0.json)。仓库中提供 `scripts/inventory_karmada_crds.py`，通过 GitHub CLI 读取指定版本并解析 YAML，不访问或修改 Kubernetes 集群；在安装了 `gh` 和 PyYAML 的环境中可复核：

```bash
python3 scripts/inventory_karmada_crds.py --ref v1.18.0 --output /tmp/karmada-crds.json
```

若核对现有安装，先确认 kubeconfig 指向 Karmada API Server，再执行以下只读命令；示例 context 名需替换为实际名称。输出包括该控制面安装的其他 CRD，应对照上面的清单确认缺项或额外项，而不是预设结果一定为 19。

```bash
kubectl --context karmada-apiserver get crd \
  -o custom-columns='NAME:.metadata.name,KIND:.spec.names.kind,GROUP:.spec.group,SCOPE:.spec.scope'
```

**CRD 数量可以说明需要维护的 API 表面，但不能单独作为选型评分。** 更有价值的检验是：业务是否必须理解这些对象，以及出现“资源已分发但 Pod 未就绪”时，平台能否把内部链路还原成明确原因。VK 也应按完整 Provider 产品核对扩展对象和运维成本，不能只拿核心库的接口数量比较。

## 6. 网络、服务发现和存储的兼容性

| 能力 | Karmada 需要检查 | VK 方案需要检查 |
| --- | --- | --- |
| Pod 网络 | 每个成员集群内部网络；跨集群链路另行设计 | 后端 IP 是否可达，是否需要代理或地址映射 |
| Service / DNS | Service 分发不自动生成统一流量入口 | 上游 Endpoints/EndpointSlice 如何反映外部实例 |
| 流量切换 | 全局负载均衡、DNS 或网关如何感知成员健康 | 虚拟 Pod Ready 与后端实际可接流量是否一致 |
| NetworkPolicy | 目标 CNI 是否支持，规则作用范围是否一致 | Provider 能否实现对应隔离语义 |
| PVC / StorageClass | 每个集群的存储类型、拓扑和数据恢复 | 卷类型是否被支持，绑定和挂载如何映射 |
| hostPath / 本地 NVMe | 数据只在特定节点；迁移需考虑模型和数据重新准备 | 虚拟节点名称不表示拥有可访问的同名宿主目录 |
| exec / logs / metrics | 成员访问路径、身份和采集链路 | Provider 的接口实现、连接转发和指标覆盖范围 |

**资源对象复制与数据复制应分别设计。** 两个集群创建同名 PVC，不能说明它们读到同一份数据；上游显示相同 Pod IP，也不能说明网络路径和身份语义已经保持一致。这些是审查架构时需要验证的条件。

Provider 的差异可以很大：微软 AKS virtual nodes 文档列出了 PVC/PV、DaemonSet、网络等方面的限制；Liqo 则有独立的 Network Fabric 和 Storage Fabric。前者的限制不能用来证明 VK 框架普遍不支持存储，后者的能力也不能算作安装 VK 核心库后自动获得的能力。[AKS Virtual Nodes](https://learn.microsoft.com/en-us/azure/aks/virtual-nodes)、[Liqo Network Fabric](https://docs.liqo.io/en/latest/features/network-fabric.html)、[Liqo Storage Fabric](https://docs.liqo.io/en/latest/features/storage-fabric.html)

## 7. 故障恢复：不可达、进程停止与主写权是三件事

### 7.1 Karmada 的故障迁移

Karmada 提供集群级和应用级故障迁移机制，但启用条件不同。核对时的 v1.18 文档仍将集群 `Failover` 功能标为 Beta、默认关闭；应用级迁移还涉及健康解释、依赖传播及相应配置。选型评估中应明确具体功能，而不是笼统写“默认支持自动容灾”。[Cluster Failover](https://karmada.io/docs/userguide/failover/cluster-failover/)、[Application-level Failover](https://karmada.io/docs/userguide/failover/application-failover/)

Karmada 管理控制面短暂不可用时，已经分发到成员集群的应用通常仍由成员本地控制器维护；跨集群的新调度、分发和状态汇总会受影响。应用能否继续提供服务，还取决于它是否依赖集中式网关、存储或其他共享组件。这是由分层控制架构推导出的故障分析，不能把“本地 Pod 还活着”当作全业务连续性的保证。

### 7.2 VK 的故障恢复依赖实现

应分别测试 Provider 进程退出、外部 API 不可达，以及真正的后端计算故障。Provider 进程停了，后端容器可能仍在运行；上游 Node 状态变化和 Pod 驱逐，也不证明外部实例已经删除。不同实现对重连、重建和清理的处理不同。

例如 Liqo 文档描述了节点健康检查与远端 ShadowPod 维护机制。其恢复行为建立在这些组件上，不能只用“VK 会模拟 kubelet”一句话概括。[Liqo Offloading](https://docs.liqo.io/en/latest/features/offloading.html)

### 7.3 两套方案都要验证网络分区下的重复执行

设想管理端无法连接集群 A，但 A 的业务仍能访问数据库。此时在 B 启动替代实例，可能导致同一任务执行两次或两个主实例同时写入。删除请求、对象消失和进程真正停止之间也可能存在时间差。

因此，有状态系统需要自己的租约、fencing（撤销旧实例写入资格）、幂等键、检查点和恢复流程。PDB 控制的是受支持的自愿中断预算，不能当作跨集群主写权协议，也不能阻止所有非自愿中断。[Kubernetes Disruptions](https://kubernetes.io/docs/concepts/workloads/pods/disruptions/)

Karmada 的状态保留机制可以提取、传递部分恢复相关字段，但文档中的 `StatefulFailoverInjection` 仍为 Alpha、默认关闭。它不传输进程内存、GPU HBM 或 NCCL 通信状态。对于训练，准确的表述应是“重新放置作业后从检查点恢复”。[Karmada Cluster Failover：State Preservation](https://karmada.io/docs/userguide/failover/cluster-failover/)

## 8. 弹性与性能应该怎样比较

Karmada 可以结合 FederatedHPA 等机制调整全局副本，再通过放置策略分配到成员集群。VK 方案则通常由上游 HPA 等控制器产生更多 Pod，再由 Provider 向后端申请执行资源；CPU/内存等指标能否参与 HPA，取决于指标链路是否完整。[Karmada FederatedHPA](https://karmada.io/docs/userguide/autoscaling/federatedhpa/)、[VK Providers](https://virtual-kubelet.io/docs/providers/)

两者都不能仅凭架构图得出“扩容更快”。建议统一测量以下时刻：

```text
负载上升 → 产生扩容决策 → 目标集群/虚拟节点确定
        → 后端接受创建 → 资源获得准入 → 容器启动
        → 应用 Ready → 第一条真实请求成功
```

用于比较的启动耗时应覆盖整个链路，并保留各阶段分解。VK 后端即使省去了新建 VM 的步骤，仍可能受配额、镜像拉取和模型加载影响；Karmada 选择了另一个已有集群，也不代表那里预留了可立即运行的 GPU。

公平的对照至少固定相同镜像、资源、存储、地域、输入负载和缓存条件，分别报告冷启动、热启动与无可用容量的结果。对推理还应报告 TTFT、TPOT、完整流成功率和达标吞吐；对训练则报告整组任务到位时间、有效训练吞吐和检查点恢复时间。本文不为没有实测的方案给出毫秒级性能差距。

## 9. 安全与多租户：一次授权经过几个边界

Karmada 的 Push 模式由控制端访问成员；Pull 模式通过成员侧 agent 同步期望和状态。连接发起方向会改变网络与凭据管理方式，但不能替代身份认证、RBAC 和审计。[Karmada Components](https://karmada.io/docs/core-concepts/components/)

VK 则需要检查上游节点身份、Provider 的资源读取权限，以及后端云账号或远端集群身份。VK 文档对 Provider 接口的数据访问有约束，不能据此推断整个节点代理进程完全不需要 Kubernetes API 权限；实际部署应按组件和接口拆分授权。

以下是两套方案共同需要落实的工程约束：

- 明确哪个租户可以把哪些数据和 Secret 送往哪个后端，避免宽泛选择器或自动反射扩大数据范围。
- 将上游对象 UID、目标集群、后端实例 ID 和操作者关联起来，支持跨端审计与删除核验。
- 校验上游准入策略在远端是否仍有效；同名 Namespace、ServiceAccount 不代表同一身份。
- 对日志、exec、指标转发分别做授权和故障测试，避免出现“业务 API 有权限隔离，调试接口没有”的缺口。
- 让租户配额同时覆盖上游准入和后端实际资源，不能把虚拟节点上报的容量当作计费或隔离机制。

## 10. 两组配置示例：看清策略放在哪里

下面仅演示资源语义，未在本文中执行。`cluster-a`、`cluster-b`、镜像域名和节点标签都是示例值。需先完成 Karmada 成员注册或所选 Provider 的安装、网络和权限配置，再替换这些值。命令显式指定 context，避免把联邦模板写入普通业务集群。

### 10.1 Karmada：6 个副本按 2:1 分配

```yaml title="karmada-demo.yaml"
apiVersion: apps/v1
kind: Deployment
metadata:
  name: demo-http
  namespace: platform-demo
spec:
  replicas: 6
  selector:
    matchLabels:
      app: demo-http
  template:
    metadata:
      labels:
        app: demo-http
    spec:
      containers:
        - name: http
          image: registry.example.com/platform/demo-http:1.0
          ports:
            - containerPort: 8080
          resources:
            requests:
              cpu: 250m
              memory: 256Mi
            limits:
              cpu: "1"
              memory: 512Mi
          readinessProbe:
            httpGet:
              path: /ready
              port: 8080
---
apiVersion: policy.karmada.io/v1alpha1
kind: PropagationPolicy
metadata:
  name: demo-http-placement
  namespace: platform-demo
spec:
  resourceSelectors:
    - apiVersion: apps/v1
      kind: Deployment
      name: demo-http
  placement:
    clusterAffinity:
      clusterNames: [cluster-a, cluster-b]
    spreadConstraints:
      - spreadByField: cluster
        minGroups: 2
        maxGroups: 2
    replicaScheduling:
      replicaSchedulingType: Divided
      replicaDivisionPreference: Weighted
      weightPreference:
        staticWeightList:
          - targetCluster:
              clusterNames: [cluster-a]
            weight: 2
          - targetCluster:
              clusterNames: [cluster-b]
            weight: 1
```

```bash
# 先确认联邦及成员侧 Namespace 已按平台规则准备好。
kubectl --context karmada-apiserver apply -f karmada-demo.yaml
kubectl --context karmada-apiserver -n platform-demo get resourcebindings
kubectl --context cluster-a -n platform-demo get deployment,pods
kubectl --context cluster-b -n platform-demo get deployment,pods
```

当两个候选集群均满足条件且分发完成时，期望看到 A 为 4 个副本、B 为 2 个副本。还要核对各成员 Ready 数，不应仅检查 ResourceBinding。这里使用静态权重展示副本分配，不提供实时容量预留，也不为故障情况下的重新放置指定完整策略。字段依据：[Propagation Policy](https://karmada.io/docs/userguide/scheduling/propagation-policy/)。

### 10.2 VK：通过虚拟节点承接普通 Deployment 的 Pod

下面的标签和污点是**平台自定义示例**，不是所有 VK Provider 通用的安装约定。假设 Provider 管理的虚拟节点已带有 `platform.example.com/execution=external` 标签和相应 `NoSchedule` 污点；应按 Provider 的节点配置方式设置，避免手工值被自动协调覆盖。

```yaml title="vk-demo.yaml"
apiVersion: apps/v1
kind: Deployment
metadata:
  name: external-http
  namespace: platform-demo
spec:
  replicas: 6
  selector:
    matchLabels:
      app: external-http
  template:
    metadata:
      labels:
        app: external-http
    spec:
      nodeSelector:
        platform.example.com/execution: external
      tolerations:
        - key: platform.example.com/execution
          operator: Equal
          value: external
          effect: NoSchedule
      containers:
        - name: http
          image: registry.example.com/platform/demo-http:1.0
          ports:
            - containerPort: 8080
          resources:
            requests:
              cpu: 250m
              memory: 256Mi
            limits:
              cpu: "1"
              memory: 512Mi
          readinessProbe:
            httpGet:
              path: /ready
              port: 8080
```

```bash
kubectl --context workload-cluster apply -f vk-demo.yaml
kubectl --context workload-cluster get nodes \
  -l platform.example.com/execution=external
kubectl --context workload-cluster -n platform-demo get pods -o wide
```

还需从 Provider 或后端确认 6 个实例真正创建并可访问，以及 `/ready` 探针语义受到支持。`tolerations` 只是允许 Pod 容忍污点，不能保证它被调度到该节点；例子同时使用 `nodeSelector` 限定目标。也不要用 `nodeName` 绕开正常调度，再把结果当作容量调度成功。[Kubernetes Taints and Tolerations](https://kubernetes.io/docs/concepts/scheduling-eviction/taint-and-toleration/)

## 11. Prometheus / Grafana：怎样看出差别确实生效

可观测性应围绕两个闭环设计：**声明式对象有没有完成执行，以及真实请求是否受益**。以下是建议建设的看板内容，不代表每个项目都开箱提供同名指标。

| 看板 | Karmada 侧重点 | VK / Provider 侧重点 |
| --- | --- | --- |
| 全局期望与实际 | 模板副本、各集群分配、成员 Ready、聚合状态更新时间 | 上游 Pod、后端实例、状态映射更新时间、孤儿实例 |
| 放置和准入 | 调度等待、不可放置原因、分发延迟、成员准入失败 | 虚拟 Node allocatable、上游已绑定但后端未准入的 Pod |
| 控制循环 | 工作队列、协调错误、API 限流与重试 | Provider 调用延迟、后端 429/5xx、重连与重试 |
| 容量和成本 | 集群可用资源、资源碎片、地域副本和费用 | 上报额度、后端实际可用量、已收费但上游不可见的实例 |
| 故障恢复 | 发现异常、迁移决策、目标 Ready、流量切换 | Node 状态、后端存活、实例重建、旧实例清理 |
| 应用体验 | 端到端成功率和延迟，按成员集群拆分 | 端到端成功率和延迟，按执行后端拆分 |

如果每个成员都有 kube-state-metrics，并在采集或远端写入时附加了唯一的 `cluster` 标签，可以从下面的查询开始观察成员侧可用副本：

```promql
sum by (cluster) (
  kube_deployment_status_replicas_available{
    namespace="platform-demo", deployment="demo-http"
  }
)
```

该查询的前提是数据源仅包含需要比较的成员实例，并已处理 Prometheus HA 副本的重复采集。`cluster` 不是所有安装默认自带的标签；没有标签时不能把混合数据当成跨集群对照。对于 VK，kube-state-metrics 通常只能看到上游声明和回报状态，还需接入 Provider 或后端证据。

建议按同一请求 ID 或业务执行 ID 记录关键时间点。聚合图展示 P50/P95/P99 和失败数，原始记录保留完整链路。对象 UID 和后端实例 ID 放入日志或追踪更合适，不必全部变成长期 Prometheus 标签。

## 12. 面向 GPU 平台的场景选择

以下建议基于执行边界，而非实测产品排名：

| 业务需求 | 优先评估方向 | 决定选型前要验证什么 |
| --- | --- | --- |
| 多地域推理服务统一发布与差异配置 | Karmada | 集群容量、模型分发、成员 Ready、跨地域流量入口 |
| 已有集群临时借用外部 CPU 容器资源 | 具备对应能力的 VK Provider | 配额、网络、镜像凭据、卷、日志与回收计费 |
| 已有集群透明借用另一套 Kubernetes 资源 | Liqo 等完整 VK 方案 | 资源协商、后端准入、网络/存储、身份映射 |
| 训练作业在多个 GPU 集群之间整组选择 | Karmada 的合适策略，或作业级多集群调度方案 | CRD 解释、整 Job 准入、Gang、数据和检查点 |
| 一个 NCCL 作业跨地域拼接零散 GPU | 先重新评估执行域 | 两者都不会消除网络延迟、带宽和拓扑约束 |
| 多租户 Notebook 与临时开发容器 | 取决于“多地域部署”还是“外部执行” | 持久目录、交互连接、GPU 设备、休眠和恢复 |
| 集群安装、升级与控制面修复 | 专门的集群生命周期工具 | Karmada 与 VK 都不以此为核心职责 |

对于紧耦合训练，更容易验证的架构通常是“跨集群选择作业落点，集群内完成整组 GPU 准入和通信”。对于独立推理副本，可以将地域放置与请求路由分开：Karmada 决定服务出现在哪些集群，成员内推理平台决定本地副本和流量；VK 可以在经过验证的成员中提供额外执行后端。

更广泛的多集群训练选型见 [跨集群与大规模 GPU](multi-cluster-ai.md)，节点层问题见 [GPU 与异构资源调度](../gpu-scheduling.md)。

## 13. 两者可以组合，但需要限制控制环的数量

一种组合是：Karmada 将区域应用放到成员集群，某个成员再通过 VK Provider 使用外部资源。这时有三次可能影响结果的决策：联邦选择成员、成员选择虚拟节点、后端选择真正执行资源。

组合前应明确：

1. 外部容量是否已被另一个成员或联邦资源视图计入，避免同一资源被重复承诺。
2. 集群故障迁移和虚拟节点驱逐是否可能同时为同一业务创建替代实例。
3. 全局 HPA、成员 HPA、后端扩容各自调整什么对象，谁拥有最终副本数。
4. 状态延迟是否会被逐层放大；排队发生在哪一层，超时由谁结束。
5. 联邦对象、成员 Pod、后端实例的删除链路能否闭合，恢复后是否会重复创建。

若需求只是统一发布清单，先比较简单 GitOps 是否足够；若需求只是稳定的本地执行，普通节点池也应作为基线。增加抽象层应有明确的业务收益和可验证的边界。

## 14. 上线前如何做有说服力的验证

下面是建议的验收范围，不是本文已执行的测试。故障注入应在隔离环境中完成，观测数据与业务数据保留策略分别设计。

| 验证项 | 操作与证据 | 通过标准应包含 |
| --- | --- | --- |
| 正常创建与扩缩 | 同一镜像与副本数，关联各端对象 | 后端实例数、Ready、真实请求与期望一致 |
| 容量不足 | 超过后端配额或模拟节点资源碎片 | 原因可见，无无限重试、无隐性重复收费 |
| 控制链路中断 | 阻断管理链路，保留业务数据链路 | 能区分未知状态和实际停止，避免双主 |
| 代理/控制器重启 | 重启专用控制组件后恢复 | 正确接管已有实例，未重复创建或丢失清理责任 |
| 删除与取消 | 排队、创建中、运行中分别取消 | 上游对象和后端执行都终止，费用停止增长 |
| 存储与配置更新 | 更新 Secret、写入持久数据、迁移 | 版本一致性、权限边界和数据恢复可核对 |
| 滚动发布 | 长连接及长任务持续运行时更新 | 中断率、排空时间、回滚路径符合业务预算 |
| GPU 作业 | 多卡放置、设备访问和通信验证 | 整组到位、拓扑符合预期、吞吐达到基线 |
| 版本升级 | 指定版本组合与 Provider 支持矩阵 | 能回滚，存量对象和状态映射不丢失 |

管理数百个集群时，应把上述验证变成版本准入与分批发布流程，而不是一次性演示。平台需要能解释“为什么这里多了一份实例、为什么这次没有迁移、为什么节点有额度但任务仍然排队”，并提供从全局对象追到真实执行后端的证据。相关经验见 [数百个 Kubernetes 集群的稳定性建设](../practices/kubernetes-fleet-reliability.md)。
