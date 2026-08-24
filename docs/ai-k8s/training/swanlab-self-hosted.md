---
title: SwanLab 自托管：从 Kubernetes 部署到真实 SFT 指标
description: 在 Kubernetes 部署 SwanLab，接入 ms-swift，区分实验追踪与基础设施监控，并用 Qwen3.5、Qwen3.6 MoE 和 DeepSeek V4 的真实 SFT 验证指标链路
status: evolving
last_reviewed: 2026-08-24
---

# SwanLab 自托管：从 Kubernetes 部署到真实 SFT 指标

训练日志能写进 TensorBoard，只解决了“曲线在哪里看”的问题。多人共享训练平台后，还需要项目、Run、超参数、标签、实验对比、权限和长期检索。SwanLab 可以承担这层实验追踪，但它不替代 Prometheus、DCGM Exporter 和 Grafana。

本文记录一套可公开复用的 Kubernetes 部署与 ms-swift 接入方法，并用真实 `Qwen3.5-4B`、`Qwen3.6-35B-A3B` 和 `DeepSeek V4 Flash` LoRA SFT 验证从训练容器到 Web 曲线的完整链路。文中不包含企业内部的集群、镜像仓库、存储端点、域名或入口配置。

## 1. 先划清系统边界

SwanLab 自托管版不是一个只读取日志目录的单容器。官方 Kubernetes Chart 包含 Gateway、前端、Server、Auth、House、PostgreSQL、Redis、ClickHouse、Vector 和 S3 兼容对象存储。

```text
ms-swift / PyTorch
  -> SwanLab SDK -> Gateway
                    -> Server / Auth -> PostgreSQL
                    -> House / Vector -> ClickHouse
                    -> 媒体与制品 -> S3 兼容对象存储

Kubernetes / DCGM Exporter / NIC
  -> Prometheus -> Grafana
```

两条链路解决不同问题：

| 系统 | 主要回答的问题 |
| --- | --- |
| SwanLab | 哪次 Run、哪些超参数、Loss 如何变化、不同实验有什么差异 |
| Prometheus + Grafana | GPU、显存、功耗、慢 Rank、节点、RDMA 和 Kubernetes 是否健康 |

生产中应使用统一的 `run_id`、`job_id`、模型版本和 Git Commit 对齐两类数据。

## 2. 使用官方 Helm Chart

先查询当前 Chart 与应用版本，不要长期照抄文章中的历史标签：

```bash
helm repo add swanlab https://helm.swanlab.cn
helm repo update
helm search repo swanlab/self-hosted --versions
```

建议先把 Chart 拉到本地，完成 Lint、渲染和变更审查：

```bash
helm pull swanlab/self-hosted --untar --untardir ./charts
helm lint ./charts/self-hosted -f values.yaml --strict

helm upgrade --install swanlab-self-hosted ./charts/self-hosted \
  --namespace swanlab \
  --create-namespace \
  -f values.yaml \
  --dry-run
```

确认渲染结果中的镜像、资源、持久卷、Service 和安全配置后再安装：

```bash
helm upgrade --install swanlab-self-hosted ./charts/self-hosted \
  --namespace swanlab \
  --create-namespace \
  -f values.yaml
```

可编辑的公开 Values 模板位于 [`examples/llm-sft-lab/swanlab/values.example.yaml`](https://github.com/runzhliu/aik8s/blob/main/examples/llm-sft-lab/swanlab/values.example.yaml)。其中的域名、StorageClass、容量和副本数都只是占位或起点，必须按实际环境修改。

受限网络环境应把官方固定标签镜像同步到受控 Registry，并记录源、目标 Digest。不要在生产集群临时构建同名镜像，也不要使用漂移的 `latest`。

## 3. 临时 PoC 与生产部署不同

短期 PoC 可以在隔离环境把 PostgreSQL、Redis、ClickHouse、Vector 和对象存储目录改为 `emptyDir`。它适合验证镜像、组件依赖、数据库迁移、页面和 SDK 链路，但必须明确：Pod 被替换后，账号、实验和曲线都可能丢失。

生产部署至少需要：

- 持久 PostgreSQL、ClickHouse 和对象存储；
- 明确的备份、恢复、RPO、RTO 和保留周期；
- HTTPS、身份认证、访问控制和 Secret 管理；
- 资源 Request/Limit、反亲和性和故障域规划；
- 按实验数、标量频率、媒体文件和保留时间做容量估算；
- 在升级前验证数据库迁移与回滚路径。

如果组织已有托管数据库或对象存储，应评估把有状态依赖外置，而不是默认把所有组件都运行在同一个 Kubernetes 集群。

## 4. 入口与首次激活

`global.settings.host` 应填写用户实际访问的外部 URL。入口可以由组织已有的 Ingress、Gateway 或零信任访问层提供；本文不展开企业内部的跨集群网络和域名实现。

社区自托管版首次访问会进入 `/activation`。完成实例激活、创建主账号后，在设置页生成训练专用 API Key。不要复用管理员密码，也不要把 API Key 写进镜像、脚本或 Git。

训练工作目录可以执行项目级登录：

```bash
python -m pip install 'swanlab>=0.8,<1'
swanlab login --host https://swanlab.example.com --local
```

共享主机要避免把凭据保存到所有用户共用的 Home。Kubernetes Job 更适合通过 Secret 注入：

```yaml
env:
  - name: SWANLAB_API_KEY
    valueFrom:
      secretKeyRef:
        name: swanlab-api-key
        key: api-key
```

Secret 只保存敏感 Key；API Host、Project 和 Experiment Name 使用普通配置，并限制 ServiceAccount 的 Secret 读取范围。

## 5. 接入 ms-swift

ms-swift SFT 使用 `report_to`、Project 和 Experiment Name 连接 SwanLab：

```bash
TRAIN_REPORT_TO=swanlab \
TRAIN_SWANLAB_PROJECT=llm-sft-lab \
TRAIN_SWANLAB_EXP_NAME=qwen35-4b-lora \
bash train.sh
```

对应的核心参数是：

```text
--report_to swanlab
--swanlab_project llm-sft-lab
--swanlab_exp_name qwen35-4b-lora
```

仓库提供两类复现入口：

- [`smoke.py`](https://github.com/runzhliu/aik8s/blob/main/examples/llm-sft-lab/swanlab/smoke.py)：不申请 GPU，只验证 SDK、Gateway、存储和 Web；
- [`meaningful-sft`](https://github.com/runzhliu/aik8s/tree/main/examples/llm-sft-lab/meaningful-sft)：运行真实 LoRA，并比较 Base 与 Adapter 的隔离盲测。

合成 Smoke 只能证明指标通路可用，不能作为模型训练效果。

## 6. 已验证的 Kubernetes PoC

2026 年 8 月 21 日使用官方 Chart `0.6.2`、SwanLab `v3.1.1` 和 Kubernetes 1.30 完成一次短期 PoC：10 个 Deployment、1 个 StatefulSet 和 1 个初始化 Job 正常工作，11 个常驻 Pod 全部 Ready 且无重启；数据库迁移、对象存储 Bucket 初始化、Gateway 页面和 API 均通过。

激活后，训练镜像内置的 SwanLab SDK `0.8.4` 创建了一个 6-Step 合成 Run，成功上传 39 条 Loss、Learning Rate 和 Tokens/s 记录。这证明了：

```text
训练容器 -> SDK -> Gateway -> 数据组件 -> Web
```

这轮 PoC 使用临时卷，不代表数据耐久性已经通过生产验收。

## 7. 真实 Qwen3.5-4B SFT 验证

同日又使用单张 L20 完成 `Qwen3.5-4B + BF16 LoRA`：330 条训练、55 条验证、110 条盲测，120 Step 耗时 612.6 秒，框架记录峰值显存 9.33 GiB。Validation Loss 在 Step 60 最低，因此盲测选择 Step 60 Adapter。

SwanLab 能显示 Train Loss、Gradient Norm、Learning Rate、Token Accuracy 和四次 Validation：

![Qwen3.5-4B 的真实训练曲线](../../assets/training/qwen35-4b-sft/swanlab-train-curves.png)

![Qwen3.5-4B 的真实验证曲线](../../assets/training/qwen35-4b-sft/swanlab-eval-curves.png)

| 110 条盲测指标 | Base | Step 60 Adapter |
| --- | ---: | ---: |
| JSON 合法率 | 99.1% | 100% |
| 自定义故障码准确率 | 0% | 77.3% |
| 故障码 Macro-F1 | 0% | 75.3% |
| 信息不足判断准确率 | 51.8% | 100% |
| 禁止动作关键字覆盖 | 5.5% | 88.2% |

完整训练参数、数据 Hash 和机器可读结果见 [Qwen3.5 小规模 SFT 实验](https://github.com/runzhliu/aik8s/tree/main/examples/llm-sft-lab/meaningful-sft)。Loss 曲线与盲测必须同时保留：前者说明优化过程，后者才回答模型行为是否改善。

随后一轮 `Qwen3.6-35B-A3B + 8 × L20 + ZeRO-3 LoRA` 也完成了 120 Step 和四次 Validation，SwanLab 保存的 Step 30/60/90/120 Validation Loss 分别为 `0.34289/0.06315/0.06051/0.05915`，最后一步 Token Accuracy 为 `98.98%`。这证明较大的多卡 Run 也能持续上传数值指标，并正常进入 `FINISHED` 状态。

这轮同时暴露了实验生命周期缺口：模型 Checkpoint、Adapter 和预测文件都使用临时任务目录没有问题，但 Base/Adapter 的最终汇总也只留在本地；任务清理后便无法恢复。正确做法是在退出前把少量数值指标和数据 Hash 上传 SwanLab，模型权重和预测原文仍可保持不持久化。公开结果因此只记录训练与 Validation，不推断盲测提升。机器可读记录见 [Qwen3.6-35B-A3B 实测](https://github.com/runzhliu/aik8s/blob/main/examples/llm-sft-lab/meaningful-sft/results/l20-qwen36-35b-a3b-20260821.json)。

2026 年 8 月 24 日，`DeepSeek V4 Flash 0731 + 8 × H20 + EP=8` 的 20-Step LoRA 又成功上传 1797 条 SwanLab 记录。Train Loss 从 Step 1 的 `1.3384` 降到 Step 20 的 `0.2692`，Step 5/10/15/20 的 Validation Loss 为 `0.9755/0.6041/0.4238/0.3469`，四个 Checkpoint 全部生成。这个 Run 证明实验追踪链路可以覆盖完整 MoE 的 Expert Parallel 训练，而不只适用于单卡 Dense 模型。

![DeepSeek V4 Flash 0731 的真实训练与验证 Loss](../../assets/training/deepseek-v4-flash-0731/loss-curves.svg)

这次同样保留边界：曲线来自真实数值记录，但 110 条隔离 Blind Test 尚未完成 Base/Adapter A/B，所以只能证明训练与验证优化过程，不宣称任务准确率已经提升。机器可读记录见 [DeepSeek V4 Flash 0731 实测](https://github.com/runzhliu/aik8s/blob/main/examples/llm-sft-lab/meaningful-sft/results/h20-deepseek-v4-flash-0731-20260824.json)。

## 8. 本次发现的兼容问题

训练镜像中的 SDK `0.8.4` 与较新的文档和 ms-swift 输出存在两个差异：

1. `swanlab.login()` 不接受新版文档中的 `web_host` 参数；接入代码必须以镜像内真实 SDK 签名为准。
2. ms-swift 4.4.1 会把 `30/120`、`3m 53s` 等展示字段作为 String Scalar 上报，SDK 0.8.4 会拒绝这些字符串。

第二项不影响数值型 Loss、Accuracy、Learning Rate、Gradient Norm、训练、Checkpoint 或盲测，但日志中会出现兼容性错误。升级 SDK 或训练镜像时应把这些场景加入回归，而不是只检查 `import swanlab`。

## 9. 验收清单

- 所有应用和依赖 Pod Ready，初始化 Job 成功；
- 数据库迁移完成，Gateway 首页与 API 返回预期状态；
- 最小 Run 能持续写入标量并正常结束；
- 同一项目的两次 Run 可以比较超参数和曲线；
- 真实 SFT 同时保存训练曲线、Validation、Checkpoint 和 Base/Adapter 盲测；
- 截图之外保存模型版本、数据 Hash、训练参数和机器可读结果；
- 公开截图裁掉内部域名、用户名、Run URL、节点名和敏感日志；
- API Key 不出现在 Git、镜像、命令行参数、Pod Spec 和日志中；
- 生产环境完成 Pod 重建、备份恢复和升级回滚演练；
- SwanLab 与 Prometheus/Grafana 使用相同的 Run、Job、模型和版本标识。

## 参考资料

- [SwanLab Kubernetes 部署](https://docs.swanlab.cn/self_host/kubernetes/deploy.html)
- [SwanLab 私有服务登录](https://docs.swanlab.cn/api/cli-swanlab-login.html)
- [ms-swift 命令行参数](https://github.com/modelscope/ms-swift/blob/main/docs/source/Instruction/Command-line-parameters.md)
