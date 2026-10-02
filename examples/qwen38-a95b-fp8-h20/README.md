# Qwen3.8-2.4T-A95B-FP8 H20 测试材料

本目录用于 `Qwen/Qwen3.8-2.4T-A95B-FP8` 在 4 台 8×141GB H20 上的部署预检、
SGLang/vLLM 正确性测试、公平压测和长上下文验证。

## 资源与路径

首轮固定使用 `TP8 × PP4`，总计 32 张 141GB H20。四台节点各自保存完整模型副本：

```text
host NVMe: <HOST_NVME_ROOT>/model-cache/Qwen3.8-2.4T-A95B-FP8/v1
container: /models-nvme/Qwen3.8-2.4T-A95B-FP8/v1
```

推理测试选择四台节点；扩展预热范围前先逐台评估 NVMe。可用空间不足 2.4 TB 的节点跳过，
并为运行时留出额外空间。本文校验的模型 Revision 为 `d2dc35658bcf77e66643428cb52e774cc3b5bd29`，
索引载荷为 `2,496,066,252,544` B；服务必须检查 NVMe 完成标记和版本身份，不得静默回退到共享存储。

## 文件

```text
nvme_probe.py  # 只读检查挂载背后的 NVMe 设备及可用空间
prewarm.py     # 增量复制稳定分片、每分钟复查 CFS、原子完成标记
preflight.py   # 零 GPU：配置、分片、Revision、运行时与 CLI 参数预检
smoke.py       # Reasoning、reasoning_effort、Tool Call、多轮与流式正确性
needle.py      # 32K/64K/128K/262K 及实验性 512K/1M 检索验证
cases.csv      # 公平性能与长上下文 Case
benchmark.sh   # 默认 dry-run；主对比统一使用 vllm bench serve
validate_benchmark_result.py # 校验全请求成功和强制输出长度
telemetry.py   # NVMe 留存功耗、显存、PCIe/NVLink/RDMA 原始计数
images/        # 固定上游 Manifest 与内网同步状态
```

## 预检

```bash
MODEL_PATH=/models-nvme/Qwen3.8-2.4T-A95B-FP8/v1 \
EXPECTED_REVISION=d2dc35658bcf77e66643428cb52e774cc3b5bd29 \
ENGINE=sglang \
python3 preflight.py
```

## 功能 Smoke

```bash
BASE_URL=http://127.0.0.1:30000/v1 \
MODEL=qwen38-a95b-fp8 \
python3 smoke.py
```

## 公平压测

默认只打印命令：

```bash
ENGINE=sglang STAGE=baseline bash benchmark.sh
```

确认服务上限、客户端和输出目录后执行：

```bash
ENGINE=sglang \
STAGE=baseline \
EXECUTE=1 \
BASE_URL=http://127.0.0.1:30000 \
TOKENIZER=/models-nvme/Qwen3.8-2.4T-A95B-FP8/v1 \
MODEL=qwen38-a95b-fp8 \
MAX_CONTEXT=32768 \
RUN_LABEL=h20-fp8-tp8-pp4-target \
bash benchmark.sh
```

SGLang 完成并释放 32 卡后，vLLM 使用同一客户端、Cases 和参数复跑。

`RESUME=1` 只跳过已通过完整性校验的结果；发现既有结果失败时停止，不覆盖原始证据。
Needle 按渲染后的 Chat Template 计算输入 Token，为输出预留空间，并精确核对返回代号。
功能 Smoke 可设置 `TRACE_FILE` 保存完整请求与响应，题目不包含预期算术答案。

OpenWebUI 可复用已有实例；先从前端 Pod 完成一次真实 API 请求，再追加模型连接。
已有模型连接必须保留。截图与实际对话导出一起存档，两套引擎分别验收。

## 增量预热

预热不申请 GPU，CFS 以只读方式挂载。分片须通过 Safetensors 头部、索引 tensor 名称与
文件完整长度检查，并在两次间隔至少 60 秒的观察中保持不变。临时文件跳过，后续落盘后自动补齐。
每次复制前后复查源文件状态，复制到本地临时文件后原子改名；只为小文件和分片头部计算 SHA256，
不对整套权重做全量哈希。该检查不等于权重内容的端到端哈希验证。

本地状态位于模型目录的 `.aik8s-prewarm/progress.json`，记录源端剩余分片、节点已完成分片、
当前文件复制字节数和剩余空间。全部 213 个分片、辅助文件、总 tensor payload 校验通过后，
才写入 `.aik8s-complete`。源端索引摘要作为当前快照标识；启动推理前仍需补齐上游 Revision 核验。

运行实例的节点清单、空间探针、Job 清单及控制器进度保留在本地 `results/`，不纳入公开材料。
可按共享存储与网络容量逐步提高并发和单节点限速。实际吞吐须以节点写入字节增量测量，
限速值不等于实际速度；若预热与压测共享主机 I/O，须记入测试条件。
通过挂载控制文件动态调整限速（0 表示不节流），无需重启复制进程。

复制每 64 MiB 执行落盘，并对源/目标已处理区域请求回收文件缓存，运行实例的内存上限为 2 GiB。
该设置用于处理大文件缓存计入容器内存导致的 OOM；节点完成状态仍以实际校验与完成标记为准。

成功的预热 Job 在完成证据归档后自动删除，以保持命名空间列表简洁；节点上的模型和
`.aik8s-complete` 不删除。已删除 Job 的完成状态从本地归档恢复，不能仅凭 Job 列表判断预热进度。

## 无人值守执行器

新的 `campaign.py` 在集群内的 CPU 容器运行，按相同四个节点串行执行两套引擎；
`node_worker.py` 接收有绝对期限的阶段命令，保存节点 NVMe 日志，并发布可查询的状态。
独立看护使用 Kubernetes API 心跳，不依赖控制器节点上的文件。每个 Pod 还设置运行期限。

`unattended.py` 是新流程的入口客户端，替代旧的 `benchmark.sh` 串行遇错即停行为：

- 模型 ID、确定性答案和完整 SSE 是性能测试的前置条件；reasoning、effort 和工具分别记录。
- 功能请求仅对指定临时错误有限重试；部分 SSE 不重试。正式失败轮不自动重跑、不覆盖。
- 连续三轮失败只停止当前阶段；高并发阶段检查前一并发档位的结果，其他独立阶段继续。
- 超时和服务进程退出会终止整个客户端子进程链。输出目录必须新建，结果不可原位覆盖。
- `strict_bench.py` 保留原生 vLLM 负载生成/调度，校验非空内容、结束标记、usage 与固定输出长度。
- `metrics.py` 输出客户端 TTFT、TPOT、完整流 E2E、成功输出吞吐和错误计数；预热与原生 CLI
  自检请求分开标记。`hardware_metrics.py` 输出 RDMA 原始计数，数据计数按每单位 4 字节换算。
- 最终状态分别列出功能、性能、长上下文、OpenWebUI、Grafana、回传、文章与 GPU 释放；
  控制器成功退出不等于所有项目通过。

`runtime_contract.py` 和 `protocol_fixture.py` 用于固定镜像内的零 GPU 请求协议及 CLI 验证。
`checkpoint_gate.py` 首次核对完整分片 SHA-256；只有上游 manifest 和各文件设备、inode、大小、
mtime、ctime 均未变化时，才复用节点上的完整校验收据。预检会核对实际挂载包中的每一个脚本哈希。

CPU 故障回归：

```bash
python3 -m unittest discover -s examples/qwen38-a95b-fp8-h20 -p test_unattended.py -v
```

具体节点、绝对运行期限、私有部署包和 Grafana/OpenWebUI 接入参数由本地运行材料管理，
不放入公开仓库。截图使用真实历史查询、绝对时间窗和浅色 1200×675 布局；无数据时记录失败，
不会生成替代的“监控截图”。
