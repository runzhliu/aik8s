---
title: AI & Kubernetes 工程知识库
description: 面向 AI 基础设施、平台工程和模型服务团队的 Kubernetes 实战知识库
hide:
  - toc
---

# 把 AI 工作负载真正跑在 Kubernetes 上

> 面向 AI 基础设施、平台工程和模型服务团队，系统讲清 GPU 集群、分布式训练、LLM 推理、RDMA、Agent 沙箱，以及上线后的成本、安全与运维。

这里不是新闻聚合，也不是工具名称大全。每篇专题都围绕一个生产问题展开：**为什么需要、组件如何分工、怎样选型、用什么指标验收、出问题从哪里查。**

[开始阅读 AI on K8s](ai-k8s/index.md){ .md-button .md-button--primary }
[查看 30/60/90 天落地路线](ai-k8s/adoption-roadmap.md){ .md-button }

## 你可以在这里解决什么

<div class="grid cards" markdown>

-   **🧩 规划 GPU 平台**

    从 Device Plugin、DRA、队列、拓扑和共享方式开始，建立清晰的计算资源模型。

    [GPU 与异构资源调度 →](ai-k8s/gpu-scheduling.md)

-   **🚄 提高训练效率**

    把数据供给、分布式通信、RDMA、Checkpoint 和故障恢复放到同一条性能链路中。

    [分布式训练平台 →](ai-k8s/distributed-training.md)

-   **⚡ 建设 LLM 推理服务**

    理解 vLLM、KServe、LWS、智能路由、KV Cache、Prefill/Decode 和弹性伸缩。

    [LLM 推理平台 →](ai-k8s/llm-inference.md)

-   **🛠️ 做好 Day-2 运营**

    用可观测性、FinOps、安全策略、性能基准和版本矩阵把平台长期稳定运行起来。

    [平台运维、升级与多集群 →](ai-k8s/platform-operations.md)

</div>

## 从你的角色开始

| 你正在做什么 | 建议阅读路径 |
| --- | --- |
| 第一次了解 AI on K8s | [十年发展与工具全景](ai-k8s/index.md) → [落地路线图](ai-k8s/adoption-roadmap.md) |
| 负责 GPU 集群和资源治理 | [GPU 调度](ai-k8s/gpu-scheduling.md) → [队列与多租户](ai-k8s/queue-multitenancy.md) → [成本与容量](ai-k8s/cost-capacity.md) |
| 优化多机多卡训练 | [分布式训练](ai-k8s/distributed-training.md) → [RDMA 网络](ai-k8s/rdma-networking.md) → [数据与存储](ai-k8s/data-storage.md) → [可靠性](ai-k8s/reliability.md) |
| 建设 LLM 推理平台 | [LLM 推理](ai-k8s/llm-inference.md) → [可观测性](ai-k8s/observability.md) → [性能基准](ai-k8s/benchmarking.md) → [成本与容量](ai-k8s/cost-capacity.md) |
| 运行 AI Agent 或代码沙箱 | [Agent 与工具执行](ai-k8s/agentic-workloads.md) → [安全治理](ai-k8s/security-governance.md) → [可观测性](ai-k8s/observability.md) |
| 负责升级、稳定性和事故响应 | [平台运维](ai-k8s/platform-operations.md) → [故障恢复](ai-k8s/reliability.md) → [性能回归](ai-k8s/benchmarking.md) |

## 17 篇专题构成一张完整地图

### 算力、队列与数据

- [GPU 与异构资源调度](ai-k8s/gpu-scheduling.md)：整卡、MIG、共享、DRA 与拓扑。
- [队列、公平共享与多租户](ai-k8s/queue-multitenancy.md)：Kueue、Flavor、Cohort、优先级与抢占。
- [AI 数据、存储与缓存](ai-k8s/data-storage.md)：对象存储、共享文件、本地 NVMe 与模型分发。
- [RDMA 与 AI 高速网络](ai-k8s/rdma-networking.md)：InfiniBand、RoCE、GPUDirect、NCCL 与逐层排障。

### 训练、推理与 Agent

- [分布式训练平台](ai-k8s/distributed-training.md)：Kubeflow Trainer、KubeRay、JobSet 与训练生命周期。
- [可靠性、Checkpoint 与故障恢复](ai-k8s/reliability.md)：RPO/RTO、Spot、PDB 与故障演练。
- [LLM 推理平台](ai-k8s/llm-inference.md)：运行时、模型服务、请求路由与 KV Cache。
- [AI Agent、沙箱与工具执行](ai-k8s/agentic-workloads.md)：Agent Sandbox、RuntimeClass、工具权限与审计。
- [边缘 AI、K3s 与云边协同](ai-k8s/edge-ai.md)：弱网自治、设备管理和模型 OTA。

### 平台工程与治理

- [MLOps 与平台工程](ai-k8s/mlops.md)：流水线、实验、模型注册、GitOps 与平台 API。
- [GPU、训练与推理可观测性](ai-k8s/observability.md)：DCGM、TTFT/TPOT、Trace、SLO 与告警。
- [AI 平台安全与治理](ai-k8s/security-governance.md)：身份、Pod Security、镜像和模型供应链。
- [GPU 成本、容量规划与 FinOps](ai-k8s/cost-capacity.md)：单位经济性、OpenCost、弹性与预算。
- [性能基准、压测与回归](ai-k8s/benchmarking.md)：硬件、NCCL、存储、训练和推理门禁。
- [平台运维、升级与多集群](ai-k8s/platform-operations.md)：版本矩阵、Canary、CRD、备份与灾备。
- [AI on K8s 落地路线图](ai-k8s/adoption-roadmap.md)：从问题清单到 30/60/90 天实施计划。

## 实战记录

理论专题之外，站内也保存真实环境的操作与验证记录：

- [K3s 升级与 DRA 预检](k3s-upgrade/index.md)：从版本跨度、备份和兼容性检查，到升级后的节点与工作负载验证。

## 内容原则

- **职责边界优先**：先分清 Kubernetes、Operator、调度器、运行时和业务代码分别负责什么。
- **指标优先**：选型最终落到吞吐、延迟、可靠性、成本和质量，而不是组件数量。
- **生产问题优先**：每章包含故障模式、上线清单或验收方法。
- **一手资料优先**：关键结论尽量链接 Kubernetes SIG、项目官方文档和公开规范。
- **渐进落地**：从最小可用栈开始，规模和治理需求出现后再增加组件。

---

如果你只准备读一篇，先从 [AI on Kubernetes 十年发展与工具全景](ai-k8s/index.md) 开始；如果已经在建设平台，直接进入 [落地路线图](ai-k8s/adoption-roadmap.md)。
