# Qwen3.8-Flash-Next + SGLang Day-0 实验材料

这组清单用于验证 Qwen3.8-Flash-Next 在 Kubernetes 上通过 SGLang
Day-0 镜像启动、提供 OpenAI-compatible API，并完成 Thinking、Tool Call 和
固定长度短基准。

首轮实测使用官方 FP8 Checkpoint。已验证基线是 4 张 141 GB H20、TP4/EP4、
原生 262K Context，并显式开启 `--ple-offload-embedding`。官方 FP8 权重约 172.76 GiB；
权重能放进显存仍不代表 QSA、Gated DeltaNet、MoE Kernel 和 CUDA Graph 都与目标
GPU 架构兼容。

## 固定制品

```text
model: Qwen/Qwen3.8-Flash-Next
BF16 upstream revision at release: f5d08274bafd880402bd16f5e3e6c514136ec06c
architecture: Qwen4ExpForConditionalGeneration
model type: qwen4_exp
native context: 262,144 tokens
BF16 weight index total_size: 359,999,963,128 bytes
BF16 shards: 131
upstream image: lmsysorg/sglang:qwen38flashnext
upstream linux/amd64 digest: sha256:12d3392bdc8be8d35e9a95f191df6aef99c5114bdbefd41bfdc7e760e6d25ec1
SGLang: 0.0.0.dev1+gd91c3682b
PyTorch / CUDA / Transformers: 2.13.0 / 13.0 / 5.12.1
SGLang support: PR #36497，尚未进入正式版本 tag
```

官方 FP8 仓库 `Qwen/Qwen3.8-Flash-Next-FP8` 在发布时的 Revision 是
`bcd9f01ddc9cff2316eb84281bebcd5b058bddce`，权重 Index 总计
`185,502,232,570` Bytes、131 个分片。它是官方发布的 FP8 制品，不是社区临时量化。

正式实验应把模型 Revision、镜像 linux/amd64 Digest 和节点 GPU UUID 写入结果记录，
不要只保留可变 tag。

## 使用前修改

1. 准备名为 `qwen38-flash-next-models` 的只读 PVC；
2. 确保 Checkpoint 位于 `/models/Qwen3.8-Flash-Next-FP8`，若同步工具生成 `v1`
   等版本子目录，启动参数必须指向真正同时包含配置、索引和分片的目录；
3. 将两个 YAML 中的示例 Node Label 替换成目标集群经过验证的 GPU 节点标签；
4. 将镜像 tag 替换成已经验证的 linux/amd64 Digest；
5. 确认节点有足够的 GPU、主机内存和 `/dev/shm`。

## 先做零 GPU 预检

```bash
kubectl apply -f preflight.yaml
kubectl -n qwen38-flash-next-lab logs -f pod/qwen38-flash-next-preflight
```

预检必须验证：

- 131 个权重分片全部存在且非空；
- Index 中的总权重字节数与官方 Revision 一致；
- `config.json`、`model.safetensors.index.json`、Tokenizer 和 Chat Template 与权重位于
  同一个启动目录；只检查分片数量和目录大小不够；
- `architectures` 与 `model_type` 是新的 Qwen4 Preview 架构；
- Day-0 镜像中确实包含 `Qwen4ExpForConditionalGeneration`；
- SGLang CLI 包含 PLE Offload、QSA/GDN Backend、TP/EP 和 Parser 参数。

预检失败时不要申请 GPU。

## 启动 TP4 基线

```bash
kubectl apply -f deployment.yaml
kubectl -n qwen38-flash-next-lab rollout status \
  deployment/qwen38-flash-next-sglang --timeout=90m
kubectl -n qwen38-flash-next-lab logs -f \
  deployment/qwen38-flash-next-sglang
```

端口转发：

```bash
kubectl -n qwen38-flash-next-lab port-forward \
  service/qwen38-flash-next-sglang 30000:30000
```

执行正确性冒烟：

```bash
BASE_URL=http://127.0.0.1:30000/v1 \
MODEL=qwen38-flash-next \
python3 smoke.py
```

## 性能基线

在带有 SGLang Python 包的环境中运行：

```bash
HOST=127.0.0.1 \
PORT=30000 \
MODEL=qwen38-flash-next \
bash benchmark.sh
```

默认跑三组短基线和一组 4K 输入：

| 并发 | 输入 | 输出 | 请求数 | 用途 |
| ---: | ---: | ---: | ---: | --- |
| 1 | 128 | 64 | 16 | 单请求延迟与 ITL |
| 4 | 128 | 64 | 32 | 短请求连续批处理 |
| 8 | 128 | 64 | 64 | 并发吞吐扩展 |
| 4 | 4,096 | 128 | 16 | 常规 RAG/Agent Turn |

脚本使用 `random-ids`、本地 Tokenizer 和 SGLang 原生端点，保证输入 Token 数精确。
正确性仍需单独通过 OpenAI-compatible API 验证。运行前还要确认健康检查不会触发真实
推理；本次 Day-0 镜像的 `GET /health` 会执行一次 64-token 生成，因此示例清单改用
TCP Socket 探针，否则后台探针会污染并发数、TTFT 和吞吐。

设置 `FULL=1` 会增加 1K 长输出、32K/64K/128K/261K 单并发和共享前缀对照。
H20 实测已经跑通原生 262K；1M 需要启用 YaRN，并单独记录 KV Cache、Prefill 时间和
业务意义，不能由 262K 结果直接外推。

## 失败后的回退顺序

目标硬件上 TP4 启动失败时，不要同时修改多个变量：

1. 保留完整 OOM 或 Backend Traceback；
2. 确认 `--ple-offload-embedding` 实际生效；
3. 降低 `--mem-fraction-static` 或 Context 只能解决 KV/Runtime 空间，不会缩小权重；
4. 改为 TP8/EP8，并把 GPU 请求同步改成 8；
5. 若当前使用 BF16，再切换约 172.76 GiB 的官方 FP8 Checkpoint；
6. 不在运行中的容器里临时升级 Python 包，避免失去镜像可复现性。

结构化实测数据见 [`results/h20-fp8-summary-20260827.json`](results/h20-fp8-summary-20260827.json)。
截至 2026-08-27，vLLM 的模型实现与 PLE/QSA Kernel 仍分别处于
[PR #53896](https://github.com/vllm-project/vllm/pull/53896)、
[PR #53899](https://github.com/vllm-project/vllm/pull/53899) 和
[PR #53909](https://github.com/vllm-project/vllm/pull/53909)，不能把 PR 分支实验写成稳定版支持。

参考：[Qwen 模型卡](https://huggingface.co/Qwen/Qwen3.8-Flash-Next)、
[SGLang Cookbook](https://docs.sglang.io/cookbook/autoregressive/Qwen/Qwen3.8-Flash-Next)、
[SGLang PR #36497](https://github.com/sgl-project/sglang/pull/36497)
