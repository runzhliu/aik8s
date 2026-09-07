# MiniMax H3 部署与音视频测试材料

状态：测试完成。两套引擎分别完成 15 类配置，每套汇总 55 个有效正式样本；音频参考与接口错误传播问题已修复并通过对应 GPU 复测。通过标准是请求与媒体结构验收，语义质量边界见实测文档。见 [运行时修复记录](RUNTIME_FIXES.md)。

- [部署与压测计划](../../docs/ai-k8s/practices/minimax-h3-h20-deployment-benchmark-plan.md)
- [实际执行记录](../../docs/ai-k8s/practices/minimax-h3-h20-benchmark.md)
- `images/`：固定上游基础镜像和源码的离线构建文件；交付状态另见镜像记录。
- `launch.sh`：单节点 4×141GB H20-3e 实测启动命令，默认 dry-run；两引擎都只加载一个 DiT 分区。
- `render_deployment.py`：生成 ConfigMap、零副本 Deployment、Service 和可选 Ingress；仅输出 JSON，不访问集群。
- `cases.json`：中英文 T2VA、首尾帧与六组多模态参考请求；50 个采样点，5/10/15 秒。
- `benchmark.py`：同一计时与媒体校验逻辑；SGLang 异步 API 与 vLLM-Omni 同步 API 使用独立协议适配。
- `verify_model.py` / `copy_model.py`：源目标文件、分片头和元数据检查，复制到全新 NVMe 目录。
- `run_suite.py`：按固定顺序执行矩阵；第一个失败立即停止，支持显式恢复。
- `monitor_gpu.py`：逐秒采集 GPU 显存、利用率和功耗。
- `make_fixtures.py`：生成自有测试素材、媒体信息与 SHA-256 清单。
- `check_api_errors.py`：非法请求与终态检查；随后还需有效生成验证恢复。
- `apply_runtime_fixes.py` / `runtime-fixes.json`：显式启用、受源码哈希保护的参考音频上下文与 RPC 错误传播修复。
- `test_runtime_fixes.py`：在实际镜像中检查上下文生命周期和客户端/内部错误的区分。
- `studio.py` / `studio.html`：浅色生成、排队、播放和下载验收页面。
- `backup_media.py`：产物回传与 SHA-256 校验；支持仅传已完成样本和持续监视。
- `review_media.py`：从原始视频提取分帧图及音轨信号指标，原始文件不改写。
- `summarize_results.py`：汇总留存样本，排除预热，核对对齐帧数并生成去除内部标识的数据。
- `summarize_gpu.py`：将逐秒 NVML 记录与实际请求时间窗匹配，分别保留显存、功耗和采样覆盖信息。

```bash
ENGINE=sglang bash launch.sh
ENGINE=vllm-omni VARIANT=ref2va bash launch.sh
python3 benchmark.py --engine sglang --base-url http://127.0.0.1:8000
```

使用 NVMe 时，模型完成同步、宿主机 `findmnt`/`lsblk` 确认 NVMe、完成标记与 Revision 齐全后，才设置
`EXECUTE=1` 启动。正式 benchmark 需显式传 `--execute`，需要本机 `ffmpeg`、`ffprobe`。
先 `--case t2va-5s --concurrency 1 --repeats 3`，再依次扩大时长和并发。

vLLM-Omni 也支持直接从只读 CFS PVC 加载，无须复制到 NVMe。设置 `MODEL_STORAGE=cfs`、
`MODEL_PATH` 为容器内的 CFS 模型根目录，并通过 `MODEL_IDENTITY_FILE` 指向校验流程生成的
JSON 报告；启动器检查报告的 `status=PASS`、`model_path` 与 `source_snapshot_id`。
该模式默认传入 `--init-timeout 3600 --stage-init-timeout 3600`，避免网络存储加载尚未完成就触发
默认启动超时；可分别用 `H3_INIT_TIMEOUT`、`H3_STAGE_INIT_TIMEOUT` 调整。测试记录应注明
模型存储来源，分别统计启动耗时与服务就绪后的生成性能。生成产物仍保存到独立 hostPath。

NVMe 容器路径为 `/models-nvme/MiniMaxAI/MiniMax-H3`。必须提供完整官方根目录，不能把过去
ComfyUI 的 pruned INT4/INT8 单文件当作完整基线。首轮不下载 Turbo、FastH3 或外部评估模型。

`benchmark.py` 支持 T2VA 与 FL2VA/Ref2VA 的条件协议适配；两边都上传同一 Data URI
字节，并保留完整请求 JSON。部署必须把素材目录只读挂载到 `/fixtures`。
具体功能通过情况以实测记录为准；不得把 T2VA PASS 标为全多模态 PASS。
输出还记录实际解码帧数。批次吞吐包含客户端媒体验收的墙钟时间，不能当作纯服务端
吞吐；单请求 E2E 则在下载完成时停止计时，排除后续 ffprobe/ffmpeg 验收。
`rtf_video` 使用实际帧数除以 24 得到视频时长；旧字段 `rtf` 使用容器时长，
汇总器对所有历史样本统一重算视频 RTF，避免 AAC 封装尾部带来的小幅偏差。

部署清单生成时填写 `--engine`、`--image`（必须固定 Digest）、`--node`、`--nvme-path`、
`--output-host-path`，默认命名空间为 `aik8s-ms`，可选 `--ingress-host`。
容器 `/outputs` 使用独立持久化 hostPath，并作为工作目录；SGLang 显式保存到
`/outputs/server`。客户端也应把下载产物和检测 JSON 写入 `/outputs/client`。
生成器按分区设置内存：FL2VA request/limit 为 192/384 GiB，Ref2VA 为 768/768 GiB；仍需核对目标节点容量与实际加载峰值。
生成音视频、失败产物和原始日志均保留，每批传回本地后核对文件大小及 SHA-256。
缩容不删除 hostPath；切换引擎或分区时使用不同子目录，不覆盖旧结果。
TCP Ready 只说明端口监听，仍须通过完整生成 Gate。

本地路径必须保留可识别的 `MiniMaxAI/MiniMax-H3` 片段；启动器显式指定
`--model-type diffusion --backend sglang --model-id MiniMax-H3`，避免进入文本模型入口或
错误回退到 Diffusers。`preserve_outputs.py` 仅修改固定 SGLang 版本删除失败视频的动作，
保留原有校验与失败状态，并校验补丁前源码 SHA-256。运行脚本和日志随每次启动写入 hostPath。
