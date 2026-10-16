---
title: "MiniMax-M3 Real-World Test on Eight H20 GPUs: SGLang vs. vLLM"
description: "MiniMax-M3 BF16 TP8 dual-engine functionality, text stress test, multimodal and deployment verification."
---

# MiniMax-M3 Real-World Test on Eight H20 GPUs: SGLang vs. vLLM

MiniMax-M3 is MiniMax's natively multimodal MoE model, designed for code, tool calling, and long-horizon agents. The official model card lists approximately **428B total parameters, 23B active parameters**, supporting text, image, and video input with text output, and declares a 1M Token context; the open weights are released under the MiniMax Community License. Model specifications are based on the [official model card](https://huggingface.co/MiniMaxAI/MiniMax-M3).

The MoE activates a subset of experts for each Token's computation, but a full deployment must still hold all weights. The pinned version in this test has 59 Safetensors files totaling 854.18 GB, all passing full SHA256 verification. The deployment budget must also cover the vision encoder, KV and sparse index caches, workspace, and CUDA Graph.

M3 jointly processes text, images, and video during training. Once deployed as a conversational service, it can read screenshots and charts, understand video content, and then output text or tool calls. This test separately verifies numeric reading from images, video color ordering, function calling, and code execution, to avoid inferring that the multimodal and Agent pipelines work merely from successful ordinary chat.

M3 uses MiniMax Sparse Attention (MSA) to improve long-context efficiency. Sparse attention reduces the scope of attention computation, but the serving stack must still manage caching, indexing, and scheduling for long requests. The model's declared 1M capability, the engine-allowed parameters, and the lengths actually passed by testing are recorded separately; this article uses a 32K serving window for same-host comparison.

Three inference modes determine the generation process of a real conversation: `enabled` always enables reasoning, `adaptive` lets the model decide when to add reasoning, and `disabled` disables reasoning. These modes change the number of generated Tokens and the waiting time, so fixed-output-length stress tests and real-conversation acceptance are counted separately. Specifications and mode definitions are in the [official documentation](https://huggingface.co/MiniMaxAI/MiniMax-M3).

## Hardware and Runtime Configuration

Both engines serially reuse the same 8×H20-3e host, with each GPU reporting 143771 MiB. The pinned model Revision is `f0e1c1e04d40177e4673a22097036854f536e9c0`, BF16 TP8, 32K context, maximum running requests 32, memory ratio 0.85, Prefix Cache disabled, MTP/speculative decoding not enabled. Both model containers request 64 CPUs and 768Gi host memory, with limits of 128 CPUs and 1536Gi; the same-CPU load-test client requests 4 CPUs and 8Gi, with limits of 8 CPUs and 16Gi.

SGLang is `0.0.0.dev1+g56e290315`, with prefill chunked CUDA Graph disabled and the normal decode graph retained; vLLM is `0.1.dev17492+g454b47db8`, actually using that version's breakable CUDA Graph path. Both use Torch 2.11.0+cu130 and NCCL 2.28.9; Transformers are 5.8.1 and 5.11.0 respectively. This is a comparison of specific configurations, not a claim that default configurations are identical.

The main matrix is submitted by the same CPU client to `/v1/completions` with fixed input/output lengths, using consistent Tokenizer, Case, and random seed. Each engine runs 11 Cases × 3 rounds, for a total of **66 rounds and 7908 official requests**; each round checks completion count, error count, input Tokens, and forced output Token count. Warmup, functional checks, the early 8K Smoke, and failed attempts are not counted in the main matrix.

![Eight-GPU and NUMA diagram](../../assets/practices/minimax-m3-h20/v2/topology.png)

## Main Stress Test Results

Each item below is the median of the corresponding metric across three rounds; full per-round values and ranges are in the [redacted data](../../assets/practices/minimax-m3-h20/benchmark-summary.json). The median of three rounds of P95 is not the overall P95 of all requests merged together. Long-output C1 has only 6 requests per round, so tail latency only describes that round and cannot be used to infer production P99. Input/output Tokens are shown with a slash.

| Workload | Concurrency | SGLang output tok/s | vLLM output tok/s | SGLang P95 TTFT ms | vLLM P95 TTFT ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| 128/64 | 1 | 114.7 | 116.6 | 128.5 | 107.7 |
| 128/64 | 4 | 324.2 | 275.4 | 246.5 | 220.6 |
| 128/64 | 8 | 499.5 | 382.2 | 253.7 | 328.5 |
| 128/64 | 16 | 784.0 | 776.7 | 290.4 | 359.4 |
| 128/64 | 32 | 1112.0 | 1089.4 | 398.4 | 352.3 |
| 4096/128 | 4 | 185.4 | 171.1 | 1582.6 | 1349.2 |
| 4096/128 | 8 | 216.9 | 200.2 | 3134.7 | 1168.1 |
| 16384/256 | 4 | 110.1 | 107.8 | 6855.0 | 4473.8 |
| 16384/256 | 8 | 120.7 | 121.0 | 13614.3 | 8696.4 |
| 128/1024 | 1 | 143.3 | 140.9 | 128.7 | 108.0 |
| 128/1024 | 8 | 624.0 | 488.9 | 245.9 | 328.3 |

![Short-request throughput](../../assets/practices/minimax-m3-h20/v2/short-throughput.png)

![Long-input time to first token](../../assets/practices/minimax-m3-h20/v2/rag-ttft.png)

For short requests, going from C1 to C32, SGLang throughput increases to 9.69× the single-concurrency value, and vLLM throughput increases to 9.35× the single-concurrency value. This is a concurrency scaling result for the same short request shape and cannot replace long-context capacity measurement.

For 16K input and 256 output, going from C4 to C8, SGLang throughput changes by +9.6% and P95 time to first token becomes 1.99×; vLLM throughput changes by +12.2% and P95 time to first token becomes 1.94×. Therefore, for interactive RAG, the time-to-first-token target should be determined first, then concurrency selected; throughput increase does not automatically mean user experience improvement.

## Functionality and Multimodal

In the 30-second telemetry sampling during the main matrix phase, the maximum single-GPU memory usage for SGLang / vLLM was 121.05 / 117.78 GiB respectively. The sampling interval includes Case warmup and client startup; discrete sampled values are not equal to continuous peaks or precise energy consumption.

| Phase | SGLang | vLLM |
| --- | --- | --- |
| 12 basic functions | 12/12 PASS | 12/12 PASS |
| Raw solid-color images and video | 6/6 official rounds passed; 6 config warmups failed | 6/6 official rounds passed; 6 config warmups failed |
| Bordered images and video with concurrency | 24/24 PASS | 24/24 PASS |
| Raw tools, code, retrieval, and error recovery | 14/28 PASS | 16/28 PASS |
| Explicit-field extraction Prompt retrieval retest | 10/10 PASS | 10/10 PASS |

Failures are concentrated in raw solid-color images, math problems with reasoning disabled that must output only integers, raw long-text retrieval, and SGLang's corrupted-media error codes; per-item status is retained in the functional data. The main matrix's zero failures refers only to fixed-length official requests and does not include these semantic and abnormal-input checks.

In both engines' raw tests, pure red/pure blue images both produced color misjudgments, with six static image configurations each stopping during warmup; chart OCR and video color ordering passed. During vLLM troubleshooting, PNG pixels and image preprocessing tensors were inspected, with no evidence that input became a black image. After adding borders and markers and changing the question to ask about the subject color, a separate test was run, with each engine completing 24 rounds and 384 requests with passing answers; this is not called a model fix, nor is the root cause attributed to the model or engine on this basis.

Neither engine found the nine keys in the raw long-text retrieval; in vLLM diagnostics, the failure of that Prompt could also be reproduced in short text. The retest kept the body text, keys, and insertion positions, changing only the instruction to the explicit field extraction in `<document>…</document>`, with both engines passing nine answer-containing samples and one no-answer control. The two result sets are listed separately, showing the task is prompt-sensitive; the original failure cannot be directly attributed to lack of 32K support, nor can the retest overwrite the failure record.

Error handling for corrupted images and corrupted video differs: vLLM returns the expected HTTP 400; SGLang returns HTTP 500, with both items judged as failures. Logs show PIL image recognition errors and TorchCodec invalid-input errors wrapped as RuntimeError, ultimately entering the server-side internal error response. Subsequent normal-request recovery checks passed, with no process exit observed; this does not mean the error code is correct. The issue in this pinned version is not yet fixed; when integrating, media input should be validated and client data errors should be distinguished from server-side failures, rather than simply rewriting all 500s as 400s.

The following preserves the actual body replies for the specified samples; they illustrate specific phenomena and are not accuracy measurements from independent sampling. Corresponding Token usage and original file SHA256 are in the public semantic sample data.

| Actual input | SGLang body reply | vLLM body reply |
| --- | --- | --- |
| Solid red image warmup | 1. black | 1. black |
| Bordered red image warmup | red | red |
| Output integer only / disabled | 264 | 264 |
| Raw long-text retrieval | NOT_FOUND | NOT_FOUND |
| Explicit-field extraction retest | jade-50-1-259920 | jade-50-1-259920 |

[View semantic sample data](../../assets/practices/minimax-m3-h20/semantic-examples.json).

![Multimodal throughput](../../assets/practices/minimax-m3-h20/v2/multimodal-throughput.png)

The following uses images with white borders and black markers, asking about the largest area color; the video is still the same red-green-blue material. Each item is the median of the corresponding metric across three rounds, with 16 requests per round. The image material differs from the raw solid-color test, and the two result sets are kept separately.

| Input | Concurrency | SGLang req/s | vLLM req/s | SGLang median E2E ms | vLLM median E2E ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| image-512 | 1 | 6.44 | 8.52 | 155.4 | 117.2 |
| image-512 | 4 | 12.29 | 11.75 | 324.1 | 338.7 |
| image-1024 | 1 | 5.75 | 7.97 | 173.8 | 125.5 |
| image-1024 | 4 | 7.72 | 10.90 | 519.1 | 294.8 |
| two-images-512 | 1 | 4.14 | 5.16 | 241.5 | 193.6 |
| two-images-512 | 4 | 6.79 | 7.84 | 587.6 | 503.1 |
| video-16frames | 1 | 3.11 | 3.27 | 318.7 | 301.7 |
| video-16frames | 2 | 4.39 | 4.51 | 456.3 | 441.3 |

Image concurrency covers 512/1024 single images and two 512 images; video uses 16-frame source material; each configuration is 16 requests × 3 rounds. Repeated material may hit the Processor cache, and actual visual Tokens may differ from the default frame-sampling path, so these end-to-end numbers are not interpreted as pure vision Kernel performance.

vLLM additionally retains a low-load observation that ended early: the actual request observation span was 30.07 minutes, with 903 requests and 0 failures; single-request E2E median was 120.8 ms. Load was approximately 0.5 req/s, 80% text and 20% repeated images, with at most four client workers. This is an observation record for that time period, not proof of one-hour stability, not a horizontal comparison with SGLang, and not representative of peak capacity. During that period there were also 60 GPU samples, with the first and last GPU memory readings on all eight cards remaining consistent; this only describes the observation window and does not imply long-term absence of leaks.

The 32K retrieval uses approximately 31K body Tokens, three insertion positions with three keys each, and one no-answer control. Body length and Chat Template overhead are recorded separately. Longer contexts, cross-node, fixed arrival-rate SLO scans, and single-variable optimization are not included in this round's conclusions.

## Reasoning Mode Comparison on the Same Question

The same question, three actual requests per mode, with the correct answer being 240. Time is the median E2E of all requests in that mode, with wrong answers also counted in the time, including first-use impact. This is not an accuracy test of three independent questions, nor part of the fixed-length main stress test; it cannot be used to infer general accuracy or production tail latency. Per-item completion_tokens uses the API-returned convention, see functional data. Actual prompt: `一个仓库有240件货物，先发走15%，又入库36件，现在有多少件？只输出最终整数，不要解释。`

| Reasoning mode | SGLang correct count | vLLM correct count | SGLang E2E seconds | vLLM E2E seconds |
| --- | ---: | ---: | ---: | ---: |
| disabled | 0/3 | 0/3 | 0.132 | 0.117 |
| adaptive | 3/3 | 3/3 | 0.373 | 0.361 |
| enabled | 3/3 | 3/3 | 0.587 | 0.578 |

## Actual Prompts and Material

Some of the actually submitted Prompts are as follows; acceptance uses temperature 0 to reduce randomness in repeated tests, and real conversations use the mode specified by `chat_template_kwargs.thinking_mode`. The official model card recommends general sampling with temperature=1.0, top_p=0.95; this acceptance did not use that sampling setting, and results are not extrapolated to accuracy under the officially recommended sampling.

- Math: `一个仓库有 240 件货物，先发走 15%，又入库 36 件，现在有多少件？只给结论并简要说明。`
- Chart: `读出图中 Q1、Q2、Q3 的数值，指出哪个季度比上季度下降。`
- Video: `按出现顺序列出视频中背景的三种颜色。`
- Parallel tools: `请在本轮同时调用 get_weather 查询广州和北京的天气，不要猜测结果。`
- Code: `编写Python函数unique_sorted(values)，输入整数列表，返回升序去重后的新列表，不修改原列表。只给一个函数的代码，不要导入模块，不要解释。`

The chart standard answers are Q1=120, Q2=90, Q3=150, with Q2 declining; the video color order is red, green, blue. Tools use local simulated return values and do not execute real business operations. Code first passes AST restrictions, then is accepted in an isolated interpreter with no credentials and limited CPU/memory.

![Chart test input](../../assets/practices/minimax-m3-h20/quarter-chart.png)

[View color-order video test material](../../assets/practices/minimax-m3-h20/color-order.mp4). These are controlled test inputs; M3 returns text understanding results.

## Fixes from Image to Usable Service

Issues found in image dependency checks include SGLang NIXL frontend and backend dependencies, Pillow version conflicts, and vLLM's PyGObject dependency and missing PyAV. After fixing, dependency closure, module entry points, CLI, and video codec were checked separately, failed attempts were retained, and image digests were re-recorded.

SGLang's first startup weight loading took approximately 24 minutes 42 seconds, and normal decode graph capture succeeded, but the remaining 42 tiers of prefill chunked graph initialization still had to complete, leaving insufficient time in the original 30-minute overall startup budget. This attempt was proactively ended, logs were retained, the startup probe budget was adjusted to 60 minutes, and prefill chunked graphs were disabled. The second functional acceptance succeeded. The two cache conditions differ, so a cold-start speedup ratio cannot be calculated from this. In the third 32K/C32 startup used for the official matrix, per-Rank weight loading was 488.35–506.34 seconds, and decode graph capture was approximately 101.7 seconds; existing cache was reused at this point, so this still cannot be directly compared with vLLM's single loading time.

vLLM's weight loading took 1006.92 seconds, graph capture approximately 12 seconds, but the first real math request additionally triggered Triton Top-K and sparse attention Kernel compilation, totaling approximately 18.7 seconds. This is first-request initialization and was not mixed into the main matrix statistics; each main Case additionally has warmup.

The unattended client also fixed a ConfigMap path issue: after resolving symbolic links, it had pinned to an old-version directory that had already been reclaimed. After retaining a stable mount entry point, the client was rerun in a new attempt, and a version-switch regression check was performed; the model service did not need to be reloaded.

The actual handling process for image dependencies, CFS mounts, priority admission, startup initialization, and client path issues is in the [deployment failure and fix record](minimax-m3-h20-deployment-fixes.md).

## Reproduction and Boundaries

Model and image lists, startup scripts, acceptance and stress-test scripts are available in the [example directory](https://github.com/runzhliu/aik8s/tree/main/examples/minimax-m3-h20). The capability samples are limited and do not replace standard accuracy evaluation; first-load and hot-cache restart are recorded separately.

Both services are registered with the existing OpenWebUI through an internal management tool, and real cross-cluster requests were initiated from the OpenWebUI container; acceptance passed. Browser connectivity was unavailable, so no front-end operation screenshots were obtained; the acceptance scope here is configuration registration and cross-cluster API calls, and schematic diagrams are not treated as interface evidence. SGLang additionally returned 17+28=45 through OpenWebUI's own model discovery and chat proxy interface; this check also does not replace browser-based interactive acceptance.

## Deployment Suggestions

1. **Allocate TP8 according to the full eight-GPU interconnect domain.** The local GPUs show NV18 in pairs; checking only that eight cards were allocated is insufficient. Driver, link, topology, and NCCL correctness must be verified inside an actual container.
2. **Check GPU interconnect and NUMA locality separately.** On this machine, GPUs 0–3 and 4–7 correspond to different NUMA domains. In the actual snapshot, four SGLang workers allow CPU `0-191`, the other four allow `192-383`; all eight vLLM TP workers allow `0-383`, and both sides allow memory nodes `0-1`. This time we did not manually unify the CPU binding of the two engines, which is also a configuration difference. The allowed set does not equal the actual memory residency location, but it shows that GPU NV18 interconnect cannot replace CPU and host memory locality checks. CPU preprocessing, host memory, and Host-to-Device copies should be checked separately, then single-variable binding experiments should be performed; do not directly claim that core binding will definitely speed things up.
3. **Determine the context first, then test concurrency.** Here it is BF16 TP8, 32K, maximum running requests 32. SGLang initialization reports manageable 410,862 tokens, vLLM reports KV capacity 328,576 tokens; the two cache implementations differ, so speed cannot be predicted from capacity numbers alone. vLLM's theoretical concurrency estimate for each full 32K request is about 10, which does not guarantee that ten arbitrary multimodal requests will all pass. A maximum running request setting of 32 also does not mean that 32 requests can all simultaneously occupy 32K. Successful weight loading does not mean that arbitrarily long inputs can be processed simultaneously; longer windows, different KV precisions, and multi-machine deployments require separate acceptance.
4. **Startup probes cover loading and graph initialization.** This time the startup budget was set to 60 minutes, and the overall runtime deadline was retained. SGLang disables the prefill segmented graph while keeping the decode graph; vLLM runs on the breakable graph path of that fixed version. Do not interpret results from different graph configurations as engine differences across all versions.
5. **Choose configuration according to business SLO.** Fixed-length throughput, real Agent inference, and multimodal preprocessing have different bottlenecks. Judge based on time to first token (TTFT), time per output token (TPOT), error rate, and GPU memory headroom; do not just pick the highest tok/s.
