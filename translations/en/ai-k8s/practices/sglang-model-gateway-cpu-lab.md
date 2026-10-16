---
title: "SGLang Model Gateway CPU Hands-On"
description: "Deploy SGLang Router and two OpenAI-Compatible Mock Workers on a GPU-less Kubernetes 1.30 cluster; test dynamic discovery, round robin, removal and recovery, and Prometheus metrics"
status: lab
last_reviewed: 2026-08-07
---

# SGLang Model Gateway CPU Hands-On

You can validate part of SGLang's cluster capabilities without a GPU, but conclusions must be limited to the **Model Gateway/Router control chain**. This time, on the sr1 Kubernetes 1.30.4 cluster, we deployed SGLang Router v0.2.4 and two CPU OpenAI-Compatible Mock Workers, and actually exercised Kubernetes dynamic discovery, OpenAI API forwarding, Round Robin, Pod removal and recovery, request IDs, and Prometheus metrics.

No model was loaded this time, so this cannot be used to claim that SGLang Runtime, Radix Cache, GPU performance, multi-node parallelism, or P/D KV transfer have been validated.

## 1. Final Results

| Validation Item | Measured Result | What It Demonstrates |
| --- | --- | --- |
| Router and Worker startup | 1 Router and 2 Mock Workers all Ready | Image, parameters, probes, and basic networking work |
| Kubernetes dynamic discovery | Logs show two `Adding pod` and `Activated worker` entries in sequence | Label Selector, Pod IP, and minimal RBAC are effective |
| OpenAI-Compatible API | `/health`, `/v1/models`, `/v1/chat/completions` return 200 | Requests can pass through the Router to the Workers |
| Round Robin | 6 consecutive requests strictly alternate between the two Pods | The routing policy actually takes effect, not just exists as a parameter |
| Scale-down and removal | After 2→1, logs show `Removing pod` and `Removed worker` | The Router can follow Pod deletion to update the backend set |
| Continuous service with a single replica | After scale-down, 3 consecutive requests are all served with 200 by the remaining Pod | The removed Pod no longer receives requests |
| Recovery | After 1→2, the new Pod auto-registers, and two subsequent requests land on different Pods | New Endpoints can automatically join the routing set |
| Prometheus | Decision, request, health, circuit-breaker result, and Add/Remove Worker metrics present | Can be integrated into monitoring, but metric semantics must be validated first |

## 2. First Distinguish Runtime and Router Versions

As of August 7, 2026, the latest release of the SGLang main project is v0.5.16, but the latest official `lmsysorg/sglang-router` container tag directly available on Docker Hub is v0.2.4. This is not downgrading the Runtime to v0.2.4; rather, **SGLang Runtime and Model Gateway/Router use independent versions and release cadences**.

The fixed combination this time is:

| Item | Version or Status |
| --- | --- |
| Kubernetes Server | v1.30.4 |
| Node architecture | amd64 |
| SGLang Router | v0.2.4 |
| SGLang Runtime | Not deployed |
| Worker | CPU OpenAI-Compatible Mock v0.7.0 |
| GPU | Cluster reports no allocatable `nvidia.com/gpu` |

The official Router v0.2.4 image currently only supports the amd64 architecture. For ARM clusters, you must first confirm whether to build it yourself or whether upstream has already supplied a corresponding image. For production rollout, do not just write "use the latest SGLang"; instead, record the Runtime, Router, Worker protocol, and image Digest separately.

References: [SGLang v0.5.16](https://github.com/sgl-project/sglang/releases/tag/v0.5.16), [SGLang Router image tags](https://hub.docker.com/r/lmsysorg/sglang-router/tags), [SGLang Model Gateway](https://docs.sglang.io/docs/advanced_features/sgl_model_gateway)

## 3. Experiment Architecture

```text
本机 curl
  → kubectl port-forward（只用于验收）
  → Service/sglang-router:30000
  → SGLang Router v0.2.4
      ├─ watch Pods: sglang.ai/worker=true
      ├─ round_robin
      ├─ health check / circuit breaker
      └─ :29000 Prometheus metrics
           ├─ Pod A :8000，CPU Mock
           └─ Pod B :8000，CPU Mock
```

Resources are split across two Namespaces:

- `sglang-system`: Router, ServiceAccount, and Service;
- `sglang-demo`: two CPU Workers, discovery Role/RoleBinding, and internal Service.

The Role only has `get/list/watch pods`, granted to `sglang-system:sglang-router` via a cross-Namespace RoleBinding. No ClusterRole is needed, and the Router should not be given `cluster-admin` for convenience.

The full manifest is in [`examples/sglang-sr1/sglang-cpu-gateway.yaml`](https://github.com/runzhliu/aik8s/blob/main/examples/sglang-sr1/sglang-cpu-gateway.yaml).

## 4. Deployment and Inspection

```bash
kubectl apply -f examples/sglang-sr1/sglang-cpu-gateway.yaml
kubectl rollout status deployment/sglang-cpu-mock \
  -n sglang-demo --timeout=180s
kubectl rollout status deployment/sglang-router \
  -n sglang-system --timeout=180s
```

In practice, the Workers were distributed across different nodes, and the Router also ran independently:

```text
sglang-router                              1/1 Running
sglang-cpu-mock-59bd99996c-5k8zm          1/1 Running
sglang-cpu-mock-59bd99996c-twtxx          1/1 Running
```

Verify least privilege:

```bash
kubectl auth can-i list pods \
  --as=system:serviceaccount:sglang-system:sglang-router \
  -n sglang-demo
```

Returns `yes`. The discovery evidence from the Router logs is:

```text
Starting K8s service discovery | selector: 'sglang.ai/worker=true'
Adding pod: sglang-cpu-mock-... | type: Some(Regular) | url: http://10.x.x.x:8000
Activated worker http://10.x.x.x:8000 (marked as healthy)
```

A Pod must satisfy both the Label Selector and the Ready condition. Discovery here directly targets Pod IPs and does not go through the Worker Service load balancer; otherwise, the Router could not know which replica was actually selected.

## 5. API and Round Robin Hands-On

During testing, only a local port was temporarily forwarded:

```bash
kubectl port-forward --address 127.0.0.1 \
  -n sglang-system service/sglang-router \
  33000:30000 32900:29000
```

The health check returns:

```text
HTTP/1.1 200 OK
OK
```

The model list returns `unknown`:

```json
{"object":"list","data":[{"id":"unknown","object":"model","owned_by":"local"}]}
```

This is the result of the Mock not implementing the full SGLang `/server_info` and `/model_info` metadata protocol, not a recommended way to name production models.

Chat request:

```bash
curl -sS http://127.0.0.1:33000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "unknown",
    "messages": [{"role": "user", "content": "round robin test"}],
    "max_tokens": 4,
    "stream": false
  }'
```

The Mock Pod names carried in 6 consecutive responses, in order, are:

```text
mdjhj → 5k8zm → mdjhj → 5k8zm → mdjhj → 5k8zm
```

This evidence is stronger than "both Pods are Ready": it proves requests pass through the Router and that `round_robin` actually executes across two independent Endpoints.

## 6. Removal and Recovery Experiment

First scale the Workers from 2 down to 1:

```bash
kubectl scale deployment/sglang-cpu-mock \
  -n sglang-demo --replicas=1
```

The Router observes the Pod deletion:

```text
Removing pod: sglang-cpu-mock-... | url: http://10.x.x.x:8000
Removed worker http://10.x.x.x:8000
```

Subsequently, 3 consecutive Chat requests are all returned with 200 by the remaining Pod `5k8zm`. Restore to 2 replicas:

```bash
kubectl scale deployment/sglang-cpu-mock \
  -n sglang-demo --replicas=2
```

The logs again show the new Pod's `Adding pod` and `Activated worker`; after recovery, two requests land on the new and old Pods respectively.

This validates **discovery and removal after a change in Kubernetes desired state**. It does not yet cover node sudden disconnection, half-open connections, process death during streaming output, health endpoint false positives, or long-request retries. Production failure drills must still add these variables.

## 7. Prometheus Metrics Hands-On

The Router exposes Prometheus text metrics on port 29000. After round robin, rolling update, and scaling, key values include:

```text
sgl_router_http_responses_total{status_code="200"} 13
sgl_router_requests_total{route="/v1/chat/completions"} 12
sgl_router_job_success_total{job_type="AddWorker"} 5
sgl_router_job_success_total{job_type="RemoveWorker"} 3
sgl_router_policy_decisions_total{policy="round_robin",worker="http://10.x.x.x:8000"} ...
sgl_router_processed_requests_total{worker="http://10.x.x.x:8000"} ...
sgl_router_worker_health{worker="http://10.x.x.x:8000"} 1
sgl_router_cb_outcomes_total{worker="http://10.x.x.x:8000",outcome="success"} ...
```

The Add/Remove counters include Router/Worker rolling updates during the experiment and do not equal the pure count of a single scale operation. Alerts and Dashboards are better built by combining:

- Current Pod list with `sgl_router_worker_health`;
- Per-Worker `processed_requests_total`;
- `policy_decisions_total` and the expected policy;
- HTTP 429/5xx, circuit-breaker status, and request latency;
- Kubernetes Ready, restarts, evictions, and Endpoint changes.

### 7.1 A Real Metric Gap

In this hands-on test, both Workers had `worker_health=1`, and requests continuously returned 200, but:

```text
sgl_router_active_workers 0
```

Therefore, on Router v0.2.4, this Gauge alone cannot be used to determine "no available Workers." Before production rollout, re-test on the target version and confirm the metric semantics or defect with upstream; until fixed, cross-check using per-Worker health, request decisions, actual success rates, and Kubernetes Endpoints.

## 8. Protocol Boundaries Exposed by the CPU Mock

### 8.1 `openai` Backend Cannot Be Combined with Dynamic Discovery

To make the generic Flask Mock work fully over HTTP/1.1, we attempted to add:

```text
--backend openai
```

Router v0.2.4 rejects this combination at startup:

```text
Configuration error: OpenAI mode does not support service discovery
```

Therefore, this experiment keeps the default `sglang` backend and Kubernetes Service Discovery. If the goal is to proxy arbitrary static OpenAI-Compatible Endpoints, you can use `--backend openai` with static Worker URLs; if the goal is automatic discovery as Pods scale, you should use a real SGLang Runtime, or first confirm that a newer version has changed this restriction.

### 8.2 Generic Mock Is Not an SGLang Worker

The default backend probes SGLang connectivity during registration. The Flask/Werkzeug Mock does not support HTTP/2, so the logs show one 505 probe error; the Router then falls back and can still complete Chat requests over HTTP/1.1. This only proves the fallback path, not a production protocol combination.

The Token Usage returned by the Mock is also a random placeholder and cannot be used to calculate throughput, cost, TTFT, or TPOT.

### 8.3 Why the Example Has No API Key

The Router's `--api-key` is used to access Workers. When combining the generic Mock with the default SGLang backend, this authentication convention is not correctly inherited, so the CPU Workers remain unauthenticated, may only be used within an isolated Namespace, and must not be exposed to the office network or the public internet.

Production recommendation:

```text
Client
  → Higress：TLS、OIDC/API Key、租户授权、限流、审计
  → SGLang Router：模型池选择、Prefix/负载/P-D 路由
  → SGLang Runtime：受限集群网络、可选 Worker mTLS/API Key
```

## 9. What Else Can Be Tested Without a GPU

| Can be tested first on CPU/Mock | Status This Time | Cannot Be Proven by CPU Mock |
| --- | --- | --- |
| Router startup, probes, Service, and resource limits | Tested | CUDA/ROCm kernel availability |
| Kubernetes Label dynamic discovery and minimal RBAC | Tested | Model actually loads successfully |
| Round Robin | Tested | Real benefit of Prefix Cache |
| Worker Add/Remove and basic continuous service | Tested | GPU OOM, NCCL failures, and high-speed node networking |
| Prometheus exposure, request IDs, HTTP status | Tested | TTFT, TPOT, throughput, and GPU memory capacity |
| `random`, `power_of_two`, concurrency limits, queues, retries, circuit breaking | Can continue testing | Optimality of policies under real mixed long/short requests |
| P/D Label Selector and Router startup parameters | Can do syntax/control-plane testing | Prefill generating KV, Bootstrap, KV transfer, and Decode continuation |
| CORS, timeouts, 429, and error codes | Can continue testing | Real recovery semantics after streaming token interruption |

Even if `cache_aware` can be unit-tested for policy on the Mock, there is no real Radix/Prefix Cache hit evidence. You cannot claim cache hit rate or TTFT improvement just because the same Prompt is pinned to the same Pod.

## 10. Steps to Switch to a GPU Runtime

1. Replace the CPU Mock with a SGLang Runtime image that has passed compatibility testing;
2. Pin the model, quantization, CUDA, PyTorch, communication libraries, Router, and Runtime versions;
3. Configure `nvidia.com/gpu`, shared memory, model cache PVC/HostPath, and startup probes;
4. Keep the Pod's Router Selector and confirm `/health`, model metadata, and API Key protocol;
5. First establish correctness and performance baselines with a single Pod on single/multiple GPUs;
6. Then use RBG, LeaderWorkerSet, or KubeRay to express one cross-node model replica;
7. Finally validate Cache-aware, P/D, KV transfer, cancellation, rolling release, and Autoscaling.

In P/D mode, both Prefill and Decode are GPU Workers that actually run the model. The Router can discover both Pod types via `--prefill-selector` and `--decode-selector`, but you must use a real Runtime to validate Bootstrap information and the KV data path. Seeing both Pod types registered does not mean Decode can continue generation from Prefill's KV.

## 11. How to Combine with Higress, RBG, and AIBrix

| Component | Responsibility in This Chain |
| --- | --- |
| Higress | Domain, TLS, authentication, tenant quotas, protocol governance, auditing, and unified entry |
| SGLang Router/Model Gateway | SGLang Worker discovery, request-level replica selection, Prefix/load policies, and P/D pairing |
| RBG/LWS/KubeRay | Pod lifecycle and topology for Router, Prefill, Decode, or multi-node ranks |
| SGLang Runtime | Model execution, batching, Radix Cache, parallelism, and KV data path |
| AIBrix | Another LLM Gateway, model routing, orchestration, Autoscaling, LoRA, and KV capability combination |

One clear combination is:

```text
Higress
  → SGLang Router Service
  → RBG 管理的 SGLang Prefill/Decode Worker
```

If you have already adopted the AIBrix Gateway, do not let both SGLang Router and AIBrix perform model-aware replica selection on the same model pool. You can split by model: existing vLLM models go through AIBrix, native SGLang/P-D models go through SGLang Router; or you can uniformly choose one internal Router. Regardless of the choice, retries, timeouts, rate limiting, circuit breaking, and Autoscaling must each have a clearly defined policy owner.

## 12. Pre-Production Acceptance Checklist

- [x] Router and two CPU Mock Workers Ready;
- [x] ServiceAccount has Pod read permission only for the target Namespace;
- [x] Two Pod IPs automatically discovered and activated;
- [x] OpenAI Chat requests return 200;
- [x] Six requests demonstrate Round Robin;
- [x] After scaling from 2 to 1, the remaining replica continues serving;
- [x] After restoring from 1 to 2, the new replica automatically joins;
- [x] Prometheus metrics cover Worker, policy, and HTTP dimensions;
- [ ] Switch to a real SGLang Runtime and load the target model;
- [ ] Verify streaming, cancellation, retry budget, circuit breaking, and long-request failures;
- [ ] Compare policy gains with real Prefix Cache workloads;
- [ ] Prove KV transfer with real Prefill/Decode Workers;
- [ ] Integrate Higress authentication, NetworkPolicy, Secret, and mTLS;
- [ ] Re-verify `active_workers` metrics on the target Router version.

## 13. Cleanup

The experiment resources are fully isolated and can be cleaned up per Namespace:

```bash
kubectl delete namespace sglang-demo sglang-system
```

This time, to keep an entry point for later GPU replacement, cleanup was not performed; the final state remains 1 Router and 2 CPU Mock Workers Ready.

## Further Reading

- [SGLang Model Gateway](https://docs.sglang.io/docs/advanced_features/sgl_model_gateway)
- [SGLang Router Source](https://github.com/sgl-project/sglang/tree/main/sgl-model-gateway)
- [SGLang Documentation](https://docs.sglang.io/)
- [RBG multi-role inference orchestration and sr1 in practice](rbg-existing-cluster.md)
- [AI Gateway, inference routing, and traffic governance](../inference/gateway-routing.md)
- [Distributed and P/D-separated inference](../inference/distributed-serving.md)
