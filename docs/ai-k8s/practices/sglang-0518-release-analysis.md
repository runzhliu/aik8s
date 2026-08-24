---
title: SGLang v0.5.16 / v0.5.17 / v0.5.18 单卡 L20 实测：升级真的更快吗
description: 使用官方镜像在同一张 L20 上实测 SGLang v0.5.16、v0.5.17 与 v0.5.18，并对照官方 Release 分析吞吐、尾延迟、启动与容量变化
status: evolving
last_reviewed: 2026-08-24
---

# SGLang v0.5.16 / v0.5.17 / v0.5.18 单卡 L20 实测：升级真的更快吗

> SGLang v0.5.18 已于 2026 年 8 月 22 日发布，共合入 710 个 PR、来自 212 位贡献者。除了拆解官方 H100、B200 与 Blackwell 数据，本文还使用三张官方 `lmsysorg/sglang` 运行时镜像，在同一张 L20、同一个 Qwen3.8-27B-FP8 和同一压测客户端上完成 v0.5.16 / v0.5.17 / v0.5.18 A/B。结论很明确：短请求单请求性能几乎没有版本级跃升；v0.5.17 存在运行槽容量下降；v0.5.17 与 v0.5.18 在本次 4K 混合 Prefill/Decode 用例中出现可复现的尾延迟抬升。

这次测试的起因很简单：今天看到一篇公众号文章宣称 v0.5.18“推理速度暴涨”，展示的性能提升相当夸张。与其转述结论，本文选择回到官方 PR 的原始测试口径，并在可用的 L20 环境中完成一次独立复测。

## 1. 实测先给结论

| 问题 | 实测结果 | 判断 |
| --- | --- | --- |
| 升级后短请求会更快吗 | C1 约 18.8～18.9 tok/s，C4 约 79.6～80.2 tok/s；三版差异不超过约 1% | 在单卡 L20 + Qwen3.8-27B-FP8 路径上基本持平 |
| 高并发容量有变化吗 | v0.5.17 只有 5 个实际运行槽，v0.5.16/v0.5.18 为 6；C8 吞吐分别为 95.61、110.83、111.71 tok/s | v0.5.17 的高并发吞吐下降约 14%，首先是容量变化 |
| 4K 输入会更好吗 | 三版吞吐都约 44 tok/s；v0.5.16 两轮 P95 TPOT 约 61 ms，v0.5.17/v0.5.18 约 71 ms | 总吞吐不变，但新两版出现可复现的请求级尾延迟抬升 |
| 启动快 2.38× 吗 | 排除 Image Pull 后，容器到内部 Ready 约 126 / 131 / 122 秒 | 官方 2.38× 是 H100 上显式 Overlap 路径，不能外推到本次默认 L20 配置 |

所以，对 v0.5.18 最稳妥的定位是：**能力面和若干特定路径继续进步，但对当前 L20 + Qwen3.8-27B-FP8，升级价值主要来自功能与修复，不是短请求吞吐暴涨；上线前还应重点回归长输入调度尾延迟。**

![单张 L20 上 SGLang v0.5.16、v0.5.17、v0.5.18 实测对比](../../assets/practices/sglang-0518-l20/version-benchmark.png)

原始汇总数据：[sglang-v0516-v0518-ab-20260824.json](https://github.com/runzhliu/aik8s/blob/main/examples/qwen38-27b-l20-sglang/results/sglang-v0516-v0518-ab-20260824.json)。官方依据：[SGLang v0.5.18 Release](https://github.com/sgl-project/sglang/releases/tag/v0.5.18)。

## 2. 测试设计与公平性边界

| 项目 | 固定值 |
| --- | --- |
| GPU | 单张 NVIDIA L20，46,068 MiB |
| 模型 | Qwen3.8-27B-FP8，TP=1 |
| 上下文与 KV | 32K，FP8 E4M3 KV Cache |
| 功能 | 保留完整多模态、Reasoning Parser 与 Tool Parser |
| CUDA Graph | 关闭 Prefill Graph，保留 Decode Graph |
| Server | `mem-fraction-static=0.88`、声明最大运行请求 8、Chunked Prefill 8192 |
| 镜像 | 官方 `lmsysorg/sglang:v0.5.16-cu129-runtime`、`v0.5.17-cu129-runtime`、`v0.5.18-cu129-runtime` |
| 客户端 | 独立固定为 v0.5.16 官方环境，三轮不重建 |
| 流量 | `random-ids`、固定 Tokenizer、seed=42、temperature=0、request-rate=inf |

短请求每组 64 个请求、8 个 Warmup，测试 128 输入 / 64 输出与 C1/C4/C8；长请求每组 32 个请求、4 个 Warmup，测试 4096 输入 / 128 输出与 C4。每次版本切换均先通过同一条 Chat 正确性 Smoke，三版均返回正确结果，全部压测请求也均成功。

这仍不是实验室级多轮统计：短请求每个 Shape 只有一轮；长输入因发现异常，v0.5.16 与 v0.5.18 各复跑一轮，v0.5.17 一轮。版本按 0.5.16 → 0.5.18 → 0.5.17 执行，后测版本可能受宿主页缓存已热影响。因此 Weight Load 只作为观测，不用于宣布版本加载加速；在线压测的输入、服务和客户端变量则保持不变。

## 3. 短请求：C1/C4 持平，C8 暴露 v0.5.17 容量下降

### 3.1 128 输入 / 64 输出

| 版本 | 并发 | 输出 tok/s | P95 TTFT | P95 TPOT | P95 E2E |
| --- | ---: | ---: | ---: | ---: | ---: |
| 0.5.16 | 1 | 18.92 | 187.46 ms | 50.63 ms | 3,368.96 ms |
| 0.5.17 | 1 | 18.89 | 188.37 ms | 50.58 ms | 3,373.66 ms |
| 0.5.18 | 1 | 18.83 | 204.26 ms | 50.68 ms | 3,389.18 ms |
| 0.5.16 | 4 | 79.59 | 267.27 ms | 47.34 ms | 3,250.80 ms |
| 0.5.17 | 4 | 79.64 | 272.91 ms | 47.28 ms | 3,251.79 ms |
| 0.5.18 | 4 | 80.20 | 277.97 ms | 46.92 ms | 3,235.77 ms |
| 0.5.16 | 8 | 110.83 | 3,705.50 ms | 48.42 ms | 6,755.62 ms |
| 0.5.17 | 8 | 95.61 | 3,601.77 ms | 47.98 ms | 6,617.22 ms |
| 0.5.18 | 8 | 111.71 | 3,678.68 ms | 48.01 ms | 6,701.84 ms |

C1、C4 的 Output Throughput 和 TPOT 几乎重合，不支持“升级 v0.5.18 后 L20 上的 Qwen 短请求明显提速”。C8 的 TTFT 都进入秒级，因为客户端并发已经高于 Engine 实际运行槽，排队成为主要因素。

更关键的是容量日志：

| 版本 | Torch | KV Token 容量 | Mamba State Cache | 实际运行槽 |
| --- | --- | ---: | ---: | ---: |
| 0.5.16 | 2.11.0+cu129 | 181,320 | 33 | 6 |
| 0.5.17 | 2.11.0+cu129 | 158,375 | 29 | 5 |
| 0.5.18 | 2.13.0+cu129 | 178,120 | 32 | 6 |

v0.5.17 的 C8 吞吐比 v0.5.16 低 13.7%、比 v0.5.18 低 14.4%，与 5/6 的运行槽差异方向一致；单请求和 C4 没有同步变慢，说明问题不是 Decode Kernel 普遍回退。容量指标必须与吞吐一起看，否则很容易把“可同时服务的请求变少”误判成单请求算力下降。

这里的“运行槽”不是 Pod、副本或 HTTP 连接数，而是每个 Engine/DP Rank 同一时刻能在 GPU 上保持活跃的请求数。这个 Qwen3.8 模型还需要为每个请求分配 Mamba/SSM State Cache；日志显示每个请求占 5 个 State Slot，所以实际并发为：

```text
v0.5.16: floor(33 / 5) = 6
v0.5.17: floor(29 / 5) = 5
v0.5.18: floor(32 / 5) = 6
```

命令行中的 `max-running-requests=8` 只是上限，Engine 会根据 State Cache 与显存预算自动下调以避免 OOM。请求超过实际运行槽后不会立即失败，而是留在队列中等待，因此最先恶化的是 TTFT，系统吞吐也会在更低并发提前触顶。这不是“镜像文件占用 GPU 显存”，而是各镜像包含的 SGLang、PyTorch、Kernel 与运行时显存分配行为不同。

若要强行提高槽数，可以评估增加 Mamba Cache 预算、使用更小的 Mamba State dtype、降低上下文/KV 占用或提高显存利用率；这些方案都会改变 OOM 与长上下文边界，必须重新做容量测试，不能只把声明并发改成 8。

## 4. 4K 输入：吞吐不变，但请求级尾延迟抬升

| 版本 | 轮次 | 输出 tok/s | P95 TTFT | P95 TPOT | P95 ITL | Max ITL |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 0.5.16 | 1 | 44.04 | 5,902.98 ms | 60.91 ms | 50.46 ms | 1,944.61 ms |
| 0.5.16 | 2 | 43.91 | 5,921.20 ms | 60.60 ms | 50.01 ms | 1,877.49 ms |
| 0.5.17 | 1 | 44.12 | 5,819.91 ms | 71.45 ms | 48.67 ms | 3,121.59 ms |
| 0.5.18 | 1 | 44.33 | 5,790.50 ms | 70.88 ms | 48.31 ms | 3,109.77 ms |
| 0.5.18 | 2 | 44.42 | 5,784.71 ms | 71.06 ms | 48.29 ms | 3,072.33 ms |

三版整轮吞吐都约为 44 tok/s，v0.5.17/v0.5.18 的 P95 TTFT 还略低；但两版的 P95 TPOT 稳定在约 71 ms，比 v0.5.16 两轮约 61 ms 高约 16%～18%。与此同时 P95 ITL 仍约 48～50 ms，差异来自少量更长停顿：Max ITL 从约 1.9 秒增加到约 3.1 秒，进而拉高部分请求的平均 TPOT。

因此更准确的表述是：**在当前 4K Prefill 与 Decode 混跑形状下，v0.5.17 起出现可复现的请求级尾延迟变化，但总体吞吐没有回退。**它可能与 Chunked Prefill/Decode 调度交错相关，还不能只凭这些数据定位到具体 PR，也不能外推到没有 Mamba/混合架构、不同 Chunk Size 或不同并发的模型。

## 5. 启动：没有复现“2.38×”，但口径必须拆开

| 版本 | Weight Load | Decode Graph | 容器到内部 Ready |
| --- | ---: | ---: | ---: |
| 0.5.16 | 24.90 s | 32.55 s | 125.57 s |
| 0.5.17 | 14.65 s | 32.82 s | 约 131.00 s |
| 0.5.18 | 16.79 s | 30.88 s | 122.44 s |

镜像拉取约 3～4 分钟，但它属于镜像分发，已从 Engine 启动时间中剥离。Weight Load 的后两版明显更短，却受到宿主页缓存已热的顺序效应，不能归因于 SGLang 版本；更稳妥的端到端口径是容器启动到内部 Warmup Ready，三版只相差约 9 秒。

这也解释了为什么本次没有看到官方 2.38×：官方数据来自 Qwen3-32B/H100，并显式启用了 Checkpoint Staging 与 CUDA Graph Capture Overlap；本次是 L20、不同模型和默认启动路径。

## 6. v0.5.18 相比 v0.5.17，重点发生了什么

v0.5.17 的主线是 Kimi K3、MiniMax-H3 Day-0 支持、Rust Frontend 初始版本、DCP 通信后端、MoE Prefill 的 DWDP，以及大模型加载和恢复优化。v0.5.18 没有只沿着一条主线继续，而是把变更摊到了运行时全链路。

| 维度 | v0.5.17 重点 | v0.5.18 重点 | 生产含义 |
| --- | --- | --- | --- |
| 新模型 | Kimi K3、MiniMax-H3、EmbeddingGemma、LFM2.5 等 | Muse Glimmer、Intern-S2-Mobius、SANA-Video、LingBot-Video-MoE、LTX-2.5、Cosmos3、LongCat-Image | 自回归、多模态与 Diffusion 继续向同一项目汇合 |
| 启动 | 大 MoE H2D、Weight Cache Recovery | Checkpoint Staging 与 CUDA Graph Capture 重叠；Kernel Cache 统一目录 | 启动优化开始从单点优化转向阶段重叠，但首次升级会重新编译 |
| Decode | DCP、DWDP、MTP Host Overhead | TP LMHead All-to-All、FlashInfer MNNVL Pure Allreduce | 收益高度依赖 DP-Attention、互联拓扑、Batch 和模型架构 |
| P/D 与缓存 | NIXL、PP、DCP、HiCache 的大量可靠性改进 | Mooncake Staging 支持 PP Prefill、NIXL Bootstrap Timeout、HiCache 与推测解码/DCP 组合增强 | P/D 仍在快速演进，升级必须连同 NIXL、Mooncake 和缓存路径回归 |
| 运行时 | Rust Frontend 初始落地 | Rust Server 增加原生 Qwen VL 多模态处理；Tracing v2 异步导出 | 前端重构仍在推进，不能假定所有 Python 路径已经等价迁移 |
| 依赖 | PyTorch 2.11、FlashInfer 0.6.15.post1 | PyTorch 2.13、Triton 3.7.1、FlashInfer 0.6.17、CuTeDSL 4.6.2 | 不是只换一个 SGLang Wheel，AOT/JIT Kernel 和基础镜像都发生变化 |

v0.5.17 依据：[SGLang v0.5.17 Release](https://github.com/sgl-project/sglang/releases/tag/v0.5.17)。

## 7. “2.38×”到底是什么变快了

### 7.1 Qwen3-32B：优化的是启动路径

官方在 H100 上使用 Qwen3-32B 测得：

- 普通默认路径：84.8 秒；
- 已启用协调预取的串行路径：38.94 秒；
- Checkpoint Staging 与 CUDA Graph Capture 重叠：35.6 秒；
- 相对普通默认路径为 2.38×；
- 相对已经启用 Prefetch 的串行路径快 8.6%～11.7%。

这组数字描述的是 **API Ready 前的启动时间**，不是 Output Token Throughput、TTFT 或 TPOT。它需要显式启用：

```text
--startup-weight-load-mode overlap
```

PR 将“串行预取 → 重叠”的 B→C 对比定义为新增机制的主要结果；默认串行 → 重叠的 2.38× 还包含了协调预取的既有收益，而且该路径当前是 Opt-in。官方初始验证范围是 Dense Llama/Qwen2/Qwen3、FP16/BF16、TP1/TP2、默认 Loader 与 mmap Safetensors，不能直接外推到 MoE、FP8 或任意加载后端。

如果模型已经常驻数周，2.38× 启动收益对单次请求吞吐几乎没有直接影响；如果平台频繁弹性扩容、滚动升级或故障重建，这个优化才会显著影响可用容量恢复时间。

实现与数据：[PR #32017](https://github.com/sgl-project/sglang/pull/32017)。

### 7.2 DeepSeek-V4-Pro：Kernel 快 47%，端到端 TPOT 约快 3.5%

在 B200 的 DeepSeek-V4-Pro Decode 路径中，TP LMHead 把 `allgather + scatter` 合并为一次 All-to-All：

| 指标 | 优化前 | 优化后 | 变化 |
| --- | ---: | ---: | ---: |
| LMHead | 320 μs | 169 μs | 下降约 47.2% |
| TPOT | 36.97 ms | 35.67 ms | 下降约 3.5% |

这正好说明了 Kernel 微基准与端到端指标的区别。LMHead 只是每个 Decode Step 的一部分；即使局部耗时近乎减半，整体 TPOT 也不会同比例下降。该优化针对 Pure-DP DP-Attention 路径，不能直接映射到任意 TP 配置。

实现与数据：[PR #32313](https://github.com/sgl-project/sglang/pull/32313)。

### 7.3 DeepSeek-V4-Flash：最多 +6.9% 有三个限定词

官方第三组数据是 DeepSeek-V4-Flash、TP=4、Blackwell、Decode 小 Batch，FlashInfer MNNVL Pure Allreduce 带来 **最多** 6.9% 的收益。限定词不能删：

1. 模型是 DeepSeek-V4-Flash；
2. 硬件是支持对应 MNNVL 路径的 Blackwell；
3. 最大收益出现在小 Batch。

PR 中完整的 Decode Batch Sweep 更能说明“最多”的含义：

| Batch Size | Decode 吞吐变化 |
| ---: | ---: |
| 1 | +6.9% |
| 2 | +6.8% |
| 4 | +6.4% |
| 8 | +3.0% |
| 16 | +2.6% |
| 32 | +3.0% |
| 64 | -1.4% |

因此这项优化在小 Batch 上确实有效，但并非并发越高收益越大；至少在这组 `one_batch` 数据中，BS64 已经出现轻微回退。

Release 说明该能力对 DeepSeek-V3/V3.2/V4 自动启用，其他模型需要显式参数。这并不意味着 H100、L20、AMD 或 Ascend 上会得到相同收益。

实现与数据：[PR #30700](https://github.com/sgl-project/sglang/pull/30700)。

## 8. “全模型适配”为什么需要降一级表述

v0.5.18 Release 明确列出 7 个新增模型：

| 模型 | 类型 |
| --- | --- |
| Muse Glimmer | 自回归、多模态 |
| Intern-S2-Mobius | 自回归 |
| SANA-Video | Diffusion |
| LingBot-Video-MoE | Diffusion |
| LTX-2.5 | Diffusion |
| Cosmos3 Edge & Distilled | Diffusion |
| LongCat-Image | Diffusion |

它还补充了 Qwen3.8、Ling-3.0、Nemotron 3.5 Lightning、Dots3-Note 与 DeepSeek-V4-Pro-0813 的 Cookbook Recipe。这里有三个不同层级：

```text
代码中出现 Model Class
        ↓
有官方 Cookbook 和已验证启动配置
        ↓
目标硬件、精度、上下文与 API 功能通过回归
```

“仓库中已有适配代码”不等于“所有量化制品、所有硬件和所有 API 组合均已验证”。尤其是多模态、Diffusion、LoRA、结构化输出、工具调用、推测解码和 P/D 组合，必须按目标路径分别验收。

最直接的兼容性入口是官方 [SGLang Cookbook](https://docs.sglang.io/cookbook)，而不是根据模型名称猜测是否支持。

## 9. 多硬件优化是真的，但不是能力对齐

v0.5.18 的 Release 分类中同时出现 NVIDIA、AMD/ROCm、Ascend NPU、CPU/Intel XPU 和 Local/Desktop AI，这说明 SGLang 已经不是只围绕单一 CUDA 路径开发。

| 后端 | v0.5.18 可见方向 | 不应自动推断的结论 |
| --- | --- | --- |
| NVIDIA | H100/B200/Blackwell、FA4、FlashInfer、MNNVL、DeepGEMM、NVFP4/MXFP8 | 任意 NVIDIA 架构都支持同一 Kernel 和同等性能 |
| AMD/ROCm | DeepSeek V4 CP、DSpark、Kimi K3、AITER/Triton、MXFP4 | ROCm 与 CUDA 的参数、精度和性能完全一致 |
| Ascend NPU | Kimi K3、DeepSeek V4 DSpark、MiniMax-M3 W8A8、MoE 与量化路径 | CUDA Cookbook 可以原样复制到 NPU |
| CPU/Intel XPU | Gemma4 Xeon、Qwen3.5 CPU Kernel、DeepSeek V4 XPU Kernel | 所有 GPU 模型都适合 CPU 在线服务 |
| MLX/桌面 | GPT-OSS 的 MLX SWA、DGX Spark Inkling | 桌面后端等价于数据中心多机能力 |

因此，“多硬件覆盖持续扩大”是合理概括；“多硬件全域优化完成”会掩盖能力矩阵仍不对称这一事实。

## 10. 升级前比性能更重要的五件事

### 10.1 PyTorch 与 Triton 一起升级

CUDA 运行时切换到 PyTorch 2.13.0 与 Triton 3.7.1，FlashInfer、CuTeDSL、SGL Kernel 和 DeepEP 分发方式也变化。生产镜像需要整体固定，不能只在旧镜像里覆盖安装 `sglang`。

### 10.2 Kernel Cache 目录迁移

Triton、FlashInfer、Inductor、DeepGEMM 和 CUDA Driver Cache 统一迁移到 `SGLANG_CACHE_DIR`。官方明确提醒：升级后的第一次启动会重新编译。若平台把旧 Cache 目录做了预热或挂载，需要同步修改路径，否则首次启动数据会被误判为性能回退。

### 10.3 torchao 集成被移除

`--torchao-config` 已删除。仍依赖该路径的量化部署不能直接升级。

### 10.4 默认行为发生变化

MoE Deferred Finalize、Unified Cache 的窗口外 Slot 释放、DeepSeek V4 的融合路径等变成默认开启；Diffusion Speed Mode 的 `torch.compile` 则改为显式启用。默认参数相同并不代表执行路径相同。

### 10.5 Release 仍有 Known Issues

官方明确记录 Kimi K3 的一项融合优化、AMD GLM-5.2 的一项融合优化在发布前被回滚；v0.5.17 的一项 gRPC Request Lifecycle Tracking 也已回滚，部分 NPU 测试暂时禁用。升级验收不能只测健康检查。

完整清单见 [v0.5.18 Breaking Changes & Known Issues](https://github.com/sgl-project/sglang/releases/tag/v0.5.18#breaking-changes--upgrade-notes)。

## 11. 能否据此判断 SGLang 比 vLLM 快

不能。

上游 Release 的三组数据都是 SGLang 内部新旧路径 A/B，不是 SGLang 与 vLLM 的同机对照。此前我们在单张 L20 上测试 Qwen3.8-27B-FP8 时，SGLang v0.5.16 在部分并发下的 Output Throughput 和 TPOT 更好，vLLM 0.26.0 在部分 TTFT 与高并发场景更好；但当时两端加载形态、CUDA Graph 和 Running Slots 也不完全相同，因此报告没有给出“框架总冠军”。

同样，v0.5.18 的 H100 启动优化不能与另一套框架在 L20 上的 Decode 吞吐放进同一张排行榜。要做有效的 vLLM/SGLang 对比，至少固定：

- 同一个模型 Revision、精度与 Tokenizer；
- 同一台机器、GPU 拓扑、驱动与 CUDA；
- 同样的最大上下文、KV Cache 精度和显存利用率；
- 同样的 CUDA Graph、推测解码、Prefix Cache 和并发上限；
- 同一组 Input/Output Length、并发或到达率；
- 同样的冷启动、热启动与 Shape Warmup 状态。

已有实测参考：[Qwen3.8-27B Day 0：vLLM 与 SGLang 测试记录](qwen38-27b-day0.md)。

## 12. 推荐的 v0.5.17 → v0.5.18 Canary

```text
固定 v0.5.17 基线
  ├─ 正确性：Chat / Reasoning / Tool Call / Structured Output
  ├─ 性能：128/64、4K/128、长上下文、目标并发或到达率
  ├─ 启动：Cold / Weight Cache Hit / Kernel Cache Hit
  └─ 稳定性：30～60 分钟稳态、取消、超时、OOM 与恢复
                 ↓
同硬件、同权重切到 v0.5.18
                 ↓
先保持旧特性开关，再逐项打开 Overlap / 新 Kernel / 新 Cache 路径
```

建议记录以下指标：

| 阶段 | 指标 |
| --- | --- |
| 启动 | Image Pull、Weight Load、Compile、CUDA Graph、API Ready |
| Prefill | TTFT、Input tok/s、Chunked Prefill、Prefix Cache Hit |
| Decode | TPOT、Inter-Token Latency、Output tok/s、Batch Size |
| 资源 | HBM、Host Memory、CPU、PCIe/NVLink/RDMA、Cache Size |
| 稳定性 | 失败率、取消泄漏、OOM、重启时间、结果一致性 |

验收时应该把“框架升级收益”和“显式打开新优化的收益”分成两个实验，否则无法回滚单一变量。

## 13. 最终判断

SGLang v0.5.18 值得跟进，尤其是以下场景：

- 频繁扩缩或冷启动成本很高的 Qwen/Dense 模型服务；
- 在 Blackwell 上运行 DeepSeek V4 系列，使用 DP-Attention、MNNVL 或新量化 Kernel；
- 正在建设 P/D、HiCache、推测解码和多机并行组合；
- 需要最新多模态、视频 Diffusion 或异构硬件适配。

对本次单卡 L20 + Qwen3.8-27B-FP8，v0.5.18 相比 v0.5.16 的短请求吞吐基本持平，并修复了 v0.5.17 只有 5 个运行槽导致的高并发容量下降；但 v0.5.17 起出现的 4K 请求级尾延迟变化在 v0.5.18 仍然存在。若业务以短对话为主，升级不应期待吞吐暴涨；若长提示词与 Decode 混跑很多，应先按真实到达率复测 Chunked Prefill 调度。

因此它不适合因为一句“推理速度暴涨”就全量滚动升级。**先确认优化是否落在自己的模型、硬件和请求形状上，再用同口径 Canary 决定是否迁移。升级验收还应把“单请求速度”和“运行槽/缓存容量”分开，否则会漏掉 v0.5.17 这种容量型回归。**

## 参考资料

- [SGLang v0.5.18 Release](https://github.com/sgl-project/sglang/releases/tag/v0.5.18)
- [SGLang v0.5.17 Release](https://github.com/sgl-project/sglang/releases/tag/v0.5.17)
- [SGLang Cookbook](https://docs.sglang.io/cookbook)
- [Overlap Checkpoint Staging 与 CUDA Graph Capture：PR #32017](https://github.com/sgl-project/sglang/pull/32017)
- [TP LMHead All-to-All：PR #32313](https://github.com/sgl-project/sglang/pull/32313)
- [FlashInfer MNNVL Pure Allreduce：PR #30700](https://github.com/sgl-project/sglang/pull/30700)
