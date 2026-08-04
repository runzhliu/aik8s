---
title: Kueue 与 Volcano 对比实验
description: 用相同训练任务验证准入队列、Gang、公平共享、抢占与拓扑能力
status: lab
last_reviewed: 2026-08-04
---

# Kueue 与 Volcano 对比实验

Kueue 和 Volcano 并非简单替代关系。Kueue 强调工作负载准入和与现有调度器组合；Volcano 提供面向批任务的调度器、Job、Queue、PodGroup 和多种调度策略。应按平台所需控制点做实验。

## 1. 相同测试集

准备以下任务：

1. 单 Pod 单 GPU 短任务；
2. 8 Pod Gang 训练；
3. 需要同机或同机架拓扑的多卡任务；
4. 高低优先级混合；
5. 两个租户借用和回收配额；
6. 一个无法满足的超大任务；
7. 任务等待期间新增 GPU 节点。

## 2. 观察维度

| 维度 | 问题 |
| --- | --- |
| 准入 | Pod 创建前还是创建后等待？ |
| Gang | 不完整资源组是否会占用部分 GPU？ |
| 公平 | 长短任务、租户和优先级怎样共享？ |
| 抢占 | 谁被抢、损失多少、能否恢复？ |
| 拓扑 | 队列决策是否理解节点/机架/设备域？ |
| 弹性 | Pending/准入状态怎样驱动节点供给？ |
| 生态 | Trainer、JobSet、RayJob 等怎样接入？ |
| 运维 | 状态、事件、指标和升级是否清晰？ |

## 3. 结果记录

记录提交到准入、准入到 Running、完成时间、GPU 碎片、空转时间、抢占损失、队列公平偏差和控制器故障后的恢复。不要只比较 YAML 长度。

## 4. 组合场景

有些平台使用 Kueue 做配额准入，再由 kube-scheduler 或其他调度器完成 Pod 放置；也有平台使用 Volcano 独立承担批调度。若组合两者，必须验证 PodGroup、Suspend、Priority 和抢占的所有权，禁止两个控制器重复准入或恢复同一任务。

延伸阅读：[GPU 调度](../gpu-scheduling.md)、[队列与多租户](../queue-multitenancy.md)
