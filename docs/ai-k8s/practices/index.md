---
title: 实战、排障与选型
description: 用可复现的实验、性能数字、事故证据和决策树回答 AI/LLM on Kubernetes 的高频问题
status: evolving
last_reviewed: 2026-08-05
---

# 实战、排障与选型

这个系列不再按组件解释“它是什么”，而是从一个具体问题出发，给出证据链、实验变量、验收指标和停止条件。页面中的数字应由目标硬件和真实负载实测，示例值不能替代生产基线。

## 排障与事故

- [GPU 有空闲，Pod 为什么仍然 Pending](gpu-pending.md)
- [GPU 利用率为什么很低](low-gpu-utilization.md)
- [GPU 节点故障图鉴](gpu-failure-atlas.md)
- [AI 集群事故复盘方法](incident-review.md)

## 性能、成本与容量

- [vLLM、SGLang 与 TensorRT-LLM 同机实测](inference-engine-benchmark.md)
- [模型显存与并发容量计算器](model-memory-calculator.md)
- [Prefill/Decode 分离的性能拐点](pd-break-even.md)
- [国内外 GPU 云资源选型](cloud-gpu-selection.md)

## 平台和调度

- [GPU 资源银行与潮汐推理平台实践蓝图](gpu-resource-bank-tidal-platform.md)
- [Kueue 与 Volcano 对比实验](kueue-vs-volcano.md)
- [Kubernetes 还是 Slurm](kubernetes-vs-slurm.md)
- [KubeVirt 单节点桌面实战：本地盘、CDI 与浏览器 noVNC](kubevirt-local-desktop-lab.md)
- [用 KubeVirt 与 Ceph RBD 构建持久 GPU Notebook](kubevirt-rbd-notebook.md)
- [Spot GPU 与 Checkpoint 恢复实验](spot-checkpoint.md)
- [国产 GPU/NPU 的 Kubernetes 实践](domestic-accelerators.md)

## 端到端交付

- [在既有 Kubernetes 集群落地 AIBrix](aibrix-existing-cluster.md)
- [AIBrix 真实 GPU 实测：从两机推理到八节点碎片 GPU](aibrix-gpu-multinode-pd-production.md)
- [RBG 多角色推理编排与 sr1 实战](rbg-existing-cluster.md)
- [SGLang Model Gateway CPU 实战：动态发现、路由与故障摘除](sglang-model-gateway-cpu-lab.md)
- [从 Ollama 到 Kubernetes 生产推理](ollama-to-production.md)
- [70B 模型向百节点分发](model-distribution-100-nodes.md)
- [离线环境部署 AI/LLM 平台](air-gapped-ai-platform.md)
- [Agent Sandbox 攻防实验](agent-sandbox-red-team.md)

## 阅读和复现约定

每个实验至少记录：

1. Kubernetes、驱动、CUDA/ROCm/CANN 和组件版本；
2. GPU/NPU/TPU、CPU、内存、磁盘和网络拓扑；
3. 模型、精度、输入输出长度和并发分布；
4. 冷缓存/热缓存、失败重试和预热状态；
5. 原始日志、事件、指标、Trace 和时间戳；
6. 成功标准、失败标准和结果的不适用范围。

复现实验时先修改 Namespace、镜像、StorageClass、资源名和安全策略，不要直接把示例中的权限、镜像标签或云厂商参数复制到生产。
