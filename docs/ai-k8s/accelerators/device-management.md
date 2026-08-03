---
title: Device Plugin、CDI 与 DRA
description: 理解 Kubernetes 设备发现、容器注入和动态资源分配的职责、API 与迁移路径
status: evolving
last_reviewed: 2026-08-02
---

# Device Plugin、CDI 与 DRA

Kubernetes 管理 GPU、NIC、FPGA 和 AI ASIC 时涉及三个容易混淆的机制：Device Plugin 负责将设备作为扩展资源提供给 kubelet，CDI 描述容器如何获得设备，Dynamic Resource Allocation（DRA）提供更丰富的设备选择和分配 API。

它们解决的是相互关联但不同的问题。

## 一、职责对照

| 机制 | 主要回答 | 典型对象或文件 |
| --- | --- | --- |
| Device Plugin | 节点上有多少可分配设备，容器分到哪些设备 | 扩展资源、kubelet Device Plugin API |
| CDI | 容器运行时如何注入设备节点、挂载和环境变量 | CDI JSON Spec |
| DRA | 工作负载需要什么属性的设备，如何声明和绑定 | DeviceClass、ResourceSlice、ResourceClaim |
| NFD/Node Labeller | 节点具有什么硬件或软件特征 | Node Label |
| Kueue | 哪个工作负载现在可以使用多少设备配额 | Workload、ClusterQueue、ResourceFlavor |

DRA 不替代驱动安装，CDI 不负责调度，Kueue 也不选择具体设备。

## 二、Device Plugin 工作方式

典型流程：

```text
厂商 Device Plugin DaemonSet
  → 在每个节点发现设备
  → 向 kubelet 注册资源名
  → kubelet 更新 Node Capacity/Allocatable
  → Pod 通过 resources.limits 请求整数数量
  → scheduler 选择有足够扩展资源的节点
  → kubelet 调用 Allocate
  → Runtime 获得设备节点、挂载、环境变量或 CDI 设备名
```

请求示例：

```yaml
resources:
  requests:
    nvidia.com/gpu: "2"
  limits:
    nvidia.com/gpu: "2"
```

Device Plugin 的优点：

- API 稳定、生态成熟；
- Pod 写法简单；
- 调度器、配额和监控广泛支持扩展资源；
- 适合整卡或预先配置好的 MIG/共享资源。

主要限制：

- 资源通常只是整数计数；
- 很难表达每块设备属性和跨设备关系；
- 复杂共享和动态重配置依赖厂商私有机制；
- 多种相关设备的联合分配能力有限；
- 选择逻辑经常退化为节点标签。

## 三、CDI 工作方式

一个概念性 CDI Spec：

```json
{
  "cdiVersion": "0.8.0",
  "kind": "vendor.example/device",
  "devices": [
    {
      "name": "device0",
      "containerEdits": {
        "deviceNodes": [
          {"path": "/dev/example0"}
        ]
      }
    }
  ]
}
```

CDI 的价值是让设备注入从运行时特定 Hook 走向标准化描述。常见内容包括：

- Linux Device Node；
- 宿主文件或目录挂载；
- 环境变量；
- Hook；
- Intel、NVIDIA 等厂商设备的限定名称。

运维重点：

- CDI Spec 由谁生成；
- 文件目录和权限；
- 设备重配置后何时刷新；
- containerd/CRI-O 是否启用对应版本；
- 陈旧 Spec 是否会引用已不存在的设备；
- RuntimeClass 是否使用相同的 CDI 路径。

## 四、DRA API 模型

DRA 的核心角色：

```text
设备厂商 / Driver
  └── ResourceSlice：发布设备库存、属性和容量

集群管理员
  └── DeviceClass：定义可申请的设备类别和选择规则

工作负载作者
  ├── ResourceClaimTemplate：随 Pod 创建 Claim
  └── ResourceClaim：一次具体设备请求

scheduler + kubelet + DRA Driver
  └── 选择、绑定、准备、注入和回收设备
```

DeviceClass 概念示例：

```yaml
apiVersion: resource.k8s.io/v1
kind: DeviceClass
metadata:
  name: high-memory-gpu
spec:
  selectors:
    - cel:
        expression: device.attributes["gpu.example.com"].memoryGiB >= 80
```

具体 API 字段以目标 Kubernetes 版本和 Driver 文档为准。DRA 在 Kubernetes 1.34 将核心 API 推进到 GA，后续版本仍在增加共享、Workload ResourceClaim 和设备健康等能力。

参考：[Kubernetes 1.34 DRA GA](https://kubernetes.io/blog/2025/09/01/kubernetes-v1-34-dra-updates/)、[Kubernetes 1.36 DRA](https://kubernetes.io/blog/2026/05/07/kubernetes-v1-36-dra-136-updates/)

## 五、DRA 比节点标签多表达什么

传统方式：

```yaml
nodeSelector:
  nvidia.com/gpu.product: NVIDIA-H100-80GB-HBM3
resources:
  limits:
    nvidia.com/gpu: "1"
```

节点标签描述“节点上存在某类设备”，但不能保证分到的具体设备具备某属性。DRA 可以将属性与每个 Device 关联，并支持：

- 显存、型号、固件或能力选择；
- 多个候选请求和回退；
- 多容器或多 Pod 的共享语义；
- GPU、NIC 等设备的拓扑关系；
- 可配置容量或分区；
- 工作负载级 Claim 生命周期；
- 更精确的设备健康和状态。

是否真正支持取决于 Kubernetes 版本和厂商 DRA Driver，不应只根据上游 API 存在就承诺功能。

## 六、ResourceClaim 生命周期

必须验证：

1. Claim 在何时创建；
2. scheduler 在何时选择设备；
3. Pod 删除、失败和重建后是否复用；
4. Driver 重启时分配状态如何恢复；
5. 节点 NotReady 后 Claim 如何处理；
6. 多 Pod Workload 是否能整体持有设备；
7. Claim 删除后设备何时可重新分配；
8. 控制面备份恢复后状态是否一致。

有状态设备分配不能只做一次“Pod 能跑”的 Smoke Test。

## 七、Device Plugin 与 DRA 如何选择

| 场景 | 建议 |
| --- | --- |
| 单一型号、整卡独占、生态稳定 | Device Plugin 仍然合适 |
| 已有 MIG/共享资源命名且运行稳定 | 暂不为追新强制迁移 |
| 需要设备属性选择和候选回退 | 评估 DRA |
| GPU 与 NIC 等多设备拓扑联合选择 | 优先验证 DRA Driver 能力 |
| 厂商只支持 Device Plugin | 使用 Device Plugin |
| DRA 与节点自动扩容尚不兼容 | 保留 Device Plugin 或分离节点池 |
| 新建平台且厂商提供受支持 DRA | 在 Canary 节点逐步引入 |

DRA 不是 Device Plugin 的立即替代品，而是设备 API 的长期演进方向。生产平台可以在不同节点池并行使用两种模式，但同一设备通常不能由两个 Driver 同时管理。

## 八、迁移策略

### 第 1 阶段：库存与兼容性

- 固定 Kubernetes、Driver、Operator 和 Runtime 版本；
- 确认厂商支持，而不是只有实验仓库；
- 列出依赖扩展资源名的 Kueue、配额、策略和监控；
- 验证自动扩容、RuntimeClass、MIG/共享和多网卡组合。

### 第 2 阶段：独立节点池

- 准备 DRA Canary 节点池；
- 不在同一设备上运行 Device Plugin；
- 使用新的 Workload Template；
- 对比资源库存、Pod 状态和计费归属；
- 注入 Driver 重启、节点重启和 Claim 删除故障。

### 第 3 阶段：平台 API 双栈

平台接口可以暂时同时生成：

- Device Plugin 的 `resources.limits`；
- DRA 的 ResourceClaimTemplate。

选择由 Accelerator Flavor 或 Runtime 版本决定，用户不必手工维护两套复杂清单。

### 第 4 阶段：逐池迁移

按硬件型号和业务风险迁移，保留回滚到旧节点池的能力。不要在一次集群升级中同时更换 Kubernetes、驱动、DRA 和训练框架。

## 九、与队列和调度的关系

Kueue 的配额可能仍以资源 Flavor 表达，而 DRA Claim 选择具体设备。平台需要确保：

- 准入资源口径与实际设备数量一致；
- Gang/PodGroup 不会部分分配设备后长期等待；
- 拓扑约束同时考虑 Workload 和 Device；
- 抢占时 Claim 能正确释放或重用；
- 多集群分发前目标集群存在相同 DeviceClass 契约。

Kubernetes 1.36 的 Workload/PodGroup 与 ResourceClaim 集成代表这一层仍在快速演进，应在文档中明确目标版本和 Feature State。

## 十、可观测性

至少采集：

- ResourceSlice 数量和最后更新时间；
- DeviceClass、Claim、Allocation 状态；
- Claim Pending/失败原因与耗时；
- Driver Controller 和 Node Plugin 错误；
- Pod、容器、Claim、物理设备 ID 的关联；
- 设备健康、共享容量和实际利用率；
- 删除后未释放的分配；
- Driver Reconcile 和 API 延迟。

使用 Device Plugin 时也应建立 Pod UID 到设备 UUID 的映射，不能只按节点聚合 GPU 指标。

## 十一、故障场景

| 故障 | 需要验证的行为 |
| --- | --- |
| Device Plugin/Node Plugin 重启 | 已运行容器不受影响，库存恢复 |
| DRA Controller 重启 | Claim 状态可恢复，不重复分配 |
| kubelet 重启 | Pod 和设备分配一致 |
| 节点突然掉电 | 设备不会永久泄漏 |
| 设备健康恶化 | 停止新分配并保留诊断 |
| Claim 被误删 | Owner 和准入策略阻止或安全处理 |
| API Server/etcd 恢复 | ResourceSlice/Claim 与节点实际状态一致 |
| Driver 升级失败 | 可回滚且旧 Claim 可读取 |

## 十二、安全边界

- Device Plugin、DRA Node Plugin 和 CDI 生成器通常具有主机权限；
- 限制其镜像来源、hostPath、ServiceAccount 和升级权限；
- 不允许租户任意创建系统级 DeviceClass 或配置 Driver；
- DeviceClass 的 CEL 选择规则应经过审查；
- CDI Spec 目录应只允许可信组件写入；
- 设备直通、共享和 Kata Runtime 需要独立威胁模型。

## 十三、生产检查清单

- [ ] 能区分 Driver 安装、设备发现、容器注入和配额准入。
- [ ] Device Plugin 或 DRA 的选择有明确业务理由。
- [ ] 同一物理设备没有被两个机制重复管理。
- [ ] CDI Spec 的生成、刷新和权限受控。
- [ ] Claim 生命周期覆盖 Pod 删除、节点故障和控制器重启。
- [ ] 队列、计费、策略和监控已适配新的设备模型。
- [ ] 自动扩容与 DRA 的目标组合经过厂商验证。
- [ ] 每种设备管理方式都有 Canary 节点池和回滚路径。
- [ ] Feature State、Kubernetes 版本和 Driver 版本写入平台契约。
- [ ] 设备健康能阻止新分配并触发诊断。

## 延伸阅读

- [Kubernetes Device Plugins](https://kubernetes.io/docs/concepts/extend-kubernetes/compute-storage-net/device-plugins/)
- [Dynamic Resource Allocation](https://kubernetes.io/docs/concepts/scheduling-eviction/dynamic-resource-allocation/)
- [Container Device Interface](https://github.com/cncf-tags/container-device-interface)
- [NVIDIA DRA Driver](https://github.com/NVIDIA/k8s-dra-driver-gpu)
- [AMD DRA Driver](https://instinct.docs.amd.com/projects/gpu-operator/en/main/dra/dra-driver.html)
- [Amazon EKS Device Management](https://docs.aws.amazon.com/eks/latest/userguide/device-management.html)
