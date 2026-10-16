---
title: "Distributed Training Platform"
description: "Training controllers, Gang Scheduling, collective communication, fault tolerance, and job lifecycle"
status: evolving
last_reviewed: 2026-08-04
---

# Distributed Training Platform

Distributed training is not about "turning `replicas` up." The platform must simultaneously handle multi-role startup, group-based resource allocation, network topology, data provisioning, checkpoints, failure recovery, and experiment tracking. This page presents a design approach for the training control plane on Kubernetes.

If data processing, training, Tune, post-training Rollout, and online serving are all planned to use Ray, see [Ray's Role in Large Model Training and Inference](ray-llm-platform.md).

If you are not yet familiar with Loss, LoRA, Batch, Epoch, DP, TP, PP, and EP, first read [Large Model SFT Primer: Explaining Common Terms in One Go](training/sft-concepts.md). If the goal is to get training running hands-on, then gradually expand to MoE and DeepSeek V4, see [Large Model SFT Training in Practice: From Single-Card LoRA to DeepSeek V4](training/sft-from-single-gpu-to-deepseek-v4.md). That experiment first validates the data, Loss, Adapter, and inference loop with single-card LoRA, then provides the full eight-card upgrade path for V4-Flash. When you need to determine whether cross-machine training is worth adopting RDMA, see [DeepSeek V4 Dual-Machine 16-Card TCP/RDMA Real-World Measurements](training/rdma-distributed-training-benchmark.md). For framework selection, checkpoint semantics, and recovery flows after node failures, see [Multi-Machine Multi-Card Training Frameworks and Failure Recovery](training/distributed-training-frameworks-recovery.md).

## 1. What Happens During a Training Job

```text
代码与数据版本
    ▼
生成 TrainJob / RayJob / JobSet
    ▼
Kueue 准入：配额、优先级、ResourceFlavor、拓扑
    ▼
创建 Launcher / Leader / Worker Pods
    ▼
挂载数据、模型与检查点存储
    ▼
初始化通信：NCCL / Gloo / MPI / XLA
    ▼
训练、评估、周期性 Checkpoint
    ▼
写入对象存储、MLflow 与 Model Registry
```

The platform's goal is not to hide all Kubernetes details, but to let research code care only about training logic, while images, resources, scheduling, storage, and fault tolerance are expressed through reusable templates.

## 2. Three Main Control Approaches

| Approach | Core Abstraction | Advantages | Costs |
| --- | --- | --- | --- |
| Kubeflow Trainer | `TrainJob` + `TrainingRuntime` | AI-training-oriented, framework templates, Python SDK, Kueue/JobSet integration | Requires maintaining Trainer CRDs and Runtime templates |
| KubeRay | `RayCluster` / `RayJob` | Good Python experience; data, training, Tune, and Serve can share the Ray ecosystem | Applications are deeply bound to Ray's Actor/Task model |
| JobSet + native Jobs | A group of related Kubernetes Jobs | Framework-agnostic, clear semantics, suitable for self-built platforms or HPC | Requires wrapping training framework startup and user interfaces yourself |

### Kubeflow Trainer

Trainer is suitable for platform teams to predefine `ClusterTrainingRuntime`, where users only submit training functions, images, resources, and replica counts. The current version targets PyTorch, JAX, Hugging Face, DeepSpeed, MPI, and others, and reuses Kubernetes components such as Kueue, JobSet, and LeaderWorkerSet.

The new version also supports TrainJob pause, resume, and Active Deadline; pausing releases Pods, but whether training can truly resume still depends on whether the application correctly saves checkpoints.

References: [Kubeflow Trainer](https://www.kubeflow.org/docs/components/trainer/overview/), [TrainJob Lifecycle](https://www.kubeflow.org/docs/components/trainer/user-guides/trainjob-lifecycle/)

### KubeRay

KubeRay provides three main resource types:

- `RayCluster`: long-lived or manually managed Ray clusters;
- `RayJob`: creates a cluster, submits jobs, and can collect the cluster after completion;
- `RayService`: a combination of Ray Serve and RayCluster, providing high availability and rolling upgrade capabilities.

If data preprocessing, training, hyperparameter search, and serving are all Python-based, Ray reduces cross-system data movement; if the team primarily uses MPI, code migrated from Slurm, or framework-native launchers, Kubeflow Trainer/JobSet is often more natural.

For a more complete boundary between training, post-training, and inference, see [Ray's Role in Large Model Training and Inference](ray-llm-platform.md). Reference: [KubeRay](https://ray-project.github.io/kuberay/)

### JobSet

JobSet expresses distributed tasks as multiple `ReplicatedJob`, which can contain different Pod templates, and manages overall success, failure, restart, service discovery, and topology domains. It is suitable as a general execution layer for higher-level training APIs, rather than a direct replacement for all training frameworks.

Reference: [Introducing JobSet](https://kubernetes.io/blog/2025/03/23/introducing-jobset/)

## 3. Resources Must Be Admitted as a Group

Suppose a task needs 4 machines, each with 8 GPUs. If only 3 machines are scheduled successfully, 24 cards may sit idle while training can never start. This is the necessity of Gang or All-or-Nothing scheduling.

Training jobs should explicitly specify:

- `minAvailable` or the full PodSet size;
- CPU, memory, GPU, HugePages, and shared memory for a single Worker;
- acceptable GPU `ResourceFlavor`;
- whether downgrading to other models or Spot nodes is allowed;
- whether all workers must be concentrated in the same Rack/Block, or only best-effort concentration;
- maximum wait time, runtime, and retry count.

It is not recommended to mask capacity shortages with infinite retries. The queue should expose Pending reasons so users know whether it is "missing 8 H100s," "same-rack requirement not met," or "team quota exhausted."

## 4. Network and Communication

A multi-machine training platform must observe both the container network and the training communication library.

### Common Communication Stacks

| Framework/Mode | Common Communication |
| --- | --- |
| PyTorch DDP / FSDP | NCCL (GPU), Gloo (CPU/control) |
| DeepSpeed / Megatron-LM | NCCL + framework parallelism strategies |
| MPI / Horovod | MPI + NCCL |
| JAX / XLA | XLA Collectives, NCCL, or TPU ICI |
| Ray Train | Coordinated by Ray, but may still use Torch/NCCL underneath |

### Platform-Side Checks

- Whether Pods can discover the correct RDMA/RoCE devices;
- Whether MTU, PFC/ECN, and switch configurations are consistent;
- Whether NCCL is incorrectly falling back to the regular TCP NIC;
- Whether `/dev/shm` is sufficient;
- Whether CPU/NUMA, NICs, and GPUs are spread across sockets;
- Whether DNS, Headless Services, and Worker Ranks are stable;
- Whether NetworkPolicy allows training ports and control-plane connections.

Training performance degradation is not necessarily a GPU problem. It is recommended to save NCCL Test, storage throughput, and inter-node bandwidth baselines, and automatically re-run them after node or driver upgrades.

## 5. Data Provisioning Determines Whether GPUs Are Waiting

The GPU training pipeline typically includes: object storage → dataset cache → CPU decode/augmentation → Host Memory → GPU. A shortfall at any stage will make expensive GPUs wait.

### Common Data Approaches

| Approach | Advantages | Caveats |
| --- | --- | --- |
| Direct read from S3/object storage | Durable data, elastic capacity | Small files, repeated downloads, and remote latency can become bottlenecks |
| PVC / distributed file system | POSIX-compatible, minimal changes to legacy code | Metadata pressure, concurrent throughput, and cross-region costs |
| Node-local NVMe cache | High throughput, reduces remote reads | Data warm-up, eviction, consistency, and job migration |
| Streaming dataset reads | Reduces full disk writes and startup time | Requires framework, format, and retry mechanism cooperation |

It is recommended to store data versions as immutable URIs or Manifests, not directory names that change. Training records should at minimum associate: code Commit, image Digest, data version, hyperparameters, runtime version, and random seed.

## 6. Checkpoints Are Part of Scheduling Capability

Spot, preemption, and node failures only offer cost advantages when the application can recover. A qualified checkpoint solution must answer:

- How often to save, and how long saving takes;
- Whether all Ranks save, or the Leader aggregates;
- Whether checkpoints are atomically visible;
- Whether recovery works when the World Size changes;
- Whether the optimizer, learning rate scheduler, and random state are complete;
- Whether a final save can be triggered before job deletion, pause, or preemption;
- How old checkpoints are retained and cleaned up.

The following approximation can be used to determine the interval:

```text
预期浪费成本 ≈ 故障概率 × 平均丢失训练时间
Checkpoint 成本 ≈ 保存次数 × 单次暂停/IO 时间
```

Shorter intervals are not always better; the interval should be measured based on failure rate, save duration, and training unit cost.

## 7. Failure Classification and Recovery Strategies

| Failure Type | Platform Action | Retry Directly? |
| --- | --- | --- |
| Image pull, Secret, configuration errors | Fail fast and notify the user | No, resubmit after fixing configuration |
| GPU XID, node offline | Isolate device/node, restart from checkpoint | Yes, but with a limit on attempts |
| OOM | Save logs and GPU memory metrics | Usually no, need to adjust Batch/parallelism strategy |
| Spot reclamation | Graceful termination and recovery | Yes |
| NCCL timeout | Collect all Rank logs and network state | Conditional retry |
| Data corruption or Schema changes | Mark the data version as failed | No |
| Training Loss NaN | Treat as a model quality failure | Should not be infinitely retried by infrastructure |

The platform must distinguish Infrastructure Failures from User Code Failures; otherwise, automatic retries will repeatedly burn GPU time.

## 8. Images and Runtime Templates

It is recommended to split images into two layers:

1. **Platform base image**: CUDA/ROCm, Python, communication libraries, common diagnostic tools, and security updates.
2. **Project image**: training code with pinned dependencies.

Runtime templates should uniformly set:

- Non-root user and read-only root file system;
- `/dev/shm`, ephemeral storage, and ulimits;
- NCCL/communication environment variables;
- ServiceAccount, NetworkPolicy, and Secret references;
- Queue name, priority, topology requirements, and acceptable node pools;
- Metrics, logs, exit codes, and checkpoint hooks.

Do not copy a 300-line YAML into every project. The platform team maintains a small set of versioned Runtimes, and projects only override the necessary fields.

## 9. Observability and Experiment Records

At minimum, the infrastructure side should record:

- Job queueing, startup, running, pause, and completion times;
- Exit code and failure reason for each Rank;
- GPU SM, GPU memory, power, temperature, XID;
- CPU, memory, network, and storage throughput;
- NCCL Collective latency and training Step Time;
- Checkpoint time, size, and recovery results.

At minimum, the experiment side should record:

- Parameters, metrics, and model artifacts;
- Dataset and code versions;
- Training image Digest;
- Full resource and runtime configuration;
- Evaluation set results and model approval status.

MLflow is suitable for carrying experiment and model metadata; Prometheus/DCGM handles infrastructure time series; the two need to be linked through Run ID, Job UID, and model version, rather than replacing each other.

## 10. Pre-Production Checklist

- [ ] Baseline results exist for single-machine single-card, single-machine multi-card, and multi-machine multi-card.
- [ ] Jobs are admitted as a group and will not partially start and hold cards for a long time.
- [ ] Topology labels, RDMA, NCCL, and MTU have been verified.
- [ ] Datasets have immutable versions, and read throughput meets training requirements.
- [ ] Checkpoints can recover under real failure and preemption scenarios.
- [ ] User errors are not infinitely retried by the platform.
- [ ] Runtime, image, driver, and training framework versions are traceable.
- [ ] Logs can be aggregated and searched by Job and Rank.
- [ ] MLflow Runs, Kubernetes Job UIDs, and model artifacts can be cross-referenced.
- [ ] Task time limits, quotas, priorities, and cleanup policies are defined.

For the principles, deployment components, and layer-by-layer troubleshooting of networking, see: [RDMA and AI High-Speed Networks](rdma-networking.md).

When GPU capacity is spread across multiple clusters, prefer letting a complete TrainJob select a target cluster through mechanisms such as MultiKueue, then complete Gang and topology scheduling within that cluster; cross-region synchronous collectives are usually not the default approach. See: [Kubernetes Cross-Cluster and Large-Scale GPU](cluster/multi-cluster-ai.md).
