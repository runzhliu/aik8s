---
title: 模型格式、制品供应链与分发
description: 管理模型格式、OCI 制品、跨地域复制、P2P 分发、节点缓存、流式加载、签名和冷启动
status: evolving
last_reviewed: 2026-08-03
---

# 模型格式、制品供应链与分发

模型权重不是一个随手复制的大文件。生产平台需要把模型、Tokenizer、配置、量化参数、推理引擎兼容性、许可证、评估和签名组成不可变制品，并确保它能在目标 Kubernetes 节点上高效、安全地分发。

## 一、模型制品包含什么

一个可部署模型版本通常包括：

- 权重分片和索引；
- `config.json`、Tokenizer、Chat Template；
- Generation/Serving 默认参数；
- 量化配置、Scale 和校准信息；
- Adapter/LoRA；
- 自定义模型代码或 Remote Code 审查结果；
- 目标框架、引擎和硬件兼容信息；
- 许可证、来源和使用限制；
- 离线评估、安全评估和性能基准；
- SHA-256/OCI Digest、签名、SBOM/Model BOM；
- 发布、审批和回滚状态。

模型 Registry 的元数据和权重存储可以分开，但必须通过不可变 URI 和 Digest 关联。

## 二、常见模型格式

| 格式 | 典型用途 | 主要特点 | 注意事项 |
| --- | --- | --- | --- |
| safetensors | PyTorch/Transformers 训练与推理 | 不依赖 Pickle 执行、支持分片和部分读取 | 仍需验证来源、配置和外部代码 |
| PyTorch `.bin/.pt` | 旧模型、Checkpoint | 生态广 | Pickle 类格式可能执行代码，不直接信任外部文件 |
| GGUF | llama.cpp 等本地/边缘推理 | 模型、Tokenizer 和量化元数据集中 | 与数据中心引擎支持程度不同 |
| ONNX | 跨框架推理 | 图和算子标准化 | Opset、动态形状和自定义算子兼容性 |
| TensorRT Engine | NVIDIA 优化推理 | 针对硬件和构建环境高度优化 | Compute Capability、TensorRT/驱动版本敏感 |
| Neuron/其他编译制品 | AI ASIC | 减少部署时编译 | 通常绑定芯片、编译器和输入 Shape |
| Checkpoint | 继续训练 | 包含优化器、RNG、调度等状态 | 不等于可直接上线的推理制品 |

safetensors 降低了反序列化执行风险，但模型仓库还可能包含 Python Remote Code、Tokenizer 扩展和恶意配置，不能把格式安全等同于整个供应链安全。

参考：[Safetensors](https://huggingface.co/docs/safetensors/main/index)

## 三、基础模型、微调和量化的关系

```text
基础模型 Revision
  ├── 完整微调权重
  ├── LoRA / Adapter
  ├── 合并后的部署权重
  └── 多种量化或硬件编译制品
        ├── BF16 / FP16
        ├── FP8
        ├── INT8
        ├── INT4 / AWQ / GPTQ
        └── GGUF / 厂商 Engine
```

每个派生制品都应记录父模型 Digest、转换工具、命令、校准数据和质量变化。只记录一个模型名称无法重现部署。

## 四、模型版本标识

不推荐：

```text
s3://models/chat/latest/
hf://org/model-main
registry.example.com/model:latest
```

推荐使用不可变标识：

```text
s3://models/chat/2026-08-02/manifest.json#sha256=...
hf://org/model@<commit-sha>
registry.example.com/models/chat@sha256:<digest>
```

业务别名如 `chat-production` 可以指向不可变版本，但别名变更本身必须审计并可快速回退。

## 五、制品 Manifest

概念示例：

```yaml
apiVersion: platform.example.com/v1alpha1
kind: ModelArtifact
metadata:
  name: chat-model-2026-08-02
spec:
  source:
    baseModel: hf://org/base-model@commit-sha
    trainingRun: mlflow://experiments/42/runs/run-id
  artifact:
    uri: oci://registry.example.com/models/chat@sha256:digest
    format: safetensors
    precision: fp8
    sizeBytes: 73400320000
  compatibility:
    engines: [vllm, sglang]
    accelerators: [nvidia-hopper]
  evidence:
    evaluation: s3://evidence/chat/eval-v12.json
    benchmark: s3://evidence/chat/perf-h100-v4.json
    signature: cosign://registry.example.com/models/chat@sha256:digest
```

这不是标准 Kubernetes API，而是一种元数据契约示例。可以由 Kubeflow Hub、MLflow、OCI Annotation 或内部 Catalog 实现。

## 六、存储方式

### 对象存储

优点：容量大、耐久、生命周期和权限成熟。缺点：每个 Pod 直接下载会制造出口尖峰和冷启动延迟。

适合权威模型副本和 Checkpoint，不一定适合直接作为运行时随机读取层。

### Hugging Face Hub 或模型 Hub

适合发现和上游同步。生产环境应：

- 固定 Commit Revision；
- 镜像或同步到受控存储；
- 使用短期凭据；
- 记录许可证和扫描结果；
- 避免所有生产 Pod 直接依赖外部公网。

### 共享文件系统/PVC

多个 Pod 可共享已下载模型，但要验证元数据性能、并发读取、可用区和缓存一致性。单个 RWO PVC 不能直接满足跨节点多副本。

### OCI Registry

模型作为 OCI Artifact 或 Modelcar 可以复用 Registry 的 Digest、权限、镜像分发和节点缓存。需要评估大 Layer、垃圾回收、签名、Registry 带宽和 Snapshotter。

## 七、KServe Modelcar

KServe 支持用 `oci://` 指向包含模型数据的 OCI Image：

```dockerfile
FROM busybox
RUN mkdir -p /models && chmod 775 /models
COPY model/ /models/
```

```yaml
apiVersion: serving.kserve.io/v1beta1
kind: InferenceService
metadata:
  name: example-model
spec:
  predictor:
    model:
      modelFormat:
        name: huggingface
      storageUri: oci://registry.example.com/models/example@sha256:replace
```

使用 Digest 避免 Tag 漂移。Modelcar 的进程命名空间、UID、缓存和安全行为要按目标 KServe 版本验证。

参考：[KServe OCI Modelcars](https://kserve.github.io/website/docs/model-serving/storage/providers/oci)

## 八、本地模型缓存

模型冷启动路径：

```text
远端 Registry/对象存储
  → 节点本地 NVMe/镜像缓存
  → Pod Volume/Modelcar
  → CPU 内存
  → GPU HBM
  → 引擎预热和 Prefix/KV Cache
```

每层缓存不同：

| 缓存 | 生命周期 | 价值 |
| --- | --- | --- |
| Registry/对象存储 CDN | 平台级 | 减少跨地域流量 |
| 节点镜像 Layer | 节点级 | 复用 OCI 模型层 |
| LocalModelCache/NVMe | 节点级 | 避免重复下载权重 |
| Page Cache | OS 级 | 加速相同文件读取 |
| GPU 权重 | Pod/进程级 | 模型真正可执行 |
| Prefix/KV Cache | 请求级 | 减少重复计算 |

不能用 Prefix Cache 命中率衡量模型权重缓存，也不能把 Pod Running 当成 GPU 权重已经加载。

## 九、KServe LocalModelCache

KServe LocalModelCache 可以在目标节点预下载模型，并维护节点缓存状态。典型对象包括 `LocalModelNodeGroup`、`LocalModelCache` 和 `LocalModelNode`。

需要关注：

- 目标节点和 GPU 型号；
- 本地路径、HostPath 与 UID/GID；
- 模型 URI 必须与 InferenceService 一致；
- 缓存下载 Job 的 CPU、内存和网络；
- 磁盘水位、淘汰和失败重试；
- 节点替换和扩容时的预热；
- 缓存 Ready 是否进入 Pod/Gateway Readiness。

截至本页复核日期，LocalModel API 仍是 `v1alpha1`，并作为 KServe 的可选组件安装；官方安装文档说明当前仅支持 `InferenceService`，`LLMInferenceService` 支持仍在规划中。生产采用前应固定 KServe/LocalModel 版本，不要仅因为 CRD 名称稳定就假定接口已经 GA。

参考：[KServe Local Model Cache](https://kserve.github.io/website/docs/model-serving/generative-inference/modelcache/localmodel)、[LocalModel Installation](https://kserve.github.io/website/docs/install/localmodel-install)

## 十、分发策略

### 每个 Pod 下载

最简单，但大规模扩容会重复传输和消耗对象存储请求。适合小模型或低副本。

### Init Container 下载到 PVC/emptyDir

逻辑清晰，支持多种存储；但 Pod 每次重建可能重新下载，且 Init Container 资源不足会 OOM。

### DaemonSet/Controller 预热本地盘

适合大模型和固定 GPU 节点池。需要数据局部性调度、缓存状态和清理控制器。

### OCI Layer/Modelcar

复用 Registry 与节点镜像缓存，Digest 和签名自然；需要处理超大 Layer、解压、GC 和 Runtime 支持。

### P2P 分发

大规模节点可以从已有缓存节点分发，降低中心存储热点。增加了 Peer 发现、完整性、流控和安全复杂度，只在规模确实需要时采用。

### 流式或惰性加载

引擎可以从 HTTP/S3 等远端源并发读取 Tensor，或通过特定格式边下载边反序列化，减少完整落盘和 CPU 内存峰值。它优化的是“远端字节进入引擎/GPU”的路径，不能替代不可变版本、区域复制、权限、缓存和回滚。

## 十一、主流生产分层

当前主流做法不是在对象存储、OCI、PVC、P2P 中四选一，而是让它们承担不同层次：

```text
训练 / 转换 / 量化流水线
        ▼
Model Registry / Catalog
  记录版本、Digest、血缘、评估、兼容性和审批
        ▼
权威制品层
  Object Storage 或 OCI Registry
        ▼
区域分发层
  跨地域复制、区域 Registry/Bucket、CDN/Seed
        ▼
集群分发层
  Storage Initializer / 共享文件 / P2P / 预热控制器
        ▼
节点缓存层
  OCI Layer Cache / LocalModelCache / 本地 NVMe
        ▼
运行时加载层
  mmap / Page Cache / 并行反序列化 / Streaming
        ▼
GPU HBM + Engine Warmup
        ▼
Traffic Ready
```

推荐把控制面与数据面分开：

| 层 | 保存什么状态 | 是否传输大模型字节 |
| --- | --- | --- |
| Model Registry/Catalog | 模型版本、审批、评估、血缘和部署别名 | 通常不直接承担大规模运行时下载 |
| 发布/放置控制器 | 哪个版本应进入哪些地域、集群和节点组 | 触发复制与预热，不一定代理字节 |
| 对象/OCI 存储 | 不可变权威制品与 Digest | 是，作为回源和跨地域复制源 |
| P2P/缓存系统 | Piece、Peer、节点缓存和下载状态 | 是，承担大规模集群内分发 |
| Serving Controller/Gateway | Pod、模型 Ready、流量和版本状态 | 否，不应把模型字节放进 Kubernetes API |

这套分层避免让一个系统同时承担制品治理、跨地域复制、节点缓存和请求发布。最常见的生产组合是：**对象存储或 OCI Registry 作为权威源，区域内保留副本，发布前预热到 GPU 节点本地 NVMe；节点规模很大时再加入 P2P。**

## 十二、跨地域模型分发

多地域平台不应让每个 Pod 从中央 Bucket 或公网 Model Hub 跨 WAN 拉取。更稳健的路径是：

```text
Global Artifact Digest
  ├── Region A Registry/Bucket
  │     └── Cluster A Seed/Node Cache
  ├── Region B Registry/Bucket
  │     └── Cluster B Seed/Node Cache
  └── Region C Registry/Bucket
        └── Cluster C Seed/Node Cache
```

一次多地域发布建议经过以下状态：

1. `ArtifactApproved`：权威制品、签名和评估通过；
2. `RegionReplicated`：目标地域已存在相同 Digest；
3. `NodePreheated`：目标 GPU 节点组达到缓存覆盖率；
4. `EngineReady`：权重已经进入运行时并完成必要编译/预热；
5. `TrafficReady`：Gateway 才允许真实流量进入。

关键原则：

- 每个地域使用相同 Artifact Digest，不用会漂移的 Tag 同步；
- 复制模型 Manifest、权重分片、Tokenizer、配置、量化 Scale 和自定义代码的完整集合；
- 区域复制状态必须进入发布门禁，不由 Pod 启动时临时发现缺文件；
- 严格 SLO 的地域保留当前版本和上一版本的 Warm Cache；
- 复制失败只阻止新地域接流量，不破坏已经运行的旧版本；
- 用区域内身份读取区域副本，避免向所有集群分发一个全局长期 Access Key；
- 统计跨地域复制流量与集群内分发流量，二者成本和容量归属不同。

OCI Registry 的 Layer 去重只对内容完全相同的 Layer 有效。一个权重分片中的少量数值变化也会产生新的 Digest，因此不要把增量同步收益建立在“模型版本相近”的直觉上；应根据真实分片和 Registry 行为测量。

## 十三、百节点与 TB 级 P2P 分发

直接回源的理论流量近似为：

```text
源站读取量 ≈ 模型大小 × 同时冷启动的节点数
```

如果一个模型在 200 个节点同时冷启动，任何源站、出口、ToR 或对象存储限流都可能成为长尾。P2P 把第一次回源得到的 Piece 继续提供给其他节点，源站主要承担每个区域或 P2P 域的首份数据，后续流量在 Peer 之间扩散。

一种分层拓扑是：

```text
Region Object Storage / OCI Registry
        ▼
Regional Seed Peer
        ▼
Rack / Network Block Peers
        ▼
GPU Node Local NVMe
```

Dragonfly 等系统会把文件拆成 Piece，Scheduler 根据 Peer 和负载选择父节点，Seed Peer 负责首次回源。它适合大量节点同时需要相同模型、数据集或镜像的场景。[Dragonfly](https://d7y.io/docs/)

P2P 上线前要明确：

- P2P 域按地域、机房、Rack 还是租户划分；
- Seed、Scheduler 和 Peer 故障时能否安全回源；
- 每节点上传/下载并发、磁盘 IO 和网络带宽上限；
- 是否避免跨 Rack/跨区 Peer 流量反而增加网络成本；
- Piece、完整文件和最终 Artifact Digest 如何逐级校验；
- Peer 是否可能向未授权租户提供模型内容；
- 下载取消、部分 Piece、节点重启和缓存淘汰如何清理；
- 发布前主动 Preheat 与请求触发的 On-demand 下载怎样分工；
- P2P 遥测能否关联 Model Digest、Region、Node 和发布批次。

P2P 是分发数据面，不是权威 Registry。Peer Cache 可以随时丢失和重建，模型审批、签名、生命周期与回滚仍由上层制品系统负责。

## 十四、分发完成不等于模型可服务

一个模型从权威存储到真正提供请求，至少有四个不同状态：

| 状态 | 含义 | 常见错误判断 |
| --- | --- | --- |
| Artifact Ready | 权威存储中制品完整且已审批 | 误认为所有地域已经可用 |
| Node Cached | 文件已在目标节点本地盘并通过校验 | 误认为已经占用 GPU |
| Engine Ready | 引擎已经加载权重、分配 HBM 并完成初始化 | 误把 Pod Running 当作这一状态 |
| Traffic Ready | Warmup、健康检查和路由注册完成 | 还未预热就开始测 TTFT |

流式加载或 Tensorizer 等方案可以从 HTTP/S3 并行读取 Tensor，降低完整下载和反序列化时间，某些实现还能降低 CPU 内存占用。[vLLM Tensorizer](https://docs.vllm.ai/en/latest/models/extensions/tensorizer/)

它们的代价包括：

- 模型格式和推理引擎绑定更深；
- 远端存储延迟可能进入启动甚至首次访问路径；
- 网络中断、重试和部分加载的故障语义更复杂；
- 转换制品需要与原始 safetensors 一起做血缘、质量和兼容管理；
- 不能因为支持 Streaming 就取消区域副本和本地缓存。

对于严格在线 SLO，更稳妥的默认值仍是先把完整、校验过的模型放到本地 NVMe，再由引擎并行加载；Streaming 用于经过基准证明的启动优化或长尾模型。

## 十五、训练与推理的分发路径不同

| 维度 | 训练/Checkpoint | 在线推理权重 |
| --- | --- | --- |
| 访问模式 | 大规模读 + 周期性写 | 基本只读，发布时集中读 |
| 常见权威层 | 对象存储、并行文件系统 | 对象存储、OCI Registry、Model Hub 镜像 |
| 本地化 | 数据集/基础模型缓存，Checkpoint 暂存 | GPU 节点 NVMe 热模型缓存 |
| 一致性重点 | 原子 Checkpoint、分片完整、恢复点 | 不可变 Digest、所有副本加载同一版本 |
| 扩展方式 | Shard、并行 IO、异步上传 | 区域复制、预热、P2P、并行加载 |
| 回收策略 | 保留恢复点和训练血缘 | 当前/上一版本保热，长尾按 LRU |

训练 Checkpoint 不应被简单套用推理 Modelcar 流程。它可能由所有 Rank 并行写入，包含优化器和 RNG 状态，并要求一个完成标记或 Manifest 原子发布。推理制品则应由训练/转换流水线晋级为不可变只读版本后再进入分发。

基础模型与 Adapter 也可以分层：大型基础模型长期驻留节点，较小的 LoRA/Adapter 独立版本化并按需分发。仍需验证 Adapter 与基础模型 Digest、Tokenizer、引擎版本和租户权限，不能只按文件名拼装。

## 十六、模型发布状态机

一个可控的模型发布流程可以表示为：

```text
Build
  → Scan / Evaluate
  → Sign
  → Replicate Regions
  → Preheat Nodes
  → Load Engine
  → Warmup
  → Shadow
  → Canary
  → Promote
  → Drain Old Version
  → Retain for Rollback
```

发布控制器或流水线应检查：

- Artifact Digest 与审批记录一致；
- 目标地域复制完成且校验成功；
- 目标节点缓存覆盖率达到门槛；
- 新旧模型需要的 Runtime、GPU 和量化格式兼容；
- Engine Ready 数量满足最小可用容量；
- Shadow/Canary 的质量、TTFT、TPOT、错误率和成本达标；
- 回滚版本仍保留区域副本、节点缓存和兼容 Runtime；
- Drain 完成前不清理旧模型和长连接。

不要让 Autoscaler 在流量峰值到来后才第一次下载几百 GB 权重。在线推理的节点供给、模型预热和副本扩容需要联合规划；必要时保留空 GPU 节点或 Warm Pool。

## 十七、容量与带宽规划

单节点下载时间可以粗略估算为：

```text
下载时间下限 ≈ 模型大小
              / min(源站分配带宽, 网络带宽, 磁盘写入, Peer 供给带宽)
              + 校验与文件落盘时间
```

大规模发布还要计算：

```text
源站放大倍数 = 源站实际发送字节 / 模型逻辑大小
缓存覆盖率   = 已缓存目标 Digest 的合格节点 / 目标节点总数
有效预热率   = 发布时真正命中缓存的副本 / 新启动副本总数
```

本地盘不能只按“一个模型大小”规划：

```text
本地缓存预算 = 当前生产模型
             + 回滚版本
             + Canary/下一版本
             + 热门 Adapter
             + 下载临时空间
             + 容器镜像与日志
             + GC 安全水位
```

模型 Shard 也有权衡：过大的 Shard 降低元数据数量，但单片失败重试成本高、并发度低；过小的 Shard 会增加请求、文件系统元数据和打开文件压力。应让分片大小、引擎并行加载能力、对象存储 Multipart 和 P2P Piece 策略共同基准，而不是机械地统一文件大小。

## 十八、冷启动预算

```text
冷启动 = 节点供给
       + 驱动/设备组件就绪
       + 容器镜像拉取
       + 模型权重下载/挂载
       + 权重反序列化
       + CPU → GPU 传输
       + 图编译/Kernel Autotune
       + 引擎预热
       + Gateway 发现
```

对每一项测量 P50/P95，并记录缓存冷/热两种情况。一个 100 GiB 模型即使远端带宽为 10 Gbit/s，理论传输下限也超过一分钟，实际还包括协议、并发、解压和存储瓶颈。

## 十九、完整性和签名

推荐链路：

```text
受控训练/转换
  → 生成 Manifest 与评估证据
  → 计算 Digest
  → 上传不可变存储/OCI Registry
  → 签名与 Attestation
  → Registry 审批
  → Admission/部署控制器校验
  → 节点下载后再次校验
```

不仅签名权重，还要关联 Tokenizer、配置、量化 Scale 和自定义代码。Digest 一致只能证明内容未变，不能证明模型质量或来源可信。

## 二十、权限模型

- 模型发现、读取、发布、晋级和删除使用不同权限；
- 生产 Pod 只读特定已审批 Digest；
- 下载凭据通过 Workload Identity 或短期 Secret 获取；
- Registry 管理员不能自动成为模型审批人；
- 外部模型先进入隔离扫描区；
- 模型许可证和数据使用限制进入元数据；
- 审计谁让哪个模型版本进入哪个环境。

## 二十一、垃圾回收

清理对象包括：

- 失败或未审批的转换制品；
- Registry 中无引用 Layer/Manifest；
- 节点本地过期模型；
- 未再使用的 Adapter；
- 历史评估与基准证据；
- 回滚窗口外的模型版本。

删除前检查线上部署、Canary、回滚策略、训练血缘和合规保留。缓存可以按 LRU 清理，权威制品不能用同一策略。

## 二十二、可观测性

至少记录：

- 模型 URI、Digest、大小和分片数；
- 跨地域复制进度、延迟、积压和失败；
- 每个地域的 Artifact 可用性和回源路径；
- 下载队列、吞吐、失败和重试；
- 每节点缓存占用、命中和淘汰；
- 目标节点缓存覆盖率、有效预热率和回源放大倍数；
- P2P Seed/Peer 数、Piece 命中、回源字节和跨故障域流量；
- 镜像/Modelcar 拉取时间；
- Artifact Ready、Region Replicated、Node Cached、Engine Ready 和 Traffic Ready 各阶段时间；
- 权重反序列化、CPU 内存峰值、CPU→GPU 传输、图编译和预热时间；
- Registry/对象存储限流与错误；
- Digest/签名验证失败；
- 每次扩容产生的下载流量与成本。

所有指标至少带上 `model_digest`、`region`、`cluster_id`、`node`、`source` 和 `release_id` 中适用的维度。模型名称或 Tag 不足以区分实际字节版本。

## 二十三、常见故障

| 现象 | 可能原因 |
| --- | --- |
| Init:OOMKilled | Storage Initializer 内存不足 |
| 多副本同时卡住 | Registry/对象存储限流或出口饱和 |
| 某地域发布一直 Pending | 区域复制未完成、Digest 不一致或目标权限错误 |
| P2P 速度反而更慢 | Seed 不足、Peer 跨区、磁盘瓶颈或限流配置不当 |
| P2P 控制面故障 | 新下载无法调度；需要已有缓存继续服务并安全回源 |
| 缓存显示 Ready 但 Pod 找不到 | HostPath、UID、URI 或节点组不一致 |
| 文件存在但 Engine 不 Ready | 分片缺失、格式/引擎不兼容、CPU 内存或 HBM 不足 |
| 同一 Tag 行为不同 | Tag 漂移或拉取策略不同 |
| 权重能加载但输出错误 | Tokenizer、配置、量化 Scale 不匹配 |
| 新硬件无法启动 | Engine/量化制品绑定旧架构 |
| 节点磁盘爆满 | Layer、模型缓存和日志 GC 失效 |
| Streaming 首次请求抖动 | 远端读取、惰性 Page Fault 或未完成 Engine Warmup |
| 回滚失败 | 旧模型或对应 Runtime 已被清理 |

## 二十四、生产检查清单

- [ ] 模型版本关联权重、Tokenizer、配置、量化和评估。
- [ ] 所有生产部署使用不可变 Revision 或 Digest。
- [ ] 外部模型经过许可证、格式、自定义代码和安全审查。
- [ ] 每个硬件/引擎组合有明确兼容元数据。
- [ ] 模型下载、加载和预热分阶段计时。
- [ ] 每个生产地域拥有同一 Digest 的受控副本，不依赖 Pod 跨 WAN 回源。
- [ ] 区域复制、节点预热、Engine Ready 和 Traffic Ready 是不同发布门禁。
- [ ] 大规模扩容不会把 Registry 或对象存储压垮。
- [ ] 百节点级并发下载已评估 P2P/Seed、回源降级、流控和故障域。
- [ ] 节点缓存有容量、水位、淘汰和重建策略。
- [ ] 调度器或 Serving Controller 能识别目标节点是否缓存指定 Digest。
- [ ] 当前、回滚和 Canary 版本能同时放入本地缓存预算。
- [ ] Streaming/Lazy Loading 经过冷/热缓存基准和远端故障测试。
- [ ] 训练 Checkpoint 与只读推理制品使用不同的一致性和保留策略。
- [ ] 基础模型与 Adapter 的 Digest、兼容性和租户权限可以联合校验。
- [ ] 签名验证与模型审批是不同控制层。
- [ ] 旧版本在回滚窗口内保持可部署。
- [ ] 制品、缓存和评估证据分别有保留策略。

## 延伸阅读

- [KServe Storage Overview](https://kserve.github.io/website/docs/model-serving/storage/overview)
- [KServe OCI Modelcars](https://kserve.github.io/website/docs/model-serving/storage/providers/oci)
- [KServe Local Model Cache](https://kserve.github.io/website/docs/model-serving/generative-inference/modelcache/localmodel)
- [KServe LocalModel Installation](https://kserve.github.io/website/docs/install/localmodel-install)
- [Hugging Face Hub 下载与缓存](https://huggingface.co/docs/huggingface_hub/en/guides/download)
- [Dragonfly](https://d7y.io/docs/)
- [vLLM Tensorizer](https://docs.vllm.ai/en/latest/models/extensions/tensorizer/)
- [Safetensors](https://huggingface.co/docs/safetensors/main/index)
- [OCI Image Specification](https://github.com/opencontainers/image-spec)
- [Sigstore Cosign](https://docs.sigstore.dev/cosign/signing/signing_with_containers/)
