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

## 2. 为什么先选 ms-swift 和 Qwen3-4B

ms-swift 官方快速开始给出了 `Qwen3-4B-Instruct-2507` 在单张 RTX 3090 上进行 LoRA SFT 的例子，标注显存占用约 13 GB；框架同时支持自定义 JSONL 数据、LoRA、推理和导出。这比第一次就安装 Megatron-Core、准备数百 GB 权重和占用八张高显存卡更适合排错。[ms-swift Quick Start](https://github.com/modelscope/ms-swift#-quick-start)

这里选择 4B 模型不是因为它的架构等价于 DeepSeek V4，而是因为以下内容可以复用：

- `messages` 对话数据格式；
- System/User/Assistant 角色和 Chat Template；
- LoRA 数据闭环和基础超参数；
- Checkpoint、Adapter 推理与训练前后评测方法；
- 镜像版本、数据版本和实验元数据记录方式。

不能直接复用的是 DeepSeek V4 的 Hybrid Attention、MoE Expert Parallel、MTP、FP4/FP8 权重转换和多机通信配置，这些在第二阶段单独验证。

## 3. 最小硬件与软件

### 3.1 单卡 Smoke Test

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

### 3.2 完整 DeepSeek V4 Flash LoRA

DeepSeek V4 Flash 有 284B 总参数、每 Token 激活 13B 参数；LoRA 只减少可训练参数和优化器状态，不会把 284B 基座变成 13B 模型。[DeepSeek V4 官方模型卡](https://huggingface.co/deepseek-ai/DeepSeek-V4-Pro)

当前公开的 Megatron-SWIFT LoRA 示例使用：

- 单机 8 GPU；
- `TP=1`、`EP=8`；
- 4K 最大训练长度；
- Full Recompute；
- BF16 LoRA Rank 16；
- MTP 1 层。

因此本章把 `8 × 96 GB` 视为完整 V4-Flash LoRA 的合理起点，`8 × 141 GB` 会有更充足的激活值和通信缓冲余量。`8 × 80 GB` 是否能稳定运行需要以精确 Checkpoint、加载精度和实测峰值显存为准，不能只用总显存相加判断。[Megatron-SWIFT DeepSeek V4 最佳实践](https://github.com/modelscope/ms-swift/blob/main/docs/source/BestPractices/deepseek-v4.md)

## 4. 五分钟准备最小实验

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

## 5. 看懂训练数据

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

## 6. 跑通单卡 LoRA

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

### 6.1 单张 L20 实测结果

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

## 7. 怎样判断不是“能跑但没学到”

准备至少三组固定问题：

| 组别 | 目的 | 例子 |
| --- | --- | --- |
| 域内未见题 | 看知识和回答规范是否泛化 | 给出一个训练集中没有的 GPU Pending 场景 |
| 通用保留题 | 检查灾难性遗忘 | 简单数学、摘要、常识和指令遵循 |
| 边界与拒答题 | 检查是否胡编或越权 | 信息不足时是否先指出缺失证据 |

每道题分别保存 Base 和 Adapter 的输出，固定 Prompt、Temperature、Seed 和最大输出长度。只有当域内指标改善、通用能力没有明显回退，才扩大数据和训练步数。

Loss 降低只是优化器拟合了训练 Token，不等于答案更可靠。十几条 Smoke 数据尤其容易在几步内过拟合。

## 8. 升级到小型 MoE

在投入完整 V4 前，可以用 Qwen3-30B-A3B 一类较小 MoE 验证：

- Expert 权重是否被 LoRA 覆盖；
- Router 是否冻结，或是否需要辅助均衡 Loss；
- Grouped GEMM 和 MoE Kernel 是否正常；
- 多卡 Expert Parallel 的 All-to-All 是否符合预期。

ms-swift 的官方 MoE LoRA 示例提醒：如果不希望训练 Router，应显式限制 `target_modules` 为 Attention 和 MLP 投影层，而不是盲目匹配所有参数。[Qwen3 MoE LoRA 示例](https://github.com/modelscope/ms-swift/blob/main/examples/train/moe/qwen3_moe.sh)

这个阶段的目标是验证 MoE 训练行为，不要把“小型 MoE 能用 Transformers + PEFT 训练”外推为 DeepSeek V4 的特殊 Attention 和 Checkpoint 格式已经兼容。

## 9. 升级到完整 DeepSeek V4 Flash

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

## 10. 什么时候需要 Kubernetes

单卡 Smoke 阶段直接在已有 GPU 开发容器里运行最简单。满足下面任一条件后，再把命令封装成 Kubernetes Job、Kubeflow TrainJob 或 JobSet：

- 需要队列准入和 Gang Scheduling；
- 训练跨节点，需要稳定的 Rank、Service 和 RDMA 配置；
- 需要自动重试、抢占恢复和 Checkpoint 生命周期；
- 多人共享 GPU，必须记录镜像、配额、优先级和审计信息；
- 训练要成为可重复流水线，而不是一次性的终端命令。

Kubernetes 只负责资源和作业生命周期，不会修复错误的数据、Loss Mask、模型实现或并行策略。先在单卡容器中跑通，再做平台封装，能够明显缩短定位链路。

## 11. 实验记录模板

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

## 12. 下一轮实验顺序

1. 在一张 GPU 上运行仓库的 Qwen3-4B 20-Step Smoke；
2. 用固定 Prompt 比较 Base 与 Adapter，保存原始输出；
3. 换成一份经过人工审核的真实小数据集，运行 100～500 Step；
4. 如果最终目标是 MoE，先用小型 MoE 验证 Router、Expert LoRA 和通信；
5. 准备单机八卡高显存节点，运行 DeepSeek V4 Flash Adapter-only Smoke；
6. 只有正确性和评测通过后，扩大数据、长度和训练时间；
7. 最后再设计多机全参数训练、Checkpoint 和 RDMA 基线。

这条路线把最便宜的错误留在单卡阶段，把昂贵 GPU 用在已经通过数据与训练闭环验证的问题上。

## 参考资料

- [ms-swift Quick Start](https://github.com/modelscope/ms-swift#-quick-start)
- [Qwen3 使用 ms-swift 训练](https://github.com/QwenLM/Qwen3/blob/main/docs/source/training/ms_swift.md)
- [Megatron-SWIFT Quick Start](https://github.com/modelscope/ms-swift/blob/main/docs/source_en/Megatron-SWIFT/Quick-start.md)
- [Megatron-SWIFT DeepSeek V4 最佳实践](https://github.com/modelscope/ms-swift/blob/main/docs/source/BestPractices/deepseek-v4.md)
- [DeepSeek V4 官方模型卡](https://huggingface.co/deepseek-ai/DeepSeek-V4-Pro)
