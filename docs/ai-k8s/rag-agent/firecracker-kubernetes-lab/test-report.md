# 测试报告

- 日期：2026-09-02 至 2026-09-03
- 范围：一个隔离的 x86_64 Kubernetes Worker
- 结果：原生、Launcher、Kata、快照、并发、Agent、可观测性和 jailer 链路均通过，限制条件已记录

为便于独立公开发布，本报告有意省略集群名称、内网地址、镜像仓库名称、跳板机细节、凭据和
无关工作负载。

## 测试环境

| 项目 | 观测值 |
| --- | --- |
| 宿主机 OS | Anolis OS 8.8 |
| 宿主机内核 | Linux 5.10.134、x86_64、4 KiB Page |
| CPU | Intel Xeon E5-2683 v3，56 个逻辑 CPU |
| 内存 | 总计 251 GiB；测试前约 226 GiB 可用 |
| 磁盘 | 214 GiB 根文件系统；测试前约 177 GiB 可用 |
| 虚拟化 | 裸金属、Intel VMX、EPT、KVM，已启用嵌套虚拟化 |
| 设备 | `/dev/kvm` 和 `/dev/net/tun` 存在且可写 |
| Kubernetes | 1.30.4 |
| 容器运行时 | containerd 1.7.14、cgroup v1 |
| Firecracker | 1.16.1 |
| Kata Containers | 4.1.0 静态 amd64 包、runtime-rs |

## 制品完整性

安装前，Firecracker 官方发布包通过校验和验证。

| 制品 | SHA256 |
| --- | --- |
| `firecracker-v1.16.1-x86_64.tgz` | `382a02a869e4d6d5cb14c40577f9545e8458021ea8b0b2d3fc10ec14d9c242e6` |
| quickstart `vmlinux.bin` | `ea5e7d5cf494a8c4ba043259812fc018b44880d70bcbbfc4d57d2760631b1cd6` |
| quickstart `rootfs.ext4` | `2a840feeccb5cb161c6eab1ecd86667c06ed5e307da534d2d3c9e39a6ec6c30a` |
| `kata-static-4.1.0-amd64.tar.zst` | `3dc6b69c4acb787b967b04b64599a20d02a8beb1a8eaab3084110df9d0b08c96` |

基础 rootfs 已成功完成 `e2fsck -fn`。Kata 归档在离线传输前后的哈希一致。由于工作站上的
Sigstore 验证器初始化失败，未验证其 GitHub 制品证明，因此这里的 Digest 只作为传输完整性
证据。

## 原生运行结果

| 测试项 | 观测结果 | 状态 |
| --- | --- | --- |
| Firecracker 可执行文件 | `Firecracker v1.16.1` | 通过 |
| Jailer 可执行文件 | `Jailer v1.16.1` | 通过 |
| API Socket | 创建成功且可响应 | 通过 |
| `GET /version` | `firecracker_version=1.16.1` | 通过 |
| `GET /` | `state=Running`、`app_name=Firecracker` | 通过 |
| Guest 启动 | Ubuntu 进入 Multi-User，并自动登录串口 | 通过 |
| Guest 内核 | 一次性快速入门镜像中的 Linux 4.14.174 | 通过 |
| TAP 连通性 | 3/3 ICMP 回复，0% 丢包 | 通过 |
| TAP 延迟 | 本次单次运行平均 0.137 ms | 参考信息 |
| SSH Ready | 约 1,243 ms 后 TCP/22 可访问 | 参考信息 |
| 正常停止 | `SendCtrlAltDel` 返回 HTTP 204，VMM 退出 | 通过 |

这些耗时是冒烟观测，不是基准结果。它包含旧版快速入门 Guest 的初始化链路，也没有在受控
负载下重复执行。

## Kubernetes Launcher 结果

| 测试项 | 观测结果 | 状态 |
| --- | --- | --- |
| 调度位置 | Pod 选择带指定 Label 的测试节点 | 通过 |
| Pod 状态 | Running，重启次数为 0 | 通过 |
| Pod 日志中的 Guest 启动 | 到达 Multi-User、SSH 服务和串口登录阶段 | 通过 |
| Kubernetes 资源核算 | 观测时约 66 millicores、84 MiB | 参考信息 |
| 宿主机 cgroup 成员关系 | VMM PID 位于该 Pod 的 CPU、内存、设备和 PIDs cgroup 下 | 通过 |
| Pod 删除 | 删除 Pod 时 Firecracker 进程一并终止 | 通过 |

## Kata + Firecracker RuntimeClass 结果

Kata 4.1.0 静态包在可联网工作站下载，通过 Kubernetes API 传输，并使用其 runtime-rs
Firecracker 配置安装。第一阶段安装的 Firecracker 1.16.1 提供 VMM 和 jailer 二进制。

在根文件系统上创建了专用的 20 GiB 数据/2 GiB 元数据稀疏 Loopback Thin Pool，没有使用
裸盘或预先存在的 LVM 卷组。测试期间，containerd 内置 devmapper 插件从最初未配置的
`error` 状态变为 `ok`。

| 测试项 | 观测结果 | 状态 |
| --- | --- | --- |
| Runtime Handler | runtime-rs shim v2 提供的 `kata-fc` | 通过 |
| RuntimeClass 调度 | 专用 Label、Taint、Selector 和 Toleration 只选择实验节点 | 通过 |
| Snapshotter | 可在 devmapper 中看到 rootfs Layer 和活跃沙箱快照 | 通过 |
| Pod 启动 | `10:30:29Z` 创建，`10:30:33Z` Ready | 通过 |
| Guest 身份 | Linux `6.18.35`、x86_64，与宿主机 `5.10.134` 不同 | 通过 |
| CNI | Pod 获得地址并报告 `eth0` 已启动 | 通过 |
| Kubernetes exec/logs | 两者均返回 Guest 输出 | 通过 |
| VMM 证据 | 宿主机上可见独立 Firecracker 进程 | 通过 |
| 宿主机 VMM 内存 | 第 33 秒时约 129 MiB RSS | 参考信息 |
| Payload 指标 | `kubectl top` 报告容器使用 2 MiB | 参考信息 |
| Pod 删除 | Firecracker 进程和活跃 devmapper 快照消失 | 通过 |

四秒启动和内存样本来自一次冒烟运行，不构成基准结论。容器级指标不能代表宿主机 VMM RSS，
因此生产容量研究必须分别观测 shim 和 VMM cgroup。

### 兼容性发现

前两次沙箱尝试被有意保留在报告中，因为它们识别出了可复现的版本/配置问题：

1. `default_maxvcpus = 0` 展开为宿主机全部 56 个 CPU，Firecracker 因此拒绝 VM。
   实验配置副本将 `default_maxvcpus` 限制为 `2`。
2. 发布版 Firecracker runtime-rs 配置设置了 `dial_timeout_ms = 45000`，却没有兼容的
   `reconnect_timeout_ms`，Runtime 因此拒绝配置。采用上游
   [Issue #13484](https://github.com/kata-containers/kata-containers/issues/13484)
   中的 `dial_timeout_ms = 2000` 和 `reconnect_timeout_ms = 60000` 临时方案后，
   沙箱成功启动。

两次失败尝试都没有遗留孤儿 Firecracker 进程。升级 Kata 时必须重新评估这些覆盖配置，不能
盲目照搬。

## 保留环境验证

回滚路径验证后，该节点被有意重新启用为专用 Firecracker 测试 Worker。现在由 systemd
oneshot 服务挂载稀疏数据与元数据文件、创建 `fc-devpool`，并作为 containerd 的必要前置
服务。

在没有 Kata Pod 运行时测试了该依赖：

1. 停止 containerd 和 Pool 服务；
2. `dmsetup` 和两个 Loopback 查询均返回空；
3. 启动 containerd 后，Pool 服务自动启动；
4. `fc-devpool` 恢复，devmapper 插件报告 `ok`。

销毁先前的 Pool、但保留 containerd Content Store 后，遗留了两个
`containerd.io/gc.ref.snapshot.devmapper` Label，因此第一次创建保留 Workbench 时出现
`snapshot does not exist`。确认没有活跃 devmapper 快照或 Pod 后，清除了这些 Label 并
重启 containerd。下一次创建 Workbench 时，沙箱和工作负载镜像都成功解包到新 Pool，Pod
随后 Ready。

随后在 Workbench 保持活跃时在线重启 containerd。Pod UID 和 Firecracker PID 未变化，
容器重启次数保持为 0，Guest Uptime 持续增加，Pod `emptyDir` 下的文件仍可读取。

## 后续重点实验结果

### 1. 完整快照与恢复

| 检查项 | 观测结果 | 状态 |
| --- | --- | --- |
| 完整快照 API | 188.82 ms 完成 | 通过 |
| 制品 | 保留 256 MiB 内存、23 KiB VM 状态、配套 rootfs 和指标 | 通过 |
| 恢复 API | 16.86 ms 完成 | 通过 |
| 恢复后的 Guest Ready | ICMP 在 26.15 ms 后 Ready；TCP/22 可访问 | 通过 |
| 冷启动 Ready 基线 | 单次对比运行中，ICMP 在 1.280 s 后 Ready | 参考信息 |
| 快照指标 | `load_snapshot` 报告 3,957 微秒 | 参考信息 |

单次恢复到 ICMP Ready 的速度约为单次冷启动基线的 49 倍。这不是基准结论：本轮没有执行
重复的不可变磁盘克隆，也没有采集多个受控样本。

![快照与恢复证据](assets/evidence/snapshot-restore-light.jpg)

### 2. Kata 并发

| 批次 | Ready 时间 | 结果 |
| --- | --- | --- |
| 1 | 4 s | 1/1 通过 |
| 5 | 4、5、6、7、8 s | 5/5 通过；P50 6 s |
| 10 | 4、5、5、6、6、6、7、8、8、8 s | 10/10 通过；P50 6 s，P95 8 s |

峰值时包含保留 Workbench 在内共有 11 个 Firecracker 进程，聚合 RSS 约 1.45 GiB。删除
批次后，没有遗留额外 VMM 或 devmapper 快照。

![并发测试证据](assets/evidence/concurrency-light.jpg)

### 3. Agent 应用

OpenClaw 2026.8.2、DSH 0.1.2-alpha.4、Hermes 0.21.0 和 Codex 0.150.1 均以
Kata/Firecracker Pod 运行，全部 Ready 且重启次数为 0。

| 应用 | 结果 | 状态 |
| --- | --- | --- |
| OpenClaw | 模型 Turn 调用 `cube_exec`、`cube_status` 和 `cube_release`；三次调用、失败为 0 | 通过 |
| DSH | Headless 模型运行返回执行和释放标记；Adapter 审计无残留 | 通过 |
| Hermes | Plugin Doctor 和单次模型运行通过；生命周期审计无残留 | 通过 |
| Codex | 直接 Adapter 冒烟和官方 MCP stdio 握手通过；发现 17 个工具 | Adapter/MCP 通过 |
| Codex 模型 Turn | 网关使用 Chat Completions，而 Codex 自定义 Provider 要求 Responses | 未运行；协议不兼容 |

测试 Worker 无法直接路由到模型端点，Kata TAP 链路也无法使用常规 Service VIP。准入测试
临时使用中继和 Pod 直连，完成后已删除中继。凭据通过 Kubernetes Secret 注入，不会出现在
清单、截图或报告中。

![Agent 应用证据](assets/evidence/agents-light.jpg)

### 5. 可观测性

在一个采样时刻，四个 Payload 容器合计使用 1,094 MiB，而宿主机上包含保留 Workbench
在内的五个 Firecracker 进程聚合 RSS 约为 2.68 GiB。这说明只统计 Payload 的 Kubernetes
指标会低估完整运行时开销。应用任务结束后，Adapter 报告的活跃租约数为 0。

![可观测性证据](assets/evidence/observability-light.jpg)

### 7. 原生 jailer 基线

使用 jailer 1.16.1 启动了一个独立的 2 vCPU、256 MiB microVM，并保留用于后续测试。它
使用 UID/GID 65534、每实例独立 chroot、新的 PID 和挂载命名空间、64 CPU shares，以及
128 的 `nofile` 限制。VM 启动后，观测到的每个 VMM 线程都处于 seccomp 模式 2；主进程
`NoNewPrivs=1`，有效 Capabilities 为 0。

![Jailer 安全证据](assets/evidence/security-light.jpg)

## 节点最终状态

- Worker 在线且可调度；专用 `sandbox.aik8s.run/kata-fc=true:NoSchedule` Taint 阻止普通
  工作负载使用它；
- CNI 在 Worker 上 Ready；
- `RuntimeClass/kata-fc-lab` 保持安装，只选择带指定 Label 的测试节点；
- `firecracker-lab` Namespace 及其中长时间运行的 `kata-fc-workbench` Pod 保持活跃，
  可用于交互测试；
- 四个 Agent 应用 Pod 保持 Ready 并留在专用 Worker 上供检查，但临时模型网络中继已删除；
- 原生 jailer 启动的 `security-smoke` microVM 保持活跃，用于后续安全测试；
- containerd、CRI、devmapper、kubelet 和持久化 Pool 服务均处于活跃状态；Pool 服务已设置
  开机启动，并排在 containerd 之前；
- containerd 原始配置仍有备份并记录 SHA-256，当前配置包含 `kata-fc` Handler；
- 基础 Firecracker 实验、Kata 文件和离线压缩归档仍保留在磁盘上，便于重复测试；
- 临时制品传输资源已删除；
- 本文档未写入任何凭据或私有端点。

## 后续工作

1. 用生产专用存储替代 Loopback Thin Pool，并配置持久化激活、监控和恢复流程。
2. 跟踪 Kata Issue #13484，在上游修复完成验证后删除超时临时方案。
3. 验证持久卷、NetworkPolicy、资源压力、kubelet/containerd 异常故障和并发删除。
4. 通过组织批准的供应链验证路径，同步固定版本的 Kata、Firecracker、Guest 和工作负载制品。
5. 用持续维护、可复现构建的镜像替换一次性的 Ubuntu 18.04 快速入门 Guest。
6. 将有界的 1/5/10 Pod 冒烟测试扩展为重复的 50/100 Pod 并发测试，并使用等价 Ready
   标准与 CubeSandbox 对比。
7. 修复 Kata TAP 网络到 Service VIP 的可达性，用生产出站链路替换临时模型中继。
