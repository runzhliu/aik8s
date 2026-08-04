---
title: GPU 成本、容量规划与 FinOps
description: AI 平台的成本归属、单位经济性、容量预测和弹性策略
status: stable
last_reviewed: 2026-08-02
---

# GPU 成本、容量规划与 FinOps

GPU 平台的成本优化不是把利用率推到 100%。过度压缩容量会增加排队和尾延迟，错误的共享会损害模型性能，而便宜的 Spot 节点也可能因为反复重算变得更贵。

正确做法是把成本与训练产出、推理 Token、SLO 和故障损失放在一起衡量。

## 1. 建立完整成本模型

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

只看 GPU 实例账单，会忽略模型反复下载、跨区训练、Checkpoint 存储和平台复杂度。

## 2. 分清 Allocation、Usage 和产出

| 维度 | 问题 | 示例 |
| --- | --- | --- |
| Allocation | 调度系统为任务保留了多少 | 8 张 GPU × 10 小时 |
| Usage | 设备实际工作了多少 | 平均 SM active、显存、功耗 |
| Output | 产生了什么业务价值 | tokens、samples、成功实验、请求 |

Allocation 决定账单，Usage 帮助发现浪费，Output 才能比较不同模型和平台方案。

OpenCost 提供 Kubernetes 成本分配的开放规范，能按 namespace、Pod、Job、Label 等维度区分工作负载、共享和闲置成本。参考：[OpenCost Overview](https://opencost.io/docs/)、[OpenCost Specification](https://opencost.io/docs/specification/)

## 3. 统一资源归属标签

至少标准化：

```yaml
metadata:
  labels:
    platform.example.com/team: search
    platform.example.com/environment: production
    platform.example.com/workload-type: training
    platform.example.com/model: reranker
    platform.example.com/cost-center: cc-1042
```

标签值要低基数、可验证，并通过准入策略自动补齐。不要依赖用户自由输入的项目名做财务对账。

## 4. 训练的单位经济性

训练可以使用：

```text
每百万样本成本 = 训练总成本 / 处理样本数 × 1,000,000
每十亿 Token 训练成本 = 训练总成本 / Token 数 × 1,000,000,000
有效 GPU 小时 = GPU 数 × 真正训练时间
失败损失 = 故障前未保存时间 × GPU 数 × GPU 时价
```

比较实验时还要保证目标质量一致。更快达到较差 Loss 的方案，不一定比稍慢但达到目标质量的方案好。

MLPerf Training 的核心思想也是测量达到目标质量所需时间，而不是只测单步峰值。参考：[MLPerf Training](https://mlcommons.org/benchmarks/training/)

## 5. 推理的单位经济性

```text
每百万 Token 成本
  = 服务总成本 / 输出与计费 Token × 1,000,000

每个成功请求成本
  = 服务总成本 / 满足 SLO 的成功请求数
```

同时按以下维度拆分：

- 模型与量化版本；
- 输入/输出长度；
- 在线、批量与交互优先级；
- 峰值和非峰值时段；
- 缓存命中与未命中；
- 满足 SLO 与超时请求。

吞吐增加但 TTFT 超标，不算有效的成本下降。

## 6. 训练容量怎么估

先收集任务画像：

- 各 GPU 型号需求；
- 单任务 GPU 数和运行时长分布；
- 到达率与截止时间；
- 可抢占比例；
- 拓扑和 RDMA 要求；
- Checkpoint/数据预热时间。

容量不仅要满足平均 GPU 数，还要满足“大任务同时获得连续资源”的概率。高度碎片化的 64 张空闲 GPU，可能无法启动一个要求同一网络域 32 卡的任务。

## 7. 推理容量怎么估

推理要用压测得到每个副本在目标 SLO 下的安全吞吐：

```text
所需副本
  = 峰值有效请求率 / 单副本安全吞吐
  × 冗余系数
```

安全吞吐应覆盖真实的输入/输出长度分布，而不是只用短 Prompt。还需要预留：

- 模型发布期间的新旧版本重叠；
- 节点故障或维护；
- 扩容和模型加载时间；
- 突发流量；
- 网关和下游工具故障造成的排队。

## 8. 四层弹性不要互相打架

```text
请求层：并发、动态 Batch、限流
Pod 层：HPA / KEDA / 自定义 Autoscaler
节点层：Cluster Autoscaler / Karpenter
队列层：Kueue 准入、Flavor 与优先级
```

需要明确时间尺度：请求层以毫秒到秒反应，Pod 层通常分钟级，GPU 节点启动可能更久，队列则决定哪些需求值得触发扩容。

如果每层都根据短期指标独立扩缩，容易产生震荡、重复扩容和昂贵的空节点。

## 9. 提高利用率的优先顺序

建议按风险从低到高推进：

1. 修复数据和通信瓶颈；
2. 减少镜像/模型冷启动；
3. 调整 Batch、并行和量化；
4. 清理僵尸任务和过大资源请求；
5. 使用队列借用和更好的 Bin Packing；
6. 为小推理或开发任务引入 MIG/时间共享；
7. 训练与推理混部；
8. 使用 Spot 和主动抢占。

前几项通常不改变隔离模型，收益更稳；后几项需要更成熟的可观测和恢复能力。

## 10. 闲置不一定是浪费

以下空闲容量可能是合理的：

- 在线服务的故障冗余；
- 大模型发布的临时重叠；
- 等待大规模 Gang 任务形成连续资源；
- 节点启动时间过长，需要保留 warm pool；
- 维护或故障域预留；
- 业务明确购买的低延迟保障。

应把闲置拆成“有意预留”和“不可解释浪费”，不能一刀切回收。

## 11. Spot 与预留如何组合

| 容量类型 | 适合 | 不适合 |
| --- | --- | --- |
| 预留/自有 | 在线底线、长训练、稳定需求 | 短期峰值全部依赖 |
| 按需 | 突发、发布重叠、临时恢复 | 长期稳定负载全部使用 |
| Spot | 可恢复训练、批推理、容错数据处理 | 无 Checkpoint 的长任务、关键在线底线 |

衡量 Spot 收益时使用：

```text
净节省 = 原按需成本 - Spot 成本 - 重算成本 - 额外运维成本
```

## 12. 预算与保护栏

- namespace/team 月度预算与预警；
- 单任务最大 GPU 数和最长运行时间；
- 未归属资源自动标记并提醒；
- 高价 Flavor 需要显式理由或审批；
- 开发环境夜间回收；
- 闲置 Notebook 自动暂停；
- 模型服务设置最大副本和扩容速率；
- 跨区数据读取和公网流量单独告警。

预算保护不应在没有通知的情况下直接终止生产服务。

## 13. 推荐周报

| 维度 | 指标 |
| --- | --- |
| 容量 | 总 GPU、可用、故障、维护、各 Flavor 分布 |
| 利用 | Allocation、SM active、显存、功耗、闲置 |
| 队列 | 等待时间、拒绝、抢占、借用比例 |
| 训练 | 成功率、有效 GPU-hours、失败重算成本 |
| 推理 | 每百万 Token 成本、满足 SLO 的吞吐 |
| 租户 | 成本、配额、预算偏差、未归属资源 |
| 优化 | 本周回收、节省以及对 SLO 的影响 |

## 14. 上线清单

- [ ] 所有 GPU 工作负载都能归属到团队和成本中心；
- [ ] Allocation、Usage 和业务产出分别可见；
- [ ] 训练按目标质量和有效 GPU-hours 比较；
- [ ] 推理成本只统计满足 SLO 的有效请求；
- [ ] 容量模型考虑大任务碎片、拓扑和冷启动；
- [ ] 队列、Pod、节点和请求层扩缩容时间尺度明确；
- [ ] Spot 节省扣除了重算和运维成本；
- [ ] 有意冗余与不可解释闲置分开；
- [ ] 预算策略不会意外中断生产。

## 延伸阅读

- [OpenCost Documentation](https://opencost.io/docs/)
- [OpenCost Specification](https://opencost.io/docs/specification/)
- [MLPerf Training](https://mlcommons.org/benchmarks/training/)
- [Kueue Overview](https://kueue.sigs.k8s.io/docs/overview/)
