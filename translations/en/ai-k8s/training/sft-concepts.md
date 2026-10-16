---
title: "Getting Started with LLM SFT: Loss, LoRA, Batch, and Parallelism Explained in One Go"
description: "For readers encountering LLM training for the first time, this guide uses one complete example to explain SFT, Token, Loss, LoRA, QLoRA, Batch, Epoch, Checkpoint, Dense, MoE, DP, TP, PP, EP, ZeRO, and evaluation"
status: evolving
last_reviewed: 2026-08-24
---

# Getting Started with LLM SFT: Loss, LoRA, Batch, and Parallelism Explained in One Go

The hardest part of reading LLM training material for the first time is usually not the code, but the fact that every sentence contains a new term: SFT, Loss, LoRA, Rank, Batch, Epoch, DP, EP, ZeRO, Checkpoint. You can find an explanation for each term individually, but when put together, you still don't know "what actually happens during a training run."

This article does not start from framework commands. Instead, it uses a small fault triage assistant as a running example throughout. After reading, you should be able to answer four questions:

1. What exactly SFT teaches the model;
2. How one Q&A data item becomes one parameter update;
3. What Loss, Batch, Epoch, and LoRA parameters each represent;
4. Why DP, TP, PP, EP, and ZeRO appear as models get larger.

On a first read, you don't need to force yourself to memorize every abbreviation. It is recommended to read Sections 1–6 first to understand SFT and LoRA, then read Sections 12–18 to understand "how to judge whether training is effective"; only when preparing for multi-GPU training do you need to read Sections 9–11 in detail. Section 20 can be used as a glossary at any time.

## 1. Understanding SFT in One Minute

Assume the base model can already speak, but its answers are unstable when it encounters Kubernetes failures: sometimes it gives the correct troubleshooting steps, sometimes it directly suggests deleting resources, and it also fails to output the fault codes required by the team.

We prepare a batch of "questions and ideal answers":

```text
问题：Pod 一直 Pending，Event 显示 GPU 资源不足，应该怎么处理？

理想答案：
故障码：SCH-103
判断：GPU 资源不足，Pod 尚未获得调度。
动作：检查节点可分配 GPU、队列配额和同批任务占用情况。
禁止：不要通过删除其他团队的 Pod 强行释放资源。
```

SFT is about having the model repeatedly read such samples and slightly adjust parameters when its prediction of the ideal answer is not accurate enough. After many adjustments, the model is more likely to stably output the required structure, terminology, and handling process.

```text
基础模型
   + 高质量问题与理想答案
   + 监督训练
   = 更符合目标行为的模型或 Adapter
```

The English term for SFT is **Supervised Fine-Tuning**:

- **Supervised**: the training data contains the ideal answers we want the model to produce;
- **Fine-Tuning**: not training from scratch, but continuing to adjust an existing model;
- **Goal**: usually to change response style, task workflow, format, and domain behavior.

SFT is more like "teaching a new employee who can already read to work according to the rules" than "re-educating a person from elementary school."

## 2. SFT, Pretraining, RAG, and Preference Alignment Are Not the Same Thing

| Method | You can think of it as | Problems it is better suited to solve |
| --- | --- | --- |
| Pretraining | Learning language and knowledge from massive text | Forming foundational capabilities from scratch |
| Continued Pretraining | Continuing to read large amounts of raw industry material | Becoming familiar with domain terminology, writing style, and knowledge distribution |
| SFT | Learning "how to answer when encountering this kind of problem" | Instruction following, fixed formats, task workflows, and tool trajectories |
| DPO/RLHF/GRPO | Learning which answer is better among multiple answers | Preferences, safety boundaries, and complex policies |
| RAG | Looking up information temporarily before answering | Latest, private, citable facts |

A common misconception is hoping to inject large amounts of facts into a model with just a few dozen SFT samples. SFT can make the model remember some content, but it is better at changing behavior. If the goal is to query frequently changing product prices, internal policies, or fault records, RAG is usually more appropriate than writing facts into model parameters.

## 3. How One Conversation Enters the Model

Training data is often stored in JSONL format, with one sample per line:

```json
{
  "messages": [
    {"role": "system", "content": "你是一个谨慎的基础设施助手。"},
    {"role": "user", "content": "Pod Pending 应该先看什么？"},
    {"role": "assistant", "content": "先查看 Pod Event，再检查资源、污点和队列配额。"}
  ]
}
```

This data does not enter the GPU as-is; it goes through three steps in between.

### 3.1 Chat Template: Concatenating Multi-Turn Messages into a Format the Model Recognizes

Different models represent roles and turns differently. The Chat Template converts structured messages into a piece of text, for example:

```text
<system>
你是一个谨慎的基础设施助手。
<user>
Pod Pending 应该先看什么？
<assistant>
先查看 Pod Event，再检查资源、污点和队列配额。
```

Training and inference must use compatible Templates. If one format is used during training and another during deployment, you may see a low Loss but poor actual conversation quality.

### 3.2 Tokenizer: Cutting Text into Numbers

The model does not directly read Chinese characters or English words; it reads Token IDs. The Tokenizer cuts text into Tokens:

```text
“先查看 Pod Event”
        ↓ Tokenizer
[18493, 9231, 442, 13872, ...]
```

A Token is not a character, nor is it a word. The same sentence may produce different lengths under different Tokenizers. Therefore, training scale and cost are usually measured in Token count, not file size or character count.

### 3.3 Loss Mask: Deciding Which Tokens Count as Wrong Answers

Common SFT only requires the model to learn the Assistant's answer, not to re-predict the System and User content:

```text
System    不计算 Loss
User      不计算 Loss
Assistant 计算 Loss
```

In many training implementations, positions that do not participate in Loss have their Label set to `-100`:

```text
输入 Token： [System...] [User...] [Assistant...]
训练 Label： [-100 ...]  [-100...] [答案 Token...]
```

This is called **Assistant Loss Mask**. A misconfigured Mask is one of the most subtle problems: the job may run normally and Loss may even decrease, but the model is learning to repeat the question, role markers, or irrelevant templates.

## 4. What Actually Happens in One Training Step

The most basic parameter update can be broken down into four steps:

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

| Term | Plain explanation |
| --- | --- |
| Forward | Using the current model to complete one prediction |
| Loss | The error between the current prediction and the ground truth |
| Backward | Computing how the error should be propagated back to the parameters of each layer |
| Gradient | The direction and relative magnitude in which parameters should be adjusted |
| Optimizer | The algorithm that updates parameters based on the Gradient, e.g., AdamW |
| Learning Rate | How big a step each update takes |
| Step | Usually refers to completing one Optimizer parameter update |

If the Learning Rate is too large, the model may oscillate, produce NaN, or even destroy existing capabilities; if it is too small, training may run for a long time without noticeable change.

Three related terms also frequently appear in training commands:

- **Warmup**: at the very beginning of training, use a smaller Learning Rate first, then gradually increase to the target value;
- **Scheduler**: specifies how the Learning Rate rises and falls throughout the training process;
- **Gradient Clipping**: limits the range of the Gradient when it is too large, reducing the risk of sudden explosions.

## 5. Sample, Token, Batch, Step, and Epoch

These terms all describe "how much has been trained," but the units differ.

| Term | Meaning |
| --- | --- |
| Sample | One training sample, e.g., a single-turn or multi-turn conversation |
| Token | The smallest unit of text the model actually processes |
| Sequence Length | The maximum number of Tokens allowed in one sequence fed to the model |
| Micro Batch | The number of samples one GPU processes in one Forward/Backward |
| Gradient Accumulation | Accumulating several small Batches before updating parameters once |
| Global Batch | The total number of samples processed across all data-parallel replicas in one parameter update |
| Step | Completing one parameter update |
| Epoch | Roughly going through the entire training set once |

The common way to compute Global Batch is:

```text
Global Batch
= 每张 GPU 的 Micro Batch
× Gradient Accumulation
× Data Parallel Size
```

For example:

```text
Micro Batch = 1
Gradient Accumulation = 8
Data Parallel Size = 2

Global Batch = 1 × 8 × 2 = 16
```

If the training set has 800 samples:

```text
每个 Epoch 的 Step 数 ≈ 800 ÷ 16 = 50
训练 3 个 Epoch ≈ 150 Step
```

TP, PP, and EP are usually not multiplied directly into this formula, because those GPUs are collaboratively processing the same data; only different DP replicas typically read different samples.

### 5.1 Why Gradient Accumulation Is Needed

When GPU memory cannot fit 16 samples at once, you can process only 1 sample at a time, accumulate the Gradient 8 times in a row, and then perform one parameter update. It trades more time for lower instantaneous GPU memory requirements.

### 5.2 Why Sequence Length Matters

`max_length=512` means one training sequence keeps at most 512 Tokens. Overly long samples may be truncated, and overly short samples may be padded to fill the length. The longer the sequence, the more GPU memory Activation typically occupies, and Attention computation is also more expensive.

### 5.3 What Is Packing

If many samples are far shorter than the maximum length, padding each one individually wastes computation. Packing safely concatenates several short samples into one longer sequence, improving the effective Token ratio. It must correctly handle sample boundaries, positional encodings, and Loss Mask; otherwise, one sample may incorrectly affect the next.

## 6. Full SFT, LoRA, and QLoRA

### 6.1 Full SFT: Modifying the Entire Model

Full SFT allows all model parameters to participate in training, giving the strongest expressiveness, but it requires saving Gradient and Optimizer State for a large number of parameters, making GPU memory, communication, and Checkpoint costs very high.

### 6.2 LoRA: Training Only a Small Set of Incremental Parameters

LoRA does not directly modify most of the base model weights. Instead, it adds a small set of trainable matrices next to some layers. You can think of it as:

```text
原模型回答
  + 一张可学习的“行为修正贴纸”
  = 微调后的回答
```

After training, this "sticker" is usually saved as an Adapter. The base model may be tens of GB, while the Adapter is often much smaller.

| LoRA Parameter | What it controls |
| --- | --- |
| Rank | The expressive capacity of the Adapter; larger usually means more parameters, GPU memory, and computation |
| Alpha | Scaling of the LoRA update magnitude |
| Dropout | Randomly dropping part of the LoRA path during training to help reduce overfitting risk |
| Target Modules | Which model layers LoRA is attached to, e.g., Attention projection layers |

Rank is not "number of training epochs," and Alpha is not the Learning Rate. They are structural configuration of the Adapter.

### 6.3 QLoRA: Quantizing the Base Model, Then Training LoRA

QLoRA typically loads the base model at a lower bit width, reducing weight footprint; it dequantizes on the fly during computation, while what is actually updated is still the LoRA Adapter.

```text
低位宽、冻结的基础模型
        +
BF16/FP16 等精度训练的 LoRA
```

QLoRA is not "full-parameter training of the entire 4-bit model." The model architecture, quantization format, and Kernels must also be supported by the training framework.

### 6.4 How to Choose Among the Three Methods

| Method | Resource Requirements | Suitable for a First Experiment? | Main Limitations |
| --- | ---: | --- | --- |
| Full SFT | High | Usually not suitable starting from a large model | High GPU memory, communication, and Checkpoint costs |
| LoRA | Medium | Most suitable | Need to choose target layers correctly; capability ceiling is affected by Adapter structure |
| QLoRA | Lower | Suitable when GPU memory is tight | Depends on quantization training compatibility; not necessarily faster |

Regardless of LoRA or QLoRA, the base model still needs to be loaded; you cannot assume that just because the Adapter file is only a few hundred MB, training only needs a few hundred MB of GPU memory.

## 7. Who Uses Up Training GPU Memory

Inference mainly needs model weights and KV Cache; training adds several more categories of data:

```text
模型权重
+ Gradient
+ Optimizer State
+ Activation
+ 临时计算与通信 Buffer
```

| Term | Purpose |
| --- | --- |
| Weight | The model's current parameters |
| Gradient | How parameters should change in this round |
| Optimizer State | Historical state the optimizer saves for each parameter |
| Activation | Intermediate results from Forward, still needed during Backward |
| Buffer | Temporary space for Attention, quantization, communication, etc. |

Common GPU memory saving techniques include LoRA/QLoRA, Gradient Checkpointing, reducing Micro Batch, shortening Sequence Length, ZeRO/FSDP sharding, and CPU Offload. Their costs may be slower training, more communication, or more complex implementation.

Note that **Gradient Checkpointing** here is easily confused with saving model Checkpoints: it does not write the model to disk, but rather saves fewer Activations and recomputes them during Backward, trading extra computation for GPU memory.

## 8. What Are BF16, FP16, FP8, INT4, and NF4

These names describe how many bits are used for a number and how it is encoded.

| Format | Common Use | Intuitive Characteristics |
| --- | --- | --- |
| FP32 | High-precision computation, some critical states | High precision, large footprint |
| BF16 | Common compute precision for large model training | Good dynamic range, 2 Bytes per value |
| FP16 | Training and inference | 2 Bytes per value, dynamic range differs from BF16 |
| FP8 | Low-precision training or inference paths | Saves GPU memory and bandwidth, but depends on hardware and Kernels |
| INT4/NF4 | Quantized weights, QLoRA | Smaller weights, requires quantization-compatible paths |

"The model file is FP8" does not mean all training computation uses FP8. The framework may save or load weights in FP8, but use BF16 in parts of Forward, Backward, or LoRA paths.

## 9. Dense and MoE Models

### 9.1 Dense: Each Token Roughly Passes Through the Same Set of Parameters

Every layer of a Dense model typically participates in the computation for every Token. A 4B Dense model can be roughly understood as every Token using this network of about 4B parameters.

### 9.2 MoE: Each Token Selects Only Some Experts

MoE stands for Mixture of Experts. The model contains many Experts, and a Router selects a subset of them for each Token:

```text
Token
  ↓
Router 判断应该交给谁
  ↓
Expert 2 + Expert 7 参与本次计算
```

Names like `35B-A3B` typically express "about 35B total parameters, with about 3B parameters activated per Token." But this does not mean the model weights only occupy GPU memory for 3B parameters: all Expert weights still need to be placed on one or more GPUs.

MoE training also requires attention to:

- Whether the Router concentrates Tokens too heavily on a few Experts;
- Whether load is balanced among Experts;
- Whether LoRA actually covers the Expert parameters;
- Whether All-to-All communication across GPUs becomes a bottleneck.

## 10. How DP, TP, PP, and EP Divide Work

Think of training a very large model as a restaurant: there are many orders, a large kitchen, and multiple groups of different chefs.

| Parallelism | Restaurant Analogy | What GPUs Are Actually Dividing |
| --- | --- | --- |
| DP: Data Parallel | Multiple identical kitchens each handling different orders | Different GPUs process different training samples |
| TP: Tensor Parallel | Several chefs cutting the same huge ingredient together | Matrix computation within the same layer is split |
| PP: Pipeline Parallel | Appetizers, main courses, and desserts assigned to different stations | Different model layers placed on different GPUs/nodes |
| EP: Expert Parallel | Different specialist chefs handling different types of orders | MoE Experts distributed across different GPUs |

### 10.1 DP: Same Model, Different Data

Each DP replica processes different samples, then synchronizes Gradients. DP most easily improves throughput, but each replica must be able to hold the model, or combine with FSDP/ZeRO sharding.

### 10.2 TP: One Layer Too Large, Split the Computation

TP splits the same matrix computation across multiple GPUs. It usually requires frequent communication, so it depends more on high-speed intra-node interconnects or low-latency networks.

### 10.3 PP: Model Layers Connected End to End

PP places the first few layers, middle layers, and last few layers on different GPUs. Data flows through each stage sequentially like a pipeline. When stage splitting is uneven or Micro Batch is too small, some GPUs experience Pipeline Bubble waiting.

### 10.4 EP: Placing Different Experts Separately

EP specifically serves MoE. After the Router selects an Expert, Tokens may need to be sent via All-to-All to the GPU holding that Expert, and the results sent back.

### 10.5 They Can Be Combined

A large MoE task may use several at the same time:

```text
2 个 Pipeline Stage
× 每个 Stage 8 路 Expert Parallel
× 2 份 Data Parallel
= 32 张 GPU
```

This does not mean that the Global Batch should be multiplied by all 32 GPUs. When calculating the Batch, you should confirm the DP Size ultimately derived by the framework.

## 11. How DDP, FSDP, and ZeRO Relate to DP

They are all related to data parallelism, but differ in how model states are saved.

| Method | What each GPU saves | Primary goal |
| --- | --- | --- |
| DDP | Usually saves full weights, Gradients, and Optimizer State | Simply replicate the model and scale data throughput |
| FSDP | Shards parameters, Gradients, and Optimizer State | Fit larger models across multiple GPUs |
| ZeRO-1 | Mainly shards Optimizer State | First save optimizer GPU memory |
| ZeRO-2 | Also shards Gradients | Further save GPU memory |
| ZeRO-3 | Also shards model parameters | Maximally avoid storing the full model on each GPU |

Sharding reduces per-GPU memory, but requires communication such as All-Gather and Reduce-Scatter during computation. The slower the network and the finer the sharding, the more noticeable communication waits can become.

## 12. How to Read Loss Curves

A lower Loss means the model finds it easier to predict the standard answer under the current data and Mask configuration. But Loss is not business accuracy.

A model can not only handle questions seen during training, but also process new questions of the same type; this is called **Generalization**. When the model only memorizes training data more and more thoroughly while performing worse on new questions, this is called **Overfitting**.

| Metric | What it answers | What it cannot prove on its own |
| --- | --- | --- |
| Train Loss | Whether the model is becoming more familiar with training data | Whether it works on new questions |
| Validation Loss | Whether it is also improving on data not involved in updates | That the business task is definitely correct |
| Token Accuracy | The proportion of standard-answer Tokens predicted correctly | That the full response and task logic are correct |
| Gradient Norm | Whether gradients are abnormally large or small | Final model quality |
| Learning Rate | Current parameter update step size | Whether training is effective |
| Tokens/s | Training throughput | Model quality |
| GPU Utilization | Whether GPUs are busy | Whether effective compute is all used for the target computation |

Typical curve judgments:

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

Loss values obtained from different models, Tokenizers, datasets, and Masks generally cannot be compared directly.

## 13. Train, Validation, Test, and Blind Test

| Dataset | Purpose | Can it be used for tuning |
| --- | --- | --- |
| Train | Compute Gradients and update the model | Yes |
| Validation | Select learning rate, Step, and best Checkpoint | Yes, but must not repeatedly leak answers manually |
| Test | Final evaluation | Should not participate in training or tuning |
| Blind Test | Final test deliberately isolated in templates, scenarios, or answers | Should not be viewed in advance and modified accordingly |

If the same question with a few numbers changed appears in both Train and Test, the scores may look good, but it only proves the model memorized the template. Data splitting should isolate by scenario, source, time, or template family as much as possible.

Meaningful validation usually compares:

```text
同一个 Base Model
同一套推理参数
同一批从未用于训练的题
        ↓
Base 输出 vs 加载 Adapter 后的输出
```

Besides accuracy, also observe format compliance rate, refusal boundaries, hallucination, general capability regression, and dangerous actions.

## 14. Base, Adapter, Checkpoint, and Merge

| Term | Meaning |
| --- | --- |
| Base Model | The base model before fine-tuning begins |
| Adapter | Incremental parameters trained by methods such as LoRA |
| Checkpoint | A state snapshot saved at a certain training moment |
| Optimizer Checkpoint | Contains optimizer and other states, can be used to continue training |
| Merged Model | A model after merging LoRA increments into the base weights |

Saving only the Adapter is usually sufficient to load the fine-tuning effect, but may not restore training losslessly. To resume training from a breakpoint, you also need the Optimizer, Scheduler, random numbers, and data sampling progress states.

The Adapter must also be paired with the correct Base Model, Tokenizer, and Template. If given the wrong base model, even if the files load, the results may be wrong.

## 15. Smoke Test and Effective Training Are Not the Same Thing

### 15.1 A Smoke Test Proves the Engineering Pipeline Works

A 5–20 Step Smoke Test is suitable for confirming:

- The model can load;
- Data format and Template produce no errors;
- Forward, Backward, and Checkpoint saving succeed;
- Loss is not NaN/Inf;
- The Adapter can be reloaded.

It cannot prove the model's effectiveness has improved.

### 15.2 Meaningful Training Must Also Prove Behavioral Change

At minimum, you need:

- Independent Train, Validation, and Blind Test;
- A/B comparison of Base/Adapter using the same inference parameters;
- Saved training curves and the basis for selecting the best Checkpoint;
- Classification of error samples, not just a single total score;
- Checking whether the model harms existing general capabilities.

## 16. How to Read an SFT Command

The following is not the only correct set of parameters; it is only used to explain common fields:

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

| Parameter | Plain-language explanation |
| --- | --- |
| `model` | Which base model to start from |
| `dataset` | Which standard answers to train with |
| `train_type=lora` | Train only the LoRA Adapter |
| `lora_rank=8` | Low-rank capacity of the Adapter |
| `lora_alpha=16` | LoRA update scaling |
| `max_length=512` | At most 512 Tokens per sequence |
| `per_device_train_batch_size=1` | Each GPU holds only 1 sample at a time |
| `gradient_accumulation_steps=8` | Accumulate 8 times before updating parameters |
| `learning_rate=1e-4` | Step size for each update |
| `num_train_epochs=3` | Roughly 3 passes over the training set |

When looking at a training command, do not first ask "how many GPUs were used." Instead, first confirm the model, data, Mask, training method, Global Batch, length, Learning Rate, total Tokens, and evaluation approach.

## 17. Common Symptoms and Troubleshooting Directions

| Symptom | Priority checks |
| --- | --- |
| OOM immediately at startup | Base weight precision, Sequence Length, Micro Batch, Activation, Optimizer, sharding strategy |
| Loss near 0 from the first step | Whether Label/Mask also masks out the answers; whether data is duplicated |
| Loss does not decrease | Data format, Template, Target Modules, Learning Rate, whether the Adapter is actually trainable |
| Loss becomes NaN | Learning Rate, precision overflow, abnormal samples, Gradient Clip |
| Train Loss drops, Validation Loss rises | Overfitting, too little data, or inconsistent distribution |
| No change in responses after loading Adapter | Adapter path, Base version, Template, whether the inference service actually enables LoRA |
| Multi-GPU is no faster than single-GPU | Global Batch, data loading, communication, model too small, too few LoRA Gradients |
| MoE trained but Experts unchanged | Whether LoRA Target Modules cover Experts; whether Router/Expert parameters are trainable |
| Very low GPU utilization | CPU Tokenization, data reading, Checkpoint, cross-GPU waits, single-process layer sharding |

## 18. How Large Should the First Experiment Be

For the first attempt, it is not recommended to start directly with a several-hundred-B MoE model. A more understandable and acceptable starting point is:

| Item | Suggested starting point |
| --- | --- |
| Model | An instruction model of about 4B |
| GPU | A single GPU with sufficient memory |
| Method | BF16 LoRA; evaluate QLoRA only if memory is insufficient |
| Data | A few hundred Train samples, dozens of Validation samples, about a hundred Blind Test samples |
| Length | Start with 256–512 Tokens |
| Step | First do a 20-Step Smoke test, then a 100–500 Step effective experiment |
| Acceptance | Loss curve + Base/Adapter Blind A/B |

The recommended learning order is:

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

## 19. What to Record at Minimum for Each Experiment

Training without records is hard to reproduce, and it is also hard to explain why this run is better than the previous one.

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

## 20. Quick Reference Glossary

| Term | One-sentence explanation |
| --- | --- |
| Activation | Intermediate results produced by Forward and still needed by Backward |
| Adapter | Incremental parameters trained by methods such as LoRA |
| Backward | Deriving each parameter's Gradient backward from the Loss |
| Batch | A group of samples involved in one parameter update |
| Checkpoint | State saved at a certain training moment |
| Chat Template | Rules for assembling System/User/Assistant messages into the model format |
| Dense | Each Token roughly uses the same set of model layers |
| DP | Multiple model replicas process different data, then synchronize Gradients |
| Epoch | Roughly one full pass over the training set |
| EP | Distributing MoE Experts across different GPUs |
| Eval/Validation | Checking generalization on data where parameters are not updated |
| Forward | Using current parameters to complete predictions |
| FSDP | PyTorch's fully sharded data parallel approach |
| Global Batch | Total number of samples processed in one parameter update |
| Gradient | How parameters should be adjusted |
| Gradient Accumulation | Accumulating gradients multiple times before updating parameters |
| Gradient Checkpointing | Storing fewer Activations and recomputing them in Backward, trading compute for GPU memory |
| Gradient Clipping | Limiting overly large Gradients to reduce the risk of numerical explosion |
| Generalization | The model applying learned patterns to unseen data of the same type |
| Label | The target Token the training wants the model to predict |
| Learning Rate | Step size for each parameter update |
| LoRA | Using small low-rank Adapters instead of full parameter updates |
| Loss | Error between current predictions and standard answers |
| Mask | Specifying which Tokens participate in the Loss |
| Micro Batch | Number of samples processed at once per GPU |
| MoE | A model containing multiple Experts where each Token activates only a subset |
| OOM | Out of GPU memory or system memory |
| Optimizer | Algorithm that updates parameters based on Gradients |
| Overfitting | The phenomenon where training data improves while new data gets worse |
| Packing | Concatenating multiple short samples into longer sequences to reduce Padding waste |
| Padding | Using placeholder Tokens to pad samples of different lengths |
| PP | Pipeline parallelism placing different model layers on different GPUs |
| QLoRA | Loading the base model in quantized form and training LoRA |
| Rank | Low-rank dimension of the LoRA Adapter |
| Router | Module in MoE that selects Experts for Tokens |
| Scheduler | Rules controlling how Learning Rate changes over training progress |
| SFT | Supervised fine-tuning using questions and ideal answers |
| Step | Completing one Optimizer parameter update |
| Token | The smallest text unit the model reads and predicts |
| Tokenizer | Component that converts text into Token IDs |
| TP | Splitting the same layer's matrix computation across different GPUs |
| Truncation | Cutting off some Tokens when a sample exceeds the maximum length |
| Warmup | Gradually increasing Learning Rate in early training |
| ZeRO | DeepSpeed's training state sharding approach |

## 21. From Concepts to Practice

After understanding the terms in this document, you can continue in the following order:

1. [Large Model SFT Training in Practice: From Single-GPU LoRA to DeepSeek V4](sft-from-single-gpu-to-deepseek-v4.md): View real Qwen, MoE, DeepSeek V4, single-node, and multi-node experiments;
2. [DeepSeek V4 Dual-Node RDMA Training Benchmarks](rdma-distributed-training-benchmark.md): View how TP/PP/EP/DP topology determines whether RDMA enters the critical path;
3. [SwanLab Self-Hosting: From Kubernetes Deployment to Real SFT Metrics](swanlab-self-hosted.md): View Loss, Learning Rate, Gradient Norm, and GPU metrics;
4. [Distributed Training Platform](../distributed-training.md): Understand how training tasks are scheduled, launched, and resumed by Kubernetes;
4. [`examples/llm-sft-lab`](https://github.com/runzhliu/aik8s/tree/main/examples/llm-sft-lab): Get runnable scripts, sample data, and result records.

The most important judgment criterion is only one sentence: **training success is not "the job exit code is 0" or "Loss dropped," but that data, optimization, Checkpoint, inference, and independent evaluation form a reproducible closed loop.**

## References

- [LoRA: Low-Rank Adaptation of Large Language Models](https://arxiv.org/abs/2106.09685)
- [QLoRA: Efficient Finetuning of Quantized LLMs](https://arxiv.org/abs/2305.14314)
- [InstructGPT: SFT, Reward Model, and RLHF](https://arxiv.org/abs/2203.02155)
- [Hugging Face PEFT LoRA Documentation](https://huggingface.co/docs/peft/package_reference/lora)
- [PyTorch Fully Sharded Data Parallel](https://docs.pytorch.org/docs/stable/fsdp.html)
- [DeepSpeed ZeRO](https://www.deepspeed.ai/tutorials/zero/)
- [NVIDIA Megatron Core Parallelism Guide](https://docs.nvidia.com/megatron-core/developer-guide/latest/user-guide/index.html)
