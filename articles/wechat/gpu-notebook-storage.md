# 大模型时代 GPU 开发平台踩坑记：共享算力、存储与环境恢复

我们不是一开始就决定用 Operator、KubeVirt 和 Ceph RBD 来建设 GPU Notebook。

最初的方案很常见：JupyterHub on Kubernetes，KubeSpawner 创建用户 Pod，GPU 节点提供本地存储。随着用户和模型规模增长，我们较早不再把 Jupyter Notebook 作为默认开发入口，转向 code-server；计算侧采用组内共享八卡开发机，存储侧又依次尝试 NFS、CephFS CSI、每用户 RBD和旁路保存用户镜像，最后才走到自建 Operator 与 KubeVirt + RBD 根盘。

整个过程不是简单的技术替换，而是一条连续的因果链：

```text
KubeSpawner 生命周期和模板能力不符合平台预期
  ↓
默认入口转向 code-server 与 Coding Agent 工作区
  ↓
组级共享八卡开发机 + 用户资源归因
  ↓
本地盘 → NFS → CephFS
  ↓
每用户 RBD + 显式 CephFS 共享目录
  ↓
个人镜像只能提供时间点恢复
  ↓
Workspace Operator 统一管理生命周期
  ↓
KubeVirt + RBD 根盘保存完整环境
```

回头看，这是一段很典型的大模型开发平台演进：IDE、算力、用户环境和存储生命周期互相牵连。每个方案都解决了当时最痛的问题，也把下一层问题暴露出来。

![GPU 开发入口与控制面的演进](../../docs/assets/practices/gpu-notebook-platform-evolution/01-platform-evolution.png)

## 1. 从 JupyterHub + KubeSpawner 到 code-server

第一版平台使用 JupyterHub on Kubernetes。JupyterHub 处理认证和用户 Server 状态，KubeSpawner 根据用户选择的规格创建 Notebook Pod。

对于标准 Jupyter 场景，这套组合很成熟：管理员可以通过 Profile 控制镜像、CPU、内存、GPU、节点选择和 PVC，用户点击启动后很快就能进入 JupyterLab。

但我们较早发现，算法工程师的主要工作已经不再局限于 Notebook Cell。大模型和 Coding Agent 开发更依赖：

- 在完整代码仓库中进行多文件编辑、搜索、重构和 Diff；
- 同时使用终端、Git、调试器、容器工具和远程任务客户端；
- 安装语言服务器、代码检查、调试和 AI 编程插件；
- 运行需要长期索引代码库和调用外部工具的 Agent；
- 对开源 Coding Agent 进行二次开发和插件集成。

code-server 提供与 VS Code 兼容的使用习惯和更丰富的插件生态。在我们内部，它很快拥有了比 Jupyter Notebook 更多的日常用户，也更适合作为 Coding Agent 工作区的基础。

Jupyter 并没有完全消失。数据探索、可视化和逐步验证仍然适合 Notebook，但它不再定义整个 GPU 开发平台。平台需要管理的是通用 Workspace，前端可以是 code-server，也可以是 JupyterLab，后端还可能是容器或虚拟机。

但我们的目标逐渐不再只是“启动一个 Jupyter Server”。平台还需要：

- 同时支持 Notebook 和 code-server；
- 统一管理 Pod、PVC、Service、访问入口和用户状态；
- 对工作区执行停止、恢复、升级、重建和回收；
- 使用版本化模板控制镜像、GPU、网络与存储；
- 让用户环境的生命周期独立于一次 Pod 启动；
- 为容器和虚拟机提供一致的申请与管理入口。

我们原本期望的模型更像 Kubernetes Operator：

```text
Workspace Spec
  → Controller 持续调谐期望状态
  → 管理 Pod/VMI、PVC、Service 与访问入口
  → 暴露稳定的 Status、Event 和审计记录
```

KubeSpawner 的核心抽象则是“为一个 JupyterHub 用户启动或停止 Server”。配置主要通过 Traitlets、`profileList`、Override 和 Hook 组合。规格、动态挂载、审批、恢复和生命周期条件越来越多后，Spawner 配置逐渐变成大量条件逻辑。

这不是 KubeSpawner 的缺陷，而是抽象层次不同。它首先是一个 Spawner，不是通用 Workspace Operator。标准 Jupyter Pod 适合直接交给它；当平台希望统一管理更多 IDE、资源对象和生命周期时，就需要自己的工作区抽象。

code-server 和 Agent 工具链也让后面的环境问题更加明显：插件、语言服务、编译器、Agent 依赖和项目工具会被安装到更多路径，基础镜像越来越大，单纯持久化几个 Notebook 目录越来越难覆盖用户真实环境。

不过在环境恢复问题完全暴露之前，我们先遇到了更直接的 GPU 资源矛盾。

## 2. GPU 共享：一人一卡不够，一人一台八卡机又不现实

传统 Notebook 平台常用“一人一张 GPU”的规格。但在大模型时代，一张卡可能连模型都放不下。算法同事进行 Tensor Parallel、推理验证或多卡训练调试时，通常希望直接使用一台开发机上的 8 张 GPU，以及大部分 CPU 和内存。

如果严格按一人一卡分配，用户拿到资源却无法完成实验；如果为每个人准备一台八卡开发机，GPU 数量、机器成本和运维规模又无法承受。

Notebook 的资源曲线还非常特殊：集中开发时可能突然占满 GPU，读代码、写配置、开会或离线时，利用率又长时间接近 0。把开发机永久绑定给个人，会产生大量空闲 GPU Hours。

我们的做法是把资源边界放到团队，而不是个人：

```text
算法组 A
  ├─ 8-GPU 开发机 A1
  ├─ 8-GPU 开发机 A2
  └─ 组内 Workspace 用户共享这些机器

算法组 B
  ├─ 8-GPU 开发机 B1
  └─ 组内 Workspace 用户共享这台机器
```

每个组分配若干台开发机。组内用户进入共享节点后，在资源空闲时可以使用一台机器的 8 张 GPU，以及接近整机的 CPU 和内存。平台不为每个人静态保留硬件，而是让突发需求在时间上复用同一批资源。

这种方式提高了利用率，却把问题从“有没有资源”变成了“现在是谁在使用资源”。如果用户只看到 GPU 已满，却不知道 CPU、内存和显存被谁占用，最后所有冲突都会变成平台团队逐个排查和协调。

因此，我们同时提供面向用户的实时资源看板，把节点消费归因到具体用户和 Workspace：

```text
开发机资源看板
  ├─ CPU：当前高占用用户与 Workspace
  ├─ 内存：使用量、增长趋势和主要消费者
  ├─ GPU：利用率、显存、功耗和对应用户
  └─ 节点：总容量、空闲量和异常状态
```

当资源不足时，组内成员可以先查看大户，再直接协商暂停、错峰或迁移实验。资源冲突从“平台为什么不给我 GPU”，变成团队内部可见、可讨论的问题，大幅减少了平台充当人工调度员的沟通成本。

这套方式依赖两个前提：组内成员相互可信，资源使用能够准确归因。它是一种**软隔离和团队自治**，不是严格的性能隔离。一个用户的显存 OOM、CPU 满载或 GPU 故障仍可能影响同机其他用户。因此跨团队仍需保留节点边界，性能压测和正式训练则应进入独占资源或受队列治理的 Job 系统。

![组级八卡开发机共享与用户资源归因](../../docs/assets/practices/gpu-notebook-platform-evolution/02-gpu-team-sharing.png)

资源共享缓解后，下一层瓶颈很快转向存储。

## 3. 第一坑：GPU 节点本地盘很快不够用了

第一版 Notebook 直接使用 GPU 节点本地存储。它路径简单、延迟低，模型解压、Python Import 和编译缓存都不需要经过网络。

在传统 Python 开发中，这可能够用；进入大模型阶段后，容量增长非常快：

- 单个模型可能占用几十到数百 GiB；
- 多位用户会重复下载同一份模型和数据；
- Conda、pip、CUDA 扩展和编译缓存不断累积；
- 数据集、Checkpoint 和实验产物持续增长；
- 节点重装、缩容或故障可能带走用户唯一副本。

本地盘还有两个结构性问题：用户换到另一台 GPU 节点后看不到原目录，也无法自然提供团队共享。

因此，本地 NVMe 后来仍被保留，但职责改成了缓存和 Scratch：热点模型、数据分片、编译缓存、临时解压都可以放进去，前提是节点丢失后能够从权威存储重建。

## 4. 第二坑：自建 NFS 能共享，但不容易继续扩

为了让 Notebook 跨节点恢复，并让用户共享文件，我们开始使用自建 NFS。

NFS 的优点很直接：POSIX 接口、使用门槛低，大多数现有脚本不需要修改。在用户不多、负载可控时，它完全可以是一种有效方案。

规模扩大后，问题逐渐出现：

- 容量和吞吐扩展依赖服务端设计；
- 单机或简单主备容易成为性能与故障瓶颈；
- 小文件、目录遍历和并发元数据操作会放大服务端压力；
- 高可用、扩容、备份和性能归因都需要平台团队自行维护；
- 所有用户共享同一服务，噪声租户会影响其他人。

我们需要的已经不只是“可以被多个 Pod 挂载”，而是能够随用户数、模型体积和元数据并发继续扩展。于是存储继续转向集群已有的 Ceph。

## 5. 第三坑：CephFS 解决了共享，却承接了不可控的 Home

CephFS 可以通过 CSI 动态供给 RWX 卷，提供 POSIX 目录语义，也具备更完整的容量和故障恢复能力。

最初我们把用户个人目录放到 CephFS。设计上看很合理：Pod 调度到任何 GPU 节点都能访问原 Home，用户之间也可以共享目录，平台只需要维护一种文件存储。

真正上线后，Notebook 用户行为的不确定性开始影响 MDS。

Notebook 本质上是一个带浏览器入口、终端和任意代码执行能力的长期 Shell。用户可能：

- 使用 Conda、pip、npm 创建数万甚至数十万个小文件；
- 执行 Git Checkout、递归 `find`、IDE 索引和文件监听；
- 下载并解压大模型，在缓存目录中生成大量临时文件；
- 反复扫描、移动或删除整个环境目录；
- 让多个 Kernel 和后台进程同时访问同一 Home；
- 把日志、Lock、缓存和中间结果都写进共享目录。

CephFS 的数据最终进入 RADOS，但目录、文件名、权限和 inode 等元数据需要经过 MDS。当所有用户 Home 共享同一个元数据平面时，一位用户制造的目录风暴就可能推高 MDS 延迟，进而影响所有人的 Git、Conda、Python Import 和 Notebook 启动。

增加 MDS 资源可以暂时缓解，但没有改变负载模型。我们最终意识到，问题不是简单的“CephFS 性能不够”，而是：

> 大量无需共享、行为不可预测的个人文件，被放进了共享文件系统的元数据热路径。

## 6. 第一次关键优化：个人目录用 RBD，共享目录才用 CephFS

重新分析访问模式后，我们发现绝大多数个人 Home 都具有相同特点：只属于一个用户，同一时刻通常只由一个工作区读写，需要停止后保留，但不需要多节点同时挂载。

这正好符合块存储，而不是 RWX 文件系统。

于是个人目录改成每用户一个 Ceph RBD PVC：

```text
用户 A Workspace
  └─ RWO/RWOP → RBD Volume A
用户 B Workspace
  └─ RWO/RWOP → RBD Volume B
用户 C Workspace
  └─ RWO/RWOP → RBD Volume C
```

用户在 Home 中创建、扫描和删除文件时，不再进入 CephFS MDS，个人负载被分散到各自文件系统和 Ceph RBD/OSD 数据路径。

这个变化带来了几项直接收益：

- 每个用户的容量、扩容和告警可以独立管理；
- 一位用户的小文件风暴不再直接占用共享 MDS；
- PVC 可以独立快照、恢复、归档和离职回收；
- 工作区 Pod 删除后，个人 RBD 继续保留；
- 用户重新调度到其他节点时，可以重新 Attach 原卷。

RBD 通常只能由一个节点读写，因此平台必须保证同一用户只有一个活跃工作区，并在节点失联时谨慎处理强制迁移和防双挂载。对个人 Notebook 来说，这个约束与实际生命周期是匹配的。

CephFS 没有被删除，而是收缩到明确需要共享的场景：团队代码、公共数据、共享工具和兼容 POSIX 的协作目录。每个项目有自己的路径、ACL、配额和生命周期策略。

第一轮优化后的目录大致是：

```text
/home/jovyan  → 每用户 Ceph RBD，个人目录
/shared       → CephFS，明确的团队共享目录
/models       → 节点 NVMe，热点模型缓存
/scratch      → Local NVMe / emptyDir，可丢弃
```

这一步显著缓解了 CephFS MDS 压力，却仍然没有完全解决“用户环境能否恢复”。

## 7. 第四坑：持久化 Home，不等于持久化整个环境

容器 Notebook 重建时，只有挂载到持久卷的路径会保留，容器可写层中的修改仍会消失。

为了减少环境丢失，我们已经把常用目录绑定到 CephFS 或 RBD，例如用户 Home、常见 Conda 环境、pip 缓存和部分 IDE 配置。问题是，平台无法完全干预用户怎样安装软件。

用户可能把内容写到：

- `/opt/conda`、`/opt/cuda` 或其他自定义目录；
- `/usr/local/bin`、`/usr/local/lib`；
- 系统 Python、APT 数据库和系统配置；
- code-server、Jupyter 扩展或工具自己的隐藏目录；
- 平台没有预先识别出的任意缓存与运行目录。

只要还有一个重要路径位于容器可写层，Pod 重建后环境就可能不完整。继续增加目录挂载会让模板越来越复杂，也无法覆盖未来软件产生的新路径。

与此同时，Notebook 基础镜像越来越大。CUDA、PyTorch、编译工具、JupyterLab、code-server 和常用依赖都希望提前放进镜像，以减少用户安装时间。镜像越完整，体积越大；镜像越精简，用户重建环境的工作越多。

这造成了一个很难彻底解决的矛盾：

```text
大而全的镜像 → 拉取慢、预热难、升级和 Registry 成本高
精简的镜像   → 用户安装多、重建慢、任意路径更难持久化
```

用户最直接的感受是：昨天还能工作的环境，Pod 重建后突然缺少某个库、编译器或系统配置。即使多数文件已经保留，丢掉的那一小部分也足以让整个环境不可用。

## 8. 过渡方案：旁路保存用户镜像

为了尽快降低环境重建带来的投诉，平台增加了旁路环境保存能力。用户可以主动把当前工作区保存为个人镜像，后续从这个镜像恢复。

它解决了一个重要问题：除了预先挂载的目录，容器可写层中的软件和配置也能在保存时进入恢复点。用户不必每次都从公共基础镜像重新安装所有依赖。

但个人镜像本质上是**时间点恢复**，不是持续持久化：

```text
上一次保存镜像
      ↓
用户继续修改环境
      ↓
节点或 Pod 故障
      ↓
只能恢复到上一次保存点
```

如果机器在下一次保存前发生故障，这段时间的系统级修改仍会丢失。保存频率越高，镜像构建、上传、Registry 容量和版本清理压力越大；保存频率越低，恢复点就越旧。

个人镜像还会放大镜像体积问题：每位用户都可能产生多个包含 CUDA、Conda 和缓存的巨大镜像，节点拉取时间、Registry 存储和垃圾回收都变得更难控制。

因此，旁路保存镜像是非常有价值的止损手段，但它无法提供“机器随时崩溃，环境仍恢复到最后一次写入”的语义。

## 9. 控制面转向：自建 Operator 管理 Notebook 和 code-server

随着存储、镜像保存、工作区类型和恢复策略增多，继续把全部逻辑放在 KubeSpawner Hook 中已经难以维护。

我们最终通过自建 Operator 重新管理 Notebook 和 code-server，把工作区作为独立资源，而不是一次 Jupyter Server 启动。

Operator 统一处理：

- 用户选择的镜像、CPU、内存和 GPU 规格；
- Notebook 或 code-server 工作负载；
- 个人 RBD、共享 CephFS 和临时缓存挂载；
- Service、访问入口和工作区状态；
- 创建、启动、停止、重建、升级和删除；
- 容器环境与 KubeVirt 环境的不同生命周期。

最重要的变化是：计算对象与用户数据被明确拆开。

```text
停止 Workspace ≠ 删除用户数据
重建 Pod        ≠ 重建个人 RBD
删除 Workspace  ≠ 立即删除磁盘
```

JupyterHub 仍然可以作为用户入口或认证体系的一部分，但平台生命周期不再被 Spawner 的单一 Server 模型限制。Notebook 和 code-server 也可以共享同一套规格、存储和审计逻辑。

## 10. 完整环境恢复：KubeVirt + Ceph RBD 根盘

即使由 Operator 管理，容器本身仍然只有被挂载的目录可以持续保存。要完整覆盖 `/etc`、`/opt`、`/usr/local`、`/var`、Home、systemd 和任意隐藏路径，就不能继续猜测用户会把文件写到哪里。

因此平台进一步支持用 KubeVirt 创建 Notebook 环境，并把用户 VM 的根盘放在独立 Ceph RBD 上：

```text
KubeVirt VirtualMachine
  ├─ Root RBD：/、/home、/opt、/usr/local、/var
  ├─ Shared CephFS：团队协作目录
  ├─ Object/Data Layer：模型、数据和 Checkpoint
  ├─ Local Scratch：可重建缓存
  └─ GPU：PCI Passthrough 或经过验证的 vGPU
```

现在用户在 guest OS 内写入的所有目录都进入 RBD 根盘。只要 Ceph RBD 保持正常，即使 VMI 重启、Pod 重建或计算节点发生故障，VM 在其他节点重新启动后仍能看到完整文件系统。

它与“保存个人镜像”的区别是：

| 模式 | 保存范围 | 恢复点 | 主要限制 |
| --- | --- | --- | --- |
| 容器 + Home RBD | 预先挂载的个人目录 | 持续 | 任意系统路径仍在容器可写层 |
| 容器 + 旁路镜像保存 | 保存时的容器环境 | 某个时间点 | 两次保存之间仍可能丢失 |
| KubeVirt + Root RBD | 完整 guest 文件系统 | 持续 | 运维成本和资源开销更高 |

KubeVirt 不是免费的持久化。平台还要管理黄金镜像、guest OS 补丁、RBD 扩容、快照与备份、QEMU Guest Agent、GPU 直通、节点故障隔离和恢复流程。VM 启动密度和速度也通常不如容器。

因此，我们没有把所有用户都迁移到 VM，而是把它作为一类明确的工作区规格。

## 11. 最终形成两类 GPU 工作区

最终平台同时保留容器和 KubeVirt 两种路径：

![最终工作区与 Ceph RBD、CephFS 存储分层](../../docs/assets/practices/gpu-notebook-platform-evolution/03-final-architecture.png)

### 默认容器工作区

适合大多数用户：

- 使用平台维护的 CUDA/PyTorch 基础镜像；
- Notebook 或 code-server 快速启动；
- 每用户一个 RBD Home；
- 团队共享内容进入 CephFS；
- 模型和数据使用权威存储与节点缓存；
- 正式训练提交到 Job、TrainJob 或 RayJob。

它的优势是密度高、启动快、镜像和安全边界容易标准化。用户需要接受系统层修改不能无限制持久化。

### 持久 VM 工作区

适合确实需要个人 Linux 工作站语义的用户：

- 需要 `apt`、systemd、自定义 CUDA Toolkit 或编译器；
- 软件会安装到任意系统路径；
- 停止数天后仍要求完整恢复；
- 能接受更长启动时间和更高资源开销；
- 平台能够承担 guest OS 与磁盘生命周期治理。

停止 VMI 后，CPU、内存和 GPU 被释放，VM 对象与 RBD 根盘保留。再次启动时，用户恢复的是整套操作系统，而不是几个被猜中的目录。

## 12. 这套链路已经在测试集群跑起来了

为了避免架构只停留在图上，我们在测试集群部署并验证了 KubeVirt 与 CDI。验证时 Kubernetes 为 `v1.30.4`、KubeVirt 为 `v1.4.1`、CDI 为 `v1.61.1`，控制面中的 `virt-api`、`virt-controller`、`virt-handler`、`virt-operator` 和 CDI 控制器均正常运行。

最先检查的是控制面，而不是直接创建几十台 VM：

```bash
kubectl get pods -n kubevirt
kubectl get pods -n cdi
kubectl get kubevirt -n kubevirt
kubectl get cdi -n cdi
```

然后为用户准备独立的 DataVolume，再让 VirtualMachine 引用它。对外公开的生产模板统一把根盘放到 `ceph-rbd`：

```yaml
apiVersion: cdi.kubevirt.io/v1beta1
kind: DataVolume
metadata:
  name: notebook-user01-root
spec:
  sourceRef:
    kind: DataSource
    name: ubuntu-24-04-gpu
    namespace: vm-images
  storage:
    accessModes: [ReadWriteOnce]
    storageClassName: ceph-rbd
    resources:
      requests:
        storage: 200Gi
```

根盘由平台独立管理，不把删除 VM 直接等价为删除 DataVolume 和 PVC。工作区的实际创建顺序是：

```text
选择黄金镜像
  → CDI 克隆个人 RBD 根盘
  → 创建默认停止的 VirtualMachine
  → 用户启动后生成 VMI 和 virt-launcher Pod
  → guest 内启动 code-server / JupyterLab
  → 用户停止后删除 VMI，保留 VM 与 RBD
```

测试集群中同时保留了 Running 和 Stopped 的用户 VM。部分工作区处于 Running，其他批量创建的用户工作区保持 Stopped，用来验证“停止计算但不删除环境”。检查时使用：

```bash
kubectl get vm,vmi,dv,pvc -n gpu-workspaces
```

这组状态比单纯看到 VM 启动成功更重要：Running 用户有 VMI，Stopped 用户不再占用 VMI 对应的 CPU、内存和 GPU，但工作区对象与个人根盘仍处于平台控制之下。再次启动后，恢复的是 RBD 中的完整系统。

完整的 Ceph RBD、DataVolume、VM、Service、快照和故障验证清单已经整理到 AIK8S 实战文章，公众号正文只保留最关键的部署链路。

## 13. 最终的数据分层

无论使用容器还是 VM，大模型、数据集和 Checkpoint 都不应无限复制进个人磁盘。最终存储职责被拆成：

| 数据 | 推荐位置 | 原因 |
| --- | --- | --- |
| 容器用户 Home | 每用户 RBD PVC | 个人读写、独立扩容和恢复 |
| VM 完整系统 | 每用户 RBD 根盘 | 保存任意 guest 文件路径 |
| 团队共享目录 | CephFS | RWX、POSIX、ACL 和项目配额 |
| 模型与数据权威副本 | 对象/模型数据层 | 版本化、跨节点和跨集群恢复 |
| 热点模型与编译缓存 | 节点 NVMe | 低延迟、高吞吐，可重建 |
| Notebook Scratch | `emptyDir`/本地盘 | 临时解压和中间结果 |
| 正式 Checkpoint | 权威持久层 | 与个人工作区生命周期解耦 |

关键不是目录名称，而是让用户明确知道：什么会持续保存，什么可以共享，什么只能恢复到某个时间点，什么会随着节点或 Pod 消失。

## 14. 这段踩坑过程留下的经验

第一，**Spawner 和平台控制器不是同一个抽象。** 标准 Jupyter Server 可以直接使用 KubeSpawner；当工作区需要多 IDE、多资源对象、复杂恢复和不同运行形态时，Operator 更容易维持一致生命周期。

第二，**GPU 开发入口已经从 Notebook Cell 扩展为完整 IDE 与 Agent Workspace。** code-server 的代码仓库、终端和插件工作流更适合多数日常开发，Jupyter 则保留在数据探索和交互验证场景。

第三，**大模型交互开发不适合简单套用一人一卡。** 组级共享八卡开发机能够承接突发需求，但必须提供用户归因监控，才能让团队自行发现并协调资源大户。

第四，**共享开发机是软隔离，不是生产调度。** 性能压测、正式训练和需要稳定 SLO 的任务，仍应使用独占资源或受队列治理的执行系统。

第五，**本地盘的优势应该用于缓存，而不是唯一持久副本。** 它能显著改善模型加载和编译速度，但必须允许节点故障后重建。

第六，**不要为不需要共享的数据支付 RWX 成本。** 个人 Home 使用 RBD，把不可控小文件移出 CephFS MDS 热路径；CephFS 只服务真正的团队共享目录。

第七，**持久化几个常用目录，无法等价于持久化用户环境。** 平台永远无法提前猜中用户会把所有软件写到哪里。

第八，**个人镜像是恢复点，不是磁盘。** 它适合容器环境的阶段性保存和迁移，但无法覆盖两次保存之间的故障窗口。

第九，**完整恢复需要完整根盘。** 对必须拥有个人 Linux 工作站语义的用户，KubeVirt + RBD 根盘比不断增加容器挂载目录更诚实，也更容易解释故障边界。

我们最终没有找到一个组件解决所有问题，而是接受了资源和工作区分层：组级共享开发机解决突发式八卡需求，队列和独占资源承接正式任务；容器解决标准化和密度，KubeVirt 解决完整环境持久化；RBD 隔离个人写入，CephFS 提供受控共享，本地 NVMe 加速热点数据，Operator 把这些不同生命周期重新组织成统一产品。

这套方案比最初的 `JupyterHub + Pod + 一块共享盘` 复杂得多，但每一层复杂度都有明确来源，也对应一段真实踩坑。

完整的 GPU Notebook 架构、KubeVirt + RBD 实践、存储 PoC 和上线清单，将放在“阅读原文”的 AIK8S 文档中。
