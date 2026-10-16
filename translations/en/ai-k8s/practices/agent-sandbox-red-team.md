---
title: "Agent Sandbox Attack and Defense Experiment"
description: "Validate Agent isolation boundaries with file, credential, network, resource exhaustion, and persistence tests"
status: lab
last_reviewed: 2026-08-04
---

# Agent Sandbox Attack and Defense Experiment

The goal of the experiment is to verify what untrusted Agent code can affect at most, not to prove that "containers are safe." All attack samples may only be executed in an authorized, isolated environment with no production credentials.

## 1. Threat Use Cases

| Category | Test Question | Pass Criteria |
| --- | --- | --- |
| Files | Can it read the host, other Workspaces, or Secrets | Only explicit workspaces are accessible |
| Identity | Can it obtain SA Tokens, cloud metadata, or tool keys | No long-lived credentials by default |
| Network | Can it scan the internal network, access the control plane, or data services | Only declared Egress is allowed |
| Kernel | Can it use dangerous syscalls, devices, or privileged capabilities | Rejected by Runtime/Policy |
| Resources | Fork bomb, disk exhaustion, GPU/network abuse | Quota, Limit, and timeout take effect |
| Persistence | Can it leave processes, files, or routes after the task ends | Sandbox destruction is verifiable |
| Tools | Can a prompt invoke high-risk APIs beyond its authority | Tool Gateway requires secondary authorization |

## 2. Comparing Runtimes

Compare regular containers, hardened containers, gVisor, Kata/microVMs, and dedicated Sandbox Runtimes under the same Pod API and policy. Record startup time, density, syscall compatibility, networking, GPU support, destruction residue, and escape surface.

## 3. Prompt Injection Chain

```text
不可信网页/文档
  → Prompt Injection
  → Agent 生成工具调用
  → Tool Gateway 鉴权与参数校验
  → Sandbox 执行
  → 输出过滤与审计
```

A sandbox can only limit the consequences of execution; it cannot replace tool authorization, data permissions, and human confirmation.

## 4. Automated Evidence

Each test saves the Sandbox ID, image digest, RuntimeClass, NetworkPolicy, identity, syscall/network audit, exit reason, and cleanup result. Automatically regress after upgrading the kernel, Runtime, or policy.

## 5. Stop Conditions

If access to real credentials, the production network, or host devices is discovered, stop the experiment immediately, revoke credentials, and handle it as a security incident. Do not continue attempting to expand the scope of impact.

Further reading: [Agent Sandbox Selection](../rag-agent/agent-sandbox-selection.md), [Agent and Tool Execution](../agentic-workloads.md), [Security Governance](../security-governance.md)
