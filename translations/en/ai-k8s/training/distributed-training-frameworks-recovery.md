---
title: "Multi-Node Multi-GPU Training Frameworks and Fault Recovery: From DDP, FSDP to DeepSpeed, Megatron, and Ray"
description: "Compare the parallelism capabilities, checkpoint and elasticity boundaries of mainstream multi-node multi-GPU training frameworks, and provide a Kubernetes recovery architecture after node failure, RPO/RTO, drill methods, and a production checklist"
status: stable
last_reviewed: 2026-09-17
---

# Multi-Node Multi-GPU Training Frameworks and Fault Recovery: From DDP, FSDP to DeepSpeed, Megatron, and Ray

Multi-node multi-GPU training splits a single training run into many interdependent processes. Each process typically corresponds to one Rank, and Ranks synchronize gradients, parameters, or activations via NCCL, Gloo, MPI, or XLA Collectives. This brings larger model capacity and higher throughput, but it also amplifies a single-node failure into a failure of the entire training group.

Here is the most important conclusion of this article first: **After a single machine goes offline in synchronous training, the default recovery unit is usually the entire Worker Group, not a one-for-one replacement of the failed Rank.** The original Collective communication group is already invalid; even if healthy Ranks are still alive, they may be stuck on All-Reduce, All-Gather, or Send/Recv. Production recovery generally requires terminating the old process group, excluding the failed node, re-acquiring the full set of resources, establishing a new World, and then resuming from the most recent complete Checkpoint.

So-called training fault tolerance requires at least four layers of capability working together:

1. The training framework can save and restore complete state;
2. The Launcher can detect Rank failure and restart the process group;
3. The scheduler and controller can re-acquire a complete set of suitable GPUs;
4. The Checkpoint resides outside the failed node and can be proven fully readable.

![Four-layer technology stack for multi-node multi-GPU training](/assets/training/distributed-training-recovery/training-stack.png)

## 1. First Distinguish "Framework" from "Platform"

The industry often refers to DeepSpeed, Ray, Kubeflow Trainer, and Kueue all as training frameworks, but their actual responsibilities are completely different.

| Layer | Representative Projects | Primary Responsibilities | What They Do Not Handle |
| --- | --- | --- | --- |
| Algorithm and parallelism runtime | PyTorch DDP/FSDP, DeepSpeed, Megatron Core, JAX/XLA, Colossal-AI, Horovod | Forward/backward computation, parameter sharding, Collectives, mixed precision, parallelism strategies | Cluster quotas, failed node repair |
| Ease-of-use wrappers | Hugging Face Accelerate, Transformers Trainer, Lightning Fabric | Provide a unified interface to DDP, FSDP, DeepSpeed, and other backends | Replacing underlying communication and Checkpoint semantics |
| Distributed execution and launch | `torchrun`, Ray Train, MPI Launcher | Establish Worker Group, Rank/World Size, Rendezvous, process restart | Automatically guaranteeing training state integrity |
| Kubernetes training controllers | Kubeflow Trainer, JobSet, KubeRay, Volcano Job | Create Leader/Worker, observe status, execute failure policies | Deciding how the model is sharded |
| Queueing and scheduling | Kueue, Volcano, Slurm, KAI Scheduler | Quotas, priority, Gang, topology, and preemption | Saving optimizer and data cursor state |
| State and artifacts | PyTorch DCP, Megatron Distributed Checkpoint, DeepSpeed Checkpoint, Orbax, object storage | Saving model, optimizer, and training progress | Automatically determining whether a node is healthy |

When choosing a framework, these layers must be combined. Configuring only the Kubernetes `restartPolicy: OnFailure` can at most restart a container; it does not know that other Ranks have lost synchronization, nor does it know which training Step a new process should resume from.

## 2. Mainstream Multi-Node Multi-GPU Training Frameworks

### 2.1 PyTorch DDP and torchrun: The Default Baseline

DistributedDataParallel (DDP) keeps a full copy of the model on each Rank and synchronizes gradients via Collectives. Its concepts are clear and its ecosystem is mature, making it suitable for models that fit into a single GPU's memory, or that can still fit into a single GPU after techniques such as LoRA or Activation Checkpointing.

`torchrun` is responsible for launching and monitoring processes. Elastic mode can re-establish the Worker Group after process failure or membership changes and re-execute the training entry point; the training script must still load the Checkpoint at the entry point. PyTorch's official fault tolerance tutorial also explicitly states that after a failure, all processes are restarted and training resumes from the most recent Snapshot.

**Suitable for:** General CV/NLP, multi-node data parallelism, teams that want to stay with native PyTorch.

**Recovery focus:** Save model, Optimizer, Scheduler, GradScaler, Step, Sampler, and random state; have all Ranks restart from the same logical Step.

Reference: [Fault-tolerant Distributed Training with torchrun](https://docs.pytorch.org/tutorials/beginner/ddp_series_fault_tolerance.html)

### 2.2 PyTorch FSDP + DCP: Native Parameter Sharding

Fully Sharded Data Parallel (FSDP) further shards parameters, gradients, and optimizer states across multiple Ranks, reducing per-GPU memory usage. It is suitable for scenarios where the model cannot be kept as a full copy on each GPU, and is an important route for native PyTorch large-model training.

Fault recovery should not have Rank 0 aggregate a huge complete State Dict and then save it. PyTorch Distributed Checkpoint (DCP) supports multiple Ranks saving Shards in parallel and can re-shard during loading. This reduces single-point memory and I/O pressure and leaves room for World Size adjustments.

**Suitable for:** Teams that want to stay on the native PyTorch stack, need fully sharded training, and are willing to manage the training loop and parallelism strategy themselves.

**Recovery focus:** Use Sharded State Dict/DCP; before recovery, initialize the model according to the new topology, then let DCP map the global state to the new Shards.

Reference: [PyTorch Distributed Checkpoint](https://docs.pytorch.org/docs/main/distributed.checkpoint.html), [FSDP](https://docs.pytorch.org/docs/main/fsdp.html)

### 2.3 DeepSpeed: ZeRO and 3D Parallelism

DeepSpeed's most widely used capability is ZeRO, which shards optimizer states, gradients, and parameters at different Stages, and can combine Tensor Parallel, Pipeline Parallel, and CPU/NVMe Offload. It suits teams that want to make fewer changes to Hugging Face/PyTorch code while gaining large-model memory optimization.

Ordinary ZeRO Checkpoints are tied to the sharding layout at save time. DeepSpeed Universal Checkpoint uses a unified format to solve recovery across different DP, TP, and PP configurations, but the official documentation still marks the relevant capabilities as an evolving feature; before adoption, validate it against the target model, optimizer, and parallelism combination. The old elastic checkpoint option in ZeRO-3 is no longer supported, and the official recommendation is to move to Universal Checkpoint.

**Suitable for:** Hugging Face ecosystem, ZeRO, Offload, and medium-to-large model training.

**Recovery focus:** All Ranks participate jointly in `save_checkpoint`; do not save only Rank 0; before cross-parallelism recovery, validate Universal conversion and optimizer state compatibility.

Reference: [DeepSpeed Model Checkpointing](https://deepspeed.readthedocs.io/en/stable/model-checkpointing.html), [Universal Checkpointing](https://www.deepspeed.ai/tutorials/universal-checkpointing/)

### 2.4 Megatron Core / NeMo: Large-Scale Transformer Parallelism

Megatron Core targets large-scale Transformers, with system-level implementations of Tensor, Pipeline, Context, Expert, and Data Parallelism, often combined with NeMo, Transformer Engine, and the NVIDIA Resiliency Extension. It is closer to a large-model pretraining foundation than a simple Trainer wrapper.

Megatron Distributed Checkpoint allows multiple Ranks to save shards in parallel and supports loading across different parallelism configurations. Optimizer Checkpoints also distinguish between the performance-oriented `dp_reshardable` and the `fully_reshardable` that can recover across more model-parallel dimensions; the two cannot be swapped based on name alone. Asynchronous saving, partial Checkpoints, cross-node replication, and Hang/Straggler detection can further reduce recovery cost, but some automatic fault tolerance capabilities are tied to Slurm or specific NVIDIA components, and the boundaries must be verified item by item before deployment to Kubernetes.

**Suitable for:** Transformer/MoE pretraining on tens to thousands of GPUs, teams with a clear parallel topology and performance engineering capability.

**Recovery focus:** Save parallel topology and optimizer format; distinguish fast local Checkpoints from persistent Checkpoints; validate compatibility of old optimizer states when upgrading Megatron Core.

Reference: [Megatron Core Distributed Checkpoint](https://docs.nvidia.com/megatron-core/developer-guide/latest/api-guide/core/dist_checkpointing.html), [Megatron Bridge Resiliency](https://docs.nvidia.com/nemo/megatron-bridge/latest/training/resiliency.html)

### 2.5 JAX/XLA + Orbax: The Array-Sharding Route for Multiple Hosts

JAX uses XLA and global array Sharding to describe device layouts, making it suitable for GPU, TPU, and large-scale SPMD training. Multi-host environments require each process to load the correct data Shard; data placed on the wrong device may not always produce an immediate error, yet it can silently corrupt training results.

Orbax is the Checkpoint component of the JAX ecosystem, supporting multi-process, asynchronous saving, atomicity options, retention policies, and topology-independent loading. All Hosts must participate in saving and recovery according to the protocol; it cannot be treated as an ordinary serialization tool where only the main process writes files.

**Suitable for:** JAX/Flax, TPU, teams centered on XLA/SPMD.

**Recovery focus:** Save the complete PyTree and Sharding metadata; validate multi-host barriers, temporary directory cleanup, preemption notifications, and new-topology recovery.

Reference: [JAX Distributed Data Loading](https://docs.jax.dev/en/latest/501/data-loading.html), [Orbax CheckpointManager](https://orbax.readthedocs.io/en/latest/api_reference/checkpoint.checkpoint_manager.html)

### 2.6 Hugging Face Accelerate: A Unified Entry Point, Not a New Communication Framework

Accelerate can switch between DDP, FSDP, DeepSpeed, and other backends with a relatively unified configuration, and provides `save_state`/`load_state` to save the model, optimizer, Scaler, random state, and registered objects. It lowers the barrier to entry, but the final sharding, Collectives, and topology compatibility still depend on the underlying backend.

The official documentation reminds that `save_state` is more suitable for resuming within the same training environment. When recovery requires crossing World Size, backends, or model code versions, one cannot assume usability merely because files exist in the directory.

**Suitable for:** Hugging Face Trainer, custom PyTorch scripts, teams that need to keep similar code across multiple backends.

Reference: [Accelerate Accelerator API](https://huggingface.co/docs/accelerate/main/package_reference/accelerator), [Accelerate FSDP Checkpoint](https://huggingface.co/docs/accelerate/main/usage_guides/fsdp)

### 2.7 Colossal-AI: Booster and Heterogeneous Parallelism

Colossal-AI provides Booster, hybrid parallelism, Gemini/ZeRO-class memory management, and sharded Checkpoints. Booster can save the model, optimizer, and LR Scheduler separately, and also supports Shard and asynchronous saving. It suits teams willing to adopt its training abstractions and validate compatibility against target models.

Its community size, model recipes, version compatibility matrix, and large-scale production cases are fewer than those of the native PyTorch, DeepSpeed, and Megatron routes. When selecting, "the sample runs" and "fault recovery passes at the target scale" should be accepted as separate acceptance criteria.

Reference: [Colossal-AI Booster Checkpoint](https://colossalai.org/docs/basics/booster_checkpoint/)

### 2.8 Horovod Elastic: Mature All-Reduce and Membership Changes

Horovod was once the mainstream solution for general-purpose All-Reduce in TensorFlow/PyTorch. Elastic Horovod can synchronize state when Workers are added or removed, and saves in-memory consistency points via `state.commit()`. It suits teams with existing Horovod code, Spot/elastic Workers, and workloads that do not require complex model parallelism.

In-memory Commit solves fast rollback among currently alive Workers; it cannot replace remote persistent Checkpoints. When the entire job or storage node disappears, recovery still requires restoring from external storage. Worker count changes also alter global Batch, data partitioning, and learning rate semantics.

Reference: [Elastic Horovod](https://horovod.readthedocs.io/en/latest/elastic_include.html)

### 2.9 Ray Train: A Training Orchestration Layer, Not a Training Kernel

Ray Train can launch PyTorch, TensorFlow, and other Worker Groups, coordinating resources, Checkpoints, and retries. After a Worker or node failure, Ray Train typically stops the entire Worker Group, waits for resources, and then provides the latest Checkpoint to new Workers. Whether retry is enabled by default and the API semantics vary with the Ray Train version; the current Train V2 configures failure and preemption retries via `FailureConfig`.

Ray's value lies in bringing data processing, training, Tune, batch inference, and post-training Actors into a unified Python distributed runtime. If fixed-topology large-scale pretraining is already stably carried by `torchrun`, Megatron Launcher, Kubeflow Trainer, or Slurm, there is no need to introduce Ray solely for "elasticity."

Reference: [Ray Train Failure Handling](https://docs.ray.io/en/latest/train/user-guides/fault-tolerance.html), [Ray Train Checkpoints](https://docs.ray.io/en/latest/train/user-guides/checkpoints.html)

## 3. How to Choose

| Scenario | Priority Evaluation | Reason | Additional Verification Needed |
| --- | --- | --- | --- |
| Model fits on a single GPU, scaling primarily by throughput | DDP + torchrun | Simple, stable, complete ecosystem | Snapshot and data cursor |
| Model requires full parameter sharding | FSDP + DCP | PyTorch native, supports parallel save and resharding | Target model operators, DCP backend, and recovery time |
| Hugging Face + large model GPU memory optimization | Accelerate + DeepSpeed/FSDP | Minimal code changes, many Recipes | The underlying Checkpoint is the real boundary |
| Large-scale Transformer/MoE pretraining | Megatron Core/NeMo | Complete parallel dimensions and Kernel optimizations | Version matrix, topology, optimizer state compatibility |
| JAX/TPU/SPMD | JAX/XLA + Orbax | Global array Sharding and multi-Host capability | Data shard, Barrier, and storage atomicity |
| Dynamic Python workflows, Tune, post-training | Ray Train + PyTorch/DeepSpeed | Flexible execution and resource orchestration | Head/Driver, Worker, Checkpoint layered fault tolerance |
| Existing general All-Reduce projects | Horovod Elastic | Cross-framework, mature membership change semantics | Global batch, data repartitioning, durable recovery |
| Want to try another set of hybrid parallelism abstractions | Colossal-AI | Rich Booster and memory optimization capabilities | Community maturity at target scale and disaster recovery |

No framework can replace real failure drills. The most important selection evidence is not the official support list, but the recovery results under the target model, target parallelism, target storage, and target scheduler.

## 4. What Machine Failures Actually Break

| Failure | Common Symptom | Automatic Action | Should the Node Be Replaced |
| --- | --- | --- | --- |
| Single training process exits | A Rank throws an exception, other Ranks hit Collective timeout | Terminate and rebuild Worker Group | Depends on error cause |
| GPU XID / ECC | CUDA/NCCL exception, GPU may no longer be usable | Isolate GPU or node, limit automatic retries | Usually yes |
| Node down or NotReady | Multiple Ranks disappear simultaneously | Release old Gang, re-queue | Yes |
| RDMA/NIC/switch network anomaly | NCCL Hang, throughput drop, retries | Timeout abort, collect communication diagnostics | Conditional |
| Spot/preemption | Termination signal received or Pod Evicted | Attempt to save, then full recovery | Yes |
| Local disk failure | Latest local Checkpoint lost | Fall back to remote durable version | Yes |
| Shared storage timeout | Save hangs or only writes partial Shards | Invalidate this Checkpoint | Not necessarily |
| OOM, data corruption, code exception | Fails at the same step every time | Fail fast and preserve evidence | No, fix config/data first |
| Loss NaN/Inf | Process may still be running | Stop automatic retries, roll back and analyze | Depends on hardware evidence |

Infrastructure failures warrant limited retries; deterministic user code errors should not consume more GPU time for repeated execution. An NCCL timeout can originate from a machine failure, or from a Rank that OOM'd first or stalled reading data, so prioritize locating the first failed Rank rather than only looking at the last communication timeout.

## 5. What State a Checkpoint Must Save

"Saving model weights" is only enough for inference or fine-tuning again; it does not mean precise training resumption. A complete training Checkpoint must include at least:

- Model parameters and Buffers;
- Optimizer state, e.g., Adam first and second moments;
- LR Scheduler, GradScaler, and gradient accumulation position;
- Global Step, tokens processed, Epoch;
- Python, NumPy, CPU/GPU RNG state;
- DataLoader/Sampler state, data Shard, and consumption Watermark;
- Parallel topology metadata for DP, TP, PP, CP, EP, etc.;
- Dataset Snapshot, Tokenizer, training config, code Commit, and image Digest;
- Checkpoint format version, Shard manifest, size, and checksums.

Without the Optimizer, the recovered Loss trajectory may change; without the data cursor, samples will be repeated or skipped; without RNG, Dropout and sampling cannot be reproduced; without topology metadata, even if all shard files are present, they may not load into a new World.

## 6. A Recoverable Save Protocol

Large model Checkpoints are often written out in parallel by multiple Ranks. If a single Shard is missing, the entire Checkpoint may be invalid. The following publication protocol is recommended:

1. Create a unique temporary directory for this Step, e.g., `step-12000.tmp-<run-id>`;
2. Each Rank writes its own model, optimizer, and additional state;
3. Wait for all Ranks to complete and aggregate file sizes, checksums, and format versions;
4. Write the Manifest and perform a loadability check;
5. Atomically publish the completion flag or rename the directory to the official version;
6. Finally update the `latest` pointer;
7. When cleaning up old versions, keep at least the most recent version, the previous verified version, and periodic milestones.

The recovery program may only select versions that have been published and verified; it must not guess "latest" by taking the maximum directory name. Asynchronous saves must also distinguish between "the training thread has returned" and "the remote data has been persisted"; if a failure occurs between the two, this Checkpoint may still be unusable.

## 7. Layered Checkpoint Architecture

A single storage tier can rarely satisfy both speed and reliability simultaneously. Production training commonly uses a two- or three-tier structure:

- **Node-local NVMe**: high frequency, low latency, but may disappear if the node is lost;
- **Cross-node replicated local Checkpoints**: copies kept on neighboring nodes, covering single-node failures;
- **Object storage or reliable shared storage**: low-frequency durable versions, covering the entire Worker Group or datacenter-level failures.

![Checkpoint recovery path after training failure](/assets/training/distributed-training-recovery/failure-recovery.png)

Local saves must not simply copy within the same failure domain. For example, if the same chassis, same power domain, or same rack fails simultaneously, local copies may disappear together. Object storage paths must also isolate different Runs; two training jobs must not write `latest` to the same directory concurrently.

## 8. Where Checkpoints Actually Live

Storage choice determines save duration and which failure level can be covered. First choose the medium based on recovery objectives, then optimize speed.

| Storage | Multi-Node Access | Performance Characteristics | Failures Covered | Suitable Use |
| --- | --- | --- | --- | --- |
| Pod `emptyDir` / node NVMe | By default only on this node | Lowest latency, highest bandwidth | Process or container restart; lost on node damage | High-frequency temporary versions, staging for async saves |
| HostPath / Local PV | Bound to node | Close to local disk | Pod recreation; cannot cover node failure | Local fast recovery in controlled environments |
| Block storage PVC (RWO/RWOP) | Usually mounted by a single node | Stable latency, throughput depends on volume spec | Can be remounted after node replacement | Single-node training, per-Worker independent volumes |
| RWX file system | Mounted by multiple nodes simultaneously | Convenient, susceptible to metadata and small-file overhead | Worker or node failure | Multi-Rank shard direct save, short-term shared staging |
| Parallel file system | Multi-node concurrent access | High bandwidth, requires striping and metadata planning | Node and Worker Group failures | Large-scale synchronous/asynchronous sharded Checkpoints |
| Object storage | Accessed via API | Good throughput scaling, no POSIX directory semantics | Entire training group, node pool, or even cluster failure | Durable recovery points, archival, and cross-cluster recovery |

Kubernetes AccessMode must not be taken for granted: `ReadWriteOnce` means single-node read/write, but multiple Pods on the same node may still access it concurrently; when strict single-Pod restriction is required, evaluate CSI-supported `ReadWriteOncePod`. If multi-machine training has all Ranks writing to the same path, RWX, a parallel file system, or an object storage backend that supports distributed writes is typically required. Reference: [Kubernetes Persistent Volumes](https://kubernetes.io/docs/concepts/storage/persistent-volumes/)

![Layered storage and publication path for Checkpoints](/assets/training/distributed-training-recovery/checkpoint-storage.png)

### Three Common Deployment Approaches

**Small/medium DDP:** Rank 0 writes common state such as model and optimizer to RWX/PVC; each Rank additionally saves its own RNG and data consumption state; after a successful save, publish the completion flag. Simple to implement, suitable as the first reliable path.

**FSDP/ZeRO/Megatron:** All Ranks write shards in parallel to RWX or a parallel file system; the coordinating Rank publishes the Manifest after all shards complete. A separate upload process then copies the complete directory to object storage. This way the training process does not directly bear remote small-file and retry logic.

**Ultra-large-scale training:** Each Rank writes to local disk at high frequency, replicating copies to another node by failure domain; a durable object storage version is generated at longer intervals. On recovery, first try the local copy within the same Worker Group, then the cross-node copy, and finally fall back to the remote version.

## 9. Directories, Manifest, and Atomic Publication

Checkpoint paths should be isolated by Run and Attempt; once a Step directory is published, it is never overwritten:

```text
checkpoints/
└── team-a/model-x/run-20260917-001/
    ├── run.json
    ├── steps/
    │   ├── step-000012000/
    │   │   ├── model/
    │   │   │   ├── __0_0.distcp
    │   │   │   └── __1_0.distcp
    │   │   ├── rank-state/rank-00000.pt
    │   │   ├── manifest.json
    │   │   └── COMMITTED
    │   └── step-000012500.tmp-attempt-03/
    ├── latest.json
    └── attempts/attempt-03.json
```

`manifest.json` should record at least the following:

```json
{
  "schema_version": 1,
  "run_id": "run-20260917-001",
  "step": 12000,
  "world_size": 32,
  "parallelism": {"dp": 4, "tp": 4, "pp": 2, "ep": 1},
  "framework": {"name": "pytorch", "version": "<exact-version>"},
  "image_digest": "sha256:<digest>",
  "code_commit": "<git-commit>",
  "dataset_snapshot": "<immutable-dataset-version>",
  "files": [
    {"path": "model/__0_0.distcp", "bytes": 123456, "sha256": "<checksum>"}
  ],
  "created_at": "2026-09-17T12:00:00Z"
}
```

On a POSIX file system, all content can be written to a temporary directory in the same file system; after closing files and completing a Barrier, publish the official directory with an atomic `rename`. Do not simulate directory renames in object storage: object Keys are essentially independent objects, and copy-then-delete is both slow and non-transactional. A more robust sequence is:

1. Upload immutable shards with unique Run/Step keys;
2. Verify size and independent SHA-256 or similar checksums for each object;
3. Upload `manifest.json`;
4. Finally write a very small `COMMITTED` object;
5. Use a versioned or conditional-write `latest.json` to point to that Step;
6. The recovery side only accepts directories where `COMMITTED` exists and the Manifest passes verification.

`latest.json` is only an accelerator for lookups, not the source of truth. If it is corrupted or points to an invalid version, the recoverer should scan Steps in descending order and fall back to the previous version that passed verification.

The ETag in object storage is not necessarily equal to the content MD5 under multipart upload, encryption, and different implementations, and should not be treated as a general-purpose content checksum. It is recommended to enable Bucket Versioning or equivalent capability to protect `latest.json` and the Manifest, and to grant the training identity least privilege: the training job can only write its own Run prefix, the recovery job only reads the specified prefix, and GC uses a separate identity. Static encryption, transport encryption, access auditing, and cross-failure-domain replicas should also be part of the storage baseline.

### Capacity Estimation

Using Adam-class optimizers and BF16 parameters as an example, a rough calculation of one complete training state:

```text
BF16 模型参数       2 byte / parameter
FP32 Master Weight  4 byte / parameter
Adam 一阶、二阶矩   8 byte / parameter
合计约             14 byte / parameter
```

If BF16 gradients are also saved, this approaches 16 byte/parameter; shard indices, alignment, extra Buffers, and version differences add more space. A 70B model at 14 byte/parameter is roughly 980 GB, and keeping 3 complete versions approaches 3 TB. For production capacity, use the measured single-version size multiplied by the retention count, then add 20%–30% headroom for temporary writes, retries, and fragmentation.

Not every Checkpoint needs to be retained forever. A common policy is to keep the most recent 3–5 verified versions, one version per day, and each milestone or best-evaluation version; GC first marks objects for deletion, then confirms no active recovery job references them, and finally deletes the objects and Manifest.

## 10. Recoverable Save Practices for DDP

In ordinary DDP, model and optimizer state are typically consistent across Ranks; common state can be saved by Rank 0; RNG, Sampler, and data Watermark are Rank-local state and must be saved per Rank. The core structure on a shared POSIX file system is shown below; exception handling and metric reporting can be supplemented per platform:

```python
import hashlib
import json
import os
import random
from pathlib import Path

import numpy as np
import torch
import torch.distributed as dist


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def save_ddp_checkpoint(root, step, attempt_id, model, optimizer, scheduler, scaler, data_state):
    rank = dist.get_rank()
    world = dist.get_world_size()
    tmp = Path(root) / f"step-{step:012d}.tmp-{attempt_id}"
    final = Path(root) / f"step-{step:012d}"

    if rank == 0:
        tmp.mkdir(parents=True, exist_ok=False)
        (tmp / "rank-state").mkdir()
    dist.barrier()

    # 每个 Rank 都保存自身的随机数和数据消费位置。
    torch.save(
        {
            "rank": rank,
            "torch_rng": torch.get_rng_state(),
            "cuda_rng": torch.cuda.get_rng_state_all(),
            "numpy_rng": np.random.get_state(),
            "python_rng": random.getstate(),
            "data_state": data_state,
        },
        tmp / "rank-state" / f"rank-{rank:05d}.pt",
    )

    if rank == 0:
        module = model.module if hasattr(model, "module") else model
        torch.save(
            {
                "step": step,
                "model": module.state_dict(),
                "optimizer": optimizer.state_dict(),
                "scheduler": scheduler.state_dict(),
                "scaler": scaler.state_dict() if scaler else None,
            },
            tmp / "training.pt",
        )
    dist.barrier()

    if rank == 0:
        files = sorted(path for path in tmp.rglob("*") if path.is_file())
        manifest = {
            "step": step,
            "world_size": world,
            "files": [
                {
                    "path": str(path.relative_to(tmp)),
                    "bytes": path.stat().st_size,
                    "sha256": sha256(path),
                }
                for path in files
            ],
        }
        (tmp / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (tmp / "COMMITTED").write_text("ok\n", encoding="utf-8")
        if final.exists():
            raise FileExistsError(f"immutable checkpoint already exists: {final}")
        os.rename(tmp, final)  # 临时目录与正式目录必须位于同一文件系统。
    dist.barrier()
```

Actual recovery proceeds in the following order:

1. Rank 0 finds the latest `COMMITTED` directory and verifies the Manifest;
2. Broadcast the selected path to all Ranks;
3. All Ranks load common state, and each loads its corresponding `rank-state`;
4. Restore Optimizer, Scheduler, Scaler, RNG, and data cursor;
5. After a Barrier, run a short validation Step, then enter formal training.

```python
def restore_ddp_checkpoint(path, model, optimizer, scheduler, scaler):
    rank = dist.get_rank()
    common = torch.load(Path(path) / "training.pt", map_location="cpu", weights_only=False)
    local = torch.load(
        Path(path) / "rank-state" / f"rank-{rank:05d}.pt",
        map_location="cpu",
        weights_only=False,
    )

    module = model.module if hasattr(model, "module") else model
    module.load_state_dict(common["model"])
    optimizer.load_state_dict(common["optimizer"])
    scheduler.load_state_dict(common["scheduler"])
    if scaler and common["scaler"] is not None:
        scaler.load_state_dict(common["scaler"])

    torch.set_rng_state(local["torch_rng"])
    torch.cuda.set_rng_state_all(local["cuda_rng"])
    np.random.set_state(local["numpy_rng"])
    random.setstate(local["python_rng"])
    dist.barrier()
    return common["step"], local["data_state"]
```

This code is suitable for explaining correct boundaries and should not be used directly for TB-scale models without stress testing. Also evaluate `weights_only`, serialization format, file and parent directory `fsync`, exception broadcasting, and safe loading strategies based on the actual PyTorch version. The `weights_only=False` in the example may only be used for trusted, self-owned, access-controlled training state; do not load Pickle Checkpoints of unknown origin. If the World Size changes, the old Ranks' RNG and data state cannot be mechanically applied by index; redefine data partitioning and use a Checkpoint format that supports resharding.

### The Data Cursor Matters More Than Epoch

Saving only `epoch=3` cannot indicate which data has been consumed. Data state must at least answer: dataset version, Shard, sample or Token Watermark, offset within the current Epoch, Shuffle Seed, and which Microbatch gradient accumulation has reached. When precise resumption is not possible, explicitly choose "replay from the beginning of this Epoch" and include the number of duplicated samples in the RPO.

## 11. FSDP and PyTorch DCP Practices

FSDP is not suitable for first aggregating all shards to Rank 0 and then `torch.save`. DCP can save in parallel across Ranks and reshard on load according to the already-initialized new model layout:

```python
import torch.distributed.checkpoint as dcp
from torch.distributed.checkpoint.state_dict import get_state_dict, set_state_dict


def save_fsdp_checkpoint(path, model, optimizer):
    model_state, optim_state = get_state_dict(model, optimizer)
    dcp.save(
        {"model": model_state, "optimizer": optim_state},
        checkpoint_id=path,
    )


def load_fsdp_checkpoint(path, model, optimizer):
    # 模型和优化器必须先按新的 DeviceMesh / World Size 初始化。
    model_state, optim_state = get_state_dict(model, optimizer)
    state = {"model": model_state, "optimizer": optim_state}
    dcp.load(state, checkpoint_id=path)
    set_state_dict(
        model,
        optimizer,
        model_state_dict=state["model"],
        optim_state_dict=state["optimizer"],
    )
```

Step, Scheduler, RNG, and data cursor still need to be saved as application state; they cannot be omitted just because DCP successfully wrote the model shards. The DCP file system Writer assumes the target directory is empty or nonexistent and relies on file creation semantics; storage backend, framework version, and cross-topology loading must all be verified against the target environment. [PyTorch DCP](https://docs.pytorch.org/docs/main/distributed.checkpoint.html) currently also provides `async_save`, but `COMMITTED` may only be published after the background upload has truly completed; "data has been staged to CPU" must not be treated as remote persistence complete.

DeepSpeed's `save_checkpoint` must be called by all Ranks, and Megatron Distributed Checkpoint also requires full-group participation. Framework-provided `latest`, Tracker, or Metadata files can be part of the internal implementation, but the platform layer should still record Run, Attempt, object manifest, and completion status, so that recovery evidence is not lost after framework upgrades.

The basic DeepSpeed invocation is as follows; `client_state` is used to save the training loop's own Step, data position, and configuration summary:

```python
tag = f"step-{global_step:012d}"
engine.save_checkpoint(
    checkpoint_root,
    tag=tag,
    client_state={"global_step": global_step, "data_state": data_state},
)

load_path, client_state = engine.load_checkpoint(checkpoint_root, tag=tag)
if load_path is None:
    raise RuntimeError(f"failed to restore {tag}")
```

All ranks must enter the save call, otherwise the process will hang at the synchronization point. Under ZeRO-3, do not assume that an Engine that has already been sharded and continues training can be unconditionally reloaded in place; verify the recovery flow after re-initializing the Engine against the target DeepSpeed version. Reference: [DeepSpeed Model Checkpointing](https://deepspeed.readthedocs.io/en/stable/model-checkpointing.html)

## 12. Storage and Recovery Practices on Kubernetes

The mounting approach below expresses a common combination: local disks handle fast staging, an RWX PVC holds short-lived shared recovery points, and an uploader then syncs already-committed versions to object storage.

```yaml
spec:
  template:
    spec:
      terminationGracePeriodSeconds: 180
      containers:
        - name: trainer
          env:
            - name: LOCAL_CHECKPOINT_DIR
              value: /checkpoint/local
            - name: SHARED_CHECKPOINT_DIR
              value: /checkpoint/shared
          volumeMounts:
            - name: checkpoint-local
              mountPath: /checkpoint/local
            - name: checkpoint-shared
              mountPath: /checkpoint/shared
      volumes:
        - name: checkpoint-local
          emptyDir: {}
        - name: checkpoint-shared
          persistentVolumeClaim:
            claimName: training-checkpoint-rwx
```

Uploading to object storage is best handled by a separate process, and it should only process Steps that contain `COMMITTED`. It can be a Sidecar in the same Pod, a standalone Deployment, or a short-lived Job created per version:

- A Sidecar has low latency, but it disappears together with the training Pod when the Pod is force-deleted;
- A standalone uploader does not share the life cycle of the training container, making it more suitable for reliable transfer;
- Using the framework's object storage Writer directly reduces intermediate layers, but multi-rank coordination, rate limiting, retry, and consistency semantics must be verified.

When a recovery Pod starts, an Init Container can download the selected version to a local cache and the Trainer then loads it in parallel; alternatively, it can read directly from the shared file system. Either way, do not blindly pick the directory with the largest path name in the Init Container; instead, run the same Manifest checksum and fallback logic.

CSI VolumeSnapshot can protect an entire volume, but by default it only means that storage blocks were captured at a certain point in time; it does not automatically guarantee that application state across multiple ranks is consistent. If a Snapshot is to be used as a recovery point, the training processes must first complete a Barrier, flush files, and publish a Manifest before the Snapshot is triggered; otherwise, it can only serve as disaster recovery material and cannot directly promise precise training resumption.

### A Recovery Runbook

1. Confirm that the old Worker Group has fully exited and no residual Rank is still writing to the same Run;
2. Decide whether to isolate the original node based on XID, Node status, RDMA, and storage logs;
3. Validate starting from `latest.json`; on failure, fall back to the last committed version;
4. Establish a new Worker Group that satisfies the topology requirements;
5. First initialize the model, Optimizer, parallel groups, and target Sharding;
6. Load the model and optimizer, then load the Scheduler, Scaler, RNG, and data state;
7. Verify the recovery Step, World Size, global Batch, and Dataset Snapshot;
8. Run 5–20 observation Steps and confirm that Loss, gradient norm, throughput, and Collective operations are normal;
9. Record lost Steps, download/load time, queueing time, and final RTO;
10. Only after the new Checkpoint is successfully committed may GC clean up versions from before the failure.

### Which Metrics to Monitor

| Metric | Purpose |
| --- | --- |
| `checkpoint_last_success_timestamp_seconds` | Determine how long it has been since the last valid recovery point |
| `checkpoint_save_duration_seconds` | Observe save P50/P95/P99 and I/O degradation |
| `checkpoint_bytes_total` | Estimate throughput, capacity, and abnormal small files |
| `checkpoint_save_failures_total` | Detect write, validation, or publish failures |
| `checkpoint_validation_failures_total` | Detect missing Shards, Checksum errors, or format errors |
| `checkpoint_fallback_total` | Count fallbacks caused by the latest version being unavailable |
| `training_recovery_duration_seconds` | Measure end-to-end RTO |
| `training_recovery_lost_steps` | Measure actual RPO |

Alert thresholds should not only look at save failures. Even without errors, if `time() - checkpoint_last_success_timestamp_seconds` exceeds twice the planned interval, it means the expected recovery capability has already been lost. Asynchronous saves should also monitor queue depth and the number of uncommitted versions, to prevent background I/O from accumulating and eventually exhausting host memory or local disk.

If the planned interval is exposed as seconds via a Label, the PromQL idea below can be used as a starting point, then adjusted according to metric labels:

```promql
time() - max by (run_id) (checkpoint_last_success_timestamp_seconds)
  > 2 * max by (run_id) (checkpoint_planned_interval_seconds)
```

### Recovery Acceptance Cannot Only Check That the Process Is Running Again

At minimum, verify the following evidence:

- The first Step after recovery equals the value recorded in the Manifest, not zero;
- Optimizer State is non-empty and LR is the same as before recovery;
- Dataset Snapshot, Sampler Watermark, and processed Token count are correct;
- Within the agreed window, Loss and gradient norm show no abnormal jumps;
- All ranks have the same Step, with no rank running ahead;
- The first Checkpoint written by the new Attempt can be independently recovered again;
- Compared with the failure-free baseline, the final evaluation result is within the predefined tolerance.

## 13. Standard Recovery Process After Node Failure

An automatic recovery can be broken down into eight steps:

1. **Detection**: process exit, NCCL Watchdog, heartbeat, Node NotReady, XID, or preemption notification triggers the failure;
2. **Converge state**: mark this Attempt as failed, stop the old Worker Group, and prevent residual Ranks from continuing to write state;
3. **Preserve evidence**: collect the first abnormal Rank, all Rank exit codes, GPU XID, dmesg, NCCL/RDMA, Pod Events, and storage logs;
4. **Classify**: distinguish infrastructure, transient network, capacity, OOM, code, data, and numerical errors;
5. **Isolate**: when there is hardware evidence, add a failure label/taint to the node or GPU so the next attempt is not scheduled back to the same machine;
6. **Re-admit**: re-queue as a full Gang, and only start after GPU model, quantity, RDMA, and topology requirements are satisfied;
7. **Recover**: select the most recent committed and validated Checkpoint, rebuild the World, and load state;
8. **Verify**: confirm that the recovery Step, data Watermark, Loss range, and Collective operations are normal, then mark the Attempt as successfully recovered.

Automation should retain the nodes, Ranks, Checkpoints, error classification, and recovery duration of each Attempt. A final Job Completed status must not overwrite the records of previous failures.

## 14. Recovery with the Same Number of GPUs and Scale-Down Recovery

### Same World Size

This is the easiest path to implement and verify. A new Worker Group that keeps the same DP/TP/PP/EP layout can usually load the original shards directly. For production, at minimum ensure this path is stable first.

### World Size Changes

Elastic recovery may change the data parallel scale, and may even change Tensor/Pipeline/Expert Parallel. In this case, the following must be handled simultaneously:

- Model and optimizer state re-sharding;
- Global Batch Size and gradient accumulation;
- Whether the learning rate is adjusted with World Size;
- Data partitioning, Sampler, and consumed samples;
- Re-mapping of Pipeline Stages and Experts;
- Compilation cache, communication groups, and random state.

| Technology | Cross-topology recovery capability | Production note |
| --- | --- | --- |
| PyTorch DCP | Supports re-sharding at load time; adapts to DDP/FSDP/DTensor and other states | Must be tested with the target version and StorageBackend |
| Megatron Distributed Checkpoint | Can load across multiple parallel configurations | Optimizer formats have different re-shardable boundaries |
| DeepSpeed Universal Checkpoint | Aims to recover across ZeRO/3D parallel configurations | Feature is still evolving; verify the model and optimizer combination first |
| Orbax | Supports multi-host and topology-independent loading | Sharding and Barrier across all processes must be correct |
| Horovod Elastic | Can synchronize in-memory state when membership changes | Also handle Batch, learning rate, and data re-partitioning |
| Accelerate `save_state` | Wraps the underlying backend save | Officially positioned more for resuming in the same environment; for cross-environment, look at the underlying format |

"Being able to start with a different number of GPUs" does not mean "training semantics are unchanged." After scale-down, throughput, global Batch, optimizer update frequency, and data order may all change; the Loss and final evaluation must be compared against the failure-free baseline.

## 15. How to Combine on Kubernetes

### 15.1 Gang Scheduling

Multi-node jobs should start together only after the full resource requirement is satisfied, to avoid some Workers occupying GPUs while waiting for the remaining Ranks. Kubeflow Trainer can integrate with scheduling solutions such as Kueue and Volcano; JobSet and Volcano Job can also express whole-group failure and restart policies.

Kueue is responsible for quotas, priority, admission, and topology; the training controller is responsible for creating Workers; the training framework is responsible for process groups and Checkpoints. The three must not overstep each other's authority.

### 15.2 Whole-Group Restart Policy

JobSet's FailurePolicy can choose `RestartJobSet`, `RestartJob`, or fail directly based on the sub-Job failure reason; for Volcano Job, events such as `PodFailed` and `PodEvicted` can trigger `RestartJob`. Synchronous training usually uses whole-group restart as the safe default.

The following only shows a policy skeleton; fields should be validated against the JobSet API version installed in the cluster:

```yaml
spec:
  failurePolicy:
    maxRestarts: 3
    restartStrategy: Recreate
    rules:
      - name: restart-workers
        action: RestartJobSet
        targetReplicatedJobs: [workers]
        onJobFailureReasons: []
        onJobFailureMessagePatterns: []
```

Reference: [JobSet Failure Policy](https://jobset.sigs.k8s.io/docs/tasks/failure_policy/), [Volcano Job Policy](https://volcano.sh/docs/v1.13.0/userguide/user_guide_how_to_use_job_policy/)

### 15.3 Preemption and Graceful Exit

When a Pod receives SIGTERM, it can trigger an emergency save, but this must not be treated as the only guarantee: preemption notifications can be very short, and the node may also lose power directly. It is recommended to also use periodic persistent Checkpoints, and to have the emergency save exit proactively after a timeout, to avoid occupying a Terminating Pod indefinitely.

### 15.4 Faulty Node Isolation

Before automatic retry, at least check:

- Whether the node has XID, ECC, PCIe, or NVLink errors;
- Whether RDMA NIC, ports, PFC/ECN, and link errors are abnormal;
- Whether the same node has recently caused multiple consecutive training Attempt failures;
- Whether the GPU health check only verifies `nvidia-smi` without verifying GPU memory, P2P, and Collective operations.

Hardware failures should be converted into Labels/Taints by Node Problem Detector, GPU Operator, DCGM, or a dedicated health controller, and then excluded by the scheduler. Training scripts should not modify Nodes themselves.

## 16. RPO, RTO, and Checkpoint Interval

- **RPO**: the maximum amount of training progress that can be lost after a failure. With periodic saves, the upper bound is usually close to the Checkpoint interval; uncommitted portions of asynchronous saves do not count as valid recovery points.
- **RTO**: the time from failure occurrence until training stably produces Steps again.

```text
RTO = 故障检测
    + 旧进程组退出
    + 重新排队与节点准备
    + 镜像/数据准备
    + Checkpoint 下载与重分片
    + 通信组重建
    + 恢复后验证
```

The more frequent the Checkpoints, the fewer training steps are lost, but the higher the I/O, pause, and storage costs. The Young approximation formula can be used as a starting point for the first experiment:

```text
候选间隔 ≈ sqrt(2 × 单次 Checkpoint 耗时 × 平均故障间隔)
```

It is not the final answer. Asynchronous I/O, queueing, partial saves, object storage rate limiting, and large-scale parallelism all change the actual optimal value. Production configuration should be measured through fault injection, not copied from a formula.

It is recommended to continuously record:

- Checkpoint write and load P50/P95/P99;
- Age of committed versions;
- Steps/Tokens lost per failure;
- MTTD, RTO, and recovery success rate;
- Re-queueing duration and bad-node repeat hit rate;
- Step Time, Loss, and data Watermark differences before and after recovery.

## 17. Mandatory Failure Drills

| Drill | Injection method | Pass criteria |
| --- | --- | --- |
| Rank process exit | Kill one Worker process | Entire group exits and recovers within budget, no zombie Ranks |
| Pod eviction | Delete one Worker Pod | Controller rebuilds per whole-group policy, Attempt is traceable |
| Node down | Shut down or isolate kubelet | New Attempt no longer hits the bad node |
| NCCL/RDMA interruption | Block the training network or shut down ports | Hang is detected within timeout, logs can locate the link |
| Latest Checkpoint incomplete | Delete one Shard or the completion flag | Automatically falls back to the last valid version |
| Object storage slowdown | Inject high latency/rate limiting | Async queue has an upper bound, does not consume memory indefinitely |
| Spot preemption | Send termination notification | Emergency save is time-bounded; on failure, recovery still works from periodic versions |
| World Size change | Recover with fewer or more GPUs | Re-sharding succeeds, Batch/LR/data semantics verified |
| Consecutive failures | Inject 3 failures into the same job | Stops and alerts after reaching the retry budget, does not burn GPUs indefinitely |
| Numerical consistency | Run the same number of Steps as the failure-free baseline | Loss trajectory and final evaluation are within the agreed tolerance |

One successful recovery only proves that a viable path exists. Production acceptance should repeat injections at different training stages and cover failures during save, failures right after publication, and failures during load.

### A Minimal Reproducible Experiment

The following closed loop can first be run with a smaller model, then scaled up to formal training:

1. Fix the dataset Snapshot, Seed, World Size, and image; run an uninterrupted baseline;
2. Save every 50 Steps; around Step 135, delete one Worker Pod;
3. Confirm that the other Ranks of the old World exit and the controller leaves no orphan processes occupying GPUs;
4. The new Attempt recovers from the valid version at Step 100, with the data Watermark consistent with the Manifest;
5. Observe at least 20 Steps and compare Loss, gradient norm, and learning rate between the baseline and the recovery path;
6. Wait until Step 150 produces a new valid Checkpoint, restart again, and verify it can be loaded;
7. Create a Step 200 directory that is missing `COMMITTED` or missing one Shard;
8. Confirm that the recoverer rejects Step 200 and automatically falls back to Step 150;
9. Inject three consecutive failures and confirm that the job stops and alerts after exceeding the budget;
10. Summarize lost Steps, Checkpoint duration, re-queueing time, load time, and end-to-end RTO.

In an isolated test namespace, the command below can be used to trigger Pod-level failures. Node power-off, RDMA blocking, and GPU XID drills have a larger blast radius and should use dedicated fault nodes and change windows.

```bash
kubectl delete pod <worker-pod> \
  -n <test-namespace> \
  --grace-period=0 \
  --force
```

The result record should contain at least the following fields, to avoid leaving only a "recovery succeeded" conclusion:

| Field | Example meaning |
| --- | --- |
| Run / Attempt | Distinguish the original training from each restart |
| Failure time and first failed Rank | Determine detection latency and root cause order |
| Failed node, GPU, XID/RDMA evidence | Determine whether the node needs isolation |
| Selected Checkpoint and number of fallbacks | Prove the recoverer chose the right version |
| Save Step / Recovery Step / First new Step | Calculate actual lost progress |
| Scheduling, download, load, validation duration | Break down RTO bottlenecks |
| Loss, LR, data Watermark before and after recovery | Verify training semantics |
| Result of loading the new version again | Avoid a state where recovery only allows continued running but not another recovery |

## 18. Common Anti-Patterns

- Saving only model weights while claiming support for resume training;
- Checkpoint written to HostPath on the failed node, with no remote replica;
- All Ranks directly overwrite the same file;
- Only start writing Shards after updating `latest`;
- Pod restart count treated as equivalent to training recovery count;
- No distinction between XID, OOM, code exceptions, and data errors, all uniformly retried indefinitely;
- After Worker count changes, still reusing the original learning rate and data partitioning without verifying convergence;
- Validating Checkpoint only at the end of training, never actually loading it mid-training;
- Relying on `preStop` to complete multi-TB saves during preemption;
- Keeping only local versions for recovery speed, with no cross-fault-domain replicas;
- After automatic recovery, not verifying Step, data Watermark, or Loss.

## 19. Recommendations by Scale

### 1–8 GPUs

Start with DDP or FSDP. Use `torchrun`, shared/object storage, and full Snapshots, and prioritize getting single-machine and single-node failure recovery working. There is no need to introduce complex 3D parallelism from the start.

### 8–64 GPUs

Choose FSDP or DeepSpeed ZeRO based on model GPU memory; use DCP/sharded Checkpoints to reduce the save bottleneck. On Kubernetes, add Gang, queue, topology scheduling, and full-group restart, and begin measuring RPO/RTO.

### Large-Model Pretraining Above 64 GPUs

Evaluate Megatron Core/NeMo or a well-validated DeepSpeed 3D parallelism setup. Checkpoints need parallel, asynchronous, and tiered saving; training network, storage, and node health enter a unified fault-domain design. At this scale, even a one-minute global pause can correspond to significant GPU cost.

### Spot, Dynamic Resources, and Complex Python Workflows

Ray Train or Horovod Elastic can be evaluated, but first define which parallel dimensions are allowed to change. Model parallel groups typically require fixed topology; the easiest dimension to make elastic is usually only the data parallel replicas. Elasticity should not come at the cost of breaking Batch, data consumption, or convergence.

## 20. Production Checklist

- [ ] Responsibilities of the training framework, Launcher, training controller, queue, and storage are clearly defined;
- [ ] The unit of failure recovery is Rank, Worker Group, or the entire Job, and the behavior has been verified;
- [ ] Checkpoint includes model, optimizer, scheduler, Scaler, RNG, Step, and data cursor;
- [ ] Multi-Rank saving uses Manifest, checksums, and an atomic publication protocol;
- [ ] Step directories are immutable, `latest` serves only as a pointer and can automatically roll back;
- [ ] At least one Checkpoint resides outside the training node fault domain;
- [ ] Single-version size, save bandwidth, load bandwidth, capacity margin, and GC policy have been measured;
- [ ] Object storage has version protection, least privilege, encryption, and access audit configured;
- [ ] Same-World-Size recovery has become a hard launch gate;
- [ ] Cross-World-Size recovery has been separately verified for resharding, Batch, LR, and data semantics;
- [ ] Gang Scheduling does not let some Workers occupy GPUs for extended periods;
- [ ] XID/RDMA/node failures can be automatically isolated, and user errors do not trigger infinite retries;
- [ ] Preemption, force kill, node crash, network interruption, and bad Checkpoints have all been drilled;
- [ ] MTTD, RPO, RTO, lost Steps, queue time, and recovery success rate are recorded;
- [ ] Latest valid Checkpoint age, async queue, and rollback count are monitored;
- [ ] Nodes, Ranks, errors, and Checkpoints for each Attempt are traceable;
- [ ] Post-recovery Loss, data Watermark, and final model quality are consistent with the baseline.

The reliability of a training platform does not depend on whether the controller can recreate Pods, but on whether the old World can exit cleanly, the new World can avoid fault domains, the latest complete state can be validated and loaded, and whether the training semantics after recovery remain correct.

## References

- [PyTorch Elastic Run](https://docs.pytorch.org/docs/stable/elastic/run.html)
- [PyTorch Distributed Checkpoint](https://docs.pytorch.org/docs/main/distributed.checkpoint.html)
- [DeepSpeed Model Checkpointing](https://deepspeed.readthedocs.io/en/stable/model-checkpointing.html)
- [Megatron Core Distributed Checkpoint](https://docs.nvidia.com/megatron-core/developer-guide/latest/api-guide/core/dist_checkpointing.html)
- [Megatron Bridge Resiliency](https://docs.nvidia.com/nemo/megatron-bridge/latest/training/resiliency.html)
- [Orbax CheckpointManager](https://orbax.readthedocs.io/en/latest/api_reference/checkpoint.checkpoint_manager.html)
- [Elastic Horovod](https://horovod.readthedocs.io/en/latest/elastic_include.html)
- [Ray Train Fault Tolerance](https://docs.ray.io/en/latest/train/user-guides/fault-tolerance.html)
- [Kubernetes Persistent Volumes](https://kubernetes.io/docs/concepts/storage/persistent-volumes/)
- [Kubeflow Trainer Runtime Guide](https://trainer.kubeflow.org/en/latest/operator-guides/runtime.html)
- [JobSet Failure Policy](https://jobset.sigs.k8s.io/docs/tasks/failure_policy/)
- [Volcano Job](https://volcano.sh/docs/concepts/volcanojob/)
