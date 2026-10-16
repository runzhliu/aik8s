---
title: "Understanding the Enterprise Agent Technology Stack through WorkBuddy"
description: "From Tencent WorkBuddy's Agent, Runtime, Session, Skill, MCP, and evaluation capabilities, deconstruct the complete enterprise Agent technology stack from model to sandbox, identity, observability, and delivery"
status: evolving
last_reviewed: 2026-08-13
---

# Understanding the Enterprise Agent Technology Stack through WorkBuddy: Choosing the Model Is Not the Hard Part

> Research date: 2026-08-13. This article discusses Tencent WorkBuddy and WorkBuddy Enterprise. Commercial products do not publish complete source code; descriptions of WorkBuddy in this article use only official public materials. The subsequent "enterprise self-built technology stack" is an architecture mapping based on public capabilities and does not represent Tencent's internal implementation.

When many enterprises build their first Agent, discussions usually start with three questions: which model to use, whether to choose LangGraph or another framework, and whether to build multi-Agent.

Once actually in production, the questions quickly become a different set: Under whose identity does the Agent access business systems? Where does the code execute? Can long-running tasks resume after interruption? Does effect regress after model upgrades? Can one connector expose only three read-only tools? Which department should the cost be charged to? How do you reconstruct every step of a call when something goes wrong?

WorkBuddy is worth studying not just because it can generate documents, spreadsheets, and code, but because its publicly documented enterprise product concepts already cover **Agent, Runtime, Session, Manifest, Skill, MCP, Connector, Credential, Trace, and Evaluation**. Put together, these concepts form exactly the skeleton that an enterprise Agent platform should have.

![Mapping enterprise Agent platform from WorkBuddy public capabilities](../../assets/rag-agent/workbuddy-enterprise-agent-stack/01-workbuddy-map.png)

## 1. What WorkBuddy Actually Is

WorkBuddy's personal edition is more like an Agent desktop for knowledge work: users state goals in natural language, the Agent autonomously breaks down steps, reads authorized local files, calls tools, and delivers verifiable artifacts such as documents, spreadsheets, presentations, charts, or code. It also provides both work mode and development mode, and can trigger tasks remotely through messaging channels.

The enterprise edition further decomposes personal capabilities into manageable objects:

| Public Concept | Problem It Solves | Position in the Enterprise Platform |
| --- | --- | --- |
| Agent | Which model to use, what role to play, what capabilities to have | Versionable Agent definition |
| Manifest | Declares identity, capabilities, workspace, and runtime configuration | Declarative deliverable of the Agent |
| Runtime | The Linux file system, terminal, and sandbox where the Agent actually runs | Isolated execution environment |
| Session | Independently maintains the history and context of one user task | Session state and execution state |
| Skill | Encapsulates methods, scripts, and domain experience into capabilities | Reusable, evaluable capability package |
| Expert/Expert Team | Combines capabilities with experience and enables multiple roles to collaborate | Role templates and multi-Agent workflows |
| MCP/Connector | Securely accesses external systems such as GitHub, documents, and email | Tool Gateway and authorization proxy |
| Trace/Evaluation | Reconstructs execution chains, measures effect against datasets | Observability and quality engineering |

WorkBuddy's official distinction between Skill, Expert, and Expert Team is also very instructive: Skill is "capability," Expert is "capability plus experience," and Expert Team is "multiple experts plus collaboration process." This is easier to govern than calling everything an Agent, because the platform can separately manage tool capabilities, role methods, and collaboration topology.

WorkBuddy Managed Agents' public documentation also defines the runtime surface quite concretely: a Runtime includes a cloud sandbox, Manifest, and one or more Sessions, and provides data persistence, cross-node recovery, fast cloning, port forwarding, warm pools, auto-sleep, and resume capabilities. What deserves the most attention here is not a specific product name, but a fact: **as long as an Agent can operate files, terminals, and external systems, the Runtime becomes infrastructure as important as the model.**

Official materials: [WorkBuddy Product Overview](https://cloud.tencent.com/product/workbuddy), [WorkBuddy Enterprise Quick Start](https://cloud.tencent.com/document/product/1831/134527), [WorkBuddy Managed Agents](https://cloud.tencent.com/document/product/1831/134407).

## 2. What Can and Cannot Be Inferred from Public Capabilities

What can be confirmed is that WorkBuddy externally provides the following product capabilities:

- Multi-model selection and Agent System Prompt;
- Assembly of Skills, Experts, MCP, and Connectors;
- Task execution in local files and cloud sandboxes;
- Runtime and Session lifecycle;
- Enterprise channel integration, credential management, and connector gateway;
- Full-chain Trace, test runs, and dataset evaluation;
- Two interaction modes: default permissions and full access, with high-risk actions requiring confirmation;
- Enterprise-exclusive VPC, tenant isolation, enterprise plugins, and other delivery options.

What cannot be asserted from this is which open-source orchestration framework, database, vector store, container runtime, or workflow engine it internally must use. The fact that a commercial product's concepts resemble an open-source project does not prove the underlying implementation is that project.

Therefore, the following does not attempt to "reverse-engineer WorkBuddy's source code," but instead uses the product objects it exposes to answer a more practical question: if an enterprise builds similar capabilities itself, how should the technology stack be layered?

## 3. The Ten-Layer Enterprise Agent Technology Stack

![Enterprise Agent production technology stack](../../assets/rag-agent/workbuddy-enterprise-agent-stack/02-enterprise-stack.png)

### 3.1 Entry and Delivery Layer

An Agent should not exist only in a chat webpage. Enterprises typically need simultaneous integration with Web, desktop clients, WeCom, Feishu, DingTalk, Slack, APIs, event triggers, and scheduled tasks.

This layer also manages final artifacts: documents, spreadsheets, code repositories, tickets, approval records, and object storage files. Enterprise users ultimately accept results, not how many sentences the model spoke.

Optional technologies include self-built Web/IM bots, application workbenches such as Dify/Coze Studio, and existing enterprise portals and API Gateways.

### 3.2 Agent Definition and Control Plane

Production Agents need a declarative definition similar to a Manifest, including at minimum:

```yaml
name: contract-reviewer
version: 1.4.2
model_policy: legal-balanced
system_prompt_ref: prompts/contract-reviewer@sha256:...
skills:
  - contract-clause-check@2.1.0
tools:
  - contract.read
  - policy.search
workspace: persistent
approval_policy: external_write_requires_human
budgets:
  max_tokens: 200000
  max_runtime: 30m
```

This layer manages the Agent Catalog, versions, owners, target audiences, model policies, Skills, tools, budgets, publishing, canary releases, and rollbacks. The Prompt is just one field and should not become an untraceable string scattered across code and databases.

### 3.3 Model Service and Gateway

Enterprises typically do not let every Agent directly store a model vendor API Key. A more reasonable path is to route uniformly through a Model Gateway:

```text
Agent → Model Gateway → 云端模型 / 私有模型 / 多模态模型
```

The gateway is responsible for unified authentication, model aliases, routing, rate limiting, retries, degradation, token accounting, semantic caching, and cost attribution. Private models can be served by vLLM, SGLang, or TensorRT-LLM; multi-provider entry points can be evaluated against LiteLLM, Higress AI Gateway, Envoy AI Gateway, or cloud vendor gateways.

Model selection should be driven by task routing rather than the whole company choosing a single model: fast classification, long-document understanding, complex reasoning, vision, code, and low-cost batch processing often suit different models. Models must also be rollback-capable; otherwise, upstream rate limiting directly becomes full-site Agent unavailability.

### 3.4 Agent Harness and Orchestration

The Harness is the loop that "keeps the model doing things," responsible for:

- Organizing context and system constraints;
- Letting the model select tools and read results;
- Maintaining plans, steps, stop conditions, and error recovery;
- Pausing to wait for human approval;
- Delegating subtasks to other Agents or deterministic services.

Common choices include LangGraph, OpenAI Agents SDK, Google ADK, Microsoft Agent Framework, CrewAI, and self-built state machines. Framework selection mainly comes down to four things: whether state is explicit, whether pause/resume is supported, whether tools and models are replaceable, and whether execution traces are easy to observe.

A more stable production combination is typically:

```text
模型负责理解、选择和异常处理
+ 状态图负责允许的路径
+ 普通代码负责交易和不可逆动作
```

Multi-Agent is not a default layer. Only when tasks can be clearly divided, independently verified after parallel execution, or genuinely require context isolation, is it worth bearing the extra Token, latency, and error propagation costs.

### 3.5 Tool, Skill, and Connector Gateway

Skill solves "how to do it," Tool solves "what can be done," and Connector solves "which system to connect to under what identity." The three should not be mixed into a single Prompt.

MCP can standardize tool discovery and invocation, but **MCP itself is not an enterprise authorization system**. Production connectors additionally require:

- OAuth 2.1, user-delegated identity, or workload identity;
- Tool-level and parameter-level allowlists;
- Short-lived credentials and Secret rotation;
- Timeouts, retries, circuit breakers, rate and cost limits;
- Read/write classification and high-risk operation approval;
- Audit of caller, Agent, tool, parameter summary, and result status.

WorkBuddy's public connector design already includes authentication credentials, MCP Server, tool filtering, timeouts, and request headers, with access proxied through a unified gateway. This is exactly the responsibility an enterprise Tool Gateway should bear. The [WorkBuddy Connector documentation](https://cloud.tencent.com/document/product/1831/134453) also explicitly emphasizes independent authorization, least privilege, and tool filtering.

For remote MCP, authorization should follow the MCP OAuth specification and audience binding; received Tokens must not be passed through verbatim to downstream services. Reference: [MCP Authorization](https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization).

### 3.6 Knowledge, Context, and Memory

Enterprises often treat "buying a vector database" as completing RAG and memory. In reality, state needs to be decomposed into four categories:

| State | Typical Content | Recommended Carrier |
| --- | --- | --- |
| Session context | Current conversation and recent tool results | PostgreSQL/Redis/Checkpoint Store |
| Task workspace | Uploaded files, intermediate files, and final artifacts | Object storage, PVC, cloud disk, or sandbox file system |
| Enterprise knowledge | Policies, contracts, code, and business records | Search engine, vector store, data warehouse, knowledge service |
| Long-term memory | User preferences, confirmed facts, and historical experience | Structured Memory Store, with write policies and expiration mechanisms |

Vector store options include pgvector, Milvus, OpenSearch/Elasticsearch, and others, but retrieval quality also depends on permission filtering, document parsing, chunking, hybrid retrieval, reranking, citation, and update freshness. Long-term memory must allow viewing, correction, deletion, and expiration; not every model output should be automatically written as a "fact."

### 3.7 Runtime and Execution Sandbox

For read-only knowledge Q&A only, a shared application process is usually sufficient. Once an Agent needs to run code, install dependencies, operate a browser, or process untrusted files, an independent Runtime becomes necessary.

A usable Runtime includes at minimum:

- Isolated file system, processes, network, and identity;
- CPU, memory, disk, GPU, duration, and process count quotas;
- Temporary workspaces and persistent workspaces mounted only when needed;
- Network denied by default, with egress opened per domain or service;
- Image/template versioning, warm pools, and fast creation;
- Pause, resume, destroy, and artifact export;
- Malicious file, dependency, and output scanning.

A common implementation is Kubernetes Pods with NetworkPolicy, Seccomp, and read-only root file systems; for higher isolation requirements, use gVisor, Kata Containers, Firecracker, or standalone VMs. It must be noted: **a Pod is a scheduling and resource boundary, not automatically a hostile multi-tenant security boundary.**

### 3.8 Session, Durable Execution, and Queues

An Agent's Session cannot be just a chat history. Long-running tasks should save "conversation state" and "execution state" separately: the current step, tool-call idempotency keys, pending approvals, retry counts, budget consumption, and already-produced artifacts must all be recoverable.

LangGraph Checkpoint is suitable for saving state graph execution points; durable execution engines like Temporal suit workflows spanning hours or days, including timers and external callbacks; Kafka, Redis Streams, RabbitMQ, or cloud queues handle peak shaving and decoupling. The selection criterion is not popularity, but whether tasks require cross-process recovery, Exactly-once business semantics, and human waiting.

### 3.9 Observability and Evaluation

Traditional APM can only answer whether a request errored; Agents additionally need to answer:

- Why the model chose this tool;
- At which step it began to deviate from the goal;
- Whether it incorrectly retried after tool failure;
- Which model, Prompt, Skill, and knowledge version produced the result;
- What the total latency, first Token, Tokens, tool time, and cost were;
- Whether the business task actually completed, not just HTTP 200.

It is recommended to use OpenTelemetry to thread through entry points, models, retrieval, tools, workflows, and sandboxes, and to use Langfuse, LangSmith, Phoenix, or a self-built platform to display Agent Traces. OpenTelemetry already provides GenAI-related semantic attributes, but these conventions are still evolving; enterprises should retain their own version fields and data masking policies.

Evaluation should be layered at least three levels:

1. **Component evaluation**: retrieval recall, tool parameters, model format, and security classification;
2. **Trajectory evaluation**: whether steps are reasonable, whether there are redundant calls, whether permissions are respected;
3. **Business evaluation**: whether tickets were correctly closed, whether contract risks were recalled, whether reports were adopted by users.

Offline regression before release, online sampling and human feedback after release, and production failure trajectories fed back into datasets together form a continuous optimization loop.

### 3.10 Identity, Security, and Cost Governance

The most critical question for an enterprise Agent is not "what is it called," but:

```text
谁发起任务
→ 哪个 Agent 代表谁
→ 使用哪个 Runtime 身份
→ 允许调用哪些工具和数据
→ 哪些动作需要谁审批
→ 最终由谁承担费用和责任
```

Employee identity, Agent identity, Runtime workload identity, and third-party delegated credentials must be kept separate. Common infrastructure includes enterprise IdP/OIDC, Kubernetes ServiceAccount, SPIFFE/SPIRE, Vault/KMS, OPA/Cedar, and API Gateway. Shared admin accounts are the easiest way to get a Demo working, but they almost certainly become production governance debt.

Costs must also be attributed by user, department, Agent, model, task, and tool, with per-task Token, execution time, concurrency, daily/monthly budgets, and anomaly circuit breakers configured. An autonomous loop without budget boundaries is essentially a program that can automatically expand its own costs.

## 4. A Practical Open-Source Reference Stack

The following is not the only answer, but a set of combinations with relatively clear layering and easy replacement:

| Layer | Starting Choice | Additions at Scale |
| --- | --- | --- |
| Application entry | Self-built Web/IM Bot, Dify, or Coze Studio | API Gateway, application catalog, channel center |
| Agent orchestration | LangGraph, OpenAI Agents SDK, or Google ADK | Independent Control Plane, version and release system |
| Durable workflows | LangGraph Checkpoint + PostgreSQL | Temporal, event bus, task queue |
| Model entry | Cloud model API or single inference endpoint | LiteLLM/Higress/Envoy AI Gateway, multi-model routing |
| Private inference | vLLM or SGLang | AIBrix/KServe, elasticity, P/D and KV Cache |
| Tool connectivity | Function Calling, small amount of MCP | MCP/Tool Gateway, OAuth, parameter-level policies |
| Knowledge and memory | PostgreSQL + pgvector + object storage | OpenSearch/Milvus, permission-aware retrieval, Memory Service |
| Execution environment | Restricted Kubernetes Pod | gVisor/Kata/VM, warm pools, snapshots and recovery |
| Observability and evaluation | OpenTelemetry + Langfuse/Phoenix | Online evaluation, red teaming, quality gates, and cost attribution |
| Identity and credentials | OIDC + Secret Manager | SPIFFE, Vault/KMS, OPA/Cedar, short-lived credentials |
| Platform delivery | Docker + Kubernetes + GitOps | Multi-tenant Control Plane, quotas, audit, and disaster recovery |

Frameworks do not need to be fully selected at once. A read-only knowledge assistant may not need an independent Runtime at all; a development Agent that needs to run code should prioritize building the sandbox rather than complex RAG first; cross-system approval processes may need Temporal and identity proxies more than multi-Agent.

## 5. How to Choose Between WorkBuddy and a Self-Built Platform

| Scenario | Better to start with WorkBuddy/Enterprise product | Better to self-build or combine an open-source stack |
| --- | --- | --- |
| Office documents, spreadsheets, PPT, research and file processing | Yes, the product delivers a complete solution and pilots are fast | Only when there are special compliance or deep workflow requirements |
| Already heavily using Tencent Docs, WeCom, QQ Mail and similar ecosystems | Shorter connection path | You need to build connectors and identity integration yourself |
| Want business staff to configure Skills, experts and workflows | The enterprise workbench is easier to adopt | Self-building requires an additional low-code product layer |
| Core transactions, production operations and highly deterministic workflows | Can serve as an entry point, but critical actions still need to be carried by business services | Easier to deeply integrate with existing approval, transaction and audit systems |
| Special models, private inference and underlying Runtime customization | Depends on the open boundaries of the enterprise edition | Self-building gives more control, but operational cost is higher |
| External multi-tenant Agent SaaS | Need to separately verify tenant, data and runtime boundaries | Usually requires your own control plane and isolated data plane |

Procurement and self-building are not an either/or choice. A common path is to first use a mature product to validate office scenarios and organizational adoption, then consolidate high-value, deeply integrated and strongly governed workflows into the enterprise's own Agent Control Plane; the underlying models, MCP Servers and business APIs can be reused by both sides at the same time.

## 6. For enterprise rollout, build in this order

![Enterprise Agent build order](../../assets/rag-agent/workbuddy-enterprise-agent-stack/03-adoption-path.png)

### Step 1: Choose a task with clear boundaries that can be accepted and validated

Prioritize read-only or low-risk tasks, such as internal policy Q&A, weekly report summarization, fault information aggregation, or contract clause extraction. Define success rate, manual effort, maximum latency and error consequences first, then discuss models.

### Step 2: Connect identity and read-only tools first

Let the Agent access data as a real user or as an independent workload identity, and avoid sharing high-privilege accounts. Keep the first batch of tools as read-only as possible, and record complete audit logs.

### Step 3: Build a model gateway and a minimal Agent Harness

Unify model credentials, routing, quotas and cost; use one Agent with a small number of tools to run through a closed loop. Unless the task naturally requires role separation, do not adopt multi-Agent yet.

### Step 4: Choose the Runtime based on side effects

Pure Q&A runs on a shared service; file processing can use short-lived workspaces; running code and browsers goes into an isolated sandbox. Do not give every Agent a Shell, and do not create a full virtual machine for a single FAQ Agent.

### Step 5: Build Trace and regression sets first, then expand users

Prepare real desensitized samples, privilege-escalation samples and tool-failure samples before launch. Automatically run regression on every change to models, Prompts, Skills, knowledge or connectors; keep only desensitized data that is genuinely needed in production Trace.

### Step 6: Do multi-Agent, long-term memory and full automation last

These capabilities significantly increase system complexity. Only move to the next stage after a single Agent has reached a stable baseline and you can explain which metric the split improves.

## 7. The eight pitfalls most likely to trip you up

1. **Treating Agent as Prompt engineering.** Prompts cannot replace execution state, permissions, sandboxing and evaluation.
2. **Every application calls the model vendor directly.** Credentials, routing, rate limiting, cost and failover will quickly spiral out of control.
3. **Treating MCP as an authorization layer.** MCP standardizes connections; it does not automatically understand enterprise data permissions and approval responsibilities.
4. **Executing tools with a shared admin account.** User identity and data boundaries disappear, and audit logs can no longer be attributed.
5. **Treating a Kubernetes Pod as a full sandbox.** High-risk code requires stronger isolation, egress policies and resource limits.
6. **Treating chat history as Trace.** It cannot reconstruct the retrieval, model, tool, retry, approval and version chain.
7. **Building multi-Agent from day one.** More roles does not mean better quality; it usually first adds latency, cost and debugging difficulty.
8. **Only watching Demo success and not maintaining a failure set.** The real moat for an enterprise is not a one-off demo, but the continuously accumulated evaluation set, failure traces, permission model and business closed loop.

## 8. Final judgment

From WorkBuddy's publicly visible product form, mature Agent platforms are no longer organized around "one model plus a few plugins," but around the following four objects:

```text
Agent：声明目标、模型、能力与边界
Runtime：提供可隔离、可恢复的执行环境
Session：保存一次任务的上下文与执行状态
Connector：以受控身份连接真实业务系统
```

On top of these four objects, adding a model gateway, knowledge and memory, Trace, evaluation, approval and cost governance is what makes up a complete enterprise Agent technology stack.

So when an enterprise selects technology, the first question should not be "LangGraph or some multi-Agent framework," but rather: which business outcome are we preparing the Agent to be responsible for, on whose behalf does it need to take what actions, and how does it stop, recover, audit and roll back after failure.

Once these questions are answered clearly, the framework is usually just a replaceable layer; if they are not answered clearly, even the strongest model will only make the Demo look more like production, without actually becoming production.
