---
title: Qwen3.8-Flash-Next Day 0 实战：4×H20 跑通原生 262K
description: 用 SGLang Day-0 官方镜像和 FP8 权重，在 4×H20 上验证 Qwen4 预览架构、OpenAI-compatible API、长上下文、长输出与共享前缀性能
status: published
last_reviewed: 2026-08-27
---

# Qwen3.8-Flash-Next Day 0 实战：4×H20 跑通原生 262K

2026 年 8 月 26 日，Qwen 发布 Qwen3.8-Flash-Next，并把它定位为 Qwen4 架构的实验性预览；SGLang 同日给出专用镜像和部署 Cookbook。一天之内，我在 Kubernetes 上完成了两条实测：官方 FP8 权重在 **4×141 GB H20** 上以 TP4/EP4 跑通原生 262,144 Token Context，Thinking、Tool Call 和图片输入均可用；官方镜像在 **8×48 GB L20** 上不能直接运行，只有替换 QSA Decode Kernel 的兼容补丁能够生成，而且性能不具备生产参考价值。

H20 短请求输出吞吐从并发 1 的 90.32 tok/s 扩展到并发 64 的 1,860.09 tok/s；接近 262K 的单请求可完成，P95 TTFT 为 19.16 秒；4K 共享系统提示词场景得到 50.2% 的缓存命中率。这里的结论来自本地实测，不使用官方 H200/B200 数字代替。

## 1. 模型名字和规模先说清楚

开放权重名称是 `Qwen/Qwen3.8-Flash-Next`，不是云端托管的 Qwen3.8-Flash，也不是 Qwen4 正式版。它的 Hugging Face 配置注册为：

```json
{
  "architectures": ["Qwen4ExpForConditionalGeneration"],
  "model_type": "qwen4_exp"
}
```

参数数字看起来容易矛盾，实际上统计范围不同：

| 组成 | 参数量 | 运行时含义 |
| --- | ---: | --- |
| MoE 语言模型主体 | 125B | 每 Token 激活约 6B |
| N-gram Embedding | 51B | 查表为主，可用 PLE Offload 放到主机内存 |
| 主 Serving Body | 约 176B | 主体与 N-gram Embedding 之和 |
| MTP | 约 4B | Checkpoint 内置的一层多 Token 预测模块 |

BF16 权重 Index 为 359,999,963,128 Bytes，约 335.28 GiB；本文使用官方 FP8 Checkpoint，131 个 Safetensors 分片合计 185,502,232,570 Bytes，约 172.76 GiB。它仍然是一个很大的模型，不能因为“每 Token 激活 6B”就按 6B 模型估算显存。

架构上最值得关注的是三点：

- 48 层语言模型按三层 Gated DeltaNet 加一层 Qwen Sparse Attention（QSA）的节奏重复；
- 四分支 Gated Residual 用数据相关的 Read/Write Gate 控制残差信息流；
- 51B Bigram/Trigram Embedding 增加局部 Token 组合信息，并允许通过 PLE Offload 降低 GPU 权重压力。

QSA 的目标是改变长上下文 Attention 的增长曲线，所以只测 128 Token 不能证明这种架构是否有意义。本文把 32K、64K、128K 和接近 262K 都纳入了验证。

参考：[Qwen 模型卡](https://huggingface.co/Qwen/Qwen3.8-Flash-Next)、[官方发布说明](https://qwen.ai/blog?id=qwen3.8-flash-next)、[SGLang Cookbook](https://docs.sglang.io/cookbook/autoregressive/Qwen/Qwen3.8-Flash-Next)。

## 2. 实验环境与边界

| 项目 | 实测配置 |
| --- | --- |
| Checkpoint | `Qwen/Qwen3.8-Flash-Next-FP8`，官方 FP8，131 分片 |
| GPU | 4×NVIDIA H20-3e，单卡 143,771 MiB 可见显存，SM90 |
| 并行 | TP4 / EP4，单机 |
| Context | 262,144 Token，未用 YaRN 扩展 |
| Runtime | SGLang `0.0.0.dev1+gd91c3682b` |
| PyTorch / CUDA / Transformers | `2.13.0+cu130` / `13.0` / `5.12.1` |
| GDN Backend | Prefill 与 Decode 均为 FlashInfer |
| Mamba State | BF16 |
| PLE | N-gram Embedding Offload 开启 |
| API | OpenAI-compatible `/v1` |

SGLang 发布时给出的 NVIDIA 验证矩阵主要是 H200、B200、B300 和 GB300，H20 不在签字矩阵内。因此本文只能表述为“在 H20 上实测成功”，不能外推为官方支持保证。L20 的兼容补丁更不能与官方 Kernel 性能混在一起比较。

## 3. 启动方式

公开示例保留核心参数，不包含任何内部集群、镜像仓库、存储和访问入口细节：

```bash
sglang serve \
  --model-path /models/Qwen3.8-Flash-Next-FP8 \
  --served-model-name qwen38-flash-next \
  --tp-size 4 \
  --ep-size 4 \
  --mem-fraction-static 0.85 \
  --chunked-prefill-size 8192 \
  --ple-offload-embedding \
  --linear-attn-prefill-backend flashinfer \
  --linear-attn-decode-backend flashinfer \
  --mamba-ssm-dtype bfloat16 \
  --reasoning-parser auto \
  --tool-call-parser auto \
  --enable-metrics
```

没有显式传 `--context-length`，运行时读取模型原生的 262,144。第一次尝试建议用 `restartPolicy: Never` 的单 Pod 做 Canary：如果 GPU Device Manager 在准入阶段报错，Deployment/ReplicaSet 会不停创建替代 Pod，几分钟内就可能积累几百个失败对象。单 Pod 健康以后再切换为 Deployment。

### 模型预检不能只数分片

一次真实失败来自版本目录：权重同步工具把完整 Checkpoint 放在父目录下的版本子目录，递归统计仍能看到 131 个分片和约 173 GiB，但 `--model-path` 指向父目录时读不到同层 `config.json`，最终报 `Should have a model_type key in config.json`。

零 GPU 预检必须针对传给 `--model-path` 的**精确目录**同时验证：

1. `config.json` 中的 `model_type` 与 `architectures`；
2. `model.safetensors.index.json` 与 131 个分片的引用完整性；
3. Tokenizer、Chat Template 和 Generation Config；
4. Day-0 镜像里确实注册了 `Qwen4ExpForConditionalGeneration`；
5. CLI 中存在 PLE、QSA/GDN Backend、TP/EP 和 Parser 参数。

## 4. 启动与资源结果

| 指标 | 4×H20 FP8 实测 |
| --- | ---: |
| 首节点拉取 13.95 GB 镜像 | 130.42 s |
| 权重加载 | 88.11 s |
| Decode CUDA Graph 捕获 | 105.15 s |
| Engine Ready | 234.88 s |
| `max_total_num_tokens` | 3,680,256 |
| 稳定后每卡已用显存 | 127,280–128,070 MiB |
| 稳定后每卡余量 | 约 15.25 GiB |

这里还有一个容易误判的冷启动现象：短请求 C4 第一轮的 P95 TTFT 是 2.69 秒，原参数立即复测降到 385 ms。日志显示服务 Ready 后仍有一次性 Kernel 编译落入首轮请求。因此“Ready 后第一轮”和“稳定态”应分别记录，不能挑一个更好看的数字覆盖冷态成本。

## 5. API 不只是 `/health` 返回 200

| 用例 | 结果 | 观察 |
| --- | --- | --- |
| `/v1/models` | 通过 | Served Model 名称固定 |
| Chat Completion | 通过 | OpenAI-compatible 响应正常 |
| Thinking | 通过 | `reasoning_content` 与最终 `content` 可区分 |
| Tool Call | 通过 | 返回结构化函数名和参数 |
| 图片 Data URL | 通过 | 能描述测试图片中的客观内容 |
| OpenWebUI | 通过 | 按 OpenAI-compatible Base URL 注册后可直接选择 |

图片测试还暴露了一个语义坑：开启 Thinking 且只给 128 个输出 Token 时，准确描述全部写进 `reasoning_content`，最终 `content` 为空。这不是 Vision 失败，而是推理过程吃完了输出预算。面向 UI 的图片请求应关闭 Thinking，或把推理预算和最终答案预算分开。

## 6. 压测口径

短基准和长上下文基准统一使用：

- SGLang 原生 Token-ID Endpoint，避免 Chat Template 改变输入长度；
- `random-ids` 与本地 Tokenizer，输入/输出长度固定；
- `request-rate=inf`，由 `max-concurrency` 控制并发；
- `temperature=0`，每轮 Flush Cache；
- 成功请求数必须等于发起数；
- Kubernetes 探针使用 TCP Socket，不产生模型请求。

最后一点来自实测排障。这个 Day-0 镜像的 `GET /health` 不是纯状态读取，而会触发一次 64-token 生成。若每 10 秒用它做 Readiness/Liveness Probe，压测期间就会混入看不见的请求，服务端最大并发、TTFT 和吞吐全部失真。HTTP 200 并不代表接口无副作用。

## 7. 短请求吞吐

工作负载为每请求 128 输入、64 输出 Token：

| 并发 | 请求数 | Output tok/s | Median TTFT | P95 TTFT | P95 TPOT | P95 E2E |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 16 | 90.32 | 196.07 ms | 200.30 ms | 8.14 ms | 710.69 ms |
| 4 | 32 | 334.95 | 181.84 ms | 385.01 ms | 8.86 ms | 942.41 ms |
| 8 | 64 | 578.77 | 188.40 ms | 371.43 ms | 10.69 ms | 1,020.89 ms |
| 16 | 64 | 864.16 | 393.46 ms | 410.07 ms | 12.71 ms | 1,183.96 ms |
| 32 | 128 | 1,393.73 | 440.42 ms | 452.25 ms | 16.61 ms | 1,484.50 ms |
| 64 | 256 | 1,860.09 | 646.43 ms | 1,323.93 ms | 28.77 ms | 2,896.71 ms |

![4×H20 FP8 短请求输出吞吐](../../assets/practices/qwen38-flash-next-sglang/short-throughput.svg)

吞吐从 C1 到 C64 持续增长，但 C64 的尾延迟已经明显恶化。容量规划不应以 1,860 tok/s 当作所有业务的默认并发；交互式 Chat 更可能在 C16–C32 之间按 TTFT SLO 找平衡。

## 8. 长上下文与长输出

### 8.1 单并发 Prefill 曲线

| 输入 / 输出 | 请求数 | Input tok/s | P95 TTFT | P95 TPOT | P95 E2E |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 4K / 128 | 4 | 2,722.55 | 253.72 ms | 9.83 ms | 1.50 s |
| 32K / 128 | 4 | 10,668.22 | 1.86 s | 9.88 ms | 3.07 s |
| 64K / 128 | 4 | 13,159.32 | 3.72 s | 9.92 ms | 4.98 s |
| 128K / 128 | 2 | 14,227.63 | 7.95 s | 9.95 ms | 9.21 s |
| 261,120 / 128 | 1 | 12,748.52 | 19.16 s | 10.27 ms | 20.47 s |

![4×H20 FP8 单并发长上下文 TTFT](../../assets/practices/qwen38-flash-next-sglang/context-ttft.svg)

原生 262K 确实能跑通，但“能放进去”不等于“适合在线交互”。接近 262K 时首 Token 等待约 19 秒，Decode 仍维持约 10 ms/Token，主要代价落在 Prefill。长上下文容量、TTFT SLO 和调用频率必须分开评估。

高并发长上下文还会出现批处理空隙：64K、C4 的 P95 TTFT 为 14.35 秒，P95 TPOT 被拉到 90.40 ms；这不等于单请求 Decode Kernel 突然慢九倍，而是 TPOT 统计包含了请求在连续批处理中的等待。比较 Kernel 时看 C1，评估在线体验时再看多并发 E2E。

### 8.2 1K 长输出

| 并发 | 输入 / 输出 | 请求数 | Output tok/s | P95 TTFT | P95 TPOT | P95 E2E |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 128 / 1,024 | 4 | 114.11 | 205.14 ms | 8.57 ms | 8.97 s |
| 8 | 128 / 1,024 | 16 | 702.56 | 385.49 ms | 11.19 ms | 11.82 s |

长输出比 64 Token 更能稳定观察 Decode 吞吐，也避免用极短样本放大启动抖动。

## 9. 共享前缀：缓存收益能不能量出来

我构造了 4 个系统提示词组，每组 8 个请求；每个请求包含约 4K 共享系统提示词、128 Token 独立问题和 64 Token 输出，并与 4,224 Token 随机独立输入比较：

| 场景 | 总输入 Token | 时长 | Input tok/s | Output tok/s | P95 TTFT | P95 E2E |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 随机独立输入 | 135,168 | 11.10 s | 12,174.35 | 184.46 | 2.28 s | 3.06 s |
| 4 组共享前缀 | 144,808 | 7.15 s | 20,243.86 | 286.31 | 1.09 s | 1.82 s |

![共享前缀与随机输入对比](../../assets/practices/qwen38-flash-next-sglang/shared-prefix.svg)

服务端报告 72,640 个 Device Cached Token，缓存命中率 50.2%。共享前缀组的输入 Token 反而略多，因此它不是逐 Token 完全相同的微基准；但总时长下降 35.6%、P95 TTFT 下降 52.4%，方向非常清楚。统一 System Prompt、长文档问答和多轮 Agent 会比完全随机请求更能吃到 Radix Cache 收益。

## 10. L20 为什么不能当作正式性能路径

官方 Day-0 镜像在 L20（SM89）上直接失败：FlashInfer GDN 要求 SM90+；改用 Triton GDN 后可以越过线性注意力，但 QSA 的 FA4/CuTe 路径继续报 `unable to compute crd2idx`。

为了判断是权重还是 Kernel 问题，我做了一个兼容性补丁：QSA Decode 逐请求回退到 PyTorch SDPA，并关闭 CUDA Graph。8×L20、TP8/EP8、32K 可以正确生成，但 C1 128/64 只有 7.47 tok/s，P95 TPOT 131.77 ms；这是正确性证明，不是 SGLang 的正式 L20 性能。公开结果必须同时写出补丁和禁用项，不能只留下“L20 已支持”。

## 11. vLLM 现在支持吗

截至 2026 年 8 月 27 日，答案是：**稳定版和主分支尚不能直接部署，社区适配正在进行，FP8 也还不能按正式支持使用。**

- [vLLM PR #53896](https://github.com/vllm-project/vllm/pull/53896) 正在加入 `Qwen4ExpForConditionalGeneration`、模型注册、测试和 FP8 量化相关改动，状态仍为 Open/Blocked；
- [vLLM PR #53899](https://github.com/vllm-project/vllm/pull/53899) 单独实现 PLE Offload，状态 Open，且当日存在冲突；
- [vLLM PR #53909](https://github.com/vllm-project/vllm/pull/53909) 补 Qwen4 HyperConnection/QSA/PLE Triton Kernel，状态仍为 Open/Blocked。

因此可以拉取 PR Commit 做实验，但那是维护自定义分支，不应注册成生产稳定模型。本文选择 SGLang，不是因为 vLLM 永远不能支持，而是 SGLang 在发布当天已经交付了可运行的模型实现、专用镜像、PLE、GDN/QSA Backend 和启动配方。

## 12. 接入 OpenWebUI

SGLang 暴露的是 OpenAI-compatible API，OpenWebUI 不需要理解 QSA、PLE 或 TP/EP。在管理员的 OpenAI-compatible Connections 中填写：

```text
Base URL: https://your-model-endpoint.example.com/v1
API Key: 由访问层配置
Model ID: qwen38-flash-next
```

注册前应从 OpenWebUI 所在网络分别验证 `/v1/models` 和一次 Chat Completion。只验证浏览器能打开入口不够：模型服务可能 Ready，但跨网络路由、证书、超时或访问控制仍会使 UI 返回 502。

## 13. 可以复用的 Day-0 检查表

1. 固定模型 Revision、镜像 Digest 和硬件架构，不只记 Tag；
2. 用零 GPU Pod 验证精确模型目录和运行时模型注册；
3. 用单 Pod Canary 避免准入失败引发 ReplicaSet 风暴；
4. Ready 后分别记录冷态首轮和稳定态复测；
5. 检查健康探针是否调用真实推理；
6. API 至少覆盖 Thinking、Tool Call、Vision 和错误预算；
7. 性能至少覆盖短输入、多并发、长输出和原生 Context 边界；
8. 对有前缀缓存的引擎增加共享 System Prompt 场景；
9. 非官方 GPU、补丁 Kernel 和禁用优化必须写在数字旁边；
10. UI 接入从 UI 所在网络验证，不把服务内自测等同于用户可达。

公开 Kubernetes 清单、冒烟脚本、压测脚本与结构化结果位于 [`examples/qwen38-flash-next-sglang`](https://github.com/runzhliu/aik8s/tree/main/examples/qwen38-flash-next-sglang)。

延伸阅读：[Qwen3.8-27B Day 0：vLLM 与 SGLang 测试记录](qwen38-27b-day0.md)、[性能基准与回归](../benchmarking.md)
