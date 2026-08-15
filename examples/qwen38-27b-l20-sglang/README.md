# Qwen3.8-27B-FP8：SGLang 单卡 L20 0-day 材料

固定制品：

```text
upstream: lmsysorg/sglang:v0.5.16-cu129-runtime
upstream index: sha256:f9a7b74fb843cb2089320fa7f09b6bc7892e3ce5da3b284134c466ed8d897a93
linux/amd64 manifest: sha256:29f0f645122be1799a594c15907d81da326dbbe6ccd6395710a07a4292125a5f
SGLang: 0.5.16 (commit fdebc938f7f4d16fe6b9f55dcd9a767cf0899ea1)
PyTorch: 2.11.0+cu129
Transformers: 5.12.1
model: /models/Qwen3.8-27B-FP8
served model: qwen3-8-27b-fp8-l20-sglang
```

首轮加载完整多模态 Checkpoint，不启用 `--language-only`；MTP/EAGLE 关闭。
这两个变量都存在 Qwen3.5 Hybrid GDN 相关的上游问题记录，应在基础正确性通过后
独立 A/B。公开清单使用名为 `qwen38-models` 的只读 PVC，并假设 Checkpoint 位于
`/models/Qwen3.8-27B-FP8`。

单卡 L20 首次启动在默认 8192-token prefill CUDA Graph 捕获阶段 OOM；清单仅将
`--cuda-graph-backend-prefill` 设为 `disabled`，保留 decode CUDA Graph。不要把这
个稳定性修复误写成“默认参数直接启动成功”，也不要与 vLLM 的 TTFT 做无条件横比。

## 预检与部署

```bash
kubectl apply -f preflight.yaml
kubectl -n qwen38-test logs -f pod/qwen3-8-27b-fp8-l20-sglang-preflight
kubectl -n qwen38-test delete pod qwen3-8-27b-fp8-l20-sglang-preflight

kubectl apply -f deployment.yaml
kubectl -n qwen38-test rollout status deployment/qwen3-8-27b-fp8-l20-sglang --timeout=60m
```

`deployment.yaml` 会申请一张额外 L20。部署前重新检查目标节点资源；若没有空闲卡，
先把 vLLM Deployment 缩为 0，再启动 SGLang，避免两个 Engine 争抢同一 GPU。

## 冒烟与公平 A/B

```bash
kubectl -n qwen38-test port-forward service/qwen3-8-27b-fp8-l20-sglang 23000:30000
curl -sS http://127.0.0.1:23000/v1/models
```

正确性顺序与 vLLM 相同：关闭 Thinking、开启 Thinking、结构化 Tool Call、工具结果
回填。性能 A/B 继续从 vLLM 客户端调用 SGLang 的 OpenAI-compatible endpoint，
固定相同 Tokenizer、随机种子、输入/输出长度、并发、请求数和到达率，只替换 URL
与 Served Model Name。
