---
title: 平台运维、升级与多集群
description: 版本矩阵、渐进升级、CRD、备份、灾备和事故响应
status: stable
last_reviewed: 2026-08-02
---

# 平台运维、升级与多集群

AI 平台的版本矩阵比普通 Kubernetes 更复杂：内核、驱动、CUDA、Container Toolkit、Device Plugin、GPU Operator、RDMA、训练框架和推理引擎彼此约束。升级成功的标准不是 Pod 全绿，而是代表性训练和推理仍然满足性能与可靠性基线。

## 1. 先定义责任边界

| 领域 | 平台团队 | 模型/业务团队 |
| --- | --- | --- |
| Kubernetes、CNI、CSI | 负责 | 了解维护窗口 |
| GPU/Network Operator | 负责 | 提供兼容性需求 |
| 队列、配额、基础运行时模板 | 负责 | 选择并遵守策略 |
| 训练代码和模型 | 提供标准 | 负责 |
| 推理引擎公共版本 | 维护支持集 | 验证模型兼容 |
| SLO 与 Runbook | 共同 | 共同 |

没有明确归属时，驱动问题会被认为是模型问题，模型回归又会被当成集群问题。

## 2. 维护版本清单

至少记录：

- OS、内核和固件；
- Kubernetes、containerd/CRI-O；
- CNI、CSI；
- GPU 驱动、CUDA 兼容级别；
- NVIDIA Container Toolkit、Device Plugin；
- GPU Operator、DCGM；
- RDMA/NIC 驱动和 Network Operator；
- Kueue、JobSet、LWS、Trainer、KubeRay；
- KServe、vLLM/SGLang/Triton；
- 模型格式和关键 Python 框架。

清单要同时包含“当前版本”“目标版本”“支持来源”“验证状态”和“回滚方式”。

## 3. 不要跳过兼容矩阵

Kubernetes 只维护最近若干个次版本，并对 apiserver、kubelet、kubectl 等组件定义版本偏差和升级顺序。当前规则以官方 Version Skew Policy 为准。参考：[Kubernetes Version Skew Policy](https://kubernetes.io/releases/version-skew-policy/)

GPU Operator 也有独立的 Kubernetes、OS、容器运行时、驱动和组件矩阵，并限制跨大版本升级路径。参考：[GPU Operator Platform Support](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/platform-support.html)

“某个版本能安装”不等于处于供应商支持组合。

## 4. 推荐升级顺序

一次平台升级可以按以下阶段设计：

1. 备份、兼容性和 API 弃用扫描；
2. 在实验集群验证控制面和基础组件；
3. 升级 Kubernetes 控制面；
4. 升级节点组件、CNI 和 CSI；
5. Canary GPU 节点升级 OS/内核/驱动；
6. GPU/Network Operator 与 CRD；
7. 队列、训练、服务控制器；
8. 推理引擎和公共运行时；
9. 代表性训练、推理与故障测试；
10. 扩大节点池并观察；
11. 清理旧 API 和临时兼容项。

实际顺序必须遵循发行版和厂商文档，不能把这张列表当成通用命令序列。

## 5. Canary GPU 节点池

Canary 节点应覆盖生产硬件型号，并运行：

- 驱动和 GPU Operator 验证；
- CUDA 基础测试；
- DCGM 诊断；
- GPU 间 P2P/NVLink 测试；
- NCCL Tests；
- RDMA/存储基准；
- 一个代表性训练 Job；
- 一个代表性推理服务；
- DRA/MIG/共享策略（如果使用）。

Canary 通过后再按故障域滚动，避免同一模型所有副本同时进入新驱动版本。

## 6. 节点维护流程

```text
确认容量与 PDB
  → cordon
  → 停止新任务准入
  → 等待/Checkpoint/迁移现有任务
  → drain
  → 升级或维修
  → 节点自检与基准
  → uncordon
  → 观察代表性工作负载
```

`kubectl drain` 会尊重 PDB，但单副本服务、错误 PDB 或本地数据都可能阻塞。参考：[Safely Drain a Node](https://kubernetes.io/docs/tasks/administer-cluster/safely-drain-node/)

长训练不应在没有 Checkpoint 协议时被强制 drain。

## 7. CRD 和 Webhook 是升级高风险点

检查：

- 新版本是否先更新 CRD；
- Helm 是否自动升级 CRD；
- 存储版本和 Conversion Webhook；
- Webhook 在新 API 字段下是否兼容；
- Webhook 不可用时的 `failurePolicy`；
- Controller 回滚后能否读取新对象；
- 删除旧 CRD 是否会级联删除业务资源。

GPU Operator 官方升级流程明确提示 Helm 对 CRD 的处理需要额外注意。参考：[Upgrading GPU Operator](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/upgrade.html)

## 8. GitOps 管什么

适合 GitOps：

- Operator 与 CRD 版本；
- Kueue 配额、Flavor 和策略；
- Namespace、RBAC、NetworkPolicy；
- 标准训练/推理模板；
- Dashboard、告警和 SLO；
- 模型服务声明和流量策略。

不应明文放入 Git：

- Secret 和私钥；
- 大模型与数据集；
- 节点一次性 Token；
- 运行时生成的状态；
- 未脱敏的事故证据。

集群内手工热修必须尽快回写 Git 或撤销，否则状态会漂移。

## 9. 多集群何时必要

合理原因：

- 不同地区/数据主权；
- 训练与生产推理隔离；
- 不同硬件或驱动生命周期；
- 控制面故障域；
- 边缘站点；
- 超大规模下的 Blast Radius 控制。

不合理原因：单集群治理问题没解决，就用更多集群隐藏配额、权限和升级混乱。

多集群会增加 Registry、身份、策略、可观测、成本和版本分布复杂度。

## 10. 工作负载放置

多集群调度要区分：

- 组织策略：数据地域、租户、环境；
- 资源能力：GPU、RDMA、存储和模型缓存；
- 当前容量和排队时间；
- 成本与 Spot 风险；
- 模型和数据复制状态；
- 失败后的重新放置成本。

Kueue MultiKueue 可以把工作负载分发到 Worker Cluster，但模型制品、Secret、RuntimeClass 和监控仍需平台准备。

## 11. 备份与灾备

定期验证：

- etcd/控制面备份可恢复；
- Git 仓库与 Chart 可从独立位置取得；
- Registry 和对象存储有跨故障域副本；
- 模型注册表元数据和模型文件一致；
- DNS、证书和身份系统有恢复方案；
- 新集群能重新创建队列、策略和 RuntimeClass；
- 恢复后的训练能读取旧 Checkpoint；
- 推理域名能切换并保持安全配置。

灾备文档应给出实际恢复时间，而不是只描述架构。

## 12. 升级验收

| 层级 | 验收 |
| --- | --- |
| Kubernetes | API、调度、DNS、CNI、CSI、日志 |
| GPU | 发现、分配、MIG/DRA、DCGM、XID |
| 网络 | Pod 网络、RDMA、NCCL、跨节点吞吐 |
| 存储 | PVC、对象存储、模型下载、Checkpoint |
| 训练 | 启动、吞吐、收敛片段、恢复 |
| 推理 | 模型加载、TTFT/TPOT、扩缩容、灰度 |
| 治理 | Kueue、RBAC、策略、审计、成本标签 |

与升级前基线比较，性能偏差超过阈值必须解释。

## 13. 变更记录

每次变更至少保留：

- 目标和风险；
- 版本 Diff；
- 兼容性来源；
- Canary 范围；
- 验证结果；
- 观察窗口；
- 回滚触发条件；
- 实际故障和后续行动。

## 14. 上线清单

- [ ] 有完整版本清单和供应商支持矩阵；
- [ ] Kubernetes、GPU Operator 和 AI 组件升级顺序明确；
- [ ] 每类 GPU 都有 Canary 节点；
- [ ] 节点维护与长训练 Checkpoint 协调；
- [ ] CRD、Webhook 和 API 弃用在升级前验证；
- [ ] GitOps 是生产配置的权威来源；
- [ ] 多集群有明确故障域或业务理由；
- [ ] Registry、模型、配置和身份恢复不依赖单集群；
- [ ] 验收同时覆盖功能、性能和恢复；
- [ ] 每次升级有可执行回滚条件和记录。

## 延伸阅读

- [Kubernetes Version Skew Policy](https://kubernetes.io/releases/version-skew-policy/)
- [Safely Drain a Node](https://kubernetes.io/docs/tasks/administer-cluster/safely-drain-node/)
- [GPU Operator Platform Support](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/platform-support.html)
- [Upgrading GPU Operator](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/upgrade.html)
- [Kueue MultiKueue](https://kueue.sigs.k8s.io/docs/concepts/multikueue/)
