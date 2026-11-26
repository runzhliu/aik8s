---
title: "Why Low-Utilization GPU Inference Services Refuse to Scale Down: A Four-Dimensional Hardware Audit of 25 Production Services"
description: "A fully anonymized production audit of 25 low-utilization GPU inference services (313 GPUs across dual-AZ clusters; domains, teams, and GPU SKUs anonymized): exposing fake 100% GPU_UTIL from PCIe TP=2 spin-wait without NVLink, separating true bursts from 0%-Tensor bottlenecks, and showing how GPU platform teams empower application teams with deep telemetry rather than challenging business value."
date: 2026-11-26
last_reviewed: 2026-11-26
status: tested
applicable_versions: "Kubernetes v1.28+, NVIDIA DCGM Exporter (PROF metrics), vLLM v0.12–v0.33, SGLang v0.5+, 72G / 48G / 24G PCIe Inference GPUs"
---

# Why Low-Utilization GPU Inference Services Refuse to Scale Down: A Four-Dimensional Hardware Audit of 25 Production Services

Almost every AI infrastructure team operating hundreds of inference GPUs faces the same recurring standoff: a dashboard flags serving deployments whose 7-day average `DCGM_FI_DEV_GPU_UTIL` sits below `15%`, yet application owners share three very real concerns—`GPU_UTIL Max` hits `100%` daily, removing a single GPU previously triggered timeouts, or periodic bursts saturate the pool. These conversations stall not because owners want to hoard GPUs, but because a single `GPU_UTIL` curve leaves both sides operating in the dark.

To replace guesswork with hard evidence, we ran a full hardware- and engine-level audit across **25 real low-utilization production GPU inference services** originally holding **`313` GPUs** (`56` freed collaboratively in round 1, **`257` GPUs** currently active across dual-AZ clusters spanning `72G PCIe` flagship inference GPUs, `48G PCIe` mid-tier/datacenter GPUs, and `24G` entry GPUs; all domains, clusters, teams, business lines, and exact GPU SKUs have been fully anonymized).

> **One-Sentence Takeaway**: **Low-utilization GPU inference services resist scale-down not because application teams refuse to cooperate, but because a single `GPU_UTIL` curve hides four completely different root causes—fake `100%` spikes (PCIe `TP=2` spin-wait without NVLink), true bursts, `Tensor = 0%` non-GPU bottlenecks, and the long-tail HA floor**; rather than challenging business value, GPU platform teams should collect comprehensive hardware and engine telemetry and partner with owners on concrete fixes (`TP=1`, Hybrid Prefix Caching, dynamic batching/CPU, and shared Multi-LoRA pools) to safely unlock **`94–126` more GPUs out of `257` active GPUs** without risking SLA.

Four key quantitative findings from the audit:

- **`GPU_UTIL Max = 100%` frequently hides "fake saturation"**: `DCGM_FI_DEV_GPU_UTIL` only reports whether *any* CUDA kernel ran during the sample interval—including NCCL AllReduce spin-wait loops when running `TP=2` across **PCIe GPUs without NVLink**. One 24-GPU dual-AZ service (`SVC-03`, on non-NVLink `72G PCIe` GPUs) reported `GPU_UTIL >= 95%` in `39.3%` of all minutes over 24 hours (peaking at `100%`), yet during the exact same minute its real `PROF_SM_ACTIVE` was only **`7.3%–14.7%`**, `PIPE_TENSOR_ACTIVE` peaked at **`5.9%`**, and 7-day `vllm:num_requests_waiting` stayed strictly **`0`**.
- **Deep telemetry splits all 25 services into four clean physical root causes**: **Category 1 (Fake 100% / Safe Rightsize)** holds **`140` of `257` active GPUs (`54.5%`)** across 5 services and can safely free **`66–88` GPUs** via rightsizing or switching to `TP=1` while preserving 2× failover headroom; **Category 2 (Real Queue / True Burst)** (7 services / `65` GPUs) must protect SLA and *never* be hard-cut, yet platform-assisted Hybrid Prefix Caching and shared-pool multiplexing safely save **`18–24` GPUs**; **Category 3 (`Tensor = 0%` Non-GPU Bound)** (6 services / `26` GPUs) validates why scale-downs caused timeouts—fixing concurrency via dynamic batching, multi-instance colocation, or CPU inference removes the timeout risk and frees **`10–14` GPUs**; **Category 4 (At Min HA Baseline)** (7 services / `26` GPUs, `27` GPUs already freed in round 1) breaks past its physical floor via shared Multi-LoRA pools.
- **80% of high-value optimization potential sits in just 4 flagship-tier services**: Four `72G PCIe` deployments hold `136` GPUs today; helping those four teams optimize frees **`68–84` 72G GPUs**.
- **Platform governance succeeds through telemetry and enablement, not confrontation**: Upgrading inspection from a single `GPU_UTIL` curve to a four-dimensional `PROF_SM_ACTIVE + PIPE_TENSOR_ACTIVE + Waiting/KV% + 7d QPS` data plane shifts the conversation from questioning business value to jointly improving efficiency and reliability.

> **Companion context**: Our earlier guide [Why GPU Utilization Is Low](low-gpu-utilization.md) covers the general wait chain across training and inference; this case study focuses on **data-driven platform enablement and production capacity governance** across 25 live services.

---

## 1. Case Study: Fake 100% Saturation

The clearest illustration of how a single `GPU_UTIL` metric misleads both sides is **dual-AZ relevance scorer `SVC-03`** (originally `14 + 14 = 28` `72G PCIe` GPUs, trimmed slightly to `12 + 12 = 24` GPUs). These `72G PCIe` inference cards offer large VRAM, **but have no NVLink interconnect**, meaning multi-GPU tensor parallelism (`TP`) communicates solely over PCIe.

Seeing daily max `100%` spikes on the dashboard, the application team rightly hesitated to shrink further. Once the platform team assembled **six underlying hardware and vLLM engine metrics** across both availability zones (`AZ-1` and `AZ-2`, six `TP=2` pods each), both sides immediately saw the true picture:

![Anatomy of a Fake 100%: left compares 6 measured dimensions for SVC-03—surface GPU_UTIL peaks at 100%, while true SM_ACTIVE peaks at 19.5%, Tensor Core at 5.9%, power averages 85W (28.3% TDP), KV cache peaks at 1.18%, and 7-day waiting stays at 0; right details the PCIe TP=2 NCCL spin-wait root cause and TP=1 remediation saving 10-12 GPUs.](../../assets/practices/low-util-gpu-serving-governance/fake-100-anatomy.png)

| Telemetry Dimension | `AZ-1` (12 GPUs, 6×2-GPU Pods) | `AZ-2` (12 GPUs, 6×2-GPU Pods) | Data-Driven Verdict |
| --- | --- | --- | --- |
| Surface `DCGM_FI_DEV_GPU_UTIL` | 7d avg `10.2%` / Max **`100%`** | 7d avg `9.8%` / Max **`100%`** | **Misleading**: `39.3%` of minutes in 24h hit `>= 95%` |
| True Compute `DCGM_FI_PROF_SM_ACTIVE` | 24h avg `5.1%–6.1%` / peak **`13.4%–19.5%`** | 24h avg `5.3%` / peak **`19.0%`** | **Key evidence**: when `GPU_UTIL = 99%`, `SM_ACTIVE` is `7.3%–14.7%` |
| Matrix Compute `DCGM_FI_PROF_PIPE_TENSOR_ACTIVE` | 24h avg `0%` / peak **`3.9%–5.9%`** | 24h peak **`5.0%`** | Tensor Cores sit idle over `94%` of the time |
| GPU Power `DCGM_FI_DEV_POWER_USAGE` | 24h avg **`85 W`** (peak `233 W`) | 24h avg **`82 W`** (peak `228 W`) | `300 W` TDP GPUs running near idle power |
| 7-Day Cluster QPS (5m smoothed) | Avg `11.8` / P95 `16.5` / Max **`17.9 QPS`** | Avg `11.6` / P95 `16.1` / Max **`17.4 QPS`** | Each 2-GPU pod handles only **`2.5–2.6 QPS`** at peak |
| vLLM Queue & KV Cache (7d Max) | Max Running `6` / **Waiting `0`** / KV **`0.77%`** | Max Running `8` / **Waiting `0`** / KV **`1.18%`** | **Zero queuing for 7 days** (`0.0 ms` queue), `99%` KV free |
| Latency & Token Profile (24h) | Avg E2E `74.5 ms` (TTFT `37.8 ms` / P99 `652 ms`), avg `2,379 tok` in (`82.8%` PC hit) / `6.0 tok` out | Avg E2E `70.6 ms` (TTFT `37.6 ms` / P99 `622 ms`), avg `2,379 tok` in (`84.0%` PC hit) / `5.5 tok` out | P99 comes from occasional longer single-request outputs, unrelated to replica count (`Queue = 0`) |

### PCIe TP=2 Spin-Wait Without NVLink

Putting launch flags next to the interconnect topology explains it completely:
1. The `17.5 GiB` BF16 checkpoint ran with `--quantization fp8`, shrinking actual weights to **`~9 GB`**;
2. However, the deployment reused a large-model template and enabled **`TP=2` (`144 GB` total VRAM) + `--disable-custom-all-reduce`** on **`72G PCIe` GPUs without NVLink**;
3. Without NVLink, every transformer layer synchronizes tensors across PCIe via NCCL AllReduce, whose **spin-wait** polling kernels register as **`99%–100%`** in `nvidia-smi` and `DCGM_FI_DEV_GPU_UTIL`, even while SM activity stays at `7%–15%` and board power averages `85 W`.

### Remediation With 2× Failover Headroom

Even sized so a single zone absorbs **2× failover peak (`35 QPS`)**:
- **Immediate zero-risk step**: Keep `TP=2` and adjust to 4 pods (8 GPUs) per AZ (16 GPUs total)—**frees 8 more 72G GPUs**;
- **Root-cause win-win**: Platform engineers help canary `TP=2 -> TP=1`—a `~9 GB` model fits effortlessly on a single 72G GPU, **eliminating non-NVLink PCIe AllReduce spin-wait and cross-card latency jitter entirely**; running `6–7` single-GPU replicas per AZ (`12–14` GPUs total) improves stability while freeing **`10–12` more 72G GPUs**.

---

## 2. Four-Category Audit of 25 Services

Applying the same four-dimensional telemetry across all **25 low-utilization services** separates them into four distinct engineering profiles:

![Four-quadrant portfolio of 25 low-utilization GPU inference services: Category 1 holds 140 of 257 active GPUs across 5 services with 66-88 reclaimable; Category 2 holds 65 GPUs across 7 bursty services with 18-24 reclaimable via Prefix Cache and multiplexing; Category 3 holds 26 GPUs across 6 zero-Tensor services with 10-14 reclaimable; Category 4 holds 26 GPUs already scaled to HA floor.](../../assets/practices/low-util-gpu-serving-governance/four-quadrant-portfolio.png)

Plotting representative services side by side (`GPU_UTIL Max` vs. `SM_ACTIVE Peak` vs. `Tensor Peak`) makes the structural divide unmistakable:

![Hardware fingerprints of 9 anonymized production services across three low-util archetypes: Category 1 shows 100% GPU_UTIL with low SM/Tensor; Category 2 shows 79-95% true SM bursts; Category 3 shows 0% Tensor Core utilization, proving timeouts stem from non-GPU bottlenecks.](../../assets/practices/low-util-gpu-serving-governance/sm-vs-tensor-diagnosis.png)

---

### Category 1: Fake 100% and Overprovisioning

These 5 services currently hold **`140` GPUs** (`20%` of the list yet **`54.5%`** of all `257` active GPUs). Sharing the full hardware and engine evidence makes rightsizing straightforward and low-risk, collaboratively freeing **`66–88` GPUs**:

| Anonymized Service | GPU Tier & Current Count | Initial Concern / Status | Hardware & Engine Telemetry | Collaborative Fix & Savings |
| --- | --- | --- | --- | --- |
| **`SVC-01`** (27B Dual-AZ Chat) | `44×` 72G PCIe (`24 + 20`) | Pending review notes | **Largest optimization headroom**: BF16 `TP=4` (`288 GB` for 27B); SM avg `2.9%` / peak `49%`; 24h avg `0.3` QPS, 7d peak `0.9 QPS`/AZ (`< 1.8 QPS` total); Max Running `1–2`, **Waiting `0`**, KV peak `1.6%–2.4%` | Help switch to `TP=2` (or FP8 `TP=2`, cutting non-NVLink PCIe sync overhead), keep `2–3` replicas/AZ (`8–12` GPUs total) or join shared pool; **free `32–36` GPUs** |
| **`SVC-02`** (Dual-AZ Fine Reranker) | `36×` 72G PCIe (`18 + 18`) | High fan-out bursts; planned tidal | **Fake `100%` #2**: `GPU_UTIL Max = 100%`, yet SM avg `3.6%` / peak `27%–28%`, Tensor peak `9%`; 7d avg `1.3` / peak `3.4 QPS` (`< 0.4 QPS`/Pod); **Waiting `0`**, KV peak `7%–10%`, PC hit `81%` | Rightsize with ample headroom to `8–10` GPUs/AZ immediately with zero queuing; **free `16–20` GPUs** |
| **`SVC-03`** (Dual-AZ Relevance Scorer) | `24×` 72G PCIe (`28 → 24`) | `max 100%` peak concern | Case study above: `~9 GB` FP8 on non-NVLink PCIe `TP=2` (`144 GB`), SM peak `19.5%`, Tensor peak `5.9%`, **Waiting `0`**, KV peak `1.2%` | Trim to `8 + 8` or canary `TP=1` (`6 + 6` ~ `7 + 7`); **free `8–12` more GPUs** |
| **`SVC-04`** (Dual-AZ Internal Tool) | `32×` 48G PCIe-A (`48 → 32`: `12 + 20`) | Unpredictable usage windows | 12-GPU side averages `2.2%` util, `1.3%` SM, `33 W` power, `27 GB` VRAM; asymmetric `12 + 20` split | Align both zones to `12 + 12` (`8` GPUs freed), then add tidal scaling (`8` more); **free `8–16` GPUs** |
| **`SVC-05`** (14B Internal Chat) | `4×` 24G GPU | Pending review notes | SM avg `1.4%` (peak `53%`), Tensor peak `16%`, avg power `39 W` | Confirm dependency scope with owner; rightsize to 2 GPUs or retire; **free `2–4` GPUs** |

---

### Category 2: Real Queues and Bursts

These 7 services hold **`65` GPUs**, and cutting replicas blindly would trigger immediate SLA degradation—hardware profiling confirms genuine peak saturation (`SM 79%–96%` and `Waiting > 0`). Here, the platform's role is to **defend their capacity against naive cuts while delivering Hybrid Prefix Caching, shared-pool priority multiplexing, or tidal autoscaling to safely save `18–24` GPUs**:

| Anonymized Service | GPU Tier & Current Count | Verified Hardware / Engine Bottleneck | SLA-Safe Platform Enablement |
| --- | --- | --- | --- |
| **`SVC-06`** (27B-FP8 Bursty Summarizer) | `32×` 72G PCIe (`16 + 16`) | **True heavy burst**: SM peak `78%–79%`, KV peak `41%`, `Waiting = 2–3`, QPS jumps `0.7 -> 10.0` (`14×` spike), E2E `7.1 s` | Do not hard-cut standalone; idle `80%+` of the day, ideal to share a 27B-FP8 pool with online traffic via CNCF `llm-d` EPP priority queues (`+10` online / `-10` batch, zero `429`); **save `12–16` GPUs** |
| **`SVC-07` & `SVC-08`** (2B / 0.8B Hybrid Moderation) | `9 + 2 = 11×` 48G PCIe-A | **True high-QPS burst**: SM peak **`95% / 84%`**, Tensor peak `68% / 47%`, Max QPS `194 / 137`, **`Waiting = 43 / 458`** | **Protect capacity—never hard-cut!** Telemetry uncovered both run legacy vLLM (v0.27) with **Hybrid Prefix Caching OFF (`0%` hit)**, recomputing `500–930 tok` of fixed rules per request—while a sibling 1B VLM with `97.2%` prefix-cache hit serves `460 QPS` on 2 GPUs. Assist upgrade to `vLLM 0.33.0+` with Hybrid Prefix Caching (see our [Single-L20 Hybrid Multi-LoRA benchmark](hybrid-multi-lora-l20-prefix-cache.md) proving `4.1×` QPS gains) + consolidate duplicate weights to **safely save `6–8` GPUs** |
| **`SVC-09`** (14B Legacy Scorer) | `8×` 48G PCIe-A (`4 + 4`) | Only 2 `TP=2` pods/AZ; fan-out triggers `Waiting = 16–17`, E2E `718 ms` | Cannot remove a replica without losing HA; runs legacy vLLM v0.12.0 (`39%` PC hit vs. `83%` on newer build)—help upgrade engine or migrate smoothly |
| **`SVC-10`** (Dual-AZ Search Ranker) | `8×` 72G PCIe (`16 → 8`) | After round-1 halving, 7d Max Running `12–14`, `Waiting = 3–5`, PC hit `74%` | Already at healthy utilization; respect current footprint and observe for 1 week |
| **`SVC-11` & `SVC-12`** (Image Edit / Vision Picker) | `4×` 48G PCIe-A + `2×` 48G PCIe-B | **True batch saturation**: SM peak **`87% / 96%`**, Tensor peak `37% / 90%` | Do not hard-cut before upstream async shaping; provide KEDA tidal autoscaling or Scale-to-Zero (see [KEDA + Volcano + DRA Tidal GPU Lab](keda-volcano-tidal-gpu.md)) |

---

### Category 3: Zero-Tensor Non-GPU Bottlenecks

These 6 services hold **`26` GPUs**: when application teams report *"removing one GPU caused timeouts,"* they are completely right—and hardware telemetry proves **`Tensor = 0%`, meaning the bottleneck is not GPU compute**; fixing concurrency or moving to CPU eliminates timeouts while saving **`10–14` GPUs**:

| Anonymized Service | GPU Tier & Current Count | Owner Feedback | Hardware Reality (Why Scale-Down Timed Out) | Collaborative Root-Cause Fix |
| --- | --- | --- | --- | --- |
| **`SVC-13`** (Vision Dual-Encoder) | `6×` 24G GPU | Small model cannot handle per-instance concurrency; scale-down hurts KPI | `GPU_UTIL` 7d peak `29%`, SM peak **`9%`**, **`Tensor = 0%`**, VRAM only **`4 GB / 24 GB`**, avg power `41 W` | 6× 24G GPUs doing <0.5 GPU of compute! Help enable Triton/ONNX Dynamic Batching or run 3× 4 GB instances per 24G GPU (`6 -> 2` HA GPUs), **saving `4×` 24G GPUs while increasing concurrency headroom** |
| **`SVC-14`** (Search Ranking Baseline) | `6×` 48G PCIe-B (`3 + 3`) | Core baseline; scaling down causes severe timeouts | SM avg `0.8%–1.0%`, peak **`4%–5%`**, **`Tensor = 0%`**, VRAM pre-allocated `34 GB` (48G GPU) | Process-level concurrency / framework memory pre-allocation bottleneck, not GPU compute; co-evaluate MIG/MPS multi-instance or CPU inference to free 48G GPUs |
| **`SVC-15` & `SVC-16`** (Search/Rec Control Groups) | `4 + 4 = 8×` 24G GPU | Timeouts when scaled; CPU pilot underway | Both **`Tensor = 0%`**; SM peaks `6%–14%` and `8%–24%`, VRAM `15 GB` each | Support CPU inference parity testing and smooth migration; **free `4–8×` 24G GPUs** |
| **`SVC-17`** (New Vision Classifier) | `4×` 72G PCIe (`2 + 2`) | Full rollout ramping up | SM avg `3.6%` / peak `9%–10%`, Tensor `2%`, yet pre-allocates `62 GB` VRAM | Support rollout for 1 week; if SM stays `< 20%`, help trim pre-allocation and move to 48G tier |
| **`SVC-18`** (Dual-AZ Object Detection) | `2×` 24G GPU | Live endpoint requires 2-GPU HA | Only **`1 GB / 24 GB`** VRAM, SM avg `4.1%`, power `43 W` | Preserve full dual-AZ HA while colocating with other `1–4 GB` vision models on shared GPUs |

All six share the same underlying trap: **single-process synchronous blocking, greedy framework VRAM pre-allocation, or CPU feature bottlenecks** force teams to add whole GPUs just to buy worker concurrency. When the platform team helps enable dynamic batching, multi-instance sharing, or CPU serving, both timeout risk and GPU waste disappear together.

---

### Category 4: Minimum HA Baseline

Seven services had already partnered with the platform in round 1 to trim from **`53 → 26` GPUs** down to their minimum HA or single-GPU baseline (freeing `27` GPUs):
- **Voice / ASR / TTS Dual-AZ Canary (4 services, `28 → 14` GPUs)**: full-duplex voice (`16 → 8×` 48G GPUs), ASR (`4 → 2×` 48G GPUs), and two TTS endpoints (`4 → 2×` 48G GPUs each), all at 1 instance per AZ;
- **Evaluation & Validation (2 services, `11 → 2` GPUs)**: both trimmed to 1 GPU each;
- **Visual Retrieval (1 service, `14 → 10×` 24G GPUs)**: 4 GPUs freed (`6 GB` VRAM / `1%` Tensor peak leaves room for a future multi-instance optimization if needed).

---

### Long-Tail Fine-Tunes: Shared Multi-LoRA

Once Categories 1–3 are addressed, platform teams inevitably hit a **physical granularity floor**: dozens of long-tail fine-tuned models, canary variants, and vertical tasks (such as `SVC-01`, `SVC-05`, and Category-4 services already trimmed to 1 replica per zone) only serve `0.3–10` QPS—yet under the traditional **"offline-merged full weights + standalone Deployment"** model, dual-AZ high availability still locks at least **`2` whole GPUs** per model (`4` GPUs if `TP=2`). Shrinking replicas alone can go no further.

This is where **Multi-LoRA shared base pools** turn long-tail governance into a direct win for both platform and application teams:

1. **Cluster same-base fine-tunes using platform telemetry and skip offline merging**: Scan fine-tuned deployments by shared base architecture (such as common 2B, 8B, 14B, or 27B Dense/Hybrid bases). For low-QPS long-tail and experimental endpoints sharing a base, help teams move from "merge full multi-GB weights and request dedicated HA GPUs" to "deliver a `30–90 MB` LoRA adapter and hot-load it onto a shared dual-AZ Multi-LoRA pool."
2. **Proactively eliminate the two concerns teams care about most—accuracy parity and noisy neighbors**:
   - **Automated parity gates**: Provide ready-to-run online LoRA vs. offline-merged greedy verification scripts showing lossless native support (including modern hybrid linear-attention bases), with only tens of MB per GPU slot and `< 5%` incremental throughput tax from `1` to `8` concurrent adapters;
   - **Affinity routing + work-conserving isolation**: Place model-aware routing in front of shared pools (AIBrix `ModelAdapter` or CNCF `llm-d` EPP affinity routing with priority queues) so interactive long-tail tasks keep tight tail latency even when batch workloads run alongside them.
3. **Turn cost governance into iteration velocity for ML teams**: Previously, launching a new vertical fine-tune or A/B canary meant waiting on `2–4` GPUs, merging weights offline, and provisioning a standalone service and endpoint. On a shared Multi-LoRA pool, **shipping a new fine-tuned variant takes seconds via hot-loading a lightweight adapter—zero GPU wait time, instant canarying, and effortless cleanup**.
4. **Respect engineering boundaries—never force Multi-LoRA everywhere**: High-QPS flagship services that already saturate dedicated GPUs, as well as massive MoE + Expert Parallel + speculative decoding stacks, should stay offline-merged (avoiding the `13%` fixed Punica kernel tax). Focus Multi-LoRA squarely on **same-base long-tail fine-tunes, vertical rules, and low-QPS experimental pools**.

---

## 3. Platform Enablement and Toolkit

Looking back across all 25 services, the biggest lesson goes beyond GPU counts—it is about **how a GPU platform team should partner with application teams**:

1. **Never blindly challenge business value**: Deciding whether a model justifies its product impact belongs to the business. Waving a `GPU_UTIL = 5%` chart to question whether a team "deserves" GPUs is both unhelpful and adversarial.
2. **The platform's primary responsibility is collecting deeper, richer GPU data**: Most application engineers should not have to debug `DCGM_FI_PROF_SM_ACTIVE`, non-NVLink PCIe NCCL spin-wait, or vLLM Hybrid Prefix Cache hit rates on their own. **The GPU platform should continuously collect comprehensive hardware, interconnect, and serving-engine metrics** and surface clear diagnostics so application teams can see exactly where cycles go.
3. **Deliver engineering solutions, not arbitrary quotas**: When telemetry reveals fake `100%` spikes, help canary `TP=2 -> TP=1`; when telemetry confirms real bursts, bring Hybrid Prefix Caching, shared-pool priority routing, and tidal autoscaling to the table; when `Tensor = 0%` explains timeouts, help roll out dynamic batching or GPU sharing. When optimization makes latency cleaner *and* lowers the bill, efficiency becomes a shared win.

### Attribution, Self-Service Skills, and Weekly Loop

Collecting deep hardware metrics is only half the battle. To turn governance across hundreds of GPUs into a lightweight ongoing workflow rather than a quarterly manual spreadsheet exercise, three platform practices made the biggest operational difference:

1. **Customizing `dcgm-exporter` to stamp business and owner labels onto every GPU metric**: Upstream `dcgm-exporter` only labels metrics by node, GPU, and Pod, forcing brittle kube-state-metrics joins or manual lookups whenever anyone slices utilization by team. Through a lightweight customization of `dcgm-exporter`, we inject **business domain, service, department/queue, and owner metadata directly as metric labels at export time**, binding "GPU → Pod → Service → Business → Owner" natively on every time series. Slicing utilization, idle ratios, or drill-downs by team, domain, GPU tier, or individual owner becomes an instant single-query operation—eliminating manual reconciliation altogether.
2. **Shipping self-service Agent Skills so application teams can audit their own efficiency**: Application and ML engineers should not have to memorize `DCGM_FI_PROF_SM_ACTIVE` or engine metric names. The platform packages four-metric profiling, fake-`100%` detection, daily P90/peak trends, and efficiency breakdowns into ready-to-use **Agent Skills** so owners can query and verify their own GPU utilization accurately in plain language—turning the platform from a black-box auditor into a transparent self-service calculator.
3. **Weekly alerts, targeted email digests, and a continuous governance tracker**: Built on those exact attribution labels, the platform runs **weekly low-utilization alerts** and sends **targeted weekly email digests** directly to each owner (complete with 7-day SM/Tensor peaks, QPS, queuing, and concrete next steps), paired with a lightweight **collaborative tracking ledger** that records failover rationale and optimization milestones. That end-to-end loop—clean attribution, self-service skills, weekly touchpoints, and steady follow-through—is what enabled these 25 services to collaboratively free `56` GPUs in round 1 and keep shipping architecture wins smoothly.

### Four-Metric PromQL Bundle

Upgrade cluster observability from single-metric `GPU_UTIL` to this **four-metric PromQL bundle** (replace `<SERVICE_LABEL>` with your cluster's service label such as `app` or `deployment`):

```promql
# 1. True SM Activity (24h peak, %) -- exposes PCIe NCCL spin-wait fake 100%
max by (cluster, pod_name, gpu) (
  max_over_time(DCGM_FI_PROF_SM_ACTIVE{service="<SERVICE_LABEL>",pod_name!=""}[24h])
) * 100

# 2. Tensor Core Utilization (24h peak, %) -- spots non-GPU bottlenecks
max by (cluster, pod_name, gpu) (
  max_over_time(DCGM_FI_PROF_PIPE_TENSOR_ACTIVE{service="<SERVICE_LABEL>",pod_name!=""}[24h])
) * 100

# 3. Serving Engine 7-Day Max Queue & Peak KV Cache (%) -- verifies real queuing
max by (cluster) (max_over_time(vllm:num_requests_waiting{service="<SERVICE_LABEL>"}[7d]))
max by (cluster) (max_over_time(vllm:kv_cache_usage_perc{service="<SERVICE_LABEL>"}[7d])) * 100

# 4. Serving Engine 7-Day Peak QPS (5m smoothed) & 24h Prefix Cache Hit Rate
max_over_time((sum by (cluster) (rate(vllm:request_success_total{service="<SERVICE_LABEL>"}[5m])))[7d:5m])
sum by (cluster) (increase(vllm:prefix_cache_hits_total{service="<SERVICE_LABEL>"}[24h]))
  / sum by (cluster) (increase(vllm:prefix_cache_queries_total{service="<SERVICE_LABEL>"}[24h]))
```

> **Collection prerequisite**: `DCGM_FI_PROF_SM_ACTIVE` and `DCGM_FI_PROF_PIPE_TENSOR_ACTIVE` require enabling DCGM profiling (`PROF`) metrics in DCGM Exporter. On older architectures or partitioned GPUs without `PROF` counters, combine `DCGM_FI_DEV_POWER_USAGE / TDP` with serving-engine `Waiting / KV%`. Also label node interconnect topology explicitly (such as NVLink presence) so deployment templates warn early before small weights land on non-NVLink PCIe `TP=2/4`.

### Collaborative Decision Tree

With four-metric telemetry in place, platform and application teams can align in five minutes:

1. **Check queue and true SM first**: If `7d Max Waiting == 0`, `KV peak < 15%`, and `SM_ACTIVE peak < 35%` → **Category 1 (Fake 100% / Safe Rightsize)**. Check for small models placed on non-NVLink PCIe `TP=2/4`, size safely for 2× failover peak, and canary lower `TP`.
2. **If `SM_ACTIVE peak >= 70%` or `7d Max Waiting > 0`** → **Category 2 (Real Load)**. Protect SLA and never hard-cut. Check whether Prefix Cache hit rate is near `0%` (upgrading to enable Hybrid Prefix Caching often yields `3–4×` throughput) and whether an `80%+`-idle bursty pool can share a base pool with `llm-d` EPP priority flow control or KEDA tidal autoscaling.
3. **If `PIPE_TENSOR_ACTIVE peak <= 2%` with low VRAM and scale-down timeouts** → **Category 3 (Non-GPU Bound)**. Partner on Dynamic Batching, multi-instance GPU sharing (MIG / MPS / ModelClaim), or CPU inference validation.
4. **If a service is already at its minimum HA floor (`1–2` GPUs/AZ) yet remains low-QPS and shares a base model with sibling fine-tunes** → **Guide it onto a shared Multi-LoRA pool**, breaking the "1 long-tail model = 2–4 whole GPUs" floor while giving ML engineers second-level hot deployment and canary velocity.
5. **Maintain a Joint Capacity & Efficiency Record**: Whenever a high-value GPU service needs dedicated headroom, co-document three objective baselines—**target P99 latency SLA**, **single-replica load-test knee QPS**, and a **four-metric hardware snapshot**. That protects necessary failover margin with hard evidence while giving both teams a clear roadmap for future efficiency upgrades.

---

## Summary

Looking back across all 25 production services, three durable lessons stand out for any GPU platform team:

1. **Collect complete telemetry before discussing scale-downs**: A single `DCGM_FI_DEV_GPU_UTIL` line cannot expose fake `100%` spikes from non-NVLink PCIe `TP=2` spin-wait, nor separate real bursts from `Tensor = 0%` concurrency limits. Collecting `PROF_SM_ACTIVE`, `PIPE_TENSOR_ACTIVE`, node NVLink topology labels, and engine `Waiting / KV% / Prefix Cache` metrics is the platform's first job.
2. **Empower application teams with data rather than questioning business value**: Protect genuinely bursty services while bringing Hybrid Prefix Caching, priority multiplexing, and tidal scaling; help fake-100% and non-GPU-bound services adopt `TP=1`, dynamic batching, or CPU serving; and guide long-tail fine-tunes stuck at the HA floor onto **shared Multi-LoRA pools** that deliver both GPU savings and second-level hot deployments.
3. **Turn governance into a repeatable engineering loop**: Combining `dcgm-exporter` owner attribution, self-service Agent Skills, weekly alerts and email digests, a collaborative governance tracker, and joint capacity records turns GPU efficiency into a continuous shared win rather than a recurring end-of-quarter tug-of-war.

---

## Sanitized Data & Related Reading

- Anonymized summary dataset: [audit_summary.json](../../assets/practices/low-util-gpu-serving-governance/audit_summary.json)
- Related reading:
  - [Single-L20 Hybrid Multi-LoRA Limit Benchmark: Qwen3.5-2B Saturation Knee and the 544-Token Prefix Cache Sawtooth Cliff](hybrid-multi-lora-l20-prefix-cache.md) (benchmark proof for the `4.1×` Hybrid Prefix Cache win in Category 2)
  - [Multi-LoRA Sharing on NVIDIA L20: AIBrix v0.8.0 vs. CNCF llm-d EPP v1.0.0](multi-lora-l20-aibrix-vs-llmd.md) (shared-pool priority multiplexing and noisy-neighbor isolation for Category 2)
  - [How Do Borrowed Nighttime Inference GPUs Return? KEDA, Volcano, and DRA Lab](keda-volcano-tidal-gpu.md) (tidal autoscaling closed loop for bursty services)
  - [Why GPU Utilization Is Low](low-gpu-utilization.md) (foundational wait-chain diagnosis)
