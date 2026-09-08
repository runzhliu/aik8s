# MiniMax-M3 / H20：镜像与测试准备

两套引擎已在同一台八卡 H20-3e 上串行完成 BF16 TP8、32K/C32 主矩阵：各 33 轮、3,954 请求，合计 66 轮、7,908 请求且无请求失败；各 12 项基础功能通过。扩展测试保留纯色图片、特定数学提示词和原始检索的失败，以及独立复测；SGLang 损坏媒体返回 500 的问题尚未修复。vLLM 额外观察已按要求结束，保留约 30 分钟、903 请求、零失败的数据，不与 SGLang 比较。

- [实测报告](../../docs/ai-k8s/practices/minimax-m3-h20-benchmark.md)
- [镜像记录](images/README.md) / [不可变镜像清单](images/images.lock.json)
- `launch.sh`：BF16 TP8、32K 启动参数，默认只打印；实际参数须在固定镜像内通过 CLI 检查。
- `benchmark.sh`、`cases.csv`：同一 vLLM 客户端、11 个主 Case、每个 3 轮；默认只打印。
- `bench_client.py`：给固定版本的 vLLM HTTP 压测客户端显式选择 CPU 平台，避免无 GPU 时全局 CLI 初始化失败；不用于启动推理服务。
- `smoke.py`：12 项真实 API 验收，包含图片与视频理解，保存输入、输出与素材散列。
- `campaign.py`：CPU 客户端等待 API、验收功能并执行主矩阵；支持持久化暂停标记、单轮超时和完整结果复核。
- `multimodal_bench.py`：纯色原始输入与带边框输入分别计量，保留预热失败，避免将错误回答算入有效吞吐。
- `extended.py`、`needle_retest.py`：工具、代码、推理模式、错误恢复及约 31K 输入检索；显式字段提取是独立提示词复测，不覆盖原始结果。
- `stability.py`：可选混合负载观察工具；本轮 vLLM 观察已提前结束，SGLang 不执行此项。
- `summarize.py`、`runtime_summary.py`：校验完整矩阵，导出脱敏指标与采样遥测。
- `validate_result.py`：拒绝缺失请求、失败请求或不足目标长度的结果。
- `images/verify_runtime.py`：镜像内零 GPU 版本、依赖、模型源码与 CLI 检查；不能代替 GPU 实测。
- `private/`、`results/`、`k8s/`：本地私有执行材料，Git 忽略。

## 资源

一台独占 8×H20-3e（141GB/卡）作为 BF16 TP8 起点，两套引擎串行复用。
长上下文/高并发预留双机扩展，但不能保证单机 1M 窗口或双机任意并发。
实际测试命名空间固定 `aik8s-ms`，复用既有 OpenWebUI 并经 gmanctl 注册。

## 预览命令

```bash
ENGINE=sglang MODEL_PATH=/models/MiniMax-M3/v1 bash launch.sh
ENGINE=vllm MODEL_PATH=/models/MiniMax-M3/v1 bash launch.sh
ENGINE=sglang STAGE=baseline TOKENIZER=/models/MiniMax-M3/v1 bash benchmark.sh
```

两个脚本仅在 `EXECUTE=1` 时执行；这只是本地误操作保护，不是额外的用户审批要求。
在实际 GPU 测试获准恢复、资源/权重/镜像/CLI Gate 均通过之后执行。
不要通过运行本目录命令恢复已暂停的 Qwen 任务。

公开文件包含通用配置、源与修复后镜像 digest、脱敏 CPU 检查结果和修复过程；内网镜像路径与完整执行记录放 private/。

## 控制器回归

```bash
python3 -m unittest discover -s examples/minimax-m3-h20 -p test_campaign.py
```

覆盖服务未就绪、客户端失败、半写 JSON、有效结果续跑、暂停及子进程终止，以及等待期间 ConfigMap 版本目录被回收的场景；不申请 GPU。
