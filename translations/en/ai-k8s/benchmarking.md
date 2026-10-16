---
title: "Performance Benchmarking, Stress Testing, and Regression"
description: "Layered benchmarks and release gates for GPU, network, storage, training, and inference"
status: stable
last_reviewed: 2026-08-02
---

# Performance Benchmarking, Stress Testing, and Regression

Performance testing for an AI platform cannot rely on running `nvidia-smi` once or looking at some public leaderboard. Effective benchmarking requires fixed data, models, software, topology, and quality targets, and must span from hardware micro-benchmarks all the way to real business SLOs.

## 1. Five-Layer Benchmark System

```text
业务结果：成本、质量、成功请求、训练目标
端到端：完整训练、完整推理请求
框架组件：vLLM、PyTorch、数据加载、Checkpoint
集群通信：NCCL、RDMA、存储、Pod 网络
硬件基线：GPU、NVLink、PCIe、CPU、磁盘、NIC
```

Low-level benchmarks help with localization; end-to-end benchmarks determine whether something is usable. No single layer can replace the others.

## 2. Freeze Variables Before Testing

Every result must record:

- GPU model, count, power mode, and clocks;
- CPU, NUMA, and memory;
- NIC, switching fabric, and topology;
- OS, kernel, driver, CUDA, and NCCL;
- Kubernetes, Runtime, and Operator;
- Image digest and code commit;
- Model, precision, quantization, and parallelism strategy;
- Dataset, input/output length distribution;
- Batch, concurrency, and cache cold/hot state;
- Number of runs, warm-up, and statistical method.

A "20% faster" claim without this metadata cannot be reproduced.

## 3. Hardware and Node Baseline

Before new nodes join the pool, at minimum check:

- DCGM diagnostics and GPU health;
- GPU memory bandwidth and basic compute capability;
- GPU P2P matrix;
- NVLink/NvSwitch status;
- PCIe Link Width/Generation;
- CPU memory bandwidth and NUMA;
- Local NVMe sequential and random I/O;
- NIC bandwidth, latency, and errors;
- Temperature, power, and sustained-load throttling.

The goal is not to chase theoretical peaks, but to detect abnormal outliers among nodes of the same model.

## 4. NCCL and RDMA Benchmarks

Recommended to test layer by layer:

1. Two GPUs on one machine;
2. All GPUs on one machine;
3. Two nodes in the same rack;
4. Multiple nodes in the same network domain;
5. Cross-rack or cross-Block;
6. Same scale as real training.

Test All-Reduce, All-Gather, Reduce-Scatter, and All-to-All, and plot bandwidth/latency curves by message size. Reporting only maximum message throughput masks problems with small messages and real gradient sizes.

Also save the NCCL topology, selected NICs, and GPU/NIC affinity.

## 5. Storage and Data Loading Benchmarks

Test separately:

- Single Pod sequential read/write;
- Multi-Pod/multi-node concurrency;
- Large files and large numbers of small files;
- Cold cache and hot cache;
- Object storage first byte and sustained throughput;
- Concurrent model downloads;
- Checkpoint save and restore;
- Real DataLoader samples/s.

`fio` can test block and file systems, but cannot replace the real data format, decoding, and augmentation pipeline.

## 6. Training Benchmarks

Training benchmarks should cover at least three categories:

### Single-Step Performance

- step time;
- samples/tokens per second;
- GPU, communication, and data waiting breakdown;
- Scaling Efficiency.

```text
扩展效率
  = N 卡实际吞吐 / (单卡吞吐 × N)
```

### Time-to-Quality

Using fixed data, a random seed range, and quality thresholds, measure the time to reach target Loss/Accuracy. MLPerf Training also compares systems by reaching target quality. Reference: [MLPerf Training](https://mlcommons.org/benchmarks/training/)

### Recovery Performance

- Checkpoint save blocking time;
- Recovery download and re-sharding;
- RTO after worker failure;
- Proportion of recomputation caused by Spot interruptions.

## 7. Inference Stress Test Scenarios

Cover at minimum:

| Scenario | Purpose |
| --- | --- |
| Offline | Measure maximum throughput, without emphasizing per-request latency |
| Server | Test throughput and tail latency under random arrival rates |
| Interactive | Emphasize TTFT, streaming output, and concurrent experience |
| Cold Start | Test image, model loading, and first request |
| Burst | Test spikes, queuing, rate limiting, and scaling |
| Long Context | Test long inputs, KV Cache, and OOM boundaries |
| Mixed Models | Test routing, caching, and resource contention across multiple models |

MLPerf Inference distinguishes Datacenter/Edge and scenarios such as Offline, Server, and Interactive, and can serve as a design reference. Reference: [MLPerf Inference](https://docs.mlcommons.org/inference/)

## 8. LLM Stress Test Inputs Must Be Realistic

Fixed short prompts severely overestimate capacity. Construct inputs from a de-identified business distribution:

- Input token distribution;
- Output token distribution;
- Streaming vs. non-streaming ratio;
- Different models/Adapters;
- Repeated prefixes and cache hits;
- Cancelled requests;
- Tool calls and retrieval latency;
- Priority and tenant mixing.

Report P50/P95/P99 TTFT, TPOT, E2E, Token/s, error rate, and maximum throughput that satisfies the SLO.

## 9. Quality and Performance Must Be Tied Together

Quantization, speculative decoding, batching, parallelism, and caching can all change outputs. Run the following alongside every performance optimization:

- Offline accuracy/task quality;
- Key safety and refusal evaluations;
- Output stability;
- Numerical precision and overflow checks;
- Business sample regression.

Performance results that do not meet quality thresholds do not enter the comparison table.

## 10. Variables Introduced by Kubernetes

- CPU request/limit and throttling;
- Pod QoS and eviction;
- Topology Manager/CPU Manager;
- Device Plugin or DRA;
- CNI, Service Mesh, and proxies;
- PVC/CSI;
- Interference from other Pods on the node;
- Kueue waiting and Flavor;
- Autoscaler cold start;
- Overhead of monitoring collection itself.

Keep both bare-metal results and Kubernetes results; the difference between them helps localize platform overhead.

## 11. Avoid Incorrect Comparisons

Do not directly compare:

- Different models or quality thresholds;
- Different input/output lengths;
- Hot cache vs. cold cache;
- Different precision/quantization;
- Different power caps;
- A single best result vs. the median of multiple runs;
- Full-load throughput vs. low-load latency;
- Vendor-optimized implementations vs. unoptimized reference implementations.

Public leaderboards are used to form an expected range; they cannot replace testing on your own models and clusters.

## 12. Statistics and Result Presentation

- Run at least multiple times; report the median and dispersion;
- Run long-duration steady-state tests to exclude results that rely only on short-term boost;
- Clearly state warm-up time and discarded intervals;
- Report failures and OOMs, not just successful results;
- Save time series and aggregate values together;
- Mark whether the environment is shared and whether there is interference;
- Retain raw logs, configurations, and image digests.

## 13. Integrate Regression Testing into Releases

Execute in tiers:

1. PR: small-scale functional and short performance Smoke Test;
2. Daily: representative single-node training/inference;
3. Weekly: multi-node NCCL, storage, and long steady-state;
4. Before/after upgrades: full baseline matrix;
5. New hardware onboarding: node acceptance and cluster-level testing.

Set an allowed regression threshold for each item, and distinguish between noise, known changes, and true failures.

## 14. Result Template

```text
目标：验证新驱动不降低 8×GPU 训练性能
环境：硬件/拓扑/软件/镜像摘要
工作负载：模型、数据、精度、Batch、并行
基线：版本 A 的中位数与方差
候选：版本 B 的中位数与方差
质量：目标指标与是否通过
性能：吞吐、延迟、GPU/网络/存储分解
可靠性：失败、重试、XID、恢复
结论：通过 / 阻塞 / 有条件通过
原始证据：Dashboard、日志、制品链接
```

## 15. Go-Live Checklist

- [ ] Establish five-layer benchmarks for hardware, communication, storage, framework, and end-to-end;
- [ ] Record complete hardware, topology, and software metadata for every result;
- [ ] Training measures throughput, Time-to-Quality, and recovery simultaneously;
- [ ] Inference covers realistic length distributions, bursts, and cold starts;
- [ ] All optimizations pass quality and safety regression;
- [ ] Bare-metal and Kubernetes results are comparable;
- [ ] Report median, dispersion, and failed results;
- [ ] Key benchmarks enter upgrade and release gates;
- [ ] Raw configuration and evidence are traceable.

## Further Reading

- [MLPerf Training](https://mlcommons.org/benchmarks/training/)
- [MLPerf Inference](https://docs.mlcommons.org/inference/)
- [NVIDIA DCGM Diagnostics](https://docs.nvidia.com/datacenter/dcgm/latest/user-guide/dcgm-diagnostics.html)
- [NCCL Tests](https://github.com/NVIDIA/nccl-tests)
