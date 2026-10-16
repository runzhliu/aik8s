---
title: "Ray's Role in Large Model Training and Inference"
description: "The boundaries of Ray Core, Data, Train, Tune, Serve, Serve LLM, and KubeRay in large model data processing, training, post-training, and online inference"
status: evolving
last_reviewed: 2026-08-04
---

# Ray's Role in Large Model Training and Inference

Ray has become important again in the large model era, not because it invented new training kernels or inference engines, but because large model systems need to simultaneously coordinate data processing, distributed training, hyperparameter search, batch inference, online serving, and reinforcement learning rollouts. Ray uses a unified Python Task, Actor, resource, and scheduling model to bring these stages into the same distributed runtime.

Its boundaries must be stated clearly first: Ray is responsible for process orchestration, resource placement, data flow, and application lifecycle; PyTorch, JAX, DeepSpeed, FSDP, NCCL, vLLM, SGLang, and others remain responsible for model computation, parallel algorithms, and communication. Treating Ray as a training framework or a replacement for CUDA/NCCL will directly lead to incorrect architectural judgments.

## 1. Why Large Models Need Ray More Than Traditional Machine Learning

Traditional training often resembles a fixed worker group: prepare data, start several ranks, and exit after training completes. Large model platforms add more heterogeneous, dynamic, and stateful roles:

- CPU workers parse, filter, tokenize, and pack data;
- GPU workers execute pretraining, SFT, DPO, GRPO, and other training;
- Multiple trials search learning rate, parallelism, and batch in parallel;
- Reward, Reference, Policy, Rollout, and other models collaborate in post-training;
- vLLM/SGLang workers execute online or batch generation;
- Router, Preprocessor, Retriever, and Postprocessor form the online inference graph;
- Different roles use different GPU, CPU, memory, network, and elasticity policies.

Ray's Task/Actor, Placement Group, heterogeneous resources, and shared object transfer are well suited to expressing this kind of dynamic Python distributed system. But fixed-topology, single-framework large-scale pretraining may not need Ray; `torchrun`, Kubeflow Trainer, JobSet, Slurm, or framework-native launchers may still be more direct.

## 2. Ray Ecosystem Layers

| Layer | Core Abstraction | Responsibility in Large Model Systems |
| --- | --- | --- |
| Ray Core | Task, Actor, Object Ref, Placement Group | Distributed execution, stateful services, resource declaration, and grouped placement |
| Ray Data | Dataset, Block, Streaming Execution | Data reading, transformation, tokenization, batch inference, and training data supply |
| Ray Train | Trainer, Worker, ScalingConfig, Checkpoint | Launching training workers, establishing framework distributed environments, recovery, and metrics |
| Ray Tune | Tuner, Trial, Search Algorithm, Scheduler | Hyperparameter search, trial concurrency, early stopping, and resource allocation |
| Ray Serve | Deployment, Replica, Handle, Application | Python microservice graph, traffic, batching, backpressure, and independent scaling |
| Ray Serve LLM | LLMServer, Ingress, Routing, Engine Adapter | Multi-node/multi-model LLM serving, vLLM integration, P/D separation, and advanced routing |
| KubeRay | `RayCluster`, `RayJob`, `RayService` | Managing Ray clusters, batch jobs, and online services on Kubernetes |

Ray AIR once appeared as a unified brand for multiple libraries. Platform APIs should not depend on brand names but should pin the actual Ray Data, Train, Tune, Serve, and KubeRay versions and interfaces in use.

## 3. An End-to-End Large Model Pipeline

```text
对象存储 / Lakehouse Snapshot
          │
       Ray Data
解析、过滤、Tokenize、Shuffle、Streaming Split
          │
       Ray Train
PyTorch / FSDP / DeepSpeed / Transformers / JAX
          │
  Checkpoint / Model Registry
          │
     ┌────┴───────────────┐
     ▼                    ▼
Ray Data Batch        Ray Serve LLM
离线生成/评估          vLLM/SGLang Replica
     │                    │
评估集/偏好数据       Gateway / OpenAI API
     └────────┬───────────┘
              ▼
       反馈、后训练与新版本
```

Kubernetes perspective:

```text
Pipeline / SDK / Git
        │
RayJob（批处理、训练、调参） / RayService（在线服务）
        │
Kueue 准入与配额
        │
KubeRay 创建 Head/Worker Pod
        │
Ray Scheduler 放置 Task、Actor、Placement Group
        │
框架内部使用 NCCL/Gloo/HTTP/Object Store
```

The Kubernetes Scheduler decides which node a Pod goes to; the Ray Scheduler decides which Ray worker process a Task/Actor goes to. Both layers schedule, but the objects and time scales differ.

## 4. Key Semantics of Ray Core

### Task and Actor

- **Task** is suitable for stateless, parallelizable functions that release resources upon completion, such as file parsing, tokenization, and offline evaluation;
- **Actor** is a stateful process, suitable for model replicas, tokenizer services, rollout workers, and long-lived caches;
- **Object Ref/Object Store** transfers objects between Tasks/Actors, suitable for intermediate data exchange, but not a persistent data lake;
- **Placement Group** reserves a set of resource bundles and controls placement with strategies such as `PACK`, `STRICT_PACK`, and `SPREAD`.

Before large objects enter the Object Store, evaluate serialization, shared memory, network replication, and spill. Model weights, checkpoints, and authoritative data should still be placed in object storage, shared file systems, or a model registry, rather than relying on the Ray Object Store for long-term persistence.

### Resources Are Logical Labels

Ray can declare CPU, GPU, and custom resources, but it does not create devices on behalf of Kubernetes. Kubernetes Pods first obtain devices through `nvidia.com/gpu`, DRA, etc.; Ray then allocates Actors/Tasks within the resources the Pod already owns.

Custom resources are suitable for expressing:

- GPU model or node capability;
- Whether the local model cache is hit;
- Specific network or accelerator;
- Roles that can only be placed on a certain type of worker group.

Custom resource labels are not real isolation; the underlying layer still requires Kubernetes Resources, Node Labels, Affinity, and security policies.

## 5. Three Entry Points of KubeRay

| CRD | Lifecycle | Suitable For | Not Recommended For |
| --- | --- | --- | --- |
| `RayCluster` | Long-lived or managed by external systems | Shared development clusters, manual submission, multi-job services | All tenants sharing one unlimited-lifecycle cluster without governance |
| `RayJob` | Create cluster, submit Job, reclaim after completion | Data processing, training, Tune, batch inference | Online services or long-lived traffic that depends on fixed endpoints |
| `RayService` | RayCluster + Serve Application | Online inference, composable AI services, rolling upgrades | One-off batch jobs |

The official recommendation is to use KubeRay to run Ray on Kubernetes. Production platforms typically default to:

- Batch jobs use a dedicated `RayJob` per job, reclaiming the cluster after completion;
- Online services use a dedicated `RayService`;
- Shared `RayCluster` is only for controlled development, interactive analysis, or a large number of short tasks;
- Do not place training and online inference in the same RayCluster to compete for resources and fault budgets.

References: [KubeRay](https://ray-project.github.io/kuberay/), [Ray on Kubernetes](https://docs.ray.io/en/latest/cluster/kubernetes/)

## 6. Ray Data: Connecting CPU Data Processing with GPU

Ray Data uses Blocks and streaming execution to process Parquet, JSON, images, audio, video, and other data, suitable for:

- Python/UDF, tokenizer, and multimodal decoding before training;
- Pipelining CPU preprocessing with GPU training;
- Embedding, reward scoring, synthetic data, and offline generation;
- Automatically sharding Datasets to Ray Train workers;
- Organizing batch processing pipelines across heterogeneous CPU/GPU worker groups.

```text
Read → Map/Filter → Repartition/Shuffle → map_batches(GPU) → Write
                        │
                        └→ iter_torch_batches() → Train Worker
```

Key tuning items:

- Block size and count, avoiding oversized single blocks or scheduling explosion;
- `map_batches` batch, concurrency, and Actor Pool;
- Backpressure between CPU parsing, object store reads, and GPU consumption;
- Object Store memory, spill directory, and local disk watermarks;
- Small files, compression formats, and tokenizer CPU overhead;
- Whether to cache, recompute, or directly use the framework DataLoader when re-reading across training epochs.

Ray Data is more like a Python execution layer for AI data processing and should not automatically replace Spark/Flink: complex SQL, large-scale Lakehouse table maintenance, continuous stateful stream computing, and mature data governance are usually still handled by big data platforms. A common combination is Spark/Flink generating versioned tables, with Ray Data handling the last-mile processing closest to the model.

References: [Ray Data](https://docs.ray.io/en/latest/data/data.html), [Ray Train Data Loading](https://docs.ray.io/en/latest/train/user-guides/data-loading-preprocessing.html)

## 7. Ray Train: Training Control Layer, Not a Training Kernel

Ray Train's basic model is: the user defines a Training Function, the Trainer creates a group of workers, configures resources and count, establishes the distributed environment for frameworks such as PyTorch, and then executes the training function on each worker.

```python
from ray.train import ScalingConfig
from ray.train.torch import TorchTrainer

def train_loop(config):
    # 初始化模型、数据、FSDP/DeepSpeed，并报告指标与 Checkpoint。
    ...

trainer = TorchTrainer(
    train_loop,
    scaling_config=ScalingConfig(num_workers=8, use_gpu=True),
)
result = trainer.fit()
```

Suitable combinations:

| Training Stack | Ray's Responsibility | Framework's Responsibility |
| --- | --- | --- |
| PyTorch DDP/FSDP | Worker lifecycle, rank environment, results, and recovery | Gradient synchronization, parameter sharding, and computation |
| DeepSpeed | Process and resource orchestration | ZeRO, parallelism, optimizer, and communication |
| Hugging Face Transformers/Accelerate | Distributed launch, checkpoint/metric integration | Trainer, model, and training loop |
| JAX/Lightning | Cluster execution and resources | Framework parallelism and training semantics |

In large-scale pretraining, whether Ray is worth introducing depends on peripheral complexity. If the task is simply running a fixed 128 ranks for weeks, a native launcher may be simpler; if the same platform also needs data processing, elastic trials, evaluation, generation, and post-training Actor orchestration, Ray's unified execution model provides greater value.

References: [Ray Train Overview](https://docs.ray.io/en/latest/train/overview.html), [Ray Train Examples](https://docs.ray.io/en/latest/train/examples.html)

## 8. Checkpoints and Training Fault Tolerance

Ray can rebuild worker groups after worker/node failure, but progress recovery depends on the application saving and loading checkpoints. Default retry counts, driver fault tolerance, and Train API behavior may differ across Ray versions and must be verified against the target version.

Production requirements:

- `storage_path` points to object storage or a shared file system accessible to all workers;
- Model-parallel frameworks such as FSDP, DeepSpeed, and Megatron should upload their respective shards in parallel first;
- Checkpoints include model, optimizer, scheduler, random state, and data watermark;
- Drill head/driver, worker, node, and object store failures separately;
- Best-effort save before spot node termination, but do not rely on PreStop completing;
- Limit retries and distinguish node failure, OOM, data errors, and code exceptions.

Ray Train worker failure recovery typically stops the current worker group, recreates all workers, and resumes from the latest checkpoint. It is not a lossless hot replacement of a single rank.

References: [Ray Train Fault Tolerance](https://docs.ray.io/en/latest/train/user-guides/fault-tolerance.html), [Ray Train Checkpoints](https://docs.ray.io/en/latest/train/user-guides/checkpoints.html)

## 9. Ray Tune: Searching Experiments, Not Scaling a Single Model

Ray Tune allocates resources across multiple trials and can combine with Ray Train so that each trial is itself distributed training. It is suitable for:

- Searching SFT/DPO learning rate, batch, LoRA rank, etc.;
- Exploring quantization, parallelism, and inference parameters;
- Early stopping with ASHA/HyperBand, etc.;
- After small-scale screening of key parameters, launching full training.

Capacity must be calculated according to the nesting relationship:

```text
总 GPU ≈ 并发 Trial 数 × 每 Trial Worker 数 × 每 Worker GPU
```

Do not let dozens of trials automatically consume the production GPU pool. The Tune Driver, trial checkpoints, search state, and remote storage must also enter the fault recovery design.

References: [Ray Tune](https://docs.ray.io/en/latest/tune/), [Ray Train Hyperparameter Optimization](https://docs.ray.io/en/latest/train/user-guides/hyperparameter-optimization.html)

## 10. Post-training and RLHF/GRPO

Large model post-training often includes multiple model roles and two distinctly different workloads:

```text
Prompt Dataset
   │
Rollout Engine（vLLM/SGLang，多次生成）
   │
Reward / Verifier / Reference Model
   │
Advantage 与样本整理
   │
Policy Training（PyTorch/DeepSpeed/FSDP）
   └──────── 新权重同步回 Rollout Engine
```

Ray Actors are well suited to expressing long-lived Policy, Reference, Reward, and Rollout roles; Ray Tasks are suitable for parallel scoring and data organization; Placement Groups can coordinate the GPU bundles of each role. Therefore, many post-training systems use Ray as the orchestration foundation and use vLLM/SGLang for rollouts and PyTorch/DeepSpeed for updates.

The truly difficult parts are not "launching Actors" but:

- Whether training and rollout share GPUs, and how to avoid GPU memory peak conflicts;
- How often weights are synchronized, using full, sharded, or incremental transfer;
- How the rollout version corresponds to the policy step;
- How to apply backpressure when Reward/Verifier becomes slow;
- How to dynamically adjust the GPU ratio among generation, training, and data processing;
- Whether failed recovery causes duplicate consumption or sample contamination;
- Whether algorithm implementations, Ray, PyTorch, vLLM, and CUDA versions are compatible.

Ray itself does not provide complete RLHF algorithm correctness, reward design, or weight synchronization protocols. When adopting a Ray-based post-training framework, separately review its support for PPO, DPO, GRPO, and other algorithms, model parallelism, and target hardware.

## 11. Ray Data Batch Inference

Offline embedding, reward scoring, evaluation, and synthetic data typically do not require long-lived HTTP services. Ray Data can let a GPU Actor Pool execute inference on batches and write results back to a Lakehouse or object storage.

Differences from online services:

| Dimension | Ray Data Batch Inference | Ray Serve Online Inference |
| --- | --- | --- |
| Input | Dataset/files/tables | HTTP/gRPC/Handle requests |
| Optimization target | Total throughput, cost, recoverability | TTFT, TPOT, tail latency, availability |
| Backpressure | Dataset execution pipeline | Queue, replica, and request rejection |
| Lifecycle | Exits after completion | Long-running |
| Output | Files/tables/datasets | Streaming or normal responses |

Do not route billions of offline records one by one through the production gateway just to reuse an API; and do not use batch jobs to handle online requests that require low latency and streaming responses.

## 12. Ray Serve: Composable AI Microservices

Ray Serve Deployments can individually wrap preprocessing, embedding, retriever, reranker, LLM, guardrail, and post-processing steps, and compose them into an application graph through Deployment Handles. Each Deployment can use different resources and replica counts.

```text
HTTP/gRPC Ingress
      │
  Auth/Router
      │
  ┌───┼──────────┐
  ▼   ▼          ▼
Embed Retriever Guardrail
  └───┬──────────┘
      ▼
   LLM Replica
      ▼
 Postprocess/Stream
```

It suits Compound AI applications that have substantial Python logic, pass many objects between components, and need independent scaling. The platform still needs to provide unified identity, tenant quotas, WAF, global traffic, and API governance outside Ray Serve; do not let each application implement its own enterprise gateway.

In production on Kubernetes, prefer `RayService`, with KubeRay managing health, status, cluster recovery, and upgrades. Serve Config is used to declare Application and Deployment parameters; images or remote `working_dir` must be immutable.

References: [Ray Serve Production Guide](https://docs.ray.io/en/latest/serve/production-guide/), [Deploy Ray Serve on Kubernetes](https://docs.ray.io/en/latest/serve/production-guide/kubernetes.html)

## 13. Relationship Between Ray Serve LLM and vLLM

vLLM is an inference engine; Ray Serve LLM is a distributed serving framework built around inference engines. A typical combination is:

```text
Ray Serve LLM
  ├── OpenAI-Compatible Ingress
  ├── Router / Autoscaling / Deployment Graph
  └── LLMServer Replica
        └── vLLM Engine
              └── TP / PP / GPU Worker
```

Ray Serve LLM currently focuses on:

- Horizontal scaling of a single model and multi-model serving;
- Cross-node Tensor/Pipeline Parallel;
- Prefix/Session-aware custom routing;
- Multi-LoRA;
- Prefill/Decode separation;
- Large-scale patterns such as Data Parallel Attention and Expert Parallel;
- OpenAI-Compatible API, metrics, and Grafana integration.

If a single `Deployment + vLLM` already meets the SLO, there is no need to add Ray merely for "cloud-native" reasons. The following scenarios are more worth evaluating Ray Serve LLM: a single logical replica spans nodes, multiple models need unified Python control, complex pre/post-processing needs independent scaling, or Ray is already used to host training/post-training and data processing.

References: [Ray Serve LLM](https://docs.ray.io/en/latest/serve/llm/), [Ray Serve LLM Architecture](https://docs.ray.io/en/latest/serve/llm/architecture/overview.html)

## 14. Three Layers of Elasticity Must Work Together

```text
Ray Serve Autoscaler：请求队列 → Replica 数
          │
Ray Autoscaler：待调度 Actor/Task → Ray Worker Pod 数
          │
Node Autoscaler：Pending Pod → Kubernetes Node 数
```

Training batch workloads may also add a fourth layer of Kueue admission. Common problems:

- Serve has already scaled up Replicas, but Ray Worker Pods are still waiting for GPU;
- Ray scaling is faster than node and model warm-up, causing many Pending states;
- Model cache and Object Store data are lost when Nodes scale down;
- Kueue has already admitted up to the limit, but the Ray Autoscaler requests Workers beyond the quota;
- HPA, Ray Serve Autoscaler, and external Autoscalers modify the same replica count simultaneously.

Each layer should set minimum, maximum, cooldown, and failure boundaries. For LLM scaling metrics, prioritize Queue, Running Request, Token, KV Cache, TTFT/TPOT rather than only CPU or GPU Utilization.

Reference: [Ray Serve Autoscaling](https://docs.ray.io/en/latest/serve/autoscaling-guide.html)

## 15. Kueue, Gang, and Elastic RayJob

Kueue can manage quotas and admission for `RayJob`, `RayCluster`, and `RayService`. Batch training often uses `RayJob`: Kueue controls `spec.suspend`, and only after admission does KubeRay create the RayCluster.

Notes:

- Fixed-size distributed training should be admitted as a complete Head + Worker Group gang;
- RayJobs managed by Kueue should not reuse an existing RayCluster and should be reclaimed after completion;
- Ray In-tree Autoscaling and Kueue elastic Workload versions and Feature Gates must match;
- `minReplicas` is the minimum runnable resource, and `maxReplicas` is the capacity ceiling; both enter queue planning;
- Ray Placement Groups can only place Actors inside already-admitted, already-created Pods and cannot replace cluster-level quotas.

Reference: [Kueue RayJob](https://kueue.sigs.k8s.io/docs/tasks/run/rayjobs/)

## 16. GPU, Topology, and High-Speed Networks

Ray can express Placement Groups, but it does not automatically understand all hardware topology. Large-model training and multi-node inference still require configuration of:

- Kubernetes Node Affinity, Taint/Toleration, and topology-aware scheduling;
- Head Pods should not request expensive GPUs unless they actually execute model work;
- Worker Groups split by GPU model, CPU/memory, NIC, and purpose;
- TP should be placed within the same NVLink/NVSwitch domain where possible;
- PP/training across nodes requires verifying RDMA, NCCL, MTU, and NUMA;
- Object Store, `/dev/shm`, Spill, and model cache require temporary storage requests;
- Placement Group Bundles must exactly match the GPU/CPU of each actual Actor.

The Ray Dashboard showing sufficient logical resources does not mean NCCL selected the correct NIC or that GPU and NIC are on the same NUMA node. Network baselines still need independent verification with NCCL Tests, iperf/ib_write_bw, and similar tools.

## 17. Head, GCS, and Failure Domains

The Ray Head hosts critical functions such as GCS, Dashboard, and Job/Serve control entry points. By default, GCS state is primarily in memory; Head/GCS failure can lead to loss of cluster state.

Recommendations:

- Batch `RayJob` relies on external Checkpoints and Job reconstruction, and does not treat the Head as persistent state;
- High-availability `RayService` should evaluate GCS Fault Tolerance and HA Redis according to the official support matrix;
- The Head should use reliable nodes, PriorityClass, PDB, and reasonable resources to avoid CPU/memory being squeezed by Worker tasks;
- Do not expose Dashboard, GCS, Ray Client, and Job Submission ports to the public network;
- Record the association between RayService, Serve Application, Deployment, Actor, and underlying Pods.

GCS Fault Tolerance does not mean lossless requests: connections, queued requests, Actor memory, and non-persisted Objects can still be lost.

Reference: [KubeRay GCS Fault Tolerance](https://docs.ray.io/en/latest/cluster/kubernetes/user-guides/kuberay-gcs-ft.html)

## 18. Storage and Dependency Release

- Production images pin Ray, Python, CUDA, PyTorch, vLLM, and business dependencies;
- Do not let all Workers fetch from the public internet `pip install` after startup;
- Runtime Environment suits small-scale, immutable remote packages and should not replace the image supply chain;
- Checkpoints, training results, and Dataset Manifests use object storage or reliable shared file systems;
- Object Store Spill uses local NVMe/PVC with clear capacity, and disk water levels are monitored;
- Model weights are distributed via node cache, PVC, object storage, or P2P, not relayed through the Ray Head;
- The Ray version in Head and Worker images must match the target KubeRay version matrix.

## 19. Observability

| Layer | Key Metrics and Logs |
| --- | --- |
| Kubernetes | Pod Pending, startup, eviction, GPU/CPU/memory/temporary storage |
| KubeRay | CR Condition, Operator Reconcile, cluster creation and upgrade |
| Ray Core | Node, Task, Actor, Placement Group, Object Store, Spill |
| Ray Data | Block, Operator throughput, Backpressure, CPU/GPU Idle |
| Ray Train/Tune | Worker, Trial, Loss, Checkpoint, Retry, Driver |
| Ray Serve | Queue, Ongoing Request, Replica, Autoscaling, errors |
| LLM Engine | TTFT, TPOT, Token/s, KV Cache, Batch, model loading |

Recommended unified labels:

```text
namespace / tenant / raycluster / rayjob / rayservice
job_id / actor_id / serve_application / deployment / replica
model_id / dataset_snapshot / code_commit / image_digest
node / pod / gpu_uuid / accelerator_type
```

The Ray Dashboard is a diagnostic entry point, not a long-term monitoring database. Metrics go to Prometheus, logs go to a centralized platform, and events and Checkpoint metadata go to a persistent system.

## 20. Multi-Tenancy and Security

- Do not let mutually untrusted tenants share a single RayCluster; Ray Actor/Task is distributed Python code execution capability;
- Each RayJob/RayService uses a least-privilege ServiceAccount;
- NetworkPolicy restricts communication between Head, Workers, object storage, metrics, and external APIs;
- Dashboard, Client, GCS, and Job Submission are only open on trusted networks;
- RuntimeEnv, remote code packages, models, and Pickle/serialized objects all go through supply chain review;
- Object storage uses Workload Identity/short-term credentials;
- Set Namespace quotas, Kueue Queues, Priority, and maximum Worker counts;
- Online services and experimental tasks use different Namespaces, node pools, and credentials.

## 21. When to Prioritize Ray

Prioritize evaluating Ray when:

- The team is primarily Python-based and needs unified data, training, Tune, batch inference, and online serving;
- The workflow contains multiple dynamic Actor/model roles;
- CPU data processing needs to be pipelined with GPU stages;
- Post-training needs to coordinate Rollout, Reward, Reference, and Policy;
- An online application consists of multiple independently scalable Python inference steps;
- Multi-node vLLM/SGLang needs the orchestration capability of Ray Serve LLM.

Should not default to Ray when:

- There is only a single-node vLLM service;
- Fixed-topology pre-training is already stably handled by Slurm, Trainer/JobSet, or native Launchers;
- The main requirement is complex SQL, Lakehouse table maintenance, or continuous stateful stream processing;
- The team cannot bear the four-layer version matrix of Ray, KubeRay, Kubernetes, and model frameworks;
- The intent is merely to use one tool to mask data, Checkpoint, network, and scheduling problems.

## 22. Recommended Implementation Order

### Phase 1: Batch Tasks

- KubeRay Operator + standalone `RayJob`;
- CPU/GPU Worker Groups and object storage;
- Small-scale batch inference with Ray Data;
- Logging, Dashboard, Prometheus, and reclamation upon completion.

### Phase 2: Training

- Ray Train + PyTorch/FSDP or DeepSpeed;
- Kueue fixed-size admission;
- Distributed Checkpoints and node failure drills;
- Ray Data for last-mile data supply.

### Phase 3: Inference

- `RayService` manages composable applications;
- Start with a single-model vLLM baseline, then evaluate Ray Serve LLM;
- Four-layer capacity model of request queue, Replica, Ray Pod, and node;
- Canary, model warm-up, and Head/GCS failure drills.

### Phase 4: Post-Training and Advanced Elasticity

- Rollout/Reward/Policy role modeling;
- Tune, Spot, elastic RayJob;
- P/D separation, multi-node MoE, and weight synchronization;
- Continuous optimization by GPU-hour, Goodput, and recovery cost.

## 23. Launch Checklist

- [ ] Clarify the responsibility boundaries of Ray, Kubernetes, training frameworks, and inference engines;
- [ ] Batch tasks use RayJob, online services use RayService, with no mixing of lifecycles;
- [ ] The Head does not take on unintended GPU work and has independent resources and failure policies;
- [ ] Worker Groups are split by CPU/GPU/network/model role;
- [ ] Kueue admission, Ray Autoscaler, and Node Autoscaler upper/lower limits are consistent;
- [ ] Placement Group and TP/PP topology are verified with real hardware;
- [ ] Object Store, Spill, `/dev/shm`, and local cache complete capacity testing;
- [ ] Checkpoints reside on external persistent storage, and Worker/Head/node failures are recoverable;
- [ ] Ray Data does not leave GPUs idle due to Blocks, small files, or backpressure;
- [ ] Ray Serve metrics can be correlated with vLLM/SGLang and GPU metrics;
- [ ] Dashboard, GCS, Client, and Job APIs are not exposed to untrusted networks;
- [ ] Ray, KubeRay, Python, CUDA, PyTorch, and engine versions are locked;
- [ ] Multi-tenancy does not share RayClusters without security boundaries;
- [ ] There is a baseline that does not use Ray, allowing quantification of the benefits and operational costs it brings.

## Official Resources

- [Ray on Kubernetes](https://docs.ray.io/en/latest/cluster/kubernetes/)
- [KubeRay](https://ray-project.github.io/kuberay/)
- [Ray Data](https://docs.ray.io/en/latest/data/data.html)
- [Ray Train](https://docs.ray.io/en/latest/train/overview.html)
- [Ray Train Fault Tolerance](https://docs.ray.io/en/latest/train/user-guides/fault-tolerance.html)
- [Ray Tune](https://docs.ray.io/en/latest/tune/)
- [Ray Serve Production Guide](https://docs.ray.io/en/latest/serve/production-guide/)
- [Ray Serve LLM](https://docs.ray.io/en/latest/serve/llm/)
- [Kueue RayJob Integration](https://kueue.sigs.k8s.io/docs/tasks/run/rayjobs/)
