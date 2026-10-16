---
title: "AI/LLM Kubernetes Glossary"
description: "Quick reference for common terms in GPU, big data, scheduling, training, inference, networking, Agent sandboxes, model artifacts, and reliability"
status: stable
last_reviewed: 2026-08-04
---

# AI/LLM Kubernetes Glossary

This page standardizes terminology used across the site. English abbreviations retain their common industry usage, while the Chinese explanations emphasize the engineering meaning in Kubernetes AI infrastructure.

## Kubernetes and Devices

| Term | Explanation |
| --- | --- |
| CRI | Container Runtime Interface, the interface between kubelet and container runtimes such as containerd/CRI-O. |
| CNI | Container Network Interface, the plugin interface that configures network interfaces, addresses, and routes for Pods. |
| CSI | Container Storage Interface, the plugin interface for volume creation, mounting, expansion, and snapshots. |
| CRD | CustomResourceDefinition, adds custom resource types to the Kubernetes API. |
| Operator | A pattern that uses controllers to continuously reconcile the lifecycle of a software stack or domain object. |
| Reconcile | The loop in which a controller compares desired state with actual state and drives them to convergence. |
| Extended Resource | An integer resource published by device plugins and similar components, such as `nvidia.com/gpu`. |
| Device Plugin | A vendor plugin that discovers, registers, and allocates special devices to kubelet. |
| CDI | Container Device Interface, uses a standard Spec to describe the device nodes, mounts, and environment a container needs injected. |
| DRA | Dynamic Resource Allocation, expresses dynamic device allocation using DeviceClass, ResourceSlice, and ResourceClaim. |
| DeviceClass | Device categories and selection rules defined by administrators in DRA. |
| ResourceSlice | Device inventory, attributes, and capacity published by DRA Drivers. |
| ResourceClaim | A workload's declaration of a specific device capability. |
| NFD | Node Feature Discovery, discovers node features such as CPU, PCI, and kernel, and generates labels. |
| RuntimeClass | A Kubernetes object that lets Pods select container runtime implementations such as runc, gVisor, or Kata. |
| Cluster API | An upstream project that manages cluster and Machine lifecycles using Kubernetes-style declarative APIs. |
| ClusterSet | A group of Kubernetes clusters with explicit membership; a logical boundary used by multi-cluster APIs such as MCS. |
| MCS API | Multicluster Services API, expresses cross-cluster service discovery using ServiceExport/ServiceImport. |
| Karmada | A Kubernetes multi-cluster orchestration system that manages resources in member clusters using propagation, Override, cluster placement, and Failover policies. |
| Taint/Toleration | A scheduling mechanism that restricts whether Pods can enter a given class of nodes. |
| Node Affinity | Expresses where a Pod must or prefers to run based on node labels. |
| Topology Spread | Distributes replicas across topology domains such as nodes and availability zones. |
| Topology Manager | The kubelet mechanism that coordinates CPU, device, and memory NUMA hints. |

## GPU and Hardware

| Term | Explanation |
| --- | --- |
| HBM | High Bandwidth Memory, high-bandwidth GPU memory. |
| SM | Streaming Multiprocessor, the primary compute execution unit on NVIDIA GPUs. |
| VRAM/Framebuffer | GPU memory available for weights, KV Cache, activations, and Workspace. |
| PCIe | The bus connecting devices such as CPUs, GPUs, and NICs; link generation and width affect bandwidth. |
| NUMA | Non-Uniform Memory Access, where differing distances between CPU/memory/devices cause differences in access cost. |
| NVLink | High-speed interconnect between NVIDIA GPUs. |
| NVSwitch | A switch fabric connecting multiple GPUs, commonly used in HGX/DGX. |
| MIG | Multi-Instance GPU, hardware-partitions supported NVIDIA GPUs into isolated instances. |
| MPS | CUDA Multi-Process Service, allows multiple CUDA processes to share GPU execution capability. |
| Time-Slicing | Multiple workloads share a GPU by time, without MIG-style memory or fault isolation. |
| GPU Direct | A collection of data path technologies that reduce CPU bounce buffers between GPUs and devices such as NICs/storage. |
| GPU Direct RDMA | A data path where NICs access GPU memory directly via RDMA. |
| ECC | Error-Correcting Code, used to detect and correct memory errors. |
| XID | A class of GPU error event numbers reported by the NVIDIA Driver. |
| Accelerator Flavor | A platform's stable abstraction of GPU/ASIC model, network, region, price, and other capabilities. |

## Scheduling and Queues

| Term | Explanation |
| --- | --- |
| Admission | The decision of whether a workload is granted quota and may begin creating/running Pods. |
| Gang Scheduling | A group of Pods must all be satisfiable before scheduling, avoiding partial occupancy. |
| PodGroup | An API/concept that expresses multiple Pods as a single scheduling group. |
| Workload | An object in Kueue/upstream scheduling that represents a group of Pods admitted together. |
| Kueue | A Kubernetes-native Job queue and quota admission system; does not replace kube-scheduler. |
| MultiKueue | Kueue's multi-cluster Job dispatch capability, typically sending an entire workload to one chosen Worker Cluster. |
| ClusterQueue | The cross-Namespace quota and policy object in Kueue. |
| LocalQueue | The queue entry point within a Namespace where users submit Workloads. |
| ResourceFlavor | An object in Kueue representing the attributes and Taints of a class of nodes/resources. |
| Cohort | A group of ClusterQueues that share or borrow quota. |
| Preemption | Higher-priority workloads cause lower-priority workloads to release resources. |
| Fair Sharing | Fair allocation among tenants based on historical usage, weights, or shares. |
| TAS | Topology-Aware Scheduling, places workloads as a whole according to rack, Block, host, and other topologies. |
| Volcano | A Kubernetes scheduling and queue system for batch, AI, and HPC workloads. |
| Cluster Autoscaler | Scales Kubernetes nodes by adjusting predefined node groups. |
| Karpenter | Dynamically provisions and manages node lifecycles based on Pending Pods and NodePool constraints. |
| HPA | Horizontal Pod Autoscaler, changes replica count based on metrics. |
| VPA | Vertical Pod Autoscaler, recommends or adjusts Pod CPU/memory requests. |
| KEDA | Scales based on events and external metrics, and supports 0-to-1 activation. |

## Big Data and Lakehouse

| Term | Explanation |
| --- | --- |
| Apache Spark | A distributed compute engine for batch processing, SQL, stream processing, and data preparation; on Kubernetes, the Driver typically creates Executor Pods. |
| Apache Flink | A distributed engine for stateful stream processing and stream-batch jobs, known for Checkpoint, Savepoint, and event-time capabilities. |
| Apache Kafka | A persistent distributed event log used for messaging, CDC, log and traffic buffering; not equivalent to a long-term data lake. |
| KRaft | Kafka's built-in Raft metadata control plane, replacing ZooKeeper. |
| Strimzi | A project that manages Kafka, Node Pool, Topic, User, Connect, and MirrorMaker resources on Kubernetes using Operators. |
| Trino | A distributed SQL query engine for Lakehouse, data source federation, and interactive analytics. |
| Lakehouse | A data architecture that stores data on object storage/file systems and provides tables, Snapshots, transactions, and multi-engine access through open table formats and Catalogs. |
| Open Table Format | Table-level formats such as Iceberg, Delta, and Hudi that manage data files, Schema, Partition, Snapshot, and transactions. |
| Apache Iceberg | An open table format for large analytical tables, supporting Snapshot, Schema/Partition Evolution, and multi-engine reads and writes. |
| Catalog | A metadata service that manages table names, Namespaces, current metadata pointers, and related access entry points. |
| CDC | Change Data Capture, converts database inserts, updates, and deletes into consumable change events. |
| Shuffle | The process of redistributing data by Key/Partition between stages in distributed computing, often consuming significant network, disk, and memory. |
| Backpressure | A pressure signal propagated upstream when downstream processing is too slow; stream systems such as Flink expose processing bottlenecks through this. |

## Ray

| Term | Explanation |
| --- | --- |
| Ray Core | The foundational runtime providing distributed Tasks, Actors, object transfer, resources, and scheduling. |
| Ray Task | A function call that can be remotely executed in parallel, typically used for stateless or short-lived work. |
| Ray Actor | A remote object with state and a stable process lifecycle, commonly used for model Workers, services, and post-training roles. |
| Object Store | The data layer for sharing and transferring objects between Ray nodes; not a persistent object store or data lake. |
| Placement Group | Reserves a set of resource Bundles and co-places Actors or Tasks according to policies such as Pack/Spread. |
| Ray Data | A distributed library for AI data processing, streaming execution, batch inference, and training data supply. |
| Ray Train | A training control layer that coordinates training Workers, framework distributed environments, Checkpoints, and results. |
| Ray Tune | A distributed experimentation and hyperparameter search library that manages Trials, search algorithms, early stopping, and resources. |
| Ray Serve | Organizes independently scalable Python inference services and call graphs using Deployments, Replicas, and Handles. |
| Ray Serve LLM | A framework that extends Ray Serve for multi-model, multi-machine, vLLM/SGLang, P/D separation, and advanced LLM routing. |
| KubeRay | An Operator that manages `RayCluster`, `RayJob`, and `RayService` on Kubernetes. |
| RayJob | KubeRay's batch task resource that can create a RayCluster, submit a Job, and collect the cluster when finished. |
| RayService | A combined resource in KubeRay for a RayCluster and Ray Serve Application, used for online serving and upgrades. |

## Distributed Training

| Term | Explanation |
| --- | --- |
| Rank | The global or local number of a process within a distributed task. |
| World Size | The total number of processes participating in distributed communication. |
| Rendezvous | The process by which Workers discover each other and establish a distributed group. |
| Data Parallel | Each device holds a model replica and processes different data, then synchronizes gradients. |
| Tensor Parallel | Splits tensors and computation within a layer, requiring frequent inter-device communication. |
| Pipeline Parallel | Splits by model layer/Stage and executes with Micro-batch pipelining. |
| Expert Parallel | Distributes MoE Experts across different devices, often involving All-to-All. |
| FSDP | Fully Sharded Data Parallel, shards parameters, gradients, and optimizer states. |
| All-Reduce | A Collective that aggregates data from all Ranks and returns the result to all Ranks. |
| All-Gather | Collects shards from all Ranks and gives each Rank the complete result. |
| Reduce-Scatter | Reduces then distributes result shards to each Rank. |
| All-to-All | Each Rank sends different data to all Ranks; commonly used in MoE. |
| Checkpoint | An artifact that saves recoverable training or model state. |
| RPO | Recovery Point Objective, how much training progress/data loss is acceptable. |
| RTO | Recovery Time Objective, how quickly operations resume after a failure. |
| Elastic Training | A training approach that can reorganize and continue when Worker counts change or after failures. |

## Networking and RDMA

| Term | Explanation |
| --- | --- |
| RDMA | Remote Direct Memory Access, reduces CPU and copy overhead for remote memory access. |
| InfiniBand | A network fabric and protocol stack designed for high-performance computing. |
| RoCE | RDMA over Converged Ethernet, carries RDMA over Ethernet. |
| iWARP | An RDMA protocol based on TCP. |
| HCA | Host Channel Adapter, an InfiniBand/RDMA host adapter. |
| SR-IOV | Virtualizes one PCIe device into multiple VFs for allocation to Pods/VMs. |
| PF/VF | Physical Function / Virtual Function in SR-IOV. |
| Multus | A Kubernetes Meta CNI that attaches multiple network interfaces to Pods. |
| PFC | Priority Flow Control, per-priority flow control commonly used in RoCE lossless networks. |
| ECN | Explicit Congestion Notification, explicit congestion marking. |
| MTU | Maximum Transmission Unit, the maximum frame/packet size a link can carry. |
| NCCL | NVIDIA Collective Communications Library. |
| RCCL | AMD ROCm Collective Communications Library. |
| UCX | A unified communication framework for high-performance networking and memory transfer. |
| NIXL | An NVIDIA open-source library and abstraction for memory/KV data transfer in inference systems. |

## LLM Inference

| Term | Explanation |
| --- | --- |
| Prefill | A phase that processes the input prompt once and generates the initial KV Cache. |
| Decode | The phase that generates output autoregressively, token by token. |
| TTFT | Time To First Token, the latency from request to first token. |
| TPOT | Time Per Output Token, the average time per token during the output phase. |
| ITL | Inter-Token Latency, the latency between adjacent output tokens. |
| E2E Latency | The total latency from request start to the end of the complete response. |
| Goodput | Effective throughput that simultaneously meets SLOs such as latency/quality. |
| Continuous Batching | A batching method that dynamically adds/removes requests at each scheduling step. |
| Chunked Prefill | Splits the Prefill of long prompts to reduce blocking of Decode. |
| KV Cache | The Key/Value intermediate state of Attention, occupying GPU memory with context and concurrency. |
| Paged KV Cache | Manages KV in fixed Blocks, reducing fragmentation and supporting flexible scheduling. |
| Prefix Cache | Reuses the already-computed KV of shared prompt prefixes. |
| KV Offload | Moves KV from GPU HBM to CPU, NVMe, or remote layers. |
| P/D Separation | Prefill and Decode use independent Worker Pools and transfer KV. |
| Speculative Decoding | Draft/MTP etc. first propose multiple candidate tokens, then the main model verifies them. |
| LoRA | Low-Rank Adaptation, expressing model fine-tuning with a smaller Adapter. |
| InferencePool | A set of inference Endpoints in the Gateway API Inference Extension. |
| EPP | Endpoint Picker/Endpoint Picker Provider, selects an Endpoint based on request and backend state. |
| LWS | LeaderWorkerSet, treats one Leader and multiple Workers as a replication unit. |
| Modelcar | A pattern in KServe that attaches a model as an OCI Image to a Serving Pod. |
| AIBrix | A control plane for Kubernetes LLM inference, covering Gateway, routing, elasticity, LoRA, KV Cache, and distributed inference capabilities. |
| NVIDIA NIM | A product stack that wraps models, validated inference runtimes, configuration, and management interfaces as NVIDIA inference microservices. |

## Model, RAG, and MLOps

| Term | Explanation |
| --- | --- |
| Model Registry | A service that manages model versions, metadata, stages, and lineage; it does not necessarily store the weight artifacts themselves. |
| Kubeflow Hub | The evolved name of Kubeflow's Model Registry and Catalog components. |
| Artifact | Immutable output artifacts such as models, data, evaluations, and logs. |
| Lineage | The provenance relationships among code, data, configuration, training, and models. |
| safetensors | A tensor serialization format that does not rely on Pickle code execution. |
| GGUF | A model and quantization metadata format commonly used in the llama.cpp ecosystem. |
| OCI Artifact | An artifact model that uses an OCI Registry to distribute non-container content. |
| Embedding | Converts content such as text/images into vector representations. |
| Vector Database | A database that stores vectors and performs approximate nearest neighbor and Metadata Filter operations. |
| ANN | Approximate Nearest Neighbor, approximate nearest neighbor search. |
| HNSW | A common graph-structured ANN index algorithm. |
| Chunk | The retrieval unit into which documents are split in RAG. |
| Hybrid Search | Retrieval that combines vectors, keywords, and Metadata Filters. |
| Reranker | A model that more precisely ranks initial retrieval candidates. |
| Groundedness | Whether generated content is supported by the provided sources or context. |

## Agent and Sandbox

| Term | Explanation |
| --- | --- |
| Agent Control Plane | A control plane that manages Agent sessions, model calls, budgets, policies, Sandboxes, and tool approvals. |
| Agent Sandbox | A general term for providing isolated execution environments for Agents; it can also specifically refer to the Kubernetes SIG Apps Agent Sandbox CRD/Controller project. |
| Sandbox | An Agent execution instance with an independent lifecycle, file system, resources, and network policies. |
| SandboxTemplate | A reusable Sandbox configuration template maintained by the platform in Kubernetes Agent Sandbox. |
| SandboxClaim | A Kubernetes API object through which users or applications request a Sandbox from the Warm Pool. |
| SandboxWarmPool | A resource pool that pre-starts a set of Sandboxes for quick Claim pickup. |
| Warm Hit | A Sandbox request directly picks up a prepared instance without going through a full cold start. |
| Tool Gateway | A service that proxies Agent external tool calls and performs identity, parameters, authorization, approval, rate limiting, and auditing. |
| gVisor | A sandbox runtime that intercepts and implements application system calls through a user-space kernel, reducing the host kernel's exposure surface. |
| Kata Containers | A runtime that uses lightweight VMs and independent Guest Kernels to provide stronger Pod isolation, integrated with Kubernetes via OCI/CRI. |
| Firecracker | A minimal VMM based on KVM, targeting high-density microVMs; it is a low-level building block rather than a complete Sandbox control plane. |
| MicroVM | A lightweight virtual machine with a minimal device model and Guest OS, commonly used for Serverless and untrusted code isolation. |
| Prompt Injection | An attack method where untrusted content induces the model to ignore intended instructions or abuse tools; it cannot be solved by the Sandbox Runtime alone. |
| Egress Proxy | A proxy that uniformly checks, restricts, and audits Sandbox outbound connections. |

## Platform, Security, and Reliability

| Term | Explanation |
| --- | --- |
| GPU Notebook | An interactive development workspace running on GPU compute resources, typically including JupyterLab, IDE, terminal, persistent Home, and data access, rather than just an `.ipynb` file. |
| Workspace | A development environment that users can stop, resume, and reselect compute specifications for; its Pod lifecycle should be separated from persistent Home, data, and formal tasks. |
| Idle Culler | A controller or service that detects workspaces with prolonged inactivity or no effective computation and stops their compute resources. |
| Golden Image | A standard development image validated and published by the platform, with fixed framework, CUDA, tool, and security patch versions. |
| SLI | Service Level Indicator, the measured service metric. |
| SLO | Service Level Objective, the target that metrics should achieve. |
| Error Budget | The failure or unavailability budget allowed by the SLO. |
| PDB | PodDisruptionBudget, limits the number of Pods affected simultaneously by voluntary disruptions. |
| Canary | Lets a small amount of real traffic use the new version and observes. |
| Shadow | Copies traffic to the new version but does not return results to the main request. |
| GitOps | Uses Git declarations as the desired state and continuously reconciles via controllers. |
| Workload Identity | Uses workload identity to obtain short-term permissions for cloud resources, avoiding static keys. |
| PSA | Pod Security Admission, enforces Pod Security levels per Namespace. |
| SBOM | Software Bill of Materials, a software dependency list. |
| Provenance | Proof of what source code, builds, and processes produced an artifact. |
| Attestation | A verifiable claim about the trusted state of builds, runtime environments, or hardware. |
| TEE | Trusted Execution Environment, a hardware-protected trusted execution environment. |
| Confidential Container | Runs Pods in confidential VMs, combined with attestation and key release. |
| FinOps | An operational practice that links technical resources, usage, costs, and business outcomes. |

## Units and Calibration Reminders

- GPU utilization is not equal to effective business utilization.
- GPU Allocation is scheduled occupancy, Usage is actual computation, and Goodput is effective output that meets SLOs.
- Requests/s cannot represent the cost of LLM requests of different lengths, and Token/s alone cannot represent the interactive experience either.
- Model parameter count is not equal to runtime GPU memory; precision, KV Cache, Workspace, and parallelism must still be added.
- The number of physical GPUs is not equal to the schedulable full-group capacity; topology and failures create fragmentation.
