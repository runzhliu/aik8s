# 性能基准、压测与回归

AI 平台的性能测试不能只跑一次 `nvidia-smi` 或看某个公开榜单。有效基准需要固定数据、模型、软件、拓扑和质量目标，并从硬件微基准一直覆盖到真实业务 SLO。

## 一、五层基准体系

```text
业务结果：成本、质量、成功请求、训练目标
端到端：完整训练、完整推理请求
框架组件：vLLM、PyTorch、数据加载、Checkpoint
集群通信：NCCL、RDMA、存储、Pod 网络
硬件基线：GPU、NVLink、PCIe、CPU、磁盘、NIC
```

底层基准帮助定位，端到端基准决定是否可用。任何单层都不能替代其他层。

## 二、测试前冻结变量

每次结果必须记录：

- GPU 型号、数量、功耗模式和时钟；
- CPU、NUMA、内存；
- NIC、交换网络和拓扑；
- OS、内核、驱动、CUDA、NCCL；
- Kubernetes、Runtime、Operator；
- 镜像 Digest 和代码 Commit；
- 模型、精度、量化和并行策略；
- 数据集、输入/输出长度分布；
- Batch、并发、缓存冷热状态；
- 运行次数、预热和统计方法。

缺少这些元数据的“快 20%”无法复现。

## 三、硬件和节点基线

新节点入池前至少检查：

- DCGM 诊断和 GPU 健康；
- GPU 显存带宽和基本算力；
- GPU P2P 矩阵；
- NVLink/NvSwitch 状态；
- PCIe Link Width/Generation；
- CPU 内存带宽和 NUMA；
- 本地 NVMe 顺序与随机 I/O；
- NIC 带宽、延迟和错误；
- 温度、功耗与持续负载降频。

目标不是追求理论峰值，而是发现同型号节点中的异常离群值。

## 四、NCCL 与 RDMA 基准

建议逐层：

1. 单机两 GPU；
2. 单机全部 GPU；
3. 同机架两节点；
4. 同网络域多节点；
5. 跨机架或跨 Block；
6. 与真实训练相同规模。

测试 All-Reduce、All-Gather、Reduce-Scatter 和 All-to-All，并按消息大小绘制带宽/延迟曲线。只报告最大消息吞吐，会掩盖小消息和真实梯度大小的问题。

同时保存 NCCL 拓扑、选用网卡和 GPU/NIC 亲和性。

## 五、存储和数据加载基准

分别测试：

- 单 Pod 顺序读写；
- 多 Pod/多节点并发；
- 大文件和大量小文件；
- 冷缓存与热缓存；
- 对象存储首字节和持续吞吐；
- 模型并发下载；
- Checkpoint 保存和恢复；
- 真实 DataLoader samples/s。

`fio` 能测块和文件系统，但不能替代真实的数据格式、解码和增强流程。

## 六、训练基准

训练基准至少分三类：

### 单步性能

- step time；
- samples/tokens per second；
- GPU、通信和数据等待分解；
- Scaling Efficiency。

```text
扩展效率
  = N 卡实际吞吐 / (单卡吞吐 × N)
```

### Time-to-Quality

使用固定数据、随机种子范围和质量门槛，测达到目标 Loss/Accuracy 的时间。MLPerf Training 也是以达到目标质量来比较系统。参考：[MLPerf Training](https://mlcommons.org/benchmarks/training/)

### 恢复性能

- Checkpoint 保存阻塞时间；
- 恢复下载和重分片；
- Worker 故障后的 RTO；
- Spot 中断造成的重算比例。

## 七、推理压测场景

至少覆盖：

| 场景 | 目的 |
| --- | --- |
| Offline | 测最大吞吐，不强调单请求延迟 |
| Server | 按随机到达率测试吞吐与尾延迟 |
| Interactive | 强调 TTFT、流式输出和并发体验 |
| Cold Start | 测镜像、模型加载和首次请求 |
| Burst | 测突发、排队、限流和扩容 |
| Long Context | 测长输入、KV Cache 和 OOM 边界 |
| Mixed Models | 测路由、缓存和多模型资源竞争 |

MLPerf Inference 区分 Datacenter/Edge 和 Offline、Server、Interactive 等场景，可作为设计参考。参考：[MLPerf Inference](https://docs.mlcommons.org/inference/)

## 八、LLM 压测输入必须真实

固定短 Prompt 会严重高估容量。应从脱敏业务分布构造：

- 输入 Token 分布；
- 输出 Token 分布；
- 流式与非流式比例；
- 不同模型/Adapter；
- 重复前缀和缓存命中；
- 取消请求；
- 工具调用与检索延迟；
- 优先级和租户混合。

报告 P50/P95/P99 TTFT、TPOT、E2E、Token/s、错误率和满足 SLO 的最大吞吐。

## 九、质量与性能必须绑定

量化、投机解码、Batch、并行和缓存都可能改变输出。每次性能优化同时运行：

- 离线准确率/任务质量；
- 关键安全与拒答评估；
- 输出稳定性；
- 数值精度和溢出检查；
- 业务样本回归。

不满足质量门槛的性能结果不进入比较表。

## 十、Kubernetes 引入的变量

- CPU request/limit 和节流；
- Pod QoS 与驱逐；
- Topology Manager/CPU Manager；
- Device Plugin 或 DRA；
- CNI、Service Mesh 和代理；
- PVC/CSI；
- 节点上其他 Pod 干扰；
- Kueue 等待和 Flavor；
- Autoscaler 冷启动；
- 监控采集本身的开销。

裸机结果和 Kubernetes 结果都要保留，它们的差值能帮助定位平台开销。

## 十一、避免错误比较

不能直接比较：

- 不同模型或质量门槛；
- 不同输入/输出长度；
- 热缓存与冷缓存；
- 不同精度/量化；
- 不同功耗上限；
- 单次最好结果与多次中位数；
- 满载吞吐与低负载延迟；
- 厂商优化实现与未优化参考实现。

公开榜单用于形成预期范围，不能替代自己的模型和集群测试。

## 十二、统计与结果展示

- 至少运行多次，报告中位数和离散程度；
- 长时间稳态测试，排除仅靠短时 Boost 的结果；
- 明确预热时间和舍弃区间；
- 报告失败和 OOM，不只保留成功结果；
- 时间序列与汇总值同时保存；
- 标记环境是否共享、是否有干扰；
- 保留原始日志、配置和镜像摘要。

## 十三、把回归测试接入发布

分级执行：

1. PR：小规模功能和短性能 Smoke Test；
2. 每日：代表性单节点训练/推理；
3. 每周：多节点 NCCL、存储和长稳态；
4. 升级前后：完整基线矩阵；
5. 新硬件入池：节点验收与集群级测试。

为每项设置允许回归阈值，并区分噪声、已知变化和真正失败。

## 十四、结果模板

```text
目标：验证新驱动不降低 8×GPU 训练性能
环境：硬件/拓扑/软件/镜像摘要
工作负载：模型、数据、精度、Batch、并行
基线：版本 A 的中位数与方差
候选：版本 B 的中位数与方差
质量：目标指标与是否通过
性能：吞吐、延迟、GPU/网络/存储分解
可靠性：失败、重试、XID、恢复
结论：通过 / 阻塞 / 有条件通过
原始证据：Dashboard、日志、制品链接
```

## 十五、上线清单

- [ ] 建立硬件、通信、存储、框架和端到端五层基准；
- [ ] 每次结果记录完整硬件、拓扑和软件元数据；
- [ ] 训练同时测吞吐、Time-to-Quality 和恢复；
- [ ] 推理覆盖真实长度分布、突发和冷启动；
- [ ] 所有优化都通过质量和安全回归；
- [ ] 裸机与 Kubernetes 结果可对比；
- [ ] 报告中位数、离散程度和失败结果；
- [ ] 关键基准进入升级和发布门禁；
- [ ] 原始配置与证据可追溯。

## 延伸阅读

- [MLPerf Training](https://mlcommons.org/benchmarks/training/)
- [MLPerf Inference](https://docs.mlcommons.org/inference/)
- [NVIDIA DCGM Diagnostics](https://docs.nvidia.com/datacenter/dcgm/latest/user-guide/dcgm-diagnostics.html)
- [NCCL Tests](https://github.com/NVIDIA/nccl-tests)
