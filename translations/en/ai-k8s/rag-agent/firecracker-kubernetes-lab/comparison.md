# How to choose the right technology layer

Firecracker and CubeSandbox are not direct substitutes at the same layer. Firecracker is a VMM; CubeSandbox is an agent-oriented sandbox control plane that provides scheduling, images, snapshots, networking, policy, APIs, and SDKs around KVM microVMs.

| Option | Primary abstraction | Relationship with Kubernetes | Best suited for | Primary cost |
| --- | --- | --- | --- | --- |
| Standalone Firecracker | Single microVM process and API | Does not depend on Kubernetes itself | VMM research, self-built platforms, most minimal boot path | You must handle images, networking, scheduling, storage, security, and cleanup yourself |
| Kubernetes Launcher Pod | Privileged Pod that launches Firecracker | Scheduler only manages the Launcher process | Hardware validation and controlled proof-of-concept | Not a CRI runtime, not suitable for untrusted tenants |
| Kata + Firecracker | Pod runtime hosted by a VM | Selected via `RuntimeClass` | Existing Pod workloads that need a VM isolation boundary | Runtime, snapshotter, CNI integration costs and feature limitations |
| KubeVirt | VirtualMachine / VMI | Kubernetes-native VM controller | General-purpose VMs, richer devices, and VM lifecycle needs | Heavier and more VM-oriented than the minimal microVM path |
| CubeSandbox | Agent sandbox API and lifecycle | Control plane and data plane can be deployed on Kubernetes | Agent code execution, templates, pause/resume, clone/rollback, outbound governance | More platform components than a bare VMM |

## Practical selection recommendations

- When building or testing the lowest-level VMM, choose native Firecracker.
- Launcher mode is only for node capability validation and experiments.
- Choose Kata when existing Kubernetes Pods need a VM isolation boundary with minimal application changes.
- Choose KubeVirt when the user-facing object is a VM, not a Pod or Agent sandbox.
- Choose CubeSandbox when callers need sandbox services and SDKs, not the underlying VMM or Kubernetes runtime handler.

CubeSandbox's official architecture uses its own CubeShim and CubeHypervisor path on top of KVM, so deploying Firecracker alongside CubeSandbox is suitable for baseline comparison, but you cannot directly swap Firecracker in place as CubeSandbox's backend.

## Can CubeSandbox run without Kubernetes?

Yes. Kubernetes is not a VMM, and CubeSandbox's API model does not require Kubernetes. As long as compute, networking, images, storage, and service discovery are provided, CubeSandbox can be deployed through its own control plane and Worker components. Kubernetes is just one way to run these components; it additionally provides declarative scheduling, rolling updates, health state convergence, service discovery, Secret distribution, resource policies, and integration with existing cluster operations systems.

When organizations already need multi-node placement, standardized deployment, quotas, node labels/taints, observability, and controlled upgrades, Kubernetes is valuable; but it does not take over CubeSandbox's own sandbox lifecycle, images, snapshots, or microVM responsibilities.

## What the combined test shows

The applied test intentionally adds an outer Kata/Firecracker microVM for each Agent Pod and executes tools through the CubeSandbox sandbox on the inner layer. This is an effective defense-in-depth approach, but it is not the default recommendation:

| Concern | Outer Kata + Firecracker | CubeSandbox |
| --- | --- | --- |
| Protected workload | Agent process and its dependencies | Tools or code execution created by the Agent |
| Invocation interface | Kubernetes Pod and `RuntimeClass` | Sandbox API, SDK, plugin, or MCP tool |
| Scheduling and lifecycle | kube-scheduler, kubelet, containerd | CubeSandbox control plane |
| Isolation unit | A Pod hosted by a microVM | An Agent sandbox |
| Snapshot implications | VM/runtime snapshot, disk must be handled separately | Product-level sandbox lifecycle and template semantics |

Only when an independent trust boundary is sufficient to offset the additional host RSS, dual-layer network path, image management, and failure modes should both be used together. In other scenarios, choose the layer whose API better matches the workload, rather than stacking by default.

The experiment verified that Kata 4.1.0 can run ordinary Kubernetes Pods via Firecracker 1.16.1 on the tested host, and also showed that the actual integration cost is higher than the table suggests: Firecracker requires a devmapper snapshotter, restricted vCPU configuration, and a temporary workaround for the runtime-rs Firecracker timeout defect in the release configuration.

Subsequent measurements added full snapshot/restore, Kata concurrency, four Agent application paths, layered resource accounting, and native jailer baselines. Detailed observations are in the [redacted test report](test-report.md), and the combined architecture is in the [Agent workload guide](agent-workloads.md).

## Recommended benchmark dimensions

Comparisons should use the same host hardware, Guest kernel/rootfs size, vCPU, memory, and network policy. At minimum, measure:

- From process startup to Guest ready, not just VMM process creation;
- Steady-state host RSS and CPU per idle sandbox;
- Concurrent create/delete success rate and tail latency;
- Correctness of snapshot, restore, clone, and cleanup;
- Network throughput, latency, policy, and outbound audit behavior;
- Operational effort required for images, leases, failures, upgrades, and GC;
- Security boundaries, privileged components, API authentication, and audit logs.

Unless the platform control plane overhead is listed separately, do not directly compare native Firecracker startup time with the platform's authenticated API request latency.

## Key references

- [Firecracker design](https://github.com/firecracker-microvm/firecracker/blob/main/docs/design.md)
- [Kata virtualization architecture](https://github.com/kata-containers/kata-containers/blob/main/docs/design/virtualization.md)
- [Kubernetes RuntimeClass](https://kubernetes.io/docs/concepts/containers/runtime-class/)
- [KubeVirt architecture](https://kubevirt.io/user-guide/architecture/)
- [CubeSandbox architecture overview](https://github.com/TencentCloud/CubeSandbox/blob/master/docs/architecture/overview.md)
