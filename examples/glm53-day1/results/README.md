# GLM-5.3 H20 公开压测数据

这里保存 2026-08-30 GLM-5.3 Native FP8 在单节点 8×NVIDIA H20-3e、TP8 上的
脱敏聚合结果。

- SGLang 与 vLLM 各 9 个 Case，每个 Case 3 轮；
- 两套引擎各完成 3,840 个请求，合计 7,680 个请求，失败数为 0；
- 每个数值指标分别取三轮中位数，不选择最快一轮；
- 两套服务端统一使用 `vllm bench serve` 客户端、相同 Case 和随机请求参数；
- 原始 JSON 包含随机 Prompt 与生成文本，因此不放入公开仓库。

[`h20-fp8-baseline-median-20260830.csv`](h20-fp8-baseline-median-20260830.csv)
保留每个引擎、每个 Case 的请求计数、吞吐，以及 P50/P95/P99 TTFT、TPOT 和 E2E。

完整分析见
[`GLM-5.3 首日实测：8×H20 上的 SGLang 与 vLLM 基线压测`](../../../docs/ai-k8s/practices/glm53-h20-sglang-vllm-test-plan.md)。
