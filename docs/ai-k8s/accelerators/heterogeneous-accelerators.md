---
title: NVIDIA、AMD、Intel、TPU 与 AI ASIC
description: Kubernetes 上多厂商 GPU、TPU、Gaudi 和云端 AI 加速器的接入方式、差异与选型边界
status: evolving
last_reviewed: 2026-08-02
---

# NVIDIA、AMD、Intel、TPU 与 AI ASIC

“GPU 集群”经常被默认等同于 NVIDIA CUDA 集群，但完整的 AI Kubernetes 平台还应理解 AMD ROCm、Intel GPU/Gaudi、Google TPU、AWS Trainium/Inferentia 等设备。Kubernetes 可以统一生命周期和资源声明，却不能抹平编译器、运行时、通信库和模型兼容差异。

## 一、统一层与非统一层

### Kubernetes 可以统一

- 节点、Pod、Job 和控制器生命周期；
- Namespace、RBAC、队列和配额；
- Device Plugin 或 DRA 资源分配；
- CNI、CSI、Service 和 Gateway；
- 日志、指标、GitOps 和策略；
- 工作负载状态与成本归属。

### Kubernetes 不能自动统一

- CUDA、ROCm、oneAPI、SynapseAI、Neuron、XLA；
- NCCL、RCCL、HCCL、EFA 和 TPU ICI；
- 模型支持、Kernel 覆盖和量化格式；
- 设备内存、互联拓扑和并行策略；
- 驱动、固件、编译器和框架版本；
- 云厂商的容量、预留和拓扑语义。

因此平台 API 可以暴露抽象的 `acceleratorClass`，但底层 Runtime、镜像和验收必须按厂商维护。

## 二、生态对比

| 平台 | Kubernetes 接入 | 主要软件栈 | 典型通信 | 主要特点 |
| --- | --- | --- | --- | --- |
| NVIDIA GPU | GPU Operator、Device Plugin、DRA | CUDA、cuDNN、NCCL、TensorRT | NVLink/NVSwitch、NCCL、GPUDirect | 工具和框架覆盖最广 |
| AMD Instinct | AMD GPU Operator、Device Plugin、DRA | ROCm、MIOpen、RCCL | Infinity Fabric、RCCL、RDMA | 大显存和开放软件栈，兼容需逐模型验证 |
| Intel GPU | Intel Device Plugins Operator | oneAPI、Level Zero、OpenVINO | oneCCL、Xe Link | GPU/媒体/通用加速器统一插件生态 |
| Intel Gaudi | Gaudi Device Plugin | SynapseAI、PyTorch/Habana | HCCL、以太网/RDMA | 面向训练与推理的专用加速器 |
| Google TPU | GKE TPU Slice/设备资源 | XLA、JAX、PyTorch/XLA | ICI、Collectives | 拓扑以 Slice 表达，与 GKE 生命周期深度集成 |
| AWS Trainium/Inferentia | Neuron Device Plugin 或 DRA | Neuron SDK、NxD | NeuronLink、EFA | 与 EKS、实例拓扑和编译缓存紧密绑定 |

工具和支持状态变化很快，选型时应以目标版本的官方兼容矩阵和真实模型基准为准。

## 三、NVIDIA GPU

典型资源名：

```yaml
resources:
  limits:
    nvidia.com/gpu: "1"
```

常见平台组件：

- NVIDIA GPU Operator；
- NVIDIA Container Toolkit；
- Device Plugin 或 NVIDIA DRA Driver；
- GPU Feature Discovery / NFD；
- DCGM Exporter；
- MIG Manager；
- Network Operator、OFED 和 RDMA 组件；
- NIM Operator、Dynamo 等可选推理组件。

优点是框架、镜像、诊断、监控和社区示例丰富。代价是版本矩阵复杂，GPU Operator、驱动、CUDA、NCCL、内核和硬件代际仍需严格验证。

## 四、AMD Instinct 与 ROCm

AMD GPU Operator 能管理驱动、Device Plugin、节点标签、指标、健康和 DRA。传统资源通常为：

```yaml
resources:
  limits:
    amd.com/gpu: "1"
```

重点验证：

- 目标 GPU 型号和 ROCm 版本；
- PyTorch/JAX/vLLM/SGLang 的 ROCm 构建；
- RCCL 与网络拓扑；
- Flash Attention、量化和自定义 Kernel 覆盖；
- 容器镜像的 `gfx` 目标；
- 分区模式、健康测试和指标语义。

不要把 CUDA 镜像换一个基础镜像就视为完成迁移。自定义 CUDA Extension、NCCL 参数和监控查询通常都要调整。

参考：[AMD GPU Operator](https://instinct.docs.amd.com/projects/gpu-operator/en/latest/)、[AMD DRA Driver](https://instinct.docs.amd.com/projects/gpu-operator/en/main/dra/dra-driver.html)

## 五、Intel GPU 与 Gaudi

Intel Device Plugins Operator 可以管理 GPU、NPU、QAT、SGX、DSA 等插件。Intel GPU 需要关注：

- Level Zero/oneAPI Runtime；
- 驱动和容器设备节点；
- 集成 GPU 与独立 GPU 的资源命名；
- OpenVINO、PyTorch XPU 和目标框架；
- Xe Link 和多设备通信。

Intel Gaudi 使用独立的 Gaudi Device Plugin 和 SynapseAI 软件栈。平台应把 Gaudi 视为独立 Accelerator Flavor，维护专用镜像、HCCL 网络和框架版本，不与 Intel 通用 GPU 混用同一 Runtime。

参考：[Intel Device Plugins](https://intel.github.io/intel-device-plugins-for-kubernetes/README.html)、[Intel Gaudi Device Plugin](https://docs.habana.ai/en/latest/Installation_Guide/Additional_Installation/Kubernetes_Installation/Intel_Gaudi_Kubernetes_Device_Plugin.html)

## 六、Google TPU

GKE 以 TPU Slice 和拓扑组织设备。单主机与多主机 Slice 的扩缩容行为不同，多主机 Slice 通常需要按完整拓扑原子创建或缩到零。

工作负载通常通过节点选择器和 TPU 资源声明请求具体版本和拓扑：

```yaml
spec:
  nodeSelector:
    cloud.google.com/gke-tpu-accelerator: tpu-v5-lite-podslice
    cloud.google.com/gke-tpu-topology: 2x4
```

设计时关注：

- TPU 版本、Slice 拓扑和可用区；
- JAX/XLA 或 PyTorch/XLA 软件栈；
- 多主机任务是否整体扩容；
- 编译缓存和程序启动时间；
- TPU 预留、抢占和容量等待；
- 数据路径与 Checkpoint。

参考：[Plan TPUs in GKE](https://cloud.google.com/kubernetes-engine/docs/concepts/plan-tpus)、[Deploy TPU Workloads](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/tpus)

## 七、AWS Trainium 与 Inferentia

AWS Neuron 设备可以通过 Device Plugin 暴露为扩展资源，也可以在适用的 EKS 版本和节点类型上使用 Neuron DRA Driver。

Device Plugin 资源示例：

```yaml
resources:
  requests:
    aws.amazon.com/neuron: "1"
  limits:
    aws.amazon.com/neuron: "1"
```

Neuron DRA 可以表达设备属性、连接子集、Logical NeuronCore 和 EFA 拓扑。需要注意 DRA 与 Karpenter/EKS Auto Mode 的组合限制，以目标 EKS 文档为准。

还应管理：

- Neuron Compiler 和 Runtime 版本；
- 预编译模型 Artifact 与缓存；
- Trn/Inf 实例拓扑和 NeuronLink；
- EFA 与分布式训练；
- 模型算子覆盖和数值质量；
- 编译时间进入发布流水线，而不是在线冷启动。

参考：[EKS Hardware Device Management](https://docs.aws.amazon.com/eks/latest/userguide/device-management.html)、[EKS Neuron Devices](https://docs.aws.amazon.com/eks/latest/userguide/device-management-neuron.html)

## 八、CPU、NPU 与边缘加速器

并非所有推理都需要数据中心 GPU。小模型、Embedding、Reranker、语音和边缘任务还可能使用：

- x86/ARM CPU 的 AVX、AMX、SVE；
- Intel/AMD 集成 GPU；
- NPU、VPU、FPGA；
- Jetson 和其他 SoC；
- 云端推理 ASIC。

这类设备可能通过 Device Plugin、DRA、RuntimeClass 或厂商 Operator 接入。平台仍应使用相同验收框架：库存、隔离、模型兼容、性能、故障和可观测。

## 九、平台抽象方式

不要让用户直接记住所有底层标签和资源名。可以提供受控的 Flavor：

```yaml
acceleratorClass: high-memory-training
count: 8
capabilities:
  minMemoryGiB: 80
  highSpeedCollective: true
  precision:
    - bf16
```

平台将它映射到已验证的具体实现，例如 H100、MI300X 或 TPU Slice。但以下情况不应静默替换：

- 模型只支持某厂商 Kernel；
- Checkpoint 或量化 Artifact 与硬件绑定；
- 目标质量和性能基准不同；
- 并行拓扑需要特定互联；
- 许可证或合规要求限制硬件。

抽象应该减少重复配置，而不是隐藏不可互换的事实。

## 十、可移植镜像策略

常见方式：

1. 每种硬件维护独立镜像；
2. 共享上层代码，通过多阶段构建产生不同 Runtime；
3. 同一模型版本关联多个硬件 Artifact；
4. 在发布元数据中记录设备、框架、驱动和编译目标；
5. 使用相同评估集比较正确性与性能。

镜像命名示例：

```text
trainer:2026.08-cuda
trainer:2026.08-rocm
trainer:2026.08-neuron
```

生产部署仍使用 Digest，Tag 只用于人类识别。

## 十一、跨硬件基准方法

必须固定：

- 模型和权重 Revision；
- 精度、量化和编译选项；
- 输入/输出分布、Batch 和并发；
- 目标质量；
- 设备数量、拓扑和主机资源；
- 软件栈版本；
- 预热、持续时间和统计口径；
- 功耗与完整成本。

训练比较 Time-to-Quality，不只看 samples/s；推理同时比较 TTFT、TPOT、吞吐、质量和单位 Token 成本。

## 十二、监控的统一与差异

平台层可以统一以下维度：

- 分配设备数与运行时间；
- Job/Pod/模型/租户标签；
- 温度、功耗、内存、利用率和错误；
- 队列等待、失败和重试；
- 训练吞吐和推理 Token 指标。

但底层指标名称和错误码由厂商决定。应建立归一化 Dashboard，同时保留原始厂商指标和诊断证据。

## 十三、选型顺序

1. 确认目标模型和框架的生产支持；
2. 验证数值质量和功能完整性；
3. 根据真实负载做端到端性能测试；
4. 评估设备可获得性、预留和交付周期；
5. 评估网络、存储和节点运维能力；
6. 计算完整三年成本而非单卡价格；
7. 检查可观测、升级、故障和供应商支持；
8. 用 Canary 工作负载持续防止回归。

## 十四、生产检查清单

- [ ] 平台没有把所有加速器都写成 `nvidia.com/gpu`。
- [ ] 每种硬件有独立支持矩阵、Runtime 镜像和验收测试。
- [ ] Device Plugin/DRA、节点标签和分区策略有明确权威来源。
- [ ] 模型和量化 Artifact 标注目标硬件与软件栈。
- [ ] 跨硬件比较绑定相同质量目标和真实工作负载。
- [ ] 监控同时提供统一视图和厂商原始诊断。
- [ ] 容量模型考虑拓扑、预留、可用区和交付风险。
- [ ] 抽象层不会把不可互换的硬件静默替换。
- [ ] 升级和回滚在每种硬件上独立验证。
- [ ] 业务团队知道其工作负载实际运行在哪类设备上。

## 延伸阅读

- [Kubernetes Device Plugins](https://kubernetes.io/docs/concepts/extend-kubernetes/compute-storage-net/device-plugins/)
- [NVIDIA Cloud Native Technologies](https://docs.nvidia.com/datacenter/cloud-native/)
- [AMD GPU Operator](https://instinct.docs.amd.com/projects/gpu-operator/en/latest/)
- [Intel Device Plugins](https://intel.github.io/intel-device-plugins-for-kubernetes/README.html)
- [Google Cloud TPU in GKE](https://docs.cloud.google.com/kubernetes-engine/docs/concepts/tpus)
- [Amazon EKS Device Management](https://docs.aws.amazon.com/eks/latest/userguide/device-management.html)
