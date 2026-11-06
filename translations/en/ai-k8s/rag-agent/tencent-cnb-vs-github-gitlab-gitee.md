---
title: "What Is Tencent CNB? Comparing It with GitHub, GitLab, and Gitee"
description: Evaluate Tencent CNB and compare major development platforms across code collaboration, CI/CD, cloud development, AI agents, security boundaries, and cost
status: evolving
date: 2026-11-06
last_reviewed: 2026-11-06
---

# What Is Tencent CNB? Comparing It with GitHub, GitLab, and Gitee

## At a Glance

**CNB (Cloud Native Build) is more than a build tool, and it is not a Kubernetes distribution. It is a platform built around Git repositories, containerized CI/CD, remote development environments, and AI-assisted development.** The Community Edition is a publicly hosted cloud service; according to the official documentation, the Enterprise Edition is deployed in the enterprise's own Tencent Cloud VPC. CNB is worth evaluating alongside GitHub, GitLab, and Gitee, but the fact that they all host Git does not mean they have the same deployment models, permissions, or costs.

- Consider CNB if you want a single development entry point for code, pipelines, cloud development, and AI assistance, and its cloud service or Tencent Cloud VPC deployment boundary is acceptable.
- If global open-source collaboration and existing GitHub workflows are key constraints, evaluate GitHub first. If a self-managed development platform and runners are the main requirements, focus on comparing GitLab Self-Managed, GitHub Enterprise Server, and Gitee's private deployment offerings.
- NPC is an automated role to which tasks can be delegated, not a developer that needs no supervision. By default, it reads code and writes comments; it can write code, push branches, and create PRs only when work mode is enabled and permission requirements are met.
- As of **2026-11-06**, this article analyzes publicly available official material; **no account was used for hands-on evaluation, and no security audit or performance testing was performed**. Prices, quotas, regional availability, and feature requirements can change and should be checked before purchase.

## 1. What Layers Does the Product Have?

CNB's name emphasizes cloud-native builds, but its [official repository introduction](https://docs.cnb.cool/zh/repo/intro.md), [build introduction](https://docs.cnb.cool/zh/build/intro.md), and [AI feature introduction](https://docs.cnb.cool/zh/ai/intro.md) indicate that the discussion covers at least these layers:

| Layer | Capabilities and purpose | What does not follow automatically |
| --- | --- | --- |
| Code and collaboration | Git repositories, branch protection, Pull Requests, Issues, and version management | Migratable Git history does not mean PR comments, approval policies, and attachments will all migrate automatically |
| Builds and artifacts | Use `.cnb.yml` to describe events, Docker environments, and tasks; caches, plugins, and artifact repositories are available | Container-based execution does not imply sufficiently strong isolation for untrusted code |
| Cloud development | Remote development built on build capabilities, with connections from clients such as WebIDE, VS Code, and Cursor | A remote development environment is not automatically a production cluster and does not guarantee compatibility with every local extension |
| AI assistance | CodeBuddy NPC, CodeBuddy in cloud development, change/error analysis, knowledge bases, and more | Feature availability, data flows, models, and actual quality depend on the edition, configuration, and licensing |
| Enterprise governance | The platform hosts the Community Edition; the Enterprise Edition is deployed in a VPC within the enterprise's Tencent Cloud account and supports OAuth integration | This does not establish that the Enterprise Edition can be installed in any on-premises data center, nor does self-management of build nodes mean the platform can be self-deployed anywhere |

The [Enterprise Edition documentation](https://docs.cnb.cool/zh/enterprise.html) also lists prerequisites: NPC and some AI capabilities require a configured large language model; knowledge bases additionally require Elasticsearch and an embedding model. The documentation specifies requirements including OpenAI Chat Completions API compatibility, context length, and Tool Use; **interface compatibility is only a condition for integration, not proof that arbitrary models, agent tools, tool-call semantics, or data policies are seamlessly interchangeable**.

### What a Minimal Pipeline Looks Like

The following **teaching example has not been run on CNB** and is written according to the [official build syntax](https://docs.cnb.cool/zh/build/intro.md): after a push to the repository's `main` branch, it prints the Python version in the specified container image. It does not constitute a test or deployment and does not create production credentials.

```yaml
# .cnb.yml
main:
  push:
    - docker:
        image: python:3.13-slim
      stages:
        - python --version
```

As with a GitHub Actions workflow file or GitLab CI configuration, the key idea is to review triggers, environments, and steps alongside the code. However, the configuration syntax and event models differ, so the configuration must be rewritten for the platform. A production pipeline should also pin a trusted image digest, install and lock dependencies, run tests, control credentials, and verify branch and event permissions.

### Relationship with CODING

The [official CODING discontinuation announcement](https://coding.net/help/docs/admin/pay/price-adjustment.html), published on 2025-06-23, lists these milestones: the Standard Edition was discontinued on 2025-09-01, sales stopped on 2025-09-30, and renewals stopped on 2026-03-30; service is scheduled to end on 2028-09-30. The announcement describes CNB as the next-generation product, with development moving to CNB and collaboration, testing, documentation, and similar scenarios moving to TAPD. **This does not mean that all CODING features are in CNB or that all assets can be migrated with one click.** Confirm the service shutdown schedule and actual migration support with the provider again.

## 2. Reference Architecture: From Commit to Deployment

The following is a **conceptual architecture for discussion, not a deployed or validated solution**:

```text
开发者 / 评审者                  AI 使用者
    │                                │ @NPC，受角色与模式限制
    ▼                                ▼
Git 仓库 ── PR / Issue ──► 人工评审与保护分支
    │                                ▲
    ├── 云开发环境                   │ AI 建议 / 可选分支与 PR
    │                                │
    └── push / PR 事件 ─► CNB 流水线 ─┘
                         │ 测试、扫描、构建
                         ▼
                   制品 / OCI 镜像仓库
                         │ 按环境审批与授权
                         ▼
                GitOps 控制器或部署流水线
                         │
                         ▼
                  Kubernetes 集群
```

CNB provides building blocks such as repositories, declarative builds, and remote development. Image signing, approvals, a GitOps controller, Kubernetes networking, and permission controls in the diagram are **elements to design or integrate yourself**, not a claim that the platform provides them all by default. Build environments can be separated from production clusters: first produce a traceable image digest, then have a controlled release identity deploy it to each environment, avoiding production administrator credentials for every PR job.

## 3. Comparison with GitHub, GitLab, and Gitee

This capability map supports product selection; it is not a feature commitment for a single, uniform version. **Check GitHub Cloud, GitHub Enterprise Server, GitLab.com, GitLab Self-Managed, and each vendor's enterprise and private deployment products separately.** In particular, do not automatically apply GitHub Cloud's Codespaces, hosted runners, or Copilot entitlements to Enterprise Server, or assume that CNB Community SaaS entails the same operational responsibilities as another product's self-managed edition.

| Dimension | Tencent CNB | GitHub | GitLab | Gitee |
| --- | --- | --- | --- | --- |
| Audience and collaboration | Repositories, PRs, and Issues for teams seeking to combine builds and remote development | GitHub Cloud suits teams centered on open source and cross-organization collaboration; repositories, PRs, and Issues are common collaboration entry points | Covers repositories, merge requests, and development workflows, with hosted and self-managed options | Code hosting and enterprise development collaboration; worth considering for existing workflows of Chinese-speaking teams |
| CI and execution nodes | `.cnb.yml`, Docker environments, and cloud builds; Enterprise Edition documentation also lists self-managed compute resources | Actions can use GitHub-hosted or self-hosted runners; capabilities and costs depend on the product and specification | GitLab CI/CD uses runners; GitLab.com and some other offerings have hosted runners, and runners can also be self-managed | [Gitee Go](https://gitee.com/features/gitee-go) provides CI/CD; check the specific product, purchase terms, and execution resources; **do not assume SaaS includes it for free** |
| Cloud development | Cloud-native development supports WebIDE and remote clients; quotas and resource charges depend on the edition | GitHub Cloud's Codespaces provides cloud development environments, subject to plan, usage, and billing | Workspaces documentation lists it for Premium/Ultimate and requires a compatible Kubernetes cluster, agentk, and other prerequisites | Verify cloud IDEs, hosted environments, and external integrations for the chosen edition; do not assume they are standard features |
| AI and permissions | CodeBuddy NPC has a delegation model limited by time, repository, and permissions; Enterprise Edition requires model configuration | Copilot covers coding assistance and agent scenarios; features, policies, models, and licenses depend on the plan and deployment model | GitLab Duo provides agent and non-agent capabilities; check plan, deployment, and data policies | Product offerings include [AI Teammates](https://gitee.com/ai-teammates); specific permissions, models, billing, and deployment depend on the contract and edition |
| Deployment | Community Edition SaaS; Enterprise Edition deployed in the enterprise's Tencent Cloud VPC | GitHub Cloud is a hosted service; Enterprise Server is a separate self-managed product whose feature matrix must be checked separately | GitLab.com, Self-Managed, and Dedicated are different deployment models | Distinguish enterprise cloud services from [Gitee private deployment products](https://gitee.cn/) |
| Ecosystem, procurement, and cost | Check Tencent Cloud and TAPD integrations, core-hour and AI usage; Enterprise Edition has a licensing threshold | Evaluate the global open-source community and Marketplace integrations; check seats, Actions, Codespaces, AI, and data transfer | Evaluate runners, integrations, and the self-managed ecosystem; include infrastructure, upgrades, and security operations | Examine local collaboration, product offerings, and commercial support; request separate quotes for Go, AI, private deployment, and resources |

Sources for these capabilities include [GitHub Actions self-hosted runners](https://docs.github.com/en/actions/concepts/runners/self-hosted-runners), [GitHub Codespaces](https://docs.github.com/en/codespaces/about-codespaces/what-are-codespaces), [GitHub Copilot](https://github.com/features/copilot), [GitHub Enterprise Server](https://docs.github.com/en/enterprise-server@3.19/admin/overview/about-github-enterprise-server), [GitLab Runner](https://docs.gitlab.com/ci/runners/), [GitLab Workspaces](https://docs.gitlab.com/user/workspace/), and [GitLab Duo](https://docs.gitlab.com/user/gitlab_duo/). For cost comparisons, consult [GitHub pricing](https://github.com/pricing), [GitLab pricing](https://about.gitlab.com/pricing/), and the [Gitee Enterprise pricing and procurement page](https://gitee.com/enterprises/price) separately, and confirm against your region, plan, and quotation; this article does not speculate about competitors' figures.

### How to Narrow the Shortlist

1. **Community collaboration first**: Count external contributors and inventory existing Actions, integrations, and identity systems, then assess how a platform change would affect participation barriers. GitHub is a natural candidate, but community size should not replace compliance review.
2. **Self-management first**: Specify whether deployment must be in an on-premises IDC, a particular cloud, or merely an enterprise VPC; then examine the actual boundaries of GitLab Self-Managed, GitHub Enterprise Server, Gitee private deployment, and CNB Enterprise Edition separately.
3. **Integrated cloud development first**: Compare CNB cloud development with GitHub Cloud Codespaces; GitLab Workspaces also requires consideration of Kubernetes resources and management responsibilities. Calculate total cost using the same team, duration, and resource specifications.
4. **Chinese-language collaboration and domestic procurement first**: Both CNB and Gitee merit consideration. Verify product editions, account and contracting entities, enterprise identity, support SLAs, storage locations, integrations, and migration costs separately; do not assume a particular network or support experience.

## 4. How Are CNB Community Edition Costs Calculated?

According to [CNB pricing](https://docs.cnb.cool/zh/pricing.md), each **top-level organization is billed independently**. Free allowances and pay-as-you-go overage rates are shown below. Monthly CPU, GPU, and AI usage allowances reset at the end of the month and do not roll over. Repository and object storage are billed based on **average daily usage** during the calendar month minus the applicable free allowance, rather than treating the instantaneous month-end peak as the billable amount.

| Item | Free allowance | Overage unit price |
| --- | ---: | ---: |
| Git repository storage | 100 GiB | 1 yuan/GiB/month |
| Object storage (including artifacts, LFS, etc.) | 100 GiB | 1 yuan/GiB/month |
| Build CPU | 160 core-hours/month | 0.125 yuan/core-hour |
| Cloud development CPU | 1600 core-hours/month | 0.125 yuan/core-hour |
| Build GPU, development GPU | 0 core-hours/month each | 0.5 yuan/core-hour each |
| AI Credits | 500 credits/month | 0.05 yuan/credit |

Core-hours are not task counts: **using 8 cores for 1 hour equals 8 core-hours**. The documentation counts NPC events toward cloud development usage, while model token consumption also uses AI Credits, so budgeting for AI credits alone is insufficient. CPU/GPU and AI overages require an available budget: when the free allowance is exhausted and no budget is linked or the available balance is insufficient, affected tasks are terminated or capabilities restricted; there is no automatic unlimited overdraft. Refer to the pricing page for details of freezing, attribution across months, and settlement.

**Arithmetic example only, not a bill or a measurement**: Suppose one top-level organization uses 320 build CPU core-hours, 2000 cloud development CPU core-hours, and 700 AI credits in a month, with average daily Git storage of 120 GiB and object storage of 110 GiB, no GPU or other billable items, and a sufficient linked budget:

- Build CPU: `(320 - 160) × 0.125 = 20 元`; cloud development CPU: `(2000 - 1600) × 0.125 = 50 元`.
- AI: `(700 - 500) × 0.05 = 10 元`; Git storage: `(120 - 100) × 1 = 20 元`; object storage: `(110 - 100) × 1 = 10 元`.
- The listed items total approximately **110 yuan**. The actual bill also depends on metering, resources, budget, and the rules in effect; this example excludes GPU, networking, taxes, and other possible charges.

The [Enterprise Edition China site](https://docs.cnb.cool/zh/enterprise.html) lists a license at 1024 yuan per authorized user per year or 100 yuan per month, with a **minimum purchase of 100 licenses**; cloud resources consumed by the deployment are charged separately by the resource provider. Simply multiplying by the minimum 100 licenses gives an annual subscription license cost of 102400 yuan/year or a monthly subscription cost of 10000 yuan/month, excluding cloud resources and other services in both cases. Do not infer discounts, taxes, or the final contract amount from these figures. The provider also warns that write operations are prohibited after license expiry, so continuity planning must cover renewal and data export.

## 5. NPC: Permission Boundaries and Security Practices

The [official NPC documentation](https://docs.cnb.cool/zh/build/npc.md) describes `@CodeBuddy` as an automated role running in a pipeline. In default mode it can read code and write comments; it may write and push code and create branches and PRs only when a user with Developer or higher repository permissions enables the “work for me” mode. Its temporary `CNB_TOKEN` is issued according to the initiating user's role; by default it applies only to the current repository and the current task, with a maximum role of Developer. Reporter/Guest users cannot enable work mode. A root-organization administrator can explicitly enable cross-repository operations, extending the scope to the same root organization while retaining the time and role limits; additional public-repository restrictions apply when a contributor triggers a cross-repository fork PR.

These rules apply to the **`@npc` event** described in the documentation. When `npc:go` is used in an ordinary pipeline or triggered through another entry point, token and prompt rules may differ and should not be applied mechanically. Recommendations:

- Start with read-only comments and restrict write mode to trusted people. Protect the main branch and require independent human review, testing, and merging; do not treat an agent's PR as an accepted result.
- Leave cross-repository access disabled by default. If needed, first define the allowed scope and exit conditions, and assess exposure across all repositories in the root organization. Verify trigger permissions for forks, external contributors, and bot accounts.
- Treat Issues, PRs, repository files, dependency output, and logs as untrusted input: prompt injection can induce a model to read secrets, execute commands, or exfiltrate data. Restrict network egress, tools, keys, and writable directories in the execution environment; separate test and production credentials.
- Pin and review custom NPC images, role prompts, and pipeline configuration, and manage third-party dependencies and plugins. Maintain auditable records of access, execution, generated diffs, and model calls, and avoid storing sensitive content in logs.
- Verify how temporary tokens, branch protection, approvals, the cross-repository switch, task cancellation, and abnormal exits behave in the actual version; a permission ceiling does not eliminate leakage risks for data the role can read.

Data governance is equally important. The [CNB privacy statement](https://docs.cnb.cool/zh/saas/privacy.html) describes personal information processing, notes that third-party services are governed by their own policies, and specifies the storage region for personal information collected in mainland China. **This does not mean that all code, logs, prompts, or model calls remain within the enterprise boundary, nor can the privacy statement alone establish that models do not train on data, retain no data, or perform all inference locally.** Check input and output, log retention, training use, subprocessors, regions, and deletion mechanisms for the specific model and contract. Deployment of the Enterprise Edition in a VPC also does not automatically prove that an external model API is on the internal network; verify the network path and contract separately.

## 6. How Kubernetes Teams Should Use CNB

CNB's value is in organizing the development entry point, not replacing the Kubernetes control plane. Teams building AI services or agents can consider connecting application code, image builds, deployment configuration, and review workflows, then using a separate release system or GitOps controller to manage desired cluster state. Pipeline containers, cloud development environments, and production Pods are different trust domains; they should not share highly privileged credentials just because they all use containers.

Prefer releasing by image digest rather than mutable tag, and retain build provenance, test results, and artifact inventories. Use short-lived identities scoped to namespaces or environments to access clusters, and add approvals, policy checks, and rollback-capable versions for production changes. If a task executes untrusted code from PRs, dependencies, or agents, assess execution-node isolation strength, network egress, cache poisoning, resource limits, and secret injection; the Docker name is not a security guarantee.

GitLab Workspaces is another architecture that requires specific verification: its [documentation](https://docs.gitlab.com/user/workspace/) states that workspaces run on Kubernetes clusters and that users are responsible for restricting network access to the control plane. It also warns that running workspaces may remain accessible after user access is revoked. This illustrates that even when workspaces are provided, cluster isolation, identity revocation, and resource cleanup remain part of operational design.

## 7. Security, Migration, and Compatibility Checklist

CNB's [migration tools documentation](https://docs.cnb.cool/zh/guide/migration-tools.md) lists bulk repository imports from GitHub, GitLab, and Gitee, cross-platform code synchronization, migration of selected artifact types, and tools for moving CODING project collaboration data to TAPD or CNB. The existence of a tool does not guarantee lossless preservation of every history, permission, and attachment; migrate a sample and verify each item first.

- **Asset inventory**: List sources, destinations, and owners separately for repositories and all refs, LFS, submodules, artifacts, images, Issues, PRs/MRs, comments, attachments, Wikis, audit records, and retention policies.
- **Identity and permissions**: Compare organization hierarchy, SSO/OAuth, roles, branch rules, approvals, bots, and token lifecycles. Verify account deactivation on departure and data ownership; account and asset boundaries differ between Community and Enterprise editions.
- **Pipeline changes**: List existing CI configurations, plugins, variables, secrets, scheduled and event triggers, caches, runner architecture, image access, and outbound network dependencies. `.cnb.yml` is not guaranteed to be compatible with other platforms' configurations; test failure, retry, and cancellation after rewriting.
- **Migration semantics**: Verify separately whether Git history, LFS objects, and non-Git collaboration data can be migrated and whether authors and links are retained; update webhooks, repository addresses, deployment keys, and image pull addresses. Do not call a single Git mirror push a complete migration.
- **AI and data**: Identify model providers, processing regions, input scope, prompt-injection defenses, operation approvals, logging, and auditing. Verify support for required APIs and tool calls; interface compatibility alone cannot establish equivalent quality or functionality.
- **Recovery and contracts**: Confirm data export formats, responsibility for backup and recovery drills, RPO/RTO, service levels, shutdown notices, cost caps, behavior on license expiry, and the vendor exit path.

## 8. A Brief Validation Plan and What Remains Unverified

Use a non-sensitive sample repository for a small-scale evaluation, agreeing on pass criteria, budget, and cleanup responsibilities first:

1. Migrate a small number of branches, tags, and LFS objects, and compare objects and commits. Check separately which Issues, PRs, attachments, and permission rules are retained and which require manual re-entry.
2. Run tests and builds on each candidate product using the same code, resource specifications, dependencies, and network conditions. Record queue times, success rates, build durations, cache hits, and billing methodology; do not extrapolate rankings from an insufficient sample.
3. Create a remote development environment and check IDE extensions, dependencies, sleep and recovery, data persistence, network restrictions, and behavior after access is revoked.
4. Compare NPC default and work modes in an isolated test repository. Test the cross-repository switch, external PRs, token lifetime, protected branches, and review gates; do not provide real production secrets.
5. Use test artifacts to exercise approval, deployment, failure, and rollback from image build to a non-production Kubernetes environment, and check auditability and traceability.

**This article cannot verify** actual speed, availability, isolation strength, model output quality, or migration completeness for each platform in the reader's region. Nor can public material establish specific purchasing discounts, the data policies of every model provider, or support for arbitrary on-premises private deployment of CNB. Official performance descriptions are product materials, not measurements or service guarantees made by this article.

## Conclusion

CNB can be understood as a development platform that uses repositories as an entry point to connect containerized pipelines, remote development, and AI roles. Its capabilities overlap with those of GitHub, GitLab, and Gitee, but their architecture and procurement boundaries differ. Before choosing, establish whether SaaS or self-management is required, where data and execution environments reside, and who handles operations; then compare collaboration experience and full lifecycle costs. For agents in particular, **being triggerable does not mean an agent can be safely authorized, and generating a PR does not mean it can be merged directly**.

## Official Sources

- CNB: [Repositories](https://docs.cnb.cool/zh/repo/intro.md), [Builds](https://docs.cnb.cool/zh/build/intro.md), [Cloud Development](https://docs.cnb.cool/zh/workspaces/intro.md), [AI](https://docs.cnb.cool/zh/ai/intro.md), [NPC](https://docs.cnb.cool/zh/build/npc.md), [Pricing](https://docs.cnb.cool/zh/pricing.md), [Enterprise Edition](https://docs.cnb.cool/zh/enterprise.html), [Privacy Statement](https://docs.cnb.cool/zh/saas/privacy.html).
- [CODING DevOps discontinuation announcement](https://coding.net/help/docs/admin/pay/price-adjustment.html).
- GitHub: [Actions Runner](https://docs.github.com/en/actions/concepts/runners/self-hosted-runners), [Codespaces](https://docs.github.com/en/codespaces/about-codespaces/what-are-codespaces), [Copilot](https://github.com/features/copilot), [Enterprise Server](https://docs.github.com/en/enterprise-server@3.19/admin/overview/about-github-enterprise-server), [Pricing](https://github.com/pricing).
- GitLab: [Runner](https://docs.gitlab.com/ci/runners/), [Workspaces](https://docs.gitlab.com/user/workspace/), [Duo](https://docs.gitlab.com/user/gitlab_duo/), [Pricing](https://about.gitlab.com/pricing/).
- Gitee: [Enterprise Edition and procurement](https://gitee.com/enterprises), [Enterprise pricing](https://gitee.com/enterprises/price), [Gitee Go](https://gitee.com/features/gitee-go), [AI Teammates](https://gitee.com/ai-teammates), [Private deployment products](https://gitee.cn/).
