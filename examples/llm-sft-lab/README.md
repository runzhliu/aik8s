# 大模型 SFT 最小闭环

这组材料对应文档《大模型 SFT 训练实战：从单卡 LoRA 到 DeepSeek V4》。`train-qwen3-4b-lora.sh` 保留为 20-Step 工程 Smoke；当前可量化实验位于 `meaningful-sft/`，默认使用单张 GPU、Qwen3.5-4B、LoRA 和隔离盲测比较 Base/Adapter。

## 最短运行路径

要求宿主机或容器已安装 NVIDIA Driver，并且当前 Python 环境中的 PyTorch 能识别 CUDA。

```bash
cd examples/llm-sft-lab

bash install-ms-swift.sh
source .venv/bin/activate

bash preflight.sh
bash train-qwen3-4b-lora.sh
bash infer-latest-adapter.sh
```

如果已经有可用的 CUDA PyTorch 和 ms-swift 环境，可以跳过安装脚本。

要验证训练前后的实际差值，而不是只看 Loss：

```bash
cd meaningful-sft
TRAIN_MODEL_ID=/models/Qwen3.5-4B bash run-ab.sh
```

该实验生成 330 条训练、55 条验证和 110 条盲测样本，并输出结构化指标与机器可读对比结果。

想先通过界面认识参数，可以运行 `swift web-ui`；正式实验仍建议保存并执行本目录中的 CLI 脚本，便于审查和复跑。不要把无认证的训练 UI 直接暴露到公网。

默认模型由 ModelScope 下载。使用本地权重：

```bash
TRAIN_MODEL_ID=/models/Qwen3-4B-Instruct-2507 \
bash train-qwen3-4b-lora.sh
```

T4 使用 FP16：

```bash
TRAIN_TORCH_DTYPE=float16 bash train-qwen3-4b-lora.sh
```

常用覆盖项：

```bash
TRAIN_DATASET_PATH=/workspace/data/train.jsonl \
TRAIN_MAX_LENGTH=2048 \
TRAIN_MAX_STEPS=100 \
TRAIN_OUTPUT_DIR=/workspace/output/qwen3-4b-lora \
bash train-qwen3-4b-lora.sh
```

## 文件说明

| 文件 | 用途 |
| --- | --- |
| `data/train.jsonl` | 只用于工程 Smoke 的小型对话数据 |
| `install-ms-swift.sh` | 创建 `.venv` 并安装 PyPI 版 ms-swift |
| `preflight.sh` | 输出 GPU、PyTorch、CUDA 和 ms-swift 版本 |
| `train-qwen3-4b-lora.sh` | 单卡 20-Step LoRA Smoke |
| `infer-latest-adapter.sh` | 自动查找最新 Checkpoint 并交互推理 |
| `install-deepseek-v4-training.sh` | 安装 V4 公开方案需要的开发版组件 |
| `train-deepseek-v4-flash-lora.sh` | 单机八卡 V4-Flash Adapter-only 模板 |
| `distributed/` | 单机多卡、多机 TCP/RDMA 的 NCCL 与 SFT 对照 Harness |
| `meaningful-sft/` | 默认 Qwen3.5-4B，带盲测集和自动评分的故障分诊 Base/Adapter A/B |
| `swanlab/` | SwanLab 私有化部署边界与 ms-swift 接入示例 |

## 成功标准

- 训练日志没有数据 Schema、OOM、NaN/Inf 或 CUDA 错误；
- 输出目录生成 Adapter Checkpoint；
- `infer-latest-adapter.sh` 能加载 Adapter 并返回结果；
- 保存依赖版本、显存峰值、最终 Loss、Step Time 和固定问题的 Base/Adapter 输出。

示例数据很小，即使 Loss 很快下降也不代表模型获得了可泛化的领域能力。

公开参考实测：单张 L20 46 GB 使用默认 20-Step 配置，训练耗时 31.39 秒，ms-swift 日志记录的峰值显存为 7.94 GiB，最终 Adapter 约 63 MiB。完整参数、统计口径和推理验证见正文“单张 L20 实测结果”。

## DeepSeek V4 Flash 模板

V4 模板不是单卡脚本的直接替换：它需要单机八卡高显存 GPU、完整模型权重以及 Megatron-SWIFT 环境。建议先阅读正文中的精度、Expert Parallel 和 LoRA 合并限制，再执行：

```bash
bash install-deepseek-v4-training.sh

V4_MODEL_PATH=/models/DeepSeek-V4-Flash \
V4_DATASET_PATH=/workspace/data/train.jsonl \
V4_OUTPUT_DIR=/workspace/output/deepseek-v4-flash-lora \
bash train-deepseek-v4-flash-lora.sh
```

默认关闭 Merge，只保存 Adapter，避免 Smoke 阶段额外生成数百 GB 的完整权重。

## 接入 SwanLab

TensorBoard 不是唯一选择。激活私有化 SwanLab、创建 API Key 后，先在训练目录完成项目级登录，避免把凭据保存到共享用户目录：

```bash
python -m pip install 'swanlab>=0.8,<1'
swanlab login --host https://swanlab.example.com --local
```

再让 ms-swift 把训练指标上报到 SwanLab：

```bash
TRAIN_REPORT_TO=swanlab \
TRAIN_SWANLAB_PROJECT=llm-sft-lab \
TRAIN_SWANLAB_EXP_NAME=qwen3-4b-lora-smoke \
bash train-qwen3-4b-lora.sh
```

API Key 不应写进脚本、镜像或 Git；在 Kubernetes 中应通过 Secret 注入，或在受控工作目录执行项目级登录。部署说明见 [`swanlab/README.md`](swanlab/README.md)。
