---
title: AIBrix 真实 GPU 实测：从两机推理到八节点碎片 GPU
description: 在生产 Kubernetes 集群使用 NVIDIA L20、AIBrix v0.7.0、RayClusterFleet、StormService 和 vLLM，验证两机模型并行、NIXL P/D 分离、八节点 Qwen3-235B FP8，以及 DeepSeek 70B 的四节点单卡、两节点双卡和单节点四卡拓扑
status: lab
last_reviewed: 2026-08-08
---

# AIBrix 真实 GPU 实测：从两机推理到八节点碎片 GPU

前一轮实验使用 CPU mock 验证了 AIBrix v0.7.0 的控制面、模型发现、路由、StormService 和自动扩缩容。本轮继续在一套生产 Kubernetes 集群中使用真实 NVIDIA L20 和本地模型权重，回答四个更关键的问题：

1. `RayClusterFleet` 能否让一个 vLLM Engine 跨两台机器共同执行同一个模型；
2. `StormService` 能否让 Prefill、Decode 分别运行在不同 GPU 节点，并通过 NIXL 交接 KV Cache；
3. 当每台节点都只剩一张空闲 GPU 时，能否把八张碎片 L20 组成一个 235B MoE 推理实例。
4. 相同四张 L20 分别采用四节点单卡、两节点双卡和单节点四卡时，单流推理性能相差多少。

最终结果：两机两卡的 Qwen2.5-32B BF16 Ray Pipeline Parallel 推理成功；两机两卡的 Qwen2.5-Coder-32B GPTQ Int4 P/D 服务成功完成 AIBrix Gateway → Prefill → NIXL KV Transfer → Decode → 响应的完整链路；Qwen3-235B-A22B FP8 成功运行在八台节点、每台一张 L20 的碎片拓扑上；DeepSeek-R1-Distill-Llama-70B BF16 依次完成四节点单卡 TP=1/PP=4、两节点双卡 TP=2/PP=2 和单节点四卡 TP=4/PP=1 实测，单流 Decode 分别约为 5.13、9.92 和 18.33 token/s。

本次以**功能、拓扑和数据路径验证**为主，并为 235B 实例记录了一组热请求 TTFT、TPOT 和吞吐样本。样本来自非独占生产实验窗口，不是正式容量结论；生产选型仍需使用真实流量分布进行并发、长上下文、故障和 Goodput 基准测试。

!!! warning "公开文档已经脱敏"
    本文不会记录公司内部集群名、节点地址、Ceph monitor、模型卷真实路径、Registry、Ingress 域名、Pod IP 或 Secret。所有环境相关值统一写成 `<...>` 占位符，不能直接复制后执行。

## 1. 测试环境与版本

| 项目 | 实测值 |
| --- | --- |
| AIBrix | v0.7.0 |
| GPU | NVIDIA L20，单卡约 46 GiB 显存 |
| 两机 Ray 镜像 | vLLM 0.8.3 开发构建，Ray 2.43.0 |
| P/D 与八节点 Ray 镜像 | vLLM 0.10.1 开发构建，Ray 2.48.0 |
| KV Connector | NIXL Connector |
| P/D 传输后端 | NIXL + UCX |
| 模型存储 | CephFS，只读挂载 |
| Namespace | 独立实验 Namespace，便于整体清理 |
| 请求入口 | AIBrix Envoy Gateway，OpenAI-Compatible API |

镜像版本来自容器运行时实测，而不是只读取 YAML 标签。某些企业镜像的标签、AIBrix 示例参数和实际 Python 包版本不完全一致，排查兼容性时应在容器中确认：

```bash
python3 -c 'import vllm, ray; print(vllm.__version__, ray.__version__)'
```

## 2. 模型和验证矩阵

| 模型 | 精度 | 编排 | GPU 拓扑 | 结果 |
| --- | --- | --- | --- | --- |
| Qwen2.5-3B-Instruct | BF16 | RayClusterFleet | 单节点单卡 | OpenAI API 成功，作为 Ray 基线 |
| Qwen2.5-3B-Instruct | BF16 | StormService P/D | Prefill 1 卡 + Decode 1 卡 | P/D 控制流成功，作为 NIXL 基线 |
| Qwen2.5-32B-Instruct | BF16 | RayClusterFleet | 两节点，每节点 1 卡 | PP=2，多机推理成功 |
| Qwen2.5-Coder-32B-Instruct | GPTQ Int4 | StormService P/D | 两节点，每节点 1 卡 | NIXL KV 传输和生成成功 |
| Qwen3-235B-A22B-Instruct | FP8 | RayClusterFleet | 八节点，每节点 1 卡 | PP=8，加载与 OpenAI API 生成成功 |
| DeepSeek-R1-Distill-Llama-70B | BF16 | RayClusterFleet | 四节点，每节点 1 卡 | PP=4，加载与 OpenAI API 生成成功 |
| DeepSeek-R1-Distill-Llama-70B | BF16 | RayClusterFleet | 两节点，每节点 2 卡 | TP=2、PP=2；同模型同参数 A/B 中 Decode 提升约 93% |
| DeepSeek-R1-Distill-Llama-70B | BF16 | RayClusterFleet | 单节点 4 卡 | TP=4、PP=1；热态 Decode 约 18.33 token/s |

两个 32B 实验验证的能力并不相同：

- Ray 实验把**同一个 Engine 的模型层**切到两台机器，两个 Ray Rank 共同完成 Prefill 和 Decode；
- P/D 实验运行**两个完整 Engine**，Prefill、Decode 各加载一份量化权重，再把 KV Cache 从前者传给后者。

因此不能把 Ray Worker 理解成 Decode Worker，也不能因为 P/D 使用两张 GPU 就认为模型权重只保存了一份。

## 3. 模型卷必须保持只读

模型目录由多个生产服务共享。本次没有给模型目录写权限，并同时在 CephFS Volume 与容器 VolumeMount 两层声明只读：

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

仅把 CephFS 设为只读还不够。Hugging Face、Transformers、vLLM 和 Torch Compile 可能默认向模型目录附近写缓存，因此显式改到临时盘：

```yaml
env:
  - name: HF_HOME
    value: /tmp/huggingface
  - name: TRANSFORMERS_CACHE
    value: /tmp/huggingface/transformers
  - name: XDG_CACHE_HOME
    value: /tmp/.cache
```

验收时检查 Pod Spec 和实际 Mount 均为只读，但不要用 `touch` 等命令主动写共享模型目录来做破坏性测试。

## 4. RayClusterFleet 两机模型并行

### 4.1 拓扑

Qwen2.5-32B-Instruct 的 BF16 Safetensors 约 61 GiB。单张 L20 无法稳定容纳权重、运行时和 KV Cache，因此使用两个 Pod：

```text
AIBrix Gateway
  → Ray Head / vLLM API / GPU 0
       │
       └── Ray Worker / GPU 1

vLLM: TP=1, PP=2, distributed-executor-backend=ray
```

Head 和 Worker 都请求一张 GPU，并使用强制 Pod Anti-Affinity，保证它们不会落到同一节点：

```yaml
affinity:
  podAntiAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
      - labelSelector:
          matchExpressions:
            - key: model.aibrix.ai/name
              operator: In
              values: [qwen2-5-32b-ray-2n]
        topologyKey: kubernetes.io/hostname
```

核心 vLLM 参数如下：

```bash
vllm serve /models/Qwen2.5-32B-Instruct \
  --served-model-name qwen2-5-32b-ray-2n \
  --tensor-parallel-size 1 \
  --pipeline-parallel-size 2 \
  --distributed-executor-backend ray \
  --dtype bfloat16 \
  --gpu-memory-utilization 0.90 \
  --max-model-len 8192 \
  --max-num-seqs 8
```

这里选择 PP=2 而不是跨节点 TP=2，主要是为了先验证跨节点执行和 AIBrix 编排。PP 会在流水段之间传递激活；TP 则会在每层产生更频繁的 Collective，对网络带宽和延迟更敏感。

### 4.2 验证证据

Ray Runtime 返回两个 Alive Node，每个 Node 各发布一张 L20，集群合计 2 GPU。vLLM 完成全部权重分片加载，服务稳定运行且无容器重启。

直接访问 vLLM 与经过 AIBrix Gateway 的请求都返回成功：

```json
{
  "model": "qwen2-5-32b-ray-2n",
  "choices": [
    {"message": {"role": "assistant", "content": "OK"}}
  ]
}
```

这证明：

- Ray Head 和 Worker 已组成一个资源池，而不是两个独立模型副本；
- vLLM 实际取得两张 GPU 并完成 PP=2 初始化；
- Service 只选择 Ray Head API Pod，Worker 不会成为 AIBrix 请求 Endpoint；
- AIBrix 模型发现和 Gateway 路由可以访问多机 Engine。

## 5. StormService 两机 P/D 分离

### 5.1 为什么使用量化 32B

P/D 两端都需要加载模型权重。为了让每个 Role 使用单张 L20，同时给 KV Cache 留出足够空间，本次选择约 18 GiB 的 Qwen2.5-Coder-32B GPTQ Int4 权重。

```text
AIBrix Gateway / P/D Router
  ├── Prefill Role / GPU A / 完整量化权重
  │       └── 计算 Prompt KV
  │
  └── Decode Role / GPU B / 完整量化权重
          └── 通过 NIXL 获取 KV 后继续生成
```

StormService 中 Prefill、Decode 各一个副本，并使用强制 Anti-Affinity 保证跨节点。两个 Role 都启用：

```text
kv_connector = NixlConnector
kv_role      = kv_both
UCX_TLS      = tcp,cuda_copy,cuda_ipc
```

`kv_both` 并不代表两个 Role 没有分工。AIBrix Gateway 会为具体请求注入不同的 `kv_transfer_params`，vLLM 再按请求承担 Producer 或 Consumer 角色。

### 5.2 验证证据

两侧均成功完成以下初始化：

- GPTQ 权重自动转换为 GPTQ Marlin Kernel；
- 单侧加载约 18 GiB 权重；
- NIXL Connector 和 UCX Agent 初始化成功；
- KV Cache 注册完成；
- 16K 上下文配置下仍保留约 21 GiB KV Cache 空间；
- Prefill、Decode Pod 均 Ready，且无重启。

经过 AIBrix Gateway 发送同一条请求后，脱敏日志出现了两组互补证据：

```text
Prefill:
  max_tokens=1
  do_remote_decode=true
  do_remote_prefill=false

Decode:
  max_tokens=<REQUEST_MAX_TOKENS>
  do_remote_prefill=true
  do_remote_decode=false
  remote_engine_id=<REDACTED>
  remote_block_ids=<REDACTED>
```

最终响应内容为：

```text
PD-32B-OK
```

这比“两个 Pod 都 Ready”更强：它证明同一请求先在 Prefill 侧计算 KV，再由 Decode 侧引用远端 Engine 和 Block 信息继续生成。若只看到两个 Pod 各自能回答请求，不能声称 P/D 数据路径已经验证。

## 6. 通过 AIBrix Gateway 验收

测试时可以把 Envoy Service 临时转发到本地，避免在文档中记录内部入口：

```bash
kubectl -n <ENVOY_NAMESPACE> port-forward \
  svc/<AIBRIX_ENVOY_SERVICE> 28999:80
```

Ray 多机请求：

```bash
curl http://127.0.0.1:28999/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -H 'model: qwen2-5-32b-ray-2n' \
  --data '{
    "model": "qwen2-5-32b-ray-2n",
    "messages": [{"role": "user", "content": "只回答 OK"}],
    "temperature": 0,
    "max_tokens": 16
  }'
```

P/D 请求：

```bash
curl http://127.0.0.1:28999/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -H 'model: qwen2-5-coder-32b-pd' \
  --data '{
    "model": "qwen2-5-coder-32b-pd",
    "messages": [{"role": "user", "content": "只回答 PD-32B-OK"}],
    "temperature": 0,
    "max_tokens": 32
  }'
```

除 HTTP 200 和答案内容外，还应同时检查：

1. AIBrix Route 的 `Accepted=True` 与 `ResolvedRefs=True`；
2. Service Endpoint 只包含应对外服务的 Pod；
3. Ray Cluster 中每个 Node 的 GPU Resource；
4. Prefill/Decode 两侧是否记录同一 Request ID；
5. `kv_transfer_params` 是否呈现互补 Producer/Consumer 语义；
6. 推理前后 Pod Restart Count 是否保持为 0。

## 7. Console 与测试工具

为了快速调用和可视化，本次在相同实验 Namespace 部署：

- AIBrix Console：查看 AIBrix 管理界面；
- Open WebUI：交互式切换模型并测试聊天；
- Hoppscotch：构造 OpenAI-Compatible HTTP 请求；
- k6 Web Dashboard：执行简单负载并观察请求结果。

这些工具只是客户端和实验入口，不能替代 Prometheus/Grafana、分布式 Trace、GPU 指标、请求日志和正式压测平台。AIBrix Console 也不应被理解成“自动导入集群内所有历史 Deployment”的通用 Kubernetes Dashboard；模型是否可见仍取决于 AIBrix 标签、Endpoint、API 数据模型和 Console Backend 的实现。

所有测试工具集中放在同一 Namespace，清理时不会跨 Namespace 扫描或按模糊名称删除资源。

## 8. 八个碎片节点运行 Qwen3-235B FP8

### 8.1 为什么选择 PP=8

这次最现实的约束不是集群没有八张 GPU，而是**每台节点都只剩一张 L20**。Qwen3-235B-A22B-Instruct FP8 权重约 220 GiB，八卡平均静态权重约 27.5 GiB；考虑未量化模块、运行时和 KV Cache 后，容量仍落在单卡约 46 GiB 的范围内。

可选并行方式并不等价：

| 方式 | 跨节点通信特征 | 碎片 L20 + 10Gb 网络判断 |
| --- | --- | --- |
| TP=8 | 几乎每层都有 Collective | 对带宽和尾延迟敏感，不作为第一轮 |
| EP=8 | MoE Token 在 Expert 间进行 All-to-All | 235B MoE 可用，但 10Gb 网络代价很高 |
| PP=8 | 相邻流水段传递激活 | 单请求有流水线延迟，但最适合先验证“能否运行” |

因此本次使用 `TP=1、PP=8`。这不是追求最高性能的拓扑，而是把八台机器上的单卡碎片转化为一个可用的大模型实例。

```text
AIBrix RayClusterFleet
  └── KubeRay 创建 RayCluster
       ├── Head / PP Rank 0 / vLLM API / 1×L20
       ├── Worker / PP Rank 1 / 1×L20
       ├── Worker / PP Rank 2 / 1×L20
       ├── ...
       └── Worker / PP Rank 7 / 1×L20

94 个 Transformer Layer：11, 12, 12, 12, 12, 12, 12, 11
```

这里四层组件的职责要分清：

- **AIBrix RayClusterFleet**：声明副本、滚动策略、标签和模型入口，不执行模型并行；
- **KubeRay**：创建 Head、Worker、Service，并让八个 Ray Node 组成集群；
- **Ray**：提供跨节点资源池和 Placement Group，原子预留八张 GPU；
- **vLLM**：识别模型架构、划分 PP Rank、加载权重、管理 KV Cache 并暴露 OpenAI-Compatible API。

### 8.2 先验证镜像，不要只相信 Tag

已验证的镜像标签写着 vLLM 0.10.0，但容器内实际版本是 vLLM 0.10.1 开发构建、Ray 2.48.0。部署前直接在已有 Pod 中检查：

```bash
/usr/bin/python3 -c '
import ray, vllm
from vllm.model_executor.models.registry import ModelRegistry

arch = "Qwen3MoeForCausalLM"
print("vllm:", vllm.__version__)
print("ray:", ray.__version__)
print("registered:", arch in ModelRegistry.get_supported_archs())
print("pp_supported:", ModelRegistry.is_pp_supported_model([arch]))
'
```

本次输出确认 Qwen3 MoE 已注册、支持 Pipeline Parallel，且镜像已经包含 Ray。相同镜像没有注册 `Qwen3_5MoeForConditionalGeneration`，所以不能因为名字只差 `.5` 就直接用于 Qwen3.5-397B；后者需要更新 vLLM，并再次确认 Ray 是否仍在镜像中。

### 8.3 调度：每个 Pod 只拿一张卡，并强制分散

RayClusterFleet 使用七个 Worker，加上 Head 正好八个 Ray Node。节点标签在不同企业环境中会不同，下面使用通用占位值：

```yaml
spec:
  template:
    spec:
      rayVersion: 2.48.0
      headGroupSpec:
        template:
          spec:
            affinity: &fragmented_l20_affinity
              nodeAffinity:
                requiredDuringSchedulingIgnoredDuringExecution:
                  nodeSelectorTerms:
                    - matchExpressions:
                        - key: <GPU_WORKLOAD_LABEL>
                          operator: In
                          values: [<LLM_SERVING_VALUE>]
                        - key: <GPU_MODEL_LABEL>
                          operator: In
                          values: [<L20_VALUE>]
              podAntiAffinity:
                requiredDuringSchedulingIgnoredDuringExecution:
                  - labelSelector:
                      matchLabels:
                        model.aibrix.ai/name: qwen3-235b-fp8-ray-8n
                    topologyKey: kubernetes.io/hostname
            containers:
              - name: ray-head
                resources: &one_l20
                  requests:
                    cpu: "8"
                    memory: 64Gi
                    nvidia.com/gpu: "1"
                  limits:
                    cpu: "16"
                    memory: 96Gi
                    nvidia.com/gpu: "1"
      workerGroupSpecs:
        - groupName: worker-group
          replicas: 7
          minReplicas: 7
          maxReplicas: 7
          template:
            spec:
              affinity: *fragmented_l20_affinity
              containers:
                - name: ray-worker
                  resources: *one_l20
```

强制 Pod Anti-Affinity 不是装饰。没有它时，调度器可能把多个单卡 Pod 放到同一台仍有多张空闲卡的节点，最终拓扑与“每台一张碎片卡”的验证目标不同。

vLLM Head 的核心参数如下：

```bash
vllm serve /models/Qwen3-235B-A22B-Instruct-2507-FP8 \
  --served-model-name qwen3-235b-fp8-ray-8n \
  --tensor-parallel-size 1 \
  --pipeline-parallel-size 8 \
  --distributed-executor-backend ray \
  --quantization fp8 \
  --dtype auto \
  --gpu-memory-utilization 0.88 \
  --max-model-len 4096 \
  --max-num-seqs 1 \
  --enforce-eager \
  --trust-remote-code
```

第一轮把上下文压到 4K、并发压到 1，并关闭 CUDA Graph，目的是减少显存和编译变量。功能跑通后再分别扩大上下文、并发和图优化，不要一次改动所有参数。

### 8.4 从调度到 API Ready 的实测过程

八个 Pod 一次性调度到八台不同节点，没有出现 Pending。Ray 返回八个 Active Node，Placement Group 原子预留 8/8 GPU，随后 vLLM 把 94 层划分为 `[11,12,12,12,12,12,12,11]`。

| 阶段 | 实测 |
| --- | ---: |
| 首次拉取运行时镜像 | 约 147 秒，镜像约 10.9 GB |
| 24 个 Safetensors Shard 加载 | 约 163–166 秒 |
| Engine Profile、KV Cache 创建和 Warmup | 约 5.6 秒 |
| 容器启动到 API Ready | 约 3 分 45 秒 |
| Pod 创建到 API Ready，包含首次拉镜像 | 约 6 分 14 秒 |
| 每个 PP Rank 的模型显存 | 约 30.20 GiB |
| 每卡剩余 KV Cache | 约 8.48 GiB |

加载进度约 7 秒一个 Shard。不能简单用“单 Shard 文件大小 ÷ 7 秒”当作 CephFS 吞吐，因为每个 PP Worker 会遍历 Shard、只读取属于自己 Rank 的张量，同时还包含反序列化、CPU 到 GPU 拷贝和 FP8 初始化。对运维更有意义的指标是：八个 Worker 并发读取时，整个 235B 模型约三分钟完成权重加载，且没有出现 CephFS 超时或 Pod 重启。

### 8.5 API 与性能样本

OpenAI-Compatible Chat Completions 返回了正确中文结果，证明不是“Pod Ready 但 Engine 不可用”。一次 64 Token 的受控热请求得到：

| 指标 | 实测值 |
| --- | ---: |
| TTFT | 4.859 秒 |
| 端到端延迟 | 12.647 秒 |
| 稳态 Decode | 8.089 token/s |
| TPOT | 约 124 ms/token |
| 包含 TTFT 的平均输出速度 | 约 5.1 token/s |
| 日志窗口中的 Prefill | 约 40–74 token/s |

该时间窗口仍存在少量交互式请求，不是独占压测。首次请求还触发了 Ray Compiled DAG Communicator 初始化，日志窗口一度只有 0.1–1.5 token/s；通信组热身后，Decode 稳定在约 7.6–8.1 token/s。

vLLM 报告最小 PP Stage 的 GPU KV Cache 容量约 370K Token，并给出 4K 请求约 90 倍的理论并发容量，但本次显式设置了 `max_num_seqs=1`，**实际并发仍然只有 1**。容量日志不能代替并发压测结果。

### 8.6 能跑不等于已经优化

L20 上出现两类重要但不阻断启动的告警：

```text
CutlassBlockScaledGroupedGemm not supported on the current platform
Using default W8A8 Block FP8 / Fused MoE config; performance might be sub-optimal
```

这意味着 vLLM 使用了正确性回退路径和默认 Kernel 配置，没有找到针对 L20 与当前 MoE Shape 调优的配置。结合 PP=8 的七段跨节点传输，本次结果应解释为：

- **容量和功能成立**：碎片卡可以组成一个 235B FP8 实例；
- **交互可用但 TTFT 偏高**：热请求约 4.9 秒首 Token；
- **稳态生成尚可**：单请求约 8 token/s；
- **不能直接作为生产容量值**：仍需压测并发、长上下文、取消、超时和故障恢复。

## 9. 四个碎片节点运行 DeepSeek-R1-Distill-Llama-70B

### 9.1 先识别真正的权重集合

模型目录整体占用约 395 GiB，第一次看到这个数字时不能直接得出“四卡放不下”的结论。继续拆分后发现目录包含三份约 132 GiB 的数据：

- 根目录的 17 个 Safetensors Shard，约 132 GiB；
- 一个版本子目录中的另一份权重，约 132 GiB；
- Git LFS 仓库对象，约 132 GiB。

根目录 `model.safetensors.index.json` 只索引根目录的 17 个 Shard，vLLM 实际加载约 132 GiB，而不是把整个 395 GiB 目录送入 GPU。容量评估应以 Index 引用的文件为准，不能只看 `du -sh <MODEL_DIR>`。

模型配置是 80 层 `LlamaForCausalLM`、BF16 Dense 权重。部署前在同版本 vLLM 容器中确认 `LlamaForCausalLM` 已注册且支持 Pipeline Parallel。

### 9.2 四节点 RayClusterFleet

沿用 Qwen3 实验的单卡节点标签、Anti-Affinity、只读 CephFS 和运行时镜像，改为一个 Head 加三个 Worker：

```bash
vllm serve /models/DeepSeek-R1-Distill-Llama-70B \
  --served-model-name deepseek-r1-70b-ray-4n \
  --tensor-parallel-size 1 \
  --pipeline-parallel-size 4 \
  --distributed-executor-backend ray \
  --dtype bfloat16 \
  --gpu-memory-utilization 0.88 \
  --max-model-len 4096 \
  --max-num-seqs 1 \
  --enforce-eager \
  --trust-remote-code
```

四个 Pod 一次调度到四台不同 L20 节点。Ray 返回四个 Active Node，Placement Group 原子占用 4/4 GPU；80 层被均匀切成四个 20 层 PP Stage。

| 阶段或资源 | 实测 |
| --- | ---: |
| 根目录权重 | 约 132 GiB，17 个 Shard |
| 权重加载 | 约 28.8–29.1 秒 |
| 每个 PP Rank 模型显存 | 约 33.864 GiB |
| 每卡剩余 KV Cache | 约 4.63 GiB |
| Engine Profile、KV Cache 创建和 Warmup | 约 1.89 秒 |
| 容器启动到 API Ready | 约 83 秒 |
| 最小 PP Stage KV 容量 | 约 60K Token |

运行时镜像此前已被节点缓存，因此这次没有 10.9 GB 首次拉取时间。与 Qwen3 MoE FP8 不同，DeepSeek Distill 70B 是 Dense BF16，没有出现 FP8 或 Fused-MoE Kernel 回退告警。

### 9.3 API 验证与真实队头阻塞

OpenAI-Compatible API 成功返回 `<think>` 推理内容，证明四个 PP Rank 已共同完成生成。DeepSeek-R1 默认可能先生成较长思考过程，过小的 `max_tokens` 会让响应在最终答案前以 `finish_reason=length` 截断；客户端需要正确展示 Reasoning，并为思考 Token 预留预算。

测试窗口中 Open WebUI 自动发现新模型并产生了最长约 2K–3.8K Token 的交互请求。由于本次保守设置 `max_num_seqs=1`，日志出现 `Running=1、Waiting=1–3`。三个 64 Token 测试请求得到：

| 请求 | 排队后 TTFT | E2E | 开始生成后的 Decode |
| --- | ---: | ---: | ---: |
| 1 | 97.390 秒 | 109.642 秒 | 5.142 token/s |
| 2 | 55.577 秒 | 67.829 秒 | 5.142 token/s |
| 3 | 65.226 秒 | 77.477 秒 | 5.142 token/s |

这些 TTFT 主要是排队时间，**不能当作空载模型 TTFT**；但它们真实揭示了生产风险：R1 长思考请求遇到单并发 Engine 时会造成严重 Head-of-Line Blocking。日志窗口中的 Decode 稳定约 5.1 token/s，Prefill 峰值约 172 token/s。

下一轮性能实验至少应把 `max_num_seqs` 提高到 4，再同时限制单请求最大输出、设置网关超时和取消传播。只增加 KV Cache 理论并发而不处理长请求，仍可能让短请求被排在长思考之后。

### 9.4 为什么 235B MoE 反而生成更快

两组碎片卡实测不能只按模型总参数比较：

| 模型 | 总参数与精度 | 每 Token 计算特征 | PP | 实测 Decode |
| --- | --- | --- | ---: | ---: |
| Qwen3-235B-A22B FP8 | 235B，总激活约 22B | MoE，每 Token 只激活部分 Expert；FP8 | 8 | 约 8.1 token/s |
| DeepSeek-R1-Distill-Llama-70B BF16 | 70B | Dense，每 Token 经过完整 70B；BF16 | 4 | 约 5.1 token/s |

Qwen3 虽然总权重更大、PP Stage 更多，但激活参数量更小且使用 FP8；DeepSeek Distill 70B 每个 Token 都要计算完整 Dense 70B，因此后者 Decode 更慢并不矛盾。这个比较仍受网络、Kernel、Prompt 和并发流量影响，只能作为本轮环境中的实测解释。

### 9.5 为什么慢，以及优化优先级

本轮拓扑优先解决“碎片卡能否组成一个大模型”，不是单请求性能最优解。DeepSeek 每生成一个 Token，都要顺序经过四个 PP Stage；四个 Stage 位于四台节点，使用 10Gb TCP，且实验显式设置 `NCCL_IB_DISABLE=1`，没有使用 RoCE/InfiniBand。Dense 70B 每个 Token 又会经过完整模型，约 5.1 token/s 是多项约束叠加后的结果。

优化必须区分两个目标：

| 目标 | 优先动作 | 预期影响 |
| --- | --- | --- |
| 降低并发 TTFT | `max_num_seqs` 从 1 调到 4，再逐步压测到 8 | 减少长思考请求造成的队头阻塞，不保证单请求 Decode 成倍提升 |
| 降低并发 TTFT | 网关限制最大输出、设置取消传播，并拆分长短请求队列 | 防止一个 3K Token 请求阻塞所有短请求 |
| 改善交互体验 | UI 流式展示 `<think>` / Reasoning | 用户能看到模型已经开始工作，但不改变算力速度 |
| 提高单请求 Decode | 去掉 `--enforce-eager`，A/B 测试 CUDA Graph | 减少 Kernel Launch 开销，收益必须实测 |
| 提高单请求 Decode | 把 4 卡压缩为两节点两卡或单节点四卡 | 减少跨节点 PP Hop，通常是最直接的拓扑优化 |
| 提高单请求 Decode | 使用 25/100Gb 网络、RoCE/IB 和 NCCL RDMA | 只能跨节点时降低激活传输延迟 |
| 提高单请求 Decode | 使用 FP8、INT8 或 INT4 的 70B 权重 | 降低显存与计算开销，并可能把 PP=4 缩到 PP=2 |
| 提高单请求 Decode | 升级 vLLM/CUDA Kernel，测试 Ray Compiled DAG 通信重叠 | 获取更新模型实现和通信优化，需回归稳定性 |
| 提高单请求 Decode | Speculative Decoding | 用 Draft Model 一次接受多个 Token，增加显存和系统复杂度 |

P/D 分离主要提升混合流量下的吞吐、资源隔离和 Goodput，不会自动让单请求 Decode 更快。若 Decode Group 仍是四节点 PP=4、10Gb TCP，它的单流生成速度仍受相同数据路径限制。

拓扑 A/B 完成后，最小风险的下一轮对照实验是保留性能最好的单节点四卡和 4K 上下文，只把 `max_num_seqs=4` 并去掉 `--enforce-eager`。先比较 Ready 时间、空载 TTFT、4 路并发 TTFT、Decode、GPU 利用率和取消行为，再决定是否引入量化、RDMA 或 P/D；不要同时改变所有变量。

### 9.6 三种四卡拓扑的 A/B 实测

常规服务池中没有一台空闲四卡节点，但找到了两台各已使用 6/8 卡、仍各有两卡可用的同型号 L20 节点。没有迁移或抢占既有业务，而是创建一套独立 RayClusterFleet，使用节点范围约束和 Pod Anti-Affinity，把一个双卡 Head 与一个双卡 Worker 固定分散到两台节点：

```text
节点 A：Rank 0 = PP 0 / TP 0，Rank 1 = PP 0 / TP 1
                         │
                         │  仅 PP 边界跨节点
                         ↓
节点 B：Rank 2 = PP 1 / TP 0，Rank 3 = PP 1 / TP 1
```

节点内两个 TP Rank 通过 GPU P2P/NCCL 协作，跨节点只保留一个 PP 边界。启动日志验证了四个 Rank 的 PP/TP 分组，Ray Placement Group 获得 4/4 GPU；80 层模型被切成两个 PP Stage，每个 Stage 再做两卡 TP。

随后先把四节点单卡和两节点双卡 Fleet 缩容到 0。在隔离池中找到一台 `Ready=True`、无资源压力、8 卡均未分配，但带有 `offline-node` NoSchedule/NoExecute 污点的 L20 节点。实验没有移除节点污点，只在新建的测试 Fleet 中显式增加 Toleration，并用 Hostname 把单个四卡 Head 限定到该节点。这样即使节点不适合运行模型，故障也只会留在测试实例内。

单节点启动日志确认四个 Rank 全部是 PP Rank 0，TP Rank 分别为 0–3：

```text
单节点：Rank 0 = PP 0 / TP 0
        Rank 1 = PP 0 / TP 1
        Rank 2 = PP 0 / TP 2
        Rank 3 = PP 0 / TP 3
```

为了让差异只来自拓扑，三组测试保持模型权重、L20 总卡数、vLLM 版本、BF16、4K 上下文、`max_num_seqs=1`、`--enforce-eager`、提示词和 64 Token 输出上限一致。实例空载后发请求，并逐条解析 SSE，以第一条非空 Token 而不是 HTTP 响应头计算 TTFT：

| 拓扑 | 热态空载 TTFT | 64 Token E2E | 稳态 Decode |
| --- | ---: | ---: | ---: |
| 四节点 × 单卡，TP=1、PP=4 | 约 0.250 秒 | 约 12.52 秒 | 约 5.13 token/s |
| 两节点 × 双卡，TP=2、PP=2 | 约 0.140 秒 | 约 6.49 秒 | 约 9.92 token/s |
| 单节点 × 四卡，TP=4、PP=1 | 约 0.124 秒 | 约 3.56 秒 | 约 18.33 token/s |

以四节点单卡为基线，两节点双卡的 Decode 提高约 93%；单节点四卡提高约 257%，也就是约 3.57 倍。单节点四卡与两节点双卡相比，TTFT 再降低约 11%，E2E 降低约 45%，Decode 提高约 85%。单节点的第一轮 TTFT 是 1.148 秒，后两轮稳定为 0.124 秒，因此第一轮被标记为首次请求 Warmup，不混入热态 TTFT。

两节点双卡每个 Rank 加载约 32.89 GiB 模型显存，可用 KV Cache 约 5.64 GiB，最小 Stage 的 KV 容量约 73K Token。权重加载约 44–49 秒，比此前四节点单卡的约 29 秒慢；这是共享文件系统读取、节点缓存和同时加载行为的差异，不能据此判断计算拓扑退化。

单节点四卡每个 Rank 加载约 32.89 GiB 模型显存，可用 KV Cache 约 5.67 GiB，KV 容量约 74.3K–75.3K Token；权重加载约 90 秒，Engine Profile、KV Cache 创建和 Warmup 约 7.2 秒。该节点首次拉取约 10.9 GB 运行镜像，镜像拉取不计入上述推理指标。

日志还出现一条重要警告：这台机器是四张 PCIe-only GPU，vLLM 不支持在超过两张此类 GPU 上使用 Custom AllReduce，因此自动回退到 NCCL AllReduce。即使存在这个回退，消除跨节点 PP 后的收益仍远大于本机四卡 AllReduce 成本；但如果节点具备 NVLink/NVSwitch，TP=4 还有进一步提升空间。

三轮单节点测试结束后，服务端指标恰好记录 3 个完成请求和 192 个生成 Token，`running=0`、`waiting=0`、`abort=0`，说明结果没有被外部流量污染。

测试中还捕获到一个外部长请求插入造成的样本：TTFT 上升到约 13.8 秒，但请求开始执行后的 Decode 仍约 9.92 token/s。该样本从空载 A/B 中剔除，却保留为生产证据：

- TTFT 必须同时关联 `num_requests_running`、`num_requests_waiting` 和队列时间；
- `curl time_starttransfer` 在 SSE 场景通常只量到响应头，不能当作首 Token；
- 固定输出长度下，Decode 应从第一条有效 Token 到结束计算；
- 拓扑改善了单流速度，但 `max_num_seqs=1` 的队头阻塞仍需单独治理。

这次 A/B 说明，碎片调度不应只问“能否凑够四张卡”。在没有高速 RDMA 的环境里，应优先选择单节点四卡；其次让 TP 留在节点内并把跨节点 PP Stage 数压到最低；若只能使用单卡碎片，则要接受 PP Hop 对 Decode 的明显影响。离线池节点可用于短期受控实验，但在重新进入生产服务池前，仍需由节点维护方确认离线原因、健康基线和回收策略。

## 10. 大模型的多节点 P/D 分离蓝图

P/D 分离不能把现有 PP Rank 一半标成 Prefill、另一半标成 Decode。Prefill 与 Decode 都必须是能独立运行完整模型的 Engine，只是分别优化 Prompt 计算和逐 Token 生成：

```text
                         ┌─ Prefill RayCluster
AIBrix Gateway / Router ─┤    PP Rank 0 ... PP Rank N-1
                         │          │
                         │          └── NIXL KV Transfer
                         │                         │
                         └─ Decode RayCluster      ↓
                              PP Rank 0 ... PP Rank N-1
                                      └── Streaming Response
```

最小 GPU 账单会直接翻倍：

| 模型 | 单个 Engine | 1 Prefill + 1 Decode | 1 Prefill + 2 Decode |
| --- | ---: | ---: | ---: |
| DeepSeek-R1-Distill-Llama-70B | 4×L20，PP=4 | 8×L20 | 12×L20 |
| Qwen3-235B-A22B FP8 | 8×L20，PP=8 | 16×L20 | 24×L20 |

落地时需要两套独立的 RayCluster 或 RayClusterFleet，并分别提供只选择 Head Pod 的 Service。两个 Engine 都启用 NIXL Connector；AIBrix P/D Router 先选择 Prefill Group，再把携带 KV Transfer 元数据的请求交给 Decode Group。

两个 Engine 的共同 vLLM 参数至少包括：

```bash
--tensor-parallel-size 1 \
--pipeline-parallel-size <4_OR_8> \
--distributed-executor-backend ray \
--kv-transfer-config '{"kv_connector":"NixlConnector","kv_role":"kv_both"}'
```

并为所有 Rank 统一配置 NIXL/UCX、可达的 Side Channel 地址和数据网卡。`kv_both` 表示 Engine 具备发送与接收能力，具体请求由 AIBrix 注入的 `kv_transfer_params` 决定 Producer/Consumer 角色；它不代表 Prefill、Decode 没有分工。

现有单 Pod `StormService` P/D 示例不能原样复制：它的每个 Role 本身只是一个 Pod，而这里每个 Role 都是一个多 Pod RayCluster。可行的工程路线是：

1. 分别创建 Prefill RayClusterFleet 与 Decode RayClusterFleet；
2. 给两个 Head Service 标记相同模型名和不同 P/D Role；
3. 为两个 vLLM Engine 配置 NIXL、UCX、Side Channel 和稳定的 Rank 拓扑；
4. 让 AIBrix P/D Router 发现两个 Group，并验证同一请求的 Producer/Consumer 参数；
5. 检查每个 PP Rank 的本地 Layer KV 是否被对应 Decode Rank 正确接收；
6. 再增加 Decode Group 数量并验证负载均衡、请求排空和故障恢复。

当前环境已经分别验证了“多节点 Ray PP”和“单 Pod StormService + NIXL P/D”，但**尚未验证二者组合后的多节点 P/D**。尤其不能只看到两套 RayCluster Ready 就声称成功；必须从 Prefill、Decode 两组日志中找到同一 Request ID、互补 KV Transfer 参数和最终响应证据。

P/D 的企业价值主要在高并发和 Prompt/Output 比例差异明显时体现。低 QPS 场景会因为双份权重、双倍冷启动和更多 GPU 常驻而更贵；对当前 `max_num_seqs=1` 的队头阻塞，先提高 Engine 并发、限制长输出和完善取消传播，可能比立即复制一整套 P/D 集群更划算。

## 11. 尚未执行的模型容量规划

| 候选 | 权重大小 | 碎片卡拓扑 | 当前判断 |
| --- | ---: | --- | --- |
| Qwen2.5-72B-Instruct BF16 | 约 135 GiB | 4 节点，每节点 1 张 L20，TP=1、PP=4 | 容量与已跑通的 70B 接近，**未部署** |
| Qwen2.5-72B-Instruct GPTQ Int8 | 约 72 GiB | 2–4 节点，每节点 1 张 L20 | 容量更宽松，适合做下一轮性能基线，**未部署** |
| Qwen3.5-397B-A17B GPTQ Int4 | 约 220 GiB | 8 节点，每节点 1 张 L20，优先 PP=8 | 容量可能成立，但当前 vLLM 0.10 未注册 Qwen3.5 MoE；需更新运行时并补齐 Ray，**未部署** |

如果 GPU 不足，应只缩容或删除本次实验创建的工作负载，先按精确资源名确认，再执行：

```bash
kubectl -n <EXPERIMENT_NAMESPACE> get rayclusterfleet,stormservice,roleset,pod
kubectl -n <EXPERIMENT_NAMESPACE> delete rayclusterfleet <EXPERIMENT_RAY_FLEET>
kubectl -n <EXPERIMENT_NAMESPACE> delete stormservice <EXPERIMENT_STORM_SERVICE>
```

不要用宽泛 Label 或整个 Namespace 删除生产中原有服务。

## 12. 本轮结论与边界

已经证明：

- AIBrix v0.7.0 可以管理真实 GPU RayClusterFleet 和 StormService；
- vLLM 可以在两台 L20 上以 PP=2 运行 32B BF16 模型；
- 八台各剩一张 L20 的节点可以通过 Ray Placement Group 和 PP=8 运行 Qwen3-235B FP8；
- Qwen3-235B FP8 每个 PP Rank 实际占用约 30.20 GiB 模型显存，并保留约 8.48 GiB KV Cache；
- 该碎片拓扑可以完成 OpenAI-Compatible API 生成，热请求样本约 4.9 秒 TTFT、8 token/s Decode；
- 四台各剩一张 L20 的节点可以通过 PP=4 运行 DeepSeek-R1-Distill-Llama-70B BF16；
- DeepSeek 70B 每个 PP Rank 使用约 33.864 GiB 模型显存，权重约 29 秒加载完成，生成约 5.1 token/s；
- 相同四张 L20 改为两节点双卡、TP=2/PP=2 后，空载 Decode 提高到约 9.92 token/s，证明减少跨节点 PP Hop 是当前网络条件下最有效的单流优化；
- 改为单节点四卡、TP=4/PP=1 后，热态 Decode 进一步提高到约 18.33 token/s，是四节点单卡的约 3.57 倍；
- 四张 PCIe-only L20 会让 vLLM Custom AllReduce 回退到 NCCL，但本轮消除跨节点 PP 的收益仍显著大于回退成本；
- `max_num_seqs=1` 遇到 R1 长思考请求会出现明显队头阻塞，排队请求 TTFT 可扩大到几十秒；
- AIBrix Gateway 可以发现并路由到多机 Ray Engine；
- StormService 可以把 Prefill、Decode 放到不同节点；
- AIBrix P/D Router 能为同一请求生成互补的 KV Transfer 参数；
- NIXL/UCX 已实际参与 KV Cache 交接；
- CephFS 模型目录可以保持双层只读，运行时缓存写入临时盘。

尚未证明：

- Qwen3-235B 的单次热请求样本可以代表正式并发容量或 Goodput；
- L20 上的默认 FP8/Fused-MoE Kernel 已达到最优性能；
- Qwen3.5-397B 已经在当前拓扑运行；
- 多节点 Ray PP 与 NIXL P/D 组合后的分布式 Prefill/Decode 数据路径可靠；
- P/D 比共置模式吞吐更高或成本更低；
- 当前 TCP/UCX 参数是最优网络配置；
- Role 级自动扩缩在真实模型冷启动和请求排空下安全；
- Ray 或 P/D 在节点故障、网络抖动、取消和超时场景下能无损恢复；
- 当前镜像组合适合长期生产运行；开发构建仍需锁定 digest 并完成安全扫描。

控制面安装、CPU mock、自动扩缩和 Higress 串联见：[在既有 Kubernetes 集群落地 AIBrix](aibrix-existing-cluster.md)。使用相同镜像、模型和 GPU 拓扑改由 RBG 编排后的实测，以及 RBG 与 RayClusterFleet/StormService 的逐项比较见：[RBG 多角色推理编排：从 CPU 控制面到生产 GPU 实测](rbg-existing-cluster.md#rbg-vs-aibrix-production)。多机模型并行与 P/D 的概念边界见：[分布式与 P/D 分离推理](../inference/distributed-serving.md)。GPU 页面、离线镜像和跨集群入口见：[在 Kubernetes 部署 ComfyUI](comfyui-minimax-h3-gpu.md)。
