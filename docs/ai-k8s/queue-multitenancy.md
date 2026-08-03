---
title: 队列、公平共享与多租户
description: Kueue 队列、ResourceFlavor、Cohort、优先级、抢占和租户治理
status: evolving
last_reviewed: 2026-08-02
---

# 队列、公平共享与多租户

GPU 平台的多租户问题，不是简单地给每个团队建一个 namespace。真正需要治理的是：谁可以提交任务、能占用多少稀缺资源、空闲配额能否借用、紧急任务如何抢占，以及不同硬件和拓扑如何计价。

本章以 Kueue 的模型为主线，同时说明它与 Kubernetes 调度、RBAC 和网络隔离之间的边界。

## 一、多租户至少有五层

| 层级 | 解决的问题 | 常用机制 |
| --- | --- | --- |
| 身份 | 谁在操作 | OIDC、ServiceAccount、RBAC |
| API 与策略 | 可以创建什么 | Admission、Kyverno/Gatekeeper、ResourceQuota |
| 资源准入 | 什么时候可以开始、能拿多少 | Kueue、Volcano |
| 运行隔离 | Pod 之间是否互相影响 | Namespace、NetworkPolicy、Pod Security、RuntimeClass |
| 成本与审计 | 谁为资源负责 | 标签、OpenCost、审计日志、预算 |

Namespace 是边界的一部分，但它不提供公平排队，也不会自动阻止某团队长期占用全部 GPU。

## 二、Kueue 的对象关系

```text
用户提交 Job
    │ queueName
    ▼
LocalQueue（namespace 内入口）
    │ 指向
    ▼
ClusterQueue（集群配额与策略）
    │ 使用
    ├── ResourceFlavor（GPU 型号、节点池、价格或区域）
    └── Cohort（多个队列之间借用空闲配额）
```

- `LocalQueue` 给租户一个 namespace 内稳定入口；
- `ClusterQueue` 定义名义配额、借用、抢占和队列策略；
- `ResourceFlavor` 把资源数量与节点标签/污点联系起来；
- `Cohort` 让多个 ClusterQueue 共享暂时空闲的配额；
- `Workload` 是 Kueue 对一次待准入任务的统一表示。

Kueue 只负责准入和配额，不替代 kube-scheduler 的 Pod 到 Node 放置。参考：[Kueue Overview](https://kueue.sigs.k8s.io/docs/overview/)

## 三、配额应该表达业务承诺

建议把配额拆成三部分：

1. **Nominal quota**：团队长期可以依赖的基线；
2. **Borrowing**：其他团队不用时可以临时借用的上限；
3. **Lending limit**：为了保护本队列未来需求，最多可以借出多少。

名义配额不是机器的静态切片。合理的共享可以提高利用率，但借用任务必须接受等待、缩容或被抢占的风险。

## 四、ResourceFlavor 不只是 GPU 型号

一个 Flavor 可以表达：

- `h100`、`a100`、`l4` 等 GPU 型号；
- 按需、预留、Spot 节点；
- 带 RDMA 或只有普通以太网的节点；
- 不同区域、机架或供电域；
- MIG、整卡或其他设备切分方式；
- 数据已经预热的节点池。

不要让用户直接绑定具体节点名。让用户声明性能或能力等级，再由队列和调度策略映射到硬件。

## 五、一个最小 Kueue 配置

```yaml
apiVersion: kueue.x-k8s.io/v1beta1
kind: ResourceFlavor
metadata:
  name: a100-rdma
spec:
  nodeLabels:
    accelerator.example.com/class: a100-rdma
---
apiVersion: kueue.x-k8s.io/v1beta1
kind: ClusterQueue
metadata:
  name: research
spec:
  namespaceSelector: {}
  resourceGroups:
    - coveredResources: ["cpu", "memory", "nvidia.com/gpu"]
      flavors:
        - name: a100-rdma
          resources:
            - name: nvidia.com/gpu
              nominalQuota: 32
---
apiVersion: kueue.x-k8s.io/v1beta1
kind: LocalQueue
metadata:
  name: gpu
  namespace: team-a
spec:
  clusterQueue: research
```

生产配置还需要明确 CPU、内存、GPU 的比例，避免任务拿到 GPU 却因 CPU 或内存配额不足无法启动。

## 六、公平不等于 FIFO

严格 FIFO 很容易被一个无法满足的大任务阻塞。常见策略包括：

- `StrictFIFO`：顺序可预测，但队头阻塞明显；
- `BestEffortFIFO`：允许后面可满足的任务先运行；
- Fair Sharing：根据队列历史或当前资源份额调整准入顺序；
- 优先级：让生产恢复、紧急训练或课堂作业有不同等级；
- Aging：等待越久逐步提高权重，避免长期饥饿。

Kueue 的 Admission Fair Sharing 会考虑 LocalQueue 的历史使用量，优先准入使用较少的队列。参考：[Admission Fair Sharing](https://kueue.sigs.k8s.io/docs/concepts/admission_fair_sharing/)

## 七、抢占要有明确契约

抢占不是免费的调度动作，它可能丢失数小时训练进度。平台应规定：

- 哪些优先级可以抢占哪些任务；
- 借用配额的任务是否默认可被抢占；
- 任务收到终止信号后有多少时间保存 Checkpoint；
- 抢占频率是否设置上限；
- 被抢占任务重新排队时是否保留年龄；
- 在线推理是否与训练共用抢占域。

高优先级不应由普通用户任意填写，应该通过准入策略、独立队列或受控模板赋予。

## 八、Gang 与 All-or-Nothing

一个需要 8 个 Worker 的训练任务，如果只启动 5 个，既不能训练又占住资源。平台需要保证：

- 所需 Pod 或 PodSet 同时满足准入；
- 任一关键角色无法启动时不提前消耗 GPU；
- 集群扩容器能看到完整需求；
- 失败后不会留下孤立 Worker；
- 最小并行规模和可弹性规模分开表达。

Kueue、JobSet、Kubeflow Trainer 和 KubeRay 可以组合表达工作负载级准入；Volcano 则提供更强调度器内的 Gang 能力。

## 九、拓扑感知准入

多机训练拿到正确数量的 GPU 仍可能很慢，因为资源分散在不同机架、网络 Block 或可用区。拓扑策略应回答：

- 必须放在同一主机、机架还是网络域；
- 是 `Required` 还是 `Preferred`；
- 同一任务不同 PodSet 是否需要不同拓扑；
- 等待紧凑拓扑的最大时间；
- 性能收益是否高于等待成本。

Kueue 的 `Topology` 与 `ResourceFlavor` 可以把配额准入和数据中心拓扑联系起来。参考：[Kueue Concepts](https://kueue.sigs.k8s.io/docs/concepts/)

## 十、Namespace 与 RBAC 设计

推荐模式：

- 每个团队至少一个 namespace，生产与实验分开；
- 普通用户只能使用已有 LocalQueue；
- ClusterQueue、ResourceFlavor 和优先级由平台管理员维护；
- 提交 Job 的 ServiceAccount 与读取模型/数据的身份分开；
- 平台控制器使用最小 RBAC，不给租户修改 webhook 或 CRD 的权限；
- 对跨 namespace 的 Secret、PVC 和 Service 访问做显式设计。

共享 Jupyter 环境尤其要小心：能在 Notebook 中执行任意代码的用户，往往等同于拥有该 Pod 的 ServiceAccount 权限。

## 十一、在线推理和训练是否共池

共池可以提高利用率，但必须满足：

- 在线推理有预留容量或不可借出的底线；
- 训练扩容不会耗尽推理所需的 CPU、内存和网络；
- 节点维护不会同时击穿多个推理副本；
- 调度和成本系统能区分在线、离线和开发用途；
- 抢占前可预热替代推理副本。

小规模平台通常先分池更容易运营；达到稳定 SLO 和可观测能力后，再逐步混部。

## 十二、需要监控什么

| 对象 | 指标或状态 |
| --- | --- |
| LocalQueue | 待处理 Workload 数、等待时间、历史使用量 |
| ClusterQueue | 名义配额、借入、借出、保留、实际占用 |
| Workload | Pending 原因、准入时间、抢占次数 |
| Flavor | 各硬件池可用量、不可调度节点、扩容延迟 |
| 租户 | GPU-hours、成功率、排队 P50/P95、被抢占损失 |

“Pending”必须拆分成配额不足、拓扑不满足、准入检查未通过和 Pod 调度失败，否则用户只会看到一个模糊状态。

## 十三、治理清单

- [ ] 每个租户有明确名义配额和借用规则；
- [ ] 优先级创建和使用权限受控；
- [ ] 多 Pod 任务不会部分占用 GPU；
- [ ] 抢占前能保存 Checkpoint，并监控损失时间；
- [ ] Flavor 能区分硬件、网络、区域和价格等级；
- [ ] 训练与在线推理的容量保护策略明确；
- [ ] 用户能看到排队原因和大致等待情况；
- [ ] 成本、配额和实际 GPU 使用能按租户对账；
- [ ] 队列策略变更有审计和回滚方式。

## 延伸阅读

- [Kueue Overview](https://kueue.sigs.k8s.io/docs/overview/)
- [Kueue Concepts](https://kueue.sigs.k8s.io/docs/concepts/)
- [Kueue Admission Fair Sharing](https://kueue.sigs.k8s.io/docs/concepts/admission_fair_sharing/)
- [Kubernetes Multi-tenancy](https://kubernetes.io/docs/concepts/security/multi-tenancy/)
