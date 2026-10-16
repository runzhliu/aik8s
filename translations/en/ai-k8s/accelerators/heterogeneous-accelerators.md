---
title: "NVIDIA, AMD, Intel, TPU, and AI ASIC"
description: "Integration methods, differences, and selection boundaries for multi-vendor GPUs, TPUs, Gaudi, and cloud AI accelerators on Kubernetes"
status: evolving
last_reviewed: 2026-08-02
---

# NVIDIA, AMD, Intel, TPU, and AI ASIC

"GPU clusters" are often assumed by default to be equivalent to NVIDIA CUDA clusters, but a complete AI Kubernetes platform should also understand AMD ROCm, Intel GPU/Gaudi, Google TPU, AWS Trainium/Inferentia, and other devices. Kubernetes can unify lifecycle and resource declaration, but it cannot erase differences in compilers, runtimes, communication libraries, and model compatibility.

## 1. Unified Layer and Non-Unified Layer

### What Kubernetes Can Unify

- Node, Pod, Job, and controller lifecycle;
- Namespace, RBAC, queues, and quotas;
- Device Plugin or DRA resource allocation;
- CNI, CSI, Service, and Gateway;
- Logs, metrics, GitOps, and policies;
- Workload status and cost attribution.

### What Kubernetes Cannot Automatically Unify

- CUDA, ROCm, oneAPI, SynapseAI, Neuron, XLA;
- NCCL, RCCL, HCCL, EFA, and TPU ICI;
- Model support, kernel coverage, and quantization formats;
- Device memory, interconnect topology, and parallel strategies;
- Driver, firmware, compiler, and framework versions;
- Cloud vendor capacity, reservation, and topology semantics.

Therefore, the platform API can expose an abstract `acceleratorClass`, but the underlying runtime, images, and acceptance must be maintained per vendor.

## 2. Ecosystem Comparison

| Platform | Kubernetes Integration | Primary Software Stack | Typical Communication | Key Characteristics |
| --- | --- | --- | --- | --- |
| NVIDIA GPU | GPU Operator, Device Plugin, DRA | CUDA, cuDNN, NCCL, TensorRT | NVLink/NVSwitch, NCCL, GPUDirect | Broadest tool and framework coverage |
| AMD Instinct | AMD GPU Operator, Device Plugin, DRA | ROCm, MIOpen, RCCL | Infinity Fabric, RCCL, RDMA | Large GPU memory and open software stack; compatibility requires per-model validation |
| Intel GPU | Intel Device Plugins Operator | oneAPI, Level Zero, OpenVINO | oneCCL, Xe Link | Unified plugin ecosystem for GPU/media/general-purpose accelerators |
| Intel Gaudi | Gaudi Device Plugin | SynapseAI, PyTorch/Habana | HCCL, Ethernet/RDMA | Dedicated accelerator for training and inference |
| Google TPU | GKE TPU Slice/device resources | XLA, JAX, PyTorch/XLA | ICI, Collectives | Topology expressed as slices, deeply integrated with GKE lifecycle |
| AWS Trainium/Inferentia | Neuron Device Plugin or DRA | Neuron SDK, NxD | NeuronLink, EFA | Tightly bound to EKS, instance topology, and compilation cache |

Tools and support status change quickly; selection should be based on the official compatibility matrix of the target version and real model benchmarks.

## 3. NVIDIA GPU

Typical resource names:

```yaml
resources:
  limits:
    nvidia.com/gpu: "1"
```

Common platform components:

- NVIDIA GPU Operator;
- NVIDIA Container Toolkit;
- Device Plugin or NVIDIA DRA Driver;
- GPU Feature Discovery / NFD;
- DCGM Exporter;
- MIG Manager;
- Network Operator, OFED, and RDMA components;
- NIM Operator, Dynamo, and other optional inference components.

The advantage is rich frameworks, images, diagnostics, monitoring, and community examples. The cost is a complex version matrix; GPU Operator, drivers, CUDA, NCCL, kernel, and hardware generations still require strict validation.

## 4. AMD Instinct and ROCm

The AMD GPU Operator can manage drivers, Device Plugin, node labels, metrics, health, and DRA. The traditional resource is typically:

```yaml
resources:
  limits:
    amd.com/gpu: "1"
```

Key validation points:

- Target GPU model and ROCm version;
- ROCm builds of PyTorch/JAX/vLLM/SGLang;
- RCCL and network topology;
- Flash Attention, quantization, and custom kernel coverage;
- `gfx` target of container images;
- Partition modes, health tests, and metric semantics.

Do not treat swapping the base image of a CUDA image as completing the migration. Custom CUDA extensions, NCCL parameters, and monitoring queries usually all need adjustment.

References: [AMD GPU Operator](https://instinct.docs.amd.com/projects/gpu-operator/en/latest/), [AMD DRA Driver](https://instinct.docs.amd.com/projects/gpu-operator/en/main/dra/dra-driver.html)

## 5. Intel GPU and Gaudi

The Intel Device Plugins Operator can manage GPU, NPU, QAT, SGX, DSA, and other plugins. For Intel GPUs, pay attention to:

- Level Zero/oneAPI Runtime;
- Drivers and container device nodes;
- Resource naming for integrated and discrete GPUs;
- OpenVINO, PyTorch XPU, and target frameworks;
- Xe Link and multi-device communication.

Intel Gaudi uses a separate Gaudi Device Plugin and the SynapseAI software stack. The platform should treat Gaudi as an independent accelerator flavor, maintaining dedicated images, HCCL networks, and framework versions, and not share the same runtime with Intel general-purpose GPUs.

References: [Intel Device Plugins](https://intel.github.io/intel-device-plugins-for-kubernetes/README.html), [Intel Gaudi Device Plugin](https://docs.habana.ai/en/latest/Installation_Guide/Additional_Installation/Kubernetes_Installation/Intel_Gaudi_Kubernetes_Device_Plugin.html)

## 6. Google TPU

GKE organizes devices by TPU slice and topology. Single-host and multi-host slices have different scaling behaviors; multi-host slices typically need to be created atomically with the full topology or scaled to zero.

Workloads typically request specific versions and topologies through node selectors and TPU resource declarations:

```yaml
spec:
  nodeSelector:
    cloud.google.com/gke-tpu-accelerator: tpu-v5-lite-podslice
    cloud.google.com/gke-tpu-topology: 2x4
```

Design considerations:

- TPU version, slice topology, and availability zone;
- JAX/XLA or PyTorch/XLA software stack;
- Whether multi-host jobs scale as a whole;
- Compilation cache and program startup time;
- TPU reservation, preemption, and capacity waiting;
- Data path and checkpoints.

References: [Plan TPUs in GKE](https://cloud.google.com/kubernetes-engine/docs/concepts/plan-tpus), [Deploy TPU Workloads](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/tpus)

## 7. AWS Trainium and Inferentia

AWS Neuron devices can be exposed as extended resources through Device Plugin, or use the Neuron DRA Driver on applicable EKS versions and node types.

Device Plugin resource example:

```yaml
resources:
  requests:
    aws.amazon.com/neuron: "1"
  limits:
    aws.amazon.com/neuron: "1"
```

Neuron DRA can express device attributes, connection subsets, Logical NeuronCores, and EFA topology. Note the combination limitations of DRA with Karpenter/EKS Auto Mode; refer to the target EKS documentation.

Also manage:

- Neuron Compiler and Runtime versions;
- Precompiled model artifacts and cache;
- Trn/Inf instance topology and NeuronLink;
- EFA and distributed training;
- Model operator coverage and numerical quality;
- Compilation time in the release pipeline, not online cold start.

References: [EKS Hardware Device Management](https://docs.aws.amazon.com/eks/latest/userguide/device-management.html), [EKS Neuron Devices](https://docs.aws.amazon.com/eks/latest/userguide/device-management-neuron.html)

## 8. CPU, NPU, and Edge Accelerators

Not all inference requires data center GPUs. Small models, embeddings, rerankers, speech, and edge tasks may also use:

- AVX, AMX, SVE on x86/ARM CPUs;
- Intel/AMD integrated GPUs;
- NPU, VPU, FPGA;
- Jetson and other SoCs;
- Cloud inference ASICs.

Such devices may be integrated via Device Plugin, DRA, RuntimeClass, or vendor Operators. The platform should still use the same acceptance framework: inventory, isolation, model compatibility, performance, failure, and observability.

## 9. Platform Abstraction Approach

Do not make users memorize all underlying labels and resource names directly. Provide a controlled flavor:

```yaml
acceleratorClass: high-memory-training
count: 8
capabilities:
  minMemoryGiB: 80
  highSpeedCollective: true
  precision:
    - bf16
```

The platform maps it to validated concrete implementations, such as H100, MI300X, or TPU slices. However, the following cases should not be silently replaced:

- The model only supports a specific vendor's kernels;
- Checkpoint or quantization artifacts are bound to hardware;
- Target quality and performance benchmarks differ;
- Parallel topology requires specific interconnects;
- License or compliance requirements restrict hardware.

Abstraction should reduce repetitive configuration, not hide the fact that hardware is not interchangeable.

## 10. Portable Image Strategy

Common approaches:

1. Maintain separate images for each hardware type;
2. Share upper-layer code, produce different runtimes through multi-stage builds;
3. Associate the same model version with multiple hardware artifacts;
4. Record device, framework, driver, and compilation target in release metadata;
5. Use the same evaluation set to compare correctness and performance.

Image naming example:

```text
trainer:2026.08-cuda
trainer:2026.08-rocm
trainer:2026.08-neuron
```

Production deployments still use digests; tags are only for human identification.

## 11. Cross-Hardware Benchmarking Method

Must be fixed:

- Model and weight revision;
- Precision, quantization, and compilation options;
- Input/output distribution, batch, and concurrency;
- Target quality;
- Device count, topology, and host resources;
- Software stack versions;
- Warm-up, duration, and statistical methodology;
- Power consumption and total cost.

Training compares time-to-quality, not just samples/s; inference compares TTFT, TPOT, throughput, quality, and per-token cost simultaneously.

## 12. Monitoring: Unified and Differentiated

The platform layer can unify the following dimensions:

- Allocated device count and runtime;
- Job/Pod/model/tenant labels;
- Temperature, power, memory, utilization, and errors;
- Queue waiting, failures, and retries;
- Training throughput and inference token metrics.

But underlying metric names and error codes are determined by vendors. Build a normalized dashboard while preserving raw vendor metrics and diagnostic evidence.

## 13. Selection Order

1. Confirm production support for the target model and framework;
2. Validate numerical quality and functional completeness;
3. Run end-to-end performance tests with real workloads;
4. Evaluate device availability, reservation, and lead time;
5. Evaluate network, storage, and node operations capabilities;
6. Calculate full three-year cost, not single-card price;
7. Check observability, upgrades, failure, and vendor support;
8. Use canary workloads to continuously prevent regression.

## 14. Production Checklist

- [ ] The platform does not write all accelerators as `nvidia.com/gpu`.
- [ ] Each hardware type has an independent support matrix, runtime images, and acceptance tests.
- [ ] Device Plugin/DRA, node labels, and partitioning policies have clear authoritative sources.
- [ ] Models and quantization artifacts are labeled with target hardware and software stack.
- [ ] Cross-hardware comparisons bind the same quality targets and real workloads.
- [ ] Monitoring provides both unified views and raw vendor diagnostics.
- [ ] Capacity models consider topology, reservation, availability zones, and delivery risk.
- [ ] The abstraction layer does not silently replace non-interchangeable hardware.
- [ ] Upgrades and rollbacks are validated independently on each hardware type.
- [ ] Business teams know which device type their workloads actually run on.

## Further Reading

- [Kubernetes Device Plugins](https://kubernetes.io/docs/concepts/extend-kubernetes/compute-storage-net/device-plugins/)
- [NVIDIA Cloud Native Technologies](https://docs.nvidia.com/datacenter/cloud-native/)
- [AMD GPU Operator](https://instinct.docs.amd.com/projects/gpu-operator/en/latest/)
- [Intel Device Plugins](https://intel.github.io/intel-device-plugins-for-kubernetes/README.html)
- [Google Cloud TPU in GKE](https://docs.cloud.google.com/kubernetes-engine/docs/concepts/tpus)
- [Amazon EKS Device Management](https://docs.aws.amazon.com/eks/latest/userguide/device-management.html)
