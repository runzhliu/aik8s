---
title: "GPUs Are Idle, Why Is the Pod Still Pending?"
description: "Locate GPU Pending layer by layer: queue admission, scheduling, topology, devices, storage, and elasticity"
status: stable
last_reviewed: 2026-08-04
---

# GPUs Are Idle, Why Is the Pod Still Pending?

"Monitoring shows 8 GPUs still available" only means the aggregate number is non-zero; it does not mean a node exists that satisfies all of the Pod's constraints. The goal of troubleshooting is not to delete some Affinity as quickly as possible, but to find out at which control layer the request was rejected, and whether the rejection conforms to the platform contract.

## 1. Ten Common Root Causes

| Layer | Typical Root Cause | First Evidence |
| --- | --- | --- |
| Controller | Job/Operator has not created the Pod yet | Parent object `status` and events |
| Queue | Kueue Workload not admitted, insufficient quota | `Workload`, `ClusterQueue` |
| Gang | PodGroup/JobSet waiting for the complete resource group | PodGroup and scheduler events |
| Request | Wrong resource name, card count, or GPU memory spec | Pod `requests/limits` |
| Node | Label, Taint, Affinity mismatch | scheduler `FailedScheduling` |
| Topology | Scattered cards exist, but no contiguous resources on the same machine/domain | Node card distribution and topology |
| Device | Device Plugin/DRA not reporting or Claim not allocated | Node allocatable, ResourceClaim |
| Scaling | Scale from Zero template has no GPU resource information | autoscaler/Karpenter events |
| Storage | PVC Pending, availability zone conflict | PVC/PV events |
| Policy | Admission, ResourceQuota, or LimitRange rejection | API/admission audit and events |

## 2. Shortest Troubleshooting Path

```bash
kubectl describe pod <pod> -n <namespace>
kubectl get events -n <namespace> --sort-by=.lastTimestamp
kubectl get nodes -L nvidia.com/gpu.product,topology.kubernetes.io/zone
kubectl get nodes -o custom-columns='NAME:.metadata.name,GPU:.status.allocatable.nvidia\.com/gpu'
kubectl get pvc -n <namespace>
```

When using Kueue, continue checking:

```bash
kubectl get workload -A
kubectl describe workload <workload> -n <namespace>
kubectl describe clusterqueue <queue>
```

When using Volcano, check `PodGroup`, Queue, and `vc-scheduler` events. When using DRA, check `ResourceClaim`, `ResourceSlice`, and scheduling events.

## 3. Decision Tree

```text
有没有 Pod？
  否 → 看父控制器、Webhook 和 CRD
  是
  └─ 是否被队列准入？
       否 → 看配额、Flavor、优先级和借用
       是
       └─ scheduler 是否给出候选节点？
            否 → 看请求、Taint、Affinity、PVC 和拓扑
            是
            └─ 是否等待设备或节点扩容？
                 是 → 看 Device Plugin/DRA 和 autoscaler
                 否 → 检查 kubelet、Runtime 和 Sandbox 创建
```

## 4. Don't Fix It This Way

- Delete Taints, Affinities, or queues without looking at events;
- Change the request from 8 cards to 1 card just to get the Pod into Running;
- Use the average number of idle GPUs instead of per-node and per-topology inventory;
- Restart the scheduler directly, losing the most valuable evidence;
- Let the autoscaler, Kueue, and business controllers repeatedly create/delete the same task.

## 5. Evidence Template

Record the Pod UID, parent Job, queue, request, number of candidate nodes, scheduling failure reason, target Flavor, PVC availability zone, scaling decision, device reporting, and final fix. After the fix, resubmit the same request to confirm the problem was not bypassed by lowering the business contract.

Further reading: [GPU Scheduling](../gpu-scheduling.md), [Queues and Multi-tenancy](../queue-multitenancy.md), [Autoscaling](../scheduling/autoscaling.md)
