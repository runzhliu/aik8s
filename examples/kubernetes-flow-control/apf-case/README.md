# APF 隔离实测示例

配套案例：`docs/ai-k8s/practices/apf-isolation-case.md`。

本例使用 Kubernetes flowcontrol v1 API，运行四个阶段：5 份额 Queue、0 份额 Reject、0 份额 Queue、恢复 5 份额 Queue。每阶段默认 90 秒。客户端以最多 8 个并发、目标 5 req/s 读取一个专用 ConfigMap；独立账号每秒读取同一对象，作为对照。请求不自动重试。

**这里演示的是低负载下的客户端隔离与恢复，不是 API Server 容量压测，也不是所有版本通用的封禁方案。** Kubernetes 1.30.4 实测中，0 份额 Reject 仍会在空闲时放行请求，0 份额 Queue 才形成等待和拒绝；原因与版本源码见案例。

## 执行

依赖：Python 3、requests、kubectl。目标 kubeconfig 需要内嵌 CA，调用者需要创建专用 Namespace、RBAC、TokenRequest 和 APF 对象的权限。使用显式 context，先阅读 YAML 确认作用范围。

```bash
python3 -m venv /tmp/apf-case-venv
/tmp/apf-case-venv/bin/pip install requests
/tmp/apf-case-venv/bin/python examples/kubernetes-flow-control/apf-case/run_case.py \
  --context YOUR_TEST_CONTEXT \
  --output-dir /tmp/apf-case-results \
  --phase-seconds 90
```

脚本拒绝使用已经存在的 `apf-case` Namespace、`apf-case-batch` FlowSchema/优先级对象。它创建两个 ServiceAccount，仅授予读取本例 ConfigMap 的权限，校验响应中 FlowSchema/优先级 UID 确认实际分类，再开始实验。连续三个对照请求失败或超过 2 秒会中止实验。

正常结束或 Python 异常时，finally 恢复执行份额并清理本例 APF 对象与 Namespace。SIGKILL、机器断电或集群不可达时不能保证自动清理；确认对象确实属于本次实验后，用下列命令清理：

```bash
kubectl --context YOUR_TEST_CONTEXT delete \
  flowschema/apf-case-batch prioritylevelconfiguration/apf-case-batch
kubectl --context YOUR_TEST_CONTEXT delete namespace apf-case
```

本例不配置生产 APF 默认对象、不修改 API Server 启动参数，也不安装集群监控。ServiceMonitor、Prometheus 和 Grafana 需要事先准备。案例实测采集间隔为 15 秒，实验后恢复为 60 秒；源码不自动改动已有采集规则。

## 输出与解释

- `requests.jsonl`：每次请求的阶段、状态码、客户端耗时、实际分类匹配结果及 Retry-After。
- `events.json`：策略应用与阶段切换的实际时间。
- `summary.json`：按阶段、账号统计状态码和客户端分位数。

请求按开始时间所属阶段归类；跨恢复边界后成功的请求仍算作 Queue 阶段的请求。策略 apply 返回不等于所有请求瞬间切换，边界响应保留在结果中。客户端耗时包括网络、APF 和服务处理；Prometheus 的 APF 等待只度量其中一部分。

`normal.yaml` 中 5 表示名义份额，实际席位取决于集群其他优先级配置。实验中使用 1 个队列和队列长度 2，便于展示边界，不能当作生产公平队列参数建议。
