---
title: "Platform Operations, Upgrades, and Multi-Cluster"
description: "Version matrix, progressive upgrades, CRDs, backup, disaster recovery, and incident response"
status: stable
last_reviewed: 2026-08-02
---

# Platform Operations, Upgrades, and Multi-Cluster

The version matrix for an AI platform is more complex than for ordinary Kubernetes: kernel, drivers, CUDA, Container Toolkit, Device Plugin, GPU Operator, RDMA, training frameworks, and inference engines all constrain one another. The criterion for a successful upgrade is not that all Pods are green, but that representative training and inference workloads still meet performance and reliability baselines.

## 1. Define Responsibility Boundaries First

| Domain | Platform Team | Model/Business Team |
| --- | --- | --- |
| Kubernetes, CNI, CSI | Responsible | Aware of maintenance windows |
| GPU/Network Operator | Responsible | Provides compatibility requirements |
| Queues, quotas, base runtime templates | Responsible | Selects and complies with policies |
| Training code and models | Provides standards | Responsible |
| Inference engine shared versions | Maintains supported set | Validates model compatibility |
| SLOs and Runbooks | Joint | Joint |

Without clear ownership, driver issues get mistaken for model issues, and model regressions get mistaken for cluster issues.

## 2. Maintain a Version Inventory

At minimum, record:

- OS, kernel, and firmware;
- Kubernetes, containerd/CRI-O;
- CNI, CSI;
- GPU driver, CUDA compatibility level;
- NVIDIA Container Toolkit, Device Plugin;
- GPU Operator, DCGM;
- RDMA/NIC drivers and Network Operator;
- Kueue, JobSet, LWS, Trainer, KubeRay;
- KServe, vLLM/SGLang/Triton;
- Model formats and key Python frameworks.

The inventory must include both "current version," "target version," "support source," "validation status," and "rollback method."

## 3. Do Not Skip the Compatibility Matrix

Kubernetes only maintains the most recent few minor versions and defines version skew and upgrade ordering for components such as apiserver, kubelet, and kubectl. The current rules follow the official Version Skew Policy. Reference: [Kubernetes Version Skew Policy](https://kubernetes.io/releases/version-skew-policy/)

GPU Operator also has its own independent matrix for Kubernetes, OS, container runtime, drivers, and components, and restricts upgrade paths across major versions. Reference: [GPU Operator Platform Support](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/platform-support.html)

"Version X can be installed" does not mean it is within a vendor-supported combination.

## 4. Recommended Upgrade Order

A platform upgrade can be designed in the following stages:

1. Backup, compatibility, and API deprecation scan;
2. Validate control plane and base components on an experimental cluster;
3. Upgrade the Kubernetes control plane;
4. Upgrade node components, CNI, and CSI;
5. Canary GPU node OS/kernel/driver upgrade;
6. GPU/Network Operator and CRDs;
7. Queue, training, and serving controllers;
8. Inference engines and shared runtimes;
9. Representative training, inference, and failure testing;
10. Expand the node pool and observe;
11. Clean up old APIs and temporary compatibility items.

The actual order must follow distribution and vendor documentation; this list must not be treated as a universal command sequence.

## 5. Canary GPU Node Pool

Canary nodes should cover production hardware models and run:

- Driver and GPU Operator validation;
- CUDA basic tests;
- DCGM diagnostics;
- GPU-to-GPU P2P/NVLink tests;
- NCCL Tests;
- RDMA/storage benchmarks;
- One representative training Job;
- One representative inference service;
- DRA/MIG/sharing policies (if used).

After the canary passes, roll out by failure domain to avoid all replicas of the same model entering the new driver version simultaneously.

## 6. Node Maintenance Procedure

```text
确认容量与 PDB
  → cordon
  → 停止新任务准入
  → 等待/Checkpoint/迁移现有任务
  → drain
  → 升级或维修
  → 节点自检与基准
  → uncordon
  → 观察代表性工作负载
```

`kubectl drain` respects PDBs, but single-replica services, incorrect PDBs, or local data can all block. Reference: [Safely Drain a Node](https://kubernetes.io/docs/tasks/administer-cluster/safely-drain-node/)

Long-running training should not be force-drained without a Checkpoint protocol.

## 7. CRDs and Webhooks Are High-Risk Upgrade Points

Check:

- Whether the new version updates CRDs first;
- Whether Helm automatically upgrades CRDs;
- Storage versions and Conversion Webhooks;
- Whether Webhooks are compatible with new API fields;
- `failurePolicy` when Webhooks are unavailable;
- Whether a rolled-back Controller can read new objects;
- Whether deleting old CRDs cascades into deleting business resources.

The official GPU Operator upgrade procedure explicitly notes that Helm's handling of CRDs requires extra attention. Reference: [Upgrading GPU Operator](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/upgrade.html)

## 8. What GitOps Manages

Suitable for GitOps:

- Operator and CRD versions;
- Kueue quotas, Flavors, and policies;
- Namespaces, RBAC, NetworkPolicies;
- Standard training/inference templates;
- Dashboards, alerts, and SLOs;
- Model serving declarations and traffic policies.

Must not be stored in plaintext in Git:

- Secrets and private keys;
- Large models and datasets;
- One-time node tokens;
- Runtime-generated state;
- Unredacted incident evidence.

Manual hotfixes in the cluster must be written back to Git or reverted as soon as possible, otherwise state will drift.

## 9. When Multi-Cluster Is Necessary

Valid reasons:

- Different regions/data sovereignty;
- Isolation between training and production inference;
- Different hardware or driver lifecycles;
- Control plane failure domains;
- Edge sites;
- Blast radius control at very large scale.

Invalid reason: unresolved single-cluster governance problems being hidden by adding more clusters to mask quota, permission, and upgrade chaos.

Multi-cluster increases complexity in Registry, identity, policy, observability, cost, and version distribution.

## 10. Workload Placement

Multi-cluster scheduling must distinguish:

- Organizational policy: data locality, tenants, environments;
- Resource capability: GPU, RDMA, storage, and model cache;
- Current capacity and queueing time;
- Cost and Spot risk;
- Model and data replication status;
- Re-placement cost after failure.

Kueue MultiKueue can distribute workloads to Worker Clusters, but model artifacts, Secrets, RuntimeClasses, and monitoring still need to be prepared by the platform.

## 11. Backup and Disaster Recovery

Regularly validate:

- etcd/control plane backups are restorable;
- Git repositories and Charts can be retrieved from an independent location;
- Registry and object storage have cross-failure-domain replicas;
- Model registry metadata and model files are consistent;
- DNS, certificates, and identity systems have recovery plans;
- A new cluster can recreate queues, policies, and RuntimeClasses;
- Restored training can read old Checkpoints;
- Inference domains can switch over while preserving security configuration.

Disaster recovery documentation should give actual recovery times, not just describe the architecture.

## 12. Upgrade Acceptance

| Layer | Acceptance |
| --- | --- |
| Kubernetes | API, scheduling, DNS, CNI, CSI, logging |
| GPU | Discovery, allocation, MIG/DRA, DCGM, XID |
| Network | Pod network, RDMA, NCCL, cross-node throughput |
| Storage | PVC, object storage, model download, Checkpoint |
| Training | Startup, throughput, convergence segment, recovery |
| Inference | Model loading, TTFT/TPOT, scaling, canary rollout |
| Governance | Kueue, RBAC, policies, audit, cost labels |

Compare against the pre-upgrade baseline; any performance deviation beyond the threshold must be explained.

## 13. Change Records

Each change must retain at least:

- Objective and risk;
- Version diff;
- Compatibility source;
- Canary scope;
- Validation results;
- Observation window;
- Rollback trigger conditions;
- Actual failures and follow-up actions.

## 14. Go-Live Checklist

- [ ] Complete version inventory and vendor support matrix exist;
- [ ] Upgrade order for Kubernetes, GPU Operator, and AI components is explicit;
- [ ] Canary nodes exist for each GPU type;
- [ ] Node maintenance is coordinated with long-running training Checkpoints;
- [ ] CRDs, Webhooks, and API deprecations are validated before upgrade;
- [ ] GitOps is the authoritative source for production configuration;
- [ ] Multi-cluster has clear failure-domain or business justification;
- [ ] Registry, model, configuration, and identity recovery do not depend on a single cluster;
- [ ] Acceptance covers functionality, performance, and recovery;
- [ ] Every upgrade has executable rollback conditions and records.

## Further Reading

- [Kubernetes Version Skew Policy](https://kubernetes.io/releases/version-skew-policy/)
- [Safely Drain a Node](https://kubernetes.io/docs/tasks/administer-cluster/safely-drain-node/)
- [GPU Operator Platform Support](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/platform-support.html)
- [Upgrading GPU Operator](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/upgrade.html)
- [Kueue MultiKueue](https://kueue.sigs.k8s.io/docs/concepts/multikueue/)
