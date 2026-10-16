# K3s Upgrade and DRA Pre-check Report

> Target host: **192.168.1.200**; host log timestamps are in CST (UTC+8). This report records environment checks, version planning, multi-stage backups, minor-version-by-minor-version upgrades, fault handling, final verification, and the Kubernetes 1.36 DRA pre-check.

## 1. Final Conclusion

| Item | Final Status |
| --- | --- |
| Upgrade | Completed, upgraded in minor-version order |
| K3s | `v1.36.2+k3s1 (01b6f04a)` |
| Node | `master` / Ready |
| Container Runtime | `containerd 2.3.2-k3s2` |
| cgroup | v1 / systemd driver, compatibility configuration retained |
| API Health | `/readyz = ok` |
| Backup | 874M / multi-stage |
| Traefik | 3.7.4 / `192.168.1.200` |
| DRA API | `resource.k8s.io/v1` available, Driver not yet installed |
| Host Reboot | Not rebooted, only the K3s service was restarted |

K3s has been upgraded one minor version at a time in accordance with Kubernetes version skew requirements; the original custom systemd unit, proxy environment, and `--cluster-domain cat.dog` were all preserved. During the upgrade, only the K3s service was restarted; the operating system was not rebooted.

## 2. Pre-upgrade Environment

| Item | Check Result |
|----------|-------------------------------------------------------------------------|
| Host | `192.168.1.200`, SSH user `root` |
| Operating System | Anolis OS 8.9, x86_64 |
| Kernel | `5.10.134-17.3.an8.x86_64` |
| Resources | Approximately 30 GiB memory, approximately 882 GiB disk available |
| Topology | Single node: `master`, role control-plane / master |
| Initial K3s | `v1.32.5+k3s1`, node Ready |
| Data Store | SQLite: `/var/lib/rancher/k3s/server/db/state.db`; embedded etcd not enabled |
| cgroup | cgroup v1; `stat -fc %T /sys/fs/cgroup` returns `tmpfs` |
| Cluster Domain | `cat.dog` |

### Custom systemd Service

The service file was not overwritten by the install script; the original mounts and parameters remain unchanged. Core configuration is as follows:

    ExecStartPre=/bin/sleep 10s
    ExecStartPre=/usr/bin/bindfs -u 1000 -g 1000 \
      /mnt/k8s/docker/images/local-gitea/gitea/local /mnt/gitea
    ExecStart=/usr/local/bin/k3s server --cluster-domain cat.dog
    ExecStopPost=/bin/sh -c "umount /mnt/gitea || true"

The proxy environment is located at `/etc/systemd/system/k3s.service.env` and was preserved during the upgrade.

### Pre-upgrade Pod Baseline

-   Running: 44
-   A large number of historical terminal-state Pods existed (Completed, Error, ContainerStatusUnknown).
-   `default/blog-0` was already `ImagePullBackOff` before the upgrade.
-   4 non-Traefik ServiceLBs were Pending due to port 80 contention on the single-node host.

## 3. Version Planning and Preparation

After querying the K3s default stable channel, the target version is `v1.36.2+k3s1`. Since Kubernetes does not support skipping multiple minor versions in a direct upgrade, the following path was used:

    v1.32.5+k3s1
      → v1.32.13+k3s1
      → v1.33.13+k3s1
      → v1.34.9+k3s1
      → v1.35.6+k3s1
      → v1.36.2+k3s1

### Binaries and Checksums

The amd64 binaries for the five target versions were downloaded to the following cache directory and verified one by one against the official `sha256sum-amd64.txt` checksums:

    /var/tmp/k3s-upgrade/v1.32.13+k3s1/k3s
    /var/tmp/k3s-upgrade/v1.33.13+k3s1/k3s
    /var/tmp/k3s-upgrade/v1.34.9+k3s1/k3s
    /var/tmp/k3s-upgrade/v1.35.6+k3s1/k3s
    /var/tmp/k3s-upgrade/v1.36.2+k3s1/k3s

All checksum verifications passed. The download cache is approximately 378M.

### System Image Pre-pull

Based on the official `k3s-images.txt` for each version, the core images that would be added or changed after each upgrade were cached in advance:

-   `rancher/klipper-helm:v0.11.1-build20260615`
-   `rancher/klipper-lb:v0.4.17`
-   `rancher/local-path-provisioner:v0.0.36`
-   `rancher/mirrored-coredns-coredns:1.14.4`
-   `rancher/mirrored-library-busybox:1.37.0`
-   `rancher/mirrored-library-traefik:3.7.4`
-   `rancher/mirrored-metrics-server:v0.8.1`
-   `rancher/mirrored-pause:3.6`

During the pull, the proxy and public image registry intermittently returned 503/TLS timeout errors; the core image cache was completed through retries.

## 4. Backup Records

The initial backup and the backup before each cross-minor-version upgrade were saved to:

    /var/backups/k3s-upgrade-20260801-095231-v1.32.5+k3s1

The directory permissions are set to `0700`, with a final footprint of approximately **874M**. The backup contents include:

-   A consistent copy of the SQLite database directory taken after stopping K3s;
-   The server token (backup file only; its contents are not recorded in this report);
-   The old `/usr/local/bin/k3s` for each stage;
-   `/etc/rancher/k3s`, the systemd unit, and proxy environment configuration;
-   Pre-upgrade snapshots of node, Pod, and controller state;
-   The final effective cgroup v1 kubelet drop-in.

| Backup Directory | Corresponding Stage |
|------------------------------|----------------------|
| `db-v1.32.5+k3s1` | Initial database consistency copy |
| `pre-v1.33.13-from-v1.32.13` | Before upgrade to v1.33.13 |
| `pre-v1.34.9-from-v1.33.13` | Before upgrade to v1.34.9 |
| `pre-v1.35.6-from-v1.34.9` | Before upgrade to v1.35.6 |
| `pre-v1.36.2-from-v1.35.6` | Before upgrade to v1.36.2 |

## 5. Upgrade Execution Timeline

1.  **v1.32.5 → v1.32.13**
    Stopped the service, copied SQLite and the old binary, replaced K3s, started it, and verified Node Ready. containerd updated to 2.1.5.
2.  **v1.32.13 → v1.33.13**
    Upgrade succeeded; Node is Ready, containerd updated to 2.2.5-k3s1.33.
3.  **v1.33.13 → v1.34.9**
    Upgrade succeeded; Node is Ready, containerd updated to 2.2.5-k3s2. One Flannel VXLAN race condition was handled during the startup phase.
4.  **v1.34.9 → v1.35.6**
    Discovered that Kubernetes 1.35 rejects cgroup v1 by default; recovery was achieved by using a kubelet drop-in to set `failCgroupV1: false`.
5.  **Traefik v40 Upgrade Fix**
    Re-ran the interrupted CRD Helm Job; both the Traefik CRD and the main Chart were upgraded to revision 5, and the Traefik image became 3.7.4.
6.  **v1.35.6 → v1.36.2**
    Final version started; the network policy controller encountered a transient link enumeration error on first startup, and systemd automatically retried once before it stabilized.
7.  **Final Recovery**
    Restored Traefik ServiceLB priority; retried nginx image resolution; all 44 pre-upgrade Running Pods were restored.

## 6. cgroup v1 Compatibility Handling

Starting with Kubernetes 1.35, the kubelet defaults to setting `failCgroupV1=true`. The initially attempted K3s configuration was:

    kubelet-arg:
      - "fail-cgroupv1=false"

On v1.35.6, K3s had already started the kubelet using `--config-dir`, and the above CLI configuration did not make it into the final kubelet parameters, causing the kubelet to exit repeatedly. The key error in the logs was:

    Error: failed to validate kubelet configuration,
    error: kubelet is configured to not run on a host using cgroup v1.

A high-priority drop-in was then created following the K3s recommended approach:

    # /var/lib/rancher/k3s/agent/etc/kubelet.conf.d/99-cgroup-v1.conf
    apiVersion: kubelet.config.k8s.io/v1beta1
    kind: KubeletConfiguration
    failCgroupV1: false

`/etc/rancher/k3s/config.yaml` was changed to an explanatory comment to avoid retaining an invalid parameter:

    # Kubelet cgroup v1 compatibility is configured in:
    # /var/lib/rancher/k3s/agent/etc/kubelet.conf.d/99-cgroup-v1.conf

Finally verified via the kubelet `configz`:

    {"failCgroupV1":false,"cgroupDriver":"systemd"}

cgroup v1 currently runs, but Kubernetes has marked it as deprecated, and future versions may remove support entirely. Per user requirements, v1 continues to be used this time; no kernel boot parameters were modified and the host was not rebooted.

## 7. Issues Encountered During Upgrade and Their Handling

### 7.1 v1.34.9 Flannel VXLAN Startup Race

A null pointer occurred once during the first startup:

    panic: runtime error: invalid memory address or nil pointer dereference
    github.com/flannel-io/flannel/pkg/backend/vxlan.(*network).watchVXLANDevice

systemd automatically restarted, after which it remained stable; the restart count, Node Ready status, and the four core Deployments were observed before proceeding to the next stage.

### 7.2 bindfs Leftover Process Warning

    Found left-over process (bindfs) in control group while starting unit. Ignoring.

Confirmed that the `/mnt/gitea` mount is correct. This message comes from a cgroup leftover warning after bindfs daemonized; it is not the root cause of the v1.34 crash, so the custom unit was not modified.

### 7.3 v1.35 cgroup v1 Startup Loop

The root cause was that the CLI-form compatibility switch did not make it into the final kubelet configuration. After stopping the service, `99-cgroup-v1.conf` was written, and a restart restored operation; the Node version became `v1.35.6+k3s1`.

### 7.4 Traefik CRD Chart Interrupted

Multiple kubelet exits interrupted the Helm revision update, and the main Chart reported:

    UPGRADE FAILED: Required CRDs are missing.
    Please install the corresponding CRD chart before installing this chart.

After inspecting the Helm release, the CRD Job was confirmed to be an expired Job. The generated `helm-install-traefik-crd` Job was deleted, allowing the Helm Controller to recreate and execute it. Final result:

-   `traefik-crd` revision 5: deployed;
-   `traefik` revision 5: deployed;
-   HelmChart `Failed=False`;
-   Traefik image is `rancher/mirrored-library-traefik:3.7.4`.

### 7.5 Single-node ServiceLB Port Contention

Multiple LoadBalancer Services in the cluster all request port 80 on the host. To restore the pre-upgrade ingress behavior, the following DaemonSets auto-generated by K3s were deleted so that the Traefik ServiceLB would be scheduled with priority:

-   `svclb-dify-nginx-nodeport-*`
-   `svclb-envoy-aibrix-*`
-   `svclb-envoy-default-*`
-   `svclb-kube-prometheus-stack-grafana-*`

The K3s Controller subsequently recreates them; since port 80 is already occupied by Traefik, these 4 Pods remain Pending, consistent with pre-upgrade behavior.

### 7.6 v1.36 Network Policy Controller Transient Error

    failed to start networking: unable to initialize network policy controller:
    error getting node subnet: failed to get list of links:
    results may be incomplete or inconsistent

systemd retried once automatically. The second startup succeeded, and ultimately `NRestarts=1`, after which the service remained active/running.

### 7.7 Public Image Registry 503

After the upgrade and restart, some Pods configured with `imagePullPolicy: Always` briefly failed due to Docker Hub / Quay 503 responses. Core images had been cached in advance; an explicit pull was performed for the previously Running Volcano nginx Pod:

    k3s crictl pull docker.io/library/nginx:latest

After the pull succeeded, the Pod automatically returned to Running. The imagePullPolicy of the business Deployment was not modified.

## 8. Final Health Verification

Final check time: `2026-08-01T10:21:24+08:00`.

| Check Item             | Final Result                                                 |
|------------------------|--------------------------------------------------------------|
| K3s version            | `v1.36.2+k3s1 (01b6f04a)`                                      |
| systemd                | `ActiveState=active`, `SubState=running`             |
| API                    | `k3s kubectl get --raw=/readyz` returned `ok`     |
| Node                   | `master Ready`, Internal IP `192.168.1.200` |
| Container runtime      | `containerd://2.3.2-k3s2`                                      |
| cgroup                 | v1; kubelet `failCgroupV1=false`, driver is systemd       |
| CoreDNS                | 1/1 Ready                                                    |
| metrics-server         | 1/1 Ready                                                    |
| local-path-provisioner | 1/1 Ready                                                    |
| Traefik                | Deployment 1/1; ServiceLB 2/2; External IP `192.168.1.200` |
| Aggregated APIService  | No APIService with Available=False                           |
| Service externalIPs    | No Service using the deprecated `spec.externalIPs` found |
| Running Pod            | 44, identical to the pre-upgrade Running baseline            |

### Final Non-Terminal Abnormal Pods

-   `default/blog-0`: ImagePullBackOff; existed before the upgrade, not introduced by the upgrade.
-   4 non-Traefik ServiceLB Pods: Pending; single-node port 80 conflict, behavior identical to pre-upgrade.

The large number of Error, Completed, and ContainerStatusUnknown Pods are long-retained historical terminal Pods in the cluster; the running workload baseline has been restored.

## 9. DRA Feature Pre-check and Suggested Testing

A read-only pre-check was performed on the final v1.36.2 cluster, confirming that the following APIs are provided by `resource.k8s.io/v1`:

-   DeviceClass (cluster-scoped)
-   ResourceSlice (cluster-scoped)
-   ResourceClaim (namespaced)
-   ResourceClaimTemplate (namespaced)

All four resource types are currently empty, and there is no DRA driver socket in `/var/lib/kubelet/plugins_registry` either. This indicates that the control-plane DRA API is enabled, but no DRA driver has been installed yet.

### Heterogeneous GPU Management: Improvements over Node Labels / Taints

DRA directly helps when "the cluster contains a large number of GPUs with different models and capability tiers." It moves the scheduling basis from node-level labels down to specific devices: the DRA Driver publishes the attributes and capacity of each GPU, workloads declare the capabilities they need, and the scheduler selects both the specific device and the node that can access it.

The traditional approach typically requires maintaining labels on nodes and repeating nodeSelector, nodeAffinity, taint, and toleration in every workload:

    gpu.vendor: nvidia
    gpu.model: h100
    gpu.memory: 80g
    gpu.arch: hopper
    gpu.pool: training
    gpu.exclusive: "true"

This approach describes the entire node, not each individual card within the node. If the same node mixes H100, A100, or other devices, node labels struggle to accurately express each device's model, GPU memory, health status, and allocatable quantity.

A DRA Driver instead publishes device-level inventory through ResourceSlice, conceptually similar to:

    Node node-a
    ├── GPU-0: NVIDIA H100, 80GiB, Hopper, healthy
    ├── GPU-1: NVIDIA A100, 40GiB, Ampere, healthy
    └── GPU-2: NVIDIA T4,   16GiB, Turing, unhealthy

Pods use ResourceClaim to request "device capabilities" without needing to know the target node name. DeviceClass and ResourceClaim can use CEL to filter by driver, device attributes, and capacity. The specific attribute names are defined by the DRA Driver; the following expression is only a structural illustration:

    selectors:
      - cel:
          expression: >-
            device.capacity["driver.example.com"].memory
              .compareTo(quantity("80Gi")) >= 0

| Management Dimension | Node label / taint                 | DRA                                    |
|----------------------|------------------------------------|----------------------------------------|
| Object described     | Entire node                        | Each physical or logical device        |
| Model and GPU memory | Manually synced labels             | Driver publishes device attributes and capacity |
| Mixed GPUs on one node | Difficult to express             | Each GPU recorded independently        |
| Device selection     | nodeSelector / affinity            | DeviceClass + CEL selector             |
| Candidate device fallback | Requires complex affinity or custom scheduling logic | Can use prioritized list |
| Failure or reservation | Usually taints the entire node   | Supports device-level taint / toleration |
| Partitioning and sharing | Depends on vendor extensions    | Can model partitions and consumable capacity |
| Allocation lifecycle | Mainly reflected as extended resource counts | Claim, Prepare, Unprepare, and reclamation are observable |

### Recommended: Platform-Provided Capability-Level DeviceClasses

Businesses should preferably not bind directly to a specific model; instead, the platform team should provide stable capability tiers:

    gpu-inference-small
      → T4、A10、L4

    gpu-inference-large
      → L40S、A100、H100

    gpu-training-standard
      → A100 40G、A100 80G

    gpu-training-premium
      → H100、H200

    gpu-memory-80g
      → any compatible device with at least 80GiB of GPU memory

This way, when adding H200, B200, or other devices, the main changes are to DeviceClass and policy, without batch-modifying business YAML. The prioritized list in Kubernetes 1.36 is now stable and can express policies such as "prefer H100, fall back to A100 if unavailable."

### Node Labels and Taints That Should Still Be Retained

DRA does not replace all node labels. Availability zones, racks, CPU architecture, local data, network, storage topology, operating system, and node maintenance state should still use labels, affinity, or node taints. The recommended boundary is:

    Node label / taint
      → describe and manage nodes, machine rooms, and infrastructure topology

    DRA ResourceSlice / DeviceClass / ResourceClaim
      → describe, select, and manage specific GPUs

### Multi-Vendor and Driver Maturity Limitations

-   DRA cannot automatically make CUDA workloads run on AMD GPUs; the container image, runtime, and software stack still need to be compatible with the target vendor.
-   The usual approach is to first establish vendor-level base DeviceClasses for NVIDIA, AMD, etc., then establish training, inference, and GPU memory tiers within the same compatible stack.
-   The Kubernetes DRA core API is stable, but production capability depends on whether vendor drivers publish sufficient device attributes and support MIG, sharing, health checks, and non-disruptive upgrades.
-   The ComputeDomain of the current Kubernetes SIGs NVIDIA DRA Driver is officially supported, but the GPU allocation part is still marked experimental and disabled by default in Helm; the AMD ROCm DRA Driver provides a v1 API and Helm Chart, but the project is also relatively young.

References: [Kubernetes DRA Concepts](https://kubernetes.io/docs/concepts/scheduling-eviction/dynamic-resource-allocation/), [DeviceClass API](https://kubernetes.io/docs/reference/kubernetes-api/resource/device-class-v1/), [Kubernetes 1.36 DRA Updates](https://kubernetes.io/blog/2026/05/07/kubernetes-v1-36-dra-136-updates/), [NVIDIA DRA Driver](https://github.com/kubernetes-sigs/dra-driver-nvidia-gpu), [AMD ROCm DRA Driver](https://github.com/ROCm/k8s-gpu-dra-driver).

### Recommended Migration Order

1.  Inventory existing GPU models, GPU memory, MIG, driver versions, and existing label rules.
2.  First use the official mock driver to validate the ResourceClaim allocation and reclamation flow.
3.  Select a non-critical GPU node to trial-install the corresponding vendor's DRA Driver, confirming that the same physical device is not double-allocated by the old Device Plugin and DRA simultaneously.
4.  Establish platform-level capability DeviceClasses, e.g., `gpu-training-large`.
5.  Migrate one non-critical Job to test device filtering, candidate fallback, release, driver restart, and node drain.
6.  Once the driver is stable, gradually remove node labels used only to describe GPU model, GPU memory, and health status; retain node-level operational and topology labels.

### GPU-Free End-to-End Test Plan

It is recommended to use the Kubernetes official `dra-example-driver`, which simulates 9 GPUs and does not require real GPUs. Installation creates a test namespace and a small amount of cluster-scoped RBAC/DeviceClass:

    k3s kubectl create namespace dra-tutorial

    for file in \
      deviceclass \
      serviceaccount \
      clusterrole \
      clusterrolebinding \
      priorityclass \
      daemonset
    do
      k3s kubectl apply --server-side \
        -f "https://k8s.io/examples/dra/driver-install/${file}.yaml"
    done

    k3s kubectl -n dra-tutorial rollout status \
      daemonset/dra-example-driver-kubeletplugin --timeout=180s

    k3s kubectl get deviceclasses
    k3s kubectl get resourceslices

Create a Claim and the Pod that consumes it:

    k3s kubectl apply --server-side \
      -f https://k8s.io/examples/dra/driver-install/example/resourceclaim.yaml

    k3s kubectl apply --server-side \
      -f https://k8s.io/examples/dra/driver-install/example/pod.yaml

    k3s kubectl -n dra-tutorial wait \
      --for=condition=Ready pod/pod0 --timeout=180s

Success criteria:

1.  `kubectl get resourceslices` can see the simulated devices provided by `gpu.example.com`;
2.  `some-gpu` ResourceClaim status is `allocated,reserved`;
3.  Pod logs contain something like `GPU_DEVICE_0="gpu-0"`;
4.  Driver logs show `PrepareResourceClaims`;
5.  After deleting the Pod, the Claim returns to pending, and driver logs show `UnprepareResourceClaims`.

<!-- -->

    k3s kubectl -n dra-tutorial get resourceclaims
    k3s kubectl -n dra-tutorial logs pod0 -c ctr0 | \
      grep -E 'GPU_DEVICE_[0-9]+='
    k3s kubectl -n dra-tutorial logs \
      -l app.kubernetes.io/name=dra-example-driver

### Cleaning Up Test Resources

    k3s kubectl delete namespace dra-tutorial
    k3s kubectl delete \
      deviceclass/gpu.example.com \
      clusterrole/dra-example-driver-role \
      clusterrolebinding/dra-example-driver-role-binding \
      priorityclass/dra-driver-high-priority

This time only the DRA API and kubelet plugin directory pre-checks were performed; no example driver was actually installed, to avoid creating cluster-scoped RBAC resources without confirmation.

## 10. Key Command Records

The following are the main command patterns executed this time. Repeated per-version operations are recorded only once as a general flow; sensitive tokens were not output.

### Version and Node Checks

    k3s --version
    k3s kubectl get nodes -o wide
    k3s kubectl get pods -A -o wide
    systemctl show k3s -p ActiveState -p SubState -p NRestarts

### cgroup and Effective Kubelet Configuration

    stat -fc %T /sys/fs/cgroup
    k3s kubectl get --raw /api/v1/nodes/master/proxy/configz | \
      jq '.kubeletconfig | {failCgroupV1,cgroupDriver,featureGates}'

### General Per-Version Rolling Upgrade Flow

    # 1. Snapshot of running state
    k3s kubectl get nodes -o wide > "$pre/nodes-before.txt"
    k3s kubectl get pods -A -o wide > "$pre/pods-before.txt"

    # 2. Stop the service and copy the consistent SQLite database
    timeout 180 systemctl stop k3s
    cp -a /var/lib/rancher/k3s/server/db "$pre/db"
    cp -a /var/lib/rancher/k3s/server/token "$pre/server-token"
    cp -a /usr/local/bin/k3s "$pre/k3s-old-version"

    # 3. Atomically replace the binary and start
    install -m 0755 "$target" /usr/local/bin/k3s.next
    mv -f /usr/local/bin/k3s.next /usr/local/bin/k3s
    systemctl start k3s

    # 4. Verify version and Ready status
    k3s kubectl get node master -o wide
    k3s kubectl get --raw=/readyz

### Core Component Verification

    k3s kubectl -n kube-system get deploy \
      coredns metrics-server local-path-provisioner traefik
    k3s kubectl -n kube-system get svc traefik -o wide
    k3s kubectl -n kube-system get pod \
      -l svccontroller.k3s.cattle.io/svcname=traefik

### Traefik CRD Job Recovery

    k3s kubectl -n kube-system delete job \
      helm-install-traefik-crd --wait=true
    k3s kubectl -n kube-system get helmchart traefik traefik-crd

### Restoring Traefik ServiceLB Priority Scheduling

    for ds in $(k3s kubectl -n kube-system get ds -o name | \
      grep -E 'svclb-(dify-nginx|envoy-aibrix|envoy-default|kube-prometheus-stack-grafana)')
    do
      k3s kubectl -n kube-system delete "$ds" --wait=false
    done

### APIService, Pod Baseline, and externalIPs Checks

    k3s kubectl get apiservice -o json | jq -r '
      .items[] |
      select(any(.status.conditions[]?;
        .type=="Available" and .status!="True")) |
      .metadata.name'

    k3s kubectl get pods -A --no-headers | awk '
      {count[$4]++}
      END {for (status in count) print status, count[status]}'

    k3s kubectl get svc -A -o json | jq -r '
      .items[] |
      select((.spec.externalIPs // []) | length > 0) |
      [.metadata.namespace,.metadata.name,
       (.spec.externalIPs|join(","))] | @tsv'

### DRA Pre-checks

    k3s kubectl api-resources --api-group=resource.k8s.io -o wide
    k3s kubectl get deviceclasses
    k3s kubectl get resourceslices
    k3s kubectl get resourceclaims -A
    k3s kubectl get resourceclaimtemplates -A
    find /var/lib/kubelet/plugins_registry -maxdepth 1 -type s

## 11. Official References

-   [K3s Manual Upgrades](https://docs.k3s.io/upgrades/manual)
-   [K3s v1.36 Release Notes](https://docs.k3s.io/release-notes/v1.36.X)
-   [K3s Configuration Options / Kubelet Drop-ins](https://docs.k3s.io/installation/configuration)
-   [K3s Backup and Restore](https://docs.k3s.io/datastore/backup-restore)
-   [K3s Rollback](https://docs.k3s.io/upgrades/roll-back)
-   [Kubernetes Version Skew Policy](https://kubernetes.io/releases/version-skew-policy/)
-   [Kubelet Configuration and Drop-in Directory](https://kubernetes.io/docs/tasks/administer-cluster/kubelet-config-file/)
-   [Install Drivers and Allocate Devices with DRA](https://kubernetes.io/docs/tutorials/cluster-management/install-use-dra/)
-   [Kubernetes SIGs DRA Example Driver](https://github.com/kubernetes-sigs/dra-example-driver)
-   [Kubernetes v1.36 DRA Updates](https://kubernetes.io/blog/2026/05/07/kubernetes-v1-36-dra-136-updates/)

The report records the results actually executed and observed this time. For security reasons, SSH private keys, the K3s server token, and any image registry credentials were not recorded.
