---
title: "Lending inference GPUs overnight: declarative reclaim, fragmentation, Gang jobs, and DRA DeviceTaintRule"
description: "Hands-on tests on 16 simulated B300 GPUs and 4 DRA devices using KEDA v2.21.1, Volcano v1.16.0 multi-queue reclaim, binpack fragmentation control, 12-GPU Gang jobs, and three failure drills."
date: 2026-11-23
last_reviewed: 2026-11-24
status: tested
applicable_versions: "Kubernetes v1.37.2, Volcano v1.16.0, KEDA v2.21.1, fake-gpu-operator v0.2.1, dra-example-driver v0.5.0"
---

# Lending inference GPUs overnight: declarative reclaim, fragmentation, Gang jobs, and DRA DeviceTaintRule

At ten in the evening, an online model sees light traffic and needs only 4 baseline GPUs instead of its daytime 8. Can the idle 4 GPUs be lent automatically to offline batch inference or distributed training? When a midnight traffic burst hits, how fast do the GPUs come back without custom glue scripts—and what breaks when an offline container hangs, when GPUs fragment across nodes, or when you switch from `nvidia.com/gpu` to DRA?

We ran five hands-on test suites on a local 3-node Kubernetes v1.37.2 cluster (two 8-GPU workers exposing **16 simulated B300 GPUs** plus **4 exclusive DRA example devices**) using **KEDA v2.21.1**, **Volcano v1.16.0 multi-queue `reclaim`**, and **Kubernetes v1.37 native `DeviceTaintRule`**:

- **16-GPU `nvidia.com/gpu` declarative lending and reclaim (zero custom handoff script)**: Overnight, an offline `vcjob` automatically borrowed up to 12 GPUs (16/16 GPUs utilized). After injecting **400 burst online requests**, KEDA scaled the elastic Deployment and Volcano `reclaim` evicted exactly 4 offline Pods while the remaining 8 kept running uninterrupted. Within **13.10 s** of enqueue, all 4 elastic replicas were Running and serving; **400/400 online requests** completed (252 base, 148 elastic) and **720/720 offline items** committed with an execution count of 1 each.
- **Three real Volcano + KEDA production traps caught live**: Volcano's default `overcommit` plugin blocked a 4-GPU online `PodGroup` in `Pending` at 16/16 GPU utilization; the default Deployment `PodGroup` (`minMember: 1`) stopped `reclaim` after 1 GPU; and `vcjob`'s default `maxRetry: 3` failed the entire offline job (`Failed`) during a 4-GPU reclaim wave.
- **Measured DRA `ResourceClaim` boundary and Kubernetes v1.37 fix**: In Volcano v1.16.0, `capacity` enforces DRA admission quotas, but **`reclaim` does not automatically evict DRA devices** (full DRA nodes are filtered out during preemption predicates). On Kubernetes v1.37, applying a native **`DeviceTaintRule (NoExecute)`** with an offline `tolerationSeconds: 2` window handed `gpu-1` to the waiting online Pod in **5.39 s**.
- **Fragmentation control, Gang jobs, and chaos drills**: Volcano `binpack` plus `pod-deletion-cost` cleared a full 8-GPU worker so an 8-GPU single-node job started in **5.32 s** (versus `Pending` under spread with the same 10 free GPUs). A 12-GPU multi-node Gang `vcjob` showed **8 zombie GPUs** under `RestartPod` versus clean full release (2.48 s full reset, 4 online GPUs Ready at **7.12 s**) under `RestartJob`. Chaos drills verified a **20.63 s** bounded ceiling for a rogue `SIGTERM`-ignoring worker (`terminationGracePeriodSeconds: 15`) and exposed two critical blind spots in KEDA `fallback`.

> All workloads in this lab are lightweight synthetic processes. The timings measure **control-plane detection, scheduling reclaim, device release, and container startup**—production time to first token must also include image pulls, model weight loading, and engine warmup.

---

## Choose what to hand over: engine sleep vs. whole-device lending

| Goal | Mechanism | Cost when demand returns |
| --- | --- | --- |
| Alternate two models in one GPU's VRAM | Coordinate engine sleep/wake inside the owning Pod, keeping its device allocation alive | Restore weights, rebuild KV cache, verify free VRAM |
| Lend a whole exclusive GPU to another Kubernetes Job | Scale elastic serving replicas to zero and reclaim via Volcano multi-queue `reclaim` or DRA `DeviceTaintRule` | Wait for offline checkpoint/exit, device deallocation, Pod startup, and model warmup |
| Serve latency-sensitive traffic overnight | Isolate always-on `base` replicas outside KEDA with Volcano `guarantee`, lending only elastic replicas | Base replicas absorb initial burst queuing until elastic replicas warm up |

vLLM level-1 sleep offloads weights to host memory and drops the KV cache, while level-2 also discards model parameters; SGLang exposes memory release and resume endpoints. **These calls change only in-process VRAM usage.** In our control probe, pausing the online worker while keeping its Pod alive left the exclusive `ResourceClaim` locked across two observations **9.75 s** apart, keeping a competing offline Pod `Pending`. For multi-model coexistence on one physical GPU, see our earlier L20 study. [vLLM Sleep Mode](https://docs.vllm.ai/en/latest/features/sleep_mode/) · [SGLang memory release and resume](https://docs.sglang.io/docs/advanced_features/sglang_for_rl) · [AIBrix on one L20](aibrix-modelclaim-l20.md)

Whenever overnight borrowers are independent batch or training Jobs, the elastic online Pods must terminate to return whole GPUs—and the cluster needs a declarative path to reclaim them under burst traffic.

![Declarative tidal GPU architecture and measured boundaries: Volcano reclaim for nvidia.com/gpu, Kubernetes v1.37 DeviceTaintRule for DRA, and always-on base replicas isolated outside KEDA.](../../assets/practices/keda-volcano-tidal-gpu/reclaim-mechanism-matrix.png)

---

## Lab topology and declarative queue setup

The cluster runs Kubernetes v1.37.2 across 1 control-plane node and 2 workers (`Worker A`, `Worker B`) with two device pools:

1. **16 simulated B300 GPUs (`nvidia.com/gpu`)**: `fake-gpu-operator` v0.2.1 advertises 8 `NVIDIA-B300-SXM6-AC` devices per worker for multi-queue reclaim, fragmentation control, 12-GPU Gang jobs, rogue-worker drills, and KEDA outage drills.
2. **4 exclusive DRA devices (`gpu.example.com`)**: `dra-example-driver` v0.5.0 advertises `gpu-0` through `gpu-3` on `Worker A` for Volcano DRA reclaim testing and Kubernetes v1.37 `DeviceTaintRule`.

In `volcano-system`, we ran an isolated Volcano scheduler (`tide-volcano`) and PodGroup controller (`tide-pg-controller` with `--controllers=pg-controller --scheduler-name=tide-volcano`) alongside two queues:

- **`tide-online`**: `reclaimable: false`, `guarantee: 4 GPU / 1 DRA`, `deserved: 8 GPU / 2 DRA`, `capability: 16 GPU / 4 DRA`, `PriorityClass: tide-online-high (1000)`.
- **`tide-offline`**: `reclaimable: true`, `guarantee: 0`, `deserved: 8 GPU / 2 DRA`, `capability: 16 GPU / 4 DRA`, `PriorityClass: tide-offline-low (100)`.

Because `tide-online` reserves `guarantee: 4`, Volcano's `capacity` plugin automatically caps `tide-offline`'s `realCapability` at `16 - 4 = 12` GPUs—offline jobs can borrow up to 12 GPUs without ever encroaching on the 4 baseline GPUs, while any allocation above `deserved: 8` remains immediately reclaimable by `tide-online`.

```yaml
# Verified tide-volcano scheduler config after fixing production pitfalls
actions: "enqueue, allocate, backfill, reclaim, preempt"
tiers:
- plugins:
  - name: priority
  - name: gang
    enablePreemptable: false
    enableReclaimable: false   # allow reclaiming minAvailable == replicas Gang jobs
  - name: conformance
- plugins:
  # Intentionally omit default overcommit plugin so 16/16 full utilization does not block enqueue
  - name: drf
    enablePreemptable: true
    enableReclaimable: true
  - name: predicates
    arguments:
      predicate.DynamicResourceAllocationEnable: true
  - name: capacity
    arguments:
      capacity.DynamicResourceAllocationEnable: true
      capacity.DRAConsumableCapacityEnable: true
  - name: nodeorder
  - name: binpack
    arguments:
      binpack.weight: 10
      binpack.resources: nvidia.com/gpu
      binpack.resources.nvidia.com/gpu: 10
```

---

## Trial 1: 16-GPU declarative multi-queue reclaim (`nvidia.com/gpu` vs. DRA)

### 1A. 16-GPU `nvidia.com/gpu`: full automation with zero custom handoff script

Online serving splits into `base` (fixed 4 replicas outside KEDA) and `elastic` (KEDA `ScaledObject` scaling `0–4` via a daytime Cron window plus a Redis list backlog trigger). Offline work is a 12-replica Volcano `vcjob` (`batch-elastic`, `minAvailable: 1`, `maxRetry: 50`, `PodEvicted -> RestartPod`) processing 720 items; each worker traps `SIGTERM`, commits its in-flight item to Redis, and exits cleanly (`exit 0`).

| Observation (UTC) | Cluster state | Measured outcome |
| --- | --- | --- |
| 06:57:53 | Daytime steady state: `base=4`, `elastic=4`, `offline=8` (4 Pending) | 16/16 GPUs utilized; offline fills the remaining 8 GPUs |
| 06:59:13 | Cron daytime window ends; KEDA scales `elastic` to 0 | Only the 4 baseline GPUs remain online |
| 06:59:19 | Offline scales to `12 Running` (0 Pending) | **4 freed GPUs borrowed in ~6 s** (`tide-offline` reaches `12 > deserved 8`) |
| 06:59:34.6 | **400 burst online requests** enqueued in Redis | Queue spikes; `base` absorbs initial load |
| 06:59:42.8 | **+8.2 s**: KEDA scales `elastic=4`; Volcano evicts 4 offline Pods | `worker-4/5/6/7` checkpoint on `SIGTERM` and exit; **8 other offline Pods keep running** |
| 06:59:47.7 | **+13.1 s**: All 4 `elastic` Pods `Running` and already serving 25 replies | Zero custom controller logic; **13.1 s** from enqueue to all 4 elastic GPUs serving |
| 07:00:05.5 | **+30.9 s**: All 400 online requests completed | `base`: **252**, `elastic`: **148**, zero drops |
| 07:00:15.0 | **+40.4 s**: KEDA cooldown scales `elastic` to 0; all 720 offline items done | Every offline ID has execution count **1** (zero duplicates, zero loss) |

![Light-theme Grafana 12.3.0 dashboard showing 16-GPU allocation across daytime, nighttime lending, and burst reclaim, 400 online burst requests drained, and 720 offline items completed with zero duplicates.](../../assets/practices/keda-volcano-tidal-gpu/handoff-grafana-16gpu.png)

*Captured from real Grafana (light theme) by replaying all 86 timestamped cluster and Redis samples into Prometheus. Upper-left shows total allocation holding tightly at 16 GPUs across phases; lower-right shows offline progress climbing continuously to 720/720 across 4 graceful `SIGTERM` evictions.* [Sample CSV](../../assets/practices/keda-volcano-tidal-gpu/observations.csv) · [Consolidated verification JSON](../../assets/practices/keda-volcano-tidal-gpu/events.json)

### Three real Volcano + KEDA production traps caught during Trial 1A

Before Trial 1A succeeded end-to-end, we hit and isolated three silent failure modes directly from scheduler logs:

1. **Trap 1: `overcommit` blocks `reclaim` at 100% GPU utilization.** Volcano's default Helm config enables `overcommit` with factor `1.2`. On a full 16-GPU cluster (limit `19.2`), a 4-GPU elastic `PodGroup` (`16 + 4 = 20 > 19.2`) was rejected at `enqueue` (`overcommit.go:129: Resource in cluster is overused, reject job ... to be inqueue`). Because the `PodGroup` stayed `Pending`, `reclaim.go:73` skipped it altogether. **Fix**: remove `overcommit` on `capacity + reclaim` schedulers and let `capacity` enforce queue limits.
2. **Trap 2: Default Deployment `PodGroup(minMember=1)` stops `reclaim` after 1 GPU.** Volcano's `pg-controller` creates one `PodGroup` per `ReplicaSet` with default `minMember: 1`. Because `reclaim.go:91` triggers only while `JobStarving (waiting + ready < minMember)` is true, scaling `elastic` `0 -> 4` reclaimed only the first GPU, flipped `JobStarving` to `false`, and logged `No preemptors in Queue <tide-online>, break.`, leaving replicas 2–4 stuck `Pending`. **Fix**: set `scheduling.volcano.sh/group-min-member: "4"` on fixed-step elastic Deployments, or split variable-step elastic capacity into separate 1-replica Deployments (or sync `minMember` dynamically).
3. **Trap 3: `vcjob` default `maxRetry=3` kills the offline job on a 4-GPU reclaim wave.** Every `PodEvicted -> RestartPod` increments `vcjob.status.retryCount`. Reclaiming 4 pods at once tripped `retryCount=3 -> Failed`, marking the entire `vcjob` `Failed` and terminating the other 8 healthy offline Pods. **Fix**: set an explicit `spec.maxRetry` headroom (such as `50`) on reclaimable batch `vcjob`s.

### 1B. DRA `ResourceClaim` under the exact same setup: Volcano v1.16.0 does not reclaim

Using the **same `tide-volcano` scheduler and queues** (with both `predicate.DynamicResourceAllocationEnable: true` and `capacity.DynamicResourceAllocationEnable: true`, plus `deviceclass/gpu.example.com` `capability`/`deserved`/`guarantee` configured per Volcano's DRA quota guide), we tested the 4 DRA devices:

- Nighttime steady state: `dra-base` held `gpu-0`; `dra-batch` (`tide-offline`) borrowed `gpu-1`, `gpu-2`, `gpu-3` (`3 > deserved 2`, 4/4 DRA devices full).
- Trigger: scaled `dra-elastic` (`tide-online`, `deserved: 2`) from `0 -> 1` and observed for 35 seconds.
- **Measured outcome: `reclaimed_automatically = false`, 0 evictions**, and `dra-elastic` stayed `Pending`.

The `-v=4` `tide-volcano` logs pinpointed two causes:
1. **Full DRA nodes are eliminated before victim selection**: `reclaim.go:183` runs `PredicateForPreemptAction` before tentative eviction, where `DynamicResources` fails `Worker A` with `cannot allocate all claims`, removing the node before `reclaim` inspects candidate victims.
2. **`capacity` reclaim dimensions exclude DRA**: `capacity.go:686` logged `Queue <tide-online> can reclaim on resource dimensions: [cpu memory]`. In addition, `totalResource` sums `Node.Status.Allocatable` (which omits DRA devices), clamping `tide-online`'s scalar `deserved` for `deviceclass/gpu.example.com` down to its `guarantee` of 1.

> **Takeaway**: In Volcano v1.16.0, `deviceclass/<DeviceClass>` works for queue admission quota, **not yet for automated cross-queue DRA `reclaim`**. On DRA-based clusters, pair quota with Kubernetes v1.37's native `DeviceTaintRule` (Trial 4C below).

---

## Trial 2: 16-GPU fragmentation governance and 12-GPU Gang `vcjob` reclaim

### 2A. Why 10 free GPUs cannot fit an 8-GPU single-node job

With 6 online GPUs kept overnight across two 8-GPU workers (10 GPUs free cluster-wide), we submitted one 8-GPU single-node `vcjob` (representing intra-node NVLink training):

- **Control (Default spread)**: Online replicas split 3 + 3 across `Worker A` and `Worker B`, leaving 5 + 5 free. The 8-GPU `vcjob` stayed **`Pending`** (`0/3 nodes are unavailable: 3 Insufficient nvidia.com/gpu`).
- **Governed (`binpack` + `pod-deletion-cost`)**: Daytime 10 online replicas packed 8 on `Worker A` + 2 on `Worker B` via Volcano `binpack`. Annotating `controller.kubernetes.io/pod-deletion-cost` (`"100"` on fuller `Worker A`, `"-100"` on sparse `Worker B`) before scaling `10 -> 6` drained `Worker B` first, leaving 6 on `Worker A` + 0 on Worker B (8 contiguous free GPUs on `Worker B`). The exact same 8-GPU single-node `vcjob` reached **`Running` on `Worker B` in 5.32 s**.

![16-GPU fragmentation trap vs. binpack governance: with 6 online GPUs and 10 free GPUs in both runs, spread leaves an 8-GPU single-node job Pending while binpack plus pod-deletion-cost clears Worker B and runs the job in 5.32 s.](../../assets/practices/keda-volcano-tidal-gpu/fragmentation-binpack-comparison.png)

### 2B. 12-GPU multi-node Gang `vcjob` reclaim: `RestartPod` vs. `RestartJob`

Distributed training requires all ranks to synchronize at barriers. We deployed a **12-GPU multi-node Gang `vcjob`** (`minAvailable: 12`, spanning 4 GPUs on `Worker A` + 8 GPUs on `Worker B`, synchronizing epochs via a 12-rank Redis barrier) and triggered a 4-GPU online `elastic` burst:

> **Prerequisite**: In the `gang` plugin, `gang.enableReclaimable: true` causes `gang.go:113` to refuse evicting any Pod once `ready <= minAvailable`. Set `enableReclaimable: false` on the `gang` plugin so online queues can reclaim full-width offline Gang jobs.

| Policy | Time to 4 elastic GPUs Running | Offline GPUs held during burst | Training progress | Post-burst recovery |
| --- | --- | --- | --- | --- |
| `PodEvicted -> RestartPod` (anti-pattern) | **7.13 s** | **8 zombie GPUs deadlocked** (`gang_running=8, pending=4`) | Frozen at epoch 4 waiting at 12-rank barrier | No clean group reset |
| `PodEvicted -> RestartJob` | **7.12 s** | All 12 released cleanly at 2.48 s (`gang_running=0`); watch `backfill` | Clean restart triggered across all 12 ranks | Resumed from checkpoint to **epoch 10/10 in 18.60 s** |

Trial 2B uncovered a subtle scheduler interaction: `RestartJob` cleanly terminated all 12 ranks at `t+2.48 s` (`gang_running=0, gang_pending=12`), freeing the cluster for online reclaim under `RestartJob`. However, once `vcjob` recreated the 12 Pods, `tide-volcano`'s `backfill` action still backfilled 8 of the recreated Pods onto the 8 remaining idle GPUs during the burst (`vcjob` stayed `Pending` until online scaled back down and released the final 4 GPUs). **For strict all-or-nothing Gang training, either disable `backfill` on the Gang scheduler or use `TerminateJob` with an external requeuing layer (such as Kueue).**

---

## Trial 3: Production chaos drills

### 4A. Rogue offline container ignoring `SIGTERM`: bounding worst-case SLA

In production, offline containers can hang on NCCL or checkpoint I/O, or ignore `SIGTERM` completely. With `terminationGracePeriodSeconds: 15` on both runs and `elastic` scaling `0 -> 2` on a full 16-GPU cluster:

- **Graceful `SIGTERM` exit**: Eviction seen at `1.97 s` -> Scheduled at `3.56 s` -> 2 elastic Pods **`Running` in `5.96 s`**.
- **Rogue worker (`trap '' TERM INT`, ignoring `SIGTERM`)**: Eviction seen at `2.96 s` -> kubelet waits the full 15 s grace period and sends `SIGKILL` -> Scheduled at `19.16 s` -> 2 elastic Pods **`Running` in `20.63 s`** (an exact `+14.67 s` bounded penalty).

**Takeaway**: Enforce a strict maximum `terminationGracePeriodSeconds` on `tide-offline` Pods via admission policy (Kyverno / ValidatingAdmissionPolicy) so a hung container turns into a deterministic SLA ceiling rather than an unbounded stall.

### 4B. Metric-source outage: two real blind spots in KEDA `fallback`

Scaling `tide-redis` to `0` on KEDA v2.21.1 with `ScaledObject` `fallback: {failureThreshold: 2, replicas: 2}` revealed two critical limitations:

1. **Scale-to-zero blind spot (`Active=False`)**: When `elastic` was already at `0`, taking `tide-redis` down moved the `ScaledObject` to `Ready=False, Active=Unknown, Fallback=Unknown` over 51 s—**KEDA `fallback` never woke `elastic` from `0` to `2`**.
2. **Scaler-init blind spot**: Even with `elastic` actively serving at `4` replicas (`Active=True`), killing `tide-redis` failed inside `scalers_builder.go:96` (TCP dial error while building the Redis scaler cache before `GetMetricsAndActivity`), so `fallback` never incremented (`Fallback` stayed `False`); when Redis recovered empty, KEDA immediately scaled `4 -> 0`.

**Guardrail**: Never rely on KEDA `fallback` as your baseline availability net. Keep `base` replicas in a separate Deployment outside KEDA, protected by Volcano `guarantee` and `reclaimable: false`.

### 4C. Kubernetes v1.37 native DRA `DeviceTaintRule`: 5.39 s device recall

To bridge the Volcano v1.16.0 DRA reclaim gap for DRA `ResourceClaim`s from Trial 1B, we tested Kubernetes v1.37's GA `DeviceTaintRule` (`resource.k8s.io/v1`):

- The offline Pod held `gpu-1` with a Claim toleration carrying **`tolerationSeconds: 2`** for `tide.aik8s.io/reclaim=online-only:NoExecute`.
- The waiting online Pod carried permanent `NoExecute` and `NoSchedule` tolerations and waited `Pending` while `gpu-1` was busy.
- Applying a `DeviceTaintRule (effect: NoExecute)` targeting `driver: gpu.example.com, device: gpu-1`:
  - **`t + 2.79 s`**: `DeviceTaintManagerEviction: Marking for deletion` fired right after the 2 s toleration window.
  - **`t + 4.53 s`**: The offline Pod completed its `SIGTERM` trap and exited, auto-deallocating its `ResourceClaim` while blocking untolerated offline re-entry on `gpu-1`.
  - **`t + 5.39 s`**: The waiting online Pod claimed `gpu-1` and entered **`Running`**.

> Kubelet path pitfall: on clusters using a nonstandard kubelet root, both `kubeletPlugin.kubeletRegistrarDirectoryPath` and `kubeletPlugin.kubeletPluginsDirectoryPath` must point to the actual kubelet root when installing the DRA driver—otherwise pods schedule and receive claims under `DeviceTaintRule`, then stall on `FailedPrepareDynamicResources: DRA driver ... is not registered`.

![Online recovery latency across GPU reclaim paths: DRA DeviceTaintRule 5.39 s, graceful Volcano reclaim 5.96 s, 12-GPU Gang RestartJob 7.12 s, KEDA burst to 4 serving 13.10 s, and rogue worker SIGKILL cap 20.63 s.](../../assets/practices/keda-volcano-tidal-gpu/reclaim-latency-comparison.png)

---

## Reproducing the lab and production checklist

[Download the sanitized lab kit](../../assets/practices/keda-volcano-tidal-gpu/lab.zip), containing the verified `tide-volcano` scheduler ConfigMap, `tide-online`/`tide-offline` Queues and `PriorityClass` manifests, the Kubernetes v1.37 `DeviceTaintRule` manifest, all three experiment runners, and the light-theme Grafana dashboard JSON.

```sh
export LAB_CONTEXT=your-test-context
# 1. Apply queues, PriorityClasses, and isolated tide-volcano / tide-pg-controller
kubectl --context "$LAB_CONTEXT" apply -f volcano-scheduler-cm.yaml -f queues-and-priorities.yaml
# 2. Run all three test suites
python3 exp1_multiqueue_reclaim.py
python3 exp2_gang_and_fragmentation.py
python3 exp3_chaos_drills.py
```

Before rolling out tidal GPU sharing in production, check six items:

1. **Isolate baseline serving**: Keep `base` outside KEDA scale-to-zero and reserve its GPUs with Volcano `guarantee` and `reclaimable: false`.
2. **Audit `overcommit` and `group-min-member`**: If an online `PodGroup` sits `Pending` on a full cluster, check scheduler logs for `overcommit.go` rejections and verify `PodGroup.spec.minMember` is not stuck at `1`.
3. **Raise `vcjob` `spec.maxRetry`**: Size retry headroom above your worst-case reclaim wave so batch jobs survive multi-GPU reclamation without turning `Failed`.
4. **Prevent cross-node fragmentation**: Enable `nvidia.com/gpu`-weighted `binpack` for online serving and set `controller.kubernetes.io/pod-deletion-cost` so scale-downs empty sparse nodes first.
5. **Cap offline grace periods**: Enforce an upper bound on `terminationGracePeriodSeconds` for `tide-offline` via admission policy to bound recovery SLA against hung containers.
6. **Match mechanism to device stack**: Today, **`nvidia.com/gpu` + Volcano `capacity/reclaim`** is the most mature declarative stack for automated tidal lending; on Kubernetes v1.37+ DRA clusters, pair DRA quotas with **`DeviceTaintRule (NoExecute)`** for eviction, and always budget real model cold-start and warmup time on top of these control-plane numbers.
