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

延伸阅读：[GPU 节点软件栈](../cluster/gpu-node-stack.md)、[可观测性](../observability.md)、[可靠性](../reliability.md)

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

容器内版本为 `nvitop 1.5.0`、`nvitop-exporter 1.5.0` 和 `nvidia-ml-py 12.575.51`，而 H20 样本节点使用 580.126 驱动。`nvitop` 上游在 1.5.3 才加入 CUDA 13/NVML 580 支持，在 1.6.2 才把 `nvidia-ml-py 13.580.126` 加入支持列表；1.7.1 又修复了后台线程中的 NVML 查询与 `nvmlShutdown()` 竞争导致的间歇性 `SIGSEGV`。因此本案的主因是旧采集栈与 H20/580 驱动组合不匹配，NVML 查询路径触发原生内存错误。

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
