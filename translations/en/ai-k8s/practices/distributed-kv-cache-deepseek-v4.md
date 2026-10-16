---
title: "DeepSeek V4 Flash Distributed KV Cache: From P/D Direct Transfer to Global Cache Pool"
description: "Distinguishes P/D KV direct transfer, KV Offload, Prefix-aware routing, and cross-engine shared caching, compares Mooncake, AIBrix, LMCache/llm-d, and Dynamo KVBM, and provides a progressive validation roadmap for DeepSeek V4 Flash"
status: exploratory
last_reviewed: 2026-08-13
---

# DeepSeek V4 Flash Distributed KV Cache: From P/D Direct Transfer to Global Cache Pool

As online users, long sessions, and Agent requests continue to grow, the GPU KV Cache of a single inference Engine quickly encounters two problems: inactive sessions occupy HBM, and requests routed to another replica must recompute long prefixes that have already appeared. P/D separation adds a third problem: where Prefill generates KV, where Decode should read it from, and how to fall back when transfer fails.

These requirements are often summarized as "building a centralized KV Cache." This phrasing easily evokes the image of a single centralized cache server, but production architectures are better suited to the following definition:

> What is centralized is the global directory, lifecycle, and scheduling decisions of the KV Cache; the KV Blocks themselves should be distributed across GPU HBM, node memory, local NVMe, and remote storage, while retaining a degraded path that re-runs Prefill.

This document only discusses public architectures and reproducible experiments; it contains no organizational, personnel, internal cluster, repository, address, or capacity information. Community capabilities evolve quickly; "implemented" in this document only means that the cited version or documentation explicitly provides the capability, and does not imply that production validation has been completed on DeepSeek V4 Flash.

## 1. First, Disentangle Four Frequently Confused Concepts

### 1.1 P/D KV Direct Transfer

For the same request, the Prefill Engine first processes the Prompt, then hands the KV Cache generated for this request to the Decode Engine. KV can be transferred directly from the Prefill GPU to the Decode GPU, without requiring a separate cluster that persistently stores KV.

```text
Request → Prefill Engine ── NIXL / Mooncake / RDMA ──→ Decode Engine
                   本次请求的 KV Transfer
```

It solves the decoupling of the Prefill/Decode phases, but does not automatically solve cross-replica reuse of historical sessions.

### 1.2 KV Offload

When HBM space is insufficient or inactive sessions occupy GPU memory for extended periods, KV Blocks are moved down to Host DRAM, NVMe, or remote storage, and loaded back when needed. This expands effective cache capacity but adds PCIe, disk, or network I/O.

### 1.3 Prefix Cache-Aware Routing

KV remains stored locally on each Engine; the Router maintains or estimates "which instance has cached which Token Prefixes" and preferentially routes requests to Engines with high hit rates and suitable load. This reduces cross-node transfer, but after replica scale-down or failure, local caches may still disappear.

### 1.4 Cross-Engine Shared KV

Multiple Engines use a shared L2/L3 KV Backend, and the cache is no longer fully attached to a single GPU process. Requests can resume Prefixes on another replica, at the cost of global indexing, data layout compatibility, tenant isolation, capacity governance, and remote transfer.

These four capabilities can be combined, but cannot be summarized with a single "KV Cache enabled":

| Capability | Primary Goal | Requires Shared Storage | Reasonable Fallback After Failure |
| --- | --- | --- | --- |
| P/D Direct Transfer | Isolate Prefill from Decode | No | Decode re-runs Prefill or switches to Combined |
| KV Offload | Expand effective capacity, free HBM | Local Offload does not require it | Recompute evicted Blocks |
| KV-aware Routing | Improve local Prefix hit rate | No, but requires global visibility | Select another instance by load |
| Cross-Engine Shared KV | Reuse across replicas and restarts | Yes | Re-run Prefill when Backend is unavailable |

## 2. Recommended Layered Architecture

A scalable implementation typically includes a control plane and a data plane:

```text
                                 ┌─ Prefill Pool
OpenAI-compatible Request → Router┤
                                 ├─ Decode Pool
                                 └─ Combined Pool（短请求与故障兜底）
                                          │
                              P/D KV Transfer / Cache Load
                                          │
        ┌─────────────────────────────────┴──────────────────────────────┐
        │                                                                │
全局 KV 目录与调度                                                分层 KV 数据面
Prefix → Block Location                                     L1：GPU HBM
Model / Runtime / Layout Fingerprint                         L2：Host DRAM
Tenant / Session / TTL / Quota                               L3：Local NVMe
Load / Topology / Hit Cost                                   L4：Distributed KV Store
```

The global directory should not store large Tensors; it should only store Prefixes, Blocks, locations, versions, tenants, expiration times, and states. The data plane is tiered by heat: active requests remain in HBM, temporarily inactive sessions are moved down to DRAM, and hot long Prefixes can enter NVMe or a distributed Store.

The Router's goal should also not be merely "maximum hits," but rather a comparison of two costs:

```text
预计收益 = 避免重新 Prefill 的时间
预计成本 = 排队时间 + KV 读取/传输时间 + 目标实例 Decode 压力
```

Only when the expected benefit exceeds the expected cost is remote reuse worth executing. Otherwise, re-running Prefill directly on a lower-load Engine may be faster.

## 3. Four Open-Source Paths Worth Tracking

### 3.1 SGLang HiCache + Mooncake

[Mooncake](https://github.com/kvcache-ai/Mooncake) is a public KVCache-centric disaggregated inference infrastructure. It includes:

- Transfer Engine: moves Tensors between VRAM, DRAM, NVMe, and multiple network types;
- Mooncake Store: distributed management of Tensor objects such as KV Cache and model weights;
- Multi-RDMA-NIC bandwidth aggregation, NUMA/topology-aware path selection, and transfer failure switching;
- Integration with SGLang P/D, HiCache, and vLLM.

SGLang [HiCache](https://github.com/sgl-project/sglang/blob/main/docs_new/docs/advanced_features/hicache_design.mdx) extends RadixAttention from GPU to Host Memory and remote storage; publicly documented L3 Backend options include `file`, `mooncake`, `hf3fs`, `nixl`, `aibrix`, and `dynamic`. This path is most tightly coupled with the SGLang Engine and is suitable for priority validation of DeepSeek V4 Flash.

However, "having a startup parameter" does not mean the combination is mature. A public [DeepSeek V4 Flash + H20 + Mooncake P/D reproduction](https://github.com/sgl-project/sglang/issues/26475) points out that DeepSeek V4, in addition to the primary C4 KV, also has SWA/extra states, FlashMLA, and transfer metadata; after enabling HiSparse, the community observed SWA extra-state transfer hanging and incomplete Prefix hit semantics. At minimum, this indicates:

1. The community has already run this DeepSeek V4 data path on H20;
2. Validation must cover not only the primary KV Block but also all additional states;
3. The first round should disable HiSparse and speculative decoding, and first establish a baseline for ordinary P/D and tiered caching.

### 3.2 AIBrix Distributed KV Cache

[AIBrix](https://github.com/vllm-project/aibrix) simultaneously covers Kubernetes orchestration, Gateway routing, P/D pairing, and KV Cache management. Capabilities must be distinguished by version:

- Existing stable versions can complete model discovery, P/D Role pairing, Prompt length bucketing, load scoring, and Combined fallback;
- The current main branch and subsequent releases are unifying the `aibrix_kvcache` data plane, providing L1 DRAM, pluggable L2, Prefix Cache Connector, and Redis-backed Gateway state synchronization;
- The P/D Router and KV data plane can be combined, but the Router selecting Prefill/Decode does not mean historical KV is already shared across replicas.

This path is best suited for clusters already using the AIBrix Gateway: continue letting AIBrix handle ingress, service discovery, and cache-aware scheduling, then select Mooncake, the AIBrix KV Backend, or another data plane through supported Connectors. Before going live, the combined versions of AIBrix, Engine, Connector, NIXL, UCX/CUDA, and Cache Backend must be locked.

### 3.3 llm-d + LMCache

[llm-d](https://github.com/llm-d/llm-d) is a Kubernetes-oriented distributed inference stack whose public goals include:

- Prefix Cache and load-aware routing;
- Precise global indexing of KV Cache;
- CPU, Disk, and remote tiered Offload;
- P/D separation, flow control, SLO-aware scheduling, and auto-scaling.

[LMCache](https://github.com/LMCache/LMCache) provides KV Cache Connectors, CPU/disk Offload, remote caching, and P/D support. Its vLLM P/D example uses NVLink, RDMA, or TCP via NIXL; the old in-process mode has been marked deprecated, and new validation should use MP mode.

The official vLLM DeepSeek V4 Flash Recipe has marked CPU Offload and Filesystem Offload as verified, and provides `LMCacheMPConnector` as a general KV Offload option for single-node TP/TEP/DEP strategies. The current Recipe's LMCache mode is one sidecar `lmcache server` per node, not a cross-node shared pool; therefore it is sufficient for entering DeepSeek V4 intra-node compatibility testing, but cannot directly prove that "cross-node centralized KV Cache is supported." Executable single-node Baseline/LMCache A/B materials are available at: [DeepSeek V4 Flash: vLLM + LMCache MP](https://github.com/runzhliu/aik8s/tree/main/examples/deepseek-v4-flash-vllm-lmcache).

Testing must also cover known risks: DeepSeek V4 uses multiple groups of Hybrid KV, and the community has reported Prefix Cache replay with 0% hit rate, high-concurrency Offload Worker crashes, and DSpark Draft KV external hits remaining at zero for extended periods. The first round should disable DSpark and P/D, and only validate LMCache Load after GPU Cache eviction, deterministic output, and concurrency stability; then P/D, remote Backend, and Draft Model should each be introduced as independent variables.

#### 3.3.1 Single-Node H20 Measurement: A Hit Does Not Mean Correctness

We first validated `LMCacheMPConnector + Host DRAM L1` on a single 8-GPU H20 Engine, without simultaneously introducing P/D, remote Backend, or DSpark. With a fixed Chat Template, random seed, and a 5,142-token Prompt, the model was required to return only `CACHE_OK`. To avoid relying on request pressure to guess the GPU Block eviction order, the test environment briefly enabled the vLLM development interface, reset only the local Prefix Cache, explicitly retained the External Cache, and then replayed the same request.

The metrics prove that the external data path is indeed active:

```text
external_prefix_cache_hits_total  +5,120 tokens
prompt_tokens source=external_kv_transfer  +5,120 tokens
LMCache L1 Lookup/Hit 与内存使用量同时增长
```

But strict output validation did not pass: the cold request and the GPU-local warm hit both stably returned `CACHE_OK`; after clearing the GPU Prefix Cache, the external reload request showed a 5,120-token External Hit but generated corrupted Tokens. After changing the KV dtype from the generic `fp8` to the explicit `fp8_ds_mla` required by the LMCache DeepSeek V4 recipe, the problem still reproduced.

| Configuration | Cold / GPU Warm | External Hit | Output After Reload | Conclusion |
| --- | --- | ---: | --- | --- |
| Generic `fp8` | `CACHE_OK` | 5,120 tokens | Corrupted | Failed |
| Explicit `fp8_ds_mla` | `CACHE_OK` | 5,120 tokens | Corrupted | Failed |

At the same time, a basic compatibility issue was found in the test image: vLLM 0.26.0 and Torch 2.11.0 use CUDA 12.9, but the LMCache 0.5.2 within it comes from the default CUDA 13 installation path, and `lmcache.c_ops` looks for `libcudart.so.13`, which can only fall back to the Python/Torch fallback. The official LMCache installation documentation requires the specifically released cu129 wheel or the `latest-cu129` image for CUDA 12.9, rather than directly installing the default PyPI wheel.

Therefore, this round only proved that "Store, Lookup, and External Transfer counters can work," and did not prove that DeepSeek V4 Hybrid KV can be correctly restored. After the correctness gate failed, throughput and concurrency stress testing were not continued; the test Deployment was scaled down to 0, retaining the model HostPath, manifests, and stress-test scripts. The next round should first switch to a version-locked cu129 combination, require `import lmcache.c_ops` to pass, and then repeat the same deterministic reload test; only after passing can performance A/B testing proceed.

This case is also the most important counterexample in central KV Cache acceptance: **the External Hit metric only proves that a transfer occurred, not that the KV layout and content transferred back are correct.** Deterministic output or Logits must be compared; any garbled text, Hash changes, or incorrect Tokens should immediately halt performance testing.

### 3.4 NVIDIA Dynamo KVBM

[Dynamo KVBM](https://docs.nvidia.com/dynamo/dev/knowledge-base/modular-components/kvbm/overview) provides unified Block management across GPU, Pinned Host Memory, RDMA Remote Memory, SSD, and remote storage, using NIXL for registration, sharing, and transfer. It clearly distinguishes:

- KV-aware Routing: selects Workers based on Prefix overlap and load;
- P/D KV Transfer: hands the current request's KV from Prefill to Decode;
- KV Offloading: migrates Blocks between GPU, CPU, Disk, or remote tiers.

In the current public support matrix, KVBM supports vLLM and TensorRT-LLM, but does not yet support SGLang. It is therefore well suited as a reference for lifecycle, tiering, and metric design, but should not be written up as a ready-made deployment solution for DeepSeek V4 + SGLang. NVIDIA also has a large-scale [DeepSeek V3.2 + TensorRT-LLM + P/D + KV-aware Routing](https://docs.nvidia.com/dynamo/dev/recipes/deepseek-v3-2-nvfp4) Recipe, which is useful for understanding testing methodology but cannot replace actual H20 and DeepSeek V4 measurements.

### 3.5 Selection Summary

| Path | Primary Engine | Tiered KV | P/D | Global Routing | Direct DeepSeek V4 Evidence | Current Positioning |
| --- | --- | --- | --- | --- | --- | --- |
| SGLang HiCache + Mooncake | SGLang | GPU/DRAM/remote Store | Yes | Requires combined Router | H20 reproduction exists, but with unresolved issues | First validation target |
| AIBrix KVCache | Primarily vLLM, extends to multiple Engines | L1 + pluggable L2 | Yes | Strong | Requires version-locked validation | Evolution of existing control plane |
| llm-d + LMCache | vLLM | GPU/CPU/Disk/remote | Yes | Strong | No equivalent out-of-the-box evidence yet | Strict vLLM comparison |
| Dynamo KVBM | vLLM/TRT-LLM | GPU/CPU/SSD/remote | Yes | Strong | Has DeepSeek V3.2 Recipe | Long-term architecture reference |

## 4. Why DeepSeek V4 Flash Requires Separate Validation

DeepSeek V4 Flash's KV Cache is smaller than that of traditional GQA models. Public model documentation states that V4 Flash's KV Cache is approximately 7% of DeepSeek V3.2's, and is lower than a conventional 8-head GQA BF16 KV: [DeepSeek V4 Architecture Introduction](https://github.com/huggingface/blog/blob/main/deepseekv4.md). Therefore, the primary value of building a distributed KV Cache may not be "KV does not fit in HBM," but more likely:

- Long-session recovery in coding agents, search agents, and tool calls;
- Multi-user shared system prompts, tool definitions, knowledge bases, or code repository prefixes;
- KV location discovery and transfer after P/D separation;
- Prefix reuse after Engine scaling, rebuild, or request migration;
- Evicting inactive sessions from HBM to increase concurrency for active requests.

V4's attention state also cannot simply be treated as a traditional set of K/V tensors. At minimum, the main KV, sliding window or other additional states, Indexer/FlashMLA metadata, target model and draft model states, and their consistency across prefix hits, eviction, and P/D transfer must all be verified.

"An increase in user count" is not by itself a sufficient condition for enabling shared KV. If requests are independent of each other, prompts are very short, and prefix overlap is low, a central cache only adds indexing and transfer costs. Whether it is worthwhile can be judged using the following relationship:

```text
可复用 Token 比例 × 避免的 Prefill 计算时间
  > 全局查询 + KV 读取 + 网络传输 + 目标排队时间
```

## 5. Recommended Progressive Validation Roadmap

### Phase A: Keep the Combined Baseline First

Fix the model digest, runtime image, TP, context, KV dtype, CUDA Graph, speculative decoding, and request set to obtain a single Combined TP=8 baseline for correctness, TTFT, TPOT, throughput, HBM, and power consumption.

Previous H20 measurements have already shown that P/D is not necessarily beneficial for low-load short requests, while high concurrency and long prompts are more likely to yield tail latency benefits. Full data is available at: [DeepSeek-V4-Flash-0731 H20 Deployment and Load Testing](deepseek-v4-flash-h20-evaluation.md).

### Phase B: Validate P/D Direct Transfer Only

Use two nodes of identical specifications: one Prefill TP=8 and one Decode TP=8. First disable HiSparse, speculative decoding, and the shared L3 Cache, keeping only SGLang P/D, Mooncake or NIXL, RDMA, and a regular Radix Cache.

Acceptance must simultaneously satisfy:

1. Prefill and Decode use exactly the same model, tokenizer, data type, and KV layout;
2. The transfer backend initializes successfully with no silent fallback to TCP;
3. Prefill/Decode logs can be correlated to the same Request ID;
4. Both the successful transfer counter and the RDMA port hardware counter increase;
5. Decode does not re-Prefill due to transfer failure;
6. Deterministic output for fixed prompts is correct;
7. On backend failure, it can fall back to Combined or recompute, rather than using incomplete state.

### Phase C: Add L2 Host Memory

Start with intra-node offload to avoid introducing a distributed store at the same time. Compare HBM released, Host Memory usage, PCIe bandwidth, Cache Hit/Load latency, and TPOT under high concurrency. Only expand offload capacity when repeated long prefixes can cover the load cost.

### Phase D: Add Distributed L3

Choose one of Mooncake Store, AIBrix KV Backend, or LMCache Remote Backend to validate cross-Engine hits. At this point, the following must be completed:

- Global block index, Watcher, and Cache Engine high availability;
- Tenant, session, model, and runtime fingerprints;
- TTL, quota, eviction, backpressure, and capacity watermarks;
- Fallback for cache backend interruption, network partition, and dirty entries;
- Data rebalancing and hotspot migration when cache nodes scale.

### Phase E: Enable DeepSeek V4-Specific Optimizations Last

After plain P/D and hierarchical caching are stable, enable HiSparse, Draft Model, FP8 KV, and larger context one at a time. Change only one variable per run, and re-run correctness, prefix hit, transfer integrity, and performance A/B tests.

## 6. Load Testing Must Simulate Reusable Prefixes

Load testing with only random prompts cannot prove the value of shared KV. At minimum, four workload groups are needed:

| Request Set | Prefix Characteristics | Question to Answer |
| --- | --- | --- |
| Random prompts | Almost no overlap | How much extra cost does a cache miss add |
| Shared system prompt | Multiple users share a fixed prefix | Can the router stably hit shared blocks |
| Multi-turn sessions | Same session continuously appends | Can historical KV be reused after session migration |
| Agent/code repository trace | Long prefix, short increments, tool results continuously appended | Does it actually reduce long-context TTFT and improve Goodput |

Core metrics include:

- p50/p95/p99 TTFT, TPOT, ITL, E2E, and Goodput;
- Number of prefix cache hit tokens, not just request hit rate;
- P/D KV transfer and shared backend load in bytes, latency, and failure rate;
- Capacity and bandwidth at each layer: GPU HBM, Host Memory, NVMe, RDMA;
- Eviction, promotion, demotion, recompute, and Combined fallback;
- Cost per million tokens and actual GPU-seconds saved per hit.

The test matrix must include at least:

```text
Combined + Round Robin
Combined + KV-aware Routing
P/D + 无共享 Cache
P/D + L2 Host Memory
P/D + Distributed L3
```

All combinations use the same trace, arrival pattern, and SLO, to avoid mistaking more GPUs or different concurrency for cache benefits.

## 7. Multi-Tenancy and Failure Boundaries

The KV Cache may contain user prompts, retrieved content, source code, tool results, and business data. The global cache key must not use only a token hash; it should include at least:

```text
Tenant / Security Domain
+ Model Digest / Tokenizer / Chat Template
+ Runtime / KV Layout / Block Size / DType
+ Adapter / LoRA / Prompt Adapter
+ Prefix Token Hash
```

Cross-user sharing should only be allowed for explicitly classified public prefixes; private sessions are restricted by default to the tenant or session domain. Metadata, cached data, and access logs require independent authentication, encryption in transit, encryption at rest, retention periods, and deletion capabilities.

The shared backend must not become a hard dependency for inference. The recommended degradation order is:

1. On remote KV hit failure, fall back to the local prefix cache;
2. If the local cache also misses, re-Prefill;
3. If the P/D pair is incomplete or transfer fails, fall back to Combined;
4. Return a service error only when the model itself is unavailable.

A timeout budget must be set for KV reuse. If remote load time is already close to the estimated time of re-Prefill, the Router should proactively cancel the remote read and recompute.

## 8. Current Recommendations

For DeepSeek V4 Flash, the more prudent path right now is not to immediately build a large, all-encompassing "central cache cluster," but rather:

1. Use the existing Combined TP=8 as the correctness and cost baseline;
2. Prioritize validating plain P/D direct transfer with SGLang + Mooncake/NIXL + RDMA;
3. Have AIBrix or an equivalent Router handle P/D pairing, prefix- and load-aware selection, and Combined fallback;
4. Add node Host Memory first, then choose one distributed L3 backend;
5. Only expand the cache pool after real Agent traces prove that prefix reuse can cover query and transfer costs;
6. Finally enable HiSparse, speculative decoding, and V4-specific state optimizations.

The open-source community already provides enough control-plane and data-plane components. The truly difficult part is not building another storage system, but validating DeepSeek V4's complete state semantics, version compatibility, cache hit benefits, tenant isolation, and failure fallback. A centralized KV Cache should be treated as a scheduling and data lifecycle system, not a new shared disk.

Further reading:

- [The Performance Inflection Point of Prefill/Decode Separation](pd-break-even.md)
- [DeepSeek-V4-Flash-0731 H20 Deployment and Load Testing](deepseek-v4-flash-h20-evaluation.md)
- [Deploying AIBrix on an Existing Kubernetes Cluster](aibrix-existing-cluster.md)
- [Distributed Inference and P/D Separation](../inference/distributed-serving.md)
