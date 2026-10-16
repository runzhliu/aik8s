---
title: "CubeSandbox Kubernetes in Practice: From Node Preflight to the First MicroVM Sandbox"
description: "Deploy CubeSandbox v0.7.0 in an existing Kubernetes cluster, completing KVM, XFS, Helm, node registration, template building, and sandbox lifecycle acceptance"
status: lab
last_reviewed: 2026-08-29
---

# CubeSandbox Kubernetes in Practice: From Node Preflight to the First MicroVM Sandbox

This article documents a real CubeSandbox Kubernetes deployment: not just getting the Pod to become `Running`, but also having the compute node successfully register, the template complete its build, the KVM MicroVM actually boot, commands execute, and finally cleaning up the test sandbox completely.

The experiment is pinned to the official [`v0.7.0`](https://github.com/TencentCloud/CubeSandbox/releases/tag/v0.7.0). Kubernetes delivery is still marked Preview in this release, so this article is a reproducible PoC path, not a drop-in answer for production. For deployment prerequisites, host permissions, PVM risks, and production blockers, see [CubeSandbox Kubernetes Deployment Prerequisites and Production Assessment](cubesandbox-kubernetes.md); if you want to continue using it as the enterprise execution surface for OpenClaw / DSH, see [Enhancing OpenClaw and DSH with CubeSandbox](cubesandbox-openclaw-dsh-enterprise-practice.md).

Here are the final results up front:

- The Helm release successfully entered `deployed`, with the control plane, three StatefulSets, and three groups of node DaemonSets all Ready;
- All 4 PVCs bound, with persistent volumes for CubeMaster, MySQL, Redis, and MinIO data;
- All 8 groups of Helm tests bundled with the official Chart passed `Succeeded`;
- A native KVM compute node registered as `HEALTHY=true` and `HOST_STATUS=RUNNING`;
- The official `sandbox-code` image was used to build an `READY` template;
- The temporary sandbox successfully entered `running`, executed commands in the Guest, and was then destroyed cleanly;
- After acceptance testing, the sandbox count returned to 0, and the pre-existing KubeVirt VMs on the node continued running.

All addresses, node names, repositories, and credentials in this article use public placeholders. `<...>` must be replaced with your own environment values.

## 1. Experiment Goals and Boundaries

This is not starting from a blank server. Instead, in an existing Kubernetes cluster, we select one test node with native KVM support and let it carry both the CubeSandbox control plane and the compute plane.

There are three reasons for choosing this path:

1. Verify whether CubeSandbox can coexist with existing Kubernetes, CNI, CSI, and KubeVirt workloads;
2. Avoid PVM's host kernel replacement and reboot, narrowing the variables down to the Chart, node initialization, storage, and networking;
3. Run the full lifecycle through with minimal resources before deciding whether to build a dedicated node pool.

The experiment uses the following anonymized specifications:

| Item | Lab Configuration | Notes |
| --- | --- | --- |
| CubeSandbox | `v0.7.0` | Chart and components use the same version |
| Kubernetes | `v1.30.x` | Above the official `v1.24+` minimum |
| Node architecture | `linux/amd64` | Native KVM, no PVM |
| Node kernel | Linux 5.10 | `/dev/kvm` available, KVM module loaded |
| CPU / Memory | 100+ logical CPUs, 250 GiB+ memory | Well above the functional verification minimum |
| CNI | Cilium 1.16.x | This smoke test passed, but this is not full compatibility certification |
| Control plane storage | Local LVM StorageClass | Only suitable for single-node PoC, no cross-node recovery |
| `/data/cubelet` | XFS | CubeSandbox template and CoW data directory |
| Existing workloads | KubeVirt VMI | Runtime status checked before and after deployment |

The following was intentionally not done this time:

- No `NoSchedule` taint was added to the shared test node;
- No `cube.tencent.com/allow-pvm-bootstrap=true` was added;
- No PVM host kernel was installed, no GRUB changes, and no node reboot;
- The Chart was not allowed to modify cluster CoreDNS;
- WebUI, CubeAPI, and management endpoints were not exposed to the public internet;
- No high-concurrency, Pause/Resume, Snapshot, cross-node recovery, or production SLO testing.

Production environments should use a dedicated node pool and taint the compute nodes. The shared node is only meant to answer "can it run through," not as a recommended architecture.

## 2. First Understand What Installation Will Change

CubeSandbox is not just installing a few ordinary Deployments. The Chart delivers the control plane, ingress, and host-level node runtime at the same time:

| Component | Kubernetes Form | Primary Role |
| --- | --- | --- |
| CubeMaster, CubeAPI, CubeOps, WebUI | Deployment | Templates, scheduling, API, operations, and management UI |
| MySQL, Redis, MinIO | StatefulSet | Metadata, cache, template and snapshot artifacts |
| CubeProxy, Lifecycle Manager | Deployment + Service | Sandbox inbound proxy and lifecycle coordination |
| `cube-node-installer` | DaemonSet | Installs Cubelet, Shim, Guest, Kernel, and other node artifacts |
| `cube-node-bootstrap` | privileged DaemonSet | Checks KVM, XFS, bpffs, cgroup, and host directories |
| `cube-node` | privileged Big Pod | Runs Cubelet, CubeEgress, and the node-side sandbox runtime |

Node components by default require `privileged`, `hostPID`, `hostPath`, and `/dev/kvm`. This is equivalent to wiring a virtualization runtime into the host, and it should not be installed into a general-purpose multi-tenant cluster without isolation boundaries and supply chain controls.

## 3. Node Preflight: First Prove the Host Meets the Requirements

### 3.1 Kubernetes and Storage

First confirm the current context, nodes, StorageClass, and default volume capacity:

```bash
kubectl config current-context
kubectl version
kubectl get nodes -o wide
kubectl get storageclass
kubectl get pv
```

The most easily overlooked issue in a single-node PoC is the total control plane PVC size. The default values in the `v0.7.0` Chart are:

| PVC | Default Capacity |
| --- | ---: |
| CubeMaster | 20 GiB |
| MySQL | 20 GiB |
| Redis | 10 GiB |
| MinIO | 20 GiB |
| Total | 70 GiB |

The lab node's Local LVM allocatable capacity is only about 60 GiB. If the defaults are used directly, it is impossible for all four PVCs to bind successfully. Therefore, the PoC shrinks them to 5 + 10 + 2 + 10 GiB, for a total of 27 GiB.

This is only a functional verification specification. Production should not copy the 27 GiB figure; capacity must be re-planned based on template count, database retention, snapshot backend, logs, and recovery targets.

### 3.2 KVM, XFS, bpffs, and cgroup

Each compute node must be checked:

```bash
# KVM 设备
ls -l /dev/kvm

# CPU 虚拟化与 KVM 模块
grep -Eoc '(vmx|svm)' /proc/cpuinfo
lsmod | grep -E '^kvm'

# BPF 文件系统
findmnt /sys/fs/bpf

# Cubelet 数据目录
findmnt -T /data/cubelet
df -h /data/cubelet

# cgroup CPU controller
mount | grep cgroup
```

The acceptance focus is not "the command produced output," but:

- `/dev/kvm` can be opened, not just that the file exists;
- `kvm_intel` or `kvm_amd` is loaded;
- `/data/cubelet` ultimately lands on XFS;
- bpffs is mounted;
- The cgroup CPU controller is available;
- Node memory is clearly above the Chart's minimum check value;
- Host routes do not occupy the CIDR reserved for CubeSandbox.

If the node is already on XFS, `/data/cubelet` can be used directly. If the root disk is not XFS, the PoC can let bootstrap create a loopback XFS; production should use a dedicated data disk.

### 3.3 Network CIDR

The Chart's default sandbox network is `172.16.0.0/18`. Before installation, at minimum compare:

```bash
# Pod CIDR
kubectl get nodes -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.podCIDR}{"\n"}{end}'

# Service CIDR 可从 apiserver 参数或集群配置中查询
kubectl -n kube-system get pods -l component=kube-apiserver -o yaml | grep service-cluster-ip-range

# 节点本地路由
ip -4 route
```

Also manually verify VPC, peering networks, VPN, and IDC routes. Helm's Service CIDR preflight cannot detect all external route conflicts.

In this experiment:

- The Pod CIDR belongs to `10.0.0.0/8`;
- The Service CIDR is `10.96.0.0/12`;
- Node addresses are in a different `10.0.0.0/8` subnet;
- `172.16.0.0/18` does not overlap with known cluster addresses.

This only proves there is no direct conflict inside the cluster; it does not replace route verification by the external network team.

### 3.4 Image Reachability

CubeSandbox control plane images, node artifact images, and subsequent template images must all be reachable by the target environment. Offline or restricted networks should first sync images to a Registry reachable by the nodes, and pin versions or Digests.

This article does not cover image mirroring, re-tagging, or private registry operations; these steps are highly dependent on the enterprise network. Before installation, only two things need to be ensured:

1. Kubernetes nodes can pull all images rendered by the Chart;
2. CubeMaster's template build chain can also access the template image registry and trust its TLS CA.

The second point is easy to miss: the node's containerd being able to pull private images does not mean CubeMaster's internal OCI client automatically inherits the same CA. This is explained separately later.

## 4. Pin the Version and Prepare values

### 4.1 Fetch and Inspect the Chart

```bash
git clone https://github.com/TencentCloud/CubeSandbox.git
cd CubeSandbox
git checkout v0.7.0

helm lint deploy/kubernetes/chart \
  -f deploy/kubernetes/chart/values-single-node.yaml \
  -f runtime-values.yaml
```

Do not deploy with `master` directly and then troubleshoot against the documentation of some other Release. The Chart, images, Guest Kernel, and CLI should all be pinned to the same version.

### 4.2 Key values for the Single-Node PoC

Below is the public version used in this experiment. Passwords are placed only in privately injected values at release time and must not be committed to Git.

```yaml
cubeProxy:
  advertiseIP: "<node-ip>"
  domain: "sandbox.example.test"
  configureClusterDNS: false
  service:
    type: NodePort
    nodePorts:
      http: 30080
      https: 30443
      grpc: 30090
      admin: ""
  ingress:
    enabled: false
  tls:
    mode: selfSigned

persistence:
  storageClassName: <storage-class>

controlPlane:
  master:
    persistence:
      size: 5Gi

mysql:
  password: "<generated-password>"
  rootPassword: "<generated-root-password>"
  persistence:
    size: 10Gi

redis:
  password: "<generated-password>"
  persistence:
    size: 2Gi

minio:
  persistence:
    size: 10Gi

bootstrap:
  pvmHostKernel:
    enabled: false
  nodeInit:
    dataCubelet:
      loopback:
        enabled: true
        imagePath: /data/cubelet-xfs.img
        size: 25G

cubeNode:
  pvmGuestKernel:
    enabled: false
  hostNetwork: false
  network:
    cidr: "172.16.0.0/18"
    cidrSkipConflictCheck: false
```

Several key choices:

- `pvmHostKernel.enabled=false`: prevents the Chart from installing the PVM host kernel;
- `pvmGuestKernel.enabled=false`: uses the standard BM Guest Kernel;
- `configureClusterDNS=false`: does not modify cluster CoreDNS;
- `hostNetwork=false`: keeps the default Pod network, suitable for PoC;
- `cidrSkipConflictCheck=false`: keeps network conflict protection;
- 4 PVCs totaling 27 GiB: fits the limited Local LVM space in this experiment;
- `selfSigned` + NodePort: only for the controlled test network.

`cubeProxy.service.type=NodePort` has an easily misjudged detail: even if the nodePort of `admin` is left empty, Kubernetes will still automatically assign a NodePort for the admin port in the Service. Token authentication is not a substitute for a firewall; production should not expose this Service to an untrusted network directly.

### 4.3 Why Both PVM Switches Must Be Turned Off

Setting only `cubeNode.pvmGuestKernel.enabled=false` is not sufficient. The Chart also has a separate host PVM installation path:

```yaml
bootstrap:
  pvmHostKernel:
    enabled: false
cubeNode:
  pvmGuestKernel:
    enabled: false
```

At the same time, do not add the following to native KVM nodes:

```text
cube.tencent.com/allow-pvm-bootstrap=true
```

Before the actual installation, inspect the final rendered result:

```bash
helm template cube deploy/kubernetes/chart \
  --namespace cube-system \
  -f deploy/kubernetes/chart/values-single-node.yaml \
  -f runtime-values.yaml \
  | grep -E 'PVM_FEATURE_ENABLED|CUBE_PVM_ENABLE|cube-node-pvm'
```

The expected PVM value in node initialization is `0`, and no `cube-node-pvm` DaemonSet is generated.

## 5. Installation: dry-run First, Then Write to the Cluster

### 5.1 Label the Node

The single-node profile requires the same machine to carry both control plane and compute plane labels:

```bash
kubectl label node <node-name> \
  cube.tencent.com/cube-control=true \
  cube.tencent.com/cube-node=true \
  --overwrite
```

The shared PoC node has no taint added, to avoid evicting or blocking existing workloads. Production dedicated compute nodes should have the `NoSchedule` taint added, and the Chart toleration should be confirmed to match the platform policy.

### 5.2 Server-Side dry-run

Local `helm lint` and `helm template` can only validate templates. Helm versions that support server dry-run can continue with:

```bash
helm upgrade --install cube deploy/kubernetes/chart \
  --namespace cube-system \
  --create-namespace \
  -f deploy/kubernetes/chart/values-single-node.yaml \
  -f runtime-values.yaml \
  --dry-run=server \
  --hide-secret >/dev/null
```

This step can surface API version, admission policy, CRD, and some cluster-side constraint issues in advance, while avoiding printing Secrets to the terminal.

### 5.3 Actual Installation

```bash
helm upgrade --install cube deploy/kubernetes/chart \
  --namespace cube-system \
  --create-namespace \
  -f deploy/kubernetes/chart/values-single-node.yaml \
  -f runtime-values.yaml \
  --wait \
  --wait-for-jobs \
  --timeout 90m
```

During installation, open another terminal to observe:

```bash
kubectl get pods,pvc,jobs -n cube-system -o wide -w
```

Under normal conditions, the following will appear in sequence:

1. MySQL, Redis, MinIO, and PVCs become ready;
2. CubeMaster, CubeOps, CubeAPI, WebUI, and CubeProxy start;
3. `cube-node-installer` installs node runtime artifacts;
4. `cube-node-bootstrap` checks KVM, XFS, bpffs, CIDR, and CubeMaster connectivity;
5. `cube-node` Big Pod starts and registers with CubeOps.

## 6. A Real Startup Race: When to Wait, When to Investigate

The following phenomena appeared in the first minute of this installation:

- CubeMaster could not resolve the MySQL Service on first startup;
- CubeOps and Lifecycle Manager restarted because CubeMaster was not yet Ready;
- `cube-node-bootstrap` had passed the KVM, XFS, bpffs, and CIDR checks, but could not reach CubeMaster at the end;
- `cube-node` was stuck in the Init phase waiting for node prep.

Shortly afterward, MySQL and Service DNS became ready, CubeMaster started successfully on the next retry, bootstrap re-ran and passed, and all components entered Ready.

This kind of phenomenon can be observed briefly, but it cannot be handled with "just wait a bit longer." It is recommended to confirm in the following order:

```bash
kubectl get pods,svc,endpoints,pvc -n cube-system -o wide

kubectl logs -n cube-system \
  -l app.kubernetes.io/component=cube-node-bootstrap \
  -c cube-node-init --tail=200

kubectl logs -n cube-system deploy/cube-master \
  -c cube-master --tail=200

kubectl get events -n cube-system --sort-by=.lastTimestamp | tail -50
```

Judgment criteria:

- If the dependent Service and Endpoints have appeared, the retry count stops growing, and all Pods eventually become Ready, it can be classified as startup timing;
- If DNS `NXDOMAIN`, PVC Pending, KVM/XFS check failures, or ImagePullBackOff persist, the root cause must be fixed;
- Do not disable CIDR, KVM, XFS, or memory checks just to make bootstrap turn green.

Troubleshooting logs may contain database URLs, passwords, or admin tokens. Public articles and tickets should redact them first; in production, credentials must be rotated after any leak.

## 7. Acceptance: Four-Layer Checks After Pods Are Ready

### 7.1 Kubernetes Resources

```bash
helm status cube -n cube-system
kubectl get deploy,statefulset,daemonset -n cube-system
kubectl get pvc -n cube-system
```

Results this time:

| Resource | Result |
| --- | ---: |
| Deployment | 7/7 Ready |
| StatefulSet | 3/3 Ready |
| DaemonSet | 3/3 Ready |
| PVC | 4/4 Bound |

### 7.2 Node Registration

```bash
kubectl exec -n cube-system deploy/cube-cubemastercli -- \
  sh -lc 'cubeopscli \
    --address "$CUBEOPSCLI_ADDRESS" \
    --port "$CUBEOPSCLI_PORT" \
    node list'
```

At minimum, confirm:

- `HEALTHY=true`;
- `HOST_STATUS=RUNNING`;
- `SCHEDULING_DISABLED=false`;
- Component versions all match the target Release;
- Kernel variant is `bm`, not PVM;
- CPU, memory, and disk metrics are not 0.

### 7.3 Official Helm Tests

```bash
helm test cube -n cube-system --timeout 20m --logs
```

`v0.7.0` actually ran 8 test suites:

| Test Suite | What It Verifies |
| --- | --- |
| `cube-health-test` | CubeMaster, CubeOps, CubeAPI, WebUI, Proxy, Node health |
| `cube-cubemastercli-test` | CLI can reach CubeMaster and the sandbox list |
| `cube-cubeopscli-test` | CLI can reach CubeOps and the node list |
| `cube-mysql-test` | MySQL liveness |
| `cube-redis-test` | Redis `PONG` |
| `cube-proxy-control-test` | Proxy ClusterIP control path |
| `cube-node-image-test` | Node images and artifacts |
| `cube-node-runtime-test` | Host runtime assets |

All 8 suites were `Succeeded` this time.

### 7.4 Coexistence with Existing KVM Workloads

If the test node already has KubeVirt, libvirt, or other KVM consumers, you must re-check after installation:

```bash
kubectl get vmi -A -o wide
kubectl get node <node-name> -o jsonpath='{.spec.taints}'
```

The 4 pre-existing KubeVirt VMIs on the node all remained `Running/Ready` after installation, and no new taints were added to the node. This only shows that a single low-concurrency PoC did not conflict immediately; it does not prove that the two virtualization platforms are long-term compatible under resource pressure, upgrades, and failure scenarios.

## 8. Building the First Template

CubeSandbox cannot directly treat an arbitrary OCI image as a running sandbox. It must first convert the image into a template: pull the image, unpack the rootfs, start a temporary MicroVM, wait for the HTTP probe, take a snapshot, and then distribute the artifact to compute nodes.

Using the official `sandbox-code` image:

```bash
kubectl exec -n cube-system deploy/cube-cubemastercli -- \
  sh -lc 'cubemastercli \
    --address "$CUBEMASTERCLI_ADDRESS" \
    --port "$CUBEMASTERCLI_PORT" \
    tpl create-from-image \
    --image <registry>/cube-sandbox/sandbox-code@sha256:<digest> \
    --alias k8s-smoke \
    --writable-layer-size 1G \
    --expose-port 49999 \
    --expose-port 49983 \
    --probe 49999 \
    --probe-path /health \
    --node <compute-node>'
```

For a private registry, you can use `--registry-username` and `--registry-password`, but do not write passwords directly into shell history. A more robust approach is injection via Secrets, short-lived credentials, or a controlled pipeline.

### 8.1 The Hidden Problem of a Private Registry CA

The first template build this time failed at `PULLING`: the node's containerd could already pull from the same registry, but CubeMaster's native OCI export flow reported `x509: certificate signed by unknown authority`.

The reason is that the two pull paths are different:

```text
Kubernetes Pod 镜像
  → kubelet / containerd
  → 节点上的 registry 配置与 CA

CubeSandbox 模板镜像
  → CubeMaster / Cubelet 的 OCI 客户端
  → 容器自己的 CA 信任链
```

The production solution should be:

- Use a trusted HTTPS certificate for the Registry; or
- Inject the enterprise CA into CubeMaster and the relevant template build components via ConfigMap/Secret or a customized image;
- Pin the image Digest to avoid `latest` drift;
- Test template image pulling separately during installation acceptance.

Do not treat disabling TLS verification as a long-term solution, and do not skip template build testing just because Kubernetes Pods can pull the image.

### 8.2 Observing Template Status

```bash
kubectl exec -n cube-system deploy/cube-cubemastercli -- \
  sh -lc 'cubemastercli \
    --address "$CUBEMASTERCLI_ADDRESS" \
    --port "$CUBEMASTERCLI_PORT" \
    tpl list -o wide'
```

A successful build will pass through the following stages in order:

```text
PULLING
  → UNPACKING
  → DISTRIBUTING
  → CREATING_TEMPLATE
  → READY
```

This time, the template eventually reached `1/1 ready` on the single compute node.

## 9. Minimal Business Loop: Create → Exec → Destroy

The official Helm tests already cover a large amount of component health, but you still need to create a real sandbox.

### 9.1 Temporarily Forwarding CubeAPI

```bash
kubectl port-forward --address 127.0.0.1 \
  -n cube-system service/cube-api 13000:3000
```

### 9.2 Creating a Sandbox

```bash
response="$(curl -sS --fail-with-body \
    -X POST http://127.0.0.1:13000/sandboxes \
    -H 'Content-Type: application/json' \
    -H 'X-API-Key: e2b_000000' \
    -d '{
      "templateID": "<template-id>",
      "timeout": 300,
      "autoPause": false
    }')"

sandbox_id="$(printf '%s' "$response" | jq -r '.sandboxID')"
printf 'sandbox_id=%s\n' "$sandbox_id"
```

In the test environment, CubeAPI does not have API Key validation additionally enabled, but the SDK and example clients still require a non-empty placeholder value. Production environments must integrate formal authentication; do not interpret this placeholder value as a security credential.

### 9.3 Executing Commands in the Sandbox

```bash
kubectl exec -n cube-system daemonset/cube-node -c cubelet -- \
  cubecli exec "$sandbox_id" sh -lc '
    echo cube-smoke-ok
    uname -m
    uname -r
    findmnt -n -o FSTYPE /
  '
```

The actual output this time proved:

- Sandbox status is `running`;
- Guest architecture is `x86_64`;
- The Guest Kernel differs from the host kernel;
- The rootfs uses overlay;
- Commands executed successfully in the isolated environment.

### 9.4 Destroying and Confirming No Residue

```bash
curl -sS --fail-with-body \
  -X DELETE "http://127.0.0.1:13000/sandboxes/${sandbox_id}" \
  -H 'X-API-Key: e2b_000000'

kubectl exec -n cube-system deploy/cube-cubemastercli -- \
  sh -lc 'cubemastercli \
    --address "$CUBEMASTERCLI_ADDRESS" \
    --port "$CUBEMASTERCLI_PORT" \
    cubebox list'
```

At the end of acceptance, `SANDBOX_COUNT` should return to 0. Automation scripts should use `trap` or `finally` to ensure test sandboxes are cleaned up even if a mid-run failure occurs.

## 10. WebUI: The Most Intuitive Entry Point After Deployment

The WebUI Service defaults to ClusterIP. In a test environment, you can listen only on the local loopback address:

```bash
kubectl port-forward --address 127.0.0.1 \
  -n cube-system service/cube-webui 12088:12088
```

Open in a browser:

```text
http://127.0.0.1:12088
```

The default test account for first login of `v0.7.0` is `admin / admin`. After logging in, change the password immediately in Settings. Do not expose the WebUI or CubeOps `:3010` directly to the public internet.

The pages most worth looking at first:

| Page | Questions It Answers |
| --- | --- |
| Overview | Current sandbox count, resource pressure, and healthy node count |
| Nodes | Whether nodes are Ready, versions are consistent, and whether nodes are isolated |
| Templates | Whether templates are READY and at which stage a build task failed |
| Sandboxes | Sandbox status, template, node, and lifecycle operations |
| Versions | Whether Cubelet, Shim, Guest, Kernel, and Agent are on the same version |
| Network | Ingress and network-related configuration |
| Observability | Runtime, template build, and sandbox health overview |
| API Keys | SDK credential management |

## 11. What You Can Play With and Test After Deployment

Dividing tests into four levels avoids jumping straight to high concurrency and mixing basic issues with performance issues.

### 11.1 Level 1: Functional Smoke Test

The goal is to prove that one complete path works:

1. WebUI login;
2. Node is `HEALTHY/RUNNING`;
3. Build an `sandbox-code` template;
4. Create a sandbox;
5. Execute shell and Python;
6. Read and write temporary files;
7. Destroy the sandbox and confirm the count returns to 0.

You can use the E2B-compatible SDK:

```bash
python -m venv .venv
source .venv/bin/activate
pip install e2b-code-interpreter

export E2B_API_URL=http://127.0.0.1:13000
export E2B_API_KEY=e2b_000000
export CUBE_TEMPLATE_ID=<template-id>
```

```python
import os
from e2b_code_interpreter import Sandbox

with Sandbox.create(template=os.environ["CUBE_TEMPLATE_ID"]) as sandbox:
    result = sandbox.run_code("print(sum(i * i for i in range(10)))")
    print(result)
```

### 11.2 Level 2: Templates and Lifecycle

Capabilities worth exploring:

- Build templates from different OCI images;
- Override command, args, env, and probe for templates;
- Pause / Resume;
- Create a Snapshot;
- Create a new sandbox from a Snapshot;
- Rollback and Clone;
- Template alias and version upgrades;
- Re-distribution of templates across multiple compute nodes.

Record during testing:

- Create-to-Running;
- Duration of each phase: Pause, Resume, Snapshot, Rollback;
- Whether memory state and file state are preserved as expected;
- Whether old Snapshots remain compatible after template or Guest version upgrades;
- Whether lifecycle failures leave orphan runtime, tap, volume, or metadata behind.

### 11.3 Level 3: Network and Security

At minimum, verify four paths:

| Test | Expected Result |
| --- | --- |
| Sandbox accesses the public internet | Controlled by `allow_internet_access` |
| Sandbox accesses the cluster/internal network | Default policy matches expectations; sensitive subnets are not accidentally allowed |
| External access to sandbox ports | Wildcard domain, TLS, HTTP/gRPC Proxy all work normally |
| Dynamic network policy updates | Whether rules are replaced or merged matches documented behavior |

Further tests you can run:

- DNS inheritance, search domains, and `ndots`;
- `allowOut`, `denyOut`, and rule priority;
- `allow_public_traffic=false` and access Tokens;
- CubeEgress proxy, auditing, and credential injection;
- Coexistence of Cilium/Calico with CubeVS eBPF Hooks;
- MTU, NAT, long connections, WebSocket, and gRPC.

Do not run uncontrolled Agent red-team experiments on test nodes that can still reach the production internal network. Network default-deny must be verified with packet captures and target service logs, not just by observing that the API returns success.

### 11.4 Level 4: Storage, Performance, and Faults

Storage tests you can run:

- MinIO/S3 persistent volumes;
- Re-mounting the same volume after destroying a sandbox;
- Multi-tenant volume isolation;
- XFS reflink and project quota;
- Scheduling and alerting when the data disk approaches 80% usage;
- Snapshot backend failure and recovery.

For performance, do not only measure averages:

- Single-concurrency cold start and warm start;
- Creation at 1, 10, 50, and 100 concurrent requests;
- P50, P95, P99, and maximum values;
- Phase-by-phase timing for Create API, scheduling, Cubelet, and Guest probe;
- Different template sizes and writable layer sizes;
- Sandbox density per node, host memory overhead, and CPU overcommit;
- Storage and network resource reclamation after mass destruction.

Fault tests you can run:

- Isolate/un-isolate compute nodes;
- Brief unavailability of CubeMaster, Redis, MySQL, MinIO;
- DNS failure;
- Registry unreachable or CA expired;
- `/data/cubelet` space insufficient;
- `cube-node` Pod recreation;
- Node restart and Kubernetes upgrade;
- Control-plane upgrade and compute-plane version drift.

Note: when `cubeNode.hostNetwork=false`, recreating `cube-node` will replace the Pod Network Namespace, and existing sandbox networking may be interrupted. Do not delete this Pod casually while important sandboxes are running.

## 12. What This Exercise Has Proven and What It Has Not

| Verification Item | Status | Boundary of the Conclusion |
| --- | --- | --- |
| Helm installation and resource Ready | Passed | Only one single-node profile |
| Local LVM PVC | Passed | No cross-node high availability |
| Native KVM and BM Guest | Passed | PVM not tested |
| Basic Cilium coexistence | Passed | Only covers template and single-sandbox smoke, not full CNI certification |
| 8 official Helm test suites | Passed | Proves component and node runtime health |
| Template build | Passed | Single node, single official image |
| Sandbox Create / Exec / Destroy | Passed | Single concurrency, no performance conclusions |
| Coexistence with existing KubeVirt VMIs | Observed as passed | No resource pressure, upgrade, or fault injection |
| Pause / Resume / Snapshot | Not tested | Requires separate verification of state and compatibility |
| S3 persistent volumes | Not tested | MinIO health does not equal a complete business volume loop |
| Inbound domain and public TLS | Not tested | The experiment only used local port-forward |
| High concurrency and density | Not tested | Cannot cite the official 60ms figure as this cluster's SLO |
| Upgrade and disaster recovery | Not tested | Must be completed before production rollout |

## 13. Cleanup and Rollback

Before uninstalling, first confirm there are no sandboxes and no templates, Snapshots, or Volumes that still need to be retained:

```bash
kubectl exec -n cube-system deploy/cube-cubemastercli -- \
  sh -lc 'cubemastercli \
    --address "$CUBEMASTERCLI_ADDRESS" \
    --port "$CUBEMASTERCLI_PORT" \
    cubebox list'
```

Then uninstall the release:

```bash
helm uninstall cube -n cube-system
```

Remove node labels:

```bash
kubectl label node <node-name> \
  cube.tencent.com/cube-control- \
  cube.tencent.com/cube-node-
```

After uninstalling, manually check:

- Whether PVC/PV were deleted due to the StorageClass reclaim policy;
- Whether `/data/cubelet`, toolbox, logs, and loopback files are retained;
- Whether bpffs, mount points, and udev/fstab were modified;
- Whether NodePort, ClusterRole, and ClusterRoleBinding were cleaned up;
- Whether private Registry credentials and temporary CAs were revoked.

Do not recursively delete `/data/cubelet` directly. First confirm that no other release, template, Snapshot, or still-running runtime uses that path, then follow the official cleanup procedure.

## 14. Next Steps

If the goal is only to verify that Agent code can run in a MicroVM, the Create → Exec → Destroy loop in this article already completes the minimal closed loop.

If you are preparing for team trial use, the recommended next phase is to proceed in this order:

1. Build a dedicated compute node pool, adding taints and admission policies;
2. Prepare a dedicated XFS data disk for `/data/cubelet`;
3. Use a trusted HTTPS Registry, pinned Digests, and image signing;
4. Integrate formal authentication, production TLS, Wildcard DNS, and controlled ingress;
5. Decide on `cubeNode.hostNetwork` and complete the NetworkPolicy/Egress design;
6. Verify Pause/Resume, Snapshot, S3 Volume, and recovery;
7. Run concurrency, density, resource reclamation, and fault injection tests;
8. Only then define the startup latency and availability SLOs for this environment.

## References

- [CubeSandbox GitHub](https://github.com/TencentCloud/CubeSandbox)
- [CubeSandbox v0.7.0 Release](https://github.com/TencentCloud/CubeSandbox/releases/tag/v0.7.0)
- [Kubernetes Deployment Overview](https://cubesandbox.com/zh/guide/kubernetes/)
- [Kubernetes Installation](https://cubesandbox.com/zh/guide/kubernetes/install)
- [Kubernetes Architecture](https://cubesandbox.com/zh/guide/kubernetes/architecture)
- [v0.7.0 Chart Default Values](https://github.com/TencentCloud/CubeSandbox/blob/v0.7.0/deploy/kubernetes/chart/values.yaml)
- [Creating an OCI Image Template](https://cubesandbox.com/zh/guide/tutorials/template-from-image)
- [WebUI](https://cubesandbox.com/zh/guide/webui)
- [Network Policies](https://cubesandbox.com/zh/guide/network-policy)
- [Lifecycle](https://cubesandbox.com/zh/guide/lifecycle)
- [CLI Tools](https://cubesandbox.com/zh/guide/cli-tools)
