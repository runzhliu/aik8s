# Test report

- Date: 2026-09-02 to 2026-09-03
- Scope: one isolated x86_64 Kubernetes worker
- Result: native, launcher, Kata, snapshot, concurrency, agent, observability, and jailer paths passed with documented limitations

This report intentionally omits cluster names, internal addresses, registry
names, bastion details, credentials, and unrelated workloads so it can be
published independently.

## Environment

| Item | Observed value |
| --- | --- |
| Host OS | Anolis OS 8.8 |
| Host kernel | Linux 5.10.134, x86_64, 4 KiB pages |
| CPU | Intel Xeon E5-2683 v3, 56 logical CPUs |
| Memory | 251 GiB total; about 226 GiB available before the test |
| Disk | 214 GiB root filesystem; about 177 GiB available before the test |
| Virtualization | Bare metal, Intel VMX, EPT, KVM, nested virtualization enabled |
| Devices | `/dev/kvm` and `/dev/net/tun` present and writable |
| Kubernetes | 1.30.4 |
| Container runtime | containerd 1.7.14, cgroup v1 |
| Firecracker | 1.16.1 |
| Kata Containers | 4.1.0 static amd64, runtime-rs |

## Artifact integrity

The official Firecracker release checksum passed before installation.

| Artifact | SHA256 |
| --- | --- |
| `firecracker-v1.16.1-x86_64.tgz` | `382a02a869e4d6d5cb14c40577f9545e8458021ea8b0b2d3fc10ec14d9c242e6` |
| quickstart `vmlinux.bin` | `ea5e7d5cf494a8c4ba043259812fc018b44880d70bcbbfc4d57d2760631b1cd6` |
| quickstart `rootfs.ext4` | `2a840feeccb5cb161c6eab1ecd86667c06ed5e307da534d2d3c9e39a6ec6c30a` |
| `kata-static-4.1.0-amd64.tar.zst` | `3dc6b69c4acb787b967b04b64599a20d02a8beb1a8eaab3084110df9d0b08c96` |

`e2fsck -fn` completed successfully on the base rootfs. The Kata archive hash
matched before and after the offline transfer. Its GitHub artifact attestation
was not verified because the workstation's Sigstore verifier did not
initialize, so the digest is reported only as transfer-integrity evidence.

## Native results

| Test | Observed result | Status |
| --- | --- | --- |
| Firecracker executable | `Firecracker v1.16.1` | Pass |
| Jailer executable | `Jailer v1.16.1` | Pass |
| API socket | Created and responsive | Pass |
| `GET /version` | `firecracker_version=1.16.1` | Pass |
| `GET /` | `state=Running`, `app_name=Firecracker` | Pass |
| Guest boot | Ubuntu reached Multi-User and automatic serial login | Pass |
| Guest kernel | Linux 4.14.174 from the disposable quickstart image | Pass |
| TAP connectivity | 3/3 ICMP replies, 0% loss | Pass |
| TAP latency | 0.137 ms average in this single run | Informational |
| SSH readiness | TCP/22 became reachable after about 1,243 ms | Informational |
| Graceful stop | `SendCtrlAltDel` returned HTTP 204 and VMM exited | Pass |

The timing is a smoke observation, not a benchmark. It includes the old
quickstart guest's init path and was not repeated under controlled load.

## Kubernetes launcher results

| Test | Observed result | Status |
| --- | --- | --- |
| Scheduler placement | Pod selected the labelled test node | Pass |
| Pod state | Running, zero restarts | Pass |
| Guest boot in Pod logs | Multi-User, SSH service, and serial login reached | Pass |
| Kubernetes accounting | Approximately 66 millicores and 84 MiB during observation | Informational |
| Host cgroup membership | VMM PID present under the Pod's CPU, memory, devices, and PIDs cgroups | Pass |
| Pod deletion | Firecracker process terminated with Pod deletion | Pass |

## Kata + Firecracker RuntimeClass results

The Kata 4.1.0 static package was downloaded on a connected workstation,
transferred through the Kubernetes API, and installed with its runtime-rs
Firecracker configuration. Firecracker 1.16.1 from the first phase supplied the
VMM and jailer binaries.

A dedicated 20 GiB data / 2 GiB metadata sparse loopback thin pool was created
on the root filesystem. No raw disk or pre-existing LVM volume group was used.
containerd's built-in devmapper plugin changed from its original unconfigured
`error` state to `ok` during the test.

| Test | Observed result | Status |
| --- | --- | --- |
| Runtime handler | `kata-fc` through runtime-rs shim v2 | Pass |
| RuntimeClass scheduling | Dedicated label, taint, selector, and toleration selected only the lab node | Pass |
| Snapshotter | Rootfs layers and active sandbox snapshots visible in devmapper | Pass |
| Pod startup | Created at `10:30:29Z`, Ready at `10:30:33Z` | Pass |
| Guest identity | Linux `6.18.35`, x86_64, distinct from host `5.10.134` | Pass |
| CNI | Pod received an address and reported `eth0` up | Pass |
| Kubernetes exec/logs | Both returned guest output | Pass |
| VMM evidence | Separate Firecracker process visible on the host | Pass |
| Host VMM memory | About 129 MiB RSS at 33 seconds | Informational |
| Payload metrics | `kubectl top` reported 2 MiB for the container | Informational |
| Pod deletion | Firecracker process and active devmapper snapshots disappeared | Pass |

The four-second startup and memory samples came from one smoke run. They are not
benchmark claims. Container-level metrics did not represent the host VMM's RSS,
so a production capacity study must observe shim and VMM cgroups separately.

### Compatibility findings

The first two sandbox attempts intentionally remain documented because they
identify reproducible release/configuration problems:

1. `default_maxvcpus = 0` expanded to the 56 host CPUs. Firecracker rejected the
   VM. A lab copy of the configuration bounded `default_maxvcpus` to `2`.
2. The released Firecracker runtime-rs configuration set
   `dial_timeout_ms = 45000` without a compatible `reconnect_timeout_ms`. The
   runtime rejected it. The `dial_timeout_ms = 2000` and
   `reconnect_timeout_ms = 60000` workaround from upstream
   [issue #13484](https://github.com/kata-containers/kata-containers/issues/13484)
   allowed the sandbox to start.

No orphan Firecracker process remained after either failed attempt. These
overrides must be re-evaluated when upgrading Kata rather than copied forward
blindly.

## Retained environment validation

After the rollback path had been verified, the node was deliberately enabled
again as a dedicated Firecracker test worker. A systemd oneshot service now
attaches the sparse data and metadata files, creates `fc-devpool`, and is a
required predecessor of containerd.

The dependency was tested with no Kata Pod running:

1. containerd and the pool service were stopped;
2. `dmsetup` and both loopback lookups returned empty;
3. starting containerd automatically started the pool service;
4. `fc-devpool` returned and the devmapper plugin reported `ok`.

Destroying the earlier pool while retaining containerd's content store left
two stale `containerd.io/gc.ref.snapshot.devmapper` labels. The first retained
workbench therefore failed with `snapshot does not exist`. With no devmapper
snapshot or Pod active, those labels were cleared and containerd restarted.
The next workbench creation unpacked both sandbox and workload images into the
new pool and became Ready.

A live containerd restart was then run while that workbench remained active.
The Pod UID and Firecracker PID were unchanged, container restart count stayed
at zero, guest uptime increased continuously, and a file under the Pod's
`emptyDir` remained readable.

## Selected follow-up experiment results

### 1. Full snapshot and restore

| Check | Observed result | Status |
| --- | --- | --- |
| Full snapshot API | Completed in 188.82 ms | Pass |
| Artifacts | 256 MiB memory, 23 KiB VM state, paired rootfs and metrics retained | Pass |
| Restore API | Completed in 16.86 ms | Pass |
| Guest readiness after restore | ICMP ready in 26.15 ms; TCP/22 reachable | Pass |
| Cold readiness baseline | ICMP ready in 1.280 s in one comparison run | Informational |
| Snapshot metric | `load_snapshot` reported 3,957 microseconds | Informational |

The single restore was about 49 times faster to ICMP readiness than the single
cold baseline. This is not a benchmark: repeated immutable disk clones and
multiple controlled samples were not run.

![Snapshot and restore evidence](assets/evidence/snapshot-restore-light.jpg)

### 2. Kata concurrency

| Batch | Ready times | Result |
| --- | --- | --- |
| 1 | 4 s | 1/1 passed |
| 5 | 4, 5, 6, 7, 8 s | 5/5 passed; P50 6 s |
| 10 | 4, 5, 5, 6, 6, 6, 7, 8, 8, 8 s | 10/10 passed; P50 6 s, P95 8 s |

At peak, 11 Firecracker processes including the retained workbench used about
1.45 GiB aggregate RSS. After batch deletion there were no extra VMMs or
devmapper snapshots.

![Concurrency evidence](assets/evidence/concurrency-light.jpg)

### 3. Agent applications

OpenClaw 2026.8.2, DSH 0.1.2-alpha.4, Hermes 0.21.0, and Codex 0.150.1 all ran
as Ready, zero-restart Kata/Firecracker Pods.

| Application | Result | Status |
| --- | --- | --- |
| OpenClaw | Model turn called `cube_exec`, `cube_status`, and `cube_release`; three calls and zero failures | Pass |
| DSH | Headless model run returned execution and release markers; Adapter audit clean | Pass |
| Hermes | Plugin doctor and one-shot model run passed; lifecycle audit clean | Pass |
| Codex | Direct Adapter smoke and official MCP stdio handshake passed; 17 tools discovered | Pass for Adapter/MCP |
| Codex model turn | Gateway used Chat Completions while the Codex custom provider required Responses | Not run; incompatible protocol |

The test worker could not directly route to the model endpoint and the Kata TAP
path could not use the normal Service VIP. A temporary relay and direct Pod
addressing were used for qualification, then the relay was removed. Credentials
were injected from Kubernetes Secrets and are absent from the manifests,
screenshots, and report.

![Agent application evidence](assets/evidence/agents-light.jpg)

### 5. Observability

At one observation point, the four payload containers used 1,094 MiB in total,
while five host Firecracker processes including the retained workbench used
approximately 2.68 GiB aggregate RSS. This confirms that payload-only
Kubernetes metrics undercount the complete runtime footprint. The Adapter
reported zero active leases after application tasks.

![Observability evidence](assets/evidence/observability-light.jpg)

### 7. Native jailer baseline

A separate 2-vCPU, 256-MiB microVM was launched with jailer 1.16.1 and retained
for follow-up testing. It used UID/GID 65534, a per-instance chroot, a new PID
and mount namespace, CPU shares of 64, and a `nofile` limit of 128. After VM
start, every observed VMM thread had seccomp mode 2; the main process had
`NoNewPrivs=1` and zero effective capabilities.

![Jailer security evidence](assets/evidence/security-light.jpg)

## Final node state

- the worker is online and schedulable, with a dedicated
  `sandbox.aik8s.run/kata-fc=true:NoSchedule` taint preventing ordinary
  workloads from using it;
- the CNI is Ready on the worker;
- `RuntimeClass/kata-fc-lab` remains installed and selects only labelled test
  nodes;
- namespace `firecracker-lab` and its long-running `kata-fc-workbench` Pod
  remain active for interactive testing;
- the four agent application Pods remain Ready on the dedicated worker for
  inspection, but the temporary model-network relay has been removed;
- the native jailed `security-smoke` microVM remains active for security
  follow-up;
- containerd, CRI, devmapper, kubelet, and the persistent pool service are
  active; the pool service is enabled for boot and ordered before containerd;
- the original containerd configuration remains backed up with its recorded
  SHA-256, while the active configuration contains the `kata-fc` handler;
- the base Firecracker lab, Kata files, and compressed offline archive remain
  on disk for repeatable tests;
- temporary artifact-transfer resources were removed;
- no credentials or private endpoints were written into this documentation.

## Follow-up work

1. Replace the loopback thin pool with dedicated production storage, persistent
   activation, monitoring, and recovery procedures.
2. Track Kata issue #13484 and remove the timeout workaround after a verified
   upstream fix.
3. Validate persistent volumes, NetworkPolicy, resource pressure, abnormal
   kubelet/containerd failures, and concurrent deletion.
4. Mirror pinned Kata, Firecracker, guest, and workload artifacts through the
   organization's approved supply-chain verification path.
5. Replace the disposable Ubuntu 18.04 quickstart guest with a maintained,
   reproducibly built image.
6. Extend the bounded 1/5/10-Pod smoke to repeated 50/100-Pod concurrency and
   compare it with CubeSandbox using equivalent readiness criteria.
7. Fix Service VIP reachability from the Kata TAP network and replace the
   temporary model relay with a production egress path.
