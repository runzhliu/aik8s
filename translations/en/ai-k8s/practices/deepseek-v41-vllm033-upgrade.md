---
title: Testing vLLM 0.33.0 Against 0.32.0 for DeepSeek-V4.1-Flash on H20-3e
description: Measure vLLM 0.33.0 on eight H20-3e GPUs and compare throughput, latency, and streaming integrity with historical 0.32.0 results.
date: 2026-11-04
last_reviewed: 2026-11-04
---

# Testing vLLM 0.33.0 Against 0.32.0 for DeepSeek-V4.1-Flash on H20-3e

DeepSeek-V4.1-Flash is a multimodal Mixture-of-Experts (MoE) model with Engram conditional memory. We previously [tested vLLM 0.32.0](deepseek-v41-vllm032-upgrade.md) on eight H20-3e GPUs. With version 0.33.0 available, the practical question is how much changes under the same model and comparable workload settings.

We run the benchmark on 0.33.0 and compare it with retained 0.32.0 results. The runs took place on different dates and nodes; this is a historical comparison rather than a strictly paired same-node A/B experiment.

## 1. Model-related changes in 0.33.0

The [vLLM 0.33.0 release notes](https://github.com/vllm-project/vllm/releases/tag/v0.33.0rc3) describe Humming improvements for DeepSeek V4/V4.1 experts on Hopper, along with changes to speculative decoding and context parallelism. The reported results use different GPUs, models, and configurations; they are not expected gains on H20-3e.

For example, the [Humming optimization PR](https://github.com/vllm-project/vllm/pull/61875) reports improvements for some decode workloads using DeepSeek-V4-Flash on four H200 GPUs, but also records regressions at low concurrency. The 0.33.0 startup log records selection of the Humming MXFP4 MoE backend, MXFP8 activations running as block FP8 on Hopper, and SWA bounded replay. This establishes that these paths were selected, not their individual performance contributions. Our comparison measures complete images and their default execution paths; total throughput differences alone cannot identify a single responsible kernel.

## 2. Method

| Item | Configuration |
| --- | --- |
| Model | Original `deepseek-ai/DeepSeek-V4.1-Flash`; revision `fb2764a5cf321eaa5070ca8f9e892818f477c16d`; not the 1017 version |
| GPUs and parallelism | One node with 8×H20-3e; tensor parallelism TP8 with expert parallelism EP |
| Limits | 32,768-token context, 32 concurrent sequences, 8,192 batched tokens; GPU memory utilization 0.85 |
| Other settings | Engram on GPU, prefix caching disabled, DSpark disabled; same tokenizer, client and random seeds |
| 0.32.0 | Previously measured historical data; not rerun |
| 0.33.0 | Pinned official image; prefix caching disabled using `--disable-prefix-caching` |

The main matrix covers 10 input, output and concurrency combinations, with three formal rounds per combination. Warmups are recorded separately. A successful request requires HTTP 200, nonempty text, a complete stream end, valid usage and the expected output length. Invalid responses remain in the denominator; latency percentiles cover valid responses only. Output throughput is valid output tokens divided by the full round duration; the reported statistic is the median of three rounds.

### Image and startup parameters

The 0.33.0 run uses the upstream official image's amd64 platform manifest digest `sha256:91ee972ab751fb7180bc71c175865e36b091686600dca783d52b2511399810b3`. The comparison includes the entire image and its dependencies:

| Component | 0.32.0 | 0.33.0 |
| --- | --- | --- |
| Torch | `2.13.0+cu130` | `2.14.0+cu130` |
| Transformers | `5.19.0` | `5.20.2` |
| FlashInfer | `0.7.0.post1` | `0.7.2.post1` |
| Humming | `0.1.17` | `0.1.19` |

`pip check` in the 0.33 image reported NCCL and OpenTelemetry version-constraint mismatches. NCCL communication, model startup, and the request tests described here ran, but that does not establish that every dependency constraint is satisfied. Verify your own environment.

In the command below, `/model` is the container mount point for the read-only model directory:

```bash
vllm serve /model \
  --served-model-name deepseek-v41-flash \
  --tensor-parallel-size 8 --enable-expert-parallel \
  --max-model-len 32768 --max-num-seqs 32 --max-num-batched-tokens 8192 \
  --gpu-memory-utilization 0.85 --tokenizer-mode deepseek_v41 \
  --reasoning-parser deepseek_v41 --tool-call-parser deepseek_v41 \
  --enable-auto-tool-choice --engram-config '{"cpu_offload":false}' \
  --disable-prefix-caching --host 0.0.0.0 --port 30000
```

Per-round statistics, result-file hashes, and supplementary results are available in the [public data file](../../assets/practices/deepseek-v41-vllm033-upgrade/results.json).

## 3. Main matrix results

Output throughput is in token/s and shown as the median of three rounds; success counts retain the original request denominators. Observed change is shown only when neither version had failures. Throughput for cases with failures remains descriptive and is not used to calculate upgrade gains.

| Input→output / concurrency | Historical 0.32.0 | 0.33.0 | 0.32 successes / requests | 0.33 successes / requests | Observed change |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1,024→128 / C32 | 1015.77 | 1322.74 | 190/192 | 191/192 | — |
| 8,192→128 / C1 | 82.94 | 92.22 | 24/24 | 24/24 | +11.2% |
| 8,192→128 / C8 | 217.46 | 291.74 | 48/48 | 48/48 | +34.2% |
| 8,192→128 / C32 | 263.14 | 375.20 | 190/192 | 190/192 | — |
| 1,024→512 / C1 | 113.69 | 115.32 | 24/24 | 24/24 | +1.4% |
| 1,024→512 / C8 | 676.93 | 760.58 | 48/48 | 47/48 | — |
| 1,024→512 / C32 | 1576.39 | 1933.22 | 190/192 | 190/192 | — |
| 24,576→128 / C1 | 52.25 | 63.37 | 23/24 | 23/24 | — |
| 24,576→128 / C8 | 87.57 | 123.56 | 47/48 | 47/48 | — |
| 24,576→128 / C32 | 94.78 | 137.79 | 189/192 | 190/192 | — |

![Cases in which all requests succeeded in both versions](../../assets/practices/deepseek-v41-vllm033-upgrade/throughput-en.png)

All 30 formal rounds and 10 warmups in the main matrix matched the historical request fingerprints. We did not repeat the earlier open-loop arrival-rate test; the historical 0.300 requests/s run included failures and does not establish a failure-free capacity limit.


### Time to first content and token latency

Each cell is the median of the three per-round P95 values, in milliseconds. P95 TTFT is the wait for the first nonempty content; P95 TPOT is the per-request average time per output token. Only cases with valid responses for both versions are shown.

| Case | TTFT 0.32 | TTFT 0.33 | TPOT 0.32 | TPOT 0.33 |
| --- | ---: | ---: | ---: | ---: |
| 8,192→128 / C1 | 472.40 | 328.86 | 8.46 | 8.35 |
| 8,192→128 / C8 | 3,428.99 | 2,356.67 | 32.85 | 24.48 |
| 1,024→512 / C1 | 164.59 | 157.13 | 8.52 | 8.41 |

![Average utilization, memory, power and temperature across eight GPUs during the main run](../../assets/practices/deepseek-v41-vllm033-upgrade/gpu-evidence-primary.png)

The real monitoring screenshot shows eight-GPU averages over the main test window. Averages do not replace per-GPU fault checks. Fluctuations include different cases and gaps and should not be read as a fixed utilization for one workload.

## 4. Empty output and upgrade acceptance

In completed cases, some streaming requests returned HTTP 200 but did not pass the complete checks for nonempty content, a stream-end marker and usage. The previous 0.32.0 test also observed responses without valid text. Separate empty output, missing end markers and missing usage in the final diagnosis, preserving the responses as evidence; HTTP 200 alone does not establish successful generation.

In the main matrix, 0.33.0 returned 974/984 valid responses. All 10 invalid responses had an end marker and usage but failed the nonempty-text check; the historical 0.32.0 result was 973/984. Both samples are limited and come from different nodes and dates, so they do not establish an improvement or regression in failure rate.

Parsing each of the 10 failed streams showed HTTP 200, an end marker and usage, with `finish_reason` equal to `length` but no nonempty `choices[].text` fragment. Seven reported 128 completion tokens and three reported 512. The cause remains unknown. A follow-up should retain output token IDs and replay the same conditions against non-streaming, natural-language, and non-`ignore-eos` requests. The failure ratio from this synthetic fixed-length workload is not a production failure rate.

## 5. Tools, images and deployment guidance

Tool calling and vision checks passed in both runs: tool-argument parsing, tool-result roundtrip, and single- and two-image recognition. These samples do not establish correctness for every tool or vision task. Historical 0.32.0 data for these cases came from a separate batch and should be interpreted separately; per-round request fingerprints matched across versions.

| Input→output / concurrency | Historical 0.32.0 | 0.33.0 | Successes / requests per version | Observed change |
| --- | ---: | ---: | ---: | ---: |
| 1,024→128 / C1 | 103.80 | 105.21 | 24/24 | +1.4% |
| 1,024→128 / C8 | 535.18 | 622.88 | 48/48 | +16.4% |
| 4,096→128 / C32 | 463.20 | 642.71 | 384/384 | +38.8% |

Output throughput is in token/s and shown as the median of three rounds; 4K/C32 has 128 requests per round.


For an upgrade, pin the model revision, inference image, dependencies, parallelism and service endpoint first. Validate complete streams and quality with actual application requests, then compare throughput, time to first token, memory and power. Improvements can differ between low and high concurrency, so evaluate them against the workload distribution.

## References

- [DeepSeek-V4.1-Flash model card](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash)
- [vLLM 0.33.0 release notes](https://github.com/vllm-project/vllm/releases/tag/v0.33.0rc3)
- [DeepSeek V4 Hopper Humming optimization PR](https://github.com/vllm-project/vllm/pull/61875)
- [Previous vLLM 0.32.0 measurements](deepseek-v41-vllm032-upgrade.md)
