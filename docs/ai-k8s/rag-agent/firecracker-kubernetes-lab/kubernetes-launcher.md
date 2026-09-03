# Kubernetes Launcher 测试

此模式调度一个以 Firecracker 为主进程的特权 Pod，适合在隔离节点上进行硬件准入和生命周期
实验。它不是 CRI Runtime，也不是可安全对外提供的公共沙箱服务。

## 1. 准备并隔离节点

启用节点前，先禁止普通工作负载调度到该节点：

```bash
NODE_NAME=worker-firecracker

kubectl label node "${NODE_NAME}" \
  sandbox.aik8s.run/firecracker=true --overwrite
kubectl taint node "${NODE_NAME}" \
  sandbox.aik8s.run/firecracker=true:NoSchedule --overwrite
```

确认所需的系统 DaemonSet 和 CNI 能容忍该专用污点。冒烟测试清单使用 `hostNetwork: true`，
但仍需要健康的 kubelet、containerd 和沙箱镜像。

如果准备阶段对节点执行过 cordon，只能在专用污点已经生效后再 uncordon：

```bash
kubectl uncordon "${NODE_NAME}"
```

## 2. 准备不可变与可变制品

按照[宿主机部署指南](deployment.md)安装 Firecracker 和基础镜像。复制
[`configs/kubernetes-smoke.json`](configs/kubernetes-smoke.json)，并创建一份新的可写
rootfs：

```bash
sudo install -m 0644 configs/kubernetes-smoke.json \
  /opt/firecracker-lab/run/k8s-config.json
sudo cp --reflink=auto --sparse=always \
  /opt/firecracker-lab/artifacts/rootfs.ext4 \
  /opt/firecracker-lab/run/rootfs-k8s.ext4
```

Worker 节点无法访问公共镜像仓库时，应同步或预热 Launcher 镜像。Firecracker 二进制本身为
静态链接，并从节点实验目录挂载。

## 3. 调度 Launcher

审阅 [`manifests/firecracker-launcher.yaml`](manifests/firecracker-launcher.yaml)，
然后应用：

```bash
kubectl apply -f manifests/firecracker-launcher.yaml
kubectl get pod firecracker-k8s-smoke -o wide
kubectl logs -f firecracker-k8s-smoke
```

一次成功运行应同时具备以下证据：

- 调度器选中的节点带有 `sandbox.aik8s.run/firecracker=true`；
- Pod 处于 Running，重启次数为 0；
- 日志到达 Guest 登录提示；
- `kubectl top pod --containers` 将 VMM 纳入 Pod 资源统计；
- 宿主机上的 Firecracker PID 属于 `/kubepods...` CPU 和内存 cgroup。

宿主机侧 cgroup 检查示例：

```bash
FC_PID=$(pgrep -f '/lab/bin/firecracker' | head -1)
ps -o pid,ppid,user,%cpu,%mem,rss,vsz,etimes,cmd -p "${FC_PID}"
cat "/proc/${FC_PID}/cgroup"
```

## 4. 生命周期与回滚

删除 Pod 时也必须终止 VMM：

```bash
kubectl delete pod firecracker-k8s-smoke --wait=true
pgrep -a -f '/lab/bin/firecracker' || true
```

按节点原有策略恢复节点。对于离线实验节点：

```bash
kubectl cordon "${NODE_NAME}"
kubectl label node "${NODE_NAME}" sandbox.aik8s.run/firecracker-
```

只有该专用污点在测试前不存在时，才能将其删除：

```bash
kubectl taint node "${NODE_NAME}" \
  sandbox.aik8s.run/firecracker:NoSchedule-
```

不要删除无关污点，也不要 uncordon 一个在测试前就被有意隔离的节点。

## 5. 为什么这不是 RuntimeClass

Kubernetes 只能看到一个特权 Launcher 容器，并不了解内部 microVM、Guest 进程、Guest
就绪状态、Guest IP 分配、磁盘或快照。可以用控制器补充这些能力，但这实际上已经是在构建
一个新的 microVM 平台。

对于普通的 `runtimeClassName` Pod，应使用 Kata Containers 这类兼容 CRI 的运行层。
Kata 4.1.0 提供 `kata-fc` RuntimeClass，其官方 Helm 默认值会为 Firecracker shim 选择
`devmapper` snapshotter。本实验第二阶段已经测试该链路；存储配置、runtime-rs 兼容性修复、
证据和回滚方式参见 [Kata Firecracker RuntimeClass](kata-firecracker-runtimeclass.md)。

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

修改节点前，请参考当前的
[Kata 安装指南](https://github.com/kata-containers/kata-containers/blob/main/docs/installation.md)，
并在本地渲染固定版本的 Chart：

```bash
helm template kata-fc ./kata-deploy \
  --set shims.disableAll=true \
  --set shims.fc.enabled=true \
  --set runtimeClasses.createDefault=false
```

只渲染 RuntimeClass 并不能安装或验证 Runtime、snapshotter、CNI、内核或 Guest 镜像。
必须演练完整的 Pod 生命周期，并使用经过验证的回滚流程恢复节点。
