# Host deployment and native smoke test

This guide uses a connected workstation to download artifacts and then transfers
them to an isolated Linux node. Commands are intentionally independent of any
particular bastion, cluster name, registry, or repository.

## 1. Requirements

The host must be Linux on `x86_64` or `aarch64`, with KVM enabled and read/write
access to `/dev/kvm`. A network test also needs `/dev/net/tun`.

Run these checks on the host:

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

Expected results are `x86_64` or `aarch64`, an existing `/dev/kvm`, and `vmx`
or `svm`. Firecracker explicitly requires read/write access to `/dev/kvm`.

## 2. Download on a connected workstation

Pin a release instead of following an unversioned latest URL:

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

For a disposable smoke test, the Firecracker project publishes quickstart
artifacts:

```bash
curl -fL --retry 10 --retry-all-errors \
  -o "${WORK_DIR}/vmlinux.bin" \
  https://s3.amazonaws.com/spec.ccfc.min/img/quickstart_guide/x86_64/kernels/vmlinux.bin
curl -fL --retry 10 --retry-all-errors \
  -o "${WORK_DIR}/rootfs.ext4" \
  https://s3.amazonaws.com/spec.ccfc.min/img/quickstart_guide/x86_64/rootfs/bionic.rootfs.ext4

sha256sum "${WORK_DIR}/vmlinux.bin" "${WORK_DIR}/rootfs.ext4"
```

The quickstart guest is old and exists only to prove the VMM path. Build and
patch a maintained guest kernel and root filesystem before production use.

## 3. Transfer to an isolated node

Use the transport available in your environment. Standard `scp` through a
bastion is sufficient. If only the Kubernetes API can reach the node, use the
provided artifact-transfer Pod:

1. Replace `worker-firecracker` in
   [`manifests/artifact-transfer.yaml`](manifests/artifact-transfer.yaml).
2. Ensure the referenced small container image is already cached or mirrored.
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

The transfer Pod is privileged by placement and host-path access even though it
does not set `securityContext.privileged`. Delete it immediately after the copy.

## 4. Install into an isolated lab directory

On the node:

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

Keep the VMM, images, mutable disks, and results separate. Never boot the base
rootfs writable; make a copy for each test.

## 5. Native boot and API test

Copy [`configs/native-smoke.json`](configs/native-smoke.json) to
`/opt/firecracker-lab/run/smoke-config.json`, then run:

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

Successful output contains `state: Running`, followed by the guest login prompt.
Request a clean shutdown through the API:

```bash
curl -X PUT \
  --unix-socket /opt/firecracker-lab/run/firecracker.socket \
  -H 'Content-Type: application/json' \
  -d '{"action_type":"SendCtrlAltDel"}' \
  http://localhost/actions
```

HTTP 204 and VMM process exit indicate graceful shutdown.

## 6. TAP network test

Copy [`configs/network-smoke.json`](configs/network-smoke.json) into the lab run
directory. The example rootfs maps MAC `06:00:AC:10:00:02` to guest address
`172.16.0.2`.

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

This validates host-to-guest networking only. Outbound guest access additionally
requires an explicit forwarding/NAT or routed-network policy. Do not silently
change the host's global forwarding or firewall defaults for a smoke test.

After shutdown, remove only the interface created by this lab:

```bash
sudo ip link del fc-tap0
```

## 7. Production gap

The smoke command runs the VMM directly for observability. A production design
must invoke the matching-version `jailer`, use a dedicated unprivileged UID/GID,
protect jail inputs from unprivileged writes, restrict cgroups and resources,
and own network namespace plus disk cleanup. See the official
[production host setup](https://github.com/firecracker-microvm/firecracker/blob/main/docs/prod-host-setup.md).
