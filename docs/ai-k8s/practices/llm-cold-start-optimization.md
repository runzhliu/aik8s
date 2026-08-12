---
title: 从半小时到五分钟：大模型冷启动全链路优化
description: 从 DeepSeek-V4-Pro 滚动重启接近半小时的真实问题出发，按启动关键路径拆解怎样将 H20 节点缓存重启优化到五分钟量级，以及模型缓存、权重加载、JIT、CUDA Graph 与热恢复的工程取舍
status: exploratory
last_reviewed: 2026-08-12
---

# 从半小时到五分钟：大模型冷启动全链路优化

今年上半年部署 DeepSeek-V4-Pro 时，我们遇到过一个无法回避的问题：**一次模型滚动重启接近半小时**。

正常发布时，旧副本还能继续承接流量；如果服务已经整体不可用，这半小时就是故障恢复时间。对于已经接入真实业务的推理服务，这几乎无法接受。

最初我们把问题归因于模型下载。模型提前下到 GPU 节点以后，下载时间确实消失了，Engine 却仍要等待数分钟才能服务。后来在约 156 GiB 的 DeepSeek V4 Flash 上逐段打点，才确认冷启动是一条连续的关键路径：

```text
调度与镜像
  → 模型准备
  → Checkpoint 读取、转换与 GPU 搬运
  → 通信和显存初始化
  → Kernel JIT、Autotune 与 CUDA Graph
  → 真实请求验证
  → Gateway 接入流量
```

本文按这条路径回答三个问题：半小时花在哪里、每个阶段怎样优化，以及对 150 GiB 级模型可以设定什么样的现实目标。

![大模型从调度、模型准备到业务可用的冷启动全链路](../../assets/practices/llm-cold-start-optimization/01-cold-start-pipeline.png)

> 文中的集群名称、地址、镜像仓库、对象存储、模型路径和凭据均已删除或替换。时间来自特定软硬件组合，只用于说明量级与方法，不是生产容量承诺。

## 1. 先统一口径：我们到底在测什么

“启动只用了 10 秒”可能指完全不同的事情。讨论优化前，至少要区分四种状态：

| 口径 | 镜像 | 节点模型 | 编译缓存 | 进程与 GPU 状态 | 典型场景 |
| --- | --- | --- | --- | --- | --- |
| 完整冷启动 | 未命中 | 未命中 | 未命中 | 不存在 | 新节点扩容、灾难恢复 |
| 节点缓存重启 | 已命中 | 已命中 | 可命中 | 不存在 | Pod 重建、滚动发布 |
| 预热副本切换 | 已命中 | 已命中 | 已命中 | 已 Ready | 发布切流、容量保险 |
| 休眠或快照恢复 | 已命中或随快照恢复 | 已加载或保存 | 已编译 | 被保存或仍保留 | 秒级恢复实验 |

V4-Pro 接近半小时的经历接近完整冷启动。生产上首先要把“节点缓存重启”压到分钟级，再用预热副本保障故障切换；不能用快照恢复的秒级数字代替完整冷启动。

### 1.1 统一 T0–T9 计时边界

我们使用下面的阶段定义：

```text
T0  Deployment 或 Role revision 创建
T1  Pod 调度完成，开始准备 Runtime Image
T2  Init Container 开始准备模型
T3  模型完整性校验通过
T4  推理进程启动
T5  权重加载、转换与 H2D 完成
T6  JIT 和 Autotune 完成
T7  CUDA Graph 与内置 Warm-up 完成
T8  /health、/v1/models 和确定性生成请求通过
T9  Gateway 将副本加入可服务集合
```

端口开始监听、Kubernetes `Ready`、第一条请求成功以及 Gateway 开始分流，必须分开记录。

## 2. 基线：23 分钟到底花在哪里

一次 DeepSeek V4 Flash 完整冷启动提供了比较完整的证据：约 156 GiB 模型、48 个 Safetensors 分片、单节点 8×H20。

| 阶段 | 观测时间 | 结论 |
| --- | ---: | --- |
| 模型准备 | 约 6 分钟 | 有效吞吐约 0.43 GiB/s |
| 首次拉取约 14.29 GB Runtime Image | 约 127 秒 | 节点镜像未命中 |
| NCCL 初始化 | 约 19 秒 | 单节点 TP=8 |
| 48 个 Target 权重分片读取 | 约 25 秒 | 只是日志可见的文件读取部分 |
| Target CUDA Graph，51 组 Batch Shape | 约 394 秒 | 本轮最大单项之一 |
| DSpark Draft CUDA Graph | 约 123 秒 | 推测解码额外成本 |
| Engine 内部启动 | 约 854 秒 | 包含权重处理、JIT、Graph 与 Warm-up |
| Pod 创建到业务 Ready | 约 23 分钟 | 再次逼近半小时窗口 |

模型已经命中节点缓存也不代表问题解决：

- SGLang Combined 首次启动仍约 11 分钟，其中权重加载、转换和预热约 278 秒，Decode CUDA Graph 约 356 秒；
- vLLM 节点缓存命中后的重建仍约 7 分 40 秒，主要时间转移到了 TileLang、DeepGEMM 编译和 CUDA Graph。

由此得到本文最重要的判断：**优化会不断改变关键路径。** 下载消失后，Checkpoint 转换会浮现；编译缓存命中后，Graph Capture 又可能成为最长阶段。不能用一个总耗时解释所有问题。

一项针对 vLLM 的公开研究同样将冷启动拆为六个阶段，并发现整体主要受 CPU 路径限制。GPU 显存很快分配完成，并不表示 Python、Checkpoint 转换、Kernel 编译和 Graph 已结束：[Breaking the Ice: Analyzing Cold Start Latency in vLLM](https://arxiv.org/abs/2606.07362)。

## 3. 按启动顺序优化关键路径

### 3.1 第一步：在申请 GPU 前准备好镜像和模型

让每个 GPU Pod 的 Init Container 都从远端下载模型，实现简单，但会产生两个问题：GPU 在下载期间空等；N 个副本会同时下载 N 份相同权重。

更合理的职责划分是：

```text
对象存储或共享存储：权威模型副本
节点模型缓存：面向启动的可丢失副本
GPU Pod：校验缓存命中后直接启动 Engine
```

节点上线流程也应该提前完成准备工作：

```text
Node Ready
  → Runtime Image 预拉取
  → 模型缓存预热与完整性校验
  → 编译制品准备
  → 节点进入 inference-ready 池
  → 推理 Pod 才允许申请 GPU
```

模型缓存不能只判断目录存在，至少还应校验：

- 模型 Digest、配置、Tokenizer 和权重索引；
- 索引声明的全部 Safetensors 分片；
- 完成标记只在下载和校验全部成功后原子写入；
- 节点磁盘容量、配额、淘汰策略和缓存位置标签。

KServe 的 `LocalModelCache`、`LocalModelNodeGroup` 和 `LocalModelNode` 已能将模型预下载到节点 NVMe 并跟踪缓存状态，可作为缓存控制器的公开参考：[KServe Local Model Cache](https://kserve.github.io/website/docs/model-serving/generative-inference/modelcache/localmodel)。

共享 CephFS 可以保存权威副本，却不一定适合作为最高频启动盘。多个 Rank 同时 mmap、读取和遍历元数据时，共享文件系统会变成公共瓶颈。比较稳妥的分层是：共享存储保证可恢复，本地 NVMe 保证启动速度。

#### HostPath 不等于 NVMe：一次现场 A/B

`hostPath` 只表示把宿主机目录挂进 Pod，并不说明底层盘型。我们检查两台同规格 8×H20 节点后发现：原模型 HostPath 位于约 1 TiB 的系统根盘；每台节点另有两块约 5.8 TiB NVMe，已经组成约 12 TiB 的双盘条带 XFS 数据卷。

将约 166.9 GB、56 个文件复制到 NVMe 后，两台节点分别耗时 59 秒和 58 秒，包含文件系统 `sync`，表观吞吐约 2.7 GiB/s。随后使用同一模型、镜像、参数和 GPU 规格并行启动 SGLang Combined TP=8：

| 观测项 | 双盘 NVMe | 系统根盘 | 怎样解释 |
| --- | ---: | ---: | --- |
| 模型 Cache Check | 命中 | 命中 | 均不下载 |
| SGLang `Load weight` | 约 246.7 秒 | 约 275.8 秒 | NVMe 快约 29.1 秒，约 10.5% |
| Decode CUDA Graph | 约 26.9 秒 | 约 359.1 秒 | 两节点 JIT Cache 状态不同，不能算作存储收益 |
| Pod 创建到 Ready | 约 320 秒 | 约 700 秒 | 现场总耗时，不是纯存储 A/B |
| 确定性生成请求 | 正确 | 正确 | 两边均返回预期文本 |

![双盘 NVMe 与系统根盘的权重加载实测对比](../../assets/practices/llm-cold-start-optimization/02-root-disk-vs-nvme.png)

可信的存储结论是权重阶段缩短约 29 秒，而不是整体缩短 380 秒。约 167 GB 文件虽然可以在一分钟左右完成顺序复制，Engine 的 `Load weight` 仍需约 247 秒，说明它还包含 Checkpoint 解析、权重转换与重排、FP8/MXFP4 处理以及 CPU 到 GPU 搬运。

这轮没有执行系统级 `drop_caches`，两节点编译缓存状态也不一致，适合确认方向和量级。形成容量承诺前，还应在同一节点串行重复，分别测冷、热 Page Cache，并统一 JIT Cache 指纹。

#### 先算清物理下限

156 GiB 权重的纯传输下限如下，尚未包含协议、文件系统、解析、转换和 GPU 初始化：

| 有效带宽 | 只搬运 156 GiB 的理论下限 |
| ---: | ---: |
| 1 Gbit/s | 约 22.3 分钟 |
| 10 Gbit/s | 约 134 秒 |
| 25 Gbit/s | 约 54 秒 |
| 3.5 GiB/s NVMe | 约 45 秒 |
| 7 GiB/s NVMe | 约 22 秒 |
| 14 GiB/s 条带化 NVMe | 约 11 秒 |

下载需要 6 分钟时，应优先优化模型分发和缓存；模型已在本地 NVMe 后，继续盯着下载带宽就无法解释剩余的数分钟。

### 3.2 第二步：让 Checkpoint 适合当前并行拓扑

Safetensors 支持安全加载和 mmap，却不保证原始分片适合当前 TP、PP 或 EP。常见浪费包括每个 Rank 遍历全部分片、读入后再丢弃不属于自己的张量，以及在启动阶段才做量化、转置或 Marlin 布局转换。

优化顺序建议为：

1. 将确定性的量化、转置和权重重排移到离线构建；
2. 按目标并行拓扑预分片，例如 TP=8 时每个 Rank 直接读取自己的连续数据；
3. 使用多线程读取和流水加载，让文件读取、CPU 转换和 H2D 重叠；
4. 根据存储介质选择 mmap、eager 或 prefetch；
5. 用 Loader 内部指标区分文件读取、转换和 GPU 搬运，避免只看总耗时。

vLLM 的加载配置包含 `sharded_state`、`runai_streamer`、`runai_streamer_sharded`、`instanttensor`、`tensorizer` 和 `modelexpress` 等路径：[vLLM LoadConfig](https://docs.vllm.ai/en/latest/api/vllm/config/)。Safetensors 的 `lazy`、`eager` 和 `prefetch` 也需要结合本地盘或高延迟共享存储做 A/B：[vLLM serve](https://docs.vllm.ai/en/stable/cli/serve/)。

SGLang 的 `--weight-loader-prefetch-checkpoints` 可以预取 Checkpoint 到 OS Page Cache，但它只减少文件等待，不能跳过转换、JIT 或 CUDA Graph：[SGLang Server Arguments](https://github.com/sgl-project/sglang/blob/main/docs/advanced_features/server_arguments.md)。

GPUDirect Storage 只有在硬件、文件系统、驱动和 Runtime Loader 都支持时，才能通过 DMA 减少 CPU Bounce Buffer。给 Pod 增加 RDMA Resource 并不会自动启用 GDS：[NVIDIA GPUDirect Storage](https://github.com/NVIDIA/gds-nvidia-fs)。

### 3.3 第三步：把现场编译变成带指纹的制品

在 H20 上启动 DeepSeek V4 SGLang 时，进程会为 `sm_90a` 生成 CUDA 源码，再通过 `nvcc`、`cicc`、`ptxas` 和 Ninja 生成 CUBIN 或动态库。

| 制品 | 典型缓存位置 | 现场观测 |
| --- | --- | --- |
| MHC/DeepGEMM Kernel | `/root/.cache/sglang/deep_gemm/cache/kernel.<fingerprint>/kernel.cubin` | 16 个 Bucket 的 CUBIN |
| SGL Kernel 通信扩展 | `/root/.cache/tvm-ffi/sgl_kernel_jit_communicator_<fingerprint>/` | C++/CUDA 编译出的 `.so` |
| CUDA IPC 与 Triton 扩展 | `/root/.cache/tvm-ffi/`、`/root/.cache/sglang/triton/` | Runtime 辅助 `.so` |
| FlashInfer | `/root/.cache/sglang/.cache/flashinfer/<version>/<arch>/` | 版本和架构相关 Kernel Cache |
| vLLM torch.compile | `$VLLM_CACHE_ROOT/torch_compile_cache/` | Inductor、Triton 与 AOT 制品 |

一次 MHC Prewarm 生成 16 个 CUBIN 约花 248 秒，而最终文件不足 1 MiB。这类成本应从每次 Pod 启动移到受控预热或镜像构建阶段。vLLM 也建议持久化或复制 `VLLM_CACHE_ROOT`，否则只保存 Hugging Face 权重缓存仍会重新编译：[vLLM Docker 部署](https://docs.vllm.ai/en/latest/deployment/docker/)、[vLLM 启动优化](https://docs.vllm.ai/en/latest/configuration/optimization/)。

编译缓存不能跨环境盲目复用，指纹至少应包含：

```text
GPU Architecture + Driver + CUDA
+ Runtime Image Digest
+ SGLang/vLLM/Torch/Triton/DeepGEMM/TileLang/FlashInfer
+ Python ABI
+ Model Implementation + DType + Quantization
+ TP/PP/EP 与编译参数
```

推荐构建流程：

```text
固定基础镜像 Digest
  → 在同架构 GPU 上执行预热矩阵
  → 收集 .cubin、.so 和 torch.compile cache
  → 生成 Cache Manifest 与兼容性指纹
  → 写入派生镜像的 /opt/prebuilt-cache/<fingerprint>
  → Init Container 复制到可写 Cache Volume
```

如果 `/root/.cache` 被 `emptyDir` 整体覆盖，镜像中的预编译制品也会被遮住。应复制到可写卷，或只挂载需要持久化的子目录。缓存命中后仍要做正确性回归，因为错误制品可能导致崩溃或错误 Token。

SGLang 还提供 `SGLANG_JIT_DEEPGEMM_PRECOMPILE`、并行编译 Worker 和 Fast Warm-up。Fast Warm-up 可能缩短启动但损失稳态性能，应同时比较正确性、吞吐和尾延迟：[SGLang Environment Variables](https://github.com/sgl-project/sglang/blob/main/docs/references/environment_variables.md)。

### 3.4 第四步：缩小 CUDA Graph 和 Warm-up 的形状集合

编译缓存命中后，CUDA Graph 往往成为下一段关键路径。本轮 Target 和 Draft 两轮 Capture 合计约 517 秒。Graph 与进程显存地址、通信器和 Shape 相关，不能像 CUBIN 一样简单复制到另一个进程。

更可行的策略是控制形状，而不是完全关闭 Graph：

- 用真实流量的并发、输入和输出长度决定 Capture 集合；
- 限制 `max-num-seqs` 或等价的最大请求数；
- Target-only、Speculative Draft 和不同配置分别计时；
- 低频大 Shape 先走 Eager，后台完成 Capture；
- 区分“最低可服务”和“全部目标 Shape 已预热”两级 Readiness。

vLLM 的 `-O0` 到 `-O3` 体现了启动时间与稳态性能的显式取舍，适合成为 A/B 变量，而不是长期使用 `--enforce-eager` 掩盖问题：[vLLM Optimization Levels](https://docs.vllm.ai/en/latest/configuration/optimization/)。

### 3.5 第五步：用真实请求定义业务 Ready

最低验收不能停在 TCP 端口或 `/health=200`。至少要验证：

1. `/v1/models` 返回预期模型；
2. 一条固定 Prompt、固定采样参数的生成请求返回确定性结果；
3. 常见 Shape 已完成预热；
4. Gateway 只有在上述条件通过后才加入流量；
5. 新副本失败时，旧副本或 Combined 副本仍能继续服务。

这一步不会让 Engine 加载更快，但能避免把“端口 Ready、首次请求现场编译”误认为冷启动完成。

## 4. 当普通加载优化到头：直接复用已有状态

完成 NVMe、Checkpoint、编译缓存和 Graph 优化后，下一步不再是更快读文件，而是复用另一份已经加载或初始化的状态。

### 4.1 GPU Peer 复制：适合扩容和滚动发布

NVIDIA ModelExpress 会优先从兼容的现有副本通过 NIXL 和 P2P RDMA 复制 GPU 权重；无可用 Peer 时，再回退到对象存储流式加载、GDS 或 POSIX Loader。它还可以传输 Triton、DeepGEMM、TileLang、CuTe DSL 和 FlashInfer Kernel Cache。

公开 Benchmark 中，约 806 GiB DeepSeek-V4-Pro、TP=8、8×B200 与 ConnectX-7 的 P2P 权重加载约 11 秒；复用 Kernel Artifacts 后，API Ready 从约 8 分钟降到 1 分 44 秒。起点是已经存在兼容副本，不能当作 H20 从远端存储完整冷启动的承诺：[ModelExpress Benchmark](https://github.com/ai-dynamo/modelexpress/blob/main/docs/BENCHMARKS.md)、[部署说明](https://github.com/ai-dynamo/modelexpress/blob/main/docs/DEPLOYMENT.md)。

### 4.2 Sleep Mode：用 Host Memory 换唤醒速度

vLLM Sleep Mode 保留进程，将权重卸载到 CPU Memory、丢弃 KV Cache，再通过唤醒恢复。它避免 Python 初始化和重新编译，但要占用大量 Host Memory，也不能解决 Pod 或节点消失后的恢复：[vLLM Sleep Mode](https://docs.vllm.ai/en/v0.11.0/features/sleep_mode/)。

### 4.3 GPU 快照：秒级，但不是普通冷启动

NVIDIA Dynamo Snapshot 使用 CRIU 和 `cuda-checkpoint` 保存进程、CUDA Context 和 GPU 状态。官方公开的 `gpt-oss-120b` 原型做到 5 秒以内、约 21 倍加速，但项目仍标注早期开发、尚未生产就绪；多 GPU、多节点、驱动兼容和特权 Node Agent 都需要验证：[Dynamo Snapshot](https://github.com/ai-dynamo/snapshot)、[原型说明](https://github.com/ai-dynamo/dynamo/blob/main/docs/fern/pages/blog/2026/dynamo-snapshot.mdx)、[Kubernetes 限制](https://github.com/ai-dynamo/dynamo/blob/main/docs/fern/pages/developer-guide/knowledge-base/kubernetes/kubernetes-operator/snapshot.md)。

ServerlessLLM 在 OSDI 2024 中使用本地 Checkpoint、优化格式、多层存储和 Locality-aware Scheduling，将多类模型加载延迟降低 10–200 倍；但小模型的亚秒数字不能线性套用到 156 GiB DeepSeek：[ServerlessLLM](https://www.usenix.org/conference/osdi24/presentation/fu)。

## 5. 现实目标：从半小时到哪一级

结合现场实测、字节下限和公开结果，可以给 156 GiB 级模型建立分层目标：

| 场景 | 时间量级 | 性质 |
| --- | --- | --- |
| 远端模型、镜像、编译缓存均未命中 | 10–30 分钟；现场约 23–30 分钟 | 完整冷启动 |
| 模型命中节点，但现场转换、JIT 和 Graph | 约 7 分 40 秒至 11 分钟 | 已验证基线 |
| NVMe + 预分片 + 编译缓存 + 收敛 Graph | **2–5 分钟** | 当前合理工程目标 |
| 流式 Loader、GDS 或充分流水 | **45–120 秒** | 激进路径，依赖硬件与 Runtime |
| 已有兼容 GPU Peer | 公开 B200 结果 **1 分 44 秒 Ready** | Scale-out，不是首次启动 |
| 热副本、Sleep 或 GPU 快照 | **数秒至十几秒**已有原型 | 热恢复，不是真冷启动 |

![从完整冷启动到热恢复的分阶段优化路线](../../assets/practices/llm-cold-start-optimization/03-optimization-ladder.png)

对现有 H20 环境，合理顺序是：先稳定进入 2–5 分钟，再评估 P2P 冲击两分钟以内；关键服务通过预热副本或快照把故障切换压到秒级。**完整冷启动时间不能直接成为业务 RTO。**

## 6. 落地路线：每轮只改变一个变量

### 6.1 先补齐分段可观测性

每个 Pod 应输出结构化启动事件：

```json
{"stage":"model_cache_check","elapsed_ms":1234,"cache_hit":true}
{"stage":"weight_load","elapsed_ms":246700,"bytes":166900000000}
{"stage":"kernel_jit","elapsed_ms":248231,"cache_hit":false}
{"stage":"cuda_graph","elapsed_ms":356020,"shape_count":51}
{"stage":"business_ready","elapsed_ms":663104}
```

Prometheus 至少记录创建到 Ready、各阶段 Histogram、模型与编译缓存命中率、读取字节和吞吐、第一条真实请求 TTFT。P95 比单次最快值更重要。

### 6.2 按四轮 A/B 推进

| 轮次 | 唯一变量 | 要回答的问题 |
| --- | --- | --- |
| A | 远端回源 → 节点 NVMe | 重复下载消除了多少 |
| B | 默认加载 → 预分片、并行或流式 Loader | 读取、转换和 H2D 缩短多少 |
| C | 空编译缓存 → 同指纹预编译缓存 | JIT 与 Autotune 消除了多少 |
| D | 全 Shape Graph → 真实流量 Shape | Capture 缩短多少，稳态性能是否保持 |

每轮必须固定模型 Digest、Runtime Image、TP、上下文、量化和采样参数，并同时比较：启动时间、正确性、吞吐、TTFT、TPOT、显存和功耗。冷启动变快但稳态性能明显下降，不是无代价优化。

### 6.3 最后再评估极致路径

只有普通加载稳定进入 2–5 分钟后，再验证：

- GDS 或流式 Loader 是否真的打通目标数据路径；
- 同型号 GPU 副本间 P2P 权重和 Kernel Cache 复制；
- Sleep Mode 的 Host Memory 成本与唤醒时间；
- GPU Snapshot 对 TP=8、当前 Runtime 和安全策略是否可用；
- 常驻备用副本的 GPU 成本是否低于半小时故障窗口的业务损失。

## 7. 结论

从 DeepSeek-V4-Pro 滚动重启接近半小时开始，我们最初只盯着模型下载；在 DeepSeek V4 Flash 上逐段观测后，才确认模型缓存只解决第一段问题。Checkpoint 布局、GPU 搬运、现场 JIT、CUDA Graph 和真实请求 Warm-up 都可能依次成为关键路径。

最终需要管理的不是一个启动参数，而是三类可复用资产：

1. **模型资产**：不可变 Digest、节点 NVMe 缓存、面向并行拓扑的 Checkpoint；
2. **Runtime 资产**：带兼容性指纹的 CUBIN、`.so`、Triton、DeepGEMM、TileLang、FlashInfer 与 torch.compile Cache；
3. **运行状态资产**：预热副本、GPU Peer、休眠进程或经过验证的快照。

普通 H20 路径先把节点缓存重启做到 2–5 分钟，是合理且可验证的目标；秒级则要依赖热副本、Sleep 或 GPU 快照，并诚实地称为恢复，而不是完整冷启动。

延伸阅读：

- [大模型与数据制品](../data/model-artifacts.md)：模型分发、节点缓存、OCI 制品与供应链；
- [DeepSeek-V4-Flash-0731 的 H20 部署与压测](deepseek-v4-flash-h20-evaluation.md)：逐项启动日志、部署配置与吞吐基线。
