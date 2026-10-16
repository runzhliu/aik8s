---
title: "AI/LLM Cluster Component Inventory"
description: "Lists the Kubernetes cluster components needed for minimal closed-loop, training, big data, Ray, online inference, and advanced inference scenarios, along with the rationale for introducing them and acceptance criteria"
status: evolving
last_reviewed: 2026-08-04
---

# AI/LLM Cluster Component Inventory

This inventory is used to translate a reference architecture into the actual scope of cluster construction. It does not require installing all projects at once. Instead, first select the target scenario, then install only the components that solve a clearly identified problem.

Components are classified into three levels:

- **Required**: Without it, the scenario cannot form an operable closed loop;
- **Conditionally required**: Needed only after reaching multi-tenancy, multi-node, high availability, or a specific data scale;
- **Optional**: Can be skipped when an equivalent capability already exists or the current scale does not require it.

## 1. First Select the Target Scenario

| Scenario | Typical Scale | Primary Goal | Recommended Starting Point |
| --- | --- | --- | --- |
| A. Minimal GPU closed loop | 1–8 GPUs, single team | Run training/inference and observability | Kubernetes + GPU access + Job/Deployment + object storage |
| B. Multi-tenant training | 8–hundreds of GPUs | Queuing, fairness, gang scheduling, Checkpoint | Kueue + Trainer/JobSet or KubeRay |
| C. Ray data/training/inference | Many Python tasks, dynamic roles | Unified Data/Train/Tune/Serve | KubeRay + RayJob/RayService |
| D. Big data and AI | Batch/streaming, Lakehouse, training data | Data processing, versioning, and real-time pipelines | Spark/Flink/Kafka/Trino + object storage |
| E. High-availability LLM inference | Multiple models, multiple replicas | TTFT/TPOT, elasticity, Canary | Gateway + KServe/AIBrix/RayService + vLLM |
| F. Large-scale disaggregated inference | Multi-node models, high traffic | Goodput, P/D separation, KV transfer | LWS/Kueue + llm-d/AIBrix/Dynamo/Ray Serve LLM |

If you currently have only one model, a small number of GPUs, and one team, prioritize completing Scenario A. Do not install all components of Scenario F directly.

## 2. Base Components for All Scenarios

| Capability | Recommended Component/Implementation | Level | Why It Is Needed | Acceptance Evidence |
| --- | --- | --- | --- | --- |
| Kubernetes control plane | Managed K8s, RKE2, K3s, or a standard distribution | Required | Provides resources, lifecycle, networking, and declarative APIs | Control plane backup/upgrade drill; nodes can safely join and drain |
| Container runtime | containerd/CRI-O | Required | Starts containers and connects images, devices, and RuntimeClass | Pinned version; GPU container smoke test passes |
| CoreDNS | Kubernetes DNS | Required | Worker, Head, Service, and controllers depend on service discovery | DNS latency, errors, and capacity are observable |
| CNI | Cilium, Calico, cloud CNI, etc. | Required | Pod networking, NetworkPolicy, and service communication | Cross-node throughput, MTU, and Policy tests pass |
| CSI | Cloud disk, Ceph, NFS, vendor CSI, etc. | Conditionally required | Notebook Home, Checkpoint, Kafka/Flink state, etc. need persistent volumes | Create, mount, resize, snapshot, and failure recovery pass |
| Ingress/Gateway | Gateway API Controller, Envoy Gateway, NGINX, etc. | Conditionally required | Expose APIs externally, TLS, routing, and unified entry point | TLS, streaming responses, timeouts, and large request tests pass |
| Certificate | cert-manager or enterprise PKI | Conditionally required | Automatically issue and rotate TLS certificates | Rotation does not cause service interruption |
| GitOps | Argo CD, Flux, or controlled CI/CD | Required | Versioned installation, rollback, and audit of cluster components | Configuration can be rebuilt from Git and rolled back to the previous version |
| Registry | OCI Registry | Required | Store immutable images and optional model artifacts | Digest pull, signing, and permission verification pass |
| Secret/Identity | External Secrets, Vault, cloud Workload Identity | Required | Avoid long-lived keys scattered in YAML and images | Credential rotation, least privilege, and audit pass |

## 3. GPU and Node Software Stack

| Capability | Recommended Component/Implementation | Level | Why It Is Needed | When It Can Be Skipped |
| --- | --- | --- | --- | --- |
| GPU Driver | Node image, Driver Container, or GPU Operator | Required | User-space CUDA needs to communicate with the kernel driver | CPU-only cluster |
| GPU Device Plugin | NVIDIA/AMD/Intel Device Plugin | Required | Expose GPU as a Kubernetes Resource allocated to Pods | CPU-only cluster |
| GPU Operator | NVIDIA GPU Operator, etc. | Conditionally required | Unify driver, Toolkit, Plugin, DCGM, and node state | All components are already stably managed by node image/cloud service |
| Container Toolkit | NVIDIA Container Toolkit/vendor Runtime | Required | Inject devices and driver libraries into containers | CPU-only cluster |
| GPU metrics | DCGM Exporter/vendor Exporter | Required | Locate GPU memory, utilization, XID, temperature, and power | Cannot rely only on Pod Running |
| GPU health | Node Problem Detector, GPU health agent, custom isolation | Conditionally required | Faulty GPUs need automatic Cordon/isolation and retesting | Small manual clusters can temporarily handle manually, but alerts are needed |
| GPU sharing | MIG, Time-slicing, HAMi, etc. | Optional | Improve development and small-model density | Formal training/inference defaults to whole GPU, or business does not need sharing |
| DRA/CDI | Kubernetes DRA, CDI, and vendor Driver | Optional/evolving | Express dynamic device declarations, partitioning, and richer topology | Device Plugin already satisfies the target version and scenario |

Minimum acceptance:

```text
Node Ready
  → GPU Resource 可分配
  → Pod 内 nvidia-smi/厂商工具正常
  → 单卡矩阵计算
  → 多卡 Collective
  → 指标能关联 Pod、Node 和 GPU UUID
```

## 4. Scheduling, Queues, and Multi-tenancy

| Capability | Recommended Component | Level | Why It Is Needed | Conditions for Skipping |
| --- | --- | --- | --- | --- |
| Default Pod scheduling | kube-scheduler | Required | Handles resources, Affinity, Taint, and topology constraints | Irreplaceable base component |
| Batch job admission | Kueue | Conditionally required | Check quota, priority, and Flavor before creating large numbers of Pods | Single team, few jobs, and no queuing requirement |
| Gang scheduling | Kueue, Volcano, YuniKorn | Required for multi-node | Avoid partial Worker GPU allocation while jobs cannot start | Only single-Pod/single-node jobs |
| Topology awareness | Kueue TAS, Scheduler Plugin/vendor solution | Conditionally required for multi-node | TP/training needs concentration on high-speed networks and appropriate failure domains | Single-node jobs |
| Priority and preemption | PriorityClass + Kueue/scheduler | Required for multi-tenant | Protect online services and allow batch jobs to yield in an orderly manner | Single team without sharing |
| Node scaling | Cluster Autoscaler, Karpenter, cloud Autoscaler | Optional/conditionally required | Pending workloads drive node provisioning | Fixed physical cluster without automatic provisioning capability |
| Policy | Kyverno, Gatekeeper, ValidatingAdmissionPolicy | Conditionally required | Restrict privileges, Tags, HostPath, and missing resource requests | Very small trusted experimental clusters can use a review process first |

Kueue, Volcano, and YuniKorn do not all need to be installed. Choose the primary path based on whether you need "admission queue" or "Gang/queue capability replacing the Scheduler," and avoid having the same workload managed by multiple scheduling control planes.

## 5. Data, Storage, and Model Artifacts

| Capability | Recommended Component/Implementation | Level | Why It Is Needed |
| --- | --- | --- | --- |
| Authoritative object storage | S3/GCS/OSS/COS, MinIO/Ceph RGW, etc. | Required | Store datasets, Checkpoints, models, and logs, independent of Pod lifecycle |
| Shared files | Cloud file, CephFS, NFS, parallel file systems | Conditionally required | POSIX compatibility, Notebook Home, multi-Rank Checkpoint |
| Local high-speed disk | NVMe, Local PV, `emptyDir` with size limit | Conditionally required | Shuffle, Spill, model cache, and data hot tier |
| Model Registry | MLflow, Kubeflow Model Registry/Hub, custom Catalog | Conditionally required | Manage model metadata, stages, evaluation, and lineage |
| OCI Registry | Harbor, Zot, Quay, GitLab Registry, Artifactory, or cloud vendor Registry | Required | Store immutable images, OCI model artifacts, signatures, and SBOM; see [Model Artifacts and Distribution](../ai-k8s/data/model-artifacts.md#7-oci-registry-harbor) for selection |
| Model distribution | OCI Modelcar, KServe LocalModel, P2P/node cache, custom DaemonSet | Conditionally required for large models | Reduce cold start and object storage hotspots when weights are very large |
| Dataset Catalog | Iceberg/Delta/Hudi Catalog, data Catalog | Conditionally required for data platform | Bind training to Snapshot, Schema, and permissions |
| Data/model signing | Digest, Cosign, SBOM/Model BOM | Required for production | Confirm artifacts entering training and inference are immutable and auditable |

It is not recommended to put all data, models, and Checkpoints in one huge RWX PVC, nor to distribute frequently changing hundreds-of-GB weights via container images.

## 6. Distributed Training Components

| Capability | Recommended Component | Level | Why It Is Needed | Selection Notes |
| --- | --- | --- | --- | --- |
| Training controller | Kubeflow Trainer | Conditionally required | Standardize framework startup and lifecycle with TrainJob/Runtime | Multi-framework, platform templates preferred |
| Generic multi-Job orchestration | JobSet | Conditionally required | Express multiple ReplicatedJobs such as Leader/Worker | Custom training API or framework-agnostic scenarios |
| Ray training | KubeRay + RayJob/Ray Train | Conditionally required | Unify Python data, training, Tune, and post-training roles | Use when the Ray ecosystem is already chosen |
| Collective communication | NCCL/RCCL, Gloo, MPI | Required for multi-GPU | Gradient, parameter, and state synchronization | Install with framework image and run benchmarks |
| RDMA | Network Operator, Multus, SR-IOV/RDMA Device Plugin | Conditionally required for multi-node | Reduce Collective latency and increase bandwidth | Can be deferred when regular Ethernet meets small-scale baseline |
| Experiment tracking | MLflow, Weights & Biases, custom | Required for production | Correlate code, data, parameters, metrics, and Artifacts | Choose one authoritative system |
| Workflow | Argo Workflows, Kubeflow Pipelines, Flyte | Conditionally required | Orchestrate data, training, evaluation, and release dependencies | Can be skipped for single Jobs |

Trainer, JobSet, and KubeRay are different execution paths and should not all become mandatory user options just for "component completeness." Platforms typically provide one golden path and reserve another for special workloads.

## 7. Ray Scenario Components

| Component | Level | Why It Is Needed | Key Configuration |
| --- | --- | --- | --- |
| KubeRay Operator | Required | Manage RayCluster, RayJob, RayService lifecycle | Locked with Ray version, Webhook/CRD upgrades |
| RayJob | Required for batch jobs | Create ephemeral RayClusters for data, training, Tune, and batch inference | `shutdownAfterJobFinishes`, Checkpoint, Kueue |
| RayService | Required for online services | Manage RayCluster + Serve Application, high availability, and upgrades | Serve Config, minimum replicas, GCS failure policy |
| Kueue Ray integration | Conditionally required for multi-tenant | Complete quota admission before creating Head/Worker | Fixed/elastic Worker Group and Feature Gate |
| Object storage | Required | Store Checkpoint, results, and Dataset | Workload Identity, immutable paths |
| Object Store Spill | Conditionally required | Protect large object processing when memory is insufficient | NVMe/PVC, disk watermark and cleanup |
| Prometheus/Grafana | Required | Observe Task/Actor, Object Store, Data, Train, Serve | Correlate Ray CR, Pod, GPU, and model |
| HA Redis/GCS FT | Optional for online high availability | RayService Head/GCS recovery | Enable only per official support matrix and drill |

See [Ray's Role in Large Model Training and Inference](../ai-k8s/ray-llm-platform.md) for the Ray topic.

## 8. Big Data on Kubernetes Components

| Capability | Recommended Component | Level | Why It Is Needed |
| --- | --- | --- | --- |
| Batch processing | Spark native/Kubeflow Spark Operator/Apache Spark Operator | Conditionally required | ETL, corpus processing, table maintenance, and large-scale Join |
| Stream processing | Flink Kubernetes Operator | Required for real-time scenarios | CDC, event time, stateful computation, and Checkpoint |
| Event logging | Kafka + Strimzi | Required for real-time scenarios | CDC, feedback, logs, and traffic buffering |
| Interactive SQL | Trino | Optional/required for analytics scenarios | Lakehouse queries, federated data exploration |
| Open table formats | Iceberg/Delta/Hudi | Required for Lakehouse | Snapshot, transactions, Schema/Partition evolution |
| Catalog | REST/Hive/Glue/Nessie or other target Catalog | Required for Lakehouse | Table names, metadata pointers, access, and concurrent commits |
| Workflow | Airflow/Argo/Flyte | Conditionally required | Dependencies across Spark/Flink/quality/training |
| Queues | Kueue/Volcano/YuniKorn | Conditionally required for shared clusters | Prevent ETL from contending with training/inference for resources without order |

Do not put all state and compute into the same node pool just because Spark, Flink, and Kafka can all run on Kubernetes. Kafka/Flink persistent stateful services, Spark elastic batch jobs, and GPU training require different availability and scaling strategies.

## 9. LLM Inference and Microservice Components

| Layer | Recommended Component | Level | Why Needed | When Not Needed |
| --- | --- | --- | --- | --- |
| Inference Engine | vLLM, SGLang, TensorRT-LLM, Triton | Required | Loads models, batching, KV Cache, and token computation | When using an externally hosted managed API |
| Base Deployment | Deployment/StatefulSet + Service | Required | Minimal model service lifecycle | Not written by hand when generated by KServe/AIBrix/RayService |
| Serving Control Plane | KServe | Conditionally Required | Standard model API, Runtime, Canary, and model loading | Single model and Helm/Deployment already suffice |
| LLM Control Plane | AIBrix | Optional / Conditionally Required at Scale | LLM Gateway, routing, autoscaling, LoRA, and KV | Few replicas, no dedicated caching/routing requirements |
| Composable Services | Ray Serve/BentoML | Optional | Multi-step Python AI microservices and independent scaling | Single model endpoint |
| Enterprise Runtime | NVIDIA NIM/NIM Operator | Optional | Vendor-verified, model profiles, caching, and support lifecycle | Self-managed open-source runtime already suffices |
| Intelligent Gateway | Gateway API Inference Extension, AIBrix/Envoy AI Gateway | Conditionally Required for Multi-Model | Model-, queue-, prefix/KV-, and priority-aware routing | Single model, single replica |
| Multi-Node Replicas | LeaderWorkerSet | Conditionally Required for Multi-Node | One model replica consists of Leader + multiple Workers | Model fits in a single Pod |
| P/D/KV Platform | llm-d, AIBrix, Dynamo, Ray Serve LLM | Advanced Optional | Independent scaling of Prefill/Decode and KV transfer | Colocated inference already meets SLO |
| Inference Elasticity | KEDA/HPA, built-in control plane autoscaler | Conditionally Required | Scale replicas based on Queue/Token/Latency | Fixed small scale and manual capacity is sufficient |

See [LLM Serving and AI Microservice Frameworks](../ai-k8s/inference/serving-frameworks.md) for selection principles. A single service can have only one replica-count owner, one primary routing owner, and one model lifecycle owner.

## 10. RAG, Agent, and Application Layer

| Capability | Recommended Component/Implementation | Level | Why Needed |
| --- | --- | --- | --- |
| Vector Retrieval | Milvus, Qdrant, Weaviate, pgvector, managed services | Required for RAG | Stores embeddings and performs ANN + Metadata Filter |
| Embedding/Reranker | Standalone model service, NIM, vLLM/TEI, etc. | Required for RAG | Scales and releases generation models independently from retrieval models |
| Document Pipeline | Kafka/Flink, Job, Ray/Spark, in-house | Conditionally Required | Parsing, chunking, permissions, and incremental indexing |
| Agent/Workflow | Dify, LangGraph, LlamaIndex, Haystack, in-house | Optional | Orchestrates prompts, tools, state, and business processes |
| Tool Gateway | In-house/platform gateway | Required for Agent Production | Unified authentication, approval, rate limiting, auditing, and credential proxying |
| Sandbox | Kubernetes Agent Sandbox, gVisor, Kata, MicroVM | Required when executing untrusted code | Limits the impact of Agent code/browser/Shell on the host and network |

Application frameworks do not replace GPU serving. It is recommended that Dify/LangGraph and similar tools call stable model APIs through an internal AI Gateway.

## 11. Observability and Operations

| Capability | Recommended Component | Level | Why Needed |
| --- | --- | --- | --- |
| Metrics | Prometheus + long-term storage | Required | Unified cluster, GPU, training, data, and inference metrics |
| Dashboards | Grafana | Required | Capacity, SLO, failure, and cost views |
| Logs | Loki/ELK/OpenSearch/cloud logs | Required | Aggregates multi-Pod, multi-Rank, and controller logs |
| Tracing | OpenTelemetry + Tempo/Jaeger | Conditionally Required for Online Paths | Breaks down Gateway, retrieval, Prefill, KV, and Decode |
| GPU Metrics | DCGM/vendor Exporter | Required | Device-level utilization, GPU memory, health, and power |
| Cost | OpenCost/Kubecost/cloud billing + GPU attribution | Conditionally Required for Multi-Tenancy | Chargeback, idle capacity, and per-token/training cost |
| Alerting | Alertmanager/On-call platform | Required | Converts SLO and capacity risks into actionable events |

Retain at minimum the following correlation keys: Namespace, Tenant, Queue, Job/Service, Pod, Node, GPU UUID, model version, data Snapshot, image Digest.

## 12. Security and Governance

| Capability | Recommended Component/Mechanism | Level | Why Needed |
| --- | --- | --- | --- |
| Identity | OIDC, Workload Identity, SPIFFE/SPIRE (optional) | Required | Both users and workloads need stable identities |
| RBAC | Kubernetes RBAC + platform authorization | Required | Restricts CRD, Secret, Pod, and model operations |
| Network | NetworkPolicy, Egress Proxy, WAF | Required | Prevents lateral movement and unaudited outbound connections |
| Pod Security | Pod Security, Kyverno/Gatekeeper | Required | Restricts privileges, HostPath, Root, and dangerous Capabilities |
| Supply Chain | Signing, SBOM, scanning, Admission Policy | Required for Production | Prevents unverified images, models, and dependencies from entering the cluster |
| Secrets | Vault/External Secrets/KMS | Required | Credentials do not enter Git, images, or user Notebooks |
| Audit | Kubernetes Audit, Gateway/model/tool call auditing | Required for Production | Tracks who deployed, accessed, and modified what |

## 13. Five Executable Component Packages

### Package A: Minimal GPU Inference/Fine-Tuning

```text
Kubernetes + CNI/CSI
GPU Driver/Device Plugin + DCGM
Registry + Object Storage
Job + Deployment + vLLM
Gateway/Ingress + TLS
Prometheus/Grafana + Logs
GitOps + Secret/Identity
```

Do not install yet: Kueue, KServe, AIBrix, Ray, LWS, P/D platforms. First prove single-model performance, cold start, release, and failure recovery.

### Package B: Multi-Tenant Training

Add to Package A:

```text
Kueue（或 Volcano/YuniKorn 主路径）
Kubeflow Trainer/JobSet（或 KubeRay 主路径）
RDMA/Network Operator（多机需要）
MLflow/Model Registry
Workflow
共享/并行存储 + Checkpoint
成本与队列看板
```

### Package C: Ray Large Model Platform

Add to the base layer:

```text
KubeRay Operator
RayJob + Kueue
Ray Data / Train / Tune
RayService / Ray Serve LLM
对象存储 + Object Store Spill
Ray/Serve 指标、日志和 Dashboard 受控访问
```

Training and online serving use RayJob and RayService respectively, and do not share the same failure domain.

### Package D: Big Data and AI

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

### Package E: Online Inference at Scale

Select one control plane on top of Package A based on the target:

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

Do not stack KServe, AIBrix, RayService, and NIM Operator all on the same model service.

## 14. Recommended Installation Order

1. Kubernetes, CNI, CSI, DNS, and node baseline;
2. GPU driver, Device Plugin, Runtime, and DCGM;
3. Registry, object storage, Secret/Identity, and GitOps;
4. Prometheus, logging, alerting, and auditing;
5. Native Job and `Deployment + vLLM` minimal closed loop;
6. Choose Kueue + training controller, or KubeRay, based on the scenario;
7. Add Spark/Flink/Kafka/Lakehouse based on the data scenario;
8. Choose KServe, AIBrix, Ray Serve, or NIM based on service scale;
9. Add multi-node, P/D, KV Offload, and multi-cluster only when benchmarks prove the need;
10. Add upgrade, backup, failure, and rollback drills with every additional layer.

## 15. Cluster-Level Acceptance Checklist

- [ ] Every component corresponds to a clear requirement and Owner;
- [ ] No multiple controllers writing to the same resource for the same capability;
- [ ] All versions are entered into the Kubernetes, Driver, CUDA, framework, and CRD compatibility matrix;
- [ ] GPU baseline for single card, multi-card, cross-node, and faulty-card isolation is complete;
- [ ] Jobs can queue, admit, run, save Checkpoints, and be reclaimed;
- [ ] Models can cold start, warm up, receive traffic, drain, and roll back;
- [ ] Data, models, images, and configuration all use immutable versions;
- [ ] Object storage, shared disks, NVMe, and network have completed capacity testing;
- [ ] Metrics and logs can be traced from business requests/training runs down to Pod, Node, and GPU;
- [ ] Failure drills are complete for the control plane, Operators, Gateway, Head, and state stores;
- [ ] Namespace, RBAC, Queue, NetworkPolicy, and credential isolation have passed testing;
- [ ] The cluster can be rebuilt from Git, backups, and external artifacts;
- [ ] Component upgrades have Canary, rollback, and CRD compatibility plans;
- [ ] Can answer "what capability would be lost if this component were removed."

## Further Reading

- [AI/LLM on Kubernetes Reference Architecture](../ai-k8s/guides/reference-architectures.md)
- [AI on Kubernetes Implementation Roadmap](../ai-k8s/adoption-roadmap.md)
- [Big Data on Kubernetes](../ai-k8s/data/big-data-on-kubernetes.md)
- [Ray's Role in Large Model Training and Inference](../ai-k8s/ray-llm-platform.md)
- [LLM Serving and AI Microservice Frameworks](../ai-k8s/inference/serving-frameworks.md)
- [GPU Platform Minimal Closed-Loop Experiment](../ai-k8s/guides/gpu-platform-lab.md)
