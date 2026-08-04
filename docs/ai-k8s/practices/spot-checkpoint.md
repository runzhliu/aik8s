---
title: Spot GPU 与 Checkpoint 恢复实验
description: 测量抢占通知、Checkpoint、重排队和训练恢复的真实成本收益
status: lab
last_reviewed: 2026-08-04
---

# Spot GPU 与 Checkpoint 恢复实验

Spot 价格折扣不等于训练成本同比下降。有效收益取决于中断率、通知窗口、Checkpoint 时间、排队、容量重新获得和恢复后的重复计算。

## 1. 成本模型

```text
有效成本 = GPU 运行费用
         + Checkpoint I/O
         + 中断后的重复计算
         + 等待新容量的空窗
         + 恢复失败和人工干预
```

## 2. 实验步骤

1. 在按需节点完成无中断基线；
2. 分别设置 5、15、30、60 分钟 Checkpoint 周期；
3. 在不同训练阶段注入节点终止；
4. 测量通知到进程退出、写入完成和 Pod 消失的时间；
5. 重新排队并从最新有效 Checkpoint 恢复；
6. 验证 step、数据游标、优化器和随机状态；
7. 对比最终收敛、总 GPU 小时和墙钟时间。

## 3. 必须区分

- 单节点消失与整个 Gang 被回收；
- 本地 NVMe Checkpoint 与远端持久 Checkpoint；
- 同规格恢复与 GPU 数变化后的重分片；
- 云中断通知、Kubernetes 优雅终止和强制关机；
- 弹性训练继续运行与完整 Job 重启。

## 4. 验收

连续注入多次中断，训练仍能自动恢复且最终质量与基线一致；损失的训练步数、RPO、RTO 和成本节省均有记录。无法自动验证 Checkpoint 完整性时，不应扩大 Spot 比例。

延伸阅读：[可靠性与 Checkpoint](../reliability.md)、[成本与容量](../cost-capacity.md)、[自动扩缩容](../scheduling/autoscaling.md)

