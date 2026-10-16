---
title: "Device Plugin, CDI, and DRA"
description: "Understanding the responsibilities, APIs, and migration paths of Kubernetes device discovery, container injection, and dynamic resource allocation"
status: evolving
last_reviewed: 2026-08-02
---

# Device Plugin, CDI, and DRA

When Kubernetes manages GPUs, NICs, FPGAs, and AI ASICs, three mechanisms are often confused: Device Plugin is responsible for exposing devices to kubelet as extended resources, CDI describes how containers gain access to devices, and Dynamic Resource Allocation (DRA) provides a richer API for device selection and allocation.

They solve related but distinct problems.

## 1. Responsibility Comparison

| Mechanism | Primary Question | Typical Object or File |
| --- | --- | --- |
| Device Plugin | How many allocatable devices are on the node, and which devices are assigned to a container | Extended resources, kubelet Device Plugin API |
| CDI | How the container runtime injects device nodes, mounts, and environment variables | CDI JSON Spec |
| DRA | What device attributes a workload needs, and how to declare and bind them | DeviceClass, ResourceSlice, ResourceClaim |
| NFD/Node Labeller | What hardware or software characteristics a node has | Node Label |
| Kueue | Which workload can use how much device quota right now | Workload, ClusterQueue, ResourceFlavor |

DRA does not replace driver installation, CDI is not responsible for scheduling, and Kueue does not select specific devices.

## 2. How Device Plugin Works

Typical flow:

```text
厂商 Device Plugin DaemonSet
  → 在每个节点发现设备
  → 向 kubelet 注册资源名
  → kubelet 更新 Node Capacity/Allocatable
  → Pod 通过 resources.limits 请求整数数量
  → scheduler 选择有足够扩展资源的节点
  → kubelet 调用 Allocate
  → Runtime 获得设备节点、挂载、环境变量或 CDI 设备名
```

Request example:

```yaml
resources:
  requests:
    nvidia.com/gpu: "2"
  limits:
    nvidia.com/gpu: "2"
```

Advantages of Device Plugin:

- Stable API and mature ecosystem;
- Simple Pod specification;
- Scheduler, quota, and monitoring have broad support for extended resources;
- Suitable for whole-card or pre-configured MIG/shared resources.

Main limitations:

- Resources are usually just integer counts;
- Difficult to express per-device attributes and cross-device relationships;
- Complex sharing and dynamic reconfiguration depend on vendor-private mechanisms;
- Limited ability to jointly allocate multiple related device types;
- Selection logic often degenerates into node labels.

## 3. How CDI Works

A conceptual CDI Spec:

```json
{
  "cdiVersion": "0.8.0",
  "kind": "vendor.example/device",
  "devices": [
    {
      "name": "device0",
      "containerEdits": {
        "deviceNodes": [
          {"path": "/dev/example0"}
        ]
      }
    }
  ]
}
```

The value of CDI is moving device injection from runtime-specific hooks toward a standardized description. Common contents include:

- Linux Device Node;
- Host file or directory mounts;
- Environment variables;
- Hooks;
- Qualified names for devices from vendors such as Intel and NVIDIA.

Operational focus:

- Who generates the CDI Spec;
- File directory and permissions;
- When to refresh after device reconfiguration;
- Whether containerd/CRI-O has the corresponding version enabled;
- Whether stale Specs reference devices that no longer exist;
- Whether RuntimeClass uses the same CDI path.

## 4. DRA API Model

Core roles of DRA:

```text
设备厂商 / Driver
  └── ResourceSlice：发布设备库存、属性和容量

集群管理员
  └── DeviceClass：定义可申请的设备类别和选择规则

工作负载作者
  ├── ResourceClaimTemplate：随 Pod 创建 Claim
  └── ResourceClaim：一次具体设备请求

scheduler + kubelet + DRA Driver
  └── 选择、绑定、准备、注入和回收设备
```

Conceptual DeviceClass example:

```yaml
apiVersion: resource.k8s.io/v1
kind: DeviceClass
metadata:
  name: high-memory-gpu
spec:
  selectors:
    - cel:
        expression: device.attributes["gpu.example.com"].memoryGiB >= 80
```

Specific API fields are subject to the target Kubernetes version and Driver documentation. DRA advanced the core API to GA in Kubernetes 1.34, and subsequent releases continue to add capabilities such as sharing, Workload ResourceClaim, and device health.

References: [Kubernetes 1.34 DRA GA](https://kubernetes.io/blog/2025/09/01/kubernetes-v1-34-dra-updates/), [Kubernetes 1.36 DRA](https://kubernetes.io/blog/2026/05/07/kubernetes-v1-36-dra-136-updates/)

## 5. What DRA Expresses Beyond Node Labels

Traditional approach:

```yaml
nodeSelector:
  nvidia.com/gpu.product: NVIDIA-H100-80GB-HBM3
resources:
  limits:
    nvidia.com/gpu: "1"
```

Node labels describe "a certain type of device exists on the node," but cannot guarantee that the specific device assigned has a particular attribute. DRA can associate attributes with each Device and supports:

- Selection by GPU memory, model, firmware, or capability;
- Multiple candidate requests and fallback;
- Sharing semantics across multiple containers or Pods;
- Topology relationships among devices such as GPUs and NICs;
- Configurable capacity or partitioning;
- Workload-level Claim lifecycle;
- More precise device health and status.

Whether these are actually supported depends on the Kubernetes version and the vendor DRA Driver; functionality should not be promised merely because the upstream API exists.

## 6. ResourceClaim Lifecycle

Must verify:

1. When the Claim is created;
2. When the scheduler selects devices;
3. Whether the Claim is reused after Pod deletion, failure, and recreation;
4. How allocation state is recovered when the Driver restarts;
5. How Claims are handled after a node becomes NotReady;
6. Whether multi-Pod Workloads can hold devices as a whole;
7. When devices become reallocatable after Claim deletion;
8. Whether state remains consistent after control-plane backup restore.

Stateful device allocation cannot be validated with a single "Pod can run" smoke test.

## 7. How to Choose Between Device Plugin and DRA

| Scenario | Recommendation |
| --- | --- |
| Single model, whole-card exclusive, stable ecosystem | Device Plugin remains appropriate |
| Existing MIG/shared resource naming that runs stably | Do not force migration just to chase novelty |
| Need device attribute selection and candidate fallback | Evaluate DRA |
| Joint selection of multi-device topology such as GPU and NIC | Prioritize validating DRA Driver capabilities |
| Vendor only supports Device Plugin | Use Device Plugin |
| DRA not yet compatible with node autoscaling | Keep Device Plugin or separate node pools |
| New platform and vendor provides supported DRA | Introduce gradually on Canary nodes |

DRA is not an immediate replacement for Device Plugin, but rather the long-term evolution direction of the device API. Production platforms can run both modes in parallel across different node pools, but the same device usually cannot be managed by two Drivers simultaneously.

## 8. Migration Strategy

### Phase 1: Inventory and Compatibility

- Pin Kubernetes, Driver, Operator, and Runtime versions;
- Confirm vendor support, not just an experimental repository;
- List Kueue, quota, policy, and monitoring that depend on extended resource names;
- Validate autoscaling, RuntimeClass, MIG/sharing, and multi-NIC combinations.

### Phase 2: Dedicated Node Pool

- Prepare a DRA Canary node pool;
- Do not run Device Plugin on the same devices;
- Use new Workload Templates;
- Compare resource inventory, Pod status, and billing attribution;
- Inject Driver restart, node restart, and Claim deletion failures.

### Phase 3: Dual-Stack Platform API

The platform interface can temporarily generate both:

- Device Plugin's `resources.limits`;
- DRA's ResourceClaimTemplate.

Selection is determined by Accelerator Flavor or Runtime version; users do not need to manually maintain two complex manifest sets.

### Phase 4: Pool-by-Pool Migration

Migrate by hardware model and business risk, retaining the ability to roll back to old node pools. Do not replace Kubernetes, drivers, DRA, and the training framework all at once in a single cluster upgrade.

## 9. Relationship with Queues and Scheduling

Kueue quotas may still be expressed in terms of resource Flavors, while DRA Claims select specific devices. The platform must ensure:

- Admission resource accounting is consistent with actual device counts;
- Gang/PodGroup does not partially allocate devices and then wait indefinitely;
- Topology constraints consider both Workload and Device;
- Claims can be correctly released or reused during preemption;
- The target cluster has the same DeviceClass contract before multi-cluster distribution.

The Workload/PodGroup and ResourceClaim integration in Kubernetes 1.36 indicates this layer is still evolving rapidly; the target version and Feature State should be clearly documented.

## 10. Observability

At minimum, collect:

- ResourceSlice count and last update time;
- DeviceClass, Claim, and Allocation status;
- Claim Pending/failure reasons and duration;
- Driver Controller and Node Plugin errors;
- Correlation of Pod, container, Claim, and physical device IDs;
- Device health, shared capacity, and actual utilization;
- Allocations not released after deletion;
- Driver Reconcile and API latency.

When using Device Plugin, a mapping from Pod UID to device UUID should also be established; GPU metrics must not be aggregated only at the node level.

## 11. Failure Scenarios

| Failure | Behavior to Verify |
| --- | --- |
| Device Plugin/Node Plugin restart | Running containers are unaffected; inventory recovers |
| DRA Controller restart | Claim state can be recovered without duplicate allocation |
| kubelet restart | Pod and device allocation remain consistent |
| Sudden node power loss | Devices are not permanently leaked |
| Device health degrades | Stop new allocations and retain diagnostics |
| Claim accidentally deleted | Owner and admission policy prevent or safely handle it |
| API Server/etcd recovery | ResourceSlice/Claim consistent with actual node state |
| Driver upgrade failure | Rollback possible and old Claims remain readable |

## 12. Security Boundaries

- Device Plugin, DRA Node Plugin, and CDI generators typically have host privileges;
- Restrict their image sources, hostPath, ServiceAccount, and upgrade permissions;
- Do not allow tenants to arbitrarily create system-level DeviceClasses or configure Drivers;
- CEL selection rules in DeviceClass should be reviewed;
- The CDI Spec directory should only be writable by trusted components;
- Device passthrough, sharing, and Kata Runtime require independent threat models.

## 13. Production Checklist

- [ ] Can distinguish between Driver installation, device discovery, container injection, and quota admission.
- [ ] The choice of Device Plugin or DRA has a clear business rationale.
- [ ] The same physical device is not managed redundantly by two mechanisms.
- [ ] CDI Spec generation, refresh, and permissions are controlled.
- [ ] Claim lifecycle covers Pod deletion, node failure, and controller restart.
- [ ] Queue, billing, policy, and monitoring have been adapted to the new device model.
- [ ] The target combination of autoscaling and DRA has been validated by the vendor.
- [ ] Each device management mode has a Canary node pool and rollback path.
- [ ] Feature State, Kubernetes version, and Driver version are written into the platform contract.
- [ ] Device health can block new allocations and trigger diagnostics.

## Further Reading

- [Kubernetes Device Plugins](https://kubernetes.io/docs/concepts/extend-kubernetes/compute-storage-net/device-plugins/)
- [Dynamic Resource Allocation](https://kubernetes.io/docs/concepts/scheduling-eviction/dynamic-resource-allocation/)
- [Container Device Interface](https://github.com/cncf-tags/container-device-interface)
- [NVIDIA DRA Driver](https://github.com/NVIDIA/k8s-dra-driver-gpu)
- [AMD DRA Driver](https://instinct.docs.amd.com/projects/gpu-operator/en/main/dra/dra-driver.html)
- [Amazon EKS Device Management](https://docs.aws.amazon.com/eks/latest/userguide/device-management.html)
