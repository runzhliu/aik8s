---
title: "Principles and Community Practice of Agent Long-Task Interruption and Resumption"
description: "Explains how hour-long agent tasks recover after process crashes, network disconnects, and manual pauses, comparing LangGraph, Temporal, Restate, DBOS, Mastra, and session recovery, with reproducible interruption experiments and Kubernetes architecture recommendations"
status: evolving
last_reviewed: 2026-10-14
---

# Principles and Community Practice of Agent Long-Task Interruption and Resumption

To keep an agent working continuously for an hour, what really needs to be solved is: after a process disappears, can another process know the goal, the work already completed, the operations not yet confirmed, and what the next step should be.

**Interrupted task resumption is achievable, and the community already has corresponding frameworks. What is typically recovered is the task state and execution steps, not the internal state of a model inference halfway through.** Saved results can be reused; steps currently in execution may be re-run; if they write to a database, create tickets, or publish content, idempotency and result verification are also required.

This involves three mutually supporting parts: the workflow saves progress, the Harness (agent runtime and governance layer) rebuilds the model context, and the tools and execution environment retain queryable results. Saving only chat history, configuring automatic Pod restarts, or extending interface timeouts cannot fully solve this.

## 1. What Is Lost When an Hour-Long Task Is Interrupted at Minute 37

Assume a code refactoring task is expected to take one hour: first analyze the repository, gather materials, modify code, then run tests, review, and deliver. The times below are scenario illustrations, not performance test results.

| Phase | Illustrative Time | Recovery Basis That Should Remain |
| --- | --- | --- |
| Clarify goals and acceptance criteria | 0–5 minutes | Task description, constraints, acceptance checklist |
| Gather materials and analyze repository | 5–20 minutes | Material sources, file locations, verified conclusions |
| Modify code | 20–32 minutes | Workspace files, Git Diff or Commit, artifact hashes |
| Run tests | 32–40 minutes | Test task ID, parameters, logs, exit codes |
| Review and supplement | 40–50 minutes | Review findings, fix records, re-verification results |
| Deliver | 50–60 minutes | Final artifacts, acceptance results, delivery receipt |

![Recovery position after an hour-long task is interrupted at minute 37](../../assets/rag-agent/agent-durable-execution/recovery-boundary.png)

If the Worker crashes at minute 37, the recovery process should first confirm whether the files and state from minute 32 were reliably saved, then verify the test task: if still running, re-attach; if already finished, read the results; only re-run if the task itself has also disappeared and duplicate execution is permitted.

It must not proceed directly to the delivery phase based on a statement like "I am testing," nor should it default to restarting from repository analysis. **The recovery position is determined by persistent state and actual results, not by the last piece of natural language description.**

## 2. Four Recovery Capabilities Must Not Be Conflated

| Layer | What Is Recovered | Typical Implementation | Boundary |
| --- | --- | --- | --- |
| Session recovery | Messages, recorded tool results, current goal | Session database, JSONL logs, session Resume | Does not automatically recover terminal processes or external business state |
| Workflow recovery | Committed steps, next step, waiting conditions | Checkpoint, event history, Durable Workflow | Steps in execution but not yet committed may re-run |
| Working environment recovery | Repository, files, dependencies, browser configuration | Persistent volumes, object storage, environment manifests, sandbox snapshots | File existence does not mean the original process is still alive; logins may expire |
| Execution site recovery | Memory, processes, and partial system state | Dedicated process or VM snapshot mechanisms | External connections, locks, and credentials still need re-verification |

Checkpoint refers to a checkpoint, and Durable Execution refers to durable execution: execution state is saved independently of the lifecycle of any single Worker, allowing the program to continue after a failure.

Saving the complete session helps the model understand what happened before, but task recovery also requires structured state. Long-term memory is suitable for saving preferences, experience, and knowledge, but it cannot replace the execution ledger that records "whether this operation has been completed." For the difference between the two, see the [Agent Memory technical survey](agent-memory-technology-overview.md).

If an interruption occurs during the streaming output of a model request, the request typically needs to be re-issued, or a request-result query mechanism explicitly supported by the provider must be used. Partial output should not be directly counted as complete tool parameters or complete conclusions. KV Cache, model request internal state, and task Checkpoints belong to different layers.

## 3. What Information a Resumable Task Needs to Save

A practical task record should at minimum be able to answer the following questions.

| Information | Purpose |
| --- | --- |
| `tenant_id`, `run_id`, goal and acceptance criteria | Determine ownership and task identity; it remains the same task after restart |
| Step ID, status, input hash, and output reference | Distinguish completed, failed, waiting, and unknown-result states |
| Original tool calls, results, business receipts | Rebuild facts; avoid treating model speculation as execution results |
| Workspace version and artifact hashes | Locate files corresponding to the checkpoint; detect workspace modifications |
| Tool version, workflow version, model configuration | Prevent old tasks from being directly taken over by incompatible new code |
| Retry count, cost, and total deadline | Continue using the original budget upon recovery rather than receiving a new budget |
| External task ID, approval records, cancellation status | Query still-running work and preserve user control |
| Worker lease and execution generation | Prevent two recovery processes from handling the same task simultaneously |

This information does not necessarily need to be stored in one giant JSON. Steps and receipts can go in a database, large files in object storage, code in the workspace and version control, and checkpoints only save references and hashes.

The recovery process can proceed in the following order:

1. Load the task; first check cancellation, permissions, deadline, and remaining budget.
2. Validate workflow version and workspace version, then acquire the task lease.
3. Reuse results of committed steps and reconstruct the model-visible context.
4. For tool calls still in execution or with unknown results, query and verify first.
5. Retry only steps that comply with the rules; commit new results before proceeding to the next step.
6. Deliver according to acceptance criteria; record final artifacts and delivery receipts.

Here, "completed" should mean the result has been durably committed. A success flag in Worker memory, completion text in logs, or the model saying "done" cannot alone carry this meaning.

## 4. What Implementations Already Exist in the Community

### 4.1 LangGraph Recovers Graph State Through Checkpoints

LangGraph's Checkpointer saves the graph state of a Thread, supporting error recovery, human interruption, and continued execution. Here, Thread is a state-ownership identifier, not an OS thread; the same Thread can have multiple executions. A Super-step is one round of graph scheduling and may contain parallel nodes; complete checkpoints are located at its boundaries. Successfully persisted outputs of nodes can also be used for fault recovery within the same round; this cannot be simply understood as "if one parallel task fails, everything re-runs." [LangGraph Checkpointers](https://docs.langchain.com/oss/python/langgraph/checkpointers)

It also provides different persistence modes:

| Mode | Commit Timing | Impact on Crash Recovery |
| --- | --- | --- |
| `sync` | Synchronously saved before advancing to the next step | Reduces the progress-loss window but adds storage latency |
| `async` | Saving overlaps with subsequent execution | Sudden process disappearance may lose progress not yet persisted |
| `exit` | Saved on normal exit, error exit, or human interruption | Hard crashes during execution may lose intermediate progress |

For long tasks that need protection against crashes during execution, the persistence strategy should be explicitly chosen. `sync` still cannot eliminate the window where "the external tool has executed but the graph result has not yet been saved"; Section 5 handles this separately. [Persistence modes](https://docs.langchain.com/oss/python/langgraph/checkpointers#durability-modes)

The storage must also be chosen correctly: `InMemorySaver` loses state after process restart; SQLite is suitable for local demos, while production multi-Worker deployments typically choose persistent backends such as PostgreSQL. When recovering the same task, the original `thread_id` must be reused, and access permissions for that task must be re-acquired. [LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)

### 4.2 Temporal Recovers Orchestration Through Event History

Temporal places orchestration logic in Workflow and model, tool, and other external calls in Activity. On recovery, the Workflow is rebuilt from event history rather than re-requesting the model each time to guess the previous progress. This approach suits long waits, multi-step business processes, and cross-service tasks. [Temporal Durable AI](https://docs.temporal.io/ai)

Activity executions may be retried after failure, so the external side effects they produce still require idempotency. Long-running Activities can report progress using Heartbeat, but how to continue processing using that progress after a retry must still be implemented by the Activity. Do not wrap an entire hour-long agent loop into a single Activity with no internal progress and expect the framework to automatically recover each of its tool calls. [Activity Execution](https://docs.temporal.io/activity-execution), [Long-running Activity patterns](https://docs.temporal.io/ai)

The replayable portion of a Workflow must satisfy the framework's determinism requirements; model calls, current time, random numbers, and external network access should use the execution boundaries permitted by the framework. Reusing existing results can avoid regenerating different model decisions. [Workflow determinism constraints](https://docs.temporal.io/workflow-definition#deterministic-constraints)

In the task platform's records, changing model or tool parameters and then executing should be recorded as a new attempt or branch.

### 4.3 Restate Records Call Results in a Persistent Journal

Restate uses a Journal to record execution steps and continues execution through replay after process replacement. It provides Agent SDK integration, key-managed state, and persistent waiting primitives, connecting models, tools, and approvals. Its official examples already demonstrate persistent combinations of model calls, tool calls, and waiting for approval. [Restate Agent integration practice](https://restate.dev/blog/durable-orchestration-for-ai-agents-with-restate-and-openai-sdk)

When using it, actions whose results need to be saved must be placed inside its persistent execution interface. Executing writes outside the interface, or encapsulating a long chain of side effects into a single non-queryable step, still leaves a window for duplicate operations.

### 4.4 DBOS Records Step Execution in a Database

DBOS uses Workflow and Step to save execution progress and reuses results of completed steps upon recovery. It explicitly distinguishes Step from supported database Transactions: incomplete Steps may be retried, and database transaction guarantees cannot be generalized to arbitrary remote HTTP write operations. Unhandled exceptions put the Workflow into an error state, which does not mean all errors automatically resume. [DBOS Workflows](https://docs.dbos.dev/python/tutorials/workflow-tutorial)

This route suits teams that want to introduce durable execution with application code and a database at the core. When selecting, database availability, version upgrade methods, and ownership management of recovered tasks still need to be evaluated.

### 4.5 Mastra Must Distinguish Approval Pauses from Crash Recovery

Mastra provides Durable Agent and pause/resume capabilities, but the default `recovery.durableAgents: 'off'` in the current documentation does not enable automatic crash recovery for running tasks. Enabling `'auto'` or configuring a persistence strategy containing `running` is what involves the corresponding runtime checkpoints and recovery paths; the storage must also be a persistent backend. [Mastra Durable Agents](https://mastra.ai/docs/harness/durable-agents)

Recovery may re-execute model and tool calls. An action delegated to a sub-agent may also be saved only as a single outer tool step, so replay re-runs the entire sub-agent. **Being able to Resume after human approval is not sufficient proof that arbitrary hard crashes can be safely recovered.**

### 4.6 Pydantic AI Can Connect to Durable Execution Engines

Pydantic AI already provides durable execution integrations with Temporal, DBOS, Prefect, Restate, and others, placing model requests and tool calls into the execution units of the corresponding engine. It also explicitly distinguishes chat history persistence from crash recovery of a single Run. [Pydantic AI Durable Execution](https://pydantic.dev/docs/ai/capabilities/durable_execution/overview/)

Frameworks can be composed in layers, but two engines should not retry the same side effect simultaneously without design. A reliable composition approach: the outer layer handles business phases and approvals, and the inner layer handles the agent loop within a phase; clarify who records results, who handles timeouts, and who owns the retry budget.

### 4.7 How to Choose

The table below is an engineering selection recommendation based on the execution models above, not a throughput or reliability ranking.

| Requirement | Priority Evaluation | Key Checks Before Adoption |
| --- | --- | --- |
| Existing Python graph-based agent, adding step recovery | LangGraph + persistent Checkpointer | Node granularity, save modes, idempotency of external writes |
| Business processes of one hour or more, including approvals and cross-service coordination | Temporal | Activity partitioning, timeouts, retries, and version compatibility |
| Combining service calls, key-managed state, and persistent waiting | Restate | Journal boundaries, service versions, tool receipts |
| Want to introduce durable execution with application libraries and a database | DBOS | Boundary between Step and transactions, exception classification, recovery ownership |
| TypeScript agent product, already using Mastra | Mastra Durable Agents | Persistent storage, actual recovery switches, sub-agent granularity |
| Already using Pydantic AI | Corresponding durable execution integration | Choose one execution engine and verify its actual semantics |

## 5. The Hardest Window Is When the Tool Has Succeeded but the Agent Has Not Yet Recorded It

For example, the tool has already created a ticket, and the Worker crashes before saving the tool result. The recovered checkpoint does not contain this ticket, and a direct retry may create a second one.

This is the commit window between the caller and the external system. **Having an event log and checkpoints does not mean remote side effects execute exactly once.**

The following operation record can be used:

```text
action_id       同一业务动作的稳定标识
request_hash    参数内容的哈希
status          PREPARED / IN_FLIGHT / SUCCEEDED / UNKNOWN
provider_id     外部工单、作业或草稿 ID
receipt         可核验的返回值与证据
```

`action_id` must remain unchanged across retries of the same action and must not contain newly generated random numbers or Attempt numbers. When the external system supports idempotency keys, call repeatedly with the same key and obtain the original result; when the same key corresponds to different parameters, refuse execution.

When the external system has no idempotency interface, a business verification adapter is needed: query status by the saved task ID, look up results by unique business markers, or use the request records provided by the external system. If "the request never arrived" cannot be distinguished from "the request succeeded but the response was lost," record `UNKNOWN` and wait for verification rather than automatically treating a timeout as failure.

Model requests have a similar window: the provider has already generated and billed, but the response has not yet been saved. Without request query or deduplication capabilities, a retry may generate and bill again. A task can be recovered, but that does not mean all model costs occur only once.

A transactional Outbox can reliably save "actions pending sending," but it cannot alone guarantee that the external system executes only once. Consumers still need idempotency or verification on redelivery. Only within boundaries controllable by the same transaction is it possible to commit business writes and result registration together.

For generated artifacts, the typical approach is to write a temporary object first, verify the hash, and then update the final reference. For side effects such as sending notifications, publishing content, and payments, the corresponding system's receipts and authorization rules must be used; success cannot be judged from a file or a single log entry alone.

## 6. Local Experiment Demonstrating Actual Recovery Boundaries

The accompanying [reproducible experiment code](https://github.com/runzhliu/aik8s/tree/main/examples/agent-durable-resume) uses LangGraph, SQLite checkpoints, and a simulated tool service. It does not call a large model and does not access production systems.

The flow has only three nodes: `plan → write_draft → finish`. The simulated tool service uses a separate SQLite database to save action keys and receipts, completing the write and registration within the same transaction. The experiment terminates the process directly via `os._exit(86)`, bypassing normal shutdown, and a new process then reads the same Thread to recover.

Test versions are LangGraph **1.2.15**, langgraph-checkpoint **4.3.0**, SQLite Checkpointer **3.1.2**, using `durability="sync"`.

| Interruption Position | First Exit Code | Tool Result Count at Interruption | Cumulative Node Execution Count After Recovery | Tool Result Count After Recovery |
| --- | --- | --- | --- | --- |
| Before the tool actually writes | 86 | 0 | plan 1 / write_draft 2 / finish 1 | 1 |
| Tool write committed, graph result not committed | 86 | 1 | plan 1 / write_draft 2 / finish 1 | 1 |

The actual log for the second scenario is:

```text
# 第一个进程
EXECUTE plan
EXECUTE write_draft
TOOL committed receipt draft-7854be0b31d5
CRASH after effect commit, before graph checkpoint

# 恢复进程
EXECUTE write_draft
TOOL reuse receipt draft-7854be0b31d5
EXECUTE finish
```

`plan` was not re-run; `write_draft` was re-run once, and the simulation tool used a stable action key to return the old receipt. Finally, a completed Run was restored again, and no nodes were re-executed.

This verifies the boundary that "steps can be re-run, but business results must be deduplicated." The simulation service can place the write and the receipt in the same SQLite transaction; a real remote interface must provide an equivalent guarantee on its own, or the caller must verify. This short experiment does not prove recovery capability for one-hour runs, node failures, or real business services.

Running the full verification:

```bash
uv run --python 3.12 \
  --with-requirements examples/agent-durable-resume/requirements.txt \
  python examples/agent-durable-resume/verify.py
```

The core recovery call is as follows; creating a new input or a new Thread is not the same thing as continuing the original execution.

```python
config = {"configurable": {"thread_id": original_run_id}}

with SqliteSaver.from_conn_string("checkpoints.sqlite") as saver:
    graph = builder.compile(checkpointer=saver)
    snapshot = graph.get_state(config)
    if snapshot.next:
        graph.invoke(None, config, durability="sync")
```

## 7. What Session Recovery Can Do in Pi, OpenClaw, DSH, and Hermes

Personal agents and coding assistants already have a fair amount of session continuation practice, but you should check the specific version and execution backend.

| Project | Capability in current documentation | Long tasks still need verification |
| --- | --- | --- |
| Pi | Saves tree-structured JSONL sessions per working directory; continues via `pi -c`, `pi -r`, or a specified Session | Whether files still exist, whether running commands have finished, whether external tools are called repeatedly |
| Hermes Agent | SQLite saves sessions; loads history via `hermes -c` or `--resume`, restoring session information such as the working directory | Whether long commands and external tasks can be re-attached, whether tool results have already been confirmed |
| OpenClaw | Gateway holds session state; documentation describes automatically attempting to continue an interrupted Turn after restart, retaining recorded tool calls and results | Recovery budget, backend capabilities, permission re-verification, and the actual state of unfinished tools |
| DeepSeek Harness | Distinguishes persistent Session events from real-time control events; recorded facts are used to rebuild sessions | The state directory retained by the deployment, the recovery trigger method, and the lifecycle of tools and sandboxes |

References: [Pi Sessions](https://github.com/earendil-works/pi/tree/main/packages/coding-agent#sessions), [Hermes Sessions](https://hermes-agent.nousresearch.com/docs/user-guide/sessions), [OpenClaw Session source documentation](https://github.com/openclaw/openclaw/blob/main/docs/concepts/session.md), [DeepSeek Harness Agent lifecycle](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/agent-lifecycle.zh.md).

In particular, OpenClaw should not be summarized as "can only recover chat history": the current documentation explicitly includes Gateway restart recovery. However, this still cannot replace business verification of a given tool; a recovery system knows that a tool call was interrupted, but not necessarily whether the external service has already completed it.

A low-cost improvement when running long tasks on these assistants is to maintain structured progress: goals, verified steps, current file versions, running task IDs, failure reasons, and next actions. For changes to the same repository, use Git and test results as evidence rather than relying only on conversation summaries.

Anthropic's long-task Harness practice uses an initialization phase followed by incremental execution phases, combined with a feature list, progress files, Git records, and end-to-end tests, to help a new session continue the work. It mainly addresses handoff across context windows, not a general-purpose business-side-effect deduplication protocol. [Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)

## 8. Long Tool Calls Should Be Re-Attachable

If a tool internally runs a forty-minute build or test, and the workflow only saves state after the tool returns, there is still a forty-minute recovery blind spot.

An interface better suited to long operations can be split into three actions:

```text
submit(parameters, action_id) → external_job_id
get_status(external_job_id) → queued / running / completed / failed
get_result(external_job_id) → logs / artifacts / exit_code
```

The submission interface should also be idempotent or support lookup; otherwise, the window of "external job already started, Job ID not yet saved" still exists. After an agent restart, query the old job rather than automatically creating a new one.

For batch processing, the tool can save a Cursor by completed shard; after recovery, continue from the last reliable shard. Calling Heartbeat merely to report "still alive" is not enough; progress data needs to explicitly include which shards have been committed.

`nohup` or `tmux` can keep a process from exiting when the terminal disconnects, but they cannot cover node restarts, container disappearance, or workspace loss. Sandbox snapshots should also not be treated as a guarantee that all external connections can be restored. For critical operations, you still need to be able to read results and verify external state.

## 9. How to Host Recoverable Agents on Kubernetes

The following is a platform architecture recommendation; the core idea is to place task identity, progress, and artifacts outside the Worker Pod.

![Responsibility split for recoverable agents on Kubernetes](../../assets/rag-agent/agent-durable-execution/kubernetes-architecture.png)

| Component | What it saves or processes | Responsibility after failure |
| --- | --- | --- |
| Task API | Task creation, ownership, cancellation, query | Returns a stable Run ID; the same task can still be queried after a browser reconnect |
| Durable execution engine | Steps, waits, queues, retry rules | Detects interruption and reschedules according to saved state |
| Agent Worker | Context construction, model and tool calls | Can be replaced; does not bear sole state storage |
| Durable database | Checkpoints, receipts, budgets, ownership | Availability, backup, and recovery determine the basis for continuation |
| Workspace and artifact storage | Repositories, outputs, logs, environment manifests | Provides file versions consistent with checkpoints |
| External tool execution surface | Long jobs, sandboxes, browsers, business writes | Provides task IDs, queries, deduplication, and cleanup |

### 9.1 Page Disconnect Should Not Cancel Backend Tasks

A one-hour task should not depend on an HTTP request that lasts one hour. After task creation, return `run_id`; the page displays progress via queries or event streams. A connection drop only means losing the observation connection. Whether to cancel is decided through a separate cancellation interface.

Event stream reconnection can use persistent event sequence numbers to retrieve missed events. The page seeing old logs and the Worker being able to continue execution are two different capabilities and should be accepted separately.

### 9.2 Persistent Volumes Save Files, Not Ordinary Processes

A PersistentVolumeClaim (PVC) can help preserve the working directory, but an ordinary container's processes, memory, and TCP connections do not automatically recover when the volume is remounted. When an execution environment is needed, use rebuildable images and dependency manifests; when continuing a long job is needed, retain the independent job identity and query interface.

`emptyDir` cannot serve as the sole recovery storage. The SQLite file demonstration should also not be directly extended into a production design where multiple Workers share a single file lock. Multi-Worker systems are better suited to database backends that support concurrency and transactions, with versioning and retention policies for artifacts.

### 9.3 A Task Can Have Only One Valid Execution Owner

During a network partition, the old Worker may still be executing while a new Worker starts recovery. Leases handle claim and expiry determination, but should be combined with an execution generation or Fencing Token: for example, the old executor holds generation 3, the new executor obtains generation 4, and the write side rejects generation 3 writes. Critical side effects continue to use stable action keys.

Adding only an `running=true` in the database, or relying only on ReadWriteOnce (RWO, single-node read-write mount) storage volumes, is not sufficient protection for business actions. Multiple Pods on the same node can still access an RWO volume. [Kubernetes storage access modes](https://kubernetes.io/docs/concepts/storage/persistent-volumes/#access-modes)

Database records and external tools must know who owns the current execution right, or at least be able to prevent duplicate effects.

### 9.4 Rolling Upgrades Should Preserve Execution Semantics for Old Tasks

During ordered termination, stop accepting new tasks, attempt to save progress at safe boundaries, and reserve time for normal shutdown. But a hard crash gives the program no opportunity to run exit callbacks; recovery capability must hold even without callbacks.

Old tasks should retain the versions of workflows, tools, and state schemas. When a new Worker is incompatible, route old tasks to old-version Workers, or implement explicit state migration; do not retry replay errors indefinitely.

## 10. Which Interruptions Can Automatically Continue

| Cause | Handling |
| --- | --- |
| Page closed, browser offline | Backend continues; client reconnects to the same Run |
| Rate limiting or transient network failure | Bounded retries with backoff within step deadlines and total budget |
| Worker reclaimed, Pod or node failure | New executor takes over, verifies workspace and unconfirmed tools, then resumes |
| Credentials expired, permissions revoked | Wait for repair or authorization; retries cannot bypass permissions |
| Human approval | Save the waiting state; continue after approval is valid and bound to the original parameters |
| User explicitly stops or cancels | Keep an auditable state; do not treat cancellation as a failure to auto-restart |
| Budget or total deadline exhausted | End or wait for a new budget; do not reset to zero after restart |
| External operation result unknown | Query and verify; manual handling if necessary |

Approval should not be just a "yes" written into the chat log. It should at minimum bind the subject, action parameters, target resource, and validity scope; after parameter changes, permission changes, or approval expiry, authorization should be re-evaluated. Recovery permissions should also not exceed the original execution permissions.

For long jobs already cancelled by the user, also distinguish between "cancellation request sent" and "external job stopped." Only after confirming the job is stopped or completed can its execution resources be safely cleaned up.

## 11. How to Evaluate Recovery Capability

You can inject failures at different boundaries for the same task and compare the final result, the reuse of completed work, and the number of side effects.

| Failure injection point | Expected observation |
| --- | --- |
| Force process termination after a completed node | Committed results are reused; materials are not re-analyzed |
| Process terminates after external write succeeds but before saving the result | Retry does not produce a second business result, or enters a verification state |
| Worker terminated during a long test run | New Worker looks up the original test task, then re-attaches or reads the result |
| Restart during a human approval wait | The wait still exists; restart is not mistaken for approval |
| Recovery after permission revocation or target parameter changes | Old authorization cannot drive new actions |
| Two Workers claim the same task simultaneously | Only one valid owner; duplicate effects are protected against |
| Workspace files do not match the checkpoint | Inconsistency is detected; repair or block progress per explicit rules |
| A completed task receives a recovery request again | Return the existing result; do not re-execute the delivery action |

The platform dashboard can include recovery success rate, recovery wait time, number of repeated steps, number of unknown results, checkpoint write failures, retry costs, and orphaned job count. These are suggested metric definitions and need to be implemented in your own task platform.

The denominator of the recovery success rate should include tasks that triggered recovery; tasks that do not meet automatic recovery conditions should be categorized separately. Tokens and tool costs already consumed should be attributed back to the original Run, not shown only for the last successful attempt.

Distributed tracing can help track the execution of the same Run across different Workers and Attempts, but it should not serve as the recovery database: sampling, retention periods, and asynchronous writes can make trace records incomplete. `run_id` can go into logs and traces, but unbounded high cardinality should be avoided in metric labels.

## 12. Incremental Migration from Existing Agents

For single-user Pi, Hermes, OpenClaw, or DSH, you can first ensure session and workspace persistence, maintain progress files and acceptance lists, and convert long-running Shell operations into queryable tasks. During recovery, first check diffs, job status, and receipts, then let the model propose the next step.

For teams that already have multi-step applications, you can further introduce LangGraph or the durable execution mechanisms of existing frameworks, define the save granularity explicitly, and add stable action keys and result verification to all write tools.

For enterprise multi-user platforms, long waits, cross-service operations, and Worker scheduling can be handed to durable execution systems such as Temporal, Restate, or DBOS; at the same time, manage tenant permissions, budgets, versions, cancellation, and artifact lifecycle. The model is responsible for understanding and decision-making; the platform is responsible for saving facts and advancing tasks safely.

The most valuable verification for judging whether a solution suits one-hour tasks is: **terminate the process at the hardest commit window, switch to a different Worker, and still get the correct final result without duplicating business effects.**

## References

- [LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- [LangGraph Checkpointers and persistence modes](https://docs.langchain.com/oss/python/langgraph/checkpointers)
- [Temporal Durable AI](https://docs.temporal.io/ai)
- [Temporal Activity Execution](https://docs.temporal.io/activity-execution)
- [Temporal Workflow determinism and version constraints](https://docs.temporal.io/workflow-definition)
- [Restate Agent integration practice](https://restate.dev/blog/durable-orchestration-for-ai-agents-with-restate-and-openai-sdk)
- [DBOS Workflows](https://docs.dbos.dev/python/tutorials/workflow-tutorial)
- [Mastra Durable Agents](https://mastra.ai/docs/harness/durable-agents)
- [Pydantic AI Durable Execution](https://pydantic.dev/docs/ai/capabilities/durable_execution/overview/)
- [Anthropic long-task Harness practice](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)
- [OpenClaw Session documentation](https://github.com/openclaw/openclaw/blob/main/docs/concepts/session.md)
- [Pi Coding Agent](https://github.com/earendil-works/pi/tree/main/packages/coding-agent)
- [Hermes Sessions](https://hermes-agent.nousresearch.com/docs/user-guide/sessions)
- [DeepSeek Harness Agent lifecycle](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/agent-lifecycle.zh.md)
- [Kubernetes persistent volume access modes](https://kubernetes.io/docs/concepts/storage/persistent-volumes/#access-modes)

Further reading: [Agent Harness technical survey](agent-harness-technology-overview.md), [Agent Memory technical survey](agent-memory-technology-overview.md), [Agent evaluation methodology survey](agent-evaluation-overview.md).
