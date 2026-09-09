# Kubernetes 流控配图

三张图均为机制说明或明确假设下的算例，不是集群截图或压测结果。采用 MiniMax M3 的浅色版式、冬青黑体中文、Helvetica Neue 英文/数字及关键数字粗体。

| 图片 | 用途 | 依据 |
| --- | --- | --- |
| `01-three-layers.png` | 区分 API、任务和推理请求的治理位置 | Kubernetes APF、Kueue/Volcano、Envoy Gateway 官方文档 |
| `02-apf-request-path.png` | 解释分类、并发预算和排队/拒绝 | APF 与 flowcontrol v1 API 定义 |
| `03-rate-and-concurrency.png` | 解释 RPS 与在途并发的关系 | 稳态关系 N=λW；假设 20 req/s，平均耗时 0.2、2、10 秒 |

桌面版尺寸为 1200×675；同名 `-mobile.png` 为独立重排的 720×1080 手机版，通过正文的 picture 元素在窄屏切换，避免将多列图直接缩小。图中文字和数字均由代码生成，不使用生成式图片绘制技术信息。

复现命令（在仓库根目录）：

```bash
.venv/wechat/bin/python scripts/generate_kubernetes_flow_control_visuals.py
```

源代码：`scripts/generate_kubernetes_flow_control_visuals.py`。依赖 Pillow 和脚本中声明的中文、英文字体。发布前检查原图、手机宽度下的展示和文字边界；颜色在本组图中表示流程/强调，不代表推理引擎性能。
