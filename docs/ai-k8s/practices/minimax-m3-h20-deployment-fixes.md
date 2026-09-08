---
title: MiniMax-M3 H20 部署故障与修复记录
description: MiniMax-M3 实测中的镜像依赖、模型启动、客户端路径故障与异常输入处理记录。
---

# MiniMax-M3 H20 部署故障与修复记录

MiniMax-M3 是支持文本、图片、视频输入的 MoE 模型。本次以单机八卡 H20-3e、BF16 TP8、32K 窗口完成 SGLang 和 vLLM 实测。本文记录实际遇到的问题、已经验证的修复及仍未解决的边界；完整性能和功能结果见[实测报告](minimax-m3-h20-benchmark.md)。

## 镜像准备中的问题、修复与验证

以下来自本次镜像准备的实际检查。依赖检查、模块入口、CLI 和编解码分别验收，避免仅凭镜像构建成功就进入占卡测试。可复用实现见 [镜像目录](https://github.com/runzhliu/aik8s/tree/main/examples/minimax-m3-h20/images)，精简证据见 [CPU 检查记录](https://github.com/runzhliu/aik8s/blob/main/examples/minimax-m3-h20/images/cpu-verification-summary.json)。完整原始日志另行归档。

### 1. SGLang：先明确 CUDA 12 与 CUDA 13 的区别

最初按 SGLang 官方 Hopper 配方检查 CUDA 12.9 镜像。CLI 可以输出帮助，但 `pip check` 返回 1，发现七项依赖问题，包括缺少 `nixl-cu13`、CUDA Python 版本低于 SGLang 声明要求、CUDA pathfinder 版本过低，以及 NumPy、Pillow、setuptools 版本冲突。因此，CLI 能运行并不能证明环境依赖完整。

中转下载该镜像的大层时又出现重试。随后找到同一 SGLang Commit `56e290315b8fdb4c8c10f8e31360d9bc3d878633` 的官方 CUDA 13 构建及已有仓库副本，转为验证这条路线。CUDA 12 镜像保留为排查记录，没有作为修复成功的镜像交付。

不能只凭标签相同信任已有副本。本次核对其 config digest 与官方一致，并在实际拉取后逐项核对 **63 个解压后层的 diffID 全部一致**。压缩层 digest 不同，说明压缩表示不同，不能描述为所有 blob 完全相同。验证内容身份后，才将这份副本用作构建基础；公开 Dockerfile 默认仍固定官方 amd64 digest。

CUDA 13 构建的 Torch 架构清单包含 `sm_90`，这是后续 Hopper 验证的一个前提。它不证明 M3 专用 Kernel、NCCL 或 H20 服务已经运行成功；官方 CUDA 12 Hopper 配方与本次 CUDA 13 候选的差异需在 GPU 阶段继续验收。

### 2. SGLang：NIXL 不能靠卸载入口来修依赖

CUDA 13 原镜像剩余两项报错：

```text
nixl 1.2.0 requires nixl-cu12, which is not installed.
moviepy 2.2.1 has requirement pillow<12.0,>=9.2.0, but you have pillow 12.2.0.
```

第一次尝试把 `nixl` 当作可移除的依赖元包：卸载后 `pip check` 通过，但补充的 `find_spec('nixl')` 入口断言失败，构建被拦截，没有发布。检查安装文件发现，`nixl` 实际包含 `nixl/__init__.py`、`nixl/_api.py` 等 Python 入口，不能只看依赖检查结果就删除。

最终方案保留 `nixl==1.2.0` 和已有 `nixl-cu13==1.2.0`，补装其声明要求的 `nixl-cu12==1.2.0`，并将 Pillow 固定为 `11.3.0`：

```bash
python3 -m pip install --no-cache-dir nixl-cu12==1.2.0 pillow==11.3.0
python3 -m pip check
python3 -c "import importlib.util as u; assert u.find_spec('nixl') is not None"
```

为什么 CUDA 13 镜像里仍有 CUDA 12 的 NIXL 包？实际检查的 NIXL 1.2.0 依赖声明包含两个后端包，它们使用独立的 `nixl_cu12`、`nixl_cu13` 命名空间；前端根据 `torch.version.cuda` 选择后端。本镜像 Torch 为 CUDA 13，因此该选择逻辑指向 `nixl_cu13`。这里验证了依赖闭合和入口保留，尚未运行 NIXL GPU 数据传输。

修复后 `pip check` 输出 `No broken requirements found.`，SGLang CLI 和 PyAV 编解码检查通过。最终方案没有沿用早期 CUDA 12 尝试中的 CUDA Python 降级或 NIXL 卸载操作。

### 3. vLLM：清理无关系统依赖，补齐视频解码器

vLLM 原镜像的依赖检查发现 `pygobject 3.42.1` 缺少 `pycairo`。定位到镜像中的系统 GI 和软件源管理工具依赖后，修复层移除 `python3-gi`、`python3-software-properties`、`software-properties-common` 三个不参与本次模型服务的系统包，没有执行全局 `autoremove`。

另一个检查结果是原镜像未安装 PyAV/Decord。不能据此直接判定模型不支持视频，但为后续视频测试补装固定的 `av==16.1.0`：

```bash
apt-get remove -y python3-gi python3-software-properties software-properties-common
python3 -m pip install --no-cache-dir av==16.1.0
python3 -m pip check
```

修复后依赖检查通过。视频探针在内存中生成 8 帧、64×64 的 MPEG-4 样本，编码为 MP4，再用 PyAV 解码并断言帧数和宽度，得到 `AV_ROUNDTRIP_PASS 8`。它验证的是基础编解码链路；真实视频请求的帧采样、Processor、视觉编码器和回答正确性仍属于后续模型测试。

### 4. vLLM：区分 CPU 客户端与 GPU 服务初始化

零 GPU 容器执行原始 `vllm serve --help=all` 时出现 `Failed to infer device type`。该固定版本的全局 CLI 在构造命令参数时会初始化设备相关默认值，连只发送 HTTP 请求的压测客户端入口也受到影响。

处理方式分为两处：镜像探针保留原始失败，再显式选用 `CpuPlatform` 检查参数解析；独立的 [bench_client.py](https://github.com/runzhliu/aik8s/blob/main/examples/minimax-m3-h20/bench_client.py) 只给 HTTP 压测客户端选择 CPU 平台。**实际推理服务启动脚本没有强制使用 CPU 平台。** 这段客户端适配使用固定版本的内部接口，升级 vLLM 时须重新验证。

显式 CPU 参数解析和压测 CLI 参数检查均通过，原始 GPU 自动探测错误仍保存在报告里。该阶段状态标记为 `CPU_PASS_GPU_CLI_DEFERRED`，只说明 CPU 检查完成；后续 GPU 模型功能与正式主矩阵已通过，见实测报告。

### 5. 构建和镜像中转：验收到最终拉取端

构建还遇到 PyPI 下载及额外 Dockerfile frontend 拉取停滞。依赖下载改用可配置的 `PIP_INDEX_URL`，直接修复的依赖保留精确版本；简单的 ARG/FROM/RUN 构建去掉非必要的外部 frontend 指令，使用内置 frontend。重新构建检查退出码，失败尝试的日志保留，新镜像记录独立 digest，不覆盖已有验收结论。

本机推送曾返回 `unauthorized`，随后切换到已有授权的中转机推送通道。凭据通过既有凭据文件提供，不放入公开命令或 Dockerfile。跨仓库复制先确认暂存镜像，再检查生产同步和目标云端复制各自的最终状态；`queued` 只代表提交成功。

最终在目标集群用修复后的镜像执行零 GPU Pod，核对实际 `imageID` 和探针结果后归档、清理。镜像构建、复制、CPU 检查的证据均不代替权重加载与 GPU 功能验收。最终版本和各检查状态以 [镜像清单](https://github.com/runzhliu/aik8s/blob/main/examples/minimax-m3-h20/images/images.lock.json) 为准。

### 6. CFS 挂载失败与节点选择

模型清点 Pod 最初被调度到 CPU 节点，出现 `MountVolume.MountDevice failed`，CSI 返回 `node has not turbo kernel mod`。这是节点缺少 CFS Turbo 所需内核模块，不能解释成模型目录不存在或权重损坏。

修复时保留同一只读 PVC，将清点 Pod 重新调度到已具备该挂载能力的目标 GPU 资源池节点，并设置明确的节点选择与对应污点容忍。重新挂载后可以读取模型目录。未修改模型文件、PVC 或宿主机内核。后续 CPU 检查客户端同样需要确认节点存储能力，不能只看是否申请 GPU。

节点选择属于 Pod 不可变字段。重建时须先确认旧 Pod 已实际删除，再提交新清单；删除请求刚返回时对象可能仍在 Terminating，立即 apply 会被当作非法更新。

### 7. Pod 抢占策略的准入约束

初次 GPU 预检显式设置 `preemptionPolicy: Never`，但未指定匹配的 PriorityClass。集群准入控制器按优先级配置计算得到 `PreemptLowerPriority`，两者不一致，拒绝创建 Pod。

检查已有 PriorityClass 后，确认没有可复用的非抢占类别；本次采用默认优先级 0，并核对指定节点的现有工作负载优先级均不低于 0、八卡确实未分配，再提交精确节点选择的 Pod。没有提升优先级、创建全局 PriorityClass 或驱逐其他任务。一般部署中，若需要严格的非抢占语义，应使用集群管理员已配置好的 `preemptionPolicy: Never` PriorityClass，不能仅在 Pod 中覆盖与准入规则冲突的值。

### 8. 启动预算需要覆盖权重加载与两类图初始化

首次 SGLang 启动时，八个 Rank 的权重加载耗时为 1,481.53–1,481.82 秒（约 24 分 42 秒），随后普通解码 CUDA Graph 对 bs=4/2/1 捕获成功，耗时约 84.7 秒。仅观察显存已经分配，不能把前面的读取时间算成服务已经可用。

接下来引擎继续执行分段 CUDA Graph 初始化，默认覆盖从 4 到 2,048 Token 的 42 档形状。原 Pod 的启动探针预算只有 30 分钟，已经不足以覆盖权重加载和全部图初始化。因此在 API 尚未就绪时保留日志、结束第一次尝试，调整后重试；这不代表权重损坏或出现 OOM，也不把主动结束记录成已发生的探针超时。

第二次尝试采用 `--disable-piecewise-cuda-graph` 关闭分段图，保留普通解码 CUDA Graph，将启动探针预算改为 60 分钟，并继续保留 Pod 总运行期限。该固定镜像提示旧参数已弃用，会映射到 `--cuda-graph-backend-prefill=disabled`；本仓库脚本改用后者，实际运行配置须核对 prefill 后端为 disabled。两次启动日志分开保存，缓存状态也需要分别记录，不能将第二次启动时间直接当作相同冷缓存条件下的性能提升。

```bash
# 功能验收配置；对性能的影响须通过后续独立对照测量。
ENGINE=sglang DISABLE_PIECEWISE_CUDA_GRAPH=1 \
MAX_CONTEXT=8192 MAX_REQUESTS=4 EXECUTE=1 bash launch.sh
```

`DISABLE_PIECEWISE_CUDA_GRAPH` 是本仓库启动脚本的可选开关，当前默认启用该开关，即关闭 prefill 分段图。第二次尝试实际 API 就绪，12 项功能检查全部通过，涵盖三种推理模式、工具调用及结果回填、流式、多轮、图片和视频理解、非法参数及恢复。权重加载约 734–763 秒，普通解码图捕获约 45 秒；因缓存条件变化，不能与第一次直接作加载性能比较。启动探针覆盖加载与初始化，readiness probe 判断是否接流量，两者都不应替代功能测试。

日志还提示缺少 `NVIDIA_H20-3e`、E=129/N=384 对应的 Triton MoE 调优配置，当前使用默认配置。它属于性能调优提示，不能直接当作模型不支持 H20。后续性能结果应注明是否调优；专用 Kernel 配置须在实际硬件上生成和验证，不能简单改名复制其他 GPU 的配置后宣称已经优化。

### 9. 无人值守客户端不能固定 ConfigMap 的旧版本目录

vLLM 服务已经就绪后，自动验收第一次启动子脚本时返回 `No such file or directory`。定位发现控制器使用 `Path(__file__).resolve().parent`：ConfigMap 的文件是投影符号链接，解析后指向一个带版本的临时目录。控制器等待模型加载期间更新过 ConfigMap，旧版本目录被回收，随后启动 `smoke.py` 时路径已不存在。

修复为保留稳定挂载入口：`Path(__file__).absolute().parent`。旧尝试单独归档，使用新 attempt 重跑客户端，模型服务无需重启。补充模拟 ConfigMap 在等待期间切换并删除旧目录的回归验证，修复后控制器可以完成整条模拟流程。控制器启动失败与模型推理失败分开记录，不将这次失败计入请求错误率，也不删除原始日志。

### 10. 主压测通过后，语义验收仍须独立判断

vLLM 的主矩阵完成 33 轮、3,954 个请求，完成数、错误数和 Token 数检查全部通过。随后扩展验收发现：六个纯色静态图像配置在预热阶段未能正确回答颜色，因而没有计入对应正式图像压测；视频颜色顺序测试仍可通过。原始 PNG 的 RGB 像素经过检查，红图确为 (255,0,0)，蓝图确为 (0,0,255)。JPEG 重测仍有误判；带边框的红图及原有图表读取正常。当前不能把该结果表述成“图像生成文件损坏”，也不能以带边框图片通过来覆盖纯色图片失败。

约 31K 正文的原始检索模板同样返回 NOT_FOUND。继续缩短到只有一条记录后，原模板仍失败；明确要求提取 `<document>` 内“验收密钥:”后面的完整文本，则在短文本和原有约 31K 文档中都得到正确值。这说明不能仅据原模板失败就判定模型不支持 32K。独立复测保留原来的密钥、干扰内容和插入位置，单独记录提示词包装改变；两套引擎各通过三个位置的九个含答案样例和一个无答案对照。实现见 [needle_retest.py](https://github.com/runzhliu/aik8s/blob/main/examples/minimax-m3-h20/needle_retest.py)。

同一算术题要求“只输出最终整数”时，disabled 模式重复回答 264，而 adaptive/enabled 返回正确的 240。三个重复请求是同一道题的复现，不是三道独立题的准确率评估。公开报告同时列正确性、输出 Token 和耗时，不用更短的错误答案证明模式更好。

以上属于本次观察到的输入与模式边界，并未修改权重或推理引擎来宣称修复模型。原始失败请求、诊断请求和复测结果分别保存。只有测试脚本的路径故障等已经定位并修正的执行问题，才标记为修复通过。

## 已完成的八卡硬件预检

两个修复镜像在同一节点串行运行，各验证八张 GPU 的型号与容量、BF16 矩阵计算结果有限性，以及 NCCL all-reduce 的元素求和正确性。每档预热 5 次，测量 20 次，采用最慢 Rank 的平均耗时计算算法带宽。

| 镜像环境 | 1 MiB 正确性 | 16 MiB 正确性 | 128 MiB 正确性 | 128 MiB 算法带宽 |
| --- | --- | --- | --- | ---: |
| SGLang / Torch 2.11.0+cu130 | PASS | PASS | PASS | 235.9 GB/s |
| vLLM / Torch 2.11.0+cu130 | PASS | PASS | PASS | 235.6 GB/s |

这是单次短时硬件连通性检查，算法带宽也不是 NCCL bus bandwidth；它不加载 M3，不用于比较两个推理引擎的模型吞吐。小消息耗时容易受到调度和启动波动影响，完整通信性能评估需增加重复测量与统计。复现脚本见 [gpu_preflight.py](https://github.com/runzhliu/aik8s/blob/main/examples/minimax-m3-h20/gpu_preflight.py)，精简结果见 [GPU 预检记录](https://github.com/runzhliu/aik8s/blob/main/examples/minimax-m3-h20/images/gpu-preflight-summary.json)。

实测节点为双 Socket、两个 NUMA 域。GPU 0–3 对应 NUMA 0（CPU 0–191），GPU 4–7 对应 NUMA 1（CPU 192–383），GPU 两两拓扑均显示 NV18。GPU 间具有 NVLink 连接，不表示 CPU 预处理、主机内存和 GPU 拷贝天然满足 NUMA 本地性。部署时应分别记录 GPU 互联、Worker CPU affinity 和主机内存分配；绑定优化作为独立实验验证，不能把两个 NUMA 域简单视为 GPU 只能经 CPU 互联通信。

### 11. SGLang：损坏媒体的 HTTP 状态码未通过

正式扩展验收提交无效 PNG 与 MP4 内容：vLLM 均返回 400，SGLang 均返回 500。SGLang 日志显示 PIL 的 `UnidentifiedImageError` 与 TorchCodec 无效输入错误被多模态加载器包装为 `RuntimeError`，服务入口将其作为内部错误响应。之后正常请求恢复检查通过，进程未退出，但错误码验收仍为失败。本轮未修改该引擎源码或重新定义通过条件；这是仍需修复的接口边界。建议将明确的媒体格式校验错误转换为客户端错误，同时保留其他运行时异常的 500 语义，修复后另行验证坏媒体、正常多模态与恢复路径。
