---
title: "GLM-5.3 Day-1 Benchmark: SGLang vs. vLLM Baseline on 8×H20"
date: 2026-08-30
authors:
  - runzhliu
categories:
  - Inference
  - Hands-on
description: "Baseline benchmark of GLM-5.3 native FP8 with SGLang/vLLM on a single node of 8×141GB H20, comparing output throughput, TTFT, TPOT, and end-to-end latency."
---

# GLM-5.3 Day-1 Benchmark: SGLang vs. vLLM Baseline on 8×H20

On 2026-08-30, I deployed GLM-5.3 native FP8 weights on the same single node of 8×141GB NVIDIA H20-3e using SGLang and vLLM respectively, and completed 9 Target-only baseline cases. Both engines were load-tested by the same `vllm bench serve` client, with each case run 3 times; this article uses the median of the three runs.

GLM-5.3 is a MoE text model with approximately 743B total parameters and 39B activated parameters, using DSA, 256 routed experts (8 activated per token), one native MTP layer, and a declared 1,048,576-token context. The default `zai-org/GLM-5.3` is the native FP8 checkpoint; BF16 weights are in a separate repository.

## Key Findings

- Both engines each produced 27 complete result files, 54 JSON files in total, with 7,680 completed requests and 0 failed requests;
- SGLang achieved higher output throughput in all 9 cases, 7.3%–57.4% higher than vLLM;
- For 128/64 short requests, SGLang's P50 TTFT was 46.0%–75.4% lower;
- For 4K/16K prefill, vLLM had lower P50 TTFT, but SGLang had better output throughput and P50 E2E;
- These results only represent the 128K Target-only baseline with MTP, Prefix Cache, HiCache, and Context Parallelism disabled, and do not represent the final ranking with each engine's best optimizations enabled.

## Test Environment and Methodology

| Item | Configuration |
| --- | --- |
| Model | `zai-org/GLM-5.3`, Native FP8, 141 Safetensors shards |
| GPU | Single node 8×NVIDIA H20-3e, 141GB per card, TP8 |
| Context | 131,072 tokens |
| SGLang | Pinned `linux/amd64` image Digest `sha256:bde16a…fd74bf`; archived version file is empty, so no semantic version is declared |
| vLLM | 0.28.0, pinned `linux/amd64` image Digest `sha256:2286e8…b06635` |
| KV Cache | SGLang uses Hopper default BF16; vLLM uses `auto` |
| Optimization switches | MTP, Prefix Cache, HiCache, Context Parallelism all disabled |
| Client | Both sides uniformly use `vllm bench serve`, identical random request set and parameters |
| Statistics | 3 rounds per case, table takes per-metric median; fastest round is not selected |

## Baseline Benchmark Results

Throughput is Output Token Throughput. TTFT delta is computed per `(SGLang / vLLM - 1) × 100%`; negative values mean SGLang produces the first token faster.

| Case | SGLang output tok/s | vLLM output tok/s | Throughput delta | SGLang P50 TTFT | vLLM P50 TTFT | TTFT delta |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 128/64, C1 | 90.41 | 69.27 | +30.5% | 54.29ms | 210.45ms | -74.2% |
| 128/64, C4 | 288.50 | 183.33 | +57.4% | 98.30ms | 400.31ms | -75.4% |
| 128/64, C8 | 459.47 | 330.82 | +38.9% | 142.10ms | 392.56ms | -63.8% |
| 128/64, C16 | 656.41 | 601.02 | +9.2% | 210.48ms | 439.92ms | -52.2% |
| 128/64, C32 | 964.25 | 814.68 | +18.4% | 443.91ms | 821.37ms | -46.0% |
| 4K/128, C4 | 100.07 | 93.31 | +7.3% | 3,446.90ms | 2,752.07ms | +25.2% |
| 4K/128, C8 | 115.40 | 103.63 | +11.4% | 5,913.69ms | 1,902.32ms | +210.9% |
| 16K/256, C4 | 53.57 | 49.76 | +7.6% | 12,429.06ms | 10,464.75ms | +18.8% |
| 16K/256, C8 | 57.67 | 53.24 | +8.3% | 20,281.42ms | 12,540.84ms | +61.7% |

### Short Requests: SGLang Wins Both Throughput and First Token

![128/64 short-request output throughput](../../assets/practices/glm53-day1/short-throughput-median.png)

In the 128/64 cases, SGLang maintained higher throughput and lower TTFT from C1 to C32. At C32, output throughput reached 964.25 tok/s versus vLLM's 814.68 tok/s; P50 TTFT was 443.91ms and 821.37ms respectively. For chat and short agent calls, SGLang's advantage is clearest under this configuration.

![128/64 short-request P50 TTFT](../../assets/practices/glm53-day1/short-ttft-median.png)

### 4K/16K Prefill: vLLM Produces the First Token Earlier, SGLang Finishes Earlier

![P50 TTFT vs. P50 E2E trade-off in RAG scenarios](../../assets/practices/glm53-day1/rag-latency-tradeoff.png)

With 4K and 16K inputs, vLLM's P50 TTFT is lower, especially 4K/C8 at 1.90s versus 5.91s. However, at fixed output length, SGLang's decode is faster, and P50 E2E across the four RAG cases remains about 6.2%–10.6% lower than vLLM. Therefore, first-token-sensitive RAG interactions and batch processing that prioritizes total completion time/throughput may lead to different engine choices.

## Data Quality and Conclusion Boundaries

- All 54 result files are parseable; every case has 3 rounds, `failed=0`, and the error string is empty;
- SGLang's `short-128-64-c4` third round overlapped with an OpenWebUI request, and throughput was lower than the other two rounds; this article still takes the three-round median as pre-agreed, with the first two rounds at 288.93 and 288.50 tok/s respectively;
- SGLang's batch run was interrupted on first execution and resumed from the remaining cases; aggregation only includes the 27 rounds that wrote complete JSON, excluding unfinished rounds;
- Both services passed `/v1/models`, streaming/non-streaming Chat Completion, three reasoning levels, Tool Call, multi-turn dialogue, and error-input acceptance, and were connected to OpenWebUI during testing; functional responses are retained only in the internal audit archive, and a single smoke test does not substitute for production stability conclusions;
- After benchmarking, both workloads were scaled down to 0 and all 8 H20 GPUs were released; the OpenWebUI connection configuration is retained and can be reused for future scaling;
- MTP, FP8 KV, Prefix Cache, 32K–1M Needle, power consumption, and GPU memory curves are not yet included in this comparison.

Per-request raw JSON contains random prompts and generated text and is not publicly released. The repository provides a desensitized [per-case aggregated CSV](https://github.com/runzhliu/aik8s/blob/main/examples/glm53-day1/results/h20-fp8-baseline-median-20260830.csv) with throughput, P50/P95/P99 TTFT, TPOT, E2E, and request counts, so the tables in this article can be recomputed.

## Official Support Boundaries

| Route | Boundaries currently stated in official materials | Positioning in this round |
| --- | --- | --- |
| vLLM 0.28.0+ | Recipe explicitly lists single-node 8×H20/H200 141GB for FP8; full 1M context points to 8×B200 | Primary H20 validation route |
| SGLang `latest`/pre-release | Cookbook already supports GLM-5.3, DSA, MTP, Reasoning, Tool Call, HiCache, and Context Parallelism; hardware matrix lists H200 but does not name H20 | Hopper compatibility hands-on route; not documented as official H20 validation until Ready |

This differs from the Hy4-preview MXFP8/SM100 limitation. GLM-5.3's default FP8 weights can start from a single node of 8×141GB H20 without first preparing a BF16 dual-node setup.

## Reproduction Materials

This round of testing used a single node of 8×H20, TP8, and a 128K serving window, with MTP, Prefix Cache, HiCache, and Context Parallelism disabled. Both engines serially reused the same node, completing 27 baseline rounds each through the same client and case set; per-item configuration, sample counts, and statistical methodology are described above.

The [reproduction directory](https://github.com/runzhliu/aik8s/tree/main/examples/glm53-day1) provides pinned images, model pre-checks, functional acceptance, and benchmark scripts, with the results directory retaining public aggregated data. Unfinished optimization and long-context experiments are not included in this article's conclusions.

## Public Artifacts

Executable materials are in `examples/glm53-day1/`: image baselines, case matrix, weight pre-checks, functional smoke tests, benchmarks, Prefix Cache, and Needle. `results/` provides desensitized aggregated CSV; per-request raw results containing random prompts and generated text are retained only in the internal audit archive. The three figures in this article were generated by `scripts/generate_glm53_day1_assets.py` reading the public aggregated CSV directly.

## Further Reading: GLM-5.3-Flash Hands-on on 4×H20

This article tested the GLM-5.3 text model with approximately 743B total parameters and 39B activated parameters, establishing a 128K Target-only baseline on 8×H20 with TP8. A lighter GLM-5.3-Flash was also tested previously: approximately 320B total parameters and 18B activated parameters, on 4×H20 with TP4, natively supporting multimodal and 1M context.

In the Flash tests, both SGLang and vLLM completed near-1M-token cold prefill and Needle retrieval; vLLM was faster at high concurrency and 1K decode, while SGLang had a more complete functional loop for Reasoning, Tool Call, images, Prefix Cache, and OpenWebUI. Both engines exhibited tail latency from first-time JIT compilation on new shapes, so the same per-round archiving and three-round median approach was used rather than publishing only the best result.

Full results are available at:
[GLM-5.3-Flash Day 1 Hands-on: 4×H20 Deployment, 1M Context, and SGLang/vLLM Comparison](glm53-flash-day1-h20.md).

## References

- [GLM-5.3 Model and Weights](https://huggingface.co/zai-org/GLM-5.3)
- [SGLang GLM-5.3 Cookbook](https://docs.sglang.io/cookbook/autoregressive/GLM/GLM-5.3)
- [vLLM GLM-5.3 Recipe](https://recipes.vllm.ai/zai-org/GLM-5.3)
