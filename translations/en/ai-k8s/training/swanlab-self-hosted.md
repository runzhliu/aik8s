---
title: "SwanLab Self-Hosting: From Kubernetes Deployment to Real SFT Metrics"
description: "Deploy SwanLab on Kubernetes, integrate ms-swift, distinguish experiment tracking from infrastructure monitoring, and validate the metrics pipeline and overfitting inflection points with real SFT runs on Qwen3.5, Qwen3.6 MoE, and DeepSeek V4"
status: evolving
last_reviewed: 2026-08-25
---

# SwanLab Self-Hosting: From Kubernetes Deployment to Real SFT Metrics

Writing training logs into TensorBoard only solves the problem of "where to view the curves." Once a multi-user shared training platform is in place, you also need projects, Runs, hyperparameters, tags, experiment comparison, permissions, and long-term retrieval. SwanLab can take on this experiment-tracking layer, but it does not replace Prometheus, DCGM Exporter, and Grafana.

If you want to evaluate selection, licensing, and migration boundaries from existing W&B usage experience, first read [From W&B Local to SwanLab: Two Years of Team Experiment Tracking Practice and Selection](wandb-vs-swanlab.md).

This article documents a publicly reusable Kubernetes deployment and ms-swift integration method, and validates the complete pipeline from training container to web curves using real LoRA SFT runs on `Qwen3.5-4B`, `Qwen3.6-35B-A3B`, and `DeepSeek V4 Flash`. It does not include internal cluster, image registry, storage endpoint, domain, or ingress configuration.

## 1. Define the System Boundary First

The SwanLab self-hosted edition is not a single container that only reads log directories. The official Kubernetes Chart includes Gateway, Frontend, Server, Auth, House, PostgreSQL, Redis, ClickHouse, Vector, and S3-compatible object storage.

```text
ms-swift / PyTorch
  -> SwanLab SDK -> Gateway
                    -> Server / Auth -> PostgreSQL
                    -> House / Vector -> ClickHouse
                    -> 媒体与制品 -> S3 兼容对象存储

Kubernetes / DCGM Exporter / NIC
  -> Prometheus -> Grafana
```

The two pipelines answer different questions:

| System | Primary Question Answered |
| --- | --- |
| SwanLab | Which Run, which hyperparameters, how Loss changes, what differences exist between experiments |
| Prometheus + Grafana | Whether GPU, GPU memory, power consumption, slow ranks, nodes, RDMA, and Kubernetes are healthy |

In production, use a unified `run_id`, `job_id`, model version, and Git commit to align both types of data.

## 2. Using the Official Helm Chart

First query the current Chart and application versions; do not blindly copy historical tags from articles over the long term:

```bash
helm repo add swanlab https://helm.swanlab.cn
helm repo update
helm search repo swanlab/self-hosted --versions
```

It is recommended to pull the Chart locally first, then complete Lint, rendering, and change review:

```bash
helm pull swanlab/self-hosted --untar --untardir ./charts
helm lint ./charts/self-hosted -f values.yaml --strict

helm upgrade --install swanlab-self-hosted ./charts/self-hosted \
  --namespace swanlab \
  --create-namespace \
  -f values.yaml \
  --dry-run
```

After confirming the images, resources, persistent volumes, Services, and security configuration in the rendered output, install:

```bash
helm upgrade --install swanlab-self-hosted ./charts/self-hosted \
  --namespace swanlab \
  --create-namespace \
  -f values.yaml
```

The editable public Values template is located at [`examples/llm-sft-lab/swanlab/values.example.yaml`](https://github.com/runzhliu/aik8s/blob/main/examples/llm-sft-lab/swanlab/values.example.yaml). The domain, StorageClass, capacity, and replica counts in it are only placeholders or starting points and must be modified according to the actual environment.

In restricted network environments, sync the official fixed-tag images to a controlled Registry and record the source and destination Digests. Do not build same-name images ad hoc in the production cluster, and do not use drifting `latest`.

## 3. Temporary PoC Differs from Production Deployment

A short-term PoC can change PostgreSQL, Redis, ClickHouse, Vector, and object storage directories to `emptyDir` in an isolated environment. It is suitable for validating images, component dependencies, database migrations, pages, and SDK pipelines, but it must be clear: after Pods are replaced, accounts, experiments, and curves may all be lost.

Production deployment requires at least:

- Persistent PostgreSQL, ClickHouse, and object storage;
- Clear backup, recovery, RPO, RTO, and retention policies;
- HTTPS, authentication, access control, and Secret management;
- Resource Request/Limit, anti-affinity, and failure-domain planning;
- Capacity estimation based on experiment count, scalar frequency, media files, and retention time;
- Validation of database migration and rollback paths before upgrades.

If the organization already has managed databases or object storage, evaluate externalizing stateful dependencies rather than running all components in the same Kubernetes cluster by default.

## 4. Ingress and First Activation

`global.settings.host` should be filled with the external URL users actually access. The ingress can be provided by the organization's existing Ingress, Gateway, or zero-trust access layer; this article does not cover enterprise-internal cross-cluster networking and domain implementation.

The community self-hosted edition enters `/activation` on first access. After completing instance activation and creating the primary account, generate a training-dedicated API Key on the settings page. Do not reuse the administrator password, and do not write the API Key into images, scripts, or Git.

Project-level login can be performed in the training working directory:

```bash
python -m pip install 'swanlab>=0.8,<1'
swanlab login --host https://swanlab.example.com --local
```

On shared hosts, avoid saving credentials to a Home directory shared by all users. Kubernetes Jobs are better suited for injection via Secrets:

```yaml
env:
  - name: SWANLAB_API_KEY
    valueFrom:
      secretKeyRef:
        name: swanlab-api-key
        key: api-key
```

The Secret should only hold sensitive Keys; API Host, Project, and Experiment Name use ordinary configuration, and restrict the ServiceAccount's Secret read scope.

## 5. Integrating ms-swift

ms-swift SFT uses `report_to`, Project, and Experiment Name to connect to SwanLab:

```bash
TRAIN_REPORT_TO=swanlab \
TRAIN_SWANLAB_PROJECT=llm-sft-lab \
TRAIN_SWANLAB_EXP_NAME=qwen35-4b-lora \
bash train.sh
```

The corresponding core parameters are:

```text
--report_to swanlab
--swanlab_project llm-sft-lab
--swanlab_exp_name qwen35-4b-lora
```

The repository provides two types of reproduction entry points:

- [`smoke.py`](https://github.com/runzhliu/aik8s/blob/main/examples/llm-sft-lab/swanlab/smoke.py): no GPU required; only validates the SDK, Gateway, storage, and Web;
- [`meaningful-sft`](https://github.com/runzhliu/aik8s/tree/main/examples/llm-sft-lab/meaningful-sft): runs a real LoRA and compares the isolated blind test between Base and Adapter.

A synthetic Smoke test can only prove the metrics pipeline works; it cannot serve as evidence of model training effectiveness.

## 6. Verified Kubernetes PoC

On August 21, 2026, a short-term PoC was completed using the official Chart `0.6.2`, SwanLab `v3.1.1`, and Kubernetes 1.30: 10 Deployments, 1 StatefulSet, and 1 initialization Job worked normally, all 11 resident Pods were Ready with no restarts; database migration, object storage Bucket initialization, Gateway pages, and API all passed.

After activation, the SwanLab SDK `0.8.4` built into the training image created a 6-Step synthetic Run and successfully uploaded 39 records of Loss, Learning Rate, and Tokens/s. This proved:

```text
训练容器 -> SDK -> Gateway -> 数据组件 -> Web
```

This PoC round used temporary volumes and does not mean data durability has passed production acceptance.

## 7. Real Qwen3.5-4B SFT Validation

On the same day, `Qwen3.5-4B + BF16 LoRA` was completed on a single L20: 330 training samples, 55 validation samples, 110 blind-test samples, 120 Steps taking 612.6 seconds, with the framework recording a peak GPU memory of 9.33 GiB. Validation Loss was lowest at Step 60, so the blind test used the Step 60 Adapter.

SwanLab can display Train Loss, Gradient Norm, Learning Rate, Token Accuracy, and four validation runs:

![Real training curves for Qwen3.5-4B](../../assets/training/qwen35-4b-sft/swanlab-train-curves.png)

![Real validation curves for Qwen3.5-4B](../../assets/training/qwen35-4b-sft/swanlab-eval-curves.png)

| 110 blind-test metrics | Base | Step 60 Adapter |
| --- | ---: | ---: |
| JSON validity rate | 99.1% | 100% |
| Custom fault-code accuracy | 0% | 77.3% |
| Fault-code Macro-F1 | 0% | 75.3% |
| Insufficient-information judgment accuracy | 51.8% | 100% |
| Forbidden-action keyword coverage | 5.5% | 88.2% |

Full training parameters, data hashes, and machine-readable results are in [Qwen3.5 small-scale SFT experiment](https://github.com/runzhliu/aik8s/tree/main/examples/llm-sft-lab/meaningful-sft). The Loss curve and blind test must be preserved together: the former describes the optimization process, while the latter answers whether model behavior actually improved.

A subsequent `Qwen3.6-35B-A3B + 8 × L20 + ZeRO-3 LoRA` round also completed 120 Steps and four validation runs; the Step 30/60/90/120 Validation Loss values saved by SwanLab were `0.34289/0.06315/0.06051/0.05915`, and the final-step Token Accuracy was `98.98%`. This proves that larger multi-GPU Runs can also continuously upload numeric metrics and properly enter the `FINISHED` state.

This round also exposed an experiment-lifecycle gap: model Checkpoints, Adapters, and prediction files all used temporary task directories without issue, but the final Base/Adapter summary also remained only on the local machine; after task cleanup, it could not be recovered. The correct approach is to upload a small set of numeric metrics and data hashes to SwanLab before exiting, while model weights and raw prediction text can remain non-persistent. The public results therefore only record training and validation, without inferring blind-test improvements. Machine-readable records are in [Qwen3.6-35B-A3B measured results](https://github.com/runzhliu/aik8s/blob/main/examples/llm-sft-lab/meaningful-sft/results/l20-qwen36-35b-a3b-20260821.json).

On August 24, 2026, a 20-Step LoRA run of `DeepSeek V4 Flash 0731 + 8 × H20 + EP=8` successfully uploaded 1797 SwanLab records. Train Loss dropped from `1.3384` at Step 1 to `0.2692` at Step 20; Validation Loss at Steps 5/10/15/20 was `0.9755/0.6041/0.4238/0.3469`, and all four Checkpoints were generated. This Run proves the experiment-tracking pipeline can cover full MoE Expert Parallel training, not just single-GPU Dense models.

![Real training and validation Loss for DeepSeek V4 Flash 0731](../../assets/training/deepseek-v4-flash-0731/loss-curves.svg)

This round also preserved the boundary: the curves come from real numeric records, but the 110-sample isolated Blind Test Base/Adapter A/B has not yet been completed, so it can only prove the training and validation optimization process, not claim task accuracy improvement. Machine-readable records are in [DeepSeek V4 Flash 0731 measured results](https://github.com/runzhliu/aik8s/blob/main/examples/llm-sft-lab/meaningful-sft/results/h20-deepseek-v4-flash-0731-20260824.json).

On August 25, 2026, SwanLab was also used for a two-node TCP/RDMA performance comparison: all six official Runs of `DeepSeek V4 Flash + PP=1 / EP=16 / Dense DP=16` completed reporting. The median of three stable-step means dropped from TCP `4.490` to RDMA `3.050 秒`, an equivalent throughput improvement of `47.23%`. The project comparison page simultaneously retains Loss, Gradient Norm, Learning Rate, MoE Load Balancing Loss, GPU memory, and cumulative Step Time, making it easy to confirm that optimization trajectories remain comparable across different Transports.

![Six DeepSeek V4 TCP/RDMA experiments in SwanLab](../../assets/training/deepseek-v4-rdma/swanlab-runs.png)

This figure also illustrates the boundary between SwanLab and network monitoring: it handles Run, parameter, and training-metric comparison, but cannot prove that the underlying traffic actually used RDMA. Transport is still accepted via the `NET/Socket`, `NET/IB`, and `GDRDMA` logs in NCCL INFO, while NIC counters and congestion are left to Prometheus/Grafana. Full positive/negative comparisons and raw data are in [DeepSeek V4 two-node RDMA training measured results](rdma-distributed-training-benchmark.md).

On the same day, an independent two-node 16-GPU, 60-Step DeepSeek V4 convergence Run was also completed. SwanLab normally recorded 8 columns of numeric metrics and ended with `FINISHED`; Validation Loss reached its lowest value of `0.04059` at Step 30, then rose again while Train Loss continued to decline, reaching `0.06463` at Step 60. This set of curves moved experiment tracking from "proving the SDK can report" to serving as a training decision basis: small-data SFT should select the best checkpoint by Validation or use early stopping, not default to the final step.

![DeepSeek V4 60-Step convergence curves](../../assets/training/deepseek-v4-rdma/convergence-validation.svg)

This round also showed that hyperparameters themselves must enter tracking: `eval_steps=10` and `save_steps=20` meant the best Step 30 had no corresponding Checkpoint. The next round should align validation and save intervals, and upload the Base/Adapter blind-test summary before the Run ends; curves alone are still insufficient to prove task accuracy improvement.

## 8. Compatibility Issues Found This Time

The SDK `0.8.4` in the training image has two differences from the newer documentation and ms-swift output:

1. `swanlab.login()` does not accept the `web_host` parameter from the newer documentation; integration code must follow the actual SDK signature inside the image.
2. ms-swift 4.4.1 reports display fields such as `30/120` and `3m 53s` as String Scalars, and SDK 0.8.4 rejects these strings.

The second issue does not affect numeric Loss, Accuracy, Learning Rate, Gradient Norm, training, Checkpoints, or blind tests, but compatibility errors will appear in the logs. When upgrading the SDK or training image, add these scenarios to regression testing rather than only checking `import swanlab`.

## 9. Acceptance Checklist

- All application and dependency Pods Ready, initialization Job succeeded;
- Database migration completed, Gateway homepage and API return expected status;
- A minimal Run can continuously write scalars and end normally;
- Two Runs in the same project can be compared for hyperparameters and curves;
- Real SFT simultaneously saves training curves, Validation, Checkpoints, and Base/Adapter blind tests;
- Model version, data hashes, training parameters, and machine-readable results are saved in addition to screenshots;
- Public screenshots crop out internal domains, usernames, Run URLs, node names, and sensitive logs;
- API Keys do not appear in Git, images, command-line arguments, Pod Specs, or logs;
- Production environment has completed Pod recreation, backup recovery, and upgrade rollback drills;
- SwanLab and Prometheus/Grafana use the same Run, Job, model, and version identifiers.

## References

- [SwanLab Kubernetes Deployment](https://docs.swanlab.cn/self_host/kubernetes/deploy.html)
- [SwanLab Private Service Login](https://docs.swanlab.cn/api/cli-swanlab-login.html)
- [ms-swift Command-Line Parameters](https://github.com/modelscope/ms-swift/blob/main/docs/source/Instruction/Command-line-parameters.md)
