---
title: 国内外 GPU 云资源选型
description: 按库存、拓扑、网络、存储、Spot、出流和软件栈评估云上 GPU
status: evolving
last_reviewed: 2026-08-04
---

# 国内外 GPU 云资源选型

选择云上 GPU 不能只比较“每卡每小时”。同名 GPU 在 CPU 配比、NVLink/NVSwitch、NIC、NUMA、虚拟化、磁盘、地域库存和预留条件上可能完全不同。

## 1. 询价表

| 类别 | 必填字段 |
| --- | --- |
| 计算 | GPU 型号/显存/卡数、CPU、内存、虚拟化方式 |
| 拓扑 | PCIe、NVLink/NVSwitch、NUMA、卡间带宽 |
| 网络 | NIC 数量、带宽、RDMA 类型、跨机/跨区拓扑 |
| 存储 | 本地 NVMe、块存储、并行文件、对象存储吞吐 |
| 容量 | 地域/AZ、即时库存、预留、交付周期、配额 |
| 价格 | 按需、包年、预留、Spot、出流、跨区和支持费用 |
| 软件 | OS、驱动、CUDA/ROCm/CANN、Device Plugin、监控 |

## 2. 训练和推理的权重不同

训练优先看多卡拓扑、RDMA、容量整组交付、Checkpoint 和 Spot 恢复；推理优先看单卡性价比、共享/切分、模型加载、扩容速度、区域覆盖和在线 SLA。

## 3. POC 必测

- 单卡 Kernel 与显存带宽；
- 单机 Collective 和跨机 NCCL/HCCL；
- 对象存储、文件系统和本地盘；
- 冷节点到模型 Ready；
- 真实训练 step time 或推理 TTFT/TPOT；
- Spot 中断、节点维修和容量重新获得；
- 跨可用区和公网出流账单样本。

## 4. 结果归一化

训练使用“达到目标质量的总成本和墙钟时间”；推理使用“满足延迟 SLO 的每百万有效 Token 成本”。仅比较峰值 TFLOPS、Token/s 或标价都会误导。

## 5. 多云策略

先统一模型 Revision、OCI 镜像、对象存储接口、队列契约、指标和基准，再适配各云 CNI/CSI/IAM/NodeClass。多云可以增加容量来源，但数据复制、人才、折扣和故障复杂度也会增加。

延伸阅读：[云厂商 Kubernetes](../cluster/cloud-managed-kubernetes.md)、[异构加速器](../accelerators/heterogeneous-accelerators.md)、[成本与容量](../cost-capacity.md)

