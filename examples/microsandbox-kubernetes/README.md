# Microsandbox Kubernetes 实验

[English](README.en.md) · [中文文章](../../docs/ai-k8s/rag-agent/microsandbox-kubernetes-practice.md) · [English article](../../translations/en/ai-k8s/rag-agent/microsandbox-kubernetes-practice.md)

实际使用 Microsandbox 0.7.8，在一个 Kubernetes Pod 内验证代码执行、隔离、四 guest 并发、Live Fork 和跨 Pod 重建的完整/磁盘快照。`results.json` 保留首轮的两条 managed-job 拒绝记录，以及修正后独立 attempt 的结果；并非每次尝试都成功。

需要 Linux x86_64、可用 KVM、暴露 `devices.kubevirt.io/kvm` 的现有设备插件，以及可用存储类。此示例不会安装设备插件或修改宿主网络，也没有部署官方云端服务；页面是配套 SDK 工作台。

```bash
docker build --platform linux/amd64 -t registry.example.org/lab/microsandbox:0.7.8 examples/microsandbox-kubernetes
docker push registry.example.org/lab/microsandbox:0.7.8
python3 examples/microsandbox-kubernetes/render.py \
  --test-node kvm-worker --storage-class local-test \
  --image registry.example.org/lab/microsandbox:0.7.8 \
  --output .local/microsandbox-install
kubectl apply --dry-run=server -f .local/microsandbox-install/install.json
kubectl apply -f .local/microsandbox-install/install.json
```

镜像构建包含固定 SDK、运行时和校验过的官方 `msb-metrics`。默认 guest 仅从 Microsandbox 本地缓存使用，不会自动联网拉取。先准备并导入：

```bash
docker pull --platform linux/amd64 python:3.12-slim
docker save -o /tmp/microsandbox-guest.tar python:3.12-slim
kubectl -n microsandbox-lab get pods
# Replace POD with the actual Pod name; kubectl cp does not accept deployment/name.
kubectl -n microsandbox-lab cp /tmp/microsandbox-guest.tar POD:/data/guest.tar
kubectl -n microsandbox-lab exec deploy/microsandbox-lab -- msb load --input /data/guest.tar --tag python-lab:local
kubectl -n microsandbox-lab exec deploy/microsandbox-lab -- msb doctor
kubectl -n microsandbox-lab port-forward svc/microsandbox-lab 18950:9118
```

打开 <http://127.0.0.1:18950/>，或请求 `POST /api/suite`。接口仅表示接受执行；持续读取 `GET /api/state`，确认每项断言结果。完整/磁盘快照准备成功后：

```bash
kubectl -n microsandbox-lab rollout restart deploy/microsandbox-lab
kubectl -n microsandbox-lab rollout status deploy/microsandbox-lab
# Reestablish port-forward in another terminal after the old Pod exits.
curl -X POST http://127.0.0.1:18950/api/restore
```

`POST /api/capture` 仅运行 Fork 和快照准备，用于修正调用方式后的独立 attempt；`POST /api/resource-run` 重复四 guest 的 90 秒 CPU 验证。重新执行完整套件前，使用新的 `--attempt`、渲染并更新部署，保留旧记录和归档；不要用同一编号覆盖结果。默认目录是 `/data`，运行时目录由 `MSB_HOME=/data/runtime` 指定。

监控接入可在渲染时传入 `--otel-endpoint`，使用完整 OTLP HTTP metrics URL。`monitoring.yaml` 和 `dashboard.py` 默认针对命名空间 `victoriametrics`、数据源 UID `VictoriaMetrics`，按实际监控环境调整后再应用；本示例不更新共享 Helm release，也不替换现有采集配置。

```bash
python3 examples/microsandbox-kubernetes/dashboard.py --output .local/microsandbox-dashboard.json
kubectl apply --dry-run=server -f examples/microsandbox-kubernetes/monitoring.yaml
kubectl apply -f examples/microsandbox-kubernetes/monitoring.yaml
kubectl apply -f .local/microsandbox-dashboard.json
```

官方 guest 指标通过 `msb-metrics` 导出；外层容器采样器只验证过本轮 cgroup v1 布局。工作台没有认证，仅在受控实验网和 localhost 转发下使用。每个 guest 都有最长运行期限，正常结束后停止并删除；PVC 保留镜像缓存、元数据、归档与证据。8 GiB 是本轮小实验容量，不是任意任务的存储建议。

公开数据中不包含内网地址、凭据和真实节点名。`monitoring-evidence.json` 含四 guest 计算窗口内的查询、两秒采样时间序列和峰值；CPU、guest used、host resident、配置 RAM、容器工作集口径互不替代。
