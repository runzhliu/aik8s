---
title: GPU 节点故障图鉴
description: 用 XID、ECC、NVLink、掉卡、NCCL、RDMA 和 kubelet 证据定位 GPU 故障
status: evolving
last_reviewed: 2026-08-08
---

# GPU 节点故障图鉴

同一个“CUDA error”可能来自应用、驱动、GPU、PCIe、NVLink、NIC、交换网络或节点电源。故障图鉴的作用是保存证据和缩小故障域，不是看到错误码就自动重启节点。

## 1. 症状矩阵

| 症状 | 可能故障域 | 第一批证据 |
| --- | --- | --- |
| GPU 从 Allocatable 消失 | Device Plugin、驱动、PCIe | kubelet、插件日志、`nvidia-smi` |
| XID/ECC 增长 | GPU/显存/驱动 | DCGM、内核日志、XID 时间 |
| NCCL Timeout | 慢 Rank、GPU、NIC、Fabric | 各 Rank 日志、NCCL、RDMA 指标 |
| NVLink 降级 | Link、拓扑、硬件 | NVLink counters、拓扑图 |
| 容器看不到 CUDA | Runtime/CDI/挂载 | CDI Spec、Runtime、设备节点 |
| 性能突然下降 | 时钟、温度、功耗、链路 | DCGM、功耗、PCIe/NIC 速率 |
| 节点反复 NotReady | OS、kubelet、磁盘、网络 | Node Condition、系统日志 |

## 2. 证据顺序

```text
保存 Pod/Job/Node UID 和时间
  → 采集 Kubernetes Event 与调度状态
  → 采集 kubelet、Runtime、Device Plugin
  → 采集 DCGM/nvidia-smi/内核日志
  → 采集 NIC/RDMA/NCCL 与交换网络
  → 再决定隔离、复位、重启或维修
```

## 3. 自动隔离原则

临时错误可以阻止新任务并观察；重复 XID、不可恢复 ECC、GPU 丢失或链路硬故障应 Taint/隔离节点。正在训练的任务是否终止，要结合 Checkpoint 和分布式框架语义，不能由节点健康控制器盲目删除。

## 4. Runbook 字段

故障签名、首次时间、影响卡/节点/作业、固件/驱动版本、复现条件、诊断命令、临时处置、恢复验证、维修结论和再次发生阈值。

延伸阅读：[NCCL 报错背后的 Host Memory OOM 排障实录](nccl-unhandled-cuda-error-host-memory-oom.md)、[GPU 节点软件栈](../cluster/gpu-node-stack.md)、[可观测性](../observability.md)、[可靠性](../reliability.md)

## 5. 实战案例：GPU 指标 Exporter 在新驱动节点反复段错误

### 5.1 现象

某生产 GPU 集群的节点级指标 Exporter 以 DaemonSet 运行。集群共 207 个实例，其中 106 个发生过重启，26 个实例重启超过 100 次，单实例最高超过 1,200 次；一个实例持续处于 `CrashLoopBackOff`。容器退出码统一为 `139`，应用日志在发现 8 张 GPU 并启动 HTTP 指标端点后出现：

```text
free(): invalid next size (normal)
double free or corruption (!prev)
```

这类签名表示原生代码发生堆内存破坏并收到 `SIGSEGV`，不是 Kubernetes 探针失败，也不是容器 OOM。该 DaemonSet 没有配置健康探针，因此处于 `Running/Ready` 只能说明进程当时还活着，不能证明指标端点持续可用。

### 5.2 交叉对比

对相同镜像按节点机型聚合后，故障呈现清晰边界：

| 节点组 | GPU/驱动特征 | Pod 数 | 有重启 Pod | 累计重启 |
| --- | --- | ---: | ---: | ---: |
| 通用计算 GPU 节点 | RTX Ada、570 驱动分支 | 99 | 0 | 0 |
| 高性能 GPU 节点 | H20/H20-3e、580 驱动分支 | 108 | 106 | 11,648 |

容器内版本为 `nvitop 1.5.0`、`nvitop-exporter 1.5.0` 和 `nvidia-ml-py 12.575.51`，而 H20 样本节点使用 580.126 驱动。`nvitop` 上游在 1.5.3 才加入 CUDA 13/NVML 580 支持，在 1.6.2 才把 `nvidia-ml-py 13.580.126` 加入支持列表；1.7.1 又修复了后台线程中的 NVML 查询与 `nvmlShutdown()` 竞争导致的间歇性 `SIGSEGV`。这组证据形成了“旧采集栈不兼容”的首要假设；后续 core dump 和纠正后的升级验证进一步缩小了故障范围。

### 5.3 访问不通是另一个问题

现场同时存在“域名访问不通”，但不能把它与进程崩溃混为一谈：

- DaemonSet 仅使用 `hostNetwork` 暴露节点 `5050` 端口，没有 Service 或 Ingress。
- 配置中的业务域名只是 Pod 注解和环境变量，现场 DNS 查询返回 `NXDOMAIN`。
- 从运维终端直连节点端口也超时，说明网络 ACL/路由没有提供节点端口访问路径。

即使修复进程崩溃，仍需通过 ClusterIP Service、Prometheus 服务发现或受控 Ingress 建立明确的访问链路；不要依赖注解自动生成可访问域名。

### 5.4 建议处置与验证

1. 先制作灰度镜像，将 `nvitop` 与 `nvitop-exporter` 升到至少 1.7.1，并使用与 580.126 驱动对应的 `nvidia-ml-py 13.580.126` 或上游当前兼容版本。
2. 仅在 1～2 个 H20 节点灰度，连续采集 24 小时，观察退出码、重启数、指标抓取成功率和抓取延迟；不要先滚动全量 DaemonSet。
3. 增加 `startupProbe`、`readinessProbe` 和 `livenessProbe`，探测本机 `/metrics`，让 Ready 状态反映真实服务能力。
4. 给 Prometheus 使用明确的 Service/服务发现配置；页面访问需求应独立部署 Grafana 或受控 dashboard，而不是把节点 Exporter 直接暴露给浏览器。
5. 若新版本仍出现堆损坏，保留故障节点并采集 core dump、驱动日志和最小 NVML 复现，再向上游提交包含 GPU 型号、驱动、Python 绑定版本和栈回溯的缺陷报告。

上游依据：[nvitop v1.5.3](https://github.com/XuehaiPan/nvitop/releases/tag/v1.5.3)、[nvitop v1.6.2](https://github.com/XuehaiPan/nvitop/releases/tag/v1.6.2)、[nvitop v1.7.1](https://github.com/XuehaiPan/nvitop/releases/tag/v1.7.1)、[SIGSEGV 修复说明](https://github.com/XuehaiPan/nvitop/issues/222)

### 5.5 候选镜像构建与反证记录

现场以原 `linux/amd64` 镜像为基础增加一个 Python 依赖升级层，保留 CUDA、系统和 Python 运行环境，并将默认入口纠正为 `python -m nvitop_exporter`。本地验证结果为：目标平台正确、`pip check` 无依赖冲突、exporter CLI 可以启动。

首次推送使用了构建器默认的 OCI image index，并附带 provenance attestation。旧版同步 Jobservice 将它误报为“源仓库不存在”。使用 `--provenance=false` 重新输出单一 Docker schema v2 manifest 后，同一 tag 成功完成生产镜像同步。这个问题与应用层 NVML 崩溃无关，但会阻断修复镜像交付。

可复用构建文件位于仓库的 `examples/nvitop-exporter-fix/` 目录。

第一次候选镜像安装了 `nvitop 1.7.1`、`nvitop-exporter 1.7.1` 和 `nvidia-ml-py 13.580.126` 并完成全量 rollout。207 个 Pod 全部更新后，几分钟内至少 24 个 H20/HCC 节点再次以 139 退出；RTX Ada 节点仍为零重启。故障 Pod 的 `/proc/1/maps` 证明进程加载的是宿主机 580.126 `libnvidia-ml.so`，不是容器内残留旧库。

但进一步核验发现，这次 rollout 并没有真正运行 nvitop 1.7.1。原基础镜像的工作目录是 `/nvitop`，并保留了 1.5.0 源码；Python 的模块搜索顺序让它优先导入当前目录，而不是 site-packages 中的新包。仅检查 `pip show` 因此产生了误判，实际进程是“nvitop API 1.5.0 + exporter 1.7.1 + nvidia-ml-py 13.580.126”的混合栈。

在单个 H20 节点挂载 `/apps/logs`、开启无限 core 后，旧候选镜像约 33 秒复现崩溃并留下约 50 MiB core。带 CPython 符号的 GDB 分析将 Python 调用栈定位到 1.5.0 的 `nvitop.api.device.query_nvlink_throughput_counters()`，上层依次为 NVLink 汇总吞吐量属性和 exporter 的设备指标采集。主线程最终在 ctypes/NVML 调用后的释放路径触发 `double free or corruption (!prev)`。该结论说明触发器位于旧 NVLink 查询路径，但还不能单独证明内存破坏发生在 Python 绑定还是驱动实现。

第二版镜像显式设置 `WORKDIR /`，确保运行时从 site-packages 加载 nvitop 1.7.1。本地同时校验当前目录、`nvitop.__version__` 和 `nvitop.__file__`，避免再次被 `pip show` 欺骗。单 H20 canary 识别 8 张 GPU，连续 60 次 `/metrics` 调用全部成功，运行超过 5 分钟仍无重启；但全量 207 个实例更新后，H20-3e 节点仍复现 `double free or corruption (!prev)`。故障 Pod 的运行时模块路径确认是真实 1.7.1。短时内正式实例累计达到 111 次重启，35 个 Pod 的最后退出码为 139，说明旧源码遮蔽不是唯一原因，单节点短时 canary 也不足以覆盖该故障。

第三版镜像保留真实 1.7.1，只通过 Python `.pth` 启动钩子让 `Device.nvlink_throughput()` 返回空列表，从而绕开 core 已指向的 NVML NVLink field-value 查询。该变更会让 NVLink 总量、均值和逐链路吞吐量指标缺失或为 NaN，但不改变 GPU、显存、功耗、温度、PCIe 和进程指标。开关默认启用，并可通过环境变量显式恢复，便于上游或驱动修复后重新验证。

H20-3e canary 在 5 分钟内完成 1,180 次主动 `/metrics` 请求，其中 1,000 次并发请求，重启数 0、无 core。正式 DaemonSet 随后更新：207/207 实例全部 Ready；从 rollout 完成后的零基线连续观察 5 分钟，全量重启数仍为 0，没有退出 139 或 `CrashLoopBackOff`。在一个此前真实发生 139 的 H20-3e 节点抽查，guard 已生效，正式指标端点正常返回。

这是一项有明确指标损失的稳定性规避，不应写成 NVML 根因已经修复。生产侧仍应连续观察至少 24 小时，并调整依赖 NVLink 吞吐量的仪表盘和告警。若必须恢复该指标，应在隔离节点验证新的驱动、NVML Python 绑定或上游实现；若业务优先保证完整硬件遥测，也可继续使用已验证稳定的 DCGM Exporter。
