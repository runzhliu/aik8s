# Kimi K3 在 H20 上的部署测试与压测计划

> 状态：2026-09-02 已完成两台 8×141GB H20 上的 SGLang 与 vLLM 实测；
> 结果与限制见 `examples/kimi-k3-h20/results/20260902-h20-mxfp4/README.md`。

## 结论先行

Kimi K3 是约 2.8T 总参数、原生 MXFP4 的多模态 MoE 模型。官方 vLLM Recipe 给出的
Checkpoint footprint 约为 1,680 GB。单台 8×141GB H20 只有 1,128GB 显存，无法装载；
两台 8×96GB H20 也只有 1,536GB，仍应直接排除。

首轮测试的最低候选资源是：

- 2 节点 × 8 张 141GB H20，共 16 卡；
- 两节点具有稳定的 RDMA/高速互联，且 NCCL AllReduce 和 All-to-All 预检通过；
- CUDA 13 专用镜像要求宿主驱动为 R580 或更新；
- 模型 CFS 目录实际完整，不重复下载权重；
- 模型先从 CFS `/models/Kimi-K3/v1` 预热到宿主机 NVMe
  `/apps/dat/model-cache/Kimi-K3/v1`，推理容器只读挂载为
  `/models-nvme/Kimi-K3/v1`；
- SGLang 先做基线，vLLM 排在其后并标为 Experimental。

H20 与官方 H200 路线同属 Hopper/SM90，但 H20 没有出现在 Kimi K3 Cookbook 的已验证
硬件表内，显存带宽和跨机网络也会直接影响 MoE 性能。因此在服务 Ready 和结果校验完成前，
不能把方案写成“已支持”。

## 固定测试对象

模型 `moonshotai/Kimi-K3` 的预期特征：

| 项目 | 预期值 |
| --- | --- |
| 外层架构 | `KimiK3ForConditionalGeneration` |
| 文本架构 | `KimiLinearForCausalLM` |
| 层数 | 93（69 KDA + 24 MLA） |
| Routed experts | 896 |
| 每 Token 激活 experts | 16 |
| 原生 Context | 1,048,576 |
| 权重 | compressed-tensors / `mxfp4-pack-quantized` |
| 量化单元 | 4-bit，group size 32 |

测试镜像必须用固定的 `linux/amd64` Manifest，不直接依赖会漂移的上游 Tag：

| 引擎 | 上游 Tag | 固定 amd64 Manifest | 压缩层体积 |
| --- | --- | --- | ---: |
| SGLang | `lmsysorg/sglang:kimi-k3` | `sha256:e35551fd3adb5a4a894246249cb77f2d47cfd3702072d0dd137285c2e1b9fc27` | 16.08 GB |
| vLLM | `vllm/vllm-openai:kimi-k3` | `sha256:fb16b180bd9727600067e16fcd6a6de43fb4db1baf4298ef20b4dbdf6bfa5a0e` | 13.33 GB |

对应的内网 Tag 和同步记录见 `examples/kimi-k3-h20/images/README.md`。

## Gate 0：零 GPU 模型完整性检查

在已经完成预热的 H20-3e 节点上、使用 NVMe `hostPath` 且不申请 GPU 的 Pod 中执行。
发现和预热任务可以读取 CFS，但正式预检、推理服务和压测客户端都不得回退到 CFS：

```bash
MODEL_PATH=/models-nvme/Kimi-K3/v1 \
ENGINE=sglang \
python3 examples/kimi-k3-h20/preflight.py
```

必须确认：

1. 架构、层数、KDA/MLA 分布、MoE 参数、1M Context 和 MXFP4 配置与上表一致；
2. `model.safetensors.index.json` 引用的每个分片均存在且非空；
3. Tokenizer、Processor、Chat Template 所需文件存在；
4. 验证 `/models-nvme/Kimi-K3/v1/.aik8s-complete`，并记录本地实际分片数、
   总字节数和 Revision，不因为公开资料写了 1,680GB 就跳过本地核验；
5. 专用镜像能注册 Kimi K3 架构，且包含计划使用的并行和 Parser 参数。

预检不对约 1.56TB 权重做全量 SHA256，避免对 NVMe 造成没有必要的全盘读；若同步工具提供
对象级校验结果，则将它作为证据归档。

## Gate 1：节点、驱动、网络和存储

选定两台空闲的 8×141GB H20 后，先做下面的只读/低负载验证：

- GPU 型号、每卡可用显存、驱动版本和 CUDA 兼容性一致；
- 每节点 8 卡拓扑与 NIC 绑定清楚，确定 `NCCL_SOCKET_IFNAME`、`GLOO_SOCKET_IFNAME`；
- 两节点 RDMA 设备、MTU 和路由一致，必要端口可达；
- NCCL 8 卡单机、16 卡跨机 AllReduce 以及 All-to-All 测试无错误；
- 两节点的 `/apps/dat/model-cache/Kimi-K3/v1` 位于 NVMe XFS，完成标记、96 个分片和
  `1,560,936,091,448` 实际权重字节一致；
- 节点没有其他 GPU 任务，Pod 不会与现有 GLM/Hy4 服务争用显存和网络。

任一网络预检不通过都不进入模型启动。Kimi K3 的 expert parallel 对 All-to-All 很敏感，
“容器能启动”不能代替网络验收。

## Gate 2：SGLang Target-only 基线

首轮按官方 H200 的两节点思路缩到保守配置：

```text
nodes: 2 × 8 H20 141GB
tp-size: 16
ep-size: 16
context-length: 32768
moe-runner-backend: marlin
attention-backend: flashmla
enable-symm-mem: true
KV / KDA state dtype: BF16 baseline
DSpark: Off
prefix cache / HiCache: Off
```

两台节点的启动参数应相同，只替换 `--node-rank`、`--dist-init-addr`、本机 IP 和 NIC。
服务 Pod 把宿主机 `/apps/dat/model-cache` 只读挂载到 `/models-nvme`，模型参数固定为
`/models-nvme/Kimi-K3/v1`；Init Container 校验完成标记失败时直接阻止模型启动。
保留 `NCCL_MNNVL_ENABLE=1`、`NCCL_CUMEM_ENABLE=1`，并为模型加载和多机 rendezvous 设置
足够长的启动超时。首轮不把 DSpark、HiCache、FP8 KV 和其他优化一起打开。

SGLang 的 Kimi K3 Cookbook 当前仍标注最终验证进行中，所以完整记录镜像 digest、参数、
环境变量、节点、启动耗时、每个 Rank 的显存和日志。

## Gate 3：功能与内容正确性

服务 Ready 后先执行 `smoke.py`，至少覆盖：

1. `/v1/models` 返回预期 served model name；
2. 文本问答与确定性算术结果正确；
3. `kimi_k3` reasoning parser 返回最终答案，不只有 reasoning；
4. `kimi_k3` tool parser 返回 OpenAI 兼容的结构化调用及合法 JSON 参数；
5. 流式响应、连续多轮对话正常；
6. 原生图片输入能被模型理解；
7. 非法图片和超长请求返回可解释的 4xx，而不是 Rank 崩溃。

HTTP 200、非空字符串和高 tokens/s 都不等于内容正确。错误答案、重复 token、NaN、乱码或
提前截断均判定失败。

## Gate 4：Target-only 性能基线

使用同一版本的 `vllm bench serve` 客户端、相同随机种子、Tokenizer、请求集合和参数，
对两个引擎生成一致的 OpenAI 请求。这样适合做端到端公平 A/B；同时可用 SGLang 原生客户端
做诊断，但不能把两种客户端的数据直接拼到主对比表。

建议矩阵：

| 类别 | 输入/输出 Token | 并发 | 目的 |
| --- | --- | --- | --- |
| 短请求 | 128 / 64 | 1、4、8、16 | 延迟、批处理和吞吐拐点 |
| RAG | 4K / 128 | 4、8 | 常规 Prefill |
| 长 Prefill | 16K / 256 | 4、8 | Agent/RAG 长输入 |
| 长输出 | 128 / 1K | 1、8 | Decode 延迟与吞吐 |

并发 32 只在 C16 稳定且显存有余量后执行。每个有效 Case 先 Warmup，再记录三轮；主表使用
中位数并报告离散度，禁止只取最好的一轮。采集 Request/Input/Output TPS、P50/P95/P99
TTFT、TPOT、ITL、E2E、成功率、GPU 利用率、显存、功耗、网络吞吐和每 Rank expert 负载。

## Gate 5：长上下文逐级验证

先验证 32K，再依次尝试 64K、128K；只有内容正确和显存稳定后才继续。256K 是能力探针，
1M 只在更低层级全部通过后单并发测试，并配合 Needle/重复检测，不能混入日常吞吐结论。

vLLM 当前存在 Kimi K3 在约 240K 长上下文后重复 token/NaN 的公开问题，因此在问题修复并
固定到含修复的镜像前，vLLM 不执行 256K/1M 验收。即便接口成功返回，也不能算通过。

## Gate 6：单变量优化实验

仅在 Target-only 稳定后逐项重启并复跑相同 Case：

- Prefix cache：分别测冷缓存和可复用前缀，不能混成一个数字；
- DSpark：先关闭取得 NOSPEC 基线，再开启并记录 draft tokens、acceptance length、显存；
- HiCache/KDA 状态优化：只在独立轮次开启；
- Hopper 基线不启用 FP8 KV；当前公开问题显示 Kimi K3 的 FP8 KV 在 Hopper 路线上不可用，
  且 DSpark + FP8 KV 可能出现严重退化。

DSpark 当前 Cookbook 示例使用 7 draft tokens，但最终 serving 验证仍未完成。Acceptance 很低、
尾延迟恶化或吞吐下降时，保留 Target-only 为建议配置。

## Gate 7：vLLM Experimental

SGLang 基线完成后再尝试 vLLM，首轮同样使用 32K、Target-only、BF16 KV，关闭 Prefix Cache
和 speculative decoding。官方 Hopper 建议还包括 Marlin、FlashMLA、较低并发、关闭 custom
all-reduce 和 FlashInfer autotune，并延长引擎 Ready 超时。

目前公开问题显示 Kimi K3 在 H200 上 TP8 可能 OOM，TP8+PP2 也可能遇到并行组错误，TP≥16
还有 MoE padding/replication 风险。因此 vLLM 可能在 H20 16 卡阶段被启动问题阻塞；如果两个
引擎最终使用不同拓扑、Context 或优化项，其数据只作各自实验结果，不能写成公平框架对比。

## 停止与清理条件

- 不是 16×141GB H20，或驱动低于 CUDA 13 镜像要求：不启动；
- 权重、Tokenizer、Revision 或量化配置不一致：不申请 GPU；
- NCCL/RDMA 预检失败、任一 Rank OOM/退出或持续通信超时：保存日志后停止；
- 输出内容错误、重复、NaN 或工具 JSON 非法：即使 HTTP 200 也停止性能结论；
- 长上下文失败后不直接放大 Context；
- 每个引擎测试结束后保存结果、日志和启动参数，立即将 StatefulSet/Job 缩容到 0，释放 16 卡。

## 官方资料与当前风险

- [Kimi K3 模型配置](https://huggingface.co/moonshotai/Kimi-K3/blob/main/config.json)
- [SGLang Kimi K3 Cookbook](https://github.com/sgl-project/sglang/blob/main/docs/cookbook/autoregressive/Moonshotai/Kimi-K3.mdx)
- [vLLM Kimi K3 Recipe](https://github.com/vllm-project/recipes/blob/main/models/moonshotai/Kimi-K3.yaml)
- [vLLM Kimi K3 Day-0 说明](https://github.com/vllm-project/vllm-project.github.io/blob/main/_posts/2026-07-27-k3.md)
- [vLLM H200 TP8 OOM / TP8+PP2 问题](https://github.com/vllm-project/recipes/issues/698)
- [vLLM Kimi K3 长上下文内容损坏问题](https://github.com/vllm-project/vllm/issues/51039)
- [vLLM Kimi K3 Hopper FP8 KV 问题](https://github.com/vllm-project/vllm/issues/51313)
- [vLLM Kimi K3 TP≥16 MoE 问题](https://github.com/vllm-project/vllm/issues/51124)
- [SGLang Kimi K3 DSpark + FP8 KV 退化问题](https://github.com/sgl-project/sglang/issues/32938)
