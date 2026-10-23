---
title: "AI Agent, Sandbox, and Tool Execution"
description: "Runtime isolation, networking, identity, tool permissions, and audit design for Agent workloads"
status: evolving
last_reviewed: 2026-10-23
---

# AI Agent, Sandbox, and Tool Execution

Agent workloads differ from ordinary Deployments: they may hold state for long periods, proactively access external tools, generate and execute code, process untrusted web pages or repository content, and take actions without step-by-step human confirmation.

Kubernetes can provide identity, quotas, networking, storage, and lifecycle foundations, but it cannot automatically prove that Agent behavior is safe.

For how agents read pages, click elements or use screenshots to operate desktops, including Codex and other public implementations, see [Computer Use and Browser Implementation](rag-agent/agent-computer-use-browser-implementation.md).

If you are comparing Kubernetes Agent Sandbox, gVisor, Kata, Firecracker, or managed execution platforms, first read [Agent Sandbox Selection and Architecture Analysis](rag-agent/agent-sandbox-selection.md). If you plan to use OpenClaw as the foundation for an internal Agent platform, see [OpenClaw Enterprise Platform Pros/Cons and Secondary Development Boundaries](rag-agent/openclaw-enterprise-agent-platform.md). This chapter continues the discussion of tool authorization, Prompt Injection, networking, budgets, auditing, and release boundaries after selection.

## 1. Why Agents Are Not Ordinary Microservices

| Characteristic | Ordinary Service | Agent Runtime |
| --- | --- | --- |
| Lifecycle | Multi-replica, replaceable | Often singleton, long sessions, can pause and resume |
| State | Primarily external databases | Workspace, memory, tool state |
| Input | API requests | Prompts, web pages, repositories, files, events |
| Behavior | Predefined code paths | Model-driven dynamic planning and tool calls |
| Permissions | Fixed downstream APIs | Files, Shell, browser, cloud APIs, etc. |
| Risk | Code vulnerabilities | Also includes Prompt Injection and tool abuse |

Therefore, the Agent control plane, execution sandbox, and tool proxy must be separated.

## 2. Reference Architecture

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

Agents should not directly hold long-term administrative keys for all external systems.

## 3. Positioning of Agent Sandbox

Kubernetes SIG Apps' Agent Sandbox provides the `Sandbox` CRD for managing singleton workloads with stable identity and persistent state; extended APIs include `SandboxTemplate`, `SandboxClaim`, and `SandboxWarmPool`. As of 2026-08-03, the project release line is `v0.5.4` and the API is `v1beta1`, but it remains a pre-1.0 project that requires pinning versions and rehearsing upgrades. References: [Agent Sandbox Documentation](https://agent-sandbox.sigs.k8s.io/docs/) and [Releases](https://github.com/kubernetes-sigs/agent-sandbox/releases).

What it solves is declarative lifecycle:

- Create and reclaim isolated environments;
- Stable identity and workspace;
- Templated runtime;
- Warm pool to reduce startup latency;
- Decoupling of Claims from specific Sandboxes.

It is not a RuntimeClass, nor a Prompt security product; it does not replace gVisor/Kata, NetworkPolicy, Secret management, or tool authorization.

## 4. How to Choose Isolation Levels

| Risk | Recommended Isolation |
| --- | --- |
| Only calls controlled APIs, does not execute code | Ordinary restricted Pod can be a starting point |
| Executes user scripts or third-party dependencies | Dedicated ServiceAccount, default-deny networking, read-only root filesystem |
| Executes untrusted repositories or generated code | Sandbox RuntimeClass such as gVisor/Kata, optional dedicated node pool |
| Strong adversarial, multi-tenant code execution | Micro-VM/VM, dedicated network, and stronger hardware boundaries |

Kubernetes officially states that sandboxed Pods have no unified security API definition, and isolation effectiveness depends on the specific runtime; gVisor, Kata, etc. can only strengthen kernel boundaries, not replace least privilege. Reference: [Pod Security Standards - Sandboxed Pods](https://kubernetes.io/docs/concepts/security/pod-security-standards/)

## 5. Workspace Lifecycle

Classify data into:

- Read-only input snapshots;
- Agent-writable workspace;
- Structured session state;
- Outputs that require review before submission;
- Temporary cache;
- Audit evidence.

The design must answer:

- What is retained after Sandbox deletion;
- Whether recovery returns to the same model/tool version;
- Whether the workspace may contain Tokens or downloaded malicious files;
- How outputs are scanned before entering trusted Git/Registry;
- Whether different users may mount the same volume;
- Whether automatic cleanup meets retention and compliance requirements.

## 6. Tool Permissions Must Be Modeled Item by Item

For each tool, define:

- Allowed operations and resource scope;
- Read-only or writable;
- Parameter Schema and maximum size;
- Timeout, retry, and idempotency;
- Per-session/user call budget;
- Whether human approval is required;
- Whether returned content re-enters the model context;
- Audit fields and masking rules.

"Can execute Shell" is not an acceptable fine-grained permission model.

## 7. Short-Term Identity and Tool Gateway

It is recommended that Agents only hold their own Kubernetes identity, with the Tool Gateway:

1. Verifying the Sandbox, user, and session;
2. Checking the policy for this tool call;
3. Exchanging short-term downstream credentials;
4. Constraining resource scope and operations;
5. Recording approvals, parameter summaries, and results;
6. Invalidating credentials after the call ends.

Even if the Agent workspace is compromised, long-term production keys should not be exposed.

## 8. Network Policy

Default-deny outbound traffic, then open per tool proxy:

- DNS only allows controlled Resolvers;
- Git goes through an internal proxy or allowlist;
- Browser access goes through URL filtering and download scanning;
- Access to cloud metadata addresses, nodes, and the Kubernetes API is forbidden;
- Databases are not directly exposed to the Sandbox;
- Set bandwidth, connection count, and request budgets for public outbound traffic;
- Treat tool responses as untrusted input.

Allowlisting by domain name alone can be bypassed through redirects, DNS, or user content; the proxy layer must check the final destination.

## 9. Platform Perspective on Prompt Injection

Prompt Injection cannot be solved with just a system prompt. Platform controls include:

- Separation of untrusted content from system instructions;
- Tool permissions cannot be expanded by the model itself;
- High-risk write operations require policy or human approval;
- Tool return values cannot modify control-plane policy;
- Configuration files in external repositories are treated as untrusted;
- Re-verify execution results before they enter trusted pipelines;
- Use deterministic server-side validation for critical business actions.

The model can propose actions; the authorization system decides whether actions are allowed.

## 10. Resource and Cost Protection

Agents may loop indefinitely calling models and tools. The following are needed:

- Per-session maximum Tokens, time, and cost;
- Maximum concurrent tool calls;
- Sandbox CPU, memory, GPU, and ephemeral storage limits;
- Idle pause and maximum lifetime;
- Warm Pool upper limit;
- Download and log capacity limits;
- Detection of repeated plans or no-progress loops;
- Safe termination and state preservation after exceeding budget.

## 11. Observability and Audit

It is recommended to record the event chain rather than the full thought process:

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

Metrics include:

- Sandbox creation P50/P95 and failure rate;
- Warm Pool hit rate;
- Per-session Tokens, tool calls, and cost;
- Policy rejections and approval wait times;
- Agent completion rate, timeout rate, loop termination rate;
- Workspace capacity and cleanup latency;
- Runtime isolation anomalies.

Logs should not by default save full Prompts, user code, tool credentials, or sensitive returned content.

## 12. Release and Recycling

Code, configuration, or images produced by Agents must not enter production directly:

- Build in an isolated environment;
- Run tests, Lint, Secret and vulnerability scanning;
- Generate a reviewable Diff;
- Human or policy approval;
- Rebuild and sign with a trusted CI identity;
- Deploy through the standard GitOps/release pipeline.

The Agent's Sandbox identity should not simultaneously hold production release permissions.

## 13. Launch Checklist

- [ ] Clarify the state and permission model that distinguishes Agents from ordinary services;
- [ ] Separate the execution environment, Agent control plane, and Tool Gateway;
- [ ] Use an appropriate RuntimeClass or stronger isolation for untrusted code;
- [ ] Use a dedicated least-privilege identity for each Sandbox;
- [ ] Default-deny networking, with all tool access through a controlled proxy;
- [ ] Tool permissions have parameter Schema, budgets, audit, and approval;
- [ ] Prompt Injection cannot expand platform authorization;
- [ ] Session Tokens, time, cost, and storage all have hard limits;
- [ ] Workspace retention and cleanup policies are explicit;
- [ ] Agent artifacts must go through trusted CI before release;
- [ ] Audit records capture the action chain without leaking sensitive content.

## Further Reading

- [Agent Sandbox](https://agent-sandbox.sigs.k8s.io/)
- [Agent Sandbox Documentation](https://agent-sandbox.sigs.k8s.io/docs/)
- [Kubernetes Pod Security Standards](https://kubernetes.io/docs/concepts/security/pod-security-standards/)
- [Kubernetes RuntimeClass](https://kubernetes.io/docs/concepts/containers/runtime-class/)
