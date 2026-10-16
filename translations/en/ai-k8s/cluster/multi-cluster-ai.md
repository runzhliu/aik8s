---
title: "Kubernetes Multi-Cluster and Large-Scale GPU"
description: "From Federation evolution to MultiKueue, Karmada, OCM, MCS and Liqo, combined with large-scale GPU training and inference design"
status: evolving
last_reviewed: 2026-08-03
---

# Kubernetes Multi-Cluster and Large-Scale GPU

Kubernetes multi-cluster is not about simply stitching multiple clusters into one larger cluster. It involves at least distinct concerns such as cluster lifecycle, resource inventory, workload placement, service discovery, network connectivity, traffic governance, data replication, and unified policy.

For large-scale GPU platforms, the most important boundary is:

> Selecting "which cluster an entire job runs in" across clusters is already practical; making the same synchronous training run or the same low-latency inference replica span multiple geographically distant clusters remains a highly constrained scenario.

If GPU topology, RDMA, data location, and model warm-up are ignored, and only the idle GPU counts of each cluster are aggregated, cross-cluster scheduling can easily produce a platform where "the capacity numbers are correct, but the jobs cannot run."

## 1. Why AI Platforms Move Toward Multi-Cluster

Common drivers include:

- The API Server, scheduler, network, or operational Blast Radius of a single cluster should not keep growing;
- Training, production inference, and interactive development require different upgrade and security boundaries;
- GPU models, drivers, OS, RDMA fabrics, or cloud vendors differ;
- GPU capacity is distributed across multiple regions, data centers, or cloud accounts;
- Data sovereignty, tenant compliance, and network isolation require workloads to stay in designated regions;
- Online inference needs to be close to users, while training needs to be close to data and large-scale compute;
- When local capacity is insufficient, recoverable batch jobs should be able to burst to public cloud or partner clusters;
- Edge sites need disconnected autonomy and cannot depend on a remote control plane remaining continuously online.

The benefits of multi-cluster are primarily isolation, choice, and independent failure domains—not a free, larger low-latency compute domain. Each additional cluster also adds consistency costs for versions, identity, policy, Secrets, images, models, observability, and disaster recovery.

## 2. From Federation to Composable Multi-Cluster

### 2016–2017: Federation v1

Kubernetes 1.3 introduced Cluster Federation, and 1.5 added `kubefed` and more federated resources. The early idea was to provide a Kubernetes-like API in a Federation Control Plane that replicated or distributed Deployments, Services, ConfigMaps, and other objects to member clusters.

It proved the need for cross-region resource distribution, service discovery, and high availability, but also exposed problems:

- The Kubernetes API itself evolved rapidly, making it difficult for the federation layer to cover all resources in sync;
- The semantics of replicas, overrides, conflicts, and status aggregation for an object across clusters were complex;
- Cluster registration, network, identity, data, and traffic could not be automatically solved by resource replication;
- Users could easily mistake "visible in the federation control plane" for "all clusters are one scheduling domain."

Reference: [Cluster Federation in Kubernetes 1.5](https://kubernetes.io/blog/2016/12/Cluster-Federation-In-Kubernetes-1-5/)

### 2018–2020: Federation v2 / KubeFed

Federation v2 shifted toward extensible type configuration, placement, and override policies, and supported Namespace-level federation. Upstream had already made clear at the time that the multi-cluster problem space was too large for any single model to fit all scenarios.

The key lesson from this history is not "federation failed, so multi-cluster is impossible," but rather: cluster lifecycle, application distribution, network connectivity, and request routing should be decoupled, with each layer composed through clear APIs.

Reference: [Kubernetes Federation Evolution](https://kubernetes.io/blog/2018/12/12/kubernetes-federation-evolution/)

### 2019–2023: Capabilities Differentiate by Responsibility

The ecosystem gradually formed multiple tracks:

- Cluster API manages cluster creation, scaling, upgrades, and destruction with declarative resources;
- Open Cluster Management (OCM) uses Hub-Agent, `ManagedCluster`, `Placement`, and `ManifestWork` to manage member clusters and resource distribution;
- Karmada uses an independent control plane, `PropagationPolicy`, cluster scheduling, and Override to express application placement, distribution, and failover;
- GitOps controllers continuously sync application configuration per cluster or environment;
- Submariner, Cilium ClusterMesh, service meshes, and others address cross-cluster connectivity and service discovery at different scopes;
- Liqo abstracts remote resources as Virtual Nodes and provides Offloading, network, and storage fabrics;
- SIG Multicluster advances common APIs such as Cluster ID, Multicluster Services, Work, and ClusterProfile.

### 2023–2026: From Application Replication to Workload Placement

AI, HPC, and large-scale batch processing do not need simple Deployment replication; they need a single Job to obtain quota and topology as a whole in an appropriate cluster.

MultiKueue adopts a Manager Cluster + Worker Cluster model: the Manager receives Jobs, creates remote Workloads on candidate Workers, and the cluster that first satisfies admission conditions executes the entire job, then syncs status back. It supports Job, JobSet, Kubeflow Trainer, KubeRay, MPIJob, LeaderWorkerSet, and other workload types.

As of this page's review date, MultiKueue is Beta and enabled by default. Its primary semantics are **dispatching one job to one member cluster**, not automatically splitting a distributed Job's Workers across multiple clusters.

Reference: [MultiKueue](https://kueue.sigs.k8s.io/docs/concepts/multikueue/), [MultiKueue TrainJob](https://kueue.sigs.k8s.io/docs/tasks/run/multikueue/trainjob/)

### Status as of 2026

Multi-cluster is still not a single master switch in the Kubernetes core, nor has any single upstream implementation become the sole standard for cluster lifecycle, application distribution, networking, and Job scheduling simultaneously. SIG Multicluster focuses more on interoperability APIs such as Cluster Identity, MCS, Work, and ClusterProfile; specific data planes and advanced policies are implemented by different projects. The mainstream direction for production platforms is to compose a small number of components by responsibility while keeping member clusters autonomous.

## 3. First Split the Seven Planes Apart

| Plane | Question to Answer | Common Capabilities/Projects | What It Does Not Handle |
| --- | --- | --- | --- |
| Cluster Lifecycle | Who creates, upgrades, repairs, and destroys clusters | Cluster API, managed cloud cluster APIs | Job placement and request routing |
| Inventory and Identity | Which clusters exist, who manages them, what are their capabilities and health | ClusterProfile, OCM ManagedCluster, custom Inventory | Guaranteeing real-time schedulable capacity |
| Application and Policy Distribution | Which objects go to which clusters, how differences are overridden | Karmada, OCM ManifestWork, Argo CD/Flux | Cross-cluster data consistency |
| Batch Job Dispatch | Which queue and cluster a Job should enter | MultiKueue, custom Fleet Scheduler | Automatically splitting synchronous Jobs across WAN |
| Service Discovery and Networking | How services are resolved and accessed by other clusters | MCS API, Submariner, Cilium ClusterMesh, Service Mesh, Liqo | Global capacity and model-aware routing |
| Traffic Scheduling | Which region, cluster, and model pool user requests enter | DNS/GSLB, Anycast, Global Gateway, Inference Gateway | Creating GPU capacity |
| Data and Artifacts | Where data, models, and Checkpoints live, and how they are replicated | Object storage, Registry, data catalog, cache systems | Collective communication and Gang Scheduling |

Do not select purely by "multi-cluster product." First determine which planes are needed, then decide the single source of authority and controller ownership for each plane.

## 4. Current Common Architecture Patterns

### Pattern A: Fleet / Hub-Spoke

```text
管理集群 / Hub
  ├── 集群清单、策略、GitOps
  ├── 全局队列或放置控制器
  └── 统一观测入口
        │
        ├── GPU Cluster A
        ├── GPU Cluster B
        └── GPU Cluster C
```

The Hub decides which cluster objects or jobs enter, while member clusters retain their own API Server, scheduler, queues, and failure autonomy. OCM, Karmada, MultiKueue, and many commercial Fleet Managers all follow this line of thinking, but each has different areas of focus.

This is the most common starting point for large-scale GPU platforms. The Hub should not become a synchronous data path for already-running training processes or online inference requests; when the Hub is briefly unavailable, services already running inside member clusters should continue to work.

### Pattern B: GitOps Multi-Target Deployment

Each cluster remains an independent environment, with installation content determined by baselines, Overlays, and cluster labels in Git. It suits versioned platform components, Runtimes, policies, and inference services, but GitOps itself typically does not select training targets based on real-time idle GPU capacity.

### Pattern C: Application-Level Cross-Cluster

Karmada/OCM and others distribute application replicas, policies, and status to multiple clusters, suitable for regional Active-Active, disaster recovery, and unified release. For custom AI CRDs, you must verify whether the controller can understand resource requirements, status, dependencies, and health semantics; merely replicating CRD objects does not mean the upper-layer Operator is working correctly.

### Pattern D: Resource Offloading / Virtual Node

Systems such as Liqo abstract remote cluster resources into the local scheduling view and provide resource reflection and network connectivity. This is attractive for cloud-edge collaboration, temporary resource sharing, and Offloading without modifying applications.

GPU scenarios must additionally verify extended resources, device attributes, Gang, topology, network performance, and failure semantics. A Virtual Node showing `nvidia.com/gpu: 32` cannot automatically express whether those 32 GPUs reside in the same NVLink/RDMA domain.

### Pattern E: Stretched Single Cluster Across Sites

Making one Kubernetes Control Plane or Node set span multiple geographically distant sites looks simplest on the surface, but it exposes the API, etcd, CNI, DNS, Webhooks, and scheduling to WAN latency and partitioning.

Unless the sites have a proven low-latency private network, a clear failure model, and vendor support, it is not recommended to turn cross-region GPU resources into one stretched cluster. Multiple autonomous clusters usually make it easier to define failure boundaries.

## 5. How Mainstream Capabilities Combine

| Capability | Suitable Scenarios | Value for GPU Platforms | Key Limitations |
| --- | --- | --- | --- |
| Cluster API | Multi-cluster creation, scaling, and version lifecycle | Unified GPU cluster templates and upgrade batches | Does not schedule Jobs or replicate models |
| MultiKueue | Batch Job queuing and dispatch across clusters | TrainJob/JobSet/KubeRay selects target cluster as a whole | Not a cross-cluster Worker scheduler by default |
| Karmada | Application propagation, Override, cross-cluster placement and failover | Multi-region inference replicas, cluster-level capacity placement | AI CRDs may require Resource Interpreter |
| OCM | Cluster registration, Placement, ManifestWork, Policy | Fleet inventory, governance, and application distribution | Training queues and GPU topology need other components |
| Liqo | Remote resource Offloading, cross-cluster networking and storage | Cloud-edge or partner cluster resource borrowing | GPU topology and high-performance networking need separate proof |
| MCS API | Standardized ServiceExport/ServiceImport | Cross-cluster control-plane and internal service discovery | SIG does not provide a unified reference implementation, nor is it a global traffic scheduler |
| ClusterMesh/Submariner | Pod/Service connectivity across clusters | Control flow, service discovery, regional access | Not equivalent to an RDMA/NCCL fabric |
| GitOps | Multi-cluster configuration and version convergence | Driver stacks, Operators, Runtimes, and service release | Does not understand real-time GPU queues and request load |

You usually do not need to install the entire table. A practical combination might simply be: GitOps for the platform baseline, MultiKueue for training dispatch, and a Global Gateway for inference scheduling; only introduce MCS/ClusterMesh when a real cross-cluster Service access need arises.

Reference: [Cluster API](https://cluster-api.sigs.k8s.io/), [OCM Architecture](https://open-cluster-management.io/docs/concepts/architecture/), [Karmada Concepts](https://karmada.io/docs/core-concepts/concepts/), [Liqo](https://docs.liqo.io/), [MCS API](https://multicluster.sigs.k8s.io/concepts/multicluster-services-api/)

## 6. How Karmada Combines with AI/GPU

Karmada's core positioning is: using Kubernetes-style APIs, place and propagate resource templates to multiple autonomous clusters according to policies, and aggregate status, handle differences, and perform failover. It is not a cluster creation tool, not a cross-cluster CNI, and not a way to turn all member clusters into a single Node/GPU scheduling domain.

### Control Path

```text
Resource Template
  Deployment / Job / KServe / TrainJob / LWS ...
        +
PropagationPolicy / ClusterPropagationPolicy
        +
OverridePolicy / ClusterOverridePolicy
        ▼
ResourceBinding
        ▼  karmada-scheduler 选择成员集群
每个目标集群一个 Work
        ▼
Push：控制面写成员集群 API
Pull：成员集群 karmada-agent 拉取并执行
        ▼
成员集群本地 Controller / Scheduler / Kueue
        ▼
健康、状态和副本信息聚合回 Karmada 控制面
```

The Karmada Scheduler makes cluster-level decisions; once resources enter a member cluster, Pods are still assigned nodes and GPUs by that cluster's kube-scheduler, Kueue, Volcano, and device plugins.

Reference: [Karmada Architecture](https://karmada.io/docs/core-concepts/architecture/)

### Core Objects and AI Platform Uses

| Object/Capability | Role | AI/GPU Scenario |
| --- | --- | --- |
| `PropagationPolicy` | Selects resources and target clusters, defines replica distribution, Spread, and Failover | Place inference services into designated regions/GPU clusters, or place complete offline jobs into candidate clusters |
| `ClusterPropagationPolicy` | Cluster-scoped propagation policy | Platform administrators distribute common Runtimes, monitoring, and device-related resources |
| `OverridePolicy` | Modifies fields per target cluster | Override image Registry, StorageClass, model URI, ServiceAccount, or GPU Flavor |
| `ResourceBinding` | Stores resource templates and cluster scheduling results | Audit which clusters a given model/job ultimately entered |
| `Work` | Pending Manifests targeting one member cluster | Connects the Karmada control plane to actual objects in member clusters |
| Resource Interpreter | Interprets replicas, components, dependencies, health, and status of custom resources | Enables accurate estimation and aggregation for CRDs such as TrainJob, RayCluster, KServe/LWS |
| Cluster Resource Modeling | Aggregates or models available resources of member clusters | Cluster-level pre-filtering of CPU, memory, Pod, and extended resource capacity |

`OverridePolicy` is well suited to handling "logically the same application, different member cluster details." For example, the same model service uses an internal Registry and local object storage in a private cluster, while in a cloud cluster it uses cloud Workload Identity and a different StorageClass. Differences should be expressed by policies, not by duplicating multiple full YAML files that gradually drift.

Reference: [Propagation Policy](https://karmada.io/docs/userguide/scheduling/propagation-policy/), [Override Policy](https://karmada.io/docs/userguide/scheduling/override-policy/)

### GPU Cluster Placement Still Requires Secondary Admission

Karmada can filter targets based on member cluster labels, Taints, region, and resource models, and can also distribute replicas according to cluster available resources. But the platform must not directly commit to large jobs merely by reading the aggregated `nvidia.com/gpu` headroom.

GPU scenarios also need to handle:

- Whether the 16 idle GPUs are concentrated in the same NVSwitch, Rack, or RDMA Block;
- Whether a higher-priority Workload already exists in the local Kueue queue;
- Whether GPU model, GPU memory, MIG Profile, driver, and CUDA/ROCm match;
- Whether data, model cache, and Checkpoints are reachable from that cluster;
- Whether capacity contention has already arisen while member cluster status is being reported to Karmada.

Therefore, it is recommended to treat Karmada's cluster selection as candidate placement, with final admission performed by the member cluster's queue and scheduler. The default Cluster Resource Summary may also hide node fragmentation; the current Customized Cluster Resource Modeling only supports basic resource grading for CPU, memory, storage, and ephemeral storage, and cannot directly describe GPU/NVLink/RDMA topology. AI capabilities still need to be expressed jointly through stable cluster labels, Resource Interpreter, propagation policies, and local topology scheduling.

Reference: [Karmada Cluster Resource Modeling](https://karmada.io/docs/userguide/scheduling/cluster-resources/)

### Why AI CRDs Need Resource Interpreter

For native objects such as Deployment and Job, Karmada has built-in knowledge of resource structure; for TrainJob, RayCluster, RayJob, KServe, or custom inference CRDs, Karmada by default only sees an ordinary custom object and does not necessarily know how many Workers it contains, how many GPUs each component needs, which Secrets it depends on, or what status represents Healthy.

Resource Interpreter can supplement CRDs with:

- `InterpretReplica`: extract replica and resource requirements from a single Pod Template;
- `InterpretComponent`: separately extract multi-component requirements such as Leader/Worker and Head/Worker;
- `InterpretDependency`: identify dependencies such as ServiceAccount, Secret, ConfigMap, and PVC;
- `InterpretHealth`: define when the resource is healthy, usable for status and Failover;
- `AggregateStatus`: aggregate member cluster status back to the control plane;
- `Retain`: preserve fields managed by member cluster HPA/Controller to avoid repeated overwrites by both sides.

As of this page's review date, `InterpretComponent` and `MultiplePodTemplatesScheduling` in Karmada v1.16+ are still Alpha and disabled by default. Although they target multi-component AI/big-data workloads such as TrainJob and RayCluster, production use requires pinning versions, writing or confirming the Interpreter, validating with `karmadactl interpret`, and testing capacity estimation, dependency propagation, and status aggregation.

Reference: [Karmada Resource Interpreter](https://karmada.io/docs/userguide/globalview/customizing-resource-interpreter/)

### Karmada Suits Inference and Can Also Propagate Training Jobs

**Multi-region inference** is a more natural Karmada scenario:

1. Use PropagationPolicy to select region, cloud provider, and GPU capability;
2. Use Duplicate/Spread to place complete model services into multiple failure domains;
3. Use OverridePolicy to set each cluster's model URI, identity, and storage;
4. Let KServe/LWS/Deployment inside the member cluster create and pre-warm model replicas;
5. The global Gateway only sends traffic to clusters where the model is Ready and has capacity;
6. The in-cluster EPP/Router then completes model-, KV Cache-, and queue-aware routing.

Karmada can also propagate Jobs or TrainJobs, but the semantics must be clarified first:

- If the goal is "the same offline task runs one copy in each of multiple clusters," the application propagation model is appropriate;
- If the goal is "select only one of multiple candidate clusters to run, respecting tenant queues and fair sharing," MultiKueue's Job Dispatch semantics are usually more direct;
- If the goal is "the Ranks of one distributed training job span multiple clusters," Karmada will not automatically provide Gang, Rendezvous, NCCL/RDMA, and unified failure recovery.

### Karmada and MultiKueue Are Not an Either/Or Choice

| Dimension | Karmada | MultiKueue |
| --- | --- | --- |
| Primary objects | General Kubernetes resources and CRDs | Kueue Workload and supported Job types |
| Primary goal | Application propagation, cross-cluster placement, Override, status and Failover | Batch jobs queued across multiple Worker Clusters and dispatched to one |
| Multi-cluster replicas | Can Duplicate, Divide, Spread | Usually one target cluster executes the complete Job |
| Quota and fair sharing | Not its primary queue model | Reuses Kueue ClusterQueue, Flavor, and admission |
| AI CRDs | May require Resource Interpreter | Requires MultiKueue integration for the corresponding Job type |
| Suited for inference | Multi-region publishing and failure-domain placement | Not a request-traffic routing system |
| Suited for training | Replicates/places complete resources, suitable for explicit propagation semantics | Better suited for queue-driven whole-Job dispatch to one cluster |

Both can take on different responsibilities on the same platform—for example, Karmada/GitOps distributes Trainer Runtime, inference services, and policies to member clusters, while MultiKueue alone handles training Job dispatch. However, field ownership must be explicit to avoid two controllers creating or migrating the same Job simultaneously.

### Failover Is Not GPU Process Live Migration

Karmada can trigger migration based on Cluster or Application health, and also provides policies such as Purge and Graceful Eviction. For training and stateful AI workloads, true recoverability still depends on external Checkpoints, model/data reachability, and application recovery entry points.

Karmada's Application State Preservation can extract and re-inject some state fields during failover migration, but the related Stateful Failover Injection is still Alpha. It cannot copy GPU HBM, NCCL Communicators, or in-process training state. Therefore, training disaster recovery should be described as "Karmada triggers re-placement, and the application then recovers from Checkpoint," not as Live Migration.

Reference: [Karmada Application-level Failover](https://karmada.io/docs/userguide/failover/application-failover)

## 7. Cross-Cluster GPU Training: Prioritize Whole-Job Placement

### Recommended Data Flow

```text
用户提交 TrainJob
      ▼
全局队列：租户、优先级、预算、候选集群
      ▼
选择一个满足整组资源的 GPU 集群
      ▼
集群内 Kueue/Volcano：配额、Gang、拓扑
      ▼
JobSet/Trainer/KubeRay：创建所有 Rank
      ▼
NCCL/RDMA Fabric 内训练
      ▼
Checkpoint 写入跨集群可访问的对象存储
```

The global layer is responsible for cluster selection; the local layer is responsible for precise node and device scheduling. The two layers must not modify the placement result of the same Pod simultaneously.

### Cluster Selection Cannot Rely Only on Total Idle GPU Count

A training job's target cluster must at minimum satisfy:

- Accelerator vendor, model, GPU memory, precision, and driver/Runtime version;
- The GPU count for the complete Gang, not an eventually consistent aggregated idle count;
- Whether GPUs are concentrated in an acceptable NVLink, NVSwitch, Rack, or Network Block;
- RDMA, NCCL, MTU, bandwidth, and oversubscription levels;
- Whether the local queue can admit the workload, and whether tenant quota and priority allow it;
- Whether the dataset, base model, and container image are already available nearby;
- Checkpoint location, recovery bandwidth, and object storage egress cost;
- Spot/on-demand type, price, maintenance window, and expected interruption rate;
- Data region, tenant permissions, and compliance constraints.

It is recommended that the cluster Inventory publish stable capability labels and capacity summaries, while the local scheduler still performs final admission based on real-time state. The global layer's cache necessarily has latency, so "nominate candidate clusters first, then confirm with the local queue" is more robust than directly committing to nodes.

### How MultiKueue Applies

The Manager Cluster holds user Jobs and global admission policies; each Worker Cluster runs its own Kueue and training controllers. After the target Worker completes Workload admission, MultiKueue creates the Job mirror in that cluster and synchronizes status.

The platform must also guarantee:

- Namespace, LocalQueue, ResourceFlavor, and Runtime exist in member clusters with consistent semantics;
- Image, Secret, ServiceAccount, data URI, and model URI are valid in the target cluster;
- The Job's final status, logs, metrics, and artifacts can return to a unified portal;
- Manager and Worker quota accounting does not persistently create false available capacity;
- Cancellation, timeout, and retry do not run the same task in two clusters simultaneously.

### Which Training Is Naturally Suited for Cross-Cluster Parallelism

The following work units have loose communication and can each run within one cluster:

- Hyperparameter search and multi-random-seed experiments;
- Data preprocessing, synthetic data, Embedding, and offline evaluation;
- Batch inference over multiple models or multiple data shards;
- Ensembles whose results can be aggregated independently;
- Federated Learning using application-level protocols with asynchronous, low-frequency aggregation;
- Pipeline Stages that exchange artifacts with each other through object storage.

For such tasks, the best cross-cluster granularity is usually a Trial, Shard, or Pipeline Stage, not a single GPU process.

### Why Synchronous Training Usually Does Not Span Regional Clusters

DDP/FSDP, Tensor Parallel, and Expert Parallel frequently perform All-Reduce, All-Gather, or All-to-All. Their Step Time is bounded by the slowest Rank, link latency, and effective bandwidth. WAN latency, jitter, packet loss, and bandwidth cost recur at every training Step.

Only when all of the following conditions hold simultaneously is it worth evaluating a single Job spanning clusters:

- The two clusters are actually in the same campus or on the same low-latency high-speed Fabric;
- The cluster boundary is primarily a management boundary, not a physical network boundary;
- Pods/processes can obtain stable routable addresses, ports, identity, and Rendezvous;
- NCCL/RDMA paths, MTU, QoS, and failure recovery have benchmarks and a support matrix;
- The training framework supports elastic membership changes, or the platform can restart all Ranks as a whole;
- The benefit is verified by end-to-end training throughput, not inferred from the link's nominal bandwidth.

Even so, one should first compare the complexity of "merging into one dedicated training cluster" or "queuing the whole job and waiting."

### Cross-Cluster Migration Is Not Live Migration

Moving a long training run from Cluster A to Cluster B is usually: stop or fail → save/select Checkpoint → re-queue in B → resume. The platform should explicitly define RPO, RTO, Checkpoint compatibility, and data reachability, and should not describe this as lossless Pod migration.

## 8. Cross-Cluster GPU Inference: Replicate Services, Schedule Requests

### Recommended Architecture

```text
Client
  ▼
Global DNS / Anycast / Global Gateway
  ├── Cluster A：Gateway → InferencePool → GPU Pods
  ├── Cluster B：Gateway → InferencePool → GPU Pods
  └── Cluster C：Gateway → InferencePool → GPU Pods
          │
          └── 每个集群内完成模型并行、KV-aware Routing 和 P/D 配对

Model Registry / Object Storage
  └── 向各集群分发权重，并由节点缓存预热
```

Each inference cluster should be a complete, independently serviceable failure domain. The global layer selects region or cluster; the local Gateway/EPP then selects the specific replica based on model, queue, KV Cache, and Endpoint status.

### Layering Global Routing and In-Cluster Routing

The global layer is suitable for:

- User region, network latency, and data sovereignty;
- Whether the model version is deployed and Ready;
- Cluster-level available capacity, error rate, queueing, and circuit-breaker status;
- Tenant, cost, cloud provider, and failure-domain policies;
- Session migratability and disaster-recovery priority.

The in-cluster layer is suitable for:

- Real-time Endpoint queue and Batch;
- Prefix/KV Cache hits;
- Whether LoRA/Adapter is loaded;
- Prefill/Decode pool balancing;
- Per-replica GPU, GPU memory, and health status.

Do not synchronize every request's high-frequency Endpoint status to the global control plane before making decisions. Status latency cancels out the benefit of intelligent routing and puts the WAN on the request critical path.

### Model and Capacity Must Arrive Before Traffic

Regional failover is not just modifying DNS. The target cluster also needs:

- Sufficient baseline GPUs or an acceptable scale-up time;
- Model, Tokenizer, Adapter, and configuration already replicated and validated;
- Node-local model cache or predictable download bandwidth;
- Gateway, Runtime, Engine, and model versions compatible with the source cluster;
- Object storage, KMS, Registry, identity, and dependent services available;
- Long-connection Drain, request retry, and idempotency policies.

A cold cluster can reduce cost, but its model download, node provisioning, and compilation time must enter the RTO. Strict SLOs usually require Warm Standby or Active-Active capacity.

### Do Not Lightly Put TP/PP, P/D, or KV Across the WAN

Tensor/Pipeline/Expert Parallel within a single model replica should stay in the same high-speed network domain as much as possible. Prefill/Decode separation requires transferring large amounts of KV Cache and should also normally be done within the same data center or a validated low-latency network.

The more appropriate boundary across regions is the complete request or asynchronous task, not the internal stages of Token generation. Cross-cluster P/D should only be considered after testing KV size, transfer time, cancellation, version compatibility, and network partitioning; "the network is reachable" is far from sufficient.

### Multi-Cluster Service Discovery Is Not Intelligent Inference Routing

MCS, ClusterMesh, or Service Mesh can make services discoverable and accessible across multiple clusters, but they usually do not understand models, KV Cache, Token queues, or TTFT. A production LLM platform still needs to layer global traffic selection with in-cluster Inference-aware Routing.

## 9. Training and Inference Do Not Reach the Same Conclusions

| Question | Large-Scale Training | Online Inference |
| --- | --- | --- |
| Recommended cross-cluster granularity | Whole Job/Trial/Pipeline Stage | Complete model service replica and individual request |
| Global scheduling goal | Find GPU + Fabric + data that can be admitted as a whole | Region, model Ready, capacity, SLO, and compliance |
| Local scheduling goal | Gang, topology, queue, node, and device | Endpoint, queue, KV, Batch, and Adapter |
| Failure recovery | Restart from Checkpoint in the original/another cluster | Traffic switched away, Warm/Active-Active takeover |
| Cross-cluster data | Dataset, Checkpoint, model artifacts | Model, configuration, Adapter, session state when necessary |
| Least suitable for cross-WAN | Per-Step Collective | TP/PP, KV transfer, P/D internal links |

## 10. A Deployable Layered Reference Architecture

```text
全局管理层（不在同步数据路径）
  Cluster Inventory / GitOps / Policy / Cost / Global Queue
          │
          ├── 训练 Fleet
          │     MultiKueue Manager
          │       ├── Cluster A：Kueue + Trainer + RDMA
          │       └── Cluster B：Kueue + Trainer + RDMA
          │
          └── 推理 Fleet
                Global Gateway / DNS
                  ├── Region A：Gateway + EPP + Model Pool
                  └── Region B：Gateway + EPP + Model Pool

共享但不强耦合的基础设施
  Identity / Registry / Model Registry / Object Storage / Telemetry Backend
```

Key design principles:

1. **Global coarse-grained, local fine-grained.** The global layer selects clusters; the local layer selects nodes, GPUs, or Endpoints.
2. **Member clusters can operate autonomously.** WAN or Hub failure should not immediately interrupt running training and online inference.
3. **Status is layered by purpose.** Inventory stores relatively stable capabilities; the local scheduler holds real-time capacity.
4. **Data first.** Validate data, model, identity, and dependency reachability before migrating Jobs or traffic.
5. **Failure domains are explicit.** Cluster, region, network Block, and storage failures should have different recovery strategies.
6. **Version is a set of artifacts.** Kubernetes, drivers, Runtime, Operators, CRDs, models, and Connectors are released together.

## 11. Cross-Cluster Failure Semantics

| Failure | How the training platform should handle it | How the inference platform should handle it |
| --- | --- | --- |
| Management Hub unavailable | Running Jobs continue; pause new dispatching; reconcile after recovery | Member clusters continue serving; global configuration freezes or degrades |
| Worker Cluster API unreachable | Do not re-dispatch the same Job; confirm lease/state before resuming | Remove from the global health pool, but distinguish control-plane state from data-plane state |
| Entire cluster fails | Restart from external Checkpoint on another cluster | Shift requests to clusters that have the model and capacity |
| Cross-cluster network partition | Do not let both sides believe they own the task simultaneously | Keep serving locally; stop routing that depends on remote synchronized state |
| Object storage/Registry unavailable | Cached tasks may continue; otherwise stop admission | Already-loaded models continue; block new versions that require cold loading |
| Global state stale | Local queue ultimately rejects/admits | Local circuit breaking and Endpoint health override global recommendations |
| Credentials or policy out of sync | Fail fast and report the target cluster differences | Do not send traffic to versions whose identity/policy is not ready |

Cross-cluster controllers must have unique task identity, idempotent creation, Lease/Ownership, and eventual reconciliation mechanisms. After a network partition, the most dangerous situation is not "temporarily unable to see," but the same training run or release being executed twice in two clusters.

## 12. Common Anti-Patterns

- Treating 8 idle GPUs in each of 4 clusters as a resource pool capable of running a 32-GPU synchronous training job;
- A global scheduler promising capacity based directly on GPU idle counts that are seconds or even minutes old;
- Karmada/OCM/MultiKueue/GitOps managing the same object fields simultaneously, causing controllers to overwrite one another;
- Opening up Pod CIDR first, then assuming NCCL, GPUDirect RDMA, or KV transport is already available;
- Stretching etcd, the API Server, or a single inference replica across long-distance sites;
- Replicating Deployments without replicating models, Secrets, identity, Runtime, queues, and NetworkPolicies;
- Disaster-recovery clusters having no GPU baseline or model pre-warming, only starting to pull weights when an incident occurs;
- Training failover without an external Checkpoint, yet still promising cluster-level automatic disaster recovery;
- Treating MCS/Service Mesh as global GPU scheduling or LLM intelligent routing;
- Only demoing the happy path, without rehearsing Hub disconnection, dual-write, cancellation, and state reconciliation.

## 13. How to Choose a Starting Point

| Requirement | Suggested starting point |
| --- | --- |
| Unified creation and upgrade of multiple GPU clusters | Cluster API or cloud vendor Fleet/Lifecycle API + GitOps |
| Training Jobs placed in one of several clusters | MultiKueue + local Kueue/Trainer per cluster |
| Unified release of multi-region inference replicas | GitOps; evaluate Karmada/OCM when complex placement/Override is needed |
| Multi-cluster application governance and policy | OCM/Karmada, with clear field ownership relative to GitOps |
| Cross-cluster Service access | MCS implementations, Submariner, ClusterMesh, or Service Mesh, chosen by network boundary |
| Borrowing remote clusters while keeping the Kubernetes scheduling experience | Evaluate Liqo, and separately validate GPU/topology/RDMA |
| Large-scale synchronous training | First build single-cluster/single-Fabric topology and queues; cross-cluster only does whole-Job placement |
| Global LLM inference | Complete Serving Stack per region + Global Gateway/GSLB + model pre-warming |

### Suggested Evolution Order

1. Unify Cluster ID, labels, identity, version, and observability dimensions across all clusters.
2. Use GitOps or a Fleet Manager to unify the platform baseline; do not first connect cross-cluster Pod networking.
3. Establish replicable and verifiable mechanisms for models, data, and Checkpoints.
4. Introduce whole-Job cross-cluster dispatch for training, while the local side continues to handle Gang and topology.
5. For inference, establish region-level full replicas, model pre-warming, and global traffic failover.
6. Only add MCS, ClusterMesh, or Offloading when a clear application dependency emerges.
7. Only last, evaluate highly coupled solutions such as cross-cluster synchronous training, P/D, or KV transport.

## 14. Go-Live Checklist

- [ ] Every cluster has a stable unique ID, owner, region, failure domain, and version information.
- [ ] Inventory can express GPU model, GPU memory, interconnect, RDMA, data, and price, not just card count.
- [ ] Responsibilities, field ownership, and the final admission authority for global placement and local scheduling are explicit.
- [ ] During Hub/WAN outages, running training and online inference can operate autonomously by design.
- [ ] The same Job will not be executed twice by two clusters during a network partition or retry.
- [ ] Training enters a single topology-satisfying cluster as a whole Job, or cross-cluster communication has measured evidence.
- [ ] Checkpoints, data, and models use immutable versions and can be verified in the target cluster.
- [ ] Inference failover covers GPU capacity, model pre-warming, dependencies, and long-lived connection handling.
- [ ] Global routing and in-cluster model/KV-aware routing are layered.
- [ ] Cross-cluster networking has separately validated the paths required for ordinary Services, storage, RDMA/NCCL, or KV.
- [ ] Secrets and identity do not rely on unbounded replication; permissions are auditable in each member cluster.
- [ ] Observability data includes `cluster_id`, Job UID, model version, request ID, and failure domain.
- [ ] All CRDs, Controllers, and Runtimes have a compatibility matrix, Canary, and rollback methods.
- [ ] Rehearsed Hub disconnection, member cluster disconnection, object storage failure, and stale global state.

## Further Reading

- [SIG Multicluster](https://multicluster.sigs.k8s.io/)
- [ClusterProfile API](https://multicluster.sigs.k8s.io/concepts/cluster-profile-api/)
- [Work API](https://multicluster.sigs.k8s.io/concepts/work-api/)
- [Multicluster Services API](https://multicluster.sigs.k8s.io/concepts/multicluster-services-api/)
- [Cluster API](https://cluster-api.sigs.k8s.io/)
- [MultiKueue](https://kueue.sigs.k8s.io/docs/concepts/multikueue/)
- [Karmada Propagation Policy](https://karmada.io/docs/userguide/scheduling/propagation-policy/)
- [Open Cluster Management Architecture](https://open-cluster-management.io/docs/concepts/architecture/)
- [Liqo Architecture and Offloading](https://docs.liqo.io/)

For in-cluster details accompanying this page, see: [AI Cluster Architecture Design](architecture.md), [Distributed Training Platform](../distributed-training.md), [Multi-Machine and Disaggregated LLM Inference](../inference/distributed-serving.md), and [Edge AI and Cloud-Edge Collaboration](../edge-ai.md).

Cross-region model weights should not be fetched directly by each Pod over the WAN from the source; see [Model Format, Artifact Supply Chain, and Distribution](../data/model-artifacts.md) for regional replicas, P2P, node NVMe pre-warming, and release gates.
