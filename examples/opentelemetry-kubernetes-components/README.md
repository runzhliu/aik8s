# OpenTelemetry Kubernetes Components

这个示例让 OpenTelemetry Collector 采集 Kubernetes 控制面、CoreDNS 与集群对象状态，再以 Prometheus 格式暴露给现有监控栈；可选的 OTLP 与 Tempo 链路用来查看 Trace 和 Span。

```text
API Server ──────────────┐
Controller Manager ──────┤
Scheduler ───────────────┤
etcd ────────────────────┼─> OTel Collector ─> /metrics ─> Prometheus ─> Grafana
CoreDNS ─────────────────┤
Kubernetes API objects ──┘

Application / API Server ─> OTLP ─> OTel Collector ─> Tempo ─> Grafana Explore
```

示例包含：

- `collector.yaml`：Namespace、RBAC、Collector、Service 和 ServiceMonitor；
- `grafana-dashboard.json`：可导入的 16 面板 Grafana Dashboard；
- `tempo-demo.yaml`：单实例 Tempo 与 10 GiB PVC，供实验环境保存 Trace；
- `grafana-tempo-datasource.yaml`：Grafana Tempo 数据源 provisioning 示例；
- `send-demo-traces.py`：只使用 Python 标准库发送带父子关系的 OTLP/HTTP Span。

## 适用范围

清单采用一个 Collector 副本，并把它调度到 control-plane 节点。`k8s_cluster` receiver 因此只运行一份，适合单控制面学习环境和功能验证。

部署前确认：

1. 集群已经安装 Prometheus Operator，存在 `ServiceMonitor` CRD；
2. API Server 的 `/metrics` 允许 ServiceAccount Bearer Token 访问；
3. Controller Manager `10257`、Scheduler `10259` 能从 Collector Pod 访问；
4. etcd 指标端口 `2381` 已启用且能从 Collector Pod 访问；
5. CoreDNS 在 `kube-dns.kube-system.svc.cluster.local:9153` 暴露指标；
6. Prometheus 的 `serviceMonitorSelector` 能选中本示例的 ServiceMonitor。

如需部署 Tempo，集群还应有默认 StorageClass，或者在 `tempo-demo.yaml` 的 PVC 中明确设置 `storageClassName`。示例使用单实例与本地块存储，适合学习和功能验证；生产环境应使用对象存储与高可用拓扑。

不同发行版的监听地址、证书和 Service 名称可能不同。先确认实际参数，再修改清单。

## 部署

先检查 Prometheus 选择 ServiceMonitor 的标签：

```bash
kubectl -n monitoring get prometheus -o yaml \
  | sed -n '/serviceMonitorSelector:/,/podMonitorSelector:/p'
```

`collector.yaml` 默认使用以下标签：

```yaml
labels:
  release: kube-prometheus-stack
```

如果现有 Prometheus 使用其他 selector，先修改标签，然后部署指标管道：

```bash
kubectl apply -f collector.yaml
kubectl -n otel-k8s-monitoring rollout status deploy/otel-k8s-components
```

检查 Collector：

```bash
kubectl -n otel-k8s-monitoring get pod,service,servicemonitor
kubectl -n otel-k8s-monitoring logs deploy/otel-k8s-components --tail=100
```

本地查看 Collector 导出的 Prometheus 指标：

```bash
kubectl -n otel-k8s-monitoring port-forward service/otel-k8s-components 8889:8889
curl -fsS http://127.0.0.1:8889/metrics | grep '^otel_k8s_' | head
```

## 查看 Trace 与 Span

指标和 Trace 是两条独立的数据流。Prometheus 指标不能自动还原成 Span；应用或 Kubernetes 组件必须实际发送 OTLP Trace。

先部署实验用 Tempo。已有同名 Tempo 时跳过这一步，并修改 Collector exporter 地址：

```bash
kubectl apply -f tempo-demo.yaml
kubectl -n otel-k8s-monitoring rollout status deploy/tempo
kubectl -n otel-k8s-monitoring get pvc/tempo-data
```

`collector.yaml` 已开放 OTLP/gRPC `4317` 与 OTLP/HTTP `4318`，并将 Trace 发送到 Tempo。向 Collector 发送一组成功与失败的父子 Span：

```bash
kubectl -n otel-k8s-monitoring port-forward service/otel-k8s-components 4318:4318
python3 send-demo-traces.py --endpoint http://127.0.0.1:4318/v1/traces --count 20
```

将 `grafana-tempo-datasource.yaml` 放进 Grafana provisioning 目录，或在 Grafana 的 **Connections → Data sources** 中新增 Tempo，URL 填写：

```text
http://tempo.otel-k8s-monitoring.svc.cluster.local:3200
```

打开 **Explore**，选择 Tempo，并用 TraceQL 搜索：

```traceql
{ resource.service.name = "otel-k8s-span-demo" }
{ resource.service.name = "otel-k8s-span-demo" && status = error }
{ resource.service.name = "otel-k8s-span-demo" && duration > 300ms }
```

进入单条 Trace 后，先看 Root Span 总耗时，再沿瀑布图寻找最长或标红的子 Span；随后展开该 Span，核对 `status`、events、`k8s.operation`、`k8s.resource.kind` 等属性。

### API Server Trace 需要额外配置

抓取 API Server `/metrics` 不会产生 API Server Span。Kubernetes 1.30 的 kube-apiserver 需要读取 `TracingConfiguration`，并通过 `--tracing-config-file` 启用。生产环境建议让控制面节点上的 host-network OTel Agent 监听 `127.0.0.1:4317`，再把 Trace 转发给 Gateway 或 Tempo；采样率先从 0.1%～1% 开始。

Kubernetes 1.30 配置示例：

```yaml
apiVersion: apiserver.config.k8s.io/v1alpha1
kind: TracingConfiguration
endpoint: 127.0.0.1:4317
samplingRatePerMillion: 10000  # 1%
```

在 kubeadm 管理的静态 Pod 中，还要把配置文件以 hostPath 挂载到 kube-apiserver，并增加：

```yaml
- --tracing-config-file=/etc/kubernetes/tracing/tracing-config.yaml
```

不同 Kubernetes 版本支持的配置 API 版本可能不同。修改静态 Pod 前先用对应版本的 kube-apiserver 验证配置，并保留原 manifest；变更会触发控制面组件重启。

## 导入 Grafana

在 Grafana 选择 **Dashboards → New → Import**，上传 `grafana-dashboard.json`，并选择保存这些 `otel_k8s_*` 指标的 Prometheus 数据源。

Dashboard 包含：

- 六类采集目标的在线状态；
- Ready Node、Deployment 副本与 Pod 阶段；
- API Server QPS、P95 与 APF 排队；
- Scheduler Pending Queue 与调度 P95；
- Controller Manager Workqueue；
- etcd leader、pending/failed proposals；
- CoreDNS 请求与错误；
- Collector 接收点数和 RSS。

## 高可用控制面

多控制面集群需要调整拓扑：

- 集群对象状态仍由一个 `k8s_cluster` receiver 采集，避免每个副本重复生成同一组指标；
- 每个控制面组件实例都要有独立 target，保留 `instance` 或节点标签；
- 可用 Prometheus service discovery、静态控制面地址列表或控制面专用 DaemonSet 发现所有实例；
- 多 Collector 接收同一组 targets 时要分片，避免重复序列；
- etcd metrics 端口只向监控网络开放。

如果还需要 Node、Pod 和 Container 的 CPU、内存、网络、文件系统指标，在每个节点增加 `kubeletstats` receiver DaemonSet；不要把它塞进这个集群级单副本 Collector 后再假设能覆盖所有 kubelet。

## 基数与容量

清单只保留看板和告警需要的指标，并用 `metrics_transform` 聚合 API Server、Scheduler 与 CoreDNS 的高基数标签。修改聚合规则时，先记录：

```promql
count({__name__=~"otel_k8s_.*"})
```

同时观察：

```promql
rate(otel_k8s_otelcol_receiver_accepted_metric_points_total[5m])
rate(otel_k8s_otelcol_receiver_refused_metric_points_total[5m])
rate(otel_k8s_otelcol_exporter_send_failed_metric_points_total[5m])
otel_k8s_otelcol_process_memory_rss
```

标签聚合会丢失细分维度。任何删除都应从实际 Dashboard、告警和排障查询反推，而不是凭感觉清理。

## 清理

```bash
kubectl delete -f collector.yaml
kubectl delete -f tempo-demo.yaml
```
