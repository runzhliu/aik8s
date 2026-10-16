---
title: "GPU Cost, Capacity Planning, and FinOps"
description: "Cost attribution, unit economics, capacity forecasting, and elasticity strategies for AI platforms"
status: stable
last_reviewed: 2026-08-02
---

# GPU Cost, Capacity Planning, and FinOps

GPU platform cost optimization is not about pushing utilization to 100%. Over-compressing capacity increases queuing and tail latency, incorrect sharing harms model performance, and cheap Spot nodes can become more expensive due to repeated recomputation.

The right approach is to measure cost together with training output, inference tokens, SLOs, and failure losses.

## 1. Build a Complete Cost Model

```text
总成本
  = GPU/CPU/内存节点
  + 存储容量与请求
  + 网络与跨区流量
  + 控制面和平台组件
  + 软件许可
  + 闲置与预留损失
  + 失败重算成本
  + 运维人力
```

Looking only at GPU instance bills ignores repeated model downloads, cross-region training, checkpoint storage, and platform complexity.

## 2. Distinguish Allocation, Usage, and Output

| Dimension | Question | Example |
| --- | --- | --- |
| Allocation | How much the scheduler reserves for a task | 8 GPUs × 10 hours |
| Usage | How much the device actually works | Average SM active, GPU memory, power consumption |
| Output | What business value is produced | tokens, samples, successful experiments, requests |

Allocation determines the bill, Usage helps identify waste, and Output enables comparison across different models and platform options.

OpenCost provides an open specification for Kubernetes cost allocation, distinguishing workloads, shared, and idle costs by namespace, Pod, Job, Label, and other dimensions. Reference: [OpenCost Overview](https://opencost.io/docs/), [OpenCost Specification](https://opencost.io/docs/specification/)

## 3. Standardize Resource Attribution Labels

At minimum, standardize:

```yaml
metadata:
  labels:
    platform.example.com/team: search
    platform.example.com/environment: production
    platform.example.com/workload-type: training
    platform.example.com/model: reranker
    platform.example.com/cost-center: cc-1042
```

Label values should be low-cardinality, verifiable, and automatically filled in via admission policies. Do not rely on user-entered project names for financial reconciliation.

## 4. Unit Economics for Training

Training can use:

```text
每百万样本成本 = 训练总成本 / 处理样本数 × 1,000,000
每十亿 Token 训练成本 = 训练总成本 / Token 数 × 1,000,000,000
有效 GPU 小时 = GPU 数 × 真正训练时间
失败损失 = 故障前未保存时间 × GPU 数 × GPU 时价
```

When comparing experiments, ensure target quality is consistent. A solution that reaches a worse Loss faster is not necessarily better than one that is slightly slower but reaches the target quality.

The core idea of MLPerf Training is also to measure the time required to reach target quality, not just single-step peak performance. Reference: [MLPerf Training](https://mlcommons.org/benchmarks/training/)

## 5. Unit Economics for Inference

```text
每百万 Token 成本
  = 服务总成本 / 输出与计费 Token × 1,000,000

每个成功请求成本
  = 服务总成本 / 满足 SLO 的成功请求数
```

Also break down by the following dimensions:

- Model and quantization version;
- Input/output length;
- Online, batch, and interactive priority;
- Peak and off-peak periods;
- Cache hit and miss;
- Requests meeting SLO and timeouts.

Increased throughput with TTFT exceeding the target does not count as an effective cost reduction.

## 6. How to Estimate Training Capacity

First collect workload profiles:

- GPU model requirements;
- GPU count per task and runtime distribution;
- Arrival rate and deadlines;
- Preemptible ratio;
- Topology and RDMA requirements;
- Checkpoint/data warm-up time.

Capacity must satisfy not only the average GPU count, but also the probability that large tasks can obtain contiguous resources simultaneously. 64 highly fragmented idle GPUs may not be able to start a 32-card task that requires the same network domain.

## 7. How to Estimate Inference Capacity

Inference requires load testing to determine the safe throughput per replica under the target SLO:

```text
所需副本
  = 峰值有效请求率 / 单副本安全吞吐
  × 冗余系数
```

Safe throughput should cover the real input/output length distribution, not just short prompts. Also reserve for:

- Overlap of old and new versions during model releases;
- Node failures or maintenance;
- Scale-out and model loading time;
- Traffic spikes;
- Queuing caused by gateway and downstream tool failures.

## 8. Four Layers of Elasticity Should Not Conflict

```text
请求层：并发、动态 Batch、限流
Pod 层：HPA / KEDA / 自定义 Autoscaler
节点层：Cluster Autoscaler / Karpenter
队列层：Kueue 准入、Flavor 与优先级
```

Clarify the time scales: the request layer reacts in milliseconds to seconds, the Pod layer is typically at minute level, GPU node startup may take longer, and the queue determines which demands are worth triggering scale-out.

If each layer scales independently based on short-term metrics, it is easy to produce oscillation, repeated scale-outs, and expensive idle nodes.

## 9. Priority Order for Improving Utilization

It is recommended to proceed from low to high risk:

1. Fix data and communication bottlenecks;
2. Reduce image/model cold starts;
3. Adjust batch, parallelism, and quantization;
4. Clean up zombie tasks and oversized resource requests;
5. Use queue borrowing and better bin packing;
6. Introduce MIG/time-sharing for small inference or development tasks;
7. Colocate training and inference workloads;
8. Use Spot and proactive preemption.

The first few items usually do not change the isolation model and have more stable gains; the later items require more mature observability and recovery capabilities.

## 10. Idle Capacity Is Not Necessarily Waste

The following idle capacity may be reasonable:

- Fault redundancy for online services;
- Temporary overlap during large model releases;
- Waiting for large-scale Gang tasks to form contiguous resources;
- Node startup time is too long, requiring a warm pool;
- Maintenance or failure domain reservations;
- Explicitly purchased low-latency guarantees by the business.

Idle capacity should be split into "intentional reservation" and "unexplainable waste," and should not be reclaimed uniformly.

## 11. How to Combine Spot and Reserved Capacity

| Capacity type | Suitable for | Not suitable for |
| --- | --- | --- |
| Reserved/owned | Online baseline, long training, stable demand | Relying entirely on it for short-term peaks |
| On-demand | Bursts, release overlap, temporary recovery | Using it entirely for long-term stable load |
| Spot | Resumable training, batch inference, fault-tolerant data processing | Long tasks without checkpoints, critical online baseline |

When measuring Spot benefits, use:

```text
净节省 = 原按需成本 - Spot 成本 - 重算成本 - 额外运维成本
```

## 12. Budgets and Guardrails

- Monthly budget and alerts per namespace/team;
- Maximum GPU count and longest runtime per task;
- Automatically tag and alert on unattributed resources;
- High-priced flavors require explicit justification or approval;
- Nightly reclamation of development environments;
- Automatic suspension of idle notebooks;
- Maximum replicas and scale-out rate limits for model services;
- Separate alerts for cross-region data reads and public network traffic.

Budget protection should not terminate production services without notification.

## 13. Recommended Weekly Report

| Dimension | Metrics |
| --- | --- |
| Capacity | Total GPU, available, failed, maintenance, distribution by flavor |
| Utilization | Allocation, SM active, GPU memory, power consumption, idle |
| Queue | Wait time, rejection, preemption, borrowing ratio |
| Training | Success rate, effective GPU-hours, failed recomputation cost |
| Inference | Cost per million tokens, throughput meeting SLO |
| Tenant | Cost, quota, budget variance, unattributed resources |
| Optimization | This week's reclamation, savings, and impact on SLO |

## 14. Launch Checklist

- [ ] All GPU workloads can be attributed to a team and cost center;
- [ ] Allocation, Usage, and business output are each visible;
- [ ] Training is compared by target quality and effective GPU-hours;
- [ ] Inference cost only counts effective requests meeting SLO;
- [ ] Capacity model considers large-task fragmentation, topology, and cold starts;
- [ ] Queue, Pod, node, and request layer scaling time scales are clear;
- [ ] Spot savings deduct recomputation and operational costs;
- [ ] Intentional redundancy and unexplainable idle are separated;
- [ ] Budget policies do not accidentally interrupt production.

## Further Reading

- [OpenCost Documentation](https://opencost.io/docs/)
- [OpenCost Specification](https://opencost.io/docs/specification/)
- [MLPerf Training](https://mlcommons.org/benchmarks/training/)
- [Kueue Overview](https://kueue.sigs.k8s.io/docs/overview/)
