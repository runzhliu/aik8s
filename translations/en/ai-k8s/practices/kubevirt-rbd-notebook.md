---
title: "Building Persistent GPU Notebooks with KubeVirt and Ceph RBD"
description: "Provide each user with a persistent Linux workstation with a dedicated RBD root disk, covering host preparation, KubeVirt/CDI, GPU passthrough, snapshots, failure recovery, and production acceptance"
status: lab
last_reviewed: 2026-08-04
---

# Building Persistent GPU Notebooks with KubeVirt and Ceph RBD

Container notebooks typically only persist `/home` or `/workspace`. But real users write Conda, Python, compilers, system packages, and caches to `/opt`, `/usr/local`, `/var`, `~/.cache`, and even modify systemd services. The platform cannot require all users to always place files in the correct PVC directory, nor can it fully emulate a mutable Linux workstation with a few symlinks.

If the enterprise already has Ceph RBD, and each user's personal environment does not need to be mounted on multiple machines simultaneously, the most direct solution is: **create a KubeVirt VM for each user, and use a dedicated Ceph RBD block volume as the VM root disk**. After the user stops the VM, CPU, memory, and GPU are released, while the entire file system continues to be preserved in RBD.

The goal of this practical guide is not to prove that VMs are more advanced than containers, but to establish a clear "persistent workstation pattern" that solves the problem of arbitrary installation paths that cannot be fully covered by container directory mounts.

## 1. First Confirm Whether This Approach Fits

### Suitable When

- Users genuinely need `apt`, systemd, custom CUDA Toolkit, compilers, or kernel-independent system configuration;
- Users habitually install Conda, Python, IDE plugins, and caches into arbitrary directories;
- The workspace needs to be restored exactly as-is after being stopped for days, but must not continue occupying GPU while stopped;
- Each user's root file system does not need to be read/written by multiple notebooks simultaneously;
- The cluster already has stable Ceph RBD CSI, snapshots, monitoring, and capacity governance;
- The platform can bear the cost of guest OS patching, golden images, disk backups, and VM failure recovery.

### Not Suitable When

- Only a standard Python environment and a persistent Home are needed; containers already suffice;
- You need second-level startup, extremely high density, or large numbers of one-off sessions;
- The same user directory needs to be mounted on multiple machines simultaneously; use a shared file system such as CephFS instead;
- Formal training must be run long-term by the notebook itself and cannot be handed off to Job, TrainJob, or RayJob;
- The platform is unwilling to maintain guest OS vulnerabilities, disk growth, and long-term environment drift.

| Question | Can VM + RBD root disk solve it? | Explanation |
| --- | --- | --- |
| Conda/Python installed in arbitrary paths | Yes | All files in `/` are on the persistent root disk |
| `apt`, system libraries, and IDE plugins survive restart | Yes | The complete guest file system is preserved |
| GPU released after stop | Yes | Stop the VMI, keep the VM object and RBD |
| Environment reproducible | Cannot solve automatically | Still requires golden images, Lockfiles, export and reset capabilities |
| Disk will not fill up | No | Caches, logs, and models still need quotas and alerts |
| GPU VM automatic live migration | Usually cannot be promised | Devices such as PCI Passthrough limit migration |
| User critical data automatically backed up | No | Snapshots, backups, and recovery must be built separately |

## 2. Target Architecture and Lifecycle

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

It is recommended to separate the object lifecycle:

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

**Stopping a VM and deleting a VM must be two operations with different permissions and different confirmation levels.** If the root disk comes from `dataVolumeTemplates` inside the VM, deleting the VM may cascade to deleting the DataVolume/PVC. A production platform is better off managing user DataVolumes/PVCs independently, with the VM referencing them via `persistentVolumeClaim`; deleting a user disk must go through snapshots, a retention period, and secondary confirmation.

## 3. Required Cluster Components

| Component | Required? | Purpose |
| --- | --- | --- |
| Kubernetes | Required | Runs the KubeVirt control plane and `virt-launcher` Pods |
| KubeVirt Operator/CR | Required | Manages VMs, VMIs, scheduling, and lifecycle |
| CDI | Required | Imports, uploads, or clones golden images; creates DataVolumes |
| Ceph RBD CSI | Required | Dynamically creates per-user block volumes and attaches them to VMs |
| CSI Snapshot Controller and `VolumeSnapshotClass` | Strongly recommended | VM root disk snapshots, rollback, and misoperation protection |
| CNI | Required | Provides the default Pod network; add Multus/SR-IOV for complex networks |
| OIDC/Gateway/Portal | Required for production | User identity, web entry point, and self-service lifecycle |
| QEMU Guest Agent | Strongly recommended | Guest status, graceful shutdown, and online consistent snapshots |
| Prometheus/Grafana/logging system | Required for production | VM, node, RBD, GPU, and capacity observability |
| Node Health Check/fencing automation | Required for production | Safely release and re-attach RBD after node loss |

CDI supports importing or cloning images from HTTP, Registry, or existing PVCs into DataVolumes. Reference: [KubeVirt CDI](https://kubevirt.io/user-guide/storage/containerized_data_importer/)

## 4. Host Preparation

### 4.1 Minimum Hardware and Operating System Conditions

Each Worker hosting VMs must satisfy at least:

- BIOS/UEFI has Intel VT-x/VT-d or AMD-V/AMD-Vi enabled;
- Linux kernel has `kvm` loaded, as well as `kvm_intel` or `kvm_amd`;
- `/dev/kvm`, `/dev/vhost-net`, `/dev/net/tun` exist and are usable;
- Kubernetes API Server allows the privileged DaemonSets required by KubeVirt;
- Use a supported containerd or CRI-O, and verify the Kubernetes and KubeVirt version matrix;
- Node time synchronization, DNS, CNI, MTU, and network access to Ceph MONs are stable;
- SELinux nodes have the matching version of `container-selinux` installed, and AppArmor policies do not block QEMU/KVM.

On each candidate node, run:

```bash
# Intel 通常出现 vmx，AMD 通常出现 svm；结果必须大于 0
grep -Ec '(vmx|svm)' /proc/cpuinfo

ls -l /dev/kvm /dev/vhost-net /dev/net/tun
lsmod | grep -E 'kvm|vhost'

# 安装 libvirt client/host validation 工具后执行
virt-host-validate qemu
```

KubeVirt officially recommends using `virt-host-validate qemu` to verify hardware virtualization, KVM, vhost-net, and TUN. Software emulation `useEmulation: true` is only for experiments and cannot be a production solution for GPU notebooks. Reference: [KubeVirt installation requirements](https://kubevirt.io/user-guide/cluster_admin/installation/)

If the Kubernetes Worker itself runs inside a VM, the outer virtualization platform must also enable Nested Virtualization:

```bash
cat /sys/module/kvm_intel/parameters/nested 2>/dev/null
cat /sys/module/kvm_amd/parameters/nested 2>/dev/null
```

### 4.2 Node Pools and Labels

Do not default to letting all Kubernetes Workers host VMs. It is recommended to establish a dedicated node pool:

```text
vm-cpu         普通 CPU Notebook VM
vm-gpu-pci     GPU 绑定 vfio-pci，专供 GPU 直通 VM
container-gpu  GPU 绑定 nvidia/amdgpu 驱动，专供容器 Pod
```

Example labels and taints:

```bash
kubectl label node <node> workload.example.com/kubevirt=true
kubectl label node <node> accelerator.example.com/mode=vfio
kubectl taint node <node> workload.example.com/kubevirt=true:NoSchedule
```

Then constrain `spec.workloads.nodePlacement` through the `virt-handler` in the KubeVirt CR, and constrain user workloads through the VM's Node Selector, Affinity, and Toleration. This way, ordinary containers will not accidentally occupy VFIO GPU nodes, and VMs will not be scheduled onto nodes without KVM.

### 4.3 CPU, NUMA, and HugePages

Ordinary development VMs do not need dedicated CPUs and HugePages enabled from the start. For data preprocessing, compilation, and single-GPU debugging, start with ordinary CPU requests and optimize only after measurable jitter is observed.

When stable latency or high throughput is needed, configure:

- kubelet `cpuManagerPolicy: static`;
- VM `dedicatedCpuPlacement: true`, with equal integer CPU request/limit;
- Topology Manager `single-numa-node` or a policy appropriate to the current node topology;
- Node-reserved 2 MiB/1 GiB HugePages, with the VM explicitly requesting the same page size;
- Verify dedicated CPU, HugePages, and device topology before NUMA passthrough;
- Reserve additional CPU/memory for the QEMU emulator, `virt-launcher`, and platform DaemonSets.

KubeVirt's dedicated vCPUs depend on the Kubernetes CPU Manager; NUMA passthrough also requires Dedicated CPU and allocatable HugePages. Reference: [Dedicated CPU](https://kubevirt.io/user-guide/compute/dedicated_cpu_resources/), [NUMA](https://kubevirt.io/user-guide/compute/numa/)

The number of vCPUs in `domain.cpu`, the CPU request/limit of the `virt-launcher` Pod, and the host pCPUs are three different layers. When you need to choose between "fixed 2 cores per user", "guaranteed 2 cores with burst when idle", and "Best Effort oversubscription of 80 vCPU / 600 GiB Guest", and understand the differences between Guest OOM, cgroup OOM, and node eviction, see [Resource isolation of notebook containers, KubeVirt, and shared large machines](../development/gpu-notebook-platform.md#6-kubevirt).

### 4.4 GPU Passthrough Host Preparation

PCI Passthrough hosts additionally require:

1. IOMMU enabled in BIOS;
2. Kernel boot parameters including `intel_iommu=on iommu=pt` or `amd_iommu=on iommu=pt`;
3. Loading `vfio`, `vfio_pci`, `vfio_iommu_type1`;
4. Verifying the IOMMU Group of the target GPU; do not mistakenly pass through devices still in use by the host together with it;
5. Persistently binding the target GPU to `vfio-pci`, then exposing it as a resource through KubeVirt;
6. Installing the driver and CUDA/ROCm user-space components matching the target GPU in the guest golden image.

Inspection example:

```bash
dmesg | grep -Ei 'DMAR|IOMMU'
find /sys/kernel/iommu_groups -type l
lsmod | grep -E 'vfio|kvm'
lspci -nnk | grep -A3 -Ei 'NVIDIA|AMD.*VGA|3D controller'
```

The same physical GPU cannot be bound to `vfio-pci` for a VM while simultaneously being allocated to containers by the NVIDIA Device Plugin. In production, drain the node before persistently modifying the driver binding, and keep "container GPU nodes" and "VM passthrough GPU nodes" separate. Do not perform unbind/bind on nodes with active workloads.

The KubeVirt CR must also permit the corresponding devices. The resource name and PCI IDs must be replaced with actual hardware:

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

KubeVirt supports PCI devices and mediated devices/vGPU, but vGPU also involves vendor drivers, licenses, and profile lifecycles. Reference: [Host Devices Assignment](https://kubevirt.io/user-guide/compute/host-devices/), [Mediated Devices](https://kubevirt.io/user-guide/compute/mediated_devices_configuration/)

## 5. Ceph RBD Pre-checks

### 5.1 StorageClass Design

For user root disks, it is recommended:

- `volumeMode: Block`, with the guest itself using ext4/XFS;
- `accessModes: [ReadWriteOnce]`, one root disk allows only one active VM;
- `allowVolumeExpansion: true`, supporting disk expansion;
- A dedicated RBD Pool or at least a dedicated StorageClass, for QoS, quotas, and cost attribution;
- Use SSD/low-latency Pools; measure Conda unpacking, Git Checkout, and Python Import in practice;
- Evaluate `reclaimPolicy: Retain` for personal root disks, while establishing offboarding and expired-volume cleanup processes;
- Set the corresponding `VolumeSnapshotClass`, and verify create, delete, and restore behavior.

Check:

```bash
kubectl get storageclass
kubectl get volumesnapshotclass
kubectl get csidriver
```

RWO means the volume is read/write on one node, which does not mean platform-side single-instance control can be skipped. Never let two VMs mount and write to the same guest file system simultaneously. When a node is lost, do not force-start the same RBD from another node before confirming the original node is completely offline, otherwise dual-write corruption may occur.

### 5.2 Why Not CephFS Home

The goal here is not a shared directory, but transparently preserving the entire Linux system. RBD exposes a block device, and the guest maintains its own file system on it, so `/etc`, `/opt`, `/usr/local`, `/var`, Home, and various hidden caches are all persisted together. CephFS is better suited for multi-node shared directories, but it cannot naturally preserve a complete OS root disk, and it also places all users on the shared file system's metadata and permission governance path.

### 5.3 Recommended Split into Root Disk and Workspace Disk

A single root disk can solve the problem, but in production the following split is more recommended:

| Volume | Default Capacity | Contents | Reset Behavior |
| --- | --- | --- | --- |
| Root RBD | 100–200 GiB | OS, Conda, Python, caches, user configuration | Can be rebuilt from golden image |
| Workspace RBD | 100–500 GiB | Code, notebooks, uncommitted results | Retained when root disk is reinstalled |
| Object Storage | Per project | Datasets, models, checkpoints, artifacts | Authoritative copy, not deleted with VM |
| Local Scratch | Per node | Rebuildable caches and temporary files | May be lost on shutdown, migration, or node failure |

This allows users to modify the system arbitrarily while preserving the truly important working directory when the root disk is corrupted or upgraded.

## 6. Installing KubeVirt and CDI

Production environments should pin a verified KubeVirt/CDI version and upgrade step by step from N-1 according to the official support matrix. The following only shows the installation order; it is not recommended to directly parse `latest` in production scripts:

```bash
kubectl apply -f kubevirt-operator-<version>.yaml
kubectl apply -f kubevirt-cr-<version>.yaml
kubectl -n kubevirt wait kubevirt kubevirt --for=condition=Available --timeout=10m

kubectl apply -f cdi-operator-<version>.yaml
kubectl apply -f cdi-cr-<version>.yaml
kubectl -n cdi wait cdi cdi --for=condition=Available --timeout=10m
```

After installation, check:

```bash
kubectl get pods -n kubevirt
kubectl get pods -n cdi
kubectl get nodes -L kubevirt.io/schedulable
kubectl get kubevirt -n kubevirt kubevirt -o yaml
```

KubeVirt requires the privileged `virt-handler` DaemonSet. Before installation, confirm that Pod Security, Admission, SELinux/AppArmor, and security scanning policies do not silently block it; user VMs themselves should not thereby gain Kubernetes cluster-admin privileges.

## 7. Establishing Golden Images and User Root Disks

The golden image must contain at least:

- Ubuntu/RHEL-family compatible OS and security patches;
- `qemu-guest-agent`, cloud-init, SSH, or platform proxy;
- Controlled startup methods for JupyterLab/VS Code Server;
- Enterprise CA, Registry, PyPI/Conda Mirror, and proxy configuration;
- guest GPU drivers, CUDA/ROCm compatibility baseline;
- Disk auto-expansion tools, log rotation, and time synchronization;
- Does not include user passwords, long-lived tokens, private keys, or fixed host identity.

First import the image into a protected golden DataVolume, then clone it for each user. The StorageClass, Namespace, source PVC, and capacity in the example must all be replaced:

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

Cross-Namespace cloning requires CDI/CSI clone capability and explicit authorization. The platform controller should create root disks on behalf of end users, preventing users from reading other people's PVCs or the golden image source. Verify the clone result:

```bash
kubectl -n notebook-alice wait datavolume alice-rootdisk \
  --for=condition=Ready --timeout=30m
kubectl -n notebook-alice get datavolume,pvc
```

### 7.1 Clean up cloud-init and fixed NIC identity before sealing

You cannot simply shut down a VM that has already been booted and use it as a golden image. cloud-init caches instance-id, network rendering results, and initialization state; Ubuntu's `/etc/netplan/50-cloud-init.yaml` may also contain the MAC of the NIC from first boot. A cloned VM will receive a new MAC; if cloud-init misidentifies it as the old instance, Netplan will still only match the old MAC, which ultimately manifests as:

```text
VMI Phase：Running
VMI Ready：True
Guest Agent：Connected
VMI IP：空
Guest enp1s0：DOWN / unmanaged
```

This kind of problem is not necessarily a CNI or KubeVirt DHCP failure. First compare the current NIC and Netplan via Console:

```bash
virtctl console -n notebook-alice alice-gpu-workstation

ip -br address
networkctl status enp1s0 --no-pager
sed -n '1,160p' /etc/netplan/50-cloud-init.yaml
cloud-init status --long
```

If the MAC in the current `ip link` differs from the `match.macaddress` in Netplan, the fix should remove both `match` and the `set-name` that depends on it, keeping the configuration that enables DHCP by predictable interface name:

```yaml
network:
  version: 2
  ethernets:
    enp1s0:
      dhcp4: true
      dhcp6: false
```

After modification, verify first, then seal:

```bash
netplan generate
netplan apply
ip -br address
ip route
getent hosts kubernetes.default.svc
```

After confirming that qemu-guest-agent, SSH, JupyterLab, code-server, and the disk expansion flow all work normally, run the following inside the base image VM:

```bash
cloud-init clean --logs --machine-id --configs all
```

The expected result is that `/etc/machine-id` changes to `uninitialized`, and the cloud-init instance cache and generated Netplan are cleared. Then gracefully stop the VM and clone its PVC; do not boot it again after cleanup before making the image, otherwise instance identity will be rewritten. Whether `--configs` is available depends on the cloud-init version; the `cloud-init clean --help` inside the image should be authoritative. Reference: [cloud-init clean](https://docs.cloud-init.io/en/latest/reference/cli.html#clean)

Cleaning machine-id is not just about DHCP: it also prevents multiple clones from sharing the same systemd machine-id. The platform should also confirm that SSH Host Keys are regenerated on first boot, so that dozens of Notebooks do not inherit the same host identity.

## 8. Create a persistent GPU Notebook VM

The following is the minimal skeleton. `runStrategy: Halted` means it will not start by default after creation; GPU resource names, SSH public keys, domain names, and image initialization methods must be adjusted according to the environment.

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
              ports:
                - name: ssh
                  port: 22
                - name: code-server
                  port: 8080
                - name: jupyterlab
                  port: 8888
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
            networkData: |
              version: 2
              ethernets:
                enp1s0:
                  dhcp4: true
                  dhcp6: false
            userData: |
              #cloud-config
              hostname: alice-gpu-workstation
              packages:
                - qemu-guest-agent
              runcmd:
                - [systemctl, enable, --now, qemu-guest-agent]
```

`networkData` is a standalone network configuration for NoCloud; its content itself does not carry a top-level `network:`. A single-NIC, fixed q35 topology can use the predictable name `enp1s0`; for multi-NIC VMs, the platform should generate configuration per interface, and must not hard-code a specific clone's MAC in the golden disk. Reference: [KubeVirt cloud-init Startup Scripts](https://kubevirt.io/user-guide/user_workloads/startup_scripts/)

To access SSH, code-server, and JupyterLab via stable addresses, you can create a Service pointing to the VMI template label, then use Gateway/Ingress for OIDC and TLS:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: alice-notebook
  namespace: notebook-alice
spec:
  selector:
    app: alice-gpu-workstation
  ports:
    - name: ssh
      port: 22
      targetPort: 22
    - name: code-server
      port: 8080
      targetPort: 8080
    - name: jupyterlab
      port: 8888
      targetPort: 8888
```

### 8.1 Guest IP, VMI IP, and Service IP

When the default Pod network is combined with `masquerade`, three types of addresses appear simultaneously and should not be conflated:

| Address | Example | Meaning | Stability |
| --- | --- | --- | --- |
| Guest internal address | `10.0.2.2` | Assigned to the Guest by KubeVirt's built-in DHCP, inside the NAT | Valid for the current VMI lifecycle |
| VMI `IP` | `10.42.x.x` | `virt-launcher` Pod IP; cluster workloads reach it through Masquerade forwarding | May change after VMI recreation |
| Service ClusterIP | `10.43.x.x` | Stable virtual IP of the Kubernetes Service, forwarding to the current `virt-launcher` Endpoint | Stable for the lifetime of the Service |

KubeVirt Masquerade hides the Guest behind the `virt-launcher` Pod and forwards traffic externally through the Pod IP; VM restart or migration may change the Pod IP, so the fixed entry point should use a Service. Reference: [KubeVirt Interfaces and Networks](https://kubevirt.io/user-guide/network/interfaces_and_networks/), [KubeVirt Service Objects](https://kubevirt.io/user-guide/network/service_objects/)

When the `kubectl get vmi` of `IP` is empty, troubleshoot in the following order:

```bash
kubectl -n notebook-alice get vmi alice-gpu-workstation -o wide
kubectl -n notebook-alice describe vmi alice-gpu-workstation
kubectl -n notebook-alice get pod -l kubevirt.io=virt-launcher -o wide
virtctl console -n notebook-alice alice-gpu-workstation
```

Judgment rules:

1. `virt-launcher` has a Pod IP, but the VMI `status.interfaces` has no address: enter the Guest and check DHCP, Netplan, and cloud-init;
2. `AgentConnected=True`, the interface exists but has no address: prioritize checking stale MAC, wrong interface name, and DHCP;
3. The Guest already has an address but the Service is unreachable: check Service selector, EndpointSlice, interface `ports`, and the Guest listening address;
4. The Service has Endpoints but the web page is unreachable: confirm inside the Guest that the service is listening on `0.0.0.0`, not only on `127.0.0.1`.

Service verification example:

```bash
kubectl -n notebook-alice describe service alice-notebook
kubectl -n notebook-alice get endpointslice \
  -l kubernetes.io/service-name=alice-notebook

curl -I http://<cluster-ip>:8080/
curl -I http://<cluster-ip>:8888/
ssh alice@<cluster-ip>
```

ClusterIP can only be accessed from cluster nodes, Pods, or networks that can route the Service CIDR. Office computers need to enter through Gateway/Ingress, LoadBalancer, controlled NodePort, VPN, or a jump host; do not expose an unauthenticated Jupyter directly to the public internet just because ClusterIP is unreachable.

Do not expose unauthenticated Jupyter directly to the public internet, and do not store passwords or long-lived tokens in YAML. Notebook VMs should not hold cluster admin kubeconfig by default; when submitting formal jobs, use least-privilege platform APIs, short-lived credentials, or a separate Job submission identity.

## 9. Start/stop, idle reclamation, and environment reset

```bash
virtctl start -n notebook-alice alice-gpu-workstation
virtctl stop -n notebook-alice alice-gpu-workstation

kubectl -n notebook-alice get vm,vmi,pvc
```

After a successful stop, you should see:

- `VirtualMachine` still exists;
- `VirtualMachineInstance` disappears;
- The root disk PVC is still `Bound`;
- GPU resources return to the node's allocatable pool;
- After starting again, `/etc`, `/opt`, Conda, Python, Home, and caches still exist.

Idle Culler must not only check whether the web page is closed. It should also observe Jupyter Kernels, SSH/terminal processes, GPU utilization, and recent user activity; first warn, then gracefully shut down, and only force-stop after timeout. Formal training should be handed off to Job/TrainJob/RayJob, not by disabling the Culler to occupy a personal VM long-term.

The platform should provide at least four distinct operations:

1. **Stop**: release compute resources, retain all disks;
2. **Start**: remount the root disk on an available node and start;
3. **Reset system**: rebuild Root RBD from the golden image, by default retaining Workspace RBD;
4. **Delete account data**: delete Root/Workspace RBD after backup, retention period, and approval.

## 10. Snapshots, backup, and recovery

KubeVirt `VirtualMachineSnapshot` depends on CSI `VolumeSnapshot`. Live snapshots check the QEMU Guest Agent; when the Agent is available, the guest filesystem is frozen; when the Agent is missing, only a crash-consistent snapshot similar to sudden power loss can be obtained. Before important changes, the safest path is still to shut down first and then take a snapshot. Reference: [KubeVirt Snapshot Restore API](https://kubevirt.io/user-guide/storage/snapshot_restore_api/)

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

You must verify the `readyToUse` in the status, the included volume list, and whether the snapshot involved `GuestAgent` or is `NoGuestAgent`. Snapshots are not offline backups: a Ceph Pool failure, accidental snapshot deletion, or cluster-level incident can still affect both the original volume and the snapshot simultaneously. Critical user data should also be copied to an independent failure domain or backup system.

## 11. Node failure, fencing, and rescheduling

The high-availability goal for a personal Notebook is usually not seamless live migration, but rather:

```text
节点失联
  → 停止新 VM 调度到该节点
  → 确认旧节点已关机或隔离 Ceph/存储网络
  → 清理失联 VMI/Pod 状态
  → 在另一台兼容节点重新挂载同一 RBD
  → 冷启动 VM
  → 验证文件系统、GPU 与 Jupyter
```

The safety red line for Ceph RBD is to avoid the same writable volume appearing in two guests that may still be running. Simply marking a Kubernetes Node as `NotReady` does not necessarily prove that the original host has stopped writing to disk. BMC/IPMI, power control, Ceph-CSI network fencing, node isolation, and platform recovery Runbooks should be chained together. Rook's RBD documentation also requires confirming that the old node is offline before volume migration and application recovery in node-loss scenarios. Reference: [Rook RBD Block Storage](https://rook.io/docs/rook/latest-release/Storage-Configuration/Block-Storage-RBD/block-storage/), [RBD Application Migration](https://rook.io/docs/rook/latest-release/Storage-Configuration/Block-Storage-RBD/app-migration/)

GPU PCI Passthrough VMs are by default designed as "stop and cold start". Only when `VirtualMachineInstance` explicitly reports `LiveMigratable=True`, and storage, CPU, network, and all devices have passed migration drills, can live migration be written into the SLO. KubeVirt's regular live migration requires shared access capability, while RWO root disks and Host Devices often become constraints. Reference: [KubeVirt Live Migration](https://kubevirt.io/user-guide/compute/live_migration/)

## 12. Monitoring and capacity governance

| Layer | Key metrics and alerts |
| --- | --- |
| KubeVirt | VM/VMI status, startup failures, Guest Agent, stop duration, node schedulable labels |
| Host | KVM/VFIO, CPU Steal, memory, HugePages, IOMMU, hardware errors |
| Ceph RBD | Capacity, IOPS, throughput, P95/P99 latency, slow requests, degraded PGs, snapshot growth |
| Guest | Root disk/inode usage, logs, OOM, Jupyter status, SSH, NTP |
| GPU | Allocation, GPU memory, SM, power, temperature, XID, PCIe errors, ECC |
| Platform | Active users, Idle GPU Hours, startup time, snapshot success rate, recovery time |

The root disk should have tiered alerts at 70%, 85%, and 95%. The default cleanup policy may only delete caches and expired logs that are clearly rebuildable; it must not silently clean up user projects. After expansion, partition or filesystem expansion must also be completed inside the guest; the golden image should have the relevant tools pre-installed and verified.

Cost reports should show both the VM configured capacity and actual usage. RBD Thin Provisioning does not replace quotas; a large number of personal root disks, snapshots, and long-stopped VMs will still gradually fill the Ceph Pool.

## 13. Production acceptance experiments

### Host and scheduling

- [ ] All VM nodes pass `virt-host-validate qemu`;
- [ ] KVM, vhost, TUN, IOMMU, and VFIO still load correctly after reboot;
- [ ] VFIO GPU nodes are not accidentally used by container GPU workloads;
- [ ] VMs can only be scheduled to matching CPU/GPU node pools;
- [ ] Node drain, upgrade, and reboot have dedicated Runbooks.

### Persistence semantics

- [ ] Write test files to `/etc`, `/opt`, `/usr/local`, Home, and Conda default directories respectively;
- [ ] Install Python packages, IDE plugins, and system packages, then shut down and start again;
- [ ] Verify all files and service states still exist;
- [ ] After stopping the VM, GPU, CPU, and memory are actually released;
- [ ] Deleting a VM does not delete the user root disk without confirmation;
- [ ] When Root RBD is reset, Workspace RBD and object storage data are unaffected.

### Storage and recovery

- [ ] Concurrent golden image cloning does not overwhelm Ceph;
- [ ] Actually test Conda unpacking, Python Import, Git Checkout, and model caching;
- [ ] Root/Workspace RBD can be expanded and recognized inside the guest;
- [ ] Online snapshots involve the Guest Agent; offline snapshots can be restored;
- [ ] The restored VM can boot, mount disks, and recognize the GPU;
- [ ] Simulate node loss, complete fencing, then cold-start on another node;
- [ ] Prove that there is no double-mount, double-write, or old node resurrecting and writing to disk again.

### Security and product experience

- [ ] Users can only manage their own VMs, Console, Services, and snapshots;
- [ ] Jupyter entry point passes through OIDC, TLS, audit, and network policies;
- [ ] The guest does not hold cluster admin credentials;
- [ ] Users can distinguish between stop, restart, reset system, and delete data;
- [ ] Warning before idle shutdown; disks are retained after shutdown;
- [ ] Disk quotas, snapshot retention, and costs are visible to users.

## 14. Pros and cons review

### Advantages

- No longer relies on users following persistent directory conventions; the complete Linux state is transparently preserved;
- RBD does not require shared personal directories; isolation, independent expansion, snapshot, and recovery boundaries are clear;
- Expensive GPUs are released after shutdown while preserving the "personal workstation" experience;
- Supports systemd, apt, custom system libraries, and complex IDEs;
- Still leverages Kubernetes' Namespace, scheduling, quotas, API, and observability systems.

### Costs

- Startup, memory overhead, and resource density are typically inferior to containers;
- The platform must maintain guest OS patches, golden images, drivers, and environment drift;
- PCI GPU passthrough brings dedicated node pools, VFIO, and migration restrictions;
- Per-user root disks and snapshots continuously consume Ceph capacity;
- Node failure recovery must rely on reliable fencing, and cannot forcibly remount RBD;
- VMs solve "won't lose data," but do not automatically make experiments reproducible or formal training reliable.

## 15. Recommended Implementation Order

1. First complete the KVM, KubeVirt, CDI, and RBD root disk PoC on two GPU-less Workers;
2. Verify stop/resume, scaling, snapshots, reset, and node failure fencing;
3. Prepare a VFIO GPU node pool, complete single-card passthrough and guest driver testing;
4. Establish versioned Profiles for CPU, single GPU, and different memory and disk capacities;
5. Integrate OIDC, Gateway, Idle Culler, audit, quotas, and cost display;
6. Open "persistent workstation mode" to a small scope, coexisting with container Notebooks;
7. Uniformly hand over formal training to Job, TrainJob, RayJob, and queue systems;
8. After meeting recovery, capacity, and security gates, expand the user scope.

The final product does not need to choose between containers and VMs: standard users use fast-starting, easily reproducible container Notebooks; users who genuinely need to arbitrarily modify the system environment choose KubeVirt + RBD persistent workstations. Both share identity, data, model artifacts, and task submission entry points, but adopt different lifecycle and operational commitments.
