---
title: "APF Isolation in Practice: Why Zero-Seat Reject Still Lets Requests Through"
description: "Explains APF principles from request classification, concurrent seats, and fair queuing, then uses Kubernetes 1.30.4 four-phase testing, Grafana screenshots, and source code to explain zero-seat rejection and recovery"
status: evolving
last_reviewed: 2026-09-09
---

# APF Isolation in Practice: Why Zero-Seat Reject Still Lets Requests Through

When batch scripts, Operators, or resource inventory programs continuously access the Kubernetes API, the platform needs to be able to limit the execution opportunities of certain request types while preserving access for other callers. Monitoring can tell us that requests have increased; APF provides request classification, execution shares, and bounded queuing.

This case study runs on a cluster with Kubernetes **1.30.4**, using two dedicated ServiceAccounts to read the same ConfigMap, actually verifying "normal → zero-seat Reject → zero-seat Queue → recovery". The experiment only generates a small amount of read-only traffic, with the goal of verifying isolation and recovery behavior, not probing the API Server throughput ceiling.

The most notable result is: **in this version, zero-seat Reject did not block low-concurrency requests; zero-seat Queue did form queuing and rejection.** This article preserves this counterintuitive result and cross-checks it with actual responses, monitoring, and version source code.

## Understanding APF First: How Requests Obtain Execution Opportunities

APF stands for **API Priority and Fairness**. It manages execution opportunities for requests within each kube-apiserver: first identifying which class a request belongs to, then deciding whether to admit, wait, or reject based on the execution budget of that traffic class. It does not increase the actual compute capacity of the API Server; its main role is to make resource contention more controllable during overload. [APF official documentation](https://kubernetes.io/docs/concepts/cluster-administration/flow-control/)

### A Real-Life Example: Don't Let One Agency Fill Up the Service Hall

Assume a service hall has **10 windows**. An ordinary citizen comes to reissue a document, while an agency brings in hundreds of documents at once. If everyone queues in a single line, one agency could make later citizens wait a very long time.

The hall therefore adjusts its rules: first, at the ticket counter, identify the person and business type. Ordinary business nominally gets **8 windows**, batch agency business gets **2 windows**; within batch business, queue positions from different companies are spread out as much as possible, to avoid one company's large volume of documents blocking other companies. Whether idle windows can be temporarily reassigned to a busy class depends on additional allocation rules.

This is a hypothetical scenario used to map to APF concepts; the numbers are not from this experiment's configuration:

| What happens in the service hall | Corresponding APF concept |
| --- | --- |
| At ticket issuance, identify "who is applying and for what" | FlowSchema matches identity and request type |
| Personal business and batch business each have their own set of windows and waiting rules | PriorityLevelConfiguration |
| Both belong to batch business, but distinguish Company A's and Company B's documents | flow, usually distinguished via ByUser and similar methods |
| How many ordinary documents can be processed simultaneously | Concurrent execution budget corresponding to seats |
| How many unprocessed documents the waiting area can hold | Bounded queue |
| Idle windows temporarily support another business class | Seat lending and borrowing |
| When there is no processing capacity, make people wait or ask them to come back later | Queue or Reject |

The "windows" here only analogize execution opportunities; **APF does not actually reserve dedicated CPU or threads for any request class.** Next, following the order of "take a number → allocate a window → wait → process or reject" to look at the configuration makes this experiment easier to understand.

<picture>
  <source media="(max-width: 600px)" srcset="/assets/kubernetes-flow-control/02-apf-request-path-mobile.png">
  <img src="/assets/kubernetes-flow-control/02-apf-request-path.png" alt="APF principle diagram: FlowSchema classification, priority allocation of execution budget, then admit, queue, or reject" width="1200" style="max-width:100%;height:auto">
</picture>

The above diagram is a mechanism illustration. The client results and Grafana screenshots later are the actual experimental data; in particular, the judgment of "whether admission is possible" must also be combined with the specific implementation of the tested version.

### Request Classification: FlowSchema Determines Which Rule Is Hit

FlowSchema examines both the caller identity and request content, for example "which ServiceAccount, for which Namespace's which resource type, performing GET or LIST". When multiple rules match, the FlowSchema with the smaller `matchingPrecedence` value is preferred, and its reference is used to find the PriorityLevelConfiguration. **This number determines classification order, not a preemption score for the request.** FlowSchema and PriorityLevelConfiguration are both native API resources provided by Kubernetes, requiring no additional CRD installation. [FlowSchema v1 definition](https://kubernetes.io/docs/reference/kubernetes-api/flowcontrol/flow-schema-v1/)

Within a classification, APF also distinguishes different **flows**. A flow is identified by "matched FlowSchema + distinguisher value": `ByUser` uses the authenticated username, `ByNamespace` uses the namespace of the request's target resource. Different flows can share the same priority's budget but receive fair treatment opportunities when queuing. When multiple scripts share the same ServiceAccount, `ByUser` does not automatically distinguish them into multiple independent callers. [FlowSchema's distinguisherMethod](https://kubernetes.io/docs/reference/kubernetes-api/flowcontrol/flow-schema-v1/#FlowSchemaSpec)

In this example, `batch-reader` hits a specific rule, and `control-reader` goes through other rules. The response header check later verifies this step, rather than merely checking whether the YAML exists.

Mapping to the hall: first confirm that the agency's documents actually received a "batch business" ticket, then discuss how many windows it should use. If the wrong ticket is issued, even if the batch window rules have been adjusted, it cannot explain the actual waiting situation.

### Execution Budget: Seats, Shares, and QPS Are Three Different Things

**A seat is APF's unit of concurrent work measurement.** Ordinary requests typically occupy one seat; high-cost LIST requests may occupy multiple seats based on estimated work. Therefore, "number of executing requests" and "number of seats in use" may also differ. APF has special handling for WATCH seat occupation, such as an initialization phase; long-connection counts cannot be directly treated as seats occupied long-term. [Seats occupied by requests](https://kubernetes.io/docs/concepts/cluster-administration/flow-control/#seats-occupied-by-a-request)

The `Limited` type of PriorityLevelConfiguration configures the execution budget and excess handling; the `Exempt` type is not subject to this concurrency limit. The following fields only allocate execution opportunities and do not grant permission to access resources:

| Concept or field | Question it answers | How to understand in this example |
| --- | --- | --- |
| `nominalConcurrencyShares` | What relative share this class occupies when allocating | 5 shares convert to 12 nominal seats in the tested environment |
| Nominal seat cap | Based on total capacity and each class's share, how many seats are nominally allocated | Not equal to the 5 written in the field, nor 5 QPS |
| `lendablePercent` | How much of this class's nominal capacity may be lent out | 0 in this example, lending prohibited |
| `borrowingLimitPercent` | The upper limit of additional capacity this class may borrow | 0 in this example, borrowing prohibited |
| Current seat cap | Combined with borrowing adjustments, the capacity used for scheduling at this moment | When troubleshooting, check separately from nominal values |

Nominal capacity is calculated based on each class's share ratio and involves integer rounding; borrowing and lending also affect dynamic allocation. Simply increasing one class's share also affects the proportion other classes can receive. `borrowingLimitPercent` not being set has a different meaning from being explicitly set to 0: the former does not set this borrowing cap, the latter prohibits borrowing. [PriorityLevelConfiguration v1 definition](https://kubernetes.io/docs/reference/kubernetes-api/flowcontrol/priority-level-configuration-v1/)

Back to the hall, the batch business's 2 windows represent the capacity concept of "how many ordinary documents can be processed simultaneously", not "only 2 people per minute". A document taking 1 minute versus 20 minutes to process produces completely different queuing situations. Whether batch windows can receive support when ordinary windows are temporarily idle depends on the borrowing rules.

A hypothetical calculation illustrates its difference from QPS: if each request always occupies 1 seat with an actual occupation time of 50 ms, 5 req/s corresponds to an average seat demand of approximately `5 × 0.05 = 0.25`; if occupation time grows to 5 seconds, the same request rate requires approximately 25 seats. This is a simplified estimate under stable load, not a seat measurement from this experiment, and client-side end-to-end latency cannot be directly substituted. Therefore, when queuing appears, check both whether requests have increased and whether the API Server's subsequent processing has slowed down.

### Fair Queuing: Isolating Classes and Reducing Interference Between Same-Class Callers

Multiple queues can be configured within a limited priority. APF uses **shuffle sharding**: based on the flow identifier, a small set of candidate queues is determined, and the shorter queue among them is selected for enqueueing. This way, a flow that continuously sends a large number of requests cannot easily fill all queues. When dequeuing, a fair scheduling algorithm selects which queue to advance based on estimated work, rather than merging all sources into a single global FIFO. [v1.30.4 queue allocation and distribution implementation](https://github.com/kubernetes/kubernetes/blob/v1.30.4/staging/src/k8s.io/apiserver/pkg/util/flowcontrol/fairqueuing/queueset/queueset.go)

Three parameters control different boundaries: `queues` is the number of queues, `handSize` is the number of candidate queues per flow, and `queueLengthLimit` is the upper limit of waiting length for a single queue. Increasing queues or waiting length changes memory overhead, isolation effects, and waiting experience, **but does not increase execution capacity**. Fairness also does not mean every user gets strictly equal QPS. [QueuingConfiguration definition](https://kubernetes.io/docs/reference/kubernetes-api/flowcontrol/priority-level-configuration-v1/#QueuingConfiguration)

This example deliberately uses `queues: 1`, `handSize: 1`, `queueLengthLimit: 2` to make it easy to observe two waiting positions. **This experiment verifies classification isolation, queuing, and recovery, but does not verify shuffle sharding fairness between multiple flows.**

The corresponding practice in the hall is: spread Company A's and Company B's documents across different waiting lines as much as possible, reducing Company A's interference with Company B when A submits in large batches. But adding more waiting chairs only accommodates more waiters; it does not add processing windows.

### Excess Handling: Reject Means "Don't Wait", Queue Means "Bounded Wait"

`limitResponse.type` determines what happens when a request cannot execute at this moment:

| Mode | When it can be admitted | When it cannot execute immediately |
| --- | --- | --- |
| Reject | Enters execution | Does not queue, returns rejection |
| Queue | Obtains execution opportunity through the queue scheduling mechanism | Waits in a bounded queue; rejected if the queue is full or the wait times out |

Therefore, `Reject` does not mean "all requests matching this rule are rejected". The question in this example should be split into two steps: **first look at why the request is judged admissible, then look at which handling method is used when it cannot be admitted.** This is also why Sections 4 and 5 separately verify the no-queue path and the queuing distribution path. [LimitResponse definition](https://kubernetes.io/docs/reference/kubernetes-api/flowcontrol/priority-level-configuration-v1/#LimitResponse)

Mapping to the hall, Reject is more like "process if there's a window, come back later if not"; Queue is "when there's no window, go to a limited waiting area first". Neither rule cancels the applicant's eligibility. To truly prohibit an account from accessing resources, handle it at the authorization mechanism, such as adjusting RBAC, rather than relying on the queuing mode.

Queues and execution budgets are maintained separately by each API Server. In a multi-replica control plane, the same policy works on each instance, but does not form a cluster-wide shared global queue. Monitoring should retain instance dimensions such as `instance`; one instance congested while another is idle may also be related to uneven request distribution.

This is like two service halls in the same city using the same rules, but each issuing tickets and queuing independently; one being full does not automatically transfer waiting people to the other.

### Connecting the Monitoring Evidence with the Principles

When reading the measurements, verify against the request lifecycle:

1. **Is classification correct**: Does the response header UID correspond to the experimental FlowSchema and priority?
2. **Has the budget changed**: Do the nominal seats, current seat cap, and borrowing settings match expectations?
3. **Where did the request stop**: Do queue counts, distribution counters, and rejection reasons corroborate each other?
4. **What did the caller actually get**: Do the final status codes and per-request latencies match server-side observations?

APF dispatch success only means the request obtained a subsequent processing opportunity, not that the final HTTP status is 200. Waiting histograms, execution counters, and client results describe different stages; the later case study also demonstrates label semantics and misinterpretation caused by histogram interpolation.

## 1. Scenario and Boundaries

APF became stable in Kubernetes 1.29. The 1.30.4 here is the tested version, not a recommendation for new deployments; other versions require re-verification of boundary behavior. For principles and API migration background, see [Kubernetes flow control guide](../cluster/flow-control.md).

| Item | Actual setting |
| --- | --- |
| Target | One API Server backend, Kubernetes 1.30.4 |
| Experimental Namespace | `apf-case`, did not exist before the experiment |
| Request object | `ConfigMap/fixture` created in this example |
| Batch account | `apf-case/batch-reader`, target send rate 5 req/s, maximum in-flight 8 |
| Control account | `apf-case/control-reader`, target send rate 1 req/s |
| Permissions | Both accounts can only GET this ConfigMap |
| APF match scope | Only batch account GET on ConfigMap in the experimental Namespace |
| Phase duration | 90 seconds per phase, approximately 6 minutes total |
| Timeout and retry | Request parameter `timeout=20s`, client read timeout 25 seconds, no automatic retry |
| Observation | Temporary 15-second collection; Grafana uses 15-second query step, rate window 1 minute |

The independent control account accesses the same object but does not match the experimental FlowSchema. The client verifies actual classification via `X-Kubernetes-PF-FlowSchema-UID` and `X-Kubernetes-PF-PriorityLevel-UID` in the response. **A successfully created YAML is not evidence that classification is in effect.**

The experiment did not modify default APF rules or API Server startup parameters. Adding a new positive-share class still changes the total share allocation, so even with a very small match scope, the capacity allocation impact needs to be assessed. The client aborts when the control request fails three consecutive times or exceeds 2 seconds, and restores and cleans up experimental resources.

## 2. Four-Phase Results

The formal phases counted **1800 batch requests and 359 control requests**. One additional control request sent before the first phase began is not counted in the phase table; pre-check requests are also not counted. Requests are classified by start time; requests that complete across phase boundaries are not artificially moved to another phase.

| Phase | Nominal share / Mode | Batch HTTP 200 | Batch HTTP 429 | Batch client P95 | Control success / total | Control client P95 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Normal | 5 / Queue | 450 | 0 | 49.3 ms | 90 / 90 | 46.7 ms |
| Zero-seat Reject | 0 / Reject | 450 | 0 | 62.1 ms | 90 / 90 | 44.6 ms |
| Zero-seat Queue | 0 / Queue | 2 | 448 | 5011.9 ms | 90 / 90 | 73.5 ms |
| Recovery | 5 / Queue | 450 | 0 | 53.0 ms | 89 / 89 | 48.3 ms |

<picture>
  <source media="(max-width: 600px)" srcset="/assets/kubernetes-apf-case/client-outcomes-mobile.png">
  <img src="/assets/kubernetes-apf-case/client-outcomes.png" alt="Four-phase batch request status codes with independent control results, from actual client logs" width="1200" style="max-width:100%;height:auto">
</picture>

The 448 429s in the Queue phase match the API Server counters: **414 `queue-full`, 34 `time-out`**; the queue peak observed by monitoring was **2**. The other 2 requests began waiting in the Queue phase and returned 200 after the execution share was restored.

All control requests in the formal phases succeeded, but the control P95 varied between 44.6–73.5 ms. Small sample sizes, client network, and execution timing can all affect latency, so what this proves here is that "the control account was not blocked by the experiment rules"; it cannot be used to claim zero cluster-wide impact.

## 3. How the configuration matched this single account

The FlowSchema below maps the dedicated account's requests to the `apf-case-batch` priority. `matchingPrecedence: 1000` takes precedence over the general ServiceAccount rule in the tested cluster; other clusters still need to verify existing rules.

```yaml
apiVersion: flowcontrol.apiserver.k8s.io/v1
kind: FlowSchema
metadata:
  name: apf-case-batch
spec:
  matchingPrecedence: 1000
  priorityLevelConfiguration:
    name: apf-case-batch
  distinguisherMethod:
    type: ByUser
  rules:
    - subjects:
        - kind: ServiceAccount
          serviceAccount:
            namespace: apf-case
            name: batch-reader
      resourceRules:
        - verbs: [get]
          apiGroups: [""]
          resources: [configmaps]
          namespaces: [apf-case]
          clusterScope: false
```

A FlowSchema does not grant read permissions. A separate Role constrains read objects via `resourceNames: [fixture]`, and a RoleBinding authorizes the two experiment accounts. All manifests are in the [reproducible experiment directory](https://github.com/runzhliu/aik8s/tree/main/examples/kubernetes-flow-control/apf-case).

The `nominalConcurrencyShares: 5` in the normal phase corresponds to **12 nominal seats** in monitoring for this cluster, not a fixed 5 concurrent requests, nor 5 QPS. The actual share conversion is affected by other priorities and the API Server's total execution capacity.

## 4. Why 0 + Reject did not block requests

The first attempt set the category's nominal share to 0, while also setting `borrowingLimitPercent: 0` and using `limitResponse.type: Reject`. Both the actual configuration and monitoring confirmed the execution limit became 0, but all 450 low-frequency batch requests still returned 200, and the response headers confirmed they did match the experiment priority.

In the Kubernetes 1.30.4 queue implementation, requests without a queue check `canAccommodateSeatsLocked`. When a single request needs more seats than the category limit and no request is currently executing, this function still permits execution. This explains why a request needing 1 seat still passed through when the limit was 0 and the category was idle. See [v1.30.4 queueset.go](https://github.com/kubernetes/kubernetes/blob/v1.30.4/staging/src/k8s.io/apiserver/pkg/util/flowcontrol/fairqueuing/queueset/queueset.go#L745).

This result does not mean the Reject mode is useless. Reject controls how requests that cannot be admitted are handled; this version and the low-concurrency load triggered the boundary path described above. It also demonstrates again: **APF concurrency governance cannot replace RBAC, credential revocation, or other access authorization boundaries.** A "zero-share" manifest alone should not be promised as an absolute block.

## 5. 0 + Queue: queuing, timeout, and recovery

The second configuration still used zero share, but enabled a queue that waits for at most 2 requests:

```yaml
apiVersion: flowcontrol.apiserver.k8s.io/v1
kind: PriorityLevelConfiguration
metadata:
  name: apf-case-batch
spec:
  type: Limited
  limited:
    nominalConcurrencyShares: 0
    lendablePercent: 0
    borrowingLimitPercent: 0
    limitResponse:
      type: Queue
      queuing:
        queues: 1
        handSize: 1
        queueLengthLimit: 2
```

In this version, the queue scheduling loop requires "occupied seats less than the execution limit" before continuing to dispatch. When the limit is 0, requests in the queue cannot obtain an execution opportunity, producing two types of rejection:

- **queue-full**: the queue is already full, and new requests receive 429 quickly.
- **time-out**: requests first enter the queue and receive 429 after exceeding the APF wait deadline.

This is why, even though both are HTTP 429, client-side latency can differ significantly. For requests with a deadline, the tested version caps APF maximum wait at one quarter of the request's time budget, subject to a one-minute upper bound; in this case `timeout=20s` corresponds to roughly 5 seconds of waiting, consistent with the client P95 of about 5.01 seconds. See [v1.30.4 getRequestWaitContext](https://github.com/kubernetes/kubernetes/blob/v1.30.4/staging/src/k8s.io/apiserver/pkg/server/filters/priority-and-fairness.go#L390).

After restoring 5 seats, the two requests still in the queue completed, and all subsequent 450 batch requests succeeded. The queue provides a waiting position; **restoring the execution share is what allowed the backlogged requests to continue.** In production, unlimited waiting cannot be treated as an availability guarantee; bounded timeouts, backoff, and upstream retry budgets are also needed.

## 6. How to read the real Grafana screenshots

The figure below comes from an actual dedicated Grafana dashboard. The time range is fixed to this experiment, and phase markers use the actual policy application return times; no metric curves were redrawn. To avoid leaking environment identifiers, the screenshots use panel titles and legends that do not contain internal addresses.

<picture>
  <source media="(max-width: 600px)" srcset="/assets/kubernetes-apf-case/grafana-case-mobile.png">
  <img src="/assets/kubernetes-apf-case/grafana-case.png" alt="Real Grafana screenshot: experiment priority nominal seats, execution, rejections, queuing, waits, and cluster GET latency" width="1440" style="max-width:100%;height:auto">
</picture>

| Panel | How to interpret it |
| --- | --- |
| Nominal execution seats | Observe 12 → 0 → 12; it is not a per-second request quota |
| Experiment request execution rate | Still executes in the Reject phase; stops in the Queue phase, resumes after recovery |
| Experiment request rejection rate | Distinguish queue-full from time-out; there may be no series when there are no events |
| Experiment request queue count | Reaches 2 in the Queue phase; returns to zero after recovery |
| APF wait P95 | Observe wait cost via the execute label; in this version, true does not equal final execution success, see below |
| Cluster general GET P95 | Serves as background observation, not equal to the independent control account's latency |

The rates and quantiles in the figure use a rolling 1-minute window; curves after a phase switch retain the influence of old requests within the window, so graph edges cannot be treated as the exact moment a policy took effect. Grafana quantiles come from histogram estimation; the client P95 in the results table comes from per-request latency, and the two numbers should not be directly compared or subtracted.

There is also a version-related metric pitfall here: "execution=true" in the screenshot legend corresponds to the `execute="true"` label. The 1.30.4 implementation sets this label via `req != nil`, and requests that time out after queuing without actually entering the execution callback are also recorded as true. Therefore this curve cannot be read as "wait P95 of successfully executed requests," nor can it be used to compute a success rate; actual execution is seen in the dispatched counter, and HTTP results are seen on the client. See [v1.30.4 apf_filter.go](https://github.com/kubernetes/kubernetes/blob/v1.30.4/staging/src/k8s.io/apiserver/pkg/util/flowcontrol/apf_filter.go#L159).

The wait P95 in the screenshot is close to 9.7 seconds, but this also cannot be used to conclude that requests actually waited that long. In this version's wait histogram, after 5 seconds the next bucket boundary is 10 seconds; samples slightly above 5 seconds fall into this wider bucket, and quantile interpolation can deviate noticeably from true latency. For precise analysis, both the bucket distribution and per-request records should be examined. Bucket definitions are in [v1.30.4 metrics.go](https://github.com/kubernetes/kubernetes/blob/v1.30.4/staging/src/k8s.io/apiserver/pkg/util/flowcontrol/metrics/metrics.go#L50).

Both the collection interval and the query step must be confirmed. In this case, it was initially discovered that Grafana was using the original data source's 60-second minimum step, so a separate 15-second data source configuration was created for the case; existing composite dashboards kept their original configuration. Otherwise, even if Prometheus collects every 15 seconds, the page may still only plot sparse points.

## 7. Reproduction, evidence, and cleanup

Run [run_case.py](https://github.com/runzhliu/aik8s/blob/main/examples/kubernetes-flow-control/apf-case/run_case.py) to reproduce the four-phase flow. The script uses an explicit context, refuses to reuse existing experiment object names, and includes control probes, abort conditions, and finally cleanup. Full instructions are in the [README](https://github.com/runzhliu/aik8s/tree/main/examples/kubernetes-flow-control/apf-case).

After this experiment, it was confirmed that the experiment Namespace, ServiceAccount, RBAC, and the two APF objects were cleaned up, the API Server `/readyz` is normal, and the original metric collection was restored to 60 seconds. Monitoring data, screenshots, and client results are retained outside the Pod.

| Material | Purpose |
| --- | --- |
| [results.json](../../assets/kubernetes-apf-case/results.json) | Parameters, phase events, status codes, and client quantiles |
| [requests.csv](../../assets/kubernetes-apf-case/requests.csv) | 2159 formal-phase requests, timestamps converted to relative seconds, no addresses or credentials |
| [metrics.json](../../assets/kubernetes-apf-case/metrics.json) | Sanitized real Prometheus time series, rejection reasons, and queue peaks |
| [Grafana JSON](https://github.com/runzhliu/aik8s/blob/main/examples/kubernetes-flow-control/apf-case/grafana-dashboard.json) | After importing, select your own Prometheus data source |
| [Result chart generation code](https://github.com/runzhliu/aik8s/blob/main/scripts/generate_apf_case_visuals.py) | Generates client result charts from results.json |

## 8. Extending from this case to stability engineering

Control-plane governance on large platforms typically also includes high-cost LIST management, client-side rate limiting and caching, Operator retry budgets, critical controller isolation, and capacity and upgrade validation. For example, Uber's public engineering article describes using APF to manage high-cost API calls and building scale-validation tooling with staged scaling mechanisms. See [Uber Kubernetes migration practice](https://www.uber.com/ca/en/blog/migrating-ubers-compute-platform-to-kubernetes-a-technical-journey/).

This case demonstrates a small-scope, verifiable engineering loop: identify the risk and the caller → configure the isolation boundary → verify actual classification → observe client- and server-side evidence → explain version differences → restore and clean up. It can prove an understanding of how APF works, but it cannot replace production-scale load testing, upgrade drills, or disaster-recovery validation.

## 9. Production configuration recommendations: give batch workloads a limited window, not a closed hall

The zero-share configuration above was used to expose boundary behavior. Production governance usually needs "batch tasks slower, but still able to complete, while critical control requests continue to make progress." In the government-service-hall analogy, this means keeping a limited batch window, controlling the number of people waiting, and having the agency submit materials at a measured pace.

The following are engineering recommendations based on the mechanisms and this case's results. The configuration is a **starting point that must be validated before rollout**; it was not executed in this experiment, and the example values should not be treated as production defaults for all clusters.

### 9.1 First classify by caller and request cost, then consider raising capacity

| Traffic | Recommended approach | Pitfalls to avoid |
| --- | --- | --- |
| Leader Election, node and critical controller traffic | First verify and preserve existing system classification, then check its wait and error budgets | Accidentally covering system traffic with broad rules |
| Release platforms, daily operations tooling | Confirm actual classification by identity; create a dedicated priority only when business need exists | Setting all human operations to Exempt, allowing abnormal scripts to bypass limits |
| Resource inventory, reporting, batch sync | Use a dedicated ServiceAccount and place high-cost LISTs in a non-zero small-share category | Multiple programs sharing a high-privilege account makes attribution difficult and prevents per-flow isolation |
| A single abnormal client | First reduce concurrency or stop the task; adjust authorization when access must be denied | Treating zero share as a permanent blocking mechanism |

Prefer adding clearly named custom FlowSchemas and priorities, narrowing the match scope. Match conditions can start with "one account, one business Namespace, LIST on two resource types," then expand after validation. The isolation granularity of `ByUser` depends on the authenticated identity and does not automatically split by process or Pod; there is also no need to create a set of priority objects per Pod.

The system's built-in APF objects have an automatic maintenance mechanism, so modifying default objects must not be treated as ordinary business configuration; if modification is truly needed, verify whether the object is a forced configuration, the rules of `apf.kubernetes.io/autoupdate-spec`, and upgrade behavior. APF configuration permissions should be managed by the platform; ordinary tenants must not be allowed to route their own traffic into the Exempt category. [Default configuration and maintenance rules](https://kubernetes.io/docs/concepts/cluster-administration/flow-control/#default-configuration)

### 9.2 A starting configuration for one batch LIST

Assume the platform uses `platform-ops/inventory-reader` to inventory Pods and Deployments in `app-prod`. The following only governs its LISTs; other requests continue to be classified by existing FlowSchemas. Both Namespaces and the ServiceAccount are hypothetical names, and authorization must be configured separately through RBAC.

```yaml
apiVersion: flowcontrol.apiserver.k8s.io/v1
kind: PriorityLevelConfiguration
metadata:
  name: platform-batch-read
spec:
  type: Limited
  limited:
    nominalConcurrencyShares: 5
    lendablePercent: 0
    borrowingLimitPercent: 0
    limitResponse:
      type: Queue
      queuing:
        queues: 32
        handSize: 4
        queueLengthLimit: 10
---
apiVersion: flowcontrol.apiserver.k8s.io/v1
kind: FlowSchema
metadata:
  name: platform-inventory-list
spec:
  matchingPrecedence: 1000
  priorityLevelConfiguration:
    name: platform-batch-read
  distinguisherMethod:
    type: ByUser
  rules:
    - subjects:
        - kind: ServiceAccount
          serviceAccount:
            namespace: platform-ops
            name: inventory-reader
      resourceRules:
        - verbs: [list]
          apiGroups: [""]
          resources: [pods]
          namespaces: [app-prod]
          clusterScope: false
        - verbs: [list]
          apiGroups: [apps]
          resources: [deployments]
          namespaces: [app-prod]
          clusterScope: false
```

This template is suitable for starting validation from a controlled batch read entry point. **A LIST across all Namespaces will not automatically be covered by the namespace-scoped rule above just because the account is the same**; it must be designed separately according to the actual URL and request classification. `matchingPrecedence: 1000` is only meaningful after verifying existing match rules; the hit must be validated with response headers from a real account.

| Example parameter | Selection intent | How to calibrate before rollout |
| --- | --- | --- |
| Non-zero share of 5 | Preserve normal execution opportunity | Verify each API Server's actual nominal seats, current limits, and batch task completion time; 5 does not represent a fixed percentage |
| Borrow 0, lend 0 | Limit dynamic borrowing in the first round to observe category capacity | Adjust separately after evaluation; how much borrowing a batch category should allow also requires observing critical categories under contention |
| Queue | Allow short burst waiting | If the business cannot tolerate waiting and the client can handle 429 correctly, Reject can be evaluated |
| 32 queues, 4 candidates | Reserve fair queuing capacity for multiple independent identities sharing this category in the future | Adjust based on flow count, contention patterns, and memory cost; a single account cannot prove multi-flow fairness |
| 10 waits per queue | Set a boundary on waiting backlog | A single instance allows at most about 320 queue wait positions for this category, with no guarantee any one flow can use them all; combine with wait budgets to keep backlog low |

`queueLengthLimit` must not be treated as wait seconds, nor should continuously lengthening queues be used to absorb sustained overload. The precise semantics of seat allocation and queuing fields are in [PriorityLevelConfiguration v1](https://kubernetes.io/docs/reference/kubernetes-api/flowcontrol/priority-level-configuration-v1/).

### 9.3 The client must change too, to avoid traffic growing after rejections

Treat APF as a server-side protection layer, while also limiting concurrency, QPS, and burst in the inventory program. After receiving 429, the client should honor the `Retry-After` given by the server (if present), use backoff with jitter, and set a total retry count or total time budget; it must not retry immediately without bound, nor let multiple SDK layers each retry independently. [Client retry recommendations for the Kubernetes API](https://kubernetes.io/docs/reference/using-api/api-concepts/#watch-cache-initialization)

For programs that repeatedly scan the same set of resources, prioritize evaluating informer/watch caches to reduce periodic full LISTs; when a full read is truly needed, use appropriate pagination and verify the behavior of the resource type, cache path, and target version. Also limit concentrated rebuild traffic after task restarts, so that all instances do not re-LIST simultaneously. **The application side controls submission rate, and APF controls the opportunity to enter execution; both must take effect together.**

### 9.4 Observe by category and instance, then adjust in small steps

First record baselines for normal and business-peak conditions, including critical controller request latency, errors, reconciliation backlog, and batch task completion deadlines. After rollout, observe at least the following sets of evidence simultaneously, rather than only the overall 429 ratio:

| Observation combination | Judgment and handling direction |
| --- | --- |
| Classification response header + FlowSchema status | First rule out unmatched or invalid references; do not mask an ineffective configuration by increasing shares |
| Current seat limit + seat occupancy + queue count | Confirm whether this category is capacity-constrained, or whether a particular API Server has uneven request distribution |
| `queue-full` + `time-out` + client wait time | Distinguish burst backlog from prolonged lack of execution opportunity; reduce load first, then evaluate shares and queues |
| Key controller latency, errors, and reconciliation progress | Verify that protected workloads continue to function; proactive rejection of batch workloads should not alone trigger a site-wide failure determination |
| API Server CPU/memory, etcd, and Webhook latency | When multiple categories slow down simultaneously, check for backend bottlenecks; increasing APF limits may further amplify overload |

For example, the following query retains the API Server instance and rejection reason, making it easier to determine whether only a particular backend is congested. Multi-cluster data sources should also include actual cluster label filters.

```promql
sum by (instance, reason) (
  rate(apiserver_flowcontrol_rejected_requests_total{
    priority_level="platform-batch-read"
  }[5m])
)
```

Alert thresholds should be set based on the latency budget and allowed duration of critical workloads; a predictable 429 in batch categories is not the same severity as critical controllers failing to make progress. Do not directly copy the P95 or rejection ratio from the 90-second phase in this example into production thresholds.

### 9.5 Canary rollout and rollback require a clear sequence

1. **Save the baseline and the previous configuration.** Verify the target version, the matching order of all relevant FlowSchemas, priority shares, and existing request classification; place the configuration under version control.
2. **Narrow the matching scope first.** Create a priority that is not yet referenced and confirm its status and capacity changes, then attach a FlowSchema that matches only dedicated accounts. Even before traffic is attached, adding a non-zero share changes the nominal allocation of other categories and requires observation.
3. **Gradually increase load from a small number of real requests.** Validate response headers and keep an independent control probe that does not match the rule; cover ordinary reads, high-cost reads, bursts, and recovery. Server-side dry-run only verifies that the configuration is acceptable; it cannot prove that scheduling behavior and performance are correct.
4. **Decide whether to continue or roll back based on the business budget.** When critical controller errors or waits exceed the budget, batch tasks persistently fail to complete, or unexpected matching occurs, first slow down or pause the clients generating load, then restore the previous policy and check queue recovery and control plane health.
5. **Clean up objects last.** After confirming that objects are no longer referenced or used, delete the newly created objects and synchronize the GitOps desired configuration. Directly deleting a FlowSchema causes new requests to fall under other rules and may place anomalous traffic back into the shared category; deleting the object itself cannot be treated as a complete rollback.

After upgrading Kubernetes, adjusting the number of API Server replicas, or introducing a new large Operator, revalidate the classification and capacity boundaries. The production goal is to keep critical requests making continuous progress while making the waiting, rejection, and recovery of batch requests explainable; this goal requires configuration, client behavior, and monitoring to be validated together.

Official references: [APF concepts](https://kubernetes.io/docs/concepts/cluster-administration/flow-control/), [PriorityLevelConfiguration v1](https://kubernetes.io/docs/reference/kubernetes-api/flowcontrol/priority-level-configuration-v1/).
