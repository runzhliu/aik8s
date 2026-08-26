---
title: 从 W&B Local 到 SwanLab：两年团队实验追踪实践与选型
description: 从一套运行两年的 W&B Local 讲起，结合 SwanLab 真实 SFT 实测，解释实验追踪为什么难以生产化，以及团队应该怎样选型和验收
status: evolving
last_reviewed: 2026-08-26
---

# 从 W&B Local 到 SwanLab：两年团队实验追踪实践与选型

当年刚开始建设大模型平台时，我遇到过一个很现实的矛盾。

一边是生产环境不允许用户把训练 Trace、Metrics、日志和模型相关数据直接发送到公网；另一边是大量开源模型、训练框架和教程默认接入 W&B，算法同学对它的需求和认可度都很高。

既不能简单开放公网，又不能让用户放弃已经熟悉的工具，最后只剩下一条路：在内部环境私有化部署 W&B Local。

我后来用一个单副本 StatefulSet 把它跑了起来，陆续接入 OPT、Baichuan/Megatron、YOLO 和医学影像等训练任务。这个实例经历过 License 更新、数据库外置、对象存储扩容、断网补传和数据迁移，最后稳定运行了两年才下线。

最近重新做大模型 SFT，我又在 Kubernetes 部署并实测了 SwanLab。回头比较两段经历，我发现真正值得讨论的不是谁的曲线更漂亮，而是三个更实际的问题：

1. 实验追踪系统为什么很容易从“小工具”变成生产基础设施？
2. W&B 和 SwanLab 各自适合解决什么问题？
3. 如果今天重新选型，怎样避免再踩一遍旧坑？

先说我的结论：**当前主要做大模型 SFT、看训练曲线和比较 Run，我会继续用 SwanLab；如果需要数据集、Checkpoint、模型血缘、Registry、自动调参和企业权限治理，W&B 的体系仍然更完整。无论选谁，都要把数据库、对象存储、备份恢复、授权和退出方案一起评估。**

## 用户为什么强烈需要 W&B

当时很多开源项目已经把 W&B 当作默认实验追踪工具。用户照着社区文档运行训练脚本后，自然希望内部平台也能看到相同的 Project、Run 和曲线。W&B 产品本身也比较成熟，算法工程师不需要重新学习一套完全不同的使用方式。

他们关心的问题很具体：

- 这次训练的 Loss 和上一次有什么区别？
- Learning Rate、Grad Norm 和训练速度是否正常？
- 哪组超参数效果最好？
- 网络中断后，曲线能不能补回来？
- 几个月后还能不能找到当时的配置和结果？

TensorBoard 可以看一份日志目录里的曲线，但当训练分散在不同机器、目录和用户手里时，项目管理、Run 对比和长期检索会越来越麻烦。

这给我留下的第一个判断是：

> 一个工具只要开始集中保存全团队的训练历史，它就不再只是可视化页面，而是训练平台的数据系统。

## 一张 License、一个 StatefulSet，先把需求顶住

我接触过 W&B 的销售，也认真了解过正式采购。但当时的 License 确实非常贵，不是一般团队可以轻松承担的成本。那时 AI 还没有像现在这样受到重视，公司也很难为一个训练辅助工具投入这么高的预算。

为了先满足用户，我用一个有效的个人或试用 License，部署了一套单副本 StatefulSet 版本的 W&B Local。这个方案现在看当然比较“搓”：没有正式商业支持，也谈不上严格的生产 SLA，但它解决了两个最紧迫的问题：

- 训练数据不需要离开生产环境；
- 用户可以继续使用社区里熟悉的 W&B SDK 和操作方式。

真正麻烦的是用户多起来以后。一个人使用时，实例重启可能没什么；大量用户持续写入 Metrics、Trace 和文件时，容量、迁移、恢复和升级都会变成平台问题。

这也是选型时容易忽略的一点：**License 不只是采购问题，还会影响服务能不能升级、能不能长期保存数据，以及平台有没有明确的退出路径。**

## W&B Local 看似一个容器，实际是一套系统

W&B Local 表面上是一个 Docker 镜像，执行 `wandb server start` 就能启动。我进入容器分析后才发现，它其实是一个典型的富容器，里面不只有 Web 服务，还有 Redis、MinIO、MySQL 相关逻辑、Nginx、后台任务和大量初始化与迁移脚本。

可以把当时的关系简化成下面这样：

```text
训练任务 / W&B SDK
        |
        v
W&B Local 富容器
  ├─ Web / API / 后台任务
  ├─ MySQL：项目、Run、用户和指标元数据
  ├─ MinIO：日志、媒体、模型与其他文件
  └─ Redis：缓存和内部状态
```

因此，只备份数据库并不能保证 Run 可以恢复。MySQL 里可能还有记录，但 MinIO 文件不完整时，前端依然打不开历史数据；反过来，只保存对象文件也无法还原项目、用户和指标之间的关系。

对今天任何实验追踪系统都适用的结论是：

> 元数据数据库、时序指标和对象文件必须作为同一份业务数据设计备份与恢复，不能让三个团队分别“各保各的”。

## 对象存储不是换一个地址就行

我们当时已经有公司级对象存储，我也尝试过替换内置 MinIO。原本以为只要修改 S3 Endpoint，实际却没有这么简单。

旧版 W&B 还依赖一个 Gateway 一类的中间组件，并且涉及 S3 协议和签名兼容。内部对象存储能提供 S3 API，不代表它与应用使用的每一种请求、签名和目录语义都完全兼容。折腾一轮后，我仍然无法把它可靠替换掉，只能放弃。

既然 MinIO 暂时换不了，我就把富容器里需要保存的目录梳理清楚，再通过 RBD、CephFS 等存储提供持久化和在线扩容。大量用户共用一个实例以后，Metrics、Trace 和上传文件增长很快，如果没有容量监控，MySQL 和 MinIO 很容易被打满。

这个坑可以提炼成一条很实用的验收要求：

> 对象存储兼容性必须用真实上传、查询、离线补传、删除和恢复验证，看到“兼容 S3”四个字还不够。

## 数据库最终交给专业系统

数据库部分最后做得更完整一些。经过初始化、迁移权限和表结构等一轮排查，我们把 MySQL 接到了公司级数据库服务，由专业 DBA 同事保障备份、容量和稳定性。MinIO 暂时留在实例侧，MySQL 则从富容器里解耦出去。

这一步的价值不是“用了一个更高级的数据库”，而是把责任边界理顺：

- 应用团队关注 W&B 版本、接口与用户体验；
- 数据库团队负责高可用、备份、恢复和容量；
- 存储团队提供可靠卷与扩容能力；
- 平台团队负责 Kubernetes、监控和变更流程。

自托管平台最怕所有组件都“能跑”，却没有任何团队对恢复结果负责。

## License 更新也不能丢历史数据

早期 Self-Hosted 的个人或试用 License 只有几个月有效期。如果每次到期都重建实例，用户、项目和历史 Run 都会非常被动。

我当时通过分析容器日志、数据库、MinIO 和启动流程之间的关系，梳理出了在拿到新的有效 License 后更新授权、同时保留原有数据的流程。这里不公开 License 文件位置、令牌或具体操作步骤，重点是授权更新不应迫使数据系统从零开始。

这套方案并不漂亮，却真的在大量用户使用、数据持续增长、没有正式商业支持的情况下稳定运行了两年。现在回头看，我觉得这段经历挺有价值：我不只是把软件安装起来，而是把一个闭源富容器一点点拆明白，再利用现有 Kubernetes、存储和数据库能力让它长期工作。

我有时也会想，自己会不会是国内第一个把 W&B Local 私有化后，又真正给整个团队维护一两年的人。不过企业内部实践很难建立完整时间线，公开文章更稳妥的说法是：

> 我可能是国内较早一批把 W&B Local 私有化，并真正面向团队持续运维一两年的工程师之一。

有一点需要说明：这些经历主要来自旧版 `wandb/local` 一体化镜像。现在 W&B Self-Managed 已经推荐通过 Kubernetes Operator 部署，不能把旧版本遇到的每个问题直接套到当前产品上。当前架构仍然需要 Kubernetes、MySQL、Redis、S3 兼容对象存储和有效的 Server License，但组件管理与升级方式已经变化。

参考：[W&B Self-Managed 基础设施要求](https://docs.wandb.ai/platform/hosting/self-managed/requirements)、[W&B Kubernetes Operator](https://docs.wandb.ai/platform/hosting/self-managed/operator)

## 为什么这次选择 SwanLab

这次做 SFT，我希望找一个比 TensorBoard 更适合多人使用，又容易接入中文大模型训练框架的页面：

- ms-swift 能直接上报；
- 能看 Train Loss、Validation Loss、Learning Rate 和 Grad Norm；
- 能把多轮实验放在一起比较；
- 中文界面和文档足够友好；
- 可以部署在自己的环境里。

SwanLab 基本符合这些要求。训练命令加入 `--report_to swanlab`、Project 和实验名，数值指标就可以写进去。官方集成还覆盖 Transformers、PyTorch、LLaMA-Factory、Ultralytics 等框架，并支持 NVIDIA GPU 和多种国产加速器。

参考：[SwanLab 功能与集成](https://docs.swanlab.cn/guide_cloud/general/what-is-swanlab.html)、[SwanLab 实验结果页面](https://docs.swanlab.cn/guide_cloud/experiment_track/view-result.html)

## SwanLab 我不只跑了一个 Smoke

这次我拿真实训练验证过 SwanLab：

| 实验 | 规模 | SwanLab 验证内容 |
| --- | --- | --- |
| Qwen3.5-4B LoRA | 单张 L20、120 Step | 训练与 Validation 曲线、110 条 Base/Adapter 盲测 |
| Qwen3.6-35B-A3B LoRA | 8 × L20 | 多卡训练、四次 Validation、Run 正常结束 |
| DeepSeek V4 Flash MoE | 8 × H20、EP=8 | 训练指标、Validation 与 Checkpoint |
| DeepSeek V4 TCP/RDMA | 双机 16 卡、六轮 Run | 同项目实验对比、Loss 与 Step Time |
| DeepSeek V4 收敛实验 | 双机 16 卡、60 Step | 发现 Validation Loss 在 Step 30 后回升 |

![SwanLab 中的六轮 DeepSeek V4 TCP/RDMA 实验](../../assets/training/deepseek-v4-rdma/swanlab-runs.png)

最后一个结果对我很有意义。如果只看 Train Loss，会认为 Step 60 更好；Validation Loss 却说明 Step 30 附近已经达到最佳点，继续训练开始过拟合。实验追踪终于不只是“训练结束后留一张图”，而是真的影响了早停和 Checkpoint 选择。

SwanLab 也有明确边界。页面里的 Step Time 变快，不能证明训练真的走了 RDMA；通信路径仍然要看 NCCL 的 `NET/Socket`、`NET/IB`、`GDRDMA` 日志以及网卡 Counter。SwanLab 负责 Run 和训练指标，Prometheus、DCGM Exporter 与 Grafana 负责 GPU、节点和网络，两类数据需要用同一个 Run ID 对齐。

完整实测见：[SwanLab 自托管与真实 SFT 指标](swanlab-self-hosted.md)、[DeepSeek V4 双机 RDMA 训练实测](rdma-distributed-training-benchmark.md)

## W&B 和 SwanLab 应该怎样选

下面只比较我实际关心并验证过的部分，不代表所有商业版本的完整功能。

| 问题 | W&B | SwanLab | 我的建议 |
| --- | --- | --- | --- |
| 训练曲线和超参数 | Workspace、过滤、分组和面板成熟 | 表格与多实验曲线更直接 | 常规 SFT 两者都够用 |
| 中文 LLM 框架 | 通用生态成熟 | ms-swift、LLaMA-Factory 接入方便 | 国内 LLM 训练优先试 SwanLab |
| 模型和数据制品 | Artifacts、Registry、版本与血缘完整 | 文件保存能力在完善，我尚未验证同等级闭环 | 资产治理优先 W&B |
| 自动调参 | Sweeps、Launch 体系成熟 | 不是本次验证重点 | 大规模 HPO 优先 W&B |
| 报告与协作 | Reports、Tables、可编程 Workspace 和权限成熟 | 日常比较和分享更轻 | 正式研究报告偏 W&B |
| 断网补传 | `wandb offline/sync` 我实际用过 | 支持 Offline 与 `swanlab sync` | 两边都要做断网恢复测试 |
| 私有化部署 | Operator + MySQL + Redis + S3 | Helm + PostgreSQL + Redis + ClickHouse + Vector + S3 | 生产环境都不轻 |
| 企业治理 | License、SSO、服务账号、审计体系完整 | 需要按团队规模和版本继续评估 | 合规场景单独做 PoC |

W&B 的优势不只是一张 Loss 曲线。它可以把 Run、数据集、Checkpoint、模型版本、Registry、报告和自动化连起来。SwanLab 当前给我的感受则是先把训练实验做好，让曲线、参数、日志和环境快速集中起来。

参考：[W&B 项目能力](https://docs.wandb.ai/models/track/project-page)、[W&B Registry](https://docs.wandb.ai/models/registry/create_collection)、[W&B Launch Sweeps](https://docs.wandb.ai/platform/launch/sweeps-on-launch)

## SwanLab 私有化同样不是一个小容器

SwanLab 的训练接入很轻，但它的 Kubernetes 版本同样包含 Gateway、前端、Server、Auth、House、PostgreSQL、Redis、ClickHouse、Vector 和 S3 兼容对象存储。

所以我现在会把“好不好接入”和“好不好运维”分开评价：

- 开发接入：SwanLab 确实比较轻；
- 短期 PoC：可以很快看到页面；
- 团队生产：数据库、对象存储、备份、升级、容量和高可用一个都不会少。

组件名字可以不同，生产运维的问题不会自动消失。

参考：[SwanLab Kubernetes 部署](https://docs.swanlab.cn/self_host/kubernetes/deploy.html)

## 从 W&B 迁移到 SwanLab，不能只搬一条 Loss

SwanLab 支持把 W&B 代码实时转接，也可以转换 W&B Server 和本地 Run 的历史数据。不过当前官方说明主要支持标量图表，不能期待 Artifacts、媒体、Reports、权限和完整血缘全部自动搬过去。

我会先选两三个项目做迁移演练：

1. 只读归档原始 W&B Run 目录；
2. 转换标量指标，核对 Step 数、端点、最值和 Summary；
3. 单独导出媒体与文件，用数量、大小和 Hash 验证；
4. 重新登记 Base Model、Adapter、数据集 Hash、Git Commit 和评测结果；
5. 确认新旧页面与原始数据一致后，再逐步扩大范围。

SwanLab SDK `0.8.0` 还修改过本地日志格式，新旧日志不能直接混用。因此训练镜像必须固定 SDK，并真正跑一次“断网训练—恢复网络—离线补传—页面核对”。

参考：[SwanLab 转换 W&B 数据](https://docs.swanlab.cn/guide_cloud/integration/integration-wandb.html)、[SwanLab 离线同步](https://docs.swanlab.cn/guide_cloud/experiment_track/sync-logfile.html)

## 一套实验追踪平台上线前，至少验收这些事情

不管最后选 W&B、SwanLab 还是别的产品，我现在都会检查下面这些项目：

- [ ] 真实训练可以连续上报标量、日志和媒体，不只是随机数 Demo；
- [ ] 相同项目的多次 Run 可以按参数、标签和指标比较；
- [ ] 网络中断不会拖垮训练，恢复后可以离线补传；
- [ ] 数据库、指标存储和对象文件有一致的备份与恢复方案；
- [ ] 真正执行过 Pod 重建、数据库恢复和对象存储恢复；
- [ ] 有容量模型：Run 数、指标频率、指标基数、媒体大小和保留时间；
- [ ] SDK 与服务端版本被固定，并有升级回归用例；
- [ ] License、用户规模、功能限制和到期处理已经明确；
- [ ] 平台可以导出数据，停用时有迁移和退出方案；
- [ ] 训练指标与 GPU、节点、网络监控能通过 Run ID 对齐。

如果这些问题没有答案，页面现在能打开，也不能说明它已经可以给团队长期使用。

## 如果让我现在重新选

我当前会这样组合：

```text
ms-swift / PyTorch
  -> SwanLab：Run、超参数、Loss、Validation、实验比较
  -> 对象存储：Checkpoint、Adapter、数据集与预测文件

Kubernetes / GPU / NIC / RDMA
  -> Prometheus + DCGM Exporter + Grafana：基础设施与通信监控
```

当前主要做 Qwen、DeepSeek SFT 和多机训练实验，SwanLab 已经够用，而且接入成本比较低。

如果以后出现下面这些需求，我会重新正式评估 W&B：

- 数据集、Checkpoint 和模型版本需要完整血缘；
- 需要 Registry、审批、别名、审计与自动化；
- 需要 Sweeps、Launch 和大规模超参数搜索；
- SSO、服务账号、多团队权限与合规成为硬要求；
- 团队能够接受正式 License 和运维支持成本。

我不会简单地下结论说 SwanLab 比 W&B 好，或者 W&B 一定比 SwanLab 强。对我当前的训练实验来说，SwanLab 更合适；对一套完整的企业 MLOps 系统来说，W&B 依然值得认真评估。

真正应该避免的是只看 Demo 页面做决定。实验追踪系统一旦成为团队的训练历史入口，就必须像数据库和对象存储一样被认真对待。
