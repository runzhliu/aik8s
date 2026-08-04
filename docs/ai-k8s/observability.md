---
title: GPU、训练与推理可观测性
description: 从用户请求和训练作业到 Pod、GPU、网络与存储的指标和追踪体系
status: evolving
last_reviewed: 2026-08-02
---

# GPU、训练与推理可观测性

AI 平台最常见的可观测性误区，是只安装 Prometheus 和一个 GPU Dashboard。真正可用的系统必须把基础设施、调度、训练进度、推理请求和模型质量连接到同一条证据链。

## 1. 五层可观测模型

```text
业务与模型质量：正确率、拒答率、用户反馈、安全评估
请求与服务：TTFT、TPOT、Token/s、队列、错误、缓存命中
工作负载：训练 step、loss、checkpoint、rank、重试
设备与节点：GPU、显存、NVLink、RDMA、CPU、磁盘、网络
控制面：队列准入、调度、扩容、Operator、Kubernetes 事件
```

只有一层数据时，团队往往只能知道“慢了”，无法回答慢在数据、网络、GPU、调度还是模型本身。

## 2. 先统一关联键

指标、日志和 Trace 至少应携带以下低基数标识：

- `cluster`、`namespace`、`workload`；
- `team`、`environment`；
- `job_id` 或 `service`；
- `model_name`、`model_revision`；
- `gpu_model`、`resource_flavor`；
- `release` 或镜像摘要。

请求 ID、Prompt、用户 ID 等高基数或敏感字段不要直接成为 Prometheus Label。它们更适合进入受控日志、Trace 或专用分析系统。

## 3. GPU 指标怎么看

NVIDIA DCGM Exporter 通过 `/metrics` 暴露 GPU 指标，可作为 DaemonSet 或由 GPU Operator 管理，并能借助 kubelet PodResources 把设备指标关联到 Pod。参考：[DCGM Exporter](https://docs.nvidia.com/datacenter/dcgm/latest/gpu-telemetry/dcgm-exporter.html)

| 类别 | 关注指标 | 解释 |
| --- | --- | --- |
| 核心利用 | GPU utilization、SM activity | GPU 是否在执行计算 |
| 显存 | framebuffer used/free | 模型、Batch 和 KV Cache 占用 |
| 内存带宽 | DRAM active | 是否受显存带宽限制 |
| Tensor Core | Tensor activity | 混合精度矩阵计算是否充分 |
| 互联 | NVLink/NvSwitch throughput、error | 多卡通信负载和异常 |
| PCIe | TX/RX throughput、replay | 主机与设备传输瓶颈 |
| 健康 | XID、ECC、health status | 驱动或硬件故障信号 |
| 环境 | 功耗、温度、时钟、降频原因 | 是否被功耗或散热限制 |

“GPU utilization 100%”不等于效率最佳。它可能在执行低效 Kernel，也可能因同步等待呈现误导性的平均值，需要结合吞吐和业务目标判断。

## 4. 训练任务的黄金指标

训练至少记录：

- global step、epoch、samples/s 或 tokens/s；
- loss、学习率、梯度范数；
- step time 的平均值和 P95；
- DataLoader wait、数据解码时间；
- collective communication time；
- Checkpoint 保存/恢复时间与大小；
- 有效训练时间、排队时间、失败恢复时间；
- 各 Rank 的 straggler 差异。

一个实用分解是：

```text
step_time
  = data_wait
  + forward
  + backward
  + communication
  + optimizer
  + checkpoint_amortized
```

如果只记录总 step time，网络抖动、数据饥饿和计算回退会混在一起。

## 5. 分布式训练如何找慢 Rank

应同时观察：

- 每个 Rank 的 step duration；
- NCCL collective 的耗时分布；
- GPU/NIC/NUMA 亲和性；
- 网卡吞吐、丢包、ECN/PFC 和重传；
- CPU 调度、Page Fault 与存储读取；
- 是否某个节点降频、发生 XID 或链路降级。

最慢 Rank 决定同步训练的整体速度。不要只看集群平均值，平均值会隐藏单节点异常。

## 6. LLM 推理的核心指标

| 指标 | 含义 | 使用方式 |
| --- | --- | --- |
| TTFT | 从请求到首 Token | 反映排队、Prefill 和冷启动 |
| TPOT | 后续每 Token 时间 | 反映 Decode 性能 |
| ITL | Token 间延迟 | 评估流式输出稳定性 |
| E2E latency | 完整请求延迟 | 用户体验与输出长度相关 |
| input/output tokens/s | 吞吐 | 需要区分输入和输出 |
| queue time/depth | 排队时间和深度 | 扩缩容与过载控制依据 |
| KV Cache utilization | 缓存占用 | 判断并发上限和驱逐风险 |
| prefix cache hit | 前缀命中 | 评估路由和缓存收益 |
| request success/cancel | 成功、错误、取消 | 长连接和客户端行为 |

所有延迟都应按模型、输入长度、输出长度、优先级和流式/非流式请求分桶，否则 P95 缺乏可比性。

## 7. 从基础设施 SLI 到业务 SLO

建议至少定义三类 SLO：

### 平台 SLO

- Job 提交 API 可用性；
- 调度控制面错误率；
- 有配额且有容量时的准入延迟；
- 推理平台发布成功率。

### 工作负载 SLO

- 训练任务成功率与恢复时间；
- Checkpoint 成功率；
- 在线推理可用性、TTFT 和错误率；
- 模型版本发布和回滚时间。

### 模型 SLO

- 离线评估门槛；
- 在线质量、拒答率或安全策略命中；
- 数据漂移和模型漂移；
- 用户反馈与业务转化。

基础设施 SLO 达标而模型输出错误，仍然是一次失败发布。

## 8. 日志设计

训练日志应结构化包含：时间、Job、Rank、step、组件和错误类别。推理日志应区分网关、调度器、模型服务器和下游工具调用。

禁止默认记录：

- 完整 Prompt 与响应；
- 访问 Token、Cookie、API Key；
- 数据集中的个人信息；
- 未脱敏的模型输入附件；
- Secret、环境变量或完整 Pod Spec。

为排障临时提高日志级别时，应设置自动过期，并限制访问权限。

## 9. Trace 应覆盖哪些边界

一次推理请求可以跨越：

```text
API Gateway
  → 身份/限流
  → 模型路由
  → 排队
  → Prefill Worker
  → KV Cache 传输
  → Decode Worker
  → 工具或检索服务
  → 流式响应
```

Trace 的价值是解释端到端延迟，不是替代指标。OpenTelemetry 提供 Trace、Metric、Log 和 Resource 的语义约定，可用统一资源属性关联信号。参考：[OpenTelemetry Semantic Conventions](https://opentelemetry.io/docs/concepts/semantic-conventions/)

## 10. 告警应该可行动

较好的告警示例：

- GPU 节点出现新的 XID 且对应 Pod 错误率上升；
- TTFT P99 超过 SLO，同时队列深度持续增加；
- 有配额队列等待超过阈值，但集群扩容没有动作；
- Checkpoint 连续失败，剩余可恢复窗口低于 RPO；
- 单个 Rank 比中位数慢 30% 以上；
- GPU 功耗低、显存高、吞吐下降，疑似数据或通信瓶颈。

“CPU 高”或“Pod 重启”本身通常不够行动化，需要包含影响对象、可能原因和 Runbook 链接。

## 11. 控制指标基数和成本

- 不把 request ID、用户 ID、文件名作为 Metric Label；
- 模型版本只保留当前和少量历史版本；
- 对高频 GPU Profiling 指标控制采样间隔；
- 长期趋势降采样，原始高分辨率数据短期保留；
- Trace 使用按错误、延迟或租户的尾部采样；
- 为日志、指标和 Trace 本身设置容量预算。

可观测系统把生产集群拖慢，是平台常见的二次故障。

## 12. 推荐 Dashboard

1. **平台总览**：GPU 容量、队列、成本、SLO、告警；
2. **节点详情**：GPU、NVLink、NIC、CPU、存储、XID；
3. **训练任务**：step、loss、吞吐、Rank、通信、Checkpoint；
4. **推理服务**：TTFT、TPOT、队列、KV Cache、错误、版本；
5. **租户视图**：配额、GPU-hours、成功率、等待时间和成本；
6. **发布视图**：新旧版本的质量、性能和错误对比。

## 13. 上线清单

- [ ] 指标能从集群关联到团队、Job、模型和发布版本；
- [ ] GPU 指标来自 DCGM，并验证 Pod 映射正确；
- [ ] 训练能看到数据、计算、通信和 Checkpoint 分解；
- [ ] 推理同时记录 TTFT、TPOT、队列和 Token 吞吐；
- [ ] SLO 同时覆盖平台、工作负载和模型质量；
- [ ] Prompt、Secret 和个人信息默认不进入日志；
- [ ] 告警包含影响、归属和 Runbook；
- [ ] 指标基数、日志量和 Trace 采样有预算；
- [ ] 发布前后可以在同一 Dashboard 对比。

## 延伸阅读

- [NVIDIA DCGM Exporter](https://docs.nvidia.com/datacenter/dcgm/latest/gpu-telemetry/dcgm-exporter.html)
- [DCGM Exporter Metrics](https://docs.nvidia.com/datacenter/dcgm/latest/reference/dcgm-exporter-metrics.html)
- [OpenTelemetry Semantic Conventions](https://opentelemetry.io/docs/concepts/semantic-conventions/)
- [Kueue Monitoring](https://kueue.sigs.k8s.io/docs/tasks/manage/monitor_pending_workloads/)
