---
title: "Model Formats, Artifact Supply Chain, and Distribution"
description: "Managing model formats, OCI artifacts, cross-region replication, P2P distribution, node caching, streaming loading, signing, and cold start"
status: evolving
last_reviewed: 2026-08-04
---

# Model Formats, Artifact Supply Chain, and Distribution

Model weights are not just a large file you copy around casually. Production platforms need to compose the model, Tokenizer, configuration, quantization parameters, inference engine compatibility, license, evaluation, and signature into an immutable artifact, and ensure it can be distributed efficiently and securely to target Kubernetes nodes.

## 1. What a Model Artifact Contains

A deployable model version typically includes:

- Weight shards and index;
- `config.json`, Tokenizer, Chat Template;
- Generation/Serving default parameters;
- Quantization configuration, Scale, and calibration information;
- Adapter/LoRA;
- Custom model code or Remote Code review results;
- Target framework, engine, and hardware compatibility information;
- License, provenance, and usage restrictions;
- Offline evaluation, security evaluation, and performance benchmarks;
- SHA-256/OCI Digest, signature, SBOM/Model BOM;
- Release, approval, and rollback status.

The model Registry's metadata and weight storage can be separated, but they must be linked through immutable URIs and Digests.

## 2. Common Model Formats

| Format | Typical Use | Key Characteristics | Considerations |
| --- | --- | --- | --- |
| safetensors | PyTorch/Transformers training and inference | No dependency on Pickle execution; supports sharding and partial reads | Still need to verify provenance, configuration, and external code |
| PyTorch `.bin/.pt` | Legacy models, Checkpoints | Broad ecosystem | Pickle-like formats may execute code; do not directly trust external files |
| GGUF | Local/edge inference with llama.cpp and similar | Model, Tokenizer, and quantization metadata in one place | Support differs from datacenter engines |
| ONNX | Cross-framework inference | Standardized graph and operators | Opset, dynamic shapes, and custom operator compatibility |
| TensorRT Engine | NVIDIA optimized inference | Highly optimized for specific hardware and build environments | Sensitive to Compute Capability, TensorRT/driver versions |
| Neuron/other compiled artifacts | AI ASIC | Reduces deployment-time compilation | Usually bound to chip, compiler, and input Shape |
| Checkpoint | Continued training | Contains optimizer, RNG, scheduler, and other state | Not equivalent to a directly deployable inference artifact |

safetensors reduces the risk of code execution during deserialization, but a model repository may still contain Python Remote Code, Tokenizer extensions, and malicious configuration. Format safety must not be equated with end-to-end supply chain security.

Reference: [Safetensors](https://huggingface.co/docs/safetensors/main/index)

## 3. Relationship Between Base Models, Fine-Tuning, and Quantization

```text
基础模型 Revision
  ├── 完整微调权重
  ├── LoRA / Adapter
  ├── 合并后的部署权重
  └── 多种量化或硬件编译制品
        ├── BF16 / FP16
        ├── FP8
        ├── INT8
        ├── INT4 / AWQ / GPTQ
        └── GGUF / 厂商 Engine
```

Every derived artifact should record the parent model Digest, conversion tools, commands, calibration data, and quality changes. Recording only a model name is insufficient to reproduce a deployment.

## 4. Model Version Identification

Not recommended:

```text
s3://models/chat/latest/
hf://org/model-main
registry.example.com/model:latest
```

Recommended: use immutable identifiers:

```text
s3://models/chat/2026-08-02/manifest.json#sha256=...
hf://org/model@<commit-sha>
registry.example.com/models/chat@sha256:<digest>
```

Business aliases such as `chat-production` may point to immutable versions, but alias changes themselves must be audited and quickly reversible.

## 5. Artifact Manifest

Conceptual example:

```yaml
apiVersion: platform.example.com/v1alpha1
kind: ModelArtifact
metadata:
  name: chat-model-2026-08-02
spec:
  source:
    baseModel: hf://org/base-model@commit-sha
    trainingRun: mlflow://experiments/42/runs/run-id
  artifact:
    uri: oci://registry.example.com/models/chat@sha256:digest
    format: safetensors
    precision: fp8
    sizeBytes: 73400320000
  compatibility:
    engines: [vllm, sglang]
    accelerators: [nvidia-hopper]
  evidence:
    evaluation: s3://evidence/chat/eval-v12.json
    benchmark: s3://evidence/chat/perf-h100-v4.json
    signature: cosign://registry.example.com/models/chat@sha256:digest
```

This is not a standard Kubernetes API, but an example of a metadata contract. It can be implemented by Kubeflow Hub, MLflow, OCI Annotation, or an internal Catalog.

## 6. Storage Methods

### Object Storage

Advantages: large capacity, durability, mature lifecycle and permission management. Disadvantages: direct downloads from every Pod create egress spikes and cold-start latency.

Suitable for authoritative model copies and Checkpoints, but not necessarily suitable as a direct runtime random-read layer.

### Hugging Face Hub or Model Hub

Suitable for discovery and upstream synchronization. Production environments should:

- Pin the Commit Revision;
- Mirror or sync to controlled storage;
- Use short-lived credentials;
- Record license and scan results;
- Avoid all production Pods directly depending on the external public internet.

### Shared File System/PVC

Multiple Pods can share downloaded models, but metadata performance, concurrent reads, availability zones, and cache consistency must be verified. A single RWO PVC cannot directly satisfy multi-replica across nodes.

### OCI Registry

Models as OCI Artifacts or Modelcars can reuse the Registry's Digest, permissions, image distribution, and node caching. Large Layers, garbage collection, signing, Registry bandwidth, and Snapshotter need to be evaluated.

## 7. OCI Registry Selection: Beyond Harbor

Harbor is a feature-complete, mature open-source choice, but not the only option. Selection should first distinguish between lightweight Registries, enterprise-grade Registries, development-platform built-in Registries, general-purpose artifact repositories, and cloud-hosted services.

### Self-Hosted vs. Managed Options Comparison

| Option | Type | Suitable For | Key Characteristics and Boundaries |
| --- | --- | --- | --- |
| Harbor | Open source, self-hosted | General-purpose enterprise Registry, multi-project, replication, and security governance | Complete UI, RBAC, Proxy Cache, replication, scanning, and signing ecosystem; component and database operations are relatively heavy |
| Zot | Open source, self-hosted | Lightweight private Registry, edge, small or dedicated model repositories | OCI-native, single binary; can enable authentication, authorization, scanning, GC, deduplication, image sync, and HA; platform governance ecosystem is smaller than Harbor |
| Project Quay / Red Hat Quay | Open source/commercial support | Enterprise, multi-tenant, OpenShift, and multi-region | Clair scanning, Robot Accounts, and Geo-replication; database, object storage, and failover still require overall design |
| CNCF Distribution | Open source, self-hosted | Minimal Registry, test environments, or a base for secondary development | Upstream Registry implementation with clear TLS, authentication, and storage drivers; lacks full UI, scanning, tenancy, replication, and policy management |
| GitLab Container Registry | GitLab SaaS/self-hosted integration | GitLab CI/CD is already the primary development entry point | Convenient project permissions, CI Tokens, cleanup policies, and metadata integration; OCI 1.1 Referrers support for the target version must be verified separately |
| GitHub Container Registry | Cloud-hosted | GitHub projects, open source, and Actions pipelines | Simple integration with Repository/Actions permissions; not suitable as the sole upstream for offline or on-premises production clusters |
| JFrog Artifactory | Commercial, self-hosted/SaaS | Manages OCI, Maven, PyPI, npm, models, and other artifacts simultaneously | Strong Remote/Virtual Repository and supply chain governance; higher licensing, cost, and platform complexity |
| ECR / Artifact Registry / ACR | Public cloud managed | Cluster primarily runs on a single public cloud | IAM, VPC, Kubernetes, scanning, replication, and managed storage integration with low operational cost; cross-cloud and migration are constrained by cloud interfaces |
| Alibaba Cloud ACR Enterprise Edition | Domestic cloud managed | ACK, multi-region at home and abroad, and large image distribution | OCI artifacts, multi-region sync, P2P, and on-demand loading suit domestic networks; production should use enterprise tiers with SLA |

### Quick Decision Guide

| Condition | Preferred Candidate |
| --- | --- |
| Need a complete platform with open-source UI, RBAC, scanning, replication, and Proxy Cache | Harbor |
| Want a lightweight, OCI-native, standalone model/image repository | Zot |
| OpenShift/Red Hat ecosystem or need Quay enterprise support | Quay |
| Already using GitLab for code, CI, and project permissions | GitLab Container Registry |
| Need unified management of multiple language packages, binaries, containers, and models | JFrog Artifactory |
| All workloads on a single public cloud | Prefer that cloud's managed Registry |
| Only need a minimal `/v2/` API or plan secondary development | CNCF Distribution |

Do not compare only "whether it can `docker push`". Production capability at minimum includes:

- Namespace/Repository permissions and Robot/Workload Identity;
- Tag Immutability, Digest pulls, and retention policies;
- Online/offline Garbage Collection and its availability impact;
- Vulnerability scanning, signing, SBOM/Model BOM, and audit;
- Proxy/Pull-through Cache and external source governance;
- Object storage Backend, database backup, and disaster recovery;
- Cross-AZ/region replication consistency, latency, and failure semantics;
- Monitoring, rate limiting, and SLOs for concurrent uploads and downloads.

### Special Checks for Large Model Weights

An OCI Registry can store Artifacts beyond containers. ORAS provides tools for pushing, pulling, and developing OCI Artifact clients; it is not a Registry Server. Different Registries may vary in their support for OCI 1.1 `subject`, the Referrers API, custom Media Types, and Artifact UI, so actual verification against the target version is required.

For large models, also verify:

- Whether large Blob uploads can resume after interruption, and whether Gateway/Ingress has Body, Buffer, and timeout limits;
- How model shards map to Layers, and whether updating a small amount of weights causes all Layers to be re-uploaded;
- Registry, object storage, and egress throughput and rate limiting when many Pods cold-start simultaneously;
- Whether Layers are decompressed/copied after download, and how much temporary disk the container runtime needs;
- Whether cross-region replication completion enters the model release gate;
- Whether GC understands Blobs still referenced by Manifests, signatures, SBOMs, or Referrers;
- Whether Tags are immutable, and whether training, deployment, and rollback always record the Manifest Digest;
- Whether a regional Registry, Pull-through Cache, Dragonfly/P2P, or node model cache is needed;
- When the Registry fails, whether pre-warmed nodes can continue serving, and how new nodes degrade safely.

The Registry is responsible for authoritative artifacts and the distribution entry point; Dragonfly/P2P, node caches, and Snapshotter belong to the acceleration data plane and cannot replace the Registry's approval, signing, permissions, and lifecycle.

Reference: [Zot Registry](https://zotregistry.dev/latest/), [Project Quay](https://docs.projectquay.io/), [CNCF Distribution](https://distribution.github.io/distribution/about/), [GitLab Container Registry](https://docs.gitlab.com/user/packages/container_registry/), [ORAS](https://oras.land/docs/), [Amazon ECR Pull-through Cache](https://docs.aws.amazon.com/AmazonECR/latest/userguide/pull-through-cache.html), [Azure Container Registry](https://learn.microsoft.com/en-us/azure/container-registry/container-registry-concepts), [Alibaba Cloud ACR](https://help.aliyun.com/zh/acr/product-overview/what-is-container-registry/)

## 8. KServe Modelcar

KServe supports using `oci://` to point to an OCI Image containing model data:

```dockerfile
FROM busybox
RUN mkdir -p /models && chmod 775 /models
COPY model/ /models/
```

```yaml
apiVersion: serving.kserve.io/v1beta1
kind: InferenceService
metadata:
  name: example-model
spec:
  predictor:
    model:
      modelFormat:
        name: huggingface
      storageUri: oci://registry.example.com/models/example@sha256:replace
```

Use Digest to avoid Tag drift. The Modelcar's process namespace, UID, caching, and security behavior must be verified against the target KServe version.

Reference: [KServe OCI Modelcars](https://kserve.github.io/website/docs/model-serving/storage/providers/oci)

## 9. Local Model Caching

Model cold-start path:

```text
远端 Registry/对象存储
  → 节点本地 NVMe/镜像缓存
  → Pod Volume/Modelcar
  → CPU 内存
  → GPU HBM
  → 引擎预热和 Prefix/KV Cache
```

Each cache layer differs:

| Cache | Lifecycle | Value |
| --- | --- | --- |
| Registry/object storage CDN | Platform-level | Reduces cross-region traffic |
| Node image Layer | Node-level | Reuses OCI model layers |
| LocalModelCache/NVMe | Node-level | Avoids repeated weight downloads |
| Page Cache | OS-level | Accelerates reads of the same files |
| GPU weights | Pod/process-level | Model is actually executable |
| Prefix/KV Cache | Request-level | Reduces repeated computation |

Prefix Cache hit rate must not be used to measure model weight caching, and Pod Running must not be taken as evidence that GPU weights are already loaded.

## 10. KServe LocalModelCache

KServe LocalModelCache can pre-download models on target nodes and maintain node cache status. Typical objects include `LocalModelNodeGroup`, `LocalModelCache`, and `LocalModelNode`.

Points to watch:

- Target nodes and GPU models;
- Local paths, HostPath, and UID/GID;
- The model URI must match the InferenceService;
- CPU, memory, and network of the cache download Job;
- Disk watermarks, eviction, and failure retry;
- Pre-warming during node replacement and scale-out;
- Whether cache Ready enters Pod/Gateway Readiness.

As of this page's review date, the LocalModel API is still `v1alpha1` and is installed as an optional KServe component; the official installation documentation states that only `InferenceService` is currently supported, with `LLMInferenceService` support still planned. Before production adoption, pin the KServe/LocalModel version; do not assume the interface is GA merely because the CRD name is stable.

Reference: [KServe Local Model Cache](https://kserve.github.io/website/docs/model-serving/generative-inference/modelcache/localmodel), [LocalModel Installation](https://kserve.github.io/website/docs/install/localmodel-install)

## 11. Distribution Strategies

### Download per Pod

Simplest, but large-scale scale-out causes repeated transfers and consumes object storage requests. Suitable for small models or low replica counts.

### Init Container Downloads to PVC/emptyDir

Clear logic and supports multiple storage types; but Pods may re-download on every rebuild, and insufficient Init Container resources can cause OOM.

### DaemonSet/Controller Pre-warms Local Disks

Suitable for large models and fixed GPU node pools. Requires data-locality scheduling, cache status, and cleanup controllers.

### OCI Layer/Modelcar

Reuses the Registry and node image cache; Digest and signing come naturally; requires handling very large Layers, decompression, GC, and Runtime support.

### P2P Distribution

Large-scale nodes can distribute from nodes with existing caches, reducing central storage hotspots. Adds peer discovery, integrity, flow control, and security complexity; adopt only when scale genuinely requires it.

### Streaming or Lazy Loading

The engine can concurrently read Tensors from remote sources such as HTTP/S3, or deserialize while downloading in a specific format, reducing full disk writes and CPU/memory peaks. It optimizes the path of "remote bytes entering the engine/GPU" and cannot replace immutable versions, regional replication, permissions, caching, and rollback.

## 12. Mainstream Production Layering

The current mainstream approach is not to choose one of object storage, OCI, PVC, or P2P, but to have them serve different layers:

```text
训练 / 转换 / 量化流水线
        ▼
Model Registry / Catalog
  记录版本、Digest、血缘、评估、兼容性和审批
        ▼
权威制品层
  Object Storage 或 OCI Registry
        ▼
区域分发层
  跨地域复制、区域 Registry/Bucket、CDN/Seed
        ▼
集群分发层
  Storage Initializer / 共享文件 / P2P / 预热控制器
        ▼
节点缓存层
  OCI Layer Cache / LocalModelCache / 本地 NVMe
        ▼
运行时加载层
  mmap / Page Cache / 并行反序列化 / Streaming
        ▼
GPU HBM + Engine Warmup
        ▼
Traffic Ready
```

It is recommended to separate the control plane from the data plane:

| Layer | What state is saved | Whether it transfers large model bytes |
| --- | --- | --- |
| Model Registry/Catalog | Model versions, approvals, evaluations, lineage, and deployment aliases | Usually does not directly handle large-scale runtime downloads |
| Release/Placement controller | Which version should go to which regions, clusters, and node groups | Triggers replication and preheating, does not necessarily proxy bytes |
| Object/OCI storage | Immutable authoritative artifacts and digests | Yes, as the origin and cross-region replication source |
| P2P/cache system | Pieces, peers, node caches, and download status | Yes, handles large-scale in-cluster distribution |
| Serving Controller/Gateway | Pods, model readiness, traffic, and version status | No, model bytes should not be placed in the Kubernetes API |

This layering prevents a single system from simultaneously handling artifact governance, cross-region replication, node caching, and request serving. The most common production combination is: **object storage or an OCI Registry as the authoritative source, with regional replicas retained, preheated to GPU node local NVMe before release; P2P is added when the node fleet is very large.**

## 13. Cross-Region Model Distribution

Multi-region platforms should not let every Pod pull from a central bucket or public Model Hub across the WAN. A more robust path is:

```text
Global Artifact Digest
  ├── Region A Registry/Bucket
  │     └── Cluster A Seed/Node Cache
  ├── Region B Registry/Bucket
  │     └── Cluster B Seed/Node Cache
  └── Region C Registry/Bucket
        └── Cluster C Seed/Node Cache
```

A multi-region release should pass through the following states:

1. `ArtifactApproved`: Authoritative artifact, signature, and evaluation pass;
2. `RegionReplicated`: The target region already has the same digest;
3. `NodePreheated`: The target GPU node group reaches cache coverage;
4. `EngineReady`: Weights have entered the runtime and completed necessary compilation/preheating;
5. `TrafficReady`: The Gateway only then allows real traffic in.

Key principles:

- Each region uses the same artifact digest; do not use drifting tags for synchronization;
- Replicate the complete set of model manifest, weight shards, tokenizer, configuration, quantization scales, and custom code;
- Regional replication status must be part of the release gate; missing files should not be discovered ad hoc at Pod startup;
- Regions with strict SLOs retain warm caches for the current and previous versions;
- Replication failure only blocks new regions from receiving traffic; it does not break already-running old versions;
- Use in-region identities to read regional replicas, avoiding distributing a single global long-lived access key to all clusters;
- Meter cross-region replication traffic and in-cluster distribution traffic separately; their cost and capacity attribution differ.

OCI Registry layer deduplication only works for layers with identical content. Even small numerical changes in a weight shard produce a new digest, so do not base incremental sync benefits on the intuition that "model versions are similar"; measure based on real shards and Registry behavior.

## 14. P2P Distribution at 100-Node and TB Scale

The theoretical traffic for direct origin fetch is approximately:

```text
源站读取量 ≈ 模型大小 × 同时冷启动的节点数
```

If a model cold-starts on 200 nodes simultaneously, any origin, egress, ToR, or object storage rate limit can become a long tail. P2P lets the pieces obtained from the first origin fetch be served to other nodes; the origin mainly handles the first copy of data for each region or P2P domain, and subsequent traffic spreads between peers.

One layered topology is:

```text
Region Object Storage / OCI Registry
        ▼
Regional Seed Peer
        ▼
Rack / Network Block Peers
        ▼
GPU Node Local NVMe
```

Systems like Dragonfly split files into pieces; the Scheduler selects parent nodes based on peers and load, and Seed Peers handle the initial origin fetch. It suits scenarios where many nodes simultaneously need the same model, dataset, or image. [Dragonfly](https://d7y.io/docs/)

Before rolling out P2P, clarify:

- Whether P2P domains are divided by region, data center, rack, or tenant;
- Whether origin fetch can safely fall back when Seed, Scheduler, or Peer fails;
- Per-node upload/download concurrency, disk I/O, and network bandwidth limits;
- Whether to avoid cross-rack/cross-zone peer traffic that could increase network costs;
- How pieces, complete files, and the final artifact digest are validated at each level;
- Whether a peer could serve model content to unauthorized tenants;
- How download cancellation, partial pieces, node restarts, and cache eviction are cleaned up;
- How proactive preheat before release and request-triggered on-demand downloads divide responsibilities;
- Whether P2P telemetry can correlate model digest, region, node, and release batch.

P2P is the distribution data plane, not an authoritative Registry. Peer caches can be lost and rebuilt at any time; model approval, signing, lifecycle, and rollback remain the responsibility of the upper-layer artifact system.

## 15. Distribution Completion Does Not Mean the Model Is Serviceable

A model passes through at least four distinct states from authoritative storage to actually serving requests:

| State | Meaning | Common misjudgment |
| --- | --- | --- |
| Artifact Ready | Artifact is complete and approved in authoritative storage | Mistakenly assuming all regions are already available |
| Node Cached | Files are on the target node's local disk and validated | Mistakenly assuming GPU is already occupied |
| Engine Ready | Engine has loaded weights, allocated HBM, and completed initialization | Mistaking Pod Running for this state |
| Traffic Ready | Warmup, health checks, and route registration complete | Measuring TTFT before preheating |

Streaming loading or Tensorizer-style approaches can read tensors in parallel from HTTP/S3, reducing full download and deserialization time; some implementations also reduce CPU memory usage. [vLLM Tensorizer](https://docs.vllm.ai/en/latest/models/extensions/tensorizer/)

Their costs include:

- Deeper coupling between model format and inference engine;
- Remote storage latency can enter the startup or even first-access path;
- Failure semantics for network interruption, retries, and partial loading are more complex;
- Converted artifacts need lineage, quality, and compatibility management alongside the original safetensors;
- Supporting streaming does not justify removing regional replicas and local caches.

For strict online SLOs, the safer default remains placing the complete, validated model on local NVMe first, then having the engine load it in parallel; streaming is used for benchmark-proven startup optimizations or long-tail models.

## 16. Training and Inference Distribution Paths Differ

| Dimension | Training/Checkpoint | Online inference weights |
| --- | --- | --- |
| Access pattern | Large-scale reads + periodic writes | Mostly read-only, concentrated reads at release time |
| Common authoritative layer | Object storage, parallel file systems | Object storage, OCI Registry, Model Hub mirrors |
| Localization | Dataset/base model cache, checkpoint staging | GPU node NVMe hot model cache |
| Consistency focus | Atomic checkpoints, shard completeness, recovery points | Immutable digest, all replicas load the same version |
| Scaling approach | Shards, parallel I/O, asynchronous upload | Regional replication, preheating, P2P, parallel loading |
| Reclamation policy | Retain recovery points and training lineage | Keep current/previous version hot, long-tail by LRU |

Training checkpoints should not simply reuse the inference Modelcar flow. They may be written in parallel by all ranks, contain optimizer and RNG state, and require a completion marker or manifest for atomic publication. Inference artifacts should be promoted by the training/conversion pipeline to an immutable read-only version before entering distribution.

Base models and adapters can also be layered: large base models reside on nodes long-term, while smaller LoRA/adapters are versioned independently and distributed on demand. Adapter compatibility with the base model digest, tokenizer, engine version, and tenant permissions still needs validation; do not assemble them by file name alone.

## 17. Model Release State Machine

A controllable model release flow can be represented as:

```text
Build
  → Scan / Evaluate
  → Sign
  → Replicate Regions
  → Preheat Nodes
  → Load Engine
  → Warmup
  → Shadow
  → Canary
  → Promote
  → Drain Old Version
  → Retain for Rollback
```

The release controller or pipeline should check:

- Artifact digest matches the approval record;
- Target region replication is complete and validated;
- Target node cache coverage reaches the threshold;
- Runtime, GPU, and quantization format requirements of old and new models are compatible;
- Engine Ready count meets minimum available capacity;
- Shadow/Canary quality, TTFT, TPOT, error rate, and cost meet targets;
- Rollback version still retains regional replicas, node caches, and compatible runtime;
- Do not clean up old models and long-lived connections before drain completes.

Do not let the Autoscaler download hundreds of GB of weights for the first time only after a traffic peak arrives. Node provisioning, model preheating, and replica scaling for online inference need joint planning; keep empty GPU nodes or a warm pool when necessary.

## 18. Capacity and Bandwidth Planning

Single-node download time can be roughly estimated as:

```text
下载时间下限 ≈ 模型大小
              / min(源站分配带宽, 网络带宽, 磁盘写入, Peer 供给带宽)
              + 校验与文件落盘时间
```

Large-scale releases also need to account for:

```text
源站放大倍数 = 源站实际发送字节 / 模型逻辑大小
缓存覆盖率   = 已缓存目标 Digest 的合格节点 / 目标节点总数
有效预热率   = 发布时真正命中缓存的副本 / 新启动副本总数
```

Local disk cannot be planned by "one model size" alone:

```text
本地缓存预算 = 当前生产模型
             + 回滚版本
             + Canary/下一版本
             + 热门 Adapter
             + 下载临时空间
             + 容器镜像与日志
             + GC 安全水位
```

Model shards also involve trade-offs: overly large shards reduce metadata count but make single-shard failure retries expensive and concurrency low; overly small shards increase request count, filesystem metadata, and open-file pressure. Shard size, engine parallel loading capability, object storage multipart, and P2P piece strategy should be benchmarked together, rather than mechanically unifying file sizes.

## 19. Cold Start Budget

```text
冷启动 = 节点供给
       + 驱动/设备组件就绪
       + 容器镜像拉取
       + 模型权重下载/挂载
       + 权重反序列化
       + CPU → GPU 传输
       + 图编译/Kernel Autotune
       + 引擎预热
       + Gateway 发现
```

Measure P50/P95 for each item, and record both cold and hot cache cases. Even with 10 Gbit/s remote bandwidth, a 100 GiB model has a theoretical transfer floor of over a minute; in practice, protocol, concurrency, decompression, and storage bottlenecks also apply.

## 20. Integrity and Signing

Recommended chain:

```text
受控训练/转换
  → 生成 Manifest 与评估证据
  → 计算 Digest
  → 上传不可变存储/OCI Registry
  → 签名与 Attestation
  → Registry 审批
  → Admission/部署控制器校验
  → 节点下载后再次校验
```

Sign not only weights but also the tokenizer, configuration, quantization scales, and custom code. Digest consistency only proves content is unchanged; it does not prove model quality or trustworthy provenance.

## 21. Permission Model

- Model discovery, read, publish, promote, and delete use different permissions;
- Production Pods read only specific approved digests;
- Download credentials are obtained via Workload Identity or short-lived Secrets;
- Registry administrators cannot automatically become model approvers;
- External models first enter an isolated scanning zone;
- Model licenses and data usage restrictions go into metadata;
- Audit who promoted which model version into which environment.

## 22. Garbage Collection

Objects to clean up include:

- Failed or unapproved converted artifacts;
- Unreferenced layers/manifests in the Registry;
- Expired models on node local storage;
- Adapters no longer in use;
- Historical evaluation and benchmark evidence;
- Model versions outside the rollback window.

Before deletion, check live deployments, canaries, rollback policy, training lineage, and compliance retention. Caches can be cleaned by LRU; authoritative artifacts cannot use the same policy.

## 23. Observability

At minimum, record:

- Model URI, digest, size, and shard count;
- Cross-region replication progress, latency, backlog, and failures;
- Artifact availability and origin fetch path per region;
- Download queue, throughput, failures, and retries;
- Per-node cache usage, hits, and evictions;
- Target node cache coverage, effective preheat rate, and origin fetch amplification factor;
- P2P seed/peer count, piece hits, origin fetch bytes, and cross-failure-domain traffic;
- Image/Modelcar pull time;
- Time for each stage: Artifact Ready, Region Replicated, Node Cached, Engine Ready, and Traffic Ready;
- Weight deserialization, CPU memory peak, CPU→GPU transfer, graph compilation, and preheat time;
- Registry/object storage rate limiting and errors;
- Digest/signature verification failures;
- Download traffic and cost generated by each scale-out.

All metrics should carry at least the applicable dimensions from `model_digest`, `region`, `cluster_id`, `node`, `source`, and `release_id`. Model names or tags are insufficient to distinguish actual byte versions.

## 24. Common Failures

| Symptom | Possible cause |
| --- | --- |
| Init:OOMKilled | Storage Initializer ran out of memory |
| Multiple replicas stuck simultaneously | Registry/object storage rate limiting or egress saturation |
| A region's release stays Pending | Regional replication incomplete, digest mismatch, or incorrect target permissions |
| P2P is slower instead of faster | Insufficient seeds, cross-zone peers, disk bottlenecks, or misconfigured rate limits |
| P2P control plane failure | New downloads cannot be scheduled; existing caches must continue serving and fall back to origin safely |
| Cache shows Ready but Pod cannot find it | HostPath, UID, URI, or node group mismatch |
| Files exist but Engine is not Ready | Missing shards, format/engine incompatibility, insufficient CPU memory or HBM |
| Same Tag behaves differently | Tag drift or different pull policies |
| Weights load but output is wrong | Tokenizer, configuration, or quantization scale mismatch |
| New hardware cannot start | Engine/quantized artifacts bound to old architecture |
| Node disk full | Layer, model cache, and log GC failing |
| Streaming first-request jitter | Remote reads, lazy page faults, or incomplete engine warmup |
| Rollback fails | Old model or corresponding runtime already cleaned up |

## 25. Production Checklist

- [ ] Model version links weights, tokenizer, configuration, quantization, and evaluation.
- [ ] All production deployments use immutable revisions or digests.
- [ ] External models pass license, format, custom code, and security review.
- [ ] Each hardware/engine combination has explicit compatibility metadata.
- [ ] Model download, loading, and preheating are timed in stages.
- [ ] Each production region has a controlled replica of the same digest, without relying on Pods fetching from origin across the WAN.
- [ ] Regional replication, node preheating, Engine Ready, and Traffic Ready are distinct release gates.
- [ ] Large-scale scale-out does not overwhelm the Registry or object storage.
- [ ] 100-node-level concurrent downloads have evaluated P2P/seed, origin fetch degradation, flow control, and failure domains.
- [ ] Node caches have capacity, watermark, eviction, and rebuild policies.
- [ ] The scheduler or Serving Controller can identify whether target nodes have the specified digest cached.
- [ ] Current, rollback, and canary versions can fit within the local cache budget simultaneously.
- [ ] Streaming/lazy loading has passed cold/hot cache benchmarks and remote failure tests.
- [ ] Training checkpoints and read-only inference artifacts use different consistency and retention policies.
- [ ] Base model and adapter digest, compatibility, and tenant permissions can be jointly validated.
- [ ] Signature verification and model approval are different control layers.
- [ ] Old versions remain deployable within the rollback window.
- [ ] Artifacts, caches, and evaluation evidence each have retention policies.

## Further Reading

- [KServe Storage Overview](https://kserve.github.io/website/docs/model-serving/storage/overview)
- [KServe OCI Modelcars](https://kserve.github.io/website/docs/model-serving/storage/providers/oci)
- [KServe Local Model Cache](https://kserve.github.io/website/docs/model-serving/generative-inference/modelcache/localmodel)
- [KServe LocalModel Installation](https://kserve.github.io/website/docs/install/localmodel-install)
- [Zot Registry](https://zotregistry.dev/latest/)
- [Project Quay](https://docs.projectquay.io/)
- [CNCF Distribution](https://distribution.github.io/distribution/about/)
- [GitLab Container Registry](https://docs.gitlab.com/user/packages/container_registry/)
- [ORAS](https://oras.land/docs/)
- [Hugging Face Hub Download and Cache](https://huggingface.co/docs/huggingface_hub/en/guides/download)
- [Dragonfly](https://d7y.io/docs/)
- [vLLM Tensorizer](https://docs.vllm.ai/en/latest/models/extensions/tensorizer/)
- [Safetensors](https://huggingface.co/docs/safetensors/main/index)
- [OCI Image Specification](https://github.com/opencontainers/image-spec)
- [Sigstore Cosign](https://docs.sigstore.dev/cosign/signing/signing_with_containers/)
