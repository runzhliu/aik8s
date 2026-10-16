---
title: "LLM Serving and AI Microservice Frameworks"
description: "Comparing the layers, composition patterns, and selection boundaries of vLLM, KServe, AIBrix, Ray Serve, BentoML, NVIDIA NIM, and application orchestration frameworks"
status: evolving
last_reviewed: 2026-08-04
---

# LLM Serving and AI Microservice Frameworks

"LLM microservice framework" is not a single category. vLLM handles model compute, KServe/AIBrix manage model serving, Ray Serve/BentoML organize Python inference applications, and Dify/LangGraph orchestrate RAG, Agent, and business workflows. Before selecting a framework, you must first determine which layer is missing.

## 1. First Distinguish the Six Layers

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

A single platform usually combines multiple layers. For example, `AIBrix + vLLM`, `KServe + vLLM`, and `RayService + Ray Serve LLM + vLLM` are all reasonable combinations, not mutually exclusive products.

## 2. Positioning of Mainstream Solutions

| Solution | Core Positioning | Suitable For | Main Trade-offs |
| --- | --- | --- | --- |
| Deployment + vLLM | Minimal model serving | Single model, establishing a performance baseline first | Release, intelligent routing, caching, and advanced elasticity must be built yourself |
| KServe | Kubernetes-native model serving control plane | Standardized model API, Canary, Runtime, platform self-service | CRD/gateway/storage integration and version matrix |
| AIBrix | Kubernetes inference control plane for LLMs | LLM Gateway, routing, Autoscaling, LoRA, KV, and distributed inference | Project evolves quickly, many components, target version must be validated |
| Ray Serve / Serve LLM | Python composable serving and distributed LLM Serving | Multi-stage inference graphs, multi-node/multi-model, existing Ray ecosystem | Introduces Ray cluster, Actor, and two-tier scheduling operations |
| BentoML | Python-first model and AI application packaging/serving | Quickly packaging custom models, RAG, vLLM into services | Cluster-level quotas, Gang, and device topology still need platform supplementation |
| NVIDIA NIM | NVIDIA-validated model inference microservices with enterprise lifecycle | Reducing runtime validation effort, needing enterprise support | NVIDIA/NGC/licensing and support matrix constraints |
| Dify/LangGraph, etc. | AI application and Agent Workflow | Prompts, tools, knowledge bases, and business processes | Not a GPU Serving control plane, nor a replacement for inference engines |

## 3. vLLM Is an Engine, Not a Complete Platform

vLLM is responsible for:

- Loading models and executing token computation;
- Continuous Batching and Paged KV Cache;
- Prefix Cache, quantization, LoRA, and multiple parallelism modes;
- OpenAI-Compatible API;
- Exposing engine and request metrics.

It typically does not independently handle:

- Cross-team quotas, authentication, and token budgets;
- Kubernetes release, Canary, and cluster-level scaling;
- Global routing and failure domains across multiple models;
- Model artifact approval and data governance;
- The complete call graph of RAG/Agent.

The minimal production starting point can be `Deployment + Service + Gateway + vLLM`. Only add KServe, AIBrix, or Ray Serve when explicit requirements emerge, avoiding stacking multiple control planes from the start.

Reference: [vLLM Documentation](https://docs.vllm.ai/)

## 4. KServe: Standardized Model Serving

KServe is suitable for platform teams providing a unified model deployment interface to users:

- `InferenceService` manages general models and ordinary LLM serving;
- `ServingRuntime` fixes container, protocol, and model loading contracts;
- `LLMInferenceService` targets Prefix-aware Routing, P/D separation, and advanced LLM capabilities;
- Modelcar, LocalModelCache, and similar capabilities connect model artifacts with node caching;
- Composes with Kubernetes components such as Gateway, Autoscaler, LWS, and Kueue.

The key reason to choose KServe is not "writing one fewer Deployment," but enabling different teams to use the same release, status, routing, model loading, and policy entry points.

Reference: [KServe](https://kserve.github.io/website/docs/), [LLMInferenceService](https://kserve.github.io/website/docs/concepts/architecture/control-plane-llmisvc)

## 5. AIBrix: A Control Plane for LLMs

AIBrix targets large-scale LLM inference on Kubernetes, with core capabilities including:

- LLM Gateway and model routing based on Envoy Gateway;
- Autoscaler designed around real-time inference load;
- LoRA Model Adapter lifecycle and high-density reuse;
- Distributed KV Cache orchestration;
- Multi-node and Prefill/Decode disaggregated inference;
- Integration with vLLM metrics and OpenAI-Compatible API.

Conceptual structure:

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

Suitable for evaluation when:

- You already have multi-model, multi-replica, and dynamic LoRA loading requirements;
- Ordinary Service/Ingress cannot leverage queue, model, and cache state;
- You need LLM-specific elasticity rather than CPU/HPA-only scaling;
- You plan to unify the entry point and operational capabilities of vLLM services.

Not suitable for direct adoption when:

- You have only one or a few vLLM Pods;
- You have not yet established TTFT, TPOT, Queue, KV, and Token baselines;
- The team cannot maintain the Gateway, Controller, CRD, and engine version matrix;
- You only need standard release, and KServe/Deployment already satisfies the requirement.

There is overlap between AIBrix, KServe, and the Gateway API Inference Extension capabilities. A production platform should designate who owns model CRDs, Endpoint discovery, routing, and scaling decisions, to avoid multiple controllers writing to the same object simultaneously.

Reference: [AIBrix](https://aibrix.readthedocs.io/latest/), [AIBrix Gateway Routing](https://aibrix.readthedocs.io/latest/features/gateway-plugins.html), [AIBrix Autoscaler](https://aibrix.readthedocs.io/latest/designs/aibrix-autoscaler.html)

## 6. Ray Serve: Composable Python Microservices

Ray Serve uses Deployment, Replica, and Handle to organize directed call graphs, where each step can declare independent CPU/GPU, concurrency, Batch, and Autoscaling. It is suitable for:

- Preprocess → Retriever → Reranker → LLM → Guardrail;
- Multi-model Ensemble, cascading, and degradation;
- Passing Python objects between components;
- Multi-node vLLM/SGLang and complex LLM Serving;
- Training, post-training, and Serving already sharing the Ray ecosystem.

On Kubernetes, use KubeRay `RayService` to manage RayCluster and Serve Application. See [The Role of Ray in Large Model Training and Inference](../ray-llm-platform.md) for detailed design.

Reference: [Ray Serve](https://docs.ray.io/en/latest/serve/), [Ray Serve LLM](https://docs.ray.io/en/latest/serve/llm/)

## 7. BentoML: From Python Models to Services

BentoML provides Python Service, model/dependency packaging, API, Runner/service composition, and deployment tooling, suitable for development teams to quickly turn the following into deliverable services:

- Custom PyTorch/Transformers models;
- vLLM OpenAI-Compatible Endpoints;
- Embedding, Reranker, and Guardrail;
- RAG or Compound AI flows;
- Inference APIs requiring custom pre/post-processing.

It is closer to an application and model service development framework. Kubernetes cluster-level GPU queues, topology, model caching, multi-tenant networking, and cost governance still need to be designed at the platform layer.

Reference: [BentoML](https://docs.bentoml.com/en/latest/)

## 8. NVIDIA NIM: Validated Inference Microservices

NVIDIA NIM wraps models, inference runtimes, configuration, health, and observability interfaces into inference microservices. The NIM Operator manages deployment, model caching, health, and elasticity through resources such as `NIMService` and `NIMCache`.

Suitable for:

- NVIDIA GPU environments requiring vendor validation and enterprise support;
- Reducing the effort of validating model, quantization, Runtime, and hardware combinations;
- Unified deployment of LLM, Embedding, Reranker, speech, or vision models;
- Environments with NGC, licensing, offline deployment, and supply chain processes.

Points to evaluate:

- Supported models, GPUs, Profiles, and licensing;
- The time gap between NIM containers and upstream vLLM/SGLang features;
- NGC credentials, model caching, and air-gapped environments;
- Responsibility overlap between NIM Operator and existing KServe/GitOps/Autoscaler.

Reference: [NVIDIA NIM for LLMs](https://docs.nvidia.com/nim/large-language-models/latest/introduction.html), [NIM Operator](https://docs.nvidia.com/nim-operator/latest/)

## 9. Dify, LangGraph, etc. Belong to the Application Layer

Application orchestration frameworks typically manage:

- Prompts, model Providers, and Workflows;
- RAG, knowledge bases, tools, and Agent state;
- Human approval, business rules, and sessions;
- Application-level Trace, evaluation, and operations.

They typically do not manage:

- GPU device allocation and topology;
- vLLM KV Cache and Batch;
- Multi-node model Rank and NCCL;
- Kubernetes cluster queues and node scaling;
- High-performance distribution of model weights.

It is recommended to call standard OpenAI-Compatible/KServe APIs through an internal AI Gateway, decoupling the application layer from the underlying vLLM/AIBrix/KServe/Ray Serve.

## 10. Composition Patterns

### Pattern A: Minimal Open Source Stack

```text
Gateway/Ingress → Deployment + vLLM → GPU
```

Suitable for single-model or validation phases. Establish performance, release, caching, and failure baselines first.

### Pattern B: Standardized Model Platform

```text
Gateway → KServe InferenceService → vLLM/SGLang
```

Suitable for multi-team self-service release, Canary, and unified Runtime.

### Pattern C: LLM-Specific Control Plane

```text
AIBrix Gateway/Router
  → AIBrix 管理的 Model/Adapter/Autoscaling
  → vLLM Replica / Distributed Pool
```

Suitable when model, LoRA, traffic, and cache scale have already created dedicated scheduling requirements.

### Pattern D: Composable Python AI Services

```text
Enterprise Gateway → RayService
  → Ray Serve Application
      → Retriever / Reranker / vLLM / Guardrail
```

Suitable for multiple Python components scaling independently and multi-node LLM Serving.

### Pattern E: Enterprise Support Stack

```text
Enterprise Gateway → NIMService/KServe → NIM LLM → NVIDIA GPU
```

Suitable for environments that value vendor support, validated configurations, and security maintenance cycles.

## 11. Do Not Duplicate Ownership of Control

Before going live, designate a single Owner for each capability:

| Capability | Possible Owner | Must Avoid |
| --- | --- | --- |
| Model serving CRD | KServe / AIBrix / NIM Operator / RayService | The same service generated by multiple CRDs |
| Endpoint routing | AIBrix / EPP / Ray Serve / Gateway | Multiple layers with conflicting retry and cache affinity |
| Replica scaling | HPA/KEDA / AIBrix / Ray Serve | Multiple Autoscalers writing replica counts simultaneously |
| Model caching | KServe LocalModel / NIMCache / custom DaemonSet | Duplicate downloads and conflicting eviction policies |
| P/D orchestration | AIBrix / llm-d / Dynamo / Ray Serve LLM | Mixing incompatible KV Connectors |
| Canary | Gateway / KServe / GitOps | Multi-layer traffic percentages multiplied and unexplainable |

## 12. Selection Order

1. Use `Deployment + vLLM/SGLang` to establish model and hardware performance baselines;
2. Evaluate KServe when unified model release is needed;
3. Evaluate AIBrix when LLM-specific routing, LoRA, caching, and elasticity are needed;
4. Evaluate Ray Serve when Python composable services are needed or Ray already exists;
5. Evaluate BentoML when developer packaging experience is needed;
6. Evaluate NIM when NVIDIA validation and support are needed;
7. Application layers such as Dify/LangGraph should always decouple from the Serving layer through stable APIs.

## 13. Go-Live Checklist

- [ ] Distinguished between inference engine, control plane, gateway, and application orchestration;
- [ ] Each control ownership has exactly one Owner;
- [ ] A vLLM/SGLang performance baseline exists without introducing frameworks;
- [ ] API, model names, error codes, and streaming behavior form a stable contract;
- [ ] Model caching, startup probes, warmup, and rolling release have been validated;
- [ ] Autoscaler uses inference metrics such as Queue/Token/KV/latency;
- [ ] LoRA, Prefix Cache, and tenant routing do not leak data;
- [ ] Gateway, controller, Runtime, and model versions are locked;
- [ ] Failure drills completed for single replica, node, Gateway, and control plane failures;
- [ ] Can explain the benefit of adding a new framework relative to a basic Deployment.
