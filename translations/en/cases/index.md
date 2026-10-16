---
title: "Engineering Case Studies"
description: "Records of implementation processes, troubleshooting, verification evidence, and reusable experience in real Kubernetes and AI infrastructure environments"
status: evolving
last_reviewed: 2026-08-04
---

# Engineering Case Studies

This section collects implementation and troubleshooting records from real environments. Topic documents answer "how should this normally be designed," while case studies retain specific versions, hardware, constraints, operational procedures, and verification results, demonstrating how these methods are applied in concrete environments.

[View Cluster Component Inventory](ai-cluster-component-checklist.md){ .md-button .md-button--primary }
[View K3s Cluster Upgrade Case Study](../k3s-upgrade/index.md){ .md-button }
[Return to Full Technical Map](../ai-k8s/index.md){ .md-button }

## Case Study Index

<div class="grid cards" markdown>

-   **AI/LLM Cluster Component Inventory**

    Component packages broken down by minimal GPU closed loop, multi-tenant training, Ray, big data, high-availability inference, and disaggregated inference, with item-by-item explanations of what is needed, why it is needed, when it can be omitted, and how to validate it.

    [View Component Inventory](ai-cluster-component-checklist.md)

-   **K3s Cluster Cross-Version Upgrade and DRA Preflight**

    On a real K3s single-node cluster, upgrading from `v1.32.5+k3s1` to `v1.36.2+k3s1` through minor versions, documenting backup, cgroup v1 compatibility, network component recovery, workload verification, and DRA with heterogeneous GPU management preflight.

    [View Case Overview](../k3s-upgrade/index.md) · [Read Full Report](../k3s-upgrade/report.md)

</div>

## Difference Between Case Studies and Topic Documents

| Content Type | Primary Question Answered | How to Use |
| --- | --- | --- |
| Topic documents | Architecture boundaries, general methods, selection criteria, and production checklists | Used for designing new platforms or establishing team standards |
| Lab guides | How to reproduce a minimal closed loop in a controlled environment | Used for learning, validating components, and establishing baselines |
| Engineering case studies | What happened in a specific environment, how it was handled, and what the results were | Used as reference paths and for identifying risks; cannot be copied verbatim |

Version numbers, addresses, resource scales, and compatibility approaches in case studies all have environmental boundaries. When reusing them, first return to the corresponding topic document to verify current upstream documentation, then re-plan the steps based on your own cluster version, data storage, network, hardware, and rollback requirements.

## Inclusion Criteria

Each case study should preserve as much as possible:

- Background, objectives, timing, and applicable boundaries;
- Environment baseline before the upgrade or change;
- Risk assessment, backup, and rollback plans;
- Key operations, anomalies, reasoning, and remediation processes;
- Functional, performance, and workload verification after the change;
- Completed items, residual risks, and follow-up recommendations;
- Reusable experience and special handling applicable only to that environment.

Case studies are maintained separately from general topic documents, to avoid mistaking a single successful operation as the standard answer for all environments.
