---
title: 多机与分离式 LLM 推理
description: 设计多机模型副本、LeaderWorkerSet、Prefill/Decode 分离、KV 传输、llm-d 和 NVIDIA Dynamo
status: evolving
last_reviewed: 2026-08-03
---

# 多机与分离式 LLM 推理

当模型、KV Cache 或目标吞吐超过单机能力时，推理副本会从一个 Pod 变成多个相互依赖的 Worker。更进一步，Prefill 与 Decode 可以拆成独立资源池，通过网络传输 KV Cache。

这类系统能够提高规模化效率，但也把网络、拓扑、发布、故障和状态管理引入请求关键路径。

## 1. 先区分三种扩展

| 模式 | 扩展对象 | 主要目标 |
| --- | --- | --- |
| Data Parallel | 增加完整模型副本 | 提高总请求吞吐和可用性 |
| 模型并行 | 一个模型副本跨多个 GPU/节点 | 让大模型装得下或降低单请求延迟 |
| P/D 分离 | Prefill 与 Decode 独立池 | 分别优化两类计算并独立扩缩容 |

一个生产系统可能同时使用三者：每个副本内部 TP/PP，多份 DP 副本，再拆分 Prefill 和 Decode Pool。

## 2. 多机模型副本

```text
一个逻辑模型副本
  Leader / API Pod
    ├── Worker 0：GPU 0-7，节点 A
    ├── Worker 1：GPU 0-7，节点 B
    └── Worker 2：GPU 0-7，节点 C
```

需要整体管理：

- 同时创建和删除；
- 稳定身份与发现；
- Gang/All-or-Nothing 调度；
- 网络和拓扑；
- 所有 Rank 的 Ready；
- 一个 Worker 故障时整体恢复；
- 以完整副本为单位扩缩和发布。

普通 Deployment 不具备这些语义。

## 3. LeaderWorkerSet

LeaderWorkerSet（LWS）用于描述一个 Leader 与多个 Worker 构成的复制单元，适合多机推理和其他 Leader/Worker 工作负载。

它提供：

- Group 级副本；
- Leader/Worker 稳定索引和发现；
- 有序/并行生命周期能力；
- 组级滚动更新和扩缩；
- 与 Kueue、Gateway 和推理控制面集成。

LWS 不负责模型请求路由、配额准入或 KV Cache。通常还需要：

- Kueue 做成组准入和拓扑；
- Gateway/InferencePool 做请求选择；
- 引擎完成 TP/PP 通信；
- 模型缓存和 RDMA 组件提供数据路径。

参考：[LeaderWorkerSet](https://lws.sigs.k8s.io/)

## 4. 拓扑选择

优先顺序通常是：

1. TP 尽量留在 NVLink/NVSwitch 域；
2. PP 跨节点时保证稳定 RDMA/高速网络；
3. MoE EP 关注 All-to-All 和 Expert 热点；
4. CPU、GPU、NIC 保持合理 NUMA/PCIe 邻近；
5. 多副本分散到故障域，而单个副本内部集中；
6. 模型缓存位于被选节点。

“副本内部集中”和“副本之间分散”是两个不同目标，需要分层拓扑策略。

## 5. vLLM 多机并行

vLLM 支持 Tensor/Pipeline 等分布式推理。典型思路：

- 单节点内 TP 等于本机使用的 GPU 数；
- 模型跨节点时加入 PP；
- 多副本吞吐通过 DP 或上层多个 Deployment/LWS；
- 具体 Runtime 可以使用 Ray 或其他受支持执行后端。

示意：

```bash
vllm serve /models/example \
  --tensor-parallel-size 8 \
  --pipeline-parallel-size 2
```

这表示一个逻辑副本使用 16 张 GPU 的概念配置，实际还需要多节点启动、地址发现、容器共享内存和网络参数。

参考：[vLLM Distributed Serving](https://docs.vllm.ai/en/latest/serving/distributed_serving.html)

## 6. Prefill 与 Decode 为什么不同

| 阶段 | 计算特征 | 主要资源压力 | 关键 SLO |
| --- | --- | --- | --- |
| Prefill | 一次处理输入 Token，可高度并行 | FLOPS、输入长度 | TTFT |
| Decode | 逐 Token 生成，反复读取权重/KV | HBM 带宽、同步、并发 | TPOT/ITL |

在共置模式中，同一组 GPU 在两类任务之间共享资源。负载不均时可能出现：

- 长 Prompt 阻塞交互 Decode；
- Prefill 峰值与 Decode 容量无法分别扩展；
- 不同硬件无法各自发挥优势；
- Queue 和 Batch 互相影响。

## 7. P/D 分离架构

```text
Client
  → Router / Frontend
      → Prefill Pool
          → 生成 KV Cache
          → 通过 NIXL/UCX/RDMA/其他 Connector 传输
      → Decode Pool
          → 继续生成并流式返回
```

收益来源：

- Prefill 与 Decode 独立扩缩；
- 使用不同 GPU 型号或并行配置；
- 分别调 Batch、并发和 SLO；
- 更好隔离长 Prompt 对 Decode 的影响；
- 在足够规模下提高利用率和 Goodput。

新增成本：

- KV 传输延迟和带宽；
- Peer 发现和连接管理；
- 双池容量平衡；
- 取消、故障和孤儿状态；
- 发布、回滚和版本兼容；
- 更多组件和可观测边界。

## 8. 什么时候不应该 P/D 分离

- 单机或少量 GPU 已满足 SLO；
- 请求短、KV 传输成本接近或超过收益；
- 网络没有稳定的高带宽低延迟能力；
- Prefill/Decode 流量比例稳定且共置效率已很好；
- 团队还没有完整的基准、Trace 和故障处理；
- 模型/引擎/Connector 组合没有生产支持；
- 冷启动和发布复杂度比 GPU 节省更重要。

P/D 分离是规模优化，不是部署 LLM 的入门前置条件。

## 9. KV 传输路径

必须明确：

- KV 格式、Block 大小、Dtype 和布局；
- Prefill/Decode 引擎和版本是否完全一致；
- 谁发起传输，Push 还是 Pull；
- Peer 如何发现和认证；
- 使用 GPU Direct、RDMA、TCP 还是共享存储；
- KV 在发送端何时释放；
- Decode 失败后如何清理；
- 请求取消如何传播；
- 传输超时和重试是否安全；
- KV 是否包含敏感 Prompt 信息。

一次模型或引擎升级可能改变 KV 布局，不能让新旧 Worker 任意互连。

## 10. llm-d

llm-d 是面向 Kubernetes 的分布式 LLM 推理架构，围绕：

- InferencePool 和 Endpoint Picker；
- vLLM/SGLang 等模型服务；
- Prefix/KV-aware Routing；
- KV Cache Indexing 和 Offload；
- P/D 分离；
- Flow Control；
- Kubernetes Deployment、Prometheus 和 Gateway 集成。

它适合希望使用 Kubernetes 原生 API 构建可组合推理数据面的团队。生产选型要固定 llm-d、Gateway Extension、Engine、Connector 和 CRD 版本。

参考：[llm-d Architecture](https://llm-d.ai/docs/architecture)

## 11. NVIDIA Dynamo

Dynamo 提供 Frontend、Router、Planner、Worker 和分离式推理能力，可组合 vLLM、SGLang、TensorRT-LLM 等 Backend，并通过 NIXL 等机制传输 KV。

适合：

- NVIDIA 平台的大规模分布式推理；
- 需要经过配方验证的 P/D、KV Routing、Expert Parallel；
- 希望通过 `DynamoGraphDeployment` 等资源表达组件图；
- 需要在部署前进行拓扑和容量规划。

需要管理 etcd/NATS 等发现或消息依赖、Dynamo CRD/Operator、Runtime 镜像和 Backend 兼容。

参考：[NVIDIA Dynamo Disaggregated Serving](https://docs.nvidia.com/dynamo/latest/user-guides/disaggregated-serving)

## 12. 双池容量规划

分别测量：

```text
Prefill 需求 ≈ 输入 Token 到达率 / 单 Prefill Worker 的有效 Token/s
Decode 需求  ≈ 输出 Token 到达率 / 单 Decode Worker 的有效 Token/s
```

还要加入：

- 长短 Prompt 分布；
- KV 传输并发和带宽；
- 单 Worker 故障冗余；
- 峰值与目标利用率；
- 模型/Cache 预热；
- 拒绝和排队预算。

两个 Pool 的 Autoscaler 不能只看自身局部队列。Prefill 扩得过快会淹没 Decode，Decode 过剩又会空等 KV。

## 13. 发布与版本

一个分离式版本至少包括：

- 模型 Artifact；
- Prefill Runtime 和参数；
- Decode Runtime 和参数；
- KV Connector/NIXL/UCX 版本；
- Router/EPP；
- Gateway 和 CRD；
- GPU Driver、CUDA/ROCm；
- 网络和 RDMA 配置。

Canary 最安全的方式是建立一整套新 Pool，而不是让新 Prefill 随机连接旧 Decode。

发布流程：

1. 创建新版本 Prefill/Decode Pool；
2. 通过兼容性和 KV 传输测试；
3. 预热模型和连接；
4. Shadow 无副作用流量；
5. 按租户/请求稳定 Canary；
6. 比较质量、TTFT、TPOT、Goodput 和成本；
7. 停止旧 Pool 新请求；
8. Drain 后回收。

## 14. 故障语义

| 故障 | 处理目标 |
| --- | --- |
| Prefill Worker 失败 | 请求可安全重试或快速失败，不产生无主 KV |
| Decode Worker 失败 | 已输出流式请求可识别终止，不重复副作用 |
| KV 传输超时 | 清理双方状态，记录链路和 Request ID |
| Router/EPP 失败 | 数据面回退或高可用实例接管 |
| Cache Index 失效 | 回退非 Cache-aware 路由 |
| 节点 Drain | 先移除 Endpoint，再停止新配对 |
| 新旧版本不兼容 | 发布门禁阻止跨版本连接 |
| 网络分区 | 超时、隔离和恢复不会重复请求 |

## 15. 可观测性

必须能从一次请求看到：

```text
Gateway
  → Router 选择原因
  → Prefill 排队/执行
  → KV 大小、传输时间和路径
  → Decode 排队/执行
  → Token 流式返回
```

指标：

- Prefill/Decode 各自队列、Batch 和 Token/s；
- KV 传输字节、时间、失败和重试；
- Peer 数、连接建立和断开；
- TTFT 中路由、排队、Prefill、传输分解；
- TPOT 和 Decode Batch；
- 孤儿 KV、取消和清理；
- Pool 扩缩容、Ready 和版本；
- RDMA/NIC/GPU/CPU 指标。

## 16. 安全

- KV Cache 可能包含可还原的用户上下文，按敏感数据处理；
- Prefill 与 Decode 之间使用网络身份、加密或受控数据平面；
- 不同租户的 KV Index 和 Cache 访问边界明确；
- Worker 不对公网暴露；
- Router 不能把请求送到未授权模型/Adapter；
- 调试日志不记录原始 KV、Prompt 或凭据；
- 多网卡/RDMA 端口通过网络隔离和节点策略保护。

## 17. 上线清单

- [ ] 已证明单机/共置模式无法更简单地满足目标。
- [ ] 一个多机副本由 LWS/控制器整体创建、调度和发布。
- [ ] 副本内部集中、不同副本跨故障域分散。
- [ ] KV 格式、Connector、引擎和模型版本完整锁定。
- [ ] P/D 两个 Pool 使用联合容量模型和保护机制。
- [ ] 请求取消、Worker 失败和 KV 超时经过演练。
- [ ] 发布不会让新旧不兼容 Worker 随机配对。
- [ ] Trace 能分解路由、Prefill、KV 传输和 Decode。
- [ ] Cache Index/Router 故障时能安全降级。
- [ ] KV Cache 的隐私、网络和租户隔离经过评审。

## 延伸阅读

- [LeaderWorkerSet](https://lws.sigs.k8s.io/)
- [llm-d](https://llm-d.ai/)
- [llm-d Disaggregated Serving](https://llm-d.ai/docs/architecture/advanced/disaggregation)
- [NVIDIA Dynamo Disaggregated Serving](https://docs.nvidia.com/dynamo/latest/user-guides/disaggregated-serving)
- [TensorRT-LLM Disaggregated Serving](https://nvidia.github.io/TensorRT-LLM/features/disagg-serving.html)
- [KServe LLMInferenceService](https://kserve.github.io/website/docs/concepts/architecture/control-plane-llmisvc)

多地域场景应优先在每个集群部署完整推理栈，由全局 Gateway 选择集群，再由集群内 Router/EPP 选择模型副本；TP/PP、P/D 和 KV 传输原则上留在低延迟网络域。详见：[Kubernetes 跨集群与大规模 GPU](../cluster/multi-cluster-ai.md)。
