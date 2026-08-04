---
title: RDMA 与 AI 高速网络
description: InfiniBand、RoCE、GPUDirect、NCCL、Kubernetes 接入和分层排障
status: stable
last_reviewed: 2026-08-02
---

# RDMA 与 AI 高速网络

在单机训练中，GPU 之间主要通过 PCIe、NVLink 或 NVSwitch 通信；一旦扩展到多机，网络就可能决定整个任务的上限。RDMA 的价值是让数据以更少的 CPU 参与、更少的内存复制和更低的软件栈开销在节点间传输。

本页从网络基础讲到 Kubernetes 落地，重点不是某个厂商命令，而是建立一条可以验证和排障的完整通信链路。

## 1. RDMA 到底是什么

RDMA 是 Remote Direct Memory Access。它允许一台机器直接访问另一台机器已注册的内存区域，数据路径尽量绕过远端 CPU 和传统内核网络协议栈。

传统 Socket 路径可以简化为：

```text
应用内存
  → 系统调用
  → 内核 TCP/IP
  → Socket Buffer
  → NIC
  → 网络
  → 远端 NIC / 内核 / 应用内存
```

RDMA 路径更接近：

```text
应用注册内存
  → RNIC DMA
  → RDMA Fabric
  → 远端 RNIC DMA
  → 远端已注册内存
```

它带来三类主要收益：

- **Kernel Bypass**：数据面减少内核协议栈参与；
- **Zero/Low Copy**：减少用户态与内核缓冲区之间的复制；
- **CPU Offload**：由支持 RDMA 的 NIC（RNIC/HCA）处理传输，释放 CPU 给数据预处理或训练协调。

RDMA 并不意味着“完全没有 CPU”或“网络绝不丢包”。连接建立、内存注册、控制路径、拥塞控制和错误恢复仍然需要软件参与。

## 2. InfiniBand、RoCE 和 iWARP

| 技术 | 承载网络 | 可路由性 | 常见位置 | 关键特点 |
| --- | --- | --- | --- | --- |
| InfiniBand | 原生 IB Fabric | 由 IB Subnet Manager 管理 | HPC、专用 AI 训练网络 | 协议栈与交换网络统一，低延迟、高带宽，运维体系独立 |
| RoCE v1 | Ethernet 二层 | 不跨三层路由 | 小型同二层网络 | 基于以太网，部署范围受二层限制 |
| RoCE v2 | UDP/IP | 可三层路由 | 数据中心 AI 集群最常见的 Ethernet RDMA | 复用 Ethernet，但必须认真设计 QoS、拥塞和无损/半无损策略 |
| iWARP | TCP/IP | 可路由 | 部分存储和传统 RDMA 场景 | 利用 TCP 可靠性，AI GPU 集群中相对少见 |

### InfiniBand

InfiniBand 使用专用 HCA、交换机和 Subnet Manager。它的服务等级、路由、分区和拥塞管理与普通 Ethernet 不同。优点是整套 Fabric 围绕高性能通信设计；代价是需要独立的网络技能和设备体系。

### RoCE

RoCE 在 Ethernet 上承载 RDMA。RoCE v2 使用 UDP/IP，因此更适合大型可路由数据中心网络。它不是“装上支持 RDMA 的网卡就自然变快”：端点、交换机、队列、MTU、PFC、ECN、DSCP/PCP 和拥塞控制必须保持一致。

## 3. AI 为什么依赖 RDMA

### 数据并行：All-Reduce

每个 Worker 计算一部分 Batch，然后交换并聚合梯度。模型越大、GPU 越多，All-Reduce 的时间越容易吞噬计算收益。

```text
每步时间 = 前向计算 + 反向计算 + 梯度通信 + 优化器更新 + 数据等待
```

如果新增节点后梯度通信增长得比计算并行收益更快，Scale-out Efficiency 就会下降。

### 模型并行：All-Gather / Reduce-Scatter / All-to-All

- Tensor Parallel 会频繁同步张量分片；
- FSDP/ZeRO 需要 All-Gather 和 Reduce-Scatter；
- Mixture-of-Experts 的 Token Dispatch 常依赖 All-to-All；
- Pipeline Parallel 需要在 Stage 间传输 Activation。

这些通信通常比单纯数据并行更敏感，尤其是 MoE 的 All-to-All 会同时考验带宽、拥塞和尾延迟。

### 分布式推理

- 多机 Tensor/Pipeline Parallel；
- Prefill 与 Decode Pool 之间传输 KV Cache；
- 分布式 KV Cache、Remote Memory 和模型权重加载；
- 多副本间的缓存或 Adapter 协同。

因此 RDMA 不再只属于训练集群，也逐渐进入大型 LLM 推理平台。

## 4. GPUDirect RDMA 解决什么

没有 GPUDirect RDMA 时，GPU 网络数据通常要经过 Host Memory：

```text
GPU Memory → PCIe → Host Memory → NIC → Fabric
```

GPUDirect RDMA 让兼容 NIC 可以直接 DMA GPU Memory：

```text
GPU Memory → PCIe / PCIe Switch → NIC → Fabric
```

这样可以减少 Host Memory Bounce 和 CPU 开销。是否真正走 GPUDirect，取决于：

- GPU、NIC、Driver、CUDA、rdma-core 和 Kernel 支持；
- GPU 与 NIC 的 PCIe/NUMA 拓扑；
- DMA-BUF 或 `nvidia-peermem` 等内核机制；
- IOMMU、ACS 和虚拟化配置；
- NCCL/UCX 是否选择了正确的 Transport。

“Pod 同时看得到 GPU 和 `/dev/infiniband`”只是必要条件，不代表 GPUDirect 已生效。必须通过拓扑、日志和性能 A/B 测试确认。

参考：[GPU Operator GPUDirect RDMA](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/gpu-operator-rdma.html)

## 5. Kubernetes 中的一条完整数据路径

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

常见组件职责如下：

| 组件 | 职责 |
| --- | --- |
| 默认 CNI（Cilium/Calico/Flannel 等） | Pod 常规网络、Service、NetworkPolicy 和控制流量 |
| Multus | 为 Pod 调用多个 CNI，附加第二张或更多网卡 |
| NetworkAttachmentDefinition | 声明附加网络和 IPAM 配置 |
| SR-IOV Network Device Plugin | 发现 PF/VF/SF，并以扩展资源发布给 kubelet |
| SR-IOV CNI / Host-Device CNI | 将分配到的 NIC/VF 放进 Pod Network Namespace |
| RDMA CNI / RDMA Device Plugin | 配置 RDMA Namespace 或暴露共享 HCA 资源 |
| NVIDIA Network Operator | 管理 Network Driver、Device Plugin、CNI、IPAM 及 RDMA/GPUDirect 相关组件 |
| GPU Operator | 管理 GPU Driver、Toolkit、Device Plugin 和 GPUDirect GPU 侧能力 |

参考：[Multus CNI](https://github.com/k8snetworkplumbingwg/multus-cni)、[SR-IOV Network Device Plugin](https://github.com/k8snetworkplumbingwg/sriov-network-device-plugin)、[NVIDIA Network Operator](https://docs.nvidia.com/networking/display/kubernetes25100/deployment-guide-kubernetes.html)

## 6. 为什么经常使用第二张 Pod 网卡

默认 CNI 主要优化 Kubernetes 通用连接、Service 和安全策略；训练数据面可能需要：

- 不经过 Overlay 封装；
- 直接使用 SR-IOV VF 或 Host NIC；
- 独立 MTU、VLAN、PKey、路由和 QoS；
- 与管理/存储/公网流量隔离；
- 让 RDMA 的 NetDevice、GID 与 Network Namespace 一致。

Multus 是 Meta CNI：它保留 `eth0` 作为默认网络，再调用 SR-IOV、Macvlan、IPVLAN 等插件添加 `net1`。应用需要明确选择高速接口；NCCL 如果自动选中不可达的管理接口，可能在初始化阶段卡住。

## 7. 三种 Pod 接入方式

### 1. Host Network

优点是简单、性能路径短，适合受控的专用集群或快速验证。缺点是端口冲突、租户隔离和 NetworkPolicy 能力弱，不建议作为通用多租户方案。

### 2. 共享 HCA

多个 Pod 共享同一物理 HCA，各自获得 RDMA 访问资源。资源利用率高，适合信任域内训练；隔离、QoS 和故障影响范围需要仔细验证。

### 3. SR-IOV VF

为 Pod 分配独立 Virtual Function，设备和队列隔离更明确，适合多租户和高性能场景。代价是 VF 数量、IPAM、交换机策略、调度资源和节点生命周期更复杂。

| 需求 | 优先方式 |
| --- | --- |
| 快速单租户验证 | Host Network 或共享 HCA |
| 多租户、资源可计量 | SR-IOV VF |
| Pod 数量远大于 VF 数量 | 共享 HCA，配合配额和安全边界 |
| 严格网络隔离和固定性能 | SR-IOV VF / 专用节点池 |

## 8. 一个概念性 Pod 示例

以下示例表达“默认网络 + Multus 高速网络 + GPU + RDMA 资源”的组合。资源名和 NetworkAttachmentDefinition 必须按实际 Operator/Device Plugin 配置调整。

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

不要直接复制到生产。不同 RDMA Plugin 可能使用不同资源名；SR-IOV 场景通常还会请求对应 VF Resource。

## 9. RoCE 网络为什么难

Ethernet 允许拥塞和丢包，而 RDMA 对丢包、乱序和尾延迟较敏感。RoCE Fabric 通常组合以下机制：

### PFC：Priority Flow Control

PFC 可以只暂停某个优先级的流量，构建近似无损队列。它能减少丢包，但配置错误会导致 Pause Storm、Head-of-Line Blocking，甚至把拥塞扩散到更大范围。

### ECN：Explicit Congestion Notification

交换机在队列开始拥塞时标记包，端点根据 CNP/拥塞反馈降低发送速率。ECN 的阈值、交换机 Buffer 和端点算法必须共同调优。

### QoS 与优先级

RoCE Traffic Class、DSCP/PCP、交换机 Priority、PFC Queue 和 CNP Queue 必须端到端一致。如果中间一跳重写或丢失优先级，网络可能在轻载正常、重载时突然崩溃。

### MTU

训练网络常使用 Jumbo Frame，但所有端点、VF、PF 和交换路径必须一致。MTU 不一致可能表现为小包正常、大消息超时或吞吐异常。

参考：[NVIDIA RoCE 配置](https://docs.nvidia.com/networking-ethernet-software/cumulus-linux-513/Layer-1-and-Switch-Ports/Quality-of-Service/RDMA-over-Converged-Ethernet-RoCE/)

## 10. 拓扑感知比网卡速率更重要

同样是 400 Gb/s NIC，实际性能还取决于 GPU 到 NIC 的路径：

```text
GPU ─┐
     ├─ 同一 PCIe Switch ─ NIC     ← 通常更优
GPU ─┘

GPU ─ CPU Socket 0 ─ UPI/Infinity Fabric ─ CPU Socket 1 ─ NIC
                                      ← 跨 NUMA，可能更慢
```

平台需要记录并利用：

- `nvidia-smi topo -m` 的 GPU/NIC/NUMA 关系；
- HCA 名称、端口、Link Layer 和 Rail；
- 节点所在 Rack、Block、Leaf Switch；
- 每个 Pod Group 需要单 Rail、双 Rail 还是跨 Rail；
- CPU Pinning、HugePages 和 IRQ 亲和。

Kueue Topology-Aware Scheduling 或专用调度器可以控制 Worker 尽量位于同一 Rack/Block；节点内 GPU/NIC 亲和还需要 Runtime、NCCL 和设备分配策略配合。

## 11. NCCL 如何选择网络

NCCL 会探测 Socket、InfiniBand/RoCE 和拓扑，并选择 Collective 算法与 Transport。常见环境变量适合诊断和明确接口，但不应未经基准就永久复制一大套“调优参数”。

常见诊断变量：

```bash
NCCL_DEBUG=INFO
NCCL_DEBUG_SUBSYS=INIT,NET,GRAPH
NCCL_SOCKET_IFNAME=net1
```

A/B 判断是否为 RDMA 路径问题：

```bash
# 只用于诊断：禁用 IB/RoCE，退回 Socket
NCCL_IB_DISABLE=1
```

如果禁用 RDMA 后任务虽然变慢但稳定，问题很可能在 HCA、GID、RoCE Fabric、GPUDirect 或 RDMA Namespace；如果仍失败，应继续检查应用启动、DNS、端口和普通网络。

## 12. 逐层基准测试

不要直接用完整训练任务测试网络。建议从底到顶建立测试梯子：

### 第 1 层：物理与驱动

```bash
lspci | grep -Ei 'Mellanox|NVIDIA|Ethernet|InfiniBand'
rdma link
ibstat
ibdev2netdev
ethtool <interface>
```

确认 Link 为 Active、速率和宽度符合预期、Link Layer 正确、没有意外降速。

### 第 2 层：IP 与 MTU

```bash
ip -br address
ip route
ping <peer>
ping -M do -s <payload> <peer>
```

确认附加网络地址、路由和大包在所有节点间一致。

### 第 3 层：RDMA Perftest

```bash
# 服务端
ib_write_bw -d <device>

# 客户端
ib_write_bw -d <device> <server-address>

# 延迟
ib_write_lat -d <device> <server-address>
```

测试不同消息大小、双向流量、并发连接和跨机架组合。带宽正常不代表尾延迟正常。

### 第 4 层：NCCL Tests

运行 `all_reduce_perf`、`all_gather_perf` 和 `alltoall_perf`，分别覆盖：

- 单机多卡；
- 两节点；
- 同机架多节点；
- 跨机架；
- 单 Rail 与多 Rail；
- GPUDirect 开/关 A/B。

### 第 5 层：真实框架

最后再运行 PyTorch FSDP、DeepSpeed、Megatron、JAX 或推理 KV Transfer 基准。此时若性能异常，可以与前四层结果对照，而不是盲目修改 NCCL 参数。

参考：[NCCL Networking Troubleshooting](https://docs.nvidia.com/deeplearning/nccl/user-guide/docs/troubleshooting/networking_troubleshooting.html)

## 13. 常见故障模式

| 现象 | 常见原因 | 优先检查 |
| --- | --- | --- |
| NCCL 初始化卡住 | 选错接口、端口不通、Rank 地址错误 | `NCCL_DEBUG`、接口连通、DNS、Firewall |
| 小流量正常，大消息超时 | MTU、PFC/ECN、Buffer、丢包 | Jumbo Frame、交换机计数器、RDMA Counter |
| 只有跨机架慢 | Oversubscription、ECMP、拥塞、拓扑放置 | Fabric Telemetry、Kueue TAS、路径一致性 |
| RDMA 与 TCP 性能接近 | 没走 IB Transport 或 GPUDirect | NCCL Log、`NCCL_IB_DISABLE` A/B、GPU/NIC 拓扑 |
| 个别节点持续慢 | Link 降速、PCIe Width、NUMA、坏线缆 | `mlxlink`、`ethtool`、`nvidia-smi topo -m` |
| Pod 有 RDMA Device 但不可通信 | 对应 NetDevice/GID 不在 Pod Namespace | Multus/RDMA CNI、`ip addr`、GID Table |
| 负载高时全网停顿 | PFC Pause Storm 或拥塞配置错误 | PFC、ECN/CNP、Buffer 与 Queue Counter |
| Pod 重建后设备不可用 | CNI 清理、VF Reset、Device Plugin 注册异常 | kubelet、CNI、Device Plugin 日志和资源健康 |

`rdma statistic` 中持续增长的 `rnr_nak_retry_err`、`packet_seq_err`、`implied_nak_seq_err` 或 `local_ack_timeout_err` 常提示丢包、重试或超时，应与交换机和 HCA Counter 同时观察。

## 14. 可观测性

### 节点/HCA

- Port State、Link Rate、Link Width；
- Symbol/CRC Error、Packet Discard；
- RDMA Retry、RNR、Timeout；
- PCIe Replay、ACS、NUMA 与 IRQ；
- PFC Pause Duration、ECN Mark、CNP。

### Kubernetes

- SR-IOV/RDMA Resource 的 allocatable 与 allocated；
- Device Plugin、CNI、Network Operator DaemonSet 健康；
- Pod 附加网络创建耗时和失败；
- 节点 drain 后 VF/HCA 回收；
- Topology-Aware Scheduling 的 Pending 原因。

### 应用

- NCCL Collective 时间和 Algorithm/BUS Bandwidth；
- Training Step 中 Communication 占比；
- All-to-All P95/P99；
- 推理 KV Cache Transfer 吞吐和延迟。

网络指标必须能关联 Node、NIC、Port、Pod、Job 和 Rank。只保留交换机级总带宽，很难定位一项训练任务的慢节点。

## 15. 安全边界

高性能附加网络可能绕过默认 CNI 的 NetworkPolicy。SR-IOV VF、Host Device 和 RDMA 访问意味着工作负载更接近硬件，因此需要额外控制：

- 使用专用 Namespace、ServiceAccount、节点池和 RuntimeClass；
- 仅允许受信镜像申请 RDMA/SR-IOV 资源；
- 用 VLAN、PKey、VRF、交换机 ACL 或物理 Fabric 做数据面隔离；
- 禁止普通用户修改 NetworkAttachmentDefinition；
- 限制特权、Host Network、HostPath 和设备直通；
- 审计 VF、HCA、GPU 和租户的分配关系；
- 验证容器逃逸、DMA/IOMMU 与固件安全策略。

不要假设默认 Kubernetes NetworkPolicy 自动覆盖所有 Multus 附加接口；是否生效取决于对应 CNI 和数据路径。

## 16. 上线清单

- [ ] 选择 InfiniBand 或 RoCE 的原因和运维责任清楚。
- [ ] GPU、NIC、PCIe、NUMA、Rack 和 Rail 拓扑有资产记录。
- [ ] 默认网络和训练数据网络相互隔离，路由边界明确。
- [ ] Multus、SR-IOV/RDMA Plugin 和 Operator 版本固定且兼容。
- [ ] RoCE 的 MTU、PFC、ECN、QoS 和 Buffer 端到端一致。
- [ ] 已确认 NCCL 实际使用预期 HCA、接口和 GPUDirect 路径。
- [ ] `ib_write_bw/lat` 和 NCCL Tests 有单机、同机架、跨机架基线。
- [ ] 网络与训练指标能关联到 Job、Pod、Rank、NIC 和交换端口。
- [ ] 节点 drain、VF 回收、Operator 升级和 HCA 故障经过演练。
- [ ] 附加网络的安全与租户隔离不依赖默认 NetworkPolicy 假设。

## 延伸阅读

- [NVIDIA Network Operator](https://docs.nvidia.com/networking/display/kubernetes25100/deployment-guide-kubernetes.html)
- [NVIDIA GPU Operator：GPUDirect RDMA](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/gpu-operator-rdma.html)
- [NCCL 官方文档](https://docs.nvidia.com/deeplearning/nccl/user-guide/index.html)
- [Multus CNI](https://github.com/k8snetworkplumbingwg/multus-cni)
- [SR-IOV Network Device Plugin](https://github.com/k8snetworkplumbingwg/sriov-network-device-plugin)
- [Kubernetes Network Plumbing Working Group](https://github.com/k8snetworkplumbingwg)
