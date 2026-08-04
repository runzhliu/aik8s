---
title: KubeVirt 单节点桌面实战：本地盘、CDI 与浏览器 noVNC
description: 在没有 Ceph 的 Kubernetes 集群中，把 KubeVirt VM 限制到单个节点，使用本地盘保存完整系统环境，并通过受限 noVNC 网关从浏览器访问桌面
status: lab
last_reviewed: 2026-08-04
---

# KubeVirt 单节点桌面实战：本地盘、CDI 与浏览器 noVNC

容器 Notebook 最难处理的并不是 Notebook 文件，而是用户会把 Conda、Python、编译器、IDE 插件、系统包和缓存写到任何目录。平台可以挂载 `/home` 或 `/workspace`，却很难约束每个人始终把所有状态写进 PVC。容器重建后，遗漏在镜像可写层里的环境仍会消失。

这次实战采用另一条路线：在 Kubernetes 中运行一台具有持久根盘的 KubeVirt VM。用户修改的是完整 guest 文件系统，停止 VM 后释放 CPU 和内存，再次启动仍可恢复原环境。实验没有共享存储，先用一个节点上的 Local LVM 验证完整链路；后续接入 Ceph RBD 时，可以保留上层 VM、CDI 和访问方式，只替换 StorageClass。

最终跑通了以下路径：

```text
办公网浏览器
  → 节点地址:6080
  → 带 Basic Auth 的 noVNC/WebSocket 代理
  → virtctl VNC 子资源
  → KubeVirt VMI
  → Tiny Core 图形桌面
  → 节点本地 LVM DataVolume
```

本文只使用公开项目地址和通用占位符，不依赖特定公司的地址、账号或密码。`<...>` 必须替换成自己的值，版本和镜像应固定到经过验证的 tag 或 digest。

## 1. 适用范围和边界

这个方案适合：

- 先在一个支持 KVM 的节点验证 KubeVirt，而不改动其他节点；
- 用户环境是“可长期修改的 Linux 工作站”，不仅是几个 Notebook 文件；
- 用户个人根盘不需要在多台机器之间共享；
- 当前没有 Ceph RBD，但节点已有 Local LVM、Local PV 或其他本地 CSI；
- 办公网能够直接访问节点地址，因此实验阶段不需要 NodePort。

它不等于生产高可用方案：

- 本地盘绑定节点，节点故障时 VM 不能自动在别处恢复；
- 本地卷通常不能支持 VM 热迁移；
- `Retain` 只降低误删风险，不等于备份；
- 浏览器直连节点端口适合受控办公网实验，生产入口仍应使用 HTTPS、统一认证和审计；
- Tiny Core 只是快速验证桌面和 VNC，不适合作为 Jupyter 或 code-server 的正式开发环境。

如果已有 Ceph RBD，生产设计参见[用 KubeVirt 与 Ceph RBD 构建持久 GPU Notebook](kubevirt-rbd-notebook.md)。

## 2. 实验组件

| 组件 | 作用 | 本次选择 |
| --- | --- | --- |
| KubeVirt | 在 Kubernetes 中管理 VM/VMI | Operator + KubeVirt CR |
| CDI | 导入镜像、克隆 PVC、创建空白 DataVolume | 即使没有 Ceph 也可以使用 |
| 本地 CSI | 为 VM 提供持久块设备或文件系统卷 | `WaitForFirstConsumer` 的 Local LVM StorageClass |
| Tiny Core ISO | 快速验证图形启动、键鼠和 VNC | 仅用于 smoke test |
| `virtctl` | Console、VNC 和 VM 生命周期客户端 | 版本与 KubeVirt 匹配 |
| noVNC + websockify | 把 VNC 转换为浏览器可访问的 WebSocket | 独立、最小权限代理 Pod |

KubeVirt 的 `containerDisk` 会随 Pod 生命周期变化，不适合保存需要长期修改的根文件系统。持久状态应写入 DataVolume/PVC。参考 [KubeVirt disks and volumes](https://kubevirt.io/user-guide/storage/disks_and_volumes/)。

## 3. 前置检查

### 3.1 节点虚拟化能力

只在候选节点执行以下只读检查：

```bash
# Intel 通常出现 vmx，AMD 通常出现 svm，结果应大于 0
grep -Ec '(vmx|svm)' /proc/cpuinfo

ls -l /dev/kvm /dev/vhost-net /dev/net/tun
lsmod | grep -E 'kvm|vhost'
```

还要确认：

- BIOS/UEFI 已开启 VT-x/VT-d 或 AMD-V/AMD-Vi；
- 节点不是禁止嵌套虚拟化的虚拟机，或者上层已经正确开放 nested virtualization；
- Kubernetes、containerd/CRI-O 与目标 KubeVirt 版本在支持范围内；
- CNI、DNS 和节点时间同步正常；
- Pod Security、SELinux 或 AppArmor 不会拦截 KubeVirt 所需权限。

安装前应查看 [KubeVirt releases](https://github.com/kubevirt/kubevirt/releases) 和对应版本的支持信息，不要把本文实验版本当成长期固定版本。

### 3.2 本地 StorageClass

```bash
kubectl --context <context> get storageclass
kubectl --context <context> get storageclass <local-storage-class> -o yaml
```

本地盘实验优先选择：

- `volumeBindingMode: WaitForFirstConsumer`，等 VM 调度决策后再创建卷；
- 回收策略为 `Retain`，避免删除 PVC 后立即回收底层数据；
- CSI 能通过 PV `nodeAffinity` 把卷固定到实际节点；
- 已有容量、磁盘健康和卷使用率监控。

`Immediate` 模式可能先把卷创建在另一个节点，随后 VM 因节点选择与卷亲和性冲突而一直 Pending。

## 4. 将虚拟机限制到一个节点

先给实验节点增加专用标签：

```bash
kubectl --context <context> label node <vm-node> \
  kubevirt.io/test-host=true --overwrite
```

安装 KubeVirt 后，在 KubeVirt CR 中配置两层限制：

```yaml
apiVersion: kubevirt.io/v1
kind: KubeVirt
metadata:
  name: kubevirt
  namespace: kubevirt
spec:
  workloads:
    nodePlacement:
      nodeSelector:
        kubevirt.io/test-host: "true"
  configuration:
    developerConfiguration:
      nodeSelectors:
        kubevirt.io/test-host: "true"
```

其中：

- `workloads.nodePlacement` 限制 `virt-handler` 等节点侧工作负载；
- `developerConfiguration.nodeSelectors` 为 VMI 增加默认节点选择；
- 每个实验 VM 仍建议显式写同一个 `nodeSelector`，让意图可以直接从资源清单中看到；
- `virt-api`、`virt-controller` 和 Operator 属于控制面，可以运行在其他合适节点，真正的 VMI/`virt-launcher` 仍被限制在实验节点。

验证时不要只看 VM 状态，还要看实际 Pod 所在节点：

```bash
kubectl --context <context> -n kubevirt get pods -o wide
kubectl --context <context> -n <vm-namespace> get pods -o wide
```

VM 和普通 Pod 可以同时运行在同一个节点。KubeVirt 的 VM 最终也是由 `virt-launcher` Pod 承载，仍参与 Kubernetes 调度和资源核算。生产上若担心相互争抢，应增加 ResourceQuota、PriorityClass、CPU Manager、Topology Manager、污点和专用节点池，而不是假设 VM 会天然隔离普通 Pod。

## 5. 安装 KubeVirt 与 CDI

固定经过兼容性验证的版本，不要在生产清单中使用浮动地址：

```bash
export KUBEVIRT_VERSION='<validated-version>'

kubectl --context <context> apply -f \
  "https://github.com/kubevirt/kubevirt/releases/download/${KUBEVIRT_VERSION}/kubevirt-operator.yaml"
kubectl --context <context> apply -f \
  "https://github.com/kubevirt/kubevirt/releases/download/${KUBEVIRT_VERSION}/kubevirt-cr.yaml"

kubectl --context <context> -n kubevirt wait kubevirt kubevirt \
  --for=condition=Available --timeout=10m
```

安装匹配的 CDI：

```bash
export CDI_VERSION='<validated-version>'

kubectl --context <context> apply -f \
  "https://github.com/kubevirt/containerized-data-importer/releases/download/${CDI_VERSION}/cdi-operator.yaml"
kubectl --context <context> apply -f \
  "https://github.com/kubevirt/containerized-data-importer/releases/download/${CDI_VERSION}/cdi-cr.yaml"

kubectl --context <context> -n cdi get pods
```

CDI 与后端存储解耦：它负责导入、上传、克隆或初始化 DataVolume，底层既可以是 Ceph RBD，也可以是本地 LVM。没有 Ceph 并不妨碍本实验创建空白持久盘。

## 6. 先用 CirrOS 验证 KVM 和 Console

桌面系统涉及存储、图形和 WebSocket，直接排障会把问题混在一起。先运行一个极小的 CirrOS VM，验证 KVM、调度和串口控制台：

```yaml
apiVersion: kubevirt.io/v1
kind: VirtualMachine
metadata:
  name: cirros-smoke
  namespace: kubevirt-lab
spec:
  runStrategy: Always
  template:
    metadata:
      labels:
        kubevirt.io/domain: cirros-smoke
    spec:
      nodeSelector:
        kubevirt.io/test-host: "true"
      domain:
        resources:
          requests:
            memory: 256Mi
        devices:
          disks:
            - name: root
              disk:
                bus: virtio
      volumes:
        - name: root
          containerDisk:
            image: quay.io/kubevirt/cirros-container-disk-demo:<matching-tag>
```

```bash
kubectl --context <context> create namespace kubevirt-lab
kubectl --context <context> apply -f cirros-smoke.yaml
kubectl --context <context> -n kubevirt-lab get vm,vmi,pod -o wide

virtctl --context <context> console -n kubevirt-lab cirros-smoke
```

退出 `virtctl console` 使用 **Ctrl+]**。这是控制字符：在英文输入法下按住 Control 再按 `]`，不是输入字符串 `Ctrl+]`。如果终端客户端仍无法退出，结束本地 `virtctl` 进程即可；这只断开控制台，不会关闭 VM。

## 7. 创建本地持久盘

下面创建一个 40 GiB 空白 DataVolume。8 GiB 足以验证 Tiny Core，但 Ubuntu、Conda、模型缓存和 IDE 插件很快会写满，正式工作站建议从 80–200 GiB 起步，并按团队数据量设置配额。

```yaml
apiVersion: cdi.kubevirt.io/v1beta1
kind: DataVolume
metadata:
  name: desktop-root
  namespace: kubevirt-lab
spec:
  source:
    blank: {}
  storage:
    storageClassName: <local-storage-class>
    accessModes:
      - ReadWriteOnce
    resources:
      requests:
        storage: 40Gi
    volumeMode: Filesystem
```

```bash
kubectl --context <context> apply -f desktop-root.yaml
kubectl --context <context> -n kubevirt-lab get dv,pvc
kubectl --context <context> get pv -o wide
```

DataVolume 在没有消费者时保持 `WaitForFirstConsumer` 是正常现象。创建带目标节点选择器的 VM 后，调度器才会触发卷创建。绑定后检查 PV 的 `nodeAffinity` 是否指向 `<vm-node>`。

## 8. 用 Tiny Core 验证桌面

从 [Tiny Core Linux 下载页](http://www.tinycorelinux.net/downloads.html)获取 ISO，并校验官网提供的散列。把 ISO 封装成 KubeVirt `containerDisk`：

```dockerfile
FROM scratch
ADD --chown=107:107 TinyCore-current.iso /disk/disk.img
```

```bash
docker build -t <registry>/lab/tinycore-container-disk:<tag> .
docker push <registry>/lab/tinycore-container-disk:<tag>
```

这里的 `<registry>` 是实验环境能够访问的 OCI Registry。生产中应固定镜像 digest、生成 SBOM 并完成漏洞扫描。

创建桌面 VM：

```yaml
apiVersion: kubevirt.io/v1
kind: VirtualMachine
metadata:
  name: tinycore-desktop
  namespace: kubevirt-lab
spec:
  runStrategy: Always
  template:
    metadata:
      labels:
        kubevirt.io/domain: tinycore-desktop
    spec:
      nodeSelector:
        kubevirt.io/test-host: "true"
      domain:
        cpu:
          cores: 1
        resources:
          requests:
            memory: 1Gi
        devices:
          inputs:
            - name: tablet
              type: tablet
              bus: usb
          disks:
            - name: root
              bootOrder: 1
              disk:
                bus: virtio
            - name: installer
              bootOrder: 2
              cdrom:
                bus: sata
      networks:
        - name: default
          pod: {}
      volumes:
        - name: root
          dataVolume:
            name: desktop-root
        - name: installer
          containerDisk:
            image: <registry>/lab/tinycore-container-disk:<tag>
```

第一次启动时，空白根盘没有操作系统，固件会继续从 ISO 启动。此时看到桌面只说明图形链路已经成功，**并不代表系统状态已经写入持久盘**。必须在 guest 内运行安装程序，把系统写到 `desktop-root`，随后移除 ISO 或调整启动顺序。若只运行 Live ISO，重启后操作系统层的修改仍会丢失。

## 9. 浏览器访问：最小权限 noVNC 代理

`virtctl vnc` 默认面向本地客户端。为了从浏览器访问，可以构建一个只包含匹配版本 `virtctl`、noVNC 和 websockify 的小型代理镜像：

```text
浏览器 /vnc.html
  → websockify :6080
  → virtctl vnc --proxy-only 127.0.0.1:5900
  → Kubernetes VMI VNC subresource
```

代理的启动逻辑应具备两个特征：

1. `virtctl vnc --proxy-only` 退出后循环重启，以便浏览器断线后能够再次连接；
2. 不要使用 `nc -z 127.0.0.1 5900` 探测 VNC 端口。

第二点非常关键。`virtctl` 的 proxy-only 模式一次只服务一个 VNC 连接，`nc -z` 本身就会消耗这次连接，导致真正的 noVNC 随后收到 `Connection refused`。健康检查应探测 websockify 的 6080 监听端口，而不是连接 5900。

代理 ServiceAccount 只需要当前命名空间内的 VMI 读取与 VNC 子资源权限：

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: tinycore-novnc
  namespace: kubevirt-lab
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: tinycore-novnc
  namespace: kubevirt-lab
rules:
  - apiGroups: ["kubevirt.io"]
    resources: ["virtualmachineinstances"]
    verbs: ["get"]
  - apiGroups: ["subresources.kubevirt.io"]
    resources: ["virtualmachineinstances/vnc"]
    verbs: ["get"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: tinycore-novnc
  namespace: kubevirt-lab
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: tinycore-novnc
subjects:
  - kind: ServiceAccount
    name: tinycore-novnc
    namespace: kubevirt-lab
```

不要在 YAML 或 Git 中保存实际密码。先生成随机密码，再创建 Secret：

```bash
NOVNC_PASSWORD="$(openssl rand -hex 16)"

kubectl --context <context> -n kubevirt-lab create secret generic tinycore-novnc-auth \
  --from-literal=username=vmuser \
  --from-literal=password="${NOVNC_PASSWORD}"

printf 'noVNC user: vmuser\nnoVNC password: %s\n' "${NOVNC_PASSWORD}"
```

代理 Deployment 的关键配置如下：

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: tinycore-novnc
  namespace: kubevirt-lab
spec:
  replicas: 1
  strategy:
    type: Recreate
  selector:
    matchLabels:
      app: tinycore-novnc
  template:
    metadata:
      labels:
        app: tinycore-novnc
    spec:
      serviceAccountName: tinycore-novnc
      hostNetwork: true
      dnsPolicy: ClusterFirstWithHostNet
      nodeSelector:
        kubevirt.io/test-host: "true"
      containers:
        - name: proxy
          image: <registry>/lab/kubevirt-novnc-proxy:<tag>
          env:
            - name: VM_NAMESPACE
              value: kubevirt-lab
            - name: VM_NAME
              value: tinycore-desktop
            - name: NOVNC_USERNAME
              valueFrom:
                secretKeyRef:
                  name: tinycore-novnc-auth
                  key: username
            - name: NOVNC_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: tinycore-novnc-auth
                  key: password
          ports:
            - name: http
              containerPort: 6080
              hostPort: 6080
          readinessProbe:
            tcpSocket:
              port: http
```

代理入口脚本的核心命令可以写成：

```bash
while true; do
  virtctl vnc --proxy-only --address=127.0.0.1 --port=5900 \
    --namespace="${VM_NAMESPACE}" "${VM_NAME}"
  sleep 1
done &

websockify --web=/usr/share/novnc \
  --web-auth --auth-plugin=BasicHTTPAuth \
  --auth-source="${NOVNC_USERNAME}:${NOVNC_PASSWORD}" \
  0.0.0.0:6080 127.0.0.1:5900
```

`hostNetwork` 使办公网可以直接访问：

```text
http://<vm-node-ip>:6080/vnc.html?autoconnect=1&resize=scale
```

这里不创建 NodePort。因为同一节点的固定 6080 端口不能同时被旧、新两个 Pod 占用，所以 Deployment 必须使用 `Recreate`；默认 `RollingUpdate` 可能让更新永久卡住。readiness 使用 TCP 探针，不能使用未携带凭据的 HTTP GET，否则 Basic Auth 返回 401，Pod 会一直显示未就绪。

Basic Auth 只适合受控网络 PoC，而且明文 HTTP 无法保护密码。生产环境至少要改成 HTTPS，并通过 Ingress/Gateway 接入 OIDC、短期授权、审计和网络策略。防火墙只应允许办公网 CIDR 访问该节点端口。

## 10. 怎样验证链路真的工作

### 10.1 VM、调度和存储

```bash
kubectl --context <context> -n kubevirt-lab get vm,vmi,pod -o wide
kubectl --context <context> -n kubevirt-lab get dv,pvc
kubectl --context <context> get pv <pv-name> -o yaml
```

验收点：

- VM 和 VMI 为 Running/Ready；
- `virt-launcher` 位于 `<vm-node>`；
- DataVolume 成功，PVC 为 Bound；
- PV `nodeAffinity` 与 VM 节点一致；
- VMI condition 中本地盘导致 `LiveMigratable=False` 是预期结果。

### 10.2 noVNC

```bash
kubectl --context <context> -n kubevirt-lab get deploy,pod -l app=tinycore-novnc -o wide
kubectl --context <context> -n kubevirt-lab logs deploy/tinycore-novnc

curl -u 'vmuser:<password>' -I 'http://<vm-node-ip>:6080/vnc.html'
```

页面请求应返回 200，浏览器 WebSocket 应完成 101 Switching Protocols。若 HTML 能加载但顶部显示“无法连接到服务器”，应检查代理日志和 5900 连接生命周期，而不是先怀疑 guest 密码。

## 11. 常见故障

| 现象 | 常见原因 | 处理 |
| --- | --- | --- |
| VMI 一直 Pending | 节点没有 KVM、标签不匹配、资源不足 | 检查 VMI Events、`virt-handler` 和节点设备 |
| DataVolume/PVC Pending | `WaitForFirstConsumer` 尚无 VM 消费者 | 创建 VM 后再观察；检查 StorageClass 和调度事件 |
| 卷与 VM 节点冲突 | StorageClass 使用 `Immediate` 或 PV 已绑定别处 | 使用 WFFC；重建实验卷时先确认数据处置 |
| 浏览器拒绝连接 6080 | 代理 Pod 未运行、hostPort 未监听或防火墙拦截 | 检查 Pod、节点监听和办公网 ACL |
| noVNC 页面显示无法连接 | `virtctl` 已退出，或健康检查占用了单连接 VNC 代理 | 移除对 5900 的 `nc -z`；循环重启 `virtctl` |
| 代理 Pod 一直未就绪 | HTTP readiness 被 Basic Auth 返回 401 | 改用 6080 TCP readiness |
| Deployment 更新卡住 | RollingUpdate 时新旧 Pod 争抢 hostPort | 使用 `strategy.type: Recreate` |
| Console 无法退出 | 没有发送正确控制字符 | 英文输入法按 Ctrl+]，或结束本地客户端进程 |
| VM 重启后修改丢失 | 仍从 Live ISO 启动，系统没有装进 DataVolume | 完成 guest 安装并从持久根盘启动 |

## 12. Jupyter Notebook 与 code-server 镜像怎么选

这里要先区分“容器应用镜像”和“VM 系统镜像”。

### 12.1 只运行容器 Notebook

| 场景 | 推荐起点 | 说明 |
| --- | --- | --- |
| 最小 JupyterLab | `quay.io/jupyter/base-notebook:<date-or-sha>` | 体积较小，适合从项目 Lockfile 构建派生镜像 |
| 常用 Python 数据科学 | `quay.io/jupyter/scipy-notebook:<date-or-sha>` | NumPy、pandas、SciPy 等常用栈，适合作为多数 CPU Notebook 默认值 |
| PyTorch + NVIDIA GPU | `quay.io/jupyter/pytorch-notebook:cuda12-<pinned-tag>` | 官方 Docker Stacks 的 CUDA 变体，使用前核对驱动与 CUDA 兼容性 |
| NVIDIA 优化 PyTorch | `nvcr.io/nvidia/pytorch:<pinned-release>-py3` | 适合重视 NVIDIA 优化库的 GPU 环境，镜像包含 JupyterLab，但启动和安全配置需要平台明确管理 |

Jupyter Docker Stacks 已只把新镜像发布到 Quay.io，JupyterLab 是默认前端，并建议为可复现性固定日期或 Git SHA tag。不要继续把 Docker Hub 的旧 `jupyter/*` 当作更新来源。参见 [Jupyter Docker Stacks](https://jupyter-docker-stacks.readthedocs.io/en/latest/)和[镜像选择说明](https://jupyter-docker-stacks.readthedocs.io/en/latest/using/selecting.html)。NVIDIA 镜像说明参见 [NGC PyTorch](https://catalog.ngc.nvidia.com/orgs/nvidia/containers/pytorch)。

### 12.2 只运行容器 code-server

使用官方镜像：

```text
codercom/code-server:<pinned-version>
```

官方镜像支持 amd64 和 arm64。至少持久化 `/home/coder/.local`、`/home/coder/.config` 和项目目录，并通过 HTTPS 反向代理暴露；code-server 依赖 WebSocket。参考 [code-server 安装文档](https://coder.com/docs/code-server/install)和[安全访问说明](https://coder.com/docs/code-server/guide)。

不要把 `ghcr.io/coder/coder` 与 `codercom/code-server` 混为一谈：前者是多用户开发环境平台 Coder 的控制服务，后者才是浏览器中的 VS Code 服务。

### 12.3 同时需要 Jupyter 和 code-server，而且环境必须完整保留

本文场景的默认选择不是把两个服务硬塞进一个应用容器，而是：

```text
Ubuntu 24.04 LTS QCOW cloud image（或经过 GPU 兼容验证的 Ubuntu 22.04 LTS）
  → CDI 导入并克隆为每用户独立根盘
  → cloud-init 创建用户、SSH key 和初始配置
  → 在 VM 内安装 Miniforge/Micromamba、JupyterLab、code-server
  → systemd 分别管理两个服务
  → 完整 / 根盘由 DataVolume 持久化
```

这样用户后来通过 `apt`、`pip`、Conda、VS Code 扩展或任意脚本写入 `/home`、`/opt`、`/usr/local`、`/var` 的内容都会随 VM 根盘保存。code-server 官方 FAQ 也建议多租户场景为每位用户提供 VM，并明确提到 Kubernetes 上可用 KubeVirt 获得 VM 式体验。参考 [code-server FAQ](https://coder.com/docs/code-server/FAQ)。

镜像选择建议：

- CPU 开发环境默认用 Ubuntu 24.04 LTS QCOW cloud image；从 [Ubuntu 公开镜像](https://cloud-images.ubuntu.com/releases/noble/release/)选择发布版、校验 SHA256，再由 CDI 导入 DataVolume，不要在生产中跟随不断变化的 daily/current 文件；
- GPU 直通环境由 guest NVIDIA 驱动、CUDA Toolkit、框架版本共同决定，Ubuntu 22.04/24.04 二选一，以实际兼容矩阵为准；
- 黄金镜像只预装稳定的系统依赖、QEMU Guest Agent、安全补丁和平台 Agent；频繁变化的 Python 项目依赖仍用 `environment.yml`、`requirements.lock`、`uv.lock` 或容器保存；
- 为 Jupyter 和 code-server 使用不同端口、独立 systemd unit 和统一身份入口，不要关闭 token/密码后直接暴露到网络；
- 为黄金镜像记录来源 URL、SHA256、构建脚本、SBOM 和发布日期，并按周期重建，不要人工维护一个永不升级的“宠物镜像”。

如果只是标准化教学或短期实验，容器镜像 + PVC 更轻、更快；如果核心问题正是用户会在任意目录安装环境，持久 VM 根盘才真正覆盖问题边界。

## 13. 从实验走向生产

| 实验做法 | 生产替换 |
| --- | --- |
| 单节点 Local LVM | Ceph RBD 等支持故障恢复的块存储 |
| Tiny Core Live ISO | 可审计、定期重建的 Ubuntu LTS 黄金镜像 |
| 节点地址 + hostNetwork:6080 | HTTPS Gateway/Ingress + OIDC + 每用户短期授权 |
| 一个静态 noVNC 账号 | 用户身份映射、细粒度授权、会话审计和凭据轮换 |
| 手工创建 VM | Workspace Portal/Operator 自动创建、停止、快照和回收 |
| `Retain` 本地 PV | CSI Snapshot、异地备份、恢复演练和生命周期策略 |
| CPU/内存尽力共享 | Quota、优先级、NUMA/CPU 拓扑和专用 GPU 节点池 |

还需要明确三类生命周期：

1. **停止 VM**：删除 VMI，释放计算资源，但保留 VM 和根盘；
2. **重置环境**：从黄金镜像重新克隆根盘，必须提供快照或二次确认；
3. **删除用户**：经过保留期后删除 PVC/PV 和备份，不能与停止操作共用按钮或权限。

## 14. 验收清单

- [ ] 候选节点存在可用的 `/dev/kvm`，且 `virt-handler` 只落在预期节点；
- [ ] CirrOS VMI Ready，串口 console 能连接和退出；
- [ ] Desktop VM、`virt-launcher`、本地 PV 的节点一致；
- [ ] Tiny Core 图形桌面可通过 noVNC 操作；
- [ ] noVNC 代理只有命名空间内 VNC 所需最小权限；
- [ ] 断开并重新连接浏览器时，`virtctl` 代理能够自动恢复；
- [ ] 健康检查没有占用 5900 的单连接代理；
- [ ] 停止并重启 VM 后，写入持久根盘的测试文件仍存在；
- [ ] 已记录本地盘不可迁移、节点故障不可用和 `Retain` 回收流程；
- [ ] 正式工作站改用 Ubuntu LTS 黄金镜像，并固定 Jupyter/code-server 版本；
- [ ] 生产入口具备 HTTPS、统一认证、授权、审计和网络访问控制。

这次实验最有价值的结论不是“浏览器里出现了桌面”，而是把状态边界验证清楚了：`containerDisk` 和 Live ISO 负责分发启动介质，DataVolume/PVC 才负责保存用户完整环境；本地盘能验证持久工作站体验，但不能假装具备共享存储的故障恢复能力。
