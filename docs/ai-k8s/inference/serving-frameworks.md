---
title: LLM Serving 与 AI 微服务框架
description: 对比 vLLM、KServe、AIBrix、Ray Serve、BentoML、NVIDIA NIM 与应用编排框架的层次、组合方式和选型边界
status: evolving
last_reviewed: 2026-08-04
---

# LLM Serving 与 AI 微服务框架

“大模型微服务框架”不是一个单一类别。vLLM 解决模型计算，KServe/AIBrix 管理模型服务，Ray Serve/BentoML 组织 Python 推理应用，Dify/LangGraph 等编排 RAG、Agent 和业务流程。选型前必须先确定缺的是哪一层。

## 1. 先分清六层

```text
业务应用 / Agent / RAG Workflow
  Dify、LangGraph、LlamaIndex、Haystack、自研服务
                         │
AI 应用微服务与调用图
  Ray Serve、BentoML、普通 FastAPI/gRPC
                         │
Gateway 与请求调度
  AIBrix Gateway、Gateway API Inference Extension、Envoy AI Gateway
                         │
Serving 控制面
  KServe、AIBrix、KubeRay/RayService、NIM Operator、Deployment/LWS
                         │
推理引擎
  vLLM、SGLang、TensorRT-LLM、Triton
                         │
GPU、模型权重、KV Cache、网络与存储
```

同一平台通常会组合多层。例如 `AIBrix + vLLM`、`KServe + vLLM`、`RayService + Ray Serve LLM + vLLM` 都是合理组合，而不是互斥产品。

## 2. 主流方案定位

| 方案 | 核心定位 | 适合 | 主要代价 |
| --- | --- | --- | --- |
| Deployment + vLLM | 最小模型服务 | 单模型、先建立性能基线 | 发布、智能路由、缓存和高级弹性自行补齐 |
| KServe | Kubernetes 原生模型 Serving 控制面 | 标准化模型 API、Canary、Runtime、平台自助服务 | CRD/网关/存储集成和版本矩阵 |
| AIBrix | 面向 LLM 的 Kubernetes 推理控制面 | LLM Gateway、路由、Autoscaling、LoRA、KV 和分布式推理 | 项目演进快，组件较多，需验证目标版本 |
| Ray Serve / Serve LLM | Python 组合式服务与分布式 LLM Serving | 多阶段推理图、多机/多模型、已有 Ray 生态 | 引入 Ray 集群、Actor 与双层调度运维 |
| BentoML | Python-first 模型和 AI 应用打包/服务 | 快速把自定义模型、RAG、vLLM 包成服务 | 集群级配额、Gang、设备拓扑仍需平台补充 |
| NVIDIA NIM | NVIDIA 验证的模型推理微服务与企业生命周期 | 希望减少运行时验证、需要企业支持 | NVIDIA/NGC/许可与支持矩阵约束 |
| Dify/LangGraph 等 | AI 应用和 Agent Workflow | Prompt、工具、知识库和业务流程 | 不是 GPU Serving 控制面，也不替代推理引擎 |

## 3. vLLM 是引擎，不是完整平台

vLLM 负责：

- 加载模型并执行 Token 计算；
- Continuous Batching 与 Paged KV Cache；
- Prefix Cache、量化、LoRA 和多种并行；
- OpenAI-Compatible API；
- 暴露引擎和请求指标。

它通常不独立负责：

- 跨团队配额、认证和 Token 预算；
- Kubernetes 发布、Canary 和集群级扩缩；
- 多模型的全局路由和故障域；
- 模型制品审批与数据治理；
- RAG/Agent 的完整调用图。

最小生产起点可以是 `Deployment + Service + Gateway + vLLM`。只有出现明确需求，再增加 KServe、AIBrix 或 Ray Serve，避免一开始叠加多个控制面。

参考：[vLLM Documentation](https://docs.vllm.ai/)

## 4. KServe：标准化模型服务

KServe 适合平台团队向用户提供统一的模型部署接口：

- `InferenceService` 管理通用模型和普通 LLM 服务；
- `ServingRuntime` 固定容器、协议与模型加载契约；
- `LLMInferenceService` 面向 Prefix-aware Routing、P/D 分离和高级 LLM 能力；
- Modelcar、LocalModelCache 等能力连接模型制品和节点缓存；
- 与 Gateway、Autoscaler、LWS、Kueue 等 Kubernetes 组件组合。

选择 KServe 的关键理由不是“少写一份 Deployment”，而是让不同团队使用相同的发布、状态、路由、模型加载和策略入口。

参考：[KServe](https://kserve.github.io/website/docs/)、[LLMInferenceService](https://kserve.github.io/website/docs/concepts/architecture/control-plane-llmisvc)

## 5. AIBrix：面向 LLM 的控制面

AIBrix 面向 Kubernetes 上大规模 LLM 推理，核心能力包括：

- 基于 Envoy Gateway 的 LLM Gateway 和模型路由；
- 根据实时推理负载设计的 Autoscaler；
- LoRA Model Adapter 生命周期与高密度复用；
- 分布式 KV Cache 编排；
- 多节点和 Prefill/Decode 分离式推理；
- 面向 vLLM 指标和 OpenAI-Compatible API 的集成。

概念结构：

```text
Client
  → Envoy Gateway / AIBrix Router
      ├── Model/Adapter/Request Policy
      ├── Load/Prefix-aware Routing
      └── vLLM Replica / Distributed Inference Pool
              ├── Model Adapter
              ├── KV Cache
              └── Autoscaler
```

适合评估：

- 已有多模型、多副本和 LoRA 动态加载需求；
- 普通 Service/Ingress 无法利用队列、模型和缓存状态；
- 需要 LLM 专用弹性，而非只按 CPU/HPA；
- 计划统一 vLLM 服务的入口和运营能力。

不宜直接引入：

- 只有一个或少量 vLLM Pod；
- 尚未建立 TTFT、TPOT、Queue、KV 和 Token 基准；
- 团队无法维护 Gateway、Controller、CRD 和引擎版本矩阵；
- 只是需要标准发布，KServe/Deployment 已满足需求。

AIBrix、KServe 和 Gateway API Inference Extension 的能力存在交叉。生产平台应选定谁拥有模型 CRD、Endpoint 发现、路由和扩缩决策，避免多个控制器同时写同一对象。

参考：[AIBrix](https://aibrix.readthedocs.io/latest/)、[AIBrix Gateway Routing](https://aibrix.readthedocs.io/latest/features/gateway-plugins.html)、[AIBrix Autoscaler](https://aibrix.readthedocs.io/latest/designs/aibrix-autoscaler.html)

## 6. Ray Serve：组合式 Python 微服务

Ray Serve 用 Deployment、Replica 和 Handle 组织有向调用图，每个步骤可以声明独立 CPU/GPU、并发、Batch 与 Autoscaling。它适合：

- Preprocess → Retriever → Reranker → LLM → Guardrail；
- 多模型 Ensemble、级联和降级；
- Python 对象在组件间传递；
- 多机 vLLM/SGLang 和复杂 LLM Serving；
- 训练、后训练和 Serving 已共享 Ray 生态。

在 Kubernetes 上使用 KubeRay `RayService` 管理 RayCluster 与 Serve Application。详细设计见[Ray 在大模型训练与推理中的角色](../ray-llm-platform.md)。

参考：[Ray Serve](https://docs.ray.io/en/latest/serve/)、[Ray Serve LLM](https://docs.ray.io/en/latest/serve/llm/)

## 7. BentoML：从 Python 模型到服务

BentoML 提供 Python Service、模型/依赖打包、API、Runner/服务组合和部署工具，适合开发团队快速把以下内容变成可交付服务：

- 自定义 PyTorch/Transformers 模型；
- vLLM OpenAI-Compatible Endpoint；
- Embedding、Reranker 和 Guardrail；
- RAG 或 Compound AI 流程；
- 需要自定义前后处理的推理 API。

它更接近应用与模型服务开发框架。Kubernetes 集群级 GPU 队列、拓扑、模型缓存、多租户网络和成本治理仍要由平台层设计。

参考：[BentoML](https://docs.bentoml.com/en/latest/)

## 8. NVIDIA NIM：验证过的推理微服务

NVIDIA NIM 把模型、推理运行时、配置、健康和可观测接口包装为推理微服务。NIM Operator 通过 `NIMService`、`NIMCache` 等资源管理部署、模型缓存、健康和弹性。

适合：

- NVIDIA GPU 环境，需要厂商验证与企业支持；
- 希望减少模型、量化、Runtime 和硬件组合验证；
- 需要统一部署 LLM、Embedding、Reranker、语音或视觉模型；
- 有 NGC、许可、离线部署和供应链流程。

需要评估：

- 支持模型、GPU、Profile 和许可；
- NIM 容器与上游 vLLM/SGLang 特性的时间差；
- NGC 凭据、模型缓存和 Air-gap；
- NIM Operator 与现有 KServe/GitOps/Autoscaler 的职责重叠。

参考：[NVIDIA NIM for LLMs](https://docs.nvidia.com/nim/large-language-models/latest/introduction.html)、[NIM Operator](https://docs.nvidia.com/nim-operator/latest/)

## 9. Dify、LangGraph 等属于应用层

应用编排框架通常管理：

- Prompt、模型 Provider 和 Workflow；
- RAG、知识库、工具和 Agent 状态；
- 人机审批、业务规则和会话；
- 应用级 Trace、评估和运营。

它们通常不管理：

- GPU 设备分配与拓扑；
- vLLM 的 KV Cache 和 Batch；
- 多机模型 Rank 与 NCCL；
- Kubernetes 集群队列和节点扩容；
- 模型权重的高性能分发。

推荐通过内部 AI Gateway 调用标准 OpenAI-Compatible/KServe API，使应用层与底层 vLLM/AIBrix/KServe/Ray Serve 解耦。

## 10. 组合模式

### 模式 A：最小开源栈

```text
Gateway/Ingress → Deployment + vLLM → GPU
```

适合单模型或验证阶段。先建立性能、发布、缓存和故障基线。

### 模式 B：标准化模型平台

```text
Gateway → KServe InferenceService → vLLM/SGLang
```

适合多团队自助发布、Canary 和统一 Runtime。

### 模式 C：LLM 专用控制面

```text
AIBrix Gateway/Router
  → AIBrix 管理的 Model/Adapter/Autoscaling
  → vLLM Replica / Distributed Pool
```

适合模型、LoRA、流量与缓存规模已经出现专用调度需求。

### 模式 D：组合式 Python AI 服务

```text
Enterprise Gateway → RayService
  → Ray Serve Application
      → Retriever / Reranker / vLLM / Guardrail
```

适合多个 Python 组件独立扩缩和多机 LLM Serving。

### 模式 E：企业支持栈

```text
Enterprise Gateway → NIMService/KServe → NIM LLM → NVIDIA GPU
```

适合重视厂商支持、验证配置和安全维护周期的环境。

## 11. 不要重复拥有控制权

上线前为每项能力指定唯一 Owner：

| 能力 | 可能 Owner | 必须避免 |
| --- | --- | --- |
| 模型服务 CRD | KServe / AIBrix / NIM Operator / RayService | 同一服务由多个 CRD 生成 |
| Endpoint 路由 | AIBrix / EPP / Ray Serve / Gateway | 多层各自重试和缓存亲和冲突 |
| 副本扩缩 | HPA/KEDA / AIBrix / Ray Serve | 多个 Autoscaler 同时写副本数 |
| 模型缓存 | KServe LocalModel / NIMCache / 自研 DaemonSet | 重复下载和不同淘汰策略 |
| P/D 编排 | AIBrix / llm-d / Dynamo / Ray Serve LLM | 不兼容 KV Connector 混用 |
| Canary | Gateway / KServe / GitOps | 多层流量比例相乘且不可解释 |

## 12. 选型顺序

1. 用 `Deployment + vLLM/SGLang` 建立模型与硬件性能基线；
2. 需要统一模型发布时评估 KServe；
3. 需要 LLM 专用路由、LoRA、缓存和弹性时评估 AIBrix；
4. 需要 Python 组合服务或已有 Ray 时评估 Ray Serve；
5. 需要开发者打包体验时评估 BentoML；
6. 需要 NVIDIA 验证与支持时评估 NIM；
7. Dify/LangGraph 等应用层始终通过稳定 API 与 Serving 层解耦。

## 13. 上线检查清单

- [ ] 已区分推理引擎、控制面、网关和应用编排；
- [ ] 每种控制权只有一个 Owner；
- [ ] 有不引入框架的 vLLM/SGLang 性能基线；
- [ ] API、模型名、错误码和流式行为形成稳定契约；
- [ ] 模型缓存、启动探针、预热和滚动发布已验证；
- [ ] Autoscaler 使用 Queue/Token/KV/延迟等推理指标；
- [ ] LoRA、Prefix Cache 和租户路由不会泄漏数据；
- [ ] Gateway、控制器、Runtime 和模型版本已锁定；
- [ ] 单副本、节点、Gateway 和控制面故障完成演练；
- [ ] 能解释新增框架相对基础 Deployment 的收益。
