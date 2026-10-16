---
title: "GPU Workloads and Node Autoscaling"
description: "Coordinating HPA, KEDA, Kueue, Cluster Autoscaler, and Karpenter to handle GPU cold starts, fragmentation, and interruptions"
status: evolving
last_reviewed: 2026-08-02
---

# GPU Workloads and Node Autoscaling

Scaling an AI platform is not a single HPA. A single traffic change can sequentially trigger inference replica scaling, Pending Pods, GPU node creation, driver and device component readiness, image pull, model download, and cache warm-up. If any layer lacks a time budget, autoscaling can time out before capacity arrives.

## 1. Four Layers of Elasticity

```text
请求层
  并发、Token、优先级、排队和拒绝
        │
Pod/Workload 层
  HPA、KEDA、WVA、训练弹性、队列准入
        │
节点层
  Cluster Autoscaler、Karpenter、云厂商自动供给
        │
容量层
  预留、Spot、配额、区域库存和裸金属交付
```

Kueue does not create nodes, and HPA does not understand whether GPUs are obtainable from the cloud provider. Each layer must have its own SLO and failure reasons.

## 2. Scaling Timeline

```text
T0  流量或排队增长
T1  Autoscaler 生成新副本
T2  Pod Pending
T3  Node Autoscaler 决定创建节点
T4  云实例获得容量并启动
T5  kubelet、CNI、CSI、GPU Driver/Plugin Ready
T6  镜像和模型下载
T7  GPU 权重加载、图编译和预热
T8  Pod Ready，Gateway 开始送流量
```

Record the time for each stage. Monitoring only T0 to T1 severely underestimates the cold start of large models.

## 3. Workload Scaling Signals

### Traditional HPA

CPU is usually not the primary bottleneck for LLM inference. HPA is better suited for:

- Gateways, Tokenizers, Embedding, or CPU services;
- Custom metrics already exposed through a Metrics Adapter;
- Stable online services that maintain at least one replica.

### KEDA

KEDA can generate HPAs based on external signals such as Prometheus or message queues, and handles 0-to-1 activation. Suitable for:

- Batch inference queues;
- Asynchronous Embedding;
- Request queues or token metrics;
- Models that can scale to zero and tolerate cold starts.

### Inference-Specific Signals

Prioritize:

- Waiting Requests / Queue Depth;
- Running Requests versus safe concurrency;
- Prompt/Generation Token Rate;
- TTFT, TPOT, and rejection rate;
- KV Cache utilization;
- Model loading status;
- Predicted request duration.

Using only GPU Utilization is easily misleading: Decode may be GPU memory bandwidth-bound while SM utilization stays low, and long Prompts can cause short Prefill spikes.

## 4. Example KEDA Approach

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: llm-server
spec:
  scaleTargetRef:
    name: llm-server
  minReplicaCount: 1
  maxReplicaCount: 8
  cooldownPeriod: 300
  triggers:
    - type: prometheus
      metadata:
        serverAddress: http://prometheus.monitoring.svc:9090
        metricName: llm_waiting_requests
        query: sum(llm_waiting_requests{model="example-model"})
        threshold: "8"
```

The metric names are examples of a platform contract and should be adjusted according to actual engine metrics and aggregation methods. Missing metrics, Prometheus unavailability, and high cardinality issues must be handled before scaling.

## 5. Cluster Autoscaler vs. Karpenter

| Capability | Cluster Autoscaler | Karpenter |
| --- | --- | --- |
| Node source | Predefined Node Groups | Dynamically selects Nodes based on NodePool constraints |
| Cloud provider coverage | Broad | Depends on Provider implementation |
| Node lifecycle | Focuses mainly on scaling in/out | Also covers provisioning, expiration, drift, and consolidation |
| Instance selection | Selects from configured groups | Selects instances based on Pending Pods and constraints |
| Best suited for | Stable node groups, consistent multi-cloud patterns | Dynamic cloud instances and rapidly iterating node pools |

The Kubernetes project lists both as SIG Autoscaling-related Node Autoscalers. Specific capabilities and supported clouds depend on the target Provider documentation.

Reference: [Kubernetes Node Autoscaling](https://kubernetes.io/docs/concepts/cluster-administration/node-autoscaling/)

## 6. GPU NodePool Constraints

A GPU NodePool should at minimum constrain:

- Allowed instance/GPU models;
- Regions and availability zones;
- On-Demand, Spot, or reserved capacity;
- Total GPU/CPU/memory limits;
- Node Taints and platform labels;
- OS/AMI/node images;
- Expiration, consolidation, and interruption budgets;
- DaemonSet resource overhead;
- Local disks and network capabilities.

Karpenter concept example:

```yaml
apiVersion: karpenter.sh/v1
kind: NodePool
metadata:
  name: gpu-inference
spec:
  limits:
    nvidia.com/gpu: 32
  disruption:
    consolidationPolicy: WhenEmpty
    budgets:
      - nodes: "1"
  template:
    spec:
      taints:
        - key: accelerator
          value: gpu
          effect: NoSchedule
      requirements:
        - key: karpenter.sh/capacity-type
          operator: In
          values: ["on-demand"]
```

The Provider also requires cloud resource configuration such as NodeClass; this example cannot be used directly as a complete installation manifest.

## 7. Prerequisites for Scale from Zero

The Node Autoscaler must be able to infer even when nodes do not exist:

- What extended resources the node will provide;
- Node labels, Taints, and availability zones;
- How much CPU, memory, and Pod Slots DaemonSets will consume;
- Whether DRA Drivers/Device Plugins are compatible with autoscaling;
- Whether multi-node tasks require atomic topology;
- Whether cloud quotas and instance inventory allow provisioning.

If the autoscaler cannot see future GPU resources, Pending Pods will not trigger node creation. Managed Kubernetes offerings often supplement this information through node templates or NodePool metadata.

## 8. Queueing and Node Provisioning

Kueue typically only admits Workloads when quota is available. Common strategies:

### Admit First, Then Scale Nodes

Advantages: simple, Pending Pods trigger the Node Autoscaler. Risks: quota exists but cloud capacity is insufficient, admitted jobs wait indefinitely.

### ProvisioningRequest

Kueue/Autoscaler coordinate capacity provisioning first, then complete admission. Suitable for expensive, scarce, or reserved full-group capacity, but component integration and state machines are more complex.

### Reserve Minimum Capacity

Online inference keeps a Warm Pool; training and batch processing scale elastically. This sacrifices some idle cost for predictable latency.

Users must be able to see the difference between "waiting for quota," "waiting for cloud capacity," "waiting for node startup," and "waiting for model warm-up."

## 9. Multi-Node Jobs and Atomic Scaling

A 16-node job cannot accept being created with only 9 nodes and then waiting indefinitely. Considerations:

- Gang/All-or-Nothing admission;
- Whether the cloud provider can atomically obtain the full group of capacity;
- Same network Block/Placement Group/TPU Slice;
- Release of partially failed capacity;
- Whether to switch regions, models, or queues after timeout;
- Cost leakage when nodes are created but jobs do not start in time.

For TPU Slices, UltraServers, or high-bandwidth network domains, node count and topology are part of the same resource request.

## 10. Scaling Down and Interruptions

Node scale-down should not look only at "low GPU utilization." First determine whether workloads can be safely moved:

- Does online inference have other Ready replicas;
- How long does model cache rebuild take;
- Has training completed Checkpointing;
- Is local NVMe the only copy of data;
- Are PDB, Kueue, and termination grace periods consistent;
- How are DRA Claims, RDMA connections, and multi-host groups released;
- Is disruption allowed during Canary/release windows.

For online GPU nodes, use conservative consolidation strategies; batch nodes can scale down more aggressively after Jobs complete.

## 11. Spot and Preemption

Suitable for Spot:

- Training with reliable Checkpoints;
- Retryable batch inference and data processing;
- Low-priority experiments;
- Tasks that can migrate across models or regions.

Not suitable for Spot-only:

- Online models without redundancy;
- Training that cannot save state for long periods;
- Tasks with strict topology that are hard to re-acquire as a full group;
- Workloads whose cold start far exceeds the average available window.

Interruption notifications must simultaneously trigger stopping admission, Checkpoint/Drain, and metric recording.

## 12. Preventing Elastic Controllers from Fighting

Typical conflicts:

- HPA scales replicas while KEDA manages the same Scale Target;
- VPA recreates Pods, affecting inference availability;
- Karpenter consolidates nodes while Kueue just admitted training;
- Canary traffic changes trigger HPA, breaking experiment ratios;
- Prefill/Decode two Autoscalers lose balance;
- Model Cache DaemonSet has not finished, but Pods are already marked Ready.

Each scalable object can have only one final writer. Different controllers coordinate through explicit metrics and protection windows.

## 13. Capacity Protection

Recommended layering:

```text
硬下限：系统和生产推理最小容量
保护容量：单故障域、升级和突发预留
可借用容量：训练/实验可临时使用
弹性容量：云上按需或 Spot 扩展
```

When production traffic rises, first stop training borrowing or new job admission, rather than directly preempting already-loaded inference replicas with low traffic.

## 14. Metrics That Must Be Monitored

| Layer | Metrics |
| --- | --- |
| Request | Arrival rate, queueing, rejection, TTFT/TPOT |
| Pod | Desired/Ready, scaling decisions, Pending reasons |
| Queue | Admission, wait time, quota, Flavor |
| Node | Provision time, failures, NotReady, consolidation |
| Model | Download, load, warm-up, and cache hit time |
| Cloud capacity | Quota, insufficient inventory, Spot interruptions, price |
| Cost | Idle time, cold start waste, cost per Token/Job |

The end-to-end scaling SLO should be measured from signal generation to newly Ready capacity, not just Autoscaler Reconcile.

## 15. Failure Modes

| Symptom | Common Cause |
| --- | --- |
| HPA scaled out but no new capacity | GPU Pods Pending, nodes not created |
| Pods still Pending after node creation | DaemonSet overhead, labels/Taints, Device Plugin not ready |
| Pod Running but not receiving traffic | Model download/load, Readiness, or Gateway state |
| Scaling oscillation | Metric latency, thresholds too close, insufficient cooldown |
| Cannot scale down | PDB, local data, long training, do-not-disrupt |
| Wrong GPU model selected | NodePool constraints too broad or platform labels inconsistent |
| Abnormal cost growth | Created but not admitted, model load failure, consolidation permanently blocked |

## 16. Production Checklist

- [ ] Full timeline from scaling signal to model Ready has been recorded.
- [ ] Inference scaling is based on queue, Token, or latency, not CPU alone.
- [ ] Node Autoscaler can identify resources and labels of future GPU nodes.
- [ ] Kueue admission and insufficient node capacity have distinct states and alerts.
- [ ] Multi-node jobs do not occupy resources indefinitely after partial provisioning.
- [ ] Online inference has a Warm Pool and failure redundancy.
- [ ] Scale-down respects Checkpoint, PDB, local cache, and DRA Claims.
- [ ] Spot interruption path has been tested in real drills.
- [ ] Each Scale Target has only one final controller.
- [ ] End-to-end scaling SLO and cost can be continuously regressed.

## Further Reading

- [Kubernetes Node Autoscaling](https://kubernetes.io/docs/concepts/cluster-administration/node-autoscaling/)
- [Kubernetes Workload Autoscaling](https://kubernetes.io/docs/concepts/workloads/autoscaling/)
- [KEDA Scaling Deployments](https://keda.sh/docs/latest/concepts/scaling-deployments/)
- [Karpenter NodePools](https://karpenter.sh/docs/concepts/nodepools/)
- [Kueue ProvisioningRequest](https://kueue.sigs.k8s.io/docs/admission-check-controllers/provisioning/)
- [KServe Autoscaling with KEDA](https://kserve.github.io/website/docs/model-serving/predictive-inference/autoscaling/keda-autoscaler)
