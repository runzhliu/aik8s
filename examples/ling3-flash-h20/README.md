# Ling-3.0-flash H20 实测材料

这是 Ling-3.0-flash 在单台 4×141GB H20 上进行 SGLang/vLLM BF16 部署、功能验证、压测和 MTP A/B 的可执行材料。

## 已完成的实测

2026-09-03 已完成 SGLang 基线/NEXTN 与 vLLM 基线/MTP 四组正式测试：共 9,022 个成功
请求、0 失败；两个引擎的功能 Smoke 和 32K～256K Needle 正确性验证全部通过。

- 完整报告：`docs/ai-k8s/practices/ling3-flash-h20-deployment-benchmark-plan.md`
- 公开汇总：`results/2026-09-03-h20-bf16/`
- 图表重建：`make_report_charts.py`

## 模型输入

只需准备主模型：

```text
Hugging Face: inclusionAI/Ling-3.0-flash
```

主 Checkpoint 自带 MTP 层，不需要为了 SGLang NEXTN 或 vLLM MTP 再下载一个模型。
`Ling-3.0-flash-fp8` 和 `Ling-3.0-flash-dspark` 是后续可选项。

权重既可以从共享只读存储直接加载，也可以为缩短启动时间预热到宿主机 NVMe；本轮正式测试
选择前者，启动耗时不纳入引擎性能排名。

## 公开目录

- `results/2026-09-03-h20-bf16/`：经过脱敏的正式汇总与正确性证据；
- `make_report_charts.py`：从公开结果确定性重建报告图表；
- `docs/ai-k8s/practices/ling3-flash-h20-deployment-benchmark-plan.md`：完整中文报告。

本地工作目录另有部署清单、内部镜像记录、Case 定义和执行脚本；它们包含具体集群、Registry、
节点或存储信息，不进入公开仓库。公开数据足以核对报告结论并重建图表，但不对外提供可直接作用于
内部环境的部署材料。

## 关键约束

- 基线默认关闭 speculative decoding；
- SGLang 和 vLLM 使用相同客户端、Case、种子和重复次数；
- Prefix Cache 可以开启，但每轮正式测试前必须验证清空成功；
- 压测结果写到 HostPath 或 EmptyDir，测试结束后再复制回本地，不写共享存储；
- 单节点 TP4 不声称使用跨节点 RDMA；
- Ling-3.0-flash 是文本模型，OpenWebUI 只测文字、thinking 和工具调用；
- 测试完成、证据保存后缩容服务和 Job。
