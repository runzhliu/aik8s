---
title: GPU 节点软件栈、初始化与验收
description: 从固件、内核、驱动、容器运行时到 Kubernetes 设备接入构建可维护的 GPU 节点
status: stable
last_reviewed: 2026-08-02
---

# GPU 节点软件栈、初始化与验收

GPU 节点能够加入 Kubernetes，不代表它已经适合生产 AI。真正的验收要覆盖固件、PCIe/NUMA、内核驱动、容器运行时、设备接入、监控、网络和实际框架。

## 1. 软件栈边界

```text
训练框架 / 推理引擎
PyTorch、JAX、vLLM、SGLang、TensorRT-LLM
                  │
用户态计算与通信库
CUDA/ROCm、cuDNN、NCCL/RCCL、UCX/NIXL
                  │
容器设备注入
Container Toolkit、CDI、RuntimeClass
                  │
Kubernetes 设备管理
Device Plugin 或 DRA Driver
                  │
节点管理
GPU Operator、NFD、监控与健康控制器
                  │
宿主机
固件、BIOS、内核、驱动、PCIe、NUMA、GPU、NIC
```

容器中的 CUDA Toolkit 可以比宿主机驱动更新到一定程度，但具体兼容范围以厂商矩阵为准。不要因为 `nvidia-smi` 能运行，就推断任意 CUDA、PyTorch 和 NCCL 组合都受支持。

## 2. 节点镜像应固定什么

建议把以下内容纳入不可变节点镜像或声明式节点配置：

- 操作系统发行版与补丁级别；
- 内核、启动参数和 cgroup 模式；
- GPU/NIC 固件与驱动策略；
- containerd/CRI-O 配置；
- 时间同步、DNS、证书和 Registry CA；
- 磁盘分区、日志和本地缓存目录；
- kubelet 预留、驱逐阈值和最大 Pod 数；
- Node Feature Discovery 和稳定平台标签来源；
- 安全加固、审计和远程访问策略。

驱动可以由 GPU Operator 容器化安装，也可以预装在节点镜像中。两种方式都可行，关键是只能有一个权威来源，并明确升级、重启和回滚顺序。

## 3. 固件与 BIOS

在安装 Kubernetes 前确认：

- GPU、NIC、主板和 BMC 固件处于受支持组合；
- IOMMU/VT-d/AMD-Vi 按 SR-IOV、Kata 或直通需求配置；
- Above 4G Decoding 和 Resizable BAR 按硬件参考架构启用；
- NUMA、CPU SMT、功耗和性能模式有明确标准；
- PCIe 链路宽度和速率符合设计；
- NVLink/NVSwitch Fabric Manager 状态正常；
- Secure Boot 与驱动模块签名策略一致。

这些设置受具体服务器和加速器限制，不能复制一份通用 BIOS 模板后跳过厂商验证。

## 4. 内核与驱动

驱动升级前至少核对：

| 层级 | 要确认的兼容性 |
| --- | --- |
| OS/内核 | 厂商驱动是否支持，DKMS/KMM 能否构建 |
| GPU 驱动 | GPU 型号、固件、CUDA/ROCm 版本 |
| Container Toolkit | containerd/CRI-O 与 Runtime 配置 |
| Device Plugin/DRA | Kubernetes API 与驱动版本 |
| 通信库 | NCCL/RCCL、OFED、UCX、RDMA Core |
| 框架镜像 | PyTorch/JAX/vLLM 的二进制构建目标 |

内核小版本更新也可能触发驱动模块重建。Canary 节点必须执行完整计算、P2P、RDMA 和框架测试，而不是只观察 DaemonSet 为 Ready。

## 5. 容器运行时与 CDI

Container Device Interface 使用标准化 JSON 规范描述容器应获得的设备节点、挂载和环境变量。它能减少针对不同容器运行时的专用 Hook，但不会替代 Device Plugin/DRA 的调度和分配。

检查 containerd：

```bash
containerd --version
crictl info
crictl version
```

检查节点上的 CDI 规格：

```bash
find /etc/cdi /var/run/cdi -maxdepth 2 -type f -print 2>/dev/null
```

生产中应记录生成 CDI 文件的组件、刷新时机和回滚行为。设备重配置后陈旧的 CDI Spec 可能让容器获得错误设备路径。

## 6. GPU Operator 安装模式

NVIDIA GPU Operator 常见组件包括：

- Driver Manager；
- Container Toolkit；
- Device Plugin 或 DRA Driver；
- GPU Feature Discovery；
- DCGM 与 DCGM Exporter；
- MIG Manager；
- Node Feature Discovery；
- 验证工作负载与升级控制。

安装前选择：

1. 驱动由 Operator 安装还是宿主机预装；
2. container toolkit 是否已有权威来源；
3. Device Plugin 还是 DRA；
4. 是否启用 MIG、Time-Slicing 或 MPS；
5. DCGM 指标由谁采集；
6. OpenShift、Kata、vGPU、RDMA 等是否需要专用配置。

AMD GPU Operator 同样可以管理驱动、Device Plugin、节点标签、指标和健康测试。不要把 NVIDIA 组件名称硬编码为平台通用 API。

## 7. kubelet 资源预留

GPU 节点仍需要足够 CPU 和内存运行 kubelet、CNI、CSI、Device Plugin、监控和日志代理。建议明确：

```yaml
kubeReserved:
  cpu: 1
  memory: 2Gi
systemReserved:
  cpu: 1
  memory: 2Gi
evictionHard:
  memory.available: 1Gi
  nodefs.available: 10%
```

示例仅表达思路，实际数值应基于节点规模、DaemonSet 和最大 Pod 数测量。低估预留会出现 GPU 空闲但节点因内存或磁盘压力驱逐工作负载。

## 8. CPU、NUMA 与拓扑

数据加载、Tokenization、通信和推理网关都消耗 CPU。GPU 工作负载应尽量让：

- CPU 核与目标 GPU 位于相近 NUMA 节点；
- GPU 与 RDMA NIC 具有理想 PCIe 路径；
- `/dev/shm`、锁页内存和 HugePages 满足通信库；
- CPU Manager、Topology Manager 策略经过真实负载验证；
- 多容器 Pod 的资源请求不会破坏整体拓扑。

查看节点拓扑：

```bash
lscpu
numactl --hardware
lspci -tv
nvidia-smi topo -m
```

不同厂商使用各自诊断工具，但排查目标相同：确认设备之间的实际互联路径，而不是只看 Kubernetes 标签。

## 9. 本地磁盘和共享内存

大型模型冷启动可能同时消耗容器镜像层、模型权重和临时转换空间。节点需要规划：

- containerd 数据目录容量和 inode；
- 本地模型/数据缓存独立目录；
- emptyDir `sizeLimit` 和 ephemeral-storage 请求；
- `/dev/shm` 的 memory-backed volume；
- 日志轮转和失败 Pod 清理；
- 缓存水位、淘汰和预热机制。

```yaml
volumes:
  - name: dshm
    emptyDir:
      medium: Memory
      sizeLimit: 16Gi
containers:
  - name: worker
    volumeMounts:
      - name: dshm
        mountPath: /dev/shm
```

## 10. 节点标签和 Taint

硬件事实建议由 NFD、GPU Feature Discovery 或厂商 Node Labeller生成；平台抽象标签由平台团队维护。

避免业务直接依赖大量厂商内部标签。可以建立稳定映射：

```text
厂商发现标签
  nvidia.com/gpu.product=NVIDIA-H100-80GB-HBM3
        │
        ▼
平台标签
  platform.example.com/accelerator-class=h100-80g
```

升级发现组件时，平台标签契约可以保持稳定。

## 11. 分层验收

### 第 1 层：硬件与驱动

```bash
nvidia-smi
nvidia-smi -q
nvidia-smi topo -m
```

确认 GPU 数量、ECC、温度、功耗、PCIe、NVLink 和错误记录。

### 第 2 层：Kubernetes 库存

```bash
kubectl get nodes
kubectl describe node <gpu-node>
kubectl get pods -A -o wide --field-selector spec.nodeName=<gpu-node>
```

检查容量、可分配资源、标签、Taint、RuntimeClass 和设备组件。

### 第 3 层：容器设备

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: gpu-smoke-test
spec:
  restartPolicy: Never
  containers:
    - name: cuda
      image: nvcr.io/nvidia/k8s/cuda-sample:vectoradd-cuda12.5.0
      resources:
        limits:
          nvidia.com/gpu: "1"
```

成功标准不只是 Pod Completed，还要检查分配设备、日志和 DCGM 的 Pod 映射。

### 第 4 层：设备间互联

执行 P2P、NVLink/NVSwitch 和 NCCL Tests。跨节点再加入 RDMA Perftest 与 NCCL All-Reduce。

### 第 5 层：真实框架

使用生产 PyTorch/JAX 镜像完成：

- 分配张量并执行 Kernel；
- 单机多卡 Collective；
- 多机训练短跑；
- 模型加载和推理；
- Checkpoint 保存和恢复。

## 12. 健康与自动隔离

需要区分：

- 瞬时应用错误；
- GPU XID/ECC/Row Remap 等设备错误；
- PCIe/NVLink/NIC 故障；
- 驱动或 DaemonSet 异常；
- 节点 OS、内存、磁盘问题。

自动化流程可以是：

```text
检测异常
  → 标记设备或节点不可调度
  → 停止新工作负载准入
  → 保存证据和诊断
  → 尝试受控恢复/重启
  → 运行节点验收
  → 恢复调度或进入维修
```

不要让控制器无限重启一个存在硬件故障的长训练。

## 13. 升级流程

1. 冻结目标版本矩阵；
2. 在相同硬件的实验节点验证；
3. 对 Canary 节点 cordon、drain；
4. 升级 OS/内核/驱动/Operator；
5. 执行五层验收；
6. 运行代表性训练和推理基准；
7. 观察错误、性能和功耗；
8. 按故障域逐批推广；
9. 保留旧节点镜像与回滚路径。

驱动变更可能改变性能，即使 API 完全兼容，也必须与历史基准比较。

## 14. 节点验收记录模板

```text
Node:
Hardware SKU / Serial:
BMC / BIOS / GPU / NIC firmware:
OS / kernel:
containerd / kubelet:
GPU driver / CUDA compatibility:
GPU Operator / Device Plugin or DRA:
NIC / RDMA driver:
GPU count and health:
PCIe / NVLink / NVSwitch:
DCGM diagnostics:
NCCL / RDMA / storage baseline:
Representative training:
Representative inference:
Result / evidence URI:
```

## 15. 生产检查清单

- [ ] 节点镜像、固件和 BIOS 有受控版本。
- [ ] 驱动和 Container Toolkit 只有一个权威安装来源。
- [ ] containerd、CDI、Device Plugin/DRA 分配路径经过验证。
- [ ] kubelet 为系统组件保留足够 CPU、内存和磁盘。
- [ ] NUMA、GPU、NIC 和 NVLink/PCIe 拓扑可查询。
- [ ] 本地模型缓存、镜像和日志不会耗尽磁盘。
- [ ] 五层验收可自动重复运行并保存证据。
- [ ] GPU 硬件故障能自动停止调度并进入维修流程。
- [ ] Canary 节点覆盖每种生产硬件。
- [ ] 升级验收包含真实性能回归。

## 延伸阅读

- [NVIDIA GPU Operator](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/)
- [NVIDIA GPU Operator Platform Support](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/platform-support.html)
- [AMD GPU Operator](https://instinct.docs.amd.com/projects/gpu-operator/en/latest/)
- [Container Device Interface](https://github.com/cncf-tags/container-device-interface)
- [Kubernetes Topology Manager](https://kubernetes.io/docs/tasks/administer-cluster/topology-manager/)
- [Kubernetes Node Allocatable](https://kubernetes.io/docs/tasks/administer-cluster/reserve-compute-resources/)
