# GLM-5.3 runtime images

本目录固定 2026-08-30 验证到的 `linux/amd64` Manifest：

| Engine | Upstream | amd64 manifest |
| --- | --- | --- |
| SGLang | `lmsysorg/sglang:latest` | `sha256:bde16a8447b19e89056b9eea06c72be6c02801dc89d528c9ea90c53368fd74bf` |
| vLLM | `vllm/vllm-openai:v0.28.0` | `sha256:2286e8533ca8b6bc777594bae30524f1426ba46ca21797524e06df6a94b06635` |

目标节点为 `linux/amd64`，拉取和推送必须显式限定平台。内部仓库域名、项目名和 Digest
不写入公开仓库：

```bash
docker pull --platform linux/amd64 \
  lmsysorg/sglang@sha256:bde16a8447b19e89056b9eea06c72be6c02801dc89d528c9ea90c53368fd74bf

docker pull --platform linux/amd64 \
  vllm/vllm-openai@sha256:2286e8533ca8b6bc777594bae30524f1426ba46ca21797524e06df6a94b06635

docker tag <UPSTREAM_REF> <STAGING_REGISTRY>/<PROJECT>/<IMAGE>:<TAG>
docker push --platform linux/amd64 <STAGING_REGISTRY>/<PROJECT>/<IMAGE>:<TAG>
```

推送后验证目标端是单一 `linux/amd64` Manifest，并在运行时预检中打印 SGLang、vLLM、
Transformers、Torch、CUDA 与关键 Kernel 版本。
