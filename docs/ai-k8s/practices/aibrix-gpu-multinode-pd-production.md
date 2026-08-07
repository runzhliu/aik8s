---
title: AIBrix 真实 GPU 实测：Ray 多机推理与 NIXL P/D 分离
description: 在生产 Kubernetes 集群使用 NVIDIA L20、AIBrix v0.7.0、RayClusterFleet、StormService 和 vLLM 验证多机模型并行、P/D 路由及 NIXL KV Cache 传输
status: lab
last_reviewed: 2026-08-08
---

# AIBrix 真实 GPU 实测：Ray 多机推理与 NIXL P/D 分离

前一轮实验使用 CPU mock 验证了 AIBrix v0.7.0 的控制面、模型发现、路由、StormService 和自动扩缩容。本轮继续在一套生产 Kubernetes 集群中使用真实 NVIDIA L20 和本地模型权重，回答两个更关键的问题：

1. `RayClusterFleet` 能否让一个 vLLM Engine 跨两台机器共同执行同一个模型；
2. `StormService` 能否让 Prefill、Decode 分别运行在不同 GPU 节点，并通过 NIXL 交接 KV Cache。

最终结果：两机两卡的 Qwen2.5-32B BF16 Ray Pipeline Parallel 推理成功；两机两卡的 Qwen2.5-Coder-32B GPTQ Int4 P/D 服务也成功完成 AIBrix Gateway → Prefill → NIXL KV Transfer → Decode → 响应的完整链路。

本次只完成**功能、拓扑和数据路径验证**，没有形成吞吐、TTFT、TPOT 或 Goodput 性能结论。生产选型仍需使用真实流量分布进行基准测试。

!!! warning "公开文档已经脱敏"
    本文不会记录公司内部集群名、节点地址、Ceph monitor、模型卷真实路径、Registry、Ingress 域名、Pod IP 或 Secret。所有环境相关值统一写成 `<...>` 占位符，不能直接复制后执行。

## 1. 测试环境与版本

| 项目 | 实测值 |
| --- | --- |
| AIBrix | v0.7.0 |
| GPU | NVIDIA L20，单卡约 46 GiB 显存 |
| Ray 多机镜像 | vLLM 0.8.3 开发构建，Ray 2.43.0 |
| P/D 镜像 | vLLM 0.10.1 开发构建，Ray 2.48.0 |
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

## 8. 下一档模型：四卡 72B

模型目录还包含更大 Qwen 权重。仅按权重大小和 L20 显存估算：

| 候选 | 权重大小 | 建议拓扑 | 判断 |
| --- | ---: | --- | --- |
| Qwen2.5-72B-Instruct BF16 | 约 135 GiB | 两节点，每节点 2 卡，TP=2、PP=2 | 能尝试，但每卡权重约 34 GiB，KV 和运行时余量偏紧 |
| Qwen2.5-72B-Instruct GPTQ Int8 | 约 72 GiB | 两节点，每节点 2 卡，TP=2、PP=2 | 推荐作为四卡第一轮，容量更稳 |
| Qwen3-235B-A22B FP8 | 约 220 GiB | 至少 8 张 L20 | 四卡总显存不足，不应强行部署 |
| Qwen3-235B-A22B BF16 | 约 438 GiB | 需要更多 GPU | 不适合作为下一步冒烟测试 |

下一轮建议先运行 72B Int8 四卡，验证：

1. 每个节点能否连续分配 2 张 GPU；
2. Ray Placement Group 是否形成预期的 TP/PP Rank 分布；
3. 跨节点 TP Collective 的网络性能和错误率；
4. 4K、8K、16K 上下文下的显存余量；
5. 冷启动时间、单请求 TTFT/TPOT 和并发 Goodput；
6. Worker 或节点重启后的恢复语义。

如果 GPU 不足，应只缩容或删除本次实验创建的工作负载，先按精确资源名确认，再执行：

```bash
kubectl -n <EXPERIMENT_NAMESPACE> get rayclusterfleet,stormservice,roleset,pod
kubectl -n <EXPERIMENT_NAMESPACE> delete rayclusterfleet <EXPERIMENT_RAY_FLEET>
kubectl -n <EXPERIMENT_NAMESPACE> delete stormservice <EXPERIMENT_STORM_SERVICE>
```

不要用宽泛 Label 或整个 Namespace 删除生产中原有服务。

## 9. 本轮结论与边界

已经证明：

- AIBrix v0.7.0 可以管理真实 GPU RayClusterFleet 和 StormService；
- vLLM 可以在两台 L20 上以 PP=2 运行 32B BF16 模型；
- AIBrix Gateway 可以发现并路由到多机 Ray Engine；
- StormService 可以把 Prefill、Decode 放到不同节点；
- AIBrix P/D Router 能为同一请求生成互补的 KV Transfer 参数；
- NIXL/UCX 已实际参与 KV Cache 交接；
- CephFS 模型目录可以保持双层只读，运行时缓存写入临时盘。

尚未证明：

- P/D 比共置模式吞吐更高或成本更低；
- 当前 TCP/UCX 参数是最优网络配置；
- Role 级自动扩缩在真实模型冷启动和请求排空下安全；
- Ray 或 P/D 在节点故障、网络抖动、取消和超时场景下能无损恢复；
- 当前镜像组合适合长期生产运行；开发构建仍需锁定 digest 并完成安全扫描。

控制面安装、CPU mock、自动扩缩和 Higress 串联见：[在既有 Kubernetes 集群落地 AIBrix](aibrix-existing-cluster.md)。多机模型并行与 P/D 的概念边界见：[分布式与 P/D 分离推理](../inference/distributed-serving.md)。
