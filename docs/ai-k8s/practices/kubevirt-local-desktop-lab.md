---
title: KubeVirt 单节点桌面实战：本地盘、CDI 与浏览器 noVNC
description: 在没有 Ceph 的 Kubernetes 集群中，把 KubeVirt VM 限制到单个节点，使用本地盘保存完整系统环境，并通过受限 noVNC 网关从浏览器访问桌面
status: lab
last_reviewed: 2026-08-05
---

# KubeVirt 单节点桌面实战：本地盘、CDI 与浏览器 noVNC

容器 Notebook 最难处理的并不是 Notebook 文件，而是用户会把 Conda、Python、编译器、IDE 插件、系统包和缓存写到任何目录。平台可以挂载 `/home` 或 `/workspace`，却很难约束每个人始终把所有状态写进 PVC。容器重建后，遗漏在镜像可写层里的环境仍会消失。

这次实战采用另一条路线：在 Kubernetes 中运行一台具有持久根盘的 KubeVirt VM。用户修改的是完整 guest 文件系统，停止 VM 后释放 CPU 和内存，再次启动仍可恢复原环境。实验没有共享存储，先用一个节点上的 Local LVM 验证完整链路；后续接入 Ceph RBD 时，可以保留上层 VM、CDI 和访问方式，只替换 StorageClass。

最终跑通了以下路径：

```text
办公网浏览器
  → 节点地址:6080
  → 带 Basic Auth 的 noVNC/WebSocket 代理
  → virtctl VNC 子资源
  → KubeVirt VMI
  → Tiny Core 图形桌面
  → 节点本地 LVM DataVolume
```

本文只使用公开项目地址和通用占位符，不依赖特定公司的地址、账号或密码。`<...>` 必须替换成自己的值，版本和镜像应固定到经过验证的 tag 或 digest。

## 1. 适用范围和边界

这个方案适合：

- 先在一个支持 KVM 的节点验证 KubeVirt，而不改动其他节点；
- 用户环境是“可长期修改的 Linux 工作站”，不仅是几个 Notebook 文件；
- 用户个人根盘不需要在多台机器之间共享；
- 当前没有 Ceph RBD，但节点已有 Local LVM、Local PV 或其他本地 CSI；
- 办公网能够直接访问节点地址，因此实验阶段不需要 NodePort。

它不等于生产高可用方案：

- 本地盘绑定节点，节点故障时 VM 不能自动在别处恢复；
- 本地卷通常不能支持 VM 热迁移；
- `Retain` 只降低误删风险，不等于备份；
- 浏览器直连节点端口适合受控办公网实验，生产入口仍应使用 HTTPS、统一认证和审计；
- Tiny Core 只是快速验证桌面和 VNC，不适合作为 Jupyter 或 code-server 的正式开发环境。

如果已有 Ceph RBD，生产设计参见[用 KubeVirt 与 Ceph RBD 构建持久 GPU Notebook](kubevirt-rbd-notebook.md)。

## 2. 先读懂 KubeVirt：CRD、控制器和虚拟机运行链路

KubeVirt 不是另一套独立于 Kubernetes 的虚拟化平台，也不是把 Kubernetes 节点替换成传统 Hypervisor。它通过 CRD、Controller、Webhook 和节点 DaemonSet，把虚拟机变成 Kubernetes API 能声明和协调的一类工作负载。网络仍由 CNI 提供，磁盘仍由 CSI/PVC 提供，调度、配额、优先级、ServiceAccount、审计和 Namespace 仍沿用 Kubernetes。

官方概念与组件说明可对照 [KubeVirt Architecture](https://kubevirt.io/user-guide/architecture/) 和 [Virtual Machines](https://kubevirt.io/user-guide/user_workloads/virtual_machines/)。

可以把它理解成四层：

```text
用户与平台层
  kubectl / virtctl / KubeVirt Manager / 自研 Workspace Portal
                     │ 创建和修改 Kubernetes 对象
                     ▼
声明式 API 层
  VirtualMachine、VMI、Migration、Snapshot、DataVolume 等 CRD
                     │ Controller 持续比较期望状态与实际状态
                     ▼
Kubernetes 编排层
  scheduler、Pod、PVC/CSI、CNI、Service、RBAC、Quota、PriorityClass
                     │ 把 virt-launcher 调度到具体节点
                     ▼
节点虚拟化层
  virt-handler → virt-launcher → libvirt/QEMU/KVM → guest OS
```

CRD 是 CustomResourceDefinition，作用是给 Kubernetes API 增加新的资源类型；CR 是这些类型的具体对象。安装 KubeVirt 后，API Server 才会认识 `VirtualMachine`、`VirtualMachineInstance` 等资源。只有 CRD 还不能运行虚拟机，真正执行协调逻辑的是 KubeVirt Controller、Webhook 和节点组件。

### 2.1 最容易混淆的 VM、VMI 与 Pod

这三个对象分别表达不同层次：

| 对象 | 类比 | 生命周期 | 主要保存什么 |
| --- | --- | --- | --- |
| `VirtualMachine`，简称 VM | Deployment 一类的长期期望状态 | 可以长期存在，停止后仍保留 | 开关机策略、VM 模板、CPU/内存、卷和网络声明 |
| `VirtualMachineInstance`，简称 VMI | 正在运行的 Pod | 每次启动创建，停止后删除 | 本次运行实例、节点、Guest IP、运行条件和迁移能力 |
| `virt-launcher` Pod | 承载进程的 Pod | 与 VMI 同生共死 | QEMU/libvirt 进程、卷挂载、tap/NAT 和 Console/VNC socket |

创建一个 `runStrategy: Always` 的 VM 后，核心链路是：

```text
VirtualMachine
  → virt-controller 创建 VirtualMachineInstance
  → virtualmachine-controller 创建 virt-launcher Pod
  → kube-scheduler 结合资源、亲和性和 PV nodeAffinity 选择节点
  → 目标节点 virt-handler 通知 virt-launcher 定义 libvirt domain
  → QEMU 打开 PVC/块设备，创建 tap，启动 guest OS
  → VMI status 回报节点、IP、Guest Agent 和 Ready 条件
```

所以：

- `kubectl get vm` 回答“这台机器应该开机还是关机”；
- `kubectl get vmi` 回答“当前是否存在一个正在运行的实例”；
- `kubectl get pod` 回答“QEMU 进程落在哪个节点、容器为什么 Pending 或退出”；
- `virtctl stop <vm>` 通常删除 VMI 和 `virt-launcher`，但 VM 与独立 PVC 继续存在；
- 删除 VM 是否连带删除磁盘，取决于磁盘是独立 PVC，还是由 `dataVolumeTemplates` 等方式被 VM 拥有，不能仅凭名称判断。

### 2.2 常见 KubeVirt CRD 到底负责什么

安装后会看到几十个 CRD，它们不是都需要业务用户直接创建。按职责理解比背名称有效：

| API 资源 | 谁通常创建 | 作用与使用时机 |
| --- | --- | --- |
| `KubeVirt` | 集群管理员 | 集群级安装实例；配置 feature gate、节点放置、允许直通的设备和证书策略。通常一个集群只有一个 |
| `VirtualMachine` | 用户或平台 | 长期 VM 定义，管理启动、停止和模板 |
| `VirtualMachineInstance` | VM Controller；也可直接创建 | 一次实际运行。普通平台不应把直接创建 VMI 当默认方式，否则缺少长期 VM 对象管理重启 |
| `VirtualMachineInstanceMigration` | 运维或迁移控制器 | 请求 VMI 热迁移；本地盘、PCI Passthrough GPU 等条件可能使其不可迁移 |
| `VirtualMachineInstanceReplicaSet` | 平台 | 维持一组同构 VMI，语义类似 ReplicaSet；个人工作站通常不需要 |
| `VirtualMachinePool` | 平台 | 管理一组 VM 及副本，适合 VM 池而非单人宠物工作站 |
| `VirtualMachineSnapshot` / `VirtualMachineRestore` | 用户或备份平台 | 协调 VM 配置和 CSI 卷快照、恢复；底层仍依赖 CSI Snapshot 能力 |
| `VirtualMachineExport` | 用户或镜像平台 | 通过临时导出服务下载 VM、PVC 或快照内容 |
| `VirtualMachineInstancetype` / `ClusterInstancetype` | 平台管理员 | 复用 CPU、内存等规格，类似云主机 Flavor |
| `VirtualMachinePreference` / `ClusterPreference` | 平台管理员 | 复用机器类型、磁盘总线、固件等偏好；与 Instancetype 分工 |
| `VirtualMachineTemplate` | 新版 KubeVirt 的模板平台 | 把 VM 及相关资源组织成参数化模板；是否默认部署取决于 KubeVirt 版本 |

先看集群实际安装了什么，不要根据另一篇文章猜测：

```bash
kubectl api-resources --api-group=kubevirt.io
kubectl get crd | grep -E 'kubevirt.io|cdi.kubevirt.io'
kubectl explain virtualmachine.spec
kubectl explain virtualmachineinstance.status.conditions
```

`KubeVirt` CR 与业务 VM 不是一回事。前者由 Operator 持续协调，用来安装和配置整个虚拟化控制面；后者是 Namespace 内的用户工作负载。修改 `KubeVirt` CR 可能滚动整个控制面或改变所有 VMI 行为，权限应只给集群管理员。

### 2.3 常驻组件和按需组件

KubeVirt 的常驻组件负责“管理”，运行中的 VM 才产生真正的 QEMU 工作负载：

| 组件 | 形态 | 职责 |
| --- | --- | --- |
| `virt-operator` | Deployment | 安装、升级、回滚并协调 KubeVirt CR |
| `virt-api` | Deployment + APIService/Webhook | 提供准入、验证以及 Console、VNC、start/stop 等子资源 API |
| `virt-controller` | Deployment | 协调 VM、VMI、迁移、快照及 `virt-launcher` Pod |
| `virt-handler` | DaemonSet | 每个可运行 VM 的节点一个，连接节点上的 libvirt/QEMU 生命周期 |
| `virt-launcher` | 每个活跃 VMI 一个 Pod | 承载该 VMI 的 QEMU/libvirt 进程；不是常驻控制面 |
| `virt-exportproxy` / `virt-exportserver` | 常驻入口 + 按需服务 | 处理 VM/PVC/快照导出；没有导出任务时不应把 export server 当常驻 VM 开销 |

排障时先判断问题属于哪一层：VM Controller 没创建 VMI、scheduler 没调度 Pod、CSI 没绑定 PVC、virt-handler 没同步 domain，还是 guest 自己没有启动服务。只看一个 `kubectl get vm` 状态往往不够。

### 2.4 CDI 是什么，为什么装 KubeVirt 时经常一起出现

CDI 全称 Containerized Data Importer，是 KubeVirt 生态里独立的存储数据准备项目。KubeVirt 本身擅长“拿一块已经准备好的磁盘启动 VM”，但不会替你完成以下工作：

- 从 HTTP 下载 Ubuntu QCOW2/RAW 镜像并写入 PVC；
- 从 OCI Registry 导入 `containerDisk` 风格的磁盘内容；
- 接收 `virtctl image-upload` 上传的本地镜像；
- 从已有 PVC 或 `VolumeSnapshot` 克隆出用户独立根盘；
- 创建空白磁盘，并在数据准备完成前阻止 VM 过早启动。

CDI 为此引入 `DataVolume`。可以把 DataVolume 理解为“带数据来源和准备状态的 PVC 上层对象”：

```text
DataVolume
  ├─ source：http / registry / upload / pvc / snapshot / blank
  ├─ storage：StorageClass / accessModes / volumeMode / size
  ├─ 目标 PVC
  └─ status：Pending / ImportInProgress / CloneInProgress / Succeeded
```

最小导入示例：

```yaml
apiVersion: cdi.kubevirt.io/v1beta1
kind: DataVolume
metadata:
  name: ubuntu-golden
  namespace: kubevirt-lab
spec:
  source:
    http:
      url: https://example.invalid/ubuntu.qcow2
  storage:
    storageClassName: <storage-class>
    accessModes: [ReadWriteOnce]
    volumeMode: Block
    resources:
      requests:
        storage: 100Gi
```

CDI Controller 创建或填充目标 PVC，Importer/Cloner/Upload Server 是按任务出现的 Pod。数据完成后，这些临时 Pod 消失，VM 最终只消费 PVC；CDI 不在每次 guest 读写磁盘的数据路径上，因此它不是一个长期 I/O 代理。

完整来源类型和行为以 [Containerized Data Importer](https://kubevirt.io/user-guide/storage/containerized_data_importer/) 为准。

CDI 自己也有几类 CRD：

| CDI 资源 | 作用 |
| --- | --- |
| `CDI` | Operator 管理的集群级安装与配置对象 |
| `CDIConfig` | CDI 运行配置和能力状态 |
| `DataVolume` | 声明目标卷的数据来源、容量和准备流程 |
| `DataSource` | 为黄金镜像提供稳定引用，可在后台切换到新 PVC 或 Snapshot |
| `StorageProfile` | 记录每个 StorageClass 的默认访问模式、卷模式、快照类和克隆策略 |
| `ObjectTransfer` | 在特定场景跨 Namespace 转移 DataVolume/PVC 所有权 |

### 2.5 CDI 克隆为什么有时快、有时会复制很久

CDI 会结合 `StorageProfile` 和 CSI 能力选择克隆策略：

| 策略 | 数据路径 | 优点 | 风险与前提 |
| --- | --- | --- | --- |
| CSI Volume Clone | 存储驱动原生克隆 PVC | 通常最快、数据不经过 Pod 网络 | CSI 必须正确实现可写克隆、拓扑和扩容 |
| CSI Snapshot Clone | 先快照，再由快照恢复 PVC | 适合黄金镜像和批量派生 | 快照恢复必须产生可写卷；一致性仍需 guest freeze/停机配合 |
| Host-assisted Copy | Source Pod 读取源卷，Upload/Clone Pod 写目标卷 | 不依赖存储原生克隆，兼容面广 | 会真实读取和写入磁盘，占网络、CPU 和 I/O，几十台并发会压垮 HDD |

这次 Local LVM 实验验证了一个很重要的边界：`VolumeSnapshot ReadyToUse=True` 只说明快照对象已经准备好，不保证“恢复出的 PVC 一定适合当可写 VM 根盘”。实际恢复出的 PV 带有只读属性，QEMU 最终报根盘为只读文件系统。把 CDI 强制切到 host-assisted copy 后，又暴露了存储驱动对文件系统开销取整和 Block 设备权限的兼容问题。

因此批量创建用户 VM 前必须先做一台完整金丝雀：

1. 停止或 freeze 黄金 VM，创建 Snapshot；
2. 恢复一个独立目标 PVC；
3. 检查 PV 的 `volumeMode`、`nodeAffinity`、CSI `volumeAttributes` 和只读标记；
4. 启动 VM，实际在 guest 根盘创建文件并重启；
5. 删除金丝雀并确认底层卷被正确回收；
6. 再决定批量采用原生快照、CSI Clone、CDI Copy，还是由镜像流水线生成新的 RAW/QCOW2。

不要一次创建 50 个克隆后才验证第一台能否写盘。对本地 HDD，host-assisted copy 还应限制并发；对 Ceph RBD，则要验证快照分层、flatten、深度、回收和故障域行为。

### 2.6 PVC、DataVolume、containerDisk、cloud-init 分别放什么

| 机制 | 是否持久 | 典型用途 | 不应承担的职责 |
| --- | --- | --- | --- |
| PVC | 是 | VM 根盘、数据盘；最终由 CSI 提供块设备或文件系统 | 不描述镜像从哪里来 |
| DataVolume | 目标 PVC 持久，准备 Pod 临时 | 导入、上传、克隆和初始化 PVC | 不替代 CSI，也不长期代理磁盘 I/O |
| `containerDisk` | 随镜像/Pod，可视为只读分发介质 | Smoke test、只读系统盘、安装介质 | 保存用户长期修改 |
| `cloudInitNoCloud` | 启动配置介质；内容来自 VM 定义/Secret | 首次用户、SSH Key、hostname、网络和初始化脚本 | 保存大量数据或作为持续配置管理系统 |
| `emptyDisk` / ephemeral | 否 | 临时 scratch、一次性测试 | 用户环境和重要结果 |

`containerDisk` 是 OCI 容器镜像中的磁盘文件，不等于“VM 的所有磁盘都变成容器镜像”。Ubuntu ISO、QCOW2 和 RAW 也不是同一种东西：ISO 通常是安装介质；QCOW2 是支持稀疏、压缩和快照元数据的磁盘格式；RAW 更接近直接块内容，体积可能稀疏但写入路径简单。CDI 可以负责格式识别与转换，最终写入 PVC。

### 2.7 调度为什么会同时看到 VM、Pod 和 PVC Pending

VM 最终还是 `virt-launcher` Pod，因此调度器需要同时满足：

- VM 的 CPU、内存、扩展资源、Node Selector、Affinity 和 Toleration；
- KubeVirt 自动增加的 KVM、网络和设备条件；
- PVC 的可用区与 PV `nodeAffinity`；
- Local Storage 的 `WaitForFirstConsumer` 拓扑决策；
- CDI Importer/Cloner 等临时 Pod 的调度条件。

使用本地盘时，WFFC 会形成一个看似循环、其实有意设计的过程：PVC 先 Pending，等真正消费者暴露目标节点；scheduler 选出节点后，CSI 才在该节点创建卷。排障顺序应是：

```bash
kubectl -n <ns> get vm,vmi,pod,dv,pvc -o wide
kubectl -n <ns> describe vmi <name>
kubectl -n <ns> describe pod <virt-launcher-pod>
kubectl -n <ns> describe pvc <pvc>
kubectl -n <ns> get events --sort-by=.lastTimestamp
```

如果 VMI Pending，不要只给 VM 增加资源；先确认到底是 scheduler、PVC 拓扑、CDI 临时 Pod还是 KubeVirt 节点能力在等待。

### 2.8 KubeVirt Manager 在架构中处于哪里

KubeVirt Manager 是浏览器管理界面，不是新的 Hypervisor，也不替代 `virt-controller`。它通过 ServiceAccount 和 Kubernetes API 读取或修改上述 CRD，并调用 Console/VNC 等子资源。因此 UI 能看到多少 Namespace、能否删除磁盘或修改集群对象，最终取决于它的 Kubernetes RBAC。

安装、认证与 WebSocket 入口配置可参考 [KubeVirt Manager documentation](https://docs.kubevirt-manager.io/)。

实验环境可以使用官方 bundled manifest 快速安装，但上线前至少要检查：

- Deployment 的镜像 tag/digest、Pod 标签和 Service selector 是否一致；
- ServiceAccount 被绑定了哪些 ClusterRole，是否远超实际管理范围；
- HTTP Basic/OIDC 是否启用，入口是否使用 HTTPS；
- Ingress/Gateway 是否正确代理 VNC 与 XTerm WebSocket；
- 管理端是否只对办公网或管理网开放；
- “前端登录认证”与“Kubernetes API 授权”是两层控制，不能只做其中一层。

KubeVirt Manager 适合管理员和实验室运维；面向多用户的 Notebook Portal 仍应实现用户到 VM 的所有权映射、配额、最多同时启动数量、空闲关机、删除保护和审计。

## 3. 实验组件

| 组件 | 作用 | 本次选择 |
| --- | --- | --- |
| KubeVirt | 在 Kubernetes 中管理 VM/VMI | Operator + KubeVirt CR |
| CDI | 导入镜像、克隆 PVC、创建空白 DataVolume | 即使没有 Ceph 也可以使用 |
| 本地 CSI | 为 VM 提供持久块设备或文件系统卷 | `WaitForFirstConsumer` 的 Local LVM StorageClass |
| Tiny Core ISO | 快速验证图形启动、键鼠和 VNC | 仅用于 smoke test |
| `virtctl` | Console、VNC 和 VM 生命周期客户端 | 版本与 KubeVirt 匹配 |
| noVNC + websockify | 把 VNC 转换为浏览器可访问的 WebSocket | 独立、最小权限代理 Pod |

KubeVirt 的 `containerDisk` 会随 Pod 生命周期变化，不适合保存需要长期修改的根文件系统。持久状态应写入 DataVolume/PVC。参考 [KubeVirt disks and volumes](https://kubevirt.io/user-guide/storage/disks_and_volumes/)。

## 4. 前置检查

### 4.1 节点虚拟化能力

只在候选节点执行以下只读检查：

```bash
# Intel 通常出现 vmx，AMD 通常出现 svm，结果应大于 0
grep -Ec '(vmx|svm)' /proc/cpuinfo

ls -l /dev/kvm /dev/vhost-net /dev/net/tun
lsmod | grep -E 'kvm|vhost'
```

还要确认：

- BIOS/UEFI 已开启 VT-x/VT-d 或 AMD-V/AMD-Vi；
- 节点不是禁止嵌套虚拟化的虚拟机，或者上层已经正确开放 nested virtualization；
- Kubernetes、containerd/CRI-O 与目标 KubeVirt 版本在支持范围内；
- CNI、DNS 和节点时间同步正常；
- Pod Security、SELinux 或 AppArmor 不会拦截 KubeVirt 所需权限。

安装前应查看 [KubeVirt releases](https://github.com/kubevirt/kubevirt/releases) 和对应版本的支持信息，不要把本文实验版本当成长期固定版本。

### 4.2 本地 StorageClass

```bash
kubectl --context <context> get storageclass
kubectl --context <context> get storageclass <local-storage-class> -o yaml
```

本地盘实验优先选择：

- `volumeBindingMode: WaitForFirstConsumer`，等 VM 调度决策后再创建卷；
- 回收策略为 `Retain`，避免删除 PVC 后立即回收底层数据；
- CSI 能通过 PV `nodeAffinity` 把卷固定到实际节点；
- 已有容量、磁盘健康和卷使用率监控。

`Immediate` 模式可能先把卷创建在另一个节点，随后 VM 因节点选择与卷亲和性冲突而一直 Pending。

## 5. 将虚拟机限制到一个节点

先给实验节点增加专用标签：

```bash
kubectl --context <context> label node <vm-node> \
  kubevirt.io/test-host=true --overwrite
```

安装 KubeVirt 后，在 KubeVirt CR 中配置两层限制：

```yaml
apiVersion: kubevirt.io/v1
kind: KubeVirt
metadata:
  name: kubevirt
  namespace: kubevirt
spec:
  workloads:
    nodePlacement:
      nodeSelector:
        kubevirt.io/test-host: "true"
  configuration:
    developerConfiguration:
      nodeSelectors:
        kubevirt.io/test-host: "true"
```

其中：

- `workloads.nodePlacement` 限制 `virt-handler` 等节点侧工作负载；
- `developerConfiguration.nodeSelectors` 为 VMI 增加默认节点选择；
- 每个实验 VM 仍建议显式写同一个 `nodeSelector`，让意图可以直接从资源清单中看到；
- `virt-api`、`virt-controller` 和 Operator 属于控制面，可以运行在其他合适节点，真正的 VMI/`virt-launcher` 仍被限制在实验节点。

验证时不要只看 VM 状态，还要看实际 Pod 所在节点：

```bash
kubectl --context <context> -n kubevirt get pods -o wide
kubectl --context <context> -n <vm-namespace> get pods -o wide
```

VM 和普通 Pod 可以同时运行在同一个节点。KubeVirt 的 VM 最终也是由 `virt-launcher` Pod 承载，仍参与 Kubernetes 调度和资源核算。生产上若担心相互争抢，应增加 ResourceQuota、PriorityClass、CPU Manager、Topology Manager、污点和专用节点池，而不是假设 VM 会天然隔离普通 Pod。

## 6. 安装 KubeVirt 与 CDI

### 6.1 KubeVirt 1.7 与 1.9：为什么控制面 Pod 变多了

KubeVirt 1.7 和 1.9 的核心架构没有改变。常驻的核心组件仍然是：

| 组件 | 部署方式 | 职责 |
| --- | --- | --- |
| `virt-operator` | Deployment，通常两个副本 | 安装、升级并持续协调 KubeVirt 控制面 |
| `virt-api` | Deployment，通常两个副本 | 提供 VM/VMI 子资源、准入和 Console/VNC 等 API |
| `virt-controller` | Deployment，通常两个副本 | 协调 VM、VMI、迁移、快照和相关 Pod |
| `virt-handler` | DaemonSet，每个可虚拟化节点一个 | 在节点侧管理 libvirt/QEMU 和 VMI 生命周期 |
| `virt-exportproxy` | Deployment，通常两个副本 | 为 VM、快照和 PVC 导出提供稳定入口 |

`virt-launcher` 不属于常驻控制面。每个运行中的 VMI 都会创建自己的 `virt-launcher` Pod；停止或删除 VMI 后，该 Pod 也会消失。类似地，真正读取卷数据的 `virt-exportserver` 只会在执行导出任务时按需创建。排查资源占用时，应把“常驻控制面”和“随 VM/任务创建的工作负载”分开统计。

1.9 默认安装后最显眼的变化，是多出以下两个常驻 Pod：

- `virt-template-apiserver`：提供原生 `VirtualMachineTemplate` 相关 API；
- `virt-template-controller`：协调模板、模板请求及其关联资源。

原生 `VirtualMachineTemplate` 在 1.8 作为 Alpha 功能引入，需要显式开启；到了 1.9，它升级为 Beta 并默认开启，因此 Operator 会自动部署这两个 `virt-template` 组件。它可以把网络、卷、DataVolume 等集群资源和参数一起纳入可复用 VM 蓝图，与主要复用 CPU、内存和设备偏好的 Instancetype/Preference 是互补关系。参见 [VirtualMachine Templates](https://kubevirt.io/user-guide/user_workloads/vm_templates/)。

不要用 KubeVirt 主版本号判断这两个镜像是否“混装”。例如 KubeVirt `v1.9.0` 固定的是 `virt-template-apiserver:v0.2.2` 和 `virt-template-controller:v0.2.2`；`v0.2.2` 是独立 `virt-template` 组件自己的版本。应让 `virt-operator` 管理这组依赖，不要为了让版本字符串看起来一致而手动替换镜像。

下面是 1.7 与 1.9 的主要运维差异：

| 维度 | KubeVirt 1.7 | KubeVirt 1.9 | 实际影响 |
| --- | --- | --- | --- |
| Kubernetes 基线 | 面向 Kubernetes 1.34，并支持此前两个小版本 | 面向 Kubernetes 1.36，并支持此前两个小版本 | Kubernetes 1.36/K3s 1.36 应选择 1.9，不应为了减少 Pod 回退到 1.7 |
| 核心控制面 | Operator、API、Controller、Handler | 与 1.7 相同 | VM 的基本调度和运行路径没有被替换 |
| 原生 VM Template | 不属于默认控制面 | Beta，默认启用 | 通常会额外看到一个 apiserver 和一个 controller Pod |
| VM Export | 已有 `virt-exportproxy`，它并非 1.9 新组件 | VMExport 升为 GA，并能配合功能门导出 OCI、导出 VM Template | 不要把 exportproxy 误判成版本膨胀带来的新进程 |
| Beta 功能门 | 默认关闭，需要加入 `featureGates` 显式启用 | 全部 Beta 功能默认开启，使用 `disabledFeatureGates` 逐项退出 | 从 1.7 升级前必须审计默认值变化，Alpha 功能仍保持默认关闭 |
| 面向 AI/异构节点的能力 | 已支持通过 DRA 描述 GPU 和 HostDevice | 增加 GPU UUID 与 VMI 关联指标、单设备 vGPU 热迁移等能力；Grace/IOMMUFD 等仍受架构、内核和功能门约束 | “API 已支持”不等于节点硬件、IOMMU、驱动和迁移存储已经满足条件 |

版本日期、Kubernetes 支持范围和完整变更以 [KubeVirt release notes](https://kubevirt.io/user-guide/release_notes/) 与 [Kubernetes support matrix](https://github.com/kubevirt/sig-release/blob/main/releases/k8s-support-matrix.md) 为准。1.9 默认启用 Beta 功能的背景和从 1.7 跨版本升级的注意事项，参见官方说明 [Beta Features Enabled by Default in KubeVirt v1.9](https://kubevirt.io/2026/Beta-Features-On-By-Default-In-v1-9.html)。

可以直接观察当前版本部署了哪些常驻组件：

```bash
kubectl --context <context> -n kubevirt get deployment,daemonset
kubectl --context <context> -n kubevirt get pods -o wide
kubectl --context <context> get crd | grep -E 'template.kubevirt.io|kubevirt.io'
```

如果平台完全不使用原生 VM Template，可以显式关闭模板组件以减少两个常驻 Pod。生产环境应先确认没有模板对象和调用方，再修改 KubeVirt CR：

```yaml
apiVersion: kubevirt.io/v1
kind: KubeVirt
metadata:
  name: kubevirt
  namespace: kubevirt
spec:
  configuration:
    virtTemplateDeployment:
      enabled: false
```

不建议仅仅为了减少组件数量而选择不支持当前 Kubernetes 版本的旧 KubeVirt。对于 1.9，更重要的是在上线前审计 [feature gate report](https://github.com/kubevirt/kubevirt/releases/tag/v1.9.0)，明确哪些 Beta 功能应保留默认开启、哪些应通过 `disabledFeatureGates` 退出。

### 6.2 固定版本并安装

固定经过兼容性验证的版本，不要在生产清单中使用浮动地址：

```bash
export KUBEVIRT_VERSION='<validated-version>'

kubectl --context <context> apply -f \
  "https://github.com/kubevirt/kubevirt/releases/download/${KUBEVIRT_VERSION}/kubevirt-operator.yaml"
kubectl --context <context> apply -f \
  "https://github.com/kubevirt/kubevirt/releases/download/${KUBEVIRT_VERSION}/kubevirt-cr.yaml"

kubectl --context <context> -n kubevirt wait kubevirt kubevirt \
  --for=condition=Available --timeout=10m
```

安装匹配的 CDI：

```bash
export CDI_VERSION='<validated-version>'

kubectl --context <context> apply -f \
  "https://github.com/kubevirt/containerized-data-importer/releases/download/${CDI_VERSION}/cdi-operator.yaml"
kubectl --context <context> apply -f \
  "https://github.com/kubevirt/containerized-data-importer/releases/download/${CDI_VERSION}/cdi-cr.yaml"

kubectl --context <context> -n cdi get pods
```

CDI 与后端存储解耦：它负责导入、上传、克隆或初始化 DataVolume，底层既可以是 Ceph RBD，也可以是本地 LVM。没有 Ceph 并不妨碍本实验创建空白持久盘。

## 7. 先用 CirrOS 验证 KVM 和 Console

桌面系统涉及存储、图形和 WebSocket，直接排障会把问题混在一起。先运行一个极小的 CirrOS VM，验证 KVM、调度和串口控制台：

```yaml
apiVersion: kubevirt.io/v1
kind: VirtualMachine
metadata:
  name: cirros-smoke
  namespace: kubevirt-lab
spec:
  runStrategy: Always
  template:
    metadata:
      labels:
        kubevirt.io/domain: cirros-smoke
    spec:
      nodeSelector:
        kubevirt.io/test-host: "true"
      domain:
        resources:
          requests:
            memory: 256Mi
        devices:
          disks:
            - name: root
              disk:
                bus: virtio
      volumes:
        - name: root
          containerDisk:
            image: quay.io/kubevirt/cirros-container-disk-demo:<matching-tag>
```

```bash
kubectl --context <context> create namespace kubevirt-lab
kubectl --context <context> apply -f cirros-smoke.yaml
kubectl --context <context> -n kubevirt-lab get vm,vmi,pod -o wide

virtctl --context <context> console -n kubevirt-lab cirros-smoke
```

退出 `virtctl console` 使用 **Ctrl+]**。这是控制字符：在英文输入法下按住 Control 再按 `]`，不是输入字符串 `Ctrl+]`。如果终端客户端仍无法退出，结束本地 `virtctl` 进程即可；这只断开控制台，不会关闭 VM。

## 8. 创建本地持久盘

下面创建一个 40 GiB 空白 DataVolume。8 GiB 足以验证 Tiny Core，但 Ubuntu、Conda、模型缓存和 IDE 插件很快会写满，正式工作站建议从 80–200 GiB 起步，并按团队数据量设置配额。

```yaml
apiVersion: cdi.kubevirt.io/v1beta1
kind: DataVolume
metadata:
  name: desktop-root
  namespace: kubevirt-lab
spec:
  source:
    blank: {}
  storage:
    storageClassName: <local-storage-class>
    accessModes:
      - ReadWriteOnce
    resources:
      requests:
        storage: 40Gi
    volumeMode: Filesystem
```

```bash
kubectl --context <context> apply -f desktop-root.yaml
kubectl --context <context> -n kubevirt-lab get dv,pvc
kubectl --context <context> get pv -o wide
```

DataVolume 在没有消费者时保持 `WaitForFirstConsumer` 是正常现象。创建带目标节点选择器的 VM 后，调度器才会触发卷创建。绑定后检查 PV 的 `nodeAffinity` 是否指向 `<vm-node>`。

## 9. 用 Tiny Core 验证桌面

从 [Tiny Core Linux 下载页](http://www.tinycorelinux.net/downloads.html)获取 ISO，并校验官网提供的散列。把 ISO 封装成 KubeVirt `containerDisk`：

```dockerfile
FROM scratch
ADD --chown=107:107 TinyCore-current.iso /disk/disk.img
```

```bash
docker build -t <registry>/lab/tinycore-container-disk:<tag> .
docker push <registry>/lab/tinycore-container-disk:<tag>
```

这里的 `<registry>` 是实验环境能够访问的 OCI Registry。生产中应固定镜像 digest、生成 SBOM 并完成漏洞扫描。

创建桌面 VM：

```yaml
apiVersion: kubevirt.io/v1
kind: VirtualMachine
metadata:
  name: tinycore-desktop
  namespace: kubevirt-lab
spec:
  runStrategy: Always
  template:
    metadata:
      labels:
        kubevirt.io/domain: tinycore-desktop
    spec:
      nodeSelector:
        kubevirt.io/test-host: "true"
      domain:
        cpu:
          cores: 1
        resources:
          requests:
            memory: 1Gi
        devices:
          inputs:
            - name: tablet
              type: tablet
              bus: usb
          disks:
            - name: root
              bootOrder: 1
              disk:
                bus: virtio
            - name: installer
              bootOrder: 2
              cdrom:
                bus: sata
      networks:
        - name: default
          pod: {}
      volumes:
        - name: root
          dataVolume:
            name: desktop-root
        - name: installer
          containerDisk:
            image: <registry>/lab/tinycore-container-disk:<tag>
```

第一次启动时，空白根盘没有操作系统，固件会继续从 ISO 启动。此时看到桌面只说明图形链路已经成功，**并不代表系统状态已经写入持久盘**。必须在 guest 内运行安装程序，把系统写到 `desktop-root`，随后移除 ISO 或调整启动顺序。若只运行 Live ISO，重启后操作系统层的修改仍会丢失。

## 10. 浏览器访问：最小权限 noVNC 代理

`virtctl vnc` 默认面向本地客户端。为了从浏览器访问，可以构建一个只包含匹配版本 `virtctl`、noVNC 和 websockify 的小型代理镜像：

```text
浏览器 /vnc.html
  → websockify :6080
  → virtctl vnc --proxy-only 127.0.0.1:5900
  → Kubernetes VMI VNC subresource
```

代理的启动逻辑应具备两个特征：

1. `virtctl vnc --proxy-only` 退出后循环重启，以便浏览器断线后能够再次连接；
2. 不要使用 `nc -z 127.0.0.1 5900` 探测 VNC 端口。

第二点非常关键。`virtctl` 的 proxy-only 模式一次只服务一个 VNC 连接，`nc -z` 本身就会消耗这次连接，导致真正的 noVNC 随后收到 `Connection refused`。健康检查应探测 websockify 的 6080 监听端口，而不是连接 5900。

代理 ServiceAccount 只需要当前命名空间内的 VMI 读取与 VNC 子资源权限：

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: tinycore-novnc
  namespace: kubevirt-lab
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: tinycore-novnc
  namespace: kubevirt-lab
rules:
  - apiGroups: ["kubevirt.io"]
    resources: ["virtualmachineinstances"]
    verbs: ["get"]
  - apiGroups: ["subresources.kubevirt.io"]
    resources: ["virtualmachineinstances/vnc"]
    verbs: ["get"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: tinycore-novnc
  namespace: kubevirt-lab
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: tinycore-novnc
subjects:
  - kind: ServiceAccount
    name: tinycore-novnc
    namespace: kubevirt-lab
```

不要在 YAML 或 Git 中保存实际密码。先生成随机密码，再创建 Secret：

```bash
NOVNC_PASSWORD="$(openssl rand -hex 16)"

kubectl --context <context> -n kubevirt-lab create secret generic tinycore-novnc-auth \
  --from-literal=username=vmuser \
  --from-literal=password="${NOVNC_PASSWORD}"

printf 'noVNC user: vmuser\nnoVNC password: %s\n' "${NOVNC_PASSWORD}"
```

代理 Deployment 的关键配置如下：

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: tinycore-novnc
  namespace: kubevirt-lab
spec:
  replicas: 1
  strategy:
    type: Recreate
  selector:
    matchLabels:
      app: tinycore-novnc
  template:
    metadata:
      labels:
        app: tinycore-novnc
    spec:
      serviceAccountName: tinycore-novnc
      hostNetwork: true
      dnsPolicy: ClusterFirstWithHostNet
      nodeSelector:
        kubevirt.io/test-host: "true"
      containers:
        - name: proxy
          image: <registry>/lab/kubevirt-novnc-proxy:<tag>
          env:
            - name: VM_NAMESPACE
              value: kubevirt-lab
            - name: VM_NAME
              value: tinycore-desktop
            - name: NOVNC_USERNAME
              valueFrom:
                secretKeyRef:
                  name: tinycore-novnc-auth
                  key: username
            - name: NOVNC_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: tinycore-novnc-auth
                  key: password
          ports:
            - name: http
              containerPort: 6080
              hostPort: 6080
          readinessProbe:
            tcpSocket:
              port: http
```

代理入口脚本的核心命令可以写成：

```bash
while true; do
  virtctl vnc --proxy-only --address=127.0.0.1 --port=5900 \
    --namespace="${VM_NAMESPACE}" "${VM_NAME}"
  sleep 1
done &

websockify --web=/usr/share/novnc \
  --web-auth --auth-plugin=BasicHTTPAuth \
  --auth-source="${NOVNC_USERNAME}:${NOVNC_PASSWORD}" \
  0.0.0.0:6080 127.0.0.1:5900
```

`hostNetwork` 使办公网可以直接访问：

```text
http://<vm-node-ip>:6080/vnc.html?autoconnect=1&resize=scale
```

这里不创建 NodePort。因为同一节点的固定 6080 端口不能同时被旧、新两个 Pod 占用，所以 Deployment 必须使用 `Recreate`；默认 `RollingUpdate` 可能让更新永久卡住。readiness 使用 TCP 探针，不能使用未携带凭据的 HTTP GET，否则 Basic Auth 返回 401，Pod 会一直显示未就绪。

Basic Auth 只适合受控网络 PoC，而且明文 HTTP 无法保护密码。生产环境至少要改成 HTTPS，并通过 Ingress/Gateway 接入 OIDC、短期授权、审计和网络策略。防火墙只应允许办公网 CIDR 访问该节点端口。

## 11. 怎样验证链路真的工作

### 11.1 VM、调度和存储

```bash
kubectl --context <context> -n kubevirt-lab get vm,vmi,pod -o wide
kubectl --context <context> -n kubevirt-lab get dv,pvc
kubectl --context <context> get pv <pv-name> -o yaml
```

验收点：

- VM 和 VMI 为 Running/Ready；
- `virt-launcher` 位于 `<vm-node>`；
- DataVolume 成功，PVC 为 Bound；
- PV `nodeAffinity` 与 VM 节点一致；
- VMI condition 中本地盘导致 `LiveMigratable=False` 是预期结果。

### 11.2 noVNC

```bash
kubectl --context <context> -n kubevirt-lab get deploy,pod -l app=tinycore-novnc -o wide
kubectl --context <context> -n kubevirt-lab logs deploy/tinycore-novnc

curl -u 'vmuser:<password>' -I 'http://<vm-node-ip>:6080/vnc.html'
```

页面请求应返回 200，浏览器 WebSocket 应完成 101 Switching Protocols。若 HTML 能加载但顶部显示“无法连接到服务器”，应检查代理日志和 5900 连接生命周期，而不是先怀疑 guest 密码。

## 12. 常见故障

| 现象 | 常见原因 | 处理 |
| --- | --- | --- |
| VMI 一直 Pending | 节点没有 KVM、标签不匹配、资源不足 | 检查 VMI Events、`virt-handler` 和节点设备 |
| DataVolume/PVC Pending | `WaitForFirstConsumer` 尚无 VM 消费者 | 创建 VM 后再观察；检查 StorageClass 和调度事件 |
| 卷与 VM 节点冲突 | StorageClass 使用 `Immediate` 或 PV 已绑定别处 | 使用 WFFC；重建实验卷时先确认数据处置 |
| 浏览器拒绝连接 6080 | 代理 Pod 未运行、hostPort 未监听或防火墙拦截 | 检查 Pod、节点监听和办公网 ACL |
| noVNC 页面显示无法连接 | `virtctl` 已退出，或健康检查占用了单连接 VNC 代理 | 移除对 5900 的 `nc -z`；循环重启 `virtctl` |
| 代理 Pod 一直未就绪 | HTTP readiness 被 Basic Auth 返回 401 | 改用 6080 TCP readiness |
| Deployment 更新卡住 | RollingUpdate 时新旧 Pod 争抢 hostPort | 使用 `strategy.type: Recreate` |
| Console 无法退出 | 没有发送正确控制字符 | 英文输入法按 Ctrl+]，或结束本地客户端进程 |
| VM 重启后修改丢失 | 仍从 Live ISO 启动，系统没有装进 DataVolume | 完成 guest 安装并从持久根盘启动 |

## 13. Jupyter Notebook 与 code-server 镜像怎么选

这里要先区分“容器应用镜像”和“VM 系统镜像”。

### 13.1 只运行容器 Notebook

| 场景 | 推荐起点 | 说明 |
| --- | --- | --- |
| 最小 JupyterLab | `quay.io/jupyter/base-notebook:<date-or-sha>` | 体积较小，适合从项目 Lockfile 构建派生镜像 |
| 常用 Python 数据科学 | `quay.io/jupyter/scipy-notebook:<date-or-sha>` | NumPy、pandas、SciPy 等常用栈，适合作为多数 CPU Notebook 默认值 |
| PyTorch + NVIDIA GPU | `quay.io/jupyter/pytorch-notebook:cuda12-<pinned-tag>` | 官方 Docker Stacks 的 CUDA 变体，使用前核对驱动与 CUDA 兼容性 |
| NVIDIA 优化 PyTorch | `nvcr.io/nvidia/pytorch:<pinned-release>-py3` | 适合重视 NVIDIA 优化库的 GPU 环境，镜像包含 JupyterLab，但启动和安全配置需要平台明确管理 |

Jupyter Docker Stacks 已只把新镜像发布到 Quay.io，JupyterLab 是默认前端，并建议为可复现性固定日期或 Git SHA tag。不要继续把 Docker Hub 的旧 `jupyter/*` 当作更新来源。参见 [Jupyter Docker Stacks](https://jupyter-docker-stacks.readthedocs.io/en/latest/)和[镜像选择说明](https://jupyter-docker-stacks.readthedocs.io/en/latest/using/selecting.html)。NVIDIA 镜像说明参见 [NGC PyTorch](https://catalog.ngc.nvidia.com/orgs/nvidia/containers/pytorch)。

### 13.2 只运行容器 code-server

使用官方镜像：

```text
codercom/code-server:<pinned-version>
```

官方镜像支持 amd64 和 arm64。至少持久化 `/home/coder/.local`、`/home/coder/.config` 和项目目录，并通过 HTTPS 反向代理暴露；code-server 依赖 WebSocket。参考 [code-server 安装文档](https://coder.com/docs/code-server/install)和[安全访问说明](https://coder.com/docs/code-server/guide)。

不要把 `ghcr.io/coder/coder` 与 `codercom/code-server` 混为一谈：前者是多用户开发环境平台 Coder 的控制服务，后者才是浏览器中的 VS Code 服务。

### 13.3 同时需要 Jupyter 和 code-server，而且环境必须完整保留

本文场景的默认选择不是把两个服务硬塞进一个应用容器，而是：

```text
Ubuntu 24.04 LTS QCOW cloud image（或经过 GPU 兼容验证的 Ubuntu 22.04 LTS）
  → CDI 导入并克隆为每用户独立根盘
  → cloud-init 创建用户、SSH key 和初始配置
  → 在 VM 内安装 Miniforge/Micromamba、JupyterLab、code-server
  → systemd 分别管理两个服务
  → 完整 / 根盘由 DataVolume 持久化
```

这样用户后来通过 `apt`、`pip`、Conda、VS Code 扩展或任意脚本写入 `/home`、`/opt`、`/usr/local`、`/var` 的内容都会随 VM 根盘保存。code-server 官方 FAQ 也建议多租户场景为每位用户提供 VM，并明确提到 Kubernetes 上可用 KubeVirt 获得 VM 式体验。参考 [code-server FAQ](https://coder.com/docs/code-server/FAQ)。

镜像选择建议：

- CPU 开发环境默认用 Ubuntu 24.04 LTS QCOW cloud image；从 [Ubuntu 公开镜像](https://cloud-images.ubuntu.com/releases/noble/release/)选择发布版、校验 SHA256，再由 CDI 导入 DataVolume，不要在生产中跟随不断变化的 daily/current 文件；
- GPU 直通环境由 guest NVIDIA 驱动、CUDA Toolkit、框架版本共同决定，Ubuntu 22.04/24.04 二选一，以实际兼容矩阵为准；
- 黄金镜像只预装稳定的系统依赖、QEMU Guest Agent、安全补丁和平台 Agent；频繁变化的 Python 项目依赖仍用 `environment.yml`、`requirements.lock`、`uv.lock` 或容器保存；
- 为 Jupyter 和 code-server 使用不同端口、独立 systemd unit 和统一身份入口，不要关闭 token/密码后直接暴露到网络；
- 为黄金镜像记录来源 URL、SHA256、构建脚本、SBOM 和发布日期，并按周期重建，不要人工维护一个永不升级的“宠物镜像”。

如果只是标准化教学或短期实验，容器镜像 + PVC 更轻、更快；如果核心问题正是用户会在任意目录安装环境，持久 VM 根盘才真正覆盖问题边界。

## 14. VM 内网 DNS：为什么宿主机能访问，VM 却解析失败

KubeVirt VM 使用默认 Pod 网络和 `masquerade` 接口时，guest 并不会直接继承宿主机的 `/etc/resolv.conf`。典型解析链路是：

```text
guest 应用
  → systemd-resolved 或 guest resolver
  → KubeVirt DHCP 下发的 Kubernetes DNS Service IP
  → masquerade 网关，例如 10.0.2.1
  → kube-dns/CoreDNS ClusterIP
  → CoreDNS Pod
  → 企业 DNS 或公共上游 DNS
```

因此，“宿主机可以 `curl`，VM 不可以”不能直接归因于企业 DNS。宿主机可能直接查询企业 DNS，VM 却先依赖 Kubernetes Service VIP；两条路径中间还隔着 guest 网卡、KubeVirt NAT、`virt-launcher` 网络命名空间和 CNI Service 负载均衡。

### 14.1 一次真实故障的证据链

本次实验出现了以下现象，地址和域名已泛化：

| 检查位置 | 结果 | 说明 |
| --- | --- | --- |
| 宿主机查询 `<internal-fqdn>` | 企业 DNS 返回内网 IP | 企业 DNS 记录正常 |
| 宿主机 `curl http://<internal-fqdn>` | 收到 HTTP 403 | 网络已经到达目标，403 属于应用鉴权，不是 DNS 或连接失败 |
| VM `/etc/resolv.conf` | 指向 `127.0.0.53` | 这是 systemd-resolved 的本地 stub，不是真正的上游 DNS |
| VM `resolvectl status` | 上游为 `<kube-dns-cluster-ip>` | KubeVirt DHCP 把 Pod 的 ClusterFirst DNS 传给 guest |
| VM 到 `<kube-dns-cluster-ip>:53` | TCP/UDP 超时 | 故障点位于 VM 到 Kubernetes Service VIP 的路径 |
| VM 到两个 CoreDNS Pod IP | 端口可达 | CoreDNS 进程和 Pod 网络并未整体中断 |
| VM 到两个企业 DNS IP | 端口可达 | guest 的默认路由与企业 DNS ACL 正常 |
| VM 临时改用企业 DNS | 解析成功，HTTP 403 | 进一步证明问题不是域名记录，而是 kube-dns ClusterIP 路径 |

先在宿主机确认真实上游：

```bash
cat /etc/resolv.conf
getent hosts <internal-fqdn>
curl -I --connect-timeout 5 "http://<internal-fqdn>/"
```

再在 guest 内检查：

```bash
cat /etc/resolv.conf
resolvectl status
ip route

getent hosts <internal-fqdn>
timeout 3 bash -c '</dev/tcp/<kube-dns-cluster-ip>/53'
timeout 3 bash -c '</dev/tcp/<corp-dns-1>/53'
timeout 3 bash -c '</dev/tcp/<corp-dns-2>/53'
```

最后查看集群 DNS 和 CNI，不要只在 guest 中反复改 `/etc/hosts`：

```bash
kubectl -n kube-system get service kube-dns -o wide
kubectl -n kube-system get pod -l k8s-app=kube-dns -o wide
kubectl -n kube-system get configmap coredns -o yaml
kubectl -n kube-system get configmap cilium-config -o yaml
```

如果 CoreDNS 使用 `forward . /etc/resolv.conf`，而 CoreDNS Pod 又采用 `dnsPolicy: Default`，非 `cluster.local` 查询通常会继续交给节点的企业 DNS。此时不必为每个内网域名向 CoreDNS `hosts` 插件增加静态记录；先修复 VM 到 DNS 服务的路径。

### 14.2 单台 VM：直接指定企业 DNS

对只需要访问企业服务、不要求解析 Kubernetes Service 名称的 VM，最小变更是在 VM 模板中显式设置 DNS：

```yaml
apiVersion: kubevirt.io/v1
kind: VirtualMachine
metadata:
  name: ai-workstation
spec:
  template:
    spec:
      dnsPolicy: None
      dnsConfig:
        nameservers:
          - <corp-dns-1>
          - <corp-dns-2>
        searches:
          - <corp-search-domain-1>
          - <corp-search-domain-2>
        options:
          - name: timeout
            value: "1"
          - name: attempts
            value: "2"
```

`dnsPolicy: None` 很重要。仅在 `ClusterFirst` 下追加 `dnsConfig.nameservers`，不可达的 kube-dns 仍可能排在最前面，让每次查询先等待超时。VM 模板修改只会作用于新建的 `virt-launcher`/VMI，已有 VMI 需要安排重启。

也可以在 Ubuntu guest 内覆盖 DHCP DNS。下面是持久化示例：

```yaml
# /etc/netplan/50-cloud-init.yaml
network:
  version: 2
  ethernets:
    enp1s0:
      dhcp4: true
      dhcp4-overrides:
        use-dns: false
      nameservers:
        addresses:
          - <corp-dns-1>
          - <corp-dns-2>
        search:
          - <corp-search-domain-1>
          - <corp-search-domain-2>
```

```bash
netplan generate
netplan apply
resolvectl flush-caches
getent hosts <internal-fqdn>
```

VM 模板配置更适合平台统一管理；guest Netplan 适合验证或保留工作站自己的 DNS 策略。不要直接编辑由 systemd-resolved 管理的 `/etc/resolv.conf`，它通常是符号链接，重启或 DHCP 续租后会被覆盖。

直接使用企业 DNS 的代价是无法解析 `*.svc.cluster.local`。如果 VM 同时需要企业域名和 Kubernetes Service 域名，应优先修复 CNI Service 路径或使用节点本地 DNS，而不是把 CoreDNS Pod IP 固定在模板里；Pod IP 会随滚动升级和故障恢复变化。

### 14.3 集群根治：检查 Cilium kube-proxy replacement

本次故障集群没有运行 kube-proxy，而由 Cilium eBPF 处理 ClusterIP：

```yaml
kube-proxy-replacement: "true"
```

KubeVirt guest 的连接来自 QEMU/tap，经 `virt-launcher` 的 NAT 后进入 CNI。它不像普通 Pod 进程那样直接从 Pod cgroup 发起 socket 调用，因此可能无法命中以 socket hook 为主的 Service 转换路径。Cilium 官方把 KubeVirt、Kata Containers 和 gVisor 明确列为需要考虑 socket LB bypass 的工作负载，并给出以下配置方向：

```yaml
socketLB:
  hostNamespaceOnly: true
```

它让非宿主机命名空间绕过 socket-level rewrite，并在 tc 层处理原始 ClusterIP。参见 [Cilium kube-proxy replacement：Socket LB bypass](https://docs.cilium.io/en/stable/network/kubernetes/kubeproxy-free/#socket-loadbalancer-bypass-in-pod-namespace)。

如果抓包和 Cilium monitor 表明 guest 流量被识别为集群外流量，还要评估：

```yaml
bpf:
  lbExternalClusterIP: true
```

这个开关会扩大 ClusterIP 的可访问边界，不能仅为修复 DNS 就直接在生产集群开启。应先核对 NetworkPolicy、安全模型和所有节点的 Cilium 配置，再在测试节点验证。推荐顺序是：

1. 记录 Cilium 版本、Helm values、路由模式和 kube-proxy replacement 状态；
2. 用 `cilium-dbg monitor` 或 Hubble 观察 guest 到 kube-dns ClusterIP 的丢包位置；
3. 优先验证 `socketLB.hostNamespaceOnly=true`；
4. 只有确认流量被视为 external 时，才评估 `bpf.lbExternalClusterIP=true`；
5. 同时回归普通 Pod DNS、ClusterIP、NodePort、NetworkPolicy 和 VM 网络；
6. 验证通过后再滚动更新 Cilium，保留回滚 values。

### 14.4 多 VM 平台：NodeLocal DNSCache

当平台要运行大量 Notebook VM，更稳定的结构是给每个节点部署 NodeLocal DNSCache，并让 VM 查询一个稳定的节点本地地址：

```text
KubeVirt VM
  → 节点本地 DNS，例如 <node-local-dns-ip>
      ├─ cluster.local → CoreDNS
      └─ 其他域名 → 企业 DNS
```

它可以减少跨节点 DNS 请求、避开 guest 直接依赖 kube-dns ClusterIP，并同时保留 Kubernetes Service 与企业内网域名解析。上线前仍要验证 KubeVirt masquerade guest 能访问选定的节点本地地址，以及缓存失败、CoreDNS 故障和企业 DNS 切换时的行为。参考 [Kubernetes NodeLocal DNSCache](https://kubernetes.io/docs/tasks/administer-cluster/nodelocaldns/)。

建议把 DNS 纳入黄金镜像与 VM 平台验收，而不是等用户安装 Python 包失败后才处理：

- FQDN、短域名、企业搜索域和 `*.svc.cluster.local` 分别测试；
- UDP 53 与 TCP 53 都要测试，避免大响应或截断回退到 TCP 时失败；
- 验证 DNS 超时和重试值，避免不可达 nameserver 让 `apt`、`pip`、Conda 长时间假死；
- 区分 NXDOMAIN、超时、连接拒绝和 HTTP 401/403，它们属于完全不同的故障层；
- 记录 DNS 由 VM 模板、guest Netplan、NodeLocal DNS 还是 CoreDNS 管理，避免多处配置互相覆盖。

## 15. 固定 IP 与稳定访问入口

讨论 KubeVirt 固定 IP 之前，必须先确认要固定的是哪一层。默认 Pod 网络配合 `masquerade` 时，guest、`virt-launcher` Pod 和办公网入口拥有不同的地址语义：

| 层级 | 典型地址 | 谁分配 | 生命周期与可达性 |
| --- | --- | --- | --- |
| guest 私网 IP | `10.0.2.2` | KubeVirt 内置 DHCP | 位于每个 VMI 独立的 NAT 网络中；不同 VM 可以重复，办公网不能把它当作唯一可路由地址 |
| VMI/`virt-launcher` Pod IP | `<pod-cidr-address>` | 集群主 CNI | 集群内可达性取决于 CNI；VMI 重建或迁移后可能变化，不应写入用户书签和外部 DNS |
| Kubernetes Service IP | `<cluster-ip>` | Kubernetes | Service 存续期间稳定，但通常只在集群网络内可达 |
| 办公网入口 IP/VIP | `<office-routable-vip>` | 企业网络、负载均衡或二层 IP 通告系统 | 面向用户的稳定入口，可绑定域名、TLS 和统一认证 |
| VM underlay IP | `<office-routable-vm-ip>` | 企业 DHCP、静态地址或 underlay IPAM | 直接配置在 guest 的第二张网卡上，表现最像传统虚拟机，但网络改造和治理成本最高 |

当前实验使用的是：

```text
办公网或集群客户端
  → VMI Pod IP / Kubernetes Service
  → virt-launcher 网络命名空间中的 NAT
  → guest 10.0.2.2
```

`10.0.2.2` 看起来很固定，却只是每台 VM 自己 NAT 空间里的私网地址。VMI 状态中看到的 `<pod-cidr-address>` 才是本次运行对应的 Pod IP，但它也不是长期身份。KubeVirt 官方建议 `masquerade` 工作负载通过 Kubernetes Service 暴露，因为 Service 可以在 VMI 硬重启或迁移导致 Pod IP 变化后继续选择新的实例。参见 [KubeVirt Interfaces and Networks](https://kubevirt.io/user-guide/network/interfaces_and_networks/)。

### 15.1 Notebook 首选固定域名，而不是固定 guest IP

JupyterLab 和 code-server 都是 HTTP/WebSocket 应用，适合使用一个固定 Gateway/Ingress VIP，再按域名转发到每台 VM 的 Service：

```text
user01.notebook.example.internal ─┐
user02.notebook.example.internal ─┼→ HTTPS Gateway/Ingress 固定 VIP
user03.notebook.example.internal ─┘        │
                                           ├→ Service/notebook-user01
                                           ├→ Service/notebook-user02
                                           └→ Service/notebook-user03
                                                    │
                                                    ▼
                                          动态 VMI Pod IP → guest
```

每台 VM 的 Service 只需要选择稳定的 domain 标签：

```yaml
apiVersion: v1
kind: Service
metadata:
  name: notebook-user01
spec:
  selector:
    kubevirt.io/domain: notebook-user01
  ports:
    - name: code
      port: 8080
      targetPort: 8080
    - name: jupyter
      port: 8888
      targetPort: 8888
```

Service 的 ClusterIP 不等于办公网 VIP。完整生产链路还需要 Gateway/Ingress Controller、企业负载均衡或 MetalLB 一类的地址通告机制，把一个办公网可路由地址交给入口。MetalLB 分配的是 Service VIP，并不会把该 IP 配置到 guest 网卡，概念说明参见 [MetalLB Concepts](https://metallb.io/concepts/)。

这个方案的优点是：

- VM 重启、重建和未来迁移时不要求保持 VMI Pod IP；
- 多个用户共享少量 VIP，不需要为每台 Notebook 消耗办公网地址；
- TLS、OIDC、访问日志、限流和 WebSocket 可以统一治理；
- 用户只记域名，平台可以在后台替换 VM、Service 或存储实现。

SSH 不是 HTTP，通常通过统一 SSH Bastion、TCP Gateway 或受控 LoadBalancer Service 暴露。不要为了让浏览器访问 Jupyter 而给每台 VM 都接入办公网二层网络。

### 15.2 真正需要 VM 固定 IP：Multus 双网卡

某些场景确实要求 guest 像传统虚拟机一样直接出现在办公网，例如旧软件按源 IP 授权、网络设备主动回连 VM、需要完整端口空间，或者运维工具只接受一机一 IP。此时可以保留默认 Pod 网络作为管理面，再通过 Multus 增加一张 underlay 网卡：

```text
VM eth0：Pod network + masquerade
  用途：Kubernetes Service、平台探测和默认管理链路

VM office0：Multus + bridge/SR-IOV/macvtap
  用途：办公网或业务 VLAN 中的可路由固定 IP
```

KubeVirt 的 `network` 声明连接到哪张逻辑网络，`interface` 声明该网络如何接入 guest，两者名称必须一一对应。一个精简的双网卡 VM 片段如下：

```yaml
spec:
  template:
    spec:
      domain:
        devices:
          interfaces:
            - name: default
              masquerade: {}
            - name: office
              bridge: {}
              macAddress: "02:00:00:00:01:01"
      networks:
        - name: default
          pod: {}
        - name: office
          multus:
            networkName: office-network
```

`office-network` 是一个 `NetworkAttachmentDefinition`，它通常引用 Linux Bridge、OVS、macvlan、macvtap 或 SR-IOV CNI。以 Linux Bridge 为例，宿主机必须先有接入目标 VLAN 的 `br-office`；Multus 只是调用对应 CNI，把 VMI Pod 中的第二张接口接到这座桥上，不会自动替管理员配置交换机、VLAN、网关和路由。

生产上更稳妥的固定地址方式是“固定 MAC + 企业 DHCP 保留地址”：

1. 平台为每台 VM 分配全局唯一、不可随重启变化的 MAC；
2. 网络/IPAM 系统根据该 MAC 保留一个办公网 IP；
3. guest 第二张网卡使用 DHCP；
4. CMDB 同时记录用户、VM、MAC、IP、VLAN 和回收状态。

Ubuntu cloud-init 可以按 MAC 为第二张网卡固定名称并启用 DHCP：

```yaml
networkData: |
  version: 2
  ethernets:
    office0:
      match:
        macaddress: "02:00:00:00:01:01"
      set-name: office0
      dhcp4: true
```

如果企业网络没有 DHCP，也可以在 `networkData` 中写预留的静态地址、前缀、路由和 DNS。但必须先由 IPAM/CMDB 完成唯一性校验，不能让用户在 guest 中随意挑选地址。动态地址池插件能避免并发分配冲突，却不天然等于“删除 VMI 后仍拿到同一个 IP”；使用 Whereabouts、Spiderpool、Kube-OVN 或云厂商 IPAM 时，要额外确认其固定地址、保留和回收语义。

### 15.3 宿主机与网络侧前置条件

在单节点实验中给 VM 接入办公网之前，至少确认：

- 节点有独立业务网卡、Bond VLAN 子接口或经过评审的共享链路；
- `br-office`、OVS Bridge 或 SR-IOV VF 的配置能够在节点重启后自动恢复；
- 交换机 Trunk/Access VLAN、MTU、网关、DHCP Relay 和 ACL 已匹配；
- Multus 与对应 CNI 二进制已安装，`NetworkAttachmentDefinition` 能在目标 Namespace 使用；
- MAC/IP 地址由平台统一分配，具备冲突检测、审计和回收流程；
- 办公网到 VM 网段有双向路由，返回路径不会错误地走 masquerade 网卡；
- NetworkPolicy 主要约束 Pod 网络，underlay 流量是否受控要单独验证；
- 本地盘 VM 不能迁移到没有相同二层网络和本地卷的节点，节点故障边界没有因为固定 IP 而消失。

不要直接把承载 Kubernetes 管理流量的物理接口加入新 Bridge 后在线试错，这可能让节点立刻失联。优先使用专用网卡或 VLAN 子接口；修改前保存 NetworkManager/systemd-networkd 配置和带外恢复手段，先用一台测试 VM 验证 ARP、DHCP、DNS、MTU、路由和重启恢复。

### 15.4 三种方案怎么选

| 需求 | 推荐入口 | 是否需要每 VM 固定 IP |
| --- | --- | --- |
| 浏览器访问 JupyterLab/code-server | 固定域名 + HTTPS Gateway/Ingress + VM Service | 否 |
| 管理员 SSH 进入用户 VM | Bastion/TCP Gateway，或受控的 LoadBalancer Service | 通常不需要 |
| 用户从办公网 SSH，且必须保持传统一机一 IP | Multus 第二网卡 + 固定 MAC + DHCP 保留 | 是 |
| 旧系统主动连接 VM 任意端口 | Multus underlay IP，并配套 ACL/IPAM | 是 |
| 只要求服务入口地址固定 | LoadBalancer Service + 企业 LB/MetalLB | 固定的是 Service VIP，不是 guest IP |
| GPU/RDMA 高性能数据面 | 管理网保留 masquerade，数据面按需使用 Multus + SR-IOV | 数据面地址按网络方案治理 |

对多用户 Notebook 平台，默认选择应是“稳定域名和身份入口”，而不是“50 个永不变化的 Pod IP”。只有无法通过 Service/Gateway 表达的网络需求，才给个别 VM 增加 Multus underlay 网卡。这样既保留 Kubernetes 的服务发现和生命周期能力，也不会过早把平台绑定到办公网 VLAN、地址容量和物理交换机配置。

## 16. KubeVirt 还有哪些适合工作站平台的能力

KubeVirt 提供的是 VM 生命周期和虚拟化能力，不会直接替平台判断“用户是否还在工作”。对多用户 Notebook 平台，比较实用的能力包括：

| 能力 | 解决什么问题 | 关键边界 |
| --- | --- | --- |
| `runStrategy` 与 start/stop/restart 子资源 | 声明 VM 应持续运行、失败重启、只运行一次、手动控制或保持关机 | 它只执行期望状态，不负责判断用户是否空闲 |
| VM Snapshot/Restore | 保存 VM 配置并协调 CSI 卷快照与恢复 | 数据卷能否快照取决于 CSI 与 `VolumeSnapshotClass`；在线一致性最好配合 QEMU Guest Agent |
| Live Migration | 节点维护时迁移正在运行的 VM | 本地盘、部分直通设备和网络绑定不可迁移；本文 Local LVM VM 不具备这一能力 |
| DataVolume、Clone 与 Export | 导入黄金镜像、创建用户盘、复制或导出 VM/PVC | 批量 Host-assisted Copy 会产生真实网络与磁盘 I/O，应限并发 |
| Instancetype 与 Preference | 把 4C16G、48C192G、GPU 工作站等规格和机器偏好标准化 | 规格变更是否可以在线生效取决于版本、LiveUpdate 与 guest 支持 |
| 磁盘和网卡热插拔 | 不关机增加数据盘或附加网络 | 需要对应 feature gate、CNI/CSI 能力和 guest 驱动；不等于所有设备都能热插拔 |
| QEMU Guest Agent | 上报 guest OS、接口、文件系统、登录用户等信息，并辅助一致性快照 | Agent 是观测与协作通道，不应把它当成完整的终端审计或唯一空闲信号 |
| 持久 TPM/UEFI 状态 | 支持需要持久固件变量或虚拟 TPM 的工作负载 | 需要后端状态 StorageClass，并增加备份与恢复对象 |
| VM Pool | 维护一组同构 VM，适合教学池、临时桌面池和预热实例 | 个人长期工作站更适合一人一 VM/PVC，避免池控制器误回收用户状态 |

这些能力应以集群实际版本和 feature gate 为准。不要因为最新文档出现了某个 API，就假设当前安装版本已经可用；上线前用 `kubectl api-resources`、`kubectl explain` 和测试 VM 验证。

### 16.1 多久不用自动关机：KubeVirt 提供动作，平台负责策略

KubeVirt 当前没有一个内置字段可以表达：

```yaml
idleTimeout: 2h
```

它提供的是可靠的生命周期原语。Controller 判定 VM 空闲后，可以调用 stop 子资源，或者把 VM 改成 `runStrategy: Halted`；再次访问时，再通过 start 子资源恢复为运行状态。KubeVirt 支持 `Always`、`RerunOnFailure`、`Once`、`Manual` 和 `Halted` 等运行策略，具体语义参见 [KubeVirt Run Strategies](https://kubevirt.io/user-guide/compute/run_strategies/)。

真正释放资源的停机链路是：

```text
空闲检测器确认超时
  → 给用户发送即将停机通知并进入宽限期
  → 再次确认没有活跃会话和后台任务
  → 调用 VM stop / 设置 runStrategy: Halted
  → guest 尽量优雅关机
  → VMI 与 virt-launcher Pod 删除
  → CPU、内存和临时网络资源释放
  → VirtualMachine、PVC 和用户完整根文件系统继续保留
```

不要用 `virtctl pause` 代替自动停机。Pause 会冻结 guest 的 vCPU 和 I/O，但 QEMU 进程与 VM 内存仍留在宿主机，不能解决多人共享节点的内存容量问题。KubeVirt 官方生命周期文档也明确说明暂停时 domain memory 继续分配，参见 [KubeVirt Lifecycle](https://kubevirt.io/user-guide/user_workloads/lifecycle/)。Memory Dump 同样只用于故障分析，并不是保存内存状态后释放资源的休眠机制。

### 16.2 空闲不能只看“网页多久没有请求”

Notebook 工作站可能在浏览器关闭后继续训练、下载数据、运行终端任务或编译代码。仅根据 Ingress 最后请求时间或 CPU 低利用率停机，都容易误伤。推荐综合以下信号：

| 信号 | 能发现什么 | 局限 |
| --- | --- | --- |
| Gateway/Jupyter 最后请求时间 | 浏览器是否仍在交互 | 发现不了 SSH、后台 Kernel 和 detached 任务 |
| Jupyter Session/Kernel 状态 | Notebook Kernel 是否繁忙、最后活动时间 | 看不到 code-server、系统进程和独立 Python 脚本 |
| code-server WebSocket/心跳 | IDE 是否在线 | 用户断网不代表后台任务可以终止 |
| SSH 登录与 PTY | 是否存在交互式终端 | `tmux`、`screen`、systemd user service 可能在退出后继续运行 |
| CPU、GPU、磁盘和网络利用率 | 是否存在持续计算或 I/O | 阈值过低会误判等待数据、睡眠或间歇运行的任务 |
| QEMU Guest Agent/平台 Agent | guest 登录用户、进程摘要和自定义心跳 | Agent 可能故障，不能把“无数据”解释成“空闲” |
| 用户显式租约 | 用户声明“今晚保持运行” | 必须设置最长时限、配额和审计，不能允许永久绕过回收 |

JupyterHub 已有 `jupyterhub-idle-culler`，可以根据 Hub 记录的用户活动停止单用户 Server，参见 [JupyterHub Idle Culler](https://jupyterhub.readthedocs.io/en/latest/tutorial/getting-started/services-basics.html)。但本文是一台 VM 内同时运行 JupyterLab、code-server、SSH 和任意后台进程，不能直接把“Jupyter Server 空闲”等同于“整台 VM 可以关机”。更合适的是让 Jupyter 活动成为平台 Controller 的一个输入，再结合 VM 级指标和保护租约做最终决策。

### 16.3 推荐的自动停机与按需唤醒流程

可以在 VM 上声明平台策略，而不是让 guest 自己永久掌握开关机权限：

```yaml
metadata:
  labels:
    workstation.aik8s.run/autostop: "enabled"
  annotations:
    workstation.aik8s.run/idle-timeout: "2h"
    workstation.aik8s.run/grace-period: "10m"
    workstation.aik8s.run/max-keep-running: "24h"
```

这些不是 KubeVirt 内置字段，而是自研 Workspace Controller 的示例约定。Controller 可以按下面的状态机工作：

```text
Running
  ├─ 有活动 → 更新 last-active，继续运行
  └─ 超过 idle-timeout
       → StoppingPending，页面与消息通知用户
       ├─ 宽限期内恢复活动 → Running
       └─ 宽限期结束且无保护租约
            → 调用 stop → Stopped

Stopped
  └─ 用户访问固定域名
       → Gateway 跳转到“工作站启动中”页面
       → Controller 调用 start
       → 等待 VMI Ready、SSH/Jupyter readiness 成功
       → 重新转发到用户工作站
```

建议的初始策略是：

- 普通开发工作站连续 2 小时无有效活动后进入停机宽限期；
- 停机前至少提前 10 分钟通知，并允许用户点击“继续运行”；
- 后台任务通过最长 24 小时的显式租约保护，超时后要求重新申请；
- 停机动作先请求 guest 优雅关机，超时后才由平台决定是否强制停止；
- 只有 PVC 已 Bound、根盘可恢复且应用服务可自动启动的 VM 才开启 autostop；
- 记录判定信号、停机原因、执行者和恢复耗时，方便解释误停与调优阈值。

如果 VM 使用 `runStrategy: Always`，guest 内执行 `shutdown` 后 KubeVirt 会把它再次拉起，因此不要只在 guest 里放一个 idle shutdown 脚本。由外部 Controller 调用 VM stop 最清晰；或者使用 `Manual`/`RerunOnFailure` 并明确其重启语义。对于当前 Notebook VM，可以让平台在开机时调用 start、空闲回收时调用 stop，根盘仍保留在独立 DataVolume/PVC 中。

### 16.4 推荐启用顺序

1. 先安装并验证 QEMU Guest Agent、Service readiness 和优雅关机；
2. 建立固定域名入口，让停止状态可以显示“启动中”而不是直接返回 502；
3. 只记录活动数据一周，不执行停机，用真实分布确定阈值；
4. 选择少量测试用户启用通知式 autostop，保留一键续租；
5. 验证停止后 VMI 消失、CPU/内存释放、PVC 保留，重新启动后环境和服务恢复；
6. 最后再推广到全部用户，并给训练、推理、教学和临时开发设置不同策略。

## 17. 从实验走向生产

| 实验做法 | 生产替换 |
| --- | --- |
| 单节点 Local LVM | Ceph RBD 等支持故障恢复的块存储 |
| Tiny Core Live ISO | 可审计、定期重建的 Ubuntu LTS 黄金镜像 |
| 节点地址 + hostNetwork:6080 | HTTPS Gateway/Ingress + OIDC + 每用户短期授权 |
| 一个静态 noVNC 账号 | 用户身份映射、细粒度授权、会话审计和凭据轮换 |
| 手工创建 VM | Workspace Portal/Operator 自动创建、停止、快照和回收 |
| `Retain` 本地 PV | CSI Snapshot、异地备份、恢复演练和生命周期策略 |
| CPU/内存尽力共享 | Quota、优先级、NUMA/CPU 拓扑和专用 GPU 节点池 |
| 直接使用 VMI Pod IP | 稳定域名 + Service + HTTPS Gateway；特殊场景再增加 Multus underlay 网卡 |

还需要明确三类生命周期：

1. **停止 VM**：删除 VMI，释放计算资源，但保留 VM 和根盘；
2. **重置环境**：从黄金镜像重新克隆根盘，必须提供快照或二次确认；
3. **删除用户**：经过保留期后删除 PVC/PV 和备份，不能与停止操作共用按钮或权限。

## 18. 验收清单

- [ ] 候选节点存在可用的 `/dev/kvm`，且 `virt-handler` 只落在预期节点；
- [ ] CirrOS VMI Ready，串口 console 能连接和退出；
- [ ] Desktop VM、`virt-launcher`、本地 PV 的节点一致；
- [ ] Tiny Core 图形桌面可通过 noVNC 操作；
- [ ] noVNC 代理只有命名空间内 VNC 所需最小权限；
- [ ] 断开并重新连接浏览器时，`virtctl` 代理能够自动恢复；
- [ ] 健康检查没有占用 5900 的单连接代理；
- [ ] 停止并重启 VM 后，写入持久根盘的测试文件仍存在；
- [ ] 已记录本地盘不可迁移、节点故障不可用和 `Retain` 回收流程；
- [ ] 正式工作站改用 Ubuntu LTS 黄金镜像，并固定 Jupyter/code-server 版本；
- [ ] VM 能解析企业内网 FQDN，DNS 查询不会先等待不可达的 kube-dns 超时；
- [ ] 需要访问 Kubernetes Service 的 VM 已验证 `*.svc.cluster.local`，没有把动态 CoreDNS Pod IP 固定进模板；
- [ ] Cilium kube-proxy replacement 场景已回归 VM 到 ClusterIP 的 TCP/UDP 访问；
- [ ] 用户入口使用稳定域名或 Service，没有把 VMI Pod IP 当作 VM 的永久地址；
- [ ] 需要固定办公网 IP 的 VM 已验证 Multus、固定 MAC、IPAM、VLAN、返回路由和地址回收；
- [ ] underlay 网络不会绕过预期的 ACL、审计和租户隔离；
- [ ] 自动停机综合 Jupyter、SSH、后台任务与资源信号，不会把单一 HTTP 空闲当作 VM 空闲；
- [ ] 自动停机经过通知和宽限期，并提供有上限、可审计的保持运行租约；
- [ ] 停止 VM 后 VMI/`virt-launcher` 消失、计算资源释放、PVC 保留，按需唤醒后服务自动恢复；
- [ ] 生产入口具备 HTTPS、统一认证、授权、审计和网络访问控制。

这次实验最有价值的结论不是“浏览器里出现了桌面”，而是把状态边界验证清楚了：`containerDisk` 和 Live ISO 负责分发启动介质，DataVolume/PVC 才负责保存用户完整环境；本地盘能验证持久工作站体验，但不能假装具备共享存储的故障恢复能力。
