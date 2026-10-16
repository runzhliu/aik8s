---
title: "Agent Sandbox Selection and Architecture Analysis"
description: "A systematic selection approach from threat models, lifecycle control planes, gVisor, Kata, microVMs to managed sandboxes"
status: evolving
last_reviewed: 2026-08-29
---

# Agent Sandbox Selection and Architecture Analysis

When an Agent can execute Shell commands, run user code, clone repositories, open web pages, or call external tools, the sandbox is no longer an optional optimization but part of the production architecture. However, "Agent Sandbox" may refer to a Kubernetes lifecycle controller, an isolation runtime, a full VM, or a managed execution API; if you do not first decompose it into layers, it is easy to compare projects with different responsibilities against each other.

This chapter provides a selection methodology for Kubernetes platforms. Key conclusions first:

- If you already have a mature Kubernetes platform and need data to remain in your own environment, prioritize evaluating **Kubernetes SIG Agent Sandbox + gVisor**;
- If you execute strongly adversarial code, tenants do not trust each other, or compliance requirements are higher, prioritize evaluating **Agent Sandbox + Kata Containers/dedicated VM node pools**;
- If you need an E2B-compatible API, self-hosted KVM MicroVM, templates/snapshots, and high-density execution, and your team can maintain the host kernel and eBPF, you may evaluate **CubeSandbox**;
- If the product is still in the validation phase and the team does not want to maintain the runtime and sandbox control plane, prioritize using **managed APIs such as E2B, Modal, Daytona** for small-scale validation;
- To protect development machines with local Coding Agents, you can use **Docker Sandboxes** and similar local microVM tools; these are not server-side multi-tenant control planes;
- Ordinary Pods, `seccomp`, non-Root, and NetworkPolicy are the baseline required by every option, but they cannot alone serve as sufficient isolation proof for strongly adversarial code.

All of these conclusions must be validated through your own compatibility, security, and performance testing; project names cannot be treated as security certifications.

## 1. First Decompose into Three Layers

```text
Agent / Application
        │
        ▼
Sandbox API 与生命周期控制面
├── create / claim / assign / pause / resume / delete
├── template / snapshot / workspace / warm pool
└── quota / tenant / audit / metrics
        │
        ▼
执行隔离边界
├── runc + Linux namespaces / user namespace
├── gVisor user-space kernel
├── Kata / Firecracker microVM
└── full VM
        │
        ▼
外部能力与数据边界
├── Egress Proxy / Tool Gateway
├── short-lived identity / approval
├── artifact scanning / trusted CI
└── object storage / database / Git / browser
```

### 1. Lifecycle Control Plane

Responsible for stable identity, create/reclaim, templates, pre-warming, state, and persistent workspaces. The Kubernetes SIG Apps Agent Sandbox, managed platform Sandbox APIs, and self-built Pod/VM Factories all belong to this layer.

### 2. Isolation Runtime

Determines what kernel boundary untrusted processes share with the host. `runc`, gVisor, Kata Containers, Firecracker, and full VMs belong to this layer.

### 3. Tool and Data Boundary

Determines which networks, secrets, files, and external side effects a Sandbox can access. NetworkPolicy, Egress Proxy, Tool Gateway, short-lived credentials, and approval systems belong to this layer.

A lifecycle controller does not automatically provide strong isolation; a microVM also does not automatically prevent data exfiltration or accidental deletion of production resources. The three layers must be combined.

## 2. Write the Threat Model First, Then Look at Products

### 1. What Needs to Be Protected

- Kubernetes node kernels, kubelet, container runtimes, and other Pods;
- Cloud metadata, node credentials, ServiceAccount Tokens, and production Secrets;
- User source code, data, Prompts, model inputs, and session workspaces;
- Internal databases, Git, artifact repositories, CI/CD, and SaaS APIs;
- Billing, CPU, GPU, storage, bandwidth, and external API quotas;
- Audit evidence and confidentiality between tenants.

### 2. Where Do Untrusted Inputs Come From

| Source | Typical Risks |
| --- | --- |
| Model-generated code | Arbitrary commands, infinite loops, Fork Bombs, disk exhaustion |
| User-uploaded code | Malicious binaries, kernel exploits, dependency poisoning, data exfiltration |
| Third-party repositories | Installation scripts, Git Hooks, malicious tests, Prompt Injection |
| Web pages and documents | Indirect Prompt Injection, malicious file downloads, SSRF |
| Package managers | Typosquatting, supply chain attacks, install-time scripts |
| MCP/tool services | Unauthorized calls, malicious return values, long-lived Token leakage |

### 3. Risk Levels

| Level | Workload | Minimum Recommended Boundary |
| --- | --- | --- |
| L0: Trusted tasks | Fixed images, fixed code, read-only controlled APIs | Hardened Pod |
| L1: Semi-trusted scripts | Internal user code, controlled dependencies, no production permissions | User Namespace or gVisor; network denied by default |
| L2: Untrusted code | Public user code, third-party repositories, browser automation | gVisor or Kata; independent identity and Tool Gateway |
| L3: Strongly adversarial multi-tenant | Public code execution, tenants do not trust each other, sensitive data | Kata/microVM/full VM; dedicated node pools and network boundaries |
| L4: High regulation | Strong data residency, hardware trust, or confidential computing requirements | Dedicated cluster/account, VM, or Confidential Containers, with a dedicated threat review |

The same Agent can span multiple levels depending on the tool. For example, read-only search may be L1, executing tests from unfamiliar repositories is L2, and operating a production database requires an additional business authorization boundary that cannot be solved by a stronger runtime alone.

## 3. Twelve Selection Dimensions

Do not only compare startup speed and SDKs. At minimum, record the following dimensions:

| Dimension | Key Questions |
| --- | --- |
| Isolation boundary | Does it share the kernel with the host? Is the attack surface a syscall proxy, Guest Kernel, or Hypervisor? |
| Lifecycle | Are Claim, TTL, pause/resume, Warm Pool, orphan reclamation, and idempotent APIs available? |
| Startup path | How long do cold start, warm start, image pull, and workspace restore take respectively? |
| Workspace | How are ephemeral disks, PVCs, snapshots, Fork, encryption, erasure, and retention policies implemented? |
| Network | What is the default egress policy? Does it support CIDR, domains, proxies, and runtime changes? |
| Identity | Does the Sandbox automatically obtain cluster/cloud credentials? Can short-lived, per-tool-authorized identities be used? |
| Compatibility | Are `ptrace`, FUSE, Docker-in-Docker, browsers, systemd, and eBPF required? |
| Accelerators | Are GPU/TPU supported? Which isolation assumptions do device drivers weaken? |
| Density and cost | What is the fixed overhead per Sandbox, Warm Pool idle cost, node fragmentation, and control plane QPS? |
| Observability | Can creation phases, command execution, policy denials, network, resources, and reclamation be correlated to sessions? |
| Operational maturity | Are API stability, upgrade paths, CVE response, HA, backups, and Runbooks complete? |
| Lock-in and compliance | Where does data reside, can it be self-hosted, how portable is the API, and how do audit export and deletion proof work? |

## 4. Solution Landscape: Do Not Miscompare Across Layers

### 1. Self-Built Kubernetes Route

| Option | Lifecycle | Isolation Boundary | Advantages | Main Costs | Suitable For |
| --- | --- | --- | --- | --- | --- |
| Self-built Pod Factory + runc | Self-implemented | Shared host kernel | Simplest, best compatibility and density | Reclamation, pre-warming, state, and security all self-built | L0, low-scale internal tasks |
| Agent Sandbox + runc | Standard CRD/SDK | Shared host kernel | Kubernetes-native lifecycle, low migration cost | Agent Sandbox itself does not enhance kernel isolation | Trusted Agents, validate control plane first |
| Agent Sandbox + gVisor | Standard CRD/SDK | user-space kernel | Balanced isolation, density, and startup speed | Linux compatibility gaps exist; requires full testing | Most L1/L2 code execution |
| Agent Sandbox + Kata | Standard CRD/SDK | Per-Pod lightweight VM/Guest Kernel | Stronger kernel boundary, still integrated via RuntimeClass | Nodes, images, networking, storage, and observability are more complex | L2/L3, high-risk multi-tenant |
| KubeVirt/self-built VM Factory | Self-built or VM API | Full VM | Full Linux/Windows compatibility and clear VM boundary | Higher startup, density, image, and operational costs | Requires systemd, nested containers, or full OS |
| Direct Firecracker integration | Largely self-built | microVM/KVM | Deep optimization of startup, snapshots, and density | Firecracker is a VMM building block, not a complete Agent platform | Very large-scale systems with dedicated virtualization/platform teams |
| CubeSandbox | Built-in E2B-compatible API, scheduling, templates, snapshots, and networking | KVM MicroVM + independent Guest Kernel | Self-hosted, low latency, high density, relatively complete control plane and data plane | K8s delivery is still Preview; requires privileged/hostPID/hostPath, KVM/PVM, XFS, eBPF, and host modification capabilities | Teams with virtualization/kernel expertise needing a self-hosted MicroVM platform |

### 2. Managed or External Sandbox APIs

| Option | Public Positioning and Runtime | Advantages | Needs Verification | Better Suited For |
| --- | --- | --- | --- | --- |
| E2B | On-demand Linux VMs for Agents, Templates, and SDK; offers Terraform self-hosting route | Simple API, ecosystem focused on code execution/desktop, fast prototyping | Region, network policy, concurrency, data residency, self-hosting operations, and cost | Rapidly shipping Code Interpreter, Computer Use |
| Modal Sandboxes | gVisor by default; Beta VM Sandbox also available | SDK, images, network policy, snapshots, and elastic platform integration are complete | Default public egress policy, Beta feature status, snapshot/GPU limitations | Already using Modal or wanting minimal control plane maintenance |
| Daytona | Containers by default, with Linux/Windows VM and GPU Sandbox options | Multi-language SDK, snapshots/Fork, network restrictions, full development environment capabilities | Isolation assumptions of each Sandbox Class, region, quotas, pricing, and lock-in | Coding Agents, long-lived workspaces, VM/GPU options needed |
| Docker Sandboxes | Local microVMs, each Sandbox has an independent Docker daemon, filesystem, and network | Protects development machines, suitable for local Coding Agent workflows | Not a server-side multi-tenant scheduler or Kubernetes API | Developer desktops, local repository modifications |

Managed platform capabilities change rapidly. The table is only for identifying PoC candidates; before procurement, the security/data terms in the target region, plan, and contract must govern.

CubeSandbox and the Kubernetes SIG Agent Sandbox are not the same project: the former is a vertical platform with a KVM Hypervisor, E2B-compatible API, templates, snapshots, proxies, and eBPF networking; the latter manages Kubernetes workload lifecycle via CRD/Controller and composes runc, gVisor, or Kata through RuntimeClass. CubeSandbox `v0.7.0` Kubernetes prerequisites, the 60ms benchmark methodology, and production blockers are covered in [CubeSandbox Kubernetes Deployment Requirements and Production Evaluation](cubesandbox-kubernetes.md).

## 5. Deep Dive: Kubernetes SIG Agent Sandbox

### 1. What It Solves

Agent Sandbox uses Kubernetes CRDs to express execution environments with stable identity, singleton semantics, and persistence. Core and extension objects include:

| Object | Responsibility |
| --- | --- |
| `Sandbox` | Desired state and lifecycle of a single stateful Sandbox |
| `SandboxTemplate` | Platform-maintained Pod, RuntimeClass, volume, and policy templates |
| `SandboxWarmPool` | Pre-starts a specified number of Sandboxes to reduce allocation latency |
| `SandboxClaim` | User-side request interface to acquire a Sandbox from the Warm Pool |

It also provides Python/Go Clients, file and command operations, pause/resume, scheduled deletion, and PVC template capabilities. Reference: [Agent Sandbox Documentation](https://agent-sandbox.sigs.k8s.io/docs/).

### 2. Current Maturity

As of 2026-08-03, the project's latest release line is `v0.5.4`, and the CRD has been upgraded to `v1beta1`, but the project itself is still pre-1.0. `v0.5.0` and `v0.5.1` previously exhibited state races affecting Warm-start Claim upgrades, which were fixed in subsequent releases. This indicates it is suitable for serious validation, but production use still requires:

- Pinning Controller, CRD Manifest, and SDK versions;
- Backing up all CRs and associated PVC metadata;
- Rehearsing upgrades in environments with active Claims and Warm Pools;
- Checking CRD `storedVersions` and Conversion Webhooks;
- Maintaining a version compatibility matrix and rollback procedures;
- Avoiding automatic tracking of `latest` or main-branch Manifests.

Version and upgrade information is available in [Agent Sandbox Releases](https://github.com/kubernetes-sigs/agent-sandbox/releases) and the [v1alpha1 to v1beta1 Migration Guide](https://agent-sandbox.sigs.k8s.io/docs/getting_started/api-migration-guide/).

### 3. Advantages

- Reuses the Kubernetes Namespace, RBAC, Quota, CNI, CSI, Admission, and audit systems;
- The Lifecycle API is decoupled from the specific RuntimeClass, allowing platform templates across runc, gVisor, and Kata;
- `SandboxClaim` hides the underlying Pod configuration, allowing the platform to control which fields users may override;
- The Warm Pool suits interactive Agents' startup latency requirements;
- PVC Templates support independent persistent workspaces per Sandbox;
- State enters the Kubernetes API and can be managed with existing GitOps and observability tooling.

### 4. Limitations

- It is a lifecycle control plane, not a security runtime or Prompt Injection protection system;
- The Warm Pool trades idle resources for latency; Pool counts can multiply rapidly across Runtime, image, and resource specifications;
- CRDs, Controller, Router, SDK, and RuntimeClass add upgrade and failure surface area;
- The real-world effectiveness of NetworkPolicy depends on the CNI; domain-level egress typically still requires a proxy;
- Persistent PVCs can cause malicious files, downloaded credentials, and poisoned state to survive across sessions;
- If the Sandbox API has excessive permissions, users may bypass template policy through overridable Pod fields;
- The pre-1.0 phase may still introduce API and upgrade behavior changes.

### 5. When to Choose It

Suitable when:

- Kubernetes is already the organization's standard operating platform;
- The team can operate CRDs, Controllers, CNI, RuntimeClass, and node images;
- Data, network, or identity must remain in your own cloud account/data center;
- Per-session independent Workspaces, Warm Pools, and tenant quotas are required;
- Sandbox volume is sufficient to amortize platform construction costs;
- You want the lifecycle API decoupled from underlying runtimes such as gVisor/Kata.

In the following cases, using a managed solution first may be more reasonable:

- The product has not yet proven demand; only a few dozen concurrent Sandboxes are needed;
- No container runtime, kernel security, or Kubernetes Operator operations capability;
- Desktop, browser, snapshot, PTY, and file APIs are needed immediately;
- Data boundaries, pricing, and API lock-in are acceptable.

## 6. How to Choose an Isolation Runtime

### 1. Hardened runc Pod

The minimum baseline includes:

- `runAsNonRoot`, `allowPrivilegeEscalation: false`, Drop All Capabilities;
- `seccompProfile: RuntimeDefault`, AppArmor/SELinux on demand;
- Prohibit HostPID, HostNetwork, HostIPC, HostPath, and privileged devices;
- `automountServiceAccountToken: false`;
- Read-only root filesystem, mapping writable paths to quota-limited `emptyDir`/PVC;
- Hard limits on CPU, memory, PID, Ephemeral Storage, and execution duration;
- Deny inbound and outbound traffic by default;
- Dedicated low-trust node pool, avoiding colocation with the control plane or sensitive workloads.

Pod User Namespaces are stable in Kubernetes 1.36 and can be used via `hostUsers: false` to map in-container UID/GID to unprivileged ranges on the host, reducing the impact after a partial escape. It is an important hardening layer, but it still does not equal an independent Guest Kernel. Reference: [Kubernetes User Namespaces](https://kubernetes.io/docs/concepts/workloads/pods/user-namespaces/).

### 2. gVisor

gVisor's `runsc` provides a user-space kernel (Sentry) between the application and the host Linux Kernel, reducing the attack surface of applications directly using host system call interfaces, and can be integrated via Kubernetes `RuntimeClass`.

Advantages:

- Generally closer to container startup speed and density than full VMs;
- Compatible with most ordinary Linux user-space programs;
- Direct integration with Kubernetes/containerd;
- Suitable for large numbers of short-lived Python, Node.js, compilation, and browser-type executions;
- Supports specific NVIDIA GPU/Driver combinations and CDI, but requires separate validation.

Limitations:

- Some filesystems, `iptables`/`nftables`, `io_uring`, devices, and KVM capabilities are incomplete;
- Nested virtualization is not supported; complex Docker-in-Docker and low-level system tools may fail;
- Performance overhead is strongly correlated with syscall, file I/O, and network patterns; it cannot be inferred from CPU benchmarks alone;
- GPU interacts with host drivers via `nvproxy`; the support matrix and Driver patching remain part of the security plan.

First review [gVisor Kubernetes Quick Start](https://gvisor.dev/docs/user_guide/quick_start/kubernetes/), [Compatibility](https://gvisor.dev/docs/user_guide/compatibility/), and [GPU Support](https://gvisor.dev/docs/user_guide/gpu/).

### 3. Kata Containers

Kata integrates with Kubernetes via OCI/CRI and containerd/CRI-O, running Pods in lightweight VMs with independent Guest Kernels, and is selected via `RuntimeClass`.

Advantages:

- The boundary is closer to a VM compared to a shared host kernel;
- Pod API, image format, and Kubernetes scheduling remain consistent;
- Usually more natural than gVisor for tasks requiring more complete Linux Kernel semantics;
- Can be combined with the Confidential Containers roadmap.

Costs:

- Per-Pod VM memory, startup, Guest Image, and Hypervisor overhead;
- CNI, CSI, DNS, logging, monitoring, debugging, and upgrade paths are more complex;
- Nodes must support and correctly configure hardware virtualization;
- GPU/device passthrough expands the host driver and device surface; hardware, Runtime, and Driver combination validation is mandatory;
- Warm Pool, Snapshot, and PVC behavior must be tested against the actual Hypervisor and cloud environment.

Architecture reference: [Kata Containers Architecture](https://github.com/kata-containers/kata-containers/blob/main/docs/design/architecture/README.md).

### 4. Firecracker and Full VMs

Firecracker is a minimal VMM based on KVM, emphasizing microVM isolation, low overhead, and fast startup, and comes with `jailer`. It can serve as the underlying technology for platforms such as Kata, but it will not provide tenant management, image building, network policy, workspaces, APIs, Warm Pools, auditing, or reclamation control planes on your behalf. Reference: [Firecracker](https://firecracker-microvm.github.io/).

Building a platform directly around Firecracker is only recommended when all of the following conditions are met:

- Sandbox scale is sufficient to justify the cost of building in-house;
- Dedicated virtualization, Kernel, networking, and storage engineering capability exists;
- Standard Kata/KubeVirt or managed offerings cannot meet the goals;
- Long-term maintenance of Guest Kernel, Snapshot compatibility, security patches, and host capacity management is feasible.

When a full OS, Windows, systemd, complex nested containers, or VM-level operations are required, KubeVirt or cloud VM APIs can be evaluated. The cost is higher startup latency, capacity fragmentation, and image management complexity.

## 7. Runtime Decision Matrix

| Requirement | runc + Hardening | gVisor | Kata/microVM | Full VM |
| --- | --- | --- | --- | --- |
| Ordinary Python/Node code | Best compatibility | Usually suitable | Suitable | Suitable but heavyweight |
| Strongly adversarial multi-tenancy | Not recommended alone | Medium-high, requires threat review | High, still requires perimeter governance | High, still requires perimeter governance |
| Cold start and high density | Optimal | Good | Medium | Weak |
| Full Linux Kernel semantics | Yes, but shared host | Has compatibility gaps | Fairly complete | Most complete |
| Docker/systemd/eBPF | Easy but risky | Often restricted | Requires validation | Most suitable |
| GPU | Best native ecosystem | Only combinations within support matrix | Requires passthrough/vendor validation | Depends on cloud/VM model |
| Kubernetes integration | Native | RuntimeClass | RuntimeClass | KubeVirt/external VM API |
| Node operations complexity | Low | Medium | High | High |
| Recommended risk level | L0/L1 | L1/L2 | L2/L3 | L3/L4 |

"High" here refers to relative isolation potential, not a security guarantee. Runtime vulnerabilities, misconfiguration, open networks, and leaked credentials can all bypass the intended boundaries.

## 8. How to Choose a Managed Platform

### 1. E2B

E2B provides Agent-oriented Linux VMs, Templates, command/file SDKs, and desktop usage modes, and also publishes its infrastructure repository and Terraform self-hosting roadmap. It is suitable for quickly implementing Code Interpreter and Computer Use. Reference: [E2B Documentation](https://www.e2b.dev/docs) and [E2B GitHub](https://github.com/e2b-dev/E2B).

The PoC should validate:

- Sandbox creation/restore P50, P95, and concurrency quotas;
- Default values for public ingress and egress restrictions;
- Template building and supply chain;
- Volume/Snapshot encryption, deletion, and region;
- API Key tenant isolation and least privilege;
- BYOC/self-hosting support scope and operations responsibility;
- Cost of long sessions, desktop, and batch tasks.

### 2. Modal Sandboxes

Modal's default Sandbox uses gVisor and provides network blocking, CIDR/domain Allowlists, snapshots, Volumes, and multi-language SDKs; VM Sandboxes are still marked as Beta. The official documentation also states that the default Sandbox can access the public internet, so "secure by default" should not be understood as "no egress by default." Reference: [Modal Sandboxes](https://modal.com/docs/guide/sandboxes) and [Networking and security](https://modal.com/docs/guide/sandbox-networking).

Suitable for teams already using the Modal compute platform or wanting images, elasticity, and Sandboxes in a single managed experience. The PoC should focus on testing network policy, snapshot limitations, GPU/VM feature status, and cost models.

### 3. Daytona

Daytona provides container Sandboxes, Linux/Windows VMs, GPU Sandboxes, Snapshot/Fork, persistent Volumes, and multi-language SDKs, positioning closer to a full Agent Computer/Coding Workspace. Reference: [Daytona Sandboxes](https://www.daytona.io/docs/en/sandboxes/) and [Architecture](https://www.daytona.io/docs/en/architecture/).

When selecting, do not only look at the unified API; separately confirm the isolation boundaries, pause/snapshot semantics, data location, and network policy for Container, VM, Windows, and GPU Classes. The official network restrictions support Block All, CIDR, and domain Allowlists, but DNS, redirects, proxies, and private network access behavior still need to be validated.

### 4. Docker Sandboxes

Docker Sandboxes use microVMs on the developer machine to isolate Coding Agents, with each environment having an independent Docker daemon, filesystem, and network. They are suitable for protecting the local host and enforcing unified organizational development policies, but do not handle server-side Namespaces, tenant quotas, cross-node scheduling, API concurrency, or production reclamation. Reference: [Docker Sandboxes](https://docs.docker.com/ai/sandboxes/) and [Security model](https://docs.docker.com/ai/sandboxes/security/).

## 9. Four Recommended Combinations

### Combination A: Internal Agent, Low-Risk Controlled Tools

```text
Agent Control Plane
  → Agent Sandbox 或自建 Pod Factory
  → Hardened runc / User Namespace
  → 只访问 Tool Gateway
```

Conditions: images and code are trusted, no public user code, no direct production write permissions. Network denial by default, short-lived identities, and hard resource limits are still required.

### Combination B: General Untrusted Code Execution

```text
Agent Control Plane
  → SandboxClaim
  → SandboxWarmPool
  → Agent Sandbox + gVisor RuntimeClass
  → Egress Proxy / Tool Gateway
  → Artifact Scan → Trusted CI
```

This is the default PoC starting point for an existing Kubernetes platform. It strikes a balance between isolation, density, and platform consistency.

### Combination C: Strongly Adversarial and Sensitive Tenants

```text
独立低信任 Kubernetes Cluster / Node Pool
  → Agent Sandbox
  → Kata / microVM RuntimeClass
  → 每会话独立身份与加密 Workspace
  → 强制 Egress Proxy
  → 与生产系统跨账户 Tool Broker
```

The node pool does not run the control plane, Secret managers, or sensitive workloads. Even if a Sandbox breaks through the Guest, it only enters a low-trust failure domain.

### Combination D: Product Validation or Small-Scale Managed Service

```text
Application Backend
  → E2B / Modal / Daytona API
  → Hosted Sandbox
  → 自有 Tool Gateway
```

Even if the execution environment is managed, tool authorization, user identity, approval, budget, and business auditing should still be handled by your own control plane, avoiding placing all long-lived credentials inside the Sandbox.

## 10. Kubernetes Template Baseline

The following only shows structure, not a complete list ready for production. It requires the Agent Sandbox `v0.5.x`, a RuntimeClass named `gvisor`, and an internal image with a pinned Digest prepared.

```yaml
apiVersion: extensions.agents.x-k8s.io/v1beta1
kind: SandboxTemplate
metadata:
  name: python-gvisor-restricted
  namespace: agent-tenants
spec:
  podTemplate:
    metadata:
      labels:
        aik8s.run/sandbox-policy: restricted
    spec:
      runtimeClassName: gvisor
      automountServiceAccountToken: false
      containers:
        - name: sandbox
          image: registry.example.com/agent/python@sha256:<digest>
          resources:
            requests:
              cpu: "500m"
              memory: 1Gi
              ephemeral-storage: 2Gi
            limits:
              cpu: "2"
              memory: 4Gi
              ephemeral-storage: 8Gi
          securityContext:
            allowPrivilegeEscalation: false
            capabilities:
              drop: ["ALL"]
            runAsNonRoot: true
            readOnlyRootFilesystem: true
            seccompProfile:
              type: RuntimeDefault
          volumeMounts:
            - name: workspace
              mountPath: /workspace
            - name: tmp
              mountPath: /tmp
      volumes:
        - name: workspace
          emptyDir:
            sizeLimit: 4Gi
        - name: tmp
          emptyDir:
            sizeLimit: 1Gi
---
apiVersion: extensions.agents.x-k8s.io/v1beta1
kind: SandboxWarmPool
metadata:
  name: python-gvisor-restricted
  namespace: agent-tenants
spec:
  replicas: 2
  sandboxTemplateRef:
    name: python-gvisor-restricted
---
apiVersion: extensions.agents.x-k8s.io/v1beta1
kind: SandboxClaim
metadata:
  name: session-example
  namespace: agent-tenants
spec:
  warmPoolRef:
    name: python-gvisor-restricted
```

Production environments must also use Admission Policy to restrict the Templates, RuntimeClasses, images, volumes, labels, and Annotations users can select, prohibiting tenants from directly creating arbitrary Pods or modifying `SandboxTemplate`.

### Network Denied by Default

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: sandbox-default-deny
  namespace: agent-tenants
spec:
  podSelector:
    matchLabels:
      aik8s.run/sandbox-policy: restricted
  policyTypes: [Ingress, Egress]
```

After that, only open:

- To the controlled DNS Resolver;
- To the fixed Service/CIDR of the Tool Gateway/Egress Proxy;
- Required observability egress;
- Reviewed object storage or internal Registry.

Domain Allowlists should be resolved and checked against the final connection target at the proxy layer, not relying solely on static IPs or the initial DNS response.

## 11. Identity and Tool Boundaries

Recommended call chain:

```text
Sandbox 无长期凭据
  → 使用会话身份请求 Tool Gateway
  → Gateway 校验 user / tenant / session / tool / args
  → 策略或人工审批
  → 交换一次性下游凭据
  → 执行动作并记录结果摘要
  → 凭据到期
```

The following must be prohibited:

- Mounting the Kubernetes ServiceAccount Token by default;
- Writing cloud admin Keys, Git Personal Tokens, or database passwords into images/Workspaces;
- Sandbox directly accessing the cloud metadata service;
- The Agent deciding on its own whether to bypass approval;
- Tool return content modifying platform policy;
- The Sandbox identity simultaneously holding production deployment permissions.

## 12. Workspace, Snapshot, and Persistence

A workspace is not better the more persistent it is. Divide data into:

| Data | Recommended Policy |
| --- | --- |
| Base Runtime | Read-only, pinned Digest, signature verification |
| Input repository/documentation | Read-only snapshot or per-session independent Clone |
| `/tmp`, build intermediates | Quota-limited `emptyDir`, deleted at session end |
| User workspace | Per-user/per-session independent PVC, with explicit TTL and encryption |
| Package/model cache | Read-only shared or produced by trusted builds; tenants must not write to each other |
| Output artifacts | Upload to a quarantine zone, scanned, then rebuilt by trusted CI |
| Audit evidence | Written to external tamper-evident storage, not dependent on Sandbox disk |

Pause, resume, and snapshots retain state written by attackers. Before restoring, bind to the original tenant, Template/Runtime version, and policy version; do not return Sandboxes of unknown state to the Warm Pool for other tenants.

## 13. Warm Pool Capacity Model

The Warm Pool is not a single global number, but a Cartesian product of multiple dimensions:

```text
Pool 数量
= Region × RuntimeClass × Base Image × CPU/Memory Class × Tenant Tier
```

If multiple instances are kept for every combination, idle cost will quickly exceed the cold-start benefit. Recommendations:

1. Only build Pools for high-frequency Templates;
2. Merge compatible Runtime Images to avoid a separate set per Agent;
3. Adjust based on Claim arrival rate and target hit rate over the past 5–15 minutes;
4. Record Warm Hit, Cold Fallback, idle seconds, and waiting P95;
5. Set a total budget and tenant limits for the Pool;
6. When publishing a new image, first build a new Pool, drain the old Pool, and do not mix in place;
7. When upgrading the controller, test Adoption and state retention of existing Warm Sandboxes.

## 14. Mandatory PoC Test Items

### 1. Functional Compatibility

- Python/Node/Java and target binaries;
- Git Clone, package installation, compilation, testing, and browser;
- PTY, signals, subprocesses, file Watch, Unix Socket;
- Special requirements such as FUSE, Docker, systemd, eBPF, GPU;
- Chinese paths, large files, long output, and concurrent commands;
- Disconnect-reconnect, pause-resume, and Workspace remounting.

### 2. Performance

| Metric | At Minimum Distinguish |
| --- | --- |
| Create-to-Ready | Cold node, hot node, cold image, hot image, Warm Hit |
| Claim-to-Assigned | Controller Queue, API latency, Pool hit |
| Exec latency | First vs. subsequent commands, short vs. long commands |
| File performance | Small files, sequential read/write, Metadata, Workspace restore |
| Network | DNS, TLS, proxy, throughput, connection count, and rejected requests |
| Density | Sandboxes per node, RSS, CPU Steal, Daemon overhead |
| Reclamation | Latency from TTL to actual resource/PVC/route deletion |

Report P50/P95/P99, not just the best startup time.

### 3. Security Validation

- Attempt to access the Kubernetes API, cloud metadata, Node IP, kubelet, and other Pods;
- Attempt to read ServiceAccount, environment variables, Host files, and neighboring tenant Workspaces;
- Test Capability, Mount, Namespace, `ptrace`, devices, and dangerous Syscalls;
- Test DNS Rebinding, HTTP Redirect, IPv6, and proxy bypass;
- Execute Fork Bomb, disk fill, log flood, and connection flood;
- Verify cleanup after Runtime crash, node restart, and Controller restart;
- Verify that Prompt Injection cannot expand Tool permissions;
- Have the security team perform an escape and supply chain review against the target Runtime version.

### 4. Operations and Upgrades

- CRD/Controller/SDK version combinations across releases;
- Rolling upgrades with active Claims, Warm Pool, and PVCs;
- Multi-replica failures of Controller and Router;
- Consistency between Sandbox and actual Pods after etcd recovery;
- CNI, CSI, RuntimeClass, and node image upgrades;
- Version rollback and migration plans when downgrade is not possible;
- Cleanup of Orphan Pods, PVCs, Services, NetworkPolicies, and routes.

## 15. Scoring Template

Set weights by business needs first, then score, to avoid "most features wins" automatically.

| Category | Example Weight | Scoring Notes |
| --- | ---: | --- |
| Security and Isolation | 30% | Threat model, runtime boundary, network, identity, audit |
| Compatibility | 15% | Target code, browsers, tools, GPU, Docker |
| Latency and Performance | 15% | Cold/warm start, execution, I/O, network, and density |
| Lifecycle | 10% | TTL, Warm Pool, pause, snapshot, persistent state |
| Operational Maturity | 15% | Upgrades, HA, observability, Runbooks, CVE response |
| Cost | 10% | Compute, Idle, Storage, Egress, License, manpower |
| Portability and Compliance | 5% | Self-hosting, data region, API, deletion, contracts |

```text
总分 = Σ(单项 1～5 分 × 权重)
```

Security hard gates should be independent of the total score: any candidate that cannot meet isolation, data residency, or deletion requirements must not advance to the next round, even with a high composite score.

## 16. Recommended Decision Tree

```text
是否只保护开发者本机？
├─ 是 → Docker Sandboxes / 本地 VM
└─ 否
   │
   ├─ 产品是否仍在验证、缺少平台团队？
   │  ├─ 是 → E2B / Modal / Daytona PoC
   │  └─ 否
   │
   ├─ 是否必须自托管或复用 Kubernetes 治理？
   │  ├─ 否 → 托管与自建做 TCO/合规对比
   │  └─ 是 → Kubernetes Agent Sandbox
   │
   ├─ 是否执行公开、恶意或租户互不信任的代码？
   │  ├─ 否 → Hardened Pod / User Namespace / gVisor
   │  └─ 是
   │
   ├─ 是否需要完整 Kernel、Docker、systemd 或强 VM 边界？
   │  ├─ 否 → Agent Sandbox + gVisor
   │  └─ 是 → Agent Sandbox + Kata，或 KubeVirt/VM
   │
   └─ 是否属于高监管/高价值环境？
      ├─ 否 → 独立低信任节点池
      └─ 是 → 独立集群/账户 + VM/Confidential Containers
```

## 17. Common Misconceptions

### "Using an Agent Sandbox CRD means it's secure"

Wrong. The CRD manages the lifecycle; actual isolation depends on RuntimeClass, Pod configuration, nodes, network, and identity.

### "With microVMs, NetworkPolicy is unnecessary"

Wrong. VM escape and data exfiltration, SSRF, and accidental resource deletion are different risks. Network and tool authorization must still be minimized.

### "A domain Allowlist is enough for safe public internet access"

Wrong. You also need to handle DNS Rebinding, Redirect, CDN, IPv6, proxy protocols, and downloaded content. High-risk traffic should go through an L7 Egress Proxy.

### "A bigger Warm Pool means a better experience"

Wrong. Pools amplify idle costs, stale image exposure, and upgrade complexity. Plan dynamically based on hit rate and latency SLOs.

### "Long-lived Tokens can be stored inside the Sandbox since it will be deleted anyway"

Wrong. Tokens can be exfiltrated over the network, written to logs, snapshots, or PVCs. Prefer Tool Gateway and one-time credentials.

### "Managed platforms require no operations, so no threat model is needed"

Wrong. The managed provider is responsible for part of the execution infrastructure; users are still responsible for business authorization, data classification, secrets, Prompt Injection, compliance, and deletion verification.

## 18. Launch Checklist

- [ ] Classified code, users, data, and tools by L0–L4;
- [ ] Selected lifecycle control plane, isolation runtime, and tool/data boundaries separately;
- [ ] Agent Sandbox/Runtime/SDK/Node Image versions pinned with a compatibility matrix;
- [ ] Tenants cannot create arbitrary Pods, Templates, RuntimeClasses, or mount HostPath;
- [ ] Sandbox has no ServiceAccount Token or long-lived external credentials by default;
- [ ] Pod Security, Seccomp, Capability, PID, and resource limits are enabled;
- [ ] Network defaults to deny, allowing only DNS, Tool Gateway, and necessary observability egress;
- [ ] Workspaces, snapshots, PVCs, caches, and logs have TTL, encryption, quotas, and deletion proof;
- [ ] Warm Pool has hit rate, idle cost, image rotation, and Drain policies;
- [ ] Artifacts only enter the quarantine zone, and are rebuilt and signed by trusted CI after scanning;
- [ ] Metrics cover creation, allocation, commands, policies, network, resources, and reclamation;
- [ ] Runtime/Controller/Node failures and CRD upgrades have been tested;
- [ ] Escape, egress, resource exhaustion, and Prompt Injection security tests have been performed;
- [ ] Every candidate is benchmarked with the same set of real Agent tasks;
- [ ] Security hard gates are independent of feature and cost total scores.

## Official References

- [Kubernetes SIG Agent Sandbox](https://agent-sandbox.sigs.k8s.io/docs/)
- [Agent Sandbox Releases](https://github.com/kubernetes-sigs/agent-sandbox/releases)
- [Kubernetes RuntimeClass](https://kubernetes.io/docs/concepts/containers/runtime-class/)
- [Kubernetes Security Checklist](https://kubernetes.io/docs/concepts/security/security-checklist/)
- [Kubernetes User Namespaces](https://kubernetes.io/docs/concepts/workloads/pods/user-namespaces/)
- [gVisor Kubernetes Guide](https://gvisor.dev/docs/user_guide/quick_start/kubernetes/)
- [gVisor Compatibility](https://gvisor.dev/docs/user_guide/compatibility/)
- [gVisor GPU Support](https://gvisor.dev/docs/user_guide/gpu/)
- [Kata Containers Architecture](https://github.com/kata-containers/kata-containers/blob/main/docs/design/architecture/README.md)
- [Firecracker](https://firecracker-microvm.github.io/)
- [E2B Documentation](https://www.e2b.dev/docs)
- [Modal Sandboxes](https://modal.com/docs/guide/sandboxes)
- [Daytona Sandboxes](https://www.daytona.io/docs/en/sandboxes/)
- [Docker Sandboxes](https://docs.docker.com/ai/sandboxes/)
- [CubeSandbox](https://github.com/TencentCloud/CubeSandbox)

## Further Reading

- [AI Agents, Sandboxes, and Tool Execution](../agentic-workloads.md): tool authorization, Prompt Injection, budgets, audit, and release boundaries.
- [AI Platform Security and Governance](../security-governance.md): cluster identity, Pod Security, supply chain, and tenant governance.
- [Production Reference Architecture](../guides/reference-architectures.md): end-to-end deployment locations for untrusted Agent tool execution.
- [CubeSandbox Kubernetes Deployment Requirements and Production Evaluation](cubesandbox-kubernetes.md): KVM/PVM, XFS, eBPF, Helm, 60ms benchmark methodology, and production launch boundaries.
