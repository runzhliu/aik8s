---
title: "Model GPU Memory and Concurrency Capacity Calculator"
description: "Estimate model weights, KV Cache, runtime overhead, maximum concurrency, and per-token cost"
status: lab
last_reviewed: 2026-08-04
---

# Model GPU Memory and Concurrency Capacity Calculator

Use estimates first to filter out clearly infeasible combinations, then measure with the target engine. The calculator cannot precisely account for quantization metadata, temporary Workspace, CUDA Graph, fragmentation, MoE activated experts, or engine version differences.

<div class="aik8s-calculator" data-calculator="model-memory">
  <label>Parameters (B)<input name="params" type="number" min="0.1" step="0.1" value="70"></label>
  <label>Bytes per parameter<input name="bytes" type="number" min="0.25" step="0.25" value="2"></label>
  <label>Number of GPUs<input name="gpus" type="number" min="1" step="1" value="8"></label>
  <label>GPU memory per card (GiB)<input name="memory" type="number" min="1" step="1" value="80"></label>
  <label>Runtime reserve ratio (%)<input name="reserve" type="number" min="0" max="60" step="1" value="15"></label>
  <label>KV Cache per request (GiB, measured)<input name="kv" type="number" min="0.01" step="0.01" value="1.2"></label>
  <output aria-live="polite"></output>
</div>

## 1. Basic Formulas

```text
权重 GiB ≈ 参数量 × 每参数字节 / 2^30
可用显存 ≈ GPU 数 × 单卡显存 × (1 - 运行时预留比例)
KV 预算 ≈ 可用显存 - 权重 - 其他常驻开销
理论并发 ≈ floor(KV 预算 / 单请求 KV Cache)
```

BF16/FP16 weights use approximately 2 bytes per parameter, but total GPU memory is never equal to the weight size. Quantization also introduces Scale, Zero Point, packing formats, and Kernel Workspace. Training additionally requires gradients, optimizer states, and activations, so this inference calculator must not be used for training.

## 2. Per-Request KV Cache

KV Cache depends on the number of layers, KV heads, head dimension, precision, input length, generated length, and parallel sharding. The most reliable approach is to fix a request length in the target engine, read the engine metrics or GPU memory delta, and then enter it into the calculator.

## 3. Cost Calculator

<div class="aik8s-calculator" data-calculator="token-cost">
  <label>GPU hourly price<input name="hourly" type="number" min="0" step="0.01" value="20"></label>
  <label>Number of GPUs<input name="gpus" type="number" min="1" step="1" value="1"></label>
  <label>Effective output tokens/s<input name="tokens" type="number" min="0.01" step="1" value="1000"></label>
  <label>Effective utilization (%)<input name="utilization" type="number" min="1" max="100" step="1" value="60"></label>
  <output aria-live="polite"></output>
</div>

The result covers GPU time only. Production cost should also include CPU, memory, storage, model distribution, network, idle redundancy, logging, control plane, and engineering support.

Further reading: [Inference Optimization](../inference/optimization.md), [Cost and Capacity](../cost-capacity.md)
