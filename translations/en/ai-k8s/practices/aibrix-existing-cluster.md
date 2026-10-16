---
title: "Deploying AIBrix on an Existing Kubernetes Cluster: Routing, P/D, Autoscaling, and Observability Field Test"
description: "Install AIBrix v0.7.0 on a Kubernetes 1.30 cluster, use CPU mock to validate model routing, P/D, StormService, autoscaling, Prometheus metrics, and Higress two-layer gateway chaining"
status: lab
last_reviewed: 2026-08-06
---

# Deploying AIBrix on an Existing Kubernetes Cluster: Routing, P/D, Autoscaling, and Observability Field Test

This experiment did not run the Quickstart on a clean Kind cluster. Instead, it incrementally installed AIBrix into a Kubernetes cluster already running databases, virtual machines, storage, and other controllers. The goal was to answer six questions:

1. Which AIBrix version fits the existing Kubernetes version;
2. When the external Registry is unstable, how to fully prepare dependent images in advance;
3. Without allocatable GPUs, can the AIBrix control plane and model-aware routing still be validated;
4. Can the CPU demo be used to observe the two resource abstractions, StormService/RoleSet and KVCache;
5. Without GPUs, how far can KPA, APA, native HPA, and Prometheus custom metrics be tested;
6. When the business entry point uses Higress, how should Higress and the AIBrix Gateway divide responsibilities.

Final validation results: all six control-plane Deployments of AIBrix v0.7.0, the Envoy Gateway control plane, and the data plane were Ready; two mock vLLM replicas ran on different nodes; ordinary model routing, role-based filtering, Session Affinity, P/D control flow, and error semantics all produced actual response evidence. After installing Metrics Server as a supplement, KPA, APA, resource-based HPA, and Prometheus custom-metrics HPA all triggered real scaling; a minimal Prometheus Operator, Prometheus, and Adapter also collected and exposed vLLM metrics. Later, the same cluster also ran Higress → AIBrix → mock vLLM end to end, and boundary response header stripping was verified.

```text
测试客户端
  → Envoy Gateway
  → AIBrix ext_proc Gateway Plugin
  → 按 model + routing-strategy 选择 Pod
  → mock vLLM 副本
  → OpenAI-Compatible 响应
```

This article writes the internal company Registry, domain names, and addresses as `<...>` placeholders. Do not copy experimental API keys, internal addresses, or floating labels directly into production.

This article mainly records CPU mock and control-plane validation. For subsequent field tests with real NVIDIA GPUs, two-machine model parallelism with Ray, NIXL P/D KV Cache transfer, and running a 235B FP8 model on eight nodes of fragmented GPUs, see: [AIBrix Real GPU Field Test: From Two-Machine Inference to Eight-Node Fragmented GPUs](aibrix-gpu-multinode-pd-production.md).

## 1. Inventory the Cluster First; Do Not Run Quickstart Directly

First, collect the version, node resources, and existing CRDs:

```bash
kubectl config current-context
kubectl version
kubectl get nodes -o wide
kubectl get nodes \
  -o custom-columns='NAME:.metadata.name,GPU:.status.allocatable.nvidia\.com/gpu'
kubectl get crd | grep -E 'gateway|envoy|ray|aibrix'
kubectl get deploy,ds -A | grep -Ei 'gateway|envoy|ray|gpu|device-plugin'
kubectl get storageclass
```

The key facts about this target cluster are as follows:

| Item | Actual State | Impact on Installation |
| --- | --- | --- |
| Kubernetes Server | v1.30.4 | Can run the Envoy Gateway v1.2 series pinned by AIBrix v0.7.0 |
| Container Runtime | containerd 1.7.x | No special restrictions, but nodes must be able to reach the image Registry |
| Gateway API | Not installed | The AIBrix dependency manifest must be installed first |
| Envoy Gateway | Not installed | AIBrix model-aware routing depends on it; installing only the AIBrix Controller is not sufficient |
| KubeRay CRD | Not installed | The official dependency will install it; if AIBrix does not use Ray, Ray workloads need not be deployed |
| `nvidia.com/gpu` | Not published on any node | Cannot claim real GPU inference has been validated; first use the CPU mock Runtime to validate the control plane |
| LoadBalancer Controller | Has not assigned an address to the Envoy Service | The Gateway Listener can work, but the external entry point requires ClusterIP, an internal LB/VIP, or port forwarding |
| Metrics API | Initially absent; installed during the experiment | Source of CPU/memory data for resource HPA and APA |
| Prometheus Operator CRD | Initially absent; minimal stack installed during the experiment | Provides declarative monitoring resources such as ServiceMonitor and PrometheusRule |
| Custom Metrics API | Initially absent; Adapter installed during the experiment | Allows native HPA to use vLLM metrics such as `gpu_cache_usage_perc` |

"Nodes may physically have GPUs" and "Kubernetes can already allocate GPUs" are two different things. Only when the node `status.allocatable` shows `nvidia.com/gpu` or the target DRA ResourceClaim can be allocated can you proceed to deploy a real GPU vLLM.

## 2. Why AIBrix v0.7.0 Was Chosen

At installation time, the latest stable version queried was v0.7.0, released on 2026-06-18. The official release provides three separate assets:

- `aibrix-dependency-v0.7.0.yaml`: dependencies such as Gateway API, Envoy Gateway, and KubeRay CRDs;
- `aibrix-core-crds-v0.7.0.yaml`: AIBrix's own CRDs;
- `aibrix-core-v0.7.0.yaml`: Controller, Gateway Plugin, Metadata, Redis, and default Gateway resources.

This version pins Envoy Gateway v1.2.8. The Envoy Gateway v1.2 compatibility matrix covers Kubernetes 1.28–1.31, so Kubernetes 1.30 is within the compatible range. However, v1.2 has already ended upstream maintenance, and production environments must not arbitrarily upgrade only Envoy Gateway to a newer version: AIBrix uses `EnvoyExtensionPolicy`, `EnvoyPatchPolicy`, and a custom Envoy image, so AIBrix, Envoy Gateway, Gateway API CRDs, and Envoy Proxy must be regression-tested as a single group.

References: [AIBrix Installation](https://aibrix.readthedocs.io/latest/getting_started/installation/installation.html), [AIBrix Releases](https://github.com/vllm-project/aibrix/releases), [Envoy Gateway Compatibility Matrix](https://gateway.envoyproxy.io/news/releases/matrix/)

## 3. Prepare the Complete Image Set First, Rather Than Waiting for Pods to Fail One by One

The official v0.7.0 default installation involves at least the following images:

| Component | Upstream Image |
| --- | --- |
| AIBrix Controller | `aibrix/controller-manager:v0.7.0` |
| Gateway Plugin | `aibrix/gateway-plugins:v0.7.0` |
| Metadata/GPU Optimizer | `aibrix/metadata-service:v0.7.0` |
| KubeRay Operator | `aibrix/kuberay-operator:v1.2.1-patch-20250726` |
| Envoy Gateway | `envoyproxy/gateway:v1.2.8` |
| Envoy data plane | `envoyproxy/envoy:v1.33.2` |
| Initialization and state storage | `busybox:stable`, `redis:latest` |
| GPU-less validation Runtime | `aibrix/vllm-mock:nightly` |

If the cluster cannot reliably reach Docker Hub, unify the images before installation. The cluster nodes are amd64, but the computer preparing the images may be Apple Silicon, so `linux/amd64` must be explicitly pulled:

```bash
docker pull --platform linux/amd64 aibrix/controller-manager:v0.7.0
docker pull --platform linux/amd64 aibrix/gateway-plugins:v0.7.0
docker pull --platform linux/amd64 aibrix/metadata-service:v0.7.0
docker pull --platform linux/amd64 aibrix/kuberay-operator:v1.2.1-patch-20250726
docker pull --platform linux/amd64 envoyproxy/gateway:v1.2.8
docker pull --platform linux/amd64 envoyproxy/envoy:v1.33.2
docker pull --platform linux/amd64 busybox:stable
docker pull --platform linux/amd64 redis:latest
docker pull --platform linux/amd64 aibrix/vllm-mock:nightly
```

Then retag and push each one:

```bash
docker tag aibrix/controller-manager:v0.7.0 \
  <INTERNAL_REGISTRY>/aibrix-controller-manager:v0.7.0
docker push <INTERNAL_REGISTRY>/aibrix-controller-manager:v0.7.0
```

Use the same process for the remaining images. After pushing, replace all `image:` occurrences in both installation manifests, and rescan to confirm nothing was missed:

```bash
grep -n 'image:' aibrix-dependency-v0.7.0.yaml
grep -n 'image:' aibrix-core-v0.7.0.yaml
```

There are three common pitfalls here:

1. Replacing only the AIBrix Deployment images is not enough; the `EnvoyProxy` custom resource also declares the Envoy and shutdown-manager images used to dynamically create the data plane;
2. The Certgen Job and the Envoy Gateway Deployment share the Envoy Gateway image;
3. The official manifests use `redis:latest` and mock `nightly`; the experiment can keep them consistent, but production should pin digests after validation to avoid getting different content on rebuild.

## 4. Install Strictly in Dependency Order

First download the pinned release assets:

```bash
curl -fLO https://github.com/vllm-project/aibrix/releases/download/v0.7.0/aibrix-dependency-v0.7.0.yaml
curl -fLO https://github.com/vllm-project/aibrix/releases/download/v0.7.0/aibrix-core-crds-v0.7.0.yaml
curl -fLO https://github.com/vllm-project/aibrix/releases/download/v0.7.0/aibrix-core-v0.7.0.yaml
```

After completing image replacement, execute in the following order:

```bash
kubectl apply --server-side -f aibrix-dependency-v0.7.0.yaml

kubectl -n envoy-gateway-system \
  rollout status deployment/envoy-gateway --timeout=180s
kubectl -n envoy-gateway-system \
  wait --for=condition=complete job/eg-gateway-helm-certgen --timeout=180s

kubectl apply --server-side -f aibrix-core-crds-v0.7.0.yaml
kubectl wait --for=condition=Established \
  crd/stormservices.orchestration.aibrix.ai \
  crd/modeladapters.model.aibrix.ai \
  crd/podautoscalers.autoscaling.aibrix.ai \
  --timeout=120s

kubectl apply -f aibrix-core-v0.7.0.yaml
kubectl -n aibrix-system rollout status deployment --timeout=300s
```

If all three manifests are applied together with `--dry-run=server`, later objects may report that the Namespace or CRD does not exist. The reason is that dry-run does not actually persist the previous manifest; it does not mean the API is incompatible. The reliable approach is to actually install the dependencies and CRDs first, confirm `Established=True`, and only then preflight or install Core.

### 4.1 Resources and Service Override on a Single-Node k3s

When re-validating on another single-node k3s v1.36.2+k3s1 environment, the node had 28 cores and approximately 31 GiB of allocatable memory, but no `nvidia.com/gpu`. In the official manifests, the Gateway Plugin and Envoy data plane each request 2 CPU / 8 GiB; after adding the existing KubeVirt, storage, and business Pods, the node's memory requests approached 100%, and the Higress Gateway could not be scheduled. For CPU control-plane experiments, you can temporarily lower the requests, but production capacity must not copy this configuration:

```bash
kubectl -n aibrix-system patch deployment aibrix-gateway-plugins \
  --type=strategic \
  --patch-file examples/aibrix-sr1/k3s-lab-gateway-plugin-strategic-patch.yaml

kubectl -n aibrix-system patch envoyproxy aibrix-custom-proxy-config \
  --type=merge \
  --patch-file examples/aibrix-sr1/k3s-lab-envoyproxy-merge-patch.yaml

kubectl -n aibrix-system rollout status deployment/aibrix-gateway-plugins
kubectl -n envoy-gateway-system rollout status \
  deployment/envoy-aibrix-system-aibrix-eg-903790dc
kubectl -n aibrix-system wait --for=condition=Programmed \
  gateway/aibrix-eg --timeout=120s
```

The second patch also changed the Envoy Service from `LoadBalancer` to `ClusterIP`. On single-node k3s without MetalLB or a cloud load balancer, the default Service will keep waiting for an external address, and K3s ServiceLB may fail to become Ready because port 80 is already occupied; ClusterIP is sufficient to support same-cluster Higress chaining and `port-forward` testing, and lets the Gateway obtain an address and enter `Programmed=True`. When access from outside the cluster is needed, configure MetalLB/internal VIP, NodePort, or a controlled ingress separately; ClusterIP must not be treated as a public-facing solution.

This k3s cluster already had newer Gateway API CRDs, and the `BackendTLSPolicy` and `TLSRoute` `status.storedVersions` include `v1`. Do not forcibly downgrade these two CRDs just to fit the AIBrix dependency manifest; keep the existing storable versions and confirm that Envoy Gateway, Gateway, HTTPRoute, and AIBrix extension policies all reconcile normally. The served/storage versions of CRDs belong to the cluster-level compatibility surface; back up and inspect existing objects before handling them.

## 5. What You Should See After Installation

The AIBrix v0.7.0 default control plane includes:

```text
aibrix-system
  aibrix-controller-manager
  aibrix-gateway-plugins
  aibrix-gpu-optimizer
  aibrix-kuberay-operator
  aibrix-metadata-service
  aibrix-redis-master

envoy-gateway-system
  envoy-gateway
  envoy-<namespace>-<gateway>-<hash>
```

When checking, do not look only at Pods:

```bash
kubectl -n aibrix-system get deploy,pod,svc
kubectl get gatewayclass aibrix-eg -o yaml
kubectl -n aibrix-system \
  get gateways.gateway.networking.k8s.io,httproutes.gateway.networking.k8s.io
kubectl -n envoy-gateway-system get deploy,pod,svc
```

When other CRDs named `Gateway` exist in the cluster, `kubectl get gateway` may resolve to the wrong API Group. During troubleshooting, use the full resource name `gateways.gateway.networking.k8s.io` to avoid confusing Gateway API objects with cloud resource CRDs.

## 6. Without GPUs, You Can Still Prove AIBrix Routing Works

This time, two CPU mock vLLM replicas were used; the Manifest is at [`examples/aibrix-sr1/mock-llama2-7b.yaml`](https://github.com/runzhliu/aik8s/blob/main/examples/aibrix-sr1/mock-llama2-7b.yaml). The core constraints are:

```yaml
metadata:
  labels:
    model.aibrix.ai/name: llama2-7b
    model.aibrix.ai/port: "8000"
spec:
  template:
    metadata:
      labels:
        model.aibrix.ai/name: llama2-7b
        model.aibrix.ai/port: "8000"
```

The Service name, the `model` in the request body, and `model.aibrix.ai/name` should remain consistent. The port label must be written on the Pod Template; if written only at the Deployment top level, AIBrix will fall back to 8000 and produce a warning.

```bash
kubectl apply -f examples/aibrix-sr1/mock-llama2-7b.yaml
kubectl -n aibrix-demo rollout status deployment/mock-llama2-7b
kubectl -n aibrix-demo get pods,svc,endpoints -o wide
kubectl -n aibrix-system get httproutes.gateway.networking.k8s.io
```

The Controller will generate the corresponding HTTPRoute for the discovered model. During testing, temporarily forward the Envoy data-plane Service:

```bash
kubectl -n envoy-gateway-system get svc
kubectl -n envoy-gateway-system port-forward \
  svc/<AIBRIX_ENVOY_SERVICE> 28999:80
```

Send the request from another terminal:

```bash
curl -i http://127.0.0.1:28999/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer test-key-1234567890' \
  -H 'routing-strategy: least-request' \
  --data '{
    "model": "llama2-7b",
    "messages": [{"role": "user", "content": "Say this is an AIBrix test"}],
    "temperature": 0.1
  }'
```

This field test returned:

```text
HTTP/1.1 200 OK
routing-strategy: least-request
target-pod: mock-llama2-7b-...
target-pod-ip: <pod-ip>:8000
request-id: <uuid>
```

The Gateway Plugin logs simultaneously record the model name, target Pod, routing latency, input/output Tokens, and total latency, forming a complete evidence chain.

### 6.1 Do Not Test Only One Routing Strategy

The following request headers were actually tested against the same set of CPU mock backends. Except for the error cases, all requests returned HTTP 200:

| `routing-strategy` | Field Test Result | What the CPU Environment Can Prove |
| --- | --- | --- |
| `random` | Success | The policy is accepted by the plugin and backend selection completes |
| `least-request` | Success | Can traverse the least-requests selection path |
| `power-of-two` | Success | Can perform a one-of-two selection from the candidate set |
| `least-latency` | Success | Can read and participate in the latency statistics path |
| `throughput` | Success | Can enter the throughput-aware policy |
| `prefix-cache` | Success | The Prefix routing code path is usable; the mock cannot prove real KV hits |
| `external-filter` | `role=prefill/decode` precisely selected the corresponding Role | Metadata filtering and StormService Role labels take effect |
| `session-affinity` | After replaying `x-session-id` in the response, the request landed on the same Pod | The session stickiness closed loop takes effect |
| `pd` | Both Prefill and Decode targets were recorded simultaneously | The P/D orchestration control flow takes effect |

For `prefix-cache`, the first two consecutive requests hit the same Pod, and the third request switched Pods. This is not an error, and the Prefix hit rate cannot be calculated from it: the mock Runtime has no real KV Blocks, model context, or cache events. To prove the benefits of Prefix routing, you must switch to a real inference engine and simultaneously observe hits, TTFT, input Tokens, and cache capacity.

### 6.2 For P/D Routing, Look at Both Segment Targets and Plugin Logs

After sending `aibrix-role-demo` to `routing-strategy: pd`, the response contains both a Decode target and `prefill-target-pod`. The Gateway Plugin logs the following in sequence:

```text
selected prefill/decode pair
prefill request start/end
prefill_time_taken
kv_transfer_time_taken
ttft
decode_time_taken
```

This proves that the request traversed the Prefill, simulated KV transfer, and Decode control flow, but `kv_transfer_time_taken` is only the phase latency of the mock protocol; it does not mean that GPU KV Tensors were actually transferred over NIXL, RDMA, or TCP.

Failure semantics should also be included in acceptance criteria: a nonexistent model and a request body missing the model both return HTTP 400 with `x-error-no-model-backends`; an invalid routing policy returns HTTP 400 with `x-error-routing: true`. Production gateways can use this to distinguish between "capacity temporarily unavailable" and "client request error," and must not retry all 4xx/5xx responses.

## 7. Can AIBrix deploy Prefill, Decode, and KV Cache by role

Yes, but two resource models must be distinguished:

- `StormService → RoleSet → Pod` describes roles within an inference service, such as Prefill and Decode;
- The `KVCache` CRD describes an independent cache layer, including metadata, member discovery, and the cache nodes that actually store KV Blocks.

They can be used in combination, but KV Cache is not simply a matter of adding an `StormService` role inside `cache`.

### 7.1 Prefill and Decode are both inference Pods

AIBrix's `StormService` can define multiple Roles within a single service unit. A typical P/D separation service includes:

```yaml
apiVersion: orchestration.aibrix.ai/v1alpha1
kind: StormService
spec:
  replicas: 1
  template:
    spec:
      roles:
        - name: prefill
          replicas: 1
          template: <vLLM Prefill PodTemplate>
        - name: decode
          replicas: 1
          template: <vLLM Decode PodTemplate>
```

Prefill Pods are responsible for processing Prompts and generating initial KV; Decode Pods receive the KV and continue generating token by token. Both types of Pods run the model and typically both require GPUs. The vLLM 1P1D example in AIBrix v0.7.0 uses the NIXL Connector to transfer KV between the two types of inference processes; it does not require deploying an independent cache cluster that persistently stores KV.

This is not the same layer of concept as Ray multi-node: in an ordinary RayCluster, Head/Worker jointly execute the Prefill and Decode of the same Engine and do not separately play P/D roles. If the model itself must span nodes, the Prefill Engine and Decode Engine can each run on their own set of multi-node resources, but this simultaneously introduces intra-group model parallelism and inter-group KV transfer. See [What is the relationship between vLLM Ray multi-node and P/D separation](../inference/distributed-serving.md#vllm-ray-vs-pd) for the complete data path.

With `StormService.spec.replicas > 1`, each RoleSet can be scaled as a complete service replica by group; with `spec.replicas = 1`, the Roles form a shared pool. AIBrix v0.7.0 already provides a shared-pool role-level autoscaling example: create `PodAutoscaler` pointing to the same StormService, then use `subTargetSelector.roleName` to select Prefill or Decode, and add the `autoscaling.aibrix.ai/storm-service-mode: pool` annotation. Production environments must still validate scaling, warm-up, P/D capacity ratios, and request draining during scale-down with real metrics; it is not enough that the CRD can express them.

If the service already uses Ray internally, `RayClusterFleet` can be used instead: each RayCluster is a complete replica, Ray handles intra-cluster process scheduling, and AIBrix only routes requests to the Head/API Pod. The boundary between the two routes needs to be clarified separately.

### 7.2 Two AIBrix orchestration routes: RayClusterFleet and StormService/RoleSet { #rayclusterfleet-vs-stormservice }

`StormService` and `RoleSet` are not two peer-level options. The real either/or choice is **RayClusterFleet versus StormService**; RoleSet is the next-level resource managed by StormService:

```text
Ray 路线
RayClusterFleet（类似 Deployment）
  └─ RayClusterReplicaSet（类似 ReplicaSet）
       └─ RayCluster × N（每个都是完整推理副本）
            ├─ Ray Head / vLLM API
            └─ Ray Worker × M

Role 路线
StormService（整个推理服务）
  └─ RoleSet × N（完整副本或共享池）
       ├─ Role: prefill → Pod / 多 Pod Group
       ├─ Role: decode  → Pod / 多 Pod Group
       └─ Role: 其他自定义角色
```

| Dimension | RayClusterFleet | StormService / RoleSet |
| --- | --- | --- |
| Core abstraction | One application instance is one complete RayCluster | One service consists of one or more named Roles |
| Internal orchestration | Ray handles distributed processes, Actor/Task, and resource scheduling; KubeRay handles Head/Worker Pods | AIBrix Controller directly manages Roles, Pods, indexes, status, and update order; the Runtime handles distributed process communication itself |
| Dependencies | Requires KubeRay and Ray prepared in the image | Does not depend on KubeRay; the AIBrix v0.7.0 installation documentation explicitly allows using only StormService |
| Typical topology | Fixed Ray Head + one or more Worker Groups | Prefill/Decode, homogeneous Workers, proxies, or any other role; a single Role can also express multi-node instances with `podGroupSize > 1` |
| External Endpoint | Only exposes the vLLM API on the Ray Head; Workers cannot enter the Gateway Endpoint | Colocated mode exposes the service Role; P/D mode lets AIBrix select Prefill/Decode by Role and RoleSet |
| Scaling unit | `spec.replicas` adds or removes complete RayClusters, i.e., complete model replicas | Replica mode adds or removes complete RoleSets; Pool mode can scale Prefill/Decode Pods separately via `roleName` |
| Updates | Deployment-style RollingUpdate/Recreate, Revision, and rollback; the update unit is the RayCluster | StormService supports Rolling/InPlace; RoleSet supports Parallel, Sequential, and Interleave, and can declare `upgradeOrder` |
| State and failure boundary | KubeRay repairs Head/Worker within a Cluster; Fleet aggregates complete RayCluster replica status | RoleSet aggregates the Ready status of each Role; Stateful Roles retain stable Slots, Stateless Roles are interchangeable |
| Scheduling capability | Primarily relies on Kubernetes/KubeRay; Gang and topology constraints for the full GPU group must be validated separately | RoleSet can reference Volcano, Coscheduling, or Godel PodGroup policies, but the cluster must still have the corresponding scheduler installed |
| Best suited for | Teams already using Ray, or vLLM started with the Ray Backend; want to reuse Ray Dashboard, tasks, and cluster models | P/D separation, heterogeneous roles/independent scaling, wanting to remove Ray, or wanting the platform to directly understand role boundaries |

Three configurations best illustrate the scaling semantics:

1. `RayClusterFleet.replicas=2`, each RayCluster contains 1 Head + 1 Worker: yields two complete model replicas, and AIBrix only routes between the two Head Endpoints;
2. `StormService.replicas=2`, each RoleSet contains 2 Prefill + 1 Decode: yields two mutually isolated complete P/D replicas, and one scale-out adds the entire RoleSet;
3. `StormService.replicas=1`, with Prefill=4 and Decode=8 in the RoleSet: yields one shared P/D Pool, and `PodAutoscaler` can be created separately for the two Roles, scaled independently via `subTargetSelector.roleName`.

Therefore, **a model spanning nodes does not mean RayClusterFleet is required**. If the team already runs vLLM with Ray, RayClusterFleet requires the least change; if the goal is AIBrix-native P/D, role-level elasticity, or avoiding Ray, StormService is the priority.

References: [AIBrix Installation](https://aibrix.readthedocs.io/latest/getting_started/installation/installation.html), [AIBrix Multi-Node Inference](https://aibrix.readthedocs.io/latest/features/multi-node-inference.html), [AIBrix StormService](https://aibrix.readthedocs.io/latest/designs/aibrix-stormservice.html), [StormService Role-Level Autoscaling](https://aibrix.readthedocs.io/latest/features/autoscaling/metric-based-autoscaling.html#stormservice-role-level-autoscaling)

### 7.3 Can multiple 8-GPU Pods started with bare Kubernetes replace them

They can produce the same **inference data plane**, but will not automatically provide the same **operations control plane**. Several Pods requesting `nvidia.com/gpu: 8` can each run a complete model, can form a cross-Pod model, or can even be manually split into Prefill and Decode pools. But running `sleep infinity` and then starting processes with `kubectl exec` is only suitable for debugging: the commands are lost after Pod recreation, and Kubernetes does not know which Pods belong to the same complete replica.

| Goal | Minimal viable approach | Gap versus AIBrix abstractions |
| --- | --- | --- |
| Model fits in a single 8-GPU Pod, multiple replicas | `Deployment + Service`, each Pod starts one vLLM, `replicas=N` | Sufficient for ordinary colocated models; lacks Fleet-level Revision/rollback and role semantics |
| One model spans multiple 8-GPU Pods | `StatefulSet + Headless Service + Leader Service`, determine Rank from stable ordinal | Must handle group start/stop, readiness, Gang Scheduling, group failure, and Leader-only Endpoint yourself |
| Manual Ray cluster | Head Pod runs `ray start --head`, Worker Pods run `ray start --address=...`, then start vLLM on the Head | Obtains a Ray runtime, but without KubeRay's RayCluster coordination, and without Fleet's multi-complete-replica management |
| Manual P/D separation | Prefill and Decode each have their own Workload/Service, configured with NIXL/KV Connector and P/D Router | Labels alone do not transfer KV; pairing, independent scaling, request draining, and failure degradation must be handled yourself |

For a static cross-Pod experiment, a minimal skeleton can be:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: vllm-headless
spec:
  clusterIP: None
  selector:
    app: vllm-multinode
  ports:
    - {name: control, port: 29500}
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: vllm
spec:
  serviceName: vllm-headless
  podManagementPolicy: Parallel
  replicas: 2
  selector:
    matchLabels: {app: vllm-multinode}
  template:
    metadata:
      labels: {app: vllm-multinode}
    spec:
      containers:
        - name: vllm
          image: <预装模型、vLLM 和通信依赖的镜像>
          command: ["/opt/aik8s/start-vllm-rank.sh"]
          env:
            - {name: WORLD_SIZE, value: "2"}
            - {name: MASTER_ADDR, value: vllm-0.vllm-headless}
          resources:
            requests:
              nvidia.com/gpu: 8
            limits:
              nvidia.com/gpu: 8
```

`start-vllm-rank.sh` must derive `node-rank` from the ordinal in the Pod name, starting the API/Leader for Rank 0 and Headless Workers for other Ranks. If Ray is chosen, start Ray Head/Worker instead and launch vLLM on the Head. The external Service can only select Rank 0, for example by filtering with `statefulset.kubernetes.io/pod-name: vllm-0`; Readiness must only succeed after all Ranks have joined and the model is servable.

To approach production readiness, the following must also be completed yourself:

- Stop using `sleep + exec`; bake the startup logic into the image EntryPoint or a versioned ConfigMap;
- Design Group ID, Rank, stable DNS, Leader-only Service, and whole-group Readiness for complete replicas;
- Introduce Gang Scheduling such as Volcano/Coscheduling to avoid occupying only some GPU Pods for long periods;
- Configure GPU/RDMA resources, topology affinity, NCCL/NIXL networking, and consistent model paths;
- Implement whole-group restart, rolling updates, scale-down draining, autoscaling, failure removal, and observability.

For selection, when **a single Pod with 8 GPUs is itself a complete replica**, a native Deployment is often the simplest, and letting AIBrix discover it via `model.aibrix.ai/name` and `model.aibrix.ai/port` is sufficient. When **one replica must span multiple 8-GPU Pods**, use at least one of LWS, RayClusterFleet, or StormService/RoleSet; if you insist on native Workloads only, you are effectively taking on the design and operations work of a small Operator yourself.

References: [vLLM Multi-Node Serving](https://docs.vllm.ai/en/latest/examples/ray_serving/multi-node-serving/), [vLLM on LeaderWorkerSet](https://docs.vllm.ai/en/latest/deployment/frameworks/lws/), [vLLM Parallelism and Scaling](https://docs.vllm.ai/en/latest/serving/parallelism_scaling/)

#### When practicing P/D and KV Cache yourself, the core is still the vLLM data path

For the current technology stack in this article, the answer is **yes**: it is still vLLM that actually executes the model, generates KV Tensors, and moves KV through Connectors. AIBrix is not another inference engine; it brings the same data path into Kubernetes service discovery, role orchestration, request routing, and scaling.

| Layer | Assembled yourself | After adding AIBrix |
| --- | --- | --- |
| Inference engine | vLLM Prefill/Decode processes | Still vLLM, or another engine supported by AIBrix |
| KV transfer | vLLM Connectors such as `NixlConnector` | Still the version-matched Connector and NIXL/UCX data plane |
| P/D pairing and routing | vLLM example Proxy or a Router you write yourself | AIBrix Gateway selects Prefill/Decode based on RoleSet, load, and cache signals |
| Workload orchestration | Deployment/StatefulSet, Service, and startup scripts | StormService/RoleSet or RayClusterFleet |
| KV storage | vLLM local HBM/CPU, or an independent Backend such as LMCache | AIBrix Offloading Connector + L1 DRAM, optionally an L2 Backend managed by the `KVCache` CR |
| Physical data plane | TCP, or NIXL + UCX/RDMA | Unchanged; AIBrix CRDs will not automatically turn a slow network into RDMA |

Three goals must be distinguished:

1. **P/D direct transfer**: the same request first enters Prefill, and the computed KV is then passed to Decode. This does not require an independent cache cluster that persistently stores KV.
2. **KV Offload**: moving KV that would normally remain in GPU HBM to local CPU DRAM, SSD, or remote storage, primarily to expand capacity or free HBM.
3. **Cross-engine KV sharing**: different vLLM replicas reuse the same prefix through a shared L2 Backend. This is what requires metadata, a Cache Engine, capacity governance, and hit/miss-origin logic.

A verifiable experimental sequence that is also easy to troubleshoot is:

1. **Single colocated vLLM baseline**: Fix the model, image, TP, context length, and request set; record TTFT, TPOT, throughput, and HBM.
2. **Bare vLLM 1P1D**: Deploy one Prefill Pod and one Decode Pod, using exactly matching vLLM/NIXL/UCX images on both ends and `--kv-transfer-config`, first over TCP, then switch to RDMA.
3. **Add a minimal Proxy**: First use the official vLLM `disagg_proxy_demo.py`, have it call Prefill, pass `kv_transfer_params`, then call Decode. This step proves the P/D data plane and is independent of AIBrix.
4. **Replace the Proxy with the AIBrix Gateway**: Put the same two engines into a StormService/RoleSet, and send requests using `routing-strategy: pd`. Compare request pairing, failure removal, and role-independent scaling.
5. **Then do L1 KV Offload**: Offload KV only to local CPU DRAM, and verify HBM release, PCIe overhead, and end-to-end latency.
6. **Finally add shared L2 KVCache**: Use the AIBrix `KVCache` CR to create an InfiniStore/Vineyard backend, and enable the corresponding Offloading Connector in real vLLM. Use repeated long system prompts to verify cross-replica hits, then test whether fallback recomputation works when the backend is interrupted.

The bare vLLM P/D command form is roughly as follows and should be placed in the Pod's `command/args` rather than manually `exec`:

```bash
# Prefill
vllm serve <MODEL> --port 8100 \
  --kv-transfer-config \
  '{"kv_connector":"NixlConnector","kv_role":"kv_producer"}'

# Decode
vllm serve <MODEL> --port 8200 \
  --kv-transfer-config \
  '{"kv_connector":"NixlConnector","kv_role":"kv_consumer"}'

# 实验用 P/D Router
python examples/disaggregated/disaggregated_serving/disagg_proxy_demo.py \
  --model <MODEL> --prefill prefill:8100 --decode decode:8200 --port 8000
```

This snippet is used to illustrate component boundaries and should not be copied into production without the image version. The vLLM Connector parameters and the P/D protocol are still evolving; the specific images in the AIBrix official examples may also require both ends to use `kv_role=kv_both`. **AIBrix, vLLM, AIBrix KVCache Connector, NIXL, UCX/CUDA/PyTorch** must be locked as a validated version combination, not each chased to its latest separately.

Acceptance is not just about whether the Pod `Running` or the request returns; at minimum you must also prove: Prefill really only does the prompt phase, Decode really receives the remote KV, the second request with the same long prefix shows an observable hit, and disabling the Connector/cache backend produces the expected performance regression or recomputation.

For the boundaries of P/D direct transfer, KV offload, prefix-cache-aware routing, and cross-engine shared KV, as well as the selection comparison among Mooncake, AIBrix, LMCache/llm-d, and Dynamo KVBM, see: [DeepSeek V4 Flash's Distributed KV Cache](distributed-kv-cache-deepseek-v4.md).

References: [vLLM Disaggregated Serving](https://docs.vllm.ai/en/stable/examples/disaggregated/disaggregated_serving/), [vLLM NixlConnector Usage Guide](https://docs.vllm.ai/en/stable/features/nixl_connector_usage/), [vLLM KV Offloading Usage Guide](https://docs.vllm.ai/en/latest/features/kv_offloading_usage/), [AIBrix Prefill-Decode Disaggregation](https://aibrix.readthedocs.io/latest/features/pd-disaggregation.html), [AIBrix KVCache Offloading Framework](https://aibrix.readthedocs.io/latest/designs/aibrix-kvcache-offloading-framework.html)

### 7.4 An Independent KV Cache Cluster Is Not Just One "Management Pod"

If you want to further offload KV from GPU HBM or single-machine memory to a shared L2 cache, AIBrix uses an independent `KVCache` CR. Taking the InfiniStore backend as an example, it typically includes:

| Component | Runs Model | Stores Actual KV Blocks | Responsibility |
| --- | --- | --- | --- |
| AIBrix Controller | No | No | Reconciles the `KVCache` CR into resources such as Deployments and Services |
| Metadata Redis/Etcd | No | No | Stores metadata such as membership, index, and location; does not store large KV tensors |
| Watcher | No | No | Registers and discovers cache members, maintains cache cluster topology |
| Cache Engine Pod | No | Yes | Actually stores and reads KV Blocks in CPU memory or remote media |
| Prefill Pod | Yes | Generates KV | Executes prompt computation, writes or transfers KV through the Connector |
| Decode Pod | Yes | Consumes and extends KV | Reads existing KV and continues token generation |

The corresponding resource form is roughly as follows:

```yaml
apiVersion: orchestration.aibrix.ai/v1alpha1
kind: KVCache
spec:
  mode: distributed
  metadata:
    redis:
      runtime:
        replicas: 1
        image: <redis-image>
  watcher:
    image: <kvcache-watcher-image>
  cache:
    replicas: 3
    image: <cache-engine-image>
    resources:
      requests:
        cpu: "10"
        memory: 120Gi
        <rdma-resource>: "1"
```

Inference Pods communicate with the cache layer through the AIBrix Offloading Connector. The data path can be summarized as:

```text
客户端
  → AIBrix Gateway
  → Prefill / Decode 推理 Pod（StormService / RoleSet）
       ↕ AIBrix Offloading Connector
     L1：推理节点 CPU DRAM
       ↕
     L2：分布式 KVCache
       ├─ Redis / Etcd：元数据和位置索引
       ├─ Watcher：成员注册与发现
       └─ Cache Engine Pod × N：保存实际 KV Block
```

The `aibrix-redis-master` generated by this installation is the Redis used by the AIBrix platform control plane. Its existence does not mean the distributed KV data plane has been deployed; the `KVCache` CR will also create its own metadata and cache workloads according to the backend and configuration.

### 7.5 How to Choose Among the Three Modes

| Mode | Composition | Applicable Scenario | Main Cost |
| --- | --- | --- | --- |
| Local KV | Inference engine HBM, optional single-machine L1 DRAM | Get it running first, low complexity, low reuse rate | Capacity limited by a single machine; no sharing across replicas |
| P/D direct transfer | Prefill Role + Decode Role + NIXL/RDMA transport | Resource characteristics of prompt and generation phases differ significantly | Network, connector, and failure recovery are more complex |
| Independent L2 KVCache | Inference pool + Metadata + Watcher + Cache Engine | Long shared prefixes, cross-replica hits, need to expand cache capacity | Consumes large amounts of CPU memory/network; requires consistency, capacity, and degradation governance |

"KVCache deployed" cannot be directly equated with "throughput will definitely improve." L2 cache is worthwhile only when the hit benefit from shared system prompts, long prefixes, or multi-turn context outweighs the query and transfer cost. Cache failures should also allow fallback recomputation; inference correctness must not depend on the cache being permanently available.

### 7.6 Deploy Both Abstractions in GPU-less sr1

The repository provides two independent examples:

- [`stormservice-role-demo.yaml`](https://github.com/runzhliu/aik8s/blob/main/examples/aibrix-sr1/stormservice-role-demo.yaml): creates a StormService containing two CPU mock Roles, Prefill and Decode;
- [`kvcache-vineyard-demo.yaml`](https://github.com/runzhliu/aik8s/blob/main/examples/aibrix-sr1/kvcache-vineyard-demo.yaml): creates a centralized Vineyard KVCache containing Etcd metadata and a Vineyard Cache Engine.

In the offline cluster, first map the public images in the examples to a Registry accessible to the cluster, then run:

```bash
kubectl apply -f examples/aibrix-sr1/stormservice-role-demo.yaml
kubectl apply -f examples/aibrix-sr1/kvcache-vineyard-demo.yaml

kubectl -n aibrix-demo get stormservice,roleset,kvcache
kubectl -n aibrix-demo get deploy,pod,svc,endpoints -o wide
```

The measured StormService result this time was:

```text
StormService/aibrix-role-demo  Ready=True
└─ RoleSet/aibrix-role-demo-roleset-...  Ready=True
   ├─ Pod/...-prefill-...  Running  node=<node-a>
   └─ Pod/...-decode-...   Running  node=<node-b>
```

`status.roleStatuses` shows both Prefill and Decode are `replicas=1, readyReplicas=1`. Requesting model `aibrix-role-demo` through the AIBrix Gateway returned HTTP 200, with response headers recording:

```text
routing-strategy: least-request
target-pod: aibrix-role-demo-roleset-...-decode-...
target-pod-ip: <pod-ip>:8000
```

Then `StormService.spec.replicas` was changed from 1 to 2, and the Controller created two RoleSets and four Pods, with each RoleSet containing one Prefill and one Decode. Four consecutive P/D requests round-robin between the two RoleSets, but each Prefill and Decode always come from the same RoleSet, showing the grouped replica boundary was not broken. After restoring to 1, the extra RoleSet was deleted and the status returned to:

```text
readyReplicas=1
roleStatuses[prefill].readyReplicas=1
roleStatuses[decode].readyReplicas=1
```

This test is more valuable than "the CRD can be created": it verifies RoleSet lifecycle, grouped scaling, P/D pairing, and scale-down reclamation. Real GPU scenarios should also continue testing model loading during scale-up, connection warm-up, graceful termination of in-flight requests, and KV invalidation.

A very typical pitfall appeared here: do not manually create a same-name ordinary ClusterIP Service for the StormService. The Controller automatically creates a same-name Headless Service; if the ordinary Service already exists, the Controller will keep failing when trying to change `clusterIP` to `None` because the field is immutable, and the RoleSet will not be generated. After deleting the conflicting Service, the StormService immediately returned to Ready.

The resources actually generated by the KVCache test were:

```text
KVCache/vineyard-demo
├─ Pod/vineyard-demo-etcd-0       role=metadata
├─ Deployment/vineyard-demo
│  └─ Pod/vineyard-demo-...       role=cache
├─ Service/vineyard-demo-etcd-service:2379
└─ Service/vineyard-demo-rpc:9600
```

The OwnerReference of both workloads points to `KVCache/vineyard-demo`. Logs confirmed the Etcd single node completed leader election, Vineyard successfully connected to the metadata service, and listened on `/var/run/vineyard.sock` and `0.0.0.0:9600`; since the node has no RDMA, Vineyard explicitly fell back to TCP.

These two demos prove that the CRD, Controller, OwnerReference, role status, and basic cache processes can work, but they do not prove real P/D or KV offload performance: Prefill/Decode use the same CPU mock, with no NIXL/LMCache Connector; Vineyard is not connected to real vLLM; and the nodes have not published GPU/RDMA to Kubernetes. The next phase should first complete a single-GPU vLLM baseline, then verify P/D direct transfer, cache hit rate, and distributed InfiniStore in sequence, rather than treating the demo's `Running` as proof that the production data path is working.

References: [AIBrix StormService](https://aibrix.readthedocs.io/latest/designs/aibrix-stormservice.html), [AIBrix KVCache Offloading Framework](https://aibrix.readthedocs.io/latest/designs/aibrix-kvcache-offloading-framework.html)

## 8. Actually Run KPA, APA, HPA, and Custom Metrics End to End

The four chains have different dependencies; you cannot broadly say "install Prometheus and you get autoscaling":

```text
资源 HPA
  kubelet → Metrics Server → metrics.k8s.io → 原生 HPA

AIBrix APA（resource metric）
  kubelet → Metrics Server → metrics.k8s.io → AIBrix Controller → Scale

AIBrix KPA / APA（pod metric）
  推理 Pod /metrics → AIBrix Controller 直接抓取 → Scale

自定义指标 HPA
  推理 Pod /metrics → Prometheus → Prometheus Adapter
  → custom.metrics.k8s.io → 原生 HPA
```

The Prometheus Operator manages Prometheus, ServiceMonitor, and PrometheusRule; it itself provides neither the resource Metrics API nor the Custom Metrics API.

### 8.1 Which Metrics Server Should Be Installed on Kubernetes 1.30

sr1 is Kubernetes 1.30.4. At experiment time, the latest Metrics Server was already v0.9.0, but the official compatibility matrix requires: 0.9.x corresponds to Kubernetes 1.34+, 0.8.x to 1.31+, and 0.7.x supports 1.27+. Therefore v0.7.2 was chosen here rather than mechanically installing the latest version:

```bash
kubectl apply -f \
  https://github.com/kubernetes-sigs/metrics-server/releases/download/v0.7.2/components.yaml

kubectl get apiservice v1beta1.metrics.k8s.io
kubectl top nodes
```

After installation, `v1beta1.metrics.k8s.io Available=True`, 11 nodes could return CPU/memory; the Kubelet on another node refused connections on port 10250, so it still showed `<unknown>`.

This also exposed a more serious historical problem: the Kubelet Serving Certificates on most nodes had already expired. To complete the experiment first, Metrics Server was temporarily given:

```text
--kubelet-insecure-tls
```

This only disables certificate verification between Metrics Server and Kubelet; it does not disable Kubernetes API TLS, but it should still not become a long-term configuration. The production fix is to rotate Kubelet certificates, validate certificate SANs, and enable automatic renewal, then remove this parameter; otherwise node identity verification is degraded and man-in-the-middle risk is hidden.

Reference: [Metrics Server compatibility matrix](https://github.com/kubernetes-sigs/metrics-server#compatibility-matrix)

### 8.2 AIBrix v0.7.0's APA Is Missing One RBAC Rule

Native HPA succeeded immediately after installing Metrics Server, but the AIBrix APA kept reading 0. The Controller log gave the real reason:

```text
pods.metrics.k8s.io is forbidden:
User "system:serviceaccount:aibrix-system:aibrix-controller-manager"
cannot get resource "pods" in API group "metrics.k8s.io"
```

That is, the CRD status may still show Ready, but the algorithm is actually computing with 0. After minimally supplementing `get/list pods.metrics.k8s.io` through an independent ClusterRole, the APA read the actual CPU and completed scaling. The manifest is at [`controller-metrics-rbac.yaml`](https://github.com/runzhliu/aik8s/blob/main/examples/aibrix-sr1/controller-metrics-rbac.yaml). An independent Role is easier to audit and upgrade than directly modifying the large ClusterRole in the release manifest.

### 8.3 Measured CPU Results for the Three Strategies

The experiment manifests in the repository include:

- [`podautoscaler-cpu-demo.yaml`](https://github.com/runzhliu/aik8s/blob/main/examples/aibrix-sr1/podautoscaler-cpu-demo.yaml): directly scrapes the mock `/metrics`;
- [`podautoscaler-hpa-cpu-demo.yaml`](https://github.com/runzhliu/aik8s/blob/main/examples/aibrix-sr1/podautoscaler-hpa-cpu-demo.yaml): resource HPA;
- [`podautoscaler-apa-cpu-demo.yaml`](https://github.com/runzhliu/aik8s/blob/main/examples/aibrix-sr1/podautoscaler-apa-cpu-demo.yaml): APA reading the Metrics API.

| Strategy | Data Source | Measured Result | Key Finding |
| --- | --- | --- | --- |
| KPA | mock Pod `/metrics` | StormService 1→2, then back to 1 | Controller can scrape metrics directly; mock fluctuation, per-replica normalization, and 0 cooldown cause oscillation |
| HPA | `metrics.k8s.io` CPU | Deployment 1→2 | AIBrix correctly generates an `autoscaling/v2` HPA with OwnerReference |
| APA | `metrics.k8s.io` CPU | After RBAC fix, Deployment 1→2 | AIBrix reads the Metrics API itself; insufficient permissions in the default installation silently yield 0 |

The measured HPA metric was `cpu: 1000%/20%`, and the event was `SuccessfulRescale`. The APA status ended as `desiredScale=2, actualScale=2`. These CPU burners were used only to prove the controller and metrics chain, and were all deleted afterward to avoid continuously occupying the cluster.

KPA's rapid 1→2→1 is not ideal behavior for a production strategy; it shows that cooldown windows, stabilization windows, target values, and real time-series data must be designed together. Inference scaling also has to account for minute-level model loading latency and cannot copy the second-level HPA parameters of web services.

### 8.4 Collecting vLLM Metrics with a Minimal Prometheus Stack

This time we use `kube-prometheus-stack 88.1.5`, but disable Grafana, Alertmanager, node-exporter, kube-state-metrics, and the default rules, keeping only Prometheus Operator and a single Prometheus; no PVC is requested, and data is retained for 2 hours. The configuration is in [`prometheus-minimal-values.yaml`](https://github.com/runzhliu/aik8s/blob/main/examples/aibrix-sr1/prometheus-minimal-values.yaml):

```bash
helm upgrade --install aibrix-monitoring \
  prometheus-community/kube-prometheus-stack \
  --version 88.1.5 \
  -n monitoring --create-namespace \
  -f examples/aibrix-sr1/prometheus-minimal-values.yaml

kubectl apply -f examples/aibrix-sr1/mock-vllm-servicemonitor.yaml
```

In an offline environment, you need to preload the four images—Operator, Webhook Certgen, Prometheus, and Config Reloader—into a Registry accessible to the cluster, then override the image addresses via values. Do not forget Config Reloader: it is dynamically written into the Prometheus Pod by the Operator, and it is easy to miss if you only look at the Deployment rendered by Helm.

Prometheus ultimately selects only Monitors with the `monitoring.aik8s.run/instance=aibrix` label. Both mock vLLM Targets are `health=up`, and the following query returns the current values for the two Pods:

```promql
vllm:gpu_cache_usage_perc{model_name="llama2-7b"}
```

### 8.5 Let Native HPA Use vLLM Custom Metrics

Prometheus Adapter is responsible for mapping PromQL to the Kubernetes Custom Metrics API. The configuration is in [`prometheus-adapter-values.yaml`](https://github.com/runzhliu/aik8s/blob/main/examples/aibrix-sr1/prometheus-adapter-values.yaml):

```bash
helm upgrade --install aibrix-prometheus-adapter \
  prometheus-community/prometheus-adapter \
  --version 5.3.0 \
  -n monitoring \
  -f examples/aibrix-sr1/prometheus-adapter-values.yaml

kubectl get apiservice v1beta1.custom.metrics.k8s.io
kubectl get --raw \
  '/apis/custom.metrics.k8s.io/v1beta1/namespaces/aibrix-demo/pods/%2A/gpu_cache_usage_perc'
```

The APIService ultimately becomes `Available=True`, and `pods/gpu_cache_usage_perc` is discovered. After applying [`podautoscaler-hpa-vllm-metric-demo.yaml`](https://github.com/runzhliu/aik8s/blob/main/examples/aibrix-sr1/podautoscaler-hpa-vllm-metric-demo.yaml), AIBrix creates a native HPA, and the actual test shows:

```text
gpu_cache_usage_perc: 61500m / 10
SuccessfulRescale: New size: 3
AIBrix desiredScale=3, actualScale=3
```

The mock vLLM scales from 2 to 3, and after the test, the PodAutoscaler is deleted and it returns to 2. Production rules cannot copy `targetValue: 10` directly; they should be jointly calibrated based on real GPU KV capacity, waiting queue, request rate, TTFT/TPOT SLO, scaling cost, and model loading time. A single instantaneous Gauge should not be used as the sole scaling signal.

## 9. Why Gateway Is Accepted but Programmed=False

Envoy Gateway by default creates a Service of type `type: LoadBalancer` for the data plane. If the cluster has no cloud LoadBalancer Controller or MetalLB, the Service will show for a long time:

```text
TYPE           EXTERNAL-IP
LoadBalancer   <pending>
```

At this point, the Gateway Condition is usually:

- `Accepted=True`: The GatewayClass and configuration have been accepted by the controller;
- Listener `Programmed=True`: The listener configuration has been sent to Envoy;
- Gateway `Programmed=False / AddressNotAssigned`: No external address.

It does not mean that Envoy or AIBrix routing has failed. In this test, HTTP 200 was already obtained through port forwarding behind the ClusterIP. For production ingress, choose ClusterIP, internal LoadBalancer/VIP, or a controlled cross-cluster address based on the network topology. Do not misdiagnose `<pending>` as a model backend failure.

## 10. How Higress and AIBrix Should Divide Responsibilities

It is not recommended to use Higress to directly replace AIBrix's fixed Envoy Gateway. AIBrix's Gateway Plugin obtains model, queue, Prefix/KV, and P/D awareness through Envoy `ext_proc`, `EnvoyExtensionPolicy`, and `EnvoyPatchPolicy`. A clearer division of responsibilities is:

```text
客户端
  → Higress：域名、TLS、认证、租户、限流、审计
  → AIBrix Envoy Gateway：模型发现、LLM 路由、P/D、KV/Prefix 策略
  → vLLM / SGLang / TensorRT-LLM
```

### 10.1 Higress and AIBrix in the Same Cluster

Higress's Upstream points to the AIBrix Envoy data plane Service, not to a specific vLLM Service:

```text
envoy-<namespace>-<gateway>-<hash>.envoy-gateway-system.svc.cluster.local:80
```

The ingress needs to preserve:

- `/v1/*` path and request body;
- `Authorization`;
- `routing-strategy` and other controlled routing headers;
- SSE/streaming responses, long request timeouts, and cancellation propagation.

If the enterprise already has a mature Higress, it is not recommended to switch all existing models to AIBrix. Existing single-node single-GPU/multi-GPU Deployments continue to be directly connected by Higress; only models that require multi-replica model awareness, P/D, KV/Prefix, or Role-aware routing should gradually migrate to the internal AIBrix Gateway per Route. A single fixed multi-node multi-GPU replica that always accesses only one Leader Service does not automatically gain the necessity of a second-layer gateway just because it is "multi-node."

For example, the official vLLM multi-node recipe for DeepSeek-V4-Pro can combine 2 GB200 NVL4 Trays, totaling 8 GPUs, into one DP + EP Replica. When there is only this one group, Higress can directly connect to its Leader/API Service; when a second homogeneous 8-GPU Replica is deployed, or an independent Prefill/Decode Pool is added, AIBrix performs model-aware selection among the complete groups. The lifecycle and communication of ranks within a group are still handled by StormService/RoleSet, LeaderWorkerSet, KubeRay, or the Runtime. The Gateway cannot arbitrarily splice Workers from different Replicas. See [Multi-node and Disaggregated LLM Inference](../inference/distributed-serving.md#deepseek-v4-multi-node-example) for details.

### 10.2 Higress and AIBrix in Different Clusters

Cross-cluster is also feasible, but `*.svc.cluster.local` cannot be used. The AIBrix cluster needs to provide a stable and routable internal address:

1. Internal LoadBalancer/VIP, preferred;
2. Internal DNS resolving to that VIP;
3. A stable service in the enterprise service registry;
4. Port forwarding only for experiments, not for production.

Higress registers this address as a static, DNS, or registry Upstream. The network must allow Higress data plane to reach the AIBrix Gateway listening port, and health checks, connection pools, streaming timeouts, and capacity protection should be configured. Do not use a single Envoy Pod IP: Pod recreation and rolling releases will invalidate the address.

The two-layer gateway should also avoid duplicate policies: retries are handled by only one layer or with a clear budget; rate limiting distinguishes tenant ingress from model capacity; the Request ID generated by Higress should be passed through to AIBrix; AIBrix's internal diagnostic headers such as `target-pod` should not be exposed to the public network by default.

Subsequently, in the same cluster, we installed Higress v2.2.3 using a dedicated `higress-system` Namespace, `higress-sr1` IngressClass, and ClusterIP Service, and successfully ran Higress → AIBrix → CPU mock vLLM through a stable alias Service. The request returned HTTP 200, AIBrix `least-request` selected the specific model Pod, and Plugin logs recorded input/output tokens; Higress logs also recorded the target Upstream. The first response exposed AIBrix internal Pod/IP headers; after adding Route-level response header deletion, the retest passed. When continuing to retest with forged headers, Higress successfully cleared identity/configuration control headers and overwrote the client's `random` with the platform's `least-request`; a legitimate `traceparent` also made AIBrix logs and responses use the same Trace ID. No existing nginx, AIBrix Gateway, or business routes were modified. The full checklist, evidence, and selection boundaries are in [Higress AI Gateway Practice](../inference/higress-ai-gateway.md).

### 10.3 Single-Node k3s Re-verification Matrix

On a k3s node with 28 cores, about 31 GiB memory, and no GPU, the following re-verifications were completed. All temporary scaling has been restored to baseline replica counts:

| Test | Actual Result | What It Proves |
| --- | --- | --- |
| GatewayClass, Gateway, HTTPRoute | `Accepted=True`, `Programmed=True`, `ResolvedRefs=True` | Envoy Gateway and AIBrix routing objects are reconciled |
| `least-request`, `random`, `prefix-cache` | All HTTP 200, with different target Pods recorded in response headers/logs | Model discovery and three routing code paths are usable; does not represent real KV hits |
| Nonexistent model | HTTP 400, `model_not_found` | Error semantics can converge at the gateway layer |
| StormService `pd` | HTTP 200, with both Prefill and Decode Pods recorded | P/D role pairing and mock control flow are usable |
| StormService 1→2→1 | Two RoleSets, four role Pods Ready, requests succeeded during scaling, then restored to 1 group | Group lifecycle and scaling reconciliation are usable |
| Delete one mock Pod | Requests immediately after deletion still returned 200, Deployment replenished a new replica | Endpoint removal and basic self-healing are usable |
| KVCache / Vineyard | etcd Ready, Vineyard RPC listening on 9600 | CR, metadata, and TCP cache process are usable |
| RDMA fallback | Logs record RDMA initialization failure and fallback to TCP | Expected degradation on nodes without RDMA; does not prove high-speed KV transfer |
| Higress → AIBrix | HTTP 200, client `random` overwritten to `least-request`, internal headers cleaned | Two-layer gateway chaining and boundary header policies work |

This round of node testing used approximately 9% CPU and 57% memory; this is only a transient observation of the control plane and CPU mock, and should not be used to estimate real model capacity.

## 11. What Is Still Missing Before Switching to Real GPU vLLM

Mock request success only proves the following chain:

- AIBrix Controller, Webhook, and CRDs are normal;
- Envoy Gateway and AIBrix Gateway Plugin are normal;
- Model discovery, HTTPRoute generation, and routing policies are normal;
- OpenAI-Compatible requests can reach the target backend.

It does not prove that GPU, model loading, NCCL, RDMA, KV Cache, or multi-node P/D are ready. Before real models go live, at least complete:

- Install and verify NVIDIA Device Plugin/GPU Operator, and the node shows `nvidia.com/gpu`;
- Confirm Driver, CUDA, Container Toolkit, and vLLM image compatibility;
- Prepare model PVC, object storage, or node cache;
- First run a single-Pod, single-GPU vLLM health check and performance baseline;
- Then make the Service name, served model name, and AIBrix model labels consistent;
- For multi-node TP/PP or P/D scenarios, add high-speed network, topology, StormService/RoleSet, and fault tests;
- Integrate real TTFT, TPOT, queue, KV hit, and GPU metrics into monitoring.

### 11.1 What Capabilities Are Still Untested, and How Far CPU Can Test

| Capability | CPU Testable? | Current Status | Next Step |
| --- | --- | --- | --- |
| Gateway multi-policy, error semantics, Session | Can fully test control flow | Tested | Supplement quality and performance comparison with real traffic |
| StormService/RoleSet lifecycle | Yes | Tested 1→2→1 and P/D pairing | Add Pod failure, rolling upgrade, graceful shutdown |
| KPA, APA, HPA | Yes | All three policies triggered scaling | Stability testing with real time series and cooldown parameters |
| Prometheus and custom metrics HPA | Yes | Collected and scaled | Add combined queue, TTFT/TPOT, request rate policies |
| RayClusterFleet/ReplicaSet | Control plane and CPU Ray tasks testable | CRD/Operator installed, Fleet not yet created | Prepare fixed Ray image, test scaling and Head failure |
| ModelAdapter / LoRA | CR lifecycle testable, effect requires compatible Runtime | Not yet tested | Validate load/unload with small model and CPU-compatible vLLM, then go to GPU |
| Batch API / BrixBench | Yes | Not yet tested | Run concurrency, cancellation, failure retry, and reporting against mock Endpoint |
| Semantic Router | Control plane usable on CPU | Not yet tested | Requires accessible Embedding model and at least two semantic backends |
| Real P/D KV transfer | Insufficient | Only mock control flow verified | GPU + NIXL/LMCache + high-speed network |
| KVCache performance and hit benefits | Insufficient | Vineyard process and CR lifecycle tested | Real Connector, shared prefix, and capacity/fault experiments |
| Multi-GPU, multi-node, heterogeneous, and GPU failure | No | Node has no GPU published | Device Plugin/GPU Operator, topology, NCCL/RDMA, and fault injection |

Therefore, the next phase's highest priority is not to create more CRs of `Running`, but to first get a single-GPU real vLLM baseline running; otherwise LoRA, P/D, KVCache, heterogeneous scheduling, and GPU fault detection can only verify Kubernetes control objects and cannot prove data plane value. The CPU environment is still suitable for continuing to supplement Ray, Batch, BrixBench, Semantic Router, and fault lifecycle, and these should be clearly labeled as "control plane tested" or "real model data plane tested."

## 12. Practical Experience Exposed by This Experiment

1. **Versions must be selected as a combination.** AIBrix, Envoy Gateway, Gateway API, and Envoy Proxy form a compatibility unit;
2. **Offline images must be fully inventoried at once.** The dynamically generated Envoy data plane image is the easiest to miss;
3. **Verify the control plane first, then occupy GPU.** The mock Runtime can quickly distinguish gateway issues from model issues;
4. **Look at response headers and logs to prove routing.** HTTP 200 alone is not enough to prove requests passed through AIBrix;
5. **A complete API Group can avoid CRD ambiguity.** Large enterprise clusters often have multiple Kinds with the same name;
6. **LoadBalancer Pending does not mean the Listener is not working.** You need to check Service, Gateway, and Listener Conditions separately;
7. **Higress and AIBrix are two layers of responsibility.** The former serves as the unified entry point, the latter as the LLM-aware data plane;
8. **StormService owns a Headless Service with the same name.** Do not create a regular ClusterIP Service with the same name in advance;
9. **Cross-cluster entry points must be stable.** Use VIP/DNS/service registration, do not rely on Pod IPs;
10. **The three types of Metrics APIs must be distinguished.** Metrics Server, Prometheus Operator, and Prometheus Adapter solve different problems;
11. **Ready does not mean metrics are valid.** APA may remain Ready even with RBAC Forbidden; you must check both Controller logs and actual Scale;
12. **Offline monitoring images must consider dynamic Sidecars.** Config Reloader may not directly appear in Helm's static Deployment image list;
13. **Scaling parameters cannot be copied from web services.** LLM model loading, KV warm-up, and GPU costs determine a longer stabilization window and more cautious scale-down.

## 13. Acceptance Checklist

- [x] Kubernetes and the fixed Envoy Gateway version are within the compatibility matrix;
- [x] External dependency images have been prepared to a cluster-accessible Registry according to node architecture;
- [x] Envoy Gateway Controller and Certgen succeeded;
- [x] All six default AIBrix Deployments are Ready;
- [x] GatewayClass `Accepted=True`;
- [x] All three HTTPRoutes are `Accepted=True`, `ResolvedRefs=True`;
- [x] Two mock model Pods are Ready, Service has two Endpoints;
- [x] Gateway request returns HTTP 200;
- [x] Response headers and Gateway Plugin logs can locate the target Pod;
- [x] StormService automatically generates RoleSet, Prefill/Decode Roles are both Ready;
- [x] CPU mock model routes to Role Pods through AIBrix Gateway;
- [x] Centralized KVCache automatically generates Etcd, Vineyard, and corresponding Services;
- [x] `random`, `least-request`, `power-of-two`, latency, throughput, Prefix, Session, and filtered routing are available;
- [x] P/D requests can select Prefill and Decode in the same RoleSet;
- [x] StormService completes 1→2→1 group scaling;
- [x] Metrics Server APIService is available, 11 nodes return resource metrics;
- [x] AIBrix KPA, APA, and resource HPA have all triggered real scaling;
- [x] Prometheus Operator and single-instance Prometheus are Ready, both vLLM Targets are Up;
- [x] Prometheus Adapter exposes `pods/gpu_cache_usage_perc`;
- [x] Custom vLLM metric HPA scaled the mock Deployment from 2 to 3, and has recovered;
- [x] Same-cluster Higress → AIBrix → mock vLLM returns HTTP 200, and internal diagnostic response headers are cleaned;
- [x] Higress removes forged identity/configuration headers and enforces platform routing policy; AIBrix uses unified Trace ID via `traceparent`;
- [x] Single-node k3s configures same-cluster ClusterIP for Gateway, `Programmed=True`;
- [ ] Configure intranet VIP/LoadBalancer for cross-cluster or production traffic;
- [ ] Kubernetes publishes GPU resources and runs real vLLM;
- [ ] Fix Kubelet Serving Certificate expiration and remove `--kubelet-insecure-tls`;
- [ ] Fix Metrics `<unknown>` caused by node Kubelet 10250 connection refusal;
- [ ] Verify RayClusterFleet, ModelAdapter/LoRA, Batch, BrixBench, and Semantic Router;
- [ ] Integrate OpenTelemetry Collector, write Higress/AIBrix Trace IDs into unified logs, and verify timeout, streaming, authentication, and failure semantics.

## Further Reading

- [AIBrix Installation](https://aibrix.readthedocs.io/latest/getting_started/installation/installation.html)
- [AIBrix Gateway Routing](https://aibrix.readthedocs.io/latest/features/gateway-plugins.html)
- [Envoy Gateway Compatibility Matrix](https://gateway.envoyproxy.io/news/releases/matrix/)
- [AI Gateway and Intelligent Routing](../inference/gateway-routing.md)
- [Multi-machine and Disaggregated LLM Inference](../inference/distributed-serving.md)
- [RBG Multi-Role Inference Orchestration and sr1 Practice](rbg-existing-cluster.md)
