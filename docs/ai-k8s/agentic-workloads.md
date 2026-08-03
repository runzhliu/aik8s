---
title: AI Agent、沙箱与工具执行
description: Agent 工作负载的运行时隔离、网络、身份、工具权限和审计设计
status: evolving
last_reviewed: 2026-08-02
---

# AI Agent、沙箱与工具执行

Agent 工作负载与普通 Deployment 不同：它可能长时间保持状态，主动访问外部工具，生成并执行代码，处理不可信网页或仓库内容，并在没有人逐步确认的情况下采取动作。

Kubernetes 可以提供身份、配额、网络、存储和生命周期底座，但不能自动证明 Agent 的行为安全。

## 一、Agent 为什么不是普通微服务

| 特征 | 普通服务 | Agent Runtime |
| --- | --- | --- |
| 生命周期 | 多副本、可替换 | 常见单例、会话长、可暂停恢复 |
| 状态 | 外部数据库为主 | 工作区、记忆、工具状态 |
| 输入 | API 请求 | Prompt、网页、仓库、文件、事件 |
| 行为 | 预定义代码路径 | 模型动态规划和工具调用 |
| 权限 | 固定下游 API | 文件、Shell、浏览器、云 API 等 |
| 风险 | 代码漏洞 | 还包括 Prompt Injection 和工具滥用 |

因此需要把 Agent 控制面、执行沙箱和工具代理分开。

## 二、参考架构

```text
用户/API
   │
   ▼
Agent Control Plane
├── 会话、策略、预算、审批
├── Sandbox 生命周期
└── 审计与状态
   │
   ▼
隔离执行环境
├── Agent Runtime
├── 临时/持久 Workspace
└── 受控工具客户端
   │
   ▼
Tool Gateway / Broker
├── 身份交换
├── 参数校验
├── 限速与审批
└── 外部 API、Git、浏览器、数据库
```

Agent 不应直接持有所有外部系统的长期管理员密钥。

## 三、Agent Sandbox 的定位

Kubernetes SIG Apps 的 Agent Sandbox 提供 `Sandbox` CRD，用于管理具有稳定身份和持久状态的单例工作负载；扩展 API 包括 `SandboxTemplate`、`SandboxClaim` 和 `SandboxWarmPool`。参考：[Agent Sandbox Documentation](https://agent-sandbox.sigs.k8s.io/docs/)

它解决的是声明式生命周期：

- 创建和回收隔离环境；
- 稳定身份与工作区；
- 模板化运行时；
- 预热池降低启动延迟；
- Claim 与具体 Sandbox 解耦。

它不是 Prompt 安全产品，也不替代 NetworkPolicy、RuntimeClass、Secret 管理和工具授权。

## 四、隔离等级怎么选

| 风险 | 建议隔离 |
| --- | --- |
| 只调用受控 API，不执行代码 | 普通受限 Pod 可作为起点 |
| 执行用户脚本或第三方依赖 | 独立 ServiceAccount、默认拒绝网络、只读根文件系统 |
| 执行不可信仓库或生成代码 | gVisor/Kata 等沙箱 RuntimeClass，独立节点池可选 |
| 强对抗、多租户代码执行 | 微虚机/VM、独立网络和更强硬件边界 |

Kubernetes 官方说明沙箱 Pod 没有统一安全 API 定义，隔离效果取决于具体运行时；gVisor、Kata 等只能增强内核边界，不能替代最小权限。参考：[Pod Security Standards - Sandboxed Pods](https://kubernetes.io/docs/concepts/security/pod-security-standards/)

## 五、工作区生命周期

把数据分为：

- 只读输入快照；
- Agent 可写工作区；
- 结构化会话状态；
- 需要提交审核的输出；
- 临时缓存；
- 审计证据。

设计要回答：

- Sandbox 删除后哪些内容保留；
- 恢复是否回到同一模型/工具版本；
- 工作区是否可能包含 Token 或下载的恶意文件；
- 输出如何扫描后再进入可信 Git/Registry；
- 不同用户是否可能挂载同一个卷；
- 自动清理是否满足保留与合规要求。

## 六、工具权限必须逐项建模

对每个工具定义：

- 允许的操作和资源范围；
- 只读或可写；
- 参数 Schema 和最大大小；
- 超时、重试和幂等性；
- 单会话/用户调用预算；
- 是否需要人工批准；
- 返回内容是否会再次进入模型上下文；
- 审计字段和脱敏规则。

“可以执行 Shell”不是一个可接受的细粒度权限模型。

## 七、短期身份与 Tool Gateway

推荐 Agent 只持有自己的 Kubernetes 身份，由 Tool Gateway：

1. 验证 Sandbox、用户和会话；
2. 检查本次工具调用策略；
3. 交换短期下游凭证；
4. 约束资源范围和操作；
5. 记录审批、参数摘要和结果；
6. 调用结束后让凭证失效。

即使 Agent 工作区泄露，也不应暴露长期生产密钥。

## 八、网络策略

默认拒绝出站，然后按工具代理开放：

- DNS 仅允许受控 Resolver；
- Git 通过内部代理或允许列表；
- 浏览器访问经过 URL 过滤和下载扫描；
- 禁止访问云元数据地址、节点和 Kubernetes API；
- 数据库不直接暴露给 Sandbox；
- 对公网出站设置带宽、连接数和请求预算；
- 将工具响应视作不可信输入。

只按域名允许访问可能被重定向、DNS 或用户内容绕过，需要代理层检查最终目标。

## 九、Prompt Injection 的平台视角

Prompt Injection 不能只靠一段系统提示解决。平台控制包括：

- 不可信内容与系统指令分离；
- 工具权限不由模型自行扩大；
- 高风险写操作需要策略或人工审批；
- 工具返回值不能修改控制面策略；
- 外部仓库中的配置文件视为不可信；
- 执行结果进入可信流水线前重新验证；
- 关键业务动作使用确定性服务端校验。

模型可以提出动作，授权系统决定动作是否允许。

## 十、资源与成本保护

Agent 可能无限循环调用模型和工具。需要：

- 每会话最大 Token、时间和金额；
- 最大并发工具调用；
- Sandbox CPU、内存、GPU 和临时存储限制；
- 空闲暂停与最大存活时间；
- Warm Pool 上限；
- 下载和日志容量限制；
- 检测重复计划或无进展循环；
- 超预算后的安全终止与状态保存。

## 十一、可观测与审计

建议记录事件链而非完整思维过程：

```text
session created
→ sandbox assigned
→ model invocation metadata
→ tool requested
→ policy decision / approval
→ tool result metadata
→ artifact produced
→ sandbox suspended/deleted
```

指标包括：

- Sandbox 创建 P50/P95 和失败率；
- Warm Pool 命中；
- 每会话 Token、工具调用和成本；
- 策略拒绝与审批等待；
- Agent 完成率、超时率、循环终止率；
- 工作区容量和清理延迟；
- 运行时隔离异常。

日志不要默认保存完整 Prompt、用户代码、工具凭证和敏感返回内容。

## 十二、发布和回收

Agent 产出的代码、配置或镜像不能直接进入生产：

- 在隔离环境构建；
- 执行测试、Lint、Secret 与漏洞扫描；
- 生成可审查 Diff；
- 人工或策略审批；
- 用可信 CI 身份重新构建和签名；
- 通过标准 GitOps/发布流水线部署。

Agent 的 Sandbox 身份不应同时拥有生产发布权限。

## 十三、上线清单

- [ ] 明确 Agent 与普通服务不同的状态和权限模型；
- [ ] 执行环境、Agent 控制面和 Tool Gateway 分离；
- [ ] 不可信代码使用适当 RuntimeClass 或更强隔离；
- [ ] 每个 Sandbox 使用独立最小权限身份；
- [ ] 默认拒绝网络，所有工具访问经过受控代理；
- [ ] 工具权限有参数 Schema、预算、审计和审批；
- [ ] Prompt Injection 不能扩大平台授权；
- [ ] 会话 Token、时间、成本和存储都有硬上限；
- [ ] 工作区保留和清理策略明确；
- [ ] Agent 产物必须经过可信 CI 才能发布；
- [ ] 审计记录动作链且不泄露敏感内容。

## 延伸阅读

- [Agent Sandbox](https://agent-sandbox.sigs.k8s.io/)
- [Agent Sandbox Documentation](https://agent-sandbox.sigs.k8s.io/docs/)
- [Kubernetes Pod Security Standards](https://kubernetes.io/docs/concepts/security/pod-security-standards/)
- [Kubernetes RuntimeClass](https://kubernetes.io/docs/concepts/containers/runtime-class/)
