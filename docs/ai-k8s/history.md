---
title: AI on Kubernetes 十年发展史
description: 从 GPU Device Plugin、训练 Operator、MLOps 到 DRA、Inference Gateway 和分离式推理
status: stable
last_reviewed: 2026-08-02
---

# AI on Kubernetes 十年发展史

AI on Kubernetes 不是一个单独产品，而是一套逐步形成的云原生 AI 基础设施。过去十年的核心变化，是 Kubernetes 从“能运行使用 GPU 的容器”，发展为能够表达分布式训练、稀缺加速器、模型服务和生成式推理特征的平台底座。

## 一、发展阶段

| 阶段 | 核心问题 | 主要变化 | 代表工具/能力 |
| --- | --- | --- | --- |
| 2016—2017 | Pod 如何使用 GPU | Extended Resource、Device Plugin、HugePages、CPU Manager | NVIDIA Device Plugin、kubelet Device Manager |
| 2018—2020 | 多角色训练如何运行 | Training Operator、Gang Scheduling、Notebook 和 Pipeline | Kubeflow、Volcano、MPI Operator、Argo |
| 2020—2022 | 实验到生产如何治理 | Pipeline、实验追踪、模型注册、统一 Serving、队列 | MLflow、KServe、Flyte、Kueue、KubeRay |
| 2023—2024 | LLM 如何高吞吐运行 | Paged KV、连续 Batch、GPU 共享、拓扑与成本 | vLLM、SGLang、LWS、KServe、DCGM |
| 2025—2026 | 设备、Workload 和请求如何协同 | DRA、Workload/PodGroup、Inference Extension、P/D 分离 | DRA、JobSet、LWS、llm-d、Dynamo |

## 二、2016—2017：让 Kubernetes 看见 GPU

早期 Kubernetes 主要面向 CPU 和内存。GPU、FPGA、RDMA 等设备需要一种不把厂商逻辑写入核心的扩展机制。

Device Plugin 形成后，厂商插件可以向 kubelet 注册扩展资源：

```yaml
resources:
  limits:
    nvidia.com/gpu: "1"
```

这解决了设备库存和容器分配，但能力主要是整数计数。设备型号、显存、拓扑、共享和动态配置仍依赖节点标签与厂商机制。

同一时期 CPU Manager、HugePages、Topology Manager 等能力逐步为高性能工作负载建立底座。

## 三、2018—2020：训练语义进入 Operator

分布式训练不只是多个相同 Pod。它包含不同角色、Rank、Rendezvous、整体启动、失败恢复和完成状态。

Kubeflow Training Operator、MPI Operator 等控制器将这些语义写入 CRD。Volcano、早期 Gang Scheduling 方案解决“任务必须一次获得整组资源”的问题，避免部分 Worker 启动后长期占用 GPU。

这一阶段的典型平台开始包含：

- Jupyter Notebook；
- Pipeline/DAG；
- 训练 Operator；
- 批调度与队列；
- 模型服务；
- 实验元数据。

但许多团队也经历了“安装完整 Kubeflow 等于拥有 MLOps”的误区。组件存在不代表数据、模型和审批已经形成闭环。

## 四、2020—2022：MLOps 与平台工程

规模增长后，问题从“能运行”变成“能否复现、共享和治理”：

- 哪个代码、数据、镜像和配置产生了模型；
- 实验指标如何比较；
- 模型如何注册、审批和回滚；
- 多团队如何共享 GPU；
- 训练失败由平台还是用户负责；
- 发布是否能自动评估。

MLflow、Kubeflow Pipelines、Argo Workflows、Flyte 等承担实验和工作流；KServe 形成统一推理 API；Kueue 将队列、配额和借用带入 Kubernetes 原生工作负载准入；KubeRay 让 Ray 集群和任务进入控制器模型。

## 五、2023—2024：LLM 改变推理系统

LLM 的请求和资源模型与普通预测服务不同：

- 模型权重和 KV Cache 占用大量显存；
- 输入输出长度高度变化；
- 流式连接持续时间长；
- 动态/连续 Batch 决定吞吐；
- Prefix Cache 让请求带有状态亲和；
- Tensor/Pipeline Parallel 让一个副本跨设备；
- Token 而不是请求数成为容量和成本单位。

vLLM 的 PagedAttention 和高吞吐服务生态、SGLang 的 Prefix/Radix 能力、TensorRT-LLM 的硬件优化，使推理引擎成为独立基础设施层。

LeaderWorkerSet 开始表达“一个模型副本由 Leader 和多个 Worker 构成”，Gateway 和服务控制面也需要理解模型级状态，而不是仅把 Pod 视作无状态 HTTP 后端。

## 六、2025—2026：从 Pod 到设备、Workload 和请求

这一阶段有三条并行演进路线。

### 设备级

Dynamic Resource Allocation 使用 DeviceClass、ResourceSlice 和 ResourceClaim，让设备属性、选择和共享不再只能依赖整数扩展资源。Kubernetes 1.34 将核心 DRA API 推进到 GA，1.36 又继续扩展 Driver、Workload Claim 和设备能力。

### Workload 级

Kueue、JobSet、LeaderWorkerSet、Kubeflow Trainer 等已经把多个 Pod 视为一个整体。Kubernetes 1.36 的 Workload/PodGroup API 继续推动上游调度器理解成组工作负载、拓扑和抢占。

### 请求级

Gateway API Inference Extension 引入 InferencePool、InferenceModel 和 Endpoint Picker，使 Gateway 能按模型、队列、KV Cache 和实时状态选择后端。

llm-d、NVIDIA Dynamo 等系统进一步组合：

- Prefix/KV-aware Routing；
- KV Cache Index/Offload；
- Prefill/Decode 分离；
- NIXL/UCX/RDMA 传输；
- 多机、多池和多种引擎；
- Flow Control 和联合扩缩容。

## 七、控制对象的演进

```text
第一阶段：Pod
  设备能不能被容器使用

第二阶段：Job / Workload
  一组 Pod 能不能整体获得资源并完成

第三阶段：Model Service
  一个模型副本如何跨 Pod、加载、发布和扩缩

第四阶段：Inference Request
  一次请求应进入哪个模型、Cache 和计算阶段
```

每次上移都不会让下一层消失。请求级 Router 仍依赖正确的 Pod 调度，DRA 仍依赖驱动和容器运行时。

## 八、基础设施主线

截至 2026 年，一套常见开源主线可以概括为：

```text
Kubernetes + containerd + CNI/CSI
  → GPU/Accelerator Operator + Device Plugin/DRA
  → Kueue/Volcano + JobSet/LWS
  → Kubeflow Trainer/KubeRay
  → KServe/Deployment + vLLM/SGLang/TensorRT-LLM
  → Gateway API Inference Extension/AI Gateway
  → Prometheus/DCGM/OpenTelemetry
  → MLflow/Kubeflow Hub + GitOps + Policy
```

这不是必须全部安装的标准答案。小团队应从最少组件开始，只有当队列、拓扑、缓存、路由或治理问题真实出现时再增加对应控制器。

## 九、长期不变的工程原则

1. **Kubernetes 不等于 MLOps。** 它不自动管理数据血缘、模型质量和审批。
2. **GPU 可分配不等于 GPU 被有效使用。** 数据、网络和 Batch 都可能是瓶颈。
3. **更多 GPU 不一定更快。** 并行通信和拓扑可能让收益为负。
4. **组件数量不是成熟度。** 可复现、可观测、可升级和可回滚才是。
5. **请求调度不能替代容量治理。** Router 无法凭空创造 GPU。
6. **实验功能必须标注版本和状态。** DRA、Inference 和 P/D 生态变化很快。
7. **质量与性能必须绑定。** 更快但质量下降的模型不是同一产品。
8. **先建立基线，再引入优化。** 否则无法知道收益和回归来源。

## 十、延伸阅读

- [Kubernetes 十年回顾](https://kubernetes.io/blog/2024/06/06/10-years-of-kubernetes/)
- [CNCF Cloud Native AI Whitepaper](https://www.cncf.io/reports/cloud-native-artificial-intelligence-whitepaper/)
- [Kubernetes 1.34 DRA GA](https://kubernetes.io/blog/2025/09/01/kubernetes-v1-34-dra-updates/)
- [Kubernetes 1.36 Workload-aware Scheduling](https://kubernetes.io/blog/2026/05/13/kubernetes-v1-36-advancing-workload-aware-scheduling/)
- [Gateway API Inference Extension](https://gateway-api-inference-extension.sigs.k8s.io/)
- [llm-d](https://llm-d.ai/)
