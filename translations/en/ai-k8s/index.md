---
title: "AI/LLM on Kubernetes Infrastructure"
description: "A complete technical map from accelerators, big data and clusters, to training, inference, RAG, Agent and production operations"
status: stable
last_reviewed: 2026-08-14
---

# AI/LLM on Kubernetes Infrastructure

This documentation is not about "how to get a GPU Pod running", but about how to build Kubernetes into a sustainable, evolving AI/LLM infrastructure: devices can be discovered and isolated, jobs can queue fairly, data can keep up with compute, training can recover, inference can meet latency targets, models and dependencies can be traced, and the platform can be upgraded, observed and audited.

The content covers the complete chain from hardware to applications, and attempts to answer four types of questions: what each component is responsible for, when it is needed, how to verify it, and where to troubleshoot when problems arise.

[Browse by Topic](#topic-map){ .md-button .md-button--primary }
[View Reference Architecture](guides/reference-architectures.md){ .md-button }
[Run GPU Platform Experiments](guides/gpu-platform-lab.md){ .md-button }
[Go to Hands-On and Troubleshooting](practices/index.md){ .md-button }

## Infrastructure Overview

```text
用户、SDK、应用与工作流
        │
        ├─ 大数据 / RAG / Agent / 在线推理 / 训练任务
        │
Gateway、Serving、Trainer、Pipeline、Queue
        │
Kubernetes API、控制器、调度器、准入与策略
        │
Device Plugin / CDI / DRA / CNI / CSI / CRI
        │
GPU、TPU、NPU、CPU、RDMA、NVMe、对象存储
        │
供电、散热、机架、故障域与数据中心网络
```

Any layer can become the bottleneck. Low GPU utilization is not necessarily a GPU problem; it may be caused by queuing policy, CPU decoding, model download, storage throughput, network congestion, request routing, or batching parameters. When reading and troubleshooting, you should verify layer by layer along the complete request or job path.

## Where to Start

| Your Goal | Suggested Path |
| --- | --- |
| Understand from scratch how AI runs on Kubernetes | [How Kubernetes Hosts AI](foundations/kubernetes-for-ai.md) → [Cluster Architecture Design](cluster/architecture.md) → [Glossary](reference/glossary.md) |
| Build or take over a GPU cluster | [GPU Node Software Stack](cluster/gpu-node-stack.md) → [Device Management](accelerators/device-management.md) → [GPU Scheduling](gpu-scheduling.md) → [Platform Operations](platform-operations.md) |
| Choose an open-source cluster management platform | [Open-Source Cluster Management Tools and Approaches](cluster/open-source-management.md) → [Platform Operations](platform-operations.md) → [Cross-Cluster and Large-Scale GPU](cluster/multi-cluster-ai.md) |
| Choose domestic or international cloud vendor Kubernetes | [Cloud Vendor Managed Kubernetes](cluster/cloud-managed-kubernetes.md) → [Cluster Architecture Design](cluster/architecture.md) → [Heterogeneous Accelerators](accelerators/heterogeneous-accelerators.md) |
| Build a GPU Notebook development platform | [GPU Notebook Platform and Storage](development/gpu-notebook-platform.md) → [GPU Scheduling](gpu-scheduling.md) → [Data and Caching](data-storage.md) → [MLOps](mlops.md) |
| Build a big data and AI data platform | [Big Data on Kubernetes](data/big-data-on-kubernetes.md) → [Data and Caching](data-storage.md) → [Model Artifacts](data/model-artifacts.md) → [MLOps](mlops.md) |
| Build a multi-tenant training platform | [Queues and Multi-Tenancy](queue-multitenancy.md) → [Distributed Training](distributed-training.md) → [RDMA Networking](rdma-networking.md) → [Reliability](reliability.md) |
| Build a Ray large model platform | [Ray Training and Inference](ray-llm-platform.md) → [Distributed Training](distributed-training.md) → [Big Data on Kubernetes](data/big-data-on-kubernetes.md) → [Reliability](reliability.md) |
| Build online LLM inference services | [Local Running and Testing](inference/local-testing.md) → [Inference Platform Overview](llm-inference.md) → [Inference Engines](inference/engines.md) → [Serving Frameworks](inference/serving-frameworks.md) → [API Relay and Gateway Selection](inference/llm-api-relay-gateway-overview.md) → [Gateway and Routing](inference/gateway-routing.md) → [Higress in Practice](inference/higress-ai-gateway.md) |
| Plan multi-region or multi-GPU clusters | [Cluster Architecture Design](cluster/architecture.md) → [Cross-Cluster and Large-Scale GPU](cluster/multi-cluster-ai.md) → [Production Reference Architecture](guides/reference-architectures.md) |
| Build a RAG or Agent platform | [Agent Status and Trends](rag-agent/agent-landscape-2026.md) → [Agent Harness](rag-agent/agent-harness-technology-overview.md) → [HarnessRouter](rag-agent/harnessrouter-overview.md) → [DeepSeek Harness Containerization](rag-agent/deepseek-harness-runtime-containerization.md) → [Kubernetes in Practice](practices/deepseek-harness-kubernetes.md) → [Agent Sandbox Selection](rag-agent/agent-sandbox-selection.md) → [Security Governance](security-governance.md) |
| Responsible for SRE, cost or capacity | [Observability](observability.md) → [Performance Benchmarks](benchmarking.md) → [Cost and Capacity](cost-capacity.md) → [Adoption Roadmap](adoption-roadmap.md) |

## Complete Topic Map { #topic-map }

### Foundations and Architecture

- [How Kubernetes Hosts AI](foundations/kubernetes-for-ai.md): From APIs, controllers and schedulers to CRI, CNI, CSI and device interfaces.
- [AI Cluster Architecture Design](cluster/architecture.md): Workload profiling, node pools, failure domains, single-cluster and multi-cluster boundaries.
- [Kubernetes Flow Control and Service Rate Limiting](cluster/flow-control.md): APF, fair queuing, client rate limiting, GPU job admission and model API traffic governance.
- [Open-Source Kubernetes Cluster Management Tools and Approaches](cluster/open-source-management.md): From kubectl, Headlamp and GitOps, to layered selection of Rancher, Cluster API, Gardener, Karmada and OCM.
- [Mainstream Domestic and International Cloud Vendor Kubernetes](cluster/cloud-managed-kubernetes.md): Comparing ACK, TKE, CCE, EKS, GKE and AKS managed boundaries, network storage ecosystems and AI/GPU capabilities.
- [Kubernetes Cross-Cluster and Large-Scale GPU](cluster/multi-cluster-ai.md): Federation history, current capabilities such as Karmada/MultiKueue, and training whole-Job placement and regional inference architecture.
- [Karmada vs Virtual Kubelet Comparison](cluster/karmada-vs-virtual-kubelet.md): Architecture boundaries, replica semantics, failure recovery, network storage and GPU selection for cluster-level orchestration vs virtual node adaptation.
- [Ten Years of AI on Kubernetes](history.md): From GPU Pods, Operators and batch scheduling, to DRA, inference gateways and disaggregated inference.
- [Glossary](reference/glossary.md): Unifying Kubernetes, GPU, training, inference, networking, RAG and reliability terminology.

### Clusters, Nodes and Accelerators

- [GPU Node Software Stack](cluster/gpu-node-stack.md): Firmware, kernel, drivers, container runtime, CDI, Operators and node acceptance.
- [Multi-Vendor Heterogeneous Accelerators](accelerators/heterogeneous-accelerators.md): NVIDIA, AMD, Intel, TPU, Trainium/Inferentia and CPU/NPU.
- [Device Plugin, CDI and DRA](accelerators/device-management.md): Responsibilities of the three, migration paths and production selection.
- [GPU and Heterogeneous Resource Scheduling](gpu-scheduling.md): Full GPU, MIG, sharing, topology, affinity and fragmentation management.

### Queues, Elasticity and Capacity

- [Queues, Fair Sharing and Multi-Tenancy](queue-multitenancy.md): Kueue, ClusterQueue, Flavor, Cohort, priority and preemption.
- [AI Workload Elastic Scaling](scheduling/autoscaling.md): HPA, KEDA, Cluster Autoscaler, Karpenter and queue coordination.
- [GPU Cost and Capacity Planning](cost-capacity.md): Unit economics, demand forecasting, utilization, Spot and FinOps.

### Networking, Data and Model Artifacts

- [RDMA and AI High-Speed Networking](rdma-networking.md): InfiniBand, RoCE, GPUDirect, NCCL and layer-by-layer troubleshooting.
- [Contiv, OVS and Cilium Chained Networking in Practice](practices/contiv-ovs-cilium-network.md): VLAN networking, Socket LB and kube-proxy data path boundaries.
- [AI Data, Storage and Caching](data-storage.md): Object storage, shared files, local NVMe, data loading and cache hierarchy.
- [Big Data on Kubernetes](data/big-data-on-kubernetes.md): Spark, Flink, Kafka, Trino, Lakehouse, Operators, queue scheduling, and training and RAG data pipelines.
- [Model Artifacts, Distribution and Caching](data/model-artifacts.md): Formats, versions, OCI Modelcar, cross-region replication, P2P, node caching, streaming loading and cold start.

### Distributed Training

- [Distributed Training Platform](distributed-training.md): Kubeflow Trainer, KubeRay, JobSet and the training lifecycle.
- [Large Model SFT Introduction](training/sft-concepts.md): Starting from a single Q&A sample, explaining Loss, LoRA, Batch, Epoch, Checkpoint, Dense, MoE and various parallelism approaches.
- [Kubernetes Domain SFT Community Practices](training/kubernetes-domain-sft-community.md): Analyzing KubeFix, K8s Distill, KubeBench and ITBench, explaining how domain data, tool calling, security boundaries and executable evaluation should be designed.
- [SFT Training in Practice: From Single-GPU LoRA to DeepSeek V4](training/sft-from-single-gpu-to-deepseek-v4.md): Single-GPU closed loop, multi-GPU MoE, DeepSeek V4 and multi-node network benchmarks.
- [DeepSeek V4 Two-Node RDMA Training Benchmark](training/rdma-distributed-training-benchmark.md): Using three rounds of TCP/RDMA A/B, NCCL AllReduce/All-to-All and negative controls to explain which training truly benefits.
- [SwanLab Self-Hosting and SFT Metrics](training/swanlab-self-hosted.md): Official Helm deployment, PoC/production boundaries, ms-swift integration, real curves and version compatibility.
- [From W&B Local to SwanLab](training/wandb-vs-swanlab.md): Combining two years of team-based W&B Local operations records with current SwanLab benchmarks, comparing features, production complexity, migration and licensing boundaries.
- [Ray's Role in Large Model Training and Inference](ray-llm-platform.md): End-to-end boundaries of Ray Core, Data, Train, Tune, Serve, Serve LLM and KubeRay.
- [Reliability, Checkpoint and Failure Recovery](reliability.md): RPO/RTO, Spot, graceful exit and failure drills.

### LLM Inference

- [Running and Testing Large Models Locally](inference/local-testing.md): Using Ollama, llama.cpp, LM Studio, LocalAI, MLX-LM and vLLM/SGLang to verify model and application contracts.
- [LLM Inference Platform Overview](llm-inference.md): Service abstraction, runtime, request path and capacity model.
- [Inference Engine Selection](inference/engines.md): Boundaries of runtimes such as vLLM, SGLang, TensorRT-LLM, Triton and llama.cpp.
- [LLM Serving and AI Microservice Frameworks](inference/serving-frameworks.md): vLLM, KServe, AIBrix, Ray Serve, BentoML, NVIDIA NIM and application-layer frameworks.
- [LLM Inference Performance Optimization](inference/optimization.md): TTFT, TPOT, batching, KV Cache, quantization, parallelism and speculative decoding.
- [KV Cache Principles, Applications and Kubernetes](inference/kv-cache-overview.md): Attention principles, GPU memory calculations, prefix reuse, hierarchical caching, and request routing, NUMA and scaling.
- [Large Model API Relay and LLM Gateway Overview](inference/llm-api-relay-gateway-overview.md): Model aggregation, self-built unified APIs, enterprise AI Gateway, inference routing, semantic routing, security risks and selection.
- [AI Gateway and Intelligent Routing](inference/gateway-routing.md): Gateway API Inference Extension, prefix awareness, load awareness and flow control.
- [Higress AI Gateway in Practice](inference/higress-ai-gateway.md): Isolated installation, AI Proxy, token governance, observability, and same-cluster and cross-cluster integration with AIBrix.
- [Distributed and Prefill/Decode Separated Inference](inference/distributed-serving.md): Model parallelism, LeaderWorkerSet, llm-d, Dynamo and KV transfer.

### RAG, Agent and Edge

- [2026 AI Agent Landscape, Implementation Principles, and Trends](rag-agent/agent-landscape-2026.md): Product landscape, implementation principles, frameworks, risks, and evolution directions for mainstream coding, browser, and enterprise agents.
- [Agent Harness Technical Survey](rag-agent/agent-harness-technology-overview.md): Agent Loop, context, tools, state recovery, sandboxing, permissions, verification, and Kubernetes production architecture.
- [Agent RL: veRL and Miles](rag-agent/agent-rl-verl-miles-overview.md): Multi-turn trajectories, rewards and action masks, training frameworks, TITO, fully asynchronous pipelines, and Kubernetes engineering.
- [DeepSeek Search/Fetch and Agent Web Costs](rag-agent/deepseek-search-fetch-agent-cost.md): Search and retrieval roles, provider-pricing differences, and task budgeting.
- [Omarchy Linux and Agent OS Survey](rag-agent/omarchy-agent-os-overview.md): Positioning, working mechanisms, permissions, and enterprise adoption of desktop Linux, Agno, AIOS, and BrowserOS.
- [ChatGPT Dots Technical Analysis](rag-agent/chatgpt-dots-overview.md): Release timing, persistent responsibilities, memory, cloud and local execution, Codex collaboration, plus enterprise permissions and Kubernetes integration recommendations.
- [Agent Evaluation Methods Survey](rag-agent/agent-evaluation-overview.md): Scoring methods for task success, tool trajectories, failure recovery, safety, cost, and human intervention.
- [Harbor Agent Evaluation Framework Survey](rag-agent/harbor-agent-evaluation-framework.md): Task, Agent Adapter, isolated environment, Verifier, Rollout, and Kubernetes productionization.
- [Jev System One Decision Model Survey](rag-agent/jev-system-one-model-overview.md): Probabilistic decision interface without text generation, confidence, agent routing, community controversy, production architecture, and evaluation methods.
- [Jev Weekly Review](rag-agent/jev-weekly-review.md): Weekly tracking of official releases, independent evaluations, community weights, and agent applications, preserving historical results and judgments.
- [HarnessRouter Survey](rag-agent/harnessrouter-overview.md): UHP, unified Harness API, Cloud and Community Edition, security boundaries, cost, and relationship with model gateways.
- [HiRoute Agent Routing and Model Collaboration](rag-agent/hiroute-overview.md): Local routing engine from the Higress team, model selection at the parsing stage, Jev decisions, context preservation, and enterprise integration.
- [DeepSeek Harness GitHub Repository Deep Dive](rag-agent/deepseek-harness-repository-analysis.md): Source directory, Cordis plugin tree, Profile and Bundle, Agent Loop, event-sourced sessions, and capability seams.
- [DeepSeek Harness Docker, Compose, and Helm Deployment in Practice](rag-agent/deepseek-harness-runtime-containerization.md): Multi-architecture images, EROFS fixes, state persistence, StatefulSet, Helm, and security exposure boundaries.
- [From Docker to Kubernetes: DeepSeek Harness, Built-in Chromium, and DSH Plugin in Practice](practices/deepseek-harness-kubernetes.md): All-in-one browser desktop, custom DSH Plugin, Tailscale remote entry, state volumes, Cilium probe conflicts, and security boundaries.
- [RAG Infrastructure](rag-agent/rag-infrastructure.md): Ingestion, chunking, Embedding, vector databases, retrieval, reranking, and permission filtering.
- [Agent Sandbox Selection and Architecture Analysis](rag-agent/agent-sandbox-selection.md): Threat models, Kubernetes Agent Sandbox, gVisor, Kata, microVMs, and managed platform decisions.
- [OpenSandbox on Kubernetes in Practice](rag-agent/opensandbox-kubernetes-practice.md): Official Console, file and command execution, four concurrent tasks, access authentication, expiry cleanup, and real monitoring screenshots.
- [OpenKruise Agents on Kubernetes in Practice](rag-agent/openkruise-agents-kubernetes-practice.md): Warm and on-demand creation, SDK tasks, filesystem separation, expiry cleanup, and troubleshooting a resume blocked by image-reference comparison.
- [BoxLite on Kubernetes in Practice](rag-agent/boxlite-kubernetes-practice.md): Start microVMs through an embedded SDK, validate four concurrent instances, file separation, and disk recovery after Pod recreation, and inspect resource curves and a recovery-related metric discrepancy.
- [Microsandbox on Kubernetes in Practice](rag-agent/microsandbox-kubernetes-practice.md): Use KVM from an unprivileged Pod; validate four concurrent guests, Live Fork, and full memory snapshot recovery after Pod recreation, comparing disk recovery and retaining failed attempts.
- [CubeSandbox Kubernetes Deployment Prerequisites and Production Evaluation](rag-agent/cubesandbox-kubernetes.md): 60ms benchmark baseline, KVM/PVM, XFS, eBPF, Helm, and production rollout boundaries.
- [CubeSandbox Agent Adapter v0.3 Field Test](rag-agent/cubesandbox-agent-adapter-v03.md): Acceptance testing with four clients—OpenClaw, DSH, Hermes, and Codex—plus persistent leases, asynchronous Jobs, PTY, Checkpoint, Redis HA, multi-tenant identity, and migration Gates.
- [OpenClaw as an Enterprise Agent Platform Foundation](rag-agent/openclaw-enterprise-agent-platform.md): Reusable capabilities, enterprise control plane gaps, security risks, secondary development boundaries, and recommended architecture.
- [OpenClaw 2.0 Field Test: Architecture, Feature, Performance, and Migration Risk Comparison with 1.x](rag-agent/openclaw-2-real-world-review.md): Isolated installation, Control UI, Workboard, headless agents, measured metrics, doctor migration, and rollback Gates.
- [How to Rapidly Publish and Share Internal Enterprise AI Applications](rag-agent/internal-agent-app-publishing.md): Build, trial run, approval, permissions, runtime, and application catalog design for non-engineering users in business, legal, and operations.
- [AI Agents, Sandboxes, and Tool Execution](agentic-workloads.md): RuntimeClass, network boundaries, credentials, tool permissions, and auditing.
- [Edge AI and Cloud-Edge Collaboration](edge-ai.md): K3s, weak-network autonomy, device management, model OTA, and edge observability.

### Platform Engineering and Production Operations

- [GPU Notebook Platforms and Storage Selection in the LLM Era](development/gpu-notebook-platform.md): JupyterHub, Kubeflow, managed Workbench, GPU sharing, user home directories, object storage, and local caching.
- [MLOps and Platform Engineering](mlops.md): Pipelines, experiments, model registries, GitOps, and platform APIs.
- [GPU, Training, and Inference Observability](observability.md): DCGM, job metrics, TTFT/TPOT, Trace, SLOs, and alerting.
- [AI Platform Security and Governance](security-governance.md): Identity, Pod Security, image and model supply chains, and tenant isolation.
- [Performance Benchmarking, Load Testing, and Regression](benchmarking.md): Hardware, NCCL, storage, training, inference, and release gates.
- [Platform Operations, Upgrades, and Multi-Cluster](platform-operations.md): Version matrices, Canary, CRD, backup, disaster recovery, and incident response.
- [AI on K8s Adoption Roadmap](adoption-roadmap.md): From current-state assessment to a 30/60/90-day implementation plan.

### Reference Architectures and Experiments

- [Hands-On Practice, Troubleshooting, and Selection](practices/index.md): GPU Pending, low utilization, inference engine field tests, cost calculation, model distribution, Spot recovery, and security attack/defense.
- [Production Reference Architectures](guides/reference-architectures.md): Small GPU platforms, multi-tenant training, high-availability inference, disaggregated inference, and agent sandboxes.
- [Minimal GPU Platform Closed-Loop Experiment](guides/gpu-platform-lab.md): Resource discovery, GPU smoke tests, vLLM serving, network policies, cold start, and graceful shutdown.
- [AI/LLM Cluster Component Checklist](../cases/ai-cluster-component-checklist.md): Components, necessity, rationale for introduction, and acceptance criteria listed by target scenario.

## Tools Are Not Architecture

Multiple projects are usually available for the same layer, and projects may overlap. Before choosing a tool, write down the inputs, outputs, owners, and acceptance metrics first.

| Capability | Common Implementations | Questions to Answer First |
| --- | --- | --- |
| Device access | Device Plugin, CDI, DRA, vendor Operators | Do you need full-GPU, slicing, topology, or dynamic claims? |
| Batch scheduling | kube-scheduler, Kueue, Volcano | Do you need admission queues, fair sharing, or Gang Scheduling? |
| Big data compute | Spark, Flink, Trino, Ray Data | Is it batch processing, streaming state, interactive SQL, or AI data preparation? |
| Training control | Kubeflow Trainer, JobSet, KubeRay | What are the training framework, fault tolerance, and elasticity boundaries? |
| Model serving | KServe, Seldon, custom controllers | Do you need standard model APIs, multi-model, or LLM-specific capabilities? |
| Inference runtime | vLLM, SGLang, TensorRT-LLM, Triton | What are the target model, hardware, latency, and throughput? |
| Request ingress | Gateway API, Inference Extension, service mesh | Does routing need to understand model, KV Cache, and queue state? |
| Agent execution | Agent Sandbox, gVisor, Kata, managed Sandbox APIs | Are lifecycle, isolation runtime, and tool authorization already layered? |
| Observability | Prometheus, OpenTelemetry, DCGM Exporter | Can you trace from user requests down to Pod, GPU, network, and model version? |

## Content Status and Update Rules

- `stable`: Principles and production methods are relatively stable, but still need to be validated against your target Kubernetes and component versions.
- `evolving`: Upstream APIs, project boundaries, or best practices are still changing rapidly; check official release notes before going live.
- `lab`: Minimal experiments for reproduction and learning; should not be copied directly into production without review.
- `last_reviewed`: Date of the most recent review against primary sources; does not mean all dependencies are pinned to that date.
- Examples primarily express structure and validation methods; production configurations must additionally complete image pinning, capacity, identity, secrets, backup, SLOs, and change processes.

## Recommended Build Order

1. First establish a repeatable acceptance baseline for nodes, drivers, networking, storage, and GPU.
2. Then unify the resource model, queues, tenants, images, model artifacts, and observability.
3. Establish golden paths for training, online inference, offline inference, RAG, and agents respectively.
4. Use performance benchmarks, failure drills, cost metrics, and upgrade matrices to form continuous delivery gates.
5. Finally, introduce DRA, advanced topology, disaggregated inference, multi-cluster, and complex scheduling policies based on scale.

If you are planning a first-version platform, you can start from the [Production Reference Architectures](guides/reference-architectures.md) and pick the closest starting point, then use the [Adoption Roadmap](adoption-roadmap.md) to break it into phased goals.
