# K3s 升级与 DRA 预检报告

> 目标主机：**192.168.1.200**；主机日志时间以 CST（UTC+8）为准。报告记录环境检查、版本规划、多阶段备份、逐小版本升级、故障处理、最终验证，以及 Kubernetes 1.36 DRA 预检。

## 1. 最终结论

| 项目 | 最终状态 |
| --- | --- |
| 升级 | 已完成，按小版本顺序升级 |
| K3s | `v1.36.2+k3s1 (01b6f04a)` |
| Node | `master` / Ready |
| Container Runtime | `containerd 2.3.2-k3s2` |
| cgroup | v1 / systemd driver，保留兼容配置 |
| API 健康 | `/readyz = ok` |
| 备份 | 874M / 多阶段 |
| Traefik | 3.7.4 / `192.168.1.200` |
| DRA API | `resource.k8s.io/v1` 可用，尚未安装 Driver |
| 主机重启 | 未重启，只重启 K3s 服务 |

K3s 已按 Kubernetes 版本偏差要求逐小版本升级；原有自定义 systemd unit、代理环境和 `--cluster-domain cat.dog` 均被保留。升级期间只重启 K3s 服务，没有重启操作系统。

## 2. 升级前环境

| 项目     | 检查结果                                                                |
|----------|-------------------------------------------------------------------------|
| 主机     | `192.168.1.200`，SSH 用户 `root`                                        |
| 操作系统 | Anolis OS 8.9，x86_64                                                   |
| 内核     | `5.10.134-17.3.an8.x86_64`                                              |
| 资源     | 约 30 GiB 内存，磁盘约 882 GiB 可用                                     |
| 拓扑     | 单节点：`master`，角色为 control-plane / master                         |
| 初始 K3s | `v1.32.5+k3s1`，节点 Ready                                              |
| 数据存储 | SQLite：`/var/lib/rancher/k3s/server/db/state.db`；未启用 embedded etcd |
| cgroup   | cgroup v1；`stat -fc %T /sys/fs/cgroup` 返回 `tmpfs`                    |
| 集群域   | `cat.dog`                                                               |

### 自定义 systemd 服务

服务文件没有被安装脚本覆盖，原有挂载和参数保持不变。核心配置如下：

    ExecStartPre=/bin/sleep 10s
    ExecStartPre=/usr/bin/bindfs -u 1000 -g 1000 \
      /mnt/k8s/docker/images/local-gitea/gitea/local /mnt/gitea
    ExecStart=/usr/local/bin/k3s server --cluster-domain cat.dog
    ExecStopPost=/bin/sh -c "umount /mnt/gitea || true"

代理环境位于 `/etc/systemd/system/k3s.service.env`，升级过程中予以保留。

### 升级前 Pod 基线

-   Running：44
-   存在大量历史终态 Pod（Completed、Error、ContainerStatusUnknown）。
-   `default/blog-0` 在升级前已是 `ImagePullBackOff`。
-   4 个非 Traefik ServiceLB 因单节点宿主机 80 端口竞争而 Pending。

## 3. 版本规划与准备

查询 K3s 默认 stable channel 后，目标版本为 `v1.36.2+k3s1`。由于 Kubernetes 不支持跳过多个小版本直接升级，采用以下路线：

    v1.32.5+k3s1
      → v1.32.13+k3s1
      → v1.33.13+k3s1
      → v1.34.9+k3s1
      → v1.35.6+k3s1
      → v1.36.2+k3s1

### 二进制与校验

五个目标版本的 amd64 二进制下载到以下缓存目录，并逐一对照官方 `sha256sum-amd64.txt` 校验：

    /var/tmp/k3s-upgrade/v1.32.13+k3s1/k3s
    /var/tmp/k3s-upgrade/v1.33.13+k3s1/k3s
    /var/tmp/k3s-upgrade/v1.34.9+k3s1/k3s
    /var/tmp/k3s-upgrade/v1.35.6+k3s1/k3s
    /var/tmp/k3s-upgrade/v1.36.2+k3s1/k3s

校验结果全部通过。下载缓存约 378M。

### 系统镜像预拉取

根据各版本官方 `k3s-images.txt`，提前缓存了升级后新增或变化的核心镜像：

-   `rancher/klipper-helm:v0.11.1-build20260615`
-   `rancher/klipper-lb:v0.4.17`
-   `rancher/local-path-provisioner:v0.0.36`
-   `rancher/mirrored-coredns-coredns:1.14.4`
-   `rancher/mirrored-library-busybox:1.37.0`
-   `rancher/mirrored-library-traefik:3.7.4`
-   `rancher/mirrored-metrics-server:v0.8.1`
-   `rancher/mirrored-pause:3.6`

拉取期间代理和公共镜像仓库偶发 503/TLS timeout；通过重试完成了核心镜像缓存。

## 4. 备份记录

初始备份和每次跨小版本前的备份均保存在：

    /var/backups/k3s-upgrade-20260801-095231-v1.32.5+k3s1

目录权限设置为 `0700`，最终占用约 **874M**。备份内容包括：

-   停止 K3s 后复制的一致性 SQLite 数据库目录；
-   server token（仅备份文件，报告中不记录其内容）；
-   每阶段旧版 `/usr/local/bin/k3s`；
-   `/etc/rancher/k3s`、systemd unit 和代理环境配置；
-   升级前节点、Pod、控制器状态快照；
-   最终生效的 cgroup v1 kubelet drop-in。

| 备份目录                     | 对应阶段             |
|------------------------------|----------------------|
| `db-v1.32.5+k3s1`            | 最初数据库一致性副本 |
| `pre-v1.33.13-from-v1.32.13` | 升级到 v1.33.13 前   |
| `pre-v1.34.9-from-v1.33.13`  | 升级到 v1.34.9 前    |
| `pre-v1.35.6-from-v1.34.9`   | 升级到 v1.35.6 前    |
| `pre-v1.36.2-from-v1.35.6`   | 升级到 v1.36.2 前    |

## 5. 升级执行时间线

1.  **v1.32.5 → v1.32.13**
    停止服务、复制 SQLite 与旧二进制、替换 K3s、启动并验证 Node Ready。containerd 更新到 2.1.5。
2.  **v1.32.13 → v1.33.13**
    升级成功；Node 为 Ready，containerd 更新到 2.2.5-k3s1.33。
3.  **v1.33.13 → v1.34.9**
    升级成功；Node 为 Ready，containerd 更新到 2.2.5-k3s2。启动阶段处理了一次 Flannel VXLAN 竞态。
4.  **v1.34.9 → v1.35.6**
    发现 Kubernetes 1.35 默认拒绝 cgroup v1；改用 kubelet drop-in 设置 `failCgroupV1: false` 后恢复。
5.  **Traefik v40 升级修复**
    重新执行被中断的 CRD Helm Job，Traefik CRD 和主 Chart 都升级到 revision 5，Traefik 镜像变为 3.7.4。
6.  **v1.35.6 → v1.36.2**
    最终版本启动；网络策略控制器第一次启动遇到瞬时 link 枚举错误，systemd 自动重试一次后稳定。
7.  **最终恢复**
    恢复 Traefik ServiceLB 优先级；重试 nginx 镜像解析，升级前 44 个 Running Pod 全部恢复。

## 6. cgroup v1 兼容处理

Kubernetes 1.35 起 kubelet 默认设置 `failCgroupV1=true`。最初尝试的 K3s 配置为：

    kubelet-arg:
      - "fail-cgroupv1=false"

在 v1.35.6 上，K3s 已使用 `--config-dir` 启动 kubelet，上述 CLI 配置没有进入最终 kubelet 参数， 导致 kubelet反复退出。日志中的关键错误为：

    Error: failed to validate kubelet configuration,
    error: kubelet is configured to not run on a host using cgroup v1.

随后按 K3s 推荐方式创建高优先级 drop-in：

    # /var/lib/rancher/k3s/agent/etc/kubelet.conf.d/99-cgroup-v1.conf
    apiVersion: kubelet.config.k8s.io/v1beta1
    kind: KubeletConfiguration
    failCgroupV1: false

`/etc/rancher/k3s/config.yaml` 改为说明性注释，避免保留无效参数：

    # Kubelet cgroup v1 compatibility is configured in:
    # /var/lib/rancher/k3s/agent/etc/kubelet.conf.d/99-cgroup-v1.conf

最终通过 kubelet `configz` 验证：

    {"failCgroupV1":false,"cgroupDriver":"systemd"}

cgroup v1 目前可以运行，但 Kubernetes 已将其标记为弃用，未来版本可能完全移除支持。 本次按用户要求继续使用 v1，没有修改内核启动参数，也没有重启主机。

## 7. 升级中问题与处理

### 7.1 v1.34.9 Flannel VXLAN 启动竞态

第一次启动时出现一次空指针：

    panic: runtime error: invalid memory address or nil pointer dereference
    github.com/flannel-io/flannel/pkg/backend/vxlan.(*network).watchVXLANDevice

systemd 自动重启，随后持续稳定；观察重启计数、Node Ready 和四个核心 Deployment 后再继续下一阶段。

### 7.2 bindfs 遗留进程警告

    Found left-over process (bindfs) in control group while starting unit. Ignoring.

确认 `/mnt/gitea` 挂载正确。该信息来自 bindfs 守护化后的 cgroup 遗留警告，不是 v1.34 崩溃根因，因此未改动自定义 unit。

### 7.3 v1.35 cgroup v1 启动循环

根因是 CLI 形式的兼容开关未进入最终 kubelet 配置。停止服务后写入 `99-cgroup-v1.conf`，重启即恢复，Node 版本变为 `v1.35.6+k3s1`。

### 7.4 Traefik CRD Chart 被中断

多次 kubelet 退出中断了 Helm revision 更新，主 Chart 报错：

    UPGRADE FAILED: Required CRDs are missing.
    Please install the corresponding CRD chart before installing this chart.

检查 Helm release 后确认 CRD Job 是过期 Job。删除生成的 `helm-install-traefik-crd` Job， 让 Helm Controller 重新创建并执行。最终：

-   `traefik-crd` revision 5：deployed；
-   `traefik` revision 5：deployed；
-   HelmChart `Failed=False`；
-   Traefik 镜像为 `rancher/mirrored-library-traefik:3.7.4`。

### 7.5 单节点 ServiceLB 端口竞争

集群内多个 LoadBalancer Service 都请求宿主机 80 端口。为了恢复升级前的入口行为，删除了以下由 K3s 自动生成的 DaemonSet，让 Traefik ServiceLB 优先调度：

-   `svclb-dify-nginx-nodeport-*`
-   `svclb-envoy-aibrix-*`
-   `svclb-envoy-default-*`
-   `svclb-kube-prometheus-stack-grafana-*`

K3s Controller 随后会重新创建它们；由于端口已被 Traefik 占用，这 4 个 Pod 继续 Pending，与升级前行为一致。

### 7.6 v1.36 网络策略控制器瞬时错误

    failed to start networking: unable to initialize network policy controller:
    error getting node subnet: failed to get list of links:
    results may be incomplete or inconsistent

systemd 自动重试一次。第二次启动成功，最终 `NRestarts=1`，之后服务持续 active/running。

### 7.7 公共镜像仓库 503

升级重启后，配置为 `imagePullPolicy: Always` 的部分 Pod 因 Docker Hub / Quay 503 短暂失败。核心镜像已提前缓存；对原先 Running 的 Volcano nginx Pod执行一次显式拉取：

    k3s crictl pull docker.io/library/nginx:latest

拉取成功后 Pod 自动恢复为 Running。未修改业务 Deployment 的 imagePullPolicy。

## 8. 最终健康验证

最终检查时间：`2026-08-01T10:21:24+08:00`。

| 检查项                 | 最终结果                                                   |
|------------------------|------------------------------------------------------------|
| K3s 版本               | `v1.36.2+k3s1 (01b6f04a)`                                  |
| systemd                | `ActiveState=active`，`SubState=running`                   |
| API                    | `k3s kubectl get --raw=/readyz` 返回 `ok`                  |
| Node                   | `master Ready`，Internal IP `192.168.1.200`                |
| Container runtime      | `containerd://2.3.2-k3s2`                                  |
| cgroup                 | v1；kubelet `failCgroupV1=false`，driver 为 systemd        |
| CoreDNS                | 1/1 Ready                                                  |
| metrics-server         | 1/1 Ready                                                  |
| local-path-provisioner | 1/1 Ready                                                  |
| Traefik                | Deployment 1/1；ServiceLB 2/2；External IP `192.168.1.200` |
| 聚合 APIService        | 没有 Available=False 的 APIService                         |
| Service externalIPs    | 未发现使用已弃用 `spec.externalIPs` 的 Service             |
| Running Pod            | 44，与升级前 Running 基线相同                              |

### 最终非终态异常 Pod

-   `default/blog-0`：ImagePullBackOff；升级前已存在，当前不是升级引入。
-   4 个非 Traefik ServiceLB Pod：Pending；单节点 80 端口冲突，行为与升级前一致。

大量 Error、Completed 和 ContainerStatusUnknown 为集群内长期保留的历史终态 Pod；运行中工作负载基线已经恢复。

## 9. DRA 功能预检与建议测试

在最终 v1.36.2 集群上执行只读预检，确认以下 API 已由 `resource.k8s.io/v1` 提供：

-   DeviceClass（cluster-scoped）
-   ResourceSlice（cluster-scoped）
-   ResourceClaim（namespaced）
-   ResourceClaimTemplate（namespaced）

当前四类资源均为空，`/var/lib/kubelet/plugins_registry` 中也没有 DRA 驱动 socket。这表明控制面 DRA API 已启用，但还没有安装 DRA 驱动。

### 异构 GPU 管理：对 node label / taint 的改进

DRA 对“集群中存在大量型号和能力层级不同的 GPU”有直接帮助。它把调度依据从节点级标签下沉到具体设备： DRA Driver 发布每一块 GPU 的属性和容量，工作负载声明需要的能力，scheduler 同时选择具体设备和能够访问该设备的节点。

传统方式通常要在节点上维护类似标签，并在每个工作负载中重复 nodeSelector、nodeAffinity、taint 和 toleration：

    gpu.vendor: nvidia
    gpu.model: h100
    gpu.memory: 80g
    gpu.arch: hopper
    gpu.pool: training
    gpu.exclusive: "true"

这种方式描述的是整台节点，而不是节点里的每一块卡。如果同一节点混装 H100、A100 或其他设备，节点标签很难准确表达每块设备的型号、显存、健康状态和可分配数量。

DRA Driver 则通过 ResourceSlice 发布设备级库存，概念上类似：

    节点 node-a
    ├── GPU-0: NVIDIA H100, 80GiB, Hopper, healthy
    ├── GPU-1: NVIDIA A100, 40GiB, Ampere, healthy
    └── GPU-2: NVIDIA T4,   16GiB, Turing, unhealthy

Pod 使用 ResourceClaim 请求“设备能力”，不必知道目标节点名称。DeviceClass 和 ResourceClaim 可以使用 CEL 按驱动、设备属性及容量进行筛选。具体属性名由 DRA Driver 定义，以下表达式仅为结构示意：

    selectors:
      - cel:
          expression: >-
            device.capacity["driver.example.com"].memory
              .compareTo(quantity("80Gi")) >= 0

| 管理维度       | Node label / taint                 | DRA                                    |
|----------------|------------------------------------|----------------------------------------|
| 描述对象       | 整台节点                           | 每一块物理或逻辑设备                   |
| 型号与显存     | 人工同步标签                       | 驱动发布设备属性和容量                 |
| 同节点混合 GPU | 表达困难                           | 每块 GPU 独立记录                      |
| 设备选择       | nodeSelector / affinity            | DeviceClass + CEL selector             |
| 候选设备回退   | 需要复杂 affinity 或自定义调度逻辑 | 可使用 prioritized list                |
| 故障或预留     | 通常 taint 整个节点                | 支持设备级 taint / toleration          |
| 分区与共享     | 依赖厂商扩展                       | 可建模分区和可消费容量                 |
| 分配生命周期   | 主要体现为扩展资源数量             | Claim、Prepare、Unprepare 和回收可观察 |

### 建议由平台提供能力级 DeviceClass

业务最好不要直接绑定某个具体型号，而由平台团队提供稳定的能力分层：

    gpu-inference-small
      → T4、A10、L4

    gpu-inference-large
      → L40S、A100、H100

    gpu-training-standard
      → A100 40G、A100 80G

    gpu-training-premium
      → H100、H200

    gpu-memory-80g
      → 任意显存至少 80GiB 的兼容设备

这样增加 H200、B200 或其他设备时，主要调整 DeviceClass 和策略，而不需要批量修改业务 YAML。Kubernetes 1.36 的 prioritized list 已稳定，可以表达“优先 H100，没有则回退 A100”一类策略。

### 仍然需要保留的节点标签和污点

DRA 不替代所有 node label。可用区、机架、CPU 架构、本地数据、网络、存储拓扑、操作系统和节点维护状态仍应使用 label、affinity 或 node taint。推荐的边界是：

    Node label / taint
      → 描述和管理节点、机房及基础设施拓扑

    DRA ResourceSlice / DeviceClass / ResourceClaim
      → 描述、选择和管理具体 GPU

### 多厂商与驱动成熟度限制

-   DRA 不能自动让 CUDA 工作负载运行在 AMD GPU 上；容器镜像、运行时和软件栈仍需兼容目标厂商。
-   通常应先建立 NVIDIA、AMD 等厂商级基础 DeviceClass，再在同一兼容栈内建立训练、推理和显存等级。
-   Kubernetes DRA 核心 API 已稳定，但生产能力取决于厂商驱动是否发布足够的设备属性，并支持 MIG、共享、健康检查及无中断升级。
-   当前 Kubernetes SIGs NVIDIA DRA Driver 的 ComputeDomain 已正式支持，但 GPU allocation 部分仍标为试验性质且 Helm 默认关闭；AMD ROCm DRA Driver 已提供 v1 API 与 Helm Chart，但项目也较年轻。

参考：[Kubernetes DRA 概念](https://kubernetes.io/docs/concepts/scheduling-eviction/dynamic-resource-allocation/)、 [DeviceClass API](https://kubernetes.io/docs/reference/kubernetes-api/resource/device-class-v1/)、 [Kubernetes 1.36 DRA 更新](https://kubernetes.io/blog/2026/05/07/kubernetes-v1-36-dra-136-updates/)、 [NVIDIA DRA Driver](https://github.com/kubernetes-sigs/dra-driver-nvidia-gpu)、 [AMD ROCm DRA Driver](https://github.com/ROCm/k8s-gpu-dra-driver)。

### 推荐迁移顺序

1.  盘点现有 GPU 型号、显存、MIG、驱动版本和现有 label 规则。
2.  先使用官方模拟驱动验证 ResourceClaim 的分配与回收流程。
3.  选择非关键 GPU 节点试装对应厂商的 DRA Driver，确认同一物理设备不会同时被旧 Device Plugin 和 DRA 重复分配。
4.  建立平台级能力 DeviceClass，例如 `gpu-training-large`。
5.  迁移一个非关键 Job，测试设备筛选、候选回退、释放、驱动重启和节点 drain。
6.  驱动稳定后，逐步移除只用于描述 GPU 型号、显存和健康状态的 node label；保留节点级运维与拓扑标签。

### 无 GPU 的端到端测试方案

建议使用 Kubernetes 官方 `dra-example-driver`，它会模拟 9 个 GPU，不需要真实 GPU。安装会创建测试 namespace 和少量 cluster-scoped RBAC/DeviceClass：

    k3s kubectl create namespace dra-tutorial

    for file in \
      deviceclass \
      serviceaccount \
      clusterrole \
      clusterrolebinding \
      priorityclass \
      daemonset
    do
      k3s kubectl apply --server-side \
        -f "https://k8s.io/examples/dra/driver-install/${file}.yaml"
    done

    k3s kubectl -n dra-tutorial rollout status \
      daemonset/dra-example-driver-kubeletplugin --timeout=180s

    k3s kubectl get deviceclasses
    k3s kubectl get resourceslices

创建 Claim 和消费它的 Pod：

    k3s kubectl apply --server-side \
      -f https://k8s.io/examples/dra/driver-install/example/resourceclaim.yaml

    k3s kubectl apply --server-side \
      -f https://k8s.io/examples/dra/driver-install/example/pod.yaml

    k3s kubectl -n dra-tutorial wait \
      --for=condition=Ready pod/pod0 --timeout=180s

成功标准：

1.  `kubectl get resourceslices` 能看到 `gpu.example.com` 提供的模拟设备；
2.  `some-gpu` ResourceClaim 状态为 `allocated,reserved`；
3.  Pod 日志包含类似 `GPU_DEVICE_0="gpu-0"`；
4.  驱动日志出现 `PrepareResourceClaims`；
5.  删除 Pod 后，Claim 回到 pending，驱动日志出现 `UnprepareResourceClaims`。

<!-- -->

    k3s kubectl -n dra-tutorial get resourceclaims
    k3s kubectl -n dra-tutorial logs pod0 -c ctr0 | \
      grep -E 'GPU_DEVICE_[0-9]+='
    k3s kubectl -n dra-tutorial logs \
      -l app.kubernetes.io/name=dra-example-driver

### 清理测试资源

    k3s kubectl delete namespace dra-tutorial
    k3s kubectl delete \
      deviceclass/gpu.example.com \
      clusterrole/dra-example-driver-role \
      clusterrolebinding/dra-example-driver-role-binding \
      priorityclass/dra-driver-high-priority

本次只执行了 DRA API 和 kubelet 插件目录预检，没有实际安装示例驱动，避免未经确认创建 cluster-scoped RBAC 资源。

## 10. 关键命令记录

以下为本次执行过的主要命令模式。重复的逐版本操作只记录一次通用流程；敏感 token 未输出。

### 版本与节点检查

    k3s --version
    k3s kubectl get nodes -o wide
    k3s kubectl get pods -A -o wide
    systemctl show k3s -p ActiveState -p SubState -p NRestarts

### cgroup 与 kubelet 生效配置

    stat -fc %T /sys/fs/cgroup
    k3s kubectl get --raw /api/v1/nodes/master/proxy/configz | \
      jq '.kubeletconfig | {failCgroupV1,cgroupDriver,featureGates}'

### 逐版本停机升级通用流程

    # 1. 运行中状态快照
    k3s kubectl get nodes -o wide > "$pre/nodes-before.txt"
    k3s kubectl get pods -A -o wide > "$pre/pods-before.txt"

    # 2. 停止服务并复制一致性 SQLite
    timeout 180 systemctl stop k3s
    cp -a /var/lib/rancher/k3s/server/db "$pre/db"
    cp -a /var/lib/rancher/k3s/server/token "$pre/server-token"
    cp -a /usr/local/bin/k3s "$pre/k3s-old-version"

    # 3. 原子替换二进制并启动
    install -m 0755 "$target" /usr/local/bin/k3s.next
    mv -f /usr/local/bin/k3s.next /usr/local/bin/k3s
    systemctl start k3s

    # 4. 验证版本和 Ready
    k3s kubectl get node master -o wide
    k3s kubectl get --raw=/readyz

### 核心组件验证

    k3s kubectl -n kube-system get deploy \
      coredns metrics-server local-path-provisioner traefik
    k3s kubectl -n kube-system get svc traefik -o wide
    k3s kubectl -n kube-system get pod \
      -l svccontroller.k3s.cattle.io/svcname=traefik

### Traefik CRD Job 恢复

    k3s kubectl -n kube-system delete job \
      helm-install-traefik-crd --wait=true
    k3s kubectl -n kube-system get helmchart traefik traefik-crd

### 恢复 Traefik ServiceLB 优先调度

    for ds in $(k3s kubectl -n kube-system get ds -o name | \
      grep -E 'svclb-(dify-nginx|envoy-aibrix|envoy-default|kube-prometheus-stack-grafana)')
    do
      k3s kubectl -n kube-system delete "$ds" --wait=false
    done

### APIService、Pod 基线和 externalIPs 检查

    k3s kubectl get apiservice -o json | jq -r '
      .items[] |
      select(any(.status.conditions[]?;
        .type=="Available" and .status!="True")) |
      .metadata.name'

    k3s kubectl get pods -A --no-headers | awk '
      {count[$4]++}
      END {for (status in count) print status, count[status]}'

    k3s kubectl get svc -A -o json | jq -r '
      .items[] |
      select((.spec.externalIPs // []) | length > 0) |
      [.metadata.namespace,.metadata.name,
       (.spec.externalIPs|join(","))] | @tsv'

### DRA 预检

    k3s kubectl api-resources --api-group=resource.k8s.io -o wide
    k3s kubectl get deviceclasses
    k3s kubectl get resourceslices
    k3s kubectl get resourceclaims -A
    k3s kubectl get resourceclaimtemplates -A
    find /var/lib/kubelet/plugins_registry -maxdepth 1 -type s

## 11. 官方参考资料

-   [K3s Manual Upgrades](https://docs.k3s.io/upgrades/manual)
-   [K3s v1.36 Release Notes](https://docs.k3s.io/release-notes/v1.36.X)
-   [K3s Configuration Options / Kubelet Drop-ins](https://docs.k3s.io/installation/configuration)
-   [K3s Backup and Restore](https://docs.k3s.io/datastore/backup-restore)
-   [K3s Rollback](https://docs.k3s.io/upgrades/roll-back)
-   [Kubernetes Version Skew Policy](https://kubernetes.io/releases/version-skew-policy/)
-   [Kubelet Configuration and Drop-in Directory](https://kubernetes.io/docs/tasks/administer-cluster/kubelet-config-file/)
-   [Install Drivers and Allocate Devices with DRA](https://kubernetes.io/docs/tutorials/cluster-management/install-use-dra/)
-   [Kubernetes SIGs DRA Example Driver](https://github.com/kubernetes-sigs/dra-example-driver)
-   [Kubernetes v1.36 DRA Updates](https://kubernetes.io/blog/2026/05/07/kubernetes-v1-36-dra-136-updates/)

报告记录的是本次实际执行与观察到的结果。出于安全考虑，未记录 SSH 私钥、K3s server token 或任何镜像仓库凭据。
