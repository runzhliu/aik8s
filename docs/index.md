---
title: AI/LLM on Kubernetes 基础设施
description: 面向平台工程师、SRE、数据平台和模型服务团队的 AI/LLM 基础设施工程文档
hide:
  - toc
---

# AI/LLM on Kubernetes 基础设施知识库

Hi~你好👋, 这里是 runzhliu 的工作笔记，我是一名在 AI/LLM/大数据/Kubernetes 领域工作了十年的工程师，同时我也是一个记录狂人🤔，特别爱记笔记，这个站点是我基于这几年在 AI/LLM Infras 的工作经历总结的一些笔记，同时也经过一些大模型的润色发布的，希望和大家一起交流和学习，一起在大模型时代做一点🤏小事，无论是内容本身还是工作，欢迎大家找我交流😄👏!(runzhliu@163.com)

这是一套面向平台工程师、SRE、数据平台、训练和模型服务团队的工程文档，系统整理 AI/LLM 工作负载运行在 Kubernetes 上需要的基础设施知识。

内容从 GPU 节点、异构设备、大数据、调度队列、RDMA 和数据供给开始，延伸到分布式训练、LLM 推理、RAG、Agent 沙箱、可观测性、安全、成本和生产运维。每个专题尽量说明组件边界、选型条件、关键指标、故障路径和上线检查，而不只是罗列项目名称。

[进入完整技术地图](ai-k8s/index.md){ .md-button .md-button--primary }
[查看生产参考架构](ai-k8s/guides/reference-architectures.md){ .md-button }
[实战与排障](ai-k8s/practices/index.md){ .md-button }
[浏览工程案例](cases/index.md){ .md-button }
[RSS 订阅](https://aik8s.run/rss.xml){ .md-button }

## 常用官方网站

按技术层次整理的官方文档直达入口。项目能力、版本兼容性和安装方式变化较快，使用时以官方文档与目标版本的 Release Notes 为准。

<div class="grid cards" markdown>

-   **LLM 推理引擎**

    [vLLM](https://docs.vllm.ai/) · [SGLang](https://docs.sglang.io/) · [TensorRT-LLM](https://nvidia.github.io/TensorRT-LLM/) · [Triton Inference Server](https://docs.nvidia.com/deeplearning/triton-inference-server/user-guide/docs/) · [llama.cpp](https://github.com/ggml-org/llama.cpp) · [Ollama](https://docs.ollama.com/)

-   **推理服务与分布式编排**

    [KServe](https://kserve.github.io/website/) · [Ray / KubeRay](https://docs.ray.io/en/latest/cluster/kubernetes/) · [AIBrix](https://aibrix.readthedocs.io/latest/) · [llm-d](https://llm-d.ai/) · [NVIDIA Dynamo](https://docs.nvidia.com/dynamo/latest/)

-   **Kubernetes、GPU 与调度**

    [Kubernetes](https://kubernetes.io/docs/) · [NVIDIA GPU Operator](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/) · [Kueue](https://kueue.sigs.k8s.io/) · [Volcano](https://volcano.sh/docs/) · [Kubeflow](https://www.kubeflow.org/docs/)

-   **模型、训练与通信**

    [PyTorch](https://docs.pytorch.org/docs/stable/index.html) · [Hugging Face](https://huggingface.co/docs) · [DeepSpeed](https://deepspeed.readthedocs.io/) · [NCCL](https://docs.nvidia.com/deeplearning/nccl/user-guide/)

</div>

## 文档覆盖范围

<div class="grid cards" markdown>

-   **集群与加速器**

    理解 AI 工作负载从 Kubernetes API 到节点驱动、容器运行时和 GPU 的完整路径，建立可重复的节点验收和异构设备管理方式。

    [从基础架构开始](ai-k8s/foundations/kubernetes-for-ai.md)

-   **大数据、调度与分布式训练**

    处理 Spark/Flink/Kafka/Lakehouse、资源声明、队列准入、Gang Scheduling、RDMA、数据加载、Checkpoint 和故障恢复。

    [查看大数据基础设施](ai-k8s/data/big-data-on-kubernetes.md)

-   **LLM 推理与 RAG**

    覆盖推理引擎、批处理、KV Cache、量化、智能路由、Prefill/Decode 分离，以及向量检索和权限过滤。

    [查看推理技术地图](ai-k8s/llm-inference.md)

-   **平台工程与生产运维**

    用版本矩阵、基准测试、SLO、可观测性、安全策略、容量模型和发布门禁保持平台长期可运行。

    [查看平台运维体系](ai-k8s/platform-operations.md)

</div>

## 按你的任务开始

| 当前任务 | 建议阅读路径 |
| --- | --- |
| 第一次系统了解 AI on Kubernetes | [Kubernetes 如何承载 AI](ai-k8s/foundations/kubernetes-for-ai.md) → [集群架构设计](ai-k8s/cluster/architecture.md) → [完整技术地图](ai-k8s/index.md) |
| 建设 GPU 或异构算力集群 | [GPU 节点软件栈](ai-k8s/cluster/gpu-node-stack.md) → [设备管理](ai-k8s/accelerators/device-management.md) → [GPU 调度](ai-k8s/gpu-scheduling.md) |
| 建设 GPU Notebook 开发平台 | [Notebook 平台与存储](ai-k8s/development/gpu-notebook-platform.md) → [数据与缓存](ai-k8s/data-storage.md) → [MLOps](ai-k8s/mlops.md) |
| 建设大数据与 AI 数据平台 | [大数据 on Kubernetes](ai-k8s/data/big-data-on-kubernetes.md) → [数据与缓存](ai-k8s/data-storage.md) → [模型制品](ai-k8s/data/model-artifacts.md) → [MLOps](ai-k8s/mlops.md) |
| 建设多租户训练平台 | [队列与多租户](ai-k8s/queue-multitenancy.md) → [分布式训练](ai-k8s/distributed-training.md) → [RDMA 网络](ai-k8s/rdma-networking.md) → [可靠性](ai-k8s/reliability.md) |
| 建设 Ray 大模型平台 | [Ray 训练与推理](ai-k8s/ray-llm-platform.md) → [分布式训练](ai-k8s/distributed-training.md) → [可靠性](ai-k8s/reliability.md) |
| 建设 LLM 在线推理平台 | [推理平台总览](ai-k8s/llm-inference.md) → [引擎选型](ai-k8s/inference/engines.md) → [Serving 框架](ai-k8s/inference/serving-frameworks.md) → [智能路由](ai-k8s/inference/gateway-routing.md) → [Higress 实战](ai-k8s/inference/higress-ai-gateway.md) |
| 建设 RAG 或 Agent 服务 | [Agent 现状与趋势](ai-k8s/rag-agent/agent-landscape-2026.md) → [RAG 基础设施](ai-k8s/rag-agent/rag-infrastructure.md) → [OpenClaw 企业平台分析](ai-k8s/rag-agent/openclaw-enterprise-agent-platform.md) → [Agent Sandbox 选型](ai-k8s/rag-agent/agent-sandbox-selection.md) → [工具与执行治理](ai-k8s/agentic-workloads.md) → [安全治理](ai-k8s/security-governance.md) |
| 负责稳定性、成本和容量 | [可观测性](ai-k8s/observability.md) → [性能基准](ai-k8s/benchmarking.md) → [成本与容量](ai-k8s/cost-capacity.md) → [落地路线图](ai-k8s/adoption-roadmap.md) |

## 核心专题

### 计算与集群

- [Kubernetes 如何承载 AI](ai-k8s/foundations/kubernetes-for-ai.md)
- [AI 集群架构设计](ai-k8s/cluster/architecture.md)
- [GPU 节点软件栈](ai-k8s/cluster/gpu-node-stack.md)
- [多厂商异构加速器](ai-k8s/accelerators/heterogeneous-accelerators.md)
- [Device Plugin、CDI 与 DRA](ai-k8s/accelerators/device-management.md)

### 调度、网络与数据

- [GPU 与异构资源调度](ai-k8s/gpu-scheduling.md)
- [队列、公平共享与多租户](ai-k8s/queue-multitenancy.md)
- [AI 工作负载弹性伸缩](ai-k8s/scheduling/autoscaling.md)
- [RDMA 与 AI 高速网络](ai-k8s/rdma-networking.md)
- [大数据 on Kubernetes](ai-k8s/data/big-data-on-kubernetes.md)
- [模型制品、分发与缓存](ai-k8s/data/model-artifacts.md)

### 训练与推理

- [分布式训练平台](ai-k8s/distributed-training.md)
- [大模型 SFT 入门：把 Loss、LoRA、Batch 和并行一次讲明白](ai-k8s/training/sft-concepts.md)
- [大模型 SFT 训练实战：从单卡 LoRA 到 DeepSeek V4](ai-k8s/training/sft-from-single-gpu-to-deepseek-v4.md)
- [SwanLab 自托管：从 Kubernetes 部署到真实 SFT 指标](ai-k8s/training/swanlab-self-hosted.md)
- [从 W&B Local 到 SwanLab：两年团队实验追踪实践与选型](ai-k8s/training/wandb-vs-swanlab.md)
- [Ray 在大模型训练与推理中的角色](ai-k8s/ray-llm-platform.md)
- [LLM 推理平台总览](ai-k8s/llm-inference.md)
- [推理引擎选型](ai-k8s/inference/engines.md)
- [LLM Serving 与 AI 微服务框架](ai-k8s/inference/serving-frameworks.md)
- [LLM 推理性能优化](ai-k8s/inference/optimization.md)
- [AI Gateway 与智能路由](ai-k8s/inference/gateway-routing.md)
- [Higress AI Gateway：架构、安装与 AIBrix 接入实战](ai-k8s/inference/higress-ai-gateway.md)
- [分布式与 Prefill/Decode 分离推理](ai-k8s/inference/distributed-serving.md)

### 应用基础设施与治理

- [大模型时代的 GPU Notebook 平台与存储选型](ai-k8s/development/gpu-notebook-platform.md)
- [2026 年 AI Agent 现状、实现原理与趋势](ai-k8s/rag-agent/agent-landscape-2026.md)
- [RAG 基础设施](ai-k8s/rag-agent/rag-infrastructure.md)
- [Agent Sandbox 选型与架构分析](ai-k8s/rag-agent/agent-sandbox-selection.md)
- [CubeSandbox Kubernetes 部署条件与生产评估](ai-k8s/rag-agent/cubesandbox-kubernetes.md)
- [OpenClaw 作为企业 Agent 平台底座](ai-k8s/rag-agent/openclaw-enterprise-agent-platform.md)
- [AI Agent、沙箱与工具执行](ai-k8s/agentic-workloads.md)
- [GPU、训练与推理可观测性](ai-k8s/observability.md)
- [AI 平台安全与治理](ai-k8s/security-governance.md)
- [平台运维、升级与多集群](ai-k8s/platform-operations.md)

## 可直接使用的参考材料

- [AI/LLM 集群组件清单](cases/ai-cluster-component-checklist.md)：按场景说明需要哪些组件、为什么需要、何时可以不装以及怎样验收。
- [五种生产参考架构](ai-k8s/guides/reference-architectures.md)：小型 GPU 平台、多租户训练、高可用推理、分离式推理和 Agent 沙箱。
- [GPU 平台最小闭环实验](ai-k8s/guides/gpu-platform-lab.md)：从 GPU 发现和冒烟测试，到 vLLM 服务、网络策略和冷启动测量。
- [AI on Kubernetes 十年发展史](ai-k8s/history.md)：理解关键接口和工具为什么出现，以及当前技术主线。
- [术语表](ai-k8s/reference/glossary.md)：快速查询设备、调度、训练、推理、网络和 RAG 术语。
- [30/60/90 天落地路线图](ai-k8s/adoption-roadmap.md)：把架构目标拆成可执行的实施阶段。

## 实战案例

[工程案例](cases/index.md) 单独收录可执行清单和真实环境记录。其中 [AI/LLM 集群组件清单](cases/ai-cluster-component-checklist.md) 用于确定建设范围，[K3s 集群升级与 DRA 预检](k3s-upgrade/index.md) 保存了一次真实环境的版本跨度评估、备份、兼容性检查、升级和验证过程。

## 内容标准

- 优先使用 Kubernetes SIG、项目官方文档和公开规范等一手资料。
- 区分稳定原理、快速演进的上游能力和仅用于学习的实验配置。
- 选型结论必须落到吞吐、延迟、可靠性、成本、安全或运维复杂度。
- 示例必须能说明验证方法；生产落地还要补齐版本固定、权限、密钥、容量、备份和回滚。
- 保留已有页面地址，新增内容按主题目录组织，避免链接随导航调整而失效。

建议先进入 [完整技术地图](ai-k8s/index.md)，再按当前角色选择一条阅读路径。

## 关注微信公众号

更多 AI/LLM on Kubernetes 实战、部署记录与性能分析会同步到微信公众号 **AI-K8S技术工程**。使用微信扫描二维码，或在“微信搜一搜”中搜索 `AI-K8S技术工程`：

<p align="center">
  <img src="assets/wechat-official-account-promo.png" alt="扫描二维码或通过微信搜一搜关注公众号 AI-K8S技术工程" width="900">
</p>
