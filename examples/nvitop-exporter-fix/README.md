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
  --tag '<staging-registry>/nvitop-exporter:v1.7.1-nvml13.580.126-r2' \
  examples/nvitop-exporter-fix
```

这里显式使用 `--provenance=false`，让单架构构建输出传统 Docker schema v2 image manifest。部分旧版 Harbor Jobservice 会把默认的“OCI index + attestation manifest”误判为仓库不存在，导致同步任务在提交阶段失败。

## 本地验证

本地没有 GPU 时至少验证包依赖和 CLI；GPU/NVML 稳定性必须在 H20 节点灰度验证：

```bash
docker run --rm --platform linux/amd64 \
  --entrypoint /venv/bin/python \
  '<staging-registry>/nvitop-exporter:v1.7.1-nvml13.580.126-r2' \
  -m pip check

docker run --rm --platform linux/amd64 \
  --entrypoint /venv/bin/python \
  '<staging-registry>/nvitop-exporter:v1.7.1-nvml13.580.126-r2' \
  -c 'import os,nvitop; print(os.getcwd(), nvitop.__version__, nvitop.__file__)'

docker run --rm --platform linux/amd64 \
  '<staging-registry>/nvitop-exporter:v1.7.1-nvml13.580.126-r2' \
  --help
```

版本校验不能只看 `pip show`。原镜像把 `WORKDIR` 设置为 `/nvitop`，并在该目录保留 1.5.0 源码；即使 site-packages 已安装 1.7.1，Python 仍会优先导入当前目录下的旧包。修复镜像把工作目录切到 `/`，校验结果应同时满足：当前目录不是 `/nvitop`、版本是 1.7.1、模块路径位于 `/venv/lib/python3.8/site-packages/`。

如果真实 1.7.1 在 H20/H20-3e 上仍复现 NVLink field-value 查询导致的堆损坏，可在 r2 上构建关闭 NVLink 吞吐量指标的 r3。其他 GPU、显存、功耗、温度、PCIe 和进程指标保持不变：

```bash
docker build \
  --platform linux/amd64 \
  --provenance=false \
  --file examples/nvitop-exporter-fix/Dockerfile.nvlink-guard \
  --build-arg BASE_IMAGE='<staging-registry>/nvitop-exporter:v1.7.1-nvml13.580.126-r2@sha256:<digest>' \
  --tag '<staging-registry>/nvitop-exporter:v1.7.1-nvml13.580.126-r3-no-nvlink' \
  examples/nvitop-exporter-fix
```

r3 通过 Python `.pth` 启动钩子替换 `Device.nvlink_throughput()`，默认由 `NVITOP_DISABLE_NVLINK_THROUGHPUT=1` 启用。设置为 `0`、`false` 或 `no` 可恢复上游查询；没有完成驱动或上游修复验证前，不应在故障节点恢复。

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
skopeo inspect --raw 'docker://<staging-registry>/nvitop-exporter:v1.7.1-nvml13.580.126-r2'
gmanctl image sync '<project>/nvitop-exporter:v1.7.1-nvml13.580.126-r2' --wait
```

同步成功不等于 H20 稳定性验证通过。必须完成灰度观察后才能替换正式 DaemonSet。

## 实测结果

第一次全量 rollout 使用的候选镜像仍然崩溃：207 个 Pod 中，几分钟内至少 24 个 H20/HCC 节点出现退出码 139，RTX Ada 节点无重启。但这次测试不能作为 1.7.1 的反证。容器中 `pip show` 虽显示 1.7.1，运行时实际导入的是 `/nvitop/nvitop/` 下的 1.5.0 源码，形成“1.5.0 API + 1.7.1 exporter + 13.580.126 NVML Python 绑定”的混合栈。

在单个 H20 节点启用 core dump 后，旧候选镜像约 33 秒复现 `double free or corruption (!prev)`。Python/GDB 栈定位到 1.5.0 的 `nvitop.api.device.query_nvlink_throughput_counters()`，调用链来自 exporter 的设备指标采集。正式 DaemonSet 没有挂载 core pattern 指向的 `/apps/logs`，因此此前即使内核生成 core，也无法在容器文件系统中保留。

`r2` 镜像通过 `WORKDIR /` 消除旧源码遮蔽。单 H20 canary 加载 site-packages 中的 nvitop 1.7.1，连续 60 次 `/metrics` 请求成功，超过 5 分钟仍无重启；但全量 207 个实例更新后，H20-3e 节点再次出现 `double free or corruption (!prev)`。运行时确认故障 Pod 的确加载 1.7.1，不再是旧源码遮蔽。正式 r2 在短时观察中累计达到 111 次重启，35 个 Pod 的最后退出码为 139，说明单节点短时 canary 不能覆盖该故障的随机性和节点差异。

r3 保持真实 1.7.1，只禁用 core 已指向的 NVLink throughput field-value 查询。H20-3e canary 在 5 分钟内完成 1,180 次主动 `/metrics` 请求，其中 1,000 次为并发请求，重启数 0、无 core。随后正式 DaemonSet 更新为 r3：207/207 实例全部 Ready；从 rollout 完成后的零基线连续观察 5 分钟，全量重启数仍为 0，没有退出 139 或 `CrashLoopBackOff`。在一个此前实际发生 139 的 H20-3e 节点抽查，guard 已生效且正式 5050 `/metrics` 正常返回。

这个结果表明禁用 NVLink 吞吐量查询可以消除当前短时复现，但仍需连续观察至少 24 小时。r3 的已知功能差异是 NVLink 总量、均值和逐链路吞吐量指标不再产生有效样本；仪表盘和告警应显式容忍这些指标缺失或 NaN。

如需复现和取栈，可基于 `Dockerfile.debug` 构建调试镜像并使用 `gdb-canary-pod.yaml`。提交到 Git 的示例只保留占位符，不记录生产仓库、节点地址或其他内部标识。
