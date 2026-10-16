---
title: "LLM Inference Platform"
description: "Control plane, runtime, routing, scaling, and capacity design for online large model services"
status: evolving
last_reviewed: 2026-08-04
---

# LLM Inference Platform

Traditional model serving is mostly "one request corresponds to one short computation," whereas LLM inference is characterized by long-lived connections, streaming output, dynamic batching, massive GPU memory, and KV Cache. Platform design has therefore evolved from ordinary Service load balancing to model-aware, cache-aware, and request-aware scheduling.

For a comparison of the layers and composition approaches of vLLM, KServe, AIBrix, Ray Serve, BentoML, and NVIDIA NIM, see [LLM Serving and AI Microservice Frameworks](inference/serving-frameworks.md); if you plan to use Ray Data, Train, Tune, and Serve together, see [The Role of Ray in Large Model Training and Inference](ray-llm-platform.md).

## 1. First Distinguish the Four Layers

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

- **Inference engine** executes model computation and determines batching, quantization, parallelism, and cache efficiency.
- **Service control plane** manages Deployments, model loading, health checks, scaling, and versions.
- **Inference gateway** understands models, requests, and backend state, and selects the appropriate instance.
- **Kubernetes** provides the resource, lifecycle, networking, and failure recovery foundation.

Conflating these layers into a single "Serving tool" leads to incorrect selection decisions. For example, KServe and vLLM are usually a composition relationship, not an either/or choice.

## 2. How to Choose an Inference Engine

| Engine | Key Characteristics | Common Scenarios |
| --- | --- | --- |
| vLLM | Continuous batching, PagedAttention, OpenAI API, broad model and hardware support | General-purpose LLM online and batch inference; most active cloud-native ecosystem integration |
| SGLang | Radix/Prefix Cache, structured generation, complex Agent/multimodal workloads | Many repeated prefixes, structured output, and inference programs |
| NVIDIA Triton | Multi-framework, dynamic batching, model repository, unified metrics | Traditional ML/DL, multiple models, unified serving across multiple backends |
| TensorRT-LLM | Deep optimization on NVIDIA platforms, compilation and kernel optimization | Pursuing extreme performance on NVIDIA GPUs while accepting build complexity |
| llama.cpp / Ollama | Lightweight, CPU/edge/development experience | Local development, small models, and edge; not the first choice for large-scale clusters |

Benchmarks must fix the model, precision, context length, input/output token distribution, concurrency, hardware, and SLO. Comparing only "tokens per second" without looking at TTFT and tail latency usually yields conclusions with no production value.

## 3. Two Main Entry Points for KServe

### InferenceService

The standard `InferenceService` is suitable for traditional prediction models and most ordinary LLM deployments. It provides:

- Model artifact loading and pluggable ServingRuntime;
- Deployment/Service, health check, and network management;
- Canary, A/B, and inference graphs;
- Deployment modes such as Standard and Knative/Serverless;
- Backends such as vLLM, Triton, and custom containers.

### LLMInferenceService

When the platform needs Prefix-aware Routing, KV Cache Offloading, Prefill/Decode separation, or finer-grained multi-node GPU management, you can evaluate `LLMInferenceService`. As of 2026, its API is still evolving rapidly; production platforms should pin a version and retain migration tests.

KServe officially recommends starting with the standard InferenceService and switching to LLMInferenceService only when advanced LLM requirements actually arise.

References: [KServe Administrator Guide](https://kserve.github.io/website/docs/admin-guide/overview), [LLMInferenceService Architecture](https://kserve.github.io/website/docs/concepts/architecture/control-plane-llmisvc)

## 4. Multi-Node Models Require LeaderWorkerSet

When a single model replica is sharded across multiple machines, a "replica" is no longer a single Pod. LeaderWorkerSet (LWS) replicates and manages one Leader and several Workers as a unit, providing stable identity, parallel creation, and a unified lifecycle.

Patterns suitable for LWS:

- One model replica uses multi-node Tensor Parallel / Pipeline Parallel;
- The Leader receives requests while Workers only participate in Collectives;
- Scaling and rolling upgrades must be performed at the granularity of the entire Pod Group;
- One service runs multiple mutually independent distributed model replicas.

LWS solves workload orchestration but does not automatically solve queue admission and GPU quotas. In production, Kueue is typically also needed for group-level admission and topology awareness.

Reference: [LeaderWorkerSet](https://lws.sigs.k8s.io/)

## 5. Why Plain Round-Robin Is Not Enough

Even if two vLLM Pods have identical replica specifications, their actual state may differ:

- One instance already has a Prefix Cache for the same System Prompt;
- One instance has a full queue while another is idle;
- One instance is loading a LoRA Adapter;
- One instance has less available GPU memory or is in a recovery state;
- Requests differ in model, version, context length, and priority.

Plain Service round-robin cannot see this information. The Gateway API Inference Extension introduces `InferencePool` and Endpoint Picker, allowing the router to filter and score backends based on metrics and capabilities exposed by the model service.

Usable routing signals include:

- Whether the requested model and Adapter are already loaded;
- KV/Prefix Cache hit likelihood;
- Running Request, Waiting Queue, and estimated latency;
- GPU KV Cache utilization and the maximum acceptable context;
- Tenant priority, token budget, and rate-limiting policies.

Reference: [Gateway API Inference Extension](https://gateway-api-inference-extension.sigs.k8s.io/)

## 6. KV Cache Is a Distributed Resource

KV Cache directly affects GPU memory usage, throughput, and latency. The platform must be explicit about four types of cache:

| Cache | Content | Value | Risk |
| --- | --- | --- | --- |
| Model weight cache | Model files, Tokenizer, Adapters | Shortens Pod cold start | Local disk space, consistency, and eviction |
| Prefix Cache | KV of repeated Prompts | Reduces TTFT and redundant computation | Routing must maintain cache affinity |
| Runtime KV Cache | Context of active requests | Supports the generation process | Consumes large amounts of GPU memory |
| Offloaded/Distributed KV | CPU, NVMe, or remote cache | Expands context or enables cross-instance reuse | Network overhead and consistency complexity |

"Send the request to the most idle instance" is not always optimal; if another slightly busier instance already has a high-value Prefix Cache, the total cost may actually be lower. Modern inference routing is therefore multi-objective optimization, not simple Least Connections.

## 7. Prefill / Decode Separation

LLM requests can be roughly divided into:

- **Prefill**: processes all input tokens; compute-intensive with high parallelism;
- **Decode**: generates tokens one by one; constrained by GPU memory bandwidth and synchronization latency, with greater focus on tail latency.

In large-scale scenarios, different GPU Pools can handle Prefill and Decode separately, with KV Cache transferred between them. The benefit is that the two workload types can be scaled and tuned independently; the costs are:

- Increased KV transfer and network requirements;
- More complex failure paths and observability;
- May not be worthwhile for small-scale or short-prompt scenarios;
- Capacity planning must balance both Pools simultaneously.

llm-d combines vLLM, Inference Gateway, KV Cache-aware routing, rate limiting, and disaggregated inference into a reusable solution. It is suitable for optimizing performance/cost once a certain scale is reached and should not be a prerequisite for the first LLM Pod.

Reference: [llm-d](https://llm-d.ai/)

## 8. What to Look at for Scaling

CPU utilization is usually not an effective scaling signal for LLM services. More valuable metrics include:

- Waiting Request / Queue Depth;
- Running Request versus maximum concurrency;
- Prompt/Generation Token Rate;
- KV Cache utilization;
- TTFT, TPOT, and P95/P99;
- Request rejection, timeouts, and Preemption;
- Model loading state per replica.

### Common Latency Metrics

| Metric | Meaning |
| --- | --- |
| TTFT | Time To First Token, the time the user waits for the first token |
| TPOT | Time Per Output Token, the average time per token after the first token |
| ITL | Inter-Token Latency, the delay between adjacent tokens |
| E2E | Total latency from request entry to completion |

A simplified capacity relationship:

```text
并发需求 ≈ 到达率 × 平均请求持续时间
所需副本 ≈ 并发需求 / 单副本在目标 SLO 下的安全并发
```

Safe concurrency must come from load-test curves; the engine's theoretical upper limit cannot be adopted directly. Scaling must also account for node creation, image pull, model download, and weight loading time; cold start for large models can be far longer than the traffic spike window.

## 9. Release and Rollback

LLM releases involve at least four types of changes:

1. Model weights or quantization versions;
2. Inference engine and CUDA/driver combinations;
3. Prompts, tool definitions, or safety policies;
4. Routing, batching, and parallelism parameters.

Recommended process:

- Pin artifacts using image Digests and immutable model URIs;
- Deploy Shadow instances only after offline evaluation passes;
- Use fixed traffic or tenant allowlists for Canary;
- Compare quality, TTFT, TPOT, throughput, error rate, and cost simultaneously;
- Rollback must restore the model, engine parameters, Prompts, and routing configuration together;
- Do not let HPA change the sample ratio during Canary and skew the conclusions.

## 10. Security and Multi-Tenancy

- Perform authentication, tenant quotas, Token Rate Limits, and maximum context limits at the gateway.
- When user input is not trusted, set up independent permission boundaries for Tool Calling and external connections.
- Use short-lived identities or Secrets for model download credentials; do not bake them into images.
- Record tokens, latency, model versions, and cost per tenant, but avoid putting sensitive Prompts into ordinary logs.
- LoRA/Adapter upload, loading, and routing require approval and size limits.
- Public-facing interfaces should set timeouts, maximum Body, concurrency, and streaming connection limits.
- NetworkPolicy should restrict model Pods to accessing only the necessary object storage, cache, and observability services.

## 11. Production Checklist

- [ ] Complete benchmark testing with real input/output token distributions.
- [ ] Define SLOs for TTFT, TPOT, P99, availability, and rejection rate.
- [ ] Model URIs, image Digests, quantization, and engine parameters are all traceable.
- [ ] Model cold start, node scaling, and cache warm-up times have been measured.
- [ ] Multi-node replicas are scheduled, scaled, and upgraded as a whole.
- [ ] The router can avoid instances that are unloaded, overloaded, or unhealthy.
- [ ] The Autoscaler uses queue, token, or latency signals rather than CPU alone.
- [ ] Canary evaluates both model quality and infrastructure performance.
- [ ] Streaming connection interruption, Pod eviction, and node failure have been verified.
- [ ] Per-tenant tokens, concurrency, model permissions, and cost are auditable.
