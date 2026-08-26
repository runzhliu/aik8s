---
title: 从 W&B Local 到 SwanLab：两年团队实验追踪实践与选型
description: 回顾我把 W&B Local 私有化并交给团队使用一两年的经历，再结合当前 SwanLab 自托管与真实 SFT 实测，聊聊两个工具应该怎么选
status: evolving
last_reviewed: 2026-08-26
---

# 从 W&B Local 到 SwanLab：两年团队实验追踪实践与选型

最近在折腾大模型 SFT，我给训练任务接上了 SwanLab。单卡 Qwen、多卡 MoE、DeepSeek V4 以及双机 RDMA 都跑过之后，我突然想起，自己其实很早就折腾过另外一个实验追踪工具——W&B。

我不是只在本地启动过一次 W&B。大概从 2023 年开始，我把 W&B Local 私有化部署到 Kubernetes，后来又给整个团队一起用，前前后后维护了一两年。数据库、对象存储、离线同步、账号、License、数据迁移，基本能踩的坑都踩过。

所以这篇文章不准备只对着官方功能列表念一遍。我更想结合自己实际运维 W&B 和最近实测 SwanLab 的经历，聊聊它们有什么区别，以及如果让我现在重新选，我会怎么选。

先说结论：**目前主要做大模型 SFT、看训练曲线和比较不同实验，我会继续用 SwanLab；如果以后真要管理数据集、Checkpoint、模型血缘、Registry、自动调参和多团队权限，W&B 仍然更完整。**

## 当年刚开始搞大模型，W&B 几乎绕不开

当年刚开始搞大模型平台时，我遇到的第一个问题不是 W&B 怎么部署，而是生产环境根本不允许用户把训练 Trace、Metrics、日志和模型相关数据直接发送到公网的 `wandb.ai`。从网络和数据安全的角度看，这个限制很正常，但用户对 W&B 的需求又非常强烈。

原因也很简单：当时大量开源模型、训练框架和教程默认都接了 W&B。用户照着社区材料跑起来之后，自然希望平台也提供相同的页面。W&B 本身又比较成熟，Project、Run、实验对比和可视化已经获得很多算法工程师认可，所以这不是平台凭空创造出来的需求，而是用户真的在催。

算法同学关心的问题也很具体：

- 这次训练的 Loss 和上一次有什么区别？
- Learning Rate、Grad Norm 和训练速度有没有异常？
- 哪组超参数效果最好？
- 网络断了之后，曲线还能不能补回来？
- 训练结束几个月后，还能不能找到当时的结果？

TensorBoard 可以看曲线，但当训练分散在不同机器、不同目录和不同用户手里时，管理起来还是很麻烦。既然生产环境不能直接访问公网 W&B，剩下的办法就是把 W&B Local 部署到内部环境。

## 一张 License、一个 StatefulSet，先把需求顶住

我后来也接触过 W&B 的销售，认真了解过正式采购。但当时的 License 确实非常贵，不是一般团队可以轻松承担的价格。那时 AI 还没有像现在这么火，公司也很难为一个训练辅助工具投入这么高的预算。

最后为了先满足用户，我用一个有效的个人或试用 License，部署了一套单副本 StatefulSet 版本的 W&B Local。现在回头看，这个方案当然比较“搓”：没有正式商业支持，也谈不上严格的生产 SLA。但它至少让用户不需要把数据发到公网，也能继续使用社区里已经很熟悉的 W&B SDK 和页面。

后来接入的不只是一个 Demo。我用它记录过 OPT、Baichuan/Megatron、YOLO 和医学影像相关训练，也看过 Loss、Learning Rate、Grad Norm、Iteration Time 和单卡 TFLOPS 等指标。训练环境网络不稳定时，还试过保留本地 Run，等网络恢复后再用 `wandb sync` 补传。

真正麻烦的是团队用起来之后。一个人用时，服务重启一下也许没什么；大量用户都在写 Trace、Metrics 和文件时，页面打不开、数据库迁移失败、容量不够或者历史曲线丢失，就会变成平台问题。

## W&B Local 不是无状态服务，而是一个富容器

W&B Local 表面上看是一个 Docker 镜像，执行 `wandb server start` 就能启动。但我进入容器分析之后发现，它其实是一个典型的富容器：里面不只有 W&B Web 服务，还有 Redis、MinIO、MySQL 相关逻辑、Nginx、后台任务和一大堆初始化与迁移脚本。

换句话说，它看上去是一个实例，实际装着一套系统。数据库、缓存、对象存储中的任何一块出问题，都可能让历史 Run 无法正常打开。

如果按照生产标准做，Redis、MySQL 和对象存储当然都应该尽量使用公司级的标准产品，交给专业系统保证高可用、备份和容量。但旧版 W&B Self-Hosted 有很多限制，并不是把连接地址改一下就能完成外置。

对象存储就是最明显的例子。我们本身已经有公司级对象存储，我也尝试过把内置 MinIO 换掉，但当时版本还依赖一个 Gateway 一类的中间组件，并且涉及 S3 协议和签名兼容。折腾了一轮以后，依然没办法可靠对接内部对象存储，最后只能放弃。

既然 MinIO 暂时换不了，我就转而把富容器里真正需要保存的目录梳理清楚，再通过 RBD、CephFS 等存储为它提供持久化和扩容能力。这个事情很重要，因为大量用户共用一个 W&B 实例以后，训练 Metrics、Trace 和上传文件增长非常快，MySQL 和 MinIO 很容易被打满。

数据库这边最后做得更完整一些。经过数据库初始化、迁移权限和表结构等一轮排查，我们最终把 MySQL 接到了公司级数据库服务，后面有专业 DBA 同事帮忙保障备份、容量和稳定性。MinIO 继续保留在实例侧，MySQL 则从富容器里逐步解耦出去。

License 也是同样的问题。Self-Hosted 的个人或试用 License 只有几个月有效期，如果到期后直接重建，历史数据和用户使用都会非常被动。我当时通过分析容器日志、数据库、MinIO 和启动流程之间的关系，梳理出了在拿到新的有效 License 后更新授权、同时保留原有数据的办法。这里不公开具体位置、令牌或操作步骤，重点是这套实例不需要因为授权更新就从零重建。

这套方案谈不上漂亮，却真的在大量用户使用、数据持续增长、没有正式商业支持的情况下稳定运行了两年，最后才正式下线。现在回头看，我觉得这确实是一段挺牛的工程经历：不只是把软件装起来，而是把一个闭源富容器一点点拆明白，再用现有的 Kubernetes、存储和数据库能力让它活下来。

## 我可能是国内比较早折腾这件事的人

回头看这些记录，我有时候会想，我会不会是国内第一个把 W&B Local 私有化以后，又真正给整个团队连续维护一两年的人。

但这个事情其实很难证明。企业内部做过的系统大多不会公开，网上搜不到也不能说明别人没有做过。所以公开文章里，我更愿意这样描述：

> 我可能是国内较早一批把 W&B Local 私有化，并真正面向团队持续运维一两年的工程师之一。

这句话我觉得已经足够了。重点不是争一个“第一”，而是我确实经历了 W&B 从能跑、有人用，到容量、迁移、备份、授权更新和持续维护的完整过程。

不过这里也要说明一下：我当时研究的主要是旧版 `wandb/local` 一体化镜像，现在 W&B Self-Managed 已经推荐通过 Kubernetes Operator 部署。当前架构仍然需要 Kubernetes、MySQL、Redis、S3 兼容对象存储和有效的 Server License，但部署与升级方式已经变了。

所以旧经验能说明团队化实验追踪为什么会产生运维成本，却不能简单认为今天的 W&B 还会出现当年的每一个问题。

参考：[W&B Self-Managed 基础设施要求](https://docs.wandb.ai/platform/hosting/self-managed/requirements)、[W&B Kubernetes Operator](https://docs.wandb.ai/platform/hosting/self-managed/operator)

## 最近为什么又选了 SwanLab

这次做 SFT，我最开始只是想找一个比 TensorBoard 更适合多人使用的页面。要求也不复杂：

- ms-swift 能直接上报；
- 可以看 Train Loss、Validation Loss、Learning Rate 和 Grad Norm；
- 可以把几轮实验放在一起比较；
- 页面和文档对中文用户友好；
- 最好还能私有化部署。

SwanLab 基本符合这些要求，而且接入 ms-swift 比较直接。训练命令里加上 `--report_to swanlab`、Project 和实验名，数值指标就可以写进去。

它并不是只有中文界面这个优点。官方文档列出的集成覆盖 Transformers、PyTorch、LLaMA-Factory、ms-swift、Ultralytics 等框架，还支持 NVIDIA GPU 和多种国产加速器。对国内训练环境来说，这些细节确实比较实用。

参考：[SwanLab 功能与集成](https://docs.swanlab.cn/guide_cloud/general/what-is-swanlab.html)、[SwanLab 实验结果页面](https://docs.swanlab.cn/guide_cloud/experiment_track/view-result.html)

## 两个工具实际怎么比

下面这个表是我根据自己用过的部分做的判断，不代表两个产品所有版本和商业功能的完整比较。

| 我关心的问题 | W&B | SwanLab | 我的判断 |
| --- | --- | --- | --- |
| 训练曲线和超参数 | Workspace、过滤、分组和面板很成熟 | 表格和多实验曲线更直接 | 当前 SFT 两者都够用 |
| 中文 LLM 框架接入 | 通用框架生态很成熟 | ms-swift、LLaMA-Factory 接入方便 | 当前训练更偏向 SwanLab |
| 模型和数据制品 | Artifacts、Registry、版本与血缘完整 | 可以保存文件，但我还没有验证到同等级闭环 | 真做资产治理时 W&B 更强 |
| 自动调参 | Sweeps、Launch 比较成熟 | 这次没有重点验证 | 大规模 HPO 优先看 W&B |
| 报告和协作 | Reports、Tables、可编程 Workspace 和权限体系完整 | 日常实验对比与分享更轻 | 正式研究报告偏 W&B |
| 断网补传 | `wandb offline/sync` 我实际用过 | 支持 Offline 与 `swanlab sync` | 都能用，但要测试版本兼容 |
| 私有化部署 | Operator + MySQL + Redis + S3 | Helm + PostgreSQL + Redis + ClickHouse + Vector + S3 | 上生产都不算轻 |
| 基础设施监控 | 能采训练进程附近的系统指标 | 也支持 GPU、CPU、磁盘和网络指标 | 都不能代替 Grafana 和 RDMA 监控 |

W&B 强的地方不只是一张 Loss 曲线。它可以把 Run、数据集、Checkpoint、模型版本、Registry、报告和自动化连起来。项目页面本身就包含 Runs、Sweeps、Reports 和 Artifacts，Registry 还能继续管理模型与数据版本。

参考：[W&B 项目能力](https://docs.wandb.ai/models/track/project-page)、[W&B Registry](https://docs.wandb.ai/models/registry/create_collection)、[W&B Launch Sweeps](https://docs.wandb.ai/platform/launch/sweeps-on-launch)

SwanLab 目前给我的感受更像是：先把训练实验这件事情做好，让训练任务很快接进来，让曲线、参数、日志和运行环境可以统一查看。对现在的我来说，这已经解决了最直接的问题。

## SwanLab 我不只是跑了一个 Smoke

这次我确实拿真实训练验证过 SwanLab：

1. `Qwen3.5-4B + 单张 L20 + BF16 LoRA`，完成 120 Step、四次 Validation 和 110 条 Base/Adapter 盲测；
2. `Qwen3.6-35B-A3B + 8 × L20 + ZeRO-3 LoRA`，完整记录训练和验证指标；
3. `DeepSeek V4 Flash + 8 × H20 + EP=8`，完成 MoE 训练、Validation 和 Checkpoint；
4. `DeepSeek V4 Flash + 双机 16 卡`，完成 TCP/RDMA 六轮正式 Run 对照；
5. 另一轮 60-Step 收敛实验里，Validation Loss 在 Step 30 最低，后面反而回升，说明模型已经开始过拟合。

![SwanLab 中的六轮 DeepSeek V4 TCP/RDMA 实验](../../assets/training/deepseek-v4-rdma/swanlab-runs.png)

最后这个例子对我来说比较有意义。以前实验追踪有时只是“训练跑完以后有张图”，这一次曲线真的影响了训练决策：如果只看 Train Loss，会觉得 Step 60 更好；看 Validation 才知道应该提前停止，并优先保存 Step 30 附近的 Checkpoint。

当然，SwanLab 页面里的 Step Time 变快，并不能证明训练真的走了 RDMA。RDMA 还是要看 NCCL 的 `NET/Socket`、`NET/IB`、`GDRDMA` 日志以及网卡 Counter。SwanLab 负责记录实验，Prometheus、DCGM Exporter 和 Grafana 负责看 GPU、节点和网络，这两个边界不能混在一起。

完整实测见：[SwanLab 自托管与真实 SFT 指标](swanlab-self-hosted.md)、[DeepSeek V4 双机 RDMA 训练实测](rdma-distributed-training-benchmark.md)

## SwanLab 私有化也不是一个小容器

第一次看到 SwanLab Docker 部署时，也很容易觉得它比 W&B 轻很多。但真正部署 Kubernetes 版本以后，会发现它同样包含 Gateway、前端、Server、Auth、House、PostgreSQL、Redis、ClickHouse、Vector 和 S3 兼容对象存储。

因此，我现在会把“好不好接入”和“好不好运维”分开看：

- 对训练代码来说，SwanLab 的接入确实比较轻；
- 做一个短期 PoC，也可以很快看到页面；
- 但要让团队长期使用，数据库、对象存储、备份、升级、容量和高可用一个都不会少。

这点跟我当年用 W&B 得到的教训其实一样：**组件名字可以不同，生产运维的问题不会自动消失。**

参考：[SwanLab Kubernetes 部署](https://docs.swanlab.cn/self_host/kubernetes/deploy.html)

## 离线同步两边都有坑

我以前用 W&B 时遇到过训练网络中断。训练指标保存在本地 Run 目录，网络恢复后执行 `wandb sync`，Loss 等曲线可以补回去；但当时 GPU 等实时系统指标没有完整补齐。

SwanLab 也支持 Offline 和 `swanlab sync`，还可以把 W&B 代码实时转接到 SwanLab，或者转换 W&B Server 和本地 Run 的历史数据。这个迁移能力挺实用，不过目前官方说明主要支持标量图表，不能期待 Artifacts、媒体、Reports、用户权限和完整血缘一起自动搬过去。

另外，SwanLab SDK `0.8.0` 修改过本地日志格式，新旧日志不能直接混用。这类问题只有真正做一次“断网训练—恢复网络—离线补传—页面核对”才能发现，检查 `import swanlab` 没什么用。

参考：[SwanLab 转换 W&B 数据](https://docs.swanlab.cn/guide_cloud/integration/integration-wandb.html)、[SwanLab 离线同步](https://docs.swanlab.cn/guide_cloud/experiment_track/sync-logfile.html)

## 绕不开的 W&B License

W&B 的 License 当时确实很贵，公司一直没有正式采购。我接触销售、了解过价格之后，发现它不是一般团队能轻松承担的成本。我那套环境主要依赖个人或者试用 License 维持，因此虽然给团队用过很长时间，但始终不能算一套有商业支持和生产 SLA 的正式服务。

更麻烦的是，早期 Self-Hosted License 几个月就会过期。一个工具的功能再强，如果授权成本进不了预算，团队又已经把训练记录都放进去，平台维护者最后会非常被动。这也是我后来重新考虑实验追踪平台的重要原因。

前面提到的手动更新，是在拿到新的有效 License 后保留原有数据，不是绕过授权。不过我仍然不会把“没有正式采购”写成值得推广的方案，更不会在公开文档里保留 License 文件位置、令牌或具体替换步骤。当前 W&B 官方写得很清楚，Self-Managed 需要有效的 Server License；个人版也不能当作公司团队的长期方案。

参考：[W&B Self-Managed License 要求](https://docs.wandb.ai/platform/hosting/self-managed/requirements)、[W&B 当前价格与版本](https://wandb.ai/site/pricing/)

## 如果要把旧 W&B 数据迁到 SwanLab

我不会一上来就把所有历史目录全量转换。比较稳妥的方式是先选两三个项目：

1. 保留原始 W&B Run 目录的只读归档；
2. 转换标量指标，核对 Step 数、曲线端点、最大值、最小值和 Summary；
3. 单独导出媒体与文件，用文件数、大小和 Hash 验证；
4. 重新登记 Base Model、Adapter、数据集 Hash、Git Commit 和评测结果；
5. 确认 SwanLab 页面与原始数据一致后，再逐步扩大范围。

迁移的目标不能只是“新页面上也出现了一条 Loss”。如果模型、数据和评测结果之间的关系丢了，曲线搬过去也没有解决可复现性问题。

## 回头看，旧笔记还有一个更严重的问题

我重新翻旧资料时，发现以前为了方便排障，在笔记里留下过明文 API Key、对象存储密钥、数据库密码、用户密码、Cookie 和 License Token。现在看，这显然不是一个好习惯。

即使这些值大部分已经过期，也应该按照凭据泄露处理：能撤销的撤销、能轮换的轮换，公开文章全部使用占位符，训练任务则通过 Kubernetes Secret 或其他密钥系统注入。

这个教训可能比 W&B 和 SwanLab 谁更好更重要。实验追踪系统本身会保存训练配置、代码信息、日志和模型文件，一旦平台凭据也散落在 README 和脚本里，数据安全就很难真正做好。

## 如果让我现在重新选

我现在会这样组合：

```text
ms-swift / PyTorch
  -> SwanLab：Run、超参数、Loss、Validation、实验比较
  -> 对象存储：Checkpoint、Adapter、数据集与预测文件

Kubernetes / GPU / NIC / RDMA
  -> Prometheus + DCGM Exporter + Grafana：基础设施与通信监控
```

当前主要做 Qwen、DeepSeek SFT 和多机训练实验，SwanLab 已经够用，而且接入成本比较低。

等到以后真的需要下面这些能力，我再正式评估 W&B：

- 数据集、Checkpoint 和模型版本的完整血缘；
- Registry、审批、别名、审计与自动化；
- Sweeps、Launch 和大规模超参数搜索；
- SSO、服务账号、多团队权限与合规；
- 正式的商业支持和 SLA。

我现在不会简单地下结论说 SwanLab 比 W&B 好，或者 W&B 比 SwanLab 强。它们解决问题的深度不完全一样。对我目前的训练实验来说，SwanLab 更合适；对一套完整的企业 MLOps 系统来说，W&B 依然值得认真评估。
