---
title: "Kubernetes Domain SFT: Community Cases, Datasets, and Executable Evaluation"
description: "Analyze community practices such as KubeFix, K8s Distill, KubeBench, and ITBench, and explain how to prepare data, train models, and complete trustworthy evaluation for Kubernetes documentation Q&A, Manifest generation, and troubleshooting"
status: evolving
last_reviewed: 2026-08-24
---

# Kubernetes Domain SFT: Community Cases, Datasets, and Executable Evaluation

The community has already produced a number of SFT projects aimed at Kubernetes Q&A, `kubectl` commands, Manifest generation, and troubleshooting, but maturity varies widely. Some have published data generation, LoRA, and model export pipelines; others have only model cards or project introductions. In addition, many so-called "Kubernetes large models" actually use RAG, tool calling, or Agents, and have not trained a Kubernetes domain model.

Here is this article's assessment first:

- **The best fit for reproducing a complete SFT pipeline is KubeFix**, but it also proves that "synthesizing Q&A from official documentation" is not sufficient to obtain reliable troubleshooting capability;
- **The most worthwhile data methodology to learn from is K8s Distill**, because training samples first pass through an external validator rather than relying only on the teacher model;
- **The most worthwhile Manifest evaluation to learn from is KubeBench**, because it submits generated results to the Kubernetes control plane for validation, rather than only comparing textual similarity;
- **The best fit for blind troubleshooting testing is ITBench**, because it provides events, logs, metrics, call traces, and cluster object state, but it is not a clean SFT Q&A set for direct training;
- The correct route for production troubleshooting is usually not pure SFT, but rather **SFT to solidify behavior and output protocols, RAG and read-only tools to provide real-time facts, and an Agent to orchestrate the investigation process**.

If you are not yet familiar with the differences between LoRA, Epoch, Checkpoint, and Train/Validation/Test, we recommend first reading [Large Model SFT Introduction](sft-concepts.md). This article focuses on answering a different question: **for training a model that truly understands Kubernetes, what has the community achieved, and how should we verify it.**

## 1. First Distinguish Two Completely Different Kinds of "Kubernetes SFT"

When searching community materials, you will often encounter projects with similar titles but completely different goals:

```text
在 Kubernetes 上做 SFT
  └─ Kubernetes 只是训练作业运行平台
     例如：在 GPU Pod 中训练通用 Alpaca 数据

对 Kubernetes 知识和任务做 SFT
  └─ Kubernetes 是模型要学习和解决的领域
     例如：生成 Deployment、诊断 ImagePullBackOff
```

This article only analyzes the second kind. Deploying a general model training Job to Kubernetes does not give the model Kubernetes capability.

We also need to further distinguish four capabilities, because their data, risks, and acceptance methods differ:

| Capability | Input Example | Output Example | Suitable for SFT? | How to Objectively Verify |
| --- | --- | --- | --- | --- |
| Conceptual Q&A | `Service 和 Ingress 有什么区别？` | Principles, boundaries, and examples | Suitable, but knowledge is easily affected by version | Human question bank, source citation, version consistency |
| Command generation | `查看某个 Pod 最近的事件` | `kubectl describe...` | Very suitable | Command parsing, read-only/write operation classification, sandbox execution |
| Manifest generation | `创建限制资源的 Deployment` | Kubernetes YAML | Very suitable | Schema, policy, Dry Run, actual creation |
| Troubleshooting | Event, logs, metrics, and object state | Root cause, evidence, next actions | Can only solve part of it | Fault injection, entity localization, evidence coverage, and safety checks |

The inputs for the first three categories are usually relatively static; the last category depends on the dynamic facts of the current cluster. A model that relies only on parametric memory does not know why a given Pod is Pending at this moment, nor which CNI is installed in the current cluster. It must read real evidence.

## 2. Community Project Overview

| Project | Task | Public Data and Models | Evaluation Characteristics | Reproducibility | What Is More Worth Learning From |
| --- | --- | --- | --- | --- | --- |
| [KubeFix](https://github.com/andyburgin/kubefix-llm) | Documentation Q&A, explaining K8sGPT diagnostics | 2,564 Alpaca records; Phi-3 Mini LoRA/GGUF | Small-scale human question scoring | Relatively high | Full pipeline of data generation, cleaning, LoRA, GGUF |
| [K8s Distill Pilot](https://arxiv.org/abs/2605.25835) | Kubernetes YAML generation | 1,200/100/200; Qwen2.5-Coder-1.5B | External validator; paper reports full-pass@1 91.5% | Medium to low | Validate before entering training set, strict output protocol |
| [KubeBench](https://www.ischool.berkeley.edu/projects/2025/kubebench-domain-expert-code-writing-ai-comprehensive-benchmark-kubernetes-llms) | Resource Manifest generation | 16+ models, 0.5B to 8B QLoRA | Three-stage validation: Schema, cluster deployment, runtime correctness | Currently low | Incorporate "acceptable to the cluster" into evaluation |
| [ITBench](https://github.com/itbench-hub/ITBench) | Kubernetes SRE fault localization | Scenarios, cluster snapshots, Ground Truth, Agent trajectories | Root cause entity, propagation chain, and alert explanation | Relatively high, but heavy to run | Realistic blind troubleshooting testing |
| Hugging Face small datasets | Q&A, commands, and remediation suggestions | Hundreds to approximately twenty thousand records | Most lack reliable blind testing | Varies | Use as data seeds, not as conclusions directly |

"Reproducibility" here does not evaluate whether the model performs well, but rather whether public materials allow a third party to rebuild the data, training, and evaluation. Model weights being downloadable does not mean the training conclusions can be reproduced.

## 3. KubeFix: The Most Complete, and Also the Best Illustration of the Boundaries of Documentation Q&A

[KubeFix](https://github.com/andyburgin/kubefix-llm)'s goal is to generate Q&A data from the official Kubernetes English documentation, then fine-tune a small model, and finally integrate it into K8sGPT's fault analysis pipeline. It has published data generation scripts, Notebooks, datasets, and GGUF models, making it especially suitable as the first community reproduction experiment.

Its main pipeline is:

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

The public [KubeFix dataset](https://huggingface.co/datasets/andyburgin/kubefix) contains `instruction`, `input`, `output`, and the original documentation path, under CC BY 4.0. This practice of "preserving the source" is important, because it allows later inspection of which Kubernetes version and page a given answer belongs to.

More importantly, the author did not describe the synthetic data as naturally reliable. He recorded problems such as invalid JSON, duplicate questions, and meaningless answers, and performed a considerable amount of manual repair. This yields three lessons:

1. Teacher model output must pass format and content checks; it cannot be written directly into the training set;
2. Similar Q&A generated from the same documentation segment must be split by source group; otherwise the test set will leak;
3. Documentation versions must be recorded; otherwise the model may simultaneously learn both deprecated and currently valid APIs.

KubeFix's small-scale human evaluation shows that the fine-tuned model improves relative to Base, but overall diagnostic performance remains unsatisfactory. This result is valuable: **Q&A SFT more easily improves terminology, answer style, and factual recall, but does not automatically yield the ability to perform root cause localization based on Events, logs, and metrics.**

Therefore, KubeFix is suitable for reproducing the data pipeline, but not suitable as direct evidence that it "can replace a Kubernetes SRE."

## 4. K8s Distill: Training Data First Passes Through a Validator

The preprint [Context-Instrumental Data Distillation for Kubernetes Manifest Generation](https://arxiv.org/abs/2605.25835), submitted in May 2026, studies how to make 1B to 4B small models generate Kubernetes Manifests.

Its experimental design includes:

- Teacher model uses the DeepSeek-V4 Flash API;
- Student model uses Qwen2.5-Coder-1.5B-Instruct;
- Uses LoRA, completing fine-tuning in resource-constrained environments;
- Pilot data is split into 1,200 training, 100 validation, and 200 test records;
- Only data pairs that pass the external validator and conform to the domain context enter the training set;
- The paper reports that under strict prompts and `max_new_tokens=768`, `full-pass@1` reaches 91.5%, meaning 183 of 200 pass.

The most worthwhile thing to copy here is not the single number 91.5%, but the following data gate:

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

The paper also observes that strictly constraining the output format may have a greater impact on results than simply increasing the number of training samples. This shows that when comparing Base and Adapter, the System Prompt, decoding parameters, and maximum output length must be fixed; otherwise, the observed differences may come from inference configuration rather than SFT.

Limitations that must be retained: this project is currently mainly published as a preprint, and the availability of complete training artifacts is not as good as KubeFix. Therefore, it is more suitable as a methodology design reference; one cannot assert based only on the paper's metrics that third-party environments can achieve the same results.

## 5. KubeBench: Do Not Evaluate YAML with Textual Similarity

[KubeBench](https://www.ischool.berkeley.edu/projects/2025/kubebench-domain-expert-code-writing-ai-comprehensive-benchmark-kubernetes-llms) targets Kubernetes resource generation, training 16+ models ranging from 0.5B to 8B parameters using QLoRA. The project introduction states that data comes from Kubernetes documentation and open-source YAML, and that generated results undergo three-stage validation:

1. **Schema Compliance**: whether fields and types are valid;
2. **Cluster Deployment**: whether the Manifest can be accepted and created by the Kubernetes control plane;
3. **Operational Correctness**: query the actual resource state, then check whether the task requirements are satisfied.

This is more reasonable than comparing strings between the standard answer and the model output. For example, the following two YAML segments have different field order but can be completely identical in meaning; conversely, a YAML segment with high textual similarity to the standard answer may reference a nonexistent Secret or use a deprecated API.

KubeBench's public introduction reports improvements in execution validity and YAML quality, and notes that smaller models benefit more visibly. However, as of this article's review, the [public repository](https://github.com/naomatheus/kubebench-public) mainly provides project descriptions, and no artifacts sufficient for one-click reconstruction of data, training, and complete evaluation were found. Therefore, this article treats these numbers as results reported by the project team, not as independently reproduced conclusions.

What we should copy is the three-stage execution evaluation, not a set of percentages that cannot be verified under identical conditions.

## 6. ITBench: Not Standard SFT Data, but Closer to Real Troubleshooting

[ITBench](https://github.com/itbench-hub/ITBench) targets IT automation tasks such as SRE, FinOps, and security. Its Kubernetes SRE scenarios construct environments through fault injection and provide alerts, Events, Metrics, Traces, logs, and Kubernetes object state, requiring the Agent to find the faulty entity and propagation relationships.

[ITBench Trajectories](https://huggingface.co/datasets/ibm-research/ITBench-Trajectories) currently publishes 105 complete run trajectories across 35 SRE scenarios, with each scenario run three times, along with metrics such as Precision, Recall, and F1 for root cause localization. The data is under CC BY-NC 4.0, and commercial use requires special attention to license boundaries.

[ITBench-AA](https://huggingface.co/datasets/ArtificialAnalysis/ITBench-AA), published in 2026, further organizes 40 public Kubernetes Incident scenarios. Each scenario's Ground Truth describes the fault, alerts, entity groups, propagation graph, and recommended remediation. Public analysis shows that even frontier models, when facing this kind of task that requires reading multiple types of evidence, score far below the level needed for unsupervised autonomous operations.

These Agent trajectories cannot be used as-is as SFT standard answers, for reasons including:

- Trajectories may contain trial-and-error, invalid tool calls, and detour steps;
- A final answer being correct does not mean every preceding reasoning step is worth learning;
- The investigation order may depend on specific tools, monitoring stacks, and environment snapshots;
- The license may not permit the intended commercial use;
- If the training set and test set contain different runs of the same scenario, evaluation will leak.

A more reasonable usage is:

1. Treat ITBench primarily as an external blind test set;
2. Extract short "observation → next read-only action" samples from correct trajectories;
3. Remove failed steps, sensitive content, and environment-specific identifiers;
4. Perform Train/Test isolation by scenario rather than by conversation line;
5. Reserve a batch of scenarios that never participated in training or prompt tuning as the final test.

## 7. Hugging Face Small Datasets: Can Be Used as Material, but Not Taken Wholesale

### 7.1 K8s Conceptual Q&A

[ItshMoh/kubernetes_qa_pairs](https://huggingface.co/datasets/ItshMoh/kubernetes_qa_pairs) contains approximately 500 English Q&A pairs, providing topic, type, and difficulty fields. It is suitable for teaching-style Q&A and data format demonstration, but the scale is small, there is no naturally independent validation and test split, and it cannot validate real-time troubleshooting.

### 7.2 kubectl Commands

[dereklck/kubernetes_cli_dataset_20k](https://huggingface.co/datasets/dereklck/kubernetes_cli_dataset_20k) contains nearly twenty thousand instructions and commands, but a large number of mechanical templates are visible, such as `cordon`, `uncordon` that only replace the node name, and `describe` that only replaces the Pod name.

This kind of data most easily produces false high scores:

```text
Train:  cordon node worker-001
Test:   cordon node worker-002
```

When splitting randomly by row, the model has almost seen the same answer. The correct approach is to first normalize commands into templates, then split by template family:

```text
kubectl cordon <NODE>
kubectl describe pod <POD> -n <NAMESPACE>
kubectl rollout restart deployment <NAME> -n <NAMESPACE>
```

An entire template may only appear on one side of Train or Test.

### 7.3 Troubleshooting Q&A and Remediation Conversations

- [pavanmantha/devops-v1](https://huggingface.co/datasets/pavanmantha/devops-v1) is several hundred Docker/Kubernetes troubleshooting Q&A pairs, under Apache 2.0, suitable as case leads;
- [northriverfence/varxipod-k8s-remediation](https://huggingface.co/datasets/northriverfence/varxipod-k8s-remediation) contains 112 Kubernetes Remediation conversations, under Apache 2.0, with a format close to tool-based Agents, but very small in scale;
- [kubernetes_operator_3b_peft_gguf](https://huggingface.co/dereklck/kubernetes_operator_3b_peft_gguf) demonstrates training results for Llama 3.2 3B, Unsloth, TRL, LoRA, and GGUF, and emphasizes clarifying when information is insufficient, but lacks sufficient Base/Adapter blind test results.

These data can provide problem types and output formats, but cannot skip manual review, version checking, deduplication, and reconstruction of blind test sets.

## 8. Why Kubernetes Troubleshooting Cannot Rely Only on SFT

SFT is good at training stable behaviors:

- What to check first given what symptoms;
- How to organize evidence, root cause, and actions into structured output;
- Clarify when information is insufficient, rather than fabricate;
- Default to proposing only read-only operations; changes require confirmation;
- Prohibit outputting or automatically executing high-risk commands.

SFT is not good at providing dynamic facts:

- The current Pod's Events;
- The current cluster's Kubernetes, CNI, CSI, and GPU driver versions;
- GPU, network, storage, and application metrics from the past ten minutes;
- Private image registry, Namespace, ResourceQuota, and release history;
- Whether a given CRD is installed, and whether fields match the documentation version.

Therefore, the production form should be:

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

This is also why the existence of K8sGPT, HolmesGPT, or various Kubernetes Copilots cannot by itself prove that they trained a Kubernetes domain model. They may primarily rely on Prompts, RAG, general models, and cluster tools to complete tasks.

## 9. A Data Design That Can Be Put into Practice

Compared to directly concatenating multiple community datasets, a more robust approach is to establish three data layers.

### 9.1 Concept and Version Knowledge

Each sample should retain at least:

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

This section is for learning terminology, boundaries, and explanation conventions. After a version upgrade, use `kubernetes_version` to locate samples that need to be regenerated or deprecated.

### 9.2 Commands and Manifests

Command-type samples need an added risk level:

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

Manifest-type samples should save validation results rather than only the model's answer:

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

### 9.3 Fault Diagnosis

Diagnostic samples cannot consist of just one symptom sentence and one conclusion sentence. They should at least include observed evidence and permitted next actions:

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

`fault_code` should come from a finite, versioned fault taxonomy, rather than letting each answer freely invent names. Only then can Exact Match, confusion matrices, and per-fault-type recall be computed.

## 10. How to Split Training and Test Sets

Kubernetes data is prone to four types of leakage:

| Leakage | Manifestation | Correct Isolation Unit |
| --- | --- | --- |
| Document leakage | Multiple similar questions generated from the same document passage | Document page or section |
| Template leakage | Only Pod, Node, Namespace names are replaced | Normalized command/YAML template |
| Fault leakage | The same fault reappears under a different workload name | Fault family or fault injection script |
| Trajectory leakage | Three Agent runs of the same scenario are split across both sides | Full scenario ID |

Three data groups are recommended:

- **Train**: used for updating parameters;
- **Validation**: used for selecting Epoch, learning rate, and Checkpoint;
- **Blind Test**: not visible during training or parameter selection, run only once after results are frozen.

If you keep looking at the Blind Test and modify data or parameters based on its results, it has already become Validation, and a new Blind Test needs to be prepared.

## 11. Beyond Loss: Building Executable Evaluation

### 11.1 General Gates

Every experiment must fix and record:

- Base model and exact Revision;
- Adapter, training framework, dependency versions, and data version;
- System Prompt, Chat Template, and Tokenizer;
- Temperature, Top P, maximum input length, and maximum output length;
- Train/Validation/Test grouping strategy;
- Base and Adapter use exactly the same inference parameters.

### 11.2 Q&A Evaluation

- Whether the core facts are correct;
- Whether the correct version of the source is cited;
- Whether uncertainty is explicitly expressed when uncertain;
- Whether APIs, fields, components, or command parameters are fabricated.

### 11.3 Command Safety Evaluation

- Whether the command can be parsed;
- Whether Namespace, resource types, and parameters are correct;
- Whether read-only requests are incorrectly converted into write operations;
- Whether actions such as `delete`, `drain`, `scale`, `patch`, `rollout restart` require confirmation;
- Whether pipelines, redirection, or shell expansion trigger stricter review.

### 11.4 Manifest Execution Evaluation

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

Successful execution does not equal production safety. For example, a Pod with `privileged: true` may be created successfully, yet it should fail at the policy stage.

### 11.5 Fault Diagnosis Evaluation

It is recommended to separately measure:

- Root cause entity localization Precision, Recall, F1;
- `fault_code` Accuracy and per-fault-type Recall;
- Necessary evidence coverage;
- Proportion of incorrect attribution and unsupported conclusions;
- Success rate of next-step read-only investigation actions;
- Unconfirmed rate of high-risk actions — a single occurrence is enough to fail the safety gate;
- Number of tool calls and total tokens from the start of investigation to root cause localization.

The final report must present both Base and Adapter. A decrease in Adapter Loss alone, without Base/Adapter blind testing and execution validation, cannot prove improved domain capability.

## 12. Recommended Roadmap Based on Existing Experiments

The repository has already run fault classification training, Adapter inference, and Base/Adapter blind testing using `Qwen3.5-4B + LoRA`, with supporting records in [SFT Training Practice](sft-from-single-gpu-to-deepseek-v4.md). On this basis, there is no need to switch to a larger model first; the priority should be upgrading the data and evaluation.

The recommended order is as follows:

### Phase One: Reproduce the Community Baseline

- Use KubeFix to reproduce the document Q&A data pipeline;
- Do not aim to reproduce the authors' absolute scores; focus on verifying source retention, cleaning, and group splitting;
- Use the same 50 to 100 isolated Q&A items for both Base and Adapter.

### Phase Two: Executable Manifest SFT

- Select a limited set of resource types from Deployment, Service, ConfigMap, Secret, and RBAC;
- Every synthetic data item must pass YAML, Schema, Policy, and Server-Side Dry Run;
- Split by task template; creating a test set by only replacing names is prohibited;
- Compare the full pass rate and safety failure rate between Base and Adapter.

### Phase Three: Controlled Fault Diagnosis

- Inject ImagePull, Probe, resource insufficiency, scheduling, DNS, network, and storage faults in an isolated test cluster;
- Save desensitized Object, Event, Log, and Metric snapshots;
- Have the model output a fixed `fault_code`, evidence, diagnosis, and next read-only action;
- Each entire fault family goes into only one side of Train or Blind Test;
- Use ITBench or another independent set of injected scenarios for external evaluation.

### Phase Four: Add Agent and Safety Policies

- The SFT model only generates investigation plans and structured tool calls;
- By default, only `get`, `list`, `describe`, `logs`, and metric queries are enabled;
- All write operations go through an approval layer;
- Test the model's recovery capability with wrong tool outputs, timeouts, permission denials, and conflicting evidence;
- Record every tool call and final conclusion, forming an auditable data loop for later review.

## 13. How to Judge Whether a Community Kubernetes SFT Project Is Trustworthy

When seeing a new model or article, check in the following order:

1. Is it "trained on Kubernetes" or "trained for Kubernetes domain capability"?
2. Is the data public, and does the license permit the intended use?
3. Are the data sources, Kubernetes version, and generation method traceable?
4. Was semantic deduplication and template/scenario-based splitting performed?
5. Are both Base and Adapter reported?
6. Are the inference Prompt and decoding parameters consistent?
7. Are YAML and commands actually executed and validated, rather than only scored by another LLM?
8. Does fault diagnosis read real evidence such as Events, logs, and metrics?
9. Is there a Blind Test that never participated in development?
10. Are high-risk operations, confirmation mechanisms, and auditing included in scoring?

If there is only training Loss, a few polished conversations, and a downloadable Adapter, at most it shows that the training pipeline runs end to end; it does not show that the model has reliable Kubernetes operations capability.

## 14. Conclusion

The community has shown that small models can generate Kubernetes commands and Manifests more stably through SFT, and can also achieve clear improvements on constrained classification tasks. However, there is currently insufficient evidence that fine-tuning with document Q&A or a small number of fault conversations alone can produce a Kubernetes expert model capable of handling production incidents without review.

A more credible path is:

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

For Kubernetes-domain SFT, how many training steps to run is not the hardest question. What truly determines the credibility of results is: whether the data is traceable, whether the test sets are isolated, whether outputs can be executed and validated, and whether the model stops and continues gathering evidence when it does not know the answer.

## References

- [KubeFix GitHub](https://github.com/andyburgin/kubefix-llm)
- [KubeFix Dataset](https://huggingface.co/datasets/andyburgin/kubefix)
- [KubeBench Project Introduction](https://www.ischool.berkeley.edu/projects/2025/kubebench-domain-expert-code-writing-ai-comprehensive-benchmark-kubernetes-llms)
- [KubeBench Public Repository](https://github.com/naomatheus/kubebench-public)
- [Context-Instrumental Data Distillation for Kubernetes Manifest Generation](https://arxiv.org/abs/2605.25835)
- [ITBench](https://github.com/itbench-hub/ITBench)
- [ITBench Trajectories](https://huggingface.co/datasets/ibm-research/ITBench-Trajectories)
- [ITBench-AA](https://huggingface.co/datasets/ArtificialAnalysis/ITBench-AA)
