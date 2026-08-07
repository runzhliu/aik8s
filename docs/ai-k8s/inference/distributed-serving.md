---
title: 多机与分离式 LLM 推理
description: 设计多机模型副本、LeaderWorkerSet、Prefill/Decode 分离和 KV 传输，并对比 AIBrix、llm-d、KServe、Dynamo、Ray Serve 与 vLLM Production Stack
status: evolving
last_reviewed: 2026-08-07
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

### 2.1 用 DeepSeek-V4-Pro 理解“多机副本”和“多个副本” { #deepseek-v4-multi-node-example }

DeepSeek-V4-Pro 很适合说明这两个容易混淆的层次。官方公开规格为 1.6T 总参数、49B 激活参数、1M Context；模型权重采用 FP4 与 FP8 混合精度。vLLM 官方配方估算混合精度 Checkpoint 约 960GB，并给出一个明确的多节点例子：一个 GB200 NVL4 Tray 有 4 张 GPU，单 Tray 放不下该 Checkpoint，因此使用 2 个 Tray、共 8 张 GPU，以 DP + EP 方式共同承载模型。

参考：[DeepSeek-V4 官方发布](https://api-docs.deepseek.com/news/news260424/)、[DeepSeek-V4 开放权重](https://huggingface.co/collections/deepseek-ai/deepseek-v4)、[vLLM DeepSeek-V4-Pro Recipe](https://github.com/vllm-project/recipes/blob/main/models/deepseek-ai/DeepSeek-V4-Pro.yaml)

这 2 个节点、8 张 GPU 在平台层首先是**一个完整模型副本**：

```text
DeepSeek-V4-Pro Replica A
  Leader / API Endpoint
    ├── GB200 NVL4 Tray A1：4 GPU
    └── GB200 NVL4 Tray A2：4 GPU
        └── vLLM DP + Expert Parallel 通信域
```

调度器需要一次性为整个组准备节点、GPU、网络和模型数据；任何必要 Rank 未 Ready 时，Replica A 都不应进入外部 Endpoint。Higress 或 AIBrix 也不应该把用户请求直接发送给某个 Worker Pod，只能访问这个组的 Leader/API Service。

当企业为了吞吐和可用性再部署一组相同资源时，才出现“多个完整副本”：

```text
逻辑模型 deepseek-v4-pro
  ├── Replica A：2 Tray / 8 GPU
  └── Replica B：2 Tray / 8 GPU
```

这时有两次不同的调度：

1. Kubernetes、Kueue 和 StormService/RoleSet、LeaderWorkerSet 或 KubeRay 决定每个 8-GPU 组如何整体落到节点；
2. AIBrix Gateway 决定一次 `model=deepseek-v4-pro` 请求进入 Replica A 还是 B，不能把 A/B 内部 Worker 混成普通 Endpoint 池。

如果只有 Replica A，一个稳定 Leader Service 就足够承接流量，AIBrix 的“选副本”价值有限；如果有 A/B 多组、P/D 两类 Pool、长上下文导致的显著队列差异，或希望做 KV/Session 感知，内部推理路由才开始成为必要能力。

硬件数字不能直接照搬。vLLM 同一配方也给出 8×B300、8×H200 和其他平台的不同参数；实际节点数取决于 GPU 显存、权重精度、Context/并发产生的 KV Cache、Runtime 版本和并行策略。上线前必须按目标硬件复测，而不是由“1.6T 参数”直接推导节点数量。

### 2.2 除了 DeepSeek-V4，还有哪些现成例子 { #other-vllm-aibrix-multi-node-examples }

先区分三种“支持”，否则很容易把模型列表写成已经跑通的生产案例：

1. **AIBrix 官方端到端样例**：仓库里有编排、标签、Service 和路由清单；
2. **vLLM 官方多机配方**：模型和多机并行策略有上游依据，但需要把 Runtime 接入 AIBrix；
3. **理论上兼容 OpenAI API**：只能说明 AIBrix 可以发现和转发，不能证明多机通信、P/D 或扩缩容已经验证。

截至 2026 年 8 月，AIBrix 仓库里最值得直接参考的三套样例是：

| 官方样例 | 证明了什么 | 适合怎么用 | 不能直接照搬的部分 |
| --- | --- | --- | --- |
| [DeepSeek-R1 671B](https://github.com/vllm-project/aibrix/tree/v0.7.0/samples/deepseek-r1) | 2 个节点、16×H20 96GB、RayClusterFleet、vLLM TP16、Head-only Service、路由、自动扩缩和监控 | 大模型跨节点完整副本的主要蓝本 | 样例基于旧版 vLLM 0.7.3 定制镜像和特定云 RDMA；存储、NIC、镜像和版本必须重做 |
| [Qwen2.5-Coder-7B 两节点](https://github.com/vllm-project/aibrix/blob/v0.7.0/samples/distributed/fleet-two-node.yaml) | RayClusterFleet 建立 1 个 Head GPU + 1 个 Worker GPU，vLLM TP2，AIBrix 只把请求送给 Head | 用小模型验证 KubeRay、Fleet、Service 和 Gateway 控制链 | 启动时执行 `apt`/`pip`，且使用 vLLM 0.7.1；它是教程，不是生产镜像模板 |
| [Qwen3-8B P/D](https://github.com/vllm-project/aibrix/tree/v0.7.0/samples/disaggregation/vllm) | StormService 的 Replica/Pool 两种模式、2 Prefill + 1 Decode、NIXL 传输和 `routing-strategy: pd` | 验证 Prefill/Decode 角色编排与动态路由 | 这不是“大模型跨节点装载”样例；RDMA 注解、NIXL 镜像和 NCCL 参数带有环境假设 |

真正的大模型候选不只 DeepSeek。下表中的模型都在 [vLLM 官方 Recipes](https://github.com/vllm-project/recipes) 中明确声明兼容 `multi_node_tp`、`multi_node_tp_pp`、分布式 Expert Parallel 和 `pd_cluster`，因此适合把 vLLM Leader/API Endpoint 接到 AIBrix：

| 开放权重模型 | 规模与上下文 | vLLM 最低版本 | 配方中的典型权重显存 | 更适合验证什么 |
| --- | --- | --- | --- | --- |
| [DeepSeek-R1](https://github.com/vllm-project/recipes/blob/main/models/deepseek-ai/DeepSeek-R1.yaml) | 671B / 37B 激活，163K | 0.12.0 | FP8 约 805GB；NVFP4 约 403GB | AIBrix 已有 671B 多机蓝本，适合作为 V4 之外证据最完整的基线 |
| [Qwen3-235B-A22B-Instruct](https://github.com/vllm-project/recipes/blob/main/models/Qwen/Qwen3-235B-A22B-Instruct-2507.yaml) | 235B / 22B 激活，262K | 0.10.0 | FP8 约 240GB；NVFP4 约 141GB | 资源门槛相对低，适合第一套真实 MoE 多机、EP 和长上下文验证 |
| [Qwen3-Coder-480B-A35B](https://github.com/vllm-project/recipes/blob/main/models/Qwen/Qwen3-Coder-480B-A35B-Instruct.yaml) | 480B / 35B 激活，262K | 0.10.0 | FP8 约 576GB；NVFP4 约 288GB | 代码与 Agent 请求、Tool Calling、长上下文以及多副本路由 |
| [GLM-4.7](https://github.com/vllm-project/recipes/blob/main/models/zai-org/GLM-4.7.yaml) | 358B / 32B 激活，202K | 0.11.0 | FP8 约 430GB；NVFP4 约 215GB | 中文、推理与 Tool Calling，且可验证 MTP 推测解码 |
| [Qwen3.5-397B-A17B](https://github.com/vllm-project/recipes/blob/main/models/Qwen/Qwen3.5-397B-A17B.yaml) | 397B / 17B 激活，262K | 0.17.0 | NVFP4/GPTQ Int4 约 238—239GB | 新版多模态/推理模型，但 Runtime 与连接器版本门槛更高 |
| [Kimi-K2.5](https://github.com/vllm-project/recipes/blob/main/models/moonshotai/Kimi-K2.5.yaml) | 1T / 32B 激活，262K | 0.19.1 | INT4 约 714GB；NVFP4 约 600GB | 超大 MoE、多模态、P/D 和大规模 Expert Parallel；成本最高的一档 |
| [MiniMax-M2.5](https://github.com/vllm-project/recipes/blob/main/models/MiniMaxAI/MiniMax-M2.5.yaml) | 230B / 10B 激活，196K | 0.20.2 | FP8 约 276GB；NVFP4 约 138GB | 用较低权重门槛验证多机和 P/D；部分硬件上单机已能容纳，不要为了多机而多机 |
| [Mistral Large 3 675B](https://github.com/vllm-project/recipes/blob/main/models/mistralai/Mistral-Large-3-675B-Instruct-2512.yaml) | 675B / 22B 激活，294K | 0.11.0 | FP8 约 810GB；NVFP4 约 405GB | 国际开放权重模型、多语言和长上下文，多机 TP/PP/EP 与 P/D |

表中的显存只是配方对**权重变体**给出的最低量级，不包含目标并发所需的全部 KV Cache、CUDA Graph、通信 Buffer 和安全余量；也不等于推荐 GPU 数。尤其 NVFP4 通常要求 Blackwell 原生能力，不能只看总显存相加。

### 2.3 模型接入 AIBrix 的正确边界

AIBrix 并没有一张只允许特定模型的白名单。对普通共置式 vLLM 服务，至少要保证：

- Pod 带有一致的 `model.aibrix.ai/name` 和 `model.aibrix.ai/port`；
- vLLM 的 `--served-model-name`、请求体 `model`、Service 与路由配置一致；
- Service 只选择一个完整副本的 Leader/API Pod，不能选中内部 Headless Worker；
- Readiness 只有在所有必要 Rank 和模型都可服务后才成功；
- AIBrix Gateway 在多个**完整副本**之间选路，组内 Rank 由 RayClusterFleet、StormService/RoleSet、LWS 或 Runtime 管理。

非 P/D 场景中，AIBrix Gateway 与 vLLM 引擎版本的耦合相对较弱，新版 vLLM 只要保持兼容 API、指标和发现标签，通常可以先作为普通模型 Endpoint 接入。P/D、KV Offload、NIXL Connector 和 Runtime Sidecar 则位于数据路径上，版本耦合很强。Qwen3.5、Kimi-K2.5、MiniMax-M2.5 等配方要求的 vLLM 0.17—0.20 已明显新于 AIBrix v0.7.0 示例镜像，必须重新构建镜像并验证 KV Connector、NIXL、CUDA/NCCL 和指标，而不能只替换 `model` 字段。

推荐按风险递增落地：

1. 先用 Qwen2.5-Coder-7B 两节点样例证明 RayClusterFleet 和 Head-only 路由；
2. 用 Qwen3-8B 证明 StormService 与 P/D 控制链，但暂不据此宣称性能收益；
3. 第一套真实大模型优先选择 Qwen3-235B-A22B FP8，或复现证据更完整的 DeepSeek-R1 671B；
4. 再加入第二个完整副本，验证 AIBrix 的队列、Prefix/Session 感知、故障摘除和扩缩；
5. 最后才测试 Kimi-K2.5 等 1T 模型以及跨节点 P/D，并用 TTFT、TPOT、Goodput 和故障恢复时间决定是否上线。

### 2.4 AIBrix 的两条编排路线

AIBrix 既可以用 `RayClusterFleet` 管理多个完整 RayCluster 副本，也可以用 `StormService → RoleSet → Pod` 直接表达 Prefill、Decode 或其他角色。`RoleSet` 不是与前两者平级的第三种方案，而是 StormService 管理的下一层资源。

这里只建立概念边界：已经使用 Ray 时通常优先 RayClusterFleet；需要 P/D 分离、角色级弹性或想去掉 Ray 时通常优先 StormService。CRD 层级、依赖、Endpoint、扩缩、更新和故障边界的完整对比，以及裸 Kubernetes 的替代做法，统一放在 [AIBrix 实战中的编排方案选型](../practices/aibrix-existing-cluster.md#rayclusterfleet-vs-stormservice)。

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

当前 vLLM 多节点既可以用 Ray，也支持原生 MultiProcessing 的 `--nnodes`、`--node-rank` 和 `--headless` 模式。Ray 是分布式执行 Backend，不是多机推理本身唯一的并行算法；TP、PP、DP、EP 才决定模型计算如何拆分。

参考：[vLLM Parallelism and Scaling](https://docs.vllm.ai/en/latest/serving/parallelism_scaling/)

### 5.1 vLLM Ray 多机与 P/D 分离是什么关系 { #vllm-ray-vs-pd }

它们是两个正交维度：

- **vLLM Ray 多机**回答：一套 vLLM Engine 如何把**同一个模型副本**的计算拆到多张 GPU、多个节点；
- **P/D 分离**回答：一次请求的 Prefill 和 Decode 是否交给**两套独立 vLLM Engine**，以及如何把 KV Cache 从前者交给后者。

最重要的认知是：**Ray Worker 不是 Decode Worker。** 普通 Ray 多机模式中的 Head/Worker Rank 会共同参与同一个 Engine 的 Prefill 和 Decode；P/D 模式中的 Prefill、Decode 则是两个具有独立 Scheduler、Batch、KV Cache 和 Endpoint 的引擎。

#### 5.1.1 只有 Ray，没有 P/D

```text
Client
  → vLLM API / Ray Head
      → 同一个 vLLM Engine
          ├─ Ray Rank 0：GPU/权重分片
          ├─ Ray Rank 1：GPU/权重分片
          └─ Ray Rank 2：GPU/权重分片
             所有 Rank 共同执行 Prefill 和 Decode
```

这里模型通过 TP/PP/EP 跨 GPU 放置。一次请求从开始到结束都属于同一个 Engine；Rank 之间会在层、Token 或 Expert 计算中持续进行 Collective、Activation 或 Pipeline 通信。Ray 负责进程放置和执行协调，vLLM 仍负责推理 Scheduler。

#### 5.1.2 只有 P/D，没有 Ray

```text
Client
  → P/D Router
      → Prefill vLLM Instance：加载模型，计算 Prompt 和初始 KV
          → NIXL/LMCache/Mooncake 等 Connector 传输 KV
      → Decode vLLM Instance：也加载模型，接收 KV 后逐 Token 生成
```

两端可以各自只使用一张 GPU，也可以使用单机多卡 MultiProcessing。P/D 不要求 Ray，但要求 P/D-aware Router、KV Connector、Peer 发现以及兼容的模型、KV Layout 和 Engine 版本。Prefill 和 Decode 都不是“只装半个模型”：两边都要具备执行相应阶段所需的完整逻辑模型能力，因此通常会形成两份权重容量，只是每份内部仍可分片。

#### 5.1.3 Ray 与 P/D 可以组合

```text
Client
  → P/D Router
      → Prefill Engine（RayCluster P）
          ├─ P-Head
          └─ P-Worker × N
              → 跨 Engine 传输 KV
      → Decode Engine（RayCluster D）
          ├─ D-Head
          └─ D-Worker × M
```

这时 Ray 解决 P、D **各自内部**的模型并行，P/D Router 与 Connector 解决两个 Engine **之间**的请求切换和 KV 交接。Prefill、Decode 可以使用不同 TP/PP 形状，但只有 KV Connector 的 TP Mapping 和兼容矩阵明确支持时才能这样配置，不能任意组合。

AIBrix v0.7.0 的官方例子分别展示了 RayClusterFleet 多机和 StormService P/D，尚不是一份可直接套用的“RayClusterFleet 嵌套 StormService”清单。企业如果需要上图的组合，应把它当作高级集成：分别管理 P/D 分布式 Engine，只向 Router 暴露各自的 Leader/API Endpoint，并单独验证发现、配对、KV 传输和故障恢复。

#### 5.1.4 异同对照

| 维度 | vLLM Ray 多机 | P/D 分离 |
| --- | --- | --- |
| 拆分对象 | 一个模型副本内部的 Rank、权重和计算 | 一次请求的两个执行阶段 |
| Engine 数量 | 通常 1 个 Engine，多个 Ray Rank | 至少 2 个独立 Engine：Prefill 与 Decode |
| 模型权重 | 按 TP/PP/EP 在 Rank 间分片 | P、D 两边都要加载模型；每边内部可以再次分片 |
| 请求 Scheduler | 一个 vLLM Scheduler 管完整请求 | P、D 各有 Scheduler，还需要外层 P/D Router |
| 主要数据通信 | Rank 间频繁传 Activation、Collective 或 Expert 数据 | 阶段切换时跨 Engine 传 KV Cache，Engine 内仍可能有 TP/PP 通信 |
| 主要目的 | 模型单机放不下、使用更多 GPU 加速一个副本 | 分别优化 TTFT 与 ITL、隔离长 Prompt 对 Decode 的干扰 |
| 扩缩方式 | 增加完整 RayCluster 副本；改变 Rank 数通常需要重建并重新加载模型 | Prefill、Decode Pool 可以按各自负载独立扩缩 |
| 故障影响 | 任一必要 Rank 故障可能让整个模型副本不可服务 | Prefill/Decode 或 KV 交接失败会影响请求阶段，还要清理孤儿 KV |

四种常见组合可以快速判断架构：

| 组合 | 是否合理 | 典型场景 |
| --- | --- | --- |
| 单机 vLLM，共置 P/D | 是，默认起点 | 模型与 SLO 单机可满足 |
| Ray 多机，共置 P/D | 是 | 模型单机放不下，但还不需要阶段池化 |
| 单机/单节点 P Pool + D Pool | 是 | 模型单实例可容纳，但希望隔离 TTFT/ITL 并独立扩缩 |
| 多机 Ray P Pool + 多机 Ray D Pool | 可以，但最复杂 | 超大模型且确实需要 P/D，网络、Connector 和运维能力成熟 |

不要因为已经用了 Ray 就自然引入 P/D。vLLM 当前官方文档明确把 P/D 的主要价值描述为分别调优 TTFT/ITL、控制尾部 ITL，并提醒它**不会自动提高原始吞吐**。平台层可能通过独立配比获得更高的 SLO Goodput 或利用率，但必须让收益覆盖 KV 传输、双份权重、额外 Router 和故障面的成本。

参考：[vLLM Disaggregated Prefilling](https://docs.vllm.ai/en/stable/features/disagg_prefill/)、[NixlConnector Usage Guide](https://docs.vllm.ai/en/stable/features/nixl_connector_usage/)、[NixlConnector Compatibility Matrix](https://docs.vllm.ai/en/stable/features/nixl_connector_compatibility/)

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

## 12. AIBrix 之外还有哪些选择

先区分三层，避免把推理引擎、Kubernetes 编排组件和完整推理控制面当作同类产品：

```text
平台控制面：AIBrix / llm-d / KServe / Ray Serve / Dynamo
集群编排层：Kubernetes / LeaderWorkerSet / KubeRay
推理执行层：vLLM / SGLang / TensorRT-LLM
```

一个平台经常同时采用三层组件。例如 KServe 负责服务生命周期，LeaderWorkerSet 表达跨节点副本，vLLM 执行模型计算；它们不是互相替代的三个产品。

| 项目 | 主要定位 | 多机多卡与分离式推理能力 | 更适合的场景 |
| --- | --- | --- | --- |
| AIBrix | Kubernetes LLM 推理控制面 | Gateway、模型感知路由、Autoscaling、LoRA、KV Cache 和 P/D 等能力 | 希望建设包含流量、模型和弹性管理的通用推理平台 |
| llm-d | Kubernetes 原生分布式推理栈 | InferencePool/EPP、Prefix/KV-aware Routing、KV 索引与卸载、P/D 分离 | 重点优化大规模请求调度、KV 命中率和分离式推理，可作为 AIBrix 的重点对标对象 |
| KServe LLMInferenceService | 模型服务 CRD 和生命周期控制面 | 通过 LeaderWorkerSet 表达跨节点副本，支持 Tensor/Data/Expert Parallelism，并组合 Gateway 和 Autoscaler | 已有 KServe，希望统一模型服务 API、发布和弹性治理 |
| NVIDIA Dynamo | NVIDIA 高性能分布式推理框架 | Frontend、Router、Prefill/Decode Pool、KV-aware Routing、NIXL/RDMA 数据路径 | NVIDIA GPU 和高速网络完备，优先追求 P/D、KV 传输和极限性能 |
| Ray Serve LLM + KubeRay | 可编程分布式应用与服务平台 | 跨节点 TP/PP/EP、P/D 分离、模型感知路由和副本弹性 | 已使用 Ray Data/Train/Jobs，希望把数据、训练、评测和推理放在同一运行时 |
| vLLM Production Stack | vLLM 官方 Kubernetes 生产部署栈 | 多 Serving Engine、Router、Prefix/KV-aware Routing、P/D、KEDA、LoRA 和监控 | 已确定使用 vLLM，希望以较小平台成本快速上线 |
| SGLang 与其 Router/Model Gateway | 高性能推理引擎及路由能力 | 多节点并行、Radix Cache、P/D 分离和多种路由策略 | 重视 SGLang 引擎能力，并愿意自行组合 Kubernetes 生命周期和治理组件 |
| LeaderWorkerSet | 多 Pod 组成一个逻辑副本的 Kubernetes API | 统一创建、扩缩和更新 Leader/Worker Pod 组 | 给 KServe、llm-d 或自研控制面提供多机副本编排；它不是完整推理平台 |

### 12.1 选型结论

- 寻找与 AIBrix 定位最接近的开源方案：优先评估 **llm-d**；
- 已有 KServe 平台：使用 **KServe LLMInferenceService + LeaderWorkerSet**；
- NVIDIA GPU、RDMA 和拓扑条件成熟：测试 **Dynamo + TensorRT-LLM/vLLM**；
- 数据处理、训练和推理已经大量使用 Ray：选择 **KubeRay + Ray Serve LLM**；
- 想先让 vLLM 生产化，不急于建设统一控制面：从 **vLLM Production Stack** 起步；
- 需要自研企业推理平台：可组合 **Gateway API + llm-d Router/EPP + KServe/LWS + vLLM/SGLang**，但必须明确每个资源只有一个生命周期和扩缩控制器。

参考：[llm-d Architecture](https://llm-d.ai/docs/0.7/architecture)、[KServe LLMInferenceService](https://kserve.github.io/website/docs/model-serving/generative-inference/llmisvc/llmisvc-configuration)、[Ray Serve LLM](https://docs.ray.io/en/latest/serve/llm/index.html)、[vLLM Production Stack](https://github.com/vllm-project/production-stack)、[SGLang](https://github.com/sgl-project/sglang)

## 13. 双池容量规划

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

## 14. 发布与版本

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

## 15. 故障语义

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

## 16. 可观测性

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

## 17. 安全

- KV Cache 可能包含可还原的用户上下文，按敏感数据处理；
- Prefill 与 Decode 之间使用网络身份、加密或受控数据平面；
- 不同租户的 KV Index 和 Cache 访问边界明确；
- Worker 不对公网暴露；
- Router 不能把请求送到未授权模型/Adapter；
- 调试日志不记录原始 KV、Prompt 或凭据；
- 多网卡/RDMA 端口通过网络隔离和节点策略保护。

## 18. 上线清单

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
