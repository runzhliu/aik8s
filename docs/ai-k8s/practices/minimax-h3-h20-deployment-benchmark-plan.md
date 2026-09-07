---
title: MiniMax H3：H20 音视频生成部署、测试与压测计划
description: SGLang Diffusion 与 vLLM-Omni 的离线镜像、NVMe 模型加载、功能验收和公平音视频生成基线
status: planned
---

# MiniMax H3：H20 音视频生成部署、测试与压测计划

本文保留原始测试方案；已完成结果、配置调整与适用边界见[实测文档](minimax-h3-h20-benchmark.md)。MiniMax H3 需要联合执行条件编码、音视频扩散与
音视频解码；本文以 SGLang Diffusion 和 vLLM-Omni 为两套候选运行时。

## 1. 固定测试范围

首轮使用 `MiniMaxAI/MiniMax-H3` 官方完整权重，保留其原始 BF16/FP32 混合精度；
先测 FL2VA 分区的文本生成及首尾帧控制，再切换 Ref2VA 分区测试参考图片、视频和音频。
两引擎按相同顺序复用同一节点，避免并行争抢资源。

已有 [ComfyUI 部署记录](comfyui-minimax-h3-gpu.md) 只完成页面和模型发现，不作为 H3
视频生成通过的证据。其 pruned INT4/INT8 权重不进入完整官方模型性能表。

MiniMax 官方模型卡提供完整组件、参考请求和输出。下载应包含两个 DiT 分区、共享编码器、
Tokenizer/Processor、视频及音频 VAE、配置和所需自定义代码。先核对实际仓库 Revision
及目录格式，再配置本地路径；不同导出布局不能仅靠软链接假装兼容。
来源：[官方模型卡](https://huggingface.co/MiniMaxAI/MiniMax-H3)。

## 2. 硬件与加载

| 资源 | 首轮候选 | 验证边界 |
| --- | --- | --- |
| H20 141GB | 单节点 4 卡，单 DiT，Ulysses4 | 参照 Hopper 方案；H20 仍须完整生成确认 |
| H20 96GB | 单节点 4 卡，优先 TP2 × Ulysses2 | 容量候选；不能只把四卡显存相加判断能否加载 |
| RTX PRO 5000 | 先确认具体显存，再考虑 4 卡 TP2 × Ulysses2 | 官方 72GiB 配方不能直接套给其他显存版本 |
| CPU/内存 | 首轮请求 32 CPU、192GiB，内存 limit 384GiB | 加载峰值和 Offload 另计，按节点余量调整 |
| 本地 NVMe | 以文件清单总字节数加余量为准；核对的源目录约 498.6GB，至少预留 550GB | 模型与输出分目录；共享存储只读 |

SGLang 的 H200 Ulysses4 和 H100 TP2×Ulysses2 是已公开的起点；本实验沿用拓扑思路，
不移植其性能数字。vLLM 的 Blackwell 专用 attention 优化不直接用于 H20。
来源：[SGLang H3 Cookbook](https://docs.sglang.io/cookbook/diffusion/MiniMax/MiniMax-H3)、
[vLLM H3 Recipe](https://recipes.vllm.ai/MiniMaxAI/MiniMax-H3)。

路径约定：共享源由运维填写；宿主机示例 `/srv/models/MiniMax-H3/v1`（须替换为实际 NVMe 挂载路径），容器
`/models-nvme/MiniMaxAI/MiniMax-H3`。宿主机必须用 `findmnt -T` 和 `lsblk` 确认底层 NVMe。
复制完成时比较源/目标逐文件名称与大小、分片索引引用，并记录 `REVISION`；不全量读权重
计算哈希。全部检查通过再写 `.aik8s-complete`。启动脚本拒绝缺少标记或 Revision 的目录。

只为选中的 GPU 节点预热。模型还未完整下载时不启动正式 GPU 服务。共享存储此前有
ENOSPC 现象，下载完成状态必须以文件完整性核对为准，不能只看 `df` 的汇总剩余容量。

## 3. 镜像与 Kubernetes 准备

固定基础镜像 Digest、框架源码 Commit、Python/PyTorch/CUDA/FFmpeg 版本，依赖在
构建期安装。源码覆盖方式必须运行 import、CLI、H3 模块和依赖一致性检查，不能以 Docker
build 成功替代运行时验收。镜像交付分为：上游解析、构建、离线 CPU 探针、staging、生产、
目标 Registry、GPU 完整生成，各阶段单独记录。

SGLang 使用 `sglang[diffusion]`，vLLM 使用 `vllm-omni` 与其兼容的核心 vLLM。
vLLM 官方 Recipe 指出 H3 专用基础镜像落后于模块化服务源码，因此准备固定源码的派生镜像。
准确状态见仓库 `examples/minimax-h3-h20/images/README.md`。

部署要求：每个引擎一个 `Recreate` Deployment，初始 replicas=0；四卡 requests=limits；
共享模型挂载只读，独立输出目录，`/dev/shm` 使用有上限的内存卷；Service 指向 API 端口。
创建前固定节点、NVMe 路径、镜像 Digest 与命名空间。Ingress 允许适量媒体上传并配置
长请求超时，URL 参考媒体只能指向预设的测试素材服务。无需为了单节点实验开放跨节点 RDMA。

启动探针预留 60 分钟，启动期间不使用短 liveness 强制重启。Ready 后必须生成并解码
一个 50 步短视频；仅 `/health` 为 200 不算业务验收。

## 4. 功能与样本清单

| Gate | 输入/动作 | 验收 |
| --- | --- | --- |
| T2VA | 中英文固定 Prompt，运动、物体、环境声、镜头约束 | 有效视频和音轨，场景与声音符合指令 |
| FL2VA | 首帧、尾帧、首尾两帧各一个用例 | 对应端点与参考一致、过渡连贯 |
| Ref2VA | 图片、视频、图片+音频、混合引用 | 主体/风格/声音参考有效，不要求逐像素保持源视频 |
| API | 排队、轮询、失败状态、非法素材、超限参数 | 正常终态、明确错误，失败后下一个请求可恢复 |
| 媒体 | MP4 实际解码，检测视频流/音轨/时长/帧率 | 默认目标 24fps、AAC 双声道 32kHz，无损坏/NaN 产物 |
| UI | 输入、排队、视频播放、声音和下载 | Light 模式截图，记录请求 ID 与输出文件 |

准备自有或可公开使用的素材：2 张同一物体首尾帧、3 张不同主体参考图、2 个 5 秒参考视频
（有声/无声）、1 个 5 秒 WAV。素材先做格式、时长、尺寸检查，以清单保存来源与文件摘要。
无需先下载大型评测数据集；机器评分后续若需要 VBench/CLIP/ASR，另建依赖和权重清单，
只在内网运行。素材、请求和输出不得包含内部账号或生产信息。

OpenWebUI 接入先检查是否支持本部署的 Video API。如果不能原生提交/播放，使用独立浅色
视频测试页面保留完整证据；不得把文本模型连接成功写成音视频 UI 已通过。

## 5. 公平性能矩阵

同一节点、GPU 拓扑、模型 Revision、分区、原始精度、Prompt、素材、种子、目标尺寸、
输出时长和采样步数。首轮 50 步，video flow shift=12、audio flow shift=3；CFG-distilled
模型不增加第二个 CFG 分支。完整权重、Turbo、FastH3、量化、缓存优化分别建表。

| 阶段 | 请求 | 并发 | 正式样本 |
| --- | --- | --- | --- |
| 基础 | T2VA 768p，5 秒，50 步 | 1 | 3 次 |
| 时长 | T2VA 768p，10/15 秒 | 1 | 各 3 次 |
| 排队 | T2VA 768p，5 秒 | 2，稳定后 4 | 每组至少 3×并发 |
| 条件生成 | FL2VA、Ref2VA，768p，5 秒 | 1 | 每种素材组合 3 次 |
| 容量探索 | 2 卡/4 卡、TP/Ulysses、Offload | 1 | 独立实验，不混入同配置主表 |

每种分辨率/时长先预热一次，并另存冷启动结果。先串行对齐输出尺寸、实际帧数和采样 NFE；
客户端请求中的 seconds 并不保证两框架帧数公式完全相同，差异必须在主对比前解决。

共同指标：客户端端到端秒数、服务端编码/DiT/VAE/封装耗时、排队时间、成功率、峰值 GPU
显存、功耗、视频/小时、生成视频秒数/墙钟秒数。RTF 定义为 E2E/实际视频秒数，越低越好。
客户端 E2E 包括输出下载，不包含本地 ffmpeg 解码校验；轮询开销、网络路径和同步/异步
API 差异要单独记录。仅 3 个样本报告原值、中位数和范围，不用它宣称可靠 P99。

压测客户端不使用 `vllm bench serve` 的随机文本 Token 模式。两边使用同一驱动程序的
协议适配器；上传/下载、超时、排队、预热和成功标准一致。质量判断包括主体一致性、运动
连续性、音画同步、首尾帧保持和 Prompt 遵循；同一个 seed 不意味着两框架输出逐像素相同。

## 6. 停止、耗时与交付

先用第一个 50 步样本测实际耗时，再估剩余时间：服务初始化 + 各 Case 预热 + 排队批次
× 实测单批耗时 + 素材校验/截图。H20 首轮可预留每引擎半天资源窗口，但在首样本完成前
不给固定完成时刻。失败、超时、OOM、音轨缺失、输出不可解码时停止扩大并发并保存证据。

测试与压测资源统一部署在 `aik8s-ms`。输出使用独立持久化 hostPath，生成的音视频不删除；
每批复制回本地，核对文件大小及 SHA-256，保留失败或不符合媒体约定的产物以便排查。

每个引擎完成后导出参数、版本、请求 JSON、媒体信息、日志、监控、原始 MP4 和截图，再
缩容到 0，确认 GPU 释放后切换下一个引擎。完整 2K 商用 API 工作流另设实验，不把调用
外部 H3-Context-IR/Regenerate 服务的效果归为纯本地部署结果。

交付顺序：镜像 CPU 验证 → 双 Registry 同步 → 模型/NVMe 预检 → 单节点完整生成 →
功能与质量 → 固定性能矩阵 → UI 证据 → 缩容 → 去标识化公开实测文档。
