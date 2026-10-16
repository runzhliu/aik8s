---
title: "Higress AI Gateway: Architecture, Installation, and AIBrix Integration in Practice"
description: "Install Higress in isolation within an existing Kubernetes cluster, understand Controller, Gateway, Console, AI Proxy and observability plugins, and design same-cluster and cross-cluster paths between Higress and AIBrix"
status: lab
last_reviewed: 2026-08-06
---

# Higress AI Gateway: Architecture, Installation, and AIBrix Integration in Practice

Higress is not just an Ingress Controller that forwards domain names to Services. It uses Envoy as the data plane and places traditional API Gateway capabilities, Wasm plugins, and model-oriented protocol proxying, authentication, token accounting, rate limiting, and multi-model governance at the same entry layer. For teams that already use Higress to expose business APIs and are planning to introduce AIBrix, vLLM, or SGLang, it is better suited to serve as the "unified entry point and tenant governance" layer rather than replacing the model-aware scheduling logic inside the inference platform.

This article includes a real installation record in an existing Kubernetes 1.30 cluster. The cluster was already running nginx Ingress and the AIBrix Envoy Gateway, so the experiment used a separate Helm Release, Namespace, IngressClass, and ClusterIP Service without taking over existing domains or modifying business entry points.

Final results:

- Higress v2.2.3 Controller, Gateway, and Console all Ready;
- `IngressClass=higress-sr1` isolated from existing `nginx`;
- Echo request returned `higress-sr1-ok` after passing through the Higress Gateway;
- Console returned HTTP 200;
- Higress → AIBrix → two-replica CPU mock vLLM returned HTTP 200;
- The client-forged `routing-strategy: random` was overwritten at the entry point with the platform policy `least-request`, and AIBrix's Pod/IP diagnostic headers were not exposed to the client;
- The experiment has not yet verified real GPU models, the Higress AI Proxy plugin, TLS, or public entry points.

## 1. First distinguish Higress, AIBrix, and the inference engine

```text
客户端 / SDK / Agent
        │
        ▼
Higress
  域名、TLS、认证、租户、API Key、Token 配额、审计、协议转换
        │
        ▼
AIBrix / Inference Gateway / 自研 Router
  模型发现、队列、Prefix/KV、Session、P/D 和 Endpoint 选择
        │
        ▼
vLLM / SGLang / TensorRT-LLM
  Continuous Batching、KV Cache、模型并行和 Token 生成
```

All three layers may use the word "routing," but the input signals differ:

| Layer | Primary decisions | What should not be its sole responsibility |
| --- | --- | --- |
| Higress | Which logical model a user can access, which provider to call, quotas and security policies | Selecting an Endpoint based on each vLLM Pod's KV cache hit status |
| AIBrix/inference routing | Which model pool, role, or specific replica a request should enter | Storing long-term API keys and billing accounts for public users |
| Inference engine | How to batch, allocate KV cache, and perform Prefill/Decode | Enterprise domains, TLS certificates, and organization-level authorization |

Small-scale platforms can have Higress directly proxy one or more vLLM Services. After introducing AIBrix, Higress's Upstream should point to the AIBrix Gateway rather than bypassing it and directly accessing vLLM Pods at random.

## 2. Higress components and resources

After Helm installation, three Deployments appear first:

| Component | Responsibility | Data path |
| --- | --- | --- |
| `higress-controller` | Watches Ingress, Service, plugins, and Higress/Istio resources, generates xDS configuration | Does not carry user requests |
| `higress-gateway` | Envoy data plane, executes routing, TLS, plugins, and traffic policies | Carries user requests |
| `higress-console` | Web management page and management API | Management plane, should not be directly exposed to the public internet |

The following objects also appear:

- `IngressClass`: determines which Ingress Controller handles a given `Ingress`;
- CRDs such as `McpBridge`, `WasmPlugin`, and `EnvoyFilter`: express service sources, plugins, and low-level extensions;
- Istio Networking API: Higress can internally use `Gateway`, `VirtualService`, `DestinationRule`, etc. to express advanced traffic configuration;
- Gateway API: newer versions can choose to enable it, but in a cluster that already has Envoy Gateway/AIBrix, `GatewayClass` ownership should be clarified first;
- ConfigMap/Secret: stores domains, HTTPS, controller configuration, Console accounts, and control-plane CA.

Console is one configuration entry point, not a new data plane. Changes made in the page are ultimately still converted into Kubernetes resources; in production, critical configuration should be incorporated into GitOps to avoid un-auditable state that exists only in the page.

## 3. Why v2.2.3 was chosen for this cluster

At the time of the experiment, both the latest stable Higress release and Helm Chart were v2.2.3. This version provides `global.createIngressClass`, suitable for creating an independent IngressClass in a cluster that already has an Ingress Controller; Kubernetes v1.30 also satisfies the basic API requirements of this version.

Version selection cannot be based on Kubernetes alone: the Helm Chart, Gateway image, Pilot/Controller, Console, Wasm plugin ABI, and existing Gateway API CRDs must also be verified together. Production upgrades should pin the Chart version and image digest, and avoid floating tags.

References: [Higress v2.2.3 Release](https://github.com/higress-group/higress/releases/tag/v2.2.3), [Helm deployment documentation](https://higress.cn/docs/latest/ops/deploy-by-helm/)

## 4. Pre-installation inventory

Do not directly copy the Quickstart into a production cluster. First check for conflict areas:

```bash
kubectl version
kubectl get ingressclass
kubectl get gatewayclass
kubectl get ingress -A
kubectl get gateway,httproute -A
kubectl get crd | grep -Ei 'higress|istio|gateway'
kubectl get deploy,svc -A | grep -Ei 'ingress|gateway|envoy'
```

Inventory results for this run:

| Item | Actual status | Installation decision |
| --- | --- | --- |
| Kubernetes | v1.30.4 | Use Higress v2.2.3 |
| Ingress Controller | Existing nginx, Class is `nginx` | Create new `higress-sr1`, do not set as default Class |
| Gateway API | Already used by AIBrix/Envoy Gateway | Disable Gateway API for the Higress experiment |
| AIBrix Gateway | Already running | Do not modify existing Gateway, HTTPRoute, or EnvoyExtensionPolicy |
| LoadBalancer | No available address allocator | Use ClusterIP for both Gateway and Console initially |
| External Registry | TLS certificate chain not trusted by nodes | Pre-sync pinned-version amd64 images |

## 5. Isolated installation configuration

The [`examples/higress-sr1/values.yaml`](https://github.com/runzhliu/aik8s/blob/main/examples/higress-sr1/values.yaml) in the repository is the minimal configuration for this experiment:

```yaml
global:
  ingressClass: higress-sr1
  createIngressClass: true
  watchNamespace: ""
  enableIstioAPI: false
  enableGatewayAPI: false
  enableAlphaGatewayAPI: false
  enableInferenceExtension: false
  enableRedis: false
  enablePluginServer: false

higress-core:
  gateway:
    replicas: 1
    service:
      type: ClusterIP
  controller:
    replicas: 1
    automaticHttps:
      enabled: false

higress-console:
  replicaCount: 1
  service:
    type: ClusterIP
  ingress:
    enabled: false
```

Isolation was achieved with a dedicated IngressClass rather than pinning `watchNamespace` to a business Namespace. Testing found that when the Controller only watches `higress-lab`, in `higress-system`, the Namespace Controller does not generate the `higress-ca-root-cert` required by the Gateway, and the Gateway remains stuck in `ContainerCreating` because it cannot mount the ConfigMap. After restoring cluster-wide Namespace watching, the Controller acquired the Leader Lease, published the root certificate, and the Gateway was able to start.

Cluster-wide watching does not mean taking over all Ingress resources. Actual route ownership is determined by `ingressClassName: higress-sr1`; existing `ingressClassName: nginx` resources are still handled by the nginx Controller. In production, RBAC, admission policies, and GitOps should also be used to restrict who can create Higress resources.

## 6. Installation commands and offline images

In an online environment, installation can follow the official Helm repository:

```bash
helm repo add higress.io https://higress.io/helm-charts
helm repo update

helm upgrade --install higress-sr1 higress.io/higress \
  --version 2.2.3 \
  -n higress-system --create-namespace \
  -f examples/higress-sr1/values.yaml \
  --set-string higress-console.admin.password='<ADMIN_PASSWORD>'
```

This cluster cannot trust the upstream Registry's certificate chain, involving four images:

```text
higress/console:2.2.3
higress/higress:2.2.3
higress/pilot:2.2.3
higress/gateway:2.2.3
```

On a machine with access to the upstream, sync the `linux/amd64` images to the enterprise Registry, then override via the following values. Do not write the enterprise Registry address into public documentation:

```bash
helm upgrade --install higress-sr1 higress.io/higress \
  --version 2.2.3 \
  -n higress-system --create-namespace \
  -f examples/higress-sr1/values.yaml \
  --set global.hub='<INTERNAL_REGISTRY>' \
  --set higress-console.image.repository='<INTERNAL_REGISTRY>/higress/console' \
  --set-string higress-console.admin.password='<ADMIN_PASSWORD>'
```

Do not sync only the Gateway: the Controller Deployment uses both `higress` and `pilot`, and Console has a separate repository. When preparing images on Apple Silicon, the target architecture must be explicitly specified to avoid pushing arm64 Manifests to amd64 nodes.

## 7. Installation acceptance

### 7.1 Control plane and data plane

```bash
helm status higress-sr1 -n higress-system
kubectl -n higress-system get deploy,pod,svc
kubectl get ingressclass higress-sr1
kubectl -n higress-system get cm higress-ca-root-cert
```

Results for this run:

```text
higress-console      1/1 Ready
higress-controller   1/1 Ready（Pod 内两个容器 Ready）
higress-gateway      1/1 Ready
higress-ca-root-cert 已生成
```

If the Gateway remains in `ContainerCreating`, first run `describe pod`. If the event is `configmap "higress-ca-root-cert" not found`, check the Controller's Namespace watch scope and discovery container logs rather than repeatedly pulling the Gateway image.

### 7.2 Regular Ingress origin fetch

Test checklist is in [`echo-ingress.yaml`](https://github.com/runzhliu/aik8s/blob/main/examples/higress-sr1/echo-ingress.yaml):

```bash
kubectl apply -f examples/higress-sr1/echo-ingress.yaml
kubectl -n higress-lab rollout status deployment/echo
```

Request from inside the cluster through the Gateway Service, explicitly carrying the Host header:

```bash
kubectl -n higress-lab run higress-smoke --rm -i --restart=Never \
  --image=busybox:stable -- \
  wget -qO- --header='Host: echo.higress.lab' \
  http://higress-gateway.higress-system.svc/
```

Actual response:

```text
higress-sr1-ok
```

This result simultaneously proves the Gateway Listener, Ingress conversion, xDS delivery, Service discovery, and backend networking, and is not merely a Pod status of Running.

### 7.3 Single-node k3s end-to-end re-verification

On a single-node k3s v1.36.2+k3s1, the full path was re-verified using the same `higress-sr1` isolation configuration:

```text
curl /v1/chat/completions
  → Higress ClusterIP Gateway
  → aibrix-gateway-upstream 稳定别名 Service
  → AIBrix Envoy Gateway + ext_proc
  → mock-llama2-7b Pod
```

Apply the manifests and request:

```bash
kubectl apply -f examples/higress-sr1/higress-to-aibrix.yaml
kubectl -n higress-system port-forward svc/higress-gateway 18080:80

curl -i http://127.0.0.1:18080/v1/chat/completions \
  -H 'Host: aibrix.higress.lab' \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer <TEST_API_KEY>' \
  -H 'routing-strategy: random' \
  --data '{
    "model": "llama2-7b",
    "messages": [{"role": "user", "content": "gateway validation"}]
  }'
```

The request returned HTTP 200. The AIBrix Gateway Plugin logs recorded `routing_strategy="least-request"` and the selected mock Pod, proving that the Higress override took effect; the client response did not contain `target-pod`, `target-pod-ip`, or `routing-strategy`. After deleting one mock Pod, an immediate retry still returned 200, traffic landed on the surviving replica, and the Deployment subsequently replenished the second Pod. This test proves entry policy, service discovery, and basic self-healing; it does not mean real model reload, KV cache rebuild, and long-connection draining have been validated.

## 8. Console access and accounts

The experiment did not create a public Ingress for Console. The most stable temporary access method is port forwarding:

```bash
kubectl -n higress-system port-forward svc/higress-console 8080:8080
```

Then open `http://127.0.0.1:8080`. The default administrator username is `admin`, and the password should be injected at installation time through secure Helm values, a Secret management system, or CI, and must not be committed to Git. The current Secret fields include `adminUsername` and `adminPassword`, but do not write decoded Secret output into terminal logs or tickets.

Direct Pod IP access is only suitable for temporary troubleshooting: the IP changes after Pod recreation. When long-term access from the corporate office network is needed, prefer configuring an internal Ingress/VIP, TLS, SSO, or at least source IP allowlisting for Console; do not expose the management page directly to the public internet.

## 9. How Higress proxies large models

The Higress AI Proxy can unify multiple upstream model services behind an OpenAI-Compatible API and supports recognizing or converting protocols such as OpenAI and Claude. A typical configuration process is:

1. Store provider API keys in a Secret or external key system;
2. Create logical models and Upstreams so clients never learn the real Endpoint;
3. Enable AI Proxy on the Route, configuring model mapping and protocol;
4. Then layer authentication, token rate limiting, statistics, security, and audit plugins on top;
5. Validate with both streaming and non-streaming requests separately.

References: [AI Gateway overview](https://higress.io/en/ai-gateway), [AI Proxy plugin](https://higress.io/en/docs/latest/plugins/ai/api-provider/ai-proxy/)

### 9.1 Why logical model names matter

Clients can always request `chat-standard`, and the gateway maps it internally to:

```text
chat-standard
  ├── 自托管 AIBrix Pool / vLLM
  ├── 云厂商模型 API
  └── 灾备模型或降级模型
```

This allows model versions, providers, and deployment methods to change independently. However, before failover, capabilities such as context length, tool calling, multimodality, content safety, and output quality must be confirmed as interchangeable; do not switch automatically simply because the HTTP API looks the same.

### 9.2 Token rate limiting is better than QPS-only

LLM request costs vary greatly. A production entry point should at least distinguish:

- Per-tenant input/output tokens per minute;
- Maximum context and maximum output tokens;
- Concurrent requests and active SSE connections;
- Per-model and per-provider budgets;
- Rejection, queuing, or degradation policies after exceeding limits.

Traditional QPS rate limiting can only block large numbers of short requests; it cannot block a small number of very long-context requests.

## 10. Observability

The Higress Gateway's access logs and Prometheus Endpoint can answer entry-layer questions. The AI Statistics plugin can also count input/output tokens, time to first token (TTFT), and total response time, analyzed by gateway, route, service, and model.

Reference: [AI Statistics plugin](https://higress.io/en/docs/latest/plugins/ai/api-o11y/ai-statistics/)

The following labels are recommended for retention, but keep cardinality under control:

| Label/metric | Purpose |
| --- | --- |
| route, logical_model | Find which entry point and which logical model is abnormal |
| tenant/team | Quota, cost, and inefficient resource governance |
| status, error_type | Distinguish authentication, rate limiting, gateway, and model errors |
| input/output tokens | Capacity, cost, and abnormal request identification |
| TTFT, total latency | Interactive experience and end-to-end SLO |
| upstream/model version | Release regression and failover troubleshooting |

Request IDs and Trace Context should be propagated from Higress through to AIBrix and vLLM. Prompt, Response, Authorization, API Key, and Tool parameters should not enter normal access logs by default; debug sampling requires masking, authorization, and retention limits.

## 11. Mature Higress Platform Introducing AIBrix: Should You Mix Them?

The conclusion is: **layered chaining is recommended, but only route models that need AIBrix's advanced scheduling through the second layer. Do not merge the two gateways into a single control plane, and do not migrate all existing services at once.**

When an enterprise already uses Higress to stably carry single-node single-GPU or single-node multi-GPU Deployments, the existing domain names, TLS, authentication, tenants, quotas, auditing, and release processes have already become platform assets. Replacing the ingress to introduce AIBrix carries far more migration risk than benefit. The AIBrix Gateway should be viewed as an "internal inference router" behind Higress, not a second external API Gateway:

```text
                                ┌─→ 现有单机单卡 Deployment Service
Client → Higress 统一入口 ──────┼─→ 现有单机多卡 Deployment Service
                                │
                                └─→ AIBrix 内部 Gateway
                                      ├─→ 多机多卡 Replica A
                                      ├─→ 多机多卡 Replica B
                                      ├─→ Prefill Role / Decode Role
                                      └─→ KV/Prefix/Session 感知 Endpoint
```

"Multi-node multi-GPU" alone is not a sufficient reason to add an AIBrix Gateway. Multi-node execution is usually orchestrated by LeaderWorkerSet, StormService, KubeRay, or the Runtime; if there is only one fixed model replica, requests always enter the same Leader Service, and Higress can still proxy directly. Only when selection must be made among multiple model replicas, roles, or Endpoints based on runtime state does the AIBrix Gateway demonstrate value.

"Model-aware replica selection" here does not mean selecting model parameters or GPU count. It means first identifying the logical model from the request Body/Header, excluding Endpoints that have not loaded that model or Adapter, and then selecting among eligible replicas based on queue length, concurrency, Session, Prefix/KV hit rate, Prefill/Decode role, and health status. Ordinary Service load balancing only sees a set of Endpoints and does not natively understand these model runtime signals. When there is only one overall replica, there is no selection space, so this capability naturally yields no obvious benefit.

Taking DeepSeek-V4-Pro as an example, the official specification is 1.6T total parameters, 49B activated parameters, and 1M Context; the mixed-precision Checkpoint in the official vLLM recipe is approximately 960GB, with a multi-node DP + EP deployment of 2 GB200 NVL4 Trays totaling 8 GPUs. These 8 GPUs constitute one complete Replica, not 8 replicas that a gateway can independently select among:

```text
Higress：识别企业逻辑模型 deepseek-v4-pro、执行认证和配额
  → AIBrix Gateway：在 Replica A 与 Replica B 之间选择
      ├── Replica A：2 Tray / 8 GPU，内部由 vLLM DP + EP 协同
      └── Replica B：2 Tray / 8 GPU，内部由 vLLM DP + EP 协同
```

If only Replica A currently exists, Higress can work by directly accessing its Leader/API Service; when Replica B is added, or Prefill/Decode is split into different Pools, AIBrix becomes responsible for inter-group selection. AIBrix cannot send a request to half the GPUs of A1 and the other half of B2; the Rank composition of a complete replica is controlled by StormService/RoleSet, LeaderWorkerSet, KubeRay, or the Runtime.

References: [DeepSeek-V4 Official Release](https://api-docs.deepseek.com/news/news260424/), [vLLM DeepSeek-V4-Pro Recipe](https://github.com/vllm-project/recipes/blob/main/models/deepseek-ai/DeepSeek-V4-Pro.yaml), [Multi-Node and Disaggregated LLM Inference](distributed-serving.md#deepseek-v4-multi-node-example)

| Scenario | Recommended Path | Reason |
| --- | --- | --- |
| Already stable single-node single-GPU/multi-GPU Deployment | Higress → Service | No need to add another proxy hop and failure domain |
| Single fixed multi-node multi-GPU replica, only exposing Leader Service | Initially Higress → Leader Service | Multi-node orchestration and request replica selection are two separate problems |
| Multiple multi-node multi-GPU replicas requiring load/Session awareness | Higress → AIBrix → Replica | AIBrix handles Endpoint selection within the inference pool |
| P/D separation, KV/Prefix-aware, Role-aware | Higress → AIBrix → Role/Pod | Ordinary Layer-7 gateways do not have access to these real-time inference signals |
| Internal cluster-only calls with no unified API governance requirements | Can use AIBrix Gateway directly | The enterprise governance value of the outer Higress layer is not evident |
| External users, multi-tenant, multi-model, and cloud API mixed | Higress → AIBrix/cloud model Upstream | Higress maintains unified identity, protocol, budget, and auditing |

For progressive migration, split traffic by model or Route: leave existing paths untouched, first establish a Higress → AIBrix Canary for one new logical model, and expand scope only after validation is complete. Do not let Higress and AIBrix both become authoritative writers for retries, authentication, tenant rate limiting, or model mapping.

## 12. Same-Cluster Chaining with AIBrix: Measured Results

In the same cluster, the Higress Upstream should point to the stable Service DNS of the AIBrix Envoy data plane:

```text
Client
  → higress-gateway.higress-system.svc
  → envoy-<namespace>-<gateway>-<hash>.envoy-gateway-system.svc:80
  → AIBrix ext_proc Gateway Plugin
  → selected vLLM Pod
```

Higress is responsible for:

- External domain names, TLS, authentication, and tenants;
- OpenAI/Claude protocol and logical model names;
- Ingress Token quotas, content policies, and auditing;
- Provider-level failover.

AIBrix is responsible for:

- Discovering model Endpoints;
- Selecting Pods based on load, Prefix/KV, Session, and role;
- P/D, StormService, and model workload scaling;
- Capacity protection within the inference pool.

Do not let Higress directly load balance all vLLM Services managed by AIBrix, otherwise AIBrix's model-aware selection will be bypassed.

### 12.1 Using a Stable Service to Hide the Envoy Gateway Hash Name

The Service name auto-generated by Envoy Gateway contains a hash. The experiment created an `aibrix-gateway-upstream` ClusterIP Service, used the owning-gateway label to select AIBrix Envoy Pods, and then pointed the Higress Ingress at this stable name. The full manifest is in [`higress-to-aibrix.yaml`](https://github.com/runzhliu/aik8s/blob/main/examples/higress-sr1/higress-to-aibrix.yaml):

```text
aibrix.higress.lab
  → higress-gateway.higress-system.svc:80
  → aibrix-gateway-upstream.envoy-gateway-system.svc:80
  → Envoy targetPort 10080
  → AIBrix ext_proc
  → selected mock vLLM Pod:8000
```

```bash
kubectl apply -f examples/higress-sr1/higress-to-aibrix.yaml
kubectl -n envoy-gateway-system \
  get svc,endpointslice,ingress -l app.kubernetes.io/part-of=higress-aibrix-lab
```

This alias Service is the stable entry point in the experiment. In production, you can use an Envoy Gateway customized Service, an internal VIP, or a platform-managed alias Service, but you must monitor whether the Selector still matches Endpoints and must not silently degrade to zero Endpoints.

### 12.2 OpenAI-Compatible Request Evidence

A request was sent through the Higress Gateway with model `llama2-7b` in the Body and routing policy `least-request`:

```bash
curl http://<HIGRESS_INTERNAL_ADDRESS>/v1/chat/completions \
  -H 'Host: aibrix.higress.lab' \
  -H 'Authorization: Bearer <TEST_API_KEY>' \
  -H 'Content-Type: application/json' \
  -H 'routing-strategy: least-request' \
  -d '{
    "model": "llama2-7b",
    "messages": [{"role": "user", "content": "reply pong"}],
    "max_tokens": 8
  }'
```

The measured result returned HTTP 200, model name `llama2-7b`, and 10 total Tokens. The Higress access log recorded:

```text
route_name=envoy-gateway-system/aibrix-via-higress
upstream_cluster=aibrix-gateway-upstream.envoy-gateway-system.svc.cluster.local
response_code=200
duration=57ms
upstream_service_time=56ms
```

The AIBrix Gateway Plugin recorded at the same moment:

```text
model=llama2-7b
routing_strategy=least-request
target_pod=mock-llama2-7b-...
prompt_tokens=2 completion_tokens=8 total_tokens=10
routing_time_taken=363µs total_time_taken=54.7ms
```

This proves the request passed sequentially through Higress, the AIBrix ext_proc, and the selected mock vLLM Pod. The 57ms/56ms figures are single observations from a CPU mock and are not a performance benchmark; whether production can accept the extra hop must be validated with comparative load testing using a real model, SSE, concurrency, and connection reuse.

### 12.3 Two Production Gaps Found in Testing

On the first request, internal diagnostic headers returned by AIBrix, such as `target-pod`, `target-pod-ip`, and routing latency, were passed through to the client unchanged by Higress. The experiment then added `higress.io/response-header-control-remove` to the Ingress, and these headers disappeared on subsequent requests. Higress officially supports deleting specified Headers per Route before backend responses reach the client; see [Ingress Annotation Advanced Traffic Governance](https://higress.cn/en/docs/latest/user/annotation-use-case/#response-header-control).

This boundary must also handle the request direction. AIBrix v0.7.0 reads Headers such as `user`, `external-filter`, `routing-strategy`, `config-profile`, and `x-session-id`; if public internet users can set these themselves, they could forge identity, select internal configurations, or manipulate load policies. The experiment manifest used two types of Annotations:

```yaml
higress.io/request-header-control-remove: "user,external-filter,config-profile,x-session-id,target-pod,target-pod-ip,request-id"
higress.io/request-header-control-update: "routing-strategy least-request"
higress.io/response-header-control-remove: "target-pod,target-pod-ip,routing-strategy,req-cost-time,req-arrive-time,resp-start-time,x-went-into-req-headers"
```

During re-testing, the client deliberately sent `routing-strategy: random`, forged `user`, `config-profile`, `external-filter`, and `x-session-id`, and the request still returned HTTP 200; the AIBrix log ultimately recorded `routing_strategy=least-request`, proving that external values had been overridden by platform policy. In production, the trusted `user` and tenant-level Session ID should be re-injected by Higress after authentication, rather than trusting same-named client Headers directly.

The second gap was inconsistent local Request IDs across the two layers. The AIBrix v0.7.0 source code generates a UUID when there is no tracing context, but it reads the W3C `traceparent` and uses the Trace ID within it as the internal Request ID. Therefore, there is no need to force Higress and AIBrix to have identical local Request IDs; instead, unify the cross-layer Trace Context:

```text
traceparent: 00-0123456789abcdef0123456789abcdef-0123456789abcdef-01
                 └──────────── Trace ID ────────────┘
```

In testing, AIBrix's `request_start`, `request_end`, and the returned `request-id` all became `0123456789abcdef0123456789abcdef`. Higress's default Access Log still records its own `x-request-id`; production should enable Higress OpenTelemetry Tracing and add Trace ID/`traceparent` fields to logs so that both logs and Traces can be queried by the same Trace ID. Higress supports configuring an OpenTelemetry Collector in `higress-config`; see [Higress Tracing Configuration](https://higress.cn/docs/latest/user/configmap/#tracing-配置说明).

Trace Context is only a correlation key, not an identity credential. The edge gateway should generate or validate its format; it must not grant permissions, deduplicate billing, or trust uniqueness merely because a client provided a certain Trace ID.

| Gap | Direct Risk | Priority | sr1 Status |
| --- | --- | --- | --- |
| Internal response headers leaked | Exposes Pod/IP, topology, scheduling policy, and latency | P0 before external launch | Deleted and re-tested |
| Client forges AIBrix control headers | Bypasses platform routing/identity policies, creates load skew | P0 before external launch | Cleared/overridden and re-tested |
| Request ID/Trace cannot be correlated | Faults, auditing, retries, and cost cannot be located end-to-end | P1 before scaling; P0 for strong-audit scenarios | `traceparent` verified; Collector/log fields pending integration |

## 13. Cross-Cluster Chaining with AIBrix

Higress and AIBrix can be deployed in different clusters, but AIBrix's `*.svc.cluster.local` must not be registered directly with Higress. The AIBrix cluster must first expose a stable internal entry point:

1. Internal LoadBalancer/VIP;
2. Enterprise DNS resolving to the VIP;
3. Service registry address;
4. Multi-cluster Service API or a controlled east-west gateway.

Higress then uses that address as the Upstream. The following must be verified:

- Routing, ACL, MTU, DNS, and TLS between the two clusters;
- SSE long connections, Idle Timeout, connection pools, and client cancellation;
- AIBrix Gateway multi-replica and ingress health checks;
- Circuit breaking and capacity fallback when one cluster loses connectivity;
- Cross-cluster propagation of Trace, tenant identity, and Request ID;
- Data residency and Prompt compliance boundaries.

Do not register a single Envoy Pod IP; it changes when the Pod is recreated. Cross-cluster does not necessarily require a service mesh: a stable VIP plus mTLS is often easier to operate.

## 14. The Most Common Mistakes with Two Gateway Layers

### Duplicate Retries

If the client, Higress, AIBrix, and the Runtime each retry once, the worst-case request count multiplies. Streaming responses generally cannot be safely retried after Tokens have already been output; Tool Calls can also produce duplicate side effects. Only one layer should be the authoritative executor of automatic retries, and the total budget should be limited.

### Duplicate Rate Limiting

Higress's tenant Token quota and AIBrix's model pool capacity protection are not the same concept. The former answers "can this user use it," while the latter answers "can this pool handle it right now." Define metrics and error codes separately, and do not let both layers return indistinguishable 429s.

### Inconsistent Timeouts

The total timeout from outside to inside should converge layer by layer, while separately defining connection, first-Token, streaming Idle, and total request timeouts. When the outer layer disconnects first, cancellation must be propagated to the inference engine to prevent the GPU from continuing to generate Tokens that no one consumes.

### Exposing Internal Information

AIBrix's target Pod, internal model labels, and debug headers should not be returned to the public internet by default. Higress should strip internal diagnostic headers and retain only a stable error contract for users.

## 15. Production Readiness Checklist

- [ ] Chart, four core images, and Wasm plugins all pinned to fixed versions or digests.
- [ ] `higress-sr1` is not the default IngressClass and has not taken over existing nginx routes.
- [ ] Gateway has at least two replicas with anti-affinity or topology spread constraints.
- [ ] Data plane is exposed via internal LB/VIP, not dependent on Pod IPs.
- [ ] Console is reachable only from the internal network, integrated with SSO/RBAC, and the admin password is stored in a Secret system.
- [ ] TLS certificate auto-renewal, failure alerts, and rollback have all been rehearsed.
- [ ] API Keys are not stored in plaintext in Ingress Annotations, Git, logs, or ConfigMaps.
- [ ] Buffer, Idle Timeout, Drain, and cancellation propagation for streaming requests have been verified with real clients.
- [ ] Token, concurrency, context, Body size, and cost all have tenant-level limits.
- [ ] Prompts, responses, and Tool parameters are not written to ordinary logs by default.
- [ ] Retry, rate limiting, error code, and routing responsibilities between Higress and AIBrix have exactly one authoritative source.
- [ ] AIBrix Pod/IP/routing diagnostic headers have been removed at the Higress boundary.
- [ ] Higress, AIBrix, and the Runtime use correlatable Request IDs or Trace Context.
- [ ] Gateway data plane failures do not affect the Controller, and Controller failures do not cut existing connections.
- [ ] Configuration goes through GitOps, and temporary Console changes can be detected and reverted.
- [ ] Before upgrades, old CRDs, plugin ABI, configuration conversion, and rollback paths are verified.

## 16. What This Experiment Has Not Yet Proven

Successful chaining with ordinary echo and CPU mock only proves that the two-layer gateway control flow works. The next phase still needs to add, in an isolated Namespace:

- AI Proxy to a CPU mock OpenAI-Compatible Endpoint;
- API Key, model mapping, and protocol conversion;
- Non-streaming and SSE streaming requests;
- Token statistics, TTFT, and Prometheus scraping;
- Tenant Token rate limiting and error semantics;
- Ingress behavior during AIBrix failures, timeouts, cancellations, and scaling events;
- Internal VIP, TLS, SSO, and multi-replica high availability.

Control plane readiness and plain HTTP 200 responses cannot substitute for performance, security, and fault testing of the real model data plane.

## Further Reading

- [Higress Official Documentation](https://higress.io/en/)
- [Higress Helm Deployment](https://higress.cn/docs/latest/ops/deploy-by-helm/)
- [Higress AI Gateway](https://higress.io/en/ai-gateway)
- [Higress AI Proxy](https://higress.io/en/docs/latest/plugins/ai/api-provider/ai-proxy/)
- [Higress AI Statistics](https://higress.io/en/docs/latest/plugins/ai/api-o11y/ai-statistics/)
- [AIBrix Existing Cluster Practice](../practices/aibrix-existing-cluster.md)
- [AI Gateway and Intelligent Routing](gateway-routing.md)
