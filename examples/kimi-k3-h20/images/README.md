# Kimi K3 镜像记录

记录日期：2026-08-31。专用镜像由可访问公网 Registry 的 `10.189.109.87` 中转机使用
Skopeo 直接 Registry-to-Registry 复制，不经过本地 VPN，也不在中转机展开完整 Docker 镜像层。

## 固定上游 Manifest

| 引擎 | 上游引用 | Index / List | `linux/amd64` Manifest | 压缩层总计 |
| --- | --- | --- | --- | ---: |
| SGLang | `lmsysorg/sglang:kimi-k3` | `sha256:6d9594a421be244f2af29d726158ebffe9c3c2b3f39b5b89affd8150a106e187` | `sha256:e35551fd3adb5a4a894246249cb77f2d47cfd3702072d0dd137285c2e1b9fc27` | 16,076,118,611 B |
| vLLM | `vllm/vllm-openai:kimi-k3` | `sha256:e90e2603b2781936651ba019804137714367c69e10a7b25a2e57b46995225616` | `sha256:fb16b180bd9727600067e16fcd6a6de43fb4db1baf4298ef20b4dbdf6bfa5a0e` | 13,327,998,789 B |

## 内网 Tag

```text
vipdocker-f9nub.vclound.com/vip/llm-serving-sglang:kimi-k3-cu130-amd64-20260831
vipdocker-f9nub.vclound.com/vip/llm-serving-vllm:kimi-k3-cu130-amd64-20260831
```

Skopeo 复制时固定上游 amd64 digest，并以 Docker schema2 写入 staging。由于目标 Manifest
序列化格式可能不同，最终以 staging `inspect` 返回的 digest 为准，不假定它一定等于上游 digest。

通过 `gmanctl image sync` 同步后，集群使用：

```text
vip-gd-harbor.tencentcloudcr.com/vip/llm-serving-sglang:kimi-k3-cu130-amd64-20260831
vip-gd-harbor.tencentcloudcr.com/vip/llm-serving-vllm:kimi-k3-cu130-amd64-20260831
```

复制和目标 digest 完成后补在下表：

| 目标 | SGLang digest | vLLM digest | 状态 |
| --- | --- | --- | --- |
| staging | `sha256:f9c859687705b4ff171b1941bad6a991b752d8f06bcdb7f3bd2430d421d0e709` | `sha256:fb16b180bd9727600067e16fcd6a6de43fb4db1baf4298ef20b4dbdf6bfa5a0e` | amd64/linux inspect 通过 |
| production | 任务 `474880` 成功 | 任务 `474881` 成功 | staging → 生产完成 |
| gd5c | `sha256:f9c859687705b4ff171b1941bad6a991b752d8f06bcdb7f3bd2430d421d0e709` | `sha256:fb16b180bd9727600067e16fcd6a6de43fb4db1baf4298ef20b4dbdf6bfa5a0e` | 后台复制与集群实际拉取均通过 |

gd5c 的 GPU Manager 操作记录分别为 SGLang `20057` / Harbor task `158560`、vLLM
`20060` / Harbor task `158562`，最终状态均为 `Success`。零 GPU 运行时探针在
`10.91.0.106` 和 `10.91.0.128` 上完成，确认目标镜像为 `linux/x86_64`，镜像内版本为：

- SGLang：`0.5.16`；
- vLLM：`0.1.dev19262+gb6bbf29dd.d20260727`。

## 运行时约束

- 两个 Day-0 镜像均为 CUDA 13 路线，宿主机驱动需要 R580+；
- SGLang 同时提供 `lmsysorg/sglang:kimi-k3-cu12` 作为 CUDA 12 备选，但本轮未同步；
- 不使用浮动 Tag 部署，Kubernetes Manifest 应引用内网 Tag，并在结果元数据里保存实际 digest；
- Dockerfile 只用于记录固定基础镜像；当前没有额外补丁，不需要为了“封装”再构建一层。
