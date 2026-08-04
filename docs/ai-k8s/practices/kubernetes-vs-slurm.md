---
title: Kubernetes 还是 Slurm
description: 从训练、推理、拓扑、队列、生态和运维边界选择 AI 调度平台
status: stable
last_reviewed: 2026-08-04
---

# Kubernetes 还是 Slurm

Slurm 不是“旧时代方案”，Kubernetes 也不是所有 AI 工作负载的默认答案。选型应看主要工作负载和组织边界，而不是团队更熟悉哪个命令。

## 1. 核心差异

| 维度 | Kubernetes | Slurm |
| --- | --- | --- |
| 原生对象 | 服务、控制器、Pod、声明式 API | Batch Job、Partition、Reservation |
| 长项 | 在线服务、平台 API、Operator、云原生生态 | HPC 批任务、队列、拓扑和紧耦合调度 |
| 推理 | Deployment、Gateway、自动扩缩丰富 | 通常需另建服务层 |
| 训练 | 依赖 Kueue/Volcano/Trainer/JobSet | 批调度语义成熟 |
| 镜像 | OCI/CRI 原生 | 可结合容器运行时但模型不同 |
| 多租户 | Namespace、RBAC、Policy、Queue 组合 | Account/QOS/Partition 等体系 |
| 平台开发 | CRD/Controller 生态强 | 更偏作业和集群运维接口 |

## 2. 优先 Slurm 的情况

- 工作负载几乎都是大规模紧耦合训练和 HPC；
- 团队已有成熟 Partition、Reservation、拓扑、Accounting 和运维体系；
- 作业以批处理为主，在线推理由另一平台承担；
- 用户和软件栈已经围绕 Slurm 构建，迁移收益不明确。

## 3. 优先 Kubernetes 的情况

- 同一平台要承载 Notebook、Pipeline、训练、推理、RAG 和 Agent；
- 需要标准 API、Operator、GitOps、Gateway 和云服务集成；
- 平台希望用 Namespace/RBAC/Policy 暴露自助服务；
- 训练任务规模可由 Kueue/Volcano 和现有拓扑能力满足。

## 4. 混合不是免费

可以保留 Slurm 训练域，同时用 Kubernetes 承载开发、推理和控制面。但身份、数据、镜像、模型、作业状态、配额和成本必须有统一接口。不要让同一批 GPU 同时被两个调度器直接管理。

## 5. POC

用相同训练任务比较排队时间、启动时间、NCCL 性能、故障恢复、用户体验、审计、升级和单位训练成本；再增加一个在线推理服务，观察是否需要构建第二套平台。

延伸阅读：[分布式训练](../distributed-training.md)、[队列与多租户](../queue-multitenancy.md)、[落地路线图](../adoption-roadmap.md)

