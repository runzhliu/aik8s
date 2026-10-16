---
title: "Looks Like an NCCL Failure, but It Was Host Memory OOM"
description: "A sanitized troubleshooting record of ncclCommInitRank unhandled cuda error: tracing from GPU, PCIe, and RDMA step by step to cgroup OOM and NVIDIA locked-page failure"
status: stable
last_reviewed: 2026-08-14
---

# Looks Like an NCCL Failure, but It Was Host Memory OOM

When a distributed training job reports an error, the last line of the log is often the most misleading.

In this incident, TensorFlow failed while initializing the NCCL Communicator:

```text
UnknownError: ncclCommInitRank failed: unhandled cuda error
(run with NCCL_DEBUG=INFO for details)
```

The first instinct is to suspect NCCL, RDMA, GPU P2P, or the driver. But following the node-side evidence further down, the root cause turned out to be the training container's Host Memory hitting the cgroup hard limit. Some training processes were OOM-killed, the NVIDIA driver could no longer lock large chunks of user-space memory, and the failure finally surfaced at the NCCL initialization boundary as `unhandled cuda error`.

This article is a fully sanitized production troubleshooting record. Cluster, node, namespace, Pod, job, image, address, and account information have been removed or replaced with placeholders; the retained hardware scale, kernel signatures, and calculation steps are used to illustrate the diagnostic method.

## 1. Conclusion First

The evidence chain for this incident is:

```text
多 Rank 训练进程启动
        ↓
数据缓存、共享内存和 Host Pinned Memory 快速增长
        ↓
Pod memory cgroup 达到约 640 GiB 硬限制
        ↓
NVIDIA os_lock_user_pages 无法再锁定 4/16 GiB 大块内存
        ↓
部分训练 Rank 被 memcg OOM-kill
        ↓
其他 Rank 初始化 NCCL Communicator 失败
        ↓
TensorFlow 最终只显示 ncclCommInitRank: unhandled cuda error
```

On the node side, no NVIDIA Xid, GPU drop-off, uncorrectable ECC, or PCIe AER errors were found; all eight GPUs were recognized, and P2P Read/Write all passed. Therefore, "node-side NCCL hardware failure" is not the explanation that best fits the evidence.

A more accurate conclusion is: **NCCL is where the error surfaced, not where the failure first occurred.**

## 2. Why the Last Line Leads You Astray

`ncclCommInitRank` requires each Rank to complete CUDA Context setup, topology discovery, shared-memory or network Transport, memory registration, and Peer connection establishment. If any Rank fails earlier due to a CUDA call failure, process exit, or memory registration failure, the other Ranks may only observe a Communicator initialization error.

Therefore, the following three statements are not equivalent:

```text
日志里出现 NCCL
≠ NCCL 库本身有 Bug
≠ RDMA 网络发生故障
```

When troubleshooting, look for the "earliest anomaly," not just the "last exception thrown." In this incident, the earliest valid signal came from the host kernel, not from the TensorFlow Traceback.

## 3. Step 1: Confirm Whether the GPU Is Actually Broken

First, enter the host namespace of the target node. Depending on the platform, you can use `kubectl debug node`, or execute `nsenter` through an existing privileged Node Agent:

```bash
kubectl exec \
  -n <NODE_AGENT_NAMESPACE> \
  <NODE_AGENT_POD> -- \
  nsenter --mount=/proc/1/ns/mnt -- bash
```

First check GPU identity, driver, and current status:

```bash
nvidia-smi -L

nvidia-smi \
  --query-gpu=index,name,uuid,pci.bus_id,driver_version,pstate,\
temperature.gpu,memory.used,memory.total,compute_mode \
  --format=csv,noheader
```

Then check GPU topology and P2P capability:

```bash
nvidia-smi topo -m
nvidia-smi topo -p2p r
nvidia-smi topo -p2p w
nvidia-smi nvlink --status
```

The node in question was an eight-GPU Blackwell node without NVLink; GPU topology within the same NUMA was `NODE`, and across NUMA it was `SYS`. This means communication relied primarily on PCIe, but "no NVLink" itself is not a failure. More importantly, P2P Read/Write for all GPU pairs returned `OK`.

Next, check the kernel signatures that can actually support a hardware failure determination:

```bash
dmesg -T | grep -Ei \
  'NVRM: Xid|Xid \(|GPU has fallen|PCIe Bus Error|AER:.*(error|fatal)'
```

This time, no Xid, GPU drop-off, or PCIe AER errors were matched. `nvidia-smi -q` also showed no pending GPU Recovery Action or Page/Row Repair. This does not yet prove the application is healthy, but it significantly lowers the priority of "GPU hardware failure."

## 4. Step 2: Don't Mistake an RDMA Label for an RDMA Device

The target node carried a label like "RDMA Device Plugin enabled," which easily steers troubleshooting toward RDMA. But a Kubernetes Label is only control-plane metadata; it may be stale, misapplied, or merely indicate that a component is allowed to be deployed.

Real device evidence comes from the host:

```bash
ls -la /dev/infiniband
ls -la /sys/class/infiniband
rdma link show
ibdev2netdev
lspci -nn | grep -Ei 'Mellanox|Infiniband|Ethernet controller'
```

On site, there was no `/dev/infiniband`, `/sys/class/infiniband` was empty, and no RDMA NIC appeared in the PCIe device list. Therefore, this machine actually had no IB/RoCE device available for NCCL.

But this still was not the direct root cause of the error:

- Single-node eight-GPU collective communication does not depend on cross-node RDMA;
- Multi-node jobs without IB/RoCE can fall back to Socket depending on environment and configuration;
- What actually appeared immediately before the error was memory lock-page failure and cgroup OOM.

To confirm the Transport, you can temporarily set the following variables for an A/B test:

```bash
export NCCL_DEBUG=INFO
export NCCL_DEBUG_SUBSYS=INIT,BOOTSTRAP,ENV,GRAPH,P2P,SHM,NET,ALLOC_HOST,REG
export NCCL_DEBUG_FILE=/tmp/nccl.%h.%p.log
```

To verify whether "IB auto-detection interferes with initialization," run a controlled comparison:

```bash
export NCCL_IB_DISABLE=1
```

According to the [NVIDIA NCCL environment variable documentation](https://docs.nvidia.com/deeplearning/nccl/user-guide/docs/env.html), this variable disables the IB/RoCE Transport and falls back to IP Socket. It is only suitable as a diagnostic variable or an explicit system configuration, and should not be left in place long-term without performance regression testing.

## 5. Step 3: Kernel Logs Provided the Real Breakthrough

After expanding the search scope of `dmesg`, logs appeared that predated the NCCL error:

```text
train_process: page allocation failure
...
get_user_pages
os_lock_user_pages [nvidia]
...
Cannot map memory with base addr <REDACTED> and size of 0x100000 pages
Cannot map memory with base addr <REDACTED> and size of 0x400000 pages
```

With the default 4 KiB Page Size:

```text
0x100000 pages × 4 KiB = 4 GiB
0x400000 pages × 4 KiB = 16 GiB
```

In other words, the training process was asking the NVIDIA driver to register or lock large chunks of Host Memory, but the kernel could not complete the allocation. Shortly afterward, the same Pod cgroup showed a clear OOM:

```text
memory: usage 671088640kB, limit 671088640kB
Memory cgroup out of memory: Killed process <PID> (train_process)
```

Converting KiB to GiB:

```text
671088640 KiB ÷ 1024 ÷ 1024 = 640 GiB
```

`usage` and `limit` are exactly equal. This is more direct evidence than "the machine still looks like it has free memory": **the trigger was a Pod/Container memory cgroup OOM, not necessarily a node-wide Global OOM.**

So even if the Kubernetes Node Condition still shows `MemoryPressure=False`, the container may well have been killed because of its own memory limit.

## 6. Step 4: Use kubelet and Runtime to Complete the Timeline

When the Pod has already been deleted by the controller, `kubectl get pod` and Events often no longer retain evidence. At this point, you can trace back from the host Journal using the Pod UID, container ID, or a relative time window:

```bash
journalctl -u kubelet \
  --since '<START_TIME>' \
  --until '<END_TIME>' \
  --no-pager | grep -E '<POD_UID>|OOM|ContainerDied'

journalctl -u containerd \
  --since '<START_TIME>' \
  --until '<END_TIME>' \
  --no-pager | grep -E '<CONTAINER_ID>|TaskOOM|shim disconnected'
```

The sanitized on-site timeline is as follows:

| Relative Time | Evidence |
| --- | --- |
| T+0 | Pod Sandbox created, training container begins startup |
| T+~1 minute | Training main container enters Running |
| T+several seconds | NVIDIA `os_lock_user_pages` begins reporting large memory mapping failures |
| T+over ten seconds | memory cgroup reaches ~640 GiB, kernel begins OOM-killing training Ranks |
| T+several minutes | containerd continuously records `TaskOOM` |
| T+end | Container exit code 137, kubelet cleans up Pod Volumes |

This timeline explains why some Ranks only saw NCCL initialization failure: other Ranks in the same distributed job had already entered an abnormal state or been killed due to Host Memory pressure.

## 7. What Actually Consumed the Host Memory

The Host Memory of a GPU training container includes more than just the Python heap. At minimum, the following should be observed separately:

- Anonymous memory per Rank;
- Dataset Cache, sample decompression, and data preprocessing buffers;
- Process copies of DataLoader/Reader Workers;
- Prefetch queues;
- CUDA Host Pinned Memory;
- `/dev/shm` and other tmpfs;
- File Page Cache;
- Host Buffers registered by communication libraries;
- Sidecar and other containers in the same Pod.

Multi-Rank scenarios are especially prone to the problem of "a single process configuration that looks small, but multiplied by eight fills the node":

```text
单 Rank 缓存 × Rank 数
+ Worker 缓存 × Worker 数 × Rank 数
+ Prefetch 深度
+ Pinned Buffer
+ tmpfs/shmem
= Pod Host Memory 峰值
```

If `/dev/shm` uses `emptyDir.medium: Memory`, the files in it also count toward container memory rather than ordinary temporary disk. The Kubernetes official [container resource management documentation](https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/) explicitly states that tmpfs `emptyDir` is tracked by kubelet as container memory usage; without setting `sizeLimit`, it can keep growing until the Pod memory limit.

It is recommended to constrain `/dev/shm` in the YAML at the same time:

```yaml
volumes:
  - name: dshm
    emptyDir:
      medium: Memory
      sizeLimit: 64Gi

containers:
  - name: trainer
    resources:
      requests:
        memory: <MEASURED_STEADY_STATE_PLUS_HEADROOM>
      limits:
        memory: <VALIDATED_PEAK_PLUS_HEADROOM>
```

You cannot directly copy `64Gi` or raise the Limit to the node Allocatable. The correct value should come from peak measurements of the target workload, while leaving node-level headroom for kubelet, Runtime, Device Plugin, filesystem clients, and the kernel.

## 8. Fix Order: Reduce the Peak First, Then Discuss Adding Memory

Directly raising the Pod memory limit may temporarily bypass the OOM, but it may also turn a memcg OOM into a whole-node OOM. It is recommended to proceed in the following order:

1. Measure the RSS, anonymous memory, shmem, and Pinned Memory growth of each Rank;
2. Reduce Dataset Cache, Reader Worker count, Prefetch depth, and per-batch buffers;
3. Check whether every Rank is redundantly loading the full index, vocabulary, or sample cache;
4. For memory-backed `emptyDir`, set `sizeLimit`;
5. Confirm that Sidecars are not sharing and amplifying pressure on the same cgroup;
6. Only after the peak is explainable, adjust Request/Limit while preserving node system headroom;
7. Re-validate with the exact same data scale and Rank count.

When re-running, also save the following at the same time:

```text
NCCL INFO 日志
各 Rank 第一条异常及时间
Pod memory working set / RSS / cache / shmem
cgroup memory failcnt 或 memory.events
kubelet、containerd 和 dmesg 时间线
GPU Xid/ECC/PCIe/P2P 状态
```

## 9. How to Prove NCCL and the Node Have Recovered

After the application memory issue is resolved, perform two layers of validation.

The first layer is a minimal collective communication test:

```bash
./all_reduce_perf -b 8M -e 1G -f 2 -g 8
```

Observe whether all Ranks complete, whether bandwidth is stable, and whether NCCL ultimately selected P2P, SHM, Socket, or IB/RoCE. Multi-node tests must fix the nodes, NICs, MTU, GID, and NCCL version; a single-node success cannot substitute for cross-node validation.

The second layer is replaying the original training job: restore Worker, Prefetch, and Batch levels step by step, recording memory peaks and the time of the first Collective. Running one small Batch successfully once does not prove that memory will not accumulate to OOM again after hours of training.

## 10. Five Lessons from This Troubleshooting Session

1. `ncclCommInitRank` is the error boundary, not the root cause determination result.
2. Without Xid, AER, GPU drop-off, or P2P anomalies, do not rush to reset GPUs or reboot the node.
3. Node `MemoryPressure=False` cannot rule out a Container memory limit OOM.
4. An RDMA Label, Device Plugin configuration, and actual RDMA devices are three different things.
5. Distributed jobs must estimate Host Memory peaks as "per-Rank cost × Rank count × Worker count."

In the end, what is truly useful is not labeling this error as an "NCCL problem," but establishing a fixed troubleshooting chain:

```text
应用首错
  → Rank 生命周期
  → cgroup 内存
  → NVIDIA/内核日志
  → GPU 与 PCIe
  → SHM/P2P
  → RDMA/Socket
  → 最小 nccl-tests
```

As long as the order is correct, many seemingly complex NCCL failures can ultimately be reduced to more specific — and more fixable — resource or topology problems.
