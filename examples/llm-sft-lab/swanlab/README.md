# SwanLab 训练实验追踪

这个目录记录一套可公开复用的 SwanLab 私有化部署与训练接入方法。示例不包含内部集群、节点、镜像仓库、存储端点、域名、Secret 或跨集群入口实现。

## 组件与边界

SwanLab 自托管版不是一个只读取日志目录的单容器。当前官方 Kubernetes Chart 会部署 Gateway、前端、Server、Auth、House、PostgreSQL、Redis、ClickHouse、Vector 和 S3 兼容对象存储。它适合管理项目、实验、超参数、Loss 曲线和运行对比；Prometheus、DCGM Exporter 与 Grafana 仍负责 GPU、节点和网络指标。

## 官方 Helm 安装

先检查当前 Chart 与应用版本，不要长期依赖文档中的历史版本号：

```bash
helm repo add swanlab https://helm.swanlab.cn
helm repo update
helm search repo swanlab/self-hosted --versions
```

复制并修改 [`values.example.yaml`](values.example.yaml)，先把 Chart 拉到本地做 Lint 和渲染，再安装：

```bash
helm pull swanlab/self-hosted --untar --untardir ./charts
helm lint ./charts/self-hosted -f values.example.yaml --strict

helm upgrade --install swanlab-self-hosted ./charts/self-hosted \
  --namespace swanlab \
  --create-namespace \
  -f values.example.yaml \
  --dry-run

helm upgrade --install swanlab-self-hosted ./charts/self-hosted \
  --namespace swanlab \
  --create-namespace \
  -f values.example.yaml
```

受限网络环境应把官方固定标签镜像复制到组织内 Registry，并记录源 Digest 与目标 Digest；不要在生产集群临时拉取或重新构建同名镜像。外部地址通过组织已有的认证 Gateway/Ingress 暴露，`global.settings.host` 必须填写用户实际访问的 URL。本文不包含任何企业内部的镜像同步、存储或入口配置。

## 临时 PoC 与生产部署

官方 Chart 默认使用持久化组件。若只想短期验证页面，可以在隔离环境把 PostgreSQL、Redis、ClickHouse、Vector 和对象存储卷替换为 `emptyDir`，但这不是生产方案：任一 Pod 被重建都可能丢失部分状态并破坏组件间一致性。测试完成后应整体销毁，不要在该实例积累需要保留的实验。

生产部署至少应使用持久数据库、持久对象存储、备份恢复、HTTPS、访问控制和资源限制。SwanLab 官方文档建议 Vector 使用足够的缓冲空间，并支持把 PostgreSQL、Redis、ClickHouse 与 S3 切换为外部托管服务。容量应按实验数、日志频率、标量列数、媒体文件和保留周期估算，而不是照抄 PoC 的小规格。

## 首次激活与训练接入

SwanLab 社区自托管版首次访问会进入 `/activation`。个人使用可从 SwanLab 官网申请免费 License；激活主账号后，在设置页创建 API Key。

训练目录执行：

```bash
python -m pip install 'swanlab>=0.8,<1'
swanlab login --host https://swanlab.example.com --local
```

ms-swift SFT 使用：

```bash
TRAIN_REPORT_TO=swanlab \
TRAIN_SWANLAB_PROJECT=llm-sft-lab \
TRAIN_SWANLAB_EXP_NAME=qwen3-4b-lora-smoke \
bash ../train-qwen3-4b-lora.sh
```

Kubernetes Job 不应把 API Key 直接写进环境值。先创建专用 Secret，再在训练容器中引用；下面只有结构，不包含真实凭据：

```yaml
env:
  - name: SWANLAB_API_KEY
    valueFrom:
      secretKeyRef:
        name: swanlab-api-key
        key: api-key
```

## 已验证的兼容性 Smoke

2026 年 8 月 21 日使用官方 Chart `0.6.2`、服务端 `v3.1.1` 和 Kubernetes 1.30 完成了一轮短期 PoC：10 个 Deployment、1 个 StatefulSet、1 个初始化 Job 正常工作，11 个常驻 Pod 全部 Ready 且无重启，数据库迁移、对象存储 Bucket 初始化、Gateway 页面和 API 均通过。

激活后，使用现有训练镜像内置的 SwanLab SDK `0.8.4` 创建了一个 6 Step 合成实验，成功上传 39 条记录，包括 `train/loss`、Learning Rate 和 Tokens/s，Run 页面可正常打开。这证明了 `训练容器 -> SDK -> Gateway -> 存储 -> Web` 链路，但不代表真实模型训练质量。

Smoke 还发现，镜像内 `0.8.4` 的 `swanlab.login()` 不接受当前文档所列的 `web_host` 参数。接入时要以训练镜像内的实际 SDK 为准；每次升级镜像或服务端后，至少回归登录、创建 Run、连续写入指标、结束 Run 和打开页面。

随后又使用同一链路完成一次真实 `Qwen3.5-4B + BF16 LoRA`：120 Step 训练和四次 Validation 指标均可查看，最佳 Checkpoint 由 Validation Loss 选在 Step 60，110 条盲测的自定义故障码准确率由 Base 的 0% 提升到 Adapter 的 77.3%。这次真实 Run 还发现，ms-swift 4.4.1 会把 `30/120`、`3m 53s` 等展示字段作为字符串上报，SDK 0.8.4 拒绝 String Scalar；Loss、Accuracy、Learning Rate、Gradient Norm 等数值型指标不受影响。

完整参数、脱敏曲线和机器可读盲测结果见 [`meaningful-sft/README.md`](../meaningful-sft/README.md)。合成 Smoke 用于检查链路，真实 SFT + 隔离盲测才用于讨论训练效果。

仓库中的 [`smoke.py`](smoke.py) 可以复现这条指标链路，它只生成合成指标，不申请 GPU：

```bash
export SWANLAB_API_HOST=https://swanlab.example.com
export SWANLAB_API_KEY='<从 Secret 或安全凭据工具注入>'
python smoke.py
```

不要把真实 Key 保存到 Shell 脚本或提交到 Git。Kubernetes 中应从 `secretKeyRef` 注入 API Key，API Host 使用普通配置，并给 Smoke Job 设置较短的完成后回收时间。

至少确认 `train/loss`、`eval/loss`、Learning Rate、Gradient Norm、Token Accuracy 和 Step/Elapsed Time 随训练推进；再与 Grafana 中相同时间窗的 GPU 利用率、显存、功耗和网络指标对齐。Loss 下降只能说明训练目标在当前数据上改善，不能替代隔离评测和 Base/Adapter A/B。

## 验收清单

- 所有应用和依赖 Pod Ready，初始化 Job 成功；
- 数据库迁移完成，Gateway 首页与 API 都返回预期状态；
- 创建一次最小 Run，标量曲线能持续写入并正常结束；
- 同一项目中的两次 Run 可以比较超参数和曲线；
- 总结真实 SFT 时保存 Run 概览、Loss/Learning Rate、吞吐或 Step Time 截图；
- 截图之外同时保存模型版本、数据 Hash、训练参数和机器可读结果；
- 公开截图已裁掉内部域名、用户名、Run URL、节点名和敏感日志；
- API Key 不出现在 Git、命令历史、Pod Spec 和日志中；
- Pod 重建和备份恢复演练符合声明的数据保留目标；
- SwanLab 与 Prometheus/Grafana 使用同一 Run、Job、模型和版本标识。

参考：[SwanLab Kubernetes 部署](https://docs.swanlab.cn/self_host/kubernetes/deploy.html)、[SwanLab 私有服务登录](https://docs.swanlab.cn/api/cli-swanlab-login.html)、[ms-swift 日志参数](https://github.com/modelscope/ms-swift/blob/main/docs/source/Instruction/Command-line-parameters.md)。
