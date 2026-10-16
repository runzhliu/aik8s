---
title: "Kubernetes Flow Control Guide: APF, Workload Admission, and Inference Service Rate Limiting"
description: "Illustrated guide to API Priority and Fairness, client-side rate limiting, event rate limiting, resource quotas, GPU task queues, and model gateway rate limiting, with v1 configuration and observability examples"
status: evolving
last_reviewed: 2026-09-09
---

# Kubernetes Flow Control Guide: APF, Workload Admission, and Inference Service Rate Limiting

A GPU cluster may encounter three types of congestion at the same time: Operators querying resources heavily, slowing down the API Server; training jobs submitted in bursts, competing for limited GPUs; and sudden traffic spikes to model endpoints, causing time to first token (TTFT) to keep increasing. All of these relate to requests exceeding the system's carrying capacity, but they occur at different locations and require different control measures.

Kubernetes already provides mechanisms such as API request classification, fair queuing, concurrency budgets, and resource quotas. Combined with task queues and inference gateways, these can further manage when tasks start and how many user requests a service accepts. This article explains these capabilities along the actual request path and provides configuration and troubleshooting examples.

This article is based on official documentation and API definitions; the figures are architectural illustrations and hypothetical calculation examples. The examples do not represent flow-control load tests that have already been executed on a production cluster.

If you want to validate behavior with real configuration and monitoring, continue reading [APF Isolation Real-World Test](../practices/apf-isolation-case.md): a four-phase experiment, Grafana screenshots, and a source-code explanation of why zero-seat Reject still passes requests in Kubernetes 1.30.4.

## 1. First Identify What Needs Protection

<picture>
  <source media="(max-width: 600px)" srcset="/assets/kubernetes-flow-control/01-three-layers-mobile.png">
  <img src="/assets/kubernetes-flow-control/01-three-layers.png" alt="Three-layer governance path for API requests, GPU tasks, and model requests" width="1200" style="max-width:100%;height:auto">
</picture>

When the training platform creates a Job, it calls the API Server; training computation after the task starts does not pass through APF; user access to an already-started model service does not automatically receive business-level rate limiting just because the API Server has flow control configured.

| Control Target | Primary Mechanism | Control Unit | Typical Outcome |
| --- | --- | --- | --- |
| Work concurrently handled by the API Server | APF | Concurrency seats, queued requests | Classified, queued, executed, or rejected |
| Rate at which clients issue API requests | client-go RateLimiter | QPS, Burst | Client waits before sending |
| Event write storms | EventRateLimit | Event request rate | Excess event writes are rejected |
| Resources consumed by a Namespace | ResourceQuota, LimitRange | CPU, memory, GPU, object count | Excess or non-compliant requests are rejected |
| When tasks acquire resources | Kueue, Volcano Queue | Workloads, resource quotas | Queued, admitted, shared, or preempted |
| Requests accepted by model services | Gateway and application/engine controls | Rate, tokens, concurrency, wait time | Accepted, queued, degraded, or rejected |

Native `NetworkPolicy` controls allow/deny relationships for network connections and has no generic HTTP QPS or token rate-limiting fields. Network bandwidth control also depends on CNI or node capabilities; NetworkPolicy cannot replace application-level rate limiting. See [NetworkPolicy](https://kubernetes.io/docs/concepts/services-networking/network-policies/).

## 2. Capabilities of Newer Kubernetes Versions and Migration Boundaries

As of the time of this review, the latest stable version listed on the official release page is **1.37.0**. However, APF has been **stable since 1.29**, and upgrading to the latest version is not required to use it. See [Release Information](https://kubernetes.io/releases/) and [APF Feature Status](https://kubernetes.io/docs/concepts/cluster-administration/flow-control/).

| Capability or API | Status | Practical Impact |
| --- | --- | --- |
| APF and `flowcontrol.apiserver.k8s.io/v1` | Stable since 1.29; APF enabled by default | New configurations use v1, but actual API Server settings still need to be verified |
| APF `v1beta3` | No longer served since 1.32 | Old YAML, clients, and Helm templates need migration |
| `nominalConcurrencyShares: 0` | In v1, an explicit 0 is not defaulted to 30 | 0 cannot be treated as "use the default value" |
| EventRateLimit | Still marked Alpha, disabled by default | Event storms will not be automatically limited after upgrade |
| Kueue, Volcano, Gateway rate limiting | Independent projects or implementation-specific capabilities | Require separate installation, configuration, and version verification |

Older tutorials may show `assuredConcurrencyShares` or `v1beta3` and should be migrated according to the target version. See [API Migration Guide](https://kubernetes.io/docs/reference/using-api/deprecation-guide/) for specific requirements; see [EventRateLimit](https://kubernetes.io/docs/reference/access-authn-authz/admission-controllers/#eventratelimit) for event rate limiting status.

## 3. How APF Protects the API Server

### 3.1 Classify First, Then Allocate Execution Opportunities

A single API Server concurrency limit can cap the amount of admitted work, but it cannot adequately distinguish critical controllers from bulk query scripts. APF adds classification and isolation, allocating execution capacity to different categories and then fairly handling different sources within each category.

The default APF configuration already assigns appropriate classifications to traffic such as Leader Election and built-in controllers. A common use of custom rules is to place bulk reads, resource inventory scans, or abnormal clients into a controlled share, reducing the impact of them continuously occupying execution opportunities. See [APF Concepts](https://kubernetes.io/docs/concepts/cluster-administration/flow-control/).

<picture>
  <source media="(max-width: 600px)" srcset="/assets/kubernetes-flow-control/02-apf-request-path-mobile.png">
  <img src="/assets/kubernetes-flow-control/02-apf-request-path.png" alt="Relationship between FlowSchema, concurrency budget, and execution rejection in APF" width="1200" style="max-width:100%;height:auto">
</picture>

### 3.2 FlowSchema: Which Requests Belong to the Same Category

`FlowSchema` matches requests by user, group, ServiceAccount, as well as resource, operation, and target Namespace, and points to an `PriorityLevelConfiguration`.

- `matchingPrecedence` determines matching order; the smaller the value, the earlier the match. It is not a GPU task priority and does not directly dictate request execution speed.
- `distinguisherMethod` determines how flows are distinguished within a category. `ByUser` distinguishes by request identity; `ByNamespace` distinguishes by the Namespace of the request's target resource, and cannot be interpreted as the Namespace of the client Pod.

When multiple scripts share the same ServiceAccount, `ByUser` can no longer distinguish them as different users. Programs requiring independent governance should use identifiable identities. Field definitions are in [FlowSchema v1](https://kubernetes.io/docs/reference/kubernetes-api/flowcontrol/flow-schema-v1/).

### 3.3 PriorityLevelConfiguration: How Much Capacity to Allocate

For the `Limited` type, `nominalConcurrencyShares` represents the **nominal concurrency share**, not an absolute seat count, and not requests per second. A category's nominal capacity is related to the ratio of its share to the total share; actual operation is also affected by total capacity, rounding, and borrowing/lending constraints. Adding a new category with a positive share can also change the capacity allocation of existing categories.

| Parameter | Meaning |
| --- | --- |
| `nominalConcurrencyShares` | Nominal share used to allocate concurrency capacity |
| `lendablePercent` | Maximum proportion of nominal capacity that can be lent out |
| `borrowingLimitPercent` | Upper limit proportion of capacity that can be borrowed |
| `limitResponse.type` | Uses Queue or Reject when capacity is insufficient |
| `queues`, `handSize`, `queueLengthLimit` | Tune fair queuing, flow isolation, and queue boundaries |

Field definitions and legal ranges are in [PriorityLevelConfiguration v1](https://kubernetes.io/docs/reference/kubernetes-api/flowcontrol/priority-level-configuration-v1/). APF performs flow control on each API Server instance; nominal shares cannot be treated as an exact QPS quota shared across the entire HA cluster.

### 3.4 Seats, WATCH, and Bounded Queuing

Ordinary requests are typically understood as occupying one seat; LIST requests returning many objects may occupy multiple seats. Reading a single object versus scanning many objects in full can have different control-plane costs even at the same QPS.

WATCH cannot simply be understood as "one seat held for the entire connection duration." APF handles its establishment and possible initial event phase, and accounts for related notification overhead. Certain long-running requests such as `exec` and log following are not subject to this APF filter. See [APF Seats and WATCH Explanation](https://kubernetes.io/docs/concepts/cluster-administration/flow-control/#seats-occupied-by-a-request).

APF uses mechanisms such as flow partitioning and Shuffle Sharding to reduce the interference of a high-traffic source on other flows. Bounded queues can absorb short bursts, but sustained overload still results in waiting, timeouts, and rejections. It does not replace etcd capacity optimization, slow Webhook fixes, or preempt running GPU tasks.

## 4. A Well-Scoped APF Configuration

The following places GET/LIST requests from the dedicated ServiceAccount `apf-demo/batch-reader` for Pods in `apf-demo` into a separate category. The Namespace, ServiceAccount, and read permissions must already exist; **FlowSchema does not grant RBAC permissions.**

```yaml
apiVersion: flowcontrol.apiserver.k8s.io/v1
kind: PriorityLevelConfiguration
metadata:
  name: example-batch-reader
spec:
  type: Limited
  limited:
    nominalConcurrencyShares: 5
    lendablePercent: 0
    borrowingLimitPercent: 0
    limitResponse:
      type: Queue
      queuing:
        queues: 64
        handSize: 8
        queueLengthLimit: 20
---
apiVersion: flowcontrol.apiserver.k8s.io/v1
kind: FlowSchema
metadata:
  name: example-batch-reader
spec:
  matchingPrecedence: 1000
  priorityLevelConfiguration:
    name: example-batch-reader
  distinguisherMethod:
    type: ByUser
  rules:
    - subjects:
        - kind: ServiceAccount
          serviceAccount:
            namespace: apf-demo
            name: batch-reader
      resourceRules:
        - verbs: ["get", "list"]
          apiGroups: [""]
          resources: ["pods"]
          namespaces: ["apf-demo"]
          clusterScope: false
```

`matchingPrecedence: 1000` should be compared with existing rules to confirm that no earlier rule intercepts the request. 5 is a share, not 5 QPS or a fixed concurrency of 5. This example disables borrowing/lending to make the boundaries easier to explain; the queue parameters are also teaching examples only and cannot be used to infer throughput or maximum wait time.

These rules do not match LIST across all Namespaces, WATCH, or other resources, and use a separate custom object, so there is no need to directly modify the system default classifications. The full manifest is in [apf-batch-reader.yaml](https://github.com/runzhliu/aik8s/blob/main/examples/kubernetes-flow-control/apf-batch-reader.yaml).

You can first inspect the actual cluster configuration:

```bash
kubectl api-resources --api-group=flowcontrol.apiserver.k8s.io
kubectl get flowschemas
kubectl get prioritylevelconfigurations
```

Server-side validation should explicitly target the intended context:

```bash
kubectl --context <target-context> apply --dry-run=server \
  -f examples/kubernetes-flow-control/apf-batch-reader.yaml
```

dry-run can surface API and admission validation issues, but it does not make the policy take effect, nor does it prove that actual request classification is correct. After enabling in production, you can use the `X-Kubernetes-PF-FlowSchema-UID` and `X-Kubernetes-PF-PriorityLevel-UID` fields in responses (provided intermediate proxies preserve these headers) along with APF metrics to identify matched objects. See [APF Observability](https://kubernetes.io/docs/concepts/cluster-administration/flow-control/#observability).

Default APF objects may be automatically maintained by the API Server; before modifying them, you should understand the auto-update annotations and forced configuration rules. Webhooks that call the API Server again while processing requests can create recursive waits or priority inversion, which requires separate dependency analysis; do not compress all controllers into the lowest share.

## 5. Client-Side Rate Limiting: Reducing Request Pressure at the Source

client-go provides QPS, Burst, and custom RateLimiter. The default constants in the official source code are QPS=5, Burst=10, but actual components may override the configuration, so you cannot infer the limits of all clients from these defaults. See [client-go REST Configuration](https://github.com/kubernetes/client-go/blob/master/rest/config.go).

```go
// cfg 已由 kubeconfig 或 InClusterConfig 构造。
// 数值仅作说明，不是所有 Operator 的推荐配置。
cfg.QPS = 10
cfg.Burst = 20
```

A custom RateLimiter may override the effect of QPS/Burst. When multiple replicas each use a local rate limiter, the aggregate request volume also increases; a single-client threshold is not equal to the cluster-wide threshold.

Controllers/Operators can reduce pressure through Informer/Lister caches, reducing full LIST operations, narrowing query scopes, controlling work-queue concurrency, and bounded backoff. Client retries should distinguish error sources; not all 429s should be retried immediately, or request amplification will result.

## 6. What EventRateLimit and Resource Quotas Each Control

### 6.1 EventRateLimit: Limiting Event Writes

When abnormal components continuously create or update Events, event-specific rate limiting can be considered. EventRateLimit supports buckets by Server, Namespace, User, or SourceAndObject, and requires configuring the API Server's admission plugin and configuration file. It is still Alpha and disabled by default, and managed clusters may not expose the relevant configuration. See [EventRateLimit](https://kubernetes.io/docs/reference/access-authn-authz/admission-controllers/#eventratelimit).

Limiting event writes also means some Events may be missing. Recovery status should be assessed in combination with component logs, metrics, and the root cause of the anomaly; do not conclude that the system has recovered simply because Events have decreased.

### 6.2 ResourceQuota: Limiting Total Resources

Namespaces using `nvidia.com/gpu` extended resources can set GPU and object count limits:

```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: example-team-budget
  namespace: apf-demo
spec:
  hard:
    requests.nvidia.com/gpu: "16"
    count/pods: "100"
    count/jobs.batch: "50"
```

Quotas are not the number of creations allowed per second, nor do they guarantee that the cluster has corresponding idle GPUs. Excess creations are typically rejected rather than automatically queued; after a Job is allowed to be created, its child Pods may still fail to be created due to insufficient Pod quota. See [ResourceQuota](https://kubernetes.io/docs/concepts/policy/resource-quotas/).

LimitRange can constrain the default, minimum, and maximum resource requirements of individual objects or containers. ValidatingAdmissionPolicy can check fields, labels, and specs, but cannot directly serve as a request rate limiter that depends on global counters. See [LimitRange](https://kubernetes.io/docs/concepts/policy/limit-range/) and [ValidatingAdmissionPolicy](https://kubernetes.io/docs/reference/access-authn-authz/validating-admission-policy/).

## 7. GPU Task Queuing: Kueue and Volcano

"Queue now if no GPUs are available, allow borrowing when idle, and reclaim resources by policy when important tasks arrive" is workload admission and scheduling governance.

Kueue manages quotas and admission through objects such as LocalQueue and ClusterQueue, combined with corresponding workload integrations, topology configurations, and AdmissionChecks, to decide whether a task can start. Volcano Queue, combined with its scheduling system, provides resource queues and corresponding sharing and reclamation policies. See [Kueue Admission](https://kueue.sigs.k8s.io/docs/concepts/admission/) and [Volcano Queue](https://volcano.sh/docs/concepts/queue/).

| Symptom | Check First |
| --- | --- |
| API calls for creating and querying Jobs slow down the control plane | APF, client-side rate limiting, and Controller behavior |
| Many tasks waiting for GPUs, unfair allocation between teams | Queues, quotas, priorities, and borrowing policies |
| Quota is sufficient, but multi-GPU tasks cannot be placed | Device fragmentation, topology, Gang/TAS, and actual node resources |
| Urgent tasks need GPUs occupied by existing tasks | Queue/scheduler preemption and task recovery policies |

API request fairness and GPU allocation fairness are two separate mechanisms. The same workload can first successfully call the API, then wait for queue admission, and finally wait for node devices to meet conditions. Each layer should provide independent status and wait-time metrics. For more object relationships, see [Queues, Fair Sharing, and Multi-Tenancy](../queue-multitenancy.md) and [GPU Scheduling](../gpu-scheduling.md).

## 8. Inference Rate Limiting: Beyond RPS, Also Consider Concurrency and Tokens

### 8.1 Identical Request Rates Do Not Equal Identical Backend Pressure

Short answers and long document generation occupy engine time differently. Under the premise that steady state is reachable and the statistical scope is consistent, `平均在途请求 ≈ 实际接纳速率 × 平均耗时` can be used to understand concurrency. If traffic persistently exceeds processing capacity, queues grow continuously, and the steady-state assumption no longer holds.

<picture>
  <source media="(max-width: 600px)" srcset="/assets/kubernetes-flow-control/03-rate-and-concurrency-mobile.png">
  <img src="/assets/kubernetes-flow-control/03-rate-and-concurrency.png" alt="Relationship between average latency and in-flight concurrency at identical request rates; numbers are hypothetical examples" width="1200" style="max-width:100%;height:auto">
</picture>

At an average admission rate of 20 req/s with 0.2-second latency, there are approximately 4 requests in flight; with 10-second latency, there are approximately 200. This example illustrates why long generations and streaming requests need concurrency control; it is not a measured model throughput result.

### 8.2 Gateway and Engine Jointly Control the Admission Boundary

Implementations such as Envoy Gateway provide local and global rate limiting. The scope of local counters is determined by the proxy configuration and cannot be directly treated as the total service-wide quota under multiple replicas; global rate limiting typically requires a shared rate-limiting service and state backend. `BackendTrafficPolicy` is an extension resource of a specific implementation, not a core API natively supported by all Gateways. See [Local Rate Limiting](https://gateway.envoyproxy.io/docs/tasks/traffic/local-rate-limit/) and [Global Rate Limiting](https://gateway.envoyproxy.io/docs/tasks/traffic/global-rate-limit/).

| Constraint | Purpose |
| --- | --- |
| Tenant/API Key request rate | Prevent a single caller from continuously occupying the entry point |
| Input tokens, maximum output tokens | Bound the workload of a single request |
| Running requests/active streams | Control requests that occupy the backend for a long time |
| Waiting requests, maximum wait time | Avoid unbounded backlog and stale work |
| Model or tenant token budget | Make quotas closer to inference cost |
| Timeout, cancellation, and retry budget | Stop work that has lost its consumer, limit retry amplification |

Token quotas should clearly specify whether they account for estimated input, reserved maximum output, or actual post-generation settlement, because the final output length is unknown before the request. Streaming retries must also handle partial results already returned to the user; budgets at the entry point, client, and engine must be coordinated.

APF does not automatically adjust quotas based on model tokens, and Kubernetes Service has no general-purpose token rate-limiting capability. Prefix cache hits also change the actual compute cost of same-length requests; see [KV Cache Overview](../inference/kv-cache-overview.md) and [AI Gateway and Intelligent Routing](../inference/gateway-routing.md).

## 9. Observability Metrics and Troubleshooting Paths

### 9.1 Is APF Actually Queueing or Rejecting

In addition to API Server CPU, also check rejections, queueing, and seat usage. Metrics are based on target version `/metrics`; see [APF Metrics](https://kubernetes.io/docs/concepts/cluster-administration/flow-control/#metrics).

| Metric | Purpose |
| --- | --- |
| `apiserver_flowcontrol_rejected_requests_total` | Locate rejections by FlowSchema, priority level, and reason |
| `apiserver_flowcontrol_current_inqueue_requests` | Current number of queued requests |
| `apiserver_flowcontrol_request_wait_duration_seconds` | Wait time added by APF |
| `apiserver_flowcontrol_priority_level_seat_utilization` | Priority level seat usage |

Aggregate rejection rate by source and reason:

```promql
sum by (flow_schema, priority_level, reason) (
  rate(apiserver_flowcontrol_rejected_requests_total[5m])
)
```

For classic Histogram, the P95 of queue wait time can be calculated:

```promql
histogram_quantile(
  0.95,
  sum by (le, priority_level) (
    rate(apiserver_flowcontrol_request_wait_duration_seconds_bucket[5m])
  )
)
```

The query assumes the collection targets do not have duplicate counting. Multi-cluster Prometheus should add cluster label filtering or grouping; percentiles may be unstable under low traffic. Queueing is only part of end-to-end latency; it should be combined with execution time, Webhook, and etcd metrics.

### 9.2 First Identify Which Layer the Error Comes From

| Symptom | Priority Check | Common Misjudgment |
| --- | --- | --- |
| API 429, APF rejection count grows in sync | Priority level share, queues, and callers | Only increasing client retries |
| API slow, but APF queueing is not obvious | etcd, Webhook, execution cost, and network | Assuming APF rate limiting in all cases |
| Events decrease or writes fail | Event plugin, writers, and aggregation behavior | Treating event reduction as fault recovery |
| Creating Pod reports exceeded quota | ResourceQuota and current usage | Adjusting APF expecting to obtain GPU |
| Workload not admitted or Pod Pending | Queues, quotas, devices, and topology | Only checking API QPS |
| Model API 429 or long waits | Gateway, engine queues, concurrency, and tokens | Modifying API Server concurrency limits |

The same HTTP 429 can be returned by different components. The source should be confirmed by combining the actual request address, response headers, logs, and metrics before adjusting the corresponding layer's policy.

## 10. GPU Platform Deployment Recommendations and Material Notes

Governance responsibility can be divided into three parts:

1. **Control plane**: Preserve protection for critical system traffic, use dedicated identities for batch programs; configure APF based on real request cost, and constrain query and retry behavior.
2. **Resource plane**: Use Namespace quotas to express hard boundaries, use workload queues to express waiting, borrowing, and sharing; also check multi-card topology and actual capacity.
3. **Service entry point**: Gateway and engine jointly manage rate, tokens, active requests, wait time, and cancellation propagation.

Thresholds should be adjusted based on actual load and latency targets. Increasing queues only delays rejection temporarily; raising concurrency may also amplify etcd, Webhook, or GPU pressure. Configuration needs to clearly specify when requests are admitted, how long they may wait at most, who returns failure, and whether retries create more work.

This document is accompanied by [APF Examples and Notes](https://github.com/runzhliu/aik8s/tree/main/examples/kubernetes-flow-control) and [Diagram Generation Code](https://github.com/runzhliu/aik8s/blob/main/scripts/generate_kubernetes_flow_control_visuals.py). Static checks cannot replace server-side validation on the target cluster, rule-matching confirmation, and performance observation. This document has not applied any policies to running clusters, nor has it modified existing business traffic.
