---
title: "K3s Cluster Cross-Version Upgrade"
description: "Upgrade from K3s v1.32 minor version by minor version to v1.36, including backup, compatibility handling, workload validation, and DRA preflight checks"
status: stable
last_reviewed: 2026-08-04
---

# K3s Cluster Cross-Version Upgrade

This case study documents the complete process of upgrading a real K3s single-node cluster from `v1.32.5+k3s1` to `v1.36.2+k3s1` minor version by minor version, including upgrade planning, multi-stage backup, compatibility issue handling, workload recovery, and Kubernetes DRA preflight checks.

[Read the full upgrade report](report.md){ .md-button .md-button--primary }
[Browse all engineering case studies](../cases/index.md){ .md-button }

## Case Overview

| Item | Details |
| --- | --- |
| Environment | Anolis OS 8.9, single-node K3s, SQLite, cgroup v1 |
| Starting version | `v1.32.5+k3s1` |
| Target version | `v1.36.2+k3s1` |
| Upgrade method | Sequential upgrade following Kubernetes minor version order |
| Key risks | SQLite consistency, cgroup v1, Flannel, Traefik, ServiceLB, and legacy workloads |
| Final result | Node Ready, core API, network components, and workloads Running before the upgrade recovered |
| Extended validation | Kubernetes 1.36 DRA API and heterogeneous GPU management preflight |

## Reading Guide

- To understand the final state and key conclusions: read the "Final Conclusions" section of the report.
- Preparing for a similar upgrade: focus on "Version Planning and Preparation," "Backup Records," and "Upgrade Execution Timeline."
- If kubelet fails to start: see "cgroup v1 Compatibility Handling."
- Concerned about post-upgrade stability: see component, APIService, network, and workload validation.
- Evaluating new device interfaces: see DRA and heterogeneous GPU management preflight.

The report has been converted to site-native Markdown, with unified left navigation, table of contents, search, code copy, and light/dark themes. The original standalone HTML is preserved in the `archive/` directory of the repository as a pre-conversion archive.

## Case Coverage

- Sequential version upgrade path from `v1.32.5+k3s1` to `v1.36.2+k3s1`;
- Multi-stage backup of SQLite, binaries, configuration, and runtime state;
- Handling of cgroup v1 compatibility, Flannel, Traefik, and ServiceLB issues;
- Baseline validation of core components, APIService, and workloads;
- Kubernetes 1.36 DRA and heterogeneous GPU management preflight.

## Reuse Boundaries

This is an engineering record for a specific environment, not a generic upgrade script. Multi-server setups, embedded etcd, external databases, different CNIs, different operating systems, or production high-availability clusters require redesigning backup, quorum, upgrade order, and rollback plans. Before execution, also verify the official upgrade documentation for the target K3s and Kubernetes versions.
