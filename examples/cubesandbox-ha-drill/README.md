[简体中文](README.md) | [English](README.en.md)

# CubeSandbox 多副本故障切换实验

配套文章：[组件故障与恢复](../../docs/ai-k8s/rag-agent/cubesandbox-failure-recovery-practice.md)。本目录会扩容并删除指定控制组件 Pod，只适用于空闲、可恢复、由你独占实验范围的测试安装。不是生产巡检工具，也不是完整高可用部署模板。

本次实际测量：CubeSandbox / SDK 0.7.3，API、Master、Proxy 各临时扩到 2 副本，在**同一物理节点**逐项删除一个 Pod，保留另一副本。Master 两个 Pod 在同节点挂载原 RWO（ReadWriteOnce，单节点读写）卷；这不等于跨节点共享存储。没有停止主机、计算 Pod、CNI、数据库或已有虚拟机，也没有改 Helm release。结果见 [results.json](results.json)，691 条读取探针见 [probes.csv](probes.csv)。

| 文件 | 用途 |
| --- | --- |
| `run.py` | 备份副本数、双副本预检、独立 Nginx 入口、串行故障与最终恢复 |
| `guest.py` | guest 内随机身份与内存计数，18080 端口只通过 guest 内回环读取 |
| `watchdog.py` | 独立看护，控制器失联后恢复原副本数 |
| `dashboard.py` | 生成独立 Grafana 看板 ConfigMap |
| `export.py` | 按白名单导出测量结果，排除内部地址、Pod 名和响应原文 |

## 条件与请求路径

安装的 Helm release 名需为 `cube`，具有 `cube-api`、`cube-master`、`cube-proxy` 及配套 Service。只运行本目录创建的临时沙箱。模板必须绑定已验证的 v0.7.3 Rust Shim，并暴露 envd 的 49983 命令端口；从镜像标签不能推断实际运行时。运行前导出完整 workload、原 VMI UID / Ready 状态、卷信息，结束后逐项核对。

入口使用现有 CubeProxy 镜像内的 OpenResty，配置独立，不加载产品 Proxy 的 Lua 路由配置。真实四层入口使用 Nginx `stream`；真实七层入口使用 Nginx `http`。API 后端轮询；Proxy 后端主备，使故障前两条长流都经过被删除的主副本。静态后端是本次预检读到的 Pod IP；每组前重新读取并 reload，组内不跟踪新 Pod IP。被动失败摘除 `max_fails=1`、`fail_timeout=60s`、连接超时 1 秒，关闭前置 LB 的请求重放。

API 列表探针使用新 HTTP 连接，要求 JSON 含已知沙箱 ID。命令探针使用 SDK 原本的连接池，读取 guest 回环状态并核对身份。故障期间还串行执行“新建→命令→删除”，不重试变更请求。两条长流是 envd 的 `application/connect+json` 命令输出流，不是 WebSocket 或原生 gRPC。TLS 四层透传另做成功命令预检，因实验自签证书关闭了该请求的证书校验；不能照搬为生产 TLS 配置。

## 配置与运行

原始配置、清单、日志和输出必须放在 Git 忽略目录。下面是字段示例，替换为专用测试安装的真实值；`observer` 是已有稳定实验桥接，可用前一目录的 `observer.py` 准备，它不能作为长流测量入口。

```json
{
  "context": "lab-cluster",
  "namespace": "cube-system",
  "lab_namespace": "cube-fault-lab",
  "node": "REPLACE_TEST_NODE",
  "lb_image": "REPLACE_APPROVED_CUBE_PROXY_IMAGE:v0.7.3",
  "template": "REPLACE_VERIFIED_TEMPLATE",
  "observer": "http://127.0.0.1:18971",
  "observer_port": 18971,
  "required_shim_sha256": "REPLACE_ACTUAL_RUNTIME_SHA256",
  "vm_url": "http://127.0.0.1:18928"
}
```

`vm_url` 可省略；设置后会把**控制器实际观测值**带时间戳导入 VictoriaMetrics，不是 CubeSandbox 原生指标。不要把未脱敏的运行结果、模板材料或环境配置提交 GitHub。

```bash
python3 -m venv .local/cube-ha/venv
.local/cube-ha/venv/bin/pip install cubesandbox==0.7.3 requests websocket-client

# 先启动独立看护，在另一个终端运行主程序。
.local/cube-ha/venv/bin/python examples/cubesandbox-ha-drill/watchdog.py \
  --config .local/cube-ha/private/settings.json
.local/cube-ha/venv/bin/python examples/cubesandbox-ha-drill/run.py \
  --config .local/cube-ha/private/settings.json
```

主程序拒绝覆盖 `run.json`。独立看护每 2 秒检查租约；主程序每 5 秒续租，失联 70 秒或总期限 20 分钟到达后恢复原副本数。看护不负责迁移 VM、修复网络或终止未知进程。Pod 删除宽限期为 1 秒；这是 Pod 删除实验，不是主机断电或直接进程强杀。基线失败则不注入；`MEASURED` 只表示完成测量，不代表零错误或完整高可用验收。

## 查看、导出与恢复

```bash
python3 examples/cubesandbox-ha-drill/dashboard.py --view control \
  --output .local/cube-ha/private/dashboard-control.json
python3 examples/cubesandbox-ha-drill/dashboard.py --view proxy \
  --output .local/cube-ha/private/dashboard-proxy.json
python3 examples/cubesandbox-ha-drill/export.py \
  --private-dir .local/cube-ha/private --output-dir .local/cube-ha/public
```

看板需使用你的数据源 UID 和现有 sidecar 标签规则；生成器不会改变共享监控登录权限或采集配置。实验前置 LB 只有一个副本，未验证 LB 层本身的故障切换。没有测试 WebSocket、原生 gRPC、HTTP/2 流均衡、节点断电、跨节点 Master 存储、Redis / 数据库选主或快照迁移。

本次 API / Master / Proxy 已恢复原来各 1 副本，临时 LB 已删除，实验沙箱清单为 0，新建执行删除复核通过，原 5 台 VMI 的 UID 与 Ready 状态均保持。旧一轮计算 Pod 故障遗留的快照没有被本实验改动。早期 18080 端口预检返回 404、另一次模板准备未通过健康探测，都未进入故障注入，不混入正式结果。
