# DeepSeek-V4-Flash-Vision-Exp 测试材料

这组材料用于 `deepseek-ai/DeepSeek-V4-Flash-Vision-Exp` 的零 GPU 预检、多模态功能测试和
OpenAI-compatible 性能压测。2026-09-01 已在单节点 4×141GB H20 上通过 SGLang Vision
Preview 完成 Day 0 实测；vLLM 暂无 Vision-Exp 端到端实现，因此没有伪造框架 A/B 数据。

完整结论、卡型矩阵、Gate 和标准多模态测试方法见：

[`docs/ai-k8s/practices/deepseek-v4-flash-vision-exp-deployment-benchmark-plan.md`](../../docs/ai-k8s/practices/deepseek-v4-flash-vision-exp-deployment-benchmark-plan.md)

## 文件

```text
preflight.py            # 零 GPU：模型/视觉权重/分片/同步残留检查
smoke.py                # OpenAI API：文本、单图、双图交错和图片敏感性
prepare_perf_dataset.py # 生成确定性冷/热图片压测集，不依赖外部数据集
requirements-client.txt # 生成图片数据所需的最小客户端依赖
cases.csv               # 性能矩阵
benchmark.sh            # 同一 vllm bench serve 客户端压两个框架，默认 dry-run
datasets/README.md      # 质量数据集下载与离线搬运清单
images/README.md        # 当前运行时缺口与后续镜像同步 Gate
```

## 0. CFS 预检

模型路径以同步完成后的实际目录为准：

```bash
MODEL_PATH=/models/DeepSeek-V4-Flash-Vision-Exp/v1 \
python3 preflight.py
```

脚本只读取配置、Index 和文件大小，不计算权重哈希，不申请 GPU。

CFS Gate 通过且运行时支持落地后，只把模型预热到选中的 H20-3e 节点 NVMe
`<NVME_MODEL_ROOT>/DeepSeek-V4-Flash-Vision-Exp/v1`，容器路径固定为
`/models-nvme/DeepSeek-V4-Flash-Vision-Exp/v1`；不要预先铺满所有卡型节点。

## 1. 生成性能请求集

先生成冷图片矩阵；每个请求使用不同图片：

```bash
python3 -m pip install -r requirements-client.txt

python3 prepare_perf_dataset.py \
  --output-root /datasets/aik8s/deepseek-v4-vision/perf \
  --cache-mode cold
```

再生成热 cache 矩阵；同一 Case 复用图片：

```bash
python3 prepare_perf_dataset.py \
  --output-root /datasets/aik8s/deepseek-v4-vision/perf-warm \
  --cache-mode warm
```

脚本生成 360p、720p、1080p、2×720p 和 4×720p 五类 JSONL。每条记录使用 vLLM
`CustomImageDataset` 的交错 `content` 格式，可发送到任意 OpenAI-compatible endpoint。

## 2. 功能 Smoke

使用已随模型仓库同步的两张官方图片：

```bash
BASE_URL=http://127.0.0.1:30000 \
MODEL=deepseek-v4-flash-vision-exp \
IMAGE_CARROTS=/models/DeepSeek-V4-Flash-Vision-Exp/v1/inference/examples/images/carrots.jpeg \
IMAGE_CORN=/models/DeepSeek-V4-Flash-Vision-Exp/v1/inference/examples/images/corn.jpeg \
python3 smoke.py
```

Smoke 会确认图片答案随输入变化，并验证双图顺序；仅 HTTP 200 不算通过。

## 3. 压测 dry-run

```bash
ENGINE=sglang \
BASE_URL=http://sglang-endpoint:30000 \
DATA_ROOT=/datasets/aik8s/deepseek-v4-vision \
bash benchmark.sh
```

确认命令后才执行：

```bash
ENGINE=sglang \
EXECUTE=1 \
BASE_URL=http://sglang-endpoint:30000 \
MODEL=deepseek-v4-flash-vision-exp \
TOKENIZER=/models-nvme/DeepSeek-V4-Flash-Vision-Exp/v1 \
DATA_ROOT=/datasets/aik8s/deepseek-v4-vision \
bash benchmark.sh
```

对 vLLM 只替换 `ENGINE` 和 `BASE_URL`。两个框架必须使用同一客户端镜像、同一 JSONL、同一
模型目录/Revision、GPU 拓扑、Context 和优化开关。SGLang 自带 `bench_serving` 只用于内部
诊断，结果不与主 A/B 表混用。

## 运行时状态 Gate

在 SGLang/vLLM 官方仓库出现以下内容之前，`benchmark.sh` 只能作为准备材料：

- Vision-Exp 专用模型实现或明确复用路径；
- `DeepseekV4ForCausalLM` 多模态注册；
- Vision/Aligner 权重加载；
- `<｜deepseek_image｜>`、单图/多图交错预处理；
- 至少一条端到端图片测试或官方 Recipe。

当前文本版 DeepSeek-V4 镜像即使能启动，也不能据此跳过 Gate。
