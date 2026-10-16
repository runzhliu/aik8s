---
title: "Multi-Machine and Disaggregated LLM Inference"
description: "Design multi-machine model replicas, LeaderWorkerSet, Prefill/Decode disaggregation and KV transfer, and compare AIBrix, llm-d, KServe, Dynamo, Ray Serve and the vLLM Production Stack"
status: evolving
last_reviewed: 2026-08-07
---

# Multi-Machine and Disaggregated LLM Inference

When the model, KV Cache, or target throughput exceeds the capacity of a single machine, an inference replica grows from one Pod into multiple interdependent Workers. Going further, Prefill and Decode can be split into independent resource pools that transfer the KV Cache over the network.

Such systems improve scaling efficiency, but they also bring networking, topology, rollout, failure, and state management into the request critical path.

## 1. First Distinguish Three Kinds of Scaling

| Mode | What Is Scaled | Primary Goal |
| --- | --- | --- |
| Data Parallel | Add full model replicas | Increase total request throughput and availability |
| Model Parallel | One model replica spans multiple GPUs/nodes | Fit large models or reduce per-request latency |
| P/D Disaggregation | Independent Prefill and Decode pools | Optimize the two compute types separately and scale them independently |

A production system may use all three at once: TP/PP inside each replica, multiple DP replicas, and then split Prefill and Decode Pools.

## 2. Multi-Machine Model Replicas

```text
一个逻辑模型副本
  Leader / API Pod
    ├── Worker 0：GPU 0-7，节点 A
    ├── Worker 1：GPU 0-7，节点 B
    └── Worker 2：GPU 0-7，节点 C
```

These need to be managed as a whole:

- Created and deleted together;
- Stable identity and discovery;
- Gang/All-or-Nothing scheduling;
- Networking and topology;
- Readiness of all Ranks;
- Whole-replica recovery when one Worker fails;
- Scaling and rollout in units of complete replicas.

A plain Deployment does not provide these semantics.

### 2.1 Using DeepSeek-V4-Pro to Understand "Multi-Machine Replica" vs. "Multiple Replicas" { #deepseek-v4-multi-node-example }

DeepSeek-V4-Pro is well suited to illustrate these two easily confused levels. The official public specification is 1.6T total parameters, 49B activated parameters, 1M Context; the model weights use FP4 and FP8 mixed precision. The official vLLM recipe estimates the mixed-precision checkpoint at about 960GB and gives a concrete multi-node example: one GB200 NVL4 Tray has 4 GPUs, and a single Tray cannot hold this checkpoint, so 2 Trays with 8 GPUs total are used, sharing the model via DP + EP.

References: [DeepSeek-V4 official release](https://api-docs.deepseek.com/news/news260424/), [DeepSeek-V4 open weights](https://huggingface.co/collections/deepseek-ai/deepseek-v4), [vLLM DeepSeek-V4-Pro Recipe](https://github.com/vllm-project/recipes/blob/main/models/deepseek-ai/DeepSeek-V4-Pro.yaml)

These 2 nodes and 8 GPUs are, at the platform layer, first of all **one complete model replica**:

```text
DeepSeek-V4-Pro Replica A
  Leader / API Endpoint
    ├── GB200 NVL4 Tray A1：4 GPU
    └── GB200 NVL4 Tray A2：4 GPU
        └── vLLM DP + Expert Parallel 通信域
```

The scheduler must prepare nodes, GPUs, networking, and model data for the entire group at once; if any required Rank is not Ready, Replica A must not enter the external Endpoint. Higress or AIBrix must also not send user requests directly to an individual Worker Pod; they may only access this group's Leader/API Service.

When an enterprise deploys another set of identical resources for throughput and availability, "multiple complete replicas" appear:

```text
逻辑模型 deepseek-v4-pro
  ├── Replica A：2 Tray / 8 GPU
  └── Replica B：2 Tray / 8 GPU
```

There are now two different scheduling decisions:

1. Kubernetes, Kueue, and StormService/RoleSet, LeaderWorkerSet, or KubeRay decide how each 8-GPU group lands on nodes as a whole;
2. The AIBrix Gateway decides whether a given `model=deepseek-v4-pro` request goes to Replica A or B, and must not mix the internal Workers of A/B into a plain Endpoint pool.

If only Replica A exists, a stable Leader Service is sufficient to carry traffic, and AIBrix's "replica selection" adds limited value; only with multiple groups A/B, P/D pools of both types, significant queue differences caused by long contexts, or a desire for KV/Session awareness does internal inference routing become a necessary capability.

Hardware numbers cannot be copied directly. The same vLLM recipe also gives different parameters for 8×B300, 8×H200, and other platforms; the actual node count depends on GPU memory, weight precision, the KV Cache produced by Context/concurrency, Runtime version, and parallelism strategy. Before going live, you must re-measure against the target hardware rather than deriving the node count directly from "1.6T parameters."

### 2.2 Besides DeepSeek-V4, What Existing Examples Are There { #other-vllm-aibrix-multi-node-examples }

First distinguish three kinds of "support," otherwise a model list can easily be mistaken for production cases that have actually been run:

1. **AIBrix official end-to-end examples**: the repository contains orchestration, label, Service, and routing manifests;
2. **vLLM official multi-machine recipes**: the model and multi-machine parallelism strategy have upstream basis, but the Runtime still needs to be integrated with AIBrix;
3. **Theoretically OpenAI API compatible**: this only shows that AIBrix can discover and forward; it does not prove that multi-machine communication, P/D, or scaling have been verified.

As of August 2026, the three example sets in the AIBrix repository most worth referencing directly are:

| Official example | What it proves | How to use it | Parts that cannot be copied directly |
| --- | --- | --- | --- |
| [DeepSeek-R1 671B](https://github.com/vllm-project/aibrix/tree/v0.7.0/samples/deepseek-r1) | 2 nodes, 16×H20 96GB, RayClusterFleet, vLLM TP16, Head-only Service, routing, autoscaling, and monitoring | The main blueprint for a large model's cross-node complete replica | The example is based on an older vLLM 0.7.3 custom image and a specific cloud RDMA; storage, NIC, image, and version must be redone |
| [Qwen2.5-Coder-7B two-node](https://github.com/vllm-project/aibrix/blob/v0.7.0/samples/distributed/fleet-two-node.yaml) | RayClusterFleet creates 1 Head GPU + 1 Worker GPU, vLLM TP2, AIBrix only sends requests to the Head | Use a small model to validate the KubeRay, Fleet, Service, and Gateway control chain | It executes `apt`/`pip` at startup and uses vLLM 0.7.1; it is a tutorial, not a production image template |
| [Qwen3-8B P/D](https://github.com/vllm-project/aibrix/tree/v0.7.0/samples/disaggregation/vllm) | StormService Replica/Pool two modes, 2 Prefill + 1 Decode, NIXL transport, and `routing-strategy: pd` | Validate Prefill/Decode role orchestration and dynamic routing | This is not a "large model loaded across nodes" example; RDMA annotations, NIXL images, and NCCL parameters carry environment assumptions |

Real large-model candidates are not limited to DeepSeek. The models in the table below are all explicitly declared in the [vLLM official Recipes](https://github.com/vllm-project/recipes) to be compatible with `multi_node_tp`, `multi_node_tp_pp`, distributed Expert Parallel, and `pd_cluster`, so they are suitable for connecting the vLLM Leader/API Endpoint to AIBrix:

| Open-weight model | Size and context | Minimum vLLM version | Typical weight GPU memory in the recipe | Better suited to validate what |
| --- | --- | --- | --- | --- |
| [DeepSeek-R1](https://github.com/vllm-project/recipes/blob/main/models/deepseek-ai/DeepSeek-R1.yaml) | 671B / 37B activated, 163K | 0.12.0 | FP8 about 805GB; NVFP4 about 403GB | AIBrix already has a 671B multi-machine blueprint, suitable as the most complete baseline besides V4 |
| [Qwen3-235B-A22B-Instruct](https://github.com/vllm-project/recipes/blob/main/models/Qwen/Qwen3-235B-A22B-Instruct-2507.yaml) | 235B / 22B activated, 262K | 0.10.0 | FP8 about 240GB; NVFP4 about 141GB | Relatively low resource threshold, suitable for the first real MoE multi-machine, EP, and long-context validation |
| [Qwen3-Coder-480B-A35B](https://github.com/vllm-project/recipes/blob/main/models/Qwen/Qwen3-Coder-480B-A35B-Instruct.yaml) | 480B / 35B activated, 262K | 0.10.0 | FP8 about 576GB; NVFP4 about 288GB | Code and Agent requests, Tool Calling, long context, and multi-replica routing |
| [GLM-4.7](https://github.com/vllm-project/recipes/blob/main/models/zai-org/GLM-4.7.yaml) | 358B / 32B activated, 202K | 0.11.0 | FP8 about 430GB; NVFP4 about 215GB | Chinese, reasoning, and Tool Calling, and can validate MTP speculative decoding |
| [Qwen3.5-397B-A17B](https://github.com/vllm-project/recipes/blob/main/models/Qwen/Qwen3.5-397B-A17B.yaml) | 397B / 17B activated, 262K | 0.17.0 | NVFP4/GPTQ Int4 about 238—239GB | Newer multimodal/reasoning model, but Runtime and connector version requirements are higher |
| [Kimi-K2.5](https://github.com/vllm-project/recipes/blob/main/models/moonshotai/Kimi-K2.5.yaml) | 1T / 32B activated, 262K | 0.19.1 | INT4 about 714GB; NVFP4 about 600GB | Very large MoE, multimodal, P/D, and large-scale Expert Parallel; the most expensive tier |
| [MiniMax-M2.5](https://github.com/vllm-project/recipes/blob/main/models/MiniMaxAI/MiniMax-M2.5.yaml) | 230B / 10B activated, 196K | 0.20.2 | FP8 about 276GB; NVFP4 about 138GB | Validate multi-machine and P/D with a lower weight threshold; on some hardware a single machine can already hold it, so do not go multi-machine just for the sake of it |
| [Mistral Large 3 675B](https://github.com/vllm-project/recipes/blob/main/models/mistralai/Mistral-Large-3-675B-Instruct-2512.yaml) | 675B / 22B activated, 294K | 0.11.0 | FP8 about 810GB; NVFP4 about 405GB | International open-weight model, multilingual and long context, multi-machine TP/PP/EP and P/D |

The GPU memory in the table is only the minimum order of magnitude the recipe gives for the **weight variant**; it does not include the full KV Cache, CUDA Graph, communication buffers, and safety margin required for the target concurrency, nor does it equal a recommended GPU count. In particular, NVFP4 usually requires native Blackwell capability; you cannot simply add up total GPU memory.

### 2.3 The Correct Boundary for Integrating a Model into AIBrix

AIBrix does not have a whitelist that only permits specific models. For an ordinary colocated vLLM service, at minimum you must ensure:

- Pods carry consistent `model.aibrix.ai/name` and `model.aibrix.ai/port`;
- vLLM's `--served-model-name`, request body `model`, Service, and routing configuration are consistent;
- The Service selects only the Leader/API Pod of one complete replica and must not select internal Headless Workers;
- Readiness succeeds only after all required Ranks and the model are servable;
- The AIBrix Gateway routes between multiple **complete replicas**, while intra-group Ranks are managed by RayClusterFleet, StormService/RoleSet, LWS, or the Runtime.

In non-P/D scenarios, the coupling between the AIBrix Gateway and the vLLM engine version is relatively weak; as long as a newer vLLM keeps compatible APIs, metrics, and discovery labels, it can usually be integrated first as an ordinary model Endpoint. P/D, KV Offload, NIXL Connector, and Runtime Sidecar sit on the data path, where version coupling is strong. Recipes such as Qwen3.5, Kimi-K2.5, and MiniMax-M2.5 require vLLM 0.17—0.20, which is clearly newer than the AIBrix v0.7.0 example images; you must rebuild images and validate the KV Connector, NIXL, CUDA/NCCL, and metrics, rather than only replacing the `model` field.

Recommended rollout in increasing risk order:

1. First use the Qwen2.5-Coder-7B two-node example to prove RayClusterFleet and Head-only routing;
2. Use Qwen3-8B to prove the StormService and P/D control chain, but do not yet claim performance benefits from it;
3. For the first real large model, prefer Qwen3-235B-A22B FP8, or DeepSeek-R1 671B, which has more complete reproduction evidence;
4. Then add a second complete replica to validate AIBrix queueing, Prefix/Session awareness, failure removal, and scaling;
5. Only last test 1T models such as Kimi-K2.5 and cross-node P/D, and decide whether to go live based on TTFT, TPOT, Goodput, and failure recovery time.

### 2.4 AIBrix's Two Orchestration Routes

AIBrix can use `RayClusterFleet` to manage multiple complete RayCluster replicas, or `StormService → RoleSet → Pod` to directly express Prefill, Decode, or other roles. `RoleSet` is not a third option on the same level as the previous two, but the next-level resource managed by StormService.

This section only establishes the conceptual boundary: when Ray is already in use, RayClusterFleet is usually preferred; when P/D separation, role-level elasticity, or removing Ray is needed, StormService is usually preferred. A complete comparison of CRD hierarchy, dependencies, Endpoints, scaling, updates, and failure boundaries, as well as alternative approaches on bare Kubernetes, is consolidated in [Orchestration Option Selection in AIBrix Practice](../practices/aibrix-existing-cluster.md#rayclusterfleet-vs-stormservice).

## 3. LeaderWorkerSet

LeaderWorkerSet (LWS) describes a replication unit consisting of one Leader and multiple Workers, suitable for multi-machine inference and other Leader/Worker workloads.

It provides:

- Group-level replicas;
- Stable Leader/Worker indices and discovery;
- Ordered/parallel lifecycle capabilities;
- Group-level rolling updates and scaling;
- Integration with Kueue, Gateway, and the inference control plane.

LWS does not handle model request routing, quota admission, or KV Cache. Typically you also need:

- Kueue for group admission and topology;
- Gateway/InferencePool for request selection;
- The engine to handle TP/PP communication;
- Model cache and RDMA components for the data path.

Reference: [LeaderWorkerSet](https://lws.sigs.k8s.io/)

## 4. Topology Selection

The usual priority order is:

1. Keep TP within the NVLink/NVSwitch domain whenever possible;
2. When PP crosses nodes, ensure stable RDMA/high-speed networking;
3. For MoE EP, pay attention to All-to-All and Expert hotspots;
4. Keep CPU, GPU, and NIC in reasonable NUMA/PCIe proximity;
5. Spread multiple replicas across failure domains, while concentrating within a single replica;
6. Place the model cache on the selected nodes.

"Concentrate within a replica" and "spread between replicas" are two different goals that require a layered topology strategy.

## 5. vLLM Multi-Machine Parallelism

vLLM supports Tensor/Pipeline and other distributed inference. Typical approaches:

- Within a single node, TP equals the number of GPUs used on that machine;
- When the model crosses nodes, add PP;
- Multi-replica throughput is achieved via DP or multiple upper-layer Deployments/LWS;
- The specific Runtime can use Ray or another supported execution backend.

Illustration:

```bash
vllm serve /models/example \
  --tensor-parallel-size 8 \
  --pipeline-parallel-size 2
```

This represents a conceptual configuration where one logical replica uses 16 GPUs; in practice, multi-node startup, address discovery, container shared memory, and network parameters are also required.

Currently, vLLM multi-node deployments can use either Ray or the native MultiProcessing modes `--nnodes`, `--node-rank`, and `--headless`. Ray is a distributed execution backend, not the only parallel algorithm for multi-machine inference itself; TP, PP, DP, and EP determine how model computation is split.

Reference: [vLLM Parallelism and Scaling](https://docs.vllm.ai/en/latest/serving/parallelism_scaling/)

### 5.1 What is the relationship between vLLM Ray multi-node and P/D disaggregation { #vllm-ray-vs-pd }

They are two orthogonal dimensions:

- **vLLM Ray multi-node** answers: how a single vLLM Engine splits the computation of **the same model replica** across multiple GPUs and multiple nodes;
- **P/D disaggregation** answers: whether the Prefill and Decode of a single request are handled by **two independent vLLM Engines**, and how the KV Cache is transferred from the former to the latter.

The most important insight is: **Ray Workers are not Decode Workers.** In ordinary Ray multi-node mode, the Head/Worker Ranks jointly participate in the Prefill and Decode of the same Engine; in P/D mode, Prefill and Decode are two Engines with independent Schedulers, Batches, KV Caches, and Endpoints.

#### 5.1.1 Ray only, without P/D

```text
Client
  → vLLM API / Ray Head
      → 同一个 vLLM Engine
          ├─ Ray Rank 0：GPU/权重分片
          ├─ Ray Rank 1：GPU/权重分片
          └─ Ray Rank 2：GPU/权重分片
             所有 Rank 共同执行 Prefill 和 Decode
```

Here the model is placed across GPUs via TP/PP/EP. A request belongs to the same Engine from start to finish; Ranks continuously perform Collective, Activation, or Pipeline communication during layer, token, or expert computation. Ray handles process placement and execution coordination, while vLLM still handles the inference Scheduler.

#### 5.1.2 P/D only, without Ray

```text
Client
  → P/D Router
      → Prefill vLLM Instance：加载模型，计算 Prompt 和初始 KV
          → NIXL/LMCache/Mooncake 等 Connector 传输 KV
      → Decode vLLM Instance：也加载模型，接收 KV 后逐 Token 生成
```

Each side can use just a single GPU, or single-node multi-GPU MultiProcessing. P/D does not require Ray, but it does require a P/D-aware Router, KV Connector, Peer discovery, and compatible models, KV layouts, and Engine versions. Neither Prefill nor Decode is "only half a model installed": both sides must have the full logical model capability required to execute their respective stages, so this typically results in two copies of weight capacity, though each copy can still be sharded internally.

#### 5.1.3 Ray and P/D can be combined

```text
Client
  → P/D Router
      → Prefill Engine（RayCluster P）
          ├─ P-Head
          └─ P-Worker × N
              → 跨 Engine 传输 KV
      → Decode Engine（RayCluster D）
          ├─ D-Head
          └─ D-Worker × M
```

In this case, Ray handles model parallelism **within** P and D respectively, while the P/D Router and Connector handle request switching and KV handoff **between** the two Engines. Prefill and Decode can use different TP/PP shapes, but this configuration is only possible when the KV Connector's TP Mapping and compatibility matrix explicitly support it; arbitrary combinations are not allowed.

The official AIBrix v0.7.0 examples separately demonstrate RayClusterFleet multi-node and StormService P/D; they are not yet a ready-to-apply "RayClusterFleet nesting StormService" manifest. Enterprises that need the combined architecture above should treat it as an advanced integration: manage the P/D distributed Engines separately, expose only their respective Leader/API Endpoints to the Router, and independently verify discovery, pairing, KV transfer, and failure recovery.

#### 5.1.4 Comparison of similarities and differences

| Dimension | vLLM Ray multi-node | P/D disaggregation |
| --- | --- | --- |
| What is split | Ranks, weights, and computation within a single model replica | The two execution stages of a single request |
| Number of Engines | Typically 1 Engine with multiple Ray Ranks | At least 2 independent Engines: Prefill and Decode |
| Model weights | Sharded across Ranks via TP/PP/EP | Both P and D sides must load the model; each side can be further sharded internally |
| Request Scheduler | One vLLM Scheduler manages the complete request | P and D each have their own Scheduler, plus an outer P/D Router is required |
| Primary data communication | Frequent Activation, Collective, or Expert data transfer between Ranks | KV Cache transferred across Engines at stage switch; TP/PP communication may still occur within an Engine |
| Primary purpose | Model does not fit on a single machine; use more GPUs to accelerate one replica | Optimize TTFT and ITL separately; isolate long-Prompt interference on Decode |
| Scaling method | Add complete RayCluster replicas; changing the number of Ranks usually requires rebuilding and reloading the model | Prefill and Decode Pools can scale independently according to their respective loads |
| Failure impact | Failure of any required Rank can make the entire model replica unavailable | Prefill/Decode or KV handoff failure affects request stages; orphaned KV must also be cleaned up |

Four common combinations for quick architecture assessment:

| Combination | Is it reasonable | Typical scenario |
| --- | --- | --- |
| Single-node vLLM, colocated P/D | Yes, default starting point | Model and SLO can be satisfied on a single machine |
| Ray multi-node, colocated P/D | Yes | Model does not fit on a single machine, but stage pooling is not yet needed |
| Single-machine/single-node P Pool + D Pool | Yes | A single model instance can fit, but TTFT/ITL isolation and independent scaling are desired |
| Multi-node Ray P Pool + multi-node Ray D Pool | Possible, but most complex | Very large models that genuinely need P/D; network, Connector, and operations capabilities are mature |

Do not introduce P/D simply because Ray is already in use. The current vLLM official documentation explicitly describes the primary value of P/D as separately tuning TTFT/ITL and controlling tail ITL, and reminds users that it **does not automatically improve raw throughput**. The platform layer may achieve higher SLO Goodput or utilization through independent scaling ratios, but the benefits must cover the costs of KV transfer, duplicate weights, an additional Router, and the expanded failure surface.

References: [vLLM Disaggregated Prefilling](https://docs.vllm.ai/en/stable/features/disagg_prefill/), [NixlConnector Usage Guide](https://docs.vllm.ai/en/stable/features/nixl_connector_usage/), [NixlConnector Compatibility Matrix](https://docs.vllm.ai/en/stable/features/nixl_connector_compatibility/)

## 6. Why Prefill and Decode are different

| Stage | Compute characteristics | Primary resource pressure | Key SLO |
| --- | --- | --- | --- |
| Prefill | Processes input tokens in one pass; highly parallelizable | FLOPS, input length | TTFT |
| Decode | Generates token by token; repeatedly reads weights/KV | HBM bandwidth, synchronization, concurrency | TPOT/ITL |

In colocated mode, the same set of GPUs shares resources between the two types of tasks. When load is unbalanced, the following issues can occur:

- Long Prompts block interactive Decode;
- Prefill peaks and Decode capacity cannot be scaled separately;
- Different hardware cannot each leverage its own strengths;
- Queues and Batches interfere with each other.

## 7. P/D disaggregation architecture

```text
Client
  → Router / Frontend
      → Prefill Pool
          → 生成 KV Cache
          → 通过 NIXL/UCX/RDMA/其他 Connector 传输
      → Decode Pool
          → 继续生成并流式返回
```

Sources of benefit:

- Prefill and Decode scale independently;
- Different GPU models or parallel configurations can be used;
- Batch, concurrency, and SLO can be tuned separately;
- Better isolation of long-Prompt impact on Decode;
- Higher utilization and Goodput at sufficient scale.

New costs:

- KV transfer latency and bandwidth;
- Peer discovery and connection management;
- Dual-pool capacity balancing;
- Cancellation, failure, and orphan states;
- Release, rollback, and version compatibility;
- More components and observability boundaries.

## 8. When P/D disaggregation should NOT be used

- A single machine or a small number of GPUs already satisfies the SLO;
- Requests are short and KV transfer cost approaches or exceeds the benefit;
- The network does not have stable high-bandwidth, low-latency capability;
- The Prefill/Decode traffic ratio is stable and colocated efficiency is already good;
- The team does not yet have complete benchmarks, traces, and failure handling;
- The model/Engine/Connector combination does not have production support;
- Cold-start and release complexity matters more than GPU savings.

P/D disaggregation is a scale optimization, not a prerequisite for deploying LLMs.

## 9. KV transfer path

The following must be clarified:

- KV format, Block size, Dtype, and layout;
- Whether Prefill/Decode Engines and versions are exactly identical;
- Who initiates the transfer, Push or Pull;
- How Peers are discovered and authenticated;
- Whether GPU Direct, RDMA, TCP, or shared storage is used;
- When the KV is released on the sending side;
- How cleanup is handled after Decode failure;
- How request cancellation propagates;
- Whether transfer timeouts and retries are safe;
- Whether the KV contains sensitive Prompt information.

A single model or Engine upgrade can change the KV layout; old and new Workers must not be arbitrarily interconnected.

## 10. llm-d

llm-d is a Kubernetes-oriented distributed LLM inference architecture built around:

- InferencePool and Endpoint Picker;
- Model serving with vLLM/SGLang and others;
- Prefix/KV-aware Routing;
- KV Cache Indexing and Offload;
- P/D disaggregation;
- Flow Control;
- Kubernetes Deployment, Prometheus, and Gateway integration.

It is suitable for teams that want to build a composable inference data plane using Kubernetes-native APIs. For production selection, pin the llm-d, Gateway Extension, Engine, Connector, and CRD versions.

Reference: [llm-d Architecture](https://llm-d.ai/docs/architecture)

## 11. NVIDIA Dynamo

Dynamo provides Frontend, Router, Planner, Worker, and disaggregated inference capabilities. It can compose vLLM, SGLang, TensorRT-LLM, and other Backends, and transfers KV via mechanisms such as NIXL.

Suitable for:

- Large-scale distributed inference on NVIDIA platforms;
- P/D, KV Routing, and Expert Parallel that have been validated through recipes;
- Expressing component graphs via resources such as `DynamoGraphDeployment`;
- Topology and capacity planning before deployment.

Dependencies such as etcd/NATS for discovery or messaging, Dynamo CRD/Operator, Runtime images, and Backend compatibility must be managed.

Reference: [NVIDIA Dynamo Disaggregated Serving](https://docs.nvidia.com/dynamo/latest/user-guides/disaggregated-serving)

## 12. What alternatives exist beyond AIBrix

First, distinguish three layers to avoid treating inference Engines, Kubernetes orchestration components, and complete inference control planes as comparable products:

```text
平台控制面：AIBrix / llm-d / KServe / Ray Serve / Dynamo
集群编排层：Kubernetes / RBG / LeaderWorkerSet / KubeRay
推理执行层：vLLM / SGLang / TensorRT-LLM
```

A platform often uses components from all three layers simultaneously. For example, KServe handles service lifecycle, LeaderWorkerSet expresses cross-node replicas, and vLLM performs model computation; they are not three interchangeable products.

| Project | Primary positioning | Multi-node multi-GPU and disaggregated inference capabilities | Better suited for |
| --- | --- | --- | --- |
| AIBrix | Kubernetes LLM inference control plane | Gateway, model-aware routing, Autoscaling, LoRA, KV Cache, and P/D capabilities | Building a general-purpose inference platform that includes traffic, model, and elasticity management |
| RBG (RoleBasedGroup) | Multi-role, stateful inference workload orchestration API | Router/Prefill/Decode role dependencies, stable discovery, role-level scaling, Leader/Worker and coordinated updates; does not implement request routing or KV data paths | Using an independent orchestration layer on top of SGLang, Dynamo, Mooncake, or a self-developed Runtime; the most direct comparison with AIBrix is StormService/RoleSet |
| llm-d | Kubernetes-native distributed inference stack | InferencePool/EPP, Prefix/KV-aware Routing, KV indexing and offload, P/D disaggregation | Focused on optimizing large-scale request scheduling, KV hit rate, and disaggregated inference; can serve as a primary benchmark against AIBrix |
| KServe LLMInferenceService | Model serving CRD and lifecycle control plane | Expresses cross-node replicas via LeaderWorkerSet, supports Tensor/Data/Expert Parallelism, and composes Gateway and Autoscaler | Already using KServe and wanting unified model serving API, release, and elasticity governance |
| NVIDIA Dynamo | NVIDIA high-performance distributed inference framework | Frontend, Router, Prefill/Decode Pool, KV-aware Routing, NIXL/RDMA data paths | NVIDIA GPUs and high-speed networking are complete; prioritizes P/D, KV transfer, and peak performance |
| Ray Serve LLM + KubeRay | Programmable distributed application and service platform | Cross-node TP/PP/EP, P/D disaggregation, model-aware routing, and replica elasticity | Already using Ray Data/Train/Jobs and wanting data, training, evaluation, and inference on the same runtime |
| vLLM Production Stack | vLLM official Kubernetes production deployment stack | Multiple Serving Engines, Router, Prefix/KV-aware Routing, P/D, KEDA, LoRA, and monitoring | Already committed to vLLM and wanting to go live quickly with lower platform cost |
| SGLang with its Router/Model Gateway | High-performance inference Engine and routing capabilities | Multi-node parallelism, Radix Cache, P/D disaggregation, and multiple routing strategies | Values SGLang Engine capabilities and is willing to assemble Kubernetes lifecycle and governance components itself |
| LeaderWorkerSet | Kubernetes API where multiple Pods form one logical replica | Unified creation, scaling, and update of Leader/Worker Pod groups | Providing multi-node replica orchestration for KServe, llm-d, or a self-developed control plane; it is not a complete inference platform |

### 12.1 Selection conclusions

- Looking for the open-source option closest to AIBrix's positioning: prioritize evaluating **llm-d**;
- Already have a KServe platform: use **KServe LLMInferenceService + LeaderWorkerSet**;
- NVIDIA GPUs, RDMA, and topology conditions are mature: test **Dynamo + TensorRT-LLM/vLLM**;
- Already using Ray extensively for data processing, training, and inference: choose **KubeRay + Ray Serve LLM**;
- Want to productionize vLLM first without rushing to build a unified control plane: start with **vLLM Production Stack**;
- Need a multi-role lifecycle API independent of the Gateway: evaluate **RBG**; if the full AIBrix stack is already adopted, compare StormService first to avoid two controllers owning the same set of Pods;
- Need a self-developed enterprise inference platform: compose **Gateway API + llm-d Router/EPP + KServe/LWS + vLLM/SGLang**, but must ensure each resource has exactly one lifecycle and scaling controller.

References: [RBG](https://github.com/sgl-project/rbg), [llm-d Architecture](https://llm-d.ai/docs/0.7/architecture), [KServe LLMInferenceService](https://kserve.github.io/website/docs/model-serving/generative-inference/llmisvc/llmisvc-configuration), [Ray Serve LLM](https://docs.ray.io/en/latest/serve/llm/index.html), [vLLM Production Stack](https://github.com/vllm-project/production-stack), [SGLang](https://github.com/sgl-project/sglang). For the detailed boundary between RBG and AIBrix/Higress and the sr1 measurements, see [RBG Multi-Role Inference Orchestration](../practices/rbg-existing-cluster.md); for the SGLang Router CPU control chain measurements, see [SGLang Model Gateway CPU in Practice](../practices/sglang-model-gateway-cpu-lab.md).

## 13. Dual-Pool Capacity Planning

Measure separately:

```text
Prefill 需求 ≈ 输入 Token 到达率 / 单 Prefill Worker 的有效 Token/s
Decode 需求  ≈ 输出 Token 到达率 / 单 Decode Worker 的有效 Token/s
```

Also include:

- Long and short prompt distribution;
- KV transfer concurrency and bandwidth;
- Single Worker failure redundancy;
- Peak and target utilization;
- Model/Cache warm-up;
- Rejection and queueing budget.

The Autoscalers of the two Pools cannot only look at their own local queues. If Prefill scales up too quickly, it will overwhelm Decode; if Decode is over-provisioned, it will idle waiting for KV.

## 14. Release and Versioning

A disaggregated release includes at least:

- Model artifact;
- Prefill runtime and parameters;
- Decode runtime and parameters;
- KV Connector/NIXL/UCX versions;
- Router/EPP;
- Gateway and CRD;
- GPU driver, CUDA/ROCm;
- Network and RDMA configuration.

The safest Canary approach is to stand up an entirely new Pool, rather than letting new Prefill workers randomly connect to old Decode workers.

Release process:

1. Create a new-version Prefill/Decode Pool;
2. Pass compatibility and KV transfer tests;
3. Warm up models and connections;
4. Shadow side-effect-free traffic;
5. Canary by tenant/request in a stable manner;
6. Compare quality, TTFT, TPOT, Goodput, and cost;
7. Stop new requests to the old Pool;
8. Reclaim after draining.

## 15. Failure Semantics

| Failure | Handling Objective |
| --- | --- |
| Prefill Worker failure | Requests can be safely retried or fail fast, without producing orphaned KV |
| Decode Worker failure | In-flight streaming requests can be recognized as terminated, without repeating side effects |
| KV transfer timeout | Clean up state on both sides, record the link and Request ID |
| Router/EPP failure | Data plane falls back or a high-availability instance takes over |
| Cache Index invalidation | Fall back to non-Cache-aware routing |
| Node drain | Remove Endpoints first, then stop new pairing |
| New/old version incompatibility | Release gate prevents cross-version connections |
| Network partition | Timeout, isolation, and recovery do not duplicate requests |

## 16. Observability

It must be possible to see from a single request:

```text
Gateway
  → Router 选择原因
  → Prefill 排队/执行
  → KV 大小、传输时间和路径
  → Decode 排队/执行
  → Token 流式返回
```

Metrics:

- Prefill/Decode respective queues, batch, and tokens/s;
- KV transfer bytes, time, failures, and retries;
- Peer count, connection establishment and teardown;
- TTFT breakdown into routing, queueing, Prefill, and transfer;
- TPOT and Decode batch;
- Orphaned KV, cancellations, and cleanup;
- Pool scaling, Ready status, and version;
- RDMA/NIC/GPU/CPU metrics.

## 17. Security

- KV Cache may contain reconstructable user context; treat it as sensitive data;
- Use network identity, encryption, or a controlled data plane between Prefill and Decode;
- Access boundaries for KV Index and Cache across different tenants are clearly defined;
- Workers are not exposed to the public network;
- The Router must not send requests to unauthorized models/Adapters;
- Debug logs do not record raw KV, prompts, or credentials;
- Multi-NIC/RDMA ports are protected through network isolation and node policies.

## 18. Go-Live Checklist

- [ ] It has been demonstrated that single-machine/colocated mode cannot meet the goals more simply.
- [ ] A multi-machine replica is created, scheduled, and released as a whole by LWS/controller.
- [ ] Replicas are concentrated internally and spread across failure domains between replicas.
- [ ] KV format, Connector, engine, and model versions are fully locked down.
- [ ] The P/D two Pools use a joint capacity model and protection mechanisms.
- [ ] Request cancellation, Worker failure, and KV timeout have been exercised.
- [ ] Releases do not let new and old incompatible Workers pair randomly.
- [ ] Traces can break down routing, Prefill, KV transfer, and Decode.
- [ ] Safe degradation is possible when Cache Index/Router fails.
- [ ] KV Cache privacy, network, and tenant isolation have been reviewed.

## Further Reading

- [LeaderWorkerSet](https://lws.sigs.k8s.io/)
- [llm-d](https://llm-d.ai/)
- [llm-d Disaggregated Serving](https://llm-d.ai/docs/architecture/advanced/disaggregation)
- [NVIDIA Dynamo Disaggregated Serving](https://docs.nvidia.com/dynamo/latest/user-guides/disaggregated-serving)
- [TensorRT-LLM Disaggregated Serving](https://nvidia.github.io/TensorRT-LLM/features/disagg-serving.html)
- [KServe LLMInferenceService](https://kserve.github.io/website/docs/concepts/architecture/control-plane-llmisvc)

For multi-region scenarios, prefer deploying a complete inference stack in each cluster, with a global Gateway selecting the cluster and the in-cluster Router/EPP selecting the model replica; TP/PP, P/D, and KV transfer should in principle stay within a low-latency network domain. See: [Kubernetes Cross-Cluster and Large-Scale GPU](../cluster/multi-cluster-ai.md).
