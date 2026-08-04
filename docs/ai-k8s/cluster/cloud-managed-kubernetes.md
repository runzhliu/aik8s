---
title: 国内外主流云厂商 Kubernetes
description: 对比阿里云 ACK、腾讯云 TKE、华为云 CCE、AWS EKS、Google GKE 和 Azure AKS 的托管边界与 AI/GPU 能力
status: evolving
last_reviewed: 2026-08-04
---

# 国内外主流云厂商 Kubernetes

云厂商托管 Kubernetes 的共同点是托管 API Server、etcd 和控制面高可用，并把 Kubernetes 与本云的计算、网络、存储、负载均衡、身份和可观测服务集成起来。差异主要不在 `kubectl` 能否使用，而在数据面由谁管理、节点能否定制、网络模型、异构算力、自动扩容、版本节奏和云服务绑定深度。

本文选择国内常见的阿里云 ACK、腾讯云 TKE、华为云 CCE，以及海外常见的 AWS EKS、Google GKE 和 Azure AKS。功能、地域、配额和价格变化频繁，上线前必须以目标地域和目标版本的官方控制台、文档和 SLA 为准。

## 1. 先理解托管边界

```text
云厂商负责
  机房和基础云 → 托管控制面 → 部分系统组件和升级能力

共同责任
  VPC/子网 → 节点池 → CNI/CSI → 身份 → 可观测 → 备份

用户负责
  Namespace/RBAC → Operator → 训练/推理 → 数据/模型 → SLO
```

“托管 Kubernetes”不表示云厂商自动负责以下工作：

- 选择正确的 Kubernetes 和节点 OS 升级窗口；
- 验证 GPU 驱动、CUDA、RDMA、训练框架和推理引擎兼容性；
- 为训练建立队列、公平共享、Gang 和 Checkpoint；
- 为推理建立容量、灰度、路由、模型分发和延迟 SLO；
- 备份用户创建的 Kubernetes 对象、PV 数据和外部依赖；
- 保证某个 GPU 型号在目标地域随时有足够库存。

全托管或 Autopilot 模式通常减少节点运维，但也会限制特权容器、自定义内核、驱动、RuntimeClass、HostPath、DaemonSet 或网络插件。AI/GPU 平台不能只因为“免运维”就默认选择它。

## 2. 国内云厂商

### 阿里云 ACK

阿里云容器服务 Kubernetes 版 ACK 提供托管集群、Serverless、Edge 和面向智能计算灵骏的集群形态。生产集群通常从 ACK 托管集群 Pro 版评估，控制面由阿里云托管，工作节点可使用 ECS、GPU 实例和部分裸金属/灵骏资源。

主要特点：

- 与 ECS、SLB、云盘、NAS、CPFS、OSS、ACR 和云监控集成；
- 提供面向 VPC/ENI 的容器网络与 CSI 存储接入；
- 节点池、集群升级、组件管理和弹性能力较完整；
- ACK Edge 面向云边协同，ACK Serverless 面向无需长期维护节点的工作负载；
- 云原生 AI 套件覆盖异构资源、GPU 共享、拓扑感知、队列调度、数据访问加速、训练和推理工具链；
- ACK 灵骏面向大规模 AI/HPC，强化多卡拓扑、eRDMA、共享 GPU 和批任务调度。

适合：已经大量使用阿里云网络、存储、ACR/OSS/CPFS，或者需要在中国大陆地域建设训练、推理和大数据一体化平台的团队。

注意点：ACK 集群类型和 AI 套件组件存在版本、规格与计费差异；共享 GPU、调度、数据加速等增强能力不等同于上游同名项目，迁移前要确认资源名、CRD、镜像、驱动和监控指标。

参考：[ACK 产品介绍](https://help.aliyun.com/zh/ack/product-overview/product-introduction)、[ACK 云原生 AI 套件](https://help.aliyun.com/zh/ack/cloud-native-ai-suite/product-overview/cloud-native-ai-suite-overview)、[ACK 异构计算](https://help.aliyun.com/zh/ack/ack-managed-and-ack-dedicated/user-guide/overview-5/)

### 腾讯云 TKE

腾讯云容器服务 TKE 提供标准集群、Serverless/超级节点、边缘和注册节点等方式。一个集群可以根据场景组合普通节点、面向 Kubernetes 优化的原生节点、超级节点，以及通过专线或公网纳管的外部节点。

主要特点：

- 与 CVM、CLB、CBS、CFS、COS、TCR 和腾讯云可观测体系集成；
- 支持 Global Router、VPC-CNI，以及部分混合云场景的 Cilium Overlay 等网络方式；
- 原生节点侧重快速供给、节点生命周期和资源效率；
- 超级节点提供类似 Serverless 的 Pod 算力和弹性方式；
- 注册节点适合把 IDC 或其他位置的节点纳入 TKE 管理，但网络、存储和云 API 可达性要单独设计；
- qGPU 提供显存和算力细粒度共享与隔离，并与 TKE 原生节点绑定；
- 产品体系还包括面向 AI Agent 的沙箱、跨地域算力等能力，具体成熟度和地域支持需按目标版本验证。

适合：业务已经深度使用腾讯云，关注在线服务弹性、混合节点形态、GPU 共享，或者需要把部分 IDC 资源与公有云控制面结合的团队。

注意点：普通节点、原生节点、超级节点和注册节点的生命周期、计费、可观测、GPU 能力和限制不同。qGPU 不是所有节点类型都支持；VPC-CNI 还受子网 IP、网卡数量和可用区约束。

参考：[TKE 产品概述](https://intl.cloud.tencent.com/zh/document/product/457/51208)、[TKE 节点与产品形态](https://cloud.tencent.com/product/tke)、[TKE qGPU](https://cloud.tencent.com/document/product/457/61448)、[TKE VPC-CNI](https://intl.cloud.tencent.com/zh/document/product/457/38970)

### 华为云 CCE

华为云云容器引擎 CCE 提供 CCE Standard、CCE Turbo 和 CCE Autopilot。Standard 面向通用托管 Kubernetes；Turbo 强化 VPC 直通、网络和调度性能；Autopilot 进一步托管节点并按工作负载资源使用计费。

主要特点：

- 与 ECS、裸金属、ELB、EVS、SFS、OBS、SWR 和云监控集成；
- 同时覆盖 x86、Arm、NVIDIA GPU 和昇腾 NPU；
- CCE AI Suite 提供 GPU/NPU 驱动、设备接入、虚拟化、监控和故障治理；
- Volcano Scheduler 与 CCE、GPU/NPU 和 CloudMatrix 拓扑结合，提供队列、Gang、优先级、拓扑感知和批任务调度；
- CCE Turbo 使用面向 VPC 的高性能容器网络，适合对网络时延和吞吐更敏感的场景；
- 昇腾 NPU、vNPU 和超节点/Hypernode 拓扑是其 AI 基础设施的重要差异点。

适合：采用华为云基础设施、需要 NVIDIA 与昇腾异构算力，或希望使用 Volcano 建设大规模训练、推理和批处理平台的团队。

注意点：Standard、Turbo 和 Autopilot 并非创建后可随意互转；网络模型、VPC/子网、可用区和控制面规格通常是早期架构决策。GPU/NPU 虚拟化强依赖集群、OS、内核、驱动、插件和硬件型号矩阵。

参考：[CCE 产品介绍](https://support.huaweicloud.com/intl/zh-cn/productdesc-cce/cce_productdesc_0001.html)、[CCE 产品功能](https://support.huaweicloud.com/productdesc-cce/cce_productdesc_0014.html)、[CCE 云原生 AI 套件](https://support.huaweicloud.com/intl/zh-cn/usermanual-cce/cce_10_0973.html)

## 3. 海外云厂商

### AWS EKS

Amazon Elastic Kubernetes Service（EKS）提供 EKS Standard 和 EKS Auto Mode。Standard 托管 Kubernetes 控制面，数据面可以使用 Managed Node Groups、自建节点、Karpenter、Fargate 或 Hybrid Nodes；Auto Mode 进一步托管节点、扩缩容、网络、负载均衡、DNS、块存储和部分 GPU 软件栈。

主要特点：

- 与 IAM、VPC CNI、Elastic Load Balancing、EBS/EFS/FSx、S3、ECR、CloudWatch 和 Managed Prometheus 深度集成；
- Managed Node Groups 提供节点创建、更新、排空和替换；
- Karpenter 和 Auto Mode 可以根据 Pending Pod 需求动态选择和创建 EC2；
- 支持 NVIDIA GPU、AWS Trainium/Inferentia、Neuron SDK 和 EFA 高速网络；
- EKS Auto Mode 内置部分 NVIDIA/Neuron 驱动和 Device Plugin，减少 GPU 节点软件维护；
- EKS Hybrid Nodes 和 EKS Anywhere 覆盖混合云与本地场景，但责任边界不同于公有云 EKS。

适合：AWS 是主要云平台、需要丰富 EC2 机型和 Spot、依赖 IAM/VPC/S3/FSx，或计划使用 Trainium/Inferentia 与 EFA 的团队。

注意点：Standard、Managed Node Groups、Karpenter、Fargate 和 Auto Mode 是不同数据面模型。Auto Mode 节点更不可变且限制直接登录和自定义；EFA 的 Device Plugin、DRA、Karpenter 和 Auto Mode 支持矩阵也不同。大型训练要在选型阶段确定 AMI、EFA、GPU/Neuron 拓扑和容量预留方式。

参考：[Amazon EKS](https://docs.aws.amazon.com/eks/latest/userguide/what-is-eks.html)、[EKS Auto Mode](https://docs.aws.amazon.com/eks/latest/userguide/automode.html)、[EKS GPU/Neuron](https://docs.aws.amazon.com/eks/latest/userguide/auto-accelerated.html)、[EKS EFA](https://docs.aws.amazon.com/eks/latest/userguide/device-management-efa.html)

### Google GKE

Google Kubernetes Engine（GKE）提供 Standard 与 Autopilot 两种运行模式。Standard 允许平台团队直接控制节点池和大部分基础设施设置；Autopilot 由 Google 管理节点、扩缩容、安全约束和更多默认配置。当前 GKE 也支持在 Standard 集群中通过 ComputeClass 让部分工作负载以 Autopilot 模式运行。

主要特点：

- 与 VPC、Cloud Load Balancing、Persistent Disk/Hyperdisk、Filestore、Cloud Storage、Artifact Registry 和 Cloud Monitoring 集成；
- Release Channel、自动升级和自动修复体系成熟；
- Autopilot 面向减少节点运维，Standard 面向特权、自定义网络和特殊硬件需求；
- 同时支持 NVIDIA GPU 和 Google TPU，TPU 以 Slice、拓扑和原子节点池表达；
- ComputeClass 可以声明候选硬件、GPU 和节点供给偏好；
- GKE Fleet、Config Sync 等能力可用于多集群治理，但会进一步绑定 Google Cloud 平台模型。

适合：希望获得成熟的托管 Kubernetes 体验、需要 TPU/JAX/Google AI 生态，或希望将通用工作负载和加速器工作负载统一放在 GKE 的团队。

注意点：Autopilot 对特权工作负载、节点定制和部分系统组件有约束；GPU/TPU 的计费和请求规则与普通 Pod 不同。多主机 TPU Slice 通常按完整拓扑创建、修复和缩放，不能把它当作普通可独立增减的节点池。

参考：[GKE 模式选择](https://docs.cloud.google.com/kubernetes-engine/docs/concepts/choose-cluster-mode)、[GKE Autopilot 与 Standard 对比](https://docs.cloud.google.com/kubernetes-engine/docs/resources/autopilot-standard-feature-comparison)、[GKE GPU](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/gpus)、[GKE TPU](https://docs.cloud.google.com/kubernetes-engine/docs/concepts/tpus)

### Azure AKS

Azure Kubernetes Service（AKS）提供 AKS Standard 和 AKS Automatic。Standard 让平台团队管理节点池、网络和更多基础设施选项；Automatic 提供生产默认值，并由 Azure 进一步管理节点供给、扩缩容、安全、监控和升级。

主要特点：

- 与 Microsoft Entra ID、Workload Identity、Azure CNI、Load Balancer/Application Gateway、Azure Disk/Files/Blob、ACR 和 Azure Monitor 集成；
- AKS Standard 支持多节点池、Windows 节点和多种网络选择；
- Node Auto-Provisioning 基于 Karpenter，根据 Pod 需求选择 VM SKU、Spot/按需容量并管理节点生命周期；
- 支持 NVIDIA GPU 节点池，并提供托管 GPU 节点池路径；
- 与 Azure Machine Learning、Microsoft Fabric、GitHub/Azure DevOps 和企业身份体系组合自然；
- Azure Arc-enabled Kubernetes 可统一连接其他位置的集群，但它不是 AKS 公有云控制面本身。

适合：企业身份和治理以 Entra/Azure Policy 为中心、已有大量 Azure 数据与应用服务、需要 Windows 容器，或希望与微软 AI/数据平台整合的团队。

注意点：Automatic 和 Standard 的 VM SKU、网络、节点访问和自定义范围不同。GPU 节点要核对目标区域库存、驱动安装方式、节点 OS 生命周期和自动升级策略；高性能多机训练还要单独确认支持 InfiniBand/RDMA 的 VM、拓扑和镜像组合。

参考：[Azure AKS](https://learn.microsoft.com/azure/aks/what-is-aks)、[AKS GPU](https://learn.microsoft.com/azure/aks/use-nvidia-gpu)、[AKS Node Auto-Provisioning](https://learn.microsoft.com/azure/aks/use-node-auto-provisioning)

## 4. 六家产品快速对比

| 服务 | 主要集群/数据面形态 | AI 加速器重点 | 弹性与节点 | 典型优势 |
| --- | --- | --- | --- | --- |
| 阿里云 ACK | 托管 Pro、Serverless、Edge、灵骏 | NVIDIA GPU、共享 GPU、eRDMA | 节点池、弹性节点、Serverless | 国内云生态、AI 套件、灵骏与数据加速 |
| 腾讯云 TKE | 标准、原生节点、超级节点、注册节点 | NVIDIA GPU、qGPU | 原生节点、超级节点、混合节点 | 节点形态灵活、在线弹性、GPU 共享 |
| 华为云 CCE | Standard、Turbo、Autopilot | NVIDIA GPU、昇腾 NPU、CloudMatrix | 节点池、Autopilot | GPU/NPU 异构、Volcano、云原生高性能网络 |
| AWS EKS | Standard、MNG、Karpenter、Fargate、Auto Mode、Hybrid | NVIDIA、Trainium、Inferentia、EFA | MNG、Karpenter、Auto Mode | AWS 服务集成、机型和 Spot、Neuron/EFA |
| Google GKE | Standard、Autopilot、Autopilot ComputeClass | NVIDIA GPU、TPU | NodePool、ComputeClass、Autopilot | Kubernetes 成熟度、TPU、自动化运维 |
| Azure AKS | Standard、Automatic、Virtual Nodes | NVIDIA GPU | NodePool、NAP/Karpenter、Automatic | Entra、微软企业生态、Azure AI/数据平台 |

这张表不能直接用于采购。每一项都要继续展开到目标地域、实例型号、交付周期、配额、预留、Spot 行为、网络带宽、存储吞吐、驱动版本和 SLA。

## 5. 云服务映射

| 能力 | ACK | TKE | CCE | EKS | GKE | AKS |
| --- | --- | --- | --- | --- | --- | --- |
| 镜像 Registry | ACR | TCR | SWR | ECR | Artifact Registry | ACR |
| 对象存储 | OSS | COS | OBS | S3 | Cloud Storage | Blob Storage |
| 块/文件存储 | 云盘、NAS、CPFS | CBS、CFS | EVS、SFS | EBS、EFS、FSx | Persistent Disk/Hyperdisk、Filestore | Azure Disk、Azure Files |
| 云身份 | RAM/OIDC 体系 | CAM/OIDC 体系 | IAM | IAM、Pod Identity | Workload Identity Federation | Entra Workload Identity |
| 云负载均衡 | SLB/ALB/NLB | CLB | ELB | ALB/NLB | Cloud Load Balancing | Azure Load Balancer/Application Gateway |
| 可观测 | ARMS/Prometheus/日志服务 | TMP/日志服务 | AOM/云监控 | CloudWatch/Managed Prometheus | Cloud Monitoring/Managed Prometheus | Azure Monitor/Managed Prometheus |

同名缩写可能冲突：阿里云 ACR 和 Azure ACR 都是 Registry；华为云 CCE 与百度智能云的容器产品缩写也可能相同。架构文档应写全产品名和云厂商，不要只写缩写。

## 6. 面向 GPU 训练的选择重点

大规模训练不要先比较控制台体验，而要逐项验证：

1. 目标 GPU/NPU/TPU 型号在哪些地域和可用区可交付；
2. 单节点卡数、PCIe/NVLink/NVSwitch 和 NUMA 拓扑；
3. 多机网络是普通 VPC、RoCE、InfiniBand、EFA、ICI 还是厂商超节点网络；
4. NCCL/HCCL/XLA、驱动、固件、OFED 和容器镜像由谁维护；
5. 是否支持 Gang、队列、公平共享、拓扑调度和整组扩容；
6. Spot/竞价回收通知、Checkpoint 和容量预留方式；
7. 对象存储、并行文件系统、本地 NVMe 和数据缓存吞吐；
8. 是否可以执行 NCCL Tests、存储基准和长时间故障演练。

各云的特色可以概括为：AWS 的 EFA 与 Trainium/Inferentia、GKE 的 TPU Slice、CCE 的昇腾与 Volcano/CloudMatrix、ACK 的灵骏/eRDMA 与 AI 套件、TKE 的 qGPU 和多节点形态、AKS 的 Azure GPU VM 与微软 AI 生态。真正的性能仍由具体实例、区域、网络和软件版本决定。

## 7. 面向 LLM 推理的选择重点

推理平台还要比较：

- GPU 小规格、共享、MIG/vGPU 和 Serverless GPU 是否真实可用；
- 节点从零扩容、镜像拉取和模型加载的完整冷启动时间；
- Registry、对象存储和节点缓存之间的模型分发链路；
- 负载均衡是否支持长连接、流式响应、Gateway API 和会话保持；
- 是否能按 TTFT、TPOT、队列深度、KV Cache 和模型维度观测；
- 跨可用区流量、NAT、公网出流和日志的隐性成本；
- 灰度、容量预热、优雅下线和故障域切换方式。

Autopilot、Auto Mode、Automatic 或超级节点能降低节点管理成本，但大模型权重加载可能远慢于节点创建。没有模型缓存、容量预留和预热流程时，“秒级扩容”不等于“秒级可服务”。

## 8. 可移植性与云绑定

Kubernetes API 提供了基础可移植性，但以下对象通常绑定云厂商：

- `StorageClass`、快照和文件系统参数；
- `Service`/Ingress/Gateway 的负载均衡 Annotation；
- Workload Identity 的 ServiceAccount Annotation 和云 IAM；
- CNI、Pod IP、Security Group 和 NetworkPolicy 实现；
- 节点标签、实例类型、可用区和容量类型；
- GPU/NPU/TPU 资源名、Device Plugin 和调度 CRD；
- 自动供给的 NodePool/NodeClass/ComputeClass API；
- 日志、指标、密钥、证书和数据库接入方式。

推荐把应用和平台拆成三层：

```text
可移植应用层
  Deployment / Job / Service / Gateway API / 标准指标

平台契约层
  GPU Capability、Queue、Model Artifact、Workload Identity、Storage Profile

云适配层
  CNI/CSI、LB Annotation、IAM、节点类、云监控和加速器插件
```

使用 Kustomize/Helm Overlay 或平台 Operator 生成云差异，不要让业务仓库到处复制云厂商 Annotation。多云的目标应是可重建和可迁移，而不是假设训练数据、模型、网络和 GPU 可以无成本实时漂移。

## 9. 怎么选

| 已有条件或核心诉求 | 优先评估 |
| --- | --- |
| 主要业务、数据和采购都在阿里云 | ACK Pro；大规模 AI 进一步评估 ACK 灵骏和 AI 套件 |
| 主要业务在腾讯云，重视节点弹性或 GPU 共享 | TKE 原生节点/超级节点与 qGPU |
| 需要昇腾 NPU，或已采用华为云与 Volcano | CCE Turbo/Standard 与 CCE AI Suite |
| AWS 是主云，需要丰富 EC2、Spot、EFA 或 Neuron | EKS Standard + Karpenter/MNG；再评估 Auto Mode |
| 需要 TPU/JAX，或希望高度自动化的 GKE 体验 | GKE Standard/Autopilot |
| 企业身份和数据平台围绕 Microsoft/Azure | AKS Standard/Automatic |
| 必须跨国内外云部署 | 先统一 OCI、GitOps、模型/数据接口和可观测，再选择各云托管 K8s |

如果 GPU 数量还很少、团队也没有 Kubernetes SRE 能力，云厂商的托管训练、Notebook 或推理服务可能比直接建设 Kubernetes 平台更合适。选择 Kubernetes 应由可移植控制器、多租户调度、统一运行时或平台 API 等明确需求驱动。

## 10. POC 清单

- [ ] 在目标地域实际创建目标模式的集群和 GPU 节点池；
- [ ] 记录控制面、节点、NAT、公网 IP、LB、存储、日志和跨区流量费用；
- [ ] 验证 Kubernetes 版本支持窗口、升级路径和节点 OS 生命周期；
- [ ] 验证 OIDC/Workload Identity，不向 Pod 发放长期云密钥；
- [ ] 验证 Pod IP 上限、子网耗尽、LB 配额和 DNS 行为；
- [ ] 验证云盘、文件存储、对象存储和本地 NVMe 吞吐；
- [ ] 验证 GPU 发现、驱动、拓扑、DCGM 和故障隔离；
- [ ] 执行 NCCL/HCCL/XLA、训练片段和 vLLM/SGLang 推理基准；
- [ ] 从零扩容并测量节点、镜像、模型到 Ready 的分段耗时；
- [ ] 演练节点升级、Spot 回收、可用区故障和控制面不可达；
- [ ] 用 IaC 与 GitOps 重建第二个集群，确认没有控制台隐藏配置；
- [ ] 明确退出路径：制品、数据、身份和网络怎样迁移到另一云或本地。

## 延伸阅读

- [开源 Kubernetes 集群管理工具与方式](open-source-management.md)
- [AI 集群架构设计](architecture.md)
- [Kubernetes 跨集群与大规模 GPU](multi-cluster-ai.md)
- [GPU 节点软件栈](gpu-node-stack.md)
- [多厂商异构加速器](../accelerators/heterogeneous-accelerators.md)
- [模型制品、分发与缓存](../data/model-artifacts.md)
