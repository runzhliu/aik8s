# LLM 推理平台

传统模型服务多半是“一个请求对应一次短计算”，而 LLM 推理具有长连接、流式输出、动态批处理、巨量显存和 KV Cache 等特征。平台设计因此从普通 Service 负载均衡，演进到模型感知、缓存感知和请求感知的调度。

## 一、先分清四层

```text
客户端 / OpenAI-Compatible API
            │
            ▼
网关与请求调度：Gateway API / Inference Gateway / Envoy AI Gateway
            │
            ▼
服务控制面：KServe / Ray Serve / Seldon / 自研 Operator
            │
            ▼
推理引擎：vLLM / SGLang / Triton / TensorRT-LLM
            │
            ▼
GPU、模型权重、KV Cache、网络与存储
```

- **推理引擎**执行模型计算，决定批处理、量化、并行和缓存效率。
- **服务控制面**管理 Deployment、模型加载、健康检查、扩缩容和版本。
- **推理网关**理解模型、请求和后端状态，选择合适实例。
- **Kubernetes**提供资源、生命周期、网络和故障恢复底座。

把这几层混成一个“Serving 工具”会造成选型误判。例如 KServe 和 vLLM 通常是组合关系，不是二选一。

## 二、推理引擎怎么选

| 引擎 | 主要特点 | 常见场景 |
| --- | --- | --- |
| vLLM | 连续批处理、PagedAttention、OpenAI API、广泛模型与硬件支持 | 通用 LLM 在线与批推理，云原生生态集成最活跃 |
| SGLang | Radix/Prefix Cache、结构化生成、复杂 Agent/多模态工作负载 | 重复前缀多、结构化输出和推理程序 |
| NVIDIA Triton | 多框架、动态批处理、模型仓库、统一指标 | 传统 ML/DL、多模型、多后端统一服务 |
| TensorRT-LLM | NVIDIA 平台深度优化、编译和 Kernel 优化 | 追求 NVIDIA GPU 极限性能且接受构建复杂度 |
| llama.cpp / Ollama | 轻量、CPU/边缘/开发体验 | 本地开发、小模型和边缘，不是大规模集群首选 |

评测时必须固定模型、精度、上下文长度、输入/输出 Token 分布、并发、硬件和 SLO。只比较“每秒 Token”而不看 TTFT 与尾延迟，结论通常没有生产意义。

## 三、KServe 的两个主要入口

### InferenceService

标准 `InferenceService` 适合传统预测模型和大多数普通 LLM 部署。它提供：

- 模型制品加载与可插拔 ServingRuntime；
- Deployment/Service、健康检查和网络管理；
- Canary、A/B 和推理图；
- Standard、Knative/Serverless 等部署模式；
- vLLM、Triton 和自定义容器等后端。

### LLMInferenceService

当平台需要 Prefix-aware Routing、KV Cache Offloading、Prefill/Decode 分离或更细粒度的多机 GPU 管理时，可以评估 `LLMInferenceService`。截至 2026 年，其 API 仍处于较快演进阶段，生产平台应固定版本并保留迁移测试。

KServe 官方建议先从标准 InferenceService 开始，确实遇到高级 LLM 需求时再切换到 LLMInferenceService。

参考：[KServe Administrator Guide](https://kserve.github.io/website/docs/admin-guide/overview)、[LLMInferenceService Architecture](https://kserve.github.io/website/docs/concepts/architecture/control-plane-llmisvc)

## 四、多机模型需要 LeaderWorkerSet

当单个模型副本跨多台机器分片时，一个“副本”已经不再是一个 Pod。LeaderWorkerSet（LWS）把一个 Leader 和若干 Worker 作为整体复制和管理，提供稳定身份、并行创建和统一生命周期。

适合 LWS 的模式：

- 一个模型副本使用多节点 Tensor Parallel / Pipeline Parallel；
- Leader 接收请求，Worker 只参与 Collective；
- 需要以整个 Pod Group 为单位扩缩和滚动升级；
- 一个服务运行多个互相独立的分布式模型副本。

LWS 解决工作负载编排，不自动解决队列准入和 GPU 配额。生产中通常还需要 Kueue 负责成组准入和拓扑感知。

参考：[LeaderWorkerSet](https://lws.sigs.k8s.io/)

## 五、为什么普通轮询不够

两个 vLLM Pod 即使副本规格相同，真实状态也可能不同：

- 一个实例已有相同 System Prompt 的 Prefix Cache；
- 一个实例队列已满，另一个空闲；
- 一个实例正在加载 LoRA Adapter；
- 一个实例可用显存更少或处于恢复状态；
- 请求模型、版本、上下文长度和优先级不同。

普通 Service 轮询看不到这些信息。Gateway API Inference Extension 引入 `InferencePool` 和 Endpoint Picker，让路由器根据模型服务暴露的指标与能力筛选、打分后端。

可用的路由信号包括：

- 请求的模型和 Adapter 是否已加载；
- KV/Prefix Cache 命中可能性；
- Running Request、Waiting Queue 与预计延迟；
- GPU KV Cache 使用率和可接受的最大上下文；
- 租户优先级、Token 预算和流控策略。

参考：[Gateway API Inference Extension](https://gateway-api-inference-extension.sigs.k8s.io/)

## 六、KV Cache 是一种分布式资源

KV Cache 直接影响显存占用、吞吐和延迟。平台要明确四类缓存：

| 缓存 | 内容 | 价值 | 风险 |
| --- | --- | --- | --- |
| 模型权重缓存 | 模型文件、Tokenizer、Adapter | 缩短 Pod 冷启动 | 本地盘空间、一致性和淘汰 |
| Prefix Cache | 重复 Prompt 的 KV | 降低 TTFT 和重复计算 | 路由必须保持缓存亲和 |
| Runtime KV Cache | 活跃请求上下文 | 支撑生成过程 | 占用大量 GPU 显存 |
| Offloaded/Distributed KV | CPU、NVMe 或远端缓存 | 扩大上下文或跨实例复用 | 网络开销和一致性复杂度 |

“把请求发给最空闲实例”不总是最优；如果另一个稍忙的实例已有高价值 Prefix Cache，总成本可能反而更低。因此现代推理路由是多目标优化，而不是简单 Least Connections。

## 七、Prefill / Decode 分离

LLM 请求大致分为：

- **Prefill**：处理全部输入 Token，计算密集、并行度高；
- **Decode**：逐 Token 生成，受显存带宽和同步延迟影响，更关注尾延迟。

在大规模场景中，可以由不同 GPU Pool 分别承担 Prefill 和 Decode，再传输 KV Cache。好处是两类负载可以独立扩容和调参；代价是：

- 增加 KV 传输和网络要求；
- 故障路径和可观测性更复杂；
- 小规模或短 Prompt 场景可能得不偿失；
- 容量规划必须同时平衡两个 Pool。

llm-d 将 vLLM、Inference Gateway、KV Cache 感知路由、流控和分离式推理组合成可复用方案。它适合达到一定规模后优化性能/成本，不应成为第一个 LLM Pod 的前置条件。

参考：[llm-d](https://llm-d.ai/)

## 八、扩缩容应该看什么

CPU 使用率通常不是 LLM 服务的有效扩缩容信号。更有价值的指标包括：

- Waiting Request / Queue Depth；
- Running Request 与最大并发；
- Prompt/Generation Token Rate；
- KV Cache 使用率；
- TTFT、TPOT 和 P95/P99；
- 请求拒绝、超时与 Preemption；
- 每个副本的模型加载状态。

### 常用延迟指标

| 指标 | 含义 |
| --- | --- |
| TTFT | Time To First Token，用户等到首个 Token 的时间 |
| TPOT | Time Per Output Token，首 Token 后平均每 Token 时间 |
| ITL | Inter-Token Latency，相邻 Token 间延迟 |
| E2E | 从请求进入到完成的总延迟 |

一个简化容量关系：

```text
并发需求 ≈ 到达率 × 平均请求持续时间
所需副本 ≈ 并发需求 / 单副本在目标 SLO 下的安全并发
```

安全并发必须来自压测曲线，不能直接采用引擎理论上限。扩容还要计入节点创建、镜像拉取、模型下载和权重加载时间；大型模型的冷启动可能远长于流量突增窗口。

## 九、发布和回滚

LLM 发布至少有四种变化：

1. 模型权重或量化版本；
2. 推理引擎与 CUDA/驱动组合；
3. Prompt、工具定义或安全策略；
4. 路由、批处理和并行参数。

推荐流程：

- 用镜像 Digest 和不可变模型 URI 固定制品；
- 离线评估通过后再部署 Shadow 实例；
- 使用固定流量或租户白名单做 Canary；
- 同时比较质量、TTFT、TPOT、吞吐、错误率和成本；
- 回滚必须同时恢复模型、引擎参数、Prompt 和路由配置；
- 不要让 HPA 在 Canary 期间改变样本比例而影响结论。

## 十、安全与多租户

- 在网关做认证、租户配额、Token Rate Limit 和最大上下文限制。
- 不信任用户输入时，对 Tool Calling 和外部连接设置独立权限边界。
- 模型下载凭据使用短期身份或 Secret，不写入镜像。
- 按租户记录 Token、延迟、模型版本和费用，但避免把敏感 Prompt 放进普通日志。
- LoRA/Adapter 的上传、加载和路由需要审批与大小限制。
- 公网接口设置超时、最大 Body、并发和流式连接上限。
- NetworkPolicy 应限制模型 Pod 仅访问必要对象存储、缓存和观测服务。

## 十一、生产检查清单

- [ ] 用真实输入/输出 Token 分布完成基准测试。
- [ ] 定义 TTFT、TPOT、P99、可用性和拒绝率 SLO。
- [ ] 模型 URI、镜像 Digest、量化和引擎参数全部可追溯。
- [ ] 模型冷启动、节点扩容和缓存预热时间已测量。
- [ ] 多机副本按整体调度、扩缩和升级。
- [ ] 路由器能避开未加载、过载或不健康的实例。
- [ ] Autoscaler 使用队列、Token 或延迟信号，而非只看 CPU。
- [ ] Canary 同时评估模型质量和基础设施性能。
- [ ] 已验证流式连接中断、Pod 驱逐和节点故障。
- [ ] 每租户的 Token、并发、模型权限和成本可审计。
