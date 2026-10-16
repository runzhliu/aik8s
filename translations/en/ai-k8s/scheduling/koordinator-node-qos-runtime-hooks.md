---
title: "Koordlet and Runtime Hook: Node Resource Isolation Principles"
description: "Understanding how Koordlet implements CPU, memory, cache, I/O and network QoS from the control loop, container lifecycle and Linux kernel mechanisms"
status: reviewed
last_reviewed: 2026-09-21
---

# Koordlet and Runtime Hook: CPU, Memory, Cache and I/O Isolation Principles

The scheduler decides which machine a Pod goes to, but it is the node kernel that actually limits how much CPU it can use, whether it can squeeze the memory of latency-sensitive workloads, and how much last-level cache and disk bandwidth it can occupy. Koordinator uses `koordlet` on the node to continuously observe and adjust resources, and injects resource parameters at critical moments in the container lifecycle through Runtime Hook.

These two mechanisms address problems at different time scales:

- **Runtime Hook is responsible for "correct at container birth"**: on the container creation or update path, based on the Pod's QoS, annotations and `NodeSLO`, it brings CPUSet, CPU/memory QoS, `resctrl` and other parameters into the runtime or writes them directly to control groups;
- **Reconciler is responsible for "still correct while running"**: periodically scans Pod, container and node state, repairs configuration drift, and performs dynamic suppression, reclamation or eviction when load changes;
- **The kernel is responsible for actual execution**: cgroup, scheduler, memory reclamation, `resctrl`, block I/O controller and `tc`/eBPF are the execution surface of resource isolation.

This article is based on Koordinator stable documentation v1.8. Some capabilities depend on specific kernels, cgroup versions, CPU vendor extensions, container runtimes or CNI (Container Network Interface). You cannot assume that all nodes have the same effect based on a single YAML.

If you want to first understand why online-offline colocation is needed, you can read [Koordinator and Workload Colocation: From Resource Reclamation to Production](koordinator-colocation.md). This article continues to break down into the node internals.

![Koordlet node control loop](../../assets/koordinator-node-qos-runtime-hooks/node-control-loop.svg)

## 1. Koordlet is not a simple cgroup write script

`koordlet` runs on each node as a DaemonSet. It both collects state and executes policies. Internally it can be understood as five parts by responsibility:

| Module | Main Inputs | Main Outputs |
| --- | --- | --- |
| States Informer | kubelet, container runtime, cgroup, Pod metadata | Local view of nodes, Pods, containers and resource topology |
| Collectors / Metric Cache | CPU, memory, PSI, devices and performance counters | Short-period metrics and aggregation windows for control algorithms |
| NodeMetric Reporter | Local metric cache | Reports `NodeMetric` for control plane computation and scheduling |
| QoS Manager / Reconciler | `NodeSLO`, QoS, metrics and node state | Periodically writes cgroup, performs suppression, reclamation and eviction |
| Runtime Hooks | Container lifecycle events, rule cache | Modifies OCI (Open Container Initiative) resource configuration at creation or update |

On the control plane, `koord-manager` generates the `NodeSLO` for each node based on cluster configuration. `koordlet` watches for new rules and writes them to the local rule cache. Runtime Hook and each Reconciler read the same desired state. This way, containers get low-latency injection at creation time and continuous correction while running.

A typical closed loop is:

```text
slo-controller-config
        ↓
koord-manager 校验并生成 NodeSLO
        ↓
koordlet Rule Cache
        ├── Runtime Hook：生命周期内同步或近实时注入
        └── Reconciler：周期扫描、纠偏和动态调节
                    ↓
      cgroup / resctrl / tc / 内核调度器
                    ↓
       指标、PSI、延迟、压制与驱逐反馈
```

This design has an easily overlooked implication: **desired state, injection timing and kernel capability are three different things**. `NodeSLO` being correct does not mean the node kernel supports the target parameters; a successful Hook return does not mean no other component will later rewrite the cgroup; periodic reconciliation eventually converges, but it does not guarantee that the first sampling period after container startup will not interfere with latency-sensitive workloads.

## 2. Why both Runtime Hook and Reconciler are needed

Suppose an `BE` (Best Effort) container should be restricted to the shared CPU pool after startup, with a lower CPU weight.

If only the periodic Reconciler were used, the flow might be:

1. kubelet creates the container;
2. The container starts executing with the runtime's default parameters;
3. koordlet discovers it in the next scan round;
4. koordlet then modifies the CPUSet and weight.

There is a window between steps 2 and 4. A short scan period cannot eliminate the race, especially for batch tasks that are fully loaded at startup.

Runtime Hook moves the action forward into the container lifecycle path, so the container carries the desired configuration the first time it runs. The Reconciler is still indispensable because it must handle:

- State recovery after koordlet or container runtime restart;
- Online changes to `NodeSLO`, Pod annotations or QoS policies;
- Container rebuilds, ephemeral containers and cgroup hierarchy changes;
- Configuration drift caused by kubelet, other node agents or manual operations;
- CPU Suppress, memory reclamation and eviction that vary with node pressure.

Therefore, a more accurate relationship is: **Hook shortens the misconfiguration window, Reconciler converges long-term state, and both jointly depend on kernel execution.**

## 3. Three integration modes of Runtime Hook

![Standalone, CRI Proxy and NRI: three Runtime Hook modes](../../assets/koordinator-node-qos-runtime-hooks/runtime-hook-modes.svg)

Three integration paths have appeared in Koordinator design materials. The difference is mainly where the Hook sits in the container lifecycle.

| Mode | Call Path | Timing Guarantee | Main Cost | Applicability |
| --- | --- | --- | --- | --- |
| Standalone | kubelet calls the runtime directly; koordlet discovers containers asynchronously | Eventually consistent, startup window exists | Small change, cannot guarantee injection before the first process runs | Suitable for scenarios that only need periodic reconciliation or prioritize compatibility |
| CRI Proxy | kubelet → Hook Proxy → containerd/CRI-O | Can process synchronously before/after CRI requests | Rewrites the node CRI path; proxy failure affects container creation | Usable in older environments, but the proxy must be included in node critical path governance |
| NRI | kubelet → runtime; runtime calls back to the plugin through NRI | Synchronous adjustment of OCI Spec/resources within the lifecycle | Depends on runtime version, NRI configuration and plugin connection reliability | Evaluate first for new deployments; Koordinator v1.8 installation supports enabling by default |

NRI (Node Resource Interface) provides a plugin interface from the container runtime. After koordlet registers as an NRI plugin, containerd or CRI-O sends events at stages such as Pod Sandbox, Container creation and update. The Hook generates a response based on the Pod, container and rules; the runtime merges the resource modifications into the OCI configuration, then starts the container process.

The stable installation documentation gives the basic conditions as containerd 1.7 or above, Koordinator 1.3 or above with NRI enabled; the design documentation also lists CRI-O 1.25 or above as a target runtime. In production you must also verify whether the distribution compiled and enabled NRI, whether the plugin directory and socket match, and whether a runtime upgrade changes the default configuration.

### What happens in an NRI creation flow

```text
1. kubelet 请求运行时创建容器
2. runtime 把生命周期事件交给 koordlet NRI 插件
3. koordlet 将 Pod/Container 元数据构造成上下文
4. Hook 读取 NodeSLO、QoS、注解和节点能力
5. Hook 计算 LinuxResources、CPUSet 或 resctrl 等增量
6. runtime 合并响应并创建 OCI 容器
7. Reconciler 后续复核实际 cgroup 与期望状态
```

NRI solves reliable call timing; it does not add kernel capabilities out of thin air. If the node does not support `resctrl`, a successful NRI call still cannot provide LLC isolation; if the cgroup controller is not enabled, writing the corresponding parameters will not produce the expected effect.

Once Runtime Hook enters the container creation critical path, the failure policy must also be explicit. Fail-open allows the container to be created when the Hook fails, but the container may run with the wrong QoS; Fail-closed can uphold strong isolation requirements, but amplifies Hook failures into Pod startup failures. The platform should classify by policy importance: security boundaries can choose to reject, performance optimizations are usually better suited to alerting and degrading, while letting the Reconciler compensate.

## 4. CPU: share, cap, core binding and same-core interference are four problems

![Linux resource execution surface used by Koordlet](../../assets/koordinator-node-qos-runtime-hooks/linux-enforcement-map.svg)

CPU QoS cannot be reduced to "how many cores are limited". Linux has at least four different mechanisms:

### 4.1 CPU weight: who gets more time slices when contention occurs

- The common parameter in cgroup v1 is `cpu.shares`;
- cgroup v2 uses `cpu.weight`;
- Weight only takes effect when CPU contention exists at the same hierarchy level; it is not a fixed quota.

Latency-sensitive Pods use higher weight and BE Pods use lower weight, so that when the CPU is busy, latency-sensitive workloads get priority, but when the node is idle, batch tasks can still use idle compute capacity.

### 4.2 CPU bandwidth: how long a task can run at most within a period

- cgroup v1 uses `cpu.cfs_quota_us` and `cpu.cfs_period_us`;
- cgroup v2 uses `cpu.max`;
- Kernels that support CPU Burst can also use the corresponding burst parameter to bank unused quota and allow short bursts to suffer less throttling.

A hard quota easily protects neighbors, but can also create CPU throttling and lengthen latency-sensitive request tail latency. Burst allows short bursts to borrow, but cannot replace capacity planning; sustained overload is ultimately still limited by the quota.

### 4.3 CPUSet: which CPUs a process can actually run on

`cpuset.cpus` determines the set of runnable CPUs. Combined with the kubelet CPU Manager, NUMA topology and Koordinator's fine-grained CPU orchestration, it can implement dedicated cores, shared pools or different QoS pools. Here you must check simultaneously:

- Whether physical cores and hyperthread siblings are split apart;
- Whether CPUSet is aligned with NUMA memory, GPU and RDMA NICs;
- Whether kubelet and koordlet may manage the same hierarchy at the same time;
- Whether the actual CPUSet reconverges after hotplug and container rebuilds.

### 4.4 Interference on the same physical core: Core Scheduling and Group Identity

Even if two tasks use different logical CPUs, they may still share the execution resources of the same physical core. Koordinator CPU QoS supports selection by environment:

- **Core Scheduling**: uses the Linux kernel's Core Scheduling cookie to control which tasks can run simultaneously on SMT (Simultaneous Multithreading) sibling threads, and can be combined with `sched_idle` to make low-priority tasks yield;
- **Group Identity**: depends on specific kernel extensions such as Anolis, influencing scheduling priority through task group identity.

Neither is a universal capability of all distributions. Before enabling in production, you must verify kernel configuration, version, overhead and compatibility with existing scheduling policies.

## 5. Memory: protection, throttling, limits and eviction must be layered

The biggest difference between memory and CPU is that memory is incompressible. When CPU is insufficient, tasks can run later; sustained memory shortage triggers reclamation, thrashing, OOM (Out of Memory) and even node unavailability.

In cgroup v2, common memory control semantics are:

| Parameter | Semantics | Usage Risk |
| --- | --- | --- |
| `memory.min` | Hard protection boundary; below this value, reclamation is avoided as much as possible | If total protection is configured too large, pressure is transferred to other groups |
| `memory.low` | Best-effort protection; under pressure, participates in reclamation according to the unmet portion | It is a protection value, not proof of successful reservation |
| `memory.high` | Throttles allocations and applies reclamation pressure beyond this value | Setting it too low causes obvious thrashing and tail latency |
| `memory.max` | Hard limit; triggers cgroup OOM when reclamation is impossible | Requires clear container and Pod OOM recovery behavior |
| `memory.oom.group` | Treats the workload as a group for OOM handling | Must be consistent with upper-layer task retry and Pod lifecycle |

Koordinator Memory QoS converts declarations into node-available memcg (memory cgroup) parameters based on QoS and policy, and continuously maintains them through the reconciler. The fields are not exactly the same across different kernels and cgroup v1/v2; when using official examples, first confirm the corresponding implementation on the target node.

The node side also needs two types of last line of defense:

1. **Reclamation and suppression**: preferentially reclaim or limit low-priority workloads when pressure rises;
2. **Eviction**: `MemoryEvict` or `MemoryAllocatableEvict` terminates yieldable Pods when the node approaches a dangerous water level, quickly releasing memory.

Eviction is not a substitute for Memory QoS. The correct order is to protect and reclaim first, and only evict after confirming pressure is still uncontrollable. Monitoring must simultaneously observe working set, anonymous pages, Page Cache, Major Fault, direct reclamation, PSI, OOM and business latency; you cannot look only at `memory.usage`.

## 6. LLC and memory bandwidth: use resctrl, not cgroup

LLC (Last Level Cache) and memory bandwidth contention often manifest as "CPU utilization is not high, but latency-sensitive P99 degrades". The Linux `resctrl` filesystem provides:

- **CAT (Cache Allocation Technology)**: uses cache bit masks to limit the LLC ways a group of tasks can use;
- **MBA (Memory Bandwidth Allocation)**: allocates or throttles memory bandwidth for a group of tasks.

Koordinator can create `resctrl` control groups by QoS or Pod annotation, place the container process PIDs into the corresponding `tasks`, and write `schemata`. What actually happens here is: Pod identity is resolved into a group of processes, the processes are bound to a CLOS (Class of Service) identifier, and the CPU hardware then executes cache or bandwidth allocation.

In production, four questions must be answered first:

1. Whether the CPU model and microcode support CAT/MBA;
2. Whether the kernel has enabled and mounted `resctrl`;
3. Whether hardware resources such as CLOSID and RMID are sufficient in number;
4. Whether `tasks` remains correct after container process changes, restarts and exits.

LLC percentage is also not a "performance percentage". The same cache ways produce completely different hit rates on different working sets. You must build an interference matrix using latency-sensitive P99, LLC misses, memory bandwidth and batch task throughput.

## 7. Block I/O: ultimately it lands on specific devices

Block I/O QoS is usually implemented by the cgroup v1 `blkio` or cgroup v2 `io` controller:

- Weight-type parameters determine relative share during contention;
- `io.max` or throttle parameters limit the IOPS/bandwidth of a specific block device;
- Some kernels provide latency or cost models; capability varies with kernel and I/O scheduler.

The control target is ultimately the device's `major:minor`. This brings several common pitfalls:

- The container sees the OverlayFS path, while real I/O may land on multiple underlying devices;
- The data disk, container layer, and log disk may use different devices;
- LVM, Device Mapper, cloud disks, or multipath can change device mappings;
- When a new mounted volume appears, the Reconciler needs to re-parse and write the rules;
- The throughput limit of a local SSD cannot represent the real QoS of a network storage backend.

Therefore, policy validation should observe at least the container cgroup I/O statistics, node block device latency/queue, volume backend metrics, and application tail latency simultaneously.

## 8. Network: Requires CNI, tc, or eBPF Cooperation

Network QoS cannot be fully implemented by only writing cgroup files. Koordinator's Terway QoS integration uses Linux `tc` (Traffic Control) and eBPF (extended Berkeley Packet Filter), mapping workloads to three network QoS levels, L0, L1, and L2, and enforcing node- or Pod-level bandwidth management.

This capability depends on the CNI, kernel, and NIC data path:

- Pod veth, host networking, and passthrough devices have different traffic paths;
- HostNetwork Pods do not necessarily traverse the same qdisc (queueing discipline);
- RDMA, SR-IOV, or user-space networking may bypass the kernel's regular data path;
- Ingress and egress shaping locations and accounting scopes differ;
- Limiting bandwidth alone may not resolve queueing latency caused by short micro-bursts.

Koordlet handles the policy and identity bridging here, while actual enforcement still resides in the CNI, `tc`/eBPF, and the kernel network stack. When using other CNIs, you need to confirm whether an equivalent implementation exists; you cannot blindly copy the Terway configuration.

## 9. How Configuration Becomes Node Kernel Parameters

Production configuration is usually not applied by modifying cgroups node-by-node directly, but through a declarative chain:

1. Define default policies and node-group policies in `slo-controller-config`;
2. `koord-manager` validates the configuration and generates or updates `NodeSLO` for target nodes;
3. koordlet watches the local node object and compiles the rules into the local Rule Cache;
4. The Runtime Hook computes incremental resource configurations during the container lifecycle;
5. The Reconciler periodically compares "expected values" against "actual values";
6. The kernel enforces the limits, and metrics feed back into the next control loop.

The following content only expresses configuration relationships and should not be treated as an executable checklist for any specific version:

```yaml
# 概念示例：字段以目标 Koordinator 版本的 API 为准
clusterPolicy:
  default:
    cpuQoS: <default-policy>
    memoryQoS: <default-policy>
    resourceQOS: <default-policy>
  nodeStrategies:
    - selector: <canary-node-labels>
      cpuQoS: <canary-policy>
      memoryQoS: <canary-policy>
```

The reason no "copy-and-run" universal configuration is provided is that cgroup v1/v2, kernel distributions, containerd NRI, CPU features, and Koordinator versions all change the fields and their actual effects. Before merging configuration, you should generate a minimal diff from the [SLO configuration documentation](https://koordinator.sh/docs/user-manuals/slo-config) of the target version and verify the actual file values on a canary node with identical hardware.

## 10. Check the Capability Matrix Before Enabling Features

The following read-only commands can help confirm node facts. Paths and permissions vary by distribution:

```bash
# cgroup 版本与已启用控制器
stat -fc %T /sys/fs/cgroup
cat /sys/fs/cgroup/cgroup.controllers 2>/dev/null

# CPU 拓扑与 NUMA
lscpu -e=CPU,CORE,SOCKET,NODE,ONLINE

# resctrl 是否可用、已挂载
grep -w resctrl /proc/filesystems
mount | grep resctrl
ls /sys/fs/resctrl/info 2>/dev/null

# PSI 支持与当前压力
cat /proc/pressure/cpu
cat /proc/pressure/memory
cat /proc/pressure/io

# containerd 与 NRI 配置位置需按发行版核对
containerd --version
crictl info
```

It is recommended to expose node capabilities as labels or a machine profile, recording at least: kernel version, cgroup mode, runtime version, NRI status, CPU model, SMT, NUMA, `resctrl`, block devices, and CNI. Policies should only be delivered to validated node groups, to avoid the same `NodeSLO` having different meanings on different machines.

## 11. Failure Model: Hook Success Does Not Equal Policy Effectiveness

| Failure | Surface Symptom | Facts to Check |
| --- | --- | --- |
| NRI not registered or disconnected | Pod can start, but no injection at creation time | Runtime logs, plugin registration, Hook invocation count and errors |
| Hook timeout | Pod creation becomes slow or fails | Hook P95/P99, timeout policy, whether Fail-open is entered |
| `NodeSLO` stale | Inconsistent policies between old and new nodes | Object update time, watch/relist, rule cache version |
| Kernel does not support the parameter | No obvious API/Hook error, but isolation has no effect | Actual cgroup/resctrl files and kernel capabilities |
| Multiple components write the same cgroup | Parameters fluctuate periodically | Write boundaries of kubelet, koordlet, and other agents |
| Drift after container recreation | Old container works, new container fails | Container ID, cgroup path, and Reconciler convergence |
| Device mapping changes | I/O throttling applies to the wrong device | major:minor, mounts, OverlayFS, and volume backend |
| Rules too aggressive | Online workloads run normally, batch tasks make almost no progress | Suppression time, resource satisfaction, completion time, and eviction rate |

The Koordinator community is still continuously enhancing NRI Hook reliability, for example discussing how to declare that "a certain Hook must succeed" and how to make the runtime take explicit action when required plugins lose connectivity. This shows that production design cannot focus only on installation success; plugin connectivity, invocation latency, and degradation behavior must also be included in the SLO.

## 12. Monitoring Must Cover "Expected, Actual, and Outcome"

Looking only at the koordlet Pod Running status cannot prove that isolation is effective. It is recommended to build dashboards in three layers:

### Control and Injection

- `NodeSLO` update time, rule version, and distribution latency;
- Runtime Hook/NRI registration status, invocation count, errors, timeouts, and P95/P99;
- Reconciler execution count, failure count, per-round duration, and configuration drift count;
- koordlet and containerd/CRI-O restarts and connection re-establishment.

### Actual Kernel State

- Expected vs. actual `cpu.weight`, `cpu.max`, CPUSet;
- CPU throttling, Run Queue, context switches, and PSI;
- `memory.low/high/max`, direct reclaim, Major Fault, OOM, and memory PSI;
- `resctrl` groups, task count, LLC misses, and memory bandwidth;
- Per-device IOPS, throughput, queue, latency, and I/O PSI;
- `tc`/eBPF rule hits, packet drops, retransmissions, and bandwidth.

### Business Outcomes

- Online service P99/P999, error rate, and throughput;
- BE task queueing, effective progress, completion time, suppressed seconds, evictions, and retries;
- The closed loop among reclaimable resources, allocated resources, and actual usage.

Keeping a control node without the policy enabled on the same dashboard makes it easier to determine whether changes come from the policy or from business traffic, compared to showing only the pilot nodes.

## 13. Production Rollout Sequence

1. **Build a capability matrix**: group by OS, kernel, cgroup, runtime, CPU, and CNI;
2. **Collect first, do not enforce**: validate NodeMetric, PSI, runtime events, and cgroup paths;
3. **Enable only one mechanism at a time**: for example, validate CPU weight first, then CPUSet, to avoid changing five variables at once;
4. **Use node labels for canary rollout**: a small number of same-model nodes, keeping an unenabled control group;
5. **Validate both the birth-time and runtime paths**: cover fast container startup, restarts, Hook disconnection, koordlet restarts, and rule updates;
6. **Set stop-loss thresholds**: automatically halt expansion when online P99, error rate, PSI, OOM, or Hook latency exceeds bounds;
7. **Open reclaimable resources last**: first prove that isolation and rollback work, then let BE tasks consume online headroom.

A reliable acceptance test must answer at least: whether the container receives correct parameters before its first run, whether they remain correct after running for a period, whether it yields by priority when node pressure rises, whether it recovers automatically after component restarts, and whether the online workload's tail latency stays within the red line.

## 14. Conclusion

The core value of Koordlet is not "providing more parameters," but continuously translating the control plane's resource intent into executable kernel state on the node. The Runtime Hook moves critical configuration earlier into the container lifecycle, the Reconciler repairs drift during runtime, and the Linux kernel actually performs scheduling, reclamation, and throttling.

Once the boundaries of these three layers are understood, many issues become clear: NRI solves timing, not hardware capability; cgroup manages CPU, memory, and block I/O, but cannot replace `resctrl` or CNI; writing node policies into the API only represents the desired state, and ultimately actual files, kernel metrics, and business SLOs must prove that they take effect. The credibility of production isolation comes from this evidence chain being closed.

## References

- [Koordinator: Architecture Overview](https://koordinator.sh/docs/architecture/overview)
- [Koordinator: QoS Architecture](https://koordinator.sh/docs/architecture/qos)
- [Koordinator: SLO Configuration](https://koordinator.sh/docs/user-manuals/slo-config)
- [Koordinator: CPU QoS](https://koordinator.sh/docs/user-manuals/cpu-qos)
- [Koordinator: Memory QoS](https://koordinator.sh/docs/user-manuals/memory-qos)
- [Koordinator: Memory Evict](https://koordinator.sh/docs/user-manuals/memory-evict)
- [Koordinator: Terway Network QoS](https://koordinator.sh/docs/user-manuals/network-qos-with-terwayqos)
- [Koordinator: NRI Mode Resource Management Design](https://koordinator.sh/docs/designs/nri-mode-resource-management)
- [Koordinator: Installation and NRI Requirements](https://koordinator.sh/docs/installation)
- [Koordinator: Runtime Hook Design Archive](https://github.com/koordinator-sh/koordinator/blob/main/docs/design-archive/koordlet-runtime-hooks.md)
- [Koordinator: Resctrl QoS Enhancement Design](https://github.com/koordinator-sh/koordinator/blob/main/docs/proposals/koordlet/20231227-koordlet-resctrl-qos-enhance.md)
- [Koordinator Runtime API](https://github.com/koordinator-sh/koordinator/blob/main/apis/runtime/v1alpha1/api.proto)
- [Linux Kernel: Control Group v2](https://docs.kernel.org/admin-guide/cgroup-v2.html)
- [Linux Kernel: Resource Control](https://docs.kernel.org/arch/x86/resctrl.html)
