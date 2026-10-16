# Kubernetes Launcher Testing

This pattern schedules a privileged Pod with Firecracker as its main process, suitable for hardware admission and lifecycle experiments on isolated nodes. It is not a CRI Runtime, nor is it a public sandbox service that can be safely exposed externally.

## 1. Prepare and Isolate the Node

Before enabling the node, first prevent normal workloads from being scheduled to it:

```bash
NODE_NAME=worker-firecracker

kubectl label node "${NODE_NAME}" \
  sandbox.aik8s.run/firecracker=true --overwrite
kubectl taint node "${NODE_NAME}" \
  sandbox.aik8s.run/firecracker=true:NoSchedule --overwrite
```

Confirm that the required system DaemonSets and CNI can tolerate this dedicated taint. The smoke test manifest uses `hostNetwork: true`, but still requires a healthy kubelet, containerd, and sandbox image.

If the node was cordoned during preparation, only uncordon after the dedicated taint is already in effect:

```bash
kubectl uncordon "${NODE_NAME}"
```

## 2. Prepare Immutable and Mutable Artifacts

Install Firecracker and the base image according to the [host deployment guide](deployment.md). Copy [`configs/kubernetes-smoke.json`](configs/kubernetes-smoke.json) and create a new writable rootfs:

```bash
sudo install -m 0644 configs/kubernetes-smoke.json \
  /opt/firecracker-lab/run/k8s-config.json
sudo cp --reflink=auto --sparse=always \
  /opt/firecracker-lab/artifacts/rootfs.ext4 \
  /opt/firecracker-lab/run/rootfs-k8s.ext4
```

If worker nodes cannot access public image registries, sync or pre-warm the Launcher image. The Firecracker binary itself is statically linked and mounted from the node's experiment directory.

## 3. Schedule the Launcher

Review [`manifests/firecracker-launcher.yaml`](manifests/firecracker-launcher.yaml), then apply:

```bash
kubectl apply -f manifests/firecracker-launcher.yaml
kubectl get pod firecracker-k8s-smoke -o wide
kubectl logs -f firecracker-k8s-smoke
```

A successful run should have all of the following evidence:

- The scheduler selected a node with `sandbox.aik8s.run/firecracker=true`;
- The Pod is Running with 0 restarts;
- Logs reach the Guest login prompt;
- `kubectl top pod --containers` includes the VMM in Pod resource statistics;
- The Firecracker PID on the host belongs to the `/kubepods...` CPU and memory cgroup.

Example host-side cgroup check:

```bash
FC_PID=$(pgrep -f '/lab/bin/firecracker' | head -1)
ps -o pid,ppid,user,%cpu,%mem,rss,vsz,etimes,cmd -p "${FC_PID}"
cat "/proc/${FC_PID}/cgroup"
```

## 4. Lifecycle and Rollback

Deleting the Pod must also terminate the VMM:

```bash
kubectl delete pod firecracker-k8s-smoke --wait=true
pgrep -a -f '/lab/bin/firecracker' || true
```

Restore the node according to its original policy. For offline experiment nodes:

```bash
kubectl cordon "${NODE_NAME}"
kubectl label node "${NODE_NAME}" sandbox.aik8s.run/firecracker-
```

Only delete the dedicated taint if it did not exist before the test:

```bash
kubectl taint node "${NODE_NAME}" \
  sandbox.aik8s.run/firecracker:NoSchedule-
```

Do not delete unrelated taints, and do not uncordon a node that was intentionally isolated before the test.

## 5. Why This Is Not a RuntimeClass

Kubernetes only sees a privileged Launcher container and is unaware of the internal microVM, Guest processes, Guest readiness, Guest IP allocation, disks, or snapshots. A controller could supplement these capabilities, but that would effectively be building a new microVM platform.

For ordinary `runtimeClassName` Pods, use a CRI-compatible runtime layer such as Kata Containers. Kata 4.1.0 provides the `kata-fc` RuntimeClass, and its official Helm defaults select the `devmapper` snapshotter for the Firecracker shim. This link was tested in the second phase of this experiment; see [Kata Firecracker RuntimeClass](kata-firecracker-runtimeclass.md) for storage configuration, runtime-rs compatibility fixes, evidence, and rollback procedures.

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

Before modifying nodes, refer to the current [Kata installation guide](https://github.com/kata-containers/kata-containers/blob/main/docs/installation.md) and render a pinned version of the Chart locally:

```bash
helm template kata-fc ./kata-deploy \
  --set shims.disableAll=true \
  --set shims.fc.enabled=true \
  --set runtimeClasses.createDefault=false
```

Rendering only the RuntimeClass does not install or verify the Runtime, snapshotter, CNI, kernel, or Guest image. You must exercise the full Pod lifecycle and restore the node using a validated rollback procedure.
