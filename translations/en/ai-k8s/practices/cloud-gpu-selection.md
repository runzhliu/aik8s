---
title: "GPU Cloud Resource Selection: Domestic and International"
description: "Evaluate cloud GPUs by inventory, topology, network, storage, Spot, egress, and software stack"
status: evolving
last_reviewed: 2026-08-04
---

# GPU Cloud Resource Selection: Domestic and International

Choosing cloud GPUs cannot rely only on comparing "per-card per-hour" pricing. GPUs with the same name can differ completely in CPU ratio, NVLink/NVSwitch, NIC, NUMA, virtualization, disk, regional inventory, and reservation terms.

## 1. Price Inquiry Table

| Category | Required Fields |
| --- | --- |
| Compute | GPU model/GPU memory/card count, CPU, memory, virtualization method |
| Topology | PCIe, NVLink/NVSwitch, NUMA, inter-card bandwidth |
| Network | NIC count, bandwidth, RDMA type, cross-node/cross-zone topology |
| Storage | Local NVMe, block storage, parallel file system, object storage throughput |
| Capacity | Region/AZ, immediate inventory, reservation, delivery lead time, quota |
| Pricing | On-demand, annual, reserved, Spot, egress, cross-zone, and support fees |
| Software | OS, driver, CUDA/ROCm/CANN, Device Plugin, monitoring |

## 2. Training and Inference Have Different Weights

Training prioritizes multi-card topology, RDMA, whole-group capacity delivery, Checkpoint, and Spot recovery; inference prioritizes per-card cost-effectiveness, sharing/partitioning, model loading, scaling speed, regional coverage, and online SLA.

## 3. Mandatory POC Tests

- Single-card kernel and GPU memory bandwidth;
- Single-node Collective and cross-node NCCL/HCCL;
- Object storage, file systems, and local disks;
- Cold node to model Ready;
- Real training step time or inference TTFT/TPOT;
- Spot interruption, node maintenance, and capacity reacquisition;
- Cross-AZ and public internet egress billing samples.

## 4. Result Normalization

For training, use total cost and wall-clock time to reach target quality; for inference, use cost per million effective tokens that meet the latency SLO. Comparing only peak TFLOPS, Token/s, or list prices is misleading.

## 5. Multi-Cloud Strategy

First unify model Revision, OCI images, object storage interfaces, queue contracts, metrics, and benchmarks, then adapt to each cloud's CNI/CSI/IAM/NodeClass. Multi-cloud can add capacity sources, but data replication, talent, discount, and failure complexity also increase.

Further reading: [Cloud Provider Kubernetes](../cluster/cloud-managed-kubernetes.md), [Heterogeneous Accelerators](../accelerators/heterogeneous-accelerators.md), [Cost and Capacity](../cost-capacity.md)
