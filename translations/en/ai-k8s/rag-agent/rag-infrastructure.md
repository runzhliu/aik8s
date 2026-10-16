---
title: "RAG Data Plane and Vector Search Infrastructure"
description: "Designing document ingestion, Embedding, vector databases, Reranker, caching, index publishing, and disaster recovery on Kubernetes"
status: evolving
last_reviewed: 2026-08-02
---

# RAG Data Plane and Vector Search Infrastructure

RAG is not "deploy a vector database." The complete data plane includes document ingestion, parsing, chunking, Embedding, indexing, retrieval, filtering, Rerank, context assembly, permissions, and feedback loops. Kubernetes can manage the lifecycle of these services, but data consistency and retrieval quality require separate design.

## 1. Complete Data Pipeline

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

Every step must carry version and tenant permissions so that you can determine which documents and indexes were used for a given generation.

## 2. Control Plane and Data Plane

### Control Plane

- Data source registration and permissions;
- Pipeline/Job definitions;
- Embedding/Chunk versions;
- Collection/Index lifecycle;
- Publishing, rollback, and aliases;
- Data retention, deletion, and audit;
- Quality evaluation and change approval.

### Data Plane

- Document reading and parsing;
- Embedding batch inference;
- Vector/keyword writes;
- Online Query, Filter, Rerank;
- Context construction and caching;
- Real-time incremental updates.

Do not let the online API process also handle large-scale index rebuilds. Offline construction and the online read path should be decoupled.

## 3. Data Versioning

A reproducible index version records at minimum:

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

Recording only the Collection name cannot reproduce retrieval results.

## 4. Chunking Is Not a Pure Application Parameter

Chunk size, overlap, and structure affect:

- Document coverage and semantic completeness;
- Embedding compute cost;
- Vector count and storage;
- Retrieval latency and recall;
- Rerank cost;
- Final Prompt tokens;
- Citation explainability;
- Data deletion granularity.

Every chunking strategy change typically requires a new index version; do not mix writes in place.

## 5. Embedding Service

Embedding can be:

- An online synchronous service;
- A Kafka/queue-driven asynchronous worker;
- A Kubernetes Job/Spark/Ray batch process;
- A managed API;
- A GPU, CPU, or dedicated accelerator service.

Platform metrics:

- documents/chunks/tokens per second;
- Batch size, queue, and GPU utilization;
- Failures, retries, poison data, and Dead Letter;
- Model version and output dimensions;
- Cost per document/token;
- Incremental data freshness.

Embedding model or dimension changes typically require rebuilding the entire index; estimate time and double capacity before publishing.

## 6. Vector Database Selection Dimensions

| Dimension | Questions to Answer |
| --- | --- |
| Data scale | Vector count, dimensions, metadata, growth, and retention |
| Query | Top-K, Filter, Hybrid, range, multi-vector |
| Consistency | How soon after write is data visible; read/write consistency requirements |
| Index | HNSW, IVF, DiskANN, quantization, build time |
| Scaling | Sharding, replication, rebalancing, and hotspots |
| Storage | Memory, NVMe, object storage, shared storage |
| Tenancy | Collection, Partition, Payload Filter, physical isolation |
| Operations | Operator, backup, upgrade, metrics, and disaster recovery |
| Cost | Memory footprint, storage, query CPU/GPU, write amplification |

Do not choose based solely on a single ANN Benchmark. Metadata Filter, incremental writes, deletion, backup, and failure recovery often matter more for production experience.

## 7. Common Implementations

### PostgreSQL + pgvector

Suitable for teams that already operate PostgreSQL, for small-to-medium scale, and for scenarios where transactional metadata and vectors live in the same database. Advantages include mature SQL, permissions, and backup; very large-scale ANN or high concurrency requires careful validation of partitioning, indexes, and scalability.

### Qdrant

Purpose-built for vector search, with support for Shard, Replica, Payload Filter, and distributed deployment. When self-hosting, plan Shard count, replication, rebalancing, snapshots, and Load Balancer in advance; enabling cluster mode does not automatically replicate existing data.

Reference: [Qdrant Distributed Deployment](https://qdrant.tech/documentation/scaling/distributed_deployment/)

### Milvus

Purpose-built for large-scale vector search, with a layered architecture separating compute, storage, and coordination components. Suitable for scenarios requiring horizontal scaling and complex indexes, but with more components; you must evaluate the operational cost of metadata, message/WAL, object storage, and each worker.

Reference: [Milvus Architecture](https://milvus.io/docs/architecture_overview.md)

### OpenSearch/Elasticsearch

Suitable for teams that already have a search platform and need Keyword, Filter, aggregation, and Vector Hybrid Search. Pay attention to Segment, Merge, Heap, Shard count, and the memory/disk cost of vector indexes.

Choosing managed service versus self-hosting depends on data sovereignty, latency, cost, and whether the team truly has the operational capability for stateful databases.

## 8. Kubernetes Deployment Principles

Vector databases are stateful systems. Minimum requirements:

- StatefulSet/Operator manages stable identity;
- Anti-affinity or topology-spread replicas;
- Appropriate StorageClass, IOPS, and expansion capability;
- PDB consistent with the actual Quorum;
- Init/Readiness/Liveness understands database semantics;
- Rolling upgrades and version skew have official support;
- Snapshots, logical backups, and recovery drills;
- Separation of management, internal replication, and client ports;
- NetworkPolicy, TLS, authentication, and Secret;
- Capacity, water level, and Compaction monitoring.

Kubernetes recreating a Pod does not mean data has been recovered or Replicas have resynchronized.

## 9. Sharding and Replication

### Shard

Used to scale capacity and query throughput horizontally. Too few creates hotspots; too many increases metadata, connections, and fan-out.

### Replica

Used for availability and read throughput. The replication factor must account for failure-domain placement; multiple replicas on the same node provide no node-level disaster tolerance value.

### Rebalance

After adding nodes, whether data moves automatically depends on the product and deployment method. Rebalancing consumes network, disk, and CPU; you must throttle the speed and observe online latency.

### Quorum

PDB, node maintenance, and replica count must match the database consistency protocol. An incorrect PDB can either block all maintenance or allow too many replicas to be evicted at once.

## 10. Index Publishing Patterns

Blue/Green is recommended:

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

Avoid making large-scale in-place modifications to Chunk, Embedding, or Index parameters in a production Collection.

## 11. Incremental Updates

Must handle:

- Upsert idempotency keys;
- Source Cursor/Offset;
- Document deletion and permission revocation;
- Duplicate events and out-of-order delivery;
- Temporary Embedding failures;
- Dual-write of old and new versions;
- Data freshness SLO;
- Poison Document isolation;
- Schema Evolution.

Deletion is harder than insertion: after the source document is deleted, all Chunks, Embeddings, Cache, index replicas, and backup retention policies must be executed consistently.

## 12. Hybrid Search and Rerank

Common path:

```text
Query
  ├── Dense Vector Search
  ├── Sparse/BM25 Search
  └── Metadata/ACL Filter
        → Fusion
        → Reranker
        → Context Selection
```

Rerankers are usually more accurate than vector similarity, but add model inference, latency, and cost. Record the Top-K, latency, and elimination reason at each stage to optimize quality.

## 13. Permission Filtering

One of the most serious infrastructure risks in RAG is retrieving documents the user is not authorized to read.

Principles:

- ACLs enter Metadata at ingestion time, but queries still use real-time identity;
- Filtering must take effect at the retrieval layer, not only after LLM output;
- Tenant ID is injected by a trusted gateway, never accepted from arbitrary client claims;
- Permission changes and deletions have a freshness SLO;
- Cache Keys include tenant, permissions, and index version;
- High-isolation tenants use dedicated Collections/instances/clusters;
- Record the document IDs and versions actually retrieved for a given answer.

## 14. Caching

| Cache | Key | Invalidation Condition |
| --- | --- | --- |
| Document parsing | Source Digest + Parser Version | Source document or parser changes |
| Embedding | Text Digest + Model Revision | Text or model changes |
| Query Embedding | Query + Model + Tenant Policy | Model/policy changes |
| Retrieval Result | Query + Filter + Index Version | Index/permission changes |
| Rerank | Candidates + Reranker Revision | Candidates/model changes |
| LLM Response | Full context and generation configuration | Any input or policy changes |

Permission-sensitive caches must prevent cross-tenant hits.

## 15. Backup and Disaster Recovery

Must back up separately:

- Raw/normalized documents;
- Source Cursor and Pipeline state;
- Collection Schema and Index parameters;
- Vector data and Metadata;
- Database snapshots/WAL;
- Embedding/Chunk/Parser versions;
- Permission mappings;
- Publishing aliases.

If the index can be rebuilt from authoritative documents, also measure whether the rebuild time meets the RTO. Rebuilding billions of vectors can far exceed database snapshot recovery time.

## 16. Observability

### Offline

- Ingestion latency, throughput, failures, and retries;
- Parse, Chunk, and Embedding stage latency;
- Data freshness from Source to Index;
- Index build time and resources;
- Deletion/permission update backlog;
- Data volume and cost per version.

### Online

- Query, Filter, ANN, and Rerank stage latency;
- Recall/Precision/nDCG/MRR or task quality;
- Top-K, hits, empty results, and degradation;
- Shard/Replica/node hotspots;
- Cache hit rate;
- Final Context tokens and citation accuracy;
- Per-tenant QPS, data volume, and cost.

## 17. Failures and Degradation

| Failure | Optional Degradation |
| --- | --- |
| Vector DB unavailable | Fail explicitly or switch to read-only replicas; do not fabricate results |
| Reranker timeout | Return a controlled Top-K without Rerank |
| Embedding service failure | Queue backlog, keep old index |
| New index quality failure | Keep production alias unchanged, do not switch |
| Single Shard hotspot | Rate-limit, add replicas, reshard |
| Permission service unavailable | Fail Closed; do not return potentially unauthorized documents |
| Source delay | Expose data freshness rather than staying silent |
| LLM service failure | Retrieved results still need protection; do not write to ordinary error logs |

## 18. Production Checklist

- [ ] Source, Parser, Chunk, Embedding, Index, and Reranker are all versioned.
- [ ] Offline index construction is decoupled from online queries.
- [ ] Vector database is designed as a stateful system, not a plain Deployment.
- [ ] Shard, Replica, Quorum, PDB, and failure domains are mutually consistent.
- [ ] New indexes are published via Blue/Green aliases and can be rolled back.
- [ ] Incremental updates support idempotency, deletion, out-of-order, and Poison Data.
- [ ] ACL is enforced before retrieval, and Cache cannot leak across tenants.
- [ ] Actual RTO for backup recovery and source rebuild has been measured.
- [ ] Trace can decompose Embed, Retrieve, Rerank, and LLM.
- [ ] Retrieval quality, freshness, latency, and cost all have SLOs.

## Further Reading

- [Qdrant Distributed Deployment](https://qdrant.tech/documentation/scaling/distributed_deployment/)
- [Qdrant Production Checklist](https://qdrant.tech/documentation/production-checklist/)
- [Milvus Architecture](https://milvus.io/docs/architecture_overview.md)
- [OpenSearch Vector Search](https://docs.opensearch.org/latest/vector-search/)
- [Kubernetes StatefulSets](https://kubernetes.io/docs/concepts/workloads/controllers/statefulset/)
- [Kubernetes Volume Snapshots](https://kubernetes.io/docs/concepts/storage/volume-snapshots/)
