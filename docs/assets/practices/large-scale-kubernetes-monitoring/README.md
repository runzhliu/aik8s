# 配图计划与来源

使用项目既有的 MiniMax M3 图表字体、蓝橙配色与 1200×675 画幅。生成源码：`scripts/generate_large_scale_kubernetes_visuals.py`。

| 图片 | 用途 | 来源与性质 |
| --- | --- | --- |
| local-and-central.png | 解释本地告警与中心存储的职责 | 作者设计的概念架构，依据 Prometheus Agent、Remote Write 与 vmagent 文档；非实验拓扑截图 |
| selection-path.png | 对比四种选型需求 | 正文方案比较的视觉索引；非性能排名 |
| resource-count-evidence.png | 验证部署后的查询与对象趋势 | 实际 Grafana Kubernetes Views Global 看板节选，Kubernetes 1.30.4、12 节点、30 秒采集 |

截图只保留对象数量面板，未修改曲线和数字；裁掉内部标识及口径尚未对齐的容量面板。原始截图和环境配置不提交公开仓库。`visual-manifest.json` 记录输出尺寸、哈希、裁剪范围与原截图哈希，不包含内部路径。

生成方法：

```bash
.venv/wechat/bin/python scripts/generate_large_scale_kubernetes_visuals.py \
  --grafana-screenshot /path/to/private/global-dashboard.png
```
