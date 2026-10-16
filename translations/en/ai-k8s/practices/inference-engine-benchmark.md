---
title: "vLLM, SGLang, and TensorRT-LLM Same-Machine Benchmark"
description: "Fix model, hardware, and load to fairly compare mainstream LLM inference engines"
status: lab
last_reviewed: 2026-08-04
---

# vLLM, SGLang, and TensorRT-LLM Same-Machine Benchmark

Engine comparisons are only meaningful when model, precision, hardware, parallelism, input/output distribution, and quality thresholds are consistent. This experiment page defines the test protocol and does not presuppose that any engine is always faster.

## 1. Fixed Variables

| Dimension | Must record |
| --- | --- |
| Model | Repo, Revision, Tokenizer, quantization, and maximum context |
| Hardware | GPU, number of cards, interconnect, CPU, memory, and power limits |
| Software | Driver, CUDA, PyTorch, engine, and image Digest |
| Parallelism | TP, PP, DP, EP, and number of replicas |
| Load | Input/output length distribution, arrival model, concurrency, and dataset |
| Quality | Output consistency, task metrics, or allowed perplexity deviation |

## 2. Test Matrix

At minimum, include:

- Fixed concurrency of 1, 8, 32, 128;
- Short input/long output, long input/short output, and long context;
- Both Poisson arrival and closed concurrency models;
- Cold start, warm model, warm Prefix Cache;
- Single replica, multiple replicas, and maximum load before the SLO is violated.

## 3. Output Metrics

```text
TTFT p50/p95/p99
TPOT p50/p95/p99
端到端延迟与失败率
请求/秒、输入 Token/秒、输出 Token/秒
GPU 显存、SM、功耗和 KV Cache 使用
每百万 Token 的 GPU 时间与成本
```

Peak throughput and maximum throughput that meets the SLO must be reported separately. If OOM, queue overflow, or output quality changes occur, that point cannot count as a valid winning result.

## 4. Recommended Results Table

| Engine | Concurrency | TTFT p95 | TPOT p95 | Output tok/s | Peak GPU memory | Error rate | Quality pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| vLLM | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| SGLang | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| TensorRT-LLM | TBD | TBD | TBD | TBD | TBD | TBD | TBD |

## 5. Kubernetes Variables

Fix CPU Manager, NUMA, GPU topology, sharing policy, in-container `/dev/shm`, network, model mounts, and probes. Before testing, confirm that no other Pods share the GPU, CPU, NIC, or disk.

Further reading: [Inference engines](../inference/engines.md), [Inference optimization](../inference/optimization.md), [Performance benchmarks](../benchmarking.md)
