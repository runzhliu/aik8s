---
title: AI Kubernetes 集群架构设计
description: 从故障域、节点池、控制面、网络和存储规划训练与推理集群
status: stable
last_reviewed: 2026-08-02
---

# AI Kubernetes 集群架构设计

AI 集群设计不是先安装一串 Operator，而是先明确工作负载、故障域、性能路径和团队边界。相同数量的 GPU，在错误的节点池、网络或容量模型下，可能得到完全不同的吞吐、可用性和成本。

## 一、从工作负载开始

先收集四类画像：

| 画像 | 需要回答的问题 |
| --- | --- |
| 训练 | 单机还是多机、GPU 数、最长运行时间、Checkpoint、Spot 容忍度 |
| 在线推理 | 模型大小、上下文长度、TTFT/TPOT、流量峰值、可用性 |
| 批推理和数据 | 数据量、并发、完成期限、CPU/GPU 比例、读写模式 |
| 交互开发 | Notebook 数量、信任等级、空闲时间、外网和数据权限 |

不要用平均值设计容量。训练关注同时申请的整组 GPU，在线推理关注峰值和故障冗余，Notebook 则更容易产生长时间低利用率占用。

## 二、推荐的逻辑分层

```text
入口层
  Gateway / SSO / API / GitOps
        │
平台控制层
  Kueue / Trainer / KServe / Policy / Observability
        │
通用计算池        GPU 训练池        GPU 推理池        高隔离池
  CPU Job          RDMA + 大块 GPU    稳定型号 + 缓存    Kata/独立节点
        │               │                │                │
集群网络、存储、Registry、对象存储、身份与密钥服务
```

控制组件不一定需要运行在昂贵 GPU 节点。为系统组件保留通用节点池，可以减少 GPU 节点维护和弹性伸缩对控制面的影响。

## 三、一个集群还是多个集群

### 优先一个集群的条件

- 团队数量有限，身份和配额模型相近；
- 训练与推理能通过节点池和队列隔离；
- 使用同一 Kubernetes、驱动和 Operator 版本；
- 单个控制面和故障域满足业务目标；
- 数据地域和合规要求一致。

### 应考虑多个集群的条件

- 生产推理和实验训练需要独立升级窗口；
- 不同 GPU/ASIC 需要互不兼容的驱动或 OS；
- 跨地域、数据主权或网络边界明确；
- 单集群规模已经影响 API Server、调度或 Blast Radius；
- 不可信执行环境需要更强隔离；
- 边缘站点必须弱网自治。

多集群不会自动解决治理问题。每增加一个集群，都要复制身份、策略、Registry、Secret、观测、版本管理和灾备能力。

## 四、节点池如何划分

节点池应该表达硬件和运维边界，而不是组织架构的每个小团队。

建议至少区分：

| 节点池 | 典型能力 | 关键策略 |
| --- | --- | --- |
| system | CPU、稳定、按需 | 承载系统控制器，避免 Spot |
| general | CPU/内存均衡 | 数据处理、网关、普通服务 |
| gpu-training | 高速互联、整卡、批任务 | Kueue、拓扑、Checkpoint |
| gpu-inference | 稳定型号、本地模型缓存 | PDB、Canary、扩缩容保护 |
| gpu-shared | MIG/Time-Slicing | 仅开发或明确隔离承诺 |
| sandbox | Kata/gVisor/机密计算 | 限制网络、设备和身份 |

节点池常用维度：加速器型号、显存、互联类型、CPU 架构、网络、存储、本地缓存、购买方式、可用区和隔离级别。

## 五、标签、Taint 与 ResourceFlavor

稳定标签表示平台承诺，自动发现标签表示硬件事实，两者不应混为一谈。

```yaml
metadata:
  labels:
    platform.example.com/accelerator-class: h100-80g
    platform.example.com/network-class: roce-400g
    platform.example.com/lifecycle: on-demand
    topology.kubernetes.io/zone: zone-a
```

GPU 节点建议设置 Taint，只有明确请求 GPU 的工作负载才容忍：

```yaml
spec:
  taints:
    - key: accelerator
      value: nvidia-h100
      effect: NoSchedule
```

Kueue `ResourceFlavor` 可以把节点标签、Taint 容忍和配额组合为用户可理解的资源类型，例如 `h100-rdma`、`a100-spot`。

## 六、控制面容量

AI 集群容易制造大量短生命周期 Pod、Event、Job 和 CR。控制面要关注：

- API 请求速率和对象数量；
- etcd 数据库大小、碎片和备份；
- scheduler 的 Pending Pod 数和调度延迟；
- Webhook 延迟、失败策略与可用性；
- Controller workqueue 深度和 Reconcile 错误；
- 日志和 Event 保留时间；
- 大量 Job 完成后的资源清理。

不要让一个不可用的非关键 Webhook 阻塞整个集群创建 Pod。对每个 Admission Webhook 明确 `timeoutSeconds`、`failurePolicy` 和高可用部署。

## 七、网络平面

至少区分以下流量：

| 流量 | 特征 | 设计重点 |
| --- | --- | --- |
| Kubernetes 控制流量 | 小包、要求稳定 | API Server、DNS、CNI 可靠性 |
| 训练 Collective | 高带宽、低延迟、同步 | RDMA、无损网络、拓扑 |
| 数据和模型 | 大吞吐、突发 | 对象存储、缓存、出口容量 |
| 推理入口 | 长连接、流式、尾延迟 | Gateway、连接超时、负载均衡 |
| 观测 | 高基数、持续写入 | 独立预算、采样与保留 |

RDMA 网络不应成为普通 Service 流量的唯一通道。多网络方案要验证 DNS、NetworkPolicy、MTU、Host Network 和故障切换行为。

## 八、存储平面

推荐按数据类型选择而不是统一使用一个共享文件系统：

- 对象存储：数据集、模型归档、Checkpoint 和长期制品；
- 共享/并行文件系统：需要 POSIX、并发元数据和低延迟读取的训练；
- 块存储：数据库、Notebook 工作区；
- 本地 NVMe：模型缓存、数据集缓存、临时 Shuffle；
- Registry：容器镜像和 OCI 模型制品。

本地缓存是可再生数据，不应成为唯一副本。跨可用区读取的成本和吞吐也必须进入调度与容量模型。

## 九、容量与冗余

可用 GPU 容量不是物理总数：

```text
可分配容量 = 物理容量
            - 故障隔离
            - 节点维护
            - 系统预留
            - 拓扑碎片
            - 在线服务冗余
```

训练集群常见的是“总量够但整组不够”。例如 32 张空闲 GPU 分散在多个网络 Block，未必能满足一个要求同一高速域的 32 卡任务。

在线推理至少要为单节点、单可用区或一次滚动升级预留冗余，具体取决于 SLO。不要把训练可借用容量算作推理故障冗余。

## 十、身份与租户边界

建议把身份路径画清楚：

```text
人员 OIDC 身份
  → 平台 API / Git 变更
  → Kubernetes ServiceAccount
  → 云 Workload Identity
  → 对象存储、Registry、KMS、数据库
```

训练、推理、流水线和 Notebook 使用不同 ServiceAccount。云权限通过短期身份映射，不在镜像和 Git 中保存长期 Access Key。

## 十一、环境与发布策略

至少准备：

- 一个不含真实生产数据的集成环境；
- 每种生产 GPU 的 Canary 节点或小节点池；
- 可重复的节点镜像、驱动和 Operator 安装方式；
- 代表性训练、推理、RDMA、存储和故障测试；
- 一次升级对应的版本矩阵和回滚门槛。

开发、预生产、生产不一定各自复制完整昂贵 GPU 集群。可以共享少量硬件，但必须保留独立配置、队列和发布门禁。

## 十二、三种起始架构

### 小型：1—8 张 GPU

- 一个集群，system 与 GPU 两类节点；
- Device Plugin、基础监控、对象存储；
- Deployment/Job 或 KServe/Kueue 的最小组合；
- 不提前部署复杂多集群和分离式推理。

### 中型：8—128 张 GPU

- 训练、推理、共享开发节点池；
- Kueue、拓扑标签、自动扩缩容；
- 模型缓存、统一网关、完整可观测；
- Canary 节点、版本矩阵和成本归属。

### 大型：数百张以上 GPU

- 按网络 Block、地域和故障域规划；
- Workload 级拓扑、MultiKueue 或专用批调度；
- 分布式模型缓存和推理请求调度；
- 多集群放置、容量预留、自动故障隔离；
- 控制面和遥测规模测试。

## 十三、架构评审清单

- [ ] 有真实训练、推理、批处理和 Notebook 负载画像。
- [ ] 节点池表达硬件、网络、购买方式和隔离边界。
- [ ] system 控制器不依赖可随时缩到零的 GPU 节点。
- [ ] 控制、训练、存储、推理和观测流量边界清晰。
- [ ] 数据、模型、Checkpoint 和缓存分别选择存储层。
- [ ] 配额模型考虑拓扑碎片和推理冗余。
- [ ] 身份从人员到云资源全链路可审计。
- [ ] 单节点、单网络域和单可用区故障有预期行为。
- [ ] 所有关键组件有 Canary、升级和回滚方案。
- [ ] 多集群由明确的故障域或合规需求驱动。

## 延伸阅读

- [Kubernetes Cluster Architecture](https://kubernetes.io/docs/concepts/architecture/)
- [Kubernetes Large Clusters](https://kubernetes.io/docs/setup/best-practices/cluster-large/)
- [Node Autoscaling](https://kubernetes.io/docs/concepts/cluster-administration/node-autoscaling/)
- [Kubernetes Multi-tenancy](https://kubernetes.io/docs/concepts/security/multi-tenancy/)
- [Kueue ResourceFlavor](https://kueue.sigs.k8s.io/docs/concepts/resource_flavor/)
