---
title: vLLM、SGLang 与 TensorRT-LLM 同机实测
description: 固定模型、硬件和负载，公平比较主流 LLM 推理引擎
status: lab
last_reviewed: 2026-08-04
---

# vLLM、SGLang 与 TensorRT-LLM 同机实测

引擎对比只有在模型、精度、硬件、并行、输入输出分布和质量门槛一致时才有意义。这个实验页定义测试协议，不预设哪个引擎永远更快。

## 1. 固定变量

| 维度 | 必须记录 |
| --- | --- |
| 模型 | Repo、Revision、Tokenizer、量化和最大上下文 |
| 硬件 | GPU、卡数、互联、CPU、内存和功耗限制 |
| 软件 | 驱动、CUDA、PyTorch、引擎和镜像 Digest |
| 并行 | TP、PP、DP、EP 和副本数 |
| 负载 | 输入/输出长度分布、到达模型、并发和数据集 |
| 质量 | 输出一致性、任务指标或困惑度允许偏差 |

## 2. 测试矩阵

至少包含：

- 固定并发 1、8、32、128；
- 短输入长输出、长输入短输出和长上下文；
- Poisson 到达与封闭并发两种模型；
- 冷启动、热模型、热 Prefix Cache；
- 单副本、多副本以及达到 SLO 前的最大负载。

## 3. 输出指标

```text
TTFT p50/p95/p99
TPOT p50/p95/p99
端到端延迟与失败率
请求/秒、输入 Token/秒、输出 Token/秒
GPU 显存、SM、功耗和 KV Cache 使用
每百万 Token 的 GPU 时间与成本
```

吞吐最大值和满足 SLO 的最大吞吐必须分别报告。发生 OOM、队列溢出或输出质量变化时，该点不能作为有效胜出结果。

## 4. 推荐结果表

| 引擎 | 并发 | TTFT p95 | TPOT p95 | Output tok/s | 峰值显存 | 错误率 | 质量通过 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| vLLM | 待测 | 待测 | 待测 | 待测 | 待测 | 待测 | 待测 |
| SGLang | 待测 | 待测 | 待测 | 待测 | 待测 | 待测 | 待测 |
| TensorRT-LLM | 待测 | 待测 | 待测 | 待测 | 待测 | 待测 | 待测 |

## 5. Kubernetes 变量

固定 CPU Manager、NUMA、GPU 拓扑、共享策略、容器内 `/dev/shm`、网络、模型挂载和探针。测试前确认没有其他 Pod 共享 GPU、CPU、NIC 或磁盘。

延伸阅读：[推理引擎](../inference/engines.md)、[推理优化](../inference/optimization.md)、[性能基准](../benchmarking.md)

