---
title: "Performance Inflection Point of Prefill/Decode Separation"
description: "Use dual-pool capacity, KV transfer, and real workloads to determine whether P/D separation is worthwhile"
status: lab
last_reviewed: 2026-08-04
---

# Performance Inflection Point of Prefill/Decode Separation

P/D separation is not faster by default. It trades two resource pools and KV transfer for stage-independent scaling, hardware matching, and interference isolation; when transfer, queuing, and operational costs exceed the benefits, ordinary replicas are better.

## 1. Signals That Must Be Met Simultaneously

- Prefill and Decode have distinctly different compute/GPU memory characteristics;
- The share of long prompts or long outputs in the workload is stable enough;
- Capacity peaks of the two stages do not occur at the same time, so independent scaling has benefits;
- The KV transfer network and protocol do not eat up the benefits;
- The team can operate dual pools, routing, versions, and failure semantics.

## 2. Three Baseline Groups

```text
A. 单副本：Prefill + Decode 同实例
B. 多普通副本：增加副本并智能路由
C. P/D 双池：独立实例 + KV 传输
```

First tune A/B to a reasonable level, then test C. Otherwise, an unoptimized baseline will be mistaken for separation benefits.

## 3. Required Test Workloads

| Workload | Input | Output | Purpose |
| --- | --- | --- | --- |
| Chat | Short to medium | Medium | Ordinary online baseline |
| RAG | Long | Short to medium | Prefill pressure |
| Reasoning | Medium | Very long | Decode pressure |
| Mixed | Real distribution | Real distribution | Inter-pool capacity and tail latency |

## 4. Inflection Point Judgment

Compare the minimum number of GPUs, cost per million tokens, p99 queue time, KV transfer traffic, and scaling time when meeting the same TTFT, TPOT, and failure rate. When the conclusion reverses after workload distribution changes, ordinary replicas should be kept as a degradation path.

## 5. Failure Experiments

- Prefill pool full, Decode pool full, and KV channel timeout;
- One side upgrades causing protocol/model version mismatch;
- Request completed Prefill but Decode instance disappears;
- Router state loss or duplicate dispatch;
- Cross-AZ transfer latency and cost increase.

Further reading: [Distributed and P/D Inference](../inference/distributed-serving.md), [Inference Optimization](../inference/optimization.md)
