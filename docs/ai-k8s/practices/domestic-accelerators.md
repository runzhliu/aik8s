---
title: 国产 GPU/NPU 的 Kubernetes 实践
description: 用平台契约接入昇腾及其他国产加速器，管理驱动、资源名、镜像、调度和可观测差异
status: evolving
last_reviewed: 2026-08-04
---

# 国产 GPU/NPU 的 Kubernetes 实践

国产加速器接入的难点不只是 Device Plugin。框架、编译器、算子、镜像、驱动、固件、集合通信、拓扑、监控和故障码通常都与 CUDA 生态不同。

## 1. 接入清单

```text
硬件与固件
  → OS/内核/IOMMU
  → 驱动与容器 Runtime
  → Device Plugin/CDI/DRA
  → 调度器与拓扑
  → PyTorch 适配/编译器/算子
  → HCCL 或厂商 Collective
  → Exporter、健康与故障隔离
```

## 2. 平台不要暴露厂商细节

业务提交稳定能力，例如：

```yaml
accelerator:
  class: training-large-memory
  count: 8
  topology: single-node
  precision: bf16
```

平台再映射到 `nvidia.com/gpu`、厂商 NPU 资源名、ResourceFlavor、节点标签、RuntimeClass 和镜像。不要声称不同硬件可以无条件运行同一镜像和同一模型制品。

## 3. 昇腾实践重点

确认 CANN、驱动、固件、PyTorch 适配、HCCL、Device Plugin、NPU Exporter 和目标硬件的完整矩阵。多机训练要同时验证 NPU 拓扑和 HCCS/RoCE 等网络路径。云上可评估 CCE AI Suite 与 Volcano，私有环境则要自行承担组件集成和升级验证。

## 4. 其他国产加速器

对于海光、寒武纪、壁仞、沐曦、燧原等方案，用同一张验收表逐项确认：上游框架兼容、模型覆盖、算子缺口、容器镜像、Kubernetes 接口、监控、集合通信、虚拟化、故障恢复和厂商支持边界。产品名称和支持矩阵变化快，应以目标型号的正式文档和 POC 为准。

## 5. 迁移基准

先做算子与模型正确性，再比较端到端训练收敛或推理质量；随后比较吞吐、延迟、功耗、稳定性和工程改造成本。不能只用理论算力或单个 Kernel 判断迁移完成。

延伸阅读：[多厂商异构加速器](../accelerators/heterogeneous-accelerators.md)、[设备管理](../accelerators/device-management.md)、[GPU 调度](../gpu-scheduling.md)

