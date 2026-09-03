# Choosing the right layer

Firecracker and CubeSandbox are not direct substitutes at the same layer.
Firecracker is a VMM; CubeSandbox is an agent-oriented sandbox control plane
that includes scheduling, images, snapshots, networking, policy, APIs, and SDKs
around KVM microVMs.

| Option | Main abstraction | Kubernetes relationship | Best fit | Main cost |
| --- | --- | --- | --- | --- |
| Firecracker alone | One microVM process and API | None by itself | VMM research, custom platforms, minimal boot path | You own images, networking, scheduling, storage, security, and cleanup |
| Kubernetes launcher Pod | Privileged Pod launching Firecracker | Scheduler manages the launcher process | Hardware qualification and controlled PoCs | Not a CRI runtime; unsafe for untrusted tenants |
| Kata + Firecracker | VM-backed Pod runtime | Selected with `RuntimeClass` | Existing Pod workloads needing a VM boundary | Runtime/snapshotter/CNI integration and feature limitations |
| KubeVirt | VirtualMachine / VMI | Kubernetes-native VM controller | General VMs, richer device and VM lifecycle requirements | Larger and more VM-oriented than a minimal microVM path |
| CubeSandbox | Agent sandbox API and lifecycle | Can deploy its control/data plane on Kubernetes | Agent code execution, templates, pause/resume, clone/rollback, egress governance | More platform components than a raw VMM |

## Practical decision

- Choose raw Firecracker when building or benchmarking the lowest VMM layer.
- Choose the launcher pattern only for node qualification and experiments.
- Choose Kata when existing Kubernetes Pod specifications must gain a VM-backed
  isolation boundary with minimal application changes.
- Choose KubeVirt when the user-facing object is a VM rather than a Pod or agent
  sandbox.
- Choose CubeSandbox when callers need a sandbox service and SDK instead of a
  low-level VMM or Kubernetes runtime handler.

CubeSandbox's official architecture uses its own CubeShim and CubeHypervisor
path over KVM, so installing Firecracker beside CubeSandbox is useful for a
baseline comparison; it is not an in-place backend switch.

## Can CubeSandbox run without Kubernetes?

Yes. Kubernetes is not the VMM and is not required by the CubeSandbox API
model. CubeSandbox can be deployed with its own control-plane and worker
components as long as their compute, network, image, storage, and discovery
requirements are supplied. Kubernetes is one way to operate those components;
it adds declarative scheduling, rollout, health reconciliation, service
discovery, Secret distribution, resource policy, and integration with an
existing cluster operations model.

Kubernetes is valuable when the organization already needs multi-node
placement, standardized deployment, quotas, node labels/taints, observability,
and controlled upgrades. It does not remove CubeSandbox's own sandbox
lifecycle, image, snapshot, or microVM responsibilities.

## What the composed test showed

The application test intentionally used an outer Kata/Firecracker microVM for
each agent Pod and an inner CubeSandbox sandbox for tool execution. This is a
valid defense-in-depth pattern, but it is not the default recommendation:

| Concern | Outer Kata + Firecracker | CubeSandbox |
| --- | --- | --- |
| Protected workload | Agent process and its dependencies | Agent-created tool/code execution |
| Caller interface | Kubernetes Pod and `RuntimeClass` | Sandbox API, SDK, plugin, or MCP tools |
| Scheduler/lifecycle | kube-scheduler, kubelet, containerd | CubeSandbox control plane |
| Isolation unit | One microVM-backed Pod | One agent sandbox |
| Snapshot meaning | VM/runtime snapshot, with disk handled separately | Product-level sandbox lifecycle and template semantics |

Use both when independent trust boundaries justify the extra host RSS,
double-network path, image management, and failure modes. Otherwise choose the
layer whose API matches the workload rather than stacking them automatically.

The lab validated that Kata 4.1.0 can run a normal Kubernetes Pod through
Firecracker 1.16.1 on the evaluated host. It also showed why this option has a
higher integration cost than the table alone suggests: Firecracker required a
devmapper snapshotter, a bounded vCPU configuration, and a workaround for a
runtime-rs Firecracker timeout defect in the released configuration.

The measured follow-up added full snapshot/restore, Kata concurrency, four
agent application paths, layered resource accounting, and a native jailer
baseline. See [the sanitized report](test-report.md) for observations and
[the agent guide](agent-workloads.md) for the composed architecture.

## Suggested benchmark dimensions

Use identical host hardware, guest kernel/rootfs size, vCPU, memory, and network
policy. Measure at least:

- process start to guest readiness, not just VMM process creation;
- steady-state host RSS and CPU per idle sandbox;
- concurrent create/delete success rate and tail latency;
- snapshot, restore, clone, and cleanup correctness;
- network throughput, latency, policy, and egress audit behavior;
- operational work required for images, leases, failures, upgrades, and GC;
- security boundary, privileged components, API authentication, and audit logs.

Do not compare a raw Firecracker boot time with a platform's authenticated API
request unless the platform-control-plane work is separately reported.

## Primary references

- [Firecracker design](https://github.com/firecracker-microvm/firecracker/blob/main/docs/design.md)
- [Kata virtualization architecture](https://github.com/kata-containers/kata-containers/blob/main/docs/design/virtualization.md)
- [Kubernetes RuntimeClass](https://kubernetes.io/docs/concepts/containers/runtime-class/)
- [KubeVirt architecture](https://kubevirt.io/user-guide/architecture/)
- [CubeSandbox architecture overview](https://github.com/TencentCloud/CubeSandbox/blob/master/docs/architecture/overview.md)
