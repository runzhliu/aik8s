---
title: "Big Data on Kubernetes"
description: "Spark, Flink, Kafka, Trino, Lakehouse, object storage, Operators, queue scheduling, and integration with LLM training and RAG"
status: evolving
last_reviewed: 2026-08-04
---

# Big Data on Kubernetes

Large models have not made big data platforms disappear; instead they have expanded their responsibilities: training corpus cleaning, deduplication and quality filtering, RAG document parsing and incremental updates, batch Embedding generation, online feedback ingestion, and model evaluation data construction all require a stable data engineering pipeline.

Kubernetes can unify containers, resources, identity, release and observability, but it does not automatically provide distributed SQL, stream state, message persistence or Lakehouse transactions. When building "Big Data on Kubernetes", you must model the Kubernetes control plane, compute engines, data systems and AI workloads separately.

For the boundary between Ray Data and Spark/Flink, and how it connects LLM training, post-training and inference, see [Ray's role in LLM training and inference](../ray-llm-platform.md).

## 1. From Hadoop clusters to cloud-native data platforms

Big data platforms have roughly gone through three main lines:

1. **Storage and compute bound together**: HDFS stores data, YARN manages compute resources for MapReduce, Spark, etc., and node scaling often adds both storage and compute.
2. **Compute containerization**: Spark, Flink, Kafka, Trino, etc. gradually gained Kubernetes deployment methods, and Operators began managing stateful upgrades and job lifecycles.
3. **Storage and compute separation**: Object storage becomes the authoritative data layer, columnar files such as Parquet/ORC store data, open table formats such as Iceberg/Delta/Hudi manage table snapshots and transactions, and different compute engines read the same data on demand.

The current mainstream direction is not "rewriting Hadoop with Kubernetes", but rather:

- Kubernetes manages compute, service lifecycle, resources and security boundaries;
- Object storage or retained HDFS manages persistent bytes;
- Lakehouse Catalog and open table formats manage tables, Snapshots and transactions;
- Spark/Flink handle batch and stream processing;
- Kafka handles event logs and traffic buffering;
- Engines such as Trino provide interactive SQL;
- Airflow, Argo Workflows, Flyte, etc. orchestrate cross-system dependencies;
- AI platforms consume data that has passed versioning and quality gates.

Kubernetes is not a data semantics layer. A Pod restarting successfully does not mean Flink state can be recovered; a Spark Job completing does not mean the Iceberg Snapshot has passed quality audit.

## 2. First classify by workload

| Workload | Typical systems | Lifecycle | Primary goal |
| --- | --- | --- | --- |
| Offline ETL/ELT | Spark, Flink Batch, Ray Data | Minutes to hours, released after use | Throughput, cost, retryability, data quality |
| Real-time stream processing | Flink, Kafka Streams, Spark Structured Streaming | Long-running | Lag, Backpressure, state consistency, recovery time |
| Messaging and event logs | Kafka | Long-running stateful | Durability, partition availability, replication and end-to-end latency |
| Interactive SQL | Trino | Long-running service + short queries | Concurrency, queuing, query latency and resource isolation |
| Lakehouse maintenance | Spark, Flink, Trino | Periodic jobs | Compaction, Snapshot, orphan file and small file governance |
| AI data preparation | Spark, Ray, GPU ETL, custom Jobs | Batch or incremental | Sample quality, traceability, throughput and cost |
| RAG index updates | Kafka/Flink + Embedding Worker | Continuous or micro-batch | Freshness, idempotency, permissions and index consistency |

Don't let one elasticity policy control all workloads at the same time. Spark Executors can disappear with the Job, but Kafka Brokers and Flink stateful Jobs cannot be scaled down arbitrarily like ordinary stateless Deployments.

## 3. A layered reference architecture

```text
业务数据库 / 日志 / 文件 / SaaS / IoT
              │
        CDC / Kafka / Connect
              │
      Flink 实时清洗与聚合
              │
              ├──────────────→ 在线特征 / 告警 / 实时索引
              ▼
对象存储：Raw / Bronze / Silver / Gold
              │
       Iceberg / Delta / Hudi
              │
    Catalog / Schema / Lineage / Policy
              │
      ┌───────┼───────────┐
      ▼       ▼           ▼
    Spark    Trino      Ray / GPU ETL
   批处理   交互 SQL      AI 数据处理
      │       │           │
      └───────┼───────────┘
              ▼
训练数据集 / 评估集 / RAG Chunk / Embedding / 特征
              │
       训练、推理、RAG 与 Agent
```

The control plane typically includes:

```text
Git / CI / Data Pipeline
        │
Airflow / Argo / Flyte / Kubeflow Pipelines
        │
Spark/Flink/Kafka Operator、Helm、Kubernetes Job
        │
Kueue / Volcano / YuniKorn / kube-scheduler
        │
NodePool、CSI、CNI、对象存储身份与可观测性
```

The data plane and control plane must each have their own high availability. An Operator being healthy does not replace Kafka replicas, Flink Checkpoints or Catalog database backups.

## 4. How to choose the main components

| Component | Core positioning | Suitable for | Main cost |
| --- | --- | --- | --- |
| Spark | General batch processing, SQL, micro-batch streaming, ML data preparation | Large-scale ETL, table maintenance, training corpus processing | Shuffle, Driver stability, startup and small file governance |
| Flink | Stateful stream processing and stream-batch jobs | CDC, real-time aggregation, event time, low-latency incremental pipelines | Checkpoint, state Backend, complex upgrade compatibility |
| Kafka | Persistent event log and decoupling | Event bus, CDC, logs, traffic buffering | Broker storage, partition planning, cross-zone traffic and long-term operations |
| Trino | Distributed interactive SQL | Federated queries, Lakehouse BI, data exploration | Memory, Coordinator, concurrency governance and Connector differences |
| Iceberg/Delta/Hudi | Open table formats | Snapshot, Schema/Partition Evolution, concurrent reads and writes | Still requires Catalog, object storage and maintenance jobs |
| Ray Data | Python/AI data processing | Data preparation sharing the Python/Ray ecosystem with training | Should not replace all SQL/streaming platforms just because training uses Ray |
| RAPIDS Accelerator for Spark | Lets supported Spark SQL/DataFrame operators use NVIDIA GPUs | ETL with proven GPU acceleration benefits | Operator coverage, data transfer, GPU cost and version matrix |

When selecting, look at data semantics and SLOs first; don't start by asking "which project is most cloud-native".

## 5. Spark on Kubernetes

In Spark's native Kubernetes mode, the Driver Pod creates Executor Pods through the Kubernetes API; Executors run tasks and exit when the application ends. This suits elastic batch processing, but the platform must handle Driver permissions, images, dependencies, Shuffle, local disks and history information.

### Three submission and control methods

| Method | API/entry point | Use cases | Notes |
| --- | --- | --- | --- |
| Native `spark-submit` | Spark CLI + Pod | Existing submission platform, want fewer CRDs | Submission status, retries, scheduling and cleanup are filled in by the platform |
| Apache Spark K8s Operator | `spark.apache.org/v1`, `SparkApplication` / `SparkCluster` | Evaluating the current Spark ASF Operator mainline | New project; upgrades and ecosystem integration must be validated against the target version |
| Kubeflow Spark Operator | `sparkoperator.k8s.io/v1beta2`, `SparkApplication` | Existing mature deployment, ready-made integrations such as Kueue | Project is still marked Beta; API is incompatible with the Apache Operator |

Both Operators have a Kind named `SparkApplication`, but `apiVersion`, Spec and controllers differ. Migration cannot just replace the API Group.

Conceptual example of native submission:

```bash
spark-submit \
  --master k8s://https://kubernetes.default.svc \
  --deploy-mode cluster \
  --name corpus-cleaning \
  --conf spark.kubernetes.namespace=data-jobs \
  --conf spark.kubernetes.authenticate.driver.serviceAccountName=spark-runner \
  --conf spark.kubernetes.container.image=registry.example.com/data/spark@sha256:replace \
  local:///opt/jobs/corpus_cleaning.py
```

Production focus:

- The Driver ServiceAccount is granted only the Pod, Service and ConfigMap permissions required within the target Namespace;
- Images pin Spark, Java/Scala/Python, Hadoop Connector, Iceberg and business dependency versions;
- Driver and Executor have separate CPU, memory and Memory Overhead settings;
- Use Pod Templates to express SecurityContext, Volume, Affinity, Toleration and Sidecar;
- Shuffle uses local NVMe, PVC or a validated remote Shuffle solution, with temporary storage requests set;
- Dynamic Allocation may conflict with batch queue admission; it must be clear who decides the Executor upper limit;
- Logs after the Driver ends and the Spark History Event Log must be persisted;
- Establish automated diagnostics for data skew, Fetch Failure, Executor Lost and small file output.

As of this page's review date, Kueue's direct integration with Kubeflow Spark Operator `SparkApplication` is Alpha, disabled by default, and does not support Dynamic Allocation under that integration. Spark can also be integrated via Plain Pod, AppWrapper or other schedulers, but the admission semantics for the Driver and all Executors must be validated in every case.

References: [Spark on Kubernetes](https://spark.apache.org/docs/latest/running-on-kubernetes.html), [Apache Spark Kubernetes Operator](https://github.com/apache/spark-kubernetes-operator), [Kubeflow Spark Operator](https://github.com/kubeflow/spark-operator), [Kueue SparkApplication](https://kueue.sigs.k8s.io/docs/tasks/run/kubeflow/sparkapplications/)

## 6. Flink on Kubernetes

Flink's core difficulty is not starting JobManager and TaskManager, but maintaining stream state over the long term. The Flink Kubernetes Operator manages `FlinkDeployment`, application upgrades, Savepoints, rollbacks and the Job Autoscaler, which is closer to production needs than simply wrapping Flink in a Deployment.

### Application vs Session

| Mode | Characteristics | Recommendation |
| --- | --- | --- |
| Application | One cluster hosts one application, with clear lifecycle and resource isolation | Production default, especially for different teams or different state boundaries |
| Session | Multiple Jobs share a cluster, fast startup, high utilization | Trusted, dependency-compatible small tasks; larger blast radius |

The Operator supports Native and Standalone deployment modes. In Native mode, Flink can request and release TaskManagers directly from Kubernetes; in Standalone mode, an external control plane manages Kubernetes resources, with a more contained permission boundary.

State management must be explicit:

- **Checkpoint** is used for automatic recovery after unplanned failures; its lifecycle is usually managed by Flink;
- **Savepoint** is used for planned upgrades, migration and Job Graph changes, managed by the user or Operator;
- Checkpoint/Savepoint paths must be accessible from all JobManagers/TaskManagers;
- Production typically uses object storage or a reliable distributed file system, not Pod local directories;
- Local state such as RocksDB/ForSt, temporary directories and remote Checkpoints are different layers;
- Before upgrading, validate Serializer, State Schema, Operator UID and target Flink version compatibility.

The Flink Autoscaler computes each Job Vertex's parallelism based on Lag, processing rate and target recovery time. It changes application parallelism; the Node Autoscaler changes node provisioning. Both must share the capacity upper limit and cold start budget.

References: [Flink Native Kubernetes](https://nightlies.apache.org/flink/flink-docs-stable/docs/deployment/resource-providers/native_kubernetes/), [Flink Kubernetes Operator](https://nightlies.apache.org/flink/flink-kubernetes-operator-docs-stable/), [Checkpoints vs. Savepoints](https://nightlies.apache.org/flink/flink-docs-stable/docs/ops/state/checkpoints_vs_savepoints/)

## 7. Kafka and Strimzi

Kafka is a persistent event log, not a replacement for object storage. It is suitable for carrying CDC, logs, feedback events and real-time pipeline buffering; long-term training data should still land in a versionable data lake or Lakehouse.

Strimzi uses Operators to manage Kafka, `KafkaNodePool`, Topic, User, Kafka Connect, MirrorMaker 2 and other resources. Since Kafka 4.0 only supports KRaft, new platforms should plan Controller/Broker roles around KRaft rather than continuing to design new ZooKeeper dependencies.

Production design focus:

- Controller and Broker have different failure semantics and can use separate Node Pools;
- Brokers use persistent volumes or explicitly validated local persistent disks, not `emptyDir`, to store the only log replica;
- Spread replicas across nodes/availability zones, and confirm Rack Awareness is consistent with the storage topology;
- Partition count determines the upper limit of consumption parallelism, and also increases Controller, file handle and recovery overhead;
- Pod rolling upgrades must respect ISR, minimum in-sync replicas and availability thresholds;
- Configure idempotency, retries, batching and backpressure policies for Producers/Consumers;
- Kafka Connect's Offset, Config and Status Topics also need replication and backup policies;
- Use Kafka User, TLS, ACL or OAuth to manage identity; do not replace authorization with network reachability;
- MirrorMaker 2 provides cross-cluster replication, but failover, Offset and dual-write conflicts still need to be designed.

References: [Strimzi Documentation](https://strimzi.io/docs/operators/latest/), [Kafka KRaft](https://kafka.apache.org/documentation/#kraft)

## 8. Trino on Kubernetes

Trino typically runs with one Coordinator and multiple Workers, suitable for interactive or federated SQL against object storage, Iceberg, Hive, relational databases and more. The official Helm Chart is a direct starting point on Kubernetes.

```bash
helm repo add trino https://trinodb.github.io/charts
helm repo update
helm install analytics trino/trino -f values-production.yaml
```

Production focus:

- Pin image versions; do not use `latest`;
- Separate resource specifications for Coordinator and Worker; the Coordinator should avoid taking on data processing;
- The official recommendation favors fewer, larger Pods, and avoids placing multiple Trino Pods on the same physical host causing contention;
- Use Resource Groups, query queues and tenant labels to limit concurrency and memory;
- Interactive Queries and large Batch Queries have different resource profiles, and separate clusters are often worthwhile;
- Large queries need evaluation of Fault-tolerant Execution and an external Exchange Manager;
- Whether each Connector supports read/write, retry and authorization capabilities must be validated individually;
- Coordinator, Catalog configuration and external metadata services must enter the backup and release process.

Trino's Task Retry requires an Exchange Manager, which writes intermediate Exchange data to external locations such as object storage. It improves Worker failure recovery but also significantly increases storage I/O; you cannot just enable the configuration without capacity testing.

Reference: [Trino on Kubernetes](https://trino.io/docs/current/installation/kubernetes.html), [Fault-tolerant Execution](https://trino.io/docs/current/admin/fault-tolerant-execution.html)

## 9. Lakehouse: Object Storage, Table Formats, and Catalog

A Lakehouse has at least four layers:

```text
对象存储：Parquet / ORC / Avro 数据文件
开放表格式：Iceberg / Delta / Hudi 元数据、Snapshot 与事务
Catalog：表名、Namespace、当前 Metadata 指针和访问入口
计算引擎：Spark / Flink / Trino / 其他 Reader 与 Writer
```

The four layers must not be conflated:

- An S3 Bucket existing does not mean table transactions are complete;
- A Catalog being available does not mean the data files in object storage are all readable;
- An Iceberg Snapshot succeeding does not mean data quality has passed;
- A Kubernetes CRD is not a table Catalog, and etcd should not store table metadata files or data files;
- Before multiple engines write to the same table concurrently, verify Catalog locking, isolation levels, and version compatibility.

Open table formats such as Iceberg are especially valuable for AI data: a training Run can bind to an immutable Snapshot ID; Schema and Partition can evolve; data deletion, quality fixes, and rollbacks have clear table-level versioning. However, a Snapshot still references a large number of files, requiring periodic Compaction, Manifest Rewrite, Snapshot Expiration, and Orphan File Cleanup.

Recommended records:

```text
dataset_id
catalog + namespace + table
snapshot_id / branch / tag
schema_id
transform_code_commit
quality_report_id
source_watermark
access_policy_version
```

Reference: [Apache Iceberg](https://iceberg.apache.org/docs/latest/), [Iceberg Spark Configuration](https://iceberg.apache.org/docs/latest/spark-configuration/), [Trino Iceberg Connector](https://trino.io/docs/current/connector/iceberg.html)

## 10. Boundaries Between Orchestration Systems and Operators

An Operator manages the lifecycle of a system or a job object; a Workflow Orchestrator manages cross-system dependencies. A typical flow might be:

```text
等待上游分区
  → 提交 Spark 清洗
  → 运行质量检查
  → 发布 Iceberg Snapshot
  → 生成训练 Dataset Manifest
  → 提交训练
  → 评估并注册模型
```

Responsibility recommendations:

| Layer | Responsible For | Not Responsible For |
| --- | --- | --- |
| Spark/Flink Operator | Creating, upgrading, observing engine jobs | Cross-project business DAGs |
| Airflow/Argo/Flyte | Dependencies, retries, scheduling, Artifact references | Engine-internal Task scheduling |
| Kueue/Volcano/YuniKorn | Quotas, admission, fairness, Pod placement | Table transactions and data quality |
| GitOps | Operator, cluster service, and policy versions | The large number of ephemeral Job instances generated every minute |

Do not let a Workflow Controller poll tens of thousands of Executor Pods; it should observe higher-level objects such as SparkApplication/FlinkDeployment/Job and data publication results.

## 11. Queues, Scheduling, and Resource Isolation

When big data and AI share Kubernetes, distinguish at least:

- **System reserved pool**: Operators, Catalog, monitoring, DNS;
- **Stateful service pool**: Kafka, Flink JobManager, Trino Coordinator;
- **Elastic CPU/memory pool**: Spark/Flink Batch, Compaction, regular ETL;
- **Local NVMe pool**: Large Shuffle, high Spill, cache;
- **GPU pool**: RAPIDS, Embedding, training and inference;
- **Spot/preemptible pool**: Batch jobs that can retry from input or Checkpoint.

Scheduling strategies:

| Scenario | Recommended Approach |
| --- | --- |
| Standalone Spark Job | Kueue admission or Volcano/YuniKorn queue, limit maximum Executors |
| Large fixed-parallelism batch jobs | Group admission, avoid Driver occupying resources while Executors wait indefinitely |
| Dynamic Allocation | Reserve headroom for growth, prevent already-admitted jobs from starving each other |
| Flink long-running streaming jobs | Reserve base capacity, adjust parallelism based on Lag/Backpressure |
| Kafka/Trino resident services | Separate quotas and priorities, do not share availability budget with preemptible batch jobs |
| GPU ETL | Separate Queue/Flavor, establish clear priorities with training and online inference |

Gang Scheduling suits jobs that "cannot start without the full resource set"; Spark Dynamic Allocation emphasizes changing Executor count at runtime. Before combining the two, clarify minimum, initial, and maximum resources; do not let multiple controllers expand unboundedly at the same time.

## 12. Storage, Shuffle, and State

Recommended layering:

```text
权威数据：对象存储 / 保留的 HDFS
表元数据：Catalog + 数据库 + 对象存储 Metadata
流状态：本地 State Backend + 远端 Checkpoint/Savepoint
消息日志：Kafka Broker 持久卷/本地持久盘 + 副本
Shuffle/Spill：本地 NVMe / PVC / 外部 Exchange
历史与日志：对象存储 + History Server / 日志平台
```

### Is HDFS Still Needed

Cases where keeping HDFS is appropriate:

- Large amounts of existing data and a Kerberos/Hadoop ecosystem;
- Workloads heavily dependent on POSIX/HDFS semantics and data locality;
- Local network and disks provide proven cost-effectiveness;
- Migration risk is higher than short-term benefit.

New cloud-native platforms typically prefer object storage + open table formats, allowing compute and storage to scale independently. Object storage is not unlimited bandwidth; control small objects, LIST/HEAD, cross-region traffic, request throttling, and concurrent commits.

### Small File Governance

Small files amplify simultaneously:

- Object storage requests;
- Catalog/Manifest metadata;
- Spark Task count and Driver pressure;
- Trino Split planning;
- The cost of training DataLoader opening files.

Benchmark target file size, write parallelism, Compaction cycles, and downstream read patterns together, rather than endlessly merging afterward.

## 13. Elasticity Is Not Just About Pod Count

| System | Scaling Signal | Primary Constraints |
| --- | --- | --- |
| Spark | Pending Task, Stage, Executor utilization | Driver, Shuffle, queue quota, node startup time |
| Flink | Source Lag, processing rate, Backpressure, target catch-up time | State redistribution, Checkpoint, partition count |
| Kafka | Broker capacity, partition distribution, disk and network | Partition migration cost, ISR, Controller load |
| Trino | Query Queue, Worker CPU/memory, Split | In-flight query Worker changes and cold cache |
| NodePool | Pending Pod, resource requests | Image, storage topology, Spot provisioning, and node warm-up |

Fast scale-up does not mean safe scale-down. Before scaling down, confirm whether Spark Shuffle, Flink State, Kafka Replica, and Trino Query can be migrated or retried.

## 14. Integration with LLM Training

The data pipeline before LLM pretraining and fine-tuning typically includes:

```text
原始语料
  → 格式解析与文本抽取
  → 语言/质量/安全过滤
  → PII 与许可证治理
  → 精确去重与近似去重
  → 文档切分与 Token 统计
  → 数据混合、采样权重和分片
  → 不可变 Dataset Manifest / Lakehouse Snapshot
  → 训练 DataLoader
```

Spark suits large-scale SQL/DataFrame cleaning, Join, deduplication, statistics, and sharding; Ray Data integrates more easily with Python model preprocessing and training pipelines; RAPIDS Accelerator can speed up supported Spark operators. Final selection must be validated with real corpora, compressed formats, and operator plans for CPU time, GPU time, and read/write amplification.

A training Run must bind at least:

- Lakehouse Snapshot or Dataset Manifest;
- Data transformation code Commit and image Digest;
- Filter, Dedup, and Sampling configuration;
- Tokenizer and version;
- Data quality, compliance, and leakage check reports;
- Output shard Digest and total Token count.

GPU nodes should not handle all parsing work that can be cheaply done on the CPU pool. Only when Profiling proves the end-to-end benefit of GPU ETL, and it does not squeeze training/inference SLOs, should the relevant Stages be placed in the GPU queue.

## 15. Integration with RAG, Embedding, and Online Feedback

An incremental RAG pipeline can be:

```text
文档变更 / CDC
  → Kafka
  → Flink 清洗、权限映射和版本判定
  → Chunk 任务
  → Embedding Worker（GPU/CPU）
  → Vector Database Upsert
  → 索引版本发布
```

Must address:

- When events are delivered at-least-once, whether Chunk and vector writes are idempotent;
- How document deletion, permission changes, and re-chunking revoke old vectors;
- How Source Offset, document version, Chunk Hash, Embedding model, and index version are correlated;
- When Embedding Workers slow down, how Kafka Lag drives scale-out and degradation;
- How to reconcile when the vector database update succeeds but the Lakehouse record fails;
- Online retrieval can only access Chunks the user is authorized to view.

Inference logs and user feedback can also flow back to the Lakehouse via Kafka/Flink, then be used for quality analysis, evaluation set construction, and fine-tuning candidates. Raw Prompt/Response may contain sensitive data; design access control, masking, retention periods, and deletion propagation before entering the streaming platform.

## 16. Multi-Tenancy and Security

- Namespace expresses team or environment boundaries, but does not equal complete data isolation;
- Driver/JobManager do not use default high-privilege ServiceAccounts;
- Object storage prefers Workload Identity/short-lived credentials; do not put long-lived Access Keys into images;
- Establish stable mappings between Kafka Topics, Iceberg Namespaces, Bucket Prefixes, and Kubernetes identities;
- Restrict `hostPath`, Host Network, privileged containers, and arbitrary Pod Templates;
- User-submitted JARs, Python packages, and UDFs are untrusted code; use non-root, Seccomp, NetworkPolicy, and controlled images;
- SQL Gateway, Trino, and Kafka APIs all require authentication, authorization, TLS, rate limiting, and auditing;
- Data classification, Row/Column Policy, and deletion requests must propagate to derived tables, training sets, and vector indexes;
- Operator Webhooks and CRD upgrades enter the platform version matrix and change audit.

## 17. Observability and SLOs

| Layer | Key Metrics |
| --- | --- |
| Kubernetes | Pending reason, Pod startup, restart, eviction, CPU/memory/ephemeral storage |
| Spark | Job/Stage/Task time, Shuffle Read/Write, Spill, GC, Executor Lost, Skew |
| Flink | Records/s, Lag, Backpressure, Checkpoint duration/failure, recovery time, State size |
| Kafka | Under-replicated Partition, ISR, Consumer Lag, Produce/Fetch latency, disk watermark |
| Trino | Query Queue, Planning/Execution time, failures, Worker memory, Spill/Exchange |
| Lakehouse | Commit latency/conflicts, file count, average file size, Snapshot count, Compaction Backlog |
| AI data | Document/sample count, Token count, filter rate, dedup rate, Embedding Lag, index freshness |

Recommended unified correlation keys include:

```text
tenant / namespace / workflow_id / job_id
dataset_id / table / snapshot_id
source_offset / partition / watermark
image_digest / code_commit / runtime_version
model_id / tokenizer_id / index_version
```

Do not keep only Pod logs. Spark Event Log, Flink Job/Checkpoint state, Kafka Consumer Group Offset, Trino Query Event, and Lakehouse Commit metadata must all be persisted.

## 18. Failures and Recovery

| Failure | Protection Mechanism | Recovery Path That Must Be Tested |
| --- | --- | --- |
| Spark Executor/Node loss | Task retry, reliable input, Shuffle strategy | Consistent results after Executor rebuild |
| Spark Driver loss | Operator retry, external state, idempotent writes | No duplicate publication of wrong Snapshot |
| Flink TaskManager loss | Checkpoint + State Backend | Recovery within RTO without duplicate side effects |
| Kafka Broker/disk loss | Replica, ISR, Rack Awareness | Replica leader election and data resync |
| Trino Worker loss | Query/Task Retry, Exchange Manager | Partial retry of large queries |
| Catalog database failure | Database HA, backup and recovery | Consistent recovery of table pointers and permissions |
| Object storage unavailable | Retry, rate limiting, region policy | Writes do not produce partial publication |
| Operator upgrade failure | CRD/version backup, Canary | Old objects can still be reconciled or safely rolled back |

Exactly-once is an end-to-end property; it cannot be viewed only through Flink Checkpoint. Source Offset, external Sink transactions, Lakehouse Commit, and vector database writes must all participate in the consistency design.

## 19. Common Anti-Patterns

- Using Kafka as a long-term data lake without tiered storage and retention boundaries;
- Putting all data into one huge RWX PVC;
- Every Spark Executor downloading dependencies from the public internet;
- Driver runs without full quota first, waiting indefinitely for Executors;
- Using HPA to scale Kafka Brokers or Flink TaskManagers arbitrarily by CPU;
- Flink Checkpoint written to Pod local disk;
- Multiple write engines using incompatible versions to modify the same Lakehouse table concurrently;
- Not distinguishing Trino short queries from very large Batch Queries;
- Letting low-priority ETL preempt online inference GPUs for "unified compute";
- Observing only Pod Running, not Lag, Checkpoint, Shuffle, and table Commits;
- Datasets record only paths, not Snapshot, transformation code, and quality results.

## 20. Phased Implementation

### Phase 1: Establish Reliable Batch Processing

- Object storage and immutable data paths;
- Native Spark submission or a selected Operator;
- Event Log, logs, resource requests, and failure classification;
- CPU/memory batch node pools and queues;
- Minimal data quality and Dataset Manifest.

### Phase 2: Establish Lakehouse and SQL

- Choose an open table format and Catalog;
- Write tables with Spark/Flink, query with Trino;
- Establish Compaction, Snapshot, and orphan file governance;
- Integrate Lineage, permissions, and auditing.

### Phase 3: Introduce Real-Time Pipelines

- Strimzi/Kafka, Schema and Topic governance;
- Flink Application + Checkpoint/Savepoint;
- End-to-end idempotency, Lag SLOs, and failure drills;
- CDC, real-time features, or RAG incremental indexing.

### Phase 4: Unified Governance with AI

- Data Snapshot bound to training, evaluation, and model versions;
- CPU/GPU queues, priorities, and cost attribution;
- Training corpus, Embedding, and feedback loops;
- Evaluate Ray Data, GPU ETL, and cross-cluster distribution based on real benefits.

## 21. Go-Live Checklist

- [ ] Clarify the responsibility boundaries for batch, streaming, messaging, SQL, Lakehouse, and AI data processing;
- [ ] Fix the Spark Operator/API selection; do not mix incompatible CRDs;
- [ ] Complete drills for Flink Checkpoint, Savepoint, upgrade, and recovery;
- [ ] Kafka uses KRaft/Node Pool and replica design adapted to the target version;
- [ ] Trino Coordinator, Worker, query queues, and Batch/Interactive boundaries are clear;
- [ ] Object storage, table format, Catalog, and compute engines each have HA and backup;
- [ ] Batch queues, Dynamic Allocation, application Autoscaler, and Node Autoscaler do not conflict with one another;
- [ ] Shuffle, Spill, State, Checkpoint, and small files all have capacity baselines;
- [ ] Data identity, Schema, Snapshot, Lineage, quality, and permissions are traceable;
- [ ] Resident stateful services and preemptible batch jobs use different availability strategies;
- [ ] Monitoring can trace from business data latency to Job, Pod, Node, storage, and network;
- [ ] Training and RAG both bind to immutable data versions and can handle deletion and permission changes;
- [ ] Version upgrades, node failures, object storage throttling, and cross-zone recovery have all completed drills.

## Official Resources

- [Apache Spark on Kubernetes](https://spark.apache.org/docs/latest/running-on-kubernetes.html)
- [Apache Spark Kubernetes Operator](https://github.com/apache/spark-kubernetes-operator)
- [Kubeflow Spark Operator](https://github.com/kubeflow/spark-operator)
- [Apache Flink Native Kubernetes](https://nightlies.apache.org/flink/flink-docs-stable/docs/deployment/resource-providers/native_kubernetes/)
- [Apache Flink Kubernetes Operator](https://nightlies.apache.org/flink/flink-kubernetes-operator-docs-stable/)
- [Strimzi Documentation](https://strimzi.io/docs/operators/latest/)
- [Apache Kafka Documentation](https://kafka.apache.org/documentation/)
- [Trino on Kubernetes](https://trino.io/docs/current/installation/kubernetes.html)
- [Apache Iceberg Documentation](https://iceberg.apache.org/docs/latest/)
- [Kueue Workload Integrations](https://kueue.sigs.k8s.io/docs/tasks/run/)
- [RAPIDS Accelerator for Apache Spark](https://docs.nvidia.com/spark-rapids/user-guide/)
