# DeepSeek V4 Flash：vLLM + LMCache MP 单节点 A/B 材料

这组清单用于回答一个收敛的问题：在单节点 `8 × H20 96 GB`、DeepSeek-V4-Flash-0731、vLLM TP=8 的条件下，`LMCacheMPConnector + Host DRAM` 能否在 GPU Prefix Cache 被挤出后正确恢复 DeepSeek V4 的 Hybrid KV，并改善重复长前缀的 TTFT。

它不是跨节点中央 KV Cache 的完整部署，也不用于第一轮 P/D 实验。vLLM 官方 DeepSeek V4 Recipe 已把 LMCache 列为 KV Offload 选项，但当前生成方案把 `LMCacheMPConnector` 定位为**单节点、伴随式 MP Server**；跨节点共享和 P/D 应在这个基础正确性通过后分别验证。

所有公开清单使用占位镜像、通用 HostPath 和通用节点标签，不包含任何真实仓库、节点、模型源、地址或凭据。

## 1. 实验拓扑

Baseline 和 LMCache 两种模式串行使用同一份 Deployment，因此最多占用一台 8 卡节点：

```text
A0 Baseline
Client → vLLM TP=8 → GPU Prefix Cache

A1 LMCache MP
Client → vLLM TP=8 → GPU Prefix Cache
                         ↕ CUDA IPC / LMCache MP Connector
                    LMCache Server → Host DRAM L1
```

两种模式保持不变的变量：

- DeepSeek-V4-Flash-0731 模型目录与 Digest；
- vLLM/LMCache 派生镜像 Digest；
- TP=8、`distributed-executor-backend=mp`；
- `block-size=256`、Hybrid KV Manager、Prefix Caching；
- 最大上下文、Batch、并发、GPU Memory Utilization；
- Eager/CUDA Graph 状态、请求 Trace 和到达顺序。

唯一差异是是否启动 LMCache MP Server 并给 vLLM 增加 `LMCacheMPConnector`。

## 2. 文件说明

| 文件 | 用途 |
| --- | --- |
| `Dockerfile` | 仅供不含 LMCache 的已验证 vLLM 镜像构建回退派生镜像 |
| `base/` | 两种模式共同的 Deployment、Service 和启动脚本 |
| `overlays/baseline/` | `ENABLE_LMCACHE=false` 的 A0 基线 |
| `overlays/lmcache/` | `ENABLE_LMCACHE=true` 的 A1 实验组 |
| `preflight-pod.yaml` | 不申请 GPU，检查 vLLM、LMCache、MP Connector 和 CLI |
| `benchmark-prefix-reuse.py` | 冷请求、GPU 热命中、缓存压力、淘汰后重放四阶段测试 |

## 3. 版本与镜像

DeepSeek-V4-Flash-0731 的官方 Recipe 要求 vLLM 至少为 0.25.0。当前材料默认：

```text
vLLM base: vllm/vllm-openai:v0.26.0-cu129
LMCache:   0.5.2（该 vLLM 镜像已经内置）
```

优先直接同步并使用这一组已经配套的镜像，不需要再安装 LMCache。部署前通过 `preflight-pod.yaml` 核对实际版本、MP Connector 和 Server CLI。

只有已经通过 DeepSeek V4 正确性验证的其他 vLLM 镜像不包含 LMCache 时，才使用回退 Dockerfile 构建派生镜像：

```bash
docker build \
  --build-arg BASE_IMAGE=REGISTRY/PROJECT/VLLM@sha256:PINNED \
  --build-arg LMCACHE_VERSION=0.5.2 \
  -t REGISTRY/PROJECT/vllm-dsv4-lmcache:0.5.2 \
  -f Dockerfile .
```

不要在 Pod 启动时临时 `pip install`。LMCache MP 接口仍在演进，vLLM、LMCache、Python、Torch 与 CUDA 必须作为一个组合锁定并记录镜像 Digest。也不要在已内置 LMCache 的镜像上强制覆盖版本；这会改变官方已经配套的依赖组合。

## 4. 部署前替换项

先替换三个通用占位值：

1. `example.invalid/ai/vllm-lmcache:replace-me`：已同步且通过 Preflight 的组合镜像 Digest；
2. `/var/lib/aik8s/models/DeepSeek-V4-Flash-0731`：节点上已经准备好的模型目录；
3. `/var/lib/aik8s/cache/deepseek-v4-flash-vllm-lmcache`：编译缓存目录。

如果节点标签、Taint 或 Namespace 不同，再修改 Base 和 Preflight。模型建议提前放入 HostPath/NVMe；本实验不把模型下载纳入变量，也不在 Init Container 重复回源。

Host DRAM 初始设置为 128 GiB、初次只分配 8 GiB。LMCache 官方 Recipe 建议 L1 上限不超过可专用 Host DRAM 的约 75%，并保留：

```text
Kubernetes Memory Limit
> vLLM CPU 峰值 + LMCache L1 上限 + Page Cache + 安全余量
```

`--max-gpu-workers=1` 用于减少高压异步加载中的并发 GPU Transfer 冲突；不要在第一轮为了追求带宽直接调大。

## 5. 无 GPU 预检

先替换 `preflight-pod.yaml` 中的镜像，然后执行：

```bash
gmanctl apply -f preflight-pod.yaml
gmanctl logs -f pod/deepseek-v4-flash-vllm-lmcache-preflight
gmanctl delete pod deepseek-v4-flash-vllm-lmcache-preflight
```

预期最后出现：

```text
DeepSeek V4 / LMCache image preflight: PASS
```

还应记录实际的 vLLM、LMCache、Torch、CUDA 和 Driver 版本。Preflight 通过只表示组件存在，不证明 V4 Hybrid KV 能正确 Offload。

## 6. 渲染和串行部署

先检查两个 Overlay：

```bash
kubectl kustomize overlays/baseline >/tmp/dsv4-lmcache-baseline.yaml
kubectl kustomize overlays/lmcache >/tmp/dsv4-lmcache-enabled.yaml
gmanctl apply --dry-run=server -f /tmp/dsv4-lmcache-baseline.yaml
gmanctl apply --dry-run=server -f /tmp/dsv4-lmcache-enabled.yaml
```

运行 A0：

```bash
gmanctl apply -k overlays/baseline
gmanctl rollout status deployment/deepseek-v4-flash-vllm-lmcache-ab --timeout=30m
```

A0 完成后直接切换 A1。Deployment 使用 `Recreate`，不会同时运行两个 8-GPU Pod：

```bash
gmanctl apply -k overlays/lmcache
gmanctl rollout status deployment/deepseek-v4-flash-vllm-lmcache-ab --timeout=30m
```

切换前后都要保存 Pod UID、节点、镜像 ID、启动参数和编译缓存状态。如果严格比较冷启动时间，应为两轮使用独立但等价的编译缓存目录；如果只比较稳态 Prefix 复用，可以共享已经预热的编译缓存。

## 7. 正确性门槛

第一轮必须保持以下设置：

- 不启用 DSpark/MTP；
- 不启用 P/D；
- 不增加 Filesystem、Redis、S3 或跨节点 Backend；
- 保留 `--no-disable-hybrid-kv-cache-manager`；
- 使用 `block-size=256`；
- 先沿用已经验证的 `KV_CACHE_DTYPE=fp8`。

DeepSeek V4 同时包含 C4/C128 压缩层、SWA/残余状态和 Indexer 相关状态。以下检查全部通过后才能进入性能测试：

1. `/v1/models` 返回正确模型；
2. 中文、英文、代码各 20 次确定性生成没有乱码或错误 Token；
3. 4K、32K、128K 三档 Prompt 输出正确；
4. 第一次请求和重复 Prefix 请求的结果一致；
5. 发生 GPU Cache 淘汰后，LMCache Load 仍返回正确结果；
6. LMCache Server 被终止时，请求明确失败或回退重算，不能使用不完整 KV；
7. vLLM、LMCache 与 Pod RSS 在持续请求中没有单调增长。

社区已出现 DeepSeek V4 Hybrid KV 在高并发 Offload 中 Worker 崩溃、Prefix 命中异常以及 DSpark Draft KV 外部命中为零的报告。因此 Smoke Test 不能替代至少 30～60 分钟的并发 Soak Test。

`fp8_ds_mla` 可能更符合部分 DeepSeek Hybrid KV Offload 路径的布局假设，但不能在 A/B 中顺手切换。应把它作为 A1 通过后的独立 A2 变量：先确认当前 vLLM 构建支持该 dtype，再比较正确性、容量、命中和并发稳定性。

## 8. 怎样证明命中的是 LMCache

立即重复同一个 Prompt，通常只会命中 GPU Prefix Cache。正确顺序是：

```text
目标 Prefix 冷请求
→ 立即重放，证明 GPU Prefix Cache 生效
→ 输入大量互不相同的长 Prefix，制造 GPU Cache 压力
→ 确认目标 Block 已从 GPU 层淘汰
→ 再重放目标 Prefix
→ 观察 LMCache 外部命中和 TTFT
```

从 Pod 内执行脚本：

```bash
python3 benchmark-prefix-reuse.py \
  --endpoint http://deepseek-v4-flash-vllm-lmcache-ab:8000 \
  --model deepseek-v4-flash-lmcache-ab \
  --prefix-chars 64000 \
  --eviction-prompts 128 \
  --eviction-concurrency 4
```

默认压力集只是起点。必须根据 `/metrics` 暴露的 GPU KV 容量和使用率调整，直到确认目标 Prefix 已经离开 GPU 层；否则 `target_after_pressure` 仍可能只是 GPU 命中。

同时保存指标：

```bash
curl -sS http://deepseek-v4-flash-vllm-lmcache-ab:8000/metrics \
  | grep -E 'prefix_cache|external.*cache|kv_offload|lmcache|gpu_cache'
```

不同版本的指标名会变化，实际执行前先保存完整 `/metrics`。有效证据至少包括：External Query/Hit 或 LMCache Load 计数增长、Load Bytes/Time 增长、GPU Cache 压力或淘汰发生，以及重放请求的确定性结果正确。

## 9. A/B 指标和判定

| 指标 | A0 Baseline | A1 LMCache | 判定用途 |
| --- | ---: | ---: | --- |
| 冷请求 TTFT | 记录 | 记录 | Connector 的 Miss 额外成本 |
| GPU 热命中 TTFT | 记录 | 记录 | 不应明显退化 |
| 淘汰后重放 TTFT | 重新 Prefill | LMCache Load | 核心收益 |
| External Hit Tokens | 0 | 应增长 | 证明不是 GPU 命中 |
| Host DRAM | 基线 | L1 实际使用 | 容量成本 |
| CPU、PCIe、H2D | 基线 | 记录 | 数据搬运成本 |
| p95 TPOT/吞吐 | 记录 | 记录 | Offload 是否干扰 Decode |
| Crash/OOM/错误 Token | 0 | 必须为 0 | 正确性门槛 |

建议判定条件：

```text
LMCache 有效
= 淘汰后确定性输出正确
+ 外部命中 Token/Bytes 可观测增长
+ 淘汰后 TTFT 明显低于 Baseline 重新 Prefill
+ 稳态吞吐和 TPOT 退化在事先约定范围内
+ Soak Test 无崩溃、OOM 或单调内存泄漏
```

如果外部命中为零，先判断目标 Prefix 是否真的被 GPU 淘汰，再查 Hybrid KV Group、dtype、Block Size 和 Connector 版本；不要只靠一次响应时间猜测命中。

## 10. 第二阶段：P/D 与跨节点

只有 A1 通过，才增加 P/D：

```text
Router → Prefill TP=8 → LMCache/NIXL Transfer → Decode TP=8
```

LMCache 官方 MP P/D 示例当前明确标注为 `1P1D` 且尚未针对性能优化。P/D 实验需要另行回答：

- 本次请求的 P/D 传输走 LMCache、NIXL 还是组合路径；
- Prefill Store 完成事件怎样通知 Router；
- Decode 读取的是本次 KV 还是历史 Prefix；
- 两节点是各自节点内 LMCache，还是一个真正可共享的远端 Backend；
- RDMA 是否实际生效；
- Cache 或一侧 Engine 故障时怎样转 Combined。

因此第一阶段清单故意不包含 P/D。若目标是跨节点中央 KV 池，LMCache MP 的节点内验证只是兼容性门槛，后续还要选择 LMCache Remote Backend、Mooncake Store 或其他分布式数据面并做严格对照。

## 11. 上游依据与已知风险

- [vLLM DeepSeek V4 Flash Recipe](https://github.com/vllm-project/recipes/blob/main/models/deepseek-ai/DeepSeek-V4-Flash.yaml)
- [vLLM KV Offload taxonomy：LMCacheMPConnector](https://github.com/vllm-project/recipes/blob/main/taxonomy.yaml)
- [LMCache MP Quickstart](https://docs.lmcache.ai/mp/quickstart.html)
- [LMCache MP Deployment](https://docs.lmcache.ai/mp/deployment.html)
- [LMCache MP P/D 示例](https://github.com/LMCache/LMCache/tree/dev/examples/disagg_prefill_mp)
- [DeepSeek V4 Prefix Cache Hybrid Group 已知问题](https://github.com/vllm-project/vllm/issues/42948)
- [DeepSeek V4 高并发 KV Offload 崩溃报告](https://github.com/vllm-project/vllm/issues/45475)
- [DeepSeek V4 DSpark External Hit 为零报告](https://github.com/vllm-project/vllm/issues/47890)
