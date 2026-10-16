---
title: "Distributing a 70B Model to 100 Nodes"
description: "Designing Registry, object storage, P2P, and node cache experiments for TB-scale models and 100-node inference pools"
status: lab
last_reviewed: 2026-08-04
---

# Distributing a 70B Model to 100 Nodes

Here, "70B" and "100 nodes" are experimental scale labels, not fixed answers. The goal is to break a single scale-out into measurable stages and avoid all nodes repeatedly pulling the same weights from remote object storage at the same time.

## 1. Timeline

```text
节点供给
  → OS/驱动/Runtime Ready
  → 镜像拉取
  → 模型发现与校验
  → 模型下载/解压/转换
  → 本地缓存命中
  → 引擎加载权重
  → CUDA Graph/Warmup
  → Readiness
```

Reporting only Pod creation to Running would mask the actual model loading time.

## 2. Comparison Approaches

| Approach | Advantages | Risks |
| --- | --- | --- |
| Each Pod pulls directly from object storage | Simple | Duplicate traffic, rate limiting, and startup storms |
| Init Container + HostPath | Easy to understand, node reuse | Locking, GC, security, and node lifecycle |
| DaemonSet pre-warming | Can complete in advance | Capacity prediction and version switching are complex |
| OCI Modelcar | Unified artifacts, digests, and supply chain | Registry large-artifact capability needs validation |
| P2P distribution | Reduces source fan-out | Peer security, topology, and failure recovery |
| Parallel file system | Consistent entry point | Metadata and concurrent read bottlenecks |

## 3. Experiment Matrix

Scale up progressively through 1, 10, 50, and 100 nodes, and test cold nodes, hot nodes, same availability zone, cross-availability zone, and single-source failure separately. Record source egress traffic, per-node throughput, p50/p95 completion time, failure rate, retry count, and cache hit rate.

## 4. Preventing the Thundering Herd

- Use batched pre-warming with jitter instead of creating all Pods at once;
- Download to a temporary path, then atomically rename after Digest verification;
- Use a lock on the same node to ensure it downloads only once;
- Cache GC first retains the current and previous production versions;
- Readiness waits until the model is actually ready to serve;
- The release system distinguishes between "artifact copied", "node cached", and "instance ready".

## 5. Acceptance

Source failure, a corrupted Peer, insufficient disk space, interrupted downloads, and model rollback must all have deterministic outcomes. The final report should give the complete time from zero scale-out to SLO capacity, not just download bandwidth.

Further reading: [Large model weight distribution and loading acceleration: community and commercial solution selection](model-weight-delivery-acceleration.md), [Model artifacts and distribution](../data/model-artifacts.md), [Data and caching](../data-storage.md)
