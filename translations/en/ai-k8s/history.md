---
title: "Ten Years of AI on Kubernetes"
description: "From GPU Device Plugin, Training Operators, and MLOps to DRA, Inference Gateway, and disaggregated inference"
status: stable
last_reviewed: 2026-08-03
---

# Ten Years of AI on Kubernetes

AI on Kubernetes is not a single product but a cloud-native AI infrastructure that has taken shape incrementally. The core change over the past decade is that Kubernetes has evolved from "being able to run containers that use GPUs" into a platform foundation capable of expressing distributed training, scarce accelerators, model serving, and generative inference characteristics.

## 1. Development Stages

| Stage | Core Problem | Major Changes | Representative Tools/Capabilities |
| --- | --- | --- | --- |
| 2016–2017 | How Pods use GPUs | Extended Resource, Device Plugin, HugePages, CPU Manager | NVIDIA Device Plugin, kubelet Device Manager |
| 2018–2020 | How multi-role training runs | Training Operator, Gang Scheduling, Notebook and Pipeline | Kubeflow, Volcano, MPI Operator, Argo |
| 2020–2022 | How to govern experiments to production | Pipeline, experiment tracking, model registry, unified Serving, queues | MLflow, KServe, Flyte, Kueue, KubeRay |
| 2023–2024 | How LLMs run at high throughput | Paged KV, continuous batching, GPU sharing, topology and cost | vLLM, SGLang, LWS, KServe, DCGM |
| 2025–2026 | How devices, workloads, and requests coordinate | DRA, Workload/PodGroup, Inference Extension, P/D disaggregation | DRA, JobSet, LWS, llm-d, Dynamo |

## 2. 2016–2017: Making Kubernetes See GPUs

Early Kubernetes was primarily oriented toward CPU and memory. Devices such as GPUs, FPGAs, and RDMA needed an extension mechanism that did not write vendor logic into the core.

Once the Device Plugin took shape, vendor plugins could register extended resources with the kubelet:

```yaml
resources:
  limits:
    nvidia.com/gpu: "1"
```

This solved device inventory and container allocation, but the capability was mainly integer counting. Device model, GPU memory, topology, sharing, and dynamic configuration still relied on node labels and vendor mechanisms.

During the same period, capabilities such as CPU Manager, HugePages, and Topology Manager gradually built the foundation for high-performance workloads.

## 3. 2018–2020: Training Semantics Enter Operators

Distributed training is not just multiple identical Pods. It involves different roles, ranks, rendezvous, collective startup, failure recovery, and completion states.

Controllers such as the Kubeflow Training Operator and MPI Operator wrote these semantics into CRDs. Volcano and early Gang Scheduling approaches solved the problem of "a job must acquire its entire set of resources at once," avoiding the situation where some workers start and then occupy GPUs for a long time.

Typical platforms in this stage began to include:

- Jupyter Notebook;
- Pipeline/DAG;
- Training Operators;
- Batch scheduling and queues;
- Model serving;
- Experiment metadata.

But many teams also went through the misconception that "installing full Kubeflow equals having MLOps." The existence of components does not mean that data, models, and approvals have formed a closed loop.

## 4. 2020–2022: MLOps and Platform Engineering

As scale grew, the question shifted from "can it run" to "can it be reproduced, shared, and governed":

- Which code, data, image, and configuration produced the model;
- How experiment metrics are compared;
- How models are registered, approved, and rolled back;
- How multiple teams share GPUs;
- Whether training failures are the platform's or the user's responsibility;
- Whether releases can be evaluated automatically.

MLflow, Kubeflow Pipelines, Argo Workflows, and Flyte took on experiments and workflows; KServe formed a unified inference API; Kueue brought queues, quotas, and borrowing into Kubernetes-native workload admission; KubeRay brought Ray clusters and jobs into the controller model.

## 5. 2023–2024: LLMs Change the Inference System

The request and resource model of LLMs differs from ordinary prediction services:

- Model weights and KV Cache consume large amounts of GPU memory;
- Input and output lengths are highly variable;
- Streaming connections last for a long time;
- Dynamic/continuous batching determines throughput;
- Prefix Cache makes requests state-affine;
- Tensor/Pipeline Parallel makes a single replica span multiple devices;
- Tokens, not request counts, become the unit of capacity and cost.

vLLM's PagedAttention and high-throughput serving ecosystem, SGLang's Prefix/Radix capabilities, and TensorRT-LLM's hardware optimizations made the inference engine an independent infrastructure layer.

LeaderWorkerSet began to express "one model replica consists of a Leader and multiple Workers," and the Gateway and serving control plane also needed to understand model-level state rather than merely treating Pods as stateless HTTP backends.

## 6. 2025–2026: From Pods to Devices, Workloads, and Requests

This stage has three parallel evolution tracks.

### Device Level

Dynamic Resource Allocation uses DeviceClass, ResourceSlice, and ResourceClaim so that device attributes, selection, and sharing no longer depend solely on integer extended resources. Kubernetes 1.34 advanced the core DRA API to GA, and 1.36 continued to extend Drivers, Workload Claims, and device capabilities.

### Workload Level

Kueue, JobSet, LeaderWorkerSet, Kubeflow Trainer, and others already treat multiple Pods as a single unit. The Kubernetes 1.36 Workload/PodGroup API continues to push the upstream scheduler toward understanding grouped workloads, topology, and preemption.

### Request Level

The Gateway API Inference Extension introduces InferencePool, InferenceModel, and Endpoint Picker, enabling the Gateway to select backends based on model, queue, KV Cache, and real-time state.

Systems such as llm-d and NVIDIA Dynamo further combine:

- Prefix/KV-aware Routing;
- KV Cache Index/Offload;
- Prefill/Decode disaggregation;
- NIXL/UCX/RDMA transport;
- Multi-node, multi-pool, and multi-engine;
- Flow Control and joint scaling.

## 7. Evolution of Control Objects

```text
第一阶段：Pod
  设备能不能被容器使用

第二阶段：Job / Workload
  一组 Pod 能不能整体获得资源并完成

第三阶段：Model Service
  一个模型副本如何跨 Pod、加载、发布和扩缩

第四阶段：Inference Request
  一次请求应进入哪个模型、Cache 和计算阶段
```

Each move upward does not make the layer below disappear. Request-level Routers still depend on correct Pod scheduling, and DRA still depends on drivers and the container runtime.

## 8. Infrastructure Mainline

As of 2026, a common open-source mainline can be summarized as:

```text
Kubernetes + containerd + CNI/CSI
  → GPU/Accelerator Operator + Device Plugin/DRA
  → Kueue/Volcano + JobSet/LWS
  → Kubeflow Trainer/KubeRay
  → KServe/Deployment + vLLM/SGLang/TensorRT-LLM
  → Gateway API Inference Extension/AI Gateway
  → Prometheus/DCGM/OpenTelemetry
  → MLflow/Kubeflow Hub + GitOps + Policy
```

This is not a standard answer that must be installed in full. Small teams should start with the fewest components and add the corresponding controllers only when queue, topology, cache, routing, or governance problems actually appear.

### Cross-Cluster Mainline

Cross-cluster has also gone through a process from "a unified Federation API replicating various resources" to splitting by responsibility: Cluster API manages cluster lifecycle, Karmada/OCM/GitOps manage application and policy distribution, MCS/ClusterMesh and others manage service discovery and connectivity, and MultiKueue manages dispatching batch jobs across multiple clusters by selecting one.

For AI platforms, the currently more mature boundary is usually "select the cluster globally, select the node or Endpoint locally": training places a complete Job into a single cluster that satisfies GPU topology and RDMA, while inference deploys complete model services in each region and schedules requests. For detailed evolution and architecture, see: [Kubernetes Cross-Cluster and Large-Scale GPU](cluster/multi-cluster-ai.md).

## 9. Long-Standing Engineering Principles

1. **Kubernetes is not MLOps.** It does not automatically manage data lineage, model quality, or approvals.
2. **GPU allocatable does not equal GPU effectively used.** Data, network, and batching can all be bottlenecks.
3. **More GPUs are not necessarily faster.** Parallel communication and topology can make the benefit negative.
4. **Component count is not maturity.** Reproducibility, observability, upgradeability, and rollback are.
5. **Request scheduling cannot replace capacity governance.** A Router cannot create GPUs out of thin air.
6. **Experimental features must be labeled with version and status.** The DRA, Inference, and P/D ecosystems change quickly.
7. **Quality and performance must be bound together.** A faster model with degraded quality is not the same product.
8. **Establish a baseline before introducing optimizations.** Otherwise, you cannot know the source of gains and regressions.

## 10. Further Reading

- [Kubernetes Ten-Year Retrospective](https://kubernetes.io/blog/2024/06/06/10-years-of-kubernetes/)
- [CNCF Cloud Native AI Whitepaper](https://www.cncf.io/reports/cloud-native-artificial-intelligence-whitepaper/)
- [Kubernetes 1.34 DRA GA](https://kubernetes.io/blog/2025/09/01/kubernetes-v1-34-dra-updates/)
- [Kubernetes 1.36 Workload-aware Scheduling](https://kubernetes.io/blog/2026/05/13/kubernetes-v1-36-advancing-workload-aware-scheduling/)
- [Gateway API Inference Extension](https://gateway-api-inference-extension.sigs.k8s.io/)
- [llm-d](https://llm-d.ai/)
