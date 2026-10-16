---
title: "KubeVirt Single-Node Desktop in Practice: Local Disks, CDI, and Browser noVNC"
description: "In a Kubernetes cluster without Ceph, confine KubeVirt VMs to a single node, use local disks to preserve the complete system environment, and access the desktop from a browser through a restricted noVNC gateway"
status: lab
last_reviewed: 2026-08-05
---

# KubeVirt Single-Node Desktop in Practice: Local Disks, CDI, and Browser noVNC

The hardest part of containerized Notebooks is not the Notebook files themselves, but the fact that users write Conda, Python, compilers, IDE plugins, system packages, and caches into arbitrary directories. The platform can mount `/home` or `/workspace`, but it is difficult to force every user to always write all state into a PVC. After a container is rebuilt, environments left behind in the image's writable layer are lost.

This hands-on exercise takes a different route: run a KubeVirt VM with a persistent root disk inside Kubernetes. Users modify the complete guest filesystem; stopping the VM releases CPU and memory, and starting it again restores the original environment. The experiment has no shared storage, so we first validate the full chain with Local LVM on a single node; when Ceph RBD is added later, the upper-layer VM, CDI, and access method can be kept and only the StorageClass replaced.

The following path was ultimately validated end to end:

```text
办公网浏览器
  → 节点地址:6080
  → 带 Basic Auth 的 noVNC/WebSocket 代理
  → virtctl VNC 子资源
  → KubeVirt VMI
  → Tiny Core 图形桌面
  → 节点本地 LVM DataVolume
```

This article uses only public project URLs and generic placeholders; it does not rely on any specific company's addresses, accounts, or passwords. `<...>` must be replaced with your own values, and versions and images should be pinned to verified tags or digests.

## 1. Scope and Boundaries

This approach is suitable for:

- Validating KubeVirt on a single KVM-capable node first, without touching other nodes;
- User environments that are "long-term modifiable Linux workstations," not just a few Notebook files;
- User personal root disks that do not need to be shared across multiple machines;
- No Ceph RBD is currently available, but nodes already have Local LVM, Local PV, or another local CSI;
- The office network can reach node addresses directly, so NodePort is not needed during the experiment phase.

It is not equivalent to a production high-availability solution:

- Local disks are bound to a node; when the node fails, the VM cannot automatically recover elsewhere;
- Local volumes usually cannot support VM live migration;
- `Retain` only reduces the risk of accidental deletion; it is not a backup;
- Direct browser access to node ports suits controlled office-network experiments; production entry points should still use HTTPS, unified authentication, and auditing;
- Tiny Core is only for quickly validating the desktop and VNC; it is not suitable as a formal development environment for Jupyter or code-server.

If Ceph RBD is already available, see [Building a Persistent GPU Notebook with KubeVirt and Ceph RBD](kubevirt-rbd-notebook.md) for the production design.

## 2. Understanding KubeVirt First: CRDs, Controllers, and the VM Runtime Chain

KubeVirt is not another virtualization platform independent of Kubernetes, nor does it replace Kubernetes nodes with a traditional hypervisor. Through CRDs, Controllers, Webhooks, and node DaemonSets, it turns virtual machines into a class of workload that the Kubernetes API can declare and reconcile. Networking is still provided by CNI, disks are still provided by CSI/PVC, and scheduling, quotas, priorities, ServiceAccounts, auditing, and Namespaces still follow Kubernetes conventions.

For official concepts and component descriptions, refer to [KubeVirt Architecture](https://kubevirt.io/user-guide/architecture/) and [Virtual Machines](https://kubevirt.io/user-guide/user_workloads/virtual_machines/).

It can be understood as four layers:

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

CRD stands for CustomResourceDefinition; its purpose is to add new resource types to the Kubernetes API. CRs are concrete objects of those types. Only after KubeVirt is installed does the API Server recognize resources such as `VirtualMachine` and `VirtualMachineInstance`. CRDs alone cannot run virtual machines; the actual reconciliation logic is executed by the KubeVirt Controller, Webhooks, and node components.

### 2.1 The Most Easily Confused: VM, VMI, and Pod

These three objects express different layers:

| Object | Analogy | Lifecycle | What It Mainly Stores |
| --- | --- | --- | --- |
| `VirtualMachine`, abbreviated VM | Long-term desired state like a Deployment | Can exist long-term; retained after stop | Power on/off policy, VM template, CPU/memory, volume and network declarations |
| `VirtualMachineInstance`, abbreviated VMI | A running Pod | Created on each start; deleted on stop | This run's instance, node, Guest IP, running conditions, and migration capability |
| `virt-launcher` Pod | The Pod hosting the process | Lives and dies with the VMI | QEMU/libvirt processes, volume mounts, tap/NAT, and Console/VNC sockets |

After creating a VM of type `runStrategy: Always`, the core chain is:

```text
VirtualMachine
  → virt-controller 创建 VirtualMachineInstance
  → virtualmachine-controller 创建 virt-launcher Pod
  → kube-scheduler 结合资源、亲和性和 PV nodeAffinity 选择节点
  → 目标节点 virt-handler 通知 virt-launcher 定义 libvirt domain
  → QEMU 打开 PVC/块设备，创建 tap，启动 guest OS
  → VMI status 回报节点、IP、Guest Agent 和 Ready 条件
```

Therefore:

- `kubectl get vm` answers "should this machine be powered on or off";
- `kubectl get vmi` answers "does a running instance currently exist";
- `kubectl get pod` answers "which node the QEMU process landed on, and why the container is Pending or exited";
- `virtctl stop <vm>` usually deletes the VMI and `virt-launcher`, but the VM and independent PVC continue to exist;
- Whether deleting the VM also deletes the disk depends on whether the disk is an independent PVC or is owned by the VM through mechanisms such as `dataVolumeTemplates`; this cannot be determined by name alone.

### 2.2 What the Common KubeVirt CRDs Actually Do

After installation you will see dozens of CRDs; not all of them need to be created directly by business users. Understanding them by responsibility is more effective than memorizing names:

| API Resource | Who Usually Creates It | Purpose and When to Use |
| --- | --- | --- |
| `KubeVirt` | Cluster administrator | Cluster-level installation instance; configures feature gates, node placement, allowed passthrough devices, and certificate policies. Usually only one per cluster |
| `VirtualMachine` | User or platform | Long-term VM definition; manages start, stop, and templates |
| `VirtualMachineInstance` | VM Controller; can also be created directly | One actual run. A normal platform should not make direct VMI creation the default, otherwise there is no long-term VM object to manage restarts |
| `VirtualMachineInstanceMigration` | Operations or migration controller | Requests VMI live migration; conditions such as local disks or PCI Passthrough GPUs may make it non-migratable |
| `VirtualMachineInstanceReplicaSet` | Platform | Maintains a group of homogeneous VMIs; semantics similar to ReplicaSet; usually not needed for personal workstations |
| `VirtualMachinePool` | Platform | Manages a group of VMs and replicas; suited to VM pools rather than single-user pet workstations |
| `VirtualMachineSnapshot` / `VirtualMachineRestore` | User or backup platform | Coordinates VM configuration with CSI volume snapshots and restore; still depends on CSI Snapshot capability underneath |
| `VirtualMachineExport` | User or image platform | Downloads VM, PVC, or snapshot content through a temporary export service |
| `VirtualMachineInstancetype` / `ClusterInstancetype` | Platform administrator | Reuses CPU, memory, and other specifications; similar to cloud host Flavors |
| `VirtualMachinePreference` / `ClusterPreference` | Platform administrator | Reuses machine type, disk bus, firmware, and other preferences; divides responsibilities with Instancetype |
| `VirtualMachineTemplate` | Template platform in newer KubeVirt versions | Organizes VMs and related resources into parameterized templates; whether it is deployed by default depends on the KubeVirt version |

First check what the cluster actually has installed; do not guess based on another article:

```bash
kubectl api-resources --api-group=kubevirt.io
kubectl get crd | grep -E 'kubevirt.io|cdi.kubevirt.io'
kubectl explain virtualmachine.spec
kubectl explain virtualmachineinstance.status.conditions
```

The `KubeVirt` CR is not the same thing as a business VM. The former is continuously reconciled by the Operator and is used to install and configure the entire virtualization control plane; the latter is a user workload inside a Namespace. Modifying the `KubeVirt` CR may roll the entire control plane or change the behavior of all VMIs; permissions should be granted only to cluster administrators.

### 2.3 Resident Components and On-Demand Components

KubeVirt's resident components are responsible for "management"; only running VMs produce real QEMU workloads:

| Component | Form | Responsibility |
| --- | --- | --- |
| `virt-operator` | Deployment | Installs, upgrades, rolls back, and reconciles KubeVirt CRs |
| `virt-api` | Deployment + APIService/Webhook | Provides admission, validation, and subresource APIs such as Console, VNC, and start/stop |
| `virt-controller` | Deployment | Reconciles VMs, VMIs, migrations, snapshots, and `virt-launcher` Pods |
| `virt-handler` | DaemonSet | One per node that can run VMs; connects to the libvirt/QEMU lifecycle on the node |
| `virt-launcher` | One Pod per active VMI | Hosts the QEMU/libvirt processes for that VMI; not a resident control plane |
| `virt-exportproxy` / `virt-exportserver` | Resident entry point + on-demand service | Handles VM/PVC/snapshot export; when there are no export tasks, the export server should not be counted as resident VM overhead |

When troubleshooting, first determine which layer the problem belongs to: the VM Controller did not create the VMI, the scheduler did not schedule the Pod, CSI did not bind the PVC, virt-handler did not sync the domain, or the guest itself did not start services. Looking only at one `kubectl get vm` status is often not enough.

### 2.4 What Is CDI, and Why Does It Often Appear Together with KubeVirt

CDI stands for Containerized Data Importer; it is an independent storage data preparation project in the KubeVirt ecosystem. KubeVirt itself is good at "starting a VM from an already-prepared disk," but it will not do the following for you:

- Download Ubuntu QCOW2/RAW images over HTTP and write them into a PVC;
- Import `containerDisk`-style disk content from an OCI Registry;
- Receive local images uploaded via `virtctl image-upload`;
- Clone a user's independent root disk from an existing PVC or `VolumeSnapshot`;
- Create blank disks and prevent the VM from starting too early before data preparation completes.

CDI introduces `DataVolume` for this purpose. You can think of a DataVolume as "a PVC upper-layer object with a data source and preparation status":

```text
DataVolume
  ├─ source：http / registry / upload / pvc / snapshot / blank
  ├─ storage：StorageClass / accessModes / volumeMode / size
  ├─ 目标 PVC
  └─ status：Pending / ImportInProgress / CloneInProgress / Succeeded
```

Minimal import example:

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

The CDI Controller creates or populates the target PVC; the Importer/Cloner/Upload Server are Pods that appear per task. After data preparation completes, these temporary Pods disappear, and the VM ultimately consumes only the PVC; CDI is not on the data path for every guest disk read/write, so it is not a long-running I/O proxy.

The complete source types and behaviors are defined by [Containerized Data Importer](https://kubevirt.io/user-guide/storage/containerized_data_importer/).

CDI itself also has several types of CRDs:

| CDI Resource | Purpose |
| --- | --- |
| `CDI` | Operator-managed cluster-level installation and configuration object |
| `CDIConfig` | CDI runtime configuration and capability status |
| `DataVolume` | Declares the data source, capacity, and preparation flow for the target volume |
| `DataSource` | Provides a stable reference for golden images; can switch to a new PVC or Snapshot in the background |
| `StorageProfile` | Records each StorageClass's default access mode, volume mode, snapshot class, and clone strategy |
| `ObjectTransfer` | Transfers DataVolume/PVC ownership across Namespaces in specific scenarios |

### 2.5 Why CDI Cloning Is Sometimes Fast and Sometimes Takes a Long Time to Copy

CDI selects a clone strategy by combining `StorageProfile` with CSI capabilities:

| Strategy | Data Path | Advantages | Risks and Prerequisites |
| --- | --- | --- | --- |
| CSI Volume Clone | Storage driver natively clones the PVC | Usually fastest; data does not traverse the Pod network | CSI must correctly implement writable cloning, topology, and expansion |
| CSI Snapshot Clone | Snapshot first, then restore the PVC from the snapshot | Suited to golden images and batch derivation | Snapshot restore must produce a writable volume; consistency still requires guest freeze/shutdown cooperation |
| Host-assisted Copy | A Source Pod reads the source volume; an Upload/Clone Pod writes the target volume | Does not depend on storage-native cloning; broad compatibility | Actually reads and writes disks, consuming network, CPU, and I/O; dozens of concurrent copies can overwhelm HDDs |

This Local LVM experiment validated a very important boundary: `VolumeSnapshot ReadyToUse=True` only indicates that the snapshot object is ready; it does not guarantee that "the restored PVC is necessarily suitable as a writable VM root disk." The PV actually restored carried a read-only attribute, and QEMU ultimately reported the root disk as a read-only filesystem. After forcing CDI to switch to host-assisted copy, compatibility issues with the storage driver's filesystem overhead rounding and Block device permissions were also exposed.

Therefore, before creating user VMs in batch, you must first run a complete canary:

1. Stop or freeze the golden VM, and create a Snapshot;
2. Restore an independent target PVC;
3. Check the PV's `volumeMode`, `nodeAffinity`, CSI `volumeAttributes`, and read-only flags;
4. Start the VM, actually create files on the guest root disk, and reboot;
5. Delete the canary and confirm the underlying volume is correctly reclaimed;
6. Then decide whether batch creation should use native snapshots, CSI Clone, CDI Copy, or a new RAW/QCOW2 generated by the image pipeline.

Do not create 50 clones at once and only then verify whether the first one can write to disk. For local HDDs, host-assisted copy should also limit concurrency; for Ceph RBD, you must verify snapshot layering, flatten, depth, reclamation, and failure-domain behavior.

### 2.6 What Goes into PVC, DataVolume, containerDisk, and cloud-init Respectively

| Mechanism | Persistent | Typical Use | Responsibilities It Should Not Assume |
| --- | --- | --- | --- |
| PVC | Yes | VM root disk, data disk; ultimately provided by CSI as a block device or file system | Does not describe where the image comes from |
| DataVolume | Target PVC persistent, preparation Pod temporary | Import, upload, clone, and initialize PVCs | Does not replace CSI, nor does it proxy disk I/O long term |
| `containerDisk` | Tied to image/Pod, can be treated as a read-only distribution medium | Smoke test, read-only system disk, installation medium | Persisting user modifications over time |
| `cloudInitNoCloud` | Boot configuration medium; content comes from VM definition/Secret | First-boot user, SSH key, hostname, network, and initialization scripts | Storing large amounts of data or serving as a continuous configuration management system |
| `emptyDisk` / ephemeral | No | Temporary scratch, one-off tests | User environment and important results |

`containerDisk` is a disk file inside an OCI container image; it does not mean "all VM disks become container images." Ubuntu ISO, QCOW2, and RAW are also not the same thing: ISO is typically an installation medium; QCOW2 is a disk format that supports sparse allocation, compression, and snapshot metadata; RAW is closer to direct block content, possibly sparse in size but with a simpler write path. CDI can handle format detection and conversion, ultimately writing to a PVC.

### 2.7 Why Scheduling Simultaneously Sees VM, Pod, and PVC Pending

A VM ultimately becomes an `virt-launcher` Pod, so the scheduler must simultaneously satisfy:

- The VM's CPU, memory, extended resources, Node Selector, Affinity, and Toleration;
- The KVM, network, and device conditions automatically added by KubeVirt;
- The PVC's availability zone and PV `nodeAffinity`;
- The `WaitForFirstConsumer` topology decisions for Local Storage;
- Scheduling conditions for temporary Pods such as CDI Importer/Cloner.

When using local disks, WFFC forms a process that looks circular but is intentionally designed: the PVC is Pending first, waiting for the real consumer to expose the target node; after the scheduler selects a node, CSI creates the volume on that node. The troubleshooting order should be:

```bash
kubectl -n <ns> get vm,vmi,pod,dv,pvc -o wide
kubectl -n <ns> describe vmi <name>
kubectl -n <ns> describe pod <virt-launcher-pod>
kubectl -n <ns> describe pvc <pvc>
kubectl -n <ns> get events --sort-by=.lastTimestamp
```

If the VMI is Pending, do not just add resources to the VM; first confirm whether it is the scheduler, PVC topology, CDI temporary Pod, or KubeVirt node capability that is waiting.

### 2.8 Where KubeVirt Manager Sits in the Architecture

KubeVirt Manager is a browser-based management interface, not a new hypervisor, and does not replace `virt-controller`. It reads or modifies the CRDs above through a ServiceAccount and the Kubernetes API, and calls sub-resources such as Console/VNC. Therefore, how many Namespaces the UI can see, whether it can delete disks or modify cluster objects, ultimately depends on its Kubernetes RBAC.

Installation, authentication, and WebSocket entry configuration can be found in the [KubeVirt Manager documentation](https://docs.kubevirt-manager.io/).

For experimental environments, the official bundled manifest can be used for quick installation, but before going live, at minimum check:

- Whether the Deployment's image tag/digest, Pod labels, and Service selector are consistent;
- Which ClusterRoles the ServiceAccount is bound to, and whether they far exceed the actual management scope;
- Whether HTTP Basic/OIDC is enabled and whether the entry uses HTTPS;
- Whether Ingress/Gateway correctly proxies VNC and XTerm WebSocket;
- Whether the management endpoint is only exposed to the office network or management network;
- "Front-end login authentication" and "Kubernetes API authorization" are two layers of control; neither can be done alone.

KubeVirt Manager is suitable for administrators and lab operations; a multi-user Notebook Portal should still implement user-to-VM ownership mapping, quotas, maximum concurrent startup count, idle shutdown, deletion protection, and auditing.

## 3. Experimental Components

| Component | Role | This Selection |
| --- | --- | --- |
| KubeVirt | Manage VM/VMI in Kubernetes | Operator + KubeVirt CR |
| CDI | Import images, clone PVCs, create blank DataVolumes | Usable even without Ceph |
| Local CSI | Provide persistent block devices or file system volumes for VMs | `WaitForFirstConsumer`'s Local LVM StorageClass |
| Tiny Core ISO | Quickly verify graphical boot, keyboard/mouse, and VNC | Smoke test only |
| `virtctl` | Console, VNC, and VM lifecycle client | Version matched with KubeVirt |
| noVNC + websockify | Convert VNC to a browser-accessible WebSocket | Standalone, least-privilege proxy Pod |

KubeVirt's `containerDisk` changes with the Pod lifecycle and is not suitable for preserving a root file system that requires long-term modification. Persistent state should be written to DataVolume/PVC. See [KubeVirt disks and volumes](https://kubevirt.io/user-guide/storage/disks_and_volumes/).

## 4. Pre-checks

### 4.1 Node Virtualization Capability

Run the following read-only checks only on candidate nodes:

```bash
# Intel 通常出现 vmx，AMD 通常出现 svm，结果应大于 0
grep -Ec '(vmx|svm)' /proc/cpuinfo

ls -l /dev/kvm /dev/vhost-net /dev/net/tun
lsmod | grep -E 'kvm|vhost'
```

Also confirm:

- BIOS/UEFI has VT-x/VT-d or AMD-V/AMD-Vi enabled;
- The node is not a VM that forbids nested virtualization, or the upper layer has correctly enabled nested virtualization;
- Kubernetes, containerd/CRI-O, and the target KubeVirt version are within the supported range;
- CNI, DNS, and node time synchronization are normal;
- Pod Security, SELinux, or AppArmor will not block the permissions KubeVirt requires.

Before installation, check [KubeVirt releases](https://github.com/kubevirt/kubevirt/releases) and the support information for the corresponding version; do not treat the experimental version in this article as a long-term fixed version.

### 4.2 Local StorageClass

```bash
kubectl --context <context> get storageclass
kubectl --context <context> get storageclass <local-storage-class> -o yaml
```

For local disk experiments, prefer:

- `volumeBindingMode: WaitForFirstConsumer`, creating the volume only after the VM scheduling decision is made;
- Reclaim policy of `Retain`, to avoid immediately reclaiming underlying data after PVC deletion;
- CSI can pin the volume to the actual node via PV `nodeAffinity`;
- Existing capacity, disk health, and volume utilization monitoring.

The `Immediate` mode may first create the volume on another node, after which the VM stays Pending forever due to node selection conflicting with volume affinity.

## 5. Restricting VMs to a Single Node

First add a dedicated label to the experimental node:

```bash
kubectl --context <context> label node <vm-node> \
  kubevirt.io/test-host=true --overwrite
```

After installing KubeVirt, configure two layers of restriction in the KubeVirt CR:

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

Where:

- `workloads.nodePlacement` restricts node-side workloads such as `virt-handler`;
- `developerConfiguration.nodeSelectors` adds a default node selector for VMIs;
- Each experimental VM should still explicitly write the same `nodeSelector` so the intent is directly visible from the resource manifest;
- `virt-api`, `virt-controller`, and the Operator belong to the control plane and can run on other suitable nodes; the actual VMI/`virt-launcher` remains restricted to the experimental node.

When verifying, do not just look at the VM status; also check the node where the actual Pod is running:

```bash
kubectl --context <context> -n kubevirt get pods -o wide
kubectl --context <context> -n <vm-namespace> get pods -o wide
```

VMs and ordinary Pods can run on the same node simultaneously. KubeVirt VMs are ultimately carried by `virt-launcher` Pods and still participate in Kubernetes scheduling and resource accounting. In production, if contention is a concern, add ResourceQuota, PriorityClass, CPU Manager, Topology Manager, taints, and dedicated node pools rather than assuming VMs will naturally isolate from ordinary Pods.

## 6. Installing KubeVirt and CDI

### 6.1 KubeVirt 1.7 vs 1.9: Why There Are More Control Plane Pods

The core architecture of KubeVirt 1.7 and 1.9 has not changed. The resident core components remain:

| Component | Deployment Method | Responsibility |
| --- | --- | --- |
| `virt-operator` | Deployment, usually two replicas | Install, upgrade, and continuously reconcile the KubeVirt control plane |
| `virt-api` | Deployment, usually two replicas | Provide VM/VMI sub-resources, admission, and APIs such as Console/VNC |
| `virt-controller` | Deployment, usually two replicas | Reconcile VMs, VMIs, migrations, snapshots, and related Pods |
| `virt-handler` | DaemonSet, one per virtualizable node | Manage libvirt/QEMU and VMI lifecycle on the node side |
| `virt-exportproxy` | Deployment, usually two replicas | Provide a stable entry point for VM, snapshot, and PVC export |

`virt-launcher` is not part of the resident control plane. Each running VMI creates its own `virt-launcher` Pod; after the VMI is stopped or deleted, that Pod also disappears. Similarly, the `virt-exportserver` that actually reads volume data is only created on demand when performing export tasks. When troubleshooting resource usage, separate "resident control plane" from "workloads created with VMs/tasks."

The most visible change after a default 1.9 installation is two additional resident Pods:

- `virt-template-apiserver`: provides native `VirtualMachineTemplate`-related APIs;
- `virt-template-controller`: reconciles templates, template requests, and their associated resources.

Native `VirtualMachineTemplate` was introduced in 1.8 as an Alpha feature requiring explicit enablement; in 1.9, it was promoted to Beta and enabled by default, so the Operator automatically deploys these two `virt-template` components. It can incorporate cluster resources and parameters such as networks, volumes, and DataVolumes into a reusable VM blueprint, complementing Instancetype/Preference, which mainly reuse CPU, memory, and device preferences. See [VirtualMachine Templates](https://kubevirt.io/user-guide/user_workloads/vm_templates/).

Do not use the KubeVirt major version number to judge whether these two images are "mixed." For example, KubeVirt `v1.9.0` pins `virt-template-apiserver:v0.2.2` and `virt-template-controller:v0.2.2`; `v0.2.2` is the independent version of the `virt-template` component itself. Let `virt-operator` manage this set of dependencies; do not manually replace images just to make version strings look consistent.

Below are the main operational differences between 1.7 and 1.9:

| Dimension | KubeVirt 1.7 | KubeVirt 1.9 | Actual Impact |
| --- | --- | --- | --- |
| Kubernetes baseline | Targets Kubernetes 1.34, supports the two previous minor versions | Targets Kubernetes 1.36, supports the two previous minor versions | Kubernetes 1.36/K3s 1.36 should choose 1.9; do not fall back to 1.7 just to reduce Pod count |
| Core control plane | Operator, API, Controller, Handler | Same as 1.7 | The basic VM scheduling and runtime path has not been replaced |
| Native VM Template | Not part of the default control plane | Beta, enabled by default | Typically one additional apiserver and one controller Pod |
| VM Export | Already has `virt-exportproxy`; it is not a new 1.9 component | VMExport promoted to GA, and can work with feature gates to export OCI and export VM Templates | Do not mistake exportproxy for a new process caused by version bloat |
| Beta feature gates | Disabled by default, must be explicitly enabled via `featureGates` | All Beta features enabled by default, opt out individually via `disabledFeatureGates` | Must audit default value changes before upgrading from 1.7; Alpha features remain disabled by default |
| AI/heterogeneous node capabilities | Already supports describing GPU and HostDevice via DRA | Adds GPU UUID and VMI association metrics, single-device vGPU live migration, etc.; Grace/IOMMUFD remain constrained by architecture, kernel, and feature gates | "API supports it" does not mean node hardware, IOMMU, drivers, and migration storage already meet the conditions |

Version dates, Kubernetes support ranges, and full changes are governed by [KubeVirt release notes](https://kubevirt.io/user-guide/release_notes/) and the [Kubernetes support matrix](https://github.com/kubevirt/sig-release/blob/main/releases/k8s-support-matrix.md). For the background of Beta features being enabled by default in 1.9 and considerations for cross-version upgrades from 1.7, see the official note [Beta Features Enabled by Default in KubeVirt v1.9](https://kubevirt.io/2026/Beta-Features-On-By-Default-In-v1-9.html).

You can directly observe which resident components the current version has deployed:

```bash
kubectl --context <context> -n kubevirt get deployment,daemonset
kubectl --context <context> -n kubevirt get pods -o wide
kubectl --context <context> get crd | grep -E 'template.kubevirt.io|kubevirt.io'
```

If the platform does not use native VM Templates at all, you can explicitly disable the template components to reduce two resident Pods. In production, first confirm there are no template objects or callers, then modify the KubeVirt CR:

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

It is not recommended to choose an older KubeVirt that does not support the current Kubernetes version merely to reduce component count. For 1.9, the more important step before going live is to audit the [feature gate report](https://github.com/kubevirt/kubevirt/releases/tag/v1.9.0) and clarify which Beta features should remain enabled by default and which should be opted out via `disabledFeatureGates`.

### 6.2 Pinning Versions and Installing

Pin versions that have passed compatibility validation; do not use floating addresses in production manifests:

```bash
export KUBEVIRT_VERSION='<validated-version>'

kubectl --context <context> apply -f \
  "https://github.com/kubevirt/kubevirt/releases/download/${KUBEVIRT_VERSION}/kubevirt-operator.yaml"
kubectl --context <context> apply -f \
  "https://github.com/kubevirt/kubevirt/releases/download/${KUBEVIRT_VERSION}/kubevirt-cr.yaml"

kubectl --context <context> -n kubevirt wait kubevirt kubevirt \
  --for=condition=Available --timeout=10m
```

Install the matching CDI:

```bash
export CDI_VERSION='<validated-version>'

kubectl --context <context> apply -f \
  "https://github.com/kubevirt/containerized-data-importer/releases/download/${CDI_VERSION}/cdi-operator.yaml"
kubectl --context <context> apply -f \
  "https://github.com/kubevirt/containerized-data-importer/releases/download/${CDI_VERSION}/cdi-cr.yaml"

kubectl --context <context> -n cdi get pods
```

CDI is decoupled from the backend storage: it handles importing, uploading, cloning, or initializing DataVolumes, and the underlying layer can be either Ceph RBD or local LVM. Not having Ceph does not prevent this experiment from creating blank persistent disks.

## 7. First Verify KVM and Console with CirrOS

Desktop systems involve storage, graphics, and WebSocket; troubleshooting them directly mixes problems together. First run a very small CirrOS VM to verify KVM, scheduling, and the serial console:

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

To exit `virtctl console`, use **Ctrl+]**. This is a control character: with the English input method active, hold Control and press `]` — it is not the string `Ctrl+]`. If the terminal client still cannot exit, terminating the local `virtctl` process is sufficient; this only disconnects the console and does not shut down the VM.

## 8. Creating a Local Persistent Disk

Below, create a 40 GiB blank DataVolume. 8 GiB is enough to validate Tiny Core, but Ubuntu, Conda, model caches, and IDE plugins will quickly fill it up. For a production workstation, start with 80–200 GiB and set quotas according to team data volume.

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

It is normal for a DataVolume to remain in the `WaitForFirstConsumer` state when there is no consumer. After creating a VM with a target node selector, the scheduler will trigger volume creation. After binding, check whether the PV's `nodeAffinity` points to `<vm-node>`.

## 9. Validating the Desktop with Tiny Core

Obtain the ISO from the [Tiny Core Linux download page](http://www.tinycorelinux.net/downloads.html) and verify the hash published on the official site. Wrap the ISO into a KubeVirt `containerDisk`:

```dockerfile
FROM scratch
ADD --chown=107:107 TinyCore-current.iso /disk/disk.img
```

```bash
docker build -t <registry>/lab/tinycore-container-disk:<tag> .
docker push <registry>/lab/tinycore-container-disk:<tag>
```

The `<registry>` here is an OCI Registry accessible from the lab environment. In production, pin the image digest, generate an SBOM, and complete vulnerability scanning.

Create the desktop VM:

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

On first boot, the blank root disk has no operating system, so the firmware will continue booting from the ISO. Seeing the desktop at this point only proves that the graphics path works — **it does not mean the system state has been written to the persistent disk**. You must run the installer inside the guest to write the system to `desktop-root`, then remove the ISO or adjust the boot order. If you only run the Live ISO, operating-system-level changes will still be lost after reboot.

## 10. Browser Access: Least-Privilege noVNC Proxy

`virtctl vnc` is designed for local clients by default. To access it from a browser, you can build a small proxy image containing only the matching-version `virtctl`, noVNC, and websockify:

```text
浏览器 /vnc.html
  → websockify :6080
  → virtctl vnc --proxy-only 127.0.0.1:5900
  → Kubernetes VMI VNC subresource
```

The proxy startup logic should have two characteristics:

1. Loop-restart after `virtctl vnc --proxy-only` exits, so the browser can reconnect after a disconnect;
2. Do not use `nc -z 127.0.0.1 5900` to probe the VNC port.

The second point is critical. `virtctl`'s proxy-only mode serves only one VNC connection at a time, and `nc -z` itself consumes that connection, causing the real noVNC client to subsequently receive `Connection refused`. The health check should probe websockify's listening port 6080, not connect to 5900.

The proxy ServiceAccount only needs VMI read and VNC subresource permissions within the current namespace:

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

Do not store actual passwords in YAML or Git. Generate a random password first, then create the Secret:

```bash
NOVNC_PASSWORD="$(openssl rand -hex 16)"

kubectl --context <context> -n kubevirt-lab create secret generic tinycore-novnc-auth \
  --from-literal=username=vmuser \
  --from-literal=password="${NOVNC_PASSWORD}"

printf 'noVNC user: vmuser\nnoVNC password: %s\n' "${NOVNC_PASSWORD}"
```

The key configuration of the proxy Deployment is as follows:

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

The core command of the proxy entry script can be written as:

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

`hostNetwork` allows the office network to access it directly:

```text
http://<vm-node-ip>:6080/vnc.html?autoconnect=1&resize=scale
```

No NodePort is created here. Because the fixed port 6080 on the same node cannot be occupied by both the old and new Pods simultaneously, the Deployment must use `Recreate`; the default `RollingUpdate` may cause updates to hang indefinitely. The readiness probe uses a TCP probe; it cannot use an HTTP GET without credentials, because Basic Auth would return 401 and the Pod would remain in a not-ready state.

Basic Auth is only suitable for a PoC on a controlled network, and plaintext HTTP cannot protect passwords. In production, at minimum switch to HTTPS and integrate OIDC, short-lived authorization, auditing, and network policies through Ingress/Gateway. The firewall should only allow office-network CIDRs to access that node port.

## 11. How to Verify the Path Actually Works

### 11.1 VM, Scheduling, and Storage

```bash
kubectl --context <context> -n kubevirt-lab get vm,vmi,pod -o wide
kubectl --context <context> -n kubevirt-lab get dv,pvc
kubectl --context <context> get pv <pv-name> -o yaml
```

Acceptance points:

- VM and VMI are Running/Ready;
- `virt-launcher` is on `<vm-node>`;
- DataVolume succeeded, PVC is Bound;
- PV `nodeAffinity` matches the VM node;
- In VMI conditions, `LiveMigratable=False` caused by the local disk is the expected result.

### 11.2 noVNC

```bash
kubectl --context <context> -n kubevirt-lab get deploy,pod -l app=tinycore-novnc -o wide
kubectl --context <context> -n kubevirt-lab logs deploy/tinycore-novnc

curl -u 'vmuser:<password>' -I 'http://<vm-node-ip>:6080/vnc.html'
```

Page requests should return 200, and the browser WebSocket should complete a 101 Switching Protocols handshake. If the HTML loads but the top shows "Unable to connect to server," check the proxy logs and the 5900 connection lifecycle rather than first suspecting the guest password.

## 12. Common Troubleshooting

| Symptom | Common Cause | Resolution |
| --- | --- | --- |
| VMI stuck in Pending | Node lacks KVM, label mismatch, insufficient resources | Check VMI Events, `virt-handler`, and node devices |
| DataVolume/PVC Pending | `WaitForFirstConsumer` has no VM consumer yet | Create the VM and observe again; check StorageClass and scheduling events |
| Volume conflicts with VM node | StorageClass uses `Immediate` or PV already bound elsewhere | Use WFFC; confirm data disposition before recreating lab volumes |
| Browser refuses to connect to 6080 | Proxy Pod not running, hostPort not listening, or firewall blocking | Check Pod, node listening state, and office-network ACL |
| noVNC page shows unable to connect | `virtctl` has exited, or the health check consumed the single-connection VNC proxy | Remove the `nc -z` probe on 5900; loop-restart `virtctl` |
| Proxy Pod never becomes ready | HTTP readiness returns 401 from Basic Auth | Switch to 6080 TCP readiness |
| Deployment update stuck | Old and new Pods contend for hostPort during RollingUpdate | Use `strategy.type: Recreate` |
| Console cannot exit | Correct control character not sent | Press Ctrl+] with English input method, or terminate the local client process |
| Changes lost after VM reboot | Still booting from Live ISO; system not installed into DataVolume | Complete guest installation and boot from the persistent root disk |

## 13. How to Choose Between Jupyter Notebook and code-server Images

First, distinguish between "container application images" and "VM system images."

### 13.1 Running Only Containerized Notebook

| Scenario | Recommended Starting Point | Description |
| --- | --- | --- |
| Minimal JupyterLab | `quay.io/jupyter/base-notebook:<date-or-sha>` | Relatively small; suitable for building derived images from a project Lockfile |
| Common Python data science | `quay.io/jupyter/scipy-notebook:<date-or-sha>` | Common stack including NumPy, pandas, SciPy, etc.; suitable as the default for most CPU Notebooks |
| PyTorch + NVIDIA GPU | `quay.io/jupyter/pytorch-notebook:cuda12-<pinned-tag>` | CUDA variant of the official Docker Stacks; verify driver and CUDA compatibility before use |
| NVIDIA-optimized PyTorch | `nvcr.io/nvidia/pytorch:<pinned-release>-py3` | Suitable for GPU environments that value NVIDIA optimization libraries; the image includes JupyterLab, but startup and security configuration require explicit platform management |

Jupyter Docker Stacks now publishes new images only to Quay.io, JupyterLab is the default frontend, and pinning a date or Git SHA tag is recommended for reproducibility. Do not continue treating the old `jupyter/*` on Docker Hub as an update source. See [Jupyter Docker Stacks](https://jupyter-docker-stacks.readthedocs.io/en/latest/) and [image selection notes](https://jupyter-docker-stacks.readthedocs.io/en/latest/using/selecting.html). For NVIDIA images, see [NGC PyTorch](https://catalog.ngc.nvidia.com/orgs/nvidia/containers/pytorch).

### 13.2 Running Only Containerized code-server

Use the official image:

```text
codercom/code-server:<pinned-version>
```

The official image supports amd64 and arm64. Persist at least `/home/coder/.local`, `/home/coder/.config`, and the project directory, and expose it through an HTTPS reverse proxy; code-server depends on WebSocket. Refer to the [code-server installation documentation](https://coder.com/docs/code-server/install) and [secure access notes](https://coder.com/docs/code-server/guide).

Do not confuse `ghcr.io/coder/coder` with `codercom/code-server`: the former is the control service of Coder, a multi-user development environment platform, while the latter is the VS Code service in the browser.

### 13.3 When Both Jupyter and code-server Are Needed, and the Environment Must Be Fully Preserved

The default choice for this article's scenario is not to cram both services into a single application container, but rather:

```text
Ubuntu 24.04 LTS QCOW cloud image（或经过 GPU 兼容验证的 Ubuntu 22.04 LTS）
  → CDI 导入并克隆为每用户独立根盘
  → cloud-init 创建用户、SSH key 和初始配置
  → 在 VM 内安装 Miniforge/Micromamba、JupyterLab、code-server
  → systemd 分别管理两个服务
  → 完整 / 根盘由 DataVolume 持久化
```

This way, everything the user later writes to `apt`, `pip`, Conda, VS Code extensions, or arbitrary scripts — into `/home`, `/opt`, `/usr/local`, `/var` — is saved with the VM root disk. The code-server official FAQ also recommends providing each user a VM in multi-tenant scenarios and explicitly mentions that KubeVirt on Kubernetes can provide a VM-like experience. Refer to the [code-server FAQ](https://coder.com/docs/code-server/FAQ).

Image selection recommendations:

- For CPU development environments, default to the Ubuntu 24.04 LTS QCOW cloud image; choose a release from the [Ubuntu public images](https://cloud-images.ubuntu.com/releases/noble/release/), verify the SHA256, and import the DataVolume via CDI. Do not follow the ever-changing daily/current files in production;
- For GPU passthrough environments, the choice is determined jointly by the guest NVIDIA driver, CUDA Toolkit, and framework versions; choose between Ubuntu 22.04/24.04 based on the actual compatibility matrix;
- Golden images should only preinstall stable system dependencies, QEMU Guest Agent, security patches, and platform agents; frequently changing Python project dependencies should still be saved with `environment.yml`, `requirements.lock`, `uv.lock`, or containers;
- Use different ports for Jupyter and code-server, independent systemd units, and a unified identity entry point; do not disable tokens/passwords and expose directly to the network;
- Record the source URL, SHA256, build script, SBOM, and release date for golden images, and rebuild them on a schedule; do not manually maintain a "pet image" that is never upgraded.

If the goal is only standardized teaching or short-term experiments, container images + PVC are lighter and faster; if the core problem is precisely that users install environments in arbitrary directories, a persistent VM root disk truly covers the problem boundary.

## 14. VM Internal DNS: Why the Host Can Access It but the VM Fails to Resolve

When a KubeVirt VM uses the default Pod network and the `masquerade` interface, the guest does not directly inherit the host's `/etc/resolv.conf`. The typical resolution path is:

```text
guest 应用
  → systemd-resolved 或 guest resolver
  → KubeVirt DHCP 下发的 Kubernetes DNS Service IP
  → masquerade 网关，例如 10.0.2.1
  → kube-dns/CoreDNS ClusterIP
  → CoreDNS Pod
  → 企业 DNS 或公共上游 DNS
```

Therefore, "the host can `curl`, but the VM cannot" cannot be directly attributed to enterprise DNS. The host may query enterprise DNS directly, while the VM first depends on the Kubernetes Service VIP; between the two paths lie the guest NIC, KubeVirt NAT, the `virt-launcher` network namespace, and CNI Service load balancing.

### 14.1 Evidence Chain from a Real Incident

The following phenomena occurred in this experiment; addresses and domain names have been generalized:

| Check Location | Result | Description |
| --- | --- | --- |
| Host queries `<internal-fqdn>` | Enterprise DNS returns internal IP | Enterprise DNS records are normal |
| Host `curl http://<internal-fqdn>` | Received HTTP 403 | The network already reached the target; 403 is application authorization, not DNS or connection failure |
| VM `/etc/resolv.conf` | Points to `127.0.0.53` | This is systemd-resolved's local stub, not the real upstream DNS |
| VM `resolvectl status` | Upstream is `<kube-dns-cluster-ip>` | KubeVirt DHCP passes the Pod's ClusterFirst DNS to the guest |
| VM to `<kube-dns-cluster-ip>:53` | TCP/UDP timeout | The fault point is on the path from the VM to the Kubernetes Service VIP |
| VM to both CoreDNS Pod IPs | Ports reachable | CoreDNS processes and Pod network are not entirely down |
| VM to both enterprise DNS IPs | Ports reachable | The guest's default route and enterprise DNS ACL are normal |
| VM temporarily switched to enterprise DNS | Resolution succeeds, HTTP 403 | Further proves the problem is not the domain record but the kube-dns ClusterIP path |

First confirm the real upstream on the host:

```bash
cat /etc/resolv.conf
getent hosts <internal-fqdn>
curl -I --connect-timeout 5 "http://<internal-fqdn>/"
```

Then check inside the guest:

```bash
cat /etc/resolv.conf
resolvectl status
ip route

getent hosts <internal-fqdn>
timeout 3 bash -c '</dev/tcp/<kube-dns-cluster-ip>/53'
timeout 3 bash -c '</dev/tcp/<corp-dns-1>/53'
timeout 3 bash -c '</dev/tcp/<corp-dns-2>/53'
```

Finally inspect the cluster DNS and CNI; do not repeatedly modify `/etc/hosts` only inside the guest:

```bash
kubectl -n kube-system get service kube-dns -o wide
kubectl -n kube-system get pod -l k8s-app=kube-dns -o wide
kubectl -n kube-system get configmap coredns -o yaml
kubectl -n kube-system get configmap cilium-config -o yaml
```

If CoreDNS uses `forward . /etc/resolv.conf`, and the CoreDNS Pods also use `dnsPolicy: Default`, then non-`cluster.local` queries will typically be forwarded to the node's enterprise DNS. In that case, there is no need to add static records to the CoreDNS `hosts` plugin for every internal domain; first fix the path from the VM to the DNS service.

### 14.2 Single VM: Directly Specify Enterprise DNS

For VMs that only need to access enterprise services and do not require Kubernetes Service name resolution, the minimal change is to explicitly set DNS in the VM template:

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

`dnsPolicy: None` is important. With `ClusterFirst`, merely appending `dnsConfig.nameservers` may still leave an unreachable kube-dns listed first, causing every query to wait for a timeout first. VM template changes only affect newly created `virt-launcher`/VMI instances; existing VMIs require a scheduled restart.

You can also override DHCP DNS inside the Ubuntu guest. Here is a persistence example:

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

VM template configuration is better suited for platform-wide unified management; guest Netplan is suitable for validation or for preserving a workstation's own DNS policy. Do not directly edit `/etc/resolv.conf` managed by systemd-resolved—it is usually a symbolic link and will be overwritten after reboot or DHCP lease renewal.

The cost of using enterprise DNS directly is that `*.svc.cluster.local` cannot be resolved. If a VM needs both enterprise domains and Kubernetes Service domains, the priority should be to fix the CNI Service path or use NodeLocal DNS, rather than pinning the CoreDNS Pod IP in the template; Pod IPs change with rolling upgrades and failure recovery.

### 14.3 Cluster-level fix: check Cilium kube-proxy replacement

The failed cluster in this incident was not running kube-proxy; Cilium eBPF handled ClusterIP instead:

```yaml
kube-proxy-replacement: "true"
```

KubeVirt guest connections originate from QEMU/tap, pass through the NAT of `virt-launcher`, and then enter the CNI. Unlike ordinary Pod processes that make socket calls directly from the Pod cgroup, these connections may not hit the Service translation path that relies primarily on socket hooks. Cilium officially lists KubeVirt, Kata Containers, and gVisor as workloads that need to consider socket LB bypass, and provides the following configuration direction:

```yaml
socketLB:
  hostNamespaceOnly: true
```

This causes non-host-namespace traffic to bypass socket-level rewrite and handles the original ClusterIP at the tc layer. See [Cilium kube-proxy replacement: Socket LB bypass](https://docs.cilium.io/en/stable/network/kubernetes/kubeproxy-free/#socket-loadbalancer-bypass-in-pod-namespace).

If packet capture and Cilium monitor indicate that guest traffic is being identified as traffic from outside the cluster, also evaluate:

```yaml
bpf:
  lbExternalClusterIP: true
```

This switch expands the reachability boundary of ClusterIP and must not be enabled in production clusters merely to fix DNS. First verify NetworkPolicy, the security model, and Cilium configuration on all nodes, then validate on test nodes. The recommended order is:

1. Record the Cilium version, Helm values, routing mode, and kube-proxy replacement status;
2. Use `cilium-dbg monitor` or Hubble to observe where packet loss occurs from guest to the kube-dns ClusterIP;
3. Prioritize validating `socketLB.hostNamespaceOnly=true`;
4. Only when traffic is confirmed to be treated as external, evaluate `bpf.lbExternalClusterIP=true`;
5. Simultaneously regression-test ordinary Pod DNS, ClusterIP, NodePort, NetworkPolicy, and VM networking;
6. After validation passes, roll out Cilium updates incrementally and retain rollback values.

### 14.4 Multi-VM platform: NodeLocal DNSCache

When a platform needs to run a large number of Notebook VMs, a more stable structure is to deploy NodeLocal DNSCache on each node and have VMs query a stable node-local address:

```text
KubeVirt VM
  → 节点本地 DNS，例如 <node-local-dns-ip>
      ├─ cluster.local → CoreDNS
      └─ 其他域名 → 企业 DNS
```

This reduces cross-node DNS requests, avoids guests depending directly on the kube-dns ClusterIP, and preserves both Kubernetes Service and enterprise intranet domain resolution. Before rollout, still verify that KubeVirt masquerade guests can reach the selected node-local address, and observe behavior during cache failure, CoreDNS outage, and enterprise DNS switchover. See [Kubernetes NodeLocal DNSCache](https://kubernetes.io/docs/tasks/administer-cluster/nodelocaldns/).

It is recommended to include DNS in the golden image and VM platform acceptance process, rather than waiting until users fail to install Python packages:

- Test FQDN, short names, enterprise search domains, and `*.svc.cluster.local` separately;
- Test both UDP 53 and TCP 53 to avoid failures when large responses or truncation fall back to TCP;
- Verify DNS timeout and retry values to prevent unreachable nameservers from causing `apt`, `pip`, and Conda to hang for extended periods;
- Distinguish between NXDOMAIN, timeout, connection refused, and HTTP 401/403—they belong to completely different failure layers;
- Record whether DNS is managed by the VM template, guest Netplan, NodeLocal DNS, or CoreDNS, to avoid multiple configurations overwriting each other.

## 15. Fixed IP and Stable Access Entry Points

Before discussing KubeVirt fixed IPs, you must first confirm which layer needs to be fixed. With the default Pod network combined with `masquerade`, the guest, the `virt-launcher` Pod, and the office network entry point have different address semantics:

| Layer | Typical Address | Assigned By | Lifecycle and Reachability |
| --- | --- | --- | --- |
| Guest private network IP | `10.0.2.2` | KubeVirt built-in DHCP | Located in each VMI's independent NAT network; different VMs can reuse the same address, and the office network cannot treat it as a uniquely routable address |
| VMI/`virt-launcher` Pod IP | `<pod-cidr-address>` | Cluster primary CNI | In-cluster reachability depends on the CNI; may change after VMI recreation or migration and should not be written into user bookmarks or external DNS |
| Kubernetes Service IP | `<cluster-ip>` | Kubernetes | Stable for the lifetime of the Service, but usually only reachable within the cluster network |
| Office network entry IP/VIP | `<office-routable-vip>` | Enterprise network, load balancer, or Layer 2 IP advertisement system | User-facing stable entry point; can be bound to domains, TLS, and unified authentication |
| VM underlay IP | `<office-routable-vm-ip>` | Enterprise DHCP, static address, or underlay IPAM | Configured directly on the guest's second NIC; behaves most like a traditional VM, but carries the highest network rework and governance cost |

The current experiment uses:

```text
办公网或集群客户端
  → VMI Pod IP / Kubernetes Service
  → virt-launcher 网络命名空间中的 NAT
  → guest 10.0.2.2
```

`10.0.2.2` looks fixed, but it is only a private address within each VM's own NAT space. The `<pod-cidr-address>` visible in the VMI status is the Pod IP corresponding to the current run, but it is not a long-term identity either. KubeVirt officially recommends exposing `masquerade` workloads through Kubernetes Services, because a Service can continue to select new instances after a VMI hard reboot or migration changes the Pod IP. See [KubeVirt Interfaces and Networks](https://kubevirt.io/user-guide/network/interfaces_and_networks/).

### 15.1 Notebooks prefer fixed domain names over fixed guest IPs

JupyterLab and code-server are both HTTP/WebSocket applications and are well suited to using a fixed Gateway/Ingress VIP with domain-based forwarding to each VM's Service:

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

Each VM's Service only needs to select a stable domain label:

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

The Service's ClusterIP is not the same as the office network VIP. The full production path also requires a Gateway/Ingress Controller, an enterprise load balancer, or an address advertisement mechanism such as MetalLB to hand an office-network-routable address to the entry point. MetalLB allocates a Service VIP; it does not configure that IP on the guest NIC. For the conceptual explanation, see [MetalLB Concepts](https://metallb.io/concepts/).

The advantages of this approach:

- VM restart, recreation, and future migration do not require preserving the VMI Pod IP;
- Multiple users share a small number of VIPs, without consuming office network addresses for each Notebook;
- TLS, OIDC, access logs, rate limiting, and WebSocket can be governed uniformly;
- Users only remember domain names; the platform can replace VMs, Services, or storage implementations in the background.

SSH is not HTTP and is typically exposed through a unified SSH Bastion, TCP Gateway, or a controlled LoadBalancer Service. Do not connect every VM to the office network Layer 2 just to let browsers access Jupyter.

### 15.2 When a VM fixed IP is genuinely required: Multus dual NIC

Some scenarios genuinely require the guest to appear directly on the office network like a traditional VM—for example, legacy software licensing by source IP, network devices proactively connecting back to the VM, the need for the full port space, or operations tools that only accept one IP per machine. In these cases, you can keep the default Pod network as the management plane and add an underlay NIC through Multus:

```text
VM eth0：Pod network + masquerade
  用途：Kubernetes Service、平台探测和默认管理链路

VM office0：Multus + bridge/SR-IOV/macvtap
  用途：办公网或业务 VLAN 中的可路由固定 IP
```

KubeVirt's `network` declares which logical network to connect to, and `interface` declares how that network attaches to the guest; the two names must correspond one-to-one. A minimal dual-NIC VM snippet is as follows:

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

`office-network` is an `NetworkAttachmentDefinition`, which typically references Linux Bridge, OVS, macvlan, macvtap, or SR-IOV CNI. Taking Linux Bridge as an example, the host must first have an `br-office` attached to the target VLAN; Multus only invokes the corresponding CNI to attach the second interface in the VMI Pod to that bridge. It does not automatically configure switches, VLANs, gateways, or routes for the administrator.

A more robust production approach for fixed addresses is "fixed MAC + enterprise DHCP reserved address":

1. The platform assigns each VM a globally unique MAC that does not change across restarts;
2. The network/IPAM system reserves an office network IP based on that MAC;
3. The guest's second NIC uses DHCP;
4. The CMDB records user, VM, MAC, IP, VLAN, and reclamation status simultaneously.

Ubuntu cloud-init can fix the second NIC's name by MAC and enable DHCP:

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

If the enterprise network has no DHCP, you can also write a reserved static address, prefix, routes, and DNS in `networkData`. However, uniqueness validation must first be completed by IPAM/CMDB; users must not be allowed to arbitrarily pick addresses inside the guest. Dynamic address pool plugins can avoid concurrent allocation conflicts, but they do not inherently guarantee "getting the same IP after deleting the VMI"; when using Whereabouts, Spiderpool, Kube-OVN, or cloud provider IPAM, you must additionally confirm their fixed-address, reservation, and reclamation semantics.

### 15.3 Host and network-side prerequisites

Before attaching VMs to the office network in a single-node experiment, at minimum confirm:

- The node has a dedicated business NIC, a Bond VLAN sub-interface, or a reviewed shared link;
- `br-office`, OVS Bridge, or SR-IOV VF configuration can be automatically restored after node reboot;
- Switch Trunk/Access VLAN, MTU, gateway, DHCP Relay, and ACL are matched;
- Multus and the corresponding CNI binaries are installed, and `NetworkAttachmentDefinition` can be used in the target Namespace;
- MAC/IP addresses are uniformly allocated by the platform, with conflict detection, audit, and reclamation processes;
- Bidirectional routing exists between the office network and the VM subnet, and the return path does not incorrectly traverse the masquerade NIC;
- NetworkPolicy primarily constrains Pod network traffic; whether underlay traffic is controlled must be validated separately;
- Local-disk VMs cannot migrate to nodes lacking the same Layer 2 network and local volumes; the node failure boundary does not disappear because of fixed IPs.

Do not directly add the physical interface carrying Kubernetes management traffic to a new Bridge and experiment online—this can cause the node to lose connectivity immediately. Prefer a dedicated NIC or VLAN sub-interface; save NetworkManager/systemd-networkd configuration and out-of-band recovery methods before making changes, and first use a test VM to validate ARP, DHCP, DNS, MTU, routing, and reboot recovery.

### 15.4 How to choose among the three options

| Requirement | Recommended Entry Point | Per-VM Fixed IP Required? |
| --- | --- | --- |
| Browser access to JupyterLab/code-server | Fixed domain + HTTPS Gateway/Ingress + VM Service | No |
| Administrator SSH into user VMs | Bastion/TCP Gateway, or a controlled LoadBalancer Service | Usually not |
| Users SSH from the office network and must maintain traditional one-IP-per-machine | Multus second NIC + fixed MAC + DHCP reservation | Yes |
| Legacy systems proactively connect to any VM port | Multus underlay IP, with ACL/IPAM | Yes |
| Only the service entry address needs to be fixed | LoadBalancer Service + enterprise LB/MetalLB | What is fixed is the Service VIP, not the guest IP |
| GPU/RDMA high-performance data plane | Management network keeps masquerade; data plane uses Multus + SR-IOV as needed | Data plane addresses governed per network plan |

For a multi-user Notebook platform, the default choice should be "stable domain names and identity entry points," not "50 Pod IPs that never change." Only add a Multus underlay NIC to individual VMs when the network requirement cannot be expressed through Service/Gateway. This preserves Kubernetes service discovery and lifecycle capabilities without prematurely binding the platform to office network VLANs, address capacity, and physical switch configuration.

## 16. Other KubeVirt capabilities suitable for workstation platforms

KubeVirt provides VM lifecycle and virtualization capabilities; it does not directly determine for the platform whether "the user is still working." For a multi-user Notebook platform, the more practical capabilities include:

| Capability | Problem it solves | Key boundary |
| --- | --- | --- |
| `runStrategy` and start/stop/restart subresources | Declares that a VM should keep running, restart on failure, run only once, be manually controlled, or remain powered off | It only enforces the desired state; it does not determine whether the user is idle |
| VM Snapshot/Restore | Saves VM configuration and coordinates CSI volume snapshots and restore | Whether data volumes can be snapshotted depends on the CSI and `VolumeSnapshotClass`; online consistency is best achieved with the QEMU Guest Agent |
| Live Migration | Migrates running VMs during node maintenance | Local disks, certain passthrough devices, and network bindings cannot be migrated; the Local LVM VMs in this article do not have this capability |
| DataVolume, Clone, and Export | Imports golden images, creates user disks, clones or exports VMs/PVCs | Bulk Host-assisted Copy generates real network and disk I/O and should be rate-limited |
| Instancetype and Preference | Standardizes specifications such as 4C16G, 48C192G, GPU workstations, and machine preferences | Whether a specification change can take effect online depends on the version, LiveUpdate, and guest support |
| Hot-plug disk and NIC | Adds data disks or attaches networks without shutting down | Requires the corresponding feature gates, CNI/CSI capabilities, and guest drivers; not all devices can be hot-plugged |
| QEMU Guest Agent | Reports guest OS, interfaces, file systems, logged-in users, and other information, and assists with consistent snapshots | The agent is an observability and collaboration channel; it should not be treated as a full terminal audit trail or the sole idle signal |
| Persistent TPM/UEFI state | Supports workloads that require persistent firmware variables or a virtual TPM | Requires a backend state StorageClass and adds backup and restore objects |
| VM Pool | Maintains a group of homogeneous VMs, suitable for teaching pools, temporary desktop pools, and pre-warmed instances | Personal long-term workstations are better served by one VM/PVC per user, to avoid the pool controller mistakenly reclaiming user state |

These capabilities should be validated against the actual cluster version and feature gates. Do not assume that an API mentioned in the latest documentation is already available in the currently installed version; verify with `kubectl api-resources`, `kubectl explain`, and a test VM before going live.

### 16.1 How long without use before automatic shutdown: KubeVirt provides the action, the platform owns the policy

KubeVirt currently has no built-in field that can express:

```yaml
idleTimeout: 2h
```

What it provides is a reliable lifecycle primitive. After the Controller determines that a VM is idle, it can call the stop subresource or change the VM to `runStrategy: Halted`; on the next access, it can restore the running state via the start subresource. KubeVirt supports run strategies such as `Always`, `RerunOnFailure`, `Once`, `Manual`, and `Halted`; see [KubeVirt Run Strategies](https://kubevirt.io/user-guide/compute/run_strategies/) for the exact semantics.

The shutdown path that actually releases resources is:

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

Do not use `virtctl pause` as a substitute for automatic shutdown. Pause freezes the guest's vCPUs and I/O, but the QEMU process and VM memory remain on the host, so it cannot solve the memory capacity problem of a node shared by many users. The official KubeVirt lifecycle documentation also states explicitly that domain memory remains allocated while paused; see [KubeVirt Lifecycle](https://kubevirt.io/user-guide/user_workloads/lifecycle/). Memory Dump is likewise only for fault analysis; it is not a hibernation mechanism that saves memory state and then releases resources.

### 16.2 Idle cannot be judged only by "how long since the last web request"

A Notebook workstation may continue training, downloading data, running terminal tasks, or compiling code after the browser is closed. Judging idle solely by the last Ingress request time or low CPU utilization will easily cause false positives. The recommended approach is to combine the following signals:

| Signal | What it can detect | Limitation |
| --- | --- | --- |
| Gateway/Jupyter last request time | Whether the browser is still interacting | Cannot detect SSH, background kernels, or detached tasks |
| Jupyter Session/Kernel state | Whether the Notebook kernel is busy and its last activity time | Cannot see code-server, system processes, or standalone Python scripts |
| code-server WebSocket/heartbeat | Whether the IDE is online | A user losing network connectivity does not mean background tasks can be terminated |
| SSH login and PTY | Whether an interactive terminal exists | `tmux`, `screen`, and systemd user services may keep running after logout |
| CPU, GPU, disk, and network utilization | Whether sustained compute or I/O is occurring | Thresholds set too low will misjudge tasks that are waiting on data, sleeping, or running intermittently |
| QEMU Guest Agent/platform agent | Guest logged-in users, process summaries, and custom heartbeats | The agent may fail; "no data" must not be interpreted as "idle" |
| Explicit user lease | User declares "keep running tonight" | Must have a maximum duration, quota, and audit trail; permanent bypass of reclamation must not be allowed |

JupyterHub already has `jupyterhub-idle-culler`, which can stop single-user Servers based on user activity recorded by the Hub; see [JupyterHub Idle Culler](https://jupyterhub.readthedocs.io/en/latest/tutorial/getting-started/services-basics.html). However, this article describes a single VM running JupyterLab, code-server, SSH, and arbitrary background processes simultaneously, so "Jupyter Server idle" cannot be directly equated with "the entire VM can be shut down." A better approach is to make Jupyter activity one input to the platform Controller, combined with VM-level metrics and protection leases for the final decision.

### 16.3 Recommended automatic shutdown and on-demand wake-up flow

Platform policy can be declared on the VM rather than letting the guest permanently hold power control:

```yaml
metadata:
  labels:
    workstation.aik8s.run/autostop: "enabled"
  annotations:
    workstation.aik8s.run/idle-timeout: "2h"
    workstation.aik8s.run/grace-period: "10m"
    workstation.aik8s.run/max-keep-running: "24h"
```

These are not built-in KubeVirt fields but example conventions from a self-developed Workspace Controller. The Controller can operate according to the following state machine:

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

The recommended initial policy is:

- An ordinary development workstation enters a shutdown grace period after 2 consecutive hours without valid activity;
- Notify at least 10 minutes before shutdown, and allow the user to click "keep running";
- Background tasks are protected by an explicit lease of at most 24 hours; after timeout, a new request is required;
- The shutdown action first requests a graceful guest shutdown; only after a timeout does the platform decide whether to force-stop;
- Autostop is enabled only for VMs whose PVC is already Bound, whose root disk is recoverable, and whose application services can start automatically;
- Record the decision signals, shutdown reason, executor, and recovery duration to explain false shutdowns and tune thresholds.

If the VM uses `runStrategy: Always`, KubeVirt will bring it back up after `shutdown` is executed inside the guest, so do not simply place an idle shutdown script inside the guest. Having an external Controller call VM stop is the clearest approach; alternatively, use `Manual`/`RerunOnFailure` and be explicit about their restart semantics. For the current Notebook VM, the platform can call start at boot time and stop at idle reclamation, while the root disk remains in a separate DataVolume/PVC.

### 16.4 Recommended enablement order

1. First install and verify the QEMU Guest Agent, Service readiness, and graceful shutdown;
2. Establish a fixed-domain entry point so that the stopped state can display "starting" instead of returning 502 directly;
3. Record activity data for one week only, without performing shutdowns, and use the real distribution to determine thresholds;
4. Enable notification-based autostop for a small group of test users, keeping one-click lease renewal;
5. Verify that after shutdown the VMI disappears, CPU/memory are released, the PVC is retained, and the environment and services recover after restart;
6. Finally roll out to all users, and set different policies for training, inference, teaching, and temporary development.

## 17. From experiment to production

| Experimental practice | Production replacement |
| --- | --- |
| Single-node Local LVM | Block storage with failure recovery such as Ceph RBD |
| Tiny Core Live ISO | Auditable, periodically rebuilt Ubuntu LTS golden image |
| Node address + hostNetwork:6080 | HTTPS Gateway/Ingress + OIDC + per-user short-term authorization |
| One static noVNC account | User identity mapping, fine-grained authorization, session audit, and credential rotation |
| Manually created VMs | Workspace Portal/Operator automatically creates, stops, snapshots, and reclaims |
| `Retain` local PV | CSI Snapshot, off-site backup, recovery drills, and lifecycle policies |
| Best-effort CPU/memory sharing | Quota, priority, NUMA/CPU topology, and dedicated GPU node pools |
| Direct use of VMI Pod IP | Stable domain + Service + HTTPS Gateway; add Multus underlay NICs for special scenarios |

Three types of lifecycle also need to be made explicit:

1. **Stop VM**: delete the VMI and release compute resources, but retain the VM and root disk;
2. **Reset environment**: re-clone the root disk from the golden image; a snapshot or second confirmation must be required;
3. **Delete user**: delete PVC/PV and backups after a retention period; this must not share a button or permission with the stop operation.

## 18. Acceptance checklist

- [ ] Candidate nodes have a usable `/dev/kvm`, and `virt-handler` lands only on the expected nodes;
- [ ] CirrOS VMI is Ready, and the serial console can connect and disconnect;
- [ ] Desktop VM, `virt-launcher`, and local PV are on the same node;
- [ ] The Tiny Core graphical desktop can be operated through noVNC;
- [ ] The noVNC proxy has only the minimal permissions needed for VNC within the namespace;
- [ ] When the browser disconnects and reconnects, the `virtctl` proxy recovers automatically;
- [ ] Health checks do not occupy the single-connection proxy on port 5900;
- [ ] After stopping and restarting the VM, test files written to the persistent root disk still exist;
- [ ] The local-disk non-migratability, node-failure unavailability, and `Retain` reclamation flow have been documented;
- [ ] Production workstations have switched to the Ubuntu LTS golden image with pinned Jupyter/code-server versions;
- [ ] VMs can resolve enterprise intranet FQDNs, and DNS queries do not first wait for an unreachable kube-dns timeout;
- [ ] VMs that need to access Kubernetes Services have been verified with `*.svc.cluster.local`, and dynamic CoreDNS Pod IPs are not hardcoded into templates;
- [ ] The Cilium kube-proxy replacement scenario has been regression-tested for VM-to-ClusterIP TCP/UDP access;
- [ ] User entry points use stable domains or Services, and VMI Pod IPs are not treated as permanent VM addresses;
- [ ] VMs that need a fixed office-network IP have been verified with Multus, fixed MAC, IPAM, VLAN, return routes, and address reclamation;
- [ ] The underlay network does not bypass the expected ACLs, audit, and tenant isolation;
- [ ] Automatic shutdown combines Jupyter, SSH, background task, and resource signals, and does not treat a single HTTP idle as VM idle;
- [ ] Automatic shutdown goes through notification and a grace period, and provides a capped, auditable keep-running lease;
- [ ] After stopping the VM, the VMI/`virt-launcher` disappears, compute resources are released, the PVC is retained, and services recover automatically on on-demand wake-up;
- [ ] The production entry point has HTTPS, unified authentication, authorization, audit, and network access control.

The most valuable conclusion of this experiment is not that "a desktop appeared in the browser," but that the state boundaries were verified clearly: `containerDisk` and the Live ISO are responsible for distributing the boot medium, while the DataVolume/PVC is what actually preserves the user's complete environment; local disks can validate the persistent workstation experience, but cannot pretend to have the failure-recovery capability of shared storage.
