# 配图计划与来源

| 图片 | 用途 | 证据与性质 |
| --- | --- | --- |
| scheduling-path.png | 区分排队、串行决策、可并发绑定与节点执行 | Kubernetes Scheduling Framework；简化流程，省略部分扩展点，非性能图 |
| search-and-quality.png | 解释可行节点阈值与稀疏候选 | Kubernetes Scheduler Performance Tuning；10000 / 1000 / 30 是正文的假设示例 |

采用 MiniMax M3 的字体与蓝橙配色，1200×675。源码为 `scripts/generate_large_scale_kubernetes_visuals.py`，图像哈希记录在相邻监控主题的 `visual-manifest.json` 中。

参考：

- [Scheduling Framework](https://v1-34.docs.kubernetes.io/docs/concepts/scheduling-eviction/scheduling-framework/)
- [Scheduler Performance Tuning](https://kubernetes.io/docs/concepts/scheduling-eviction/scheduler-perf-tuning/)
