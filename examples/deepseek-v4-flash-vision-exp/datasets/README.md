# Vision-Exp 数据集准备清单

## 最小结论

首轮性能压测不需要下载公开数据集。运行 `../prepare_perf_dataset.py` 即可生成固定图片数、
分辨率、冷/热 cache 的可复现 JSONL。公开数据集只用于内容质量与 Agent 能力评测。

建议先准备下面三个 P1 数据集：

1. `xai-org/RealworldQA`：真实世界感知，小而快；
2. `AI4Math/MathVista`：图形、图表和数学视觉推理，先跑 `testmini`；
3. `MMMU/MMMU`：多学科、多图和专业图表，先跑 validation。

如果要验证 DeepSeek 模型卡强调的多模态 Agent 能力，再补 `likaixin/ScreenSpot-Pro`。

## 推荐目录

```text
/datasets/aik8s/deepseek-v4-vision/
├── hf-cache/
├── RealworldQA/
├── MathVista/
├── MMMU/
├── ScreenSpot-Pro/
├── ChartQA/
├── OCRBench/
├── perf/
└── perf-warm/
```

下载时保存每个数据集的 commit/revision、许可文件和下载日志。不要只记录 `main`。

## Hugging Face 数据集

在可访问公网的中转机上使用 `hf download`，不要通过本地 VPN 搬大文件：

```bash
DATASET_ROOT=/data/deepseek-v4-vision

hf download xai-org/RealworldQA \
  --repo-type dataset \
  --revision 17e7f75e092e47169732462ea3cdfebe911105dd \
  --local-dir "${DATASET_ROOT}/RealworldQA"

hf download AI4Math/MathVista \
  --repo-type dataset \
  --revision 2b6ad69445fbb5695c9b165475e8decdbeb97747 \
  --local-dir "${DATASET_ROOT}/MathVista"

hf download MMMU/MMMU \
  --repo-type dataset \
  --revision 98e6ac0cb9b7b2cd2c991b85a50762edc4aedc68 \
  --local-dir "${DATASET_ROOT}/MMMU"

hf download likaixin/ScreenSpot-Pro \
  --repo-type dataset \
  --revision 210e78d3844251110bff86c95835ebd37a6930fa \
  --local-dir "${DATASET_ROOT}/ScreenSpot-Pro"
```

上面的 Revision 是 2026-08-31 核对到的当前 commit；不要在两次框架对比之间更新数据集。
若后续确实需要吸收数据修订，建立一个新版本目录并同时重跑两个框架，不要覆盖旧数据。

官方地址与规模：

| 数据集 | 官方地址 | 公开规模 | 主要指标 |
| --- | --- | ---: | --- |
| RealWorldQA | https://huggingface.co/datasets/xai-org/RealworldQA | 765 条，约 678 MB | Accuracy |
| MathVista | https://huggingface.co/datasets/AI4Math/MathVista | 约 1.75 GB | 官方答案抽取/Accuracy |
| MMMU | https://huggingface.co/datasets/MMMU/MMMU | 11.5K 题 | Accuracy |
| ScreenSpot-Pro | https://huggingface.co/datasets/likaixin/ScreenSpot-Pro | 1,581 图，约 3.38 GB | Grounding success |

## ChartQA 与 OCRBench

这两套优先使用官方代码和 scorer：

```bash
git clone https://github.com/vis-nlp/ChartQA.git
git clone https://github.com/Yuliang-Liu/MultimodalOCR.git
```

- ChartQA 官方仓库自带基础数据，并链接包含完整 annotation 的 Hugging Face 数据；
- OCRBench 汇集多个来源，下载前逐项检查子数据集的许可和内部使用边界；
- 不要只抽图片而丢掉原始 question、answer、split 和 scorer 版本。

官方地址：

- https://github.com/vis-nlp/ChartQA
- https://github.com/Yuliang-Liu/MultimodalOCR

## GUI Agent / 浏览器 Agent

ScreenSpot-Pro 是静态 GUI grounding 数据集，适合第一阶段。VisualWebArena 是完整浏览器
环境，不是一个图片压缩包；它需要部署网站、浏览器、任务配置和 evaluator，放在服务稳定后的
P3 阶段：

- https://github.com/web-arena-x/visualwebarena

模型卡里的 AutomationBench、ApexBench、ZeroBench、Chartography 和 Agents' Last Exam
不应在没有公开版本、任务环境和官方 scorer 的情况下自行仿造同名分数。能取得官方环境时再
追加，当前不作为部署验收阻塞项。

## 离线集群使用

数据同步到 CFS 后，在评测 Pod 固定缓存目录并禁止自动联网：

```bash
export HF_HOME=/datasets/aik8s/deepseek-v4-vision/hf-cache
export HF_DATASETS_CACHE="${HF_HOME}/datasets"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
```

质量评测建议固定一个 `lmms-eval` commit，用 `async_openai` 指向 SGLang/vLLM 的同一 OpenAI
Chat endpoint。两个框架必须使用同一 prompt 模板、解码参数、dataset revision 和 scorer。

## 许可提示

- MMMU：Apache-2.0；
- MathVista：新增部分为 CC BY-SA 4.0，底层图片仍归原作者；
- RealWorldQA：CC BY-ND 4.0；
- ScreenSpot-Pro：MIT；
- ChartQA/OCRBench：以各官方仓库及子数据集许可为准。

这些数据默认只作为内部评测材料。对外发布样例图、错误案例或数据子集前再做一次许可核对。
