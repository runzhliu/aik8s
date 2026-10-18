---
title: "DeepSeek-V4.1-Flash-1017 Day0: vLLM on Eight H20 GPUs and Million-Token Tests"
description: "Eight-GPU vLLM deployment of native mixed-precision DeepSeek 1017 weights, 36 throughput and latency rounds, tools and vision checks, 1M retrieval, and measured resource curves."
created: 2026-10-18
updated: 2026-10-18
last_reviewed: 2026-10-18
---

# DeepSeek-V4.1-Flash-1017 Day0: vLLM on Eight H20 GPUs and Million-Token Tests

## 1. What changed in 1017

DeepSeek-V4.1-Flash-1017 updates the weights of V4.1-Flash, accepting text and images and producing text. It retains the Mixture of Experts (MoE) architecture and Engram conditional memory. The publisher highlights reasoning, coding, agent tasks, and vision, and reports reduced task execution time and output length. [Official model card](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash-1017)

Deployment must distinguish computation from storage: each token activates only some experts, but serving still requires the full weight set. Engram is a parameter table built into the model. The Key-Value Cache (KV Cache) stores request attention state and grows with context and concurrency. CPU offloading of Engram and prefix caching affect different resource paths.

This test pins model revision `1bae0e1088993b9b82de08f59de5be5a34e42170`, with architecture `DeepseekV41ForCausalLM`. The 48 weight shards total approximately **475.25 GiB**. Native mixed quantization uses FP4 experts, FP8 for other major weights, and UE8M0 scales. [Pinned configuration](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash-1017/blob/1bae0e1088993b9b82de08f59de5be5a34e42170/config.json)

The publisher reports Terminal-Bench 4.0 increasing from 31.2 to 42.3 and DeepSWE v1.1 from 74.2 to 77.0, using its specified Claude Code and Mini-SWE-V2 evaluation environments, respectively. These are publisher results. This article uses deployment, fixed-length load tests, and independent functional samples to examine whether eight GPUs can run the model, what concurrency costs, and whether actual million-token input retrieval completes.

## 2. Eight-GPU deployment and versions

The test uses a single node with **8×H20-3e**. The core matrix executed 36 rounds: 34 had all requests complete, with **1,054/1,056** successful requests overall. Tool and basic vision checks passed. A separate long-context configuration completed seven samples, including three inputs exceeding one million tokens, with all target codes retrieved from three positions.

| Condition | Measured configuration |
| --- | --- |
| GPUs and driver | 143,771 MiB reported per GPU; driver 580.126.20 |
| Interconnect | NV18 between GPU pairs; GPUs 0–3 associated with NUMA 0, 4–7 with NUMA 1 |
| vLLM | 0.32.0rc1.dev329+g39983a5e7 |
| Dependencies | PyTorch 2.14.0+cu130; Transformers 5.19.0; FlashInfer 0.7.2; NCCL 2.30.7 |
| Parallelism and Engram | Tensor parallelism TP8; Engram CPU offload explicitly disabled; expert parallelism not explicitly enabled |
| Base service | Maximum context 32,768; maximum sequences 32; batch token budget 4,096; GPU memory utilization parameter 0.85 |
| Long-context service | Maximum context 1,048,576; maximum sequences 1; other key switches unchanged |
| Caching and speculative decoding | Prefix caching disabled; DSpark not enabled |
| Container resources | CPU request/limit 48/128; host memory 512/1,024 GiB; shared memory 64 GiB |

The vLLM source commit is `39983a5e7a5a575a7829f5d5ada50a33d9337ec1`. The tested image content digest is `sha256:9c482f0f927b7064777c7baf0faafe5721804a9eb8b9bfea9d939cfbc3138348`. This identifies the tested build, not a publicly pullable image reference. Follow the [official Recipe](https://github.com/vllm-project/recipes/blob/main/models/deepseek-ai/DeepSeek-V4.1-Flash.yaml) to prepare a compatible build and verify its actual version.

All eight ranks passed the AllReduce numerical check. This checks single-node communication correctness, not cross-node network bandwidth. Weights were loaded from a read-only shared filesystem. Filesystem caching can affect successive stages, so startup duration was not treated as a controlled cold-start comparison.

The base service used the following arguments, with `/model` as the model directory inside the container:

```bash
vllm serve /model \
  --served-model-name deepseek-v41-flash-1017 \
  --host 0.0.0.0 --port 30000 \
  --tensor-parallel-size 8 \
  --tokenizer-mode deepseek_v41 \
  --reasoning-parser deepseek_v41 \
  --tool-call-parser deepseek_v41 --enable-auto-tool-choice \
  --max-model-len 32768 --max-num-seqs 32 \
  --max-num-batched-tokens 4096 --gpu-memory-utilization 0.85 \
  --no-enable-prefix-caching \
  --limit-mm-per-prompt '{"image":2}' \
  --engram-config '{"cpu_offload":false}'
```

For the long-context stage, the service was restarted with `--max-model-len` set to `1048576` and `--max-num-seqs` to `1`. vLLM initially enabled Engram CPU offload automatically. Before formal measurement, `--engram-config '{"cpu_offload":false}'` explicitly established the GPU Engram baseline used below.

## 3. How the load test was counted

Fixed-length requests used `/v1/completions`, the same pinned vLLM bench client, and the native encoder. Input/output lengths were 1,024/128, 8,192/128, 1,024/512, and 24,576/128 tokens. Each was tested at concurrency C1, C8, and C32 for three rounds, with 8, 16, and 64 requests per round, respectively. The request rate was unlimited but client concurrency was capped. These were finite batch tests, not sustained open-arrival production capacity measurements.

Fixed-length requests used `temperature=0` and `ignore_eos=true`; warmup and calibration were separate. Success required complete stream termination, nonempty content, valid Usage, and the prescribed output length. Failed requests remain in their original denominators; reruns do not replace scores.

- TTFT (Time to First Token): time from request submission to the first nonempty output fragment.
- TPOT (Time per Output Token): each request's time between its first and last output fragments, divided by generated tokens minus one. The table gives P95 across these per-request averages, not P95 across individual token intervals.
- E2E (End-to-End): full request duration. Throughput is successful output tokens divided by the entire round duration.
- Each table metric is the median over complete valid rounds, not a percentile recomputed from pooled requests. Latency includes successful requests. Sample sizes, especially at C1, are too small to extrapolate production tail latency.

The client validation adapter SHA-256 is `bb3bb2f170bd3c398d146aa5471a5f5fd71be2d27a7eb8b86cd64ade3281e0d6`. The [per-round CSV](../../assets/practices/deepseek-v41-flash-1017-day0/core-rounds.csv) retains all 36 rounds, including two incomplete rounds. The [summary JSON](../../assets/practices/deepseek-v41-flash-1017-day0/benchmark-summary.json) contains the figure values.

## 4. More throughput also means more waiting

| Input → output | C | Valid rounds | Success / requests | Output tok/s | P95 TTFT ms | P95 TPOT ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1,024 → 128 | 1 | 3/3 | 24/24 | 125.9 | 162.9 | 6.80 |
| 1,024 → 128 | 8 | 3/3 | 48/48 | 569.2 | 568.5 | 12.68 |
| 1,024 → 128 | 32 | 3/3 | 192/192 | 1,036.8 | 1,843.8 | 28.12 |
| 8,192 → 128 | 1 | 3/3 | 24/24 | 97.3 | 461.0 | 6.74 |
| 8,192 → 128 | 8 | 3/3 | 48/48 | 223.6 | 3,208.9 | 30.96 |
| 8,192 → 128 | 32 | 2/3 | 191/192 | 270.2 | 12,511.8 | 107.41 |
| 1,024 → 512 | 1 | 3/3 | 24/24 | 141.2 | 163.5 | 6.79 |
| 1,024 → 512 | 8 | 3/3 | 48/48 | 727.0 | 566.8 | 10.67 |
| 1,024 → 512 | 32 | 3/3 | 192/192 | 1,566.9 | 1,850.3 | 19.73 |
| 24,576 → 128 | 1 | 3/3 | 24/24 | 58.1 | 1,363.8 | 6.66 |
| 24,576 → 128 | 8 | 3/3 | 48/48 | 90.9 | 9,568.1 | 74.01 |
| 24,576 → 128 | 32 | 2/3 | 191/192 | 98.3 | 36,957.3 | 213.99 |

The second C32 round for 8K→128 and the third C32 round for 24K→128 each had one request fail complete-stream validation, giving 191/192 successes in each cell. Those cells have only two complete rounds and are marked accordingly. The other ten cells have three complete rounds.

For 1K→128, increasing concurrency from C1 to C32 raised output throughput from 125.9 to 1,036.8 tok/s, or **8.24×**, while P95 TTFT rose from 162.9 to 1,843.8 ms, or **11.32×**. Throughput alone hides the increase in waiting time.

![Throughput and first-token wait for the same short request, both normalized to C1](../../assets/practices/deepseek-v41-flash-1017-day0/concurrency-cost-en.png)

Orange is output throughput and purple is P95 TTFT. Both use C1 as 1×, with a shared scale rather than dual axes.

With longer input, additional concurrency yielded less throughput. For 24K→128, C8 to C32 raised throughput from 90.9 to 98.3 tok/s, about 8.1%, while P95 TTFT rose from 9.57 to 36.96 seconds, about 3.86×; C32 also had an incomplete request. Interactive long-document workloads therefore need tighter admission and queue protection at this setting.

For 1K→512 at C32, throughput reached 1,566.9 tok/s with P95 TPOT of 19.73 ms. Longer outputs amortize Prefill, so this throughput cannot be transferred directly to short-answer workloads.

![Actual eight-GPU utilization, memory, power, and temperature during the base matrix](../../assets/practices/deepseek-v41-flash-1017-day0/vllm-short-gpu-overview.png)

This is the actual load-test window. Sampled peaks were 100% GPU utilization, approximately 121 GiB per-GPU memory, 402 W, and 62°C. Memory includes weights, cache preallocation, and runtime workspace; it is not 121 GiB of model weights. These peaks need not occur simultaneously on all eight GPUs.

## 5. Historical comparison with the original V4.1-Flash

The earlier [eight-H20 V4.1-Flash test](deepseek-v41-flash-h20-day0.md) already used 8×H20-3e, GPU Engram, a 32K serving context, and the same four input/output lengths. Both experiments used fixed-length synthetic requests, disabled prefix caching, and repeated each cell three times, allowing a comparison of deployment behavior at matching request shapes.

The comparison consistently selects **C8** for all four workloads: both deployments have three complete rounds and 48/48 successful requests per cell. This avoids C32 cells with different complete-round counts. Metrics were recalculated as medians from retained per-round data; synthetic inputs were not byte-for-byte replays.

| Input → output / C8 | Previous tok/s | 1017 tok/s | Change | Previous TTFT s | 1017 TTFT s |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1K → 128 | 404.25 | 569.24 | +40.8% | 1.176 | 0.569 |
| 8K → 128 | 97.63 | 223.56 | +129.0% | 9.194 | 3.209 |
| 1K → 512 | 613.74 | 726.95 | +18.4% | 1.177 | 0.567 |
| 24K → 128 | 35.09 | 90.92 | +159.1% | 26.228 | 9.568 |

![Relative changes for matching C8 workloads in the two deployments](../../assets/practices/deepseek-v41-flash-1017-day0/v41-comparison-en.png)

Across these four C8 workloads, throughput increased by 18.4%–159.1% and P95 TTFT decreased by approximately 51.6%–65.1%. For 24K input, waiting fell from 26.23 to 9.57 seconds, still substantial for an interactive service. Short-request waiting fell from approximately 1.18 to 0.57 seconds. These are changes between two actual deployments.

Configuration differences affecting the comparison are:

| Item | Original V4.1-Flash deployment | 1017 deployment |
| --- | --- | --- |
| vLLM | 0.1.dev1+g79a7108d9 | 0.32.0rc1.dev329+g39983a5e7 |
| PyTorch | 2.13.0+cu130 | 2.14.0+cu130 |
| Batch token budget | 8,192 | 4,096 |
| Expert parallelism | Explicitly enabled | Not explicitly enabled |
| CPU request / limit | 64 / 128 | 48 / 128 |
| Model revision | fb2764a5cf321eaa5070ca8f9e892818f477c16d | 1bae0e1088993b9b82de08f59de5be5a34e42170 |

Model weights, engine implementation, and scheduling budgets changed together, so the isolated benefit of the 1017 weights cannot be extracted from these records. The supported conclusion is that **1017 with this newer vLLM configuration was faster in these historical scenarios at matching lengths and concurrency**. Fixed-length output tests also do not verify the publisher's shorter-natural-output claim.

The original core matrix had 32/36 complete rounds and 1,051/1,056 successful requests; this run had 34/36 and 1,054/1,056. Both had incomplete requests, and short tests cannot establish improved stability. The original model also advertised 1M context; its earlier experiment only reached 24K. This test adds actual retrieval evidence beyond 1.04 million input tokens. [Comparison values and conditions](../../assets/practices/deepseek-v41-flash-1017-day0/v41-deployment-comparison.json) are provided with the article.

## 6. Functional checks and actual prompts

Basic text, Chinese and English, multi-turn memory, complete streaming, tool calls, and image-content sensitivity checks passed. Tool validation checked the function name and arguments, returned a simulated tool result, and checked the model's final answer. Vision checks varied image content and order instead of merely testing whether the API accepted an image.

A separate set contained 12 small tasks, repeated three times each, using `temperature=1.0`, `top_p=1.0`, and low reasoning effort. Strict JSON validation passed **33/36**. Selected original prompts were:

```text
Compute 19 * 23. Reply with the integer only.

Extract fields into JSON with keys name, department, seats: Ada works in platform and requested 6 seats.

Return JSON with keys items and total: 3 apples at 4 credits each, 2 books at 11 credits each.
```

The first task should return 437; the field extraction should return Ada, platform, and 6. All three failures were the order task: validation expected `items` to be the count 5, but the model interpreted it as an array of item details, while still calculating total 34 correctly. The prompt omitted the field type, making the acceptance criterion ambiguous. The original 33/36 is retained without inferring an arithmetic failure or treating this small set as a capability leaderboard.

## 7. How far the million-token requests actually reached

Each synthetic document contained three independent random codes, inserted at approximately 10%, 50%, and 90% of the body. The model retrieved codes for specified project names and returned an exactly matching JSON object. The core instruction was:

```text
Return only a JSON object mapping each requested project name to its access_code.
```

The native encoder counted input tokens before submission, and the count was checked against server Usage. The output budget was 4,096 tokens, with early completion allowed. TTFT below starts at the first generated content fragment, which may include reasoning; E2E includes completion of the final JSON.

| Context / seed | Actual input tokens | Output tokens | TTFT s | E2E s | Retrieval |
| --- | ---: | ---: | ---: | ---: | --- |
| 64K / 101701 | 57,285 | 187 | 3.25 | 4.52 | PASS |
| 128K / 101701 | 122,881 | 309 | 6.81 | 8.92 | PASS |
| 256K / 101701 | 253,900 | 206 | 15.28 | 16.66 | PASS |
| 512K / 101701 | 516,033 | 168 | 36.12 | 37.20 | PASS |
| 1M / 101701 | 1,040,333 | 209 | 97.23 | 98.56 | PASS |
| 1M / 101702 | 1,040,325 | 192 | 97.18 | 98.38 | PASS |
| 1M / 101703 | 1,040,323 | 194 | 97.07 | 98.28 | PASS |

All seven records had zero difference between local encoding counts and server input Usage. Each of the three 1M inputs contained approximately **1.04 million tokens**, and all codes at all three positions were retrieved. First-token time was about 97 seconds and the complete request about 98 seconds. Each seed had one request: this verifies long-context reachability and synthetic retrieval, not multi-user 1M serving capacity or complex long-document reasoning.

![Eight-GPU resource curves during the separate long-context stage](../../assets/practices/deepseek-v41-flash-1017-day0/vllm-long-gpu-overview.png)

Sampled peaks in this window were 100% utilization, approximately 128 GiB per-GPU memory, 387 W, and 64°C. The base and long-context services used different memory budgets. Each figure corresponds to its own stage; the stages are not stitched together into a single performance curve.

## 8. Deployment recommendations and test boundaries

**Set a waiting-time target before choosing concurrency.** Short requests gain throughput from concurrency, but long inputs show substantial queuing costs. Consider separate queues by input length, limits on long-request concurrency, and overload rejection or timeout policies. C32 should not be copied directly into production admission settings.

**Configure 32K and 1M separately.** This test used a single-sequence 1M service, with inputs near the context limit. Mixing long and short requests requires separate measurements of scheduling interference, workspace, and cache capacity. Raising the context-limit parameter alone does not answer those questions.

**Pin the native protocol and Engram location.** The model repository uses V4.1 native encoding; tokenizer, reasoning parser, and tool parser must match. CPU offloading changes host-memory and PCIe paths and needs a separate test. Do not mix results obtained with different Engram placements.

**Allocate GPUs, CPUs, and memory with topology in mind.** Non-Uniform Memory Access (NUMA) affects host-to-device paths. Check the expected GPU interconnect domain, then use process CPU affinity and memory policy to investigate bottlenecks. This test did not perform a CPU-affinity A/B comparison.

A separate historical-length auxiliary matrix planned 12 rounds but executed six, with one complete round. It stopped after consecutive failures, leaving six unexecuted. The rate-controlled Service Level Objective (SLO) scan did not run because its required complete reference was unavailable. Neither stage is included in the 36-round core matrix. This article therefore gives no long-term stability or production SLO capacity result.

RTX PRO 5000 Blackwell 48GB was not measured here. Native weight files total approximately 475.25 GiB, so one 48GB GPU cannot hold the full weights under this article's GPU Engram configuration. Multi-GPU or offloaded deployments require separate checks of memory, bandwidth, and engine support.

## References

- [DeepSeek-V4.1-Flash-1017 model card](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash-1017)
- [Pinned model configuration](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash-1017/blob/1bae0e1088993b9b82de08f59de5be5a34e42170/config.json)
- [vLLM V4.1 Recipe](https://github.com/vllm-project/recipes/blob/main/models/deepseek-ai/DeepSeek-V4.1-Flash.yaml)
