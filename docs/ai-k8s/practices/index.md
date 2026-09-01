---
title: 实战、排障与选型
description: 用可复现的实验、性能数字、事故证据和决策树回答 AI/LLM on Kubernetes 的高频问题
status: evolving
last_reviewed: 2026-08-14
---

# 实战、排障与选型

这个系列不再按组件解释“它是什么”，而是从一个具体问题出发，给出证据链、实验变量、验收指标和停止条件。页面中的数字应由目标硬件和真实负载实测，示例值不能替代生产基线。

## 排障与事故

- [GPU 有空闲，Pod 为什么仍然 Pending](gpu-pending.md)
- [GPU 利用率为什么很低](low-gpu-utilization.md)
- [GPU 节点故障图鉴](gpu-failure-atlas.md)
- [看似 NCCL 故障，实际是 Host Memory OOM](nccl-unhandled-cuda-error-host-memory-oom.md)
- [AI 集群事故复盘方法](incident-review.md)

## 性能、成本与容量

- [DeepSeek-V4-Flash-Vision-Exp Day 0：4×H20 多模态部署与压测](deepseek-v4-flash-vision-exp-day0-h20.md)
- [GLM-5.3 首日实测：8×H20 上的 SGLang 与 vLLM 基线压测](glm53-h20-sglang-vllm-test-plan.md)
- [Hy4-preview BF16 双机 H20 实测：SGLang 与 vLLM 怎么选](hy4-preview-hardware-benchmark-plan.md)
- [Qwen3.8-Flash-Next Day 0 实战：4×H20 跑通原生 262K](qwen38-flash-next-sglang-day0.md)
- [SGLang v0.5.16 / v0.5.17 / v0.5.18 单卡 L20 实测：升级真的更快吗](sglang-0518-release-analysis.md)
- [DeepSeek V4 Flash 的分布式 KV Cache：从 P/D 直传到全局缓存池](distributed-kv-cache-deepseek-v4.md)
- [从半小时到五分钟：大模型冷启动全链路优化](llm-cold-start-optimization.md)
- [大模型权重分发与加载加速：社区与商业方案选型](model-weight-delivery-acceleration.md)
- [vLLM、SGLang 与 TensorRT-LLM 同机实测](inference-engine-benchmark.md)
- [模型显存与并发容量计算器](model-memory-calculator.md)
- [Prefill/Decode 分离的性能拐点](pd-break-even.md)
- [国内外 GPU 云资源选型](cloud-gpu-selection.md)

## 平台和调度

- [大模型时代 GPU 开发平台踩坑记](gpu-notebook-platform-evolution.md)
- [8 卡节点的四卡任务，如何避免拿到跨 NUMA 的碎片 GPU](gpu-topology-fragmentation-scheduling.md)
- [GPU 资源银行与潮汐推理平台实践蓝图](gpu-resource-bank-tidal-platform.md)
- [Kueue 与 Volcano 对比实验](kueue-vs-volcano.md)
- [Kubernetes 还是 Slurm](kubernetes-vs-slurm.md)
- [KubeVirt 单节点桌面实战：本地盘、CDI 与浏览器 noVNC](kubevirt-local-desktop-lab.md)
- [用 KubeVirt 与 Ceph RBD 构建持久 GPU Notebook](kubevirt-rbd-notebook.md)
- [Spot GPU 与 Checkpoint 恢复实验](spot-checkpoint.md)
- [国产 GPU/NPU 的 Kubernetes 实践](domestic-accelerators.md)

## 端到端交付

- [大模型 SFT 入门：把 Loss、LoRA、Batch 和并行一次讲明白](../training/sft-concepts.md)
- [大模型 SFT 训练实战：从单卡 LoRA 到 DeepSeek V4](../training/sft-from-single-gpu-to-deepseek-v4.md)
- [RDMA 到底能让分布式训练快多少：DeepSeek V4 双机 16 卡实测](../training/rdma-distributed-training-benchmark.md)
- [SwanLab 自托管：从 Kubernetes 部署到真实 SFT 指标](../training/swanlab-self-hosted.md)
- [从 W&B Local 到 SwanLab：两年团队实验追踪实践与选型](../training/wandb-vs-swanlab.md)
- [用 SGLang-Omni 部署 MiniMax-Music3：从一句创意到完整歌曲](minimax-music3-sglang-omni.md)
- [Qwen3.8-27B Day 0：vLLM 与 SGLang 测试记录](qwen38-27b-day0.md)
- [从 Docker 到 Kubernetes：DeepSeek Harness、内置 Chromium 与 DSH Plugin 实战](deepseek-harness-kubernetes.md)
- [GLM-5.2 FP8 在 8×H20 141GB 上的 AIBrix + vLLM 实测](glm52-fp8-h20-aibrix-vllm.md)
- [DeepSeek-V4-Flash-0731 的 H20 部署与压测](deepseek-v4-flash-h20-evaluation.md)
- [在既有 Kubernetes 集群落地 AIBrix](aibrix-existing-cluster.md)
- [AIBrix 真实 GPU 实测：从两机推理到八节点碎片 GPU](aibrix-gpu-multinode-pd-production.md)
- [在 Kubernetes 部署 ComfyUI：离线镜像、CephFS 模型与跨集群 Ingress](comfyui-minimax-h3-gpu.md)
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
