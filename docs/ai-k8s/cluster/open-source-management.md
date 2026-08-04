---
title: 开源 Kubernetes 集群管理工具与方式
description: 从 kubectl、Web UI 和 GitOps，到 Rancher、Cluster API、Gardener、Karmada 与 OCM 的分层选型
status: evolving
last_reviewed: 2026-08-04
---

# 开源 Kubernetes 集群管理工具与方式

“管理 Kubernetes 集群”至少包含六件不同的事：访问和排障、创建和升级集群、统一身份与权限、配置收敛、跨集群应用分发，以及跨集群工作负载放置。没有一个工具应该同时成为这六层的唯一控制器。

先定义问题，再选择最小组合。对于大多数团队，一个可靠的命令行入口、一个只读优先的 Web UI、GitOps 和清晰的集群生命周期工具，比安装一套功能重叠的“大而全平台”更容易长期维护。

## 1. 先拆开六类能力

| 管理层 | 要解决的问题 | 常见开源实现 |
| --- | --- | --- |
| 人员访问与排障 | 如何安全切换上下文、查看资源、日志和事件 | `kubectl`、`kubectx`、k9s、Headlamp |
| 集群安装与生命周期 | 谁创建、扩缩、升级、修复和销毁集群 | kubeadm、Kubespray、kOps、Cluster API、Gardener、Kubermatic |
| 统一门户与治理 | 多集群身份、RBAC、项目、配额和可视化入口 | Rancher、KubeSphere、Portainer CE、Headlamp |
| 配置和组件收敛 | CNI、CSI、Operator、策略和应用如何保持版本一致 | Argo CD、Flux、Rancher Fleet |
| 多集群资源与策略分发 | 哪些对象进入哪些集群，如何做差异覆盖和故障迁移 | Karmada、Open Cluster Management |
| 跨集群作业放置 | 一个训练或批任务应在哪个集群完整运行 | Kueue MultiKueue、OCM Placement，以及平台自建 Broker |

这些层可以组合，但必须规定对象和字段的唯一所有者。例如，不要让 Argo CD、Fleet 和 Karmada 同时修改同一个 Deployment 的副本数，也不要让 Rancher、Cluster API 和人工脚本同时负责同一集群的升级。

## 2. 方式一：原生 CLI 加轻量 UI

这是最简单也最透明的管理方式：

```text
OIDC / 短期凭据
      │
kubeconfig exec plugin
      │
kubectl / k9s / Headlamp
      │
Kubernetes API + RBAC + Audit
```

### kubectl、kubectx 和 k9s

- `kubectl` 是自动化和故障排查的基础，应保留为最终诊断入口；
- `kubectx`/`kubens` 适合快速切换集群和 Namespace；
- k9s 适合终端中的实时资源浏览、日志、事件和常见操作。

这种方式不提供集群创建、统一租户门户或配置持续收敛。集群数量增加后，应把静态管理员证书换成 OIDC、`exec` 凭据插件或受控访问代理，不要在个人电脑上长期保存几十份 `cluster-admin` kubeconfig。

### Headlamp

Headlamp 是 Kubernetes SIG UI 下的开源 Web/桌面 UI，可以连接一个或多个集群，界面操作遵循用户在目标集群中的 RBAC，并支持插件扩展。它适合：

- 为开发者和一线运维提供资源、日志和事件入口；
- 给现有认证、GitOps 或内部平台补一个轻量 UI；
- 在不引入完整集群管理平台时统一基本操作体验。

Headlamp 不负责创建集群，也不会自动建立组织级租户、策略和交付体系。Web 版仍要配置 OIDC、Ingress、TLS、NetworkPolicy、审计和最小权限。

Kubernetes Dashboard 已被官方标记为弃用且停止维护，新部署应优先评估 Headlamp，而不是继续围绕 Dashboard 建设门户。

参考：[Headlamp](https://headlamp.dev/docs/latest/)、[Kubernetes Web UI](https://kubernetes.io/docs/tasks/access-application-cluster/web-ui-dashboard/)

## 3. 方式二：GitOps 管理集群配置

GitOps 不负责创建物理机或修复控制面，但很适合让多个集群持续收敛到可审计的目标状态：

```text
Git / OCI Artifact
        │
评审、测试、签名和版本
        │
Argo CD / Flux / Fleet
        │
基础组件、策略、AI Operator 和业务应用
```

### Argo CD

Argo CD 提供集中式控制面、Web UI、应用健康状态、Diff、同步和回滚，并能注册多个目标集群。它适合希望从一个入口查看多集群应用状态、采用 App-of-Apps 或 ApplicationSet 的团队。

集中式 Argo CD 会持有目标集群凭据，需要认真设计项目边界、目标 Namespace、凭据轮换、高可用和控制器分片。它管理的是集群中的声明式资源，不等同于集群生命周期管理。

### Flux

Flux 由一组 Kubernetes 控制器组成，通常在每个集群内部拉取 Git、OCI、Helm 或 Bucket 中的期望状态。它适合偏好分布式 Pull 模型、Kubernetes 原生 CRD、较小管理故障域，以及希望按集群自治的团队。

Flux 本身不提供官方 UI，可以配合 Headlamp 插件或其他生态界面。无论选择 Argo CD 还是 Flux，都应先确定仓库层级、Secret 加密、变更晋级、紧急修复回写和漂移处理规则。

参考：[Argo CD Cluster Management](https://argo-cd.readthedocs.io/en/stable/operator-manual/cluster-management/)、[Flux Core Concepts](https://fluxcd.io/flux/concepts/)

## 4. 方式三：统一门户和多集群治理平台

### Rancher

Rancher 是较完整的开源 Kubernetes 管理平台，可以注册现有集群，也可以创建和升级部分类型的集群，并提供集中身份、RBAC、项目、集群浏览、应用目录和 Fleet 持续交付。

适合：

- 同时管理 RKE2/K3s、云托管和其他已存在的 Kubernetes 集群；
- 需要统一登录、权限和面向团队的 Web 门户；
- 希望把集群生命周期、访问入口和 Fleet 集成在一个产品中。

注意：注册进 Rancher 不代表 Rancher 获得了所有发行版的完整生命周期控制权；不同集群类型可执行的升级、节点和备份操作不同。生产环境通常应把 Rancher Server 部署在独立、高可用的管理集群，避免业务集群故障同时带走管理入口。

参考：[Rancher Manager](https://ranchermanager.docs.rancher.com/rancher-manager)、[Rancher Cluster Management](https://ranchermanager.docs.rancher.com/getting-started/overview)

### KubeSphere

KubeSphere 提供面向平台团队的多租户工作区、项目、应用交付、可观测和多集群管理界面。它适合希望用中文友好门户整合开发和运维流程、并愿意采用其平台抽象的团队。

选型时要核对目标版本的扩展组件、Kubernetes 兼容矩阵和社区维护节奏。KubeSphere 的 Workspace、Project 等抽象需要与原生 Namespace、RBAC、GitOps 所有权对齐，避免形成第二套无人维护的权限和交付模型。

参考：[KubeSphere Multi-cluster Management](https://www.kubesphere.io/multicluster/)

### Portainer CE

Portainer CE 能从一个轻量界面管理 Kubernetes、Docker 等环境，适合小团队、实验室和已有 Portainer 使用经验的场景。Server 配合 Agent 可以连接多个环境，但社区版和商业版功能边界不同，且 Portainer Server 的高可用和同一环境多实例管理存在架构限制。

如果目标是大规模 Kubernetes Fleet、严格多租户或完整生命周期自动化，不应只因为安装简单就默认选择 Portainer。

参考：[Portainer CE on Kubernetes](https://docs.portainer.io/start/install-ce/server/kubernetes)、[Portainer Architecture](https://docs.portainer.io/start/architecture)

## 5. 方式四：声明式集群生命周期

### kubeadm、Kubespray 和 kOps

这三类工具更接近安装器或运维自动化，而不是统一多集群门户：

- kubeadm 提供 `init`、`join`、证书和升级等集群引导能力，不负责创建机器，也不安装完整的网络、存储、监控和管理平台；
- Kubespray 用 Ansible 把主机准备、kubeadm、高可用、网络插件、扩缩节点和升级流程自动化，适合裸金属、虚拟机和离线环境；
- kOps 同时管理 Kubernetes 和必要的云基础设施，适合其正式支持的云环境，但必须按目标 Provider 核对能力成熟度。

少量自建集群可以使用 Terraform 创建主机、负载均衡和网络，再用 Kubespray 安装 Kubernetes；基础设施状态和集群内资源状态仍应分开管理。随着集群数量增长，命令式流水线和 Ansible Inventory 容易变成事实数据库，此时可转向 Cluster API 等持续协调的声明式控制器。

参考：[kubeadm](https://kubernetes.io/docs/reference/setup-tools/kubeadm/)、[Kubespray](https://github.com/kubernetes-sigs/kubespray)、[kOps](https://kops.sigs.k8s.io/)

### Cluster API

Cluster API（CAPI）用 Kubernetes 风格的 `Cluster`、`Machine`、`MachineDeployment` 等 API 管理集群创建、扩缩、升级和删除，并通过不同 Infrastructure、Bootstrap 和 Control Plane Provider 对接公有云、私有云或裸金属。

它适合平台团队构建“集群即 API”，并把环境模板、机器池和升级流程纳入 GitOps。需要注意：

- Provider 的成熟度、功能和版本节奏并不完全一致；
- CAPI 不是日常资源管理 UI，也不分发业务应用；
- 已存在且不是由 CAPI 创建的集群，通常不能简单地获得完整 CAPI 生命周期管理；
- 管理集群本身的备份、升级和灾备仍需单独设计。

参考：[Cluster API Book](https://cluster-api.sigs.k8s.io/)

### Gardener

Gardener 使用 Kubernetes 管理 Kubernetes，通过 Garden、Seed 和 Shoot 层级提供多云 Kubernetes as a Service。它覆盖集群创建、控制面托管、版本与机器镜像策略、维护窗口和生命周期协调，适合要运营数百到数千个相对标准化集群的平台提供方。

它的能力和运维复杂度都明显高于“装一个管理 UI”。团队需要掌握管理集群、Seed 容量、云扩展、网络、备份和 Gardener 自身升级，不适合作为少量现有集群的简单控制台。

参考：[Gardener Introduction](https://gardener.cloud/docs/getting-started/introduction/)、[Gardener Architecture](https://gardener.cloud/docs/getting-started/architecture/)

### Kubermatic Kubernetes Platform

Kubermatic Kubernetes Platform（KKP）提供多云集群创建、模板、项目、OIDC 和生命周期管理。Community Edition 可以作为自助式 Kubernetes 平台起点，但部分备份、多 Seed、配额、策略和边缘能力属于 Enterprise Edition。

选型不能只看代码仓库是否开放，应把实际需要的功能逐项对照版本和 Edition，验证完全开源部署是否能形成生产闭环。

参考：[KKP Community and Enterprise Editions](https://docs.kubermatic.com/kubermatic/v2.30/architecture/editions/)

## 6. 方式五：多集群清单、策略和应用分发

### Open Cluster Management

Open Cluster Management（OCM）使用 Hub-Agent 架构管理 `ManagedCluster` 清单，并通过 `ManagedClusterSet`、`Placement`、`ManifestWork` 和 Add-on 构建注册、放置、工作分发及扩展能力。它适合：

- 需要一套可组合的多集群 API，而不是固定产品门户；
- 成员集群只能主动连接 Hub 的网络环境；
- 希望基于 Cluster Claim、Placement 和 Add-on 开发内部 Fleet Manager。

OCM 更像多集群控制面的构件集合。开源 OCM 与基于它构建的商业产品在安装体验、策略包、UI 和支持范围上并不相同。

参考：[OCM Concepts](https://open-cluster-management.io/docs/concepts/)、[OCM Placement](https://open-cluster-management.io/docs/concepts/content-placement/placement/)

### Karmada

Karmada 提供独立多集群 API Server、集群注册、`PropagationPolicy`、Override、放置、资源状态聚合和故障迁移能力。它更适合跨地域应用副本、环境差异覆盖和策略化分发。

Karmada 不创建底层 Kubernetes 集群，不是跨集群 CNI，也不会把多个集群中的 GPU 合并为一个节点级调度域。自定义 AI CRD 是否能正确估算资源、传播依赖和聚合状态，还取决于 Resource Interpreter 与目标版本能力。

参考：[Karmada Concepts](https://karmada.io/docs/core-concepts/concepts/)、[跨集群与大规模 GPU](multi-cluster-ai.md)

## 7. 开源工具对比

| 工具 | 核心定位 | 创建/升级集群 | 统一 UI/身份 | 配置或应用分发 | 适合的起点 |
| --- | --- | --- | --- | --- | --- |
| Headlamp | 轻量 Kubernetes UI | 否 | UI；身份依赖集群/外部系统 | 否 | 少量集群、开发者门户 |
| Rancher | 综合多集群管理平台 | 部分类型支持 | 强 | Fleet | 企业多集群统一入口 |
| KubeSphere | 多租户云原生平台门户 | 侧重注册和平台能力 | 强 | 平台 DevOps/应用能力 | 希望整合开发运维体验 |
| Portainer CE | 轻量多环境管理 | 弱 | 有 | 基础部署能力 | 实验室和小团队 |
| kubeadm/Kubespray/kOps | 安装和运维自动化 | 强 | 否 | 否 | 自建集群和基础设施自动化 |
| Cluster API | 声明式集群生命周期 API | 强 | 否 | 否 | 自建 Cluster-as-a-Service |
| Gardener | 大规模 Kubernetes as a Service | 强 | 有 | 侧重集群与系统组件 | 大规模、多云平台提供方 |
| Kubermatic CE | 自助式多云 Kubernetes 平台 | 强 | 有 | 部分能力依 Edition | 中大型平台团队 |
| Argo CD | 集中式 GitOps CD | 否 | 应用 UI/身份 | 强 | 多集群应用交付 |
| Flux | 分布式 Pull GitOps | 否 | 无官方 UI | 强 | 自治集群与配置收敛 |
| OCM | 可组合 Fleet 管理 API | 可集成 CAPI | 本身非完整门户 | 强 | 自研多集群平台 |
| Karmada | 跨集群应用编排 | 否 | 控制面 API 为主 | 强 | 多地域放置、Override、Failover |

表中的“强”只说明核心能力方向，不代表安装后自动满足高可用、安全、审计和灾备要求。

## 8. 面向 AI/GPU 集群的推荐组合

### 少量 GPU 集群

```text
云托管 Kubernetes / kubeadm / RKE2
  + OIDC、kubectl、Headlamp 或 k9s
  + Argo CD 或 Flux
  + GPU Operator、Kueue、监控和对象存储
```

先把节点验收、驱动矩阵、队列、镜像/模型分发和可观测做稳定，不要为了“将来可能多集群”提前引入联邦控制面。

### 多团队、多环境的 GPU 平台

```text
Rancher 或 KubeSphere：统一入口、团队和访问
GitOps：GPU/Network Operator、Kueue、KubeRay、Trainer、KServe
Cluster API 或既有 IaaS：集群和 GPU 节点池生命周期
```

平台门户负责身份和体验，Git 是配置权威来源，生命周期控制器负责机器与版本。三者必须避免修改同一字段。

### 多地域训练和推理 Fleet

```text
Cluster API / Gardener / 云 API：创建和升级集群
Argo CD / Flux：基线组件与运行时收敛
Karmada / OCM：应用、策略和区域放置
MultiKueue：把完整训练 Job 派发到一个可用集群
Gateway / DNS：在线推理流量切换
```

跨集群管理层应维护稳定能力标签，例如 GPU 厂商和型号、RDMA、地域、合规域、存储和模型缓存状态。真实可用容量与 GPU/NVLink/RDMA 拓扑仍由成员集群的 Kueue、Volcano、kube-scheduler 和设备管理层判断。

不要让一个分布式训练的 Rank 默认横跨普通 Kubernetes 集群。跨集群网络时延、NCCL/RDMA、Gang、Checkpoint 和故障语义都必须经过专门设计；常见方案仍是把完整训练任务择一放入单个集群。

## 9. 选型建议

| 当前问题 | 优先评估 |
| --- | --- |
| 只想更方便地看资源、日志和事件 | Headlamp 或 k9s，保留 kubectl |
| 多个现有集群需要统一登录和门户 | Rancher；也可评估 KubeSphere |
| 小团队同时管理 Docker 和少量 Kubernetes | Portainer CE |
| 要把集群创建、节点池和升级变成声明式 API | Cluster API |
| 要对外提供大规模、多云 Kubernetes 服务 | Gardener 或 Kubermatic |
| 要让各集群配置与 Git 持续一致 | Argo CD 或 Flux |
| 要建立可扩展的成员集群清单、Placement 和 Add-on | OCM |
| 要做跨地域应用放置、Override 和 Failover | Karmada |
| 要把训练 Job 根据队列和容量发送到某个集群 | MultiKueue |

如果团队还说不清当前缺的是 UI、身份、生命周期、配置收敛还是工作负载放置，就先不要安装新的中心控制面。

## 10. 上线前检查

- [ ] 每个集群和节点的生命周期所有者唯一；
- [ ] 人员通过 OIDC、短期凭据或代理访问，不共享静态管理员 kubeconfig；
- [ ] 管理平台本身有独立故障域、备份、升级和恢复流程；
- [ ] Agent、Hub 和成员集群间的网络方向、证书轮换和断连行为已测试；
- [ ] GitOps、门户和多集群控制器不会争抢同一对象字段；
- [ ] 集群注册不会默认授予超出需要的 `cluster-admin`；
- [ ] GPU、RDMA、驱动和 AI Operator 兼容矩阵按集群记录；
- [ ] 多集群标签有固定 Schema、来源、刷新频率和审计；
- [ ] 训练放置依据队列和完整拓扑，不只看聚合 GPU 数量；
- [ ] 已演练管理平面不可用、成员集群断连和凭据泄露的恢复流程。

## 延伸阅读

- [Kubernetes 跨集群与大规模 GPU](multi-cluster-ai.md)
- [平台运维、升级与多集群](../platform-operations.md)
- [AI 集群架构设计](architecture.md)
- [AI/LLM 集群组件清单](../../cases/ai-cluster-component-checklist.md)
