---
title: "GPU Node Software Stack, Initialization, and Acceptance"
description: "Build maintainable GPU nodes from firmware, kernel, drivers, container runtime, to Kubernetes device integration"
status: stable
last_reviewed: 2026-08-02
---

# GPU Node Software Stack, Initialization, and Acceptance

A GPU node being able to join Kubernetes does not mean it is ready for production AI. True acceptance must cover firmware, PCIe/NUMA, kernel drivers, container runtime, device integration, monitoring, networking, and actual frameworks.

## 1. Software Stack Boundaries

```text
训练框架 / 推理引擎
PyTorch、JAX、vLLM、SGLang、TensorRT-LLM
                  │
用户态计算与通信库
CUDA/ROCm、cuDNN、NCCL/RCCL、UCX/NIXL
                  │
容器设备注入
Container Toolkit、CDI、RuntimeClass
                  │
Kubernetes 设备管理
Device Plugin 或 DRA Driver
                  │
节点管理
GPU Operator、NFD、监控与健康控制器
                  │
宿主机
固件、BIOS、内核、驱动、PCIe、NUMA、GPU、NIC
```

The CUDA Toolkit inside a container can be newer than the host driver to a certain extent, but the specific compatibility range is subject to the vendor matrix. Do not infer that any arbitrary combination of CUDA, PyTorch, and NCCL is supported just because `nvidia-smi` runs.

## 2. What to Pin in the Node Image

It is recommended to include the following in an immutable node image or declarative node configuration:

- OS distribution and patch level;
- Kernel, boot parameters, and cgroup mode;
- GPU/NIC firmware and driver policy;
- containerd/CRI-O configuration;
- Time synchronization, DNS, certificates, and Registry CA;
- Disk partitioning, logging, and local cache directories;
- kubelet reservations, eviction thresholds, and maximum Pod count;
- Node Feature Discovery and stable platform label sources;
- Security hardening, auditing, and remote access policy.

Drivers can be installed containerized via the GPU Operator or pre-installed in the node image. Both approaches are viable; the key is to have exactly one authoritative source and a clear upgrade, restart, and rollback sequence.

## 3. Firmware and BIOS

Before installing Kubernetes, confirm:

- GPU, NIC, motherboard, and BMC firmware are in a supported combination;
- IOMMU/VT-d/AMD-Vi is configured per SR-IOV, Kata, or passthrough requirements;
- Above 4G Decoding and Resizable BAR are enabled per the hardware reference architecture;
- NUMA, CPU SMT, power, and performance modes have clear standards;
- PCIe link width and speed match the design;
- NVLink/NVSwitch Fabric Manager status is healthy;
- Secure Boot is consistent with the driver module signing policy.

These settings are constrained by the specific server and accelerator; do not copy a generic BIOS template and skip vendor validation.

## 4. Kernel and Drivers

Before upgrading drivers, at minimum verify:

| Layer | Compatibility to Confirm |
| --- | --- |
| OS/Kernel | Whether the vendor driver is supported, and whether DKMS/KMM can build |
| GPU Driver | GPU model, firmware, CUDA/ROCm version |
| Container Toolkit | containerd/CRI-O and Runtime configuration |
| Device Plugin/DRA | Kubernetes API and driver version |
| Communication Libraries | NCCL/RCCL, OFED, UCX, RDMA Core |
| Framework Images | Binary build targets of PyTorch/JAX/vLLM |

Even a minor kernel update can trigger driver module rebuilds. Canary nodes must run full compute, P2P, RDMA, and framework tests, not just observe that the DaemonSet is Ready.

## 5. Container Runtime and CDI

The Container Device Interface uses a standardized JSON specification to describe the device nodes, mounts, and environment variables a container should receive. It reduces the need for runtime-specific Hooks, but it does not replace Device Plugin/DRA scheduling and allocation.

Check containerd:

```bash
containerd --version
crictl info
crictl version
```

Check the CDI specifications on the node:

```bash
find /etc/cdi /var/run/cdi -maxdepth 2 -type f -print 2>/dev/null
```

In production, record which component generates the CDI files, when they are refreshed, and the rollback behavior. After device reconfiguration, stale CDI Specs may give containers incorrect device paths.

## 6. GPU Operator Installation Modes

Common NVIDIA GPU Operator components include:

- Driver Manager;
- Container Toolkit;
- Device Plugin or DRA Driver;
- GPU Feature Discovery;
- DCGM and DCGM Exporter;
- MIG Manager;
- Node Feature Discovery;
- Validation workloads and upgrade controls.

Before installation, choose:

1. Whether drivers are installed by the Operator or pre-installed on the host;
2. Whether the container toolkit already has an authoritative source;
3. Device Plugin or DRA;
4. Whether to enable MIG, Time-Slicing, or MPS;
5. Who collects DCGM metrics;
6. Whether OpenShift, Kata, vGPU, RDMA, etc. require dedicated configuration.

The AMD GPU Operator can similarly manage drivers, Device Plugin, node labels, metrics, and health tests. Do not hardcode NVIDIA component names as platform-generic APIs.

## 7. kubelet Resource Reservations

GPU nodes still need sufficient CPU and memory to run kubelet, CNI, CSI, Device Plugin, monitoring, and logging agents. It is recommended to specify:

```yaml
kubeReserved:
  cpu: 1
  memory: 2Gi
systemReserved:
  cpu: 1
  memory: 2Gi
evictionHard:
  memory.available: 1Gi
  nodefs.available: 10%
```

The example only conveys the approach; actual values should be measured based on node scale, DaemonSets, and maximum Pod count. Under-reserving can result in idle GPUs while the node evicts workloads due to memory or disk pressure.

## 8. CPU, NUMA, and Topology

Data loading, tokenization, communication, and inference gateways all consume CPU. GPU workloads should, as much as possible, ensure:

- CPU cores and the target GPU are on nearby NUMA nodes;
- GPU and RDMA NIC have ideal PCIe paths;
- `/dev/shm`, pinned memory, and HugePages satisfy communication libraries;
- CPU Manager and Topology Manager policies are validated with real workloads;
- Resource requests of multi-container Pods do not break the overall topology.

Inspect node topology:

```bash
lscpu
numactl --hardware
lspci -tv
nvidia-smi topo -m
```

Different vendors use their own diagnostic tools, but the troubleshooting goal is the same: confirm the actual interconnect paths between devices, not just look at Kubernetes labels.

## 9. Local Disk and Shared Memory

Cold-starting large models may simultaneously consume container image layers, model weights, and temporary conversion space. The node needs planning for:

- containerd data directory capacity and inodes;
- A dedicated local model/data cache directory;
- emptyDir `sizeLimit` and ephemeral-storage requests;
- `/dev/shm` memory-backed volumes;
- Log rotation and failed Pod cleanup;
- Cache watermarks, eviction, and prewarming mechanisms.

```yaml
volumes:
  - name: dshm
    emptyDir:
      medium: Memory
      sizeLimit: 16Gi
containers:
  - name: worker
    volumeMounts:
      - name: dshm
        mountPath: /dev/shm
```

## 10. Node Labels and Taints

Hardware facts should be generated by NFD, GPU Feature Discovery, or vendor Node Labellers; platform abstraction labels are maintained by the platform team.

Avoid having workloads depend directly on a large number of vendor-internal labels. A stable mapping can be established:

```text
厂商发现标签
  nvidia.com/gpu.product=NVIDIA-H100-80GB-HBM3
        │
        ▼
平台标签
  platform.example.com/accelerator-class=h100-80g
```

When upgrading discovery components, the platform label contract can remain stable.

## 11. Layered Acceptance

### Layer 1: Hardware and Drivers

```bash
nvidia-smi
nvidia-smi -q
nvidia-smi topo -m
```

Confirm GPU count, ECC, temperature, power, PCIe, NVLink, and error records.

### Layer 2: Kubernetes Inventory

```bash
kubectl get nodes
kubectl describe node <gpu-node>
kubectl get pods -A -o wide --field-selector spec.nodeName=<gpu-node>
```

Check capacity, allocatable resources, labels, Taints, RuntimeClass, and device components.

### Layer 3: Container Devices

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: gpu-smoke-test
spec:
  restartPolicy: Never
  containers:
    - name: cuda
      image: nvcr.io/nvidia/k8s/cuda-sample:vectoradd-cuda12.5.0
      resources:
        limits:
          nvidia.com/gpu: "1"
```

The success criterion is not just Pod Completed; also check allocated devices, logs, and DCGM Pod mapping.

### Layer 4: Inter-Device Interconnect

Run P2P, NVLink/NVSwitch, and NCCL Tests. For multi-node, add RDMA Perftest and NCCL All-Reduce.

### Layer 5: Real Frameworks

Using production PyTorch/JAX images, complete:

- Allocating tensors and executing Kernels;
- Single-node multi-GPU Collectives;
- Short multi-node training runs;
- Model loading and inference;
- Checkpoint save and restore.

## 12. Health and Auto-Isolation

A distinction must be made between:

- Transient application errors;
- Device errors such as GPU XID/ECC/Row Remap;
- PCIe/NVLink/NIC failures;
- Driver or DaemonSet anomalies;
- Node OS, memory, or disk issues.

The automation flow can be:

```text
检测异常
  → 标记设备或节点不可调度
  → 停止新工作负载准入
  → 保存证据和诊断
  → 尝试受控恢复/重启
  → 运行节点验收
  → 恢复调度或进入维修
```

Do not let a controller infinitely restart a long-running training job on a node with hardware faults.

## 13. Upgrade Process

1. Freeze the target version matrix;
2. Validate on experimental nodes with identical hardware;
3. Cordon and drain Canary nodes;
4. Upgrade OS/kernel/driver/Operator;
5. Run the five-layer acceptance;
6. Run representative training and inference benchmarks;
7. Observe errors, performance, and power consumption;
8. Roll out batch by batch according to failure domains;
9. Keep the old node image and rollback path.

Driver changes can alter performance; even if the API is fully compatible, results must be compared against historical baselines.

## 14. Node Acceptance Record Template

```text
Node:
Hardware SKU / Serial:
BMC / BIOS / GPU / NIC firmware:
OS / kernel:
containerd / kubelet:
GPU driver / CUDA compatibility:
GPU Operator / Device Plugin or DRA:
NIC / RDMA driver:
GPU count and health:
PCIe / NVLink / NVSwitch:
DCGM diagnostics:
NCCL / RDMA / storage baseline:
Representative training:
Representative inference:
Result / evidence URI:
```

## 15. Production Checklist

- [ ] Node image, firmware, and BIOS have controlled versions.
- [ ] Drivers and Container Toolkit have exactly one authoritative installation source.
- [ ] containerd, CDI, and Device Plugin/DRA allocation paths are validated.
- [ ] kubelet reserves sufficient CPU, memory, and disk for system components.
- [ ] NUMA, GPU, NIC, and NVLink/PCIe topology is queryable.
- [ ] Local model cache, images, and logs will not exhaust disk.
- [ ] Five-layer acceptance can be automatically repeated and evidence saved.
- [ ] GPU hardware failures automatically stop scheduling and enter the repair process.
- [ ] Canary nodes cover every production hardware type.
- [ ] Upgrade acceptance includes real performance regression testing.

## Further Reading

- [NVIDIA GPU Operator](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/)
- [NVIDIA GPU Operator Platform Support](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/platform-support.html)
- [AMD GPU Operator](https://instinct.docs.amd.com/projects/gpu-operator/en/latest/)
- [Container Device Interface](https://github.com/cncf-tags/container-device-interface)
- [Kubernetes Topology Manager](https://kubernetes.io/docs/tasks/administer-cluster/topology-manager/)
- [Kubernetes Node Allocatable](https://kubernetes.io/docs/tasks/administer-cluster/reserve-compute-resources/)
