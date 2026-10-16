---
title: "Harbor Agent Evaluation Framework Overview: From Sandbox Tasks, Verifier to Large-Scale Rollout"
description: "Systematically introduces how Harbor unifies tasks, Agents, models, isolated environments, verifiers, and trajectories, analyzes its boundaries with Agent Harness, Inspect AI, SWE-bench, LangGraph, and Langfuse, and provides a Kubernetes production deployment solution"
status: evolving
last_reviewed: 2026-09-23
---

# Harbor Agent Evaluation Framework Overview: From Sandbox Tasks, Verifier to Large-Scale Rollout

The **Harbor** discussed in this article is the Agent evaluation and optimization framework open-sourced by the Terminal-Bench team, not the CNCF container registry Harbor. The problem it aims to solve is: how to put Claude Code, Codex CLI, OpenHands, or self-developed Agents into a reproducible environment, have them complete the same set of real tasks, then use independent programs to check the results, while preserving trajectories, logs, artifacts, and rewards.

This adds several layers of engineering constraints beyond "give the model a question and judge whether the answer is similar." Agents execute Shell commands, modify files, start services, access browsers, or call external tools; the final answer is only a small part of the process. What truly needs to be scored is the **complete system composed of the Agent, model, environment, and task contract**.

The [Harbor official repository](https://github.com/harbor-framework/harbor) positions the project as a framework for evaluating and optimizing Agents in container environments; the [official core concepts](https://www.harborframework.com/docs/core-concepts) lists local containers and multiple remote environment providers; [Harbor Hub](https://hub.harborframework.com/) handles sharing of tasks, datasets, run results, and leaderboards. Together, the three form the task specification, execution plane, and collaborative distribution surface.

## One-Page Summary

1. **Harbor is an outer evaluation Harness, not an Agent Runtime.** Claude Code, Codex CLI, and OpenHands handle the Agent Loop; Harbor handles scheduling tasks, creating environments, running Agents, invoking Verifiers, and saving results.
2. **Task is the core asset.** A task is not just a Prompt; it also includes a fixed environment, tests, timeout, network, resources, optional Oracle solutions, and artifact rules. Task quality determines whether scores are meaningful.
3. **The Verifier determines what counts as completion.** File existence, test passing, service status, or database changes should be checked by an independent verifier. The Agent saying "done," a process exit code of zero, or an HTTP 200 response are not sufficient evidence of success.
4. **Harbor evaluates the complete combination.** The score belongs to `Agent × Model × Task × Environment × Policy × Budget` and cannot be attributed solely to the model.
5. **It suits terminal, code, and tool-based Agents.** Through custom tasks, Agent Adapters, and environment providers, it can also extend to research, data analysis, and MCP tool tasks; pure conversational knowledge Q&A usually does not need to bear this container overhead.
6. **Reproducibility does not equal validity.** A fixed image only guarantees environment consistency; whether tasks represent real business, whether Verifiers can be gamed, and whether Adapters faithfully reproduce upstream behavior still require manual design and validation.
7. **Kubernetes is suitable for hosting large-scale Trials.** One Trial maps to a short-lived Job, combined with queues, RuntimeClass, NetworkPolicy, short-term credentials, object storage, and TTL cleanup, forming an enterprise evaluation platform.
8. **Production selection cannot look only at average Reward.** At minimum, publish strict success rate, stability, infrastructure error rate, cost, latency, security thresholds, and per-question raw results simultaneously.

![Harbor Agent Evaluation Framework Architecture](../../assets/rag-agent/harbor-agent-evaluation-framework/architecture.png)

## 1. What Problem Does Harbor Actually Solve

Agent evaluation involves at least six types of objects:

| Object | Role | Common Variations |
| --- | --- | --- |
| Task | Defines goals, environment, and acceptance criteria | Instructions, initial state, tests, resources, and network |
| Agent | Determines loop, tools, context, and recovery strategies | Codex CLI, Claude Code, OpenHands, self-developed Runtime |
| Model | Produces decisions and content | Provider, model snapshot, sampling parameters |
| Environment | Hosts real execution | Docker, remote Sandbox, service Sidecar |
| Verifier | Independently judges results | Tests, state checks, rule scoring, Judge |
| Job / Trial | Organizes batch experiments and individual runs | Dataset, repetition count, concurrency, timeout, retry |

If a team assembles these parts themselves, they quickly encounter a set of recurring problems: how do different Agents use the same task; how are containers created and cleaned up; whether failure comes from the Agent, model, environment, or evaluation infrastructure; how multiple runs are aggregated; how trajectories are uniformly saved; and how to generate Rollouts needed for reinforcement learning.

Harbor abstracts these problems into a unified execution model. A **Job** describes an entire batch of experiments, and one Job expands into multiple **Trials**; each Trial binds one Task, one Agent, one model, and one environment, and the Verifier then outputs a Reward. According to the [official run results documentation](https://www.harborframework.com/docs/run-jobs/results-and-artifacts), a single Trial saves configuration, results, Agent trajectory, terminal recording, Verifier logs, and artifacts, and the Job layer aggregates the entire batch of results.

Therefore, Harbor's value is not "making Agents smarter," but enabling the capabilities of different Agents to be stably run, verified, compared, and reviewed.

## 2. Difference Between Outer Evaluation Harness and Agent Harness

The term "Harness" in the Agent field often refers to two different systems:

- **Agent Harness / Runtime**: Implements observation, reasoning, tool calls, result feedback, context compression, permission confirmation, and recovery around the model;
- **Evaluation Harness**: Prepares questions and environments outside the Agent, starts a run, and independently scores after completion.

Harbor belongs to the second category. The Codex CLI, Claude Code, or OpenHands under test belong to the first category. The former is like the examination room and judging system, while the latter is like the contestant entering the examination room to complete tasks. Separating the two makes many concepts clearer:

```text
Harbor Job
  └── Trial
      ├── Task：题目、初始环境和验收规则
      ├── Agent Adapter：怎样安装、启动和读取轨迹
      ├── Agent Runtime：怎样调用模型和工具完成任务
      ├── Environment Provider：在哪里创建隔离环境
      └── Verifier：最终状态是否满足要求
```

If comparing Harnesses, the model, task, tool contract, budget, and environment should be fixed; if comparing models, the Agent Runtime and other variables should be fixed; if comparing complete products, each product may use its recommended configuration, but the report must acknowledge that the score belongs to the complete combination.

## 3. What Does a Harbor Task Contain

The [official task specification](https://www.harborframework.com/docs/tasks) gives a straightforward base directory:

```text
my-task/
├── instruction.md
├── task.toml
├── environment/
│   └── Dockerfile
├── solution/
│   └── solve.sh
└── tests/
    └── test.sh
```

- `instruction.md` is the goal and constraints visible to the Agent;
- `task.toml` stores metadata such as Schema, timeout, resources, network, and execution mode;
- `environment/` fixes the toolchain, dependencies, initial files, and services;
- `solution/` can provide an Oracle solution to prove the task is solvable and validate tests;
- `tests/` checks the environment state after the Agent completes.

The Verifier ultimately writes a single floating-point reward to `/logs/verifier/reward.txt`, or writes multiple numerical dimensions to `/logs/verifier/reward.json`. Multi-dimensional rewards are suitable for simultaneously preserving strict correctness, safety, quality, and efficiency, but external aggregation should still retain a hard pass field that cannot be masked by averages.

![Harbor Task Executable Contract](../../assets/rag-agent/harbor-agent-evaluation-framework/task-contract.png)

### 3.1 Why the Environment Is Part of the Task

Terminal or code tasks are highly dependent on the environment. Compiler version, system packages, repository Commit, pre-installed tools, file permissions, and background services can change results if any one drifts. Writing the environment into a Dockerfile or Compose turns a task from a "natural language description" into a "replayable experiment."

But image tags are not enough. Production evaluation should record the image Digest and freeze the task dataset, Harbor version, Agent version, model snapshot, and tool Schema together. `latest`, floating Git branches, or runtime online downloads all weaken reproducibility.

### 3.2 Why the Verifier Should Ideally Run Independently

If the Agent can read tests, modify scoring scripts, or fabricate results, the Reward may reflect "gaming ability" rather than task ability. Harbor supports a separate Verifier environment: first stop or isolate the main environment where the Agent runs, then hand the required artifacts to the verifier. This can hide proprietary tests, isolate scoring credentials, and reduce opportunities to tamper with evidence.

An independent Verifier is still not a universal defense. Task authors should also prepare:

- Oracle runs, proving that legitimate solutions can pass;
- Nop and wrong answers, proving that not doing the task or fabricating output cannot pass;
- Hidden tests, Canaries, and unpredictable inputs, reducing hardcoding against fixed samples;
- State readback, rather than only checking whether a certain text segment appears in stdout;
- Checks on artifact generation time, provenance, and integrity.

### 3.3 Network Policy Is Part of Task Semantics

If internet access is allowed, the Agent may download ready-made answers, leak data, or be affected by external changes; with a complete network cutoff, dependency package installation and real business API tasks may become distorted. Harbor's task specification can separately describe network modes for environment preparation, Agent execution, and Verifier phases. If an environment provider cannot honor dynamic network policies, the correct behavior is to reject the task, not silently degrade to unrestricted outbound access.

Enterprise golden sets are typically divided into three tiers:

1. `no-network`: code, terminal, file, and offline data tasks;
2. `allowlist`: only allow model gateways, artifact repositories, and designated business simulation services;
3. `recorded-network`: allow controlled external network, while recording DNS, destination addresses, and traffic summaries.

## 4. How Does a Single Trial Run

A standard Trial can be broken down into the following phases:

1. Parse the Job and dataset, generate an immutable Trial configuration;
2. Build or pull the task environment, check whether the environment provider satisfies CPU, memory, network, and operating system requirements;
3. Create an isolated environment, install or connect the Agent;
4. Hand `instruction.md` to the Agent, recording tool calls, terminal events, Tokens, and time;
5. After the Agent finishes, times out, or reaches the budget, collect the declared artifacts;
6. Run the Verifier in a shared or independent environment;
7. Write Reward, error classification, trajectory, logs, and artifacts;
8. Aggregate Job results, and view and compare them through the Viewer or Harbor Hub.

The [official results viewer](https://www.harborframework.com/docs/run-jobs/run-evals) can display Jobs, Trials, tool calls, trajectories, Tokens, duration, Verifier output, and artifacts. It is suitable for locating "why it failed," while leaderboards are only suitable for answering "how is overall performance."

Three types of failures need to be distinguished:

| Result | Meaning | Counted as Task Failure |
| --- | --- | --- |
| `task_fail` | Agent ran normally, but the final state did not pass the Verifier | Yes |
| `timeout` | Did not complete within the specified budget | Yes, additionally report timeout rate |
| `infra_error` | Image, Sandbox, Provider, or control plane failure | Not disguised as task failure, but must enter infrastructure availability and cost |

Infrastructure errors can be re-run, but the original Trial cannot be deleted. Automatic retries such as temporary model API 429s or Sandbox startup failures should also generate independent Attempts and preserve the reason; only the best attempt cannot be kept.

## 5. Agent Adapter and Environment Provider

### 5.1 Agent Adapter

The [Harbor Agent documentation](https://www.harborframework.com/docs/agents) lists built-in Agents such as Claude Code, Codex CLI, GitHub Copilot CLI, Gemini CLI, OpenHands, and Mini-SWE-Agent. Self-developed systems can implement a unified Agent interface and choose between two integration methods:

- **Externally driven**: The Agent runs in the Harbor control process and executes actions against the Sandbox through the Environment API;
- **In-container execution**: Install the Agent into the task environment, run it in Headless mode, then collect the trajectory and output.

An Adapter is not a thin command alias layer. It affects system prompts, working directory, model parameters, tool presentation, timeout, exit conditions, and trajectory conversion. The fact that an Adapter can run does not mean it faithfully reproduces the upstream Agent. Each upgrade should at minimum:

- Align per-question results with the upstream official execution method;
- Check the system Prompt, tool Schema, and default budget;
- Verify whether SIGTERM, timeout, and abnormal exits can produce complete results;
- Verify whether declared capabilities such as multimodal input, MCP, and sub-Agents are actually passed through;
- Run version regression against a fixed golden task set.

### 5.2 Environment Provider

The Provider maps the unified lifecycle to local Docker or managed Sandboxes. The official documentation lists environments including Daytona, Modal, E2B, Runloop, Tensorlake, LangSmith, Blaxel, Novita, and others. Different Providers differ in their support for network switching, resource limits, operating systems, image caching, artifact collection, and concurrency.

When selecting a Provider, do not look only at single-startup speed; compare simultaneously:

| Dimension | Questions to Verify |
| --- | --- |
| Isolation strength | Shared-kernel container, gVisor, microVM, or independent VM |
| Lifecycle | Whether create, pause, resume, timeout termination, and forced cleanup are reliable |
| Network | Whether outbound access can be disabled or restricted by phase, and whether auditing is supported |
| Resources | Whether CPU, memory, disk, and GPU limits actually take effect |
| Artifacts | Whether large files, Sidecars, and abnormal exits can be fully returned |
| Supply chain | Whether image Digest, cache, and dependency downloads are traceable |
| Cost | Startup cost, runtime cost, idle cost, and failed retry cost |

## 6. How Should Harbor Run Results Be Scored

### 6.1 First Layer: Strict Success Rate

The most important metric is:

```text
Strict Success Rate = 通过所有必需 Verifier 的 Trial 数 / 全部有效 Trial 数
```

For Agents with randomness, each question can be run multiple times and report average success rate, variance, and confidence intervals. `pass@k` is suitable for measuring "whether at least one success occurs given k chances," but the best result among k runs cannot be used to masquerade as `pass@1`.

### 6.2 Second Layer: Reliability and Error Structure

It is recommended to also report:

- First-attempt success rate and repeated-run success rate;
- Proportions of `task_fail`, `timeout`, `agent_error`, `model_error`, and `infra_error`;
- Per-question result variance and consecutive success count;
- Whether recovery from Checkpoint or persistent state is possible after failure;
- P50/P95 latency for environment creation, Agent initialization, and Verifier phases.

### 6.3 Third Layer: Efficiency

Efficiency is only interpretable when the task succeeds:

```text
Cost per Success   = 全部 Trial 总成本 / 成功 Trial 数
Tokens per Success = 全部 Trial 总 Token / 成功 Trial 数
Time to Success    = 成功 Trial 墙钟时间的 P50 / P95
```

Tokens, model costs, and Sandbox time consumed by failed runs must enter the total cost. Otherwise, a system that keeps failing and retrying will appear deceptively cheap.

### 6.4 Fourth Layer: Security Thresholds

Credential leakage, unauthorized tool calls, bypassing approvals, modifying the Verifier, accessing prohibited networks, or escaping the Sandbox should all serve as independent Gates. A single serious violation cannot be averaged away by high Rewards on other questions.

For LLM Judge or Agent Judge, it is recommended to have it evaluate only dimensions that are difficult to programmatically check, such as report coverage, interaction quality, and open-ended research quality; task status, files, tests, permissions, and network behavior should be checked deterministically first.

## 7. How Harbor Divides Responsibilities with Other Frameworks

![Boundary between Harbor and common Agent tools](../../assets/rag-agent/harbor-agent-evaluation-framework/framework-map.png)

| Item | Primary Positioning | Suitable For | What It Should Not Be Taken As |
| --- | --- | --- | --- |
| Harbor | Environment-driven Agent evaluation, datasets, and Rollout | Reproducible experiments and large-scale concurrency for terminal, code, and tool Agents | A production Agent orchestration framework |
| [Inspect AI](https://inspect.aisi.org.uk/) | General model and Agent evaluation framework | Building broad safety and capability evaluations with Dataset, Solver, and Scorer | A model Benchmark with only multiple-choice questions |
| [SWE-bench Harness](https://github.com/SWE-bench/SWE-bench/blob/main/docs/reference/harness.md) | Specialized evaluation protocol for code repair | Applying Patches in fixed repository environments, running tests, and scoring | An arbitrary business Agent platform |
| LangGraph | Stateful Agent application orchestration | Building nodes, state, routing, checkpoints, and human intervention | A standalone Sandbox evaluation system |
| Langfuse | LLM / Agent observability and evaluation operations | Production Trace, Prompt, dataset, experiment, human and automated review | A task environment provider |
| Kubernetes | General container orchestration and resource platform | Isolation, queuing, elasticity, scheduling, and cleanup of Trials | An Agent scorer |

The capability boundary between Harbor and Inspect AI is narrowing: Inspect also supports tools, external Agents, Docker, Kubernetes, and multiple Sandboxes. Actual selection should not fabricate claims like "framework X cannot do Y at all"; instead, compare the team's existing task formats, Adapter ecosystem, result protocols, Sandbox providers, training Rollout paths, and governance requirements.

The relationship between Harbor and SWE-bench is more like a general framework versus a specialized standard. SWE-bench's Docker Harness is responsible for applying code Patches, running real repository tests, and determining fixes; Harbor can place SWE-type tasks and other terminal, data, and tool tasks into the same Job/Trial model.

LangGraph and Langfuse typically sit on a different chain: LangGraph is used to build Agents, Langfuse is used to observe experiments and production, and Harbor is used for controlled offline evaluation. All three can coexist.

## 8. The Relationship Between Harbor and Terminal-Bench, Harbor Hub, and RL

Harbor originated from the evaluation engineering needs of the Terminal-Bench team, but it does not only run Terminal-Bench. Tasks can form datasets, and the same Task can belong to multiple datasets, thereby building base sets, regression sets, safety sets, and business-domain combinations. The [official dataset documentation](https://www.harborframework.com/docs/datasets) supports local directories, published datasets, and Git repository sources.

Harbor Hub is a sharing layer that can publish tasks and datasets, upload Job results, compare runs, and display trajectories. When used internally within an enterprise, data boundaries must first be clarified: production logs, source code, Prompts, tool returns, terminal recordings, and artifacts may all contain sensitive information. By default, data should be stored locally; only desensitized and authorized data may be uploaded publicly.

Harbor can also convert trajectories produced by Trials into Rollouts needed for training. The [official reinforcement learning workflow](https://www.harborframework.com/docs/training-workflows/rl) uses the same set of Tasks, Environments, and Verifiers to generate trajectories and Rewards. This reduces protocol drift between the "evaluation environment" and the "training environment," but it also introduces a risk: if training optimizes against a fixed Verifier over the long term, Agents may learn reward hacking. Therefore, hidden tests, rotating question banks, and a final verification set not used in training should be retained.

## 9. How to Productionize on Kubernetes

Harbor's environment provider is responsible for abstracting Sandboxes; Kubernetes is responsible for multi-tenant resources, queuing, scheduling, and lifecycle. For private clusters, one clear mapping is: one Trial corresponds to one short-lived Kubernetes Job, and the Job contains the Agent, the task environment, and any necessary Sidecars.

![Harbor production architecture on Kubernetes](../../assets/rag-agent/harbor-agent-evaluation-framework/kubernetes-production.png)

### 9.1 Control Plane

The control plane stores Job configurations and Trial state, and is only responsible for scheduling and aggregation; it does not directly execute untrusted commands. It needs to support:

- Idempotent Trial creation and a recoverable state machine;
- Four-level concurrency limits: global, tenant, dataset, and Provider;
- Deciding whether to retry based on error type, while retaining all Attempts;
- Phase timeouts and an overall deadline for the entire Job;
- Automatic environment cleanup after abort, while first uploading logs and artifacts;
- Version, cost, and quota auditing.

### 9.2 Workload Isolation

Agents execute model-generated commands, so ordinary container boundaries cannot be equated with strong security Sandboxes. Choose based on the threat model:

- Trusted internal code: restricted containers, read-only root filesystems, Seccomp, non-root;
- Semi-trusted plugins and external repositories: gVisor RuntimeClass;
- High-risk untrusted code: Kata Containers or microVMs;
- Tasks requiring browsers, desktops, or special kernels: dedicated node pools or managed Sandboxes.

Each Trial uses a separate Namespace or equivalent isolation unit, with east-west and north-south network traffic denied by default, and a least-privilege ServiceAccount. Model keys are injected via Workload Identity or short-lived Tokens, and are not written into task images, trajectories, or artifacts.

### 9.3 Queuing and Capacity

The load from large-scale evaluations is typically bursty. Kueue or Volcano can manage quotas, priorities, and queues; `ResourceQuota` prevents a single dataset from exhausting the cluster; `PriorityClass` gives regression gates and exploratory experiments different preemption levels.

Higher concurrency is not always better. The following should be limited separately:

- Sandbox creation QPS;
- Image registry pull bandwidth;
- Model gateway RPM/TPM;
- Shared filesystem IOPS;
- Verifier CPU peaks;
- Object storage upload bandwidth.

### 9.4 Evidence and Observability

After a Trial ends, structured results enter the metadata database, while trajectories, terminal recordings, logs, and large files enter object storage. Prometheus focuses on queues, phase latency, success rates, error classification, resources, and cleanup; OpenTelemetry connects the control plane, Sandbox, model gateway, and Verifier; Langfuse can handle model and tool Trace retrieval and experiment analysis.

The minimum dashboard should include:

- Job pass rate, Trial status, and infrastructure availability rate;
- P50/P95 for environment creation, Agent execution, Verifier, and artifact upload;
- Model 429/5xx, Agent exceptions, OOM, evictions, and timeouts;
- Tokens, model costs, Sandbox costs, and cost per success;
- Regression trends by task, Agent, model, version, and Provider;
- Namespaces, Pods, PVCs, and external Sandboxes still alive after completion.

## 10. An Example Enterprise Internal Task

Suppose we want to evaluate whether an Agent can diagnose a Kubernetes workload stuck in Pending state. `instruction.md` only tells the Agent: use the provided read-only snapshot, find the root cause, and output `report.json`. The task environment pre-provisions desensitized Pod, Event, Node, Queue, and PodGroup data, along with a restricted `kubectl-snapshot` tool.

The Verifier does not evaluate whether the write-up "looks like it was written by an expert"; instead, it checks:

1. Whether `root_cause` hits the real cause;
2. Whether `evidence` references the correct objects and fields;
3. Whether the recommendation can unblock the situation;
4. Whether unauthorized write operations were proposed;
5. Whether the output satisfies the JSON Schema.

A multi-dimensional Reward can be expressed as:

```json
{
  "strict_pass": 1,
  "root_cause": 1.0,
  "evidence": 0.9,
  "remediation": 0.8,
  "safety": 1.0
}
```

`strict_pass` is still determined by hard conditions. For example, if the root cause is wrong or the recommendation directly deletes a production object, the task must not pass even if the textual quality is high. Such a task can both compare different models and, under the same model, compare the tool usage and context management of Codex, Claude Code, OpenHands, and internal Agents.

## 11. Recommended Steps for Implementation from Scratch

### Phase One: Validate the Framework, Do Not Rush to Build a Leaderboard

Select 10–20 deterministic tasks covering files, Shell, code, services, and structured output. For each task, first run the Oracle, then run the Nop and known-wrong answers. The goal is to prove that the environment is reproducible, the Verifier does not misjudge, and artifacts are complete — not to chase high scores.

### Phase Two: Build an Adapter Alignment Set

Prepare a small compatibility matrix for each Agent: text tasks, timeouts, abnormal exits, MCP, multimodal, sub-Agents, long outputs, and large artifacts. Adapter upgrades must pass this regression set, to avoid "the command still starts, but behavior has already changed."

### Phase Three: Build an Enterprise Golden Set

Extract tasks from real failure tickets, code changes, and operational procedures; remove sensitive information and fix the initial state. The golden set is layered by basic capability, business capability, failure recovery, and safety, with a portion of hidden verification sets retained.

### Phase Four: Integrate into Release Gates

Every upgrade to the model, Prompt, tool, Skill, Agent, or Provider runs a fixed regression. The gate checks success rate, safety incidents, cost, and P95 latency simultaneously; it does not accept obvious regressions just because the average score is slightly higher.

### Phase Five: Scale Rollout and Continuous Updates

Only after tasks and Verifiers are stable should you scale up to hundreds or thousands of parallel environments or training Rollouts. Periodically check for question contamination, Reward Hacking, task aging, and production traffic changes, and roll in new questions on a rotating basis.

## 12. Common Misconceptions

### Misconception One: Once Containerized, Evaluation Is Fair

Containers can only fix part of the environment. Agent Prompts, tools, budgets, model versions, networks, and Adapter differences still affect results. Fairness comes from variable control and full disclosure.

### Misconception Two: The Finer the Reward, the More Objective the Evaluation

A large number of dimensions does not necessarily improve validity. As long as the Verifier is inconsistent with the real goal, fine-grained decimals are just measuring the wrong thing more precisely. First ensure strict success conditions, then add diagnostic scores.

### Misconception Three: Automatically Rerunning Failures Makes Results More Stable

Rerunning may mask first-attempt failures and instability. Every attempt should be retained, with `pass@1`, repeated success rate, and infrastructure errors reported separately.

### Misconception Four: Public Leaderboards Are the Answer for Enterprise Selection

Public Benchmarks provide comparability; enterprise tasks provide relevance. A model scoring high on Terminal-Bench or SWE-bench does not mean it can correctly handle internal permissions, data, tools, and approvals.

### Misconception Five: The More Complete the Trajectory, the More Suitable It Is for Public Release

Trajectories may contain source code, keys, user data, internal addresses, and tool returns. Before uploading to Harbor Hub or sharing a Job, automated scanning, desensitization, and approval are required.

## 13. Version and Maturity Assessment

Harbor is still evolving rapidly. [GitHub Releases](https://github.com/harbor-framework/harbor/releases) shows the latest release as of this review is v0.23.0; recent versions have continuously added multi-step tasks, standalone Verifier environments, phased network policies, resource constraints, and Agent capability declarations. Rapid iteration brings capability, but it also means configurations and commands may undergo breaking changes.

For production environments, it is recommended to pin simultaneously:

- Harbor version and code Commit;
- Task Schema version;
- Dataset version and task content hash;
- Agent Adapter version;
- Container image Digest;
- Full model identifier and Provider;
- Verifier and aggregation script versions.

Before upgrading, run a dual run on a small golden set to confirm that result structures, error classification, network policies, artifacts, and Rewards have not changed unexpectedly, and only then scale up concurrency.

## 14. When Harbor Is Worth Using

Harbor is particularly suitable for the following scenarios:

- Maintaining multiple terminal or programming Agents simultaneously and needing unified comparison;
- Tasks that must be completed in real file, Shell, service, or browser environments;
- Needing standalone Verifiers, complete trajectories, and reproducible experiments;
- Needing large-scale parallel Trials or generating Rollouts for reinforcement learning;
- Wanting to put public Benchmarks and enterprise golden sets into the same execution model.

If the team only does simple offline Q&A sets, already has mature assets built on Inspect AI, or the main need is production Trace and Prompt operations, using the existing platform directly is usually more appropriate. Harbor's value comes from environment-driven evaluation, Agent Adapters, and executable Verifiers; without these needs, it also brings additional costs for images, Sandboxes, artifacts, and scheduling.

## References

- [Harbor GitHub repository](https://github.com/harbor-framework/harbor)
- [Harbor official documentation: Core Concepts](https://www.harborframework.com/docs/core-concepts)
- [Harbor official documentation: Tasks](https://www.harborframework.com/docs/tasks)
- [Harbor official documentation: Agents](https://www.harborframework.com/docs/agents)
- [Harbor official documentation: Run Evals](https://www.harborframework.com/docs/run-jobs/run-evals)
- [Harbor official documentation: Results and Artifacts](https://www.harborframework.com/docs/run-jobs/results-and-artifacts)
- [Harbor official documentation: Datasets](https://www.harborframework.com/docs/datasets)
- [Harbor official documentation: RL Workflows](https://www.harborframework.com/docs/training-workflows/rl)
- [Harbor Hub](https://hub.harborframework.com/)
- [Inspect AI](https://inspect.aisi.org.uk/)
- [SWE-bench Evaluation Harness](https://github.com/SWE-bench/SWE-bench/blob/main/docs/reference/harness.md)
- [Terminal-Bench 2](https://github.com/harbor-framework/terminal-bench-2)
