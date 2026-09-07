# MiniMax H3 运行时修复与复测

修复标识：`h3-20260906-audio-context-rpc-errors-v1`。这是本次实验的源码补丁，不能当作未修改的上游镜像结果。

## SGLang：参考音频编码缺少前向上下文

固定源码 `71de97b264b04dcd514cf904003028aefe9775c8` 的
`MiniMaxH3AudioEncodingStage.forward()` 直接进入参考音频编码。
`reference_encoding.py` 调用音频 VAE 的 `pre_block`，其注意力层执行
`get_forward_context()` 时断言失败。有声参考视频、独立参考音频会进入这条路径；
无声视频使用零长度音频条件，因此先前的无声视频测试通过。

修复在音频编码阶段设置 `current_timestep=0`、`attn_metadata=None` 和当前请求，
退出时恢复先前上下文。原有临时输入清理的 `finally` 保持生效。
这与同版本文本编码、VAE 解码使用显式前向上下文的方式一致。
[上游同类问题记录](https://github.com/sgl-project/sglang/issues/35447)也包含同一调用链。

## vLLM-Omni：异步 RPC 丢失客户端错误元数据

固定源码 `48298030d4b3c320b858dd98934c01babdd320ce` 的模型校验已经抛出
`OmniClientError(status_code=400)`。但 `WorkerProc._worker_busy_loop()` 发送的
`AsyncDiffusionOutput` 只携带错误文字，结果泵将其还原成 `RuntimeError`；
执行器再次用 `DiffusionOutput(error=str(exc))` 包装，最终同步视频接口返回 500。

修复同时覆盖这三处信息丢失：

1. 异步结果信封增加可选 `error_status_code`、`error_type`，工作进程从原异常填入。
2. 结果泵仅在状态码为 4xx 时还原 `OmniClientError`；内部运行错误仍是 `RuntimeError`。
3. 执行器使用已有 `DiffusionOutput.from_exception()` 保留元数据。

模型的时长、提示词和参考素材校验未被放宽，接口仍须返回正确错误状态。
本补丁针对本次使用的异步请求 RPC 路径；不宣称已覆盖所有分布式拓扑和同步 RPC 路径。

## 应用与证据

`runtime-fixes.json` 包含每个文件的修复前后 SHA-256 和精确替换内容。
`apply_runtime_fixes.py` 先验证全部文件，再保存原文件并应用；陌生版本拒绝修改。
运行时在 ConfigMap 中提供这两个文件，并设置 `H3_RUNTIME_FIXES=1`。
`launch.sh` 在启动引擎前应用补丁，将原源码和 `applied.json` 写入持久化的
`/outputs/runtime/<启动标识>/fix-evidence/`。

```bash
python3 /h3-launch/test_runtime_fixes.py --engine sglang
python3 /h3-launch/test_runtime_fixes.py --engine vllm-omni
```

CPU 回归测试在实际固定镜像内运行，不加载模型权重：

- SGLang：正常/异常路径的上下文、请求绑定、异常透传、清理和外层上下文恢复通过。
- vLLM：实际工作进程循环 → 序列化信封 → 结果泵 → DiffusionOutput 的 400/413 传播通过；内部错误未误判为客户端错误。

## GPU 复测范围

修复运行使用独立的 `*-repair-v1` 输出目录，保留原失败阶段。
两个引擎各使用四张 H20-3e，原始权重、50 个采样点、输入素材与种子不变。

- SGLang：从有声视频参考配置开始，执行预热和三次正式请求，再执行图像加音频、混合参考配置。
- vLLM：先执行四类非法请求和一次正常生成恢复；通过后重跑 2/4 并发、首帧/尾帧/首尾帧，再执行完整 Ref2VA 矩阵。
- 预检恢复请求与正式性能样本分目录，不能混入性能统计。
- 修复运行、原始运行和同机负载时段分别标识；不将重复运行混成一个总体中位数。

单元测试通过不等于 GPU 全部验收通过；最终通过情况以留存的请求结果、媒体检查、套件状态和归档哈希为准。

GPU 复测已完成：SGLang 有声视频、图片加音频和混合参考各 3 次正式请求通过；vLLM 的四类非法请求均返回 400，正常生成恢复、并发 2/4、三组首尾帧和六组参考素材测试通过。版本、硬件和运行时段的差异见[实测文档](../../docs/ai-k8s/practices/minimax-h3-h20-benchmark.md)，不能混作未修改上游的同条件速度排名。
