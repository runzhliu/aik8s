# Kimi K3：双机 16×H20 SGLang 与 vLLM 实测

测试于 2026-09-01 至 2026-09-02 完成。两套引擎使用同一份 NVMe 模型、同两台
8×141GB H20、同一个固定版本的 Python `vllm bench serve` 客户端、相同随机请求集合、
并发、输出长度与重复次数。每个引擎执行 2,398 个 benchmark 请求，共 4,796 个，失败数为 0。

原始 JSON 保存在测试节点 NVMe：

```text
/apps/dat/model-cache/aik8s-results/kimi-k3-20260901/sglang-tp16-ep16
/apps/dat/model-cache/aik8s-results/kimi-k3-20260901/vllm-tp16
```

## 环境

| 项目 | SGLang | vLLM |
| --- | --- | --- |
| GPU | 2 节点 × 8×141GB H20 | 相同节点 |
| 并行 | TP16 / EP16 | TP16 |
| 版本 | 0.5.16 | 0.1.dev19262+gb6bbf29dd.d20260727 |
| 模型路径 | `/models-nvme/Kimi-K3/v1` | 相同路径 |
| 最大上下文 | 32,768 | 32,768 |
| Benchmark Job | 约 101 分钟 | 104 分钟 |
| 跨节点通信 | NCCL `NET/IB`，8 个 `mlx5_bond_*`，RoCE GID 3 | 相同 |

部署前的 16 GPU NCCL AllReduce 预检通过。两个运行时日志都确认使用 `NET/IB`，没有
回退到 Socket。SGLang 每 rank 模型内存约 102.75GB，BF16 KV Cache 共 567,296 Token；
vLLM 每 rank 模型占用约 129.75GiB，KV Cache 60,013 Token。

## 公平压测结果

下表为重复轮次的中位数。吞吐单位为 tok/s，TTFT/TPOT 单位为 ms。

| Case | SGLang 输出吞吐 | vLLM 输出吞吐 | SGLang P50 TTFT | vLLM P50 TTFT | SGLang P50 TPOT | vLLM P50 TPOT |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 128→64 C1 | 32.99 | 32.61 | 267.65 | 255.10 | 26.49 | 27.05 |
| 128→64 C4 | 104.59 | 104.03 | 432.59 | 383.37 | 31.84 | 32.77 |
| 128→64 C8 | 168.88 | 170.84 | 633.56 | 610.59 | 37.80 | 38.19 |
| 128→64 C16 | 259.01 | 263.78 | 1,020.97 | 1,072.33 | 46.49 | 45.31 |
| 4K→128 C4 | 49.66 | 51.98 | 6,145.30 | 4,427.18 | 34.33 | 42.74 |
| 4K→128 C8 | 59.23 | 62.95 | 10,431.93 | 5,843.45 | 55.49 | 82.73 |
| 16K→256 C4 | 30.45 | 29.69 | 18,280.37 | 13,397.18 | 60.30 | 71.34 |
| 16K→256 C8 | 33.78 | 29.71 | 30,912.37 | 51,334.99 | 116.45 | 71.35 |
| 128→1K C1 | 37.32 | 36.69 | 270.83 | 257.69 | 26.55 | 27.02 |
| 128→1K C8 | 203.37 | 208.23 | 638.03 | 618.95 | 38.75 | 38.01 |
| 32K total C1 | 7.75 | 8.22 | 12,817.21 | 12,015.95 | 27.57 | 28.05 |

32K 使用 32,640 输入 + 128 输出，每个引擎 2 轮、每轮 3 请求，全部成功。64K 与 128K
没有伪装成成功：当前服务 `max_model_len=32768`，脚本明确记录 `SKIP_UNSUPPORTED`。

## 功能与兼容性

- 两个引擎都通过模型列表、确定性数学、多轮记忆、结构化工具调用、流式输出和真实图片理解；
- SGLang 返回 `reasoning_content`，vLLM Rust frontend 返回 `reasoning`；测试器同时识别并记录；
- SGLang 对损坏图片返回 4xx；vLLM Rust frontend 返回 500，记为健壮性 warning；
- vLLM `--gpu-memory-utilization 0.90` 在权重加载后因无可用 KV block 失败，调整到官方 Hopper
  配方使用的 `0.97` 后成功；
- vLLM Rust frontend 不提供 SGLang 的 `/flush_cache`，vLLM 压测禁用该调用，并通过不同固定
  随机种子避免重复轮次共享前缀；SGLang 保持原生 cache flush；
- vLLM 的 60K Token KV Cache 在 16K C8 出现明显排队：P50 TTFT 51.33 秒；SGLang 更大的
  KV Cache 在相同 case 为 30.91 秒，且输出吞吐也更高；
- 4K C4/C8 与 32K C1 的预填充延迟则是 vLLM 更低，短请求与长输出两者基本同档。

## OpenWebUI 证据

两套后端都通过同一稳定模型入口注册到 OpenWebUI，并在强制浅色模式下上传真实 PNG 验证
视觉能力。截图不包含节点 IP、集群地址或宿主机路径。

- [SGLang OpenWebUI 视觉实测](../../../../docs/assets/practices/kimi-k3-h20/openwebui-sglang-light.png)
- [vLLM OpenWebUI 视觉实测](../../../../docs/assets/practices/kimi-k3-h20/openwebui-vllm-light.png)

## 结论

在本次 16×H20 MXFP4 配置上，两者都能稳定提供 Kimi K3 文本、工具调用和图像能力。
短请求与 1K 持续解码的差距很小；vLLM 在 4K 和 32K 单请求预填充更快，SGLang 在 16K C8
高并发长上下文更占优。生产选型不能只看一个总吞吐数字：普通交互/RAG 可优先比较 vLLM，
高并发长上下文应优先验证 SGLang，同时需要为 vLLM 增加损坏图片 500 的网关保护。

测试结束后，SGLang 与 vLLM head/worker Deployment 均已缩容到 0，GPU Pod 已删除。
