---
title: 8 卡节点的四卡任务，如何避免拿到跨 NUMA 的碎片 GPU
description: 从 NVIDIA Device Plugin、Topology Manager、Volcano、Koordinator、HAMi 到 Kubernetes DRA，评价 GPU 设备拓扑感知调度的真实能力与生产落地路径
status: evolving
last_reviewed: 2026-08-26
---

# 8 卡节点的四卡任务，如何避免拿到跨 NUMA 的碎片 GPU

一台 8 卡服务器明明还空闲 4 张 GPU，四卡推理任务也成功启动了，性能却比正常情况差。进入容器才发现，任务拿到的不是同一个高速互联域中的 4 张卡，而是跨 NUMA、跨 PCIe Root Complex 的碎片组合。

这不是一个简单的“空闲 GPU 数量”问题，而是 Kubernetes 的节点选择与 GPU 设备选择发生在不同阶段。传统调度器看到节点还有 4 个 `nvidia.com/gpu`，却不一定知道具体空闲 GPU 的 UUID、NUMA、PCIe 和 NVLink 关系。

截至 2026 年 8 月，社区已有多种拓扑感知方案，但能力边界差异很大：

- NVIDIA Device Plugin 能够**优选**拓扑较近的设备，但不能保证没有完整四卡分组时让 Pod 等待；
- Kubelet Topology Manager 能在节点侧做严格准入，但调度器可能事先不知道该节点无法满足要求；
- Volcano 的 `numa-aware` 目前主要处理 CPU NUMA，尚未完整解决标准整卡 GPU 的 NUMA 调度；
- Koordinator 已能在调度阶段表达 GPU 同 NUMA、同 PCIe 或严格 GPU Partition，是现阶段最贴近这个需求的开源方案；
- Kubernetes DRA 可以从 API 层表达“4 张 GPU 必须具有相同 NUMA 属性”，方向最标准，但 NVIDIA GPU DRA Driver 仍需要结合目标版本验证成熟度。

本文评价的是社区公开能力，不代表任何特定集群的实测结论。生产选型前仍应在目标 Kubernetes、GPU Driver 和硬件拓扑上做故障注入与回归测试。

## 1. 先把问题描述准确

假设一台服务器的实际拓扑是：

```text
NUMA 0 / PCIe Island A       NUMA 1 / PCIe Island B
GPU 0  GPU 1  GPU 2  GPU 3   GPU 4  GPU 5  GPU 6  GPU 7
```

四卡任务的理想分配是：

```text
GPU 0-3
或
GPU 4-7
```

随着不同推理实例在不同时刻退出，节点可能只剩下面四张空卡：

```text
占用  占用  空闲  空闲   空闲  空闲  占用  占用
GPU0  GPU1  GPU2  GPU3   GPU4  GPU5  GPU6  GPU7
```

从资源数量看，节点确实还有 4 张 GPU；从通信拓扑看，唯一组合 `GPU 2-5` 横跨了两个 NUMA 或 PCIe 域。对于 Tensor Parallel、频繁 Collective 或 P2P 通信的任务，这可能增加 Host Bridge、UPI/CPU Interconnect 路径上的通信，并使吞吐和尾延迟变差。

### 1.1 “连续编号”不等于“拓扑相邻”

不能把 `GPU 0-3` 永久等同于一个 NUMA 域。GPU Index 可能受驱动枚举顺序、`CUDA_DEVICE_ORDER`、MIG 和容器内重映射影响。判断依据应该是 GPU UUID 与真实拓扑：

```bash
nvidia-smi -L
nvidia-smi topo -m
nvidia-smi topo -p2p r
```

平台策略应该表达“同一 NUMA”“同一 PCIe Switch”或“属于同一个经过验证的 Partition”，而不是只判断编号是否连续。

### 1.2 这是两个决策，不是一个决策

传统 Device Plugin 模式下，链路大致如下：

```text
Pod 请求 nvidia.com/gpu: 4
          │
          ▼
kube-scheduler 选择一个还剩 4 张卡的节点
          │  此时主要看到整数容量
          ▼
kubelet 调用 Device Plugin
          │
          ▼
Device Plugin 从该节点空闲 UUID 中选择 4 张
          │
          ▼
容器获得 CUDA_VISIBLE_DEVICES / CDI Devices
```

如果拓扑约束直到 kubelet 或 Device Plugin 阶段才被发现，调度器已经完成了节点绑定。这正是“总数够，但组合不好”的根因。

## 2. 评价一套方案要看什么

只写“支持 NUMA-aware”没有意义。至少要回答五个问题：

| 评价维度 | 关键问题 |
| --- | --- |
| 设备可见性 | 组件看到的是整数 GPU 数，还是每张 GPU 的 UUID、NUMA、PCIe、NVLink 属性？ |
| 决策时机 | 在调度器选择节点前决策，还是 Pod 绑定节点后才决策？ |
| 约束语义 | 是 `Preferred` 尽量满足，还是 `Required/Restricted` 不满足就等待？ |
| 碎片治理 | 只能避免新碎片，还是能够通过预留、抢占或重调度恢复完整分组？ |
| 生产代价 | 是否替换调度器、Device Plugin 和资源 API？升级、回滚与可观测性如何？ |

本场景最重要的不是“能否选到好卡”，而是：

> 当只剩 `GPU 2-5` 时，系统能否拒绝这个退化组合，让四卡任务保持 Pending，并去其他节点寻找完整拓扑域。

## 3. NVIDIA Device Plugin：成本最低的拓扑优选

当前 NVIDIA Device Plugin 实现了 `GetPreferredAllocation`。其 GPU Allocator 会参考设备的 PCIe 和 NVLink 拓扑，在可用设备中尽量选择关系更近的组合，并考虑给后续同规模申请保留较好的组合。相关实现可以直接查看 [NVIDIA Device Plugin 的分配服务](https://github.com/NVIDIA/k8s-device-plugin/blob/main/internal/plugin/server.go)与 [NVIDIA go-gpuallocator](https://github.com/NVIDIA/go-gpuallocator)。

它适合作为第一层低成本优化：当 `GPU 0-3` 和 `GPU 4-7` 都完整空闲时，优先选出一个较好的四卡集合，而不是随机拆散两个集合。

但它不能单独提供本场景需要的硬保证：

- kube-scheduler 仍然主要按照 `nvidia.com/gpu: 4` 选择节点；
- `GetPreferredAllocation` 是在节点已选定后的设备优选；
- 如果节点只剩 `GPU 2-5`，Allocator 不等同于一个集群级拓扑调度器；
- 不同 Device Plugin、MIG 模式和硬件上报质量会影响实际结果，不能只看到接口存在就宣布生效。

因此，对 NVIDIA Device Plugin 更准确的评价是：**它能减少不必要的坏分配，但不能代替严格的设备拓扑调度。**

## 4. Kubelet Topology Manager：能够严格，但拒绝得太晚

Kubernetes Topology Manager 在 kubelet 中汇总 CPU Manager、Memory Manager 和 Device Manager 的拓扑 Hint。`restricted` 与 `single-numa-node` 策略可以拒绝不满足对齐条件的 Pod；Device Plugin 也可以通过 `TopologyInfo` 上报设备关联的 NUMA Node。[Kubernetes Topology Manager](https://kubernetes.io/docs/tasks/administer-cluster/topology-manager/)和 [Device Plugin API](https://kubernetes.io/docs/concepts/extend-kubernetes/compute-storage-net/device-plugins/)说明了这条链路。

它适合 CPU、HugePage、内存和 GPU 都要求位于同一 NUMA 的单机 HPC 负载，但存在一个架构限制：Topology Manager 是 kubelet 组件，不是 scheduler 插件。官方文档也提示，被拓扑准入拒绝的 Pod 不会由 scheduler 自动换一个节点重新绑定；上层 Deployment 或 Job 可能不断创建替代 Pod，又反复命中错误节点。

| 优点 | 限制 |
| --- | --- |
| Kubernetes 原生能力 | 决策发生在节点绑定之后 |
| 可以使用严格准入策略 | scheduler 缺少逐设备拓扑库存 |
| 能协调 CPU、内存和设备 NUMA | 处理不当会形成创建、拒绝、重试循环 |

所以它适合作为**节点侧最后一道保护线**，但不应该是大规模集群唯一的 GPU 拓扑调度方案。

## 5. Volcano：方向正确，但当前能力不要高估

看到这个场景，很多人的第一反应是 Volcano `numa-aware`。这个判断并不离谱：Volcano 本来就擅长 Gang、Queue、DRF、抢占和面向 AI/HPC 的批调度，也确实存在 NUMA-aware 插件。

问题是 CPU NUMA-aware 不等于 GPU Device NUMA-aware。Volcano 社区在 2026 年公开的 [GPU NUMA topology-aware scheduling Issue](https://github.com/volcano-sh/volcano/issues/4998)明确指出，当前 `numa-aware` 主要支持 CPU NUMA，调度 GPU 工作负载时尚未考虑 GPU NUMA。Issue 给出的示例也是一台 8 卡节点分成两个四卡 NUMA 域，希望避免得到跨域的四卡组合。

Volcano vGPU 提供 `volcano.sh/vgpu-use-gpuuuid` 和 `volcano.sh/vgpu-nouse-gpuuuid` 等注解，可以指定或排除 GPU UUID，参见 [Volcano vGPU 使用文档](https://github.com/volcano-sh/volcano/blob/master/docs/user-guide/how_to_use_volcano_vgpu.md)。但这更接近人工设备绑定，并不等于针对标准整卡请求自动寻找完整四卡拓扑域。

另外，Volcano 的 [Network Topology-aware Scheduling](https://github.com/volcano-sh/volcano/blob/master/docs/design/Network%20Topology%20Aware%20Scheduling.md)主要处理节点、机架和网络域之间的放置，不能直接推导为“会选择节点内哪四张 GPU”。

因此，截至本文评审日期：

> Volcano 可以继续承担队列、Gang 和跨节点拓扑调度，但不能因为启用了 `numa-aware` 就认为本场景已经解决。

## 6. Koordinator：当前最贴近需求的开源实现

Koordinator 把逐设备信息上报为 `Device` 对象，其中包括设备 ID、Bus ID、NUMA Node 和 PCIe ID，再由 `koord-scheduler` 在调度阶段做设备选择。这避免了“scheduler 先盲选节点，kubelet 再发现拓扑不满足”的时间差。[Koordinator Device 架构](https://koordinator.sh/docs/next/architecture/device)和其 [NUMA-aware Scheduling 设计](https://github.com/koordinator-sh/koordinator/blob/main/docs/proposals/scheduling/20230415-numa-topology-scheduling.md)说明了这套机制。

Koordinator 已公开支持：

- GPU 必须位于同一个 NUMA Node；
- GPU 必须位于同一个 PCIe 拓扑域；
- CPU、内存与 GPU 的 NUMA 对齐；
- 预定义 GPU Partition；
- GPU 与 RDMA 网卡联合拓扑分配。

以同 NUMA 为例，其公开配置思路如下：

```yaml
metadata:
  annotations:
    scheduling.koordinator.sh/device-allocate-hint: |
      {
        "gpu": {
          "requiredTopologyScope": "NUMANode"
        }
      }
spec:
  schedulerName: koord-scheduler
  containers:
    - name: inference
      resources:
        limits:
          koordinator.sh/gpu: "400"
```

这里的资源名与 `400` 计量方式来自 Koordinator 的公开示例，表示四张完整 GPU；实际部署必须按照所用版本、设备插件和资源协议调整，不能直接复制到现有集群。完整能力示例见 [Koordinator v1.6 发布说明](https://koordinator.sh/blog/release-v1.6.0)。

对于拓扑稳定的 8 卡节点，更容易验证和解释的方式是预定义两个 GPU Partition：

```text
Partition A = GPU 0、1、2、3 对应的四个 UUID
Partition B = GPU 4、5、6、7 对应的四个 UUID
```

四卡工作负载采用 `Restricted` 分配语义：有完整 Partition 才运行；只剩跨域的四张碎片卡时保持 Pending。这样不仅能保护当前任务，也能让 scheduler 在集群范围内继续寻找其他节点。

Koordinator 的代价也要说清楚：它不是给现有 Pod 增加一条注解就能自动生效。平台需要部署和维护 `koord-scheduler`、`koordlet`、Device CRD 与对应设备分配链路，并验证它与当前 NVIDIA Device Plugin、GPU Operator、MIG、监控和配额系统的兼容性。

综合来看，若目标是**在传统 Kubernetes 集群中尽快得到调度阶段的严格 GPU NUMA/PCIe 约束**，Koordinator 是当前最值得做 PoC 的方案。

## 7. Kubernetes DRA：API 语义最干净的长期方向

Dynamic Resource Allocation 不再把 GPU 只表示成一个整数，而是由 Driver 发布每个设备及其属性。`ResourceClaim` 可以使用 `matchAttribute` 约束一次申请中的多台设备具有相同属性。Kubernetes 的标准 NUMA 属性设计正好给出了同 NUMA 设备分配的表达方式，参见 [ResourceClaim API](https://kubernetes.io/docs/reference/kubernetes-api/resource/resource-claim-v1/)与 [DRA 标准 NUMA Node 属性 KEP](https://github.com/kubernetes/enhancements/blob/master/keps/sig-node/6072-dra-standard-numanode/README.md)。

概念上，四卡同 NUMA 可以表达为：

```yaml
devices:
  requests:
    - name: gpu
      exactly:
        deviceClassName: gpu.nvidia.com
        count: 4
  constraints:
    - requests:
        - gpu
      matchAttribute: resource.kubernetes.io/numaNode
```

当没有四张具有相同 NUMA 属性的 GPU 时，Claim 无法完成分配，Pod 保持 Pending。这比“先选择节点，再让 kubelet 拒绝”更符合调度器的工作方式。

但生产评价不能只看 API 漂亮。NVIDIA GPU DRA Driver 仍在快速演进，其仓库目前仍提醒部分 GPU 分配能力尚未正式支持或默认启用，部署还依赖对应 Kubernetes 与 GPU Operator 版本。升级前需要核对 Driver Release、Feature Gate、Resource API 版本、Claim 回收和故障恢复，参见 [NVIDIA GPU DRA Driver](https://github.com/kubernetes-sigs/dra-driver-nvidia-gpu)。

因此，DRA 适合放入中长期技术路线，并用独立节点池做 PoC；对于已有成熟 Device Plugin 链路的生产集群，暂时不应仅为这一个问题直接全量替换。

## 8. HAMi：适合已有 vGPU 需求的集群

[HAMi](https://github.com/Project-HAMi/HAMi)提供 GPU 共享、显存隔离和拓扑感知能力，并通过 Scheduler Extender、Webhook 与 Device Plugin 协作完成设备分配。如果平台本来就在评估 vGPU、显存切分和提高开发集群利用率，它值得一起验证。

但对于“整卡独占的四卡推理必须位于同一硬件岛”这一单一需求，引入完整 HAMi 设备栈通常比 Koordinator Partition 更重。社区关于 NUMA 选择、设备记账和状态一致性的讨论也说明这部分仍在演进，例如 [HAMi NUMA 相关 Issue](https://github.com/Project-HAMi/HAMi/issues/2080)。

更稳妥的定位是：已经使用 HAMi 的集群验证其拓扑策略；只需要严格整卡分组的集群，不必为了这一项能力先引入 GPU 共享体系。

## 9. 没有调度器能无损“整理”正在使用的 GPU

拓扑感知可以避免继续产生碎片，却不能把一个正在运行的普通 CUDA 进程从 GPU 6 在线迁移到 GPU 2。要重新得到完整四卡分区，只能组合使用：

- 等待短任务自然结束；
- 排空流量后驱逐、重建小规格推理 Pod；
- 使用 PriorityClass 和拓扑感知抢占；
- 为四卡任务预留完整 Partition 或专用节点池；
- 让 1 卡、2 卡任务在一个 Partition 内优先 Binpack，避免同时污染两个四卡域；
- 对可恢复训练任务配合 Checkpoint，对在线推理配合多副本和优雅下线。

不要用手工设置 `CUDA_VISIBLE_DEVICES=0,1,2,3` 绕过 Device Plugin 的资源记账。调度器不知道这些 GPU 已被使用时，可能把同一设备再次分给其他 Pod。直接用 `nodeName` 固定节点也只解决节点选择，不解决设备 UUID 的安全分配。

## 10. 推荐落地路径

### 阶段一：先确认现有链路有没有浪费能力

不修改集群策略，先完成只读审计：

1. 用 GPU UUID 建立实际 NUMA、PCIe、NVLink/NVSwitch 拓扑图；
2. 记录 Kubernetes、Driver、GPU Operator 和 NVIDIA Device Plugin 版本；
3. 确认 Device Plugin 的 Preferred Allocation 是否被调用；
4. 在空闲 8 卡节点反复创建四卡 Pod，记录实际分配的 UUID；
5. 分别构造“两个完整四卡域”和“只剩跨域四卡”的状态；
6. 记录 Pod 事件、设备分配结果和业务性能，不只看 `nvidia-smi` 截图。

这一阶段能够判断问题是“能力没有启用”“拓扑上报错误”，还是确实需要引入调度期硬约束。

### 阶段二：用一个节点池验证 Koordinator

PoC 至少包含四个验收用例：

| 用例 | 期望结果 |
| --- | --- |
| 空闲 8 卡，提交两个四卡任务 | 分别得到两个完整拓扑域 |
| 只剩同域四卡 | 任务得到该完整分组 |
| 只剩跨域四卡 | Restricted 任务保持 Pending |
| 释放一个完整分组 | Pending 任务自动获得该分组并运行 |

同时验证调度器重启、koordlet 重启、节点 NotReady、Pod 强制删除、MIG 开关和 Device CRD 状态恢复。只有正常路径成功还不能证明可生产使用。

### 阶段三：治理小任务造成的碎片

建议明确三类服务等级：

| 工作负载 | 建议策略 |
| --- | --- |
| 1/2 卡开发与普通推理 | Partition 内 Binpack，允许 Preferred |
| 4/8 卡通信敏感推理 | 同 NUMA/PCIe 或严格 Partition |
| 可中断训练和批任务 | Checkpoint + 低优先级 + 可抢占 |

如果四卡在线服务有明确 SLO，应预留一个完整四卡域，而不是期待调度器在满载节点上随时自动拼出连续资源。

### 阶段四：跟踪 DRA，而不是一次性押注

在独立测试节点验证：

- NVIDIA Driver 是否正确上报每张 GPU 的标准 NUMA 属性；
- `matchAttribute` 是否在调度阶段拒绝跨 NUMA 组合；
- ResourceClaim 在 Pod 删除、节点故障和 Driver 重启后能否正确回收；
- DRA 与 GPU Operator、监控、计费、队列和自动扩容器能否闭环；
- 从 Device Plugin 回滚时是否需要修改所有工作负载 API。

## 11. 最终判断

| 需求 | 建议 |
| --- | --- |
| 只想减少随机分到差拓扑 | 先验证 NVIDIA Device Plugin Preferred Allocation |
| CPU、内存和设备必须同 NUMA | 增加 Kubelet Topology Manager 作为节点侧保护 |
| 四卡任务必须是完整 NUMA/PCIe 分组 | 优先验证 Koordinator Device Topology / GPU Partition |
| 已经使用 Volcano 管理批任务 | 保留 Queue/Gang 能力，但不要把现有 `numa-aware` 当作 GPU NUMA 方案 |
| 已经采用 HAMi 做 GPU 共享 | 在现有栈内验证其拓扑策略与严格语义 |
| 希望采用 Kubernetes 标准设备属性 API | 跟踪 DRA，并先在独立节点池验证 NVIDIA Driver |

这个问题真正需要的平台契约不是“尽量选择连续卡”，而是下面两种可被用户理解的语义：

```text
Preferred：有好拓扑就用，没有也允许退化运行。
Restricted：没有完整拓扑域就等待，绝不静默退化。
```

对于通信敏感的四卡推理或训练，默认采用 `Restricted` 更容易保证性能可预测性；对于吞吐优先、拓扑不敏感的小任务，`Preferred` 可以换取更高资源利用率。把这两类策略显式暴露出来，比把所有 GPU 都伪装成完全同质的整数资源更符合生产实际。

延伸阅读：[GPU 与异构资源调度](../gpu-scheduling.md)、[GPU 有空闲，Pod 为什么仍然 Pending](gpu-pending.md)、[GPU 资源银行与潮汐推理平台实践蓝图](gpu-resource-bank-tidal-platform.md)
