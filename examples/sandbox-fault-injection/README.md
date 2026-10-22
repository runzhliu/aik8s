# 沙箱故障与网络限制实验

[English](README.en.md) · [公开文章](../../docs/ai-k8s/rag-agent/sandbox-runtime-failure-network-policy.md)

在独立 fault Pod 中运行 Microsandbox 0.7.8 / BoxLite 0.10.7，分别强杀 detached SDK 客户端、持有 KVM 句柄的 VMM、重建承载 Pod。两个独立接收端分别代表允许和禁止目标。`results.json` 保留正式测量、对照、失败、中断与未执行范围。

前提是已准备此前 Microsandbox / BoxLite 实验的镜像、命名空间和 PVC（默认 `microsandbox-data` / `boxlite-data`）。新 Deployment 名为 `fault-runtime`，使用独立 home，原工作台不修改。示例 BoxLite 配置为特权容器，沿用原实验的设备访问方式；Microsandbox 使用已有 KVM 设备插件。不要部署到正在承载其他沙箱的运行目录。

```bash
python3 examples/sandbox-fault-injection/render.py \
  --node kvm-worker \
  --microsandbox-image registry.example.org/lab/microsandbox:0.7.8 \
  --boxlite-image registry.example.org/lab/boxlite:0.10.7 \
  --output .local/sandbox-fault-install
kubectl create namespace sandbox-fault-lab
kubectl apply --dry-run=server -f .local/sandbox-fault-install/install.json
kubectl apply -f .local/sandbox-fault-install/install.json
```

按此前文章的方法准备 `/data/guest.tar`，在新 Microsandbox fault Pod 内导入到它自己的 `MSB_HOME`：

```bash
kubectl -n microsandbox-lab exec deploy/fault-runtime -- msb load --input /data/guest.tar --tag python-lab:local
```

两条 port-forward 必须分别保持运行：

```bash
kubectl -n sandbox-fault-lab port-forward svc/fault-allow 18960:8080
kubectl -n sandbox-fault-lab port-forward svc/fault-deny 18961:8080
```

先用 `control` 验证两个目标都可达，再运行 `sdk`、`vmm`、`pod`。同一个运行时按顺序执行，每次使用全新的 attempt；不要并发操作同一个 fault Pod。脚本只杀经过身份检查的专用容器 PID，故障后保留约 12 秒完整观测，并清理本轮 guest。

```bash
python3 examples/sandbox-fault-injection/run_case.py microsandbox control --context lab-cluster --attempt a01 --evidence-dir .local/sandbox-fault-evidence
python3 examples/sandbox-fault-injection/run_case.py microsandbox sdk --context lab-cluster --attempt a01 --evidence-dir .local/sandbox-fault-evidence
```

同理替换 engine 为 `boxlite`。本轮两个本地版本都没有独立网络代理进程，因此未提供把代理强杀伪装成额外测量的命令。探针最多运行 240 秒，worker 最多 290 秒；控制器单个 kubectl 操作有期限并在 `finally` 中清理。若手动中断导致状态不完整，先检查并回收当前 case，再开始下一项。

`opensandbox_fault.py` 是额外的普通容器后端控制面测试，需要已有且无任务的 OpenSandbox 实验安装、Python SDK 和以下环境变量：`KUBE_CONTEXT`、`EVIDENCE_DIR`、`OPENSANDBOX_API_KEY_FILE`、`GUEST_IMAGE`、`ALLOW_URL`、`DENY_URL`。`ATTEMPT` 可选。它会等待 API / Controller Pod 全部删除，观察 15 秒，然后在 `finally` 中恢复原副本数并删除任务。此组没有出口限制，不能用于证明网络策略安全。

`monitoring.yaml` 新增 VMServiceScrape；`dashboard.py --output FILE` 生成 Grafana ConfigMap，默认命名空间 `victoriametrics`、数据源 UID `VictoriaMetrics`。Dashboard 选择器固定为本轮正式 case；复测时根据自己的 attempt 更新。只追加实验资源，不替换现有 Helm values。

故障运行时清理：

```bash
kubectl -n microsandbox-lab delete deploy fault-runtime
kubectl -n boxlite-lab delete deploy fault-runtime
```

接收端 UI 位于 <http://127.0.0.1:18960/>，按 `?group=sdk` 与 `?group=platform` 分组，支持中英文。它是本文配套观测页，非官方 Console；展示上传的实测记录。结果可通过 `/record` 上传；该实验入口无认证，只应通过受控网络和 localhost 转发访问。不要把私有环境清单、Key 或原始内部地址提交到公开仓库。

`receiver-events.csv` 保存去重后的接收端请求时间、目标角色与场景编号；所有正式场景的前后窗口计数均已与 CSV 逐项核对。
