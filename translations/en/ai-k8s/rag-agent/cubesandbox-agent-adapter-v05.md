---
title: "CubeSandbox Agent Adapter v0.5: Strong Audit, Trusted Tasks, and Five-Client Field Testing"
description: "Understand the audit boundaries and deployment practices of CubeSandbox Agent Adapter v0.5 through execution intent persistence, failure lockdown, and manual reconciliation"
status: tested
last_reviewed: 2026-09-11
---

# CubeSandbox Agent Adapter v0.5: No Audit Trail, No Execution

For multi-cluster routing, internal templates, log continuation, and console practices in later versions, see [Adapter v0.6](cubesandbox-agent-adapter-v06.md). This page retains the v0.5 implementation and field test records.

CubeSandbox Agent Adapter `v0.5.0` turns strong auditing into a precondition for controlled execution, and completes real MicroVM acceptance testing across five clients: OpenClaw, DSH, Hermes, Codex, and Claude Code.

The last time I wrote about CubeSandbox Agent Adapter was `v0.3.0`.

At that point, it had just moved from "three Agents sharing one sandbox entry" to managing persistent workspaces, asynchronous Jobs, PTY, Checkpoint, Rollback, Fork, and multi-tenant identity. It was beginning to look like an execution control plane, not just a few plugin code snippets.

The subsequent `v0.4.0` added a path better suited to enterprise intranets: local Code Agents no longer directly access production SSH, database passwords, or cluster admin kubeconfigs. Instead, they submit a named task defined by the server side. The task first undergoes parameter validation, then independent identity approval when needed, enters a fixed-Profile MicroVM, and upon completion returns only whitelisted results and a signed receipt.

But one problem remained genuinely unsolved: **if auditing is just an asynchronous JSONL write, and the process crashes between execution and log write, who can prove whether that operation actually happened?**

`v0.5.0`, released on September 9, 2026, primarily answers this question.

The most critical point of this upgrade is: **persistent auditing has changed from "recording an entry after execution" to "recording must happen before execution." When the authoritative audit is unavailable, controlled operations fail closed directly.**

The official image is `ghcr.io/aik8s/cubesandbox-agent-adapter:v0.5.0`, supporting `linux/amd64` and `linux/arm64`. The tag points to commit `80325ae`, with the OCI Index Digest:

```text
sha256:b70e7e537bf0f6615ce6d25e16da60e6aa6b56ee0959204c7c3308901fb3ed14
```

## Five Agents, Still Through a Single Execution Control Plane

v0.5.0 does not require anyone to switch away from familiar Agents. OpenClaw, DeepSeek Harness (DSH), and Hermes Agent continue to connect through their respective plugins; Codex, Claude Code, and other MCP Hosts connect through the local `stdio` MCP Facade.

![Five Agents sharing CubeSandbox Agent Adapter](../../assets/rag-agent/cubesandbox-agent-adapter-v05/architecture.png)

Agents can keep their own UI, models, and Agent Loop, while the security boundary in the middle remains consistent:

- The Adapter holds CubeAPI, CubeProxy, full Sandbox ID, and Traffic Token;
- Clients only receive opaque references and never directly touch underlying sandbox credentials;
- Runtime, Profile, network, paths, quotas, timeouts, and lifecycle are fixed on the platform side;
- Requests are rejected when the backend is unavailable, identity lacks authorization, or auditing is unavailable — no fallback to the host Shell;
- After the MicroVM ends, there is a clear Release, TTL, GC, and verifiable execution record.

The project has now run through OpenClaw, DSH, Hermes, Codex, and Claude Code in real clients. Agent plugins provide 19 general-purpose execution and trusted task tools; when stricter boundaries are needed, clients can be limited to only `cube_task_plan`, `cube_task_submit`, `cube_task_status`, `cube_task_result`, and `cube_task_receipt`.

## From v0.3 to v0.5, Two Pieces the Control Plane Added

![CubeSandbox Agent Adapter evolution from v0.3 to v0.5](../../assets/rag-agent/cubesandbox-agent-adapter-v05/evolution.png)

Looking at the three versions together:

- `v0.3.0` manages state: persistent leases, Redis recovery, asynchronous Jobs, PTY, workspaces, Checkpoint, and multi-tenant authentication;
- `v0.4.0` manages tasks: named TaskTemplate, JSON Schema, Action Scope, independent approval, output whitelist, MicroVM cleanup, and signed Execution Receipt;
- `v0.5.0` manages evidence: persist intent first, then execute external effects, then persist results; when the audit store is abnormal, enter failure lockdown.

These three layers respectively answer "how the task continues," "what the task can do," and "whether what happened can be proven afterward."

## How Local Code Agents Touch Production Resources More Controllably

The place where this architecture is closest to real enterprise practice is its ability to handle the scenario where office networks and production networks are separated.

Many teams keep office networks and production networks isolated from each other. Developers are already accustomed to using Codex, Claude Code, OpenClaw, or DSH locally, but training data, GPUs, internal artifact registries, Kubernetes APIs, and production databases all remain on the other side.

Handing VPN, SSH Keys, long-lived Tokens, or admin kubeconfigs directly to local Agents grants too much permission; deploying the full Agent Runtime, model configuration, session history, and third-party plugins entirely into the production network creates too large a trust boundary.

The Adapter offers a third path: **the Agent stays local, data and credentials stay in production, and only authenticated, authorized, and approved structured tasks cross the boundary.**

![Trusted execution boundary from local Code Agent to production resources](../../assets/rag-agent/cubesandbox-agent-adapter-v05/trusted-execution-boundary.png)

For example, when initiating training or data cleaning, the local Agent only submits parameters that conform to the JSON Schema. The actual scripts, data paths, training APIs, result locations, and workload identity are fixed by production-side templates.

For single-machine preprocessing, small model training, or feature inspection, tasks can run directly in CubeSandbox MicroVMs; for large-scale training on Kubernetes, Volcano, or Slurm, the MicroVM is better suited as a narrow-permission submission and validation boundary, with the internal training platform continuing to handle scheduling.

"Trusted execution" here focuses on policy, isolation, auditing, and resource reclamation. When host invisibility, memory encryption, or hardware remote attestation is needed, confidential computing capabilities such as SGX, TDX, or SEV must be layered on top.

## Why JSONL Alone Is Not Enough

Traditional asynchronous logging has a window that is hard to avoid:

1. The service receives a request;
2. The external command or MicroVM operation has already occurred;
3. The process crashes before the log is written.

After restart, if the system simply retries, the external operation may be executed twice; if it treats the case as a failure, it may conceal effects that have already occurred.

The `required` pattern in v0.5.0 changes the order to:

![v0.5.0 strong audit persistent commit chain](../../assets/rag-agent/cubesandbox-agent-adapter-v05/durable-audit-flow.png)

The first step synchronously commits the sanitized execution intent. Only after the authoritative SQLite log confirms persistence does the Adapter proceed to permission checks, state changes, or backend calls. After external effects complete, results are synchronously committed; if results are not reliably persisted, success is not returned to the client and no Receipt is issued.

If the audit disk cannot be written, the API returns `503 audit_unavailable` and readiness simultaneously fails. If a restart reveals a pending operation with only an intent and no result, the Adapter does not blindly replay it — it remains blocked, waiting for an administrator to reconcile CubeSandbox, Redis, and external task state.

After the administrator confirms the scene, an offline tool can append an `manually_reconciled` event. This action only indicates "manually reconciled" — it does not fabricate task success, nor does it delete the original intent.

## How the Authoritative Record and Outbound Logs Divide Responsibilities

v0.5.0 defaults to `${CUBE_ADAPTER_AUDIT_LOG}.sqlite3` as the authoritative record. JSONL, stdout, and HTTP Collector are retryable outbound copies:

- Each event has a stable `event_id`, and downstream systems deduplicate by it;
- Outbound delivery uses at-least-once semantics; a Collector that is temporarily offline does not cause already-reliably-recorded operations to fail;
- Records pending delivery are also persisted and continue to be delivered after process restart;
- The audit page displays at most the most recent 200 entries; authoritative data still follows the SQLite record.

Audit content continues to be sanitized. Request bodies and identities are saved as keyed digests; raw commands, output, Tokens, and production addresses must not enter public audit records. When complete business evidence is needed, protected ticketing, log platforms, and data governance systems should fill the gap.

## I Ran the Real Kubernetes Failure Path

The acceptance environment deployed the v0.5.0 candidate image as a single non-root Pod, using the `Recreate` policy and a retained 1 GiB RWO local block storage PVC, connected to real CubeSandbox MicroVMs.

The trusted task suites of the four existing clients passed **23/23**, of which 19 actually created or operated MicroVMs:

![v0.5.0 real MicroVM and four-client acceptance](../../assets/rag-agent/cubesandbox-agent-adapter-v05/runtime-clients.png)

Before and after deleting and recreating the Adapter Pod, committed events in the authoritative store remained **498 → 498**; when a second writer process attempted to open the same online log, it was rejected by the exclusive file lock:

![Persistent audit acceptance after Pod recreation](../../assets/rag-agent/cubesandbox-agent-adapter-v05/persistence-restart.png)

The failure lockdown test injected a synthetic pending intent offline that would not call a real backend. After restart, `audit_ready=false`, the pending count was 1, and the controlled API returned HTTP 503; after manual reconciliation, it returned to Ready. Subsequently scanning 506 authoritative events found no mounted key values, Bearer strings, or known raw task markers:

![Failure lockdown, manual reconciliation, and privacy scan](../../assets/rag-agent/cubesandbox-agent-adapter-v05/fail-closed-recovery.png)

After the tag release, Claude Code completed two supplementary tests against the official v0.5.0 amd64 image:

- The `acquire → exec → status → release` direct connection path aligned with Codex;
- The five-tool trusted task path, ending with `succeeded`, cleanup `verified`, and Receipt algorithm HS256.

Permission denials on both paths were 0, and active leases returned to 0 upon completion. The following figure records the complete invocation results in Claude Code's own Light mode TUI:

![Claude Code completing v0.5.0 trusted tasks via MCP](../../assets/rag-agent/cubesandbox-agent-adapter-v05/claude-code-trusted-task.png)

On the code side, the Python 3.10, 3.12, and 3.14 matrix tests were also completed; the 48 Adapter tests include Redis integration; plugin, Helm security constraints, container build, SBOM, and Trivy scans all passed.

## How to Start a New Deployment

The Adapter does not require Kubernetes to run. As long as it can reach an already-deployed CubeSandbox backend, a development machine or single-server setup can use Docker Compose directly:

```bash
git clone --branch v0.5.0 --depth 1 \
  https://github.com/aik8s/cubesandbox-agent-adapter.git
cd cubesandbox-agent-adapter

# 按文档生成 .env，并填写 CubeAPI、CubeProxy 与 READY 模板
docker compose pull adapter
docker compose up -d --no-build adapter

curl --fail http://127.0.0.1:18080/healthz
curl --fail http://127.0.0.1:18080/readyz
```

If the Adapter is deployed on Kubernetes, v0.5.0 defaults to requiring:

- `replicaCount: 1`;
- `audit.mode: required`;
- An RWO PVC on reliable local disk or block storage;
- `Recreate` update policy;
- A PVC with a retain policy so that audit evidence is not automatically deleted when the Release is uninstalled.

The installer can automatically generate an independent random Bearer Token and HMAC Key, and does not print Secrets to the terminal:

```bash
./scripts/install.sh adapter \
  --context <kube-context> \
  --cube-api-url http://cube-api.cube-system.svc:3000 \
  --cube-proxy-host cube-proxy.cube-system.svc \
  --cube-proxy-port 80 \
  --audit-storage-class <可靠本地盘或块存储类> \
  --template agent-code
```

Health checks must show `version=0.5.0`, `audit_mode=required`, and `audit_ready=true`. After the Pod is Ready, a real sandbox E2E must also be run to confirm that the MicroVM creation, execution, and cleanup chain all work.

## Boundaries You Must Know Before Upgrading

The following items need to be confirmed before deployment:

1. The SQLite authoritative store supports only a single writer; multiple Adapters must not share the same database;
2. The audit disk must use local disk or block storage that honors synchronous write and file lock semantics; NFS is not supported;
3. The entire volume must be retained, including `.sqlite3`, lock files, and recovery files — backing up only JSONL is insufficient;
4. The JSONL from `v0.4.0` is a historical export and will not be retroactively recognized as v0.5 strong audit evidence;
5. `best_effort` is an explicit degradation mode that may lose records and must not be marketed as strong auditing;
6. Audit and runtime state are stored separately; restoring leases, tasks, and approvals after restart also requires reliable Redis and encrypted Keys;
7. The single-disk mechanism does not provide cross-node replication, WORM, tamper resistance, automatic backup, or compliance certification;
8. MicroVM isolation cannot prevent a malicious task from leaking data through stdout or files it is allowed to read; output whitelists, DLP, least-privilege identity, and network policies are still required.

## What This Upgrade Means

`v0.3.0` lets multiple Agents share one recoverable execution control plane; `v0.4.0` converges free-form commands into approvable named tasks; `v0.5.0` continues to ask: when the system fails, is the evidence still trustworthy?

v0.5.0 does not wrap external MicroVMs and the local database in a perfect transaction that does not exist. When it encounters the window where "the operation may have already happened, but the result has not yet been persisted," the Adapter stops and waits for reconciliation — it neither auto-retries nor writes unknown outcomes as success.

This version can be summarized in one sentence: **No audit trail, no execution; uncertain outcome, no continuation.**

Before putting it into real production, enterprise identity, network whitelists, data governance, backup, and alerting must still be connected. On top of that infrastructure, the Adapter has strung together identity, tasks, isolation, reclamation, and strong auditing into a complete path for local Code Agents using production-side GPUs, data, internal APIs, and Kubernetes resources.

References:

```text
项目官网：
https://aik8s.github.io/cubesandbox-agent-adapter/

GitHub 项目：
https://github.com/aik8s/cubesandbox-agent-adapter

v0.5.0 Release：
https://github.com/aik8s/cubesandbox-agent-adapter/releases/tag/v0.5.0

Docker Compose 部署：
https://github.com/aik8s/cubesandbox-agent-adapter/blob/main/docs/deploy-docker.zh-CN.md

强审计与恢复：
https://github.com/aik8s/cubesandbox-agent-adapter/blob/main/docs/audit-durability.zh-CN.md

可信执行：
https://github.com/aik8s/cubesandbox-agent-adapter/blob/main/docs/trusted-execution.zh-CN.md
```
