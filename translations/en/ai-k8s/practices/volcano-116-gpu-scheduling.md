---
title: "Volcano 1.16 GPU scheduling in practice: Why does a job wait, and who gets the next GPU?"
description: "Test NamespaceQueue, fairshare and the unschedulable job cache with 16 simulated B300s. Compare queue status, container start times and scheduler counters."
status: tested
last_reviewed: 2026-11-23
applicable_versions: "Volcano v1.16.0, Fake GPU Operator 0.2.1"
tested_environment: "Kubernetes v1.37.2, 2 workers × 8 simulated B300 GPUs"
---

# Volcano 1.16 GPU scheduling in practice: Why does a job wait, and who gets the next GPU?

A team held two GPUs and had a job waiting for a third. Raising its child queue limit from 2 to 3 let that job start while the original Pod kept running. A second experiment put two teams in line for one GPU. The team that submitted first had just used the device. With `fairshare` off, its older job ran first. With the plugin on, the newcomer got the GPU first. The scheduler log records the comparison between the two teams’ historical usage.

These are separate operational questions. A queue limit determines how much a team may consume. Historical usage can determine which eligible job gets the next opportunity. The third experiment concerns the scheduler itself. When no node matches, how often can it skip the work, and what event makes it try again? Volcano introduced all three features in v1.16.0, released on October 14, 2026. [Official release announcement](https://volcano.sh/blog/volcano-1.16.0-release/)

| Operational question | Feature under test | Decisive observation |
| --- | --- | --- |
| The cluster has spare GPUs. Why must a team's third request wait? | NamespaceQueue | Changing only the child limit raised its allocated count from 2 to 3 |
| Why should a team making its first request queue behind a returning user? | fairshare | The two waiting jobs started in opposite orders in the same single-GPU queue |
| Does the scheduler repeat all its work for a persistently Pending job? | UnschedulableJobCache | The `allocate` skip counter rose, then a label change produced one `UpdateNodeLabel` wakeup |

## Environment and reproduction files

The cluster had one control-plane node and two workers. Fake GPU Operator 0.2.1 registered eight `nvidia.com/gpu` devices per worker with the product label `NVIDIA-B300-SXM6-AC`. BusyBox requested whole devices and ran `sleep`. Kubernetes created the containers and allocated devices. Volcano performed admission, ordering and binding. This setup exercises scheduling policy. GPU throughput, memory utilization, NCCL traffic and scheduling performance at scale require separate tests. The v1.16 announcement lists Kubernetes 1.36 support. This experiment ran on 1.37.2. [Volcano v1.16.0](https://github.com/volcano-sh/volcano/releases/tag/v1.16.0) · [Fake GPU Operator](https://github.com/run-ai/fake-gpu-operator)

Download and extract the [lab manifests and scripts](../../assets/practices/volcano-116-gpu/lab.zip). They include the queue definitions, positive and negative admission examples, three workloads, both fairness rounds and cleanup. Run the commands from the extracted directory with `kubectl`, Helm, Bash and `jq`. The [observations](../../assets/practices/volcano-116-gpu/results.txt) include the admission rejection, cache counters, scheduler comparison and UTC timestamps for all six containers in the fairness test.

Use a dedicated test cluster with an existing `volcano` Helm release at the same version. Check your current kubeconfig context and confirm the two lab namespace names are unused. The starting point here was the chart’s default scheduling policy. The first values file enables `NamespaceQueue`, `UnschedulableJobCache` and per-job debug metrics. The chart configures admission, controller and scheduler, replacing the default `proportion` plugin with hierarchical `capacity`. If you supply your own scheduler configuration, merge the capacity changes into it. Save the starting revision for rollback. [Pinned chart configuration](https://github.com/volcano-sh/volcano/tree/v1.16.0/installer/helm/chart/volcano)

```sh
helm repo add volcano-sh https://volcano-sh.github.io/helm-charts
helm repo update volcano-sh
helm history volcano -n volcano-system
BASE_REV=$(helm history volcano -n volcano-system -o json | jq -r 'last.revision')
helm upgrade volcano volcano-sh/volcano -n volcano-system --version 1.16.0 \
  --reuse-values -f features.yaml --wait
kubectl create namespace v116-team
kubectl create namespace v116-guest
```

## Experiment 1. Who may attach a child queue, and who can use a third GPU?

The platform administrator creates the cluster Queue `v116-pool` with a four-GPU ceiling. Its `allowedNamespaces` contains only `v116-team`. The team creates `training` in its own namespace and sets `parent: cluster/v116-pool`. Both `deserved` and `capability` start at 2. Jobs refer to this child with `queue: namespace/training`. Omitting `namespace/` resolves the bare name against cluster Queues, an easy detail to miss when reviewing manifests. [NamespaceQueue design and reference resolution](https://github.com/volcano-sh/volcano/blob/v1.16.0/docs/design/namespace-queue.md)

```sh
kubectl create -f queues.yaml
kubectl -n v116-team wait --for=condition=Ready namespacequeue/training --timeout=60s
kubectl create --dry-run=server -f guest.yaml
```

The permitted child reported `Authorized=True` and `Ready=True`. The last command is expected to exit nonzero. Submitting the same child under `v116-guest` caused the Volcano admission webhook to return `namespace "v116-guest" is not allowed to use parent Queue "v116-pool"`. This checks permission to attach to a parent. Kubernetes RBAC still governs who may create and edit NamespaceQueues. The lab used an administrator identity throughout.

```sh
kubectl create -f quota-holder.yaml
kubectl -n v116-team wait --for=jsonpath='{.status.state.phase}'=Running vcjob/quota-holder --timeout=90s
kubectl create -f quota-waiter.yaml
kubectl -n v116-team get vcjob,podgroup,pod
kubectl -n v116-team get namespacequeue training -o yaml
```

`quota-holder` requested two GPUs and stayed running. `quota-waiter` requested one and matched the same B300 workers. The child queue’s `status.allocated["nvidia.com/gpu"]` was 2. The second Pod already existed, its PodGroup was `Inqueue`, and its Job was `Pending`. We kept the holder, nodes and `deserved: 2` in place and changed one field.

```sh
kubectl -n v116-team patch namespacequeue training --type=merge \
  -p '{"spec":{"capability":{"nvidia.com/gpu":"3"}}}'
kubectl -n v116-team wait --for=jsonpath='{.status.state.phase}'=Running vcjob/quota-waiter --timeout=60s
```

![Terminal observations of both jobs and the allocated device count before and after the quota change](../../assets/practices/volcano-116-gpu/quota.png)

*The two kubectl samples bracket the change. At three devices allocated, the two-GPU holder and the one-GPU waiter were both Running. The terminal screenshots replay captured output with the workstation title bar cropped.*

Start troubleshooting by resolving the queue reference on the Job. Follow the parent chain and compare ceilings and allocations before examining Pod placement requirements. A node inventory from `kubectl get nodes` gives only the cluster’s capacity. In this experiment the parent had room, so the child could exceed its `deserved: 2` and reach its own `capability`. A higher child limit alone cannot supply a device if the parent or the physical cluster is full.

## Experiment 2. Can usage history change who gets the next GPU?

A separate cluster Queue, `v116-fair`, allowed one GPU. In both rounds, team first held the GPU for 45 seconds. It submitted older, then guest submitted newer a few seconds later. Both waiting jobs requested one GPU of the same model, had equal priority, ran for 18 seconds and reached Pending while the holder was active. In the second round we enabled `fairshare` for this queue. The other scheduling plugins and hierarchical capacity settings stayed the same.

```sh
kubectl create -f fair-queue.yaml
bash fair-round.sh off
helm upgrade volcano volcano-sh/volcano -n volcano-system --version 1.16.0 \
  --reuse-values -f fairshare-values.yaml --wait
bash fair-round.sh on
cat off-timing.tsv on-timing.tsv
```

| Plugin | team/older created → started (UTC) | guest/newer created → started (UTC) | First after release |
| --- | --- | --- | --- |
| Off | 08:08:23 → 08:09:11 | 08:08:27 → 08:09:32 | team/older |
| On | 08:10:13 → 08:11:21 | 08:10:16 → 08:11:00 | guest/newer |

![Observed timestamps for the six Pods with fairshare off and on](../../assets/practices/volcano-116-gpu/fair.png)

*Rows are ordered by container start time. CREATED is the Pod creationTimestamp. STARTED and FINISHED come from the terminated container state. The holder ran for the full 45 seconds in each round.*

The plugin accounts for allocated resources over time per namespace within a queue and decays historical usage. We tracked `nvidia.com/gpu` with a half-life of 240 minutes and placed the plugin after `priority` and before `drf`. Team had already released the GPU when the waiters could start, but its history remained. The `JobOrderFn` log explicitly preferred guest with a comparison of `0.0 < 47158.5`. These are internal accounting units. A sleeping process holding a GPU still accumulates usage. [v1.16 fairshare ordering and accounting implementation](https://github.com/volcano-sh/volcano/blob/v1.16.0/pkg/scheduler/plugins/fairshare/fairshare.go)

For teams identified by namespace and sharing a queue, this addresses the case where a steady stream of short jobs keeps one tenant at the front. We ran one round per condition and matched the observed start order against the plugin’s decision. Production wait-time distributions also depend on arrival rates, job lengths and priorities. Both `enableEnqueueGate` and `persistState` were disabled. If history must survive scheduler restarts, test persistence in a pilot queue before a wider rollout.

## Experiment 3. Can a node label wake a cached job?

This job used the default cluster Queue. It requested one B300 and also required `aik8s.run/cache-probe=ready`, a label initially absent from every node. For reproduction, set `WORKER` to the simulated GPU worker you intend to label and verify that the key is unused. Run the first metrics query after the job has spent several scheduling cycles Pending, then add the label.

```sh
kubectl create -f cache-probe.yaml
METRICS=/api/v1/namespaces/volcano-system/services/volcano-scheduler-service:8080/proxy/metrics
kubectl get --raw "$METRICS" | grep '^volcano_unschedulable_job_cache_' | grep 'job_name="cache-probe-'
kubectl label node "$WORKER" aik8s.run/cache-probe=ready
kubectl -n v116-team wait --for=jsonpath='{.status.state.phase}'=Running vcjob/cache-probe --timeout=90s
kubectl get --raw "$METRICS" | grep '^volcano_unschedulable_job_cache_' | grep 'job_name="cache-probe-'
kubectl -n v116-team wait --for=jsonpath='{.status.state.phase}'=Completed vcjob/cache-probe --timeout=90s
kubectl label node "$WORKER" aik8s.run/cache-probe-
```

![Cache skips before the label change and the wakeup after it](../../assets/practices/volcano-116-gpu/cache.png)

*The screenshot selects the scheduler counters for this job. Both allocate and backfill had recorded 138 skips before the label update. Both read 139 at the next sample and the Job was Running. The raw metric identifies resource="Node" and action="UpdateNodeLabel".*

The condition rejecting the job can remain stable across many scheduling cycles. The cache records that rejection and lets later cycles skip the corresponding stages. A node label update is a retry hint. The scheduler evaluates placement again and binds the Pod when the checks pass. The two stages can skip work in the same cycle, so adding their counts does not give cycles saved or a scheduler CPU reduction. In v1.16 every rejecting plugin on the path must provide a safe hint. Hierarchical `capacity` rejections are outside this optimization. Using a missing node label here kept this case distinct from the quota experiment. [Cache behavior and supported rejection paths](https://volcano.sh/blog/volcano-1.16.0-release/)

For large backlogs of similar Pending jobs, measure whether skips occur, how quickly jobs bind after a relevant change, and what happens to scheduler CPU and wait times for healthy work. Debug metrics carry job and namespace labels, so collect them over a bounded window. This experiment used one blocked job. Queue latency and metric cardinality at scale need a workload with representative arrival rates.

## Cleanup and adoption

The experiments change quota, ordering and retries respectively. On a shared cluster, settle how much each team can acquire, then decide who gets the next device, and finally measure how much repeated work the cache removes. For a shared accelerator pool, the second experiment is particularly worth running with tenants. The two observed start orders give teams a concrete choice about which queues should consider past usage.

Before cleanup, check that the current context is still the test cluster and that the temporary node label has been removed. Delete the lab jobs, then the child and parent queues, and restore the original Helm revision. We compared the restored user values with the original, verified that all three Volcano Deployments were ready and confirmed removal of the lab namespaces and temporary node label.

```sh
bash cleanup.sh
helm rollback volcano "$BASE_REV" -n volcano-system --wait
helm get values volcano -n volcano-system
kubectl -n volcano-system get deploy
kubectl get queue
```
