---
title: AIBrix 真实 GPU 实测：从两机推理到八节点碎片 GPU
description: 在生产 Kubernetes 集群使用 NVIDIA L20、AIBrix v0.7.0、RayClusterFleet、StormService 和 vLLM，验证两机模型并行、NIXL P/D 分离及八节点 Qwen3-235B FP8 推理
status: lab
last_reviewed: 2026-08-08
---

# AIBrix 真实 GPU 实测：从两机推理到八节点碎片 GPU

前一轮实验使用 CPU mock 验证了 AIBrix v0.7.0 的控制面、模型发现、路由、StormService 和自动扩缩容。本轮继续在一套生产 Kubernetes 集群中使用真实 NVIDIA L20 和本地模型权重，回答三个更关键的问题：

1. `RayClusterFleet` 能否让一个 vLLM Engine 跨两台机器共同执行同一个模型；
2. `StormService` 能否让 Prefill、Decode 分别运行在不同 GPU 节点，并通过 NIXL 交接 KV Cache；
3. 当每台节点都只剩一张空闲 GPU 时，能否把八张碎片 L20 组成一个 235B MoE 推理实例。

最终结果：两机两卡的 Qwen2.5-32B BF16 Ray Pipeline Parallel 推理成功；两机两卡的 Qwen2.5-Coder-32B GPTQ Int4 P/D 服务成功完成 AIBrix Gateway → Prefill → NIXL KV Transfer → Decode → 响应的完整链路；Qwen3-235B-A22B FP8 也成功运行在八台节点、每台一张 L20 的碎片拓扑上，并通过 OpenAI-Compatible API 完成真实生成。

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

## 9. 尚未执行的模型容量规划

以下只完成模型配置、权重大小和运行时能力检查，没有创建工作负载：

| 候选 | 权重大小 | 碎片卡拓扑 | 当前判断 |
| --- | ---: | --- | --- |
| DeepSeek-R1-Distill-Llama-70B BF16 | 约 131 GiB | 4 节点，每节点 1 张 L20，TP=1、PP=4 | 标准 Llama 架构，vLLM 0.10 可支持；每卡约 33 GiB 静态权重，具备尝试条件，**未部署** |
| Qwen2.5-72B-Instruct BF16 | 约 135 GiB | 4 节点，每节点 1 张 L20，TP=1、PP=4 | 容量与 70B 接近，**未部署** |
| Qwen2.5-72B-Instruct GPTQ Int8 | 约 72 GiB | 2–4 节点，每节点 1 张 L20 | 容量更宽松，适合做下一轮性能基线，**未部署** |
| Qwen3.5-397B-A17B GPTQ Int4 | 约 220 GiB | 8 节点，每节点 1 张 L20，优先 PP=8 | 容量可能成立，但当前 vLLM 0.10 未注册 Qwen3.5 MoE；需更新运行时并补齐 Ray，**未部署** |

DeepSeek 70B 若继续验证，应沿用本章的 RayClusterFleet，只把 Worker 数改为 3、PP 改为 4、模型路径和服务名改成对应值。不要把“容量估算可行”写成“已经跑通”，验收仍需覆盖权重加载、API 请求、每卡显存、TTFT/TPOT 和节点故障。

如果 GPU 不足，应只缩容或删除本次实验创建的工作负载，先按精确资源名确认，再执行：

```bash
kubectl -n <EXPERIMENT_NAMESPACE> get rayclusterfleet,stormservice,roleset,pod
kubectl -n <EXPERIMENT_NAMESPACE> delete rayclusterfleet <EXPERIMENT_RAY_FLEET>
kubectl -n <EXPERIMENT_NAMESPACE> delete stormservice <EXPERIMENT_STORM_SERVICE>
```

不要用宽泛 Label 或整个 Namespace 删除生产中原有服务。

## 10. 本轮结论与边界

已经证明：

- AIBrix v0.7.0 可以管理真实 GPU RayClusterFleet 和 StormService；
- vLLM 可以在两台 L20 上以 PP=2 运行 32B BF16 模型；
- 八台各剩一张 L20 的节点可以通过 Ray Placement Group 和 PP=8 运行 Qwen3-235B FP8；
- Qwen3-235B FP8 每个 PP Rank 实际占用约 30.20 GiB 模型显存，并保留约 8.48 GiB KV Cache；
- 该碎片拓扑可以完成 OpenAI-Compatible API 生成，热请求样本约 4.9 秒 TTFT、8 token/s Decode；
- AIBrix Gateway 可以发现并路由到多机 Ray Engine；
- StormService 可以把 Prefill、Decode 放到不同节点；
- AIBrix P/D Router 能为同一请求生成互补的 KV Transfer 参数；
- NIXL/UCX 已实际参与 KV Cache 交接；
- CephFS 模型目录可以保持双层只读，运行时缓存写入临时盘。

尚未证明：

- Qwen3-235B 的单次热请求样本可以代表正式并发容量或 Goodput；
- L20 上的默认 FP8/Fused-MoE Kernel 已达到最优性能；
- DeepSeek-R1-Distill-Llama-70B、Qwen3.5-397B 已经在当前拓扑运行；
- P/D 比共置模式吞吐更高或成本更低；
- 当前 TCP/UCX 参数是最优网络配置；
- Role 级自动扩缩在真实模型冷启动和请求排空下安全；
- Ray 或 P/D 在节点故障、网络抖动、取消和超时场景下能无损恢复；
- 当前镜像组合适合长期生产运行；开发构建仍需锁定 digest 并完成安全扫描。

控制面安装、CPU mock、自动扩缩和 Higress 串联见：[在既有 Kubernetes 集群落地 AIBrix](aibrix-existing-cluster.md)。使用相同镜像、模型和 GPU 拓扑改由 RBG 编排后的实测，以及 RBG 与 RayClusterFleet/StormService 的逐项比较见：[RBG 多角色推理编排：从 CPU 控制面到生产 GPU 实测](rbg-existing-cluster.md#rbg-vs-aibrix-production)。多机模型并行与 P/D 的概念边界见：[分布式与 P/D 分离推理](../inference/distributed-serving.md)。
