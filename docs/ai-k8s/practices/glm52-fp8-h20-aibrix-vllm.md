---
title: GLM-5.2 FP8 在 8×H20 141GB 上的 AIBrix + vLLM 实测
description: 记录 GLM-5.2 FP8 单节点 TP=8 的兼容性检查、标准 vLLM 启动、AIBrix 路由、冷启动、OpenWebUI 接入和四组性能基线
status: exploratory
last_reviewed: 2026-08-13
---

# GLM-5.2 FP8 在 8×H20 141GB 上的 AIBrix + vLLM 实测

这次实验回答一个具体问题：GLM-5.2 FP8 是否一定要用 SGLang，还是可以直接使用 AIBrix + vLLM，在一台 `8 × H20 141 GB` 节点上提供 OpenAI-compatible 服务？

结论是可以。模型已使用标准 `vllm serve`、单节点 TP=8 启动，经 AIBrix Gateway 完成确定性中文请求和四组基准测试，并被 OpenWebUI 现有的 AIBrix 连接自动发现。本文所有集群名称、Namespace、节点地址、存储地址、镜像仓库和凭据均已删除或替换为占位符。

这只是功能正确且可复现的 vLLM 基线，不是最终性能结论。本轮没有启用 MTP/DSpark，使用的通用镜像也未发现可独立导入的 DeepGEMM 包，不能把结果直接与官方优化配置或此前其他模型的推测解码数据比较。

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

## 7. 这组数据能说明什么

它证明了四件事：

- GLM-5.2 FP8 可以使用标准 vLLM 在单台八卡 H20 141 GB 上完成 TP=8 加载；
- AIBrix 不要求后端一定是 SGLang，可以发现并路由 vLLM Engine；
- AIBrix Gateway 的 completions、chat 和 OpenWebUI 链路均功能正确；
- 在没有 MTP/DSpark 的基线下，增加并发能够提高总吞吐，但尾延迟很快恶化。

它还不能证明 vLLM 比 SGLang 更快，也不能代表官方 GLM-5.2 H20 的最优性能。下一轮严格 A/B 应只改变一个变量：

1. 当前 vLLM 基线与原生 MTP `num_speculative_tokens=5`；
2. 当前通用镜像与带 DeepGEMM 的官方优化构建；
3. vLLM 与 SGLang 使用相同模型 Revision、上下文、KV 精度、并发和推测解码策略；
4. 直连 vLLM 与经 AIBrix Gateway，量化网关本身的开销；
5. 共享文件系统冷读、节点 NVMe 命中和持久编译缓存命中三种冷启动状态。

在完成这些 A/B 前，当前服务适合作为 AIBrix + vLLM 的可用基线，不应直接替代已有生产路径。

延伸阅读：

- [大模型权重分发与加载加速](model-weight-delivery-acceleration.md)
- [从半小时到五分钟：大模型冷启动全链路优化](llm-cold-start-optimization.md)
- [DeepSeek-V4-Flash-0731 的 H20 部署与压测](deepseek-v4-flash-h20-evaluation.md)
- [在既有 Kubernetes 集群落地 AIBrix](aibrix-existing-cluster.md)
