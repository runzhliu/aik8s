---
title: "MiMo-V2.6-Flash-RL Day 0: 4-Card and 8-Card H20-3e Deployment Field Test"
description: "MiMo-V2.6-Flash-RL model architecture, SGLang 8-card and vLLM 4-card deployment profiles, fixed-length stress testing, long-context boundaries, multimodal validation, and production deployment recommendations"
last_reviewed: 2026-09-23
---

# MiMo-V2.6-Flash-RL Day 0: 4-Card and 8-Card H20-3e Deployment Field Test

## 1. First, Get to Know MiMo-V2.6-Flash-RL

MiMo-V2.6-Flash-RL is an open-weight sparse Mixture of Experts (MoE) model released by XiaomiMiMo. The official description positions it as an efficiency-oriented checkpoint: **309B** total parameters, approximately **15B** activated parameters per Token, natively accepting text, image, video, and audio inputs, offering a **1M Token** context window, and licensed under MIT. [Official model card](https://huggingface.co/XiaomiMiMo/MiMo-V2.6-Flash-RL)

![MiMo-V2.6-Flash-RL model overview](../../assets/practices/mimo-v26-flash-rl-h20-day0/model-overview.png)

The structural aspects that most affect deployment are as follows:

| Structure | Official Configuration | Impact on Inference Service |
| --- | --- | --- |
| Sparse MoE | 309B total parameters, 15B activated parameters | Compute is smaller than total parameters, but all weights still need to be stored and participate in expert routing |
| Attention | 48 layers, of which 39 are sliding-window attention and 9 are global attention | Bottlenecks differ for short requests, long Prefill, and long Decode |
| Expert routing | 256 experts, Top-8 | Parallelism scheme, expert scheduling, and communication change card count and throughput |
| Multi-Token Prediction | 5-layer sliding-window MTP Drafter, predicting 7 Tokens at once | The engine must match the corresponding speculative decoding implementation; support cannot be judged from model format alone |
| Vision and audio | 681M vision encoder; audio Tokenizer and Patch Encoder | After text service starts successfully, media decoding, templates, and output semantics still need separate validation |
| Context | Official 1M Token | Service context is jointly determined by GPU memory, KV Cache, runtime implementation, and concurrency |

The service window for this test was set to 32,768 Tokens, with the longest formal input at 24,576 Tokens. The official 1M capability was not validated on this round of hardware configuration.

## 2. Two Deployment Profiles That Actually Ran

Two runnable configurations were obtained this time: SGLang using a single node with 8 H20-3e GPUs, and vLLM using a single node with 4 H20-3e GPUs. The two configurations differ in card count, parallelism strategy, and runtime implementation, so this article reports each deployment's own performance and resource density rather than interpreting the results as an engine ranking under identical conditions.

![SGLang and vLLM deployment profiles](../../assets/practices/mimo-v26-flash-rl-h20-day0/deployment-profiles.png)

| Item | SGLang | vLLM |
| --- | --- | --- |
| GPU | 1 node × 8×H20-3e | 1 node × 4×H20-3e |
| Parallelism | TP8, DP2, DP Attention, DP LM Head | TP4 |
| Service context | 32,768 Tokens | 32,768 Tokens |
| Max running requests | 64 | Runtime schedules based on 32K and GPU memory budget |
| GPU memory configuration | `mem-fraction-static=0.65` | `gpu-memory-utilization=0.90` |
| Prefill | Chunked Prefill 16,384 | Engine default chunked path |
| Prefix Cache | Disabled | Disabled |
| Tool protocol | MiMo reasoning/tool parser | MiMo reasoning/tool parser |
| MoE Kernel | FlashInfer MXFP4 | MiMo path in fixed supported branch |

Both containers requested 64 CPU and 512 GiB memory, with GPU limits of 8 cards and 4 cards respectively. The model was loaded directly from shared read-only storage. Prefix caching was not enabled during stress testing, to avoid repeated synthetic inputs changing results due to cache hits.

## 3. Measurement Methodology

The core matrix covers four types of fixed-length requests:

| Scenario | Input / Output Tokens | Observation Focus |
| --- | ---: | --- |
| Short request | 1,024 / 128 | Throughput and queueing for online conversation |
| Long Prefill | 8,192 / 128 | Impact of long input on TTFT |
| Long Decode | 1,024 / 512 | Sustained generation throughput and TPOT |
| Long context | 24,576 / 128 | Boundary behavior within the 32K service window |

Each length is tested at C1, C8, and C32. C denotes the client concurrency cap; C1 runs 8 requests per round, C8 runs 16 requests per round, and C32 runs 64 requests per round. Each tier is warmed up first, then three formal test rounds are executed. Requests use fixed-length randomly synthesized Tokens, `temperature=0`, and `ignore_eos=true`, with the performance interface being the OpenAI-compatible `/v1/completions`.

A successful request must simultaneously satisfy HTTP success, non-empty output, complete end marker, valid usage, and target output length. Failed requests remain in the original denominator; the throughput, TTFT, and TPOT in the tables are the medians of metrics across all valid rounds. If a round contains failures, it does not enter the performance median, but its completion count still enters the success rate statistics.

- **Output throughput**: Output Tokens produced by successful requests ÷ total round duration.
- **TTFT** (Time to First Token): From request dispatch to the first non-empty output fragment.
- **TPOT** (Time per Output Token): Average generation time per output Token after the first output fragment; the tables report the P95 of request-level TPOT.
- **E2E** (End-to-End Latency): From request start to full stream completion.

## 4. Text, Tools, and Vision Must First Clear the Hard Gate

Both engines passed model ID, arithmetic, multi-turn memory, streaming integrity, tool calling, single-image, and dual-image sequential validation. Length calibration was also performed separately before the performance matrix began.

Some actual Prompts are as follows:

| Capability | Prompt / Operation | Validation Point |
| --- | --- | --- |
| Arithmetic | `计算 17 加 25，只回答数字。` | Final answer is 42 |
| Multi-turn | `Remember code 482619.` → `What was the code? Reply only with the code.` | Second turn accurately returns 482619 |
| Tool | `Use get_weather to look up weather in Beijing. Do not invent the weather.` | Tool name, arguments, and simulated result are correctly fed back |
| Single image | `Name the main vegetable shown. Reply with one English noun only.` | Official carrot and corn samples are each recognized correctly |
| Dual image | `Name the main vegetable in each image in order. Reply as two English nouns separated by a comma.` | Answer changes accordingly when image order is swapped |
| Video | `List the three background colors in the order they appear.` | vLLM inference recognizes blue, green, and red; no final field generated within the 256-Token cap |
| Audio | `What verification code is spoken? Reply with digits only.` | Current vLLM request returns an unsupported audio file error |

The video sample shows that visual temporal information entered model inference, but the final response did not satisfy the success condition because it hit the output cap; the audio interface returned HTTP 400. Image passing cannot substitute for video and audio passing, so this round's public conclusions are limited to text, tool, and image capabilities being validated.

## 5. Core Performance Results

![Output throughput for three load types](../../assets/practices/mimo-v26-flash-rl-h20-day0/core-throughput.png)

### 5.1 Short Requests: 8-Card Has Higher Total Throughput, 4-Card Has Higher Resource Density

In the 1K/128 C32 scenario, SGLang total output throughput was **970.41 Token/s** and vLLM was **657.72 Token/s**. Simple division by allocated card count gives approximately **121.30** and **164.43 Token/s/GPU** respectively. This per-card value describes the resource density of the current deployment profile and includes TP/DP, scheduling, and Kernel differences; it does not equal standalone single-card inference performance.

| Input/Output | Concurrency | SGLang 8-Card Token/s | vLLM 4-Card Token/s | TTFT P95 seconds: S / V | TPOT P95 ms: S / V |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1K/128 | C1 | 76.93 | 156.83 | 0.120 / 0.170 | 12.34 / 5.13 |
| 1K/128 | C8 | 490.27 | 469.43 | 0.588 / 0.872 | 12.05 / 15.66 |
| 1K/128 | C32 | 970.41 | 657.72 | 2.141 / 3.227 | 21.67 / 41.89 |
| 8K/128 | C1 | 57.59 | 85.49 | 0.651 / 0.842 | 12.62 / 5.18 |
| 8K/128 | C8 | 169.39 | 132.02 | 4.477 / 6.405 | 33.65 / 49.37 |
| 8K/128 | C32 | 223.99 | 144.38 | 15.037 / 23.752 | 126.43 / 198.48 |
| 1K/512 | C1 | 78.35 | 183.30 | 0.118 / 0.169 | 12.66 / 5.14 |
| 1K/512 | C8 | 609.87 | 653.82 | 0.539 / 0.874 | 12.29 / 12.00 |
| 1K/512 | C32 | 1,528.83 | 1,042.44 | 1.915 / 3.221 | 18.60 / 28.93 |

vLLM's 8K/C32 completed 63/64 in the first round and 64/64 in the remaining two rounds, for a three-round total of **191/192**; the performance median in the table uses only the two complete rounds. All other formal requests in the table above completed fully.

The core matrix recorded **824/848** formal requests completed for SGLang, with all 24 failures coming from 24K/C8; vLLM completed **1,055/1,056**, with the only failure coming from 8K/C32.

### 5.2 Long Context: Latency Amplifies Rapidly Under Concurrency

![24K long-context boundary](../../assets/practices/mimo-v26-flash-rl-h20-day0/long-context.png)

| Engine | Concurrency | Completed/Requests | Output Token/s | TTFT P95 | TPOT P95 | E2E P95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| SGLang 8-Card | C1 | 24/24 | 36.92 | 1.883 s | 12.70 ms | 3.484 s |
| SGLang 8-Card | C8 | 8/32 | — | — | — | — |
| SGLang 8-Card | C32 | Not executed | — | — | — | — |
| vLLM 4-Card | C1 | 24/24 | 38.83 | 2.638 s | 5.33 ms | 3.309 s |
| vLLM 4-Card | C8 | 48/48 | 47.46 | 19.543 s | 137.63 ms | 28.876 s |
| vLLM 4-Card | C32 | 192/192 | 49.32 | 74.423 s | 592.72 ms | 148.263 s |

SGLang's 24K/C8 was executed for two rounds, with only 4/16 requests completing in each round, after which it stopped per the staged protection condition; C32 was not executed. vLLM's 24K/C32 completed fully, but the P95 time to first Token was approximately 74.4 seconds and the full stream approximately 148.3 seconds, already beyond the waiting range of typical interactive applications. Production capacity should limit long-input concurrency based on business latency targets, rather than only looking at whether requests ultimately complete.

## 6. SGLang Fixed Arrival Rate Scan

The rate-limited scan used the SGLang 8K/128, C32 calibration point of 1.7499 req/s, forming three arrival rate tiers at 0.5×, 0.8×, and 1.1×. Each tier ran three rounds, executing 600, 756, and 1,041 requests respectively, for a total of **2,397/2,397** completed.

![SGLang fixed arrival rate scan](../../assets/practices/mimo-v26-flash-rl-h20-day0/sglang-slo.png)

| Tier | Median Achieved Request Rate | P95 TTFT | P95 TPOT | P95 E2E |
| ---: | ---: | ---: | ---: | ---: |
| 0.5× | 0.866 req/s | 1.939 s | 54.49 ms | 7.821 s |
| 0.8× | 1.379 req/s | 3.554 s | 194.77 ms | 27.141 s |
| 1.1× | 1.644 req/s | 26.851 s | 287.67 ms | 53.107 s |

When the request rate increased from 0.8× to 1.1×, the actual completion rate only increased by about 19%, while P95 TTFT expanded from 3.55 seconds to 26.85 seconds. This inflection point is suitable for setting admission and queueing caps. The three tiers are experimental axes relative to this calibration point and do not represent production capacity percentages.

vLLM's execution package for this round did not carry a shared rate-limiting reference, so this phase was skipped per the rules, without fabricating symmetric data against SGLang.

## 7. GPU Resource Curves

Below are real light-theme dashboards corresponding to the formal test time windows. The SGLang chart covers the 8-card service, and the vLLM chart covers the 4-card service; the gaps and utilization dips in the charts correspond to phase switches and service wind-down.

![SGLang eight-card resource curves](../../assets/practices/mimo-v26-flash-rl-h20-day0/grafana-sglang-light.png)

SGLang's eight-card GPU memory stabilized at approximately 109–110 GB, each card's utilization reached 100% during core phases, power consumption in the high-load range was approximately 300–400 W, and peak temperature was approximately 60℃. This is a 30-second sampling resource curve and cannot replace finer-grained Kernel Profiling.

![vLLM four-card resource curves](../../assets/practices/mimo-v26-flash-rl-h20-day0/grafana-vllm-light.png)

The vLLM four-card service had a GPU utilization peak of 100%, peak GPU memory usage of approximately 131 GB, single-card peak power of approximately 402 W, and peak temperature of 57℃. The screenshot uses a retained absolute time window; internal node addresses have been removed from the title and description.

## 8. OpenWebUI Integration

The service was registered to the existing OpenWebUI via an OpenAI-compatible connection. The image below is a real screenshot of the connection management page; the internal gateway address was redacted at the browser screenshot stage, and the online configuration was not modified.

![OpenWebUI registration entry](../../assets/practices/mimo-v26-flash-rl-h20-day0/openwebui-registration-light.png)

OpenWebUI registration only proves that the entry configuration exists. Model ID, streaming completion, final answers, multimodal content, and tool calls are still separately checked by API automated acceptance; the appearance of a model name in the UI cannot replace interface validation.

## 9. Deployment Recommendations

1. **Select the profile by resource target first.** The 4-card vLLM offers a smaller single-instance footprint and higher per-card throughput density; the 8-card SGLang achieves higher total throughput in C32 short-request and long-output scenarios. Online services should also include replica count, queueing, failure domains, and card price in the capacity model.
2. **Check GPU topology for both 4-card and 8-card configurations.** The 4-card setup should preferably land within the same high-speed interconnect domain; the 8-card TP8/DP2 setup also needs checks on expert communication, GPU Direct paths, and NCCL correctness. Kubernetes only guarantees allocation of the specified number of GPUs, not the optimal interconnect relationship.
3. **Include NUMA locality in acceptance criteria.** CPU tokenization, media preprocessing, Pinned Memory, and Host-to-Device copies access host memory. Even with good GPU interconnect, cross-NUMA CPU and memory access can still slow down the Prefill and multimodal paths.
4. **Set up a separate queue for long inputs.** Completion at 24K/C32 does not mean suitability for interactive use. Apply rate limiting by input length tier, set a maximum queueing time and cancellation mechanism, and avoid long Prefill occupying the entire running sequence.
5. **Build a separate baseline for cache configuration.** Prefix Cache is disabled in this round. If production traffic contains a large number of identical system prompts, a separate "cache-enabled" profile should be built, reporting hit rate, GPU memory usage, and miss performance, without mixing with no-cache results.
6. **Validate each modality type separately.** Images, video, and audio have different decoders, templates, and output limits. Video with correct intermediate inference can still fail due to truncated output; audio format errors should be counted separately as client-side or media-processing issues.
7. **Complete capacity steps before scaling to 1M.** Validate GPU memory, TTFT, request cancellation, and concurrency degradation curves step by step from 32K, 64K, and 128K before deciding whether to open longer windows.
8. **Use SLOs to control admission rather than chasing peak tok/s.** Monitor at minimum success rate, TTFT, TPOT, E2E, queue length, KV Cache utilization, GPU utilization, and power consumption simultaneously. When throughput plateaus while TTFT expands rapidly, rate limiting or scaling out should be applied first.

## 10. Conclusion

MiMo-V2.6-Flash-RL has been validated on H20-3e across two representative serving profiles. The 4-card vLLM completed the full core matrix under a smaller GPU footprint, reaching 657.72 Token/s at short-request C32; the 8-card SGLang reached 970.41 and 1,528.83 Token/s at short-request and long-output C32 respectively, and completed a three-tier fixed arrival-rate scan.

What truly affects production selection is resource footprint, latency inflection points, and request integrity. The clearest boundary currently comes from 24K inputs: vLLM can complete C32, but the wait is no longer suitable for most interactive applications; SGLang shows stable failures at C8, requiring separate investigation of runtime timeouts, scheduling, and the long-Prefill path. Text, tools, and images have passed; video and audio still need further convergence on interface and output budget.

## References

- [MiMo-V2.6-Flash-RL Model Card](https://huggingface.co/XiaomiMiMo/MiMo-V2.6-Flash-RL)
- [XiaomiMiMo MiMo-V2-Flash Code Repository](https://github.com/XiaomiMiMo/MiMo-V2-Flash)
- [SGLang Documentation](https://docs.sglang.ai/)
- [vLLM Documentation](https://docs.vllm.ai/)
