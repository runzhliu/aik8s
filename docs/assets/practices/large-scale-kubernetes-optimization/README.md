# 万节点 Kubernetes 集群优化配图

这些配图由 `scripts/generate_large_scale_kubernetes_optimization_assets.py` 确定性生成，统一为 1200×675、16:9 浅色横图：

- `control-plane-pressure.png`：控制面压力模型。图中的 1000 次 Lease 更新/秒为 10000 节点按默认 10 秒续租间隔计算的算术值，不是压测结果。
- `ten-thousand-node-choice.png`：多集群、托管超大规模和定制单一集群的决策边界。
- `etcd-optimization-loop.png`：etcd 减负、资源隔离、维护、恢复和分片的执行顺序。

图中机制参考 Kubernetes 与 etcd 官方文档，企业案例和适用边界在正文中逐项引用。图片不包含生产环境地址、账号或内部配置。
