---
title: AI on Kubernetes 落地路线图
description: 从现状评估到 30、60、90 天建设计划和长期能力演进
status: stable
last_reviewed: 2026-08-02
---

# AI on K8s 落地路线图

技术栈的最佳起点不是“安装完整 Kubeflow”，而是先回答工作负载、规模、租户和运维能力。下面给出一套可以逐步扩展的实施路线。

## 1. 先回答十个问题

1. 主要是训练、批推理还是在线推理？
2. 传统 ML、CV、多模态还是 LLM？
3. 单机可运行，还是必须多机多卡？
4. 峰值和常态分别需要多少 GPU？
5. GPU 型号是否异构，是否有 MIG/共享需求？
6. 有几个团队共享，是否需要优先级、借用和抢占？
7. 数据和模型目前放在哪里，吞吐和冷启动是多少？
8. 需要什么 SLO、合规、审计和数据隔离？
9. 团队更熟悉 Kubernetes、Ray 还是现有数据平台？
10. 哪些能力可以购买托管服务，哪些必须自托管？

如果这些问题没有答案，工具比较越详细，选型越容易偏离真实需求。

## 2. 什么时候不应该上 Kubernetes

以下情况可以先使用单机 Docker、托管 Notebook、云厂商训练服务或简单 VM：

- 只有一两张固定 GPU，没有多租户和高可用要求；
- 工作负载偶发，手工启动已经足够；
- 团队没有 Kubernetes 运维能力，也没有平台团队；
- 主要调用外部模型 API，自托管推理不是核心能力；
- 数据无法高效进入集群，迁移成本远高于调度收益；
- 模型仍在探索期，接口与依赖每天变化。

Kubernetes 的收益来自标准化、大规模共享和自动化。如果没有这些需求，它只会增加控制面和排障成本。

## 3. 按规模选择起始栈

### 小型：1—8 张 GPU、一个团队

```text
托管 Kubernetes 或 K3s
+ GPU Operator
+ Job / Deployment
+ MLflow
+ 对象存储
+ Prometheus / Grafana / DCGM
```

- 训练先用原生 Job 或框架启动器；
- 推理先用 Deployment + vLLM/Triton；
- 使用 Helm/Kustomize 和 CI 构建镜像；
- 暂不引入专用队列和完整 Kubeflow。

### 中型：8—128 张 GPU、多个团队

```text
Kubernetes + GPU Operator
+ Kueue
+ Kubeflow Trainer 或 KubeRay
+ Argo Workflows / KFP
+ MLflow + Model Registry
+ KServe
+ Argo CD
+ 统一监控、日志和策略
```

- 建立 ResourceFlavor、团队配额和优先级；
- 训练任务必须成组调度并支持 Checkpoint；
- 模型通过 Registry + GitOps 发布；
- 建立开发、训练、在线推理节点池边界。

### 大型：数百张以上 GPU、多集群

在中型栈基础上增加：

- Topology-Aware Scheduling、JobSet/LWS；
- MultiKueue 或其他多集群调度；
- DRA 与设备级健康/分区管理；
- Inference Gateway、llm-d 或等价智能路由；
- RDMA、Local NVMe Cache、分布式对象/文件存储；
- 容量预测、Chargeback、自动故障隔离和性能基准平台。

规模变大后，最重要的是减少“特殊例外”，而不是继续增加工具。

## 4. 30/60/90 天实施计划

### 第 1—30 天：建立可测量基线

- 盘点模型、数据、GPU、网络和当前发布流程；
- 固定 Kubernetes、驱动、GPU Operator 与框架版本矩阵；
- 建立一个非生产 GPU 节点池；
- 跑通单卡和多卡基准，保存吞吐、延迟、显存和成本；
- 部署 Prometheus、Grafana、DCGM Exporter 和集中日志；
- 使用对象存储保存模型与 Artifact；
- 选择一个训练或推理工作负载作为 Pilot。

**验收结果**：任意一次 Pilot 都能找到镜像、配置、日志、GPU 指标和输出制品。

### 第 31—60 天：建立可重复交付

- 用 Argo Workflows/KFP 封装数据、训练和评估；
- 引入 MLflow，关联代码、数据、Run、模型与评估；
- 引入 Kueue，为团队配置 Queue、Quota 和 ResourceFlavor；
- 选择 Kubeflow Trainer 或 KubeRay，形成一套 Runtime 模板；
- 模型服务使用 KServe 或标准化 Helm Chart；
- 用 Argo CD/Flux 管理生产配置；
- 验证 Checkpoint、抢占、Pod/节点故障和回滚。

**验收结果**：同一 Git Commit 和数据版本可以重复产生同类结果，模型发布不再依赖个人电脑。

### 第 61—90 天：建立多租户与 SLO

- 接入企业 OIDC、最小权限 RBAC 和默认拒绝 NetworkPolicy；
- 建立镜像签名、策略校验、Secret 管理和审计；
- 为训练定义排队时间、成功率和恢复 SLO；
- 为推理定义可用性、TTFT、TPOT、P99 和拒绝率 SLO；
- 运行 Canary、容量压测和故障演练；
- 建立 GPU 利用率、队列等待、模型成本与团队归属报表；
- 将 Pilot 的黄金路径推广给第二个团队，验证可复用性。

**验收结果**：平台能安全服务多个团队，并能解释一次失败、一次发布和一笔 GPU 成本。

## 5. 建议的最小平台接口

平台至少提供四类自助入口：

| 入口 | 用户提供 | 平台负责 |
| --- | --- | --- |
| 训练任务 | 代码/镜像、数据、资源、超参数 | 队列、运行时、日志、指标、Checkpoint |
| 批推理 | 模型、输入、输出位置 | 分片、重试、资源和结果清单 |
| 在线服务 | 模型版本、Runtime、SLO | 网络、弹性、Canary、证书和监控 |
| 实验与模型 | Run、指标、Artifact、评估 | 元数据、权限、注册、保留和审计 |

接口可以是 CRD、Python SDK、CLI 或门户，但最终应生成可审计的 Kubernetes 与 Git 声明。

## 6. 容量规划方法

### 训练

```text
单次训练成本 ≈ GPU 数 × 训练小时 × GPU 小时单价
有效训练效率 ≈ 实际训练计算时间 / GPU 分配总时间
```

要同时计算排队、数据准备、Checkpoint、失败重跑和空闲占卡。单纯提高 SM 利用率不一定缩短 Time-to-Model。

### 推理

```text
单位成本 = 总 GPU 成本 / 成功输出 Token
安全容量 = 满足目标 P99 时的最大稳定 Token Throughput
```

容量测试至少覆盖：常见请求、长上下文、突发并发、混合模型、缓存冷/热和单实例故障。

### 预留

建议将 GPU 容量分为：

- 在线服务基线容量；
- 批任务和训练可抢占容量；
- 故障与升级预留；
- 临时峰值或 Spot 容量。

不要让所有 GPU 都达到 100% allocation 后才考虑高可用；在线推理至少需要能够承受一个故障域退出。

## 7. 关键 SLO

| 场景 | 推荐 SLI |
| --- | --- |
| 训练平台 | Queue P50/P95、启动成功率、Job 成功率、Checkpoint 恢复率 |
| GPU 基础设施 | 可分配率、XID、节点修复时间、Driver/Plugin 可用性 |
| 在线推理 | Availability、TTFT、TPOT、P99、Token Throughput、拒绝率 |
| MLOps | Pipeline 成功率、可复现率、发布 Lead Time、回滚时间 |
| 治理 | 未归属成本、策略违规、过期 Secret、不可追溯模型数 |

每个 SLO 必须有 Owner、告警、Runbook 和复盘机制；只有 Dashboard 没有响应流程不算可运维。

## 8. 版本与升级策略

- 平台组件使用固定版本，不跟随 `latest`。
- 维护 Kubernetes → GPU Operator → Driver → CUDA → Framework → Runtime 兼容矩阵。
- 先升级非生产节点池，再运行训练和推理基准。
- 节点采用滚动替换，提前验证 drain、Checkpoint 和 PodDisruptionBudget。
- CRD 升级前备份对象并阅读转换/废弃说明。
- KServe LLMInferenceService、DRA 等快速演进 API 要单独建立迁移测试。
- 模型服务升级同时验证输出质量，不能只检查 Pod Ready。

## 9. 常见失败路线

1. **先装完整平台，再寻找使用者**：最终形成无人维护的组件集合。
2. **所有工作负载共享一个 GPU 节点池**：开发 Notebook、训练和在线服务相互干扰。
3. **只按申请 GPU 数计费**：无法发现长期空占和低效任务。
4. **把模型放进超大镜像**：构建、分发和回滚极慢。
5. **没有不可变数据版本**：实验指标无法复现。
6. **没有真实故障演练**：Checkpoint、抢占和回滚只存在于文档。
7. **追求满负载而牺牲 SLO**：推理尾延迟和训练失败率恶化。
8. **每个团队自选全部工具**：平台无法统一升级、安全和观测。

## 10. 最终验收清单

- [ ] 新用户可在一天内提交第一个受控训练或推理任务。
- [ ] 平台能解释任务为什么 Pending、失败或被抢占。
- [ ] 任意模型可追溯到代码、数据、镜像、配置和评估。
- [ ] GPU 故障和节点维护不会导致不可恢复的数据或模型丢失。
- [ ] 生产发布支持 Shadow/Canary、自动指标判断和快速回滚。
- [ ] 每个租户的身份、网络、Secret、资源和成本边界清楚。
- [ ] 关键 SLO 有告警和经过演练的 Runbook。
- [ ] 平台升级有兼容矩阵、基准、灰度和回退方案。
- [ ] 组件数量与当前规模匹配，没有为未来假设提前堆叠系统。
- [ ] 第二个团队成功复用了同一条黄金路径。
