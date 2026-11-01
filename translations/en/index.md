---
title: "AI/LLM on Kubernetes Infrastructure"
description: "AI/LLM infrastructure engineering documentation for platform engineers, SREs, data platform, and model serving teams"
hide:
  - toc
---

# AI/LLM on Kubernetes Infrastructure Knowledge Base

[简体中文](/){ .md-button .md-button--primary }
[English](/en/){ .md-button }

Hi~Hello👋, this is runzhliu's work notebook. I am an engineer with ten years of experience in AI/LLM/Big Data/Kubernetes, and I am also a note-taking fanatic🤔 who particularly loves taking notes. This site is a collection of notes summarized from my work experience in AI/LLM Infras over the past few years, polished with the help of large language models. I hope to exchange ideas and learn together with everyone, and do a little🤏 something in the era of large models. Whether it's about the content itself or work, feel free to reach out to me😄👏! (runzhliu@163.com)

This is a set of engineering documentation for platform engineers, SREs, data platform, training, and model serving teams, systematically organizing the infrastructure knowledge required to run AI/LLM workloads on Kubernetes.

Content starts with GPU nodes, heterogeneous devices, big data, scheduling queues, RDMA, and data provisioning, then extends to distributed training, LLM inference, RAG, Agent sandboxes, observability, security, cost, and production operations. Each topic strives to explain component boundaries, selection criteria, key metrics, failure paths, and rollout checklists, rather than merely listing project names.

[Enter the Full Technical Map](ai-k8s/index.md){ .md-button .md-button--primary }
[View Production Reference Architecture](ai-k8s/guides/reference-architectures.md){ .md-button }
[Hands-on Practice & Troubleshooting](ai-k8s/practices/index.md){ .md-button }
[Browse Engineering Case Studies](cases/index.md){ .md-button }
[RSS Subscription](https://aik8s.run/rss.xml){ .md-button }

## Commonly Used Official Websites

Direct entry points to official documentation organized by technical layer. Project capabilities, version compatibility, and installation methods change quickly; always refer to the official documentation and the target version's Release Notes when in use.

<div class="grid cards" markdown>

-   **LLM Inference Engines**

    [vLLM](https://docs.vllm.ai/) · [SGLang](https://docs.sglang.io/) · [TensorRT-LLM](https://nvidia.github.io/TensorRT-LLM/) · [Triton Inference Server](https://docs.nvidia.com/deeplearning/triton-inference-server/user-guide/docs/) · [llama.cpp](https://github.com/ggml-org/llama.cpp) · [Ollama](https://docs.ollama.com/)

-   **Inference Serving & Distributed Orchestration**

    [KServe](https://kserve.github.io/website/) · [Ray / KubeRay](https://docs.ray.io/en/latest/cluster/kubernetes/) · [AIBrix](https://aibrix.readthedocs.io/latest/) · [llm-d](https://llm-d.ai/) · [NVIDIA Dynamo](https://docs.nvidia.com/dynamo/latest/)

-   **Kubernetes, GPU & Scheduling**

    [Kubernetes](https://kubernetes.io/docs/) · [NVIDIA GPU Operator](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/) · [Kueue](https://kueue.sigs.k8s.io/) · [Volcano](https://volcano.sh/docs/) · [Kubeflow](https://www.kubeflow.org/docs/)

-   **Models, Training & Communication**

    [PyTorch](https://docs.pytorch.org/docs/stable/index.html) · [Hugging Face](https://huggingface.co/docs) · [DeepSpeed](https://deepspeed.readthedocs.io/) · [NCCL](https://docs.nvidia.com/deeplearning/nccl/user-guide/)

</div>

## Documentation Coverage

<div class="grid cards" markdown>

-   **Clusters & Accelerators**

    Understand the complete path of AI workloads from the Kubernetes API to node drivers, container runtimes, and GPUs, establishing repeatable node acceptance and heterogeneous device management practices.

    [Start with the Infrastructure](ai-k8s/foundations/kubernetes-for-ai.md)

-   **Big Data, Scheduling & Distributed Training**

    Handle Spark/Flink/Kafka/Lakehouse, resource declarations, queue admission, Gang Scheduling, RDMA, data loading, Checkpoint, and failure recovery.

    [View Big Data Infrastructure](ai-k8s/data/big-data-on-kubernetes.md)

-   **LLM Inference & RAG**

    Cover inference engines, batching, KV Cache, quantization, intelligent routing, Prefill/Decode disaggregation, as well as vector retrieval and permission filtering.

    [View the Inference Technical Map](ai-k8s/llm-inference.md)

-   **Platform Engineering & Production Operations**

    Keep the platform running long-term with version matrices, benchmarks, SLOs, observability, security policies, capacity models, and release gates.

    [View the Platform Operations System](ai-k8s/platform-operations.md)

</div>

## Start by Your Task

| Current Task | Recommended Reading Path |
| --- | --- |
| First systematic understanding of AI on Kubernetes | [How Kubernetes Carries AI](ai-k8s/foundations/kubernetes-for-ai.md) → [Cluster Architecture Design](ai-k8s/cluster/architecture.md) → [Full Technical Map](ai-k8s/index.md) |
| Building a GPU or heterogeneous compute cluster | [GPU Node Software Stack](ai-k8s/cluster/gpu-node-stack.md) → [Device Management](ai-k8s/accelerators/device-management.md) → [GPU Scheduling](ai-k8s/gpu-scheduling.md) |
| Building a GPU Notebook development platform | [Notebook Platform & Storage](ai-k8s/development/gpu-notebook-platform.md) → [Data & Caching](ai-k8s/data-storage.md) → [MLOps](ai-k8s/mlops.md) |
| Building a big data and AI data platform | [Big Data on Kubernetes](ai-k8s/data/big-data-on-kubernetes.md) → [Data & Caching](ai-k8s/data-storage.md) → [Model Artifacts](ai-k8s/data/model-artifacts.md) → [MLOps](ai-k8s/mlops.md) |
| Building a multi-tenant training platform | [Queues & Multi-tenancy](ai-k8s/queue-multitenancy.md) → [Distributed Training](ai-k8s/distributed-training.md) → [RDMA Networking](ai-k8s/rdma-networking.md) → [Reliability](ai-k8s/reliability.md) |
| Building a Ray large model platform | [Ray Training & Inference](ai-k8s/ray-llm-platform.md) → [Distributed Training](ai-k8s/distributed-training.md) → [Reliability](ai-k8s/reliability.md) |
| Building an LLM online inference platform | [Inference Platform Overview](ai-k8s/llm-inference.md) → [Engine Selection](ai-k8s/inference/engines.md) → [Serving Frameworks](ai-k8s/inference/serving-frameworks.md) → [API Relay & Gateway Selection](ai-k8s/inference/llm-api-relay-gateway-overview.md) → [Intelligent Routing](ai-k8s/inference/gateway-routing.md) → [Higress Hands-on](ai-k8s/inference/higress-ai-gateway.md) |
| Building RAG or Agent services | [Agent Current State & Trends](ai-k8s/rag-agent/agent-landscape-2026.md) → [Agent Harness](ai-k8s/rag-agent/agent-harness-technology-overview.md) → [HarnessRouter](ai-k8s/rag-agent/harnessrouter-overview.md) → [RAG Infrastructure](ai-k8s/rag-agent/rag-infrastructure.md) → [Agent Sandbox Selection](ai-k8s/rag-agent/agent-sandbox-selection.md) → [Security Governance](ai-k8s/security-governance.md) |
| Responsible for stability, cost, and capacity | [Observability](ai-k8s/observability.md) → [10k-Node Cluster Optimization](ai-k8s/practices/large-scale-kubernetes-optimization.md) → [API Server Load Balancing](ai-k8s/practices/kube-apiserver-load-balancing.md) → [Multi-cluster Stability](ai-k8s/practices/kubernetes-fleet-reliability.md) → [Cost & Capacity](ai-k8s/cost-capacity.md) |

## Core Topics

### Compute & Clusters

- [How Kubernetes Carries AI](ai-k8s/foundations/kubernetes-for-ai.md)
- [AI Cluster Architecture Design](ai-k8s/cluster/architecture.md)
- [10k-Node Kubernetes Cluster Optimization in Practice](ai-k8s/practices/large-scale-kubernetes-optimization.md)
- [Kube-apiserver Load Balancing in Practice](ai-k8s/practices/kube-apiserver-load-balancing.md)
- [GPU Node Software Stack](ai-k8s/cluster/gpu-node-stack.md)
- [NVIDIA NVCRE: GPU Cluster Readiness and Production Integration](ai-k8s/practices/nvidia-cluster-readiness-engine.md)
- [Multi-vendor Heterogeneous Accelerators](ai-k8s/accelerators/heterogeneous-accelerators.md)
- [Device Plugin, CDI & DRA](ai-k8s/accelerators/device-management.md)

### Scheduling, Networking & Data

- [GPU & Heterogeneous Resource Scheduling](ai-k8s/gpu-scheduling.md)
- [Queues, Fair Sharing & Multi-tenancy](ai-k8s/queue-multitenancy.md)
- [Elastic Scaling for AI Workloads](ai-k8s/scheduling/autoscaling.md)
- [RDMA & AI High-speed Networking](ai-k8s/rdma-networking.md)
- [Big Data on Kubernetes](ai-k8s/data/big-data-on-kubernetes.md)
- [Model Artifacts, Distribution & Caching](ai-k8s/data/model-artifacts.md)

### Training & Inference

- [Distributed Training Platform](ai-k8s/distributed-training.md)
- [Multi-node Multi-GPU Training Frameworks & Failure Recovery](ai-k8s/training/distributed-training-frameworks-recovery.md)
- [LLM SFT Primer: Loss, LoRA, Batch, and Parallelism Explained in One Go](ai-k8s/training/sft-concepts.md)
- [LLM SFT Training in Practice: From Single-GPU LoRA to DeepSeek V4](ai-k8s/training/sft-from-single-gpu-to-deepseek-v4.md)
- [SwanLab Self-hosting: From Kubernetes Deployment to Real SFT Metrics](ai-k8s/training/swanlab-self-hosted.md)
- [From W&B Local to SwanLab: Two Years of Team Experiment Tracking Practice & Selection](ai-k8s/training/wandb-vs-swanlab.md)
- [Ray's Role in LLM Training & Inference](ai-k8s/ray-llm-platform.md)
- [LLM Inference Platform Overview](ai-k8s/llm-inference.md)
- [Inference Engine Selection](ai-k8s/inference/engines.md)
- [LLM Serving & AI Microservice Frameworks](ai-k8s/inference/serving-frameworks.md)
- [LLM Inference Performance Optimization](ai-k8s/inference/optimization.md)
- [LLM API Relay & LLM Gateway Survey](ai-k8s/inference/llm-api-relay-gateway-overview.md)
- [AI Gateway & Intelligent Routing](ai-k8s/inference/gateway-routing.md)
- [Higress AI Gateway: Architecture, Installation & AIBrix Integration in Practice](ai-k8s/inference/higress-ai-gateway.md)
- [Distributed & Prefill/Decode Disaggregated Inference](ai-k8s/inference/distributed-serving.md)

### Application Infrastructure & Governance

- [GPU Notebook Platform & Storage Selection in the LLM Era](ai-k8s/development/gpu-notebook-platform.md)
- [2026 AI Agent Current State, Implementation Principles & Trends](ai-k8s/rag-agent/agent-landscape-2026.md)
- [Agent Harness Technical Survey](ai-k8s/rag-agent/agent-harness-technology-overview.md)
- [DeepSeek Super-agent Analysis: From Chat Sessions to a Team Task System](ai-k8s/rag-agent/deepseek-superagent-prototype-analysis.md)
- [Omarchy Linux & Agent OS Survey](ai-k8s/rag-agent/omarchy-agent-os-overview.md)
- [ChatGPT Dots Technical Analysis: Resident Agents, Cloud Computers & Enterprise Applications](ai-k8s/rag-agent/chatgpt-dots-overview.md)
- [Agent Long-task Interruption & Resume Principles and Community Practices](ai-k8s/rag-agent/agent-long-running-durable-execution.md)
- [HarnessRouter Survey](ai-k8s/rag-agent/harnessrouter-overview.md)
- [HiRoute Technical Survey: Higress Team's Agent Routing & Model Collaboration Engine](ai-k8s/rag-agent/hiroute-overview.md)
- [RAG Infrastructure](ai-k8s/rag-agent/rag-infrastructure.md)
- [Agent Sandbox Selection & Architecture Analysis](ai-k8s/rag-agent/agent-sandbox-selection.md)
- [CubeSandbox Kubernetes Deployment Requirements & Production Evaluation](ai-k8s/rag-agent/cubesandbox-kubernetes.md)
- [CubeSandbox Agent Adapter v0.6: Multi-cluster Execution & Practice](ai-k8s/rag-agent/cubesandbox-agent-adapter-v06.md)
- [OpenClaw as an Enterprise Agent Platform Foundation](ai-k8s/rag-agent/openclaw-enterprise-agent-platform.md)
- [OpenClaw Enterprise Kubernetes Deployment in Practice: Persistence, Cross-cluster Ingress & Model Validation](ai-k8s/rag-agent/openclaw-enterprise-kubernetes-practice.md)
- [OpenClaw 2.0 Hands-on: Architecture, Features, Performance & Migration Risk Comparison with 1.x](ai-k8s/rag-agent/openclaw-2-real-world-review.md)
- [AI Agents, Sandboxes & Tool Execution](ai-k8s/agentic-workloads.md)
- [GPU, Training & Inference Observability](ai-k8s/observability.md)
- [AI Platform Security & Governance](ai-k8s/security-governance.md)
- [Platform Operations, Upgrades & Multi-cluster](ai-k8s/platform-operations.md)

## Ready-to-Use Reference Materials

- [AI/LLM Cluster Component Checklist](cases/ai-cluster-component-checklist.md): Explains by scenario which components are needed, why they are needed, when they can be omitted, and how to verify acceptance.
- [Five Production Reference Architectures](ai-k8s/guides/reference-architectures.md): Small GPU platform, multi-tenant training, high-availability inference, disaggregated inference, and Agent sandbox.
- [Minimal Closed-Loop GPU Platform Experiment](ai-k8s/guides/gpu-platform-lab.md): From GPU discovery and smoke testing to vLLM service, network policies, and cold start measurement.
- [Ten Years of AI on Kubernetes Development](ai-k8s/history.md): Understand why key interfaces and tools emerged, and the current technical mainline.
- [Glossary](ai-k8s/reference/glossary.md): Quick lookup of device, scheduling, training, inference, networking, and RAG terminology.
- [30/60/90-Day Implementation Roadmap](ai-k8s/adoption-roadmap.md): Break architectural goals into executable implementation phases.

## Practical Cases

[Engineering Cases](cases/index.md) separately collects executable checklists and real-environment records. Among them, [AI/LLM Cluster Component Checklist](cases/ai-cluster-component-checklist.md) is used to determine the scope of construction, and [K3s Cluster Upgrade and DRA Preflight](k3s-upgrade/index.md) records a real-environment version span assessment, backup, compatibility check, upgrade, and verification process.

## Content Standards

- Prioritize primary sources such as Kubernetes SIGs, official project documentation, and public specifications.
- Distinguish between stable principles, rapidly evolving upstream capabilities, and experimental configurations used only for learning.
- Selection conclusions must be tied to throughput, latency, reliability, cost, security, or operational complexity.
- Examples must demonstrate verification methods; production deployment must also cover version pinning, permissions, secrets, capacity, backup, and rollback.
- Preserve existing page URLs; organize new content by topic directory to avoid broken links when navigation changes.

It is recommended to start with the [Complete Technical Map](ai-k8s/index.md), then choose a reading path based on your current role.

## Follow the WeChat Public Account

More hands-on AI/LLM on Kubernetes practices, deployment records, and performance analysis are published on the WeChat public account **AI-K8S技术工程**. Scan the QR code with WeChat, or search for `AI-K8S技术工程` in "WeChat Search":

<p align="center">
  <img src="assets/wechat-official-account-promo.png" alt="Scan the QR code or follow the public account AI-K8S技术工程 via WeChat Search" width="900">
</p>
