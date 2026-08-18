---
title: GLM-5.2 FP8 在 H20 上的 vLLM、SGLang 与 P/D RDMA 实测
description: 记录 GLM-5.2 FP8 单节点 TP=8 的 vLLM 与 SGLang 基线，以及双节点 P/D 分离下 TCP 和 RDMA 的 KV 传输与端到端性能对比
status: exploratory
last_reviewed: 2026-08-18
---

# GLM-5.2 FP8 在 H20 上的 vLLM、SGLang 与 P/D RDMA 实测

这次实验回答一个具体问题：GLM-5.2 FP8 是否一定要用 SGLang，还是可以直接使用 AIBrix + vLLM，在一台 `8 × H20 141 GB` 节点上提供 OpenAI-compatible 服务？

结论是可以。模型已使用标准 `vllm serve`、单节点 TP=8 启动，经 AIBrix Gateway 完成确定性中文请求和四组基准测试，并被 OpenWebUI 现有的 AIBrix 连接自动发现。本文所有集群名称、Namespace、节点地址、存储地址、镜像仓库和凭据均已删除或替换为占位符。

这只是功能正确且可复现的 vLLM 基线，不是最终性能结论。本轮没有启用 MTP/DSpark，使用的通用镜像也未发现可独立导入的 DeepGEMM 包，不能把结果直接与官方优化配置或此前其他模型的推测解码数据比较。

随后我们又用相同 FP8 Checkpoint、相同节点和 TP=8 启动了隔离的 SGLang 0.5.16b1 实例。第三轮在限制模型加载并发、为启动探针保留 60 分钟窗口后成功 Ready，最小确定性请求得到正确结果。它证明 SGLang 能在这套硬件上运行该 FP8 Checkpoint，但尚未形成与 vLLM 参数严格对齐的性能 A/B。

在单节点基线之后，我们还增加了两个 `8 × H20 141 GB` 节点上的 vLLM P/D 分离实验：Prefill 和 Decode 各自使用 TP=8，通过 NIXL 传递 KV Cache，并在保持模型、节点、路由和压测负载不变的前提下只切换 UCX 的 TCP 与 RDMA 数据面。结果显示，RDMA 将 NIXL 的 Rank 聚合传输速率提高约 21.9 倍，并在 4K Prompt 场景提高约 22% 输出吞吐；但短 Prompt、并发 8 的尾延迟明显回退，因此不能把“KV 传得更快”直接等同于“所有请求都更快”。

## 1. 为什么单机八卡能够放下

[vLLM 官方 GLM-5.2 Recipe](https://github.com/vllm-project/recipes/blob/main/models/zai-org/GLM-5.2.yaml) 给出的模型规模约为 743B 总参数、39B 激活参数，原生 FP8 权重最低显存需求约 893 GB，并明确列出 `8 × H200/H20 141GB` 单节点方案。

八张 141 GB H20 的标称显存合计约 1.1 TB。TP=8 后，每个 Rank 不只是保存约八分之一的权重，还要为 KV Cache、CUDA Graph、通信缓冲区和框架运行时留出空间。本次观测如下：

| 项目 | 实测或配置 |
| --- | ---: |
| GPU | 8 × NVIDIA H20 141 GB |
| TP | 8 |
| 权重分片 | 141 个 Safetensors |
| vLLM 报告的单 Rank 模型加载内存 | 89.93 GiB |
| 启动稳定后的单卡显存 | 约 132 GiB |
| 单 Rank 可用 KV Cache | 25.37 GiB |
| GPU KV Cache 容量 | 504,960 tokens |
| 131,072 上下文下估算最大并发 | 3.85× |

标称容量相减只能回答“是否有机会放下”，不能代替启动实测。尤其不能把 39B 激活参数误当成全部权重规模；MoE 推理时每个 Token 只激活部分专家，但完整服务仍需保存模型需要的专家权重。

## 2. 部署结构与版本检查

本轮没有使用 SGLang，也没有调用镜像中的二次封装 `start.sh`。AIBrix 负责模型发现和请求路由，vLLM 负责模型加载、TP=8 和生成：

```text
OpenWebUI / benchmark client
              │
              ▼
        AIBrix Gateway
              │
              ▼
   HTTPRoute → DNS-safe Service
              │
              ▼
       vLLM Pod, TP=8
              │
              ▼
  8 × H20 141 GB + 共享模型目录
```

实际容器版本为 vLLM `0.26.0b2.dev1`、Transformers `5.14.1`。部署前先验证了以下三点：

1. vLLM 模型注册表包含 `GlmMoeDsaForCausalLM`；
2. 共享目录能够读到模型配置、Tokenizer、索引和全部 141 个权重分片；
3. 镜像中未发现可独立导入的 `deep_gemm`/`deepgemm` 包，因此把它定义为通用兼容性基线，而不是官方 H20 极致性能镜像。

标准启动命令如下，模型路径和镜像应替换为目标环境中的实际值：

```bash
vllm serve /models/GLM-5.2-FP8/v1 \
  --host 0.0.0.0 \
  --port 8000 \
  --tensor-parallel-size 8 \
  --served-model-name glm-5.2-fp8-vllm \
  --kv-cache-dtype fp8 \
  --gpu-memory-utilization 0.90 \
  --max-model-len 131072 \
  --max-num-seqs 16 \
  --max-num-batched-tokens 32768 \
  --tool-call-parser glm47 \
  --reasoning-parser glm45 \
  --enable-auto-tool-choice \
  --enable-prefix-caching
```

资源清单还需要显式申请八张 GPU，并根据目标节点的隔离策略配置 `nodeSelector`、`affinity` 和精确的 `tolerations`。不要为绕过调度而使用覆盖面过大的 `Exists` 容忍；它容易把实验 Pod 放进非预期的隔离节点。

## 3. 一个容易踩中的 AIBrix 路由命名问题

模型名使用 `glm-5.2-fp8-vllm` 时，AIBrix Gateway Plugin 会按 `<model-name>-router` 查找 HTTPRoute，即：

```text
glm-5.2-fp8-vllm-router
```

HTTPRoute 名称允许句点，但 Kubernetes Service 采用更严格的 DNS-1035 标签，不能照搬带句点的模型名。若让自动化同时用模型名创建 Service，或者删除约定名称的 Route 后另建一个任意名称的 Route，可能分别遇到 Service 创建失败或 Gateway 返回 503。

本轮验证有效的命名方式是：

```yaml
modelName: glm-5.2-fp8-vllm
httpRouteName: glm-5.2-fp8-vllm-router
serviceName: glm52-fp8-vllm-aibrix
```

Route 保留 AIBrix 约定名称，`backendRefs` 则指向 DNS-safe Service。跨 Namespace 时再由 `ReferenceGrant` 精确授权该 Service。修正后，HTTPRoute 的 `Accepted` 和 `ResolvedRefs` 均为 `True`，`/v1/completions` 与 `/v1/chat/completions` 都返回 200。

## 4. 冷启动时间花在哪里

这次是镜像未命中、模型通过共享文件系统挂载的冷启动。Pod 创建到模型 Ready 约 17 分钟：

| 阶段 | 实测 |
| --- | ---: |
| 首次拉取约 13.1 GB 镜像 | 2 分 18 秒 |
| 加载 141 个权重分片 | 386.50 秒 |
| vLLM 报告的模型加载阶段 | 391.78 秒 |
| `torch.compile` | 104.56 秒 |
| 初始 Profiling / Warm-up | 38.42 秒 |
| Pod 创建至 Ready | 约 17 分钟 |

这些分项不能机械相加：容器创建、存储挂载、进程初始化、最终 32K Token CUDA Graph Warm-up 之间存在前后依赖，也有日志口径重叠。真正应该用于 SLO 的是 `Pod created → first correct response`，而不是单独截取 `weights loaded`。

本轮编译缓存放在 `emptyDir`，Pod 重建后不会复用。这意味着镜像命中只能省掉拉取时间，仍会重新读权重、编译和预热。后续若要压缩滚动更新时间，应分别验证节点 NVMe 模型缓存、持久化且带兼容性指纹的编译缓存，以及预热完成后再接流量。

## 5. 正确性与 OpenWebUI 接入

验证按三层进行：

1. 直连 vLLM Pod，确定性中文请求返回预期文本；
2. 经 AIBrix Gateway 请求，响应携带实际目标 Pod 的路由信息，且文本正确；
3. 从 OpenWebUI 所在 Pod 使用其已经配置的 AIBrix OpenAI-compatible 地址请求，模型出现在 `/v1/models` 中，中文对话返回预期文本。

因此，这里的“注册到 OpenWebUI”不需要为每个模型再修改一次 OpenWebUI Deployment。只要 OpenWebUI 已经连接 AIBrix 的 `/v1` 地址，AIBrix 能发现新模型并正确路由，OpenWebUI 就会通过模型列表自动看到它。本轮没有重启 OpenWebUI，也避免了无意义的配置扰动。

若模型没有出现，应按下面顺序排查：

```text
vLLM /v1/models
  → AIBrix /v1/models
  → HTTPRoute Accepted / ResolvedRefs
  → OpenWebUI 使用的 Base URL
  → OpenWebUI 持久化配置是否覆盖环境变量
```

## 6. 与此前一致的四组压测

压测客户端位于模型 Pod 内，但所有请求均发送到 AIBrix Gateway，而不是直连本地端口。使用 `vllm bench serve`、random dataset、`temperature=0`、`ignore-eos` 和无限请求到达速率；每组先做独立 Warm-up，再采集正式结果。

表中的 `C` 是客户端最大并发请求数。它不是总用户数，也不是服务端 Batch Size。

| 场景 | 请求成功 | req/s | 输出 tok/s | p50/p95/p99 TTFT | p95 TPOT | p95 ITL | p95 E2EL |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 128 in / 64 out，C=1 | 16/16 | 1.02 | 65.24 | 216 / 225 / 225 ms | 12.13 ms | 14.02 ms | 989 ms |
| 128 in / 64 out，C=4 | 32/32 | 2.44 | 156.41 | 577 / 743 / 755 ms | 22.86 ms | 17.35 ms | 1,680 ms |
| 128 in / 64 out，C=8 | 64/64 | 3.42 | 218.80 | 442 / 3,239 / 3,241 ms | 52.46 ms | 22.62 ms | 4,514 ms |
| 4096 in / 128 out，C=4 | 16/16 | 0.64 | 81.99 | 4,411 / 4,416 / 4,417 ms | 40.52 ms | 17.39 ms | 6,321 ms |

四组请求均无失败。短请求从 C=1 增至 C=8，总输出吞吐提高约 3.35 倍，但 p95 TTFT 从约 225 ms 增至 3.24 秒，p95 TPOT 从 12.13 ms 增至 52.46 ms。当前配置在并发 8 时已经明显用单请求尾延迟换取总吞吐。4K 输入的 p95 TTFT 为 4.42 秒，Prefill 成为主要延迟来源。

单请求场景的输出吞吐为 65.24 tok/s，但 p95 TPOT 12.13 ms 对应稳定 Decode 阶段约 82 tok/s；二者口径不同，前者把 TTFT 和整轮持续时间计算在内，不能混为同一个数字。

### 6.1 两节点 P/D：TCP 与 RDMA 对照

单节点基线回答了模型能否放下以及普通共置服务的性能范围，下一步要验证的是：当 Prefill 和 Decode 分别占用一个完整八卡节点时，RDMA 加速 KV Cache 传输能否转化为端到端收益。

实验拓扑如下。这里有两份完整模型实例，而不是把一个 TP=16 Engine 拆成两个角色：

```text
Benchmark Client
       │
       ▼
 AIBrix P/D Router
       │
       ├─ Prefill：Node A，8 × H20 141 GB，TP=8
       │       │
       │       └─ NIXL + UCX：传输 KV Cache
       │                         │
       └─ Decode：Node B，8 × H20 141 GB，TP=8
```

主要软件与参数如下。模型权重的分发方式、集群标识、节点地址、镜像仓库、Namespace 和入口配置均不属于本文公开范围：

| 项目 | 配置 |
| --- | --- |
| 模型 | GLM-5.2 FP8，同一 Revision |
| GPU | 两个节点，每节点 8 × H20 141 GB，共 16 张 |
| Engine | vLLM 0.26.0，Prefill TP=8、Decode TP=8 |
| KV Connector | NIXL 1.3.2，FP8 KV Cache，失败时允许 Recompute |
| P/D 路由 | AIBrix 0.7.0，固定 Prefill/Decode 角色配对 |
| 上下文与批处理 | 131,072；`max_num_seqs=16`；`max_num_batched_tokens=32768` |
| RDMA 组 | `UCX_TLS=rc,cuda_copy,cuda_ipc`，8 路 ConnectX-7 |
| TCP 对照组 | `UCX_TLS=tcp,cuda_copy,cuda_ipc` |

对照实验只改变 `UCX_TLS`，不改变节点、GPU、模型、路由、压测客户端和 vLLM 参数。TCP 组的 Pod 仍能发现 RDMA 设备，但 UCX 被限制为 TCP；测试前后 RDMA 端口计数完全不变，避免了“名义上配置 TCP、实际仍走 RDMA”的伪对照。

压测仍使用 `vllm bench serve`、精确随机长度、`temperature=0`、`ignore-eos` 和无限请求到达速率。每组先以相同并发完成 Warm-up，再使用两个不同 Seed 各运行一轮：C=1 为每轮 16 个请求，C=4 为 32 个请求，C=8 为 64 个请求，4K 输入为 16 个请求。TCP 与 RDMA 合计 512 个正式请求，失败数为 0。

下面是两轮中相同指标的算术平均。这里的 p95 是“两次独立 p95 的平均值”，不是把两轮原始样本合并后重新计算的 p95；小样本尾延迟只能用于识别趋势，不能替代长时间稳定性测试。

| 场景 | TCP 输出 tok/s | RDMA 输出 tok/s | 吞吐变化 | TCP p95 TTFT | RDMA p95 TTFT | TTFT 变化 | TCP p95 E2EL | RDMA p95 E2EL | E2EL 变化 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 128 in / 64 out，C=1 | 58.39 | 60.22 | +3.1% | 566 ms | 479 ms | -15.3% | 1,326 ms | 1,239 ms | -6.5% |
| 128 in / 64 out，C=4 | 177.55 | 177.29 | -0.1% | 1,445 ms | 1,597 ms | +10.5% | 2,375 ms | 2,530 ms | +6.5% |
| 128 in / 64 out，C=8 | 287.89 | 255.85 | -11.1% | 786 ms | 2,806 ms | +257.2% | 2,076 ms | 4,079 ms | +96.5% |
| 4096 in / 128 out，C=4 | 77.89 | 95.03 | **+22.0%** | 6,279 ms | 4,531 ms | **-27.8%** | 8,166 ms | 6,597 ms | **-19.2%** |

C=1 和 C=4 的两轮尾延迟都有明显波动，不能据此宣称稳定收益。C=8 的 RDMA 回退和 4K Prompt 的 RDMA 收益则在两轮中方向一致：

- 对短 Prompt 高并发，KV 数据量较小，路由、批处理、P/D 同步、连接状态和队列抖动足以覆盖网络收益；当前 C=8 结果说明该配置仍需调优；
- 对 4K Prompt，Prefill 产生的 KV 更多，网络传输更容易进入关键路径。RDMA 把 p95 TTFT 降低约 28%，最终带来约 22% 输出吞吐和约 19% p95 E2EL 收益；
- TPOT 主要描述 Decode 稳态阶段，本轮两次 4K 测试的 TPOT 方向并不完全一致。RDMA 优化的是 Prefill 后的 KV 传输，不能预期它稳定改善每 Token Decode 时间。

### 6.2 如何证明数据面真的经过 RDMA

只看到 P/D 两个 Pod 都收到 HTTP 请求，不能证明 KV Tensor 已经通过 RDMA 传输。本轮同时核对 NIXL 指标与八个 RDMA 端口的硬件计数：

| 同规模完整轮次 | NIXL 传输数据 | NIXL 累计 `xfer_time` | Rank 聚合有效速率 |
| --- | ---: | ---: | ---: |
| TCP | 约 32.81 GB | 136.284 s | 约 0.241 GB/s |
| RDMA | 33.25 GB | 6.295 s | 约 5.28 GB/s |

按这个口径，RDMA 的 NIXL Rank 聚合有效传输速率约为 TCP 的 **21.9 倍**。需要特别说明：`bytes / sum(xfer_time)` 汇总了八个 TP Rank，是用于同拓扑 A/B 的框架指标，不是单张网卡的物理线速。RDMA 轮次中，八路端口发送计数合计增加约 38.18 GB，方向与 NIXL 指标一致；TCP 轮次完成全部请求后，RDMA 端口计数保持不变。两种传输均未记录失败。

最后还直连 Decode 实例，在不提供远端 `kv_transfer_params` 的情况下让它本地计算 Prompt。`128 in / 64 out，C=1` 得到 65.58 输出 tok/s、p95 TTFT 220 ms、p95 E2EL 981 ms，NIXL 传输计数没有增长，与第 6 节的 65.24 tok/s、225 ms、989 ms 基本一致。这个检查证明此前单机基线仍可作为方向性参照；但该进程仍加载了 NIXL Connector 并使用 Recompute 回退，不应包装成一个全新、完全独立的纯共置 Engine A/B。

这组数据最重要的结论不是“RDMA 一定更快”，而是：**RDMA 已经把大块 KV 传输从明显瓶颈降为较小成本，但端到端收益取决于 Prompt 长度、并发、P/D 容量比例和调度同步。** 下一轮应使用固定 RPS 阶梯、至少五次重复和阶段 Trace，把排队时间、Prefill、KV 传输、首 Token 与 Decode 分开；同时分别测试 UCX 网卡绑定、连接预热，以及 Prefill/Decode 独立的 `max_num_seqs` 和 `max_num_batched_tokens`。

## 7. 与现有 SGLang W4AFP8 参数的静态对比

为了避免影响生产业务，这里没有向现有 SGLang GLM-5.2 服务发送探活、推理或压测请求，也没有修改其 Deployment。以下结论只来自脱敏后的镜像版本、资源规格和启动参数，不代表实测性能排名。

当前两种配置的主要差异如下：

| 维度 | 本文 vLLM 基线 | 现有 SGLang W4AFP8 配置 | 参数作用 |
| --- | --- | --- | --- |
| 权重量化 | 原生 FP8 | W4AFP8 | W4 降低权重显存与读取带宽，使模型可适配 96 GB H20；FP8 通常保留更高质量余量 |
| KV Cache | `fp8` | `fp8_e4m3` | 都通过低精度 KV 扩大容量，仍需评测长上下文质量 |
| 上下文上限 | 131,072 | 204,800 | 更高上限提供更长请求能力，但不等于每种并发都能跑满上限 |
| 并发上限 | 16 | 32 | 更高上限有利于吞吐和连续批处理，也可能放大排队与尾延迟 |
| 推测解码 | 未启用 | EAGLE，3 steps、最多 4 个 draft tokens | 接受率足够高时减少大模型 Decode 次数，是当前最明显的速度变量 |
| Prefix / 分级缓存 | Prefix Cache | HiCache + 内存层 KV Cache | HiCache 主要扩大 KV 容量和复用范围，不保证热 KV 比 HBM 更快 |
| 显存比例 | 0.90 | 0.85 | SGLang 保留更多运行余量，vLLM 把更多显存交给 KV/运行时 |
| Shared Expert Fusion | 默认引擎实现 | 显式关闭 | 通常是兼容性或正确性规避，可能损失一部分 MoE 融合收益 |

SGLang 配置中最值得借鉴的不是“FP4”单个参数，而是下面这组组合：

```text
W4AFP8 权重量化
  + FP8 E4M3 KV Cache
  + EAGLE 推测解码
  + 更高的运行请求上限
  + HiCache 分级 KV Cache
```

它的主要优势分别落在不同目标上：W4AFP8 降低显存成本和权重带宽，EAGLE 优化 Decode，`max-running-requests` 提高调度并发，HiCache 则用主机内存换取更大的 KV 容量。它们不能都被解释成“单请求更快”。例如并发从 16 提到 32 可能提高总吞吐，却让 p95 TTFT 变差；HiCache 的 `write_through` 会增强可恢复性和容量，但也会增加写入流量。

### 7.1 FP8 是否比 FP4 更好

不能只按位宽给出总排名：

- 质量、复杂推理、工具调用和量化风险优先时，原生 FP8 更稳妥；
- 单副本 GPU 成本、96 GB 卡适配和副本规模优先时，W4AFP8 更有优势；
- 单请求 Decode 速度主要取决于有效 Kernel、推测解码接受率和内存带宽，FP4 不会自动更快；
- 高并发吞吐还受 Scheduler、Batch、KV 容量和业务长度分布影响，不能从权重精度直接推出。

因此，本文 vLLM FP8 与现有 SGLang W4AFP8 不是严格的引擎 A/B，而是两套不同的质量、成本与性能组合。将来若测试，应另建隔离实例和独立 Service/Route，不能使用生产服务，并分成两组实验：

1. **引擎 A/B**：相同 FP8 Checkpoint、硬件、上下文、KV 精度、推测解码和压测流量，只改变 vLLM/SGLang；
2. **方案 A/B**：vLLM FP8 对 SGLang W4AFP8，同时报告正确性、EAGLE 接受率、显存、吞吐、TTFT、TPOT 和单次请求成本。

静态分析阶段只能确认 SGLang 参数更偏向“96 GB 适配、长上下文、分级 KV 和推测解码”，不能据此宣称它比当前 vLLM FP8 更快。后续隔离实例的实测结果见 7.2.4；由于客户端数据集和 Engine 参数仍有差异，该数据依然不是只改变推理引擎的严格 A/B。

### 7.2 同 FP8 Checkpoint 的 SGLang 启动实验

为了将权重量化与推理引擎两个变量分开，我们又创建了一个独立 SGLang 0.5.16b1 实例，仍使用本文的原生 FP8 Checkpoint、`8 × H20 141 GB`、TP=8、131K 上下文和 FP8 E4M3 KV Cache。这个实例没有复用或压测已有业务服务。

第三轮使用 SGLang 自带的前台入口启动，没有调用镜像里的二次封装 `start.sh`：

```bash
python3 -m sglang.launch_server \
  --model-path /models/GLM-5.2-FP8/v1 \
  --host 0.0.0.0 \
  --port 8000 \
  --tp-size 8 \
  --served-model-name glm-5.2-fp8-sglang-test \
  --kv-cache-dtype fp8_e4m3 \
  --reasoning-parser glm45 \
  --tool-call-parser glm47 \
  --context-length 131072 \
  --mem-fraction-static 0.85 \
  --model-loader-extra-config '{"enable_multithread_load":false}' \
  --speculative-algorithm EAGLE \
  --speculative-num-steps 3 \
  --speculative-eagle-topk 1 \
  --speculative-num-draft-tokens 4 \
  --max-running-requests 32
```

镜像中的 `python -m sglang.launch_server` 仍然可用，但 0.5.16b1 已提示优先使用等价的 `sglang serve` 入口。模型被识别为 `GlmMoeDsaForCausalLM` 和 FP8 Checkpoint；八个 TP Rank 在约 18 秒内完成 NCCL 2.28.9 初始化，SGLang 为 DSA 自动选择 `flashmla_kv` 作为 Prefill/Decode Attention Backend。

### 7.2.1 为什么 `141/141` 后仍等了二十多分钟

该 Checkpoint 的 `model.safetensors.index.json` 记录总大小为 755,617,140,416 Bytes，约 703.7 GiB。日志中的：

```text
Loading safetensors checkpoint shards: 141/141
```

只反映负责输出进度的一个 Rank 遍历完 141 个分片，不能证明八个 Rank 都完成加载。该进度条本轮约 70 秒就到 100%，但通过 `/proc/<scheduler-pid>/io` 观察，其他 Scheduler 仍持续产生实际磁盘读取，端口也尚未监听。

各进程的 `read_bytes` 最终合计约 704 GiB，与 Checkpoint 体积基本吻合。物理 I/O 主要记在部分 Rank 上，是 Linux 页缓存和并发读盘的记账结果，不代表只有这些 GPU 在装载模型。只有同时满足以下条件才能判定启动成功：

```text
全部 Rank 完成权重与 Kernel 初始化
              ↓
HTTP 端口开始监听
              ↓
Pod Ready=True
              ↓
/v1/models 正确 + 一次正确生成
```

本轮主要时间线如下：

| 阶段 | 观测结果 |
| --- | ---: |
| Pod 创建至八个 Rank 开始加载 | 约 66 秒 |
| 单个可见进度条遍历 141 个分片 | 约 70 秒 |
| 全部权重实际读取与加载阶段 | 约 23 分钟 |
| 首次 DeepGEMM JIT、Warm-up 和服务初始化 | 约 3 分钟 |
| Pod 创建至 Ready | 27 分 20 秒 |
| Ready 后单卡显存 | 127,688–128,168 MiB，约 124.7–125.2 GiB |
| Ready 后剩余显存 | 约 15.5 GiB |

本轮节点已经历过前两轮加载，Linux 页缓存状态不是严格冷缓存，因此 27 分 20 秒不能作为共享存储冷启动的通用成绩；但它能说明只盯一个 Safetensors 进度条会把就绪时间低估一个数量级。

### 7.2.2 加载并发、JIT 和探针

本次镜像中的 `sglang/srt/model_loader/loader.py` 默认允许每个 Rank 使用 8 个加载线程。TP=8 时，这可能把一个 Pod 的模型冷读放大为约 64 路并发 I/O：

```text
8 个 TP Rank × 每 Rank 8 个加载线程
                  │
                  ▼
      约 64 路共享文件系统读取
                  │
        ┌─────────┴─────────┐
        ▼                   ▼
  CFS 吞吐与元数据压力    Rank 完成时间分叉
                            │
                            ▼
                   所有 Rank 同步等待
```

第一轮使用默认加载方式，运行约 24 分钟仍未 Ready；第二轮关闭多线程后，在约 10 分钟时为控制共享文件系统压力主动停止。第三轮继续使用单线程加载并完整等待，最终成功 Ready。关闭多线程降低了瞬时并发，但没有消除 755.6 GB 权重读取量，因此它是存储保护手段，不是冷启动加速结论。

权重加载结束后，SGLang 首次进入 DeepGEMM JIT Pre-Compile。Runtime 明确提示：如果没有预先运行 `sglang.compile_deep_gemm`，该阶段通常可能耗时 10–20 分钟；本轮实际约数分钟完成。后续镜像应使用与正式启动相同的模型、TP 和 GPU 架构预编译，并把生成缓存按以下指纹管理：

```text
SGLang commit + SGL Kernel + CUDA/Driver
  + GPU compute capability + TP
  + 模型 Revision/量化方式 + Kernel 参数
```

不能直接跨版本或跨卡型复用编译目录。本轮还发现镜像缺少 Triton 3.6 对 H20 FP8 MoE 的对应 JSON 配置，Runtime 回退到 Triton 3.5.1 配置并提示性能可能不是最优；正式压测前应先补齐或验证该配置，避免把回退 Kernel 的结果当成 SGLang 上限。

探针配置必须覆盖权重加载、所有 Rank 同步、JIT、KV Cache 和 CUDA Graph：

| 探针 | 本轮设置 | 失败后的行为 |
| --- | --- | --- |
| Startup | TCP 8000，每 10 秒，`failureThreshold=360` | 约 60 分钟仍失败才重启容器 |
| Liveness | TCP 8000，每 30 秒，连续失败 3 次 | 重启容器 |
| Readiness | TCP 8000，每 10 秒，连续失败 3 次 | 只摘出流量，不重启 |

Startup Probe 成功前，Liveness 和 Readiness 不会干扰长时间冷启动。本轮 Pod 全程 `RESTARTS=0`。若 Startup 窗口仍沿用普通 Web 服务的几分钟默认值，就会在 700 GB 级模型即将完成加载时反复杀进程，形成“永远启动不了”的重启循环。

服务启动后还观察到集群采集组件访问 `/metrics` 返回 404。这是因为测试命令没有启用 SGLang Metrics，不影响 OpenAI-compatible 推理接口；正式接入监控时应增加 `--enable-metrics`，并确认抓取周期不会形成无意义的 404 日志风暴。

### 7.2.3 正确性结果与结论边界

Pod 在 0 次重启的情况下达到 `1/1 Running`，`/v1/models` 返回：

```json
{"id":"glm-5.2-fp8-sglang-test","owned_by":"sglang","max_model_len":131072}
```

随后向隔离测试 Pod 的 Loopback 地址发送 `temperature=0`、关闭 Thinking 的最小请求，要求只返回 `FP8_OK`，实际得到精确的 `FP8_OK`。这证明标准 SGLang 0.5.16b1、TP=8、原生 FP8 权重和 EAGLE 参数组合至少通过了模型加载与基本生成验证。

本轮没有向现有生产 SGLang GLM 服务发送任何探活或压测请求。隔离实例随后完成了与 vLLM 基线相同长度和并发档位的压测，但还不是参数严格对齐的引擎 A/B。启动实验能确认的是：

- `141/141` 不能作为多 Rank 服务就绪条件，应同时检查端口、Ready 状态和一次正确推理响应；
- 大模型加载并发需要按 `Pod 数 × TP Rank × 每 Rank 线程数` 估算，不能只看 Pod 数；
- 关闭多线程可以降低瞬时并发，但也可能牺牲单 Rank 吞吐，并非最终优化方案；
- 启动探针应覆盖最慢 Rank、KV Cache 初始化、编译和 CUDA Graph，而不是只覆盖权重进度；
- 首次 DeepGEMM JIT 与 H20 MoE Kernel 配置会影响冷启动和最终性能，需要在镜像构建阶段单独治理；
- 严格冷启动测试必须区分共享存储冷读、Linux 页缓存命中和节点本地缓存命中。

同一时间窗口内，另有已经 Ready 的推理副本发生过重启，因此最初只能确认共享文件系统压力与故障在时间上重叠，不能把相关性写成因果关系。后续完成的宿主机和 Runtime 日志核验已经排除 CFS 是直接根因，完整证据见下一节。

更稳妥的下一轮方案是先把模型按 Revision 预热到节点本地 NVMe，再从 NVMe 启动 SGLang；同时设置全局下载并发上限，持久化且预生成 DeepGEMM/Triton 缓存，记录每个 Rank 的加载完成时间、存储吞吐、`Pod created → first correct response` 和缓存状态。共享文件系统保留为权威源和回源路径，不再让多个 TP Rank 在业务启动时直接形成无界并发冷读。

### 7.2.4 经 AIBrix Gateway 的隔离压测

服务 Ready 后，先确认 AIBrix 侧路由状态：测试模型对应 HTTPRoute 的 `Accepted=True`、`ResolvedRefs=True`，AIBrix Gateway `/v1/models` 已列出 `glm-5.2-fp8-sglang-test`。随后经 Gateway 发送确定性请求，准确返回 `AIBRIX_OK`。因此，已经连接该 AIBrix `/v1` 地址的 OpenWebUI 会通过模型列表自动发现它，无需保存 Pod IP 或为每个模型修改 OpenWebUI Deployment。

压测没有访问现有生产 SGLang GLM 服务。客户端运行在隔离模型 Pod 内，所有请求都发往 AIBrix Gateway。SGLang 的 `random` 数据集实现会尝试从 Hugging Face 下载 ShareGPT 语料，而测试网络无法访问外网；因此本轮改用完全离线的 `random-ids`，并固定 `random-range-ratio=1`，保证请求长度精确。正式命令的结构如下：

```bash
python3 -m sglang.benchmark.serving \
  --backend sglang-oai \
  --base-url http://<AIBRIX_GATEWAY> \
  --model /models/GLM-5.2-FP8/v1 \
  --served-model-name glm-5.2-fp8-sglang-test \
  --tokenizer /models/GLM-5.2-FP8/v1 \
  --dataset-name random-ids \
  --num-prompts <REQUESTS> \
  --random-input-len <INPUT_TOKENS> \
  --random-output-len <OUTPUT_TOKENS> \
  --random-range-ratio 1 \
  --request-rate inf \
  --max-concurrency <CONCURRENCY> \
  --temperature 0 \
  --warmup-requests <CONCURRENCY> \
  --disable-tqdm
```

四组请求全部成功，压测后 Pod 仍为 Ready、0 次重启，并再次经 AIBrix 返回确定性文本 `BENCH_OK`：

| 场景 | 请求成功 | req/s | 输出 tok/s | p50/p95/p99 TTFT | p95 TPOT | p95 ITL | p95 E2EL |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 128 in / 64 out，C=1 | 16/16 | 1.47 | 94.24 | 248 / 260 / 262 ms | 10.10 ms | 17.60 ms | 895 ms |
| 128 in / 64 out，C=4 | 32/32 | 2.24 | 143.44 | 274 / 766 / 775 ms | 31.41 ms | 263.38 ms | 2,481 ms |
| 128 in / 64 out，C=8 | 64/64 | 3.24 | 207.56 | 273 / 529 / 614 ms | 49.29 ms | 265.57 ms | 3,424 ms |
| 4096 in / 128 out，C=4 | 16/16 | 0.69 | 88.66 | 1,212 / 3,665 / 3,665 ms | 44.16 ms | 888.73 ms | 7,887 ms |

与第 6 节的 vLLM 基线做方向性比较：

| 场景 | SGLang 相对 vLLM 的变化 | 观察 |
| --- | --- | --- |
| 128/64，C=1 | 输出吞吐约 `+44%`，p95 TPOT 约 `-17%`，p95 E2E 约 `-10%` | 低并发 Decode 受益最明显 |
| 128/64，C=4 | 输出吞吐约 `-8%`，p95 TPOT 约 `+37%`，p95 E2E 约 `+48%` | 当前参数下中等并发反而退化 |
| 128/64，C=8 | 输出吞吐约 `-5%`，p95 TTFT 约 `-84%`，p95 E2E 约 `-24%` | 总吞吐接近，但尾部排队明显改善 |
| 4096/128，C=4 | 输出吞吐约 `+8%`，p95 TTFT 约 `-17%`，p95 E2E 约 `+25%` | Prefill 更快，但完整请求尾延迟没有同步改善 |

这里的 ITL 不能直接与 vLLM 表格做数值排名：EAGLE 一次可能接受并流式返回多个 Token，SGLang 客户端看到的是响应 Chunk 间隔，不完全等价于逐 Token Decode 间隔。更重要的是，这组对比同时改变了多个变量：

- vLLM 使用 `random`，SGLang 使用离线 `random-ids`，长度相同但 Token 内容不相同；
- SGLang 启用了 EAGLE，vLLM 基线没有 MTP/DSpark；
- `mem-fraction-static`、最大运行请求数、Scheduler 和 Kernel 路径不同；
- SGLang 当前还回退使用 Triton 3.5.1 的 H20 FP8 MoE 配置。

因此不能从这四组数据得出“SGLang 全面快于 vLLM”。当前更准确的结论是：SGLang 在单请求和 C=8 尾延迟上显示出优势，但 C=4 与长输入仍有明显调参空间。下一轮严格 A/B 应复用同一批 Token ID，请求分别发往两个隔离后端，并先关闭双方推测解码；得到引擎基线后，再单独比较 EAGLE 与 MTP/DSpark 的增益和接受率。

### 7.2.5 长上下文、EAGLE 与请求收尾补充验证

为了避免每验证一个功能就重新读取 700 GiB 权重，后续测试在同一次启动窗口内打开了：

```text
--enable-metrics
--enable-metrics-for-all-schedulers
--enable-cache-report
```

这次 Pod 在约 28 分钟达到 Ready，随后 `/health` 首次响应又等待约 4 秒。TCP Startup/Readiness Probe 只能证明端口已经打开，因此生产冷启动 SLO 仍应使用 `Pod created → first correct response`，不能把 `Ready=True` 单独当成业务可用时间。

权重读取完成后，Runtime 生成的主要 JIT 产物位于：

```text
/root/.cache/deep_gemm/cache/
/root/.cache/tvm-ffi/
```

前者包括 SM90 FP8 GEMM 和 Paged MQA Kernel，后者包括 DSA TopK、量化、RoPE 与自定义 AllReduce 等 SGL Kernel 产物。两者合计只有数 MiB，但本次 `/root/.cache` 使用 `emptyDir`，Pod 重建后仍会丢失；正式镜像应按 SGLang、SGL Kernel、CUDA、GPU 架构、TP 和模型量化方式建立兼容性指纹后预编译或持久化，不能无校验地跨版本复用。

#### 功能正确性

隔离实例依次通过以下 OpenAI-compatible 测试：

- 关闭 Thinking 的确定性输出；
- 开启 Thinking 后同时返回 `reasoning_content` 和正确最终答案；
- JSON Schema 约束输出，可被标准 JSON Parser 解析；
- GLM47 工具调用解析，函数名和参数均正确；
- 客户端收到第一个流式 Chunk 后主动取消，服务仍能返回 `/health 200`。

Thinking 用例还暴露了客户端参数问题：`max_tokens=128` 时，推理过程占满输出预算且最终 `content` 为空；提高到 512 后正常返回最终答案。因此 Thinking 模型不能继续沿用普通短回答的低输出上限。

#### 长上下文针检索

在 Prompt 中部埋入唯一密钥、末尾只询问该密钥，得到以下结果：

| 服务端 Prompt Token | 完整请求用时 | 结果 |
| ---: | ---: | --- |
| 3,766 | 12.61 秒 | 精确命中 |
| 30,049 | 12.56 秒 | 精确命中 |
| 60,086 | 17.17 秒 | 精确命中 |
| 117,345 | 32.46 秒 | 精确命中 |

这证明 131K 不只是 `/v1/models` 中的声明值，至少 117K 实际输入可以完成 Prefill 和检索。但四组测试按顺序运行，文本存在公共前缀，也没有在每轮前清空 Radix Cache，因此这里只能作为容量与正确性验证，不能把用时当成严格冷 Prefill 性能。

#### EAGLE 接受率随负载变化

Metrics 已实际返回以下指标，而不是只打开了命令行参数：

```text
sglang:spec_verify_calls_total
sglang:spec_accept_rate
sglang:spec_accept_length
```

`spec_accept_rate` 是被接受 Draft Token 占提议 Draft Token 的比例；`spec_accept_length` 还包含每轮 Verify 的 Bonus Token。不同负载的观测如下：

| 负载 | 接受率 | 平均接受长度 |
| --- | ---: | ---: |
| 中文解释、代码、数学等自然输出 | 约 73%–83% | 3.20–3.48 |
| 单 Token 短请求 | 约 35% | 2.05 |
| AIBrix 路径 C=8 混合请求，运行约 2 分钟 | 约 77% | 3.31 |

这说明 EAGLE 已经有效减少部分 Target Model Decode，但收益明显依赖语料和输出长度。后续必须对生产请求分桶统计接受率，并与关闭 EAGLE 的同语料基线比较，不能用单次高接受率直接推导总体收益。

#### 直连与 AIBrix 路径

流式客户端出现异常后，先用非流式、相同 Seed 的 `128 in / 32 out / C=4` 请求完成了一轮方向性对照：

| 路径 | 成功 | req/s | 输出 tok/s | 平均 E2E | p95 E2E |
| --- | ---: | ---: | ---: | ---: | ---: |
| 直连 SGLang | 16/16 | 0.72 | 23.00 | 4.34 秒 | 5.02 秒 |
| AIBrix Gateway | 16/16 | 0.81 | 25.85 | 4.59 秒 | 5.72 秒 |

非流式响应无法计算真实 TTFT、ITL 和 TPOT，因此这些字段不应参与比较。小样本中 Gateway 的总吞吐反而更高，但平均和 p95 E2E 更慢，说明运行抖动已经大到不能靠两次顺序执行量化纯路由开销。

随后使用相同单 Token 请求交替执行 20 轮，降低顺序偏差：

| 路径 | 中位 E2E | 平均 E2E | p95 E2E |
| --- | ---: | ---: | ---: |
| 直连 SGLang | 3.31 秒 | 3.35 秒 | 3.98 秒 |
| AIBrix Gateway | 3.63 秒 | 3.56 秒 | 4.28 秒 |
| Gateway - 直连 | +327 ms | +214 ms | +303 ms |

这个增量高于普通 TCP 转发，但客户端运行在模型 Pod 内，路径是“模型 Pod → Gateway → 同一模型 Pod”的回环拓扑，同时包含 AIBrix 路由、跨节点网络和两次业务序列化。它只能说明当前实验路径存在可见成本，仍需从独立压测客户端做交错、扩大样本并结合 Router Trace 才能定位开销。

#### 流式结束处理是当前阻断项

本轮两次复现 Engine 已经完成请求、客户端却不能退出：

```text
SGLang 原生 /generate 或 OpenAI 流式请求
                  ↓
GPU 完成生成，Metrics 显示 running=0、queue=0
                  ↓
客户端仍停在 socket poll / event loop 等待结束
```

问题既出现在原生 `/generate`，也出现在 `sglang-oai` 的 `/v1/completions` 流式基准；改为非流式后能够完成。主动取消流式请求后服务仍健康，说明目前证据更接近结束帧、连接关闭或 Runtime 与客户端协议收尾问题，而不是 GPU 一直在计算。当前还不能断言根因一定是 EAGLE，必须补做关闭 EAGLE、抓取完整 SSE 帧、核验 `[DONE]`、客户端超时和 SGLang 对应版本 Issue 的对照实验。

计划运行 5 分钟的 C=8 混合稳定性测试因节点需要立即释放，在约 2 分钟时主动停止；停止前 Pod 保持 Ready、0 次重启、队列为 0，但没有形成完整请求统计，因此不能写成“5 分钟稳定性通过”。测试 Deployment 随后缩容至 0，隔离 Pod 已删除，Service、Route 和部署材料保留供后续复测。

### 7.3 `Completed / exit 0` 背后的 SGLang 崩溃

共享文件系统加载实验期间，另一组已经 Ready 的 Qwen3.5-397B SGLang TP=8 实例反复重启。Kubernetes 显示容器状态为 `Completed`、退出码为 `0`，应用标准输出末尾通常只有 `destroy_process_group() was not called before program exit`，一度让故障看起来像外部探针、节点 OOM 或存储压力触发的正常退出。

这类问题不能停留在 `kubectl logs --previous`。我们通过节点上的运维 DaemonSet 进入宿主机 Mount Namespace，只读核验内核、kubelet 和容器运行时日志：

```bash
kubectl -n <NODE_AGENT_NAMESPACE> exec <NODE_AGENT_POD> -- \
  nsenter --mount=/proc/1/ns/mnt -- bash -lc '
    journalctl -k --since "<START_TIME>" --until "<END_TIME>" --no-pager |
    grep -Ei "oom|out of memory|killed process|NVRM: Xid|nfs: server|rpc.*timeout|I/O error|hung task"
  '
```

排查覆盖所有故障实例所在节点，结果是：

- 没有任何 OOM 记录命中 SGLang Pod UID；
- 没有 NVIDIA Xid、CFS/NFS/RPC timeout、I/O error 或 hung task；
- kubelet 与 containerd 只看到容器主进程结束，并记录退出码 `0`；多数退出前没有 Liveness Probe 失败或 `StopContainer` 事件；
- 共享文件系统加载测试停止后，这组实例仍以相同模式继续崩溃。

同一节点确实出现过一条 Memory Cgroup OOM，但 UID 最终映射到网络 DaemonSet 的 Pod，而不是 SGLang。该 cgroup 的内存上限约 200 MiB，主要消耗来自 kernel slab，最终被杀的是网络代理进程。内核栈中的 `GFP_NOFS` 表示内存分配时不允许递归进入文件系统回收路径，`xfs_vm_readpages` 表示本机 XFS Page Cache 读取；二者都不能作为 CFS 导致 OOM 的证据。**同一节点、相近时间发生，不等于属于同一个 Pod 或同一条故障链。**

真正的异常保存在 HostPath 持久化的 SGLang 日志中。五个副本在不同时间都出现了相同调用栈：

```text
eagle_worker_v2.verify()
  -> prepare_mamba_track_for_verify()
  -> set_mamba_track_indices_from_reqs()
  -> torch.tensor([req.mamba_next_track_idx ...])

TypeError: 'NoneType' object cannot be interpreted as an integer
```

故障发生在 SGLang `0.5.15b1` 的 EAGLE speculative decode 与 Hybrid Mamba Radix Cache 路径。部分请求进入 Verify 阶段时，`req.mamba_next_track_idx` 仍然是 `None`，代码却直接用它构造 `int64` Tensor。一个 Scheduler 首先异常后，所有 TP Scheduler 退出，Tokenizer Manager 收到 `SIGQUIT`，随后 Runtime 主动调用 `kill_process_tree`。业务请求有时已经返回 HTTP 200，服务进程才在请求收尾阶段退出，因此客户端成功率也不能单独证明实例健康。

```text
请求完成并返回 200
        |
        v
EAGLE Verify 读取未初始化的 Mamba Track Index
        |
        v
8 个 TP Scheduler 抛出 TypeError
        |
        v
父进程收到 SIGQUIT 并清理进程树
        |
        v
外层 Shell/tee 返回 0 -> Kubernetes 显示 Completed
```

容器之所以显示 `Completed / exit 0`，还叠加了启动脚本的错误码掩盖：Engine 由后台 `nohup` 启动，外层使用 `start 2>&1 | tee -a ...` 收集日志但没有保留 Engine 的退出码。Engine 进程树结束后，`tee` 正常读到 EOF，Pipeline 最终返回 `0`。因此生产启动脚本应让 Runtime 成为前台主进程，或至少启用 `pipefail`、显式 `wait` 并传播子进程退出码。

这不是仅在本环境出现的偶发现象。SGLang 社区已经记录相同的 Qwen3.5/Mamba、推测解码和 `NoneType` 调用栈，并在 [PR #27998](https://github.com/sgl-project/sglang/pull/27998) 中合入保护逻辑：当 Track Index 尚未初始化时使用第一个 Ping-Pong Slot。相关复现可参考 [Issue #28312](https://github.com/sgl-project/sglang/issues/28312) 和 [Issue #28484](https://github.com/sgl-project/sglang/issues/28484)。镜像标签看起来更新并不代表一定包含修复，仍应按源码 Commit 或镜像 Digest 核验目标代码是否已有 `None` Guard。

处理顺序建议如下：

1. 应急恢复时关闭 EAGLE/NEXTN 推测解码，移除 `--speculative-*` 参数，先验证普通 Decode 路径稳定性；
2. 正式镜像合入 SGLang PR #27998 对应修复，并固定源码 Commit、SGLang/SGL Kernel/CUDA 版本和镜像 Digest；
3. 在隔离实例回归短请求、长 Prompt、Prefix Cache 命中、结构化输出、工具调用和取消请求，观察 Scheduler、GPU Xid、cgroup OOM 与真实进程退出码；
4. 修正启动脚本和告警规则，把 `Completed`、进程主动退出、Probe Kill、OOMKill 和节点故障区分开；
5. 网络 DaemonSet 的小内存 cgroup slab OOM 作为独立问题治理，不与本次 SGLang Runtime 崩溃混为一谈。

## 8. 这组数据能说明什么

它证明了七件事：

- GLM-5.2 FP8 可以使用标准 vLLM 在单台八卡 H20 141 GB 上完成 TP=8 加载；
- AIBrix 不要求后端一定是 SGLang，可以发现并路由 vLLM Engine；
- AIBrix Gateway 的 completions、chat 和 OpenWebUI 链路均功能正确；
- SGLang 0.5.16b1 也能在同一张 FP8 Checkpoint 和单节点 TP=8 上完成加载、结构化输出、工具调用和 117K 长上下文检索；
- 在没有 MTP/DSpark 的基线下，增加并发能够提高总吞吐，但尾延迟很快恶化；
- vLLM 的 Prefill/Decode 可以各占一个八卡节点，通过 NIXL 完成跨节点 KV 传输；
- RDMA 能显著提高 KV 数据面的有效传输速率，并改善长 Prompt 性能，但当前短 Prompt 高并发配置仍可能出现端到端回退。

它还不能证明 vLLM 比 SGLang 更快，也不能代表官方 GLM-5.2 H20 的最优性能。下一轮严格 A/B 应只改变一个变量：

1. 当前 vLLM 基线与原生 MTP `num_speculative_tokens=5`；
2. 当前通用镜像与带 DeepGEMM 的官方优化构建；
3. 模型先分发到节点本地 NVMe，再让 vLLM 与 SGLang 使用相同 Revision、上下文、KV 精度、并发和推测解码策略；
4. 直连 vLLM 与经 AIBrix Gateway，量化网关本身的开销；
5. 共享文件系统冷读、节点 NVMe 命中和持久编译缓存命中三种冷启动状态；
6. P/D 的固定 RPS 阶梯、更多重复与阶段 Trace，定位短请求 C=8 的 RDMA 尾延迟回退。

在完成这些 A/B 前，当前服务适合作为 AIBrix + vLLM 的可用基线，不应直接替代已有生产路径。

延伸阅读：

- [大模型权重分发与加载加速](model-weight-delivery-acceleration.md)
- [从半小时到五分钟：大模型冷启动全链路优化](llm-cold-start-optimization.md)
- [DeepSeek-V4-Flash-0731 的 H20 部署与压测](deepseek-v4-flash-h20-evaluation.md)
- [在既有 Kubernetes 集群落地 AIBrix](aibrix-existing-cluster.md)
