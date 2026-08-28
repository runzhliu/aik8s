---
title: Agent Sandbox 选型与架构分析
description: 从威胁模型、生命周期控制面、gVisor、Kata、微虚机到托管沙箱的系统选型方法
status: evolving
last_reviewed: 2026-08-29
---

# Agent Sandbox 选型与架构分析

Agent 能执行 Shell、运行用户代码、克隆仓库、打开网页或调用外部工具时，沙箱就不再是可选优化，而是生产架构的一部分。但“Agent Sandbox”可能指 Kubernetes 生命周期控制器、隔离运行时、完整虚机或托管执行 API；如果不先拆层，很容易把不同职责的项目放在一起比较。

本章给出一套面向 Kubernetes 平台的选型方法。先说结论：

- 已经有成熟 Kubernetes 平台、需要数据留在自有环境，优先评估 **Kubernetes SIG Agent Sandbox + gVisor**；
- 执行强对抗代码、租户互不信任或合规要求更高，优先评估 **Agent Sandbox + Kata Containers/独立 VM 节点池**；
- 需要 E2B 兼容 API、自托管 KVM MicroVM、模板/快照和高密度执行，并且团队能维护宿主内核与 eBPF，可评估 **CubeSandbox**；
- 产品仍在验证期、团队不想维护运行时和沙箱控制面，优先使用 **E2B、Modal、Daytona 等托管 API** 做小规模验证；
- 本地 Coding Agent 保护开发机，可使用 **Docker Sandboxes** 一类本地微虚机工具，它不是服务端多租户控制面；
- 普通 Pod、`seccomp`、非 Root 和 NetworkPolicy 是每种方案都需要的基线，但不能单独作为强对抗代码的充分隔离证明。

这些结论都必须通过自己的兼容性、安全和性能测试验证，不能把项目名称当成安全认证。

## 1. 先拆成三层

```text
Agent / Application
        │
        ▼
Sandbox API 与生命周期控制面
├── create / claim / assign / pause / resume / delete
├── template / snapshot / workspace / warm pool
└── quota / tenant / audit / metrics
        │
        ▼
执行隔离边界
├── runc + Linux namespaces / user namespace
├── gVisor user-space kernel
├── Kata / Firecracker microVM
└── full VM
        │
        ▼
外部能力与数据边界
├── Egress Proxy / Tool Gateway
├── short-lived identity / approval
├── artifact scanning / trusted CI
└── object storage / database / Git / browser
```

### 1. 生命周期控制面

负责稳定身份、创建回收、模板、预热、状态和持久工作区。Kubernetes SIG Apps 的 Agent Sandbox、托管平台的 Sandbox API、自建 Pod/VM Factory 都属于这一层。

### 2. 隔离运行时

决定不可信进程与宿主机共享什么内核边界。`runc`、gVisor、Kata Containers、Firecracker 和完整 VM 属于这一层。

### 3. 工具与数据边界

决定 Sandbox 能访问哪些网络、密钥、文件和外部副作用。NetworkPolicy、Egress Proxy、Tool Gateway、短期凭据和审批系统属于这一层。

生命周期控制器不自动提供强隔离；微虚机也不自动阻止数据外传或误删生产资源。三层必须组合。

## 2. 先写威胁模型，再看产品

### 1. 需要保护什么

- Kubernetes 节点内核、kubelet、容器运行时和其他 Pod；
- 云元数据、节点凭据、ServiceAccount Token 和生产 Secret；
- 用户源代码、数据、Prompt、模型输入和会话工作区；
- 内网数据库、Git、制品仓库、CI/CD 和 SaaS API；
- 账单、CPU、GPU、存储、带宽和外部 API 配额；
- 审计证据和租户之间的保密性。

### 2. 不可信输入从哪里来

| 来源 | 典型风险 |
| --- | --- |
| 模型生成代码 | 任意命令、无限循环、Fork Bomb、磁盘写满 |
| 用户上传代码 | 恶意二进制、内核利用、依赖投毒、数据外传 |
| 第三方仓库 | 安装脚本、Git Hook、恶意测试、Prompt Injection |
| 网页与文档 | 间接 Prompt Injection、下载恶意文件、SSRF |
| 包管理器 | Typosquatting、供应链攻击、安装时脚本 |
| MCP/工具服务 | 越权调用、恶意返回值、长期 Token 泄露 |

### 3. 风险等级

| 等级 | 工作负载 | 最低建议边界 |
| --- | --- | --- |
| L0：受信任务 | 固定镜像、固定代码、只读受控 API | Hardened Pod |
| L1：半受信脚本 | 内部用户代码、受控依赖、无生产权限 | User Namespace 或 gVisor；默认拒绝网络 |
| L2：不可信代码 | 公网用户代码、第三方仓库、浏览器自动化 | gVisor 或 Kata；独立身份和 Tool Gateway |
| L3：强对抗多租户 | 公开代码执行、租户互不信任、敏感数据 | Kata/微虚机/完整 VM；专用节点池和网络边界 |
| L4：高监管 | 强数据驻留、硬件信任或机密计算要求 | 独立集群/账户、VM 或 Confidential Containers，并做专门威胁评审 |

同一个 Agent 可以因工具不同跨越等级。例如只读搜索可能是 L1，执行陌生仓库测试是 L2，操作生产数据库则需要额外的业务授权边界，不能只靠更强运行时解决。

## 3. 十二个选型维度

不要只比较启动速度和 SDK。至少记录以下维度：

| 维度 | 关键问题 |
| --- | --- |
| 隔离边界 | 与宿主共享内核吗？攻击面是系统调用代理、Guest Kernel 还是 Hypervisor？ |
| 生命周期 | 是否有 Claim、TTL、暂停恢复、Warm Pool、孤儿回收和幂等 API？ |
| 启动路径 | 冷启动、热启动、镜像拉取、工作区恢复分别多久？ |
| 工作区 | 临时盘、PVC、快照、Fork、加密、擦除和保留策略如何实现？ |
| 网络 | 默认出站策略是什么？支持 CIDR、域名、代理和运行时变更吗？ |
| 身份 | Sandbox 是否自动获得集群/云凭据？能否使用短期、按工具授权的身份？ |
| 兼容性 | `ptrace`、FUSE、Docker-in-Docker、浏览器、systemd、eBPF 是否需要？ |
| 加速器 | GPU/TPU 是否支持？设备驱动会削弱哪些隔离假设？ |
| 密度与成本 | 每 Sandbox 固定开销、Warm Pool 闲置、节点碎片和控制面 QPS 是多少？ |
| 可观测性 | 创建阶段、命令执行、策略拒绝、网络、资源和回收能否关联到会话？ |
| 运维成熟度 | API 稳定性、升级路径、CVE 响应、HA、备份和 Runbook 是否完整？ |
| 锁定与合规 | 数据在哪里、能否自托管、API 可移植性、审计导出和删除证明如何？ |

## 4. 方案全景：不要跨层误比

### 1. 自建 Kubernetes 路线

| 方案 | 生命周期 | 隔离边界 | 优点 | 主要代价 | 适合 |
| --- | --- | --- | --- | --- | --- |
| 自建 Pod Factory + runc | 自己实现 | 共享宿主内核 | 最简单、兼容性和密度高 | 回收、预热、状态和安全都要自建 | L0、低规模内部任务 |
| Agent Sandbox + runc | 标准 CRD/SDK | 共享宿主内核 | Kubernetes 原生生命周期，迁移成本低 | Agent Sandbox 本身不增强内核隔离 | 受信 Agent、先验证控制面 |
| Agent Sandbox + gVisor | 标准 CRD/SDK | user-space kernel | 隔离、密度和启动速度较平衡 | Linux 兼容性存在缺口，需完整测试 | 大多数 L1/L2 代码执行 |
| Agent Sandbox + Kata | 标准 CRD/SDK | 每 Pod 轻量 VM/Guest Kernel | 更强内核边界，仍通过 RuntimeClass 接入 | 节点、镜像、网络、存储和可观测更复杂 | L2/L3、高风险多租户 |
| KubeVirt/自建 VM Factory | 自己或 VM API | 完整 VM | 完整 Linux/Windows 兼容和清晰 VM 边界 | 启动、密度、镜像和运维成本更高 | 需要 systemd、嵌套容器或完整 OS |
| 直接集成 Firecracker | 大量自建 | microVM/KVM | 可深度优化启动、快照和密度 | Firecracker 是 VMM 构件，不是完整 Agent 平台 | 有专职虚拟化/平台团队的超大规模系统 |
| CubeSandbox | 自带 E2B 兼容 API、调度、模板、快照和网络 | KVM MicroVM + 独立 Guest Kernel | 自托管、低延迟、高密度、控制面与数据面较完整 | K8s 交付仍是 Preview；需要 privileged/hostPID/hostPath、KVM/PVM、XFS、eBPF 和宿主机变更能力 | 有虚拟化/内核团队、需要自托管 MicroVM 平台 |

### 2. 托管或外部沙箱 API

| 方案 | 公开定位与运行时 | 优势 | 需要核实 | 更适合 |
| --- | --- | --- | --- | --- |
| E2B | 面向 Agent 的按需 Linux VM、Template 和 SDK；提供 Terraform 自托管路线 | API 简单、生态集中在代码执行/桌面、原型快 | 地域、网络策略、并发、数据驻留、自托管运维和成本 | 快速上线 Code Interpreter、Computer Use |
| Modal Sandboxes | 默认 gVisor；另有 Beta VM Sandbox | SDK、镜像、网络策略、快照和弹性平台集成完整 | 默认公网出站策略、功能 Beta 状态、快照/GPU 限制 | 已使用 Modal 或希望少维护控制面 |
| Daytona | 容器为默认，同时提供 Linux/Windows VM 与 GPU Sandbox | 多语言 SDK、快照/Fork、网络限制、完整开发环境能力 | 各 Sandbox Class 的隔离假设、地区、配额、价格和锁定 | Coding Agent、长工作区、需要 VM/GPU 选项 |
| Docker Sandboxes | 本地微虚机，每 Sandbox 独立 Docker daemon、文件系统和网络 | 保护开发机，适合 Coding Agent 本地工作流 | 不是服务端多租户调度或 Kubernetes API | 开发者桌面、本地仓库修改 |

托管平台能力变化很快。表格只用于确定 PoC 候选，采购前必须以目标区域、套餐和合同中的安全/数据条款为准。

CubeSandbox 与 Kubernetes SIG Agent Sandbox 不是同一个项目：前者是带 KVM Hypervisor、E2B 兼容 API、模板、快照、代理和 eBPF 网络的垂直平台；后者用 CRD/Controller 管理 Kubernetes 工作负载生命周期，并通过 RuntimeClass 组合 runc、gVisor 或 Kata。CubeSandbox `v0.7.0` 的 Kubernetes 前置条件、60ms 基准口径和生产阻塞项见 [CubeSandbox Kubernetes 部署条件与生产评估](cubesandbox-kubernetes.md)。

## 5. Kubernetes SIG Agent Sandbox 深入分析

### 1. 它解决什么

Agent Sandbox 用 Kubernetes CRD 表达有稳定身份、单例、可持久化的执行环境。核心和扩展对象包括：

| 对象 | 职责 |
| --- | --- |
| `Sandbox` | 单个状态化 Sandbox 的期望状态和生命周期 |
| `SandboxTemplate` | 平台维护的 Pod、RuntimeClass、卷和策略模板 |
| `SandboxWarmPool` | 预先启动指定数量的 Sandbox，降低分配延迟 |
| `SandboxClaim` | 用户侧申请接口，从 Warm Pool 领取 Sandbox |

它还提供 Python/Go Client、文件和命令操作、暂停/恢复、定时删除及 PVC 模板等能力。参考：[Agent Sandbox Documentation](https://agent-sandbox.sigs.k8s.io/docs/)。

### 2. 当前成熟度

截至 2026-08-03，项目最新发布线为 `v0.5.4`，CRD 已升级到 `v1beta1`，但项目本身仍是 pre-1.0。`v0.5.0` 和 `v0.5.1` 曾出现影响 Warm-start Claim 升级的状态竞争，并在后续版本修复。这说明它已经适合认真验证，但生产使用仍要：

- 固定 Controller、CRD Manifest 和 SDK 版本；
- 备份全部 CR 与相关 PVC 元数据；
- 在带活跃 Claim 和 Warm Pool 的环境演练升级；
- 检查 CRD `storedVersions` 和 Conversion Webhook；
- 维护版本兼容矩阵与回滚步骤；
- 避免自动跟随 `latest` 或主分支 Manifest。

版本和升级信息见 [Agent Sandbox Releases](https://github.com/kubernetes-sigs/agent-sandbox/releases) 与 [v1alpha1 到 v1beta1 迁移指南](https://agent-sandbox.sigs.k8s.io/docs/getting_started/api-migration-guide/)。

### 3. 优势

- 复用 Kubernetes Namespace、RBAC、Quota、CNI、CSI、Admission 和审计体系；
- Lifecycle API 与具体 RuntimeClass 解耦，可在 runc、gVisor、Kata 之间建立平台模板；
- `SandboxClaim` 隐藏底层 Pod 配置，平台能控制用户允许覆盖的字段；
- Warm Pool 适合交互式 Agent 对启动延迟的要求；
- PVC Template 支持每个 Sandbox 独立持久工作区；
- 状态进入 Kubernetes API，可用现有 GitOps 和可观测工具管理。

### 4. 局限

- 它是生命周期控制面，不是安全运行时或 Prompt Injection 防护系统；
- Warm Pool 用闲置资源换延迟，Pool 数量按 Runtime、镜像和资源规格相乘后可能快速膨胀；
- CRD、Controller、Router、SDK 和 RuntimeClass 增加升级与故障面；
- NetworkPolicy 的真实效果依赖 CNI，域名级出站通常仍需代理；
- 持久 PVC 会让恶意文件、下载凭据和污染状态跨会话保留；
- Sandbox API 权限过大时，用户可能通过可覆盖 Pod 字段绕过模板策略；
- pre-1.0 阶段仍可能出现 API 和升级行为变化。

### 5. 什么时候选它

适合以下条件：

- Kubernetes 已经是组织的标准运行平台；
- 有能力运维 CRD、Controller、CNI、RuntimeClass 和节点镜像；
- 数据、网络或身份必须留在自己的云账户/数据中心；
- 需要每会话独立 Workspace、Warm Pool 和租户配额；
- Sandbox 数量足以摊薄平台建设成本；
- 希望生命周期 API 与 gVisor/Kata 等底层运行时解耦。

以下情况先用托管方案可能更合理：

- 产品尚未证明需求，只需要几十个并发 Sandbox；
- 没有容器运行时、内核安全和 Kubernetes Operator 运维能力；
- 需要立即获得桌面、浏览器、快照、PTY 和文件 API；
- 可以接受数据边界、价格和 API 锁定。

## 6. 隔离运行时怎么选

### 1. Hardened runc Pod

最低基线包括：

- `runAsNonRoot`、`allowPrivilegeEscalation: false`、Drop All Capabilities；
- `seccompProfile: RuntimeDefault`，按需 AppArmor/SELinux；
- 禁止 HostPID、HostNetwork、HostIPC、HostPath 和特权设备；
- `automountServiceAccountToken: false`；
- 只读根文件系统，把可写路径映射到限额 `emptyDir`/PVC；
- CPU、内存、PID、Ephemeral Storage 和执行时长硬限制；
- 默认拒绝入站和出站；
- 专用低信任节点池，避免与控制面或敏感工作负载共置。

Kubernetes 1.36 中 Pod User Namespace 已稳定，可通过 `hostUsers: false` 把容器内 UID/GID 映射到宿主非特权范围，降低部分逃逸后的影响。它是重要加固层，但仍不等于独立 Guest Kernel。参考：[Kubernetes User Namespaces](https://kubernetes.io/docs/concepts/workloads/pods/user-namespaces/)。

### 2. gVisor

gVisor 的 `runsc` 在应用与宿主 Linux Kernel 之间提供 user-space kernel（Sentry），减少应用直接使用宿主系统调用接口的攻击面，并可通过 Kubernetes `RuntimeClass` 接入。

优点：

- 通常比完整 VM 更接近容器的启动速度和密度；
- 对大多数普通 Linux 用户态程序兼容；
- 与 Kubernetes/containerd 集成直接；
- 适合大量短时 Python、Node.js、编译和浏览器类执行；
- 支持特定 NVIDIA GPU/Driver 组合和 CDI，但需要单独验证。

限制：

- 某些文件系统、`iptables`/`nftables`、`io_uring`、设备和 KVM 能力不完整；
- 嵌套虚拟化不支持，复杂 Docker-in-Docker 和底层系统工具可能失败；
- 性能开销与 syscall、文件 I/O 和网络模式强相关，不能只用 CPU Benchmark 推断；
- GPU 通过 `nvproxy` 与宿主驱动交互，支持矩阵和 Driver 修补仍是安全计划的一部分。

先看 [gVisor Kubernetes Quick Start](https://gvisor.dev/docs/user_guide/quick_start/kubernetes/)、[Compatibility](https://gvisor.dev/docs/user_guide/compatibility/) 和 [GPU Support](https://gvisor.dev/docs/user_guide/gpu/)。

### 3. Kata Containers

Kata 通过 OCI/CRI 和 containerd/CRI-O 接入 Kubernetes，将 Pod 运行在轻量 VM 与独立 Guest Kernel 中，并通过 `RuntimeClass` 选择。

优点：

- 相比共享宿主内核，边界更接近 VM；
- Pod API、镜像格式和 Kubernetes 调度方式保持一致；
- 对需要更完整 Linux Kernel 语义的任务通常比 gVisor 更自然；
- 可与 Confidential Containers 路线结合。

代价：

- 每 Pod VM 的内存、启动、Guest Image 和 Hypervisor 开销；
- CNI、CSI、DNS、日志、监控、Debug 和升级路径更复杂；
- 节点必须支持并正确配置硬件虚拟化；
- GPU/设备直通会扩大宿主驱动和设备面，必须做硬件、Runtime 和 Driver 组合验证；
- Warm Pool、Snapshot 与 PVC 行为需要按实际 Hypervisor 和云环境测试。

架构参考：[Kata Containers Architecture](https://github.com/kata-containers/kata-containers/blob/main/docs/design/architecture/README.md)。

### 4. Firecracker 与完整 VM

Firecracker 是基于 KVM 的精简 VMM，强调 microVM 隔离、低开销和快速启动，并配有 `jailer`。它可以作为 Kata 等平台的底层技术，但不会替你提供租户、镜像构建、网络策略、工作区、API、Warm Pool、审计和回收控制面。参考：[Firecracker](https://firecracker-microvm.github.io/)。

只有在以下条件满足时才建议直接围绕 Firecracker 建平台：

- Sandbox 规模足以证明自研收益；
- 有专职虚拟化、Kernel、网络和存储工程能力；
- 标准 Kata/KubeVirt 或托管方案无法达到目标；
- 能长期维护 Guest Kernel、Snapshot 兼容、安全补丁和宿主容量管理。

需要完整 OS、Windows、systemd、复杂嵌套容器或 VM 级运维时，可评估 KubeVirt 或云 VM API。代价是更高的启动延迟、容量碎片和镜像管理复杂度。

## 7. Runtime 决策矩阵

| 需求 | runc + 加固 | gVisor | Kata/microVM | 完整 VM |
| --- | --- | --- | --- | --- |
| 普通 Python/Node 代码 | 最佳兼容 | 通常适合 | 适合 | 适合但偏重 |
| 强对抗多租户 | 不建议单独使用 | 中高，需威胁评审 | 高，仍需外围治理 | 高，仍需外围治理 |
| 冷启动与高密度 | 最优 | 较好 | 中等 | 较弱 |
| 完整 Linux Kernel 语义 | 是，但共享宿主 | 有兼容缺口 | 较完整 | 最完整 |
| Docker/systemd/eBPF | 容易但风险大 | 经常受限 | 需验证 | 最适合 |
| GPU | 原生生态最好 | 仅支持矩阵内组合 | 需直通/厂商验证 | 云/虚机型号依赖 |
| Kubernetes 接入 | 原生 | RuntimeClass | RuntimeClass | KubeVirt/外部 VM API |
| 节点运维复杂度 | 低 | 中 | 高 | 高 |
| 推荐风险级别 | L0/L1 | L1/L2 | L2/L3 | L3/L4 |

这里的“高”是相对隔离潜力，不是安全保证。运行时漏洞、错误配置、开放网络和泄露凭据都能绕过预期边界。

## 8. 托管平台怎么选

### 1. E2B

E2B 提供面向 Agent 的 Linux VM、Template、命令/文件 SDK 和桌面使用方式，也公开基础设施仓库与 Terraform 自托管路线。它适合快速实现 Code Interpreter 和 Computer Use。参考：[E2B Documentation](https://www.e2b.dev/docs) 与 [E2B GitHub](https://github.com/e2b-dev/E2B)。

PoC 要验证：

- Sandbox 创建/恢复 P50、P95 和并发配额；
- 公网入口与出站限制的默认值；
- Template 构建和供应链；
- Volume/Snapshot 的加密、删除和区域；
- API Key 的租户隔离与最小权限；
- BYOC/自托管的支持范围和运维责任；
- 长会话、桌面和批量任务的成本。

### 2. Modal Sandboxes

Modal 默认 Sandbox 使用 gVisor，并提供阻断网络、CIDR/域名 Allowlist、快照、Volume 和多语言 SDK；VM Sandbox 仍标注为 Beta。官方文档同时说明默认 Sandbox 可访问公网，因此不能把“默认安全”理解为“默认无出站”。参考：[Modal Sandboxes](https://modal.com/docs/guide/sandboxes) 与 [Networking and security](https://modal.com/docs/guide/sandbox-networking)。

适合已经使用 Modal 计算平台或希望把镜像、弹性和 Sandbox 放在同一托管体验中的团队。PoC 应重点测试网络策略、快照限制、GPU/VM 功能状态和费用模型。

### 3. Daytona

Daytona 提供容器 Sandbox、Linux/Windows VM、GPU Sandbox、Snapshot/Fork、持久 Volume 和多语言 SDK，定位更接近完整的 Agent Computer/Coding Workspace。参考：[Daytona Sandboxes](https://www.daytona.io/docs/en/sandboxes/) 与 [Architecture](https://www.daytona.io/docs/en/architecture/)。

选择时不要只看统一 API，要分别确认 Container、VM、Windows 和 GPU Class 的隔离边界、暂停/快照语义、数据位置和网络策略。官方网络限制支持 Block All、CIDR 和域名 Allowlist，但仍要验证 DNS、重定向、代理和私网访问行为。

### 4. Docker Sandboxes

Docker Sandboxes 在开发机上用微虚机隔离 Coding Agent，每个环境有独立 Docker daemon、文件系统和网络。它适合保护本地宿主和组织统一开发策略，不负责服务端 Namespace、租户配额、跨节点调度、API 并发和生产回收。参考：[Docker Sandboxes](https://docs.docker.com/ai/sandboxes/) 与 [Security model](https://docs.docker.com/ai/sandboxes/security/)。

## 9. 四套推荐组合

### 组合 A：内部 Agent，低风险受控工具

```text
Agent Control Plane
  → Agent Sandbox 或自建 Pod Factory
  → Hardened runc / User Namespace
  → 只访问 Tool Gateway
```

条件：镜像和代码受信、无公网用户代码、无直接生产写权限。仍需默认拒绝网络、短期身份和资源硬上限。

### 组合 B：通用不可信代码执行

```text
Agent Control Plane
  → SandboxClaim
  → SandboxWarmPool
  → Agent Sandbox + gVisor RuntimeClass
  → Egress Proxy / Tool Gateway
  → Artifact Scan → Trusted CI
```

这是已有 Kubernetes 平台的默认 PoC 起点。它在隔离、密度和平台一致性之间较均衡。

### 组合 C：强对抗与敏感租户

```text
独立低信任 Kubernetes Cluster / Node Pool
  → Agent Sandbox
  → Kata / microVM RuntimeClass
  → 每会话独立身份与加密 Workspace
  → 强制 Egress Proxy
  → 与生产系统跨账户 Tool Broker
```

节点池不运行控制面、Secret 管理器或敏感业务。Sandbox 即使突破 Guest，也只进入低信任故障域。

### 组合 D：产品验证或小规模托管

```text
Application Backend
  → E2B / Modal / Daytona API
  → Hosted Sandbox
  → 自有 Tool Gateway
```

即使执行环境托管，工具授权、用户身份、审批、预算和业务审计仍应由自己的控制面负责，避免把所有长期凭据放进 Sandbox。

## 10. Kubernetes 模板基线

下面只展示结构，不是可直接上线的完整清单。它要求已经安装 Agent Sandbox `v0.5.x`、名为 `gvisor` 的 RuntimeClass，并准备好固定 Digest 的内部镜像。

```yaml
apiVersion: extensions.agents.x-k8s.io/v1beta1
kind: SandboxTemplate
metadata:
  name: python-gvisor-restricted
  namespace: agent-tenants
spec:
  podTemplate:
    metadata:
      labels:
        aik8s.run/sandbox-policy: restricted
    spec:
      runtimeClassName: gvisor
      automountServiceAccountToken: false
      containers:
        - name: sandbox
          image: registry.example.com/agent/python@sha256:<digest>
          resources:
            requests:
              cpu: "500m"
              memory: 1Gi
              ephemeral-storage: 2Gi
            limits:
              cpu: "2"
              memory: 4Gi
              ephemeral-storage: 8Gi
          securityContext:
            allowPrivilegeEscalation: false
            capabilities:
              drop: ["ALL"]
            runAsNonRoot: true
            readOnlyRootFilesystem: true
            seccompProfile:
              type: RuntimeDefault
          volumeMounts:
            - name: workspace
              mountPath: /workspace
            - name: tmp
              mountPath: /tmp
      volumes:
        - name: workspace
          emptyDir:
            sizeLimit: 4Gi
        - name: tmp
          emptyDir:
            sizeLimit: 1Gi
---
apiVersion: extensions.agents.x-k8s.io/v1beta1
kind: SandboxWarmPool
metadata:
  name: python-gvisor-restricted
  namespace: agent-tenants
spec:
  replicas: 2
  sandboxTemplateRef:
    name: python-gvisor-restricted
---
apiVersion: extensions.agents.x-k8s.io/v1beta1
kind: SandboxClaim
metadata:
  name: session-example
  namespace: agent-tenants
spec:
  warmPoolRef:
    name: python-gvisor-restricted
```

生产环境还要用 Admission Policy 限制用户可选择的 Template、RuntimeClass、镜像、卷、标签和 Annotation，禁止租户直接创建任意 Pod 或修改 `SandboxTemplate`。

### 默认拒绝网络

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: sandbox-default-deny
  namespace: agent-tenants
spec:
  podSelector:
    matchLabels:
      aik8s.run/sandbox-policy: restricted
  policyTypes: [Ingress, Egress]
```

之后仅开放：

- 到受控 DNS Resolver；
- 到 Tool Gateway/Egress Proxy 的固定 Service/CIDR；
- 必须的可观测出口；
- 经过评审的对象存储或内部 Registry。

域名 Allowlist 应在代理层解析和检查最终连接目标，不能只靠静态 IP 或初始 DNS 响应。

## 11. 身份与工具边界

推荐的调用链：

```text
Sandbox 无长期凭据
  → 使用会话身份请求 Tool Gateway
  → Gateway 校验 user / tenant / session / tool / args
  → 策略或人工审批
  → 交换一次性下游凭据
  → 执行动作并记录结果摘要
  → 凭据到期
```

必须禁止：

- 默认挂载 Kubernetes ServiceAccount Token；
- 把云管理员 Key、Git Personal Token 或数据库密码写入镜像/Workspace；
- Sandbox 直接访问云元数据服务；
- Agent 自己决定是否绕过审批；
- Tool 返回内容修改平台策略；
- Sandbox 身份同时拥有生产部署权限。

## 12. Workspace、快照与持久化

工作区不是越持久越好。把数据分为：

| 数据 | 推荐策略 |
| --- | --- |
| 基础 Runtime | 只读、固定 Digest、签名验证 |
| 输入仓库/文档 | 只读快照或每会话独立 Clone |
| `/tmp`、构建中间物 | 限额 `emptyDir`，会话结束删除 |
| 用户工作区 | 每用户/会话独立 PVC，明确 TTL 和加密 |
| Package/模型缓存 | 只读共享或可信构建产生，禁止租户相互写 |
| 输出制品 | 上传隔离区，扫描后由可信 CI 重新构建 |
| 审计证据 | 写入外部不可篡改存储，不依赖 Sandbox 磁盘 |

暂停、恢复和快照会保留攻击者写入的状态。恢复前要绑定原始租户、Template/Runtime 版本和策略版本；不能把未知状态的 Sandbox 重新放回 Warm Pool 给其他租户。

## 13. Warm Pool 的容量模型

Warm Pool 不是一个全局数字，而是多个维度的笛卡尔积：

```text
Pool 数量
= Region × RuntimeClass × Base Image × CPU/Memory Class × Tenant Tier
```

如果每个组合都保留多个实例，闲置成本会迅速超过冷启动收益。建议：

1. 只为高频模板建 Pool；
2. 合并可兼容的 Runtime Image，避免每个 Agent 建一套；
3. 以过去 5～15 分钟的 Claim 到达率和目标命中率调整；
4. 记录 Warm Hit、Cold Fallback、闲置秒数和等待 P95；
5. 给 Pool 设置总预算和租户上限；
6. 发布新镜像时先建新 Pool，Drain 旧 Pool，不原地混用；
7. 控制器升级时测试已有 Warm Sandbox 的 Adoption 和状态保持。

## 14. PoC 必测项目

### 1. 功能兼容

- Python/Node/Java 和目标二进制；
- Git Clone、包安装、编译、测试和浏览器；
- PTY、信号、子进程、文件 Watch、Unix Socket；
- FUSE、Docker、systemd、eBPF、GPU 等特殊需求；
- 中文路径、大文件、长输出和并发命令；
- 断线重连、暂停恢复和 Workspace 重新挂载。

### 2. 性能

| 指标 | 至少区分 |
| --- | --- |
| Create-to-Ready | 冷节点、热节点、冷镜像、热镜像、Warm Hit |
| Claim-to-Assigned | Controller Queue、API 延迟、Pool 命中 |
| Exec 延迟 | 首次与后续命令、短命令与长命令 |
| 文件性能 | 小文件、顺序读写、Metadata、Workspace 恢复 |
| 网络 | DNS、TLS、代理、吞吐、连接数和被拒绝请求 |
| 密度 | 每节点 Sandbox 数、RSS、CPU Steal、Daemon 开销 |
| 回收 | TTL 到实际资源/PVC/路由删除的延迟 |

报告 P50/P95/P99，不只报告最佳启动时间。

### 3. 安全验证

- 尝试访问 Kubernetes API、云元数据、Node IP、kubelet 和其他 Pod；
- 尝试读取 ServiceAccount、环境变量、Host 文件和相邻租户 Workspace；
- 测试 Capability、Mount、Namespace、`ptrace`、设备和危险 Syscall；
- 测试 DNS Rebinding、HTTP Redirect、IPv6 和代理绕过；
- 执行 Fork Bomb、磁盘写满、日志洪水和连接洪水；
- 验证 Runtime 崩溃、节点重启和 Controller 重启后的清理；
- 验证 Prompt Injection 无法扩大 Tool 权限；
- 请安全团队针对目标 Runtime 版本做逃逸和供应链评审。

### 4. 运维与升级

- CRD/Controller/SDK 前后版本组合；
- 带活跃 Claim、Warm Pool、PVC 的滚动升级；
- Controller 与 Router 多副本故障；
- etcd 恢复后 Sandbox 与实际 Pod 的一致性；
- CNI、CSI、RuntimeClass 和节点镜像升级；
- 版本回滚和无法降级时的迁移方案；
- Orphan Pod、PVC、Service、NetworkPolicy 和路由清理。

## 15. 评分模板

先按业务设置权重，再打分，避免“功能最多”自动获胜。

| 类别 | 示例权重 | 评分说明 |
| --- | ---: | --- |
| 安全与隔离 | 30% | 威胁模型、运行时边界、网络、身份、审计 |
| 兼容性 | 15% | 目标代码、浏览器、工具、GPU、Docker |
| 延迟与性能 | 15% | 冷/热启动、执行、I/O、网络和密度 |
| 生命周期 | 10% | TTL、Warm Pool、暂停、快照、持久状态 |
| 运维成熟度 | 15% | 升级、HA、观测、Runbook、CVE 响应 |
| 成本 | 10% | Compute、Idle、Storage、Egress、License、人力 |
| 可移植与合规 | 5% | 自托管、数据区域、API、删除、合同 |

```text
总分 = Σ(单项 1～5 分 × 权重)
```

安全硬门槛应独立于总分：任何无法满足隔离、数据驻留或删除要求的候选，即使综合分高也不能进入下一轮。

## 16. 推荐决策树

```text
是否只保护开发者本机？
├─ 是 → Docker Sandboxes / 本地 VM
└─ 否
   │
   ├─ 产品是否仍在验证、缺少平台团队？
   │  ├─ 是 → E2B / Modal / Daytona PoC
   │  └─ 否
   │
   ├─ 是否必须自托管或复用 Kubernetes 治理？
   │  ├─ 否 → 托管与自建做 TCO/合规对比
   │  └─ 是 → Kubernetes Agent Sandbox
   │
   ├─ 是否执行公开、恶意或租户互不信任的代码？
   │  ├─ 否 → Hardened Pod / User Namespace / gVisor
   │  └─ 是
   │
   ├─ 是否需要完整 Kernel、Docker、systemd 或强 VM 边界？
   │  ├─ 否 → Agent Sandbox + gVisor
   │  └─ 是 → Agent Sandbox + Kata，或 KubeVirt/VM
   │
   └─ 是否属于高监管/高价值环境？
      ├─ 否 → 独立低信任节点池
      └─ 是 → 独立集群/账户 + VM/Confidential Containers
```

## 17. 常见误区

### “用了 Agent Sandbox CRD 就安全了”

错误。CRD 管生命周期，实际隔离取决于 RuntimeClass、Pod 配置、节点、网络和身份。

### “用了微虚机就不用 NetworkPolicy”

错误。VM 逃逸与数据外传、SSRF、误删资源是不同风险。网络和工具授权仍必须最小化。

### “域名 Allowlist 就能安全访问公网”

错误。还要处理 DNS Rebinding、Redirect、CDN、IPv6、代理协议和下载内容。高风险流量应经过 L7 Egress Proxy。

### “Warm Pool 越大体验越好”

错误。Pool 会放大闲置成本、旧镜像暴露和升级复杂度。应按命中率与延迟 SLO 动态规划。

### “Sandbox 内可以放长期 Token，反正会删除”

错误。Token 可能被网络外传、写入日志、快照或 PVC。优先使用 Tool Gateway 和一次性凭据。

### “托管平台免运维，所以不用做威胁模型”

错误。托管方负责执行基础设施的一部分，用户仍负责业务授权、数据分类、密钥、Prompt Injection、合规和删除验证。

## 18. 上线清单

- [ ] 已按 L0～L4 对代码、用户、数据和工具分类；
- [ ] 生命周期控制面、隔离运行时、工具/数据边界分别选型；
- [ ] Agent Sandbox/Runtime/SDK/Node Image 版本固定并有兼容矩阵；
- [ ] 租户不能创建任意 Pod、Template、RuntimeClass 或挂载 HostPath；
- [ ] Sandbox 默认没有 ServiceAccount Token 和长期外部凭据；
- [ ] Pod Security、Seccomp、Capability、PID 和资源限制已启用；
- [ ] 网络默认拒绝，只能访问 DNS、Tool Gateway 和必要观测出口；
- [ ] 工作区、快照、PVC、缓存和日志有 TTL、加密、配额与删除证明；
- [ ] Warm Pool 有命中率、闲置成本、镜像轮换和 Drain 策略；
- [ ] 产物只进入隔离区，经扫描后由可信 CI 重建和签名；
- [ ] 指标覆盖创建、分配、命令、策略、网络、资源和回收；
- [ ] 已测试 Runtime/Controller/Node 故障与 CRD 升级；
- [ ] 已进行逃逸、出网、资源耗尽和 Prompt Injection 安全测试；
- [ ] 每个候选都用同一组真实 Agent 任务完成基准；
- [ ] 安全硬门槛独立于功能和成本总分。

## 官方资料

- [Kubernetes SIG Agent Sandbox](https://agent-sandbox.sigs.k8s.io/docs/)
- [Agent Sandbox Releases](https://github.com/kubernetes-sigs/agent-sandbox/releases)
- [Kubernetes RuntimeClass](https://kubernetes.io/docs/concepts/containers/runtime-class/)
- [Kubernetes Security Checklist](https://kubernetes.io/docs/concepts/security/security-checklist/)
- [Kubernetes User Namespaces](https://kubernetes.io/docs/concepts/workloads/pods/user-namespaces/)
- [gVisor Kubernetes Guide](https://gvisor.dev/docs/user_guide/quick_start/kubernetes/)
- [gVisor Compatibility](https://gvisor.dev/docs/user_guide/compatibility/)
- [gVisor GPU Support](https://gvisor.dev/docs/user_guide/gpu/)
- [Kata Containers Architecture](https://github.com/kata-containers/kata-containers/blob/main/docs/design/architecture/README.md)
- [Firecracker](https://firecracker-microvm.github.io/)
- [E2B Documentation](https://www.e2b.dev/docs)
- [Modal Sandboxes](https://modal.com/docs/guide/sandboxes)
- [Daytona Sandboxes](https://www.daytona.io/docs/en/sandboxes/)
- [Docker Sandboxes](https://docs.docker.com/ai/sandboxes/)
- [CubeSandbox](https://github.com/TencentCloud/CubeSandbox)

## 继续阅读

- [AI Agent、沙箱与工具执行](../agentic-workloads.md)：工具授权、Prompt Injection、预算、审计和发布边界。
- [AI 平台安全与治理](../security-governance.md)：集群身份、Pod Security、供应链和租户治理。
- [生产参考架构](../guides/reference-architectures.md)：Agent 不可信工具执行的端到端部署位置。
- [CubeSandbox Kubernetes 部署条件与生产评估](cubesandbox-kubernetes.md)：KVM/PVM、XFS、eBPF、Helm、60ms 基准口径和生产上线边界。
