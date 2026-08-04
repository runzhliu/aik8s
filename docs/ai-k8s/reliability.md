---
title: 可靠性、Checkpoint 与故障恢复
description: AI 作业的故障模型、RPO、RTO、优雅退出、Spot 和恢复演练
status: stable
last_reviewed: 2026-08-02
---

# 可靠性、Checkpoint 与故障恢复

AI 工作负载经常把“Pod 重启成功”误认为“业务恢复成功”。对于运行数天的训练、占用多机多卡的推理副本和数百 GB 的模型，真正需要衡量的是进度损失、恢复耗时、数据一致性和服务容量。

## 1. 先定义故障域

| 故障域 | 示例 | 平台应对 |
| --- | --- | --- |
| 进程 | OOM、框架异常、死锁 | 重启 Rank/Worker、诊断转储 |
| Pod | 驱逐、镜像或挂载失败 | Controller 重建、就绪探针 |
| 节点 | GPU XID、内核崩溃、网卡故障 | 隔离节点、重新调度、恢复 |
| 机架/网络域 | 交换机或供电故障 | 跨域副本、容量冗余 |
| 集群 | 控制面、CNI、CSI 故障 | 多集群恢复、备份、GitOps |
| 区域 | 云区域或机房不可用 | 跨区域制品与灾备策略 |
| 数据/模型 | 损坏、误删、版本错误 | 不可变版本、校验、对象版本化 |

恢复策略必须匹配故障域。只设置 `restartPolicy` 无法解决节点或集群级问题。

## 2. 用 RPO 和 RTO 描述训练恢复

- **RPO**：最多允许丢失多少训练进度；
- **RTO**：从故障发生到恢复有效训练需要多久。

训练的恢复时间通常包括：

```text
故障发现
  + 任务终止/清理
  + 重新排队与扩容
  + 镜像和数据预热
  + Checkpoint 下载/重分片
  + 通信组重建
  + 恢复到稳定吞吐
```

如果只统计 Pod 重新 Running 的时间，RTO 会被严重低估。

## 3. Checkpoint 需要保存什么

完整恢复通常需要：

- 模型参数；
- 优化器状态；
- 学习率调度器；
- global step / epoch；
- 随机数状态；
- 数据采样器位置；
- 混合精度 scaler；
- 并行和分片元数据；
- 数据、代码、镜像与配置版本。

只保存模型权重适合推理发布，不一定能无损继续训练。

## 4. Checkpoint 保存频率怎么算

保存越频繁，恢复进度损失越小，但写入开销越大。可以用以下信息确定周期：

- 任务平均故障间隔；
- 单次 Checkpoint 保存耗时；
- 每小时 GPU 成本；
- 可接受的最大进度损失；
- 存储吞吐和保留成本。

一个实用做法是同时保留：

1. 高频本地或近端 Checkpoint；
2. 较低频的远端持久 Checkpoint；
3. 关键里程碑的长期归档。

本地副本缩短恢复，远端副本覆盖节点和集群故障。

## 5. 分布式 Checkpoint 与重分片

大模型不适合由 Rank 0 汇总后单文件保存，否则内存和网络会形成瓶颈。PyTorch Distributed Checkpoint 支持多个 Rank 并行读写，并能在加载时重分片，使保存拓扑与恢复拓扑不必完全相同。参考：[PyTorch Distributed Checkpoint](https://docs.pytorch.org/docs/main/distributed.checkpoint.html)

平台仍需解决：

- 多文件何时视为完整；
- 清单和完成标记如何原子发布；
- 异步保存时训练状态是否一致；
- 新旧版本框架能否互相读取；
- 不完整上传如何清理；
- 恢复前如何校验摘要。

## 6. 弹性训练的边界

Torch Distributed Elastic、Ray Train 等可以在 Worker 失败时重启或改变规模，但“弹性”不代表任意时刻无损缩放。

需要确认：

- 框架是否支持成员变化；
- global batch size 改变后学习率如何调整；
- 数据采样是否重复或遗漏；
- Rendezvous 服务是否高可用；
- Worker 重启是从当前状态还是最近 Checkpoint；
- 最大重试是否会掩盖永久性故障。

参考：[Torch Distributed Elastic](https://docs.pytorch.org/docs/2.13/distributed.elastic.html)、[Ray Train Fault Tolerance](https://docs.ray.io/en/latest/train/user-guides/fault-tolerance.html)

## 7. Spot 与抢占式节点

Spot GPU 可能显著降低成本，但必须把中断当作正常事件：

- 任务模板捕获终止信号；
- 保存紧急 Checkpoint 的时间小于终止通知窗口；
- 队列知道哪些任务允许使用 Spot Flavor；
- 按需容量能够承担关键任务；
- 同一训练任务不要把所有副本放在相同故障域；
- 统计节省金额与重算损失，而不是只看折扣。

短任务、可重试批推理和频繁 Checkpoint 的训练更适合 Spot；严格低延迟在线服务通常需要稳定底线容量。

## 8. 推理服务的高可用

单个模型服务需要考虑：

- 至少两个可独立失效的副本；
- Pod 反亲和或拓扑分散；
- Readiness 在模型真正加载后才成功；
- Startup Probe 覆盖长时间模型加载；
- PreStop 与足够的终止宽限时间排空流式请求；
- 发布期间保留旧版本容量；
- 网关在过载时限流，而不是无限排队。

对于跨多节点的 LeaderWorkerSet，一个副本是整组 Pod，而不是单个 Pod。容量规划和 PDB 都要以副本组为单位理解。

## 9. PDB 能做什么，不能做什么

PodDisruptionBudget 约束通过 Eviction API 发起的自愿中断，例如节点 drain；它不能阻止硬件故障，也不会直接限制 Deployment 的滚动更新。参考：[Kubernetes Disruptions](https://kubernetes.io/docs/concepts/workloads/pods/disruptions/)

常见错误：

- 单副本服务设置 `minAvailable: 1`，导致节点永远无法 drain；
- PDB 选择器与真实 Pod 标签不匹配；
- 多个 PDB 意外重叠；
- 不健康 Pod 阻塞维护；
- 只设置 PDB，却没有跨节点的真实副本。

## 10. GPU 节点故障隔离

检测到持续 XID、ECC、NVLink 或 PCIe 错误时，建议流程：

1. 标记节点不可调度；
2. 记录受影响任务和设备 UUID；
3. 让任务保存或从 Checkpoint 恢复；
4. 执行 DCGM 诊断和硬件检查；
5. 根据错误类型 reset GPU 或重启节点；
6. 通过基准测试后再解除隔离；
7. 将故障和维修记录关联到资产。

不要让自动重启在同一故障 GPU 上无限循环。

## 11. 数据与控制面的备份

需要备份的不只是 etcd：

- Git 中的平台声明；
- CRD 与关键自定义资源；
- Kueue 配额和策略；
- 模型注册表元数据；
- 对象存储中的模型、数据版本和 Checkpoint；
- 密钥管理系统中的恢复流程；
- 镜像与 Helm Chart；
- DNS、证书和外部负载均衡配置。

如果恢复依赖已经故障的同一个集群内 Registry 或 Secret，就不是真正的灾备。

## 12. 故障演练矩阵

| 演练 | 预期结果 |
| --- | --- |
| 删除一个训练 Worker | 任务失败可解释，并从最近 Checkpoint 恢复 |
| 关停一个 GPU 节点 | 任务重新排队，不留下孤儿资源 |
| 模拟对象存储超时 | 有界重试，不产生损坏 Checkpoint |
| drain 推理节点 | 请求排空，容量仍满足 SLO |
| 发布坏模型 | 自动停止或快速回滚 |
| 控制面短时不可用 | 运行中推理不立即中断，恢复后状态收敛 |
| 丢失一个集群 | 能从另一环境取得镜像、模型和配置 |

演练要在可控环境开始，并记录实际 RPO/RTO，而不是只记录“最终恢复”。

## 13. Runbook 应包含什么

- 告警含义和影响范围；
- 第一个确认命令和 Dashboard；
- 哪些动作安全，哪些需要审批；
- Checkpoint 与回滚位置；
- 节点隔离和恢复步骤；
- 升级到人工处理的条件；
- 事件结束后的数据保留和复盘项目。

## 14. 上线清单

- [ ] 训练和推理分别定义 RPO/RTO；
- [ ] Checkpoint 包含继续训练所需的完整状态；
- [ ] 做过不完整 Checkpoint、跨节点和跨拓扑恢复测试；
- [ ] 抢占式任务能在通知窗口内保存；
- [ ] 推理副本跨节点或故障域分散；
- [ ] PDB 不会阻塞正常节点维护；
- [ ] 故障 GPU 会自动隔离而不是无限重试；
- [ ] 镜像、模型、配置和密钥恢复不依赖单一集群；
- [ ] 定期进行故障演练并记录实际 RPO/RTO。

## 延伸阅读

- [PyTorch Distributed Checkpoint](https://docs.pytorch.org/docs/main/distributed.checkpoint.html)
- [Torch Distributed Elastic](https://docs.pytorch.org/docs/2.13/distributed.elastic.html)
- [Ray Train Fault Tolerance](https://docs.ray.io/en/latest/train/user-guides/fault-tolerance.html)
- [Kubernetes Disruptions](https://kubernetes.io/docs/concepts/workloads/pods/disruptions/)
