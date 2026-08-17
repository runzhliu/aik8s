# Qwen3.8-27B-FP8：单卡 L20 0-day 实验材料

这组公开清单用于在单张 NVIDIA L20 48 GB 上验证 Qwen3.8-27B-FP8、
vLLM 0.26.0、AIBrix 路由和 OpenWebUI。

## 固定制品

```text
runtime: vllm/vllm-openai
amd64 manifest: sha256:3c5c53248febaa72823a4b7e51aafa1cd2b65d860392e3930414da4d3864f541
model: /models/Qwen3.8-27B-FP8
served model: qwen3-8-27b-fp8-l20
GPU: NVIDIA L20, 46,068 MiB visible memory
```

公开清单使用名为 `qwen38-models` 的只读 PVC，并假设 Checkpoint 位于
`/models/Qwen3.8-27B-FP8`。请按实际存储实现准备 PVC；部署前确认
`outside.safetensors.tmp` 已消失且 `outside.safetensors` 存在。

## 预检和部署

```bash
kubectl apply -f preflight.yaml
kubectl -n qwen38-test logs -f pod/qwen3-8-27b-fp8-l20-preflight
kubectl -n qwen38-test delete pod qwen3-8-27b-fp8-l20-preflight

kubectl apply -f deployment.yaml
kubectl -n qwen38-test rollout status deployment/qwen3-8-27b-fp8-l20 --timeout=60m
```

第一轮固定为 FP8、TP=1、text-only、32K、FP8 KV、MTP Off。正确性与容量基线
通过后，已独立完成 MTP Off/1/2/3 A/B；Vision 和更长上下文继续作为单独变量。

## 服务冒烟

```bash
kubectl -n qwen38-test port-forward service/qwen3-8-27b-fp8-l20 28000:8000

curl -sS http://127.0.0.1:28000/v1/models
curl -sS http://127.0.0.1:28000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen3-8-27b-fp8-l20","messages":[{"role":"user","content":"只回复 QWEN38_OK"}],"temperature":0,"max_tokens":32,"chat_template_kwargs":{"enable_thinking":false}}'
```

## OpenWebUI

Deployment 带有 AIBrix 模型发现标签，Service 名称、served model 和
`model.aibrix.ai/name` 保持一致。AIBrix Gateway 验证通过后，把模型 ID 追加到
OpenWebUI 的现有 API 配置中，并保留其他已有模型配置：

```bash
kubectl -n <OPENWEBUI_NAMESPACE> set env deployment/open-webui \
  OPENAI_API_CONFIGS='<EXISTING_CONFIG_WITH_QWEN_MODEL_ID_ADDED>'
kubectl -n <OPENWEBUI_NAMESPACE> rollout status deployment/open-webui --timeout=10m
```

注册前必须先通过 AIBrix Gateway 发送一次真实 Chat Completions 请求，不能只检查
下拉框里是否出现模型。

## 压测顺序

使用服务容器中相同版本的 `vllm bench serve`：

1. 128/64，concurrency 1、4、8，各 64 请求；
2. 4096/128，concurrency 1、4，各 32 请求；
3. 32768/256，concurrency 1，正确性和 TTFT 边界；
4. MTP Off/1/2/3 对照已完成，结果见 `results/README.md`。

每轮保存完整命令、结果 JSON、Pod UID、节点、镜像 ID、GPU 显存、功耗、TTFT、
TPOT、ITL、E2EL、输入/输出吞吐与失败率。
