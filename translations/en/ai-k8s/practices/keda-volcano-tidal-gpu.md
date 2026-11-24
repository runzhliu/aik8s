---
title: "Lending an inference GPU overnight: measuring the handoff with KEDA, Volcano and DRA"
description: "A two-device Kubernetes lab uses actual claims, a Redis queue and Grafana to follow an inference burst, a batch checkpoint and the return of a borrowed device."
date: 2026-11-23
last_reviewed: 2026-11-23
status: tested
applicable_versions: "Kubernetes v1.37.2, Volcano v1.16.0, KEDA v2.21.1, dra-example-driver v0.5.0"
---

# Lending an inference GPU overnight: how long does it take to get it back?

At ten in the evening a model still receives occasional requests, but one of its two replicas could handle the traffic. Can a batch worker borrow the second GPU? If a burst arrives at midnight, how does the worker give it back?

We ran that sequence on a local Kubernetes cluster. One simulated device stayed with the base inference replica. The other moved from the online service to a batch Job, back to the service, and finally to a new Job that resumed the batch. **All 96 online requests completed**, 55 on the base replica and 41 on the elastic replica. The first Job yielded after item 8. Its replacement completed the other 72, and each of the 80 IDs had an execution count of one. The experiment measures device ownership and handoff timing. Measuring model startup, time to first token and training checkpoint latency requires real GPUs.

## Choose what to hand over

| Goal | Mechanism | Cost when demand returns |
| --- | --- | --- |
| Alternate two models in the memory of a single instance | Coordinate engine sleep and wake inside the instance that owns the GPU, keeping its Pod and allocation alive | Restore weights, rebuild caches and check available device memory |
| Lend a whole exclusive device to another Kubernetes Job | Drain the elastic replica and end the holder Pod so the next Pod can obtain its own ResourceClaim | Wait for the batch worker to yield, start the online replica and warm the model |
| Serve latency-sensitive traffic overnight | Keep enough independent online capacity to serve requests and lend only additional replicas | The base replica absorbs the queue until more capacity becomes ready |

vLLM level 1 sleep offloads weights to host memory and discards the KV cache. Level 2 also discards model parameters. SGLang exposes endpoints to release and resume weights and KV cache with memory saver enabled. Release requires the engine to have no outstanding requests. These operations change the memory footprint of a process. As long as an exclusive device belongs to a live Pod, a second Pod cannot obtain it. We did not call either engine's CUDA APIs in this trial. The previous L20 experiment covers two engines running together or taking turns on a physical GPU. [vLLM Sleep Mode](https://docs.vllm.ai/en/latest/features/sleep_mode/) · [SGLang memory release and resume](https://docs.sglang.io/docs/advanced_features/sglang_for_rl) · [AIBrix on one L20](aibrix-modelclaim-l20.md)

## How the lab works

The local cluster had three nodes running Kubernetes v1.37.2. On one worker, version v0.5.0 of the example DRA driver advertised two exclusive devices. The base replica selected device 0. Both the elastic replica and the batch Job selected device 1, each using a template-generated claim. Spare devices elsewhere could never satisfy their requests. These devices were independent of the simulated B300s advertised by the cluster's device plugin. [Dynamic Resource Allocation](https://kubernetes.io/docs/concepts/scheduling-eviction/dynamic-resource-allocation/) · [Example driver v0.5.0](https://github.com/kubernetes-sigs/dra-example-driver/releases/tag/v0.5.0)

![Experiment design. The base replica keeps device 0. The elastic replica and two batch Jobs take turns on device 1.](../../assets/practices/keda-volcano-tidal-gpu/handoff-design.svg)

*Read the handoffs from left to right. Green indicates online replicas and gray indicates batch Jobs. Labels match the Kubernetes objects in the kit. The two counts show batch progress at each handoff.*

KEDA v2.21.1 managed only the elastic Deployment. A cron trigger requested one replica during the day. At night, Redis list depth could still activate it. The queue and the base replica stayed available throughout. We compressed the day into minutes, set polling to 3 seconds and set the scale-to-zero cooldown to 8 seconds. A separate Volcano v1.16.0 scheduler handled the experiment's scheduler name with the DRA predicate enabled. Each role used a PodGroup with a minimum membership of one. Preemption was disabled for the trial. [KEDA cron scaler](https://keda.sh/docs/2.21/scalers/cron/) · [Redis lists scaler](https://keda.sh/docs/2.21/scalers/redis-lists/) · [Volcano v1.16.0 predicates](https://github.com/volcano-sh/volcano/blob/v1.16.0/pkg/scheduler/plugins/predicates/predicates.go)

A separate lab controller submitted the batch Job after observing the nighttime scale-down. When the elastic replica was requested again and its Pod was waiting, the controller closed batch admission. The batch worker finished its current item, committed the ID and exited. Volcano could then bind the waiting Pod to a compatible device. KEDA has no knowledge of the batch checkpoint.

These are the main fields of the tested ScaledObject. The compressed daytime window ran from 14:24 to 14:30 UTC. Outside it, an arrival in an empty queue could still activate the replica.

```yaml
scaleTargetRef:
  name: elastic
minReplicaCount: 0
maxReplicaCount: 1
pollingInterval: 3
cooldownPeriod: 8
triggers:
  - type: cron
    metadata:
      timezone: Etc/UTC
      start: "24 14 * * *"
      end: "30 14 * * *"
      desiredReplicas: "1"
  - type: redis
    metadata:
      address: tide-redis.keda-tide-lab.svc.cluster.local:6379
      listName: online
      listLength: "2"
      activationListLength: "0"
```

## Control case: pause the worker and keep the Pod

First we stopped the elastic worker from consuming requests, waited for its pause acknowledgement, and left its process and Pod running. We submitted a probe Job asking for device 1. In two observations **9.75 seconds apart**, the probe Pod was Pending with a claim created and no device allocated. The online Pod remained Running with the same claim. This isolates the scheduling implications of an idle process that still owns the device. The pause flag controlled a CPU worker, so it cannot measure how many GiB an inference engine could release.

We then removed the probe and let the cron window expire naturally at 14:30:00 UTC. At 14:30:13 we first observed a target replica count of zero and the original elastic Pod gone. By 14:30:23 the batch Job had obtained device 1 and committed two items. The base Pod kept device 0 throughout.

## Burst case: returning a device to serving

We enqueued 96 unique IDs in one operation. The controller sampled before and after the enqueue, bracketing it between 14:30:24.50 and 14:30:25.68 UTC. The following are observations from one run. Kubernetes resources and Redis were read separately, which limits the ordering precision of individual fields.

| Observation (UTC) | What we saw | Interpretation |
| --- | --- | --- |
| 14:30:26.84 | One elastic replica requested, new Pod Pending, batch Job holding device 1 | KEDA saw demand before serving capacity was available |
| 14:30:29.20 | Worker reported its exit with 8 items committed | Batch admission had closed and progress was saved at an item boundary |
| 14:30:30.62 | Batch Pod succeeded. The waiting online Pod was still Pending but its claim already held device 1 | Allocation preceded container startup. The handoff was visible before the controller deleted the completed Job |
| 14:30:33.16 | The same waiting Pod was Running | No waiter recreation was needed. The successive owners used different claims |
| 14:30:35.67 | Three results from the elastic replica were visible | Approximately 10–11 seconds from enqueue to first observed output, including sampling uncertainty |
| 14:30:59.97 | All 96 IDs had results, 55 from the base and 41 from the elastic replica | Each replica's contribution can be checked independently |
| 14:32:09 | A second batch Job finished the remaining 72 items | All 80 IDs were present, and their individual execution counts were one |

![Light Grafana dashboard showing device ownership, queue depth, completions by online replica and resumed batch progress.](../../assets/practices/keda-volcano-tidal-gpu/handoff-grafana.png)

*The upper-left series come from the roles' device allocations. A value of 1 means that role held device 1. At lower right, batch progress stays at 8 until the second Job takes it to 80. This is an actual Grafana dashboard showing recorded Kubernetes and Redis samples imported into Prometheus at their original timestamps. Between daytime readiness and batch completion we collected 84 samples, with a median interval of 2.04 seconds and a maximum of 2.90 seconds.* [Sample CSV](../../assets/practices/keda-volcano-tidal-gpu/observations.csv) · [Events and verification JSON](../../assets/practices/keda-volcano-tidal-gpu/events.json)

The online worker processed an ID and wrote its result. Production latency also includes stopping new traffic, draining streaming requests, reading weights, warming the model and serving the first real request. The operator logs exposed a separate delay during setup. KEDA initially timed out connecting to the Redis Service before connectivity recovered. Use these timings to understand the order of events. They would underestimate a production first-token budget.

## Reproducing and diagnosing a handoff

[Download the lab kit](../../assets/practices/keda-volcano-tidal-gpu/lab.zip). It contains environment setup, workloads, the script generating a cron window around the current time, the tested ScaledObject and the Grafana dashboard definition. Prepare KEDA, Volcano and the example driver in a dedicated cluster. Follow the kit's instructions to forward the isolated lab Redis and the Kubernetes API locally. The commands explicitly select your test context.

```sh
export LAB_CONTEXT=your-test-context
python tidalinfra.py
python workloads.py
kubectl --context "$LAB_CONTEXT" -n keda-tide-lab rollout status deploy/base
python run.py
kubectl --context "$LAB_CONTEXT" -n keda-tide-lab get scaledobject,hpa,pod,resourceclaim
```

Follow four signals in order. First, if the Redis backlog is growing while desired replicas stay at zero, inspect ScaledObject Ready/Active conditions, Redis connectivity and the external metrics API. Second, if one replica is desired but the Pod is Pending, check its claim selector and the current owner. Third, if it has a device but is unready, inspect kubelet, image pulls and engine startup. Fourth, if it is Ready with no successful response, check routing and application logs. The test declared serving recovered using completed request IDs. Desired replica count alone would have reported success too early.

## Which jobs are worth lending GPUs to?

Start with restartable batch inference such as embedding generation or document labeling. The worker must be able to stop taking work. Use an acknowledged input queue and deduplicate results by business ID. The lab's Redis checkpoints survived Job replacement, but Redis had no persistent volume. The online worker popped its message before writing the result, leaving a loss window if its process died. In production, use acknowledgement and redelivery, and persist device lending state so a restarted controller can reconstruct ownership.

For training, the return deadline depends on the longest step, the time all ranks take to reach a common boundary, checkpoint storage and verified restore. A distributed job also needs a set of devices that can be allocated together. Before expanding a pilot, exercise a worker that refuses to exit, an unreachable queue and a model that misses its cold-start deadline. Measure P95/P99 from request arrival to first token before choosing how many replicas to lend. If the service allows two seconds of extra waiting, while even this lightweight trial needed about ten seconds to observe output, reserve more baseline capacity or route latency-sensitive traffic to replicas that are already warm.
