---
title: GLM-5.3 首日测试计划：8×H20 上的 SGLang 与 vLLM
date: 2026-08-30
authors:
  - runzhliu
categories:
  - 推理
  - 实战
description: 面向 GLM-5.3 原生 FP8、DSA、MTP 和 1M 上下文能力，制定单节点 8×141GB H20 上可复现的 SGLang/vLLM 部署与压测计划。
---

# GLM-5.3 首日测试计划：8×H20 上的 SGLang 与 vLLM

本文是测试计划，不是性能结论。只有权重、镜像、硬件、功能正确性和性能测试全部留下
可复现证据后，才会补充“已验证”结论。

GLM-5.3 是约 743B 总参数、39B 激活参数的 MoE 文本模型，使用 DSA、256 个路由专家
（每 Token 激活 8 个）、一层原生 MTP，并声明 1,048,576 Token 上下文。默认
`zai-org/GLM-5.3` 是原生 FP8 Checkpoint；BF16 权重位于独立仓库。

## 官方支持边界

| 路线 | 官方资料当前给出的边界 | 本轮定位 |
| --- | --- | --- |
| vLLM 0.28.0+ | Recipe 明确列出单节点 8×H20/H200 141GB 运行 FP8；完整 1M Context 指向 8×B200 | H20 主验证路线 |
| SGLang `latest`/预发布版 | Cookbook 已支持 GLM-5.3、DSA、MTP、Reasoning、Tool Call、HiCache 和 Context Parallelism；硬件矩阵写明 H200，但没有点名 H20 | Hopper 兼容性实测路线，Ready 前不写成官方 H20 验证 |

这与 Hy4-preview 的 MXFP8/SM100 限制不同。GLM-5.3 的默认 FP8 权重可以从单节点
8×141GB H20 起步，不需要先准备 BF16 双机方案。

## Gate 0：固定运行时镜像

2026-08-30 解析到的 `linux/amd64` 上游 Manifest：

| 引擎 | 上游版本 | `linux/amd64` Manifest |
| --- | --- | --- |
| SGLang | `lmsysorg/sglang:latest` | `sha256:bde16a8447b19e89056b9eea06c72be6c02801dc89d528c9ea90c53368fd74bf` |
| vLLM | `vllm/vllm-openai:v0.28.0` | `sha256:2286e8533ca8b6bc777594bae30524f1426ba46ca21797524e06df6a94b06635` |

`latest` 只用于发现镜像，正式测试固定上面的 amd64 Digest。镜像推入暂存仓库后，还要
检查目标端平台、Manifest、配置 Digest 和关键包版本，不能只以 `docker push` 成功作为
交付完成。

镜像内预检至少确认：

- SGLang 能识别 `glm_moe_dsa`、`glm45`、`glm47` 和 EAGLE MTP 参数；
- vLLM 为 0.28.0+，Transformers 为 5.15.0+；
- 两个镜像均包含 Hopper 上需要的 DeepGEMM/FlashMLA/DSA Kernel；
- 启动 CLI 中计划使用的每个参数都真实存在。

## Gate 1：权重同步完整性

GPU Pod 启动前执行零 GPU 预检：

- 固定模型 Revision，记录 `config.json` 中的架构、量化配置和 Context；
- 解析 `model.safetensors.index.json`，确认 141 个 Safetensors 分片均存在且非空；
- 汇总实际权重字节数，预期约 756GB，不用目录占用量代替 Index 校验；
- 校验 Tokenizer、Chat Template、Generation Config 和 MTP 层文件；
- 排除 `.incomplete`、临时文件、不同 Revision 混放及只同步部分节点的情况；
- 从最终挂载路径读取文件，不能只根据同步任务处于 `Running` 或 `Complete` 判断。

## Gate 2：硬件与最小启动

最低起点是一台独占的 8×141GB H20：

- 8 张 GPU 型号、显存容量和拓扑一致；
- TP8，不跨节点；
- 宿主机内存、`/dev/shm`、模型盘读取带宽和 NCCL P2P 正常；
- 第一次启动从 131,072 Context、32 个最大并发序列和保守显存比例开始；
- Readiness 必须等权重加载、Kernel 初始化和 Warmup 完成，不能以 Pod Running 代替。

首轮采用 Target-only：关闭 MTP、Prefix Cache、HiCache 和 Context Parallelism。SGLang
使用 Hopper 默认 BF16 KV；vLLM 也先使用同等 KV 精度，建立公平基线。

## Gate 3：功能正确性

至少覆盖以下用例：

1. `/v1/models` 和 OpenAI 兼容的流式/非流式 Chat Completion；
2. `reasoning_effort=low/high/max` 与独立的 `reasoning_content`；
3. 多轮对话使用 `clear_thinking=true`，避免把旧推理过程带入下一轮；
4. `glm47` Tool Call 的函数名、JSON 参数和多工具选择；
5. 长输出、停止条件、错误请求和服务端超时；
6. GLM-5.3 是文本模型，图片输入应按预期拒绝，不把多模态作为能力验收。

任一引擎若不能稳定完成 Tool Call 或 Reasoning Parser，本轮性能数据只标记为“引擎
吞吐测试”，不能作为可用服务结论。

## Gate 4：Target-only 性能基线

关闭 MTP，固定 Revision、KV 精度、Context、采样参数和请求集合：

| 场景 | 输入 / 输出 | 并发 | 目的 |
| --- | --- | --- | --- |
| 短对话 | 128 / 64 | 1、4、8、16、32 | 单请求延迟、动态批处理和饱和点 |
| RAG/Agent | 4K / 128、16K / 256 | 4、8 | DSA Prefill 能力 |
| 长输出 | 128 / 1K、128 / 4K | 1、8 | Decode 与 Agent 长任务 |
| 官方参考负载 | 8K / 1K | 32 请求、10 req/s | 对照 vLLM Recipe |
| 长上下文 | 32K、64K、128K、256K / 128 | 1 | TTFT、正确性和 KV 上限 |

每个常规 Case 先 Warmup，再至少记录三轮。保留所有原始结果，不能只摘最快一轮。

## Gate 5：MTP 单变量 A/B

Target-only 稳定后，在同一引擎内只切换 MTP：

- vLLM 使用官方 MTP、5 个 Speculative Tokens；
- SGLang 分别验证 Balanced 的短 Draft 和 Low-Latency 的
  `steps=5, topk=1, draft_tokens=6`；
- 同时观察单并发延迟与高并发吞吐；
- 记录 Draft Tokens、Accept Length、Verify 开销、显存和 P95/P99；
- Acceptance 过低或尾延迟变差时，保留 Target-only 作为推荐配置。

跨引擎比较分成两张表：MTP 关闭的公平基线，以及各自官方推荐 MTP 的最佳实践结果，
不能把二者混成一个排名。

## Gate 6：FP8 KV、Prefix Cache 与长上下文

完成公平基线后，再验证官方优化路线：

- vLLM 开启 FP8 KV Cache；
- SGLang 在 Hopper 上验证原生 FP8 Sparse Prefill/Decode Kernel；
- Prefix Cache 使用相同 4K/32K 前缀，分别记录冷启动和连续热请求；
- Needle 放在上下文的 10%、50%、90%，HTTP 200 但答案错误仍判失败；
- 32K → 64K → 128K → 256K 逐级放大；512K/1M 只作为单并发能力探针。

官方 vLLM Recipe 将 H20/H200 定位为单节点 FP8，而完整 1M Context 明确指向 8×B200。
因此 H20 上不能把模型声明的 1M 窗口直接写成已具备的服务能力。

## Gate 7：SGLang/vLLM 公平比较

两个引擎串行使用同一台节点。Checkpoint Revision、GPU、KV 精度、Context、MTP 状态、
请求顺序、随机种子、采样参数、Warmup 和客户端必须一致。

统一记录：

- Request、Input、Output 与 Total Token Throughput；
- P50/P95/P99 TTFT、TPOT、ITL 和 E2E；
- 错误率、超时、Pod 重启和非有限输出；
- GPU 利用率、显存、功耗、KV Cache 使用率；
- 权重加载、CUDA Graph/JIT/Autotune 和首个请求耗时；
- MTP Acceptance Length 与 Prefix Cache 命中指标。

## 停止条件

- 权重 Index、分片或 Revision 不一致；
- GPU 不是 8×141GB H20，或者测试期间存在其他 GPU 工作负载；
- 任一 Rank OOM、NCCL 超时、Kernel 非法访问或 Pod 重启；
- Parser、Tool Call 或长上下文答案不正确；
- 相同 Case 三轮结果明显漂移且无法解释。

发生停止条件时保存日志、Events、节点拓扑和原始请求，不通过反复重启掩盖问题。

## 产物

可执行材料放在 `examples/glm53-day1/`：镜像基线、Case 矩阵、权重预检、功能 Smoke、
Benchmark、Prefix Cache、Needle 和原始结果。实测开始后，先写机器可读 JSON/CSV，再更新
本文结论。

## 参考资料

- [GLM-5.3 模型与权重](https://huggingface.co/zai-org/GLM-5.3)
- [SGLang GLM-5.3 Cookbook](https://docs.sglang.io/cookbook/autoregressive/GLM/GLM-5.3)
- [vLLM GLM-5.3 Recipe](https://recipes.vllm.ai/zai-org/GLM-5.3)
