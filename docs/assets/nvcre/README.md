# NVCRE 原理图与独立 NCCL/DCGM 实测资料

本文结合 NVCRE v0.7.0 源码分析与两节点、16 张 H20-3e 的独立验机。实测使用普通 Kubernetes Job，未部署 NVCRE、Trainer 或 JobSet，也未执行 Certification。

| 文件 | 证据与制作方式 |
| --- | --- |
| `execution-chain.png` | NVCRE v0.7.0 执行、测量与结果关系，确定性原理图 |
| `production-lifecycle.png` | 验收接入节点上线、变更与复测的建议流程；非已执行的生产准入流程 |
| `validation-scope.png` | 逐步扩大验证范围的建议，非实验成绩 |
| `result-retention.png` | 测量冻结、Gauge 清理与报告留存，确定性原理图 |
| `roce-tcp-comparison.png` | 脱敏通信 CSV 的双机 AllReduce 数据；三轮中位数、对数坐标 |
| `gpu-nccl-observation.png` | 通信阶段真实 GPU 利用率面板，节点八卡平均 |
| `gpu-nccl-power.png` | 通信阶段真实功耗面板，节点最高卡 |
| `gpu-dcgm-observation.png` | 修复轮诊断期间的真实显存面板，节点最高卡 |
| `gpu-dcgm-temperature.png` | 修复轮诊断期间的真实温度面板，节点最高卡 |
| `nccl-results-dashboard.png` | 真实诊断结果表，保留首次失败、修复通过和超时 |
| `nccl-measurements.csv` | 30 轮有效通信测量 × 10 档消息，Out-of-place 原始读数；Node B 使用独立补测 attempt 2 |
| `experiment-summary.json` | 参数、重复结果、诊断状态、固定时间窗与采样口径 |
| `evidence/` | 五个已脱敏的原始面板截图，及标题、来源哈希、排版元数据 |

生成代码：

- 原理图与双封面：`scripts/generate_nvcre_article_assets.py`。
- 数据曲线与证据图排版：`scripts/generate_nvcre_benchmark_assets.py`。

正文图沿用 MiniMax M3 的 1200×675、Hiragino Sans GB / Helvetica Neue 与浅色布局。真实截图只裁切面板、等比缩放，并在图外添加说明；未修改曲线或数值。微信与公开文档使用同一份图。

指标来自独立实验 Prometheus/Grafana：Prometheus 抓取为 5 秒，既有 DCGM Exporter 自身刷新为 30 秒，采样峰值不等于短负载的瞬时峰值。通信结果指标由保存的 NCCL 输出导出，不是 NVCRE 的 `nvcre_*` 指标。

通信总执行尝试为 39 次：首次 30 次中的 Node B 九项因执行器准备问题未成功，另外独立补测九项；30 轮有效测量中错误均为零。原解析对 AllToAll 的 `N/A` 误判及一次终端输出截断，使用已保存节点文件修正，不额外执行覆盖原成绩。

诊断首轮因缺 CUDA 13 插件失败；补齐相同版本官方包后，两台 Level 1 各八张 GPU 的 Software 项通过。Level 2 两台在 730 秒超时收尾，未形成完整诊断成绩。原始诊断 JSON 含设备序列号，公开资料仅保留脱敏摘要。`status_field_counts` 包含 GPU 与 summary 的状态字段，不是测试项目数量。

图与数据不含内部集群名、IP、设备序列号、业务标识、凭据或私有镜像仓库。内部原始日志、部署包、计划和代码保持在本地忽略目录。
