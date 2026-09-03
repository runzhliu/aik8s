# Kata + Firecracker RuntimeClass test

This guide turns an ordinary Kubernetes Pod into a Firecracker-backed Kata
sandbox. It reproduces the verified lab path while keeping node names,
registries, bastions, and cluster-specific CNI controls out of the document.

The procedure restarts containerd and creates a device-mapper thin pool. Run it
only on a dedicated, cordoned worker with a tested rollback path. The loopback
thin pool below is suitable for a lab, not production.

## 1. Tested component set

| Component | Tested value |
| --- | --- |
| Kubernetes | 1.30.4 |
| containerd | 1.7.14 |
| Kata Containers | 4.1.0 static amd64, runtime-rs |
| Firecracker | 1.16.1 |
| Host | x86_64 bare metal, KVM, cgroup v1 |
| Rootfs snapshotter | containerd built-in devmapper plugin |

Kata's official `kata-static` archive includes the runtime-rs shim, guest
kernel, and guest image. It does not include the Firecracker or jailer binaries,
so install a pinned matching pair separately as described in
[deployment.md](deployment.md).

## 2. Download and transfer offline

On a connected workstation:

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

The tested archive hash was:

```text
3dc6b69c4acb787b967b04b64599a20d02a8beb1a8eaab3084110df9d0b08c96
```

This is a transfer-integrity observation, not a substitute for verifying a
publisher checksum or GitHub artifact attestation. Record the digest before and
after transfer and require an exact match.

Transfer the compressed file through the approved bastion, an offline medium,
or a short-lived hostPath Pod like
[`manifests/artifact-transfer.yaml`](manifests/artifact-transfer.yaml). Do not
put credentials or internal registry configuration in the archive.

## 3. Install Kata without changing containerd

On the worker, after verifying the transferred hash:

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

The runtime type `io.containerd.kata-fc.v2` resolves to
`containerd-shim-kata-fc-v2` in containerd's service `PATH`. The shim's
`ConfigPath` selects the Firecracker runtime-rs configuration.

## 4. Bound the released Firecracker configuration

Make a lab-specific copy rather than editing the packaged default:

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

Both changes were required in this lab:

- `default_maxvcpus = 0` expanded to all 56 host CPUs and Firecracker rejected
  the resulting VM. A value of `2` bounds the experimental sandbox.
- Kata 4.1.0 shipped `dial_timeout_ms = 45000` without a compatible
  `reconnect_timeout_ms`. The runtime rejected the configuration. The
  `2000/60000` values are the workaround documented in upstream
  [issue #13484](https://github.com/kata-containers/kata-containers/issues/13484).

Re-check the pinned release before carrying this workaround forward; remove it
when the upstream configuration is fixed and verified.

## 5. Create a lab-only devmapper pool

First verify that the names, files, and loop devices below do not already exist.
Never reuse an unknown disk or an existing LVM volume group for this recipe.

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

Sparse loopback files simplify rollback but have poor failure and performance
characteristics. Production should use dedicated block devices, persistent
activation, monitoring, capacity thresholds, and recovery procedures. Follow
the official [containerd devmapper snapshotter guide](https://github.com/containerd/containerd/blob/main/docs/snapshotters/devmapper.md).

### Persist the lab pool across service and host restarts

Loop devices are not restored automatically after a host reboot. Install the
provided lifecycle unit and make containerd depend on it:

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

The service preserves existing data and metadata files, validates their exact
sizes, attaches whichever free loop devices are available, and creates
`fc-devpool`. The containerd drop-in requires that service and orders
containerd after it.

Before trusting the setup, test the dependency while no devmapper-backed Pod is
running:

```bash
sudo systemctl stop containerd
sudo systemctl stop firecracker-devmapper-lab.service
sudo dmsetup ls --tree
sudo systemctl start containerd
sudo systemctl is-active containerd firecracker-devmapper-lab.service
sudo dmsetup status fc-devpool
```

Starting containerd must automatically reactivate the thin pool and leave the
devmapper plugin in `ok` state. A real host-reboot test should be scheduled as a
separate maintenance operation.

## 6. Merge containerd configuration

Back up the exact file, then merge the reference settings from
[`configs/containerd-kata-fc.toml`](configs/containerd-kata-fc.toml). Do not
blindly append a second devmapper table if the generated containerd config
already contains an empty one.

The effective settings are:

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

Validate before restarting:

```bash
sudo containerd --config /etc/containerd/config.toml config dump >/dev/null
sudo systemctl restart containerd
sudo systemctl is-active containerd kubelet
sudo ctr plugins ls | grep devmapper
```

The devmapper row must report `ok`, and CRI must remain healthy.

## 7. Enable only the dedicated node

Give the node a dedicated label and taint before uncordoning it:

```bash
NODE_NAME=worker-firecracker

kubectl label node "${NODE_NAME}" \
  sandbox.aik8s.run/kata-fc=true --overwrite
kubectl taint node "${NODE_NAME}" \
  sandbox.aik8s.run/kata-fc=true:NoSchedule --overwrite
```

Ensure the cluster CNI is running and ready on the node. Offline clusters must
also preload or mirror the smoke image. Then uncordon and apply the examples:

```bash
kubectl uncordon "${NODE_NAME}"
kubectl apply -f manifests/kata-fc-runtimeclass.yaml
kubectl apply -n default -f manifests/kata-fc-smoke.yaml
kubectl wait -n default --for=condition=Ready \
  pod/kata-fc-smoke --timeout=180s
```

For an interactive sandbox that remains available, apply the workbench instead:

```bash
kubectl apply -f manifests/kata-fc-workbench.yaml
kubectl wait -n firecracker-lab --for=condition=Ready \
  pod/kata-fc-workbench --timeout=180s
kubectl exec -n firecracker-lab -it kata-fc-workbench -- /bin/sh
```

The workbench has an `emptyDir` mounted at `/work`. It is intentionally small
and long-running; replace the image through the organization's normal mirroring
and supply-chain process when the node has no public-registry access.

## 8. Verify the microVM boundary

Collect evidence from both sides:

```bash
kubectl get -n default pod kata-fc-smoke -o wide
kubectl logs -n default kata-fc-smoke
kubectl exec -n default kata-fc-smoke -- uname -r

uname -r
ps -eo pid,ppid,etimes,pcpu,pmem,rss,args | grep '[f]irecracker'
sudo dmsetup status fc-devpool
sudo ctr -n k8s.io snapshots --snapshotter devmapper ls
```

In the verified run, the Pod became Ready four seconds after creation, received
a CNI address, and supported `kubectl exec`. The guest reported Linux `6.18.35`
while the host reported `5.10.134`. A separate Firecracker process used about
129 MiB RSS at the observation point, and the Pod rootfs appeared in devmapper.

Treat one startup time and one memory sample as smoke observations, not a
benchmark. `kubectl top` showed only the payload container's view, so collect
shim/VMM cgroup metrics separately for capacity studies.

The retained workbench also survived a live containerd restart: its Pod UID and
Firecracker PID were unchanged, restart count stayed at zero, guest uptime kept
increasing, and a file written under `/work` remained readable.

### Agent workload compatibility notes

Four agent images were subsequently exercised through the same RuntimeClass.
All four Pods became Ready with zero restarts. Two integration limitations were
observed:

- the tested Kata TAP path could reach Pod addresses but not the cluster's
  normal Service VIP path, so CNI/service routing requires cluster-specific
  remediation before production use;
- replacing certain application state directories with `emptyDir` triggered an
  ownership-mode (`fchmod`) failure; mount only verified paths and test the
  image's startup ownership changes.

These limitations do not affect the base workbench smoke but they matter for
real applications. See [Agent workloads](agent-workloads.md) and the sanitized
[`kata-fc-agents.yaml`](manifests/kata-fc-agents.yaml).

### Recreating a deliberately destroyed devmapper pool

Do not delete the snapshotter root while containerd still records images as
unpacked by devmapper. If a lab reset deliberately destroys the complete pool
and snapshot metadata, stale `containerd.io/gc.ref.snapshot.devmapper` content
labels can cause `snapshot does not exist` on the next sandbox.

Only when `ctr ... snapshots ls` is empty and no devmapper-backed Pod exists,
clear those stale labels and restart containerd before retrying:

```bash
STALE_DIGESTS=$(sudo ctr -n k8s.io content ls 2>/dev/null | \
  awk '/snapshot.devmapper/ {print $1}')
for DIGEST in ${STALE_DIGESTS}; do
  sudo ctr -n k8s.io content label "${DIGEST}" \
    containerd.io/gc.ref.snapshot.devmapper=
done
sudo systemctl restart containerd
```

This is pool-recreation repair, not routine garbage collection. Clearing a
live snapshot reference can corrupt active workloads.

## 9. Roll back

Delete the workload first and confirm the VMM is gone:

```bash
kubectl cordon "${NODE_NAME}"
kubectl delete -n default -f manifests/kata-fc-smoke.yaml --wait=true
kubectl delete -f manifests/kata-fc-workbench.yaml --wait=true
kubectl delete -f manifests/kata-fc-runtimeclass.yaml
pgrep -a firecracker || true
```

Stop containerd, restore the backed-up config, and remove only the pool and loop
devices created by this lab:

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

Finally remove the temporary node label and taint, then restore every original
label, taint, CNI selector, and scheduling state exactly as recorded before the
test. Verify CRI, kubelet, `dmsetup ls`, loop devices, running Pods, and the
containerd configuration hash.

The rollback path was verified once. The evaluated worker was then re-enabled
as a retained test node: the lifecycle service, thin pool, Kata handler,
RuntimeClass, CNI, and long-running workbench remain active behind the dedicated
node taint.
