---
title: "AI on Kubernetes Implementation Roadmap"
description: "From current-state assessment to 30-, 60-, and 90-day build plans and long-term capability evolution"
status: stable
last_reviewed: 2026-08-02
---

# AI on K8s Implementation Roadmap

The best starting point for the technology stack is not "install full Kubeflow," but rather answering questions about workloads, scale, tenants, and operational capability first. Below is an implementation route that can be expanded incrementally.

## 1. Answer Ten Questions First

1. Is the primary focus training, batch inference, or online inference?
2. Traditional ML, CV, multimodal, or LLM?
3. Can it run on a single machine, or must it run across multiple machines and multiple GPUs?
4. How many GPUs are needed at peak and at steady state, respectively?
5. Are GPU models heterogeneous? Is there a MIG/sharing requirement?
6. How many teams share the cluster? Are priorities, borrowing, and preemption needed?
7. Where do data and models currently reside, and what are the throughput and cold-start numbers?
8. What SLO, compliance, audit, and data isolation requirements exist?
9. Are teams more familiar with Kubernetes, Ray, or the existing data platform?
10. Which capabilities can be purchased as managed services, and which must be self-hosted?

If these questions have no answers, the more detailed the tool comparison, the more likely the selection will drift away from real needs.

## 2. When You Should NOT Use Kubernetes

In the following situations, you can start with single-machine Docker, managed notebooks, cloud vendor training services, or simple VMs:

- Only one or two fixed GPUs, with no multi-tenancy or high-availability requirements;
- Workloads are sporadic, and manual startup is already sufficient;
- The team has no Kubernetes operational capability and no platform team;
- The primary activity is calling external model APIs, and self-hosted inference is not a core capability;
- Data cannot enter the cluster efficiently, and migration costs far outweigh scheduling benefits;
- Models are still in the exploration phase, with interfaces and dependencies changing daily.

The value of Kubernetes comes from standardization, large-scale sharing, and automation. Without these needs, it only adds control-plane and troubleshooting costs.

## 3. Choose a Starting Stack by Scale

### Small: 1–8 GPUs, one team

```text
托管 Kubernetes 或 K3s
+ GPU Operator
+ Job / Deployment
+ MLflow
+ 对象存储
+ Prometheus / Grafana / DCGM
```

- Start training with native Jobs or framework launchers;
- Start inference with Deployment + vLLM/Triton;
- Build images using Helm/Kustomize and CI;
- Do not introduce dedicated queues or full Kubeflow yet.

### Medium: 8–128 GPUs, multiple teams

```text
Kubernetes + GPU Operator
+ Kueue
+ Kubeflow Trainer 或 KubeRay
+ Argo Workflows / KFP
+ MLflow + Model Registry
+ KServe
+ Argo CD
+ 统一监控、日志和策略
```

- Establish ResourceFlavor, team quotas, and priorities;
- Training jobs must be gang-scheduled and support Checkpoints;
- Models are published via Registry + GitOps;
- Establish node pool boundaries for development, training, and online inference.

### Large: Hundreds of GPUs or more, multi-cluster

On top of the medium stack, add:

- Topology-Aware Scheduling, JobSet/LWS;
- MultiKueue or other multi-cluster scheduling;
- DRA with device-level health/partition management;
- Inference Gateway, llm-d, or equivalent intelligent routing;
- RDMA, Local NVMe Cache, distributed object/file storage;
- Capacity forecasting, chargeback, automated fault isolation, and performance benchmarking platforms.

As scale grows, the most important thing is to reduce "special exceptions," not to keep adding tools.

## 4. 30/60/90-Day Implementation Plan

### Days 1–30: Establish a Measurable Baseline

- Inventory models, data, GPUs, network, and the current release process;
- Pin down the Kubernetes, driver, GPU Operator, and framework version matrix;
- Stand up one non-production GPU node pool;
- Run single-GPU and multi-GPU benchmarks; save throughput, latency, GPU memory, and cost;
- Deploy Prometheus, Grafana, DCGM Exporter, and centralized logging;
- Store models and Artifacts using object storage;
- Select one training or inference workload as the Pilot.

**Acceptance result**: Any Pilot run can locate its image, configuration, logs, GPU metrics, and output artifacts.

### Days 31–60: Establish Repeatable Delivery

- Use Argo Workflows/KFP to wrap data, training, and evaluation;
- Introduce MLflow to associate code, data, Runs, models, and evaluations;
- Introduce Kueue; configure Queues, Quota, and ResourceFlavor for teams;
- Choose Kubeflow Trainer or KubeRay to form a set of Runtime templates;
- Serve models with KServe or a standardized Helm Chart;
- Manage production configuration with Argo CD/Flux;
- Validate Checkpoint, preemption, Pod/node failures, and rollback.

**Acceptance result**: The same Git Commit and data version can repeatedly produce similar results, and model releases no longer depend on an individual's personal machine.

### Days 61–90: Establish Multi-Tenancy and SLOs

- Integrate enterprise OIDC, least-privilege RBAC, and default-deny NetworkPolicy;
- Establish image signing, policy validation, Secret management, and auditing;
- Define SLOs for training: queueing time, success rate, and recovery;
- Define SLOs for inference: availability, TTFT, TPOT, P99, and rejection rate;
- Run Canary, capacity stress tests, and failure drills;
- Build reports for GPU utilization, queue wait time, model cost, and team ownership;
- Extend the Pilot's golden path to a second team and verify reusability.

**Acceptance result**: The platform can safely serve multiple teams and can explain a single failure, a single release, and a single GPU cost.

## 5. Recommended Minimal Platform Interface

The platform should provide at least four types of self-service entry points:

| Entry point | User provides | Platform is responsible for |
| --- | --- | --- |
| Training job | Code/image, data, resources, hyperparameters | Queue, runtime, logs, metrics, Checkpoint |
| Batch inference | Model, input, output location | Sharding, retries, resources, and result manifest |
| Online service | Model version, Runtime, SLO | Networking, elasticity, Canary, certificates, and monitoring |
| Experiments and models | Run, metrics, Artifact, evaluation | Metadata, permissions, registry, retention, and auditing |

The interface can be CRDs, a Python SDK, a CLI, or a portal, but it should ultimately produce auditable Kubernetes and Git declarations.

## 6. Capacity Planning Approach

### Training

```text
单次训练成本 ≈ GPU 数 × 训练小时 × GPU 小时单价
有效训练效率 ≈ 实际训练计算时间 / GPU 分配总时间
```

Queueing, data preparation, Checkpoint, failed reruns, and idle GPU occupancy must all be accounted for. Simply raising SM utilization does not necessarily shorten Time-to-Model.

### Inference

```text
单位成本 = 总 GPU 成本 / 成功输出 Token
安全容量 = 满足目标 P99 时的最大稳定 Token Throughput
```

Capacity testing should cover at least: common requests, long context, burst concurrency, mixed models, cache cold/hot states, and single-instance failure.

### Reservation

It is recommended to divide GPU capacity into:

- Baseline capacity for online services;
- Preemptible capacity for batch jobs and training;
- Reserve for failures and upgrades;
- Temporary peak or Spot capacity.

Do not wait until all GPUs reach 100% allocation before considering high availability; online inference should be able to withstand the loss of at least one failure domain.

## 7. Key SLOs

| Scenario | Recommended SLI |
| --- | --- |
| Training platform | Queue P50/P95, startup success rate, Job success rate, Checkpoint recovery rate |
| GPU infrastructure | Allocatable rate, XID, node repair time, Driver/Plugin availability |
| Online inference | Availability, TTFT, TPOT, P99, Token Throughput, rejection rate |
| MLOps | Pipeline success rate, reproducibility rate, release lead time, rollback time |
| Governance | Unattributed cost, policy violations, expired Secrets, number of untraceable models |

Every SLO must have an Owner, alerts, a Runbook, and a review mechanism; a Dashboard alone without a response process does not count as operable.

## 8. Versioning and Upgrade Strategy

- Platform components use pinned versions and do not follow `latest`.
- Maintain the Kubernetes → GPU Operator → Driver → CUDA → Framework → Runtime compatibility matrix.
- Upgrade the non-production node pool first, then run training and inference benchmarks.
- Use rolling node replacement; validate drain, Checkpoint, and PodDisruptionBudget in advance.
- Back up objects before CRD upgrades and read the conversion/deprecation notes.
- Fast-evolving APIs such as KServe LLMInferenceService and DRA require dedicated migration tests.
- Model service upgrades must also validate output quality, not just Pod Ready status.

## 9. Common Failure Paths

1. **Install the full platform first, then look for users**: The result is a collection of unmaintained components.
2. **All workloads share one GPU node pool**: Development notebooks, training, and online services interfere with each other.
3. **Billing only by requested GPU count**: Long-term idle occupancy and inefficient jobs go undetected.
4. **Putting models into oversized images**: Build, distribution, and rollback become extremely slow.
5. **No immutable data versions**: Experiment metrics cannot be reproduced.
6. **No real failure drills**: Checkpoint, preemption, and rollback exist only in documentation.
7. **Chasing full utilization at the expense of SLOs**: Inference tail latency and training failure rates deteriorate.
8. **Every team picks its own full toolset**: The platform cannot unify upgrades, security, and observability.

## 10. Final Acceptance Checklist

- [ ] A new user can submit the first governed training or inference job within one day.
- [ ] The platform can explain why a job is Pending, failed, or preempted.
- [ ] Any model can be traced back to code, data, image, configuration, and evaluation.
- [ ] GPU failures and node maintenance do not cause unrecoverable data or model loss.
- [ ] Production releases support Shadow/Canary, automatic metric-based judgment, and fast rollback.
- [ ] Each tenant's identity, network, Secret, resource, and cost boundaries are clear.
- [ ] Key SLOs have alerts and exercised Runbooks.
- [ ] Platform upgrades have a compatibility matrix, benchmarks, canary rollout, and rollback plan.
- [ ] The number of components matches the current scale; no systems are stacked in advance based on future assumptions.
- [ ] A second team has successfully reused the same golden path.
