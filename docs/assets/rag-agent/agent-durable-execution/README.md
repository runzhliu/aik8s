# Agent 中断续跑示意图

两张图片均为 1200×675、16:9 的确定性原理图，不是产品截图或性能数据。

| 文件 | 用途 | 内容来源 |
| --- | --- | --- |
| recovery-boundary.png | 解释已提交步骤、执行中操作和后续工作 | 正文的一小时任务假设；32、37 分钟仅是示意时间 |
| kubernetes-architecture.png | 解释持久执行组件与可替换 Worker 的职责 | 正文中的平台架构建议；仅展示部分依赖 |

字体、颜色和留白沿用仓库现有 GLM / MiniMax M3 图表系统，使用 Pillow 和字体边界计算。

生成源：`scripts/generate_agent_durable_execution_assets.py`。

```bash
python scripts/generate_agent_durable_execution_assets.py
```

图中不含公司环境信息、地址、凭据或实测性能数值。
