# Kubernetes 流控配置示例

配套公开文档：`docs/ai-k8s/cluster/flow-control.md`。

`apf-batch-reader.yaml` 使用 Kubernetes 1.29 起稳定的 `flowcontrol.apiserver.k8s.io/v1`，将 `apf-demo/batch-reader` 对 `apf-demo` 中 Pod 的 GET/LIST 请求归入独立类别。

- Namespace、专用 ServiceAccount 和相应 RBAC 权限需要事先准备；此文件不授予权限。
- 分类不覆盖跨 Namespace LIST、WATCH 或其他资源。
- `matchingPrecedence` 要与已有规则比较，较小值先匹配。
- 5 是名义份额，不是 5 QPS 或固定 5 个并发。队列参数不是推荐容量。
- 这是教学示例，不是集群已应用策略或压测结果。

在选定目标环境并具备管理权限后，可先执行服务端 dry-run：

```bash
kubectl --context <target-context> apply --dry-run=server \
  -f examples/kubernetes-flow-control/apf-batch-reader.yaml
```

正式启用后应检查分类响应头、排队/拒绝指标及对系统请求的影响。对象存在或 dry-run 成功，不能证明请求匹配与性能符合预期。
