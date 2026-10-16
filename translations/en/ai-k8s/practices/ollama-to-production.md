---
title: "From Ollama to Kubernetes Production Inference"
description: "Migrating local model validation into load-testable, canary-deployable, observable vLLM/KServe services"
status: lab
last_reviewed: 2026-08-04
---

# From Ollama to Kubernetes Production Inference

Ollama is well suited for confirming whether a model can run and whether prompt templates and API calls are correct, but the goal of a production migration is not to "put an Ollama container into a Pod" — it is to preserve the application contract while replacing it with a scalable, observable, and governable inference data plane.

## 1. Migration Path

```text
Ollama 本地验证
  → 固定模型 Revision、Tokenizer 与 Prompt Template
  → 导出 OpenAI 兼容 API 契约和回归集
  → vLLM/SGLang 单机复测
  → 构建不可变镜像与模型制品
  → Kubernetes GPU Deployment/ServingRuntime
  → Gateway、认证、限流和灰度
  → 压测、故障演练和 SLO
```

## 2. What to Preserve from the Local Phase

- The model name must not be just the Ollama alias; record the upstream repo and revision;
- Save the Modelfile, system prompt, chat template, quantization format, and context length;
- Build an API regression suite covering streaming, tool calling, stop tokens, and error inputs;
- Record time to first token, generation speed, peak memory, and output differences on the target hardware.

## 3. Single-Node Re-testing Before Production

Load the same model with the target production engine and confirm tokenizer, chat template, stop token, sampling parameters, structured output, and tool calling behavior. The fact that the APIs are both called `/v1/chat/completions` does not mean their semantics are fully identical.

## 4. Minimal Kubernetes Closed Loop

At minimum, include: GPU resource requests, read-only model mounts, startup/readiness/liveness probes, sufficient `/dev/shm`, graceful termination, PDB, NetworkPolicy, ServiceAccount, logs, and engine metrics. Readiness must be false until model loading is complete.

## 5. Release Gates

1. Regression suite quality passes;
2. TTFT/TPOT meet targets under the target concurrency;
3. Cold start and model download stay within budget;
4. After SIGTERM, stop accepting new requests and drain;
5. New and old models support canary deployment and fast rollback;
6. The gateway can identify tenant, model, token, and streaming cancellation.

Further reading: [Local Running](../inference/local-testing.md), [Inference Engine](../inference/engines.md), [Gateway](../inference/gateway-routing.md), [GPU Platform Experiments](../guides/gpu-platform-lab.md)
