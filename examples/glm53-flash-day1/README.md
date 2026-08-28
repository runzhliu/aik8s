# GLM-5.3-Flash Day-1 部署与压测示例

这组材料已经在 GLM-5.3-Flash 的 SGLang 与 vLLM 专用镜像上执行。默认模型是
官方原生 FP8 Checkpoint，硬件起点是单机 4 张大显存 Hopper GPU、TP4；BF16 权重、
P/D 分离和 RDMA 不属于第一轮。

截至 2026-08-28：

- SGLang 已提供专用镜像 `lmsysorg/sglang:glm-5.3-flash` 和完整官方 Cookbook；
- vLLM 已提供专用镜像 `vllm/vllm-openai:glm53-flash` 和官方 Recipe，但测试当天
  主仓支持 PR #53906 仍未合入，专用镜像应按预览实现看待；
- 两边都应先使用 GLM-5.3-Flash 专用镜像，不能拿 `latest` 代替；
- 上线实验前要把可变 Tag 固定成目标架构的镜像 Digest。

2026-08-27 解析到的公开镜像制品如下，示例 YAML 已固定 `linux/amd64` Manifest：

| 引擎 | 专用 Tag 的 Index / Manifest List | `linux/amd64` Manifest |
| --- | --- | --- |
| SGLang | `sha256:e6f5482505e7502f791fe4615ad1fbec118cbbd6b44e98f2479b16b98b985ad6` | `sha256:0836f0160fa785e424e68d13ef88ddd548f87e6e11ad9f0e4de982e4f9188aaf` |
| vLLM | `sha256:2c6da6c6f16ed15c91e412d896dba13701f25fe1861eaec9ddaa4db34d1d21c4` | `sha256:2e771fa615452282cc331eb418b3ef21636fce355bea0491fca89e6d362ab703` |

Digest 是 2026-08-27 的快照。若上游更新专用 Tag，应把新旧镜像当成两个版本分别留结果，
不能覆盖后继续合并统计。

## 目录

```text
preflight.py              # 模型目录与镜像实现的零 GPU 检查
preflight-sglang.yaml     # SGLang 镜像预检 Job
preflight-vllm.yaml       # vLLM 镜像预检 Job
deployment-sglang.yaml    # H20/Hopper FP8 权重 + BF16 KV 起点
deployment-vllm.yaml      # 同样硬件与模型的 vLLM 起点
smoke.py                  # Reasoning、Tool Call、图片/视频正确性
needle.py                 # 长上下文 Needle 与 262K 冷 Prefill 边界
prefix_cache.py           # 精确重复 Prompt 的 Cache 命中与流式 TTFT
cases.csv                 # 短压、Decode、长上下文和极限 Case
benchmark.sh              # 默认 Dry-run 的 OpenAI-compatible 压测入口
results/                  # 脱敏聚合 JSON 与逐轮 CSV
```

## 为什么 H20 模板用 BF16 KV

官方模型是 FP8 权重，但“权重精度”和“KV Cache 精度”是两件事。SGLang Cookbook
在 Blackwell 上使用 FP8 KV + TRT-LLM DSA，在 H100/H200 上使用 BF16 KV +
TileLang DSA；vLLM Recipe 也明确说明 Hopper 必须使用 BF16 KV。H20 同属 Hopper，
本次使用 BF16 KV + TileLang DSA 完成了 H20 实测，但它仍不代表其他 Hopper GPU 或
Runtime Commit 会得到相同结果。

## Gate 0：模型和镜像零 GPU 预检

先把示例命名空间、PVC、模型路径和 Node Label 替换成测试环境的值。创建脚本
ConfigMap，再分别运行两个专用镜像：

```bash
kubectl create namespace glm53-flash-lab
kubectl -n glm53-flash-lab create configmap glm53-flash-preflight \
  --from-file=preflight.py \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl apply -f preflight-sglang.yaml
kubectl apply -f preflight-vllm.yaml
kubectl -n glm53-flash-lab logs job/glm53-flash-preflight-sglang
kubectl -n glm53-flash-lab logs job/glm53-flash-preflight-vllm
```

预检不申请 GPU，并且同时检查：

- `config.json` 的 `glm5_next` 与 `Glm5NextForConditionalGeneration`；
- Index 引用的所有 Safetensors 分片均存在且非空；
- Tokenizer 与 Chat Template 没有和权重错目录；
- 镜像运行时确实注册新架构；
- 部署所需 CLI 参数确实存在；
- 实际分片数、Index 总字节数、镜像包版本和可选 Revision。

同步工具若能生成 `REVISION` 文件，还可以设置 `EXPECTED_REVISION`；第一次完整同步后，
把输出的 `weight_bytes_from_index` 与 `weight_shards` 固定为后续预检的期望值。不要用
目录总大小代替 Weight Index，因为缓存文件和半同步分片会误导判断。

## Gate 1：先跑不带 MTP 的 Target-only 基线

先只启动一种引擎，避免两套服务争抢 GPU：

```bash
kubectl apply -f deployment-sglang.yaml
kubectl -n glm53-flash-lab rollout status deployment/glm53-flash-sglang --timeout=90m
kubectl -n glm53-flash-lab port-forward service/glm53-flash-sglang 30000:30000
```

确认加载、Warmup 和 CUDA Graph 完成后，先做正确性：

```bash
BASE_URL=http://127.0.0.1:30000/v1 \
MODEL=glm53-flash \
python3 smoke.py
```

指定 `IMAGE_PATH` 可测图片，指定 `VIDEO_PATH` 可测视频。视频测试前要确认服务镜像包含
`torchcodec`，并从小视频开始；不要一上来就把 240K Visual Token 上限当普通 Smoke。

## Gate 2：短压与 Decode

`benchmark.sh` 默认只是 Dry-run，先审阅完整命令。真正执行必须显式设置
`EXECUTE=1`：

```bash
ENGINE=sglang STAGE=smoke bash benchmark.sh

ENGINE=sglang STAGE=baseline EXECUTE=1 \
BASE_URL=http://127.0.0.1:30000 \
TOKENIZER=/models/GLM-5.3-Flash \
bash benchmark.sh

ENGINE=sglang STAGE=decode EXECUTE=1 \
BASE_URL=http://127.0.0.1:30000 \
TOKENIZER=/models/GLM-5.3-Flash \
bash benchmark.sh
```

第一轮记录并发 1/4/8/16/32 的 Request Throughput、Output TPS、P50/P95/P99
TTFT、TPOT、ITL 和 E2E。16K 输出只做一次能力验证，不混入日常吞吐平均值。

## Gate 3：长上下文必须跨过 262K 边界

社区已经报告 SGLang 首发构建在“冷缓存、输入超过约 262K、首个 Decode Token”
时可能触发 CUDA Graph Replay 崩溃。因此不能只测 4K/32K，也不能直接跳到 1M：

```bash
ENGINE=sglang STAGE=long EXECUTE=1 bash benchmark.sh
ENGINE=sglang STAGE=boundary EXECUTE=1 bash benchmark.sh

ENGINE=sglang \
LENGTHS=32768,131072,261120,263168,289000 \
POSITIONS=0.1,0.5,0.9 \
BASE_URL=http://127.0.0.1:30000/v1 \
TOKENIZER=/models/GLM-5.3-Flash \
python3 needle.py
```

每个 Repeat 前都清缓存。只有 255K 下方和 257K 上方均稳定、Needle 正确、服务没有
Crash，才继续 `STAGE=extreme` 的 512K 与接近 1M 测试。若仅在边界上方复现 CUDA
Graph Replay 问题，再单独增加 `--disable-cuda-graph` 做控制变量复测，不要直接改掉
基线。长上下文失败时要保留服务端首个 Decode Token 附近的日志，不能只记录客户端
Timeout。

## Gate 4：Prefix Cache 要看真实命中

精确重复同一个约 4,400 Token Prompt，先冷后热，联合观察流式 TTFT 和 `/metrics`：

```bash
ENGINE=sglang \
BASE_URL=http://127.0.0.1:30000 \
TOKENIZER=/models/GLM-5.3-Flash \
python3 prefix_cache.py
```

vLLM 版本的 Cache Reset 端点只在 Development Mode 下开放。示例 YAML 仅为隔离的
Benchmark 环境开启它，不能把该端点暴露到生产入口。首日社区报告曾出现 22.8K
Prefix Cache Query、零 Hit 的情况，所以“参数已开启”不等于“缓存正在工作”。

## Gate 5：再做 SGLang / vLLM A/B 和 MTP A/B

完成 SGLang 后释放服务，再应用 `deployment-vllm.yaml`，将上面的 `ENGINE` 和端口改为
`vllm` / `8000`，用相同模型 Revision、GPU、Case、并发、采样与重复次数复跑。

Target-only 数据稳定后才加入 MTP：

- SGLang 低延迟起点：`EAGLE` + Adaptive MTP 5/1/6；
- vLLM 低延迟起点：`{"method":"mtp","num_speculative_tokens":5}`；
- 高并发吞吐保留 MTP Off 对照，因为 Draft/Verify 开销不一定带来收益；
- 记录 Acceptance Length、Draft Token 数与显存，而不只比较 Output TPS。

P/D 和 RDMA 放到最后。在 Combined Target-only 尚未稳定前做 P/D，只会把模型 Kernel、
KDA/KV 状态迁移与网络问题混在一起。

本次脱敏结果位于 [`results`](results/)，完整分析见
[公开实测报告](../../docs/ai-k8s/practices/glm53-flash-day1-h20.md)。

参考：

- [GLM-5.3-Flash 模型卡](https://huggingface.co/zai-org/GLM-5.3-Flash)
- [SGLang GLM-5.3-Flash Cookbook](https://docs.sglang.io/cookbook/autoregressive/GLM/GLM-5.3-Flash)
- [vLLM GLM-5.3-Flash Recipe](https://recipes.vllm.ai/zai-org/GLM-5.3-Flash)
- [vLLM 支持 PR #53906](https://github.com/vllm-project/vllm/pull/53906)
- [SGLang 262K 冷 Prefill 问题 #36550](https://github.com/sgl-project/sglang/issues/36550)
