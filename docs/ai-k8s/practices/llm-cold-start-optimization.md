---
title: 从半小时到分钟级：大模型冷启动全链路优化
description: 从 DeepSeek-V4-Pro 滚动重启接近半小时的真实问题出发，拆解模型下载、节点缓存、权重加载、GPU 搬运、JIT 编译、CUDA Graph 与热恢复
status: exploratory
last_reviewed: 2026-08-12
---

# 从半小时到分钟级：大模型冷启动全链路优化

今年上半年部署 DeepSeek-V4-Pro 时，我们遇到的一个问题很直接：**一次模型滚动重启需要接近半小时**。

这里容易和更早的 DeepSeek R1 混淆。R1 发布于 2025 年 1 月，DeepSeek V4 Preview 则于 2026 年 4 月发布；这次接近半小时的经历对应的是 V4-Pro，不是 R1：[DeepSeek-R1 官方发布记录](https://api-docs.deepseek.com/news/news250120/)、[DeepSeek V4 Preview 官方发布记录](https://api-docs.deepseek.com/news/news260424/)。

正常发布时，还可以让旧副本继续接流量，等新副本 Ready 后再切换。但如果服务已经整体不可用，半小时就不再是一个普通的发布指标，而是半小时的故障恢复时间。对于已经接入真实业务的推理服务，这几乎无法接受。

最初我们以为慢在模型下载。把模型提前放到共享存储、再缓存到 GPU 节点后，下载时间确实消失了，服务却没有像预期那样很快 Ready。后续在约 156 GiB 的 DeepSeek V4 Flash 上逐段打点，才看清完整链路：权重到达节点只是开始，后面还有反序列化、权重转换、CPU 到 GPU 搬运、通信初始化、Kernel JIT、Autotune、CUDA Graph capture 和业务形状预热。

这篇文章不讨论某一个 `--fast-start` 参数，而是回答三个更实际的问题：

1. 半小时究竟花在哪里；
2. 哪些时间能够通过缓存和离线构建消除，哪些每次启动仍然必须支付；
3. 对 150 GiB 级模型，普通生产方案、激进加载方案和快照恢复分别能做到什么量级。

![大模型从调度、模型准备到业务可用的冷启动全链路](../../assets/practices/llm-cold-start-optimization/01-cold-start-pipeline.png)

文中的集群名称、地址、镜像仓库、对象存储、模型路径和凭据均已删除或替换为占位符。时间来自特定硬件和软件组合，只用于说明量级与方法，不是生产容量承诺。

## 1. 先定义“冷启动”

只说“启动用了 10 秒”没有意义。至少要区分四种状态：

| 口径 | 节点上的镜像 | 节点上的模型 | 编译缓存 | 进程/GPU 状态 | 适合衡量什么 |
| --- | --- | --- | --- | --- | --- |
| 完整冷启动 | 未命中 | 未命中 | 未命中 | 不存在 | 新节点扩容、灾难恢复 |
| 节点热缓存重启 | 已命中 | 已命中 | 可命中 | 不存在 | Pod 重建、普通滚动发布 |
| 预热副本切换 | 已命中 | 已命中 | 已命中 | 进程已 Ready | 发布切流与容量保险 |
| 快照或休眠恢复 | 已命中或随快照恢复 | 已加载/保存 | 已编译 | 被保存或仍保留 | 秒级恢复实验 |

我们在 V4-Pro 上遇到的接近半小时，是接近第一种口径；真正需要优先优化的故障恢复，则至少要把第二种压到分钟级，并为关键服务保留第三种兜底。快照恢复很诱人，但它不是“把一个数百 GiB 模型从远端下载、加载并编译只用了几秒”。

统一计时边界也很重要：

```text
T0  Deployment/Role revision 创建
T1  Pod 被调度并开始拉镜像
T2  Init Container 开始准备模型
T3  模型完整性校验通过
T4  推理进程启动
T5  权重加载和转换完成
T6  JIT/Autotune 完成
T7  CUDA Graph 与内置 warm-up 完成
T8  /health、/v1/models 和确定性生成请求全部通过
T9  Gateway 将副本加入可服务集合
```

Kubernetes `Ready`、HTTP 端口打开和真正能稳定生成正确结果，也不应该混成同一个时间点。

## 2. 半小时里发生了什么

后续一次 DeepSeek V4 Flash 的完整冷启动提供了更细的证据。模型约 156 GiB、48 个 Safetensors 分片，推理节点使用 8 张 H20。一次观测如下：

| 阶段 | 观测时间 | 说明 |
| --- | ---: | --- |
| 模型准备 | 约 6 分钟 | 有效吞吐约 0.43 GiB/s |
| 首次拉取约 14.29 GB Runtime 镜像 | 约 127 秒 | 节点镜像未命中 |
| NCCL 初始化 | 约 19 秒 | 单节点 TP=8 |
| 48 个 target 权重分片读取 | 约 25 秒 | 只是日志中的文件读取部分 |
| target CUDA Graph，51 组 batch shape | 约 394 秒 | 本轮最大单项之一 |
| DSpark draft CUDA Graph | 约 123 秒 | 推测解码的额外启动成本 |
| Engine 内部启动 | 约 854 秒 | 包含权重处理、JIT、图捕获和 warm-up |
| Pod 创建到业务 Ready | 约 23 分钟 | 再次接近 V4-Pro 的半小时问题 |

另一套 SGLang Combined Engine 在模型已经命中节点 HostPath 后，首次启动仍约 11 分钟：权重加载、FP8 转换与 MHC 预热约 278 秒，Decode CUDA Graph capture 约 356 秒。一次 vLLM 节点缓存命中后的重建仍约 7 分 40 秒，主要时间已经从下载转移到 TileLang/DeepGEMM 编译和 CUDA Graph。

这说明冷启动不是一个串行的 `download model`：

```text
调度与镜像
    ↓
远端模型 → 节点本地缓存 → 文件读取/页缓存
                               ↓
                    反序列化、切分、量化/重排
                               ↓
                         CPU → GPU HBM
                               ↓
                NCCL/NIXL、KV Cache、显存 Profile
                               ↓
                 JIT / Autotune / CUDA Graph
                               ↓
                   真实请求 warm-up → Ready
```

有些阶段可以流水并行，因此总时间不一定等于每一项简单相加。优化的关键不是让每一项都快 10%，而是持续找出新的关键路径。

2026 年一项针对 vLLM 的公开冷启动研究也把启动拆成六个阶段，并发现整体主要受 CPU 路径限制。这与我们的现象一致：GPU 显存很快分配完，并不表示 Python 进程、Checkpoint 转换、Kernel 编译和 Graph 已经完成：[Breaking the Ice: Analyzing Cold Start Latency in vLLM](https://arxiv.org/abs/2606.07362)。

## 3. 第一层：不要让 GPU 等模型下载

### 3.1 对象存储是权威源，不应是每个 Pod 的启动盘

直接在每个 GPU Pod 的 Init Container 中下载模型，最容易实现，也最容易在扩容和重建时制造流量风暴：N 个副本会重复下载 N 份相同权重，GPU 在此期间只能空等。

我们后来把模型放到节点级缓存目录，并让 Init Container 只做缓存命中和完整性判断：

```yaml
volumes:
  - name: model-cache
    hostPath:
      path: /var/lib/model-cache/deepseek-v4-pro/<MODEL_DIGEST>
      type: DirectoryOrCreate
```

判断缓存不能只看目录存在。至少要验证：

- `config.json`、Tokenizer 和权重索引存在；
- 索引声明的所有 Safetensors 分片齐全；
- 模型版本或 Digest 与部署声明一致；
- 完成标记只在全部下载和校验成功后原子写入。

HostPath 在这里是**可丢失的节点缓存**，不是模型唯一副本。它要求调度器尽量把重建 Pod 放回有缓存的节点，也要求节点磁盘有容量、配额、淘汰和校验机制。KServe 已经提供 `LocalModelCache`、`LocalModelNodeGroup` 和 `LocalModelNode`，可以将模型预下载到节点本地 NVMe，并跟踪每个节点的缓存状态，可作为自建缓存控制器的公开参考：[KServe Local Model Cache](https://kserve.github.io/website/docs/model-serving/generative-inference/modelcache/localmodel)。

### 3.2 下载和 GPU 调度解耦

模型预热应该由不申请 GPU 的 DaemonSet、Job 或缓存控制器完成。只有缓存进入 `Ready`，推理 Pod 才申请昂贵的 GPU。节点自动扩容时也可以按以下顺序执行：

```text
Node Ready
  → Runtime 镜像预拉取
  → 模型缓存预热与校验
  → 编译制品准备
  → 节点进入 inference-ready 池
  → 才允许推理工作负载调度
```

共享 CephFS 可以避免每个节点保存完整模型，但不一定能获得最短启动时间。大量 Rank 同时 mmap、随机读取和遍历元数据时，共享文件系统的延迟和带宽会成为公共瓶颈。比较稳妥的职责划分是：对象存储或共享存储保存权威副本，本地 NVMe 服务高频启动。

### 3.3 先算字节搬运的物理下限

156 GiB 权重在理想链路上的纯传输下限如下，尚未包含协议损耗、校验、文件系统、反序列化和 GPU 初始化：

| 有效带宽 | 只搬运 156 GiB 的理论下限 |
| ---: | ---: |
| 1 Gbit/s | 约 22.3 分钟 |
| 10 Gbit/s | 约 134 秒 |
| 25 Gbit/s | 约 54 秒 |
| 3.5 GiB/s NVMe | 约 45 秒 |
| 7 GiB/s NVMe | 约 22 秒 |
| 14 GiB/s 条带化 NVMe | 约 11 秒 |

当下载耗时 6 分钟时，有效吞吐只有约 0.43 GiB/s。此时先优化源站、并发下载和节点缓存，比调整 CUDA Graph 更有效；当模型已经在 7 GiB/s 本地 NVMe 上，22 秒的字节下限就不再是 10 分钟启动的解释，应该继续看 CPU 转换、JIT 和 Graph。

### 3.4 实测：同一份 HostPath，底层盘型不同会怎样

`hostPath` 只是把宿主机目录挂进 Pod，并不代表这个目录位于 NVMe。我们在两台同规格的 8×H20 节点上检查后发现，原模型缓存虽然通过 HostPath 挂载，但实际位于约 1 TiB 的系统根盘；每台机器另外有两块约 5.8 TiB 的本地 NVMe，已经组成约 12 TiB 的双盘条带 XFS 数据卷。

我们把同一份约 166.9 GB、56 个文件的模型从根盘复制到该 NVMe 数据卷。两台节点并行复制分别用了 59 秒和 58 秒，包含最后一次文件系统 `sync`，表观有效吞吐约 2.7 GiB/s。随后并行启动两套 SGLang Combined TP=8 实例，固定模型、镜像、启动参数和 GPU 规格，只改变模型目录的底层存储：

| 观测项 | 双盘 NVMe 条带 | 系统根盘 | 差异 |
| --- | ---: | ---: | ---: |
| 模型 Cache Check | 命中 | 命中 | 无需下载 |
| NCCL 初始化 | 约 5.3 秒 | 约 18.1 秒 | 节点噪声，不计入存储收益 |
| SGLang `Load weight` | 约 246.7 秒 | 约 275.8 秒 | NVMe 快约 29.1 秒，约 10.5% |
| Decode CUDA Graph | 约 26.9 秒 | 约 359.1 秒 | 编译/JIT Cache 状态不同，不能归因于存储 |
| Pod 创建到 Ready | 约 320 秒 | 约 700 秒 | 现场观测，不是纯存储 A/B |
| 最小确定性请求 | 正确 | 正确 | 均返回预期文本 |

这组结果最值得保留的数字不是“整体快了 380 秒”，而是框架内部记录的权重阶段快了约 29 秒。两个节点的本地编译缓存状态不同，使 CUDA Graph capture 相差 332 秒；如果把这段也算成 NVMe 收益，会得出错误结论。

另一方面，约 167 GB 文件即使能在一分钟内完成顺序复制，Engine 的权重阶段仍需要约 247 秒，也说明 `Load weight` 并非单纯读取文件。它还包含多 Rank 读取方式、Checkpoint 解析、FP8/MXFP4 相关转换、权重布局处理和 CPU 到 GPU 搬运。NVMe 值得作为节点模型缓存的默认介质，但单独更换磁盘不能把十分钟冷启动直接变成一分钟。

这轮是两台同规格节点的并行现场 A/B，并未执行系统级 `drop_caches`，也没有抹掉节点已有的 JIT Cache。它适合确认方向和量级；如果要形成容量承诺，还应在同一节点串行重复多轮，统一编译缓存指纹，并分别测量冷 Page Cache 与热 Page Cache。

![双盘 NVMe 与系统根盘的权重加载实测对比](../../assets/practices/llm-cold-start-optimization/02-root-disk-vs-nvme.png)

## 4. 第二层：让 checkpoint 适合并行加载

Safetensors 解决了安全和 mmap 等基础问题，却不保证原始分片恰好适合当前 TP/PP 拓扑。一个常见浪费是：每个 Rank 都遍历全部分片，读取张量后再丢弃不属于自己的部分，或者启动时才做量化、转置和 Marlin 布局转换。

更快的方向包括：

1. **离线转换**：把量化、权重重排和确定性的格式转换移出启动关键路径；
2. **按目标并行拓扑预分片**：TP=8 时，每个 Rank 直接读取自己的连续数据；
3. **多线程读取**：并行打开多个 Shard，避免单线程不能打满 NVMe 或网络存储；
4. **流水加载**：一部分张量读取完成后立即搬到 GPU，同时继续读取后续张量；
5. **页缓存预取**：在 Engine worker 启动前顺序读入 OS Page Cache，避免多个 Rank 在高延迟存储上产生离散缺页。

当前 vLLM 官方加载配置已经包含 `sharded_state`、`runai_streamer`、`runai_streamer_sharded`、`instanttensor`、`tensorizer` 和 `modelexpress` 等加载路径，其中预分片、并行预取和流式加载都直接针对这类问题：[vLLM LoadConfig](https://docs.vllm.ai/en/latest/api/vllm/config/)。vLLM 还区分 Safetensors 的 `lazy`、`eager` 和 `prefetch`：本地盘通常适合 mmap/lazy，高延迟 NFS/Lustre 可能更适合 eager 或预取，但会增加 CPU 内存占用，必须 A/B，而不能只凭文件系统类型决定：[vLLM serve](https://docs.vllm.ai/en/stable/cli/serve/)。

SGLang 也提供 `--weight-loader-prefetch-checkpoints`，用于在真正加载前把 Checkpoint 预取到 OS Page Cache。它优化的是文件读取等待，并不会跳过权重转换、JIT 或 CUDA Graph：[SGLang Server Arguments](https://github.com/sgl-project/sglang/blob/main/docs/advanced_features/server_arguments.md)。

如果 Runtime loader 支持，GPUDirect Storage 可以让本地或远端存储直接 DMA 到 GPU Memory，绕过 CPU Bounce Buffer。它能够减少 CPU 拷贝和提高吞吐，但需要受支持的硬件、文件系统、驱动和应用加载器，不是给 Pod 增加 RDMA Resource 就自动生效：[NVIDIA GPUDirect Storage 开源驱动与说明](https://github.com/NVIDIA/gds-nvidia-fs)。

## 5. 第三层：把现场编译变成可复用制品

### 5.1 冷启动期间到底编译了什么

在 H20 上启动 DeepSeek V4 SGLang 时，进程会为 `sm_90a` 生成 CUDA 源码，经过 `nvcc`、`cicc`、`ptxas` 和 Ninja 生成 CUBIN 或动态库。现场确认的最终产物包括：

| 类型 | 典型缓存位置 | 本轮内容 |
| --- | --- | --- |
| MHC/DeepGEMM Kernel | `/root/.cache/sglang/deep_gemm/cache/kernel.<fingerprint>/kernel.cubin` | 16 个针对不同 bucket 的 CUBIN |
| SGL Kernel 通信扩展 | `/root/.cache/tvm-ffi/sgl_kernel_jit_communicator_<fingerprint>/` | C++/CUDA 编译出的 `.so` |
| CUDA IPC 与 Triton 扩展 | `/root/.cache/tvm-ffi/`、`/root/.cache/sglang/triton/` | IPC 与 Runtime 辅助 `.so` |
| FlashInfer | `/root/.cache/sglang/.cache/flashinfer/<version>/<arch>/` | 与版本和架构相关的 Kernel Cache |
| vLLM torch.compile | `$VLLM_CACHE_ROOT/torch_compile_cache/` | Inductor、Triton 与 AOT 制品 |

一次 MHC prewarm 生成 16 个 CUBIN 约花 248 秒，而这些最终文件本身不足 1 MiB。这个投入非常适合从每个新 Pod 的启动阶段移到镜像构建或受控预热阶段。vLLM 官方也明确建议持久化或复制 `VLLM_CACHE_ROOT`，否则只挂载 Hugging Face 权重缓存，新容器仍会重新编译：[vLLM Docker 部署](https://docs.vllm.ai/en/latest/deployment/docker/)、[vLLM 启动优化](https://docs.vllm.ai/en/latest/configuration/optimization/)。

SGLang 公开的 DeepGEMM 开关还包括 `SGLANG_JIT_DEEPGEMM_PRECOMPILE`、并行编译 Worker 数、独立 Cache Directory，以及 `SGLANG_JIT_DEEPGEMM_FAST_WARMUP`。官方说明 Fast Warm-up 在相应场景可把约 30 分钟降到 3 分钟以内，但可能损失运行性能，因此它应该进入正确性、吞吐和尾延迟 A/B，不能直接作为生产默认值：[SGLang Environment Variables](https://github.com/sgl-project/sglang/blob/main/docs/references/environment_variables.md)。

### 5.2 正确复用编译缓存

编译缓存不是跨环境通用的二进制。缓存键至少应包含：

```text
GPU architecture
+ GPU/driver/CUDA version
+ Runtime image digest
+ SGLang/vLLM/Torch/Triton/DeepGEMM/TileLang/FlashInfer version
+ Python ABI
+ model implementation, dtype and quantization
+ TP/PP/EP and compilation-related arguments
```

推荐构建一个 Runtime 派生镜像：

```text
固定基础镜像 Digest
  → 在同架构 GPU 上执行完整预热矩阵
  → 收集最终 .cubin/.so/torch.compile cache
  → 生成 cache manifest 和兼容性指纹
  → 写入 /opt/prebuilt-cache/<fingerprint>
  → 发布不可变派生镜像
```

如果运行时把 `/root/.cache` 挂成 `emptyDir`，镜像内相同路径会被 Volume 遮住。可以由 Init Container 把 `/opt/prebuilt-cache/<fingerprint>` 复制到可写缓存卷，或只分别挂载需要持久化的子目录。

缓存命中后仍要做一次正确性回归。错误或过期的 Kernel Cache 不是单纯的性能问题，可能表现为进程崩溃、错误 Token 或只在某些 Shape 出错。

## 6. 第四层：控制 CUDA Graph 和 warm-up 的形状集合

编译缓存命中后，CUDA Graph capture 往往成为下一段关键路径。本轮 target 和 draft 两轮 capture 合计约 517 秒。Graph 通常与当前进程的显存地址、通信器和 Shape 相关，不能像普通 CUBIN 一样随意复制到另一个进程中直接复用。

真正可落地的优化是减少无效形状，而不是完全不预热：

- 用真实业务的并发、输入长度和输出长度分布决定 capture 集合；
- 显式限制 `max-num-seqs` 或等价的最大运行请求数；
- target-only、DSpark 和不同 speculative 配置分别计时；
- 低频大 Shape 可先走 eager，后台完成捕获后再进入优化路径；
- 把 readiness 分成“最低可服务”和“全部目标 Shape 已预热”两个等级。

vLLM 当前提供从 `-O0` 到 `-O3` 的优化等级：`-O0` 启动最快但稳态性能最低，默认等级会增加编译、Fusion 和 CUDA Graph。它适合作为启动时间与吞吐的显式 A/B 变量，而不是长期依赖 `--enforce-eager` 掩盖问题：[vLLM Optimization Levels](https://docs.vllm.ai/en/latest/configuration/optimization/)。

对于业务故障恢复，可以先让最常见的短请求形状 Ready，再异步预热长上下文和高并发形状。但在切入正式流量前，至少要完成一条确定性生成请求，不能只根据 `/health=200` 判断模型正确。

## 7. 从存储加载继续向前：GPU 到 GPU 与快照恢复

当节点 NVMe、并行加载和编译缓存都做完后，极致优化就不再是“更快地读文件”，而是复用另一份已经加载好的状态。

### 7.1 GPU 到 GPU 复制权重

NVIDIA ModelExpress 会先寻找已经持有兼容权重的服务副本，优先通过 NIXL 和 P2P RDMA 直接从源 GPU 复制到目标 GPU；没有可用 Peer 时再回退到对象存储流式加载、GDS 或普通 POSIX loader。它还能传输 Triton、DeepGEMM、TileLang、CuTe DSL 和 FlashInfer 等 Kernel Cache。

NVIDIA 公布的一组约 806 GiB DeepSeek-V4-Pro、TP=8、8×B200 数据中，P2P GPU-to-GPU 权重加载约 **11 秒**；进一步复用 Kernel Artifacts 后，完整 API Ready 时间由约 8 分钟缩短到 **1 分 44 秒**。这个结果证明百 GiB 级 DeepSeek 进入两分钟有公开实现，但硬件是 B200 与 ConnectX-7，并且起点是已有兼容的服务中副本，不能直接当作 H20 从远端存储的承诺：[ModelExpress 官方 GitHub Benchmark](https://github.com/ai-dynamo/modelexpress/blob/main/docs/BENCHMARKS.md)、[部署与实现说明](https://github.com/ai-dynamo/modelexpress/blob/main/docs/DEPLOYMENT.md)。

这类方案非常适合滚动发布和横向扩容：旧副本在退出前不仅承接流量，也充当新副本的权重与编译制品源。它不能解决“整个集群没有一份可用副本、模型只在远端对象存储”的首次 Bootstrap。

### 7.2 保留进程或 CPU 中的权重

vLLM Sleep Mode 可以保留服务进程，把权重卸载到 CPU Memory、丢弃 KV Cache，释放 90% 以上 GPU Memory，再通过唤醒恢复。它避免了 Python 启动、模型解析和重新编译，但需要约 156 GiB 甚至更多的 Host Memory，并且不是 Pod 消失后的容灾方案：[vLLM Sleep Mode](https://docs.vllm.ai/en/v0.11.0/features/sleep_mode/)。

### 7.3 保存 GPU 进程状态

NVIDIA Dynamo Snapshot 使用 CRIU 和 `cuda-checkpoint` 保存已经初始化的进程、CUDA Context 和 GPU 状态，再从共享存储恢复。官方公开的 `gpt-oss-120b` 原型使用 GPU Memory Service 后做到 **5 秒以内、约 21 倍加速**。但项目 README 同时明确标注仍处于早期开发、尚未生产就绪；多 GPU、多节点、驱动兼容性以及特权 Node Agent 都需要单独验证：[Dynamo Snapshot 官方 GitHub 项目](https://github.com/ai-dynamo/snapshot)、[5 秒原型的官方文档源文件](https://github.com/ai-dynamo/dynamo/blob/main/docs/fern/pages/blog/2026/dynamo-snapshot.mdx)、[Kubernetes 实现与限制](https://github.com/ai-dynamo/dynamo/blob/main/docs/fern/pages/developer-guide/knowledge-base/kubernetes/kubernetes-operator/snapshot.md)。

ServerlessLLM 在 OSDI 2024 展示了本地 Checkpoint、加载优化格式、多层存储加载和 Locality-aware Scheduling，可将多种 LLM 工作负载的加载延迟降低 10–200 倍；其中 OPT-6.7B 的平均启动为 0.8 秒。这个数字说明研究系统的上限，却不能线性套到 156 GiB DeepSeek：[ServerlessLLM 论文与实验](https://www.usenix.org/conference/osdi24/presentation/fu)。

## 8. 对 156 GiB DeepSeek，极致能做到多久

结合我们的实测、字节下限和公开结果，可以给出一个更诚实的分层答案：

| 场景 | 156 GiB DeepSeek 的时间判断 | 性质 |
| --- | --- | --- |
| 远端模型、镜像和编译缓存都未命中 | 10–30 分钟很常见；我们的量级为 23–30 分钟 | 完整冷启动 |
| 镜像和模型命中节点，本地加载但现场编译/Graph | 当前约 7 分 40 秒至 11 分钟 | 已验证基线 |
| 本地 NVMe + 并行/预分片加载 + 编译缓存 + 收敛 Graph | **2–5 分钟**是较现实的工程目标 | 尚需在 H20 严格 A/B |
| 上述全部完成，再做流式/GDS 与充分流水 | **45–120 秒**是激进目标；低于约 22 秒会违反单块 7 GiB/s NVMe 的纯字节下限 | 高度依赖硬件与 Runtime |
| 已有兼容 GPU Peer，复制权重与 Kernel Cache | 公开 B200 结果为 **1 分 44 秒 Ready**，传输少于 10 秒 | Scale-out，不是首次启动 |
| 预热进程、热池、GPU 状态快照 | **数秒到十几秒**已有公开原型 | 热恢复，不是真冷启动 |

因此，对现有 H20 环境，我们不应该先喊“做到 5 秒”。更合理的目标顺序是：

```text
半小时完整冷启动
  → 模型与镜像命中后稳定低于 10 分钟
  → 编译缓存和 Graph 收敛后进入 2–5 分钟
  → 评估 P2P 权重复制，冲击 2 分钟内
  → 关键服务用热副本或快照，将故障切换压到秒级
```

这里最重要的变化不是某次实验从 11 分钟变成 9 分钟，而是故障策略发生改变：**不能把完整冷启动时间直接当作服务 RTO**。至少应保留一个可接流量的 Combined/备用副本，或者有经过验证的快照与热池；否则任何加载优化退化、缓存失效或节点故障都会重新暴露半小时窗口。

![从完整冷启动到热恢复的分阶段优化路线](../../assets/practices/llm-cold-start-optimization/03-optimization-ladder.png)

## 9. 我们下一轮会怎样做

### 9.1 先完成分段可观测性

每个 Pod 输出结构化启动事件，而不是依赖人工从日志猜测：

```json
{"stage":"model_cache_check","elapsed_ms":1234,"cache_hit":true}
{"stage":"weight_load","elapsed_ms":25102,"bytes":167503724544}
{"stage":"kernel_jit","elapsed_ms":248231,"cache_hit":false}
{"stage":"cuda_graph","elapsed_ms":356020,"shape_count":51}
{"stage":"business_ready","elapsed_ms":663104}
```

Prometheus 至少记录 `pod_created_to_ready_seconds`、各 Stage Histogram、模型和编译缓存命中率、实际读取字节与吞吐，以及第一条真实请求的 TTFT。P95 比单次最快结果更重要。

### 9.2 做四轮严格 A/B

| 轮次 | 只改变一个变量 | 验证目标 |
| --- | --- | --- |
| A | `emptyDir` 回源 → 节点 NVMe 缓存 | 消除重复下载 |
| B | 默认权重加载 → 预分片/并行/流式 loader | 缩短读取、转换与 H2D |
| C | 空编译缓存 → 同指纹预编译缓存 | 消除现场 JIT 与 Autotune |
| D | 全 Shape Graph → 真实流量 Shape 集合 | 缩短 capture，保持吞吐和尾延迟 |

每轮都必须固定模型 Digest、Runtime 镜像、TP、并发、上下文、量化和采样参数，并同时比较启动时间、正确性、稳态吞吐、TTFT、TPOT 和显存。冷启动变快但稳态吞吐明显下降，不是无代价优化。

### 9.3 最后再评估极致路径

在普通加载已经进入 2–5 分钟后，再分别验证：

- GDS/流式 loader 是否真的打通直达 GPU 的数据路径；
- 同型号 GPU 副本间 P2P 权重与 Kernel Cache 复制；
- vLLM Sleep Mode 的 Host Memory 成本与唤醒时间；
- Dynamo Snapshot 对 TP=8、当前 Runtime 和安全策略是否可用；
- 一个常驻备用副本的 GPU 成本，是否低于半小时故障窗口的业务损失。

这条路径最终追求的不是一张漂亮的“最快启动”截图，而是让发布、扩容和故障恢复拥有不同的、可预测的时间预算。

## 10. 结论

我们从 DeepSeek-V4-Pro 一次滚动重启接近半小时开始，最初只盯着模型下载；随后又用约 156 GiB 的 DeepSeek V4 Flash 逐段观测，才发现节点缓存只能消除第一层问题。对于 DeepSeek 这类百 GiB 到近 TiB 级模型，权重格式、并行加载、GPU 搬运、现场 JIT、CUDA Graph 和 warm-up 都可能轮流成为最长路径。

当前最值得投入的不是一个神奇参数，而是三类可复用资产：

1. **模型资产**：不可变 Digest、节点 NVMe 缓存和面向目标并行拓扑的 Checkpoint；
2. **Runtime 资产**：按完整兼容性指纹生成的 CUBIN、`.so`、Triton、DeepGEMM、TileLang、FlashInfer 与 torch.compile Cache；
3. **运行状态资产**：预热副本、GPU Peer、休眠进程或经过验证的快照。

普通 H20 生产路径先把节点热缓存重启做到 2–5 分钟，是合理且可验证的目标；GPU 到 GPU 权重复制的公开实现已经把更大的 DeepSeek V4 Pro 做到 1 分 44 秒 Ready；数秒级则要依赖热池、Sleep 或 GPU 快照，必须诚实地称为恢复，而不是完整冷启动。

模型分发、节点缓存、OCI 制品与供应链的完整设计另见：[大模型与数据制品](../data/model-artifacts.md)。DeepSeek V4 Flash 的逐项启动日志、H20 部署和吞吐基线见：[DeepSeek-V4-Flash-0731 的 H20 部署与压测](deepseek-v4-flash-h20-evaluation.md)。
