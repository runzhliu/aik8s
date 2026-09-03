# 宿主机部署与原生冒烟测试

本指南先在可联网工作站上下载制品，再将其传输到隔离的 Linux 节点。文中的命令特意不依赖
任何特定跳板机、集群名称、镜像仓库或代码仓库。

## 1. 环境要求

宿主机必须是运行在 `x86_64` 或 `aarch64` 上的 Linux，启用 KVM，并对 `/dev/kvm`
具有读写权限。网络测试还需要 `/dev/net/tun`。

在宿主机上执行以下检查：

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

预期结果包括 `x86_64` 或 `aarch64`、存在的 `/dev/kvm`，以及 `vmx` 或 `svm`。
Firecracker 明确要求对 `/dev/kvm` 具有读写权限。

## 2. 在可联网工作站下载

固定具体版本，不要跟随未带版本号的 latest URL：

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

Firecracker 项目提供了适合一次性冒烟测试的快速入门制品：

```bash
curl -fL --retry 10 --retry-all-errors \
  -o "${WORK_DIR}/vmlinux.bin" \
  https://s3.amazonaws.com/spec.ccfc.min/img/quickstart_guide/x86_64/kernels/vmlinux.bin
curl -fL --retry 10 --retry-all-errors \
  -o "${WORK_DIR}/rootfs.ext4" \
  https://s3.amazonaws.com/spec.ccfc.min/img/quickstart_guide/x86_64/rootfs/bionic.rootfs.ext4

sha256sum "${WORK_DIR}/vmlinux.bin" "${WORK_DIR}/rootfs.ext4"
```

快速入门 Guest 较旧，只用于证明 VMM 链路可用。生产使用前，应构建并持续修补受维护的
Guest 内核和根文件系统。

## 3. 传输到隔离节点

使用环境中可用的传输方式即可。通过跳板机执行标准 `scp` 就足够；如果只有 Kubernetes API
能够访问节点，可使用随附的制品传输 Pod：

1. 替换 [`manifests/artifact-transfer.yaml`](manifests/artifact-transfer.yaml)
   中的 `worker-firecracker`。
2. 确认引用的小型容器镜像已经缓存或同步到内网。
3. 应用清单，通过 Kubernetes API 流式传输文件。

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

虽然传输 Pod 没有设置 `securityContext.privileged`，但由于它的节点位置和 hostPath
访问能力，仍应按特权工作负载对待。复制完成后立即删除。

## 4. 安装到隔离的实验目录

在节点上执行：

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

将 VMM、镜像、可变磁盘和结果分开保存。绝不要以可写方式启动基础 rootfs；每次测试都应先
复制一份。

## 5. 原生启动与 API 测试

将 [`configs/native-smoke.json`](configs/native-smoke.json) 复制到
`/opt/firecracker-lab/run/smoke-config.json`，然后执行：

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

成功输出应包含 `state: Running`，随后出现 Guest 登录提示。通过 API 请求正常关机：

```bash
curl -X PUT \
  --unix-socket /opt/firecracker-lab/run/firecracker.socket \
  -H 'Content-Type: application/json' \
  -d '{"action_type":"SendCtrlAltDel"}' \
  http://localhost/actions
```

返回 HTTP 204 且 VMM 进程退出，表示已正常关机。

## 6. TAP 网络测试

将 [`configs/network-smoke.json`](configs/network-smoke.json) 复制到实验运行目录。
示例 rootfs 将 MAC `06:00:AC:10:00:02` 映射到 Guest 地址 `172.16.0.2`。

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

这只验证宿主机到 Guest 的网络。Guest 访问外部网络还需要显式配置转发/NAT 或路由网络策略。
不要为了冒烟测试而悄悄修改宿主机的全局转发或防火墙默认设置。

关机后，只删除本实验创建的接口：

```bash
sudo ip link del fc-tap0
```

## 7. 与生产环境的差距

为方便观测，冒烟测试命令直接运行 VMM。生产设计必须调用版本匹配的 `jailer`，使用专用的
非特权 UID/GID，防止非特权用户写入 jail 输入，限制 cgroup 与资源，并完整管理网络命名空间
和磁盘清理。参见官方
[生产宿主机配置指南](https://github.com/firecracker-microvm/firecracker/blob/main/docs/prod-host-setup.md)。
