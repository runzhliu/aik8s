---
title: CubeSandbox Kubernetes 实战：从节点预检到第一个 MicroVM 沙箱
description: 在已有 Kubernetes 集群中部署 CubeSandbox v0.7.0，完成 KVM、XFS、Helm、节点注册、模板构建与沙箱生命周期验收
status: lab
last_reviewed: 2026-08-29
---

# CubeSandbox Kubernetes 实战：从节点预检到第一个 MicroVM 沙箱

这篇文章记录一次真实的 CubeSandbox Kubernetes 部署：不只让 Pod 变成 `Running`，还要让计算节点成功注册、模板完成构建、KVM MicroVM 真正启动、命令能够执行，最后把测试沙箱销毁干净。

实验固定使用官方 [`v0.7.0`](https://github.com/TencentCloud/CubeSandbox/releases/tag/v0.7.0)。Kubernetes 交付在该版本仍标注 Preview，因此本文是可复现的 PoC 路径，不是直接复制到生产环境的标准答案。部署条件、宿主机权限、PVM 风险和生产阻塞项，参见[CubeSandbox Kubernetes 部署条件与生产评估](cubesandbox-kubernetes.md)。

先给出最终结果：

- Helm release 成功进入 `deployed`，控制面、三个 StatefulSet 和三组节点 DaemonSet 全部 Ready；
- 4 个 PVC 全部绑定，CubeMaster、MySQL、Redis、MinIO 数据均有持久卷；
- 官方 Chart 自带的 8 组 Helm tests 全部 `Succeeded`；
- 一个原生 KVM 计算节点注册为 `HEALTHY=true`、`HOST_STATUS=RUNNING`；
- 使用官方 `sandbox-code` 镜像构建出 `READY` 模板；
- 临时沙箱成功进入 `running`，在 Guest 中执行命令后正常销毁；
- 验收结束后沙箱数量回到 0，节点上原有的 KubeVirt 虚拟机继续运行。

本文所有地址、节点名、仓库和凭据都使用公开占位符。`<...>` 必须替换为自己的环境值。

## 1. 实验目标与边界

本次不是从一台空白服务器开始，而是在一个已有 Kubernetes 集群中选择一台原生支持 KVM 的测试节点，让它同时承载 CubeSandbox 控制面和计算面。

选择这条路径有三个目的：

1. 验证 CubeSandbox 能否与现有 Kubernetes、CNI、CSI 和 KubeVirt 工作负载共存；
2. 避免 PVM 换宿主机内核和重启，把变量收敛到 Chart、节点初始化、存储和网络；
3. 用最小资源跑通完整生命周期，再决定是否建设专用节点池。

实验环境采用以下匿名化规格：

| 项目 | 实验配置 | 说明 |
| --- | --- | --- |
| CubeSandbox | `v0.7.0` | Chart 与组件使用同一版本 |
| Kubernetes | `v1.30.x` | 高于官方 `v1.24+` 下限 |
| 节点架构 | `linux/amd64` | 原生 KVM，不使用 PVM |
| 节点内核 | Linux 5.10 | `/dev/kvm` 可用，KVM 模块已加载 |
| CPU / 内存 | 100+ 逻辑 CPU、250 GiB+ 内存 | 远高于功能验证下限 |
| CNI | Cilium 1.16.x | 本次 smoke test 通过，不等于完整兼容性认证 |
| 控制面存储 | Local LVM StorageClass | 仅适合单节点 PoC，不提供跨节点恢复 |
| `/data/cubelet` | XFS | CubeSandbox 模板与 CoW 数据目录 |
| 现有工作负载 | KubeVirt VMI | 部署前后都检查运行状态 |

这次没有做以下事情：

- 没有给共享测试节点添加 `NoSchedule` 污点；
- 没有添加 `cube.tencent.com/allow-pvm-bootstrap=true`；
- 没有安装 PVM 宿主机内核，没有修改 GRUB，也没有重启节点；
- 没有让 Chart 修改集群 CoreDNS；
- 没有把 WebUI、CubeAPI 或管理端点暴露到公网；
- 没有测试高并发、Pause/Resume、Snapshot、跨节点恢复和生产 SLO。

生产环境应该使用专用节点池，并给计算节点加污点。共享节点只是为了回答“能否跑通”，不是推荐架构。

## 2. 先理解安装会改动什么

CubeSandbox 不是只安装几个普通 Deployment。Chart 会同时交付控制面、入口和宿主机级节点运行时：

| 组件 | Kubernetes 形态 | 主要作用 |
| --- | --- | --- |
| CubeMaster、CubeAPI、CubeOps、WebUI | Deployment | 模板、调度、API、运维和管理页面 |
| MySQL、Redis、MinIO | StatefulSet | 元数据、缓存、模板与快照制品 |
| CubeProxy、Lifecycle Manager | Deployment + Service | 沙箱入站代理和生命周期协调 |
| `cube-node-installer` | DaemonSet | 安装 Cubelet、Shim、Guest、Kernel 等节点产物 |
| `cube-node-bootstrap` | privileged DaemonSet | 检查 KVM、XFS、bpffs、cgroup 和宿主目录 |
| `cube-node` | privileged Big Pod | 运行 Cubelet、CubeEgress 与节点侧沙箱运行时 |

节点组件默认需要 `privileged`、`hostPID`、`hostPath` 和 `/dev/kvm`。这相当于把一套虚拟化运行时接进宿主机，不应在没有隔离边界和供应链控制的情况下安装到通用多租户集群。

## 3. 节点预检：先证明宿主机符合条件

### 3.1 Kubernetes 与存储

先确认当前上下文、节点、StorageClass 和默认卷容量：

```bash
kubectl config current-context
kubectl version
kubectl get nodes -o wide
kubectl get storageclass
kubectl get pv
```

单节点 PoC 最容易忽略的是控制面 PVC 总量。`v0.7.0` Chart 的默认值是：

| PVC | 默认容量 |
| --- | ---: |
| CubeMaster | 20 GiB |
| MySQL | 20 GiB |
| Redis | 10 GiB |
| MinIO | 20 GiB |
| 合计 | 70 GiB |

实验节点的 Local LVM 可分配容量只有约 60 GiB。如果直接使用默认值，四个 PVC 不可能全部成功绑定。因此 PoC 把它们缩小为 5 + 10 + 2 + 10 GiB，共 27 GiB。

这只是功能验证规格。生产环境不应照抄 27 GiB，而要根据模板数量、数据库保留、快照后端、日志和恢复目标重新规划。

### 3.2 KVM、XFS、bpffs 和 cgroup

每台计算节点都要核对：

```bash
# KVM 设备
ls -l /dev/kvm

# CPU 虚拟化与 KVM 模块
grep -Eoc '(vmx|svm)' /proc/cpuinfo
lsmod | grep -E '^kvm'

# BPF 文件系统
findmnt /sys/fs/bpf

# Cubelet 数据目录
findmnt -T /data/cubelet
df -h /data/cubelet

# cgroup CPU controller
mount | grep cgroup
```

验收重点不是“命令有输出”，而是：

- `/dev/kvm` 能被打开，而不只是文件存在；
- `kvm_intel` 或 `kvm_amd` 已加载；
- `/data/cubelet` 最终落在 XFS；
- bpffs 已挂载；
- cgroup CPU controller 可用；
- 节点内存明显高于 Chart 的最低检查值；
- 宿主机路由没有占用准备分给 CubeSandbox 的 CIDR。

如果节点本身已经是 XFS，可以直接使用 `/data/cubelet`。如果根盘不是 XFS，PoC 可让 bootstrap 创建 loopback XFS；生产应使用独立数据盘。

### 3.3 网络 CIDR

Chart 默认的沙箱网络是 `172.16.0.0/18`。安装前至少比对：

```bash
# Pod CIDR
kubectl get nodes -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.podCIDR}{"\n"}{end}'

# Service CIDR 可从 apiserver 参数或集群配置中查询
kubectl -n kube-system get pods -l component=kube-apiserver -o yaml | grep service-cluster-ip-range

# 节点本地路由
ip -4 route
```

还要人工核对 VPC、对等网络、VPN 和 IDC 路由。Helm 的 Service CIDR 预检不能发现所有外部路由冲突。

本次实验中：

- Pod 网段属于 `10.0.0.0/8`；
- Service 网段为 `10.96.0.0/12`；
- 节点地址位于另一个 `10.0.0.0/8` 子网；
- `172.16.0.0/18` 与已知集群地址不重叠。

这只能证明集群内没有直接冲突，不能替代外部网络团队的路由核对。

### 3.4 镜像可达性

CubeSandbox 的控制面镜像、节点产物镜像和后续模板镜像都必须能被目标环境访问。离线或受限网络应先同步到节点可达的 Registry，并固定版本或 Digest。

本文不展开镜像搬运、重打 tag 和私有仓库操作；这些步骤高度依赖企业网络。安装前只需要确保两件事：

1. Kubernetes 节点能拉取 Chart 渲染出的所有镜像；
2. CubeMaster 的模板构建链也能访问模板镜像仓库，并信任它的 TLS CA。

第二点很容易漏掉：节点 containerd 能拉取私有镜像，不代表 CubeMaster 内部的 OCI 客户端自动继承相同 CA。后文会单独说明。

## 4. 固定版本并准备 values

### 4.1 获取与检查 Chart

```bash
git clone https://github.com/TencentCloud/CubeSandbox.git
cd CubeSandbox
git checkout v0.7.0

helm lint deploy/kubernetes/chart \
  -f deploy/kubernetes/chart/values-single-node.yaml \
  -f runtime-values.yaml
```

不要直接用 `master` 部署后再按某个 Release 的文档排障。Chart、镜像、Guest Kernel 和 CLI 应固定到同一个版本。

### 4.2 单节点 PoC 的关键 values

下面是这次实验使用的公开化版本。密码只放在发布时注入的私密 values 中，不要提交到 Git。

```yaml
cubeProxy:
  advertiseIP: "<node-ip>"
  domain: "sandbox.example.test"
  configureClusterDNS: false
  service:
    type: NodePort
    nodePorts:
      http: 30080
      https: 30443
      grpc: 30090
      admin: ""
  ingress:
    enabled: false
  tls:
    mode: selfSigned

persistence:
  storageClassName: <storage-class>

controlPlane:
  master:
    persistence:
      size: 5Gi

mysql:
  password: "<generated-password>"
  rootPassword: "<generated-root-password>"
  persistence:
    size: 10Gi

redis:
  password: "<generated-password>"
  persistence:
    size: 2Gi

minio:
  persistence:
    size: 10Gi

bootstrap:
  pvmHostKernel:
    enabled: false
  nodeInit:
    dataCubelet:
      loopback:
        enabled: true
        imagePath: /data/cubelet-xfs.img
        size: 25G

cubeNode:
  pvmGuestKernel:
    enabled: false
  hostNetwork: false
  network:
    cidr: "172.16.0.0/18"
    cidrSkipConflictCheck: false
```

几个关键选择：

- `pvmHostKernel.enabled=false`：禁止 Chart 安装 PVM 宿主机内核；
- `pvmGuestKernel.enabled=false`：使用普通 BM Guest Kernel；
- `configureClusterDNS=false`：不修改集群 CoreDNS；
- `hostNetwork=false`：保留默认 Pod 网络，适合 PoC；
- `cidrSkipConflictCheck=false`：保留网络冲突保护；
- 4 个 PVC 合计 27 GiB：适配本次有限的 Local LVM 空间；
- `selfSigned` + NodePort：只用于受控测试网络。

`cubeProxy.service.type=NodePort` 有一个容易误判的细节：即使 `admin` 的 nodePort 留空，Kubernetes 仍会为 Service 中的 admin 端口自动分配一个 NodePort。Token 认证不能代替防火墙，生产环境不要直接对不可信网络开放这个 Service。

### 4.3 为什么要同时关闭两个 PVM 开关

只设置 `cubeNode.pvmGuestKernel.enabled=false` 不够稳妥。Chart 还有独立的宿主机 PVM 安装路径：

```yaml
bootstrap:
  pvmHostKernel:
    enabled: false
cubeNode:
  pvmGuestKernel:
    enabled: false
```

同时不要给原生 KVM 节点添加：

```text
cube.tencent.com/allow-pvm-bootstrap=true
```

正式安装前，检查最终渲染结果：

```bash
helm template cube deploy/kubernetes/chart \
  --namespace cube-system \
  -f deploy/kubernetes/chart/values-single-node.yaml \
  -f runtime-values.yaml \
  | grep -E 'PVM_FEATURE_ENABLED|CUBE_PVM_ENABLE|cube-node-pvm'
```

预期节点初始化中的 PVM 值为 `0`，且不生成 `cube-node-pvm` DaemonSet。

## 5. 安装：先 dry-run，再写入集群

### 5.1 标记节点

单节点 profile 要求同一台机器带控制面与计算面标签：

```bash
kubectl label node <node-name> \
  cube.tencent.com/cube-control=true \
  cube.tencent.com/cube-node=true \
  --overwrite
```

共享 PoC 节点没有添加污点，以免驱逐或阻塞已有业务。生产专用计算节点应添加 `NoSchedule` 污点，并确认 Chart toleration 与平台策略一致。

### 5.2 服务端 dry-run

本地 `helm lint` 和 `helm template` 只能验证模板。支持 server dry-run 的 Helm 版本可以继续执行：

```bash
helm upgrade --install cube deploy/kubernetes/chart \
  --namespace cube-system \
  --create-namespace \
  -f deploy/kubernetes/chart/values-single-node.yaml \
  -f runtime-values.yaml \
  --dry-run=server \
  --hide-secret >/dev/null
```

这一步可以提前发现 API 版本、准入策略、CRD 和部分集群端约束问题，同时避免把 Secret 输出到终端。

### 5.3 正式安装

```bash
helm upgrade --install cube deploy/kubernetes/chart \
  --namespace cube-system \
  --create-namespace \
  -f deploy/kubernetes/chart/values-single-node.yaml \
  -f runtime-values.yaml \
  --wait \
  --wait-for-jobs \
  --timeout 90m
```

安装过程中另开终端观察：

```bash
kubectl get pods,pvc,jobs -n cube-system -o wide -w
```

正常情况下会依次看到：

1. MySQL、Redis、MinIO 和 PVC 就绪；
2. CubeMaster、CubeOps、CubeAPI、WebUI、CubeProxy 启动；
3. `cube-node-installer` 安装节点运行时产物；
4. `cube-node-bootstrap` 检查 KVM、XFS、bpffs、CIDR 和 CubeMaster 连通性；
5. `cube-node` Big Pod 启动并向 CubeOps 注册。

## 6. 一次真实的启动竞态：什么时候等，什么时候查

这次安装在前一分钟出现过以下现象：

- CubeMaster 首次启动时解析不到 MySQL Service；
- CubeOps 和 Lifecycle Manager 因 CubeMaster 尚未 Ready 而重启；
- `cube-node-bootstrap` 已通过 KVM、XFS、bpffs 和 CIDR 检查，但最后连不上 CubeMaster；
- `cube-node` 因等待 node prep 而停在 Init 阶段。

随后 MySQL 和 Service DNS 就绪，CubeMaster 在下一轮重试中启动成功，bootstrap 重新执行后通过，所有组件进入 Ready。

这类现象可以短暂观察，但不能只用“再等等”处理。建议按以下顺序确认：

```bash
kubectl get pods,svc,endpoints,pvc -n cube-system -o wide

kubectl logs -n cube-system \
  -l app.kubernetes.io/component=cube-node-bootstrap \
  -c cube-node-init --tail=200

kubectl logs -n cube-system deploy/cube-master \
  -c cube-master --tail=200

kubectl get events -n cube-system --sort-by=.lastTimestamp | tail -50
```

判断标准：

- 如果依赖 Service 和 Endpoint 已出现，重试次数停止增长，所有 Pod 最终 Ready，可以归类为启动时序；
- 如果持续出现 DNS `NXDOMAIN`、PVC Pending、KVM/XFS 检查失败或 ImagePullBackOff，就必须修复根因；
- 不要为了让 bootstrap 变绿而关闭 CIDR、KVM、XFS 或内存检查。

排障日志可能包含数据库 URL、密码或管理 Token。公开文章和工单中应先脱敏，生产环境出现泄漏后要轮换凭据。

## 7. 验收：Pod Ready 之后还要做四层检查

### 7.1 Kubernetes 资源

```bash
helm status cube -n cube-system
kubectl get deploy,statefulset,daemonset -n cube-system
kubectl get pvc -n cube-system
```

本次结果：

| 资源 | 结果 |
| --- | ---: |
| Deployment | 7/7 Ready |
| StatefulSet | 3/3 Ready |
| DaemonSet | 3/3 Ready |
| PVC | 4/4 Bound |

### 7.2 节点注册

```bash
kubectl exec -n cube-system deploy/cube-cubemastercli -- \
  sh -lc 'cubeopscli \
    --address "$CUBEOPSCLI_ADDRESS" \
    --port "$CUBEOPSCLI_PORT" \
    node list'
```

至少确认：

- `HEALTHY=true`；
- `HOST_STATUS=RUNNING`；
- `SCHEDULING_DISABLED=false`；
- 组件版本都与目标 Release 一致；
- Kernel variant 为 `bm`，而不是 PVM；
- CPU、内存和磁盘指标不是 0。

### 7.3 官方 Helm tests

```bash
helm test cube -n cube-system --timeout 20m --logs
```

`v0.7.0` 实际运行了 8 组测试：

| Test Suite | 验证内容 |
| --- | --- |
| `cube-health-test` | CubeMaster、CubeOps、CubeAPI、WebUI、Proxy、Node 健康 |
| `cube-cubemastercli-test` | CLI 能访问 CubeMaster 和沙箱列表 |
| `cube-cubeopscli-test` | CLI 能访问 CubeOps 和节点列表 |
| `cube-mysql-test` | MySQL 存活 |
| `cube-redis-test` | Redis `PONG` |
| `cube-proxy-control-test` | Proxy ClusterIP 控制路径 |
| `cube-node-image-test` | 节点镜像与产物 |
| `cube-node-runtime-test` | 宿主运行时资产 |

本次 8 组全部 `Succeeded`。

### 7.4 与现有 KVM 工作负载共存

如果测试节点已有 KubeVirt、libvirt 或其它 KVM 消费者，安装后必须重新检查：

```bash
kubectl get vmi -A -o wide
kubectl get node <node-name> -o jsonpath='{.spec.taints}'
```

本次节点上原有 4 个 KubeVirt VMI 在安装后都保持 `Running/Ready`，节点也没有新增污点。这只能说明一次低并发 PoC 没有立即冲突，不能证明两套虚拟化平台在资源压力、升级和故障场景下长期兼容。

## 8. 构建第一个模板

CubeSandbox 不能直接把任意 OCI 镜像当成运行中的沙箱。它要先把镜像转换成模板：拉取镜像、解包 rootfs、启动临时 MicroVM、等待 HTTP 探针、制作快照，再把制品分发到计算节点。

使用官方 `sandbox-code` 镜像：

```bash
kubectl exec -n cube-system deploy/cube-cubemastercli -- \
  sh -lc 'cubemastercli \
    --address "$CUBEMASTERCLI_ADDRESS" \
    --port "$CUBEMASTERCLI_PORT" \
    tpl create-from-image \
    --image <registry>/cube-sandbox/sandbox-code@sha256:<digest> \
    --alias k8s-smoke \
    --writable-layer-size 1G \
    --expose-port 49999 \
    --expose-port 49983 \
    --probe 49999 \
    --probe-path /health \
    --node <compute-node>'
```

私有仓库可使用 `--registry-username` 和 `--registry-password`，但不要把密码直接写进 shell history。更稳妥的方式是由 Secret、短期凭据或受控流水线注入。

### 8.1 私有 Registry CA 的隐藏问题

本次第一次模板构建失败在 `PULLING`：节点 containerd 已能拉取同一仓库，CubeMaster 的原生 OCI 导出流程却报 `x509: certificate signed by unknown authority`。

原因是两条拉取链路不同：

```text
Kubernetes Pod 镜像
  → kubelet / containerd
  → 节点上的 registry 配置与 CA

CubeSandbox 模板镜像
  → CubeMaster / Cubelet 的 OCI 客户端
  → 容器自己的 CA 信任链
```

生产解决方案应该是：

- 给 Registry 使用受信任的 HTTPS 证书；或
- 把企业 CA 以 ConfigMap/Secret 或定制镜像方式注入 CubeMaster 与相关模板构建组件；
- 固定镜像 Digest，避免 `latest` 漂移；
- 在安装验收里单独测试模板镜像拉取。

不要把关闭 TLS 校验当成长期方案，也不要因为 Kubernetes Pod 能拉取镜像就跳过模板构建测试。

### 8.2 观察模板状态

```bash
kubectl exec -n cube-system deploy/cube-cubemastercli -- \
  sh -lc 'cubemastercli \
    --address "$CUBEMASTERCLI_ADDRESS" \
    --port "$CUBEMASTERCLI_PORT" \
    tpl list -o wide'
```

一次成功构建会依次经过：

```text
PULLING
  → UNPACKING
  → DISTRIBUTING
  → CREATING_TEMPLATE
  → READY
```

本次模板最终在唯一计算节点上达到 `1/1 ready`。

## 9. 最小业务闭环：Create → Exec → Destroy

官方 Helm tests 已经覆盖大量组件健康，但仍要创建一个真实沙箱。

### 9.1 临时转发 CubeAPI

```bash
kubectl port-forward --address 127.0.0.1 \
  -n cube-system service/cube-api 13000:3000
```

### 9.2 创建沙箱

```bash
response="$(curl -sS --fail-with-body \
    -X POST http://127.0.0.1:13000/sandboxes \
    -H 'Content-Type: application/json' \
    -H 'X-API-Key: e2b_000000' \
    -d '{
      "templateID": "<template-id>",
      "timeout": 300,
      "autoPause": false
    }')"

sandbox_id="$(printf '%s' "$response" | jq -r '.sandboxID')"
printf 'sandbox_id=%s\n' "$sandbox_id"
```

测试环境中的 CubeAPI 没有额外启用 API Key 校验，但 SDK 和示例客户端仍要求一个非空占位值。生产环境必须接入正式鉴权，不能把这个占位值理解成安全凭据。

### 9.3 在沙箱中执行命令

```bash
kubectl exec -n cube-system daemonset/cube-node -c cubelet -- \
  cubecli exec "$sandbox_id" sh -lc '
    echo cube-smoke-ok
    uname -m
    uname -r
    findmnt -n -o FSTYPE /
  '
```

本次真实输出证明了：

- 沙箱状态为 `running`；
- Guest 架构是 `x86_64`；
- Guest Kernel 与宿主机内核不同；
- rootfs 使用 overlay；
- 命令在隔离环境中成功执行。

### 9.4 销毁并确认无残留

```bash
curl -sS --fail-with-body \
  -X DELETE "http://127.0.0.1:13000/sandboxes/${sandbox_id}" \
  -H 'X-API-Key: e2b_000000'

kubectl exec -n cube-system deploy/cube-cubemastercli -- \
  sh -lc 'cubemastercli \
    --address "$CUBEMASTERCLI_ADDRESS" \
    --port "$CUBEMASTERCLI_PORT" \
    cubebox list'
```

验收结束时 `SANDBOX_COUNT` 应恢复为 0。自动化脚本应使用 `trap` 或 `finally`，确保中途失败也能清理测试沙箱。

## 10. WebUI：部署后最直观的入口

WebUI Service 默认是 ClusterIP。测试环境可以只监听本机回环地址：

```bash
kubectl port-forward --address 127.0.0.1 \
  -n cube-system service/cube-webui 12088:12088
```

浏览器打开：

```text
http://127.0.0.1:12088
```

`v0.7.0` 首次登录的默认测试账号是 `admin / admin`。登录后应立即在 Settings 中修改密码。不要把 WebUI 或 CubeOps `:3010` 直接暴露到公网。

页面中最值得先看的位置：

| 页面 | 能回答的问题 |
| --- | --- |
| Overview | 当前沙箱数量、资源压力和健康节点数 |
| Nodes | 节点是否 Ready、版本是否一致、是否被隔离 |
| Templates | 模板是否 READY、构建任务在哪个阶段失败 |
| Sandboxes | 沙箱状态、模板、节点与生命周期操作 |
| Versions | Cubelet、Shim、Guest、Kernel、Agent 是否同版 |
| Network | 入口与网络相关配置 |
| Observability | 运行时、模板构建和沙箱健康概览 |
| API Keys | SDK 凭据管理 |

## 11. 部署完成后，有什么可玩、可测试的

把测试分成四级，能避免一开始就上高并发，把基础问题和性能问题混在一起。

### 11.1 Level 1：功能冒烟

目标是证明一条完整路径可用：

1. WebUI 登录；
2. 节点为 `HEALTHY/RUNNING`；
3. 构建一个 `sandbox-code` 模板；
4. 创建一个沙箱；
5. 执行 shell 和 Python；
6. 读写临时文件；
7. 销毁沙箱并确认数量回到 0。

可以使用 E2B 兼容 SDK：

```bash
python -m venv .venv
source .venv/bin/activate
pip install e2b-code-interpreter

export E2B_API_URL=http://127.0.0.1:13000
export E2B_API_KEY=e2b_000000
export CUBE_TEMPLATE_ID=<template-id>
```

```python
import os
from e2b_code_interpreter import Sandbox

with Sandbox.create(template=os.environ["CUBE_TEMPLATE_ID"]) as sandbox:
    result = sandbox.run_code("print(sum(i * i for i in range(10)))")
    print(result)
```

### 11.2 Level 2：模板与生命周期

值得玩的能力：

- 从不同 OCI 镜像构建模板；
- 给模板覆盖 command、args、env 和 probe；
- Pause / Resume；
- 创建 Snapshot；
- 从 Snapshot 创建新沙箱；
- Rollback 与 Clone；
- 模板 alias 与版本升级；
- 模板在多计算节点之间重新分发。

测试时记录：

- Create-to-Running；
- Pause、Resume、Snapshot、Rollback 各阶段耗时；
- 内存状态和文件状态是否按预期保留；
- 模板或 Guest 版本升级后，旧 Snapshot 是否兼容；
- 生命周期失败后是否有 orphan runtime、tap、volume 或元数据。

### 11.3 Level 3：网络与安全

至少验证四条路径：

| 测试 | 期望结果 |
| --- | --- |
| 沙箱访问公网 | 受 `allow_internet_access` 控制 |
| 沙箱访问集群/内网 | 默认策略符合预期，不误放行敏感网段 |
| 外部访问沙箱端口 | 通配域名、TLS、HTTP/gRPC Proxy 正常 |
| 动态更新网络策略 | 规则是替换还是合并，行为与文档一致 |

进一步可以测试：

- DNS 继承、搜索域和 `ndots`；
- `allowOut`、`denyOut` 和规则优先级；
- `allow_public_traffic=false` 与访问 Token；
- CubeEgress 代理、审计和凭据注入；
- Cilium/Calico 与 CubeVS eBPF Hook 的共存；
- MTU、NAT、长连接、WebSocket 和 gRPC。

不要在仍能访问生产内网的测试节点上做不受控 Agent 红队实验。网络默认拒绝必须用抓包和目标服务日志验证，不能只看 API 返回成功。

### 11.4 Level 4：存储、性能与故障

存储方面可以测试：

- MinIO/S3 持久卷；
- 销毁沙箱后重新挂载同一卷；
- 多租户卷隔离；
- XFS reflink 与 project quota；
- 数据盘逼近 80% 时的调度和告警；
- Snapshot 后端故障与恢复。

性能方面不要只测平均值：

- 单并发冷启动与热启动；
- 1、10、50、100 并发创建；
- P50、P95、P99 和最大值；
- Create API、调度、Cubelet、Guest probe 分阶段耗时；
- 不同模板大小和 writable layer 大小；
- 每节点沙箱密度、宿主内存开销和 CPU overcommit；
- 大量销毁后的存储与网络资源回收。

故障方面可以测试：

- 隔离/解除隔离计算节点；
- CubeMaster、Redis、MySQL、MinIO 短暂不可用；
- DNS 故障；
- Registry 不可达或 CA 过期；
- `/data/cubelet` 空间不足；
- `cube-node` Pod 重建；
- 节点重启与 Kubernetes 升级；
- 控制面升级与计算面版本漂移。

注意：当 `cubeNode.hostNetwork=false` 时，重建 `cube-node` 会更换 Pod Network Namespace，存量沙箱网络可能中断。不要在有重要沙箱运行时随意删除这个 Pod。

## 12. 本次已经证明什么，还没有证明什么

| 验证项 | 状态 | 结论边界 |
| --- | --- | --- |
| Helm 安装与资源 Ready | 已通过 | 仅一个单节点 profile |
| Local LVM PVC | 已通过 | 不具备跨节点高可用 |
| 原生 KVM 与 BM Guest | 已通过 | 没有测试 PVM |
| Cilium 基础共存 | 已通过 | 只覆盖模板与单沙箱 smoke，不是完整 CNI 认证 |
| 8 组官方 Helm tests | 已通过 | 证明组件和节点运行时健康 |
| 模板构建 | 已通过 | 单节点、单一官方镜像 |
| 沙箱 Create / Exec / Destroy | 已通过 | 单并发，无性能结论 |
| 与已有 KubeVirt VMI 共存 | 已观察通过 | 没有资源压力、升级和故障注入 |
| Pause / Resume / Snapshot | 未测试 | 需要单独验证状态与兼容性 |
| S3 持久卷 | 未测试 | MinIO 健康不等于业务卷闭环 |
| 入站域名与公网 TLS | 未测试 | 实验只使用本机 port-forward |
| 高并发和密度 | 未测试 | 不能引用官方 60ms 当本集群 SLO |
| 升级与灾难恢复 | 未测试 | 生产上线前必须补齐 |

## 13. 清理与回滚

卸载前先确认没有沙箱和仍需保留的模板、Snapshot、Volume：

```bash
kubectl exec -n cube-system deploy/cube-cubemastercli -- \
  sh -lc 'cubemastercli \
    --address "$CUBEMASTERCLI_ADDRESS" \
    --port "$CUBEMASTERCLI_PORT" \
    cubebox list'
```

再卸载 release：

```bash
helm uninstall cube -n cube-system
```

移除节点标签：

```bash
kubectl label node <node-name> \
  cube.tencent.com/cube-control- \
  cube.tencent.com/cube-node-
```

卸载后还要人工检查：

- PVC/PV 是否因 StorageClass reclaim policy 被删除；
- `/data/cubelet`、toolbox、日志和 loopback 文件是否保留；
- bpffs、挂载点和 udev/fstab 是否被修改；
- NodePort、ClusterRole、ClusterRoleBinding 是否清理；
- 私有 Registry 凭据和临时 CA 是否撤销。

不要直接递归删除 `/data/cubelet`。先确认没有其它 release、模板、Snapshot 或仍在运行的 runtime 使用该路径，再按官方清理流程处理。

## 14. 下一步怎么走

如果目标只是验证 Agent 代码能否在 MicroVM 中运行，这篇文章的 Create → Exec → Destroy 已经完成最小闭环。

如果准备进入团队试用，建议下一阶段按这个顺序推进：

1. 建设专用计算节点池，添加污点和准入策略；
2. 给 `/data/cubelet` 准备独立 XFS 数据盘；
3. 使用可信 HTTPS Registry、固定 Digest 和镜像签名；
4. 接入正式鉴权、生产 TLS、Wildcard DNS 和受控入口；
5. 决定 `cubeNode.hostNetwork`，并完成 NetworkPolicy/Egress 设计；
6. 验证 Pause/Resume、Snapshot、S3 Volume 和恢复；
7. 做并发、密度、资源回收和故障注入；
8. 最后才定义本环境的启动时延与可用性 SLO。

## 参考资料

- [CubeSandbox GitHub](https://github.com/TencentCloud/CubeSandbox)
- [CubeSandbox v0.7.0 Release](https://github.com/TencentCloud/CubeSandbox/releases/tag/v0.7.0)
- [Kubernetes 部署总览](https://cubesandbox.com/zh/guide/kubernetes/)
- [Kubernetes 安装](https://cubesandbox.com/zh/guide/kubernetes/install)
- [Kubernetes 架构](https://cubesandbox.com/zh/guide/kubernetes/architecture)
- [v0.7.0 Chart 默认值](https://github.com/TencentCloud/CubeSandbox/blob/v0.7.0/deploy/kubernetes/chart/values.yaml)
- [创建 OCI 镜像模板](https://cubesandbox.com/zh/guide/tutorials/template-from-image)
- [WebUI](https://cubesandbox.com/zh/guide/webui)
- [网络策略](https://cubesandbox.com/zh/guide/network-policy)
- [生命周期](https://cubesandbox.com/zh/guide/lifecycle)
- [CLI 工具](https://cubesandbox.com/zh/guide/cli-tools)
