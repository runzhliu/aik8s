---
title: AIBrix ModelClaim on one L20 — concurrent serving, 14B handoffs and the memory limit
description: Measured concurrent inference, a round trip between two 14B engines, and placement and startup for a 22B model near the limit of one L20, with request records and reproduction settings.
date: 2026-11-23
last_reviewed: 2026-11-23
status: tested
applicable_versions: "Kubernetes v1.30.4, AIBrix v0.8.0, vLLM v0.30.0, kvcached v0.1.6"
---

# AIBrix ModelClaim on one L20 — concurrent serving, 14B handoffs and the memory limit

Two infrequently used models can tie up two GPUs if each runs in a Pod that requests a whole device. AIBrix lets one persistent pool Pod hold a GPU while several vLLM engines load, serve traffic and sleep independently inside it. On October 12, 2026, the project reported placing 39 models on eight H20 GPUs. We narrowed the question to one L20. What can a model catalog save by sharing that card between two Qwen models, and what difference will a caller notice? [Upstream design and H20 experiment](https://aibrix.github.io/posts/2026-10-12-modelclaim-gpu-sharing/)

**Both models served on one L20. The clearest cost was the wait for the first token.** At 1,024 input tokens, 128 output tokens and total concurrency four, Qwen3 handled **276.1 output tok/s** when it received all the traffic. Splitting the traffic equally between the models yielded **279.0 tok/s**. Holding Qwen3's own concurrency at two and adding traffic to its neighbor raised Qwen3's P95 time to first token from **54.6 to 73.1 ms**. Letting Qwen3 sleep between bursts also exposed the first caller to a 503 and roughly ten seconds of retry delay. Two 14B checkpoints totaling 55.02 GiB had to take turns. In the 22B trial, even the 950 MiB held by a sleeping engine changed the outcome.

## 1. How do two models fit inside one GPU Pod?

The experiment had **one inference-pool Pod, one runtime container and one physical L20**. Qwen3-0.6B and Qwen2.5-0.5B-Instruct each loaded its own weights in a separate vLLM service inside that container. Both served concurrent requests in the mixed workload. Three steps explain how they got there.

![Two ModelClaims start separate vLLM services inside one runtime container with access to the same L20][pod-topology]

1. **Kubernetes assigns one device to the container.** The pool Deployment has one replica. Its Pod template declares one application container, `aibrix-runtime`, with `nvidia.com/gpu: 1` in both requests and limits. The scheduler picks a node with available GPU capacity. The kubelet uses the device plugin to allocate a device to the container. The cluster has now accounted for a whole card, even while the pool has no models. [Pool manifest](https://github.com/vllm-project/aibrix/blob/v0.8.0/samples/modelclaim/warm-runtime-pool.yaml) · [Kubernetes GPU scheduling](https://kubernetes.io/docs/tasks/manage-gpus/scheduling-gpus/)
2. **AIBrix places both models in that running Pod.** Each ModelClaim specifies a model name, a weights location and the same pool selector. After checking the memory budget, the controller places both on the same Pod. Inside the container, the runtime assigns each claim a port and a distinct kvcached IPC name, then calls `subprocess.Popen` to launch separate `vllm.entrypoints.openai.api_server` processes. Both services can access the GPU already allocated to the container. The engine registry showed PID 28 on port 20000 for Qwen3 and PID 29 on port 20001 for Qwen2.5. These are API-server PIDs. vLLM can also launch GPU workers of its own. [Runtime engine launcher](https://github.com/vllm-project/aibrix/blob/v0.8.0/python/aibrix/aibrix/runtime/model_runtime.py)
3. **The gateway selects a port by model name.** Both clients use the same entrance. The request's `model` field selects the engine. The destinations share a Pod IP and listen on different ports. We called each engine directly and through the gateway, receiving HTTP 200 on all four calls. Qwen2.5 answered `Paris`. Qwen3 answered `7 plus 5 equals 12.`, which was correct but did not follow the number-only instruction.

### How do two vLLM engines avoid double-counting memory?

A container can run multiple CUDA processes. It is also possible to put two small models on a GPU manually. The operational question is what happens as traffic grows. Beyond the weights, each engine stores attention keys and values already computed for in-flight requests. Longer contexts and more concurrent requests increase the KV cache demand. Two manually launched servers need memory headroom for both.

ModelClaim accounts for each model's non-KV footprint and minimum KV allowance. Here each declared 6 GiB plus 1 GiB. Together they required at least **14 GiB** on a device with **44.39 GiB** of usable capacity reported by the runtime. The controller then sets a separate KV ceiling for each engine. kvcached maps physical GPU memory as requests consume cache. With both engines active, each had a 16.20 GiB KV ceiling while the entire card used only 3,752 MiB at the instant of the snapshot. AIBrix manages memory budgets and engine lifecycles. Both engines still compete for compute on the same device, as the time-to-first-token measurements below illustrate. [Reservation ledger](https://github.com/vllm-project/aibrix/blob/v0.8.0/pkg/controller/modelclaim/ledger.go) · [KV budget division](https://github.com/vllm-project/aibrix/blob/v0.8.0/pkg/controller/modelclaim/division.go)

The Pod also defines a shared failure boundary. When the Qwen3 engine slept, Qwen2.5 continued to answer. Scaling the entire pool to zero stops both services and returns the GPU to Kubernetes. Two ordinary Pods each requesting an exclusive GPU would account for two whole devices.

<details markdown="1">
<summary>How can I verify that the engines share a Pod and device?</summary>

In the reproduction environment below, wait for both claims to become Active, then run these read-only checks. Compare the Pod names and ports in the two rows. Inspect the device count, GPU model and engine registry inside that Pod. A device utilization chart alone cannot identify which model served a request.

```bash
NS=modelclaim-demo
kubectl -n "$NS" get modelclaims -o json | jq -r '
  .items[] | .spec.modelName as $model | .status.instances[]
  | [$model, .phase, .pod, .port] | @tsv'
POD=$(kubectl -n "$NS" get modelclaim qwen3-0-6b -o jsonpath='{.status.instances[0].pod}')
kubectl -n "$NS" get pod "$POD" -o json | jq '
  .spec.containers[] | {name, gpu: .resources.limits["nvidia.com/gpu"]}'
kubectl -n "$NS" exec "$POD" -c aibrix-runtime -- nvidia-smi -L
kubectl -n "$NS" exec "$POD" -c aibrix-runtime -- cat /var/run/aibrix/engines.json \
  | jq -r '.engines[] | [.model_name, .phase, .pid, .port] | @tsv'
```

</details>

## 2. Test configuration and success criteria

### Which models ran on H20, and why use Qwen2.5 on L20?

| Run | Hardware and models | What it shows |
| --- | --- | --- |
| Official step-by-step video | One H20, four claims for DeepSeek-R1-Distill-Llama-8B | On screen, model-a through model-d are separate claims pointing to the same weights. They go through different states as the demo shows placement, waiting, sleep and making room. |
| Official scale test | One eight-H20 node, 39 models ranging from 1.5B to 32B | The team reported about five models per card, roughly three awake at a time. The article does not enumerate all 39 models. The single-card video does not establish their identities. |
| This L20 experiment | One L20, two distinct checkpoints, Qwen3-0.6B and Qwen2.5-0.5B-Instruct | Both models were Active together and the mixed load sent two concurrent streams to each. A separate sleep experiment let Qwen3 go idle while Qwen2.5 continued serving. |

We chose the older Qwen2.5 checkpoint because the AIBrix v0.8.0 two-model sample supplies this exact pair and its memory declarations. Both fit comfortably on one device, so the experiment can test simultaneous service, model-name routing and whether the neighbor keeps answering when one engine sleeps. Neither model had to be unloaded for both to serve. A newer production checkpoint needs its own measurements at the intended precision, context length and concurrency. The 6 GiB declarations and measured tok/s apply to this configuration. [Official H20 scale test and walkthrough](https://aibrix.github.io/posts/2026-10-12-modelclaim-gpu-sharing/#demo) · [v0.8.0 two-model sample](https://github.com/vllm-project/aibrix/blob/v0.8.0/samples/modelclaim/modelclaims.yaml)


| Condition | Measured configuration |
| --- | --- |
| Cluster and device | Kubernetes v1.30.4, one experimental pool Pod, one NVIDIA L20, driver 580.173.02, 46,068 MiB reported by the device |
| Control plane and engines | In-place upgrade from AIBrix v0.7.0 to v0.8.0. Package versions read inside the container were vLLM 0.30.0 and kvcached 0.1.6 |
| Runtime image | `aibrix/kvcached-runtime:453ab36db68ac859f86ac94e32d0e02cec4c1505`, upstream linux/amd64 manifest `sha256:6adf0756fac893df3503cf2cf94cb9739bb46b3994ce92e06306ccaa6c12401f` |
| Models and resources | Qwen3-0.6B (A) and Qwen2.5-0.5B-Instruct (B) on separate read-only mounts. Pod CPU request/limit 4/12, host memory 28/44 GiB |
| Per-model settings | One replica, `maximumFootprint: 6Gi`, `kvFloor: 1Gi`, `--max-model-len 2048 --max-num-seqs 4 --enforce-eager` |
| Request protocol | In-cluster client through Envoy to `/v1/completions`, streaming SSE, temperature 0 and `ignore_eos=true`. Functional questions used `/v1/chat/completions` separately |

Both engines remained resident throughout the throughput matrix. A2 and B2 sent two concurrent requests to one model while its peer stayed idle. A4 sent all four lanes to A. AB sent two lanes each to A and B. Each lane issued six requests sequentially and the faster model could finish its share earlier. We tested 256 input / 64 output tokens and 1,024 / 128, with three rounds per traffic pattern and order rotated between rounds. Input sequences used different seeds drawn from the same distribution. We checked server-reported token counts on every request.

Before timing the matrix we validated streaming at both lengths on both models. A formal success required HTTP 200, the correct model name, nonempty text, `[DONE]`, `finish_reason=length` and the requested input and output counts. **All 432/432 formal requests passed across 24 rounds**, in addition to four protocol probes. Output throughput is successful output tokens divided by round wall time. TTFT runs from request start to the first nonempty text event. TPOT is the elapsed time from first to last nonempty text divided by output tokens minus one. We took nearest-rank P95 within each round, then the median across three rounds. Each round contained 12 or 24 requests, so these tail estimates apply to this comparison. [Per-request CSV](../../assets/practices/aibrix-modelclaim-l20/requests.csv) · [Per-round and per-model CSV](../../assets/practices/aibrix-modelclaim-l20/rounds.csv)

## 3. Who waits when both models receive traffic?

| Input / output | Traffic | Success / requests | Output tok/s | P95 TTFT (ms) | P95 TPOT (ms) | P95 E2E (s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 256 / 64 | A2 | 36 / 36 | 139.9 | 52.2 | 14.09 | 0.925 |
| 256 / 64 | B2 | 36 / 36 | 176.2 | 43.9 | 10.95 | 0.720 |
| 256 / 64 | A4 | 72 / 72 | 271.5 | 59.4 | 14.05 | 0.924 |
| 256 / 64 | AB | 72 / 72 | 271.7 | 53.3 | 14.09 | 0.935 |
| 1,024 / 128 | A2 | 36 / 36 | 141.0 | 54.6 | 14.07 | 1.822 |
| 1,024 / 128 | B2 | 36 / 36 | 180.6 | 46.8 | 11.15 | 1.453 |
| 1,024 / 128 | A4 | 72 / 72 | 276.1 | 75.9 | 14.15 | 1.842 |
| 1,024 / 128 | AB | 72 / 72 | 279.0 | 59.9 | 14.12 | 1.845 |

![Controlled comparisons of aggregate throughput and per-model P95 time to first token][throughput-latency]

**Hold total concurrency constant to evaluate the card.** At 256 / 64, A4 and AB delivered 271.5 and 271.7 tok/s. At 1,024 / 128 they delivered 276.1 and 279.0 tok/s, about 1% apart. The card sustained similar aggregate output in these two workload mixes. Changing the model mix at the same time precludes a claim that enabling sharing makes vLLM faster.

**Hold each target's concurrency constant to evaluate the user experience.** At 1,024 / 128, B's P95 TTFT increased from 46.8 to 59.9 ms when A became busy. A's increased from 54.6 to 73.1 ms. A's P95 TPOT moved only from 14.07 to 14.26 ms. The larger change occurred before the first content arrived. Client timings include the gateway, queuing and engine execution. They cannot attribute the increment to any one component without a distributed trace. The mixed-stream headline of 59.9 ms masks A's tail.

Device observations had two different sampling intervals. The formal window ran from 18:27:52 to 18:32:02 on November 23, Beijing time. Filtering DCGM to the experiment Pod and its single card gave four raw utilization samples (0%, 26%, 25%, 0%). The shortest round took roughly four seconds and could fit entirely between minute samples. Across 250 one-second NVML samples inside the runtime, GPU utilization peaked at 98% and used device memory ranged from 4,659.9 to 6,911.9 MiB. A short peak can fall between DCGM scrapes, so both readings are consistent. Throughput and TTFT were measured by the client. [Light-theme Grafana capture](../../assets/practices/aibrix-modelclaim-l20/grafana-light.png) · [Original DCGM samples](../../assets/practices/aibrix-modelclaim-l20/dcgm.csv) · [One-second NVML samples](../../assets/practices/aibrix-modelclaim-l20/nvml.csv)

![Actual light-theme Grafana panels showing device utilization and framebuffer usage on the shared L20](../../assets/practices/aibrix-modelclaim-l20/grafana-light.png)

The horizontal axis is UTC, eight hours behind Beijing time. The upper panel shows device utilization and the lower one shows used framebuffer memory on the same L20. Both include activity from both engines. Use the benchmark groups and request records above for model-level attribution.


## 4. How much memory can the neighbor actually use?

In a separate memory experiment on one card we captured four states in sequence. Removing B in the final row stopped its engine. In A2 and A4 above, B's process remained resident throughout.

| Snapshot | A KV limit | B KV limit | Physical GPU memory used |
| --- | ---: | ---: | ---: |
| Both awake | 16.20 GiB | 16.20 GiB | 3,752 MiB |
| A asleep, B still serving | 0.33 GiB | 37.63 GiB | 2,528 MiB |
| A awake again | 16.20 GiB | 16.20 GiB | 3,754 MiB |
| B removed, A alone | 38.39 GiB | — | 2,021 MiB |

![Qwen2.5 cache allowance and measured GPU memory before, during and after Qwen3 sleep][memory]

The runtime reported **44.39 GiB** available for allocation. With both engines awake and 6 GiB of non-KV budget each, the remaining cache divided evenly gives `(44.39 - 6 - 6) / 2 = 16.20 GiB` per engine. The default policy preserves the reservation needed for waking. With `noWakeReserveWhileAsleep` enabled, sleeping A still held **782 MiB**. B could receive `44.39 - 6 - 782/1024 ≈ 37.63 GiB` of KV allowance. B gained about 21.43 GiB of potential cache capacity, while physical memory in use on the card actually dropped **1,224 MiB**. The first figure describes how much cache B may grow into. The second measures what this sleep released. [Four-stage snapshot values](../../assets/practices/aibrix-modelclaim-l20/results.json)

A third claim tested the admission boundary. It requested a 96 GiB non-KV footprint plus a 1 GiB cache floor. The controller returned `TooLargeForAnyCard` with a requirement of 97.0 GiB and maximum candidate capacity of 44.4 GiB. A large free-memory reading in `nvidia-smi` cannot override the reservations already represented in the controller's ledger.

### Can B take a turn when A needs almost an entire L20?

A pool Pod requesting a whole GPU means that Kubernetes assigns a device to its container. A utilization reading of 100% describes a busy device during the sample. Whether another engine can load on the same card depends on **AIBrix's memory reservations and the KV pages currently held**. Even when both fit, competition for compute can still make the first token arrive later.

The minimum reservation per model is `maximumFootprint + kvFloor`. The operator sizes the former for peak non-KV use, including weights at the chosen precision, CUDA graphs and workspaces. The latter protects the minimum cache needed for the target context. The controller checks whether the minimum reservations fit together, then checks whether that space is available now. It charges an active engine its declared non-KV footprint plus the larger of its cache floor and already mapped KV. Lowering a ceiling does not evict pages still in use. A placement that fits on paper may have to wait for active requests to finish and release cache. [Controller memory ledger](https://github.com/vllm-project/aibrix/blob/v0.8.0/pkg/controller/modelclaim/ledger.go) · [The two admission checks](https://github.com/vllm-project/aibrix/blob/v0.8.0/pkg/controller/modelclaim/placement.go)

Take the **44.39 GiB** of usable capacity measured on our L20. For a different workload, suppose A needs at least **42 GiB**, B needs **12 GiB**, and A is observed to hold **1 GiB** asleep. These three figures illustrate the policy and are hypothetical.

| State of the single-card pool | Controller decision | Effect on B or the caller |
| --- | --- | --- |
| A is serving and B first requests placement | Keeping both awake would take at least 42 + 12 = 54 GiB, above 44.39 GiB | B waits for placement while A finishes its in-flight requests. Continuous traffic to A can keep B waiting indefinitely. |
| A is asleep with its default wake reservation | A keeps its 42 GiB reservation, leaving at most 2.39 GiB for B | The device may show free memory, but B's 12 GiB request cannot fit in the ledger. |
| A is asleep with `noWakeReserveWhileAsleep` enabled and its remaining footprint measured | A accounts for 1 GiB, leaving 43.39 GiB available for B | B can load and then serve. If B has never loaded, this includes first-load latency. |
| A receives a request while B is serving | A must find 42 GiB to wake, and both active reservations still add up to 54 GiB | The gateway returns 503 and `Retry-After`. With no alternative pool Pod, A can remain in `WaitingForRoom`. The client must retry within its own deadline. |

Alternation has to **fit in both directions**. B can enter if its reservation fits next to A's sleeping footprint. A can return if its reservation fits next to B's sleeping footprint. If B still holds 3 GiB asleep, for example, 3 + 42 = 45 GiB. Even after B sleeps, A cannot wake there. Fully unloading B to release that residual memory, or providing another card with sufficient room for A, would allow A to run. Sleeping weights also move into host memory, so size the Pod's RAM accordingly. [Upstream sleep and wake sequence](https://aibrix.github.io/posts/2026-10-12-modelclaim-gpu-sharing/#waking-through-the-controller)

The pool can use `sleepAfterSeconds` for automatic idle sleep and `sleepToMakeRoomAfterSeconds` for the minimum idle time before a neighbor may be put to sleep to make room. Running or queued requests prevent that handoff. The retry interval suggests when the client should try again. It does not guarantee a turn. The two small Qwen models in the throughput tests needed only 14 GiB in combined minimum reservations. They tested simultaneous service and a wake with room available. The roughly eleven-second client wait does not predict the time for models that must take turns. If both need to answer within a second or two at any time, provide room for their simultaneous peaks or give them separate devices. [Pool policy settings](https://github.com/vllm-project/aibrix/blob/v0.8.0/pkg/controller/modelclaim/pool_policy.go)

### Measured handoff between two real 14B checkpoints

Here A was Qwen3-14B and B was DeepSeek-R1-Distill-Qwen-14B, both BF16. Their checkpoint indexes reported **27.51 GiB each**, or **55.02 GiB** combined. The weights alone exceeded usable device capacity. Each claim declared a 33 GiB non-KV footprint and a 1 GiB KV floor. Both used `--enforce-eager --max-model-len 2048 --max-num-seqs 2`. The pool requested one L20 and 110 GiB of host RAM with a 144 GiB limit for loading and offloading sleeping weights. We measured one full round trip.

| Stage | Qwen3-14B | R1-Distill-Qwen-14B | Device memory used | Request and controller observations |
| --- | --- | --- | ---: | --- |
| A serves, B requests placement | Active | Pending | 29,151 MiB | A answered Paris. B returned 503. The controller reported 10.4 GiB still available for reservations, against B's 34 GiB requirement. |
| A sleeps with its wake reservation intact | Sleeping | Pending | 1,043 MiB | A's sleeping footprint was 950 MiB. Despite ample free physical memory, the next B request also returned 503. |
| Release the wake reservation and load B for the first time | Sleeping | Active | 30,400 MiB | B answered Tokyo. About 85.3 seconds elapsed from recording the policy update to the end of B's first correct response, including initial engine and weight loading. |
| A receives a request while B keeps serving | Sleeping | Active | 30,400 MiB | A returned 503 and its instance reported `WaitingForRoom`. All seven subsequent requests to B succeeded. |
| Stop sending B traffic and restore A | Active | Sleeping | 30,400 MiB | B held 1,062 MiB asleep. A answered Paris again. Its API-server PID and port, the Pod UID and the GPU UUID all matched the initial snapshot. |

![Observed device memory and claim phases as Qwen3-14B and DeepSeek-R1-Distill-Qwen-14B alternate on one L20][switching-14b]

The line shows device memory sampled roughly every second inside the Pod. The bands use independently polled claim phases. At the right edge, memory usage returned to 30,400 MiB, but the model answering had changed from B back to A. The device curve alone cannot identify that handoff. [Device samples](../../assets/practices/aibrix-modelclaim-l20/switch-device.csv) · [State transitions](../../assets/practices/aibrix-modelclaim-l20/switch-states.csv) · [Stage snapshots](../../assets/practices/aibrix-modelclaim-l20/switch-stages.csv) · [Request records](../../assets/practices/aibrix-modelclaim-l20/switch-requests.csv)

To reproduce this trial, create A by itself and check its gateway response before creating B. Set `sleepAfterSeconds: 35` and retain the default wake reservation to observe A asleep with B still Pending. Then use `noWakeReserveWhileAsleep: true`, `sleepAfterSeconds: 240` and `sleepToMakeRoomAfterSeconds: 20`. B can start once A's measured sleeping footprint is accounted for. Trigger a wake request for A while B is serving, keep calling B for about half a minute, then stop traffic to B. The first A call returned a ten-second retry hint. Controller events placed it back in service **86 seconds** after the wake request. From the first A call to the next correct response, the client observed **90.35 seconds**, including intentional traffic to B, idle eligibility, weight transfers and polling. This is the end-to-end duration of one orchestrated handoff.

### Measured boundary: why could a 22B model still not start after Qwen went to sleep?

We replaced B with Mistral-Small-Instruct-2409, a 22B model. Its BF16 weight index reported about **41.44 GiB**. We declared a 43 GiB non-KV footprint and a 1 GiB KV floor, totaling **44 GiB**, and kept the same single-GPU pool specifications and 2,048-token context limit. The 44 GiB figure is the operator's reservation for this configuration. [Mistral model card](https://huggingface.co/mistralai/Mistral-Small-Instruct-2409)

| Action | Observation | Deployment implication |
| --- | --- | --- |
| Put Qwen3-14B to sleep and allow its wake reservation to be released | Device usage fell to 1,043 MiB, of which the sleeping engine retained 950 MiB. Available capacity was 44.3922 − 950 / 1,024 ≈ **43.46 GiB**. The controller reported a 43.5 GiB maximum. Mistral remained Pending and the gateway returned 503. | The shortfall was about 0.54 GiB. Waiting longer for idle time would leave that sleeping process footprint in place. |
| Manually remove the trial Qwen claim and wait for its engine to exit | Mistral was placed in the original Pod. vLLM used 41.45 GiB for weights. With a process budget of roughly 40.84 GiB, kvcached calculated **−0.87 GiB** for KV after weights and activations. Both startup attempts reported `No available memory for the cache blocks`. | After placement, verify whether vLLM can initialize the cache with the selected arguments. |
| Recreate the Mistral claim with just one added argument, `--kv-cache-memory-bytes=1073741824` | Controller events recorded about **53 seconds** from `Activating` to `Activated`. Mistral later slept and retained 726 MiB. A fresh request received 503, then **HTTP 200** with the answer Tokyo on retry. The Active snapshot showed **43,305 MiB** used on the device. | The Qwen and Mistral snapshots identify the same Pod and physical GPU. The explicit 1 GiB value applied at startup. The controller subsequently adjusted the runtime KV limit to about 1.4 GiB. |

The operator explicitly unloaded Qwen to make room for this 22B service. Restoring Qwen would require creating its claim again. The 1 GiB startup setting was verified with one short request. Longer contexts and higher concurrency need their own workload tests. The workstation briefly lost cluster connectivity, so the cold-start interval comes from cluster events. The gateway response was collected after reconnecting. [Both launch configurations, controller events and gateway responses](../../assets/practices/aibrix-modelclaim-l20/switch-edge.json)

## 5. Cold start, sleep and the first successful reply for the two small models

On first pool creation, the node spent **114.13 seconds** pulling the image. Both claims then moved from `Activating` to `Activated` in **61 seconds**, with both models loading concurrently. A pool scaled back from zero can experience a different pull time depending on the node's image cache. These are two intervals observed in Kubernetes events. We did not time a single client request across that cold start.

For sleep testing the pool Pod stayed up, with `sleepAfterSeconds: 60` and `noWakeReserveWhileAsleep: true`. We kept sending traffic to B, allowed A to reach `Sleeping`, then sent A a real question. First access triggered `503` with `Retry-After: 10`. The controller restored the engine and route, and the client retried after the indicated wait. In the initial functional trial the Pod UID, GPU UUID, both engine PIDs and ports all matched before and after wake-up.

| Trial | First → retry HTTP | Time to routable | Time to correct answer |
| --- | ---: | ---: | ---: |
| Functional | 503 → 200 | 3 s | 10.92 s |
| Repeat 1 | 503 → 200 | 2 s | 11.31 s |
| Repeat 2 | 503 → 200 | — | 13.37 s |
| Repeat 3 | 503 → 200 | — | 11.47 s |

All four first attempts returned 503 and all four retries answered correctly. Median client time was **11.39 seconds**, spanning **10.92–13.37 seconds**. The last two trials lacked a distinct Woken timestamp attributable to that trial, hence the blank cells. Four wakes are insufficient to establish a wake P95.

“Routable” measures from the controller's recorded wake request to its `Woken` event, with second-resolution timestamps. Client time runs from the first send inside the Pod to the end of the successful retry, including waiting, inference and orchestration between the two in-Pod calls. The initial trial also clocked 11.64 seconds in the outer harness, including `kubectl exec` invocation overhead. A model can wake in place when capacity is available. If the budget it released has been promised to others, the controller must find room again. All four small-model wakes in the table had room available. [Individual wake trials](../../assets/practices/aibrix-modelclaim-l20/wake.csv)

## 6. Reproduce the experiment and diagnose a 503

The commands assume AIBrix v0.8.0 and Envoy Gateway are installed and the upstream weights are accessible. Use a dedicated namespace. For offline operation, mount both models read-only and point each claim's `artifactURL` at its in-container path. Our preflight used a CPU-only Pod to read each config and the first byte of each weight file, and to reach the gateway through cluster DNS. [Upstream manifests](https://github.com/vllm-project/aibrix/tree/v0.8.0/samples/modelclaim) · [Pinned runtime Dockerfile](https://github.com/vllm-project/aibrix/blob/v0.8.0/build/container/Dockerfile.kvcached-runtime)

<details markdown="1">
<summary>Expand pool and model deployment commands</summary>

```bash
git clone --depth 1 --branch v0.8.0 https://github.com/vllm-project/aibrix.git
cd aibrix
DEMO=$(mktemp -d)
cp samples/modelclaim/{warm-runtime-pool,modelclaims}.yaml "$DEMO/"
cat > "$DEMO/kustomization.yaml" <<'YAML'
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: modelclaim-demo
resources:
  - warm-runtime-pool.yaml
  - modelclaims.yaml
images:
  - name: aibrix/kvcached-runtime
    newTag: "453ab36db68ac859f86ac94e32d0e02cec4c1505"
patches:
  - target:
      kind: Deployment
      name: warm-runtime-pool
    patch: |-
      - op: replace
        path: /spec/template/spec/containers/0/resources
        value:
          requests: {cpu: "4", memory: 28Gi, nvidia.com/gpu: "1"}
          limits: {cpu: "12", memory: 44Gi, nvidia.com/gpu: "1"}
  - target:
      group: model.aibrix.ai
      kind: ModelClaim
    patch: |-
      - op: add
        path: /spec/engineConfig/args/--enforce-eager
        value: ""
      - op: add
        path: /spec/engineConfig/args/--max-num-seqs
        value: "4"
YAML
kubectl create namespace modelclaim-demo
kubectl apply -k "$DEMO"
kubectl -n modelclaim-demo wait --for=jsonpath='{.status.phase}'=Active \
  modelclaim/qwen3-0-6b modelclaim/qwen25-0-5b --timeout=20m

ENVOY=$(kubectl -n envoy-gateway-system get svc \
  -l gateway.envoyproxy.io/owning-gateway-name=aibrix-eg \
  -o jsonpath='{.items[0].metadata.name}')
kubectl -n envoy-gateway-system port-forward "svc/$ENVOY" 18888:80
```

</details>

Download the client in a second terminal and run the Bash example below. It uses the upstream sample's model aliases. Our measured client ran in the cluster. A port-forward is useful for verifying the protocol, but the network latency from a workstation needs its own label. The client retains failures in the denominator and writes the rounds into a new directory. [Standard-library benchmark client](../../assets/practices/aibrix-modelclaim-l20/stream_bench.py)

<details markdown="1">
<summary>Expand the commands for all three rounds</summary>

```bash
MODELS=(--model-a qwen3-0.6b --model-b qwen2.5-0.5b)
URL=http://127.0.0.1:18888/v1/completions
OUT=$(mktemp -d)
for profile in "256 64" "1024 128"; do
  read -r input output <<< "$profile"
  python3 stream_bench.py "$URL" probe "$input" "$output" 0 --per-lane 1 "${MODELS[@]}" > "$OUT/probe-$input.json"
  jq -e 'all(.records[]; .ok)' "$OUT/probe-$input.json" || exit 1
done
for round in 1 2 3; do
  case "$round" in
    1) modes=(A2 AB B2 A4); sizes=(256 1024) ;;
    2) modes=(AB B2 A4 A2); sizes=(1024 256) ;;
    3) modes=(B2 A4 A2 AB); sizes=(256 1024) ;;
  esac
  for input in "${sizes[@]}"; do
    output=64
    if [[ "$input" == 1024 ]]; then output=128; fi
    for mode in "${modes[@]}"; do
      python3 stream_bench.py "$URL" "$mode" "$input" "$output" "$round" "${MODELS[@]}" >> "$OUT/rounds.jsonl"
    done
  done
done
```

</details>

| Observation | How it appeared in the lab | Operator action |
| --- | --- | --- |
| 503, `NoMatchingPods` | The gateway recognized both names while the pool was empty | Check pool replicas, selector and Pod readiness, then the claim's Scheduled condition |
| 503, `Sleeping`, with a retry hint | First access triggered wake-up, followed by `Waking` and `Woken` | Back off within the request deadline and track both first-attempt failures and eventual successes |
| `TooLargeForAnyCard` | Declared minimum requirements exceeded single-card capacity | Profile the non-KV footprint and KV floor under real load, or select a larger pool device |
| Changing the weight URL or requesting two replicas was rejected | Both server-side dry runs failed validation | For v0.8.0, create a new claim when replacing the weights and then move traffic |

With the port-forward still open after the benchmark, keep B active until A sleeps. Then capture the first call to A and follow the retry header. The final step scales the dedicated pool to zero to return the GPU.

<details markdown="1">
<summary>Expand sleep, wake and GPU release commands</summary>

```bash
kubectl -n modelclaim-demo annotate deployment/warm-runtime-pool --overwrite \
  'claim.model.aibrix.ai/pool-policy={"lifecycle":{"sleepAfterSeconds":60,"noWakeReserveWhileAsleep":true}}'
CHAT=http://127.0.0.1:18888/v1/chat/completions
B='{"model":"qwen2.5-0.5b","messages":[{"role":"user","content":"Capital of France?"}],"max_tokens":32,"temperature":0}'
A='{"model":"qwen3-0.6b","messages":[{"role":"user","content":"What is 7 plus 5?"}],"chat_template_kwargs":{"enable_thinking":false},"max_tokens":64,"temperature":0}'

# Keep B active while A idles. Stop after at most 20 polls.
phase=
for ((i=0; i<20; i++)); do
  curl -fsS --max-time 15 -H 'Content-Type: application/json' -d "$B" "$CHAT" >/dev/null || break
  phase=$(kubectl -n modelclaim-demo get modelclaim/qwen3-0-6b -o jsonpath='{.status.phase}')
  [[ "$phase" == Sleeping ]] && break
  sleep 8
done
if [[ "$phase" == Sleeping ]]; then
  tmp=$(mktemp -d)
  http=$(curl -sS --max-time 30 -D "$tmp/headers" -o "$tmp/first.json" -w '%{http_code}' \
    -H 'Content-Type: application/json' -d "$A" "$CHAT")
  delay=$(awk 'tolower($1)=="retry-after:" {gsub(/\r/,"",$2); print $2}' "$tmp/headers")
  printf 'First HTTP %s, Retry-After %s\n' "$http" "$delay"
  if [[ "$http" == 503 && "$delay" =~ ^[0-9]+$ ]] && ((delay <= 60)); then
    sleep "$delay"
    curl -fsS --max-time 30 -H 'Content-Type: application/json' -d "$A" "$CHAT" | jq -r '.choices[0].message.content'
  fi
fi
kubectl -n modelclaim-demo get events --field-selector involvedObject.kind=ModelClaim \
  --sort-by=.lastTimestamp
kubectl -n modelclaim-demo scale deployment/warm-runtime-pool --replicas=0
```

</details>

## 7. Which services should try it first?

- **Internal catalogs with occasional traffic.** Clients can call the two model names independently, and sleeping models can give up cache allowance. Start with retry-tolerant, low-risk aliases. Track per-model P95 TTFT, complete responses, wake frequency and available host memory.
- **Interactive services with tight first-response targets.** The observed retry hint alone consumed ten seconds. A service with a one- or two-second first-response budget should keep its critical model awake and measure tail latency under real neighboring traffic. The pool Pod still holds its GPU while engines sleep. Scale down the pool to return a whole card to Kubernetes.
- **Before extrapolating to larger models.** The throughput matrix covered two small models, short contexts and up to four concurrent requests. The 14B pair completed one round trip under memory pressure. The 22B trial tested whether a sleeping neighbor could block admission. Cross-GPU movement, long contexts, tail latency over repeated handoffs and engine-failure isolation remain open. A larger pilot should measure real peak non-KV usage, host-memory peaks when weights are offloaded, and the busiest tenant's latency budget.

[throughput-latency]: ../../assets/practices/aibrix-modelclaim-l20/throughput-latency-en.png

[memory]: ../../assets/practices/aibrix-modelclaim-l20/memory-en.png

[pod-topology]: ../../assets/practices/aibrix-modelclaim-l20/pod-topology-en.png

[switching-14b]: ../../assets/practices/aibrix-modelclaim-l20/switching-14b-en.png
