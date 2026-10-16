---
title: "Spot GPU and Checkpoint Recovery Experiments"
description: "Measure the real cost-benefit of preemption notifications, checkpoints, requeueing, and training recovery"
status: lab
last_reviewed: 2026-08-04
---

# Spot GPU and Checkpoint Recovery Experiments

A spot price discount does not mean training cost decreases by the same percentage. Effective gains depend on interruption rate, notification window, checkpoint time, queueing, capacity reacquisition, and duplicate computation after recovery.

## 1. Cost Model

```text
有效成本 = GPU 运行费用
         + Checkpoint I/O
         + 中断后的重复计算
         + 等待新容量的空窗
         + 恢复失败和人工干预
```

## 2. Experiment Procedure

1. Complete an interruption-free baseline on on-demand nodes;
2. Configure checkpoint periods of 5, 15, 30, and 60 minutes respectively;
3. Inject node termination at different training stages;
4. Measure the time from notification to process exit, checkpoint write completion, and Pod disappearance;
5. Requeue and recover from the latest valid checkpoint;
6. Verify step, data cursor, optimizer, and random state;
7. Compare final convergence, total GPU hours, and wall-clock time.

## 3. Distinctions That Must Be Made

- Single-node disappearance versus entire gang reclamation;
- Local NVMe checkpoints versus remote persistent checkpoints;
- Recovery on the same instance type versus resharding after a change in GPU count;
- Cloud interruption notifications, Kubernetes graceful termination, and forced shutdown;
- Elastic training that continues running versus a full job restart.

## 4. Acceptance Criteria

After continuously injecting multiple interruptions, training must still recover automatically and final quality must match the baseline; the number of training steps lost, RPO, RTO, and cost savings must all be recorded. If checkpoint integrity cannot be verified automatically, the spot ratio should not be increased.

Further reading: [Reliability and Checkpoints](../reliability.md), [Cost and Capacity](../cost-capacity.md), [Autoscaling](../scheduling/autoscaling.md)
