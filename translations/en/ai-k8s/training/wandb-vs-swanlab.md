---
title: "From W&B Local to SwanLab: Two Years of Team Experiment Tracking Practice and Tool Selection"
description: "Starting from a W&B Local instance that ran for two years, combined with real SFT testing on SwanLab, this article explains why experiment tracking is hard to productionize, and how teams should evaluate and accept such tools"
status: evolving
last_reviewed: 2026-08-26
---

# From W&B Local to SwanLab: Two Years of Team Experiment Tracking Practice and Tool Selection

When I first started building the large model platform, I ran into a very real contradiction.

On one hand, the production environment did not allow users to send training traces, metrics, logs, and model-related data directly to the public internet; on the other hand, a large number of open-source models, training frameworks, and tutorials default to integrating with W&B, and algorithm engineers had high demand for and recognition of it.

We could neither simply open up public network access nor ask users to abandon tools they were already familiar with. That left only one path: privately deploy W&B Local inside the internal environment.

I later ran it as a single-replica StatefulSet, and successively connected training tasks for OPT, Baichuan/Megatron, YOLO, and medical imaging. This instance went through license updates, database externalization, object storage expansion, offline catch-up uploads, and data migration, and finally ran stably for two years before being decommissioned.

Recently, when doing large model SFT again, I deployed and tested SwanLab on Kubernetes. Looking back and comparing the two experiences, I found that what is truly worth discussing is not whose curves look prettier, but three more practical questions:

1. Why does an experiment tracking system so easily evolve from a "small tool" into production infrastructure?
2. What problems are W&B and SwanLab each best suited to solve?
3. If I were to choose again today, how can I avoid stepping into the same old pitfalls?

Let me state my conclusion first: **For current large model SFT work, viewing training curves, and comparing runs, I will continue using SwanLab; if I need datasets, checkpoints, model lineage, Registry, automated hyperparameter tuning, and enterprise permission governance, W&B's ecosystem is still more complete. Whichever you choose, you must evaluate the database, object storage, backup and recovery, licensing, and exit strategy together.**

## Why Users Strongly Needed W&B

At the time, many open-source projects had already made W&B the default experiment tracking tool. After users ran training scripts following community documentation, they naturally hoped the internal platform would also show the same Projects, Runs, and curves. The W&B product itself was also fairly mature—algorithm engineers did not need to relearn a completely different way of working.

The questions they cared about were very specific:

- How does this training run's Loss compare to the last one?
- Are Learning Rate, Grad Norm, and training speed normal?
- Which set of hyperparameters performed best?
- After a network interruption, can the curves be caught back up?
- Months later, can I still find the configuration and results from back then?

TensorBoard can show curves from a single log directory, but when training is scattered across different machines, directories, and users, project management, run comparison, and long-term retrieval become increasingly troublesome.

This left me with my first judgment:

> As soon as a tool starts centrally storing the entire team's training history, it is no longer just a visualization page—it becomes the data system of the training platform.

## One License, One StatefulSet, Holding the Line on Requirements

I had contacted W&B sales and seriously looked into formal procurement. But the license at the time was genuinely very expensive—not a cost most teams could easily bear. Back then, AI had not yet received the attention it gets today, and the company found it hard to allocate such a high budget for a training auxiliary tool.

To meet user needs first, I deployed a single-replica StatefulSet version of W&B Local using a valid personal or trial license. Looking back, this approach was admittedly "rough": there was no formal commercial support and no strict production SLA, but it solved the two most urgent problems:

- Training data did not need to leave the production environment;
- Users could continue using the W&B SDK and workflows they were familiar with from the community.

The real trouble started when the number of users grew. When one person uses it, an instance restart may not matter much; but when many users continuously write metrics, traces, and files, capacity, migration, recovery, and upgrades all become platform-level problems.

This is also a point easily overlooked during tool selection: **A license is not just a procurement issue—it also affects whether the service can be upgraded, whether data can be retained long-term, and whether the platform has a clear exit path.**

## W&B Local Looks Like a Container, But Is Actually a System

On the surface, W&B Local is a Docker image that can be started by running `wandb server start`. After I went inside the container to analyze it, I discovered it is actually a typical fat container—it contains not only the web service, but also Redis, MinIO, MySQL-related logic, Nginx, background jobs, and a large number of initialization and migration scripts.

The relationship at the time can be simplified as follows:

```text
训练任务 / W&B SDK
        |
        v
W&B Local 富容器
  ├─ Web / API / 后台任务
  ├─ MySQL：项目、Run、用户和指标元数据
  ├─ MinIO：日志、媒体、模型与其他文件
  └─ Redis：缓存和内部状态
```

Therefore, backing up only the database does not guarantee that Runs can be recovered. MySQL may still have records, but if the MinIO files are incomplete, the frontend still cannot open historical data; conversely, saving only the object files cannot restore the relationships between projects, users, and metrics.

A conclusion that applies to any experiment tracking system today is:

> The metadata database, time-series metrics, and object files must be designed for backup and recovery as a single piece of business data—three teams each "backing up their own part" is not acceptable.

## Object Storage Is Not Just Changing an Address

We already had company-level object storage at the time, and I tried to replace the built-in MinIO. I originally thought it would be enough to modify the S3 endpoint, but it was not that simple in practice.

The older version of W&B still depended on an intermediate component like a Gateway, and involved S3 protocol and signature compatibility. The fact that internal object storage provides an S3 API does not mean it is fully compatible with every request, signature, and directory semantic the application uses. After a round of tinkering, I still could not reliably replace it and had to give up.

Since MinIO could not be swapped out for the time being, I sorted out the directories inside the fat container that needed to be persisted, and then used RBD, CephFS, and similar storage to provide persistence and online expansion. After many users shared a single instance, metrics, traces, and uploaded files grew quickly; without capacity monitoring, MySQL and MinIO could easily fill up.

This pitfall can be distilled into a very practical acceptance requirement:

> Object storage compatibility must be verified with real uploads, queries, offline catch-up uploads, deletions, and recovery. Seeing the words "S3-compatible" is not enough.

## The Database Was Ultimately Handed to a Professional System

The database part ended up being done more thoroughly. After a round of troubleshooting around initialization, migration permissions, and table structures, we connected MySQL to the company-level database service, with professional DBA colleagues handling backup, capacity, and stability. MinIO stayed on the instance side for the time being, while MySQL was decoupled from the fat container.

The value of this step was not "using a more advanced database," but straightening out the responsibility boundaries:

- The application team focuses on the W&B version, interfaces, and user experience;
- The database team is responsible for high availability, backup, recovery, and capacity;
- The storage team provides reliable volumes and expansion capability;
- The platform team handles Kubernetes, monitoring, and change processes.

The worst thing about a self-hosted platform is when all components "can run," but no team is accountable for recovery results.

## License Renewals Must Not Lose Historical Data

Early self-hosted personal or trial licenses were only valid for a few months. If the instance were rebuilt every time the license expired, users, projects, and historical Runs would be in a very difficult position.

At the time, by analyzing the relationships between container logs, the database, MinIO, and the startup process, I worked out a procedure for updating the license after obtaining a new valid one while preserving the existing data. I will not disclose the license file location, tokens, or specific operation steps here—the key point is that license renewal should not force the data system to start from zero.

This approach was not elegant, but it genuinely ran stably for two years under heavy user load, continuous data growth, and no formal commercial support. Looking back now, I think this experience was quite valuable: I did not just install the software—I took apart a closed-source fat container piece by piece, and then leveraged existing Kubernetes, storage, and database capabilities to keep it running long-term.

I sometimes wonder whether I might be the first person in China to privatize W&B Local and then actually maintain it for the whole team for a year or two. However, internal enterprise practices are hard to establish as a complete timeline, so a safer statement for a public article is:

> I may be among the earlier engineers in China to privatize W&B Local and truly operate and maintain it for a team for one to two years.

One thing should be clarified: these experiences mainly come from the older all-in-one `wandb/local` image. W&B Self-Managed now recommends deployment via the Kubernetes Operator, and the problems encountered with the old version cannot be directly mapped onto the current product. The current architecture still requires Kubernetes, MySQL, Redis, S3-compatible object storage, and a valid Server License, but component management and upgrade methods have changed.

References: [W&B Self-Managed Infrastructure Requirements](https://docs.wandb.ai/platform/hosting/self-managed/requirements), [W&B Kubernetes Operator](https://docs.wandb.ai/platform/hosting/self-managed/operator)

## Why I Chose SwanLab This Time

For this SFT work, I wanted a page that is better suited for multi-user use than TensorBoard and easy to integrate with Chinese large model training frameworks:

- ms-swift can report directly;
- Can view Train Loss, Validation Loss, Learning Rate, and Grad Norm;
- Can compare multiple experiments side by side;
- Chinese interface and documentation that are friendly enough;
- Can be deployed in our own environment.

SwanLab basically meets these requirements. By adding `--report_to swanlab`, a Project name, and an experiment name to the training command, numeric metrics can be written in. Official integrations also cover Transformers, PyTorch, LLaMA-Factory, Ultralytics, and other frameworks, and support NVIDIA GPUs and multiple domestic accelerators.

References: [SwanLab Features and Integrations](https://docs.swanlab.cn/guide_cloud/general/what-is-swanlab.html), [SwanLab Experiment Results Page](https://docs.swanlab.cn/guide_cloud/experiment_track/view-result.html)

## I Did Not Just Run a Smoke Test on SwanLab

This time I verified SwanLab with real training runs:

| Experiment | Scale | SwanLab Verification Content |
| --- | --- | --- |
| Qwen3.5-4B LoRA | Single L20, 120 Steps | Training and validation curves, 110 Base/Adapter blind tests |
| Qwen3.6-35B-A3B LoRA | 8 × L20 | Multi-GPU training, four validations, Run completed normally |
| DeepSeek V4 Flash MoE | 8 × H20, EP=8 | Training metrics, validation, and checkpoints |
| DeepSeek V4 TCP/RDMA | Dual-node 16 GPUs, six Runs | Same-project experiment comparison, Loss and Step Time |
| DeepSeek V4 convergence experiment | Dual-node 16 GPUs, 60 Steps | Discovered Validation Loss rising again after Step 30 |

![Six DeepSeek V4 TCP/RDMA experiments in SwanLab](../../assets/training/deepseek-v4-rdma/swanlab-runs.png)

The last result was very meaningful to me. If you only look at Train Loss, you would think Step 60 is better; Validation Loss, however, shows that the optimal point was reached around Step 30, and continuing to train starts overfitting. Experiment tracking finally became more than "leaving a chart after training ends"—it actually influenced early stopping and checkpoint selection.

SwanLab also has clear boundaries. A faster Step Time on the page does not prove that training actually used RDMA; the communication path still needs to be verified through NCCL's `NET/Socket`, `NET/IB`, and `GDRDMA` logs as well as NIC counters. SwanLab handles Runs and training metrics; Prometheus, DCGM Exporter, and Grafana handle GPUs, nodes, and network. The two types of data need to be aligned using the same Run ID.

Full test results: [SwanLab Self-Hosting and Real SFT Metrics](swanlab-self-hosted.md), [DeepSeek V4 Dual-Node RDMA Training Test](rdma-distributed-training-benchmark.md)

## How to Choose Between W&B and SwanLab

The comparison below only covers the parts I actually cared about and verified; it does not represent the full feature set of any commercial version.

| Question | W&B | SwanLab | My Recommendation |
| --- | --- | --- | --- |
| Training curves and hyperparameters | Workspace, filtering, grouping, and panels are mature | Tables and multi-experiment curves are more direct | Both are sufficient for routine SFT |
| Chinese LLM frameworks | General ecosystem is mature | ms-swift and LLaMA-Factory integration is convenient | For domestic LLM training, try SwanLab first |
| Model and data artifacts | Artifacts, Registry, versioning, and lineage are complete | File storage capability is still maturing; I have not verified the same level of closed loop | For asset governance, prefer W&B |
| Automated hyperparameter tuning | Sweeps and Launch ecosystem are mature | Not the focus of this verification | For large-scale HPO, prefer W&B |
| Reporting and collaboration | Reports, Tables, programmable Workspace, and permissions are mature | Daily comparison and sharing are lighter weight | For formal research reports, lean toward W&B |
| Offline catch-up uploads | `wandb offline/sync`—I actually used this | Supports Offline and `swanlab sync` | Both need offline recovery testing |
| Private deployment | Operator + MySQL + Redis + S3 | Helm + PostgreSQL + Redis + ClickHouse + Vector + S3 | Neither is lightweight in production |
| Enterprise governance | License, SSO, service accounts, and audit systems are complete | Needs further evaluation based on team size and version | Run a separate PoC for compliance scenarios |

W&B's advantage is not just a Loss curve. It can connect Runs, datasets, checkpoints, model versions, Registry, reports, and automation. SwanLab's current feel to me is that it focuses first on doing training experiments well, quickly centralizing curves, parameters, logs, and environment.

References: [W&B Project Capabilities](https://docs.wandb.ai/models/track/project-page), [W&B Registry](https://docs.wandb.ai/models/registry/create_collection), [W&B Launch Sweeps](https://docs.wandb.ai/platform/launch/sweeps-on-launch)

## SwanLab Self-Hosting Is Also Not a Small Container

SwanLab's training integration is lightweight, but its Kubernetes version likewise includes Gateway, Frontend, Server, Auth, House, PostgreSQL, Redis, ClickHouse, Vector, and S3-compatible object storage.

So I now separate "ease of integration" from "ease of operations":

- Developer integration: SwanLab is indeed relatively lightweight;
- Short-term PoC: you can see a page quickly;
- Team production: database, object storage, backup, upgrades, capacity, and high availability—none of these go away.

The component names may differ, but the production operations problems do not disappear on their own.

Reference: [SwanLab Kubernetes Deployment](https://docs.swanlab.cn/self_host/kubernetes/deploy.html)

## Migrating from W&B to SwanLab Cannot Be Just Moving a Loss Curve

SwanLab supports live code conversion from W&B, and can also convert historical data from W&B Server and local Runs. However, the current official documentation mainly supports scalar charts; you should not expect Artifacts, media, Reports, permissions, and full lineage to be automatically migrated.

I would first pick two or three projects for migration rehearsal:

1. Read-only archive of the original W&B Run directories;
2. Convert scalar metrics, verifying Step counts, endpoints, extrema, and Summary;
3. Export media and files separately, verifying by count, size, and Hash;
4. Re-register Base Model, Adapter, dataset Hash, Git Commit, and evaluation results;
5. After confirming the new and old pages match the original data, gradually expand the scope.

The SwanLab SDK `0.8.0` also changed the local log format, so old and new logs cannot be mixed directly. Therefore, the training image must pin the SDK version, and a real "offline training—network recovery—offline catch-up upload—page verification" run must be performed.

References: [SwanLab Converting W&B Data](https://docs.swanlab.cn/guide_cloud/integration/integration-wandb.html), [SwanLab Offline Sync](https://docs.swanlab.cn/guide_cloud/experiment_track/sync-logfile.html)

## Before an Experiment Tracking Platform Goes Live, Verify at Least These Items

Regardless of whether the final choice is W&B, SwanLab, or another product, I now check all of the following:

- [ ] Real training can continuously report scalars, logs, and media, not just a random-number demo;
- [ ] Multiple Runs of the same project can be compared by parameters, tags, and metrics;
- [ ] Network interruptions do not cripple training, and offline re-upload is possible after recovery;
- [ ] Database, metric storage, and object files have a consistent backup and recovery plan;
- [ ] Pod recreation, database recovery, and object storage recovery have actually been executed;
- [ ] There is a capacity model: number of Runs, metric frequency, metric cardinality, media size, and retention time;
- [ ] SDK and server versions are pinned, with upgrade regression test cases;
- [ ] License, user scale, feature limitations, and expiration handling are clearly defined;
- [ ] The platform can export data, with a migration and exit plan for decommissioning;
- [ ] Training metrics can be aligned with GPU, node, and network monitoring via Run ID.

If these questions have no answers, the fact that the page opens now does not mean it is ready for long-term team use.

## If I had to choose again now

My current combination would be:

```text
ms-swift / PyTorch
  -> SwanLab：Run、超参数、Loss、Validation、实验比较
  -> 对象存储：Checkpoint、Adapter、数据集与预测文件

Kubernetes / GPU / NIC / RDMA
  -> Prometheus + DCGM Exporter + Grafana：基础设施与通信监控
```

I am currently mainly doing Qwen and DeepSeek SFT and multi-machine training experiments. SwanLab is sufficient, and the integration cost is relatively low.

If the following needs arise in the future, I will formally re-evaluate W&B:

- Full lineage is required for datasets, checkpoints, and model versions;
- Registry, approval, aliases, auditing, and automation are needed;
- Sweeps, Launch, and large-scale hyperparameter search are needed;
- SSO, service accounts, multi-team permissions, and compliance become hard requirements;
- The team can accept formal licensing and operations support costs.

I will not simply conclude that SwanLab is better than W&B, or that W&B is necessarily stronger than SwanLab. For my current training experiments, SwanLab is more suitable; for a complete enterprise MLOps system, W&B is still worth serious evaluation.

What should really be avoided is making a decision based only on a demo page. Once an experiment tracking system becomes the team's training history entry point, it must be treated as seriously as a database or object storage.
