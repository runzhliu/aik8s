# nvitop-exporter NVML 580 验证镜像

这个派生镜像用于验证升级 Python 采集栈能否解决 H20 与 580 驱动组合下反复出现的 `SIGSEGV`、`double free or corruption`。它保留原镜像的 CUDA、系统和 Python 环境，只升级以下 Python 包：

- `nvitop == 1.7.1`
- `nvitop-exporter == 1.7.1`
- `nvidia-ml-py == 13.580.126`

## 构建

仓库地址、集群名和内部域名不要写入 Git。通过构建参数传入原镜像：

```bash
docker build \
  --platform linux/amd64 \
  --provenance=false \
  --build-arg BASE_IMAGE='<source-registry>/nvitop-exporter:v1.5.0@sha256:<digest>' \
  --tag '<staging-registry>/nvitop-exporter:v1.7.1-nvml13.580.126' \
  examples/nvitop-exporter-fix
```

这里显式使用 `--provenance=false`，让单架构构建输出传统 Docker schema v2 image manifest。部分旧版 Harbor Jobservice 会把默认的“OCI index + attestation manifest”误判为仓库不存在，导致同步任务在提交阶段失败。

## 本地验证

本地没有 GPU 时至少验证包依赖和 CLI；GPU/NVML 稳定性必须在 H20 节点灰度验证：

```bash
docker run --rm --platform linux/amd64 \
  --entrypoint /venv/bin/python \
  '<staging-registry>/nvitop-exporter:v1.7.1-nvml13.580.126' \
  -m pip check

docker run --rm --platform linux/amd64 \
  '<staging-registry>/nvitop-exporter:v1.7.1-nvml13.580.126' \
  --help
```

## 灰度原则

不要直接更新全量 DaemonSet。先创建仅匹配 1～2 个 H20 节点的灰度 DaemonSet，使用不同的名称和端口，连续观察至少 24 小时：

- Pod 重启数保持为 0；
- `/metrics` 抓取持续成功；
- 无退出码 139、`double free`、`invalid next size`；
- 指标标签和 Grafana 查询与旧版本兼容。

灰度成功后再逐批更新正式 DaemonSet，并保留旧镜像 tag 以便回滚。

## 镜像同步

推送到 staging 仓库后，先确认远端是单一 `linux/amd64` image manifest，再提交生产同步。命令中的仓库域名仍通过运行环境提供，不写入文档或 Git：

```bash
skopeo inspect --raw 'docker://<staging-registry>/nvitop-exporter:v1.7.1-nvml13.580.126'
gmanctl image sync '<project>/nvitop-exporter:v1.7.1-nvml13.580.126' --wait
```

同步成功不等于 H20 稳定性验证通过。必须完成灰度观察后才能替换正式 DaemonSet。

## 实测结果

在生产集群全量 rollout 后，这组升级没有消除 H20 崩溃：207 个 Pod 全部使用新镜像后，几分钟内至少 24 个 H20/HCC 节点再次出现退出码 139；RTX Ada 节点仍无重启。抽样 Pod 确认实际包版本与上述固定版本一致，进程加载的也是宿主机 580.126 NVML 动态库。

因此这个镜像是可复现问题的验证镜像，不应标记为稳定修复版。当前更安全的临时措施是在 H20 节点停用该 exporter，改用已经验证稳定的 DCGM Exporter；后续应使用 core dump 和最小 NVML 指标查询脚本继续定位原生崩溃点。
