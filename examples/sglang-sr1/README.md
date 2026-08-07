# SGLang Model Gateway CPU 实验清单

这个清单在没有 GPU 的 Kubernetes 集群中启动：

- 1 个 SGLang Router v0.2.4；
- 2 个只模拟 OpenAI-Compatible API 的 CPU Worker；
- 基于 Pod Label 的 Kubernetes 动态发现；
- Router 的 Prometheus 指标端口。

```bash
kubectl apply -f examples/sglang-sr1/sglang-cpu-gateway.yaml
kubectl rollout status deployment/sglang-cpu-mock -n sglang-demo --timeout=180s
kubectl rollout status deployment/sglang-router -n sglang-system --timeout=180s
```

这个实验只能验收 Router 控制面。它不会加载模型，不能证明 SGLang Runtime、GPU 性能、跨节点并行、KV Cache 传输或 P/D 分离已经可用。

为保留 Kubernetes 动态发现，示例使用 Router 默认的 `sglang` 后端。v0.2.4 的 `openai` 后端不支持 Service Discovery；CPU Mock 也因此不启用认证。只应在隔离 Namespace 中复现，不要把这个无认证 Service 对外暴露。
