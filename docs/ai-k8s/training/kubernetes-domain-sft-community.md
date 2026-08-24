---
title: Kubernetes 领域 SFT：社区案例、数据集与可执行评测
description: 分析 KubeFix、K8s Distill、KubeBench、ITBench 等社区实践，解释 Kubernetes 文档问答、Manifest 生成和故障诊断应怎样准备数据、训练模型并完成可信评测
status: evolving
last_reviewed: 2026-08-24
---

# Kubernetes 领域 SFT：社区案例、数据集与可执行评测

社区已经出现了一批面向 Kubernetes 问答、`kubectl` 命令、Manifest 生成和故障诊断的 SFT 项目，但成熟度差异很大。有的公开了数据生成、LoRA 和模型导出流程，有的只有模型卡或项目介绍，还有不少所谓的“Kubernetes 大模型”实际上使用的是 RAG、工具调用或 Agent，并没有训练 Kubernetes 领域模型。

先给出本文的判断：

- **最适合复现完整 SFT 流水线的是 KubeFix**，但它也证明了“从官方文档合成问答”并不足以获得可靠的故障诊断能力；
- **最值得借鉴的数据方法是 K8s Distill**，因为训练样本先经过外部验证器，而不是只相信教师模型；
- **最值得借鉴的 Manifest 评测是 KubeBench**，它把生成结果提交给 Kubernetes 控制面验证，而不只比较文字相似度；
- **最适合做故障诊断盲测的是 ITBench**，它提供事件、日志、指标、调用轨迹和集群对象状态，但它不是拿来直接训练的干净 SFT 问答集；
- 面向生产故障的正确路线通常不是纯 SFT，而是 **SFT 固化行为与输出协议，RAG 和只读工具提供实时事实，Agent 负责编排调查过程**。

如果还不熟悉 LoRA、Epoch、Checkpoint 和 Train/Validation/Test 的区别，建议先读[大模型 SFT 入门](sft-concepts.md)。本文重点回答另一个问题：**训练一个真正懂 Kubernetes 的模型，社区做到了什么，我们应该怎样验证它。**

## 1. 先区分两种完全不同的“Kubernetes SFT”

搜索社区资料时，经常会遇到标题相似、目标完全不同的项目：

```text
在 Kubernetes 上做 SFT
  └─ Kubernetes 只是训练作业运行平台
     例如：在 GPU Pod 中训练通用 Alpaca 数据

对 Kubernetes 知识和任务做 SFT
  └─ Kubernetes 是模型要学习和解决的领域
     例如：生成 Deployment、诊断 ImagePullBackOff
```

本文只分析第二类。把一个通用模型训练 Job 部署到 Kubernetes，并不能让模型获得 Kubernetes 能力。

还要继续区分四种能力，因为它们的数据、风险和验收方法不同：

| 能力 | 输入示例 | 输出示例 | 适合 SFT 吗 | 如何客观验证 |
| --- | --- | --- | --- | --- |
| 概念问答 | `Service 和 Ingress 有什么区别？` | 原理、边界和示例 | 适合，但知识易受版本影响 | 人工题库、来源引用、版本一致性 |
| 命令生成 | `查看某个 Pod 最近的事件` | `kubectl describe...` | 很适合 | 命令解析、只读/写操作分类、沙箱执行 |
| Manifest 生成 | `创建限制资源的 Deployment` | Kubernetes YAML | 很适合 | Schema、策略、Dry Run、实际创建 |
| 故障诊断 | Event、日志、指标和对象状态 | 根因、证据、下一步动作 | 只能解决一部分 | 故障注入、实体定位、证据覆盖和安全检查 |

前三类输入通常比较静态，最后一类依赖当前集群的动态事实。一个仅靠参数记忆的模型不知道某个 Pod 此刻为什么 Pending，也不知道当前集群安装了哪个 CNI。它必须读取真实证据。

## 2. 社区项目全景

| 项目 | 任务 | 公开数据与模型 | 评测特点 | 可复现性 | 更适合借鉴什么 |
| --- | --- | --- | --- | --- | --- |
| [KubeFix](https://github.com/andyburgin/kubefix-llm) | 文档问答、解释 K8sGPT 诊断 | 2,564 条 Alpaca 数据；Phi-3 Mini LoRA/GGUF | 少量人工问题评分 | 较高 | 数据生成、清洗、LoRA、GGUF 全流程 |
| [K8s Distill Pilot](https://arxiv.org/abs/2605.25835) | Kubernetes YAML 生成 | 1,200/100/200；Qwen2.5-Coder-1.5B | 外部验证器；论文报告 full-pass@1 91.5% | 中等偏低 | 先验证再进入训练集、严格输出协议 |
| [KubeBench](https://www.ischool.berkeley.edu/projects/2025/kubebench-domain-expert-code-writing-ai-comprehensive-benchmark-kubernetes-llms) | 资源 Manifest 生成 | 16 个以上、0.5B 至 8B QLoRA 模型 | Schema、集群部署、运行正确性三阶段验证 | 当前偏低 | 把“能被集群接受”纳入评测 |
| [ITBench](https://github.com/itbench-hub/ITBench) | Kubernetes SRE 故障定位 | 场景、集群快照、Ground Truth、Agent 轨迹 | 根因实体、传播链和告警解释 | 较高，但运行较重 | 真实感故障诊断盲测 |
| Hugging Face 小型数据集 | 问答、命令和修复建议 | 数百至约两万条 | 多数没有可靠盲测 | 不一 | 作为数据种子，不应直接当结论 |

这里的“可复现性”不是评价模型效果好坏，而是判断公开资料能否让第三方重建数据、训练和评测。模型权重可以下载，不代表训练结论可以复现。

## 3. KubeFix：最完整，也最能说明文档问答的边界

[KubeFix](https://github.com/andyburgin/kubefix-llm)的目标是从 Kubernetes 官方英文文档生成问答数据，再对小模型做微调，最终接入 K8sGPT 的故障分析流程。它公开了数据生成脚本、Notebook、数据集和 GGUF 模型，因此特别适合作为第一个社区复现实验。

它的主要流程是：

```text
Kubernetes 官方 Markdown 文档
        ↓
OpenChat 生成 Question / Answer
        ↓
修复非法 JSON、去重、删除无意义样本
        ↓
2,564 条 Alpaca 格式数据
        ↓
Phi-3-mini-4k-instruct + LoRA，训练 1 Epoch
        ↓
合并权重并导出 q4_k_m GGUF
        ↓
本地 CPU / LocalAI / K8sGPT 调用
```

公开的 [KubeFix 数据集](https://huggingface.co/datasets/andyburgin/kubefix)包含 `instruction`、`input`、`output` 和原始文档路径，采用 CC BY 4.0。这种“保留来源”的做法很重要，它允许后续检查某条答案属于哪个 Kubernetes 版本和页面。

更重要的是，作者并没有把合成数据描述成天然可靠的数据。他记录了非法 JSON、重复问题和无意义回答等问题，并进行了较多人工修复。这带来三个经验：

1. 教师模型输出必须通过格式和内容检查，不能直接写入训练集；
2. 从同一段文档生成的相似问答必须按来源分组切分，否则测试集会泄漏；
3. 文档版本必须被记录，否则模型可能同时学到已经废弃和当前有效的 API。

KubeFix 的小规模人工评测显示，微调模型相对 Base 有改善，但总体诊断表现仍不理想。这个结果很有价值：**问答 SFT 更容易改善术语、回答风格和事实回忆，不会自动得到基于 Event、日志和指标进行根因定位的能力。**

因此，KubeFix 适合复现数据流水线，不适合直接作为“可以替代 Kubernetes SRE”的证据。

## 4. K8s Distill：训练数据先通过验证器

2026 年 5 月提交的预印本 [Context-Instrumental Data Distillation for Kubernetes Manifest Generation](https://arxiv.org/abs/2605.25835)研究了如何让 1B 至 4B 小模型生成 Kubernetes Manifest。

它的实验设计包括：

- 教师模型使用 DeepSeek-V4 Flash API；
- 学生模型使用 Qwen2.5-Coder-1.5B-Instruct；
- 使用 LoRA，在资源受限环境中完成微调；
- Pilot 数据划分为 1,200 条训练、100 条验证和 200 条测试；
- 只有通过外部验证器并符合领域上下文的数据对才能进入训练集；
- 论文报告在严格提示词和 `max_new_tokens=768` 下，`full-pass@1` 达到 91.5%，即 200 条中通过 183 条。

这里最值得复制的不是 91.5% 这个单一数字，而是下面的数据门禁：

```text
教师生成 Instruction + YAML
        ↓
能否解析为 YAML？
        ↓
是否符合 Kubernetes Schema？
        ↓
资源 Kind、字段和值是否满足题目约束？
        ↓
通过：进入训练候选集
失败：修复、重新生成或丢弃
```

论文还观察到，严格限定输出格式对结果的影响，可能大于简单增加训练样本数量。这说明在比较 Base 和 Adapter 时，必须固定 System Prompt、解码参数和最大输出长度；否则看到的差异可能来自推理配置，而不是 SFT。

需要保留的限制是：该项目目前主要以预印本形式公开，完整训练制品的可获得性不如 KubeFix。因此它更适合被当作方法设计参考，不能只根据论文指标断言第三方环境也能达到相同效果。

## 5. KubeBench：不要用文本相似度评估 YAML

[KubeBench](https://www.ischool.berkeley.edu/projects/2025/kubebench-domain-expert-code-writing-ai-comprehensive-benchmark-kubernetes-llms)面向 Kubernetes 资源生成，使用 QLoRA 训练了 16 个以上、参数规模从 0.5B 到 8B 的模型。项目介绍称，数据来自 Kubernetes 文档和开源 YAML，并对生成结果执行三阶段验证：

1. **Schema Compliance**：字段和类型是否合法；
2. **Cluster Deployment**：Manifest 能否被 Kubernetes 控制面接受并创建；
3. **Operational Correctness**：查询实际资源状态，再检查任务要求是否满足。

这比比较标准答案和模型输出的字符串更合理。例如以下两段 YAML 字段顺序不同，但含义可以完全一致；反过来，一段与标准答案文本高度相似的 YAML，也可能引用不存在的 Secret 或使用已废弃 API。

KubeBench 的公开介绍报告了执行有效性和 YAML 质量的提升，并指出较小模型受益更明显。但截至本文复核时，[公开仓库](https://github.com/naomatheus/kubebench-public)主要提供项目说明，没有看到足以一键重建数据、训练和完整评测的制品。因此本文把这些数字视为项目方报告结果，不把它们当作独立复现结论。

我们应该复制的是三阶段执行评测，而不是复制一组无法在相同条件下验证的百分比。

## 6. ITBench：不是标准 SFT 数据，却更接近真实故障诊断

[ITBench](https://github.com/itbench-hub/ITBench)面向 SRE、FinOps 和安全等 IT 自动化任务。它的 Kubernetes SRE 场景通过故障注入构造环境，并提供告警、Event、Metrics、Trace、日志和 Kubernetes 对象状态，要求 Agent 找到故障实体和传播关系。

[ITBench Trajectories](https://huggingface.co/datasets/ibm-research/ITBench-Trajectories)当前公开 35 个 SRE 场景的 105 条完整运行轨迹，每个场景运行三次，并附带根因定位的 Precision、Recall、F1 等指标。数据采用 CC BY-NC 4.0，商业用途需要特别检查许可证边界。

2026 年公开的 [ITBench-AA](https://huggingface.co/datasets/ArtificialAnalysis/ITBench-AA)进一步整理了 40 个公开 Kubernetes Incident 场景。每个场景的 Ground Truth 描述了故障、告警、实体组、传播图和建议修复方案。公开分析显示，即使前沿模型面对这种需要读取多类证据的任务，得分也远没有达到可以无审查自治运维的程度。

这些 Agent 轨迹不能原样当作 SFT 标准答案，原因包括：

- 轨迹中可能包含试错、无效工具调用和绕路步骤；
- 某次最终答案正确，不代表此前每一步推理都值得学习；
- 调查顺序可能依赖特定工具、监控栈和环境快照；
- 许可证可能不允许预期的商业使用方式；
- 如果训练集和测试集包含同一场景的不同运行，评测会发生泄漏。

更合理的用法是：

1. 优先把 ITBench 当作外部盲测集；
2. 从正确轨迹中提取“观察 → 下一步只读动作”的短样本；
3. 删除失败步骤、敏感内容和环境特有标识；
4. 按场景而不是按对话行进行 Train/Test 隔离；
5. 保留一批从未参与训练和提示词调优的场景作为最终测试。

## 7. Hugging Face 小数据集：可以取材，不能照单全收

### 7.1 K8s 概念问答

[ItshMoh/kubernetes_qa_pairs](https://huggingface.co/datasets/ItshMoh/kubernetes_qa_pairs)包含约 500 条英文问答，提供主题、类型和难度字段。它适合教学型问答和数据格式演示，但规模小、没有天然独立的验证与测试划分，也不能验证实时故障诊断。

### 7.2 kubectl 命令

[dereklck/kubernetes_cli_dataset_20k](https://huggingface.co/datasets/dereklck/kubernetes_cli_dataset_20k)包含接近两万条指令和命令，但能看到大量机械模板，例如只替换节点名的 `cordon`、`uncordon` 和只替换 Pod 名的 `describe`。

这种数据最容易制造虚假的高分：

```text
Train:  cordon node worker-001
Test:   cordon node worker-002
```

随机按行切分时，模型几乎看过同一个答案。正确做法是先把命令归一化为模板，再按模板族切分：

```text
kubectl cordon <NODE>
kubectl describe pod <POD> -n <NAMESPACE>
kubectl rollout restart deployment <NAME> -n <NAMESPACE>
```

整个模板只能出现在 Train 或 Test 的一边。

### 7.3 故障问答和修复对话

- [pavanmantha/devops-v1](https://huggingface.co/datasets/pavanmantha/devops-v1)是数百条 Docker/Kubernetes 故障问答，采用 Apache 2.0，适合作为案例线索；
- [northriverfence/varxipod-k8s-remediation](https://huggingface.co/datasets/northriverfence/varxipod-k8s-remediation)包含 112 条 Kubernetes Remediation 对话，采用 Apache 2.0，格式接近工具型 Agent，但规模很小；
- [kubernetes_operator_3b_peft_gguf](https://huggingface.co/dereklck/kubernetes_operator_3b_peft_gguf)展示了 Llama 3.2 3B、Unsloth、TRL、LoRA 和 GGUF 的训练结果，并强调信息不足时先澄清，但没有充分的 Base/Adapter 盲测结果。

这些数据可以提供问题类型和输出格式，不能跳过人工复核、版本检查、去重和重新构造盲测集。

## 8. 为什么 Kubernetes 故障诊断不能只做 SFT

SFT 擅长训练稳定行为：

- 面对什么症状先检查什么；
- 如何把证据、根因和动作组织成结构化输出；
- 信息不足时应该澄清，而不是编造；
- 默认只提出只读操作，变更操作需要确认；
- 禁止输出或自动执行高风险命令。

SFT 不擅长提供动态事实：

- 当前 Pod 的 Event；
- 当前集群的 Kubernetes、CNI、CSI 和 GPU 驱动版本；
- 过去十分钟的 GPU、网络、存储和应用指标；
- 私有镜像仓库、Namespace、ResourceQuota 和发布历史；
- 某个 CRD 是否已经安装、字段是否和文档版本一致。

因此，生产形态应该是：

```text
用户问题或告警
      ↓
SFT 模型：识别意图、规划调查步骤、遵循安全协议
      ↓
只读工具：读取 Object / Event / Log / Metric / Trace
      ↓
RAG：补充当前版本文档、Runbook 和历史事故
      ↓
模型：引用证据，给出根因、置信度和下一步动作
      ↓
策略层：拦截高风险操作，要求人工确认并保留审计
```

这也是为什么 K8sGPT、HolmesGPT 或各类 Kubernetes Copilot 的存在，不能单独证明它们训练了 Kubernetes 领域模型。它们可能主要依赖 Prompt、RAG、通用模型和集群工具完成任务。

## 9. 一套可以落地的数据设计

相比把多个社区数据集直接拼在一起，更稳妥的方案是建立三个数据层。

### 9.1 概念与版本知识

每条样本至少保留：

```json
{
  "task_type": "concept_qa",
  "kubernetes_version": "v1.34",
  "source_url": "https://kubernetes.io/docs/...",
  "source_revision": "git-commit-or-date",
  "question": "...",
  "answer": "..."
}
```

这部分用于学习术语、边界和解释方式。发生版本升级后，可以按 `kubernetes_version` 找到需要重新生成或废弃的样本。

### 9.2 命令和 Manifest

命令类样本需要增加风险级别：

```json
{
  "task_type": "kubectl_command",
  "request": "查看 web Namespace 中 api Pod 的最近事件",
  "answer": "kubectl describe pod api -n web",
  "operation": "read",
  "requires_confirmation": false,
  "validator": "command-policy-v1"
}
```

Manifest 类样本应保存验证结果，而不是只有模型答案：

```json
{
  "task_type": "manifest_generation",
  "request": "创建一个非 root、带 CPU/内存限制的 Deployment",
  "answer": "apiVersion: apps/v1\n...",
  "validators": {
    "yaml_parse": true,
    "schema": true,
    "server_dry_run": true,
    "policy": true
  }
}
```

### 9.3 故障诊断

诊断样本不能只给一句症状和一句结论。至少应该包含观察到的证据和允许的下一步动作：

```json
{
  "task_type": "incident_diagnosis",
  "symptom": "Pod 处于 ImagePullBackOff",
  "observations": [
    "FailedToRetrieveImagePullSecret",
    "Secret registry-auth not found"
  ],
  "expected": {
    "fault_code": "IMAGE_PULL_SECRET_NOT_FOUND",
    "evidence": ["Secret registry-auth not found"],
    "diagnosis": "Pod 引用的镜像拉取 Secret 不存在",
    "next_readonly_action": "检查 Pod spec.imagePullSecrets 和 Namespace 中的 Secret",
    "requires_confirmation": true,
    "forbidden_action": "不得直接删除生产 Deployment"
  }
}
```

`fault_code` 应该来自有限、版本化的故障分类，而不是让每条答案自由创造名字。这样才能计算 Exact Match、混淆矩阵和各故障类型的召回率。

## 10. 训练集和测试集应该怎样切

Kubernetes 数据很容易发生四种泄漏：

| 泄漏 | 表现 | 正确隔离单元 |
| --- | --- | --- |
| 文档泄漏 | 同一文档段落生成多个相似问题 | 文档页面或章节 |
| 模板泄漏 | 只替换 Pod、Node、Namespace 名 | 归一化命令/YAML 模板 |
| 故障泄漏 | 同一种故障换一个工作负载名称 | 故障族或故障注入脚本 |
| 轨迹泄漏 | 同一场景的三次 Agent 运行分到两边 | 完整场景 ID |

推荐保留三组数据：

- **Train**：用于更新参数；
- **Validation**：用于选择 Epoch、学习率和 Checkpoint；
- **Blind Test**：训练和参数选择期间不可见，只在结果冻结后运行一次。

如果持续查看 Blind Test 并根据结果修改数据或参数，它就已经变成 Validation，需要重新准备新的 Blind Test。

## 11. 不只看 Loss：建立可执行评测

### 11.1 通用门禁

每次实验必须固定并记录：

- Base 模型和精确 Revision；
- Adapter、训练框架、依赖版本和数据版本；
- System Prompt、Chat Template 和 Tokenizer；
- Temperature、Top P、最大输入和最大输出长度；
- Train/Validation/Test 的分组策略；
- Base 与 Adapter 使用完全相同的推理参数。

### 11.2 问答评测

- 核心事实是否正确；
- 是否引用正确版本的来源；
- 不确定时是否明确表达不确定性；
- 是否虚构 API、字段、组件或命令参数。

### 11.3 命令安全评测

- 命令能否解析；
- Namespace、资源类型和参数是否正确；
- 是否把只读请求错误转换为写操作；
- `delete`、`drain`、`scale`、`patch`、`rollout restart` 等动作是否要求确认；
- 出现管道、重定向、Shell 展开时是否触发更严格审查。

### 11.4 Manifest 执行评测

```text
YAML Parse
   ↓
kubeconform / Kubernetes OpenAPI Schema
   ↓
Policy：资源限制、SecurityContext、镜像和权限
   ↓
kubectl apply --server-side --dry-run=server
   ↓
临时 Namespace 实际创建
   ↓
查询资源状态与题目约束
   ↓
清理测试 Namespace
```

执行有效不等于生产安全。例如一个 `privileged: true` 的 Pod 可能创建成功，却应该在策略阶段失败。

### 11.5 故障诊断评测

建议分别统计：

- 根因实体定位 Precision、Recall、F1；
- `fault_code` Accuracy 和按故障类型的 Recall；
- 必要证据覆盖率；
- 错误归因和无依据结论比例；
- 下一步只读调查动作成功率；
- 高风险动作未确认率，出现一次即可判定安全门禁失败；
- 从开始调查到定位根因的工具调用数和总 Token。

最终报告必须同时展示 Base 和 Adapter。只有 Adapter Loss 下降，没有 Base/Adapter 盲测和执行验证，不能证明领域能力提升。

## 12. 基于现有实验的建议路线

仓库已经用 `Qwen3.5-4B + LoRA` 跑通过故障分类训练、Adapter 推理和 Base/Adapter 盲测，配套记录见[SFT 训练实战](sft-from-single-gpu-to-deepseek-v4.md)。在此基础上，没有必要先换成更大的模型，应该先升级数据和评测。

推荐顺序如下：

### 阶段一：复现社区基线

- 使用 KubeFix 复现文档问答数据流水线；
- 不追求复现作者的绝对分数，重点验证来源保留、清洗和分组切分；
- 对 Base 与 Adapter 使用相同的 50 至 100 条隔离问答。

### 阶段二：做可执行 Manifest SFT

- 从 Deployment、Service、ConfigMap、Secret 和 RBAC 中选择有限资源类型；
- 每条合成数据必须通过 YAML、Schema、Policy 和 Server-Side Dry Run；
- 按任务模板切分，禁止只替换名称制造测试集；
- 比较 Base 与 Adapter 的全通过率和安全失败率。

### 阶段三：做受控故障诊断

- 在隔离测试集群中注入 ImagePull、Probe、资源不足、调度、DNS、网络和存储故障；
- 保存脱敏后的 Object、Event、Log 和 Metric 快照；
- 让模型输出固定 `fault_code`、证据、诊断和下一步只读动作；
- 整个故障族只进入 Train 或 Blind Test 的一边；
- 使用 ITBench 或另一批独立注入场景进行外部评测。

### 阶段四：再增加 Agent 和安全策略

- SFT 模型只生成调查计划和结构化工具调用；
- 默认只开放 `get`、`list`、`describe`、`logs` 和指标查询；
- 所有写操作进入审批层；
- 用错误工具输出、超时、权限拒绝和证据冲突测试模型的恢复能力；
- 记录每次工具调用和最终结论，形成后续可审查的数据闭环。

## 13. 如何判断一个社区 Kubernetes SFT 项目是否可信

看到新的模型或文章时，可以按下面的顺序检查：

1. 它是“在 Kubernetes 上训练”，还是“训练 Kubernetes 领域能力”？
2. 数据是否公开，许可证是否允许目标用途？
3. 数据来源、Kubernetes 版本和生成方法是否可追溯？
4. 是否做了语义去重和按模板/场景切分？
5. 是否同时报告 Base 和 Adapter？
6. 推理 Prompt 和解码参数是否一致？
7. YAML 和命令是否真正执行验证，而不是只由另一个 LLM 打分？
8. 故障诊断是否读取 Event、日志、指标等真实证据？
9. 是否有从未参与开发的 Blind Test？
10. 是否把高风险操作、确认机制和审计纳入评分？

如果只有训练 Loss、几段漂亮对话和一个可下载 Adapter，最多说明训练链路跑通，不能说明模型已经具备可靠的 Kubernetes 运维能力。

## 14. 结论

社区已经证明，小模型可以通过 SFT 更稳定地生成 Kubernetes 命令和 Manifest，也能在受限分类任务上获得明显提升。但目前没有足够证据表明，仅用文档问答或少量故障对话微调，就能得到可无审查处理生产事故的 Kubernetes 专家模型。

一条更可信的路线是：

```text
KubeFix 的可追溯数据流水线
        +
K8s Distill 的验证器门禁
        +
KubeBench 的控制面执行评测
        +
ITBench 的故障场景与根因指标
        ↓
SFT 固化格式、调查策略和安全边界
        ↓
RAG 与只读工具提供实时、私有和版本化事实
        ↓
Base / Adapter / Agent 三层对照实验
```

对 Kubernetes 领域 SFT 来说，训练多少 Step 不是最难的问题。真正决定结果可信度的是：数据能否追溯、测试是否隔离、输出能否执行验证，以及模型在不知道答案时是否会停下来继续取证。

## 参考资料

- [KubeFix GitHub](https://github.com/andyburgin/kubefix-llm)
- [KubeFix Dataset](https://huggingface.co/datasets/andyburgin/kubefix)
- [KubeBench 项目介绍](https://www.ischool.berkeley.edu/projects/2025/kubebench-domain-expert-code-writing-ai-comprehensive-benchmark-kubernetes-llms)
- [KubeBench Public Repository](https://github.com/naomatheus/kubebench-public)
- [Context-Instrumental Data Distillation for Kubernetes Manifest Generation](https://arxiv.org/abs/2605.25835)
- [ITBench](https://github.com/itbench-hub/ITBench)
- [ITBench Trajectories](https://huggingface.co/datasets/ibm-research/ITBench-Trajectories)
- [ITBench-AA](https://huggingface.co/datasets/ArtificialAnalysis/ITBench-AA)

