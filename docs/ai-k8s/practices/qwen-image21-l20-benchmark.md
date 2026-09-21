---
title: Qwen-Image-2.1：单卡 L20 的 SGLang 与 vLLM-Omni 实测
description: 在 Kubernetes 中用单张 NVIDIA L20 部署 Qwen-Image-2.1，验证文字、透明 PNG、SGLang 与 vLLM-Omni 的吞吐、延迟、显存和批量生成工作台
last_reviewed: 2026-09-22
---

# Qwen-Image-2.1：单卡 L20 的 SGLang 与 vLLM-Omni 实测

Qwen-Image-2.1 是 Qwen 家族的统一图像生成与编辑模型。官方模型卡给出的视觉生成组件规模为 **7B 参数、32 层 Single-Stream DiT**，同时支持文本生成图片、图片编辑和原生 RGBA 透明图。它还支持最多 10 张参考图、通过圈选或蒙版完成局部编辑，并加强了文字排版、人物与商品身份保持、纹理和光照表现。

这类模型与文本大模型的容量判断很不一样。参数规模只有 7B，并不代表十几 GB 显存就能稳定提供在线服务：文本编码器、DiT、VAE、Attention 工作区、CUDA Graph 和输出分辨率都会占用显存。本文把完整 BF16 模型部署在单张 **NVIDIA L20 48 GB** 上，分别验证 SGLang Diffusion 与 vLLM-Omni，再用同一组 Prompt、Seed、分辨率和采样步数测量端到端表现。

本轮只验证 **Text-to-Image**。图片编辑、10 张参考图、官方推荐的 2048×2048 及更大画幅没有进入性能矩阵，不能从本文结果推断这些能力的速度和显存需求。模型能力与示例参数见 [Qwen-Image-2.1 官方模型卡](https://huggingface.co/Qwen/Qwen-Image-2.1)。

## 1. 实验配置与口径

两个引擎串行占用一张同型号 GPU，读取同一份只读模型文件。每个性能档先执行 2 次预热，再正式生成 10 张图片；失败请求保留在原分母，不补跑覆盖成绩。每次请求的原始 JSON、HTTP 响应、PNG、延迟和 SHA-256 都保存到 Pod 外，再回传到本地核对。

| 项目 | 本次配置 |
| --- | --- |
| 模型 | Qwen/Qwen-Image-2.1，BF16 |
| GPU | 单张 NVIDIA L20，48 GB 显存 |
| 服务引擎 | SGLang Diffusion；vLLM-Omni Preview |
| 正式分辨率 | 1024×1024 |
| 推理步数 | 40 |
| 并发 | 客户端 C1 / C2 / C4 |
| 每档样本 | 2 次预热 + 10 个正式请求 |
| 输出 | Base64 PNG；普通 RGB 与 RGBA 都做解码校验 |
| Prompt | 街景、中文排版、英文排版、产品摄影、透明剪纸，共 5 类 |
| 统计 | 成功图片/分钟、P50/P95 端到端延迟、整轮墙钟时间 |

SGLang 使用单请求动态批处理上限；vLLM-Omni 使用 `--max-num-seqs 1`。因此 C2、C4 描述的是**多个客户端请求在单活动请求服务前排队**的表现，不是服务端融合批处理结果。这个约束是读懂后续数据的关键。

## 2. 部署方式

SGLang Diffusion 提供 `sglang generate`、`sglang serve` 和 OpenAI-compatible API。本次使用速度模式、FlashAttention 后端和 Metrics：

```bash
sglang serve \
  --model-path /models/Qwen-Image-2.1 \
  --model-id Qwen-Image-2.1 \
  --num-gpus 1 \
  --performance-mode speed \
  --attention-backend fa \
  --host 0.0.0.0 \
  --port 30000 \
  --enable-metrics
```

SGLang 运行时来自 2026-09-18 的 Nightly 构建，并叠加了 Qwen-Image-2.1 支持 Revision。服务端日志显示模型组件按文本编码器、Transformer、VAE、Processor、Scheduler 的顺序加载，整个 Pipeline 模块加载约 25 秒。

vLLM-Omni 的模型支持来自 Preview PR 7759。运行时为 vLLM `0.29.0b1`、vLLM-Omni `0.16.0.dev0+pr7759`、PyTorch `2.13.0+cu129`、Diffusers `0.40.0` 和 Transformers `5.14.1`：

```bash
vllm serve /models/Qwen-Image-2.1 \
  --omni \
  --host 0.0.0.0 \
  --port 30000 \
  --max-num-seqs 1
```

vLLM-Omni 日志记录的模型加载耗时为 28.91 秒，模型加载占用 30.22 GiB，加载后进程级 GPU 显存为 30.58 GiB。启动时还出现了 vLLM 与 vLLM-Omni 主次版本不一致的警告，因此本文把它称为 Preview 结果，不能外推为未来稳定版本的最终性能。

第一次 vLLM-Omni 部署在 GPU 调度前失败：镜像验收脚本把 `git` 当成必要依赖，但最终运行镜像没有安装 Git。第二次改为读取已安装 Python Package 的版本号和模块路径，随后才允许 GPU Pod 入场。这个修复没有改变模型参数或性能口径，也没有消耗一次无效 GPU 加载。

## 3. 功能验证：文字和透明图是否真的可用

性能数字只有在图片链路正确时才有意义。本轮使用下面 5 类 Prompt，并固定初始 Seed 42～46；后续第二轮使用 47～51。

| 用例 | Prompt 摘要 | 验收重点 |
| --- | --- | --- |
| 写实街景 | 雨后的上海街角与红色复古自行车 | 主体、光照、反射和细节 |
| 中文海报 | 中央只显示“让想象发生” | 字形、错别字和版式 |
| 英文海报 | `CREATE WITHOUT LIMITS` | 字母完整性与居中排版 |
| 产品摄影 | 半透明红色玻璃茶壶 | 材质、焦散和背景控制 |
| 透明素材 | 红色剪纸龙、无背景 | PNG Alpha 通道与主体边缘 |

先看两套引擎的实际生成结果。画廊使用正式压测中的原始 PNG，透明素材在棋盘格背景上展示 Alpha 通道。

![SGLang 实际生成样例](../../assets/practices/qwen-image21-l20/generated-samples-sglang.png)

![vLLM-Omni 实际生成样例](../../assets/practices/qwen-image21-l20/generated-samples-vllm.png)

![同一组 Prompt 与 Seed 的实际输出](../../assets/practices/qwen-image21-l20/sample-comparison.png)

两套引擎都生成了可解码的 1024×1024 PNG。中文和英文指定文字在这组样例中完整可读；透明素材输出为 RGBA，Alpha 极值为 0～255，说明背景确实包含透明像素。相同 Seed 在两个引擎之间不保证逐像素一致，因此样例用于验证功能和视觉可用性，不作为数值一致性测试。

## 4. SGLang 与 vLLM-Omni 的实测数据

| 引擎 | 客户端并发 | 成功/总数 | 成功吞吐 | P50 E2E | P95 E2E | 整轮墙钟时间 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| SGLang | 1 | 10/10 | 2.326 img/min | 25.70 s | 26.20 s | 257.99 s |
| SGLang | 2 | 10/10 | 2.331 img/min | 51.48 s | 51.59 s | 257.39 s |
| SGLang | 4 | 10/10 | 2.329 img/min | 102.99 s | 103.13 s | 257.60 s |
| vLLM-Omni Preview | 1 | 10/10 | 2.016 img/min | 29.25 s | 30.86 s | 297.64 s |
| vLLM-Omni Preview | 2 | 10/10 | 2.054 img/min | 58.34 s | 58.55 s | 292.11 s |
| vLLM-Omni Preview | 4 | 10/10 | 2.055 img/min | 116.79 s | 116.92 s | 292.03 s |

![吞吐与 P95 端到端延迟](../../assets/practices/qwen-image21-l20/engine-comparison.png)

在这组固定配置下，SGLang C1 吞吐比 vLLM-Omni Preview 高 **15.4%**，C2 和 C4 分别高 **13.5%** 和 **13.4%**。差距只适用于当前 Revision、1024×1024、40 步和单活动请求配置，不能写成两个项目的通用排名。

更值得关注的是并发曲线。SGLang 从 C1 到 C4 一直约为 2.33 img/min，vLLM-Omni 也只从 2.02 变化到 2.05 img/min；同时 P95 延迟大致随并发倍增。这说明 GPU 一直在串行完成单张图片，更多客户端请求只是在队列里等待。客户端压力工具确实发送了并发请求，但服务端没有把它们融合成同一个计算批次。

vLLM-Omni 官方文档提供两条后续优化路线：把 `--max-num-seqs` 调到大于 1 做请求级批处理，或者启用仍处于实验阶段的 `--step-execution`，让兼容请求共享 Denoise Step。官方也建议先用 `max_num_seqs=1` 验证正确性，再逐步放大容量。下一轮如果测试批处理，必须同时核对显存、失败率、图片质量和 P95，不能只看总吞吐。

脱敏后的 [逐档 CSV](../../assets/practices/qwen-image21-l20/benchmark-results.csv) 与 [汇总 JSON](../../assets/practices/qwen-image21-l20/benchmark-summary.json) 保留了正式样本数、墙钟时间、延迟分位数和源 Summary 的 SHA-256。

## 5. Grafana：单张 L20 是否已经吃满

SGLang 场次的 GPU 利用率峰值为 100%，显存峰值 32.8 GB，功耗峰值 351 W，温度峰值 79℃。负载阶段 GPU 利用率保持在高位，说明单活动请求已经能持续占用计算单元。

![SGLang 单卡 L20 实测看板](../../assets/practices/qwen-image21-l20/grafana-sglang-overview-light.png)

vLLM-Omni 场次同样达到 100% GPU 利用率，显存峰值 40.4 GB、功耗峰值 355 W、温度峰值 78℃。它比 SGLang 多占约 7.6 GB 显存，即 **23.2%**；这个差值包含当前 Preview Runtime、CUDA Graph 和工作区行为，不能只归因于模型权重。

![vLLM-Omni Preview 单卡 L20 实测看板](../../assets/practices/qwen-image21-l20/grafana-vllm-overview-light.png)

| 资源峰值 | SGLang | vLLM-Omni Preview |
| --- | ---: | ---: |
| GPU 利用率 | 100% | 100% |
| 显存占用 | 32.8 GB | 40.4 GB |
| 功耗 | 351 W | 355 W |
| 温度 | 79℃ | 78℃ |

这些图使用完整压测绝对时间窗口，包含加载、预热、正式请求和结束阶段。峰值适合做容量保护，不能替代逐请求能效统计；Prometheus 的离散采样也可能漏掉毫秒级尖峰。

## 6. 从 API 到批量图像工作台

为了让功能验收不局限于固定 Prompt，本轮保留了一套 Gradio 图像工作台。它支持单张生成，也支持一次提交 1～200 张，客户端并行度可设为 1～10；Seed 可以完全随机，也可以从指定值递增。页面显示进度、成功数、失败数、吞吐与预计剩余时间，并允许停止尚未提交的新任务。

![批量随机生成工作台](../../assets/practices/qwen-image21-l20/batch-workbench.png)

工作台与模型服务分开部署，CPU Pod 负责表单、队列和结果索引，GPU Pod 只处理图像 API。每张图片都保存请求 JSON、每次尝试的原始响应、结果 JSON、PNG 和 SHA-256。目录先写到 Pod 外的持久位置，再异步回传到使用者机器，Pod 重建不会删除已经生成的图片。

使用端可以通过本地端口转发访问，不必给工作台开放公网入口：

```bash
kubectl -n image-serving port-forward svc/qwen-image-workbench 7861:7860
```

浏览器打开 `http://127.0.0.1:7861/` 即可。这里的“并行度”表示客户端同时在途请求数。按 SGLang 当前约 2.33 img/min 的实测吞吐估算，100 张 1024×1024、40 步图片约需 43 分钟，200 张约需 86 分钟；在服务端仍限制单活动请求时，把并行度从 1 调到 10 不会得到十倍速度。

## 7. API 复现

两个引擎都通过 OpenAI-compatible 图片生成接口提供服务。下面的请求可以同时验证中文排版与 Base64 PNG 返回：

```bash
curl -sS http://127.0.0.1:30000/v1/images/generations \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "Qwen-Image-2.1",
    "prompt": "极简科技海报，深蓝背景，中央只显示清晰准确的中文『让想象发生』",
    "size": "1024x1024",
    "num_inference_steps": 40,
    "seed": 43,
    "response_format": "b64_json",
    "output_format": "png"
  }'
```

正式验收不能只检查 HTTP 200。客户端还应验证 JSON Schema、Base64 解码、PNG 魔数、图片尺寸、RGBA 通道、文件大小和 SHA-256；失败响应原样留存，方便区分网关错误、引擎错误和输出解析错误。

## 8. 硬件与生产部署建议

L20 48 GB 是这次完整 BF16 单卡部署的可用起点。SGLang 峰值 32.8 GB，仍有约 15 GB 的卡面余量；vLLM-Omni Preview 峰值 40.4 GB，余量收窄到约 7.6 GB。生产环境还要给驱动差异、CUDA Graph、较大分辨率、批处理和偶发碎片留空间，因此不能把峰值直接当作显存 Request 上限。

A30 通常只有 24 GB 显存，本轮按用户要求没有执行 A30 测试。根据两套 L20 实测峰值，完整 BF16 运行时无法直接落入 24 GB；若必须使用 A30，需要尝试组件 CPU Offload、量化或多卡切分，并接受 PCIe 传输和更长延迟。这个判断是容量推导，不是 A30 实测结论。

面向生产可以按以下顺序推进：

1. 先用单活动请求完成固定 Prompt、文字、透明 PNG 和失败响应验收，再改批处理参数。
2. 把在线工作台、任务队列和 GPU 引擎分开，限制单用户批量规模和全局在途请求，避免 200 张任务占住整个服务。
3. 逐级测试 1024、1536、2048 和官方推荐长宽比；每一级重新记录显存峰值、单图延迟与 OOM 边界。
4. vLLM-Omni 开启 `max_num_seqs>1` 或 Step Execution 时，用同尺寸、同 CFG、同 LoRA 状态的请求组成批次，并把图片质量验收放在吞吐门槛之前。
5. 生成结果保存到对象存储、PVC 或受控 HostPath，数据库只记录任务和对象索引；为原始响应、PNG 和元数据设置不同的保留周期。
6. 看板同时展示队列深度、成功/失败率、端到端延迟、图片吞吐、GPU 利用率、显存和功耗。仅有 GPU 100% 无法判断用户是否等得过久。
7. 固定模型 Revision、镜像 Digest、Runtime 版本和生成参数。升级 SGLang、vLLM-Omni、Diffusers、Torch 或驱动后，重新跑同一组功能门槛和代表性性能档。

## 参考资料

- [Qwen/Qwen-Image-2.1 模型卡](https://huggingface.co/Qwen/Qwen-Image-2.1)
- [SGLang Diffusion 官方文档](https://github.com/sgl-project/sglang/blob/main/docs/docs/sglang-diffusion/index.mdx)
- [vLLM-Omni Diffusion Execution Modes](https://docs.vllm.ai/projects/vllm-omni/en/latest/user_guide/diffusion/execution_modes/)
- [vLLM-Omni Serve CLI](https://docs.vllm.ai/projects/vllm-omni/en/latest/api/vllm_omni/entrypoints/cli/serve/)
