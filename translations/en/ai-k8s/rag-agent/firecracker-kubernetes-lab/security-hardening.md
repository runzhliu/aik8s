# Jailer and Security Baseline

Launcher Pods are suitable for admission validation, but are essentially privileged host management code. Therefore, the security experiment also launched a native microVM using a version-matched Firecracker `jailer` binary, and checked the host processes after `InstanceStart`.

## Verified Baseline

| Control | Observation |
| --- | --- |
| Version pairing | Firecracker 1.16.1 with jailer 1.16.1 |
| Run identity | Dedicated UID/GID 65534 |
| Filesystem | Per-instance dedicated chroot; no host `/etc/shadow` present inside |
| PID namespace | Host VMM PID maps to PID 1 within its namespace |
| Mount namespace | Different from the host namespace |
| Devices | Only explicitly created `/dev/kvm` and `/dev/net/tun` device nodes in the jail |
| Capabilities | Effective capability mask is 0 |
| Privilege escalation | `NoNewPrivs=1` after VM start |
| Seccomp | After VM start, all four VMM threads report filter mode 2 |
| Cgroup v1 | CPU shares remain 64 before and after start |
| File descriptors | `nofile` soft and hard limits are both 128 |
| Guest | Runs with 2 vCPUs, 256 MiB configuration |

Before `InstanceStart`, the API process shows seccomp mode 0. After start, all four VMM threads show seccomp mode 2, with a filter installed. Therefore, security checks must observe the VMM after start and must not infer the final security posture from the pre-start API process state.

![Redacted jailer evidence](assets/evidence/security-light.jpg)

## Deployment Requirements

- Pin and verify mutually matching Firecracker/jailer versions.
- Use a non-privileged identity and a non-reused chroot per instance.
- Ensure the jail UID cannot modify the kernel, rootfs, or configuration inputs.
- Create only the device nodes required by the selected VM configuration.
- Explicitly set cgroup, rlimit, NUMA, CPU, memory, network, and cleanup policies.
- Authenticate and restrict access to the Firecracker API socket.
- Treat TAP creation, image staging, jail construction, and cleanup as privileged control-plane operations, and retain audit records.
- Verify the actual post-start process state: namespaces, capabilities, `NoNewPrivs`, seccomp mode, cgroup membership, open descriptors, and mount points.

Test instances were intentionally kept on a dedicated experimental node to allow continued testing. This is acceptable for isolated experiments, but a production controller must guarantee cleanup completes after normal exit, API failure, VMM crash, node restart, and creation interruption.

## Result Boundaries

This smoke test confirms that the isolation controls documented in the list are in effect; it is not a penetration test and cannot prove multi-tenant security. Guest escape, malicious block device images, device emulation, kernel attack surface, host service access, and cleanup races all require separate adversarial testing.

## Key References

- [Firecracker jailer](https://github.com/firecracker-microvm/firecracker/blob/main/docs/jailer.md)
- [Firecracker seccomp filters](https://github.com/firecracker-microvm/firecracker/blob/main/docs/seccomp.md)
- [Firecracker design](https://github.com/firecracker-microvm/firecracker/blob/main/docs/design.md)
