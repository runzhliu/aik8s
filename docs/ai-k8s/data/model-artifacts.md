---
title: 模型格式、制品供应链与分发
description: 管理 safetensors、GGUF、量化模型、OCI Model Artifact、Registry、缓存、签名和冷启动
status: evolving
last_reviewed: 2026-08-02
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

参考：[KServe Local Model Cache](https://kserve.github.io/website/docs/model-serving/generative-inference/modelcache/localmodel)

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

## 十一、冷启动预算

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

## 十二、完整性和签名

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

## 十三、权限模型

- 模型发现、读取、发布、晋级和删除使用不同权限；
- 生产 Pod 只读特定已审批 Digest；
- 下载凭据通过 Workload Identity 或短期 Secret 获取；
- Registry 管理员不能自动成为模型审批人；
- 外部模型先进入隔离扫描区；
- 模型许可证和数据使用限制进入元数据；
- 审计谁让哪个模型版本进入哪个环境。

## 十四、垃圾回收

清理对象包括：

- 失败或未审批的转换制品；
- Registry 中无引用 Layer/Manifest；
- 节点本地过期模型；
- 未再使用的 Adapter；
- 历史评估与基准证据；
- 回滚窗口外的模型版本。

删除前检查线上部署、Canary、回滚策略、训练血缘和合规保留。缓存可以按 LRU 清理，权威制品不能用同一策略。

## 十五、可观测性

至少记录：

- 模型 URI、Digest、大小和分片数；
- 下载队列、吞吐、失败和重试；
- 每节点缓存占用、命中和淘汰；
- 镜像/Modelcar 拉取时间；
- 权重加载、GPU 传输和预热时间；
- Registry/对象存储限流与错误；
- Digest/签名验证失败；
- 每次扩容产生的下载流量与成本。

## 十六、常见故障

| 现象 | 可能原因 |
| --- | --- |
| Init:OOMKilled | Storage Initializer 内存不足 |
| 多副本同时卡住 | Registry/对象存储限流或出口饱和 |
| 缓存显示 Ready 但 Pod 找不到 | HostPath、UID、URI 或节点组不一致 |
| 同一 Tag 行为不同 | Tag 漂移或拉取策略不同 |
| 权重能加载但输出错误 | Tokenizer、配置、量化 Scale 不匹配 |
| 新硬件无法启动 | Engine/量化制品绑定旧架构 |
| 节点磁盘爆满 | Layer、模型缓存和日志 GC 失效 |
| 回滚失败 | 旧模型或对应 Runtime 已被清理 |

## 十七、生产检查清单

- [ ] 模型版本关联权重、Tokenizer、配置、量化和评估。
- [ ] 所有生产部署使用不可变 Revision 或 Digest。
- [ ] 外部模型经过许可证、格式、自定义代码和安全审查。
- [ ] 每个硬件/引擎组合有明确兼容元数据。
- [ ] 模型下载、加载和预热分阶段计时。
- [ ] 大规模扩容不会把 Registry 或对象存储压垮。
- [ ] 节点缓存有容量、水位、淘汰和重建策略。
- [ ] 签名验证与模型审批是不同控制层。
- [ ] 旧版本在回滚窗口内保持可部署。
- [ ] 制品、缓存和评估证据分别有保留策略。

## 延伸阅读

- [KServe Storage Overview](https://kserve.github.io/website/docs/model-serving/storage/overview)
- [KServe OCI Modelcars](https://kserve.github.io/website/docs/model-serving/storage/providers/oci)
- [KServe Local Model Cache](https://kserve.github.io/website/docs/model-serving/generative-inference/modelcache/localmodel)
- [Safetensors](https://huggingface.co/docs/safetensors/main/index)
- [OCI Image Specification](https://github.com/opencontainers/image-spec)
- [Sigstore Cosign](https://docs.sigstore.dev/cosign/signing/signing_with_containers/)
