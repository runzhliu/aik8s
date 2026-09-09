---
title: APF 隔离实战：零席位 Reject 为什么仍会放行
description: Kubernetes 1.30.4 四阶段实测，结合 Grafana 截图、客户端对照和源码解释 APF 的拒绝、排队与恢复
status: evolving
last_reviewed: 2026-09-09
---

# APF 隔离实战：零席位 Reject 为什么仍会放行

批量脚本、Operator 或资源盘点程序持续访问 Kubernetes API 时，平台需要能够限制某类请求的执行机会，同时保留其他调用方的访问能力。监控可以告诉我们请求变多了；APF 则提供请求分类、执行份额和有界排队机制。

这个案例在一个运行 Kubernetes **1.30.4** 的集群上，用两个专用 ServiceAccount 读取同一个 ConfigMap，实际验证“正常 → 零席位 Reject → 零席位 Queue → 恢复”。实验只产生少量只读流量，目标是验证隔离和恢复行为，不是探测 API Server 吞吐上限。

最值得注意的结果是：**该版本中，零席位 Reject 没有阻止低并发请求；零席位 Queue 则形成了排队和拒绝。** 本文保留这个与直觉不同的结果，并用实际响应、监控和版本源码互相核对。

## 1. 场景与边界

APF 已在 Kubernetes 1.29 稳定。这里的 1.30.4 是被测版本，不是新部署的版本推荐；其他版本需要重新验证边界行为。原理和 API 迁移背景见 [Kubernetes 流控指南](../cluster/flow-control.md)。

| 项目 | 实际设置 |
| --- | --- |
| 目标 | 一个 API Server 后端，Kubernetes 1.30.4 |
| 实验 Namespace | `apf-case`，实验前不存在 |
| 请求对象 | 本例创建的 `ConfigMap/fixture` |
| 批量账号 | `apf-case/batch-reader`，目标发送速率 5 req/s，最大在途 8 |
| 对照账号 | `apf-case/control-reader`，目标发送速率 1 req/s |
| 权限 | 两个账号都只能 GET 这个 ConfigMap |
| APF 匹配范围 | 仅批量账号对实验 Namespace 中 ConfigMap 的 GET |
| 阶段时长 | 每阶段 90 秒，共约 6 分钟 |
| 超时与重试 | 请求参数 `timeout=20s`，客户端读取超时 25 秒，不自动重试 |
| 观测 | 临时 15 秒采集；Grafana 使用 15 秒查询步长，速率窗口 1 分钟 |

独立对照账号访问相同对象，但不匹配实验 FlowSchema。客户端通过响应中的 `X-Kubernetes-PF-FlowSchema-UID` 和 `X-Kubernetes-PF-PriorityLevel-UID` 校验实际分类。**创建成功的 YAML 不是分类已经生效的证据。**

实验没有修改默认 APF 规则或 API Server 启动参数。新增正份额类别仍会改变总份额分配，因此即使匹配范围很小，也需要评估容量分配影响。客户端在对照请求连续三次失败或超过 2 秒时中止，并恢复、清理实验资源。

## 2. 四阶段结果

正式阶段统计了 **1800 个批量请求、359 个对照请求**。另有一个在首阶段开始前发出的对照请求不计入阶段表；预检请求也不计入。请求按开始时间归类，跨阶段完成的请求不被人为挪到另一个阶段。

| 阶段 | 名义份额 / 模式 | 批量 HTTP 200 | 批量 HTTP 429 | 批量客户端 P95 | 对照成功数 / 总数 | 对照客户端 P95 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 正常 | 5 / Queue | 450 | 0 | 49.3 ms | 90 / 90 | 46.7 ms |
| 零席位 Reject | 0 / Reject | 450 | 0 | 62.1 ms | 90 / 90 | 44.6 ms |
| 零席位 Queue | 0 / Queue | 2 | 448 | 5011.9 ms | 90 / 90 | 73.5 ms |
| 恢复 | 5 / Queue | 450 | 0 | 53.0 ms | 89 / 89 | 48.3 ms |

<picture>
  <source media="(max-width: 600px)" srcset="/assets/kubernetes-apf-case/client-outcomes-mobile.png">
  <img src="/assets/kubernetes-apf-case/client-outcomes.png" alt="四阶段批量请求状态码与独立对照结果，源自实际客户端日志" width="1200" style="max-width:100%;height:auto">
</picture>

Queue 阶段的 448 个 429 与 API Server 计数器一致：**414 个 `queue-full`，34 个 `time-out`**；监控采到的排队峰值为 **2**。另外 2 个请求在 Queue 阶段开始等待，在恢复执行份额后返回 200。

所有正式阶段的对照请求均成功，但对照 P95 在 44.6–73.5 ms 之间变化。小样本、客户端网络和执行时序都可能影响延迟，因此这里能证明的是“对照账号未被实验规则阻断”，不能据此宣称整个集群零影响。

## 3. 配置怎样匹配到这一个账号

下面的 FlowSchema 将专用账号的请求映射到 `apf-case-batch` 优先级。`matchingPrecedence: 1000` 在被测集群中先于一般 ServiceAccount 规则；其他集群仍需核对已有规则。

```yaml
apiVersion: flowcontrol.apiserver.k8s.io/v1
kind: FlowSchema
metadata:
  name: apf-case-batch
spec:
  matchingPrecedence: 1000
  priorityLevelConfiguration:
    name: apf-case-batch
  distinguisherMethod:
    type: ByUser
  rules:
    - subjects:
        - kind: ServiceAccount
          serviceAccount:
            namespace: apf-case
            name: batch-reader
      resourceRules:
        - verbs: [get]
          apiGroups: [""]
          resources: [configmaps]
          namespaces: [apf-case]
          clusterScope: false
```

FlowSchema 不授予读取权限。单独的 Role 通过 `resourceNames: [fixture]` 约束读取对象，RoleBinding 为两个实验账号授权。全部清单见 [可复现实验目录](https://github.com/runzhliu/aik8s/tree/main/examples/kubernetes-flow-control/apf-case)。

正常阶段的 `nominalConcurrencyShares: 5` 在这个集群对应监控中的 **12 个名义席位**，不是固定 5 个并发，也不是 5 QPS。实际份额换算受其他优先级和 API Server 总执行容量影响。

## 4. 为什么 0 + Reject 没有封住请求

第一种尝试将该类别的名义份额设为 0，同时设 `borrowingLimitPercent: 0`，并使用 `limitResponse.type: Reject`。实际配置和监控都确认执行上限变为 0，但 450 个低频批量请求仍然全部返回 200，响应头也确认它们确实匹配到了实验优先级。

在 Kubernetes 1.30.4 的队列实现中，无队列请求会检查 `canAccommodateSeatsLocked`。当单个请求需要的席位超过类别上限、且当前没有正在执行的请求时，该函数仍允许执行。这解释了为什么一个需要 1 个席位的请求，在上限为 0、类别空闲时仍然通过。参见 [v1.30.4 queueset.go](https://github.com/kubernetes/kubernetes/blob/v1.30.4/staging/src/k8s.io/apiserver/pkg/util/flowcontrol/fairqueuing/queueset/queueset.go#L745)。

这个结果不表示 Reject 模式没有用。Reject 控制的是无法接纳的请求如何处理；本次版本和低并发负载触发了上述边界路径。它也再次说明：**APF 的并发治理不能替代 RBAC、凭据吊销或其他访问授权边界。** 不应仅凭一份“零份额”清单承诺绝对封禁。

## 5. 0 + Queue：排队、超时和恢复

第二种配置仍为零份额，但启用一个最多等待 2 个请求的队列：

```yaml
apiVersion: flowcontrol.apiserver.k8s.io/v1
kind: PriorityLevelConfiguration
metadata:
  name: apf-case-batch
spec:
  type: Limited
  limited:
    nominalConcurrencyShares: 0
    lendablePercent: 0
    borrowingLimitPercent: 0
    limitResponse:
      type: Queue
      queuing:
        queues: 1
        handSize: 1
        queueLengthLimit: 2
```

该版本队列调度循环需要满足“已占用席位小于执行上限”才会继续分发。上限为 0 时，队列中的请求无法取得执行机会，于是产生两类拒绝：

- **queue-full**：队列已经装满，新请求较快收到 429。
- **time-out**：请求先进入队列，超过 APF 等待期限后收到 429。

这就是为什么同为 HTTP 429，客户端耗时可能差很多。被测版本对有 deadline 的请求，APF 最大等待取请求时间预算的四分之一，并受一分钟上限约束；本例 `timeout=20s` 对应约 5 秒等待，与客户端 P95 约 5.01 秒一致。参见 [v1.30.4 getRequestWaitContext](https://github.com/kubernetes/kubernetes/blob/v1.30.4/staging/src/k8s.io/apiserver/pkg/server/filters/priority-and-fairness.go#L390)。

恢复 5 份额后，仍在队列中的两个请求完成，后续 450 个批量请求全部成功。队列提供了等待位置，**执行份额恢复才让积压请求得以继续**。生产中不能把无限等待当作可用性保障，还需要有界超时、退避和上游重试预算。

## 6. 如何阅读真实 Grafana 截图

下图来自实际 Grafana 专用看板。时间范围固定到本次实验，阶段标记使用实际策略应用返回时间；没有重绘指标曲线。为避免泄露环境标识，截图使用不含内网地址的面板标题与图例。

<picture>
  <source media="(max-width: 600px)" srcset="/assets/kubernetes-apf-case/grafana-case-mobile.png">
  <img src="/assets/kubernetes-apf-case/grafana-case.png" alt="真实 Grafana 截图：实验优先级的名义席位、执行、拒绝、排队、等待及集群 GET 延迟" width="1440" style="max-width:100%;height:auto">
</picture>

| 面板 | 应如何解释 |
| --- | --- |
| 名义执行席位 | 观察 12 → 0 → 12；它不是每秒请求额度 |
| 实验请求执行速率 | Reject 阶段仍执行；Queue 阶段停止，恢复后继续 |
| 实验请求拒绝速率 | 按 queue-full 与 time-out 区分；没有事件时可能没有序列 |
| 实验请求排队数 | Queue 阶段达到 2；恢复后归零 |
| APF 等待 P95 | 按 execute 标签观察等待成本；该版本的 true 不等于最终执行成功，见下文 |
| 集群普通 GET P95 | 作为背景观测，不等于独立对照账号的延迟 |

图中速率和分位数使用滚动 1 分钟窗口，阶段切换后的曲线会保留窗口内旧请求的影响，不能直接把图形边缘当作策略精确生效时刻。Grafana 分位数来自直方图估算；结果表的客户端 P95 则来自逐条请求耗时，两个数不应直接比较或相减。

这里还有一个版本相关的指标陷阱：截图图例中的“执行=true”对应 `execute="true"` 标签。1.30.4 的实现用 `req != nil` 设置这个标签，排队后超时、没有真正进入执行回调的请求也会记录到 true。因此不能把这条曲线理解为“成功执行请求的等待 P95”，更不能用它统计成功率；实际执行看 dispatched 计数器，HTTP 结果看客户端。参见 [v1.30.4 apf_filter.go](https://github.com/kubernetes/kubernetes/blob/v1.30.4/staging/src/k8s.io/apiserver/pkg/util/flowcontrol/apf_filter.go#L159)。

截图中的等待 P95 接近 9.7 秒，也不能据此认定请求实际等待了这么久。该版本的等待直方图在 5 秒之后，下一个桶边界就是 10 秒；略超过 5 秒的样本会进入这个较宽的桶，分位数插值可能明显偏离真实耗时。需要精确分析时，应同时检查桶分布和逐条请求记录。桶定义见 [v1.30.4 metrics.go](https://github.com/kubernetes/kubernetes/blob/v1.30.4/staging/src/k8s.io/apiserver/pkg/util/flowcontrol/metrics/metrics.go#L50)。

采集间隔和查询步长都要确认。本例最初发现 Grafana 沿用了原数据源的 60 秒最小步长，因此为案例创建了独立的 15 秒数据源配置；已有综合看板保持原配置。否则即使 Prometheus 每 15 秒采集，页面仍可能只画出稀疏的点。

## 7. 复现、证据和清理

可运行 [run_case.py](https://github.com/runzhliu/aik8s/blob/main/examples/kubernetes-flow-control/apf-case/run_case.py) 复现四阶段流程。脚本使用显式 context，拒绝重用已经存在的实验对象名，带对照探针、中止条件和 finally 清理。完整说明见 [README](https://github.com/runzhliu/aik8s/tree/main/examples/kubernetes-flow-control/apf-case)。

本次结束后已确认：实验 Namespace、ServiceAccount、RBAC 和两个 APF 对象清理完成，API Server `/readyz` 正常，原指标采集恢复到 60 秒。监控数据、截图和客户端结果保留在 Pod 之外。

| 材料 | 用途 |
| --- | --- |
| [results.json](../../assets/kubernetes-apf-case/results.json) | 参数、阶段事件、状态码和客户端分位数 |
| [requests.csv](../../assets/kubernetes-apf-case/requests.csv) | 2159 条正式阶段请求，时间已转为相对秒，无地址或凭据 |
| [metrics.json](../../assets/kubernetes-apf-case/metrics.json) | 脱敏后的真实 Prometheus 时序、拒绝原因和排队峰值 |
| [Grafana JSON](https://github.com/runzhliu/aik8s/blob/main/examples/kubernetes-flow-control/apf-case/grafana-dashboard.json) | 导入后选择自己的 Prometheus 数据源 |
| [结果图生成代码](https://github.com/runzhliu/aik8s/blob/main/scripts/generate_apf_case_visuals.py) | 从 results.json 生成客户端结果图 |

## 8. 从这个案例延伸到稳定性建设

大型平台的控制面治理通常还包括高成本 LIST 管理、客户端限速与缓存、Operator 重试预算、关键控制器隔离，以及容量和升级验证。例如 Uber 的公开工程文章介绍了使用 APF 管理高成本 API 调用，并建设规模验证工具与分批扩缩容机制。参见 [Uber Kubernetes 迁移实践](https://www.uber.com/ca/en/blog/migrating-ubers-compute-platform-to-kubernetes-a-technical-journey/)。

本例展示的是一条小范围、可核对的工程闭环：明确风险与调用方 → 配置隔离边界 → 验证实际分类 → 观察客户端与服务端证据 → 解释版本差异 → 恢复并清理。它可以证明对 APF 生效机制的理解，但不能替代生产规模压测、升级演练或灾备恢复验证。

官方参考：[APF 概念](https://kubernetes.io/docs/concepts/cluster-administration/flow-control/)、[PriorityLevelConfiguration v1](https://kubernetes.io/docs/reference/kubernetes-api/flowcontrol/priority-level-configuration-v1/)。
