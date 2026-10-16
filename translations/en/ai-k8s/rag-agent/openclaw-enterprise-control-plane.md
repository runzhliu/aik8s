---
title: "OpenClaw Enterprise Project Analysis: Agent Control Plane, Identity Isolation, and Kubernetes Deployment"
description: "An analysis of OpenClaw Enterprise's resource model, persistent work queue, per-Agent identity, runtime drivers, storage, and observability based on public source code, discussing the value and limitations of enterprise deployment"
status: evolving
last_reviewed: 2026-10-12
---

# OpenClaw Enterprise Project Analysis: Agent Control Plane, Identity Isolation, and Kubernetes Deployment

For enterprises using Agents, the difficulty often appears at the second step: the first assistant can already answer questions, modify code, and call tools, but the next step requires assigning permissions to multiple teams, managing credentials, updating runtime environments, and tracking exactly which configuration was used in a given deployment. Starting up more assistants is easy; managing them as long-running enterprise workloads is harder.

[OpenClaw Enterprise][repo] (OCE) targets exactly this class of problems. It includes the **OpenClaw Control Plane (OCC)**, which organizes Agent definitions, deployment versions, identities, permissions, and infrastructure drivers into a single platform. The project's "Kubernetes for agents" framing can be understood as borrowing Kubernetes' declarative, reconciliation, and lifecycle management approach; it does not replace Kubernetes, nor does it turn model inference services themselves into an Agent control plane. [Project description][readme], [core concepts][concepts].

This article is based on the **public source snapshot `b195e54e9b0c` dated October 12, 2026**, with a focus on verifying the current implementation and deployment contracts. It is a source-code and architecture analysis; no integration tests or production deployments of the project were executed for this article. Citations are pinned to that commit to prevent later main-branch changes from invalidating the conclusions.

A limited-scope compatibility pilot has since been completed on Kubernetes `1.30.4`, covering the office-network Console, Agent deployment, and real model responses. For the specific configuration, troubleshooting process, and the not-yet-public native chat page, see [OpenClaw Enterprise Kubernetes Deployment in Practice](openclaw-enterprise-kubernetes-practice.md). That pilot does not change the official version or the support requirements for dedicated clusters.

My assessment is: **OCE already provides an Agent management control plane worth studying, especially independent identity, immutable deployment snapshots, and persistent coordination mechanisms; for enterprise adoption, runtime isolation, update disruption, storage recovery, and driver compatibility still require careful evaluation.** These limitations directly affect how the platform is rolled out and cannot be judged from the feature list alone.

## 1. How It Relates to the Original OpenClaw

The original OpenClaw primarily addresses message ingestion, sessions, tool execution, and the Agent runtime. OCE adds an enterprise management layer around it, using drivers to deploy Agents onto infrastructure. The current standard Kubernetes paths include a merged OpenClaw runtime and a separated Codex Harness. Here, **Harness** refers to the execution framework that drives a single Agent execution, connects to models, and runs tools. [Runtime modes][concepts].

| Concern | Original OpenClaw runtime responsibility | OCE-added management responsibility |
| --- | --- | --- |
| How Agents work | Receives messages, manages sessions, calls models and tools | Defines Agents, decides which version to deploy or stop |
| How configuration is managed | Runs with native configuration | Stores reusable configuration, generates immutable snapshots per deployment |
| Who can do what | Runtime tools and access policies | Identity and permission checks on specific resources, operations, and scopes |
| How credentials are used | Runtime needs credentials for models, channels, etc. | Manages Secret references, authorization, and credential delivery to the runtime |
| How infrastructure changes | Runs in a pre-provisioned environment | Worker invokes drivers to create, update, and clean up workloads |
| How deployments are troubleshot | Checks runtime logs and status | Queries deployment history, operation status, audit, and control-plane metrics |

The original-version responsibilities in the table are used to explain the layering; OCE's actual boundaries are governed by the current [concept documentation][concepts] and [runtime security contract][runtime-security]. For discussion of directly wrapping the original OpenClaw as an enterprise Agent platform, see [OpenClaw as an Enterprise Agent Platform Foundation](openclaw-enterprise-agent-platform.md).

OCE also does not directly provide a general-purpose model hosting, inference autoscaling, or token cost settlement system. The Inference Driver in the design cannot yet be treated as an implemented unified model gateway; infrastructure CPU and memory quotas also cannot substitute for model cost budgets. [Driver implementation status][driver-design], [production handoff requirements][handoff].

## 2. Architecture First: Control Plane for Deployment, Data Plane for Execution

![OpenClaw Enterprise control plane with two standard Kubernetes runtime modes](../../assets/rag-agent/openclaw-enterprise/architecture.png)

OCC's HTTP API checks caller permissions and accepts resource changes, while Workers claim tasks from PostgreSQL and invoke Drivers to complete infrastructure operations. **The API and Worker are separate processes, and deployment work enters a persistent queue** rather than being maintained by a background task inside the API process. [Controller contract][controller].

The data plane consists of each Agent's Gateway and Harness. The Gateway receives connections and messages; the Harness performs model interactions and tool execution. The difference between the two standard modes is:

| Mode | Workload organization | Model credential placement | What to validate first |
| --- | --- | --- | --- |
| Embedded OpenClaw | Gateway and Harness merged | Merged runtime | OpenClaw connectivity, configuration, and basic model calls |
| Dedicated Codex | Gateway and Codex Harness separated | Delivered only to the Harness; Gateway does not receive model credentials | Separated execution surface, workspace access, and runtime lifecycle |

This layering is useful for troubleshooting. A healthy control plane only proves the management entry point works; a successful deployment operation does not automatically prove that model credentials, model requests, tools, and workspaces are all functioning. These chains should be validated separately. [Concept documentation][concepts], [Kubernetes deployment checks][k8s-setup].

The source entry points are also fairly clear:

| Path | What to focus on |
| --- | --- |
| `apps/controller/` | HTTP API, browser console, Worker, and specific drivers |
| `packages/contracts/` | Resource definitions, API schemas, and driver interfaces |
| `packages/occ/` | Resource lifecycle, state persistence, and work queue |
| `packages/iam/` | Identity and Access Management (IAM) |
| `packages/audit/` | Audit events and sensitive-field scrubbing |
| `cmd/occ/`, `internal/occcli/` | Go CLI commands and output |
| `internal/occclient/` | Transport and authentication client used by the CLI |

This directory breakdown comes from the [repository description][readme]. To evaluate platform stability, it is advisable to start with the queue, Worker, drivers, and authorization paths rather than reading only the console pages.

## 3. Resource Model: Creating an Agent Does Not Immediately Start a Process

OCE manages Agents through its own API and persistent resource model; the Kubernetes driver then realizes these operations as Deployments, Services, ConfigMaps, Secrets, and storage resources. Do not directly interpret the platform's `Agent` or `AgentRevision` as Kubernetes Custom Resource Definitions (CRDs). [Resource concepts][concepts], [Kubernetes driver source][k8s-source].

| Resource or concept | Meaning | Common point of confusion |
| --- | --- | --- |
| Installation | A single OCE platform installation | Can manage multiple OCE Namespaces |
| Namespace | Resource grouping for teams, tenants, or workloads | Platform `default` and Kubernetes built-in `default` are not the same concept |
| Agent | Long-lived workload definition with independent identity | Creating the definition does not start a process |
| Configuration | Reusable native OpenClaw configuration | Modifying it does not directly change the running version |
| AgentRevision | Immutable snapshot of configuration and execution settings for one deployment | Historical versions existing does not mean one-click rollback is supported |
| Secret | Independently stored sensitive values with secure references | API returns metadata, not sensitive values |
| ServicePrincipal | Automation principal; each Agent has its own principal | Does not inherit the creator's permissions |
| OCC ServiceAccount | Associates an Agent with upstream credential references | Distinct from Agent identity and Kubernetes ServiceAccounts |

The definitions above come from [core concepts][concepts] and the [Namespace contract][namespaces].

For example, after a development team creates a code assistant, they can first modify configuration and select a model; only when a deployment is submitted does an AgentRevision come into existence and enter asynchronous execution. Subsequently modifying a shared configuration does not affect the running assistant, which continues using the original snapshot until the next deployment. This answers a common incident question: **which version of the configuration was the Agent that executed yesterday's task actually using at the time?** [AgentRevision lifecycle][revisions].

But immutable snapshots also have boundaries: a Secret reference does not mean the old credential content was saved; files, databases, and workspace state will not automatically return to a previous state simply because Revision history exists.

If the response to a deployment request is lost, check the Revision history before deciding whether to retry: every accepted Deploy creates a new version. Repeatedly clicking deploy is not automatic deduplication of the same request; lacking read permission for new Revisions may also make callers mistakenly believe a previous deployment never succeeded. [Deployment and retry notes][revisions].

## 4. How the Persistent Queue Handles Failures and Retries

![Agent flow from draft, deployment snapshot, asynchronous reconciliation, to runtime verification, with recovery boundaries](../../assets/rag-agent/openclaw-enterprise/lifecycle.png)

In `packages/occ/src/state/postgres-work-queue.ts`, task claiming uses PostgreSQL's `FOR UPDATE OF work SKIP LOCKED`: lock one currently claimable record, skip records already locked by other Workers, then atomically update the task state. After claiming, a claim token and lease are generated; lease renewal and final state updates must match the current claim identity. [Queue source][queue-source].

This implementation primarily addresses three classes of problems:

1. **The control process restarts and cannot find a previous deployment.** Work records are stored in the database, so a restarted Worker can continue reconciliation without relying on process memory.
2. **Multiple Workers race for the same task.** Database row locks, claim state, and token validation coordinate control operations; the implementation also checks whether an in-flight task already exists for the same Agent or Namespace.
3. **A Worker hangs and a task would otherwise never execute again.** Lease expiry recovery and retry mechanisms allow the task to re-enter the processing flow, and the old claimant can no longer legitimately submit the current queue state.

In the source, ordinary tasks have a default maximum attempt count of 10, an initial backoff base of 1 second, a maximum backoff of 300 seconds, and a default lease duration of 60 seconds. These are the implementation defaults in this snapshot; specific tasks and startup settings vary, and they should not be interpreted as every cleanup operation strictly enforcing the same counts. [Default parameters and recovery logic][queue-source].

Two layers need to be distinguished here: **queue claiming protects the state updates of control operations; it does not guarantee exactly-once execution of the Agent's external business actions.** If a tool has already sent an email or submitted an order and the connection then drops, control-plane retries will not automatically undo those actions. Business tools still need idempotency keys, operation records, permission checks, and approval where required. This is an application-level recommendation derived from the queue's responsibilities.

Similarly, the control-plane lease is not a node or storage isolation measure. If a node experiences a network partition, the "current version" in the database alone cannot prove that the old runtime has stopped. The current security and storage documentation explicitly retains this limitation. [Runtime security][runtime-security], [storage and credentials][storage].

## 5. Independent Agent Identity Is the Key Value of the Enterprise Control Plane

Suppose an administrator creates a development assistant. The administrator can manage multiple teams and all configuration, but this assistant only needs to read one code repository and use one model credential. OCE creates an independent ServicePrincipal for the Agent and **does not inherit the administrator's permissions to the assistant**. [IAM concepts][concepts].

Its authorization model includes Role, AccessBinding, and Restriction: Roles define permissions, AccessBindings grant permissions within a specific scope, and matching Restrictions deny access. Using a model Secret also requires both the caller and the Agent identity to have the corresponding authorization, and the Worker re-checks authorization and ownership during dispatch. [Identity and permissions][concepts], [runtime authorization checks][runtime-security].

This avoids the default privilege escalation of "the creator can access it, so the Agent can too," and also allows deployment permissions, credential usage permissions, and platform administration permissions to be separated.

However, note that **OCC permissions are not business tool permissions**. An Agent being authorized to use a model Secret does not mean it can modify tickets, access all databases, or delete code branches. Enterprises should still validate access scope on the tool/API side rather than relying on the model to follow permission declarations in prompts.

For human login, current authentication supports local email/password as well as GitHub, Google, and OpenID Connect (OIDC) login after administrator pre-registration; the documentation explicitly states there is no automatic user creation or automatic mapping from identity claims to roles. Therefore, after integrating enterprise login, a personnel registration and authorization process still needs to be arranged. [Authentication contract][authentication].

## 6. Where Isolation Reaches and Which Boundaries Still Need to Be Filled

The current implementation achieves fairly fine-grained credential and resource ownership checks: Revisions use their own runtime Secret projections, the dedicated Gateway does not receive model credentials, and Agent workload identities do not have direct access to the Kubernetes Secret API. Sensitive values are also not placed in public resource responses, configuration snapshots, or audit fields. [Security contract][runtime-security].

However, "independent identity" and "separate Pods" alone cannot prove strong tenant isolation:

| Boundary | Current implementation or explicit limitation | Impact on enterprise adoption |
| --- | --- | --- |
| Control-plane permissions | API/Worker Kubernetes permissions are granted per tenant Namespace | If a Worker with Deployment write permissions is compromised, it could still mount and read Secrets in that Namespace |
| Dedicated runtime communication | Gateway and Codex use a capability-token-authenticated `ws://` protocol | The current chain has no mutual TLS (mTLS); enabling TLS at the external entry point does not replace internal link protection |
| Model credentials | Standard path delivers API keys or access tokens to the execution runtime | Cannot yet be treated as an architecture where all model access goes through a controlled proxy, short-lived identity, and unified budget |
| Sessions of the same Agent | OpenShell uses AgentRevision as the sandbox boundary; sessions of the same Agent share some system resources within it | Different sessions cannot be advertised as mutually independent OS-level security boundaries |
| Plugins and drivers | Selected by the installation administrator; installed driver code executes inside the control-plane process | Drivers are part of the platform supply chain and trust boundary, not a security sandbox for untrusted plugins |

The table boundaries come from [runtime security][runtime-security] and the [Driver selection contract][driver-selection]. Credential brokering, restricted model egress, mTLS, and short-lived workload-bound identities are still listed as follow-up work in this snapshot.

For mutually untrusting tenants, OCE resource authorization should be designed together with independent admission policies, network egress, node/cluster isolation, and tool authorization. Installing a Sandbox Driver does not remove the need to verify actual network, file, and process isolation.

## 7. Which drivers work today

Drivers must be selected by the Installation administrator in the trusted boot configuration; ordinary Agents cannot choose infrastructure implementations on their own. Configuration drivers, compute drivers, credential drivers, and others each take on different responsibilities. See [Driver selection][driver-selection].

The most important thing to verify right now is "whether a new Agent can be fully deployed," not merely whether some container-creation logic exists in the source code:

| Implementation | Currently available path | Main limitations |
| --- | --- | --- |
| Kubernetes Compute | Embedded OpenClaw; Dedicated Codex | Requires matching runtime images, credentials, storage, routing, and authorization |
| SSH Compute | Embedded OpenClaw on Linux/systemd | Operator must prepare model credentials on the host; OCC-managed model credentials and Dedicated Codex are not supported |
| Docker / Podman Compute | Local Compose control-plane preview | Currently rejects all model authentication bindings required by new Agents; cannot be used to deploy new Agents |
| Optional OpenShell Sandbox | Experimental integration with Kubernetes | The original OpenShell still lacks the required credential and workload identity projection; a test bridge does not imply production support |

Source: [current ComputeDriver deployment matrix][compute-matrix]. The detailed capability table on that page retains an earlier source baseline; some shared storage and authentication entries are historical observations. Selection decisions should follow the current deployment contract at the top of the page and the corresponding reference documentation.

This directly affects the trial experience: **`occ dev up` started without an explicitly selected profile launches the Compose control-plane preview; seeing the console does not mean an Agent can be deployed.** If the goal is to exercise a real model request, use the official Kubernetes-only local path. See [local quick start][quickstart].

## 8. Kubernetes deployment: Helm exists, but the prerequisites are not light

As of this article's snapshot, the official Kubernetes installation documentation lists the supported baseline as **Kubernetes 1.35 or later, IPv4 connectivity, and a CNI (Container Network Interface) implementation capable of enforcing NetworkPolicy**. See [Kubernetes prerequisites][k8s-setup].

**1.35 is the support and CI verification baseline, not a hard gate that blocks control-plane startup.** Kubernetes Compute's `preflight()` reads the API Server version; when it is below `1.35.0`, it returns an `KUBERNETES_VERSION_BELOW_MINIMUM` warning, and the API and Worker log `compute.preflight-warning` and continue starting. The Chart also does not set `kubeVersion` to reject older-version installs. The source tests explicitly verify that 1.34 returns a warning without blocking authenticated access. See [driver requirements][k8s-driver], [version-check source][k8s-source], [corresponding test definition][version-test], and [Chart metadata][chart].

Therefore, existing clusters such as 1.30 or 1.34 can be used as compatibility verification targets without first modifying source code to bypass the version check; however, "no version gate" does not mean full feature compatibility. The version combinations of Envoy Gateway, Gateway API, and cert-manager should be checked separately, along with network policies, storage, actual Agent deployment, model requests, tool, and workspace paths. This article did not run those older-cluster tests and cannot list them as verified deployment environments.

Another independent condition: the current Kubernetes driver requires one cluster dedicated to a single OCE Installation; shared clusters are explicitly unsupported. Even if the version satisfies 1.35, installing into an existing shared business cluster should not be treated as an officially supported production path. See [driver deployment boundaries][k8s-driver].

| Category | What needs to be prepared in advance |
| --- | --- |
| Management database | External PostgreSQL, with separate application role and migration role, TLS verified |
| Private access entry | OCC internal HTTPS access URL and certificate; the Chart does not create public Ingress/TLS automatically |
| Agent workspace routing | Envoy Gateway, Gateway API CRDs, cert-manager, existing GatewayClass |
| Images | Controller and Runtime images matching the same source version; pin digests in production |
| Storage | Bootstrap, Gateway state volumes, and RWO workspace for Dedicated Harness |
| Permissions | OCC resource authorization and Kubernetes Role-Based Access Control (RBAC) configured separately |
| Network | Connectivity and restrictions for control plane, runtime, model egress, DNS, and monitoring collection |

Envoy Gateway, Gateway API CRDs, and cert-manager are not installed by the OCC Chart and must be prepared in advance. Workspace access uses private routing and per-Agent authorization; an accessible HTTPRoute must not be treated as completed permission configuration. See [installation requirements][k8s-setup] and [workspace routing][workspace-routing].

Controller and Runtime images should also be locked together. Some workspace and paired-node capabilities require runtime cooperation; upgrading only the control-plane image will not automatically give old Agents new protocol capabilities. See [workspace compatibility][workspace-routing].

### 8.1 Storage sizing can be estimated up front; recovery capability must be verified separately

The current Kubernetes driver allocates a default **10 GiB ReadWriteOnce (RWO) private volume** for each real Gateway; the Dedicated Agent Harness additionally gets a default **40 GiB RWO workspace volume**. Gateway state and Harness workspace are mounted separately; they do not share a single RWX volume. See [storage contract][storage].

Using the conventional topology of one runtime Pod per role:

| 100-Agent mode | Estimated runtime Pods | Estimated PVCs | Default requested capacity |
| --- | --- | --- | --- |
| Embedded OpenClaw | ~100 | ~100 | 1,000 GiB |
| Dedicated Codex | ~200 | ~200 | 5,000 GiB, ~4.88 TiB |

The PersistentVolumeClaim (PVC) capacity here is the **requested capacity** calculated from default values, not actual disk usage; it does not include the control plane, database, routing, logs, temporary maintenance tasks, or backups. It is suitable for an initial capacity budget, not as a load-test result.

When the Gateway uses SQLite state, the filesystem needs reliable locking, `fsync`, and WAL/SHM file support. Upstream explicitly recommends against placing the Gateway database on NFS or SMB/CIFS. RWO only restricts read/write to a single node; it does not limit to a single Pod, nor does it provide write isolation after node partitioning. See [SQLite and volume requirements][storage].

### 8.2 Updates cause interruptions; Revision does not provide one-click rollback

The Gateway uses a single replica with an `Recreate` replacement strategy, so it may be temporarily unavailable during updates; the current documentation also specifies the order of replacing the predecessor runtime and preparing the candidate. Therefore, Agent multi-version history must not be understood as interruption-free blue-green releases. See [Controller lifecycle][controller] and [current storage behavior][storage].

In addition, `activeRevisionId` is a control-plane selection pointer that may be set before the runtime is ready; a failed deployment can also leave a pointer to the failed version. Diagnostics should combine the operational end state with runtime verification. See [Revision status description][revisions].

There is currently no public generic rollback operation. Restoring old behavior requires restoring the appropriate configuration and then submitting a new deployment; business changes produced by databases, workspaces, credentials, and external tools must each be restored individually. For services with a defined Recovery Time Objective (RTO), this recovery path should be tested in practice rather than relying on saving a Revision list.

## 9. Observability: monitor the control plane, but also monitor real tasks

OCE provides Prometheus application metrics; the production Helm defaults expose a private `/metrics` on port **9464** on the API and Worker Pod IPs. However, the Chart does not automatically create a metrics Service, ServiceMonitor, or public Ingress; the operator must configure Pod discovery, collection permissions, and network policies. See [collection configuration][metrics-scrape].

| Metric | Question it answers | Interpretation limits |
| --- | --- | --- |
| `occ_http_requests_total` | Control-plane request volume and HTTP status categories | `4xx` cannot directly distinguish specific statuses such as 401 or 403 |
| `occ_http_request_duration_seconds` | HTTP API response latency | Not Agent full execution time or model time to first token |
| `occ_reconciliation_attempts_total` | Reconciliation attempt results and retry behavior | One deployment can correspond to multiple reconciliation attempts |
| `occ_work_pending` | Queued and claimed pending work count | Every Worker reads the same queue in the database |
| `occ_work_oldest_pending_age_seconds` | How long the oldest incomplete work has waited | Includes delayed retries, calculated from the original acceptance time |
| `occ_agents` | Persisted Agent lifecycle distribution | `running` does not prove the runtime has been continuously healthy |
| `occ_agent_operation_duration_seconds` | Duration from acceptance to completion for successful deployments/stops | Includes queuing and retries; permanent failures do not enter the success duration distribution |

Source: [metric definitions][metrics]. These distinctions matter: looking only at the P95 of successful operations can miss permanent failures; looking only at the `running` count can miss runtimes that have lost contact.

After Prometheus collection, the following queries can be run per Installation. `cluster` and `installation` are labels added by the collection configuration, not high-cardinality Agent labels that come with OCC: see [official aggregation examples][metrics-scrape].

```promql
# 控制面 HTTP QPS
sum by (cluster, installation) (rate(occ_http_requests_total[5m]))

# 控制面 HTTP P95，单位秒
histogram_quantile(0.95,
  sum by (cluster, installation, le)
    (rate(occ_http_request_duration_seconds_bucket[5m])))

# 队列深度：共享数据库的 Gauge 使用 max，不能跨 Worker 相加
max by (cluster, installation)
  (occ_work_pending and on (job, instance, cluster, installation) (up == 1))

# 最老未完成工作的年龄，单位秒
max by (cluster, installation)
  (occ_work_oldest_pending_age_seconds
    and on (job, instance, cluster, installation) (up == 1))
```

Grafana dashboards are recommended to be organized in three layers: the first layer shows control-plane requests, errors, queue, and deployment duration; the second layer shows Gateway/Harness Pod readiness, restarts, CPU, memory, and volumes; the third layer shows application task success rate, actual model calls, tool failures, and workspace verification. When the first two layers look normal but the third layer fails, the fault has usually moved past the deployment management path and should be investigated in models, tools, or application dependencies.

Logs also serve three purposes: the console provides a limited set of sanitized runtime logs; the optional OpenTelemetry Collector provides operational log export; audit logs are stored separately in PostgreSQL. The current log pipeline is not equivalent to full distributed tracing, and the demo path does not export traces. Log delivery is best-effort, and audit logs are not automatically exported through that Collector. See [observability contract][observability].

Therefore, evaluating the full lifecycle, quality, and cost of a single Agent task requires designing task-level observation and evaluation separately. This is the same problem discussed in [Agent Harness](agent-harness-technology-overview.md) and [Agent evaluation methods](agent-evaluation-overview.md) regarding execution traces and final-state verification.

## 10. First trial: prioritize the minimal complete path

For initial verification, use the Kubernetes-only local profile with Embedded OpenClaw. First get identity, Secret, deployment, and real model responses working end to end, then add dedicated Harness, plugins, and experimental sandboxes. This reduces the number of compatibility issues introduced at once.

Following the [official local guide][quickstart], prepare in advance a container engine, k3d, kubectl, Helm, Bash, Python 3, the Go version specified by `go.mod`, Node.js 24+, and the pnpm version pinned by `package.json`. From the source root, run:

```bash
pnpm cli:build
export OCC_DEVELOPMENT_COMPUTE_DRIVER=kubernetes
export OCC_DEVELOPMENT_CONTROL_PLANE=kubernetes
export OCC_DEVELOPMENT_SANDBOX_DRIVER=none
./bin/occ dev up
```

After startup, use the API address and credential file path printed by the command to set `OCC_URL` and `OCC_SERVICE_KEY_FILE`, complete CLI authentication, then run:

```bash
./bin/occ installation get
./bin/occ namespace list

# 等平台 default Namespace 成为 ready，并准备可访问目标模型的凭据
node scripts/first-agent.mjs my-agent --prompt 'What is 2 + 2?'
```

The helper script's credential input and model override behavior follow the [First Agent guide][first-agent]. It creates the necessary resources and verifies a real model response; tools and the native management UI are disabled by default, so this step only proves the minimal text path and cannot serve as tool-execution acceptance. The platform console provides deployment, version, and log views, but it cannot be used directly as a browser-based chat interface.

For further verification, you can progressively check whether configuration changes leave old versions unchanged, whether credential authorization revocation prevents subsequent deployments, how operations recover after a Worker restart, whether workspaces survive Pod replacement, and whether a failed update can be recovered by a new deployment. These are verification suggestions proposed in this article and have not yet been measured results.

## 11. Which teams it suits, and what is still missing before adoption

OCE is licensed under MIT; third-party components retain their respective licenses. At the time of this article's review, the repository had no official GitHub Release, and both the Helm Chart's `version` and `appVersion` were `0.1.0`. This can indicate the current distribution status, but version numbers alone cannot prove stability or instability; specific paths should still be evaluated. See [license][license], [Chart metadata][chart], and [Release page](https://github.com/openclaw/openclaw-enterprise/releases).

| Team need | Adoption value and recommendation |
| --- | --- |
| Already manages Kubernetes and is preparing to serve multiple internal teams | Suitable for research and verification: identity, deployment snapshots, and asynchronous reconciliation can reduce duplicated effort |
| Already has an Agent execution framework but lacks a management control plane | Verify the Driver contract first; do not assume any Harness can be plugged in directly |
| Only wants to run a personal assistant | The management database, control plane, storage, and routing may exceed actual needs |
| Wants to get an executable Agent immediately with Compose | The current default preview path does not satisfy this; choose a supported full deployment path |
| SaaS serving mutually untrusting customers | Needs strengthened admission, runtime isolation, egress, and business permissions; cannot rely on platform Namespaces alone |
| Needs interruption-free upgrades, automatic rollback, and strict fault isolation | Current update and storage contracts require additional evaluation; cannot be assumed by default |
| Wants unified model billing, task evaluation, and full-path tracing | These capabilities must be built separately; cannot be inferred from the Enterprise name |

For an enterprise pilot, I would first settle four things: who manages trusted drivers and images; who owns backup and recovery for the database, Secrets, and state volumes; who approves the business tools Agents may call; and who handles disposition after real task failures. Then verify the full path with a small, recoverable workload, confirm that upgrade interruptions and recovery times meet business requirements, and only then expand the deployment.

The most valuable aspect of OpenClaw Enterprise is that it advances agents from a set of configuration files and background processes into workloads with identity, versioning, authorization, and coordination records. This provides a clear starting point for platform engineering. Whether it can serve as a production foundation for an enterprise depends on whether the isolation, recovery, and task governance required by the enterprise can be aligned item by item with the current implementation.

## References

- [OpenClaw Enterprise repository][repo] and the [fixed source snapshot analyzed in this article][snapshot].
- [Concepts][concepts], [Controller][controller], and the [AgentRevision lifecycle][revisions].
- [ComputeDriver current deployment matrix][compute-matrix], [Driver selection][driver-selection], and [design implementation status][driver-design].
- [Runtime security boundaries][runtime-security], [Kubernetes storage and credentials][storage].
- [Kubernetes Setup][k8s-setup], [workspace routing][workspace-routing], and [production handoff][handoff].
- [Metric definitions][metrics], [Prometheus collection][metrics-scrape], and [logging and observability][observability].
- [Local quick start][quickstart] and [deploying your first agent][first-agent].

[repo]: https://github.com/openclaw/openclaw-enterprise
[snapshot]: https://github.com/openclaw/openclaw-enterprise/tree/b195e54e9b0ce98ead2b2306015a5209325e837b
[readme]: https://github.com/openclaw/openclaw-enterprise/blob/b195e54e9b0ce98ead2b2306015a5209325e837b/README.md
[concepts]: https://github.com/openclaw/openclaw-enterprise/blob/b195e54e9b0ce98ead2b2306015a5209325e837b/docs/guides/concepts.md
[controller]: https://github.com/openclaw/openclaw-enterprise/blob/b195e54e9b0ce98ead2b2306015a5209325e837b/docs/reference/controller.md
[namespaces]: https://github.com/openclaw/openclaw-enterprise/blob/b195e54e9b0ce98ead2b2306015a5209325e837b/docs/reference/namespaces.md
[revisions]: https://github.com/openclaw/openclaw-enterprise/blob/b195e54e9b0ce98ead2b2306015a5209325e837b/docs/guides/topics/agent-revisions.md
[queue-source]: https://github.com/openclaw/openclaw-enterprise/blob/b195e54e9b0ce98ead2b2306015a5209325e837b/packages/occ/src/state/postgres-work-queue.ts
[k8s-source]: https://github.com/openclaw/openclaw-enterprise/blob/b195e54e9b0ce98ead2b2306015a5209325e837b/apps/controller/src/drivers/compute/kubernetes/index.ts
[k8s-driver]: https://github.com/openclaw/openclaw-enterprise/blob/b195e54e9b0ce98ead2b2306015a5209325e837b/docs/reference/drivers/kubernetes-compute.md
[version-test]: https://github.com/openclaw/openclaw-enterprise/blob/b195e54e9b0ce98ead2b2306015a5209325e837b/tests/conformance/kubernetes-preflight.test.mjs
[driver-design]: https://github.com/openclaw/openclaw-enterprise/blob/b195e54e9b0ce98ead2b2306015a5209325e837b/docs/design/drivers.md
[driver-selection]: https://github.com/openclaw/openclaw-enterprise/blob/b195e54e9b0ce98ead2b2306015a5209325e837b/docs/reference/drivers/selection.md
[compute-matrix]: https://github.com/openclaw/openclaw-enterprise/blob/b195e54e9b0ce98ead2b2306015a5209325e837b/docs/reference/drivers/compute-matrix.md
[runtime-security]: https://github.com/openclaw/openclaw-enterprise/blob/b195e54e9b0ce98ead2b2306015a5209325e837b/docs/reference/security/runtime-isolation.md
[storage]: https://github.com/openclaw/openclaw-enterprise/blob/b195e54e9b0ce98ead2b2306015a5209325e837b/docs/reference/drivers/kubernetes-compute/storage-and-credentials.md
[authentication]: https://github.com/openclaw/openclaw-enterprise/blob/b195e54e9b0ce98ead2b2306015a5209325e837b/docs/reference/authentication.md
[k8s-setup]: https://github.com/openclaw/openclaw-enterprise/blob/b195e54e9b0ce98ead2b2306015a5209325e837b/docs/guides/kubernetes-setup.md
[workspace-routing]: https://github.com/openclaw/openclaw-enterprise/blob/b195e54e9b0ce98ead2b2306015a5209325e837b/docs/guides/deploy/workspace-routing.md
[handoff]: https://github.com/openclaw/openclaw-enterprise/blob/b195e54e9b0ce98ead2b2306015a5209325e837b/docs/guides/deploy/production-handoff.md
[metrics]: https://github.com/openclaw/openclaw-enterprise/blob/b195e54e9b0ce98ead2b2306015a5209325e837b/docs/reference/metrics.md
[metrics-scrape]: https://github.com/openclaw/openclaw-enterprise/blob/b195e54e9b0ce98ead2b2306015a5209325e837b/docs/guides/observability/metrics.md
[observability]: https://github.com/openclaw/openclaw-enterprise/blob/b195e54e9b0ce98ead2b2306015a5209325e837b/docs/guides/observability.md
[quickstart]: https://github.com/openclaw/openclaw-enterprise/blob/b195e54e9b0ce98ead2b2306015a5209325e837b/docs/guides/quickstart.md
[first-agent]: https://github.com/openclaw/openclaw-enterprise/blob/b195e54e9b0ce98ead2b2306015a5209325e837b/docs/guides/first-agent.md
[license]: https://github.com/openclaw/openclaw-enterprise/blob/b195e54e9b0ce98ead2b2306015a5209325e837b/LICENSE
[chart]: https://github.com/openclaw/openclaw-enterprise/blob/b195e54e9b0ce98ead2b2306015a5209325e837b/deploy/helm/openclaw-enterprise/Chart.yaml
