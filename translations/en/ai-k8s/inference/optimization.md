---
title: "LLM Inference Optimization: Batch, KV Cache, Quantization, and Parallelism"
description: "Understand continuous batching, prefix cache, quantization, speculative decoding, and multiple parallelism strategies with verifiable methods"
status: evolving
last_reviewed: 2026-08-02
---

# LLM Inference Optimization: Batch, KV Cache, Quantization, and Parallelism

LLM inference optimization is a multi-objective problem: throughput, TTFT, TPOT, GPU memory, quality, power consumption, and cost all constrain one another. A configuration that improves offline aggregate throughput may worsen tail latency for interactive requests.

## 1. Building a Performance Model

LLM requests fall mainly into:

```text
输入 Token
  → Prefill：并行处理 Prompt，偏计算密集
  → 首 Token
  → Decode：逐 Token 生成，偏内存带宽和同步敏感
  → 完成
```

Core metrics:

| Metric | Meaning | Primary Influencing Factors |
| --- | --- | --- |
| TTFT | Time to first token | Queueing, Prefill, Prefix Cache, network |
| TPOT/ITL | Per-token latency in the decode phase | Decode batch, memory bandwidth, parallel communication |
| E2E | Total request time | Input/output length, queueing, and engine |
| Token Throughput | Tokens processed per second | Batch, concurrency, hardware, and model |
| Goodput | Effective throughput meeting SLOs | Tail latency, errors, rejections, and quality |

Goodput is closer to production value than peak throughput.

## 2. Continuous Batching

Static batching waits for an entire group of requests to finish, wasting compute when long and short requests are mixed. Continuous batching allows new requests to join and completed requests to leave at each scheduling step.

Tuning variables typically include:

- Maximum number of concurrent sequences;
- Maximum number of batched tokens per round;
- Scheduling priority between Prefill and Decode;
- Chunked Prefill size;
- Maximum wait time;
- Memory watermark and preemption policy.

Increasing the batch size usually improves throughput but may increase queueing and TPOT. Separate configuration profiles should be established for interactive, batch, and long-context workloads.

## 3. KV Cache Capacity

For the computational principles, capacity formulas, cross-request reuse, and Kubernetes deployment, see [KV Cache Survey](kv-cache-overview.md).

KV Cache grows with the number of layers, KV heads, head dimension, precision, and context length. Simplified understanding:

```text
KV Cache ∝ 并发序列数 × 上下文 Token × 每 Token KV 大小
```

GPU memory budget:

```text
GPU HBM = 模型权重
        + KV Cache
        + 激活与临时 Workspace
        + 通信 Buffer
        + CUDA Graph/引擎开销
        + 安全余量
```

Do not allocate all remaining GPU memory to the KV Cache. Load fluctuations, model characteristics, and communication libraries still need space; otherwise, unpredictable OOMs will occur.

## 4. Paged KV Cache

Paged management divides the KV Cache into blocks, reducing contiguous memory and fragmentation requirements, and supporting more flexible sequence joining, completion, and sharing. It solves the memory management problem but does not automatically solve:

- Which replica a request should be routed to;
- Whether prefixes are reused across replicas;
- Whether KV is offloaded to CPU/NVMe;
- How P/D workers transfer data between them;
- How different tenants are isolated and billed.

These require coordination among the Router, Indexer, Offloader, and control plane.

## 5. Prefix Cache

Suitable when:

- A large number of requests share a System Prompt;
- Multi-turn conversations repeat historical prefixes;
- RAG templates are stable;
- Agents use the same tool definitions;
- Batch processing shares a common prefix.

Measure:

- Number of hit tokens and hit rate;
- Saved Prefill time;
- Cache occupancy and eviction;
- Load imbalance caused by router affinity;
- Prefix isolation and sensitive data risk.

Simple least-loaded routing may break cache hits, while simple cache-affinity may create hot spots; a multi-objective scoring function is needed.

## 6. KV Cache Offload

The hierarchy can be:

```text
GPU HBM
  ↕ 高速
CPU DRAM
  ↕
本地 NVMe
  ↕
远端共享存储/分布式缓存
```

Offloading can expand effective capacity but adds latency, bandwidth, and consistency overhead. The following must be measured:

- Offload/Restore throughput and tail latency;
- CPU/NUMA and GPU topology;
- NVMe write amplification and lifespan;
- Remote network congestion;
- Cache eviction;
- State after node failure;
- Whether sensitive prompts enter persistent media.

## 7. Weight Quantization

Quantization goals include reducing weight GPU memory, improving memory bandwidth efficiency, and using low-precision Tensor Cores. Common categories:

| Type | Examples | Characteristics |
| --- | --- | --- |
| Weight-only | INT4/AWQ/GPTQ | Significantly reduces weights; activations remain at higher precision |
| Weight + Activation | FP8/INT8 | May achieve higher hardware throughput; requires scales/calibration |
| KV Cache Quantization | FP8/lower precision | Expands context and concurrency; long-context quality needs attention |
| GGUF Quant | Multiple integer/mixed formats | Commonly used with llama.cpp and local inference |

Verify before choosing:

- Whether the target GPU/ASIC has efficient kernels;
- Whether the model architecture and MoE are supported;
- Whether calibration data represents the production distribution;
- Whether quality, safety, tool calling, and structured output regress;
- Whether the throughput gain offsets conversion and operational costs.

vLLM's quantization support matrix varies by hardware and implementation; pin the target version for validation. [vLLM Quantization](https://docs.vllm.ai/en/stable/features/quantization/)

## 8. Speculative Decoding

Speculative decoding uses draft models, N-gram, MTP/EAGLE, and other methods to propose multiple candidate tokens at once, which the main model then verifies.

Potential benefits:

- Lower per-request decode latency;
- Higher output speed when the main model is expensive to compute and the acceptance rate is high.

May provide no benefit or even slow things down:

- The draft model consumes additional GPU memory;
- Low candidate acceptance rate;
- The main model is already well batched under high concurrency;
- Incompatible combinations of quantization, parallelism, or model structure;
- Draft scheduling introduces additional synchronization.

Single-stream low-latency and high-concurrency throughput must be tested separately; do not extrapolate single-request results to production.

## 9. Chunked Prefill

A long Prefill occupies a scheduling step for a long time, affecting the TPOT of existing decode requests. Chunked Prefill splits long prompts so that Prefill and Decode can interleave more easily.

Tuning must balance:

- Chunk too large: interactive decode is blocked by long Prefill;
- Chunk too small: scheduling and kernel overhead increases;
- Batched token upper limit;
- TTFT vs. TPOT priority;
- Prefix Cache and multimodal input behavior.

## 10. Parallelism Strategies

### Tensor Parallel (TP)

Splits single-layer tensors across multiple devices, requiring frequent collectives. Prefer placing it in high-bandwidth domains such as NVLink/NVSwitch.

Suitable when a single card cannot fit the model or single-card throughput is insufficient. Increasing TP may reduce per-request latency, but communication overhead increases.

### Pipeline Parallel (PP)

Splits by layers into multiple stages, suitable for cross-node or weakly interconnected setups. Pipeline bubbles, batch, and stage imbalance must be handled.

### Data Parallel (DP)

Each replica holds the full model and processes different requests. Suitable when the model fits in a single replica and throughput needs to scale. Request routing between replicas determines cache hits and load balance.

### Expert Parallel (EP)

MoE experts are distributed across devices, requiring All-to-All communication, and are sensitive to network topology and load balance.

### Context/Sequence Parallel

Splits long-context computation along the sequence dimension, suitable for extremely long contexts, but introduces communication and implementation constraints.

## 11. How to Choose a Parallelism Combination

Recommended order:

1. Whether a single GPU can hold the weights and target KV Cache;
2. Within a single node, prefer TP with high-speed interconnect;
3. Evaluate PP/TP combinations across nodes;
4. To scale throughput, first add DP replicas;
5. For MoE, evaluate EP based on experts and network;
6. Consider Context Parallel only for extremely long contexts;
7. Evaluate P/D separation once scale is sufficient.

Do not default to TP=8 just because 8 GPUs are available. For models that fit on a single card, 8 DP replicas may provide better aggregate throughput and fault isolation.

## 12. Model Compilation and CUDA Graph

Graph compilation, kernel autotuning, and CUDA Graph can reduce Python/launch overhead, but introduce:

- Compilation time on first startup or first shape;
- Compilation cache;
- Dynamic shape/multimodal constraints;
- Driver, GPU architecture, and engine version binding;
- More complex rollback and fault diagnosis.

Treat compiled artifacts as part of the model supply chain, and measure cold start and warm start separately.

## 13. LoRA and Multi-Model Serving

Dynamically loading multiple adapters on one base model can save weight GPU memory, but requires governance:

- Adapter source, size, and compatibility;
- Load/unload and cache policy;
- Whether the router knows which replica holds the adapter;
- Per-tenant concurrency, tokens, and cost;
- Adapter quality and safety evaluation;
- Compatibility when the base model is upgraded;
- Impact of a malicious adapter on the shared process.

Packing multiple models into one process also creates GPU memory fragmentation, a larger failure domain, and complex scheduling, which may not be better than independent deployment.

## 14. Tuning Experiment Design

Change only one set of variables at a time:

```text
基线：BF16、默认 Batch、单副本
  → 调整 Batch/并发
  → 调整 KV Cache 和上下文
  → 测试 Prefix Cache
  → 测试量化
  → 测试 TP/PP/DP
  → 测试投机解码
  → 测试 Offload/P-D
```

Save the configuration, raw requests, metrics, quality results, and hardware metadata at each step. If quantization, batch, and parallelism are changed simultaneously, it is impossible to know where the gains came from.

## 15. Realistic Workload Matrix

Cover at least:

- Short input/short output;
- Long input/short output;
- Short input/long output;
- Long input/long output;
- High/low shared prefix;
- Steady, bursty, and periodic traffic;
- Streaming and non-streaming;
- Multi-tenant priority;
- Tool calling/structured output;
- Cancellation, timeout, and client disconnects.

Using fixed requests with average lengths hides production tail problems.

## 16. Performance and Quality Gates

| Dimension | Example Gate |
| --- | --- |
| Quality | Task success rate does not drop beyond threshold |
| TTFT | P95/P99 meets interactive SLO |
| TPOT | Smooth output still maintained under high concurrency |
| Goodput | Requests/second meeting all SLOs does not decline |
| Stability | Stress test for target duration without OOM/deadlock |
| Cold start | Both cold and warm cache within budget |
| Cost | Cost per million effective tokens |
| Safety | Structured output, tools, and content policy pass |

## 17. Common Anti-Optimizations

- Batch too large causing TTFT/TPOT to spiral out of control;
- `max-model-len` set to the theoretical maximum, squeezing actual concurrency;
- Quantization shrinks weights but kernels are slower on the target hardware;
- TP across slow networks, making communication gains negative;
- Prefix Cache routing causing a few replicas to overheat;
- Speculative decoding consuming extra GPU under high concurrency;
- Offload making PCIe/network the bottleneck;
- Model compilation preventing cold start from meeting elasticity requirements.

## 18. Production Checklist

- [ ] Performance model distinguishes Prefill, Decode, queueing, and network.
- [ ] GPU memory budget includes weights, KV, workspace, communication, and headroom.
- [ ] Batch parameters satisfy both throughput and tail latency.
- [ ] Prefix Cache has hit, capacity, routing, and privacy metrics.
- [ ] Every quantization version passes quality and target-hardware performance regression.
- [ ] Parallelism strategy matches NVLink/RDMA/topology.
- [ ] Speculative decoding validated separately for low and high concurrency.
- [ ] Compilation and warm-up time included in the cold-start budget.
- [ ] LoRA/multi-model has permission, cache, and fault isolation policies.
- [ ] All optimizations pass the same realistic workload matrix and Goodput gates.

## Further Reading

- [vLLM Quantization](https://docs.vllm.ai/en/stable/features/quantization/)
- [vLLM Distributed Serving](https://docs.vllm.ai/en/latest/serving/distributed_serving.html)
- [SGLang Documentation](https://docs.sglang.io/)
- [TensorRT-LLM Documentation](https://nvidia.github.io/TensorRT-LLM/latest/)
- [Triton Dynamic Batching](https://docs.nvidia.com/deeplearning/triton-inference-server/user-guide/docs/user_guide/batcher.html)
- [llm-d KV Cache Management](https://llm-d.ai/docs/architecture/advanced/kv-management)
