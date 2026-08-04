---
title: GPU 利用率为什么很低
description: 从数据、CPU、通信、内核、批处理和平台指标定位 GPU 空转
status: stable
last_reviewed: 2026-08-04
---

# GPU 利用率为什么很低

低利用率不是一个根因。GPU 可能在等数据、等其他 Rank、等 CPU、等网络、等请求，或者模型本身就无法填满设备。先画出时间线，再决定优化哪一层。

## 1. 一条完整等待链

```text
对象存储/文件系统
  → DataLoader/Tokenizer/Decode
  → Host Memory 与 H2D
  → GPU Kernel
  → GPU-GPU Collective
  → Checkpoint/结果写回
```

推理还要加上 Gateway 排队、动态批处理、Prefill、Decode、KV Cache 和流式发送。

## 2. 现象与证据

| 现象 | 优先怀疑 | 证据 |
| --- | --- | --- |
| GPU 周期性锯齿 | 数据供给或 Checkpoint | I/O、DataLoader、写盘时间线 |
| 一张卡慢，其他卡等待 | 慢 Rank、拓扑或硬件 | 每 Rank step time、NCCL Trace |
| SM 低但显存很高 | 小 Batch、Decode 或内存受限 | Kernel、Batch、Token 阶段 |
| CPU 满而 GPU 空 | Tokenize/Decode/数据处理 | CPU profile、Run Queue |
| 网络满且 step time 上升 | Collective 或参数同步 | NIC/RDMA、NCCL 时间 |
| 推理低 QPS 时 GPU 低 | 流量不足 | 到达率、并发、Batch Size |

## 3. 诊断实验

1. 用合成数据替代真实数据，确认计算上限；
2. 禁用 Checkpoint，观察锯齿是否消失；
3. 单卡、单机多卡、多机逐级测试；
4. 固定输入长度和并发做推理阶梯压测；
5. 对比冷缓存和热缓存；
6. 逐 Rank 记录 step time，而不是只看平均值；
7. 用 NCCL Tests 和存储基准把框架影响隔离出去。

## 4. 优化顺序

先修错误和抖动，再修供给，再调 Batch/并行，最后才更换硬件或引入复杂分离式架构。每次只改变一个主要变量，并同时报告吞吐、延迟、质量、失败率和成本。

## 5. 常见误区

- 把 `GPU Utilization` 当作唯一 KPI；
- 为了提高利用率牺牲 TTFT、尾延迟或训练收敛；
- 只增加 DataLoader Worker，不检查 CPU、内存和小文件；
- 多机变慢时直接增加 GPU；
- 看到 Decode 利用率低就认定引擎配置错误。

延伸阅读：[可观测性](../observability.md)、[性能基准](../benchmarking.md)、[数据与缓存](../data-storage.md)、[RDMA](../rdma-networking.md)

