---
title: AI Gateway、推理路由与流量治理
description: 区分 API Gateway、Gateway API Inference Extension 和模型请求调度，设计认证、配额、缓存感知和发布策略
status: evolving
last_reviewed: 2026-08-02
---

# AI Gateway、推理路由与流量治理

传统负载均衡只需要选择一个健康后端。LLM 请求还要考虑模型、Adapter、上下文、队列、KV Cache、优先级、Token 预算和流式连接，因此网关逐渐从“转发 HTTP”发展为策略执行和请求调度层。

## 一、三个容易混淆的角色

| 角色 | 主要职责 | 典型能力 |
| --- | --- | --- |
| API/AI Gateway | 南北向 API 治理 | 认证、配额、Rate Limit、协议、审计、内容策略 |
| Inference Gateway/Router | 后端实例选择 | 模型、队列、KV、Adapter、SLO 感知路由 |
| Serving Control Plane | 管理模型工作负载 | Deployment、KServe、LWS、扩缩容、发布 |

同一产品可能覆盖多个角色，但设计文档仍要标出每项策略的唯一权威写入者。

## 二、请求路径

```text
Client
  → Edge/WAF/External Load Balancer
  → Gateway API Gateway / AI Gateway
      ├── 身份、租户、模型权限
      ├── Token/并发/上下文预算
      ├── API 协议与审计
      └── HTTPRoute → InferencePool
                         │
                         ▼
                  Endpoint Picker / Router
                      ├── 模型/LoRA 已加载
                      ├── 队列和预估延迟
                      ├── Prefix/KV 命中
                      └── Endpoint 健康
                         │
                         ▼
                   vLLM/SGLang/TRT-LLM
```

请求进入集群前后的每一跳都要保留 Trace Context，但不能默认记录完整 Prompt 和 Tool 参数。

## 三、Gateway API Inference Extension

Inference Extension 在 Gateway API 基础上增加面向推理的资源和 Endpoint Selection Extension。

核心抽象包括：

- `InferencePool`：一组可以服务模型请求的 Endpoint；
- `InferenceModel`：用户看到的逻辑模型到 Pool/后端的映射；
- Endpoint Picker/EPP：根据请求和实时后端状态筛选、打分。

概念路径：

```text
HTTPRoute backendRef
  → InferencePool
  → Endpoint Picker
  → 选择具体 Pod IP
  → Gateway 转发请求
```

这让网关保持数据面职责，同时把模型感知选择交给可扩展控制逻辑。

参考：[Gateway API Inference Extension](https://gateway-api-inference-extension.sigs.k8s.io/)、[Kubernetes 项目介绍](https://kubernetes.io/blog/2025/06/05/introducing-gateway-api-inference-extension/)

## 四、AI Gateway 与 Inference Gateway

AI Gateway 更关注平台级策略：

- OpenAI/Anthropic/自托管协议代理；
- 多模型、多提供商和故障切换；
- 身份、租户和模型授权；
- Token、请求、并发和费用限制；
- Prompt/Response 安全和脱敏；
- 缓存、重试、超时和熔断；
- 统一日志、Trace 和计费；
- 外部 API 与集群内部模型统一入口。

Inference Gateway 更专注某个推理池的后端选择。2026 年 Kubernetes 社区成立 AI Gateway Working Group，说明 API 治理和推理基础设施正在形成独立标准化方向。

参考：[Kubernetes AI Gateway Working Group](https://kubernetes.io/blog/2026/03/09/announcing-ai-gateway-wg/)

## 五、路由信号

| 信号 | 用途 | 风险 |
| --- | --- | --- |
| Ready/Health | 排除不可用 Endpoint | 探针可能滞后 |
| Waiting/Running Requests | 避开排队热点 | 指标采样延迟 |
| KV Cache 使用率 | 评估剩余容量 | 引擎指标不统一 |
| Prefix Cache 命中 | 减少 Prefill | 可能制造副本倾斜 |
| Model/LoRA 已加载 | 避免加载开销 | 状态变化和并发加载 |
| 请求长度 | 估算 Prefill/内存 | Tokenize 需要成本 |
| 租户/优先级 | SLO 与公平 | 低优先级可能饥饿 |
| GPU/Worker 状态 | 避开异常实例 | 过度依赖低层瞬时指标 |

Router 应在状态缺失时有安全回退，而不是因 Prometheus 或 Cache Indexer 不可用而停止全部请求。

## 六、负载均衡策略

### Round Robin

简单可靠，适合无状态、负载均匀或初期部署。它是必须保留的故障回退基线。

### Least Queue / Least Request

适合副本状态差异明显的情况，但需要低延迟、可比较的实时指标。

### Prefix/KV-aware

优先发送到已有相关 Cache 的副本，减少重复 Prefill。应加入队列惩罚，避免热点。

### Session/Conversation Affinity

多轮对话尽量保持到同一 Cache 域。需要处理副本退出、扩容和会话重映射。

### Cost/Hardware-aware

在不同加速器、量化或云区域之间按 SLO 和成本选择。必须确保模型质量、能力和数据地域可互换。

## 七、Flow Control

保护 GPU 的顺序通常是：

```text
认证
  → 模型授权
  → 输入大小和上下文上限
  → 租户 Token/请求预算
  → 并发限制
  → 队列上限和优先级
  → 超时/取消
  → 后端选择
```

只按 Requests/s 限流不足以防止成本型 DoS。一个超长上下文请求可能比数百个短请求昂贵。

应分别限制：

- Prompt Token；
- 最大输出 Token；
- 活跃流式连接；
- 每租户并发；
- 每模型队列；
- Tool Call 次数和外部副作用；
- 多模态 Body 大小；
- 每分钟/每天 Token 与费用。

## 八、优先级和公平性

至少区分：

- 生产交互；
- 后台批任务；
- 评估和 Canary；
- 内部开发；
- 系统健康探测。

高优先级不应无限绕过容量保护。定义最大队列、最低保障、借用和降级策略，避免低优先级永久饥饿。

请求优先级与 Kubernetes Pod Priority 不同：前者选择推理队列，后者影响 Pod 调度和抢占。不要让每个高优先级请求触发高优先级 GPU Pod 扩容。

## 九、超时、重试与取消

LLM 的重试可能非常昂贵：

- 请求已经完成大量 Prefill/Decode；
- 流式响应已向客户端输出部分 Token；
- 重试会重复 Tool Side Effect；
- 网关重试与客户端重试叠加；
- P/D 链路可能产生孤儿 KV。

原则：

- 只在明确幂等、尚未输出时自动重试；
- 为连接、首 Token、总请求分别设超时；
- 客户端取消应传播到 Router 和 Engine；
- Tool Call 使用 Idempotency Key；
- 记录重试原因和浪费 Token；
- 后端故障切换先验证模型版本和能力一致。

## 十、流式协议

SSE、HTTP/2 或 gRPC 长连接会影响：

- Gateway Idle/Request Timeout；
- Load Balancer 连接跟踪；
- 滚动发布 Drain；
- 客户端断开检测；
- Buffering 与首 Token；
- WAF/代理的响应检查能力；
- 并发连接资源。

端到端验证真实外部入口，不能只用 `kubectl port-forward` 测量生产延迟。

## 十一、模型命名和路由

客户端模型名不应直接等于部署对象名。维护逻辑模型目录：

```text
chat-standard
  → model artifact v42
  → runtime vllm-cuda-stable
  → InferencePool chat-standard-h100

chat-canary
  → model artifact v43
  → runtime vllm-cuda-canary
  → InferencePool chat-canary-h100
```

逻辑名可以保持稳定，Artifact、Runtime 和 Pool 独立版本化。

## 十二、Canary 与 Shadow

### Canary

将一部分真实请求发送到新版本并把结果返回客户端。需要同时比较：

- 模型质量；
- TTFT、TPOT、错误和拒绝；
- Token、GPU 和成本；
- 安全策略；
- Tool Side Effect。

### Shadow

复制请求到新版本但不返回结果。适合性能和质量比较，但会增加 GPU 成本，并可能重复外部 Tool/写操作。Shadow 前必须移除副作用或使用模拟工具。

Canary 路由按租户或请求 ID 做稳定哈希，避免同一会话在版本间跳动。

## 十三、认证与授权

网关需要将：

- 外部用户/应用身份；
- 组织、项目和租户；
- 允许模型；
- Token/费用预算；
- 请求优先级；
- 数据地域和合规策略；

转换为内部可信上下文。后端模型服务只信任来自网关的身份时，必须通过 mTLS、NetworkPolicy 或工作负载身份阻止绕过。

## 十四、观测与隐私

建议 Trace Span：

```text
gateway.receive
  → authz
  → tokenization/admission
  → endpoint.pick
  → backend.queue
  → prefill
  → decode
  → tool/retrieval（如有）
```

记录模型、版本、租户、输入/输出 Token、TTFT、TPOT、队列和选择原因。Prompt、响应、Tool 参数和检索文档默认不写入普通日志；需要采样时采用显式授权、脱敏、加密和保留期限。

OpenTelemetry 的 GenAI 语义约定仍在演进，属性版本和敏感字段策略应固定并记录。[OpenTelemetry Semantic Conventions](https://opentelemetry.io/docs/specs/semconv/)

## 十五、高可用

- Gateway 多副本跨节点/故障域；
- Endpoint Picker/EPP 不保存唯一状态，或状态可重建；
- 指标/Cache Indexer 不可用时回退到健康 Round Robin；
- 配额存储和身份服务有明确故障策略；
- Gateway 更新不切断全部流式连接；
- InferencePool 状态与 Pod Ready 变化及时传播；
- 控制面故障不影响已有数据面连接。

## 十六、生产检查清单

- [ ] API 治理、Endpoint 选择和 Workload 控制职责分开。
- [ ] InferencePool 的 Ready 语义代表模型可服务。
- [ ] Router 同时考虑负载和 Cache，不制造热点。
- [ ] 每租户限制 Token、上下文、并发和费用。
- [ ] 超时、取消和重试不会重复昂贵计算或 Tool 副作用。
- [ ] 外部真实入口已验证流式连接和 TTFT。
- [ ] Canary 同时评估模型质量、性能和成本。
- [ ] 后端不能绕过网关直接被公网或其他租户访问。
- [ ] Prompt/Tool/检索内容默认不进入日志。
- [ ] 状态和指标服务故障时有安全降级路径。

## 延伸阅读

- [Gateway API](https://gateway-api.sigs.k8s.io/)
- [Gateway API Inference Extension](https://gateway-api-inference-extension.sigs.k8s.io/)
- [Kubernetes AI Gateway Working Group](https://kubernetes.io/blog/2026/03/09/announcing-ai-gateway-wg/)
- [Envoy AI Gateway](https://aigateway.envoyproxy.io/)
- [llm-d Routing](https://llm-d.ai/docs/architecture/core/router)
- [KServe LLMInferenceService](https://kserve.github.io/website/docs/concepts/architecture/control-plane-llmisvc)
