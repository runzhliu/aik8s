---
title: Grok Bot 技术综述：持久化云电脑、多智能体协作与企业治理
description: 系统介绍 Grok Bot 与 Grok、@grok 和 xAI API 的区别，分析其持久化云电脑、Skills、Routines、多 Bot 协作、审批、安全边界及 Kubernetes 企业接入方式
status: evolving
last_reviewed: 2026-11-04
---

# Grok Bot 技术综述：持久化云电脑、多智能体协作与企业治理

2026 年 8 月，xAI 发布 Grok Bot。它不是在 Grok 聊天界面旁边多放了一个“自动执行”按钮，而是一种有名字、岗位、记忆和持续工作环境的托管智能体：用户通过消息交代任务，Bot 在云端浏览器、文件系统和终端中继续工作，需要确认时再回来请求审批。

如果把普通聊天助手看成一次电话咨询，Grok Bot 更像一名配有长期工位和公司电脑的远程同事。电脑不会在每轮对话后销毁，浏览器登录、文件和命令行环境可以持续保留；同时，长期工位也意味着账号、网络、审批、审计和数据清理都必须按企业系统来治理。

本文依据截至 2026 年 11 月 4 日的官方资料，讨论 Grok Bot 的产品边界、实现结构、适用任务和生产接入方式。产品仍在快速更新，套餐和管理能力应以官方当前页面为准。

## 一页结论

1. **Grok Bot 是托管的 Computer-use Agent，不是一个可下载部署的 Grok 模型。** 工作通常运行在 Cursor 云中的持久化计算机上；桌面端还可在权限允许时操作本机，移动端负责聊天、查看过程和审批。
2. **“持久化”是它与普通聊天助手最明显的区别。** Bot 能保留岗位上下文、历史摘要和偏好，云电脑能保留文件、浏览器会话与命令行环境，用户关闭笔记本后任务仍可继续。
3. **隔离边界位于用户之间，不在同一用户的 Bot 之间。** 官方架构为每个用户提供一台独立 Firecracker microVM；同一用户创建的所有 Bot 共享这台计算机及其中的登录、文件和 CLI 凭据。
4. **Skill 与 Routine 把一次成功操作变成可复用自动化。** Skill 描述怎样做，Routine 描述何时做；安全路径是先完成一次低风险任务，再稳定步骤、固化 Skill，最后增加定时或事件触发。
5. **多 Bot 协作更像共享办公室中的角色分工。** Bot 可以并行处理任务、在群聊中交换信息和交接工作，但共享计算资源和凭据，增加 Bot 数量并不等于获得更多安全域。
6. **审批是控制面，不是撤销机制。** “Stop”或拒绝后续动作不会自动回滚已经发送的邮件、修改的文件或外部系统状态。不可逆动作仍需由业务系统提供幂等、审批与补偿。
7. **Auto Review 有价值，但不能代替最小权限和网络隔离。** 它并不覆盖所有副作用；连接器策略与浏览器网络访问也是两套边界，禁用某个插件不代表 Bot 无法打开对应网站。
8. **企业版提供的关键能力集中在网络与审计。** Network Controls、Team Setup、Action Recording、组织级开关、审计日志和 OpenTelemetry 导出等能力并非都包含在自助 Teams 套餐中。
9. **Grok Bot 可以参与 Kubernetes 运维，但不应直接持有集群管理员凭据。** 更稳妥的路径是只读 API、GitOps Pull Request、受控运维网关和短期身份，并把变更放到独立审批链中。
10. **选择它的核心理由是快速获得“云电脑 + Agent + 日常应用”的完整体验。** 如果企业必须在自有集群运行、需要自定义镜像、严格数据驻留或完全掌控执行 Runtime，则应评估自建 Agent Harness 与 Sandbox。

## 近期更新：从个人助手走向团队工作台

截至 2026 年 11 月 4 日核对，官方更新日志列出的最新版本是 2026 年 10 月 27 日的 0.78.1。下面区分**官方说明的功能**与本文的工程分析；这些内容不是本文作者的实机验收，不同账号、地区和套餐的实际入口可能不同。[官方更新日志](https://x.ai/changelog/bot)

| 日期与版本 | 官方更新 | 对使用者的意义 |
| --- | --- | --- |
| 2026 年 9 月 19 日 | 部分 SuperGrok Heavy 用户可以在 grok.com 使用 Grok Bot（[网页发布说明](https://grok.com/release-notes/sep-19-2026)） | 入口开始从独立客户端扩展到网页，具体权限以账号实际显示为准 |
| 2026 年 10 月 24 日，0.75.8 | Bot 可以通过需要用户确认的卡片建议增删或修改 Auto Review 规则 | 规则也能在工作过程中调整，但仍须核对作用范围 |
| 2026 年 10 月 26 日，0.77.0 | 更新日志列出 1Password 登录授权和从其他 AI 助手导入记忆等功能；部分功能要求最低客户端版本 | 迁移体验更完整，也要管理被导入的长期上下文和第三方账号 |
| 2026 年 10 月 27 日，0.78.1 | 增加商品卡片、订阅管理模板、团队 Bot 分享和凭据相关改进 | 自动化从检索与生成继续走向跨应用的实际操作，支付和订阅变更应设置明确审批 |

### 入口：从桌面、手机到网页与 X

官方说明，在支持的账号和地区，用户可以在 X 帖子或回复中提及 `@bot`，把帖子交给自己的主 Bot。公开回复主要确认任务已交接，处理过程与结果留在 Bot 对话里；调用会消耗使用额度。它要求 X 与 Grok 账号关联、账号有 Grok Bot 权限并创建自己的 Bot；共享 Bot 不能接收这种提及，地区资格也有限制。`@bot` 是任务入口，不能等同于用于公开问答的 `@grok`。[在 X 上提及 Bot](https://docs.x.ai/grok-bot/tag-on-x)

### 共享 Bot：共享角色不等于共享所有人的聊天

[Shared Bots 官方文档](https://docs.x.ai/grok-bot/shared-bots)区分了**共享同一个 Bot**和**分享模板后各自创建副本**。所有者或 Manager 可授权团队、人员或组；Collaborator 可以聊天，Manager 还可修改指令、技能、记忆与应用。用户与共享 Bot 的个人聊天彼此私密，但 Bot 允许保存团队共同知识。分享前要检查所有者添加的应用和 Secrets：它们可在获授权成员的对话里使用；成员自己的连接器则有单独授权过程。

执行位置也取决于入口：用户在自己的对话或 Slack 私聊中，通常使用该用户的云电脑；群聊、Slack 频道等共享场景可能使用共享 Bot 的电脑；隐私设置更严格时也可能改用独立会话电脑。因此“每人一台共享电脑”是个人 Bot 的基本模型，不能直接套用到所有团队协作场景。普通成员的回复通常使用被回复者的额度，部分未关联账号的 Slack 自动消息由所有者额度承担。

### 治理：强制审批、本机执行和模型输入检查

原版文章曾说企业无法禁止成员关闭 Auto Review；**这一说法现已过时**。Enterprise 管理员现在可以开启 Enforce Auto-review 并配置团队规则，默认关闭；官方同时说明目录组可以配置例外。它覆盖命令、应用调用、Computer Use、自动化写入和委派等动作，但记忆写入与大多数设置变化等并非全部覆盖。应检查实际开关、组例外与目标系统权限，不能把模型审查当成唯一安全边界。[企业控制项](https://docs.x.ai/grok-bot/teams-and-enterprises)

桌面客户端也可在开启并获得授权后访问用户本机：运行命令、读写或传递文件；默认按命令逐次审批，管理员可限制允许的本机执行策略。这是**操作用户设备**，不等于把托管云电脑自建到企业 Kubernetes。企业还应注意云电脑流量可经桌面网络路由，相关允许范围与本机执行权限是独立设置。[执行环境和本机权限](https://docs.x.ai/grok-bot/computer-and-apps)

Enterprise beta 的 Inference Hooks 可将模型请求及其上下文发送给企业安全服务，获取允许或拒绝结论；它检查**模型输入**，不是动作执行时的逐步拦截。新配置的 Shadow 模式记录而不阻断；其他模式可配置检查失败时放行或阻断。即便选择阻断，官方也说明配置无法加载时会放行并记录异常；分流比例不足 100% 或 Shadow 检查被跳过时也会有未检查请求，不能把它描述成绝对无旁路的防护。官方要求检查服务使用公网可路由的 HTTPS 443 地址和受信任证书，不接受私网、环回地址、重定向或反向隧道；这对只在内网运行的企业安全网关是实际接入约束。[Inference Hooks](https://docs.x.ai/grok-bot/inference-hooks)

### 模型与数据：托管产品不等于模型选择可控

当前[安全文档](https://docs.x.ai/grok-bot/security)说明，Grok Bot 自行管理模型选择，用户没有模型选择器，服务组合可能包含第一方或第三方模型；团队在其他 Cursor 产品配置的模型 allowlist 不一定约束 Grok Bot。企业若对模型供应商或分包方有合同限制，应在试点前与供应商核实适用范围。

隐私模式、模型供应商零数据保留、云电脑上的持久化文件和安全审计属于不同问题：官方表示开启 Privacy Mode 时客户数据不用于训练，但这不等同于云电脑文件不会持久化，也不能替代对数据驻留、保留期和审计的合同确认。本文没有验证实际调用了哪些模型或对某家供应商执行了哪些审计。

### 套餐与额度：不要把“没有 Token 账单”理解为无限使用

[官方套餐与计费说明](https://cursor.com/help/grok-bot/plans)区分新的 The X Subscription 与旧版 Cursor / SuperGrok 关联方案：前者的 Premium、Super、Ultra 包含 Grok Bot，使用 Cursor 和 Grok 应用共享的每周额度池，超出后可按充值额度继续；旧方案的每周额度和可选的按量费用按对应 Cursor 账户规则处理。旧版 Cursor 计划和 SuperGrok 关联额度不叠加，取较高的一档；具体方案应以账号界面和当前合同为准。

这改变的是产品向用户**展示与结算用量的方式**，不是说模型推理没有 Token 或没有成本。官方说明试用消耗与 Agent 步骤、Token 等工作量有关；多个 Bot 的交接和后台 Routine 也会消耗额度。旧版按量月度上限不是正在运行任务的硬中断，已开始的运行可能越过限额后才停止新增按量使用；预算控制应同时设置任务时间、频率、审批和用量监控。

2026 年 11 月初，额度也引发了讨论：TechCrunch 报道部分用户的每周用量显示突然耗尽；Musk 在回应中表示服务成本相对收入过高，但报道时并未给出各套餐未来额度的完整调整细则。**个别用户反馈不能推导为所有套餐统一限额，也不能据此算出固定的降额比例。** 企业试点宜记录账号套餐、任务类型和每周额度消耗，以便判断预算与可持续性。[TechCrunch 报道](https://techcrunch.com/2026/11/02/elon-musk-throttles-grok-bot-limits-due-to-unsustainably-high-costs/) · [Musk 的回应](https://x.com/elonmusk/status/2116992258520064397)

### 自动操作的新边界：以购物和订阅为例

0.78.1 的商品卡片可展示价格、商店和配送进度，并引入订阅查询、试用和取消等模板；实际能否操作取决于连接器、地区与授权。这里有一个容易忽略的边界：官方 Vault 文档说明，**已保存的银行卡可能在结账时自动填充，不能假定每次付款都会重新弹窗**；如果要求逐笔确认，官方建议不要保存卡，或使用提供单次授权的支付方式，并在支付系统侧核对最终扣款。[Vault 和安全登录](https://docs.x.ai/grok-bot/vault)

可落地的试点顺序是：先让 Bot 检索并产出草稿，核对引用和原系统状态；再对连接器、网络和本机权限分别做收敛；最后才让经过业务审批的接口执行有限写入。遇到网页登录验证、敏感支付或不可逆操作时，先把执行对象、金额和副作用交给人确认。

## 1. 先分清四个名字相近的产品

“Grok Bot”很容易和 Grok、X 上的 `@grok` 以及 xAI API 混在一起。它们共享品牌和部分模型能力，但交付形态完全不同。

| 名称 | 主要入口 | 状态是否持久 | 能否操作电脑与应用 | 谁负责执行环境 | 典型用途 |
| --- | --- | --- | --- | --- | --- |
| Grok 聊天助手 | grok.com、移动应用 | 以会话和产品记忆为主 | 以聊天、搜索、文件、图像和语音能力为主 | xAI 产品 | 问答、研究、内容生成 |
| X 上的 `@grok` | X 帖子与回复 | 围绕社交上下文 | 不提供用户专属持久化电脑 | X / xAI | 解释帖子、回答公开问题 |
| xAI API 模型 | HTTP API / SDK | 请求本身通常无状态 | 需要开发者自行接工具、状态和沙箱 | 调用方 | 构建自有应用和 Agent |
| Grok Bot | 桌面端、移动端、部分网页入口 | Bot 和记忆长期存在，云电脑持久化 | 浏览器、文件系统、终端、连接器 | Cursor 云托管 | 跨应用、多步骤、定时与协作任务 |

xAI 公开了 Grok 聊天助手和 X 上 `@grok` 的部分系统提示词，但这不等于 Grok Bot 产品开源。官方 [`grok-prompts`](https://github.com/xai-org/grok-prompts) 仓库适合研究聊天产品的行为边界，不能用来在本地还原 Grok Bot 的云电脑、审批、连接器和组织管理能力。

Grok Bot 的官方发布页把它描述为“always-on agents”。更准确的工程表达是：**由托管 Agent Harness 驱动、具备持久化执行环境和人机审批界面的 Computer-use Agent 产品**。[Introducing Grok Bot](https://x.ai/news/introducing-grok-bot)

## 2. Grok Bot 的逻辑架构

官方文档没有公开完整服务端实现，但披露了足以判断安全边界的架构：桌面、移动及部分网页入口提供交互；个人 Bot 通常在 Cursor 云中的用户专属 Firecracker microVM 内使用 Shell、浏览器和图形界面，也可通过 Cursor 的连接器策略调用 MCP 工具。桌面端的可选本机执行与云电脑是不同的权限路径。

```mermaid
flowchart TB
    U[桌面端或移动端] --> C[会话、任务与审批控制面]
    C --> B1[研究 Bot]
    C --> B2[运营 Bot]
    C --> B3[工程 Bot]

    subgraph VM[每个用户一台持久化 Firecracker microVM]
      B1 --> S1[独立 Bot 屏幕]
      B2 --> S2[独立 Bot 屏幕]
      B3 --> S3[独立 Bot 屏幕]
      S1 --> E[共享浏览器会话、文件和 CLI 环境]
      S2 --> E
      S3 --> E
    end

    E --> WEB[网站与 SaaS]
    E --> DEV[终端与开发环境]
    C --> MCP[Cursor Connector / MCP 后端]
    MCP --> APP[获准的企业应用]
    E --> NET[企业私网接入客户端]
    NET --> API[内部 API、代码库或观测平台]

    P[人工审批与 Auto Review] -.约束动作.-> C
    O[管理策略、网络控制与审计] -.治理.-> C
    O -.治理.-> VM
```

这套结构有三层不同的状态：

| 状态层 | 保存内容 | 共享范围 | 主要风险 |
| --- | --- | --- | --- |
| Bot 状态 | 名称、岗位、对话、摘要、偏好和学习到的上下文 | 单个 Bot | 过期记忆、错误经验、角色漂移 |
| 云电脑状态 | 文件、浏览器 Cookie、已登录会话、CLI 凭据 | 同一用户的所有 Bot | 横向读取、凭据混用、临时文件残留 |
| 企业连接器状态 | OAuth 授权和 MCP 工具访问 | 受成员与团队策略约束 | 授权范围过宽、工具副作用、第三方风险 |

官方说明 OAuth Token 保存在 Cursor 的连接器后端，Bot 调用工具时不会直接获得 Token。浏览器中人工登录形成的 Cookie、下载文件和放入终端的 CLI 凭据则存在用户的共享云电脑里，需要采用不同的清理和隔离策略。[团队与企业架构](https://docs.x.ai/grok-bot/teams-and-enterprises)

## 3. 为什么持久化云电脑很关键

传统浏览器 Agent 常把每次任务放进新环境：安全边界清楚，但用户必须反复登录、上传文件和解释背景。Grok Bot 选择了另一条路，让环境随用户长期存在，从而减少重复准备。

### 3.1 它带来的能力

- 浏览器登录和应用会话可跨任务复用；
- 文件可以由一个 Bot 生成，再由另一个 Bot 继续处理；
- 已安装的命令行工具与工作目录无需每次重建；
- 用户关闭本地设备后，后台 Turn 和 Routine 仍可运行；
- 每个 Bot 有自己的屏幕，可并行推理、使用连接器和处理文件；
- 单个 Bot 的一个屏幕同一时刻只执行一项 Computer-use 任务。

重要限制：持久化不等于完整备份。官方说明正常更新或恢复通常保留已保存文件、浏览器状态和登录，但完整电脑更新、Recover 或 Reset 会移除安装的应用和依赖，并可能丢失未保存的最新修改。重要结果应放在共享工作区并另行备份；长任务中断后要先检查外部副作用，再决定从哪里续跑。[使用电脑与应用](https://docs.x.ai/grok-bot/computer-and-apps)

### 3.2 它改变了威胁模型

同一用户的多个 Bot 在角色和会话上分开，在计算机和凭据上并不隔离。一个“日报 Bot”下载到本地的文件，另一个“工程 Bot”在技术上也处于可访问该文件的环境中。把 Bot 取成不同名字，不能形成安全边界。

因此，企业应按 **一台长期存在的员工电脑** 来管理它：

- 一个 Cursor 用户对应一个凭据域；需要严格隔离的工作负载使用不同用户；
- 浏览器只登录完成任务所需的低权限账号，完成后及时退出；
- 临时导出的客户数据、报表和密钥文件必须有清理周期；
- 不把不同安全级别的生产运维、财务支付和市场调研放在同一用户环境；
- 删除 Bot 后继续检查共享电脑，因为 Bot 删除并不等于共享文件和登录会话都被清除。

[Grok Bot 概览](https://docs.x.ai/grok-bot/overview)明确说明：用户之间采用严格隔离，而同一用户的所有 Bot 共用一台计算机。这个细节比“每个 Bot 都有自己的屏幕”更值得安全评审关注。

## 4. Bot、Skill 与 Routine 怎样组成自动化

Grok Bot 把自动化拆成三个容易理解的对象：

| 对象 | 回答的问题 | 适合保存的内容 | 不适合保存的内容 |
| --- | --- | --- | --- |
| Bot | 谁来做 | 稳定职责、工具范围、工作风格、审批边界 | 某一次任务的临时要求 |
| Skill | 怎样做 | 输入、步骤、验证、交付格式、异常处理 | 调度时间和一次性上下文 |
| Routine | 什么时候做 | 时间或事件触发、运行频率、调用的 Skill | 大段操作细节 |

例如，“每周服务稳定性检查”可以这样拆分：

```text
Bot：平台稳定性助手
岗位：读取观测平台和 Kubernetes 只读接口，整理风险，不修改生产环境。

Skill：生成服务稳定性周报
输入：服务清单、SLO、变更记录、Prometheus/Grafana 链接
步骤：检查错误率、延迟、容量、告警和近期变更
验证：每个判断必须附查询时间、来源链接和原始指标
输出：Markdown 周报和待确认事项
审批：发送群消息、创建工单或修改配置前必须确认

Routine：每周一 09:00 执行上述 Skill，完成后把草稿交给负责人审阅
```

官方还支持通过示范教授流程：用户带 Bot 完成一次多步骤操作，再把稳定路径保存为 Skill。示范会提高起步速度，却不能省略验证。网页结构、字段语义和权限可能变化，正确顺序应是：

```mermaid
flowchart LR
    T[安全的一次性任务] --> D[人工示范或文字说明]
    D --> V[核验步骤与结果]
    V --> S[保存为 Skill]
    S --> R[安全样例回归]
    R --> A[增加 Routine]
    A --> M[持续检查失败与业务变化]
```

[Skills and routines](https://docs.x.ai/grok-bot/skills-routines-and-automations)建议 Skill 明确触发条件、输入与权限、步骤、验证、输出和审批点。这和生产 Runbook 的结构接近：能重复执行只是起点，知道如何确认成功以及何时停止才是可靠自动化。

## 5. 多 Bot 协作解决什么问题

Grok Bot 支持多个 Bot 并行工作、相互发消息、在群聊中共享上下文和交接任务。群聊可容纳 2 到 6 个 Bot，适合把复杂任务拆成清晰角色：

```mermaid
sequenceDiagram
    participant U as 用户
    participant R as 研究 Bot
    participant D as 数据 Bot
    participant E as 编辑 Bot
    U->>R: 调研主题、来源边界和截止时间
    par 并行取证
      R->>R: 浏览官方资料并记录来源
      D->>D: 读取内部指标并生成表格
    end
    R->>E: 交接来源摘要
    D->>E: 交接数据与图表
    E->>E: 统一结构、术语和结论
    E->>U: 提交草稿与待确认动作
    U-->>E: 审批发布或要求修改
```

这类编排的收益来自 **角色、来源和验收条件分开**，而不是 Bot 越多越好。交接链过长会重复读取、放大错误并消耗更多额度；共享电脑还可能形成浏览器焦点、文件名和账号状态冲突。

适合拆分的情况包括：

- 不同子任务可以并行，且各自有独立交付物；
- 不同角色需要不同的上下文和长期记忆；
- 需要让一个 Bot 审阅另一个 Bot 的证据与格式；
- 最终有一个明确的汇总负责人。

一件短任务如果只涉及一个应用，直接交给单个 Bot 通常更清楚。官方协作文档也提醒，过多交接可能造成重复和噪声。[Message and collaborate](https://docs.x.ai/grok-bot/chat-and-collaboration)

## 6. 审批与 Auto Review 的真实边界

Grok Bot 可以在发送消息、发布内容、支付、删除、权限修改、生产操作或接受法律条款前请求审批，但不能假定每笔支付都会触发确认：已保存的银行卡可能自动填充。用户可对动作选择本次允许、拒绝，也可在一定范围内保存长期规则；如果允许规则和强制审批规则冲突，Require Approval 优先。

一次完整的动作链更接近下面的结构：

```mermaid
flowchart TD
    A[Bot 提议动作] --> R{规则与 Auto Review}
    R -->|允许| E[执行]
    R -->|需要确认| H[人工查看具体动作]
    R -->|拒绝| B[阻止并反馈原因]
    H -->|批准| E
    H -->|修改或拒绝| B
    E --> O[外部系统产生结果]
    O --> V[读取回执并验证]
    V --> L[记录动作、来源和结果]
```

需要特别理解四个限制：

1. **区分单次批准和长期规则。** Allow once 只批准本次；Always allow 可以保存适用范围内的规则，因此要核对规则及目标对象。
2. **审批不会撤销先前副作用。** 用户中途发送“Stop now”，已发出的邮件或已完成的外部修改仍然存在。
3. **Auto Review 不覆盖每一种副作用。** 官方文档明确举例，记忆写入和多数设置变化不都经过相同审查。
4. **企业可强制，但要检查例外。** Enterprise 可以启用 Enforce Auto-review 和团队规则；默认关闭，目录组可配置例外，且它不覆盖所有副作用。

生产系统仍应在目标系统一侧落实：

- 只读和写入使用不同身份；
- 写操作使用结构化 API，明确资源、版本和幂等键；
- 生产变更走 Pull Request、工单或发布平台审批；
- 财务与法务动作由业务系统执行二次确认；
- 每次执行读取回执，并保存可审计的资源 ID。

参考：[Approvals, security, and privacy](https://docs.x.ai/grok-bot/approvals-security-and-privacy)、[Security FAQ](https://docs.x.ai/grok-bot/security-faq)。

## 7. 连接器策略不等于网络策略

Grok Bot 可以使用 Cursor 允许的 MCP 连接器，也可以直接在浏览器中访问网站。这两条访问路径相互独立：

```mermaid
flowchart LR
    B[Grok Bot] --> M{连接器策略}
    M -->|允许| C[MCP / SaaS Connector]
    M -->|禁止| X[不能调用该连接器]

    B --> N{网络策略}
    N -->|允许目标| W[浏览器、Shell 或 API 访问]
    N -->|禁止目标| Z[网络连接被阻断]
```

因此，管理员禁用某个 Slack、GitHub 或数据库插件后，Bot 仍可能通过浏览器访问对应网站，只要网络策略和网站登录允许。若要关闭目标服务的所有路径，需要同时处理连接器、浏览器身份和网络出口。

官方当前的关键套餐边界如下：

| 管理能力 | Teams | Enterprise | 生产意义 |
| --- | --- | --- | --- |
| Team Rules | 有 | 有 | 向所有 Bot 注入团队规则 |
| Cloud Agent delegation 开关 | 有 | 有 | 控制是否委派独立编码 Agent |
| Public template sharing | 有 | 有 | 控制 Bot 模板是否可公开分享 |
| Connector policy | 有 | 有 | 允许或禁止连接器；MCP allowlist 为企业版能力 |
| Network Controls | 无 | 有 | 限制云电脑可访问的域名、IP 和端口 |
| Enforce Auto-review / 团队审批规则 | 无 | 有 | 强制审查和统一规则，需核对组例外 |
| Execution on Local Computer | 有 | 有 | 限制 Bot 操作成员本机的权限上限 |
| Inference Hooks | 无 | 有（beta） | 由企业安全服务检查模型输入 |
| Team Setup | 无 | 有 | 在云电脑启动时安装企业工具或网络客户端 |
| Action Recording | 无 | 有 | 记录 Bot 动作，默认关闭 |
| Audit logs / OpenTelemetry Export | 无 | 有 | 输出管理、安全与动作证据 |
| SCIM | 无 | 有 | 自动开通和回收成员身份 |

自助 Teams 如果没有网络策略，目标访问默认是 allow-all；Network Controls 是 Enterprise 能力。云电脑目的地白名单默认不约束 Cursor 后端访问的远程 MCP 服务：使用白名单模式时还须显式打开 Apply to MCP servers，并核对连接器实际请求的主机。企业评估时不能只确认“购买了团队版”，还要逐项核对所需控制是否实际包含。[Grok Bot for teams and enterprises](https://docs.x.ai/grok-bot/teams-and-enterprises)

另外，官方提供的是多客户共享的静态出口地址，并不提供每个客户独享的出口 IP。如果内网白名单、安全域或审计制度依赖专属源地址，需要在接入设计阶段解决，而不是上线后再补。

## 8. 企业私网怎样接入

Grok Bot 的托管云电脑运行在 Cursor 云中，不支持部署到企业自己的 Kubernetes、私有云或本地机房，也不支持自带 VM 镜像；可选的本机命令执行并不改变这一托管边界。Enterprise 的 Team Setup 可以在每个云电脑中安装客户维护的 Linux 网络客户端，官方列举了 Tailscale 和 Cloudflare Tunnel，也允许使用其他 VPN、Zero Trust 或 Mesh 客户端。

```mermaid
flowchart LR
    G[Grok Bot 云电脑] --> Z[企业维护的网络客户端]
    Z --> GW[Zero Trust / VPN 网关]
    GW --> P[内部只读 API]
    GW --> R[代码与制品服务]
    GW --> O[Prometheus / Grafana]
    GW --> K[Kubernetes 受控入口]

    I[企业 IdP 与设备策略] -.身份.-> Z
    A[审计与 OTEL] -.记录.-> G
    A -.记录.-> GW
```

Team Setup 脚本在云电脑上以高权限运行，可在启动时执行并周期刷新。企业负责网络客户端和连接状态，Cursor 负责运行安装、检查脚本。脚本本身不应嵌入长期密钥，密钥应通过企业身份与 Secret 交付机制获得。[Connect to private networks](https://docs.x.ai/grok-bot/private-networks)

引入私网之前应回答：

- Bot 需要访问哪些 API、域名、IP 和端口；
- 访问身份属于员工、服务账号，还是临时任务身份；
- 账号被禁用后，浏览器会话、VPN 会话和服务 Token 如何一起撤销；
- 是否允许下载数据到持久化云电脑；
- 哪些日志进入 SIEM，能否串联用户、Bot、动作、目标和结果；
- 数据驻留是否满足要求。官方 FAQ 表示云电脑当前运行在美国，如需书面驻留承诺应与账户团队确认。

## 9. 与 Kubernetes 结合的推荐方式

Grok Bot 适合读取监控、整理事件、生成变更建议和发起 GitOps 流程。它不应成为一个携带 `cluster-admin` kubeconfig 的通用跳板机。

### 9.1 推荐访问路径

```mermaid
flowchart TB
    B[Grok Bot] --> Q{任务类型}
    Q -->|观测与诊断| RO[只读观测 API]
    Q -->|配置变更| PR[Git Pull Request]
    Q -->|标准运维动作| OP[受控运维 API]

    RO --> PROM[Prometheus / Grafana]
    RO --> KRO[Kubernetes 只读聚合接口]
    PR --> CI[CI 校验与策略检查]
    CI --> CD[人工审批与 GitOps 同步]
    OP --> AP[工单、审批、幂等与审计]

    CD --> K8S[Kubernetes]
    AP --> K8S
    KRO --> K8S
```

这三条路径分别处理不同风险：

| 任务 | 建议接口 | Bot 权限 | 变更如何生效 |
| --- | --- | --- | --- |
| 查询 Pod、Event 和工作负载状态 | 只读聚合 API 或受限 Kubernetes API | `get/list/watch`，不读取 Secret | 不产生变更 |
| 查询 SLO、延迟和资源利用率 | 只读 Prometheus/Grafana API | 限定数据源和组织 | 不产生变更 |
| 修改 Deployment、HPA 或策略 | Git 仓库 | 创建分支和 PR | CI、评审、GitOps Controller |
| 重启标准服务、扩缩容 | 运维平台的窄 API | 只能调用允许动作 | 工单审批后由平台执行 |
| 紧急生产操作 | 人工 Runbook | Bot 提供证据和建议 | 值班人员执行并复核 |

若必须直接访问 Kubernetes API，可先从最小只读 Role 开始，并避免读取 Secret、执行远程命令和访问节点代理：

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: agent-observer
rules:
  - apiGroups: [""]
    resources: ["pods", "events", "nodes", "namespaces"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["apps"]
    resources: ["deployments", "statefulsets", "daemonsets", "replicasets"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["batch"]
    resources: ["jobs", "cronjobs"]
    verbs: ["get", "list", "watch"]
```

这个 Role 只是权限上限示例。实际接入还应增加集群、Namespace、Label 和查询时间范围限制，并使用短期身份或身份代理，避免把长期 ServiceAccount Token 写到共享云电脑。

### 9.2 一个可直接交给 Bot 的任务模板

官方建议任务至少包含 Outcome、Sources、Constraints、Deliverable 和 Review point。一个 Kubernetes 稳定性任务可以这样写：

```text
目标：分析 payment 服务过去 6 小时错误率上升的原因，给出按证据排序的判断。

来源：
1. 只读 Grafana 与 Prometheus；
2. production/payment Namespace 的 Pod、Event、Deployment 和 HPA；
3. 最近 24 小时的 Git 变更记录。

约束：
- 不修改集群、告警、Dashboard 或代码；
- 不读取 Secret，不进入容器执行命令；
- 每个结论写明时间范围、PromQL 或资源名称；
- 数据不足时标记“无法确认”，不要补全原因。

交付：
- 一页 Markdown 报告；
- 时间线、影响范围、三个最可能原因及反证；
- 建议的验证步骤；
- 如需改动，生成 Git Diff 草案，不创建 PR。

复核点：
完成报告后停止，等待我确认；创建工单、PR、发送消息或修改任何外部系统前再次审批。
```

这类任务把 Bot 放在“证据收集与建议”位置，让 Kubernetes、GitOps 和发布平台继续承担授权与执行职责。

## 10. 与其他 Agent 路线怎样选择

Grok Bot 的优势不是允许开发者自由组合每一个 Runtime 组件，而是把电脑操作、消息入口、持久状态、协作与审批组合成可直接使用的产品。

| 路线 | 上线速度 | 可编程性 | 执行环境控制 | 适合任务 | 主要代价 |
| --- | --- | --- | --- | --- | --- |
| Grok Bot | 快 | 中 | 低，以托管云为主，可授权操作本机 | 日常跨应用工作、浏览器流程、个人与团队自动化 | 托管边界、套餐能力、共享电脑治理 |
| 普通聊天助手 | 最快 | 低到中 | 低 | 研究、问答、内容草拟 | 难以持续操作真实系统 |
| API + Agent Framework | 中 | 高 | 由开发者决定 | 产品内 Agent、结构化业务流程 | 需要自行开发状态、工具、权限和评测 |
| RPA / 工作流平台 | 中 | 中 | 中到高 | 步骤稳定、规则明确的界面流程 | 页面变化脆弱，开放任务适应性弱 |
| 自建 Harness + Sandbox | 慢 | 最高 | 最高 | 强隔离、私有部署、定制 Runtime、大规模多租户 | 建设和长期运维成本最高 |

选择 Grok Bot 前可以用四个问题快速判断：

1. 工作是否主要发生在浏览器、终端和现有 SaaS 中？
2. 是否接受执行环境位于 Cursor 云，并按其套餐获得网络和审计控制？
3. 同一用户的多个 Bot 共享登录、文件和 CLI 凭据是否符合安全模型？
4. 业务能否把高风险动作留在现有审批、GitOps 和交易系统中？

前三个答案为“是”，且企业希望尽快让知识工作者使用持久化 Agent，Grok Bot 很有吸引力。如果硬性要求在自有 Kubernetes 中运行、使用自定义基础镜像、独享出口、特定地区数据驻留或独立机器身份，自建方案更匹配。

## 11. 企业落地的分阶段方法

### 阶段一：只读试点

- 选择研究、报告、数据整理和知识检索任务；
- 使用低敏感度数据和最小权限账号；
- 禁止外发、发布、支付、删除和生产变更；
- 保存输入、工具轨迹、输出和人工修订；
- 评估完成率、人工节省时间、错误类型和审批负担。

### 阶段二：草稿与交接

- 允许生成邮件、PR、工单和配置 Diff，但不直接提交；
- 固化已验证 Skill，给每一步增加来源和完成条件；
- 分离研究、执行和审阅 Bot，限制群聊交接数量；
- 定期清理共享云电脑中的文件、会话和无用工具。

### 阶段三：有限写入

- 仅开放幂等、可追踪、可补偿的业务 API；
- 在目标系统实施审批和资源级权限；
- 为 Routine 设置最大运行时间、频率、费用和失败通知；
- 监控身份异常、网络出口、连接器调用和审批结果。

### 阶段四：规模化治理

- 接入 SSO、SCIM、网络策略、动作记录和 SIEM；
- 按用户和凭据域规划云电脑，避免角色名称被误当作隔离；
- 建立 Skill 版本、负责人、测试样例和下线机制；
- 统计任务成功率、回滚率、越权阻止率、人工接管率和单位任务成本；
- 将模型、Harness 和外部系统升级纳入回归测试。

## 12. 评估时容易忽略的问题

| 问题 | 为什么重要 | 验证方法 |
| --- | --- | --- |
| Bot 记忆是否引用最新来源 | 记忆可能过期，不是事实库 | 修改源数据后重复任务，检查是否重新读取 |
| 删除 Bot 后还剩什么 | 共享文件和登录可能继续存在 | 删除测试 Bot，检查电脑、Cookie、下载和 CLI 会话 |
| 禁用插件后能否经网页访问 | 连接器和网络是独立通道 | 禁用测试连接器，再验证网页与 Shell 路径 |
| 多 Bot 并行是否互相干扰 | 同一用户共享电脑和凭据 | 并发处理不同账号、文件和下载任务 |
| 审批被拒绝后是否停止完整动作链 | 前序动作可能已经产生副作用 | 使用沙箱系统模拟多步骤写入和拒绝 |
| Routine 遇到页面变化会怎样 | UI 自动化可能静默偏离 | 改变测试页面字段，观察停止、告警和证据 |
| 用户离职后会话是否都失效 | IdP、浏览器和网络会话生命周期不同 | 执行完整离职演练并检查残留访问 |
| 能否还原一次生产建议的依据 | 没有输入、工具结果和版本就无法审计 | 从日志重建任务时间线与来源 |

不要只做“它能不能完成一次”的 Demo。持久化 Agent 的主要风险常出现在第二次运行、长时间后台运行、权限变化、多 Bot 并发和人员离职之后。

## 13. Grok Bot 代表了怎样的产品方向

Grok Bot 把 Agent 从“需要时打开的聊天窗口”推进到“长期存在的工作角色”：有名字、有岗位、有记忆、有电脑，能观察流程、沉淀 Skill、按 Routine 运行，并与其他 Bot 交接。这种形态降低了普通用户搭建自动化的门槛，也把过去由平台工程团队处理的问题带到了每个知识工作者面前。

它最值得借鉴的产品设计有三点：

- **让用户用岗位和交付物描述自动化，而不是先画工作流；**
- **让一次成功任务逐步升级为 Skill 和 Routine，而不是直接定时运行未知流程；**
- **把审批放回对话，使人能在具体动作和上下文中判断。**

它最需要认真评估的也有三点：

- **同一用户的所有 Bot 共用一台持久化电脑；**
- **连接器、网页网络、浏览器登录和私网客户端形成多条访问路径；**
- **组织治理能力与套餐绑定，且 Auto Review、日志和网络策略各有覆盖边界。**

Grok Bot 适合作为现有业务系统之上的智能工作层。权限、交易、发布和生产变更仍应由目标系统掌握最终控制。这样才能同时得到持久化 Agent 的效率，以及企业基础设施原有的确定性与可审计性。

## 参考资料

- [Introducing Grok Bot](https://x.ai/news/introducing-grok-bot)
- [Grok Bot overview](https://docs.x.ai/grok-bot/overview)
- [Get started with Grok Bot](https://docs.x.ai/grok-bot/get-started)
- [Create and manage Bots](https://docs.x.ai/grok-bot/bots)
- [Message and collaborate](https://docs.x.ai/grok-bot/chat-and-collaboration)
- [Use the computer and apps](https://docs.x.ai/grok-bot/computer-and-apps)
- [Skills and routines](https://docs.x.ai/grok-bot/skills-routines-and-automations)
- [Approvals, security, and privacy](https://docs.x.ai/grok-bot/approvals-security-and-privacy)
- [Grok Bot for teams and enterprises](https://docs.x.ai/grok-bot/teams-and-enterprises)
- [Grok Bot security](https://docs.x.ai/grok-bot/security)
- [Grok Bot security FAQ](https://docs.x.ai/grok-bot/security-faq)
- [Connect to private networks](https://docs.x.ai/grok-bot/private-networks)
- [Grok Bot and X](https://x.ai/news/grok-bot-and-x)
- [xAI grok-prompts](https://github.com/xai-org/grok-prompts)
