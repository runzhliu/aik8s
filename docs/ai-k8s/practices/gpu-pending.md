---
title: GPU 有空闲，Pod 为什么仍然 Pending
description: 从队列准入、调度、拓扑、设备、存储和弹性逐层定位 GPU Pending
status: stable
last_reviewed: 2026-08-04
---

# GPU 有空闲，Pod 为什么仍然 Pending

“监控显示还有 8 张 GPU”只说明聚合数字不为零，不代表存在一个满足 Pod 全部约束的节点。排障目标不是尽快删除某个 Affinity，而是找出在哪个控制层被拒绝，以及拒绝是否符合平台契约。

## 1. 十类常见根因

| 层级 | 典型根因 | 第一证据 |
| --- | --- | --- |
| 控制器 | Job/Operator 尚未创建 Pod | 父对象 `status` 和事件 |
| 队列 | Kueue Workload 未准入、配额不足 | `Workload`、`ClusterQueue` |
| Gang | PodGroup/JobSet 等待完整资源组 | PodGroup 和调度器事件 |
| 请求 | 资源名、卡数或显存规格错误 | Pod `requests/limits` |
| 节点 | Label、Taint、Affinity 不匹配 | scheduler `FailedScheduling` |
| 拓扑 | 有零散卡，没有同机/同域连续资源 | 节点卡分布和拓扑 |
| 设备 | Device Plugin/DRA 未报告或 Claim 未分配 | Node allocatable、ResourceClaim |
| 扩容 | Scale from Zero 模板没有 GPU 资源信息 | autoscaler/Karpenter 事件 |
| 存储 | PVC Pending、可用区冲突 | PVC/PV 事件 |
| 策略 | Admission、ResourceQuota 或 LimitRange 拒绝 | API/准入审计和事件 |

## 2. 最短排障路径

```bash
kubectl describe pod <pod> -n <namespace>
kubectl get events -n <namespace> --sort-by=.lastTimestamp
kubectl get nodes -L nvidia.com/gpu.product,topology.kubernetes.io/zone
kubectl get nodes -o custom-columns='NAME:.metadata.name,GPU:.status.allocatable.nvidia\.com/gpu'
kubectl get pvc -n <namespace>
```

使用 Kueue 时继续检查：

```bash
kubectl get workload -A
kubectl describe workload <workload> -n <namespace>
kubectl describe clusterqueue <queue>
```

使用 Volcano 时检查 `PodGroup`、Queue 和 `vc-scheduler` 事件。使用 DRA 时检查 `ResourceClaim`、`ResourceSlice` 和调度事件。

## 3. 决策树

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

## 4. 不要这样修

- 不看事件就删除 Taint、Affinity 或队列；
- 把请求从 8 卡改成 1 卡，只为让 Pod 进入 Running；
- 用平均空闲 GPU 数替代逐节点和逐拓扑库存；
- 直接重启 scheduler，丢失最有价值的证据；
- 让扩容器、Kueue 和业务控制器反复创建/删除同一任务。

## 5. 证据模板

记录 Pod UID、父 Job、队列、请求、候选节点数、调度失败原因、目标 Flavor、PVC 可用区、扩容决策、设备上报和最终修复。修复后重新提交相同请求，确认不是通过降低业务契约绕过问题。

延伸阅读：[GPU 调度](../gpu-scheduling.md)、[队列与多租户](../queue-multitenancy.md)、[自动扩缩容](../scheduling/autoscaling.md)

