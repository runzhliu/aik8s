# Test Report

- Date: 2026-09-02 through 2026-09-03
- Scope: one isolated x86_64 Kubernetes worker
- Result: native, Launcher, Kata, snapshot, concurrency, Agent, observability, and jailer paths all passed; limitations recorded

For independent public release, this report intentionally omits cluster names, internal addresses, image registry names, jump-host details, credentials, and unrelated workloads.

## Test Environment

| Item | Observation |
| --- | --- |
| Host OS | Anolis OS 8.8 |
| Host kernel | Linux 5.10.134, x86_64, 4 KiB page |
| CPU | Intel Xeon E5-2683 v3, 56 logical CPUs |
| Memory | 251 GiB total; approximately 226 GiB available before testing |
| Disk | 214 GiB root filesystem; approximately 177 GiB available before testing |
| Virtualization | Bare metal, Intel VMX, EPT, KVM, nested virtualization enabled |
| Devices | `/dev/kvm` and `/dev/net/tun` present and writable |
| Kubernetes | 1.30.4 |
| Container runtime | containerd 1.7.14, cgroup v1 |
| Firecracker | 1.16.1 |
| Kata Containers | 4.1.0 static amd64 package, runtime-rs |

## Artifact Integrity

Before installation, the official Firecracker release packages were verified via checksums.

| Artifact | SHA256 |
| --- | --- |
| `firecracker-v1.16.1-x86_64.tgz` | `382a02a869e4d6d5cb14c40577f9545e8458021ea8b0b2d3fc10ec14d9c242e6` |
| quickstart `vmlinux.bin` | `ea5e7d5cf494a8c4ba043259812fc018b44880d70bcbbfc4d57d2760631b1cd6` |
| quickstart `rootfs.ext4` | `2a840feeccb5cb161c6eab1ecd86667c06ed5e307da534d2d3c9e39a6ec6c30a` |
| `kata-static-4.1.0-amd64.tar.zst` | `3dc6b69c4acb787b967b04b64599a20d02a8beb1a8eaab3084110df9d0b08c96` |

The base rootfs successfully completed `e2fsck -fn`. The Kata archive had identical hashes before and after offline transfer. Because Sigstore verifier initialization failed on the workstation, GitHub artifact provenance was not verified; the digests here therefore serve only as transport-integrity evidence.

## Native Run Results

| Test item | Observation | Status |
| --- | --- | --- |
| Firecracker executable | `Firecracker v1.16.1` | Passed |
| Jailer executable | `Jailer v1.16.1` | Passed |
| API socket | Created successfully and responsive | Passed |
| `GET /version` | `firecracker_version=1.16.1` | Passed |
| `GET /` | `state=Running`, `app_name=Firecracker` | Passed |
| Guest boot | Ubuntu reached multi-user and auto-logged in on the serial console | Passed |
| Guest kernel | Linux 4.14.174 from the one-shot quickstart image | Passed |
| TAP connectivity | 3/3 ICMP replies, 0% packet loss | Passed |
| TAP latency | 0.137 ms average for this single run | Reference only |
| SSH ready | TCP/22 reachable after approximately 1,243 ms | Reference only |
| Graceful stop | `SendCtrlAltDel` returned HTTP 204, VMM exited | Passed |

These timings are smoke observations, not benchmark results. They include the legacy quickstart guest initialization path and were not repeated under controlled load.

## Kubernetes Launcher Results

| Test item | Observation | Status |
| --- | --- | --- |
| Scheduling placement | Pod selected the test node carrying the specified label | Passed |
| Pod status | Running, restart count 0 | Passed |
| Guest boot in Pod logs | Reached multi-user, SSH service, and serial login stages | Passed |
| Kubernetes resource accounting | Approximately 66 millicores, 84 MiB at observation time | Reference only |
| Host cgroup membership | VMM PID was under the Pod's CPU, memory, devices, and PIDs cgroups | Passed |
| Pod deletion | Firecracker process terminated when the Pod was deleted | Passed |

## Kata + Firecracker RuntimeClass Results

The Kata 4.1.0 static package was downloaded on a networked workstation, transferred via the Kubernetes API, and installed using its runtime-rs Firecracker configuration. The Firecracker 1.16.1 from the first-phase installation provides the VMM and jailer binaries.

A dedicated 20 GiB data / 2 GiB metadata sparse loopback thin pool was created on the root filesystem; no raw disks or pre-existing LVM volume groups were used. During testing, the containerd built-in devmapper plugin transitioned from the initially unconfigured `error` state to `ok`.

| Test item | Observation | Status |
| --- | --- | --- |
| Runtime handler | `kata-fc` provided by the runtime-rs shim v2 | Passed |
| RuntimeClass scheduling | Dedicated label, taint, selector, and toleration selected only the experiment node | Passed |
| Snapshotter | Rootfs layers and active sandbox snapshots visible in devmapper | Passed |
| Pod startup | `10:30:29Z` created, `10:30:33Z` Ready | Passed |
| Guest identity | Linux `6.18.35`, x86_64, different from host `5.10.134` | Passed |
| CNI | Pod obtained an address and reported `eth0` up | Passed |
| Kubernetes exec/logs | Both returned guest output | Passed |
| VMM evidence | Separate Firecracker process visible on the host | Passed |
| Host VMM memory | Approximately 129 MiB RSS at second 33 | Reference only |
| Payload metrics | `kubectl top` reported 2 MiB container usage | Reference only |
| Pod deletion | Firecracker process and active devmapper snapshot disappeared | Passed |

The four-second startup and memory sample come from a single smoke run and do not constitute benchmark conclusions. Container-level metrics do not represent host VMM RSS, so production capacity studies must observe shim and VMM cgroups separately.

### Compatibility Findings

The first two sandbox attempts were intentionally kept in the report because they identified reproducible version/configuration issues:

1. `default_maxvcpus = 0` expanded to all 56 host CPUs, causing Firecracker to reject the VM. The experimental configuration copy restricted `default_maxvcpus` to `2`.
2. The release Firecracker runtime-rs configuration set `dial_timeout_ms = 45000` without a compatible `reconnect_timeout_ms`, so the runtime rejected the configuration. After applying the workaround from upstream [Issue #13484](https://github.com/kata-containers/kata-containers/issues/13484), using `dial_timeout_ms = 2000` and `reconnect_timeout_ms = 60000`, the sandbox started successfully.

Neither failed attempt left orphaned Firecracker processes. These override configurations must be re-evaluated when upgrading Kata; they must not be carried over blindly.

## Reserved Environment Verification

After the rollback path was verified, the node was intentionally re-enabled as a dedicated Firecracker test worker. A systemd oneshot service now mounts the sparse data and metadata files, creates `fc-devpool`, and acts as a required prerequisite service for containerd.

The dependency was tested without Kata Pods running:

1. Stopped containerd and the pool service;
2. `dmsetup` and both loopback queries returned empty;
3. After starting containerd, the pool service started automatically;
4. `fc-devpool` was restored, and the devmapper plugin reported `ok`.

After destroying the previous pool but keeping the containerd content store, two `containerd.io/gc.ref.snapshot.devmapper` labels remained, so the first reserved Workbench creation produced `snapshot does not exist`. After confirming there were no active devmapper snapshots or Pods, these labels were cleared and containerd was restarted. On the next Workbench creation, both the sandbox and workload images unpacked successfully into the new pool, and the Pod then became Ready.

containerd was then restarted online while the Workbench remained active. The Pod UID and Firecracker PID did not change, the container restart count stayed at 0, guest uptime continued to increase, and files under Pod `emptyDir` remained readable.

## Subsequent Key Experiment Results

### 1. Full Snapshot and Restore

| Check item | Observation | Status |
| --- | --- | --- |
| Full snapshot API | Completed in 188.82 ms | Passed |
| Artifacts | Retained 256 MiB memory, 23 KiB VM state, companion rootfs, and metrics | Passed |
| Restore API | Completed in 16.86 ms | Passed |
| Guest ready after restore | ICMP ready after 26.15 ms; TCP/22 reachable | Passed |
| Cold-start ready baseline | ICMP ready after 1.280 s in a single comparison run | Reference only |
| Snapshot metrics | `load_snapshot` reported 3,957 microseconds | Reference only |

The single restore-to-ICMP-ready time was approximately 49 times faster than the single cold-start baseline. This is not a benchmark conclusion: this round did not execute repeated immutable disk clones or collect multiple controlled samples.

![Snapshot and restore evidence](assets/evidence/snapshot-restore-light.jpg)

### 2. Kata Concurrency

| Batch | Ready time | Result |
| --- | --- | --- |
| 1 | 4 s | 1/1 passed |
| 5 | 4, 5, 6, 7, 8 s | 5/5 passed; P50 6 s |
| 10 | 4, 5, 5, 6, 6, 6, 7, 8, 8, 8 s | 10/10 passed; P50 6 s, P95 8 s |

At peak, including the reserved Workbench, there were 11 Firecracker processes with aggregate RSS of approximately 1.45 GiB. After deleting the batches, no extra VMMs or devmapper snapshots remained.

![Concurrency test evidence](assets/evidence/concurrency-light.jpg)

### 3. Agent Applications

OpenClaw 2026.8.2, DSH 0.1.2-alpha.4, Hermes 0.21.0, and Codex 0.150.1 all ran as Kata/Firecracker Pods, all Ready with restart count 0.

| Application | Result | Status |
| --- | --- | --- |
| OpenClaw | Model turn invoked `cube_exec`, `cube_status`, and `cube_release`; three calls, zero failures | Passed |
| DSH | Headless model run returned execution and release markers; adapter audit showed no residue | Passed |
| Hermes | Plugin Doctor and a single model run passed; lifecycle audit showed no residue | Passed |
| Codex | Direct adapter smoke and official MCP stdio handshake passed; 17 tools discovered | Adapter/MCP passed |
| Codex model turn | Gateway uses Chat Completions, while the Codex custom provider requires Responses | Not run; protocol incompatible |

The test worker could not route directly to the model endpoint, and the Kata TAP path could not use the regular Service VIP. Admission testing temporarily used a relay and direct Pod connectivity; the relay was deleted after completion. Credentials were injected via Kubernetes Secrets and do not appear in manifests, screenshots, or the report.

![Agent application evidence](assets/evidence/agents-light.jpg)

### 5. Observability

At one sampling instant, the four payload containers used 1,094 MiB combined, while the five Firecracker processes on the host, including the reserved Workbench, had aggregate RSS of approximately 2.68 GiB. This shows that Kubernetes metrics counting only payloads underestimate full runtime overhead. After application tasks finished, the adapter reported zero active leases.

![Observability evidence](assets/evidence/observability-light.jpg)

### 7. Native Jailer Baseline

A standalone 2 vCPU, 256 MiB microVM was started with jailer 1.16.1 and retained for subsequent testing. It used UID/GID 65534, a per-instance chroot, new PID and mount namespaces, 64 CPU shares, and an `nofile` limit of 128. After VM startup, every observed VMM thread was in seccomp mode 2; the main process was `NoNewPrivs=1` with effective capabilities of 0.

![Jailer security evidence](assets/evidence/security-light.jpg)

## Node Final State

- Worker is online and schedulable; the dedicated `sandbox.aik8s.run/kata-fc=true:NoSchedule` Taint prevents ordinary workloads from using it;
- CNI is Ready on the Worker;
- `RuntimeClass/kata-fc-lab` remains installed and only selects test nodes with the specified Label;
- The `firecracker-lab` Namespace and the long-running `kata-fc-workbench` Pods within it remain active and available for interactive testing;
- The four Agent application Pods remain Ready and stay on the dedicated Worker for inspection, but the temporary model network relay has been removed;
- The `security-smoke` microVM started by the native jailer remains active for subsequent security testing;
- containerd, CRI, devmapper, kubelet, and the persistent Pool service are all in an active state; the Pool service has been configured to start at boot and is ordered before containerd;
- The original containerd configuration still has a backup with its SHA-256 recorded; the current configuration includes the `kata-fc` Handler;
- The base Firecracker experiments, Kata files, and offline compressed archives remain on disk for repeatable testing;
- The temporary artifact transfer resources have been removed;
- This document contains no credentials or private endpoints.

## Follow-up Work

1. Replace the Loopback Thin Pool with production-grade dedicated storage, and configure persistent activation, monitoring, and recovery procedures.
2. Track Kata Issue #13484 and remove the timeout workaround after the upstream fix has been verified.
3. Validate persistent volumes, NetworkPolicy, resource pressure, kubelet/containerd abnormal failure, and concurrent deletion.
4. Synchronize pinned versions of Kata, Firecracker, Guest, and workload artifacts through an organization-approved supply chain validation path.
5. Replace the one-off Ubuntu 18.04 quickstart Guest with a continuously maintained, reproducibly built image.
6. Extend the bounded 1/5/10 Pod smoke tests to repeated 50/100 Pod concurrency tests, and compare against CubeSandbox using equivalent Ready criteria.
7. Fix Kata TAP network reachability to the Service VIP, and replace the temporary model relay with a production outbound link.
