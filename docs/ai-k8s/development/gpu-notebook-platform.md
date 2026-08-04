---
title: 大模型时代的 GPU Notebook 平台与存储选型
description: 从 JupyterHub、Kubeflow 和托管 Workbench，到整卡、MIG、共享 GPU、用户 Home、对象存储与本地缓存的生产选型
status: evolving
last_reviewed: 2026-08-03
---

# 大模型时代的 GPU Notebook 平台与存储选型

大模型时代的 Notebook 已经不只是浏览器里的 Python 编辑器。它往往同时承载 JupyterLab、VS Code、终端、Git、模型下载、数据探索、LoRA 微调和远程任务提交，背后还可能占用几十到数百 GiB 内存、一张或多张昂贵 GPU，以及数百 GiB 的临时缓存。

因此，Notebook 平台的真正选型对象不是某个 Web UI，而是一套**交互式开发工作区**：身份、镜像、计算规格、GPU 隔离、持久目录、数据访问、缓存、空闲回收和任务移交必须一起设计。

## 1. 先给结论

### 推荐的默认架构

对大多数已经运行 Kubernetes、但不需要完整 Kubeflow 套件的团队，第一版建议采用：

```text
JupyterHub + KubeSpawner
        │
        ├─ 受控 CPU / 共享 GPU / MIG / 整卡规格
        ├─ 每用户一个 RWO SSD PVC，保存 Home 与少量代码
        ├─ 对象存储，保存数据集、模型、Checkpoint 和 Artifact
        ├─ 本地 NVMe，保存模型缓存、数据缓存与临时文件
        └─ Job / TrainJob / RayJob，承接长时间训练任务
```

这条路线组件少、边界清晰，适合先建立多用户 GPU 开发入口。

### 什么时候换成其他方案

| 条件 | 优先方案 | 原因 |
| --- | --- | --- |
| 只需要多用户 Jupyter/VS Code、自助规格和基础认证 | JupyterHub on Kubernetes | 控制面轻，用户 PVC、资源 Profile 和 Idle Culler 已覆盖核心需求 |
| 已使用 Kubeflow Profiles、Pipelines、Trainer、Katib | Kubeflow Notebook/Workspace | 与 Kubeflow 身份、Namespace、Pipeline 和平台 UI 集成更完整 |
| 团队很小、完全单云、没有平台运维人力 | 云托管 Workbench | 云 IAM、镜像、实例和存储集成开箱即用 |
| 已在 OpenShift 且要求商业支持和统一治理 | Red Hat OpenShift AI 等发行版 | 沿用企业身份、Operator、审计和支持体系 |
| 只有少数可信用户、短期验证 | 受控 VM 或单用户 Workbench | Kubernetes 多租户控制面的投入可能暂时不划算 |

不建议直接给每位用户创建一个普通 `Deployment + Service + Ingress`。这种自建方式很快会重复实现认证、停止/恢复、PVC 生命周期、URL 路由、规格选择、镜像治理和审计。

### 2026 年选择 Kubeflow 时必须注意

截至 2026 年 8 月，Kubeflow 官方已经说明 Notebooks v1 进入维护模式，并计划在 2026 年底结束支持；Workspaces v2 的测试清单仍只适合评估，尚未准备好用于生产。因此：

- 已有 Notebooks v1 平台应制定 Workspace API、PVC、镜像和访问入口的迁移计划；
- 新建长期平台不能只根据旧教程选 v1，应确认发行版对 v2 的支持时间和迁移承诺；
- Workspaces v2 可以建立 PoC，但当前不应把 Alpha 版本当成唯一生产入口；
- 需要立即上线时，可选择版本成熟的 JupyterHub，或带明确支持周期的商业发行版/托管服务。

参考：[Kubeflow 26.03.1 发布说明](https://blog.kubeflow.org/kubeflow-26.03-release/)、[Kubeflow Notebooks Overview](https://www.kubeflow.org/docs/components/notebooks/overview/)

## 2. 先确定 Notebook 的职责边界

Notebook 适合：

- 数据探索、可视化和小样本验证；
- Prompt、Tokenizer、模型结构和推理参数实验；
- 在单卡或小规模数据上调试训练代码；
- 生成任务配置并提交到训练、批处理或 Pipeline 系统；
- 查看实验指标、日志、Checkpoint 和评估结果。

Notebook 不应承担：

- 持续数小时或数天、必须可靠恢复的正式训练；
- 需要 Gang Scheduling 的多节点分布式训练；
- 生产在线推理服务；
- 数据集、模型和 Checkpoint 的唯一持久副本；
- 直接执行生产发布或持有集群管理员权限。

推荐的交接链路是：

```text
Notebook 中调试代码
        │
        ├─ Git 提交代码与配置
        ├─ 构建不可变镜像
        ├─ 数据和模型使用版本化 URI
        ▼
Job / TrainJob / RayJob / Pipeline
        │
        ├─ Kueue 准入、配额与优先级
        ├─ Checkpoint 与实验追踪
        ▼
模型注册、评估、GitOps 发布
```

这样 Idle Culler 停止 Notebook 时，不会误杀正式训练；Notebook 损坏也不会破坏生产作业。

## 3. 平台能力应该怎样拆分

```text
企业 IdP / OIDC / SSO
          │
Gateway / Ingress / Workspace UI
          │
Notebook 控制面
JupyterHub / Kubeflow / Managed Workbench
          │
Workspace Pod：JupyterLab / VS Code / Terminal
          │
          ├──────── 计算 ──────── CPU / Shared GPU / MIG / Full GPU
          ├──────── 持久层 ────── Per-user PVC / Team RWX / Object Storage
          ├──────── 加速层 ────── Local NVMe / Page Cache / Model Cache
          └──────── 执行层 ────── Job / Trainer / Ray / Pipeline / Kueue
```

评审产品时不要只看“能否启动 Jupyter”。至少要验证以下能力：

| 能力 | 必须回答的问题 |
| --- | --- |
| 身份 | 能否接企业 OIDC？用户、组、团队空间怎样映射？ |
| 工作区 | 能否停止后保留 Home？能否修改镜像和资源再启动？ |
| 计算目录 | 用户是否只能从管理员批准的规格中选择？ |
| GPU | 整卡、MIG 和共享资源是否使用不同名称、节点池和配额？ |
| 存储 | Home、数据、模型、缓存和 Scratch 是否有独立生命周期？ |
| 长任务 | 是否能从 Notebook 提交到受队列治理的执行系统？ |
| 安全 | ServiceAccount、出站网络、Secret 和 Pod 权限是否最小化？ |
| 成本 | 能否识别空闲 Kernel、停止 Pod、回收 GPU 又保留 PVC？ |
| 运维 | 镜像预拉取、升级、备份、审计和容量告警是否完整？ |

## 4. JupyterHub、Kubeflow 与托管 Workbench 怎么选

| 维度 | JupyterHub on Kubernetes | Kubeflow Notebook/Workspace | 云托管 Workbench | 自建 Pod 门户 |
| --- | --- | --- | --- | --- |
| 核心定位 | 多用户交互式计算 | 端到端 ML 平台中的开发入口 | 云厂商管理的个人/共享工作区 | 完全自定义 |
| 控制面复杂度 | 中 | 高 | 低 | 初期低、长期很高 |
| JupyterLab | 原生 | 原生 | 通常原生 | 自行集成 |
| VS Code/code-server | 自定义镜像和 Profile | 官方支持容器化 IDE | 取决于云服务 | 自行集成 |
| 多租户边界 | Authenticator、Spawner、Namespace、Policy | Profiles、RBAC、Namespace、Istio 等 | 云 IAM 与 Workspace/Space | 自行实现 |
| 自助资源规格 | `profileList` | UI 与资源配置 | 实例/应用规格 | 自行实现 |
| 每用户持久盘 | 成熟 | 成熟 | 服务自带 | 自行实现 |
| Pipeline/Trainer 集成 | 通过 API 和模板组合 | 同一平台内集成更深 | 云服务内集成 | 自行实现 |
| 可移植性 | 高 | 高，但组件较多 | 低到中 | 取决于实现 |
| 适合团队 | 希望保持平台简单 | 已有完整 Kubeflow 体系 | 单云且运维人力有限 | 有明确差异化产品需求 |

### JupyterHub

优点：

- 控制面职责集中，容易与现有 Kubernetes、OIDC 和 GPU 节点池组合；
- KubeSpawner 可以把镜像、CPU、内存、GPU、节点亲和性和挂载包装为少量 Profile；
- 每用户 PVC、Idle Culler、用户调度器、镜像预拉取等路径成熟；
- 不强迫团队同时引入完整 Pipeline、Serving 和 Service Mesh 套件。

限制：

- 团队空间、审批、项目模板、训练作业和实验血缘需要与其他系统组合；
- Helm Chart 大版本升级可能改变用户名、Pod 或 PVC 命名规则，升级前必须读迁移说明；
- 高级 Namespace 隔离和网络策略仍由平台团队设计。

官方优化建议包括镜像预拉取、用户占位 Pod、用户调度器、专用可伸缩节点池和 Idle Culler。大型 CUDA 镜像如果未预拉取，用户可能额外等待数分钟。参考：[Zero to JupyterHub 优化指南](https://z2jh.jupyter.org/en/stable/administrator/optimization.html)、[用户资源与 GPU Profile](https://z2jh.jupyter.org/en/latest/jupyterhub/customizing/user-resources.html)

### Kubeflow Notebook/Workspace

优点：

- JupyterLab、RStudio、VS Code code-server 采用统一 Workspace 模型；
- 与 Kubeflow Profiles、RBAC、Pipelines、Trainer、Katib 等组件协同；
- 平台管理员可以提供标准镜像，用户按团队 Namespace 使用环境；
- 适合把 Notebook 作为完整数据科学门户的一部分。

限制：

- 身份、Istio、Profile、准入策略、存储和升级链路更长；
- 默认 ServiceAccount 权限必须检查，不能因为方便提交 Pipeline 就授予宽泛 Kubernetes API 权限；
- 当前正处于 Notebooks v1 到 Workspaces v2 的代际切换期。

Kubeflow 官方提醒：Pod 启动后临时安装的包会随 Pod 消失，除非装在 PVC 目录中；生产环境更应使用固定的自定义镜像。参考：[Kubeflow Notebook 镜像要求](https://www.kubeflow.org/docs/components/notebooks/container-images/)

### 云托管 Workbench

典型产品包括 Vertex AI Workbench、SageMaker Studio JupyterLab/Spaces 和 Azure Machine Learning Compute Instance。

适合：

- 数据、身份、训练和制品都已经集中在同一云；
- 用户规模不大，平台团队不想维护 Hub、Ingress、Spawner 和镜像预拉取；
- 接受厂商的实例类型、网络、镜像、存储和计费模型。

需要重点验证：

- 工作区停止后哪些磁盘保留、如何扩容和备份；
- 私有与共享 Workspace 的权限边界；
- GPU 停止计费、Idle Shutdown 的判定方式；
- 是否支持自定义镜像、VPC 私网、代理、私有 Registry 和客户密钥；
- 数据是否跨区、跨账户或通过公网访问；
- 能否把正式训练移交到托管 Job，而不是长期占用 Workbench。

例如，当前 SageMaker Studio 的不同 Space 通常使用各自的 EBS 卷，Azure ML 明确建议不要把训练数据放在 Notebook 文件共享中，并建议把大量临时小文件放到本地临时目录。参考：[SageMaker Studio Spaces](https://docs.aws.amazon.com/sagemaker/latest/dg/studio-updated-spaces.html)、[Azure ML Compute Instance](https://learn.microsoft.com/en-us/azure/machine-learning/concept-compute-instance?view=azureml-api-2)、[Vertex AI Workbench](https://cloud.google.com/vertex-ai/docs/workbench/introduction)

## 5. 不要让用户自由填写任意规格

平台应发布一个版本化的资源目录，而不是暴露完整 Pod 表单。

| 示例规格 | 典型资源 | 使用场景 | 默认时限 |
| --- | --- | --- | --- |
| `cpu-small` | 2–4 CPU、8–16 GiB 内存 | 浏览代码、轻量数据分析 | 可长期停止/恢复 |
| `cpu-memory` | 8–16 CPU、64–128 GiB 内存 | Tokenize、CPU 预处理 | 8–12 小时空闲回收 |
| `gpu-shared-dev` | 共享 GPU Access、16–32 GiB 内存 | CUDA 冒烟、小模型调试 | 1–2 小时空闲回收 |
| `gpu-mig-small` | 一个 MIG Profile | 中小模型、需要显存隔离的多租户实验 | 2–4 小时空闲回收 |
| `gpu-full` | 一张整卡、足量 CPU/内存 | 大模型加载、LoRA、性能验证 | 1–2 小时空闲回收 |
| `gpu-multi` | 同节点 2–8 张整卡 | 单机并行调试 | 审批和最长运行时间 |

每个 Profile 至少固定：

- 容器镜像或可选镜像集合；
- CPU/内存 request 与 limit；
- GPU Resource Name 和数量；
- Node Selector、Taint/Toleration 和 RuntimeClass；
- Home PVC 类型与容量上限；
- 额外挂载、网络策略和 ServiceAccount；
- Idle Timeout、最长会话时间和成本归属标签。

`ResourceQuota` 用来限制团队资源总量，`LimitRange` 和准入策略用来阻止无边界的 CPU、内存和临时存储；GPU 总量还应进入团队配额、审批或队列体系。

## 6. 先估算显存，再选择 GPU

只看模型参数量通常会低估显存。最基本的权重估算是：

```text
模型权重显存 ≈ 参数量 × 每参数字节数

FP32 / TF32：约 4 Byte
FP16 / BF16：约 2 Byte
INT8：约 1 Byte，加量化元数据
INT4：约 0.5 Byte，加量化元数据
```

例如，7B 模型仅 BF16 权重理论值约为 14 GB，但实际加载还需要 CUDA Context、临时 Workspace、激活、KV Cache、Tokenizer 和框架开销。Notebook 里同时运行多个 Kernel 或模型时还会进一步增加占用。

| 场景 | 权重之外的主要显存 |
| --- | --- |
| 推理 | KV Cache、临时 Workspace、并发 Batch、长上下文 |
| 全量训练 | 梯度、优化器状态、激活、通信 Buffer；通常远高于仅加载权重 |
| LoRA/QLoRA | 基座权重、激活、Adapter、部分优化器状态；并不等于只需要 Adapter 大小 |
| 多模态 | 图像/音频 Encoder、预处理 Tensor 和更长序列 |
| 多 GPU | 并行策略的权重、激活、通信 Buffer 和可能的重复副本 |

正式采购前必须用目标模型、框架、精度、上下文和 Batch 实测峰值显存，不要只按参数量乘字节做容量承诺。

## 7. 整卡、MIG、Time-Slicing 和 MPS 怎么选

| 模式 | 显存隔离 | 故障隔离 | 性能稳定性 | 适合 Notebook | 主要代价 |
| --- | --- | --- | --- | --- | --- |
| 整卡独占 | 强 | 强 | 最好 | 大模型、训练、性能实验 | 小任务会浪费容量 |
| MIG | 硬件分区 | 硬件分区 | 较稳定 | 多租户中小模型和稳定显存规格 | 只支持部分 GPU，Profile 固定，重配需排空节点 |
| Time-Slicing | 无 | 无 | Best Effort | 同信任域的轻量开发和 CUDA 冒烟 | OOM/异常相互影响，延迟和吞吐不确定 |
| MPS | 有限的进程级控制 | 弱于 MIG | 依负载而定 | 同团队、小 Kernel 并发 | 配置、归因和兼容性更复杂 |

### 选择规则

```text
需要可预测性能或正式训练？ ── 是 ──> 整卡
             │
             否
             ▼
需要显存/故障隔离且硬件支持 MIG？ ── 是 ──> MIG
             │
             否
             ▼
是否同一信任域、可接受 Best Effort？ ── 是 ──> Time-Slicing 或 MPS PoC
             │
             否
             ▼
使用独立 GPU、独立节点池或更强隔离平台
```

NVIDIA 明确说明 Time-Slicing Replica 之间没有 MIG 所提供的显存和故障隔离，并且申请多个共享资源不代表得到成比例的算力。建议把共享资源改名为类似 `nvidia.com/gpu.shared`，并启用 `failRequestsGreaterThanOne`，让“1”明确表示一次共享访问而不是一张独占卡。参考：[NVIDIA GPU Time-Slicing](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/25.3/gpu-sharing.html)、[GPU Operator MIG](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/gpu-operator-mig.html)

共享 GPU 还需要额外监控物理卡级 XID、显存 OOM 和利用率。仅按 Pod 的扩展资源数量计费会误导用户，因为它不能代表实际获得的 GPU 时间。

## 8. 把 Notebook 数据分成八类

| 数据 | 是否需要持久 | 是否需要共享 | 推荐位置 |
| --- | --- | --- | --- |
| Notebook、脚本、配置 | 是 | 通过 Git 协作 | Git + 用户 Home PVC |
| Shell 配置、小型个人文件 | 是 | 否 | 每用户 RWO/RWOP PVC |
| Python/CUDA 运行环境 | 可复现即可 | 是 | OCI 镜像与 Lockfile |
| 团队共享小文件 | 是 | 是 | 受权限控制的 RWX 文件系统 |
| 原始数据集和训练分片 | 是，通常是权威副本 | 是 | 对象存储或并行文件系统 |
| 模型权重和 Adapter | 是、必须版本化 | 读共享 | 对象存储/模型 Registry + 缓存 |
| Checkpoint、评估和 Artifact | 是、需生命周期策略 | 按项目共享 | 对象存储，必要时共享文件系统 |
| 下载缓存、预处理和 Scratch | 否，可重建 | 节点内共享或不共享 | 本地 NVMe、`emptyDir` |

最重要的规则是：**Home PVC 不是数据湖，RWX 共享盘不是所有数据的默认归宿，本地 NVMe 不是唯一副本。**

## 9. 存储类型选型矩阵

| 存储类型 | 访问模式 | 性能特点 | 适合 | 不适合 |
| --- | --- | --- | --- | --- |
| SSD 块存储 PVC | 常见为 RWO/RWOP | 低延迟、个人目录体验好 | 用户 Home、小项目工作区 | 多节点团队共享、大规模权重副本 |
| 共享文件系统 | RWX | POSIX 方便，性能取决于元数据和后端 | 团队目录、旧代码、共享 Checkpoint | 无配额的大型 Home、百万小文件热路径 |
| 对象存储 | API | 高耐久、版本化、容量大 | 数据集、模型、Checkpoint、Artifact | 依赖完整 POSIX 语义的随机写应用 |
| 对象存储 FUSE/CSI | 文件挂载 | 使用方便，但语义和性能不等同本地文件系统 | 只读数据、模型和验证过的访问模式 | SQLite、锁文件、频繁 rename/fsync、小文件风暴 |
| 节点本地 NVMe | 节点绑定 | 吞吐和延迟最好 | 模型热缓存、数据缓存、编译和 Scratch | 用户唯一数据、无法重建的 Checkpoint |
| `emptyDir` | Pod 生命周期 | 简单，可使用节点盘或内存 | 临时数据、`/dev/shm`、会话 Scratch | Pod 停止后仍需保留的数据 |

Kubernetes 的 PersistentVolume 生命周期独立于单个 Pod；`emptyDir` 等临时卷则跟随 Pod 生命周期。对带可用区或本地拓扑的存储，`WaitForFirstConsumer` 可以让卷在 Pod 选定拓扑后再绑定，降低“GPU 在一个区、PVC 在另一个区”的调度冲突。参考：[Kubernetes Persistent Volumes](https://kubernetes.io/docs/concepts/storage/persistent-volumes/)、[Ephemeral Volumes](https://kubernetes.io/docs/concepts/storage/ephemeral-volumes/)、[Storage Capacity](https://kubernetes.io/docs/concepts/storage/storage-capacity/)

### RWO 和 RWOP 的区别

`ReadWriteOnce` 表示卷可以在一个节点上读写，并不一定严格限制为一个 Pod；需要确保同一时刻只被一个 Pod 使用时，应评估 CSI 驱动是否支持 `ReadWriteOncePod`。多数 Notebook 平台依靠“一个用户服务器 + 一个 PVC”的控制面约束已经足够，但迁移和故障场景仍要验证重复挂载行为。

## 10. 推荐的目录与挂载约定

```text
/home/jovyan        每用户 SSD PVC；Notebook、脚本、配置、小型虚拟环境
/workspace          Git 工作树；可位于 Home 的子目录
/data               只读数据集；对象存储挂载或共享文件系统
/models             只读模型缓存；节点 NVMe 或受控共享缓存
/checkpoints        耐久写入入口；对象存储客户端或共享文件系统
/scratch            emptyDir / 本地 NVMe；可随时删除
/dev/shm            memory-backed emptyDir；供 DataLoader、多进程和框架共享内存
```

目录名不是重点，重点是用户能立刻知道哪些位置会保留、哪些位置可共享、哪些位置会丢失。登录页和终端提示应明确显示：

- `/home/jovyan` 有容量配额并会备份哪些内容；
- `/data` 和 `/models` 是否只读、对应哪个版本；
- `/scratch` 在停止工作区、迁移节点或升级时会被删除；
- 正式 Checkpoint 必须同步到哪个对象存储前缀；
- 禁止把 Token、云密钥或 kubeconfig 写入 Notebook 输出和 Git。

## 11. 推荐的存储分层

```text
权威层：对象存储
数据集、模型、Adapter、Checkpoint、评估和 Artifact
             │
             ▼
共享层：RWX / 并行文件系统 / 对象 FUSE
团队协作、兼容 POSIX、只读数据入口
             │
             ▼
节点热缓存：Local NVMe
Hugging Face Cache、模型权重、数据分片、构建缓存
             │
             ▼
Pod 临时层：emptyDir / tmpfs
Notebook Scratch、/dev/shm、临时解压和中间结果
```

缓存键必须至少包含模型 Revision 或 Digest、数据版本、Tokenizer 版本和转换代码版本。只按模型名称或 `latest` 缓存，可能让用户加载到错误权重。

### 模型缓存怎么做

常见方案从简单到复杂：

1. 每个 Notebook 直接下载到自己的 PVC：最简单，但重复占用空间、冷启动慢；
2. 节点本地只读缓存：下载一次供同节点复用，适合热点模型；
3. DaemonSet 或缓存代理预热：平台控制版本、容量和淘汰；
4. 分布式缓存或高性能共享文件系统：适合大规模并发和多节点训练；
5. OCI/模型制品分发：把摘要、权限和 Registry 供应链统一，但仍要处理节点落盘。

第一版可以采用“对象存储权威副本 + 节点 NVMe LRU 缓存”。当缓存未命中、校验失败或节点丢失时，系统必须能从权威层重建。

## 12. 不要把所有用户都放进一个巨大 RWX Home

“所有 Home 共用一个 RWX 文件系统”看起来迁移简单，但常见问题包括：

- 单个用户的小文件或递归扫描拖慢全体用户；
- POSIX UID/GID、目录权限和离职回收容易出错；
- 无法独立扩容、快照、恢复和计费；
- 一个错误命令可能删除团队共享目录；
- 元数据延迟会直接影响 Git、Python Import、Conda 和 Jupyter 启动。

默认采用每用户 RWO/RWOP SSD PVC，团队确实需要共享的内容再挂载到独立 RWX 路径。共享目录应有项目级 ACL、配额、快照和生命周期策略。

## 13. 环境应该放在镜像还是 Home

### 放进不可变镜像

- OS、CUDA/ROCm、Python 基础版本；
- PyTorch/JAX/TensorFlow 等核心框架；
- JupyterLab、VS Code Server 和平台扩展；
- 企业证书、基础调试工具和安全补丁；
- 经过兼容性验证的 GPU Runtime 与系统库。

### 放进项目 Lockfile 或个人目录

- 项目 Python 依赖与可重复 Lockfile；
- 小型、纯 Python、变化频繁的实验包；
- 用户配置、Notebook 扩展配置和 Shell 配置。

不推荐每次启动都在线安装数 GiB 依赖、长期修改容器根文件系统、使用可变 `latest` 镜像，或让用户自行搭配未经验证的 CUDA、驱动和框架版本。

推荐发布少量黄金镜像，用 Digest 固定版本，并保留镜像 SBOM、漏洞扫描和 CUDA/Driver 兼容记录。用户确实需要新依赖时，先在项目 Lockfile 中验证，再进入下一版镜像。

## 14. 启动速度和 GPU 节点弹性

```text
总启动时间
  = 排队/审批
  + GPU 节点扩容
  + 镜像拉取
  + PVC 创建与挂载
  + Secret/配置注入
  + Jupyter/IDE 启动
  + 数据或模型预热
```

优化顺序：

1. 先测清每一段，而不是只优化 Jupyter 进程；
2. 把交互式用户 Pod 放到专用 GPU 节点池，用 Taint/Toleration 隔离；
3. 预拉取黄金镜像，避免数十 GiB CUDA 镜像阻塞首个用户；
4. 对上班高峰保留少量 Warm Capacity，而不是所有 GPU 都缩到零；
5. 用用户调度器尽量压紧闲时 Pod，释放完整节点供 Autoscaler 缩容；
6. 在同可用区准备 GPU 与 Home PVC 容量；
7. 模型缓存与镜像缓存分别监控，不要混为一个启动阶段。

交互式 Notebook 不适合无限期在 Kueue 中排队。更合理的方式是给交互池保留小额配额和明确最大会话时间，正式训练则由 Notebook 提交到 Kueue 管理的 Job 队列。

## 15. Idle Culler 不是简单看浏览器是否打开

空闲回收至少要区分：

- 浏览器没有活动，但 Kernel 正在计算；
- Kernel 空闲，但终端有进程；
- GPU 已分配但利用率长期接近零；
- 用户关闭页面，但在 Notebook 内错误启动了后台训练；
- 工作区已保存，可以停止 Pod 并保留 PVC；
- 超过最长会话时间，必须结束并通知用户迁移任务。

推荐策略：

1. 在停止前分阶段提醒；
2. 同时检查 Jupyter Activity、Kernel、Terminal 和平台 Job；
3. 先保存用户工作，再停止 Workspace Pod；
4. 保留 Home PVC，不保留 GPU 和节点本地 Scratch；
5. 对共享 GPU、MIG 和整卡设置不同的 Idle Timeout；
6. 设置最长连续会话时间，防止后台进程绕过治理；
7. 给正式任务提供一键转 Job 的黄金路径，而不是让用户关闭 Culler。

成本报表至少区分 Allocation、GPU 实际利用、Active User Time 和 Idle Allocated Time。只统计“分配了几张卡”无法判断平台是否有效。

## 16. 安全隔离

Notebook 是带浏览器入口、终端和任意代码执行能力的长生命周期 Shell，应按高风险工作负载治理。

### 身份与权限

- 企业 OIDC/SSO，禁用共享账号；
- 用户和组映射到团队 Namespace 或 Workspace；
- 默认 `automountServiceAccountToken: false`；
- 提交 Job 时使用专用最小权限身份或平台 API，不向 Notebook 发放管理员 kubeconfig；
- 云资源使用 Workload Identity 和短期凭据，不在 Home 保存长期 Access Key。

### Pod 与节点

- 使用 Pod Security Admission、Seccomp、非 Root 用户和批准的镜像；
- 禁止 `privileged`、HostPath、Host Network、Docker Socket 和宿主 PID；
- 不可信租户与生产服务分节点池，必要时使用 gVisor、Kata 或独立集群；
- GPU Runtime、MIG 和 Time-Slicing 只解决设备分配，不等于完整租户沙箱。

### 网络与数据

- Namespace 默认拒绝出入站，按对象存储、Git、Registry、Pipeline API 白名单放行；
- 阻止访问云实例元数据和无关的 Kubernetes 控制面端点；
- 数据集挂载尽量只读，权限按项目和数据分级；
- Secret 使用外部 Secret 系统或短期令牌，避免显示在环境变量、Notebook 输出和日志中；
- 对外分享 Notebook 必须经过脱敏和输出清理。

## 17. 可观测性与审计

每个 Workspace Pod 建议统一用户、团队、Workspace、Profile、镜像 Digest、成本中心和 GPU 模式等标签。

| 类别 | 指标 |
| --- | --- |
| 启动 | P50/P95 启动时间、节点扩容、镜像拉取、PVC Attach、启动失败率 |
| 使用 | Active Workspace、活跃用户、Kernel/Terminal 活动、会话时长 |
| GPU | Allocation、SM、显存、功耗、XID、共享卡物理利用率、Idle GPU Hours |
| 存储 | PVC 使用率、inode、IOPS、延迟、吞吐、对象请求、缓存命中率 |
| 稳定性 | OOM、Eviction、Pod Restart、Node Drain、Workspace 恢复成功率 |
| 成本 | 用户/团队/Profile GPU 小时、存储 GiB 月、跨区流量、缓存节省量 |

审计至少保留：谁创建、启动、停止、删除或改变了 Workspace；选择了哪个镜像、Profile 和数据挂载；谁申请了整卡或多卡；Notebook 以什么身份提交了哪个 Job；谁访问了受限数据；管理员何时升级控制面、镜像、CSI 和 GPU 组件。

## 18. 三套参考架构

### A. 10–50 人研发团队

```text
OIDC → JupyterHub → KubeSpawner
                    ├─ CPU Pool
                    └─ GPU Pool：Shared Dev + Full GPU

每用户 RWO SSD PVC 50–200 GiB
S3 兼容对象存储：数据、模型、Checkpoint
节点 NVMe：模型和数据缓存
MLflow + Job/TrainJob + Kueue：正式实验
```

特点：最少组件建立完整边界。先不引入共享 RWX，除非已有明确协作需求；共享 GPU 仅提供给可信研发环境。

### B. 企业多租户 AI 平台

```text
企业 IdP → API Gateway / Workspace Portal
              │
              ├─ JupyterHub 或受支持的 Kubeflow 发行版
              ├─ Team Namespace / Quota / NetworkPolicy
              ├─ CPU / MIG / Full GPU Resource Catalog
              ├─ RWO Home + Team RWX + Object Storage + NVMe Cache
              └─ Pipeline / Trainer / Ray / Kueue / MLflow / GitOps
```

特点：资源申请、数据权限、镜像和成本均按团队治理。高风险租户进入更强 RuntimeClass 或独立节点池；Notebook 无权直接修改生产。

### C. 单云小团队

```text
Cloud IAM → Managed Workbench
             ├─ CPU/GPU Instance Profile
             ├─ Per-space Persistent Volume
             ├─ Object Storage / Managed Dataset
             └─ Managed Training Job / Pipeline
```

特点：优先减少平台运维，重点控制 Idle Shutdown、私网、实例配额、持久卷费用和跨区数据。随着租户隔离、自定义调度或多云需求增长，再评估迁移到 Kubernetes 工作区平台。

## 19. 一个平台规格契约示例

不要直接让用户填写完整 Pod。内部平台可以维护类似下面的目录对象，再渲染为 JupyterHub Profile、Kubeflow Workspace 或托管服务模板：

```yaml
apiVersion: platform.example.com/v1alpha1
kind: WorkspaceProfile
metadata:
  name: gpu-full-llm-dev
spec:
  displayName: LLM 单卡开发
  image: registry.example.com/ai/jupyter-pytorch@sha256:<digest>
  resources:
    requests:
      cpu: "8"
      memory: 64Gi
      nvidia.com/gpu: "1"
    limits:
      cpu: "16"
      memory: 96Gi
      nvidia.com/gpu: "1"
  placement:
    nodePool: gpu-interactive
    gpuMode: exclusive
  storage:
    home:
      class: notebook-rwo-ssd
      size: 200Gi
      mountPath: /home/jovyan
    scratch:
      type: LocalEphemeral
      sizeLimit: 500Gi
      mountPath: /scratch
    datasets:
      readOnly: true
      mountPath: /data
  session:
    idleTimeout: 90m
    maxDuration: 12h
  security:
    serviceAccountToken: false
    networkProfile: research-restricted
```

这不是建议立即发明一个新的 CRD。第一版可以用 Git 中的 JupyterHub Helm Values、Kubeflow 模板或内部 Portal 配置表达同样的契约。关键是用户看到的是稳定产品规格，平台内部才处理 StorageClass、Resource Name、Taint 和网络策略。

## 20. PoC 必须测什么

### 功能测试

- OIDC 登录、登出、用户禁用和组权限变化；
- CPU、共享 GPU、MIG、整卡 Profile 创建和停止；
- Home PVC 停止后保留、重新挂载和扩容；
- Git、Registry、对象存储、MLflow 和 Job API 的最小权限；
- 镜像升级后旧工作区、旧 PVC 和用户名映射是否兼容。

### 性能测试

- 冷节点、热节点、冷镜像和热镜像的 P50/P95 启动时间；
- 目标模型首次下载与缓存命中加载时间；
- Home PVC 的 Git Checkout、Python Import 和小文件性能；
- 对象存储顺序读、大量小对象和 FUSE 元数据行为；
- 本地 NVMe 缓存写入、淘汰和多用户并发；
- Time-Slicing 下一个用户 OOM、满载或重启对其他用户的影响。

### 故障与恢复测试

- 删除 Workspace Pod，验证 Home 恢复和 Scratch 丢失提示；
- Drain 或替换 GPU 节点，验证 PVC 拓扑和重新调度；
- CSI、对象存储、Registry 或 IdP 短时不可用；
- PVC 满、inode 满、本地盘满和镜像拉取失败；
- 从 VolumeSnapshot 恢复用户 Home；
- 从对象存储恢复正式 Checkpoint，而不是只恢复 Notebook 文件。

### 安全测试

- 尝试访问其他用户 PVC、Namespace、ServiceAccount 和 Secret；
- 尝试访问实例元数据、Kubernetes API、生产数据库和非授权对象前缀；
- 尝试使用特权容器、HostPath、Host Network 和未批准镜像；
- 检查 Notebook 输出、终端历史、Git 历史和日志是否泄露 Token。

## 21. 备份与生命周期

### Home PVC

- CSI `VolumeSnapshot` 适合快速恢复，但取决于 CSI 驱动支持；
- Snapshot 仍可能和源卷位于同一存储系统或故障域，不能自动等同异地备份；
- 关键 Notebook 和脚本仍应提交 Git；
- 建立离职、长期未使用用户的归档和删除审批流程。

### 对象存储

- 对数据、模型和 Checkpoint 启用版本、保留与生命周期策略；
- Bucket/Prefix 按项目和环境隔离；
- 定期从备份恢复，而不是只验证上传成功；
- 大型失败上传和旧 Checkpoint 要有清理策略。

### 本地缓存和 Scratch

- 明确是可重建数据，不纳入备份；
- 设置容量水位、LRU/TTL、inode 告警和垃圾回收；
- 节点 Drain 前不承诺迁移；
- 缓存未命中必须安全回退到权威存储。

参考：[Kubernetes Volume Snapshots](https://kubernetes.io/docs/concepts/storage/volume-snapshots/)

## 22. 常见反模式

| 反模式 | 后果 | 修正 |
| --- | --- | --- |
| 每位用户永久独占一张 GPU | 大量 Idle GPU Hours | 默认 CPU/共享/MIG，整卡按需且自动停止 |
| 正式训练跑在 Notebook Kernel | 页面、Culler、Pod 或节点故障导致任务丢失 | 调试完成后提交 Job/TrainJob/RayJob |
| 模型和数据都复制进 Home PVC | 成本高、版本混乱、迁移慢 | 对象存储权威副本 + 共享只读/节点缓存 |
| 所有人共用一个 RWX Home | 元数据争用、权限和恢复困难 | 每用户 RWO，团队共享内容单独 RWX |
| 本地 NVMe 保存唯一 Checkpoint | 节点故障即丢失 | 本地暂存，异步提交到对象存储并校验完成标记 |
| 用户随意选择镜像和 GPU 数 | 兼容性、供应链和容量不可控 | 版本化 Profile Catalog + 审批 |
| Time-Slicing 当作强隔离 | OOM、故障和性能互相影响 | MIG、整卡或独立节点池 |
| Notebook 持有集群管理员 Token | 任意代码可控制生产 | 最小权限 Job Broker/API，默认不挂 SA Token |
| Snapshot 当成唯一备份 | 同故障域或误删仍可能无法恢复 | Git + 独立备份 + 恢复演练 |
| Idle 只看浏览器连接 | 误杀计算或永不回收后台进程 | Kernel、Terminal、GPU 和最长时限联合判断 |

## 23. 选型评分表

建议先给以下维度设置权重，再用实际 PoC 数据打分：

| 维度 | 建议权重 | 验收例子 |
| --- | ---: | --- |
| 身份与多租户安全 | 20% | OIDC、最小权限、NetworkPolicy、审计均通过 |
| GPU 隔离与资源治理 | 15% | Profile、MIG/整卡、配额和 Idle 回收可验证 |
| 存储与数据路径 | 20% | Home 恢复、对象版本、本地缓存和故障测试通过 |
| 开发体验 | 15% | P95 启动、IDE、Git、依赖和调试路径达标 |
| 任务移交与 MLOps | 10% | 一键提交正式任务并关联 Run、代码和制品 |
| 可观测性与成本 | 10% | 用户到 GPU/存储/成本可归因 |
| 运维和升级 | 10% | 升级、备份、回滚、兼容矩阵和 Owner 明确 |

总分接近不代表产品等价。安全、数据恢复或 GPU 隔离中的任何一项没有达到硬门槛，都不应被更好的 UI 分数抵消。

## 24. 分阶段落地

### 第一阶段：建立可用入口

- JupyterHub 或受支持的 Workbench 控制面；
- OIDC、每用户 RWO PVC、CPU 与整卡两个 Profile；
- 黄金镜像、对象存储 SDK、基础网络策略；
- 停止 Workspace 保留 Home，禁止正式训练留在 Notebook。

### 第二阶段：提高利用率

- 共享 GPU 或 MIG Profile；
- Idle Culler、最长会话时限、镜像预拉取；
- 本地 NVMe 模型/数据缓存；
- GPU、PVC、启动时延和成本看板。

### 第三阶段：平台化治理

- Team Namespace、Quota、审批和成本中心；
- Kueue + TrainJob/RayJob/Pipeline 任务移交；
- 共享数据挂载、模型 Registry、实验追踪和 GitOps；
- 镜像供应链、VolumeSnapshot/备份和恢复演练。

### 第四阶段：规模化与演进

- 多集群或多地域 Workspace 路由；
- 更精细的 GPU Profile、DRA 评估和拓扑感知；
- 缓存预热、热点预测和容量预约；
- Kubeflow Notebooks v1 到 Workspaces v2 或其他平台的迁移。

## 25. 上线清单

- [ ] Notebook 只承担交互开发，正式长任务有独立执行系统。
- [ ] 用户只能选择批准的镜像、资源和挂载 Profile。
- [ ] 整卡、MIG、Time-Slicing 的隔离和计费语义已向用户说明。
- [ ] 每用户 Home、团队共享、对象存储、缓存和 Scratch 生命周期分开。
- [ ] 数据集、模型和 Checkpoint 的权威副本不在 Home 或本地 NVMe。
- [ ] Home PVC 有容量告警、快照/备份策略和恢复演练。
- [ ] Workspace Pod 默认无管理员 Token、特权模式和 HostPath。
- [ ] 网络默认拒绝，仅放行 Git、Registry、对象存储和平台 API。
- [ ] Idle Culler 不会误杀正式任务，并能回收闲置 GPU。
- [ ] 监控能从用户、Workspace 和 Profile 追到 GPU、存储和成本。
- [ ] 冷启动、模型缓存、PVC 拓扑、节点替换和共享 GPU 干扰均做过 PoC。
- [ ] Kubeflow 或 JupyterHub 大版本升级包含 PVC、用户名和 API 迁移验证。

## 延伸阅读

- [Kubeflow Notebooks Overview](https://www.kubeflow.org/docs/components/notebooks/overview/)
- [Kubeflow Notebook Container Images](https://www.kubeflow.org/docs/components/notebooks/container-images/)
- [Kubeflow 26.03.1 Release Announcement](https://blog.kubeflow.org/kubeflow-26.03-release/)
- [Zero to JupyterHub：Optimizations](https://z2jh.jupyter.org/en/stable/administrator/optimization.html)
- [Zero to JupyterHub：Customizing User Resources](https://z2jh.jupyter.org/en/latest/jupyterhub/customizing/user-resources.html)
- [Kubernetes Persistent Volumes](https://kubernetes.io/docs/concepts/storage/persistent-volumes/)
- [Kubernetes Ephemeral Volumes](https://kubernetes.io/docs/concepts/storage/ephemeral-volumes/)
- [Kubernetes Volume Snapshots](https://kubernetes.io/docs/concepts/storage/volume-snapshots/)
- [NVIDIA GPU Operator：Time-Slicing](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/25.3/gpu-sharing.html)
- [NVIDIA GPU Operator：MIG](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/gpu-operator-mig.html)
- [AI 数据、存储与缓存](../data-storage.md)
- [GPU 与异构资源调度](../gpu-scheduling.md)
- [MLOps 与平台工程](../mlops.md)
- [GPU 成本与容量规划](../cost-capacity.md)
- [AI 平台安全与治理](../security-governance.md)
