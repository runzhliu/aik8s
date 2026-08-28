# Results

这里保存已经脱敏、可公开复算的 GLM-5.3-Flash 实测结果：

- `h20-fp8-summary-20260828.json`：模型、环境、Runtime、正确性、长上下文、缓存和聚合指标；
- `h20-fp8-benchmark-runs-20260828.csv`：短请求、4K Prefill、1K Decode 和长上下文的逐轮指标。

结果记录包含：

- 模型架构、权重分片与 Index 总字节数；
- 镜像的 linux/amd64 Digest，而不是只有可变 Tag；
- GPU 型号、数量与驱动版本；
- 完整启动参数、MTP 是否开启、KV Cache Dtype；
- 每个公开 Case 的逐轮指标，以及结果解释所需的启动日志摘要。

服务端生成的原始 JSON 还带随机输出文本、完整运行参数和环境标识，因此不原样提交；
CSV 保留了本文计算中位数和波动范围所需的逐轮数值。使用上级目录中的脚本可以重新生成
原始结果。
