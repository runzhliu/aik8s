# Kubernetes 上的 Firecracker 实验室

这是一套可独立发布的实验文档，用于评估 Firecracker 在 Linux 和 Kubernetes
上的运行方式。它不依赖所在仓库的构建、运行时、配置或其他文档，可以整体复制到
其他站点使用。

## 验证状态

| 路径 | 状态 | 已验证内容 |
| --- | --- | --- |
| 原生 Firecracker | 已验证 | KVM 启动、API 状态、Guest 启动、TAP 网络和优雅关机 |
| Kubernetes Launcher Pod | 已验证 | 调度器放置、`/dev/kvm` 访问、Guest 启动、Pod cgroup 核算和生命周期清理 |
| Kata `RuntimeClass` + Firecracker | 已验证并保留环境 | Kata 4.1.0 runtime-rs、Firecracker 1.16.1、持久化 devmapper 激活、CNI、Guest exec、删除清理和 containerd 在线重启 |
| 快照与恢复 | 已验证 | 完整快照耗时 188.82 ms；恢复 API 耗时 16.86 ms，Guest ping 在 26.15 ms 后就绪 |
| Kata 并发 | 已验证 | 1、5、10 个 Pod 三组并发全部完成，没有失败，也没有遗留 VMM 或快照 |
| Agent 应用 | 已验证，存在一项限制 | OpenClaw、DSH 和 Hermes 完成模型及工具调用；Codex 通过 Adapter 与 MCP 测试，但其模型提供方协议不兼容 |
| 可观测性 | 已验证 | 已对齐业务容器、VMM、devmapper、宿主机和 Adapter 生命周期信号 |
| 原生 jailer | 已验证并保留环境 | 已检查 chroot、PID/挂载命名空间、非特权身份、cgroup、capability、`NoNewPrivs` 和启动后的 seccomp 状态 |

Launcher 方案有意定位为概念验证。它可以让 Kubernetes 管理 Firecracker VMM
进程，但不会让普通 Pod 自动变成由 microVM 承载的 Pod。如果目标正是获得这种
隔离边界，应使用 Kata Containers 或沙箱控制面。

## 文档目录

- [宿主机部署与原生冒烟测试](deployment.md)
- [Kubernetes Launcher 测试](kubernetes-launcher.md)
- [Kata + Firecracker RuntimeClass 测试](kata-firecracker-runtimeclass.md)
- [Firecracker 实验结果与操作手册](experiments.md)
- [Agent 工作负载：OpenClaw、DSH、Hermes 与 Codex](agent-workloads.md)
- [可观测性与资源核算](observability.md)
- [Jailer 与安全基线](security-hardening.md)
- [Firecracker、Kata、KubeVirt 与 CubeSandbox 选型](comparison.md)
- [脱敏测试报告](test-report.md)

可复用示例位于 `configs/` 和 `manifests/`，相关指南中已提供具体链接。使用前请
替换示例节点名称和镜像地址。

## 保留实验环境的访问方式

被测节点仍作为专用且带污点的 Kata/Firecracker Worker 保留。可通过以下命令
访问长期运行的 Workbench：

```bash
kubectl get pod -n firecracker-lab kata-fc-workbench -o wide
kubectl logs -n firecracker-lab kata-fc-workbench
kubectl exec -n firecracker-lab -it kata-fc-workbench -- /bin/sh
```

修改 thin pool 或 containerd 配置前，请先阅读
[RuntimeClass 指南](kata-firecracker-runtimeclass.md)；进行下一阶段测试时，请参考
[实验操作手册](experiments.md)。

## 已验证的数据流

```text
Kubernetes 调度器
        |
        v
特权 Launcher Pod -- /dev/kvm --> Firecracker VMM --> Linux microVM
        |
        +-- Kubernetes CPU、内存与生命周期 cgroup
```

它与运行时承载的路径不同：

```text
Pod runtimeClassName --> RuntimeClass --> containerd --> Kata shim
                                                     --> Firecracker --> microVM
```

两条路径都在同一个隔离 Worker 上完成了测试。当普通 Pod 需要 microVM 隔离边界
时，RuntimeClass 路径是更合适的起点；Launcher 则适合直接观察和调试 VMM。

Agent 实验组合了两套系统：

```text
Agent Pod -> Kata + Firecracker 隔离边界 -> CubeSandbox Adapter -> Agent 沙箱
```

当 Agent 运行时与它创建的临时工具执行环境都需要独立隔离时，这种双层方案有价值，
但也会增加内存、网络、存储和运维成本。普通 CubeSandbox 使用场景并不要求双层隔离。

## 安全边界

Launcher Pod 以特权模式运行，可访问 `/dev/kvm` 和一个可写宿主机目录，应将其视为
具备节点管理员权限的代码。不要向不可信租户开放这种模式，不要挂载任意宿主机路径，
也不要把它当作生产级多租户运行时。生产环境中的 Firecracker 应使用版本匹配的
`jailer`，并明确设计镜像、网络、存储、cgroup 和清理策略。

## 主要参考资料

- [Firecracker 入门指南](https://github.com/firecracker-microvm/firecracker/blob/main/docs/getting-started.md)
- [Firecracker jailer](https://github.com/firecracker-microvm/firecracker/blob/main/docs/jailer.md)
- [Kubernetes RuntimeClass](https://kubernetes.io/docs/concepts/containers/runtime-class/)
- [Kata Containers 安装指南](https://github.com/kata-containers/kata-containers/blob/main/docs/installation.md)
- [containerd devmapper snapshotter](https://github.com/containerd/containerd/blob/main/docs/snapshotters/devmapper.md)
- [Kata runtime-rs Firecracker issue #13484](https://github.com/kata-containers/kata-containers/issues/13484)
- [Kata hypervisor](https://github.com/kata-containers/kata-containers/blob/main/docs/hypervisors.md)
- [CubeSandbox 架构](https://github.com/TencentCloud/CubeSandbox/blob/master/docs/architecture/overview.md)
