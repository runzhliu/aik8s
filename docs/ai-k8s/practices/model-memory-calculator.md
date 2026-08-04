---
title: 模型显存与并发容量计算器
description: 估算模型权重、KV Cache、运行时开销、最大并发和单位 Token 成本
status: lab
last_reviewed: 2026-08-04
---

# 模型显存与并发容量计算器

先用估算筛掉明显不可行的组合，再用目标引擎实测。计算器不能精确包含量化元数据、临时 Workspace、CUDA Graph、碎片、MoE 激活专家和引擎版本差异。

<div class="aik8s-calculator" data-calculator="model-memory">
  <label>参数量（B）<input name="params" type="number" min="0.1" step="0.1" value="70"></label>
  <label>每参数字节数<input name="bytes" type="number" min="0.25" step="0.25" value="2"></label>
  <label>GPU 数量<input name="gpus" type="number" min="1" step="1" value="8"></label>
  <label>单卡显存（GiB）<input name="memory" type="number" min="1" step="1" value="80"></label>
  <label>运行时预留比例（%）<input name="reserve" type="number" min="0" max="60" step="1" value="15"></label>
  <label>每请求 KV Cache（GiB，实测）<input name="kv" type="number" min="0.01" step="0.01" value="1.2"></label>
  <output aria-live="polite"></output>
</div>

## 1. 基础公式

```text
权重 GiB ≈ 参数量 × 每参数字节 / 2^30
可用显存 ≈ GPU 数 × 单卡显存 × (1 - 运行时预留比例)
KV 预算 ≈ 可用显存 - 权重 - 其他常驻开销
理论并发 ≈ floor(KV 预算 / 单请求 KV Cache)
```

BF16/FP16 权重大约使用 2 Bytes/参数，但总显存绝不等于权重大小。量化还会引入 Scale、Zero Point、打包格式和 Kernel Workspace。训练还需计算梯度、优化器状态和激活，不能使用这个推理计算器。

## 2. 单请求 KV Cache

KV Cache 与层数、KV Head、Head Dimension、精度、输入长度、已生成长度和并行切分有关。最可靠的方法是在目标引擎中固定一个请求长度，读取引擎指标或显存增量，再填入计算器。

## 3. 成本计算器

<div class="aik8s-calculator" data-calculator="token-cost">
  <label>GPU 每小时价格<input name="hourly" type="number" min="0" step="0.01" value="20"></label>
  <label>GPU 数量<input name="gpus" type="number" min="1" step="1" value="1"></label>
  <label>有效输出 Token/s<input name="tokens" type="number" min="0.01" step="1" value="1000"></label>
  <label>有效利用率（%）<input name="utilization" type="number" min="1" max="100" step="1" value="60"></label>
  <output aria-live="polite"></output>
</div>

结果只包含 GPU 时间。生产成本还应加入 CPU、内存、存储、模型分发、网络、空闲冗余、日志、控制面和工程支持。

延伸阅读：[推理优化](../inference/optimization.md)、[成本与容量](../cost-capacity.md)
