---
title: "RBG Multi-Role Inference Orchestration: From CPU Control Plane to Production GPU Validation"
description: "Deploy RoleBasedGroup on a Kubernetes 1.30 cluster, validate role dependencies, service discovery, scaling, self-healing, two-node Ray inference, and NIXL P/D disaggregation, and compare RBG with AIBrix using the same images and models"
status: lab
last_reviewed: 2026-08-08
---

# RBG Multi-Role Inference Orchestration: From CPU Control Plane to Production GPU Validation

RBG stands for **RoleBasedGroup (RBG)**. It is not a new inference engine, nor another AI Gateway, but a set of Kubernetes APIs for distributed, stateful, multi-role AI workloads. It coordinates the creation, discovery, scaling, update, and recovery of roles such as Router, Prefill, Decode, and KV Store, as well as multi-Pod ranks within a role, as one logical service.

As of August 2026, the latest official release is `v0.8.0-alpha.3`. This time, we first validated the control plane on the sr1 Kubernetes 1.30.4 cluster using CPU placeholder processes, then on a production GPU cluster, using the same images, models, and runtime parameters as the existing AIBrix service, we successively ran single-GPU vLLM, two-node Ray/vLLM, and two-node NIXL P/D. The conclusion is: RBG is well suited to fill the gap where native Deployment under-expresses multi-role lifecycle management, but it cannot replace vLLM/SGLang/Dynamo, P/D Router, KV Connector, AIBrix Gateway, or Higress.

!!! warning "Production information has been redacted"
    This article does not record internal company cluster names, node addresses, Registry, Ceph monitor, real model volume paths, domain names, Pod IPs, or Secrets. The production manifests have not been committed to a public repository; `<...>` in this article needs to be replaced according to your own environment.

References: [RBG repository](https://github.com/sgl-project/rbg), [RBG v0.8.0-alpha.3](https://github.com/sgl-project/rbg/releases/tag/v0.8.0-alpha.3), [RBG official documentation](https://rolebasedgroup.github.io/)

## 1. Which Layer of Problem Does It Solve

A P/D-disaggregated service may include:

```text
Higress
  → 模型或 P/D Router
      → Prefill Pool
      → Decode Pool
          → KV Cache Transfer / Store
```

There are at least four different categories of responsibility here:

| Layer | Question it answers | Typical components |
| --- | --- | --- |
| Enterprise entry | Which tenant can access, how domain, TLS, authentication, rate limiting, and auditing are handled | Higress |
| Inference request routing | Which model replica should a request enter, how P and D are paired | AIBrix Gateway, SGLang Router, Dynamo Router, llm-d EPP |
| Workload orchestration | How many Pod groups Router, P, and D each need, who starts first, how discovery, update, and recovery work | RBG, AIBrix StormService/RoleSet, LWS, KubeRay |
| Inference and data path | How the model executes, how KV Cache is produced, transferred, and reused | vLLM, SGLang, TensorRT-LLM, NIXL, Mooncake, LMCache |

RBG mainly sits at the third layer. It can create Pods running SGLang, vLLM, Dynamo, or Mooncake, but it does not implement the data path of these components.

## 2. RBG's Resource Model

This installation created 10 CRDs. To understand daily operations, first focus on the following five:

```text
RoleBasedGroup：一个完整逻辑服务
  ├─ 每个 Role 自动生成一个 RoleInstanceSet
  │    └─ 每份 Role 副本生成一个 RoleInstance
  │          └─ 一个或多个 Pod
  ├─ 每个 Role 自动生成一个 Headless Service
  └─ 可选 RoleBasedGroupScalingAdapter
       └─ 为某个 Role 暴露 Scale 子资源
```

| Resource | Purpose | Instance in sr1 |
| --- | --- | --- |
| `RoleBasedGroup` | Declares which Roles, dependencies, and replica counts a service includes | `mock-pd` |
| `RoleInstanceSet` | Manages multiple instances of a Role | `mock-pd-prefill` |
| `RoleInstance` | Manages one stable instance and its Pod group | `mock-pd-prefill-0` |
| `RoleBasedGroupScalingAdapter` | Maps a single Role to a Scale target operable by HPA/KEDA | `mock-pd-decode` |
| `CoordinatedPolicy` | Declares cross-Role update or scaling coordination policy | Not validated this time |
| `RoleBasedGroupSet` | Manages multiple RBGs | Not validated this time |
| `ClusterEngineRuntimeProfile` | Reuses engine runtime configuration | Not validated this time |

A Role can also choose different instance topologies:

| Pattern | What one RoleInstance contains | Applicable scenario |
| --- | --- | --- |
| `standalonePattern` | One Pod | Router, single-GPU or single-Pod multi-GPU engine |
| `leaderWorkerPattern` | One Leader and multiple Workers | One model replica spanning multiple Pods/nodes |
| `customComponentsPattern` | Multiple custom Components | Complex Runtime requiring heterogeneous Pod combinations |

`Role` is the outer responsibility, and `Pattern` is the Pod topology within one instance of that responsibility. For example, Prefill is a Role, and one Prefill Engine can use `leaderWorkerPattern` across four nodes. Do not treat "Prefill/Decode" and "Leader/Worker" as the same dimension.

## 3. RBG, AIBrix, and Higress Comparison

RBG is not the same category of product as the full AIBrix or Higress stack. The most meaningful direct comparison is **RBG versus AIBrix StormService/RoleSet**.

| Dimension | RBG | AIBrix StormService/RoleSet | AIBrix overall | Higress |
| --- | --- | --- | --- | --- |
| Core positioning | General-purpose multi-role workload orchestration API | AIBrix's internal multi-role inference orchestration | LLM inference control plane and data plane | Enterprise API/AI Gateway |
| Owns Pod lifecycle | Yes | Yes | Can own via StormService, RayClusterFleet, etc. | No |
| Handles user requests | No | The CRD itself does not | AIBrix Gateway handles them | Higress Gateway handles them |
| Model-aware replica selection | None | Done in coordination with AIBrix Gateway | Yes | Focuses on Provider/Route governance, not P/D replica scheduling |
| P/D capability | Expresses Router, P, D Roles; data path provided by Runtime | Expresses P/D Roles, more tightly integrated with AIBrix P/D routing | Routing, orchestration, scaling, and KV capabilities can be combined | Can forward requests to a P/D Router, but does not manage P/D Pods |
| Service discovery | Automatically creates a Headless Service per Role, injects topology environment variables | StormService/RoleSet services and labels | Model/Role discovery combined with Gateway | Upstream, Ingress, Gateway API, or registry |
| Role-level elasticity | ScalingAdapter connects to HPA/KEDA, etc. | AIBrix PodAutoscaler can operate on `roleName` | KPA, APA, HPA, and custom metric chains | Mainly scales the Gateway; does not itself decide P/D pool capacity |
| Ecosystem tendency | SGLang, Dynamo, Mooncake; can also host vLLM | AIBrix Gateway, vLLM, and AIBrix CRDs | vLLM-centric full platform capability | Enterprise entry, multi-model/cloud models, Wasm plugins |
| Current project risk | Latest release is still alpha | Tied to AIBrix version and Gateway integration | Many components, larger compatibility matrix | Not a distributed inference orchestrator |

### 3.1 When RBG Is a Better Fit

- You want to express a Router/P/D/Store multi-role topology with an independent, engine-neutral API;
- Roles have explicit startup dependencies, stable identity, coordinated recovery, or coordinated update requirements;
- You need to express both single-Pod Roles and multi-node Leader/Worker Roles;
- You are using the official integration methods of SGLang, NVIDIA Dynamo, or Mooncake;
- You want to decouple workload orchestration from the upper-layer Gateway.

### 3.2 When to Keep Using StormService

- You have fully adopted AIBrix Gateway, PodAutoscaler, model labels, and P/D routing;
- You want Prefill/Decode orchestration, request pairing, and role-level scaling to all follow one set of AIBrix semantics;
- You have already validated StormService's Replica/Pool pattern and do not want to introduce a second set of similar CRDs;
- The operations team values reducing the number of controllers more than Runtime neutrality.

The same set of Pods cannot be owned by both RBG and StormService at the same time. Otherwise, replica counts, rolling updates, failure recovery, and Services will all have two sources of authority.

### 3.3 How to Combine with Higress

RBG does not have its own general-purpose external Gateway, so there is no duplication problem of "two layers of gateways: Higress and RBG." A common chain is:

```text
Client
  → Higress：TLS、认证、租户配额、审计
  → SGLang/Dynamo/自研 Router Service
  → RBG 管理的 Prefill、Decode 和 KV 角色
```

If AIBrix's model-aware routing is also needed, you can design:

```text
Client
  → Higress：企业入口
  → AIBrix Gateway：模型、Prefix/Session/P-D 感知选路
  → 由 RBG 管理的 Runtime Endpoint
```

However, AIBrix v0.7.0 did not prove in this experiment that it can natively create or manage RBG. Actual integration requires at least stable Endpoints, AIBrix model/port labels, Ready semantics, and custom integration tests. When there is only one fixed Runtime Router or one complete model replica, direct forwarding by Higress is usually simpler; do not force a second inference gateway layer just for component completeness.

### 3.4 After Using RBG, Does SGLang Still Need a Router

If SGLang uses Prefill/Decode disaggregation, the answer is: **you still need a Router that understands the P/D protocol, but it does not necessarily have to be the SGLang Router**. RBG is responsible for the lifecycle, startup dependencies, stable discovery, update, and scaling of Router, Prefill, and Decode Pods; it does not receive user inference requests, nor does it select P/D instances for a request. The Headless Service RBG creates for the Prefill Role is only a service discovery entry point; it cannot replace request pairing and data-plane coordination.

The recommended data path is:

```text
Client
  → Higress / API Gateway（可选：TLS、认证、租户限流）
  → SGLang Model Gateway（原 SGLang Router）
       ├─ 选择一个 Prefill Engine
       └─ 选择一个 Decode Engine
              ↑
       Prefill ── Mooncake/NIXL 等 KV Transfer ──→ Decode

RBG Controller
  ├─ 管理 Router Role
  ├─ 管理 Prefill Role
  └─ 管理 Decode Role
```

In P/D mode, ordinary OpenAI-Compatible traffic should not be sent directly to the Prefill Service. Prefill is only responsible for processing the Prompt and generating the initial KV; a complete response still requires Decode to continue generation. Without a Router, the caller must handle P/D selection, request splitting, KV/bootstrap metadata transfer, failure handling, and streaming response coordination itself, which is effectively reimplementing a P/D Router. Kubernetes Service's Layer-4 load balancing also knows nothing about Prefix Cache, instance queue length, P/D role ratio, or the pairing state of a single request.

Whether to deploy the SGLang Router should be decided by the operating mode:

| SGLang operating mode | Is the SGLang Router needed | Assessment |
| --- | --- | --- |
| P/D disaggregated, no other P/D routing layer yet | Needed | Use the SGLang Model Gateway to select and coordinate Prefill/Decode |
| P/D disaggregated, already has a compatible AIBrix, Dynamo, or self-developed P/D Router | Not necessarily | Keep only one P/D routing authority; the replacement component must truly support the current SGLang P/D protocol and KV transfer parameters |
| Aggregated mode, only one SGLang Engine | Not needed | Higress or a regular Service can forward directly to the complete Engine |
| Aggregated mode, multiple homogeneous Engines | Optional but usually recommended | Kubernetes Service can do basic distribution; only a Router can provide Cache/load awareness, instance removal, and more complete inference metrics |
| Fixed 1P1D functional experiment | Can be temporarily omitted | Only suitable for explicitly coordinating both ends with scripts; cannot be used to conclude that the production entry does not need a Router |

#### Cache-aware Does Not Mean Skipping Prefill

"The request already has 95% KV Cache, so it can jump directly to Decode" describes a conditional optimization direction, usually called **Conditional Disaggregation** or **Prefill Bypass**, but it cannot be decided based on the hit ratio alone. What it actually omits is the **remote Prefill node**; the missed Prompt Tokens still need some Engine to compute their KV.

For example, a 100K-Token Prompt hits 95K on the selected Decode Engine, leaving 5K Tokens missed:

```text
普通 P/D：Prefill Engine 计算剩余 5K → 传输新增 KV → Decode
条件式 P/D：Decode Engine 本地计算剩余 5K → Decode
```

The second path is only valid if the Decode Engine also has the ability to execute a small amount of Prefill locally. Even with a 95% hit ratio, the Prefill of 5K Tokens may still be enough to offset the cost of one remote call and KV transfer; conversely, a 1K Prompt with only 5 Tokens missed is more likely to be suitable for staying local on Decode. Therefore, production decisions should compare the **absolute number of missed Tokens and their compute cost** against the **remote Prefill, KV transfer, and coordination overhead**, rather than setting an isolated hit-ratio threshold.

As of SGLang `main` dated 2026-08-09, the `cache_aware` policy of the SGLang Model Gateway is a **node-selection policy**: it maintains an approximate Radix Tree based on request history and sends requests to Prefill/Decode Workers more likely to hold the same Prefix, but it does not omit the Prefill phase based on this. The current HTTP P/D path still selects a Prefill/Decode pair and sends both requests simultaneously; after a Prefill failure, the Router cancels the Decode request that is waiting for KV. Therefore, SGLang's Cache-aware Routing cannot be equated with Conditional Disaggregation.

The new SGLang Runtime provides `--disaggregation-decode-enable-radix-cache`. When enabled, Decode can reuse its own existing Prefix KV and use `decode_prefix_len` to tell Prefill to transfer only the missed suffix KV; on a full hit, there may even be no ordinary KV Pages to transfer, but the Prefill request and necessary metadata/auxiliary state coordination still exist. This capability optimizes **duplicate computation and KV transfer volume**, not the Router layer directly skipping Prefill.

llm-d Router's `prefix-based-pd-decider` is a direct example of Conditional Disaggregation. It first selects Decode, then decides whether to select remote Prefill based on the missed suffix length on that node: when missed tokens reach the `nonCachedTokens` threshold, it goes through remote P/D; below the threshold, no Prefill Endpoint is set, and the Decode node completes the remaining Prefill and Decode locally. The core parameter here is the absolute number of missed tokens, not a single ratio like "95%".

The scope of "SGLang Router supports vLLM" must also be qualified. SGLang Model Gateway can provide protocol adaptation or routing for ordinary aggregated vLLM backends, but this does not equal support for the vLLM P/D data path. The gRPC Dual/PD path in the aforementioned version explicitly rejects vLLM Workers; the HTTP P/D path also uses SGLang Bootstrap and request fields. During technology selection, "ordinary OpenAI-Compatible/vLLM routing" and "vLLM P/D pairing, KV Connector, Conditional Disaggregation" must be verified separately; the latter cannot be inferred as available from the former.

References: [SGLang HTTP P/D Router](https://github.com/sgl-project/sglang/blob/449f0da78fda43b0e0d51254b8654671bd26e504/sgl-model-gateway/src/routers/http/pd_router.rs#L697-L732), [SGLang Cache-aware Policy](https://github.com/sgl-project/sglang/blob/449f0da78fda43b0e0d51254b8654671bd26e504/sgl-model-gateway/src/policies/cache_aware.rs#L19-L30), [SGLang Decode Radix Cache](https://github.com/sgl-project/sglang/blob/449f0da78fda43b0e0d51254b8654671bd26e504/docs/docs/advanced_features/server_arguments.mdx#L3009-L3012), [SGLang vLLM P/D Check](https://github.com/sgl-project/sglang/blob/449f0da78fda43b0e0d51254b8654671bd26e504/sgl-model-gateway/src/routers/grpc/common/stages/client_acquisition.rs#L42-L52), [llm-d Disaggregation and PD Decider](https://github.com/llm-d/llm-d-router/blob/main/docs/disaggregation.md#prefix-based-pd-decider)

In a typical RBG + SGLang setup, RBG does not connect directly to the P nodes. A single `RoleBasedGroup` declares three Roles — `router`, `prefill`, `decode`, exposing only the Router Service externally while keeping Prefill/Decode Services cluster-internal. RBG's official SGLang P/D example also uses this structure: the Router Role uses `sglang_router.launch_router --pd-disaggregation` and configures Prefill and Decode Endpoints.

If the enterprise entry point already uses Higress, the `Higress → SGLang Model Gateway → P/D` two-layer structure can be retained: the former handles general API governance, and the latter handles the inference data plane. If AIBrix Gateway or another component has already completed SGLang P/D pairing, do not chain a second SGLang P/D Router, to avoid both layers retrying simultaneously, selecting Endpoints redundantly, or making different judgments about request ownership.

References: [RBG SGLang P/D Example](https://github.com/sgl-project/rbg/blob/main/examples/inference/pd-disagg-standalone.yaml), [SGLang P/D Disaggregation](https://docs.sglang.ai/backend/pd_disaggregation.html), [SGLang Model Gateway](https://github.com/sgl-project/sglang/blob/main/docs/advanced_features/sgl_model_gateway.md)

## 4. Pre-installation checks for sr1

Environment for this run:

| Item | Measured value | Conclusion |
| --- | --- | --- |
| Kubernetes Server | 1.30.4 | Meets the 1.28+ requirement of the current installation documentation |
| Node architecture | amd64 | Official controller images can run |
| GPU | No `nvidia.com/gpu` Allocatable found | Only the CPU control plane is verified |
| CRD/ClusterRole permissions | Can be created | Helm Chart can be installed |
| RBG | `v0.8.0-alpha.3` | Pinned version, does not follow latest |
| Controller App Version | `0.8.0-47cfe17` | Matches the default value of the released Chart |

Do not rely only on the compatibility table on the repository homepage. The current `doc/install.md` states Kubernetes 1.28+, so this run uses stricter criteria.

## 5. Installing RBG

Installation parameters are saved in [`helm-values.yaml`](https://github.com/runzhliu/aik8s/blob/main/examples/rbg-sr1/helm-values.yaml). The experiment pinned the Controller and CRD Upgrade Job to healthy nodes and scaled the controller down to one replica:

```bash
helm upgrade --install rbgs \
  https://github.com/sgl-project/rbg/releases/download/v0.8.0-alpha.3/rbgs-0.8.0-alpha.3.tgz \
  --namespace rbgs-system \
  --create-namespace \
  -f examples/rbg-sr1/helm-values.yaml \
  --wait
```

Final state:

```text
Deployment/rbgs-controller-manager  1/1 Ready
Image                              rolebasedgroup/rbgs-controller:v0.8.0-47cfe17
Node                               10.189.110.112
```

### 5.1 Installation pitfalls actually encountered

During the first installation, the CRD Upgrade Job landed on an `10.189.110.111` that had been prohibited from scheduling. The Chart by default configures this Job with full toleration for `operator: Exists`, so it could still be assigned to the abnormal node. After the image was successfully pulled, accessing `10.96.0.1:443` from inside the Pod timed out, and the CRD installation could not continue.

The fix was not to replace the image, but to point the `nodeSelector` of the Job and Controller at confirmed healthy nodes and retry. Further production recommendations:

- Do not equate full toleration with "suitable to run on any node";
- Configure a healthy node pool, necessary affinity, and resources for installation Hooks;
- On installation timeout, first check Job logs, node and API Service network, then determine whether it is an image problem;
- In production, run at least two Controller replicas with cross-node anti-affinity; the single replica here is only to reduce variables in the experiment.

## 6. CPU multi-role example

[`cpu-role-demo.yaml`](https://github.com/runzhliu/aik8s/blob/main/examples/rbg-sr1/cpu-role-demo.yaml) declares three Roles:

```text
gateway × 1
  └─ prefill × 2，等待 gateway Ready
       └─ decode × 2，等待 prefill Ready
            └─ 开启 ScalingAdapter
```

All three Pods run NGINX, consuming very little CPU/memory. This is only a control-plane mock: a Role named Prefill/Decode does not mean NGINX performs inference.

```bash
kubectl apply -f examples/rbg-sr1/cpu-role-demo.yaml
kubectl wait --for=condition=Ready \
  rbg/mock-pd -n rbg-demo --timeout=5m
```

The controller generates:

```text
RoleBasedGroup/mock-pd                  Ready=True
├─ RoleInstanceSet/mock-pd-gateway      1/1
├─ RoleInstanceSet/mock-pd-prefill      2/2
├─ RoleInstanceSet/mock-pd-decode       2/2
└─ ScalingAdapter/mock-pd-decode        Bound
```

The event timeline proves the dependencies take effect: Prefill is created only after Gateway is Ready; Decode is created only after both Prefills are Ready. During initial reconciliation, `DependencyNotMet` and target `RoleInstanceSet not found` Warnings appeared, eventually converging to `AllRolesReady`. Production alerting should set a duration for such recoverable reconciliation events; do not page on-call staff upon a single Warning.

## 7. Service discovery measurements

RBG automatically creates a Headless Service for each Role:

```text
s-mock-pd-gateway   ClusterIP=None
s-mock-pd-prefill   ClusterIP=None
s-mock-pd-decode    ClusterIP=None
```

Accessing Prefill from the Gateway Pod:

```bash
kubectl exec -n rbg-demo mock-pd-gateway-0 -- \
  wget -qO- http://s-mock-pd-prefill:80
```

The measurement returned NGINX HTML. RBG also injected:

```text
RBG_GROUP_NAME=mock-pd
RBG_ROLE_NAME=gateway
RBG_ROLE_INDEX=0
RBG_ROLE_INSTANCE_NAME=mock-pd-gateway-0
RBG_COMPONENT_NAME=gateway
RBG_COMPONENT_INDEX=0
```

A real Runtime can use stable DNS and these topology variables to construct Rank, registration, and Peer discovery. But the Headless Service is only a discovery mechanism; it does not provide model-aware load balancing, P/D pairing, or KV consistency.

## 8. Role-level scaling measurements

After the Decode Role enables `scalingAdapter`, the controller automatically creates an adapter with the same name. Scaling Decode from 2 to 3 via the standard Scale subresource:

```bash
kubectl scale rolebasedgroupscalingadapter mock-pd-decode \
  -n rbg-demo --replicas=3
```

Result:

```text
ScalingAdapter/mock-pd-decode  Bound  replicas=3  readyReplicas=3
RoleInstanceSet/mock-pd-decode desired=3 ready=3
```

After verification, it was restored to 2 via the same Scale subresource, and the final state matched the repository manifest. Before restoration, a server-side Dry Run was performed on the original YAML: because the manifest still declared `decode.replicas: 2` while the ScalingAdapter had already taken control at 3, the Webhook explicitly rejected the override. This is valuable protection, and it also shows that production must determine the single writer of the replica field: after enabling external scaling, do not let GitOps continuously write back a static replica count for the same Role.

This proves HPA/KEDA can change the target replica count of a Role through the adapter, but it does not prove that CPU, QPS, KV, or TTFT/TPOT metric policies are sound. P/D autoscaling must also handle model loading warm-up, P/D ratio, queueing, request draining, and Scale-to-Zero cold starts.

## 9. Self-healing measurements

After deleting `mock-pd-prefill-1`, the original Pod disappeared, and the controller recreated it with the same stable name, recovering to Ready in about 5 seconds:

```text
mock-pd-prefill-1  1/1 Running  AGE=5s
RoleInstanceSet/mock-pd-prefill desired=2 ready=2
RoleBasedGroup/mock-pd          Ready=True
```

This only proves that ordinary Pod deletion can be recovered. Real multi-node inference must continue to verify:

- When one Worker fails, is only the Worker restarted, or is the entire RoleInstance rebuilt;
- Whether NCCL/RDMA connections and residual processes can be cleaned up;
- How in-flight requests, Router Endpoints, and KV Cache are invalidated;
- Whether restart backoff forms a failure storm;
- Whether the same failure triggers duplicate recovery in RBG, Runtime, and the upper-layer Gateway.

## 10. What is the relationship between enterprise TrainingJob running vLLM and RBG { #trainingjob-vllm-vs-rbg }

Many enterprises already use VolcanoJob, PyTorchJob, or self-developed TrainingJob to start multiple Pods and run vLLM multi-node multi-GPU on them. This is not wrong usage: the Job Controller provides group startup and failure retry, enterprise scripts are responsible for establishing the Ray Cluster and discovering Rank, and finally only the Head Pod's vLLM API is exposed as an online Service.

```text
TrainingJob / VolcanoJob
  ├─ Master Pod：Ray Head + vLLM API
  ├─ Worker Pod 1：加入 Ray Cluster
  ├─ Worker Pod 2：加入 Ray Cluster
  └─ Worker Pod N
```

This architecture can run long-term and is especially suitable for companies that already have a mature training platform, fixed model topology, and a small number of internal services. Its cost is that online service semantics are usually scattered across platform code and startup scripts: Head-only Service, group-level Readiness, rolling release, request draining, full-replica scaling, and NCCL/Ray failure recovery all need to be implemented yourself.

RBG does not replace vLLM's execution layer; rather, it elevates this set of script conventions into a declarative long-running workload:

```text
RoleBasedGroup
  └─ Role: backend
       replicas: 2
       leaderWorkerPattern:
         size: 4

最终含义：
  ├─ 完整模型副本 A：1 Leader + 3 Worker
  └─ 完整模型副本 B：1 Leader + 3 Worker
```

The two numbers here must not be confused:

- `leaderWorkerPattern.size` is the number of Pods **within one complete model replica**;
- `role.replicas` is the number of complete model replicas; scaling up by 1 adds an entire group of Leader/Worker;
- The upper-layer Gateway can only select the Leader/API Endpoint of a complete replica; it cannot mix Workers from different groups.

### 10.1 How much of the vLLM multi-node multi-GPU problem can RBG solve

| Problem | Does RBG solve it | Actual responsible party |
| --- | --- | --- |
| Creating a group of Leader/Worker Pods | Yes | `leaderWorkerPattern` |
| Stable numbering, Leader address, and group size | Yes | Headless Service and `RBG_LWP_*` environment variables |
| Scaling by complete model replica | Yes | Role Replica/ScalingAdapter |
| Whole-group or partial recovery after Worker failure | Configurable | RBG RestartPolicy; Runtime cleanup still must be verified |
| Obtaining all GPUs at once | Requires combination | Gang Scheduling in Volcano or Scheduler Plugins |
| How to split TP/PP/DP/EP | No | vLLM |
| Ray Actor and process execution | No | Ray/vLLM |
| NCCL/RDMA/multi-NIC selection | No | vLLM, Ray, NCCL, CNI, and node network |
| Weight download and caching | No | Object storage, P2P distribution, image, or local cache |
| Model-aware request routing | No | AIBrix, llm-d, Ray Serve, or Runtime Router |
| P/D KV Cache transfer | No | Connectors such as NIXL, Mooncake, LMCache |

Therefore, what RBG can solve is the **Kubernetes orchestration plane for multi-node multi-GPU services**; it cannot automatically make vLLM distributed communication that has not yet worked become available or faster.

### 10.2 RBG + Ray + vLLM

The easiest way to reuse existing enterprise solutions is to keep Ray and only replace the Job Controller with RBG:

```text
Leader Template
  1. ray start --head --port=6379
  2. 等待预期 Worker Ready
  3. vllm serve MODEL --distributed-executor-backend ray ...

Worker Template
  1. ray start --address=${RBG_LWP_LEADER_ADDRESS}:6379 --block
```

RBG can set different entry scripts for Leader and Worker via `leaderTemplatePatch` and `workerTemplatePatch`, and inject:

```text
RBG_LWP_LEADER_ADDRESS  Leader 的稳定 DNS
RBG_LWP_GROUP_SIZE      一份 RoleInstance 的 Pod 总数
RBG_LWP_WORKER_INDEX    当前 Pod 序号，Leader 为 0
```

For example, with two machines, 8 GPUs each, and one model replica using 16 GPUs in total, the common combination given by vLLM officially is:

```bash
vllm serve /models/example \
  --tensor-parallel-size 8 \
  --pipeline-parallel-size 2 \
  --distributed-executor-backend ray
```

TP is usually kept within the single-machine high-speed interconnect domain, with PP spanning the two nodes. TP can also be set to the total number of GPUs in the group, but this must be measured against the model, network, and hardware. All nodes need consistent images, model paths, and Python/vLLM/Ray/CUDA/NCCL versions; in multi-NIC environments, the interfaces used by `VLLM_HOST_IP`, NCCL, and Gloo must also be made explicit.

References: [vLLM Parallelism and Scaling](https://docs.vllm.ai/en/latest/serving/parallelism_scaling/), [vLLM Multi-Node Serving](https://docs.vllm.ai/en/latest/examples/ray_serving/multi-node-serving/)

### 10.3 RBG + vLLM native MultiProcessing

Current vLLM also provides a multi-node MultiProcessing mode. Conceptually mapped as:

```text
RBG_LWP_GROUP_SIZE      → --nnodes
RBG_LWP_WORKER_INDEX    → --node-rank
RBG_LWP_LEADER_ADDRESS  → --master-addr
```

Two-node illustration:

```bash
# Leader
vllm serve /models/example \
  --tensor-parallel-size 8 \
  --pipeline-parallel-size 2 \
  --nnodes 2 --node-rank 0 \
  --master-addr "$RBG_LWP_LEADER_ADDRESS"

# Worker
vllm serve /models/example \
  --tensor-parallel-size 8 \
  --pipeline-parallel-size 2 \
  --nnodes 2 --node-rank 1 \
  --master-addr "$RBG_LWP_LEADER_ADDRESS" \
  --headless
```

Production entry scripts must not hardcode `node-rank 1`; instead, they must read `RBG_LWP_WORKER_INDEX`. They must also wait for DNS, ports, and all Ranks to be ready. The native mode reduces Ray components, but enterprises must re-verify startup barriers, log aggregation, failure recovery, and observability; fewer processes does not mean operations are necessarily simpler.

### 10.4 To what extent does official vLLM support exist

The RBG v0.8 documentation explicitly provides vLLM `standalonePattern`, and the repository also has a P/D example for vLLM + Mooncake Transfer Engine. Therefore, "RBG can host vLLM" has official basis.

However, the current out-of-the-box `leaderWorkerPattern` multi-node examples mainly use SGLang or Dynamo SGLang Runtime; the repository is not yet a vLLM Ray multi-node template that can be directly copied into any enterprise network. During deployment, you still need to write Leader/Worker entry scripts and determine vLLM/Ray versions, model distribution, ports, NICs, Gang, and recovery strategy.

References: [RBG Ecosystem Integration](https://github.com/sgl-project/rbg/blob/v0.8.0-alpha.3/doc/features/ecosystem-integration.md), [RBG vLLM + Mooncake Example](https://github.com/sgl-project/rbg/blob/v0.8.0-alpha.3/examples/inference/ecosystem/mooncake/mooncake-transfer-engine/vllm-pd-disagg-with-mooncake-te.yaml)

### 10.5 Should you migrate from TrainingJob

| Current Situation | Recommendation |
| --- | --- |
| Fixed model, one or two multi-node replicas; existing Job already has Gang, Service, and full-group recovery | Keep the existing solution; migration gains are limited |
| Already standardizing on Ray and KubeRay | Prioritize evaluating RayCluster/RayClusterFleet; do not introduce RBG just to swap CRDs |
| Already fully adopted AIBrix Gateway and role-level elasticity | Prioritize StormService/RoleSet; avoid running two workload controllers |
| Multiple teams each write their own Master/Worker scripts | RBG can unify topology, discovery, update, and recovery interfaces |
| Starting to introduce Router, Prefill, Decode, KV Store multi-role | RBG's value increases significantly |
| Need Runtime neutrality and to combine SGLang, Dynamo, Mooncake, vLLM | RBG is a better candidate than internal CRDs bound to a single platform |

When migrating, do not rewrite the vLLM data path all at once. First keep the original image, Ray, and startup parameters unchanged, and only move Pod generation, DNS, status, and Service ownership to RBG; compare startup time, TTFT, TPOT, Goodput, and recovery time using the same model, input length, and concurrency, then decide whether to expand scope.

## 11. Moving from Mock to Real Inference

Recommended in increasing risk order:

1. Keep `standalonePattern`, first replace NGINX with a single-GPU SGLang/vLLM aggregated service;
2. Then add Router, Prefill, Decode, and verify OpenAI-Compatible requests and KV Connector;
3. Connect real load metrics for P/D separately, only observe the recommended replica count, do not auto-execute yet;
4. Use `leaderWorkerPattern` to create a cross-node Engine, verifying Rank discovery, Gang, topology, and full recovery;
5. Finally add Higress or AIBrix Gateway, stress-test the extra hop, SSE, retries, timeouts, and failure semantics.

The RBG official repository already provides SGLang aggregation/P-D, multi-node Leader/Worker, and Dynamo, Mooncake Transfer Engine/Store examples. The examples prove that upstream provides integration entry points; this does not mean the target GPU, network, Runtime, and model combination has been production-verified.

Reference: [RBG Inference Examples](https://github.com/sgl-project/rbg/tree/v0.8.0-alpha.3/examples/inference), [Mooncake RBG Integration](https://kvcache-ai.github.io/Mooncake/deployment/kubernetes-deployment-guide/rbg-integration.html)

## 12. Boundaries of the sr1 Control-Plane Experiment

sr1's CPU Mock only proves RBG installation, role dependencies, service discovery, role-level scaling, and ordinary Pod self-healing. It does not prove model loading, GPU communication, Ray Rank, P/D Router, or KV Cache transfer. To avoid using Mock results to endorse real inference, the next round will re-validate with real models on a production GPU cluster.

## 13. Real Measurements of Three Architectures on Production GPUs

Production validation follows three constraints: only use the standard inference node pool, do not modify existing AIBrix/Higress services, and all new models use independent names. Each manifest first passes API Server Dry Run and controller convergence checks with `replicas: 0`, then scales up one by one to 1; any anomaly can be scaled back to 0 by the exact RBG name.

To make the RBG vs. AIBrix difference comparable, the Ray and P/D experiment groups did not rebuild images: they directly reuse the same runtime image, model directory, precision, and vLLM parameters as the existing AIBrix workloads. The main change is in Kubernetes orchestration objects, not the Runtime.

| Architecture | Model & Topology | RBG Expression | Measured Result |
| --- | --- | --- | --- |
| Single-GPU aggregated inference | 7B distilled model, 1 Pod × 1 GPU | `backend` Role + `standalonePattern` | Pod Ready, OpenAI-Compatible request succeeded |
| Ray multi-node model parallelism | 32B BF16, 2 nodes × 1 GPU, PP=2 | `head`, `worker` two Roles, one `standalonePattern` each | Ray aggregated 2 GPUs, 17 weight shards loaded, request returned `RBG_RAY_OK` |
| NIXL P/D separation | 32B GPTQ Int4, Prefill and Decode each 1 node × 1 GPU | `prefill`, `decode` two Roles, one `standalonePattern` each | Both sides NIXL/UCX Ready, request via AIBrix Gateway returned `RBG_PD_OK` |

All three Pod groups use hard Pod Anti-Affinity; Ray Head/Worker and Prefill/Decode all actually landed on different hosts, and the Restart Count remained 0 throughout the validation. This round added up to 5 GPUs at peak, without tolerating taints on reserved pools or offline nodes.

### 13.1 Single-GPU `standalonePattern`

The single-GPU scenario validates the shortest path first: RBG creates RoleInstanceSet, RoleInstance, Pod, and Headless Service, while vLLM itself still provides the OpenAI API.

```text
RoleBasedGroup
  └─ backend × 1
       └─ vLLM Pod × 1 GPU
```

There is no inherent performance difference from Deployment. RBG's value is that the same API can later add Router, Worker, Prefill, Decode, or Store Roles; if the service will always be a single stateless Pod, Deployment/KServe is usually simpler.

### 13.2 Ray Two-Node `head + worker`

The production cluster did not install the LeaderWorkerSet API for this experiment, so two RBG Roles express the Ray Head and Worker:

```text
RoleBasedGroup
  ├─ head × 1：ray start --head，等待 Ray GPU=2，再启动 vLLM API
  └─ worker × 1：通过 RBG 稳定 DNS 加入 Head

vLLM：TP=1、PP=2、distributed-executor-backend=ray
```

The Headless Service auto-generated by RBG provides stable Pod DNS even without a Service Port; scripts still need to explicitly use Ray ports. The Head log first continuously shows `GPU=1`, and after the Worker image is pulled and joins, it becomes:

```text
Active Ray nodes: 2
GPU: 2.0/2.0 reserved in placement groups
accelerator type: 2 × L20
```

Subsequently, vLLM's two `RayWorkerWrapper` run on the two nodes respectively, and the 32B model completes PP=2 initialization. The real request returns:

```json
{"model":"rbg-qwen2-5-32b-ray-2n","content":"RBG_RAY_OK"}
```

From Pod creation to all Ready took about 8 minutes this time, of which the Worker's node had no image cache and image pulling took about 4 minutes. This is not a performance benchmark, but it exposes a production fact: the startup ceiling of a multi-node service is determined by the slowest node, the Head must wait for the full GPU count, and Startup Probe, release timeout, and scale-up debounce must all cover image pulling and model loading.

### 13.3 RBG Orchestrates Roles, AIBrix Completes P/D Routing

Both P/D ends fully reuse the vLLM/NIXL image and GPTQ model used by the existing StormService; RBG only takes over Pod lifecycle:

```text
AIBrix Gateway / P-D Router
  ├─ RBG prefill Role：vLLM + NixlConnector
  └─ RBG decode Role：vLLM + NixlConnector
```

After adding AIBrix model name, port, engine, and `role-name` labels, plus the `routingStrategy=pd` annotation to the two Pods, the existing Gateway can discover them. Both sides load about 18 GiB of weights, initialize the UCX Agent, and reserve about 21 GiB of KV Cache for the 16K context.

The desensitized log for the same Request ID shows:

```text
Prefill: max_tokens=1, do_remote_decode=true
Decode:  do_remote_prefill=true,
         remote_engine_id=<PREFILL_ENGINE>,
         remote_block_ids=<BLOCKS>
```

Finally, the Gateway returns `RBG_PD_OK`. This proves that RBG-managed Pods can join the current AIBrix P/D data path, but do not describe it as "RBG itself implements P/D": request splitting, P/D pairing, and KV Transfer parameters are still generated by the AIBrix Gateway, and what actually moves the KV is vLLM NIXL/UCX.

### 13.4 DeepSeek V4 Flash SGLang Two-Node Real Measurement

Beyond the vLLM path above, the repository also prepares a set of DeepSeek V4 Flash 0731 SGLang P/D manifests, using one RBG to express one Prefill Role and one Decode Role, each Role being a single node with 8 GPUs at TP=8. Regular deployment distributes the two Pods to different H20 nodes via anti-affinity; the RDMA-specific test, in order to reuse two already cordoned isolated nodes, instead uses `spec.nodeName` to directly bind each to a node, without ever executing `uncordon`. SGLang uses NIXL to transfer KV, and the AIBrix Gateway selects both ends based on `role-name`, `roleset-name`, and model labels, and injects SGLang's bootstrap parameters.

The actual experiment used two 8×H20 96 GB nodes. Both Engines completed DeepSeek V4 Flash weight loading, Marlin preparation, NIXL 1.3.2 and UCX initialization, and RBG eventually became Ready; the initial TCP baseline spread Pods via anti-affinity, and the subsequent RDMA phase switched to directly binding the isolated nodes respectively. In the first cold start, the slower node took about 2 minutes to pull the large image, with about 157 GiB of model synchronization and roughly 295 seconds of Marlin weight preparation/JIT on one side constituting the main wait time.

This time, no SGLang Router Role was deployed in RBG, because the cluster already has an AIBrix Gateway, which handles request-level P/D pairing and bootstrap parameter injection. RBG only manages the Prefill/Decode lifecycle. If not using AIBrix, only then should an `router` Role be added per the RBG official example, exposing only the SGLang Router externally; do not chain two Routers, otherwise there will be two layers of role selection, timeout, and retry state.

The first request sent immediately after the service entered Ready hit an upstream timeout; after SGLang's disaggregation warm-up explicitly completed, deterministic requests returned `PD_OK` within 0.25 seconds. The steady-state short test results are as follows, all requests succeeded:

| Scenario | Output tok/s | p95 TTFT | p95 TPOT | p95 ITL | p95 E2E |
| --- | ---: | ---: | ---: | ---: | ---: |
| 128/64, C=1 | 93.32 | 231.42 ms | 7.24 ms | 7.46 ms | 686.99 ms |
| 128/64, C=8 | 438.42 | 874.42 ms | 8.26 ms | 8.59 ms | 1400.97 ms |
| 4096/128, C=4 | 216.50 | 1431.91 ms | 7.94 ms | 8.44 ms | 2437.57 ms |

The current Decode per-token interval is stable, but Prefill, KV transfer, and request coordination costs are on the high side. The 4K scenario's p95 TTFT is close to the previous vLLM Combined TP=8's ~1.39 seconds, output throughput is about 21.8% lower, and P/D uses twice the GPUs. Since Runtime and optimization parameters still differ, this can only be used to determine next steps, not as a strict framework ranking.

Resources can only accommodate two nodes, so strict A/B does not add a third service; instead it uses serial switching: first save the P/D data, stop the dual-role RBG, then use one of the nodes to deploy Combined TP=8 with the same SGLang image, model, and parameters; the client, Gateway, random seed, request set, and warm-up all remain unchanged, and tokens/s/GPU is compared at the same time. RDMA must also be validated as a single variable; you cannot claim RDMA is enabled just by changing one UCX environment variable. The next section records the complete evidence chain from device injection to data-plane counters.

### 13.5 Enabling RDMA on cordon Nodes: From "Device Visible" to "Real Traffic"

The test nodes were already cordoned to isolate experiment traffic. `nodeSelector`, affinity, and toleration still go through the scheduler, and new Pods cannot land on cordon nodes; after setting `spec.nodeName`, the Pod no longer goes through scheduler placement, so it can be taken over by the corresponding node's kubelet **without executing `uncordon`**. This approach is only suitable for short-term experiments on known nodes: it bypasses the scheduler's cordon, resource headroom, and topology checks, so GPU, RDMA, CPU, and memory sufficiency must be manually confirmed before submission.

`nodeName` also does not mean tolerations can be removed. A HostPath space preflight successfully bound directly to the node, but because it did not tolerate the isolated node's `NoExecute` taint, the Taint Manager immediately marked it for deletion; it only ran stably after adding the same toleration as the formal Engine. Therefore, two phases must be distinguished: cordon/`NoSchedule` mainly prevents scheduler placement, while `NoExecute` can still evict a Pod after it is bound.

Merely requesting the RDMA Extended Resource is not enough. The first Preflight could see the `/dev/infiniband/uverbs*` character device but had no RDMA network interface; moreover, the script hardcoded the device name as `uverbs0`, but the actual allocation went to a different `uverbs`, causing a false failure. The corrected check enumerates all devices and simultaneously requires the Pod to have:

```yaml
metadata:
  annotations:
    tke.cloud.tencent.com/networks: "tke-route-eni,tke-rdma-macvlan"
spec:
  nodeName: <CORDONED_RDMA_NODE>
  containers:
    - resources:
        requests:
          tke.cloud.tencent.com/tke-shared-rdma: "4"
        limits:
          tke.cloud.tencent.com/tke-shared-rdma: "4"
      securityContext:
        capabilities:
          add: ["IPC_LOCK"]
```

Among these, the CNI annotation is responsible for creating the RDMA Macvlan network, the Extended Resource is responsible for allocating devices, and `IPC_LOCK` allows the communication library to lock memory. After the formal Pod starts, each side sees 4 RDMA devices, 4 RDMA addresses, and valid GIDs; the SGLang log shows NIXL 1.3.2, UCX backend, and P/D warm-up all complete. A long-Prompt request via the AIBrix Gateway returns the expected response, while the Prefill-side port send counter increases by about 742 MiB and the Decode-side receive counter increases by about 716 MiB, proving that KV data actually traverses RDMA, not merely that "the Pod has devices."

To separate network from Runtime, `ib_write_bw` was then run directly between the two Engine Pods:

```bash
# Decode 侧
ib_write_bw -d mlx5_bond_0 -x 3 -F --report_gbits -s 65536 -n 5000

# Prefill 侧，连接 Decode 的 RDMA 地址
ib_write_bw -d mlx5_bond_0 -x 3 -F --report_gbits -s 65536 -n 5000 <DECODE_RDMA_IP>
```

The average bandwidth for RoCE v2 GID index 3 is **195.25 Gb/s**, with a peak of **195.45 Gb/s**; all ports' `xmit_wait`, discard, receive error, remote physical error, symbol error, and link recovery are all 0. At this point, GPU nodes, RDMA device injection, and underlying RoCE fabric bandwidth insufficiency can be ruled out.

Then, using exactly the same devices and parameters, only the GID index was changed to 2. The connection was established, but the client immediately reported completion errors (syndrome `0x81`) on the first batch of 128 Work Requests, producing no effective throughput; the server also terminated due to address exchange failure. This single-variable comparison shows that the current network must explicitly use the already-validated RoCE v2 GID index 3 and cannot rely on UCX auto-selection, so the formal checklist was supplemented with:

```yaml
env:
  - name: UCX_IB_GID_INDEX
    value: "3"
```

However, the first round of application stress testing after enabling RDMA actually regressed severely:

| Scenario | Requests Succeeded | Output tok/s | p95 TTFT | p95 TPOT | p95 ITL |
| --- | ---: | ---: | ---: | ---: | ---: |
| 128/16, C=1, exploratory small sample | 2/2 | 1.31 | 4687.83 ms | 542.36 ms | 956.27 ms |
| 128/16, C=8, exploratory small sample | 8/8 | 1.78 | 61486 ms | 521.54 ms | 1042.65 ms |
| 128/16, C=1, fixed GID index 3 | 2/2 | 1.35 | 4540.22 ms | 541.88 ms | 971.10 ms |

This small sample set was used only to locate the anomaly and cannot serve as the final performance conclusion for RDMA. During stress testing, GPU SMs were idle many times; the Decode log could still reach approximately 89 token/s after actually entering generation, while a long time was consumed in the KV transfer and coordination phase corresponding to `transfer-req`; concurrent requests also exhibited obvious serial waiting. Combined with the raw RDMA result of 195 Gb/s, the problem scope has narrowed from "whether the hardware or network is healthy" to **NIXL/UCX device, GID, and multi-rail selection, memory registration, and request coordination**.

After fixing GID index 3, functional requests succeeded, but the C=1 small-sample performance was almost identical to before the change. The raw link difference between index 2/3 proves that GID 3 is a necessary configuration for the current RoCE network, but it is not the root cause of the slow application layer; "correcting a misconfiguration" must not be written up as "the performance problem has been fixed."

Subsequent strict A/B testing proceeds in the following order, avoiding changing multiple Runtime variables at once:

1. Keep GID index 3, compare `UCX_NET_DEVICES=all` against explicit single rail, to check whether the issue is multi-rail selection or registration cost;
2. If single rail is still anomalous, add NIXL/UCX-level tracing to break down memory registration, metadata exchange, KV Page transfer, and completion notification latency;
3. Compare RDMA P/D, TCP P/D, and the same-image Combined TP=8, while recording per-GPU throughput and resource cost;
4. If TCP P/D is still slow, switch the execution topology to the community-validated TP=4, DP=4, DP Attention + DeepEP, to avoid mistaking the not-yet-validated pure TP=8 + Marlin FP4 combination for a network problem.

The key lesson from this process is: **device visibility, NIXL showing UCX Ready, request success, and RDMA high bandwidth are four conclusions at different levels.** Only port counters during application requests can prove the data path, and only A/B testing on the same request set can prove performance gains.

#### 13.5.1 Same-Image Combined Control Narrows the Scope to the P/D Path

To determine whether the anomaly came from the DeepSeek V4 Runtime itself or from the P/D-specific data path, the dual-role RBG was stopped, and the same SGLang image, same model, same TP=8, and same inference parameters were deployed serially on the original Decode node as a Combined Engine. Combined does not enable `disaggregation-mode`; Prefill and Decode both complete within the same 8-GPU Pod. The model continued to hit HostPath, while the JIT Cache was changed to a HostPath isolated by Runtime version.

First startup took approximately 11 minutes total: weight loading, FP8 conversion, and MHC warmup took about 278 seconds, and Decode CUDA Graph capture took about 356 seconds. The process tree showed `cicc`, NVCC, and Ninja continuously working, so this period without log refresh was not a Pod hang. Subsequent rebuilds with the same Runtime can reuse the final `.so`, CUBIN, and other JIT artifacts, but still must perform weight read-in, GPU memory allocation, and CUDA Graph capture.

To avoid external dataset dependencies, the stress-test client used a local Tokenizer to generate fixed-length `random-ids`. The first encounter with a new concurrency shape and a long-Prompt shape each showed a one-time stall; immediately re-running with the same parameters returned to stable behavior, so the table below uses the re-run data:

| Scenario | Path | Succeeded | Output tok/s | p95 TTFT | p95 TPOT | p95 ITL | p95 E2E |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 128/16, C=1 | RDMA P/D, fixed GID 3 | 2/2 | 1.35 | 4540.22 ms | 541.88 ms | 971.10 ms | - |
| 128/16, C=1 | TCP P/D | 2/2 | 1.66 | 1909.39 ms | 536.97 ms | 993.41 ms | 9803.95 ms |
| 128/16, C=1 | Combined TP=8 | 2/2 | 58.09 | 164.50 ms | 7.12 ms | 13.29 ms | 271.29 ms |
| 128/16, C=8 | RDMA P/D, multi-rail | 8/8 | 1.78 | 61486 ms | 521.54 ms | 1042.65 ms | - |
| 128/16, C=8 | TCP P/D | 8/8 | 3.44 | 29212.21 ms | 655.13 ms | 1114.56 ms | 37078.84 ms |
| 128/16, C=8 | Combined TP=8, re-run | 8/8 | 283.04 | 323.50 ms | 8.49 ms | 16.60 ms | 441.44 ms |
| 4096/128, C=4 | Combined TP=8, re-run | 4/4 | 329.36 | 555.85 ms | 7.85 ms | 15.76 ms | 1544.05 ms |

The Combined output throughput for C=1 and C=8 was approximately 43x and 159x that of the anomalous RDMA P/D, respectively, while TPOT recovered from about 0.52–0.54 seconds to 7–9 ms. This rules out the DeepSeek V4 core inference, model weights, Marlin, and single-node TP=8 in the same image as the primary root cause; the problem has converged to the P/D-specific data path or Decode mode.

The TCP control kept the same two Engines, model, TP=8, and request set, changing only `UCX_TLS` from `rc` to `tcp,cuda_copy,cuda_ipc`. Although TCP shortened part of the TTFT, TPOT remained at about 0.54–0.66 seconds, the same anomalous order of magnitude as RDMA P/D; the ITL metric exposed by the Decode Engine itself also clustered at 0.4–1 seconds, indicating the slowness occurs inside the Engine rather than in the Router's streaming return to the client. This rules out RDMA/RoCE, multi-rail, and GDR as the primary root cause.

Code inspection also ruled out an easily misjudged parameter: `disaggregation_decode_polling_interval=1` represents the Scheduler Loop interval, not a 1-second wait per token. Decode mode forces the use of Chunk Cache when Radix Cache is not enabled, and DeepSeek V4's Hybrid SWA is incompatible with `disaggregation-decode-enable-radix-cache`, so this switch cannot be enabled as a workaround.

The strongest root-cause candidate at present is **the DeepSeek V4 P/D execution topology not matching the community-validated path**. This run used pure TP=8 per side, Marlin FP4 Experts, without DP Attention or DeepEP; the SGLang upstream P/D CI added for DeepSeek V4 uses TP=4 per side, DP=4, `--enable-dp-attention`, and `--moe-a2a-backend deepep`. This does not yet prove a defect in any particular kernel line, but it has narrowed the next round of testing to execution-topology A/B rather than continuing to change RDMA parameters. References: [SGLang DeepSeek V4 P/D CI PR #24973](https://github.com/sgl-project/sglang/pull/24973), [SGLang P/D Disaggregation documentation](https://github.com/sgl-project/sglang/blob/main/docs/advanced_features/pd_disaggregation.md).

A source-level verification of the image was then performed. The `sglang` version inside the image is `0.0.0.dev1+g52afe87a0`, corresponding to upstream commit `52afe87a08c6aa049c52f9507b4f0ca26cecb562`. SGLang fixed the HiSparse P/D page-index mismatch for DeepSeek V4 in [PR #31901](https://github.com/sgl-project/sglang/pull/31901): the old path used the Host KV Page ID for both Host and Device targets, which could directly cause incorrect output. The current image is 271 commits ahead of the merge commit of that fix, so this round of issues can no longer be attributed to "the image is missing #31901."

However, "contains a known fix" does not mean the current combination has been community-validated. In the 0731 official recipe, the validated low-latency path for H200 uses TP=4; there is no measured P/D unit for H20, pure TP=8 per side, and Marlin FP4 Experts. Upstream still has an open [issue #33397](https://github.com/sgl-project/sglang/issues/33397) reporting output corruption that worsens with concurrency under 0731 with DSV4, FP8 KV, and batching, with reproduction topologies extending to non-P/D, no-DP-Attention, and other combinations. This issue is not the same proven root cause as this round's "P/D Decode extremely slow per token," but it does show that the 0731 DSA/KV path is still in a rapid-fix period.

The current conclusion is therefore: **there is no evidence that the SGLang image version is too old or the weights are corrupted; there is evidence that H20 + 0731 FP4 + Marlin + pure TP=8 P/D lacks upstream validation and carries an adjacent accuracy risk.** The next step should prioritize reproducing the community's TP=4/DP=4 + DP Attention + DeepEP topology, or first establish a control group using officially validated hardware/recipe; until then, replacing the image with another from the same series should not be treated as a root-cause fix.

#### 13.5.2 Why 8 GPUs Have Only 4 RDMA NICs

The Kubernetes RDMA Extended Resource capacity and allocatable amount on the experimental node are both 4, and the Pod can see four devices from `mlx5_bond_0` to `mlx5_bond_3`, each port reporting 200 Gb/s. `nvidia-smi topo -m` shows NIC0/NIC1 on NUMA 0, covering the first four GPUs; NIC2/NIC3 on NUMA 1, covering the last four GPUs, where each NUMA has two GPUs with `PIX` to the corresponding NIC, and the remaining same-NUMA GPUs are `NODE`. The 8 GPUs are interconnected via NVLink.

Therefore, an 8-GPU Pod requesting 4 RDMA resources matches the machine's real topology and does not require a 1:1 GPU-to-HCA mapping. Requesting 8 would exceed node capacity. The theoretical single-rail link rate is 200 Gb/s, and this raw test measured about 195 Gb/s; the theoretical four-rail link aggregation is about 800 Gb/s, so the single-port and four-port link ceilings are not the same, but the application does not automatically get four times the speed. Only if UCX/NIXL correctly stripes sufficiently large concurrent data, and GPU Memory Registration, PCIe/NUMA, and completion synchronization do not become bottlenecks, can the aggregated ceiling be approached. For small requests, single serial transfers, or compute-bound scenarios, the measured results for single-port and four-port may even be close.

Subsequent RDMA tests should, with the Pod still injected with four devices, first explicitly specify one `mlx5_bond_<N>:1` to test single rail, then use `UCX_NET_DEVICES=all` to test multi-rail. Only this way can "RDMA's benefit over TCP" be distinguished from "multi-rail's benefit over single rail."

Additionally, the earlier DeepSeek V4 vLLM P/D baseline did not use RDMA: both 8-GPU Engines explicitly set `UCX_TLS=tcp,cuda_copy,cuda_ipc`, had no RDMA CNI annotations, and did not request RDMA Extended Resources. Each Engine is single-node TP=8 internally, and only the NIXL/UCX KV Transfer crosses nodes, so the accurate description should be **NIXL over TCP**. Subsequent vLLM RDMA A/B testing must also retain this TCP baseline; "using NIXL" must not be equated with "using RDMA."

### 13.6 Using HostPath to Cache Large Models, Avoiding Re-Sourcing on Every Rebuild

RDMA parameter A/B testing requires rebuilding the Engine multiple times. The original checklist placed the approximately 157 GiB model in `emptyDir`, and the cache disappeared when the Pod was deleted, requiring two copies of the model to be re-synced from object storage each round—both slow and generating meaningless network traffic. The local ext4 root disks of the two isolated nodes each have about 935 GiB of available space, so the special test changed the model volume to node-level HostPath:

```yaml
volumes:
  - name: model
    hostPath:
      path: /tmp/aik8s-model-cache/deepseek-v4-flash-0731
      type: DirectoryOrCreate
```

The Init Container does not merely check whether the directory exists; it checks `config.json`, the weight index, the 48 Safetensors shards, and the completion marker. Only when all checks pass does it exit directly; otherwise it deletes the completion marker, continues incremental sync, and re-creates the marker after successful verification. This way, an interrupted download will not misjudge a partial result as a usable cache, and subsequent rebuilds on the same node can pass Init within seconds.

While switching the volume template, an RBG lifecycle detail was encountered: the upper-level `RoleInstanceSet` had already been updated to HostPath, but the old `RoleInstance` still being started retained the emptyDir template. At this point, deleting only the Pod would cause the old `RoleInstance` to rebuild it from the old template. In the experiment, two `RoleInstance` that had not yet reached Ready were deleted, and `RoleInstanceSet` recreated them from the latest revision, which is when the switch to HostPath actually took effect.

HostPath here is used only as a **disposable node cache**, not persistent storage: the Pod must return to the same node to hit the cache, and node reinstallation, disk failure, or `/tmp` cleanup will all make the cache disappear. Production environments should use dedicated local cache disks with a node pre-warming mechanism, and retain object storage as the authoritative source; if models need to be shared across nodes or centrally governed, parallel file systems, image-based distribution, or P2P model distribution should still be evaluated.

### 13.7 What Was Actually Compiled During Cold Start

Model sync completion does not mean the Engine will be Ready quickly. This H20 startup log showed `DeepSeek V4 MHC prenorm prewarm: 16 n_splits buckets` after weight loading, and multiple groups of `nvcc` appeared in the process tree. Directly inspecting the container file system, the artifacts generated on-site can be divided into three categories:

| Artifact | Measured path | Content |
| --- | --- | --- |
| MHC/DeepGEMM Kernel | `/root/.cache/sglang/deep_gemm/cache/kernel.sm90_tf32_hc_prenorm_gemm.<hash>/kernel.cubin` | CUDA binaries generated for H20 `sm90` and different `n_splits` buckets; this round ultimately generated 16 CUBINs, directory about 688 KiB |
| SGL Kernel communication extension | `/root/.cache/tvm-ffi/sgl_kernel_jit_communicator_<hash>__arch_9.0a__tvmffi_0.1.11/` | `main.cpp`, `cuda.cu` compiled via Ninja/NVCC into `sgl_kernel_jit_communicator_*.so` |
| CUDA IPC and Triton auxiliary extensions | `/root/.cache/tvm-ffi/sgl_kernel_jit_cuda_ipc_<hash>__arch_9.0a__tvmffi_0.1.11/*.so`, `/root/.cache/sglang/triton/<hash>/cuda_utils.cpython-312-x86_64-linux-gnu.so` | Runtime extensions such as CUDA IPC, Triton Driver |

FlashInfer's cache root directory is at `/root/.cache/sglang/.cache/flashinfer/<version>/<arch>/`. `/tmp/tmp*/tvm_kernels.cu`, `tmpxft_*`, LLVM bitcode and preprocessed files are only NVCC intermediate products and should not be placed in the image. You can use the following command to view the final files:

```bash
find /root/.cache/sglang /root/.cache/tvm-ffi \
  -type f \( -name '*.cubin' -o -name '*.so' -o -name 'build.ninja' \) \
  -ls
```

These final `.cubin` and `.so` are very small, yet may take minutes to generate on-site, so precompilation is valuable. However, they are not universal binaries; they are bound to at least the following version fingerprints:

In this round's logs, MHC prewarm starts from `19:36:47`; after the 16 CUBINs are generated and entering `Load weight end` takes about `19:40:55`, roughly **248 seconds**; the entire `Load weight` phase is about **611 seconds**. Therefore, precompilation is expected to save about 4 minutes of JIT, but cannot eliminate all 611 seconds.

- GPU architecture; this round's directory and filenames explicitly contain `sm90`/`arch_9.0a`;
- SGLang, SGL Kernel, DeepGEMM and specific Kernel source code;
- CUDA Toolkit/Driver, Torch, Triton, TVM-FFI and FlashInfer;
- Python ABI; this round's auxiliary extensions are CPython 3.12, x86_64.

It is recommended to run a complete warm-up on the same H20 model with a fixed Runtime image and parameters, export `/root/.cache/sglang` and `/root/.cache/tvm-ffi`, then build a derived image with the complete version fingerprint. Regenerate after upgrading any key dependency; do not reuse old caches across CUDA, Python or GPU architectures.

There is also an easily overlooked mount issue: this round's Pod mounts `/root/.cache` as `emptyDir`. If files are written directly to the same path in the image, the runtime Volume will completely shadow them. You can place the precompiled artifacts in the image's `/opt/sglang-prebuilt-cache`, then have an Init Container copy them to the writable `/root/.cache`; or remove the overlay mount. Precompilation can only save JIT; weight reading and GPU memory loading, some Marlin weight rearrangement, NIXL initialization, warm-up and CUDA Graph capture still need to execute at each process startup.

References: [Tencent Cloud TKE RDMA Network Usage](https://cloud.tencent.com/document/product/457/116720), [OpenUCX Configuration](https://openucx.readthedocs.io/en/master/faq.html)

The public list still uses inaccessible placeholder images and fake Secrets, and does not include internal registry, object storage, namespace, nodes or credentials.

Full materials: [DeepSeek V4 Flash: RBG + SGLang Dual-Machine P/D Separation](https://github.com/runzhliu/aik8s/tree/main/examples/deepseek-v4-flash-sglang-rbg-pd).

## 14. Comparing RBG and AIBrix under the same image and model { #rbg-vs-aibrix-production }

The most valuable comparison this time is not "whose YAML is shorter" but who owns which layer of state. After Ray and P/D both use the same Runtime, we get the following responsibility differences.

| Dimension | RBG mode | AIBrix mode | Practical judgment |
| --- | --- | --- | --- |
| Top-level object | `RoleBasedGroup` | Ray uses `RayClusterFleet/RayCluster`; P/D uses `StormService/RoleSet` | RBG uses one set of generic Role APIs; AIBrix provides scenario-specific objects |
| Pod ownership | RBG → RoleInstanceSet → RoleInstance → Pod | Fleet → RayCluster → KubeRay Pod, or StormService → RoleSet → Pod | The same Pod can only be owned by one controller |
| Ray Head/Worker | This round required writing startup, GPU wait and DNS join scripts ourselves | KubeRay natively expresses Head/Worker and Ray state | When already using KubeRay, the AIBrix path saves more glue code |
| Multi-node full replicas | Can be expressed with Role + Pattern; scaling semantics defined by manifest design | RayClusterFleet manages multiple RayClusters | Both can do it; must confirm whether scaling targets Worker or the full Engine |
| P/D Pod orchestration | Prefill/Decode are ordinary Roles and can combine other Runtimes | StormService/RoleSet natively expresses Prefill/Decode | RBG is more neutral; StormService is more tightly coupled to the AIBrix ecosystem |
| P/D request pairing | RBG does not handle requests; needs AIBrix/SGLang/Dynamo Router | AIBrix Gateway natively routes by Role and injects KV parameters | Deploying only RBG CRDs does not automatically provide P/D |
| Model-aware routing | No built-in Gateway; connects external routing via Pod labels | Gateway, model discovery and routing policies belong to the same platform | Existing AIBrix users continuing with AIBrix is most natural |
| Service discovery | One stable Headless Service per Role, with RBG topology variables injected | KubeRay Head Service, Storm/RoleSet labels and Endpoint | RBG is more unified for generic multi-role peer discovery |
| Role-level scaling | ScalingAdapter exposes the Scale subresource and can connect to HPA/KEDA | PodAutoscaler can scale by Role and model metrics | RBG is more generic; AIBrix understands inference metrics and P/D semantics better |
| Update and recovery | Role-level policies, dependencies, stable identity and coordination policies | Storm sequential/in-place updates; KubeRay/Fleet each have their own recovery semantics | Need actual testing of node failure and request draining; cannot rely only on CRD fields |
| Gateway composition | Naturally connects to Higress; add AIBrix etc. when model routing is needed | Common pattern is Higress → AIBrix Gateway → Runtime | Enterprise entry and model routing should remain layered |
| Runtime preference | SGLang, Dynamo, Mooncake, vLLM and multiple Runtimes | Current production chain centered on vLLM and AIBrix Gateway | Runtime neutrality is the main reason for choosing RBG |
| Maturity risk | Current release is still alpha; API and operational experience are newer | More components but already has a complete routing, scaling and tested chain | Production defaults to the mature path; RBG starts from side-channel models |

### 14.1 Recommendations for the current enterprise environment

If the enterprise already runs multi-machine vLLM with AIBrix `RayClusterFleet` and P/D with `StormService`, **do not migrate to RBG just to unify CRDs**. The existing path already chains KubeRay, P/D Router, model discovery and autoscaling; migration would turn some built-in semantics back into startup scripts and label conventions.

RBG is better suited for these scenarios:

- The same platform needs to carry SGLang, Dynamo, Mooncake, vLLM and custom Runtimes simultaneously;
- A service has Router, KV Store, Metadata, Tokenizer and other roles beyond P/D;
- Need stable identity, role dependencies, coordinated updates or full-replica lifecycle;
- Want the workload controller decoupled from the AIBrix Gateway, allowing the routing layer to be replaced in the future.

`AIBrix Gateway + RBG Pod` has been validated in this functional experiment, but it is currently a **label-contract-based composition**, not AIBrix controllers natively managing RBG. Production should also add model registration latency, Endpoint consistency during Pod rolling, label contract regression and dual-controller upgrade matrix.

### 14.2 Do not confuse two kinds of "multi-machine multi-GPU"

| Mode | What the two GPUs are doing | Scaling unit |
| --- | --- | --- |
| Ray PP=2 | Two ranks jointly execute one model Engine | One complete Head + Worker |
| P/D separation | Two complete Engines handle Prefill and Decode separately, then transfer KV | Prefill Pool and Decode Pool can scale independently |

RBG and AIBrix both just place these Runtimes on Kubernetes. Choosing a CRD does not change the computational nature of PP vs P/D, nor does it automatically make either mode higher throughput.

## 15. Gaps exposed by production testing

- Ray Worker nodes' first pull of large images significantly slows the whole group becoming Ready; image pre-warming, P2P distribution or node cache should be built;
- vLLM/c10d reported IPv6 unavailable warnings during address family probing on Pod FQDN; although IPv4 fallback succeeded this time, production should still fix `GLOO_SOCKET_IFNAME`, `NCCL_SOCKET_IFNAME` and verify multi-NIC;
- The current Ray image lacks some `ray[default]` Dashboard dependencies; this does not affect inference but loses some Ray metrics and page capabilities;
- The P/D sample enables the vLLM Development Endpoint for AIBrix routing compatibility; it cannot be directly exposed to untrusted networks;
- The RBG Headless Service was mainly used for DNS this time; Gateway Endpoint comes from Pod labels; it needs to be clarified which system is responsible for port discovery and Ready filtering;
- No testing of Worker/Prefill/Decode node failure, network partition, rolling upgrade, request cancellation and streaming response interruption;
- No TTFT, TPOT, throughput, Goodput and cost comparison under the same traffic and concurrency, so performance cannot be inferred from "request success";
- No verification of `leaderWorkerPattern`, Gang Scheduling, ScalingAdapter metrics loop and Scale-to-Zero;
- Higress has not taken over the new sample entry; the existing external access path remains unchanged.

## 16. Production acceptance checklist

- [x] RBG version pinned; Chart, Controller image and Kubernetes version recorded;
- [x] Controller uses two replicas spread across different nodes;
- [x] Controller, CRD, Webhook and certificate injection working normally;
- [x] Role startup dependencies, Headless Service, topology variables and CPU Mock verified;
- [x] Decode Role completed 2→3→2 independent scaling, with field ownership protection verified;
- [x] Prefill Pod recovers after deletion; RBG returns to Ready;
- [x] Single-GPU real model and OpenAI-Compatible API verified;
- [x] Ray two-node, 2 GPU, PP=2 with real requests verified;
- [x] Prefill/Decode cross-node, NIXL KV Transfer and Gateway requests verified;
- [x] RBG and AIBrix comparison uses the same image, model and key Runtime parameters;
- [ ] Multi-node Gang, GPU/NIC topology and full Engine failure recovery verified;
- [ ] HPA/KEDA metrics, pre-warming, draining and debouncing verified;
- [ ] Streaming response, cancellation, timeout, node failure and network jitter verified;
- [ ] Upgrade, rollback, CRD conversion, backup and disaster recovery verified;
- [ ] Higress/AIBrix/RBG/Runtime routing, scaling, retry and failure responsibilities have only one authoritative source.

## Further reading

- [RBG Installation](https://github.com/sgl-project/rbg/blob/v0.8.0-alpha.3/doc/install.md)
- [RBG Deploy Inference Service](https://github.com/sgl-project/rbg/blob/v0.8.0-alpha.3/doc/best-practice/zh/01-deploy-inference-service.md)
- [AIBrix Existing Cluster Practice](aibrix-existing-cluster.md)
- [AIBrix Real GPU: Two Machines, P/D and Eight-Node Fragmented Cards](aibrix-gpu-multinode-pd-production.md)
- [Higress AI Gateway Practice](../inference/higress-ai-gateway.md)
- [Multi-Machine and Separated LLM Inference](../inference/distributed-serving.md)
