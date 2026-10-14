# Agent 中断续跑的本地实验

验证两个边界：已提交的图节点不需要重跑；外部效果已经发生而图结果未保存时，恢复可能再次调用工具。

使用 LangGraph、SQLite Checkpointer 和另一份 SQLite 模拟工具服务。没有大模型请求、外部 API、公司集群或凭据。强制终止使用 `os._exit(86)`，由新进程恢复原 Thread。

从仓库根目录执行：

```bash
uv run --python 3.12 \
  --with-requirements examples/agent-durable-resume/requirements.txt \
  python examples/agent-durable-resume/verify.py
```

验证程序使用独立临时目录，结束后自动清理；输出包含中断现场、恢复日志和断言结果。

## 分步观察

```bash
TASK_DATA_DIR="$(mktemp -d)"

# 预期退出码 86；模拟工具已经写入，但图节点尚未返回。
uv run --python 3.12 \
  --with-requirements examples/agent-durable-resume/requirements.txt \
  python examples/agent-durable-resume/demo.py start \
  --data-dir "$TASK_DATA_DIR" --crash-at after-effect

uv run --python 3.12 \
  --with-requirements examples/agent-durable-resume/requirements.txt \
  python examples/agent-durable-resume/demo.py inspect --data-dir "$TASK_DATA_DIR"

uv run --python 3.12 \
  --with-requirements examples/agent-durable-resume/requirements.txt \
  python examples/agent-durable-resume/demo.py resume --data-dir "$TASK_DATA_DIR"
```

流程为 `plan → write_draft → finish`。检查点和模拟工具结果分别位于 `checkpoints.sqlite` 与 `tool-service.sqlite`。

`start` 拒绝重新启动已有 Run。`resume` 使用同一个 `thread_id` 和 `graph.invoke(None, ...)`；已结束的 Run 再次恢复不会重跑节点。示例只允许一次串行实验；修改 `--run-id` 时也应使用新的数据目录，因为展示的执行次数是整个模拟服务的累计值。

## 已验证结果

2026-10-14，Python 3.12，LangGraph 1.2.15、langgraph-checkpoint 4.3.0、SQLite Checkpointer 3.1.2，`durability="sync"`。

| 中断位置 | 中断时结果数 | 最终节点执行次数 | 最终工具结果数 |
| --- | --- | --- | --- |
| 工具写入前 | 0 | plan 1 / write_draft 2 / finish 1 | 1 |
| 工具写入后、图结果保存前 | 1 | plan 1 / write_draft 2 / finish 1 | 1 |

原始结构化结果见 [results.json](results.json)。

模拟服务在一个 SQLite 事务内登记动作键、请求哈希和结果，重复请求返回相同回执。真实远端系统需要提供幂等接口或可核实的业务回执；在 Agent 本地记一条“已调用”不能替代这个保证。

这是短时间、单机、确定性故障实验，覆盖实际进程终止与重新执行；没有验证一小时运行、多 Worker、节点故障、真实模型调用、生产数据库或真实工单服务。

公开综述：[Agent 长任务中断续跑原理与社区实践](https://aik8s.run/ai-k8s/rag-agent/agent-long-running-durable-execution/)。
