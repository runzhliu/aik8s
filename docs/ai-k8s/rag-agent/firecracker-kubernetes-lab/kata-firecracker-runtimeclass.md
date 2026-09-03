# Kata + Firecracker RuntimeClass 测试

本指南将普通 Kubernetes Pod 转换为由 Firecracker 承载的 Kata 沙箱。它复现已经验证的实验
链路，同时不在文档中出现节点名、镜像仓库、跳板机和集群特有的 CNI 控制信息。

此流程会重启 containerd 并创建 device-mapper Thin Pool。只能在已 cordon 的专用 Worker
上执行，而且必须具备经过验证的回滚路径。下文的 Loopback Thin Pool 只适合实验环境，不能
用于生产。

## 1. 已测试组件组合

| 组件 | 测试版本或配置 |
| --- | --- |
| Kubernetes | 1.30.4 |
| containerd | 1.7.14 |
| Kata Containers | 4.1.0 静态 amd64 包，runtime-rs |
| Firecracker | 1.16.1 |
| 宿主机 | x86_64 裸金属、KVM、cgroup v1 |
| Rootfs snapshotter | containerd 内置 devmapper 插件 |

Kata 官方 `kata-static` 归档包含 runtime-rs shim、Guest 内核和 Guest 镜像，但不包含
Firecracker 或 jailer 二进制。因此，需要按照[宿主机部署指南](deployment.md)单独安装一组
固定且相互匹配的版本。

## 2. 离线下载与传输

在可联网工作站上执行：

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

本次测试归档的哈希值为：

```text
3dc6b69c4acb787b967b04b64599a20d02a8beb1a8eaab3084110df9d0b08c96
```

这只是传输完整性观测，不能替代发布方校验和或 GitHub 制品证明。传输前后都应记录 Digest，
并要求完全一致。

通过经过批准的跳板机、离线介质，或类似
[`manifests/artifact-transfer.yaml`](manifests/artifact-transfer.yaml) 的短生命周期
hostPath Pod 传输压缩文件。不要把凭据或内网镜像仓库配置放进归档。

## 3. 在不修改 containerd 的前提下安装 Kata

在 Worker 上验证传输后的哈希值，再执行：

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

Runtime 类型 `io.containerd.kata-fc.v2` 会解析到 containerd 服务 `PATH` 中的
`containerd-shim-kata-fc-v2`。shim 的 `ConfigPath` 用于选择 Firecracker runtime-rs
配置。

## 4. 限定发布版 Firecracker 配置

复制一份实验专用配置，不要直接编辑软件包默认值：

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

本实验必须进行以下两处修改：

- `default_maxvcpus = 0` 会展开为宿主机全部 56 个 CPU，导致 Firecracker 拒绝创建 VM。
  设置为 `2` 可以限制实验沙箱规模。
- Kata 4.1.0 提供了 `dial_timeout_ms = 45000`，却没有兼容的
  `reconnect_timeout_ms`，Runtime 因此拒绝配置。`2000/60000` 是上游
  [Issue #13484](https://github.com/kata-containers/kata-containers/issues/13484)
  记录的临时解决方案。

在后续版本中沿用此临时方案前，应重新核对固定的发布版本；上游配置修复并完成验证后应移除它。

## 5. 创建仅供实验使用的 devmapper Pool

首先确认下列名称、文件和 Loop 设备均不存在。绝不要为此配方复用来源不明的磁盘或现有 LVM
卷组。

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

稀疏 Loopback 文件能简化回滚，但故障特性和性能都不理想。生产环境应使用专用块设备、持久化
激活、监控、容量阈值和恢复流程。参见官方
[containerd devmapper snapshotter 指南](https://github.com/containerd/containerd/blob/main/docs/snapshotters/devmapper.md)。

### 让实验 Pool 跨服务和宿主机重启保持可用

宿主机重启后，Loop 设备不会自动恢复。安装随附的生命周期 Unit，并让 containerd 依赖它：

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

该服务会保留现有数据和元数据文件、验证其精确大小、绑定任意可用的 Loop 设备，并创建
`fc-devpool`。containerd 的 Drop-in 配置要求该服务成功，并将 containerd 排在它之后启动。

正式依赖该配置前，应在没有 devmapper Pod 运行时测试服务依赖：

```bash
sudo systemctl stop containerd
sudo systemctl stop firecracker-devmapper-lab.service
sudo dmsetup ls --tree
sudo systemctl start containerd
sudo systemctl is-active containerd firecracker-devmapper-lab.service
sudo dmsetup status fc-devpool
```

启动 containerd 时必须自动重新激活 Thin Pool，并使 devmapper 插件保持 `ok` 状态。真实的
宿主机重启测试应作为独立维护操作安排。

## 6. 合并 containerd 配置

先备份原始文件，再合并
[`configs/containerd-kata-fc.toml`](configs/containerd-kata-fc.toml) 中的参考配置。
如果生成的 containerd 配置已经包含空的 devmapper 表，不要盲目追加第二份。

最终生效的配置如下：

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

重启前先验证配置：

```bash
sudo containerd --config /etc/containerd/config.toml config dump >/dev/null
sudo systemctl restart containerd
sudo systemctl is-active containerd kubelet
sudo ctr plugins ls | grep devmapper
```

devmapper 行必须报告 `ok`，同时 CRI 必须保持健康。

## 7. 只启用专用节点

uncordon 节点前，先添加专用 Label 和 Taint：

```bash
NODE_NAME=worker-firecracker

kubectl label node "${NODE_NAME}" \
  sandbox.aik8s.run/kata-fc=true --overwrite
kubectl taint node "${NODE_NAME}" \
  sandbox.aik8s.run/kata-fc=true:NoSchedule --overwrite
```

确认集群 CNI 已在该节点运行并 Ready。离线集群还必须预热或同步冒烟测试镜像。然后 uncordon
节点并应用示例：

```bash
kubectl uncordon "${NODE_NAME}"
kubectl apply -f manifests/kata-fc-runtimeclass.yaml
kubectl apply -n default -f manifests/kata-fc-smoke.yaml
kubectl wait -n default --for=condition=Ready \
  pod/kata-fc-smoke --timeout=180s
```

如需保留一个可交互沙箱，请改为应用 Workbench：

```bash
kubectl apply -f manifests/kata-fc-workbench.yaml
kubectl wait -n firecracker-lab --for=condition=Ready \
  pod/kata-fc-workbench --timeout=180s
kubectl exec -n firecracker-lab -it kata-fc-workbench -- /bin/sh
```

Workbench 在 `/work` 挂载 `emptyDir`。它被特意配置成小规格、长时间运行；节点无法访问
公共镜像仓库时，应通过组织的常规镜像同步和供应链流程替换镜像。

## 8. 验证 microVM 边界

从 Guest 和宿主机两侧收集证据：

```bash
kubectl get -n default pod kata-fc-smoke -o wide
kubectl logs -n default kata-fc-smoke
kubectl exec -n default kata-fc-smoke -- uname -r

uname -r
ps -eo pid,ppid,etimes,pcpu,pmem,rss,args | grep '[f]irecracker'
sudo dmsetup status fc-devpool
sudo ctr -n k8s.io snapshots --snapshotter devmapper ls
```

在已验证的运行中，Pod 创建四秒后 Ready，获得 CNI 地址，并支持 `kubectl exec`。Guest
报告 Linux `6.18.35`，宿主机则报告 `5.10.134`。采样时，独立 Firecracker 进程使用约
129 MiB RSS，Pod rootfs 也已出现在 devmapper 中。

单次启动时间和内存采样只能视为冒烟观测，不能作为基准结果。`kubectl top` 只展示 Payload
容器视角，因此容量研究还需单独采集 shim/VMM cgroup 指标。

保留的 Workbench 也通过了 containerd 在线重启测试：Pod UID 和 Firecracker PID 未变化，
重启次数仍为 0，Guest Uptime 持续增加，写入 `/work` 的文件仍可读取。

### Agent 工作负载兼容性说明

随后使用同一个 RuntimeClass 测试了四个 Agent 镜像。四个 Pod 均 Ready，重启次数为 0。
同时发现两项集成限制：

- 测试中的 Kata TAP 链路可以访问 Pod 地址，却无法访问集群常规 Service VIP，因此生产使用前
  必须针对具体集群修复 CNI/Service 路由；
- 用 `emptyDir` 替换某些应用状态目录时触发了属主模式（`fchmod`）失败；只应挂载经过验证的
  路径，并测试镜像启动时的属主变更行为。

这些限制不影响基础 Workbench 冒烟测试，但会影响真实应用。参见 [Agent 工作负载](agent-workloads.md)
和已经脱敏的 [`kata-fc-agents.yaml`](manifests/kata-fc-agents.yaml)。

### 重建被有意销毁的 devmapper Pool

当 containerd 仍记录镜像已由 devmapper 解包时，不要删除 snapshotter 根目录。如果实验
重置有意销毁整个 Pool 和快照元数据，残留的 `containerd.io/gc.ref.snapshot.devmapper`
内容 Label 可能导致下一个沙箱报错 `snapshot does not exist`。

只有在 `ctr ... snapshots ls` 为空且不存在 devmapper Pod 时，才能清除这些残留 Label，
重启 containerd 后再重试：

```bash
STALE_DIGESTS=$(sudo ctr -n k8s.io content ls 2>/dev/null | \
  awk '/snapshot.devmapper/ {print $1}')
for DIGEST in ${STALE_DIGESTS}; do
  sudo ctr -n k8s.io content label "${DIGEST}" \
    containerd.io/gc.ref.snapshot.devmapper=
done
sudo systemctl restart containerd
```

这是 Pool 重建修复，不是常规垃圾回收。清除仍在使用的快照引用可能损坏活跃工作负载。

## 9. 回滚

先删除工作负载并确认 VMM 已退出：

```bash
kubectl cordon "${NODE_NAME}"
kubectl delete -n default -f manifests/kata-fc-smoke.yaml --wait=true
kubectl delete -f manifests/kata-fc-workbench.yaml --wait=true
kubectl delete -f manifests/kata-fc-runtimeclass.yaml
pgrep -a firecracker || true
```

停止 containerd，恢复备份配置，并且只删除本实验创建的 Pool 和 Loop 设备：

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

最后删除临时节点 Label 和 Taint，再严格按照测试前的记录恢复全部原始 Label、Taint、CNI
Selector 和调度状态。检查 CRI、kubelet、`dmsetup ls`、Loop 设备、运行中的 Pod，以及
containerd 配置哈希。

回滚链路已验证一次。随后，被测 Worker 重新启用并作为保留测试节点：生命周期服务、Thin
Pool、Kata Handler、RuntimeClass、CNI 和长时间运行的 Workbench 均保留在专用节点 Taint
之后。
