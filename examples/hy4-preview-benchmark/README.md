# Hy4-preview 双机 H20 实测材料

本目录包含已完成的 Hy4-preview BF16 双引擎实测所用的复现脚本和公开数据。

- [实测报告](../../docs/ai-k8s/practices/hy4-preview-hardware-benchmark-plan.md)：模型介绍、双机运行配置、性能和功能结果。
- `preflight.py`：权重与运行时检查。
- `smoke.py`：API、推理模式与工具调用验收。
- `cases.csv`、`benchmark.sh`：固定工作负载与压测客户端。
- `images/`：固定镜像版本及构建材料。
- `results/`：脱敏聚合数据、正确性与 RDMA 证据。

完整执行计划和绑定实际节点的清单仅保留在本地。公开报告中的结论限定在实际完成的配置与样例。
