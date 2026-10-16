---
title: "Ling-3.0-flash BF16 Single-Node 4×H20 Field Test: Choosing Between SGLang, vLLM, and MTP"
date: 2026-09-03
authors:
  - runzhliu
categories:
  - Inference
  - Field Practice
description: "Deployed Ling-3.0-flash BF16 on a single node with 4×141GB H20, covering SGLang and vLLM deployment, functional acceptance, 256K long-context validation, and single-variable A/B testing of speculative decoding."
---

# Ling-3.0-flash BF16 Single-Node 4×H20 Field Test: Choosing Between SGLang, vLLM, and MTP

Ling-3.0-flash is a sparse MoE model released by inclusionAI. The official model card lists 124B total parameters with approximately 5.1B active parameters, using 512 routed experts with 8 experts activated per token, trained on a 256K context. The official vLLM Recipe describes it as approximately 5.5B active parameters with an additional 3.1B MTP parameters; the two upstream pages differ slightly in their active-parameter figures, so this article uniformly writes "approximately 5B active parameters." Model structure and weights follow the [official model card](https://huggingface.co/inclusionAI/Ling-3.0-flash).

This deployment used the full BF16 weights on a single node with 4×141GB H20, testing SGLang TP4 and vLLM TP4 separately, completing functional smoke tests, fixed-length stress tests, 32K–256K needle correctness validation, and a single-variable A/B comparison of SGLang NEXTN versus vLLM MTP under identical workloads.

Conclusions first:

- **For regular online workloads, SGLang is preferred.** Across ten comparison groups covering short requests C1–C16, 4K RAG C4/C8, 16K input C4/C8, and 1K decode C1/C8, SGLang led in output throughput in all cases, by 13.7%–36.5%.
- **Ultra-long context does not follow the short-request conclusion.** SGLang led output throughput by 20.1% and 13.7% at 32K and 64K; at 128K and 256K, vLLM overtook it by 10.2% and 12.6%. vLLM's low-concurrency TTFT was also generally lower.
- **Both engines passed the 256K correctness gate.** At 32K, 64K, 128K, and 256K with three needle depths each, both sides scored 12/12 PASS; thinking, disabled thinking, streaming, multi-turn, and tool call also all passed.
- **Speculative decoding should not be enabled globally by default.** NEXTN/MTP delivered roughly 52% improvement on long-output, low-concurrency decode, but regressed noticeably on high-concurrency short requests and some RAG cases; routing should be split by traffic type.

## Test Environment and Fairness Boundaries

| Item | SGLang | vLLM |
| --- | --- | --- |
| GPU | Single node 4×H20 141GB | Single node 4×H20 141GB, same spec |
| Weights / Precision | Ling-3.0-flash / BF16 | Same |
| Parallel topology | TP4 | TP4 |
| Max context | 262,144 | 262,144 |
| Runtime | `0.0.0.dev1+g0e5e40d8f` | `0.28.1rc1.dev278+g73029d424` |
| Image | `lmsysorg/sglang@sha256:687b721a…a4891f2` | `vllm/vllm-openai@sha256:38226e33…558183b` |
| Baseline speculative | Off | Off |
| A/B mode | NEXTN, 3 steps / 4 draft tokens | MTP, 3 speculative tokens |
| Prefix cache | Enabled; cleared before each official test round | Enabled; cleared before each official test round |
| Client | `vllm bench serve --backend openai` | Identical |

Weights were loaded directly from shared read-only storage; results were written to node-local temporary disk and reclaimed afterward, with no stress-test output written back to shared storage. Both engines used identical cases, input/output lengths, random seeds, clients, and repetition counts; fixed `request-rate=inf`, `random-range-ratio=0`, `temperature=0`, and `ignore-eos`. Except for the 256K capability probe, which ran one round, all official performance cases recorded three rounds, and the tables report the "median of per-round metrics," not the fastest single run. The four configurations totaled 9,022 successful requests with 0 failed requests.

This remains a **deployable recipe comparison**, not a pure kernel microbenchmark that fully isolates framework differences. The two runtimes use their own schedulers, attention/communication implementations, and development versions; conclusions apply only to the hardware, versions, and parameters explicitly stated in this article.

## Deployment Compatibility: vLLM Requires Nightly and Custom All-Reduce Disabled

SGLang natively recognizes the model using the development image for Ling. The vLLM stable image could not natively recognize `BailingMoeV3ForCausalLM` during preflight checks, so official testing switched to a nightly build with a fixed digest; this is consistent with the [official vLLM Ling-3.0-flash Recipe](https://github.com/vllm-project/recipes/pull/743/files) requiring nightly.

In this H20 environment, vLLM's default Custom All-Reduce initialization triggered CUDA `invalid argument`; adding `--disable-custom-all-reduce` allowed stable startup. To let both sides clear the prefix cache before official rounds, vLLM also enabled development mode and verified that the cache reset interface returned success. Early diagnostic rounds that were incompatible or failed to complete cache reset were not counted in official performance results.

## Functional and Long-Context Correctness: Both Engines Passed

Both services passed the following OpenAI-compatible capabilities:

- `/v1/models` returns the correct model;
- Default thinking and explicitly disabled thinking;
- Streaming responses and termination markers;
- Multi-turn conversation;
- Structured tool call.

Then four context tiers—32K, 64K, 128K, and 256K—were executed, with a unique needle placed at 10%, 50%, and 90% positions in each tier, requiring the model to return only the target string. Both engines scored **12/12 PASS**.

![Ling-3.0-flash functional and long-context correctness gate](../../assets/practices/ling3-flash-h20/correctness-gates.svg)

| Context / Needle depth | SGLang | vLLM |
| --- | ---: | ---: |
| 32K / 10%, 50%, 90% | 3/3 | 3/3 |
| 64K / 10%, 50%, 90% | 3/3 | 3/3 |
| 128K / 10%, 50%, 90% | 3/3 | 3/3 |
| 256K / 10%, 50%, 90% | 3/3 | 3/3 |
| Functional smoke | PASS | PASS |

Needle latency was used only to prove that requests actually executed, not for framework performance ranking: the cases ran serially, and service state and cache history could not be strictly aligned. Performance conclusions use only the controlled benchmark data below.

## Baseline Performance: SGLang Led Across All Regular Workloads

![Ling-3.0-flash SGLang vs vLLM baseline throughput](../../assets/practices/ling3-flash-h20/baseline-throughput.svg)

| Case | SGLang output tok/s | vLLM output tok/s | SGLang P50 TTFT | vLLM P50 TTFT | SGLang relative throughput |
| --- | ---: | ---: | ---: | ---: | ---: |
| Short 128→64, C1 | 205.31 | 180.61 | 102ms | 60ms | +13.7% |
| Short 128→64, C4 | 541.27 | 447.70 | 193ms | 138ms | +20.9% |
| Short 128→64, C8 | 908.74 | 743.59 | 201ms | 224ms | +22.2% |
| Short 128→64, C16 | 1,566.51 | 1,237.04 | 204ms | 241ms | +26.6% |
| RAG 4K→128, C4 | 470.41 | 345.08 | 485ms | 500ms | +36.3% |
| RAG 4K→128, C8 | 602.98 | 470.27 | 724ms | 829ms | +28.2% |
| Long 16K→256, C4 | 316.47 | 243.32 | 1.21s | 1.54s | +30.1% |
| Long 16K→256, C8 | 365.32 | 293.45 | 2.41s | 2.63s | +24.5% |
| Decode 128→1K, C1 | 290.03 | 212.48 | 101ms | 59ms | +36.5% |
| Decode 128→1K, C8 | 1,297.60 | 1,038.30 | 199ms | 222ms | +25.0% |

SGLang's advantage was mainly in sustained throughput and batching efficiency. vLLM was faster on time to first token for C1 Short and Decode, but still lagged in completing 1K decode; latency-sensitive workloads need to consider TTFT, TPOT, and E2E together—selection cannot rely on a single metric.

## 32K–256K: vLLM Throughput Overtakes After 128K

| Context, 128 output, C1 | SGLang output tok/s | vLLM output tok/s | SGLang P50 TTFT | vLLM P50 TTFT |
| --- | ---: | ---: | ---: | ---: |
| 32K | 91.65 | 76.32 | 1.19s | 1.46s |
| 64K | 59.63 | 52.46 | 1.65s | 1.76s |
| 128K | 81.49 | 89.81 | 1.00s | 664ms |
| 256K | 50.37 | 56.70 | 1.81s | 1.26s |

At 32K and 64K, each round contained multiple requests at different needle positions, so absolute values cannot be directly connected into a scaling curve with the single-request 128K/256K cases; they are suitable for comparing the two engines within the same row. The 128K and 256K results indicate that vLLM's recipe begins to win under ultra-long prefill. However, 256K ran only one round and should be treated as a capability probe and directional result, not a stable capacity-planning value.

## NEXTN / MTP: Clear Decode Gains, Possible Regressions on High-Concurrency Short Requests

![Ling-3.0-flash speculative decoding throughput change](../../assets/practices/ling3-flash-h20/speculative-delta.svg)

| Case | SGLang NEXTN vs Off | vLLM MTP vs Off |
| --- | ---: | ---: |
| Decode 128→1K, C1 | +52.8% | +51.8% |
| Decode 128→1K, C8 | +21.8% | +37.1% |
| RAG 4K→128, C4 | +5.7% | -19.3% |
| RAG 4K→128, C8 | -0.3% | -24.4% |
| Short 128→64, C1 | +19.7% | +29.8% |
| Short 128→64, C4 | -18.6% | +7.0% |
| Short 128→64, C8 | -40.4% | -8.8% |
| Short 128→64, C16 | -58.3% | -25.9% |

The common pattern across both implementations is clear: the longer the output and the lower the concurrency, the easier it is for speculative decoding to amortize verification costs; with very short outputs and very high concurrency, the extra draft/verify scheduling becomes a burden instead. We recommend splitting into at least two service classes: enable NEXTN/MTP for long-output agent or generation tasks, keep it Off for short conversations and high-concurrency RAG, and route by request characteristics at the gateway. Before production enablement, also collect acceptance length, GPU utilization, GPU memory, and power consumption to avoid optimizing token/s alone.

## How to Choose

- **Short conversations, RAG, high-concurrency agents:** Start with the SGLang baseline recipe; the throughput advantage is most stable.
- **Low concurrency with extreme emphasis on time to first token:** vLLM is worth validating first; C1 Short/Decode TTFT is lower.
- **128K–256K single requests:** vLLM was stronger in this round, but 256K needs more repetitions before making capacity commitments.
- **Long-output generation:** Both sides can enable speculative decoding; in this round, SGLang NEXTN had higher absolute throughput.
- **Mixed traffic:** Do not use a single global switch; split pools at minimum by "short output, high concurrency" versus "long output, low concurrency."

## Limitations

- Each engine was tested on only one 4×H20 node and one time window, without repetition across multiple machine groups;
- Data came from fixed-length random tokens and does not represent ShareGPT, real RAG, or production agent request distributions;
- Only BF16 TP4 was tested; FP8, different TP values, quantized KV cache, and higher concurrency were not covered;
- Both SGLang and vLLM are development/nightly versions; image digests must be pinned for reproduction;
- The 256K performance case ran only one round; conclusions should be treated as directional;
- Speculative acceptance length, GPU power consumption, and full GPU memory timing were not recorded, so strict energy-efficiency ranking is not possible;
- Weights were loaded directly from shared storage; startup time was not included in engine ranking.

## Reproduction Data

Public summaries and correctness evidence are located at `examples/ling3-flash-h20/results/2026-09-03-h20-bf16`. The directory retains median summaries for each official case, functional smoke, and needle JSONL; per-request raw responses and runtime logs are not included in the public repository to avoid publishing generated content, internal paths, and large volumes of duplicate data. Charts can be deterministically rebuilt from these public summaries using `examples/ling3-flash-h20/make_report_charts.py`.

## References

- [inclusionAI/Ling-3.0-flash model card](https://huggingface.co/inclusionAI/Ling-3.0-flash)
- [Ling official Cookbook](https://github.com/inclusionAI/ling-cookbook)
- [vLLM Ling-3.0-flash Recipe](https://github.com/vllm-project/recipes/pull/743/files)
