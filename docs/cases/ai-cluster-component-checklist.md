---
title: AI/LLM 集群组件清单
description: 按最小闭环、训练、大数据、Ray、在线推理和高级推理场景列出 Kubernetes 集群需要的组件、引入理由与验收条件
status: evolving
last_reviewed: 2026-08-04
---

# AI/LLM 集群组件清单

这份清单用于把参考架构转换成实际集群建设范围。它不要求一次安装所有项目，而是先选择目标场景，再只安装能够解决明确问题的组件。

组件分为三级：

- **必需**：该场景没有它就无法形成可运维闭环；
- **条件必需**：达到多租户、多机、高可用或特定数据规模后才需要；
- **可选**：已有等价能力或当前规模不需要时可以不装。

## 1. 先选择目标场景

| 场景 | 典型规模 | 首要目标 | 推荐起点 |
| --- | --- | --- | --- |
| A. 最小 GPU 闭环 | 1—8 GPU、单团队 | 跑通训练/推理和观测 | Kubernetes + GPU 接入 + Job/Deployment + 对象存储 |
| B. 多租户训练 | 8—数百 GPU | 队列、公平、成组调度、Checkpoint | Kueue + Trainer/JobSet 或 KubeRay |
| C. Ray 数据/训练/推理 | Python 任务多、角色动态 | 统一 Data/Train/Tune/Serve | KubeRay + RayJob/RayService |
| D. 大数据与 AI | 批流、Lakehouse、训练数据 | 数据处理、版本和实时链路 | Spark/Flink/Kafka/Trino + 对象存储 |
| E. 高可用 LLM 推理 | 多模型、多副本 | TTFT/TPOT、弹性、Canary | Gateway + KServe/AIBrix/RayService + vLLM |
| F. 大规模分离式推理 | 多机模型、大流量 | Goodput、P/D 分离、KV 传输 | LWS/Kueue + llm-d/AIBrix/Dynamo/Ray Serve LLM |

如果目前只有一个模型、少量 GPU 和一个团队，优先完成场景 A，不要直接安装场景 F 的全部组件。

## 2. 所有场景的基础组件

| 能力 | 推荐组件/实现 | 级别 | 为什么需要 | 验收证据 |
| --- | --- | --- | --- | --- |
| Kubernetes 控制面 | 托管 K8s、RKE2、K3s 或标准发行版 | 必需 | 提供资源、生命周期、网络和声明式 API | 控制面备份/升级演练，节点可安全加入和排空 |
| 容器运行时 | containerd/CRI-O | 必需 | 启动容器并连接镜像、设备和 RuntimeClass | 固定版本，GPU 容器冒烟通过 |
| CoreDNS | Kubernetes DNS | 必需 | Worker、Head、Service 和控制器依赖服务发现 | DNS 延迟、错误和容量可观测 |
| CNI | Cilium、Calico、云 CNI 等 | 必需 | Pod 网络、NetworkPolicy 和服务通信 | 跨节点吞吐、MTU、Policy 测试通过 |
| CSI | 云盘、Ceph、NFS、厂商 CSI 等 | 条件必需 | Notebook Home、Checkpoint、Kafka/Flink 状态等需要持久卷 | 创建、挂载、扩容、快照和故障恢复通过 |
| Ingress/Gateway | Gateway API Controller、Envoy Gateway、NGINX 等 | 条件必需 | 对外暴露 API、TLS、路由和统一入口 | TLS、流式响应、超时和大请求测试通过 |
| Certificate | cert-manager 或企业 PKI | 条件必需 | 自动签发和轮换 TLS 证书 | 轮换不导致服务中断 |
| GitOps | Argo CD、Flux 或受控 CI/CD | 必需 | 版本化安装、回滚和审计集群组件 | 能从 Git 重建配置并回滚上一版本 |
| Registry | OCI Registry | 必需 | 保存不可变镜像和可选模型 Artifact | Digest 拉取、签名和权限验证通过 |
| Secret/Identity | External Secrets、Vault、云 Workload Identity | 必需 | 避免长期密钥散落在 YAML 和镜像 | 凭据轮换、最小权限和审计通过 |

## 3. GPU 与节点软件栈

| 能力 | 推荐组件/实现 | 级别 | 为什么需要 | 什么时候可以不装 |
| --- | --- | --- | --- | --- |
| GPU Driver | 节点镜像、Driver Container 或 GPU Operator | 必需 | 用户态 CUDA 需要与内核驱动通信 | CPU-only 集群 |
| GPU Device Plugin | NVIDIA/AMD/Intel Device Plugin | 必需 | 把 GPU 作为 Kubernetes Resource 分配给 Pod | CPU-only 集群 |
| GPU Operator | NVIDIA GPU Operator 等 | 条件必需 | 统一驱动、Toolkit、Plugin、DCGM 和节点状态 | 已由节点镜像/云服务稳定管理全部组件 |
| Container Toolkit | NVIDIA Container Toolkit/厂商 Runtime | 必需 | 把设备和驱动库注入容器 | CPU-only 集群 |
| GPU 指标 | DCGM Exporter/厂商 Exporter | 必需 | 定位显存、利用率、XID、温度和功耗 | 不能只依赖 Pod Running |
| GPU 健康 | Node Problem Detector、GPU health agent、自研隔离 | 条件必需 | 故障卡需要自动 Cordon/隔离和复测 | 小型人工集群可暂时手工，但需告警 |
| GPU 共享 | MIG、Time-slicing、HAMi 等 | 可选 | 提高开发和小模型密度 | 正式训练/推理默认整卡或业务不需要共享 |
| DRA/CDI | Kubernetes DRA、CDI 与厂商 Driver | 可选/演进 | 表达动态设备声明、分区和更丰富拓扑 | Device Plugin 已满足目标版本与场景 |

最低验收：

```text
Node Ready
  → GPU Resource 可分配
  → Pod 内 nvidia-smi/厂商工具正常
  → 单卡矩阵计算
  → 多卡 Collective
  → 指标能关联 Pod、Node 和 GPU UUID
```

## 4. 调度、队列与多租户

| 能力 | 推荐组件 | 级别 | 为什么需要 | 可不安装的条件 |
| --- | --- | --- | --- | --- |
| 默认 Pod 调度 | kube-scheduler | 必需 | 处理资源、Affinity、Taint 和拓扑约束 | 不可替代的基础组件 |
| 批任务准入 | Kueue | 条件必需 | 在创建大量 Pod 前检查配额、优先级和 Flavor | 单团队、少量任务且无排队需求 |
| Gang 调度 | Kueue、Volcano、YuniKorn | 多机必需 | 避免部分 Worker 占卡但任务无法启动 | 只运行单 Pod/单机任务 |
| 拓扑感知 | Kueue TAS、Scheduler Plugin/厂商方案 | 多机条件必需 | TP/训练需集中到高速网络和合适故障域 | 单节点任务 |
| 优先级与抢占 | PriorityClass + Kueue/调度器 | 多租户必需 | 保护在线服务，允许批任务有序让路 | 单团队无共享 |
| 节点扩缩 | Cluster Autoscaler、Karpenter、云 Autoscaler | 可选/条件必需 | Pending 工作负载驱动节点供给 | 固定物理集群无自动供给能力 |
| Policy | Kyverno、Gatekeeper、ValidatingAdmissionPolicy | 条件必需 | 限制特权、Tag、HostPath 和无资源请求 | 极小受信实验集群可先使用评审流程 |

Kueue、Volcano 和 YuniKorn 不一定全部安装。应根据“准入队列”还是“替换 Scheduler 的 Gang/队列能力”选择主路径，避免同一工作负载被多个调度控制面管理。

## 5. 数据、存储与模型制品

| 能力 | 推荐组件/实现 | 级别 | 为什么需要 |
| --- | --- | --- | --- |
| 权威对象存储 | S3/GCS/OSS/COS、MinIO/Ceph RGW 等 | 必需 | 保存数据集、Checkpoint、模型和日志，独立于 Pod 生命周期 |
| 共享文件 | 云文件、CephFS、NFS、并行文件系统 | 条件必需 | 兼容 POSIX、Notebook Home、多 Rank Checkpoint |
| 本地高速盘 | NVMe、Local PV、`emptyDir` with size limit | 条件必需 | Shuffle、Spill、模型缓存和数据热层 |
| 模型 Registry | MLflow、Kubeflow Model Registry/Hub、自研 Catalog | 条件必需 | 管理模型元数据、阶段、评估和血缘 |
| OCI Registry | Harbor、Zot、Quay、GitLab Registry、Artifactory 或云厂商 Registry | 必需 | 保存不可变镜像、OCI 模型制品、签名和 SBOM；选型见[模型制品与分发](../ai-k8s/data/model-artifacts.md#7-oci-registry-harbor) |
| 模型分发 | OCI Modelcar、KServe LocalModel、P2P/节点缓存、自研 DaemonSet | 大模型条件必需 | 权重很大时降低冷启动和对象存储热点 |
| Dataset Catalog | Iceberg/Delta/Hudi Catalog、数据 Catalog | 数据平台条件必需 | 训练绑定 Snapshot、Schema 和权限 |
| 数据/模型签名 | Digest、Cosign、SBOM/Model BOM | 生产必需 | 确认进入训练和推理的制品不可变、可审计 |

不建议把所有数据、模型和 Checkpoint 放在一个巨大 RWX PVC，也不建议通过容器镜像分发频繁变化的数百 GB 权重。

## 6. 分布式训练组件

| 能力 | 推荐组件 | 级别 | 为什么需要 | 选择提示 |
| --- | --- | --- | --- | --- |
| 训练控制器 | Kubeflow Trainer | 条件必需 | 用 TrainJob/Runtime 标准化框架启动和生命周期 | 多框架、平台模板优先 |
| 通用多 Job 编排 | JobSet | 条件必需 | 表达 Leader/Worker 等多个 ReplicatedJob | 自研训练 API 或框架无关场景 |
| Ray 训练 | KubeRay + RayJob/Ray Train | 条件必需 | Python 数据、训练、Tune、后训练角色统一 | 已选择 Ray 生态时使用 |
| 集合通信 | NCCL/RCCL、Gloo、MPI | 多 GPU 必需 | 梯度、参数和状态同步 | 随框架镜像安装并做基准 |
| RDMA | Network Operator、Multus、SR-IOV/RDMA Device Plugin | 多机条件必需 | 降低 Collective 延迟、提高带宽 | 普通以太网能满足小规模基线时可后置 |
| 实验追踪 | MLflow、Weights & Biases、自研 | 生产必需 | 关联代码、数据、参数、指标和 Artifact | 选择一个权威系统 |
| Workflow | Argo Workflows、Kubeflow Pipelines、Flyte | 条件必需 | 编排数据、训练、评估和发布依赖 | 单一 Job 可先不用 |

Trainer、JobSet 和 KubeRay 是不同执行路径，不应为了“组件齐全”全部成为用户必选项。平台通常提供一条黄金路径，再为特殊工作负载保留另一条。

## 7. Ray 场景组件

| 组件 | 级别 | 为什么需要 | 关键配置 |
| --- | --- | --- | --- |
| KubeRay Operator | 必需 | 管理 RayCluster、RayJob、RayService 生命周期 | 与 Ray 版本锁定、Webhook/CRD 升级 |
| RayJob | 批任务必需 | 为数据、训练、Tune 和批推理创建临时 RayCluster | `shutdownAfterJobFinishes`、Checkpoint、Kueue |
| RayService | 在线服务必需 | 管理 RayCluster + Serve Application、高可用和升级 | Serve Config、最小副本、GCS 故障策略 |
| Kueue Ray 集成 | 多租户条件必需 | 在创建 Head/Worker 前完成配额准入 | 固定/弹性 Worker Group 与 Feature Gate |
| 对象存储 | 必需 | 保存 Checkpoint、结果和 Dataset | Workload Identity、不可变路径 |
| Object Store Spill | 条件必需 | 内存不足时保护大对象处理 | NVMe/PVC、磁盘水位与清理 |
| Prometheus/Grafana | 必需 | 观察 Task/Actor、Object Store、Data、Train、Serve | 关联 Ray CR、Pod、GPU 和模型 |
| HA Redis/GCS FT | 在线高可用可选 | RayService Head/GCS 恢复 | 只按官方支持矩阵启用并演练 |

Ray 专题见[Ray 在大模型训练与推理中的角色](../ai-k8s/ray-llm-platform.md)。

## 8. 大数据 on Kubernetes 组件

| 能力 | 推荐组件 | 级别 | 为什么需要 |
| --- | --- | --- | --- |
| 批处理 | Spark 原生/Kubeflow Spark Operator/Apache Spark Operator | 条件必需 | ETL、语料处理、表维护和大规模 Join |
| 流处理 | Flink Kubernetes Operator | 实时场景必需 | CDC、事件时间、有状态计算和 Checkpoint |
| 事件日志 | Kafka + Strimzi | 实时场景必需 | CDC、反馈、日志和流量缓冲 |
| 交互 SQL | Trino | 可选/分析场景必需 | Lakehouse 查询、联邦数据探索 |
| 开放表格式 | Iceberg/Delta/Hudi | Lakehouse 必需 | Snapshot、事务、Schema/Partition 演进 |
| Catalog | REST/Hive/Glue/Nessie 等目标 Catalog | Lakehouse 必需 | 表名、元数据指针、访问和并发提交 |
| Workflow | Airflow/Argo/Flyte | 条件必需 | 跨 Spark/Flink/质量/训练依赖 |
| 队列 | Kueue/Volcano/YuniKorn | 共享集群条件必需 | 防止 ETL 与训练/推理无序争抢资源 |

不要因为 Spark、Flink、Kafka 都能运行在 Kubernetes，就把所有状态和计算放进同一个节点池。Kafka/Flink 常驻状态服务、Spark 弹性批任务和 GPU 训练需要不同的可用性与扩缩策略。

## 9. LLM 推理与微服务组件

| 层 | 推荐组件 | 级别 | 为什么需要 | 什么时候不需要 |
| --- | --- | --- | --- | --- |
| 推理引擎 | vLLM、SGLang、TensorRT-LLM、Triton | 必需 | 加载模型、Batch、KV Cache 和执行 Token 计算 | 使用外部托管 API |
| 基础部署 | Deployment/StatefulSet + Service | 必需 | 最小模型服务生命周期 | 被 KServe/AIBrix/RayService 生成时不手写 |
| Serving 控制面 | KServe | 条件必需 | 标准模型 API、Runtime、Canary 和模型加载 | 单模型且 Helm/Deployment 已满足 |
| LLM 控制面 | AIBrix | 可选/规模化条件必需 | LLM Gateway、路由、Autoscaling、LoRA 和 KV | 少量副本、无缓存/路由专用需求 |
| 组合式服务 | Ray Serve/BentoML | 可选 | 多步骤 Python AI 微服务和独立扩缩 | 单一模型 Endpoint |
| 企业 Runtime | NVIDIA NIM/NIM Operator | 可选 | 厂商验证、模型 Profile、缓存和支持周期 | 开源 Runtime 自主管理已满足 |
| 智能 Gateway | Gateway API Inference Extension、AIBrix/Envoy AI Gateway | 多模型条件必需 | 模型、队列、Prefix/KV 和优先级感知路由 | 单模型单副本 |
| 多机副本 | LeaderWorkerSet | 多机条件必需 | 一个模型副本由 Leader + 多 Worker 构成 | 模型可放入单 Pod |
| P/D/KV 平台 | llm-d、AIBrix、Dynamo、Ray Serve LLM | 高级可选 | Prefill/Decode 独立扩缩和 KV 传输 | 共置推理已满足 SLO |
| 推理弹性 | KEDA/HPA、控制面内置 Autoscaler | 条件必需 | 根据 Queue/Token/延迟扩大副本 | 固定小规模且人工容量足够 |

选择原则见[LLM Serving 与 AI 微服务框架](../ai-k8s/inference/serving-frameworks.md)。同一个服务只能有一个副本数 Owner、一个主路由 Owner 和一个模型生命周期 Owner。

## 10. RAG、Agent 与应用层

| 能力 | 推荐组件/实现 | 级别 | 为什么需要 |
| --- | --- | --- | --- |
| 向量检索 | Milvus、Qdrant、Weaviate、pgvector、托管服务 | RAG 必需 | 保存 Embedding 并执行 ANN + Metadata Filter |
| Embedding/Reranker | 独立模型服务、NIM、vLLM/TEI 等 | RAG 必需 | 将生成模型与检索模型独立扩缩和发布 |
| 文档流水线 | Kafka/Flink、Job、Ray/Spark、自研 | 条件必需 | 解析、切分、权限和增量索引 |
| Agent/Workflow | Dify、LangGraph、LlamaIndex、Haystack、自研 | 可选 | 编排 Prompt、工具、状态和业务流程 |
| Tool Gateway | 自研/平台网关 | Agent 生产必需 | 统一鉴权、审批、限流、审计和凭据代理 |
| Sandbox | Kubernetes Agent Sandbox、gVisor、Kata、MicroVM | 执行不可信代码时必需 | 限制 Agent 代码/浏览器/Shell 对宿主和网络的影响 |

应用框架不替代 GPU Serving。推荐让 Dify/LangGraph 等通过内部 AI Gateway 调用稳定模型 API。

## 11. 可观测性与运营

| 能力 | 推荐组件 | 级别 | 为什么需要 |
| --- | --- | --- | --- |
| 指标 | Prometheus + 长期存储 | 必需 | 统一集群、GPU、训练、数据和推理指标 |
| 展示 | Grafana | 必需 | 容量、SLO、故障和成本视图 |
| 日志 | Loki/ELK/OpenSearch/云日志 | 必需 | 聚合多 Pod、多 Rank 和控制器日志 |
| Trace | OpenTelemetry + Tempo/Jaeger | 在线链路条件必需 | 分解 Gateway、检索、Prefill、KV 和 Decode |
| GPU 指标 | DCGM/厂商 Exporter | 必需 | 设备级利用率、显存、健康和功耗 |
| 成本 | OpenCost/Kubecost/云账单 + GPU 归属 | 多租户条件必需 | Chargeback、闲置和单位 Token/训练成本 |
| 告警 | Alertmanager/On-call 平台 | 必需 | 把 SLO 和容量风险转为可响应事件 |

至少保留以下关联键：Namespace、Tenant、Queue、Job/Service、Pod、Node、GPU UUID、模型版本、数据 Snapshot、镜像 Digest。

## 12. 安全与治理

| 能力 | 推荐组件/机制 | 级别 | 为什么需要 |
| --- | --- | --- | --- |
| 身份 | OIDC、Workload Identity、SPIFFE/SPIRE（可选） | 必需 | 用户和工作负载都需要稳定身份 |
| RBAC | Kubernetes RBAC + 平台授权 | 必需 | 限制 CRD、Secret、Pod 和模型操作 |
| 网络 | NetworkPolicy、Egress Proxy、WAF | 必需 | 防止横向移动和未审计外联 |
| Pod 安全 | Pod Security、Kyverno/Gatekeeper | 必需 | 限制特权、HostPath、Root 和危险 Capability |
| 供应链 | 签名、SBOM、扫描、Admission Policy | 生产必需 | 防止未验证镜像、模型和依赖进入集群 |
| Secret | Vault/External Secrets/KMS | 必需 | 凭据不进入 Git、镜像和用户 Notebook |
| 审计 | Kubernetes Audit、Gateway/模型/工具调用审计 | 生产必需 | 追踪谁部署、访问和修改了什么 |

## 13. 五套可执行组件包

### 包 A：最小 GPU 推理/微调

```text
Kubernetes + CNI/CSI
GPU Driver/Device Plugin + DCGM
Registry + Object Storage
Job + Deployment + vLLM
Gateway/Ingress + TLS
Prometheus/Grafana + Logs
GitOps + Secret/Identity
```

暂不安装：Kueue、KServe、AIBrix、Ray、LWS、P/D 平台。先证明单模型性能、冷启动、发布和故障恢复。

### 包 B：多租户训练

在包 A 上增加：

```text
Kueue（或 Volcano/YuniKorn 主路径）
Kubeflow Trainer/JobSet（或 KubeRay 主路径）
RDMA/Network Operator（多机需要）
MLflow/Model Registry
Workflow
共享/并行存储 + Checkpoint
成本与队列看板
```

### 包 C：Ray 大模型平台

在基础层上增加：

```text
KubeRay Operator
RayJob + Kueue
Ray Data / Train / Tune
RayService / Ray Serve LLM
对象存储 + Object Store Spill
Ray/Serve 指标、日志和 Dashboard 受控访问
```

训练和在线服务分别使用 RayJob 与 RayService，不共享同一故障域。

### 包 D：大数据与 AI

```text
Strimzi/Kafka（实时）
Flink Operator（流状态）
Spark（批处理）
对象存储 + Iceberg/Delta/Hudi + Catalog
Trino（交互 SQL）
Workflow + 数据质量/Lineage
CPU/NVMe 数据节点池
Ray Data 或 GPU ETL（最后一公里，可选）
```

### 包 E：规模化在线推理

在包 A 上按目标选择一条控制面：

```text
Gateway API/企业 Gateway
+ KServe 或 AIBrix 或 RayService/NIM Operator
+ vLLM/SGLang/NIM Runtime
+ 模型节点缓存
+ KEDA/HPA/专用 Autoscaler
+ LWS/Kueue（多机副本）
+ llm-d/AIBrix/Dynamo/Ray Serve LLM（仅 P/D 需要）
+ OTel Trace、Token/KV/Queue 指标
```

不要把 KServe、AIBrix、RayService 和 NIM Operator 全部叠在同一个模型服务上。

## 14. 推荐安装顺序

1. Kubernetes、CNI、CSI、DNS 和节点基线；
2. GPU 驱动、Device Plugin、Runtime 和 DCGM；
3. Registry、对象存储、Secret/Identity 和 GitOps；
4. Prometheus、日志、告警和审计；
5. 原生 Job 与 `Deployment + vLLM` 最小闭环；
6. 根据场景选择 Kueue + 训练控制器，或 KubeRay；
7. 根据数据场景增加 Spark/Flink/Kafka/Lakehouse；
8. 根据服务规模选择 KServe、AIBrix、Ray Serve 或 NIM；
9. 只有基准证明需要时增加多机、P/D、KV Offload 和多集群；
10. 每增加一层都补充升级、备份、故障和回滚演练。

## 15. 集群级验收清单

- [ ] 每个组件对应一个明确需求和 Owner；
- [ ] 同类能力没有多个控制器同时写同一资源；
- [ ] 所有版本进入 Kubernetes、Driver、CUDA、框架、CRD 兼容矩阵；
- [ ] GPU 单卡、多卡、跨节点和故障卡隔离基线完成；
- [ ] Job 能排队、准入、运行、保存 Checkpoint 并回收；
- [ ] 模型能冷启动、预热、接流量、Drain 和回滚；
- [ ] 数据、模型、镜像和配置均使用不可变版本；
- [ ] 对象存储、共享盘、NVMe 和网络完成容量测试；
- [ ] 指标和日志能从业务请求/训练 Run 追到 Pod、Node 与 GPU；
- [ ] 控制面、Operator、Gateway、Head 和状态存储故障完成演练；
- [ ] Namespace、RBAC、Queue、NetworkPolicy 和凭据隔离通过测试；
- [ ] 集群可在 Git、备份和外部制品基础上重建；
- [ ] 组件升级有 Canary、回滚和 CRD 兼容方案；
- [ ] 能回答“删掉这个组件会失去什么能力”。

## 延伸阅读

- [AI/LLM on Kubernetes 参考架构](../ai-k8s/guides/reference-architectures.md)
- [AI on Kubernetes 落地路线图](../ai-k8s/adoption-roadmap.md)
- [大数据 on Kubernetes](../ai-k8s/data/big-data-on-kubernetes.md)
- [Ray 在大模型训练与推理中的角色](../ai-k8s/ray-llm-platform.md)
- [LLM Serving 与 AI 微服务框架](../ai-k8s/inference/serving-frameworks.md)
- [GPU 平台最小闭环实验](../ai-k8s/guides/gpu-platform-lab.md)
