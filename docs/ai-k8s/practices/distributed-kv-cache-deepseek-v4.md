---
title: DeepSeek V4 Flash 的分布式 KV Cache：从 P/D 直传到全局缓存池
description: 区分 P/D KV 直传、KV Offload、Prefix 感知路由与跨引擎共享缓存，比较 Mooncake、AIBrix、LMCache/llm-d 和 Dynamo KVBM，并给出 DeepSeek V4 Flash 的渐进验证路线
status: exploratory
last_reviewed: 2026-08-12
---

# DeepSeek V4 Flash 的分布式 KV Cache：从 P/D 直传到全局缓存池

当在线用户、长会话和 Agent 请求持续增加，单个推理 Engine 的 GPU KV Cache 很快会遇到两个问题：不活跃会话占用 HBM，而请求被路由到另一副本后又要重新计算已经出现过的长前缀。P/D 分离还增加了第三个问题：Prefill 在哪里生成 KV，Decode 应从哪里读取，以及传输失败时怎样回退。

这些需求经常被概括为“建设中央式 KV Cache”。这个说法容易让人联想到一台集中式缓存服务器，但生产架构更适合采用下面的定义：

> 中央化的是 KV Cache 的全局目录、生命周期和调度决策；KV Block 本身应分布在 GPU HBM、节点内存、本地 NVMe 和远端存储中，并保留重新 Prefill 的降级路径。

本文只讨论公开架构与可复现实验，不包含组织、人员、内部集群、仓库、地址或容量信息。社区能力更新很快，文中的“已实现”仅指所引用版本或文档明确提供的能力，不表示已经在 DeepSeek V4 Flash 上完成生产验证。

## 1. 先拆开四个常被混用的概念

### 1.1 P/D KV 直传

同一次请求先由 Prefill Engine 处理 Prompt，再把本次生成的 KV Cache 交给 Decode Engine。KV 可以直接从 Prefill GPU 传到 Decode GPU，不要求存在长期保存 KV 的独立集群。

```text
Request → Prefill Engine ── NIXL / Mooncake / RDMA ──→ Decode Engine
                   本次请求的 KV Transfer
```

它解决的是 Prefill/Decode 阶段解耦，不自动解决历史会话跨副本复用。

### 1.2 KV Offload

当 HBM 空间不足或不活跃会话长期占用显存时，把 KV Block 下沉到 Host DRAM、NVMe 或远端存储，需要时再加载回来。它扩大了有效缓存容量，但增加 PCIe、磁盘或网络 I/O。

### 1.3 Prefix Cache 感知路由

KV 仍然保存在各 Engine 本地，Router 维护或估算“哪个实例缓存了哪些 Token Prefix”，优先把请求送到命中率高且负载合适的 Engine。它减少跨节点搬运，但副本缩容或故障后，本地缓存仍可能消失。

### 1.4 跨引擎共享 KV

多个 Engine 使用共享的 L2/L3 KV Backend，缓存不再完全依附某个 GPU 进程。请求可以在另一副本恢复 Prefix，代价是全局索引、数据布局兼容、租户隔离、容量治理和远端传输。

这四种能力可以组合，却不能用一个“开了 KV Cache”概括：

| 能力 | 主要目标 | 是否需要共享存储 | 失败后的合理回退 |
| --- | --- | --- | --- |
| P/D 直传 | 隔离 Prefill 与 Decode | 否 | Decode 重新 Prefill 或转 Combined |
| KV Offload | 扩大有效容量、释放 HBM | 本机 Offload 不需要 | 重新计算被淘汰 Block |
| KV-aware Routing | 提高本地 Prefix 命中 | 否，但需要全局可见性 | 按负载选择其他实例 |
| 跨引擎共享 KV | 跨副本、跨重启复用 | 是 | Backend 不可用时重新 Prefill |

## 2. 推荐的分层架构

一个可扩展的实现通常包含控制面和数据面：

```text
                                 ┌─ Prefill Pool
OpenAI-compatible Request → Router┤
                                 ├─ Decode Pool
                                 └─ Combined Pool（短请求与故障兜底）
                                          │
                              P/D KV Transfer / Cache Load
                                          │
        ┌─────────────────────────────────┴──────────────────────────────┐
        │                                                                │
全局 KV 目录与调度                                                分层 KV 数据面
Prefix → Block Location                                     L1：GPU HBM
Model / Runtime / Layout Fingerprint                         L2：Host DRAM
Tenant / Session / TTL / Quota                               L3：Local NVMe
Load / Topology / Hit Cost                                   L4：Distributed KV Store
```

全局目录不应保存大块 Tensor，只保存 Prefix、Block、位置、版本、租户、有效期和状态。数据面按热度分层：活跃请求保留在 HBM，暂时不活跃的会话下沉到 DRAM，热点长 Prefix 可以进入 NVMe 或分布式 Store。

Router 的目标也不应只是“命中最多”，而应比较两种成本：

```text
预计收益 = 避免重新 Prefill 的时间
预计成本 = 排队时间 + KV 读取/传输时间 + 目标实例 Decode 压力
```

只有预计收益大于预计成本，远端复用才值得执行。否则直接在负载较低的 Engine 重新 Prefill 可能更快。

## 3. 四条值得跟踪的开源路线

### 3.1 SGLang HiCache + Mooncake

[Mooncake](https://github.com/kvcache-ai/Mooncake) 是公开的 KVCache-centric 分离式推理基础设施。它包括：

- Transfer Engine：在 VRAM、DRAM、NVMe 以及多种网络之间搬运 Tensor；
- Mooncake Store：分布式管理 KV Cache 与模型权重等 Tensor 对象；
- 多 RDMA NIC 带宽聚合、NUMA/拓扑感知路径选择和传输失败切换；
- 与 SGLang P/D、HiCache 以及 vLLM 的集成。

SGLang [HiCache](https://github.com/sgl-project/sglang/blob/main/docs_new/docs/advanced_features/hicache_design.mdx) 将 RadixAttention 从 GPU 扩展到 Host Memory 和远端存储，公开的 L3 Backend 选项包括 `file`、`mooncake`、`hf3fs`、`nixl`、`aibrix` 和 `dynamic`。这条路线和 SGLang Engine 结合最紧，适合优先验证 DeepSeek V4 Flash。

但“有启动参数”不等于该组合已经成熟。一个公开的 [DeepSeek V4 Flash + H20 + Mooncake P/D 复现](https://github.com/sgl-project/sglang/issues/26475) 指出，DeepSeek V4 除主 C4 KV 外，还有 SWA/额外状态、FlashMLA 与传输元数据；在启用 HiSparse 后，社区观察到 SWA 额外状态传输卡住和 Prefix 命中语义不完整。它至少说明：

1. 社区已经在 H20 上运行这条 DeepSeek V4 数据路径；
2. 不能只验证主 KV Block，还要验证全部附加状态；
3. 第一轮应关闭 HiSparse 和推测解码，先建立普通 P/D 与分层缓存基线。

### 3.2 AIBrix Distributed KV Cache

[AIBrix](https://github.com/vllm-project/aibrix) 同时覆盖 Kubernetes 编排、Gateway 路由、P/D 配对和 KV Cache 管理。需要按版本区分能力：

- 已有稳定版本可完成模型发现、P/D Role 配对、Prompt 长度分桶、负载打分和 Combined 回退；
- 当前主干与后续发布正在统一 `aibrix_kvcache` 数据面，提供 L1 DRAM、可插拔 L2、Prefix Cache Connector 和 Redis 支持的 Gateway 状态同步；
- P/D Router 与 KV 数据面可以组合，但 Router 选择 Prefill/Decode 不等于历史 KV 已跨副本共享。

这条路线最适合已经使用 AIBrix Gateway 的集群：继续让 AIBrix承担入口、服务发现和缓存感知调度，再通过受支持的 Connector 选择 Mooncake、AIBrix KV Backend 或其他数据面。上线前必须锁定 AIBrix、Engine、Connector、NIXL、UCX/CUDA 和 Cache Backend 的组合版本。

### 3.3 llm-d + LMCache

[llm-d](https://github.com/llm-d/llm-d) 是面向 Kubernetes 的分布式推理栈，公开目标包括：

- Prefix Cache 和负载感知路由；
- KV Cache 的精确全局索引；
- CPU、Disk 和远端层级 Offload；
- P/D 分离、流控、SLO 感知调度和自动扩缩。

[LMCache](https://github.com/LMCache/LMCache) 提供 KV Cache Connector、CPU/磁盘 Offload、远端缓存和 P/D 支持。其 vLLM P/D 示例通过 NIXL 使用 NVLink、RDMA 或 TCP；旧的 in-process 模式已标记弃用，新验证应使用 MP 模式。

vLLM 官方 DeepSeek V4 Flash Recipe 已把 CPU Offload 和 Filesystem Offload 标为 verified，并把 `LMCacheMPConnector` 作为通用 KV Offload 选项提供给单节点 TP/TEP/DEP 策略。当前 Recipe 的 LMCache 模式是每节点一个伴随式 `lmcache server`，不是跨节点共享池；因此它足以进入 DeepSeek V4 的节点内兼容性测试，但不能直接证明“跨节点中央 KV Cache 已支持”。可执行的单节点 Baseline/LMCache A/B 材料见：[DeepSeek V4 Flash：vLLM + LMCache MP](https://github.com/runzhliu/aik8s/tree/main/examples/deepseek-v4-flash-vllm-lmcache)。

测试还需要覆盖已知风险：DeepSeek V4 使用多组 Hybrid KV，社区已有 Prefix Cache 重放 0% 命中、高并发 Offload Worker 崩溃，以及 DSpark Draft KV 外部命中长期为零的报告。第一轮应关闭 DSpark 和 P/D，只验证 GPU Cache 淘汰后的 LMCache Load、确定性输出与并发稳定性；随后再把 P/D、远端 Backend 和 Draft Model 分别作为独立变量。

### 3.4 NVIDIA Dynamo KVBM

[Dynamo KVBM](https://docs.nvidia.com/dynamo/dev/knowledge-base/modular-components/kvbm/overview) 提供跨 GPU、Pinned Host Memory、RDMA Remote Memory、SSD 和远端存储的统一 Block 管理，并使用 NIXL 完成注册、共享与传输。它清楚地区分：

- KV-aware Routing：根据 Prefix 重叠和负载选择 Worker；
- P/D KV Transfer：把当前请求的 KV 从 Prefill 交给 Decode；
- KV Offloading：在 GPU、CPU、Disk 或远端层之间迁移 Block。

当前公开支持矩阵中，KVBM支持 vLLM 和 TensorRT-LLM，尚不支持 SGLang。因此它很适合参考生命周期、分层和指标设计，但不应被写成 DeepSeek V4 + SGLang 的现成落地方案。NVIDIA 另有 [DeepSeek V3.2 + TensorRT-LLM + P/D + KV-aware Routing](https://docs.nvidia.com/dynamo/dev/recipes/deepseek-v3-2-nvfp4) 的大规模 Recipe，可用于理解测试方法，不能替代 H20 与 DeepSeek V4 实测。

### 3.5 选型摘要

| 路线 | 主要 Engine | 分层 KV | P/D | 全局路由 | DeepSeek V4 直接证据 | 当前定位 |
| --- | --- | --- | --- | --- | --- | --- |
| SGLang HiCache + Mooncake | SGLang | GPU/DRAM/远端 Store | 是 | 需组合 Router | H20 复现存在，但有未解决问题 | 第一验证对象 |
| AIBrix KVCache | vLLM 为主，扩展多 Engine | L1 + 可插拔 L2 | 是 | 强 | 需锁定版本验证 | 现有控制面演进 |
| llm-d + LMCache | vLLM | GPU/CPU/Disk/远端 | 是 | 强 | 暂无等价开箱证据 | vLLM 严格对照 |
| Dynamo KVBM | vLLM/TRT-LLM | GPU/CPU/SSD/远端 | 是 | 强 | 有 DeepSeek V3.2 Recipe | 长期架构参考 |

## 4. DeepSeek V4 Flash 为什么需要单独验证

DeepSeek V4 Flash 的 KV Cache 比传统 GQA 模型更小。公开的模型介绍称，V4 Flash 的 KV Cache 约为 DeepSeek V3.2 的 7%，相对常规 8-head GQA BF16 KV 更低：[DeepSeek V4 架构介绍](https://github.com/huggingface/blog/blob/main/deepseekv4.md)。因此，建设分布式 KV Cache 的主要价值未必是“KV 放不进 HBM”，更可能是：

- Coding Agent、搜索 Agent 和工具调用中的长会话恢复；
- 多用户共享系统 Prompt、工具定义、知识库或代码仓库前缀；
- P/D 分离后的 KV 位置发现和传输；
- Engine 扩缩容、重建或请求迁移后的 Prefix 复用；
- 把不活跃会话移出 HBM，提高活跃请求并发。

V4 的注意力状态也不能简单视为传统的一组 K/V Tensor。至少要验证主 KV、滑动窗口或其他额外状态、Indexer/FlashMLA 元数据、目标模型与 Draft Model 状态，以及它们在 Prefix 命中、淘汰和 P/D 传输中的一致性。

“用户数增加”本身不是启用共享 KV 的充分条件。如果请求彼此独立、Prompt 很短且 Prefix 重叠低，中央缓存只会增加索引和传输成本。是否值得可以用下面的关系判断：

```text
可复用 Token 比例 × 避免的 Prefill 计算时间
  > 全局查询 + KV 读取 + 网络传输 + 目标排队时间
```

## 5. 推荐的渐进验证路线

### 阶段 A：先保留 Combined 基线

固定模型 Digest、Runtime Image、TP、上下文、KV dtype、CUDA Graph、推测解码和请求集，得到单个 Combined TP=8 的正确性、TTFT、TPOT、吞吐、HBM 与功耗基线。

此前 H20 实测已经证明，P/D 对低负载短请求未必有利，而并发和长 Prompt 更容易获得尾延迟收益。完整数据见：[DeepSeek-V4-Flash-0731 的 H20 部署与压测](deepseek-v4-flash-h20-evaluation.md)。

### 阶段 B：只验证 P/D 直传

使用两台同规格节点：一个 Prefill TP=8、一个 Decode TP=8，先关闭 HiSparse、推测解码和共享 L3 Cache，只保留 SGLang P/D、Mooncake 或 NIXL、RDMA 与普通 Radix Cache。

验收必须同时满足：

1. Prefill 与 Decode 的模型、Tokenizer、数据类型和 KV Layout 完全一致；
2. Transfer Backend 初始化成功，且没有静默回退 TCP；
3. Prefill/Decode 日志能关联同一个 Request ID；
4. 成功传输计数和 RDMA 端口硬件计数同时增长；
5. Decode 没有因传输失败重新 Prefill；
6. 固定 Prompt 的确定性输出正确；
7. Backend 失败时能转 Combined 或重新计算，而不是使用不完整状态。

### 阶段 C：加入 L2 Host Memory

先做节点内 Offload，避免同时引入分布式 Store。比较 HBM 释放量、Host Memory 占用、PCIe 带宽、Cache Hit/Load 延迟和高并发下的 TPOT。只有重复长 Prefix 能覆盖加载成本时，才继续扩大 Offload 容量。

### 阶段 D：加入分布式 L3

选择 Mooncake Store、AIBrix KV Backend 或 LMCache Remote Backend 中的一条，验证跨 Engine 命中。此时要补齐：

- 全局 Block Index、Watcher 与 Cache Engine 高可用；
- 租户、Session、模型与 Runtime 指纹；
- TTL、Quota、Eviction、背压和容量水位；
- Cache Backend 中断、网络分区和脏条目的回退；
- 缓存节点扩缩时的数据重平衡和热点迁移。

### 阶段 E：最后启用 DeepSeek V4 专项优化

在普通 P/D 和分层 Cache 已稳定后，再分别开启 HiSparse、Draft Model、FP8 KV 与更大上下文。每次只改变一个变量，并重新跑正确性、Prefix 命中、传输完整性和性能 A/B。

## 6. 压测必须模拟可复用 Prefix

只用随机 Prompt 压测无法证明共享 KV 有价值。最少需要四组负载：

| 请求集 | Prefix 特征 | 要回答的问题 |
| --- | --- | --- |
| 随机 Prompt | 几乎不重叠 | Cache Miss 增加多少成本 |
| 公共系统 Prompt | 多用户共享固定前缀 | Router 能否稳定命中公共 Block |
| 多轮会话 | 同一 Session 持续追加 | 会话迁移后能否复用历史 KV |
| Agent/代码仓库 Trace | 长 Prefix、短增量、工具结果不断追加 | 是否真实降低长上下文 TTFT 与 Goodput |

核心指标包括：

- p50/p95/p99 TTFT、TPOT、ITL、E2E 与 Goodput；
- Prefix Cache 命中 Token 数，而不是只看请求命中率；
- P/D KV Transfer 和共享 Backend Load 的字节、耗时、失败率；
- GPU HBM、Host Memory、NVMe、RDMA 各层容量与带宽；
- Eviction、Promotion、Demotion、Recompute 和 Combined Fallback；
- 每百万 Token 成本以及每次命中实际节省的 GPU·秒。

测试矩阵至少包含：

```text
Combined + Round Robin
Combined + KV-aware Routing
P/D + 无共享 Cache
P/D + L2 Host Memory
P/D + Distributed L3
```

所有组合使用同一 Trace、到达时间和 SLO，避免把更多 GPU 或不同并发误认为缓存收益。

## 7. 多租户与故障边界

KV Cache 可能包含用户 Prompt、检索内容、源代码、工具结果和业务数据。全局 Cache Key 不能只使用 Token Hash，至少应包含：

```text
Tenant / Security Domain
+ Model Digest / Tokenizer / Chat Template
+ Runtime / KV Layout / Block Size / DType
+ Adapter / LoRA / Prompt Adapter
+ Prefix Token Hash
```

跨用户共享应只允许经过明确分类的公共 Prefix；私人会话默认限制在租户或 Session 域内。元数据、缓存数据和访问日志需要独立鉴权、传输加密、静态加密、保留周期和删除能力。

共享 Backend 不能成为推理硬依赖。推荐的降级顺序是：

1. 远端 KV 命中失败后回到本地 Prefix Cache；
2. 本地也未命中则重新 Prefill；
3. P/D pair 不完整或传输失败时转 Combined；
4. 只有模型本身不可用时才返回服务错误。

需要为 KV 复用设置超时预算。如果远端 Load 已经接近重新 Prefill 的预计耗时，Router 应主动取消远端读取并重算。

## 8. 当前建议

对 DeepSeek V4 Flash，当前更稳妥的路线不是立即建设一个大而全的“中央缓存集群”，而是：

1. 用现有 Combined TP=8 作为正确性和成本基线；
2. 优先验证 SGLang + Mooncake/NIXL + RDMA 的普通 P/D 直传；
3. 让 AIBrix 或等价 Router 承担 P/D 配对、Prefix 与负载感知选择、Combined 回退；
4. 先加入节点 Host Memory，再选择一个分布式 L3 Backend；
5. 只有在真实 Agent Trace 证明 Prefix 重用能覆盖查询和传输成本后，才扩大缓存池；
6. 最后再启用 HiSparse、推测解码和 V4 专属状态优化。

开源社区已经提供足够多的控制面和数据面组件，真正困难的部分不是再造一套存储，而是验证 DeepSeek V4 的完整状态语义、版本兼容、缓存命中收益、租户隔离与失败回退。中央式 KV Cache 应被当作一套调度和数据生命周期系统，而不是一个新的共享磁盘。

延伸阅读：

- [Prefill/Decode 分离的性能拐点](pd-break-even.md)
- [DeepSeek-V4-Flash-0731 的 H20 部署与压测](deepseek-v4-flash-h20-evaluation.md)
- [在既有 Kubernetes 集群落地 AIBrix](aibrix-existing-cluster.md)
- [分布式推理与 P/D 分离](../inference/distributed-serving.md)
