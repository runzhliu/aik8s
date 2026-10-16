# Kata + Firecracker RuntimeClass Testing

This guide converts an ordinary Kubernetes Pod into a Kata sandbox hosted by Firecracker. It reproduces an already-validated experimental
chain, while keeping node names, image registries, jump hosts, and cluster-specific CNI control information out of the document.

This procedure restarts containerd and creates a device-mapper Thin Pool. It may only be run on a cordoned dedicated Worker,
and must have a validated rollback path. The Loopback Thin Pool described below is for experimental environments only and must
not be used in production.

## 1. Tested Component Combination

| Component | Tested version or configuration |
| --- | --- |
| Kubernetes | 1.30.4 |
| containerd | 1.7.14 |
| Kata Containers | 4.1.0 static amd64 package, runtime-rs |
| Firecracker | 1.16.1 |
| Host | x86_64 bare metal, KVM, cgroup v1 |
| Rootfs snapshotter | containerd built-in devmapper plugin |

The official Kata `kata-static` archive contains the runtime-rs shim, Guest kernel, and Guest image, but does not contain
the Firecracker or jailer binaries. Therefore, a fixed and mutually matching set of versions must be installed separately
following the [host deployment guide](deployment.md).

## 2. Offline Download and Transfer

On a workstation with network access, run:

```bash
KATA_VERSION=4.1.0
KATA_ARCH=amd64
WORK_DIR=/tmp/kata-download

mkdir -p "${WORK_DIR}"
curl -fL --retry 10 --retry-all-errors --continue-at - \
  -o "${WORK_DIR}/kata-static-${KATA_VERSION}-${KATA_ARCH}.tar.zst" \
  "https://github.com/kata-containers/kata-containers/releases/download/${KATA_VERSION}/kata-static-${KATA_VERSION}-${KATA_ARCH}.tar.zst"
sha256sum "${WORK_DIR}/kata-static-${KATA_VERSION}-${KATA_ARCH}.tar.zst"
```

The hash values for this test archive are:

```text
3dc6b69c4acb787b967b04b64599a20d02a8beb1a8eaab3084110df9d0b08c96
```

This is only a transfer-integrity observation and does not replace publisher checksums or GitHub artifact attestations. Record the Digest
before and after transfer, and require an exact match.

Transfer the compressed file via an approved jump host, offline media, or a short-lived
hostPath Pod such as [`manifests/artifact-transfer.yaml`](manifests/artifact-transfer.yaml). Do not place credentials or internal image registry
configuration inside the archive.

## 3. Installing Kata Without Modifying containerd

Verify the transferred hash on the Worker, then run:

```bash
sudo mkdir -p /opt/kata-staging
zstd -dc kata-static-4.1.0-amd64.tar.zst | \
  sudo tar -xf - -C /opt/kata-staging
sudo mv /opt/kata-staging/opt/kata /opt/kata

sudo ln -s /opt/firecracker-lab/bin/firecracker /opt/kata/bin/firecracker
sudo ln -s /opt/firecracker-lab/bin/jailer /opt/kata/bin/jailer
sudo ln -s /opt/kata/runtime-rs/bin/containerd-shim-kata-v2 \
  /usr/local/bin/containerd-shim-kata-fc-v2
```

The runtime type `io.containerd.kata-fc.v2` is resolved in the containerd service `PATH` to `containerd-shim-kata-fc-v2`. The shim's
`ConfigPath` is used to select the Firecracker runtime-rs configuration.

## 4. Pinning the Release Firecracker Configuration

Copy an experiment-specific configuration; do not edit the package defaults directly:

```bash
KATA_CONFIG_DIR=/opt/kata/share/defaults/kata-containers/runtime-rs

sudo cp "${KATA_CONFIG_DIR}/configuration-rs-fc.toml" \
  "${KATA_CONFIG_DIR}/configuration-rs-fc-lab.toml"
sudo sed -i 's/^default_maxvcpus = 0$/default_maxvcpus = 2/' \
  "${KATA_CONFIG_DIR}/configuration-rs-fc-lab.toml"
sudo sed -i \
  's/^dial_timeout_ms = 45000$/dial_timeout_ms = 2000\nreconnect_timeout_ms = 60000/' \
  "${KATA_CONFIG_DIR}/configuration-rs-fc-lab.toml"
```

The following two changes are required for this experiment:

- `default_maxvcpus = 0` expands to all 56 host CPUs, causing Firecracker to refuse to create the VM.
  Setting it to `2` limits the experimental sandbox size.
- Kata 4.1.0 provides `dial_timeout_ms = 45000` but lacks a compatible
  `reconnect_timeout_ms`, so the Runtime refuses the configuration. `2000/60000` is a temporary
  workaround documented in upstream [Issue #13484](https://github.com/kata-containers/kata-containers/issues/13484).

Before carrying this temporary workaround into later versions, re-check the pinned release versions; remove it once the upstream
configuration fix is complete and validated.

## 5. Creating an Experiment-Only devmapper Pool

First confirm that the following names, files, and Loop devices do not exist. Never reuse disks of unknown origin or existing LVM
volume groups for this recipe.

```bash
DM_ROOT=/var/lib/containerd/devmapper-firecracker-lab
DM_POOL=fc-devpool

sudo modprobe dm_thin_pool
sudo mkdir -p "${DM_ROOT}"
sudo truncate -s 20G "${DM_ROOT}/data"
sudo truncate -s 2G "${DM_ROOT}/meta"

DATA_LOOP=$(sudo losetup --find --show "${DM_ROOT}/data")
META_LOOP=$(sudo losetup --find --show "${DM_ROOT}/meta")
DATA_SECTORS=$(sudo blockdev --getsz "${DATA_LOOP}")

sudo dmsetup create "${DM_POOL}" --table \
  "0 ${DATA_SECTORS} thin-pool ${META_LOOP} ${DATA_LOOP} 128 32768"
sudo dmsetup table "${DM_POOL}"
sudo dmsetup status "${DM_POOL}"
```

Sparse Loopback files simplify rollback, but their failure characteristics and performance are poor. Production environments should use
dedicated block devices, persistent activation, monitoring, capacity thresholds, and recovery procedures. See the official
[containerd devmapper snapshotter guide](https://github.com/containerd/containerd/blob/main/docs/snapshotters/devmapper.md).

### Keeping the Experimental Pool Usable Across Service and Host Restarts

After a host reboot, Loop devices are not restored automatically. Install the bundled lifecycle Unit and make containerd depend on it:

```bash
sudo install -m 0755 scripts/firecracker-devmapper-lab \
  /usr/local/sbin/firecracker-devmapper-lab
sudo install -m 0644 systemd/firecracker-devmapper-lab.service \
  /etc/systemd/system/firecracker-devmapper-lab.service
sudo install -d -m 0755 /etc/systemd/system/containerd.service.d
sudo install -m 0644 systemd/containerd-firecracker-devmapper.conf \
  /etc/systemd/system/containerd.service.d/20-firecracker-devmapper-lab.conf

sudo systemctl daemon-reload
sudo systemctl enable --now firecracker-devmapper-lab.service
```

This service preserves the existing data and metadata files, verifies their exact sizes, binds any available Loop device, and creates
`fc-devpool`. The containerd Drop-in configuration requires this service to succeed and starts containerd after it.

Before formally depending on this configuration, test the service dependency without any devmapper Pod running:

```bash
sudo systemctl stop containerd
sudo systemctl stop firecracker-devmapper-lab.service
sudo dmsetup ls --tree
sudo systemctl start containerd
sudo systemctl is-active containerd firecracker-devmapper-lab.service
sudo dmsetup status fc-devpool
```

When containerd starts, the Thin Pool must be reactivated automatically and the devmapper plugin must remain in the `ok` state. A real
host reboot test should be scheduled as a separate maintenance operation.

## 6. Merging the containerd Configuration

Back up the original file first, then merge the reference configuration from
[`configs/containerd-kata-fc.toml`](configs/containerd-kata-fc.toml).
If the resulting containerd configuration already contains an empty devmapper table, do not blindly append a second one.

The final effective configuration is:

```toml
[plugins."io.containerd.snapshotter.v1.devmapper"]
  async_remove = true
  base_image_size = "4GB"
  discard_blocks = true
  fs_type = "ext4"
  pool_name = "fc-devpool"
  root_path = "/var/lib/containerd/devmapper-firecracker-lab"

[plugins."io.containerd.grpc.v1.cri".containerd.runtimes.kata-fc]
  privileged_without_host_devices = true
  runtime_type = "io.containerd.kata-fc.v2"
  snapshotter = "devmapper"
  pod_annotations = ["io.katacontainers.*"]

  [plugins."io.containerd.grpc.v1.cri".containerd.runtimes.kata-fc.options]
    ConfigPath = "/opt/kata/share/defaults/kata-containers/runtime-rs/configuration-rs-fc-lab.toml"
```

Validate the configuration before restarting:

```bash
sudo containerd --config /etc/containerd/config.toml config dump >/dev/null
sudo systemctl restart containerd
sudo systemctl is-active containerd kubelet
sudo ctr plugins ls | grep devmapper
```

The devmapper line must report `ok`, and CRI must remain healthy.

## 7. Enabling Only the Dedicated Node

Before uncordoning the node, add the dedicated Label and Taint:

```bash
NODE_NAME=worker-firecracker

kubectl label node "${NODE_NAME}" \
  sandbox.aik8s.run/kata-fc=true --overwrite
kubectl taint node "${NODE_NAME}" \
  sandbox.aik8s.run/kata-fc=true:NoSchedule --overwrite
```

Confirm that the cluster CNI is running and Ready on that node. Offline clusters must also pre-warm or synchronize smoke-test images. Then uncordon
the node and apply the example:

```bash
kubectl uncordon "${NODE_NAME}"
kubectl apply -f manifests/kata-fc-runtimeclass.yaml
kubectl apply -n default -f manifests/kata-fc-smoke.yaml
kubectl wait -n default --for=condition=Ready \
  pod/kata-fc-smoke --timeout=180s
```

To keep an interactive sandbox, apply the Workbench instead:

```bash
kubectl apply -f manifests/kata-fc-workbench.yaml
kubectl wait -n firecracker-lab --for=condition=Ready \
  pod/kata-fc-workbench --timeout=180s
kubectl exec -n firecracker-lab -it kata-fc-workbench -- /bin/sh
```

At `/work`, the Workbench mounts `emptyDir`. It is deliberately configured as small-footprint and long-running; if the node cannot reach
public image registries, replace the images through your organization's normal image synchronization and supply-chain processes.

## 8. Verifying the microVM Boundary

Collect evidence from both the Guest and host sides:

```bash
kubectl get -n default pod kata-fc-smoke -o wide
kubectl logs -n default kata-fc-smoke
kubectl exec -n default kata-fc-smoke -- uname -r

uname -r
ps -eo pid,ppid,etimes,pcpu,pmem,rss,args | grep '[f]irecracker'
sudo dmsetup status fc-devpool
sudo ctr -n k8s.io snapshots --snapshotter devmapper ls
```

In the validated run, the Pod was Ready four seconds after creation, obtained a CNI address, and supported `kubectl exec`. The Guest
reported Linux `6.18.35`, while the host reported `5.10.134`. At sampling time, the standalone Firecracker process used approximately
129 MiB RSS, and the Pod rootfs had also appeared in devmapper.

Single-startup time and memory samples are smoke observations only and must not be treated as benchmark results. `kubectl top` only shows the Payload
container perspective, so capacity studies must additionally collect shim/VMM cgroup metrics.

The retained Workbench also passed the containerd online restart test: the Pod UID and Firecracker PID did not change,
the restart count remained 0, Guest Uptime continued to increase, and files written to `/work` remained readable.

### Agent Workload Compatibility Notes

Four Agent images were subsequently tested with the same RuntimeClass. All four Pods were Ready with a restart count of 0.
Two integration limitations were also found:

- The Kata TAP link under test could reach the Pod address but could not reach the cluster's regular Service VIP, so the
  CNI/Service routing must be fixed for the specific cluster before production use;
- Replacing certain application state directories with `emptyDir` triggered owner-mode (`fchmod`) failures; only mount validated
  paths, and test the image's owner-change behavior at startup.

These limitations do not affect the basic Workbench smoke test, but they do affect real applications. See [Agent workloads](agent-workloads.md)
and the already-redacted [`kata-fc-agents.yaml`](manifests/kata-fc-agents.yaml).

### Rebuilding an Intentionally Destroyed devmapper Pool

Do not delete the snapshotter root directory while containerd still records that images were unpacked by devmapper. If the experiment
reset intentionally destroys the entire Pool and snapshot metadata, residual `containerd.io/gc.ref.snapshot.devmapper`
content Labels may cause the next sandbox to report `snapshot does not exist`.

Only when `ctr ... snapshots ls` is empty and no devmapper Pod exists may these residual Labels be cleared;
then restart containerd and retry:

```bash
STALE_DIGESTS=$(sudo ctr -n k8s.io content ls 2>/dev/null | \
  awk '/snapshot.devmapper/ {print $1}')
for DIGEST in ${STALE_DIGESTS}; do
  sudo ctr -n k8s.io content label "${DIGEST}" \
    containerd.io/gc.ref.snapshot.devmapper=
done
sudo systemctl restart containerd
```

This is a Pool rebuild repair, not routine garbage collection. Clearing snapshot references that are still in use can corrupt active workloads.

## 9. Rollback

First delete the workloads and confirm the VMM has exited:

```bash
kubectl cordon "${NODE_NAME}"
kubectl delete -n default -f manifests/kata-fc-smoke.yaml --wait=true
kubectl delete -f manifests/kata-fc-workbench.yaml --wait=true
kubectl delete -f manifests/kata-fc-runtimeclass.yaml
pgrep -a firecracker || true
```

Stop containerd, restore the backed-up configuration, and delete only the Pool and Loop devices created by this experiment:

```bash
sudo systemctl stop containerd
sudo systemctl disable --now firecracker-devmapper-lab.service
sudo cp /etc/containerd/config.toml.pre-kata-fc \
  /etc/containerd/config.toml
sudo rm -rf /var/lib/containerd/devmapper-firecracker-lab
sudo rm -f /usr/local/bin/containerd-shim-kata-fc-v2
sudo rm -f /etc/systemd/system/containerd.service.d/20-firecracker-devmapper-lab.conf
sudo rm -f /etc/systemd/system/firecracker-devmapper-lab.service
sudo rm -f /usr/local/sbin/firecracker-devmapper-lab
sudo systemctl daemon-reload
sudo systemctl start containerd
```

Finally, remove the temporary node Label and Taint, then restore all original Labels, Taints, CNI
Selectors, and scheduling state exactly as recorded before the test. Check CRI, kubelet, `dmsetup ls`, Loop devices, running Pods, and
the containerd configuration hash.

The rollback chain has been validated once. The tested Worker was then re-enabled and retained as a reserved test node: the lifecycle service, Thin
Pool, Kata Handler, RuntimeClass, CNI, and long-running Workbench all remain behind the dedicated node Taint.
