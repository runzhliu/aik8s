---
title: AI/LLM on Kubernetes 基础设施
description: 从加速器、大数据和集群，到训练、推理、RAG、Agent 与生产运维的完整技术地图
status: stable
last_reviewed: 2026-08-04
---

# AI/LLM on Kubernetes 基础设施

这套文档讨论的不是“怎样把一个带 GPU 的 Pod 跑起来”，而是怎样把 Kubernetes 建设成一套可持续演进的 AI/LLM 基础设施：设备能被发现和隔离，作业能公平排队，数据能跟上算力，训练能够恢复，推理能够满足延迟目标，模型和依赖能够追溯，平台能够升级、观测和审计。

内容覆盖从硬件到应用的完整链路，并尽量回答四类问题：组件负责什么、什么时候需要、怎样验证、出问题从哪里排查。

[按主题浏览](#topic-map){ .md-button .md-button--primary }
[查看参考架构](guides/reference-architectures.md){ .md-button }
[运行 GPU 平台实验](guides/gpu-platform-lab.md){ .md-button }

## 基础设施全景

```text
用户、SDK、应用与工作流
        │
        ├─ 大数据 / RAG / Agent / 在线推理 / 训练任务
        │
Gateway、Serving、Trainer、Pipeline、Queue
        │
Kubernetes API、控制器、调度器、准入与策略
        │
Device Plugin / CDI / DRA / CNI / CSI / CRI
        │
GPU、TPU、NPU、CPU、RDMA、NVMe、对象存储
        │
供电、散热、机架、故障域与数据中心网络
```

任何一层都可能成为瓶颈。GPU 利用率低不一定是 GPU 问题，也可能是排队策略、CPU 解码、模型下载、存储吞吐、网络拥塞、请求路由或批处理参数造成的。阅读和排障时，应沿着完整请求或作业链路逐层验证。

## 从哪里开始

| 你的目标 | 建议路径 |
| --- | --- |
| 从零理解 AI 如何运行在 Kubernetes 上 | [Kubernetes 如何承载 AI](foundations/kubernetes-for-ai.md) → [集群架构设计](cluster/architecture.md) → [术语表](reference/glossary.md) |
| 建设或接管 GPU 集群 | [GPU 节点软件栈](cluster/gpu-node-stack.md) → [设备管理](accelerators/device-management.md) → [GPU 调度](gpu-scheduling.md) → [平台运维](platform-operations.md) |
| 选择开源集群管理平台 | [开源集群管理工具与方式](cluster/open-source-management.md) → [平台运维](platform-operations.md) → [跨集群与大规模 GPU](cluster/multi-cluster-ai.md) |
| 选择国内外云厂商 Kubernetes | [云厂商托管 Kubernetes](cluster/cloud-managed-kubernetes.md) → [集群架构设计](cluster/architecture.md) → [异构加速器](accelerators/heterogeneous-accelerators.md) |
| 建设 GPU Notebook 开发平台 | [GPU Notebook 平台与存储](development/gpu-notebook-platform.md) → [GPU 调度](gpu-scheduling.md) → [数据与缓存](data-storage.md) → [MLOps](mlops.md) |
| 建设大数据与 AI 数据平台 | [大数据 on Kubernetes](data/big-data-on-kubernetes.md) → [数据与缓存](data-storage.md) → [模型制品](data/model-artifacts.md) → [MLOps](mlops.md) |
| 建设多租户训练平台 | [队列与多租户](queue-multitenancy.md) → [分布式训练](distributed-training.md) → [RDMA 网络](rdma-networking.md) → [可靠性](reliability.md) |
| 建设 Ray 大模型平台 | [Ray 训练与推理](ray-llm-platform.md) → [分布式训练](distributed-training.md) → [大数据 on Kubernetes](data/big-data-on-kubernetes.md) → [可靠性](reliability.md) |
| 建设在线 LLM 推理服务 | [本地运行与测试](inference/local-testing.md) → [推理平台总览](llm-inference.md) → [推理引擎](inference/engines.md) → [Serving 框架](inference/serving-frameworks.md) → [网关与路由](inference/gateway-routing.md) |
| 规划多地域或多 GPU 集群 | [集群架构设计](cluster/architecture.md) → [跨集群与大规模 GPU](cluster/multi-cluster-ai.md) → [生产参考架构](guides/reference-architectures.md) |
| 建设 RAG 或 Agent 平台 | [RAG 基础设施](rag-agent/rag-infrastructure.md) → [Agent Sandbox 选型](rag-agent/agent-sandbox-selection.md) → [工具与执行治理](agentic-workloads.md) → [安全治理](security-governance.md) |
| 负责 SRE、成本或容量 | [可观测性](observability.md) → [性能基准](benchmarking.md) → [成本与容量](cost-capacity.md) → [落地路线图](adoption-roadmap.md) |

## 完整主题地图 { #topic-map }

### 基础与架构

- [Kubernetes 如何承载 AI](foundations/kubernetes-for-ai.md)：从 API、控制器、调度器到 CRI、CNI、CSI 和设备接口。
- [AI 集群架构设计](cluster/architecture.md)：工作负载画像、节点池、故障域、单集群与多集群边界。
- [开源 Kubernetes 集群管理工具与方式](cluster/open-source-management.md)：从 kubectl、Headlamp 和 GitOps，到 Rancher、Cluster API、Gardener、Karmada 与 OCM 的分层选型。
- [国内外主流云厂商 Kubernetes](cluster/cloud-managed-kubernetes.md)：对比 ACK、TKE、CCE、EKS、GKE 和 AKS 的托管边界、网络存储生态与 AI/GPU 能力。
- [Kubernetes 跨集群与大规模 GPU](cluster/multi-cluster-ai.md)：Federation 历史、Karmada/MultiKueue 等当前能力，以及训练整 Job 放置和区域级推理架构。
- [AI on Kubernetes 十年发展史](history.md)：从 GPU Pod、Operator 和批调度，到 DRA、推理网关与分离式推理。
- [术语表](reference/glossary.md)：统一 Kubernetes、GPU、训练、推理、网络、RAG 和可靠性术语。

### 集群、节点与加速器

- [GPU 节点软件栈](cluster/gpu-node-stack.md)：固件、内核、驱动、容器运行时、CDI、Operator 与节点验收。
- [多厂商异构加速器](accelerators/heterogeneous-accelerators.md)：NVIDIA、AMD、Intel、TPU、Trainium/Inferentia 与 CPU/NPU。
- [Device Plugin、CDI 与 DRA](accelerators/device-management.md)：三者的职责、迁移路径和生产选型。
- [GPU 与异构资源调度](gpu-scheduling.md)：整卡、MIG、共享、拓扑、亲和性与碎片治理。

### 队列、弹性与容量

- [队列、公平共享与多租户](queue-multitenancy.md)：Kueue、ClusterQueue、Flavor、Cohort、优先级与抢占。
- [AI 工作负载弹性伸缩](scheduling/autoscaling.md)：HPA、KEDA、Cluster Autoscaler、Karpenter 与队列协同。
- [GPU 成本与容量规划](cost-capacity.md)：单位经济性、需求预测、利用率、Spot 和 FinOps。

### 网络、数据与模型制品

- [RDMA 与 AI 高速网络](rdma-networking.md)：InfiniBand、RoCE、GPUDirect、NCCL 和逐层排障。
- [AI 数据、存储与缓存](data-storage.md)：对象存储、共享文件、本地 NVMe、数据加载与缓存层级。
- [大数据 on Kubernetes](data/big-data-on-kubernetes.md)：Spark、Flink、Kafka、Trino、Lakehouse、Operator、队列调度，以及训练与 RAG 数据链路。
- [模型制品、分发与缓存](data/model-artifacts.md)：格式、版本、OCI Modelcar、跨地域复制、P2P、节点缓存、流式加载和冷启动。

### 分布式训练

- [分布式训练平台](distributed-training.md)：Kubeflow Trainer、KubeRay、JobSet 与训练生命周期。
- [Ray 在大模型训练与推理中的角色](ray-llm-platform.md)：Ray Core、Data、Train、Tune、Serve、Serve LLM 与 KubeRay 的端到端边界。
- [可靠性、Checkpoint 与故障恢复](reliability.md)：RPO/RTO、Spot、优雅退出和故障演练。

### LLM 推理

- [本地运行与测试大模型](inference/local-testing.md)：用 Ollama、llama.cpp、LM Studio、LocalAI、MLX-LM 和 vLLM/SGLang 验证模型与应用契约。
- [LLM 推理平台总览](llm-inference.md)：服务抽象、运行时、请求链路和容量模型。
- [推理引擎选型](inference/engines.md)：vLLM、SGLang、TensorRT-LLM、Triton、llama.cpp 等运行时的边界。
- [LLM Serving 与 AI 微服务框架](inference/serving-frameworks.md)：vLLM、KServe、AIBrix、Ray Serve、BentoML、NVIDIA NIM 与应用层框架。
- [LLM 推理性能优化](inference/optimization.md)：TTFT、TPOT、批处理、KV Cache、量化、并行和推测解码。
- [AI Gateway 与智能路由](inference/gateway-routing.md)：Gateway API Inference Extension、前缀感知、负载感知和流控。
- [分布式与 Prefill/Decode 分离推理](inference/distributed-serving.md)：模型并行、LeaderWorkerSet、llm-d、Dynamo 和 KV 传输。

### RAG、Agent 与边缘

- [RAG 基础设施](rag-agent/rag-infrastructure.md)：采集、切分、Embedding、向量数据库、检索、重排和权限过滤。
- [Agent Sandbox 选型与架构分析](rag-agent/agent-sandbox-selection.md)：威胁模型、Kubernetes Agent Sandbox、gVisor、Kata、微虚机和托管平台决策。
- [AI Agent、沙箱与工具执行](agentic-workloads.md)：RuntimeClass、网络边界、凭据、工具权限和审计。
- [边缘 AI 与云边协同](edge-ai.md)：K3s、弱网自治、设备管理、模型 OTA 和边缘可观测性。

### 平台工程与生产运维

- [大模型时代的 GPU Notebook 平台与存储选型](development/gpu-notebook-platform.md)：JupyterHub、Kubeflow、托管 Workbench、GPU 共享、用户 Home、对象存储和本地缓存。
- [MLOps 与平台工程](mlops.md)：流水线、实验、模型注册、GitOps 和平台 API。
- [GPU、训练与推理可观测性](observability.md)：DCGM、作业指标、TTFT/TPOT、Trace、SLO 和告警。
- [AI 平台安全与治理](security-governance.md)：身份、Pod Security、镜像与模型供应链、租户隔离。
- [性能基准、压测与回归](benchmarking.md)：硬件、NCCL、存储、训练、推理和发布门禁。
- [平台运维、升级与多集群](platform-operations.md)：版本矩阵、Canary、CRD、备份、灾备和事故响应。
- [AI on K8s 落地路线图](adoption-roadmap.md)：从现状评估到 30/60/90 天实施计划。

### 参考架构与实验

- [生产参考架构](guides/reference-architectures.md)：小型 GPU 平台、多租户训练、高可用推理、分离式推理和 Agent 沙箱。
- [GPU 平台最小闭环实验](guides/gpu-platform-lab.md)：资源发现、GPU 冒烟、vLLM 服务、网络策略、冷启动和优雅下线。
- [AI/LLM 集群组件清单](../cases/ai-cluster-component-checklist.md)：按目标场景列出组件、必要性、引入理由和验收条件。

## 工具不等于架构

同一层通常有多个项目可选，项目之间也可能重叠。选择工具前先写清输入、输出、所有者和验收指标。

| 能力 | 常见实现 | 先回答的问题 |
| --- | --- | --- |
| 设备接入 | Device Plugin、CDI、DRA、厂商 Operator | 需要整卡、分片、拓扑还是动态声明？ |
| 批调度 | kube-scheduler、Kueue、Volcano | 需要准入队列、公平共享还是 Gang Scheduling？ |
| 大数据计算 | Spark、Flink、Trino、Ray Data | 是批处理、流状态、交互 SQL 还是 AI 数据准备？ |
| 训练控制 | Kubeflow Trainer、JobSet、KubeRay | 训练框架、容错和弹性边界是什么？ |
| 模型服务 | KServe、Seldon、自建控制器 | 需要标准模型 API、多模型还是 LLM 专用能力？ |
| 推理运行时 | vLLM、SGLang、TensorRT-LLM、Triton | 目标模型、硬件、延迟和吞吐是什么？ |
| 请求入口 | Gateway API、Inference Extension、服务网格 | 路由需要理解模型、KV Cache 和队列状态吗？ |
| Agent 执行 | Agent Sandbox、gVisor、Kata、托管 Sandbox API | 生命周期、隔离运行时和工具授权是否已经分层？ |
| 可观测性 | Prometheus、OpenTelemetry、DCGM Exporter | 能否从用户请求追到 Pod、GPU、网络和模型版本？ |

## 内容状态和更新规则

- `stable`：原理和生产方法相对稳定，仍需结合目标 Kubernetes 和组件版本验证。
- `evolving`：上游 API、项目边界或最佳实践仍在快速变化，上线前应检查官方版本说明。
- `lab`：用于复现和学习的最小实验，不应不经评审直接复制到生产。
- `last_reviewed`：最近一次按一手资料复核的日期，不代表所有依赖都固定在该日期。
- 示例优先表达结构和验证方法；生产配置还必须补齐镜像固定、容量、身份、密钥、备份、SLO 和变更流程。

## 建议的建设顺序

1. 先建立节点、驱动、网络、存储和 GPU 的可重复验收基线。
2. 再统一资源模型、队列、租户、镜像、模型制品和可观测性。
3. 分别为训练、在线推理、离线推理、RAG 和 Agent 建立黄金路径。
4. 用性能基准、故障演练、成本指标和升级矩阵形成持续交付门禁。
5. 最后再根据规模引入 DRA、高级拓扑、分离式推理、多集群和复杂调度策略。

如果正在规划第一版平台，可以从 [生产参考架构](guides/reference-architectures.md) 选一个最接近的起点，再用 [落地路线图](adoption-roadmap.md) 拆成阶段目标。
