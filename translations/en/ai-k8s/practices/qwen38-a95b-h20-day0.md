---
title: "Qwen3.8-2.4T-A95B-FP8 Day 0: 32×H20-3e Dual-Engine Deployment and Load Testing"
description: "SGLang and vLLM deployment, functional validation, throughput/latency, cross-node communication, and long-context testing of the Qwen3.8 2.4T MoE model on four nodes with 32 H20-3e GPUs"
last_reviewed: 2026-09-13
---

# Qwen3.8-2.4T-A95B-FP8 Day 0: 32×H20-3e Dual-Engine Deployment and Load Testing

Qwen3.8-2.4T-A95B is the first Max-tier weight model Qwen has opened. The official model card lists **2.4T total parameters with 95B activated per Token**, targeting code, professional work, research, and long-horizon agents. This article uses the fine-grained FP8 quantized version with 128×128 Blocks; the full weights still need to be written to disk and loaded, so storage or GPU memory cannot be estimated as if it were a 95B small model.

The model consists of 92 layers, with every four layers forming a repeating unit: three Gated DeltaNet layers plus one Gated Attention layer, each followed by MoE. The MoE has 512 routed experts, selecting 10 per Token, plus 1 shared expert; Attention uses 64 Q Heads and 4 KV Heads. The model's native Context is 262,144 Tokens, with a stated extension capability to approximately 1.01 million Tokens. This article records the model's stated claims, runtime configuration, and measured lengths separately, to avoid treating configuration limits as already-validated capabilities.

Qwen3.8 also offers tunable reasoning depth: the API can control the amount of reasoning via `reasoning_effort` and retain reasoning context from historical messages via `preserve_thinking`. Deployment acceptance therefore covers not just ordinary Q&A but also Reasoning, streaming output, multi-turn memory, and Tool Call.

Model specifications and positioning come from the [Qwen official model card](https://huggingface.co/Qwen/Qwen3.8-2.4T-A95B-FP8) and the [Qwen3.8 release notes](https://qwen.ai/blog?id=qwen3.8).

## 1. Why Four Nodes with 32 H20-3e GPUs

The fixed Revision for this test is `d2dc35658bcf77e66643428cb52e774cc3b5bd29`. The model index references 213 Safetensors shards with a Tensor Payload of 2,496,066,252,544 bytes, approximately 2.27 TiB. Each node's local NVMe stores a complete snapshot, mounted read-only by the container; this avoids all four machines pulling 2.4 TB of weights from shared storage simultaneously at startup.

Deployment uses a four-node `TP8 × PP4` setup: 8-way Tensor Parallel within each machine and Pipeline Parallel across the four machines. It depends on both intra-node GPU interconnect and cross-node RDMA; an anomaly in any Rank's model, network, or process state can prevent the entire 32-GPU service from becoming Ready.

This article starts the same Revision with both SGLang and vLLM, using the same 32K service window, and runs the same fixed-Token load test matrix. Both test runs reuse the four-node `TP8 × PP4` topology, with the frameworks executed serially; tables only compare rounds that completed successfully with identical input, output, and concurrency.

![Four-node 32-GPU topology and data path](../../assets/practices/qwen38-a95b-h20/topology.png)

| Item | This Configuration |
| --- | --- |
| GPU | 4 nodes × 8×NVIDIA H20-3e, 32 GPUs total; per-GPU visible GPU memory 143,771 MiB |
| Parallelism | TP8 × PP4 |
| Weights | FP8, 213 shards, ~2.27 TiB; full copy stored on each node's NVMe |
| Serving framework | SGLang and vLLM, each pinned to a fixed image Digest |
| Baseline service window | 32,768 Tokens |
| Linear attention | SGLang Prefill / Decode uses FlashInfer; vLLM uses Runtime auto-selection |
| Mamba State | Both engines use BF16; SGLang sets `mamba-full-memory-ratio=0.95` |
| Cache and scheduling | Max Prefill / Batched Token 8,192, max running requests 64; Prefix Cache disabled in both engines |
| API | OpenAI-compatible Chat / Completions, Metrics enabled |

## 2. From Communication Checks to API Ready

Before the formal load, first check each node's single-machine AllReduce, then the 4-node, 32-Rank cross-machine AllReduce; the checks also validate output values, not just process exit codes. The server is then started with the same HCA, GID, and Socket NIC configuration, and after all four Ranks enter the Serving phase, query `/v1/models` from the Head Rank.

```bash
sglang serve \
  --model-path /models/Qwen3.8-2.4T-A95B-FP8 \
  --served-model-name qwen38-a95b-fp8 \
  --tp-size 8 \
  --pp-size 4 \
  --nnodes 4 \
  --node-rank "$RANK" \
  --dist-init-addr "$HEAD_ADDR:50080" \
  --context-length 32768 \
  --linear-attn-prefill-backend flashinfer \
  --linear-attn-decode-backend flashinfer \
  --mamba-ssm-dtype bfloat16 \
  --mamba-full-memory-ratio 0.95 \
  --page-size 64 \
  --max-prefill-tokens 8192 \
  --mem-fraction-static 0.85 \
  --max-running-requests 64 \
  --reasoning-parser qwen3 \
  --tool-call-parser qwen3_coder \
  --disable-radix-cache \
  --enable-metrics
```

vLLM uses the same TP/PP and service window, with core parameters as follows:

```bash
vllm serve /models/Qwen3.8-2.4T-A95B-FP8 \
  --served-model-name qwen38-a95b-fp8 \
  --tensor-parallel-size 8 \
  --pipeline-parallel-size 4 \
  --nnodes 4 \
  --node-rank "$RANK" \
  --master-addr "$HEAD_ADDR" \
  --master-port 50080 \
  --max-model-len 32768 \
  --gpu-memory-utilization 0.85 \
  --max-num-batched-tokens 8192 \
  --max-num-seqs 64 \
  --mamba-ssm-cache-dtype bfloat16 \
  --reasoning-parser qwen3 \
  --enable-auto-tool-choice \
  --tool-call-parser qwen3_coder
```

Before starting either engine, the single-machine 8-Rank and cross-machine 32-Rank AllReduce, Broadcast, and Send/Recv numerical checks were re-run and all passed on the first attempt. In the SGLang session, Rank 0's 64 MiB AllReduce diagnostics recorded 185.82 GB/s and 35.10 GB/s respectively; this is a pre-startup connectivity check with fixed message size, not a full NCCL Test matrix, and cannot be directly treated as business traffic bandwidth.

The running instance software is SGLang `0.0.0+qwen38.20260812.4e51ffc`, PyTorch `2.13.0+cu130`, Transformers `5.12.1`, FlashInfer Python `0.6.18`, and NCCL `2.29.7`. From the four service processes entering the execution phase to the Head Rank's `/v1/models` becoming available took approximately **876.6 seconds**; in the SGLang logs, per-Rank weight loading took about 55.6–57.7 seconds, and `scheduler_e2e` was 844.46 seconds. These two metrics have different scopes, so the 57 seconds cannot be written as the full startup time.

Taking Pipeline Stage 0 as an example, each TP Rank's weight loading occupies approximately 72.34 GB per the log values; BF16 KV Cache is approximately 18.45 GB for K and V each, Mamba State approximately 0.59 GB, Prefill/Decode CUDA Graph additionally approximately 4.98 GB, with approximately 22.7 GB of GPU memory still reported available after initialization completes. SGLang reports `max_total_num_tokens` as 7,740,288 with a maximum of 64 running requests. Different PP Stages may have different weight distributions, so this article does not extrapolate one Stage's logs into total 32-GPU memory usage.

The vLLM session uses `0.1.dev19754+g3a0914114` and NCCL `2.30.7`. This time, the cold-read speeds of the four NVMe drives varied greatly: the fastest Rank read weights in approximately 281 seconds, while the slowest Rank took approximately 1,775 seconds; from distributed service command dispatch to `/v1/models` becoming available took approximately **1,974 seconds**. Stage 0's per-GPU logs record 72.32 GiB of model weights, 41.63 GiB of KV Cache, 1.38 GiB of peak activations, and 0.24 GiB of CUDA Graph, with the Engine initialization phase taking an additional 83.63 seconds, of which compilation took 49.60 seconds. For multi-node giant models, the slowest node determines full Ready time, so the startup SLO should measure the entire chain rather than picking the fastest Rank's weight-loading time.

## 3. Functional Acceptance and Actual Prompts

Model ID, deterministic arithmetic, and complete SSE are the hard gate before performance load testing. After the basic gate passes, Reasoning, three levels of `reasoning_effort`, multi-turn context, and one Tool Call round-trip are checked independently; failure of optional capabilities is not disguised as full pass, nor does it block independent performance cases.

| Capability | Actual Prompt / Operation | Acceptance Criteria |
| --- | --- | --- |
| Arithmetic | `计算 37×19，只回答数字。` | Final answer strictly 703; final field does not leak `<think>` |
| Streaming | Same arithmetic question via SSE | Received `[DONE]`, Usage, non-empty content, and correct answer |
| Reasoning | Read the separate reasoning field in the response | Reasoning and final answer fields are distinguishable |
| Reasoning strength | `只回答：12 的平方是多少？`, passing low / medium / xhigh respectively | All three levels return 144, with reasoning field recorded |
| Multi-turn | `记住代号 amber-417`, next turn asks for the codename | Only returns `amber-417` |
| Tool Call | `调用工具查询北京天气，单位用摄氏度。` | Function name, city, and unit correct; after simulated result round-trip, uses 23℃ |

Both engines passed model ID, arithmetic, full streaming, separate Reasoning, `reasoning_effort=low/medium/xhigh`, multi-turn memory, and Tool Call round-trip. OpenWebUI reuses an existing instance, registered via OpenAI-compatible Connection for each engine, then conducts real conversations; screenshots and conversation exports are saved together with API receipts.

![Real two-turn conversation with SGLang in OpenWebUI](../../assets/practices/qwen38-a95b-h20/openwebui-sglang-multiturn-light.png)

![Real conversation after connecting vLLM to OpenWebUI](../../assets/practices/qwen38-a95b-h20/openwebui-vllm-chat-light.png)

## 4. Performance Measurement Methodology

Performance requests uniformly go through `/v1/completions`, using a local Tokenizer to generate fixed-length Random Token IDs, with `temperature=0`, `request-rate=inf`, a fixed random seed, and EOS ignored. Each Case is warmed up separately, and the official rounds save raw SSE; a round only passes when the completion count, error count, Usage, and forced output Token count all match expectations.

- **TTFT**: request sent to first non-empty content fragment;
- **Per-request average TPOT**: generation time after the first content fragment divided by `completion_tokens - 1`;
- **Output throughput**: output Tokens produced by successful requests divided by the entire round's wall-clock time;
- **Aggregation**: median of three rounds per configuration, with minimum and maximum values also retained;
- **Failure handling**: failed requests remain in the original denominator and original directory, not automatically re-run to overwrite.

Load covers short requests, 8K Agent long outputs, 4K/16K RAG, 2K Decode, saturated concurrency, and 32K Prefill. Configurations not run due to phase-level absolute deadlines are recorded as `NOT_EXECUTED`, not filled in as zero, and do not enter the median.

## 5. Short Requests and Concurrency Scaling

Each engine planned 62 rounds. SGLang had 45 rounds pass, 2 fail, 10 expire without execution, and 5 skip due to the 32K service window, completing 2,672 official requests; vLLM had 47 rounds pass, 2 fail, 8 expire without execution, and 5 skip, completing 3,696 official requests. Failed and unexecuted rounds do not enter the median, and no re-run results overwrite the original directory.

| Engine | Concurrency | Valid rounds | Output throughput median | P95 TTFT | P95 TPOT | P95 E2E |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| SGLang | 1 | 3 | 51.0 tok/s | 135.6 ms | 18.9 ms | 2.53 s |
| vLLM | 1 | 3 | 65.0 tok/s | 159.8 ms | 14.5 ms | 1.99 s |
| SGLang | 4 | 3 | 139.9 tok/s | 234.4 ms | 28.2 ms | 3.79 s |
| vLLM | 4 | 3 | 158.3 tok/s | 830.2 ms | 22.8 ms | 3.30 s |
| SGLang | 8 | 3 | 190.4 tok/s | 346.8 ms | 41.2 ms | 5.50 s |
| vLLM | 8 | 3 | 231.7 tok/s | 1,040.5 ms | 31.9 ms | 4.49 s |
| SGLang | 16 | 3 | 295.3 tok/s | 558.6 ms | 56.3 ms | 7.70 s |
| vLLM | 16 | 3 | 411.9 tok/s | 924.5 ms | 35.1 ms | 5.13 s |
| SGLang | 32 | 1 | 492.4 tok/s | 701.9 ms | 65.4 ms | 8.69 s |
| vLLM | 32 | 3 | 612.4 tok/s | 1,246.8 ms | 45.8 ms | 7.06 s |

On 128→128 short requests, vLLM's output throughput is approximately 13%–40% higher than this SGLang configuration, with lower TPOT; the cost is significantly higher TTFT at C4–C32. vLLM C16's 411.9 tok/s is 39.5% higher than SGLang, but P95 first-Token latency increases from 558.6 ms to 924.5 ms. SGLang C32 has only one complete round, so this tier only compares direction and does not claim equivalent stability.

![Output throughput and first-Token latency for 128/128 short requests](../../assets/practices/qwen38-a95b-h20/short-throughput.png)

## 6. Agent, RAG, and Long Outputs

| Request Shape | Concurrency | Valid Rounds S/v | SGLang Throughput | vLLM Throughput | SGLang P95 TTFT | vLLM P95 TTFT | SGLang P95 E2E | vLLM P95 E2E |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Agent 8K → 1K | 1 | 3/3 | 48.6 | 60.4 | 1.64 s | 1.76 s | 21.09 s | 16.96 s |
| Agent 8K → 1K | 4 | 3/3 | 134.9 | 150.5 | 2.82 s | 6.95 s | 30.70 s | 28.88 s |
| Agent 8K → 1K | 8 | 3/3 | 231.5 | 192.9 | 4.39 s | 12.89 s | 35.76 s | 45.17 s |
| RAG 4K → 256 | 4 | 3/3 | 127.0 | 119.7 | 2.02 s | 3.61 s | 8.29 s | 8.66 s |
| RAG 4K → 256 | 8 | 1/1 | 196.2 | 144.7 | 2.79 s | 6.08 s | 10.77 s | 14.79 s |
| RAG 16K → 256 | 1 | 3/3 | 36.2 | 41.4 | 2.17 s | 2.32 s | 7.07 s | 6.20 s |
| RAG 16K → 256 | 4 | 3/3 | 98.5 | 53.7 | 4.63 s | 12.53 s | 10.56 s | 20.25 s |
| RAG 16K → 256 | 8 | 3/3 | 135.6 | 57.9 | 8.09 s | 23.33 s | 15.31 s | 44.84 s |
| Decode 128 → 2K | 1 | 3/3 | 53.1 | 69.2 | 0.13 s | 0.15 s | 38.73 s | 29.60 s |
| Decode 128 → 2K | 4 | 3/3 | 146.0 | 205.0 | 0.24 s | 0.83 s | 58.13 s | 40.34 s |
| Decode 128 → 2K | 8 | 3/3 | 200.9 | 292.3 | 0.34 s | 1.02 s | 82.46 s | 56.35 s |

Throughput units in the table are all tok/s. vLLM stands out on 2K long outputs: at C8 throughput is 45.5% higher and P95 E2E is 31.7% lower. The direction flips as input length grows: for 16K RAG at C8, vLLM throughput is 57.9 tok/s versus SGLang's 135.6 tok/s; the corresponding P95 TTFT values are 23.33 s and 8.09 s. Agent at C8 shows a similar turning point. This shows that framework selection must be judged against the real Prefill/Decode ratio; leadership on short requests or pure Decode cannot be extrapolated directly to long documents at high concurrency.

![Agent, RAG, and long-output workloads](../../assets/practices/qwen38-a95b-h20/workload-profile.png)

## 7. Long-Context Validation

The 32K performance rounds use fixed Token IDs to measure Prefill; extending the Context restarts the service, then uses the rendered Chat Template to compute input tokens precisely, and places a unique code in the middle of the document for Needle retrieval. Capacity, speed, and simple recall are recorded separately.

| Engine | Service Context | Server-side Prompt Tokens | Completion Tokens | Needle Depth | Result |
| --- | ---: | ---: | ---: | ---: | --- |
| SGLang | 65,536 | 63,464 | 121 | 50% | PASS |
| SGLang | 131,072 | 129,001 | 95 | 50% | PASS |
| SGLang | 262,144 | 260,073 | 95 | 50% | PASS |
| vLLM | 65,536 | 63,464 | 121 | 50% | PASS |
| vLLM | 131,072 | — | — | — | NCCL initialization failed during service restart |
| vLLM | 262,144 | — | — | — | Not executed after the previous restart failed |

![64K, 128K, 262K long-context validation](../../assets/practices/qwen38-a95b-h20/context-ladder.png)

SGLang returned the unique code correctly at all three sizes; vLLM also completed end-to-end generation at 64K. When vLLM switched to 128K, the worker process on one node exited while re-establishing the 32-Rank communication, and the other ranks subsequently reported `remote process exited or there was a network error`. This result only shows that this particular 128K restart did not succeed; it cannot be used to conclude that vLLM or the model does not support 128K. The 262K run depends on the previous size starting normally, so it was not executed. A single Needle, single depth, and single request also cannot replace multi-depth, multi-Needle, LongBench, or business-dataset evaluation.

## 8. Grafana: Looking at Client, GPU, and RDMA Together

The client exposes success/failure requests, TTFT, TPOT, E2E, and valid output tokens at 5-second intervals; the GPU side collects per-card utilization, GPU memory, power draw, and SM frequency; the RDMA side records per-node send, receive, and wait raw counters. Light-background screenshots are fixed to the full load-test absolute time window, and the raw `query_range` responses are saved together with the images.

![Client performance dashboard](../../assets/practices/qwen38-a95b-h20/grafana-sglang-client-light.png)

![8-card utilization and GPU memory for Pipeline Stage 0](../../assets/practices/qwen38-a95b-h20/grafana-sglang-gpu-light.png)

![Cross-node RDMA dashboard](../../assets/practices/qwen38-a95b-h20/grafana-sglang-rdma-light.png)

vLLM uses the same Dashboard, variables, and time-window scope:

![vLLM client performance dashboard](../../assets/practices/qwen38-a95b-h20/grafana-vllm-client-light.png)

![vLLM 8-card utilization and GPU memory for Pipeline Stage 0](../../assets/practices/qwen38-a95b-h20/grafana-vllm-gpu-light.png)

![vLLM cross-node RDMA dashboard](../../assets/practices/qwen38-a95b-h20/grafana-vllm-rdma-light.png)

Grafana's P95 is a one-minute sliding histogram estimate used to observe phase changes; the tables in the main text use per-request results to compute whole-round statistics, and the two should not be treated as the same value. Discrete sampling also cannot replace per-millisecond peaks or operator-level profiling.

Each engine's full performance window contains 15,392 GPU card-level samples, summarized as follows:

| Full-window metric | SGLang | vLLM |
| --- | ---: | ---: |
| GPU utilization mean | 54.9% | 76.4% |
| GPU utilization P95 | 99.0% | 100.0% |
| GPU memory median | 128,853 MiB | 124,496 MiB |
| Average power draw | 223.4 W | 198.9 W |
| Client one-minute output throughput peak | 521.3 tok/s | 670.3 tok/s |
| Single-node RDMA send rate P95 | 0.114 GiB/s | 0.093 GiB/s |

The window includes load switching and idle gaps, and the rounds that expired without execution are not identical on both sides, so this data describes the overall resource profile rather than per-case energy-efficiency ranking. The local peak of the client one-minute Rate also cannot replace the throughput of formal rounds computed by wall-clock time. The RDMA curves of the four nodes rise in sync during the long-input phase, and the send-wait raw counts remain zero in both runs, indicating that the cross-stage data path keeps working; link limits still need dedicated communication stress testing to confirm.

Downloadable desensitized summaries include [per-case JSON](../../assets/practices/qwen38-a95b-h20/benchmark-summary.json) and [dual-engine per-round CSV](../../assets/practices/qwen38-a95b-h20/benchmark-rounds.csv). The JSON also stores the source results of both runs and the SHA-256 of the Grafana evidence files, making it easy to verify data provenance.

## 9. Where Does It Stand on Cost-Effectiveness Inside an Enterprise

When placing Qwen3.8-2.4T-A95B-FP8 alongside other vendors' flagship open-weight models, the first thing to compare is how many resources a single replica requires, and only then discuss whether the model's capability justifies that cost. The GPU counts below come from configurations already validated in this repository, not the theoretical minimums published by the vendors; the models differ in weight precision, engine, serving window, and request shape, so historical tok/s cannot be ranked directly across them.

| Model | Official Model Scale | Validated H20-3e Configuration in This Repository | Artifacts and Capability Characteristics | Enterprise Deployment Positioning |
| --- | --- | --- | --- | --- |
| Qwen3.8-2.4T-A95B-FP8 | 2.4T total params / 95B active | 4 nodes, 32 GPUs, TP8×PP4 | FP8 snapshot approx. 2.27 TiB; native 262K Context; aimed at code, research, and long-horizon Agent | Highest single-replica threshold; suitable as a pool for hard tasks |
| MiniMax-M3 | 428B total params / 23B active | Single node, 8 GPUs, BF16 TP8 | Measured snapshot 854.18 GB; native multimodal; claims 1M Context | Eight GPUs form a complete service; suitable for a shared multimodal and Agent pool |
| DeepSeek-V4.1-Flash | 552B backbone + 196B Engram / 8B active Prefill, 16B active Decode | Single node, 8 GPUs, TP8 | Measured snapshot approx. 475.25 GiB; native multimodal; claims 1M Context | Lower active compute; suitable for a shared pool focused on throughput, long context, and multimodal |
| GLM-5.3 | Approx. 743B total params / 39B active | Single node, 8 GPUs, native FP8 TP8 | Text model; claims 1M Context | Single-node deployment and replica scaling are easier; suitable as a flagship text-model pool |

Model specifications come from the official model cards of [Qwen3.8](https://huggingface.co/Qwen/Qwen3.8-2.4T-A95B-FP8), [MiniMax-M3](https://huggingface.co/MiniMaxAI/MiniMax-M3), [DeepSeek-V4.1-Flash](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash), and [GLM-5.3](https://huggingface.co/zai-org/GLM-5.3); hardware, snapshot sizes, and available capabilities come from the corresponding measured records in this repository.

Looking at infrastructure cost alone, Qwen3.8-2.4T-A95B-FP8 falls into the **highest-cost, lower-cost-effectiveness tier** among this group of flagship models. One validated replica requires 32 H20-3e GPUs, four times the measured configuration of the other three; this run kept one 2.27 TiB weight copy per node, totaling about 9.08 TiB of local NVMe across four machines. If weights were read directly from CFS instead, local copy cost would drop, but startup bandwidth, concurrent loading, and shared-storage failure domains would become new capacity items.

Converted from the three-round median of the 128/128 short-request runs, SGLang C16's 295.3 tok/s is about **30.1 H20 GPU·hours per million output tokens**, vLLM C16's 411.9 tok/s is about **21.6 H20 GPU·hours per million output tokens**, and vLLM C32's 612.4 tok/s is about **14.5 H20 GPU·hours per million output tokens**. SGLang C32 has only one round and cannot be compared on equal stability grounds. This conversion only describes compute consumption under fixed length and sustained load; it excludes input compute, idle time, storage, CPU, network, failed retries, and power. For 16K RAG, the direction reverses again at high concurrency, so production budgeting must incorporate the real input/output distribution.

Qwen's value must be measured by "how much total cost is needed to complete a task accepted by the business." If the business is mainly internal Q&A, ordinary RAG, summarization, or image understanding, eight-GPU-class flagship models are easier to scale replicas, fail over, and keep at high utilization, and usually offer better deployment economics. If tasks concentrate on complex code, specialized research, and long-horizon Agent, and Qwen can clearly improve the one-shot completion rate, reduce manual review, or reduce the number of tool-call rounds, then the fixed cost of 32 GPUs may be offset by capability gains. Without a quality and success-rate comparison on the same business dataset, the model cannot be written off as "more cost-effective" based on model size alone.

A more practical enterprise approach is layered routing: send routine Chat, RAG, and multimodal traffic to eight-GPU-class models, and escalate hard code, research, and Agent tasks to Qwen; inside the Qwen pool, select the engine or configuration by request shape, and build capacity baselines separately for long-document Prefill and long-output Decode. Capacity planning should look at GPU·hours per million effective output tokens, task success rate, manual review time, and replica utilization together.

## 10. Cross-Node Deployment Recommendations

1. **Plan storage first based on full weights and runtime headroom.** 95B is the per-token active parameter count; the model snapshot is still about 2.27 TiB. Node NVMe must leave room for temporary files, container layers, and runtime logs in addition to the full copy.
2. **Treat the 32 Ranks as one failure domain.** Verify single-machine and cross-machine NCCL values separately before startup, pin HCA, GID, and Socket NICs; monitor Rank heartbeat, RDMA traffic, and server-side Ready together.
3. **Understand where TP8×PP4 traffic flows.** Intra-node TP relies on high-speed GPU interconnect; inter-node PP sends activations to the next Stage. Node selection, Rank order, and network topology must be fixed; simply "having enough total GPUs" is not sufficient.
4. **Check GPU, NIC, and NUMA affinity.** Four-GPU or eight-GPU containers can cross NUMA domains; when CPU threads, Pinned Memory, NIC interrupts, and the GPU's NUMA node are inconsistent, remote memory and cross-socket access occur. First read `nvidia-smi topo -m`, NIC NUMA, and CPU topology, then validate with CPU Manager, Topology Manager, or explicit core pinning.
5. **Pool short and long requests separately.** In this run, vLLM was better at short requests and long outputs, while SGLang was better at 16K RAG under high concurrency; both production concurrency and framework selection should be decided by TTFT/TPOT SLOs and the real input/output distribution.
6. **Design a full restart check for context switches.** If any one of the 32 Rank processes exits, collective communication fails. After every change to Context or cache configuration, first check the new process state of each Rank, then verify `/v1/models`; on failure, keep the logs of the first Rank that exited.
7. **Pin Revision, image Digest, and startup parameters.** Day-0 Runtime changes quickly; after upgrading SGLang, vLLM, FlashInfer, Torch, or drivers, re-run the functional gate and representative workloads.
8. **OpenWebUI is only for acceptance access.** Being able to select the model in the UI and complete a real conversation proves that the OpenAI-compatible path works; it does not replace fixed-token performance testing and structured API acceptance.
