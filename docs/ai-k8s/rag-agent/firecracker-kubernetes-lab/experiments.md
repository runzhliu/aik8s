# Firecracker experiment results and playbook

The requested subset—experiments 1, 2, 3, 5, and 7—was executed on the
dedicated worker. Results below are smoke and compatibility observations unless
explicitly described as repeated measurements.

## Executed subset

| No. | Experiment | Result | Evidence |
| --- | --- | --- | --- |
| 1 | Native snapshot and restore | Pass | Full snapshot and fresh-process restore; guest network and TCP/22 recovered |
| 2 | Kata concurrency | Pass | Batches of 1, 5, and 10 Pods; zero failed Pods, VMM leaks, or snapshot leaks |
| 3 | Agent applications | Pass with Codex model limitation | OpenClaw, DSH, Hermes model/tool runs passed; Codex Adapter and MCP paths passed |
| 5 | Observability | Pass | Payload, VMM, host, devmapper, and Adapter signals collected |
| 7 | Jailer/security baseline | Pass | Chroot, namespaces, cgroup, capabilities, `NoNewPrivs`, and seccomp inspected |

## 1. Native snapshot and restore

The guest was paused and a full snapshot was created through the Firecracker
API. VM state, memory, metrics, and the paired root filesystem were retained as
one experiment bundle.

| Measurement | Observation |
| --- | --- |
| Snapshot creation | 188.82 ms |
| Snapshot memory file | 256 MiB |
| VM state file | 23 KiB |
| Restore API | 16.86 ms |
| Restored guest ping readiness | 26.15 ms |
| Cold guest ping baseline | 1.280 s |
| Observed readiness ratio | Restore about 49 times faster than the single cold baseline |
| Restored services | ICMP and TCP/22 passed; VM state `Running` |

![Snapshot and restore evidence](assets/evidence/snapshot-restore-light.jpg)

This is not yet a repeatable snapshot benchmark. Only one restored instance was
used and the root filesystem was not immutable-cloned for repeated restores.
Firecracker snapshots do not include the backing disks, so production tooling
must version and authenticate VM state, memory, and every disk together.

## 2. Kata concurrency

[`manifests/kata-fc-concurrency.yaml`](manifests/kata-fc-concurrency.yaml)
created bounded test batches through `kata-fc-lab`.

| Batch | Ready-time observations | Summary |
| --- | --- | --- |
| 1 Pod | 4 s | 1/1 passed |
| 5 Pods | 4, 5, 6, 7, 8 s | P50 6 s, max 8 s, 5/5 passed |
| 10 Pods | 4, 5, 5, 6, 6, 6, 7, 8, 8, 8 s | P50 6 s, P95 8 s, max 8 s, 10/10 passed |

Peak host state was 11 Firecracker processes including the retained workbench,
with approximately 1.45 GiB aggregate VMM RSS. After deleting each batch, only
the retained workbench VMM and its expected active devmapper snapshots remained.

![Concurrency evidence](assets/evidence/concurrency-light.jpg)

This is a bounded smoke test, not a saturation benchmark. A production study
should run at least 30 randomized repetitions and include 50/100-Pod levels,
P99, API throttling, CPU contention, and deletion latency.

## 3. Agent applications

OpenClaw, DSH, Hermes, and Codex were deployed as Kata/Firecracker Pods and
tested against CubeSandbox Adapter. See [the full agent guide](agent-workloads.md)
for versions, credentials policy, product screenshots, network findings, and
the Codex protocol limitation.

![Agent evidence](assets/evidence/agents-light.jpg)

## 5. Observability

The measurement deliberately separated payload memory from host-side VMM RSS.
At the sample point, four agent payloads totalled about 1.07 GiB, while five
Firecracker processes including the retained workbench totalled about 2.68 GiB
RSS. The Adapter reported zero active leases after the tasks.

![Observability evidence](assets/evidence/observability-light.jpg)

Collection and interpretation details are in
[Observability and resource accounting](observability.md).

## 7. Jailer and security baseline

A native 2-vCPU, 256-MiB guest was started by jailer 1.16.1 with an
unprivileged identity. The post-start VMM had zero effective capabilities,
`NoNewPrivs=1`, and seccomp filter mode 2 on all four observed threads. The
chroot, PID/mount namespace, cgroup shares, rlimit, and deliberate device nodes
were also inspected.

![Jailer evidence](assets/evidence/security-light.jpg)

See [Jailer and security baseline](security-hardening.md) for limits and
production requirements.

## Deferred experiments

The following were intentionally not run in this round:

- MMDS and vsock control channels;
- network and block rate limiting, ballooning, and pressure/OOM behavior;
- PVC and NetworkPolicy matrices;
- shim/VMM kill, CNI outage, thin-pool exhaustion, and node-reboot injection;
- sustained 50/100-Pod concurrency and statistically controlled comparison
  against CubeSandbox.

## Primary references

- [Firecracker snapshot support](https://github.com/firecracker-microvm/firecracker/blob/main/docs/snapshotting/snapshot-support.md)
- [Snapshot versioning and CPU compatibility](https://github.com/firecracker-microvm/firecracker/blob/main/docs/snapshotting/versioning.md)
- [Firecracker metrics](https://github.com/firecracker-microvm/firecracker/blob/main/docs/metrics.md)
- [Firecracker jailer](https://github.com/firecracker-microvm/firecracker/blob/main/docs/jailer.md)
