---
title: "Why GPU Utilization Is Low"
description: "Identify GPU idle time from data, CPU, communication, kernel, batching, and platform metrics"
status: stable
last_reviewed: 2026-08-04
---

# Why GPU Utilization Is Low

Low utilization is not a root cause. The GPU may be waiting for data, waiting for other ranks, waiting for the CPU, waiting for the network, waiting for requests, or the model itself may be unable to fill the device. Draw a timeline first, then decide which layer to optimize.

## 1. A Complete Waiting Chain

```text
对象存储/文件系统
  → DataLoader/Tokenizer/Decode
  → Host Memory 与 H2D
  → GPU Kernel
  → GPU-GPU Collective
  → Checkpoint/结果写回
```

Inference also adds Gateway queueing, dynamic batching, Prefill, Decode, KV Cache, and streaming sends.

## 2. Symptoms and Evidence

| Symptom | Primary suspicion | Evidence |
| --- | --- | --- |
| Periodic GPU sawtooth pattern | Data supply or Checkpoint | I/O, DataLoader, disk write timeline |
| One card slow, other cards waiting | Slow rank, topology, or hardware | Per-rank step time, NCCL Trace |
| Low SM but very high GPU memory | Small batch, Decode, or memory-bound | Kernel, Batch, Token phases |
| CPU saturated while GPU idle | Tokenize/Decode/data processing | CPU profile, Run Queue |
| Network saturated with rising step time | Collective or parameter sync | NIC/RDMA, NCCL timing |
| Low GPU during low-QPS inference | Insufficient traffic | Arrival rate, concurrency, Batch Size |

## 3. Diagnostic Experiments

1. Replace real data with synthetic data to confirm the compute ceiling;
2. Disable Checkpoint and observe whether the sawtooth pattern disappears;
3. Test progressively: single card, single-node multi-card, multi-node;
4. Fix input length and concurrency for stepwise inference load testing;
5. Compare cold cache and hot cache;
6. Record per-rank step time instead of looking only at averages;
7. Use NCCL Tests and storage benchmarks to isolate framework effects.

## 4. Optimization Order

Fix errors and jitter first, then fix supply, then tune Batch/parallelism, and only finally replace hardware or introduce complex disaggregated architectures. Change only one major variable at a time, and report throughput, latency, quality, failure rate, and cost together.

## 5. Common Misconceptions

- Treating `GPU Utilization` as the only KPI;
- Sacrificing TTFT, tail latency, or training convergence to improve utilization;
- Only adding DataLoader workers without checking CPU, memory, and small files;
- Directly adding GPUs when multi-node slows down;
- Assuming an engine misconfiguration when seeing low Decode utilization.

Extended reading: [Observability](../observability.md), [Performance Benchmarks](../benchmarking.md), [Data and Cache](../data-storage.md), [RDMA](../rdma-networking.md)
