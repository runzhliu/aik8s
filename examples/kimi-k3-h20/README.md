# Kimi K3 H20 测试材料

这组文件用于 Kimi K3 在 `gd5c-ai-001` 集群的零 GPU 预检、两节点 SGLang/vLLM
部署验证与公平压测。2026-09-02 已在 2 台 8×141GB H20 上完成 SGLang TP16/EP16
与 vLLM TP16 的功能、视觉、RDMA、OpenWebUI 和 11 组公平压测，两个服务均已缩容到 0。
完整实测结果见
[`results/20260902-h20-mxfp4/README.md`](results/20260902-h20-mxfp4/README.md)。

共享文件存储模型目录是 `/models/Kimi-K3/v1`：索引引用的 96 个正式分片全部存在且非空，
实际分片文件合计 `1,560,936,091,448` 字节。源目录中的 3 个残留 `*.tmp` 文件不属于
索引引用分片，NVMe 预热时明确排除。

完整 Gate、停止条件和当前运行时风险见
[`docs/ai-k8s/practices/kimi-k3-h20-deployment-benchmark-plan.md`](../../docs/ai-k8s/practices/kimi-k3-h20-deployment-benchmark-plan.md)。

## 资源边界

- 单台 8×141GB H20 不足以容纳约 1,680GB Checkpoint；
- 2×8×96GB H20 也不足；
- 首轮只选择 2 台各 8×141GB H20，并要求跨机 RDMA/NCCL 预检通过；
- 先跑 SGLang TP16/EP16 Target-only，vLLM 作为第二阶段 Experimental；
- 结束后必须缩容到 0，避免持续占用 16 张 H20。

## 文件

```text
preflight.py      # 不占 GPU：校验模型、分片、量化配置和运行时注册
smoke.py          # OpenAI API、Reasoning、Tool Call、流式、多轮、图片正确性
cases.csv         # 公平压测矩阵
benchmark.sh      # 默认 dry-run 的 vllm bench serve / SGLang 原生入口
images/           # 固定 upstream linux/amd64 manifest 与内网同步记录
```

`k8s/` 中保留本次两节点部署、RDMA/NCCL 预检、正确性 Smoke、公平压测和 OpenWebUI
Ingress Manifest。节点选择、NVMe 完成标记和 `dist-init-addr` 在复测前必须重新核对，
不能直接假设旧测试节点仍可用。

实际预检、SGLang/vLLM 服务和压测客户端统一使用容器内
`/models-nvme/Kimi-K3/v1`。服务清单必须把宿主机 `/apps/dat/model-cache` 只读挂载到
`/models-nvme`，并在 Init Container 中验证 `.aik8s-complete`；不允许回退到共享文件存储。

## 0. 预热 H20-3e 本地 NVMe

`k8s/prewarm-h20-mxfp4.yaml` 只匹配 24 台同时具有
`label-group=gpu-training-H20`、`machine-type=A9-1` 和
`node.kubernetes.io/instance-type=HCCPNV6s.96XLARGE2304-ne` 的 H20-3e 节点。
它从只读共享文件存储 `/models/Kimi-K3/v1` 复制到宿主机 NVMe XFS
`/apps/dat/model-cache/Kimi-K3/v1`，按 `8 + 8 + 8` 三批、间隔 60 分钟启动。

复制按文件大小续跑，不计算哈希；完成后检查全部非临时文件、96 个分片和总字节数，
再写入 `.aik8s-complete`。任务不申请 GPU，也不会把权重放到其他机型或非 NVMe 目录。

```bash
gmanctl --cluster gd5c-ai-001 apply \
  -f examples/kimi-k3-h20/k8s/prewarm-h20-mxfp4.yaml

gmanctl --cluster gd5c-ai-001 -n aik8s-ms get pod \
  -l app.kubernetes.io/name=kimi-k3-nvme-prewarm -o wide
```

## 1. 零 GPU 预检

```bash
MODEL_PATH=/models-nvme/Kimi-K3/v1 \
ENGINE=sglang \
python3 preflight.py
```

如同步流程留下 Revision 文件，可额外固定：

```bash
EXPECTED_REVISION=<commit-or-version> \
MODEL_PATH=/models-nvme/Kimi-K3/v1 \
ENGINE=sglang \
python3 preflight.py
```

## 2. 正确性 Smoke

```bash
BASE_URL=http://127.0.0.1:30000/v1 \
MODEL=kimi-k3 \
IMAGE_URL=https://example.invalid/a-test-image.jpg \
python3 smoke.py
```

`IMAGE_URL` 必须是服务 Pod 可访问的稳定测试图片。图片测试默认必须通过；临时只做文本诊断
时可显式设 `REQUIRE_VISION=0`，但不能因此宣称多模态验收完成。

## 3. 压测 dry-run

```bash
ENGINE=sglang STAGE=baseline bash benchmark.sh
```

确认命令后才执行：

```bash
ENGINE=sglang \
STAGE=baseline \
EXECUTE=1 \
BASE_URL=http://127.0.0.1:30000 \
TOKENIZER=/models-nvme/Kimi-K3/v1 \
MODEL=kimi-k3 \
MAX_CONTEXT=32768 \
RUN_LABEL=h20-mxfp4-tp16-target \
bash benchmark.sh
```

两个引擎的主对比固定使用 `BENCH_CLIENT=vllm`。`BENCH_CLIENT=sglang-native` 仅用于 SGLang
内部诊断，结果单独保存，不与主 A/B 混用。
