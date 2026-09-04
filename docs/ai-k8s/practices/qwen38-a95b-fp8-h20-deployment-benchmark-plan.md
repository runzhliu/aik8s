# Qwen3.8-2.4T-A95B-FP8 在 H20 上的部署测试与压测计划

> 状态：2026-09-03 完成 Day-0 方案、官方 Recipe 核对，以及 SGLang/vLLM 镜像在生产与 gd5c 的交付验证；模型尚未完成共享存储同步与 NVMe 预热，本文不是实测结果。

## 结论先行

`Qwen/Qwen3.8-2.4T-A95B-FP8` 是纯文本 MoE 推理模型，总参数约 2.4T、每 Token
激活约 95B。它包含 92 层，其中 69 层为 Gated DeltaNet 线性注意力、23 层为完整
Attention；共有 512 个 Routed Experts，每 Token 激活 10 个 Routed Expert 和 1 个
Shared Expert。原生 Context 为 262,144，可实验性扩展到 1,010,000。

FP8 Safetensors 的索引载荷为 `2,496,154,358,768` 字节，共 213 个分片。vLLM Recipe
给出的可服务显存规划值约 2,996GB；因此首轮最低候选资源为：

- 4 节点 × 8 张 141GB H20，共 32 卡；
- 四节点驱动、GPU、RDMA、MTU 和 NCCL 环境一致；
- 每个节点至少保留约 2.8TB 本地 NVMe 空间，用于一份完整 Checkpoint 和同步余量；
- 模型先从共享文件存储预热到宿主机 NVMe，正式服务不从共享文件存储冷加载；
- SGLang 和 vLLM 顺序复用同一组 32 卡，不同时驻留。

SGLang 官方 Hopper Recipe 已在 4×8 H200 上验证 `TP8 × PP4`。H20 与 H200 同属
SM90，显存容量相同，但计算、带宽和集群网络不同，因此这里把官方 H200 配方作为 H20
工程起点，不提前宣称 H20 已验证。vLLM 官方容量表同样给 H200 FP8 配置 32 卡；H20
首轮也采用 `TP8 × PP4`，降低跨节点 Tensor Parallel AllReduce 压力。

## 固定对象

| 项目 | 预期值 |
| --- | --- |
| 模型 | `Qwen/Qwen3.8-2.4T-A95B-FP8` |
| 架构 | `Qwen3_5MoeForCausalLM` / `qwen3_5_moe_text` |
| 权重 | Block FP8，`weight_block_size=[128,128]` |
| 分片 | 213 个 Safetensors |
| Index tensor payload | `2,496,154,358,768` B |
| 层结构 | 69 GDN + 23 Full Attention，共 92 层 |
| MoE | 512 Experts，Top-10 Routed + 1 Shared |
| MTP | Checkpoint 内置 1 层 MTP Head |
| 原生 Context | 262,144 |
| 模型能力 | 纯文本、Reasoning、Tool Calling，不是视觉模型 |

镜像固定到上游 `linux/amd64` Manifest，不能在正式部署时引用浮动 Tag：

| 引擎 | 上游 Tag | 固定 amd64 Manifest | 压缩层总计 |
| --- | --- | --- | ---: |
| SGLang | `lmsysorg/sglang:qwen38` | `sha256:a24b4b997aff149d1090cf3e4dcda3dc65eef70e3cdd51a5f2d6cc8d94fb69db` | 17,530,853,624 B |
| vLLM | `vllm/vllm-openai:qwen38` | `sha256:d392f621bb3e372ecc09f0b0cb88099afe9fa05d37a0450de45eeb8c12b6787e` | 7,585,857,969 B |

同步状态和内部交付标签记录在
`examples/qwen38-a95b-fp8-h20/images/README.md`。公开文章只保留上游引用与去标识化流程。

## Gate 0：模型同步与 NVMe 预热

先在共享文件存储核对 `config.json` 和 `model.safetensors.index.json`，不要凭 Hugging Face
页面的“2.5TB”显示值判断完整性：

1. Index 引用 213 个唯一分片；
2. 每个分片存在且非空；
3. Index `metadata.total_size` 为 `2,496,154,358,768`；
4. Tokenizer、Chat Template、Generation Config 完整；
5. 保存模型 Revision；不做全量 SHA256。

只给最终选中的四台 H20-3e 预热，不对整个机型池复制约 2.5TB 权重。推荐目录：

```text
shared source: /models/Qwen3.8-2.4T-A95B-FP8/v1
host NVMe:     /apps/dat/model-cache/Qwen3.8-2.4T-A95B-FP8/v1
container:     /models-nvme/Qwen3.8-2.4T-A95B-FP8/v1
```

复制前使用 `findmnt -T /apps/dat/model-cache` 和 `lsblk` 确认目标确实位于 NVMe；每台节点
可用空间至少为剩余复制字节数加 300GB。复制按文件大小续跑，排除 `*.tmp`/`*.part`，完成后
再次比较文件列表、分片数与字节数，再原子写入 `.aik8s-complete`。服务 Init Container
必须检查完成标记，不允许自动回退到共享文件存储。

## Gate 1：四节点硬件与网络

申请 GPU 前先执行零 GPU/低负载预检：

- 节点必须同时匹配 H20-3e 的 `label-group=gpu-training-H20`、`machine-type=A9-1` 和
  `node.kubernetes.io/instance-type=HCCPNV6s.96XLARGE2304-ne`；
- 记录 GPU 型号、每卡显存、驱动、CUDA Compatibility、NUMA 和 GPU/NIC 拓扑；
- 四台节点均有 `/dev/infiniband`，并固定 `GLOO_SOCKET_IFNAME`、`NCCL_SOCKET_IFNAME`、
  `NCCL_IB_HCA` 与 `NCCL_IB_GID_INDEX`；
- 分别验证节点内 8 卡 NCCL AllReduce，以及 32 卡跨节点 AllReduce、Broadcast/SendRecv；
- NCCL 日志必须出现 `NET/IB`，不能回退到 `NET/Socket`；
- 四台 NVMe 的 Revision、213 分片、Index payload bytes 和完成标记一致。

任一 Rank OOM、网络回退或模型副本不一致都停止启动。主基线是 Pipeline Parallel，跨节点
主要承载 Pipeline Stage 数据，但 NCCL 全链路预检仍然必须通过。

## Gate 2：SGLang Target-only 基线

从 32K Context 开始，基于官方 H200 配方：

```text
nodes: 4 × 8 H20 141GB
parallelism: TP8 × PP4
context-length: 32768
linear-attn prefill/decode: flashinfer
mamba-ssm-dtype: bfloat16
mamba-full-memory-ratio: 0.95
page-size: 64
max-prefill-tokens: 8192
reasoning-parser: qwen3
tool-call-parser: qwen3_coder
MTP / DSpark / Expert Parallel / FP8 KV: Off
```

每台节点使用相同命令，只改变 `node-rank`、本机 IP 和 Head 地址。服务 Ready 超时至少
60 分钟。完整保存四个 Rank 的启动命令、镜像 Digest、加载耗时、JIT/CUDA Graph 时间、
显存和 NCCL 日志。

`PP > 1` 会排除 SGLang 聚合式服务的 speculative decoding，所以官方 Hopper
`TP8 × PP4` 基线不启用内置 NEXTN/MTP，也不额外下载 DSpark。H20 首轮不套用 Blackwell
的 DeepEP v2、TRT-LLM MHA、MNNVL 或 one-sided NVLink 配置。

## Gate 3：功能与内容正确性

服务 Ready 后依次验证：

1. `/v1/models` 返回固定的 Served Model Name；
2. 确定性算术和约束指令返回正确最终答案；
3. `reasoning_content` 与最终 `content` 正确拆分；
4. `reasoning_effort=low/medium/xhigh` 均可用；Qwen3.8 不能关闭 Thinking；
5. `qwen3_coder` Tool Parser 返回合法 OpenAI Tool Call 和 JSON 参数；
6. 流式响应、多轮上下文、停止条件、错误请求返回正常；
7. 接入 OpenWebUI 做文本、Reasoning 与 Tool Calling UI Smoke，并保存 Light 模式截图；
8. 模型是纯文本模型，不把图片输入列为能力验收项。

仅有 HTTP 200 或非空文本不能算正确：遗漏最终答案、裸露 `<think>`、重复 Token、NaN、乱码、
Tool JSON 非法都判失败。

## Gate 4：公平性能基线

SGLang 与 vLLM 主对比固定使用同一个 `vllm bench serve` 客户端、相同客户端镜像、同一
Tokenizer、随机种子、请求集合、采样参数和 Warmup。SGLang 原生客户端只用于内部诊断，
不能与主 A/B 的数字拼表。

| 类别 | 输入/输出 Token | 并发 | 目的 |
| --- | --- | --- | --- |
| 短请求 | 128/128 | 1、4、8、16 | 单请求延迟与 Batch 拐点 |
| Agent | 8K/1K | 1、4、8 | 接近 Coding/Agent 交互 |
| RAG | 4K/256 | 4、8、16 | 常规 Prefill 吞吐 |
| 长 Prefill | 16K/256 | 1、4、8 | 长文档输入 |
| 长输出 | 128/2K | 1、4、8 | Decode 与尾延迟 |
| 饱和探针 | 128/128 | 32、64 | 只在 C16 稳定后执行 |

每个 Case 先 Warmup，再记录 3 轮；主表使用中位数并报告离散度。采集 Request、Input、
Output 和 Total TPS，P50/P95/P99 TTFT、TPOT、ITL、E2E、成功率，以及每 Rank GPU
利用率、显存、功耗、PCIe/NVLink/RDMA 吞吐和 Pipeline Bubble。Qwen3.8 的 GDN recurrent
state pool 往往比 KV Cache 更早限制并发，必须同时记录有效 Max Running Requests。

## Gate 5：长上下文和 Needle

长上下文不与吞吐矩阵混跑。服务上限依次重启为 32K、64K、128K、262,144，并在每级执行：

- 随机 Token 单并发 Prefill 能力探针；
- 10%/50%/90% 三个位置的 Needle 精确检索；
- 最终答案重复、截断、NaN 和 Rank 稳定性检查；
- 冷缓存与可复用前缀结果分开记录。

只有原生 262K 全部通过后才准备 512K 和约 1M 实验。1M 需要独立启动参数、至少 3600 秒
客户端超时和单并发运行；vLLM 需显式启用 `VLLM_ALLOW_LONG_MAX_MODEL_LEN=1` 并覆盖
`max_position_embeddings=1010000`。SGLang 的 1M 启动方式先在固定镜像内核对 CLI，未核对
前不将其纳入必过 Gate。1M 失败不会推翻 262K 原生能力结论。

## Gate 6：单变量优化

主基线稳定后才逐项重启，禁止一次修改多个变量：

- Prefix/Radix Cache：冷缓存与热缓存分开；
- FP8 KV Cache：先做 Needle 与内容回归，再看容量收益；
- GDN Radix 策略和 recurrent-state pool 大小；
- CUDA Graph capture size；
- vLLM `fastsafetensors + lazy` 只比较加载时间；
- MTP 仅在 PP=1 的合法拓扑获得足够显存资源后测试，不进入本轮 H20 PP4 主结论；
- EP/DeepEP 只有获得与官方一致的受支持网络和软件栈后再试。

## Gate 7：vLLM 对照

SGLang 全部结果落盘并缩容到 0 后，使用相同四台节点和 NVMe 副本启动 vLLM：

```text
nodes: 4 × 8 H20 141GB
parallelism: TP8 × PP4
max-model-len: 32768 起步
KV dtype: BF16 baseline
prefix cache / MTP / EP: Off
reasoning-parser: qwen3
tool-call-parser: qwen3_coder
engine ready timeout: 3600s
```

先执行相同功能 Gate，再复跑完全相同的性能 Case 和长上下文阶梯。若 vLLM 最终必须采用
TP32 或不同 Cache/Context 才能启动，则将结果标为不同拓扑实验，不写成同配置公平对比。

## 预计耗时与停止条件

在模型已经位于四台 NVMe、节点与 RDMA 正常的前提下：

- 每个引擎冷启动和图捕获预留 30～90 分钟；
- 功能与 OpenWebUI Smoke 约 20～40 分钟；
- 主性能矩阵约 1～2 小时；
- 32K～262K Needle/能力探针约 1～2 小时；
- 每个引擎总体预留 3～5 小时，1M 和单变量优化另计。

以下任一条件触发停止并保存证据：模型 Revision/分片不一致、目标不是 NVMe、NCCL 回退
Socket、任一 Rank OOM/退出、连续通信超时、内容错误或错误率大于零。每个引擎测试完成后
立刻将服务与压测 Job 缩容/删除，确认 32 张卡全部释放。

## 参考

- https://huggingface.co/Qwen/Qwen3.8-2.4T-A95B-FP8
- https://docs.sglang.io/cookbook/autoregressive/Qwen/Qwen3.8
- https://recipes.vllm.ai/Qwen/Qwen3.8-2.4T-A95B
- https://github.com/QwenLM/Qwen3.8
- https://github.com/ai-dynamo/dynamo/tree/main/recipes/qwen3.8-2.4t-a95b
