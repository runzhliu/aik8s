# OpenTelemetry Kubernetes 五分钟实验

这个实验只演示 OpenTelemetry 的最短路径：

```text
telemetrygen Job -> OTLP/gRPC -> Collector -> debug exporter -> Collector logs
```

它不安装 Trace、Metric 或 Log 后端，便于先理解 Receiver、Processor、Exporter 和 Pipeline。

## 运行

```bash
kubectl apply -f collector.yaml
kubectl -n otel-basics rollout status deploy/otel-collector
kubectl apply -f trace-job.yaml
kubectl -n otel-basics wait --for=condition=complete job/telemetrygen-traces --timeout=120s
kubectl -n otel-basics logs deploy/otel-collector
```

Collector 日志中应出现五条 Trace，以及以下字段：

- `Trace ID`、`Span ID` 和父 Span；
- `service.name=checkout-demo`；
- `http.request.method=GET`；
- `http.response.status_code=200`；
- `k8s.namespace.name`、`k8s.pod.name`、`k8s.node.name` 等 Kubernetes Resource Attribute。

`debug` Exporter 适合学习和排障，生产环境应替换为真正的后端 Exporter，并降低日志详细度。

## 清理

```bash
kubectl delete namespace otel-basics
kubectl delete clusterrolebinding otel-basics-collector
kubectl delete clusterrole otel-basics-collector
```
