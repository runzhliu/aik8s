---
title: "MiMo-V2.6-Pro-RL First Test: vLLM Deployment and Performance Measurement on 8x H20-3e"
description: "Model architecture of MiMo-V2.6-Pro-RL, 8-card H20-3e vLLM deployment, text and image acceptance, fixed-length stress testing, and operational boundaries"
last_reviewed: 2026-09-26
---

# MiMo-V2.6-Pro-RL First Test: vLLM Deployment and Performance Measurement on 8x H20-3e

## Getting to Know the Pro Model

[MiMo-V2.6-Pro-RL](https://huggingface.co/XiaomiMiMo/MiMo-V2.6-Pro-RL) is the flagship open-weight model of Xiaomi's MiMo-V2.6 series, using a sparse mixture-of-experts architecture with approximately **1.02T** total parameters and about **42B** activated parameters per token. The official model card lists text, image, video, and audio inputs and a 1M-token context capability, under the MIT license. Compared with the Flash version, Pro's weights and per-token computation are significantly larger, so deployment first faces weight loading, expert routing, and large GPU-memory communication.

The configuration used in this round has 70 layers, 384 routed experts, and Top-8 expert selection; the main weights include FP8 and MXFP4 expert layouts. The official release also provides multi-token prediction related weights, but this round's baseline did not enable speculative decoding. The 1M context listed on the model card is a model capability; this round's serving window is fixed at **32,768 tokens**, and the two should not be equated.

The model replica has 129 main weight shards, totaling approximately 563.58 GB, plus MTP weights. The experiment reused a model replica that had already been synchronized and verified; before startup, we rechecked the main shard count, total byte size, configuration, and temporary file status, without repeating a full weight hash.

## Hardware and Test Methodology

The experiment used a single node with **8×H20-3e**, vLLM tensor parallelism TP8, and the model was loaded from shared read-only storage. Before formal stress testing, we completed 8-rank communication checks, model ID, simple arithmetic, multi-turn memory, streaming termination, and usage validation. The model service uses an OpenAI-compatible interface, with Prefix Cache disabled, and sets `gpu-memory-utilization=0.90` and a 32K serving window. The stress-test input is constructed by repeating a fixed English technical text, trimmed to the target token length, with `temperature=0`, `min_tokens=max_tokens`, and `ignore_eos=true` set; this measures the inference system's capacity under this synthetic load, not the model's answer quality.

| Configuration Item | Actual Value |
| --- | --- |
| GPU | Single node 8×H20-3e |
| Serving image | `vllm/vllm-openai:mimo-v26`, fixed amd64 image digest `sha256:5d8a6c57…10780c42b` |
| Parallelism | Tensor Parallel 8 |
| Model and context | MiMo-V2.6-Pro-RL; serving window 32,768 tokens |
| Cache and GPU memory budget | Prefix Cache disabled; `gpu-memory-utilization=0.90` |
| Parsers | MiMo reasoning parser, MiMo tool-call parser |
| Container resources | Request 64 CPU, 512 GiB host memory, 8 GPUs |

| Scenario | Input / Output Tokens | Purpose |
| --- | ---: | --- |
| Short requests | 1,024 / 128 | Interactive throughput and queuing |
| Long input | 8,192 / 128 | Prefill burden |
| Long output | 1,024 / 512 | Decode capability |
| Long context | 24,576 / 128 | Capacity boundary within the 32K window |

Each scenario runs at three concurrency levels: C1, C8, and C32. After warm-up for each level, three formal rounds are repeated. C1 has 8 requests per round, C8 has 16 requests per round, and C32 has 64 requests per round. A valid request must have a successful response, non-empty output, a complete termination marker, valid usage, and the target output length; failures remain in the original denominator. The results in the table are the median of three formal rounds. TTFT is the wait time for the first non-empty token, TPOT is the average time per output token after the first token, and E2E is the total request duration.

## vLLM 8-Card Baseline

vLLM completed **36/36 formal test rounds, with 1056/1056 requests successful**. Model ID, arithmetic, multi-turn, streaming integrity, tool calls, and tool result feedback all passed; image validation covered two different images and the answer changes after swapping their order. Passing images does not equal passing video or audio: the local model replica does not yet have complete audio tokenizer and DFlash files, so this round does not report audio or speculative decoding results based on that.

This vLLM service is also registered in the existing OpenWebUI. Sending 'Calculate 17 plus 28, answer only the number' from the interface returns 45. This check covers the complete text request path from browser, OpenWebUI, cross-cluster ingress, to the inference service.

![Actual conversation with MiMo-V2.6-Pro-RL in OpenWebUI](../../assets/practices/mimo-v26-pro-rl-h20/openwebui-chat-light.png)

The actual prompt examples used in functional acceptance are as follows. The image tests use carrot and corn images, asking the model to answer only the English name of the main vegetable, then swap the order of the two images to verify the answer order.

| Item | Prompt Excerpt | Acceptance Point |
| --- | --- | --- |
| Arithmetic | `计算 17 加 25，只回答数字。` | Final answer is 42 |
| Multi-turn | `Remember code 482619.`, then ask `What was the code? Reply only with the code.` | Returns 482619 across turns |
| Tool | `Use get_weather to look up weather in Beijing. Do not invent the weather.` | Calls `get_weather`, correctly answers after receiving simulated tool result |
| Single image | `Name the main vegetable shown. Reply with one English noun only.` | Gives different subjects for different images |
| Dual image | `Name the main vegetable in each image in order. Reply as two English nouns separated by a comma.` | Order changes synchronously after swapping images |

![MiMo-V2.6-Pro-RL model and test scope](../../assets/practices/mimo-v26-pro-rl-h20/model-overview.png)

![Short request and long output throughput](../../assets/practices/mimo-v26-pro-rl-h20/core-throughput.png)

| Input / Output | Concurrency | Output Throughput (tokens/s) | P95 TTFT | P95 TPOT | P95 E2E |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1K / 128 | C1 | 111.08 | 0.200 s | 7.50 ms | 1.152 s |
| 1K / 128 | C8 | 410.80 | 1.127 s | 17.93 ms | 2.499 s |
| 1K / 128 | C32 | 584.54 | 4.201 s | 46.50 ms | 8.023 s |
| 8K / 128 | C1 | 62.59 | 1.085 s | 7.56 ms | 2.045 s |
| 8K / 128 | C8 | 100.39 | 8.469 s | 71.21 ms | 13.628 s |
| 8K / 128 | C32 | 110.41 | 31.493 s | 264.59 ms | 64.046 s |
| 1K / 512 | C1 | 126.80 | 0.199 s | 7.51 ms | 4.038 s |
| 1K / 512 | C8 | 616.05 | 1.124 s | 12.59 ms | 6.658 s |
| 1K / 512 | C32 | 1,056.94 | 4.194 s | 28.40 ms | 16.417 s |
| 24K / 128 | C1 | 29.46 | 3.351 s | 7.85 ms | 4.346 s |
| 24K / 128 | C8 | 36.35 | 24.772 s | 188.12 ms | 44.268 s |
| 24K / 128 | C32 | 37.94 | 95.952 s | 789.48 ms | 196.213 s |

For short requests, increasing from C1 to C32 raises total output throughput by about 5.3 times, but P95 TTFT grows from 0.20 seconds to 4.20 seconds. At 24K input with C32, although all requests complete, P95 time to first token approaches **96 seconds**; online services should decide admission concurrency based on latency targets rather than only final success rate.

![24K input throughput and tail latency](../../assets/practices/mimo-v26-pro-rl-h20/long-context.png)

Within the formal stress-test time window, the utilization peak of all eight cards was 100%, GPU memory usage peaked at about 131 GB per card, power consumption peaked at about 364–396 W, and temperature peaked at about 52–65°C. These are discretely sampled curves and peaks, not precise energy consumption under continuous sampling.

![vLLM 8-card resource curves](../../assets/practices/mimo-v26-pro-rl-h20/grafana-vllm-light.png)

## Deployment Recommendations

Eight cards are the verified vLLM starting point for this round. Before going live, check the GPU topology and NCCL communication actually obtained by the container, especially cross-GPU activation and expert communication under 8-card tensor parallelism. CPU-side tokenization, vision preprocessing, and host-to-GPU-memory data copies are also affected by NUMA locality; it is recommended to include CPU, memory, and GPU affinity in acceptance.

Capacity planning should be layered by request length: the latency curves for 1K conversation, 8K retrieval-augmented, and 24K long-document differ significantly. Production traffic should set separate concurrency and queue limits, and simultaneously monitor success rate, TTFT, TPOT, E2E, GPU utilization, and GPU memory. Prefix Cache, speculative decoding, and contexts longer than 32K each require establishing new baselines and should not directly reuse the table above.

## References

- [Xiaomi MiMo-V2.6-Pro-RL official model card](https://huggingface.co/XiaomiMiMo/MiMo-V2.6-Pro-RL)
