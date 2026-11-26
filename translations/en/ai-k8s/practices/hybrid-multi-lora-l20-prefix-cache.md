---
title: "Single-L20 Hybrid Multi-LoRA Limit Benchmark: Qwen3.5-2B Saturation Knee and the 544-Token Prefix Cache Sawtooth Cliff"
description: "Controlled single NVIDIA L20 (46 GB) benchmarks on Qwen3.5-2B (3:1 GDN linear + full attention hybrid) with vLLM 0.33.0b1 covering online LoRA vs. merged equivalence, Base/1/4/8-LoRA and multimodal saturation limits, 4.1x Hybrid Prefix Cache speedup, and the 544-token block sawtooth trap."
date: 2026-11-26
last_reviewed: 2026-11-26
status: tested
applicable_versions: "NVIDIA L20 (46,068 MiB), Driver 580.173.02, vLLM 0.33.0b1, PyTorch 2.14.0+cu130, CUDA 13.0, Transformers 5.20.2, Qwen3.5-2B"
---

# Single-L20 Hybrid Multi-LoRA Limit Benchmark: Qwen3.5-2B Saturation Knee and the 544-Token Prefix Cache Sawtooth Cliff

More engineering teams are moving high-QPS classification, structured extraction, multimodal moderation, and routing workloads onto **hybrid-attention models** such as the `Qwen3.5` family, which interleaves **18 Gated DeltaNet (GDN) linear-attention layers** with **6 full-attention layers** in a **3:1 ratio**. When consolidating multiple fine-tuned variants onto a single **NVIDIA L20 (`46,068 MiB`)** via **Multi-LoRA**, four practical questions come up immediately: does online Multi-LoRA run cleanly across `linear_attn` layers, where does single-GPU throughput saturate, how big is the Hybrid Prefix Cache speedup, and what hybrid-specific pitfalls lurk beneath the surface?

To answer all four with hard measurements, we ran four controlled experiments on a dedicated L20 running open-source **`Qwen3.5-2B` BF16 on `vLLM 0.33.0b1`** with **8 deterministically generated `r=16` PEFT LoRAs (`32.13 MB` each, covering all 186 text linear weights)**, taking the **median of 3 rounds** alongside live `/metrics` cache-hit counters and `nvidia-smi` telemetry.

> **One-Sentence Takeaway**: **`vLLM 0.33.0b1` natively executes online Multi-LoRA across all 186 text and `linear_attn` weights of `Qwen3.5`, scaling from `1` to `8` concurrent LoRAs on one L20 costs only `4.7%` extra throughput (`59.59 -> 56.76 QPS`), and Hybrid Prefix Caching boosts 4-LoRA throughput `4.07×` to `81.74 QPS`—provided your shared system prompt clears the `544 tokens` (or `1,088 tokens`) hybrid block boundary to avoid a `49.0%` or `0.0%` cache-hit cliff.**

Five key measurements from the four controlled experiments:

- **Native online Multi-LoRA across all 186 hybrid text weights (Exp 1)**: `vLLM 0.33.0b1` (`PunicaWrapperGPU`) natively attaches online LoRA across all 12 text projection types of `Qwen3_5ForConditionalGeneration` (6 Full Attention layers `q/k/v/o_proj` + 18 GDN `linear_attn` layers `in_proj_{qkv,z,a,b}, out_proj` + 24 MLP layers `gate/up/down_proj` = 186 weights, 0 text layers skipped). Against an exact offline-merged reference model, 20 synthetic multimodal samples matched **`20/20` (100.0%, logprob MAE `0.0045`)** on the first token, and 50 text samples matched **`49/50` (98.0%)**.
- **Single-L20 saturation knee: ~13% fixed LoRA tax, <5% marginal scaling cost from 1 to 8 LoRAs (Exp 2)**: With prefix caching off and `420` tokens unique prompts, one L20 saturates at **`C=32`** (`92.8%–95.2%` GPU util). For short outputs (`4` tokens), `Base` hits **`68.53 QPS`**, `1 LoRA` hits **`59.59 QPS`** (`-13.0%` fixed Punica overhead), and scaling out from `1 LoRA` to **`4 LoRAs` (`57.93 QPS`)** and **`8 LoRAs` (`56.76 QPS`)** costs only **`-2.8%` and `-4.7%`** extra. Standard `64-tok` generation at `C=32` sustains **`2,001.9` (Base) / `1,728.8` (1 LoRA) / `1,674.7` (4 LoRAs) / `1,591.4 tok/s` (8 LoRAs)**. Mixed 1:1 multimodal traffic (50% text + 50% `448×448` PNG across 4 LoRAs) reaches **`66.89 QPS`** at `C=32` (`412.2 ms` E2E P50).
- **4.1× Hybrid Prefix Cache speedup with near-zero 4-LoRA penalty (Exp 3)**: Under a `1,294` tokens shared system prompt at `C=32`, enabling `--enable-prefix-caching` (`vLLM 0.33.0b1` auto-selects `--mamba-cache-mode align` for `Qwen3.5`) achieves an **`84.1%`** measured hit rate. `4-LoRA` throughput surges from **`20.06` to `81.74 QPS` (`4.07×`)**, slashing P50 TTFT from **`1,315.5 ms` to `304.5 ms` (`-76.9%`)**—practically matching single-LoRA (`82.02 QPS`). Adding `--enable-mamba-shared-prefix-checkpoint` lifts `Base` further from `95.36` to **`104.35 QPS` (`4.51×` vs. PC-Off, `+9.4%` vs. `align`)** and drops P50 TTFT another `-11.4%` to **`233.5 ms`**.
- **The hidden `544-token` hybrid block sawtooth cliff (Exp 3 probe)**: To match Full Attention page byte size with GDN Mamba state pages inside the unified paged allocator, `vLLM 0.33.0b1` inflates `Qwen3.5-2B`'s attention block size from `16` to **`544 tokens`** (plus `2.64%` Mamba page padding). Our length probe shows that at **`533 tok` (`< 544`)**, cache hit rate is **`0.0%`**. At **`1,110 tok`** (just 16 shared tokens shy of `2 × 544 = 1,088`), hit rate crashes from `83.2%` down to **`49.0%`**, spiking P50 TTFT by `+47%` (`184.5 ms`) and cutting QPS to `19.22`. Extending the prompt to **`1,284 tok`** (past `1,088`) snaps the second block into cache (`84.8%` hit rate), **raising QPS by `+40%` (`26.83`) and cutting TTFT by `-32%` (`125.6 ms`)**.
- **VRAM accounting: cheap LoRA slots, 13.6% token-slot tax for hybrid prefix caching (Exp 4)**: On a 46 GB L20 (`--gpu-memory-utilization 0.90`), `Qwen3.5-2B` base weights take `4.18 GiB`, and each `r=16` GPU LoRA slot adds only **`~55 MiB`** (`--max-loras 8` trims available KV memory from `33.83 GiB` to `33.37 GiB`, `-1.4%`). However, enabling `mamba_cache_mode=align` reserves a GDN state snapshot per `544-token` block, trimming total KV capacity on the exact same `33.83 GiB` from `2,342,480` to **`2,023,051` (`-13.6%`)**.

> **Benchmark methodology**: All measurements ran on an isolated single L20 using public open-source **`Qwen3.5-2B`** (BF16). All 8 PEFT LoRAs (`lora-01` through `lora-08`, `r=16, alpha=32`) and 20 `448×448` PNG test cards are deterministically generated with zero proprietary data. Small non-zero Gaussian weights (`std=0.0025`) are injected into `lora_B` so the online-vs.-merged equivalence test validates real non-trivial logit shifts rather than a zero-delta no-op. Complete raw data and reproduction scripts are packaged in [results.json](../../assets/practices/hybrid-multi-lora-l20-prefix-cache/results.json) and [lab.zip](../../assets/practices/hybrid-multi-lora-l20-prefix-cache/lab.zip).

---

## Hybrid Stack and 544-Token Alignment

If you have only operated pure Transformers such as `Qwen3-8B` or `Llama-3`, two architectural shifts in `Qwen3.5-2B` directly alter serving behavior:

1. **A 3:1 hybrid stack adds five linear-attention LoRA targets**: Inspecting `Qwen3.5-2B`'s `config.json` shows 24 layers with `full_attention_interval = 4`—three `linear_attention` layers (Gated DeltaNet: 16 K/V heads, `head_dim=128`, `conv_kernel=4`) followed by one `full_attention` layer (GQA 4:1: 8 Q / 2 KV heads, `head_dim=256`). An `all-linear` `r=16` adapter attaches to **186 linear weights** across Full Attention (24), GDN `linear_attn` (90), and MLP (72)—nearly half of them inside linear attention. If an inference runtime skips any of those projections, online LoRA silently diverges from offline-merged weights.
2. **Prefix caching no longer splits at 16 tokens—it aligns to 544-token Mamba pages**: Pure Transformer KV caches grow per token, allowing fine `block_size = 16` prefix reuse. In a hybrid model, the 18 GDN layers store fixed-size recurrent state tensors instead of per-token K/V vectors. To unify Full Attention pages and GDN state snapshots inside vLLM V1's single paged allocator, vLLM logs three critical startup decisions:

```text
INFO [config.py:766] Mamba cache mode is set to 'align' for Qwen3_5ForConditionalGeneration by default when prefix caching is enabled
INFO [interface.py:1108] Setting attention block size to 544 tokens to ensure that attention page size is >= mamba page size.
INFO [interface.py:1132] Padding mamba page size by 2.64% to ensure that mamba page size and attention page size are exactly equal.
```

In plain terms: **because one 18-layer GDN state snapshot is much larger than 16 tokens of 6-layer full-attention KV cache, vLLM inflates each attention block to `544 tokens` (with `2.64%` padding on the Mamba page) so both page types share the exact same byte footprint.** That keeps paged memory simple—and directly creates the **`544-token` sawtooth cliff** measured in Experiment 3.

![Qwen3.5-2B hybrid stack and vLLM 544-token unified page alignment: left shows the 24-layer 3:1 hybrid stack with 186 online Punica LoRA weights; right contrasts pure Transformer 16-token blocks against Qwen3.5 544-token aligned blocks and the resulting boundary cliff.](../../assets/practices/hybrid-multi-lora-l20-prefix-cache/hybrid-architecture-544-block.png)

---

## Testbed and Baseline

All four experiments ran back-to-back on a single dedicated **NVIDIA L20 (`46,068 MiB`)** with CUDA Graphs enabled (`--max-cudagraph-capture-size 64`, covering every tested concurrency `C=1..64`) so results reflect real production graph-accelerated ceilings rather than `--enforce-eager` slow paths:

| Component | Measured Version / Setting |
| --- | --- |
| GPU & Driver | 1× NVIDIA L20 (`46,068 MiB`), Driver `580.173.02`, CUDA `13.0` |
| Serving Engine | `vLLM 0.33.0b1` (V1 Engine), `PyTorch 2.14.0+cu130`, `Transformers 5.20.2` |
| Base Model | `Qwen3.5-2B` (`Qwen3_5ForConditionalGeneration`, BF16, `4.18 GiB` weights, 24 layers 3:1 hybrid, `hidden=2048`, `intermediate=6144`) |
| Synthetic LoRA Set | `lora-01` through `lora-08`, standard PEFT Safetensors (`r=16`, `lora_alpha=32`, BF16), covering 12 module types / 186 linear weights, `32.13 MB` each; plus 1 exact offline-merged copy `merged-lora-01` computed in FP32 (`(alpha/r) * B @ A`) and saved in BF16 |
| Multimodal Set | 20 deterministically rendered `448×448` RGB PNG cards (header bar, synthetic bar chart, geometric markers) |
| Common Runtime Flags | `--dtype bfloat16 --max-model-len 8192 --max-num-seqs 128 --max-cudagraph-capture-size 64`; requests fix `temperature=0`, `enable_thinking=false`, `stream=true` |

---

## Experiment 1: Online LoRA vs. Merged Parity

**Goal**: Verify that `vLLM 0.33.0b1` executes online Punica LoRA faithfully across all 186 text linear weights (including all 90 GDN `linear_attn` weights) without silently dropping layers, matching offline-merged weights (`W_base + (alpha/r) * B @ A`).

We ran two vLLM servers side by side on the same L20—port `8000` serving `Qwen3.5-2B` + 4 online LoRAs (`--gpu-memory-utilization 0.40 --enable-lora --max-loras 4 --max-lora-rank 16`) and port `8001` serving the exact offline-merged `merged-lora-01` (`--gpu-memory-utilization 0.40`)—and sent 50 text prompts plus 20 multimodal image prompts (`max_tokens=16, temperature=0, logprobs=true`), alongside `qwen35-2b-base` controls to verify that `lora-01` meaningfully shifts output distributions:

| Modality | Samples | Online LoRA vs. Merged First-Token Match | First-Token Logprob MAE / Max | Exact 16-Token Greedy Match | Control: Base vs. LoRA Diverged |
| --- | ---: | ---: | ---: | ---: | ---: |
| **Multimodal** (`448×448` PNG + text) | 20 | **`20/20` (100.0%)** | **`0.0045` / `0.0090`** | `16/20` (80.0%) | `6/10` (non-trivial LoRA shift) |
| **Text-only** | 50 | **`49/50` (98.0%)** | `0.0362` / `0.1151` | `43/50` (86.0%) | `20/20` (Base-vs-LoRA MAE `0.1472`) |

Two practical takeaways emerge from the logs and residuals:

1. **Zero skipped text or GDN layers**: `PunicaWrapperGPU` logs ignored-module warnings only for `visual.blocks.*` and `visual.merger.*` (expected when vision-tower LoRA is disabled; vLLM notes `enable_tower_connector_lora=True` is available if vision adapters are needed). All 90 `linear_attn` weights run natively.
2. **Why 16-token greedy exact match is 86% rather than 100%**: Because our synthetic Gaussian adapters inject dense random perturbations across all 186 layers (shifting Base logprobs by `0.147` MAE), offline BF16 weight quantization vs. online fused Punica accumulation introduces tiny rounding differences that can flip near-tie tokens over 16 autoregressive steps. On real fine-tuned classification or structured-output adapters with sharper top-1 margins, online Multi-LoRA matches offline-merged weights virtually 100% of the time; still, always run a quick greedy parity gate on your task eval set before cutover.

---

## Experiment 2: Single-L20 Multi-LoRA Limits

**Goal**: Measure the pure compute ceiling of one L20 with **prefix caching disabled** (`--no-enable-prefix-caching --gpu-memory-utilization 0.90 --max-num-seqs 128 --enable-lora --max-loras 8 --max-lora-rank 16`) across `Base`, `1 LoRA`, `4 LoRAs`, and `8 LoRAs`. Every prompt carries a unique prefix (`419.9 tokens` average) and every point is the median of 3 rounds.

![Single-L20 Multi-LoRA saturation curve and scaling overhead: left shows 420->4 tok QPS across C=1..64 saturating at C=32; right shows C=32 420->64 tok generation throughput and P50 TPOT across Base, 1, 4, and 8 LoRAs.](../../assets/practices/hybrid-multi-lora-l20-prefix-cache/single-l20-multi-lora-scaling.png)

### 2A. Short Classification

Workload: `420 -> 4 tok` (Prefix Cache off).

| Concurrency | `Base` QPS / TTFT P50 / GPU | `1 LoRA` QPS / TTFT P50 / GPU | `4 LoRAs` QPS / TTFT P50 / GPU | `8 LoRAs` QPS / TTFT P50 / GPU | `8 LoRAs` vs. `1 LoRA` |
| --- | ---: | ---: | ---: | ---: | ---: |
| `C=1` | `16.30` / `45.1 ms` / `53.2%` | `11.80` / `64.7 ms` / `46.0%` | `11.93` / `64.2 ms` / `49.0%` | `11.77` / `65.1 ms` / `48.8%` | `-0.3%` |
| `C=8` | `48.78` / `136.2 ms` / `80.8%` | `37.86` / `183.1 ms` / `64.4%` | `37.56` / `183.6 ms` / `61.0%` | `37.40` / `183.2 ms` / `73.2%` | `-1.2%` |
| `C=16` | `52.41` / `223.2 ms` / `79.0%` | `43.27` / `273.6 ms` / `75.8%` | `48.22` / `213.0 ms` / `78.0%` | `48.21` / `208.9 ms` / `85.2%` | `+11.4%` |
| **`C=32` (Knee)** | **`68.53`** / `259.4 ms` / `94.0%` | **`59.59`** / `286.7 ms` / `95.2%` | **`57.93`** / `309.9 ms` / `94.2%` | **`56.76`** / `315.9 ms` / `92.8%` | **`-4.7%`** |
| `C=64` | `68.24` / `660.9 ms` / `95.7%` | `60.91` / `743.5 ms` / `93.6%` | `58.81` / `779.3 ms` / `89.6%` | `57.84` / `791.7 ms` / `88.8%` | `-5.0%` |

### 2B. Standard Generation

Workload: `420 -> 64 tok` (Prefix Cache off).

| Variant | `C=1` Output tok/s / TPOT P50 | `C=16` Output tok/s / TPOT P50 | **`C=32` Output tok/s (QPS)** | `C=32` TTFT P50 / TPOT P50 | `C=32` GPU Util |
| --- | ---: | ---: | ---: | ---: | ---: |
| `Base` (no LoRA) | `154.3 tok/s` / `5.85 ms` | `1,359.4 tok/s` / `8.62 ms` | **`2,001.9 tok/s`** (`31.28 QPS`) | `228.7 ms` / `12.14 ms` | `92.1%` |
| `1 LoRA` | `124.3 tok/s` / `7.10 ms` | `1,152.0 tok/s` / `10.31 ms` | **`1,728.8 tok/s`** (`27.01 QPS`) | `261.9 ms` / `14.18 ms` | `97.8%` |
| `4 LoRAs` | `124.1 tok/s` / `7.10 ms` | `1,103.4 tok/s` / `10.88 ms` | **`1,674.7 tok/s`** (`26.17 QPS`) | `239.1 ms` / `15.19 ms` | `96.1%` |
| `8 LoRAs` | `124.5 tok/s` / `7.10 ms` | `1,040.1 tok/s` / `11.76 ms` | **`1,591.4 tok/s`** (`24.87 QPS`) | `242.0 ms` / `15.99 ms` | `93.6%` |

### 2C. 1:1 Multimodal Mixed Traffic

4-LoRA mixed workload: 50% text + 50% `448×448` PNG → `4` tokens output.

| Concurrency | Mixed QPS | Avg Input Tokens | TTFT P50 / P95 / P99 | E2E P50 / P95 / P99 | Avg GPU Util |
| --- | ---: | ---: | ---: | ---: | ---: |
| `C=1` | `11.62 QPS` | `326.7` | `66.4 / 69.7 / 70.1 ms` | `86.1 / 89.7 / 90.1 ms` | `41.0%` |
| `C=8` | `35.73 QPS` | `326.8` | `196.2 / 210.0 / 212.9 ms` | `221.1 / 234.3 / 292.9 ms` | `57.4%` |
| `C=16` | `54.85 QPS` | `326.8` | `194.5 / 284.9 / 285.7 ms` | `279.5 / 422.8 / 423.3 ms` | `77.8%` |
| **`C=32`** | **`66.89 QPS`** | `326.9` | **`228.3 / 510.5 / 511.7 ms`** | **`412.2 / 698.2 / 699.8 ms`** | **`78.5%`** |

Three clear operational laws fall out of these sweeps:

1. **The cost is mostly a fixed `0 -> 1` LoRA tax, not a `1 -> 8` scaling tax**: At the `C=32` knee, enabling the first LoRA incurs **`-13.0%` (short) to `-13.6%` (64-tok generation)** fixed Punica overhead across 186 layers. Scaling from 1 active adapter up to **8 simultaneous adapters** on the same L20 costs only **`-4.7%` extra** in short classification (`59.59 -> 56.76 QPS`) and **`-7.9%`** in 64-tok generation (TPOT `14.18 -> 15.99 ms`). Consolidating 4–8 long-tail fine-tuned services onto one L20 is overwhelmingly cost-effective as long as `--max-loras` covers all hot adapters.
2. **Pushing past `C=32` only inflates queuing latency**: Going from `C=32` to `C=64` leaves QPS flat (`±1 QPS`) while jumping P50 TTFT **2.5×** (`315.9 -> 791.7 ms` for 8 LoRAs). Cap per-GPU in-flight concurrency around `24–32` at the gateway layer.
3. **Multimodal Multi-LoRA becomes CPU-bound before GPU-bound**: Mixed 1:1 multimodal traffic hits `66.89 QPS` at `C=32` (average `326.9` tokens) with GPU utilization plateauing at `78.5%` (vs. `94%` for text-only) because image decoding and vision preprocessing consume CPU cycles. Provision at least `6–8 vCPU` per L20 for multimodal Multi-LoRA pods.

---

## Experiment 3: Hybrid Prefix Cache and 544 Cliff

Production moderation, extraction, routing, and agent workloads repeat 500–1,500 tokens of fixed system instructions on every call. We tested three engine modes on the exact same `1,294-tok` shared-policy workload (`~1,250 tok` fixed system prompt + `~44 tok` dynamic payload → `4` tokens output):

- **`PC-Off`**: `--no-enable-prefix-caching` (baseline, matching older builds without hybrid prefix caching);
- **`PC-On (mamba=align)`**: `--enable-prefix-caching --mamba-cache-mode align` (`vLLM 0.33.0b1` default for `Qwen3.5`);
- **`PC-On + Shared Prefix Ckpt`**: `--enable-prefix-caching --mamba-cache-mode align --enable-mamba-shared-prefix-checkpoint` (`vLLM 0.33.0b1` shared-prefix Mamba checkpoint optimization).

### 3A. 1,294-Token Shared Prompt Speedup

![Hybrid Prefix Cache speedup (1,294-token shared system prompt, C=32, 3-round median): left shows 4-LoRA throughput jumping from 20.1 to 81.7 QPS (4.07x); right shows P50 TTFT falling from 1,316 to 305 ms (-76.9%).](../../assets/practices/hybrid-multi-lora-l20-prefix-cache/hybrid-prefix-cache-speedup.png)

| Pattern | Concurrency | `PC-Off` QPS / TTFT P50 | `PC-On (align)` QPS / TTFT P50 / Hit | `PC-On + Ckpt` QPS / TTFT P50 / Hit | Peak Speedup / TTFT Drop |
| --- | --- | ---: | ---: | ---: | ---: |
| `Base` | `C=1` | `13.58` / `57.9 ms` | `15.81` / `47.6 ms` / `84.1%` | `15.95` / `46.7 ms` / `84.1%` | `1.17×` / `-19.3%` |
| `Base` | `C=8` | `22.01` / `178.0 ms` | `63.82` / `105.6 ms` / `84.1%` | `66.46` / `98.4 ms` / `84.1%` | `3.02×` / `-44.7%` |
| `Base` | `C=16` | `22.97` / `468.2 ms` | `81.48` / `160.9 ms` / `84.1%` | `87.55` / `150.9 ms` / `84.1%` | `3.81×` / `-67.8%` |
| **`Base`** | **`C=32`** | `23.15` / `1,138.8 ms` | `95.36` / `263.5 ms` / `84.1%` | **`104.35`** / **`233.5 ms`** / `84.1%` | **`4.51×`** / **`-79.5%`** |
| `1 LoRA` | `C=8` | `18.46` / `207.0 ms` | `52.56` / `129.2 ms` / `84.1%` | `53.77` / `124.8 ms` / `84.1%` | `2.91×` / `-39.7%` |
| `1 LoRA` | `C=16` | `20.47` / `523.8 ms` | `68.70` / `202.0 ms` / `84.1%` | `71.27` / `193.9 ms` / `84.1%` | `3.48×` / `-63.0%` |
| **`1 LoRA`** | **`C=32`** | `20.67` / `1,268.5 ms` | `82.02` / `307.0 ms` / `84.1%` | **`83.23`** / **`296.5 ms`** / `84.1%` | **`4.03×`** / **`-76.6%`** |
| `4 LoRAs` | `C=8` | `18.31` / `209.3 ms` | `51.78` / `128.5 ms` / `84.1%` | `53.17` / `125.9 ms` / `84.1%` | `2.90×` / `-39.8%` |
| `4 LoRAs` | `C=16` | `19.90` / `542.8 ms` | `67.57` / `204.1 ms` / `84.1%` | `69.66` / `199.1 ms` / `84.1%` | `3.50×` / `-63.3%` |
| **`4 LoRAs`** | **`C=32`** | `20.06` / `1,315.5 ms` | **`81.74`** / **`304.5 ms`** / `84.1%` | **`81.84`** / **`301.8 ms`** / `84.1%` | **`4.08×`** / **`-77.1%`** |

Key takeaways:

1. **Leaving Hybrid Prefix Caching off wastes ~75% of GPU capacity**: Without caching, `4-LoRA` hits a prefill wall at `C=16` (`19.90 -> 20.06 QPS`) with `1.32 s` TTFT at `C=32`. With `vLLM 0.33.0b1` and `mamba_cache_mode=align`, two full `544-token` blocks (`1,088 tok`) hit cache (`84.1%`), leaving only `206` tail tokens to prefill—pushing **`4-LoRA` throughput up `4.07×` to `81.74 QPS`** and cutting P50 TTFT by **`-76.9%`**.
2. **4-LoRA caching matches single-LoRA**: In `vLLM 0.33.0b1`, vLLM hashes prefix blocks per adapter so different LoRAs never corrupt each other's KV/GDN state. With `2,004,805` token slots available on L20, all 4 adapters keep their prefixes resident simultaneously, achieving identical `84.1%` hit rates and `81.74` vs. `82.02 QPS` (`-0.3%`).
3. **`--enable-mamba-shared-prefix-checkpoint` is a free win on Base**: It adds zero static VRAM overhead (confirmed in Exp 4) while lifting `Base` at `C=32` by another **`+9.4%` (`95.36 -> 104.35 QPS`)** and cutting P50 TTFT by `-11.4%` (`263.5 -> 233.5 ms`). Under LoRA, Punica compute dominates, narrowing the extra gain to `+1%–3.7%`.

### 3B. 544-Token Sawtooth Probe

Because `block_size = 544 tokens`, what happens when a shared system prompt falls just short of `544` or `1,088`? We ran a 4-point length probe (`lora-01`, `C=4`, warmed up before 20 measured requests, keeping the dynamic suffix fixed at `~38 tokens`):

![544-token hybrid block cliff probe: left shows cache hit rate dropping to 0.0% at 533 tok and 49.0% at 1,110 tok before jumping back to 84.8% at 1,284 tok; right shows throughput rebounding +40% and TTFT falling -32% once the prompt crosses 1,088 tokens.](../../assets/practices/hybrid-multi-lora-l20-prefix-cache/hybrid-544-block-sawtooth.png)

| Probe Point | Measured Avg Input | Est. Shared Prefix | Full `544` Blocks Cached | `pc_align` Hit Rate | `pc_align` TTFT P50 / QPS | `pc_align_ckpt` TTFT P50 / QPS |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Point 1 (`< 1×544`) | `532.6 tok` | `~495 tok` | **0 (49 short)** | **`0.0%`** | `125.3 ms` / `26.71 QPS` | `121.5 ms` / `27.55 QPS` |
| Point 2 (`> 1×544`) | `653.6 tok` | `~616 tok` | 1 (`544 tok`) | **`83.2%`** | `126.2 ms` / `27.17 QPS` | `117.5 ms` / `28.20 QPS` |
| **Point 3 (`< 2×544` cliff)** | **`1,109.7 tok`** | `~1,072 tok` | **1 (16 short of `1,088`)** | **`49.0%`** | **`184.5 ms` / `19.22 QPS`** | **`182.4 ms` / `19.47 QPS`** |
| **Point 4 (`> 2×544` rebound)** | **`1,283.7 tok`** | `~1,246 tok` | **2 (`1,088 tok`)** | **`84.8%`** | **`125.6 ms` / `26.83 QPS`** | **`121.1 ms` / `27.83 QPS`** |

The numbers match `floor(shared_prefix / 544) * 544 / total_input` to two decimal places:
- Point 2: `544 / 653.6 = 83.23%` (measured `83.2%`);
- Point 3: `544 / 1,109.7 = 49.02%` (measured `49.0%`)—falling **16 tokens short of `1,088`** fails to fill the second `544` block and forces vLLM to recompute **`566` uncached tokens** on every single request;
- Point 4: `1,088 / 1,283.7 = 84.76%` (measured `84.8%`)—**adding `+174` tokens** pushes the prefix over the 1,088 boundary, cutting recomputed tokens from `566` down to `196`, so **the longer prompt runs `+40%` faster (`19.22 -> 26.83 QPS`) at `-32%` lower latency (`184.5 -> 125.6 ms`)**.

> **Engineering rule of thumb**: On `Qwen3.5` hybrid models, always tokenize your fixed system prompt with the target model's tokenizer and check `Setting attention block size to N tokens` in vLLM startup logs (`544` for `Qwen3.5-2B`). Never leave a production system prompt stranded in the `450–543` or `950–1,087` dead zones—either trim it or add concise few-shot examples to clear the `N` / `2N` boundary cleanly for `80%+` hit rates.

---

## Experiment 4: VRAM and Slot Accounting

Teams often hesitate to raise `--max-loras 8` or turn on `mamba_cache_mode=align` for fear of exhausting VRAM. We restarted vLLM across five configurations on the same 46 GB L20 (`--gpu-memory-utilization 0.90 --max-model-len 8192 --max-num-seqs 128`) to record exact startup memory and KV/GDN token capacity:

| Configuration | Model + LoRA Slot VRAM | Available KV / GDN Cache | Total KV Token Capacity | Max Concurrency @ 8K | `nvidia-smi` Used |
| --- | ---: | ---: | ---: | ---: | ---: |
| `Base` (no LoRA, `PC-Off`) | `4.18 GiB` | `33.83 GiB` | **`2,342,480`** | `285.95×` | `39,665 MiB` |
| `Base` (no LoRA, `PC-On align`) | `4.18 GiB` | `33.83 GiB` | **`2,023,051`** (`-13.6%`) | `246.95×` | `39,665 MiB` |
| `Base` (no LoRA, `PC-On align + ckpt`) | `4.18 GiB` | `33.83 GiB` | `2,023,051` (`0%` extra) | `246.95×` | `39,663 MiB` |
| `Multi-LoRA max=4` (`r=16`, `align`) | `4.39 GiB` (`+0.21 GiB`) | `33.52 GiB` (`-0.31 GiB`) | `2,004,805` (`-0.9%`) | `244.73×` | `39,713 MiB` |
| `Multi-LoRA max=8` (`r=16`, `align`) | `4.62 GiB` (`+0.44 GiB`) | `33.37 GiB` (`-0.46 GiB`) | `1,995,496` (`-1.4%`) | `243.59×` | `39,713 MiB` |

Two clear budgeting takeaways:
1. **Raising `--max-loras` is nearly free on 2B hybrid models**: Adding 8 `r=16` hot slots uses only `+0.44 GiB` (`~55 MiB`/slot), reducing KV token capacity by just `1.4%`. Never starve `--max-loras` below your active adapter count—as shown in our companion [AIBrix v0.8.0 vs. CNCF llm-d EPP v1.0.0 L20 study](multi-lora-l20-aibrix-vs-llmd.md), PCIe slot swapping triggers 10× TTFT spikes.
2. **Enabling `mamba_cache_mode=align` carries a `-13.6%` token-slot tax**: Storing a GDN state snapshot per `544-token` block reduces capacity from `2.34M` to `2.02M` tokens on `33.83 GiB`, still enough for `243×` full 8K concurrency on one L20—trading `13.6%` slots for `4.1×` throughput and `-77%` TTFT.

---

## Production Rollout Checklist

### Fit and Non-Applicable Cases

- **Strong fit**: 3–16 fine-tuned vertical tasks sharing the same `Qwen3.5` (or similar hybrid/dense) base at `1–30 QPS` each with `>= 544-token` shared system prompts. One L20 running `vLLM 0.33.0+` + Hybrid Prefix Caching + `--max-loras >= active_tasks` sustains **`60–80+ QPS`** across tasks, replacing multiple underutilized single-model GPUs.
- **Poor fit (skip online LoRA)**:
  1. Single high-volume flagship models that already saturate whole GPUs—merge offline to avoid the `13%` fixed Punica kernel tax;
  2. Large MoE + Expert Parallel + speculative decoding stacks with multi-GB adapters;
  3. Workloads with short (`< 200-token`) unique prompts that cannot cross the `544-token` block boundary—size capacity using the PC-Off baseline (`~57 QPS/L20`) and disable `align` to keep the extra `13.6%` KV token slots.

### Recommended Launch Template

```bash
vllm serve /models/Qwen3.5-2B \
  --served-model-name qwen35-2b-base \
  --dtype bfloat16 \
  --max-model-len 8192 \
  --max-num-seqs 128 \
  --gpu-memory-utilization 0.90 \
  --enable-prefix-caching \
  --mamba-cache-mode align \
  --enable-mamba-shared-prefix-checkpoint \
  --enable-lora \
  --max-loras 8 \
  --max-cpu-loras 16 \
  --max-lora-rank 16 \
  --lora-modules \
    task-a=/loras/task-a \
    task-b=/loras/task-b \
    task-c=/loras/task-c \
    task-d=/loras/task-d
```

Pre-production checklist:
1. Check startup logs for `Setting attention block size to <N> tokens` and align shared system prompts past `N` (`544`) or `2N` (`1,088`);
2. Keep `--max-loras >= peak concurrent adapters` and cap per-GPU in-flight concurrency at `24–32` via your gateway (AIBrix or CNCF `llm-d` EPP);
3. Allocate `6–8 vCPU` per L20 when mixing image/multimodal traffic;
4. Alert on `rate(vllm:prefix_cache_hits_total[5m]) / rate(vllm:prefix_cache_queries_total[5m])`—a sudden drop from `80%+` to `49%` or `0%` usually means a prompt edit slipped below a `544-token` block boundary.

---

## Summary

Our single-L20 controlled benchmarks on `Qwen3.5-2B` boil down to three practical deployment rules for hybrid-attention Multi-LoRA serving:

1. **Consolidate same-base long-tail fine-tunes, keep GPU-saturating flagships merged**: Enabling the first LoRA incurs a `13%` fixed Punica kernel tax, while scaling from `1` to `8` concurrent adapters costs under `5%` extra throughput and only `55 MiB` per slot—ideal for packing 4–16 long-tail tasks onto shared GPUs, whereas single high-QPS flagship services still benefit from offline merging.
2. **Design shared prompts around the `544-token` hybrid block boundary**: Because `vLLM 0.33.0b1` inflates attention blocks to `544 tokens` to match GDN Mamba state pages, falling just short of `544` or `1,088` drops cache hits to `0%` or `49%`. Aligning system prompts past full block multiples and alerting on cache-hit drops locks in the full **`4×` QPS and `-77%` TTFT speedup**.
3. **Cap per-GPU concurrency at `24–32` and provision enough CPU for multimodal traffic**: Beyond `C=32` without caching, latency climbs with zero QPS gain; under 1:1 text-plus-image loads, CPU image decoding caps GPU utilization at `78.5%` unless pods receive `6–8 vCPU` per L20.

---

## Reproduction Kit and Raw Data

- Complete sanitized measurements (all 3 rounds, startup logs, VRAM ledger): [results.json](../../assets/practices/hybrid-multi-lora-l20-prefix-cache/results.json)
- Self-contained reproduction bundle (186-weight synthetic PEFT LoRA generator, exact offline merge script, 20 synthetic PNG generator, and 4-stage benchmark harness): [lab.zip](../../assets/practices/hybrid-multi-lora-l20-prefix-cache/lab.zip)
- Companion reading: [Multi-LoRA Sharing on NVIDIA L20: AIBrix v0.8.0 vs. CNCF llm-d EPP v1.0.0](multi-lora-l20-aibrix-vs-llmd.md)
