---
title: 用 KubeVirt 与 Ceph RBD 构建持久 GPU Notebook
description: 为每个用户提供带独立 RBD 根盘的持久 Linux 工作站，覆盖宿主机准备、KubeVirt/CDI、GPU 直通、快照、故障恢复和生产验收
status: lab
last_reviewed: 2026-08-04
---

# 用 KubeVirt 与 Ceph RBD 构建持久 GPU Notebook

容器 Notebook 通常只持久化 `/home` 或 `/workspace`。但真实用户会把 Conda、Python、编译器、系统包和缓存写到 `/opt`、`/usr/local`、`/var`、`~/.cache`，甚至修改 systemd 服务。平台无法要求所有用户始终把文件放到正确的 PVC 目录，也无法靠几个软链接完整模拟一台可变 Linux 工作站。

如果企业已经有 Ceph RBD，而且每个用户的个人环境不需要同时挂载给多台机器，最直接的解法是：**给每位用户创建一台 KubeVirt VM，并把独立 Ceph RBD 块卷作为 VM 根盘**。用户停止 VM 后，CPU、内存和 GPU 被释放，整套文件系统继续保存在 RBD 中。

这篇实战的目标不是证明 VM 比容器更先进，而是建立一种明确的“持久工作站模式”，解决任意安装路径无法被容器目录挂载完整覆盖的问题。

## 1. 先确认这个方案是否匹配

### 适合

- 用户确实需要 `apt`、systemd、自定义 CUDA Toolkit、编译器或内核无关的系统配置；
- 用户习惯把 Conda、Python、IDE 插件和缓存安装到任意目录；
- 工作区需要停止数天后原样恢复，但停止期间不能继续占用 GPU；
- 每个用户的根文件系统不需要被多台 Notebook 同时读写；
- 集群已经有稳定的 Ceph RBD CSI、快照、监控和容量治理；
- 平台能承担 guest OS 补丁、黄金镜像、磁盘备份和 VM 故障恢复。

### 不适合

- 只需要标准 Python 环境和一个持久 Home，容器已经能满足；
- 追求秒级启动、极高密度或大量一次性会话；
- 需要让同一个用户目录同时挂载到多台机器，应改用 CephFS 等共享文件系统；
- 正式训练必须由 Notebook 自身长期运行，无法移交到 Job、TrainJob 或 RayJob；
- 平台不愿维护 guest OS 漏洞、磁盘增长和长期环境漂移。

| 问题 | VM + RBD 根盘能否解决 | 说明 |
| --- | --- | --- |
| Conda/Python 装在任意路径 | 能 | `/` 中的所有文件都在持久根盘上 |
| `apt`、系统库和 IDE 插件重启后保留 | 能 | 保存的是完整 guest 文件系统 |
| 停止后释放 GPU | 能 | 停止 VMI，保留 VM 对象与 RBD |
| 环境可复现 | 不能自动解决 | 仍需黄金镜像、Lockfile、导出与重置能力 |
| 磁盘不会写满 | 不能 | 缓存、日志和模型仍需配额与告警 |
| GPU VM 自动热迁移 | 通常不能承诺 | PCI Passthrough 等设备会限制迁移 |
| 用户重要数据自动备份 | 不能 | 快照、备份和恢复必须另行建设 |

## 2. 目标架构与生命周期

```text
企业 OIDC / Workspace Portal
             │
             ├─ 创建、启动、停止、快照、重置
             ▼
KubeVirt VirtualMachine（每用户一台）
  ├─ 根盘 /：Ceph RBD，100–200 GiB
  │    ├─ OS、/home、/opt、/usr/local、/var
  │    ├─ Conda、Python、编译器、IDE 插件
  │    └─ 用户缓存和系统配置
  ├─ 工作盘 /workspace：可选的独立 RBD
  ├─ 数据/模型：对象存储或按需只读共享
  ├─ /scratch：节点本地 NVMe，可丢弃
  └─ GPU：PCI Passthrough 或经过验证的 vGPU
```

推荐把对象生命周期拆开：

```text
用户申请
  → 从黄金镜像克隆独立 RBD 根盘
  → 创建 VirtualMachine（默认停止）
  → 启动 VMI，分配 CPU/内存/GPU
  → 用户任意修改 guest 文件系统
  → 空闲提醒并关机
  → VMI 消失，计算资源释放，VM 与 RBD 保留
  → 再次启动，恢复原环境
```

**停止 VM 和删除 VM 必须是两个不同权限、不同确认级别的操作。** 如果根盘来自 VM 内的 `dataVolumeTemplates`，删除 VM 可能连带删除 DataVolume/PVC。生产平台更适合独立管理用户 DataVolume/PVC，再由 VM 通过 `persistentVolumeClaim` 引用；删除用户磁盘必须经过快照、保留期和二次确认。

## 3. 需要哪些集群组件

| 组件 | 是否必需 | 作用 |
| --- | --- | --- |
| Kubernetes | 必需 | 运行 KubeVirt 控制面和 `virt-launcher` Pod |
| KubeVirt Operator/CR | 必需 | 管理 VM、VMI、调度和生命周期 |
| CDI | 必需 | 导入、上传或克隆黄金镜像，创建 DataVolume |
| Ceph RBD CSI | 必需 | 动态创建每用户块卷并挂载到 VM |
| CSI Snapshot Controller 与 `VolumeSnapshotClass` | 强烈建议 | VM 根盘快照、回滚和误操作保护 |
| CNI | 必需 | 提供默认 Pod 网络；复杂网络再增加 Multus/SR-IOV |
| OIDC/Gateway/Portal | 生产必需 | 用户身份、Web 入口和自助生命周期 |
| QEMU Guest Agent | 强烈建议 | guest 状态、优雅关机和在线一致性快照 |
| Prometheus/Grafana/日志系统 | 生产必需 | VM、节点、RBD、GPU 和容量观测 |
| Node Health Check/fencing 自动化 | 生产必需 | 节点失联后安全释放并重新挂载 RBD |

CDI 支持把 HTTP、Registry 或现有 PVC 中的镜像导入或克隆为 DataVolume。参考：[KubeVirt CDI](https://kubevirt.io/user-guide/storage/containerized_data_importer/)

## 4. 宿主机准备

### 4.1 最低硬件和操作系统条件

每个承载 VM 的 Worker 至少满足：

- BIOS/UEFI 开启 Intel VT-x/VT-d 或 AMD-V/AMD-Vi；
- Linux 内核加载 `kvm` 以及 `kvm_intel` 或 `kvm_amd`；
- `/dev/kvm`、`/dev/vhost-net`、`/dev/net/tun` 存在并可用；
- Kubernetes API Server 允许 KubeVirt 所需的特权 DaemonSet；
- 使用受支持的 containerd 或 CRI-O，并核对 Kubernetes 与 KubeVirt 版本矩阵；
- 节点时间同步、DNS、CNI、MTU 和访问 Ceph MON 的网络稳定；
- SELinux 节点安装匹配版本的 `container-selinux`，AppArmor 策略不阻止 QEMU/KVM。

在每个候选节点执行：

```bash
# Intel 通常出现 vmx，AMD 通常出现 svm；结果必须大于 0
grep -Ec '(vmx|svm)' /proc/cpuinfo

ls -l /dev/kvm /dev/vhost-net /dev/net/tun
lsmod | grep -E 'kvm|vhost'

# 安装 libvirt client/host validation 工具后执行
virt-host-validate qemu
```

KubeVirt 官方建议用 `virt-host-validate qemu` 验证硬件虚拟化、KVM、vhost-net 和 TUN。软件模拟 `useEmulation: true` 只适合实验，不能作为 GPU Notebook 的生产方案。参考：[KubeVirt 安装条件](https://kubevirt.io/user-guide/cluster_admin/installation/)

如果 Kubernetes Worker 本身运行在虚拟机里，还必须由外层虚拟化平台开启 Nested Virtualization：

```bash
cat /sys/module/kvm_intel/parameters/nested 2>/dev/null
cat /sys/module/kvm_amd/parameters/nested 2>/dev/null
```

### 4.2 节点池与标签

不要默认让所有 Kubernetes Worker 都承载 VM。建议建立独立节点池：

```text
vm-cpu         普通 CPU Notebook VM
vm-gpu-pci     GPU 绑定 vfio-pci，专供 GPU 直通 VM
container-gpu  GPU 绑定 nvidia/amdgpu 驱动，专供容器 Pod
```

示例标签与污点：

```bash
kubectl label node <node> workload.example.com/kubevirt=true
kubectl label node <node> accelerator.example.com/mode=vfio
kubectl taint node <node> workload.example.com/kubevirt=true:NoSchedule
```

再通过 KubeVirt CR 的 `spec.workloads.nodePlacement` 约束 `virt-handler`，通过 VM 的 Node Selector、Affinity 和 Toleration 约束用户工作负载。这样普通容器不会误占 VFIO GPU 节点，VM 也不会调度到没有 KVM 的节点。

### 4.3 CPU、NUMA 与 HugePages

普通开发 VM 不必一开始就启用专用 CPU 和 HugePages。对数据预处理、编译和单卡调试，先使用普通 CPU request，测到明显抖动再优化。

需要稳定延迟或高吞吐时，再配置：

- kubelet `cpuManagerPolicy: static`；
- VM `dedicatedCpuPlacement: true`，并令 CPU request/limit 相等且为整数；
- Topology Manager `single-numa-node` 或适合当前节点拓扑的策略；
- 节点预留 2 MiB/1 GiB HugePages，VM 显式请求相同页大小；
- NUMA passthrough 前先验证专用 CPU、HugePages 和设备拓扑；
- 为 QEMU emulator、`virt-launcher` 和平台 DaemonSet 预留额外 CPU/内存。

KubeVirt 的专用 vCPU 依赖 Kubernetes CPU Manager；NUMA passthrough 还要求 Dedicated CPU 和可分配 HugePages。参考：[Dedicated CPU](https://kubevirt.io/user-guide/compute/dedicated_cpu_resources/)、[NUMA](https://kubevirt.io/user-guide/compute/numa/)

### 4.4 GPU 直通宿主机准备

PCI Passthrough 的宿主机还需要：

1. BIOS 开启 IOMMU；
2. 内核启动参数加入 `intel_iommu=on iommu=pt` 或 `amd_iommu=on iommu=pt`；
3. 加载 `vfio`、`vfio_pci`、`vfio_iommu_type1`；
4. 验证目标 GPU 的 IOMMU Group，不能把仍由宿主机使用的设备错误地一起直通；
5. 将目标 GPU 持久绑定到 `vfio-pci`，再由 KubeVirt 暴露为资源；
6. 在 guest 黄金镜像中安装与目标 GPU 匹配的驱动和 CUDA/ROCm 用户态。

检查示例：

```bash
dmesg | grep -Ei 'DMAR|IOMMU'
find /sys/kernel/iommu_groups -type l
lsmod | grep -E 'vfio|kvm'
lspci -nnk | grep -A3 -Ei 'NVIDIA|AMD.*VGA|3D controller'
```

同一张物理 GPU 不能一边绑定 `vfio-pci` 给 VM，一边继续由 NVIDIA Device Plugin 分配给容器。生产上应排空节点后持久修改驱动绑定，并把“容器 GPU 节点”和“VM 直通 GPU 节点”分开。不要在有活跃任务的节点上临时执行 unbind/bind。

KubeVirt CR 还要允许对应设备。资源名和 PCI ID 必须换成实际硬件：

```yaml
apiVersion: kubevirt.io/v1
kind: KubeVirt
metadata:
  name: kubevirt
  namespace: kubevirt
spec:
  configuration:
    permittedHostDevices:
      pciHostDevices:
        - pciVendorSelector: "10DE:20B0"
          resourceName: nvidia.com/A100-PCIE-40GB
```

KubeVirt 支持 PCI 设备和 mediated device/vGPU，但 vGPU 还涉及厂商驱动、License 和 Profile 生命周期。参考：[Host Devices Assignment](https://kubevirt.io/user-guide/compute/host-devices/)、[Mediated Devices](https://kubevirt.io/user-guide/compute/mediated_devices_configuration/)

## 5. Ceph RBD 前置检查

### 5.1 StorageClass 设计

用户根盘建议：

- `volumeMode: Block`，由 guest 自己使用 ext4/XFS；
- `accessModes: [ReadWriteOnce]`，一个根盘只允许一个活跃 VM；
- `allowVolumeExpansion: true`，支持磁盘扩容；
- 独立 RBD Pool 或至少独立 StorageClass，便于 QoS、配额和成本归属；
- 使用 SSD/低延迟 Pool，实测 Conda 解包、Git Checkout 和 Python Import；
- 对个人根盘评估 `reclaimPolicy: Retain`，同时建立离职与过期卷清理流程；
- 设置对应的 `VolumeSnapshotClass`，并验证创建、删除、恢复行为。

检查：

```bash
kubectl get storageclass
kubectl get volumesnapshotclass
kubectl get csidriver
```

RWO 表示卷在一个节点上读写，不等于可以跳过平台侧的单实例控制。绝不能让两个 VM 同时挂载并写入同一个 guest 文件系统。节点失联时也不能在确认原节点彻底离线前强行从另一节点启动同一 RBD，否则可能双写损坏。

### 5.2 为什么不是 CephFS Home

这里的目标不是共享目录，而是透明保留整个 Linux 系统。RBD 暴露块设备，guest 在其上维护自己的文件系统，因此 `/etc`、`/opt`、`/usr/local`、`/var`、Home 和各种隐藏缓存一起持久化。CephFS 更适合多节点共享目录，但不能自然保存完整 OS 根盘，也会把所有用户放到共享文件系统的元数据和权限治理路径上。

### 5.3 建议拆成根盘和工作盘

只用一个根盘可以解决问题，但生产上更推荐：

| 卷 | 默认容量 | 保存内容 | 重置行为 |
| --- | --- | --- | --- |
| Root RBD | 100–200 GiB | OS、Conda、Python、缓存、用户配置 | 可从黄金镜像重建 |
| Workspace RBD | 100–500 GiB | 代码、Notebook、未提交结果 | 重装根盘时继续保留 |
| Object Storage | 按项目 | 数据集、模型、Checkpoint、Artifact | 权威副本，不随 VM 删除 |
| Local Scratch | 按节点 | 可重建缓存和临时文件 | 关机、迁移或节点故障可丢失 |

这样既允许用户任意修改系统，又能在根盘损坏或升级时保留真正重要的工作目录。

## 6. 安装 KubeVirt 与 CDI

生产环境应固定经过验证的 KubeVirt/CDI 版本，并按照官方支持矩阵从 N-1 逐级升级。下面只展示安装顺序，不建议在生产脚本里直接解析 `latest`：

```bash
kubectl apply -f kubevirt-operator-<version>.yaml
kubectl apply -f kubevirt-cr-<version>.yaml
kubectl -n kubevirt wait kubevirt kubevirt --for=condition=Available --timeout=10m

kubectl apply -f cdi-operator-<version>.yaml
kubectl apply -f cdi-cr-<version>.yaml
kubectl -n cdi wait cdi cdi --for=condition=Available --timeout=10m
```

安装后检查：

```bash
kubectl get pods -n kubevirt
kubectl get pods -n cdi
kubectl get nodes -L kubevirt.io/schedulable
kubectl get kubevirt -n kubevirt kubevirt -o yaml
```

KubeVirt 需要特权 `virt-handler` DaemonSet。安装前应确认 Pod Security、Admission、SELinux/AppArmor 和安全扫描策略不会把它静默拦截；用户 VM 本身不应因此获得 Kubernetes 集群管理员权限。

## 7. 建立黄金镜像和用户根盘

黄金镜像至少包含：

- Ubuntu/RHEL 系兼容 OS 与安全补丁；
- `qemu-guest-agent`、cloud-init、SSH 或平台代理；
- JupyterLab/VS Code Server 的受控启动方式；
- 企业 CA、Registry、PyPI/Conda Mirror 和代理配置；
- guest GPU 驱动、CUDA/ROCm 兼容基线；
- 磁盘自动扩容工具、日志轮转和时间同步；
- 不包含用户密码、长期 Token、私钥和固定主机身份。

先把镜像导入一个受保护的黄金 DataVolume，再为每个用户克隆。示例中的 StorageClass、Namespace、源 PVC 和容量都要替换：

```yaml
apiVersion: cdi.kubevirt.io/v1beta1
kind: DataVolume
metadata:
  name: alice-rootdisk
  namespace: notebook-alice
  labels:
    platform.example.com/user: alice
spec:
  source:
    pvc:
      namespace: vm-images
      name: ubuntu-24-04-cuda-golden
  storage:
    storageClassName: ceph-rbd
    accessModes:
      - ReadWriteOnce
    volumeMode: Block
    resources:
      requests:
        storage: 150Gi
```

跨 Namespace 克隆需要 CDI/CSI 克隆能力和显式授权。平台控制器应代替最终用户创建根盘，避免用户读取其他人的 PVC 或黄金镜像源。检查克隆结果：

```bash
kubectl -n notebook-alice wait datavolume alice-rootdisk \
  --for=condition=Ready --timeout=30m
kubectl -n notebook-alice get datavolume,pvc
```

## 8. 创建一台持久 GPU Notebook VM

下面是最小骨架。`runStrategy: Halted` 表示创建后默认不启动；GPU 资源名、SSH 公钥、域名和镜像初始化方式必须按环境调整。

```yaml
apiVersion: kubevirt.io/v1
kind: VirtualMachine
metadata:
  name: alice-gpu-workstation
  namespace: notebook-alice
  labels:
    platform.example.com/user: alice
    platform.example.com/profile: gpu-a100-1
spec:
  runStrategy: Halted
  template:
    metadata:
      labels:
        app: alice-gpu-workstation
        platform.example.com/user: alice
    spec:
      terminationGracePeriodSeconds: 120
      nodeSelector:
        workload.example.com/kubevirt: "true"
        accelerator.example.com/mode: vfio
      tolerations:
        - key: workload.example.com/kubevirt
          operator: Equal
          value: "true"
          effect: NoSchedule
      domain:
        memory:
          guest: 64Gi
        resources:
          requests:
            cpu: "8"
            memory: 64Gi
        devices:
          autoattachGraphicsDevice: false
          disks:
            - name: rootdisk
              disk:
                bus: virtio
            - name: cloudinit
              disk:
                bus: virtio
          interfaces:
            - name: default
              masquerade: {}
          gpus:
            - name: gpu0
              deviceName: nvidia.com/A100-PCIE-40GB
      networks:
        - name: default
          pod: {}
      volumes:
        - name: rootdisk
          persistentVolumeClaim:
            claimName: alice-rootdisk
        - name: cloudinit
          cloudInitNoCloud:
            userData: |
              #cloud-config
              hostname: alice-gpu-workstation
              packages:
                - qemu-guest-agent
              runcmd:
                - [systemctl, enable, --now, qemu-guest-agent]
```

如果要暴露 Jupyter，可以让平台代理访问 guest，或创建指向 VMI 标签的 Service，再由 Gateway/Ingress 做 OIDC 和 TLS：

```yaml
apiVersion: v1
kind: Service
metadata:
  name: alice-jupyter
  namespace: notebook-alice
spec:
  selector:
    app: alice-gpu-workstation
  ports:
    - name: http
      port: 8888
      targetPort: 8888
```

不要把无认证的 Jupyter 直接暴露到公网，也不要在 YAML 中保存密码或长期 Token。Notebook VM 默认不应持有集群管理员 kubeconfig；提交正式任务时使用最小权限平台 API、短期凭据或单独的 Job 提交身份。

## 9. 启停、空闲回收和环境重置

```bash
virtctl start -n notebook-alice alice-gpu-workstation
virtctl stop -n notebook-alice alice-gpu-workstation

kubectl -n notebook-alice get vm,vmi,pvc
```

停止成功后应该看到：

- `VirtualMachine` 仍存在；
- `VirtualMachineInstance` 消失；
- 根盘 PVC 仍为 `Bound`；
- GPU 资源重新回到节点可分配池；
- 再次启动后 `/etc`、`/opt`、Conda、Python、Home 和缓存仍存在。

Idle Culler 不能只看网页是否关闭。应同时观察 Jupyter Kernel、SSH/终端进程、GPU 利用率和用户最近活动，先提醒、再优雅关机，超时后才强制停止。正式训练应转交到 Job/TrainJob/RayJob，不能靠关闭 Culler 长期占用个人 VM。

平台至少提供四个不同操作：

1. **停止**：释放计算资源，保留全部磁盘；
2. **启动**：在可用节点重新挂载根盘并启动；
3. **重置系统**：从黄金镜像重建 Root RBD，默认保留 Workspace RBD；
4. **删除账户数据**：经过备份、保留期、审批后删除 Root/Workspace RBD。

## 10. 快照、备份与恢复

KubeVirt `VirtualMachineSnapshot` 依赖 CSI `VolumeSnapshot`。运行中快照会检查 QEMU Guest Agent；Agent 可用时冻结 guest 文件系统，Agent 缺失时只能获得类似突然断电的 crash-consistent 快照。重要变更前最稳妥的路径仍是先关机再拍快照。参考：[KubeVirt Snapshot Restore API](https://kubevirt.io/user-guide/storage/snapshot_restore_api/)

```yaml
apiVersion: snapshot.kubevirt.io/v1beta1
kind: VirtualMachineSnapshot
metadata:
  name: alice-before-cuda-upgrade
  namespace: notebook-alice
spec:
  source:
    apiGroup: kubevirt.io
    kind: VirtualMachine
    name: alice-gpu-workstation
```

```bash
kubectl -n notebook-alice wait vmsnapshot alice-before-cuda-upgrade \
  --for=condition=Ready --timeout=10m
kubectl -n notebook-alice get vmsnapshot alice-before-cuda-upgrade -o yaml
```

必须验证状态中的 `readyToUse`、包含卷列表，以及快照是 `GuestAgent` 参与还是 `NoGuestAgent`。快照不是离线备份：Ceph Pool 故障、误删快照或集群级事故仍可能同时影响原卷与快照，关键用户数据还要复制到独立故障域或备份系统。

## 11. 节点故障、fencing 与重新调度

个人 Notebook 的高可用目标通常不是无感热迁移，而是：

```text
节点失联
  → 停止新 VM 调度到该节点
  → 确认旧节点已关机或隔离 Ceph/存储网络
  → 清理失联 VMI/Pod 状态
  → 在另一台兼容节点重新挂载同一 RBD
  → 冷启动 VM
  → 验证文件系统、GPU 与 Jupyter
```

Ceph RBD 的安全红线是避免同一可写卷在两个仍可能运行的 guest 中出现。仅仅把 Kubernetes Node 标成 `NotReady` 不一定证明原主机已经停止写盘。应把 BMC/IPMI、电源控制、Ceph-CSI network fencing、节点隔离和平台恢复 Runbook 串起来。Rook 的 RBD 文档也要求在节点丢失场景先确认旧节点离线，再进行卷迁移和应用恢复。参考：[Rook RBD Block Storage](https://rook.io/docs/rook/latest-release/Storage-Configuration/Block-Storage-RBD/block-storage/)、[RBD Application Migration](https://rook.io/docs/rook/latest-release/Storage-Configuration/Block-Storage-RBD/app-migration/)

GPU PCI Passthrough VM 默认按“停止并冷启动”设计。只有 `VirtualMachineInstance` 明确报告 `LiveMigratable=True`，并且存储、CPU、网络和全部设备都通过迁移演练后，才能把热迁移写进 SLO。KubeVirt 的常规热迁移要求共享访问能力，而 RWO 根盘和 Host Device 往往成为限制。参考：[KubeVirt Live Migration](https://kubevirt.io/user-guide/compute/live_migration/)

## 12. 监控和容量治理

| 层次 | 关键指标与告警 |
| --- | --- |
| KubeVirt | VM/VMI 状态、启动失败、Guest Agent、停止时长、节点可调度标签 |
| 宿主机 | KVM/VFIO、CPU Steal、内存、HugePages、IOMMU、硬件错误 |
| Ceph RBD | 容量、IOPS、吞吐、P95/P99 延迟、慢请求、降级 PG、快照增长 |
| Guest | 根盘/inode 使用率、日志、OOM、Jupyter 状态、SSH、NTP |
| GPU | Allocation、显存、SM、功耗、温度、XID、PCIe 错误、ECC |
| 平台 | 活跃用户、Idle GPU Hours、启动时间、快照成功率、恢复时间 |

根盘应在 70%、85%、95% 设置分级告警。默认清理策略只能删除明确可重建的缓存和过期日志，不能静默清理用户项目。扩容后还要在 guest 内完成分区或文件系统扩展，黄金镜像应预装并验证相关工具。

成本报表要同时显示 VM 配置容量和实际用量。RBD Thin Provisioning 不能替代配额；大量个人根盘、快照和长期停止 VM 仍会逐步吃满 Ceph Pool。

## 13. 上线验收实验

### 宿主机与调度

- [ ] 所有 VM 节点通过 `virt-host-validate qemu`；
- [ ] KVM、vhost、TUN、IOMMU 和 VFIO 在重启后仍正确加载；
- [ ] VFIO GPU 节点不会被容器 GPU 工作负载误用；
- [ ] VM 只能调度到匹配的 CPU/GPU 节点池；
- [ ] 节点排空、升级和重启有独立 Runbook。

### 持久化语义

- [ ] 分别在 `/etc`、`/opt`、`/usr/local`、Home 和 Conda 默认目录写入测试文件；
- [ ] 安装 Python 包、IDE 插件和系统包后关机再启动；
- [ ] 验证所有文件和服务状态仍在；
- [ ] 停止 VM 后 GPU、CPU 和内存确实释放；
- [ ] 删除 VM 不会未经确认删除用户根盘；
- [ ] Root RBD 重置时 Workspace RBD 和对象存储数据不受影响。

### 存储与恢复

- [ ] 黄金镜像克隆并发不会压垮 Ceph；
- [ ] 实测 Conda 解包、Python Import、Git Checkout 和模型缓存；
- [ ] Root/Workspace RBD 可以扩容并在 guest 内识别；
- [ ] 在线快照有 Guest Agent 参与，离线快照可恢复；
- [ ] 恢复后的 VM 能启动、挂载磁盘并识别 GPU；
- [ ] 模拟节点失联，完成 fencing 后在另一节点冷启动；
- [ ] 证明不会出现双挂载、双写和旧节点复活后再次写盘。

### 安全与产品体验

- [ ] 用户只能管理自己的 VM、Console、Service 和快照；
- [ ] Jupyter 入口经过 OIDC、TLS、审计和网络策略；
- [ ] guest 不持有集群管理员凭据；
- [ ] 用户能区分停止、重启、重置系统和删除数据；
- [ ] 空闲关机前提醒，关机后磁盘仍保留；
- [ ] 磁盘配额、快照保留和费用对用户可见。

## 14. 优缺点复盘

### 优点

- 不再依赖用户遵守持久目录约定，完整 Linux 状态透明保留；
- RBD 不要求个人目录共享，隔离、独立扩容、快照和恢复边界清晰；
- 停机后释放昂贵 GPU，同时保留“个人工作站”体验；
- 支持 systemd、apt、自定义系统库和复杂 IDE；
- 仍然沿用 Kubernetes 的 Namespace、调度、配额、API 和观测体系。

### 代价

- 启动、内存开销和资源密度通常不如容器；
- 平台要维护 guest OS 补丁、黄金镜像、驱动和环境漂移；
- PCI GPU 直通带来专用节点池、VFIO 和迁移限制；
- 每用户根盘与快照会持续消耗 Ceph 容量；
- 节点故障恢复必须依赖可靠 fencing，不能粗暴强制重挂 RBD；
- VM 解决“不会丢”，但不会自动让实验可复现或正式训练可靠。

## 15. 推荐的落地顺序

1. 先在无 GPU 的两个 Worker 上完成 KVM、KubeVirt、CDI 和 RBD 根盘 PoC；
2. 验证停止/恢复、扩容、快照、重置和节点故障 fencing；
3. 准备一个 VFIO GPU 节点池，完成单卡直通与 guest 驱动测试；
4. 建立 CPU、单 GPU、不同内存和磁盘容量的版本化 Profile；
5. 接入 OIDC、Gateway、Idle Culler、审计、配额和成本展示；
6. 小范围开放“持久工作站模式”，与容器 Notebook 并存；
7. 将正式训练统一移交到 Job、TrainJob、RayJob 和队列系统；
8. 达到恢复、容量和安全门禁后，再扩大用户范围。

最终产品不必在容器和 VM 之间二选一：标准用户使用启动快、易复现的容器 Notebook；确实需要任意修改系统环境的用户选择 KubeVirt + RBD 持久工作站。两者共享身份、数据、模型制品和任务提交入口，但采用不同的生命周期与运维承诺。
