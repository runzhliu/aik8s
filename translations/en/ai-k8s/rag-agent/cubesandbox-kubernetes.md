---
title: "CubeSandbox Kubernetes Deployment Prerequisites and Production Assessment"
description: "Verify CubeSandbox's 60ms cold start, KVM/PVM, XFS, eBPF, Helm, node privileges, and production readiness boundaries"
status: evolving
last_reviewed: 2026-08-29
---

# CubeSandbox Kubernetes Deployment Prerequisites and Production Assessment

!!! tip "Want to deploy directly?"
    This article focuses on prerequisites, risks, and production boundaries. For the complete node preflight, single-node values, Helm installation, template building, and first MicroVM sandbox acceptance, see [CubeSandbox Kubernetes in Practice: From Node Preflight to the First MicroVM Sandbox](cubesandbox-kubernetes-practice.md).

CubeSandbox is Tencent Cloud's open-source Agent execution environment: it uses KVM MicroVM to provide an independent Guest Kernel, and consists of CubeMaster, CubeAPI, Cubelet, CubeProxy, CubeVS, and CubeEgress for templating, scheduling, networking, snapshots, and execution APIs. The project is compatible with the E2B SDK, but it is not a Kubernetes SIG Apps Agent Sandbox CRD, nor is it a generic lifecycle layer that can use any `RuntimeClass` simply by installing a Controller.

As of 2026-08-29, the latest official stable release is [`v0.7.0`](https://github.com/TencentCloud/CubeSandbox/releases/tag/v0.7.0), and the Helm Chart's `version` and `appVersion` are both `0.7.0`. This chapter verifies against that release; when upgrading, re-check the Chart, node bootstrap scripts, and release notes.

Conclusions first:

- **It can be deployed on Kubernetes, but compute nodes must allow host-level integration.** The default Chart uses `privileged`, `hostPID`, multiple `hostPath`, `/dev/kvm`, host network namespace operations, and eBPF, and is not suitable for direct placement into a general-purpose business cluster that only allows Restricted Pod Security.
- **Native KVM is the simplest path.** Bare metal or Linux nodes with nested virtualization enabled can directly serve as compute nodes; ordinary x86 cloud VMs can use PVM, but this installs a customized host kernel, modifies GRUB/udev/fstab, and may automatically reboot the node.
- **Compute data must reside on XFS.** The trial default creates a 25 GiB loopback XFS; production should provision a dedicated XFS data disk for each compute node and mount it to `/data/cubelet`.
- **Kubernetes delivery is still marked Preview.** The official documentation explicitly notes eviction risks under resource pressure, compute node upgrade interruptions, and issues such as existing sandbox network disruption caused by `cube-node` Pod recreation.
- **The "60ms cold start" is not a Kubernetes end-to-end SLO.** It comes from a sandbox creation benchmark on a high-spec bare metal node where installation is complete and templates and data are already prepared; it does not include node scheduling, image pulling, Helm installation, PVM kernel-swap reboots, template building, or external proxy chains.

## 1. Performance and Product Positioning

The measurement boundaries covered by the CubeSandbox official README, the detailed Benchmark, and the Kubernetes documentation are not identical. When evaluating, API compatibility, MicroVM creation latency, and cluster end-to-end delivery should be recorded separately.

| Observation | What the official repository can prove | What cannot be inferred from it |
| --- | --- | --- |
| E2B compatibility | The official E2B-compatible API/SDK is provided, and applications can reuse part of the E2B calling conventions | API compatibility does not mean the underlying implementation, managed SLA, feature boundaries, or security responsibilities are identical |
| 60ms cold start | The official bare metal benchmark, in an environment with 96 logical cores, 375 GiB memory, NVMe XFS, 2 vCPU/2 GiB sandbox, and 3 warm-up rounds, shows single-concurrency create averaging 47.8ms, P95 57.4ms | Cannot be treated as an end-to-end SLO for arbitrary cloud VMs, cold images, Kubernetes scheduling, or high concurrency |
| 50 concurrent still in the hundreds of milliseconds | The README states an average of 67ms, P95 90ms, P99 137ms; the current detailed Benchmark records an average of 276.1ms, P95 508.4ms, maximum 681.3ms | The two sets of official data are inconsistent in methodology; the faster set cannot be cherry-picked; PoC must re-measure with fixed versions, hardware, templates, and statistical methods |
| Hardware-level isolation | Each sandbox runs in a KVM MicroVM with an independent Guest Kernel, with networking managed by CubeVS/eBPF and CubeEgress | MicroVM does not automatically solve authentication, credential exfiltration, default public egress, Prompt Injection, supply chain, or control plane exposure |

A more accurate statement is therefore: **CubeSandbox is a self-hosted KVM MicroVM platform for Agents; the official specific bare metal benchmark demonstrates approximately 48ms single-concurrency Create-to-Running; actual Kubernetes performance and production maturity must be re-validated.**

## 2. What Gets Installed on Kubernetes

The Helm Chart delivers both the control plane and the compute plane.

| Layer | Primary Components | Kubernetes Form | Key Dependencies |
| --- | --- | --- | --- |
| Control plane | CubeMaster, CubeAPI, CubeOps, WebUI, CLI | Deployment + Service | MySQL/PostgreSQL, Redis, object storage, PVC |
| Data ingress | CubeProxy, lifecycle manager | Deployment + Service/Ingress | TLS, wildcard domain, Redis, optional CoreDNS rewrite |
| Compute runtime | `cube-node` | DaemonSet Big Pod | KVM, hostPath, eBPF, XFS, host networking |
| Artifact installation | `cube-node-installer` | DaemonSet | Writes Shim, Kernel, Guest, Agent into the host toolbox directory |
| Node initialization | `cube-node-bootstrap` | `hostPID` + privileged DaemonSet | Mounts/checks XFS, loads modules, prepares host directories |
| PVM kernel swap | `cube-node-pvm` | DaemonSet that can reboot the host | x86_64, custom PVM kernel, GRUB, and reboot privileges |

This is a vertically integrated platform, not one where sandboxes are created as ordinary Pods by kubelet/runc. Kubernetes is responsible for delivering components and placing the control plane and compute plane DaemonSets; the actual Agent sandboxes are created by the in-node Cubelet, CubeShim, and KVM Hypervisor.

## 3. Hard Requirements and Recommended Conditions

### 3.1 Cluster and Tooling

| Item | Hard Requirement | Production Recommendation |
| --- | --- | --- |
| Kubernetes | `v1.24+` | Pin the Kubernetes, Chart, node OS, kernel, and CubeSandbox version matrix |
| Helm | `v3.10+` | Run `helm template`, preflight Hooks, and `helm test` before release |
| Storage | At least one usable StorageClass, or an explicit external database/object storage plan | Control plane uses CSI that can recover across nodes; do not rely on hostPath in multi-control-node environments |
| Images | All nodes can pull CubeSandbox images | Sync to an internal Registry, pin Digests, verify signatures; restrict who can publish privileged bootstrap images |
| Cluster privileges | Can create ClusterRole/Binding, DaemonSet, PVC, and allow the target Namespace to use privileged, hostPID, and hostPath | Use a separate low-trust cluster or dedicated node pool; grant only minimal exemptions to Cube's ServiceAccount and Namespace |
| CNI | Officially validated with TKE VPC-CNI, and Kubernetes/K3s + Flannel | For Cilium, Calico, and other CNIs, supplement with eBPF Hook, MTU, NAT, NetworkPolicy, and upgrade coexistence testing |
| DNS/ingress | If using the default internal wildcard domain, the Chart must be allowed to modify `kube-system/coredns` | When CoreDNS modification is not permitted, disable `cubeProxy.configureClusterDNS` and use the platform DNS instead; configure wildcard DNS, production TLS, and controlled ingress externally |

### 3.2 Nodes and Virtualization

| Role | Minimum/Recommended Spec | Additional Conditions |
| --- | --- | --- |
| Control plane nodes | At least 1; production recommends 3 or more; each at least 4C8G | Must be able to reach database, Redis, object storage, and compute nodes |
| Compute nodes | At least 1; official recommendation is 16C32G+ | Linux, `/dev/kvm` available, or use x86 PVM; dedicated nodes recommended |
| Single-node trial | Node initialization defaults to approximately 7.5GB minimum memory; in practice plan for at least 4C8G | The official recommendation does not favor the K8s single-node path, and the default 25GiB loopback is only for evaluation |

Compute nodes must also satisfy:

- Host kernel supports KVM; `/dev/kvm` exists after bootstrap completes;
- Host supports and mounts bpffs, and CubeVS can load eBPF programs;
- When using cgroup v2, the CPU Controller must be exposed and enabled;
- `/data/cubelet` is XFS; production recommends enabling reflink/project quota and planning capacity independently;
- CubeSandbox CIDR does not overlap with Service CIDR, Pod CIDR, VPC, node addresses, or existing routes;
- Nodes allow privileged Pods to enter host PID, Mount, and Network Namespaces, load kernel modules, and write to host directories;
- Nodes are not Serverless/Virtual Kubelet-style compute forms that do not expose the host and KVM.

### 3.3 x86_64, ARM64, and PVM

```text
计算节点已经有 /dev/kvm？
├─ 是
│  ├─ x86_64 → 原生 KVM 路径，最直接
│  └─ ARM64  → 使用原生 KVM 的物理机/裸金属；当前不走 PVM
└─ 否
   ├─ x86_64 → 可评估 PVM；会换宿主机内核并重启
   └─ ARM64  → 当前不支持 PVM，必须换成原生 KVM 节点
```

PVM is not an ordinary container plugin. By default, the Chart can let `cube-node-pvm` install the host kernel, set `kvm_pvm`, write GRUB and boot parameters, and coordinate reboots. The current default boot parameters include `nopti pti=off`, because the official PVM kernel path states that `kvm_pvm` does not yet support host KPTI; this expands the host-side side-channel risk, and PVM nodes should not colocate other untrusted containers or sensitive workloads.

ARM64 is supported in the project for native builds and runs, but the PVM host/Guest path remains primarily amd64. Before using ARM64 Kubernetes nodes, verify the multi-architecture control plane images, BM Guest Kernel, template images, and test results for the target Release one by one; do not infer that all Chart artifacts are covered simply because "the project supports ARM."

## 4. Node, Storage, and Network Preparation

### 4.1 Node Labels and Taints

At least two machines are recommended, separating the control plane from the compute plane:

```bash
# 控制面节点
kubectl label node <control-node> \
  cube.tencent.com/cube-control=true --overwrite

# 计算节点
kubectl label node <compute-node> \
  cube.tencent.com/cube-node=true --overwrite
kubectl taint node <compute-node> \
  cube.tencent.com/compute=true:NoSchedule --overwrite

# 仅限需要自动安装 PVM 宿主机内核的 x86 计算节点
kubectl label node <pvm-compute-node> \
  cube.tencent.com/allow-pvm-bootstrap=true --overwrite
```

The control plane taint is optional; the compute node taint is required by the official installation path. Do not apply `allow-pvm-bootstrap=true` to native KVM nodes or ARM64 nodes.

### 4.2 Compute Data Disk

Trial defaults:

```yaml
bootstrap:
  nodeInit:
    dataCubelet:
      loopback:
        enabled: true
        size: 25G
```

The first initialization creates `/data/cubelet-xfs.img`, mounted to `/data/cubelet` with XFS, reflink, and project quota. Later changes to `size` will not auto-expand.

For production, pre-mount a dedicated XFS data disk on each compute node and disable loopback:

```yaml
bootstrap:
  nodeInit:
    dataCubelet:
      loopback:
        enabled: false
```

The one-click deployment documentation treats 50GB as the minimum capacity for evaluation; multiple templates or custom images suggest starting from 200GB. Kubernetes production environments should still calculate separately based on templates, CoW layers, snapshots, logs, concurrent sandboxes, and retention periods, rather than directly copying the 25GB default.

### 4.3 Sandbox CIDR

The Chart default `cubeNode.network.cidr` is `172.16.0.0/18`. Before installation, at minimum verify:

- Kubernetes Service CIDR and existing ClusterIPs;
- Pod CIDR;
- Node host routes and VPC CIDR;
- Peered VPC, VPN, IDC, and cloud dedicated line routes;
- Whether the CubeEgress TPROXY address is the first usable address in that CIDR.

TKE presets switch to `192.168.0.0/18`, because the common TKE Service CIDR is `172.16.0.0/16`. Do not disable conflict checking to mask real overlaps; this causes unpredictable black holes and misrouting.

## 5. Minimal Installation Flow

### 5.1 Preflight

```bash
kubectl get nodes -o wide
kubectl get storageclass
helm version --short

# 每台计算节点都要核对
ls -l /dev/kvm
mount | grep ' /sys/fs/bpf '
findmnt -no FSTYPE,OPTIONS /data/cubelet
ip -4 addr
ip -4 route
```

If using PVM, `/dev/kvm` may not exist before the kernel swap, but you must confirm the node allows kernel installation, Bootloader updates, and reboots, and reserve a maintenance window for the first boot.

### 5.2 Minimal values

After copying from the official example, at minimum explicitly set the domain, TLS, MySQL, and Redis passwords:

```yaml
cubeProxy:
  advertiseIP: "10.0.1.10"
  domain: "sandbox.example.com"
  tls:
    mode: existingSecret
    existingSecret: cube-proxy-tls

mysql:
  host: ""
  password: "<generated-password>"
  rootPassword: "<generated-root-password>"

redis:
  host: ""
  password: "<generated-password>"
```

Production environments must not commit real passwords to Git. Use an external Secret manager or inject them in the release pipeline, and confirm that the Secrets generated by the Chart, database URLs, and object storage credentials cannot be read by tenants.

### 5.3 Installation and Verification

```bash
helm upgrade --install cube ./deploy/kubernetes/chart \
  --namespace cube-system \
  --create-namespace \
  --values runtime-values.yaml \
  --wait \
  --timeout 90m

kubectl get pods -n cube-system -o wide

kubectl exec -n cube-system deploy/cube-cubemastercli -- \
  sh -lc 'cubeopscli --address "$CUBEOPSCLI_ADDRESS" --port "$CUBEOPSCLI_PORT" node list'

helm test cube -n cube-system --timeout 20m --logs
```

`Pod Ready` is not sufficient. At minimum, continue by creating a fixed template, starting a sandbox, executing commands, verifying inbound proxy, DNS, egress policy, pause/resume, and destroy cleanup.

## 6. Primary Blockers Before Production

### 6.1 Kubernetes Delivery Is Still Preview

The official Kubernetes homepage currently still marks Preview, and explicitly lists:

- When compute node resources are tight, Pods may be evicted by Kubernetes and interrupt sandboxes;
- Compute plane upgrades rebuild `cube-node`, which may interrupt existing sandbox networking on that node;
- Control plane components, database, object storage, runtime, and node artifacts have independent upgrade surfaces.

Therefore, first validate with a separate test cluster, then move to low-risk workloads; do not treat the first PoC directly as a public multi-tenant production service.

### 6.2 `cube-node` Network Namespace and Upgrades

In the `v0.7.0` Chart, `cubeNode.hostNetwork` defaults to `false`. In this case, TAP devices and CubeVS hooks reside in the Network Namespace of the `cube-node` Pod; Pod recreation causes both inbound and outbound traffic of existing sandboxes on that node to be interrupted simultaneously, and cannot be automatically recovered.

The current version of `values.yaml` has already exposed `cubeNode.hostNetwork`. Before creating any production sandbox, you should evaluate whether to set:

```yaml
cubeNode:
  hostNetwork: true
```

The cost is:

- Kubernetes NetworkPolicy no longer applies directly to sandbox traffic;
- Cubelet ports such as 9998, 9999, and 9966 bind to the node;
- Monitoring, firewall, and auditing must migrate from Pod IP to Node IP;
- Nodes must be dedicated, and the network boundary must be supplemented with CubeEgress, node firewall, or a standalone Egress Proxy.

There is version drift between the official installation page and the current Chart source for this values switch. You must rely on the `values.yaml` of a pinned Release and its rendered output.

### 6.3 Default Authentication and TLS Are Only Suitable for Trial Use

CubeAPI does not enable authentication by default; when `AUTH_CALLBACK_URL` is not set, requests are passed through directly. The Chart's default Proxy TLS is `selfSigned`, which is also only suitable for testing. At minimum, production requires:

- Configure an Auth Callback for CubeAPI, and validate identity, tenant, request path, and HTTP method simultaneously;
- Keep CubeMaster, Cubelet, CubeOps, WebUI, database, Redis, and MinIO inside a controlled network;
- Use `existingSecret` or cert-manager to configure production TLS;
- Prohibit direct exposure of the control plane, Cubelet gRPC/HTTP, and WebUI to the public internet;
- Keep long-lived cloud, Git, and database credentials in the Tool Gateway/Credential Broker, not in Guest images or Workspaces.

The Chart can inject the callback address via `controlPlane.api.env`, for example:

```yaml
controlPlane:
  api:
    env:
      - name: AUTH_CALLBACK_URL
        value: "https://auth.example.com/verify"
```

When the callback service is unreachable, the request must be treated as a failed rejection and included in availability and latency SLOs.

### 6.4 Privileged Node Bootstrap Is Equivalent to Host Root

The node initialization script enters the host namespace through `hostPID`, `nsenter`, `chroot /host`, and privileged permissions. It can load kernel modules, create block devices, modify XFS, write udev/fstab/GRUB, and reboot the machine. Any compromise of the bootstrap image supply chain is equivalent to a compute node Root compromise.

Production requirements:

- Bootstrap images must be pinned by Digest, signature-verified, and sourced from a controlled Registry;
- Only platform administrators can modify Helm values, DaemonSets, ServiceAccounts, and images;
- Compute nodes must not run the Kubernetes control plane, key managers, CI runners, or sensitive workloads;
- Host changes require audit, Canary, maintenance windows, and rollback scripts;
- During uninstall, labels, taints, hostPath, kernel, GRUB, udev, fstab, and XFS must be cleaned up separately; you cannot assume `helm uninstall` will restore the host.

### 6.5 Control Plane Data and High Availability

The Chart can bundle MySQL, Redis, and MinIO, but "having a StatefulSet" does not equal production HA. You need to clarify:

- Database primary/replica, backup, recovery points, and upgrade strategy;
- Redis Sentinel/external service and failover behavior;
- S3-compatible object storage availability, versioning, encryption, and lifecycle;
- Replica counts, session handling, and dependency failure behavior for CubeMaster/CubeOps/API/Proxy;
- How running sandboxes, paused sandboxes, templates, and snapshots are each recovered when a node fails.

The cross-node pause/resume recovery and S3 backend added in `v0.7.0` still include Preview capabilities; the release notes also list full-path control-link HA and node failure recovery as future work. "Cross-machine support" must not be interpreted as already covering all disaster recovery scenarios.

## 7. Suggested PoC Acceptance Criteria

### 7.1 Functionality

- Complete install, reboot, uninstall, and reinstall on the target node OS, kernel, CPU architecture, and Kubernetes version;
- Build templates with pinned image Digests and run real Agent tools such as Python/Node/browser;
- Verify files, PTY, long output, signals, concurrent processes, pause/resume, snapshot/clone;
- Verify failure behavior for nodes, CubeMaster, Redis, database, object storage, and Proxy.

### 7.2 Performance

- Measure Create-to-Running separately for cold templates, hot templates, single concurrency, and business peak concurrency;
- Report P50/P95/P99, error rate, timeout, and reclamation latency, not just minimum values;
- Record Kubernetes scheduling, image pull, template build, MicroVM startup, and first command execution separately;
- Estimate density using real sandbox memory write volume; do not extrapolate full-load capacity from idle values of approximately 25–34MB;
- Stress-test XFS Metadata, CoW, snapshots, object storage, DNS, Proxy, and Egress separately.

### 7.3 Security

- Verify that Guests cannot read host data, Kubernetes ServiceAccounts, kubelet, cloud metadata, or other tenants' data;
- Verify default egress denial, domain/CIDR policies, DNS Rebinding, redirects, and IPv6;
- Verify that API authentication simultaneously restricts path, method, tenant, and resource ownership;
- Conduct versioned security reviews of Cube's privileged DaemonSet, Hypervisor, Guest Kernel, CubeVS, and CubeEgress;
- Execute resource exhaustion, log flooding, disk full, abnormal power loss, and upgrade interruption tests.

## 8. When It Is Worth Choosing

Suitable for serious PoC:

- Must be self-hosted and require stronger MicroVM isolation than a shared host kernel;
- Want to reuse the E2B SDK while controlling nodes, network, templates, and data;
- Sandbox volume is large, and cold start and idle density are sufficient to offset virtualization and node operations investment;
- The team already has Kubernetes, Linux Kernel, KVM, eBPF, networking, and storage engineering capabilities;
- Can provide a dedicated low-trust cluster or node pool, and accept version pinning and upgrade drills during the Preview phase.

Do not choose it yet:

- The cluster does not allow privileged, hostPID, hostPath, kernel modules, or node reboots;
- Only Serverless Kubernetes/Virtual Node is available;
- There are no dedicated compute nodes, and it must colocate with sensitive workloads or the Kubernetes control plane;
- Only a few dozen low-risk sandboxes are needed, and the team does not want to maintain kernel, networking, database, and object storage;
- You need mature SLAs, full-path HA, cross-node failure recovery, and zero-downtime upgrades today.

For such scenarios, first compare Kubernetes SIG Agent Sandbox + gVisor/Kata, KubeVirt, or managed APIs such as E2B/Modal/Daytona. For a tiered selection methodology, see [Agent Sandbox Selection and Architecture Analysis](agent-sandbox-selection.md).

## Official References

- [CubeSandbox GitHub](https://github.com/TencentCloud/CubeSandbox)
- [v0.7.0 Release](https://github.com/TencentCloud/CubeSandbox/releases/tag/v0.7.0)
- [Kubernetes Deployment Overview](https://cubesandbox.com/zh/guide/kubernetes/)
- [Helm Installation](https://cubesandbox.com/zh/guide/kubernetes/install)
- [Kubernetes Architecture Documentation](https://cubesandbox.com/zh/guide/kubernetes/architecture)
- [Kubernetes FAQ](https://cubesandbox.com/zh/guide/kubernetes/faq)
- [v0.7.0 Chart Default Values](https://github.com/TencentCloud/CubeSandbox/blob/v0.7.0/deploy/kubernetes/chart/values.yaml)
- [v0.7.0 Node Initialization Script](https://github.com/TencentCloud/CubeSandbox/blob/v0.7.0/deploy/kubernetes/images/scripts/cube-node-init.sh)
- [Bare Metal Performance Benchmark](https://github.com/TencentCloud/CubeSandbox/blob/v0.7.0/docs/zh/blog/posts/2026-06-01-cubesandbox-perf-benchmark.md)
- [PVM Performance Benchmark](https://github.com/TencentCloud/CubeSandbox/blob/v0.7.0/docs/zh/blog/posts/2026-06-03-cubesandbox-perf-benchmark-pvm.md)
- [ARM64 Support Documentation](https://github.com/TencentCloud/CubeSandbox/blob/v0.7.0/docs/zh/blog/posts/2026-07-08-cubesandbox-arm-support.md)
- [Authentication Configuration](https://cubesandbox.com/zh/guide/authentication)
- [Network Hardening](https://cubesandbox.com/zh/guide/network-hardening)
