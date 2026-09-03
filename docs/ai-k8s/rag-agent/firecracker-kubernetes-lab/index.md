# Firecracker on Kubernetes Lab

This is a standalone, publishable lab for evaluating Firecracker on Linux and
Kubernetes. It has no build, runtime, configuration, or documentation dependency
on the repository that contains it. The directory can be copied to another site
as-is.

## Validation status

| Path | Status | What was validated |
| --- | --- | --- |
| Native Firecracker | Verified | KVM boot, API state, guest boot, TAP networking, and graceful shutdown |
| Kubernetes launcher Pod | Verified | Scheduler placement, `/dev/kvm` access, guest boot, Pod cgroup accounting, and lifecycle cleanup |
| Kata `RuntimeClass` with Firecracker | Verified and retained | Kata 4.1.0 runtime-rs, Firecracker 1.16.1, persistent devmapper activation, CNI, guest exec, deletion cleanup, and live containerd restart |
| Snapshot and restore | Verified | Full snapshot created in 188.82 ms; restore API completed in 16.86 ms and guest ping was ready in 26.15 ms |
| Kata concurrency | Verified | Batches of 1, 5, and 10 Pods completed without failure or leaked VMMs/snapshots |
| Agent applications | Verified with one limitation | OpenClaw, DSH, and Hermes completed model/tool runs; Codex passed Adapter and MCP tests but its model provider protocol was incompatible |
| Observability | Verified | Payload, VMM, devmapper, host, and Adapter lifecycle signals were reconciled |
| Native jailer | Verified and retained | Chroot, PID/mount namespace, unprivileged identity, cgroup, capability, `NoNewPrivs`, and post-start seccomp state inspected |

The launcher pattern is deliberately a proof of concept. It lets Kubernetes
manage a Firecracker VMM process, but it does not turn ordinary Pods into
microVM-backed Pods. Use Kata Containers or a sandbox control plane when that is
the actual requirement.

## Documents

- [Host deployment and native smoke test](deployment.md)
- [Kubernetes launcher test](kubernetes-launcher.md)
- [Kata + Firecracker RuntimeClass test](kata-firecracker-runtimeclass.md)
- [Firecracker experiment playbook](experiments.md)
- [Agent workloads: OpenClaw, DSH, Hermes, and Codex](agent-workloads.md)
- [Observability and resource accounting](observability.md)
- [Jailer and security baseline](security-hardening.md)
- [Choosing Firecracker, Kata, KubeVirt, or CubeSandbox](comparison.md)
- [Sanitized test report](test-report.md)

Reusable examples live under `configs/` and `manifests/` and are linked from
the relevant guides. Replace example node names and image references before
use.

## Retained lab access

The evaluated node remains a dedicated, tainted Kata/Firecracker worker. Its
long-running workbench is accessible with:

```bash
kubectl get pod -n firecracker-lab kata-fc-workbench -o wide
kubectl logs -n firecracker-lab kata-fc-workbench
kubectl exec -n firecracker-lab -it kata-fc-workbench -- /bin/sh
```

See [the RuntimeClass guide](kata-firecracker-runtimeclass.md) before changing
the pool or containerd configuration, and use the
[experiment playbook](experiments.md) for the next test stages.

## Tested data flow

```text
Kubernetes scheduler
        |
        v
privileged launcher Pod -- /dev/kvm --> Firecracker VMM --> Linux microVM
        |
        +-- Kubernetes CPU, memory, and lifecycle cgroups
```

This differs from a runtime-backed path:

```text
Pod runtimeClassName --> RuntimeClass --> containerd --> Kata shim
                                                     --> Firecracker --> microVM
```

Both paths were run on the same isolated worker. The RuntimeClass path is the
appropriate starting point when an ordinary Pod must receive a microVM
boundary; the launcher remains useful for inspecting the VMM directly.

The agent experiment composed both systems:

```text
agent Pod -> Kata + Firecracker boundary -> CubeSandbox Adapter -> agent sandbox
```

This double layer is useful when both the agent runtime and its disposable tool
execution need independent boundaries, but it adds memory, networking, storage,
and operational cost. It is not required for normal CubeSandbox use.

## Security boundary

The launcher Pod is privileged and receives `/dev/kvm` plus a writable host
directory. Treat it as node-admin code. Do not expose this pattern to untrusted
tenants, do not mount arbitrary host paths, and do not treat it as a production
multi-tenant runtime. Production Firecracker should use the matching `jailer`
binary and a deliberately designed image, network, storage, cgroup, and cleanup
policy.

## Primary references

- [Firecracker getting started](https://github.com/firecracker-microvm/firecracker/blob/main/docs/getting-started.md)
- [Firecracker jailer](https://github.com/firecracker-microvm/firecracker/blob/main/docs/jailer.md)
- [Kubernetes RuntimeClass](https://kubernetes.io/docs/concepts/containers/runtime-class/)
- [Kata Containers installation](https://github.com/kata-containers/kata-containers/blob/main/docs/installation.md)
- [containerd devmapper snapshotter](https://github.com/containerd/containerd/blob/main/docs/snapshotters/devmapper.md)
- [Kata runtime-rs Firecracker issue #13484](https://github.com/kata-containers/kata-containers/issues/13484)
- [Kata hypervisors](https://github.com/kata-containers/kata-containers/blob/main/docs/hypervisors.md)
- [CubeSandbox architecture](https://github.com/TencentCloud/CubeSandbox/blob/master/docs/architecture/overview.md)
