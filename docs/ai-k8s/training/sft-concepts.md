---
title: 大模型 SFT 入门：把 Loss、LoRA、Batch 和并行一次讲明白
description: 面向第一次接触大模型训练的读者，用一个完整例子解释 SFT、Token、Loss、LoRA、QLoRA、Batch、Epoch、Checkpoint、Dense、MoE、DP、TP、PP、EP、ZeRO 和效果评测
status: evolving
last_reviewed: 2026-08-24
---

# 大模型 SFT 入门：把 Loss、LoRA、Batch 和并行一次讲明白

第一次看大模型训练资料，最难的往往不是代码，而是每一句话里都有新名词：SFT、Loss、LoRA、Rank、Batch、Epoch、DP、EP、ZeRO、Checkpoint。单独查每个词都能找到解释，连在一起却仍然不知道“一次训练到底发生了什么”。

本文不从框架命令开始，而是用一个小型故障分诊助手贯穿全文。读完后，应该能够回答四个问题：

1. SFT 究竟在教模型什么；
2. 一条问答数据怎样变成一次参数更新；
3. Loss、Batch、Epoch 和 LoRA 参数分别代表什么；
4. 为什么模型变大后会出现 DP、TP、PP、EP 和 ZeRO。

第一次阅读不必强行记住所有缩写。建议先读第 1～6 节理解 SFT 和 LoRA，再读第 12～18 节理解“怎样判断训练有效”；只有准备多卡训练时，才需要细读第 9～11 节。第 20 节可以随时当词典查阅。

## 1. 一分钟理解 SFT

假设基础模型已经会说话，但它遇到 Kubernetes 故障时回答不稳定：有时给出正确排查步骤，有时直接建议删除资源，也不会输出团队规定的故障码。

我们准备一批“问题和理想答案”：

```text
问题：Pod 一直 Pending，Event 显示 GPU 资源不足，应该怎么处理？

理想答案：
故障码：SCH-103
判断：GPU 资源不足，Pod 尚未获得调度。
动作：检查节点可分配 GPU、队列配额和同批任务占用情况。
禁止：不要通过删除其他团队的 Pod 强行释放资源。
```

SFT 就是让模型反复阅读这样的样本，并在它预测理想答案不够准确时，小幅调整参数。经过许多次调整后，模型更可能稳定输出规定的结构、术语和处理流程。

```text
基础模型
   + 高质量问题与理想答案
   + 监督训练
   = 更符合目标行为的模型或 Adapter
```

SFT 的英文是 **Supervised Fine-Tuning**，中文通常叫“监督微调”：

- **监督**：训练数据里有希望模型给出的理想答案；
- **微调**：不是从零训练，而是在已有模型上继续调整；
- **目标**：通常是改变回答方式、任务流程、格式和领域行为。

SFT 更像“教会一个已经识字的新员工按照规范工作”，而不是“从小学开始重新教育一个人”。

## 2. SFT、预训练、RAG 和偏好对齐不是一回事

| 方法 | 可以把它理解成 | 更适合解决的问题 |
| --- | --- | --- |
| 预训练 | 从海量文本中学习语言和知识 | 从零形成基础能力 |
| 继续预训练 | 继续阅读大量行业原始资料 | 熟悉领域术语、文体和知识分布 |
| SFT | 学习“遇到这种问题应该怎样回答” | 指令遵循、固定格式、任务流程和工具轨迹 |
| DPO/RLHF/GRPO | 学习多个答案中哪个更好 | 偏好、安全边界和复杂策略 |
| RAG | 回答前临时查资料 | 最新、私有、可引用的事实 |

一个常见误区是希望用几十条 SFT 样本向模型灌入大量事实。SFT 可以让模型记住部分内容，但它更擅长改变行为。如果目标是查询经常变化的产品价格、内部制度或故障记录，RAG 通常比把事实写进模型参数更合适。

## 3. 一条对话怎样进入模型

训练数据常以 JSONL 保存，一行是一条样本：

```json
{
  "messages": [
    {"role": "system", "content": "你是一个谨慎的基础设施助手。"},
    {"role": "user", "content": "Pod Pending 应该先看什么？"},
    {"role": "assistant", "content": "先查看 Pod Event，再检查资源、污点和队列配额。"}
  ]
}
```

这条数据不会原样进入 GPU，中间还要经过三步。

### 3.1 Chat Template：把多轮消息拼成模型认识的格式

不同模型表示角色和轮次的方法不同。Chat Template 会把结构化消息转换成一段文本，例如：

```text
<system>
你是一个谨慎的基础设施助手。
<user>
Pod Pending 应该先看什么？
<assistant>
先查看 Pod Event，再检查资源、污点和队列配额。
```

训练和推理必须使用兼容的 Template。训练时用一种格式，部署时用另一种格式，可能出现 Loss 很低但实际对话效果不对的情况。

### 3.2 Tokenizer：把文字切成数字

模型不直接读取汉字或英文，而是读取 Token ID。Tokenizer 会把文字切成 Token：

```text
“先查看 Pod Event”
        ↓ Tokenizer
[18493, 9231, 442, 13872, ...]
```

Token 不等于字符，也不等于单词。相同一句话在不同 Tokenizer 下可能得到不同长度。因此训练规模和费用通常用 Token 数，而不是文件大小或汉字数衡量。

### 3.3 Loss Mask：决定哪些 Token 算错题

常见 SFT 只要求模型学习 Assistant 的答案，不要求它重新预测 System 和 User 内容：

```text
System    不计算 Loss
User      不计算 Loss
Assistant 计算 Loss
```

在许多训练实现中，不参与 Loss 的位置会把 Label 设置为 `-100`：

```text
输入 Token： [System...] [User...] [Assistant...]
训练 Label： [-100 ...]  [-100...] [答案 Token...]
```

这叫 **Assistant Loss Mask**。Mask 配错是最隐蔽的问题之一：作业可能正常运行，Loss 也可能下降，但模型学到的是复述问题、角色标记或无关模板。

## 4. 一次训练 Step 到底发生什么

一次最基本的参数更新可以拆成四步：

```text
输入一批样本
    ↓
Forward：模型给出每个下一个 Token 的预测
    ↓
Loss：比较预测和理想答案相差多少
    ↓
Backward：计算每个可训练参数应该往哪个方向调整
    ↓
Optimizer Step：真正更新参数
```

| 名词 | 直白解释 |
| --- | --- |
| Forward | 用当前模型完成一次预测 |
| Loss | 当前预测和标准答案之间的误差 |
| Backward | 计算误差应该如何传回各层参数 |
| Gradient | 参数应该调整的方向和相对幅度 |
| Optimizer | 根据 Gradient 更新参数的算法，例如 AdamW |
| Learning Rate | 每次更新走多大一步 |
| Step | 通常指完成一次 Optimizer 参数更新 |

Learning Rate 太大，模型可能震荡、出现 NaN，甚至破坏原有能力；太小则训练很久也没有明显变化。

训练命令里还经常出现三个相关词：

- **Warmup**：训练刚开始时先用较小 Learning Rate，再逐渐升到目标值；
- **Scheduler**：规定 Learning Rate 在整个训练过程中怎样升降；
- **Gradient Clipping**：Gradient 过大时限制其范围，降低突然爆炸的风险。

## 5. Sample、Token、Batch、Step 和 Epoch

这些词都在描述“训练了多少”，但单位不同。

| 名词 | 含义 |
| --- | --- |
| Sample | 一条训练样本，例如一轮或多轮对话 |
| Token | 模型实际处理的最小文字单位 |
| Sequence Length | 一条送入模型的序列最多允许多少 Token |
| Micro Batch | 一张 GPU 一次 Forward/Backward 处理的样本数 |
| Gradient Accumulation | 累积几次小 Batch 后再更新一次参数 |
| Global Batch | 所有数据并行副本在一次参数更新中合计处理的样本数 |
| Step | 完成一次参数更新 |
| Epoch | 把整个训练集大致看完一遍 |

Global Batch 的常用计算方式是：

```text
Global Batch
= 每张 GPU 的 Micro Batch
× Gradient Accumulation
× Data Parallel Size
```

例如：

```text
Micro Batch = 1
Gradient Accumulation = 8
Data Parallel Size = 2

Global Batch = 1 × 8 × 2 = 16
```

如果训练集有 800 条样本：

```text
每个 Epoch 的 Step 数 ≈ 800 ÷ 16 = 50
训练 3 个 Epoch ≈ 150 Step
```

TP、PP 和 EP 通常不会直接乘进这个公式，因为这些 GPU 在协作处理同一份数据；只有不同 DP 副本通常会读取不同样本。

### 5.1 为什么需要 Gradient Accumulation

显存放不下 16 条样本时，可以一次只处理 1 条，连续累积 8 次 Gradient，再进行一次参数更新。它用更多时间换取更低的瞬时显存需求。

### 5.2 Sequence Length 为什么很重要

`max_length=512` 表示一条训练序列最多保留 512 Token。过长样本可能被截断，过短样本可能被 Padding 补齐。序列越长，Activation 通常越占显存，Attention 计算也更贵。

### 5.3 Packing 是什么

如果很多样本都远短于最大长度，单独 Padding 会浪费计算。Packing 会把几条短样本安全地拼进一个较长序列，提高有效 Token 比例。它必须正确处理样本边界、位置编码和 Loss Mask，否则前一条样本可能错误影响后一条样本。

## 6. Full SFT、LoRA 和 QLoRA

### 6.1 Full SFT：修改整个模型

Full SFT 允许所有模型参数参与训练，表达能力最强，但需要为大量参数保存 Gradient 和 Optimizer State，显存、通信和 Checkpoint 成本都很高。

### 6.2 LoRA：只训练一小组增量参数

LoRA 不直接改动大部分基础模型权重，而是在部分层旁边增加一组很小的可训练矩阵。可以把它理解成：

```text
原模型回答
  + 一张可学习的“行为修正贴纸”
  = 微调后的回答
```

训练完成后，这张“贴纸”通常保存为 Adapter。基础模型可能有几十 GB，Adapter 往往小得多。

| LoRA 参数 | 它控制什么 |
| --- | --- |
| Rank | Adapter 的表达容量；越大通常参数越多、显存和计算越高 |
| Alpha | 对 LoRA 更新幅度的缩放 |
| Dropout | 训练时随机丢弃部分 LoRA 路径，帮助降低过拟合风险 |
| Target Modules | LoRA 要挂到哪些模型层，例如 Attention 投影层 |

Rank 不是“训练轮数”，Alpha 也不是 Learning Rate。它们属于 Adapter 的结构配置。

### 6.3 QLoRA：量化基础模型，再训练 LoRA

QLoRA 通常把基础模型以较低位宽加载，从而减少权重占用；计算时再按需要解量化，而真正更新的仍是 LoRA Adapter。

```text
低位宽、冻结的基础模型
        +
BF16/FP16 等精度训练的 LoRA
```

QLoRA 不等于“把整个 4-bit 模型做全参数训练”。模型架构、量化格式和 Kernel 也必须被训练框架支持。

### 6.4 三种方法怎么选

| 方法 | 资源需求 | 适合第一次实验吗 | 主要限制 |
| --- | ---: | --- | --- |
| Full SFT | 高 | 通常不适合从大模型开始 | 显存、通信和 Checkpoint 成本高 |
| LoRA | 中 | 最适合 | 需要选对目标层，能力上限受 Adapter 结构影响 |
| QLoRA | 较低 | 显存紧张时适合 | 依赖量化训练兼容性，速度不一定更快 |

无论 LoRA 还是 QLoRA，基础模型仍然需要加载；不能只根据 Adapter 文件只有几百 MB，就认为训练只需要几百 MB 显存。

## 7. 训练显存都被谁用了

推理主要需要模型权重和 KV Cache，训练则多出几类数据：

```text
模型权重
+ Gradient
+ Optimizer State
+ Activation
+ 临时计算与通信 Buffer
```

| 名词 | 用途 |
| --- | --- |
| Weight | 模型当前参数 |
| Gradient | 这一轮参数应该如何变化 |
| Optimizer State | 优化器为每个参数保存的历史状态 |
| Activation | Forward 中间结果，Backward 时还要使用 |
| Buffer | Attention、量化、通信等临时空间 |

常见省显存手段包括 LoRA/QLoRA、Gradient Checkpointing、降低 Micro Batch、缩短 Sequence Length、ZeRO/FSDP 分片和 CPU Offload。它们的代价可能是训练变慢、通信增多或实现更复杂。

这里的 **Gradient Checkpointing** 容易和保存模型的 Checkpoint 混淆：它不是把模型写入磁盘，而是少保存一部分 Activation，在 Backward 时重新计算，用额外算力换显存。

## 8. BF16、FP16、FP8、INT4 和 NF4 是什么

这些名字描述数字用多少位以及怎样编码。

| 格式 | 常见用途 | 直观特点 |
| --- | --- | --- |
| FP32 | 高精度计算、部分关键状态 | 精度高，占用大 |
| BF16 | 大模型训练常用计算精度 | 动态范围较好，每个值 2 Byte |
| FP16 | 训练和推理 | 每个值 2 Byte，动态范围和 BF16 不同 |
| FP8 | 低精度训练或推理路径 | 更省显存和带宽，但依赖硬件与 Kernel |
| INT4/NF4 | 量化权重、QLoRA | 权重更小，需要量化兼容路径 |

“模型文件是 FP8”不代表所有训练计算都使用 FP8。框架可能以 FP8 保存或加载权重，但在部分 Forward、Backward 或 LoRA 路径中使用 BF16。

## 9. Dense 和 MoE 模型

### 9.1 Dense：每个 Token 大致经过同一套参数

Dense 模型的每一层通常都会参与每个 Token 的计算。一个 4B Dense 模型可以粗略理解为每个 Token 都会使用这套约 4B 参数的网络。

### 9.2 MoE：每个 Token 只选择部分 Expert

MoE 是 Mixture of Experts。模型包含许多 Expert，Router 会为每个 Token 选择其中一部分：

```text
Token
  ↓
Router 判断应该交给谁
  ↓
Expert 2 + Expert 7 参与本次计算
```

`35B-A3B` 一类名字通常表达“总参数约 35B，每个 Token 激活约 3B 参数”。但它不表示模型权重只占 3B 参数的显存：所有 Expert 权重仍需要放在一张或多张 GPU 上。

MoE 训练还要关注：

- Router 是否把 Token 过度集中到少数 Expert；
- Expert 之间是否负载均衡；
- LoRA 是否真的覆盖到 Expert 参数；
- 多卡之间的 All-to-All 通信是否成为瓶颈。

## 10. DP、TP、PP、EP 到底怎样分工

把一个超大模型训练任务想成一家餐厅：有很多订单、厨房很大，还有多组不同厨师。

| 并行方式 | 餐厅类比 | GPU 实际在分什么 |
| --- | --- | --- |
| DP：Data Parallel | 多个相同厨房各自处理不同订单 | 不同 GPU 处理不同训练样本 |
| TP：Tensor Parallel | 几名厨师一起切同一块巨大食材 | 同一层的矩阵计算被拆开 |
| PP：Pipeline Parallel | 前菜、主菜、甜点分到不同工位 | 不同模型层放在不同 GPU/节点 |
| EP：Expert Parallel | 不同专科厨师处理不同类型订单 | MoE Expert 分布到不同 GPU |

### 10.1 DP：模型相同，数据不同

每个 DP 副本处理不同样本，之后同步 Gradient。DP 最容易提升吞吐，但每个副本都要能容纳模型，或者结合 FSDP/ZeRO 分片。

### 10.2 TP：一层太大，拆开算

TP 把同一个矩阵计算分到多张 GPU。它通常需要频繁通信，因此更依赖节点内高速互联或低延迟网络。

### 10.3 PP：模型层首尾相接

PP 把前几层、中间层和后几层放在不同 GPU。数据像流水线一样依次流过各阶段。阶段切分不均或 Micro Batch 太少时，会出现部分 GPU 等待的 Pipeline Bubble。

### 10.4 EP：把不同 Expert 分开放

EP 专门服务 MoE。Router 选中某个 Expert 后，Token 可能需要通过 All-to-All 发送到持有该 Expert 的 GPU，再把结果传回来。

### 10.5 它们可以组合

一个大型 MoE 任务可能同时使用：

```text
2 个 Pipeline Stage
× 每个 Stage 8 路 Expert Parallel
× 2 份 Data Parallel
= 32 张 GPU
```

这并不表示 Global Batch 要乘上所有 32 张 GPU。计算 Batch 时应确认框架最终推导出的 DP Size。

## 11. DDP、FSDP 和 ZeRO 与 DP 有什么关系

它们都与数据并行有关，但保存模型状态的方式不同。

| 方式 | 每张 GPU 保存什么 | 主要目标 |
| --- | --- | --- |
| DDP | 通常保存完整权重、Gradient 和 Optimizer State | 简单地复制模型、扩大数据吞吐 |
| FSDP | 把参数、Gradient 和 Optimizer State 分片 | 让更大的模型装进多张 GPU |
| ZeRO-1 | 主要分片 Optimizer State | 先节省优化器显存 |
| ZeRO-2 | 再分片 Gradient | 进一步节省显存 |
| ZeRO-3 | 再分片模型参数 | 最大程度避免每卡保存完整模型 |

分片减少了单卡显存，却需要在计算过程中进行 All-Gather、Reduce-Scatter 等通信。网络越慢，分片越细，通信等待越可能明显。

## 12. Loss 曲线应该怎样看

Loss 越低，表示模型在当前数据和 Mask 口径下越容易预测标准答案。但 Loss 不是业务准确率。

模型不只会做训练时见过的题，还能处理同类新题，叫 **泛化（Generalization）**；只把训练数据记得越来越熟、面对新题反而变差，叫 **过拟合（Overfitting）**。

| 指标 | 它回答什么 | 不能单独证明什么 |
| --- | --- | --- |
| Train Loss | 模型对训练数据是否越来越熟悉 | 对新问题是否有效 |
| Validation Loss | 对未参与更新的数据是否也在改善 | 业务任务一定正确 |
| Token Accuracy | 标准答案 Token 预测正确的比例 | 完整回答和任务逻辑正确 |
| Gradient Norm | 梯度是否异常大或异常小 | 模型最终质量 |
| Learning Rate | 当前参数更新步长 | 训练是否有效 |
| Tokens/s | 训练吞吐 | 模型质量 |
| GPU 利用率 | GPU 是否繁忙 | 有效算力是否都用于目标计算 |

典型曲线判断：

```text
Train Loss 下降，Validation Loss 也下降
→ 仍在学习并具备一定泛化

Train Loss 继续下降，Validation Loss 开始上升
→ 可能过拟合

Loss 突然变成 NaN
→ 检查 Learning Rate、精度、异常样本和梯度

Loss 很低，但模型回答没有变化
→ 检查 Adapter 是否加载、Template 和 Loss Mask
```

不同模型、Tokenizer、数据集和 Mask 得到的 Loss 通常不能直接横向比较。

## 13. Train、Validation、Test 和 Blind Test

| 数据集 | 用途 | 能否用于调参 |
| --- | --- | --- |
| Train | 计算 Gradient 并更新模型 | 是 |
| Validation | 选择学习率、Step 和最佳 Checkpoint | 是，但不能反复手工泄漏答案 |
| Test | 最终评估 | 不应参与训练和调参 |
| Blind Test | 在模板、场景或答案上刻意隔离的最终测试 | 不应提前查看并针对性修改 |

如果同一个问题换几个数字后同时进入 Train 和 Test，分数可能很好看，但只能证明模型记住了模板。数据切分应该尽量按场景、来源、时间或模板族隔离。

真正有意义的验证通常比较：

```text
同一个 Base Model
同一套推理参数
同一批从未用于训练的题
        ↓
Base 输出 vs 加载 Adapter 后的输出
```

除了准确率，还要观察格式遵循率、拒答边界、幻觉、通用能力回退和危险动作。

## 14. Base、Adapter、Checkpoint 和 Merge

| 名词 | 含义 |
| --- | --- |
| Base Model | 开始微调前的基础模型 |
| Adapter | LoRA 等方法训练得到的增量参数 |
| Checkpoint | 某个训练时刻保存的状态快照 |
| Optimizer Checkpoint | 包含优化器等状态，可用于继续训练 |
| Merged Model | 把 LoRA 增量合并进基础权重后的模型 |

只保存 Adapter 通常足以加载微调效果，却不一定能无损恢复训练。要断点续训，还需要 Optimizer、Scheduler、随机数和数据采样进度等状态。

Adapter 还必须与正确的 Base Model、Tokenizer 和 Template 配对。给错基础模型，即使文件能加载，结果也可能错误。

## 15. Smoke Test 和有效训练不是一回事

### 15.1 Smoke Test 证明工程链路能走通

一个 5～20 Step 的 Smoke Test 适合确认：

- 模型能加载；
- 数据格式和 Template 没报错；
- Forward、Backward 和保存 Checkpoint 成功；
- Loss 不是 NaN/Inf；
- Adapter 能重新加载。

它不能证明模型效果已经提升。

### 15.2 有意义的训练还要证明行为改变

至少需要：

- 独立的 Train、Validation 和 Blind Test；
- Base/Adapter 使用相同推理参数做 A/B；
- 保存训练曲线和最佳 Checkpoint 选择依据；
- 对错误样本分类，而不只看一个总分；
- 检查模型是否损害原有通用能力。

## 16. 怎样读懂一条 SFT 命令

下面不是唯一正确参数，只用来说明常见字段：

```bash
swift sft \
  --model /models/base-model \
  --dataset train.jsonl \
  --train_type lora \
  --lora_rank 8 \
  --lora_alpha 16 \
  --max_length 512 \
  --per_device_train_batch_size 1 \
  --gradient_accumulation_steps 8 \
  --learning_rate 1e-4 \
  --num_train_epochs 3
```

| 参数 | 白话解释 |
| --- | --- |
| `model` | 从哪个基础模型开始 |
| `dataset` | 用哪些标准答案训练 |
| `train_type=lora` | 只训练 LoRA Adapter |
| `lora_rank=8` | Adapter 的低秩容量 |
| `lora_alpha=16` | LoRA 更新缩放 |
| `max_length=512` | 每条序列最多 512 Token |
| `per_device_train_batch_size=1` | 每张 GPU 一次只放 1 条样本 |
| `gradient_accumulation_steps=8` | 累积 8 次再更新参数 |
| `learning_rate=1e-4` | 每次更新的步长 |
| `num_train_epochs=3` | 训练集大致看 3 遍 |

看到训练命令时，不要先问“用了几张卡”，而应先确认模型、数据、Mask、训练方法、Global Batch、长度、Learning Rate、总 Token 和评测方式。

## 17. 常见症状与排查方向

| 症状 | 优先检查 |
| --- | --- |
| 一启动就 OOM | 基础权重精度、Sequence Length、Micro Batch、Activation、Optimizer、分片策略 |
| Loss 从第一步就接近 0 | Label/Mask 是否把答案也屏蔽了，数据是否重复 |
| Loss 不下降 | 数据格式、Template、Target Modules、Learning Rate、Adapter 是否真的可训练 |
| Loss 变 NaN | Learning Rate、精度溢出、异常样本、Gradient Clip |
| Train Loss 降、Validation Loss 升 | 过拟合、数据太少或分布不一致 |
| Adapter 加载后回答没变化 | Adapter 路径、Base 版本、Template、推理服务是否真的启用 LoRA |
| 多卡不比单卡快 | Global Batch、数据加载、通信、模型太小、LoRA Gradient 太少 |
| MoE 训练了但 Expert 没变化 | LoRA Target Modules 是否覆盖 Expert，Router/Expert 参数是否可训练 |
| GPU 利用率很低 | CPU Tokenization、数据读取、Checkpoint、跨卡等待、单进程层切分 |

## 18. 第一次实验应该做到多大

第一次不建议直接从数百 B 的 MoE 模型开始。一个更容易理解和验收的起点是：

| 项目 | 建议起点 |
| --- | --- |
| 模型 | 约 4B 的指令模型 |
| GPU | 单张显存足够的 GPU |
| 方法 | BF16 LoRA；显存不足再评估 QLoRA |
| 数据 | 数百条 Train、几十条 Validation、约百条 Blind Test |
| 长度 | 先从 256～512 Token 开始 |
| Step | 先做 20 Step Smoke，再做 100～500 Step 有效实验 |
| 验收 | Loss 曲线 + Base/Adapter Blind A/B |

推荐的学习顺序是：

```text
先看懂一条样本
  ↓
确认 Chat Template 与 Loss Mask
  ↓
单卡 LoRA Smoke
  ↓
完成 Base/Adapter 盲测
  ↓
再扩大模型、数据和 GPU 数量
  ↓
最后比较多机 TCP/RDMA 与复杂并行
```

## 19. 一次实验至少记录什么

没有记录的训练很难复现，也很难解释为什么这次比上次好。

```yaml
base_model: 精确版本或哈希
tokenizer_and_template: 名称与版本
dataset_hash: 数据哈希
train_validation_test_split: 切分规则
train_method: full / lora / qlora
lora_config: rank / alpha / dropout / target_modules
precision: 权重、计算与通信精度
sequence_length: 最大长度
micro_batch: 每卡 Micro Batch
gradient_accumulation: 累积次数
data_parallel_size: DP Size
global_batch: 最终有效 Batch
learning_rate: 学习率与调度方式
total_steps_or_tokens: 总 Step 或 Token
hardware: GPU 型号与数量
software: 框架、PyTorch、CUDA/NCCL 版本
checkpoint: 最佳与最终 Checkpoint
evaluation: Base/Adapter 指标和错误分类
known_limitations: 已知限制
```

## 20. 名词速查表

| 名词 | 一句话解释 |
| --- | --- |
| Activation | Forward 产生、Backward 还要使用的中间结果 |
| Adapter | LoRA 等方法训练出的增量参数 |
| Backward | 从 Loss 反推各参数 Gradient |
| Batch | 一次参数更新涉及的一组样本 |
| Checkpoint | 训练某个时刻保存的状态 |
| Chat Template | 把 System/User/Assistant 消息拼成模型格式的规则 |
| Dense | 每个 Token 大致使用同一套模型层 |
| DP | 多份模型处理不同数据，再同步 Gradient |
| Epoch | 大致遍历完整训练集一次 |
| EP | 把 MoE Expert 分布到不同 GPU |
| Eval/Validation | 在不更新参数的数据上检查泛化 |
| Forward | 使用当前参数完成预测 |
| FSDP | PyTorch 的全分片数据并行方案 |
| Global Batch | 一次参数更新合计处理的样本数 |
| Gradient | 参数应该怎样调整 |
| Gradient Accumulation | 多次累积梯度后再更新参数 |
| Gradient Checkpointing | 少存 Activation、Backward 时重算，用计算换显存 |
| Gradient Clipping | 限制过大的 Gradient，降低数值爆炸风险 |
| Generalization | 模型把学到的规律用于未见过的同类数据 |
| Label | 训练希望模型预测出的目标 Token |
| Learning Rate | 参数每次更新的步长 |
| LoRA | 用小型低秩 Adapter 代替全参数更新 |
| Loss | 当前预测与标准答案的误差 |
| Mask | 指定哪些 Token 参与 Loss |
| Micro Batch | 每张 GPU 一次处理的样本数 |
| MoE | 包含多个 Expert、每个 Token 只激活一部分的模型 |
| OOM | 显存或内存不足 |
| Optimizer | 根据 Gradient 更新参数的算法 |
| Overfitting | 训练数据越来越好、新数据反而变差的过拟合现象 |
| Packing | 把多条短样本拼入较长序列以减少 Padding 浪费 |
| Padding | 用占位 Token 把不同长度样本补齐 |
| PP | 把不同模型层放到不同 GPU 的流水线并行 |
| QLoRA | 量化加载基础模型并训练 LoRA |
| Rank | LoRA Adapter 的低秩维度 |
| Router | MoE 中为 Token 选择 Expert 的模块 |
| Scheduler | 控制 Learning Rate 随训练进度变化的规则 |
| SFT | 使用问题与理想答案进行监督微调 |
| Step | 完成一次 Optimizer 参数更新 |
| Token | 模型读取和预测的最小文本单位 |
| Tokenizer | 把文字转换为 Token ID 的组件 |
| TP | 把同一层矩阵计算拆到不同 GPU |
| Truncation | 样本超过最大长度后截掉一部分 Token |
| Warmup | 训练初期逐步提高 Learning Rate |
| ZeRO | DeepSpeed 的训练状态分片方案 |

## 21. 从概念进入实战

理解本文名词后，可以按下面顺序继续：

1. [大模型 SFT 训练实战：从单卡 LoRA 到 DeepSeek V4](sft-from-single-gpu-to-deepseek-v4.md)：查看真实 Qwen、MoE、DeepSeek V4、单机和多机实验；
2. [SwanLab 自托管：从 Kubernetes 部署到真实 SFT 指标](swanlab-self-hosted.md)：查看 Loss、Learning Rate、Gradient Norm 与 GPU 指标；
3. [分布式训练平台](../distributed-training.md)：理解训练任务怎样由 Kubernetes 调度、启动和恢复；
4. [`examples/llm-sft-lab`](https://github.com/runzhliu/aik8s/tree/main/examples/llm-sft-lab)：获取可以运行的脚本、示例数据和结果记录。

最重要的判断标准只有一句：**训练成功不是“作业退出码为 0”或“Loss 降了”，而是数据、优化、Checkpoint、推理和独立评测形成了可复现闭环。**

## 参考资料

- [LoRA：Low-Rank Adaptation of Large Language Models](https://arxiv.org/abs/2106.09685)
- [QLoRA：Efficient Finetuning of Quantized LLMs](https://arxiv.org/abs/2305.14314)
- [InstructGPT：SFT、Reward Model 与 RLHF](https://arxiv.org/abs/2203.02155)
- [Hugging Face PEFT LoRA 文档](https://huggingface.co/docs/peft/package_reference/lora)
- [PyTorch Fully Sharded Data Parallel](https://docs.pytorch.org/docs/stable/fsdp.html)
- [DeepSpeed ZeRO](https://www.deepspeed.ai/tutorials/zero/)
- [NVIDIA Megatron Core 并行指南](https://docs.nvidia.com/megatron-core/developer-guide/latest/user-guide/index.html)
