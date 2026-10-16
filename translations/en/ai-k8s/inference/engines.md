---
title: "LLM Inference Engine Selection"
description: "Compare the capabilities, boundaries, and Kubernetes integration approaches of engines such as vLLM, SGLang, TensorRT-LLM, Triton, and llama.cpp"
status: evolving
last_reviewed: 2026-08-02
---

# LLM Inference Engine Selection

The inference engine is responsible for loading models, managing GPU memory, organizing batches, executing kernels, and emitting tokens; KServe, Kubernetes, and the Gateway are responsible for service lifecycle, resources, and traffic. Before selecting an engine, you must first clarify these boundaries.

If you are still in the model, prompt, RAG, or API integration phase, start with [Running and Testing Large Models Locally](local-testing.md), then use this page to select production candidate engines.

## 1. Inference Platform Layering

```text
API Client
  OpenAI / KServe V2 / gRPC
        │
Gateway 与请求调度
  Auth、Quota、Rate Limit、InferencePool、KV-aware Routing
        │
服务控制面
  Deployment、KServe、Ray Serve、LWS、llm-d、Dynamo
        │
推理引擎
  vLLM、SGLang、TensorRT-LLM、Triton、llama.cpp
        │
模型与硬件
  safetensors/GGUF/Engine、GPU/TPU/ASIC、KV Cache、网络
```

KServe and vLLM are usually used in combination; llm-d/Dynamo may also provide distributed execution, routing, and KV transfer on top of multiple engines.

## 2. Define Requirements First

At minimum, clarify:

- Text, Embedding, Reranker, speech, vision, or multimodal;
- Model, parameter count, Dense/MoE, and context limit;
- Target hardware, single-node or multi-node;
- Precision and quantization constraints;
- Online, batch, or mixed traffic;
- TTFT, TPOT, throughput, and availability SLOs;
- LoRA, structured output, tool calling, and speculative decoding requirements;
- Prefix cache, KV offload, and P/D separation requirements;
- Protocols such as OpenAI API, KServe V2, gRPC;
- License, support, and upgrade strategy.

Without a workload profile, "which engine is fastest" has no actionable answer.

## 3. Major Engine Comparison

| Engine | Core Positioning | Strengths | Main Costs |
| --- | --- | --- | --- |
| vLLM | General high-throughput LLM serving | Active ecosystem, OpenAI API, Paged KV, broad model/hardware support, extensive control-plane integration | Fast feature evolution; version and model combinations need to be pinned |
| SGLang | LLM/multimodal and complex inference programs | Radix/Prefix Cache, structured generation, complex shared prefixes, active performance optimization | Production parameters and versions change quickly; requires independent benchmarking |
| TensorRT-LLM | NVIDIA extreme optimization | Deep optimization of NVIDIA kernels, quantization, parallelism, and speculative decoding | Build/compatibility complexity; stronger hardware and software coupling |
| Triton | Multi-framework unified inference server | Model Repository, dynamic/sequence batching, multiple backends, unified protocols and metrics | Not the shortest path to all advanced LLM capabilities |
| llama.cpp | Lightweight local and edge inference | GGUF, CPU/multi-backend, simple deployment, low resource requirements | Limited for large-scale datacenter serving and control-plane capabilities |
| TGI | Hugging Face model serving | Hub integration, OpenAI compatible, direct deployment | Capability overlap with newer engines; confirm active features and hardware support before selection |
| Custom PyTorch/JAX | Special models or research capabilities | Full control | You take on batching, memory, protocols, metrics, and failure handling yourself |

The table only expresses positioning. Model coverage and hardware matrices change quickly; always defer to the official documentation and benchmarks of the target version.

## 4. vLLM

Suitable for:

- General Chat/Completion/Embedding serving;
- OpenAI-Compatible API requirements;
- Integration with KServe, Ray, llm-d, or common Gateways;
- Continuous batching, Prefix Cache, LoRA, quantization, and multiple parallelism modes;
- Supported backends including NVIDIA, AMD, TPU, CPU.

Needs verification:

- Target model architecture and Attention Backend;
- `max-model-len` and KV Cache capacity;
- Tensor/Pipeline/Data/Expert Parallel combinations;
- Quantization format kernels on target hardware;
- Chunked Prefill, Prefix Cache, and speculative decoding interactions;
- Multimodal, structured output, and LoRA limitations;
- Engine metrics and upgrade compatibility.

Single-node conceptual example:

```bash
vllm serve /models/example \
  --served-model-name example \
  --tensor-parallel-size 4 \
  --max-model-len 32768 \
  --enable-prefix-caching
```

Parameters cannot be copied directly from blog posts into production. Establish a baseline first using the target model and request distribution.

Reference: [vLLM Documentation](https://docs.vllm.ai/)

## 5. SGLang

SGLang's core features include RadixAttention/Prefix Cache, structured generation, parallelism, and a runtime oriented toward complex LLM/multimodal workloads.

Priority evaluation scenarios:

- Many requests sharing system prompts or long prefixes;
- Agent, structured output, and multi-turn inference;
- Complex cache-aware scheduling requirements;
- Running on supported backends such as NVIDIA, AMD, TPU;
- Evaluating P/D separation or large-scale multi-node inference.

Key verification points:

- Radix Cache hit rate and memory overhead;
- Cache and load-balancing affinity;
- Impact of structured output on throughput;
- Target model, quantization, and hardware backend;
- Compatible versions between SGLang and control planes such as llm-d/Dynamo;
- Request cancellation, rolling release, and cache cleanup.

Reference: [SGLang Documentation](https://docs.sglang.io/). Without a GPU, you can first validate dynamic discovery, routing, failure removal, and metrics using [SGLang Model Gateway CPU Hands-on](../practices/sglang-model-gateway-cpu-lab.md), but mock results must not be treated as runtime performance conclusions.

## 6. TensorRT-LLM

Suitable for teams pursuing extreme performance on NVIDIA platforms who can bear the build and verification complexity. Capabilities typically include:

- Multiple low-precision and quantization modes;
- In-flight batching;
- Paged KV Cache;
- Tensor/Pipeline/Expert Parallel;
- Speculative decoding;
- Multi-node and disaggregated inference;
- Integration with the NVIDIA stack including Triton, Dynamo, and NIM.

Main risks:

- Engines/artifacts may be bound to GPU architecture, TensorRT-LLM, and build configuration;
- Model conversion and compilation enter the supply chain;
- New model support may lag behind general-purpose frameworks;
- Optimal performance parameters vary across GPU generations;
- Rollback requires retaining both the old engine and runtime.

Reference: [TensorRT-LLM Documentation](https://nvidia.github.io/TensorRT-LLM/latest/)

## 7. Triton Inference Server

Triton is suitable for unifying traditional ML/DL, multiple models, and multiple backends:

- Backends including TensorRT, ONNX Runtime, PyTorch, Python;
- Model Repository and versioning policy;
- HTTP/gRPC and KServe Protocol;
- Dynamic Batching, Sequence Batching;
- Multiple model instances;
- Model Management, Metrics, and Trace;
- Ensemble and pre/post-processing.

Triton can host LLM backends, but if the goal is the latest Prefix Cache, P/D separation, or complex LLM routing, you should compare the actual capabilities and operational complexity of using vLLM/SGLang/TensorRT-LLM directly or their Triton backends.

Reference: [Triton Architecture](https://docs.nvidia.com/deeplearning/triton-inference-server/user-guide/docs/user_guide/architecture.html)

## 8. llama.cpp and Edge Runtimes

Suitable for:

- CPU, consumer GPUs, Apple Silicon, or edge devices;
- GGUF quantized models;
- Single-node, small-scale, and offline scenarios;
- Environments sensitive to dependencies and deployment footprint.

On Kubernetes, you still need to address:

- Node capability labels;
- Model file distribution;
- Local disks and weak edge networks;
- CPU/memory/thread affinity;
- API, probes, updates, and rollback;
- Multi-replica load balancing.

Do not skip model versioning and quality regression just because the runtime is lightweight.

## 9. Multi-Engine Runtime Catalog

The platform can maintain a set of validated runtimes:

| Runtime ID | Engine | Hardware | Applicable Models | Status |
| --- | --- | --- | --- | --- |
| vllm-cuda-stable | vLLM | NVIDIA Ampere+ | General decoder LLMs | stable |
| sglang-cuda-prefix | SGLang | NVIDIA Hopper | Shared long prefixes | canary |
| trtllm-hopper-fp8 | TensorRT-LLM | H100/H200 | Compiled FP8 models | stable |
| vllm-rocm | vLLM ROCm | AMD Instinct | Models on the validated list | canary |
| llama-cpu | llama.cpp | x86/ARM | Small GGUF models | stable |

Each runtime records: image digest, driver/CUDA/ROCm, engine version, supported models, quantization, maximum context, known limitations, benchmarks, and end-of-life date.

## 10. Kubernetes Deployment Baseline

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: llm-server
spec:
  replicas: 1
  selector:
    matchLabels:
      app: llm-server
  template:
    metadata:
      labels:
        app: llm-server
    spec:
      terminationGracePeriodSeconds: 120
      containers:
        - name: server
          image: registry.example.com/ai/vllm@sha256:replace
          args:
            - serve
            - /models/example
            - --served-model-name=example
          ports:
            - name: http
              containerPort: 8000
          readinessProbe:
            httpGet:
              path: /health
              port: http
            periodSeconds: 5
          resources:
            requests:
              cpu: "8"
              memory: 64Gi
              nvidia.com/gpu: "1"
            limits:
              cpu: "8"
              memory: 64Gi
              nvidia.com/gpu: "1"
```

Production also requires model volumes, `/dev/shm`, security context, ServiceAccount, NetworkPolicy, PDB, Service, Gateway, metrics, and graceful termination.

## 11. Readiness and Startup Probes

Model download and loading can take a long time; it is recommended to distinguish:

- Startup Probe: allows the process and model to complete initialization;
- Liveness Probe: detects whether the process is hung;
- Readiness Probe: whether the model and engine can safely receive traffic.

Readiness should cover target model presence, engine worker health, and necessary distributed peer readiness. Port listening does not prove the model has been loaded.

## 12. Graceful Termination

During rolling upgrades:

1. Remove from Endpoint/InferencePool;
2. Stop accepting new requests;
3. Allow streaming and long requests to complete or return recognizable errors;
4. Clean up P/D, KV, and distributed connections;
5. Exit within the grace period;
6. Force terminate only on timeout.

Client cancellation, SIGTERM, preStop, and Gateway Endpoint update ordering need to be verified.

## 13. Engine Selection Experiments

Using the same model and hardware, run the following against candidate engines:

1. Functional compatibility tests;
2. Offline quality regression;
3. Single-request TTFT/TPOT;
4. Throughput and tail latency under different concurrency levels;
5. Mixed long/short inputs and burst traffic;
6. Model cold start;
7. OOM, cancellation, restart, and rolling upgrade;
8. Metrics, trace, and log completeness;
9. Per-token cost and power consumption;
10. Version upgrade compatibility.

## 14. Common Mistakes

- Only looking at vendor-published peak Token/s;
- Not pinning model revision, quantization, and request distribution;
- Treating the engine and service control plane as mutually exclusive products;
- Enabling all optimizations at once and being unable to localize regressions;
- Using `latest` images and model tags;
- Readiness only checks the port;
- Having one runtime support all models without a compatibility matrix;
- Ignoring cancellation, rolling upgrades, and long-lived connections.

## 15. Production Checklist

- [ ] Engine selection is based on the target model, hardware, and real request distribution.
- [ ] Runtime Catalog pins image digests and compatibility matrices.
- [ ] Model quality and performance regressions use the same artifact version.
- [ ] Readiness indicates the model can truly accept traffic.
- [ ] Cold start is split into download, load, compile, and warm-up.
- [ ] Streaming requests, cancellation, and SIGTERM behavior are verified.
- [ ] Multi-node engines are managed holistically by LWS/control plane.
- [ ] Gateway, KServe, and engine responsibilities are documented without overlap.
- [ ] Metrics include TTFT, TPOT, queue, token, and KV Cache.
- [ ] Upgrades can roll back model, engine, and configuration independently.

## Further Reading

- [vLLM Documentation](https://docs.vllm.ai/)
- [SGLang Documentation](https://docs.sglang.io/)
- [TensorRT-LLM Documentation](https://nvidia.github.io/TensorRT-LLM/latest/)
- [Triton Inference Server](https://docs.nvidia.com/deeplearning/triton-inference-server/user-guide/docs/)
- [KServe Serving Runtimes](https://kserve.github.io/website/docs/concepts/resources/servingruntime)
