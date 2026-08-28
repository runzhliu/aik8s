---
title: CubeSandbox Kubernetes 部署条件与生产评估
description: 核对 CubeSandbox 的 60ms 冷启动、KVM/PVM、XFS、eBPF、Helm、节点权限和生产上线边界
status: evolving
last_reviewed: 2026-08-29
---

# CubeSandbox Kubernetes 部署条件与生产评估

CubeSandbox 是腾讯云开源的 Agent 执行环境：它用 KVM MicroVM 提供独立 Guest Kernel，以 CubeMaster、CubeAPI、Cubelet、CubeProxy、CubeVS 和 CubeEgress 组成模板、调度、网络、快照和执行 API。项目兼容 E2B SDK，但它不是 Kubernetes SIG Apps 的 Agent Sandbox CRD，也不是一个只安装 Controller 就能使用任意 `RuntimeClass` 的通用生命周期层。

截至 2026-08-29，官方最新稳定版为 [`v0.7.0`](https://github.com/TencentCloud/CubeSandbox/releases/tag/v0.7.0)，Helm Chart 的 `version` 和 `appVersion` 同为 `0.7.0`。本章按该版本核对；升级时应重新检查 Chart、节点引导脚本和发行说明。

先说结论：

- **可以部署在 Kubernetes 上，但计算节点必须允许宿主机级集成。** 默认 Chart 使用 `privileged`、`hostPID`、多个 `hostPath`、`/dev/kvm`、宿主机网络命名空间操作和 eBPF，不适合直接放进只允许 Restricted Pod Security 的通用业务集群。
- **有原生 KVM 最简单。** 裸金属或已开启嵌套虚拟化的 Linux 节点可直接作为计算节点；普通 x86 云主机可以走 PVM，但会安装定制宿主机内核、修改 GRUB/udev/fstab，并可能自动重启节点。
- **计算数据必须落在 XFS。** 试用默认创建 25 GiB loopback XFS；生产应给每台计算节点准备独立 XFS 数据盘并挂载到 `/data/cubelet`。
- **Kubernetes 交付仍标注 Preview。** 官方文档明确提示资源紧张时的驱逐风险、计算节点升级中断和 `cube-node` Pod 重建导致存量沙箱网络中断等问题。
- **“60ms 冷启动”不是 Kubernetes 端到端 SLO。** 它来自已安装完成、模板与数据已准备好的高规格裸金属节点上的沙箱创建基准，不包含节点调度、镜像拉取、Helm 安装、PVM 换核重启、模板构建或外部代理链路。

## 1. 性能与产品定位口径

CubeSandbox 官方 README、详细 Benchmark 和 Kubernetes 文档关注的测量边界并不完全相同。评估时应把 API 兼容、MicroVM 创建时延和集群端到端交付拆开记录。

| 观察项 | 官方仓库能证明什么 | 不能据此推出什么 |
| --- | --- | --- |
| E2B 兼容 | 官方提供 E2B 兼容 API/SDK，应用可复用一部分 E2B 调用方式 | API 兼容不代表底层实现、托管 SLA、功能边界或安全责任完全相同 |
| 60ms 冷启动 | 官方裸金属基准在 96 逻辑核、375 GiB 内存、NVMe XFS、2 vCPU/2 GiB 沙箱、预热 3 轮的环境中，单并发创建平均 47.8ms、P95 57.4ms | 不能当成任意云主机、冷镜像、Kubernetes 调度或高并发下的端到端 SLO |
| 50 并发仍是百毫秒级 | README 写的是平均 67ms、P95 90ms、P99 137ms；当前详细 Benchmark 则记录平均 276.1ms、P95 508.4ms、最大 681.3ms | 两组官方数据口径不一致，不能只摘较快的一组；PoC 必须固定版本、硬件、模板和统计方法复测 |
| 硬件级隔离 | 每个沙箱运行在 KVM MicroVM 和独立 Guest Kernel 中，网络由 CubeVS/eBPF 与 CubeEgress 管理 | MicroVM 不会自动解决鉴权、凭据外传、默认公网出站、Prompt Injection、供应链和控制面暴露 |

因此更准确的表述是：**CubeSandbox 是一个面向 Agent 的自托管 KVM MicroVM 平台，官方特定裸金属基准展示了约 48ms 的单并发 Create-to-Running；实际 Kubernetes 性能和生产成熟度必须重新验证。**

## 2. Kubernetes 上会安装什么

Helm Chart 同时交付控制面和计算面。

| 层级 | 主要组件 | Kubernetes 形态 | 关键依赖 |
| --- | --- | --- | --- |
| 控制面 | CubeMaster、CubeAPI、CubeOps、WebUI、CLI | Deployment + Service | MySQL/PostgreSQL、Redis、对象存储、PVC |
| 数据入口 | CubeProxy、生命周期管理器 | Deployment + Service/Ingress | TLS、通配域名、Redis、可选 CoreDNS 改写 |
| 计算运行时 | `cube-node` | DaemonSet Big Pod | KVM、hostPath、eBPF、XFS、宿主网络 |
| 产物安装 | `cube-node-installer` | DaemonSet | 向宿主 toolbox 目录写入 Shim、Kernel、Guest、Agent |
| 节点初始化 | `cube-node-bootstrap` | `hostPID` + privileged DaemonSet | 挂载/检查 XFS、加载模块、准备宿主目录 |
| PVM 换核 | `cube-node-pvm` | 可重启宿主机的 DaemonSet | x86_64、定制 PVM 内核、GRUB 和 reboot 权限 |

这是一套垂直集成平台，不是把沙箱作为普通 Pod 交给 kubelet/runc 创建。Kubernetes 负责交付组件、放置控制面与计算面 DaemonSet；真正的 Agent 沙箱由节点内 Cubelet、CubeShim 和 KVM Hypervisor 创建。

## 3. 硬条件与建议条件

### 3.1 集群与工具

| 项目 | 硬条件 | 生产建议 |
| --- | --- | --- |
| Kubernetes | `v1.24+` | 固定 Kubernetes、Chart、节点 OS、内核和 CubeSandbox 版本矩阵 |
| Helm | `v3.10+` | 发布前执行 `helm template`、预检 Hook 和 `helm test` |
| 存储 | 至少一个可用 StorageClass，或明确的外部数据库/对象存储方案 | 控制面使用可跨节点恢复的 CSI；不要在多控制节点环境依赖 hostPath |
| 镜像 | 所有节点能拉取 CubeSandbox 镜像 | 同步到内部 Registry、固定 Digest、签名验证；限制谁能发布 privileged 引导镜像 |
| 集群权限 | 能创建 ClusterRole/Binding、DaemonSet、PVC，并允许目标 Namespace 使用 privileged、hostPID 和 hostPath | 单独低信任集群或专用节点池；只对 Cube 的 ServiceAccount 和 Namespace 做最小豁免 |
| CNI | 官方已验证 TKE VPC-CNI，以及 Kubernetes/K3s + Flannel | Cilium、Calico 等其它 CNI 要补做 eBPF Hook、MTU、NAT、NetworkPolicy 和升级共存测试 |
| DNS/入口 | 若使用默认内部泛域名，需要允许 Chart 修改 `kube-system/coredns` | 不允许改 CoreDNS 时关闭 `cubeProxy.configureClusterDNS`，改用平台 DNS；外部配置通配 DNS、生产 TLS 和受控入口 |

### 3.2 节点与虚拟化

| 角色 | 最低/建议规格 | 额外条件 |
| --- | --- | --- |
| 控制面节点 | 至少 1 台；生产建议 3 台以上；每台至少 4C8G | 可访问数据库、Redis、对象存储和计算节点 |
| 计算节点 | 至少 1 台；官方建议 16C32G+ | Linux、`/dev/kvm` 可用，或使用 x86 PVM；建议独占节点 |
| 单节点试用 | 节点初始化默认最低内存约 7.5GB；实际至少按 4C8G | 官方不推荐 K8s 单节点路径，且默认 25GiB loopback 只适合体验 |

计算节点还要满足：

- 宿主内核支持 KVM；`/dev/kvm` 在引导完成后存在；
- 宿主支持并挂载 bpffs，CubeVS 可加载 eBPF 程序；
- 使用 cgroup v2 时必须暴露并启用 CPU Controller；
- `/data/cubelet` 是 XFS，生产建议启用 reflink/project quota 并独立规划容量；
- CubeSandbox CIDR 不与 Service CIDR、Pod CIDR、VPC、节点地址和现有路由重叠；
- 节点允许 privileged Pod 进入宿主 PID、Mount、Network Namespace，加载内核模块并写入宿主目录；
- 节点不是 Serverless/Virtual Kubelet 一类不暴露宿主机和 KVM 的计算形态。

### 3.3 x86_64、ARM64 与 PVM

```text
计算节点已经有 /dev/kvm？
├─ 是
│  ├─ x86_64 → 原生 KVM 路径，最直接
│  └─ ARM64  → 使用原生 KVM 的物理机/裸金属；当前不走 PVM
└─ 否
   ├─ x86_64 → 可评估 PVM；会换宿主机内核并重启
   └─ ARM64  → 当前不支持 PVM，必须换成原生 KVM 节点
```

PVM 不是普通容器插件。Chart 默认可让 `cube-node-pvm` 安装宿主机内核、设置 `kvm_pvm`、写 GRUB 和启动参数并协调重启。当前默认启动参数包含 `nopti pti=off`，因为官方 PVM 内核路径说明 `kvm_pvm` 暂不支持 host KPTI；这会扩大宿主机侧信道风险，PVM 节点不应混跑其他不可信容器或敏感工作负载。

ARM64 已在项目中支持原生构建和运行，但 PVM 宿主机/Guest 路径仍以 amd64 为主。使用 ARM64 Kubernetes 节点前，要逐个核对目标 Release 的多架构控制面镜像、BM Guest Kernel、模板镜像和测试结果，不能只根据“项目支持 ARM”推断所有 Chart 产物都已覆盖。

## 4. 节点、存储和网络准备

### 4.1 节点标签与污点

推荐至少两台机器，将控制面与计算面分开：

```bash
# 控制面节点
kubectl label node <control-node> \
  cube.tencent.com/cube-control=true --overwrite

# 计算节点
kubectl label node <compute-node> \
  cube.tencent.com/cube-node=true --overwrite
kubectl taint node <compute-node> \
  cube.tencent.com/compute=true:NoSchedule --overwrite

# 仅限需要自动安装 PVM 宿主机内核的 x86 计算节点
kubectl label node <pvm-compute-node> \
  cube.tencent.com/allow-pvm-bootstrap=true --overwrite
```

控制面污点是可选项；计算节点污点是官方安装路径要求。不要把 `allow-pvm-bootstrap=true` 打到原生 KVM 节点或 ARM64 节点上。

### 4.2 计算数据盘

试用默认值：

```yaml
bootstrap:
  nodeInit:
    dataCubelet:
      loopback:
        enabled: true
        size: 25G
```

第一次初始化会创建 `/data/cubelet-xfs.img`，以 XFS、reflink 和 project quota 挂载到 `/data/cubelet`。之后修改 `size` 不会自动扩容。

生产建议预先给每台计算节点挂载独立 XFS 数据盘，并关闭 loopback：

```yaml
bootstrap:
  nodeInit:
    dataCubelet:
      loopback:
        enabled: false
```

一键部署文档把 50GB 作为体验最低容量，多个模板或自定义镜像建议从 200GB 起；Kubernetes 生产环境仍应按模板、CoW 层、快照、日志、并发沙箱和保留期单独计算，而不是直接照搬 25GB 默认值。

### 4.3 Sandbox CIDR

Chart 默认 `cubeNode.network.cidr` 为 `172.16.0.0/18`。安装前至少核对：

- Kubernetes Service CIDR 和现有 ClusterIP；
- Pod CIDR；
- 节点主机路由与 VPC CIDR；
- 对等 VPC、VPN、IDC 和云专线路由；
- CubeEgress 的 TPROXY 地址是否是该 CIDR 的首个可用地址。

TKE 预设改用 `192.168.0.0/18`，因为常见 TKE Service CIDR 是 `172.16.0.0/16`。不要关闭冲突检查来掩盖真实重叠；这会造成不可预测的黑洞与误路由。

## 5. 最小安装流程

### 5.1 预检

```bash
kubectl get nodes -o wide
kubectl get storageclass
helm version --short

# 每台计算节点都要核对
ls -l /dev/kvm
mount | grep ' /sys/fs/bpf '
findmnt -no FSTYPE,OPTIONS /data/cubelet
ip -4 addr
ip -4 route
```

如果走 PVM，`/dev/kvm` 可以在换核前不存在，但必须确认节点允许安装内核、更新 Bootloader 和重启，并为首次启动预留维护窗口。

### 5.2 最小 values

从官方示例复制后，至少显式设置域名、TLS、MySQL 和 Redis 密码：

```yaml
cubeProxy:
  advertiseIP: "10.0.1.10"
  domain: "sandbox.example.com"
  tls:
    mode: existingSecret
    existingSecret: cube-proxy-tls

mysql:
  host: ""
  password: "<generated-password>"
  rootPassword: "<generated-root-password>"

redis:
  host: ""
  password: "<generated-password>"
```

生产环境不要把真实密码提交到 Git。应使用外部 Secret 管理器或在发布流水线中注入，并确认 Chart 生成的 Secret、数据库 URL 和对象存储凭据不会被租户读取。

### 5.3 安装与验证

```bash
helm upgrade --install cube ./deploy/kubernetes/chart \
  --namespace cube-system \
  --create-namespace \
  --values runtime-values.yaml \
  --wait \
  --timeout 90m

kubectl get pods -n cube-system -o wide

kubectl exec -n cube-system deploy/cube-cubemastercli -- \
  sh -lc 'cubeopscli --address "$CUBEOPSCLI_ADDRESS" --port "$CUBEOPSCLI_PORT" node list'

helm test cube -n cube-system --timeout 20m --logs
```

`Pod Ready` 还不够。至少继续创建一个固定模板、启动沙箱、执行命令、验证入站代理、DNS、出站策略、暂停/恢复和销毁清理。

## 6. 生产上线前的主要阻塞项

### 6.1 Kubernetes 交付仍是 Preview

官方 Kubernetes 首页目前仍标注 Preview，并明确列出：

- 计算节点资源紧张时，Pod 可能被 Kubernetes 驱逐并中断沙箱；
- 计算面升级会重建 `cube-node`，可能中断该节点上的存量沙箱网络；
- 控制面组件、数据库、对象存储、运行时和节点产物有独立升级面。

因此应先用独立测试集群验证，再进入低风险业务，不宜把首个 PoC 直接当成公开多租户生产服务。

### 6.2 `cube-node` 网络命名空间与升级

`v0.7.0` Chart 中 `cubeNode.hostNetwork` 默认是 `false`。此时 TAP 设备和 CubeVS 钩子位于 `cube-node` Pod 的 Network Namespace；Pod 重建会让该节点上的存量沙箱入站、出站同时中断，且不能自动恢复。

当前版本的 `values.yaml` 已暴露 `cubeNode.hostNetwork`。在创建任何生产沙箱前，应评估是否设置：

```yaml
cubeNode:
  hostNetwork: true
```

代价是：

- Kubernetes NetworkPolicy 不再直接作用于沙箱流量；
- 9998、9999、9966 等 Cubelet 端口会绑定到节点；
- 监控、防火墙和审计要从 Pod IP 迁移到 Node IP；
- 节点必须专用，并用 CubeEgress、节点防火墙或独立 Egress Proxy 补网络边界。

官方安装页面与当前 Chart 源码对这个 values 开关存在版本漂移，必须以固定 Release 的 `values.yaml` 和渲染结果为准。

### 6.3 默认鉴权与 TLS 只适合试用

CubeAPI 默认不启用鉴权；不设置 `AUTH_CALLBACK_URL` 时，请求会直接放行。Chart 默认 Proxy TLS 是 `selfSigned`，也只适合测试。生产至少要：

- 给 CubeAPI 配置 Auth Callback，并同时校验身份、租户、请求路径和 HTTP 方法；
- 把 CubeMaster、Cubelet、CubeOps、WebUI、数据库、Redis 和 MinIO 留在受控网络；
- 用 `existingSecret` 或 cert-manager 配置生产 TLS；
- 禁止把控制面、Cubelet gRPC/HTTP 和 WebUI 直接暴露到公网；
- 把长期云、Git、数据库凭据留在 Tool Gateway/Credential Broker，不放进 Guest 镜像或 Workspace。

Chart 可以通过 `controlPlane.api.env` 注入回调地址，例如：

```yaml
controlPlane:
  api:
    env:
      - name: AUTH_CALLBACK_URL
        value: "https://auth.example.com/verify"
```

回调服务不可达时必须按失败拒绝处理，并纳入可用性与延迟 SLO。

### 6.4 privileged 节点引导等同宿主机 Root

节点初始化脚本会通过 `hostPID`、`nsenter`、`chroot /host` 和 privileged 权限进入宿主命名空间，能够加载内核模块、创建块设备、修改 XFS、写 udev/fstab/GRUB 并重启机器。任何引导镜像供应链失陷都等同计算节点 Root 失陷。

生产要求：

- 引导镜像固定 Digest、签名验证并来自受控 Registry；
- 只有平台管理员能修改 Helm values、DaemonSet、ServiceAccount 和镜像；
- 计算节点不运行 Kubernetes 控制面、密钥管理器、CI Runner 或敏感业务；
- 宿主机变更有审计、Canary、维护窗口和回滚脚本；
- 卸载时单独清理标签、污点、hostPath、内核、GRUB、udev、fstab 和 XFS，不能假设 `helm uninstall` 会恢复宿主机。

### 6.5 控制面数据与高可用

Chart 可内置 MySQL、Redis 和 MinIO，但“有 StatefulSet”不等于生产 HA。需要明确：

- 数据库主从、备份、恢复点和升级策略；
- Redis 的 Sentinel/外部服务与故障切换；
- S3 兼容对象存储的可用性、版本、加密和生命周期；
- CubeMaster/CubeOps/API/Proxy 的副本、会话和依赖故障行为；
- 节点故障时运行中沙箱、暂停沙箱、模板与快照分别如何恢复。

`v0.7.0` 新增的跨节点暂停恢复和 S3 后端仍包含 Preview 能力；发布说明也把控制链路全路径高可用和节点故障恢复列为后续工作，不能把“支持跨机”解读为已经覆盖所有灾难恢复场景。

## 7. 建议的 PoC 验收门槛

### 7.1 功能

- 在目标节点 OS、内核、CPU 架构和 Kubernetes 版本上完成安装、重启、卸载和重装；
- 固定镜像 Digest 制作模板，跑通 Python/Node/浏览器等真实 Agent 工具；
- 验证文件、PTY、长输出、信号、并发进程、暂停/恢复、快照/克隆；
- 验证节点、CubeMaster、Redis、数据库、对象存储和 Proxy 故障行为。

### 7.2 性能

- Create-to-Running 分别测冷模板、热模板、单并发和业务峰值并发；
- 报告 P50/P95/P99、错误率、超时和回收延迟，不只报告最小值；
- 单独记录 Kubernetes 调度、镜像拉取、模板构建、MicroVM 启动和首次命令执行；
- 用真实沙箱内存写入量估算密度，不能按空载约 25～34MB 推算满载容量；
- 对 XFS Metadata、CoW、快照、对象存储、DNS、Proxy 和 Egress 分别压测。

### 7.3 安全

- 验证 Guest 不能读取宿主、Kubernetes ServiceAccount、kubelet、云元数据和其他租户数据；
- 验证默认拒绝出站、域名/CIDR 策略、DNS Rebinding、重定向和 IPv6；
- 验证 API 鉴权同时限制路径、方法、租户和资源所有权；
- 对 Cube 的 privileged DaemonSet、Hypervisor、Guest Kernel、CubeVS 和 CubeEgress 做版本化安全评审；
- 执行资源耗尽、日志洪水、磁盘写满、异常断电和升级中断测试。

## 8. 什么时候值得选

适合认真 PoC：

- 必须自托管，且需要比共享宿主内核更强的 MicroVM 隔离；
- 希望复用 E2B SDK，同时掌控节点、网络、模板和数据；
- Sandbox 数量大，冷启动与空载密度足以抵消虚拟化与节点运维投入；
- 团队已有 Kubernetes、Linux Kernel、KVM、eBPF、网络和存储工程能力；
- 能提供独立低信任集群或节点池，并接受 Preview 阶段的版本固定和升级演练。

先不要选：

- 集群不允许 privileged、hostPID、hostPath、内核模块或节点重启；
- 只能使用 Serverless Kubernetes/Virtual Node；
- 没有独立计算节点，必须与敏感业务或 Kubernetes 控制面混跑；
- 只需要几十个低风险沙箱，团队不想维护内核、网络、数据库和对象存储；
- 需要今天就获得成熟 SLA、全路径 HA、跨节点故障恢复和无中断升级。

这类场景可先比较 Kubernetes SIG Agent Sandbox + gVisor/Kata、KubeVirt，或 E2B/Modal/Daytona 等托管 API。分层选型方法见 [Agent Sandbox 选型与架构分析](agent-sandbox-selection.md)。

## 官方资料

- [CubeSandbox GitHub](https://github.com/TencentCloud/CubeSandbox)
- [v0.7.0 Release](https://github.com/TencentCloud/CubeSandbox/releases/tag/v0.7.0)
- [Kubernetes 部署总览](https://cubesandbox.com/zh/guide/kubernetes/)
- [Helm 安装](https://cubesandbox.com/zh/guide/kubernetes/install)
- [Kubernetes 架构说明](https://cubesandbox.com/zh/guide/kubernetes/architecture)
- [Kubernetes FAQ](https://cubesandbox.com/zh/guide/kubernetes/faq)
- [v0.7.0 Chart 默认值](https://github.com/TencentCloud/CubeSandbox/blob/v0.7.0/deploy/kubernetes/chart/values.yaml)
- [v0.7.0 节点初始化脚本](https://github.com/TencentCloud/CubeSandbox/blob/v0.7.0/deploy/kubernetes/images/scripts/cube-node-init.sh)
- [裸金属性能基准](https://github.com/TencentCloud/CubeSandbox/blob/v0.7.0/docs/zh/blog/posts/2026-06-01-cubesandbox-perf-benchmark.md)
- [PVM 性能基准](https://github.com/TencentCloud/CubeSandbox/blob/v0.7.0/docs/zh/blog/posts/2026-06-03-cubesandbox-perf-benchmark-pvm.md)
- [ARM64 支持说明](https://github.com/TencentCloud/CubeSandbox/blob/v0.7.0/docs/zh/blog/posts/2026-07-08-cubesandbox-arm-support.md)
- [鉴权配置](https://cubesandbox.com/zh/guide/authentication)
- [网络加固](https://cubesandbox.com/zh/guide/network-hardening)
