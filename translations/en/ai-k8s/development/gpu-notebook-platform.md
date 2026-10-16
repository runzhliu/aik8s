---
title: "GPU Notebook Platform and Storage Selection in the Large Model Era"
description: "From JupyterHub, Kubeflow and managed Workbench to full-GPU, MIG, shared GPU, user Home, object storage and local cache production selection"
status: evolving
last_reviewed: 2026-08-11
---

# GPU Notebook Platform and Storage Selection in the Large Model Era

In the large model era, a Notebook is no longer just a Python editor in the browser. It often simultaneously hosts JupyterLab, VS Code, terminal, Git, model downloads, data exploration, LoRA fine-tuning and remote task submission, and behind the scenes it may consume tens to hundreds of GiB of memory, one or more expensive GPUs, and hundreds of GiB of temporary cache.

Therefore, the real selection target for a Notebook platform is not a Web UI, but a set of **interactive development workspaces**: identity, image, compute specification, GPU isolation, persistent directories, data access, cache, idle reclamation and task handoff must be designed together.

If you care more about how a platform evolves step by step from JupyterHub/KubeSpawner to code-server, group-level eight-GPU sharing, per-user Ceph RBD, Workspace Operator and KubeVirt root disk, first read [Pitfalls of GPU Development Platforms in the Large Model Era](../practices/gpu-notebook-platform-evolution.md). That practical record documents the online issues and reproducible configurations behind each adjustment.

## 1. Conclusions First

### Recommended Default Architecture

For most teams that already run Kubernetes but do not need the full Kubeflow suite, the first version recommendation is:

```text
JupyterHub + KubeSpawner
        │
        ├─ 受控 CPU / 共享 GPU / MIG / 整卡规格
        ├─ 每用户一个 RWO SSD PVC，保存 Home 与少量代码
        ├─ 对象存储，保存数据集、模型、Checkpoint 和 Artifact
        ├─ 本地 NVMe，保存模型缓存、数据缓存与临时文件
        └─ Job / TrainJob / RayJob，承接长时间训练任务
```

This route has few components and clear boundaries, and is suitable for first establishing a multi-user GPU development entry point.

### When to Switch to Other Options

| Condition | Preferred Option | Reason |
| --- | --- | --- |
| Only need multi-user Jupyter/VS Code, self-service specifications and basic authentication | JupyterHub on Kubernetes | Lightweight control plane; user PVC, resource Profiles and Idle Culler already cover core needs |
| Already using Kubeflow Profiles, Pipelines, Trainer, Katib | Kubeflow Notebook/Workspace | More complete integration with Kubeflow identity, Namespace, Pipeline and platform UI |
| Very small team, fully single-cloud, no platform operations staff | Cloud-managed Workbench | Cloud IAM, image, instance and storage integration work out of the box |
| Already on OpenShift and require commercial support and unified governance | Red Hat OpenShift AI and similar distributions | Leverage existing enterprise identity, Operator, audit and support systems |
| Only a few trusted users, short-term validation | Controlled VM or single-user Workbench | The investment in a Kubernetes multi-tenant control plane may not be worthwhile yet |
| Users will modify arbitrary system directories and must be restored exactly after stop | KubeVirt + dedicated RBD root disk | Full guest filesystem persistence, without relying on users following PVC directory conventions |

It is not recommended to directly create an ordinary `Deployment + Service + Ingress` for each user. This self-built approach will quickly end up re-implementing authentication, stop/resume, PVC lifecycle, URL routing, specification selection, image governance and auditing.

### Things to Note When Choosing Kubeflow in 2026

As of August 2026, Kubeflow officially stated that Notebooks v1 has entered maintenance mode and is planned to end support at the end of 2026; the Workspaces v2 test checklist is still only suitable for evaluation and is not yet ready for production. Therefore:

- Existing Notebooks v1 platforms should develop a migration plan for Workspace API, PVC, image and access entry points;
- New long-term platforms must not choose v1 based only on old tutorials; they should confirm the distribution's support timeline and migration commitment for v2;
- Workspaces v2 can be used for a PoC, but the Alpha version should not currently be treated as the only production entry point;
- When immediate rollout is needed, choose a mature version of JupyterHub, or a commercial distribution/managed service with a clear support cycle.

References: [Kubeflow 26.03.1 Release Notes](https://blog.kubeflow.org/kubeflow-26.03-release/), [Kubeflow Notebooks Overview](https://www.kubeflow.org/docs/components/notebooks/overview/)

## 2. First Define the Responsibility Boundary of Notebook

Notebook is suitable for:

- Data exploration, visualization and small-sample validation;
- Experiments with Prompt, Tokenizer, model structure and inference parameters;
- Debugging training code on a single GPU or small-scale data;
- Generating task configurations and submitting to training, batch or Pipeline systems;
- Viewing experiment metrics, logs, Checkpoints and evaluation results.

Notebook should not be responsible for:

- Formal training that lasts hours or days and must be reliably recoverable;
- Multi-node distributed training requiring Gang Scheduling;
- Production online inference services;
- The only persistent copy of datasets, models and Checkpoints;
- Directly executing production releases or holding cluster administrator privileges.

The recommended handoff chain is:

```text
Notebook 中调试代码
        │
        ├─ Git 提交代码与配置
        ├─ 构建不可变镜像
        ├─ 数据和模型使用版本化 URI
        ▼
Job / TrainJob / RayJob / Pipeline
        │
        ├─ Kueue 准入、配额与优先级
        ├─ Checkpoint 与实验追踪
        ▼
模型注册、评估、GitOps 发布
```

This way, when Idle Culler stops a Notebook, it will not accidentally kill formal training; Notebook corruption will not damage production jobs either.

## 3. How Platform Capabilities Should Be Decomposed

```text
企业 IdP / OIDC / SSO
          │
Gateway / Ingress / Workspace UI
          │
Notebook 控制面
JupyterHub / Kubeflow / Managed Workbench
          │
Workspace Pod：JupyterLab / VS Code / Terminal
          │
          ├──────── 计算 ──────── CPU / Shared GPU / MIG / Full GPU
          ├──────── 持久层 ────── Per-user PVC / Team RWX / Object Storage
          ├──────── 加速层 ────── Local NVMe / Page Cache / Model Cache
          └──────── 执行层 ────── Job / Trainer / Ray / Pipeline / Kueue
```

When evaluating a product, do not just look at whether it can "start Jupyter". At minimum, verify the following capabilities:

| Capability | Questions that must be answered |
| --- | --- |
| Identity | Can it connect to enterprise OIDC? How are users, groups and team spaces mapped? |
| Workspace | Can Home be preserved after stop? Can image and resources be modified and restarted? |
| Compute catalog | Can users only choose from administrator-approved specifications? |
| GPU | Are full-GPU, MIG and shared resources using different names, node pools and quotas? |
| Storage | Do Home, data, models, cache and Scratch have independent lifecycles? |
| Long tasks | Can tasks be submitted from Notebook to an execution system governed by queues? |
| Security | Are ServiceAccount, outbound network, Secret and Pod permissions minimized? |
| Cost | Can idle Kernels be identified, Pods stopped, GPUs reclaimed while PVCs are preserved? |
| Operations | Are image pre-pull, upgrade, backup, audit and capacity alerts complete? |

## 4. How to Choose Between JupyterHub, Kubeflow and Managed Workbench

| Dimension | JupyterHub on Kubernetes | Kubeflow Notebook/Workspace | Cloud-managed Workbench | Self-built Pod Portal |
| --- | --- | --- | --- | --- |
| Core positioning | Multi-user interactive computing | Development entry point in an end-to-end ML platform | Cloud vendor-managed personal/shared workspace | Fully custom |
| Control plane complexity | Medium | High | Low | Low initially, very high long-term |
| JupyterLab | Native | Native | Usually native | Self-integrated |
| VS Code/code-server | Custom image and Profile | Officially supported containerized IDE | Depends on cloud service | Self-integrated |
| Multi-tenant boundary | Authenticator, Spawner, Namespace, Policy | Profiles, RBAC, Namespace, Istio, etc. | Cloud IAM and Workspace/Space | Self-implemented |
| Self-service resource specifications | `profileList` | UI and resource configuration | Instance/application specifications | Self-implemented |
| Per-user persistent disk | Mature | Mature | Built into service | Self-implemented |
| Pipeline/Trainer integration | Combined via API and templates | Deeper integration within the same platform | Integrated within cloud service | Self-implemented |
| Portability | High | High, but more components | Low to medium | Depends on implementation |
| Suitable teams | Teams that want to keep the platform simple | Teams already with a full Kubeflow system | Single-cloud with limited operations staff | Teams with clear differentiated product requirements |

### JupyterHub

Advantages:

- Control plane responsibilities are concentrated, easy to combine with existing Kubernetes, OIDC and GPU node pools;
- KubeSpawner can package image, CPU, memory, GPU, node affinity and mounts into a small number of Profiles;
- Per-user PVC, Idle Culler, user scheduler, image pre-pull and other paths are mature;
- Does not force the team to simultaneously introduce a full Pipeline, Serving and Service Mesh suite.

Limitations:

- Team spaces, approvals, project templates, training jobs and experiment lineage need to be combined with other systems;
- Major Helm Chart upgrades may change username, Pod or PVC naming rules; migration notes must be read before upgrading;
- Advanced Namespace isolation and network policies still need to be designed by the platform team.

Official optimization recommendations include image pre-pull, user placeholder Pods, user scheduler, dedicated scalable node pools and Idle Culler. If large CUDA images are not pre-pulled, users may wait extra minutes. References: [Zero to JupyterHub Optimization Guide](https://z2jh.jupyter.org/en/stable/administrator/optimization.html), [User Resources and GPU Profile](https://z2jh.jupyter.org/en/latest/jupyterhub/customizing/user-resources.html)

### Kubeflow Notebook/Workspace

Advantages:

- JupyterLab, RStudio, VS Code code-server use a unified Workspace model;
- Works with Kubeflow Profiles, RBAC, Pipelines, Trainer, Katib and other components;
- Platform administrators can provide standard images, and users use environments per team Namespace;
- Suitable for making Notebook part of a complete data science portal.

Limitations:

- Identity, Istio, Profile, admission policy, storage and upgrade chains are longer;
- Default ServiceAccount permissions must be checked; do not grant broad Kubernetes API permissions just for the convenience of submitting Pipelines;
- Currently in the generational transition from Notebooks v1 to Workspaces v2.

Kubeflow officially reminds: packages temporarily installed after Pod startup will disappear with the Pod, unless installed in a PVC directory; in production, fixed custom images should be used instead. Reference: [Kubeflow Notebook Image Requirements](https://www.kubeflow.org/docs/components/notebooks/container-images/)

### Cloud-managed Workbench

Typical products include Vertex AI Workbench, SageMaker Studio JupyterLab/Spaces and Azure Machine Learning Compute Instance.

Suitable for:

- Data, identity, training and artifacts are already concentrated in the same cloud;
- User scale is small, and the platform team does not want to maintain Hub, Ingress, Spawner and image pre-pull;
- Accepting the vendor's instance type, network, image, storage and billing models.

Key items to verify:

- Which disks are preserved after workspace stop, and how to scale and back them up;
- Permission boundaries for private and shared Workspaces;
- GPU stop billing and Idle Shutdown determination methods;
- Whether custom images, VPC private networks, proxies, private Registries and customer-managed keys are supported;
- Whether data crosses regions, accounts or is accessed over the public internet;
- Whether formal training can be handed off to managed Jobs instead of long-term occupation of the Workbench.

For example, different Spaces in current SageMaker Studio typically use their own EBS volumes; Azure ML explicitly recommends not putting training data in the Notebook file share, and recommends placing large numbers of temporary small files in the local temporary directory. References: [SageMaker Studio Spaces](https://docs.aws.amazon.com/sagemaker/latest/dg/studio-updated-spaces.html), [Azure ML Compute Instance](https://learn.microsoft.com/en-us/azure/machine-learning/concept-compute-instance?view=azureml-api-2), [Vertex AI Workbench](https://cloud.google.com/vertex-ai/docs/workbench/introduction)

## 5. Don't Let Users Freely Fill in Arbitrary Specifications

The platform should publish a versioned resource catalog instead of exposing a full Pod form.

| Example specification | Typical resources | Use case | Default time limit |
| --- | --- | --- | --- |
| `cpu-small` | 2–4 CPU, 8–16 GiB memory | Browsing code, lightweight data analysis | Can be stopped/resumed long-term |
| `cpu-memory` | 8–16 CPU, 64–128 GiB memory | Tokenize, CPU preprocessing | 8–12 hour idle reclamation |
| `gpu-shared-dev` | Shared GPU Access, 16–32 GiB memory | CUDA smoke test, small model debugging | 1–2 hour idle reclamation |
| `gpu-mig-small` | One MIG Profile | Small/medium models, multi-tenant experiments requiring GPU memory isolation | 2–4 hour idle reclamation |
| `gpu-full` | One full GPU, sufficient CPU/memory | Large model loading, LoRA, performance verification | 1–2 hour idle reclamation |
| `gpu-multi` | 2–8 full GPUs on the same node | Single-node parallel debugging | Approval and maximum runtime required |

Each Profile should at minimum fix:

- Container image or optional image set;
- CPU/memory request and limit;
- GPU Resource Name and quantity;
- Node Selector, Taint/Toleration and RuntimeClass;
- Home PVC type and capacity limit;
- Additional mounts, network policies and ServiceAccount;
- Idle Timeout, maximum session time and cost attribution labels.

`ResourceQuota` is used to limit team total resources; `LimitRange` and admission policies are used to prevent unbounded CPU, memory and ephemeral storage; GPU totals should also enter team quotas, approvals or queue systems.

## 6. Resource Isolation for Containers, KubeVirt and Shared Large Machines

Many early Notebook platforms used a "one large machine, dozens of privileged containers, all users can see all CPU, memory and GPU" approach. Its advantage is that anyone can directly use resources when idle; its disadvantage is that security boundaries, failure domains, performance attribution and capacity protection are almost entirely left to user self-discipline.

Before migrating to KubeVirt, you must first distinguish three completely different resource semantics:

| Layer | Typical configuration | Actual effect |
| --- | --- | --- |
| Guest virtual hardware | `domain.cpu`, Guest Memory | Determines how many vCPUs and memory are visible inside the VM; the direct upper limit of the Guest |
| `virt-launcher` request | `resources.requests` | Determines Kubernetes scheduling reservation and CPU contention weight; not a CPU hard limit |
| `virt-launcher` limit | `resources.limits` | CPU is throttled via cgroup; memory overrun may cause VM crash or termination |
| Dedicated CPU | `dedicatedCpuPlacement: true` | Pins vCPUs to exclusive pCPUs for stable performance, giving up elastic sharing |
| GPU devices | PCI Passthrough, vGPU/MDEV, MIG, Time-Slicing | Determines whether GPU is exclusive, hardware-partitioned or Best Effort shared |

### Why privileged containers are not "able to use the entire machine"

`privileged: true` mainly changes Linux capabilities, device access, and the host attack surface; it does not automatically bypass CPU or memory cgroups. Notebooks on the old platform could use large amounts of resources, usually because no CPU/memory limits were set and all GPU devices were exposed to the container; ordinary non-privileged containers without CPU limits can likewise use idle node CPU.

Therefore, you should not keep using privileged containers just to preserve resource elasticity. The safer approach is to remove privileges and HostPath, keep only a small request, and choose either "no CPU limit" or a higher CPU limit. Memory should still have an explicit upper bound, to avoid a single Notebook pushing the node into OOM. Reference: [Kubernetes resource requests and limits](https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/)

### A 2 vCPU VM will not automatically borrow 10 cores

If a VM is configured with 2 vCPUs, the Guest can execute at most two vCPU threads in parallel; even if the host still has 98 idle cores, it will not automatically become a 10-core or 100-core machine. Having no CPU limit only means those two vCPUs are not subject to additional cgroup quota throttling; the QEMU emulator and I/O threads will still consume a small amount of host CPU.

KubeVirt's default `cpuAllocationRatio` is 10, so, for `virt-launcher`, a 2 vCPU VM by default requests about `200m` CPU, and by default has no CPU limit. Typical measured results are as follows:

```text
Guest：2 vCPU / 4 GiB
virt-launcher CPU request：200m
virt-launcher CPU limit：未设置
virt-launcher Memory request：约 4 GiB + 虚拟化开销
```

When running 50 such VMs on a 100-core machine, the Guests collectively see 100 vCPUs, but the scheduler by default only counts about 10 cores of CPU request. When all VMs are busy at the same time, they can still use all 100 cores; a single VM, however, will not exceed its own 2 vCPU topology. Reference: [KubeVirt Resources Requests and Limits](https://kubevirt.io/user-guide/compute/resources_requests_and_limits/), [KubeVirt Node Overcommit](https://kubevirt.io/user-guide/compute/node_overcommit/)

### Wanting "a guaranteed 2 cores, bursting to 8 cores when idle"

You need the Guest to see more vCPUs while only requesting a smaller guaranteed share from the scheduler, and without setting a CPU limit:

```yaml
spec:
  domain:
    cpu:
      sockets: 8
    resources:
      requests:
        cpu: "2"
        memory: 16Gi
      # 不设置 limits.cpu
```

This VM can use up to about 8 vCPUs in parallel when the node is idle; under contention, the `2` core request mainly determines scheduling admission and CPU shares. The differences between strategies are:

| Configuration | Scheduling reservation | Max parallel CPU per VM | Use case |
| --- | ---: | ---: | --- |
| 2 vCPU, default request, no limit | About 0.2 cores | About 2 cores | High-density lightweight Notebook |
| 8 vCPU, request 2, no limit | 2 cores | About 8 cores | Interactive development that wants to burst when idle |
| 2 vCPU, limit 2 | Depends on request | About 2 cores with quota throttling | When an explicit hard cap is needed |
| 2 vCPU, Dedicated CPU | 2 exclusive pCPUs, plus overhead | 2 fixed pCPUs | Performance testing, low latency, and stable throughput |

Dedicated CPU requires Guaranteed QoS, integer CPUs, and relies on the kubelet CPU Manager; you also need to reserve capacity for the QEMU emulator and platform DaemonSets. Reference: [KubeVirt Dedicated CPU](https://kubevirt.io/user-guide/compute/dedicated_cpu_resources/)

### Memory cannot follow the same overcommit approach as CPU

CPU time can be scheduled across multiple vCPUs, but Guest memory is closer to a capacity that must be honored at startup. KubeVirt is currently not suited to relying on large-scale dynamic Ballooning and automatic return from traditional virtualization platforms: if you give 50 VMs 16 GiB each, capacity planning should approach 800 GiB, plus `virt-launcher`, page tables, firmware, and device emulation overhead.

In production you can aggressively overcommit CPU, but you should overcommit memory cautiously. Even if `virt-launcher` has no memory limit, the Guest will not automatically see all host memory; conversely, setting a memory limit that is too tight can directly crash the VM. Notebook models, data, and caches should go into object storage, shared data layers, and local caches, rather than being solved by allocating close to the full machine capacity to every VM.

### Reproducing shared-large-machine semantics when OOM is acceptable

If the original Notebook platform was already a Best Effort model of "small request, no limit, accept OOM when resources run out," KubeVirt can provide similar semantics. Suppose a single node has 120 cores and 800 GiB of memory, you need to run 50 VMs, and you want each Guest to see 80 vCPUs and 600 GiB:

```text
总虚拟 CPU：50 × 80 = 4000 vCPU
CPU 超卖比例：4000 / 120 ≈ 33.3:1

总 Guest 内存：50 × 600 GiB = 30000 GiB
内存超卖比例：30000 / 800 = 37.5:1
```

You can explicitly set a small scheduling request for each VM and set no CPU or memory limit:

```yaml
apiVersion: kubevirt.io/v1
kind: VirtualMachine
metadata:
  name: notebook-user01
spec:
  runStrategy: Always
  template:
    spec:
      domain:
        cpu:
          sockets: 1
          cores: 80
          threads: 1
        memory:
          guest: 600Gi
        resources:
          overcommitGuestOverhead: true
          requests:
            cpu: "2"
            memory: 8Gi
          # 不设置 limits.cpu 和 limits.memory
        devices:
          autoattachGraphicsDevice: false
```

50 VMs collectively request 100 cores and 400 GiB, so the scheduler still leaves bookkeeping headroom for the node and burst workloads. A single VM can use close to 80 vCPUs when other users are idle; when all 50 are fully loaded, constrained by the total throughput of 120 physical or logical CPUs, each averages only about 2.4 cores. You must explicitly override the CPU request; otherwise, with the default `cpuAllocationRatio: 10`, one 80 vCPU VM would request about 8 cores, and 50 VMs would total 400 cores and fail to schedule.

`memory.guest: 600Gi` is only a Guest-visible upper bound, not a capacity guarantee. As long as the node still has idle memory, a single VM can keep growing; once the sum of the actual RSS of all `virt-launcher`, host processes, and system reservations approaches 800 GiB, the node enters memory pressure handling. For example, if one VM uses 600 GiB and the other 49 average 4 GiB each, the total already reaches 796 GiB, before even counting host and virtualization overhead.

Do not enable HugePages in this mode. HugePages must be reserved in advance and cannot provide the sparse allocation effect of ordinary pages. You should also phase in stress testing of startup and memory growth at 5, 20, and 50 VMs, rather than treating a 37.5x overcommit as a stable capacity commitment. Reference: [KubeVirt Node Overcommit](https://kubevirt.io/user-guide/compute/node_overcommit/), [KubeVirt Resources Requests and Limits](https://kubevirt.io/user-guide/compute/resources_requests_and_limits/)

### The three layers of OOM in a KubeVirt VM

KubeVirt's outer resource management follows Pod request, limit, QoS, and eviction rules, but the VM also contains an independent Guest OS, so three failure modes must be distinguished:

| OOM or eviction location | Trigger condition | Result | Recovery method |
| --- | --- | --- | --- |
| Inside the Guest OS | Processes inside the Guest exhaust 600 GiB | The Guest Linux usually kills the high-memory process; the VM, SSH, or other services may keep running | Restart the process or have a process manager bring it back |
| `virt-launcher` cgroup | `virt-launcher` actual memory exceeds `limits.memory` | The host kills QEMU; the whole VM is like a sudden power loss | The VM controller recreates the VMI according to `runStrategy` |
| Node memory pressure | Actual usage of all Pods, VMIs, and the host approaches physical memory | kubelet evicts by QoS/usage, or the Node OOM Killer kills processes; hard eviction is close to pulling the plug | VMI is recreated, and the file system performs crash recovery |

Therefore, "accepting OOM" is similar to the old Pod platform, but the failure unit differs: a Guest OOM may only lose one Jupyter Kernel, while the host killing QEMU simultaneously interrupts that user's JupyterLab, code-server, SSH, and the entire set of Guest services. `runStrategy: Always` can let the controller maintain the VM's running state, but it cannot turn an abnormal power loss into lossless recovery.

If `limits.memory` is included in a `ResourceQuota` in the Namespace, KubeVirt may automatically set a memory limit of about twice the request for the VMI. In that case, even though the example above declares the Guest as 600 GiB, QEMU may still be cgroup-OOM-killed around 16 GiB. Before deployment, check the final generated VMI and `virt-launcher` Pod, not just the VM template:

```bash
kubectl get resourcequota -n notebooks -o yaml
kubectl get vmi -n notebooks notebook-user01 -o yaml
kubectl get pod -n notebooks <virt-launcher-pod> \
  -o jsonpath='{.spec.containers[?(@.name=="compute")].resources}'
```

Best Effort VMs should still reserve memory for the host and kubelet, and set soft/hard eviction thresholds that keep the node manageable. The system disk and Home should use PVCs, Notebooks should autosave, and models, datasets, and checkpoints should use object storage; this way, the failure semantics after a VMI eviction are closer to "environment restart" than "data loss."

### How to provide 8 GPUs to 50 users

| Mode | Resources the user sees | Isolation | What sharing 8 cards among 50 people means |
| --- | --- | --- | --- |
| Full PCI Passthrough | One or more real GPUs | Strong, devices are usually exclusive | 8 cards can host at most 8 single-GPU VMs at once |
| NVIDIA vGPU / MDEV | A virtual GPU Profile on one card | Depends on hardware, driver, and Profile | Can split one card across multiple VMs, but requires supported GPUs and a licensing system |
| MIG | Hardware-partitioned instances | Has GPU memory and fault isolation | Suitable for stable small-spec multi-tenancy, but Profile count and shapes are fixed |
| Time-Slicing | Shared access to resources | No GPU memory or fault isolation | Increases concurrency, but one user can still fill GPU memory or affect tasks on the same card |
| Single large GPU VM | All 8 GPUs visible inside the VM | VM is isolated from the host; users inside the VM still share | Closest to the old platform's "one large machine serving 50 people" behavior |

Physical GPU Passthrough requires IOMMU, VFIO, and a device plugin, and once assigned, the device cannot simultaneously continue to be used by host containers. KubeVirt also supports mediated devices/vGPU, but driver, License, Profile reconfiguration, and node draining should be part of the lifecycle. Reference: [KubeVirt Host Devices](https://kubevirt.io/user-guide/compute/host-devices/), [KubeVirt Mediated Devices](https://kubevirt.io/user-guide/compute/mediated_devices_configuration/), [NVIDIA GPU Operator with KubeVirt](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/25.3/gpu-operator-kubevirt.html)

NVIDIA Time-Slicing can increase concurrency, but the vendor explicitly states that it does not provide MIG's GPU memory and fault isolation; requesting multiple shared resources also does not guarantee proportional compute. It suits development and testing within the same trust domain and should not be packaged as a strong-isolation specification. Reference: [NVIDIA GPU Time-Slicing](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/25.3.4/gpu-sharing.html)

### Recommended combination for 120 cores, 800 GiB, 8 cards, 50 people

Do not force all users into a single isolation model; a hybrid platform is more practical:

1. **Default interactive Notebooks use non-privileged containers**: CPU request of 1–2 cores, no CPU limit or a higher CPU limit; memory with a reasonable request and a hard limit; GPU using MIG or Time-Slicing with the risks explained.
2. **Use KubeVirt when root, systemd, arbitrary system packages, or a stronger security boundary is needed**: a robust spec can give the Guest 8–16 vCPUs, a CPU request of 2 cores with no CPU limit, and memory allocated at real capacity; GPU as full-card Passthrough or vGPU.
3. **Provide a separate spec for Best Effort compatibility with the old platform**: 50 Guests can all see 80 vCPUs / 600 GiB while requesting only 2 CPU / 8 GiB with no limits; it must be clearly labeled as an evictable shared pool, not 50 units of capacity commitment.
4. **Use a single large GPU VM when the old experience of "everyone sees 8 cards" must be preserved**: allocate most of the CPU, memory, and all 8 GPUs to one VM, then run JupyterHub and user containers inside the VM. This shrinks the attack surface against the Kubernetes host, but does not solve resource interference among the 50 users inside the VM.
5. **Move formal training from Notebooks to Job/TrainJob/RayJob**: obtain full cards or multiple cards through queues, quotas, and priorities, avoiding one interactive environment holding expensive resources for a long time.

Creating a "privileged KubeVirt VM" is not recommended. Guest root by default only controls the Guest; the GPUs, NICs, NVMe, and network capabilities needed should be declared item by item. Exposing HostPath, Host PID, arbitrary PCI devices, and host management privileges to users together would only recreate the old platform's host-level risk.

## 7. Estimate GPU memory first, then choose the GPU

Looking only at model parameter count usually underestimates GPU memory. The most basic weight estimate is:

```text
模型权重显存 ≈ 参数量 × 每参数字节数

FP32 / TF32：约 4 Byte
FP16 / BF16：约 2 Byte
INT8：约 1 Byte，加量化元数据
INT4：约 0.5 Byte，加量化元数据
```

For example, a 7B model's theoretical BF16 weight value is about 14 GB, but actually loading it also requires CUDA Context, temporary Workspace, activations, KV Cache, Tokenizer, and framework overhead. Running multiple Kernels or models simultaneously in a Notebook further increases usage.

| Scenario | Main GPU memory beyond weights |
| --- | --- |
| Inference | KV Cache, temporary Workspace, concurrent Batch, long context |
| Full training | Gradients, optimizer states, activations, communication buffers; usually far higher than just loading weights |
| LoRA/QLoRA | Base weights, activations, Adapters, partial optimizer states; not equal to just the Adapter size |
| Multimodal | Image/audio Encoders, preprocessing Tensors, and longer sequences |
| Multi-GPU | Weights, activations, communication buffers, and possible duplicate replicas from the parallel strategy |

Before formal procurement, you must measure peak GPU memory with the target model, framework, precision, context, and batch; do not make capacity commitments by simply multiplying parameter count by bytes.

## 8. How to choose among full card, MIG, Time-Slicing, and MPS

| Mode | GPU memory isolation | Fault isolation | Performance stability | Suitable for Notebook | Main cost |
| --- | --- | --- | --- | --- | --- |
| Full card exclusive | Strong | Strong | Best | Large models, training, performance experiments | Small tasks waste capacity |
| MIG | Hardware partitioning | Hardware partitioning | Fairly stable | Multi-tenant small/medium models and stable GPU memory specs | Only supported on some GPUs, Profiles are fixed, reconfiguration requires node draining |
| Time-Slicing | None | None | Best Effort | Lightweight development and CUDA smoke tests in the same trust domain | OOM/abnormalities affect each other; latency and throughput are uncertain |
| MPS | Limited process-level control | Weaker than MIG | Depends on load | Same team, small Kernel concurrency | Configuration, attribution, and compatibility are more complex |

### Selection rules

```text
需要可预测性能或正式训练？ ── 是 ──> 整卡
             │
             否
             ▼
需要显存/故障隔离且硬件支持 MIG？ ── 是 ──> MIG
             │
             否
             ▼
是否同一信任域、可接受 Best Effort？ ── 是 ──> Time-Slicing 或 MPS PoC
             │
             否
             ▼
使用独立 GPU、独立节点池或更强隔离平台
```

NVIDIA explicitly states that Time-Slicing Replicas do not have the GPU memory and fault isolation provided by MIG, and that requesting multiple shared resources does not imply receiving proportional compute power. It is recommended to rename the shared resource to something like `nvidia.com/gpu.shared` and enable `failRequestsGreaterThanOne`, so that "1" clearly means one shared access rather than one dedicated card. Reference: [NVIDIA GPU Time-Slicing](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/25.3/gpu-sharing.html), [GPU Operator MIG](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/gpu-operator-mig.html)

Shared GPUs also require additional monitoring of physical card-level XID, GPU memory OOM, and utilization. Billing solely by the number of extended resources requested by a Pod will mislead users, because it does not represent the actual GPU time obtained.

## 9. Classify Notebook Data into Eight Categories

| Data | Needs Persistence | Needs Sharing | Recommended Location |
| --- | --- | --- | --- |
| Notebooks, scripts, configuration | Yes | Collaborate via Git | Git + user Home PVC |
| Shell configuration, small personal files | Yes | No | Per-user RWO/RWOP PVC |
| Python/CUDA runtime environment | Reproducible is sufficient | Yes | OCI image and Lockfile |
| Small team-shared files | Yes | Yes | Permission-controlled RWX file system |
| Raw datasets and training shards | Yes, usually authoritative copies | Yes | Object storage or parallel file system |
| Model weights and Adapters | Yes, must be versioned | Read-shared | Object storage/Model Registry + cache |
| Checkpoints, evaluation results, and Artifacts | Yes, requires lifecycle policy | Shared per project | Object storage, shared file system when necessary |
| Download cache, preprocessing, and Scratch | No, can be rebuilt | Shared within node or not shared | Local NVMe, `emptyDir` |

The most important rule is: **Home PVC is not a data lake, RWX shared disks are not the default destination for all data, and local NVMe is not the only copy.**

## 10. Storage Type Selection Matrix

| Storage Type | Access Mode | Performance Characteristics | Suitable For | Not Suitable For |
| --- | --- | --- | --- | --- |
| SSD block storage PVC | Commonly RWO/RWOP | Low latency, good personal directory experience | User Home, small project workspaces | Multi-node team sharing, large-scale weight replicas |
| Shared file system | RWX | POSIX convenient, performance depends on metadata and backend | Team directories, legacy code, shared checkpoints | Large Home without quotas, hot paths with millions of small files |
| Object storage | API | High durability, versioned, large capacity | Datasets, models, checkpoints, artifacts | Applications relying on full POSIX semantics for random writes |
| Object storage FUSE/CSI | File mount | Convenient to use, but semantics and performance are not equivalent to a local file system | Read-only data, models, and validated access patterns | SQLite, lock files, frequent rename/fsync, small-file storms |
| Node-local NVMe | Node-bound | Best throughput and latency | Model hot cache, data cache, compilation and Scratch | User-only data, checkpoints that cannot be rebuilt |
| `emptyDir` | Pod lifecycle | Simple, can use node disks or memory | Temporary data, `/dev/shm`, session Scratch | Data that must remain after the Pod stops |

The lifecycle of a Kubernetes PersistentVolume is independent of any single Pod; ephemeral volumes such as `emptyDir` follow the Pod lifecycle. For storage with availability-zone or local topology, `WaitForFirstConsumer` allows the volume to be bound only after the Pod selects a topology, reducing scheduling conflicts where "the GPU is in one zone and the PVC is in another." Reference: [Kubernetes Persistent Volumes](https://kubernetes.io/docs/concepts/storage/persistent-volumes/), [Ephemeral Volumes](https://kubernetes.io/docs/concepts/storage/ephemeral-volumes/), [Storage Capacity](https://kubernetes.io/docs/concepts/storage/storage-capacity/)

### Difference Between RWO and RWOP

`ReadWriteOnce` means the volume can be read and written on one node, and does not necessarily strictly restrict it to one Pod; when you need to ensure it is used by only one Pod at a time, you should evaluate whether the CSI driver supports `ReadWriteOncePod`. For most Notebook platforms, relying on the control-plane constraint of "one user server + one PVC" is sufficient, but migration and failure scenarios still require verifying duplicate mount behavior.

## 11. Recommended Directory and Mount Conventions

```text
/home/jovyan        每用户 SSD PVC；Notebook、脚本、配置、小型虚拟环境
/workspace          Git 工作树；可位于 Home 的子目录
/data               只读数据集；对象存储挂载或共享文件系统
/models             只读模型缓存；节点 NVMe 或受控共享缓存
/checkpoints        耐久写入入口；对象存储客户端或共享文件系统
/scratch            emptyDir / 本地 NVMe；可随时删除
/dev/shm            memory-backed emptyDir；供 DataLoader、多进程和框架共享内存
```

Directory names are not the key point; the key is that users can immediately know which locations will be retained, which can be shared, and which will be lost. The login page and terminal prompt should clearly display:

- `/home/jovyan` has capacity quotas and which content will be backed up;
- Whether `/data` and `/models` are read-only and which version they correspond to;
- `/scratch` will be deleted when the workspace is stopped, the node is migrated, or on upgrade;
- Which object storage prefix formal checkpoints must be synchronized to;
- It is forbidden to write tokens, cloud keys, or kubeconfig into Notebook outputs and Git.

## 12. Recommended Storage Tiering

```text
权威层：对象存储
数据集、模型、Adapter、Checkpoint、评估和 Artifact
             │
             ▼
共享层：RWX / 并行文件系统 / 对象 FUSE
团队协作、兼容 POSIX、只读数据入口
             │
             ▼
节点热缓存：Local NVMe
Hugging Face Cache、模型权重、数据分片、构建缓存
             │
             ▼
Pod 临时层：emptyDir / tmpfs
Notebook Scratch、/dev/shm、临时解压和中间结果
```

Cache keys must include at least the model Revision or Digest, data version, Tokenizer version, and conversion code version. Caching only by model name or `latest` may cause users to load the wrong weights.

### How to Implement Model Caching

Common approaches, from simple to complex:

1. Each Notebook downloads directly to its own PVC: simplest, but wastes space through duplication and has slow cold starts;
2. Node-local read-only cache: downloaded once and reused by nodes on the same host, suitable for hot models;
3. DaemonSet or cache proxy pre-warming: the platform controls version, capacity, and eviction;
4. Distributed cache or high-performance shared file system: suitable for large-scale concurrency and multi-node training;
5. OCI/model artifact distribution: unifies digest, permissions, and Registry supply chain, but still requires handling node disk placement.

For the first version, "object storage authoritative copy + node NVMe LRU cache" can be adopted. When the cache misses, validation fails, or a node is lost, the system must be able to rebuild from the authoritative layer.

## 13. Do Not Put All Users into One Huge RWX Home

"All Homes sharing one RWX file system" looks simple to migrate, but common problems include:

- A single user's small files or recursive scans slow down all users;
- POSIX UID/GID, directory permissions, and offboarding recovery are error-prone;
- Cannot independently scale, snapshot, recover, or bill;
- One erroneous command may delete a team-shared directory;
- Metadata latency directly affects Git, Python Import, Conda, and Jupyter startup.

By default, use per-user RWO/RWOP SSD PVCs; content that teams genuinely need to share should be mounted to a separate RWX path. Shared directories should have project-level ACLs, quotas, snapshots, and lifecycle policies.

## 14. Should the Environment Go in the Image or in Home

### Put in the Immutable Image

- OS, CUDA/ROCm, base Python version;
- Core frameworks such as PyTorch/JAX/TensorFlow;
- JupyterLab, VS Code Server, and platform extensions;
- Enterprise certificates, basic debugging tools, and security patches;
- GPU Runtime and system libraries validated for compatibility.

### Put in the Project Lockfile or Personal Directory

- Project Python dependencies and reproducible Lockfile;
- Small, pure-Python, frequently changing experimental packages;
- User configuration, Notebook extension configuration, and Shell configuration.

It is not recommended to install several GiB of dependencies online at every startup, to persistently modify the container root file system, to use mutable `latest` images, or to let users combine unvalidated CUDA, driver, and framework versions on their own.

It is recommended to publish a small number of golden images, pin versions by Digest, and retain image SBOM, vulnerability scan, and CUDA/Driver compatibility records. When users genuinely need new dependencies, validate them in the project Lockfile first, then incorporate them into the next image version.

If the platform cannot control user default behavior: users will install software in `/opt`, `/usr/local`, `/var`, Home, and various cache directories, and explicitly require "restore exactly as it was after stopping, like a personal Linux workstation." Mounting only a Home PVC is no longer a complete answer. For such users, you can provide KubeVirt persistent workstations that save the entire VM root disk on dedicated Ceph RBD, while keeping container Notebooks as the default lightweight mode. Full steps are available at: [Building Persistent GPU Notebooks with KubeVirt and Ceph RBD](../practices/kubevirt-rbd-notebook.md).

## 15. Startup Speed and GPU Node Elasticity

```text
总启动时间
  = 排队/审批
  + GPU 节点扩容
  + 镜像拉取
  + PVC 创建与挂载
  + Secret/配置注入
  + Jupyter/IDE 启动
  + 数据或模型预热
```

Optimization order:

1. First measure each segment, rather than optimizing only the Jupyter process;
2. Place interactive user Pods in a dedicated GPU node pool, isolated with Taints/Tolerations;
3. Pre-pull golden images to avoid tens of GiB of CUDA images blocking the first user;
4. Keep a small amount of Warm Capacity for peak hours in the morning, rather than scaling all GPUs to zero;
5. Use a user scheduler to pack idle Pods as tightly as possible, releasing whole nodes for the Autoscaler to scale down;
6. Provision GPU and Home PVC capacity in the same availability zone;
7. Monitor model cache and image cache separately; do not merge them into a single startup phase.

Interactive Notebooks are not suitable for indefinite queuing in Kueue. A more reasonable approach is to reserve a small quota and a clear maximum session time for the interactive pool, while formal training is submitted by the Notebook to a Job queue managed by Kueue.

## 16. Idle Culler Is Not Simply About Whether the Browser Is Open

Idle reclamation should at least distinguish:

- Browser has no activity, but the Kernel is computing;
- Kernel is idle, but the terminal has processes;
- GPU is allocated but utilization is near zero for a long time;
- User closed the page, but mistakenly started background training inside the Notebook;
- Workspace has been saved, so the Pod can be stopped while the PVC is retained;
- Maximum session time has been exceeded, so the session must be terminated and the user notified to migrate the task.

Recommended strategy:

1. Warn in stages before stopping;
2. Check Jupyter Activity, Kernel, Terminal, and platform Jobs simultaneously;
3. Save user work first, then stop the Workspace Pod;
4. Retain the Home PVC, but not GPU and node-local Scratch;
5. Set different Idle Timeouts for shared GPU, MIG, and whole-card;
6. Set a maximum continuous session time to prevent background processes from bypassing governance;
7. Provide a golden path for one-click conversion to a Job for formal tasks, rather than making users disable the Culler.

The cost report should at least distinguish Allocation, actual GPU utilization, Active User Time, and Idle Allocated Time. Counting only "how many cards were allocated" cannot determine whether the platform is effective.

## 17. Security Isolation

A Notebook is a long-lived Shell with a browser entry point, terminal, and arbitrary code execution capability, and should be governed as a high-risk workload.

### Identity and Permissions

- Enterprise OIDC/SSO, disable shared accounts;
- Map users and groups to team Namespaces or Workspaces;
- Default `automountServiceAccountToken: false`;
- Use a dedicated least-privilege identity or platform API when submitting Jobs; do not issue administrator kubeconfig to Notebooks;
- Use Workload Identity and short-lived credentials for cloud resources; do not store long-term Access Keys in Home.

### Pod and Node

- Use Pod Security Admission, Seccomp, non-Root users, and approved images;
- Prohibit `privileged`, HostPath, Host Network, Docker Socket, and host PID;
- Separate untrusted tenants from production services into different node pools; use gVisor, Kata, or a separate cluster when necessary;
- GPU Runtime, MIG, and Time-Slicing only solve device allocation; they do not constitute a full tenant sandbox.

### Network and Data

- Deny inbound and outbound traffic by default in the Namespace, and allowlist object storage, Git, Registry, and Pipeline API access;
- Block access to cloud instance metadata and unrelated Kubernetes control-plane endpoints;
- Mount datasets as read-only where possible, and grade permissions by project and data level;
- Use an external Secret system or short-lived tokens for Secrets, avoiding display in environment variables, Notebook outputs, and logs;
- Externally shared Notebooks must go through desensitization and output cleanup.

## 18. Observability and Auditing

Each Workspace Pod should carry unified labels for user, team, Workspace, Profile, image Digest, cost center, and GPU mode.

| Category | Metrics |
| --- | --- |
| Startup | P50/P95 startup time, node scaling, image pull, PVC Attach, startup failure rate |
| Usage | Active Workspaces, active users, Kernel/Terminal activity, session duration |
| GPU | Allocation, SM, GPU memory, power, XID, shared-card physical utilization, Idle GPU Hours |
| Storage | PVC usage, inodes, IOPS, latency, throughput, object requests, cache hit rate |
| Stability | OOM, Eviction, Pod Restart, Node Drain, Workspace recovery success rate |
| Cost | User/team/Profile GPU hours, storage GiB-month, cross-zone traffic, cache savings |

Auditing should at least retain: who created, started, stopped, deleted, or changed a Workspace; which image, Profile, and data mounts were selected; who requested a whole card or multiple cards; which Job was submitted by the Notebook and under what identity; who accessed restricted data; and when administrators upgraded the control plane, images, CSI, and GPU components.

## 19. Three Reference Architectures

### A. 10–50 Person R&D Team

```text
OIDC → JupyterHub → KubeSpawner
                    ├─ CPU Pool
                    └─ GPU Pool：Shared Dev + Full GPU

每用户 RWO SSD PVC 50–200 GiB
S3 兼容对象存储：数据、模型、Checkpoint
节点 NVMe：模型和数据缓存
MLflow + Job/TrainJob + Kueue：正式实验
```

Characteristics: minimal components to establish a complete boundary. Do not introduce shared RWX initially unless there is a clear collaboration need; shared GPUs are provided only to trusted R&D environments.

### B. Enterprise Multi-Tenant AI Platform

```text
企业 IdP → API Gateway / Workspace Portal
              │
              ├─ JupyterHub 或受支持的 Kubeflow 发行版
              ├─ Team Namespace / Quota / NetworkPolicy
              ├─ CPU / MIG / Full GPU Resource Catalog
              ├─ RWO Home + Team RWX + Object Storage + NVMe Cache
              └─ Pipeline / Trainer / Ray / Kueue / MLflow / GitOps
```

Characteristics: resource requests, data permissions, images, and costs are all governed per team. High-risk tenants enter a stronger RuntimeClass or a dedicated node pool; Notebooks have no permission to directly modify production.

### C. Single-Cloud Small Team

```text
Cloud IAM → Managed Workbench
             ├─ CPU/GPU Instance Profile
             ├─ Per-space Persistent Volume
             ├─ Object Storage / Managed Dataset
             └─ Managed Training Job / Pipeline
```

Characteristics: prioritize reducing platform operations, with focus on controlling Idle Shutdown, private network, instance quotas, persistent volume costs, and cross-zone data. As tenant isolation, custom scheduling, or multi-cloud needs grow, evaluate migrating to a Kubernetes workspace platform.

## 20. An Example Platform Specification Contract

Do not let users fill in a full Pod directly. The internal platform can maintain a catalog object similar to the one below, then render it into JupyterHub Profiles, Kubeflow Workspaces, or managed service templates:

```yaml
apiVersion: platform.example.com/v1alpha1
kind: WorkspaceProfile
metadata:
  name: gpu-full-llm-dev
spec:
  displayName: LLM 单卡开发
  image: registry.example.com/ai/jupyter-pytorch@sha256:<digest>
  resources:
    requests:
      cpu: "8"
      memory: 64Gi
      nvidia.com/gpu: "1"
    limits:
      cpu: "16"
      memory: 96Gi
      nvidia.com/gpu: "1"
  placement:
    nodePool: gpu-interactive
    gpuMode: exclusive
  storage:
    home:
      class: notebook-rwo-ssd
      size: 200Gi
      mountPath: /home/jovyan
    scratch:
      type: LocalEphemeral
      sizeLimit: 500Gi
      mountPath: /scratch
    datasets:
      readOnly: true
      mountPath: /data
  session:
    idleTimeout: 90m
    maxDuration: 12h
  security:
    serviceAccountToken: false
    networkProfile: research-restricted
```

This is not a recommendation to immediately invent a new CRD. For the first version, the same contract can be expressed using JupyterHub Helm Values in Git, Kubeflow templates, or internal Portal configuration. The key is that users see a stable product specification, while the platform internally handles StorageClass, Resource Names, Taints, and network policies.

## 21. What a PoC Must Test

### Functional Testing

- OIDC login, logout, user disablement, and group permission changes;
- CPU, shared GPU, MIG, and full-GPU Profile creation and stopping;
- Home PVC retention after stop, remounting, and expansion;
- Least-privilege access for Git, Registry, object storage, MLflow, and Job APIs;
- Whether old workspaces, old PVCs, and username mappings remain compatible after image upgrades.

### Performance Testing

- P50/P95 startup time for cold nodes, hot nodes, cold images, and hot images;
- First download of the target model versus cache-hit load time;
- Git Checkout, Python Import, and small-file performance on the Home PVC;
- Object storage sequential reads, large numbers of small objects, and FUSE metadata behavior;
- Local NVMe cache writes, eviction, and multi-user concurrency;
- Under Time-Slicing, the impact of one user's OOM, full load, or restart on other users.

### Failure and Recovery Testing

- Delete the Workspace Pod and verify Home recovery and Scratch loss warnings;
- Drain or replace GPU nodes and verify PVC topology and rescheduling;
- Brief unavailability of CSI, object storage, Registry, or IdP;
- PVC full, inode full, local disk full, and image pull failure;
- Restore a user's Home from a VolumeSnapshot;
- Restore official Checkpoints from object storage, not just Notebook files.

### Security Testing

- Attempt to access other users' PVCs, Namespaces, ServiceAccounts, and Secrets;
- Attempt to access instance metadata, the Kubernetes API, production databases, and unauthorized object prefixes;
- Attempt to use privileged containers, HostPath, Host Network, and unapproved images;
- Check whether Notebook outputs, terminal history, Git history, and logs leak Tokens.

## 22. Backup and Lifecycle

### Home PVC

- CSI `VolumeSnapshot` is suitable for fast recovery, but depends on CSI driver support;
- Snapshots may still reside on the same storage system or failure domain as the source volume and cannot automatically be treated as off-site backups;
- Critical Notebooks and scripts should still be committed to Git;
- Establish an archival and deletion approval process for departing and long-term inactive users.

### Object Storage

- Enable versioning, retention, and lifecycle policies for data, models, and Checkpoints;
- Isolate Buckets/Prefixes by project and environment;
- Regularly restore from backups rather than only verifying upload success;
- Have cleanup policies for large failed uploads and stale Checkpoints.

### Local Cache and Scratch

- Explicitly treat as reconstructable data and exclude from backups;
- Set capacity watermarks, LRU/TTL, inode alerts, and garbage collection;
- Do not promise migration before node drain;
- Cache misses must safely fall back to the authoritative storage.

Reference: [Kubernetes Volume Snapshots](https://kubernetes.io/docs/concepts/storage/volume-snapshots/)

## 23. Common Anti-Patterns

| Anti-Pattern | Consequence | Correction |
| --- | --- | --- |
| Each user permanently holds an exclusive full GPU | Large amounts of idle GPU hours | Default to CPU/shared/MIG; full GPU on demand with automatic stop |
| Formal training runs in the Notebook Kernel | Page, Culler, Pod, or node failure loses the job | Submit Job/TrainJob/RayJob after debugging is complete |
| Models and data are all copied into the Home PVC | High cost, version confusion, slow migration | Authoritative copy in object storage + shared read-only/node cache |
| Everyone shares one RWX Home | Metadata contention, permission and recovery difficulties | Per-user RWO; team-shared content in a separate RWX |
| Local NVMe holds the only Checkpoint | Node failure means data loss | Stage locally, asynchronously commit to object storage, and verify the completion marker |
| Users freely choose images and GPU counts | Compatibility, supply chain, and capacity become uncontrollable | Versioned Profile Catalog + approval |
| Time-Slicing treated as strong isolation | OOM, failures, and performance affect each other | Use MIG, full GPU, or a dedicated node pool |
| Notebook holds a cluster admin Token | Arbitrary code can control production | Least-privilege Job Broker/API; do not mount SA Token by default |
| Snapshot treated as the only backup | Same failure domain or accidental deletion may still make recovery impossible | Git + independent backup + recovery drills |
| Idle judged only by browser connection | Kills compute incorrectly or never reclaims background processes | Joint judgment of Kernel, Terminal, GPU, and maximum time limit |

## 24. Selection Scoring Table

It is recommended to assign weights to the following dimensions first, then score with actual PoC data:

| Dimension | Suggested Weight | Acceptance Example |
| --- | ---: | --- |
| Identity and multi-tenant security | 20% | OIDC, least privilege, NetworkPolicy, and auditing all pass |
| GPU isolation and resource governance | 15% | Profile, MIG/full GPU, quotas, and idle reclamation are verifiable |
| Storage and data path | 20% | Home recovery, object versioning, local cache, and failure tests pass |
| Developer experience | 15% | P95 startup, IDE, Git, dependencies, and debugging paths meet targets |
| Job handoff and MLOps | 10% | One-click submission of formal jobs with associated Run, code, and artifacts |
| Observability and cost | 10% | Attribution from user to GPU/storage/cost is possible |
| Operations and upgrades | 10% | Upgrade, backup, rollback, compatibility matrix, and Owner are clear |

Similar total scores do not mean equivalent products. If any one of security, data recovery, or GPU isolation fails to meet a hard threshold, it should not be offset by a better UI score.

## 25. Phased Rollout

### Phase 1: Establish a Usable Entry Point

- JupyterHub or a supported Workbench control plane;
- OIDC, per-user RWO PVC, and two Profiles: CPU and full GPU;
- Golden image, object storage SDK, and basic network policies;
- Stop Workspace while retaining Home; prohibit formal training from remaining in the Notebook.

### Phase 2: Improve Utilization

- Shared GPU or MIG Profile;
- Idle Culler, maximum session time limit, and image pre-pulling;
- Local NVMe model/data cache;
- Dashboards for GPU, PVC, startup latency, and cost.

### Phase 3: Platform-Level Governance

- Team Namespace, Quota, approval, and cost center;
- Kueue + TrainJob/RayJob/Pipeline job handoff;
- Shared data mounts, model Registry, experiment tracking, and GitOps;
- Image supply chain, VolumeSnapshot/backup, and recovery drills.

### Phase 4: Scale and Evolve

- Multi-cluster or multi-region Workspace routing;
- Finer-grained GPU Profiles, DRA evaluation, and topology awareness;
- Cache warming, hotspot prediction, and capacity reservation;
- Migration from Kubeflow Notebooks v1 to Workspaces v2 or other platforms.

## 26. Go-Live Checklist

- [ ] Notebooks are only for interactive development; formal long-running tasks have a separate execution system.
- [ ] Users can only select approved image, resource, and mount Profiles.
- [ ] The isolation and billing semantics of full GPU, MIG, and Time-Slicing have been explained to users.
- [ ] Lifecycles are separated for per-user Home, team shared storage, object storage, cache, and Scratch.
- [ ] Authoritative copies of datasets, models, and Checkpoints are not on Home or local NVMe.
- [ ] Home PVC has capacity alerts, snapshot/backup policies, and recovery drills.
- [ ] Workspace Pods have no admin Token, privileged mode, or HostPath by default.
- [ ] Network defaults to deny, allowing only Git, Registry, object storage, and platform APIs.
- [ ] Idle Culler does not kill formal jobs and can reclaim idle GPUs.
- [ ] Monitoring can trace from user, Workspace, and Profile to GPU, storage, and cost.
- [ ] PoCs have been run for cold start, model cache, PVC topology, node replacement, and shared GPU interference.
- [ ] Kubeflow or JupyterHub major version upgrades include PVC, username, and API migration verification.

## Further Reading

- [Kubeflow Notebooks Overview](https://www.kubeflow.org/docs/components/notebooks/overview/)
- [Kubeflow Notebook Container Images](https://www.kubeflow.org/docs/components/notebooks/container-images/)
- [Kubeflow 26.03.1 Release Announcement](https://blog.kubeflow.org/kubeflow-26.03-release/)
- [Zero to JupyterHub: Optimizations](https://z2jh.jupyter.org/en/stable/administrator/optimization.html)
- [Zero to JupyterHub: Customizing User Resources](https://z2jh.jupyter.org/en/latest/jupyterhub/customizing/user-resources.html)
- [Kubernetes Persistent Volumes](https://kubernetes.io/docs/concepts/storage/persistent-volumes/)
- [Kubernetes Ephemeral Volumes](https://kubernetes.io/docs/concepts/storage/ephemeral-volumes/)
- [Kubernetes Volume Snapshots](https://kubernetes.io/docs/concepts/storage/volume-snapshots/)
- [NVIDIA GPU Operator: Time-Slicing](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/25.3/gpu-sharing.html)
- [NVIDIA GPU Operator: MIG](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/gpu-operator-mig.html)
- [AI Data, Storage, and Cache](../data-storage.md)
- [GPU and Heterogeneous Resource Scheduling](../gpu-scheduling.md)
- [MLOps and Platform Engineering](../mlops.md)
- [GPU Cost and Capacity Planning](../cost-capacity.md)
- [AI Platform Security and Governance](../security-governance.md)
