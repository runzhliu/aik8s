---
title: GPU 节点故障图鉴
description: 用 XID、ECC、NVLink、掉卡、NCCL、RDMA 和 kubelet 证据定位 GPU 故障
status: evolving
last_reviewed: 2026-08-04
---

# GPU 节点故障图鉴

同一个“CUDA error”可能来自应用、驱动、GPU、PCIe、NVLink、NIC、交换网络或节点电源。故障图鉴的作用是保存证据和缩小故障域，不是看到错误码就自动重启节点。

## 1. 症状矩阵

| 症状 | 可能故障域 | 第一批证据 |
| --- | --- | --- |
| GPU 从 Allocatable 消失 | Device Plugin、驱动、PCIe | kubelet、插件日志、`nvidia-smi` |
| XID/ECC 增长 | GPU/显存/驱动 | DCGM、内核日志、XID 时间 |
| NCCL Timeout | 慢 Rank、GPU、NIC、Fabric | 各 Rank 日志、NCCL、RDMA 指标 |
| NVLink 降级 | Link、拓扑、硬件 | NVLink counters、拓扑图 |
| 容器看不到 CUDA | Runtime/CDI/挂载 | CDI Spec、Runtime、设备节点 |
| 性能突然下降 | 时钟、温度、功耗、链路 | DCGM、功耗、PCIe/NIC 速率 |
| 节点反复 NotReady | OS、kubelet、磁盘、网络 | Node Condition、系统日志 |

## 2. 证据顺序

```text
保存 Pod/Job/Node UID 和时间
  → 采集 Kubernetes Event 与调度状态
  → 采集 kubelet、Runtime、Device Plugin
  → 采集 DCGM/nvidia-smi/内核日志
  → 采集 NIC/RDMA/NCCL 与交换网络
  → 再决定隔离、复位、重启或维修
```

## 3. 自动隔离原则

临时错误可以阻止新任务并观察；重复 XID、不可恢复 ECC、GPU 丢失或链路硬故障应 Taint/隔离节点。正在训练的任务是否终止，要结合 Checkpoint 和分布式框架语义，不能由节点健康控制器盲目删除。

## 4. Runbook 字段

故障签名、首次时间、影响卡/节点/作业、固件/驱动版本、复现条件、诊断命令、临时处置、恢复验证、维修结论和再次发生阈值。

延伸阅读：[GPU 节点软件栈](../cluster/gpu-node-stack.md)、[可观测性](../observability.md)、[可靠性](../reliability.md)

