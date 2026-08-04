---
title: Ray 在大模型训练与推理中的角色
description: Ray Core、Data、Train、Tune、Serve、Serve LLM 与 KubeRay 在大模型数据处理、训练、后训练和在线推理中的边界
status: evolving
last_reviewed: 2026-08-04
---

# Ray 在大模型训练与推理中的角色

Ray 在大模型时代重新变得重要，不是因为它发明了新的训练 Kernel 或推理引擎，而是因为大模型系统需要同时协调数据处理、分布式训练、超参搜索、批量推理、在线服务和强化学习 Rollout。Ray 用统一的 Python Task、Actor、资源和调度模型，把这些阶段放进同一个分布式运行时。

它的边界必须先说清楚：Ray 负责进程编排、资源放置、数据流和应用生命周期；PyTorch、JAX、DeepSpeed、FSDP、NCCL、vLLM、SGLang 等仍负责模型计算、并行算法与通信。把 Ray 当成训练框架或 CUDA/NCCL 的替代品，会直接导致错误的架构判断。

## 1. 为什么大模型比传统机器学习更需要 Ray

传统训练常接近一个固定 Worker Group：准备好数据，启动若干 Rank，训练结束后退出。大模型平台增加了更多异构、动态和有状态的角色：

- CPU Worker 解析、过滤、Tokenize 和打包数据；
- GPU Worker 执行预训练、SFT、DPO、GRPO 等训练；
- 多个 Trial 并行搜索学习率、并行度和 Batch；
- Reward、Reference、Policy、Rollout 等模型在后训练中协同；
- vLLM/SGLang Worker 执行在线或批量生成；
- Router、Preprocessor、Retriever 和 Postprocessor 组成在线推理图；
- 不同角色使用不同 GPU、CPU、内存、网络和弹性策略。

Ray 的 Task/Actor、Placement Group、异构资源和共享对象传输，适合表达这种动态 Python 分布式系统。但固定拓扑、单一框架的大规模预训练未必需要 Ray；`torchrun`、Kubeflow Trainer、JobSet、Slurm 或框架原生 Launcher 仍可能更直接。

## 2. Ray 生态分层

| 层 | 核心抽象 | 在大模型系统中的职责 |
| --- | --- | --- |
| Ray Core | Task、Actor、Object Ref、Placement Group | 分布式执行、状态服务、资源声明和成组放置 |
| Ray Data | Dataset、Block、Streaming Execution | 数据读取、转换、Tokenize、批量推理和训练数据供给 |
| Ray Train | Trainer、Worker、ScalingConfig、Checkpoint | 启动训练 Worker、建立框架分布式环境、恢复与指标 |
| Ray Tune | Tuner、Trial、Search Algorithm、Scheduler | 超参搜索、Trial 并发、早停和资源分配 |
| Ray Serve | Deployment、Replica、Handle、Application | Python 微服务图、流量、Batch、背压和独立扩缩 |
| Ray Serve LLM | LLMServer、Ingress、Routing、Engine Adapter | 多机/多模型 LLM 服务、vLLM 集成、P/D 分离和高级路由 |
| KubeRay | `RayCluster`、`RayJob`、`RayService` | 在 Kubernetes 上管理 Ray 集群、批任务和在线服务 |

Ray AIR 曾作为多个库的统一品牌出现。平台 API 不应依赖品牌名称，而应固定实际使用的 Ray Data、Train、Tune、Serve 和 KubeRay 版本与接口。

## 3. 一条端到端大模型链路

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

Kubernetes 视角：

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

Kubernetes Scheduler 决定 Pod 去哪个节点，Ray Scheduler 决定 Task/Actor 去哪个 Ray Worker 进程。两层都在调度，但对象和时间尺度不同。

## 4. Ray Core 的关键语义

### Task 与 Actor

- **Task** 适合无状态、可并行、完成即释放的函数，例如解析文件、Tokenize 和离线评估；
- **Actor** 是有状态进程，适合模型副本、Tokenizer 服务、Rollout Worker 和长期缓存；
- **Object Ref/Object Store** 在 Task/Actor 之间传输对象，适合中间数据交换，但不是持久数据湖；
- **Placement Group** 预留一组资源 Bundle，并用 `PACK`、`STRICT_PACK`、`SPREAD` 等策略控制放置。

大对象进入 Object Store 前要评估序列化、共享内存、网络复制和 Spill。模型权重、Checkpoint 与权威数据仍应放在对象存储、共享文件系统或模型 Registry，而不是依赖 Ray Object Store 长期保存。

### 资源是逻辑标签

Ray 可以声明 CPU、GPU 和自定义资源，但它不会替 Kubernetes 创建设备。Kubernetes Pod 先通过 `nvidia.com/gpu`、DRA 等获得设备，Ray 再在 Pod 已拥有的资源范围内分配 Actor/Task。

自定义资源适合表达：

- GPU 型号或节点能力；
- 本地模型缓存是否命中；
- 特定网络或加速器；
- 只能放在某类 Worker Group 的角色。

自定义资源标签不等于真实隔离，底层仍需 Kubernetes Resource、Node Label、Affinity 和安全策略。

## 5. KubeRay 的三个入口

| CRD | 生命周期 | 适合 | 不建议 |
| --- | --- | --- | --- |
| `RayCluster` | 长期或由外部系统管理 | 共享开发集群、手工提交、多作业服务 | 无治理地让所有租户共享一个无限生命周期集群 |
| `RayJob` | 创建集群、提交 Job、结束后可回收 | 数据处理、训练、Tune、批量推理 | 在线服务或依赖固定 Endpoint 的长期流量 |
| `RayService` | RayCluster + Serve Application | 在线推理、组合式 AI 服务、滚动升级 | 一次性批任务 |

官方推荐使用 KubeRay 在 Kubernetes 上运行 Ray。生产平台通常默认：

- 批任务使用每 Job 独立 `RayJob`，结束后回收集群；
- 在线服务使用独立 `RayService`；
- 共享 `RayCluster` 只用于受控开发、交互分析或大量短任务；
- 不把训练和在线推理放在同一 RayCluster 内争用资源和故障预算。

参考：[KubeRay](https://ray-project.github.io/kuberay/)、[Ray on Kubernetes](https://docs.ray.io/en/latest/cluster/kubernetes/)

## 6. Ray Data：连接 CPU 数据处理与 GPU

Ray Data 使用 Block 和流式执行处理 Parquet、JSON、图片、音视频等数据，适合：

- 训练前的 Python/UDF、Tokenizer 和多模态解码；
- 将 CPU 预处理与 GPU 训练流水化；
- Embedding、Reward Scoring、合成数据和离线生成；
- 将 Dataset 自动切分给 Ray Train Worker；
- 在异构 CPU/GPU Worker Group 间组织批处理流水线。

```text
Read → Map/Filter → Repartition/Shuffle → map_batches(GPU) → Write
                        │
                        └→ iter_torch_batches() → Train Worker
```

关键调优项：

- Block 大小与数量，避免单 Block 过大或调度数爆炸；
- `map_batches` 的 Batch、并发和 Actor Pool；
- CPU 解析、对象存储读取和 GPU 消费之间的背压；
- Object Store 内存、Spill 目录和本地磁盘水位；
- 小文件、压缩格式和 Tokenizer CPU 开销；
- 训练 Epoch 重复读取时是缓存、重算还是直接使用框架 DataLoader。

Ray Data 更像面向 AI 数据处理的 Python 执行层，不应自动替代 Spark/Flink：复杂 SQL、Lakehouse 大规模表维护、持续有状态流计算和成熟数据治理通常仍由大数据平台承担。两者常见组合是 Spark/Flink 生成版本化表，Ray Data 完成靠近模型的最后一公里处理。

参考：[Ray Data](https://docs.ray.io/en/latest/data/data.html)、[Ray Train Data Loading](https://docs.ray.io/en/latest/train/user-guides/data-loading-preprocessing.html)

## 7. Ray Train：训练控制层，不是训练 Kernel

Ray Train 的基本模型是：用户定义 Training Function，Trainer 创建一组 Worker，配置资源和数量，建立 PyTorch 等框架的分布式环境，然后在每个 Worker 中执行训练函数。

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

适合组合：

| 训练栈 | Ray 负责 | 框架负责 |
| --- | --- | --- |
| PyTorch DDP/FSDP | Worker 生命周期、Rank 环境、结果和恢复 | 梯度同步、参数分片和计算 |
| DeepSpeed | 进程与资源编排 | ZeRO、并行、Optimizer 和通信 |
| Hugging Face Transformers/Accelerate | 分布式启动、Checkpoint/指标集成 | Trainer、模型和训练循环 |
| JAX/Lightning | 集群执行与资源 | 框架并行和训练语义 |

在大规模预训练中，Ray 是否值得引入取决于外围复杂度。如果任务只是固定 128 个 Rank 运行数周，原生 Launcher 可能更简单；如果同一平台还要做数据处理、弹性 Trial、评估、生成和后训练 Actor 编排，Ray 的统一执行模型价值更大。

参考：[Ray Train Overview](https://docs.ray.io/en/latest/train/overview.html)、[Ray Train Examples](https://docs.ray.io/en/latest/train/examples.html)

## 8. Checkpoint 与训练容错

Ray 可以在 Worker/节点失败后重建 Worker Group，但恢复进度依赖应用保存并加载 Checkpoint。默认重试次数、Driver 容错和 Train API 在不同 Ray 版本间可能不同，必须按目标版本验证。

生产要求：

- `storage_path` 指向所有 Worker 可访问的对象存储或共享文件系统；
- FSDP、DeepSpeed、Megatron 等模型并行优先并行上传各自 Shard；
- Checkpoint 包含模型、Optimizer、Scheduler、随机状态和数据 Watermark；
- Head/Driver、Worker、节点和对象存储故障分别演练；
- Spot 节点退出前尽力保存，但不能依赖 PreStop 一定完成；
- 限制重试，区分节点故障、OOM、数据错误和代码异常。

Ray Train Worker 故障恢复通常会停止当前 Worker Group、重新创建全部 Worker，再从最新 Checkpoint 恢复。它不是单个 Rank 无损热替换。

参考：[Ray Train Fault Tolerance](https://docs.ray.io/en/latest/train/user-guides/fault-tolerance.html)、[Ray Train Checkpoints](https://docs.ray.io/en/latest/train/user-guides/checkpoints.html)

## 9. Ray Tune：搜索的是实验，不是扩大单个模型

Ray Tune 在多个 Trial 之间分配资源，可组合 Ray Train 让每个 Trial 本身又是分布式训练。它适合：

- SFT/DPO 学习率、Batch、LoRA Rank 等搜索；
- 量化、并行度和推理参数探索；
- ASHA/HyperBand 等早停；
- 小规模关键参数筛选后，再启动完整训练。

容量必须按嵌套关系计算：

```text
总 GPU ≈ 并发 Trial 数 × 每 Trial Worker 数 × 每 Worker GPU
```

不要让几十个 Trial 自动占满生产 GPU 池。Tune Driver、Trial Checkpoint、搜索状态和远端存储也必须进入故障恢复设计。

参考：[Ray Tune](https://docs.ray.io/en/latest/tune/)、[Ray Train Hyperparameter Optimization](https://docs.ray.io/en/latest/train/user-guides/hyperparameter-optimization.html)

## 10. 后训练与 RLHF/GRPO

大模型后训练常包含多个模型角色和两种截然不同的负载：

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

Ray Actor 很适合表达长期存在的 Policy、Reference、Reward 和 Rollout 角色，Ray Task 适合并行评分与数据整理，Placement Group 可协调每个角色的 GPU Bundle。因此许多后训练系统把 Ray 用作编排底座，并用 vLLM/SGLang 执行 Rollout、PyTorch/DeepSpeed 执行更新。

真正困难的部分不是“启动 Actor”，而是：

- 训练与 Rollout 是否共置 GPU，如何避免显存峰值冲突；
- 权重多久同步一次，使用全量、Shard 还是增量传输；
- Rollout 版本与 Policy Step 如何对应；
- Reward/Verifier 变慢时如何施加背压；
- Generation、Training 和数据处理的 GPU 配比如何动态调整；
- 失败恢复后是否重复消费或污染样本；
- 算法实现、Ray、PyTorch、vLLM 和 CUDA 版本是否兼容。

Ray 本身不提供完整的 RLHF 算法正确性、奖励设计或权重同步协议。采用基于 Ray 的后训练框架时，要单独评审它对 PPO、DPO、GRPO 等算法、模型并行和目标硬件的支持。

## 11. Ray Data 批量推理

离线 Embedding、Reward Scoring、评估和合成数据通常不需要长期 HTTP 服务。Ray Data 可以让 GPU Actor Pool 对 Batch 执行推理，并把结果写回 Lakehouse 或对象存储。

与在线服务的差异：

| 维度 | Ray Data 批量推理 | Ray Serve 在线推理 |
| --- | --- | --- |
| 输入 | Dataset/文件/表 | HTTP/gRPC/Handle 请求 |
| 优化目标 | 总吞吐、成本、可恢复 | TTFT、TPOT、尾延迟、可用性 |
| 背压 | Dataset 执行流水线 | Queue、Replica 和请求拒绝 |
| 生命周期 | 完成后退出 | 长期运行 |
| 输出 | 文件/表/数据集 | 流式或普通响应 |

不要为了复用 API，把数十亿条离线数据逐条经过生产网关；也不要用批处理 Job 承接需要低延迟和流式返回的在线请求。

## 12. Ray Serve：组合式 AI 微服务

Ray Serve 的 Deployment 可以分别包装预处理、Embedding、Retriever、Reranker、LLM、Guardrail 和后处理，并通过 Deployment Handle 组成应用图。每个 Deployment 可以使用不同资源和副本数。

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

它适合 Python 逻辑多、组件间传递对象多、需要独立扩缩的 Compound AI 应用。平台仍需在 Ray Serve 外提供统一身份、租户配额、WAF、全局流量和 API 治理；不要让每个应用自行实现企业网关。

生产在 Kubernetes 上优先使用 `RayService`，由 KubeRay 管理健康、状态、集群恢复和升级。Serve Config 用于声明 Application 与 Deployment 参数，镜像或远端 `working_dir` 必须不可变。

参考：[Ray Serve Production Guide](https://docs.ray.io/en/latest/serve/production-guide/)、[Deploy Ray Serve on Kubernetes](https://docs.ray.io/en/latest/serve/production-guide/kubernetes.html)

## 13. Ray Serve LLM 与 vLLM 的关系

vLLM 是推理引擎，Ray Serve LLM 是围绕推理引擎构建的分布式服务框架。典型组合是：

```text
Ray Serve LLM
  ├── OpenAI-Compatible Ingress
  ├── Router / Autoscaling / Deployment Graph
  └── LLMServer Replica
        └── vLLM Engine
              └── TP / PP / GPU Worker
```

Ray Serve LLM 当前重点覆盖：

- 单模型水平扩展和多模型服务；
- 跨节点 Tensor/Pipeline Parallel；
- Prefix/Session-aware 自定义路由；
- Multi-LoRA；
- Prefill/Decode 分离；
- Data Parallel Attention 与 Expert Parallel 等大规模模式；
- OpenAI-Compatible API、指标和 Grafana 集成。

如果单个 `Deployment + vLLM` 已满足 SLO，不需要仅为了“云原生”增加 Ray。以下场景更值得评估 Ray Serve LLM：一个逻辑副本跨节点、多模型需要统一 Python 控制、复杂前后处理需要独立扩缩，或已经以 Ray 承载训练/后训练与数据处理。

参考：[Ray Serve LLM](https://docs.ray.io/en/latest/serve/llm/)、[Ray Serve LLM Architecture](https://docs.ray.io/en/latest/serve/llm/architecture/overview.html)

## 14. 三层弹性必须协同

```text
Ray Serve Autoscaler：请求队列 → Replica 数
          │
Ray Autoscaler：待调度 Actor/Task → Ray Worker Pod 数
          │
Node Autoscaler：Pending Pod → Kubernetes Node 数
```

训练批任务还可能增加第四层 Kueue 准入。常见问题：

- Serve 已扩大 Replica，但 Ray Worker Pod 仍等待 GPU；
- Ray 扩容速度快于节点和模型预热，造成大量 Pending；
- Node 缩容时模型缓存和 Object Store 数据丢失；
- Kueue 已按上限准入，Ray Autoscaler 又请求超过配额的 Worker；
- HPA、Ray Serve Autoscaler 和外部 Autoscaler 同时修改同一副本数。

每一层都应设置最小、最大、冷却和失败边界。LLM 扩缩指标优先使用 Queue、Running Request、Token、KV Cache、TTFT/TPOT，而不是只看 CPU 或 GPU Utilization。

参考：[Ray Serve Autoscaling](https://docs.ray.io/en/latest/serve/autoscaling-guide.html)

## 15. Kueue、Gang 与弹性 RayJob

Kueue 可以管理 `RayJob`、`RayCluster` 和 `RayService` 的配额与准入。批训练常使用 `RayJob`：Kueue 控制 `spec.suspend`，准入后 KubeRay 才创建 RayCluster。

注意：

- 固定规模分布式训练应按完整 Head + Worker Group 做成组准入；
- Kueue 管理的 RayJob 不应复用已有 RayCluster，并应在结束后回收；
- Ray In-tree Autoscaling 与 Kueue 弹性 Workload 的版本和 Feature Gate 必须匹配；
- `minReplicas` 是最小可运行资源，`maxReplicas` 是容量上限，两者都进入队列规划；
- Ray Placement Group 只能在已准入、已创建的 Pod 内放置 Actor，不能替代集群级配额。

参考：[Kueue RayJob](https://kueue.sigs.k8s.io/docs/tasks/run/rayjobs/)

## 16. GPU、拓扑与高速网络

Ray 能表达 Placement Group，但不会自动理解所有硬件拓扑。大模型训练和多机推理仍要配置：

- Kubernetes Node Affinity、Taint/Toleration 和拓扑感知调度；
- Head Pod 不申请昂贵 GPU，除非它确实执行模型工作；
- Worker Group 按 GPU 型号、CPU/内存、NIC 和用途拆分；
- TP 尽量位于同一 NVLink/NVSwitch 域；
- PP/训练跨节点验证 RDMA、NCCL、MTU 和 NUMA；
- Object Store、`/dev/shm`、Spill 与模型缓存设置临时存储请求；
- Placement Group 的 Bundle 与实际每个 Actor 的 GPU/CPU 完全一致。

Ray Dashboard 显示逻辑资源充足，不代表 NCCL 选对网卡或 GPU 与 NIC 位于同一 NUMA。网络基线仍需用 NCCL Tests、iperf/ib_write_bw 等独立验证。

## 17. Head、GCS 与故障域

Ray Head 承载 GCS、Dashboard、Job/Serve 控制入口等关键功能。默认情况下，GCS 状态主要在内存中，Head/GCS 故障可能导致集群状态丢失。

建议：

- 批 `RayJob` 依靠外部 Checkpoint 和 Job 重建，不把 Head 当持久状态；
- 高可用 `RayService` 按官方支持矩阵评估 GCS Fault Tolerance 与 HA Redis；
- Head 使用可靠节点、PriorityClass、PDB 和合理资源，避免 CPU/内存被 Worker 任务挤占；
- 不向公网暴露 Dashboard、GCS、Ray Client 和 Job Submission 端口；
- 记录 RayService、Serve Application、Deployment、Actor 和底层 Pod 的关联。

GCS Fault Tolerance 不等于请求无损：连接、队列中请求、Actor 内存和未持久化 Object 仍可能丢失。

参考：[KubeRay GCS Fault Tolerance](https://docs.ray.io/en/latest/cluster/kubernetes/user-guides/kuberay-gcs-ft.html)

## 18. 存储和依赖发布

- 生产镜像固定 Ray、Python、CUDA、PyTorch、vLLM 与业务依赖；
- 不让所有 Worker 启动后从公网 `pip install`；
- Runtime Environment 适合小规模、不可变远端包，不应替代镜像供应链；
- Checkpoint、训练结果和 Dataset Manifest 使用对象存储或可靠共享文件系统；
- Object Store Spill 使用容量明确的本地 NVMe/PVC，并监控磁盘水位；
- 模型权重通过节点缓存、PVC、对象存储或 P2P 分发，不经 Ray Head 中转；
- Head 和 Worker 镜像中的 Ray 版本必须匹配目标 KubeRay 版本矩阵。

## 19. 可观测性

| 层 | 关键指标与日志 |
| --- | --- |
| Kubernetes | Pod Pending、启动、驱逐、GPU/CPU/内存/临时存储 |
| KubeRay | CR Condition、Operator Reconcile、集群创建和升级 |
| Ray Core | Node、Task、Actor、Placement Group、Object Store、Spill |
| Ray Data | Block、Operator 吞吐、Backpressure、CPU/GPU Idle |
| Ray Train/Tune | Worker、Trial、Loss、Checkpoint、Retry、Driver |
| Ray Serve | Queue、Ongoing Request、Replica、Autoscaling、错误 |
| LLM Engine | TTFT、TPOT、Token/s、KV Cache、Batch、模型加载 |

统一标签建议：

```text
namespace / tenant / raycluster / rayjob / rayservice
job_id / actor_id / serve_application / deployment / replica
model_id / dataset_snapshot / code_commit / image_digest
node / pod / gpu_uuid / accelerator_type
```

Ray Dashboard 是诊断入口，不是长期监控数据库。指标进入 Prometheus，日志进入集中平台，事件和 Checkpoint 元数据进入可持久系统。

## 20. 多租户与安全

- 不让不互信租户共享一个 RayCluster；Ray Actor/Task 是分布式 Python 代码执行能力；
- 每个 RayJob/RayService 使用最小权限 ServiceAccount；
- NetworkPolicy 限制 Head、Worker、对象存储、指标和外部 API 通信；
- Dashboard、Client、GCS 和 Job Submission 只在受信网络开放；
- RuntimeEnv、远端代码包、模型和 Pickle/序列化对象都进入供应链审查；
- 对象存储使用 Workload Identity/短期凭据；
- 设置 Namespace 配额、Kueue Queue、Priority 和最大 Worker 数；
- 在线服务与实验任务使用不同 Namespace、节点池和凭据。

## 21. 什么时候优先选择 Ray

优先评估 Ray：

- 团队以 Python 为主，需要统一数据、训练、Tune、批推理和在线服务；
- 工作流包含多种动态 Actor/模型角色；
- 需要把 CPU 数据处理与 GPU 阶段流水化；
- 后训练需要协调 Rollout、Reward、Reference 和 Policy；
- 一个在线应用由多个可独立扩缩的 Python 推理步骤组成；
- 多机 vLLM/SGLang 需要 Ray Serve LLM 的编排能力。

不应默认选择 Ray：

- 只有一个单机 vLLM 服务；
- 固定拓扑预训练已经由 Slurm、Trainer/JobSet 或原生 Launcher 稳定承载；
- 主要需求是复杂 SQL、Lakehouse 表维护或持续有状态流处理；
- 团队无法承担 Ray、KubeRay、Kubernetes 和模型框架四层版本矩阵；
- 只是希望用一个工具掩盖数据、Checkpoint、网络和调度问题。

## 22. 推荐落地顺序

### 阶段 1：批任务

- KubeRay Operator + 独立 `RayJob`；
- CPU/GPU Worker Group 与对象存储；
- Ray Data 小规模批量推理；
- 日志、Dashboard、Prometheus 和结束回收。

### 阶段 2：训练

- Ray Train + PyTorch/FSDP 或 DeepSpeed；
- Kueue 固定规模准入；
- 分布式 Checkpoint 和节点故障演练；
- Ray Data 最后一公里数据供给。

### 阶段 3：推理

- `RayService` 管理组合式应用；
- 先做单模型 vLLM 基线，再评估 Ray Serve LLM；
- 请求队列、Replica、Ray Pod 和节点四层容量模型；
- Canary、模型预热和 Head/GCS 故障演练。

### 阶段 4：后训练与高级弹性

- Rollout/Reward/Policy 角色建模；
- Tune、Spot、弹性 RayJob；
- P/D 分离、多机 MoE 和权重同步；
- 按 GPU-hour、Goodput 和恢复成本持续优化。

## 23. 上线检查清单

- [ ] 明确 Ray、Kubernetes、训练框架和推理引擎的职责边界；
- [ ] 批任务使用 RayJob、在线服务使用 RayService，生命周期没有混用；
- [ ] Head 不承担无意的 GPU 工作，并有独立资源和故障策略；
- [ ] Worker Group 按 CPU/GPU/网络/模型角色拆分；
- [ ] Kueue 准入、Ray Autoscaler 和 Node Autoscaler 上下限一致；
- [ ] Placement Group 及 TP/PP 拓扑用真实硬件验证；
- [ ] Object Store、Spill、`/dev/shm` 和本地缓存完成容量测试；
- [ ] Checkpoint 位于外部持久存储，Worker/Head/节点故障可恢复；
- [ ] Ray Data 没有因 Block、小文件或背压让 GPU 空等；
- [ ] Ray Serve 指标能关联到 vLLM/SGLang 与 GPU 指标；
- [ ] Dashboard、GCS、Client 和 Job API 不向不可信网络开放；
- [ ] Ray、KubeRay、Python、CUDA、PyTorch 和引擎版本已锁定；
- [ ] 多租户不共享无安全边界的 RayCluster；
- [ ] 有不使用 Ray 的基线，能够量化它带来的收益和运维成本。

## 官方资料

- [Ray on Kubernetes](https://docs.ray.io/en/latest/cluster/kubernetes/)
- [KubeRay](https://ray-project.github.io/kuberay/)
- [Ray Data](https://docs.ray.io/en/latest/data/data.html)
- [Ray Train](https://docs.ray.io/en/latest/train/overview.html)
- [Ray Train Fault Tolerance](https://docs.ray.io/en/latest/train/user-guides/fault-tolerance.html)
- [Ray Tune](https://docs.ray.io/en/latest/tune/)
- [Ray Serve Production Guide](https://docs.ray.io/en/latest/serve/production-guide/)
- [Ray Serve LLM](https://docs.ray.io/en/latest/serve/llm/)
- [Kueue RayJob Integration](https://kueue.sigs.k8s.io/docs/tasks/run/rayjobs/)
