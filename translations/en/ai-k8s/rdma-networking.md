---
title: "RDMA and AI High-Speed Networking"
description: "InfiniBand, RoCE, GPUDirect, NCCL, Kubernetes integration, and layered troubleshooting"
status: stable
last_reviewed: 2026-08-02
---

# RDMA and AI High-Speed Networking

In single-node training, GPUs primarily communicate via PCIe, NVLink, or NVSwitch; once scaled to multiple nodes, the network can determine the upper bound of the entire workload. The value of RDMA is enabling data to travel between nodes with less CPU involvement, fewer memory copies, and lower software stack overhead.

This page progresses from network fundamentals to Kubernetes deployment. The focus is not on any specific vendor's commands, but on establishing a complete communication path that can be verified and troubleshot.

## 1. What RDMA Actually Is

RDMA stands for Remote Direct Memory Access. It allows one machine to directly access memory regions registered by another machine, with the data path bypassing the remote CPU and traditional kernel network protocol stack as much as possible.

The traditional Socket path can be simplified as:

```text
应用内存
  → 系统调用
  → 内核 TCP/IP
  → Socket Buffer
  → NIC
  → 网络
  → 远端 NIC / 内核 / 应用内存
```

The RDMA path is closer to:

```text
应用注册内存
  → RNIC DMA
  → RDMA Fabric
  → 远端 RNIC DMA
  → 远端已注册内存
```

It delivers three main categories of benefits:

- **Kernel Bypass**: Reduces kernel protocol stack involvement in the data plane;
- **Zero/Low Copy**: Reduces copies between user-space and kernel buffers;
- **CPU Offload**: RDMA-capable NICs (RNIC/HCA) handle transport, freeing CPU for data preprocessing or training coordination.

RDMA does not mean "no CPU at all" or "the network never drops packets." Connection establishment, memory registration, control paths, congestion control, and error recovery still require software involvement.

## 2. InfiniBand, RoCE, and iWARP

| Technology | Underlying Network | Routability | Common Location | Key Characteristics |
| --- | --- | --- | --- | --- |
| InfiniBand | Native IB Fabric | Managed by IB Subnet Manager | HPC, dedicated AI training networks | Unified protocol stack and switching fabric, low latency, high bandwidth, independent operations system |
| RoCE v1 | Ethernet Layer 2 | Does not route across Layer 3 | Small same-Layer-2 networks | Based on Ethernet, deployment scope limited to Layer 2 |
| RoCE v2 | UDP/IP | Routable at Layer 3 | The most common Ethernet RDMA in data center AI clusters | Reuses Ethernet, but QoS, congestion, and lossless/semi-lossless policies must be carefully designed |
| iWARP | TCP/IP | Routable | Some storage and legacy RDMA scenarios | Leverages TCP reliability, relatively uncommon in AI GPU clusters |

### InfiniBand

InfiniBand uses dedicated HCAs, switches, and a Subnet Manager. Its service levels, routing, partitioning, and congestion management differ from ordinary Ethernet. The advantage is that the entire fabric is designed around high-performance communication; the cost is the need for a separate networking skill set and equipment ecosystem.

### RoCE

RoCE carries RDMA over Ethernet. RoCE v2 uses UDP/IP, making it better suited for large routable data center networks. It is not "naturally faster just by installing an RDMA-capable NIC": endpoints, switches, queues, MTU, PFC, ECN, DSCP/PCP, and congestion control must all remain consistent.

## 3. Why AI Depends on RDMA

### Data Parallelism: All-Reduce

Each worker computes a portion of the batch, then exchanges and aggregates gradients. The larger the model and the more GPUs, the more easily All-Reduce time can eat into the computational gains.

```text
每步时间 = 前向计算 + 反向计算 + 梯度通信 + 优化器更新 + 数据等待
```

If gradient communication grows faster than the parallel compute gains after adding nodes, Scale-out Efficiency will decline.

### Model Parallelism: All-Gather / Reduce-Scatter / All-to-All

- Tensor Parallel frequently synchronizes tensor shards;
- FSDP/ZeRO requires All-Gather and Reduce-Scatter;
- Mixture-of-Experts Token Dispatch often relies on All-to-All;
- Pipeline Parallel requires transferring Activations between stages.

These communication patterns are typically more sensitive than pure data parallelism, especially MoE All-to-All, which simultaneously stresses bandwidth, congestion, and tail latency.

### Distributed Inference

- Multi-node Tensor/Pipeline Parallel;
- KV Cache transfer between Prefill and Decode Pools;
- Distributed KV Cache, Remote Memory, and model weight loading;
- Cache or Adapter coordination across replicas.

RDMA is therefore no longer exclusive to training clusters; it is increasingly entering large-scale LLM inference platforms.

## 4. What GPUDirect RDMA Solves

Without GPUDirect RDMA, GPU network data typically must pass through Host Memory:

```text
GPU Memory → PCIe → Host Memory → NIC → Fabric
```

GPUDirect RDMA allows compatible NICs to DMA GPU Memory directly:

```text
GPU Memory → PCIe / PCIe Switch → NIC → Fabric
```

This reduces Host Memory bounce and CPU overhead. Whether GPUDirect is actually exercised depends on:

- GPU, NIC, Driver, CUDA, rdma-core, and Kernel support;
- PCIe/NUMA topology between GPU and NIC;
- Kernel mechanisms such as DMA-BUF or `nvidia-peermem`;
- IOMMU, ACS, and virtualization configuration;
- Whether NCCL/UCX selected the correct Transport.

"A Pod can see both the GPU and `/dev/infiniband`" is only a necessary condition; it does not mean GPUDirect is in effect. It must be confirmed through topology, logs, and performance A/B testing.

Reference: [GPU Operator GPUDirect RDMA](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/gpu-operator-rdma.html)

## 5. A Complete Data Path in Kubernetes

```text
训练 Pod
 ├─ eth0：默认 CNI，访问 API、DNS、对象存储和监控
 └─ net1：Multus 附加的高速网络
       │
       ├─ SR-IOV VF / Host Device / Macvlan
       ├─ RDMA Device Resource
       └─ /dev/infiniband + 对应 NetDevice
               │
               ▼
            HCA / RNIC
               │
               ▼
       InfiniBand 或 RoCE Fabric
```

Common component responsibilities are as follows:

| Component | Responsibility |
| --- | --- |
| Default CNI (Cilium/Calico/Flannel, etc.) | Pod general networking, Service, NetworkPolicy, and control traffic |
| Multus | Invokes multiple CNIs for a Pod, attaching a second or additional NICs |
| NetworkAttachmentDefinition | Declares attached networks and IPAM configuration |
| SR-IOV Network Device Plugin | Discovers PF/VF/SF and publishes them as extended resources to kubelet |
| SR-IOV CNI / Host-Device CNI | Places the allocated NIC/VF into the Pod Network Namespace |
| RDMA CNI / RDMA Device Plugin | Configures RDMA Namespace or exposes shared HCA resources |
| NVIDIA Network Operator | Manages Network Driver, Device Plugin, CNI, IPAM, and RDMA/GPUDirect-related components |
| GPU Operator | Manages GPU Driver, Toolkit, Device Plugin, and GPUDirect GPU-side capabilities |

References: [Multus CNI](https://github.com/k8snetworkplumbingwg/multus-cni), [SR-IOV Network Device Plugin](https://github.com/k8snetworkplumbingwg/sriov-network-device-plugin), [NVIDIA Network Operator](https://docs.nvidia.com/networking/display/kubernetes25100/deployment-guide-kubernetes.html)

## 6. Why a Second Pod NIC Is Often Used

The default CNI primarily optimizes general Kubernetes connectivity, Services, and security policies; the training data plane may require:

- Avoiding Overlay encapsulation;
- Using SR-IOV VFs or Host NICs directly;
- Independent MTU, VLAN, PKey, routing, and QoS;
- Isolation from management/storage/public traffic;
- Keeping RDMA NetDevice, GID, and Network Namespace consistent.

Multus is a Meta CNI: it retains `eth0` as the default network, then invokes SR-IOV, Macvlan, IPVLAN, and other plugins to add `net1`. Applications must explicitly select the high-speed interface; if NCCL automatically picks an unreachable management interface, it may stall during initialization.

## 7. Three Pod Access Methods

### 1. Host Network

The advantage is simplicity and a short performance path, suitable for controlled dedicated clusters or rapid validation. The disadvantages are port conflicts, weak tenant isolation, and limited NetworkPolicy capabilities; not recommended as a general multi-tenant solution.

### 2. Shared HCA

Multiple Pods share the same physical HCA, each obtaining RDMA access resources. Resource utilization is high, suitable for training within a trusted domain; isolation, QoS, and failure blast radius require careful validation.

### 3. SR-IOV VF

Allocates an independent Virtual Function to each Pod, with clearer device and queue isolation, suitable for multi-tenant and high-performance scenarios. The cost is greater complexity in VF count, IPAM, switch policy, scheduling resources, and node lifecycle.

| Requirement | Preferred Method |
| --- | --- |
| Fast single-tenant validation | Host Network or Shared HCA |
| Multi-tenant, metered resources | SR-IOV VF |
| Pod count far exceeds VF count | Shared HCA, with quotas and security boundaries |
| Strict network isolation and fixed performance | SR-IOV VF / dedicated node pool |

## 8. A Conceptual Pod Example

The following example expresses the combination of "default network + Multus high-speed network + GPU + RDMA resources." Resource names and NetworkAttachmentDefinition must be adjusted according to the actual Operator/Device Plugin configuration.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: nccl-worker
  annotations:
    k8s.v1.cni.cncf.io/networks: ai-system/roce-net
spec:
  containers:
    - name: worker
      image: registry.example.com/nccl-tests@sha256:...
      resources:
        limits:
          nvidia.com/gpu: 8
          rdma/rdma_shared_device_a: 1
      env:
        - name: NCCL_SOCKET_IFNAME
          value: net1
```

Do not copy directly into production. Different RDMA Plugins may use different resource names; SR-IOV scenarios typically also request the corresponding VF Resource.

## 9. Why RoCE Networks Are Difficult

Ethernet allows congestion and packet loss, while RDMA is sensitive to packet loss, reordering, and tail latency. RoCE Fabrics typically combine the following mechanisms:

### PFC: Priority Flow Control

PFC can pause only a specific priority's traffic, building an approximately lossless queue. It reduces packet loss, but misconfiguration can cause Pause Storms, Head-of-Line Blocking, and even spread congestion to a wider area.

### ECN: Explicit Congestion Notification

Switches mark packets when queues begin to congest, and endpoints reduce send rates based on CNP/congestion feedback. ECN thresholds, switch buffers, and endpoint algorithms must be tuned together.

### QoS and Priority

RoCE Traffic Class, DSCP/PCP, switch Priority, PFC Queue, and CNP Queue must be consistent end to end. If an intermediate hop rewrites or drops priority, the network may behave normally under light load and suddenly collapse under heavy load.

### MTU

Training networks often use Jumbo Frames, but all endpoints, VFs, PFs, and switching paths must be consistent. MTU mismatch may manifest as small packets working fine, large messages timing out, or abnormal throughput.

Reference: [NVIDIA RoCE Configuration](https://docs.nvidia.com/networking-ethernet-software/cumulus-linux-513/Layer-1-and-Switch-Ports/Quality-of-Service/RDMA-over-Converged-Ethernet-RoCE/)

## 10. Topology Awareness Matters More Than NIC Speed

Even with the same 400 Gb/s NIC, actual performance also depends on the path from GPU to NIC:

```text
GPU ─┐
     ├─ 同一 PCIe Switch ─ NIC     ← 通常更优
GPU ─┘

GPU ─ CPU Socket 0 ─ UPI/Infinity Fabric ─ CPU Socket 1 ─ NIC
                                      ← 跨 NUMA，可能更慢
```

The platform needs to record and leverage:

- GPU/NIC/NUMA relationships of `nvidia-smi topo -m`;
- HCA name, port, Link Layer, and Rail;
- Node's Rack, Block, and Leaf Switch location;
- Whether each Pod Group requires single Rail, dual Rail, or cross-Rail;
- CPU Pinning, HugePages, and IRQ affinity.

Kueue Topology-Aware Scheduling or a dedicated scheduler can control workers to stay within the same Rack/Block as much as possible; in-node GPU/NIC affinity also requires coordination between Runtime, NCCL, and device allocation policies.

## 11. How NCCL Selects the Network

NCCL probes Socket, InfiniBand/RoCE, and topology, then selects Collective algorithms and Transports. Common environment variables are suitable for diagnostics and explicit interface selection, but a large set of "tuning parameters" should not be permanently copied without benchmarking.

Common diagnostic variables:

```bash
NCCL_DEBUG=INFO
NCCL_DEBUG_SUBSYS=INIT,NET,GRAPH
NCCL_SOCKET_IFNAME=net1
```

A/B test to determine whether the issue is on the RDMA path:

```bash
# 只用于诊断：禁用 IB/RoCE，退回 Socket
NCCL_IB_DISABLE=1
```

If the workload becomes slower but stable after disabling RDMA, the problem is likely in the HCA, GID, RoCE Fabric, GPUDirect, or RDMA Namespace; if it still fails, continue checking application startup, DNS, ports, and general networking.

## 12. Layer-by-Layer Benchmarking

Do not test the network directly with a full training workload. It is recommended to build a test ladder from the bottom up:

### Layer 1: Physical and Driver

```bash
lspci | grep -Ei 'Mellanox|NVIDIA|Ethernet|InfiniBand'
rdma link
ibstat
ibdev2netdev
ethtool <interface>
```

Confirm Link is Active, rate and width match expectations, Link Layer is correct, and there is no unexpected speed downgrade.

### Layer 2: IP and MTU

```bash
ip -br address
ip route
ping <peer>
ping -M do -s <payload> <peer>
```

Confirm attached network addresses, routes, and large packets are consistent across all nodes.

### Layer 3: RDMA Perftest

```bash
# 服务端
ib_write_bw -d <device>

# 客户端
ib_write_bw -d <device> <server-address>

# 延迟
ib_write_lat -d <device> <server-address>
```

Test different message sizes, bidirectional traffic, concurrent connections, and cross-rack combinations. Normal bandwidth does not mean normal tail latency.

### Layer 4: NCCL Tests

Run `all_reduce_perf`, `all_gather_perf`, and `alltoall_perf`, covering respectively:

- Single-node multi-GPU;
- Two nodes;
- Multiple nodes in the same rack;
- Cross-rack;
- Single Rail and multi-Rail;
- GPUDirect on/off A/B.

### Layer 5: Real Frameworks

Finally, run PyTorch FSDP, DeepSpeed, Megatron, JAX, or inference KV Transfer benchmarks. If performance is abnormal at this point, compare against the results from the first four layers rather than blindly modifying NCCL parameters.

Reference: [NCCL Networking Troubleshooting](https://docs.nvidia.com/deeplearning/nccl/user-guide/docs/troubleshooting/networking_troubleshooting.html)

## 13. Common Failure Modes

| Symptom | Common Cause | Priority Checks |
| --- | --- | --- |
| NCCL initialization hangs | Wrong interface selected, port unreachable, Rank address error | `NCCL_DEBUG`, interface connectivity, DNS, Firewall |
| Small traffic works, large messages time out | MTU, PFC/ECN, Buffer, packet loss | Jumbo Frame, switch counters, RDMA Counter |
| Only cross-rack is slow | Oversubscription, ECMP, congestion, topology placement | Fabric Telemetry, Kueue TAS, path consistency |
| RDMA and TCP performance are similar | Not using IB Transport or GPUDirect | NCCL Log, `NCCL_IB_DISABLE` A/B, GPU/NIC topology |
| Individual nodes consistently slow | Link downshift, PCIe Width, NUMA, bad cable | `mlxlink`, `ethtool`, `nvidia-smi topo -m` |
| Pod has RDMA Device but cannot communicate | Corresponding NetDevice/GID not in Pod Namespace | Multus/RDMA CNI, `ip addr`, GID Table |
| Whole network stalls under high load | PFC Pause Storm or incorrect congestion configuration | PFC, ECN/CNP, Buffer and Queue Counter |
| Device unavailable after Pod recreation | CNI cleanup, VF Reset, Device Plugin registration anomaly | kubelet, CNI, Device Plugin logs and resource health |

In `rdma statistic`, continuously growing `rnr_nak_retry_err`, `packet_seq_err`, `implied_nak_seq_err`, or `local_ack_timeout_err` often indicate packet loss, retries, or timeouts, and should be observed together with switch and HCA counters.

## 14. Observability

### Node/HCA

- Port State, Link Rate, Link Width;
- Symbol/CRC Error, Packet Discard;
- RDMA Retry, RNR, Timeout;
- PCIe Replay, ACS, NUMA and IRQ;
- PFC Pause Duration, ECN Mark, CNP.

### Kubernetes

- SR-IOV/RDMA Resource allocatable and allocated;
- Device Plugin, CNI, Network Operator DaemonSet health;
- Pod additional network creation time and failures;
- VF/HCA reclamation after node drain;
- Pending reasons for Topology-Aware Scheduling.

### Application

- NCCL Collective time and Algorithm/BUS Bandwidth;
- Communication ratio in Training Step;
- All-to-All P95/P99;
- Inference KV Cache Transfer throughput and latency.

Network metrics must be correlatable to Node, NIC, Port, Pod, Job, and Rank. Keeping only switch-level aggregate bandwidth makes it difficult to locate the slow node of a training job.

## 15. Security Boundary

High-performance additional networks may bypass the default CNI's NetworkPolicy. SR-IOV VF, Host Device, and RDMA access mean workloads are closer to hardware, so additional controls are required:

- Use dedicated Namespace, ServiceAccount, node pool, and RuntimeClass;
- Only allow trusted images to request RDMA/SR-IOV resources;
- Use VLAN, PKey, VRF, switch ACL, or physical Fabric for data-plane isolation;
- Prohibit ordinary users from modifying NetworkAttachmentDefinition;
- Restrict privileged, Host Network, HostPath, and device passthrough;
- Audit the allocation relationship among VF, HCA, GPU, and tenants;
- Verify container escape, DMA/IOMMU, and firmware security policies.

Do not assume the default Kubernetes NetworkPolicy automatically covers all Multus additional interfaces; whether it takes effect depends on the corresponding CNI and data path.

## 16. Go-Live Checklist

- [ ] The reason for choosing InfiniBand or RoCE and the operational responsibility are clear.
- [ ] GPU, NIC, PCIe, NUMA, Rack, and Rail topology have asset records.
- [ ] Default network and training data network are isolated from each other, with clear routing boundaries.
- [ ] Multus, SR-IOV/RDMA Plugin, and Operator versions are pinned and compatible.
- [ ] RoCE MTU, PFC, ECN, QoS, and Buffer are consistent end-to-end.
- [ ] Confirmed that NCCL actually uses the expected HCA, interface, and GPUDirect path.
- [ ] `ib_write_bw/lat` and NCCL Tests have single-node, same-rack, and cross-rack baselines.
- [ ] Network and training metrics can be correlated to Job, Pod, Rank, NIC, and switch ports.
- [ ] Node drain, VF reclamation, Operator upgrade, and HCA failure have been rehearsed.
- [ ] Additional network security and tenant isolation do not rely on default NetworkPolicy assumptions.

## Further Reading

- [NVIDIA Network Operator](https://docs.nvidia.com/networking/display/kubernetes25100/deployment-guide-kubernetes.html)
- [NVIDIA GPU Operator: GPUDirect RDMA](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/gpu-operator-rdma.html)
- [NCCL Official Documentation](https://docs.nvidia.com/deeplearning/nccl/user-guide/index.html)
- [Multus CNI](https://github.com/k8snetworkplumbingwg/multus-cni)
- [SR-IOV Network Device Plugin](https://github.com/k8snetworkplumbingwg/sriov-network-device-plugin)
- [Kubernetes Network Plumbing Working Group](https://github.com/k8snetworkplumbingwg)
