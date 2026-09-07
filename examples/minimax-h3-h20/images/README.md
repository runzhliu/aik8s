# H3 镜像准备记录

两套固定镜像已完成 CPU 检查与 GPU 功能/性能测试；原始版本和运行时补丁的区别见实测文档及修复记录。

| 用途 | 上游基础镜像 | 解析 Digest |
| --- | --- | --- |
| SGLang Diffusion | `lmsysorg/sglang:v0.5.18` | `sha256:9e148f5ac788e856a06166bd6347a831831eb9fcfab4d1770874823a7c29a1a1` |
| vLLM-Omni | `vllm/vllm-omni:minimax-h3` | `sha256:e930db8e225162d01e17a49dddc43fd0e844208908d8356a028e5c4e7357696e` |

构建显式指定 `linux/amd64`。上表为 inspect 返回的上游 Digest；如为多架构 Index，
继续保留 amd64 子 Manifest、config 与 layer Digest，不能将 Index 和 config ID 混称。

SGLang 源码固定 `71de97b264b04dcd514cf904003028aefe9775c8`；vLLM-Omni 覆盖源码固定
`48298030d4b3c320b858dd98934c01babdd320ce`（H3 模块化支持 #5720），配合基础镜像
core-vLLM `0.26.0`。最初选择的较新 Omni 主分支提交依赖另一套 core-vLLM 内部模块路径，
已在构建 import Gate 被拦截，未入库。
交付镜像按下文 Manifest Digest 固定；仓库模板分别为
`<REGISTRY>/vip/llm-serving-sglang-diffusion` 和 `<REGISTRY>/vip/llm-serving-vllm-omni`。

构建：

```bash
docker build --platform linux/amd64 -f Dockerfile.sglang -t <STAGING_IMAGE_SGLANG> .
docker build --platform linux/amd64 -f Dockerfile.vllm-omni -t <STAGING_IMAGE_OMNI> .
bash verify_image.sh sglang <STAGING_IMAGE_SGLANG>
bash verify_image.sh vllm-omni <STAGING_IMAGE_OMNI>
```

镜像内必须预置 FFmpeg、FFprobe、音频解码库和框架依赖。离线 CPU Gate 需验证 CLI 与
H3 模块导入；GPU Gate 需实际跑通编码、扩散、音视频解码与 MP4 封装。
CPU 探针失败时不得标为可部署，基础镜像同步成功也不代表派生镜像已交付。
如果某个模块仅因 import 阶段强制探测 GPU 而失败，保留原始错误，转到获批 GPU 窗口
做同等检查；不能删掉探针后将结果写成 CPU Gate 已通过。检查失败时不自动推送发布标签。

| 阶段 | SGLang Diffusion | vLLM-Omni |
| --- | --- | --- |
| 上游解析 | 已完成 | 已完成 |
| 中转机基础镜像拉取 | 已完成 | 已完成 |
| 派生镜像构建及 CPU Gate | 已通过 | 已通过；另验证 H3 的 PyAV 参考视频解码 |
| staging / production / target | 已完成，目标已拉取固定 Digest | 已完成，目标已拉取固定 Digest |
| H20-3e 完整生成 | 15 类配置完成，音频参考含运行时修复 | 15 类配置完成，错误传播修复后接口验收通过 |

任何涉及内网地址、Registry 凭据及同步任务详情的运行记录只存本地忽略目录。

SGLang 实测镜像 Manifest：
`sha256:52c1049f10e9fa0e143c053e80fa94bcb5379fda23b1d3bc3e4c90e47a984c99`。
已通过 `--network none` 下的 `pip check`、H3 pipeline import、CLI 与 FFmpeg/FFprobe 检查。
基础镜像的 `nixl` 元包同时声明 CUDA 12/13 两套实现；移除无反向依赖的元包，保留
`nixl-cu13==1.4.0`，避免在 CUDA 13 镜像里混装 CUDA 12 实现。GPU 功能与性能结果另见实测文档。

vLLM-Omni 基础镜像的旧 NIXL 元包、非 H3 使用的系统 GTK Python 绑定和不支持当前 Python
平台的 Decord 也已清理。H3 源码自带 PyAV fallback；已用真实生成的 12 帧测试视频调用
`load_video_frames`，验证解码为 `(12, 64, 64, 3)`，不是只检查包能否导入。
CPU 检查使用实际入口 `vllm serve --omni --help`；裸 `vllm --help` 会初始化无关的
core-vLLM 命令并要求 GPU DeviceConfig。CPU 环境的 CUDA/custom-op 警告保留在日志，
不能据此认定 GPU kernels 已通过；完整模型生成仍是上线前独立 Gate。

vLLM-Omni 实测镜像 Manifest：
`sha256:9854b1f910bdd08bc2ced3e70e33218091229fa790d2d7bef5de0ec9f2dd4a19`。

目标 CPU 预检确认，vLLM-Omni 可通过保留目录中的 `modular_model_index.json` 识别
`MiniMaxH3ModularPipeline`；SGLang 使用 H3 原生注册路径进入对应分区。
CPU 环境下仍会记录 CUDA/custom-op 警告，不能用模型识别成功代替 GPU 生成验收。
