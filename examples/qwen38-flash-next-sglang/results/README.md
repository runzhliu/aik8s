# 实验结果记录

状态：2026-08-27 已完成 L20 兼容性回退，以及 4×141 GB H20 官方 FP8 路径的
启动、API、短请求、长输出、原生 262K Context、共享前缀、长短混部、PLE 和 MTP 实测。

## 制品基线

| 项目 | 固定值 |
| --- | --- |
| BF16 模型 | `Qwen/Qwen3.8-Flash-Next` |
| BF16 Revision | `f5d08274bafd880402bd16f5e3e6c514136ec06c` |
| BF16 Weight Bytes | `359999963128` |
| FP8 模型 | `Qwen/Qwen3.8-Flash-Next-FP8` |
| FP8 Revision | `bcd9f01ddc9cff2316eb84281bebcd5b058bddce` |
| FP8 Weight Bytes | `185502232570` |
| 权重分片 | 131 |
| 上游 SGLang 镜像 | `lmsysorg/sglang:qwen38flashnext` |
| linux/amd64 Digest | `sha256:12d3392bdc8be8d35e9a95f191df6aef99c5114bdbefd41bfdc7e760e6d25ec1` |
| SGLang | `0.0.0.dev1+gd91c3682b` |
| PyTorch / CUDA | `2.13.0+cu130` / `13.0` |
| Transformers | `5.12.1` |

## 每轮必须记录

- 时间、模型 Revision、镜像 Digest、参数完整列表；
- GPU 型号、数量、UUID、NUMA/NVLink 拓扑和 Driver；
- 从容器启动到模型 Ready、权重加载和 Compile/CUDA Graph 时间；
- 稳定后每卡显存、主机内存、CPU 和 PCIe 指标；
- Thinking、Reasoning Effort、Tool Call、工具结果回填和图片输入；
- TTFT、TPOT/ITL、E2E Latency、Input/Output/Total Throughput；
- 失败用例的完整错误、退出码和唯一变量修改。

结果文件使用下列命名：

```text
<precision>-tp<tp>-ep<ep>-c<concurrency>-i<input>-o<output>.json
```

不得把 SGLang Cookbook 的官方 H200/B200 数字复制到这里作为本地 H20 结果。

## Day-0 已确认的兼容性边界

| GPU | 官方镜像直接启动 | 实测结论 |
| --- | --- | --- |
| RTX 6000D（SM120） | 失败 | QSA 的 FA4/CuTe 路径报 `weakly congruent`，与上游 FlashAttention 已知问题一致 |
| L20（SM89） | 失败 | FlashInfer GDN 要求 SM90+；切换 Triton 后 GDN 可过，但 QSA FA4/CuTe 仍报 `unable to compute crd2idx` |
| 8×L20（SM89）+ PyTorch SDPA 兼容补丁 | 成功 | 32K、TP8/EP8、PLE Offload 可生成；这是正确性回退，不是性能实现 |
| 4×141 GB H20（SM90） | 成功 | 官方镜像、官方 FP8、TP4/EP4、PLE Offload、原生 262K，不注入补丁 |

L20 回退路径逐请求循环调用 PyTorch SDPA，并关闭 CUDA Graph。它证明模型可以被加载和
调用，但不能据此判断官方 SGLang 在 L20 上的性能。实测加载后每 Rank 权重约
16.97 GiB；每 Rank 还需要约 9.18 GiB SSM State、0.36 GiB Conv State，以及约
4.99 + 4.99 GiB 的 K/V Cache，最终每卡只剩约 6.44 GiB 余量。

## 两次容易误判为模型问题的基础设施故障

第一轮 H20 Pod 固定到一台异常节点。节点对象显示 8 卡物理容量、7 卡 Allocatable，
但 kubelet Device Manager 在准入时只报告 3 卡可用；4 卡 Pod 因而得到
`UnexpectedAdmissionError`。Deployment/ReplicaSet 对这种准入失败持续补副本，短时间
制造了大量失败 Pod。正确处理方式是先缩到 0，再清理失败 Pod；重新验证时使用
`restartPolicy: Never` 的单 Pod，健康后再切回 Deployment。

第二轮启动参数指向模型父目录，而同步工具把完整 Checkpoint 放在版本子目录。递归统计
仍能看到 131 个分片和约 173 GiB，却找不到同目录的 `config.json`，SGLang 报
`Should have a model_type key`。预检必须针对“传给 `--model-path` 的精确目录”同时检查：

- `config.json` 中的 `model_type` 与 `architectures`；
- `model.safetensors.index.json`；
- 131 个分片及 Index 引用完整性；
- Tokenizer、Chat Template 和 Generation Config。

## L20 探针污染与干净复测

首轮使用 `random-ids` 精确构造 128 输入 / 64 输出 Token。请求均成功，但 Kubernetes
每 10 秒调用一次 `GET /health`，该镜像会为健康检查执行一次 64-token 生成，因此服务端
观测到的最大并发高于压测工具设定值。以下数据只用于展示污染如何被发现，不参与硬件或
框架横向比较：

| 设定并发 | 请求 | 完成 | Output tok/s | Median TTFT | P95 TTFT | P95 TPOT | P95 E2E |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 16 | 16 | 7.45 | 310.67 ms | 346.45 ms | 131.92 ms | 8,624.92 ms |
| 4 | 32 | 32 | 27.83 | 499.94 ms | 662.18 ms | 141.63 ms | 9,331.27 ms |

清单改用 TCP Socket 探针后，干净复测如下。两轮数据接近不代表污染方法可以接受；探针
频率、请求时长和并发模式变化后，隐藏流量的影响会放大。

| 设定并发 | 请求 | Output tok/s | Median TTFT | P95 TTFT | P95 TPOT | P95 E2E |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 16 | 7.47 | 309.07 ms | 346.52 ms | 131.77 ms | 8,615.28 ms |
| 4 | 32 | 27.82 | 500.20 ms | 785.05 ms | 141.18 ms | 9,271.81 ms |

这仍然只是逐请求 PyTorch SDPA 回退的兼容性数据，不用于 H20/L20 硬件比较。

## H20 启动与 API

4×H20、TP4/EP4、官方 FP8 权重的权重加载为 88.11 秒，Decode CUDA Graph 为
105.15 秒，Engine Ready 为 234.88 秒。模型报告 `max_total_num_tokens=3680256`；
稳定后每卡占用 127,280–128,070 MiB，可用余量约 15.25 GiB。

`/v1/models`、Chat Completion、`reasoning_content`、结构化 Tool Call 和图片 Data URL
全部通过。图片请求在 Thinking 开启且输出预算过小时，可能只返回推理内容而没有最终
`content`；这是 Token Budget 问题，不应误判为 Vision 失败。

## H20 短请求稳定态

固定 128 输入、64 输出 Token：

| 并发 | 请求 | Output tok/s | Median TTFT | P95 TTFT | P95 TPOT | P95 E2E |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 16 | 90.32 | 196.07 ms | 200.30 ms | 8.14 ms | 710.69 ms |
| 4 | 32 | 334.95 | 181.84 ms | 385.01 ms | 8.86 ms | 942.41 ms |
| 8 | 64 | 578.77 | 188.40 ms | 371.43 ms | 10.69 ms | 1,020.89 ms |
| 16 | 64 | 864.16 | 393.46 ms | 410.07 ms | 12.71 ms | 1,183.96 ms |
| 32 | 128 | 1,393.73 | 440.42 ms | 452.25 ms | 16.61 ms | 1,484.50 ms |
| 64 | 256 | 1,860.09 | 646.43 ms | 1,323.93 ms | 28.77 ms | 2,896.71 ms |

C4 的首轮 P95 TTFT 为 2.69 秒，原参数复测为 385.01 ms；首轮落入了 Ready 后仍未
完成的一次性 Kernel 编译，因此结构化结果保存稳定态，并在文档中保留冷态差异。

## H20 长上下文、长输出与共享前缀

单并发、输出 128 Token 时，4K/32K/64K/128K/261K 的 P95 TTFT 分别是
0.254/1.862/3.722/7.948/19.164 秒。接近模型原生 262K 的请求完整成功，P95 TPOT
仍为 10.27 ms，主要增长来自 Prefill。

128 输入、1,024 输出时，C1/C8 输出吞吐为 114.11/702.56 tok/s，P95 TPOT 为
8.57/11.19 ms。

共享前缀测试使用 4 个组、每组 8 请求、约 4K System Prompt。相对随机独立输入，
Input Throughput 从 12,174.35 增至 20,243.86 tok/s，P95 TTFT 从 2.285 秒降至
1.089 秒；服务端报告 50.2% Cache Hit。两组总输入 Token 略有差异，因此这是方向性
在线负载对照，不是严格逐 Token 相同的 Kernel 微基准。

机器可读的完整结果：

- [`h20-fp8-summary-20260827.json`](h20-fp8-summary-20260827.json)
- [`l20-sdpa-fallback-summary-20260827.json`](l20-sdpa-fallback-summary-20260827.json)

## 追加实测：长上下文正确性与长短混部

`needle.py` 使用本地 Tokenizer 把 Chat Prompt 校准到精确长度，在 32,768、131,072 和
250,000 Token 下分别把一个随机 Key 放在 10%、50% 和 90% 位置。9 个用例全部返回正确
Key，单次耗时约为 2.02、8.40 和 18.90 秒。它只能证明单针合成检索链路可用，不能代替
LongBench 或真实长文档推理质量评估。

长短混部使用 2 路 65,536/128 长请求作为后台，同时以前台 4 req/s 发送 64 个
128/64 短请求。短请求 P95 TTFT 从独立运行的 782.27 ms 增至 7,747.93 ms，约
9.9 倍；P95 E2E 从 3.77 秒增至 10.73 秒，约 2.85 倍。这说明单实例上长 Prefill
会明显干扰交互请求，生产入口至少需要按请求长度分池、调度或隔离。

## 追加实测：PLE Offload A/B

PLE 开启后，每 Rank 权重从 43.86 GiB 降到 32.20 GiB，节省 11.66 GiB；
`max_total_num_tokens` 从 3,178,560 增至 3,680,256，`max_running_requests`
从 507 增至 587，两项容量均增加约 15.8%。

稳定态的 C8 128/64 输出吞吐分别为 535.12 与 559.99 tok/s，32K C1 Input
Throughput 分别为 10,694.21 与 10,714.06 tok/s。5% 左右的短跑吞吐波动不足以证明
PLE 更快或更慢；在这套配置里，它首先是把 GPU 权重空间换成缓存容量的功能。

## 追加实测：MTP 不是无条件加速

官方低延迟 NEXTN 参数第一次在 H20 启动失败：模型配置选中了 BF16 Mamba SSM State，
而 FlashInfer 的 GDN Target Verify 要求 `initial_state=float32`。显式设置
`--mamba-ssm-dtype float32` 后，MTP 完成 CUDA Graph 捕获并可正常生成；Draft Head
每 Rank 额外加载约 1.18 GiB，实际平均接受长度为 1.92–2.52。

| 输入 / 输出 | 并发 | 普通路径 Output tok/s | MTP Output tok/s | 变化 |
| ---: | ---: | ---: | ---: | ---: |
| 128 / 64 | 1 | 90.32 | 137.60 | +52.3% |
| 128 / 64 | 8 | 535.12 | 278.27 | -48.0% |
| 128 / 1,024 | 1 | 114.11 | 180.32 | +58.0% |
| 128 / 1,024 | 8 | 702.56 | 823.35 | +17.2% |

因此这组 MTP 配方适合低并发和长生成，但不适合直接当作短输出高并发的默认开关。普通
路径与 MTP 路径的服务参数、状态精度和最大 Running Request 也不同，生产采用前必须按
真实输入/输出长度与到达率重做 A/B。
