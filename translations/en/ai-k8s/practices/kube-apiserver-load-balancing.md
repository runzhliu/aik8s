---
title: "Kube-apiserver Load Balancing in Practice: HTTP/2, TLS Termination, and L4/L7 Selection"
description: "Starting from connection reuse, TLS identity boundaries, rebalancing during scale changes, and policy selection, compare L4 and L7 load balancing approaches for kube-apiserver along with production validation methods"
status: stable
last_reviewed: 2026-09-18
---

# Kube-apiserver Load Balancing in Practice: HTTP/2, TLS Termination, and L4/L7 Selection

If you put a load balancer in front of three kube-apiservers, is the control plane highly available? In a small cluster, this structure is usually sufficient; but in clusters with many requests, many Watches, and frequent upgrades, a common symptom is that one of the three API Servers has very high CPU while another receives only sporadic traffic, and a recently recovered instance may go a long time without receiving any requests.

The root cause is that **the balancing unit does not match the request unit**. An L4 load balancer selects a backend when the TCP connection is established; HTTP/2, in turn, allows a large number of independent requests to reuse the same connection. As long as the connection stays alive, subsequent requests continue to flow to the original API Server. Rolling upgrades, failure recovery, and controller batch reconnects change where connections land, and the skew is then pinned in place by long-lived connections.

My selection principles are:

1. For ordinary clusters, start with **L4 TCP + TLS Passthrough**, leaving authentication, authorization, and auditing entirely to kube-apiserver;
2. When long-connection skew has already appeared, first fix readiness, graceful shutdown, and connection rotation, then evaluate whether L7 is needed;
3. Only introduce a dedicated Kubernetes API Gateway when there is a clear need for request-level balancing, per-user or per-resource routing, ingress rate limiting, or multi-cluster certificate governance;
4. An L7 gateway must handle more complete protocol and identity semantics than a normal Ingress. After TLS termination, it enters the identity and audit boundary of the control plane, and Watch, exec, attach, port-forward, and write-request failure semantics must be validated separately.

## 1. Why HTTP/2 Makes Requests "Stick" to One API Server

The [HTTP/2 specification](https://www.rfc-editor.org/rfc/rfc9113) places each request/response in an independent Stream, and a single TCP connection can carry multiple Streams concurrently. This reduces TCP and TLS handshakes and avoids re-establishing connections for every request—a legitimate performance optimization.

The problem appears at the observation granularity of an L4 LB:

```text
客户端发起 TCP/TLS 连接
        ↓
L4 LB 选择 API Server 1
        ↓
HTTP/2 Stream 1、2、3……都留在这条连接上
        ↓
L4 LB 看不到每个 Stream，也不能把已有 Stream 移到 API Server 2
```

<img src="/assets/practices/kube-apiserver-load-balancing/connection-vs-request-balancing.png" alt="Difference between L4 connection-level balancing and L7 request-level balancing" width="1200">

There are three points that are easy to misjudge:

- **Adding another L4 LB does not migrate existing connections.** A new entry point can only affect subsequent connection establishments; old connections remain bound to their original backends.
- **DNS round-robin is not request balancing either.** Clients may cache resolution results and reuse already-established connections for a long time.
- **Equal request counts do not mean equal load.** A large LIST, a slow Watch consumer, and an ordinary GET differ greatly in CPU, memory, and bytes returned.

Alibaba's 10,000-node practice documented the phenomenon of traffic concentrating on a single instance after API Server upgrades, and noted that simply adding more LBs cannot solve the problem—the reason being that clients reuse TLS connections as much as possible; their improvements involved server-side protection, client reconnection, and a scale-first-then-shrink release strategy. [Alibaba 10,000-node control plane practice](https://developer.aliyun.com/article/720966)

## 2. The Real Difference Between L4 and L7

"L4 is faster, L7 has more features" only scratches the surface. For the Kubernetes API, the real difference is what the load balancer can see, and therefore what responsibility it must bear.

| Dimension | L4 TCP + TLS Passthrough | L7 TLS Terminate + Re-encrypt |
| --- | --- | --- |
| Balancing unit | TCP connection | HTTP request; a long Watch remains a single long-lived request once established |
| Visible information | Source/destination address, port, connection state | method, path, verb, resource, user, etc., depending on implementation |
| Client identity | Original certificate or Token passed directly to API Server | Gateway authenticates first; upstream must forward the Token or use controlled Impersonation |
| TLS | End-to-end encryption from client to API Server | Client-to-gateway on one segment; gateway re-establishes mTLS to API Server |
| Health check | Commonly TCP/TLS liveness; authenticated `/readyz` can be added | Can do application-level traffic draining based on `/readyz` |
| Routing and rate limiting | Cannot distinguish by Kubernetes request attributes | Can govern by user, verb, resource, namespace, etc. |
| Watch and upgrade connections | Connection goes directly from client to API Server | Gateway must correctly proxy long-lived streams and handle upstream/downstream connection lifecycles |
| exec/attach/port-forward | TCP passthrough is usually simplest | Must support Upgrade, WebSocket/SPDY, or connection hijacking semantics |
| Failure surface | Small, easy to bypass | Gateway, identity propagation, connection pools, and rules all become critical path |

If a product is configured for TLS Passthrough, even if the product name says "L7," it can only work at L4 for this Kubernetes API traffic, because the encrypted method, path, and user information are invisible.

L7 is not inherently more balanced than L4 either. It must select a backend for each request as it arrives and maintain multiple upstream connection pools; if the implementation simply decrypts and then pins the entire downstream connection to one upstream, it still does not achieve request-level balancing.

## 3. TLS Termination Moves the Identity Boundary

<img src="/assets/practices/kube-apiserver-load-balancing/tls-termination-boundaries.png" alt="TLS Passthrough versus terminate-and-re-encrypt in kube-apiserver load balancing" width="1200">

### 3.1 Passthrough: The Default Option with the Smallest Trust Surface

In L4 Passthrough, the load balancer does not decrypt traffic. Client certificates, Bearer Tokens, authentication errors, and audit identity are all handled by kube-apiserver as-is. The certificate private key does not need to be placed on the LB, and the LB cannot impersonate Kubernetes users.

Its limitations are equally clear: the entry point cannot route by API attributes and can usually only see connection counts and byte counts; a successful TCP probe only proves that 6443 is listening, not that the watch cache has been initialized or that etcd is available.

Therefore, even when the data plane runs at L4, I add a separate, authenticated `/readyz` active probe. The Kubernetes documentation states that `/livez` is used to determine whether the process needs to be restarted, while `/readyz` is used to determine whether the instance can receive traffic; when the API Server is initializing or the watch cache has not yet synchronized, `/readyz` fails. [API Server health checks](https://kubernetes.io/docs/reference/using-api/health-checks/)

### 3.2 Terminate + Re-encrypt: The Gateway Becomes a Trusted Proxy

Once the gateway terminates downstream TLS, the original client certificate cannot "pass through" the new TLS session to continue being verified by the API Server. Production designs typically choose from the following two paths:

| Identity method | How it works | Applicable boundary |
| --- | --- | --- |
| Forward Bearer Token | After the gateway performs necessary checks, it passes the original Authorization Token to the API Server for verification | Suitable for Token/OIDC; cannot preserve the original client certificate authentication chain |
| Gateway identity + Impersonation | The gateway authenticates the client, accesses upstream with a dedicated mTLS identity, and conveys the original user/user group via Impersonate information | Can unify multiple downstream authentication methods, but the gateway gains high-value permissions |

The [KubeGateway design](https://github.com/kubewharf/kubegateway) uses the Kubernetes Impersonation mechanism: the API Server first authenticates the gateway, then confirms that the gateway has permission to impersonate the user, and finally authorizes based on the impersonated user, with corresponding information retained in the audit log. [CNCF architecture introduction to KubeGateway](https://www.cncf.io/blog/2023/01/26/kubegateway-a-customized-seven-layer-load-balancer-for-kube-apiserver/)

The production baseline for this chain includes at least:

- The gateway uses a dedicated, short-lived, rotatable upstream client certificate;
- The API Server only allows precisely matched gateway identities to perform the required Impersonate operations, without broad wildcard permissions;
- The gateway must not trust client-supplied `Impersonate-*` or similar identity headers; it must delete them and regenerate them from the authentication result;
- Upstream continues to use TLS/mTLS and verifies the API Server certificate; it must not be downgraded to plaintext for convenience;
- Audit logs record the gateway identity, original user, request UID, source, and routing result simultaneously, with periodic sampling and cross-checking;
- Certificate rotation must cover all three segments—downstream, the gateway itself, and upstream—and verify the overlap window between old and new certificates as well as rollback.

## 4. Get the L4 Approach Right First

For most clusters, I keep the L4 architecture and resolve connection skew in the following order.

### 4.1 Use `/readyz` for Health Checks, Not Just Port Probing

The data plane can continue with TLS Passthrough, but the health controller should use credentials with least privilege to check each backend's HTTPS `/readyz`. Use the HTTP status code as the basis for traffic draining; `?verbose` is for manual troubleshooting only—do not let automation parse volatile text content.

When a backend recovers, let `/readyz` pass consecutively for multiple periods before adding it back to the service pool. This avoids instances whose watch cache has not yet been initialized from absorbing a LIST/WATCH storm. The current Kubernetes API documentation also states that during watch cache initialization, readiness protection is applied and some expensive requests return 429 and `Retry-After`; clients must still implement backoff. [Kubernetes API Concepts](https://kubernetes.io/docs/reference/using-api/api-concepts/)

### 4.2 Use GOAWAY for Gentle Connection Rotation

kube-apiserver provides `--goaway-chance`: it probabilistically sends GOAWAY to HTTP/2 clients per request, without interrupting current in-flight requests, allowing clients to reconnect and pass through the LB again. The official parameter documentation gives a recommended starting point of `0.001`, with an allowed range of 0 to 0.02; clusters with a single instance or no LB should not enable it. [kube-apiserver parameter reference](https://kubernetes.io/docs/reference/command-line-tools-reference/kube-apiserver/)

```text
--goaway-chance=0.001
```

This is only a starting experimental value. When every request has a probability of triggering it, the higher the QPS, the more frequent the connection rotation; setting it too large may create pressure from TLS handshakes, Watch reconnects, and LIST recovery. When rolling it out, I observe per-instance connection distribution, GOAWAY/reconnect counts, LIST/WATCH rates, 429s, and TLS CPU, then adjust gradually.

`--http2-max-streams-per-connection` can limit the maximum number of Streams on a single HTTP/2 connection that the server advertises to clients. It mainly constrains per-connection concurrency and is not equivalent to load balancing; setting it too small increases connections and handshakes, while setting it too large expands the concentration on a single connection. Unless the problem has been reproduced with real clients, I keep the Go default.

### 4.3 Releases Follow "Ready First, Drain Traffic, Then Exit"

Before an API Server exits, it needs to let the LB stop sending new traffic, then leave draining time for ordinary requests and long Watches. Relevant parameters include:

- `--shutdown-delay-duration`: immediately makes `/readyz` fail once the shutdown process begins, while delaying actual termination to give the LB time to drain traffic;
- `--shutdown-send-retry-after`: while draining non-long requests, returns 429, `Retry-After`, and `Connection: close` for new requests;
- `--shutdown-watch-termination-grace-period`: limits the time spent waiting for active Watches to finish during the graceful shutdown phase.

These parameters should be calculated together with the LB health check interval, failure threshold, static Pod/process manager termination grace period, and client backoff—not by copying a "30 seconds" value into each one. The release automation order should be: add or start new instances → wait for readiness and cache warm-up → remove old instances from the entry point → observe connection draining → terminate old instances. Change only a limited failure domain at a time.

### 4.4 `leastconn` Can Only Optimize New Connections

Using least-connections in L4 is usually better suited to long connections than source-address hashing alone, but it still only selects the backend with fewer current connections for new connections. It cannot move established HTTP/2 Streams, and it does not know whether a connection is doing an idle Watch or a continuous large LIST.

Therefore, I do not treat "equal backend connection counts" as the final success criterion. What really matters is whether per-instance request rates, bytes returned, in-flight requests, CPU, memory, and tail latency all return to budget together.

### 4.5 After Scaling Out API Servers, How to Actually Rebalance Traffic

Adding a fourth API Server to the LB only affects **new connections**. HTTP/2 connections already established on the first three instances will not proactively migrate just because the backend count changed. Production scale-out must handle instance readiness, LB traffic release, and old connection rotation simultaneously.

Before making changes, first confirm how many access paths actually exist:

- Do kubelet, external controllers, and operational kubeconfigs access a unified `controlPlaneEndpoint`;
- Do in-cluster clients access through `kubernetes.default.svc`, forming another L4 path via Service Endpoints and kube-proxy;
- Do controller-manager, scheduler, or node-local Agents connect directly to `127.0.0.1`, node addresses, or node-local LBs;
- Can the monitoring dashboard distinguish the above sources by API Server instance.

Scaling out only the external LB backends cannot change traffic on the direct-connection and Service paths. Only by first separating the sources can you explain why the LB already has four backends yet some requests remain pinned to old instances.

The kubeadm high-availability documentation recommends a TCP forwarding LB in front of control plane nodes and requires the LB address to match `ControlPlaneEndpoint`; the TCP port probe described in the documentation is suitable for installation bootstrap, but the runtime phase should also add the `/readyz` and connection lifecycle gates described earlier in this article. [kubeadm high-availability control plane](https://kubernetes.io/docs/setup/production-environment/tools/kubeadm/high-availability/)

Before a new instance enters the service pool, also verify: the serving certificate covers the same LB DNS/IP; Client CA, ServiceAccount Key, Encryption Provider, audit, Admission configuration, Runtime Config, and Feature Gates match existing instances; it connects to the intended etcd cluster; and the version skew complies with Kubernetes policy. `/readyz` passing consecutively only proves that the current check items are ready—it cannot replace configuration consistency checks.

I use the following scale-out order:

| Phase | Action | Evidence that must be observed | Stop condition |
| --- | --- | --- | --- |
| Establish baseline | Record per-instance QPS, connections, CPU, P99, 429, LIST/WATCH, and etcd latency over at least one stable window | Baseline time range and pre-release snapshot | Metrics missing or instance labels cannot be distinguished |
| Startup | New API Server does not yet receive production traffic; access the backend directly to complete certificate, version, API, etcd, and `/readyz?verbose` checks | Readiness, startup logs, configuration diffs | Certificate, configuration, or watch cache not ready |
| Join | L4 first registers as a healthy backend; L7 first sets weight to 0 or very low, then gradually increases traffic | New instance receives probes and a small proportion of real requests | Authentication, authorization, audit, or protocol results inconsistent |
| Warm-up | Observe cache, memory, CPU, P99, and etcd Range; do not substitute a single GET for warm-up acceptance | New instance metrics enter the normal range | LIST/429/etcd latency rises sharply |
| Migration | Use existing GOAWAY for natural rotation, or drain old backends one by one before controlled connection termination | Reconnect rate, TLS handshakes, Watch recovery, LIST peaks | P99, 429, reset, or etcd pressure exceeds budget |
| Convergence | Restore uniform weights; continue observing across at least one business peak | Request share and resource pressure both return to target range | Only connection counts are balanced while QPS/CPU remain clearly skewed |

<img src="/assets/practices/kube-apiserver-load-balancing/scale-out-rebalance-runbook.png" alt="Production steps for API Server scale-out, traffic admission, and rebalancing of legacy HTTP/2 connections" width="1200">

#### Two connection migration approaches for L4

**Progressive migration** suits scenarios without urgent capacity risk. A lower `--goaway-chance` should have been enabled and validated before scale-out; after new instances join, wait for natural connection rotation. The advantage is smoother reconnects; the cost is that balance cannot be guaranteed within a fixed short window. This parameter is an API Server startup parameter and should be incorporated into the control plane baseline in advance; enabling it for the first time during scale-out combines a parameter release with a capacity change.

**Controlled shuffle** is used when existing instances are already near capacity limits and new instances need to share traffic quickly. Process one old backend at a time:

1. Set the old backend to Drain, removing it from normal new-connection selection; if persistence rules are configured, separately confirm whether it will still be hit;
2. Wait for normal short connections and requests to finish naturally, and confirm other instances still have capacity;
3. Trigger graceful exit through the API Server, or after client reconnect capability has been verified, controllably terminate the remaining connections on that backend;
4. When clients reconnect, the LB re-selects from the healthy pool including new instances;
5. After the old instance returns to Ready and rejoins, process the next one.

Using the HAProxy Runtime API as an example, the operation semantics can be written as follows:

```bash
# 停止把新连接分配给 api1；现有连接仍然保留
echo "set server kube_api/api1 state drain" \
  | socat stdio /run/haproxy/admin.sock

# 仅在已经验证客户端重连和 Watch 恢复后使用：强制结束 api1 会话
echo "shutdown sessions server kube_api/api1" \
  | socat stdio /run/haproxy/admin.sock

# api1 恢复并通过门禁后重新接流量
echo "set server kube_api/api1 state ready" \
  | socat stdio /run/haproxy/admin.sock
```

`drain` only stops normal new-connection selection and does not move existing connections; `shutdown sessions server` immediately terminates sessions on that backend and should be treated as fault-injection-level operation that must not be executed against multiple backends simultaneously. HAProxy Runtime API changes are kept only in running memory; persistent configuration and automation state must be updated in sync. [HAProxy Drain semantics](https://www.haproxy.com/documentation/haproxy-configuration-manual/new/latest/management/) · [shutdown sessions server](https://www.haproxy.com/documentation/haproxy-runtime-api/reference/shutdown-sessions-server/)

Cloud LB "backend removal," "connection draining," and "connection termination" are often three different options, and the exact semantics must be confirmed by capturing connections in a test environment. Seeing only that the backend weight changed to 0 does not imply that legacy HTTP/2 connections have migrated.

#### Post-scale-out acceptance cannot rely on quarter-split alone

Four backends do not necessarily each deserve 25%. Weight, availability-zone locality policy, client access paths, and request cost all change the reasonable proportion. I would also compute:

```text
请求份额_i = instance_i QPS / 总 QPS
连接份额_i = instance_i 活跃连接 / 总活跃连接
压力份额_i = instance_i CPU 或 inflight / 总压力
```

If connection share is close but requests and CPU remain skewed, a small number of hot connections are carrying more Streams, and further L4 algorithm tuning has limited effect. If QPS is close but CPU is skewed, continue investigating request cost by verb, resource, response size, Admission, and GC.

### 4.6 Scale-down requires draining even more than scale-out

When scaling down, first remove the target instance from new-traffic selection, then wait for short requests to finish, and finally execute the API Server's graceful shutdown. Long Watch connections do not disappear automatically just because weight is 0; a maximum drain time must be given, and client recovery by resourceVersion must be verified.

If using stacked etcd, removing a control plane node also involves etcd membership and quorum, and must be handled as an independent change. Do not merge "remove backend from LB," "stop kube-apiserver," and "remove etcd member" into a single non-rollbackable script.

## 5. How should load balancing strategy be chosen

Algorithm selection must first be written down by layer. In TCP mode, round-robin, leastconn, and source in HAProxy documentation select new connections; in HTTP mode or a dedicated L7 Gateway, algorithms may execute per request. [HAProxy Backend algorithms](https://www.haproxy.com/documentation/haproxy-configuration-tutorials/proxying-essentials/configuration-basics/backends/)

| Strategy | Decision unit | Suitable scenarios | Limitations in front of API Server |
| --- | --- | --- | --- |
| L4 round-robin | Round-robin over new TCP connections | Backends of identical spec, similar connection duration and request volume | Long connections no longer participate in round-robin after establishment; hot connections still cause skew |
| L4 leastconn | New connections go to backends with fewer current connections | Many long connections such as Watch and gRPC, significant connection lifetime differences | Connection count does not represent Stream count, QPS, or request cost |
| L4 source hash | Fixed backend by source address | Connection affinity explicitly required, and sources are sufficiently dispersed | NAT, node egress, or a few controllers form hot spots; scale changes also alter the mapping |
| weighted round-robin | New connections or requests distributed by weight | Backends of different specs, canary, or slow-start for new instances | L4 weight does not affect existing connections; weights should come from measured capacity |
| random / P2C | Pick random candidates, then choose the lighter backend | Many backends, want to reduce full scans and herd effects | Still depends on whether "lighter" is measured by connections or active requests |
| L7 round-robin | Each new HTTP request | Same-spec API Servers, prioritizing explainability and stability first | Long Watch connections still occupy the selected instance for a long time |
| L7 least-request | Select backend with fewer active requests | Ordinary request latency varies significantly | Watch counts as an active request for a long time; should be split out or validated in a separate pool |
| locality-aware | Prefer same availability zone, then fail over across zones | Multi-AZ, or cross-zone latency or bandwidth costs are significant | Local preference may sacrifice global balance; remaining capacity must be verified during zone failures |

Envoy's least-request by default can use two random candidates and then select the backend with fewer active requests, i.e., P2C; with different weights, it also combines configured weight with active requests. [Envoy Least Request](https://www.envoyproxy.io/docs/envoy/latest/intro/arch_overview/upstream/load_balancing/load_balancers) This kind of algorithm suits short requests, but mixing Kubernetes long Watch with ordinary GET in one pool directly can cause the active-request metric to be occupied by Watch for long periods.

My default choices are:

- **Three to five same-spec API Servers, keep L4:** Start with leastconn, while enabling readiness-based traffic removal, graceful exit, and a validated low-probability GOAWAY; if connection lifetimes are highly consistent, round-robin can also serve as a more explainable baseline.
- **Sources concentrated behind a few NATs or node egress points:** Avoid source hash. It amplifies "few sources" directly into "backend hot spots."
- **Colocating old and new specs:** Use weights, but first measure sustainable QPS, P99, and CPU for each instance type under the same request model; do not fill weights directly by core count ratio.
- **L7 first launch:** For same-spec backends, start with weighted round-robin and slow-start; after confirming Watch and Upgrade protocol behavior, then evaluate least-request or resource-based routing.
- **High Watch proportion:** Track long-lived streams and ordinary requests separately; when using L7, set up a separate route or upstream pool for Watch to prevent it from interfering with active-request decisions for ordinary requests.
- **Cross-availability-zone:** Local preference is only the first layer of strategy; cross-zone failover must also be preserved, and APF, rate limiting, and backend weights should be designed against remaining capacity after a single zone fails.

Strategy changes also need canary validation. L4 can only be validated through a small subset of ingress or client groups; "give the new backend 10% weight" means approximately 10% of new-connection selection opportunities, not 10% of requests. L7 can get closer to 10% per request, but long Watch connections must still be tracked separately.

## 6. When is an L7 API Gateway worth it

When two or more of the following four requirement categories appear together, an L7 solution usually starts to provide value:

1. API Server frequently experiences sustained request skew due to rolling upgrades or failure reconnects;
2. Routing and rate limiting are needed by user, serviceAccount, verb, resource, namespace, or nonResourceURL;
3. Multi-tenant isolation, circuit breaking, degradation, and independent SLOs are needed at the ingress;
4. The platform manages a large number of clusters simultaneously and needs dynamic certificates, backends, and rule governance.

ByteDance's open-source KubeGateway is explicitly aimed at large-scale clusters of a thousand nodes or more, providing request-level load balancing and routing by verb, apiGroup, resource, user, serviceAccount, and other fields, and claims to reduce the TCP connection count per API Server by at least an order of magnitude. [KubeGateway README](https://github.com/kubewharf/kubegateway)

Generic Envoy, HAProxy, NGINX, or cloud L7 LBs may also accomplish part of the functionality, but the following Kubernetes semantics must be confirmed item by item, rather than going live just because an ordinary GET returns 200:

- Whether downstream and upstream HTTP/2 are both enabled as expected, and whether the connection pool can spread across multiple API Servers;
- Whether Watch allows long-duration transfers, and whether idle timeout, buffer, and backpressure are correct;
- Whether the Upgrade/WebSocket/SPDY paths for exec, attach, port-forward, and `kubectl logs -f` are complete;
- When the gateway removes a backend, how existing streaming requests terminate and reconnect;
- Whether authentication failures, authorization failures, 429, 5xx, and client cancellations are returned unchanged;
- Whether request body size, streaming responses, compression, and timeouts are altered by default gateway policies.

L7 rate limiting also cannot replace API Priority and Fairness. A gateway is suitable for discarding obviously anomalous traffic at the ingress or enforcing coarse-grained per-tenant budgets; APF lives inside the API Server, understands Kubernetes request classification, seats, and fair queuing, and should continue to protect critical control loops under overload. [API Priority and Fairness](https://kubernetes.io/docs/concepts/cluster-administration/flow-control/)

## 7. Do not let gateway automatic retries mask indeterminate writes

One of the most dangerous default behaviors at the control plane ingress is automatic retry of all 5xx errors or connection drops.

| Request type | Recommendation |
| --- | --- |
| GET | May retry when no upstream response was clearly received, and with constraints on retry count and total time limit |
| Paginated LIST | Limited retry is acceptable, but continue/resourceVersion semantics must be preserved |
| WATCH | Rebuilt by the Kubernetes client from resourceVersion; do not let the proxy silently splice into a "seemingly continuous" stream |
| POST / PUT / PATCH / DELETE | No generic automatic retry for requests with unknown outcomes; clients should query object state or rely on idempotent preconditions |
| exec / attach / port-forward | No opaque replay after connection establishment; disconnects are re-initiated by the user or upper-layer tooling |

If the gateway has already delivered a write request to the API Server and the connection drops only on the return path, the gateway cannot know whether the write was committed. Sending it again may cause duplicate operations, conflicts, or overwrites. The safe approach is to surface the failure honestly to the client while retaining Audit-ID, request UID, upstream instance, and retry decision for confirming the final state.

## 8. How should the effectiveness of different approaches be compared

Public case studies are useful for judging direction, but cannot be assembled into a "who is faster by how much" leaderboard, because hardware, object scale, QPS, request distribution, and test versions differ.

| Approach | Problems it can solve | Public or mechanism-level evidence | Still requires self-validation |
| --- | --- | --- | --- |
| L4 Passthrough | Simple HA, end-to-end TLS | Short path, simple identity boundary; no request-level balancing | Failure removal, connection skew, release recovery time |
| L4 + GOAWAY + graceful exit | Mitigates long-lived connection stickiness and rollout skew | kube-apiserver officially provides GOAWAY and graceful shutdown parameters | Appropriate probability, reconnect storms, Watch/LIST cost |
| Client/server joint modification | More proactive connection rebuilding and overload protection | Alibaba public case reports essentially balanced load after modification, recoverable after restarting two instances | Own client coverage, version maintenance, and recovery SLO |
| Dedicated L7 such as KubeGateway | Request-level balancing, routing, rate limiting, and multi-cluster governance | CNCF-reposted ByteDance case reports ~1 ms proxy overhead and 350k+ QPS; project README reports connection count reduced by at least an order of magnitude | P99, availability, security, and operational cost under same hardware and request model |

The 1 ms and 350k+ QPS in the ByteDance case are public results from their environment, and their applicability is constrained by the hardware, version, and traffic model at the time. For my own cluster, I would replay the same batch of requests sequentially against direct single-instance, L4, L4+GOAWAY, and candidate L7, keeping backend API Server, etcd, authentication chain, object set, and client concurrency unchanged.

<img src="/assets/practices/kube-apiserver-load-balancing/rollout-and-evidence-gates.png" alt="Release, failure, and security acceptance gates for kube-apiserver ingress optimization" width="1200">

## 9. An executable load test and failure validation plan

### 9.1 Load model

Do not use only an `kubectl get pods` loop. Build at least four independent load groups:

| Load group | Example | Observation focus |
| --- | --- | --- |
| Short reads | GET, paginated LIST, common discovery | QPS, P50/P99, connection pool, serialization, and returned bytes |
| Writes | CREATE/PATCH/DELETE of temporary objects | Admission, etcd commit, 429, timeouts, and indeterminate results |
| Long-lived streams | WATCH, logs -f | Long-connection distribution, disconnects, resourceVersion resume, and slow consumers |
| Upgrade streams | exec, attach, port-forward | Upgrade success rate, session interruption, and gateway compatibility |

Then overlay three events: rolling restart of one API Server, forced removal of one backend, and recovery of one cold instance. Success criteria must not be written only as "99.9% request success rate"; also define maximum per-instance load deviation, P99 budget, 429 ceiling, Watch recovery time, and connection re-convergence time.

### 9.2 Core metrics

The following PromQL is for establishing perspective; labels must be adjusted to actual collection configuration:

```promql
# 各 API Server 请求率
sum by (instance) (rate(apiserver_request_total[5m]))

# 各实例 P99；生产看板还应按 verb/resource 拆分
histogram_quantile(
  0.99,
  sum by (instance, le) (rate(apiserver_request_duration_seconds_bucket[5m]))
)

# 当前执行中的读写请求
sum by (instance, request_kind) (apiserver_current_inflight_requests)

# APF 拒绝
sum by (instance, flow_schema) (
  rate(apiserver_flowcontrol_rejected_requests_total[5m])
)
```

API Server metrics must also be placed on the same timeline as LB/gateway metrics: frontend/backend connection counts, TLS handshake rate, upstream resets, per-backend request rate, active health status, retry counts, per-route P99, gateway CPU/memory, and certificate expiry. Looking only at API Server CPU makes it impossible to tell whether traffic is truly balanced or whether the gateway is dropping requests.

I would add two direct gates to the dashboard:

```text
实例请求偏差 = max(各实例请求率) / avg(各实例请求率)
实例压力偏差 = max(各实例 CPU 或 inflight) / avg(各实例 CPU 或 inflight)
```

Thresholds should not be copied verbatim. Short-term deviation is acceptable; the key is whether the system can reconverge within a defined time after a failure or release, without tail latency, error rate, and etcd pressure deteriorating in tandem.

## 10. Production Rollout Sequence

### Phase 1: Measure the Current State

Record requests, connections, watches, CPU, memory, P99, and returned bytes per API Server instance; align the onset time of skew with upgrades, failures, certificate rotation, and controller restarts. If three instances have similar request counts but large CPU differences, first investigate large requests by verb/resource rather than attributing the cause to the load balancer.

### Phase 2: Strengthen the L4 Baseline

Complete `/readyz` traffic capture, scale-out-before-scale-in, graceful shutdown, and backend recovery gating. Only after observing HTTP/2 stickiness, validate `--goaway-chance` from a low value. Preserve end-to-end TLS and one emergency bypass entry point.

### Phase 3: Shadow-Validate L7

Replicate the statistical distribution of real traffic or perform sanitized replay, letting L7 first carry test identities and test resources. Validate all long-lived streams and upgrade protocols, then perform fault injection, certificate rotation, and rolling upgrades of the gateway itself. Do not create shadow traffic by duplicating real write requests.

### Phase 4: Migrate in Batches by Caller

First migrate rollback-capable, read-dominated automated clients, then migrate controllers and node components. Compare direct-connection/L4 bypass and L7 metrics for every batch simultaneously. Gateway rules, certificates, and identity mappings should be versioned; changes should have static validation, canary, and automatic rollback.

## 11. Final Selection Recommendations

| Cluster Situation | Recommended Approach |
| --- | --- |
| Small-to-medium scale, uniform API Server load, no complex ingress governance | L4 TCP + TLS Passthrough; implement `/readyz` and graceful release well |
| Occasional connection skew after upgrades, but limited governance needs | Stay on L4; validate `--goaway-chance`, leastconn, scale-out-before-scale-in, and connection draining |
| More than a thousand nodes, multi-tenant, many watches, requiring request-attribute-based routing and rate limiting | Evaluate KubeGateway or an L7 gateway that has passed full Kubernetes semantic validation |
| Unified ingress and certificate governance across multiple clusters | Independent API Gateway control plane; isolate certificates, upstream pools, quotas, and failure domains per cluster |
| Only want to reduce brief skew after a single failure | Do not introduce complex L7 directly; first fix rollout, readiness, and connection lifecycle |

The value of the L4 approach is a short path and a clear trust boundary; the value of the L7 approach is raising the balancing unit from connections to requests and gaining fine-grained governance capabilities. The two correspond to different responsibility models. As long as TLS is terminated at the gateway, the team simultaneously takes on identity propagation, audit integrity, protocol compatibility, and gateway high availability. A mature solution should map each new capability to these new responsibilities one-to-one, and prove through release and failure processes that it can recover.

## References

- [HTTP/2 RFC 9113](https://www.rfc-editor.org/rfc/rfc9113)
- [kube-apiserver parameter reference](https://kubernetes.io/docs/reference/command-line-tools-reference/kube-apiserver/)
- [Kubernetes API Server health checks](https://kubernetes.io/docs/reference/using-api/health-checks/)
- [Kubernetes API Concepts](https://kubernetes.io/docs/reference/using-api/api-concepts/)
- [kubeadm high-availability control plane](https://kubernetes.io/docs/setup/production-environment/tools/kubeadm/high-availability/)
- [API Priority and Fairness](https://kubernetes.io/docs/concepts/cluster-administration/flow-control/)
- [HAProxy backend algorithms](https://www.haproxy.com/documentation/haproxy-configuration-tutorials/proxying-essentials/configuration-basics/backends/)
- [HAProxy Runtime API](https://www.haproxy.com/documentation/haproxy-runtime-api/)
- [Envoy Load Balancing](https://www.envoyproxy.io/docs/envoy/latest/intro/arch_overview/upstream/load_balancing/load_balancers)
- [KubeGateway](https://github.com/kubewharf/kubegateway)
- [KubeGateway: A customized seven-layer Load Balancer for kube-apiserver](https://www.cncf.io/blog/2023/01/26/kubegateway-a-customized-seven-layer-load-balancer-for-kube-apiserver/)
- [Alibaba's 10,000-node Kubernetes control plane practice](https://developer.aliyun.com/article/720966)
