---
title: Kubernetes 如何承载 AI 工作负载
description: 从控制器、调度、设备、网络和存储理解 AI 工作负载在 Kubernetes 中的完整运行路径
status: stable
last_reviewed: 2026-08-02
---

# Kubernetes 如何承载 AI 工作负载

Kubernetes 不理解“训练”“推理”或“模型”，它首先理解的是声明式 API、Pod、资源、控制器和节点。AI 平台在这个通用底座上增加设备发现、成组调度、训练生命周期、模型分发和请求级调度。

理解各层职责，是排查 AI 平台问题的起点。否则很容易把模型加载失败归咎于调度器，或者把 GPU 节点无法创建误认为 Kueue 配额不足。

## 1. 完整运行路径

```text
用户提交 TrainJob / RayJob / InferenceService / Deployment
                    │
                    ▼
Operator / Controller 将高层 API 转换为 Pod、Service 等资源
                    │
                    ▼
Kueue 等准入控制决定工作负载何时可以使用配额
                    │
                    ▼
kube-scheduler 根据资源、拓扑、亲和性和约束选择节点
                    │
                    ▼
Device Plugin 或 DRA Driver 分配 GPU、NIC 等设备
                    │
                    ▼
kubelet 通过 CRI 请求 containerd / CRI-O 创建容器
                    │
                    ▼
CNI 配置网络，CSI 挂载卷，Runtime 注入设备和驱动库
                    │
                    ▼
训练框架或推理引擎加载代码、数据和模型并开始计算
```

这条链路中的每一层都有独立状态。看到 Pod `Pending` 时，应先确认它是否已经被队列准入，再看 scheduler 事件；看到容器已启动但 `torch.cuda.is_available()` 为 false，则重点检查设备分配、Runtime 和容器镜像。

## 2. Kubernetes 原生对象负责什么

| 对象 | 主要职责 | AI 场景中的典型用法 |
| --- | --- | --- |
| Pod | 最小调度和运行单元 | 单个训练 Worker、推理副本、数据处理步骤 |
| Job | 运行到完成并记录成功/失败 | 单机训练、批推理、模型转换 |
| Deployment | 维护无状态副本和滚动发布 | 单机推理引擎、网关、控制服务 |
| StatefulSet | 稳定身份和有序生命周期 | 向量数据库、元数据服务、部分分布式系统 |
| Service | 稳定的四层访问入口 | 推理服务、训练 Rendezvous、内部数据库 |
| Gateway / HTTPRoute | 七层入口和流量策略 | 模型 API、租户路由、Canary |
| ConfigMap / Secret | 配置与敏感值 | 引擎参数、对象存储凭据、模型访问 Token |
| PersistentVolumeClaim | 持久化卷声明 | Notebook 工作区、模型缓存、Checkpoint |
| RuntimeClass | 选择容器隔离实现 | runc、gVisor、Kata、机密容器 |
| PriorityClass | Pod 调度优先级 | 在线推理容量保护、紧急训练 |
| ResourceQuota | Namespace 级资源上限 | CPU、内存、对象数量和扩展资源约束 |

Job 不表达多角色训练，Deployment 也不理解一个模型副本跨多个节点。Kubeflow Trainer、KubeRay、JobSet 和 LeaderWorkerSet 等控制器用于补齐这些语义，而不是替代 Kubernetes。

## 3. 四类扩展接口

### CRI：容器运行时

kubelet 通过 Container Runtime Interface 与 containerd、CRI-O 等运行时交互。GPU 容器最终仍是普通 OCI 容器，只是在创建时额外挂载设备节点、驱动库和环境变量。

需要关注：

- containerd/CRI-O 与 Kubernetes 的兼容关系；
- NVIDIA Container Toolkit、ROCm Runtime 等设备运行时配置；
- 默认 Runtime 与 GPU、Kata 等 RuntimeClass 的选择；
- cgroup v2、共享内存、ulimit 和 IPC 配置；
- 镜像拉取、解压和 Snapshotter 对冷启动的影响。

### CNI：网络

CNI 为 Pod 配置接口、地址和路由。AI 集群通常同时存在：

- 集群默认网络，用于 Kubernetes API、Service 和普通东西向流量；
- RDMA/InfiniBand/RoCE 网络，用于训练 Collective 和 KV Cache 传输；
- 公网或入口网络，用于推理 API；
- 存储网络，用于数据集、模型和 Checkpoint。

Multus 可以给 Pod 添加第二张网卡，但具体性能、隔离和 NetworkPolicy 能力由底层 CNI、SR-IOV 和硬件决定。

### CSI：存储

CSI 负责卷的创建、挂载、扩容和快照。AI 平台还经常直接访问对象存储，因此“有 CSI”并不等于解决了数据路径：

- 数据集可能通过 S3/GCS/Azure Blob 或并行文件系统读取；
- 模型权重可能来自 Hugging Face、OCI Registry 或对象存储；
- Checkpoint 需要并发写入、原子提交和跨故障域恢复；
- 本地 NVMe 缓存需要调度器理解数据所在节点。

### Device Plugin 与 DRA

Device Plugin 把设备暴露为整数扩展资源，例如 `nvidia.com/gpu: 1`。Dynamic Resource Allocation 使用 `DeviceClass`、`ResourceSlice` 和 `ResourceClaim` 描述设备属性和分配要求。

两者都只负责设备发现与分配，不负责安装内核驱动，也不负责训练任务的配额和排队。

## 4. 控制器与 Operator

控制器不断比较期望状态和实际状态，并通过 Reconcile 让系统收敛。例如一个训练控制器可能：

1. 观察到新的 TrainJob；
2. 创建 Worker、Launcher 或其他角色；
3. 注入 Rendezvous、环境变量和端口；
4. 监控 Pod 状态；
5. 将失败原因和完成状态写回 CR；
6. 按策略清理或重试。

Operator 往往还负责安装、升级和配置某个软件栈，例如 GPU Operator 管理驱动、Toolkit、Device Plugin、MIG 和监控组件。

不要把所有平台逻辑塞进一个自研 CRD。优先复用职责单一、状态语义清晰的上游 API，并通过模板或平台 API 组合它们。

## 5. 三次不同的调度决策

AI 平台至少有三次容易混淆的决策：

| 阶段 | 决策 | 常见组件 |
| --- | --- | --- |
| 工作负载准入 | 现在是否有配额运行整个任务 | Kueue、Volcano Queue |
| Pod 放置 | 每个 Pod 去哪个节点 | kube-scheduler、Volcano Scheduler |
| 请求路由 | 一次推理请求进入哪个模型副本 | Gateway、Inference Extension、llm-d Router |

此外，节点自动扩缩容器会根据 Pending Pod 决定是否创建节点，Device Plugin/DRA 则在节点范围内决定分配哪块设备。

## 6. 资源请求如何影响 AI

一个 Pod 的可调度性由所有容器的资源请求共同决定。只填写 GPU 而忽略 CPU 和内存会产生两个问题：

- scheduler 可能把过多数据加载器或 Tokenizer 放到同一节点；
- 节点自动扩缩容无法准确选择实例规格。

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: gpu-worker
spec:
  restartPolicy: Never
  containers:
    - name: worker
      image: registry.example.com/ai/runtime@sha256:replace-with-digest
      resources:
        requests:
          cpu: "8"
          memory: 64Gi
          nvidia.com/gpu: "1"
        limits:
          cpu: "8"
          memory: 64Gi
          nvidia.com/gpu: "1"
```

生产环境还要考虑 `/dev/shm`、临时存储、HugePages、锁页内存和 PID 数量。它们不会因为申请 GPU 自动获得合理默认值。

## 7. Pod 生命周期与 AI 语义

Kubernetes 只知道容器退出码、探针和重启策略，并不知道：

- Loss 是否出现 NaN；
- 所有 Rank 是否仍在同一个 Collective；
- Checkpoint 是否完整；
- 模型是否已经加载到 GPU；
- 推理引擎是否仍能满足 TTFT。

这些健康信号必须由框架、控制器和业务探针补充。推理 Pod 的 `Ready` 应表示能够接收目标模型的请求，而不是仅仅进程端口已监听。

## 8. Namespace 不是完整隔离边界

Namespace 适合组织资源、RBAC、配额和策略，但多个 Pod 仍共享节点内核和设备驱动。运行不可信 Notebook、外部训练代码或 Agent 工具时，需要组合：

- 最小权限 ServiceAccount；
- Pod Security Admission；
- 默认拒绝的 NetworkPolicy；
- Seccomp、AppArmor/SELinux；
- gVisor、Kata 或机密容器；
- 独立节点池或独立集群。

GPU Time-Slicing 也不是显存或故障隔离。平台必须准确描述不同共享模式的安全承诺。

## 9. 最小排障顺序

### Pod 一直 Pending

```bash
kubectl get pod -A --field-selector=status.phase=Pending
kubectl describe pod -n <namespace> <pod>
kubectl get events -n <namespace> --sort-by=.lastTimestamp
kubectl get nodes -o custom-columns=NAME:.metadata.name,GPU:.status.allocatable.nvidia\.com/gpu
```

依次判断：队列是否准入、资源是否存在、节点约束是否冲突、PVC 是否绑定、自动扩容是否失败。

### 容器启动但看不到 GPU

```bash
kubectl describe pod -n <namespace> <pod>
kubectl get runtimeclass
kubectl get daemonset -A
kubectl logs -n <operator-namespace> <device-plugin-pod>
```

检查请求的资源名、Device Plugin/DRA Driver、RuntimeClass、容器镜像和宿主驱动。

### GPU 存在但性能很差

先把问题拆成数据、CPU、GPU Kernel、GPU 间通信、节点间网络和存储六层，再分别做基准。不要直接通过增加 GPU 数量掩盖瓶颈。

## 10. 基础设施验收清单

- [ ] 能画出从用户 API 到容器和设备的完整控制路径。
- [ ] CRI、CNI、CSI、Device Plugin/DRA 的负责人和版本清楚。
- [ ] 每个 AI Pod 都声明真实 CPU、内存、临时存储和设备请求。
- [ ] 队列准入、Pod 调度、节点扩容和请求路由分别可观测。
- [ ] 探针表达模型或训练语义，不只检查端口。
- [ ] Namespace、节点和 RuntimeClass 的隔离承诺写入平台文档。
- [ ] 关键事件能关联到 Workload、Job、Pod、Node 和 Device。
- [ ] 对 Pending、设备不可见和性能下降分别有排障路径。

## 延伸阅读

- [Kubernetes Components](https://kubernetes.io/docs/concepts/overview/components/)
- [Kubernetes Controllers](https://kubernetes.io/docs/concepts/architecture/controller/)
- [Container Runtime Interface](https://kubernetes.io/docs/concepts/architecture/cri/)
- [Device Plugins](https://kubernetes.io/docs/concepts/extend-kubernetes/compute-storage-net/device-plugins/)
- [Dynamic Resource Allocation](https://kubernetes.io/docs/concepts/scheduling-eviction/dynamic-resource-allocation/)
- [RuntimeClass](https://kubernetes.io/docs/concepts/containers/runtime-class/)
