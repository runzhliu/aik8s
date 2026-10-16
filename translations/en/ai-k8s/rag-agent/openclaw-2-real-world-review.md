---
title: "OpenClaw 2.0 Hands-On: Architecture, Features, Performance, and Migration Risk Compared with 1.x"
description: "Hands-on comparison based on isolated installs of OpenClaw 2026.7.1 and 2026.8.1, covering Gateway, Control UI, Workboard, headless Agent, and doctor migration"
status: tested
last_reviewed: 2026-08-31
---

# OpenClaw 2.0 Hands-On: Architecture, Features, Performance, and Migration Risk Compared with 1.x

OpenClaw released [2026.8.1](https://github.com/openclaw/openclaw/releases/tag/v2026.8.1) on August 31, 2026. The vendor calls this generation **OpenClaw 2.0**, but the npm package version still uses a date-based version number rather than semantic version 2.0.0.

This is not an ordinary Control UI reskin. After hands-on testing, a more accurate assessment is that OpenClaw is evolving from "a resident Gateway plus a set of Agent tools" into an **Agent coordination plane** that includes persistent sessions, workboards, approvals, Secrets, devices, cloud workers, and multi-device applications.

Conclusions first:

- **For new deployments, prefer 2026.8.1**: Control UI, persistent sessions, devices and Workers, permissions, approvals, Workboard, and headless execution entry points are all more complete than 1.x.
- **Existing 1.x deployments should not run doctor --fix in place on a production directory**: configuration structure, model routing, Skill state, default concurrency, and SQLite may all be rewritten.
- **2.0's CLI is not noticeably slower, but distribution and resident costs have risen**: in this test, the npm install directory grew from 391.9 MiB to 896.5 MiB, and idle Gateway RSS median grew from 38.3 MiB to 53.9 MiB.
- **The first-day release still has integration friction**: in an isolated install, the default openai/gpt-5.6-sol route fails when the Codex plugin is not registered or its capability is not approved; the local OpenAI-compatible model path works end to end.
- **2.0 is still not a hostile multi-tenant platform**: teams, roles, and shared sessions are more complete, but a Gateway still cannot be treated as a security boundary between mutually untrusted tenants.

## 1. Test Scope and Methodology

To avoid contamination from old configuration, credentials, and plugins, I installed both versions into temporary directories and started them with separate state directories and ports:

| Item | 1.x Baseline | 2.0 |
| --- | --- | --- |
| OpenClaw | 2026.7.1 | 2026.8.1 |
| Node.js | v24.15.0 | v24.15.0 |
| Platform | macOS arm64 | macOS arm64 |
| Gateway | loopback, temporary state directory | loopback, temporary state directory |
| Control UI | forced Light mode | forced Light mode |
| Agent success path | 1.x has no agent exec | local OpenAI-compatible mock, to avoid real models and credentials affecting results |

Test coverage:

1. npm install size, file count, and CLI startup;
2. Gateway startup, /healthz, /readyz, RSS, and default plugins;
3. Information architecture of both Control UI versions;
4. 2.0 Workboard enablement, card creation, and persistence;
5. 2.0 openclaw agent exec success JSON contract;
6. doctor --lint --json and doctor --json;
7. Migration from a valid synthetic 2026.7.1 configuration to 2026.8.1;
8. Configuration, model routing, SQLite, plugin, and rollback risk.

This test does **not evaluate model answer quality**. The headless Agent uses a deterministic local mock, verifying only OpenClaw's configuration parsing, Provider adaptation, HTTP streaming, Agent Loop, and JSON output.

## 2. Installation and Runtime Data

![OpenClaw 1.x and 2.0 measured metrics](../../assets/rag-agent/openclaw-2-review/measured-comparison.png)

| Metric | 2026.7.1 | 2026.8.1 | Observation |
| --- | ---: | ---: | --- |
| npm install directory | 391.9 MiB | 896.5 MiB | +128.8% |
| Installed file count | 32,030 | 35,902 | +12.1% |
| --version warm-start median | 46.9 ms | 44.4 ms | roughly unchanged |
| Gateway RSS median | 38.3 MiB | 53.9 MiB | +40.7% |
| Default loaded plugins | 9 | 14 | +5 |
| doctor --lint --json findings | 36 | 2 | 2.0 default output is more focused |

Three points are easy to misread here:

- Install size is the full npm directory, not a container image size; deduplication results will differ across package managers.
- RSS comes from 5 idle snapshots and only indicates relative change on this machine; it does not represent real message, browser, voice, or multi-Agent load.
- doctor dropping from 36 findings to 2 does not mean risk decreased by 94%. 1.x reports 35 built-in Skills missing binaries or environment variables as warnings; 2.0's default checks are more focused.

doctor's exit code also has a CI trap:

- openclaw doctor --lint --json exits with code 1 when warnings exist;
- 2.0's new bare openclaw doctor --json outputs the same ok: false, but in this test exited with code 0.

Automation must not rely solely on process exit codes; it must also parse the JSON ok and findings fields.

## 3. Control UI: Not a Reskin, but an Information Architecture Rework

### 3.1 1.x: Session and Gateway First

![OpenClaw 2026.7.1 Control UI](../../assets/rag-agent/openclaw-2-review/control-ui-2026.7.1.jpg)

The 2026.7.1 main navigation revolves around "Overview, More, Sessions, Settings." It can handle chat, sessions, and Gateway management, but devices, plugins, automation, security, and work status are scattered across different entry points. The upgrade banner in the screenshot also correctly detects 2026.8.1.

### 3.2 2.0: Apps, Tasks, Permissions, and Runtime Location Become First-Class Objects

![OpenClaw 2026.8.1 Control UI](../../assets/rag-agent/openclaw-2-review/control-ui-2026.8.1.jpg)

2.0's default sidebar becomes "Home, Scheduled Tasks, Plugins," and the command palette can directly enter Sessions, Skills, Apps, Settings, Agents, and Custodian. The message input area adds a session permission mode; the settings page is explicitly split into:

- Nodes and Cloud Workers;
- Agents, Model Providers, MCP, Memory, and Automation;
- Privacy and Security, Secrets, and Approvals;
- Gateway, Browser, Node Host, Discovery, and ACP.

This means "where Agents run, what they can access, who approves, and how state is persisted" has entered the product's main path.

### 3.3 Multi-Device Apps Become Part of the Architecture

![OpenClaw 2.0 multi-device apps page](../../assets/rag-agent/openclaw-2-review/apps-2026.8.1.jpg)

2.0's Apps page places iPhone, Android, Apple Watch, Wear OS, macOS, Windows, Linux, and browser extensions in a single discovery and pairing entry point. It is not just a list of download links: devices can carry chat, approval, notification, camera, Canvas, and Worker capabilities, and the Gateway begins to take on cross-device coordination responsibilities.

### 3.4 Gateway Configuration Looks More Like a Formal Operations Surface

![OpenClaw 2.0 Gateway configuration page](../../assets/rag-agent/openclaw-2-review/infrastructure-2026.8.1.jpg)

The Infrastructure page directly shows the Gateway's authentication mode, Bind, Trusted Proxy, Control UI Origin, HTTP API, Node Skills, and remote Gateway. The page explicitly warns:

- non-loopback deployments must keep authentication enabled;
- trusted-proxy should only be placed behind a hardened identity proxy;
- auto Bind may expose all interfaces;
- Allowed Origins = ["*"] is not suitable for normal production deployments.

More configuration options do not equal automatic security, but at least the security boundary has moved from hidden JSON to a visible operations surface.

## 4. Workboard Hands-On: Task State Enters the Gateway

Workboard in 2026.8.1 is a bundled plugin that is disabled by default. After enabling it and approving its capability, the Gateway's loaded plugins grew from 14 to 15, and the Control UI automatically gained a "Workboard" entry point.

In a temporary state directory, I created a "Validate OpenClaw 2.0 upgrade Gate" card with migration, SQLite, and rollback acceptance criteria. The card appeared immediately in the "To Do" column after creation, and search, priority, Agent, session, tags, and status can all be managed structurally.

![OpenClaw 2.0 Workboard card creation hands-on](../../assets/rag-agent/openclaw-2-review/workboard-2026.8.1.jpg)

Workboard's value is not just a Kanban UI. It connects tasks to Agents, Sessions, run attempts, Proof, Attachments, Heartbeat, Block/Unblock, and the scheduler, so long-running tasks do not have to express state only through chat history.

But it is a disabled-by-default plugin, so "code ships with the package" cannot be treated as "available immediately after upgrade." Production rollout should at minimum verify capability consent, SQLite, scheduler, session association, and backup/restore.

## 5. Headless Agent: 2.0 Adds a Reproducible Execution Entry Point

1.x's openclaw agent has no exec subcommand. 2.0 adds:

    openclaw agent exec \
      --config ./openclaw.json \
      --state-dir ./state \
      --model local-review/mock-model \
      --timeout 10 \
      --json \
      "Return exactly: OPENCLAW_HEADLESS_OK"

With explicit OPENCLAW_STATE_DIR, OPENCLAW_CONFIG_PATH, and a local OpenAI-compatible mock, the measured result was:

    {
      "ok": true,
      "status": "ok",
      "final": "OPENCLAW_HEADLESS_OK",
      "payloads": [
        {
          "text": "OPENCLAW_HEADLESS_OK",
          "mediaUrl": null
        }
      ],
      "codeModeEngaged": false,
      "assistantTurns": 1,
      "model": "mock-model",
      "provider": "local-review"
    }

This provides a cleaner entry point for CI, scheduled tasks, batch processing, and external orchestrators than "start the Gateway and then send WebSocket requests." --cwd, --config, --isolated, --state-dir, --model, multi-level --fallback, --code-mode, --thinking, and the stable JSON envelope also help with reproducibility.

The first-day friction is equally obvious: in a fresh isolated state, selecting openai/gpt-5.6-sol directly causes the run to fail when the Codex runtime plugin is not registered. The migration drill also showed that the Codex plugin declares tool and migration capabilities and requires capability consent. I recommend making "default model responds successfully" an upgrade Gate; Gateway Ready alone is not sufficient.

## 6. Architecture Changes: From Gateway Runtime to Coordination Plane

![OpenClaw 1.x and 2.0 architecture evolution](../../assets/rag-agent/openclaw-2-review/architecture-1x-vs-2.png)

### 6.1 1.x Core Model

1.x's structure can be summarized as:

    Control UI / CLI / Channels
                ↓
         OpenClaw Gateway
                ↓
    Session / Model / Agent Loop / Skill / Plugin / Tool / Node

Its strengths are a short path, simple deployment, and quick adoption by individuals and small teams in the same trust domain. The limitations are equally clear: state, devices, approvals, task management, and team collaboration feel more like peripheral Gateway capabilities.

### 6.2 The Four New Planes in 2.0

2.0 does not abandon the Gateway; instead, it adds four planes around it:

1. **Persistent state plane**: session search, Progress Cards that survive reloads, SQLite, recovery and backup.
2. **Permission and security operations surface**: session permissions, Secret requests, approvals, Command Owner, plugin trust and provenance hints.
3. **Task and collaboration plane**: Workboard, conversation-bound automation, structured questions, branching and shared sessions.
4. **Runtime location plane**: paired devices, cloud workers, external supervisors, device hosting, and experimental Fleet/Swarm.

Therefore, 2.0 is closer to an "Agent operating system." But it still cannot automatically solve:

- strong isolation between mutually untrusted users;
- organization-level SSO, tenancy, RBAC/ABAC, and budgets;
- arbitrarily scaled Active-Active Gateways;
- plugin supply-chain review and runtime enforcement policy;
- unified zero-trust identity across all devices and Workers.

## 7. 1.x vs. 2.0 Capability Matrix

| Capability | 1.x | 2.0 | Assessment |
| --- | --- | --- | --- |
| Control UI | Session/Gateway-centric | Apps, tasks, devices, security, and infrastructure reorganized | Significant upgrade |
| Sessions | Local sessions and history | Search, Progress Cards, branching, shared participation, Incognito | Better suited to long-running tasks |
| Task management | Cron, Heartbeat, in-chat status | Workboard, conversation-bound automation, /loop | Moving from "messages" to "work" |
| Runtime location | Gateway and paired Nodes | Devices, cloud Workers, external supervisors, Fleet/Swarm | Significant expansion, partly experimental |
| Security operations | Gateway Token, tool policy, approvals | Permission Modes, Secrets, Recurring Approval, Command Owner | More visible, but configuration responsibility remains with the user |
| Models and Providers | Mostly built-in routing | Provider plugins unpackaged, model allowlist, runtime policy | More modular, more complex to migrate |
| Automation integration | CLI/Gateway invocation | agent exec stable JSON, A2A 1.0, email triggers | Easier to integrate with CI and external systems |
| Recovery | Configuration and partial state backup | SQLite maintenance, recovery, resumable backups, state audit | More complete operations surface |
| Team capabilities | Multi-Agent, shared channels | operator role, shared profiles, shared sessions | Still not adversarial multi-tenancy |

## 8. Migration Hands-On: What doctor --fix Actually Changed

I first created a synthetic configuration that passes 2026.7.1 config validate --json, placed the entire state and workspace under /private/tmp, and then ran with 2026.8.1:

    openclaw doctor --fix --non-interactive --yes

The migration succeeded, and the post-migration configuration also passed 2026.8.1 validation. But the before/after diff goes far beyond the version number:

- agents.list changed to keyed agents.entries;
- agents.entries.*.default removed;
- openai-codex/gpt-5.5 changed to openai/gpt-5.5;
- codex/gpt-5.4 changed to openai/gpt-5.4;
- agentRuntime.id = "codex" written for both models to preserve the original routing intent;
- maxConcurrent = 8, subagents.maxConcurrent = 8, and compaction.mode = "safeguard" written;
- 35 Skills that lack dependencies in the current environment written as enabled: false;
- lastTouchedAt migrated into shared SQLite;
- Shared state tables continue migrating to SQLite STRICT, with retired tables and indexes cleaned up;
- Automatic configuration backups generated.

This shows the 2.0 migration is not "reading old JSON as-is," but an upgrade in which **configuration, runtime policy, and state model evolve simultaneously**.

## 9. Migration Risks That Must Be Listed in the Change Order

![OpenClaw 2.0 Migration Gate and Risks](../../assets/rag-agent/openclaw-2-review/migration-gates.png)

### 9.1 Configuration Structure Rewrite

agents.list → agents.entries is not difficult by itself, but doctor --fix will also fill in default concurrency, Compaction, Skill toggles, and Wizard metadata. For GitOps environments, this creates a large diff; for capacity environments, the default concurrency increase may also change CPU, memory, and model request peaks.

**Recommendation**: After fixing on a replica, review the full diff and re-include the automatically written default values in capacity assessment.

### 9.2 Codex/OpenAI Model Routing Migration

Old codex/* and openai-codex/* will be changed to openai/*, then model-scoped agentRuntime.id = "codex" preserves native Codex semantics. Model names look more unified, but the runtime dependency shifts from "prefix" to plugin and runtime policy.

**Risk**: When the Codex plugin is not installed, not enabled, or its capability is not approved, the default model will only expose failure after Gateway Ready.

### 9.3 SQLite Migration and Rollback Directionality

2.0 continues migrating shared state, sessions, Cron, audit, and device identity into SQLite. The official documentation explicitly notes: new sessions that exist only in SQLite after upgrade will not automatically appear in the old storage when rolling back to the old runtime.

**Risk**: Rolling back only the npm package or container image cannot roll back state.

### 9.4 Absolute Workspace Paths May Escape the State Directory

This drill captured a very practical risk: the workspace in 1.x --dev configuration is an absolute path. Even when OPENCLAW_STATE_DIR points to a temporary directory, doctor --fix will still access and migrate TOOLS.md/AGENTS.md in that workspace according to the configuration.

**Recommendation**:

- When copying configuration, also rewrite all absolute paths for workspace, session, plugin, and credential;
- Run the migration with a dedicated test account;
- Perform a file inventory and read-only mount drill on the target directory before fixing;
- Do not assume "state directory is isolated" means "all writes are isolated."

### 9.5 Provider Unbundling, Plugin SDK, and Capability Consent

Multiple official Providers have moved to separate packages; plugins will display source, capability, and provenance; old Plugin SDK import paths have entered the retirement window. OpenProse and /prose have been removed and need to be migrated to Agent Skills.

**Risk**: A plugin being discoverable does not mean it has been installed, authorized, and registered at runtime.

### 9.6 Default Behavior Drift

2.0 adjusts default behaviors for session reset, proactive memory/grounded dreaming, foreground concurrency, model allowlist, approval, and shared profiles.

**Risk**: The upgrade may "start successfully and serve requests successfully," but memory, cost, concurrency, session boundaries, and approval experience may already have changed.

### 9.7 doctor --fix Mass-Disables Currently Unavailable Skills

In the synthetic migration, 35 Skills missing binaries, environment variables, or configuration were written with enabled: false.

**Risk**: Build machines, Canary, and production machines have different dependencies, so migration results may also differ; running --fix on a minimal build machine will disable Skills that were actually available in production.

## 10. Recommended Upgrade Runbook

### 10.1 Before Upgrade

    openclaw backup create
    openclaw doctor --lint --json
    openclaw doctor --post-upgrade --json
    openclaw config validate --json

Also record:

- OpenClaw, Node, plugin, and Provider versions;
- openclaw.json, SQLite, Session, Cron, Workspace, and credential storage locations;
- All absolute paths;
- Default model, Fallback, Agent Runtime, and authentication profiles;
- Plugin capabilities, channel connections, and approval policies;
- Pre-upgrade health checks and a fixed set of regression requests.

### 10.2 Migrate in a Copied Environment

1. Copy configuration, SQLite, Session, Cron, and Workspace;
2. Change all absolute paths to the replica;
3. Run doctor --lint --json first;
4. Then run doctor --fix --non-interactive on the replica;
5. Review the configuration diff and automatic backups;
6. Run config validate, SQLite dry-run/validate, and plugin post-upgrade;
7. Start the Gateway, verify /healthz, /readyz, and real model responses;
8. Verify sessions, Cron, channels, Workboard, approvals, backup, and restore.

### 10.3 Canary Gate

Only expand traffic after at least the following conditions are met:

- The default model and all explicitly overridden models respond;
- Old sessions, Cron, and automations have no missing or duplicate entries;
- Plugin/Provider capability consent is complete;
- SQLite checksum and backup restore pass;
- Critical Skills are not accidentally disabled;
- Gateway, Node, device, and Worker connection methods match expectations;
- Concurrency, cost, memory, and session reset behavior match the change order.

### 10.4 Rollback

The rollback package must include all of the following:

    Old OpenClaw binary/image
    + Pre-upgrade openclaw.json
    + Pre-upgrade SQLite and legacy state
    + Pre-upgrade Workspace / Plugin state

Immediately stop expanding traffic when any of the following occurs: missing sessions, model routing changes, unauthorized plugins, duplicate or missed Cron runs, Gateway connection failures, or SQLite validation failures. It is forbidden to replace only the npm package and continue reusing migrated state.

## 11. Is It Worth Upgrading

### Suitable for Direct Adoption of 2.0

- New personal or small-team Agents within the same trust domain;
- Need cross-device, cloud Worker, Workboard, or headless Agents;
- Want approval, Secret, permission, and Gateway settings in a unified UI;
- Can accept first-day plugin authorization and configuration adjustments.

### Should First Do a Full Canary

- Already have a large number of Sessions, Cron, Channels, Skills, and custom plugins;
- Use codex/* or openai-codex/* model routing;
- Configuration contains absolute workspaces or external state directories;
- Depend on GitOps, strict rollback, and fixed cost/concurrency;
- Gateway carries production notifications, operations, or business automation.

### Recommended to Wait for a Subsequent Patch Version

- Cannot copy production state for drills;
- No SQLite-level backup/restore capability;
- Custom plugins have not completed SDK migration;
- Default model plugins are not yet installed and capability consent not completed in the target environment;
- Any single session or Cron loss, or duplicate execution, is unacceptable.

## 12. Final Assessment

OpenClaw 2.0 is a substantive major release: it pushes the "chat Agent Gateway" toward a "coordination plane operable by people, devices, Workers, and automation together." Control UI, Workboard, headless execution, permissions, Secrets, approval, and recovery capabilities are not just nouns in the release notes — this isolated real-world test was able to actually open, configure, and run them end to end.

The cost is equally real: larger packages, more resident capabilities, more complex plugin boundaries, and migration that rewrites configuration and state. For existing 1.x users, the most important upgrade action is not npm install, but first establishing a migration chain that is **replicable, diffable, verifiable, and fully rollbackable**.

If summarized in one sentence:

> 2.0 is worth adopting for new deployments, and also worth upgrading to for existing users; but it should be treated as a state and runtime architecture migration, not an ordinary version update.

## References

- OpenClaw 2026.8.1 Release: https://github.com/openclaw/openclaw/releases/tag/v2026.8.1
- OpenClaw Releases: https://docs.openclaw.ai/releases/2026.8.1
- Doctor CLI: https://docs.openclaw.ai/cli/doctor
- Agent Exec: https://docs.openclaw.ai/cli/agent#agent-exec
- Model Providers: https://docs.openclaw.ai/concepts/model-providers
- Plugin SDK Migration: https://docs.openclaw.ai/plugins/sdk-migration
- Gateway Security: https://docs.openclaw.ai/gateway/security/
- Backup CLI: https://docs.openclaw.ai/cli/backup
