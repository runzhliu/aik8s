---
title: LLM 推理优化：Batch、KV Cache、量化与并行
description: 用可验证的方法理解连续批处理、Prefix Cache、量化、投机解码和多种并行策略
status: evolving
last_reviewed: 2026-08-02
---

# LLM 推理优化：Batch、KV Cache、量化与并行

LLM 推理优化是多目标问题：吞吐、TTFT、TPOT、显存、质量、功耗和成本彼此制约。一个提高离线总吞吐的配置，可能让交互式请求的尾延迟变差。

## 1. 建立性能模型

LLM 请求主要分为：

```text
输入 Token
  → Prefill：并行处理 Prompt，偏计算密集
  → 首 Token
  → Decode：逐 Token 生成，偏内存带宽和同步敏感
  → 完成
```

核心指标：

| 指标 | 含义 | 主要影响因素 |
| --- | --- | --- |
| TTFT | 到首 Token 时间 | 排队、Prefill、Prefix Cache、网络 |
| TPOT/ITL | 输出阶段每 Token 延迟 | Decode Batch、内存带宽、并行通信 |
| E2E | 整个请求时间 | 输入/输出长度、排队和引擎 |
| Token Throughput | 每秒处理 Token | Batch、并发、硬件和模型 |
| Goodput | 满足 SLO 的有效吞吐 | 尾延迟、错误、拒绝和质量 |

Goodput 比峰值吞吐更接近生产价值。

## 2. 连续批处理

静态 Batch 要等一组请求全部完成，长短请求混合时会浪费计算。连续批处理允许在每个调度步加入新请求、移除已完成请求。

调优变量通常包括：

- 最大并发序列；
- 每轮最大 Batched Token；
- Prefill 与 Decode 的调度优先级；
- Chunked Prefill 大小；
- 最大等待时间；
- 内存水位和抢占策略。

增大 Batch 通常提高吞吐，但可能增加排队和 TPOT。应分别为交互式、批处理和长上下文建立配置档。

## 3. KV Cache 容量

KV Cache 随层数、KV Head、Head Dimension、精度和上下文增长。简化理解：

```text
KV Cache ∝ 并发序列数 × 上下文 Token × 每 Token KV 大小
```

显存预算：

```text
GPU HBM = 模型权重
        + KV Cache
        + 激活与临时 Workspace
        + 通信 Buffer
        + CUDA Graph/引擎开销
        + 安全余量
```

不要把所有剩余显存都分给 KV Cache。负载波动、模型特性和通信库仍需空间，否则会出现难以预测的 OOM。

## 4. Paged KV Cache

分页管理把 KV Cache 划分为 Block，减少连续内存和碎片要求，并支持更灵活的序列加入、完成和共享。它解决内存管理问题，但不会自动解决：

- 请求应该路由到哪个副本；
- Prefix 是否跨副本复用；
- KV 是否 Offload 到 CPU/NVMe；
- P/D Worker 之间如何传输；
- 不同租户如何隔离和计费。

这些需要 Router、Indexer、Offloader 和控制面协作。

## 5. Prefix Cache

适合：

- 大量请求共享 System Prompt；
- 多轮对话重复历史前缀；
- RAG Template 稳定；
- Agent 使用相同工具定义；
- 批量处理具有共同前缀。

衡量：

- 命中 Token 数和命中率；
- 节省的 Prefill 时间；
- Cache 占用和淘汰；
- Router 亲和带来的负载不均；
- Prefix 隔离和敏感数据风险。

简单 Least-Loaded 路由可能破坏 Cache 命中，简单 Cache-Affinity 又可能制造热点，需要多目标打分。

## 6. KV Cache Offload

层次可以是：

```text
GPU HBM
  ↕ 高速
CPU DRAM
  ↕
本地 NVMe
  ↕
远端共享存储/分布式缓存
```

Offload 能扩大有效容量，但增加延迟、带宽和一致性开销。必须测量：

- Offload/Restore 吞吐和尾延迟；
- CPU/NUMA 与 GPU 拓扑；
- NVMe 写放大和寿命；
- 远端网络拥塞；
- Cache Eviction；
- 节点故障后的状态；
- 敏感 Prompt 是否进入持久介质。

## 7. 权重量化

量化目标包括减少权重显存、提高内存带宽效率和使用低精度 Tensor Core。常见类别：

| 类型 | 示例 | 特点 |
| --- | --- | --- |
| Weight-only | INT4/AWQ/GPTQ | 显著缩小权重，激活保持较高精度 |
| Weight + Activation | FP8/INT8 | 可能获得更高硬件吞吐，需要 Scale/校准 |
| KV Cache Quantization | FP8/更低精度 | 扩大上下文和并发，需关注长上下文质量 |
| GGUF Quant | 多种整数/混合格式 | 常用于 llama.cpp 和本地推理 |

选择前验证：

- 目标 GPU/ASIC 是否有高效 Kernel；
- 模型架构和 MoE 是否支持；
- 校准数据是否代表生产分布；
- 质量、安全、Tool Calling 和结构化输出是否回归；
- 吞吐提升是否抵消转换和运维成本。

vLLM 的量化支持矩阵按硬件和实现变化，应固定目标版本验证。[vLLM Quantization](https://docs.vllm.ai/en/stable/features/quantization/)

## 8. 投机解码

投机解码使用 Draft Model、N-gram、MTP/EAGLE 等方法一次提出多个候选 Token，再由主模型验证。

可能收益：

- 降低单请求 Decode 延迟；
- 在主模型计算昂贵且接受率高时提高输出速度。

可能无收益甚至变慢：

- Draft 模型占用额外显存；
- 候选接受率低；
- 高并发下主模型已充分 Batch；
- 量化、并行或模型结构组合不兼容；
- Draft 调度引入额外同步。

必须分别测试单流低延迟和高并发吞吐，不要把单请求结果外推到生产。

## 9. Chunked Prefill

长 Prefill 会长时间占据一次调度步骤，影响已有 Decode 请求的 TPOT。Chunked Prefill 把长 Prompt 拆分，使 Prefill 与 Decode 更容易交错。

调参要平衡：

- Chunk 太大：交互式 Decode 被长 Prefill 阻塞；
- Chunk 太小：调度和 Kernel 开销增加；
- Batched Token 上限；
- TTFT 与 TPOT 的优先级；
- Prefix Cache 和多模态输入行为。

## 10. 并行策略

### Tensor Parallel（TP）

把单层张量切到多设备，需要频繁 Collective。优先放在 NVLink/NVSwitch 等高带宽域。

适合单卡装不下或单卡吞吐不足。扩大 TP 可能降低单请求延迟，但通信开销会增加。

### Pipeline Parallel（PP）

按层切分到多个 Stage，适合跨节点或互联较弱的情况。需要处理 Pipeline Bubble、Batch 和 Stage 不均衡。

### Data Parallel（DP）

每个副本持有完整模型，处理不同请求。适合模型能装入单副本并需要扩吞吐。副本间请求路由决定 Cache 命中与均衡。

### Expert Parallel（EP）

MoE Expert 分布在不同设备，需要 All-to-All，对网络拓扑和负载均衡敏感。

### Context/Sequence Parallel

把长上下文计算沿序列维拆分，适合超长上下文，但引入通信和实现限制。

## 11. 如何选并行组合

推荐顺序：

1. 单 GPU 是否能容纳权重和目标 KV Cache；
2. 单节点内优先使用高速互联的 TP；
3. 跨节点再评估 PP/TP 组合；
4. 扩吞吐优先增加 DP 副本；
5. MoE 根据 Expert 和网络评估 EP；
6. 超长上下文再考虑 Context Parallel；
7. 达到足够规模后评估 P/D 分离。

不要因为有 8 张 GPU 就默认 TP=8。对于能单卡容纳的模型，8 个 DP 副本可能提供更好的总吞吐和故障隔离。

## 12. 模型编译和 CUDA Graph

图编译、Kernel Autotune 和 CUDA Graph 可以减少 Python/Launch 开销，但会引入：

- 首次启动或首次 Shape 的编译时间；
- 编译 Cache；
- 动态 Shape/多模态限制；
- 驱动、GPU 架构和引擎版本绑定；
- 更复杂的回滚和故障诊断。

把编译产物作为模型供应链的一部分，并分别测量冷启动和热启动。

## 13. LoRA 与多模型服务

在一个基础模型上动态加载多个 Adapter 可以节省权重显存，但需要治理：

- Adapter 来源、大小和兼容性；
- 加载/卸载和缓存策略；
- Router 是否知道 Adapter 所在副本；
- 每租户并发、Token 和成本；
- Adapter 质量与安全评估；
- 基础模型升级时的兼容；
- 一个恶意 Adapter 对共享进程的影响。

多模型塞进一个进程也会产生显存碎片、故障域扩大和复杂调度，不一定优于独立部署。

## 14. 调优实验设计

一次只改变一组变量：

```text
基线：BF16、默认 Batch、单副本
  → 调整 Batch/并发
  → 调整 KV Cache 和上下文
  → 测试 Prefix Cache
  → 测试量化
  → 测试 TP/PP/DP
  → 测试投机解码
  → 测试 Offload/P-D
```

每步保存配置、原始请求、指标、质量结果和硬件元数据。若同时改变量化、Batch 和并行，无法知道收益来自哪里。

## 15. 真实负载矩阵

至少覆盖：

- 短输入/短输出；
- 长输入/短输出；
- 短输入/长输出；
- 长输入/长输出；
- 共享前缀高/低；
- 平稳、突发和周期流量；
- 流式和非流式；
- 多租户优先级；
- Tool Calling/结构化输出；
- 取消、超时和客户端断开。

使用平均长度的固定请求会隐藏生产尾部问题。

## 16. 性能与质量门禁

| 维度 | 示例门禁 |
| --- | --- |
| 质量 | 任务成功率下降不超过阈值 |
| TTFT | P95/P99 满足交互 SLO |
| TPOT | 高并发下仍满足流畅输出 |
| Goodput | 满足全部 SLO 的请求/秒不下降 |
| 稳定性 | 目标时长压测无 OOM/死锁 |
| 冷启动 | 缓存冷/热都在预算内 |
| 成本 | 每百万有效 Token 成本 |
| 安全 | 结构化输出、工具和内容策略通过 |

## 17. 常见反优化

- Batch 太大导致 TTFT/TPOT 失控；
- `max-model-len` 设到理论最大，挤压实际并发；
- 量化缩小权重但 Kernel 在目标硬件更慢；
- TP 跨慢速网络，通信收益为负；
- Prefix Cache 路由导致少数副本过热；
- 投机解码在高并发下额外消耗 GPU；
- Offload 让 PCIe/网络成为瓶颈；
- 模型编译让冷启动无法满足弹性需求。

## 18. 生产检查清单

- [ ] 性能模型区分 Prefill、Decode、排队和网络。
- [ ] 显存预算包含权重、KV、Workspace、通信和余量。
- [ ] Batch 参数同时满足吞吐和尾延迟。
- [ ] Prefix Cache 有命中、容量、路由和隐私指标。
- [ ] 每个量化版本经过质量和目标硬件性能回归。
- [ ] 并行策略与 NVLink/RDMA/拓扑相匹配。
- [ ] 投机解码分别验证低并发与高并发。
- [ ] 编译和预热时间进入冷启动预算。
- [ ] LoRA/多模型有权限、缓存和故障隔离策略。
- [ ] 所有优化通过同一真实负载矩阵和 Goodput 门禁。

## 延伸阅读

- [vLLM Quantization](https://docs.vllm.ai/en/stable/features/quantization/)
- [vLLM Distributed Serving](https://docs.vllm.ai/en/latest/serving/distributed_serving.html)
- [SGLang Documentation](https://docs.sglang.io/)
- [TensorRT-LLM Documentation](https://nvidia.github.io/TensorRT-LLM/latest/)
- [Triton Dynamic Batching](https://docs.nvidia.com/deeplearning/triton-inference-server/user-guide/docs/user_guide/batcher.html)
- [llm-d KV Cache Management](https://llm-d.ai/docs/architecture/advanced/kv-management)
