# Firecracker Lab on Kubernetes

This is a self-contained set of experiment documents for evaluating how Firecracker runs on Linux and Kubernetes. It does not depend on the build, runtime, configuration, or other documentation of the repository it lives in, and can be copied in its entirety to other sites.

## Verification Status

| Path | Status | Verified Content |
| --- | --- | --- |
| Native Firecracker | Verified | KVM boot, API status, guest boot, TAP networking, and graceful shutdown |
| Kubernetes Launcher Pod | Verified | Scheduler placement, `/dev/kvm` access, guest boot, Pod cgroup accounting, and lifecycle cleanup |
| Kata `RuntimeClass` + Firecracker | Verified, environment retained | Kata 4.1.0 runtime-rs, Firecracker 1.16.1, persistent devmapper activation, CNI, guest exec, deletion cleanup, and containerd online restart |
| Snapshot and restore | Verified | Full snapshot took 188.82 ms; restore API took 16.86 ms, guest ping ready after 26.15 ms |
| Kata concurrency | Verified | Three concurrent batches of 1, 5, and 10 Pods all completed with no failures and no leftover VMMs or snapshots |
| Agent workloads | Verified, with one limitation | OpenClaw, DSH, and Hermes completed model and tool calls; Codex passed testing via Adapter with MCP, but its model provider protocol is incompatible |
| Observability | Verified | Aligned lifecycle signals across business containers, VMM, devmapper, host, and Adapter |
| Native jailer | Verified, environment retained | Checked chroot, PID/mount namespaces, unprivileged identity, cgroup, capability, `NoNewPrivs`, and post-boot seccomp state |

The Launcher approach is intentionally positioned as a proof of concept. It lets Kubernetes manage the Firecracker VMM process, but it does not automatically turn ordinary Pods into Pods backed by microVMs. If that isolation boundary is the actual goal, Kata Containers or a sandbox control plane should be used instead.

## Document Directory

- [Host Deployment and Native Smoke Tests](deployment.md)
- [Kubernetes Launcher Tests](kubernetes-launcher.md)
- [Kata + Firecracker RuntimeClass Tests](kata-firecracker-runtimeclass.md)
- [Firecracker Experiment Results and Operations Manual](experiments.md)
- [Agent Workloads: OpenClaw, DSH, Hermes, and Codex](agent-workloads.md)
- [Observability and Resource Accounting](observability.md)
- [Jailer and Security Baseline](security-hardening.md)
- [Firecracker, Kata, KubeVirt, and CubeSandbox Selection](comparison.md)
- [Redacted Test Report](test-report.md)

Reusable examples are located in `configs/` and `manifests/`, with specific links provided in the relevant guides. Replace the example node names and image addresses before use.

## Accessing the Retained Experiment Environment

The tested node is still retained as a dedicated, tainted Kata/Firecracker worker. The long-running Workbench can be accessed with the following command:

```bash
kubectl get pod -n firecracker-lab kata-fc-workbench -o wide
kubectl logs -n firecracker-lab kata-fc-workbench
kubectl exec -n firecracker-lab -it kata-fc-workbench -- /bin/sh
```

Before modifying the thin pool or containerd configuration, read the [RuntimeClass guide](kata-firecracker-runtimeclass.md); when proceeding to the next phase of testing, refer to the [experiment operations manual](experiments.md).

## Verified Data Flows

```text
Kubernetes 调度器
        |
        v
特权 Launcher Pod -- /dev/kvm --> Firecracker VMM --> Linux microVM
        |
        +-- Kubernetes CPU、内存与生命周期 cgroup
```

This differs from the runtime-hosted path:

```text
Pod runtimeClassName --> RuntimeClass --> containerd --> Kata shim
                                                     --> Firecracker --> microVM
```

Both paths were tested on the same isolated worker. When ordinary Pods need a microVM isolation boundary, the RuntimeClass path is the more appropriate starting point; the Launcher is better suited for directly observing and debugging the VMM.

The Agent experiments combined two systems:

```text
Agent Pod -> Kata + Firecracker 隔离边界 -> CubeSandbox Adapter -> Agent 沙箱
```

This two-layer approach is valuable when both the Agent runtime and the temporary tool execution environments it creates need independent isolation, but it also adds memory, network, storage, and operational overhead. Ordinary CubeSandbox usage scenarios do not require two-layer isolation.

## Security Boundary

The Launcher Pod runs in privileged mode, with access to `/dev/kvm` and a writable host directory. It should be treated as code with node administrator privileges. Do not expose this mode to untrusted tenants, do not mount arbitrary host paths, and do not treat it as a production-grade multi-tenant runtime. In production, Firecracker should use a version-matched `jailer`, with explicitly designed image, network, storage, cgroup, and cleanup policies.

## Primary References

- [Firecracker Getting Started Guide](https://github.com/firecracker-microvm/firecracker/blob/main/docs/getting-started.md)
- [Firecracker jailer](https://github.com/firecracker-microvm/firecracker/blob/main/docs/jailer.md)
- [Kubernetes RuntimeClass](https://kubernetes.io/docs/concepts/containers/runtime-class/)
- [Kata Containers Installation Guide](https://github.com/kata-containers/kata-containers/blob/main/docs/installation.md)
- [containerd devmapper snapshotter](https://github.com/containerd/containerd/blob/main/docs/snapshotters/devmapper.md)
- [Kata runtime-rs Firecracker issue #13484](https://github.com/kata-containers/kata-containers/issues/13484)
- [Kata hypervisor](https://github.com/kata-containers/kata-containers/blob/main/docs/hypervisors.md)
- [CubeSandbox Architecture](https://github.com/TencentCloud/CubeSandbox/blob/master/docs/architecture/overview.md)
