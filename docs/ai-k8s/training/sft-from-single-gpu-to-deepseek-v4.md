---
title: 大模型 SFT 训练实战：从单卡 LoRA 到 DeepSeek V4
description: 用 ms-swift 和 Qwen3 单卡跑通数据、LoRA、Checkpoint 与推理闭环，再迁移到 Megatron-SWIFT 和 DeepSeek V4 Flash
status: evolving
last_reviewed: 2026-08-20
---

# 大模型 SFT 训练实战：从单卡 LoRA 到 DeepSeek V4

直接把第一次 SFT 放在 284B 的 DeepSeek V4 Flash 上，会把数据格式、训练参数、分布式通信、精度转换和 Checkpoint 问题同时引入。更容易成功的路线是先用相同的数据格式和训练框架，在一张 GPU 上完成一个可以验收的 LoRA 闭环；只有这个闭环稳定后，再切换到 Megatron-SWIFT 和完整 MoE 模型。

本章提供两条路径：

1. **可立即运行的最小实验**：单卡 `Qwen3-4B-Instruct-2507 + ms-swift + LoRA`；
2. **DeepSeek V4 Flash 升级模板**：单机八卡、`Megatron-SWIFT + EP=8 + LoRA`。

配套脚本和示例数据位于 [`examples/llm-sft-lab`](https://github.com/runzhliu/aik8s/tree/main/examples/llm-sft-lab)。示例不包含集群名、内部镜像、存储地址和网络配置。

## 1. 这次实验要证明什么

第一轮不是为了得到一个可上线的领域模型，而是证明下面这条链路能够完整闭环：

```text
JSONL 对话数据
    ↓
模型 Chat Template 与 Assistant Loss Mask
    ↓
LoRA SFT
    ↓
Adapter Checkpoint
    ↓
加载 Adapter 推理
    ↓
固定问题回归与训练记录
```

最小实验的通过条件是：

- GPU、PyTorch 和 `swift` 可以正常识别；
- 数据预处理没有 Schema、Template 或 Tokenizer 错误；
- 训练 Loss 是有限数值，没有 NaN/Inf；
- 输出目录出现 `adapter_model.safetensors` 和 Adapter 配置；
- `swift infer --adapters ...` 能加载该 Checkpoint 并完成一次对话；
- 记录模型、框架、数据、参数、GPU 和结果，而不是只保存一张 Loss 截图。

20 Step 的 Smoke Test 只能验证工程链路，不能证明模型质量提升。

## 2. 预训练、SFT 和对齐到底在做什么

把大模型训练统一理解成“拿数据继续训”很容易选错方法。它们都可能使用 Next Token Prediction，但数据形态、Loss 作用位置和希望改变的能力不同。

```text
海量原始文本
    ↓ 预训练（Pretraining）
基础模型：掌握语言、模式、知识和通用能力
    ↓ 可选：继续预训练（CPT / DAPT）
领域基础模型：更熟悉行业语料、术语和分布
    ↓ 监督微调（SFT）
指令模型：学会怎样理解指令、组织答案和遵循格式
    ↓ 偏好与安全对齐（DPO / RLHF / GRPO 等）
更符合人类偏好、业务边界和安全要求的模型
    ↓ 推理时结合 RAG / Tools
获取最新或私有事实，并执行外部动作
```

| 阶段 | 典型数据 | Loss 主要作用于 | 更擅长改变什么 | 常见规模 |
| --- | --- | --- | --- | --- |
| 预训练 | 去重清洗后的网页、代码、书籍等连续 Token | 几乎所有可预测 Token | 从零形成语言、知识和通用能力 | 数十亿到数万亿 Token |
| 继续预训练 | 医疗、金融、代码或企业领域原始语料 | 连续语料 Token | 领域词汇、表达和知识分布 | 通常远大于 SFT 数据 |
| SFT | `用户问题 → 理想回答`、多轮对话、工具轨迹 | 通常只计算 Assistant 回答 Token | 指令遵循、回答结构、任务流程和风格 | 数千到数百万条高质量样本 |
| 偏好对齐 | Preferred/Rejected 对，或可计算 Reward 的 Rollout | 偏好或奖励目标 | 取舍、边界、安全和可用性 | 取决于算法与任务 |
| RAG | 文档索引和查询时检索结果 | 不修改模型参数 | 最新、私有、可溯源的事实 | 推理时动态变化 |

### 2.1 预训练不是“更大的 SFT”

预训练通常把连续文本切成 Token 序列，让模型预测下一个 Token。它不要求每条数据都有问题和标准答案，目标是从非常大的语料分布中学习表示、语言规律和世界模式。继续预训练沿用相似目标，只是从通用语料转向某个领域，因此更适合让模型熟悉大量行业术语和文体。[领域继续预训练研究](https://arxiv.org/abs/2004.10964)

这类训练会更新大量甚至全部参数，Optimizer State、Gradient、Activation 和 Checkpoint 都很大。数据并行需要同步大量梯度，模型并行和 ZeRO/FSDP 还会引入 All-Gather、Reduce-Scatter 或点对点通信，所以它通常比小型 LoRA SFT 更依赖多机高速网络。

### 2.2 SFT 主要是在教“应该怎样回答”

SFT 把 Prompt、上下文和理想回答拼成一条序列，但常见做法只对 Assistant 部分计算监督 Loss。例如：

```text
System: 你是一个谨慎的基础设施助手。      Loss Mask = 0
User: Loss 降了，可以直接上线吗？           Loss Mask = 0
Assistant: 不可以，还需要隔离评测……         Loss Mask = 1
```

模型因此学习“看到这种输入时，应该生成怎样的输出”。它很适合固定回答格式、工具调用协议、推理流程和业务语气，但几十条问答无法可靠注入一整套知识库；样本过少或重复过多时，Loss 下降更可能代表记住了训练答案。

LoRA 又是 SFT 的一种参数高效实现：冻结基座权重，只训练插入的低秩矩阵。它能显著减少可训练参数、Optimizer State 和 Checkpoint，但每张数据并行 GPU 仍需加载基座模型。[LoRA 论文](https://arxiv.org/abs/2106.09685)

### 2.3 应该选哪一种

- 希望模型掌握大量领域语言和语料分布：先评估继续预训练；
- 希望模型按指定格式回答、调用工具或遵循工作流程：使用 SFT；
- 希望模型在多个可用答案之间形成偏好和安全边界：在 SFT 后做偏好对齐；
- 知识变化快、需要权限控制或引用来源：优先使用 RAG，而不是频繁重新训练；
- 需求同时存在：可以采用“继续预训练 → SFT → 偏好对齐 → RAG”的组合，但每阶段都要保留独立评测。

本章当前的 12 条数据和 20 Step 属于 **LoRA SFT 工程 Smoke Test**，不是预训练，也不能证明领域知识已经写入模型。

## 3. 为什么先选 ms-swift 和 Qwen3-4B

ms-swift 官方快速开始给出了 `Qwen3-4B-Instruct-2507` 在单张 RTX 3090 上进行 LoRA SFT 的例子，标注显存占用约 13 GB；框架同时支持自定义 JSONL 数据、LoRA、推理和导出。这比第一次就安装 Megatron-Core、准备数百 GB 权重和占用八张高显存卡更适合排错。[ms-swift Quick Start](https://github.com/modelscope/ms-swift#-quick-start)

这里选择 4B 模型不是因为它的架构等价于 DeepSeek V4，而是因为以下内容可以复用：

- `messages` 对话数据格式；
- System/User/Assistant 角色和 Chat Template；
- LoRA 数据闭环和基础超参数；
- Checkpoint、Adapter 推理与训练前后评测方法；
- 镜像版本、数据版本和实验元数据记录方式。

不能直接复用的是 DeepSeek V4 的 Hybrid Attention、MoE Expert Parallel、MTP、FP4/FP8 权重转换和多机通信配置，这些在第二阶段单独验证。

## 4. 最小硬件与软件

### 4.1 单卡 Smoke Test

| 项目 | 最低建议 | 说明 |
| --- | --- | --- |
| GPU | 1 × 16 GB | 默认 4B LoRA、1K 序列；显存紧张时降到 512 Token |
| 推荐 GPU | 1 × 24 GB 或更高 | 给数据处理、显存碎片和稍长序列留余量 |
| CPU 内存 | 32 GB | 小数据 Smoke 足够，正式数据应按预处理并发调整 |
| 磁盘 | 30 GB 可用空间 | 包含基础模型、Python 环境、缓存和 Adapter |
| Python | 3.10 及以上 | ms-swift 当前官方要求 Python 3.10+ |
| CUDA/PyTorch | 与 GPU 驱动兼容 | 先使用已有的 CUDA PyTorch 环境，避免第一轮构建镜像 |

H20、H100、A100、L20 和 3090 可使用默认 BF16。T4 不支持原生 BF16，应执行：

```bash
TRAIN_TORCH_DTYPE=float16 bash train-qwen3-4b-lora.sh
```

16 GB 是本实验参数下的尝试下限，不是所有 4B LoRA 任务的通用承诺。模型版本、Attention 实现、序列长度和 Batch 都会改变显存占用。

### 4.2 完整 DeepSeek V4 Flash LoRA

DeepSeek V4 Flash 有 284B 总参数、每 Token 激活 13B 参数；LoRA 只减少可训练参数和优化器状态，不会把 284B 基座变成 13B 模型。[DeepSeek V4 官方模型卡](https://huggingface.co/deepseek-ai/DeepSeek-V4-Pro)

当前公开的 Megatron-SWIFT LoRA 示例使用：

- 单机 8 GPU；
- `TP=1`、`EP=8`；
- 4K 最大训练长度；
- Full Recompute；
- BF16 LoRA Rank 16；
- MTP 1 层。

因此本章把 `8 × 96 GB` 视为完整 V4-Flash LoRA 的合理起点，`8 × 141 GB` 会有更充足的激活值和通信缓冲余量。`8 × 80 GB` 是否能稳定运行需要以精确 Checkpoint、加载精度和实测峰值显存为准，不能只用总显存相加判断。[Megatron-SWIFT DeepSeek V4 最佳实践](https://github.com/modelscope/ms-swift/blob/main/docs/source/BestPractices/deepseek-v4.md)

## 5. 五分钟准备最小实验

进入示例目录：

```bash
cd examples/llm-sft-lab
```

在已经安装 CUDA 版 PyTorch 的 Python 环境中安装 ms-swift：

```bash
python -m pip install --upgrade ms-swift
```

也可以执行仓库脚本，它会创建当前目录下的 `.venv`：

```bash
bash install-ms-swift.sh
source .venv/bin/activate
```

如果只是想先看看训练界面，ms-swift 也提供 Gradio Web UI：

```bash
swift web-ui
```

Web UI 适合熟悉模型、数据和参数位置；本章仍以 CLI 脚本作为可复现记录，因为它更容易做版本控制、复跑和参数 Diff。不要把没有认证的训练 UI 直接暴露到公网。[ms-swift Web UI](https://github.com/modelscope/ms-swift#web-ui)

先做预检：

```bash
bash preflight.sh
```

预检必须确认 `torch.cuda.is_available()` 为 `True`。如果 PyTorch 看不到 GPU，不要开始下载模型和训练。

## 6. 看懂训练数据

ms-swift 支持 JSON、JSONL 和 CSV。最小实验使用每行一条样本的 JSONL：

```json
{"messages":[{"role":"system","content":"你是一个谨慎的 AI 基础设施助手。"},{"role":"user","content":"GPU Pod 一直 Pending，第一步查什么？"},{"role":"assistant","content":"先读取 Pod 的调度条件和 Events，再检查资源请求、节点标签、污点与队列准入状态。"}]}
```

训练时真正参与 Loss 的通常是 Assistant 回答。应人工抽查 Tokenize 后的模板和 Loss Mask，避免把 System Prompt、用户输入、Padding 或错误的推理标记作为训练目标。

仓库中的十几条数据只是为了触发完整代码路径。正式训练至少需要完成：

- 删除重复、冲突和低质量答案；
- 按业务问题而不是随机行做 Train/Validation/Test 隔离；
- 固定一批训练集中从未出现过的回归问题；
- 决定是否保留 Thinking 内容、工具调用和多轮上下文；
- 记录数据生成方式、审核状态和版本 Hash。

## 7. 跑通单卡 LoRA

默认执行 20 Step、最大长度 1024：

```bash
bash train-qwen3-4b-lora.sh
```

脚本支持使用环境变量覆盖关键参数：

```bash
TRAIN_MODEL_ID=/models/Qwen3-4B-Instruct-2507 \
TRAIN_MAX_LENGTH=2048 \
TRAIN_MAX_STEPS=100 \
TRAIN_OUTPUT_DIR=/workspace/output/qwen3-4b-domain-lora \
bash train-qwen3-4b-lora.sh
```

第一次只调整一个变量。如果 OOM，按下面顺序收缩：

1. `TRAIN_MAX_LENGTH=512`；
2. 保持单卡 Batch 为 1；
3. 确认 Gradient Checkpointing 已开启；
4. 再考虑 QLoRA，而不是先引入多卡和 ZeRO。

训练结束后查找最新 Adapter 并进入交互推理：

```bash
bash infer-latest-adapter.sh
```

也可以显式指定 Adapter：

```bash
ADAPTER_PATH=/workspace/output/qwen3-4b-domain-lora/v0-xxx/checkpoint-100 \
bash infer-latest-adapter.sh
```

### 7.1 单张 L20 实测结果

2026 年 8 月 20 日使用本章的默认 20-Step 配置完成了一次真实 Smoke Test。环境为 `1 × NVIDIA L20 46 GB`、`Qwen3-4B-Instruct-2507`、`ms-swift 4.4.1`、`PyTorch 2.11.0 + CUDA 13.0` 和 `Transformers 5.12.1`；12 条示例经 `0.2` 比例切分为 10 条训练数据和 2 条验证数据。

| 指标 | 实测值 |
| --- | ---: |
| 最大训练长度 | 1024 Token |
| Micro Batch / 梯度累积 | 1 / 8 |
| LoRA Rank / Alpha | 8 / 32 |
| 训练步数 | 20 |
| 训练耗时 | 31.39 秒 |
| 平均 Step Time | 1.569 秒 |
| 框架记录的峰值显存 | 7.94 GiB |
| 最终 Train Loss | 3.412 |
| 最终 Eval Loss | 3.497 |
| Adapter 大小 | 约 63 MiB |

`memory(GiB)` 是 ms-swift 训练日志的统计口径，不等同于对 `nvidia-smi` 采样得到的整卡峰值。Adapter 重新加载后可以正常推理；对改写问题“训练集上的 Loss 明显下降后，可以直接把模型发布到生产环境吗？”生成的回答是：

> 不可以。需要先在验证集上验证泛化能力，再在测试集上验证稳定性。

这次结果证明单卡训练、保存与 Adapter 加载链路可用，但不证明 12 条 Smoke 数据具有业务效果。正式结论仍需要扩大数据集，并固定 Base/Adapter 对照评测。

## 8. 怎样判断不是“能跑但没学到”

准备至少三组固定问题：

| 组别 | 目的 | 例子 |
| --- | --- | --- |
| 域内未见题 | 看知识和回答规范是否泛化 | 给出一个训练集中没有的 GPU Pending 场景 |
| 通用保留题 | 检查灾难性遗忘 | 简单数学、摘要、常识和指令遵循 |
| 边界与拒答题 | 检查是否胡编或越权 | 信息不足时是否先指出缺失证据 |

每道题分别保存 Base 和 Adapter 的输出，固定 Prompt、Temperature、Seed 和最大输出长度。只有当域内指标改善、通用能力没有明显回退，才扩大数据和训练步数。

Loss 降低只是优化器拟合了训练 Token，不等于答案更可靠。十几条 Smoke 数据尤其容易在几步内过拟合。

### 8.1 一次能量化效果的小规模 SFT

仓库的 [`meaningful-sft`](https://github.com/runzhliu/aik8s/tree/main/examples/llm-sft-lab/meaningful-sft) 实验把“是否学会”定义为可自动评分的任务：模型读取 Kubernetes 或训练故障证据，使用 11 个实验自定义故障码，并只输出固定 JSON Schema。训练、验证和盲测使用不同的描述模板族，避免随机切分近重复改写造成数据泄漏。

2026 年 8 月 20 日在单张 L20 上完成的 `Qwen3-4B + BF16 LoRA` A/B 使用 330 条训练、55 条验证和 110 条盲测样本。120 Step 训练耗时 257.6 秒，峰值显存 8.1 GiB；验证集选出的最佳 Checkpoint 是 Step 60。

| 盲测指标 | Base | Adapter |
| --- | ---: | ---: |
| JSON 合法率 | 100% | 100% |
| 自定义故障码准确率 | 0% | 90.9% |
| 故障码 Macro-F1 | 0% | 90.4% |
| 信息不足判断准确率 | 100% | 100% |
| 禁止动作关键字覆盖 | 8.2% | 90.9% |

Base 能理解故障并生成合法 JSON，却会自行创造一套看似合理的分类名，因此自定义故障码得分为 0；Adapter 学会了组织约定的分类映射和排障边界。它也没有在盲测上达到 100%：Gang 与 Taint 的两个新表达族共出现 10 条误判。这比只展示成功案例更有价值，因为它直接指出下一轮应增加哪类训练表达，以及为什么修改数据后必须换一份新的盲测集。

## 9. 升级到小型 MoE

在投入完整 V4 前，可以用 Qwen3-30B-A3B 一类较小 MoE 验证：

- Expert 权重是否被 LoRA 覆盖；
- Router 是否冻结，或是否需要辅助均衡 Loss；
- Grouped GEMM 和 MoE Kernel 是否正常；
- 多卡 Expert Parallel 的 All-to-All 是否符合预期。

ms-swift 的官方 MoE LoRA 示例提醒：如果不希望训练 Router，应显式限制 `target_modules` 为 Attention 和 MLP 投影层，而不是盲目匹配所有参数。[Qwen3 MoE LoRA 示例](https://github.com/modelscope/ms-swift/blob/main/examples/train/moe/qwen3_moe.sh)

### 9.1 Qwen3-30B-A3B 在单张 L20 上的加载门槛

2026 年 8 月 20 日使用单张 L20 对 `Qwen3-30B-A3B-Instruct-2507` 做了真实加载测试。模型有 30.5B 总参数、3.3B 激活参数、128 个 Expert 且每 Token 选择 8 个 Expert；“3.3B 激活”描述主要计算路径，不等于其余权重可以不驻留。BF16 权重本身的理论下限约为 56.8 GiB，尚未计算 Activation、CUDA Workspace 和 LoRA 状态，已经超过测试卡可见的 44.4 GiB。[Qwen3-30B-A3B 模型卡](https://huggingface.co/Qwen/Qwen3-30B-A3B)

| 路径 | 实测结果 | 训练与盲测 |
| --- | --- | --- |
| 4B BF16 LoRA | 成功；120 Step 峰值 8.1 GiB | 完成，Step 60 Adapter 故障码准确率 90.9% |
| 30B-A3B BF16 + BNB NF4 | 加载到 411/531 时 OOM；进程已占 44.37 GiB | 未开始，不报告 Loss 和分数 |
| 30B-A3B GPTQ-Int4 | 加载软件兼容性通过，但测试时可用副本缺少权重分片 | 未开始，不把元数据目录算作成功 |

BNB 失败的现象与 Qwen3-MoE 的融合 Expert 表示有关：Transformers 5 会把部分专家矩阵保存为 3D `nn.Parameter`，而不是普通 `nn.Linear`。这不仅影响量化覆盖，也影响 LoRA 注入；PEFT 要求通过 `target_parameters` 显式覆盖 `mlp.experts.gate_up_proj` 和 `mlp.experts.down_proj`。[PEFT LoRA 文档](https://huggingface.co/docs/peft/package_reference/lora)

所以这次结论不是“所有 4-bit 方案都不可能”，而是：现有 BF16 + 标准 BNB NF4 组合不能在单张 L20 上完成加载。下一轮只有拿到完整的预量化 GPTQ/AWQ 权重，检查量化 Kernel 和 Expert Adapter 参数名，并完成至少一个 Forward/Backward 后，才值得继续跑相同的 60-Step 与 110 条盲测 A/B。原始失败记录保存在 [`l20-qwen3-30b-a3b-20260820.json`](https://github.com/runzhliu/aik8s/blob/main/examples/llm-sft-lab/meaningful-sft/results/l20-qwen3-30b-a3b-20260820.json)。

这个阶段的目标是验证 MoE 训练行为，不要把“小型 MoE 能用 Transformers + PEFT 训练”外推为 DeepSeek V4 的特殊 Attention 和 Checkpoint 格式已经兼容。

### 9.2 单机 8 × L20 的 BF16 LoRA 容量验证

同日使用单机 8 张 L20 对相同 BF16 Checkpoint 完成了 60-Step LoRA。直接启动 8 个 ZeRO-3 进程会在模型加载阶段同时构造多份完整权重，主机内存先于显存耗尽；通过单进程 `device_map=balanced` 将 48 层均匀放到 8 张 GPU 后，模型、数据、Forward/Backward、验证和 Adapter 保存均通过。

| 指标 | 实测结果 |
| --- | ---: |
| 可训练参数 | 497.42M / 1.603% |
| Max Length / 梯度累积 | 512 / 8 |
| 训练运行时间 | 1,438 秒 |
| 训练速度 | 0.042 Step/s |
| 平均 Train Loss | 0.348 |
| 最后一个日志窗口 Train Loss | 0.00915 |
| Eval Loss（Step 20 / 40 / 60） | 0.16276 / 0.02949 / 0.02811 |
| Step 60 Eval Token Accuracy | 99.34% |
| 最佳 Checkpoint | Step 60，Adapter 约 1.9 GiB |

镜像中的 Transformers 5.12.1 与 PEFT 0.19.1 在训练结束后重新热加载最佳 Adapter 时存在 `WeightConverter` 参数兼容问题。由于三次验证持续改善、Step 60 本身就是最佳 Checkpoint，本轮关闭 `load_best_model_at_end`，保留 Trainer 的最佳 Checkpoint 选择和保存，最终进程以退出码 0 完成。这个绕行只跳过训练后的热加载，不跳过训练、验证或保存。

需要特别限定结论：这是一条“先证明能装下并能训练”的单进程层切分路径，不是高效的 8 卡并行基线。执行会随层跨 GPU 流动，不能把 8 卡总显存可用误读为 8 卡算力线性叠加。下一轮应对比 FSDP/ZeRO-3 的低主机内存初始化或 Megatron Expert Parallel，并补齐固定 110 条盲测的 Base/Adapter 生成 A/B；在此之前，不用很低的验证 Loss 代替业务效果结论。

## 10. 升级到完整 DeepSeek V4 Flash

仓库的 `train-deepseek-v4-flash-lora.sh` 是根据官方公开方案收敛出的 **Adapter-only Smoke 模板**。和官方长跑示例相比，它把 Micro Batch 降为 1、Global Batch 降为 8，并关闭自动 Merge，目的是先降低峰值显存和避免产生巨大的完整合并权重。

安装当前公开要求的组件：

```bash
bash install-deepseek-v4-training.sh
```

再明确指定本地模型和数据目录：

```bash
V4_MODEL_PATH=/models/DeepSeek-V4-Flash \
V4_DATASET_PATH=/workspace/data/train.jsonl \
V4_OUTPUT_DIR=/workspace/output/deepseek-v4-flash-lora \
bash train-deepseek-v4-flash-lora.sh
```

开始前必须确认：

- 模型精确版本、Tokenizer 和 `config.json` 已记录；
- 8 张 GPU 在同一节点可见，GPU 之间的 P2P/NVLink 拓扑符合预期；
- Host Memory、共享内存和本地临时空间足够；
- FP4 权重加载后实际转换为 FP8 还是 BF16 已从日志确认；
- `EP=8` 下所有 Rank 都能完成初始化；
- 第一轮只跑极少数据和 Step，先检查峰值 HBM、Loss、Step Time 和 Checkpoint；
- Adapter 通过 Transformers 推理回归后，再讨论合并和 vLLM/SGLang 部署。

DeepSeek V4 当前不能直接进行 FP4 blockwise 训练，公开方案会在加载阶段转为 FP8 或 BF16；当前专项方案也暂不支持 `TP>1`。LoRA 与 FP8 组合时应只保存 Adapter，再与 BF16 基座合并，避免低精度舍入吞掉 LoRA Delta。[DeepSeek V4 训练说明](https://github.com/modelscope/ms-swift/blob/main/docs/source/BestPractices/deepseek-v4.md)

## 11. 从单机多卡测到多机 RDMA

分布式训练不能只比较一组“训练总时间”。建议先用集合通信微基准确认链路，再用相同 SFT 负载观察网络差异是否进入端到端瓶颈：

| 阶段 | 拓扑 | 主要回答的问题 |
| --- | --- | --- |
| 单卡 | 1 节点 × 1 GPU | 没有梯度同步时的计算基线是多少 |
| 单机多卡 | 1 节点 × 2/4/8 GPU | PCIe/NVLink 与 DDP 引入多少开销 |
| 多机 TCP | 2 节点 × N GPU，`NCCL_IB_DISABLE=1` | 默认以太网跨机后损失多少 |
| 多机 RDMA | 保持相同节点和 GPU 数，只启用 RDMA | RDMA 能追回多少通信时间 |

配套的 [`distributed`](https://github.com/runzhliu/aik8s/tree/main/examples/llm-sft-lab/distributed) Harness 提供：

- PyTorch/NCCL AllReduce 消息大小扫描；
- 可重复生成、带 Token 长度与 SHA-256 的本地数据；
- 固定 Global Batch 的 Qwen3-4B LoRA 强扩展测试；
- 机器可读的 `NCCL_BENCH` 和 `SFT_BENCH_RESULT` 输出。

固定 Global Batch 时：

```text
N 卡扩展效率 = N 卡 samples/s ÷（单卡 samples/s × N）
```

每个拓扑至少重复三轮，比较中位数；镜像拉取、模型加载、Tokenize 和 Checkpoint 不计入训练区间。TCP/RDMA A/B 必须固定节点、模型、数据 Hash、Batch、Step、软件版本和功耗设置，并从 NCCL INFO 日志确认实际选择的是 `NET/Socket` 还是 `NET/IB`。

还要注意训练方法本身决定通信量。本章 Rank-8 LoRA 只有约 1650 万个可训练参数，DDP 同步的梯度远小于全参数 SFT；如果 LoRA 的 TCP/RDMA 差异很小，这是有意义的业务结论，不应外推为 RDMA 对继续预训练、FSDP/ZeRO 或大型 MoE 没有收益。

### 11.1 L20 单机与多机 TCP 初测

2026 年 8 月 20 日先在可用的 L20 上完成了一轮资源占用较小的初测。软件栈与前面的单卡实验相同，NCCL 版本为 2.28.9。通信微基准使用相同的 `world_size=2`：单机组是 `1 节点 × 2 GPU`，跨机组是 `2 节点 × 1 GPU`，两组都显式关闭 IB，并从 NCCL INFO 确认跨机组使用 `NET/Socket + eth0`。这样可以避免把 GPU 数量变化误当成网络差异。

| AllReduce 消息大小 | 单机双卡延迟 | 双机单卡 TCP 延迟 | 单机双卡 BusBw | 双机单卡 TCP BusBw |
| ---: | ---: | ---: | ---: | ---: |
| 1 MiB | 0.105 ms | 0.773 ms | 10.00 GB/s | 1.36 GB/s |
| 16 MiB | 1.164 ms | 10.306 ms | 14.42 GB/s | 1.63 GB/s |
| 64 MiB | 4.608 ms | 40.910 ms | 14.56 GB/s | 1.64 GB/s |
| 256 MiB | 18.342 ms | 163.131 ms | 14.63 GB/s | 1.65 GB/s |

在 256 MiB 消息上，跨节点 TCP 延迟约为单机双卡的 `8.89×`，BusBw 只有约 `11.2%`。这说明当前普通以太网确实是大消息集合通信的明显瓶颈，但微基准不能直接等价为训练会慢 8.89 倍。

随后用相同模型、数据 Hash、555 Token 样本、20 Step、Micro Batch 1 和 Global Batch 8 做 LoRA SFT 强扩展。512 条确定性样本的 SHA-256 是 `0782c78c725ee1d6f3ac9aab3ef91c65000d5841b551f4185eca66aa74080973`。双卡组按 `2 节点 × 1 GPU` 运行，梯度累积从单卡的 8 降为 4，因此每个 Optimizer Step 看到的数据量保持不变。

| 拓扑 | World Size | Global Batch | Train Runtime | samples/s | 峰值显存/GPU | 相对单卡加速 | 扩展效率 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 节点 × 1 L20 | 1 | 8 | 57.49 s | 2.783 | 9.05 GiB | 1.00× | 100% |
| 2 节点 × 1 L20，TCP | 2 | 8 | 33.41 s | 4.789 | 9.11 GiB | 1.72× | 86.0% |

即使 AllReduce 微基准显示 TCP 明显慢于单机互联，这个 Rank-8 LoRA 仍取得 `1.72×` 加速，训练时间减少约 `41.9%`。原因是它只有 1651 万个可训练参数，梯度同步量较小，计算仍占主要部分；这正说明必须同时看通信微基准和真实训练，不能只凭带宽推算业务收益。

以上数字只运行了一轮，适合做环境摸底，不是正式容量结论。单机双卡 SFT、更多卡数以及 TCP/RDMA 同拓扑 A/B 要等到对应空闲资源出现后，再按至少三轮取中位数的口径补齐。

## 12. 什么时候需要 Kubernetes

单卡 Smoke 阶段直接在已有 GPU 开发容器里运行最简单。满足下面任一条件后，再把命令封装成 Kubernetes Job、Kubeflow TrainJob 或 JobSet：

- 需要队列准入和 Gang Scheduling；
- 训练跨节点，需要稳定的 Rank、Service 和 RDMA 配置；
- 需要自动重试、抢占恢复和 Checkpoint 生命周期；
- 多人共享 GPU，必须记录镜像、配额、优先级和审计信息；
- 训练要成为可重复流水线，而不是一次性的终端命令。

Kubernetes 只负责资源和作业生命周期，不会修复错误的数据、Loss Mask、模型实现或并行策略。先在单卡容器中跑通，再做平台封装，能够明显缩短定位链路。

## 13. 实验记录模板

每次运行至少保存：

```text
run_id:
date:
git_commit:
model_id_or_path:
model_revision:
dataset_path:
dataset_hash:
swift_version:
torch_version:
cuda_version:
gpu_name_and_count:
train_dtype:
max_length:
micro_batch:
gradient_accumulation:
lora_rank_alpha:
train_steps:
peak_gpu_memory:
mean_step_time:
final_train_loss:
eval_result:
checkpoint_path:
known_limitations:
```

第一轮结果回填本章时，应同时记录失败尝试。OOM、转换错误、NCCL 初始化超时和无法被推理引擎加载，都是决定最终方案的重要证据。

## 14. 下一轮实验顺序

1. 已完成：单张 GPU 的 Qwen3-4B 20-Step Smoke、Adapter 保存和加载回归；
2. 已完成初测：单机双卡与双机单卡的 NCCL 对照，以及双机单卡 TCP 的 SFT 强扩展；
3. 资源可用后补齐：单机双卡 SFT，并把全部初测重复三轮取中位数；
4. 换成一份经过人工审核的真实小数据集，运行 100～500 Step，并用固定 Prompt 比较 Base 与 Adapter；
5. 已完成单张 L20 的加载边界与单机 8 × L20 的 BF16 LoRA 容量验证；下一轮补齐 30B Base/Adapter 盲测，并比较 FSDP/ZeRO-3 与 Expert Parallel；
6. 高显存与 RDMA 资源可用后，用相同拓扑完成 TCP/RDMA A/B，再运行 DeepSeek V4 Flash Adapter-only Smoke；
7. 只有正确性和评测通过后，才扩大数据、长度和训练时间，并设计多机全参数训练与 Checkpoint 基线。

这条路线把最便宜的错误留在单卡阶段，把昂贵 GPU 用在已经通过数据与训练闭环验证的问题上。

## 参考资料

- [ms-swift Quick Start](https://github.com/modelscope/ms-swift#-quick-start)
- [Don't Stop Pretraining：领域继续预训练](https://arxiv.org/abs/2004.10964)
- [LoRA：Low-Rank Adaptation of Large Language Models](https://arxiv.org/abs/2106.09685)
- [InstructGPT：SFT、Reward Model 与 RLHF](https://arxiv.org/abs/2203.02155)
- [Qwen3 使用 ms-swift 训练](https://github.com/QwenLM/Qwen3/blob/main/docs/source/training/ms_swift.md)
- [Megatron-SWIFT Quick Start](https://github.com/modelscope/ms-swift/blob/main/docs/source_en/Megatron-SWIFT/Quick-start.md)
- [Megatron-SWIFT DeepSeek V4 最佳实践](https://github.com/modelscope/ms-swift/blob/main/docs/source/BestPractices/deepseek-v4.md)
- [DeepSeek V4 官方模型卡](https://huggingface.co/deepseek-ai/DeepSeek-V4-Pro)
