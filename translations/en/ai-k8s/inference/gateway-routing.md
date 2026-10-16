---
title: "AI Gateway, Inference Routing, and Traffic Governance"
description: "Distinguish API Gateway, Gateway API Inference Extension, and model request scheduling; design authentication, quotas, cache awareness, and release strategies"
status: evolving
last_reviewed: 2026-08-02
---

# AI Gateway, Inference Routing, and Traffic Governance

Traditional load balancing only needs to select a healthy backend. LLM requests also need to consider models, Adapters, context, queues, KV Cache, priority, token budgets, and streaming connections, so the gateway has gradually evolved from "forwarding HTTP" to a policy enforcement and request scheduling layer.

## 1. Three Easily Confused Roles

| Role | Primary Responsibility | Typical Capabilities |
| --- | --- | --- |
| API/AI Gateway | North-south API governance | Authentication, quotas, Rate Limit, protocols, auditing, content policy |
| Inference Gateway/Router | Backend instance selection | Model, queue, KV, Adapter, SLO-aware routing |
| Serving Control Plane | Managing model workloads | Deployment, KServe, LWS, scaling, releases |

The same product may cover multiple roles, but the design document should still identify the single authoritative writer for each policy.

## 2. Request Path

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

Every hop before and after the request enters the cluster must preserve the Trace Context, but full Prompt and Tool parameters should not be logged by default.

## 3. Gateway API Inference Extension

The Inference Extension adds inference-oriented resources and an Endpoint Selection Extension on top of the Gateway API.

Core abstractions include:

- `InferencePool`: a set of Endpoints that can serve model requests;
- `InferenceModel`: the mapping from the logical model users see to Pool/backends;
- Endpoint Picker/EPP: filters and scores based on the request and real-time backend state.

Conceptual path:

```text
HTTPRoute backendRef
  → InferencePool
  → Endpoint Picker
  → 选择具体 Pod IP
  → Gateway 转发请求
```

This keeps the gateway responsible for the data plane while delegating model-aware selection to extensible control logic.

References: [Gateway API Inference Extension](https://gateway-api-inference-extension.sigs.k8s.io/), [Kubernetes Project Introduction](https://kubernetes.io/blog/2025/06/05/introducing-gateway-api-inference-extension/)

## 4. AI Gateway vs. Inference Gateway

AI Gateway focuses more on platform-level policy:

- OpenAI/Anthropic/self-hosted protocol proxying;
- Multi-model, multi-provider, and failover;
- Identity, tenant, and model authorization;
- Token, request, concurrency, and cost limits;
- Prompt/Response security and redaction;
- Caching, retries, timeouts, and circuit breaking;
- Unified logging, tracing, and billing;
- Unified entry point for external APIs and in-cluster models.

Inference Gateway focuses more on backend selection for a specific inference pool. In 2026, the Kubernetes community established the AI Gateway Working Group, indicating that API governance and inference infrastructure are forming independent standardization directions.

Reference: [Kubernetes AI Gateway Working Group](https://kubernetes.io/blog/2026/03/09/announcing-ai-gateway-wg/)

## 5. Routing Signals

| Signal | Purpose | Risk |
| --- | --- | --- |
| Ready/Health | Exclude unavailable Endpoints | Probes may lag |
| Waiting/Running Requests | Avoid queuing hotspots | Metric sampling latency |
| KV Cache utilization | Assess remaining capacity | Engine metrics are not uniform |
| Prefix Cache hits | Reduce Prefill | May create replica skew |
| Model/LoRA loaded | Avoid loading overhead | State changes and concurrent loading |
| Request length | Estimate Prefill/memory | Tokenization has a cost |
| Tenant/priority | SLO and fairness | Low priority may starve |
| GPU/Worker status | Avoid unhealthy instances | Over-reliance on low-level transient metrics |

The Router should have a safe fallback when state is missing, rather than stopping all requests because Prometheus or the Cache Indexer is unavailable.

## 6. Load Balancing Strategies

### Round Robin

Simple and reliable, suitable for stateless, evenly loaded, or initial deployments. It is the baseline fallback that must be preserved.

### Least Queue / Least Request

Suitable for cases where replica states differ significantly, but requires low-latency, comparable real-time metrics.

### Prefix/KV-aware

Prefer sending to replicas that already have relevant Cache, reducing duplicate Prefill. Queue penalties should be added to avoid hotspots.

### Session/Conversation Affinity

Keep multi-turn conversations on the same Cache domain as much as possible. Replica exit, scaling, and session remapping need to be handled.

### Cost/Hardware-aware

Select across different accelerators, quantization levels, or cloud regions based on SLO and cost. Must ensure model quality, capability, and data residency are interchangeable.

## 7. Flow Control

The typical order for protecting GPU is:

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

Rate limiting by Requests/s alone is insufficient to prevent cost-type DoS. A single extremely long-context request can be more expensive than hundreds of short requests.

The following should be limited separately:

- Prompt Token;
- Maximum output Token;
- Active streaming connections;
- Per-tenant concurrency;
- Per-model queue;
- Tool Call count and external side effects;
- Multimodal Body size;
- Per-minute/per-day Token and cost.

## 8. Priority and Fairness

At minimum, distinguish:

- Production interactive;
- Background batch jobs;
- Evaluation and Canary;
- Internal development;
- System health probes.

High priority should not bypass capacity protection without limit. Define maximum queues, minimum guarantees, borrowing, and degradation policies to avoid permanent starvation of low-priority workloads.

Request priority differs from Kubernetes Pod Priority: the former selects the inference queue, while the latter affects Pod scheduling and preemption. Do not let every high-priority request trigger high-priority GPU Pod scaling.

## 9. Timeouts, Retries, and Cancellation

Retries for LLMs can be very expensive:

- The request has already completed a large amount of Prefill/Decode;
- The streaming response has already output partial Tokens to the client;
- Retries will repeat Tool Side Effects;
- Gateway retries stack with client retries;
- The P/D chain may produce orphaned KV.

Principles:

- Only auto-retry when the operation is explicitly idempotent and nothing has been output yet;
- Set separate timeouts for connection, first Token, and total request;
- Client cancellation should propagate to the Router and Engine;
- Tool Calls use Idempotency Keys;
- Record retry reasons and wasted Tokens;
- Backend failover must first verify model version and capability consistency.

## 10. Streaming Protocols

SSE, HTTP/2, or gRPC long connections affect:

- Gateway Idle/Request Timeout;
- Load Balancer connection tracking;
- Rolling release Drain;
- Client disconnect detection;
- Buffering and first Token;
- WAF/proxy response inspection capabilities;
- Concurrent connection resources.

End-to-end validation through the real external entry point is required; production latency cannot be measured using only `kubectl port-forward`.

## 11. Model Naming and Routing

Client model names should not directly equal deployment object names. Maintain a logical model catalog:

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

Logical names can remain stable while Artifact, Runtime, and Pool are versioned independently.

## 12. Canary and Shadow

### Canary

Send a portion of real requests to the new version and return results to the client. The following must be compared simultaneously:

- Model quality;
- TTFT, TPOT, errors, and rejections;
- Token, GPU, and cost;
- Security policies;
- Tool Side Effects.

### Shadow

Duplicate requests to the new version without returning results. Suitable for performance and quality comparison, but increases GPU cost and may duplicate external Tool/write operations. Side effects must be removed or mock tools used before Shadow.

Canary routing uses stable hashing by tenant or request ID to avoid the same session bouncing between versions.

## 13. Authentication and Authorization

The gateway needs to convert:

- External user/application identity;
- Organization, project, and tenant;
- Allowed models;
- Token/cost budgets;
- Request priority;
- Data residency and compliance policies;

into an internal trusted context. When backend model services only trust identity coming from the gateway, bypassing must be prevented via mTLS, NetworkPolicy, or workload identity.

## 14. Observability and Privacy

Recommended Trace Spans:

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

Record model, version, tenant, input/output Tokens, TTFT, TPOT, queue, and selection reason. Prompt, response, Tool parameters, and retrieved documents are not written to normal logs by default; when sampling is needed, use explicit authorization, redaction, encryption, and retention periods.

OpenTelemetry's GenAI semantic conventions are still evolving; attribute version and sensitive field policies should be fixed and documented. [OpenTelemetry Semantic Conventions](https://opentelemetry.io/docs/specs/semconv/)

## 15. High Availability

- Gateway replicas distributed across nodes/failure domains;
- Endpoint Picker/EPP holds no unique state, or state is reconstructable;
- Fall back to healthy Round Robin when metrics/Cache Indexer is unavailable;
- Quota storage and identity services have explicit failure policies;
- Gateway updates do not cut off all streaming connections;
- InferencePool status and Pod Ready changes propagate promptly;
- Control plane failures do not affect existing data plane connections.

## 16. Production Checklist

- [ ] API governance, Endpoint selection, and Workload control responsibilities are separated.
- [ ] InferencePool Ready semantics represent that the model is serviceable.
- [ ] Router considers both load and Cache without creating hotspots.
- [ ] Per-tenant limits on Token, context, concurrency, and cost.
- [ ] Timeouts, cancellation, and retries do not repeat expensive computation or Tool side effects.
- [ ] Real external entry point has been validated for streaming connections and TTFT.
- [ ] Canary evaluates model quality, performance, and cost simultaneously.
- [ ] Backends cannot be accessed directly by the public internet or other tenants, bypassing the gateway.
- [ ] Prompt/Tool/retrieved content does not enter logs by default.
- [ ] Safe degradation paths exist when state and metric services fail.

## Further Reading

- [Higress AI Gateway: Architecture, Installation, and AIBrix Integration Practice](higress-ai-gateway.md)
- [Gateway API](https://gateway-api.sigs.k8s.io/)
- [Gateway API Inference Extension](https://gateway-api-inference-extension.sigs.k8s.io/)
- [Kubernetes AI Gateway Working Group](https://kubernetes.io/blog/2026/03/09/announcing-ai-gateway-wg/)
- [Envoy AI Gateway](https://aigateway.envoyproxy.io/)
- [llm-d Routing](https://llm-d.ai/docs/architecture/core/router)
- [KServe LLMInferenceService](https://kserve.github.io/website/docs/concepts/architecture/control-plane-llmisvc)
