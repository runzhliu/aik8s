# AIBrix + DeepSeek V4 Flash 可观测性实战

这里保存脱敏后的部署模板、六类 Grafana 看板、八条 Prometheus 告警规则和流式性能客户端。实测结论见[公开文章](https://aik8s.run/ai-k8s/practices/aibrix-dsv4-observability/)。所有测试计划、账号、原始集群清单与私有证据都不在本目录。

## 范围

- 复用已部署的 AIBrix v0.7.0 / Envoy Gateway；不会替你安装或升级共享控制面。
- 两台独占八卡节点，各运行一个 TP8 模型副本。模型名为 `dsv4-flash-aibrix-perf`。
- 独立 CPU 节点运行 Prometheus/Grafana；Prometheus 使用 emptyDir，保留 24h/8GB，无 Alertmanager 通知链路。
- 示例 Namespace 为 `inference-lab`。需自行创建并绑定只读模型 PVC，确认准入策略、镜像凭据、节点污点、资源配额和 GPU 余量。
- 控制面与网关 Service 名称、标签、DCGM 命名空间沿用 AIBrix 示例环境。你的安装若不同，需修改监控模板中的服务发现条件。

## 渲染与部署

先将 `site.example.json` 复制为 Git 忽略的 `site.json`，填入实际节点、PVC、镜像。vLLM 镜像必须已验证支持该 checkpoint 的 tokenizer/parser 和 CUDA kernel。示例中使用公开 Prometheus/Grafana 标签，运行时测试使用的是同版本的内部 amd64 镜像；生产请核对并固定 digest。

```bash
python3 render.py --config site.json --output rendered
kubectl --context <CONTEXT> create namespace inference-lab
kubectl --context <CONTEXT> apply --dry-run=server -f rendered/model.json
kubectl --context <CONTEXT> apply --dry-run=server -f rendered/monitoring.json
kubectl --context <CONTEXT> apply -f rendered/model.json
kubectl --context <CONTEXT> apply -f rendered/monitoring.json
```

生成文件包含随机 Grafana 密码，权限为 0600。`rendered/` 和 `site.json` 已忽略，不应提交仓库。不要对无法理解的现有资源冲突直接使用 `--force-conflicts`。

模型的初始化容器检查索引列出的分片是否存在且非空；这是结构完整性检查，不是 SHA256 验证。模型权重与编译缓存分开挂载。startupProbe 给加载过程留出窗口，readinessProbe/livenessProbe 使用只检查健康的 `/health`，避免用生成请求作高频探针。

## 访问看板

```bash
kubectl --context <CONTEXT> -n inference-lab port-forward svc/aibrix-perf-grafana 33000:3000
kubectl --context <CONTEXT> -n inference-lab port-forward svc/aibrix-perf-prometheus 39090:9090
```

浏览器访问 `http://127.0.0.1:33000/d/aibrix-perf-overview`，账号 `admin`，密码见 `rendered/grafana-admin-password.txt`。所有看板带互相跳转的导航。Prometheus 的 Targets/Rules/Alerts 用来确认采集和规则评估；Grafana 空白不能直接解释成业务负载为零。

六个 JSON 可独立导入其他 Grafana。数据源 UID 为 `aibrix-perf-prometheus`；模型名变量为常量，可改为自己的模型。`replica`/`node_alias` 是采集重标记生成的逻辑别名，保留原始 `pod`/`node` 标签用于内部排查。

修改 ConfigMap 后先等待投影文件更新，执行 `promtool check config`，再向 Prometheus `/-/reload` 发 POST；重新查询 `/api/v1/rules`，确认规则数和 health。配置写入 API Server 不代表进程已加载新配置。

## 客户端及指标口径

`benchmark_client.py` 有三个模式：`smoke`、`run`、`serve`。`run` 顺序执行各档，每档有两轮预热，正式窗口至少 60 秒；异步闭环补请求，不模拟固定到达率。预热仍可能遗漏动态形状，需结合 JIT 日志复测，不能假设尾延迟已完全稳定。

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
export GATEWAY_URL=http://<AIBRIX_GATEWAY>
export SINGLE_POD_URL=http://<ONE_MODEL_POD>:8000
export MODEL=dsv4-flash-aibrix-perf
export RESULT_DIR=./results
.venv/bin/python benchmark_client.py smoke
.venv/bin/python benchmark_client.py serve
# 另一个终端使用相同环境变量、相同 RESULT_DIR：
.venv/bin/python benchmark_client.py run
```

正式测量建议把客户端放到集群 CPU 节点，避免把本地端口转发作为吞吐瓶颈。附带 `client.template.json`，渲染后的 `client.json` 使用独立 CPU Pod 和窄范围 hostPath。示例客户端镜像复用了本次验证包含 Python/aiohttp/prometheus-client 的 AIBrix metadata-service v0.7.0；独立镜像可以按 requirements.txt 构建。填入网关地址以及实际单个模型 Pod 地址后，再 apply 客户端清单。随后在客户端 Pod 中执行 `python3 /app/client.py run`；`serve` 进程持续导出结果指标。将 `RESULT_DIR` 挂载到专用 hostPath 或 PVC，并创建 `aibrix-perf-client:9095` Service；也可将监控模板中的 `benchmark-client` target 改为实际客户端地址。客户端不需要 GPU 或 Kubernetes 写权限。

TTFT 到第一个非空流式内容为止；TPOT 的分母来自 `usage.completion_tokens - 1`，分子是首个到最后一个内容片段的间隔。单 token 请求没有可定义的 TPOT。只有收到完整结束标记、内容及 usage，才计为成功。失败记录保存 HTTP 状态和有限错误内容，不自动重试掩盖失败。

`requests-*.jsonl` 保存每次请求；`summary-*.json` 保存精确分位数和总生成吞吐。`serve` 从这些文件导出 Prometheus 指标，不重放模型请求。已完成 phase 再运行会跳过；新一轮比较使用新的结果目录，避免把不同运行混在一起。

缓存负载为相同长前缀加不同尾部 nonce；请求顺序与缓存预热会影响结果。若要比较两种路由的独立收益，应使用对等的缓存初态、相同请求集合和交叉顺序，多轮验证。本文的热前缀演示不证明冷缓存收益。

## 演练与回滚边界

PDB 为 `minAvailable: 1`，Deployment 更新为 `maxUnavailable: 1/maxSurge: 0`。仅对自己这两个测试副本使用 Eviction API；同时记录请求错误、端点变化、告警状态和 Ready 恢复时间。不要对共享网关、其他模型或整个节点执行删除、drain 或故障注入。

验证完毕后是否保留模型副本，应按 GPU 使用窗口决定。暂停模型可将本例 Deployment 缩到 0；监控和原始证据的生命周期分别管理。若删除 Prometheus Pod，emptyDir 中的历史数据会消失，需先导出所需查询区间。


## 复现限定的恢复验证

先结束性能压测，再在同一个结果目录运行 `recovery_probe.py`。该脚本最多运行 10 分钟、并发 4，只发起测试模型请求；创建结果目录下的 `recovery-stop` 文件可让它在当前请求结束后停止。它不执行 Kubernetes 驱逐。

另开终端核对 Deployment Ready 为 2、PDB allowedDisruptions 为 1，再选择一个明确的测试 Pod。使用 `policy/v1 Eviction`，带上该 Pod 的 UID precondition，防止名称复用导致操作错误对象。恢复期间，对另一个副本只执行 `?dryRun=All` 的 Eviction 校验，预期在预算不足时返回 429；不要实际驱逐第二个副本。

恢复后检查新 Pod Ready、Service endpoints、真实生成请求及规则状态，再结束探测并回传结果。实验结束时把 `active.json` 的 phase 设为 `released`，再缩容模型到 0，可抑制示例中预期停机的副本数告警。这个结束标记只是实验控制信号；正式生产应使用期望副本数和维护窗口管理告警。
