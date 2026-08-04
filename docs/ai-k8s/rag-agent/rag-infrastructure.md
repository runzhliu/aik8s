---
title: RAG 数据面与向量检索基础设施
description: 在 Kubernetes 上设计文档摄取、Embedding、向量数据库、Reranker、缓存、索引发布和灾备
status: evolving
last_reviewed: 2026-08-02
---

# RAG 数据面与向量检索基础设施

RAG 不是“部署一个向量数据库”。完整数据面包括文档摄取、解析、切分、Embedding、索引、检索、过滤、Rerank、上下文组装、权限和反馈回流。Kubernetes 可以管理这些服务的生命周期，但数据一致性和检索质量需要单独设计。

## 1. 完整数据链路

```text
数据源
  文件、对象存储、数据库、Wiki、事件流
        │
        ▼
摄取与解析
  去重、OCR、结构解析、权限提取、PII 处理
        │
        ▼
Chunk 与 Embedding
  版本化切分规则、Embedding 模型、Batch 推理
        │
        ▼
索引构建
  Vector + Metadata + Keyword/Hybrid Index
        │
        ▼
在线检索
  Query Rewrite → Embed → Filter → Retrieve → Rerank
        │
        ▼
Context Builder → LLM Gateway/Inference
        │
        ▼
引用、反馈、质量评估和数据更新
```

每一步都要带版本和租户权限，才能回答某次生成使用了哪些文档和索引。

## 2. 控制面与数据面

### 控制面

- 数据源注册和权限；
- Pipeline/Job 定义；
- Embedding/Chunk 版本；
- Collection/Index 生命周期；
- 发布、回滚和别名；
- 数据保留、删除和审计；
- 质量评估和变更审批。

### 数据面

- 文档读取和解析；
- Embedding 批推理；
- 向量/关键词写入；
- 在线 Query、Filter、Rerank；
- Context 构建和缓存；
- 实时增量更新。

不要让在线 API 进程同时负责大规模重建索引。离线构建与在线读路径应解耦。

## 3. 数据版本

一次可重现的索引版本至少记录：

```text
Source snapshot / change cursor
Parser version
Chunk strategy and parameters
Embedding model + revision + precision
Vector dimension and distance metric
Metadata schema
Index algorithm and parameters
Reranker model
Security/ACL extraction version
Build job and evidence
```

只记录 Collection 名称无法重现检索结果。

## 4. Chunk 不是纯应用参数

Chunk 大小、重叠和结构会影响：

- 文档覆盖和语义完整性；
- Embedding 计算量；
- 向量数量与存储；
- 检索延迟和召回；
- Rerank 成本；
- 最终 Prompt Token；
- 引用可解释性；
- 数据删除粒度。

每次 Chunk 策略变化通常需要新索引版本，不应原地混写。

## 5. Embedding 服务

Embedding 可以是：

- 在线同步服务；
- Kafka/队列驱动的异步 Worker；
- Kubernetes Job/Spark/Ray 批处理；
- 托管 API；
- GPU、CPU 或专用加速器服务。

平台指标：

- documents/chunks/tokens per second；
- Batch 大小、队列和 GPU 利用率；
- 失败、重试、毒数据和 Dead Letter；
- 模型版本和输出维度；
- 单位文档/Token 成本；
- 增量数据新鲜度。

Embedding 模型或维度变化通常需要重建整个索引，发布前要估算时间和双份容量。

## 6. 向量数据库选型维度

| 维度 | 要回答的问题 |
| --- | --- |
| 数据规模 | 向量数、维度、Metadata、增长和保留 |
| 查询 | Top-K、Filter、Hybrid、范围、Multi-vector |
| 一致性 | 写入后多久可见，读写一致要求 |
| 索引 | HNSW、IVF、DiskANN、量化、构建时间 |
| 扩展 | 分片、复制、重平衡和热点 |
| 存储 | 内存、NVMe、对象存储、共享存储 |
| 租户 | Collection、Partition、Payload Filter、物理隔离 |
| 运维 | Operator、备份、升级、指标和灾备 |
| 成本 | 内存占用、存储、查询 CPU/GPU、写放大 |

不要仅根据单次 ANN Benchmark 选择。Metadata Filter、增量写入、删除、备份和故障恢复往往更决定生产体验。

## 7. 常见实现

### PostgreSQL + pgvector

适合已有 PostgreSQL 运维体系、中小规模、事务 Metadata 和向量在同一数据库的场景。优点是 SQL、权限和备份成熟；超大规模 ANN 或高并发需要仔细验证分区、索引和扩展能力。

### Qdrant

面向向量检索，支持 Shard、Replica、Payload Filter 和分布式部署。自托管时要提前规划 Shard 数、复制、重平衡、快照和 Load Balancer；启用集群模式不会自动让已有数据完成复制。

参考：[Qdrant Distributed Deployment](https://qdrant.tech/documentation/scaling/distributed_deployment/)

### Milvus

面向大规模向量检索，采用计算、存储和协调组件分层架构。适合需要横向扩展和复杂索引的场景，但组件更多，必须评估元数据、消息/WAL、对象存储和各 Worker 的运维成本。

参考：[Milvus Architecture](https://milvus.io/docs/architecture_overview.md)

### OpenSearch/Elasticsearch

适合已有搜索平台并需要 Keyword、Filter、聚合和 Vector Hybrid Search 的团队。要关注 Segment、Merge、Heap、Shard 数和向量索引的内存/磁盘成本。

选择托管服务还是自托管，取决于数据主权、延迟、成本和团队是否真正具备状态数据库运维能力。

## 8. Kubernetes 部署原则

向量数据库是状态系统。最低要求：

- StatefulSet/Operator 管理稳定身份；
- 反亲和或拓扑分散副本；
- 合适的 StorageClass、IOPS 和扩容能力；
- PDB 与真实 Quorum 一致；
- Init/Readiness/Liveness 理解数据库语义；
- 滚动升级和版本偏差有官方支持；
- 快照、逻辑备份和恢复演练；
- 管理、内部复制和客户端端口分离；
- NetworkPolicy、TLS、认证和 Secret；
- 容量、水位和 Compaction 监控。

Kubernetes 重新创建 Pod 不等于数据已经恢复或 Replica 已重新同步。

## 9. 分片与复制

### Shard

用于横向扩展容量和查询吞吐。过少会形成热点，过多会增加 Metadata、连接和 Fan-out。

### Replica

用于可用性和读吞吐。复制因子要结合故障域放置，多个副本落在同一节点没有节点级容灾价值。

### Rebalance

增加节点后，数据是否自动移动取决于产品和部署方式。重平衡会消耗网络、磁盘和 CPU，必须限制速度并观察在线延迟。

### Quorum

PDB、节点维护和副本数必须与数据库一致性协议匹配。错误的 PDB 既可能阻止所有维护，也可能允许同时驱逐过多副本。

## 10. 索引发布模式

推荐 Blue/Green：

```text
生产别名: knowledge-current → index-v41

离线构建 index-v42
  → 完整性验证
  → 检索质量评估
  → 性能和容量验证
  → 小流量 Shadow/Canary
  → 原子切换别名到 index-v42
  → 保留 index-v41 回滚
```

避免在生产 Collection 中原地大规模修改 Chunk、Embedding 或 Index 参数。

## 11. 增量更新

需要处理：

- Upsert 幂等键；
- Source Cursor/Offset；
- 文档删除和权限撤销；
- 重复事件和乱序；
- Embedding 暂时失败；
- 新旧版本双写；
- 数据新鲜度 SLO；
- Poison Document 隔离；
- Schema Evolution。

删除比新增更难：原文被删除后，所有 Chunk、Embedding、Cache、索引副本和备份保留策略都要一致执行。

## 12. Hybrid Search 与 Rerank

常见路径：

```text
Query
  ├── Dense Vector Search
  ├── Sparse/BM25 Search
  └── Metadata/ACL Filter
        → Fusion
        → Reranker
        → Context Selection
```

Reranker 通常比向量相似度更精确，但增加模型推理、延迟和成本。应记录各阶段 Top-K、耗时和被淘汰原因，才能优化质量。

## 13. 权限过滤

RAG 最严重的基础设施风险之一是检索到用户无权读取的文档。

原则：

- ACL 在摄取时进入 Metadata，但查询时仍基于实时身份；
- Filter 必须在检索层生效，不能只在 LLM 输出后过滤；
- 租户 ID 由可信网关注入，不接受客户端任意声明；
- 权限变化和删除有新鲜度 SLO；
- Cache Key 包含租户、权限和索引版本；
- 高隔离租户使用独立 Collection/实例/集群；
- 记录某次回答实际检索的文档 ID 和版本。

## 14. 缓存

| 缓存 | Key | 失效条件 |
| --- | --- | --- |
| 文档解析 | Source Digest + Parser Version | 源文档或解析器变化 |
| Embedding | Text Digest + Model Revision | 文本或模型变化 |
| Query Embedding | Query + Model + Tenant Policy | 模型/策略变化 |
| Retrieval Result | Query + Filter + Index Version | 索引/权限变化 |
| Rerank | Candidates + Reranker Revision | 候选/模型变化 |
| LLM Response | 完整上下文与生成配置 | 任一输入或策略变化 |

权限敏感缓存必须防止跨租户命中。

## 15. 备份与灾备

需要分别备份：

- 原始/规范化文档；
- Source Cursor 和 Pipeline 状态；
- Collection Schema 和 Index 参数；
- 向量数据与 Metadata；
- 数据库快照/WAL；
- Embedding/Chunk/Parser 版本；
- 权限映射；
- 发布别名。

如果能够从权威文档重建索引，也要测量重建时间是否满足 RTO。数十亿向量重建可能远超数据库快照恢复时间。

## 16. 可观测性

### 离线

- 摄取延迟、吞吐、失败和重试；
- 解析、Chunk、Embedding 各阶段耗时；
- Source 到 Index 的数据新鲜度；
- 索引构建时间和资源；
- 删除/权限更新积压；
- 每版本数据量和成本。

### 在线

- Query、Filter、ANN、Rerank 各阶段延迟；
- Recall/Precision/nDCG/MRR 或任务质量；
- Top-K、命中、空结果和降级；
- Shard/Replica/节点热点；
- Cache 命中；
- 最终 Context Token 和引用正确率；
- 每租户 QPS、数据量和成本。

## 17. 故障与降级

| 故障 | 可选降级 |
| --- | --- |
| Vector DB 不可用 | 明确失败或切只读副本，不凭空生成 |
| Reranker 超时 | 返回未 Rerank 的受控 Top-K |
| Embedding 服务故障 | 队列积压，保持旧索引 |
| 新索引质量失败 | 保持生产别名不切换 |
| 单 Shard 热点 | 限流、扩副本、重新分片 |
| 权限服务不可用 | Fail Closed，不返回可能越权文档 |
| Source 延迟 | 暴露数据新鲜度而非静默 |
| LLM 服务故障 | 检索结果仍需保护，不写入普通错误日志 |

## 18. 生产检查清单

- [ ] Source、Parser、Chunk、Embedding、Index 和 Reranker 全部版本化。
- [ ] 离线索引构建与在线查询解耦。
- [ ] 向量数据库按状态系统设计，而不是普通 Deployment。
- [ ] Shard、Replica、Quorum、PDB 和故障域相互一致。
- [ ] 新索引通过 Blue/Green 别名发布并可回滚。
- [ ] 增量更新支持幂等、删除、乱序和 Poison Data。
- [ ] ACL 在检索前执行，Cache 不会跨租户泄漏。
- [ ] 备份恢复和从源重建的实际 RTO 已测量。
- [ ] Trace 能分解 Embed、Retrieve、Rerank 和 LLM。
- [ ] 检索质量、新鲜度、延迟和成本都有 SLO。

## 延伸阅读

- [Qdrant Distributed Deployment](https://qdrant.tech/documentation/scaling/distributed_deployment/)
- [Qdrant Production Checklist](https://qdrant.tech/documentation/production-checklist/)
- [Milvus Architecture](https://milvus.io/docs/architecture_overview.md)
- [OpenSearch Vector Search](https://docs.opensearch.org/latest/vector-search/)
- [Kubernetes StatefulSets](https://kubernetes.io/docs/concepts/workloads/controllers/statefulset/)
- [Kubernetes Volume Snapshots](https://kubernetes.io/docs/concepts/storage/volume-snapshots/)
