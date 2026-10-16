---
title: "Kubernetes Practices for Domestic GPU/NPU"
description: "Using platform contracts to integrate Ascend and other domestic accelerators, managing differences in drivers, resource names, images, scheduling, and observability"
status: evolving
last_reviewed: 2026-08-04
---

# Kubernetes Practices for Domestic GPU/NPU

The difficulty of integrating domestic accelerators is not limited to the Device Plugin. Frameworks, compilers, operators, images, drivers, firmware, collective communication, topology, monitoring, and error codes typically all differ from the CUDA ecosystem.

## 1. Integration Checklist

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

## 2. The Platform Should Not Expose Vendor Details

Workloads submit stable capabilities, for example:

```yaml
accelerator:
  class: training-large-memory
  count: 8
  topology: single-node
  precision: bf16
```

The platform then maps to `nvidia.com/gpu`, vendor NPU resource names, ResourceFlavor, node labels, RuntimeClass, and images. Do not claim that different hardware can unconditionally run the same image and the same model artifact.

## 3. Key Points for Ascend Practice

Confirm the complete matrix of CANN, drivers, firmware, PyTorch adaptation, HCCL, Device Plugin, NPU Exporter, and target hardware. For multi-node training, verify both NPU topology and network paths such as HCCS/RoCE. In the cloud, CCE AI Suite and Volcano can be evaluated; in private environments, you must bear the cost of component integration and upgrade validation yourself.

## 4. Other Domestic Accelerators

For solutions from Hygon, Cambricon, Biren, MetaX, Enflame, and others, use the same acceptance checklist to confirm each item: upstream framework compatibility, model coverage, operator gaps, container images, Kubernetes interfaces, monitoring, collective communication, virtualization, failure recovery, and vendor support boundaries. Product names and support matrices change quickly; rely on the official documentation and POC of the target model.

## 5. Migration Benchmark

First verify operator and model correctness, then compare end-to-end training convergence or inference quality; subsequently compare throughput, latency, power consumption, stability, and engineering rework cost. Theoretical compute capability or a single kernel alone cannot determine that migration is complete.

Further reading: [Multi-vendor Heterogeneous Accelerators](../accelerators/heterogeneous-accelerators.md), [Device Management](../accelerators/device-management.md), [GPU Scheduling](../gpu-scheduling.md)
