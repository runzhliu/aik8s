[简体中文](README.md) | [English](README.en.md)

# CubeSandbox 组件故障演练

配套文章：[故障演练与恢复](../../docs/ai-k8s/rag-agent/cubesandbox-failure-recovery-practice.md)。这组程序用于空闲、可恢复的专用实验安装，会暂停组件、缩容服务或删除计算 Pod；不是只读检查工具。不要直接用于在线业务安装。

`results.json` 包含实际 v0.7.3 的 13 个 attempt，覆盖 12 类场景，以及 10 个明确分开的历史 attempt。11 类完成故障注入，HTTP 路径规则因允许基线失败未注入；计算 Pod 重建两次失败，不能把 `MEASURED` 理解为业务验收通过。看 `controller_result`、`task_recovered`、清理结果和 `manual_recovery_attempts`。`receiver-events.csv` 为脱敏逐请求记录，共 5296 条，导出时逐窗口核对计数。

## 文件

| 文件 | 用途 |
| --- | --- |
| `render.py` | 生成独立接收端与可选 VMServiceScrape，不修改 CubeSandbox 安装 |
| `observer.py` | 两个独立 HTTP 接收端、指标与实验用 API / CubeProxy 桥接 |
| `guest_probe.py` | 内存计数、随机身份、快照暂停与 A/B 请求 |
| `run_drill.py` | 串行运行一个故障场景，保存私有原始记录与代码哈希 |
| `process_guard.py` | 精确进程身份检查，禁止 PID 1，校验启动时间与命令哈希 |
| `watchdog.py` | 主程序之外的恢复看护，只恢复当前 armed 的对象 |
| `dashboard.py` | 生成独立 Grafana 看板 ConfigMap |
| `export_results.py` | 白名单脱敏、窗口计数复核，生成公开 JSON / CSV |
| `index.html` | 中英文结果观测页，不是官方 Console |

## 准备安装与接收端

需要：可用的 CubeSandbox 0.7.3 安装、对应 SDK、`requests`、`kubectl`、Python 3、KVM 权限及独占本轮故障范围的使用权。被测安装必须没有其他沙箱。导出原 workload 配置、记录副本数和现有虚拟机 UID；已有模板和卷不删除。本文没有提供一键升级生产安装的脚本。

```bash
python3 -m venv .local/cube-drill/venv
.local/cube-drill/venv/bin/pip install cubesandbox==0.7.3 requests
python3 examples/cubesandbox-fault-drill/render.py \
  --image python:3.12-slim --node REPLACE_TEST_NODE \
  --scrape-namespace victoriametrics \
  --output .local/cube-drill/receivers.json
kubectl --context lab-cluster apply -f .local/cube-drill/receivers.json
kubectl --context lab-cluster -n cube-fault-lab rollout status deploy/cube-fault-allow
kubectl --context lab-cluster -n cube-fault-lab rollout status deploy/cube-fault-deny
```

镜像需经过所在环境批准，并提供 Python 3 标准库；本次实际使用既有缓存实验镜像。没有 VictoriaMetrics Operator 时省略 `--scrape-namespace`，自行增加等价的 Prometheus 采集。不要覆盖共享监控的 Helm values。

在两个独立终端建立 localhost 转发，保持直到原始数据导出：

```bash
kubectl --context lab-cluster -n cube-fault-lab port-forward svc/cube-fault-allow 18971:8080
kubectl --context lab-cluster -n cube-fault-lab port-forward svc/cube-fault-deny 18972:8080
```

接收端的 `/cubeapi/` 与保留 `*.cube.app` Host 的请求转发到安装内的 Service，使控制组件 Pod IP 变化时本地 SDK 入口保持稳定。这是实验专用、无身份认证的桥接，不能暴露到公网。桥接超时为 8 秒，超时请求可能已经产生服务端副作用，清理时必须再核对资源清单。

## 私有配置与版本核对

保存到 `.local/cube-drill/private/settings.json`，把示例地址替换为两个实际接收 Pod IP。它们是 Pod 地址，不是 Service ClusterIP：

```json
{
  "context": "lab-cluster",
  "namespace": "cube-system",
  "observer": "http://127.0.0.1:18971",
  "deny_observer": "http://127.0.0.1:18972",
  "observer_port": 18971,
  "template": "REPLACE_VERIFIED_TEMPLATE_ALIAS",
  "ips": {"allow": "192.0.2.10", "deny": "192.0.2.11"},
  "variant": "describe-your-actual-installation",
  "required_shim_sha256": "REPLACE_ACTUAL_EXECUTABLE_SHA256"
}
```

镜像标签、模板绑定和实际执行文件是不同检查。先创建一次沙箱，核对真实 Rust Shim 的组件 manifest 和 SHA-256；该程序会在注入前拒绝运行时哈希不符的场景。本次官方包实际哈希在 `results.json` 中，自己构建的包不能盲目套用这个值。guest 与出口 CIDR 配置差异也必须单独记录。

## 运行、看护与停止条件

先启动独立看护，再在另一终端执行一项。`--case` 支持 `api`、`master`、`ops`、`proxy`、`cubelet`、`vmm`、`mysql`、`redis`、`minio`、`egress`、`pod`。每次换新的 attempt；程序拒绝覆盖已有记录。

```bash
.local/cube-drill/venv/bin/python examples/cubesandbox-fault-drill/watchdog.py \
  --config .local/cube-drill/private/settings.json
```

```bash
.local/cube-drill/venv/bin/python examples/cubesandbox-fault-drill/run_drill.py \
  --config .local/cube-drill/private/settings.json --case vmm --attempt a01
.local/cube-drill/venv/bin/python examples/cubesandbox-fault-drill/run_drill.py \
  --config .local/cube-drill/private/settings.json --case egress --policy l3 --attempt a02
```

程序先做无策略与受限网络预检。七层模式使用 `--case egress --policy l7`；若允许请求本来就失败，不会继续注入。Pod 网络模式下 `--case pod` 是破坏性测试，应最后执行；如需人工分析失败快照，加 `--retain-failed-snapshot`，并单独安排清理。看护只能恢复副本数和精确暂停的进程，不能自动重建网络命名空间或修复快照登记。

每项之后核对原组件恢复、任务是否延续、接收端记录、新建执行删除成功以及清理结果。若任一基础健康检查失败，停止后续注入，先恢复环境。不要自动清空 bpffs、CNI 或 OVS。本次端口孤儿清理由人工在确认所有 CubeSandbox VM 均退出后完成，没有包装成在线一键修复。

## 导出与查看

```bash
.local/cube-drill/venv/bin/python examples/cubesandbox-fault-drill/export_results.py \
  --evidence-dir .local/cube-drill --output .local/cube-drill/public
```

导出器包含本次版本和 follow-up 文件约定；新实验应审核版本哈希与文件名规则，并保留原始证据，不覆盖仓库中的测量数据。将 `index.html` 与导出的 JSON 放在同一目录，可使用 `python3 -m http.server` 查看。仓库原结果可直接查看：

```bash
python3 -m http.server 18975 --bind 127.0.0.1 --directory examples/cubesandbox-fault-drill
```

打开 `http://127.0.0.1:18975/?group=runtime`，`#en` 切换英文。实际 Grafana 截图见文章；看板生成器需要将数据源 UID 改成你的 UID，并按现有 sidecar 标签方式导入，不会自动更改共享 Grafana 登录权限。

本次组件与临时配置已恢复、无运行中实验 VM、原五台虚拟机保持原 UID。失败快照清理因副本旧 Pod 端点超时尚有尾项，完整结果明确保留；不要据此宣称该 Pod 重建场景恢复成功。
