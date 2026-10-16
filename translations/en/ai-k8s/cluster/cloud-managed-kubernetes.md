---
title: "Kubernetes Offerings from Major Cloud Providers in China and Abroad"
description: "Comparing the managed boundaries and AI/GPU capabilities of Alibaba Cloud ACK, Tencent Cloud TKE, Huawei Cloud CCE, AWS EKS, Google GKE, and Azure AKS"
status: evolving
last_reviewed: 2026-08-04
---

# Kubernetes Offerings from Major Cloud Providers in China and Abroad

What managed Kubernetes offerings from cloud providers have in common is that they manage the API Server, etcd, and control plane high availability, and integrate Kubernetes with the cloud's own compute, networking, storage, load balancing, identity, and observability services. The differences lie less in whether `kubectl` can be used, and more in who manages the data plane, whether nodes can be customized, the network model, heterogeneous compute, autoscaling, version cadence, and the depth of cloud service integration.

This article covers Alibaba Cloud ACK, Tencent Cloud TKE, and Huawei Cloud CCE, which are common in China, as well as AWS EKS, Google GKE, and Azure AKS, which are common overseas. Features, regions, quotas, and pricing change frequently; before going live, you must verify against the official console, documentation, and SLA for the target region and target version.

## 1. First, Understand the Managed Boundary

```text
云厂商负责
  机房和基础云 → 托管控制面 → 部分系统组件和升级能力

共同责任
  VPC/子网 → 节点池 → CNI/CSI → 身份 → 可观测 → 备份

用户负责
  Namespace/RBAC → Operator → 训练/推理 → 数据/模型 → SLO
```

"Managed Kubernetes" does not mean the cloud provider automatically handles the following:

- Choosing the right Kubernetes and node OS upgrade windows;
- Verifying GPU driver, CUDA, RDMA, training framework, and inference engine compatibility;
- Establishing queues, fair sharing, Gang scheduling, and Checkpointing for training;
- Establishing capacity, canary releases, routing, model distribution, and latency SLOs for inference;
- Backing up user-created Kubernetes objects, PV data, and external dependencies;
- Guaranteeing that a given GPU model has sufficient inventory in the target region at all times.

Fully managed or Autopilot modes typically reduce node operations, but they also restrict privileged containers, custom kernels, drivers, RuntimeClass, HostPath, DaemonSets, or network plugins. An AI/GPU platform should not default to these modes simply because they are "operations-free."

## 2. Cloud Providers in China

### Alibaba Cloud ACK

Alibaba Cloud Container Service for Kubernetes (ACK) offers managed clusters, Serverless, Edge, and cluster forms oriented toward the Lingjun intelligent computing platform. Production clusters are typically evaluated starting from the ACK managed cluster Pro edition; the control plane is managed by Alibaba Cloud, and worker nodes can use ECS, GPU instances, and certain bare metal/Lingjun resources.

Key characteristics:

- Integrates with ECS, SLB, cloud disks, NAS, CPFS, OSS, ACR, and Cloud Monitor;
- Provides VPC/ENI-oriented container networking and CSI storage access;
- Node pools, cluster upgrades, component management, and elasticity capabilities are relatively complete;
- ACK Edge targets cloud-edge collaboration, and ACK Serverless targets workloads that do not require long-term node maintenance;
- The Cloud-Native AI Suite covers heterogeneous resources, GPU sharing, topology awareness, queue scheduling, data access acceleration, and training and inference toolchains;
- ACK Lingjun targets large-scale AI/HPC, with enhanced multi-card topology, eRDMA, shared GPU, and batch job scheduling.

Best suited for: teams already heavily using Alibaba Cloud networking, storage, ACR/OSS/CPFS, or teams that need to build an integrated training, inference, and big data platform in mainland China regions.

Caveats: ACK cluster types and AI Suite components differ in version, specification, and billing; enhanced capabilities such as shared GPU, scheduling, and data acceleration are not equivalent to upstream projects with the same name. Before migration, confirm resource names, CRDs, images, drivers, and monitoring metrics.

References: [ACK Product Introduction](https://help.aliyun.com/zh/ack/product-overview/product-introduction), [ACK Cloud-Native AI Suite](https://help.aliyun.com/zh/ack/cloud-native-ai-suite/product-overview/cloud-native-ai-suite-overview), [ACK Heterogeneous Computing](https://help.aliyun.com/zh/ack/ack-managed-and-ack-dedicated/user-guide/overview-5/)

### Tencent Cloud TKE

Tencent Cloud Container Service (TKE) offers standard clusters, Serverless/super nodes, edge, and registered node modes. A single cluster can combine regular nodes, Kubernetes-optimized native nodes, super nodes, and external nodes managed over dedicated connections or the public internet, depending on the scenario.

Key characteristics:

- Integrates with CVM, CLB, CBS, CFS, COS, TCR, and the Tencent Cloud observability system;
- Supports Global Router, VPC-CNI, and in some hybrid cloud scenarios, Cilium Overlay networking modes;
- Native nodes focus on rapid provisioning, node lifecycle, and resource efficiency;
- Super nodes provide Serverless-like Pod compute and elasticity;
- Registered nodes are suitable for bringing nodes in IDCs or other locations under TKE management, but network, storage, and cloud API reachability must be designed separately;
- qGPU provides fine-grained sharing and isolation of GPU memory and compute, and is tied to TKE native nodes;
- The product system also includes AI Agent-oriented sandboxes, cross-region compute, and other capabilities; specific maturity and region support must be verified against the target version.

Best suited for: teams whose business already relies heavily on Tencent Cloud, that care about online service elasticity, mixed node forms, GPU sharing, or that need to combine some IDC resources with a public cloud control plane.

Caveats: Regular nodes, native nodes, super nodes, and registered nodes differ in lifecycle, billing, observability, GPU capabilities, and limitations. qGPU is not supported on all node types; VPC-CNI is also constrained by subnet IPs, ENI counts, and availability zones.

References: [TKE Product Overview](https://intl.cloud.tencent.com/zh/document/product/457/51208), [TKE Nodes and Product Forms](https://cloud.tencent.com/product/tke), [TKE qGPU](https://cloud.tencent.com/document/product/457/61448), [TKE VPC-CNI](https://intl.cloud.tencent.com/zh/document/product/457/38970)

### Huawei Cloud CCE

Huawei Cloud Cloud Container Engine (CCE) offers CCE Standard, CCE Turbo, and CCE Autopilot. Standard targets general-purpose managed Kubernetes; Turbo strengthens VPC direct connectivity, networking, and scheduling performance; Autopilot further manages nodes and bills based on workload resource usage.

Key characteristics:

- Integrates with ECS, bare metal, ELB, EVS, SFS, OBS, SWR, and Cloud Monitor;
- Covers x86, Arm, NVIDIA GPU, and Ascend NPU simultaneously;
- The CCE AI Suite provides GPU/NPU drivers, device access, virtualization, monitoring, and fault governance;
- The Volcano Scheduler combines with CCE, GPU/NPU, and CloudMatrix topology to provide queues, Gang scheduling, priorities, topology awareness, and batch job scheduling;
- CCE Turbo uses a high-performance VPC-oriented container network, suitable for scenarios more sensitive to network latency and throughput;
- Ascend NPU, vNPU, and Hypernode topology are important differentiators in its AI infrastructure.

Best suited for: teams adopting Huawei Cloud infrastructure, needing heterogeneous NVIDIA and Ascend compute, or wanting to use Volcano to build large-scale training, inference, and batch processing platforms.

Caveats: Standard, Turbo, and Autopilot cannot be freely converted between each other after creation; the network model, VPC/subnet, availability zones, and control plane specifications are typically early architectural decisions. GPU/NPU virtualization depends heavily on the cluster, OS, kernel, driver, plugin, and hardware model compatibility matrix.

References: [CCE Product Introduction](https://support.huaweicloud.com/intl/zh-cn/productdesc-cce/cce_productdesc_0001.html), [CCE Product Features](https://support.huaweicloud.com/productdesc-cce/cce_productdesc_0014.html), [CCE Cloud-Native AI Suite](https://support.huaweicloud.com/intl/zh-cn/usermanual-cce/cce_10_0973.html)

## 3. Cloud Providers Overseas

### AWS EKS

Amazon Elastic Kubernetes Service (EKS) offers EKS Standard and EKS Auto Mode. Standard manages the Kubernetes control plane, and the data plane can use Managed Node Groups, self-managed nodes, Karpenter, Fargate, or Hybrid Nodes; Auto Mode further manages nodes, scaling, networking, load balancing, DNS, block storage, and part of the GPU software stack.

Key characteristics:

- Deep integration with IAM, VPC CNI, Elastic Load Balancing, EBS/EFS/FSx, S3, ECR, CloudWatch, and Managed Prometheus;
- Managed Node Groups provide node creation, updates, draining, and replacement;
- Karpenter and Auto Mode can dynamically select and create EC2 instances based on pending Pod requirements;
- Supports NVIDIA GPU, AWS Trainium/Inferentia, the Neuron SDK, and EFA high-speed networking;
- EKS Auto Mode includes some NVIDIA/Neuron drivers and Device Plugins by default, reducing GPU node software maintenance;
- EKS Hybrid Nodes and EKS Anywhere cover hybrid cloud and on-premises scenarios, but the responsibility boundary differs from public cloud EKS.

Best suited for: teams for which AWS is the primary cloud platform, that need a rich selection of EC2 instance types and Spot, that rely on IAM/VPC/S3/FSx, or that plan to use Trainium/Inferentia and EFA.

Caveats: Standard, Managed Node Groups, Karpenter, Fargate, and Auto Mode are different data plane models. Auto Mode nodes are more immutable and restrict direct login and customization; the support matrices for EFA Device Plugins, DRA, Karpenter, and Auto Mode also differ. Large-scale training requires determining the AMI, EFA, GPU/Neuron topology, and capacity reservation approach during the selection phase.

References: [Amazon EKS](https://docs.aws.amazon.com/eks/latest/userguide/what-is-eks.html), [EKS Auto Mode](https://docs.aws.amazon.com/eks/latest/userguide/automode.html), [EKS GPU/Neuron](https://docs.aws.amazon.com/eks/latest/userguide/auto-accelerated.html), [EKS EFA](https://docs.aws.amazon.com/eks/latest/userguide/device-management-efa.html)

### Google GKE

Google Kubernetes Engine (GKE) offers two operating modes: Standard and Autopilot. Standard lets platform teams directly control node pools and most infrastructure settings; Autopilot has Google manage nodes, scaling, security constraints, and more default configurations. GKE also currently supports running some workloads in Autopilot mode within Standard clusters via ComputeClass.

Key characteristics:

- Integrates with VPC, Cloud Load Balancing, Persistent Disk/Hyperdisk, Filestore, Cloud Storage, Artifact Registry, and Cloud Monitoring;
- Release Channels, automatic upgrades, and automatic repair are mature;
- Autopilot targets reduced node operations, while Standard targets privileged, custom networking, and special hardware requirements;
- Supports both NVIDIA GPU and Google TPU; TPUs are expressed as Slices, topologies, and atomic node pools;
- ComputeClass can declare candidate hardware, GPU, and node provisioning preferences;
- GKE Fleet, Config Sync, and other capabilities can be used for multi-cluster governance, but further bind to the Google Cloud platform model.

Best suited for: teams that want a mature managed Kubernetes experience, need the TPU/JAX/Google AI ecosystem, or want to unify general-purpose and accelerator workloads on GKE.

Caveats: Autopilot imposes constraints on privileged workloads, node customization, and certain system components; GPU/TPU billing and request rules differ from ordinary Pods. Multi-host TPU Slices are typically created, repaired, and scaled as complete topologies and cannot be treated as ordinary node pools whose members can be added or removed independently.

References: [GKE Mode Selection](https://docs.cloud.google.com/kubernetes-engine/docs/concepts/choose-cluster-mode), [GKE Autopilot vs. Standard Comparison](https://docs.cloud.google.com/kubernetes-engine/docs/resources/autopilot-standard-feature-comparison), [GKE GPU](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/gpus), [GKE TPU](https://docs.cloud.google.com/kubernetes-engine/docs/concepts/tpus)

### Azure AKS

Azure Kubernetes Service (AKS) offers AKS Standard and AKS Automatic. Standard lets platform teams manage node pools, networking, and more infrastructure options; Automatic provides production defaults and has Azure further manage node provisioning, scaling, security, monitoring, and upgrades.

Key characteristics:

- Integrates with Microsoft Entra ID, Workload Identity, Azure CNI, Load Balancer/Application Gateway, Azure Disk/Files/Blob, ACR, and Azure Monitor;
- AKS Standard supports multiple node pools, Windows nodes, and multiple networking options;
- Node Auto-Provisioning is based on Karpenter, selecting VM SKUs, Spot/on-demand capacity, and managing node lifecycles based on Pod requirements;
- Supports NVIDIA GPU node pools and provides a managed GPU node pool path;
- Combines naturally with Azure Machine Learning, Microsoft Fabric, GitHub/Azure DevOps, and enterprise identity systems;
- Azure Arc-enabled Kubernetes can uniformly connect clusters in other locations, but it is not the AKS public cloud control plane itself.

Best suited for: teams whose enterprise identity and governance center on Entra/Azure Policy, that already have extensive Azure data and application services, that need Windows containers, or that want to integrate with the Microsoft AI/data platform.

Caveats: Automatic and Standard differ in VM SKUs, networking, node access, and customization scope. GPU nodes require verifying target region inventory, driver installation methods, node OS lifecycle, and automatic upgrade policies; high-performance multi-node training also requires separately confirming the VM, topology, and image combinations that support InfiniBand/RDMA.

References: [Azure AKS](https://learn.microsoft.com/azure/aks/what-is-aks), [AKS GPU](https://learn.microsoft.com/azure/aks/use-nvidia-gpu), [AKS Node Auto-Provisioning](https://learn.microsoft.com/azure/aks/use-node-auto-provisioning)

## 4. Quick Comparison of the Six Offerings

| Service | Primary cluster/data plane forms | AI accelerator focus | Elasticity and nodes | Typical strengths |
| --- | --- | --- | --- | --- |
| Alibaba Cloud ACK | Managed Pro, Serverless, Edge, Lingjun | NVIDIA GPU, shared GPU, eRDMA | Node pools, elastic nodes, Serverless | Domestic cloud ecosystem, AI Suite, Lingjun and data acceleration |
| Tencent Cloud TKE | Standard, native nodes, super nodes, registered nodes | NVIDIA GPU, qGPU | Native nodes, super nodes, hybrid nodes | Flexible node forms, online elasticity, GPU sharing |
| Huawei Cloud CCE | Standard, Turbo, Autopilot | NVIDIA GPU, Ascend NPU, CloudMatrix | Node pools, Autopilot | GPU/NPU heterogeneity, Volcano, cloud-native high-performance networking |
| AWS EKS | Standard, MNG, Karpenter, Fargate, Auto Mode, Hybrid | NVIDIA, Trainium, Inferentia, EFA | MNG, Karpenter, Auto Mode | AWS service integration, instance types and Spot, Neuron/EFA |
| Google GKE | Standard, Autopilot, Autopilot ComputeClass | NVIDIA GPU, TPU | NodePool, ComputeClass, Autopilot | Kubernetes maturity, TPU, automated operations |
| Azure AKS | Standard, Automatic, Virtual Nodes | NVIDIA GPU | NodePool, NAP/Karpenter, Automatic | Entra, Microsoft enterprise ecosystem, Azure AI/data platform |

This table cannot be used directly for procurement. Every item must be further expanded to the target region, instance model, delivery lead time, quotas, reservations, Spot behavior, network bandwidth, storage throughput, driver versions, and SLA.

## 5. Cloud Service Mapping

| Capability | ACK | TKE | CCE | EKS | GKE | AKS |
| --- | --- | --- | --- | --- | --- | --- |
| Image Registry | ACR | TCR | SWR | ECR | Artifact Registry | ACR |
| Object Storage | OSS | COS | OBS | S3 | Cloud Storage | Blob Storage |
| Block/File Storage | Cloud Disk, NAS, CPFS | CBS, CFS | EVS, SFS | EBS, EFS, FSx | Persistent Disk/Hyperdisk, Filestore | Azure Disk, Azure Files |
| Cloud Identity | RAM/OIDC system | CAM/OIDC system | IAM | IAM, Pod Identity | Workload Identity Federation | Entra Workload Identity |
| Cloud Load Balancing | SLB/ALB/NLB | CLB | ELB | ALB/NLB | Cloud Load Balancing | Azure Load Balancer/Application Gateway |
| Observability | ARMS/Prometheus/Log Service | TMP/Log Service | AOM/Cloud Monitoring | CloudWatch/Managed Prometheus | Cloud Monitoring/Managed Prometheus | Azure Monitor/Managed Prometheus |

Identical abbreviations can conflict: Alibaba Cloud ACR and Azure ACR are both Registries; Huawei Cloud CCE and Baidu AI Cloud's container product may share the same abbreviation. Architecture documents should write out full product names and cloud vendors, not just abbreviations.

## 6. Key considerations for GPU training

For large-scale training, don't start by comparing console experiences; verify item by item:

1. Which regions and availability zones can deliver the target GPU/NPU/TPU models;
2. Per-node card count, PCIe/NVLink/NVSwitch, and NUMA topology;
3. Whether multi-node networking is regular VPC, RoCE, InfiniBand, EFA, ICI, or vendor supernode networking;
4. Who maintains NCCL/HCCL/XLA, drivers, firmware, OFED, and container images;
5. Whether Gang scheduling, queues, fair sharing, topology-aware scheduling, and whole-group scaling are supported;
6. Spot/preemptible reclaim notifications, Checkpoint, and capacity reservation methods;
7. Object storage, parallel file systems, local NVMe, and data cache throughput;
8. Whether NCCL Tests, storage benchmarks, and long-duration failure drills can be run.

Each cloud's distinctive features can be summarized as: AWS's EFA and Trainium/Inferentia, GKE's TPU Slice, CCE's Ascend and Volcano/CloudMatrix, ACK's Lingjun/eRDMA and AI Suite, TKE's qGPU and multi-node forms, AKS's Azure GPU VMs and Microsoft AI ecosystem. Real performance is still determined by the specific instance, region, network, and software versions.

## 7. Key considerations for LLM inference

Inference platforms also need to compare:

- Whether small GPU specs, sharing, MIG/vGPU, and Serverless GPU are actually available;
- Full cold-start time for node scaling from zero, image pull, and model loading;
- Model distribution pipeline between Registry, object storage, and node cache;
- Whether load balancing supports long connections, streaming responses, Gateway API, and session affinity;
- Whether observability is available by TTFT, TPOT, queue depth, KV Cache, and model dimension;
- Hidden costs of cross-AZ traffic, NAT, public egress, and logs;
- Canary rollout, capacity pre-warming, graceful shutdown, and failure domain failover methods.

Autopilot, Auto Mode, Automatic, or supernodes can reduce node management costs, but large-model weight loading can be far slower than node creation. Without model caching, capacity reservation, and pre-warming processes, "second-level scaling" does not equal "second-level service availability."

## 8. Portability and cloud binding

The Kubernetes API provides basic portability, but the following objects are usually bound to cloud vendors:

- `StorageClass`, snapshots, and file system parameters;
- Load balancer annotations for `Service`/Ingress/Gateway;
- Workload Identity ServiceAccount annotations and cloud IAM;
- CNI, Pod IP, Security Group, and NetworkPolicy implementations;
- Node labels, instance types, availability zones, and capacity types;
- GPU/NPU/TPU resource names, Device Plugin, and scheduling CRDs;
- Auto-provisioned NodePool/NodeClass/ComputeClass APIs;
- Logging, metrics, secrets, certificates, and database integration methods.

It is recommended to split the application and platform into three layers:

```text
可移植应用层
  Deployment / Job / Service / Gateway API / 标准指标

平台契约层
  GPU Capability、Queue、Model Artifact、Workload Identity、Storage Profile

云适配层
  CNI/CSI、LB Annotation、IAM、节点类、云监控和加速器插件
```

Use Kustomize/Helm Overlays or a platform Operator to generate cloud differences; don't let business repositories copy cloud vendor annotations everywhere. The goal of multi-cloud should be rebuildability and migratability, not assuming that training data, models, networks, and GPUs can drift in real time at no cost.

## 9. How to choose

| Existing conditions or core requirements | Prioritize evaluating |
| --- | --- |
| Primary business, data, and procurement are on Alibaba Cloud | ACK Pro; for large-scale AI, further evaluate ACK Lingjun and AI Suite |
| Primary business on Tencent Cloud, values node elasticity or GPU sharing | TKE native nodes/supernodes and qGPU |
| Needs Ascend NPU, or already uses Huawei Cloud and Volcano | CCE Turbo/Standard and CCE AI Suite |
| AWS is the primary cloud, needs rich EC2, Spot, EFA, or Neuron | EKS Standard + Karpenter/MNG; then evaluate Auto Mode |
| Needs TPU/JAX, or wants a highly automated GKE experience | GKE Standard/Autopilot |
| Enterprise identity and data platform centered on Microsoft/Azure | AKS Standard/Automatic |
| Must deploy across domestic and international clouds | First unify OCI, GitOps, model/data interfaces, and observability, then choose each cloud's managed K8s |

If GPU counts are still small and the team lacks Kubernetes SRE capability, the cloud vendor's managed training, Notebook, or inference services may be more appropriate than building a Kubernetes platform directly. Choosing Kubernetes should be driven by clear requirements such as portable controllers, multi-tenant scheduling, unified runtime, or platform APIs.

## 10. POC checklist

- [ ] Actually create a cluster and GPU node pool of the target mode in the target region;
- [ ] Record control plane, node, NAT, public IP, LB, storage, logging, and cross-AZ traffic costs;
- [ ] Verify Kubernetes version support windows, upgrade paths, and node OS lifecycle;
- [ ] Verify OIDC/Workload Identity; don't issue long-term cloud credentials to Pods;
- [ ] Verify Pod IP limits, subnet exhaustion, LB quotas, and DNS behavior;
- [ ] Verify cloud disk, file storage, object storage, and local NVMe throughput;
- [ ] Verify GPU discovery, drivers, topology, DCGM, and fault isolation;
- [ ] Run NCCL/HCCL/XLA, training snippets, and vLLM/SGLang inference benchmarks;
- [ ] Scale from zero and measure segmented time from node, image, model to Ready;
- [ ] Drill node upgrades, Spot reclaim, availability zone failures, and control plane unreachability;
- [ ] Rebuild a second cluster with IaC and GitOps, confirming no hidden console configuration;
- [ ] Define the exit path: how artifacts, data, identity, and network migrate to another cloud or on-premises.

## Further reading

- [Open-source Kubernetes cluster management tools and approaches](open-source-management.md)
- [AI cluster architecture design](architecture.md)
- [Kubernetes cross-cluster and large-scale GPU](multi-cluster-ai.md)
- [GPU node software stack](gpu-node-stack.md)
- [Multi-vendor heterogeneous accelerators](../accelerators/heterogeneous-accelerators.md)
- [Model artifacts, distribution, and caching](../data/model-artifacts.md)
