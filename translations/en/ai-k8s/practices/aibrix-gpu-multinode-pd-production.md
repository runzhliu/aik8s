---
title: "AIBrix Real GPU Field Test: From Two-Machine Inference to Eight-Node Fragmented GPUs"
description: "On a production Kubernetes cluster using NVIDIA L20, AIBrix v0.7.0, RayClusterFleet, StormService, and vLLM, verify two-machine model parallelism, NIXL P/D separation, eight-node Qwen3-235B FP8, and DeepSeek 70B four-node single-GPU, two-node dual-GPU, and single-node four-GPU topologies"
status: lab
last_reviewed: 2026-08-08
---

# AIBrix Real GPU Field Test: From Two-Machine Inference to Eight-Node Fragmented GPUs

The previous round of experiments used CPU mocks to validate the AIBrix v0.7.0 control plane, model discovery, routing, StormService, and autoscaling. This round continues on a production Kubernetes cluster using real NVIDIA L20 GPUs and local model weights, answering four more critical questions:

1. Can `RayClusterFleet` make a single vLLM Engine execute the same model jointly across two machines;
2. Can `StormService` run Prefill and Decode on different GPU nodes respectively, handing off KV Cache via NIXL;
3. When each node has only one idle GPU left, can eight fragmented L20s be assembled into a 235B MoE inference instance;
4. With the same four L20s in four-node single-GPU, two-node dual-GPU, and single-node four-GPU configurations, how much does single-stream inference performance differ.

Final results: two-machine, two-GPU Qwen2.5-32B BF16 Ray Pipeline Parallel inference succeeded; two-machine, two-GPU Qwen2.5-Coder-32B GPTQ Int4 P/D service successfully completed the full AIBrix Gateway → Prefill → NIXL KV Transfer → Decode → response chain; Qwen3-235B-A22B FP8 ran successfully on a fragmented topology of eight nodes, one L20 per node; DeepSeek-R1-Distill-Llama-70B BF16 completed field tests in sequence across four-node single-GPU TP=1/PP=4, two-node dual-GPU TP=2/PP=2, and single-node four-GPU TP=4/PP=1, with single-stream Decode at approximately 5.13, 9.92, and 18.33 token/s respectively.

This round focuses on **functional, topology, and data-path validation**, and records a set of hot-request TTFT, TPOT, and throughput samples for the 235B instance. Samples come from a non-exclusive production experiment window and are not formal capacity conclusions; production selection still requires concurrency, long-context, failure, and Goodput benchmarking using real traffic distributions.

!!! warning "Public documentation has been sanitized"
    This article will not record internal cluster names, node addresses, Ceph monitors, real model volume paths, Registry, Ingress domains, Pod IPs, or Secrets. All environment-related values are uniformly written as `<...>` placeholders and cannot be copied and executed directly.

## 1. Test Environment and Versions

| Item | Measured Value |
| --- | --- |
| AIBrix | v0.7.0 |
| GPU | NVIDIA L20, approximately 46 GiB GPU memory per card |
| Two-machine Ray image | vLLM 0.8.3 development build, Ray 2.43.0 |
| P/D and eight-node Ray image | vLLM 0.10.1 development build, Ray 2.48.0 |
| KV Connector | NIXL Connector |
| P/D transport backend | NIXL + UCX |
| Model storage | CephFS, read-only mount |
| Namespace | Dedicated experiment Namespace for easy overall cleanup |
| Request entry point | AIBrix Envoy Gateway, OpenAI-Compatible API |

Image versions come from container runtime measurements, not just reading YAML labels. Some enterprise image labels, AIBrix example parameters, and actual Python package versions are not fully consistent; when troubleshooting compatibility, confirm inside the container:

```bash
python3 -c 'import vllm, ray; print(vllm.__version__, ray.__version__)'
```

## 2. Model and Validation Matrix

| Model | Precision | Orchestration | GPU Topology | Result |
| --- | --- | --- | --- | --- |
| Qwen2.5-3B-Instruct | BF16 | RayClusterFleet | Single-node single-GPU | OpenAI API succeeded, used as Ray baseline |
| Qwen2.5-3B-Instruct | BF16 | StormService P/D | Prefill 1 GPU + Decode 1 GPU | P/D control flow succeeded, used as NIXL baseline |
| Qwen2.5-32B-Instruct | BF16 | RayClusterFleet | Two nodes, 1 GPU per node | PP=2, multi-machine inference succeeded |
| Qwen2.5-Coder-32B-Instruct | GPTQ Int4 | StormService P/D | Two nodes, 1 GPU per node | NIXL KV transfer and generation succeeded |
| Qwen3-235B-A22B-Instruct | FP8 | RayClusterFleet | Eight nodes, 1 GPU per node | PP=8, loading and OpenAI API generation succeeded |
| DeepSeek-R1-Distill-Llama-70B | BF16 | RayClusterFleet | Four nodes, 1 GPU per node | PP=4, loading and OpenAI API generation succeeded |
| DeepSeek-R1-Distill-Llama-70B | BF16 | RayClusterFleet | Two nodes, 2 GPUs per node | TP=2, PP=2; Decode improved approximately 93% in same-model same-parameter A/B comparison |
| DeepSeek-R1-Distill-Llama-70B | BF16 | RayClusterFleet | Single node, 4 GPUs | TP=4, PP=1; hot-state Decode approximately 18.33 token/s |

The capabilities validated by the two 32B experiments are not the same:

- The Ray experiment splits the **model layers of the same Engine** across two machines, with two Ray Ranks jointly completing Prefill and Decode;
- The P/D experiment runs **two complete Engines**, with Prefill and Decode each loading one copy of the quantized weights, then transfers the KV Cache from the former to the latter.

Therefore, Ray Workers must not be understood as Decode Workers, and the fact that P/D uses two GPUs does not mean the model weights are stored in only one copy.

## 3. Model Volume Must Remain Read-Only

The model directory is shared by multiple production services. This round did not grant write permission to the model directory, and declared read-only at both the CephFS Volume and container VolumeMount layers:

```yaml
volumeMounts:
  - name: model-store
    mountPath: /models
    readOnly: true

volumes:
  - name: model-store
    cephfs:
      monitors:
        - <CEPH_MONITOR_1>:<PORT>
        - <CEPH_MONITOR_2>:<PORT>
        - <CEPH_MONITOR_3>:<PORT>
      path: <READ_ONLY_MODEL_ROOT>
      readOnly: true
      secretRef:
        name: <CEPH_SECRET>
      user: <CEPH_USER>
```

Setting CephFS to read-only alone is not sufficient. Hugging Face, Transformers, vLLM, and Torch Compile may write caches near the model directory by default, so explicitly redirect them to a temporary disk:

```yaml
env:
  - name: HF_HOME
    value: /tmp/huggingface
  - name: TRANSFORMERS_CACHE
    value: /tmp/huggingface/transformers
  - name: XDG_CACHE_HOME
    value: /tmp/.cache
```

During acceptance, verify that both the Pod Spec and the actual Mount are read-only, but do not use commands such as `touch` to actively write to the shared model directory for destructive testing.

## 4. RayClusterFleet Two-Machine Model Parallelism

### 4.1 Topology

The BF16 Safetensors of Qwen2.5-32B-Instruct are approximately 61 GiB. A single L20 cannot stably accommodate weights, runtime, and KV Cache, so two Pods are used:

```text
AIBrix Gateway
  → Ray Head / vLLM API / GPU 0
       │
       └── Ray Worker / GPU 1

vLLM: TP=1, PP=2, distributed-executor-backend=ray
```

Both Head and Worker request one GPU and use mandatory Pod Anti-Affinity to ensure they do not land on the same node:

```yaml
affinity:
  podAntiAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
      - labelSelector:
          matchExpressions:
            - key: model.aibrix.ai/name
              operator: In
              values: [qwen2-5-32b-ray-2n]
        topologyKey: kubernetes.io/hostname
```

The core vLLM parameters are as follows:

```bash
vllm serve /models/Qwen2.5-32B-Instruct \
  --served-model-name qwen2-5-32b-ray-2n \
  --tensor-parallel-size 1 \
  --pipeline-parallel-size 2 \
  --distributed-executor-backend ray \
  --dtype bfloat16 \
  --gpu-memory-utilization 0.90 \
  --max-model-len 8192 \
  --max-num-seqs 8
```

PP=2 was chosen here rather than cross-node TP=2, primarily to first validate cross-node execution and AIBrix orchestration. PP passes activations between pipeline stages; TP produces more frequent Collectives at every layer and is more sensitive to network bandwidth and latency.

### 4.2 Validation Evidence

Ray Runtime returns two Alive Nodes, each publishing one L20, for a cluster total of 2 GPUs. vLLM completes loading of all weight shards, the service runs stably with no container restarts.

Both direct access to vLLM and requests through the AIBrix Gateway return success:

```json
{
  "model": "qwen2-5-32b-ray-2n",
  "choices": [
    {"message": {"role": "assistant", "content": "OK"}}
  ]
}
```

This proves:

- Ray Head and Worker have formed a single resource pool, not two independent model replicas;
- vLLM actually acquired two GPUs and completed PP=2 initialization;
- The Service only selects the Ray Head API Pod; Workers do not become AIBrix request Endpoints;
- AIBrix model discovery and Gateway routing can reach a multi-machine Engine.

## 5. StormService Two-Machine P/D Separation

### 5.1 Why Use a Quantized 32B

Both P/D ends need to load model weights. To let each Role use a single L20 while leaving enough room for KV Cache, this round chose the approximately 18 GiB Qwen2.5-Coder-32B GPTQ Int4 weights.

```text
AIBrix Gateway / P/D Router
  ├── Prefill Role / GPU A / 完整量化权重
  │       └── 计算 Prompt KV
  │
  └── Decode Role / GPU B / 完整量化权重
          └── 通过 NIXL 获取 KV 后继续生成
```

In StormService, Prefill and Decode each have one replica, with mandatory Anti-Affinity ensuring cross-node placement. Both Roles enable:

```text
kv_connector = NixlConnector
kv_role      = kv_both
UCX_TLS      = tcp,cuda_copy,cuda_ipc
```

`kv_both` does not mean the two Roles have no division of labor. The AIBrix Gateway injects different `kv_transfer_params` values for each specific request, and vLLM then assumes the Producer or Consumer role per request.

### 5.2 Validation Evidence

Both sides successfully completed the following initialization:

- GPTQ weights automatically converted to GPTQ Marlin Kernel;
- Approximately 18 GiB of weights loaded per side;
- NIXL Connector and UCX Agent initialized successfully;
- KV Cache registration completed;
- Approximately 21 GiB of KV Cache space retained under the 16K context configuration;
- Both Prefill and Decode Pods Ready, with no restarts.

After sending the same request through the AIBrix Gateway, the sanitized logs showed two sets of complementary evidence:

```text
Prefill:
  max_tokens=1
  do_remote_decode=true
  do_remote_prefill=false

Decode:
  max_tokens=<REQUEST_MAX_TOKENS>
  do_remote_prefill=true
  do_remote_decode=false
  remote_engine_id=<REDACTED>
  remote_block_ids=<REDACTED>
```

The final response content was:

```text
PD-32B-OK
```

This is stronger than "both Pods are Ready": it proves that the same request first computes KV on the Prefill side, and the Decode side then references the remote Engine and Block information to continue generation. If one only sees that each of the two Pods can answer requests independently, one cannot claim the P/D data path has been validated.

## 6. Acceptance Through the AIBrix Gateway

During testing, the Envoy Service can be temporarily forwarded to localhost to avoid recording internal entry points in the documentation:

```bash
kubectl -n <ENVOY_NAMESPACE> port-forward \
  svc/<AIBRIX_ENVOY_SERVICE> 28999:80
```

Ray multi-machine request:

```bash
curl http://127.0.0.1:28999/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -H 'model: qwen2-5-32b-ray-2n' \
  --data '{
    "model": "qwen2-5-32b-ray-2n",
    "messages": [{"role": "user", "content": "只回答 OK"}],
    "temperature": 0,
    "max_tokens": 16
  }'
```

P/D request:

```bash
curl http://127.0.0.1:28999/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -H 'model: qwen2-5-coder-32b-pd' \
  --data '{
    "model": "qwen2-5-coder-32b-pd",
    "messages": [{"role": "user", "content": "只回答 PD-32B-OK"}],
    "temperature": 0,
    "max_tokens": 32
  }'
```

In addition to HTTP 200 and answer content, also check:

1. The `Accepted=True` and `ResolvedRefs=True` of the AIBrix Route;
2. Service Endpoints contain only the Pods that should serve external traffic;
3. GPU Resource of each Node in the Ray Cluster;
4. Whether both Prefill/Decode sides record the same Request ID;
5. Whether `kv_transfer_params` shows complementary Producer/Consumer semantics;
6. Whether Pod Restart Count remains 0 before and after inference.

## 7. Console and Test Tools

For quick invocation and visualization, the following were deployed in the same experiment Namespace this round:

- AIBrix Console: view the AIBrix management interface;
- Open WebUI: interactively switch models and test chat;
- Hoppscotch: construct OpenAI-Compatible HTTP requests;
- k6 Web Dashboard: execute simple load and observe request results.

These tools are only clients and experiment entry points; they cannot replace Prometheus/Grafana, distributed tracing, GPU metrics, request logs, and a formal load-testing platform. The AIBrix Console should also not be understood as a general-purpose Kubernetes Dashboard that "automatically imports all historical Deployments in the cluster"; whether a model is visible still depends on AIBrix labels, Endpoints, the API data model, and the Console Backend implementation.

All test tools are concentrated in the same Namespace, and cleanup does not scan across Namespaces or delete resources by fuzzy name matching.

## 8. Running Qwen3-235B FP8 on Eight Fragmented Nodes

### 8.1 Why Choose PP=8

The most realistic constraint this time is not that the cluster lacks eight GPUs, but that **each node has only one L20 left**. The Qwen3-235B-A22B-Instruct FP8 weights are approximately 220 GiB, with an average static weight of approximately 27.5 GiB across eight GPUs; after accounting for unquantized modules, runtime, and KV Cache, capacity still falls within the approximately 46 GiB range of a single card.

The available parallelism options are not equivalent:

| Approach | Cross-node communication characteristics | Judgment for fragmented L20 + 10Gb network |
| --- | --- | --- |
| TP=8 | Collectives at nearly every layer | Sensitive to bandwidth and tail latency; not used in the first round |
| EP=8 | MoE Tokens perform All-to-All among Experts | Usable for 235B MoE, but very expensive on a 10Gb network |
| PP=8 | Adjacent pipeline stages pass activations | Single requests have pipeline latency, but best suited to first validating "whether it can run" |

Therefore `TP=1、PP=8` was used this round. This is not a topology pursuing maximum performance, but rather converting single-GPU fragments across eight machines into a usable large-model instance.

```text
AIBrix RayClusterFleet
  └── KubeRay 创建 RayCluster
       ├── Head / PP Rank 0 / vLLM API / 1×L20
       ├── Worker / PP Rank 1 / 1×L20
       ├── Worker / PP Rank 2 / 1×L20
       ├── ...
       └── Worker / PP Rank 7 / 1×L20

94 个 Transformer Layer：11, 12, 12, 12, 12, 12, 12, 11
```

The responsibilities of the four layers of components must be clearly distinguished:

- **AIBrix RayClusterFleet**: declares replicas, rolling policies, labels, and model entry points; does not execute model parallelism;
- **KubeRay**: creates Head, Workers, Services, and makes eight Ray Nodes form a cluster;
- **Ray**: provides the cross-node resource pool and Placement Group, atomically reserving eight GPUs;
- **vLLM**: recognizes the model architecture, divides PP Ranks, loads weights, manages KV Cache, and exposes the OpenAI-Compatible API.

### 8.2 Validate the Image First; Do Not Trust Only the Tag

The verified image label reads vLLM 0.10.0, but the actual in-container version is a vLLM 0.10.1 development build with Ray 2.48.0. Before deployment, check directly in an existing Pod:

```bash
/usr/bin/python3 -c '
import ray, vllm
from vllm.model_executor.models.registry import ModelRegistry

arch = "Qwen3MoeForCausalLM"
print("vllm:", vllm.__version__)
print("ray:", ray.__version__)
print("registered:", arch in ModelRegistry.get_supported_archs())
print("pp_supported:", ModelRegistry.is_pp_supported_model([arch]))
'
```

This output confirmed that Qwen3 MoE is registered, Pipeline Parallel is supported, and the image already contains Ray. The same image does not register `Qwen3_5MoeForConditionalGeneration`, so it cannot be used directly for Qwen3.5-397B just because the name differs only by `.5`; the latter requires a vLLM update and re-confirmation that Ray is still present in the image.

### 8.3 Scheduling: Each Pod Takes Only One Card, with Mandatory Spreading

RayClusterFleet uses seven Workers, plus the Head for exactly eight Ray Nodes. Node labels differ across enterprise environments; generic placeholder values are used below:

```yaml
spec:
  template:
    spec:
      rayVersion: 2.48.0
      headGroupSpec:
        template:
          spec:
            affinity: &fragmented_l20_affinity
              nodeAffinity:
                requiredDuringSchedulingIgnoredDuringExecution:
                  nodeSelectorTerms:
                    - matchExpressions:
                        - key: <GPU_WORKLOAD_LABEL>
                          operator: In
                          values: [<LLM_SERVING_VALUE>]
                        - key: <GPU_MODEL_LABEL>
                          operator: In
                          values: [<L20_VALUE>]
              podAntiAffinity:
                requiredDuringSchedulingIgnoredDuringExecution:
                  - labelSelector:
                      matchLabels:
                        model.aibrix.ai/name: qwen3-235b-fp8-ray-8n
                    topologyKey: kubernetes.io/hostname
            containers:
              - name: ray-head
                resources: &one_l20
                  requests:
                    cpu: "8"
                    memory: 64Gi
                    nvidia.com/gpu: "1"
                  limits:
                    cpu: "16"
                    memory: 96Gi
                    nvidia.com/gpu: "1"
      workerGroupSpecs:
        - groupName: worker-group
          replicas: 7
          minReplicas: 7
          maxReplicas: 7
          template:
            spec:
              affinity: *fragmented_l20_affinity
              containers:
                - name: ray-worker
                  resources: *one_l20
```

Mandatory Pod Anti-Affinity is not decorative. Without it, the scheduler may place multiple single-GPU Pods on the same node that still has multiple idle GPUs, resulting in a topology different from the "one fragmented card per machine" validation goal.

The core vLLM Head parameters are as follows:

```bash
vllm serve /models/Qwen3-235B-A22B-Instruct-2507-FP8 \
  --served-model-name qwen3-235b-fp8-ray-8n \
  --tensor-parallel-size 1 \
  --pipeline-parallel-size 8 \
  --distributed-executor-backend ray \
  --quantization fp8 \
  --dtype auto \
  --gpu-memory-utilization 0.88 \
  --max-model-len 4096 \
  --max-num-seqs 1 \
  --enforce-eager \
  --trust-remote-code
```

In the first round, compress the context to 4K, concurrency to 1, and disable CUDA Graph, with the goal of reducing GPU memory and compilation variables. After the functionality works end-to-end, expand context, concurrency, and graph optimization separately—do not change all parameters at once.

### 8.4 Measured Process from Scheduling to API Ready

Eight Pods were scheduled to eight different nodes in a single pass, with no Pending state. Ray returned eight Active Nodes, the Placement Group atomically reserved 8/8 GPUs, and vLLM then divided the 94 layers into `[11,12,12,12,12,12,12,11]`.

| Stage | Measured Value |
| --- | ---: |
| First pull of runtime image | ~147 seconds, image ~10.9 GB |
| Loading 24 Safetensors shards | ~163–166 seconds |
| Engine profile, KV cache creation, and warmup | ~5.6 seconds |
| Container start to API Ready | ~3 min 45 sec |
| Pod creation to API Ready, including first image pull | ~6 min 14 sec |
| Model GPU memory per PP rank | ~30.20 GiB |
| Remaining KV cache per GPU | ~8.48 GiB |

Loading progressed at roughly one shard every 7 seconds. It is not valid to simply use "single shard file size ÷ 7 seconds" as CephFS throughput, because each PP worker traverses the shards, reads only the tensors belonging to its own rank, and also performs deserialization, CPU-to-GPU copies, and FP8 initialization. A more operationally meaningful metric is that with eight workers reading concurrently, the entire 235B model completed weight loading in about three minutes, with no CephFS timeouts or Pod restarts.

### 8.5 API and Performance Samples

The OpenAI-Compatible Chat Completions API returned correct Chinese results, proving this was not a "Pod Ready but Engine Unavailable" situation. One controlled hot request of 64 tokens produced:

| Metric | Measured Value |
| --- | ---: |
| TTFT | 4.859 sec |
| End-to-end latency | 12.647 sec |
| Steady-state decode | 8.089 token/s |
| TPOT | ~124 ms/token |
| Average output speed including TTFT | ~5.1 token/s |
| Prefill in log window | ~40–74 token/s |

This time window still contained a small number of interactive requests and was not an exclusive load test. The first request also triggered Ray Compiled DAG Communicator initialization, during which the log window briefly showed only 0.1–1.5 token/s; after the communication group warmed up, decode stabilized at approximately 7.6–8.1 token/s.

vLLM reported the minimum PP stage's GPU KV cache capacity at approximately 370K tokens and gave a theoretical concurrency capacity of roughly 90× for 4K requests, but this run explicitly set `max_num_seqs=1`, so **actual concurrency was still only 1**. Capacity logs cannot substitute for concurrency load test results.

### 8.6 Running Does Not Mean Optimized

Two important but non-blocking warnings appeared on the L20:

```text
CutlassBlockScaledGroupedGemm not supported on the current platform
Using default W8A8 Block FP8 / Fused MoE config; performance might be sub-optimal
```

This means vLLM used the correctness fallback path and default kernel configuration, and did not find a configuration tuned for the L20 and the current MoE shape. Combined with the seven cross-node transfers at PP=8, this result should be interpreted as:

- **Capacity and functionality are validated**: fragmented GPUs can form one 235B FP8 instance;
- **Interactive use is possible but TTFT is high**: ~4.9 seconds to first token on a hot request;
- **Steady-state generation is acceptable**: ~8 token/s for a single request;
- **Cannot be used directly as a production capacity value**: concurrency, long context, cancellation, timeout, and failure recovery still need load testing.

## 9. Running DeepSeek-R1-Distill-Llama-70B on Four Fragmented Nodes

### 9.1 Identify the Real Weight Set First

The model directory occupies approximately 395 GiB in total. When first seeing this number, one cannot directly conclude "four GPUs cannot fit it." Further inspection revealed the directory contains three copies of approximately 132 GiB of data:

- 17 Safetensors shards in the root directory, ~132 GiB;
- Another copy of weights in a version subdirectory, ~132 GiB;
- Git LFS repository objects, ~132 GiB.

The root directory's `model.safetensors.index.json` only indexes the 17 shards in the root directory; vLLM actually loads approximately 132 GiB, rather than feeding the entire 395 GiB directory into the GPU. Capacity assessment should be based on the files referenced by the index, not just the `du -sh <MODEL_DIR>`.

The model configuration is 80 layers `LlamaForCausalLM`, BF16 dense weights. Before deployment, it was confirmed in a same-version vLLM container that `LlamaForCausalLM` is registered and supports Pipeline Parallel.

### 9.2 Four-Node RayClusterFleet

Reusing the single-GPU node labels, anti-affinity, read-only CephFS, and runtime image from the Qwen3 experiment, changed to one Head plus three Workers:

```bash
vllm serve /models/DeepSeek-R1-Distill-Llama-70B \
  --served-model-name deepseek-r1-70b-ray-4n \
  --tensor-parallel-size 1 \
  --pipeline-parallel-size 4 \
  --distributed-executor-backend ray \
  --dtype bfloat16 \
  --gpu-memory-utilization 0.88 \
  --max-model-len 4096 \
  --max-num-seqs 1 \
  --enforce-eager \
  --trust-remote-code
```

Four Pods were scheduled to four different L20 nodes in a single pass. Ray returned four Active Nodes, the Placement Group atomically occupied 4/4 GPUs; the 80 layers were evenly split into four 20-layer PP stages.

| Stage or Resource | Measured Value |
| --- | ---: |
| Root directory weights | ~132 GiB, 17 shards |
| Weight loading | ~28.8–29.1 sec |
| Model GPU memory per PP rank | ~33.864 GiB |
| Remaining KV cache per GPU | ~4.63 GiB |
| Engine profile, KV cache creation, and warmup | ~1.89 sec |
| Container start to API Ready | ~83 sec |
| Minimum PP stage KV capacity | ~60K tokens |

The runtime image had already been cached by the nodes, so there was no 10.9 GB first-pull time this time. Unlike the Qwen3 MoE FP8, DeepSeek Distill 70B is dense BF16 and produced no FP8 or Fused-MoE kernel fallback warnings.

### 9.3 API Validation and Real Head-of-Line Blocking

The OpenAI-Compatible API successfully returned `<think>` inference content, proving that all four PP ranks completed generation together. DeepSeek-R1 may by default generate a long reasoning process first; an overly small `max_tokens` will cause the response to be truncated with `finish_reason=length` before the final answer. Clients need to correctly display Reasoning and reserve budget for reasoning tokens.

During the test window, Open WebUI automatically discovered the new model and generated interactive requests of up to approximately 2K–3.8K tokens. Because this run conservatively set `max_num_seqs=1`, the logs showed `Running=1、Waiting=1–3`. Three 64-token test requests produced:

| Request | TTFT after queueing | E2E | Decode after generation starts |
| --- | ---: | ---: | ---: |
| 1 | 97.390 sec | 109.642 sec | 5.142 token/s |
| 2 | 55.577 sec | 67.829 sec | 5.142 token/s |
| 3 | 65.226 sec | 77.477 sec | 5.142 token/s |

These TTFT values are mostly queueing time and **cannot be treated as idle-model TTFT**; however, they genuinely reveal a production risk: R1 long-reasoning requests against a single-concurrency engine cause severe head-of-line blocking. Decode in the log window stabilized at approximately 5.1 token/s, with a Prefill peak of approximately 172 token/s.

The next round of performance experiments should at least raise `max_num_seqs` to 4, while also limiting per-request maximum output, setting gateway timeouts, and cancellation propagation. Merely increasing theoretical KV cache concurrency without handling long requests can still leave short requests queued behind long reasoning.

### 9.4 Why the 235B MoE Was Actually Faster at Generation

The two fragmented-GPU results cannot be compared by total model parameters alone:

| Model | Total Parameters and Precision | Per-Token Compute Characteristics | PP | Measured Decode |
| --- | --- | --- | ---: | ---: |
| Qwen3-235B-A22B FP8 | 235B, ~22B total activated | MoE, only some experts activated per token; FP8 | 8 | ~8.1 token/s |
| DeepSeek-R1-Distill-Llama-70B BF16 | 70B | Dense, full 70B traversed per token; BF16 | 4 | ~5.1 token/s |

Although Qwen3 has larger total weights and more PP stages, its activated parameter count is smaller and it uses FP8; DeepSeek Distill 70B computes the full dense 70B for every token, so the latter being slower at decode is not contradictory. This comparison is still affected by network, kernels, prompts, and concurrent traffic, and can only be interpreted as a measured explanation within this environment.

### 9.5 Why It Was Slow, and Optimization Priorities

This round's topology prioritized answering "can fragmented GPUs form one large model," not single-request performance optimality. For every token DeepSeek generates, it must sequentially pass through four PP stages; the four stages sit on four nodes using 10Gb TCP, and the experiment explicitly set `NCCL_IB_DISABLE=1`, without RoCE/InfiniBand. The dense 70B also passes through the full model for every token, so ~5.1 token/s is the result of multiple constraints stacking.

Optimization must distinguish two goals:

| Goal | Priority Action | Expected Impact |
| --- | --- | --- |
| Reduce concurrent TTFT | Change `max_num_seqs` from 1 to 4, then gradually load test to 8 | Reduces head-of-line blocking from long-reasoning requests; does not guarantee multiplicative single-request decode improvement |
| Reduce concurrent TTFT | Gateway limits maximum output, sets cancellation propagation, and splits long/short request queues | Prevents one 3K-token request from blocking all short requests |
| Improve interactive experience | UI streams `<think>` / Reasoning | Users can see the model has started working, but compute speed is unchanged |
| Improve single-request decode | Remove `--enforce-eager`, A/B test CUDA Graph | Reduces kernel launch overhead; gains must be measured |
| Improve single-request decode | Compress 4 GPUs to two nodes × two GPUs or one node × four GPUs | Reduces cross-node PP hops; usually the most direct topology optimization |
| Improve single-request decode | Use 25/100Gb networking, RoCE/IB, and NCCL RDMA | Reduces activation transfer latency only when cross-node is unavoidable |
| Improve single-request decode | Use FP8, INT8, or INT4 70B weights | Reduces GPU memory and compute overhead, and may shrink PP=4 to PP=2 |
| Improve single-request decode | Upgrade vLLM/CUDA kernels, test Ray Compiled DAG communication overlap | Obtains newer model implementations and communication optimizations; requires regression testing for stability |
| Improve single-request decode | Speculative decoding | Uses a draft model to accept multiple tokens at once; increases GPU memory and system complexity |

P/D separation mainly improves throughput, resource isolation, and goodput under mixed traffic; it does not automatically make single-request decode faster. If the decode group remains four-node PP=4 over 10Gb TCP, its single-stream generation speed is still limited by the same data path.

After the topology A/B is complete, the lowest-risk next-round controlled experiment is to keep the best-performing single-node four-GPU configuration and 4K context, and only change `max_num_seqs=4` while removing `--enforce-eager`. First compare Ready time, idle TTFT, 4-way concurrent TTFT, decode, GPU utilization, and cancellation behavior; only then decide whether to introduce quantization, RDMA, or P/D. Do not change all variables at once.

### 9.6 A/B Measured Results for Three Four-GPU Topologies

The regular service pool had no idle four-GPU node, but two same-model L20 nodes were found, each already using 6/8 GPUs and each still having two GPUs available. Without migrating or preempting existing workloads, a separate RayClusterFleet was created using node-scope constraints and Pod anti-affinity to pin one dual-GPU Head and one dual-GPU Worker spread across the two nodes:

```text
节点 A：Rank 0 = PP 0 / TP 0，Rank 1 = PP 0 / TP 1
                         │
                         │  仅 PP 边界跨节点
                         ↓
节点 B：Rank 2 = PP 1 / TP 0，Rank 3 = PP 1 / TP 1
```

The two TP ranks within a node cooperate via GPU P2P/NCCL, leaving only one PP boundary across nodes. Startup logs confirmed the PP/TP grouping of the four ranks, and the Ray Placement Group obtained 4/4 GPUs; the 80-layer model was split into two PP stages, each doing two-GPU TP.

Next, the four-node single-GPU and two-node dual-GPU fleets were scaled down to 0. In an isolated pool, an `Ready=True` L20 node was found with no resource pressure, all 8 GPUs unallocated, but carrying the `offline-node` NoSchedule/NoExecute taint. The experiment did not remove the node taint; instead, it explicitly added a Toleration only in the newly created test Fleet and used a Hostname to pin the single four-GPU Head to that node. This way, even if the node is unsuitable for running models, any failure remains contained within the test instance.

The single-node startup logs confirmed all four ranks were PP Rank 0, with TP ranks 0–3:

```text
单节点：Rank 0 = PP 0 / TP 0
        Rank 1 = PP 0 / TP 1
        Rank 2 = PP 0 / TP 2
        Rank 3 = PP 0 / TP 3
```

To ensure differences came only from topology, the three test groups kept model weights, total L20 GPU count, vLLM version, BF16, 4K context, `max_num_seqs=1`, `--enforce-eager`, prompt, and 64-token output limit identical. Requests were sent after the instance was idle, and SSE was parsed line by line, computing TTFT from the first non-empty token rather than the HTTP response header:

| Topology | Hot idle TTFT | 64-token E2E | Steady-state decode |
| --- | ---: | ---: | ---: |
| Four nodes × single GPU, TP=1, PP=4 | ~0.250 sec | ~12.52 sec | ~5.13 token/s |
| Two nodes × dual GPU, TP=2, PP=2 | ~0.140 sec | ~6.49 sec | ~9.92 token/s |
| Single node × four GPUs, TP=4, PP=1 | ~0.124 sec | ~3.56 sec | ~18.33 token/s |

Using four-node single-GPU as the baseline, two-node dual-GPU improved decode by approximately 93%; single-node four-GPU improved it by approximately 257%, i.e., about 3.57×. Compared with two-node dual-GPU, single-node four-GPU further reduced TTFT by approximately 11%, E2E by approximately 45%, and improved decode by approximately 85%. The single-node first-round TTFT was 1.148 seconds, stabilizing to 0.124 seconds in the following two rounds, so the first round was marked as first-request warmup and not mixed into hot TTFT.

For two-node dual-GPU, each rank loaded approximately 32.89 GiB of model GPU memory, with approximately 5.64 GiB of available KV cache and a minimum-stage KV capacity of approximately 73K tokens. Weight loading took approximately 44–49 seconds, slower than the previous four-node single-GPU's approximately 29 seconds; this is a difference in shared filesystem reads, node caching, and concurrent loading behavior, and cannot be used to conclude compute topology degradation.

For single-node four-GPU, each rank loaded approximately 32.89 GiB of model GPU memory, with approximately 5.67 GiB of available KV cache and a KV capacity of approximately 74.3K–75.3K tokens; weight loading took approximately 90 seconds, and engine profile, KV cache creation, and warmup took approximately 7.2 seconds. This node pulled the ~10.9 GB runtime image for the first time; image pull time is not included in the inference metrics above.

The log also shows one important warning: this machine has four PCIe-only GPUs, and vLLM does not support Custom AllReduce on more than two such GPUs, so it automatically falls back to NCCL AllReduce. Even with this fallback, the benefit of eliminating cross-node PP still far outweighs the cost of local four-card AllReduce; however, if the node has NVLink/NVSwitch, TP=4 still has further room for improvement.

After the three rounds of single-node testing, the server-side metrics recorded exactly 3 completed requests and 192 generated tokens, `running=0`, `waiting=0`, `abort=0`, confirming that the results were not contaminated by external traffic.

The test also captured a sample caused by an external long request being inserted: TTFT rose to approximately 13.8 seconds, but Decode after the request began executing was still about 9.92 token/s. This sample was excluded from the idle A/B comparison but retained as production evidence:

- TTFT must be correlated with `num_requests_running`, `num_requests_waiting`, and queue time together;
- In SSE scenarios, `curl time_starttransfer` usually only measures the response headers and cannot be treated as the first token;
- With a fixed output length, Decode should be calculated from the first valid token to completion;
- The topology improved single-stream speed, but head-of-line blocking at `max_num_seqs=1` still needs separate remediation.

This A/B test shows that fragmented scheduling should not only ask "can we gather four cards." In environments without high-speed RDMA, single-node four-card should be prioritized; secondarily, TP should stay within the node and the number of cross-node PP stages should be minimized; if only single-card fragments are available, the significant impact of PP hops on Decode must be accepted. Offline pool nodes can be used for short-term controlled experiments, but before re-entering the production serving pool, the node maintainer must confirm the offline reason, health baseline, and reclamation policy.

## 10. Blueprint for Multi-Node P/D Separation of Large Models

P/D separation cannot simply mark half of the existing PP ranks as Prefill and the other half as Decode. Both Prefill and Decode must be Engines capable of independently running the complete model, just optimized respectively for prompt computation and token-by-token generation:

```text
                         ┌─ Prefill RayCluster
AIBrix Gateway / Router ─┤    PP Rank 0 ... PP Rank N-1
                         │          │
                         │          └── NIXL KV Transfer
                         │                         │
                         └─ Decode RayCluster      ↓
                              PP Rank 0 ... PP Rank N-1
                                      └── Streaming Response
```

The minimum GPU bill will double directly:

| Model | Single Engine | 1 Prefill + 1 Decode | 1 Prefill + 2 Decode |
| --- | ---: | ---: | ---: |
| DeepSeek-R1-Distill-Llama-70B | 4×L20, PP=4 | 8×L20 | 12×L20 |
| Qwen3-235B-A22B FP8 | 8×L20, PP=8 | 16×L20 | 24×L20 |

At implementation time, two independent RayClusters or RayClusterFleets are needed, each with a Service that selects only the Head Pod. Both Engines enable the NIXL Connector; the AIBrix P/D Router first selects the Prefill Group, then hands requests carrying KV Transfer metadata to the Decode Group.

The common vLLM parameters for both Engines include at least:

```bash
--tensor-parallel-size 1 \
--pipeline-parallel-size <4_OR_8> \
--distributed-executor-backend ray \
--kv-transfer-config '{"kv_connector":"NixlConnector","kv_role":"kv_both"}'
```

And NIXL/UCX, reachable Side Channel addresses, and data NICs must be uniformly configured for all ranks. `kv_both` indicates that the Engine has both send and receive capabilities; the specific request determines the Producer/Consumer role via the `kv_transfer_params` injected by AIBrix. It does not mean Prefill and Decode have no division of labor.

The existing single-Pod `StormService` P/D example cannot be copied as-is: each Role there is itself a single Pod, whereas here each Role is a multi-Pod RayCluster. A feasible engineering path is:

1. Create the Prefill RayClusterFleet and Decode RayClusterFleet separately;
2. Tag the two Head Services with the same model name and different P/D Roles;
3. Configure NIXL, UCX, Side Channel, and stable rank topology for both vLLM Engines;
4. Have the AIBrix P/D Router discover both Groups and verify the Producer/Consumer parameters for the same request;
5. Check whether the local Layer KV of each PP rank is correctly received by the corresponding Decode rank;
6. Then increase the number of Decode Groups and verify load balancing, request draining, and failure recovery.

The current environment has separately validated "multi-node Ray PP" and "single-Pod StormService + NIXL P/D," but **the combined multi-node P/D has not yet been validated**. In particular, seeing both RayClusters Ready is not sufficient to claim success; the same Request ID, complementary KV Transfer parameters, and final response evidence must be found in the logs of both the Prefill and Decode groups.

The enterprise value of P/D mainly appears under high concurrency and when the Prompt/Output ratio differs significantly. In low-QPS scenarios, it becomes more expensive due to duplicated weights, doubled cold-start time, and more resident GPUs; for the current head-of-line blocking at `max_num_seqs=1`, increasing Engine concurrency, limiting long outputs, and improving cancellation propagation may be more cost-effective than immediately replicating an entire P/D cluster.

## 11. Model Capacity Planning Not Yet Executed

| Candidate | Weight Size | Fragmented Card Topology | Current Assessment |
| --- | ---: | --- | --- |
| Qwen2.5-72B-Instruct BF16 | ~135 GiB | 4 nodes, 1 L20 per node, TP=1, PP=4 | Capacity close to the already-running 70B, **not deployed** |
| Qwen2.5-72B-Instruct GPTQ Int8 | ~72 GiB | 2–4 nodes, 1 L20 per node | More relaxed capacity, suitable as the next performance baseline, **not deployed** |
| Qwen3.5-397B-A17B GPTQ Int4 | ~220 GiB | 8 nodes, 1 L20 per node, prefer PP=8 | Capacity may hold, but current vLLM 0.10 has not registered Qwen3.5 MoE; requires runtime update and Ray completion, **not deployed** |

If GPUs are insufficient, only scale down or delete the workloads created by this experiment. First confirm by exact resource name, then execute:

```bash
kubectl -n <EXPERIMENT_NAMESPACE> get rayclusterfleet,stormservice,roleset,pod
kubectl -n <EXPERIMENT_NAMESPACE> delete rayclusterfleet <EXPERIMENT_RAY_FLEET>
kubectl -n <EXPERIMENT_NAMESPACE> delete stormservice <EXPERIMENT_STORM_SERVICE>
```

Do not use broad Labels or an entire Namespace to delete pre-existing production services.

## 12. Conclusions and Boundaries of This Round

What has been proven:

- AIBrix v0.7.0 can manage real-GPU RayClusterFleet and StormService;
- vLLM can run a 32B BF16 model with PP=2 on two L20s;
- Eight nodes each with one remaining L20 can run Qwen3-235B FP8 via Ray Placement Group and PP=8;
- Qwen3-235B FP8 uses approximately 30.20 GiB of model GPU memory per PP rank, with about 8.48 GiB reserved for KV Cache;
- This fragmented topology can complete OpenAI-Compatible API generation, with hot request samples at approximately 4.9 seconds TTFT and 8 token/s Decode;
- Four nodes each with one remaining L20 can run DeepSeek-R1-Distill-Llama-70B BF16 via PP=4;
- DeepSeek 70B uses approximately 33.864 GiB of model GPU memory per PP rank, weights load in about 29 seconds, generating at approximately 5.1 token/s;
- After changing the same four L20s to two nodes with two cards each, TP=2/PP=2, idle Decode improved to approximately 9.92 token/s, proving that reducing cross-node PP hops is the most effective single-stream optimization under current network conditions;
- After changing to single-node four-card, TP=4/PP=1, hot Decode further improved to approximately 18.33 token/s, about 3.57 times that of four-node single-card;
- Four PCIe-only L20s cause vLLM Custom AllReduce to fall back to NCCL, but the benefit of eliminating cross-node PP in this round still significantly outweighs the fallback cost;
- `max_num_seqs=1` exhibits significant head-of-line blocking when encountering R1 long-thinking requests, with queued request TTFT expanding to tens of seconds;
- AIBrix Gateway can discover and route to multi-machine Ray Engines;
- StormService can place Prefill and Decode on different nodes;
- The AIBrix P/D Router can generate complementary KV Transfer parameters for the same request;
- NIXL/UCX actually participate in KV Cache handoff;
- The CephFS model directory can maintain a two-layer read-only structure, with runtime cache writes going to temporary disk.

What has not yet been proven:

- A single hot request sample of Qwen3-235B can represent formal concurrency capacity or Goodput;
- The default FP8/Fused-MoE kernels on L20 have reached optimal performance;
- Qwen3.5-397B has run on the current topology;
- The distributed Prefill/Decode data path combining multi-node Ray PP with NIXL P/D is reliable;
- P/D has higher throughput or lower cost than colocated mode;
- The current TCP/UCX parameters are the optimal network configuration;
- Role-level autoscaling is safe under real model cold-start and request draining;
- Ray or P/D can recover losslessly under node failure, network jitter, cancellation, and timeout scenarios;
- The current image combination is suitable for long-term production operation; development builds still need digest pinning and security scanning.

For control-plane installation, CPU mock, autoscaling, and Higress integration, see: [Deploying AIBrix on an Existing Kubernetes Cluster](aibrix-existing-cluster.md). For measured results using the same images, models, and GPU topology but orchestrated by RBG, plus item-by-item comparison of RBG with RayClusterFleet/StormService, see: [RBG Multi-Role Inference Orchestration: From CPU Control Plane to Production GPU Measurements](rbg-existing-cluster.md#rbg-vs-aibrix-production). For the conceptual boundaries of multi-machine model parallelism and P/D, see: [Distributed and P/D-Separated Inference](../inference/distributed-serving.md). For GPU pages, offline images, and cross-cluster entry points, see: [Deploying ComfyUI on Kubernetes](comfyui-minimax-h3-gpu.md).
