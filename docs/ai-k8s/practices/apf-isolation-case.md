---
title: APF 隔离实战：零席位 Reject 为什么仍会放行
description: 从请求分类、并发席位和公平排队讲解 APF 原理，再用 Kubernetes 1.30.4 四阶段实测、Grafana 截图和源码解释零席位拒绝与恢复
status: evolving
last_reviewed: 2026-09-09
---

# APF 隔离实战：零席位 Reject 为什么仍会放行

批量脚本、Operator 或资源盘点程序持续访问 Kubernetes API 时，平台需要能够限制某类请求的执行机会，同时保留其他调用方的访问能力。监控可以告诉我们请求变多了；APF 则提供请求分类、执行份额和有界排队机制。

这个案例在一个运行 Kubernetes **1.30.4** 的集群上，用两个专用 ServiceAccount 读取同一个 ConfigMap，实际验证“正常 → 零席位 Reject → 零席位 Queue → 恢复”。实验只产生少量只读流量，目标是验证隔离和恢复行为，不是探测 API Server 吞吐上限。

最值得注意的结果是：**该版本中，零席位 Reject 没有阻止低并发请求；零席位 Queue 则形成了排队和拒绝。** 本文保留这个与直觉不同的结果，并用实际响应、监控和版本源码互相核对。

## 先理解 APF：请求如何取得执行机会

APF 的全称是 **API Priority and Fairness，API 优先级与公平性**。它在每个 kube-apiserver 内管理请求的执行机会：先识别请求属于哪一类，再根据这类流量的执行预算决定接纳、等待或拒绝。它不增加 API Server 的实际算力，主要作用是让过载时的资源竞争更可控。[APF 官方原理](https://kubernetes.io/docs/concepts/cluster-administration/flow-control/)

### 一个生活例子：别让一家代办公司占满办事大厅

假设一个办事大厅有 **10 个窗口**。普通市民来补办一份证件，代办公司则一次带来几百份材料。如果所有人只排一条队，一家代办公司就可能让后来的市民等很久。

大厅于是调整规则：先在取号处识别办理人和业务类型，普通业务名义上分到 **8 个窗口**，批量代办业务分到 **2 个窗口**；批量业务内部再尽量分散不同公司的排队位置，避免一家公司的大量材料堵住其他公司。空闲窗口能不能临时调给忙碌的一类，要看另外的调配规则。

这是假设场景，用来对应 APF 的概念，数字不是本次实验配置：

| 办事大厅里的事情 | 对应的 APF 概念 |
| --- | --- |
| 取号时识别“谁来办、办什么” | FlowSchema 匹配身份和请求类型 |
| 个人业务、批量业务各有一套窗口与等待规则 | PriorityLevelConfiguration |
| 同属批量业务，但区分甲公司和乙公司的材料 | flow，通常结合 ByUser 等方式区分 |
| 同时能够办理多少份普通材料 | 席位对应的并发执行预算 |
| 等待区能容纳多少份尚未办理的材料 | 有界队列 |
| 空闲窗口临时支援另一类业务 | 席位借出与借入 |
| 没有办理能力时，让人等候或请其稍后再来 | Queue 或 Reject |

这里的“窗口”只类比执行机会，**APF 不会真的给某类请求预留专属 CPU 或线程**。接下来沿着“取号 → 分配窗口 → 等待 → 办理或拒绝”的顺序看配置，就更容易理解这次实验。

<picture>
  <source media="(max-width: 600px)" srcset="/assets/kubernetes-flow-control/02-apf-request-path-mobile.png">
  <img src="/assets/kubernetes-flow-control/02-apf-request-path.png" alt="APF 原理示意：FlowSchema 分类、优先级分配执行预算，然后接纳、排队或拒绝" width="1200" style="max-width:100%;height:auto">
</picture>

上图是机制示意。后面的客户端结果和 Grafana 截图才是本次实验数据；特别是“能否接纳”的判断，还要结合被测版本的具体实现。

### 请求分类：FlowSchema 决定命中哪条规则

FlowSchema 同时查看调用方身份和请求内容，例如“哪个 ServiceAccount，对哪个 Namespace 的哪类资源，执行 GET 还是 LIST”。多条规则都匹配时，优先选取 `matchingPrecedence` 数值较小的 FlowSchema，再通过其引用找到 PriorityLevelConfiguration。**这个数字决定分类顺序，不是给请求设置一个抢占分数。** FlowSchema 和 PriorityLevelConfiguration 都是 Kubernetes 提供的原生 API 资源，无需额外安装 CRD。[FlowSchema v1 定义](https://kubernetes.io/docs/reference/kubernetes-api/flowcontrol/flow-schema-v1/)

在分类内部，APF 还区分不同的 **flow**。一个 flow 由“匹配的 FlowSchema＋区分值”标识：`ByUser` 使用认证后的用户名，`ByNamespace` 使用请求目标资源的命名空间。不同 flow 可以共享同一个优先级的预算，但在排队时获得公平处理的机会。多个脚本共用同一个 ServiceAccount 时，`ByUser` 不会自动把它们区分成多个独立调用方。[FlowSchema 的 distinguisherMethod](https://kubernetes.io/docs/reference/kubernetes-api/flowcontrol/flow-schema-v1/#FlowSchemaSpec)

本例中，`batch-reader` 命中特定规则，`control-reader` 走其他规则。后面的响应头检查就是在验证这一步，而不是仅检查 YAML 是否存在。

对应到大厅：先确认代办公司的材料确实取到了“批量业务”的号，再讨论它该用几个窗口。取错了号，即使批量窗口的规则已经调整，也解释不了实际等待情况。

### 执行预算：席位、份额和 QPS 是三件事

**席位（seat）是 APF 的并发工作量计量单位。** 普通请求通常占一个席位；高成本 LIST 可能按工作量估计占多个席位。因此，“正在执行的请求数”与“正在使用的席位数”也可能不同。APF 对 WATCH 的席位占用有初始化阶段等专门处理，不能把长连接数直接当作被长期占满的席位数。[请求占用的席位](https://kubernetes.io/docs/concepts/cluster-administration/flow-control/#seats-occupied-by-a-request)

PriorityLevelConfiguration 的 `Limited` 类型配置执行预算和超额处理方式；`Exempt` 类型不受这种并发限制。以下字段只是在分配执行机会，不授予访问资源的权限：

| 概念或字段 | 回答的问题 | 本例怎样理解 |
| --- | --- | --- |
| `nominalConcurrencyShares` | 该类别参与分配时占多少相对份额 | 5 份额在被测环境中换算为 12 个名义席位 |
| 名义席位上限 | 按总容量和各类别份额，名义上分到多少席位 | 不等于字段中写的 5，也不是 5 QPS |
| `lendablePercent` | 本类别的名义容量允许借出多少 | 本例为 0，禁止借出 |
| `borrowingLimitPercent` | 本类别允许借入的额外容量上限是多少 | 本例为 0，禁止借入 |
| 当前席位上限 | 结合借用调整，此刻按多少容量调度 | 排障时需与名义值分别核对 |

名义容量按各类别份额比例计算，并涉及整数取整；借入和借出又会影响动态分配。单纯增加某个类别的份额，也会影响其他类别可分得的比例。`borrowingLimitPercent` 不设置与显式设置为 0 的含义不同：前者不设置这一借入上限，后者禁止借入。[PriorityLevelConfiguration v1 定义](https://kubernetes.io/docs/reference/kubernetes-api/flowcontrol/priority-level-configuration-v1/)

回到大厅，批量业务的 2 个窗口表示“最多同时办多少份普通材料”的容量概念，不能理解为“每分钟只接待 2 人”。一份材料办 1 分钟和办 20 分钟，会产生完全不同的排队情况。若普通窗口暂时空闲，批量窗口能否获得支援，又取决于借用规则。

一个假设算例能说明它与 QPS 的区别：若每个请求始终占 1 个席位，实际占用时间为 50 ms，5 req/s 对应的平均席位需求约为 `5 × 0.05 = 0.25`；若占用时间增长到 5 秒，同样的请求速率就需要约 25 个席位。这是稳定负载下的简化估算，不是本次实测的席位测量值，也不能用客户端端到端耗时直接代入。因此，出现排队时既要检查请求是否增多，也要检查 API Server 的后续处理是否变慢。

### 公平排队：隔离类别，也减少同类调用方之间的干扰

有限优先级内部可以配置多个队列。APF 使用 **shuffle sharding**：根据 flow 标识确定一小组候选队列，再选择其中较短的队列入队。这样，一个持续发送大量请求的 flow 不容易占满所有队列。出队时，公平调度算法结合估计工作量选择推进的队列，而不是把所有来源简单拼成一条全局 FIFO。[v1.30.4 队列分配与分发实现](https://github.com/kubernetes/kubernetes/blob/v1.30.4/staging/src/k8s.io/apiserver/pkg/util/flowcontrol/fairqueuing/queueset/queueset.go)

三个参数控制不同边界：`queues` 是队列数，`handSize` 是每个 flow 的候选队列数，`queueLengthLimit` 是单个队列的等待长度上限。增加队列或等待长度会改变内存开销、隔离效果和等待体验，**不会增加执行容量**。公平性也不意味着每个用户都获得严格相等的 QPS。[QueuingConfiguration 定义](https://kubernetes.io/docs/reference/kubernetes-api/flowcontrol/priority-level-configuration-v1/#QueuingConfiguration)

本例特意使用 `queues: 1`、`handSize: 1`、`queueLengthLimit: 2`，方便观察两个等待位置。**这个实验验证了分类隔离、排队和恢复，没有验证多个 flow 之间的 shuffle sharding 公平性。**

大厅里的对应做法是：把甲公司、乙公司的材料尽量分散到不同等待队伍，降低甲公司大批提交时对乙公司的干扰。但多放几排等候椅，只能容纳更多等待者，并不会多出办事窗口。

### 超额处理：Reject 是“不等”，Queue 是“有限等待”

`limitResponse.type` 决定的是请求此刻不能执行时怎么办：

| 模式 | 能被接纳时 | 不能立即执行时 |
| --- | --- | --- |
| Reject | 进入执行 | 不排队，返回拒绝 |
| Queue | 按队列调度机制取得执行机会 | 在有界队列等待；队列满或等待超时则拒绝 |

因此，`Reject` 并不表示“匹配该规则的请求全部拒绝”。本例中的疑问应拆成两步：**先看请求为什么被判定为可以接纳，再看无法接纳时采用哪种处理方式。** 这也是第 4、5 节分别核对无队列路径和排队分发路径的原因。[LimitResponse 定义](https://kubernetes.io/docs/reference/kubernetes-api/flowcontrol/priority-level-configuration-v1/#LimitResponse)

对应到大厅，Reject 更像“有窗口就办理，没窗口就请稍后再来”；Queue 则是“没窗口时先去有限的等待区”。两种规则都没有取消办理人的资格。真正禁止某个账号访问资源，应在授权机制上处理，例如调整 RBAC，而不是依赖排队模式。

队列和执行预算由各个 API Server 分别维护。多副本控制面中，同一份策略会在各实例上工作，但不会形成一个集群共享的全局队列。监控应保留 `instance` 等实例维度；一个实例拥堵、另一个空闲，也可能与请求分布不均有关。

这就像同一座城市的两个办事大厅采用相同规则，但各自取号、各自排队；一处排满，不会自动把正在等待的人转到另一处。

### 用原理串起后面的监控证据

阅读实测时，按照请求生命周期核对：

1. **分类是否正确**：响应头 UID 是否对应实验 FlowSchema 和优先级。
2. **预算是否变化**：名义席位、当前席位上限及借用设置是否符合预期。
3. **请求停在哪一步**：排队数、分发计数、拒绝原因是否相互印证。
4. **调用方实际得到什么**：最终状态码和逐条耗时是否与服务端观测一致。

APF 分发成功只表示请求取得了后续处理机会，不等于最终 HTTP 200。等待直方图、执行计数和客户端结果分别描述不同阶段，后面的案例也会展示标签语义和直方图插值带来的误读。

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

## 9. 生产配置建议：给批量业务有限的窗口，而不是关掉大厅

前面的零席位配置用于暴露边界行为。生产治理通常需要的是“批量任务慢一点，但仍然能完成，关键控制请求继续取得进展”。对应办事大厅，就是保留有限的批量窗口、控制等候人数，并让代办公司按节奏提交材料。

以下是基于机制和本例结果给出的工程建议。配置属于**上线前需要验证的起点**，没有在本次实验中执行，不能把示例数值当作所有集群的生产默认值。

### 9.1 先按调用方和请求成本划分，再考虑调大容量

| 流量 | 建议做法 | 需要避免的问题 |
| --- | --- | --- |
| Leader Election、节点与关键控制器流量 | 先核对并保留系统已有分类，再检查其等待和错误预算 | 用宽泛规则意外覆盖系统流量 |
| 发布平台、日常运维工具 | 按身份确认实际分类；有业务必要时再建立独立优先级 | 把所有人工操作都设为 Exempt，导致异常脚本绕过限制 |
| 资源盘点、报表、批量同步 | 使用独立 ServiceAccount，将高成本 LIST 放入非零小份额类别 | 多个程序共用高权限账号，既难归因，也难按 flow 隔离 |
| 单个异常客户端 | 先降低并发或停止任务；需要禁止访问时调整授权 | 把零份额当成永久封禁手段 |

优先新增命名明确的自定义 FlowSchema 和优先级，缩小匹配范围。匹配条件可以先限定到“一个账号、一个业务 Namespace、两类资源的 LIST”，验证后再扩展。`ByUser` 的隔离粒度取决于认证身份，不会按进程或 Pod 自动拆分；也不需要为每个 Pod 创建一套优先级对象。

系统自带 APF 对象存在自动维护机制，不能把修改默认对象当成普通业务配置；确需修改时，应核对对象是否属于强制配置、`apf.kubernetes.io/autoupdate-spec` 的规则和升级行为。APF 配置权限应由平台管理，不能让普通租户自行把流量送入 Exempt 类别。[默认配置及维护规则](https://kubernetes.io/docs/concepts/cluster-administration/flow-control/#default-configuration)

### 9.2 一份批量 LIST 的起始配置

假设平台用 `platform-ops/inventory-reader` 盘点 `app-prod` 中的 Pod 和 Deployment。下面只治理它的 LIST；其他请求继续按已有 FlowSchema 分类。两个 Namespace 和 ServiceAccount 都是假设名称，授权需单独通过 RBAC 配置。

```yaml
apiVersion: flowcontrol.apiserver.k8s.io/v1
kind: PriorityLevelConfiguration
metadata:
  name: platform-batch-read
spec:
  type: Limited
  limited:
    nominalConcurrencyShares: 5
    lendablePercent: 0
    borrowingLimitPercent: 0
    limitResponse:
      type: Queue
      queuing:
        queues: 32
        handSize: 4
        queueLengthLimit: 10
---
apiVersion: flowcontrol.apiserver.k8s.io/v1
kind: FlowSchema
metadata:
  name: platform-inventory-list
spec:
  matchingPrecedence: 1000
  priorityLevelConfiguration:
    name: platform-batch-read
  distinguisherMethod:
    type: ByUser
  rules:
    - subjects:
        - kind: ServiceAccount
          serviceAccount:
            namespace: platform-ops
            name: inventory-reader
      resourceRules:
        - verbs: [list]
          apiGroups: [""]
          resources: [pods]
          namespaces: [app-prod]
          clusterScope: false
        - verbs: [list]
          apiGroups: [apps]
          resources: [deployments]
          namespaces: [app-prod]
          clusterScope: false
```

这个模板适合从受控的批量读取入口开始验证。**跨所有 Namespace 的 LIST 不会因为账号相同就自动被上述命名空间限定规则覆盖**，需要按实际 URL 和请求分类另行设计。`matchingPrecedence: 1000` 也只有在核对现有匹配规则后才有意义；必须用真实账号的响应头验证命中。

| 示例参数 | 选择意图 | 上线前怎样校准 |
| --- | --- | --- |
| 非零份额 5 | 保留正常执行机会 | 核对每个 API Server 实际名义席位、当前上限及批量任务完成时间；5 不代表固定百分比 |
| 借入 0、借出 0 | 首轮限制动态借用，方便观察分类容量 | 评估后再单独调整；批量类别允许借入多少，需要同时看关键类别在竞争时的表现 |
| Queue | 允许短时突发等待 | 若业务不能容忍等待，并且客户端能正确处理 429，可评估 Reject |
| 32 个队列、候选 4 个 | 为将来多个独立身份共享此类别预留公平排队能力 | 根据 flow 数、竞争模式和内存成本调整；当前单账号不能证明多 flow 公平性 |
| 每队列等待 10 个 | 对等待积压设置边界 | 单实例该类别最多约 320 个队列等待位置，不保证某个 flow 能用满；结合等待预算压低积压 |

不能把 `queueLengthLimit` 当成等待秒数，也不应靠不断加长队列吸收持续过载。席位分配与排队字段的准确语义见 [PriorityLevelConfiguration v1](https://kubernetes.io/docs/reference/kubernetes-api/flowcontrol/priority-level-configuration-v1/)。

### 9.3 客户端要一起改，避免拒绝后流量反而变大

把 APF 当作服务端保护层，同时在盘点程序中限制并发、QPS 和突发量。客户端收到 429 后应遵守服务端给出的 `Retry-After`（若存在），采用带抖动的退避，并设置总重试次数或总时间预算；不能立即无限重试，也不能让多层 SDK 各自重复重试。[Kubernetes API 的客户端重试建议](https://kubernetes.io/docs/reference/using-api/api-concepts/#watch-cache-initialization)

对于反复扫描同一批资源的程序，优先评估 informer/watch 缓存，减少周期性全量 LIST；确需全量读取时，使用适当分页，并验证资源类型、缓存路径及目标版本的行为。还要限制任务重启后的集中重建流量，避免所有实例同时重新 LIST。**应用侧控制提交速度，APF 控制进入执行的机会，两者需要同时生效。**

### 9.4 按类别和实例观察，再小步调整

先记录正常与业务高峰时的基线，包括关键控制器请求延迟、错误、协调积压，以及批量任务的完成期限。上线后至少同时观察下面几组证据，而不是只看总体 429 比例：

| 观测组合 | 判断与处理方向 |
| --- | --- |
| 分类响应头＋FlowSchema 状态 | 先排除未匹配或引用无效；不要通过增加份额掩盖配置未生效 |
| 当前席位上限＋席位占用＋排队数 | 确认是该类别容量紧张，还是某个 API Server 请求分布不均 |
| `queue-full`＋`time-out`＋客户端等待 | 区分突发积压与长时间得不到执行机会；先降低负载，再评估份额和队列 |
| 关键控制器的延迟、错误和协调进度 | 验证受保护业务确实继续工作；批量业务的主动拒绝不应单独触发全站故障判断 |
| API Server CPU/内存、etcd 和 Webhook 延迟 | 多个类别同时变慢时，检查后端瓶颈；调大 APF 上限可能进一步放大过载 |

例如，下面的查询保留 API Server 实例和拒绝原因，便于判断是否只有某个后端拥堵。多集群数据源还应加入实际的集群标签过滤。

```promql
sum by (instance, reason) (
  rate(apiserver_flowcontrol_rejected_requests_total{
    priority_level="platform-batch-read"
  }[5m])
)
```

告警阈值应结合关键业务的延迟预算和允许持续时间设定；批量类别发生可预期的 429，与关键控制器无法推进不是同一级别的问题。不要直接把本例 90 秒阶段中的 P95 或拒绝比例抄成生产阈值。

### 9.5 灰度和回滚要有明确顺序

1. **保存基线和上一版配置。** 核对目标版本、全部相关 FlowSchema 的匹配顺序、优先级份额和现有请求分类；配置纳入版本管理。
2. **先缩小匹配面。** 新建未被引用的优先级并确认其状态和容量变化，再接入仅匹配专用账号的 FlowSchema。即使尚未接入流量，新增非零份额也会改变其他类别的名义分配，需要观察。
3. **从少量真实请求逐步加压。** 校验响应头，保留不匹配该规则的独立对照探针；覆盖普通读取、高成本读取、突发和恢复。服务端 dry-run 只能验证配置是否可接受，不能证明调度行为和性能正确。
4. **按业务预算决定继续或回滚。** 关键控制器错误或等待超出预算、批量任务持续无法完成、出现非预期匹配时，先降速或暂停制造负载的客户端，再恢复上一版策略，检查排队恢复和控制面健康。
5. **最后清理对象。** 确认不再被引用和使用后，再删除新建对象，并同步 GitOps 的期望配置。直接删除 FlowSchema 会让新请求落入其他规则，可能把异常流量重新放回共享类别，不能把删除对象本身当作完整回滚。

升级 Kubernetes、调整 API Server 副本数或引入新的大型 Operator 后，应重新验证分类和容量边界。生产目标是让关键请求持续取得进展，同时让批量请求的等待、拒绝和恢复都可解释；这个目标需要配置、客户端行为与监控一起验证。

官方参考：[APF 概念](https://kubernetes.io/docs/concepts/cluster-administration/flow-control/)、[PriorityLevelConfiguration v1](https://kubernetes.io/docs/reference/kubernetes-api/flowcontrol/priority-level-configuration-v1/)。
