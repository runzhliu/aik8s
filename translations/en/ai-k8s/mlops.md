---
title: "MLOps and Platform Engineering"
description: "Pipelines, experiments, model registry, GitOps, and internal platform APIs"
status: evolving
last_reviewed: 2026-08-02
---

# MLOps and Platform Engineering

Kubernetes can keep declared workloads running, but it does not automatically answer "which data and code produced this model," "who approved the release," or "whether quality has regressed." The job of MLOps is to close the loop among research processes, artifacts, deployment, and feedback into a traceable engineering system.

## 1. Recommended Responsibility Layering

```text
开发体验        Notebook / IDE / Python SDK / CLI
流程编排        Kubeflow Pipelines / Argo Workflows / Flyte
实验与治理      MLflow / Model Registry / Evaluation / Metadata
计算执行        Job / TrainJob / RayJob / JobSet
在线服务        KServe / Ray Serve / vLLM / Triton
持续交付        GitHub Actions / Argo CD / Flux
平台治理        RBAC / Kueue / Policy / Secrets / Cost
可观测性        Prometheus / DCGM / Logs / Traces / LLM Evaluation
```

The platform should provide stable interfaces and encapsulate tools into a small set of "golden paths," rather than letting each project assemble a dozen components on its own.

Notebooks are only responsible for interactive development and should not serve as the executor for long training jobs. For the complete design of JupyterHub, Kubeflow, GPU specifications, user home directories, model caches, and job handoff, see [GPU Notebook Platform and Storage Selection in the Large Model Era](development/gpu-notebook-platform.md).

## 2. Reproducibility Requires Six Versions

A single training run or inference should at minimum be associated with:

1. **Code version**: Git commit;
2. **Runtime environment**: container image digest, not a mutable tag;
3. **Data version**: object storage URI, Lakehouse snapshot, or dataset manifest;
4. **Configuration version**: parameters, resources, runtime, and queue policy;
5. **Model version**: weights, tokenizer, quantization, and adapters;
6. **Evaluation version**: evaluation set, scorer, prompt, and thresholds.

Having only the model file without the above associations usually makes reliable reproduction impossible and makes it impossible to explain discrepancies in production.

## 3. How to Choose a Pipeline

| Tool | Strengths | Suitable Teams |
| --- | --- | --- |
| Kubeflow Pipelines | ML components, caching, metadata, and Kubeflow experience integration | Data science teams already using Kubeflow |
| Argo Workflows | Kubernetes-native, general-purpose DAG, parallelism, and artifacts | Platform engineering teams that want to orchestrate data, training, and operations together |
| Flyte | Strongly typed inputs/outputs, versioned tasks, data awareness | Large ML/data teams and complex dependencies |
| Airflow | Rich scheduling ecosystem and data connectors | Teams with a mature Airflow data platform |
| Tekton / CI systems | Strong at build and delivery | Images, configuration, and releases; not recommended for orchestrating all training experiment pipelines |

Argo Workflows requires configuring an Artifact Repository; in production, S3-compatible object storage is typically used rather than passing large files between Pods or relying on long-lived PVCs.

References: [Argo Workflows](https://argoproj.github.io/argo-workflows/), [Artifact Repository](https://argoproj.github.io/argo-workflows/configure-artifact-repository/)

## 4. Experiment Tracking and Model Registry

MLflow Tracking records a Run's parameters, metrics, data references, and artifacts; the Model Registry handles model versions, aliases, tags, and promotion status. It is recommended to separate responsibilities:

- Object storage stores models, evaluation results, and large artifacts;
- A database such as PostgreSQL stores Run and Registry metadata;
- The MLflow Server provides the API/UI;
- Kubernetes Job UID, Workflow UID, and MLflow Run ID are written into each other's labels.

Model registration is not deployment. A clear status flow can be:

```text
Candidate → Offline Evaluated → Security Checked
          → Staging → Canary → Production → Retired
```

Promotion should produce an auditable deployment change in Git, applied to the cluster by a GitOps controller, rather than a Notebook directly modifying the production Deployment.

References: [MLflow Tracking](https://mlflow.org/docs/latest/ml/tracking/), [MLflow Model Registry](https://mlflow.org/docs/latest/ml/model-registry/workflow)

## 5. Boundaries Between CI, Pipeline, and GitOps

### CI

- Unit tests, static checks, and dependency vulnerability scanning;
- Build and sign container images;
- Generate SBOM;
- Run quick evaluations on base models, prompts, or configurations.

### ML Pipeline

- Data preparation, training, batch evaluation, and model artifact generation;
- May run for hours or days;
- Requires GPU queues, retries, checkpoints, and experiment metadata.

### GitOps

- Declares which model versions and configurations should run in production;
- Detects drift, performs synchronization and rollback;
- Is not responsible for training models itself.

Stuffing long-running training directly into ordinary CI runners, or giving training pipelines administrator privileges over the production cluster, are both common anti-patterns.

## 6. Multi-Tenancy Design

| Control Plane | Recommended Boundary |
| --- | --- |
| Identity | Enterprise IdP/OIDC mapped to Kubernetes users and groups |
| Namespace | Team or environment boundary; not recommended to create a permanent Namespace per Run |
| Compute quota | Kueue Queue/Quota manages GPUs; ResourceQuota manages regular resource objects |
| Network | Default-deny NetworkPolicy, allowing access only to data sources and platform services |
| Secrets | External Secrets / Vault / cloud identity; avoid long-lived static keys |
| Artifacts | Object storage bucket/prefix bound to tenant identity |
| Policy | Kyverno/Gatekeeper restricts privileges, HostPath, tags, resources, and image sources |
| Cost | Unified labels for Namespace, Queue, Team, Run, and Model |

Note that a Namespace is not a complete security sandbox. Users who can run arbitrary training code may access node kernels, device drivers, and shared networks, so Pod Security, Seccomp, least-privilege ServiceAccounts, and controlled RuntimeClasses must also be used.

## 7. Three Layers of Observability

### 1. Infrastructure Layer

- Node, CPU, memory, disk, network;
- GPU SM, GPU memory, power, temperature, XID;
- Device Plugin/DRA driver, Kueue, Scheduler, and Autoscaler;
- Pod Pending, eviction, OOM, and restarts.

### 2. Workload Layer

- Training step time, loss, checkpoint, and rank status;
- Inference TTFT, TPOT, queue, token throughput, KV cache;
- Model loading, batching, errors, and timeouts.

### 3. Model and Business Layer

- Accuracy, recall, drift, and data quality;
- Prompts, tool calls, LLM traces, human feedback;
- Per-tenant success rate, tokens, cost, and business conversion.

Prometheus, Grafana, Loki, and OpenTelemetry handle system telemetry; MLflow/Phoenix/Langfuse and similar tools handle experiments, generative AI traces, or evaluation. Infrastructure health does not imply correct model output, and the two categories of alerts must not be conflated.

## 8. Evaluation Must Enter the Release Process

Common metrics for traditional models are Accuracy, F1, AUC, and calibration; LLMs additionally require:

- Task success rate and structured output validity rate;
- Groundedness, factuality, and citation correctness;
- Safety, bias, prompt injection, and data leakage testing;
- Tool calling success rate and side-effect control;
- Latency, tokens, cost, and model degradation strategy;
- Human feedback and the return of online failure samples.

The evaluation set, scorer, and judge model must all be versioned. If the judge model changes, scores cannot be directly compared with historical results. MLflow provides separate evaluation entry points for traditional ML and GenAI; the evaluation objects and metric semantics of the two categories should be clearly distinguished.

References: [MLflow Evaluation](https://mlflow.org/docs/latest/ml/evaluation), [MLflow LLM and Agent Capabilities](https://www.mlflow.org/docs/latest/)

## 9. What a Platform API Should Look Like

A good platform interface exposes only the fields users actually need:

```yaml
kind: AIWorkload
spec:
  type: training
  runtime: pytorch-fsdp
  image: registry.example.com/team/model@sha256:...
  dataset: s3://datasets/example/manifest-v12.json
  resources:
    workers: 4
    gpuPerWorker: 8
    flavor: h100-80g
  queue: research
  checkpoint: s3://checkpoints/project-a/
  experiment: churn-model
```

The platform then translates this into TrainJob, Kueue Workload, NetworkPolicy, ServiceAccount, and monitoring rules. This example is an interface design idea, not a suggestion to invent another unbounded large CRD; if existing TrainJob/RayJob already meets the requirements, prefer providing templates and SDKs directly.

## 10. Maturity Ladder

| Level | Characteristics | Next Step |
| --- | --- | --- |
| L0: Manual execution | `kubectl apply`, local logs, manual model copying | Containerization, experiment tracking, and basic monitoring |
| L1: Repeatable | Pipeline, MLflow, object storage, fixed images | Registry approval and GitOps |
| L2: Governable | Multi-tenancy, queues, policies, canary, cost attribution | Automated evaluation and failure drills |
| L3: Self-service platform | Golden paths, SDK, runtime catalog, SLO | Capacity prediction, cross-cluster, and automated optimization |
| L4: Closed-loop optimization | Online feedback, automated evaluation, policy-based release, and joint cost-performance optimization | Continuous auditing and complexity reduction |

Maturity is not the number of installed components, but whether a single change can be reproduced, explained, approved, observed, and rolled back.

## 11. Production Checklist

- [ ] Code, image, data, configuration, model, and evaluation all have immutable versions.
- [ ] Workflow, Kubernetes Job, MLflow Run, and model version can be traced to each other.
- [ ] Long-running training does not depend on the CI runner lifecycle.
- [ ] Notebooks have no permission to directly modify production services.
- [ ] Model promotion is completed through Git changes and approval.
- [ ] Tenant identity, network, secrets, quotas, and artifact permissions are isolated from each other.
- [ ] Infrastructure, workload, and model quality metrics each have an owner.
- [ ] Online failure samples can be safely returned to the evaluation set.
- [ ] Cleanup policies cover Pods, workflows, models, artifacts, logs, and metrics.
- [ ] Every critical component has an upgrade, backup, and rollback runbook.
