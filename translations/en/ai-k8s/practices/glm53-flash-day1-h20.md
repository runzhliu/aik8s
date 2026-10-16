---
title: "GLM-5.3-Flash Day 1 Hands-on: 4×H20 Deployment, 1M Context, and SGLang/vLLM Comparison"
date: 2026-08-28
authors:
  - runzhliu
categories:
  - Inference
  - Hands-on
description: "Deploy GLM-5.3-Flash on 4×H20, and test SGLang and vLLM for functionality, throughput, long context, Prefix Cache, and OpenWebUI integration."
---

# GLM-5.3-Flash Day 1 Hands-on: 4×H20 Deployment, 1M Context, and SGLang/vLLM Comparison

The day after GLM-5.3-Flash was released, I used the official Native FP8 weights on 4×141 GB H20 GPUs to run both SGLang and vLLM dedicated preview images. The test did not stop at "Pod Running": I actually verified Reasoning, Tool Call, image input, OpenAI-compatible API, OpenWebUI, short-request throughput, 1K Decode, Prefix Cache, and near-1M-token cold Prefill and Needle retrieval.

Here are the conclusions first:

- **4×H20 can deploy the official FP8 checkpoint.** The weight GPU memory for both engines is about 75 GiB per card, and with BF16 KV Cache there is still enough room to cover 1,048,576 tokens.
- **SGLang is the more complete Day-1 support path right now.** All functional smoke tests passed, it returns a separate `reasoning_content`, Prefix Cache evidence is complete, and it has been integrated with OpenWebUI for real conversations.
- **The vLLM dedicated preview image does run, and high-concurrency Decode is faster.** But the main-branch integration was not complete on the test day, and the startup logs still show gaps in Sparse MLA Prefill and H20 MoE tuning configuration; the preview API also has edge-case behavior in the Reasoning field and Cache streaming output.
- **Both engines completed near-1M-token requests and Needle retrieval.** SGLang succeeded on cold requests at 261K, 263K, and 289K, and this time the community-reported crash around 262K was not reproduced.
- **The JIT tail latency on first encounter with a new shape cannot be ignored.** If you only take the fastest round, the conclusion will be clearly distorted.

This is not a restatement of official documentation. The numbers below come from the same model and actual H20 services; per-round CSV and desensitized JSON are in the reproduction materials at the end.

## Why this model is hard in the "deployment chain"

GLM-5.3-Flash is a natively multimodal MoE with about 320B total parameters and 18B activated per token. The 45-layer text network mixes MLA, DSA, and KDA, includes 288 routed experts with 8 experts activated per token, and also has a native MTP draft layer. The official context limit is 1,048,576 tokens, and input supports text, images, and video.

This means that Transformers recognizing `glm5_next` does not mean the inference service is fully usable. Sparse MLA, KDA State, MoE Kernel, MTP, CUDA Graph, multimodal Encoder, and Cache Manager can all be independent failure points. For such a first-release model, the minimum is to answer three questions separately:

1. Can the weights and images start normally;
2. Are the API functions correct;
3. Is it stable under short requests, long context, and caching scenarios.

## Test environment and fairness boundaries

| Item | This configuration |
| --- | --- |
| Model | GLM-5.3-Flash Native FP8 |
| Model architecture | `Glm5NextForConditionalGeneration` |
| Weights | 62 shards, Index records 328,326,771,576 Byte |
| GPU | 4×NVIDIA H20 141 GB / per engine |
| Parallelism | TP=4; SGLang additionally EP=4 |
| KV Cache | BF16 |
| Context | 1,048,576 |
| MTP | Off, test Target-only baseline first |
| Driver | 580.126.20 |
| Repetitions | 3 rounds each for short load, 4K Prefill, and 1K Decode |

It should be noted: the two engines use **non-overlapping 4-card slices** on the same 8-card host, and vLLM load testing kept SGLang idle. This reduces machine and host environment differences and is suitable for Day-1 horizontal observation, but the host CPU, memory, and storage paths are still shared. It is not the gold-standard A/B of "serial re-test on the same GPU UUIDs," so this article does not interpret small differences as a general conclusion about the engines.

During testing, the official image's `linux/amd64` Digest was fixed to avoid mixing different implementations after upstream overwrote the tag:

| Engine | Actual version | Image Digest |
| --- | --- | --- |
| SGLang | `0.0.0.dev1+gf609d677b` | `sha256:0836f016...9188aaf` |
| vLLM | `0.1.dev20051+g487ecf187` | `sha256:2e771fa61...ab703` |

## How 4×H20 was deployed

### SGLang: TP4 + EP4, MTP off first

This SGLang run used DSA Attention, with TileLang for both Prefill and Decode, Triton for KDA Linear Attention, and DeepGEMM for MoE. Key configuration is as follows:

```text
TP=4, EP=4
FP8 Weight + BF16 KV Cache
DSA Prefill/Decode = TileLang
Linear Attention = Triton
MoE Runner = DeepGEMM
Max Running Requests = 32
Chunked/Max Prefill Tokens = 8192
MTP = Off
Reasoning Parser = glm45
Tool Parser = glm47
```

Why turn off MTP in the first round? Because MTP changes latency, Decode throughput, GPU memory, and CUDA Graph shapes at the same time. Getting the Target-only baseline first, then doing single-variable switches, tells you whether performance changes come from the model kernel or from Draft/Verify.

SGLang actual startup process:

| Stage | Measured |
| --- | ---: |
| Weight loading | 130.59 s |
| Weight GPU memory / GPU | 75.27 GiB |
| BF16 KV Cache / GPU | 19.93 GiB |
| KV Token Pool | 1,683,136 tokens |
| Container creation to service Ready | about 9 min 51 s |

The model also occupies the KDA/Mamba State Pool, so you cannot estimate GPU memory by just adding weights and KV Cache. After the service started, I kept `/health`, Readiness Probe, and a longer Startup Probe; for such a first-release large model, the default tens-of-seconds probes only cause meaningless restarts.

### vLLM: TP4 runs, but startup is heavier

vLLM also used TP4, FP8 Weight, BF16 KV Cache, 1M Max Model Length, and MTP Off. It eventually became Ready, but the startup logs gave several pieces of information that must be kept in the report:

| Stage | Measured |
| --- | ---: |
| Slowest rank weight loading | 365.69 s |
| Weight GPU memory / GPU | 75.65 GiB |
| KV Cache / GPU | 29.94 GiB |
| KV Token Pool | 2,735,415 tokens |
| DeepGEMM Warmup | 1,102 kernels, about 92 s |
| CUDA Graph Capture | 15 s / 0.95 GiB per card |
| Container creation to service Ready | about 12 min |

The default 10-minute Deployment Progress Deadline will first report a timeout, but the Pod does not crash; it becomes Ready normally after DeepGEMM and FlashInfer Autotune complete. Production YAML should relax the Progress Deadline and Startup Probe to 20–30 minutes, and use Readiness to control traffic, rather than seeing 10 minutes not Ready and repeatedly rebuilding the Pod.

Two other warnings are also critical: there is currently no MLA Prefill Backend adapted to this model, and Sparse MLA falls back to the Top-k MQA Path; the image also has no H20-specific FP8 MoE tuning configuration and uses the default. This does not affect the "it runs" conclusion, but it means the performance here is not vLLM's final ceiling on H20.

The public Kubernetes Deployment, Service, probes, and test scripts are at [`examples/glm53-flash-day1`](https://github.com/runzhliu/aik8s/tree/main/examples/glm53-flash-day1). The example only keeps the generic interface; actual storage, image sync, and ingress implementation are outside the scope of this article.

## Functional correctness: not just asking "hello"

| Capability | SGLang | vLLM preview image |
| --- | --- | --- |
| `/v1/models` | Pass | Pass |
| `reasoning_effort=low/high/max` | Pass | Pass |
| Separate `reasoning_content` | Yes | Not split, content still in the normal field |
| Structured Tool Call | Pass | Pass |
| Real image input | Pass | Pass |
| Video input | Not tested | Not tested |
| OpenWebUI real conversation | Pass | Not registered, temporary service released |

SGLang's OpenAI-compatible service has been integrated with OpenWebUI, and both the model list and real Chat return success. The value of this verification is not to prove the UI looks good, but to confirm that cross-service access, model name, Chat Template, Parser, and streaming responses work together.

vLLM correctly completes Reasoning requests, but does not split the thinking process into a separate `reasoning_content`. Therefore, "request returns 200" and "frontend can display Reasoning as expected" are still two different things.

## Short-request throughput: beyond the three-round median, also look at variance

Short load fixed input 128, output 64, using random token IDs, fixed length, no request rate limit. Each concurrency ran three rounds, and the chart uses the three-round median, not the best round.

![128/64 short-request three-round median](../../assets/practices/glm53-flash-day1/short-throughput-median.png)

| Concurrency | SGLang Output TPS | vLLM Output TPS | SGLang P95 TTFT | vLLM P95 TTFT |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 74.7 | 107.7 | 188 ms | 183 ms |
| 4 | 234.6 | 225.9 | 340 ms | 559 ms |
| 8 | 392.4 | 257.2 | 414 ms | 11.76 s |
| 16 | 572.2 | 735.8 | 428 ms | 565 ms |
| 32 | 847.1 | 1,156.9 | 1.10 s | 695 ms |

vLLM has higher stable throughput at concurrency 16/32, with three-round Output TPS at concurrency 32 of 1,145.4, 1,156.9, and 1,166.4. SGLang at concurrency 32 is 847.1, 842.4, and 853.5.

But at concurrency 4/8, you cannot just look at vLLM's fastest round. vLLM's three-round Output TPS at concurrency 8 is 162.2, 410.8, and 257.2; the first round has P99 TTFT of 23.43 seconds, and the third round still has P95 TTFT of 11.76 seconds. SGLang also saw about 10.9, 12.5, and 13.6 seconds P95 TTFT on first encounter with concurrency 4/8/16, then recovered to stable in the following two rounds. This matches the JIT compilation in both runtime logs.

The correct engineering conclusion is not "who is absolutely faster," but: the vLLM preview image shows higher concurrency throughput potential; SGLang is more stable after the first Shape Warmup. Before going live, you must include the actual business concurrency and length combinations in Warmup, and monitor P99, not just average TPS.

### 4K Prefill and 1K Decode

Three-round results for 4K input, 128 output, concurrency 4:

| Engine | Output TPS | P95 TTFT |
| --- | --- | --- |
| SGLang | 143.8 / 143.3 / 143.6 | 1.797 / 1.796 / 1.779 s |
| vLLM | 116.9 / 172.1 / 172.8 | 7.209 / 1.798 / 1.799 s |

The first round again shows the impact of Warmup. After removing the first new shape, vLLM has higher throughput, and both sides have essentially the same P95 TTFT.

The Decode test with 128 input and 1,024 output is clearer:

| Concurrency | SGLang Output TPS | vLLM Output TPS | SGLang P95 TPOT | vLLM P95 TPOT |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 92.3 | 148.5 | 10.71 ms | 6.56 ms |
| 8 | 461.0 | 685.0 | 17.19 ms | 11.47 ms |

In this MTP Off baseline, vLLM's Decode path advantage is clear. Whether it can offset the Warmup variance seen earlier depends on the real traffic distribution.

## 1M context: successful return does not equal correct retrieval

Long-context tests cleared the Prefix Cache each time, fixed output 128 tokens, concurrency 1. Both runtimes also ran 32K once extra: vLLM's first new-shape TTFT was 14.60 seconds, and after Warmup it was 3.43 seconds; the chart uses the latter and explicitly retains the exclusion note.

![Cold-cache long-context TTFT](../../assets/practices/glm53-flash-day1/long-context-ttft.png)

| Input tokens | SGLang TTFT | vLLM TTFT |
| ---: | ---: | ---: |
| 32,768 | 3.61 s | 3.43 s |
| 65,536 | 7.30 s | 8.29 s |
| 131,072 | 14.98 s | 13.99 s |
| 263,168 | 31.80 s | 29.57 s |
| 524,288 | 70.02 s | 65.95 s |
| 1,044,480 | 167.69 s | 160.96 s |

Both engines completed requests close to the native limit. More importantly, I placed unique identifiers at 10%, 50%, and 90% positions in the context and required the model to return them exactly:

- SGLang: 11/11 passed; three positions each at 32K, 128K, and 257K, and middle positions at 512K and near-1M;
- vLLM: 8/8 passed; three positions each at 32K and 257K, and middle positions at 512K and near-1M.

So the conclusion here is "cold request succeeded and the specified Needle is retrievable," not just HTTP 200. It still does not mean the model can perform complex reasoning on arbitrary 1M-long text; Needle is only the minimum correctness threshold.

### 262K risk boundary re-test

| Input tokens | SGLang TTFT | Result |
| ---: | ---: | --- |
| 261,120 | 31.47 s | Success |
| 263,168 | 31.80 s | Success |
| 288,768 | 35.16 s | Success |

After the test, the SGLang Pod still had 0 Restarts. This time the community-reported crash after cold Prefill at about 262K was not reproduced, but success on a single H20 configuration cannot declare the problem gone for all hardware, backends, and images.

## Prefix Cache: always look at both time and server-side metrics

Fixed about 4,400-token prompt, repeated exactly five times after the first cold request.

![Prefix Cache evidence](../../assets/practices/glm53-flash-day1/prefix-cache-evidence.png)

SGLang's evidence chain is complete: cold TTFT 456.7 ms, hot request median 198.2 ms, a 56.6% decrease; server-side Cache Hit Rate rose from 0 to 98.55%. This can be clearly documented as Prefix Cache taking effect.

The vLLM preview image's server-side Metrics also show hits: that round's Query Token increment was 26,472, Hit Token increment was 17,280, with an incremental hit rate of about 65.28%; cold E2E was 651.1 ms, hot E2E median was 296.5 ms. However, its Preview Completions API ignored `echo=false`, and some requests in the Chat streaming test had no visible first chunk content, making the TTFT measurement unreliable. Therefore, this article only publishes vLLM's E2E and server-side Metrics, and does not place that unstable TTFT and SGLang in the same bar chart.

This is also a common measurement error in public stress tests: writing `enable_prefix_caching` in parameters does not mean the cache actually hit; the client appearing faster may simply be a change in API return semantics. The two types of evidence must corroborate each other.

## How I would choose

If I had to provide an OpenAI-compatible service usable by the team on H20 today, I would first choose SGLang:

- The official Cookbook's hardware and Backend documentation is more complete;
- Reasoning, Tool Call, images, Cache, and OpenWebUI have been closed-loop verified in this environment;
- First-request tail latency for new shapes can be mitigated by Warmup covering the business matrix;
- This round's 1M and 262K boundary tests did not trigger restarts.

If the goal is to research high-concurrency throughput, I would keep the vLLM preview image and continue tracking it. The concurrency-32 and 1K Decode data is very attractive, but before main-repo support is merged, H20 MoE configuration is completed, and Sparse MLA Prefill and API boundaries stabilize, one should not equate this "it runs" directly with formal-version production readiness.

Whichever is chosen, on the Kubernetes side it is recommended:

1. Startup Probe and Progress Deadline should cover at least 20–30 minutes of cold start;
2. Only route traffic after Readiness succeeds; Liveness should not kill processes during the weight loading phase;
3. Pin image Digest, model Revision, and full startup parameters;
4. Use a real length×concurrency matrix for Warmup, and look at first-round P95/P99 separately;
5. For Prefix Cache, collect both client-side time and server-side Query/Hit Metrics.

## What this round did not prove

This round did not test video, MTP, P/D separation, RDMA, BF16 weights, nor multi-node. Random Token throughput tests only measure the Serving Path, not answer quality. TP4 data on H20 cannot be extrapolated to L20, Blackwell, ROCm, or different Runtime Commits.

The most valuable next round is a single-variable A/B of MTP Off/On, recording Acceptance Length, TTFT, TPOT, throughput, and GPU memory; then decide whether to continue testing P/D based on the real business shape, rather than stacking P/D and RDMA just for "more complex architecture".

## Reproduction materials

- [Examples and test scripts](https://github.com/runzhliu/aik8s/tree/main/examples/glm53-flash-day1)
- [Desensitized aggregated results JSON](https://github.com/runzhliu/aik8s/blob/main/examples/glm53-flash-day1/results/h20-fp8-summary-20260828.json)
- [Per-round Benchmark CSV](https://github.com/runzhliu/aik8s/blob/main/examples/glm53-flash-day1/results/h20-fp8-benchmark-runs-20260828.csv)

## References

- [GLM-5.3-Flash model card](https://huggingface.co/zai-org/GLM-5.3-Flash)
- [SGLang GLM-5.3-Flash Cookbook](https://docs.sglang.io/cookbook/autoregressive/GLM/GLM-5.3-Flash)
- [vLLM GLM-5.3-Flash Recipe](https://recipes.vllm.ai/zai-org/GLM-5.3-Flash)
- [vLLM GLM-5.3-Flash support PR #53906](https://github.com/vllm-project/vllm/pull/53906)
- [SGLang 262K cold Prefill issue #36550](https://github.com/sgl-project/sglang/issues/36550)
