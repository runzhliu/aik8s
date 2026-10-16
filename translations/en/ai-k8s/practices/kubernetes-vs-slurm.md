---
title: "Kubernetes or Slurm"
description: "Choosing an AI scheduling platform based on training, inference, topology, queues, ecosystem, and operational boundaries"
status: stable
last_reviewed: 2026-08-04
---

# Kubernetes or Slurm

Slurm is not a "legacy solution," and Kubernetes is not the default answer for all AI workloads. The choice should be based on the primary workloads and organizational boundaries, not on which command the team is more familiar with.

## 1. Core Differences

| Dimension | Kubernetes | Slurm |
| --- | --- | --- |
| Native objects | Services, controllers, Pods, declarative API | Batch jobs, partitions, reservations |
| Strengths | Online services, platform APIs, Operators, cloud-native ecosystem | HPC batch jobs, queues, topology, and tightly coupled scheduling |
| Inference | Rich Deployment, Gateway, and autoscaling | Usually requires a separate service layer |
| Training | Relies on Kueue/Volcano/Trainer/JobSet | Mature batch scheduling semantics |
| Images | Native OCI/CRI | Can integrate with container runtimes but with a different model |
| Multi-tenancy | Combination of Namespace, RBAC, Policy, Queue | Account/QOS/Partition systems |
| Platform development | Strong CRD/Controller ecosystem | More oriented toward job and cluster operations interfaces |

## 2. Prefer Slurm When

- Workloads are almost entirely large-scale tightly coupled training and HPC;
- The team already has mature Partition, Reservation, topology, Accounting, and operations systems;
- Jobs are primarily batch processing, with online inference handled by another platform;
- Users and the software stack are already built around Slurm, and the migration benefits are unclear.

## 3. Prefer Kubernetes When

- The same platform must host Notebooks, Pipelines, training, inference, RAG, and Agents;
- Standard APIs, Operators, GitOps, Gateways, and cloud service integration are required;
- The platform wants to expose self-service through Namespace/RBAC/Policy;
- Training job scale can be satisfied by Kueue/Volcano and existing topology capabilities.

## 4. Hybrid Is Not Free

You can keep the Slurm training domain while using Kubernetes for development, inference, and the control plane. But identity, data, images, models, job state, quotas, and cost must have unified interfaces. Do not let the same set of GPUs be directly managed by two schedulers at the same time.

## 5. POC

Use the same training job to compare queue time, startup time, NCCL performance, failure recovery, user experience, auditing, upgrades, and per-unit training cost; then add an online inference service to see whether a second platform needs to be built.

Further reading: [Distributed training](../distributed-training.md), [Queues and multi-tenancy](../queue-multitenancy.md), [Implementation roadmap](../adoption-roadmap.md)
