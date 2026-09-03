# Jailer 与安全基线

Launcher Pod 适合用于准入验证，但本质上是特权宿主机管理代码。因此，安全实验还使用版本
匹配的 Firecracker `jailer` 二进制启动了一个原生 microVM，并在 `InstanceStart` 后检查
宿主机进程。

## 已验证基线

| 控制项 | 观测结果 |
| --- | --- |
| 版本配对 | Firecracker 1.16.1 与 jailer 1.16.1 |
| 运行身份 | 专用 UID/GID 65534 |
| 文件系统 | 每实例独立 chroot；其中不存在宿主机 `/etc/shadow` |
| PID 命名空间 | 宿主机 VMM PID 在其命名空间内映射为 PID 1 |
| 挂载命名空间 | 与宿主机命名空间不同 |
| 设备 | jail 中只有显式创建的 `/dev/kvm` 和 `/dev/net/tun` 设备节点 |
| Capabilities | 有效 Capability 掩码为 0 |
| 权限提升 | VM 启动后 `NoNewPrivs=1` |
| Seccomp | VM 启动后，四个 VMM 线程均报告过滤模式 2 |
| Cgroup v1 | 启动前后 CPU shares 均保持为 64 |
| 文件描述符 | `nofile` 软、硬限制均为 128 |
| Guest | 以 2 vCPU、256 MiB 配置运行 |

在 `InstanceStart` 之前，API 进程显示 seccomp 模式 0。启动后，四个 VMM 线程都显示
seccomp 模式 2，并安装了一个过滤器。因此，安全检查必须观测启动后的 VMM，不能根据启动前
API 进程的状态推断最终安全姿态。

![已脱敏的 jailer 证据](assets/evidence/security-light.jpg)

## 部署要求

- 固定并验证相互匹配的 Firecracker/jailer 版本。
- 每个实例使用一个非特权身份和一个不复用的 chroot。
- 确保 jail UID 无法修改内核、rootfs 和配置输入。
- 只创建所选 VM 配置必需的设备节点。
- 明确设置 cgroup、rlimit、NUMA、CPU、内存、网络和清理策略。
- 对 Firecracker API Socket 进行身份验证和访问限制。
- 将 TAP 创建、镜像暂存、jail 构建和清理视为特权控制面操作，并保留审计记录。
- 验证启动后的实际进程状态：命名空间、Capabilities、`NoNewPrivs`、seccomp 模式、
  cgroup 成员关系、打开的描述符和挂载点。

测试实例被有意保留在专用实验节点上，以便继续测试。这对隔离实验是可以接受的，但生产控制器
必须保证在正常退出、API 失败、VMM 崩溃、节点重启和创建中断后都能完成清理。

## 结果边界

该冒烟测试确认文档列出的隔离控制已经生效；它不是渗透测试，也不能证明多租户安全。Guest
逃逸、恶意块设备镜像、设备模拟、内核攻击面、宿主机服务访问和清理竞态，都需要单独进行
对抗性测试。

## 主要参考资料

- [Firecracker jailer](https://github.com/firecracker-microvm/firecracker/blob/main/docs/jailer.md)
- [Firecracker seccomp 过滤器](https://github.com/firecracker-microvm/firecracker/blob/main/docs/seccomp.md)
- [Firecracker 设计](https://github.com/firecracker-microvm/firecracker/blob/main/docs/design.md)
