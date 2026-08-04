---
title: 分布式训练平台
description: 训练控制器、Gang Scheduling、集合通信、容错和作业生命周期
status: evolving
last_reviewed: 2026-08-03
---

# 分布式训练平台

分布式训练不是“把 `replicas` 调大”。平台必须同时处理多角色启动、资源成组分配、网络拓扑、数据供给、检查点、失败恢复和实验追踪。本页给出 Kubernetes 上训练控制面的设计方法。

## 1. 一次训练任务经过什么

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

平台的目标不是隐藏所有 Kubernetes 细节，而是让研究代码只关心训练逻辑，让镜像、资源、调度、存储和容错由可复用模板表达。

## 2. 三种主流控制方式

| 方案 | 核心抽象 | 优势 | 代价 |
| --- | --- | --- | --- |
| Kubeflow Trainer | `TrainJob` + `TrainingRuntime` | 面向 AI 训练、框架模板、Python SDK、Kueue/JobSet 集成 | 需要维护 Trainer CRD 和 Runtime 模板 |
| KubeRay | `RayCluster` / `RayJob` | Python 体验好，数据、训练、Tune、Serve 可共享 Ray 生态 | 应用较深绑定 Ray 的 Actor/Task 模型 |
| JobSet + 原生 Job | 一组有关系的 Kubernetes Jobs | 框架无关、语义清晰、适合自研平台或 HPC | 需要自行封装训练框架启动和用户接口 |

### Kubeflow Trainer

Trainer 适合平台团队预先定义 `ClusterTrainingRuntime`，用户只提交训练函数、镜像、资源和副本数。当前版本面向 PyTorch、JAX、Hugging Face、DeepSpeed、MPI 等，并复用 Kueue、JobSet 和 LeaderWorkerSet 等 Kubernetes 组件。

新版本还支持 TrainJob 的暂停、恢复和 Active Deadline；暂停会释放 Pod，但训练能否真正续跑仍取决于应用是否正确保存 Checkpoint。

参考：[Kubeflow Trainer](https://www.kubeflow.org/docs/components/trainer/overview/)、[TrainJob Lifecycle](https://www.kubeflow.org/docs/components/trainer/user-guides/trainjob-lifecycle/)

### KubeRay

KubeRay 提供三类主要资源：

- `RayCluster`：长期或手工管理的 Ray 集群；
- `RayJob`：创建集群、提交任务，并可在结束后回收集群；
- `RayService`：Ray Serve 与 RayCluster 的组合，提供高可用和滚动升级能力。

若数据预处理、训练、超参搜索和服务都基于 Python，Ray 能减少跨系统搬运；若团队主要使用 MPI、Slurm 迁移代码或框架原生启动器，Kubeflow Trainer/JobSet 往往更自然。

参考：[KubeRay](https://ray-project.github.io/kuberay/)

### JobSet

JobSet 将分布式任务表达为多个 `ReplicatedJob`，可以包含不同 Pod 模板，并管理整体成功、失败、重启、服务发现和拓扑域。它适合作为上层训练 API 的通用执行层，而不是直接替代所有训练框架。

参考：[Introducing JobSet](https://kubernetes.io/blog/2025/03/23/introducing-jobset/)

## 3. 资源必须成组准入

假设任务需要 4 台机器、每台 8 张 GPU。如果只调度成功 3 台，24 张卡可能被空占，但训练永远无法开始。这就是 Gang 或 All-or-Nothing 的必要性。

训练任务应明确：

- `minAvailable` 或完整 PodSet 大小；
- 单个 Worker 的 CPU、内存、GPU、HugePages 和共享内存；
- 可接受的 GPU `ResourceFlavor`；
- 是否允许降级到其他型号或 Spot 节点；
- 必须集中到同一 Rack/Block，还是只需尽量集中；
- 最大等待时间、运行时间和重试次数。

不建议用无限重试掩盖容量不足。队列应该公开 Pending 原因，让用户知道是“缺 8 张 H100”“不满足同机架”还是“团队配额已耗尽”。

## 4. 网络与通信

多机训练平台要同时观察容器网络和训练通信库。

### 常见通信栈

| 框架/模式 | 常用通信 |
| --- | --- |
| PyTorch DDP / FSDP | NCCL（GPU）、Gloo（CPU/控制） |
| DeepSpeed / Megatron-LM | NCCL + 框架并行策略 |
| MPI / Horovod | MPI + NCCL |
| JAX / XLA | XLA Collective、NCCL 或 TPU ICI |
| Ray Train | 由 Ray 协调，底层仍可能使用 Torch/NCCL |

### 平台侧检查

- Pod 是否能发现正确的 RDMA/RoCE 设备；
- MTU、PFC/ECN 和交换机配置是否一致；
- NCCL 是否错误地走普通 TCP 网卡；
- `/dev/shm` 是否足够；
- CPU/NUMA、NIC 和 GPU 是否跨 Socket；
- DNS、Headless Service 和 Worker Rank 是否稳定；
- NetworkPolicy 是否放行训练端口与控制面连接。

训练性能下降不一定是 GPU 问题。建议保存 NCCL Test、存储吞吐和节点间带宽基线，并在节点或驱动升级后自动复测。

## 5. 数据供给决定 GPU 是否在等待

GPU 训练链路通常包括：对象存储 → 数据集缓存 → CPU 解码/增强 → Host Memory → GPU。任何一段不足都会让昂贵的 GPU 等待。

### 常见数据方案

| 方案 | 优势 | 注意点 |
| --- | --- | --- |
| 直接读取 S3/对象存储 | 数据持久、容量弹性 | 小文件、反复下载和远端延迟可能成为瓶颈 |
| PVC / 分布式文件系统 | POSIX 兼容，传统代码改动少 | 元数据压力、并发吞吐和跨区成本 |
| 节点本地 NVMe Cache | 吞吐高、降低远端读取 | 数据预热、淘汰、一致性和任务迁移 |
| 数据集流式读取 | 减少完整落盘和启动时间 | 需要框架、格式和重试机制配合 |

推荐把数据版本保存为不可变 URI 或 Manifest，不要用会变化的目录名称。训练记录至少关联：代码 Commit、镜像 Digest、数据版本、超参数、运行时版本和随机种子。

## 6. Checkpoint 是调度能力的一部分

Spot、抢占和节点故障只有在应用能恢复时才有成本优势。一个合格的 Checkpoint 方案要回答：

- 多久保存一次，保存耗时多长；
- 是所有 Rank 保存，还是由 Leader 汇总；
- Checkpoint 是否原子可见；
- 恢复时 World Size 改变是否可用；
- 优化器、学习率调度器、随机状态是否完整；
- 作业删除、暂停或抢占前能否触发最后一次保存；
- 旧 Checkpoint 如何保留和清理。

可以用以下近似式判断间隔：

```text
预期浪费成本 ≈ 故障概率 × 平均丢失训练时间
Checkpoint 成本 ≈ 保存次数 × 单次暂停/IO 时间
```

间隔不是越短越好；应基于故障率、保存耗时和训练单价测量。

## 7. 失败分类与恢复策略

| 失败类型 | 平台动作 | 是否直接重试 |
| --- | --- | --- |
| 镜像拉取、Secret、配置错误 | 快速失败并提示用户 | 否，修正配置后再提交 |
| GPU XID、节点掉线 | 隔离设备/节点，从 Checkpoint 重启 | 是，但应限制次数 |
| OOM | 保存日志和显存指标 | 通常否，需调整 Batch/并行策略 |
| Spot 回收 | 优雅终止并恢复 | 是 |
| NCCL 超时 | 收集所有 Rank 日志和网络状态 | 有条件重试 |
| 数据损坏或 Schema 变化 | 标记数据版本失败 | 否 |
| 训练 Loss NaN | 作为模型质量失败处理 | 不应由基础设施无限重试 |

平台要区分 Infrastructure Failure 与 User Code Failure，否则自动重试会重复烧掉 GPU 时间。

## 8. 镜像和运行时模板

推荐把镜像分为两层：

1. **平台基础镜像**：CUDA/ROCm、Python、通信库、常用诊断工具和安全更新。
2. **项目镜像**：训练代码与锁定依赖。

运行时模板中统一设置：

- 非 root 用户与只读根文件系统；
- `/dev/shm`、临时存储和 ulimit；
- NCCL/通信环境变量；
- ServiceAccount、NetworkPolicy 和 Secret 引用；
- 队列名、优先级、拓扑要求和可接受节点池；
- 指标、日志、退出码和 Checkpoint Hook。

不要在每个项目复制一份 300 行 YAML。平台团队维护少量版本化 Runtime，项目只覆盖必要字段。

## 9. 可观测与实验记录

基础设施侧至少记录：

- Job 排队、启动、运行、暂停和完成时间；
- 每个 Rank 的退出码与失败原因；
- GPU SM、显存、功耗、温度、XID；
- CPU、内存、网络和存储吞吐；
- NCCL Collective 延迟与训练 Step Time；
- Checkpoint 时间、大小和恢复结果。

实验侧至少记录：

- 参数、指标和模型制品；
- 数据集与代码版本；
- 训练镜像 Digest；
- 完整资源与运行时配置；
- 评估集结果和模型审批状态。

MLflow 适合承载实验与模型元数据，Prometheus/DCGM 负责基础设施时间序列；两者需要通过 Run ID、Job UID 和模型版本建立关联，而不是彼此替代。

## 10. 上线前检查清单

- [ ] 单机单卡、单机多卡、多机多卡分别有基准结果。
- [ ] Job 必须成组准入，不会部分启动后长期占卡。
- [ ] 拓扑标签、RDMA、NCCL 和 MTU 已验证。
- [ ] 数据集有不可变版本，读取吞吐达到训练要求。
- [ ] Checkpoint 能在真实故障和抢占场景恢复。
- [ ] 用户错误不会被平台无限重试。
- [ ] Runtime、镜像、驱动和训练框架版本可追溯。
- [ ] 日志可以按 Job 和 Rank 聚合检索。
- [ ] MLflow Run、Kubernetes Job UID 和模型制品可以相互关联。
- [ ] 已定义任务时限、配额、优先级和清理策略。

网络部分的原理、部署组件和逐层排障方法见：[RDMA 与 AI 高速网络](rdma-networking.md)。

当 GPU 容量分散在多个集群时，优先让完整 TrainJob 通过 MultiKueue 等机制选择一个目标集群，再在集群内完成 Gang 和拓扑调度；跨地域同步 Collective 通常不是默认方案。详见：[Kubernetes 跨集群与大规模 GPU](cluster/multi-cluster-ai.md)。
