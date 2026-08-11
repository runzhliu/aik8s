# DeepSeek V4 Flash：RBG + SGLang 双机 P/D 分离

这组清单用于在 Kubernetes 中准备一个最小的 SGLang Prefill/Decode 分离实例：一个 Prefill Pod、一个 Decode Pod，每个 Pod 使用单机 8 卡 TP=8，由 RBG 管理生命周期，由 AIBrix Gateway 完成 P/D 选路和请求编排。

当前目录是经过一次真实双机实验修正后的**脱敏模板**，不会直接命中任何真实镜像仓库或对象存储。镜像都使用 `example.invalid` 占位，Secret 也只有假值，因此误执行不会启动 16 卡服务。替换环境参数并通过预检后再部署；本次实验现象和性能数据记录在第 9 节。

## 1. 目标拓扑

```text
                         bootstrap_host/port/room
                    ┌──────────────────────────────┐
                    │                              ▼
Client ──> AIBrix Gateway ──> Prefill Pod      Decode Pod ──> Response
                              SGLang TP=8       SGLang TP=8
                              NIXL sender       NIXL receiver
                              8 × H20           8 × H20
                              Node A            Node B
```

AIBrix 为同一次请求选择 Prefill、Decode 实例，并为 SGLang 请求注入相同的 `bootstrap_host`、`bootstrap_port` 和 `bootstrap_room`。两个 Engine 使用 NIXL 传输 KV Cache。这里的 RBG 只负责两个角色的期望状态、Pod 模板和故障重建，不代替 AIBrix Gateway 做请求级 P/D 编排。

## 2. 文件说明

| 文件 | 用途 | 默认参与 `kustomize` |
| --- | --- | --- |
| `rbg.yaml` | 一个 RBG，包含 Prefill、Decode 两个 Role | 是 |
| `runtime-config.yaml` | 模型下载、运行时检查和两个 Engine 的启动脚本 | 是 |
| `services.yaml` | 两个角色的 HTTP/Bootstrap Service | 是 |
| `kustomization.yaml` | 公共 namespace、资源集合与标签 | 是 |
| `secret.example.yaml` | 模型源 Secret 的字段示例，只含假值 | 否 |
| `preflight-pod.yaml` | 不申请 GPU 的镜像能力预检 | 否 |

## 3. 初始资源预算

| 角色 | Pod 数 | GPU | TP | CPU request | Memory request | 本地临时盘 request |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Prefill | 1 | 8 × H20 96 GB | 8 | 80 cores | 700 GiB | 180 GiB |
| Decode | 1 | 8 × H20 96 GB | 8 | 80 cores | 700 GiB | 180 GiB |
| 合计 | 2 | 16 × H20 96 GB | — | 160 cores | 1400 GiB | 360 GiB |

两个角色通过 required Pod Anti-Affinity 强制落在不同节点。候选节点必须带有以下标签，并容忍 GPU 节点隔离 taint：

```yaml
nodeSelector:
  label-group: gpu-training-H20-96G
  feature.node.kubernetes.io/custom-rdma.available: "true"
tolerations:
  - key: quarantine-room
    value: gpu-training-H20-96G
```

RDMA 标签只代表节点经过集群侧标记，不等于数据路径已经可用。首轮清单把 `UCX_TLS` 固定为 `tcp,cuda_copy,cuda_ipc` 并关闭 NCCL IB，先建立可复现的 TCP 正确性基线；正确性稳定后再单独打开 RDMA 做 A/B。正式启用 RDMA 前仍需确认 Pod 内能看到正确的设备、网卡和 GID；不要虚构或请求集群中不存在的 RDMA extended resource。

## 4. 部署前需要替换的内容

### 4.1 镜像

SGLang 镜像必须同时满足：

- 能正确加载 DeepSeek V4 Flash 0731，并支持当前 H20/CUDA 构建；
- 包含 SGLang P/D 参数和 NIXL Python 包、动态库；
- 包含当前模型需要的 Marlin、DeepSeek V4 reasoning/tool parser；
- 两个角色使用完全相同的镜像 digest。

模型同步镜像需要包含 AWS CLI。可以直接替换 YAML 中的占位镜像，也可以在 `kustomization.yaml` 中加入：

```yaml
images:
  - name: example.invalid/ai/sglang
    newName: REGISTRY/PROJECT/sglang
    newTag: PINNED_TAG
  - name: example.invalid/ai/model-sync
    newName: REGISTRY/PROJECT/model-sync
    newTag: PINNED_TAG
```

生产材料应锁定 tag 和 digest，并先完成镜像同步。不要依赖 Pod 启动时从公网拉取或通过 PyPI 临时安装 NIXL。

### 4.2 模型源 Secret

`secret.example.yaml` 不属于 Kustomize 资源，避免把真实凭据提交到仓库。未来执行时，将它复制到仓库外的临时文件，替换下面五个字段后单独创建 Secret：

```text
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
AWS_DEFAULT_REGION
S3_ENDPOINT_URL
MODEL_SOURCE_URI
```

下载脚本已固定使用 S3 virtual-hosted addressing，以兼容拒绝 path-style 请求的 S3 兼容对象存储。下载完成后会检查 `config.json`、权重索引以及 48 个 safetensors 分片，缺少任一项都会让 Init Container 失败，而不会启动不完整模型。

如果实际 namespace 不是 `deepseek-serving`，需要同时修改：

- `kustomization.yaml` 的 `namespace`；
- 仓库外 Secret 文件的 `metadata.namespace`；
- `preflight-pod.yaml` 的 `metadata.namespace`。

## 5. 未来执行时的预检顺序

以下命令是执行手册，当前准备阶段不要运行 `apply`。

### 5.1 资源预检

至少确认两台可调度节点各自空闲 8 张 GPU，并检查 CPU、内存、本地临时盘和 RDMA 标签：

```bash
gmanctl get nodes -l label-group=gpu-training-H20-96G
gmanctl describe node NODE_NAME
gmanctl get pods -A -o wide
```

不要只统计集群 GPU 总数。这里有 required Pod Anti-Affinity，必须存在两台分别能容纳完整 TP=8 Pod 的节点。

### 5.2 不占 GPU 的镜像预检

先把 `preflight-pod.yaml` 中的 SGLang 镜像替换为目标 digest，再执行：

```bash
gmanctl apply -f preflight-pod.yaml
gmanctl logs -f pod/deepseek-v4-flash-sglang-pd-preflight
gmanctl delete pod deepseek-v4-flash-sglang-pd-preflight
```

只有日志出现 `SGLang/NIXL image preflight: PASS` 才继续。这个检查不加载模型，也不申请 GPU；它用于提前发现“镜像能跑普通 SGLang，但不包含 NIXL”的问题。

### 5.3 本地渲染和服务端 Dry Run

```bash
kubectl kustomize . > /tmp/deepseek-v4-flash-sglang-pd.rendered.yaml
gmanctl apply --dry-run=server -f /tmp/deepseek-v4-flash-sglang-pd.rendered.yaml
```

Dry Run 重点检查 RBG CRD 版本、Role 模板字段、配额、准入策略和 Service。它不会验证镜像中的 kernel、NIXL/RDMA 数据路径或模型正确性。

## 6. 未来部署与观察

Secret、镜像和 namespace 都准备好后，再执行：

```bash
gmanctl apply -f /path/outside/repository/model-source-secret.yaml
gmanctl apply -k .
gmanctl get rbg,roleinstance,pod,svc -l app.kubernetes.io/name=deepseek-v4-flash-sglang-pd -o wide
```

确认两个 Pod 位于不同节点：

```bash
gmanctl get pods \
  -l app.kubernetes.io/name=deepseek-v4-flash-sglang-pd \
  -o custom-columns=NAME:.metadata.name,ROLE:.metadata.labels.role-name,NODE:.spec.nodeName,READY:.status.containerStatuses[*].ready
```

启动过程分为三段：模型同步、SGLang 权重与 kernel 初始化、Engine Ready。首次启动应重点查看：

```bash
gmanctl logs ROLE_POD -c verify-runtime
gmanctl logs -f ROLE_POD -c download-model
gmanctl logs -f ROLE_POD -c prefill
gmanctl logs -f ROLE_POD -c decode
```

预期日志应分别出现 Prefill/Decode disaggregation mode 和 NIXL 初始化信息，并且不应出现 NCCL、RDMA、KV transfer、CUDA Graph 或非法 token 错误。

## 7. AIBrix 接入与正确性验收

两个 Pod 必须保留下列标签：

```text
model.aibrix.ai/name=deepseek-v4-flash-sglang-pd
model.aibrix.ai/engine=sglang
role-name=prefill|decode
roleset-name=deepseek-v4-flash-sglang-pd-0
```

同时保留 `model.aibrix.ai/sglang-bootstrap-port: "8998"`。AIBrix SGLang handler 会据此把选中的 Prefill Pod IP 和 bootstrap port 注入请求，并让 Prefill、Decode 两次子请求共享同一个 room。

TCP probe 只证明进程端口可连接，不能证明模型输出正确。先通过 AIBrix Gateway 发确定性请求：

```bash
curl -sS http://AIBRIX_GATEWAY/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -H 'routing-strategy: pd' \
  -d '{
    "model": "deepseek-v4-flash-sglang-pd",
    "messages": [{"role": "user", "content": "只回答：PD_OK"}],
    "temperature": 0,
    "max_tokens": 16,
    "chat_template_kwargs": {"thinking": false}
  }'
```

验收时同时观察 Gateway、Prefill 和 Decode 日志，确认一次客户端请求确实命中一对角色。再进行以下正确性测试：

1. 中文、英文和代码各至少 20 次确定性请求，检查乱码、随机符号和异常 token；
2. 128、1024、4096 token 三档输入，验证短长 Prompt；
3. streaming 与 non-streaming 对比；
4. 直连 Prefill、直连 Decode 和 AIBrix P/D 路径对比，以便定位是模型运行时还是路由/传输问题；
5. 重启一个角色，确认恢复期间的错误形态和 RBG 重建行为。

初次打通不启用 DSpark。P/D、NIXL 和输出正确性稳定后，再单独增加 speculative decoding 做 A/B，避免一次引入多项变量。

## 8. 压测计划

正确性通过后，使用相同输入集、输出长度、并发度和采样参数，对 Combined TP=8 与 P/D 2×TP=8 做对比。至少记录：

- 请求成功率和错误类型；
- req/s、输入/输出 tok/s；
- p50/p95/p99 TTFT；
- p50/p95/p99 TPOT 和 ITL；
- Prefill、Decode 各自 GPU 利用率、显存、KV Cache、队列长度；
- NIXL 传输时延与网卡/RDMA 吞吐；
- 每种方案占用的 GPU 数。

建议覆盖短请求 `128 in / 64 out` 与长请求 `4096 in / 128 out`，并发至少包含 C=1、4、8。由于 P/D 使用 16 张 GPU，而 Combined TP=8 只使用 8 张，结论必须同时比较绝对吞吐和每 GPU 吞吐，不能只看总 tok/s。

## 9. 双机实测与下一轮 A/B

一次 2×TP=8 实验把 Prefill 和 Decode 分别调度到两台 8×H20 96 GB 节点。两个 Engine 都完成 DeepSeek V4 Flash 权重加载、Marlin 权重准备、NIXL 1.3.2 与 UCX 初始化，RBG 最终为 Ready。首次冷启动中，较慢节点拉取两个大镜像约 2 分钟，约 157 GiB 模型同步和 Marlin/JIT 又占用了主要等待时间；单侧 Marlin 权重准备约 295 秒。大型模型的发布超时不能只覆盖容器启动。

服务刚进入 Ready 后立即发出的第一条 P/D 请求遇到 Gateway upstream timeout；等待 SGLang 的 disaggregation warm-up 明确完成后重试，确定性请求在 0.25 秒内返回 `PD_OK`。因此 TCP Probe、HTTP Ready 和“P/D 可接流量”仍是三个不同阶段，正式发布应增加低频 synthetic request 或延长接流量门槛。

稳态短测通过同一个 AIBrix Gateway、OpenAI Chat API 和 `routing-strategy=pd` 执行，固定 `temperature=0`、`ignore_eos=true`。输入 Token 比目标多出 Chat Template 固定开销；所有输出均达到指定长度：

| 场景 | 成功 | req/s | 输出 tok/s | p95 TTFT | p95 TPOT | p95 ITL | p95 E2E |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 128 in / 64 out，C=1 | 16/16 | 1.46 | 93.32 | 231.42 ms | 7.24 ms | 7.46 ms | 686.99 ms |
| 128 in / 64 out，C=8 | 64/64 | 6.85 | 438.42 | 874.42 ms | 8.26 ms | 8.59 ms | 1400.97 ms |
| 4096 in / 128 out，C=4 | 16/16 | 1.69 | 216.50 | 1431.91 ms | 7.94 ms | 8.44 ms | 2437.57 ms |

这组数据说明 Decode 的单 Token 间隔稳定，但当前 Prefill、KV 传输和请求协调成本仍然偏高。与此前不同 Runtime 的 TP=8 数据相比，4K 场景 p95 TTFT 约为 1.43 秒，接近 1.39 秒的 vLLM Combined 基线，输出吞吐则低约 21.8%；P/D 还使用了两倍 GPU，不能据此替代现网。该比较用于确定优化方向，不是严格的框架排名。

当前资源上限是两台节点，不能让 P/D 和第三套 Combined 同时常驻。严格 A/B 应串行执行：

1. 保存当前 P/D 的结果、日志、镜像 digest 和 Runtime 参数；
2. 停止两角色 RBG，用其中一台启动同镜像、同模型、同 TP=8 和同 kernel 参数的 Combined Engine，另一台释放；
3. 继续经过同一个 AIBrix Gateway，复用相同客户端、随机种子、请求集、并发和 warm-up；
4. 同时比较绝对吞吐、p95/p99 延迟和 tokens/s/GPU，不能把 16 卡 P/D 与 8 卡 Combined 只按总 tok/s 排名；
5. 如需继续验证 P/D，再恢复双机，并把 RDMA 作为唯一变量复跑。

本次节点带有 `custom-rdma.available=true` 标签，宿主机也能看到多个 `uverbs` 设备，但当前普通 Pod 内没有 `/dev/infiniband`，Node Capacity 中也没有可申请的 RDMA extended resource。因此本轮 NIXL 明确使用 UCX TCP。启用 RDMA 前应先用不申请 GPU 的 Preflight Pod 验证设备注入、RDMA CM、GID、RoCE 网卡 IP 和 `ucx_info -d`；随后再设置真实的 `UCX_NET_DEVICES`/Transport，并用 NIXL 日志、RDMA 端口计数器和 TCP/RDMA 同负载 A/B 证明数据路径。只删除 `NCCL_IB_DISABLE=1` 或把 `UCX_TLS` 改成 `rc` 不构成验收。

## 10. 停服与回滚

RBG 是父控制器。**不要只删除 RoleInstance 或 Pod 来释放 GPU**：只删子资源会被 RBG 很快重建。

暂停整个服务应删除或缩容父 RBG；当前 CRD 清单采用固定副本数，最直接的回滚是：

```bash
gmanctl delete rbg deepseek-v4-flash-sglang-pd
```

确认两个角色都已退出、GPU 已释放：

```bash
gmanctl get roleinstance,pod -l app.kubernetes.io/name=deepseek-v4-flash-sglang-pd
gmanctl describe node NODE_A
gmanctl describe node NODE_B
```

Service 和 ConfigMap 不占 GPU，可以保留用于排障；完整清理时再执行：

```bash
gmanctl delete -k .
gmanctl delete secret deepseek-v4-flash-model-source
```

## 10. 已知边界

- 当前模型卷使用 `emptyDir`，两个 Pod 各下载一份约 156 GiB 的权重；Pod 重建会重新下载。稳定后应接入只读模型缓存或持久卷。
- JIT cache 当前也位于模型 `emptyDir`，不能跨 Pod 生命周期复用。
- 一个 Prefill + 一个 Decode 没有角色级冗余，只适合首轮正确性和性能验证。
- 节点有 RDMA 标签不代表 NIXL 一定走 RDMA；需要用运行日志、设备信息和网络指标确认，不能仅凭 Ready 状态下结论。
- AIBrix P/D 请求必须经过 Gateway，并携带 `routing-strategy: pd`；直接访问单个 Service 不会由 AIBrix 完成两阶段编排。
- 公共仓库只保留脱敏模板。真实 registry、对象存储 endpoint、bucket、namespace、节点 IP、Secret 值和 Gateway 地址都应留在环境私有 overlay 或密钥系统中。
