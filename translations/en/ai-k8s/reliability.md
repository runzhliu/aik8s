---
title: "Reliability, Checkpoint, and Failure Recovery"
description: "Failure models, RPO, RTO, graceful exit, Spot, and recovery drills for AI jobs"
status: stable
last_reviewed: 2026-08-02
---

# Reliability, Checkpoint, and Failure Recovery

AI workloads often mistake "Pod restarted successfully" for "business recovered successfully." For training that runs for days, inference replicas spanning multiple machines and GPUs, and models of hundreds of GB, what really needs to be measured is progress loss, recovery time, data consistency, and service capacity.

## 1. Define the Failure Domain First

| Failure Domain | Example | Platform Response |
| --- | --- | --- |
| Process | OOM, framework exception, deadlock | Restart Rank/Worker, diagnostic dump |
| Pod | Eviction, image or mount failure | Controller rebuild, readiness probe |
| Node | GPU XID, kernel panic, NIC failure | Isolate node, reschedule, recover |
| Rack/Network domain | Switch or power failure | Cross-domain replicas, capacity redundancy |
| Cluster | Control plane, CNI, CSI failure | Multi-cluster recovery, backup, GitOps |
| Region | Cloud region or datacenter unavailable | Cross-region artifacts and disaster recovery policy |
| Data/Model | Corruption, accidental deletion, wrong version | Immutable versions, checksums, object versioning |

The recovery strategy must match the failure domain. Setting only `restartPolicy` cannot solve node-level or cluster-level problems.

## 2. Describe Training Recovery with RPO and RTO

- **RPO**: The maximum amount of training progress that may be lost;
- **RTO**: How long it takes from failure occurrence to effective training resumption.

Training recovery time typically includes:

```text
故障发现
  + 任务终止/清理
  + 重新排队与扩容
  + 镜像和数据预热
  + Checkpoint 下载/重分片
  + 通信组重建
  + 恢复到稳定吞吐
```

If you only count the time until the Pod is Running again, RTO will be severely underestimated.

## 3. What a Checkpoint Needs to Save

Full recovery typically requires:

- Model parameters;
- Optimizer state;
- Learning rate scheduler;
- Global step / epoch;
- Random number state;
- Data sampler position;
- Mixed-precision scaler;
- Parallelism and sharding metadata;
- Data, code, image, and configuration versions.

Saving only model weights is suitable for inference release, but may not allow lossless continuation of training.

## 4. How to Calculate Checkpoint Frequency

The more frequently you save, the smaller the recovery progress loss, but the greater the write overhead. The following information can be used to determine the interval:

- Mean time between failures of the task;
- Time taken for a single Checkpoint save;
- Hourly GPU cost;
- Maximum acceptable progress loss;
- Storage throughput and retention cost.

A practical approach is to keep all of the following:

1. High-frequency local or near-side Checkpoints;
2. Lower-frequency remote persistent Checkpoints;
3. Long-term archives of key milestones.

Local copies speed up recovery; remote copies cover node and cluster failures.

## 5. Distributed Checkpoint and Resharding

Large models are not suitable for Rank 0 to aggregate and save as a single file, otherwise memory and network become bottlenecks. PyTorch Distributed Checkpoint supports multiple Ranks reading and writing in parallel, and can reshard on load, so the save topology and the recovery topology do not have to be identical. Reference: [PyTorch Distributed Checkpoint](https://docs.pytorch.org/docs/main/distributed.checkpoint.html)

The platform still needs to address:

- When multiple files are considered complete;
- How the manifest and completion marker are published atomically;
- Whether training state is consistent during asynchronous saves;
- Whether new and old framework versions can read each other;
- How incomplete uploads are cleaned up;
- How to verify checksums before recovery.

## 6. The Boundaries of Elastic Training

Torch Distributed Elastic, Ray Train, and others can restart or change scale when Workers fail, but "elastic" does not mean lossless scaling at any point in time.

You need to confirm:

- Whether the framework supports membership changes;
- How the learning rate is adjusted when the global batch size changes;
- Whether data sampling is duplicated or skipped;
- Whether the Rendezvous service is highly available;
- Whether Worker restart resumes from the current state or the most recent Checkpoint;
- Whether maximum retries mask permanent failures.

Reference: [Torch Distributed Elastic](https://docs.pytorch.org/docs/2.13/distributed.elastic.html), [Ray Train Fault Tolerance](https://docs.ray.io/en/latest/train/user-guides/fault-tolerance.html)

## 7. Spot and Preemptible Nodes

Spot GPUs can significantly reduce cost, but interruption must be treated as a normal event:

- The task template captures termination signals;
- The time to save an emergency Checkpoint is less than the termination notice window;
- The queue knows which tasks are allowed to use Spot Flavors;
- On-demand capacity can carry critical tasks;
- Do not place all replicas of the same training task in the same failure domain;
- Measure savings against recomputation loss, not just the discount.

Short tasks, retryable batch inference, and training with frequent Checkpoints are better suited for Spot; strictly low-latency online services usually need stable baseline capacity.

## 8. High Availability for Inference Services

A single model service needs to consider:

- At least two replicas that can fail independently;
- Pod anti-affinity or topology spreading;
- Readiness only succeeds after the model is actually loaded;
- Startup Probe covers long model loading times;
- PreStop with sufficient termination grace period to drain streaming requests;
- Keeping old version capacity during rollout;
- The gateway rate-limits under overload instead of queueing indefinitely.

For a LeaderWorkerSet spanning multiple nodes, one replica is the entire group of Pods, not a single Pod. Capacity planning and PDB must be understood in terms of replica groups.

## 9. What PDB Can and Cannot Do

PodDisruptionBudget constrains voluntary disruptions initiated through the Eviction API, such as node drain; it cannot prevent hardware failures, nor does it directly limit Deployment rolling updates. Reference: [Kubernetes Disruptions](https://kubernetes.io/docs/concepts/workloads/pods/disruptions/)

Common mistakes:

- Setting `minAvailable: 1` for a single-replica service, causing nodes to never be drainable;
- PDB selector does not match the actual Pod labels;
- Multiple PDBs accidentally overlap;
- Unhealthy Pods block maintenance;
- Setting only a PDB without real cross-node replicas.

## 10. GPU Node Failure Isolation

When persistent XID, ECC, NVLink, or PCIe errors are detected, the recommended process is:

1. Mark the node unschedulable;
2. Record the affected tasks and device UUIDs;
3. Let tasks save or recover from Checkpoint;
4. Run DCGM diagnostics and hardware checks;
5. Reset the GPU or reboot the node based on the error type;
6. Remove isolation only after passing benchmark tests;
7. Correlate failure and repair records with assets.

Do not let automatic restarts loop indefinitely on the same faulty GPU.

## 11. Backup of Data and Control Plane

It is not just etcd that needs backup:

- Platform declarations in Git;
- CRDs and key custom resources;
- Kueue quotas and policies;
- Model registry metadata;
- Model, data version, and Checkpoint in object storage;
- Recovery procedures in the key management system;
- Images and Helm Charts;
- DNS, certificates, and external load balancer configuration.

If recovery depends on a Registry or Secret inside the same cluster that has already failed, it is not true disaster recovery.

## 12. Failure Drill Matrix

| Drill | Expected Result |
| --- | --- |
| Delete one training Worker | Task failure is explainable and recovers from the most recent Checkpoint |
| Shut down one GPU node | Task is requeued without leaving orphaned resources |
| Simulate object storage timeout | Bounded retries, no corrupted Checkpoints produced |
| Drain an inference node | Requests are drained, capacity still meets SLO |
| Release a bad model | Automatic stop or fast rollback |
| Control plane briefly unavailable | Running inference is not immediately interrupted; state converges after recovery |
| Lose one cluster | Images, models, and configuration can be obtained from another environment |

Drills should start in a controlled environment and record actual RPO/RTO, not just "eventually recovered."

## 13. What a Runbook Should Include

- Alert meaning and impact scope;
- First confirmation command and Dashboard;
- Which actions are safe and which require approval;
- Checkpoint and rollback locations;
- Node isolation and recovery steps;
- Conditions for escalation to human handling;
- Data retention and post-incident review items after the event ends.

## 14. Go-Live Checklist

- [ ] RPO/RTO defined separately for training and inference;
- [ ] Checkpoint includes the complete state needed to continue training;
- [ ] Tested recovery from incomplete Checkpoints, across nodes, and across topologies;
- [ ] Preemptible tasks can save within the notice window;
- [ ] Inference replicas are spread across nodes or failure domains;
- [ ] PDB does not block normal node maintenance;
- [ ] Faulty GPUs are automatically isolated rather than retried indefinitely;
- [ ] Images, models, configuration, and secrets recovery does not depend on a single cluster;
- [ ] Failure drills are performed regularly and actual RPO/RTO is recorded.

## Further Reading

- [PyTorch Distributed Checkpoint](https://docs.pytorch.org/docs/main/distributed.checkpoint.html)
- [Torch Distributed Elastic](https://docs.pytorch.org/docs/2.13/distributed.elastic.html)
- [Ray Train Fault Tolerance](https://docs.ray.io/en/latest/train/user-guides/fault-tolerance.html)
- [Kubernetes Disruptions](https://kubernetes.io/docs/concepts/workloads/pods/disruptions/)
