# GLM-5.3 H20 部署与压测计划

这组材料用于 `zai-org/GLM-5.3` 权重同步完成后，在单节点 8×141GB H20 上验证
SGLang 与 vLLM。当前状态是**镜像准备与测试计划**，不是实测结果。

## 官方支持边界

| 引擎 | 最低版本/镜像 | H20 状态 |
| --- | --- | --- |
| vLLM | 0.28.0+，Transformers 5.15.0+ | 官方 Recipe 明确列出 8×H20 141GB FP8 |
| SGLang | 支持 GLM-5.3 的 `latest`/预发布版 | Cookbook 覆盖 H200/Hopper 能力，但没有点名 H20，需本地实测 |

SGLang 在 Hopper 上默认选择 BF16 KV；vLLM 的公平基线使用 `--kv-cache-dtype auto`。
FP8 KV、MTP 和 Prefix Cache 都要等 Target-only 基线稳定后分别做单变量 A/B。

## 目录

```text
images/                   # 固定 linux/amd64 上游 Manifest 的镜像入口
preflight.py              # 141 分片、Revision、量化和 Runtime/CLI 预检
preflight-sglang.yaml     # SGLang 零 GPU 预检 Job
preflight-vllm.yaml       # vLLM 零 GPU 预检 Job
deployment-sglang.yaml    # SGLang TP8、128K、MTP/Cache Off 起点
deployment-vllm.yaml      # vLLM TP8、128K、MTP/Cache Off 起点
smoke.py                  # Reasoning、Tool Call、流式、多轮和错误输入
benchmark.sh              # 统一 Case 矩阵；默认只打印命令
prefix_cache.py           # 4K/32K 精确重复前缀与流式 TTFT
needle.py                 # 长上下文 10%/50%/90% Needle
cases.csv                 # 短压、Decode、官方负载和长上下文 Case
results/                  # 实测 JSON、JSONL、日志摘要和环境清单
```

## Gate 0：零 GPU 预检

先检查 YAML 里的命名空间、PVC、模型路径、镜像和节点名。内部镜像 Tag 仍要在目标仓库
核对 `linux/amd64` Manifest 与 Digest，不能仅凭 Tag 相同认定镜像一致。

```bash
kubectl create namespace glm53-lab
kubectl -n glm53-lab create configmap glm53-preflight \
  --from-file=preflight.py \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl apply -f preflight-sglang.yaml
kubectl apply -f preflight-vllm.yaml
kubectl -n glm53-lab logs job/glm53-preflight-sglang
kubectl -n glm53-lab logs job/glm53-preflight-vllm
```

预检固定 141 个分片、Index Tensor 的 `755617140416` 字节，以及本地分片文件合计的
`755632050320` 字节。Safetensors 文件包含 Header，因此这两个数本来就不相等。
同步流程若生成 `REVISION` 或 `.revision`，应在两个 Job 中加入 `EXPECTED_REVISION`。

## Gate 1：最小启动与功能正确性

两个引擎必须串行占用同一台空闲 H20 节点。先启动其中一个：

```bash
kubectl apply -f deployment-sglang.yaml
kubectl -n glm53-lab rollout status deployment/glm53-sglang-day1 --timeout=120m
kubectl -n glm53-lab port-forward service/glm53-sglang-day1 30000:30000

BASE_URL=http://127.0.0.1:30000/v1 MODEL=glm-5.3 python3 smoke.py
```

vLLM 对应端口是 8000。Smoke 必须通过 `/v1/models`、流式输出、三档 Reasoning、
`glm47` 多工具选择、参数 JSON、多轮、畸形请求拒绝和图片输入拒绝。服务返回 HTTP 200
但 Parser 或内容错误仍判失败。

## Gate 2：统一性能基线

`benchmark.sh` 默认 Dry-run；只有显式设置 `EXECUTE=1` 才发压测请求。先审阅命令：

```bash
ENGINE=sglang STAGE=baseline \
BASE_URL=http://127.0.0.1:30000 \
TOKENIZER=/models/GLM-5.3/v1 \
bash benchmark.sh

ENGINE=sglang STAGE=baseline EXECUTE=1 \
BASE_URL=http://127.0.0.1:30000 \
TOKENIZER=/models/GLM-5.3/v1 \
bash benchmark.sh
```

可用 `STAGE=smoke|baseline|decode|official|long|extreme|all` 选阶段，也可用
`CASE_ID=rag-16k-256-c4` 精确选一行。脚本默认 `MAX_CONTEXT=131072`，会明确跳过超出
当前服务窗口的 Case；扩大服务 Context 后再同步提高这个值。每轮执行前会清 Prefix
Cache，保留逐请求明细、P50/P95/P99 TTFT/TPOT/ITL/E2E 和输入输出吞吐。

默认 `BENCH_CLIENT=vllm`，两个服务端都由同一个 vLLM Benchmark 客户端生成完全相同
的随机请求集合；压 SGLang 时也不要换客户端。只有补充观察 SGLang MTP Accept Length
时，才额外运行 `BENCH_CLIENT=sglang-native`，这组补充数据不与主基线混合比较。

## Gate 3：Prefix Cache 单变量

缓存实验前，SGLang 删除 `--disable-radix-cache`，vLLM 删除
`--no-enable-prefix-caching`，重新部署并确认 Ready。vLLM 的 Cache Reset 端点依赖
`VLLM_SERVER_DEV_MODE=1`，只应在隔离测试环境使用。

```bash
ENGINE=sglang \
BASE_URL=http://127.0.0.1:30000 \
TOKENIZER=/models/GLM-5.3/v1 \
PREFIX_LENGTHS=4096,32768 \
python3 prefix_cache.py > results/sglang-prefix-cache.jsonl
```

脚本对每种长度先清缓存，再执行一次冷请求和五次热请求，并同时保存流式 TTFT、答案
Marker 和 `/metrics` 中的 Cache 指标。只有热 TTFT 改善且指标真实增长，才算缓存有效。

## Gate 4：长上下文正确性

初始 128K 服务先测 32K/64K/128K：

```bash
ENGINE=sglang \
BASE_URL=http://127.0.0.1:30000/v1 \
TOKENIZER=/models/GLM-5.3/v1 \
LENGTHS=32768,65536,131072 \
POSITIONS=0.1,0.5,0.9 \
python3 needle.py > results/sglang-needle-128k.jsonl
```

全部正确后，逐级把两个 Deployment 的 Context 调到 256K、512K，再做 1M 单并发能力
探针。每次只提高一级，并同步修改 `LENGTHS`/`MAX_CONTEXT`；OOM、Kernel 错误、Pod
重启或 Needle 错误都应立即停止并保存日志。H20 上不得把模型声明的 1M 窗口写成已经
验证的服务能力。

## Gate 5：MTP 与 FP8 KV

Target-only 数据稳定后分别做 A/B：

- vLLM：加入 `--speculative-config.method mtp` 和
  `--speculative-config.num_speculative_tokens 5`；
- SGLang Balanced：`EAGLE` 的 `steps=1, topk=1, draft_tokens=2`；低延迟路线再测
  `steps=5, topk=1, draft_tokens=6`；
- FP8 KV 单独开一轮。SGLang/Hopper 使用 `fp8_e4m3` 时同时验证官方指定的原生 FP8
  DSA Prefill/Decode Kernel，不能只改 KV Dtype；
- 每轮保存 Draft Tokens、Accept Length、Verify 开销、显存以及 P95/P99。

完整设计见
[`glm53-h20-sglang-vllm-test-plan.md`](../../docs/ai-k8s/practices/glm53-h20-sglang-vllm-test-plan.md)。

参考：

- [GLM-5.3 模型卡](https://huggingface.co/zai-org/GLM-5.3)
- [SGLang GLM-5.3 Cookbook](https://docs.sglang.io/cookbook/autoregressive/GLM/GLM-5.3)
- [vLLM GLM-5.3 Recipe](https://recipes.vllm.ai/zai-org/GLM-5.3)
