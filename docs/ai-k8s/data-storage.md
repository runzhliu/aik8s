---
title: AI 数据、存储与缓存
description: 对象存储、共享文件、本地 NVMe、数据加载和多级缓存设计
status: stable
last_reviewed: 2026-08-02
---

# AI 数据、存储与缓存

AI 平台的数据路径通常比计算路径更容易被低估。GPU 已经分配成功，并不代表训练正在有效计算；当数据加载、模型下载或 Checkpoint 写入跟不上时，昂贵的加速器只是在等待 I/O。

本章从平台角度拆解数据分层、存储选型、缓存、数据局部性和故障诊断。

如果正在设计交互式开发环境，还需要把用户 Home、共享目录、模型缓存、Scratch 和 Idle 回收放在同一条生命周期中评估，见[大模型时代的 GPU Notebook 平台与存储选型](development/gpu-notebook-platform.md)。

## 1. 先把数据分成五类

| 数据类型 | 特征 | 典型存储 | 主要指标 |
| --- | --- | --- | --- |
| 原始数据集 | 容量大、长期保存、读取多于写入 | 对象存储 | 首字节延迟、吞吐、请求成本 |
| 训练样本/特征 | 大量小文件或分片、并发读取 | 对象存储、并行文件系统、缓存 | samples/s、随机读 IOPS |
| 模型权重 | 单文件很大、发布频繁、需版本化 | 对象存储、OCI Registry、共享文件 | 下载时间、校验时间、缓存命中率 |
| Checkpoint | 周期性大写入、必须可靠 | 对象存储、共享文件系统 | 保存耗时、恢复耗时、RPO |
| 临时中间数据 | 生命周期短、追求速度 | `emptyDir`、本地 NVMe | 本地带宽、容量水位、淘汰时间 |

不要用一个 PVC 同时解决这五类问题。它们的生命周期、访问模式和可靠性要求不同。

## 2. 常见存储层怎么选

### 对象存储

S3、GCS、Azure Blob 或兼容 S3 的对象存储适合数据集、模型和 Checkpoint 的长期保存。优势是容量、耐久性和版本化；代价是目录语义弱，大量小对象、随机读取和重复下载可能拖慢训练。

适合：

- 原始数据和不可变训练分片；
- 模型制品与评估结果；
- 跨集群恢复所需的 Checkpoint；
- 数据湖和离线归档。

### 共享文件系统

CephFS、Lustre、NFS、JuiceFS 等向 Pod 暴露 POSIX 文件接口，适合旧训练代码、共享目录和并行读取。选型时要确认元数据性能、客户端缓存、一致性模型、CSI 支持以及故障域。

### 块存储

块存储通过 PVC 提供稳定卷，适合数据库、MLflow 后端或单个任务的工作目录。多数块卷只有 `ReadWriteOnce`，不应假设多个节点可以同时挂载。

### 本地 NVMe

本地盘拥有最低延迟和最高性价比，但数据与节点绑定。它最适合作为可重建缓存或临时工作区，而不是唯一副本。

Kubernetes 的本地卷和存储容量会参与调度；CSI 驱动是否支持容量跟踪必须单独确认。参考：[Kubernetes Storage Capacity](https://kubernetes.io/docs/concepts/storage/storage-capacity/)

## 3. 推荐的冷热分层

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

核心原则是：上层缓存都可以丢失，权威数据源不能依赖某一节点；缓存键必须包含数据版本、转换版本和必要的模型版本。

## 4. 大量小文件为什么危险

百万个小文件会把瓶颈从数据带宽转移到元数据操作、TLS 请求、目录遍历和 Python 解释器开销。常见改进方式包括：

- 把样本打包为 WebDataset/TAR、Parquet 或 TFRecord 等较大分片；
- 对分片做确定性打乱，而不是每轮重新扫描目录；
- 增加并行 DataLoader，但同时监控 CPU、内存和存储队列；
- 在节点本地预取下一批分片；
- 对对象存储请求设置连接池、重试和合理并发。

分片不是越大越好。过大的分片会降低并行度并增加失败重传成本，应该通过实际训练测出平衡点。

## 5. 模型如何分发到推理 Pod

常见模式有四种：

1. **模型打入镜像**：简单，但镜像巨大、发布慢，不适合频繁更新。
2. **Init Container 下载**：主容器启动前拉取到共享卷，逻辑清晰，但冷启动时间长。
3. **CSI/对象存储挂载**：部署声明简单，需要确认读放大和缓存行为。
4. **节点级模型缓存**：DaemonSet 或缓存代理提前放置热点模型，速度快，但要解决版本和磁盘回收。

无论哪种模式，都应该校验权重摘要，避免只按可变标签如 `latest` 判断模型版本。

## 6. 一个可复现的预取模式

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

`emptyDir` 会跟随 Pod 生命周期，可能使用节点磁盘或内存；容量限制、节点临时存储请求和驱逐策略都要纳入设计。参考：[Kubernetes Ephemeral Volumes](https://kubernetes.io/docs/concepts/storage/ephemeral-volumes/)

## 7. 数据局部性必须进入调度

当 GPU、数据卷和高速网卡分别在不同拓扑域时，单独优化任何一层都可能无效。需要同时考虑：

- PVC 的可用区或节点亲和性；
- 本地缓存命中在哪些节点；
- GPU 型号、NVLink/NVSwitch 拓扑；
- RDMA 网卡所在 NUMA 节点；
- 队列允许使用的 `ResourceFlavor`；
- 集群扩容后数据预热需要多久。

对于短任务，等待缓存预热可能比直接远程读取更贵；对于多轮长训练，预热通常值得。

## 8. Checkpoint 的存储策略

Checkpoint 至少需要定义：

- 保存频率与可接受的训练进度损失，也就是 RPO；
- 本地临时副本和远端持久副本的关系；
- 保存是否阻塞训练；
- 多 Rank 文件的完整性标记；
- 保留数量和生命周期策略；
- 从不同并行拓扑恢复时是否支持重分片。

不要只测试“能写”，还要定期从远端恢复并继续训练。没有恢复演练的 Checkpoint 只是占用空间的文件。

## 9. 如何估算所需吞吐

粗略估算：

```text
最低持续读取带宽
  ≈ 每个样本平均字节数 × 全局 samples/s × 解码前放大系数
```

还应单独计算：

- 启动时所有 Rank 同时打开文件的元数据峰值；
- 推理副本扩容时模型并发下载带宽；
- Checkpoint 周期写入造成的突发流量；
- 跨可用区或公网读取成本；
- 压缩、解码和数据增强消耗的 CPU。

如果 GPU 利用率呈周期性锯齿，先把 DataLoader 等待时间、存储延迟和 Batch 准备时间放在同一时间轴上。

## 10. 必须监控的指标

| 层级 | 指标 |
| --- | --- |
| 应用 | DataLoader wait、samples/s、Checkpoint save/load duration |
| 文件系统 | IOPS、吞吐、metadata latency、客户端缓存命中 |
| 对象存储 | GET/HEAD 延迟、错误率、重试、限流、请求数 |
| 节点 | 磁盘队列、利用率、inode、临时存储水位 |
| 网络 | 到存储端的吞吐、重传、跨区流量 |
| GPU | 利用率与功耗是否因 I/O 周期性下降 |

## 11. 常见故障模式

| 现象 | 常见原因 | 优先检查 |
| --- | --- | --- |
| GPU 利用率周期性归零 | DataLoader 或远端读取阻塞 | Batch 准备时间、存储 P99 |
| 扩容后 Pod 长时间未就绪 | 每个副本重复下载大模型 | 下载并发、节点缓存、镜像大小 |
| PVC 一直 Pending | 拓扑或容量不满足 | StorageClass、CSI 容量、节点亲和性 |
| Checkpoint 偶尔无法恢复 | 多 Rank 写入未原子完成 | 完成标记、清单文件、对象一致性 |
| 节点被驱逐 | `emptyDir` 占满临时存储 | ephemeral-storage request/limit |

## 12. 上线清单

- [ ] 权威数据、缓存和临时数据边界清楚；
- [ ] 数据集、转换代码和模型都有不可变版本；
- [ ] 测过冷缓存、热缓存和并发启动三种场景；
- [ ] 本地 NVMe 丢失不会造成唯一数据副本丢失；
- [ ] Checkpoint 做过跨节点或跨集群恢复；
- [ ] 存储指标能关联到 namespace、Job 和模型版本；
- [ ] 对象存储请求与跨区流量成本可见；
- [ ] 临时存储容量、inode 和垃圾回收都有告警。

## 延伸阅读

- [Kubernetes Volumes](https://kubernetes.io/docs/concepts/storage/volumes/)
- [Kubernetes Storage Capacity](https://kubernetes.io/docs/concepts/storage/storage-capacity/)
- [Kubernetes Ephemeral Volumes](https://kubernetes.io/docs/concepts/storage/ephemeral-volumes/)
- [PyTorch Distributed Checkpoint](https://docs.pytorch.org/docs/main/distributed.checkpoint.html)
