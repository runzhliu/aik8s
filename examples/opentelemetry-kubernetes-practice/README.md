# OpenTelemetry Kubernetes 实战

这个示例演示一条可复现的 Kubernetes 可观测链路：

```text
FastAPI workload
  ├─ OTLP traces  ─┐
  └─ OTLP metrics ─┼─> OpenTelemetry Collector Gateway
                   ├─ traces  -> Langfuse
                   ├─ metrics -> Prometheus exporter -> Prometheus/Grafana
                   └─ logs    -> debug（生产可换 Loki/Elasticsearch）
```

## 目录

- `app/`：手工埋点与 FastAPI 自动埋点示例；
- `k8s/collector.yaml`：Collector、RBAC、Service 和 ServiceMonitor；
- `k8s/app.yaml`：两副本测试应用；
- `k8s/load-job.yaml`：正常、慢请求和错误请求流量。
- `grafana-dashboard.json`：请求速率、平均延迟、P95 和 Collector Target 看板。

## 构建应用

```bash
docker build -t REGISTRY/otel-k8s-demo:v1 app
docker push REGISTRY/otel-k8s-demo:v1
```

将 `k8s/app.yaml` 中的 `REPLACE_WITH_IMAGE` 替换为实际镜像。

## 准备 Langfuse 凭据

```bash
kubectl apply -f k8s/namespace.yaml
kubectl -n otel-practice create secret generic langfuse-credentials \
  --from-literal=public-key='REPLACE_WITH_PUBLIC_KEY' \
  --from-literal=secret-key='REPLACE_WITH_SECRET_KEY'
```

如果不需要 Langfuse，从 Collector 的 traces pipeline 中移除 `otlp_http/langfuse` 和 `basicauth/langfuse` 即可。
将 `LANGFUSE_OTLP_ENDPOINT` 改成实际的 Langfuse Service 地址；如果 Prometheus 通过标签筛选
`ServiceMonitor`，还需要给示例中的 `ServiceMonitor` 增加与其 selector 匹配的标签。

## 部署与验证

```bash
kubectl apply -f k8s/collector.yaml
kubectl apply -f k8s/app.yaml
kubectl create -f k8s/load-job.yaml

kubectl -n otel-practice rollout status deploy/otel-collector
kubectl -n otel-practice rollout status deploy/checkout-demo
kubectl -n otel-practice logs deploy/otel-collector
```

Prometheus 查询示例：

```promql
sum by (demo_mode, demo_result) (rate(otel_demo_demo_requests_total[5m]))
```

Collector 使用的 Langfuse OTLP 地址需要指向 `/api/public/otel`。公开清单只包含占位凭据，不应把填入真实值后的 Secret 提交到仓库。
