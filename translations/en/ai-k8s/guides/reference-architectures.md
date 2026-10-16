---
title: "AI/LLM on Kubernetes Reference Architecture"
description: "Five reference architectures ranging from small GPU platforms, multi-tenant training, online inference, disaggregated inference to Agent sandboxes"
status: evolving
last_reviewed: 2026-08-03
---

# AI/LLM on Kubernetes Reference Architecture

A reference architecture is not a product checklist, but rather a definition of responsibilities, data flows, failure domains, and evolution boundaries. The five architectures below progressively add components, from the smallest platform to large-scale inference. Each one describes when to use it, the minimal components, key SLOs, and complexity that should not be introduced prematurely.

## 1. Architecture A: Small GPU Platform

### Applicability

- 1–8 GPUs;
- One or two teams;
- Single-node training, Embedding, fine-tuning, and ordinary LLM inference;
- The goal is to first establish repeatable delivery and observability.

### Architecture

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

### Minimal Components

- Kubernetes/K3s/RKE2 or managed Kubernetes;
- NVIDIA/AMD Device Plugin or GPU Operator;
- Object storage/managed Model Hub;
- Prometheus, Grafana, logging;
- GitOps or at least declarative Helm/Kustomize;
- Basic Gateway/Ingress;
- Job/Deployment, adding Kueue or KServe as needed.

### Key Decisions

- Whole-GPU allocation by default; development sharing uses dedicated nodes or an explicit policy;
- Keep system nodes reserved; GPU nodes can be maintained or scaled down;
- Use immutable Digests for models and images;
- Benchmark single-GPU, single-node multi-GPU, and model serving baselines first;
- Do not introduce P/D separation, multi-cluster, or complex Service Mesh prematurely.

### SLOs

- Time from GPU node join to a passing Smoke Test;
- Model cold/warm startup;
- Job success rate;
- Inference TTFT/TPOT and availability;
- Checkpoint recoverability;
- GPU allocation and utilization.

## 2. Architecture B: Multi-Tenant Distributed Training Platform

### Applicability

- 8–hundreds of GPUs;
- Multiple teams sharing training capacity;
- Multi-node multi-GPU, long training runs, Spot and priority;
- Requires fairness, topology awareness, and cost attribution.

### Architecture

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

### Core Components

- Kueue or Volcano;
- Kubeflow Trainer, KubeRay, JobSet;
- GPU/Network Operator, Multus/SR-IOV;
- Object storage, parallel file system, or cache;
- MLflow/Kubeflow Hub, Pipeline;
- Prometheus/DCGM, logging, and Tracing;
- Node autoscaling;
- GitOps, Policy, and Workload Identity.

### Key Contracts

- Jobs must be admitted as a group, never partially occupying GPUs;
- Flavors express GPU, network, region, and purchasing method;
- Nominal quota, borrowing, preemption, and priority are transparent;
- Long training runs have RPO/RTO and Checkpoints;
- Data, code, Runtime, model, and experiment are traceable;
- Faulty GPUs are automatically isolated and run diagnostics.

### Main Risks

- Total GPU capacity is sufficient but topology fragmentation occurs;
- Data loading keeps GPUs waiting;
- Preemption causes significant recomputation;
- Spot interruption and whole-group capacity unavailability;
- Notebooks occupying GPUs for extended periods;
- Conflict between queue fairness and urgent business requirements.

## 3. Architecture C: High-Availability Online LLM Inference

### Applicability

- Multi-model or multi-tenant online serving;
- Strict TTFT/TPOT, availability, and cost SLOs;
- Multiple full replicas per model;
- Requires Canary, authorization, and Token governance.

### Architecture

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

### Capacity Strategy

- Minimum Warm Replicas;
- Replicas spread across nodes/availability zones;
- Redundancy for a single failure domain;
- Scaling signals use queue/Token/latency;
- Training may only borrow explicitly designated non-protected capacity;
- Cold-start budget includes nodes, models, and warm-up.

### Release Strategy

```text
Artifact + Runtime + Gateway Policy
  → 离线质量/性能评估
  → Shadow（无副作用）
  → Stable-hash Canary
  → 指标门禁
  → 扩大流量
  → Drain 旧版本
```

### Failure Strategy

- Router falls back to a healthy load balancer on state failure;
- Model replicas leave the InferencePool before termination;
- Streaming requests have a sufficient termination grace period;
- A single model anomaly does not bring down the entire Gateway;
- Rate-limiting service failures explicitly choose Fail Open/Closed;
- Model and Runtime can be rolled back together.

## 4. Architecture D: Large-Scale Disaggregated Inference

### Applicability

- Large-scale traffic and GPU pools;
- Prefill/Decode ratio varies significantly;
- Single-node/colocated mode has been proven insufficient through benchmarking;
- High-performance networking and mature SRE capability are in place.

### Architecture

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

### Version Unit

One release must pin all of the following:

- Model Artifact;
- Prefill and Decode Runtime;
- KV Connector, NIXL/UCX;
- Router/EPP/Planner;
- Gateway Extension and CRDs;
- Driver/CUDA/ROCm;
- RDMA/Network configuration.

### Core SLOs

- Prefill Queue and TTFT;
- KV Transfer P95/P99, failures, and bytes;
- Decode Queue and TPOT;
- Goodput meeting all SLOs;
- P/D resource ratio and utilization;
- Time from request cancellation to state cleanup;
- Single Worker/node failure recovery.

### Exit Criteria

If P/D separation does not deliver stable Goodput/cost benefits over colocated mode, or if failure complexity exceeds team capability, fall back to colocated mode.

## 5. Architecture E: Agent and Untrusted Tool Execution

### Applicability

- Agents executing code, Shell, browsers, or third-party tools;
- Users submitting untrusted content;
- Requires workspace, network, and side-effect auditing.

### Architecture

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
       ├── gVisor/Kata RuntimeClass
       ├── Ephemeral Workspace
       ├── 独立 ServiceAccount
       └── Default-deny NetworkPolicy

External Tools / Data / Browser
  只通过受控代理访问
```

### Security Principles

- Prompts cannot expand platform authorization;
- Each tool is independently authorized; no generic cloud credentials are given to Agents;
- Egress is denied by default;
- Workspaces and Tokens have hard limits;
- Side Effects use approval and Idempotency;
- Untrusted execution uses an appropriate RuntimeClass or a separate cluster;
- Audit the action chain without leaking Prompts, Secrets, or personal data.

## 6. Shared Foundational Capabilities

All five architectures require:

| Capability | Minimal Requirement |
| --- | --- |
| Identity | SSO/OIDC, Workload Identity, least-privilege RBAC |
| Artifacts | Image and model Digests, Registry, signing, and traceability |
| Networking | CNI, DNS, NetworkPolicy, Gateway, RDMA as needed |
| Storage | Object storage, PVC, cache, backup, and recovery |
| Observability | Three-layer metrics for Infra, Workload, and Model, with correlation keys |
| Reliability | PDB, Checkpoint, failure domains, Runbooks, and drills |
| Delivery | GitOps, Canary, version matrix, and rollback |
| Cost | Tenant tags, allocation/utilization/output, and budgets |

## 7. Evolution Path

```text
小型 GPU 平台
  → 加入队列、模型制品和完整可观测
  → 分离训练/推理节点池
  → 多租户训练或高可用推理
  → 模型感知网关和自动扩缩容
  → 只在基准证明后引入 P/D、多集群等复杂能力
```

Each stage should establish SLOs, baselines, and failure drills before adding the next controller.

## 8. Architecture Review Template

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

## 9. General Go-Live Checklist

- [ ] Architecture is driven by workloads and SLOs, not by product count.
- [ ] Each component has exactly one clear responsibility and Owner.
- [ ] Control plane, device, data, request, and identity paths can be drawn.
- [ ] Critical state has safe fallback and recovery methods.
- [ ] Model, Runtime, policy, and network configuration are all versionable and rollback-able.
- [ ] Testing covers cold start, peak load, failure, and upgrade.
- [ ] Capacity model includes redundancy, topology, and cache warm-up.
- [ ] Monitoring can correlate tenant, model, Workload, Pod, Node, and Device.
- [ ] Untrusted code and production models use different security boundaries.
- [ ] Every advanced component has an exit condition for when it is no longer needed.

## Further Reading

- [AI on K8s Implementation Roadmap](../adoption-roadmap.md)
- [GPU Node Software Stack](../cluster/gpu-node-stack.md)
- [Distributed Training Platform](../distributed-training.md)
- [LLM Inference Platform](../llm-inference.md)
- [Multi-Node and Disaggregated LLM Inference](../inference/distributed-serving.md)
- [Agent Sandbox Selection and Architecture Analysis](../rag-agent/agent-sandbox-selection.md)
- [AI Agent, Sandbox, and Tool Execution](../agentic-workloads.md)
