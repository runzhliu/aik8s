# 如何选择合适的技术层

Firecracker 和 CubeSandbox 并不是位于同一层的直接替代品。Firecracker 是 VMM；
CubeSandbox 是面向 Agent 的沙箱控制面，围绕 KVM microVM 提供调度、镜像、快照、
网络、策略、API 和 SDK。

| 方案 | 主要抽象 | 与 Kubernetes 的关系 | 最适合的场景 | 主要成本 |
| --- | --- | --- | --- | --- |
| 单独使用 Firecracker | 单个 microVM 进程及 API | 自身不依赖 Kubernetes | VMM 研究、自研平台、最精简启动路径 | 镜像、网络、调度、存储、安全和清理都要自行负责 |
| Kubernetes Launcher Pod | 启动 Firecracker 的特权 Pod | 调度器只管理 Launcher 进程 | 硬件验证和受控概念验证 | 不是 CRI 运行时，不适合不可信租户 |
| Kata + Firecracker | 由 VM 承载的 Pod 运行时 | 通过 `RuntimeClass` 选择 | 已有 Pod 工作负载需要 VM 隔离边界 | 运行时、snapshotter、CNI 集成成本和功能限制 |
| KubeVirt | VirtualMachine / VMI | Kubernetes 原生 VM 控制器 | 通用 VM、更丰富的设备和 VM 生命周期需求 | 比最小化 microVM 路径更重，也更偏向 VM |
| CubeSandbox | Agent 沙箱 API 与生命周期 | 控制面和数据面可部署在 Kubernetes | Agent 代码执行、模板、暂停/恢复、克隆/回滚、出站治理 | 平台组件多于裸 VMM |

## 实际选型建议

- 构建或测试最底层 VMM 时，选择原生 Firecracker。
- Launcher 模式只用于节点能力验证和实验。
- 已有 Kubernetes Pod 需要在尽量少改应用的前提下获得 VM 隔离边界时，选择 Kata。
- 面向用户的对象是 VM，而不是 Pod 或 Agent 沙箱时，选择 KubeVirt。
- 调用方需要沙箱服务和 SDK，而不是底层 VMM 或 Kubernetes 运行时处理器时，选择
  CubeSandbox。

CubeSandbox 官方架构在 KVM 之上使用自己的 CubeShim 和 CubeHypervisor 路径，
因此在 CubeSandbox 旁部署 Firecracker 适合做基线对比，但不能直接把 Firecracker
原地切换成 CubeSandbox 的后端。

## CubeSandbox 可以脱离 Kubernetes 运行吗？

可以。Kubernetes 不是 VMM，CubeSandbox 的 API 模型也不要求必须有 Kubernetes。
只要提供计算、网络、镜像、存储和服务发现能力，CubeSandbox 就可以通过自己的控制面
和 Worker 组件部署。Kubernetes 只是运行这些组件的一种方式，它额外提供声明式调度、
滚动更新、健康状态收敛、服务发现、Secret 分发、资源策略，以及与现有集群运维体系的
集成。

当组织已经需要多节点放置、标准化部署、配额、节点标签/污点、可观测性和受控升级时，
Kubernetes 很有价值；但它不会接管 CubeSandbox 自己的沙箱生命周期、镜像、快照或
microVM 职责。

## 组合测试说明了什么

应用测试有意为每个 Agent Pod 增加外层 Kata/Firecracker microVM，并在内层通过
CubeSandbox 沙箱执行工具。这是一种有效的纵深防御方式，但并非默认建议：

| 关注点 | 外层 Kata + Firecracker | CubeSandbox |
| --- | --- | --- |
| 受保护的工作负载 | Agent 进程及其依赖 | Agent 创建的工具或代码执行 |
| 调用接口 | Kubernetes Pod 和 `RuntimeClass` | 沙箱 API、SDK、插件或 MCP 工具 |
| 调度与生命周期 | kube-scheduler、kubelet、containerd | CubeSandbox 控制面 |
| 隔离单元 | 一个由 microVM 承载的 Pod | 一个 Agent 沙箱 |
| 快照含义 | VM/运行时快照，磁盘需单独处理 | 产品级沙箱生命周期和模板语义 |

只有当独立信任边界足以抵消额外的宿主机 RSS、双层网络路径、镜像管理和故障模式时，
才应同时使用两者。其他场景应选择 API 与工作负载更匹配的一层，而不是默认叠加。

实验验证了 Kata 4.1.0 可以在被测宿主机上通过 Firecracker 1.16.1 运行普通
Kubernetes Pod，同时也说明实际集成成本比表格看起来更高：Firecracker 需要
devmapper snapshotter、受限的 vCPU 配置，以及针对发布版配置中 runtime-rs
Firecracker 超时缺陷的临时规避方案。

后续测量补充了完整快照/恢复、Kata 并发、四种 Agent 应用路径、分层资源核算和
原生 jailer 基线。详细观测结果见[脱敏测试报告](test-report.md)，组合架构见
[Agent 工作负载指南](agent-workloads.md)。

## 建议的基准测试维度

对比时应使用相同的宿主机硬件、Guest 内核/rootfs 大小、vCPU、内存和网络策略。
至少测量：

- 从进程启动到 Guest 就绪，而不只是 VMM 进程创建；
- 每个空闲沙箱的稳态宿主机 RSS 和 CPU；
- 并发创建/删除成功率和尾延迟；
- 快照、恢复、克隆和清理的正确性；
- 网络吞吐、延迟、策略和出站审计行为；
- 镜像、租约、故障、升级和 GC 所需的运维工作量；
- 安全边界、特权组件、API 认证和审计日志。

除非单独列出平台控制面的开销，否则不要直接拿原生 Firecracker 启动时间与平台经过
认证的 API 请求耗时比较。

## 主要参考资料

- [Firecracker 设计](https://github.com/firecracker-microvm/firecracker/blob/main/docs/design.md)
- [Kata 虚拟化架构](https://github.com/kata-containers/kata-containers/blob/main/docs/design/virtualization.md)
- [Kubernetes RuntimeClass](https://kubernetes.io/docs/concepts/containers/runtime-class/)
- [KubeVirt 架构](https://kubevirt.io/user-guide/architecture/)
- [CubeSandbox 架构概览](https://github.com/TencentCloud/CubeSandbox/blob/master/docs/architecture/overview.md)
