# Hy4-preview 部署与压测计划

这组材料用于腾讯 `Hy4-preview` / `Hy4-preview-FP8` 模型同步完成后的部署预检和推理压测。
截至 2026-08-30，本文档是**测试计划**，不是实测结果。

## 先做硬件分流

| 路线 | Checkpoint | 最低起点 | 当前结论 |
| --- | --- | --- | --- |
| H20 / H200 | BF16 `tencent/Hy4-preview` | 2 节点 × 8 卡，TP16 | SGLang 官方给出 H200 BF16 路线；H20 同为 Hopper/SM90，但仍需实测确认 |
| H20 / H200 | MXFP8 `tencent/Hy4-preview-FP8` | 不执行 | 官方 MXFP8 Kernel 要求 SM100+，增加 H20 节点数也不能解决 |
| B200 | MXFP8 | 1 节点 × 8 卡，TP8 | SGLang 官方起点，Context 先设 262K |
| B300 / GB300 | MXFP8 | 1 节点 × 4 卡，TP4 | SGLang 官方起点，Context 先设 262K |

公开仓库的实际文件清单：

| Checkpoint | 分片 | Safetensors 字节数 | 约合 |
| --- | ---: | ---: | ---: |
| Hy4-preview-FP8 | 130 | 813,766,152,348 | 757.88 GiB |
| Hy4-preview BF16 | 131 | 1,559,983,809,380 | 1,452.85 GiB |

FP8 权重按 TP8 平均约 94.7 GiB/卡，从容量上看似能放入 8×141GB H20；但该 Checkpoint
使用 ModelOpt MXFP8，而不是普通 Hopper FP8。SGLang Cookbook 明确要求 SM100+，因此
不能仅凭“显存够”判断 H20 可部署。

2026-08-30 解析到的专用镜像快照如下；正式测试固定 `linux/amd64` Manifest，不直接依赖
可能被更新的 Tag：

| 引擎 | Index / Manifest List | `linux/amd64` Manifest |
| --- | --- | --- |
| SGLang | `sha256:335e6393...0293f` | `sha256:dd2dd03b...4e4c` |
| vLLM | `sha256:dc3f5fbe...522f6` | `sha256:81c930ae...86db` |

## 目录

```text
preflight.py     # 零 GPU 校验模型完整性、量化类型、架构注册和 CLI 参数
smoke.py         # OpenAI API、Thinking/no_think、Tool Call 正确性
cases.csv        # 短请求、长输出、长上下文与极限能力矩阵
benchmark.sh     # 默认 dry-run 的 SGLang/vLLM 压测入口
images/          # 固定上游 amd64 Manifest 的最小镜像封装
results/         # 公开安全的聚合数据、正确性与 RDMA 证据
```

绑定真实节点、Namespace、内部 Registry 和宿主机目录的执行清单不进入公开仓库；公开文档保留
去标识化的 Deployment 参数，使用时按本地环境生成清单。

## Gate 0：同步完整性与运行时预检

FP8 示例：

```bash
MODEL_PATH=/models/Hy4-preview-FP8/v1 \
ENGINE=sglang \
CHECKPOINT=fp8 \
python3 preflight.py
```

BF16 示例：

```bash
MODEL_PATH=/models-nvme/Hy4-preview/v1 \
ENGINE=sglang \
CHECKPOINT=bf16 \
python3 preflight.py
```

预检必须确认：

- `architectures` 包含 `HYV4ForCausalLM`，`model_type` 为 `hy_v4`；
- FP8 为 `modelopt/MXFP8`，不能误判成 Hopper 可直接运行的普通 FP8；
- Index 引用的每个分片均存在且非空，分片数和磁盘实际总字节数匹配；
- Tokenizer、Chat Template、Generation Config 完整；
- 专用镜像实际注册了 HYV4 架构，并含必需的并行、Parser 和 MTP 参数。

首发仓库的两个 Weight Index 均未写 `metadata.total_size`，所以预检不会把该字段为空误判
为损坏；总大小改为逐个统计 Index 引用的实际分片。

## Gate 1：H20 先走 SGLang BF16 TP16

H20 首轮只测试 BF16。以两节点各 8 张 141GB GPU、TP16、Context 131,072 为起点：

```text
image: lmsysorg/sglang:hy4-preview@sha256:dd2dd03b6c1a19793ed160690ec895660ff6c36f6ed71a24240e5d9944a34e4c
model: tencent/Hy4-preview 或完整本地目录
tp: 16
nnodes: 2
context-length: 131072
reasoning-parser: auto
tool-call-parser: auto
MTP: Off
```

多机命令应由 SGLang 官方 Cookbook 生成器按实际节点填写 `--node-rank`、
`--dist-init-addr` 和网卡参数。第一轮关闭 MTP，避免把模型 Kernel、通信和 Draft/Verify
问题混在一起。H20 未出现在官方 Verified 硬件表中，所以服务成功 Ready 之前，不把它写成
“已支持”。

如果 BF16 权重尚未同步，应先补同步；仅完成 FP8 同步不能启动 H20 测试。

## Gate 2：功能正确性

```bash
BASE_URL=http://127.0.0.1:30000/v1 \
MODEL=hy4-preview \
python3 smoke.py
```

验收项：

1. `/v1/models` 能看到服务名；
2. 默认 `high` Thinking 返回最终答案，并能拆出 `reasoning_content`；
3. `no_think` 能通过 Chat Template 参数生效；
4. Tool Call 返回 OpenAI 兼容的结构化参数；
5. 模型是纯文本模型，不能把图片输入成功当成验收项。

## Gate 3：Target-only 性能基线

脚本默认只打印命令：

```bash
ENGINE=sglang STAGE=baseline bash benchmark.sh
```

确认参数后显式执行：

```bash
ENGINE=sglang \
STAGE=baseline \
EXECUTE=1 \
BASE_URL=http://127.0.0.1:30000 \
TOKENIZER=/models-nvme/Hy4-preview/v1 \
MAX_CONTEXT=131072 \
RUN_LABEL=h20-bf16-target \
bash benchmark.sh
```

每个有效 Case 至少 1 次 Warmup + 3 次记录，统计 Request Throughput、Input/Output TPS、
P50/P95/P99 TTFT、TPOT、ITL、E2E、GPU 显存、功耗和错误率。不能只摘最好的一轮。

## Gate 4：长上下文逐级放大

H20 BF16 先测 32K、64K、约 127K，不直接跑 1M。即使模型声明 1M，上下文上限仍受
每 Rank 剩余显存和约 95KB/Token 的 MLA/DSA Cache 约束。官方给 H200 BF16 TP16 的
保守起点也是 131K。

Blackwell FP8 稳定后可将 `MAX_CONTEXT` 提升到 262,144，再逐项开启 256K；512K 和 1M
只作为单并发能力探针，不混入日常吞吐结论。长上下文客户端超时至少设为 300 秒。

## Gate 5：MTP 单变量 A/B

Target-only 稳定后重启同一引擎，其他变量不变：

- SGLang：NEXTN，`steps=3`、`topk=1`、`draft_tokens=4`；
- vLLM：`method=mtp`、`num_speculative_tokens=3`；
- 分别复跑单并发低延迟和高并发吞吐，不默认假定 MTP 一定更快；
- 记录 Draft Token、Acceptance Length、显存和 CUDA Graph 状态。

MTP 会为每请求预留 4 个 Token，极限 Case 必须满足
`prompt_tokens + max_tokens + 4 <= context_length`。

## Gate 6：SGLang / vLLM 公平 A/B

只有同一 Checkpoint、同一 GPU 型号和数量、同一 Context、同一 MTP 状态、同一请求集，
才进入引擎 A/B。vLLM 官方提供 `vllm/vllm-openai:hy4-preview`、
`VLLM_ENABLE_HPC_OPS=1`、`FLASHMLA_SPARSE` 和 Hy4 Parser 配方；目前公开 Recipe 的主路径
也是 MXFP8/Blackwell，因此 H20 BF16 的 vLLM 测试应排在 SGLang 成功之后，单独标为
Experimental，不能冒充官方支持矩阵。

## 停止条件

- 发现 FP8 Checkpoint 被调度到 SM90：停止，不靠增加节点规避 Kernel 代际限制；
- 权重分片、Index 总大小或 Revision 不一致：停止，不启动 GPU Pod；
- 任一 Rank OOM、NCCL 超时或退出：保存完整日志和拓扑后停止该 Case；
- 长上下文答案错误：即使 HTTP 200 也判失败；
- MTP Acceptance 很低且吞吐下降：保留 Target-only 为当前建议配置。

参考：

- [Tencent Hy4-preview 模型仓库](https://github.com/Tencent-Hunyuan/Hy4-preview)
- [Hy4-preview-FP8 权重](https://huggingface.co/tencent/Hy4-preview-FP8)
- [SGLang Hy4-preview Cookbook](https://lmsysorg.mintlify.app/cookbook/autoregressive/Tencent/Hy4-Preview)
- [vLLM Hy4-preview Recipe](https://recipes.vllm.ai/tencent/Hy4-preview)
