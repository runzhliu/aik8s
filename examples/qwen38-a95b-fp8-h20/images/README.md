# Qwen3.8-2.4T-A95B-FP8 镜像记录

记录日期：2026-09-03。镜像通过可访问公网 Registry 的中转机使用 Skopeo 做
Registry-to-Registry 复制，不经过本地 VPN，也不在中转机展开完整镜像层。

## 固定上游 Manifest

| 引擎 | 上游引用 | Index / List | `linux/amd64` Manifest | 压缩层总计 | CUDA | 构建 Commit |
| --- | --- | --- | --- | ---: | --- | --- |
| SGLang | `lmsysorg/sglang:qwen38` | `sha256:3f37902a0a4acb502403c87847b8836672f9b7b291e16e098316394d200feb58` | `sha256:a24b4b997aff149d1090cf3e4dcda3dc65eef70e3cdd51a5f2d6cc8d94fb69db` | 17,530,853,624 B | 13.0.3 | `c7c03ec53b1e664c2d415db4f02e43f86661f31d` |
| vLLM | `vllm/vllm-openai:qwen38` | `sha256:4a2f33a884222f7049b983263ad9976f89452bb81affecf5b67d89ad35c1bc31` | `sha256:d392f621bb3e372ecc09f0b0cb88099afe9fa05d37a0450de45eeb8c12b6787e` | 7,585,857,969 B | 13.0.1 | `3a0914114705fa38d4c3171d0746c1a6b6f10209` |

## 内网交付 Tag

```text
<STAGING_REGISTRY>/vip/llm-serving-sglang:qwen38-cu130-amd64-20260903
<STAGING_REGISTRY>/vip/llm-serving-vllm:qwen38-cu130-amd64-20260903
```

生产和 gd5c 集群使用同名仓库与 Tag。正式 Manifest 在同步完成后引用目标 Registry，并在
首次零 GPU 探针中记录目标实际 Digest。

| 目标 | SGLang | vLLM | 状态 |
| --- | --- | --- | --- |
| staging | 已核验 amd64、构建 Commit 和目标 Digest | 已核验 amd64、构建 Commit 和目标 Digest | Completed |
| production | staging → production 成功 | staging → production 成功 | Completed |
| gd5c | 节点实拉并运行版本探针成功 | 节点实拉并运行版本探针成功 | Verified |

gd5c 节点实际解析到的 Image ID：

```text
SGLang sha256:cbcd855fe525c4cde74b119c3755831f46209adfd4584801d51ce044924432ef
vLLM   sha256:d392f621bb3e372ecc09f0b0cb88099afe9fa05d37a0450de45eeb8c12b6787e
```

vLLM 目标 Digest 与上游 amd64 Manifest 一致。SGLang 在 Registry 复制后 Manifest Digest
发生变化；进一步比较上游与 staging 的 config Digest、层数和全部 layer Digest，组合校验值
一致，因此差异来自 Manifest 表达，不是镜像内容变化。gd5c 实拉大小分别约为 17.53GB 和
7.59GB，版本探针输出为 `sglang=0.0.0+qwen38.20260812.4e51ffc` 与
`vllm=0.1.dev19754+g3a0914114`。

H20-3e 临时网络探针能够启动强制拉取的 Docker Hub 小镜像，但容器内直接访问
`registry-1.docker.io` 超时。这只证明节点的 containerd/镜像加速路径对该小镜像可用，不能
证明任意公网镜像都能稳定直拉。因此 Qwen3.8 的两个大镜像仍走受控 Registry 同步链路。
