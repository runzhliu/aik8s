# DeepSeek-V4-Flash-Vision-Exp 部署、测试与压测计划

> 状态：2026-09-01 已执行。单节点 4×H20 的 SGLang Preview 部署、OpenWebUI 图片验收和
> 79 轮压测已经完成，3,856 请求成功、0 失败，服务已自动缩容。最终公开结果见
> [DeepSeek-V4-Flash-Vision-Exp Day 0：4×H20 多模态部署与压测](deepseek-v4-flash-vision-exp-day0-h20.md)。

> 运行时更新（2026-09-01）：SGLang 已为 Vision-Exp 增加专用 Cookbook 和预览实现，当前固定
> commit 为 `914197146f8a3407960e5c7037d0463e03c37be9`，镜像为
> `lmsysorg/sglang:dev-dsv4-flash-vision`。实现 PR `#37253` 尚未进入正式 release；4×B200
> TP4 已验证，H200 TP4/H100 TP8 配方仍处于验证中。vLLM 官方 main 仍没有可用于正式测试的
> 完整 Vision-Exp 支持。

## 结论先行

`deepseek-ai/DeepSeek-V4-Flash-Vision-Exp` 是 DeepSeek-V4 家族首个实验性视觉多模态模型。
官方仓库为 305B 参数、48 个 Safetensors 分片；Index 记录的 Tensor 数据为
`167,811,372,792` 字节，实际 48 个分片文件合计 `167,819,404,368` 字节，约
156.31 GiB。它在 DeepSeek-V4-Flash 上增加了 32 层 ViT、Aligner、图像占位向量和图像可见性
注意力，不能把文本版 DeepSeek-V4 的启动命令直接当作多模态 Recipe。

模型发布当天的仓库状态如下；2026-09-01 的 SGLang 更新以上方运行时更新为准：

- SGLang 有成熟的 DeepSeek-V4 文本 Cookbook，但没有
  `DeepSeek-V4-Flash-Vision-Exp` 的专用 Recipe、模型注册或视觉 token 处理代码；
- vLLM 有 DeepSeek-V4-Flash 文本 Recipe，但 `DeepseekV4ForCausalLM` 仍注册在纯文本模型表，
  不在多模态模型表中；官方代码也没有 `<｜deepseek_image｜>` 的处理实现；
- Hugging Face 页面自动展示的 `vllm serve ...` / `sglang.launch_server ...` 一行命令只说明
  通用入口，不构成 Vision-Exp 端到端已支持的证据；
- 当前唯一明确提供的视觉执行路径是模型仓库里的 `inference/` 参考实现：先转换为 TP4
  checkpoint，再用 `torchrun --nproc-per-node 4` 运行。官方明确说明它不是生产 Serving Engine。

2026-09-01 更新后，SGLang 专用预览镜像可以进入 Serving Gate，但仍要先通过零 GPU 镜像探针
和图片 E2E Gate，再申请 H20。vLLM 继续停在运行时支持 Gate，不使用文本版镜像代替多模态
实现。若使用官方参考实现验证模型本身，结果必须标为 `reference runtime`，不能与 SGLang
吞吐对比混用。

## 固定模型对象

| 项目 | 公开仓库实值 |
| --- | --- |
| Repo | `deepseek-ai/DeepSeek-V4-Flash-Vision-Exp` |
| Revision | `e46e16bf6035c6f317eb2ac7458eb0362926d402` |
| 外层架构 | `DeepseekV4ForCausalLM` |
| 参数量 | 305B |
| Context | 1,048,576 |
| 权重格式 | 混合 FP4 experts / FP8 dense，HF config 标记 FP8 `e4m3` + `ue8m0` scale |
| 分片 | 48 |
| Index Tensor 数据 | 167,811,372,792 B |
| 分片文件合计 | 167,819,404,368 B（156.31 GiB） |
| 视觉模块 | 32-layer ViT，dim 1024，patch 14，最多 384 image tokens/image |
| Index 中视觉权重 | 259 个 `vision.*`、4 个 `aligner.*`、4 个 image marker |

外层 `config.json` 的 `vision_config` 和 `projector_config` 当前均为 `null`；完整视觉参数放在
`inference/config.json`，视觉模块通过权重命名和官方参考代码实现。这一点会影响通用框架的
自动模型识别，也是运行时探针必须检查的内容。

## 卡型与拓扑判断

这里必须区分“显存容得下”和“框架已支持”。下面的每卡权重只是把 156.31 GiB 按 TP 均分的
容量下界，尚未包含复制权重、CUDA Graph、视觉 encoder、中间激活、KV/压缩状态和通信 workspace。

| 卡型/拓扑 | 容量判断 | 当前建议 |
| --- | --- | --- |
| 4× B200/B300/GB200/GB300 | 原始权重约 39.1 GiB/卡；官方参考实现默认 TP4，Blackwell 原生 FP4 路线最匹配 | 最优先的 reference bring-up 候选；SGLang/vLLM Vision 仍需等专用支持 |
| 8× H20 141GB（H20-3e） | 原始权重约 19.5 GiB/卡，容量非常充足；Hopper 可参考文本 V4 的 FP4/FP8 路线 | 本次资源池最现实的实验候选；框架支持落地后先 TP8，再探测 TP4，不能写成官方已验证 |
| 4× H20 141GB | 原始权重约 39.1 GiB/卡，容量充足 | 可作为第二阶段低卡数实验；不要作为首个 Day-0 排障拓扑 |
| 8× H20 96GB / H100 80GB | 容量足够；H100 在文本 V4 Cookbook 中使用 TP8 | 可以实验，首轮 TP8；H20 96GB 仍非官方已验证型号 |
| 4× H200 141GB | 文本 V4 官方 Cookbook 有 H200 TP4 路线，容量足够 | 框架视觉实现出现后的高优先级验证拓扑 |
| 2× 141GB/180GB/192GB 卡 | 权重均摊约 78.2 GiB/卡，但 runtime 余量和通信/量化实现风险变大 | 只做后续容量探针，不用于首轮验收 |
| 1× B300/GB300 288GB | 静态容量可能足够 | 不是官方参考拓扑；先验证 TP4/TP8 后再尝试 |
| 8× RTX 5880 / Pro 5000 / L20 类卡 | 即使聚合容量可能够，当前 DSV4/FP4 kernel 和视觉实现没有对应验证 | 不纳入首轮 |

本次资源池同时有 141GB H20、96GB H20 和 Pro 5000。首轮优先选择 141GB H20；是否空闲
要在真正启动前按 Pod GPU request 再核对，节点 `allocatable=8` 不代表 8 张卡当前未被占用。

## Gate 0：CFS 完整性，不申请 GPU

模型同步结束后先运行：

```bash
MODEL_PATH=/models/DeepSeek-V4-Flash-Vision-Exp/v1 \
python3 examples/deepseek-v4-flash-vision-exp/preflight.py
```

实际 CFS 路径尚未确认时不要写死到 Deployment。预检必须通过：

1. 模型 Revision、架构、Context、量化格式符合上表；
2. Index 引用恰好 48 个分片，全部存在、非空，且实际总字节数与同步完成后的记录一致；
3. `vision.*`、`aligner.*` 和四个 image marker 完整；
4. `encoding/`、`inference/`、Tokenizer 和两张官方示例图存在；
5. 不存在 `.tmp`、`.part`、`.incomplete` 等同步残留。

不对 156 GiB 权重做全量 SHA256。固定 Revision、Index 引用清单、分片数与文件大小即可作为
首轮同步 Gate。

### CFS 与 NVMe 分工

CFS 只作为模型分发源。真正选定 H20-3e 节点后，把原始 HF checkpoint 预热到该节点的
NVMe `<NVME_MODEL_ROOT>/DeepSeek-V4-Flash-Vision-Exp/v1`，推理容器只读挂载成
`/models-nvme/DeepSeek-V4-Flash-Vision-Exp/v1`。当前运行时尚未支持，不需要先铺满 24 台；
只在选中的实验节点落一份即可。

官方 reference runtime 产生的 TP4 转换权重放到另一个 NVMe 目录，例如
`<NVME_MODEL_ROOT>/DeepSeek-V4-Flash-Vision-Exp-TP4/v1`，不得覆盖或混入原始 HF
checkpoint。复制/转换前要通过 `findmnt`/`lsblk` 确认目标确实位于 NVMe。

## Gate 1：运行时支持探针

每个候选镜像都要先做零 GPU/最小资源探针，保存镜像 digest、框架 commit 和探针输出：

1. 精确型号是否出现在官方 Recipe 或测试中；
2. `DeepseekV4ForCausalLM` 是否注册为多模态模型，而不是只注册为文本 CausalLM；
3. 是否能实例化 Vision、Aligner 和 image marker，并消费 `vision.*` 权重；
4. OpenAI Chat Completions 是否识别 `image_url` 和交错多图；
5. 是否支持该 checkpoint 的 FP4 expert、FP8 dense、`ue8m0` scale 与 DSV4 sparse attention；
6. 是否有视觉预处理/encoder batching/cache 的显式指标。

任何引擎即使能加载文本权重，只要图片请求被拒绝、图片被忽略，或者视觉权重未加载，都判定
Vision Gate 失败。当前 SGLang/vLLM main 都应记为“尚未通过”，待后续支持 commit 出现后重跑。

## Gate 2：官方 reference runtime bring-up

只有在确实需要 Day-0 验证模型本身、且有合适 GPU 时执行。按照官方仓库流程：

```text
source: CFS 中完整 HF checkpoint
converted checkpoint: 节点 NVMe 独立目录
model parallel: 4
expert dtype: fp4（基线）
input: 官方 carrots/corn 两图交错样例
runtime: torch>=2.10, transformers>5, tilelang==0.1.8
```

转换后的 checkpoint 不写回原模型目录，避免与 HF 权重混淆。先确认目标盘是 NVMe，再执行转换；
记录转换耗时、目标大小和每 Rank 文件。参考实现没有连续批处理、OpenAI API、生产调度和完整
指标，所以只验：可加载、单图、多图、文本基线、内容正确、重复执行稳定。

## Gate 3：SGLang/vLLM 功能正确性

专用支持出现后，两个引擎用完全相同的 OpenAI Chat 请求集，按顺序验证：

1. `/v1/models` 与 served model name；
2. 纯文本结果与同版本 DeepSeek-V4-Flash 文本能力没有明显回退；
3. 单图物体/颜色/计数；
4. OCR、表格、图表、数学图形；
5. 两图顺序与交错 `text → image → text → image → text`；
6. 多轮对话中历史图片引用；
7. 视觉理解结合 reasoning/tool call；
8. 坏图片、超大图片、图片数量越界和不可达 URL 返回可解释 4xx，不导致 Rank 退出；
9. 图片内容确实影响输出：同一问题替换图片后答案必须随之变化，防止“接口成功但图片被忽略”。

HTTP 200 和非空文本不是多模态正确性证明。

## 多模态标准压测方法

业界没有一个覆盖所有 VLM 的单一标准，但可以用一套可复现的四层方法。

### 1. 质量评测与系统性能分开

- 质量评测固定 `temperature=0`（若模型只建议 temperature 1.0，则固定官方建议并记录 seed），
  使用数据集原始评分器，报告 accuracy/ANLS/grounding success 等任务指标；
- 性能压测固定请求和输出长度，不用模型答对率代替性能，也不用随机噪声图评价模型质量；
- Agent 端到端成功率单列，不能与单次 VQA accuracy 合并。

### 2. 每个请求记录完整 workload vector

至少记录：图片数、宽高、格式、编码后字节数、视觉 token 数、文本 input token、output token、
图片传输方式（base64/本地/URL）、cache hit/miss、并发和到达率。仅写“720p、并发 8”无法复现。

DeepSeek 官方预处理最多把每张图展开为 384 个 image token，但仍应从运行时日志/响应实际采集，
不能只靠分辨率估算。

### 3. 冷、热路径分开

- Cold image：每次使用不同图片或不同 media UUID，测下载/解码/预处理/ViT/首 token 全链路；
- Warm image：复用相同图片和合法 cache key，测 encoder cache 收益；
- Base64 与内网对象 URL 分开，避免把对象存储或 DNS 延迟归因于模型；
- 第一次 CUDA 编译/Graph capture 只计启动成本，不混入稳态请求。

### 4. 主对比使用同一客户端

对 SGLang 和 vLLM 的正式 A/B，统一使用同一版本的 `vllm bench serve`：

```bash
vllm bench serve \
  --backend openai-chat \
  --endpoint /v1/chat/completions \
  --dataset-name custom_image \
  --dataset-path /datasets/aik8s/deepseek-v4-vision/perf.jsonl \
  --custom-ensure-client-side-data \
  --num-prompts 200 \
  --max-concurrency 8 \
  --save-result --save-detailed
```

该客户端可以指向任一 OpenAI-compatible endpoint。SGLang 自带的 `bench_serving` 也支持
`image` 合成数据集和 MMMU，适合做 SGLang 内部诊断，但它的数字不能直接拼进主 A/B 表。

### 性能矩阵

| Case | 图片 | 文本/输出 | 并发 | 目的 |
| --- | --- | --- | --- | --- |
| T0 | 0 | 128/128 | 1、8、32 | 文本基线与视觉版回退 |
| V1 | 1×360p | 128/128 | 1、4、8、16 | 小图低延迟 |
| V2 | 1×720p | 128/128 | 1、4、8、16 | 主吞吐曲线 |
| V3 | 1×1080p | 128/128 | 1、4、8 | 高分辨率预处理 |
| V4 | 2×720p 交错 | 256/128 | 1、4、8 | 多图排序与 encoder 压力 |
| V5 | 4×720p | 512/128 | 1、4 | 多图上限探针 |
| V6 | 1×720p | 4K/256 | 1、4、8 | 图片 + 长文本 prefill |
| V7 | 1×720p | 128/1K | 1、4 | 图片 + 长 decode |

每个有效 Case 执行一次 Warmup 和三次记录，主表取中位数并报告离散度。并发上探采用
1→2→4→8→16→32，成功率低于 99.5%、出现 OOM/NaN/Rank exit 或 P99 无界增长时停止。

### 必报指标

- 成功率、请求吞吐、image/s、input/output token/s、vision token/s；
- P50/P95/P99 TTFT、TPOT、ITL、E2E；
- 客户端图片读取/base64 时间、服务端 decode/preprocess、ViT encoder、queue/prefill/decode；
- GPU 利用率、显存、功耗，CPU、内存、网络吞吐；
- 冷/热 cache 命中率和相同 Case 的质量得分。

## 建议准备的数据集

不需要为了性能压测下载大数据集。P0/P1 使用官方两张样例图和确定性合成图片即可；质量评测
再按优先级准备：

| 优先级 | 数据集 | 用途 | 规模/注意 |
| --- | --- | --- | --- |
| P0 | 模型仓库 `inference/examples/images` | 单图/双图 Smoke | 已随模型同步，无额外下载 |
| P0 | 合成 blank/noise 图片 | 分辨率、图片数、冷/热 cache 性能 | 客户端生成，无额外下载 |
| P1 | `xai-org/RealworldQA` | 真实世界感知、计数、空间关系 | 765 条，约 678 MB |
| P1 | `AI4Math/MathVista` | 图形/图表/数学视觉推理 | 约 1.75 GB，先跑 `testmini` |
| P1 | `MMMU/MMMU` | 多学科、图表、示意图、多图推理 | 先准备 validation；保留具体 dataset revision |
| P2 | `likaixin/ScreenSpot-Pro` | GUI grounding / 视觉 Agent | 1,581 张高分辨率截图，约 3.38 GB |
| P2 | `vis-nlp/ChartQA` | 图表 QA | 使用官方 test 标注与 scorer |
| P2 | `Yuliang-Liu/MultimodalOCR` / OCRBench | OCR、文档、表格、手写/场景文字 | 下载前核对各子数据集许可 |
| P3 | VisualWebArena | 浏览器视觉 Agent 端到端任务 | 不是单纯图片包，需要完整站点/浏览器环境，首轮不阻塞 |

具体下载命令、缓存目录和离线搬运方式见
`examples/deepseek-v4-flash-vision-exp/datasets/README.md`。质量评测优先用 `lmms-eval`
的 `async_openai` 接口或数据集官方 scorer；固定 harness commit、数据集 revision、prompt 模板、
解码参数和答案抽取规则。

## 镜像策略

不把 `lmsysorg/sglang:latest` 或 `vllm/vllm-openai:latest` 贴上 Vision-Exp 可用标签。
SGLang 专用预览镜像已按下面流程固定和同步：

1. 固定 SGLang commit `914197146f8a3407960e5c7037d0463e03c37be9`；
2. 在可访问公网 Registry 的中转机拉取专用预览镜像并固定 `linux/amd64`；
3. staging manifest 为 `sha256:5996a154550d5a39955fd7048eb44d5f655f08063af8ac3775845fd4ac404a69`；
4. 不可变 tag 为 `ai/llm-serving-sglang:dsv4-flash-vision-91419714-cu130-amd64-20260901`；
5. staging、production 与目标推理集群的 Registry 侧复制均成功；
6. 下一步先做零 GPU 架构/CLI 探针，再申请 H20-3e；
7. 正式结果记录目标实际 digest，不依赖会漂移的预览 tag。

官方 reference runtime 如需镜像，单独命名，固定模型仓库 Revision、PyTorch、Transformers、
TileLang 和 CUDA/Driver 组合，不复用 SGLang/vLLM 的结果名称。

## 停止与清理条件

- 权重还在同步、分片不完整或出现临时文件：不申请 GPU；
- 运行时只注册文本模型、忽略视觉权重或图片：停止，不做吞吐结论；
- 图片答案不随图片变化、顺序错乱、NaN/重复 token：停止性能测试；
- 任一 Rank OOM/退出、NCCL 错误或持续超时：保存日志后停止该拓扑；
- 每个框架测试完成后保存结果、日志、镜像 digest 和启动参数，立即缩容到 0。

## 官方资料

- [DeepSeek-V4-Flash-Vision-Exp 模型卡](https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash-Vision-Exp)
- [SGLang DeepSeek-V4 Cookbook](https://github.com/sgl-project/sglang/blob/main/docs/cookbook/autoregressive/DeepSeek/DeepSeek-V4.mdx)
- [vLLM DeepSeek-V4-Flash Recipe](https://github.com/vllm-project/recipes/blob/main/models/deepseek-ai/DeepSeek-V4-Flash.yaml)
- [vLLM 多模态 Benchmark CLI](https://github.com/vllm-project/vllm/blob/main/docs/benchmarking/cli.md)
- [SGLang Bench Serving Guide](https://github.com/sgl-project/sglang/blob/main/docs/developer_guide/bench_serving.md)
- [LMMs-Eval](https://github.com/EvolvingLMMs-Lab/lmms-eval)
