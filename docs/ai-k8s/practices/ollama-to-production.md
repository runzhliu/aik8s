---
title: 从 Ollama 到 Kubernetes 生产推理
description: 把本地模型验证迁移为可压测、可灰度、可观测的 vLLM/KServe 服务
status: lab
last_reviewed: 2026-08-04
---

# 从 Ollama 到 Kubernetes 生产推理

Ollama 很适合确认模型能否运行、Prompt 模板和 API 调用是否正确，但生产迁移的目标不是“把 Ollama 容器放进 Pod”，而是保持应用契约，同时替换为可扩展、可观测和可治理的推理数据面。

## 1. 迁移路径

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

## 2. 本地阶段要保存什么

- 模型名称不能只写 Ollama Alias，要记录上游 Repo 和 Revision；
- 保存 Modelfile、System Prompt、Chat Template、量化格式和上下文长度；
- 建立包含流式、工具调用、停止词和错误输入的 API 回归集；
- 记录目标硬件上的首 Token、生成速度、峰值内存和输出差异。

## 3. 生产前单机复测

用目标生产引擎加载相同模型，确认 Tokenizer、Chat Template、Stop Token、采样参数、Structured Output 和 Tool Calling 行为。API 都叫 `/v1/chat/completions` 不代表语义完全一致。

## 4. Kubernetes 最小闭环

至少包含：GPU 资源请求、模型只读挂载、启动/就绪/存活探针、足够的 `/dev/shm`、优雅终止、PDB、NetworkPolicy、ServiceAccount、日志和引擎指标。模型加载完成前 Readiness 必须为 false。

## 5. 发布门禁

1. 回归集质量通过；
2. 目标并发下 TTFT/TPOT 达标；
3. 冷启动和模型下载不超过预算；
4. SIGTERM 后停止接收新请求并排空；
5. 新旧模型可以 Canary 和快速回滚；
6. Gateway 能识别租户、模型、Token 和流式取消。

延伸阅读：[本地运行](../inference/local-testing.md)、[推理引擎](../inference/engines.md)、[Gateway](../inference/gateway-routing.md)、[GPU 平台实验](../guides/gpu-platform-lab.md)

