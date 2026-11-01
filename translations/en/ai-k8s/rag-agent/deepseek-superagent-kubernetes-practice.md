---
title: Deploying DeepSeek Super-agent on Kubernetes, from Chat Requests to Code PRs
description: A Gitea and Mattermost demo covering multi-file coding, concurrent work, human follow-ups and recovery, with real screenshots and independent acceptance checks
status: evolving
last_reviewed: 2026-11-01
---

# Deploying DeepSeek Super-agent on Kubernetes, from Chat Requests to Code PRs

The earlier [source analysis](deepseek-superagent-prototype-analysis.md) explained how Super-agent separates messages, authority, work items and execution sessions. This time I deployed it in an isolated Kubernetes test environment. A person requests work in Mattermost; the agent changes a demonstration repository in Gitea, runs tests, opens a Pull Request (PR), and returns the result to the original conversation thread.

I started with a pricing-function fix to check the complete path, then submitted three independent multi-file projects to observe two running workers and a third queued task. Validation included independent HTTP, CLI, input-scale and process-recovery checks, rather than accepting the agent's reports alone.

**Gitea and Mattermost are adapters added for this demo, not an upstream-supported product combination.** The upstream prototype targets one GitHub repository, with GitHub and optional Feishu sources, and explicitly describes itself as research code. The source baseline here is `6337fc823ce20251c8de8085948165c81aaa701e`. [Official README](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/6337fc823ce20251c8de8085948165c81aaa701e/README.md)

## 1. Keep the initial system small

The demo has four long-running Pods. Its control and tool-execution components request no GPU; they use an existing model API.

| Component | Version used | Responsibility and persistence |
| --- | --- | --- |
| DeepSeek Harness (DSH) | `0.2.2-alpha.2`, image `0.2.2-alpha.2-r1` | Loads the Super-agent Bundle and stores sessions, orchestration SQLite and working directories |
| Gitea | `28.2.0` | Demonstration repository, branches and PRs; uses SQLite |
| Mattermost Team Edition | `12.0.1` | Demo team, private channel and task threads |
| PostgreSQL | `17.11` | Mattermost database |

There is no Redis, message broker or object store. The DSH image comes from [deepseek-harness-docker](https://github.com/runzhliu/deepseek-harness-docker). The demo uses new volumes and an independent Profile, without mounting a personal session directory. The image supplies the runtime; the Super-agent Bundle and collaboration sources still require installation, configuration and validation. [Image project documentation](https://github.com/runzhliu/deepseek-harness-docker/blob/b6ed820a0611f5d81d0be0ed1970bdb7f009d514/README.md)

![Demo architecture and model access boundaries](../../assets/rag-agent/deepseek-superagent-practice/workflow.png)

*The diagram shows the adapted deployment. Model inference is a downstream dependency. The two workers are DSH sessions, not separate sandbox Pods.*

Each task gets its own session, directory and `agent/<ticket-name>` branch. Changes for the three projects are restricted to `services/webhook-relay/`, `tools/logscope/` and `tools/jobrunner/`, reducing overlapping-file conflicts. All results remain PRs awaiting human review; none is merged automatically.

Storage uses local persistent volumes with retention enabled. This supports testing Pod recreation on the same test node. Node or local-disk failure requires a separate recovery design; this experiment does not establish cross-node high availability.

### 1.1 Deployment and trial sequence

The deployment started with PostgreSQL, Mattermost and Gitea. After checking databases, persistent volumes and pages, I created dedicated bots, a private channel and a demo repository. An independent DSH instance then loaded the compiled Super-agent Bundle, source adapters, fixed repository scope, allowed task initiators and two execution slots. Real tasks came last.

The model API key remains in a dedicated bridge process on the office machine; the Pod holds only demo-bridge credentials. The bridge accepts a fixed model and designated interfaces rather than arbitrary upstream URLs. This is an access-path choice for this environment; a cluster that can reach the model API does not need this extra layer.

After deployment, verify page health, authenticated model requests, tool calls and test commands separately. A successful “hello” request is insufficient: a complex coding task can exhaust its output budget before calling a tool or have its stream truncated by transport timeouts. The Gitea/Mattermost integration here is custom experimental code. Adding a few environment variables to the upstream image does not reproduce this combination.

## 2. Where Gitea and Mattermost connect

Replacing a GitHub hostname is insufficient. A Source also needs identity checks, stable event identities, thread context, read cursors and a reply Channel. PR ownership and lifecycle tracking must be adapted as well. [Upstream extension cookbook](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/6337fc823ce20251c8de8085948165c81aaa701e/docs/008-cookbook.md)

| Input or output | Domain record | Demo restriction |
| --- | --- | --- |
| Mattermost message | Trigger; root message and replies share one Thread | One private channel and an allowed-user-ID list; the bot's own messages are filtered |
| Gitea issues and comments | Triggers and repository discussion threads | One demonstration repository and a dedicated bot account |
| Gitea PR | Deliverable bound to its original Ticket | Validate author, repository and branch rather than binding arbitrary PRs |
| Agent reply | Persisted through the Outbox before posting to the original thread | Attach a receipt marker and check for it before retrying |

### 2.1 Prepare two dedicated identities

Gitea uses the dedicated account `demo-agent`, which owns the private demonstration repository `demo-agent/agent-demo`. Its token scopes in this deployment are `write:repository`, `write:issue`, and `read:user`, used for repository operations, issue comments, and identity lookup. It is not a Gitea system administrator, but it owns this demo repository; this must not be described as server-enforced permission to edit only one subdirectory.

Code goes to `agent/<ticket-name>` branches. The `main` protection rule disables pushes and force pushes, requires one approval, and restricts the merge allowlist to the human demo account `demo-admin`. Repository rules work alongside the task's no-merge requirement; a prompt alone does not protect main.

![Actual main-branch protection settings in Gitea](../../assets/rag-agent/deepseek-superagent-practice/gitea-main-protection.jpg)

The screenshot shows “Disable push” selected. The other merge constraints are configured in the same branch rule. Main was neither changed nor merged into during this run.

Mattermost has a bot `@demo-agent`, displayed as **DSH Super-agent**, with the ordinary `Member` role. It is added to the demo team and private Coding Demo channel. The additional global posting permissions `post:all` and `post:channels` remain disabled. The bot reads messages and replies with its own API token, rather than an administrator's token.

![Role and additional permissions of the Mattermost bot account](../../assets/rag-agent/deepseek-superagent-practice/mattermost-bot-permissions.jpg)

This is the actual bot configuration: Member role, with both additional permissions unchecked. All identities shown are demonstration accounts; no token is included.

### 2.2 How API credentials reach DSH

A dedicated command-line adapter, `demo-bridge`, calls the Gitea and Mattermost REST APIs. It is separate from the model-access bridge described earlier.

Collaboration settings are projected read-only from the Kubernetes Secret `agent-integrations` to `/run/demo/integrations.json`. The adapter reads this path by default, or a path supplied through `DSH_DEMO_CONFIG_FILE`. These key fields come from the demo's custom implementation:

| Field | Purpose in this demo |
| --- | --- |
| `giteaURL`, `giteaToken` | Internal Gitea API address and bot token; the service address here is `http://gitea:3000` |
| `repository` | Fixed repository `demo-agent/agent-demo` |
| `mattermostURL`, `mattermostToken` | Internal Mattermost API address and bot token; the service address here is `http://mattermost:8065` |
| `channelId`, `botId` | Fixed channel ID and bot user ID for reading messages, filtering the bot's own posts, and replying in the original thread |

This describes selected fields, not an official upstream schema or a complete runnable configuration file. Actual tokens are absent from the article, chat prompts, and screenshots. A read-only mount restricts writes; tools able to read files in the same container may still read credentials, so the mount is not an isolation boundary against malicious code.

The compiled custom plugin registers `gitea` and `mattermost` Source kinds with Super-agent. Sources use the adapter to read events, retrieve thread context, and send replies. A separate Git credential helper checks the hostname and full repository path; the PR creation tool is also fixed to the demo repository. These integration steps cannot be replaced by merely entering a bot name.

### 2.3 Enable sources, then define who may request work

After installing the adapted Bundle, open **Superagent → Settings → Sources** and enable Gitea and Mattermost. This demo polls them every 10 and 5 seconds respectively. It uses API polling; no Mattermost outgoing Webhook was configured for this path.

![Enabled custom sources and their polling intervals in DSH](../../assets/rag-agent/deepseek-superagent-practice/dsh-source-settings.jpg)

This page controls enabled state and polling frequency. URLs and tokens are read through the Secret and adapter above; the page has no URL or token input fields for these custom sources.

Next, open **Settings → Evaluation → Per-source policy** and configure allowed task initiators. Gitea allows the login `demo-admin`; Mattermost allows that demo user's ID. These identify the human requester, a different identity from the bot's own `botId`.

![Allowed task initiator for the Mattermost source](../../assets/rag-agent/deepseek-superagent-practice/dsh-mattermost-admission.jpg)

The screenshot permits one demo user. Admission remains in `observe` mode; valid explicit requests can still be accepted, so this does not disable all work. Execution capacity is set to two.

Finally, follow one small request through the complete path: read the channel message, create its Ticket and execution session, create a branch and PR in Gitea, and return the result to the original thread. A healthy source establishes polling health. These further checks establish that identity, tool execution, and delivery are connected too.

### 2.4 Preserve deduplication and reply semantics

One issue encountered in practice was Mattermost's `update_at`: reply-related metadata can change it too. Using `post.id + update_at` as the event identity caused an old request to be processed again. The corrected mapping uses the message ID and its body-edit version, `edit_at`; an actual body edit creates a new event.

```javascript
// Use the body-edit version, not a thread-metadata update.
const version = post.edit_at || 0;
const eventIdentity = `${post.id}:${version}`;
const threadIdentity = post.root_id || post.id;
```

Sends also need idempotency. Mattermost bot replies carry a receipt property; Gitea comments carry a hidden marker. A retry checks for that marker first. This controls duplicate sends in these adapters, not arbitrary external writes with strict exactly-once semantics.

## 3. How a person submits and follows work

In the demo channel, mention `@demo-agent` and specify scope and acceptance conditions. Reply in the same thread for follow-up changes so the original Ticket and PR are reused. In DSH, **Superagent → Execution** shows running, queued, waiting and reviewable tasks.

![Two running workers and a third task waiting in the queue](../../assets/rag-agent/deepseek-superagent-practice/execution.png)

*This is the actual control panel. Its Chinese labels show two of two workers running and one queued task: observed runtime state, not concurrency inferred from task counts.*

A small request can say: “Fix `src/pricing.js`, which does not multiply by `quantity`; add a quantity-greater-than-one test, run `npm test`, and create a PR for human review without merging.” Complex requests also need interfaces, persistence, failure handling and an explicit directory boundary. A coding request in chat does not authorize administration of the surrounding cluster.

Two states are easy to confuse: an agent turn ending does not establish delivery, and code generation ending does not establish passing tests. The final checks must include test output, the remote branch and PR, and a usable result in the original thread.

Global pause stops new assessments, dispatches and replies; it does not immediately terminate an already-running turn. Use the task-specific stop operation to stop a task. Emergency access revocation also requires revoking the relevant service-side credentials; the pause button is not a security master switch.

### 3.1 Open DSH to inspect what the task actually did

The task list shows orchestration state. To inspect execution, open the task's execution session from **Superagent → Execution**, switch to **Trace**, and search for a filename, tool name, or test output. The left side lists calls; opening one exposes parameters, results, and timing separately. The main Session handles admission and dispatch. File changes and tests belong in the task's execution Session.

For the log-analysis tool, searching the trace for `component_exit=0` locates the final `bash` test invocation. Its result retains actual command output rather than only a natural-language claim that tests passed.

![Actual component and repository test results in the DSH execution trace](../../assets/rag-agent/deepseek-superagent-practice/dsh-trace-tests.jpg)

The component command exited with 0 and passed 31 tests. The repository command also exited with 0 and passed 33 tests. The latter includes the 31 component tests and 2 existing tests; adding them into 64 tests would double-count. These are agent-run self-tests. The 6 independent acceptance groups below are recorded separately.

The trace also gives a concrete troubleshooting path. A request with no execution session points to admission or dispatch. Continued text generation without file-tool calls calls for inspection of the effective output budget. A test invocation returning nonzero calls for inspecting its command and failed output. Completed code and tests without a PR or thread reply require checking external writes and receipts. A zero exit code covers only the executed cases; assertions and independent acceptance still need review before judging product correctness.

The screenshot preserves real tool calls and output without presenting the model's internal reasoning as delivery evidence. The incomplete DAG task remains in the results below rather than disappearing because other work succeeded.

## 4. From a small fix to three multi-file projects

The initial smoke test fixed `totalPrice`, which did not multiply price by item quantity. The agent changed the implementation, added regression tests and opened PR #1. A follow-up in the original thread requested zero-quantity coverage. The DSH Pod was recreated during execution; recovery reused the original session, directory, branch and PR. The final actual test run passed all seven tests.

![Follow-up request and delivered result in the original conversation](../../assets/rag-agent/deepseek-superagent-practice/chat-result.png)

*The Chinese screenshot pixels remain original evidence. The first result had five tests; the follow-up had seven. The PR remained open for human review.*

To avoid judging the system from one small function, I then submitted three independent projects.

### 4.1 A reliable Webhook delivery service

Using Node.js built-ins and SQLite, implement an enqueue API, idempotency keys, bounded retries, a fixed delivery target, HMAC-SHA256 signatures and an operator page. Acceptance covers two failures before success, a permanent HTTP 400 response, malformed JSON, real signature verification and continued delivery after a service restart.

The important boundary is local queue idempotency versus network delivery semantics. Even one queued event can be received twice if execution stops after sending but before recording success. The requirements therefore include a stable event ID and documented receiver-side deduplication.

![The reliable Webhook service delivered as a real PR](../../assets/rag-agent/deepseek-superagent-practice/webhook-pr.png)

*PR #3 contains 15 files and three commits, ending at `8ba2da4`. This is a single-process demo without API authentication, TLS, multi-instance coordination or dead-event replay. It is not ready to operate as a production Webhook platform.*

### 4.2 A streaming log-analysis CLI

Read JSON Lines incrementally, with time bounds, service filtering, invalid-line handling, latency summaries and a directly viewable HTML report. Independent acceptance uses entirely synthetic records, including invalid timestamps, negative latency, a `__proto__` service name and HTML text requiring escaping. It also processes 100,000 records with bounded key cardinality under a 64 MiB Node heap limit.

That check establishes behavior only for the specified data distribution. Aggregation tables still grow with service, time-bucket and error-signature cardinality. Reading line by line does not imply constant memory for every input.

![The multi-file log-analysis tool delivered as a real Gitea PR](../../assets/rag-agent/deepseek-superagent-practice/complex-pr.png)

*Actual Gitea PR #2 contains 19 files and two commits, with head `66fc963`. The self-test report in the PR and the independent acceptance checks in this article are recorded separately.*

![Actual HTML produced by the agent's CLI from one hundred thousand synthetic logs](../../assets/rag-agent/deepseek-superagent-practice/logscope-report.png)

*This is an actual CLI output, not an article mockup. The 100,000 synthetic records contain 5,000 errors and have a mean latency of 144.50 ms. [Open the full HTML report](../../assets/rag-agent/deepseek-superagent-practice/logscope-report.html). These are synthetic input statistics, not production-load measurements.*

### 4.3 A durable DAG task runner

A Directed Acyclic Graph (DAG) describes task dependencies. The runner must validate cycles and unknown dependencies, enforce concurrency, retry failures or timeouts within a limit, persist state in SQLite and resume after a real process termination.

The predefined acceptance plan records child-process start and end timestamps to check overlap and dependency ordering. It also checks that a failed branch blocks descendants without skipping independent branches. Recovery must not rerun succeeded tasks, and a changed configuration must not reuse incompatible state. Because no DAG implementation was delivered in this run, these checks were not executed. Application-workflow recovery and Super-agent session recovery are two separate layers.

### 4.4 Final delivery, beyond a “completed” label

| Task | Final code and PR | Actual component tests | Independent acceptance |
| --- | --- | --- | --- |
| Webhook delivery service | PR #3, `8ba2da4`, 15 files | 11 / 11 passed | 5 / 5 groups passed |
| Log-analysis CLI | PR #2, `66fc963`, 19 files | 31 / 31 passed | 6 / 6 groups passed |
| DAG task runner | No implementation or PR at the deadline; stopped | Not run | 5 predefined groups not run |

The independent checks were written outside the agent's delivered code and actually launched HTTP receivers, services or CLIs. Asking the agent whether tests passed is insufficient. Webhook acceptance was rerun on its final commit; the log-analysis workspace commit matched the remote PR. Both PRs remain open; their changes have not been merged into the demo repository's main branch.

The first log-analysis acceptance run passed 5 / 6 groups: the oracle compared a floating-point average strictly to `49.5`, while the actual result was `49.500000000000036`. After preserving that failure, only the oracle was changed to a `1e-9` tolerance. Product code did not change, and the second run passed 6 / 6. This is an oracle correction, not a product bug fix; the failed run must remain visible. [Sanitized acceptance summary and code identifiers](../../assets/rag-agent/deepseek-superagent-practice/acceptance.json)

After the original Webhook and DAG execution windows timed out and were stopped, continuation requests in the original chat threads created new Tickets and working directories. This differs from the pricing-function recovery: the same chat thread does not imply reuse of a stopped Ticket. The new DAG attempt still repeatedly reached its output limit. The supervisor stopped it at the end of a 20-minute retry window, without fabricating a delivery or continuing indefinitely.

![Final control panel showing deliverables awaiting human review](../../assets/rag-agent/deepseek-superagent-practice/final-overview.png)

*The three reviewable entries are the initial small fix and the two complex projects. The stopped DAG Ticket is absent from the open list; this screenshot does not mean all three complex projects succeeded.*

## 5. Complex work exposed a transport failure that short tasks missed

In the first attempt, both long requests ended at exactly 300 seconds. DSH logged `Stream ended without finish_reason` and retried. Work had been authorized and workers created, but no implementation files had been written. Looking only at two active workers would have mistaken the failure for normal progress.

The issue was in this demo's office-side bridge. It imposed a fixed five-minute total timeout while synchronously returning each small Server-Sent Events (SSE) chunk. On a path using port forwarding, every return required another network round trip, adding delay to generation.

The repair had three parts:

1. Aggregate returned bytes over roughly 50 ms or up to 64 KiB, preserving the original stream rather than parsing or rewriting model messages.
2. Distinguish a progressing stream from an idle one: this demo uses a 180-second idle deadline and a 15-minute total deadline, plus a separate experiment deadline.
3. Abort incomplete HTTP bodies on timeout so the caller sees a failure; do not present a stream missing its terminal marker as a normal completion.

The failed attempt and before/after settings were retained. Four tunnel tests and three buffering tests were added. This was a demo-bridge defect, not an upstream Super-agent or model failure. The repaired end-to-end duration cannot be presented as a model-performance gain.

Two other tasks ended with `max-tokens` after exactly 8,192 output tokens without issuing a code tool call. After preserving that incomplete state, I sent explicit `thinking: {type: "disabled"}` and a 32,768-token budget to the real API. A minimal probe returned a tool call, and those overrides were added to the bridge. However, the subsequent full DAG sessions still recorded 8,192 output tokens and `max-tokens`. The minimal probe does not establish that the full path adopted the new mode. The next step is to inspect effective parameters and limits across DSH, the bridge and upstream, rather than repeatedly requesting continuation. This also does not establish that the model cannot implement a DAG. [DeepSeek thinking-mode parameters](https://api-docs.deepseek.com/guides/thinking_mode/)

Recovery also exposed an interaction boundary. Records and working directories were restored, but the main session requested status, and workers ended their turns after obeying that status-only request without finishing implementation. Upstream explicitly defines status requests as not resuming implementation. This run used explicit follow-ups in the original threads to continue. Recovery validation therefore needs to cover dispatch and conversation semantics as well as storage. [The status-query boundary](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/6337fc823ce20251c8de8085948165c81aaa701e/src/core/tickets.ts)

## 6. Why the pages briefly became unreachable

The demo UI is reached through `kubectl port-forward` on the office machine. Office-to-Kubernetes-API timeouts once disconnected the Gitea and Mattermost forwards while the cluster Pods had not restarted. The supervisor detected exited forward processes, reconnected them and restored successful health checks.

Check the browser, forwarding process, Kubernetes API, Pod and model path separately. A listening port does not establish a healthy page; a healthy page does not establish model connectivity. DSH returning 401 without login credentials indicates working authentication and is not enough by itself to diagnose a service failure.

A `127.0.0.1` entry belongs only to the computer running the forwards. Sleep or network loss on that computer still interrupts access. Long-term multi-user operation needs an authenticated stable entry and an appropriate model-access path from the cluster. This experiment did not modify the existing cluster's CNI, routes or DNS to work around connectivity.

## 7. What this validates and what remains

| Layer | Evidence obtained | Boundary |
| --- | --- | --- |
| Integration and orchestration | 1,197 existing regression tests and 5 CLI adapter tests passed; two running tasks and one queued task were observed | Custom adapters, not an upstream product commitment for this IM/forge pair |
| Small-task recovery | DSH Pod recreation retained the original pricing task and PR; 7 tests passed | Same test node and retained volume |
| Complex code delivery | Two multi-file projects, 42 component tests and 11 independent acceptance groups passed | Synthetic data; the third project was not delivered and its 5 groups were not run |
| Transport repair | 4 tunnel tests and 5 office-worker tests passed | Includes 3 buffering and 2 option-override unit tests; does not prove every model option is effective end to end |
| External changes | PR #1, #2 and #3 remain unmerged; main was not modified | Real-team merge, release and rollback workflows remain untested |

These counts belong to different layers and are not summed into an overall success rate. The next priority is observing effective full-session parameters, then rerunning the DAG within a defined budget. Before adding execution slots, eliminate work that is idle while appearing active.

The demo lets a person assign work in chat, follow tasks in a control panel, inspect code and test evidence in Gitea, and request revisions in the original thread. It validates an engineering path under the specified versions, synthetic tasks and authorization boundary.

Orchestration remains single-instance. The experiment did not validate database or disk loss, node power failure, cross-machine recovery or concurrent writers, and it does not provide strong per-task isolation for malicious code. Separate DSH sessions and directories are not substitutes for container or VM sandboxes. Before connecting real teams, define identity, repository permissions, execution isolation, audit, backups and reconciliation of external state after failures.

## References

- [DeepSeek Super-agent prototype and research disclaimer](https://github.com/deepseek-ai/dsh-superagent-prototype)
- [Source and Channel extension cookbook](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/6337fc823ce20251c8de8085948165c81aaa701e/docs/008-cookbook.md)
- [Execution, pause and recovery](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/6337fc823ce20251c8de8085948165c81aaa701e/docs/003-execution.md)
- [DeepSeek Harness Docker image and Kubernetes Chart](https://github.com/runzhliu/deepseek-harness-docker)
- [Earlier source analysis](deepseek-superagent-prototype-analysis.md)
