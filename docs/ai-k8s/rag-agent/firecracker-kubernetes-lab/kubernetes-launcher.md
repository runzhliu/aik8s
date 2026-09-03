# Kubernetes launcher test

This pattern schedules a privileged Pod whose main process is Firecracker. It is
useful for hardware qualification and lifecycle experiments on an isolated
node. It is not a CRI runtime and is not a safe public sandbox service.

## 1. Prepare and isolate the node

Make ordinary workloads ineligible before enabling the node:

```bash
NODE_NAME=worker-firecracker

kubectl label node "${NODE_NAME}" \
  sandbox.aik8s.run/firecracker=true --overwrite
kubectl taint node "${NODE_NAME}" \
  sandbox.aik8s.run/firecracker=true:NoSchedule --overwrite
```

Confirm that required system DaemonSets and the CNI tolerate the dedicated
taint. The smoke manifest uses `hostNetwork: true`, but a healthy kubelet,
containerd, and sandbox image are still required.

If the node was cordoned during preparation, uncordon it only after the
dedicated taint is present:

```bash
kubectl uncordon "${NODE_NAME}"
```

## 2. Prepare immutable and mutable artifacts

Install Firecracker and the base images as described in
[deployment.md](deployment.md). Copy
[`configs/kubernetes-smoke.json`](configs/kubernetes-smoke.json) and create a
fresh writable rootfs:

```bash
sudo install -m 0644 configs/kubernetes-smoke.json \
  /opt/firecracker-lab/run/k8s-config.json
sudo cp --reflink=auto --sparse=always \
  /opt/firecracker-lab/artifacts/rootfs.ext4 \
  /opt/firecracker-lab/run/rootfs-k8s.ext4
```

Mirror or preload the launcher image when worker nodes cannot access a public
registry. The Firecracker binary itself is statically linked and is mounted
from the node lab directory.

## 3. Schedule the launcher

Review [`manifests/firecracker-launcher.yaml`](manifests/firecracker-launcher.yaml),
then apply it:

```bash
kubectl apply -f manifests/firecracker-launcher.yaml
kubectl get pod firecracker-k8s-smoke -o wide
kubectl logs -f firecracker-k8s-smoke
```

A successful run has all of the following evidence:

- the scheduler-selected node carries `sandbox.aik8s.run/firecracker=true`;
- the Pod is Running and has zero restarts;
- logs reach the guest login prompt;
- `kubectl top pod --containers` reports the VMM under Pod accounting;
- the host Firecracker PID belongs to a `/kubepods...` CPU and memory cgroup.

Example host-side cgroup check:

```bash
FC_PID=$(pgrep -f '/lab/bin/firecracker' | head -1)
ps -o pid,ppid,user,%cpu,%mem,rss,vsz,etimes,cmd -p "${FC_PID}"
cat "/proc/${FC_PID}/cgroup"
```

## 4. Lifecycle and rollback

Deleting the Pod must also terminate the VMM:

```bash
kubectl delete pod firecracker-k8s-smoke --wait=true
pgrep -a -f '/lab/bin/firecracker' || true
```

Restore the node according to its previous policy. For an offline lab node:

```bash
kubectl cordon "${NODE_NAME}"
kubectl label node "${NODE_NAME}" sandbox.aik8s.run/firecracker-
```

Remove the dedicated taint only if it did not exist before the test:

```bash
kubectl taint node "${NODE_NAME}" \
  sandbox.aik8s.run/firecracker:NoSchedule-
```

Do not remove unrelated taints or uncordon a node that was intentionally
isolated before the test.

## 5. Why this is not RuntimeClass

Kubernetes sees one privileged launcher container. It does not understand the
inner microVM, guest processes, guest readiness, guest IP allocation, disks, or
snapshots. A controller could add those capabilities, but that is effectively
the beginning of a new microVM platform.

For ordinary `runtimeClassName` Pods, use a CRI-compatible layer such as Kata
Containers. Kata 4.1.0 publishes a `kata-fc` RuntimeClass, and its official Helm
defaults select the `devmapper` snapshotter for the Firecracker shim. That path
was tested in the second phase of this lab; see
[kata-firecracker-runtimeclass.md](kata-firecracker-runtimeclass.md) for the
storage setup, runtime-rs compatibility fixes, evidence, and rollback.

```yaml
apiVersion: node.k8s.io/v1
kind: RuntimeClass
metadata:
  name: kata-fc
handler: kata-fc
overhead:
  podFixed:
    memory: 130Mi
    cpu: 250m
```

Refer to the current
[Kata installation guide](https://github.com/kata-containers/kata-containers/blob/main/docs/installation.md)
and render the pinned chart locally before changing a node:

```bash
helm template kata-fc ./kata-deploy \
  --set shims.disableAll=true \
  --set shims.fc.enabled=true \
  --set runtimeClasses.createDefault=false
```

Rendering a RuntimeClass alone does not install or validate the runtime,
snapshotter, CNI, kernel, or guest image. Exercise the complete Pod lifecycle
and restore the node from a tested rollback procedure.
