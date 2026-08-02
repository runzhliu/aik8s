# AI on Kubernetes 十年：从 GPU Pod 到分布式智能推理

> 时间范围：2016—2026；资料更新于 2026 年 8 月。

AI on Kubernetes 并不是一个单独的产品，而是一套逐步形成的云原生 AI 基础设施。它用 Kubernetes 管理计算、网络、存储和生命周期，再通过调度器、Operator、流水线、模型服务和可观测工具补齐 AI 工作负载特有的语义。

过去十年的核心变化可以浓缩成一句话：

> Kubernetes 从“能够运行使用 GPU 的容器”，发展成了“理解分布式训练、稀缺加速器和生成式推理特征的平台底座”。

## 专题阅读

### 算力、队列与数据

- [GPU 与异构资源调度](gpu-scheduling.md)：GPU 软件栈、共享方式、拓扑感知和 DRA。
- [队列、公平共享与多租户](queue-multitenancy.md)：Kueue、Flavor、Cohort、公平性、优先级和抢占契约。
- [AI 数据、存储与缓存](data-storage.md)：对象存储、共享文件、本地 NVMe、模型分发和数据局部性。
- [RDMA 与 AI 高速网络](rdma-networking.md)：InfiniBand、RoCE、GPUDirect、Multus、SR-IOV、调优与排障。

### 训练、推理与 Agent

- [分布式训练平台](distributed-training.md)：Kubeflow Trainer、KubeRay、JobSet、数据与容错设计。
- [可靠性、Checkpoint 与故障恢复](reliability.md)：RPO/RTO、分布式 Checkpoint、Spot、PDB 和故障演练。
- [LLM 推理平台](llm-inference.md)：KServe、vLLM、LWS、Inference Gateway 和核心性能指标。
- [AI Agent、沙箱与工具执行](agentic-workloads.md)：Agent Sandbox、RuntimeClass、Tool Gateway、预算和审计。
- [边缘 AI、K3s 与云边协同](edge-ai.md)：弱网自治、设备管理、模型 OTA、K3s 与 KubeEdge 选型。

### 平台工程与治理

- [MLOps 与平台工程](mlops.md)：流水线、实验、GitOps、多租户、安全和可观测性。
- [GPU、训练与推理可观测性](observability.md)：DCGM、训练分解、TTFT/TPOT、Trace、SLO 和告警。
- [AI 平台安全与治理](security-governance.md)：身份、Pod Security、镜像/模型供应链、Secret 和网络边界。
- [GPU 成本、容量规划与 FinOps](cost-capacity.md)：单位经济性、OpenCost、弹性、Spot 和预算保护。
- [性能基准、压测与回归](benchmarking.md)：硬件、NCCL、存储、Time-to-Quality、LLM 压测和发布门禁。
- [平台运维、升级与多集群](platform-operations.md)：版本矩阵、Canary GPU 节点、CRD、灾备和升级验收。
- [落地路线图](adoption-roadmap.md)：按团队规模选择技术栈，并给出 30/60/90 天实施清单。

### 推荐阅读路线

| 角色/目标 | 建议顺序 |
| --- | --- |
| 从零建设平台 | GPU 调度 → 数据存储 → 队列多租户 → MLOps → 落地路线图 |
| 优化分布式训练 | 分布式训练 → RDMA → 数据存储 → 可靠性 → 性能基准 |
| 建设 LLM 推理 | LLM 推理 → 可观测性 → 成本容量 → 安全治理 → 可靠性 |
| 运行 Agent 平台 | Agent 沙箱 → 安全治理 → 可观测性 → 成本容量 → 平台运维 |
| 负责 Day-2 运维 | 可观测性 → 可靠性 → 性能基准 → 平台运维 → 落地路线图 |

## 一、十年发展脉络

| 阶段 | 主要问题 | 代表性进展 | 典型工具 |
| --- | --- | --- | --- |
| 2016—2017：基础设施接入 | 容器如何发现和独占 GPU | Device Plugin、扩展资源、GPU 调度；Operator/CRD 模式开始普及 | Kubernetes、NVIDIA Device Plugin、TFJob |
| 2018—2020：训练平台化 | 如何编排多角色、分布式训练任务 | Kubeflow、训练 Operator、Pipeline、超参搜索；Kubeflow 1.0 | Kubeflow、Argo Workflows、Katib、MPI Operator |
| 2020—2022：MLOps 工程化 | 如何管理实验、模型版本和持续交付 | 实验追踪、模型注册、特征平台、GitOps；统一模型服务 API；批任务队列 | MLflow、Kubeflow Pipelines、KServe、Flyte、Kueue、Volcano |
| 2023—2024：生成式 AI 转向 | LLM 训练和推理如何跨多机多卡运行 | Ray/KubeRay 普及；vLLM 等高吞吐引擎出现；GPU 共享、拓扑和成本成为核心问题 | KubeRay、vLLM、Triton、KServe、KEDA、DCGM Exporter |
| 2025—2026：AI 原生控制面 | 如何按请求特征路由、共享 KV Cache、拆分 Prefill/Decode | JobSet、LeaderWorkerSet、Inference Gateway、llm-d、DRA 和工作负载感知调度持续成熟 | Kueue、JobSet、LWS、Gateway API Inference Extension、llm-d、Kubeflow Trainer V2 |

### 1. 2016—2017：先让 Kubernetes 看见 GPU

早期 Kubernetes 擅长运行无状态服务，却不了解 GPU、FPGA、RDMA 等特殊硬件。2017 年 Kubernetes 社区开始系统推进 Device Plugin、CPU Manager、HugePages 等资源管理能力；Device Plugin 后来成为稳定的设备接入机制。安装厂商插件后，Pod 可以像申请 CPU、内存一样申请 `nvidia.com/gpu` 或 `amd.com/gpu`。

这一阶段解决的是“能不能运行”，还没有解决训练任务必须同时拿到多张卡、多台机器才能启动的问题。

参考：[Kubernetes Resource Management Working Group（2017）](https://kubernetes.io/blog/2017/09/Introducing-Resource-Management-Working/)、[Kubernetes GPU 调度](https://kubernetes.io/docs/tasks/manage-gpus/scheduling-gpus/)

### 2. 2018—2020：用 Operator 表达训练语义

普通 `Job` 不知道 TensorFlow 的 Parameter Server、PyTorch Worker 或 MPI Launcher。Kubeflow 从 2017 年的 TFJob 起步，通过 CRD 和控制器把框架角色、失败重试和分布式启动过程声明化；项目在 2020 年发布 1.0，覆盖开发、训练和部署等核心环节。

这个阶段形成了经典的“平台套件”思路：Notebook + Pipeline + Training Operator + Katib + Serving。它让数据科学家不必直接拼装大量 Kubernetes YAML，但完整 Kubeflow 的安装和升级成本也比较高。

参考：[Kubeflow 1.0 与项目历史](https://blog.kubeflow.org/releases/2020/03/02/kubeflow-1-0-cloud-native-ml-for-everyone.html)、[Kubeflow Trainer 演进](https://blog.kubeflow.org/trainer/intro/)

### 3. 2020—2022：从训练编排转向 MLOps

企业开始关心的，不再只是“训练是否成功”，而是整个模型生命周期：

- 数据和代码对应哪个实验；
- 参数、指标、模型制品如何追踪；
- 模型如何注册、审批、灰度和回滚；
- 多团队如何公平共享有限的 GPU；
- 流水线如何重复执行并被审计。

MLflow 成为实验追踪和模型注册的常见选择；Kubeflow Pipelines、Argo Workflows、Flyte 负责任务 DAG；KServe 则把模型推理抽象为 `InferenceService`。KServe 的前身 KFServing 创建于 2019 年，并在 2021 年开始向独立项目 KServe 过渡。

与此同时，Kueue 在 2022 年出现，专门解决配额、公平共享、优先级和“任务何时允许启动”；Volcano 则提供更完整的批处理调度器以及 Gang Scheduling、队列和抢占能力。

参考：[MLflow Tracking](https://mlflow.org/docs/latest/ml/tracking/)、[Argo Workflows](https://argoproj.github.io/workflows/)、[KServe 历史](https://kserve.github.io/website/blog/kfserving-transition)、[Kueue 介绍](https://kubernetes.io/blog/2022/10/04/introducing-kueue/)

### 4. 2023—2024：LLM 改变资源和服务模型

大模型带来了与传统在线推理不同的约束：模型可能装不进单卡，单次请求持续更久，输出需要流式返回，吞吐取决于动态批处理和 KV Cache，扩缩容也不能只看 CPU。

这一阶段的重点从“启动一个模型 Pod”转向：

- 多机多卡并行与高速网络拓扑；
- GPU 利用率、显存碎片和单位 Token 成本；
- 连续批处理、Paged Attention、量化和模型并行；
- 基于队列长度、并发数或 Token 指标扩缩容；
- 训练、批推理、在线推理在同一资源池中的隔离与共享。

Ray 通过 KubeRay 提供 `RayCluster`、`RayJob` 和 `RayService`，覆盖分布式计算、训练和服务；vLLM、NVIDIA Triton、Text Generation Inference 等成为模型运行时；KServe 则继续承担 Kubernetes 上的部署控制面。

参考：[KubeRay 官方文档](https://ray-project.github.io/kuberay/)、[KServe 管理指南](https://kserve.github.io/website/docs/admin-guide/overview)

### 5. 2025—2026：调度对象从 Pod 扩展到设备、工作负载和请求

目前的演进同时发生在三个层面：

1. **设备层**：Dynamic Resource Allocation（DRA）用 `ResourceClaim` 等 API 描述设备选择、共享、分区、健康状态和绑定条件，逐步突破传统 Device Plugin 只暴露整数资源的限制。
2. **工作负载层**：JobSet 表达由多个 Job 组成的分布式批任务；LeaderWorkerSet 把一组 Leader/Worker Pod 当作一个复制单元，适合多机推理；Kueue 负责配额、准入、公平共享和拓扑感知。
3. **请求层**：Gateway API Inference Extension 根据模型、负载、缓存和服务能力选择后端；llm-d 进一步组合 vLLM、推理网关、KV Cache 感知路由和 Prefill/Decode 分离。

Kubeflow Trainer V2 也开始更多复用 JobSet、Kueue 等 Kubernetes 批处理能力，不再为每个框架重复实现完整的底层编排逻辑。

参考：[Kubernetes 1.36 DRA](https://kubernetes.io/blog/2026/05/07/kubernetes-v1-36-dra-136-updates/)、[JobSet](https://kubernetes.io/blog/2025/03/23/introducing-jobset/)、[LeaderWorkerSet](https://lws.sigs.k8s.io/)、[Gateway API Inference Extension](https://gateway-api-inference-extension.sigs.k8s.io/)、[llm-d](https://llm-d.ai/)

## 二、当前工具全景

下面的工具不是简单的竞争关系，而是处于不同层级。一个生产平台通常会从每层选一到两个，而不是全部安装。

```text
开发与治理       Notebook / Git / MLflow / Model Registry / Katib
                         │
流程与训练       Argo / KFP / Flyte / Kubeflow Trainer / KubeRay
                         │
资源准入与调度   Kueue / Volcano / JobSet / LWS / kube-scheduler
                         │
模型服务控制面   KServe / Ray Serve / Seldon / BentoML
                         │
推理运行时       vLLM / SGLang / Triton / TensorFlow Serving
                         │
流量与弹性       Inference Gateway / Envoy AI Gateway / llm-d / KEDA
                         │
Agent 执行         Agent Sandbox / Kata / gVisor / Tool Gateway
                         │
硬件与数据       GPU Operator / DRA / CSI / Object Storage / RDMA
                         │
统一运维         Prometheus / Grafana / OpenTelemetry / Argo CD / Kyverno
```

### 1. Kubernetes 与基础交付

| 工具 | 主要职责 | 适用建议 |
| --- | --- | --- |
| Kubernetes `Job` / `Deployment` / `StatefulSet` | 批任务、在线服务、有状态组件的基础生命周期 | 所有方案的底座；简单场景可以只用原生对象 |
| Helm / Kustomize | 安装和环境差异管理 | Helm 管第三方组件，Kustomize 管自己的声明通常较清晰 |
| Argo CD / Flux | GitOps 持续交付 | 模型服务配置和平台组件都建议声明式发布 |
| Karpenter / Cluster Autoscaler | 根据待调度 Pod 扩缩节点 | 云上弹性 GPU 节点池常用；注意 GPU 启动时间和最小保有量 |

### 2. GPU、加速器与节点管理

| 工具 | 主要职责 | 适用建议 |
| --- | --- | --- |
| NVIDIA GPU Operator | 自动安装和维护驱动、Container Toolkit、Device Plugin、节点标签和 DCGM 监控 | NVIDIA GPU 集群的事实标准起点 |
| AMD GPU Operator / Intel Device Plugins | 对应厂商的 GPU、XPU 等设备接入 | 异构集群应分别评估厂商支持矩阵 |
| Node Feature Discovery | 发现硬件并写入节点标签 | GPU 型号、网卡、CPU 特性等调度依据 |
| MIG / Time-Slicing / MPS | GPU 分区或共享 | 小模型推理、Notebook 和开发环境；强隔离场景优先 MIG |
| Dynamic Resource Allocation | 细粒度描述、选择和共享设备 | 新集群值得验证，但必须确认 Kubernetes 版本和厂商 DRA Driver 的成熟度 |

GPU Operator 自动化的不只是 Device Plugin，还包括驱动、容器运行时、标签和监控组件，显著降低了 GPU 节点 Day-2 运维复杂度。参考：[NVIDIA GPU Operator](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/)

### 3. 队列与调度

| 工具 | 主要职责 | 最适合的场景 |
| --- | --- | --- |
| Kueue | 工作负载准入、配额、公平共享、优先级、抢占、资源类型和多集群分发 | 希望保留原生 kube-scheduler，只补充 AI/批任务队列能力 |
| Volcano | 独立批调度器、Gang Scheduling、队列、DRF、公平和拓扑策略 | 大量 HPC/AI/大数据混合任务，需要强调度控制 |
| Apache YuniKorn | 分层队列和多租户调度 | 已有 Hadoop/YARN 式队列治理经验的组织 |
| Koordinator | 在线/离线混部、资源超卖和 QoS | 希望提高大规模集群综合利用率的场景 |
| 商业平台：Run:ai 等 | GPU 配额、共享、策略和使用体验 | 需要商业支持、计费和完整治理界面的企业 |

Kueue 的定位是决定 Job **何时可以开始以及可以使用哪类配额**，而不是替代 Pod 到 Node 的常规调度。它目前能集成 Job、JobSet、Kubeflow Trainer、KubeRay 和 LeaderWorkerSet。参考：[Kueue Overview](https://kueue.sigs.k8s.io/docs/overview/)

### 4. 分布式训练与计算

| 工具 | 主要职责 | 适用建议 |
| --- | --- | --- |
| Kubeflow Trainer | PyTorch、JAX、Hugging Face、DeepSpeed、MPI 等分布式训练 | 需要 Kubernetes 原生训练 API、运行时模板和多框架支持 |
| KubeRay | 管理 RayCluster、RayJob、RayService | Python/Ray 技术栈，或训练、数据处理、推理希望使用同一套分布式运行时 |
| JobSet | 用多个 Kubernetes Job 表达一个分布式任务 | 构建框架无关的训练/HPC 控制器，或需要多角色、多拓扑域 |
| MPI Operator | MPI 任务编排 | HPC、Horovod、传统 MPI 训练 |
| Spark Operator | Kubernetes 上的 SparkApplication | 大规模特征工程、ETL 和批处理 |
| DeepSpeed / Megatron-LM / PyTorch FSDP | 模型和数据并行算法 | 它们是训练运行时，不替代 Kubernetes 调度与生命周期管理 |

当前 Kubeflow Trainer 已面向 LLM 训练与微调，并与 Kueue、JobSet、LeaderWorkerSet 等组件组合。参考：[Kubeflow Trainer](https://www.kubeflow.org/docs/components/trainer/overview/)

### 5. 工作流、实验与模型治理

| 工具 | 主要职责 | 适用建议 |
| --- | --- | --- |
| Kubeflow Pipelines（KFP） | 以 ML 为中心的组件化 Pipeline、缓存、元数据 | 已使用 Kubeflow，或需要数据科学家友好的 ML Pipeline |
| Argo Workflows | Kubernetes 原生 DAG/步骤工作流 | 希望保持通用、轻量，并同时编排数据和基础设施任务 |
| Flyte | 强类型、数据感知的 ML/Data 工作流 | 大型团队、复杂依赖和可复现任务 |
| Apache Airflow | 通用数据调度和丰富连接器 | 已有 Airflow 数据平台；训练可通过 KubernetesPodOperator 提交 |
| MLflow | 实验、指标、制品、模型注册和评估 | 组件化架构中最常见的模型生命周期底座之一 |
| Katib / Optuna / Ray Tune | 超参数搜索 | Katib 偏 Kubernetes 平台，Optuna 偏 Python 库，Ray Tune 适合 Ray 用户 |
| Feast | 在线/离线特征管理 | 传统推荐、风控等强依赖一致特征的系统；LLM 项目未必需要 |

### 6. 模型服务与 LLM 推理

这一层要分清 **控制面** 和 **运行时**：KServe 管部署、流量和伸缩，vLLM/Triton/SGLang 真正执行模型计算。它们通常是组合关系。

| 工具 | 类型 | 主要职责 |
| --- | --- | --- |
| KServe | Kubernetes 模型服务控制面 | `InferenceService`、模型加载、灰度、弹性；同时覆盖传统预测与生成式推理 |
| Ray Serve | 分布式服务框架 | Python 组合、多模型 Pipeline，与 Ray Train/Data 集成 |
| Seldon Core / MLServer | 模型服务控制面与运行时 | 传统 ML、多框架推理、推理图和企业集成 |
| BentoML / Yatai | 模型打包与部署平台 | 开发体验友好，适合从 Python 服务快速产品化 |
| vLLM | LLM 推理引擎 | 连续批处理、高吞吐、OpenAI 兼容 API、张量/流水线并行 |
| SGLang | LLM/VLM 推理引擎 | 结构化生成、缓存和高性能推理 |
| NVIDIA Triton Inference Server | 通用推理运行时 | 多框架、动态批处理、GPU 优化和统一指标 |
| TensorFlow Serving / TorchServe | 框架型运行时 | 传统模型仍可使用，但新平台通常优先评估更通用的运行时 |

KServe 当前建议：一般生产部署先从标准 `InferenceService` 开始；需要高级 LLM 能力时，再评估 `LLMInferenceService`、智能路由和分离式推理。参考：[KServe 部署模式](https://kserve.github.io/website/docs/admin-guide/overview)

### 7. LLM 流量、弹性与分布式推理

| 工具 | 主要职责 | 适用建议 |
| --- | --- | --- |
| Gateway API Inference Extension | 基于模型、后端能力和实时指标的推理路由规范 | 希望使用 Kubernetes 标准 API，减少与某一网关绑定 |
| Envoy AI Gateway | OpenAI 风格 API、流量治理、鉴权、限流和可观测 | 已使用 Envoy Gateway，或需要统一接入外部与自托管模型 |
| llm-d | KV Cache 感知路由、Prefill/Decode 分离、流控和分布式 LLM 推理方案 | 大规模自托管 LLM，追求单位成本和尾延迟优化 |
| LeaderWorkerSet | 将多 Pod 推理副本作为一个整体管理 | 单个模型副本跨节点、跨 GPU 切分 |
| KEDA | 事件和自定义指标驱动扩缩容 | 根据请求队列、并发、Token 等业务指标扩缩 |
| Knative Serving | 请求驱动伸缩和 Scale-to-Zero | 流量稀疏的传统预测；大型 LLM 冷启动通常需要更谨慎 |

Inference Gateway 的关键变化是：负载均衡不再只做轮询，而是可以根据模型是否已加载、队列深度、KV Cache 命中和后端能力选择实例。参考：[Gateway API Inference Extension](https://gateway-api-inference-extension.sigs.k8s.io/)

### 8. 数据、存储和可观测性

| 领域 | 常用工具 | 关注点 |
| --- | --- | --- |
| 模型和数据制品 | S3/GCS/Azure Blob、MinIO、OCI Registry | 大文件不应直接放进容器镜像或 Git |
| 共享文件与缓存 | CSI、Ceph、JuiceFS、Alluxio、本地 NVMe Cache | 首次加载速度、并发读取、数据局部性和成本 |
| 基础指标 | Prometheus、Grafana、Thanos | 集群、任务和长周期指标 |
| GPU 指标 | NVIDIA DCGM Exporter | 利用率、显存、功耗、温度、XID 错误 |
| 日志与追踪 | Loki/Elastic、OpenTelemetry、Jaeger/Tempo | 训练任务诊断、请求链路与跨服务归因 |
| LLM 质量与追踪 | MLflow、Phoenix、Langfuse、OpenLLMetry | Prompt、Token、延迟、成本、评估和反馈，不应只看基础设施指标 |

### 9. Agent 执行、安全与成本治理

| 工具/机制 | 主要职责 | 适用建议 |
| --- | --- | --- |
| Agent Sandbox | 管理隔离、持久、单例的 Agent 执行环境和 Warm Pool | 需要大规模创建/回收 Agent Workspace 时评估 |
| Kata Containers / gVisor | 为不可信代码增加运行时隔离边界 | 代码执行、Notebook 和 Agent 场景；仍需最小权限与网络策略 |
| Pod Security Admission / Kyverno | Pod 安全基线、准入策略、镜像验证 | 把普通 workload 与特权 GPU Operator 分开治理 |
| OpenCost | Kubernetes 成本分配、Showback/Chargeback | 按团队、Job、模型统计 GPU 与闲置成本 |

Agent 工作负载把平台治理从“运行受信镜像”扩展到“执行模型动态生成的动作”，因此工具权限、网络出站、工作区生命周期和审计都必须成为一等能力。参考：[Agent Sandbox](https://agent-sandbox.sigs.k8s.io/)、[OpenCost](https://opencost.io/docs/)

## 三、怎么选：四套实用组合

### 组合 A：小团队或第一套平台

- 托管 Kubernetes；
- GPU Operator；
- 原生 Job/Deployment + Helm；
- MLflow；
- Argo Workflows 或 Kubeflow Pipelines 二选一；
- KServe + vLLM/Triton；
- Prometheus + Grafana + DCGM Exporter。

原则是先解决可复现、可发布、可监控，不要一开始安装完整 Kubeflow 和多个调度器。

### 组合 B：多团队共享训练集群

- GPU Operator + Node Feature Discovery；
- Kubeflow Trainer 或 KubeRay；
- Kueue；强 Gang Scheduling 需求可评估 Volcano；
- JobSet + 拓扑感知调度；
- MLflow + 对象存储；
- Argo CD 管理平台组件和运行时模板。

这里最重要的不是训练 UI，而是配额、公平性、抢占、拓扑、检查点和故障恢复。

### 组合 C：大规模自托管 LLM 推理

- GPU Operator；硬件和驱动支持成熟时逐步引入 DRA；
- vLLM 或 SGLang；
- KServe + LeaderWorkerSet；
- Gateway API Inference Extension；
- 需要 KV Cache 感知、Prefill/Decode 分离时评估 llm-d；
- KEDA/自定义 Autoscaler；
- Prometheus、DCGM、OpenTelemetry 和 LLM 质量追踪。

这类平台的核心指标应是 TTFT、TPOT、吞吐、P95/P99、KV Cache 命中率和每百万 Token 成本，而不只是 GPU 利用率。

### 组合 D：Ray 为中心的统一计算平台

- KubeRay；
- Ray Data + Ray Train + Ray Tune + Ray Serve；
- Kueue 管配额和准入；
- MLflow 管实验和模型；
- 对象存储保存数据与制品。

适合 Python 团队快速把数据处理、训练和服务串起来；代价是平台会较深地绑定 Ray 的任务和 Actor 模型。

## 四、常见误区

1. **Kubernetes 不等于 MLOps。** 它管理基础设施状态，不自动管理数据血缘、实验、模型质量和审批流程。
2. **KServe 不等于 vLLM。** 前者更像部署控制面，后者是推理执行引擎。
3. **Kueue 不等于 kube-scheduler。** Kueue做任务准入和配额，kube-scheduler 决定具体 Pod 放到哪个节点。
4. **GPU 利用率不是唯一目标。** 大模型服务还要看延迟、吞吐、缓存命中、可靠性和单位 Token 成本。
5. **完整 Kubeflow 不是默认答案。** 组件化安装通常更容易维护；只有确实需要多租户工作台和端到端体验时才引入整套平台。
6. **不要把训练和在线推理完全按普通微服务治理。** 训练需要 Gang、队列和检查点；推理需要模型感知路由、长连接、流式输出和 GPU 预热。
7. **工具越多，平台不一定越成熟。** 明确系统边界、版本兼容矩阵和故障责任，比堆叠功能更重要。

## 五、总结

AI on K8s 的十年，本质上经历了三次抽象升级：

1. **Pod 级**：容器能够申请 GPU；
2. **工作负载级**：平台理解分布式训练、队列、配额和多 Pod 推理副本；
3. **请求级**：平台根据模型、Token、KV Cache 和实时负载调度推理请求。

截至 2026 年，一套较稳妥的开源主线是：

> Kubernetes + GPU Operator + Kueue + Kubeflow Trainer/KubeRay + MLflow + KServe + vLLM + Inference Gateway + Prometheus/DCGM。

它不是唯一答案，但每个组件的职责相对清晰，也能从小规模逐层扩展。真正的选型原则应是：先确定训练还是推理、规模和租户模型，再选择最少的一组组件解决当前问题。

## 延伸阅读

- [Kubernetes 十年回顾](https://kubernetes.io/blog/2024/06/06/10-years-of-kubernetes/)
- [CNCF Cloud Native AI Whitepaper](https://www.cncf.io/reports/cloud-native-artificial-intelligence-whitepaper/)
- [Kubeflow 官方文档](https://www.kubeflow.org/docs/)
- [Kueue 官方文档](https://kueue.sigs.k8s.io/)
- [KServe 官方文档](https://kserve.github.io/website/)
- [KubeRay 官方文档](https://ray-project.github.io/kuberay/)
- [NVIDIA GPU Operator 文档](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/)
- [Gateway API Inference Extension](https://gateway-api-inference-extension.sigs.k8s.io/)
- [llm-d](https://llm-d.ai/)
