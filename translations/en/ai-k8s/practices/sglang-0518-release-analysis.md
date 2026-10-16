---
title: "SGLang v0.5.16 / v0.5.17 / v0.5.18 Single-Card L20 Benchmarks: Is Upgrading Really Faster?"
description: "Using official images on the same L20 to benchmark SGLang v0.5.16, v0.5.17, and v0.5.18, and analyzing throughput, tail latency, startup, and capacity changes against official Release notes"
status: evolving
last_reviewed: 2026-08-24
---

# SGLang v0.5.16 / v0.5.17 / v0.5.18 Single-Card L20 Benchmarks: Is Upgrading Really Faster?

> SGLang v0.5.18 was released on August 22, 2026, with a total of 710 PRs merged from 212 contributors. In addition to breaking down the official H100, B200, and Blackwell data, this article also uses three official `lmsysorg/sglang` runtime images to complete A/B testing of v0.5.16 / v0.5.17 / v0.5.18 on the same L20, the same Qwen3.8-27B-FP8, and the same load-testing client. The conclusion is clear: for short requests, single-request performance shows almost no version-level jump; v0.5.17 exhibits a decrease in running-slot capacity; v0.5.17 and v0.5.18 show reproducible tail-latency increases in this 4K mixed Prefill/Decode workload.

The motivation for this test is simple: today I saw a WeChat article claiming v0.5.18 delivers "explosive inference speed gains," with quite exaggerated performance improvements. Rather than relaying conclusions, this article returns to the original test methodology of the official PRs and conducts an independent re-test in the available L20 environment.

## 1. Conclusions from the Benchmarks

| Question | Measured Result | Assessment |
| --- | --- | --- |
| Are short requests faster after upgrading? | C1 about 18.8–18.9 tok/s, C4 about 79.6–80.2 tok/s; differences across the three versions do not exceed about 1% | Essentially flat on the single-card L20 + Qwen3.8-27B-FP8 path |
| Does high-concurrency capacity change? | v0.5.17 has only 5 actual running slots, v0.5.16/v0.5.18 have 6; C8 throughput is 95.61, 110.83, 111.71 tok/s respectively | v0.5.17's high-concurrency throughput drops about 14%, primarily a capacity change |
| Is 4K input better? | All three versions have throughput of about 44 tok/s; v0.5.16 has P95 TPOT of about 61 ms across two rounds, v0.5.17/v0.5.18 about 71 ms | Total throughput unchanged, but the two newer versions show reproducible request-level tail-latency increases |
| Is startup 2.38× faster? | Excluding Image Pull, container to internal Ready is about 126 / 131 / 122 seconds | The official 2.38× is the explicit Overlap path on H100 and cannot be extrapolated to this default L20 configuration |

Therefore, the safest positioning for v0.5.18 is: **capabilities and certain specific paths continue to improve, but for the current L20 + Qwen3.8-27B-FP8, the upgrade value mainly comes from features and fixes, not short-request throughput explosions; before going live, long-input scheduling tail latency should be a key regression test target.**

![Measured comparison of SGLang v0.5.16, v0.5.17, v0.5.18 on a single L20](../../assets/practices/sglang-0518-l20/version-benchmark.png)

Raw summary data: [sglang-v0516-v0518-ab-20260824.json](https://github.com/runzhliu/aik8s/blob/main/examples/qwen38-27b-l20-sglang/results/sglang-v0516-v0518-ab-20260824.json). Official reference: [SGLang v0.5.18 Release](https://github.com/sgl-project/sglang/releases/tag/v0.5.18).

## 2. Test Design and Fairness Boundaries

| Item | Fixed Value |
| --- | --- |
| GPU | Single NVIDIA L20, 46,068 MiB |
| Model | Qwen3.8-27B-FP8, TP=1 |
| Context and KV | 32K, FP8 E4M3 KV Cache |
| Features | Full multimodal, Reasoning Parser, and Tool Parser retained |
| CUDA Graph | Prefill Graph disabled, Decode Graph retained |
| Server | `mem-fraction-static=0.88`, declared max running requests 8, Chunked Prefill 8192 |
| Images | Official `lmsysorg/sglang:v0.5.16-cu129-runtime`, `v0.5.17-cu129-runtime`, `v0.5.18-cu129-runtime` |
| Client | Independently pinned to the official v0.5.16 environment, not rebuilt across the three rounds |
| Traffic | `random-ids`, fixed Tokenizer, seed=42, temperature=0, request-rate=inf |

Short requests: 64 requests per group, 8 warmups, testing 128 input / 64 output with C1/C4/C8; long requests: 32 requests per group, 4 warmups, testing 4096 input / 128 output with C4. Each version switch first passes the same Chat correctness smoke test; all three versions return correct results, and all load-test requests succeed.

This is still not laboratory-grade multi-round statistics: short requests have only one round per Shape; for long inputs, because anomalies were found, v0.5.16 and v0.5.18 each ran an additional round, v0.5.17 one round. Versions were executed in the order 0.5.16 → 0.5.18 → 0.5.17, so later-tested versions may be affected by the host page cache already being warm. Therefore, Weight Load is treated only as an observation and is not used to claim version-level load acceleration; the input, service, and client variables for online load testing remain unchanged.

## 3. Short Requests: C1/C4 Flat, C8 Exposes v0.5.17 Capacity Drop

### 3.1 128 Input / 64 Output

| Version | Concurrency | Output tok/s | P95 TTFT | P95 TPOT | P95 E2E |
| --- | ---: | ---: | ---: | ---: | ---: |
| 0.5.16 | 1 | 18.92 | 187.46 ms | 50.63 ms | 3,368.96 ms |
| 0.5.17 | 1 | 18.89 | 188.37 ms | 50.58 ms | 3,373.66 ms |
| 0.5.18 | 1 | 18.83 | 204.26 ms | 50.68 ms | 3,389.18 ms |
| 0.5.16 | 4 | 79.59 | 267.27 ms | 47.34 ms | 3,250.80 ms |
| 0.5.17 | 4 | 79.64 | 272.91 ms | 47.28 ms | 3,251.79 ms |
| 0.5.18 | 4 | 80.20 | 277.97 ms | 46.92 ms | 3,235.77 ms |
| 0.5.16 | 8 | 110.83 | 3,705.50 ms | 48.42 ms | 6,755.62 ms |
| 0.5.17 | 8 | 95.61 | 3,601.77 ms | 47.98 ms | 6,617.22 ms |
| 0.5.18 | 8 | 111.71 | 3,678.68 ms | 48.01 ms | 6,701.84 ms |

C1 and C4 Output Throughput and TPOT nearly coincide, which does not support the claim that "upgrading to v0.5.18 significantly speeds up Qwen short requests on L20." C8 TTFT enters the second range because client concurrency already exceeds the Engine's actual running slots, making queueing the dominant factor.

More critical is the capacity log:

| Version | Torch | KV Token Capacity | Mamba State Cache | Actual Running Slots |
| --- | --- | ---: | ---: | ---: |
| 0.5.16 | 2.11.0+cu129 | 181,320 | 33 | 6 |
| 0.5.17 | 2.11.0+cu129 | 158,375 | 29 | 5 |
| 0.5.18 | 2.13.0+cu129 | 178,120 | 32 | 6 |

v0.5.17's C8 throughput is 13.7% lower than v0.5.16 and 14.4% lower than v0.5.18, consistent with the direction of the 5/6 running-slot difference; single-request and C4 do not slow down correspondingly, indicating the issue is not a general regression in Decode kernels. Capacity metrics must be viewed together with throughput; otherwise, "fewer requests can be served simultaneously" can easily be misjudged as a per-request compute-power drop.

The "running slot" here is not a Pod, replica, or HTTP connection count, but the number of requests each Engine/DP Rank can keep active on the GPU at the same time. This Qwen3.8 model also needs to allocate Mamba/SSM State Cache per request; the log shows each request occupies 5 State Slots, so the actual concurrency is:

```text
v0.5.16: floor(33 / 5) = 6
v0.5.17: floor(29 / 5) = 5
v0.5.18: floor(32 / 5) = 6
```

The `max-running-requests=8` in the command line is only an upper bound; the Engine automatically lowers it based on State Cache and GPU memory budget to avoid OOM. Requests exceeding the actual running slots do not fail immediately but remain in the queue waiting, so TTFT degrades first, and system throughput also peaks at a lower concurrency. This is not "image files occupying GPU memory," but rather the different GPU memory allocation behavior of the SGLang, PyTorch, Kernel, and runtime components included in each image.

To forcibly increase the slot count, one could evaluate increasing the Mamba Cache budget, using a smaller Mamba State dtype, reducing context/KV usage, or improving GPU memory utilization; all of these options change the OOM and long-context boundaries and require re-running capacity tests, not just changing the declared concurrency to 8.

## 4. 4K Input: Throughput Unchanged, but Request-Level Tail Latency Increases

| Version | Round | Output tok/s | P95 TTFT | P95 TPOT | P95 ITL | Max ITL |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 0.5.16 | 1 | 44.04 | 5,902.98 ms | 60.91 ms | 50.46 ms | 1,944.61 ms |
| 0.5.16 | 2 | 43.91 | 5,921.20 ms | 60.60 ms | 50.01 ms | 1,877.49 ms |
| 0.5.17 | 1 | 44.12 | 5,819.91 ms | 71.45 ms | 48.67 ms | 3,121.59 ms |
| 0.5.18 | 1 | 44.33 | 5,790.50 ms | 70.88 ms | 48.31 ms | 3,109.77 ms |
| 0.5.18 | 2 | 44.42 | 5,784.71 ms | 71.06 ms | 48.29 ms | 3,072.33 ms |

All three versions have full-round throughput of about 44 tok/s, and v0.5.17/v0.5.18 even have slightly lower P95 TTFT; however, both versions' P95 TPOT is stable at about 71 ms, about 16%–18% higher than v0.5.16's two rounds at about 61 ms. Meanwhile, P95 ITL remains at about 48–50 ms, and the difference comes from a small number of longer pauses: Max ITL increases from about 1.9 seconds to about 3.1 seconds, which in turn raises the average TPOT of some requests.

Therefore, a more accurate statement is: **in the current 4K Prefill and Decode mixed shape, v0.5.17 onward shows a reproducible request-level tail-latency change, but overall throughput does not regress.** It may be related to Chunked Prefill/Decode scheduling interleaving, but these data alone cannot pinpoint a specific PR, nor can it be extrapolated to models without Mamba/hybrid architecture, different Chunk Sizes, or different concurrency.

## 5. Startup: "2.38×" Not Reproduced, but the Measurement Basis Must Be Separated

| Version | Weight Load | Decode Graph | Container to Internal Ready |
| --- | ---: | ---: | ---: |
| 0.5.16 | 24.90 s | 32.55 s | 125.57 s |
| 0.5.17 | 14.65 s | 32.82 s | about 131.00 s |
| 0.5.18 | 16.79 s | 30.88 s | 122.44 s |

Image pull takes about 3–4 minutes, but it belongs to image distribution and has been excluded from Engine startup time. Weight Load is significantly shorter for the latter two versions, but is affected by the ordering effect of the host page cache already being warm and cannot be attributed to the SGLang version; the more robust end-to-end metric is container startup to internal Warmup Ready, where the three versions differ by only about 9 seconds.

This also explains why the official 2.38× was not observed here: the official data comes from Qwen3-32B/H100 and explicitly enables Checkpoint Staging and CUDA Graph Capture Overlap; this test uses L20, a different model, and the default startup path.

## 6. v0.5.18 vs. v0.5.17: What Actually Changed

The main line of v0.5.17 is Kimi K3, MiniMax-H3 Day-0 support, the initial Rust Frontend version, the DCP communication backend, DWDP for MoE Prefill, and large-model loading and recovery optimizations. v0.5.18 does not continue along a single main line but spreads changes across the entire runtime chain.

| Dimension | v0.5.17 Highlights | v0.5.18 Highlights | Production Implications |
| --- | --- | --- | --- |
| New models | Kimi K3, MiniMax-H3, EmbeddingGemma, LFM2.5, etc. | Muse Glimmer, Intern-S2-Mobius, SANA-Video, LingBot-Video-MoE, LTX-2.5, Cosmos3, LongCat-Image | Autoregressive, multimodal, and Diffusion continue to converge into the same project |
| Startup | Large MoE H2D, Weight Cache Recovery | Checkpoint Staging overlaps with CUDA Graph Capture; unified Kernel Cache directory | Startup optimization shifts from point optimizations to stage overlap, but the first upgrade triggers recompilation |
| Decode | DCP, DWDP, MTP Host Overhead | TP LMHead All-to-All, FlashInfer MNNVL Pure Allreduce | Gains are highly dependent on DP-Attention, interconnect topology, batch size, and model architecture |
| P/D and caching | Numerous reliability improvements for NIXL, PP, DCP, HiCache | Mooncake Staging supports PP Prefill, NIXL Bootstrap Timeout, HiCache combined with speculative decoding/DCP enhancements | P/D is still evolving rapidly; upgrades must be regression-tested together with NIXL, Mooncake, and cache paths |
| Runtime | Initial Rust Frontend rollout | Rust Server adds native Qwen VL multimodal processing; Tracing v2 async export | Frontend refactoring is still in progress; not all Python paths can be assumed to be equivalently migrated |
| Dependencies | PyTorch 2.11, FlashInfer 0.6.15.post1 | PyTorch 2.13, Triton 3.7.1, FlashInfer 0.6.17, CuTeDSL 4.6.2 | It is not just swapping one SGLang wheel; AOT/JIT kernels and base images all change |

v0.5.17 reference: [SGLang v0.5.17 Release](https://github.com/sgl-project/sglang/releases/tag/v0.5.17).

## 7. What Exactly Is "2.38×" Faster At

### 7.1 Qwen3-32B: The Startup Path Is What Was Optimized

Officially measured on H100 with Qwen3-32B:

- Normal default path: 84.8 seconds;
- Serial path with coordinated prefetch enabled: 38.94 seconds;
- Checkpoint Staging with CUDA Graph Capture overlap: 35.6 seconds;
- 2.38× relative to the normal default path;
- 8.6%–11.7% faster than the serial path with Prefetch already enabled.

These numbers describe **startup time before API Ready**, not Output Token Throughput, TTFT, or TPOT. It requires explicit enabling:

```text
--startup-weight-load-mode overlap
```

The PR defines the B→C comparison of "serial prefetch → overlap" as the primary result of the new mechanism; the 2.38× from default serial → overlap also includes the existing benefit of coordinated prefetch, and that path is currently Opt-in. The official initial validation scope is Dense Llama/Qwen2/Qwen3, FP16/BF16, TP1/TP2, default Loader and mmap Safetensors, and cannot be directly extrapolated to MoE, FP8, or arbitrary loading backends.

If a model has already been resident for weeks, the 2.38× startup benefit has almost no direct impact on per-request throughput; if the platform frequently performs elastic scaling, rolling upgrades, or failure rebuilds, this optimization will significantly affect available capacity recovery time.

Implementation and data: [PR #32017](https://github.com/sgl-project/sglang/pull/32017).

### 7.2 DeepSeek-V4-Pro: Kernel 47% faster, end-to-end TPOT about 3.5% faster

In the DeepSeek-V4-Pro Decode path on B200, TP LMHead merges `allgather + scatter` into a single All-to-All:

| Metric | Before optimization | After optimization | Change |
| --- | ---: | ---: | ---: |
| LMHead | 320 μs | 169 μs | Down about 47.2% |
| TPOT | 36.97 ms | 35.67 ms | Down about 3.5% |

This precisely illustrates the difference between Kernel micro-benchmarks and end-to-end metrics. LMHead is only part of each Decode Step; even if the local latency is nearly halved, the overall TPOT does not decrease proportionally. This optimization targets the Pure-DP DP-Attention path and cannot be directly mapped to arbitrary TP configurations.

Implementation and data: [PR #32313](https://github.com/sgl-project/sglang/pull/32313).

### 7.3 DeepSeek-V4-Flash: "up to +6.9%" has three qualifiers

The official third set of data is DeepSeek-V4-Flash, TP=4, Blackwell, Decode small Batch, where FlashInfer MNNVL Pure Allreduce brings **up to** 6.9% benefit. The qualifiers cannot be removed:

1. The model is DeepSeek-V4-Flash;
2. The hardware is Blackwell supporting the corresponding MNNVL path;
3. The maximum benefit appears at small Batch.

The full Decode Batch Sweep in the PR better illustrates the meaning of "up to":

| Batch Size | Decode throughput change |
| ---: | ---: |
| 1 | +6.9% |
| 2 | +6.8% |
| 4 | +6.4% |
| 8 | +3.0% |
| 16 | +2.6% |
| 32 | +3.0% |
| 64 | -1.4% |

Therefore, this optimization is indeed effective at small Batch, but the benefit does not increase with higher concurrency; at least in this set of `one_batch` data, BS64 already shows a slight regression.

The Release notes state that this capability is automatically enabled for DeepSeek-V3/V3.2/V4, while other models require explicit parameters. This does not mean the same benefit will be obtained on H100, L20, AMD, or Ascend.

Implementation and data: [PR #30700](https://github.com/sgl-project/sglang/pull/30700).

## 8. Why "full model adaptation" needs to be downgraded one level

The v0.5.18 Release explicitly lists 7 new models:

| Model | Type |
| --- | --- |
| Muse Glimmer | Autoregressive, multimodal |
| Intern-S2-Mobius | Autoregressive |
| SANA-Video | Diffusion |
| LingBot-Video-MoE | Diffusion |
| LTX-2.5 | Diffusion |
| Cosmos3 Edge & Distilled | Diffusion |
| LongCat-Image | Diffusion |

It also adds Cookbook Recipes for Qwen3.8, Ling-3.0, Nemotron 3.5 Lightning, Dots3-Note, and DeepSeek-V4-Pro-0813. There are three different levels here:

```text
代码中出现 Model Class
        ↓
有官方 Cookbook 和已验证启动配置
        ↓
目标硬件、精度、上下文与 API 功能通过回归
```

"Adaptation code already exists in the repository" does not mean "all quantization artifacts, all hardware, and all API combinations have been validated." In particular, multimodal, Diffusion, LoRA, structured output, tool calling, speculative decoding, and P/D combinations must be individually accepted per target path.

The most direct compatibility entry point is the official [SGLang Cookbook](https://docs.sglang.io/cookbook), rather than guessing support based on model names.

## 9. Multi-hardware optimizations are real, but not capability alignment

The v0.5.18 Release categories simultaneously include NVIDIA, AMD/ROCm, Ascend NPU, CPU/Intel XPU, and Local/Desktop AI, indicating that SGLang is no longer developed solely around a single CUDA path.

| Backend | v0.5.18 visible direction | Conclusions that should not be inferred automatically |
| --- | --- | --- |
| NVIDIA | H100/B200/Blackwell, FA4, FlashInfer, MNNVL, DeepGEMM, NVFP4/MXFP8 | Any NVIDIA architecture supports the same Kernel with equivalent performance |
| AMD/ROCm | DeepSeek V4 CP, DSpark, Kimi K3, AITER/Triton, MXFP4 | ROCm and CUDA have fully identical parameters, precision, and performance |
| Ascend NPU | Kimi K3, DeepSeek V4 DSpark, MiniMax-M3 W8A8, MoE and quantization paths | CUDA Cookbook can be copied verbatim to NPU |
| CPU/Intel XPU | Gemma4 Xeon, Qwen3.5 CPU Kernel, DeepSeek V4 XPU Kernel | All GPU models are suitable for CPU online serving |
| MLX/Desktop | GPT-OSS MLX SWA, DGX Spark Inkling | Desktop backend is equivalent to data-center multi-node capability |

Therefore, "multi-hardware coverage continues to expand" is a reasonable summary; "multi-hardware full-domain optimization complete" would obscure the fact that the capability matrix remains asymmetric.

## 10. Five things more important than performance before upgrading

### 10.1 Upgrade PyTorch and Triton together

The CUDA runtime switches to PyTorch 2.13.0 and Triton 3.7.1, and the distribution methods for FlashInfer, CuTeDSL, SGL Kernel, and DeepEP also change. Production images need to be pinned as a whole; you cannot simply overlay-install `sglang` in an old image.

### 10.2 Kernel Cache directory migration

Triton, FlashInfer, Inductor, DeepGEMM, and CUDA Driver Cache are all migrated to `SGLANG_CACHE_DIR`. The official note explicitly reminds: the first startup after upgrade will recompile. If the platform has pre-warmed or mounted the old Cache directory, the path must be updated accordingly, otherwise first-startup data will be misjudged as performance regression.

### 10.3 torchao integration removed

`--torchao-config` has been deleted. Quantization deployments still relying on that path cannot upgrade directly.

### 10.4 Default behavior changes

MoE Deferred Finalize, Unified Cache out-of-window Slot release, and DeepSeek V4 fused paths become enabled by default; Diffusion Speed Mode's `torch.compile` changes to explicit opt-in. Identical default parameters do not mean identical execution paths.

### 10.5 Release still has Known Issues

The official notes record that one Kimi K3 fusion optimization and one AMD GLM-5.2 fusion optimization were rolled back before release; a v0.5.17 gRPC Request Lifecycle Tracking was also rolled back, and some NPU tests are temporarily disabled. Upgrade acceptance cannot only test health checks.

The full list is in [v0.5.18 Breaking Changes & Known Issues](https://github.com/sgl-project/sglang/releases/tag/v0.5.18#breaking-changes--upgrade-notes).

## 11. Can we conclude from this that SGLang is faster than vLLM

No.

The three sets of upstream Release data are all A/B comparisons of old vs. new paths within SGLang itself, not same-machine SGLang vs. vLLM comparisons. Previously, when we tested Qwen3.8-27B-FP8 on a single L20, SGLang v0.5.16 had better Output Throughput and TPOT at some concurrency levels, while vLLM 0.26.0 was better in some TTFT and high-concurrency scenarios; however, at that time the loading formats, CUDA Graph, and Running Slots on both sides were also not identical, so the report did not declare a "framework overall champion."

Similarly, the v0.5.18 H100 startup optimization cannot be placed on the same leaderboard as another framework's Decode throughput on L20. To perform a valid vLLM/SGLang comparison, at minimum the following must be fixed:

- The same model Revision, precision, and Tokenizer;
- The same machine, GPU topology, driver, and CUDA;
- The same maximum context, KV Cache precision, and GPU memory utilization;
- The same CUDA Graph, speculative decoding, Prefix Cache, and concurrency limits;
- The same set of Input/Output Length, concurrency, or arrival rate;
- The same cold-start, warm-start, and Shape Warmup states.

Existing measured reference: [Qwen3.8-27B Day 0: vLLM and SGLang test records](qwen38-27b-day0.md).

## 12. Recommended v0.5.17 → v0.5.18 Canary

```text
固定 v0.5.17 基线
  ├─ 正确性：Chat / Reasoning / Tool Call / Structured Output
  ├─ 性能：128/64、4K/128、长上下文、目标并发或到达率
  ├─ 启动：Cold / Weight Cache Hit / Kernel Cache Hit
  └─ 稳定性：30～60 分钟稳态、取消、超时、OOM 与恢复
                 ↓
同硬件、同权重切到 v0.5.18
                 ↓
先保持旧特性开关，再逐项打开 Overlap / 新 Kernel / 新 Cache 路径
```

It is recommended to record the following metrics:

| Stage | Metrics |
| --- | --- |
| Startup | Image Pull, Weight Load, Compile, CUDA Graph, API Ready |
| Prefill | TTFT, Input tok/s, Chunked Prefill, Prefix Cache Hit |
| Decode | TPOT, Inter-Token Latency, Output tok/s, Batch Size |
| Resources | HBM, Host Memory, CPU, PCIe/NVLink/RDMA, Cache Size |
| Stability | Failure rate, cancellation leaks, OOM, restart time, result consistency |

During acceptance, "framework upgrade benefit" and "benefit from explicitly enabling new optimizations" should be split into two experiments; otherwise a single variable cannot be rolled back.

## 13. Final judgment

SGLang v0.5.18 is worth following up on, especially for the following scenarios:

- Qwen/Dense model services with frequent scaling or high cold-start costs;
- Running DeepSeek V4 series on Blackwell, using DP-Attention, MNNVL, or new quantization Kernels;
- Building P/D, HiCache, speculative decoding, and multi-node parallel combinations;
- Needing the latest multimodal, video Diffusion, or heterogeneous hardware adaptation.

For this single-card L20 + Qwen3.8-27B-FP8 test, v0.5.18's short-request throughput is essentially flat compared to v0.5.16, and it fixes the high-concurrency capacity drop caused by v0.5.17 having only 5 running slots; however, the 4K request-level tail latency change that appeared since v0.5.17 still exists in v0.5.18. If the workload is primarily short conversations, the upgrade should not expect throughput to surge; if long prompts and Decode mixed workloads are heavy, Chunked Prefill scheduling should first be re-tested under the real arrival rate.

Therefore, it is not suitable for a full rolling upgrade just because of a claim of "inference speed surge." **First confirm whether the optimization applies to your own model, hardware, and request shape, then use a same-baseline Canary to decide whether to migrate. Upgrade acceptance should also separate "per-request speed" from "running slot/cache capacity"; otherwise, capacity-type regressions like v0.5.17 will be missed.**

## References

- [SGLang v0.5.18 Release](https://github.com/sgl-project/sglang/releases/tag/v0.5.18)
- [SGLang v0.5.17 Release](https://github.com/sgl-project/sglang/releases/tag/v0.5.17)
- [SGLang Cookbook](https://docs.sglang.io/cookbook)
- [Overlap Checkpoint Staging and CUDA Graph Capture: PR #32017](https://github.com/sgl-project/sglang/pull/32017)
- [TP LMHead All-to-All: PR #32313](https://github.com/sgl-project/sglang/pull/32313)
- [FlashInfer MNNVL Pure Allreduce: PR #30700](https://github.com/sgl-project/sglang/pull/30700)
