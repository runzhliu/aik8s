---
title: "GPU, Training, and Inference Observability"
description: "Metrics and tracing from user requests and training jobs to Pods, GPUs, network, and storage"
status: evolving
last_reviewed: 2026-08-21
---

# GPU, Training, and Inference Observability

The most common observability mistake on AI platforms is installing only Prometheus and a GPU Dashboard. A truly usable system must connect infrastructure, scheduling, training progress, inference requests, and model quality into a single chain of evidence.

## 1. Five-Layer Observability Model

```text
业务与模型质量：正确率、拒答率、用户反馈、安全评估
请求与服务：TTFT、TPOT、Token/s、队列、错误、缓存命中
工作负载：训练 step、loss、checkpoint、rank、重试
设备与节点：GPU、显存、NVLink、RDMA、CPU、磁盘、网络
控制面：队列准入、调度、扩容、Operator、Kubernetes 事件
```

With only one layer of data, teams often can only know that things are "slow" but cannot answer whether the slowness comes from data, network, GPU, scheduling, or the model itself.

## 2. Unify Correlation Keys First

Metrics, logs, and traces should carry at least the following low-cardinality identifiers:

- `cluster`, `namespace`, `workload`;
- `team`, `environment`;
- `job_id` or `service`;
- `model_name`, `model_revision`;
- `gpu_model`, `resource_flavor`;
- `release` or image digest.

High-cardinality or sensitive fields such as request IDs, prompts, and user IDs should not become Prometheus labels directly. They are better suited for controlled logs, traces, or dedicated analytics systems.

## 3. How to Read GPU Metrics

NVIDIA DCGM Exporter exposes GPU metrics via `/metrics`. It can run as a DaemonSet or be managed by GPU Operator, and can use kubelet PodResources to associate device metrics with Pods. Reference: [DCGM Exporter](https://docs.nvidia.com/datacenter/dcgm/latest/gpu-telemetry/dcgm-exporter.html)

| Category | Metric to Watch | Explanation |
| --- | --- | --- |
| Core utilization | GPU utilization, SM activity | Whether the GPU is executing computation |
| GPU memory | framebuffer used/free | Occupancy by model, batch, and KV cache |
| Memory bandwidth | DRAM active | Whether limited by GPU memory bandwidth |
| Tensor Core | Tensor activity | Whether mixed-precision matrix computation is sufficient |
| Interconnect | NVLink/NvSwitch throughput, error | Multi-GPU communication load and anomalies |
| PCIe | TX/RX throughput, replay | Host-to-device transfer bottlenecks |
| Health | XID, ECC, health status | Driver or hardware failure signals |
| Environment | Power, temperature, clock, throttling reason | Whether limited by power or thermal constraints |

"GPU utilization 100%" does not mean optimal efficiency. It may be executing inefficient kernels, or it may present a misleading average due to synchronization waits. It must be interpreted together with throughput and business goals.

## 4. Golden Metrics for Training Jobs

Training should record at minimum:

- global step, epoch, samples/s or tokens/s;
- loss, learning rate, gradient norm;
- step time mean and P95;
- DataLoader wait, data decoding time;
- collective communication time;
- checkpoint save/restore time and size;
- effective training time, queue time, failure recovery time;
- straggler differences across ranks.

A practical decomposition is:

```text
step_time
  = data_wait
  + forward
  + backward
  + communication
  + optimizer
  + checkpoint_amortized
```

If only total step time is recorded, network jitter, data starvation, and computation fallback are mixed together.

## 5. Experiment Tracking and Infrastructure Monitoring Should Be Layered

Training curves and GPU monitoring answer two different kinds of problems and should not be forced into the same system:

| Tool | Best Answer For | Not a Substitute For |
| --- | --- | --- |
| TensorBoard | Curves and computation graphs for single or a few local experiments | Team-level projects, permissions, and experiment governance |
| SwanLab | Runs, hyperparameters, loss, media files, and cross-experiment comparison | GPU, node, RDMA, and Kubernetes monitoring |
| MLflow | Experiments, model artifacts, and model registry lifecycle | High-frequency infrastructure metrics |
| Weights & Biases | Hosted experiment tracking and team collaboration | Default choice for fully self-hosted intranet scenarios |
| Prometheus + Grafana | GPU, node, network, queue, and cluster alerting | Training data, hyperparameters, and model artifact management |

A practical training infrastructure combination is:

```text
ms-swift / PyTorch
  -> SwanLab SDK -> Gateway
                    -> Server / Auth -> PostgreSQL
                    -> House / Vector -> ClickHouse
                    -> 媒体与制品 -> S3 兼容对象存储

Kubernetes / DCGM Exporter / NIC
  -> Prometheus -> Grafana
```

The two pipelines are aligned using unified `run_id`, `job_id`, model version, and Git commit. When loss jitter is observed, first locate the specific step in SwanLab, then check GPU utilization, GPU memory, power, slow ranks, and network anomalies in Grafana for the same time window.

### Validation Results from a Self-Hosted PoC

On August 21, 2026, using the official Helm Chart `0.6.2` and SwanLab `v3.1.1` on Kubernetes 1.30, an infrastructure smoke test was completed: 10 Deployments, 1 StatefulSet, and 1 initialization Job all started successfully; all 11 resident Pods were Ready with no restarts; database migration and object storage bucket initialization succeeded; the Gateway activation page and API were both accessible.

This PoC round used ephemeral volumes for all stateful directories and did not create PVCs, in order to first validate components, images, and the ingress path. It proves that pages and basic APIs work, but it does not prove data durability; after Pods are replaced, accounts, experiments, and curves may be lost. Production environments should switch to persistent PostgreSQL, ClickHouse, and object storage, and complete backup/restore drills.

After instance activation, a 6-step synthetic Run was created using the SwanLab SDK `0.8.4` bundled in the training image. The SDK successfully uploaded 39 records, including `train/loss`, Learning Rate, and Tokens/s; the Run page in the external web entry returned 200. The first compatibility smoke test also found that `swanlab.login()` in that image does not accept the `web_host` parameter from the newer documentation. Therefore, when upgrading the training image, the SDK version must be pinned at the same time, and a regression test using a real image should cover login, creating a Run, writing metrics, and ending a Run.

Subsequently, a real `Qwen3.5-4B + BF16 LoRA` was completed using the same pipeline: 120 steps of Train Loss, Learning Rate, Gradient Norm, Token Accuracy, and four validations were all viewable; the best checkpoint was selected at Step 60 by Validation Loss; the accuracy on 110 isolated blind-test custom fault codes improved from 0% for Base to 77.3% for Adapter. This formed the complete evidence chain of "metric pipeline + checkpoint + Base/Adapter effectiveness."

The real Run also exposed version compatibility details: ms-swift 4.4.1 reports display fields such as `30/120` and `3m 53s` as strings, and SwanLab SDK 0.8.4 rejects String Scalars, but numeric metrics, training, and blind testing are unaffected. This issue should be added to the image upgrade regression test cases. Reusable deployment boundaries and desensitized curves are available at [SwanLab Self-Hosting: From Kubernetes Deployment to Real SFT Metrics](training/swanlab-self-hosted.md), and machine-readable results are at [`meaningful-sft`](https://github.com/runzhliu/aik8s/tree/main/examples/llm-sft-lab/meaningful-sft).

## 6. How to Find Slow Ranks in Distributed Training

Observe simultaneously:

- step duration per rank;
- NCCL collective latency distribution;
- GPU/NIC/NUMA affinity;
- NIC throughput, packet loss, ECN/PFC, and retransmissions;
- CPU scheduling, page faults, and storage reads;
- whether any node is throttled, experiencing XID, or has degraded links.

The slowest rank determines the overall speed of synchronous training. Do not look only at cluster averages; averages hide single-node anomalies.

## 7. Core Metrics for LLM Inference

| Metric | Meaning | Usage |
| --- | --- | --- |
| TTFT | From request to first token | Reflects queueing, prefill, and cold start |
| TPOT | Time per subsequent output token | Reflects decode performance |
| ITL | Inter-token latency | Evaluates streaming output stability |
| E2E latency | Full request latency | User experience, correlated with output length |
| input/output tokens/s | Throughput | Input and output must be distinguished |
| queue time/depth | Queueing time and depth | Basis for scaling and overload control |
| KV Cache utilization | Cache occupancy | Determines concurrency ceiling and eviction risk |
| prefix cache hit | Prefix hit rate | Evaluates routing and cache benefits |
| request success/cancel | Success, error, cancel | Long-lived connections and client behavior |

All latencies should be bucketed by model, input length, output length, priority, and streaming/non-streaming requests; otherwise P95 lacks comparability.

## 8. From Infrastructure SLIs to Business SLOs

At least three types of SLOs are recommended:

### Platform SLOs

- Job submission API availability;
- Scheduling control plane error rate;
- Admission latency when quota and capacity are available;
- Inference platform release success rate.

### Workload SLOs

- Training job success rate and recovery time;
- Checkpoint success rate;
- Online inference availability, TTFT, and error rate;
- Model version release and rollback time.

### Model SLOs

- Offline evaluation thresholds;
- Online quality, refusal rate, or safety policy hit rate;
- Data drift and model drift;
- User feedback and business conversion.

If infrastructure SLOs are met but model output is wrong, it is still a failed release.

## 9. Log Design

Training logs should be structured and include: time, Job, Rank, step, component, and error category. Inference logs should distinguish between gateway, scheduler, model server, and downstream tool calls.

The following must not be logged by default:

- Full prompts and responses;
- Access tokens, cookies, API keys;
- Personal information in datasets;
- Unredacted model input attachments;
- Secrets, environment variables, or full Pod specs.

When temporarily raising log levels for troubleshooting, set automatic expiration and restrict access permissions.

## 10. Which Boundaries Should Traces Cover

A single inference request can span:

```text
API Gateway
  → 身份/限流
  → 模型路由
  → 排队
  → Prefill Worker
  → KV Cache 传输
  → Decode Worker
  → 工具或检索服务
  → 流式响应
```

The value of traces is explaining end-to-end latency, not replacing metrics. OpenTelemetry provides semantic conventions for Trace, Metric, Log, and Resource, allowing signals to be correlated with unified resource attributes. Reference: [OpenTelemetry Semantic Conventions](https://opentelemetry.io/docs/concepts/semantic-conventions/)

## 11. Alerts Should Be Actionable

Good alert examples:

- A new XID appears on a GPU node and the corresponding Pod error rate rises;
- TTFT P99 exceeds the SLO while queue depth keeps increasing;
- A queue with quota waits beyond the threshold but no cluster scaling action occurs;
- Checkpoints fail consecutively and the remaining recoverable window falls below RPO;
- A single rank is more than 30% slower than the median;
- GPU power is low, GPU memory is high, and throughput drops, suggesting a data or communication bottleneck.

"CPU high" or "Pod restarted" alone is usually not actionable enough; alerts should include the affected object, possible causes, and a Runbook link.

## 12. Controlling Metric Cardinality and Cost

- Do not use request IDs, user IDs, or file names as metric labels;
- Keep only the current and a small number of historical model versions;
- Control sampling intervals for high-frequency GPU profiling metrics;
- Downsample long-term trends; retain raw high-resolution data for a short period;
- Use tail-based sampling for traces by error, latency, or tenant;
- Set capacity budgets for logs, metrics, and traces themselves.

An observability system that slows down the production cluster is a common secondary failure on platforms.

## 13. Recommended Dashboards

1. **Platform overview**: GPU capacity, queues, cost, SLOs, alerts;
2. **Node details**: GPU, NVLink, NIC, CPU, storage, XID;
3. **Training jobs**: step, loss, throughput, ranks, communication, checkpoints;
4. **Inference services**: TTFT, TPOT, queues, KV cache, errors, versions;
5. **Tenant view**: quota, GPU-hours, success rate, wait time, and cost;
6. **Release view**: quality, performance, and error comparison between old and new versions.

## 14. Go-Live Checklist

- [ ] Metrics can be correlated from cluster to team, Job, model, and release version;
- [ ] Experiment tracking system and Prometheus/Grafana use the same Run and Job identifiers;
- [ ] GPU metrics come from DCGM and Pod mapping is verified correct;
- [ ] Training shows decomposition of data, compute, communication, and checkpoints;
- [ ] Inference records TTFT, TPOT, queue, and token throughput simultaneously;
- [ ] SLOs cover platform, workload, and model quality;
- [ ] Prompts, secrets, and personal information are not logged by default;
- [ ] Alerts include impact, ownership, and Runbook;
- [ ] Metric cardinality, log volume, and trace sampling have budgets;
- [ ] Pre- and post-release can be compared on the same dashboard.

## Further Reading

- [NVIDIA DCGM Exporter](https://docs.nvidia.com/datacenter/dcgm/latest/gpu-telemetry/dcgm-exporter.html)
- [DCGM Exporter Metrics](https://docs.nvidia.com/datacenter/dcgm/latest/reference/dcgm-exporter-metrics.html)
- [OpenTelemetry Semantic Conventions](https://opentelemetry.io/docs/concepts/semantic-conventions/)
- [Kueue Monitoring](https://kueue.sigs.k8s.io/docs/tasks/manage/monitor_pending_workloads/)
- [SwanLab Kubernetes Deployment](https://docs.swanlab.cn/self_host/kubernetes/deploy.html)
- [SwanLab Private Service Login](https://docs.swanlab.cn/api/cli-swanlab-login.html)
