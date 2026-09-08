# MiniMax-M3 镜像准备与修复记录

两套候选镜像均已构建、通过中转仓库同步到目标仓库。SGLang 最终候选采用 CUDA 13；CUDA 12 镜像保留为排查记录，没有作为已修复版本交付。镜像准备完成后，已在同一 H20-3e 节点串行通过八卡 CUDA/NCCL 预检；两套引擎在 32K/C32 配置下各通过 12 项基础功能和 33 轮、3,954 请求的主矩阵。原始语义失败、独立复测及 SGLang 损坏媒体返回 500 的边界详见[实测报告](../../../docs/ai-k8s/practices/minimax-m3-h20-benchmark.md)。

## 固定来源与最终版本

| 项目 | SGLang | vLLM |
| --- | --- | --- |
| 官方发现标签 | `lmsysorg/sglang:dev-cu13-minimax-m3` | `vllm/vllm-openai:minimax-m3` |
| CUDA / Torch | 13.0.1 / 2.11.0+cu130 | 13.0.1 / 2.11.0+cu130 |
| 引擎版本 | 0.0.0.dev1+g56e290315 | 0.1.dev17492+g454b47db8 |
| Transformers | 5.8.1 | 5.11.0 |
| FlashInfer | 0.6.12 | 0.6.12 |
| PyAV | 16.1.0 | 16.1.0 |
| 最终依赖检查 | 通过 | 通过 |
| 中转机 CPU 探针 | CPU_PASS | CPU_PASS_GPU_CLI_DEFERRED |
| 目标仓库镜像探针 | CPU_PASS | CPU_PASS_GPU_CLI_DEFERRED |
| 八卡 BF16 计算 / NCCL 正确性 | PASS | PASS |
| M3 加载与 12 项模型功能 | 32K/C32 PASS | 32K/C32 PASS |
| 完整主压测矩阵 | 33 轮 / 3,954 请求，零请求失败 | 33 轮 / 3,954 请求，零请求失败 |

上游 amd64 Manifest：

- SGLang：`sha256:8cc6e6f90bf803e9817800b679173d0b526f2b42b2c61b7ecafecdadb610eb55`
- vLLM：`sha256:a8c89303e467d08ef77ab5fac1ab20910a09b47d10787474b4ee70dfb6bee148`

修复后 Manifest（与上游分开记录）：

- SGLang：`sha256:cef47b57312b61bb4d8873873fa12dab377707a63d74b3bf51e556f09722d403`
- vLLM：`sha256:8a1060d311c177346721f4714f9d448630a69354bda07852f6e161964de98818`

完整 Index、Manifest、config、上游 layer digest、修复后版本与交付状态见 [images.lock.json](images.lock.json)。脱敏后的原始检查摘录见 [cpu-verification-summary.json](cpu-verification-summary.json)。镜像版本固定不代表两个引擎的依赖完全相同；后续对照测试须报告实际环境。

## 修复过程

公开测试文档的[镜像修复章节](../../../docs/ai-k8s/practices/minimax-m3-h20-sglang-vllm-test-plan.md#镜像准备中的问题修复与验证)记录了报错、定位、失败尝试与最终验证。这里列出实施要点。

### SGLang：保留 NIXL 入口，补齐依赖

最初 CUDA 12 候选的 pip check 报七项冲突；中转下载大层反复重试后，改为检查同一引擎 Commit 的官方 CUDA 13 构建。已有镜像副本与官方的 config 和全部 63 个解压后层 diffID 一致，压缩层 digest 不同；因此确认了内容一致，不能称为压缩 blob 完全一致。公开 Dockerfile 默认使用官方不可变源，可通过 BASE_IMAGE 指定经过同样核验的副本。

CUDA 13 原镜像报错：

```text
nixl 1.2.0 requires nixl-cu12, which is not installed.
moviepy 2.2.1 has requirement pillow<12.0,>=9.2.0, but you have pillow 12.2.0.
```

曾尝试卸载 nixl：依赖检查通过，但 `find_spec('nixl')` 断言失败，构建被拦截。这说明它包含实际 Python 入口，不能作为无用元包删除。

最终 [Dockerfile.sglang](Dockerfile.sglang) 保留 NIXL 前端和 cu13 后端，安装 `nixl-cu12==1.2.0`、`pillow==11.3.0`，再检查 pip 与入口存在。已检查的 NIXL 1.2.0 前端根据 Torch 的 CUDA 主版本选择后端；本镜像选择逻辑指向 `nixl_cu13`。两个后端包并存满足该版本的依赖声明，并不代表服务改用 CUDA 12。NIXL GPU 数据传输仍待实测。

### vLLM：系统依赖、视频解码与 CPU 客户端

原镜像报 PyGObject 缺少 pycairo。[Dockerfile.vllm](Dockerfile.vllm) 移除不用于模型服务的 `python3-gi`、`python3-software-properties`、`software-properties-common` 三个系统包，并安装 `av==16.1.0`。不执行全局 autoremove。修复后 pip check 通过。

原始 GPU CLI 在零 GPU 环境报 `Failed to infer device type`。探针保留该错误，再显式选用 CpuPlatform 只验收参数解析；[bench_client.py](../bench_client.py) 为同版本的 HTTP 压测客户端采用该适配。GPU 服务的 launch.sh 没有改成 CPU。最终标记 `CPU_PASS_GPU_CLI_DEFERRED`，这是当时 CPU 探针的范围；后续 GPU 服务启动与主矩阵已通过。

两套镜像都通过 PyAV 的 8 帧、64×64 MPEG-4 编解码往返检查。该结果不等于 M3 已完成视频理解。后续处理器、采样和模型回答的验收见实测报告。

### 构建与复制

额外 Dockerfile frontend 与 PyPI 下载曾停滞。简单 Dockerfile 改用内置 frontend，并将包索引设为可配置的 PIP_INDEX_URL，保留直接修复依赖的固定版本。构建退出码、最终新 digest 与完整日志分别归档。

本机推送遇到 unauthorized 后，改用已有授权中转通道。公开材料不保存账号凭据。生产同步与目标云端复制分别检查最终成功状态；提交成功不能视为交付成功。最终从目标仓库拉取镜像执行零 GPU 探针，核对 Pod imageID，归档后清理探针。

## 重复验证

在 x86_64 Linux 上执行，替换为已交付仓库及对应的修复后 digest：

```bash
docker run --rm --network none --cpus 4 --memory 8g \
  -e NVIDIA_VISIBLE_DEVICES=void -e CUDA_VISIBLE_DEVICES= \
  -v "$PWD/verify_runtime.py:/probe.py:ro" \
  --entrypoint python3 <IMAGE_REPO>@<PREPARED_DIGEST> /probe.py sglang
```

vLLM 将最后一个参数改为 vllm。探针输出版本、各检查退出码、缺失 CLI 参数、源码文件与状态。CPU_CHECK_INCOMPLETE 须修复具体失败项；CPU_PASS 也不能替代 GPU 验收。

两套 CUDA 13 镜像的 Torch 架构清单含 sm_90，H20-3e 八卡 CUDA/NCCL 预检已通过（[结果](gpu-preflight-summary.json)），SGLang 已完成 M3 实际加载、解码、图像与视频理解；vLLM 也已完成对应模型功能和主矩阵验收。SGLang 官方 Hopper 配方采用 CUDA 12，本次 CUDA 13 候选的实测范围见功能记录。BF16 TP8 为起点；vLLM 使用 block-size=128，Blackwell 专属加速不作为 H20 已验证能力。

参考：[SGLang Cookbook](https://docs.sglang.io/cookbook/autoregressive/MiniMax/MiniMax-M3)、[vLLM Recipe](https://recipes.vllm.ai/MiniMaxAI/MiniMax-M3)。真实仓库、同步任务及完整执行日志位于被 Git 忽略的 `../private/`。
