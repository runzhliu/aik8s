---
title: "AI Cluster Incident Review Methodology"
description: "Review training and inference incidents using timelines, fault domains, recovery evidence, and action items"
status: stable
last_reviewed: 2026-08-04
---

# AI Cluster Incident Review Methodology

Incident reviews should explain why the system allowed the failure to expand, rather than finding the person who executed the last command. AI platforms must also quantify lost GPU hours, training progress, inference requests, and model release impact.

## 1. Recommended Structure

1. Summary: user impact, duration, and severity level;
2. Architecture: control plane, data plane, models, and external dependencies involved;
3. Timeline: detection, diagnosis, mitigation, recovery, and verification;
4. Triggering factors and root cause;
5. Amplifying factors and existing protections;
6. Which signals were missing or misleading;
7. Why recovery was effective, and whether residual risks remain;
8. Action items, owners, deadlines, and verification methods.

## 2. Three High-Value Drill Questions

### Driver Upgrade Causes Inference Unavailability

Check whether the Canary covers real models, whether node rolling respects capacity, whether the Runtime and driver matrix is pinned, and whether rollback requires node rebuild.

### Model Release Saturates Object Storage or Egress

Check whether releases are batched, whether node caching exists, whether origin throttling is in place, whether download retries amplify traffic, and whether Readiness succeeds prematurely.

### PDB Blocks GPU Node Maintenance

Check replicas, Topology Spread, graceful termination, long-running requests, maintenance capacity, and the business consequences of forced Drain.

## 3. AI-Specific Losses

- Lost training steps and GPU hours;
- Checkpoint RPO/RTO;
- TTFT/TPOT and failed requests;
- Incorrect model version or output quality impact;
- Duplicate model downloads, cross-zone traffic, and additional costs;
- Preempted tenants and queue fairness.

## 4. Action Items Must Be Verifiable

"Strengthen monitoring" and "raise awareness" are not complete action items. They should be written as testable controls, for example: "The release controller limits each batch to 10 nodes, and CI fault experiments verify that origin egress stays below the threshold."

Further reading: [Platform Operations](../platform-operations.md), [Reliability](../reliability.md), [Security Governance](../security-governance.md)
