---
title: MLOps 与平台工程
description: 流水线、实验、模型注册、GitOps 与内部平台 API
status: evolving
last_reviewed: 2026-08-02
---

# MLOps 与平台工程

Kubernetes 能保证声明的工作负载持续运行，但不会自动回答“这个模型由哪份数据和代码产生”“谁批准上线”“质量是否退化”。MLOps 的任务是把研究过程、制品、部署和反馈闭合成可追溯的工程系统。

## 一、推荐的职责分层

```text
开发体验        Notebook / IDE / Python SDK / CLI
流程编排        Kubeflow Pipelines / Argo Workflows / Flyte
实验与治理      MLflow / Model Registry / Evaluation / Metadata
计算执行        Job / TrainJob / RayJob / JobSet
在线服务        KServe / Ray Serve / vLLM / Triton
持续交付        GitHub Actions / Argo CD / Flux
平台治理        RBAC / Kueue / Policy / Secrets / Cost
可观测性        Prometheus / DCGM / Logs / Traces / LLM Evaluation
```

平台应提供稳定接口，把工具封装成少量“黄金路径”，而不是让每个项目自行组合十几个组件。

## 二、可复现需要六个版本

一次训练或推理至少应关联：

1. **代码版本**：Git Commit；
2. **运行环境**：容器镜像 Digest，而不是可变 Tag；
3. **数据版本**：对象存储 URI、Lakehouse Snapshot 或 Dataset Manifest；
4. **配置版本**：参数、资源、运行时和队列策略；
5. **模型版本**：权重、Tokenizer、量化和 Adapter；
6. **评估版本**：评估集、Scorer、Prompt 与阈值。

只有模型文件而缺少上述关联，通常无法可靠复现，也无法解释线上差异。

## 三、流水线怎么选

| 工具 | 优势 | 适合团队 |
| --- | --- | --- |
| Kubeflow Pipelines | ML 组件、缓存、元数据和 Kubeflow 体验集成 | 已使用 Kubeflow 的数据科学团队 |
| Argo Workflows | Kubernetes 原生、通用 DAG、并行和 Artifact | 平台工程团队，希望同时编排数据、训练和运维 |
| Flyte | 强类型输入输出、版本化 Task、数据感知 | 大型 ML/Data 团队和复杂依赖 |
| Airflow | 调度生态和数据连接器丰富 | 已有成熟 Airflow 数据平台 |
| Tekton / CI 系统 | 构建和交付擅长 | 镜像、配置和发布；不建议承担全部训练实验编排 |

Argo Workflows 需要配置 Artifact Repository，生产中通常使用 S3 兼容对象存储，而不是在 Pod 间传递大文件或长期依赖 PVC。

参考：[Argo Workflows](https://argoproj.github.io/argo-workflows/)、[Artifact Repository](https://argoproj.github.io/argo-workflows/configure-artifact-repository/)

## 四、实验追踪和模型注册

MLflow Tracking 记录 Run 的参数、指标、数据引用和制品；Model Registry 负责模型版本、别名、标签和晋级状态。推荐把职责分开：

- 对象存储保存模型、评估结果和大型 Artifact；
- PostgreSQL 等数据库保存 Run 与 Registry 元数据；
- MLflow Server 提供 API/UI；
- Kubernetes Job UID、Workflow UID 和 MLflow Run ID 相互写入标签。

模型注册不等于部署。一个清晰的状态流可以是：

```text
Candidate → Offline Evaluated → Security Checked
          → Staging → Canary → Production → Retired
```

晋级应产生 Git 中可审计的部署变更，由 GitOps 控制器应用到集群，而不是由 Notebook 直接修改生产 Deployment。

参考：[MLflow Tracking](https://mlflow.org/docs/latest/ml/tracking/)、[MLflow Model Registry](https://mlflow.org/docs/latest/ml/model-registry/workflow)

## 五、CI、Pipeline 和 GitOps 的边界

### CI

- 单元测试、静态检查和依赖漏洞扫描；
- 构建并签名容器镜像；
- 生成 SBOM；
- 对基础模型、Prompt 或配置运行快速评估。

### ML Pipeline

- 数据准备、训练、批评估和模型制品生成；
- 可能运行数小时或数天；
- 需要 GPU 队列、重试、Checkpoint 和实验元数据。

### GitOps

- 声明生产环境应运行的模型版本和配置；
- 检测 Drift，执行同步和回滚；
- 不负责训练模型本身。

将长时间训练直接塞进普通 CI Runner，或让训练 Pipeline 持有生产集群管理员权限，都是常见反模式。

## 六、多租户设计

| 控制面 | 推荐边界 |
| --- | --- |
| 身份 | 企业 IdP/OIDC 映射到 Kubernetes 用户和组 |
| Namespace | 团队或环境边界，不建议每次 Run 创建永久 Namespace |
| 计算配额 | Kueue Queue/Quota 管 GPU，ResourceQuota 管常规资源对象 |
| 网络 | 默认拒绝 NetworkPolicy，按数据源和平台服务放行 |
| Secret | External Secrets / Vault / 云身份，避免长期静态密钥 |
| 制品 | 对象存储 Bucket/Prefix 与租户身份绑定 |
| 策略 | Kyverno/Gatekeeper 限制特权、HostPath、Tag、资源和镜像来源 |
| 成本 | Namespace、Queue、Team、Run 和 Model 标签统一 |

注意 Namespace 不是完整安全沙箱。能运行任意训练代码的用户可能访问节点内核、设备 Driver 和共享网络，因此还要使用 Pod Security、Seccomp、最小权限 ServiceAccount 和受控 RuntimeClass。

## 七、三层可观测性

### 1. 基础设施层

- Node、CPU、内存、磁盘、网络；
- GPU SM、显存、功耗、温度、XID；
- Device Plugin/DRA Driver、Kueue、Scheduler 和 Autoscaler；
- Pod Pending、Eviction、OOM 和重启。

### 2. 工作负载层

- 训练 Step Time、Loss、Checkpoint 和 Rank 状态；
- 推理 TTFT、TPOT、Queue、Token Throughput、KV Cache；
- 模型加载、批处理、错误和超时。

### 3. 模型与业务层

- 准确率、召回率、漂移和数据质量；
- Prompt、Tool Call、LLM Trace、人工反馈；
- 每租户成功率、Token、成本和业务转化。

Prometheus、Grafana、Loki 和 OpenTelemetry 负责系统遥测；MLflow/Phoenix/Langfuse 等负责实验、生成式 AI Trace 或评估。基础设施健康不代表模型输出正确，两类告警不能混为一谈。

## 八、评估必须进入发布流程

传统模型常见指标是 Accuracy、F1、AUC 和校准；LLM 还需要：

- 任务成功率和结构化输出合法率；
- Groundedness、事实性和引用正确性；
- 安全、偏见、Prompt Injection 与数据泄漏测试；
- Tool Calling 成功率和副作用控制；
- 延迟、Token、费用和模型降级策略；
- 人工反馈与线上失败样本回流。

评估集、Scorer 和 Judge Model 都要版本化。若 Judge Model 变化，不能直接与历史得分比较。MLflow 已分别提供传统 ML 与 GenAI 评估入口；两类评估对象和指标语义应明确区分。

参考：[MLflow Evaluation](https://mlflow.org/docs/latest/ml/evaluation)、[MLflow LLM 与 Agent 能力](https://www.mlflow.org/docs/latest/)

## 九、平台 API 应该长什么样

一个好的平台接口只暴露用户真正需要的字段：

```yaml
kind: AIWorkload
spec:
  type: training
  runtime: pytorch-fsdp
  image: registry.example.com/team/model@sha256:...
  dataset: s3://datasets/example/manifest-v12.json
  resources:
    workers: 4
    gpuPerWorker: 8
    flavor: h100-80g
  queue: research
  checkpoint: s3://checkpoints/project-a/
  experiment: churn-model
```

平台再将它转换为 TrainJob、Kueue Workload、NetworkPolicy、ServiceAccount 和监控规则。这个例子是接口设计思路，不是建议再发明一个无边界的大型 CRD；如果现有 TrainJob/RayJob 已满足需求，优先直接提供模板和 SDK。

## 十、成熟度阶梯

| 等级 | 特征 | 下一步 |
| --- | --- | --- |
| L0：手工运行 | `kubectl apply`、本地日志、模型手工复制 | 镜像化、实验追踪和基础监控 |
| L1：可重复 | Pipeline、MLflow、对象存储、固定镜像 | 注册审批与 GitOps |
| L2：可治理 | 多租户、队列、策略、Canary、成本归属 | 自动评估与故障演练 |
| L3：自助平台 | 黄金路径、SDK、Runtime Catalog、SLO | 容量预测、跨集群和自动优化 |
| L4：闭环优化 | 线上反馈、自动评估、策略化发布和成本性能联合优化 | 持续审计与简化复杂度 |

成熟度不是安装组件的数量，而是一次变更能否被复现、解释、审批、观测和回滚。

## 十一、生产检查清单

- [ ] 代码、镜像、数据、配置、模型和评估均有不可变版本。
- [ ] Workflow、Kubernetes Job、MLflow Run 和模型版本可互相追踪。
- [ ] 长训练不依赖 CI Runner 生命周期。
- [ ] Notebook 无权直接修改生产服务。
- [ ] 模型晋级通过 Git 变更和审批完成。
- [ ] 租户的身份、网络、Secret、配额和制品权限相互隔离。
- [ ] 基础设施、工作负载、模型质量三层指标都有 Owner。
- [ ] 线上失败样本能安全回流到评估集。
- [ ] 清理策略覆盖 Pod、Workflow、模型、Artifact、日志和指标。
- [ ] 每个关键组件都有升级、备份和回滚 Runbook。
