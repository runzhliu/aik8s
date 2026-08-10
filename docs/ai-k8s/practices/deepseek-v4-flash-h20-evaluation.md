---
title: DeepSeek-V4-Flash-0731 的 H20 部署与压测
description: 记录 DeepSeek-V4-Flash-0731 在单机八卡 H20 上的资源条件、vLLM 启动流程、性能基线、PD 分离判断与 OpenWebUI 对接方法
status: exploratory
last_reviewed: 2026-08-10
---

# DeepSeek-V4-Flash-0731 的 H20 部署与压测

本文整理一次脱敏后的探索性验证。所有集群名称、Namespace、节点地址、Pod 名称、镜像仓库、对象存储地址、模型路径、网关、账号和凭据均已删除或替换为占位符。文中的性能数字用于说明量级和测试方法，不是生产容量承诺。

## 1. 结论

DeepSeek-V4-Flash-0731 可以在单节点 `8 × NVIDIA H20 96 GB` 上使用 vLLM 启动。已经验证的拓扑是：

```text
OpenAI-compatible client
          │
          ▼
     vLLM API Server
          │
          ▼
  单 Pod、单节点、TP=8
  8 × H20 96 GB
```

这是普通的 Prefill/Decode 共置部署，不是 PD 分离。模型权重、KV Cache 和 CUDA Graph 可以放入 8 张卡，但显存水位约 93 GiB/卡，余量不大。验证期间所有压测请求均成功；完成目标并发形状的运行时预热后，128-token 输入、64-token 输出、并发 8 的总输出吞吐约为 934 tok/s。

部署可行不等于已经生产就绪。正式上线前仍需完成：真实请求回放、长时间阶梯压测、工具调用和 reasoning 正确性、DSpark A/B、故障恢复、鉴权、稳定入口和监控告警。

## 2. 资源与软件条件

### 2.1 硬件起点

建议从以下边界开始验证：

```yaml
resources:
  requests:
    cpu: "64"
    memory: 320Gi
    nvidia.com/gpu: "8"
  limits:
    cpu: "128"
    memory: 512Gi
    nvidia.com/gpu: "8"
```

同时提供至少 64–128 GiB 的 `/dev/shm`。实际 CPU 和内存应根据 tokenizer、并发下载、缓存策略和节点限制调整。模型目录约 155 GiB，实验 Pod 如果使用 `emptyDir`，还要确认节点临时盘容量；删除 Pod 后模型和缓存也会丢失。

单节点 TP=8 不依赖跨节点 RDMA。若改为多节点 TP/PP，才需要单独验证 RDMA、NCCL 拓扑、故障域和 Gang 调度。

### 2.2 已验证的软件组合

本次记录的软件量级如下：

```text
vLLM: 0.26.0 开发版本
PyTorch: 2.11
CUDA runtime: 12.9
GPU: 8 × NVIDIA H20 96 GB
```

DeepSeek V4 需要引擎原生支持 `deepseek_v4` tokenizer、reasoning parser 和 tool-call parser。DSpark 还要求相应的 draft model 实现与修复。不要只根据镜像标签判断兼容性，应在容器内核对 vLLM、PyTorch、CUDA、FlashInfer、DeepGEMM 和模型实现的实际版本。

## 3. 模型准备

### 3.1 模型体积

一次完整检查得到：

```text
总大小：约 155.43 GiB
文件数：55
Safetensors 分片：48
```

部署前应至少检查 `config.json`、tokenizer、generation config、权重索引和全部 Safetensors 分片是否完整。模型目录不要与可写的 Hugging Face、Torch、Triton 编译缓存混用。

### 3.2 S3-compatible 对象存储下载

凭据应从 Secret、工作负载身份或受控凭据系统注入，不要写进命令历史、YAML、镜像或 Git：

```bash
export AWS_ACCESS_KEY_ID='<READ_ONLY_ACCESS_KEY>'
export AWS_SECRET_ACCESS_KEY='<READ_ONLY_SECRET_KEY>'
export AWS_DEFAULT_REGION='<REGION>'
export AWS_EC2_METADATA_DISABLED=true

mkdir -p /workspace/model/DeepSeek-V4-Flash-0731

aws \
  --endpoint-url='https://<BUCKET>.<S3_ENDPOINT>' \
  s3 sync \
  's3://<BUCKET>/<MODEL_PREFIX>/' \
  /workspace/model/DeepSeek-V4-Flash-0731
```

有些对象存储禁止 path-style 请求。如果出现 `PathStyleDomainForbidden`，应把 endpoint 改成包含 Bucket 的 virtual-hosted 地址，即：

```text
https://<BUCKET>.<S3_ENDPOINT>
```

不要通过 `--no-verify-ssl` 长期绕过证书校验。凭据只授予目标 Bucket/Prefix 的只读权限，并在误入终端输出、聊天记录或日志后立即轮换。

一次 155.43 GiB 下载的观测窗口约为 364 秒，平均约 437 MiB/s（3.67 Gbit/s）。相近环境的另一次记录约为 326 秒，二者相差约 12%，属于短期存储、网络和节点负载波动的合理范围。

优化优先级：

1. 优先避免重复下载：使用只读 CephFS/PVC，或由 CPU-only downloader 先准备持久卷。
2. 再测试 AWS CLI `max_concurrent_requests`，例如 10、20、32，观察吞吐与限流。
3. 下载与 GPU 分配解耦，减少昂贵 GPU 在模型同步阶段的空闲时间。
4. 保留校验结果，避免模型不完整时进入耗时的 GPU 初始化阶段。

### 3.3 CephFS 只读挂载

下面只展示通用结构，所有环境值必须由部署方提供：

```yaml
volumeMounts:
  - name: model-store
    mountPath: /models
    readOnly: true

volumes:
  - name: model-store
    cephfs:
      monitors:
        - <CEPH_MONITOR_1>:<PORT>
        - <CEPH_MONITOR_2>:<PORT>
        - <CEPH_MONITOR_3>:<PORT>
      path: <READ_ONLY_MODEL_ROOT>
      readOnly: true
      secretRef:
        name: <CEPH_SECRET>
      user: <CEPH_USER>
```

正式使用前需确认：目标集群可以访问 monitors、Secret 已授权、目录对容器 UID/GID 可读、多 Rank 并发读取吞吐可接受，并且 volume 与 volumeMount 都保持只读。

## 4. 手工探索 Pod

裸 Pod 适合兼容性探索，但不适合作为长期服务。下面模板没有健康探针，避免模型尚未手工启动时被误判；也不包含任何真实节点标签、污点、镜像或存储信息：

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: deepseek-v4-flash-manual
spec:
  restartPolicy: Never
  containers:
    - name: workspace
      image: <VLLM_IMAGE>
      command: ["bash", "-lc", "sleep infinity"]
      stdin: true
      tty: true
      resources:
        limits:
          nvidia.com/gpu: "8"
      volumeMounts:
        - name: model
          mountPath: /workspace/model
        - name: shm
          mountPath: /dev/shm
  volumes:
    - name: model
      emptyDir: {}
    - name: shm
      emptyDir:
        medium: Memory
        sizeLimit: 128Gi
```

如果镜像确实需要 privileged 权限，应说明具体原因并缩短 Pod 生命周期；不能因为是探索环境就默认开启。探索结束后应及时回收 Pod。

## 5. vLLM 启动

已验证的命令结构如下：

```bash
vllm serve /workspace/model/DeepSeek-V4-Flash-0731 \
  --served-model-name DeepSeek-V4-Flash \
  --host 0.0.0.0 \
  --port 8000 \
  --trust-remote-code \
  --tensor-parallel-size 8 \
  --kv-cache-dtype fp8 \
  --block-size 256 \
  --gpu-memory-utilization 0.88 \
  --max-model-len 204800 \
  --tokenizer-mode deepseek_v4 \
  --tool-call-parser deepseek_v4 \
  --enable-auto-tool-choice \
  --reasoning-parser deepseek_v4 \
  --enable-prefix-caching \
  --speculative-config \
    '{"method":"dspark","num_speculative_tokens":5,"draft_sample_method":"greedy"}'
```

首次兼容性验证建议先去掉 `--speculative-config`，建立 target-only 基线，再开启 DSpark 做相同输入的 A/B。还应显式设置符合真实需求的 `--max-num-seqs`，避免为完全用不到的高并发 shape 捕获大量 CUDA Graph。

## 6. 为什么加载权重后还不能立刻接请求

加载权重只完成参数从存储到 GPU 的搬运。vLLM 在开放 API 前还会初始化 TP 通信、统计峰值显存、分配 KV Cache、预热 DeepGEMM/TileLang/FlashInfer kernel、初始化 DSpark，并捕获多种 batch shape 的 CUDA Graph。

一次冷启动记录如下：

| 阶段 | 耗时 | 说明 |
| --- | ---: | --- |
| Safetensors/模型加载 | 最慢 Rank 26.9 秒 | 权重读取和分发很快 |
| DeepGEMM kernel warmup | 159 秒 | 冷启动主要成本之一 |
| CUDA Graph capture | 229 秒 | 最大单项成本，每卡约占 3.17 GiB |
| Engine profile/KV/warmup 总计 | 605.23 秒 | 包含显存 profiling 和缓存创建 |
| `vllm serve` 到 API Ready | 约 723 秒 | 约 12 分 03 秒 |

引擎最终为每张卡分配约 58.36 GiB KV Cache，总理论容量约 176 万 Token。这个容量是引擎根据当前配置计算的池大小，不代表单请求就适合直接使用最大上下文。

可测试的冷启动优化：

- 探索配置使用 `--enforce-eager` 跳过 CUDA Graph，代价通常是稳态性能下降。
- 降低并显式设置 `--max-num-seqs`，减少需要捕获的 shape。
- A/B 测试 `fast_moe_cold_start`，但必须做正确性回归。
- 将编译缓存放在可复用卷中，验证第二次启动是否能够复用。
- target-only 与 DSpark 分别建立启动时间和吞吐基线。

## 7. 当前拓扑不是 PD 分离

当前请求路径是：

```text
Client
  → 一个 vLLM API/Engine
  → TP=8 执行 Prefill
  → KV Cache 留在同一 Engine
  → 同一组 TP=8 GPU 执行 Decode
  → Response
```

`TP=8` 表示一次模型计算跨 8 张卡；DSpark 是推测解码。这两者都不等于 PD 分离。

真正的 PD 分离需要独立的 Prefill 和 Decode 实例、KV Cache 传输 connector，以及按阶段路由请求的 Router：

```text
Client → Router → Prefill 实例
                    │
                    └── KV Cache transfer ──→ Decode 实例 → Response
```

PD 的主要价值是分别控制 TTFT 与 ITL，并减少长 Prompt Prefill 对正在 Decode 的请求造成的尾延迟干扰。它不会天然提高吞吐；短 Prompt、低 QPS 或只有一套 8 GPU 预算时，Router 和 KV 传输反而可能增加延迟与成本。

适合考虑 PD 的条件：

- 流量持续较高，长 Prompt 明显抬高 p95/p99 ITL；
- TTFT 与 ITL 都有严格且不同的 SLO；
- Prefill/Decode 需要独立扩缩容；
- 有足够 GPU 和高带宽低时延的 KV 传输网络；
- 已经具备 Router、Connector、监控、重试和故障恢复能力。

公平对比必须固定总 GPU 数。例如比较两个普通 TP=8 实例与一个 Prefill TP=8 加一个 Decode TP=8，而不是拿 8 GPU 普通实例直接对比 16 GPU 的 1P+1D。

## 8. 探索性压测数据

压测客户端和服务位于同一个 Pod，访问 loopback OpenAI-compatible API。使用 random dataset、固定 Token 长度、`temperature=0` 和 `--ignore-eos`，因此没有包含入口网关与跨节点网络开销。

指标含义：

- TTFT：请求到第一个 Token，主要受排队和 Prefill 影响；
- TPOT：除第一个 Token 外，平均生成一个 Token 的时间；
- ITL：流式输出相邻 Token 的间隔；
- E2EL：完整请求耗时；
- Output tok/s：整个实例的输出总吞吐，不是单请求速度。

### 8.1 稳态结果

| 场景 | 请求成功 | req/s | 输出 tok/s | p50/p95/p99 TTFT | p95 TPOT | p95 ITL | p95 E2EL |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 128 in / 64 out，C=1 | 16/16 | 3.91 | 250.19 | 49 / 49 / 49 ms | 4.84 ms | 9.07 ms | 352.88 ms |
| 128 in / 64 out，C=4 | 32/32 | 9.65 | 617.77 | 60 / 96 / 128 ms | 8.02 ms | 37.13 ms | 591.94 ms |
| 128 in / 64 out，C=8 | 64/64 | 14.59 | 933.70 | 71 / 233 / 233 ms | 11.53 ms | 43.63 ms | 810.29 ms |
| 4096 in / 128 out，C=4 | 16/16 | 2.16 | 277.00 | 760 / 1391 / 1423 ms | 16.00 ms | 75.07 ms | 2944.96 ms |

短请求从 C=1 增至 C=8，总输出吞吐约为 3.73 倍，同时 p95 TTFT 从约 49 ms 增至 233 ms。这是 continuous batching 用更多单请求延迟换取总吞吐的正常表现。4K 输入的 p95 TTFT 约 1.39 秒，说明 Prefill 已成为更明显的延迟组成。

DSpark 接受率在这些测试中约为 34%–59%。接受率不能单独证明收益，仍需与关闭 DSpark 的同请求 A/B 比较吞吐、延迟、正确性和功耗。

### 8.2 API Ready 后仍可能发生 JIT

第一次测试并发 8 时，p95 TTFT 达到约 33.4 秒。服务日志明确记录推理期间触发 TileLang JIT，其中一个 kernel 编译约 9 秒。相同参数复跑后，p95 TTFT 恢复到约 233 ms，输出吞吐从约 92 tok/s 恢复到约 934 tok/s。

这说明 `Application startup complete` 不代表所有真实输入长度和并发 shape 都已编译。上线前的业务 warmup 应至少覆盖：

1. 目标并发档位；
2. 常见输入长度；
3. 最大输入长度附近；
4. Chat、reasoning 和 tool call 等真实请求形态。

压测工具的 warmup 请求数至少应覆盖目标并发，而不是只发送一个串行请求。

### 8.3 GPU 采样

每秒一次的 `nvidia-smi` 采样得到：

| 场景 | 活跃样本中 8 卡平均利用率 | 峰值 | 活跃平均单卡功耗 | 最大单卡显存 |
| --- | ---: | ---: | ---: | ---: |
| 128/64，C=4 | 96.8% | 100% | 289.9 W | 93,127 MiB |
| 128/64，C=8 | 74.2% | 100% | 267.8 W | 93,169 MiB |
| 4096/128，C=4 | 97.4% | 100% | 308.7 W | 93,273 MiB |

测试持续时间较短，GPU 数据只能用于判断负载形态，不能作为精确能耗结论。显存已经接近卡的可见容量，扩大 Graph、提高显存利用率或增加额外组件前必须重新验证 OOM 风险。

### 8.4 压测命令

```bash
vllm bench serve \
  --backend openai \
  --base-url http://127.0.0.1:8000 \
  --endpoint /v1/completions \
  --model /workspace/model/DeepSeek-V4-Flash-0731 \
  --served-model-name DeepSeek-V4-Flash \
  --tokenizer /workspace/model/DeepSeek-V4-Flash-0731 \
  --tokenizer-mode deepseek_v4 \
  --dataset-name random \
  --num-prompts 64 \
  --num-warmups 8 \
  --random-input-len 128 \
  --random-output-len 64 \
  --ignore-eos \
  --temperature 0 \
  --request-rate inf \
  --max-concurrency 8 \
  --percentile-metrics ttft,tpot,itl,e2el \
  --metric-percentiles 50,95,99 \
  --save-result
```

正式容量测试应改用脱敏后的真实请求分布，在独立压测节点上通过实际服务入口运行 10–30 分钟的固定 request-rate 阶梯，并同时记录失败率、队列、GPU、显存、功耗和 tokens/s/GPU。

## 9. 对接 OpenWebUI

vLLM 提供 OpenAI-compatible API，可以被 OpenWebUI 使用。稳定链路应是：

```text
OpenWebUI
   │
   ▼
内部鉴权入口或跨集群网关
   │
   ▼
Service
   │
   ▼
vLLM Pod :8000
```

不要把 Pod IP 作为长期配置。Pod IP 会随重建变化，跨集群 Pod CIDR 即使当前可路由，也不具备服务发现、健康摘除、鉴权或稳定性保证。至少应创建选择目标 Pod 的 Service；跨集群场景再通过受控网关、服务网格或其他稳定入口暴露。

先从 OpenWebUI 所在网络验证：

```bash
curl -fsS 'http://<MODEL_ENDPOINT>/health'
curl -fsS 'http://<MODEL_ENDPOINT>/v1/models'
```

然后在 OpenWebUI 的管理员连接设置中添加 OpenAI-compatible connection：

```text
Base URL: http://<MODEL_ENDPOINT>/v1
API Key:  <API_KEY_OR_NON_EMPTY_PLACEHOLDER>
Model:    DeepSeek-V4-Flash
```

如果 vLLM 没有配置 `--api-key`，OpenWebUI 版本仍要求填写非空 Key 时可以使用不具备权限含义的占位值；正式共享服务应在 vLLM 或前置网关增加真实鉴权。若通过环境变量初始化，可使用 OpenWebUI 的 `OPENAI_API_BASE_URLS`、`OPENAI_API_KEYS` 和对应 connection config，但持久化配置开启后，数据库中的管理员设置可能覆盖后续环境变量变化。

接入后依次验证模型列表、普通对话、流式输出、reasoning 内容、长文本和 tool call。UI 能列出模型只代表 `/v1/models` 可访问，不代表 chat template 与 parser 已经正确。

## 10. 生产化检查表

- 模型文件有完整性校验，并使用可复用只读存储；
- 镜像版本和 DeepSeek V4 kernel 路径已静态核验；
- target-only、DSpark、长上下文和工具调用分别验收；
- 业务 warmup 覆盖真实并发和长度，推理日志无新 JIT；
- Service、鉴权入口、超时、限流、健康检查和优雅终止已配置；
- 压测覆盖 p50/p95/p99 TTFT、ITL、E2EL、失败率和 GPU 指标；
- 若评估 PD，固定总 GPU 数并计算 tokens/s/GPU 与尾延迟收益；
- GPU 资源有明确的申请、告警、回收和回滚流程。

## 11. 参考资料

- [DeepSeek-V4-Flash-0731 模型卡](https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash-0731)
- [vLLM DeepSeek-V4-Flash Recipe](https://recipes.vllm.ai/deepseek-ai/DeepSeek-V4-Flash)
- [SGLang DeepSeek V4 Cookbook](https://docs.sglang.io/cookbook/autoregressive/DeepSeek/DeepSeek-V4)
- [vLLM Disaggregated Prefilling](https://docs.vllm.ai/en/v0.8.0/features/disagg_prefill.html)
- [vLLM Parallelism and Scaling](https://docs.vllm.ai/en/v0.17.1/serving/parallelism_scaling/)
- [vLLM Compilation Configuration](https://docs.vllm.ai/en/v0.20.0/api/vllm/config/compilation/)
- [AWS CLI S3 Configuration](https://docs.aws.amazon.com/cli/latest/topic/s3-config.html)
