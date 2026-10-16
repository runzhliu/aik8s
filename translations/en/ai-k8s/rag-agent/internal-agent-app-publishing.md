---
title: "How Enterprise Internal AI Applications Can Be Quickly Published and Shared"
description: "Design of AI application building, pilot testing, approval, publishing, permissions, and runtime for non-R&D users such as business, legal, and operations teams"
status: evolving
last_reviewed: 2026-08-12
---

# How Enterprise Internal AI Applications Can Be Quickly Published and Shared

After business, legal, operations, and functional teams finish building a contract review, knowledge Q&A, or report generation application, they usually want to quickly make it available to other departments. If the platform requires them to prepare a Dockerfile, write Kubernetes YAML, or understand Serverless, the publishing path has already been designed incorrectly.

What business users should publish is a **governed internal application**, not a container. The ideal experience is similar to publishing an online form: choose a template, configure data and permissions, invite a small group of users for pilot testing, then publish to the company application center with one click. Containers, Serverless, workflows, and resident Agents are all implementation details of the platform.

This article presents a set of product processes, runtime architecture, and governance boundaries suitable for enterprise internal AI applications. If you are currently evaluating whether OpenClaw itself can serve as the enterprise runtime, first read [OpenClaw as an Enterprise Agent Platform Foundation](openclaw-enterprise-agent-platform.md); for scenarios involving code, Shell, or browser execution, see [Agent Sandbox Selection and Architecture Analysis](agent-sandbox-selection.md).

## 1. First Distinguish Between "Building an Application" and "Deploying a Service"

Business applications are mostly composed of the following:

```text
页面或对话入口
+ Prompt 与输出格式
+ 知识库和业务数据
+ 工作流与人工审批节点
+ 已批准的工具和连接器
+ 用户、部门和数据权限
```

These configurations can run on a shared multi-tenant application engine, without needing to build an image and start a Pod for every knowledge assistant created.

Only when the following requirements arise should the platform switch to an independent runtime instance:

- Uploading custom code or special Python or Node.js dependencies;
- Requiring long-running tasks, event consumption, or independent scaling policies;
- Requiring long-lived connections such as Feishu, WeCom, or Slack;
- Requiring persistent memory, independent workspaces, or local state;
- Using browser, Shell, or code execution environments;
- Handling highly sensitive data that requires stronger isolation;
- Resource, availability, or change cycles that differ significantly from the shared platform.

Therefore, enterprise platforms typically need two product layers, rather than routing all applications through the same deployment path:

| Product Layer | Primary Users | What Users Submit | Typical Runtime |
| --- | --- | --- | --- |
| Standard AI Applications | Business, legal, operations | Prompts, knowledge bases, forms, workflows, connectors, and permissions | Shared application runtime |
| Advanced Custom Applications | Development, data, and platform teams | Code, images, dependencies, and runtime parameters | Independent Serverless, Worker, or Agent Cell |

## 2. Public Cases: Which Organizations Used What

Public cases already reveal three different routes, but the depth of disclosure varies significantly: some only publish product names and application counts, while others disclose identity, knowledge bases, workflows, and runtime frameworks. The table below only lists cases where the organization name and first-hand public sources can be found; GitHub Stars, anonymous interviews, or product demos are not used as substitutes for enterprise adoption evidence.

| Organization | Business and Publishing Approach | Public Product or Framework | Public Results | What It Demonstrates |
| --- | --- | --- | --- | --- |
| BBVA | Employees create Custom GPTs themselves and share them internally within the bank | ChatGPT Enterprise, Custom GPTs | Over 20,000 GPTs created, approximately 4,000 used regularly | Large-scale "employee-created, internally reused" can be built directly on a managed workbench; the underlying deployment architecture is not disclosed |
| Moderna | Functional teams create GPTs, including contract summarization, policy Q&A, and clinical data analysis | ChatGPT Enterprise, Custom GPTs; early `mChat` used the OpenAI API | 750 GPTs created within two months of launching ChatGPT Enterprise | Legal and functional scenarios can start with configuration-based applications without deploying a separate service for each application |
| Kakaku.com | Employees create and publish internal AI applications through a visual platform | Dify Enterprise | Nearly 950 internal applications, 75% of employees registered to use Dify; a product data extraction application went live in about 3 hours | Open-source ecosystem low-code AI application platforms can also support internal self-service creation; data comes from the Dify customer case study |
| HEINEKEN | Employees use PowerBot via Teams or Web; there is also a legal application that checks whether marketing claims comply with company policy | Microsoft Copilot Studio, Power Platform, Azure OpenAI; Teams and custom Web entry points | The public case study describes legal, internal assistant, and external customer service applications | The Microsoft ecosystem can combine low-code Agents, office entry points, and reusable Skills |
| Coca-Cola Andina | HR assistant returns personalized policies based on employee profiles, serves employees via WhatsApp, and can create HR tickets | Copilot Studio, Entra ID, SharePoint, Power Automate, Power Apps, Direct Line API | Over 300 active users, with plans to expand scope | This is a relatively complete "identity—data—workflow—channel" reference, not just a chatbot |
| Lyft | Operations, voice of customer, and product staff define customer service Agents using prompts and configuration; the engineering platform assembles them at runtime | LangGraph, LangSmith, internal JSON configuration service, Prompt Hub | Shifted from each Agent requiring months of engineering effort to domain experts iterating self-service | Building an in-house platform does not mean having business users write LangGraph; the engineering team owns the skeleton, and domain experts modify governed configuration |
| Uber | Internal teams compose, deploy, and run production Agents; existing microservices provide tools via MCP, and the platform adds Agent identity and call attribution | Internal Agent Platform, MCP, internal workload identity system; the public article does not name the orchestration framework | The public focus is on identity, delegation, and auditing in large-scale tool calls | The challenge of enterprise Agent platforms shifts from "calling models" to Agent identity, authorization chains, and accountability |
| Sanofi | Built a proprietary unified employee AI assistant called Concierge rather than purchasing an off-the-shelf chat frontend; runs across regions and gradually adds Agent capabilities | Amazon Bedrock, multi-region AWS architecture; publicly plans to introduce Bedrock AgentCore | 72,000 monthly active users; internal employees continuously discover and build new use cases | Large enterprises often retain their own product and control plane, using cloud vendors for model and Agent infrastructure |
| Cox Automotive | Delivers multiple business Agents using a standard Agent runtime environment and reusable patterns | Amazon Bedrock, Bedrock AgentCore Runtime, Strands Agents | 17 major Agent solutions reached production | A managed Agent Runtime can reduce duplicated effort in deployment, monitoring, error handling, and security templates |

Sources: [BBVA](https://openai.com/index/bbva-2025/), [Moderna](https://openai.com/index/moderna/), [Kakaku.com](https://dify.ai/zh/blog/kakaku-accelerates-ai-adoption-with-dify-fast-secure-and-scalable), [HEINEKEN](https://www.microsoft.com/en/customers/story/25909-heineken-microsoft-copilot-studio), [Coca-Cola Andina](https://www.microsoft.com/en/customers/story/26256-coca-cola-andina-microsoft-copilot-studio), [Lyft](https://www.langchain.com/blog/lyft-built-a-self-serve-ai-agent-platform-for-customer-support-with-langgraph-and-langsmith), [Uber](https://www.uber.com/in/en/blog/solving-the-agent-identity-crisis/), [Sanofi](https://aws.amazon.com/solutions/case-studies/sanofi-bedrock-case-study/), [Cox Automotive](https://aws.amazon.com/solutions/case-studies/cox-auto-case-study/).

### 2.1 How to Interpret These Cases

These cases cannot simply be aggregated into "framework X is best," because they solve different problems:

```text
配置一个知识和 Prompt 助手
  → Custom GPTs / Microsoft 365 Agent Builder

搭建部门工作流并接入办公系统
  → Copilot Studio / Power Platform / Dify

实现复杂、长状态、可评测的专业 Agent
  → LangGraph 等编排框架 + 企业自建发布控制面

统一承载大量生产 Agent
  → Bedrock AgentCore 等托管 Runtime，或 Kubernetes 自建 Runtime
```

Custom GPT, Copilot Studio, and Dify are themselves application workbenches oriented toward creators; LangGraph, Strands Agents, and OpenClaw are closer to development frameworks or Agent Runtimes. Directly comparing them confuses product layers. Business users can publish directly in the former, but when using the latter, enterprises typically still need to build their own forms, permissions, approvals, application catalogs, evaluation, and lifecycle control planes.

### 2.2 Limitations of Case Evidence

- Most sources in the table above are vendor-published customer stories, suitable for confirming "who publicly uses what," but not equivalent to independent audits;
- Application counts do not equal active application counts, nor do they prove that every application accesses sensitive data or performs high-risk operations;
- Vendor case studies often do not disclose cost, failure rates, security incidents, tenant models, or the underlying Kubernetes architecture;
- Uber and Lyft represent platform- or engineering-team-led self-service, not legal staff directly publishing arbitrary code;
- As of this article's review date, no publicly disclosed, verifiable case has been found of a large organization using OpenClaw to complete "business users building and publishing applications company-wide." OpenClaw can serve as a channel and runtime option, but community popularity alone cannot be used to infer that this enterprise scenario has matured.

### 2.3 Product Conclusions from Public Cases

1. **Provide a shared creation workbench first.** The scale at BBVA, Moderna, and Kakaku.com comes from employees configuring and reusing applications, not from standing up a Kubernetes service for each application.
2. **The office ecosystem determines the shortest path.** For organizations already deeply using Microsoft 365, SharePoint, Entra ID, and Teams, the Copilot Studio route is usually the shortest; teams that want self-hosting and multi-model support are more likely to evaluate Dify.
3. **Domain experts and platform engineers still have a clear division of labor.** Lyft lets operations staff maintain prompts and configuration, but the LangGraph skeleton, state, security checks, and observability remain the responsibility of the engineering platform.
4. **As scale grows, identity becomes harder than the model framework.** Coca-Cola Andina's user identity passthrough and Uber's Agent identity system both show that a production platform must answer "acting as whom, on behalf of whom, and with what callable scope."
5. **Large enterprises often retain their own control plane.** Sanofi and Uber did not hand the enterprise entry point, permissions, and governance entirely to an Agent SDK; instead, they placed model services or orchestration frameworks beneath their own platform.

## 3. The Publishing Process as Seen by Business Users

The recommended complete process is designed as:

```text
选择模板
  → 配置内容、数据与工具
  → 小范围试运行
  → 选择可见范围
  → 自动风险检查
  → 必要时审批
  → 发布到内部应用中心
  → 持续评测、反馈与回收
```

### 3.1 Choosing a Template

The first version of the platform does not need to offer unlimited freedom; it can start by covering high-frequency scenarios:

- Enterprise knowledge Q&A;
- Document summarization and information extraction;
- Contract clause comparison and initial review;
- Report, email, and proposal generation;
- Information collection, process routing, and human approval;
- Read-only internal data queries;
- Feishu, WeCom, or Slack bots.

When creating an application, only business information is required, for example:

```text
名称：销售合同初审助手
用途：识别付款、违约和知识产权等风险条款
负责人：法务部合同组
预期用户：销售一部、销售二部
数据级别：内部敏感
```

The application owner cannot be an optional field. The platform will later rely on the owner to handle permission reviews, user feedback, incident response, and decommissioning handover.

### 3.2 Configuring Data and Capabilities

Business users can upload policies, templates, and review rules, or select data sources and connectors already registered on the platform. Connectors should be expressed as business capabilities, not raw keys or arbitrary API endpoints:

| Connector | Recommended Permission |
| --- | --- |
| Legal public clause library | Read-only |
| Contract system | Read contracts the current user is authorized to access |
| CRM | Read necessary basic customer information |
| Email or group messaging | Generate drafts; require human confirmation before sending |
| Contract status modification | Disabled by default; requires separate application |

Users should not paste personal API Keys into prompts, configuration files, or knowledge bases. The platform should issue an independent identity for each application and obtain short-lived credentials through a Secret service or Tool Gateway.

### 3.3 Small-Scale Pilot Testing

The application first enters a draft or test environment, accessible only to the creator and invited testers. The test page should provide at least:

- A set of savable representative inputs and expected results;
- Version records for prompts, knowledge bases, models, and tools;
- Checks for sensitive information, privilege escalation queries, and Prompt Injection;
- Degradation behavior for no-answer, model timeout, and tool failure scenarios;
- Response time, Token, and cost estimates;
- Thumbs up/down, corrections, and issue categorization;
- Automated regression testing after modifications.

For example, a contract application can maintain a set of desensitized standard contracts. After changing the model, prompt, knowledge base, or tool permissions, the platform re-runs the tests to avoid "adjusting one line in a prompt causing old scenarios to break."

### 3.4 Choosing the Access Scope

The publishing interface should not offer only public and private options. The following is recommended:

| Scope | Example | Recommended Process |
| --- | --- | --- |
| Self only | Personal draft assistant | No approval |
| Designated individuals or project groups | A specific M&A project | Owner confirmation |
| Designated department | Sales department contract assistant | Data owner confirmation |
| Company-wide internal | Company-wide policy Q&A | Automatic checks, approval if necessary |
| Public internet | External customer service | Separate external publishing process |

The access scope should be bound to the company's IdP, directory, and security groups, avoiding a manually maintained list that easily becomes stale. When users change roles or leave the company, permissions change automatically with organizational relationships.

### 3.5 Risk Classification and Approval

Approval should be risk-based, not a one-size-fits-all process for every application:

| Risk Level | Example | Publishing Policy |
| --- | --- | --- |
| Low | Public policy Q&A, no sensitive data, read-only | Auto-publish |
| Medium | Department data, contract documents, CRM queries | Application or data owner approval |
| High | External sending, modifying business systems, affecting customer rights | Security, legal, or business owner approval; mandatory human confirmation |
| Prohibited | Automatic contract signing, automatic payment, bypassing existing authorization | Reject publishing or require redesign |

The platform should automate as much as possible: data source checks, permission differences, sensitive information scanning, dependency scanning, budget estimation, and regression testing, leaving only items requiring judgment to human approval. Overly heavy approval processes will push users toward ungoverned personal scripts and external tools.

### 3.6 Publishing Results

A successful publish should not merely mean "the Pod is running"; it should return an application page that employees can understand and share:

```text
销售合同初审助手

用途：辅助识别常见合同风险，不代替正式法律意见
负责人：法务部合同组
适用范围：销售一部、销售二部
数据保留：任务完成 7 天后删除
版本：v1.3

[立即使用] [申请权限] [使用说明] [反馈问题]
```

The platform automatically completes in the background:

- Company SSO and user identity recognition;
- Authorization for user groups, departments, and application roles;
- Internal domain, TLS, and ingress routing;
- Independent application identity, Secrets, and tool permissions;
- Logs, traces, audit, and cost attribution;
- Concurrency, Token, time, and monthly budget limits;
- Version saving, canary deployment, rollback, and decommissioning;
- Listing in the internal application marketplace or collaboration tools.

## 4. Application Access Rights Do Not Equal Data Access Rights

This is the area where internal AI applications most often go wrong. The fact that an employee can open a contract assistant does not mean they can read all contracts through the assistant. The platform must handle these separately:

```text
能否打开应用？
        │
        └── 打开以后，能查看或修改哪些业务数据？
```

### 4.1 User Identity Passthrough

The application accesses business systems as the currently logged-in user:

```text
李四只能查看华东区合同
→ 通过助手查询时仍然只能看到华东区合同
```

This is the preferred mode for internal search, data queries, and personal work assistants. AI applications should not become a "universal query account" that bypasses the original system's row-level, field-level, and organizational-level permissions.

### 4.2 Application Identity

Applications can also use an independent service identity to access clearly defined shared resources, such as a read-only legal public clause library. This identity must have least privilege, resource scope, call budgets, and validity periods, and must not inherit the creator's personal credentials.

### 4.3 Tool Gateway

For high-risk scenarios, all business operations can be routed through a Tool Gateway:

1. Verify the user, application, session, and target resource;
2. Determine whether this call is permitted based on policy;
3. Trigger human confirmation when necessary;
4. Exchange short-lived downstream credentials;
5. Validate parameters and execute the operation;
6. Record desensitized audit events.

The model can propose actions, but final authorization must be determined by deterministic server-side policy.

## 5. Unified Publishing Surface, Multiple Runtimes Underneath

"One-click publishing" does not mean there is only one runtime underneath. The platform can automatically select based on triggers, state, and execution duration:

| Runtime Mode | Applicable Use Cases | Kubernetes Implementation |
| --- | --- | --- |
| Shared Application Runtime | Standard Q&A, document processing, and form workflows | Multi-tenant application service |
| Request Service | Webhooks, conversational APIs, short-lived tool calls | Knative Serving or standard Deployment |
| Event Worker | Message consumption, file processing, and background tasks | Deployment + KEDA |
| Scheduled / Durable Workflow | Scheduled reports, long-running processes, and human approvals | CronJob + durable workflow engine |
| Resident Agent | Long-lived connections, persistent memory, and dedicated workspaces | Resident Deployment or dedicated Agent Cell |

Knative Serving can auto-scale based on request concurrency and scale to zero when there is no traffic, making it suitable for stateless HTTP applications; services sensitive to cold starts can set a minimum replica count. Reference: [Knative Autoscaling](https://knative.dev/docs/serving/autoscaling/). KEDA is suitable for scaling Workers based on event sources and queue backlog, and its HTTP Add-on also supports scaling HTTP workloads from zero. Reference: [KEDA HTTP Add-on](https://keda.sh/http-add-on/0.15/).

Agents with long-lived connections, persistent local state, and the need to respond at any time should not be forcibly scaled to zero for the sake of a "Serverless" label. OpenClaw's Gateway is a resident process that holds channel connections, sessions, and the control plane; mutually untrusted tenants also cannot be isolated using only session IDs within the same Gateway. Reference: [OpenClaw Gateway](https://docs.openclaw.ai/network), [OpenClaw Multi-Tenant Hosting](https://docs.openclaw.ai/gateway/multi-tenant-hosting).

## 6. Recommended Platform Architecture

```text
业务用户 / 开发者
        │
        ▼
AI 应用工作台
├── 模板、知识库、工作流和连接器
├── 测试集、评测、权限范围和预算
└── 试运行、审批、发布和下线
        │
        ▼
应用发布控制面
├── App / Version / Owner / Environment
├── User / Group / Role / Data Policy
├── Risk / Approval / Quota / Audit
├── Runtime Selection / Rollout / Rollback
└── Catalog / Feedback / Lifecycle
        │
        ├── 共享应用运行时
        ├── Knative HTTP Service
        ├── KEDA Event Worker
        ├── Workflow / CronJob
        └── Resident Agent Cell
                │
        ┌───────┼──────────────┐
        ▼       ▼              ▼
    Model     Tool          Memory / Data
    Gateway   Gateway       Storage
```

The platform control plane should store an application declaration that is independent of the underlying implementation. For example:

```yaml
apiVersion: platform.example.io/v1alpha1
kind: AIApplication
metadata:
  name: contract-review
spec:
  owner: legal-contract-team
  runtime: auto
  audience:
    groups:
      - sales-east
      - sales-south
  triggers:
    - type: web
  dataClassification: internal-sensitive
  capabilities:
    models:
      - company/standard-llm
    tools:
      - contract.read-as-user
      - legal-clause-library.read
  scaling:
    idlePolicy: scale-to-zero
    maxInstances: 10
  retention:
    userContent: 7d
```

Business users do not need to edit YAML directly; it can be generated from a form or a conversational workbench. The value of the declaration lies in enabling the platform to audit, compare versions, enforce policies, and swap the underlying runtime.

## 7. The Internal Application Center Is More Than a Link List

The application catalog should at minimum display:

- Application purpose, scope of applicability, and clear capability boundaries;
- Owner, responsible department, and support channel;
- Data sources used, data classification level, and retention period;
- AI result explanations and scenarios requiring human review;
- Current version, last update time, and change history;
- Entry points for permission requests, feedback, corrections, and incident reporting;
- Service status and planned maintenance information.

Users without permission should not merely see `403`; the required user groups, data permissions, and application process can be displayed instead. Access addresses can also be synchronized to the corporate Wiki, Feishu Docs, Confluence, SharePoint, WeCom, or Teams, but the documentation is only an introduction and entry point—identity, authorization, data access, and execution are still controlled by the application platform.

Publishing to the internet is a different security boundary and should not reuse the expedited "internal company-wide" process. External applications require at minimum independent identity and data sources, anti-abuse measures for anonymous access, input/output security checks, rate limiting and cost caps, privacy notices, as well as security, legal, and brand approvals.

## 8. Lifecycle Governance

Applications continue to change after release. The platform needs to handle:

- Automatic transfer when the owner leaves or changes roles;
- Re-review after changes to data sources, tool permissions, models, or publishing scope;
- Regression testing after updates to prompts, knowledge bases, and models;
- Reminders and archiving for low-usage or long-unmaintained applications;
- Periodic permission and data reviews for high-risk applications;
- Rapid rollback of old versions and one-click deactivation for major issues;
- Separate retention periods for sessions, uploaded files, logs, and audit records;
- Cost attribution by application, department, model, and tool.

Kubernetes Namespaces can carry part of the isolation and quota, but they are not a complete tenant boundary by themselves; RBAC, NetworkPolicy, ResourceQuota, and a sandbox runtime for high-risk code execution are also needed. Reference: [Kubernetes Multi-tenancy](https://kubernetes.io/docs/concepts/security/multi-tenancy/).

## 9. How to Build the First Version of the Platform

For the first version, it is recommended to limit scope and not open arbitrary code execution, prioritizing:

1. Knowledge Q&A, document review, report generation, forms, and human approval templates;
2. Company SSO, department groups, application roles, and user identity passthrough;
3. Approved read-only data connectors;
4. Three basic environment states: draft, test, and release with rollback;
5. Risk classification, automated checks, and a small amount of human approval;
6. Internal web addresses, as well as Feishu, WeCom, or Teams entry points;
7. Application owner, budget, logs, feedback, and deactivation mechanisms.

The release page can ask business users only four core questions:

```text
谁可以使用？
使用哪些数据？
能够执行哪些操作？
谁对这个应用负责？
```

The second phase can add custom code, asynchronous Workers, durable workflows, resident Agent Cells, canary releases, and stronger sandboxing. This validates real business needs first and avoids bearing the full risk of arbitrary code, multi-tenant execution, and complex runtimes early in the platform's life.

## 10. Launch Checklist

- [ ] Business users do not need to understand images, Kubernetes, or Serverless;
- [ ] Standard configuration-based applications and custom-code applications use different release paths;
- [ ] Every application has an owner, usage scope, data classification level, and cost budget;
- [ ] Draft and test applications cannot be discovered or accessed company-wide;
- [ ] Application permissions and business data permissions are validated separately;
- [ ] User identity passthrough is preferred, and application identity follows least privilege;
- [ ] High-risk tool calls have parameter validation, auditing, and human confirmation;
- [ ] Approvals are graded by risk, and low-risk applications can be released automatically;
- [ ] The platform selects shared runtime, Serverless, Worker, workflow, or Agent Cell based on the workload;
- [ ] Prompt, knowledge base, model, and tool changes are traceable and trigger regression testing;
- [ ] The application catalog provides permission requests, feedback, owner information, and decommissioning details;
- [ ] Owner changes, long-term idleness, and permission reviews all have automated processes.

## Further Reading

- [OpenClaw as the Foundation for Enterprise Agent Platforms](openclaw-enterprise-agent-platform.md)
- [Agent Sandbox Selection and Architecture Analysis](agent-sandbox-selection.md)
- [AI Agents, Sandboxes, and Tool Execution](../agentic-workloads.md)
- [AI Platform Security and Governance](../security-governance.md)
- [Knative Serving Autoscaling](https://knative.dev/docs/serving/autoscaling/)
- [KEDA HTTP Add-on](https://keda.sh/http-add-on/0.15/)
- [Kubernetes Multi-tenancy](https://kubernetes.io/docs/concepts/security/multi-tenancy/)
