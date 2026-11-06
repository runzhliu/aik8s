---
title: 腾讯 CNB 是什么？与 GitHub、GitLab、Gitee 的选型比较
description: 从代码协作、CI/CD、云开发、AI Agent、安全边界与成本评估腾讯 CNB，并比较主流研发平台
status: evolving
date: 2026-11-06
last_reviewed: 2026-11-06
---

# 腾讯 CNB 是什么？与 GitHub、GitLab、Gitee 的选型比较

## 一目了然

**CNB（云原生构建）不只是一个构建工具，也不是 Kubernetes 发行版，而是围绕 Git 仓库、容器化 CI/CD、远程开发环境和 AI 辅助研发构建的平台。**社区版是公有云托管服务；企业版按官方说明部署于企业自有腾讯云 VPC。它值得与 GitHub、GitLab 和 Gitee 一起考察，但不能因为都能托管 Git，就认为各家的部署形态、权限与费用相同。

- 希望把代码、流水线、云开发和 AI 辅助放在同一研发入口，且接受其云服务或腾讯云 VPC 部署边界，可以评估 CNB。
- 全球开源协作与现有 GitHub 工作流是关键约束，可优先评估 GitHub；若主要要求自管研发平台与 Runner，可重点比较 GitLab Self-Managed、GitHub Enterprise Server 和 Gitee 私有化方案。
- NPC 是可委托执行任务的自动化角色，不等于无需监督的开发者。默认读代码、写评论；开启工作模式及满足权限条件后才可写代码、推分支并创建 PR。
- 本文截至 **2026-11-06**，根据公开官方资料分析，**没有登录账号体验、进行安全审计或性能实测**。价格、配额、地区可用性和功能条件会变化，采购前应复核。

## 1. 产品有哪些层次

CNB 的名称强调云原生构建，但从[官方仓库介绍](https://docs.cnb.cool/zh/repo/intro.md)、[构建介绍](https://docs.cnb.cool/zh/build/intro.md)和[AI 功能介绍](https://docs.cnb.cool/zh/ai/intro.md)看，实际讨论至少包括以下几层：

| 层次 | 能力与作用 | 不能直接推导的结论 |
| --- | --- | --- |
| 代码与协作 | Git 仓库、分支保护、Pull Request、Issue 和版本管理 | Git 历史可迁移，不代表 PR 评论、审批策略及附件自动完整迁移 |
| 构建与制品 | 通过 `.cnb.yml` 描述事件、Docker 环境与任务；可使用缓存、插件和制品库 | 基于容器不意味着对不可信代码有足够的强隔离 |
| 云开发 | 基于构建能力提供远程开发，支持 WebIDE、VS Code、Cursor 等客户端连接 | 远程开发环境不自动等于生产集群，也不保证兼容所有本地扩展 |
| AI 辅助 | CodeBuddy NPC、云开发内的 CodeBuddy、变更/错误分析、知识库等 | 功能可用性、数据流向、模型和实际质量取决于版本、配置与授权 |
| 企业治理 | 社区版由平台托管；企业版部署于企业腾讯云账号内的 VPC，并支持对接 OAuth | 不能据此认定企业版可装在任意本地机房，也不能把自管构建节点等同于平台任意位置自部署 |

[企业版文档](https://docs.cnb.cool/zh/enterprise.html)还列明了功能前提：NPC 和部分 AI 能力需要配置大模型；知识库还需要 Elasticsearch 与向量模型。文档提出兼容 OpenAI Chat Completions API、上下文长度和 Tool Use 等要求；**接口兼容只是接入条件，不证明任意模型、代理工具、工具调用语义或数据策略都能无缝互换**。

### 一个最小流水线长什么样

下面按[官方构建语法](https://docs.cnb.cool/zh/build/intro.md)编写一个**未在 CNB 实跑的教学示意**：仓库 `main` 分支收到 push 后，在指定容器镜像中输出 Python 版本。它不构成测试或部署，也不会创建生产凭据。

```yaml
# .cnb.yml
main:
  push:
    - docker:
        image: python:3.13-slim
      stages:
        - python --version
```

与 GitHub Actions 的工作流文件或 GitLab CI 配置一样，关键思想是把触发条件、环境和步骤跟代码一起评审；但配置语法与事件模型不同，需要针对平台重写。正式流水线还应固定可信镜像摘要、安装并锁定依赖、运行测试、控制凭据，并验证分支与事件权限。

### 与 CODING 的关系

[CODING 官方下线公告](https://coding.net/help/docs/admin/pay/price-adjustment.html)于 2025-06-23 发布，列出的节点包括：2025-09-01 标准版下线、2025-09-30 停售、2026-03-30 停止续购，并计划于 2028-09-30 停止服务。官方将 CNB 描述为下一代产品，开发域转向 CNB，协作、测试、文档等场景转向 TAPD。**这不意味着 CODING 全部功能都在 CNB 内，也不代表全部资产可一键迁移。**停服计划及实际迁移支持应再次向官方确认。

## 2. 参考架构：从提交到部署

下面是便于讨论的**概念架构，不是已经部署或验证过的方案**：

```text
开发者 / 评审者                  AI 使用者
    │                                │ @NPC，受角色与模式限制
    ▼                                ▼
Git 仓库 ── PR / Issue ──► 人工评审与保护分支
    │                                ▲
    ├── 云开发环境                   │ AI 建议 / 可选分支与 PR
    │                                │
    └── push / PR 事件 ─► CNB 流水线 ─┘
                         │ 测试、扫描、构建
                         ▼
                   制品 / OCI 镜像仓库
                         │ 按环境审批与授权
                         ▼
                GitOps 控制器或部署流水线
                         │
                         ▼
                  Kubernetes 集群
```

CNB 提供仓库、声明式构建和远程开发等构件；图中的镜像签名、审批、GitOps 控制器、Kubernetes 网络和权限控制是**建议自行设计或集成的环节**，不是声称平台默认全部提供。构建环境与生产集群可以分离：先生成可追溯镜像摘要，再由受控发布主体按环境部署，避免给每次 PR 任务生产管理员凭据。

## 3. 与 GitHub、GitLab、Gitee 比较

以下是为选型建立的能力地图，不是统一版本的功能承诺。**GitHub Cloud、GitHub Enterprise Server、GitLab.com、GitLab Self-Managed、各家企业版与私有化产品应分别核对**。尤其不能把 GitHub Cloud 的 Codespaces、托管 Runner 或 Copilot 权益自动套到 Enterprise Server，更不能把 CNB 社区 SaaS 与其他产品的自管版本当作同一运维责任。

| 维度 | 腾讯 CNB | GitHub | GitLab | Gitee |
| --- | --- | --- | --- | --- |
| 面向对象与协作 | 仓库、PR、Issue，面向希望结合构建和远程开发的团队 | GitHub Cloud 适合以开源与跨组织协作为中心的团队；仓库、PR 和 Issues 是常见协作入口 | 覆盖仓库、合并请求和研发流程，可按托管或自管形态选择 | 代码托管与企业研发协作；适合考察中文团队已有使用习惯 |
| CI 与执行节点 | `.cnb.yml`、Docker 环境与云构建；企业版文档也列出自主管理计算资源 | Actions 可使用 GitHub 托管或自托管 Runner，能力和费用依产品、规格而定 | GitLab CI/CD 使用 Runner，GitLab.com 等有托管 Runner，也可自管 | [Gitee Go](https://gitee.com/features/gitee-go) 提供 CI/CD；以具体产品、购买条件和执行资源为准，**不可假定 SaaS 免费自带** |
| 云开发 | 云原生开发支持 WebIDE 和远程客户端；配额、资源计费依版本而定 | GitHub Cloud 的 Codespaces 是云开发环境，受计划、用量和计费约束 | Workspaces 文档列为 Premium/Ultimate，需要兼容的 Kubernetes 集群与 agentk 等条件 | 应按所选版本核实云 IDE、托管环境及外部集成，不把它们视为默认标配 |
| AI 与权限 | CodeBuddy NPC 具有限时、限仓、限权的委托模型；企业版需配置模型 | Copilot 覆盖编码辅助和 Agent 场景；功能、策略、模型与许可依计划和产品形态 | GitLab Duo 提供 Agent 与非 Agent 能力；需核对计划、部署及数据策略 | 有 [AI 队友](https://gitee.com/ai-teammates)等产品入口；具体权限、模型、计费和部署以合同及版本为准 |
| 部署 | 社区版 SaaS；企业版部署企业腾讯云 VPC | GitHub Cloud 是托管服务；Enterprise Server 是单独的自管理产品，功能矩阵需单列 | GitLab.com、Self-Managed、Dedicated 是不同形态 | 企业云服务与 [Gitee 私有化产品](https://gitee.cn/)应区分 |
| 生态、采购与成本 | 适合核对腾讯云、TAPD 集成与核时/AI 用量；企业版有授权门槛 | 全球开源社区与 Marketplace 集成值得评估；核对席位、Actions、Codespaces、AI 和数据传输 | Runner、集成与自管生态值得评估；计入基础设施、升级和安全运维 | 考察本地协作、产品方案与商务支持；Go、AI、私有化及资源应分别询价 |

能力依据包括 [GitHub Actions 自托管 Runner](https://docs.github.com/en/actions/concepts/runners/self-hosted-runners)、[GitHub Codespaces](https://docs.github.com/en/codespaces/about-codespaces/what-are-codespaces)、[GitHub Copilot](https://github.com/features/copilot)、[GitHub Enterprise Server](https://docs.github.com/en/enterprise-server@3.19/admin/overview/about-github-enterprise-server)、[GitLab Runner](https://docs.gitlab.com/ci/runners/)、[GitLab Workspaces](https://docs.gitlab.com/user/workspace/) 和 [GitLab Duo](https://docs.gitlab.com/user/gitlab_duo/)。比较费用时应分别查阅 [GitHub 价格](https://github.com/pricing)、[GitLab 价格](https://about.gitlab.com/pricing/)和 [Gitee 企业版定价与采购入口](https://gitee.com/enterprises/price)，并按所在地区、计划与报价确认；这里不推测竞品数值。

### 如何缩小候选范围

1. **社区协作优先**：统计外部贡献者、现有 Actions/集成和身份体系，再看更换平台对参与门槛的影响；GitHub 是自然候选，但不应以社区规模替代合规审核。
2. **自主管理优先**：先写清楚必须部署在本地 IDC、特定云，还是仅要求企业 VPC；再分别审查 GitLab Self-Managed、GitHub Enterprise Server、Gitee 私有化及 CNB 企业版的实际边界。
3. **一体化云开发优先**：对比 CNB 云开发与 GitHub Cloud Codespaces；GitLab Workspaces 另需考虑 Kubernetes 资源与管理责任。要按相同团队、时长和资源规格计算总成本。
4. **中文协作和国内采购优先**：CNB 与 Gitee 都值得纳入；分别核验产品版本、账户与合同主体、企业身份、支持 SLA、存储位置、集成和迁移成本，不假定网络或支持体验。

## 4. CNB 社区版费用怎么算

根据 [CNB 定价](https://docs.cnb.cool/zh/pricing.md)，社区版每个**顶级组织独立结算**，免费额度与超额按量计费如下。CPU、GPU 和 AI 月度用量额度月底清零，不累积；仓库及对象存储按自然月**日均用量**减去对应免费额度，而不是把月末瞬时峰值直接当账单。

| 项目 | 免费额度 | 超额单价 |
| --- | ---: | ---: |
| Git 仓库存储 | 100 GiB | 1 元/GiB/月 |
| 对象存储（含制品、LFS 等） | 100 GiB | 1 元/GiB/月 |
| 构建 CPU | 160 核时/月 | 0.125 元/核时 |
| 云开发 CPU | 1600 核时/月 | 0.125 元/核时 |
| 构建 GPU、开发 GPU | 各 0 核时/月 | 各 0.5 元/核时 |
| AI Credits | 500 credits/月 | 0.05 元/credit |

核时不是任务个数：**8 核使用 1 小时等于 8 核时**。NPC 事件按文档计入云开发用量，模型 Token 消耗还会消耗 AI Credits，因此不能只预算 AI 额度。CPU/GPU 与 AI 的超额要有可用预算：免费额度用尽而未绑定预算或可用额度不足时，相关任务会被终止或能力受限；不是自动无限透支。具体冻结、跨月归属与结算以价格页为准。

**纯算术示例，并非账单或实测**：假设同一个顶级组织当月构建 CPU 320 核时、云开发 CPU 2000 核时、AI 700 credits，Git 存储日均 120 GiB、对象存储日均 110 GiB，无 GPU 或其他计费项，且已绑定足额预算：

- 构建 CPU：`(320 - 160) × 0.125 = 20 元`；云开发 CPU：`(2000 - 1600) × 0.125 = 50 元`。
- AI：`(700 - 500) × 0.05 = 10 元`；Git 存储：`(120 - 100) × 1 = 20 元`；对象存储：`(110 - 100) × 1 = 10 元`。
- 合计所列项约 **110 元**。实际账单还取决于统计、资源、预算与当期规则；此例不包含 GPU、网络、税务等可能的其他费用。

[企业版中国站](https://docs.cnb.cool/zh/enterprise.html)列出 License 为每授权用户每年 1024 元或每月 100 元，**100 授权起售**；部署消耗的云资源由资源提供方另计。按最低 100 授权简单相乘，年订阅授权为 102400 元/年，月订阅为 10000 元/月，均未含云资源和其他服务，不应据此推算折扣、税务或最终合同金额。官方还提示 License 到期后禁止写操作，连续性设计必须覆盖续约与数据导出。

## 5. NPC：权限边界与安全实践

[NPC 官方说明](https://docs.cnb.cool/zh/build/npc.md)把 `@CodeBuddy` 描述为运行在流水线里的自动化角色。默认模式下它可读代码并写评论；只有拥有仓库 Developer 及以上权限的用户开启「替我上班」工作模式，才允许它写代码、推送代码、创建分支和 PR。其临时 `CNB_TOKEN` 依当事人角色签发，默认当前仓库、仅本次任务有效，角色上限 Developer；Reporter/Guest 无法开启工作模式。根组织管理员可显式开启跨仓操作，将范围放宽至同一根组织，仍受限时和角色上限约束；跨仓 Fork PR 由提交者触发时另有公开仓库限制。

这些规则针对文档所述 **`@npc` 事件**。在普通流水线中使用 `npc:go` 或通过其他入口触发时，令牌和提示词规则可能不同，不能机械套用。建议：

- 从只读评论开始，对写模式设置可信人员范围；保护主分支，要求独立人工评审、测试和合并，不把 Agent 的 PR 当作已验收结果。
- 默认不启用跨仓；确有需要先列允许范围及退出条件，评估根组织内所有仓库的暴露面。核验 Fork、外部贡献者和机器人账户的触发权限。
- 把 Issue、PR、仓库文件、依赖输出和日志视为不可信输入：提示词注入可能诱导模型读取秘密、执行命令或外传。对执行环境限制网络出口、工具、密钥和可写目录；分离测试与生产凭据。
- 固定并审核自定义 NPC 镜像、角色提示词及流水线配置，管理第三方依赖和插件；对访问、执行、生成的 diff 与模型调用建立可审计记录，并避免在日志中保存敏感内容。
- 验证临时 Token、分支保护、审批、跨仓开关、任务取消和异常退出在实际版本下的行为；权限上限并不消除有权读取的数据泄露风险。

数据治理同样重要。[CNB 隐私声明](https://docs.cnb.cool/zh/saas/privacy.html)是个人信息处理说明，指出第三方服务受第三方自身政策约束，并说明中国境内收集个人信息的存储地域；**这不等于所有代码、日志、提示词或模型调用都不会离开企业边界，也不能单凭隐私声明断言模型不训练、不留存或全部本地推理**。应就具体模型和合同核实输入输出、日志保存期、训练使用、子处理方、地域和删除机制。企业版在 VPC 中部署亦不自动证明外接模型 API 在内网；需单独验证网络路径和合同。

## 6. Kubernetes 团队应怎样使用

CNB 的价值是组织开发入口，而不是替代 Kubernetes 控制面。对于构建 AI 服务或 Agent 的团队，可考虑将应用代码、镜像构建、部署配置和评审流程串联；再使用独立的发布系统或 GitOps 控制器管理集群期望状态。流水线容器、云开发环境和生产 Pod 是不同信任域，不能因为都使用容器就共用高权限凭据。

建议以镜像摘要而非可变标签发布，保存构建来源、测试结果和制品清单；用短期、按命名空间或环境限定的身份访问集群；生产变更增加审批、策略检查和可回滚版本。若任务要执行来自 PR、依赖或 Agent 的不可信代码，应评估执行节点隔离强度、网络出口、缓存污染、资源限额和秘密注入，不以 Docker 名称作为安全保证。

GitLab Workspaces 是另一种需具体核验的架构：其[文档](https://docs.gitlab.com/user/workspace/)说明工作区运行在 Kubernetes 集群上，使用方负责限制对控制面的网络访问；文档还提示运行中的工作区在用户权限撤销后仍可能保持可访问。此例说明即使提供工作区功能，集群隔离、身份撤销和资源清理仍是运维设计的一部分。

## 7. 安全、迁移与适配清单

CNB 的[迁移工具文档](https://docs.cnb.cool/zh/guide/migration-tools.md)列有 GitHub、GitLab、Gitee 仓库批量导入、跨平台代码同步、部分类型制品迁移，以及 CODING 项目协同数据迁往 TAPD 或 CNB 的工具。工具存在不等于所有历史、权限和附件都能无损保留，仍要先做样本迁移和逐项验收。

- **资产盘点**：仓库及全部 refs、LFS、子模块、制品、镜像、Issue、PR/MR、评论、附件、Wiki、审计记录和保留策略分别列出来源、目标及责任人。
- **身份权限**：对照组织层级、SSO/OAuth、角色、分支规则、审批、机器人与 Token 生命周期；核实离职禁用与数据归属，社区版和企业版账号资产边界不同。
- **流水线改造**：列出原有 CI 配置、插件、变量、密钥、定时与事件触发器、缓存、Runner 架构、镜像访问与出网依赖。`.cnb.yml` 不保证兼容其他平台配置；重写后要测试失败、重试和取消。
- **迁移语义**：分别验证 Git 历史、LFS 对象和非 Git 协作数据能否迁移、是否保留作者及链接；更新 Webhook、仓库地址、部署密钥、镜像拉取地址。不要将一次 Git 镜像推送称为完整迁移。
- **AI 与数据**：标出模型提供方、处理地域、输入范围、提示注入防护、操作审批、日志与审计；核验是否支持所需 API 和工具调用，不能仅凭兼容接口推断质量与功能等价。
- **恢复与合同**：确认数据导出格式、备份恢复演练责任、RPO/RTO、服务级别、停服通知、费用上限、授权到期行为和供应商退出路径。

## 8. 简短验证方案与尚不能证实的事项

建议用非敏感样例仓库进行小规模验证，先约定通过标准、预算和清理责任：

1. 迁移少量分支、标签和 LFS，对比对象与提交；单独检查 Issue、PR、附件和权限规则的保留或人工补录范围。
2. 在各候选产品按相同代码、资源规格、依赖与网络条件运行测试和构建，记录排队时间、成功率、构建时长、缓存命中和账单口径；样本不足时不要外推排名。
3. 创建远程开发环境，检查 IDE 扩展、依赖、休眠恢复、数据持久性、网络限制以及权限撤销后的行为。
4. 在隔离测试仓库比较 NPC 默认模式与工作模式，测试跨仓开关、外部 PR、令牌有效期、保护分支和审核门禁；不提供真实生产密钥。
5. 使用测试制品走通从镜像构建到非生产 Kubernetes 环境的审批、部署、失败和回滚，并核对审计与可追溯性。

**本文无法证实**各平台在读者地区的实际速度、可用性、隔离强度、模型输出质量及迁移完整率；也无法从公开资料确定特定采购折扣、所有模型供应商的数据政策或 CNB 任意本地私有部署的支持情况。官方页面对性能的描述属于产品资料，不是本文的实测结果或服务保证。

## 结论

CNB 可以理解为以仓库为入口，把容器化流水线、远程开发和 AI 角色连接起来的研发平台。它与 GitHub、GitLab、Gitee 的能力存在重叠，但架构和采购边界不同：选择前先固定 SaaS 还是自管、数据和执行环境在哪里、谁负责运维，再比较协作体验与全生命周期费用。尤其对 Agent，**可触发不等于可安全授权，可生成 PR 不等于可直接合并**。

## 官方资料索引

- CNB：[代码仓库](https://docs.cnb.cool/zh/repo/intro.md)、[构建](https://docs.cnb.cool/zh/build/intro.md)、[云开发](https://docs.cnb.cool/zh/workspaces/intro.md)、[AI](https://docs.cnb.cool/zh/ai/intro.md)、[NPC](https://docs.cnb.cool/zh/build/npc.md)、[定价](https://docs.cnb.cool/zh/pricing.md)、[企业版](https://docs.cnb.cool/zh/enterprise.html)、[隐私声明](https://docs.cnb.cool/zh/saas/privacy.html)。
- [CODING DevOps 下线公告](https://coding.net/help/docs/admin/pay/price-adjustment.html)。
- GitHub：[Actions Runner](https://docs.github.com/en/actions/concepts/runners/self-hosted-runners)、[Codespaces](https://docs.github.com/en/codespaces/about-codespaces/what-are-codespaces)、[Copilot](https://github.com/features/copilot)、[Enterprise Server](https://docs.github.com/en/enterprise-server@3.19/admin/overview/about-github-enterprise-server)、[价格](https://github.com/pricing)。
- GitLab：[Runner](https://docs.gitlab.com/ci/runners/)、[Workspaces](https://docs.gitlab.com/user/workspace/)、[Duo](https://docs.gitlab.com/user/gitlab_duo/)、[价格](https://about.gitlab.com/pricing/)。
- Gitee：[企业版与采购入口](https://gitee.com/enterprises)、[企业版定价](https://gitee.com/enterprises/price)、[Gitee Go](https://gitee.com/features/gitee-go)、[AI 队友](https://gitee.com/ai-teammates)、[私有化产品](https://gitee.cn/)。
