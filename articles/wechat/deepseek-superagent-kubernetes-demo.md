# 把 DeepSeek Super-agent 部署到 Kubernetes：从群聊需求到代码 PR

DeepSeek 最近公开了 **dsh-superagent-prototype**：一套基于 DeepSeek Harness 的团队编程 Agent 研究原型。它监听协作系统中的消息，把获准的请求变成可追踪的任务，交给独立会话执行，再将结果送回原来的讨论。

我把它改造成一套 Kubernetes Demo，用 Mattermost 接收需求、Gitea 保存代码，再用真实任务检查它能否接单、并行执行、接受追加要求以及在重启后继续工作。三个复杂任务中，两个交付了待审核的拉取请求（Pull Request，PR），一个没有完成。下面先解释它如何工作，再看这套 Demo 的设计和结果。

## Super-agent 怎样把消息变成任务

DeepSeek Harness，简称 DSH，提供模型接入、会话、上下文、文件与命令工具。Super-agent 以 Bundle，也就是插件和配置组合的形式运行在 Harness 上，增加任务生命周期与团队协作规则。

可以把一次工作分成六步：接收事件，检查身份与规则，确定授权范围，建立工单，派给执行器，交付结果。

![从事件到可追踪工作的原理示意](assets/deepseek-superagent-demo/principles.png)

图中是官方原型的简化流程。它内置 GitHub 来源和可选的飞书入口，围绕一个 GitHub 仓库工作；后文的 Mattermost、Gitea 是本次增加的适配。

这里最值得理解的是三个区别。

**消息和任务有各自的身份。** 来源 Source 把消息转换成不可变事件 Trigger，讨论 Thread 保存持续上下文。接受工作后才创建工单 Ticket，并记录授权 Mandate。后续讨论可以补充上下文，但不会自动扩大任务权限。

任务和某次执行也分开管理。一次派工 Assignment 将工单交给执行器；执行中断后可以重新派工，而工单、讨论关系与待处理输入仍然保留。一个模型回合结束，只能说明这轮生成结束，不能据此认定代码已经交付。

最后，做完和送达是两件事。Outbox 保存待发送的消息与回执，再通过 Channel 写回原线程。SQLite 和持久化待执行动作，使重启后能够找回尚未完成的派工、输入投递和回复。外部写入仍需核对：远端已经成功、本地还没记录时，重试存在重复窗口。

主动接单也有范围。原型提供 `off`、`observe`、`auto` 三种模式，分别控制规则推断出来的工作；默认 `observe` 只记录判断，不实际接这种任务。合法的明确请求在这三种模式下仍可执行，因此关闭主动接单与停止正在运行的任务需要分别操作。

## Demo 为什么选 Mattermost 和 Gitea

为了让交互过程看得见，我保留完整的聊天与代码评审界面：用户在 Mattermost 提需求，Agent 在 Gitea 创建分支和 PR，最后在原聊天线程中给出链接和测试结果。

整套 Demo 只有四个长期运行的 Pod：DSH、Gitea、Mattermost 和 PostgreSQL。Gitea 使用 SQLite，PostgreSQL 为 Mattermost 提供存储；没有增加 Redis、消息队列或对象存储。控制与工具执行部分没有申请 GPU，推理使用已有模型 API。

本次版本为 DSH `0.2.2-alpha.2`、镜像 `0.2.2-alpha.2-r1`，Gitea `28.2.0`、Mattermost Team Edition `12.0.1`、PostgreSQL `17.11`。DSH 镜像来自 `runzhliu/deepseek-harness-docker`。独立 Profile，也就是运行配置，以及新的持久卷用于保存本次实验，没有挂入个人会话目录。

![本次 Demo 的部署与交付关系](../../docs/assets/rag-agent/deepseek-superagent-practice/workflow.png)

两个执行器是 DSH 会话，共享这个演示实例，各自有工作目录和代码分支；图中的目录隔离不等于独立沙箱。

**Mattermost、Gitea 的接入需要实现来源适配。** 要处理账号身份、事件游标、线程上下文、回复通道，以及 PR 与原工单的绑定，不能只替换 GitHub 域名。本次也为机器人单独配置了演示频道和仓库权限。

实际接入时遇到过一个小问题：Mattermost 的 `update_at` 会随线程相关元数据变化。用它构造消息身份，会把旧需求再次当作新输入。修正后，事件身份使用消息 ID 和正文编辑版本 `edit_at`，原文真正被编辑才产生新事件。这样的去重细节，直接决定 Agent 会不会重复接活。

这套集成包含自定义代码，下面展示的是设计与验收记录，不是上游镜像直接附带的一键部署方案。

## 用户怎样提交任务、追踪结果

第一项需求很小：修复商品总价函数没有乘数量的问题。提交任务时，把范围、测试和交付条件一起写清楚。例如：

```text
@demo-agent 修复 src/pricing.js 中未乘 quantity 的错误。
补充数量大于 1 的回归测试，运行 npm test。
创建 Gitea PR，等待人工审核，不要合并。
```

Agent 完成修改后创建 PR #1，并回到原线程报告结果。随后在同一线程追加“数量为 0 时结果应为 0”的要求，它继续修改原来的分支与 PR。第一次为 5 项测试，追加后为 7 项，实际运行均通过。

![在原聊天线程追加要求，Agent 返回同一 PR 的结果](../../docs/assets/rag-agent/deepseek-superagent-practice/chat-result.png)

截图中的中文保留原样。用户可以在聊天里继续提要求，去 Gitea 看代码，在 DSH 的 Superagent 面板查看任务状态。

为了检查并发，再提交三个独立项目，修改范围分别限定在不同子目录。控制台实际出现两个执行器运行、第三个任务排队的状态。

![实际控制台中的两个运行任务与一个排队任务](../../docs/assets/rag-agent/deepseek-superagent-practice/execution.png)

每个任务使用独立会话、工作目录和分支，减少多个任务反复切换同一个工作区的问题。如果它们修改共同接口，仍然需要集成测试；增加执行名额，也会增加下游模型服务的请求和预算压力。

## 复杂任务做到了什么

第一个项目是可靠 Webhook 投递服务。要求包含入队 API、幂等键、SQLite 持久化、有限重试、固定投递目标和基于 SHA-256 的哈希消息认证码（HMAC-SHA256）。独立验收实际启动本地接收端，检查失败两次后成功、永久 HTTP 400、签名、稳定事件 ID，以及服务重启后继续投递。

它最终交付 15 个文件，组件自测 11 项通过，独立验收 5 组通过。投递语义是至少一次，接收端仍要按事件 ID 去重。这是单进程演示服务，没有 API 鉴权、TLS、多实例协调和死信重放接口。

第二个项目是流式日志分析 CLI，也就是命令行工具。它逐行读取 JSON Lines，支持时间和服务筛选、坏行处理、延迟汇总，并输出可直接打开的 HTML 报告。

![Agent 在 Gitea 交付的多文件日志分析工具](../../docs/assets/rag-agent/deepseek-superagent-practice/complex-pr.png)

PR #2 包含 19 个文件、两次提交，最终代码为 `66fc963`。组件自测 31 项通过，独立验收 6 组通过，其中包括在 64 MiB 的 Node 堆限制下处理 100,000 条有限基数合成记录。

![实际 CLI 生成的十万条合成日志报告](../../docs/assets/rag-agent/deepseek-superagent-practice/logscope-report.png)

这张图是交付代码的实际输出。输入包含 100,000 条合成记录，其中 5,000 条为 error，延迟均值 144.50 ms；这些是测试数据的统计，不是生产监控。统计表仍会随服务名、时间桶、错误文本的基数增长，逐行读取不意味着任意输入都恒定内存。

第三个项目是持久化的有向无环图（Directed Acyclic Graph，DAG）任务执行器，要求支持依赖校验、并发、重试、超时和进程恢复。它没有交付实现，预先定义的 5 组独立验收未执行。

| 复杂任务 | 最终交付 | 独立验收 |
| --- | --- | --- |
| Webhook 投递服务 | PR #3，`8ba2da4` | 5 / 5 组通过 |
| 日志分析 CLI | PR #2，`66fc963` | 6 / 6 组通过 |
| DAG 任务执行器 | 输出预算耗尽，期限结束后停止 | 5 组未执行 |

独立验收通过真实 HTTP、CLI 和进程检查来判断结果，与 Agent 自己写的测试分开记录。日志验收首轮有一项因严格比较浮点均值而失败；保留结果后，只将验收器改为 `1e-9` 数值容差，产品代码没有变化，第二轮通过。

两个复杂项目都停在待人工审核的 PR。包括最初的小修复在内，PR #1、#2、#3 均未合并，主分支没有被修改。

## 重启能续跑，但要看恢复了哪一层

计价函数追加要求执行期间，我重建了 DSH Pod。恢复后仍沿用同一个工单、会话、目录、分支和 PR，最终跑通 7 项测试。这验证了同一测试节点、保留数据卷条件下的继续工作。

恢复依靠持久任务记录、会话历史和工作树。重启之后，执行器需要检查文件、Git 历史和远端 PR，再决定接着做什么；原来的 Shell 进程没有因此恢复到被中断的 CPU 指令处。本次也没有验证节点断电、本地磁盘丢失和跨节点恢复。

另一种情况要分开看：原始 Webhook、DAG 窗口到期并停止后，原线程中的继续请求创建了新工单和目录。聊天线程相同，不意味着停止后仍是同一次任务恢复。

复杂任务还暴露了两类问题。

首先是演示模型桥接的传输实现。首轮长请求在 300 秒时被截断，出现 `Stream ended without finish_reason`。桥接逐小块同步回传服务端事件流（Server-Sent Events，SSE），每块都等待网络往返。修正为按约 50 ms 或 64 KiB 聚合，并区分 180 秒空闲时限与 15 分钟总时限后，保留失败记录继续验证。这个问题属于本次桥接实现。

其次是有效输出预算。DAG 多次在 8,192 输出 token 后以 `max-tokens` 结束，未生成实现。显式关闭思考并指定 32,768 token 的最小 API 探测能调用工具，但完整 DSH 会话仍观察到原来的上限。需要继续核对客户端、桥接与上游实际生效的参数；现有证据不足以归因于模型不会完成这个任务。

派工语义也影响推进：主会话曾请求“只报告状态”，执行器便按要求没有继续实现。原型中状态查询与继续实施是不同操作，持久化记录恢复了，也还要检查后续指令是否正确。

## 这套设计适合怎样落地

从这次 Demo 看，最适合先验证的是范围清楚、结果能审核的研发任务：修复缺陷、补测试、生成分析工具，再由人检查 PR。即时通信（Instant Messaging，IM）提供入口，Gitea 提供交付物，Super-agent 管理中间的任务状态，Harness 提供实际执行能力。

落地时我会先守住四个条件：

1. 使用专用实例、机器人和测试仓库，先限定谁能发起工作、能修改哪里，再检查事件去重与回复回执。
2. 持久化任务、会话和工作目录，先做单实例恢复。SQLite 状态目录有锁，直接增加副本不能得到可并发写入的高可用控制面。
3. 把执行隔离放在底层实现。独立会话和目录方便组织工作，任务授权也有明确记录；操作系统权限、网络、凭据和恶意代码隔离仍需要单独设计。
4. 给实验定义验收和期限，保留未完成任务。观察可评审结果、人工纠偏次数、调用成本和重复副作用，比单看“运行中几个 Agent”更有用。

Super-agent 值得研究的地方，是把持续发生的团队讨论组织成有身份、有范围、能追踪并交付的工作。这次 Demo 已经能让人从聊天里发起任务、在控制台看进展、去 Gitea 审查代码；两个复杂项目的交付和一个失败任务，也说明了把这条链路做好需要哪些工程细节。

完整部署设计、验收摘要与原始界面见“阅读原文”对应的公开实战文档。

## 资料与公开记录

官方研究原型与声明：https://github.com/deepseek-ai/dsh-superagent-prototype

领域模型：https://github.com/deepseek-ai/dsh-superagent-prototype/blob/6337fc823ce20251c8de8085948165c81aaa701e/docs/001-domain.md

执行与恢复：https://github.com/deepseek-ai/dsh-superagent-prototype/blob/6337fc823ce20251c8de8085948165c81aaa701e/docs/003-execution.md

部署边界与来源扩展：https://github.com/deepseek-ai/dsh-superagent-prototype/tree/6337fc823ce20251c8de8085948165c81aaa701e/docs

DSH 容器镜像：https://github.com/runzhliu/deepseek-harness-docker

公开原理解析：https://aik8s.run/ai-k8s/rag-agent/deepseek-superagent-prototype-analysis/

公开 Demo 实战：https://aik8s.run/ai-k8s/rag-agent/deepseek-superagent-kubernetes-practice/
