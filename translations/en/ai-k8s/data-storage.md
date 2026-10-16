---
title: "AI Data, Storage, and Caching"
description: "Object storage, shared files, local NVMe, data loading, and multi-level cache design"
status: stable
last_reviewed: 2026-08-04
---

# AI Data, Storage, and Caching

The data path of an AI platform is often more underestimated than the compute path. A successful GPU allocation does not mean training is computing effectively; when data loading, model downloads, or Checkpoint writes cannot keep up, expensive accelerators are simply waiting on I/O.

This chapter breaks down data tiering, storage selection, caching, data locality, and fault diagnosis from a platform perspective.

If you need to further design Spark, Flink, Kafka, Trino, Lakehouse, and AI data pipelines, see [Big Data on Kubernetes](data/big-data-on-kubernetes.md).

If you are designing an interactive development environment, you also need to evaluate user Home, shared directories, model caches, Scratch, and Idle reclamation within the same lifecycle. See [GPU Notebook Platform and Storage Selection in the Large Model Era](development/gpu-notebook-platform.md).

## 1. First, classify data into five categories

| Data Type | Characteristics | Typical Storage | Key Metrics |
| --- | --- | --- | --- |
| Raw datasets | Large capacity, long-term retention, more reads than writes | Object storage | Time to first byte, throughput, request cost |
| Training samples/features | Many small files or shards, concurrent reads | Object storage, parallel file systems, cache | samples/s, random read IOPS |
| Model weights | Very large single files, frequent releases, need versioning | Object storage, OCI Registry, shared files | Download time, verification time, cache hit rate |
| Checkpoint | Periodic large writes, must be reliable | Object storage, shared file systems | Save duration, restore duration, RPO |
| Temporary intermediate data | Short lifecycle, speed-oriented | `emptyDir`, local NVMe | Local bandwidth, capacity level, eviction time |

Do not use a single PVC to solve all five categories at once. Their lifecycles, access patterns, and reliability requirements differ.

## 2. How to choose among common storage layers

### Object storage

S3, GCS, Azure Blob, or S3-compatible object storage is suitable for long-term retention of datasets, models, and Checkpoints. The advantages are capacity, durability, and versioning; the cost is weak directory semantics, and large numbers of small objects, random reads, and repeated downloads can slow down training.

Suitable for:

- Raw data and immutable training shards;
- Model artifacts and evaluation results;
- Checkpoints required for cross-cluster recovery;
- Data lakes and offline archiving.

### Shared file systems

CephFS, Lustre, NFS, JuiceFS, and others expose POSIX file interfaces to Pods, suitable for legacy training code, shared directories, and parallel reads. When selecting, confirm metadata performance, client-side caching, consistency models, CSI support, and failure domains.

### Block storage

Block storage provides stable volumes through PVCs, suitable for databases, MLflow backends, or working directories for a single task. Most block volumes only support `ReadWriteOnce`; you should not assume multiple nodes can mount them simultaneously.

### Local NVMe

Local disks offer the lowest latency and best cost-performance, but data is bound to the node. They are best suited as rebuildable caches or temporary workspaces, not as the only copy.

Kubernetes local volumes and storage capacity participate in scheduling; whether the CSI driver supports capacity tracking must be confirmed separately. Reference: [Kubernetes Storage Capacity](https://kubernetes.io/docs/concepts/storage/storage-capacity/)

## 3. Recommended hot/cold tiering

```text
权威数据源：对象存储
        │
        ▼
集群共享层：并行文件系统 / 分布式缓存
        │
        ▼
节点热缓存：本地 NVMe
        │
        ▼
进程缓存：Page Cache / 内存 / 框架预取
        │
        ▼
GPU 显存：当前 Batch 与模型分片
```

The core principle is: upper-layer caches can all be lost, and the authoritative data source must not depend on any single node; cache keys must include the data version, transformation version, and the necessary model version.

## 4. Why large numbers of small files are dangerous

Millions of small files shift the bottleneck from data bandwidth to metadata operations, TLS requests, directory traversal, and Python interpreter overhead. Common improvements include:

- Pack samples into larger shards such as WebDataset/TAR, Parquet, or TFRecord;
- Perform deterministic shuffling of shards instead of rescanning directories every epoch;
- Increase parallel DataLoader workers, while monitoring CPU, memory, and storage queues;
- Prefetch the next batch of shards locally on the node;
- Configure connection pools, retries, and reasonable concurrency for object storage requests.

Bigger shards are not always better. Excessively large shards reduce parallelism and increase the cost of failed retransmission; the balance point should be determined through actual training.

## 5. How to distribute models to inference Pods

There are four common patterns:

1. **Model baked into the image**: Simple, but the image is huge and releases are slow; not suitable for frequent updates.
2. **Init Container download**: Pulls to a shared volume before the main container starts; logic is clear, but cold start time is long.
3. **CSI/object storage mount**: Deployment declaration is simple; read amplification and cache behavior need to be confirmed.
4. **Node-level model cache**: A DaemonSet or cache proxy places hot models in advance; fast, but versioning and disk reclamation must be addressed.

Regardless of the pattern, weight digests should be verified, avoiding judging model versions only by mutable tags such as `latest`.

## 6. A reproducible prefetch pattern

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: model-worker
spec:
  initContainers:
    - name: fetch-model
      image: example.com/model-fetcher@sha256:...
      args: ["--model", "llama", "--revision", "sha256:..."]
      volumeMounts:
        - name: model-cache
          mountPath: /models
  containers:
    - name: server
      image: example.com/inference@sha256:...
      volumeMounts:
        - name: model-cache
          mountPath: /models
          readOnly: true
  volumes:
    - name: model-cache
      emptyDir:
        sizeLimit: 300Gi
```

`emptyDir` follows the Pod lifecycle and may use node disk or memory; capacity limits, node ephemeral storage requests, and eviction policies must all be included in the design. Reference: [Kubernetes Ephemeral Volumes](https://kubernetes.io/docs/concepts/storage/ephemeral-volumes/)

## 7. Data locality must be part of scheduling

When GPUs, data volumes, and high-speed NICs are in different topology domains, optimizing any single layer in isolation may be ineffective. The following must be considered together:

- PVC availability zone or node affinity;
- Which nodes have local cache hits;
- GPU model, NVLink/NVSwitch topology;
- NUMA node where the RDMA NIC resides;
- The `ResourceFlavor` the queue is allowed to use;
- How long data warm-up takes after cluster scaling.

For short tasks, waiting for cache warm-up may be more expensive than reading remotely; for multi-epoch long training, warm-up is usually worthwhile.

## 8. Checkpoint storage strategy

Checkpoint at minimum needs to define:

- Save frequency and acceptable training progress loss, i.e., RPO;
- The relationship between local temporary copies and remote persistent copies;
- Whether saving blocks training;
- Integrity markers for multi-Rank files;
- Retention count and lifecycle policy;
- Whether resharding is supported when recovering from a different parallel topology.

Do not only test that writes work; also periodically restore from remote and continue training. A Checkpoint without recovery drills is just a file occupying space.

## 9. How to estimate required throughput

Rough estimate:

```text
最低持续读取带宽
  ≈ 每个样本平均字节数 × 全局 samples/s × 解码前放大系数
```

Also calculate separately:

- Metadata peak when all Ranks open files simultaneously at startup;
- Concurrent model download bandwidth when scaling out inference replicas;
- Burst traffic caused by periodic Checkpoint writes;
- Cross-availability-zone or public internet read costs;
- CPU consumed by compression, decoding, and data augmentation.

If GPU utilization shows a periodic sawtooth pattern, first place DataLoader wait time, storage latency, and Batch preparation time on the same timeline.

## 10. Metrics that must be monitored

| Layer | Metrics |
| --- | --- |
| Application | DataLoader wait, samples/s, Checkpoint save/load duration |
| File system | IOPS, throughput, metadata latency, client cache hits |
| Object storage | GET/HEAD latency, error rate, retries, throttling, request count |
| Node | Disk queue, utilization, inode, ephemeral storage level |
| Network | Throughput to storage, retransmissions, cross-zone traffic |
| GPU | Whether utilization and power consumption drop periodically due to I/O |

## 11. Common failure modes

| Symptom | Common Cause | Priority Checks |
| --- | --- | --- |
| GPU utilization periodically drops to zero | DataLoader or remote read blocking | Batch preparation time, storage P99 |
| Pods not ready for a long time after scaling | Each replica repeatedly downloads large models | Download concurrency, node cache, image size |
| PVC stuck in Pending | Topology or capacity not satisfied | StorageClass, CSI capacity, node affinity |
| Checkpoint occasionally fails to recover | Multi-Rank writes not completed atomically | Completion markers, manifest files, object consistency |
| Node evicted | `emptyDir` fills ephemeral storage | ephemeral-storage request/limit |

## 12. Launch checklist

- [ ] Authoritative data, cache, and temporary data boundaries are clear;
- [ ] Datasets, transformation code, and models all have immutable versions;
- [ ] Tested three scenarios: cold cache, hot cache, and concurrent startup;
- [ ] Loss of local NVMe does not cause loss of the only data copy;
- [ ] Checkpoint has been tested for cross-node or cross-cluster recovery;
- [ ] Storage metrics can be correlated to namespace, Job, and model version;
- [ ] Object storage requests and cross-zone traffic costs are visible;
- [ ] Alerts exist for ephemeral storage capacity, inodes, and garbage collection.

## Further Reading

- [Kubernetes Volumes](https://kubernetes.io/docs/concepts/storage/volumes/)
- [Kubernetes Storage Capacity](https://kubernetes.io/docs/concepts/storage/storage-capacity/)
- [Kubernetes Ephemeral Volumes](https://kubernetes.io/docs/concepts/storage/ephemeral-volumes/)
- [PyTorch Distributed Checkpoint](https://docs.pytorch.org/docs/main/distributed.checkpoint.html)
