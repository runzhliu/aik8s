---
title: MiniMax-M3.1-Flash Day0 — vLLM and SGLang on eight H20-3e GPUs
description: vLLM and SGLang deployment of MiniMax-M3.1-Flash on eight H20-3e GPUs, with 132 formal performance rounds, million-token recall, actual resource curves and deployment recommendations.
created: 2026-10-24
updated: 2026-10-24
last_reviewed: 2026-10-24
---

# MiniMax-M3.1-Flash Day0 — vLLM and SGLang on eight H20-3e GPUs

## 1. Understand the model before deploying it

MiniMax officially released MiniMax-M3.1-Flash on **October 19, 2026**, and opened its weights on **October 23**. Day0 in this article refers to self-hosting tests following the weight release; the model launch and weight availability are separate milestones. [Official launch announcement](https://www.minimax.io/blog/minimax-m31f), [weight announcement](https://x.com/MiniMax_AI/status/2113436864904610008)

MiniMax-M3.1-Flash is a native multimodal Mixture of Experts (MoE) model. Its publisher reports approximately 428B total parameters and 23B active parameters, text, image and video inputs, text output, and a 1M-token context window. For an existing GPU fleet, weight formats, inference kernels and the actual cost of long-context caches matter alongside active parameter count. [Official model card](https://huggingface.co/MiniMaxAI/MiniMax-M3.1-Flash)

This test pins official weight revision `54e4e69dfc452b1e94a426c24a4fdeeaa8e3ad5e`. The outer configuration specifies `quant_method=mxfp8`; the expert configuration also contains `moe_quant_algo=NVFP4` and `moe_quant_format=nvfp4-pack-quantized`. Serving therefore needs to handle both MXFP8 and packed NVFP4 experts. [Pinned configuration](https://huggingface.co/MiniMaxAI/MiniMax-M3.1-Flash/blob/54e4e69dfc452b1e94a426c24a4fdeeaa8e3ad5e/config.json)

The index for the 48 main weight shards reports 250,103,411,200 bytes of tensor data, approximately 232.93 GiB. MoE activates only part of the parameters per token, but serving still needs to hold the complete weights. File size also excludes the runtime Key-Value Cache (KV Cache), index cache, workspaces and CUDA Graphs.

vLLM and SGLang each completed **66 formal performance rounds and 1,944 requests** on eight H20-3e GPUs: **132 rounds and 3,888 requests in total, with 0 failures**. Each engine also completed 7 long-context recall probes, including three inputs exceeding one million tokens. Both use the same weight snapshot and request set on different physical nodes; the following compares the concrete deployment configurations tested here.

## 2. vLLM environment and reproducible configuration

| Item | Tested configuration |
| --- | --- |
| GPUs | Single node, 8×H20-3e; 143,771 MiB reported per card; driver 580.126.20 |
| Interconnect and host topology | NV18 between every GPU pair; GPUs 0–3 associated with NUMA 0, and 4–7 with NUMA 1 |
| vLLM | 0.1.dev23341+g8744dd2fb.d20261022.cu134 |
| Dependencies | PyTorch 2.14.0+cu130; Transformers 5.19.0; FlashInfer 0.7.2 |
| Parallelism and expert backend | Tensor parallelism TP8; Marlin |
| Main performance configuration | Maximum context 32,768; maximum sequences 32; GPU memory utilization parameter 0.85 |
| Long-context configuration | Maximum context 1,048,576; maximum sequences 1 |
| Caches | FP8 KV and FP8 index caches; prefix caching disabled |
| Other settings | DSpark speculative decoding disabled; video input limit set to 0 |

The image is `vllm/vllm-openai:minimax-m31-flash`, pinned to amd64 digest `sha256:f5ec69891fb7b855762f40598eea1aa5cad6e4f2f0c2a2f81d270e2bdcd93632`. Development tags can change: check the digest and installed versions when reproducing the run. The Hopper configuration follows the official TP8, Marlin and FP8 cache recipe. [vLLM Recipe](https://recipes.vllm.ai/MiniMaxAI/MiniMax-M3.1-Flash)

H20 uses the Hopper architecture. This run processes packed expert weights with Marlin, and the logs identify the corresponding W4A16 path. That differs from native FP4 Tensor Core execution on Blackwell: the NVFP4 weight label alone does not identify the hardware arithmetic used.

The main serving command follows. `/model` is the model directory inside the container; the parser plugin at the end is explained below.

```bash
export LD_LIBRARY_PATH="/usr/local/cuda-13.4/compat:${LD_LIBRARY_PATH:-}"
vllm serve /model \
  --served-model-name MiniMax-M3.1-Flash \
  --host 0.0.0.0 --port 30000 \
  --tensor-parallel-size 8 \
  --reasoning-parser minimax_m3 \
  --tool-call-parser minimax_m3 --enable-auto-tool-choice \
  --block-size 128 --kv-cache-dtype fp8 \
  --attention-config '{"indexer_kv_dtype":"fp8"}' \
  --moe-backend marlin \
  --compilation-config '{"cudagraph_mode":"FULL_AND_PIECEWISE"}' \
  --max-model-len 32768 --max-num-seqs 32 \
  --gpu-memory-utilization 0.85 \
  --limit-mm-per-prompt '{"video":0}' \
  --disable-hybrid-kv-cache-manager \
  --no-enable-prefix-caching --no-enable-log-requests \
  --reasoning-parser-plugin /package/scripts/minimax-reasoning-plugin.py
```

The long-context stage restarts the service with `--max-model-len` set to `1048576` and `--max-num-seqs` set to `1`. The million-token result was not obtained with the 32-concurrency configuration. AllReduce numerical checks passed on all eight ranks; this establishes single-node communication correctness, not inter-node bandwidth.

## 3. Two vLLM deployment issues

### 3.1 Loading all weights does not guarantee Marlin repacking will work

The first startup read all 48 shards, then failed while repacking expert weights for Marlin because the PTX toolchain was unsupported. The image contains CUDA 13.4 components, while the process initially saw driver API 13.0. Completing weight loading was insufficient to establish that generation would work.

For diagnosis, the same repacking operation was reduced to a small GPU probe. It failed with the default library search path. Prepending the compatibility library directory in the image caused the process to load those libraries and report driver API 13.4; the same operation then passed. The formal vLLM run used that container configuration without changing the host driver.

This depends on the supported combination of GPU, host driver and compatibility package. Check the libraries actually loaded, then execute the required kernel. An environment variable alone is not a universal CUDA compatibility fix. [NVIDIA Forward Compatibility](https://docs.nvidia.com/deploy/cuda-compatibility/forward-compatibility.html)

### 3.2 Reasoning markers in the answer: inspect parser state initialization

After the second startup, basic answers and multi-turn recall passed, but the streaming interface placed reasoning markers and their contents into the answer while leaving the separate reasoning field empty. The failure came from this template/parser combination: the system prompt includes instructions describing reasoning markers, and the parser inspected the entire prompt to decide whether reasoning had already ended. It mistook the example closing marker for the current answer state.

The plugin changes only the scope of initial state detection. It locates the last assistant prefix and inspects the suffix after that prefix, retaining the original generated-stream extraction. Prefix cases and several chunked-stream replays passed in the actual image. Complete-stream and functional checks also passed after redeployment. [Plugin source used in this run](../../assets/practices/minimax-m31-flash-day0/minimax-reasoning-plugin.py)

The plugin targets the pinned build in this article. Before carrying it into an upgrade, verify whether upstream has fixed the parser. Dependency consistency checks also reported declaration conflicts involving NIXL, CUTLASS DSL and OpenTelemetry. Runtime conclusions here cover the paths actually exercised.

## 4. What the performance tests measure

Each engine's main matrix contains 19 cases, each measured for three rounds: 57 rounds and 1,272 requests. A supplementary historical protocol uses 128→64 tokens at concurrency 1, 4, 8, again with three rounds: 9 rounds and 672 requests. Together these produce 66 rounds and 1,944 requests. Warmups and calibration are excluded. [vLLM sanitized data and per-round metrics](../../assets/practices/minimax-m31-flash-day0/vllm-results.json)

Fixed-length traffic uses `/v1/completions`, the same benchmark client from the pinned image, and the local Tokenizer. Temperature is 0, with `ignore_eos=true` to enforce output lengths. This measures serving performance; output from random synthetic prompts is not graded for answer quality. Natural-language functional checks use temperature=1.0, top_p=0.95 and low reasoning effort.

Requests have no arrival-rate limit but have bounded client concurrency, making this a finite-batch, fixed-concurrency test. Short-request batches contain 8/16/32/64/128 requests at concurrency 1, 4, 8, 16, 32 respectively; other cases are specified in the data file. This run does not validate a Service Level Objective (SLO) under sustained open-loop arrivals.

- TTFT (Time to First Token): time from request submission to the first non-empty output chunk.
- TPOT (Time per Output Token): the interval between a request's first and last output chunks divided by its output token count minus one. P95 is the percentile of these per-request averages, not of individual token intervals.
- E2E (End-to-End): complete request duration. Output throughput is successful output tokens divided by full-round duration.
- Tables take the median of three round-level values separately for each metric. Error bars span the minimum and maximum across rounds. P95 is not recomputed from pooled requests, and small-sample tail latency should not be extrapolated directly to production.

## 5. vLLM short requests: throughput and latency

Results for 128 input tokens and 128 output tokens follow.

| Concurrency | Requests per round | Output throughput Token/s | P95 TTFT ms | P95 TPOT ms | P95 E2E s |
| --- | --- | --- | --- | --- | --- |
| 1 | 8 | 141.6 | 126.2 | 6.14 | 0.90 |
| 4 | 16 | 392.9 | 393.4 | 9.85 | 1.39 |
| 8 | 32 | 633.0 | 404.7 | 11.61 | 1.63 |
| 16 | 64 | 1,074.6 | 372.6 | 13.50 | 1.93 |
| 32 | 128 | 1,585.4 | 549.8 | 16.42 | 2.63 |

![Short-request concurrency, throughput and time to first token](../../assets/practices/minimax-m31-flash-day0/short-en.png)

Increasing concurrency from 1 to 32 raises output throughput by approximately 11.2 times, while P95 TPOT rises from 6.14 ms to 16.42 ms. TTFT at concurrency 16 is lower than at concurrency 8, and the three-round data retains that behavior. Queuing, batching and overlapping phases affect finite-batch statistics; the curve should not be forced into a monotonic shape.

The following screenshot shows the eight-GPU resource curves over the actual main-matrix window. The top values are the maximum single-card measurements in that window: 100% utilization, approximately 121 GiB framebuffer memory, 428 W power and 62°C temperature. Power is not the aggregate across eight GPUs, and framebuffer memory is not the weight size alone.

![Eight-GPU utilization, memory, power and temperature during the main matrix](../../assets/practices/minimax-m31-flash-day0/vllm-gpu-core.jpg)

## 6. vLLM long-input and long-output performance

Holding concurrency at 8 reveals how request shape changes the bottleneck.

| Input→output tokens | Output throughput Token/s | P95 TTFT s | P95 TPOT ms | P95 E2E s |
| --- | --- | --- | --- | --- |
| 128→128 | 633.0 | 0.40 | 11.61 | 1.63 |
| 4,096→256 | 340.8 | 3.58 | 21.41 | 6.45 |
| 8,192→1,024 | 475.0 | 7.19 | 15.83 | 19.16 |
| 16,384→256 | 119.9 | 13.90 | 56.90 | 21.07 |
| 128→2,048 | 808.4 | 0.40 | 9.91 | 20.48 |

Long inputs require more prefill computation and compete with ongoing decoding. The 16K-input, 256-output case at C8 reaches 13.90 seconds P95 TTFT. The short-input, 2K-output case still starts in approximately 0.40 seconds, but takes approximately 20.48 seconds to finish. Retrieval-Augmented Generation (RAG) and agent workflows need concurrency limits based on their actual input/output distributions rather than short-chat throughput estimates.

## 7. vLLM million-token input and recall

The long-context probes place three independent random codes near 10%, 50% and 90% of a long document and ask for an exact JSON answer containing every code. Maximum service context is 1,048,576, with one request at a time and prefix caching disabled. Passing requires valid server Usage, stream termination, a valid finish reason and exact matches for all codes.

| Tier / seed | Server input tokens | Output tokens | TTFT s | E2E s | Result |
| --- | --- | --- | --- | --- | --- |
| 64K / 103101 | 57,344 | 82 | 6.76 | 7.29 | PASS |
| 128K / 103101 | 122,881 | 72 | 14.62 | 15.06 | PASS |
| 256K / 103101 | 253,952 | 195 | 31.80 | 33.11 | PASS |
| 512K / 103101 | 516,095 | 96 | 70.97 | 71.36 | PASS |
| 1M / 103101 | 1,040,383 | 203 | 168.49 | 169.79 | PASS |
| 1M / 103102 | 1,040,384 | 211 | 168.29 | 169.69 | PASS |
| 1M / 103103 | 1,040,384 | 174 | 168.26 | 169.29 | PASS |

All three million-token inputs recovered all three codes, and local encoding matched server input counts. This validates long-input processing and targeted recall under the single-request deployment. Multi-document reasoning, contradictory evidence handling and complex task completion require a separate task evaluation.

![Eight-GPU resource curves during long-context recall](../../assets/practices/minimax-m31-flash-day0/vllm-gpu-long.jpg)

The maximum single-card framebuffer usage in the window reaches approximately 128 GiB with million-token input. Both the service configuration and workload differ from the main matrix, where the peak was approximately 121 GiB. Their difference therefore cannot be interpreted directly as KV memory cost per million tokens. TTFT of approximately 168 seconds also shows why supported context capacity and interactive usability need separate evaluation.

## 8. vLLM tool and image checks

| Check | Result | Coverage |
| --- | --- | --- |
| Text and complete stream | 3/3 | Arithmetic, random-code multi-turn recall, stream termination and reasoning-field separation |
| Tool calls | 4/4 | Single tool, mock tool-result return, streaming arguments and nested objects |
| Images | 4/4 | Shape counting, sample receipt total, largest chart bar and two-image vegetable identification |
| Reasoning effort | 5/5 | Expected answers on a simple question at five settings; no reasoning-quality comparison |

Tool responses come from a local test stub without connecting to production systems. Image fixtures use fixed files and explicit expected answers. These checks establish whether input, templating, parsing and output paths work; they do not replace long-running agent or real-document quality evaluations. Video and UI grounding are outside this run's scores.

## 9. SGLang follow-up and deployment comparison

### 9.1 Actual configuration and comparison scope

SGLang uses `lmsysorg/sglang:dev-minimax-m31-flash`, pinned to amd64 digest `sha256:c1ad26064c80ea2d628b3575b1803e9df804949e718dd2ee15d63fb21d9dcedb`. Its installed version is `0.0.0.dev0`, with PyTorch `2.15.0.dev20261005+cu134`, Transformers `5.19.0` and FlashInfer `0.7.2`. This is a model-support build; pin its digest and actual versions when reproducing it.

| Comparison item | vLLM | SGLang |
| --- | --- | --- |
| Weights and GPUs | Same model snapshot, 8×H20-3e, TP8 | Same model snapshot, 8×H20-3e, TP8 |
| Physical node | Node A | Node B |
| KV storage precision | Explicit FP8 | auto, FP8 confirmed in runtime logs |
| Main context / concurrency limit | 32,768 / 32 | 32,768 / 32 |
| Long context / concurrency limit | 1,048,576 / 1 | 1,048,576 / 1 |
| Prefix cache / DSpark | Disabled / not enabled | Disabled / not enabled |
| Memory fraction / page size | 0.85 / 128 | 0.85 / 128 |
| Expert computation | Marlin | Marlin |
| Attention and graph capture | Triton sparse attention and indexer; FULL_AND_PIECEWISE | FA3 configuration; breakable prefill graphs and decode graphs |
| Tokenizer concurrency | Defaults not explicitly overridden | 8 workers explicitly configured |

The experiments use the same GPU model but different physical nodes and software versions. They compare concrete deployment configurations: nodes, frontend concurrency and underlying kernels also affect results. The differences cannot all be isolated as causal effects of engine names.

The SGLang command follows. Its `kv_cache_dtype=auto` ultimately allocates `torch.float8_e4m3fn`, with the KV pool's actual storage type confirmed in runtime logs. Defaults for unrelated models should not be used to infer this run's precision.

```bash
python3 -m sglang.launch_server \
  --model-path /model --served-model-name MiniMax-M3.1-Flash \
  --host 0.0.0.0 --port 30000 --trust-remote-code \
  --tp 8 --reasoning-parser minimax-m3 --tool-call-parser minimax-m3 \
  --page-size 128 --attention-backend fa3 --moe-runner-backend marlin \
  --context-length 32768 --max-running-requests 32 \
  --cuda-graph-backend-prefill breakable --cuda-graph-max-bs-decode 32 \
  --mem-fraction-static 0.85 --tokenizer-worker-num 8 --disable-radix-cache
```

For long context, set `--context-length` to `1048576` and `--max-running-requests` to `1`. Reasoning effort is passed through the top-level `reasoning_effort` field, whereas vLLM uses `chat_template_kwargs.reasoning_effort`. Both use low for functional and long-context checks.

### 9.2 Complete performance matrix

SGLang completes 57 main rounds and 1,272 requests, plus 9 supplementary rounds and 672 requests, with 0 failures. Combined with vLLM, this totals 132 formal rounds and 3,888 requests. Both use the same pinned client version, requests, seeds and output lengths; warmups and calibration are separate. [Per-round data for both engines](../../assets/practices/minimax-m31-flash-day0/comparison-results.json)

| Input→output / concurrency | SGLang output Token/s | vLLM output Token/s | SGLang P95 TTFT s | vLLM P95 TTFT s |
| --- | --- | --- | --- | --- |
| 128→128 / C1 | 172.5 | 141.6 | 0.046 | 0.126 |
| 128→128 / C4 | 492.9 | 392.9 | 0.099 | 0.393 |
| 128→128 / C8 | 775.5 | 633.0 | 0.152 | 0.405 |
| 128→128 / C16 | 1132.2 | 1074.6 | 0.269 | 0.373 |
| 128→128 / C32 | 1688.4 | 1585.4 | 0.446 | 0.550 |
| 4,096→256 / C1 | 133.4 | 123.9 | 0.470 | 0.502 |
| 4,096→256 / C4 | 281.3 | 266.4 | 1.725 | 1.845 |
| 4,096→256 / C8 | 353.8 | 340.8 | 3.353 | 3.583 |
| 4,096→256 / C16 | 411.5 | 397.5 | 6.546 | 6.787 |
| 8,192→1,024 / C1 | 151.7 | 141.2 | 0.890 | 0.936 |
| 8,192→1,024 / C4 | 364.1 | 347.8 | 3.433 | 3.633 |
| 8,192→1,024 / C8 | 486.5 | 475.0 | 6.820 | 7.188 |
| 8,192→1,024 / C16 | 601.2 | 591.4 | 13.460 | 13.837 |
| 16,384→256 / C1 | 77.4 | 74.1 | 1.824 | 1.889 |
| 16,384→256 / C4 | 113.5 | 109.3 | 7.041 | 7.333 |
| 16,384→256 / C8 | 123.6 | 119.9 | 13.980 | 13.900 |
| 128→2,048 / C1 | 180.7 | 161.4 | 0.045 | 0.138 |
| 128→2,048 / C4 | 537.2 | 499.8 | 0.098 | 0.401 |
| 128→2,048 / C8 | 857.6 | 808.4 | 0.152 | 0.404 |

![Short-request output throughput for both engines](../../assets/practices/minimax-m31-flash-day0/comparison-short-en.png)

At 128→128 and C1, P95 TTFT is 45.6 ms versus 126.2 ms. At C32, P95 TPOT is 16.40 ms versus 16.42 ms. Low-concurrency first-token latency and high-concurrency sustained decoding need separate evaluation.

![Long-input first-token latency for both engines](../../assets/practices/minimax-m31-flash-day0/comparison-prefill-en.png)

At 8K→1K and C16, output throughput is 601.2 versus 591.4 tokens/s, while P95 E2E is 27.37 versus 36.72 seconds. Similar aggregate throughput can produce different tails. Adding P95 TTFT to P95 TPOT is not a valid way to predict P95 E2E.

![Long-output time per token for both engines](../../assets/practices/minimax-m31-flash-day0/comparison-decode-en.png)

The following screenshot shows the actual SGLang main test window, including functional checks, calibration, warmups and formal rounds. Latency and throughput come from the benchmark client; resource curves come from GPU collection. The SGLang built-in metrics endpoint is not enabled in this run.

![SGLang main test resource curves](../../assets/practices/minimax-m31-flash-day0/sglang-gpu-core.jpg)

### 9.3 SGLang long-context and functional validation

| Tier / seed | Server input tokens | Output tokens | TTFT s | E2E s | Result |
| --- | --- | --- | --- | --- | --- |
| 65,536 / 103101 | 57,344 | 73 | 12.09 | 12.53 | PASS |
| 131,072 / 103101 | 122,881 | 76 | 15.61 | 16.10 | PASS |
| 262,144 / 103101 | 253,952 | 207 | 36.76 | 38.22 | PASS |
| 524,288 / 103101 | 516,095 | 169 | 94.79 | 96.14 | PASS |
| 1,048,576 / 103101 | 1,040,383 | 247 | 272.50 | 274.95 | PASS |
| 1,048,576 / 103102 | 1,040,384 | 174 | 272.26 | 273.98 | PASS |
| 1,048,576 / 103103 | 1,040,384 | 203 | 272.11 | 274.12 | PASS |

All three million-token inputs exactly recover codes near 10%, 50% and 90% of the document. Median TTFT across the three seeds is 272.26 seconds for SGLang and 168.29 seconds for vLLM. This validates single-request recall, not complex long-document reasoning quality.

![Long-context first-token latency for both engines](../../assets/practices/minimax-m31-flash-day0/comparison-long-en.png)

![SGLang long-context resource curves](../../assets/practices/minimax-m31-flash-day0/sglang-gpu-long.jpg)

In the long-context window, peak single-card memory is approximately 137.2 GiB for SGLang and 128 GiB for vLLM. The 0.85 setting is a runtime memory-planning parameter; caches, workspaces and graph capture also affect actual peaks. Keep million-token inputs single-request initially, then measure headroom before increasing concurrency.

SGLang passes text and complete streams 3/3, tools 4/4, images 4/4 and reasoning parameters 5/5, using the same small probes as vLLM above. Tool returns come from a test stub; video and UI grounding are outside this run's scores.

The initial SGLang launcher failure came from the test script assuming a standalone `torchrun` existed in the image. Switching to `python3 -m torch.distributed.run` in the same Python environment passed the eight-rank communication check. The model service still starts through `python3 -m sglang.launch_server`. Initial startup also includes DeepGEMM compilation and graph capture. File and compilation caches are uncontrolled, so these records are not used for cold-start rankings.

Web interaction was checked separately after formal performance tests: the model returned 703, then recalled jade-628 within the same conversation. This checks conversation-context forwarding. The screenshot preserves the original Chinese interface.

![Actual SGLang web conversation](../../assets/practices/minimax-m31-flash-day0/sglang-openwebui-text.jpg)

### 9.4 Deployment choices

For new low-concurrency short-chat services, prioritize reproducing this SGLang configuration for its lower first-token latency. Existing vLLM services dominated by high-concurrency traffic can retain the deployment while running business-prompt regressions. Sustained decoding is already close at C32; migration benefits need to account for tool protocols, image distributions and operating costs.

For inputs close to one million tokens, prioritize validating vLLM, which has the lower first-token wait in this run: three-seed median TTFT is 272.26 seconds for SGLang and 168.29 seconds for vLLM. Use separate admission limits for long inputs and outputs, and a dedicated configuration for million-token context. This run validates million-token input only with maximum running requests of 1, without queueing. Measure retrieval, segmentation and prefix reuse separately. Preserve image digests, actual arguments and regression cases for both development builds, and recheck compatibility libraries and parser patches after upgrades.

## References

- [MiniMax-M3.1-Flash model card](https://huggingface.co/MiniMaxAI/MiniMax-M3.1-Flash)
- [vLLM deployment recipe](https://recipes.vllm.ai/MiniMaxAI/MiniMax-M3.1-Flash)
- [SGLang Cookbook](https://docs.sglang.io/cookbook/autoregressive/MiniMax/MiniMax-M3.1)
- [SGLang MiniMax M3.1 support code](https://github.com/sgl-project/sglang/pull/45925)
- [NVIDIA CUDA forward compatibility](https://docs.nvidia.com/deploy/cuda-compatibility/forward-compatibility.html)
- [Previous MiniMax-M3 dual-engine measurements](minimax-m3-h20-benchmark.md)
