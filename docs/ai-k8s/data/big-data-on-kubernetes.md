---
title: 大数据 on Kubernetes
description: Spark、Flink、Kafka、Trino、Lakehouse、对象存储、Operator、队列调度，以及与大模型训练和 RAG 的结合
status: evolving
last_reviewed: 2026-08-04
---

# 大数据 on Kubernetes

大模型并没有让大数据平台消失，反而扩大了它的责任：训练语料清洗、去重和质量过滤，RAG 文档解析与增量更新，Embedding 批量生成，在线反馈回流，以及模型评估数据构建，都需要稳定的数据工程链路。

Kubernetes 能统一容器、资源、身份、发布和观测，但不会自动提供分布式 SQL、流状态、消息持久化或 Lakehouse 事务。建设“大数据 on Kubernetes”时，必须把 Kubernetes 控制面、计算引擎、数据系统和 AI 工作负载分开建模。

## 1. 从 Hadoop 集群到云原生数据平台

大数据平台大致经历了三条主线：

1. **存储与计算绑定**：HDFS 保存数据，YARN 管理 MapReduce、Spark 等计算资源，节点扩容往往同时增加存储和计算。
2. **计算容器化**：Spark、Flink、Kafka、Trino 等逐步具备 Kubernetes 部署方式，Operator 开始管理有状态升级和作业生命周期。
3. **存储与计算分离**：对象存储成为权威数据层，Parquet/ORC 等列式文件保存数据，Iceberg/Delta/Hudi 等开放表格式管理表快照与事务，不同计算引擎按需读取同一份数据。

当前主流方向不是“用 Kubernetes 重写 Hadoop”，而是：

- Kubernetes 管理计算、服务生命周期、资源和安全边界；
- 对象存储或保留的 HDFS 管理持久字节；
- Lakehouse Catalog 和开放表格式管理表、Snapshot 与事务；
- Spark/Flink 负责批处理与流处理；
- Kafka 负责事件日志和流量缓冲；
- Trino 等引擎提供交互式 SQL；
- Airflow、Argo Workflows、Flyte 等编排跨系统依赖；
- AI 平台消费经过版本化和质量门禁的数据。

Kubernetes 不是数据语义层。Pod 重启成功，不代表 Flink 状态可以恢复；Spark Job 完成，也不代表 Iceberg Snapshot 已通过质量审计。

## 2. 先按工作负载分类

| 工作负载 | 典型系统 | 生命周期 | 首要目标 |
| --- | --- | --- | --- |
| 离线 ETL/ELT | Spark、Flink Batch、Ray Data | 分钟到小时，用完释放 | 吞吐、成本、可重试、数据质量 |
| 实时流处理 | Flink、Kafka Streams、Spark Structured Streaming | 长期运行 | Lag、Backpressure、状态一致性、恢复时间 |
| 消息与事件日志 | Kafka | 长期有状态 | 持久性、分区可用性、复制和端到端延迟 |
| 交互式 SQL | Trino | 长期服务 + 短查询 | 并发、排队、查询延迟和资源隔离 |
| Lakehouse 维护 | Spark、Flink、Trino | 周期作业 | Compaction、Snapshot、孤儿文件和小文件治理 |
| AI 数据准备 | Spark、Ray、GPU ETL、自定义 Job | 批量或增量 | 样本质量、可追溯、吞吐和成本 |
| RAG 索引更新 | Kafka/Flink + Embedding Worker | 持续或微批 | 新鲜度、幂等、权限和索引一致性 |

不要让一种弹性策略同时控制所有负载。Spark Executor 可以随 Job 消失，Kafka Broker 和 Flink 有状态 Job 却不能按照普通无状态 Deployment 随意缩容。

## 3. 一套分层参考架构

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

控制面通常包括：

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

数据面和控制面要分别做高可用。Operator 正常并不能替代 Kafka 副本、Flink Checkpoint 或 Catalog 数据库备份。

## 4. 主要组件怎么选

| 组件 | 核心定位 | 适合 | 主要代价 |
| --- | --- | --- | --- |
| Spark | 通用批处理、SQL、微批流、ML 数据准备 | 大规模 ETL、表维护、训练语料处理 | Shuffle、Driver 稳定性、启动和小文件治理 |
| Flink | 有状态流处理与流批作业 | CDC、实时聚合、事件时间、低延迟增量管道 | Checkpoint、状态 Backend、升级兼容复杂 |
| Kafka | 持久事件日志与解耦 | 事件总线、CDC、日志、流量缓冲 | Broker 存储、分区规划、跨区流量和长期运维 |
| Trino | 分布式交互 SQL | 联邦查询、Lakehouse BI、数据探索 | 内存、Coordinator、并发治理和 Connector 差异 |
| Iceberg/Delta/Hudi | 开放表格式 | Snapshot、Schema/Partition Evolution、并发读写 | 仍需 Catalog、对象存储和维护作业 |
| Ray Data | Python/AI 数据处理 | 数据准备与训练共享 Python/Ray 生态 | 不应因为训练用 Ray 就替代所有 SQL/流平台 |
| RAPIDS Accelerator for Spark | 让受支持的 Spark SQL/DataFrame 算子使用 NVIDIA GPU | 已证明 GPU 加速收益的 ETL | 算子覆盖、数据传输、GPU 成本和版本矩阵 |

选型先看数据语义和 SLO，不要先问“哪个项目最云原生”。

## 5. Spark on Kubernetes

Spark 原生 Kubernetes 模式中，Driver Pod 向 Kubernetes API 创建 Executor Pod，Executor 运行任务并在应用结束后退出。它适合弹性批处理，但平台必须处理 Driver 权限、镜像、依赖、Shuffle、本地盘和历史信息。

### 三种提交与控制方式

| 方式 | API/入口 | 适用场景 | 注意事项 |
| --- | --- | --- | --- |
| 原生 `spark-submit` | Spark CLI + Pod | 已有提交平台、希望少装 CRD | 提交状态、重试、定时和清理由平台补齐 |
| Apache Spark K8s Operator | `spark.apache.org/v1`，`SparkApplication` / `SparkCluster` | 评估 Spark ASF 当前 Operator 主线 | 新项目，升级和生态集成要按目标版本验证 |
| Kubeflow Spark Operator | `sparkoperator.k8s.io/v1beta2`，`SparkApplication` | 已有成熟部署、Kueue 等现成集成 | 项目仍标注 Beta；API 与 Apache Operator 不兼容 |

两个 Operator 都有名为 `SparkApplication` 的 Kind，但 `apiVersion`、Spec 和控制器不同。迁移不能只替换 API Group。

原生提交的概念示例：

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

生产重点：

- Driver ServiceAccount 只授予目标 Namespace 内必需的 Pod、Service 和 ConfigMap 权限；
- 镜像固定 Spark、Java/Scala/Python、Hadoop Connector、Iceberg 和业务依赖版本；
- Driver 与 Executor 分别设置 CPU、内存和 Memory Overhead；
- 使用 Pod Template 表达 SecurityContext、Volume、Affinity、Toleration 和 Sidecar；
- Shuffle 使用本地 NVMe、PVC 或经过验证的远端 Shuffle 方案，并设置临时存储请求；
- Dynamic Allocation 与批队列准入可能冲突，必须明确谁决定 Executor 上限；
- Driver 结束后的日志和 Spark History Event Log 要持久化；
- 对数据倾斜、Fetch Failure、Executor Lost 和小文件输出建立自动诊断。

截至本页复核日期，Kueue 对 Kubeflow Spark Operator `SparkApplication` 的直接集成为 Alpha、默认关闭，并且不支持该集成下的 Dynamic Allocation。也可以通过 Plain Pod、AppWrapper 或其他调度器集成 Spark，但都要验证 Driver 与全部 Executor 的准入语义。

参考：[Spark on Kubernetes](https://spark.apache.org/docs/latest/running-on-kubernetes.html)、[Apache Spark Kubernetes Operator](https://github.com/apache/spark-kubernetes-operator)、[Kubeflow Spark Operator](https://github.com/kubeflow/spark-operator)、[Kueue SparkApplication](https://kueue.sigs.k8s.io/docs/tasks/run/kubeflow/sparkapplications/)

## 6. Flink on Kubernetes

Flink 的核心难点不是启动 JobManager 和 TaskManager，而是长期维护流状态。Flink Kubernetes Operator 管理 `FlinkDeployment`、应用升级、Savepoint、回滚和 Job Autoscaler，比单纯用 Deployment 包装 Flink 更接近生产需求。

### Application 与 Session

| 模式 | 特点 | 建议 |
| --- | --- | --- |
| Application | 一个集群承载一个应用，生命周期和资源隔离清晰 | 生产默认，尤其是不同团队或不同状态边界 |
| Session | 多个 Job 共享集群，启动快、利用率高 | 受信任、依赖兼容的小任务；爆炸半径更大 |

Operator 支持 Native 和 Standalone 部署模式。Native 模式下 Flink 可直接向 Kubernetes 申请和释放 TaskManager；Standalone 模式由外部控制面管理 Kubernetes 资源，权限边界更收敛。

状态管理必须明确：

- **Checkpoint** 用于非计划故障后的自动恢复，生命周期通常由 Flink 管理；
- **Savepoint** 用于计划升级、迁移和 Job Graph 变更，由用户或 Operator 管理；
- Checkpoint/Savepoint 路径必须从所有 JobManager/TaskManager 可访问；
- 生产通常使用对象存储或可靠分布式文件系统，而不是 Pod 本地目录；
- RocksDB/ForSt 等本地状态、临时目录和远端 Checkpoint 是不同层；
- 升级前验证 Serializer、State Schema、Operator UID 和目标 Flink 版本兼容性。

Flink Autoscaler 依据 Lag、处理速率和目标恢复时间计算各 Job Vertex 的并行度。它改变的是应用并行度；Node Autoscaler 改变的是节点供给，两者要共享容量上限和冷启动预算。

参考：[Flink Native Kubernetes](https://nightlies.apache.org/flink/flink-docs-stable/docs/deployment/resource-providers/native_kubernetes/)、[Flink Kubernetes Operator](https://nightlies.apache.org/flink/flink-kubernetes-operator-docs-stable/)、[Checkpoints vs. Savepoints](https://nightlies.apache.org/flink/flink-docs-stable/docs/ops/state/checkpoints_vs_savepoints/)

## 7. Kafka 与 Strimzi

Kafka 是持久事件日志，不是对象存储的替代品。它适合承载 CDC、日志、反馈事件和实时管道缓冲；长期训练数据仍应落到可版本化的数据湖或 Lakehouse。

Strimzi 使用 Operator 管理 Kafka、`KafkaNodePool`、Topic、User、Kafka Connect、MirrorMaker 2 等资源。Kafka 4.0 起只支持 KRaft，因此新平台应围绕 KRaft 规划 Controller/Broker 角色，而不是继续设计新的 ZooKeeper 依赖。

生产设计重点：

- Controller 与 Broker 是不同故障语义，可使用独立 Node Pool；
- Broker 使用持久卷或明确验证过的本地持久盘，不用 `emptyDir` 保存唯一日志副本；
- 跨节点/可用区分散副本，确认 Rack Awareness 与存储拓扑一致；
- 分区数决定消费并行上限，也会增加 Controller、文件句柄和恢复开销；
- Pod 滚动升级要服从 ISR、最小同步副本和可用性门槛；
- 为 Producer/Consumer 配置幂等、重试、批量和背压策略；
- Kafka Connect 的 Offset、Config、Status Topic 同样需要复制和备份策略；
- 使用 Kafka User、TLS、ACL 或 OAuth 管理身份，不以网络可达代替授权；
- MirrorMaker 2 提供跨集群复制，但故障切换、Offset 和双写冲突仍要设计。

参考：[Strimzi Documentation](https://strimzi.io/docs/operators/latest/)、[Kafka KRaft](https://kafka.apache.org/documentation/#kraft)

## 8. Trino on Kubernetes

Trino 通常以一个 Coordinator 和多个 Worker 运行，适合对对象存储、Iceberg、Hive、关系数据库等执行交互式或联邦 SQL。官方 Helm Chart 是 Kubernetes 上的直接起点。

```bash
helm repo add trino https://trinodb.github.io/charts
helm repo update
helm install analytics trino/trino -f values-production.yaml
```

生产重点：

- 固定镜像版本，不使用 `latest`；
- Coordinator 和 Worker 分离资源规格，Coordinator 避免承担数据处理；
- 官方建议倾向较少、较大的 Pod，并避免同一物理主机放置多个 Trino Pod 造成争用；
- 使用 Resource Group、查询队列和租户标签限制并发与内存；
- Interactive Query 与大型 Batch Query 的资源画像不同，常值得使用独立集群；
- 大查询需要评估 Fault-tolerant Execution 和外部 Exchange Manager；
- Connector 是否支持读写、重试和授权能力必须逐个验证；
- Coordinator、Catalog 配置和外部元数据服务进入备份与发布流程。

Trino 的 Task Retry 需要 Exchange Manager，把中间 Exchange 数据写入对象存储等外部位置。它提高 Worker 故障恢复能力，也会显著增加存储 I/O，不能只打开配置而不做容量测试。

参考：[Trino on Kubernetes](https://trino.io/docs/current/installation/kubernetes.html)、[Fault-tolerant Execution](https://trino.io/docs/current/admin/fault-tolerant-execution.html)

## 9. Lakehouse：对象存储、表格式和 Catalog

一个 Lakehouse 至少有四层：

```text
对象存储：Parquet / ORC / Avro 数据文件
开放表格式：Iceberg / Delta / Hudi 元数据、Snapshot 与事务
Catalog：表名、Namespace、当前 Metadata 指针和访问入口
计算引擎：Spark / Flink / Trino / 其他 Reader 与 Writer
```

四层不能混为一谈：

- S3 Bucket 存在不表示表事务完整；
- Catalog 可用不表示对象存储中的数据文件都可读；
- Iceberg Snapshot 成功不表示数据质量已经通过；
- Kubernetes CRD 不是表 Catalog，etcd 也不应存放表元数据文件和数据文件；
- 不同引擎同时写同一张表前，要验证 Catalog 锁、隔离级别和版本兼容。

Iceberg 等开放表格式对 AI 数据尤其有价值：训练 Run 可以绑定不可变 Snapshot ID；Schema 和 Partition 可以演进；数据删除、质量修复和回滚有清晰的表级版本。但 Snapshot 仍会引用大量文件，需要定期执行 Compaction、Manifest Rewrite、Snapshot Expiration 和 Orphan File Cleanup。

推荐记录：

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

参考：[Apache Iceberg](https://iceberg.apache.org/docs/latest/)、[Iceberg Spark Configuration](https://iceberg.apache.org/docs/latest/spark-configuration/)、[Trino Iceberg Connector](https://trino.io/docs/current/connector/iceberg.html)

## 10. 编排系统与 Operator 的边界

Operator 管理一个系统或一个作业对象的生命周期；Workflow Orchestrator 管理跨系统依赖。典型流程可能是：

```text
等待上游分区
  → 提交 Spark 清洗
  → 运行质量检查
  → 发布 Iceberg Snapshot
  → 生成训练 Dataset Manifest
  → 提交训练
  → 评估并注册模型
```

职责建议：

| 层 | 负责 | 不负责 |
| --- | --- | --- |
| Spark/Flink Operator | 创建、升级、观察引擎作业 | 跨项目业务 DAG |
| Airflow/Argo/Flyte | 依赖、重试、定时、Artifact 引用 | 引擎内部 Task 调度 |
| Kueue/Volcano/YuniKorn | 配额、准入、公平、Pod 放置 | 表事务与数据质量 |
| GitOps | Operator、集群服务和策略版本 | 每分钟产生的大量临时 Job 实例 |

不要让 Workflow Controller 轮询几万个 Executor Pod；它应观察 SparkApplication/FlinkDeployment/Job 等上层对象和数据发布结果。

## 11. 队列、调度与资源隔离

大数据与 AI 共享 Kubernetes 时，至少区分：

- **系统保留池**：Operator、Catalog、监控、DNS；
- **状态服务池**：Kafka、Flink JobManager、Trino Coordinator；
- **弹性 CPU/内存池**：Spark/Flink Batch、Compaction、普通 ETL；
- **本地 NVMe 池**：大 Shuffle、高 Spill、缓存；
- **GPU 池**：RAPIDS、Embedding、训练和推理；
- **Spot/抢占池**：可从输入或 Checkpoint 重试的批任务。

调度策略：

| 场景 | 推荐思路 |
| --- | --- |
| 独立 Spark Job | Kueue 准入或 Volcano/YuniKorn 队列，限制最大 Executor |
| 大型固定并行批作业 | 成组准入，避免 Driver 占住而 Executor 永久等资源 |
| Dynamic Allocation | 预留增长空间，防止已准入作业相互饿死 |
| Flink 长期流任务 | 保留基础容量，按 Lag/Backpressure 调整并行度 |
| Kafka/Trino 常驻服务 | 独立配额与优先级，不与可抢占批任务共用可用性预算 |
| GPU ETL | 单独 Queue/Flavor，与训练和在线推理建立明确优先级 |

Gang Scheduling 适合“拿不到完整资源就不能开始”的作业；Spark Dynamic Allocation 强调运行中改变 Executor 数。两者组合前要明确最小、初始和最大资源，不能同时让多个控制器无限扩张。

## 12. 存储、Shuffle 与状态

推荐分层：

```text
权威数据：对象存储 / 保留的 HDFS
表元数据：Catalog + 数据库 + 对象存储 Metadata
流状态：本地 State Backend + 远端 Checkpoint/Savepoint
消息日志：Kafka Broker 持久卷/本地持久盘 + 副本
Shuffle/Spill：本地 NVMe / PVC / 外部 Exchange
历史与日志：对象存储 + History Server / 日志平台
```

### HDFS 是否还需要

适合保留 HDFS 的情况：

- 已有大量数据与 Kerberos/Hadoop 生态；
- 工作负载高度依赖 POSIX/HDFS 语义和数据局部性；
- 本地网络和磁盘提供了经过证明的性价比；
- 迁移风险高于短期收益。

新建云原生平台通常优先对象存储 + 开放表格式，让计算和存储独立扩缩。对象存储不是无限带宽，需要控制小对象、LIST/HEAD、跨区流量、请求限流和并发提交。

### 小文件治理

小文件会同时放大：

- 对象存储请求；
- Catalog/Manifest 元数据；
- Spark Task 数和 Driver 压力；
- Trino Split 规划；
- 训练 DataLoader 打开文件的成本。

需要把目标文件大小、写入并行度、Compaction 周期和下游读取模式一起基准，而不是事后无限合并。

## 13. 弹性不能只看 Pod 数

| 系统 | 扩缩信号 | 主要约束 |
| --- | --- | --- |
| Spark | Pending Task、Stage、Executor 利用率 | Driver、Shuffle、队列配额、节点启动时间 |
| Flink | Source Lag、处理速率、Backpressure、目标追赶时间 | State 重分布、Checkpoint、分区数 |
| Kafka | Broker 容量、分区分布、磁盘和网络 | 分区迁移成本、ISR、Controller 负载 |
| Trino | Query Queue、Worker CPU/内存、Split | 查询进行中的 Worker 变化和冷缓存 |
| NodePool | Pending Pod、资源请求 | 镜像、存储拓扑、Spot 供给和节点预热 |

扩容快不代表缩容安全。缩容前要确认 Spark Shuffle、Flink State、Kafka Replica 和 Trino Query 是否能够迁移或重试。

## 14. 与大模型训练结合

大模型预训练和微调前的数据链路通常包括：

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

Spark 适合大规模 SQL/DataFrame 清洗、Join、去重、统计和分片；Ray Data 更容易与 Python 模型预处理和训练流水线结合；RAPIDS Accelerator 可以加速受支持的 Spark 算子。最终选型必须用真实语料、压缩格式和算子计划验证 CPU 时间、GPU 时间和读写放大。

训练 Run 至少绑定：

- Lakehouse Snapshot 或 Dataset Manifest；
- 数据转换代码 Commit 与镜像 Digest；
- Filter、Dedup 和 Sampling 配置；
- Tokenizer 与版本；
- 数据质量、合规与泄漏检查报告；
- 输出分片 Digest 和总 Token 数。

GPU 节点不应承担可以廉价在 CPU 池完成的全部解析工作。只有 Profiling 证明 GPU ETL 的端到端收益，并且不会挤压训练/推理 SLO 时，才把相关 Stage 放入 GPU 队列。

## 15. 与 RAG、Embedding 和在线反馈结合

一条增量 RAG 链路可以是：

```text
文档变更 / CDC
  → Kafka
  → Flink 清洗、权限映射和版本判定
  → Chunk 任务
  → Embedding Worker（GPU/CPU）
  → Vector Database Upsert
  → 索引版本发布
```

必须解决：

- 事件至少一次投递时，Chunk 与向量写入是否幂等；
- 文档删除、权限变化和重新切分如何撤销旧向量；
- Source Offset、文档版本、Chunk Hash、Embedding 模型和索引版本如何关联；
- Embedding Worker 变慢时，Kafka Lag 如何驱动扩容和降级；
- 向量数据库更新成功但 Lakehouse 记录失败时如何对账；
- 在线检索只能访问用户有权查看的 Chunk。

推理日志和用户反馈也可以通过 Kafka/Flink 回流到 Lakehouse，再用于质量分析、评估集构建和微调候选。原始 Prompt/Response 可能包含敏感数据，进入流平台前就要做访问控制、脱敏、保留期限和删除传播设计。

## 16. 多租户与安全

- Namespace 表达团队或环境边界，但不等于完整数据隔离；
- Driver/JobManager 不使用默认高权限 ServiceAccount；
- 对象存储优先使用 Workload Identity/短期凭据，不把长期 Access Key 放进镜像；
- Kafka Topic、Iceberg Namespace、Bucket Prefix 与 Kubernetes 身份建立稳定映射；
- 限制 `hostPath`、Host Network、特权容器和任意 Pod Template；
- 用户提交的 JAR、Python 包和 UDF 属于不可信代码，使用非 root、Seccomp、NetworkPolicy 和受控镜像；
- SQL Gateway、Trino 和 Kafka API 都要认证、授权、TLS、限流和审计；
- 数据分类、Row/Column Policy 和删除请求必须传播到派生表、训练集和向量索引；
- Operator Webhook 与 CRD 升级进入平台版本矩阵和变更审计。

## 17. 可观测性与 SLO

| 层 | 关键指标 |
| --- | --- |
| Kubernetes | Pending 原因、Pod 启动、重启、驱逐、CPU/内存/临时存储 |
| Spark | Job/Stage/Task 时间、Shuffle Read/Write、Spill、GC、Executor Lost、Skew |
| Flink | Records/s、Lag、Backpressure、Checkpoint 时长/失败、恢复时间、State 大小 |
| Kafka | Under-replicated Partition、ISR、Consumer Lag、Produce/Fetch 延迟、磁盘水位 |
| Trino | Query Queue、Planning/Execution 时间、失败、Worker 内存、Spill/Exchange |
| Lakehouse | Commit 延迟/冲突、文件数、平均文件大小、Snapshot 数、Compaction Backlog |
| AI 数据 | 文档/样本数、Token 数、过滤率、去重率、Embedding Lag、索引新鲜度 |

统一关联键建议包括：

```text
tenant / namespace / workflow_id / job_id
dataset_id / table / snapshot_id
source_offset / partition / watermark
image_digest / code_commit / runtime_version
model_id / tokenizer_id / index_version
```

不要只保留 Pod 日志。Spark Event Log、Flink Job/Checkpoint 状态、Kafka Consumer Group Offset、Trino Query Event 和 Lakehouse Commit 元数据都要持久化。

## 18. 故障与恢复

| 故障 | 保护机制 | 必测恢复路径 |
| --- | --- | --- |
| Spark Executor/Node 丢失 | Task 重试、可靠输入、Shuffle 策略 | Executor 重建后结果一致 |
| Spark Driver 丢失 | Operator 重试、外部状态、幂等写入 | 不重复发布错误 Snapshot |
| Flink TaskManager 丢失 | Checkpoint + State Backend | 在 RTO 内恢复且不重复副作用 |
| Kafka Broker/磁盘丢失 | Replica、ISR、Rack Awareness | 副本选主和数据重同步 |
| Trino Worker 丢失 | Query/Task Retry、Exchange Manager | 大查询局部重试 |
| Catalog 数据库故障 | 数据库 HA、备份与恢复 | 表指针和权限一致恢复 |
| 对象存储不可用 | 重试、限流、区域策略 | 写入不产生部分发布 |
| Operator 升级失败 | CRD/版本备份、Canary | 旧对象仍可协调或安全回滚 |

Exactly-once 是端到端属性，不能只看 Flink Checkpoint。Source Offset、外部 Sink 事务、Lakehouse Commit 和向量数据库写入都必须参与一致性设计。

## 19. 常见反模式

- 把 Kafka 当长期数据湖，不设置分层落盘和保留边界；
- 把所有数据放进一个巨大 RWX PVC；
- 每个 Spark Executor 从公网下载依赖；
- Driver 没获完整配额就先运行，长期等待 Executor；
- 用 HPA 按 CPU 随意缩放 Kafka Broker 或 Flink TaskManager；
- Flink Checkpoint 写到 Pod 本地盘；
- 多个写入引擎使用不兼容版本同时修改同一张 Lakehouse 表；
- 不区分 Trino 短查询和超大 Batch Query；
- 为了“统一算力”让低优先级 ETL 抢占在线推理 GPU；
- 只观察 Pod Running，不观察 Lag、Checkpoint、Shuffle 和表 Commit；
- 数据集只记录路径，不记录 Snapshot、转换代码和质量结果。

## 20. 分阶段落地

### 阶段 1：建立可靠批处理

- 对象存储与不可变数据路径；
- Spark 原生提交或选定一个 Operator；
- Event Log、日志、资源请求和失败分类；
- CPU/内存批处理节点池与队列；
- 最小数据质量和 Dataset Manifest。

### 阶段 2：建立 Lakehouse 与 SQL

- 选择开放表格式和 Catalog；
- 用 Spark/Flink 写表、Trino 查询；
- 建立 Compaction、Snapshot 和孤儿文件治理；
- 接入 Lineage、权限和审计。

### 阶段 3：引入实时链路

- Strimzi/Kafka、Schema 与 Topic 治理；
- Flink Application + Checkpoint/Savepoint；
- 端到端幂等、Lag SLO 和故障演练；
- CDC、实时特征或 RAG 增量索引。

### 阶段 4：与 AI 统一治理

- 数据 Snapshot 绑定训练、评估和模型版本；
- CPU/GPU 队列、优先级和成本归属；
- 训练语料、Embedding 和反馈闭环；
- 按真实收益评估 Ray Data、GPU ETL 和跨集群分发。

## 21. 上线检查清单

- [ ] 明确批、流、消息、SQL、Lakehouse 和 AI 数据处理的职责边界；
- [ ] Spark Operator/API 选型固定，不混用不兼容 CRD；
- [ ] Flink Checkpoint、Savepoint、升级和恢复完成演练；
- [ ] Kafka 使用适配目标版本的 KRaft/Node Pool 和副本设计；
- [ ] Trino Coordinator、Worker、查询队列和 Batch/Interactive 边界清楚；
- [ ] 对象存储、表格式、Catalog 和计算引擎分别做 HA 与备份；
- [ ] 批队列、Dynamic Allocation、应用 Autoscaler 和 Node Autoscaler 不互相打架；
- [ ] Shuffle、Spill、State、Checkpoint 和小文件都有容量基准；
- [ ] 数据身份、Schema、Snapshot、Lineage、质量和权限可追溯；
- [ ] 常驻状态服务与可抢占批作业使用不同可用性策略；
- [ ] 监控能从业务数据延迟追到 Job、Pod、Node、存储和网络；
- [ ] 训练和 RAG 均绑定不可变数据版本，并能处理删除与权限变化；
- [ ] 版本升级、节点故障、对象存储限流和跨区恢复都完成演练。

## 官方资料

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
