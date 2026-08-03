---
title: AI/LLM on Kubernetes 参考架构
description: 从小型 GPU 平台、多租户训练、在线推理、分离式推理到 Agent 沙箱的五套参考架构
status: evolving
last_reviewed: 2026-08-02
---

# AI/LLM on Kubernetes 参考架构

参考架构不是产品清单，而是职责、数据流、故障域和演进边界。下面五套架构从最小平台到大规模推理逐步增加组件，每套都说明何时使用、最小组件、关键 SLO 和不应提前引入的复杂度。

## 一、架构 A：小型 GPU 平台

### 适用范围

- 1—8 张 GPU；
- 一个或两个团队；
- 单机训练、Embedding、微调和普通 LLM 推理；
- 目标是先建立可重复交付和可观测性。

### 架构

```text
Git / CI
  → Registry
  → Kubernetes
      ├── system node：Ingress、GitOps、Prometheus
      └── GPU node：Job、Deployment/vLLM
             ├── Device Plugin
             ├── DCGM Exporter
             └── 本地模型缓存（可选）

Object Storage
  ├── datasets
  ├── models
  └── checkpoints
```

### 最小组件

- Kubernetes/K3s/RKE2 或托管 Kubernetes；
- NVIDIA/AMD Device Plugin 或 GPU Operator；
- 对象存储/受控 Model Hub；
- Prometheus、Grafana、日志；
- GitOps 或至少声明式 Helm/Kustomize；
- 基础 Gateway/Ingress；
- Job/Deployment，按需要增加 Kueue 或 KServe。

### 关键决策

- 默认整卡，开发共享使用独立节点或明确策略；
- 保留 system 节点，GPU 节点可以维护或缩容；
- 模型和镜像使用不可变 Digest；
- 先测单卡、单机多卡和模型服务基线；
- 不提前引入 P/D 分离、多集群或复杂 Service Mesh。

### SLO

- GPU 节点加入到可运行 Smoke Test 的时间；
- 模型冷/热启动；
- Job 成功率；
- 推理 TTFT/TPOT 和可用性；
- Checkpoint 可恢复；
- GPU 分配与利用率。

## 二、架构 B：多租户分布式训练平台

### 适用范围

- 8—数百张 GPU；
- 多团队共享训练容量；
- 多机多卡、长训练、Spot 和优先级；
- 需要公平、拓扑和成本归属。

### 架构

```text
用户 / 平台 SDK
  → Kubeflow Trainer / KubeRay / JobSet
  → Kueue LocalQueue
  → ClusterQueue / Flavor / Cohort
  → Topology-aware Admission
  → GPU Training Nodes
       ├── GPU Operator
       ├── Network Operator / RDMA
       ├── DCGM / Node Health
       └── Data Cache

Object Store / Parallel FS
  ├── versioned datasets
  ├── distributed checkpoints
  └── experiment artifacts

MLflow/Kubeflow Hub + Observability + Cost
```

### 核心组件

- Kueue 或 Volcano；
- Kubeflow Trainer、KubeRay、JobSet；
- GPU/Network Operator、Multus/SR-IOV；
- 对象存储、并行文件系统或缓存；
- MLflow/Kubeflow Hub、Pipeline；
- Prometheus/DCGM、日志和 Trace；
- 节点自动扩缩容；
- GitOps、Policy 和 Workload Identity。

### 关键契约

- Job 必须成组准入，不部分占卡；
- Flavor 表达 GPU、网络、区域和购买方式；
- 名义配额、借用、抢占和优先级透明；
- 长训练具有 RPO/RTO 和 Checkpoint；
- 数据、代码、Runtime、模型和实验可追溯；
- 故障 GPU 自动隔离并运行诊断。

### 主要风险

- 总 GPU 足够但拓扑碎片；
- 数据加载让 GPU 等待；
- 抢占造成大量重算；
- Spot 中断和整组容量不可获得；
- Notebook 长期占卡；
- 队列公平与业务紧急需求冲突。

## 三、架构 C：高可用在线 LLM 推理

### 适用范围

- 多模型或多租户在线服务；
- 严格 TTFT/TPOT、可用性和成本 SLO；
- 每个模型有多个完整副本；
- 需要 Canary、权限和 Token 治理。

### 架构

```text
Client
  → External LB/WAF
  → AI Gateway
       ├── OIDC/API Key
       ├── Model RBAC
       ├── Token/Concurrency Quota
       └── HTTPRoute
              → InferencePool / Router
                    ├── Replica A：vLLM/SGLang
                    ├── Replica B：vLLM/SGLang
                    └── Replica C：Canary

KServe/Deployment/LWS
  → KEDA/HPA
  → GPU NodePool / Karpenter or Cluster Autoscaler

Model Registry/Object Storage
  → LocalModelCache/OCI Modelcar

Prometheus + OTel + Logs + Cost
```

### 容量策略

- 最小 Warm Replica；
- 副本跨节点/可用区；
- 单故障域冗余；
- 扩容信号使用队列/Token/延迟；
- 训练只能借用明确的非保护容量；
- 冷启动预算包含节点、模型和预热。

### 发布策略

```text
Artifact + Runtime + Gateway Policy
  → 离线质量/性能评估
  → Shadow（无副作用）
  → Stable-hash Canary
  → 指标门禁
  → 扩大流量
  → Drain 旧版本
```

### 故障策略

- Router 状态失败时退回健康负载均衡；
- 模型副本先离开 InferencePool 再终止；
- 流式请求有足够终止宽限期；
- 单模型异常不拖垮整个 Gateway；
- 限流服务故障时明确 Fail Open/Closed；
- 模型和 Runtime 可同时回滚。

## 四、架构 D：大规模分离式推理

### 适用范围

- 大规模流量和 GPU 池；
- Prefill/Decode 比例变化明显；
- 单机/共置模式已通过基准证明不足；
- 具备高性能网络和成熟 SRE 能力。

### 架构

```text
Gateway
  → llm-d EPP / Dynamo Router
      ├── Prefix/KV Cache Index
      ├── Flow Control
      └── Request Planner
             │
             ├── Prefill Pool
             │     └── TP/PP/EP Workers
             │
             ├── NIXL/UCX/RDMA KV Transfer
             │
             └── Decode Pool
                   └── TP/PP/EP Workers

LWS + Kueue + Topology-aware Scheduling
Model Cache + RDMA + Observability
```

### 版本单元

一次发布必须固定：

- Model Artifact；
- Prefill 和 Decode Runtime；
- KV Connector、NIXL/UCX；
- Router/EPP/Planner；
- Gateway Extension 和 CRD；
- Driver/CUDA/ROCm；
- RDMA/Network 配置。

### 核心 SLO

- Prefill Queue 和 TTFT；
- KV Transfer P95/P99、失败和字节；
- Decode Queue 和 TPOT；
- 满足全部 SLO 的 Goodput；
- P/D 资源比例和利用率；
- 请求取消到状态清理时间；
- 单 Worker/节点故障恢复。

### 退出条件

如果 P/D 分离相比共置没有稳定 Goodput/成本收益，或者故障复杂度超出团队能力，应退回共置模式。

## 五、架构 E：Agent 与不可信工具执行

### 适用范围

- Agent 执行代码、Shell、浏览器或第三方工具；
- 用户提交不可信内容；
- 需要工作区、网络和副作用审计。

### 架构

```text
User/API
  → Agent Control Plane
       ├── Session / Budget / Policy
       ├── Model Gateway
       └── Tool Gateway
              ├── 参数 Schema / AuthZ
              ├── Approval / Idempotency
              └── Audit
       │
       ▼
Agent Sandbox Controller
  → 每会话 Pod/VM
       ├── Kata/gVisor/Agent Sandbox RuntimeClass
       ├── Ephemeral Workspace
       ├── 独立 ServiceAccount
       └── Default-deny NetworkPolicy

External Tools / Data / Browser
  只通过受控代理访问
```

### 安全原则

- Prompt 不能扩大平台授权；
- 每个工具独立授权，不给 Agent 通用云凭据；
- 默认拒绝出网；
- 工作区和 Token 有硬上限；
- Side Effect 使用审批和 Idempotency；
- 不可信执行使用适当的 RuntimeClass 或独立集群；
- 审计动作链但不泄露 Prompt、Secret 和个人数据。

## 六、共享基础能力

五套架构都需要：

| 能力 | 最小要求 |
| --- | --- |
| 身份 | SSO/OIDC、Workload Identity、最小 RBAC |
| 制品 | 镜像和模型 Digest、Registry、签名和追溯 |
| 网络 | CNI、DNS、NetworkPolicy、Gateway，按需 RDMA |
| 存储 | 对象存储、PVC、缓存、备份和恢复 |
| 可观测 | Infra、Workload、Model 三层指标和关联键 |
| 可靠性 | PDB、Checkpoint、故障域、Runbook 和演练 |
| 交付 | GitOps、Canary、版本矩阵和回滚 |
| 成本 | 租户标签、分配/利用/产出和预算 |

## 七、演进路径

```text
小型 GPU 平台
  → 加入队列、模型制品和完整可观测
  → 分离训练/推理节点池
  → 多租户训练或高可用推理
  → 模型感知网关和自动扩缩容
  → 只在基准证明后引入 P/D、多集群等复杂能力
```

每一阶段都应先建立 SLO、基准和故障演练，再增加下一个控制器。

## 八、架构评审模板

```text
目标工作负载与规模：
用户和租户：
硬件与拓扑：
模型/数据/Checkpoint 路径：
控制面与数据面：
身份和信任边界：
容量与配额：
可用性和故障域：
关键 SLO：
发布和回滚：
观测与审计：
成本模型：
已知限制：
退出/简化条件：
```

## 九、通用上线清单

- [ ] 架构由工作负载和 SLO 驱动，不是产品数量驱动。
- [ ] 每个组件只有一个清楚职责和 Owner。
- [ ] 控制面、设备、数据、请求和身份路径可画出。
- [ ] 关键状态存在安全回退和恢复方法。
- [ ] 模型、Runtime、策略和网络配置都可版本化回滚。
- [ ] 测试覆盖冷启动、峰值、故障和升级。
- [ ] 容量模型包含冗余、拓扑和缓存预热。
- [ ] 监控能关联租户、模型、Workload、Pod、Node 和 Device。
- [ ] 不可信代码和生产模型使用不同安全边界。
- [ ] 每个高级组件都有不再需要时的退出条件。

## 延伸阅读

- [AI on K8s 落地路线图](../adoption-roadmap.md)
- [GPU 节点软件栈](../cluster/gpu-node-stack.md)
- [分布式训练平台](../distributed-training.md)
- [LLM 推理平台](../llm-inference.md)
- [多机与分离式 LLM 推理](../inference/distributed-serving.md)
- [AI Agent、沙箱与工具执行](../agentic-workloads.md)
