---
title: LLM 推理引擎选型
description: 对比 vLLM、SGLang、TensorRT-LLM、Triton、llama.cpp 等引擎的能力、边界和 Kubernetes 集成方式
status: evolving
last_reviewed: 2026-08-02
---

# LLM 推理引擎选型

推理引擎负责加载模型、管理 GPU 内存、组织 Batch、执行 Kernel 并输出 Token；KServe、Kubernetes 和 Gateway 负责的是服务生命周期、资源与流量。选择引擎前必须先分清这些边界。

## 一、推理平台分层

```text
API Client
  OpenAI / KServe V2 / gRPC
        │
Gateway 与请求调度
  Auth、Quota、Rate Limit、InferencePool、KV-aware Routing
        │
服务控制面
  Deployment、KServe、Ray Serve、LWS、llm-d、Dynamo
        │
推理引擎
  vLLM、SGLang、TensorRT-LLM、Triton、llama.cpp
        │
模型与硬件
  safetensors/GGUF/Engine、GPU/TPU/ASIC、KV Cache、网络
```

KServe 和 vLLM 通常是组合关系；llm-d/Dynamo 也可能在多个引擎之上提供分布式运行、路由和 KV 传输。

## 二、先定义需求

至少明确：

- 文本、Embedding、Reranker、语音、视觉还是多模态；
- 模型、参数量、Dense/MoE 和 Context 上限；
- 目标硬件、单机还是多机；
- 精度和量化约束；
- 在线、批量或混合流量；
- TTFT、TPOT、吞吐和可用性 SLO；
- LoRA、结构化输出、Tool Calling、投机解码需求；
- Prefix Cache、KV Offload、P/D 分离需求；
- OpenAI API、KServe V2、gRPC 等协议；
- 许可证、支持和升级策略。

没有负载画像时，“哪个引擎最快”没有可操作答案。

## 三、主要引擎对比

| 引擎 | 核心定位 | 优势 | 主要代价 |
| --- | --- | --- | --- |
| vLLM | 通用高吞吐 LLM 服务 | 活跃生态、OpenAI API、Paged KV、广泛模型/硬件、控制面集成多 | 功能演进快，版本和模型组合需锁定 |
| SGLang | LLM/多模态与复杂推理程序 | Radix/Prefix Cache、结构化生成、复杂共享前缀、活跃性能优化 | 生产参数和版本变化快，需要独立基准 |
| TensorRT-LLM | NVIDIA 极致优化 | NVIDIA Kernel、量化、并行和投机解码深度优化 | 构建/兼容复杂，硬件和软件绑定更强 |
| Triton | 多框架统一推理服务器 | Model Repository、动态/序列 Batch、多 Backend、统一协议和指标 | 不是所有 LLM 高级能力的最短路径 |
| llama.cpp | 轻量本地与边缘推理 | GGUF、CPU/多后端、部署简单、资源要求低 | 大规模数据中心服务和控制面能力有限 |
| TGI | Hugging Face 模型服务 | Hub 集成、OpenAI 兼容、部署直接 | 与新引擎能力重叠，选型前确认活跃功能与硬件支持 |
| 自定义 PyTorch/JAX | 特殊模型或研究能力 | 控制完全 | 自己承担 Batch、内存、协议、指标和故障处理 |

表格只表达定位。模型覆盖和硬件矩阵变化很快，最终以目标版本官方文档和基准为准。

## 四、vLLM

适合：

- 通用 Chat/Completion/Embedding 服务；
- 需要 OpenAI-Compatible API；
- 希望接入 KServe、Ray、llm-d 或常见 Gateway；
- 需要连续批处理、Prefix Cache、LoRA、量化和多种并行；
- 使用 NVIDIA、AMD、TPU、CPU 等受支持后端。

需要验证：

- 目标模型架构与 Attention Backend；
- `max-model-len` 和 KV Cache 容量；
- Tensor/Pipeline/Data/Expert Parallel 组合；
- 量化格式在目标硬件上的 Kernel；
- Chunked Prefill、Prefix Cache 和投机解码交互；
- 多模态、结构化输出和 LoRA 限制；
- 引擎指标和升级兼容。

单机概念示例：

```bash
vllm serve /models/example \
  --served-model-name example \
  --tensor-parallel-size 4 \
  --max-model-len 32768 \
  --enable-prefix-caching
```

参数不能直接从博客复制到生产。先用目标模型和请求分布建立基线。

参考：[vLLM Documentation](https://docs.vllm.ai/)

## 五、SGLang

SGLang 的核心特点包括 RadixAttention/Prefix Cache、结构化生成、并行和面向复杂 LLM/多模态工作负载的运行时。

优先评估场景：

- 大量请求共享 System Prompt 或长前缀；
- Agent、结构化输出和多轮推理；
- 需要复杂 Cache-aware Scheduling；
- 希望在 NVIDIA、AMD、TPU 等受支持后端运行；
- 评估 P/D 分离或大规模多机推理。

重点验证：

- Radix Cache 命中和内存开销；
- Cache 与负载均衡的亲和；
- 结构化输出对吞吐的影响；
- 目标模型、量化、硬件 Backend；
- SGLang 与 llm-d/Dynamo 等控制面的兼容版本；
- 请求取消、滚动发布和缓存清理。

参考：[SGLang Documentation](https://docs.sglang.io/)

## 六、TensorRT-LLM

适合追求 NVIDIA 平台极限性能并能承担构建与验证复杂度的团队。能力通常包括：

- 多种低精度和量化；
- In-flight Batching；
- Paged KV Cache；
- Tensor/Pipeline/Expert Parallel；
- 投机解码；
- 多节点和分离式推理；
- 与 Triton、Dynamo、NIM 等 NVIDIA 栈集成。

主要风险：

- Engine/Artifact 可能绑定 GPU 架构、TensorRT-LLM 和构建配置；
- 模型转换和编译进入供应链；
- 新模型支持可能晚于通用框架；
- 性能最优参数随 GPU 代际变化；
- 回滚需要同时保留旧 Engine 和 Runtime。

参考：[TensorRT-LLM Documentation](https://nvidia.github.io/TensorRT-LLM/latest/)

## 七、Triton Inference Server

Triton 适合统一传统 ML/DL、多模型和多 Backend：

- TensorRT、ONNX Runtime、PyTorch、Python 等 Backend；
- Model Repository 与版本策略；
- HTTP/gRPC 和 KServe Protocol；
- Dynamic Batching、Sequence Batching；
- 多 Model Instance；
- Model Management、Metrics 和 Trace；
- Ensemble 和前后处理。

Triton 可以承载 LLM Backend，但如果目标是最新的 Prefix Cache、P/D 分离或复杂 LLM 路由，应比较直接使用 vLLM/SGLang/TensorRT-LLM 或其 Triton Backend 的实际能力与运维复杂度。

参考：[Triton Architecture](https://docs.nvidia.com/deeplearning/triton-inference-server/user-guide/docs/user_guide/architecture.html)

## 八、llama.cpp 与边缘运行时

适合：

- CPU、消费级 GPU、Apple Silicon 或边缘设备；
- GGUF 量化模型；
- 单机、小规模和离线场景；
- 对依赖和部署体积敏感的环境。

在 Kubernetes 上仍要解决：

- 节点能力标签；
- 模型文件分发；
- 本地盘和边缘弱网；
- CPU/内存/线程亲和；
- API、探针、更新和回滚；
- 多副本负载均衡。

不要因为 Runtime 轻量，就跳过模型版本和质量回归。

## 九、多引擎 Runtime Catalog

平台可以维护一组经过验证的 Runtime：

| Runtime ID | 引擎 | 硬件 | 适用模型 | 状态 |
| --- | --- | --- | --- | --- |
| vllm-cuda-stable | vLLM | NVIDIA Ampere+ | 通用 Decoder LLM | stable |
| sglang-cuda-prefix | SGLang | NVIDIA Hopper | 共享长前缀 | canary |
| trtllm-hopper-fp8 | TensorRT-LLM | H100/H200 | 已编译 FP8 模型 | stable |
| vllm-rocm | vLLM ROCm | AMD Instinct | 验证列表内模型 | canary |
| llama-cpu | llama.cpp | x86/ARM | GGUF 小模型 | stable |

每个 Runtime 记录：镜像 Digest、驱动/CUDA/ROCm、引擎版本、支持模型、量化、最大上下文、已知限制、基准和下线日期。

## 十、Kubernetes Deployment 基线

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: llm-server
spec:
  replicas: 1
  selector:
    matchLabels:
      app: llm-server
  template:
    metadata:
      labels:
        app: llm-server
    spec:
      terminationGracePeriodSeconds: 120
      containers:
        - name: server
          image: registry.example.com/ai/vllm@sha256:replace
          args:
            - serve
            - /models/example
            - --served-model-name=example
          ports:
            - name: http
              containerPort: 8000
          readinessProbe:
            httpGet:
              path: /health
              port: http
            periodSeconds: 5
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

生产还需要模型卷、`/dev/shm`、安全上下文、ServiceAccount、NetworkPolicy、PDB、Service、Gateway、指标和优雅终止。

## 十一、Readiness 与启动探针

模型下载和加载可能很久，建议区分：

- Startup Probe：允许进程和模型完成初始化；
- Liveness Probe：检测进程是否卡死；
- Readiness Probe：模型和引擎是否能安全接收流量。

Readiness 应覆盖目标模型存在、Engine Worker 健康和必要分布式 Peer 就绪。端口监听不能证明模型已加载。

## 十二、优雅终止

滚动升级时：

1. 从 Endpoint/InferencePool 移除；
2. 停止接收新请求；
3. 允许流式和长请求完成或返回可识别错误；
4. 清理 P/D、KV 和分布式连接；
5. 在宽限期内退出；
6. 超时才强制终止。

需要验证客户端取消、SIGTERM、preStop 和 Gateway Endpoint 更新顺序。

## 十三、引擎选择实验

用同一模型和硬件对候选引擎执行：

1. 功能兼容测试；
2. 离线质量回归；
3. 单请求 TTFT/TPOT；
4. 不同并发下吞吐和尾延迟；
5. 长短输入混合和突发流量；
6. 模型冷启动；
7. OOM、取消、重启和滚动升级；
8. 指标、Trace 和日志完整性；
9. 单位 Token 成本和功耗；
10. 版本升级兼容。

## 十四、常见错误

- 只看厂商公布的峰值 Token/s；
- 不固定模型 Revision、量化和请求分布；
- 把引擎和服务控制面视为互斥产品；
- 同时开启所有优化而无法定位回归；
- 使用 `latest` 镜像和模型 Tag；
- Readiness 只检查端口；
- 让一个 Runtime 支持所有模型而没有兼容矩阵；
- 忽略取消、滚动升级和长连接。

## 十五、生产检查清单

- [ ] 引擎选择基于目标模型、硬件和真实请求分布。
- [ ] Runtime Catalog 固定镜像 Digest 和兼容矩阵。
- [ ] 模型质量与性能使用同一制品版本回归。
- [ ] Readiness 表示模型真正可以接流量。
- [ ] 冷启动拆分为下载、加载、编译和预热。
- [ ] 流式请求、取消和 SIGTERM 行为经过验证。
- [ ] 多机引擎由 LWS/控制面整体管理。
- [ ] Gateway、KServe 和引擎职责没有重叠写入。
- [ ] 指标包含 TTFT、TPOT、队列、Token 和 KV Cache。
- [ ] 升级能回滚模型、引擎和配置三部分。

## 延伸阅读

- [vLLM Documentation](https://docs.vllm.ai/)
- [SGLang Documentation](https://docs.sglang.io/)
- [TensorRT-LLM Documentation](https://nvidia.github.io/TensorRT-LLM/latest/)
- [Triton Inference Server](https://docs.nvidia.com/deeplearning/triton-inference-server/user-guide/docs/)
- [KServe Serving Runtimes](https://kserve.github.io/website/docs/concepts/resources/servingruntime)
