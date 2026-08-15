# SGLang 实测结果（2026-08-15）

环境：单张 NVIDIA L20（46,068 MiB）、SGLang 0.5.16、
Qwen3.8-27B-FP8、TP=1、32K、FP8 KV、MTP Off、完整多模态。默认
8192-token prefill CUDA Graph 在启动时 OOM，因此只禁用 prefill graph，保留
decode CUDA Graph。可用 KV 容量使服务把内部 `max-running-requests` 从 8 降为 6。

测试由现有 vLLM 0.26.0 Pod 内的 `vllm bench serve` 发起，通过 SGLang
ClusterIP OpenAI Completions API 访问；Tokenizer、seed、请求长度、请求数、
`request-rate=inf`、`temperature=0`、`ignore-eos=true` 均与 vLLM 基线一致。

| 输入/输出 | 客户端并发 | 成功 | req/s | 输出 tok/s | 总 tok/s | p50/p95/p99 TTFT (ms) | p95 TPOT (ms) | p95 ITL (ms) | p95 E2EL (ms) |
| --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: |
| 128/64 | 1 | 64/64 | 0.30 | 19.26 | 57.79 | 179.74 / 225.45 / 226.11 | 50.57 | 51.10 | 3,366.33 |
| 128/64 | 4 | 64/64 | 1.25 | 80.12 | 240.37 | 215.33 / 216.67 / 217.72 | 47.35 | 48.00 | 3,198.97 |
| 128/64 | 8 | 64/64 | 1.75 | 112.04 | 336.12 | 290.96 / 3,631.79 / 3,632.26 | 48.44 | 49.11 | 6,681.54 |
| 4096/128 | 4 | 32/32 | 0.35 | 45.17 | 1,490.53 | 5,220.82 / 5,239.00 / 5,240.64 | 58.36 | 48.77 | 11,357.74 |

并发 1/4 时 SGLang Decode 吞吐高于本次 vLLM 基线；客户端并发 8 超过内部
6-slot 上限后，p95 TTFT 增至 3.63 秒且输出吞吐低于 vLLM。4096-token 组的
Decode 与 E2EL 仍较好，但禁用 prefill graph 后 TTFT 高于 vLLM。这些数字不能被
描述为默认配置或严格同构 A/B：vLLM 使用 language-only，而本组 SGLang 加载了
完整多模态模型。原始 JSON 与本文件同目录。

压测结束后 Pod 为 `Ready=true`、`restartCount=0`。空闲快照为
43,521 / 46,068 MiB、82.46 W；它不是压测期间的峰值功耗。
