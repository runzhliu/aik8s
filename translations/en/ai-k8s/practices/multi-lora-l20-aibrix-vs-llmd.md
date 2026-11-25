---
title: "Multi-LoRA Sharing on NVIDIA L20: AIBrix v0.8.0 vs. CNCF llm-d EPP v1.0.0 for Affinity Routing and Noisy-Neighbor Isolation"
description: "Head-to-head L20 benchmarks with Qwen3-8B and 20 PEFT LoRA adapters covering single-GPU --max-loras slot scaling, 2xL20 Round-Robin vs. AIBrix v0.8.0 ModelAdapter vs. CNCF llm-d EPP v1.0.0 routing, 70% hotspot skew, and noisy-neighbor isolation."
date: 2026-11-24
last_reviewed: 2026-11-24
status: tested
applicable_versions: "Kubernetes v1.30.4, vLLM v0.26.0, AIBrix v0.8.0, CNCF llm-d EPP v1.0.0, Gateway API Inference Extension v1.6.2, Envoy v1.33.2"
---

# Multi-LoRA Sharing on NVIDIA L20: AIBrix v0.8.0 vs. CNCF llm-d EPP v1.0.0 for Affinity Routing and Noisy-Neighbor Isolation

Picture a Monday standup that almost every AI platform team eventually faces: your company launches one open-source `Qwen3-8B` base model, and within a month twenty teams want their own fine-tuned variant—customer support built a refund-reply assistant, engineering built a code-review assistant, legal built a contract-review assistant, and marketing built a product-copy generator.

Giving each fine-tuned model its own 48 GB L20 GPU means buying 20 cards—an impossible budget sell when legal and finance tools only see a few hundred calls a day. Consolidating all 20 adapters onto a shared GPU pool with **Multi-LoRA** cuts hardware cost dramatically, **until three real support tickets hit your desk in week one**:

- **Ticket 1 (10-second freeze)**: Starting with one L20, you conservatively set `--max-loras=4` to save VRAM. Now 16 coworkers query different assistants at once, and everyone stares at a blinking cursor for **10 seconds** before the first word appears.
- **Ticket 2 (Flash-sale skew)**: You scale to 2 L20s and steady traffic looks great—until a promotion drives **70%** of all requests into marketing's copy generator. One GPU melts down while the other sits half-idle. How do you bring tail latency back under 200 ms?
- **Ticket 3 (Noisy neighbor outage)**: At 3 PM, analytics dumps 16 concurrent 3,300-word contract-summary jobs into one LoRA, instantly pushing all 19 interactive support and coding assistants past **5 seconds**!

To answer all three tickets with hard numbers, we ran three stages totaling 11 controlled experiments on real **NVIDIA L20 (46,068 MiB)** GPUs with **`Qwen3-8B` BF16 + 20 `r=16` PEFT LoRAs (87.4 MB each)**, comparing the two leading 2026 Kubernetes multi-LoRA routing stacks—**AIBrix `v0.8.0`** and **CNCF `llm-d` EPP `v1.0.0`**—head-to-head on the exact same L20 replicas (recording per-request streaming first-token latency TTFT, per-token interval TPOT, end-to-end latency E2E, and exact `target-pod` / `x-upstream-host` routing attribution):

- **Single-L20 slot inflection point (Stage 1)**: Under 16-concurrency traffic cycling across 20 LoRAs, `--max-loras=4` starved active GPU slots and pushed **TTFT P50 to `10,913 ms` (P99 `11,782 ms`)** at just **`71.2 tok/s`**. Raising `--max-loras=20` cost only **1.44 GiB** of extra VRAM (reducing KV Cache by just `6.0%`, from `24.03 GiB` to `22.58 GiB`), yet **cut TTFT P50 by `92.9%` (down to `774 ms`)** and boosted throughput **2.75× (`195.7 tok/s`)**; mixed multi-LoRA batching (SGMV kernels) modestly increased TPOT P50 from `53.0 ms` to `62.3 ms`.
- **2×L20 uniform 20-LoRA routing (Stage 2A, `--max-loras=10` per GPU)**: Against Round-Robin (`272.9 tok/s`, TTFT P99 `5,197 ms`, `63.5%` dominant-pod locality), **`llm-d` EPP `v1.0.0`** boosted throughput to **`351.8 tok/s` (+28.9%)** with `82.5%` locality and the lowest TTFT P50 (`267 ms`) with zero pre-pinning, though first-hit cross-GPU fallbacks left a `4,177 ms` P99 tail. **AIBrix `v0.8.0` `ModelAdapter` (`replicas: 1`)** pinned 10 LoRAs per GPU for **`100.0%` locality and `357.8 tok/s`**, slashing **TTFT P99 to `1,117 ms` (down `78.5%` vs. RR)** and E2E P99 to `4.53 s`.
- **70% hotspot skew reversal and hidden pitfall (Stage 2B)**: When 70% of traffic targeted `lora-01`, both AIBrix single-replica pinning (`87/0`) and `llm-d` EPP (`lora-affinity: 4.0` + `queue-scorer: 2.0`, also `87/0`) bottlenecked on one GPU (`331.7` / `336.4 tok/s`, P99 `1,354` / `1,338 ms`), losing to Round-Robin (`380.8 tok/s`, P99 `795 ms`). Root cause: with `--max-num-seqs=32` exceeding concurrency `24`, vLLM's `waiting` queue stayed at `0`, making EPP's `queue-scorer` blind to single-GPU saturation. Removing `replicas: 1` on hot `ModelAdapter/lora-01` scaled it across both L20s in 5 seconds while keeping the 19 tail LoRAs pinned—delivering **`450.6 tok/s` and `186 ms` TTFT P99 (-86.2%)**.
- **Noisy-neighbor isolation (Stage 3)**: Without protection, the 16-concurrency 3,300-token `lora-20` flood drove the 19 normal LoRAs to **`4,606 / 4,826 ms` TTFT P95/P99** (`12.06 s` E2E P99). **`llm-d` EPP `v1.0.0` priority flow control** (`priority: +10` vs. `-10`) delivered **work-conserving protection**: 0 `429` drops on the noisy tenant (`80/80` completed during spare cycles) while cutting normal **TTFT P99 by `59.9%` to `1,933 ms`**. **AIBrix `v0.8.0` Redis rate limiting** (`6 RPM / 20k TPM` on the noisy user) hard-rejected **`8,553` `HTTP 429`** requests at the edge, driving normal **TTFT P50/P95 down to `202 / 579 ms` (P95 down `87.4%`)**, while the initial 6 admitted long requests still created a `2,514 ms` P99 spike.

> **Methodology note**: The 20 LoRA adapters (plus 21st hot-load adapter `lora-21-hot`) are deterministically generated valid PEFT Safetensors weights (`r=16`, `lora_alpha=32`, 7 projection modules, `87.4 MB` each) matching `/models/Qwen3-8B/config.json` dimensions exactly, yielding realistic VRAM footprint, multi-LoRA kernel compute, and PCIe swap behavior; this lab benchmarks systems scheduling, latency, and isolation rather than text quality. All runs used the same in-cluster client, `--enforce-eager`, `temperature=0`, `ignore_eos=true`, and unique per-request nonces so prefix caching could not mask LoRA swap latency.

---

## Plain-English Background: How LoRA, AIBrix, and `llm-d` Work

If your background is application development or Kubernetes operations rather than ML fine-tuning, and you have not used AIBrix or `llm-d` before, this three-minute walkthrough explains every moving piece before we dive into benchmarks.

### 1. What Is LoRA, and How Does One GPU Serve 20 Models?

Traditional full fine-tuning rewrites the entire `15.6 GB` base model (such as `Qwen3-8B`), so 20 fine-tuned variants require 20 separate `15.6 GB` copies and 20 GPUs.

**LoRA (Low-Rank Adaptation)** freezes the original `15.6 GB` base weights and trains only a tiny set of delta matrices attached to key layers (tens of megabytes—here `87.4 MB` at `r=16`, under **0.6%** of the base model size). Think of the base model as a shared reference encyclopedia and each team's LoRA as a thin **domain sticky-note booklet** clipped onto its pages:

- At startup, the GPU loads **only one copy of `Qwen3-8B`** into VRAM;
- When requests arrive with `"model": "lora-01"` or `"model": "lora-12"`, vLLM applies the matching booklet on the fly, letting **one GPU and one vLLM process serve 20 distinct fine-tuned models simultaneously**.

### 2. How AIBrix `v0.8.0` and CNCF `llm-d` EPP `v1.0.0` Route Multi-LoRA Traffic

Once traffic outgrows one GPU, standard Kubernetes Services (random or round-robin load balancing) break down because they have no idea which GPU already holds `lora-01` in VRAM. Two distinct architectures emerged in the Kubernetes ecosystem to solve this:

- **AIBrix `v0.8.0` (the "pre-assigned table host")**: An integrated Kubernetes inference suite led by the vLLM community that owns both adapter placement and gateway routing. You apply 20 `ModelAdapter` CRDs, and the AIBrix controller decides ahead of time: **Pod A owns `lora-01` through `lora-10`, Pod B owns `lora-11` through `lora-20`**, calls vLLM APIs to load them, and writes a routing table. When a request hits Envoy, the AIBrix plugin reads the `model` field, checks Redis per-user quotas (immediately returning `HTTP 429` if exceeded), and **forwards directly to the owning GPU**.
- **CNCF `llm-d` EPP `v1.0.0` (the "floor manager polling tables every 100 ms")**: Evolved from Kubernetes Gateway API Inference Extension and now a CNCF project. It **does not manage how models are deployed or loaded** (each pod can cache all 20 LoRAs in host RAM), focusing exclusively on real-time request scheduling. Its brain—**EPP (Endpoint Picker)**—hooks into Envoy via **`ext_proc` (External Processor)** in three steps:
  1. **Live telemetry every `100 ms`**: EPP scrapes each vLLM Pod's `/metrics` endpoint to see which LoRAs are hot in VRAM (`vllm:lora_requests_info`), how many requests are waiting (`vllm:num_requests_waiting`), and remaining KV Cache capacity;
  2. **Priority queuing (`InferenceObjective`)**: Under saturation, EPP's `flowControl` queues requests by priority band—interactive support (`priority: 10`) jumps ahead of batch summaries (`priority: -10`), yet batch traffic still runs whenever idle capacity appears instead of being dropped outright;
  3. **Multi-signal scoring (`Filter -> Score -> Pick`)**: EPP scores candidate pods (rewarding LoRA cache hits, shorter queues, and KV headroom) and returns the winning Pod IP in header `x-gateway-destination-endpoint`, which Envoy dials via `ORIGINAL_DST`.

![How AIBrix v0.8.0 and CNCF llm-d EPP v1.0.0 route multi-LoRA traffic: on the left, AIBrix uses ModelAdapter CRDs to pre-pin 10 LoRAs per L20 with Redis hard quotas; on the right, llm-d EPP scrapes live vLLM metrics every 100 ms, applies priority flow control, and scores candidate GPUs dynamically.](../../assets/practices/multi-lora-l20-aibrix-vs-llmd/aibrix-vs-llmd-architecture.png)

### 3. Quick Glossary for This Lab

| Term | Plain-English Meaning | Why It Matters Here |
| --- | --- | --- |
| **`r=16` (Rank)** | The "thickness" of the LoRA adapter; higher rank stores more adaptation capacity and takes more memory | We use the common production rank `r=16` (`87.4 MB` each) so memory and swap costs match real fine-tuned adapters |
| **`--max-loras` & `--max-cpu-loras`** | Like your **desk space** (how many LoRAs stay open in GPU VRAM at once) vs. **filing cabinet** (how many stay cached in host RAM) | When desk space (`--max-loras`) is too small, incoming requests must wait while vLLM swaps old adapters out and copies new ones over PCIe |
| **Affinity Routing** | Steering requests for the same LoRA back to the GPU **that already has that LoRA open in VRAM** | Prevents both GPUs from repeatedly loading and evicting the same adapters, cutting tail latency |
| **Punica / SGMV Kernels** | Specialized GPU kernels that apply different LoRA adapters to different requests inside the same inference batch | Mixing more LoRA types per step adds mild decode overhead (here TPOT rose by ~`9 ms`) |
| **Noisy Neighbor** | One tenant flooding the shared pool with huge concurrent long-context requests, starving other tenants on the same GPU | The #1 reliability risk in multi-tenant shared inference pools |
| **Work-Conserving** | High-priority traffic jumps to the front of the queue, while low-priority traffic still runs whenever idle GPU capacity exists instead of being dropped outright | How `llm-d` EPP priority flow control behaves, contrasted with AIBrix's strict Redis quota that immediately returns `HTTP 429` |
| **TTFT / TPOT / E2E** | **TTFT**: wait until the first token appears; **TPOT**: average time per subsequent token; **E2E**: total time until the response finishes | LoRA slot swapping mainly hurts **TTFT**, while multi-LoRA batch compute overhead shows up in **TPOT** |

---

## Lab Environment and Dual-Entry Isolated Topology

For a strictly apples-to-apples comparison, both routers targeted the **exact same two 1×L20 vLLM pods** (`vLLM 0.26.0b2.dev1+g3b102b576`, `Qwen3-8B` BF16) in the same Kubernetes `v1.30.4` cluster. Without touching the shared `envoy-gateway:v1.2.8` or `aibrix-system`, we deployed an isolated **CNCF `llm-d` EPP `v1.0.0` + Envoy `v1.33.2`** stack inside namespace `lora-bench-lab` (with a second plain Round-Robin listener without `ext_proc` as the control):

```text
                             ┌──▶ Entry A: Shared Envoy Gateway v1.2.8 + AIBrix v0.8.0 (ModelAdapter + Redis RateLimit) ──┐
In-Cluster SSE Benchmark ────┼──▶ Entry B: Isolated Envoy v1.33.2 + CNCF llm-d EPP v1.0.0 (InferencePool + FlowControl)   ├──▶ 2 x 1xL20 Qwen3-8B vLLM
                             └──▶ Entry C: Isolated Envoy v1.33.2 Round-Robin Control (no ext_proc)                       ┘    (21 PEFT LoRAs each)
```

| Component | Verified Version / Key Settings |
| --- | --- |
| GPUs & Base Model | 1× or 2× NVIDIA L20 (`46,068 MiB`); `Qwen3-8B` BF16 (36 layers, `hidden=4096`, `intermediate=12288`, `heads=32`, `kv_heads=8`, `head_dim=128`) |
| Inference Engine | vLLM `0.26.0b2.dev1+g3b102b576`, `--dtype bfloat16 --max-model-len 8192 --max-num-seqs 32 --gpu-memory-utilization 0.90 --enable-lora --max-lora-rank 16 --max-cpu-loras 24 --enable-prefix-caching --enforce-eager`, `VLLM_ALLOW_RUNTIME_LORA_UPDATING=True` |
| LoRA Adapter Set | `lora-01` through `lora-20` + `lora-21-hot`, `87.4 MB` each (`r=16`), deterministically generated into local `emptyDir` `/loras` in ~8 s by an InitContainer |
| AIBrix Stack | AIBrix `v0.8.0` (`controller-manager`, `gateway-plugins`, `Redis 7.4.2`, `ModelAdapter v1alpha1`) + Envoy Gateway `v1.2.8`; when a Pod omits the `aibrix-runtime` sidecar, the `ModelAdapter` controller automatically calls vLLM `/v1/load_lora_adapter` directly for local `/loras/<name>` paths |
| CNCF `llm-d` Stack | `ghcr.io/llm-d/llm-d-router-endpoint-picker:v1.0.0` + GAIE `v1.6.2` `InferencePool` (`inference.networking.k8s.io/v1`) + `llm-d.ai/v1` `InferenceObjective` + Envoy `v1.33.2` (`ext_proc` + `ORIGINAL_DST`) |

> **Upstream evolution note**: In 2026, full-featured EPP routing (including `lora-affinity-scorer`, KV-cache routing, and `flowControl` priority shedding) moved from Gateway API Inference Extension into CNCF **`llm-d`** as `llm-d-router-endpoint-picker:v1.0.0`, graduating `InferenceObjective` and `EndpointPickerConfig` to `llm-d.ai/v1`. On clusters whose shared Envoy Gateway is older than `v1.4` (`v1.2.8` here), running a standalone Envoy `v1.33.2` with `ext_proc` + `ORIGINAL_DST` enables the full `v1.0.0` EPP without touching shared ingress infrastructure.

---

## Practice 1: Ticket 1 Replayed—Why Did Everyone Wait 10 Seconds on a Single L20?

**Workplace scenario**: On day one you only have a single 48 GB L20. Worried about squeezing conversation KV cache, you set `--max-loras` conservatively to `4`. During the Monday morning rush, 16 coworkers query 20 department assistants at once, and Slack lights up: "Why does it freeze for 10 seconds before showing the first word?"

We replayed this exact setup on **1× L20**: all 20 LoRAs were cached in host RAM (`--max-cpu-loras=24`) and hit with 100 streaming requests at concurrency 16 (~450 input tokens / 64 output tokens, seed `101`), stepping `--max-loras` from `4` to `8` to `20`:

![Single L20 serving 20 LoRAs --max-loras sweep: raising max-loras from 4 to 20 slashes TTFT P50 from 10.9s to 774ms (-92.9%) and raises output throughput from 71.2 to 195.7 tok/s (2.75x) for just 1.44 GiB extra VRAM (-6.0% KV cache).](../../assets/practices/multi-lora-l20-aibrix-vs-llmd/single-gpu-max-loras-sweep.png)

| `--max-loras` | Model + LoRA Slot VRAM | Available KV Cache (Tokens) | 100-Req Wall Time | Output Throughput | TTFT P50 / P95 / P99 | TPOT P50 | E2E P99 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **4** | `15.64 GiB` | `24.03 GiB` (`174,944`) | `89.88 s` | `71.2 tok/s` | `10,913 / 11,070 / 11,782 ms` | `53.0 ms` | `15,142 ms` |
| **8** | `16.00 GiB` | `23.66 GiB` (`172,320`) | `50.43 s` | `126.9 tok/s` | `4,117 / 4,821 / 5,235 ms` | `56.8 ms` | `8,933 ms` |
| **20** | `17.08 GiB` | `22.58 GiB` (`164,400`) | `32.71 s` | `195.7 tok/s` | `774 / 1,620 / 1,956 ms` | `62.3 ms` | `6,354 ms` |

Two physical laws stand out immediately:

1. **Undersizing slots is brutally expensive; sizing them properly is cheap**: `--max-loras` caps how many distinct LoRAs can run concurrently in GPU memory in a single step. At `4`, 16 concurrent requests spanning 20 LoRAs force **12 requests to queue for slot eviction and PCIe H2D reload**, pushing TTFT P50 to **10.91 s**. Raising `--max-loras` from `4` to `20` adds 16 hot `r=16` slots for just **`1.44 GiB`** (~`90 MiB`/slot, trimming KV Cache by only `6.0%`), **cutting TTFT P50 by `92.9%` and multiplying throughput `2.75×`**.
2. **Mixing many LoRAs per batch adds mild compute overhead**: Per-token decode interval (TPOT P50) rose gently from `53.0 ms` → `56.8 ms` → `62.3 ms` (`+17.5%`) as more distinct adapters co-executed via vLLM's multi-LoRA batching kernels (Punica / SGMV)—a minor price for eliminating 10 seconds of queue wait.

---

## Practice 2: Ticket 2 Replayed—2×L20 Affinity Routing (Steady Traffic vs. 70% Flash-Sale Skew)

**Workplace scenario**: Traffic grows and you add a second L20, but with dozens of fine-tuned models in the catalog, each GPU can only keep half of them hot in VRAM (**`--max-loras=10`** per GPU = **20 aggregate hot slots** for 20 LoRAs). First we compare all three routers during normal even traffic, then watch what flips when a single marketing assistant suddenly absorbs 70% of all calls during a flash sale.

### 2A. Uniform 20-LoRA Concurrency: Metrics-Driven Affinity vs. Declarative Pinning

The `llm-d` EPP `v1.0.0` configuration enables `lora-affinity-scorer`, `queue-scorer`, `kv-cache-utilization-scorer`, and `flowControl`:

```yaml
apiVersion: llm-d.ai/v1
kind: EndpointPickerConfig
featureGates:
- flowControl
plugins:
- type: lora-affinity-scorer
- type: queue-scorer
- type: kv-cache-utilization-scorer
- type: max-score-picker
- type: single-profile-handler
- type: soft-reflective-ceiling-policy
schedulingProfiles:
- name: default
  plugins:
  - pluginRef: lora-affinity-scorer
    weight: 4.0
  - pluginRef: queue-scorer
    weight: 2.0
  - pluginRef: kv-cache-utilization-scorer
    weight: 1.0
  - pluginRef: max-score-picker
flowControl:
  usageLimitPolicyPluginRef: soft-reflective-ceiling-policy
  defaultRequestTTL: 15s
```

On AIBrix `v0.8.0`, 20 `ModelAdapter` CRs declare `replicas: 1` (the `least-adapters` scheduler splits them evenly into **10 on Pod A + 10 on Pod B**, reaching `Running` in 48 s):

```yaml
apiVersion: model.aibrix.ai/v1alpha1
kind: ModelAdapter
metadata:
  name: lora-01
  namespace: lora-bench-lab
  labels:
    model.aibrix.ai/name: "lora-01"
    model.aibrix.ai/port: "8000"
spec:
  baseModel: qwen3-8b-lora
  replicas: 1
  podSelector:
    matchLabels:
      app: qwen3-8b-lora
  artifactURL: /loras/lora-01
  schedulerName: default
```

Under identical **160 requests, concurrency 24, uniform 20-LoRA round-robin (seed `201`)**:

![2xL20 uniform 20-LoRA routing comparison: AIBrix v0.8.0 (r=1) achieves 100% locality and 357.8 tok/s with TTFT P99 cut 78.5% to 1,117 ms; llm-d EPP v1.0.0 lifts throughput 28.9% to 351.8 tok/s and lowest TTFT P50 (267 ms) dynamically, while cold misses leave a 4.2s P99.](../../assets/practices/multi-lora-l20-aibrix-vs-llmd/uniform-affinity-routing.png)

| Router | Completion | Wall Time | Output Throughput | TTFT P50 / P95 / P99 | TPOT P50 | E2E P99 | Per-LoRA Locality | Pod Split |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| **Round-Robin (Control)** | `159/160` (1× 503) | `37.29 s` | `272.9 tok/s` | `473 / 4,936 / 5,197 ms` | `61.0 ms` | `9,860 ms` | `63.5%` | `80 / 79` |
| **`llm-d` EPP `v1.0.0`** | `160/160` | `29.11 s` | `351.8 tok/s` (`+28.9%`) | `267 / 4,154 / 4,177 ms` | `54.4 ms` | `7,433 ms` | `82.5%` | `72 / 88` |
| **AIBrix `v0.8.0` (`r=1`)** | `160/160` | `28.62 s` | `357.8 tok/s` (`+31.1%`) | `408 / 986 / 1,117 ms` | `58.1 ms` | `4,529 ms` | **`100.0%`** | `80 / 80` |

Key takeaways:

- **Round-Robin** scattered all 20 LoRAs across both 10-slot GPUs (`63.5%` locality), triggering constant slot thrashing, **`4.94 / 5.20 s` TTFT P95/P99**, and one `HTTP 503`.
- **`llm-d` EPP `v1.0.0`** required zero pre-partitioning—scraping vLLM `/metrics` for `vllm:lora_requests_info` every `100 ms` raised locality to **`82.5%`**, lifted throughput **`28.9%`**, and achieved the **lowest TTFT P50 (`267 ms`)**. However, initial cold placement across both pods left a **`4,177 ms`** P99 tail.
- **AIBrix `v0.8.0` (`ModelAdapter replicas: 1`)** partitioned the 20 LoRAs 10/10 at the control plane, yielding **`100.0%` locality from request #1**, zero slot eviction, **`986 ms` TTFT P95 and `1,117 ms` P99 (down `78.5%` vs. RR)**, and cutting E2E P99 in half to `4.53 s`.

### 2B. 70% Hotspot Reversal: Why Both EPP and AIBrix Single-Replica Lost to Round-Robin

Uniform traffic favors hard pinning, but production traffic spikes unpredictably. Sending 70% of requests to `lora-01` (`87/120` requests) and 30% to `lora-02..20` (concurrency 24, seed `202`) flipped the leaderboard:

![70% hotspot skew comparison: both AIBrix replicas=1 (331.7 tok/s, P99 1354ms) and high-affinity llm-d EPP (336.4 tok/s, P99 1338ms) pin all 87 hotspot calls to one GPU; scaling only lora-01 to all pods in AIBrix hits 450.6 tok/s and 186 ms P99 (-86.2%).](../../assets/practices/multi-lora-l20-aibrix-vs-llmd/hotspot-skew-comparison.png)

| Router Setup | 120-Req Wall | Output Throughput | TTFT P50 / P95 / P99 | E2E P99 | `lora-01` Split (87 Reqs) |
| --- | ---: | ---: | ---: | ---: | --- |
| **AIBrix `v0.8.0` (`lora-01` `replicas: 1`)** | `23.16 s` | `331.7 tok/s` | `429 / 1,057 / 1,354 ms` | `5,136 ms` | `87 / 0` (pinned to 1 GPU) |
| **`llm-d` EPP `v1.0.0` (`lora:4.0, queue:2.0`)** | `22.83 s` | `336.4 tok/s` | `335 / 1,083 / 1,338 ms` | `5,057 ms` | `87 / 0` (stuck on 1 GPU) |
| **Round-Robin** | `20.17 s` | `380.8 tok/s` | `312 / 740 / 795 ms` | `4,974 ms` | `46 / 41` (split across 2 GPUs) |
| **AIBrix `v0.8.0` (`lora-01` all pods, 19 tail `r=1`)** | **`17.04 s`** | **`450.6 tok/s`** | **`160 / 186 / 186 ms`** | **`3,439 ms`** | **`46 / 41` (dual-GPU + zero tail swap)** |

This test exposed a subtle **EPP production pitfall**:

- Even after retuning EPP weights to `queue-scorer` `3.0` vs. `lora-affinity-scorer` `1.5`, `lora-01` STILL stuck `71/0` to a single GPU.
- **Root cause**: `llm-d` EPP's `queue-scorer` inspects vLLM's `vllm:num_requests_waiting`. Because `--max-num-seqs=32` exceeded our concurrency `24`, one L20 absorbed all 24 requests into `running` with **`waiting` = `0`**—so `queue-scorer` tied both GPUs and `lora-affinity-scorer` won 100% of the time! To spill hotspots before `waiting` builds up, configure **`running-requests-scorer`** or **`active-request-scorer`** alongside it instead of relying solely on `queue-scorer`.
- On **AIBrix `v0.8.0`**, patching it with `kubectl patch modeladapter lora-01 --type=json -p='[{"op":"remove","path":"/spec/replicas"}]'` (in AIBrix `v0.8.0`, `ModelAdapterSpec.Replicas` accepts only `1` or omitted for all matching pods) loaded `lora-01` onto the second L20 within **5 seconds** while keeping the 19 tail LoRAs pinned—delivering **`450.6 tok/s` (`35.9%` faster than single-replica, `18.3%` faster than RR) and `186 ms` TTFT P99 (-86.2%)**.

### 2C. Dynamic Hot-Load and Unload (21st LoRA)

- **Direct vLLM `/v1/load_lora_adapter`** (`87.4 MB`, `r=16` local disk): mean **`1.14–1.47 s`** across 60 loads in Stage 1.
- **AIBrix `v0.8.0` `ModelAdapter` lifecycle**: applying 20 `ModelAdapter` CRs in batch converged to `Running` in **`48.04 s`** (~`2.4 s`/adapter including scheduling, headless Service/EndpointSlice creation, and vLLM load). Running `kubectl apply` for the 21st `ModelAdapter/lora-21-hot` returned **`HTTP 200`** on the very first gateway probe (`target-pod` matched the scheduled Pod); `kubectl delete modeladapter lora-21-hot` automatically called `/v1/unload_lora_adapter` and removed it from `/v1/models` within 4 seconds (`has_lora_21: false`).

---

## Practice 3: Ticket 3 Replayed—Stopping One Batch Tenant From Starving 19 Live Assistants

**Workplace scenario**: At 3 PM, 19 interactive support and coding assistants (`lora-01..19`) are quietly serving 450-token short queries (concurrency `8`, 64 requests). Suddenly an analytics cron job fires **16 concurrent 3,300-token contract-summary prompts** (128 output tokens) at `lora-20`. We compared three defenses:

1. **Unprotected baseline (Round-Robin)**;
2. **`llm-d` EPP `v1.0.0` Priority Flow Control**: two `llm-d.ai/v1` `InferenceObjective`s—`lora-critical` (`priority: 10`) and `lora-sheddable` (`priority: -10`)—selected via `x-gateway-inference-objective` with `flowControl` + `soft-reflective-ceiling-policy`;
3. **AIBrix `v0.8.0` Redis Per-User Hard Rate Limit**: writing Redis keys `aibrix-users/lora-bench-noisy` (`rpm: 6, tpm: 20000`) and `aibrix-users/lora-bench-normal` (`rpm: 10000`) into `aibrix-redis-master`, matched via the `user` header.

```yaml
# llm-d v1.0.0 InferenceObjective priority bands (work-conserving flow control)
apiVersion: llm-d.ai/v1
kind: InferenceObjective
metadata:
  name: lora-critical
  namespace: lora-bench-lab
spec:
  priority: 10
  poolRefs:
  - group: inference.networking.k8s.io
    kind: InferencePool
    name: qwen3-8b-pool
---
apiVersion: llm-d.ai/v1
kind: InferenceObjective
metadata:
  name: lora-sheddable
  namespace: lora-bench-lab
spec:
  priority: -10
  poolRefs:
  - group: inference.networking.k8s.io
    kind: InferencePool
    name: qwen3-8b-pool
```

![Noisy-neighbor isolation comparison: unprotected Round-Robin drives the 19 normal LoRAs to 4.6s/4.8s TTFT P95/P99; llm-d EPP priority flow control cuts normal P99 59.9% to 1,933 ms with 0 HTTP 429 drops (80/80 noisy completed); AIBrix Redis rate limiting rejects 8,553 noisy requests with HTTP 429 and cuts normal P50/P95 to 202/579 ms (-87.4%).](../../assets/practices/multi-lora-l20-aibrix-vs-llmd/noisy-neighbor-isolation.png)

| Protection Mode | Normal 19 LoRA Completion | Normal TTFT P50 / P95 / P99 | Normal E2E P99 | Noisy `lora-20` Outcome |
| --- | ---: | ---: | ---: | --- |
| **Unprotected (Round-Robin)** | `64/64` | `363 / 4,606 / 4,826 ms` | `12,058 ms` | `77/77` admitted (`200`), dragging down all 19 tenants |
| **`llm-d` EPP Priority (`+10` vs. `-10`)** | `64/64` | `810 / 1,875 / 1,933 ms` (**P99 -59.9%**) | `7,113 ms` (`-41.0%`) | **`80/80` completed, 0× `429`** (work-conserving) |
| **AIBrix `v0.8.0` Redis Limit (`6 RPM / 20k TPM`)** | `64/64` | `202 / 579 / 2,514 ms` (**P95 -87.4%**) | `6,114 ms` (`-49.3%`) | **`8,553`× `HTTP 429` hard-rejected**, only first `6`× `200` admitted |

The contrast captures two fundamentally different control-plane philosophies:

- **`llm-d` EPP `v1.0.0` is work-conserving priority queuing**: EPP metrics (`llm_d_epp_flow_control_queue_bytes{priority="10"}` vs. `priority="-10"`) confirmed requests entered separate priority bands. Critical requests jumped ahead in dispatch, cutting normal **TTFT P99 from `4.83 s` to `1.93 s`** while **dropping zero noisy requests (`80/80` completed during spare GPU cycles)**—ideal for co-locating internal batch jobs with interactive online LoRAs.
- **AIBrix `v0.8.0` Redis rate limiting is strict edge admission**: Excess traffic gets millisecond `HTTP 429` rejections at Envoy `ext_proc` (`8,553` blocked), keeping normal tenants near idle latency (**P50 `202 ms`, P95 `579 ms`**). Because the fixed-window opener still admits the first `6` 3,300-token calls at once, P99 (`2,514 ms`) was slightly rougher than `llm-d` priority queuing (`1,933 ms`)—making **edge quota (AIBrix / Envoy RateLimit) + priority dispatch (`llm-d` EPP)** the ideal production combination.

---

## Selection Matrix and Production Rollout Checklist

| Dimension | AIBrix `v0.8.0` (`ModelAdapter` + Gateway) | CNCF `llm-d` EPP `v1.0.0` (`InferencePool` + `InferenceObjective`) |
| --- | --- | --- |
| **Core Philosophy** | **Control-plane placement + hard-pinned routing**: CRDs place/load/unload adapters and generate per-adapter Services/EndpointSlices | **Data-plane metrics + dynamic scoring**: scrapes vLLM `/metrics` (`vllm:lora_requests_info`) every `100 ms`; leaves adapter lifecycle external |
| **Uniform Multi-LoRA (Tight Slots)** | **Clear winner** (`100%` locality, zero slot eviction, TTFT P99 down `78.5%`) | `28.9%` speedup with zero pre-pinning, but ~`17.5%` cold/spillover misses remain |
| **Hotspot LoRA Spikes** | Single-replica pins saturate one GPU; removing `replicas: 1` on hot `ModelAdapter` delivers best overall result (`450.6 tok/s`, `186 ms` P99) | Pitfall: `queue-scorer` is blind when `--max-num-seqs` exceeds concurrency; pair with `running-requests-scorer` / `active-request-scorer` |
| **Noisy-Neighbor Defense** | Built-in Redis per-user RPM/TPM + per-model RPS hard caps (instant `429`, lowest P95) | Built-in `InferenceObjective` priority bands + `flowControl` (work-conserving, protects P99 with zero wasted idle compute) |
| **Best Fit** | Multi-tenant platforms wanting one CRD for LoRA lifecycle, hard tenant quotas, and hot/tail tiering | Platforms standardizing on Kubernetes Gateway API and unifying LoRA affinity, KV-cache, P/D disaggregation, and priority flow control in one EPP pipeline |

Three production rules backed directly by our L20 data:

1. **Size `--max-loras` generously first**: On `Qwen3-8B` (`r=16`), each hot GPU slot costs only ~`90 MiB`; set per-GPU `--max-loras` to cover active resident LoRAs and never starve `--max-loras` to 4 to save 1 GiB of KV cache and pay 10-second TTFT penalties.
2. **Tier hot vs. tail LoRAs**: Pin the 80% long-tail adapters to single replicas to stop slot thrashing across the fleet, and scale the 20% hot adapters across all replicas.
3. **Layer edge quotas with priority queues**: Enforce hard RPM/TPM/`max_tokens` limits on untrusted or external tenants at the gateway, and assign `priority: -10` to internal batch LoRAs so they fill idle GPU cycles without hurting interactive SLOs.

---

## Reproducible Lab Kit and Sanitized Measurements

All sanitized summaries across the 11 L20 experiments, Kubernetes manifests, and async streaming SSE harness are available below:

- **Sanitized Raw Results JSON**: [results.json](../../assets/practices/multi-lora-l20-aibrix-vs-llmd/results.json)
- **Reproducible Lab Kit**: [lab.zip](../../assets/practices/multi-lora-l20-aibrix-vs-llmd/lab.zip) (includes `llmd-controlplane.yaml`, `vllm-qwen3-8b-lora.yaml`, `aibrix-modeladapter-sample.yaml`, `bench_lora.py`, and `README.md`)

Further reading:

- [AIBrix ModelClaim Single-GPU Lab: Dual Small Models, 14B Swapping, and L20 VRAM Boundaries](aibrix-modelclaim-l20.md)
- [What AIBrix Routing Actually Optimizes: From Cache Hits to Tail Latency](aibrix-routing-cache-tradeoffs.md)
- [Kubernetes v1.37 DRA Advanced Trio in Practice: Cross-Driver PCIe Alignment, Consumable Capacity, and Single-GPU Fault Quarantine](kubernetes-137-dra-topology-sharing-health.md)
- [AIBrix Documentation: LoRA Dynamic Loading](https://aibrix.readthedocs.io/latest/features/lora-dynamic-loading.html)
- [CNCF llm-d Router & Endpoint Picker (v1.0.0)](https://github.com/llm-d/llm-d-router)
- [Kubernetes Gateway API Inference Extension](https://gateway-api-inference-extension.sigs.k8s.io/)
