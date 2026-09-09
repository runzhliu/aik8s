---
title: Kubernetes 流控指南：APF、任务准入与推理服务限流
description: 图解 API Priority and Fairness、客户端限速、事件限流、资源配额、GPU 任务队列与模型网关限流，附 v1 配置和观测示例
status: evolving
last_reviewed: 2026-09-09
---

# Kubernetes 流控指南：APF、任务准入与推理服务限流

一个 GPU 集群可能同时遇到三种拥堵：Operator 大量查询资源，让 API Server 响应变慢；训练任务集中提交，争抢有限的 GPU；模型接口突发流量，导致首 Token 等待不断增加。它们都与请求超过可承载能力有关，但发生的位置和需要的控制手段不同。

Kubernetes 已经具备 API 请求分类、公平排队、并发预算和资源配额等机制。结合任务队列与推理网关，可以进一步管理任务何时开始，以及服务接纳多少用户请求。本文按实际请求路径解释这些能力，并给出配置和排查示例。

本文依据官方文档与 API 定义，配图属于架构说明和假设算例。示例不代表已经在生产集群执行过流控压测。

希望结合真实配置和监控验证行为，可继续阅读 [APF 隔离实测案例](../practices/apf-isolation-case.md)：四阶段实验、Grafana 截图，以及 Kubernetes 1.30.4 中零席位 Reject 仍放行的源码解释。

## 1. 先找到需要保护的对象

<picture>
  <source media="(max-width: 600px)" srcset="/assets/kubernetes-flow-control/01-three-layers-mobile.png">
  <img src="/assets/kubernetes-flow-control/01-three-layers.png" alt="API 请求、GPU 任务和模型请求的三层治理路径" width="1200" style="max-width:100%;height:auto">
</picture>

训练平台创建 Job 时会调用 API Server；任务开始后的训练计算不经过 APF；用户访问已经启动的模型服务，也不会因为 API Server 配置了流控，就自动获得业务限流。

| 控制对象 | 主要机制 | 控制单位 | 典型结果 |
| --- | --- | --- | --- |
| API Server 同时处理的工作 | APF | 并发席位、排队请求 | 分类、排队、执行或拒绝 |
| 客户端发起 API 请求的速度 | client-go RateLimiter | QPS、Burst | 客户端等待发送 |
| Event 写入风暴 | EventRateLimit | 事件请求速率 | 超额事件写入被拒绝 |
| Namespace 占用的资源 | ResourceQuota、LimitRange | CPU、内存、GPU、对象数量 | 超额或不合规请求被拒绝 |
| 任务何时取得资源 | Kueue、Volcano Queue | 工作负载、资源配额 | 排队、准入、共享或抢占 |
| 模型服务接纳的请求 | Gateway 与应用/引擎控制 | 速率、Token、并发、等待时间 | 接纳、排队、降级或拒绝 |

原生 `NetworkPolicy` 控制网络连接的允许/拒绝关系，没有通用的 HTTP QPS 或 Token 限流字段。网络带宽控制还要看 CNI 或节点能力，不能用 NetworkPolicy 代替应用限流。参见 [NetworkPolicy](https://kubernetes.io/docs/concepts/services-networking/network-policies/)。

## 2. 新版本 Kubernetes 的能力与迁移边界

截至本文核对时，官方发布页列出的最新稳定版本是 **1.37.0**。但 APF 已在 **1.29 稳定**，并非只有升级到最新版本才能使用。参见 [发布信息](https://kubernetes.io/releases/) 和 [APF 功能状态](https://kubernetes.io/docs/concepts/cluster-administration/flow-control/)。

| 能力或 API | 状态 | 实际影响 |
| --- | --- | --- |
| APF 与 `flowcontrol.apiserver.k8s.io/v1` | 1.29 起稳定；APF 默认启用 | 新配置使用 v1，仍需核对实际 API Server 设置 |
| APF `v1beta3` | 1.32 起停止提供 | 旧 YAML、客户端和 Helm 模板需要迁移 |
| `nominalConcurrencyShares: 0` | v1 中显式 0 不会被默认成 30 | 不能把 0 当作“采用默认值” |
| EventRateLimit | 仍标记 Alpha，默认关闭 | 升级后不会自动限制事件风暴 |
| Kueue、Volcano、Gateway 限流 | 独立项目或具体实现能力 | 需要单独安装、配置并核对版本 |

旧教程可能展示 `assuredConcurrencyShares` 或 `v1beta3`，应按目标版本迁移。具体要求见 [API 迁移指南](https://kubernetes.io/docs/reference/using-api/deprecation-guide/)，事件限流状态见 [EventRateLimit](https://kubernetes.io/docs/reference/access-authn-authz/admission-controllers/#eventratelimit)。

## 3. APF 怎样保护 API Server

### 3.1 分类之后，再分配执行机会

单一的 API Server 并发上限可以限制接纳的工作量，但无法充分区分关键控制器和批量查询脚本。APF 增加了分类和隔离，为不同类别分配执行容量，再在类别内部公平处理不同来源。

默认 APF 配置已经对 Leader Election、内置控制器等流量设置了相应分类。自定义规则的常见用途，是把批量读取、资源盘点或异常客户端放入可控的份额中，减少它们持续占满执行机会的影响。参见 [APF 原理](https://kubernetes.io/docs/concepts/cluster-administration/flow-control/)。

<picture>
  <source media="(max-width: 600px)" srcset="/assets/kubernetes-flow-control/02-apf-request-path-mobile.png">
  <img src="/assets/kubernetes-flow-control/02-apf-request-path.png" alt="APF 中 FlowSchema、并发预算与执行拒绝的关系" width="1200" style="max-width:100%;height:auto">
</picture>

### 3.2 FlowSchema：哪些请求属于同一类

`FlowSchema` 按用户、组、ServiceAccount，以及资源、操作和目标 Namespace 匹配请求，指向一个 `PriorityLevelConfiguration`。

- `matchingPrecedence` 决定匹配顺序，数值越小越先匹配；它不是 GPU 任务优先级，也不直接规定请求执行速度。
- `distinguisherMethod` 决定类别内部怎样区分流。`ByUser` 按请求身份划分；`ByNamespace` 按请求目标资源的 Namespace 划分，不能理解为客户端 Pod 所在 Namespace。

多个脚本共用同一 ServiceAccount 时，`ByUser` 无法再将它们区分为不同用户。需要独立治理的程序，应使用可识别的身份。字段定义见 [FlowSchema v1](https://kubernetes.io/docs/reference/kubernetes-api/flowcontrol/flow-schema-v1/)。

### 3.3 PriorityLevelConfiguration：分配多少容量

对于 `Limited` 类型，`nominalConcurrencyShares` 表示**名义并发份额**，不是绝对席位数，也不是每秒请求次数。某类别的名义容量与其份额占总份额的比例有关，实际运行还受总容量、取整和借入/借出约束影响。新增一个有正份额的类别，也可能改变已有类别的容量分配。

| 参数 | 含义 |
| --- | --- |
| `nominalConcurrencyShares` | 用于分配并发容量的名义份额 |
| `lendablePercent` | 最多可借出的名义容量比例 |
| `borrowingLimitPercent` | 可以借入的容量上限比例 |
| `limitResponse.type` | 容量不足时采用 Queue 或 Reject |
| `queues`、`handSize`、`queueLengthLimit` | 调整公平排队、流隔离和队列边界 |

字段及合法范围见 [PriorityLevelConfiguration v1](https://kubernetes.io/docs/reference/kubernetes-api/flowcontrol/priority-level-configuration-v1/)。APF 在各 API Server 实例执行流控，不能把名义份额视为整个高可用集群共享的精确 QPS 配额。

### 3.4 席位、WATCH 与有界排队

普通请求常按一个席位理解；返回大量对象的 LIST 可能占用多个席位。读取单个对象与全量扫描很多对象，即使 QPS 相同，控制面成本也可能不同。

WATCH 不能简单按“连接多久，就一直占一个席位”理解。APF 会处理其建立和可能的初始事件阶段，并核算相关通知开销。`exec`、日志跟随等部分 long-running 请求则不受该 APF 过滤器约束。参见 [APF 席位和 WATCH 说明](https://kubernetes.io/docs/concepts/cluster-administration/flow-control/#seats-occupied-by-a-request)。

APF 通过流划分和 Shuffle Sharding 等机制，减少某个高流量来源对其他流的干扰。有界队列可以吸收短暂突发，但持续过载仍会带来等待、超时和拒绝。它不会替代 etcd 容量优化、慢 Webhook 修复，也不会抢占正在运行的 GPU 任务。

## 4. 一个范围明确的 APF 配置

下面将专用 ServiceAccount `apf-demo/batch-reader` 对 `apf-demo` 中 Pod 的 GET/LIST 请求分到独立类别。Namespace、ServiceAccount 及读取权限需要事先存在；**FlowSchema 不授予 RBAC 权限。**

```yaml
apiVersion: flowcontrol.apiserver.k8s.io/v1
kind: PriorityLevelConfiguration
metadata:
  name: example-batch-reader
spec:
  type: Limited
  limited:
    nominalConcurrencyShares: 5
    lendablePercent: 0
    borrowingLimitPercent: 0
    limitResponse:
      type: Queue
      queuing:
        queues: 64
        handSize: 8
        queueLengthLimit: 20
---
apiVersion: flowcontrol.apiserver.k8s.io/v1
kind: FlowSchema
metadata:
  name: example-batch-reader
spec:
  matchingPrecedence: 1000
  priorityLevelConfiguration:
    name: example-batch-reader
  distinguisherMethod:
    type: ByUser
  rules:
    - subjects:
        - kind: ServiceAccount
          serviceAccount:
            namespace: apf-demo
            name: batch-reader
      resourceRules:
        - verbs: ["get", "list"]
          apiGroups: [""]
          resources: ["pods"]
          namespaces: ["apf-demo"]
          clusterScope: false
```

`matchingPrecedence: 1000` 应与实际已有规则比较，确认没有更早的规则截获请求。5 是份额，不是 5 QPS 或固定 5 个并发。本例关闭借入/借出以便解释边界，队列参数也只是教学示例，不能据此推断吞吐或最大等待时间。

这套规则不匹配跨所有 Namespace 的 LIST、WATCH 或其他资源，且使用独立自定义对象，不必直接修改系统默认分类。完整清单见 [apf-batch-reader.yaml](https://github.com/runzhliu/aik8s/blob/main/examples/kubernetes-flow-control/apf-batch-reader.yaml)。

可以先检查实际集群配置：

```bash
kubectl api-resources --api-group=flowcontrol.apiserver.k8s.io
kubectl get flowschemas
kubectl get prioritylevelconfigurations
```

服务端校验应明确目标 context：

```bash
kubectl --context <target-context> apply --dry-run=server \
  -f examples/kubernetes-flow-control/apf-batch-reader.yaml
```

dry-run 可以发现 API 和准入校验问题，但不会让策略生效，也不能证明实际请求分类正确。正式启用后，可结合响应中的 `X-Kubernetes-PF-FlowSchema-UID`、`X-Kubernetes-PF-PriorityLevel-UID`（前提是中间代理保留这些头）及 APF 指标定位命中对象。参见 [APF Observability](https://kubernetes.io/docs/concepts/cluster-administration/flow-control/#observability)。

默认 APF 对象可能由 API Server 自动维护，修改前应了解自动更新注解与强制配置规则。Webhook 在处理请求时再次调用 API Server，还可能形成递归等待或优先级倒置，需要单独分析依赖，不能将所有控制器统一压到最低份额。

## 5. 客户端限速：从源头减少请求压力

client-go 提供 QPS、Burst 和自定义 RateLimiter。官方源码中的默认常量为 QPS=5、Burst=10，但实际组件可能覆盖配置，因此不能据此推断所有客户端的限额。参见 [client-go REST 配置](https://github.com/kubernetes/client-go/blob/master/rest/config.go)。

```go
// cfg 已由 kubeconfig 或 InClusterConfig 构造。
// 数值仅作说明，不是所有 Operator 的推荐配置。
cfg.QPS = 10
cfg.Burst = 20
```

自定义 RateLimiter 可能覆盖 QPS/Burst 的作用。多个副本各自使用本地限速器时，聚合请求量还会增加，单客户端阈值不等于集群总阈值。

Controller/Operator 可以通过 Informer/Lister 缓存、减少全量 LIST、收窄查询范围、控制工作队列并发，以及有上限的退避减少压力。客户端重试要区分错误来源，不能把所有 429 都立即重试，否则会形成请求放大。

## 6. EventRateLimit 与资源配额分别控制什么

### 6.1 EventRateLimit：限制事件写入

异常组件持续创建或更新 Event 时，可以考虑事件专用限速。EventRateLimit 支持按 Server、Namespace、User 或 SourceAndObject 划分桶，需要配置 API Server 的准入插件与配置文件。当前仍为 Alpha、默认关闭，托管集群也可能不开放相关配置。见 [EventRateLimit](https://kubernetes.io/docs/reference/access-authn-authz/admission-controllers/#eventratelimit)。

限制事件写入也意味着部分 Event 可能缺失。应结合组件日志、指标和异常根因判断恢复情况，不能只凭 Event 变少就认为系统恢复正常。

### 6.2 ResourceQuota：限制资源总量

采用 `nvidia.com/gpu` 扩展资源的 Namespace 可以设置 GPU 和对象数量上限：

```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: example-team-budget
  namespace: apf-demo
spec:
  hard:
    requests.nvidia.com/gpu: "16"
    count/pods: "100"
    count/jobs.batch: "50"
```

配额不是每秒允许创建的数量，也不保证集群存在相应空闲 GPU。超额创建通常被拒绝，不会自动排队；Job 被允许创建后，也可能因 Pod 配额不足而创建不了子 Pod。参见 [ResourceQuota](https://kubernetes.io/docs/concepts/policy/resource-quotas/)。

LimitRange 可以约束单对象或容器的默认、最小和最大资源需求。ValidatingAdmissionPolicy 可以检查字段、标签和规格，但不能直接充当依赖全局计数器的请求速率限流器。参见 [LimitRange](https://kubernetes.io/docs/concepts/policy/limit-range/) 与 [ValidatingAdmissionPolicy](https://kubernetes.io/docs/reference/access-authn-authz/validating-admission-policy/)。

## 7. GPU 任务排队：Kueue 与 Volcano

“现在没卡先排着，空闲时允许借用，重要任务到来后按策略收回资源”，属于工作负载准入和调度治理。

Kueue 通过 LocalQueue、ClusterQueue 等对象管理配额和准入，结合对应的工作负载集成、拓扑配置与 AdmissionChecks，决定任务能否开始。Volcano Queue 则结合其调度体系提供资源队列和相应的共享、回收策略。参见 [Kueue Admission](https://kueue.sigs.k8s.io/docs/concepts/admission/) 与 [Volcano Queue](https://volcano.sh/docs/concepts/queue/)。

| 现象 | 优先检查 |
| --- | --- |
| 创建和查询 Job 的 API 调用让控制面变慢 | APF、客户端限速和 Controller 行为 |
| 大量任务等待 GPU，团队间占用不公平 | 队列、配额、优先级与借用策略 |
| 配额足够，但多卡任务无法放置 | 设备碎片、拓扑、Gang/TAS 和实际节点资源 |
| 紧急任务需要使用已有任务占用的 GPU | 队列/调度抢占和任务恢复策略 |

API 请求公平性和 GPU 分配公平性是两套机制。同一任务可以先成功调用 API，再等待队列准入，最后等待节点设备满足条件，每层都应提供独立的状态与等待时间指标。更多对象关系见 [队列、公平共享与多租户](../queue-multitenancy.md) 和 [GPU 调度](../gpu-scheduling.md)。

## 8. 推理限流：RPS 之外还要看并发与 Token

### 8.1 相同请求速率不等于相同后端压力

短回答和长文档生成占用引擎的时间不同。在可达到稳态、统计范围一致的前提下，可以用 `平均在途请求 ≈ 实际接纳速率 × 平均耗时` 理解并发。若流量长期超过处理能力，队列持续增长，稳态假设就不成立。

<picture>
  <source media="(max-width: 600px)" srcset="/assets/kubernetes-flow-control/03-rate-and-concurrency-mobile.png">
  <img src="/assets/kubernetes-flow-control/03-rate-and-concurrency.png" alt="相同请求速率下平均耗时与在途并发的关系；数字是假设算例" width="1200" style="max-width:100%;height:auto">
</picture>

平均接纳 20 req/s，耗时 0.2 秒时约有 4 个请求在途；耗时 10 秒时约有 200 个。这个算例说明长生成和流式请求为什么需要并发控制，不是模型吞吐实测。

### 8.2 网关与引擎共同控制接纳边界

Envoy Gateway 等实现提供本地与全局限流。本地计数的范围由代理配置决定，多副本下不能直接当作全服务总额；全局限流通常需要共享限流服务及状态后端。`BackendTrafficPolicy` 是具体实现的扩展资源，不是所有 Gateway 都原生支持的核心 API。参见 [本地限流](https://gateway.envoyproxy.io/docs/tasks/traffic/local-rate-limit/) 和 [全局限流](https://gateway.envoyproxy.io/docs/tasks/traffic/global-rate-limit/)。

| 约束 | 目的 |
| --- | --- |
| 租户/API Key 请求速率 | 避免单一调用方持续占用入口 |
| 输入 Token、最大输出 Token | 约束单请求工作量 |
| 运行请求数/活跃流数 | 控制长期占用后端的请求 |
| 等待请求数、最长等待时间 | 避免无界积压和过期工作 |
| 模型或租户 Token 预算 | 让配额更接近推理成本 |
| 超时、取消和重试预算 | 停止失去消费者的工作，限制重试放大 |

Token 配额应明确预计输入、预留最大输出还是实际生成后结算，因为请求前不知道最终输出长度。流式重试还要处理已经返回给用户的部分结果；入口、客户端与引擎的预算必须协调。

APF 不会根据模型 Token 自动调整配额，Kubernetes Service 也没有通用 Token 限流功能。前缀缓存命中还会改变相同长度请求的实际计算成本，见 [KV Cache 综述](../inference/kv-cache-overview.md) 和 [AI Gateway 与智能路由](../inference/gateway-routing.md)。

## 9. 观测指标与排查路径

### 9.1 APF 是否真的在排队或拒绝

除了 API Server CPU，还应看拒绝、排队和席位使用。指标以目标版本 `/metrics` 为准，参见 [APF Metrics](https://kubernetes.io/docs/concepts/cluster-administration/flow-control/#metrics)。

| 指标 | 用途 |
| --- | --- |
| `apiserver_flowcontrol_rejected_requests_total` | 按 FlowSchema、类别和原因定位拒绝 |
| `apiserver_flowcontrol_current_inqueue_requests` | 当前排队请求数 |
| `apiserver_flowcontrol_request_wait_duration_seconds` | APF 增加的等待时间 |
| `apiserver_flowcontrol_priority_level_seat_utilization` | 类别席位使用情况 |

按来源和原因聚合拒绝速率：

```promql
sum by (flow_schema, priority_level, reason) (
  rate(apiserver_flowcontrol_rejected_requests_total[5m])
)
```

对经典 Histogram，可计算排队等待的 P95：

```promql
histogram_quantile(
  0.95,
  sum by (le, priority_level) (
    rate(apiserver_flowcontrol_request_wait_duration_seconds_bucket[5m])
  )
)
```

查询假设采集目标没有重复计数。多集群 Prometheus 应增加集群标签筛选或分组；低流量下分位数可能不稳定。排队只是端到端延迟的一部分，还要结合执行时间、Webhook 与 etcd 指标。

### 9.2 先识别错误来自哪一层

| 症状 | 优先检查 | 常见误判 |
| --- | --- | --- |
| API 429，APF 拒绝计数同步增长 | 类别份额、队列与调用方 | 只增加客户端重试 |
| API 慢，但 APF 排队不明显 | etcd、Webhook、执行成本和网络 | 一律认定被 APF 限速 |
| Event 变少或写入失败 | 事件插件、写入方和聚合行为 | 将事件减少当作故障恢复 |
| 创建 Pod 提示 exceeded quota | ResourceQuota 与已占用量 | 调整 APF 期待获得 GPU |
| Workload 未准入或 Pod Pending | 队列、配额、设备与拓扑 | 只检查 API QPS |
| 模型接口 429 或等待很久 | Gateway、引擎队列、并发与 Token | 修改 API Server 并发上限 |

同一个 HTTP 429 可以由不同组件返回。应结合实际请求地址、响应头、日志与指标确认来源，再调整对应层策略。

## 10. GPU 平台的部署建议与材料说明

可以将治理责任分成三部分：

1. **控制面**：保留关键系统流量的保护，为批量程序使用独立身份；按真实请求成本配置 APF，并约束查询和重试行为。
2. **资源面**：用 Namespace 配额表达硬边界，用任务队列表达等待、借用与共享；同时检查多卡拓扑和实际容量。
3. **服务入口**：网关和引擎共同管理速率、Token、活跃请求、等待时间与取消传播。

阈值应依据实际负载和延迟目标调整。增加队列只能暂时延迟拒绝，提高并发也可能放大 etcd、Webhook 或 GPU 压力。配置需要明确请求何时接纳、最多等多久、谁返回失败，以及重试是否会制造更多工作。

本文配套提供 [APF 示例与说明](https://github.com/runzhliu/aik8s/tree/main/examples/kubernetes-flow-control) 和 [配图生成代码](https://github.com/runzhliu/aik8s/blob/main/scripts/generate_kubernetes_flow_control_visuals.py)。静态检查不能替代目标集群的服务端校验、规则匹配确认和性能观察。本文没有向运行中的集群应用策略，也没有修改已有业务流量。
