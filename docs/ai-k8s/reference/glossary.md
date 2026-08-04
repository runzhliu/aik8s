---
title: AI/LLM Kubernetes 术语表
description: GPU、大数据、调度、训练、推理、网络、Agent 沙箱、模型制品和可靠性常用术语速查
status: stable
last_reviewed: 2026-08-04
---

# AI/LLM Kubernetes 术语表

本页用于统一站内术语。英文缩写保留行业常用写法，中文解释强调它在 Kubernetes AI 基础设施中的工程含义。

## Kubernetes 与设备

| 术语 | 解释 |
| --- | --- |
| CRI | Container Runtime Interface，kubelet 与 containerd/CRI-O 等容器运行时的接口。 |
| CNI | Container Network Interface，为 Pod 配置网络接口、地址和路由的插件接口。 |
| CSI | Container Storage Interface，卷创建、挂载、扩容和快照的插件接口。 |
| CRD | CustomResourceDefinition，向 Kubernetes API 添加自定义资源类型。 |
| Operator | 使用控制器持续协调某个软件栈或领域对象生命周期的模式。 |
| Reconcile | 控制器比较期望状态和实际状态并使其收敛的循环。 |
| Extended Resource | 由设备插件等发布的整数资源，如 `nvidia.com/gpu`。 |
| Device Plugin | 厂商插件，向 kubelet发现、注册和分配特殊设备。 |
| CDI | Container Device Interface，用标准 Spec 描述容器需要注入的设备节点、挂载和环境。 |
| DRA | Dynamic Resource Allocation，用 DeviceClass、ResourceSlice、ResourceClaim 表达动态设备分配。 |
| DeviceClass | DRA 中由管理员定义的设备类别和选择规则。 |
| ResourceSlice | DRA Driver 发布的设备库存、属性和容量。 |
| ResourceClaim | 工作负载对具体设备能力的一次声明。 |
| NFD | Node Feature Discovery，发现 CPU、PCI、内核等节点特征并生成标签。 |
| RuntimeClass | Pod 选择 runc、gVisor、Kata 等容器运行实现的 Kubernetes 对象。 |
| Cluster API | 用 Kubernetes 风格声明式 API 管理集群和 Machine 生命周期的上游项目。 |
| ClusterSet | 一组具有明确成员关系的 Kubernetes 集群；MCS 等多集群 API 使用的逻辑边界。 |
| MCS API | Multicluster Services API，用 ServiceExport/ServiceImport 表达跨集群服务发现。 |
| Karmada | Kubernetes 多集群编排系统，用传播、Override、集群放置和 Failover 策略管理成员集群中的资源。 |
| Taint/Toleration | 限制 Pod 是否可以进入某类节点的调度机制。 |
| Node Affinity | 根据节点标签表达 Pod 必须或倾向运行的位置。 |
| Topology Spread | 将副本分散到节点、可用区等拓扑域。 |
| Topology Manager | kubelet 协调 CPU、设备和内存 NUMA 提示的机制。 |

## GPU 与硬件

| 术语 | 解释 |
| --- | --- |
| HBM | High Bandwidth Memory，GPU 上高带宽显存。 |
| SM | Streaming Multiprocessor，NVIDIA GPU 的主要计算执行单元。 |
| VRAM/Framebuffer | GPU 可用于权重、KV Cache、激活和 Workspace 的显存。 |
| PCIe | CPU、GPU、NIC 等设备连接总线，链路代际和宽度影响带宽。 |
| NUMA | Non-Uniform Memory Access，CPU/内存/设备距离不同造成访问开销差异。 |
| NVLink | NVIDIA GPU 间高速互联。 |
| NVSwitch | 连接多 GPU 的交换 Fabric，常用于 HGX/DGX。 |
| MIG | Multi-Instance GPU，把支持的 NVIDIA GPU 硬件分区为隔离实例。 |
| MPS | CUDA Multi-Process Service，多个 CUDA 进程共享 GPU 执行能力。 |
| Time-Slicing | 多工作负载按时间共享 GPU，不提供 MIG 式显存和故障隔离。 |
| GPU Direct | GPU 与 NIC/存储等设备减少 CPU Bounce Buffer 的数据路径技术集合。 |
| GPU Direct RDMA | NIC 通过 RDMA 直接访问 GPU 内存的数据路径。 |
| ECC | Error-Correcting Code，用于检测和修正内存错误。 |
| XID | NVIDIA Driver 报告的一类 GPU 错误事件编号。 |
| Accelerator Flavor | 平台对 GPU/ASIC 型号、网络、区域和价格等能力的稳定抽象。 |

## 调度与队列

| 术语 | 解释 |
| --- | --- |
| Admission | 工作负载是否获准使用配额并开始创建/运行 Pod 的决策。 |
| Gang Scheduling | 一组 Pod 必须整体满足后才调度，避免部分占用。 |
| PodGroup | 将多个 Pod 表达为同一调度组的 API/概念。 |
| Workload | Kueue/上游调度中代表一组共同准入 Pod 的对象。 |
| Kueue | Kubernetes 原生 Job 队列和配额准入系统，不替代 kube-scheduler。 |
| MultiKueue | Kueue 的多集群 Job 派发能力，通常把完整工作负载择一发送到某个 Worker Cluster。 |
| ClusterQueue | Kueue 中跨 Namespace 的配额和策略对象。 |
| LocalQueue | Namespace 内用户提交 Workload 的队列入口。 |
| ResourceFlavor | Kueue 中表示某类节点/资源属性和 Taint 的对象。 |
| Cohort | 多个 ClusterQueue 共享或借用配额的组。 |
| Preemption | 高优先级工作负载使低优先级工作负载释放资源。 |
| Fair Sharing | 根据历史使用、权重或份额在租户之间公平分配。 |
| TAS | Topology-Aware Scheduling，按机架、Block、主机等拓扑整体放置工作负载。 |
| Volcano | 面向批处理、AI 和 HPC 的 Kubernetes 调度与队列系统。 |
| Cluster Autoscaler | 通过调整预定义节点组扩缩 Kubernetes 节点。 |
| Karpenter | 根据 Pending Pod 和 NodePool 约束动态供给并管理节点生命周期。 |
| HPA | Horizontal Pod Autoscaler，按指标改变副本数。 |
| VPA | Vertical Pod Autoscaler，推荐或调整 Pod CPU/内存请求。 |
| KEDA | 基于事件和外部指标驱动扩缩容，并支持 0 到 1 激活。 |

## 大数据与 Lakehouse

| 术语 | 解释 |
| --- | --- |
| Apache Spark | 面向批处理、SQL、流处理和数据准备的分布式计算引擎；在 Kubernetes 上通常由 Driver 创建 Executor Pod。 |
| Apache Flink | 面向有状态流处理和流批作业的分布式引擎，以 Checkpoint、Savepoint 和事件时间能力见长。 |
| Apache Kafka | 持久分布式事件日志，用于消息、CDC、日志与流量缓冲，不等同于长期数据湖。 |
| KRaft | Kafka 内置的 Raft 元数据控制面，取代 ZooKeeper。 |
| Strimzi | 使用 Kubernetes Operator 管理 Kafka、Node Pool、Topic、User、Connect 和 MirrorMaker 等资源的项目。 |
| Trino | 面向 Lakehouse、数据源联邦和交互分析的分布式 SQL 查询引擎。 |
| Lakehouse | 以对象存储/文件系统保存数据，并通过开放表格式和 Catalog 提供表、Snapshot、事务与多引擎访问的数据架构。 |
| Open Table Format | Iceberg、Delta、Hudi 等管理数据文件、Schema、Partition、Snapshot 和事务的表级格式。 |
| Apache Iceberg | 面向大型分析表的开放表格式，支持 Snapshot、Schema/Partition Evolution 和多引擎读写。 |
| Catalog | 管理表名、Namespace、当前元数据指针及相关访问入口的元数据服务。 |
| CDC | Change Data Capture，把数据库新增、修改和删除转为可消费的变更事件。 |
| Shuffle | 分布式计算 Stage 之间按 Key/Partition 重分布数据的过程，常消耗大量网络、磁盘和内存。 |
| Backpressure | 下游处理速度不足时向上游传播的压力信号，Flink 等流系统据此暴露处理瓶颈。 |

## Ray

| 术语 | 解释 |
| --- | --- |
| Ray Core | 提供分布式 Task、Actor、对象传输、资源与调度的基础运行时。 |
| Ray Task | 可远程并行执行的函数调用，通常用于无状态或短生命周期工作。 |
| Ray Actor | 具有状态和稳定进程生命周期的远程对象，常用于模型 Worker、服务和后训练角色。 |
| Object Store | Ray 节点间共享和传输对象的数据层；不是持久对象存储或数据湖。 |
| Placement Group | 预留一组资源 Bundle，并按 Pack/Spread 等策略共同放置 Actor 或 Task。 |
| Ray Data | 面向 AI 数据处理、流式执行、批量推理和训练数据供给的分布式库。 |
| Ray Train | 协调训练 Worker、框架分布式环境、Checkpoint 和结果的训练控制层。 |
| Ray Tune | 分布式实验和超参数搜索库，管理 Trial、搜索算法、早停和资源。 |
| Ray Serve | 以 Deployment、Replica 和 Handle 组织可独立扩缩的 Python 推理服务和调用图。 |
| Ray Serve LLM | 在 Ray Serve 上扩展多模型、多机、vLLM/SGLang、P/D 分离和高级 LLM 路由的框架。 |
| KubeRay | 在 Kubernetes 上管理 `RayCluster`、`RayJob` 和 `RayService` 的 Operator。 |
| RayJob | KubeRay 的批任务资源，可创建 RayCluster、提交 Job，并在结束后回收集群。 |
| RayService | KubeRay 中 RayCluster 与 Ray Serve Application 的组合资源，用于在线服务和升级。 |

## 分布式训练

| 术语 | 解释 |
| --- | --- |
| Rank | 分布式任务中一个进程的全局或局部编号。 |
| World Size | 参与分布式通信的进程总数。 |
| Rendezvous | Worker 发现彼此并建立分布式组的过程。 |
| Data Parallel | 每个设备持有模型副本并处理不同数据，再同步梯度。 |
| Tensor Parallel | 在层内切分张量和计算，需要频繁设备间通信。 |
| Pipeline Parallel | 按模型层/Stage 切分，并以 Micro-batch 流水执行。 |
| Expert Parallel | 将 MoE Expert 分散到不同设备，常涉及 All-to-All。 |
| FSDP | Fully Sharded Data Parallel，分片参数、梯度和优化器状态。 |
| All-Reduce | 聚合所有 Rank 数据并把结果返回所有 Rank 的 Collective。 |
| All-Gather | 收集所有 Rank 的分片并让每个 Rank 获得完整结果。 |
| Reduce-Scatter | Reduce 后把结果分片分发给各 Rank。 |
| All-to-All | 每个 Rank 向所有 Rank 发送不同数据，MoE 常用。 |
| Checkpoint | 保存可恢复训练或模型状态的制品。 |
| RPO | Recovery Point Objective，可接受丢失多少训练进度/数据。 |
| RTO | Recovery Time Objective，故障后多快恢复运行。 |
| Elastic Training | Worker 数变化或故障后能够重组继续的训练方式。 |

## 网络与 RDMA

| 术语 | 解释 |
| --- | --- |
| RDMA | Remote Direct Memory Access，降低远程内存访问的 CPU 和复制开销。 |
| InfiniBand | 为高性能计算设计的网络 Fabric 和协议栈。 |
| RoCE | RDMA over Converged Ethernet，在以太网上承载 RDMA。 |
| iWARP | 基于 TCP 的 RDMA 协议。 |
| HCA | Host Channel Adapter，InfiniBand/RDMA 主机适配器。 |
| SR-IOV | 将一个 PCIe 设备虚拟为多个 VF，供 Pod/VM 分配。 |
| PF/VF | SR-IOV 的 Physical Function / Virtual Function。 |
| Multus | 为 Pod 附加多个网络接口的 Kubernetes Meta CNI。 |
| PFC | Priority Flow Control，RoCE 无损网络常用的逐优先级流控。 |
| ECN | Explicit Congestion Notification，显式拥塞标记。 |
| MTU | Maximum Transmission Unit，链路可承载的最大帧/包大小配置。 |
| NCCL | NVIDIA Collective Communications Library。 |
| RCCL | AMD ROCm Collective Communications Library。 |
| UCX | 面向高性能网络和内存传输的统一通信框架。 |
| NIXL | 面向推理系统内存/KV 数据传输的 NVIDIA 开源库和抽象。 |

## LLM 推理

| 术语 | 解释 |
| --- | --- |
| Prefill | 一次处理输入 Prompt 并生成初始 KV Cache 的阶段。 |
| Decode | 自回归逐 Token 生成输出的阶段。 |
| TTFT | Time To First Token，从请求到首 Token 的延迟。 |
| TPOT | Time Per Output Token，输出阶段平均每 Token 时间。 |
| ITL | Inter-Token Latency，相邻输出 Token 的延迟。 |
| E2E Latency | 从请求开始到完整响应结束的总延迟。 |
| Goodput | 同时满足延迟/质量等 SLO 的有效吞吐。 |
| Continuous Batching | 每个调度步动态加入/移除请求的批处理方式。 |
| Chunked Prefill | 把长 Prompt 的 Prefill 拆分，减少对 Decode 的阻塞。 |
| KV Cache | Attention 的 Key/Value 中间状态，随上下文和并发占用显存。 |
| Paged KV Cache | 以固定 Block 管理 KV，减少碎片并支持灵活调度。 |
| Prefix Cache | 复用共享 Prompt 前缀已经计算的 KV。 |
| KV Offload | 把 KV 从 GPU HBM 移到 CPU、NVMe 或远端层。 |
| P/D 分离 | Prefill 和 Decode 使用独立 Worker Pool 并传输 KV。 |
| Speculative Decoding | Draft/MTP 等先提出多个候选 Token，再由主模型验证。 |
| LoRA | Low-Rank Adaptation，以较小 Adapter 表达模型微调。 |
| InferencePool | Gateway API Inference Extension 中一组推理 Endpoint。 |
| EPP | Endpoint Picker/Endpoint Picker Provider，根据请求与后端状态选择 Endpoint。 |
| LWS | LeaderWorkerSet，把一个 Leader 和多个 Worker 作为复制单元。 |
| Modelcar | KServe 中把模型作为 OCI Image 附加到 Serving Pod 的模式。 |
| AIBrix | 面向 Kubernetes LLM 推理的控制面，覆盖 Gateway、路由、弹性、LoRA、KV Cache 和分布式推理等能力。 |
| NVIDIA NIM | 将模型、验证过的推理运行时、配置和管理接口包装为 NVIDIA 推理微服务的产品栈。 |

## 模型、RAG 与 MLOps

| 术语 | 解释 |
| --- | --- |
| Model Registry | 管理模型版本、元数据、阶段和血缘的服务；不一定存储权重本体。 |
| Kubeflow Hub | Kubeflow 的模型 Registry 与 Catalog 组件演进名称。 |
| Artifact | 模型、数据、评估、日志等不可变输出制品。 |
| Lineage | 代码、数据、配置、训练和模型之间的来源关系。 |
| safetensors | 不依赖 Pickle 代码执行的张量序列化格式。 |
| GGUF | llama.cpp 生态常用的模型和量化元数据格式。 |
| OCI Artifact | 使用 OCI Registry 分发非容器内容的制品模型。 |
| Embedding | 将文本/图像等内容转换为向量表示。 |
| Vector Database | 存储向量并执行近似最近邻和 Metadata Filter 的数据库。 |
| ANN | Approximate Nearest Neighbor，近似最近邻搜索。 |
| HNSW | 常见图结构 ANN 索引算法。 |
| Chunk | RAG 中把文档拆分的检索单元。 |
| Hybrid Search | 组合向量、关键词和 Metadata Filter 的检索。 |
| Reranker | 对初步检索候选进行更精确排序的模型。 |
| Groundedness | 生成内容是否被提供的来源或上下文支持。 |

## Agent 与沙箱

| 术语 | 解释 |
| --- | --- |
| Agent Control Plane | 管理 Agent 会话、模型调用、预算、策略、Sandbox 和工具审批的控制面。 |
| Agent Sandbox | 为 Agent 提供隔离执行环境的泛称；也可特指 Kubernetes SIG Apps 的 Agent Sandbox CRD/Controller 项目。 |
| Sandbox | 一个具有独立生命周期、文件系统、资源和网络策略的 Agent 执行实例。 |
| SandboxTemplate | Kubernetes Agent Sandbox 中由平台维护的可复用 Sandbox 配置模板。 |
| SandboxClaim | 用户或应用从 Warm Pool 申请一个 Sandbox 的 Kubernetes API 对象。 |
| SandboxWarmPool | 预先启动一组 Sandbox，供 Claim 快速领取的资源池。 |
| Warm Hit | Sandbox 申请直接领取已准备实例，没有经过完整冷启动。 |
| Tool Gateway | 代理 Agent 外部工具调用并执行身份、参数、授权、审批、限速和审计的服务。 |
| gVisor | 通过 user-space kernel 截获和实现应用系统调用、减少宿主内核暴露面的沙箱运行时。 |
| Kata Containers | 使用轻量 VM 和独立 Guest Kernel 提供更强 Pod 隔离、通过 OCI/CRI 接入 Kubernetes 的运行时。 |
| Firecracker | 基于 KVM、面向高密度 microVM 的精简 VMM；它是底层构件而非完整 Sandbox 控制面。 |
| MicroVM | 精简设备模型和 Guest OS 的轻量虚机，常用于 Serverless 与不可信代码隔离。 |
| Prompt Injection | 不可信内容诱导模型忽略预期指令或滥用工具的攻击方式，不能只靠 Sandbox Runtime 解决。 |
| Egress Proxy | 统一检查、限制和审计 Sandbox 出站连接的代理。 |

## 平台、安全与可靠性

| 术语 | 解释 |
| --- | --- |
| GPU Notebook | 运行在 GPU 计算资源上的交互式开发工作区，通常包含 JupyterLab、IDE、终端、持久 Home 和数据访问，而不只是一个 `.ipynb` 文件。 |
| Workspace | 用户可停止、恢复并重新选择计算规格的开发环境；其 Pod 生命周期应与持久 Home、数据和正式任务分离。 |
| Idle Culler | 检测长期无交互或无有效计算的工作区并停止计算资源的控制器或服务。 |
| Golden Image | 平台验证并发布的标准开发镜像，固定框架、CUDA、工具和安全补丁版本。 |
| SLI | Service Level Indicator，被测量的服务指标。 |
| SLO | Service Level Objective，指标应达到的目标。 |
| Error Budget | SLO 允许的失败或不可用预算。 |
| PDB | PodDisruptionBudget，限制自愿中断同时影响的 Pod 数。 |
| Canary | 让少量真实流量使用新版本并观察。 |
| Shadow | 复制流量到新版本但不把结果返回主请求。 |
| GitOps | 以 Git 声明作为期望状态并由控制器持续协调。 |
| Workload Identity | 用工作负载身份换取云资源短期权限，避免静态密钥。 |
| PSA | Pod Security Admission，按 Namespace 执行 Pod Security 等级。 |
| SBOM | Software Bill of Materials，软件依赖清单。 |
| Provenance | 制品由什么源码、构建和流程产生的证明。 |
| Attestation | 对构建、运行环境或硬件可信状态的可验证声明。 |
| TEE | Trusted Execution Environment，硬件保护的可信执行环境。 |
| Confidential Container | 把 Pod 运行在机密 VM 中，并结合证明和密钥释放。 |
| FinOps | 将技术资源、使用、成本和业务产出关联的运营实践。 |

## 单位和口径提醒

- GPU 利用率不等于业务有效利用率。
- GPU Allocation 是被调度占用，Usage 是实际计算，Goodput 是满足 SLO 的有效产出。
- Requests/s 无法代表不同长度 LLM 请求成本，Token/s 也不能单独代表交互体验。
- 模型参数量不等于运行显存，仍需加入精度、KV Cache、Workspace 和并行。
- 物理 GPU 数不等于可调度整组容量，拓扑和故障会产生碎片。
