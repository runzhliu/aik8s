# Host Deployment and Native Smoke Testing

This guide first downloads artifacts on a networked workstation, then transfers them to an isolated Linux node. The commands in this document deliberately do not depend on any specific jump host, cluster name, image registry, or code repository.

## 1. Environment Requirements

The host must be Linux running on `x86_64` or `aarch64`, with KVM enabled, and read/write access to `/dev/kvm`. Network testing also requires `/dev/net/tun`.

Run the following checks on the host:

```bash
uname -m
uname -r
getconf PAGESIZE
systemd-detect-virt || true
ls -l /dev/kvm /dev/net/tun
awk -F: '/^flags/ {
  if ($2 ~ /(^| )vmx( |$)/) print "virtualization=vmx"
  else if ($2 ~ /(^| )svm( |$)/) print "virtualization=svm"
  else print "virtualization=missing"
  exit
}' /proc/cpuinfo
```

Expected results include `x86_64` or `aarch64`, an existing `/dev/kvm`, and `vmx` or `svm`. Firecracker explicitly requires read/write access to `/dev/kvm`.

## 2. Download on a Networked Workstation

Pin a specific version; do not follow an unversioned latest URL:

```bash
FC_VERSION=v1.16.1
FC_ARCH=x86_64
WORK_DIR=/tmp/firecracker-download

mkdir -p "${WORK_DIR}"
curl -fL --retry 3 \
  -o "${WORK_DIR}/firecracker-${FC_VERSION}-${FC_ARCH}.tgz" \
  "https://github.com/firecracker-microvm/firecracker/releases/download/${FC_VERSION}/firecracker-${FC_VERSION}-${FC_ARCH}.tgz"
curl -fL --retry 3 \
  -o "${WORK_DIR}/firecracker-${FC_VERSION}-${FC_ARCH}.tgz.sha256.txt" \
  "https://github.com/firecracker-microvm/firecracker/releases/download/${FC_VERSION}/firecracker-${FC_VERSION}-${FC_ARCH}.tgz.sha256.txt"

cd "${WORK_DIR}"
sha256sum -c "firecracker-${FC_VERSION}-${FC_ARCH}.tgz.sha256.txt"
```

The Firecracker project provides quick-start artifacts suitable for one-off smoke testing:

```bash
curl -fL --retry 10 --retry-all-errors \
  -o "${WORK_DIR}/vmlinux.bin" \
  https://s3.amazonaws.com/spec.ccfc.min/img/quickstart_guide/x86_64/kernels/vmlinux.bin
curl -fL --retry 10 --retry-all-errors \
  -o "${WORK_DIR}/rootfs.ext4" \
  https://s3.amazonaws.com/spec.ccfc.min/img/quickstart_guide/x86_64/rootfs/bionic.rootfs.ext4

sha256sum "${WORK_DIR}/vmlinux.bin" "${WORK_DIR}/rootfs.ext4"
```

The quick-start guest is older and is only used to prove that the VMM path works. Before production use, build and continuously patch a maintained guest kernel and root filesystem.

## 3. Transfer to the Isolated Node

Use whatever transfer method is available in the environment. Standard `scp` through a jump host is sufficient; if only the Kubernetes API can reach the node, use the bundled artifact transfer Pod:

1. In [`manifests/artifact-transfer.yaml`](manifests/artifact-transfer.yaml), replace `worker-firecracker`.
2. Confirm that the referenced small container image is already cached or synced to the internal network.
3. Apply the manifest and stream the files through the Kubernetes API.

```bash
kubectl apply -f manifests/artifact-transfer.yaml
kubectl wait --for=condition=Ready \
  pod/firecracker-artifact-transfer -n kube-system --timeout=90s
kubectl exec -n kube-system firecracker-artifact-transfer -- \
  mkdir -p /host-lab/artifacts

kubectl cp "${WORK_DIR}/firecracker-${FC_VERSION}-${FC_ARCH}.tgz" \
  kube-system/firecracker-artifact-transfer:/host-lab/
kubectl cp "${WORK_DIR}/firecracker-${FC_VERSION}-${FC_ARCH}.tgz.sha256.txt" \
  kube-system/firecracker-artifact-transfer:/host-lab/
kubectl cp "${WORK_DIR}/vmlinux.bin" \
  kube-system/firecracker-artifact-transfer:/host-lab/artifacts/vmlinux.bin
kubectl cp "${WORK_DIR}/rootfs.ext4" \
  kube-system/firecracker-artifact-transfer:/host-lab/artifacts/rootfs.ext4

kubectl delete pod firecracker-artifact-transfer \
  -n kube-system --wait=true
```

Although the transfer Pod does not set `securityContext.privileged`, it should still be treated as a privileged workload because of its node placement and hostPath access. Delete it immediately after the copy completes.

## 4. Install to an Isolated Experiment Directory

Run on the node:

```bash
FC_VERSION=v1.16.1
FC_ARCH=x86_64
LAB_DIR=/opt/firecracker-lab

sudo mkdir -p "${LAB_DIR}/bin" "${LAB_DIR}/artifacts" \
  "${LAB_DIR}/run" "${LAB_DIR}/results"
cd "${LAB_DIR}"
sha256sum -c "firecracker-${FC_VERSION}-${FC_ARCH}.tgz.sha256.txt"
tar -xzf "firecracker-${FC_VERSION}-${FC_ARCH}.tgz"

sudo install -m 0755 \
  "release-${FC_VERSION}-${FC_ARCH}/firecracker-${FC_VERSION}-${FC_ARCH}" \
  "${LAB_DIR}/bin/firecracker"
sudo install -m 0755 \
  "release-${FC_VERSION}-${FC_ARCH}/jailer-${FC_VERSION}-${FC_ARCH}" \
  "${LAB_DIR}/bin/jailer"

"${LAB_DIR}/bin/firecracker" --version
"${LAB_DIR}/bin/jailer" --version
sudo e2fsck -fn "${LAB_DIR}/artifacts/rootfs.ext4"
```

Keep the VMM, images, mutable disks, and results in separate locations. Never start the base rootfs in writable mode; always make a copy for each test.

## 5. Native Boot and API Testing

Copy [`configs/native-smoke.json`](configs/native-smoke.json) to `/opt/firecracker-lab/run/smoke-config.json`, then run:

```bash
LAB_DIR=/opt/firecracker-lab

cd "${LAB_DIR}"
cp --reflink=auto --sparse=always \
  artifacts/rootfs.ext4 run/rootfs-smoke.ext4

bin/firecracker \
  --api-sock "${LAB_DIR}/run/firecracker.socket" \
  --config-file "${LAB_DIR}/run/smoke-config.json" \
  >"${LAB_DIR}/results/native-console.log" 2>&1 &

curl --unix-socket "${LAB_DIR}/run/firecracker.socket" \
  http://localhost/version
curl --unix-socket "${LAB_DIR}/run/firecracker.socket" \
  http://localhost/
tail -40 "${LAB_DIR}/results/native-console.log"
```

Successful output should include `state: Running`, followed by the guest login prompt. Request a graceful shutdown through the API:

```bash
curl -X PUT \
  --unix-socket /opt/firecracker-lab/run/firecracker.socket \
  -H 'Content-Type: application/json' \
  -d '{"action_type":"SendCtrlAltDel"}' \
  http://localhost/actions
```

An HTTP 204 response and the VMM process exiting indicate a graceful shutdown.

## 6. TAP Network Testing

Copy [`configs/network-smoke.json`](configs/network-smoke.json) to the experiment run directory. The example rootfs maps MAC `06:00:AC:10:00:02` to guest address `172.16.0.2`.

```bash
sudo ip tuntap add dev fc-tap0 mode tap
sudo ip addr add 172.16.0.1/30 dev fc-tap0
sudo ip link set dev fc-tap0 up

cp --reflink=auto --sparse=always \
  /opt/firecracker-lab/artifacts/rootfs.ext4 \
  /opt/firecracker-lab/run/rootfs-network.ext4

/opt/firecracker-lab/bin/firecracker \
  --api-sock /opt/firecracker-lab/run/firecracker-network.socket \
  --config-file /opt/firecracker-lab/run/network-config.json \
  >/opt/firecracker-lab/results/network-console.log 2>&1 &

ping -c 3 172.16.0.2
timeout 2 bash -c '</dev/tcp/172.16.0.2/22'
```

This only verifies host-to-guest networking. Guest access to external networks additionally requires explicit forwarding/NAT or routed network policy configuration. Do not silently modify the host's global forwarding or firewall defaults for the sake of a smoke test.

After shutdown, delete only the interfaces created by this experiment:

```bash
sudo ip link del fc-tap0
```

## 7. Gaps Compared to Production

For observability, the smoke test commands run the VMM directly. A production design must invoke the version-matched `jailer`, use dedicated non-privileged UID/GID, prevent non-privileged users from writing to the jail input, restrict cgroups and resources, and fully manage network namespaces and disk cleanup. See the official [production host configuration guide](https://github.com/firecracker-microvm/firecracker/blob/main/docs/prod-host-setup.md).
