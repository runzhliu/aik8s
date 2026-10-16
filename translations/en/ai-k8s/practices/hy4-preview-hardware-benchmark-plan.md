---
title: "Hy4-preview BF16 on Dual-Node H20: SGLang vs vLLM — How to Choose"
date: 2026-09-01
authors:
  - runzhliu
categories:
  - Inference
  - Hands-on
description: "Deployed Hy4-preview BF16 on two 8×H20 nodes with SGLang TP16 and vLLM TP8×PP2, covering functional acceptance, RDMA verification, 130K stress testing, and Needle/Agent correctness tests."
---

# Hy4-preview BF16 on Dual-Node H20: SGLang vs vLLM — How to Choose

Tencent released and open-sourced Hy4-preview on August 28, 2026. It is an MoE model with 770B total parameters and 49B activated parameters: the backbone has 78 layers in total, with 77 MoE layers after the first Dense layer; each layer contains 256 routed experts and 1 shared expert, using Top-8 routing, plus a native MTP layer with approximately 10B total parameters and 0.7B activated parameters. The model also introduces Gated DSA, IndexCache, and iHC, with a declared native context limit of 1,048,576 tokens. [Tencent's official release notes](https://www.tencent.com/zh-cn/tencent-releases-and-open-sources-tencent-hy4-preview/) and the [official repository](https://github.com/Tencent-Hunyuan/Hy4-preview) provide the full architecture.

The most common pitfall at launch is FP8: the official `Hy4-preview-FP8` uses ModelOpt MXFP8, and the main execution path requires SM100+; the H20 belongs to Hopper/SM90, and even if GPU memory can hold the weights, it cannot remove the GPU generation limitation. Therefore, this test did not force FP8, but instead chose the full BF16 checkpoint, validating SGLang and vLLM separately on two nodes each with 8 141GB H20 GPUs.

Conclusions first:

- **Hy4-preview BF16 can stably run at 130K context on 2×8 H20.** Functional smoke tests, OpenWebUI conversations, all formal performance requests, and 9 Needle test groups at 32K/64K/126K plus multi-turn Agent tool calls all passed on both engines.
- **For short requests, RAG, and high-concurrency throughput, choose SGLang.** At 128/64, C32, output throughput is 377.30 token/s vs vLLM's 278.97 token/s, with SGLang 35.2% higher.
- **Long context is not the same answer.** At 32K, SGLang has lower TTFT; with Prefix Cache disabled, vLLM overtakes at 64K and 130K, with 130K TTFT 17.2% lower than SGLang and E2E 8.6% lower.
- This is a **production deployment recipe comparison**, not a pure engine micro-benchmark: SGLang uses TP16, vLLM uses its natively recommended TP8×PP2. GPU model, count, weights, context, request set, and client are identical, but the parallel topology differs.

## Test Environment and Fairness Boundaries

The BF16 weights consist of 131 Safetensors shards referenced by the official Index, with an actual size of 1,559,983,809,380 bytes, i.e., 1,452.85 GiB. To avoid shared storage reads interfering with startup and stress testing, the weights were pre-cached to the local NVMe XFS on both host machines, then mounted into containers as read-only directories; the services did not silently fall back to shared storage.

| Item | SGLang | vLLM |
| --- | --- | --- |
| GPU | 2 nodes × 8 H20 141GB | Same two nodes, same 16 GPUs, serially reused |
| Precision | BF16 | BF16 |
| Parallel topology | TP16, cross-node Tensor Parallel | Intra-node TP8, inter-node PP2 |
| Context | 131,072 | 131,072 |
| Max concurrency / Batched tokens | 16 / 16,384 | 16 / 16,384 |
| MTP | Off | Off |
| Attention | HYV4 Hopper-compatible path | `FLASHMLA_SPARSE` Hopper-compatible path |
| Prefix Cache | `disable-radix-cache` | Formal long-context rounds use `no-enable-prefix-caching` |
| Image | `lmsysorg/sglang:hy4-preview`, pinned amd64 Digest | `vllm/vllm-openai:hy4-preview`, pinned amd64 Digest |
| Client | `vllm bench serve --backend openai` | Identical |

The client fixes input/output lengths: `random-range-ratio=0`, `request-rate=inf`, `temperature=0`, `ignore-eos`. Short requests and RAG record three rounds per case; 4K Decode and long context record two rounds; the data in the tables is the "median of per-round metrics," not the fastest single run. Each engine accounts for 3,364 formal requests, 6,728 in total, with 0 failed requests.

Two additional disclosures are required:

1. One round of SGLang C1 short requests was polluted by an OpenWebUI request. The raw JSON is retained, but the formal summary excludes that round and uses a clean replacement re-run with identical parameters.
2. The vLLM development image enables Prefix Cache by default, and the test image does not expose a cache reset interface. The first 64K P50 TTFT was only 9.95 seconds, and service metrics subsequently confirmed cache hits. That long-context data point is marked as diagnostic and does not enter the formal conclusions; after explicitly adding `--no-enable-prefix-caching` to the service and restarting, six rounds of 32K/64K/130K were re-run with a new seed and zero warmup. The corrected 64K P50 TTFT is 19.41 seconds.

The short-request, RAG, and Decode tables retain the full first-round matrix, where vLLM still uses the image-default Prefix Cache On; random requests and the formal request count reduce the impact of a hot cache on fixed prompts, but cannot prove the hit rate is strictly zero. Since these cases ultimately still favor SGLang, this bias cannot create an advantage for SGLang — it may instead make the advantage appear smaller; for a strict same-cache-state micro-benchmark, these should also be fully re-run with Prefix Cache Off.

The second point is especially important: the same client and the same parameter set do not mean the server-side state is automatically identical. Without checking cache metrics, long-context results can easily appear "twice as fast."

## Deployment Results: Both Can Reach Ready, but via Compatible Paths

### SGLang TP16

SGLang takes approximately 218 seconds from container startup to API Ready. Weight loading takes approximately 52.34 seconds, with per-GPU model footprint at 93.31GB per the logs; after CUDA Graph completes, approximately 20.65GB remains, `max_total_num_tokens=233920`.

### vLLM TP8×PP2

vLLM takes approximately 171 seconds from container startup to API Ready. The loader reads 131 shards from local NVMe in 20.46 seconds, per-rank model loading takes approximately 22.41–33.42 seconds, with per-GPU footprint at 90.48GiB; KV Cache is 9.65GiB/GPU, 193,152 tokens.

Since the H20 is SM90, the vLLM logs explicitly disable HPC Gated MLA and iHC, which only support SM100/SM103, and select sink-capable `FLASHMLA_SPARSE` and TritonExperts. In other words, the service does run successfully, but it cannot be described as "the H20 obtained the full performance of Blackwell-specific kernels." SGLang likewise follows the H20 experimental compatibility route, not an official Verified-hardware conclusion.

| Startup observation | SGLang TP16 | vLLM TP8×PP2 |
| --- | ---: | ---: |
| Container startup to API Ready | ~218 s | ~171 s |
| Weight loading (log) | 52.34 s | 20.46 s |
| Per-GPU model footprint | 93.31GB | 90.48GiB |
| Available token capacity | 233,920 | 193,152 |

These values come from each runtime's own logs, with inconsistent measurement scopes; they are suitable for explaining startup behavior and capacity, but "weight loading seconds" should not be used alone as a framework total-performance ranking.

## RDMA: Not Just Seeing the Devices — GDRDMA Was Actually Used

Each of the two nodes has 8 200Gb/s RoCE devices. Since the test nodes did not publish RDMA Extended Resources, the controlled experiment used HostNetwork, read-only device mounts, and temporary Privileged mode to let the container access `/dev/infiniband`; long-running services should still add the RDMA Device Plugin rather than keeping this test workaround.

Both runtimes' NCCL logs simultaneously showed:

- `Using network IB`;
- 8 RoCE rails;
- cross-node `NET/IB/.../GDRDMA`;
- GDR enabled.

Runtime counters were not static either: all 16 GPUs reached 100% utilization during heavy-load sampling, and the 8 RDMA send counters grew in sync. SGLang observed 50.278Gbit/s in a 10-second window during 130K Prefill; vLLM observed 1.309Gbit/s in a window during 16K/130K Prefill. The sampling moments and TP/PP communication patterns differ between the two, **so these numbers only prove the links are active and cannot be directly used as a framework network bandwidth ranking.**

## Functional Smoke: All OpenAI-Compatible Capabilities Passed

Both services passed the following items:

- `/v1/models` returns the correct model;
- High Thinking returns both reasoning and the final answer;
- `no_think` returns final content without attached reasoning;
- Streaming responses receive `[DONE]`;
- OpenAI-compatible Tool Call returns structured function names and JSON arguments;
- Image input is correctly rejected with HTTP 400 by the text-only model.

There is one compatibility difference in fields: SGLang returns `reasoning_content`, while this vLLM version returns `reasoning`. A caller that hard-codes only one field will misjudge "has reasoning content" as "does not." The smoke script therefore supports both key names.

After performance testing, both services also completed real conversations through the same OpenWebUI connection, with the model ID kept as `hy4-preview`, switching only the backend service. Screenshots are forced to Light mode and contain no intranet addresses.

![Real conversation acceptance of SGLang and vLLM via OpenWebUI](../../assets/practices/hy4-preview-h20/openwebui-vllm-light.jpg)

## Short Requests: SGLang Leads at All Concurrency Levels

![Hy4-preview BF16 short-request output throughput](../../assets/practices/hy4-preview-h20/short-throughput.svg)

| Concurrency | SGLang output tok/s | vLLM output tok/s | SGLang P50 TTFT | vLLM P50 TTFT |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 42.53 | 37.47 | 98ms | 250ms |
| 4 | 139.90 | 110.02 | 162ms | 509ms |
| 8 | 239.39 | 164.56 | 238ms | 551ms |
| 16 | 376.56 | 274.59 | 384ms | 753ms |
| 32 | 377.30 | 278.97 | 3.09s | 4.11s |

SGLang continues to scale throughput from C1 to C16, entering a plateau after C16; vLLM also saturates around C16, but at a lower plateau value. SGLang's output throughput advantage over vLLM grows from 13.5% at C1 to 45.5% at C8, and remains 35.2% higher at C32. For short conversations, high-frequency short Agent calls, and high-concurrency online services, this recipe should prioritize SGLang.

## RAG and Decode: Prefill Favors SGLang, Single-Stream Long Output Is Close

| Case | SGLang output tok/s | vLLM output tok/s | SGLang P50 TTFT | vLLM P50 TTFT | SGLang P50 E2E | vLLM P50 E2E |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| RAG 4K→128, C4 | 56.82 | 42.24 | 4.24s | 6.76s | 9.01s | 12.22s |
| RAG 16K→256, C4 | 36.11 | 30.12 | 15.11s | 18.05s | 28.35s | 36.12s |
| Decode 128→1K, C1 | 39.76 | 38.31 | 104ms | 249ms | 25.76s | 26.73s |
| Decode 128→1K, C8 | 241.37 | 186.43 | 248ms | 638ms | 33.90s | 43.92s |
| Decode 128→4K, C1 | 32.37 | 31.52 | 98ms | 250ms | 126.53s | 129.94s |

SGLang's output throughput for RAG 4K and 16K is 34.5% and 19.9% higher respectively, with lower TTFT as well. Single-concurrency pure Decode is much closer: 1K and 4K output throughput leads by only 3.8% and 2.7%; when concurrency rises to 8, SGLang's batching advantage re-expands to 29.5%.

## Long Context: 32K Goes to SGLang, 64K/130K Shifts to vLLM

All formal long-context results have Prefix Cache disabled. SGLang uses `disable-radix-cache`; vLLM explicitly uses `no-enable-prefix-caching` on the server side, and runtime metrics confirm the configuration is False.

![Hy4-preview BF16 long-context P50 TTFT](../../assets/practices/hy4-preview-h20/long-context-ttft.svg)

| Case | SGLang output tok/s | vLLM output tok/s | SGLang P50 TTFT | vLLM P50 TTFT | SGLang P50 E2E | vLLM P50 E2E |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 32K→128, C1 | 9.06 | 8.17 | 9.84s | 11.22s | 14.11s | 15.57s |
| 64K→128, C1 | 5.15 | 5.40 | 20.59s | 19.41s | 24.86s | 23.73s |
| 130K→1K, C1 | 13.02 | 14.24 | 44.15s | 36.57s | 78.64s | 71.90s |

At 32K, SGLang still leads; at 64K, vLLM's TTFT is 5.7% lower and E2E 4.6% lower; at 130K, vLLM's TTFT is 17.2% lower, E2E 8.6% lower, and output throughput 9.4% higher. This shows that "who is faster for short requests" cannot be directly extrapolated to 130K — TP16 and TP8×PP2 have different compute/communication balances under ultra-long Prefill.

## Long-Context Correctness: 9 Needle Groups and Multi-Turn Agent All Passed

Beyond throughput testing, both services each ran three context tiers — 32K, 64K, and 126K — with a unique random Needle placed at 10%, 50%, and 90% depth per tier. Requests used the server-side `usage.prompt_tokens` to calibrate actual length, requiring the model to return only the unique Needle; both sides achieved **9/9 PASS**.

![Hy4-preview BF16 long-context correctness gate](../../assets/practices/hy4-preview-h20/correctness-gates.svg)

| Context / Needle Depth | SGLang | vLLM |
| --- | ---: | ---: |
| 32K / 10%, 50%, 90% | 10.61s / 10.21s / 10.22s | 12.52s / 11.47s / 11.46s |
| 64K / 10%, 50%, 90% | 21.12s / 20.97s / 20.98s | 19.55s / 19.55s / 19.55s |
| 126K / 10%, 50%, 90% | 42.93s / 42.86s / 42.86s | 35.70s / 35.70s / 35.71s |

A four-stage Agent flow was then executed: query inventory, calculate shipping cost, reserve inventory, and generate a final summary based on the three tool results. Both engines produced structured Tool Calls in sequence, correctly arriving at remaining inventory 4, shipping cost 42, arrival in 2 days, and the reservation order number, with Agent Gate PASS for both. This validates the correctness of the deterministic tool chain, and does not mean production Agent traffic distribution has been covered.

Not continuing to send 1M requests is not skipping a test case. The service startup logs show that in the current 16×H20 BF16 configuration, SGLang's `max_total_num_tokens` is 233,920 and vLLM's KV Cache capacity is 193,152 tokens, which are only about 22.3% and 18.4% of the model's declared 1M Context, respectively. Changing the Context parameter to 1M will not magically increase KV/state capacity; it will only trigger capacity failure at startup or request stage. Therefore, 1M is a clear **capacity Gate failure** in this round; after single-variable solutions such as more GPUs, deeper PP/DCP, or lower-precision KV, correctness verification should be done step by step from 256K to 1M.

## How to choose

If the current business is dominated by short conversations, RAG, tool calls, and concurrent Agents, prioritize **SGLang TP16**: both throughput and TTFT advantages are more stable, and the power consumption and GPU memory sampling across the two nodes are more symmetric.

If the business core is 64K–130K single requests and the TP8×PP2 Pipeline characteristics are acceptable, you can continue to evaluate **vLLM**: it starts faster and has better formal no-prefix long-context results. However, Blackwell-specific HPC MLA/iHC is disabled on H20, and the two PP stages also show transient power asymmetry, so this round's results cannot be extended into conclusions for all concurrency, all contexts, and all hardware.

What is worth doing next is not repeating this table, but:

- Run MTP Off/On single-variable A/B on the same Runtime and record Acceptance Length;
- Test the cold/hot hit benefits of the Prefix Cache required by production separately;
- Add ShareGPT, real RAG, Tool Call, and multi-turn Agent mixed workloads to cover latency and success rate under production distribution;
- After scaling up or lowering KV precision, verify step by step from 256K to 1M, continuing to use Needle/retrieval Gate;
- Run the official MXFP8 Recipe on Blackwell to avoid treating the H20 compatibility path as the model ceiling.

## Limitations

- Only one pair of H20 nodes and one time window were tested, without repetition across multiple machine groups;
- The two frameworks use their own implementable native parallel topologies, so this is not a pure same-topology engine comparison;
- Performance data comes from fixed-length random tokens; the added Needle and deterministic Agent verified content correctness, but still cannot represent production prompts and mixed concurrency distribution;
- MTP is off, and production hot-hit benefits of Prefix Cache are not within this round's conclusions;
- The 16×H20 BF16 Runtime capacity is insufficient to carry 1M, and 1M acceptance after scaling up / low-precision KV was not completed;
- RDMA and power consumption are time-window samples, used only to prove link and load status, not for strict energy-efficiency ranking.

## Reproduction data

The experiment archive is located at `examples/hy4-preview-benchmark/results/2026-09-01-h20-bf16`, and the README in the directory indicates which results entered the official summary and which are kept only as cache diagnostic evidence. The archive contains local experiment metadata such as runtime paths, which is not part of the public page; public documents and charts use only summary values and do not contain intranet addresses, node names, private image registries, mount paths, or credentials.

## References

- [Tencent: Tencent Releases and Open-Sources Tencent HY 4.0](https://www.tencent.com/zh-cn/tencent-releases-and-open-sources-tencent-hy4-preview/)
- [Tencent-Hunyuan/Hy4-preview official repository](https://github.com/Tencent-Hunyuan/Hy4-preview)
- [Hy4-preview BF16 model card](https://huggingface.co/tencent/Hy4-preview)
- [SGLang Hy4-preview Cookbook](https://lmsysorg.mintlify.app/cookbook/autoregressive/Tencent/Hy4-Preview)
- [vLLM Hy4-preview Recipe](https://recipes.vllm.ai/tencent/Hy4-preview)
