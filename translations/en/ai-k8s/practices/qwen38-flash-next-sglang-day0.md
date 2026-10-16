---
title: "Qwen3.8-Flash-Next Day 0 Hands-On: Running Native 262K on 4×H20"
description: "Using the SGLang Day-0 official image and BF16/FP8 weights, validate the Qwen4 preview architecture, precision and capacity, 262K long context, PLE, MTP, long/short workload colocation, and framework support boundaries on 4×H20"
status: published
last_reviewed: 2026-08-27
---

# Qwen3.8-Flash-Next Day 0 Hands-On: Running Native 262K on 4×H20

On August 26, 2026, Qwen released Qwen3.8-Flash-Next and positioned it as an experimental preview of the Qwen4 architecture; SGLang provided a dedicated image and deployment Cookbook the same day. Within one day, I completed three real-world tests on Kubernetes: both the official FP8 and BF16 weights ran successfully on **4×141 GB H20** with TP4/EP4, with native 262,144-token context, Thinking, Tool Call, and image input all working; the official image could not run directly on **8×48 GB L20**, and only a compatibility patch replacing the QSA Decode Kernel could generate output, with performance having no production reference value.

H20 FP8 short-request output throughput scaled from 90.32 tok/s at concurrency 1 to 1,860.09 tok/s at concurrency 64; a single request near 262K completed successfully with a P95 TTFT of 19.16 seconds; the 4K shared system prompt scenario achieved a 50.2% cache hit rate. BF16 comparison showed that FP8 has 49.7% more Token Pool and 40.9% faster weight loading, but some Decode workloads were actually about 7%–8% faster on BF16. These conclusions come from local measurements and do not substitute official H200/B200 numbers.

Framework support must also be viewed with a timestamp: **as of August 27, 2026, SGLang already provides a Day-0 dedicated image, model implementation, and official launch recipe for Qwen3.8-Flash-Next; the vLLM stable release and main branch cannot yet deploy it directly, with model registration, PLE, and Qwen4 fused kernels still in open PRs.** This does not mean vLLM will never support it, but rather that the availability status of the two differed on the day this article was published.

## 1. Clarifying the Model Name and Scale First

The open-weight name is `Qwen/Qwen3.8-Flash-Next`, not the cloud-hosted Qwen3.8-Flash, nor the official Qwen4 release. Its Hugging Face configuration registers as:

```json
{
  "architectures": ["Qwen4ExpForConditionalGeneration"],
  "model_type": "qwen4_exp"
}
```

The parameter numbers may appear contradictory, but the counting scopes actually differ:

| Component | Parameter Count | Runtime Meaning |
| --- | ---: | --- |
| MoE language model body | 125B | Approximately 6B activated per Token |
| N-gram Embedding | 51B | Primarily lookup-based; can be offloaded to host memory via PLE Offload |
| Main Serving Body | ~176B | Sum of body and N-gram Embedding |
| MTP | ~4B | One-layer multi-token prediction module built into the checkpoint |

The BF16 weight index is 359,999,963,128 Bytes, approximately 335.28 GiB; this article uses the official FP8 checkpoint, with 131 Safetensors shards totaling 185,502,232,570 Bytes, approximately 172.76 GiB. This is still a very large model and must not be estimated as a 6B model for GPU memory just because "6B is activated per Token."

The three most noteworthy architectural points are:

- The 48 language model layers repeat in a rhythm of three Gated DeltaNet layers followed by one Qwen Sparse Attention (QSA) layer;
- The four-branch Gated Residual uses data-dependent Read/Write Gates to control residual information flow;
- The 51B Bigram/Trigram Embedding adds local token combination information and allows GPU weight pressure to be reduced through PLE Offload.

QSA's goal is to change the growth curve of long-context Attention, so testing only 128 tokens cannot prove whether this architecture is meaningful. This article includes 32K, 64K, 128K, and near-262K in validation.

References: [Qwen model card](https://huggingface.co/Qwen/Qwen3.8-Flash-Next), [official release notes](https://qwen.ai/blog?id=qwen3.8-flash-next), [SGLang Cookbook](https://docs.sglang.io/cookbook/autoregressive/Qwen/Qwen3.8-Flash-Next).

## 2. Experimental Environment and Boundaries

| Item | Measured Configuration |
| --- | --- |
| Checkpoint | `Qwen/Qwen3.8-Flash-Next-FP8`, official FP8, 131 shards |
| GPU | 4×NVIDIA H20-3e, 143,771 MiB visible GPU memory per card, SM90 |
| Parallelism | TP4 / EP4, single node |
| Context | 262,144 tokens, no YaRN extension |
| Runtime | SGLang `0.0.0.dev1+gd91c3682b` |
| PyTorch / CUDA / Transformers | `2.13.0+cu130` / `13.0` / `5.12.1` |
| GDN Backend | FlashInfer for both Prefill and Decode |
| Mamba State | BF16 on the normal path; FP32 for MTP compatibility re-test |
| PLE | N-gram Embedding Offload enabled |
| API | OpenAI-compatible `/v1` |

The NVIDIA validation matrix published by SGLang at release is mainly H200, B200, B300, and GB300; H20 is not in the signed-off matrix. Therefore, this article can only state "successfully tested on H20" and cannot extrapolate that as official support. The L20 compatibility patch must not be compared against official kernel performance.

## 3. Startup Method

The public example retains core parameters and does not include any internal cluster, image registry, storage, or access endpoint details:

```bash
sglang serve \
  --model-path /models/Qwen3.8-Flash-Next-FP8 \
  --served-model-name qwen38-flash-next \
  --tp-size 4 \
  --ep-size 4 \
  --mem-fraction-static 0.85 \
  --chunked-prefill-size 8192 \
  --ple-offload-embedding \
  --linear-attn-prefill-backend flashinfer \
  --linear-attn-decode-backend flashinfer \
  --mamba-ssm-dtype bfloat16 \
  --reasoning-parser auto \
  --tool-call-parser auto \
  --enable-metrics
```

Without explicitly passing `--context-length`, the runtime reads the model's native 262,144. For the first attempt, it is recommended to use a single Pod with `restartPolicy: Never` as a Canary: if the GPU Device Manager reports an error during admission, the Deployment/ReplicaSet will keep creating replacement Pods, potentially accumulating hundreds of failed objects within minutes. Switch to Deployment only after the single Pod is healthy.

### Model Pre-check Must Not Just Count Shards

One real failure came from the version directory: the weight synchronization tool placed the full checkpoint in a version subdirectory under the parent directory, and recursive counting still showed 131 shards and approximately 173 GiB, but when `--model-path` pointed to the parent directory, it could not read the same-level `config.json`, ultimately reporting `Should have a model_type key in config.json`.

The zero-GPU pre-check must validate the **exact directory** passed to `--model-path` for all of the following:

1. `config.json` and `model_type` in `architectures`;
2. Reference integrity of `model.safetensors.index.json` and the 131 shards;
3. Tokenizer, Chat Template, and Generation Config;
4. The Day-0 image actually registers `Qwen4ExpForConditionalGeneration`;
5. The CLI contains PLE, QSA/GDN Backend, TP/EP, and Parser parameters.

## 4. Startup and Resource Results

| Metric | 4×H20 FP8 Measured |
| --- | ---: |
| First node pulls 13.95 GB image | 130.42 s |
| Weight loading | 88.11 s |
| Decode CUDA Graph capture | 105.15 s |
| Engine Ready | 234.88 s |
| `max_total_num_tokens` | 3,680,256 |
| Per-card GPU memory used after stabilization | 127,280–128,070 MiB |
| Per-card headroom after stabilization | ~15.25 GiB |

There is also a cold-start phenomenon that is easy to misjudge: the P95 TTFT for the first round of short-request C4 was 2.69 seconds, and re-running with the original parameters dropped to 385 ms. Logs show that after the service reported Ready, one-time kernel compilation still fell into the first round of requests. Therefore, "first round after Ready" and "steady state" should be recorded separately, and one should not pick a better-looking number to cover the cold-state cost.

## 5. API Is Not Just `/health` Returning 200

| Use Case | Result | Observation |
| --- | --- | --- |
| `/v1/models` | Passed | Served Model name is fixed |
| Chat Completion | Passed | OpenAI-compatible response is normal |
| Thinking | Passed | `reasoning_content` and final `content` are distinguishable |
| Tool Call | Passed | Returns structured function names and arguments |
| Image Data URL | Passed | Can describe objective content in the test image |
| OpenWebUI | Passed | Can be selected directly after registering with the OpenAI-compatible Base URL |

The image test also exposed a semantic pitfall: with Thinking enabled and only 128 output tokens given, the accurate description was all written into `reasoning_content`, and the final `content` was empty. This is not a Vision failure, but the reasoning process consuming the entire output budget. UI-facing image requests should disable Thinking, or separate the reasoning budget from the final answer budget.

## 6. Benchmark Methodology

Both the short benchmark and the long-context benchmark uniformly use:

- The SGLang native Token-ID Endpoint, to avoid Chat Template changing input length;
- `random-ids` with the local Tokenizer, with fixed input/output lengths;
- `request-rate=inf`, with concurrency controlled by `max-concurrency`;
- `temperature=0`, with Cache Flush per round;
- The number of successful requests must equal the number issued;
- Kubernetes probes use TCP Socket and do not generate model requests.

The last point comes from real troubleshooting. The `GET /health` of this Day-0 image is not a pure state read, but triggers a 64-token generation. If used as a Readiness/Liveness Probe every 10 seconds, invisible requests get mixed into the load test, distorting server-side max concurrency, TTFT, and throughput. HTTP 200 does not mean the endpoint is side-effect free.

## 7. Short-Request Throughput

The workload is 128 input and 64 output tokens per request:

| Concurrency | Requests | Output tok/s | Median TTFT | P95 TTFT | P95 TPOT | P95 E2E |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 16 | 90.32 | 196.07 ms | 200.30 ms | 8.14 ms | 710.69 ms |
| 4 | 32 | 334.95 | 181.84 ms | 385.01 ms | 8.86 ms | 942.41 ms |
| 8 | 64 | 578.77 | 188.40 ms | 371.43 ms | 10.69 ms | 1,020.89 ms |
| 16 | 64 | 864.16 | 393.46 ms | 410.07 ms | 12.71 ms | 1,183.96 ms |
| 32 | 128 | 1,393.73 | 440.42 ms | 452.25 ms | 16.61 ms | 1,484.50 ms |
| 64 | 256 | 1,860.09 | 646.43 ms | 1,323.93 ms | 28.77 ms | 2,896.71 ms |

![4×H20 FP8 short-request output throughput](../../assets/practices/qwen38-flash-next-sglang/short-throughput.svg)

Throughput keeps growing from C1 to C64, but tail latency at C64 has clearly deteriorated. Capacity planning should not treat 1,860 tok/s as the default concurrency for all workloads; interactive Chat is more likely to find a balance between C16–C32 based on TTFT SLO.

## 8. Long Context and Long Output

### 8.1 Single-Concurrency Prefill Curve

| Input / Output | Requests | Input tok/s | P95 TTFT | P95 TPOT | P95 E2E |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 4K / 128 | 4 | 2,722.55 | 253.72 ms | 9.83 ms | 1.50 s |
| 32K / 128 | 4 | 10,668.22 | 1.86 s | 9.88 ms | 3.07 s |
| 64K / 128 | 4 | 13,159.32 | 3.72 s | 9.92 ms | 4.98 s |
| 128K / 128 | 2 | 14,227.63 | 7.95 s | 9.95 ms | 9.21 s |
| 261,120 / 128 | 1 | 12,748.52 | 19.16 s | 10.27 ms | 20.47 s |

![4×H20 FP8 single-concurrency long-context TTFT](../../assets/practices/qwen38-flash-next-sglang/context-ttft.svg)

Native 262K does run successfully, but "fits in" does not equal "suitable for online interaction." Near 262K, the first token waits about 19 seconds, while Decode still maintains about 10 ms/Token, with the main cost falling on Prefill. Long-context capacity, TTFT SLO, and call frequency must be evaluated separately.

High-concurrency long context also shows batching gaps: at 64K, C4, the P95 TTFT is 14.35 seconds, and P95 TPOT is pulled up to 90.40 ms; this does not mean the single-request Decode Kernel suddenly became nine times slower, but rather that the TPOT statistic includes the request's waiting time in continuous batching. When comparing kernels, look at C1; when evaluating online experience, look at multi-concurrency E2E.

### 8.2 1K Long Output

| Concurrency | Input / Output | Requests | Output tok/s | P95 TTFT | P95 TPOT | P95 E2E |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 128 / 1,024 | 4 | 114.11 | 205.14 ms | 8.57 ms | 8.97 s |
| 8 | 128 / 1,024 | 16 | 702.56 | 385.49 ms | 11.19 ms | 11.82 s |

Long output observes Decode throughput more stably than 64 tokens, and avoids amplifying startup jitter with extremely short samples.

## 9. Shared Prefix: Can the Cache Benefit Be Quantified

I constructed 4 system prompt groups, each with 8 requests; each request contains approximately 4K of shared system prompt, a 128-token independent question, and a 64-token output, compared against 4,224-token random independent input:

| Scenario | Total Input Tokens | Duration | Input tok/s | Output tok/s | P95 TTFT | P95 E2E |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Random independent inputs | 135,168 | 11.10 s | 12,174.35 | 184.46 | 2.28 s | 3.06 s |
| 4 groups with shared prefix | 144,808 | 7.15 s | 20,243.86 | 286.31 | 1.09 s | 1.82 s |

![Shared prefix vs. random input comparison](../../assets/practices/qwen38-flash-next-sglang/shared-prefix.svg)

The server reported 72,640 Device Cached Tokens, a cache hit rate of 50.2%. The shared-prefix group actually had slightly more input tokens, so this is not a token-for-token identical microbenchmark; but total duration dropped 35.6% and P95 TTFT dropped 52.4%, so the direction is very clear. Unified system prompts, long-document Q&A, and multi-turn agents will benefit more from Radix Cache than fully random requests.

## 10. Fixed arrival rate: a sprint cannot masquerade as a capacity curve

To get closer to online traffic, I ran a first round of 128-input, 64-output tests with Poisson Arrival. Each tier had only 64 requests, and the client concurrency cap was 64:

| Offered Rate | Achieved Rate | Output tok/s | Avg. concurrency | P95 TTFT | P99 TTFT |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 2 req/s | 2.08 req/s | 133.41 | 2.66 | 494 ms | 591 ms |
| 4 req/s | 4.03 req/s | 258.13 | 8.89 | 782 ms | 957 ms |
| 8 req/s | 7.22 req/s | 462.10 | 35.79 | 970 ms | 1.17 s |
| 16 req/s | 11.95 req/s | 764.53 | 42.61 | 2.90 s | 3.34 s |
| 24 req/s | 15.24 req/s | 975.36 | 45.63 | 1.88 s | 2.31 s |
| 32 req/s | 17.87 req/s | 1,143.50 | 47.71 | 1.53 s | 1.95 s |

The tail latency at 16, 24, and 32 req/s did not rise monotonically, which must not be read as "higher traffic is actually faster." The reason is that each tier had only 64 requests, so the test included a pronounced tail drain phase; the higher offered rates were also not actually sustained. Its value is in demonstrating that an online arrival process and a one-shot burst from `request-rate=inf` are not the same problem, and in finding that beyond 8 req/s the client could no longer deliver at the configured rate. The formal SLO curve should still extend each tier to 10–30 minutes and record queue depth, error rate, and GPU metrics in parallel.

## 11. Long/short colocation: short-request P95 TTFT amplified 9.9×

This group is closer to a production incident: two long requests with 65,536 input and 128 output tokens ran in the background, while the foreground continued sending 64 short 128/64 requests at 4 req/s.

| Short-request scenario | P95 TTFT | P99 TTFT | P95 TPOT | P95 E2E |
| --- | ---: | ---: | ---: | ---: |
| Standalone | 782 ms | 957 ms | 52.79 ms | 3.77 s |
| With 64K Prefill overlaid | 7.75 s | 7.87 s | 150.19 ms | 10.73 s |
| Change | **9.9×** | 8.2× | 2.8× | **2.85×** |

![Impact of long Prefill on short-request tail latency](../../assets/practices/qwen38-flash-next-sglang/qwen38-flash-next-h20-mixed-workload.png)

This shows that a long Prefill in a single instance creates pronounced head-of-line interference for interactive requests. Even if the model can accommodate 262K, that does not mean long-document requests should enter the same undifferentiated queue as short chat requests. In production, at minimum the pool should be split by prompt length; further options include priority scheduling, Prefill/Decode separation, or a dedicated long-context instance.

## 12. 250K is not just about "finishing"; information must be retrievable

Random-token stress testing only verifies capacity and speed. I added a Needle-in-a-Haystack smoke test with exact Tokenizer counting: in Chat Prompts of 32,768, 131,072, and 250,000 tokens, a random Key was placed at the 10%, 50%, and 90% positions respectively; the cache was cleared before each request.

| Input length | Needle position | Correct / total | Per-run duration range |
| ---: | --- | ---: | ---: |
| 32,768 | 10% / 50% / 90% | 3 / 3 | 2.02–2.03 s |
| 131,072 | 10% / 50% / 90% | 3 / 3 | 8.39–8.41 s |
| 250,000 | 10% / 50% / 90% | 3 / 3 | 18.90–18.91 s |

![Native long-context TTFT and 250K Needle results](../../assets/practices/qwen38-flash-next-sglang/qwen38-flash-next-h20-long-context.png)

9/9 passing shows that this FP8 path can still complete simple single-needle retrieval near the context limit. That does not mean complex long-document reasoning has passed: real evaluation still requires multi-needle, distractors, cross-section synthesis, and LongBench. The public script [`needle.py`](https://github.com/runzhliu/aik8s/blob/main/examples/qwen38-flash-next-sglang/needle.py) validates both the locally constructed length and the server-side Prompt token count, to avoid mistaking "character count" for "token count."

## 13. PLE and MTP: one trades for capacity, the other conditionally for speed

### 13.1 PLE Offload mainly increases capacity

Switching only PLE, keeping everything else at FP8, TP4/EP4, and 4×H20:

| Metric | PLE On | PLE Off | Change |
| --- | ---: | ---: | ---: |
| Weights per Rank | 32.20 GiB | 43.86 GiB | Saves 11.66 GiB |
| `max_total_num_tokens` | 3,680,256 | 3,178,560 | +15.8% |
| `max_running_requests` | 587 | 507 | +15.8% |
| C8 128/64 Output tok/s | 535.12 | 559.99 | Within sprint fluctuation range |
| C1 32K Input tok/s | 10,694.21 | 10,714.06 | Essentially identical |

After PLE places the roughly 51B N-gram Embedding into CPU Pinned Memory, each Rank uses 11.66 GiB less weight space, and the memory solver reallocates that space to Mamba/KV Cache. The differences in steady-state short requests and 32K Prefill are close to run-to-run fluctuation, so the main benefit in this configuration is roughly 15.8% more capacity, not a demonstrable throughput speedup.

### 13.2 MTP helps long generations, but is not a universal switch

The official SGLang low-latency recipe uses NEXTN, 3 speculative steps, and 4 Draft Tokens. On the first launch as-is on H20, GDN Target Verify reported:

```text
AssertionError: initial_state must be float32, got torch.bfloat16
```

After explicitly setting `--mamba-ssm-dtype float32`, it could start and complete generation. The Draft Head adds roughly 1.18 GiB per Rank, and the actual average acceptance length was 1.92–2.52.

| Input / Output | Concurrency | Normal path Output tok/s | MTP Output tok/s | Change |
| ---: | ---: | ---: | ---: | ---: |
| 128 / 64 | 1 | 90.32 | 137.60 | +52.3% |
| 128 / 64 | 8 | 535.12 | 278.27 | -48.0% |
| 128 / 1,024 | 1 | 114.11 | 180.32 | +58.0% |
| 128 / 1,024 | 8 | 702.56 | 823.35 | +17.2% |

![PLE capacity gain and MTP performance boundary](../../assets/practices/qwen38-flash-next-sglang/qwen38-flash-next-h20-ple-mtp.png)

Single concurrency and 1K long generations show clear gains, but 64 tokens at C8 actually regress. This is consistent with the vendor calling this parameter set the Low Latency Recipe: speculation, verification, and scheduling have fixed costs that cannot be amortized when outputs are too short or the concurrency shape is unsuitable. MTP also fixes the maximum Running Request at 48 and changes SSM State precision from BF16 to FP32, so production adoption requires re-running A/B tests with the real output length and concurrency; the single-concurrency +58% must not be extrapolated to all traffic.

References: [SGLang Qwen3.8-Flash-Next official configuration source](https://github.com/sgl-project/sglang/blob/1c8f2b38cbb318cadb6e0b5cd7cc8ce6a3fc8209/docs/src/snippets/configs/Qwen/qwen3.8-flash-next.jsx), [SGLang Mamba Server Arguments](https://github.com/sgl-project/sglang/blob/main/docs/advanced_features/server_arguments.md).

## 14. BF16 vs. FP8: a capacity advantage does not mean throughput leads across the board

On the same 4×H20, SGLang, TP4/EP4, PLE On, MTP Off configuration, I restarted with the official BF16 Checkpoint as the only major variable and re-measured. Both paths use the same 0.85 Static Memory Fraction, so steady-state GPU memory usage is close; this only shows that the engine keeps giving the remainder to the cache and cannot be used to conclude that the two precisions have identical capacity.

### 14.1 Startup and capacity

| Metric | FP8 | BF16 | Observation |
| --- | ---: | ---: | --- |
| Weight loading | 88.11 s | 149.24 s | FP8 40.9% faster |
| Engine Ready | 234.88 s | 271.40 s | FP8 13.5% faster |
| Weights per Rank | 32.20 GiB | 60.44 GiB | FP8 uses 28.24 GiB less |
| `max_total_num_tokens` | 3,680,256 | 2,458,432 | FP8 has 49.7% more |
| `max_running_requests` | 587 | 392 | FP8 has 49.7% more |

FP8's deterministic benefits are very clear: the Checkpoint is roughly half of BF16, weight loading is faster, and more GPU memory is left for Mamba/KV State. Even though both reach a steady state near the 0.85 memory watermark, FP8 can hold roughly 1.22 million more tokens in the pool.

### 14.2 Typical workload A/B

| Input / Output | Concurrency | FP8 Output tok/s | BF16 Output tok/s | Observation |
| ---: | ---: | ---: | ---: | --- |
| 128 / 64 | 1 | 90.32 | 97.16 | BF16 +7.6% |
| 128 / 64 | 8 | 535.12 | 531.38 | Essentially tied |
| 128 / 64 | 64 | 1,860.09 | 1,999.76 | BF16 +7.5% |
| 128 / 1,024 | 1 | 114.11 | 123.43 | BF16 +8.2% |
| 128 / 1,024 | 8 | 702.56 | 750.18 | BF16 +6.8% |

For 32K input, 128 output, C1, Input Throughput was FP8 10,668.22 tok/s vs. BF16 10,329.37 tok/s, with FP8 about 3.3% higher; BF16 P95 TTFT was 2.06 s vs. FP8 1.86 s. The 250K single-needle test at the 10%, 50%, and 90% positions passed 3/3 for both precisions; BF16 took about 19.77 s per run, FP8 about 18.90 s.

![BF16 vs. FP8 startup, capacity, and typical throughput A/B](../../assets/practices/qwen38-flash-next-sglang/qwen38-flash-next-h20-precision.png)

These are short-duration synthetic A/B tests, not output-quality evaluations; the C8 FP8 value uses the steady-state re-measured 535.12 tok/s to avoid dressing up the 578.77 tok/s run-to-run fluctuation from another round as a precision difference. The conclusion that can be drawn today is: **FP8 clearly buys higher capacity and faster startup, but on this H20 Kernel path it does not comprehensively beat BF16 in Decode throughput.** Whether to adopt FP8 should consider single-instance capacity, TTFT SLO, the real input/output distribution, and quality evaluation — not just the precision name.

Machine-readable results are at [`h20-bf16-summary-20260827.json`](https://github.com/runzhliu/aik8s/blob/main/examples/qwen38-flash-next-sglang/results/h20-bf16-summary-20260827.json).

## 15. Why L20 cannot be treated as a formal performance path

The official Day-0 image fails directly on L20 (SM89): FlashInfer GDN requires SM90+; after switching to Triton GDN, linear attention can be passed, but the QSA FA4/CuTe path continues to report `unable to compute crd2idx`.

To determine whether the issue was weights or kernels, I made a compatibility patch: QSA Decode falls back per-request to PyTorch SDPA, with CUDA Graph disabled. 8×L20, TP8/EP8, 32K can generate correctly, but C1 128/64 reaches only 7.47 tok/s with P95 TPOT of 131.77 ms; this is a correctness proof, not SGLang's formal L20 performance. Public results must state both the patch and the disabled features; "L20 supported" alone is not acceptable.

## 16. SGLang already supports it; vLLM is still adapting

As of August 27, 2026, the framework status can be summarized as: **SGLang can be deployed directly with the official Day-0 image and recipe; vLLM stable and main branch cannot yet be deployed directly, community adaptation is in progress, and FP8 is not yet usable as formally supported.**

- [vLLM PR #53896](https://github.com/vllm-project/vllm/pull/53896) is adding `Qwen4ExpForConditionalGeneration`, model registration, tests, and FP8 quantization changes; status remains Open/Blocked;
- [vLLM PR #53899](https://github.com/vllm-project/vllm/pull/53899) implements PLE Offload separately; status Open, with conflicts on that day;
- [vLLM PR #53909](https://github.com/vllm-project/vllm/pull/53909) adds Qwen4 HyperConnection/QSA/PLE Triton Kernels; status remains Open.

So vLLM PR commits can be pulled for experiments, but that means maintaining a custom branch and should not be registered as a production stable model. This article chose SGLang not because vLLM can never support it, but because SGLang delivered a runnable model implementation, a dedicated image, PLE, the GDN/QSA Backend, and a startup recipe on the release day itself. This judgment only represents the upstream state as of August 27, 2026; subsequent PR merges and Release Notes should be the authority.

## 17. Integrating with OpenWebUI

SGLang exposes an OpenAI-compatible API; OpenWebUI does not need to understand QSA, PLE, or TP/EP. In the administrator's OpenAI-compatible Connections, fill in:

```text
Base URL: https://your-model-endpoint.example.com/v1
API Key: 由访问层配置
Model ID: qwen38-flash-next
```

Before registering, verify both `/v1/models` and one Chat Completion from the network where OpenWebUI runs. Verifying that the browser can open the entry point is not enough: the model service may be Ready, but cross-network routing, certificates, timeouts, or access control can still make the UI return 502.

## 18. Reusable Day-0 checklist

1. Pin model revision, image digest, and hardware architecture, not just tags;
2. Use zero-GPU Pods to verify the exact model directory and runtime model registration;
3. Use a single-Pod canary to avoid admission failures triggering a ReplicaSet storm;
4. After Ready, record the cold-start first round and the steady-state retest separately;
5. Check whether health probes invoke real inference;
6. API coverage at least includes Thinking, Tool Call, Vision, and error budget;
7. Performance coverage at least includes short input, high concurrency, long output, and native context boundaries;
8. For engines with prefix caching, add a shared System Prompt scenario;
9. Unofficial GPUs, patched kernels, and disabled optimizations must be written alongside the numbers;
10. UI integration is verified from the network where the UI resides; do not equate in-service self-tests with user reachability.

Public Kubernetes manifests, smoke test scripts, load test scripts, and structured results are at [`examples/qwen38-flash-next-sglang`](https://github.com/runzhliu/aik8s/tree/main/examples/qwen38-flash-next-sglang).

Further reading: [Qwen3.8-27B Day 0: vLLM and SGLang test records](qwen38-27b-day0.md), [Performance benchmarks and regression](../benchmarking.md)
