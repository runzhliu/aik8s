---
title: "Large Model SFT Training in Practice: From Single-GPU LoRA to DeepSeek V4"
description: "Use Qwen3.5-4B to complete the LoRA, SwanLab, and blind test loop, then use 8 to 16 H20 GPUs to test DeepSeek V4 Flash's Expert Parallel, cross-node GDRDMA, and overfitting inflection point"
status: evolving
last_reviewed: 2026-08-25
---

# Large Model SFT Training in Practice: From Single-GPU LoRA to DeepSeek V4

If you are not yet familiar with Loss, LoRA, QLoRA, Batch, Epoch, Checkpoint, DP, TP, PP, and EP, we recommend first reading [Large Model SFT Introduction: Explaining Common Terms at Once](sft-concepts.md), then continue with the real experiments in this chapter.

Putting the first SFT directly on the 284B DeepSeek V4 Flash would simultaneously introduce data format, training parameters, distributed communication, precision conversion, and Checkpoint issues. An easier path to success is to first use the same data format and training framework to complete an acceptable LoRA loop on a single GPU; only after this loop is stable, switch to Megatron-SWIFT and the full MoE model.

This chapter provides three paths:

1. **Immediately runnable and quantifiable experiment**: single-GPU `Qwen3.5-4B + ms-swift + LoRA`, complete Base/Adapter blind test;
2. **Multi-GPU experiment for newer MoE**: single-node eight-GPU `Qwen3.6-35B-A3B + ZeRO-3 + LoRA`, verify sharded loading, training, validation, and Checkpoint;
3. **Full DeepSeek V4 Flash test**: single-node `8 × H20 + EP=8` to run training, then use dual-node 16 GPUs to complete TCP/GDRDMA comparison and 60-Step convergence experiment.

The accompanying scripts and sample data are located at [`examples/llm-sft-lab`](https://github.com/runzhliu/aik8s/tree/main/examples/llm-sft-lab). The examples do not include cluster names, internal images, storage addresses, or network configurations.

## 1. What This Experiment Aims to Prove

The first round is not to obtain a deployable domain model, but to prove that the following chain can be fully closed:

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

The minimum experiment's pass conditions are:

- GPU, PyTorch, and `swift` can be correctly recognized;
- Data preprocessing has no Schema, Template, or Tokenizer errors;
- Training Loss is a finite number, no NaN/Inf;
- The output directory contains `adapter_model.safetensors` and Adapter configuration;
- `swift infer --adapters ...` can load that Checkpoint and complete a conversation;
- Record the model, framework, data, parameters, GPU, and results, rather than just saving a Loss screenshot.

A 20-Step Smoke Test can only verify the engineering chain, not prove model quality improvement.

## 2. What Pretraining, SFT, and Alignment Actually Do

Understanding large model training uniformly as "continue training with data" can easily lead to choosing the wrong method. They may all use Next Token Prediction, but the data format, the position where Loss acts, and the capabilities they aim to change differ.

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

| Stage | Typical Data | Where Loss Mainly Acts | What It Is Better at Changing | Common Scale |
| --- | --- | --- | --- | --- |
| Pretraining | Deduplicated and cleaned web, code, books, and other continuous tokens | Almost all predictable tokens | Forming language, knowledge, and general capabilities from scratch | Tens of billions to trillions of tokens |
| Continued Pretraining | Raw corpora from medical, financial, code, or enterprise domains | Continuous corpus tokens | Domain vocabulary, expression, and knowledge distribution | Usually much larger than SFT data |
| SFT | `用户问题 → 理想回答`, multi-turn conversations, tool trajectories | Usually only the Assistant answer tokens | Instruction following, answer structure, task flow, and style | Thousands to millions of high-quality samples |
| Preference Alignment | Preferred/Rejected pairs, or Rollouts with computable Reward | Preference or reward objectives | Trade-offs, boundaries, safety, and usability | Depends on algorithm and task |
| RAG | Document index and retrieval results at query time | Does not modify model parameters | Latest, private, traceable facts | Dynamically changes at inference time |

### 2.1 Pretraining Is Not "a Bigger SFT"

Pretraining typically splits continuous text into token sequences and lets the model predict the next token. It does not require each data item to have a question and a standard answer; the goal is to learn representations, language patterns, and world models from a very large corpus distribution. Continued pretraining follows a similar objective, but shifts from general corpora to a specific domain, making it more suitable for familiarizing the model with a large amount of industry terminology and writing style. [Research on Domain Continued Pretraining](https://arxiv.org/abs/2004.10964)

Such training updates a large number or even all parameters, and the Optimizer State, Gradient, Activation, and Checkpoint are all large. Data parallelism requires synchronizing large gradients, and model parallelism and ZeRO/FSDP also introduce All-Gather, Reduce-Scatter, or point-to-point communication, so it typically relies more on multi-node high-speed networks than small LoRA SFT.

### 2.2 SFT Is Mainly Teaching "How to Answer"

SFT concatenates the Prompt, context, and ideal answer into a single sequence, but the common practice only computes supervised Loss on the Assistant part. For example:

```text
System: 你是一个谨慎的基础设施助手。      Loss Mask = 0
User: Loss 降了，可以直接上线吗？           Loss Mask = 0
Assistant: 不可以，还需要隔离评测……         Loss Mask = 1
```

The model thus learns "what output should be generated when seeing this input." It is well suited for fixing answer formats, tool-calling protocols, reasoning flows, and business tone, but a few dozen Q&A pairs cannot reliably inject an entire knowledge base; when samples are too few or too repetitive, a decreasing Loss more likely indicates memorization of training answers.

LoRA is a parameter-efficient implementation of SFT: it freezes the base weights and only trains the inserted low-rank matrices. It can significantly reduce trainable parameters, Optimizer State, and Checkpoint, but each data-parallel GPU still needs to load the base model. [LoRA Paper](https://arxiv.org/abs/2106.09685)

### 2.3 Which One Should You Choose

- If you want the model to master a large amount of domain language and corpus distribution: first evaluate continued pretraining;
- If you want the model to answer in a specified format, call tools, or follow workflows: use SFT;
- If you want the model to form preferences and safety boundaries among multiple available answers: do preference alignment after SFT;
- If knowledge changes quickly, requires access control, or needs source citation: prefer RAG over frequent retraining;
- If multiple needs exist simultaneously: you can adopt a combination of "continued pretraining → SFT → preference alignment → RAG," but each stage must retain independent evaluation.

The 12 data items and 20 Steps retained in this chapter belong only to the **LoRA SFT engineering Smoke Test**, not pretraining, and cannot prove that domain knowledge has been written into the model. The currently recommended Qwen3.5 experiment uses mutually isolated Train, Validation, and Blind Test sets, and compares Base with Adapter.

## 3. Why Choose ms-swift and Qwen3.5-4B First

`Qwen3.5-4B` is newer than the Qwen3-4B used earlier in the repository, while still retaining the 4B Dense model scale suitable for single-GPU reproduction. ms-swift has provided best practices for Qwen3.5 LoRA and specifically requires setting `add_non_thinking_prefix` and `ignore_empty_think` Loss Scale for non-thinking training; the framework also supports custom JSONL, Adapter saving, and inference. [ms-swift Qwen3.5 Best Practice](https://github.com/modelscope/ms-swift/blob/main/docs/source/BestPractices/Qwen3_5-Best-Practice.md)

The 4B model is chosen here not because its architecture is equivalent to DeepSeek V4, but because the following can be reused:

- `messages` conversation data format;
- System/User/Assistant roles and Chat Template;
- LoRA data loop and basic hyperparameters;
- Checkpoint, Adapter inference, and evaluation methods before and after training;
- Image version, data version, and experiment metadata recording methods.

What cannot be directly reused are DeepSeek V4's Hybrid Attention, MoE Expert Parallel, MTP, FP4/FP8 weight conversion, and multi-node communication configuration; these are verified separately in the second phase.

## 4. Minimum Hardware and Software

### 4.1 Single-GPU Smoke Test

| Item | Minimum Recommendation | Description |
| --- | --- | --- |
| GPU | 1 × 16 GB | Default 4B LoRA, 1K sequence; reduce to 512 tokens when GPU memory is tight |
| Recommended GPU | 1 × 24 GB or higher | Leave margin for data processing, GPU memory fragmentation, and slightly longer sequences |
| CPU Memory | 32 GB | Sufficient for small-data Smoke; adjust for formal data based on preprocessing concurrency |
| Disk | 30 GB free space | Includes base model, Python environment, cache, and Adapter |
| Python | 3.10 and above | ms-swift currently officially requires Python 3.10+ |
| CUDA/PyTorch | Compatible with GPU driver | First use an existing CUDA PyTorch environment to avoid building an image in the first round |

H20, H100, A100, L20, and 3090 can use default BF16. T4 does not support native BF16; you should execute:

```bash
TRAIN_TORCH_DTYPE=float16 bash train-qwen3-4b-lora.sh
```

16 GB is the lower bound for trying under this experiment's parameters, not a universal promise for all 4B LoRA tasks. Model version, Attention implementation, sequence length, and Batch all change GPU memory usage.

### 4.2 Full DeepSeek V4 Flash LoRA

DeepSeek V4 Flash has 284B total parameters and 13B activated parameters per token; LoRA only reduces trainable parameters and optimizer state, it does not turn the 284B base into a 13B model. [DeepSeek V4 Official Model Card](https://huggingface.co/deepseek-ai/DeepSeek-V4-Pro)

The currently public Megatron-SWIFT LoRA example uses:

- Single node, 8 GPUs;
- `TP=1`, `EP=8`;
- 4K maximum training length;
- Full Recompute;
- BF16 LoRA Rank 16;
- MTP 1 layer.

Therefore, this chapter treats `8 × 96 GB` as a reasonable starting point for a full V4-Flash LoRA, while `8 × 141 GB` will have more ample activation values and communication buffer margin. Whether `8 × 80 GB` can run stably must be determined by precise Checkpoint, loading precision, and measured peak GPU memory, not just by summing total GPU memory. [Megatron-SWIFT DeepSeek V4 Best Practices](https://github.com/modelscope/ms-swift/blob/main/docs/source/BestPractices/deepseek-v4.md)

## 5. Prepare the Minimal Experiment in Five Minutes

Enter the example directory:

```bash
cd examples/llm-sft-lab
```

Install ms-swift in a Python environment that already has CUDA PyTorch installed:

```bash
python -m pip install --upgrade ms-swift
```

You can also run the repository script, which will create `.venv` in the current directory:

```bash
bash install-ms-swift.sh
source .venv/bin/activate
```

If you just want to first look at the training interface, ms-swift also provides a Gradio Web UI:

```bash
swift web-ui
```

The Web UI is suitable for familiarizing yourself with the model, data, and parameter locations; this chapter still uses CLI scripts as reproducible records because they are easier for version control, re-running, and parameter diffs. Do not expose an unauthenticated training UI directly to the public internet. [ms-swift Web UI](https://github.com/modelscope/ms-swift#web-ui)

First do a pre-check:

```bash
bash preflight.sh
```

The pre-check must confirm that `torch.cuda.is_available()` is `True`. If PyTorch cannot see the GPU, do not start downloading the model and training.

## 6. Understanding the Training Data

ms-swift supports JSON, JSONL, and CSV. The minimal experiment uses JSONL with one sample per line:

```json
{"messages":[{"role":"system","content":"你是一个谨慎的 AI 基础设施助手。"},{"role":"user","content":"GPU Pod 一直 Pending，第一步查什么？"},{"role":"assistant","content":"先读取 Pod 的调度条件和 Events，再检查资源请求、节点标签、污点与队列准入状态。"}]}
```

During training, the part that actually participates in Loss is usually the Assistant answer. You should manually spot-check the tokenized template and Loss Mask to avoid using System Prompt, user input, Padding, or incorrect reasoning markers as training targets.

The dozen or so data items in the repository are only to trigger the full code path. Formal training at least needs to complete:

- Remove duplicate, conflicting, and low-quality answers;
- Isolate Train/Validation/Test by business question rather than random rows;
- Fix a set of regression questions that never appear in the training set;
- Decide whether to keep Thinking content, tool calls, and multi-turn context;
- Record data generation method, review status, and version hash.

## 7. Running Single-GPU LoRA

If you only want to confirm the old minimal chain, you can still run the 20-Step Smoke:

```bash
bash train-qwen3-4b-lora.sh
```

To obtain acceptable Qwen3.5 results, you should directly run the Base/Adapter A/B with 330 training, 55 validation, and 110 blind test samples:

```bash
cd meaningful-sft
TRAIN_MODEL_ID=/models/Qwen3.5-4B \
TRAIN_REPORT_TO=swanlab \
bash run-ab.sh
```

This script by default uses `evaluate-swift.py` compatible with Qwen3.5, and enables `add_non_thinking_prefix=true` and `loss_scale=ignore_empty_think`. If not connecting to an experiment platform, set `TRAIN_REPORT_TO=none`; the blind test results will still be written to a local JSON.

The script supports overriding key parameters with environment variables:

```bash
TRAIN_MODEL_ID=/models/Qwen3-4B-Instruct-2507 \
TRAIN_MAX_LENGTH=2048 \
TRAIN_MAX_STEPS=100 \
TRAIN_OUTPUT_DIR=/workspace/output/qwen3-4b-domain-lora \
bash train-qwen3-4b-lora.sh
```

For the first time, adjust only one variable. If OOM occurs, shrink in the following order:

1. `TRAIN_MAX_LENGTH=512`;
2. Keep single-GPU Batch at 1;
3. Confirm Gradient Checkpointing is enabled;
4. Then consider QLoRA, rather than introducing multi-GPU and ZeRO first.

After training ends, find the latest Adapter and enter interactive inference:

```bash
bash infer-latest-adapter.sh
```

You can also explicitly specify the Adapter:

```bash
ADAPTER_PATH=/workspace/output/qwen3-4b-domain-lora/v0-xxx/checkpoint-100 \
bash infer-latest-adapter.sh
```

### 7.1 Early Qwen3-4B Engineering Smoke

On August 20, 2026, a real Smoke Test was completed using this chapter's default 20-Step configuration. The environment was `1 × NVIDIA L20 46 GB`, `Qwen3-4B-Instruct-2507`, `ms-swift 4.4.1`, `PyTorch 2.11.0 + CUDA 13.0`, and `Transformers 5.12.1`; the 12 examples were split by `0.2` ratio into 10 training data items and 2 validation data items.

| Metric | Measured Value |
| --- | ---: |
| Maximum training length | 1024 tokens |
| Micro Batch / Gradient accumulation | 1 / 8 |
| LoRA Rank / Alpha | 8 / 32 |
| Training steps | 20 |
| Training duration | 31.39 seconds |
| Average step time | 1.569 seconds |
| Peak GPU memory recorded by framework | 7.94 GiB |
| Final Train Loss | 3.412 |
| Final Eval Loss | 3.497 |
| Adapter size | approximately 63 MiB |

`memory(GiB)` is the statistical basis of ms-swift training logs, not equivalent to the full-GPU peak obtained by sampling `nvidia-smi`. After reloading the Adapter, inference works normally; for the rewritten question "After the Loss on the training set drops significantly, can the model be directly released to production?", the generated answer is:

> No. You need to first verify generalization on the validation set, then verify stability on the test set.

This result proves that the single-GPU training, saving, and Adapter loading pipeline works, but it does not prove that the 12 Smoke data samples have business value. A formal conclusion still requires expanding the dataset and fixing a Base/Adapter controlled evaluation.

## 8. How to Tell Whether It Is "Runs but Did Not Learn"

Prepare at least three fixed groups of questions:

| Group | Purpose | Example |
| --- | --- | --- |
| Unseen in-domain questions | Check whether knowledge and answer conventions generalize | Give a GPU Pending scenario not present in the training set |
| General held-out questions | Check for catastrophic forgetting | Simple math, summarization, common sense, and instruction following |
| Boundary and refusal questions | Check whether it fabricates or oversteps authority | Whether it first points out missing evidence when information is insufficient |

For each question, save the outputs of both Base and Adapter separately, fixing the Prompt, Temperature, Seed, and maximum output length. Only expand the data and training steps when in-domain metrics improve and general capability does not regress noticeably.

A decreasing Loss only means the optimizer fit the training tokens; it does not mean the answers are more reliable. A dozen or so Smoke data samples are especially prone to overfitting within a few steps.

### 8.1 Qwen3.5-4B: A Small-Scale SFT That Can Quantify the Effect

The [`meaningful-sft`](https://github.com/runzhliu/aik8s/tree/main/examples/llm-sft-lab/meaningful-sft) experiment in the repository defines "whether it learned" as an automatically scorable task: the model reads Kubernetes or training failure evidence, uses 11 experiment-specific fault codes, and outputs only a fixed JSON Schema. Training, validation, and blind testing use different description template families to avoid data leakage from near-duplicate rewrites caused by random splitting.

The `Qwen3.5-4B + BF16 LoRA` A/B completed on August 21, 2026 on a single L20 used 330 training, 55 validation, and 110 blind test samples. The 120-Step training took 612.6 seconds, and the framework recorded a peak GPU memory of 9.33 GiB; the 16.23M trainable parameters account for approximately 0.3563%. Validation Loss at Step 30/60/90/120 was 0.06195/0.05315/0.06081/0.05700, respectively, so Step 60 was chosen rather than the last step.

![Qwen3.5-4B LoRA real training curve](../../assets/training/qwen35-4b-sft/swanlab-train-curves.png)

![Qwen3.5-4B LoRA real validation curve](../../assets/training/qwen35-4b-sft/swanlab-eval-curves.png)

| 110 blind test metrics | Base | Step 60 Adapter | Absolute improvement |
| --- | ---: | ---: | ---: |
| JSON validity rate | 99.1% | 100% | +0.9 pp |
| Required field completeness rate | 99.1% | 100% | +0.9 pp |
| Custom fault code accuracy | 0% | 77.3% | +77.3 pp |
| Fault code Macro-F1 | 0% | 75.3% | +75.3 pp |
| Insufficient-information judgment accuracy | 51.8% | 100% | +48.2 pp |
| Forbidden-action keyword coverage | 5.5% | 88.2% | +82.7 pp |

Base can understand faults and mostly follow JSON, but it invents English category names on its own, so it cannot hit the experiment-specific fault codes; the Adapter learned the classification mapping, insufficient-evidence judgment, and forbidden actions. It also did not reach 100% on the blind test: there were still 25 fault code errors, and it output `SCH-103` 25 times even though the balanced test contained only 10 of them. This is more valuable than showing only successful cases, because it points out that the classification boundary and expression coverage still need reinforcement.

Newer models do not automatically outperform older models on every small-data task: an earlier single-run experiment with Qwen3-4B using the same data generator reached 90.9% fault code accuracy, while this round's Qwen3.5-4B reached 77.3%. The Chat Template and inference implementation were not fully locked across the two runs, so this is treated only as a risk signal, not written up as a model leaderboard. Machine-readable records are available at [`l20-qwen35-4b-20260821.json`](https://github.com/runzhliu/aik8s/blob/main/examples/llm-sft-lab/meaningful-sft/results/l20-qwen35-4b-20260821.json).

### 8.2 Qwen3.6-35B-A3B: ZeRO-3 LoRA on 8 L20s

On the same day, a 120-Step LoRA was completed on the `Qwen3.6-35B-A3B` BF16 Checkpoint using a single machine with 8 L20s. Approximately 66.97 GiB of weights were sharded via DeepSpeed ZeRO-3; LoRA covered only the Attention projection layers, with 8.1254M trainable parameters accounting for approximately 0.0231% of the 35.115B total parameters. The maximum length was 256, the Global Batch was 8, training took 1,086.7 seconds at 0.110 Step/s, and the framework recorded a per-Rank peak GPU memory of 16.13 GiB.

| Validation | Loss | Token Accuracy |
| ---: | ---: | ---: |
| Step 30 | 0.34289 | 90.52% |
| Step 60 | 0.06315 | 98.27% |
| Step 90 | 0.06051 | 98.86% |
| Step 120 | **0.05915** | **98.98%** |

Training, four validation runs, and the Step 120 Checkpoint all succeeded, showing that this multi-GPU optimization pipeline works. However, this round saved the Adapter and prediction results in a temporary task directory, and the final Base/Adapter comparison was not exported to the experiment tracking system before task cleanup, so the public record does not report blind test improvements. This failure criterion is equally important: **Validation Loss and Token Accuracy only prove the fitting process; they cannot replace isolated blind testing.** Even if temporary storage is used again in the future, the very small A/B summary metrics should be uploaded before exit.

Full training parameters and limitations are available at [`l20-qwen36-35b-a3b-20260821.json`](https://github.com/runzhliu/aik8s/blob/main/examples/llm-sft-lab/meaningful-sft/results/l20-qwen36-35b-a3b-20260821.json).

## 9. Historical MoE Capacity Records and Next-Step Choices

The Qwen3-30B-A3B experiments are retained as historical records of capacity and LoRA injection issues, and are no longer the main subject of new training practice. If a newer small MoE is to be validated before investing in the full V4, a model that still has research value today and has clear framework training support should be selected, and the following four acceptance criteria should be reused:

- Whether Expert weights are covered by LoRA;
- Whether the Router is frozen, or whether auxiliary balancing Loss is needed;
- Whether Grouped GEMM and MoE Kernels work correctly;
- Whether the All-to-All of multi-GPU Expert Parallel behaves as expected.

The official ms-swift MoE LoRA example reminds us: if the Router is not to be trained, `target_modules` should be explicitly restricted to Attention and MLP projection layers, rather than blindly matching all parameters. [Qwen3 MoE LoRA example](https://github.com/modelscope/ms-swift/blob/main/examples/train/moe/qwen3_moe.sh)

### 9.1 Historical Record: Single-GPU Loading Barrier for Qwen3-30B-A3B

On August 20, 2026, a real loading test was performed on `Qwen3-30B-A3B-Instruct-2507` using a single L20. The model has 30.5B total parameters, 3.3B activated parameters, 128 Experts with 8 Experts selected per Token; the "3.3B activated" description refers to the main compute path and does not mean the remaining weights can be absent from memory. The theoretical lower bound for BF16 weights alone is approximately 56.8 GiB, before accounting for Activation, CUDA Workspace, and LoRA state, which already exceeds the 44.4 GiB visible on the test card. [Qwen3-30B-A3B model card](https://huggingface.co/Qwen/Qwen3-30B-A3B)

| Path | Measured result | Training and blind test |
| --- | --- | --- |
| 4B BF16 LoRA | Success; 120-Step peak 8.1 GiB | Completed; Step 60 Adapter fault code accuracy 90.9% |
| 30B-A3B BF16 + BNB NF4 | OOM at 411/531 during loading; process already occupied 44.37 GiB | Not started; no Loss or scores reported |
| 30B-A3B GPTQ-Int4 | Loading software compatibility passed, but the available test copy lacked weight shards | Not started; metadata directory not counted as success |

The BNB failure is related to the fused Expert representation of Qwen3-MoE: Transformers 5 saves some expert matrices as 3D `nn.Parameter` rather than ordinary `nn.Linear`. This affects not only quantization coverage but also LoRA injection; PEFT requires using `target_parameters` to explicitly cover `mlp.experts.gate_up_proj` and `mlp.experts.down_proj`. [PEFT LoRA documentation](https://huggingface.co/docs/peft/package_reference/lora)

So the conclusion here is not "all 4-bit approaches are impossible," but rather: the existing BF16 + standard BNB NF4 combination cannot complete loading on a single L20. Only after obtaining the complete pre-quantized GPTQ/AWQ weights, checking the quantization Kernel and Expert Adapter parameter names, and completing at least one Forward/Backward, is it worth continuing with the same 60-Step and 110-sample blind test A/B. The original failure record is saved at [`l20-qwen3-30b-a3b-20260820.json`](https://github.com/runzhliu/aik8s/blob/main/examples/llm-sft-lab/meaningful-sft/results/l20-qwen3-30b-a3b-20260820.json).

The goal of this stage is to validate MoE training behavior; do not extrapolate "small MoE can be trained with Transformers + PEFT" to mean that DeepSeek V4's special Attention and Checkpoint formats are already compatible.

### 9.2 Historical Record: BF16 LoRA Capacity Validation on a Single Machine with 8 × L20

On the same day, a 60-Step LoRA was completed on the same BF16 Checkpoint using a single machine with 8 L20s. Directly launching 8 ZeRO-3 processes constructs multiple full copies of the weights simultaneously during the model loading phase, exhausting host memory before GPU memory; after using single-process `device_map=balanced` to evenly place the 48 layers across 8 GPUs, the model, data, Forward/Backward, validation, and Adapter saving all passed.

| Metric | Measured result |
| --- | ---: |
| Trainable parameters | 497.42M / 1.603% |
| Max Length / gradient accumulation | 512 / 8 |
| Training runtime | 1,438 seconds |
| Training speed | 0.042 Step/s |
| Average Train Loss | 0.348 |
| Last log window Train Loss | 0.00915 |
| Eval Loss (Step 20 / 40 / 60) | 0.16276 / 0.02949 / 0.02811 |
| Step 60 Eval Token Accuracy | 99.34% |
| Best Checkpoint | Step 60, Adapter approximately 1.9 GiB |

The Transformers 5.12.1 and PEFT 0.19.1 in the image had an `WeightConverter` parameter compatibility issue when hot-reloading the best Adapter after training finished. Since all three validations improved continuously and Step 60 was itself the best Checkpoint, this round disabled `load_best_model_at_end`, kept the Trainer's best-Checkpoint selection and saving, and the final process exited with code 0. This workaround only skips post-training hot reload, not training, validation, or saving.

The conclusion needs a specific qualifier: this is a single-process layer-sharding path that first proves "it can fit and can be trained," not an efficient 8-card parallel baseline. Execution flows across GPUs with the layers, and the total 8-card GPU memory availability must not be misread as linear 8-card compute scaling. The next round should compare FSDP/ZeRO-3 low-host-memory initialization or Megatron Expert Parallel, and complete the fixed 110-sample blind test Base/Adapter generation A/B; until then, do not substitute a very low validation Loss for a business-effect conclusion.

## 10. Full DeepSeek V4 Flash: From "Theoretically Feasible" to Real Training

The repository's `train-deepseek-v4-flash-lora.sh` is an **Adapter-only Smoke template** converged from the official public solution. Compared with the official long-run example, it reduces the Micro Batch to 1, the Global Batch to 8, and disables automatic Merge, with the goal of first lowering peak GPU memory and avoiding the generation of huge fully merged weights.

### 10.1 Single Machine 8 × H20: 20-Step LoRA with a Validation Set

On August 24, 2026, a real LoRA SFT was completed using `DeepSeek-V4-Flash-0731-FP8-DSpark`. The base model uses Block-FP8 weights, and training computation uses BF16; the parallel strategy is `TP=1、PP=1、EP=8`. Megatron derives a Dense DP of 8 for non-Expert parameters, while Expert DP is 1; the difference between the two DP definitions is covered in Section 10.3. The data reuses the OpsRoute synthetic fault triage task from earlier, but the training set, validation set, and blind test template families are isolated from one another.

| Item | Measured configuration or result |
| --- | --- |
| GPU | 1 node × 8 NVIDIA H20 141 GB |
| Software | ms-swift 4.6.0.dev0, Megatron-Core 0.19.0, MCore-Bridge 1.7.0.dev0, PyTorch 2.11.0 + CUDA 13.0 |
| Data | 330 Train / 55 Validation; additionally prepared 110 Blind Test |
| Max length / Micro Batch / Global Batch | 512 / 1 / 8 |
| LoRA | Rank 16, Alpha 32, `all-linear` |
| Training / validation / saving interval | 20 / 5 / 5 Step |
| Framework-recorded peak GPU memory | 85.74 GiB/GPU |
| Total training loop duration | 4 minutes 30 seconds, including four validations and four Checkpoints |
| Train Loss | Step 1 was 1.3384, Step 20 was 0.2692 |
| Eval Loss | 0.9755 → 0.6041 → 0.4238 → 0.3469 |
| Experiment tracking | SwanLab upload completed, 1797 records total |

![DeepSeek V4 Flash 0731 LoRA real training and validation Loss](../../assets/training/deepseek-v4-flash-0731/loss-curves.svg)

From Step 5 to Step 20, Validation Loss decreased by approximately `64.4%`, and no NaN, OOM, or gradient explosion occurred during training; the Megatron Checkpoints and Safetensors Adapters at Step 5/10/15/20 were all saved successfully. This proves that the data, Template, FP8 base loading, 8-way Expert Parallel, LoRA Forward/Backward, validation, Checkpoint, and experiment tracking now form a complete engineering pipeline.

But this still cannot be written as "domain effect improved by 64.4%": what decreased is Token Loss, not task accuracy. The 110-sample isolated Blind Test is ready, but this round has not yet completed the Base/Adapter generation comparison, so the status can only be recorded as **training and validation complete, behavioral effect pending acceptance**. The full step-by-step curves, data hashes, and limitations are available at [`h20-deepseek-v4-flash-0731-20260824.json`](https://github.com/runzhliu/aik8s/blob/main/examples/llm-sft-lab/meaningful-sft/results/h20-deepseek-v4-flash-0731-20260824.json).

### 10.2 Three Compatibility Points That Directly Cause Failure

First, the stable `ms-swift 4.4.1 + Megatron-Core 0.18.0 + MCore-Bridge 1.6.0` cannot yet recognize the `dsv4_hybrid` Attention variant. This round used a main-branch snapshot of the public repository; when reproducing, the commits and versions of all three must be locked, not just "install the latest version."

Second, the model configuration declares one MTP layer, but the weight index of the test checkpoint is missing the corresponding normalization and projection weights. Directly setting `mtp_num_layers=1` will report missing keys during the loading phase. This round explicitly uses `mtp_num_layers=0`, which means "this round does not train the auxiliary MTP head," not a claim that the DeepSeek V4 architecture has no MTP.

Third, the Pipeline Layout must be consistent with the MTP configuration. The dual-Stage layout of `MTP=0` uses:

```text
Et*22|t*21L
```

Here `E` is the Embedding, the 43 `t` entries are Transformer Layers, and `L` is the Loss. If the layout still retains `m`, Megatron will refuse to execute during initialization, because the number of MTP layers in the layout is inconsistent with `mtp_num_layers=0`.

### 10.3 What TP, PP, EP, and DP Actually Split

All four parallelism types use more GPUs, but the objects they split are completely different:

| Parallelism | Object Split | What Each GPU Mainly Stores | Main Communication | Primary Goal |
| --- | --- | --- | --- | --- |
| TP: Tensor Parallel | Matrices and computation within the same layer | A portion of one layer's weights | Frequent All-Reduce, All-Gather, or Reduce-Scatter within each layer | Make a single large layer's matrix fit |
| PP: Pipeline Parallel | Model depth | Several consecutive layers | Adjacent Stages pass Activations forward, Gradients backward | Segment a very deep model by layers |
| EP: Expert Parallel | MoE Experts | A portion of Experts; Attention and shared modules are usually still replicated | Token All-to-All after the Router | Spread a large number of Expert weights across multiple GPUs |
| DP: Data Parallel | Input Batch | One full model or a full model shard group | Gradient synchronization every Step; ZeRO/FSDP also synchronizes parameters and optimizer states | Increase sample throughput |

A single training run can be understood as the following four divisions of labor:

```text
TP：一个 Transformer Layer 的大矩阵
    ├─ GPU 0 保存/计算矩阵分片 0
    └─ GPU 1 保存/计算矩阵分片 1
       两张卡合起来才完成这一层

PP：Input → GPU 组 0：Layer 1～22 → GPU 组 1：Layer 23～43 → Loss
    多个 Micro Batch 像流水线一样依次通过各 Stage

EP：Token → Router → GPU 0 的 Expert 0～31
                  → GPU 1 的 Expert 32～63
                  → ...
    计算后再把 Token 送回原来的序列位置

DP：Batch A → 完整模型组 0 ┐
    Batch B → 完整模型组 1 ├─ 同步 Gradient 后更新相同参数
    Batch C → 完整模型组 2 ┘
```

Their impact on performance and GPU memory also differs:

- **TP** reduces per-GPU occupancy of single-layer weights and part of the Activations, but nearly every layer requires communication. It usually depends most on intra-node NVLink/NVSwitch and should not be the first choice across ordinary Ethernet; the current DeepSeek V4 specialized training plan also does not yet support `TP>1`.
- **PP** can approximately reduce the number of layers held per GPU by the number of Stages, but it introduces Pipeline Bubble. When Micro Batches are too few, later Stages often wait for earlier Stages, and adding GPUs does not necessarily make things faster.
- **EP** only distributes MoE Experts; it cannot automatically divide Attention, Embedding, Router, and shared Experts by EP. Its All-to-All grows with the number of Tokens and the routing distribution, which is an important reason why DeepSeek-style MoE cares about RDMA.
- **DP** lets different replicas process different samples, most directly improving throughput; ordinary DDP does not reduce model weight GPU memory, only ZeRO/FSDP further shards Gradients, Optimizer States, or parameters.

#### Why You Cannot Simply Write `GPU 数 = TP × PP × EP × DP`

In a purely Dense model, ignoring Context Parallel, the common relationship is:

```text
World Size = TP × PP × Dense DP
```

But Megatron's MoE Rank has two perspectives simultaneously. EP reuses Ranks in the Dense DP domain to split Experts; it is not an additional fully independent axis. Expert weights use a different relationship:

```text
World Size = Expert TP × EP × PP × Expert DP
```

Therefore, writing only one `DP` for a MoE Run can easily cause misunderstanding. Using this round's measurements as an example:

| Topology | World Size | TP | PP | EP | Dense DP | Expert DP | Actual Meaning |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Single node, 8 GPUs | 8 | 1 | 1 | 8 | 8 | 1 | 8 Ranks each process one Micro Batch, while each holds about 1/8 of the Experts; Experts have no replicas |
| Two nodes, 16 GPUs | 16 | 1 | 2 | 8 | 8 | 1 | First split into 2 Pipeline Stages; within each Stage, 8 Ranks split the Experts; Experts still have no replicas |

The `Global Batch=8、Micro Batch=1` of the single-node configuration can also be explained by Dense DP: `1 × Dense DP 8 = 8`, with no additional gradient accumulation needed. The two-node setup adds a PP Stage, not a second data replica, so the Global Batch remains 8.

The most practical selection order is: if a layer itself does not fit, look at TP first; if the model is too deep or the full model does not fit, look at PP; if there are too many MoE Experts, look at EP; if you want higher sample throughput, increase DP; long sequences additionally require considering CP. The four are usually combined, not used as substitutes for one another. The above definitions and process group relationships can be cross-referenced with the [Megatron Core Parallelism Strategy Guide](https://docs.nvidia.com/megatron-core/developer-guide/latest/user-guide/parallelism-guide.html) and [Megatron Core `parallel_state.py`](https://github.com/NVIDIA/Megatron-LM/blob/main/megatron/core/parallel_state.py).

### 10.4 Initial TCP Test of Single-Node EP=8 vs. Two-Node PP=2 × EP=8

To rule out Checkpoint and validation overhead, a no-save control run was performed using the same model, 12 fixed data samples, 4 Optimizer Steps, the same LoRA, maximum length, and Global Batch. The two-node group explicitly disabled RDMA and confirmed from the NCCL configuration that it was using Ethernet Socket.

| Metric | Single Node, 8 GPUs | Two Nodes, 16 GPUs, TCP | Change |
| --- | ---: | ---: | ---: |
| TP / PP / EP | 1 / 1 / 8 | 1 / 2 / 8 | Only Pipeline Stage added |
| Dense DP / Expert DP | 8 / 1 | 8 / 1 | Neither group has Expert replicas |
| Step 1 cumulative time | 63.09 s | 91.33 s | +44.8% |
| Step 4 cumulative time | 100.78 s | 151.50 s | +50.3% |
| Step 4 cumulative average | 25.20 s/Step | 37.88 s/Step | +50.3% |
| Trainer progress bar total time | 118 s | 165 s | +39.8% |
| Peak GPU memory/GPU | 84.87 GiB | 43.69 GiB | -48.5% |
| Final Loss | 3.0563 | 3.0693 | Numerical trajectories are close |

The first two Steps include TorchInductor compilation and communication warm-up; estimated from progress times, Steps 3–4 are approximately `3～4 秒/步` for single node and `5 秒/步` for two-node TCP. With only 4 Steps and a single run, these numbers are suitable for demonstrating the pipeline and the observed magnitude, not as a throughput commitment.

More importantly, this is not a data-parallel scaling experiment asking "why are 16 GPUs not faster than 8 GPUs." The two-node group uses `PP=2` to split model layers across two Stages, with the goal of reducing per-GPU memory; it adds Pipeline Bubble and cross-node point-to-point communication, so being slower with short sequences and small Batches is expected. A real RDMA benefit must compare **the same two-node PP=2 topology**: TCP and RDMA change only the network transport, with all other conditions fixed.

At the time of this initial test, no RDMA resources were available, so the original record explicitly stated "RDMA not tested." After resources became available, a same-topology negative control was added: `PP=2 / EP=8`'s stable segment changed from TCP `4.109` to RDMA `4.124 秒/Step`, slower by `0.35%`, with no measurable benefit. The reason is that the EP and DP communication groups remain within a single node, and the only cross-machine traffic is Pipeline Activation; this also demonstrates that training benefits cannot be inferred directly from capability labels or theoretical bandwidth.

### 10.5 Public Reproduction Template

Install the currently publicly required components:

```bash
bash install-deepseek-v4-training.sh
```

Then explicitly specify the local model and data directories:

```bash
V4_MODEL_PATH=/models/DeepSeek-V4-Flash \
V4_DATASET_PATH=/workspace/data/train.jsonl \
V4_OUTPUT_DIR=/workspace/output/deepseek-v4-flash-lora \
bash train-deepseek-v4-flash-lora.sh
```

Before starting, you must confirm:

- The exact model version, Tokenizer, and `config.json` are recorded;
- 8 GPUs are visible on the same node, and the P2P/NVLink topology between GPUs matches expectations;
- Host Memory, shared memory, and local temporary space are sufficient;
- Whether FP4 weights are actually converted to FP8 or BF16 after loading has been confirmed from the logs;
- All Ranks under `EP=8` can complete initialization;
- The first round runs only a minimal amount of data and Steps, checking peak HBM, Loss, Step Time, and Checkpoint first;
- After the Adapter passes Transformers inference regression, only then discuss merging and vLLM/SGLang deployment.

DeepSeek V4 currently cannot directly perform FP4 blockwise training; the public approach converts to FP8 or BF16 during the loading phase; the current specialized plan also does not yet support `TP>1`. When combining LoRA with FP8, only the Adapter should be saved, then merged with the BF16 base model, to avoid low-precision rounding swallowing the LoRA Delta. [DeepSeek V4 Training Notes](https://github.com/modelscope/ms-swift/blob/main/docs/source/BestPractices/deepseek-v4.md)

## 11. From Single-Node Multi-GPU Testing to Multi-Node RDMA

Distributed training cannot be evaluated by comparing only a single "total training time." It is recommended to first use collective communication micro-benchmarks to confirm the link, then use the same SFT workload to observe whether network differences enter the end-to-end bottleneck:

| Stage | Topology | Main Question Answered |
| --- | --- | --- |
| Single GPU | 1 node × 1 GPU | What is the compute baseline without gradient synchronization |
| Single-node multi-GPU | 1 node × 2/4/8 GPUs | How much overhead do PCIe/NVLink and DDP introduce |
| Multi-node TCP | 2 nodes × N GPUs, `NCCL_IB_DISABLE=1` | How much is lost after crossing machines over default Ethernet |
| Multi-node RDMA | Keep the same nodes and GPU count, enable only RDMA | How much communication time can RDMA recover |

The accompanying [`distributed`](https://github.com/runzhliu/aik8s/tree/main/examples/llm-sft-lab/distributed) Harness provides:

- PyTorch/NCCL AllReduce message size sweep;
- Reproducibly generated local data with Token lengths and SHA-256;
- Fixed Global Batch Qwen3-4B LoRA strong scaling tests;
- Machine-readable `NCCL_BENCH` and `SFT_BENCH_RESULT` output.

With a fixed Global Batch:

```text
N 卡扩展效率 = N 卡 samples/s ÷（单卡 samples/s × N）
```

Each topology is repeated at least three rounds, comparing medians; image pulls, model loading, Tokenization, and Checkpoint are excluded from the training interval. TCP/RDMA A/B tests must fix nodes, model, data Hash, Batch, Steps, software versions, and power settings, and confirm from NCCL INFO logs whether `NET/Socket` or `NET/IB` was actually selected.

Also note that the training method itself determines communication volume. The Rank-8 LoRA in this chapter has only about 16.5 million trainable parameters, so the gradients synchronized by DDP are far smaller than full-parameter SFT; if the LoRA TCP/RDMA difference is small, that is a meaningful business conclusion and should not be extrapolated to claim RDMA has no benefit for continued pretraining, FSDP/ZeRO, or large MoE.

### 11.1 Initial L20 Single-Node and Multi-Node TCP Test

On August 20, 2026, an initial test with lower resource occupancy was first completed on the available L20. The software stack was the same as the earlier single-GPU experiments, with NCCL version 2.28.9. The communication micro-benchmark used the same `world_size=2`: the single-node group was `1 节点 × 2 GPU`, the cross-node group was `2 节点 × 1 GPU`, and both groups explicitly disabled IB, with NCCL INFO confirming the cross-node group used `NET/Socket + eth0`. This avoids mistaking GPU count changes for network differences.

| AllReduce Message Size | Single-Node Dual-GPU Latency | Two-Node Single-GPU TCP Latency | Single-Node Dual-GPU BusBw | Two-Node Single-GPU TCP BusBw |
| ---: | ---: | ---: | ---: | ---: |
| 1 MiB | 0.105 ms | 0.773 ms | 10.00 GB/s | 1.36 GB/s |
| 16 MiB | 1.164 ms | 10.306 ms | 14.42 GB/s | 1.63 GB/s |
| 64 MiB | 4.608 ms | 40.910 ms | 14.56 GB/s | 1.64 GB/s |
| 256 MiB | 18.342 ms | 163.131 ms | 14.63 GB/s | 1.65 GB/s |

At the 256 MiB message size, cross-node TCP latency is approximately `8.89×` of single-node dual-GPU, and BusBw is only about `11.2%`. This shows that ordinary Ethernet is indeed a clear bottleneck for large-message collective communication, but the micro-benchmark cannot be directly equated to training being 8.89× slower.

A LoRA SFT strong scaling test was then run with the same model, data Hash, 555-Token samples, 20 Steps, Micro Batch 1, and Global Batch 8. The SHA-256 of the 512 deterministic samples is `0782c78c725ee1d6f3ac9aab3ef91c65000d5841b551f4185eca66aa74080973`. The dual-GPU group ran with `2 节点 × 1 GPU`, with gradient accumulation reduced from 8 on single GPU to 4, so each Optimizer Step still sees the same amount of data.

| Topology | World Size | Global Batch | Train Runtime | samples/s | Peak GPU memory/GPU | Speedup vs. Single GPU | Scaling Efficiency |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 node × 1 L20 | 1 | 8 | 57.49 s | 2.783 | 9.05 GiB | 1.00× | 100% |
| 2 nodes × 1 L20, TCP | 2 | 8 | 33.41 s | 4.789 | 9.11 GiB | 1.72× | 86.0% |

Even though the AllReduce micro-benchmark showed TCP is clearly slower than single-node interconnect, this Rank-8 LoRA still achieved `1.72×` speedup, with training time reduced by approximately `41.9%`. The reason is that it has only 16.51 million trainable parameters, the gradient synchronization volume is small, and compute still dominates; this precisely demonstrates that both communication micro-benchmarks and real training must be examined together, and business benefits cannot be inferred from bandwidth alone.

The above numbers are from a single run, suitable for environment reconnaissance, not formal capacity conclusions. The subsequent H20 two-node experiments were completed using the at-least-three-rounds median metric, but they used a topology that more strongly triggers cross-node MoE Collectives, so they cannot be directly combined with these small-model L20 numbers into a scaling curve.

### 11.2 H20 Two-Node MoE TCP/RDMA Three-Round A/B

On August 25, 2026, `2 节点 × 8 张 H20` was used to further complete the formal Transport comparison. The model was DeepSeek V4 Flash 0731, with `TP=1、PP=1、EP=16、Dense DP=16` configured so that both MoE All-to-All and Dense DP synchronization crossed nodes. With Global Batch fixed at 16, Max Length at 512, and data Hash and software stack held constant, TCP and RDMA each ran three rounds of 20 Steps, excluding the first 5 compilation and warm-up Steps.

| Metric | TCP | RDMA | Change |
| --- | ---: | ---: | ---: |
| Median of three-round stable means | 4.490 s/Step | 3.050 s/Step | **-32.08%** |
| Equivalent sample throughput | 3.563 samples/s | 5.246 samples/s | **+47.23%** |
| 256 MiB/Rank AllReduce | 1.412 GB/s | 204.482 GB/s | 144.81× |
| 256 MiB/Rank All-to-All | 1.446 GB/s | 39.180 GB/s | 27.09× |

NCCL logs respectively confirmed that the TCP group used `NET/Socket` and the RDMA group used `NET/IB/.../GDRDMA/Shared`. The microbenchmark ratios only indicate link capability, not training speedup; the actual SFT outcome was a stable step-time reduction of approximately 32%. The full three-round raw data, negative controls, SwanLab screenshots, and reproduction methodology are available in [How Much Faster Can RDMA Really Make Distributed Training: DeepSeek V4 Dual-Node 16-GPU Field Test](rdma-distributed-training-benchmark.md).

### 11.3 Dual-Node 60-Step Convergence Experiment: The Best Point Is Not the Last Step

The earlier 20-Step TCP/RDMA A/B test was used to compare performance and cannot answer whether the model continues to generalize. For this reason, a separate 60-Step LoRA run was executed on the same dual-node 16-GPU `TP=1 / PP=1 / EP=16 / Dense DP=16` topology, using 330 training samples and 55 isolated Validation samples, with GDRDMA fixed and validation performed every 10 Steps.

| Item | Configuration or Result |
| --- | --- |
| Max Length / Micro Batch / Global Batch | 512 / 1 / 16 |
| LoRA | Rank 16, Alpha 32, `all-linear` |
| Training / Validation / Save interval | 60 / 10 / 20 Step |
| Approximate data epochs | 2.91 Epoch |
| Framework-recorded peak GPU memory | 50.87 GiB/GPU |
| Train Loss | 1.50588 → 0.00030 |
| Best Validation | Step 30, 0.04059 |
| Final Validation | Step 60, 0.06463; 59.25% rebound from the best point |

![Dual-node 60-Step DeepSeek V4 Validation Loss](../../assets/training/deepseek-v4-rdma/convergence-validation.svg)

This time, the inflection point that short Smoke runs could not reveal was finally observed: Train Loss dropped from `0.01786` at Step 30 all the way to `0.00030` at Step 60, while Validation Loss bottomed out at Step 30 and then rose continuously. This indicates that the Adapter had begun memorizing this small-scale synthetic training dataset, and continued training actually weakened generalization to the isolated template family. Formal training should therefore select and early-stop based on Validation, rather than publishing the last step by default.

The experiment also exposed a reproducibility issue: `eval_steps=10` and `save_steps=20` caused the exact best Step 30 to not be saved; among the three existing Checkpoints, only the Validation-suboptimal Step 40 could be selected. The next round should make the save interval cover every validation point, or enable "save on best metric trigger." In addition, the framework automatically ran only 3 Validation Iterations each time, so this round did not independently prove that all 55 configuration samples participated in every validation; the 110 Blind Tests have also not yet been executed, so Token Loss cannot be written as task accuracy. Public per-point values are available at [`h20-deepseek-v4-convergence-20260825.json`](https://github.com/runzhliu/aik8s/blob/main/examples/llm-sft-lab/meaningful-sft/results/h20-deepseek-v4-convergence-20260825.json).

## 12. Manage Training Experiments with SwanLab, Watch Infrastructure with Grafana

TensorBoard is suitable for quickly viewing local curves, but once a training cluster is shared by multiple people, projects, Runs, hyperparameters, tags, experiment comparison, and access control become new requirements. At this point, SwanLab can serve as the experiment tracking layer, while Prometheus, DCGM Exporter, and Grafana remain the infrastructure monitoring layer:

```text
ms-swift -> SwanLab：Loss、Learning Rate、Gradient Norm、吞吐、配置、Run 对比
GPU / NIC / Kubernetes -> Prometheus -> Grafana：利用率、显存、功耗、慢 Rank、网络与告警
```

The SwanLab SDK in the training image should first log in to the private service. On shared hosts, project-level login is preferred; Kubernetes Jobs inject the API Key via Secret:

```bash
python -m pip install 'swanlab>=0.8,<1'
swanlab login --host https://swanlab.example.com --local
```

The minimal script in this chapter supports switching between TensorBoard and SwanLab:

```bash
TRAIN_REPORT_TO=swanlab \
TRAIN_SWANLAB_PROJECT=llm-sft-lab \
TRAIN_SWANLAB_EXP_NAME=qwen3-4b-lora-smoke \
bash train-qwen3-4b-lora.sh
```

The corresponding ms-swift parameters are `--report_to swanlab`, `--swanlab_project`, and `--swanlab_exp_name`. The API Key must not be used as a command-line argument, plaintext environment value, or image layer; Pods should reference the Secret via `secretKeyRef`, and read permissions on the Secret should be restricted.

On August 21, 2026, an end-to-end Smoke test that did not consume GPU was completed: the training image came with the SwanLab SDK `0.8.4`, successfully created a 6-Step synthetic Run, and uploaded 39 records of Loss, Learning Rate, and Tokens/s. The validation also revealed interface differences between the SDK and the newer documentation, so image upgrades cannot just do `import swanlab`; at minimum, five checks must be completed: login, Run creation, continuous writing, normal termination, and Web page opening.

On the same day, a real Qwen3.5-4B SFT Run uploaded 120 Steps of numeric metrics; Train Loss, Gradient Norm, Learning Rate, Token Accuracy, and four Validations were all viewable on the page. The integration also exposed a non-blocking compatibility issue: ms-swift 4.4.1 reported display values such as `30/120` and `3m 53s` as String Scalars, and SwanLab SDK 0.8.4 rejected these strings; numeric metrics, training, Checkpoints, and blind tests were unaffected. After upgrading the SDK, this regression case should still be retained, rather than only checking whether the page can log in.

Formal training needs to answer two questions simultaneously: whether Loss changes as expected, and whether the change comes from a healthy training process. A Loss decrease does not equal improved model effectiveness; the Base and Adapter should also be compared on an isolated evaluation set, and a unified Run ID should be used to align training Steps with Grafana's GPU, network, and system metrics. The complete deployment boundaries, production considerations, and example Values are available in [SwanLab Self-Hosting: From Kubernetes Deployment to Real SFT Metrics](swanlab-self-hosted.md).

When summarizing public experiments, at minimum retain the real Run's training and validation curves, and record key hyperparameters at the same time; if the article discusses GPU or network bottlenecks, add Grafana charts from the same time window. Next to screenshots, still provide the model version, data Hash, training parameters, and machine-readable raw results; screenshots must not be the only evidence. Before publication, crop out the address bar, internal domain names, usernames, Run URLs, node names, and other organizational information, and confirm that the image contains no API Keys, data samples, or sensitive logs. Synthetic Smoke is only for validating the pipeline and must not be used as SFT effectiveness charts.

## 13. When Kubernetes Is Needed

In the single-GPU Smoke phase, running directly in an existing GPU development container is simplest. Once any of the following conditions is met, wrap the command as a Kubernetes Job, Kubeflow TrainJob, or JobSet:

- Queue admission and Gang Scheduling are needed;
- Training crosses nodes and requires stable Rank, Service, and RDMA configuration;
- Automatic retry, preemption recovery, and Checkpoint lifecycle management are needed;
- Multiple people share GPUs, and image, quota, priority, and audit information must be recorded;
- Training must become a repeatable pipeline rather than a one-off terminal command.

Kubernetes only handles resource and job lifecycle; it will not fix incorrect data, Loss Masks, model implementations, or parallel strategies. First get things working in a single-card container, then wrap it in a platform; this significantly shortens the troubleshooting path.

## 14. Experiment Recording Template

Each run should save at minimum:

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
metric_run_id:
metric_screenshot_paths:
known_limitations:
```

When backfilling this chapter with first-round results, failed attempts should also be recorded. OOM, conversion errors, NCCL initialization timeouts, and failures to be loaded by the inference engine are all important evidence that determined the final approach.

## 15. Next Round Experiment Order

1. Completed: single-GPU Qwen3-4B 20-Step Smoke, plus Qwen3.5-4B 120-Step LoRA, SwanLab curves, and 110-sample Base/Adapter blind tests;
2. Training pipeline completed, effect closure pending: Qwen3.6-35B-A3B completed 120 Steps of ZeRO-3 LoRA and four Validations on a single node with 8 L20 GPUs, but the Adapter blind test summary was not exported before temporary task cleanup;
3. Initial tests completed: NCCL comparison of single-node dual-GPU and dual-node single-GPU, plus SFT strong scaling over dual-node single-GPU TCP;
4. Completed: DeepSeek V4 Flash 0731 completed 20-Step LoRA, four Validations, four Checkpoints, and SwanLab reporting on a single node with 8 H20 GPUs;
5. Completed: dual-node `PP=2 / EP=8` TCP/RDMA negative control showed no measurable benefit; dual-node `PP=1 / EP=16 / Dense DP=16` each completed three rounds of TCP/RDMA A/B, with stable step time down 32.08% and equivalent throughput up 47.23%;
6. Convergence observation completed, effect closure pending: dual-node GDRDMA 60-Step achieved best Validation at Step 30, rebounding 59.25% at Step 60; next round runs Base/Adapter A/B on 110 isolated Blind Test samples;
7. Replace the synthetic fault triage data with a manually reviewed real small dataset, run 100–500 Steps, and re-create blind tests never used for hyperparameter tuning;
8. Only after correctness and evaluation pass, expand data, length, and training time, and design multi-node full-parameter training with Checkpoint baselines.

This route keeps the cheapest errors in the single-GPU phase and spends expensive GPU time only on problems already validated through the data and training closure.

## References

- [ms-swift Quick Start](https://github.com/modelscope/ms-swift#-quick-start)
- [Don't Stop Pretraining: Domain Continued Pretraining](https://arxiv.org/abs/2004.10964)
- [LoRA: Low-Rank Adaptation of Large Language Models](https://arxiv.org/abs/2106.09685)
- [InstructGPT: SFT, Reward Model, and RLHF](https://arxiv.org/abs/2203.02155)
- [Training Qwen3 with ms-swift](https://github.com/QwenLM/Qwen3/blob/main/docs/source/training/ms_swift.md)
- [ms-swift Qwen3.5 Best Practice](https://github.com/modelscope/ms-swift/blob/main/docs/source/BestPractices/Qwen3_5-Best-Practice.md)
- [Megatron-SWIFT Quick Start](https://github.com/modelscope/ms-swift/blob/main/docs/source_en/Megatron-SWIFT/Quick-start.md)
- [Megatron-SWIFT DeepSeek V4 Best Practices](https://github.com/modelscope/ms-swift/blob/main/docs/source/BestPractices/deepseek-v4.md)
- [DeepSeek V4 Official Model Card](https://huggingface.co/deepseek-ai/DeepSeek-V4-Pro)
- [SwanLab Kubernetes Deployment](https://docs.swanlab.cn/self_host/kubernetes/deploy.html)
- [SwanLab Python Login API](https://docs.swanlab.cn/api/py-login.html)
- [ms-swift Command-Line Parameters](https://github.com/modelscope/ms-swift/blob/main/docs/source/Instruction/Command-line-parameters.md)
