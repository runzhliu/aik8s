---
title: DeepSeek-V4-Flash-0731 的 H20 可部署性评估
description: 基于生产集群只读快照、CephFS 现有挂载方式和上游支持证据，评估 DeepSeek-V4-Flash-0731 在单节点八卡 H20 上的部署条件、风险与验证路径
status: exploratory
last_reviewed: 2026-08-10
---

# DeepSeek-V4-Flash-0731 的 H20 可部署性评估

本文记录一次**只读、探索性**评估：没有创建 Pod、修改调度配置、拉取镜像或加载模型。结论表示当前环境具备开展验证的条件，不表示模型已经在该生产集群通过功能、性能或稳定性验收。

!!! warning "公开文档已经脱敏"
    本文不会记录内部集群名、节点地址、Ceph monitor、模型卷真实路径、Registry、Namespace 或 Secret。资源数字保留用于说明判断依据，环境相关值统一使用 `<...>` 占位符。

## 1. 结论

**H20 可以作为 DeepSeek-V4-Flash-0731 的候选部署硬件，当前 H20 集群也存在满足首次验证需要的连续单节点八卡资源。推荐从单节点 `8 × H20 96 GB`、TP=8、Expert Parallel、32K 上下文、关闭 DSpark 的目标模型基线开始。**

判断置信度为“中等偏高”，理由如下：

- DeepSeek-V4-Flash-0731 是 304B 参数、约 13B 激活参数的 MoE 模型，融合检查点约 167 GB；八张 96 GB H20 的总显存容量明显高于权重体积，并能给 KV Cache、通信缓冲区和算子工作区留下空间。
- H20 属于 Hopper/SM90。vLLM 的 DeepSeek V4 路线中包含 H20 的 FP8 block-scaled GEMM 工作，上游问题也记录过 H20 上的 DeepSeek-V4-Flash-DSpark 目标模型成功加载和推理。
- 目标集群快照中有 16 台 Ready、未封锁、GPU 请求为 0 的八卡 H20/H20-3e 节点，不需要把模型拆到多机，也就不依赖跨节点 RDMA。
- 但是 vLLM 和 SGLang 的 0731 官方验证矩阵主要列出 H200、B200、GB300 等硬件，没有把 H20 列为正式验证平台。H20 上游成功记录针对的是结构相同的 Preview/DSpark 检查点，不能直接替代 0731 的集群实测。

因此，本次结论不是“直接生产发布”，而是：**可以进入受控 PoC；通过目标模型、长上下文、工具调用、DSpark 和稳定性门槛后，才能决定是否生产化。**

## 2. 模型带来的硬性条件

| 项目 | DeepSeek-V4-Flash-0731 条件 | 对部署的影响 |
| --- | --- | --- |
| 架构 | DeepSeek V4 MoE，304B 总参数、约 13B 激活参数 | 引擎必须原生支持 `deepseek_v4`，不能沿用只支持 DeepSeek V3/R1 的旧镜像 |
| 权重 | FP4 MoE experts + FP8 其余权重；融合 DSpark 检查点约 167 GB | 需要支持对应 FP4/FP8 kernel；磁盘体积不能直接等同于实际显存占用 |
| 上下文 | 配置上限 1,048,576 tokens | 首次验证不应直接开 1M；KV Cache、启动时间和延迟需要逐级测量 |
| 推理模式 | `low`、`high`、`max` 三档 reasoning effort | `high`/`max` 官方建议允许最多 384K 输出，完整能力验证至少需要 `max-model-len >= 393216` |
| Chat 编码 | 检查点不包含 Jinja chat template，提供独立 `encoding/` 实现 | OpenAI API 必须使用 DeepSeek V4 tokenizer、reasoning 和 tool-call parser，并测试异常输出解析 |
| 推测解码 | 检查点内含 DSpark draft module | NVIDIA 上需要 vLLM 0.25.0 或更新版本；先关闭 DSpark 建基线，再单独开启验证 |

已有的 vLLM 0.10.x 镜像太旧，不满足 DeepSeek V4 0731 和 DSpark 要求。首次实验应制作或确认一个专用的 vLLM 0.26.x 镜像，并在容器内核对 vLLM、PyTorch、CUDA、FlashInfer、DeepGEMM 和 DeepSeek V4 model implementation 的实际版本，不能只相信镜像标签。

## 3. 两个生产 GPU 池的只读快照

快照时间为 2026-08-10。GPU 空余量按活跃 Pod 的 `requests.nvidia.com/gpu` 计算，是调度视角的瞬时值，不代表 GPU 利用率，也不等于未来预留能力。

### 3.1 L20 集群：不适合作为首选

| 指标 | 只读快照 |
| --- | ---: |
| GPU 节点 / 总可分配 GPU | 77 / 616 |
| 活跃 Pod GPU requests | 565 |
| 名义空闲 GPU | 51 |
| Ready、未封锁且完整空闲的八卡节点 | 0 |
| 主要 GPU | NVIDIA L20，单卡约 48 GB |

51 张空闲 GPU 分散在多台节点：大部分节点只空闲 1 张或 2 张。另有一台保留 4 张空闲 GPU 的节点带离线污点，不能作为正常容量。即使总空闲卡数看起来足够，也无法组成推荐的单节点八卡拓扑。

更重要的是，L20 是 Ada/SM89。SGLang 对 SM89 的 DeepSeek V4 FP8 支持仍属于实验性上游工作，不能作为生产首选。因此不建议为了利用碎片卡而先走 L20 多机 TP/PP 路径。

### 3.2 H20 集群：具备单节点验证条件

| 指标 | 只读快照 |
| --- | ---: |
| GPU 节点 / 总可分配 GPU | 210 / 1,673 |
| 活跃 Pod GPU requests | 1,431 |
| 名义空闲 GPU | 242 |
| GPU requests 为 0 的八卡节点 | 27 |
| 其中 Ready、未封锁的完整八卡节点 | 24 |
| 其中 H20/H20-3e 完整八卡节点 | 16 |

这 16 台 H20 候选节点包括：

- 13 台标准 H20，DCGM 观测每卡约 94–95 GiB 空闲显存；
- 3 台 H20-3e，DCGM 观测每卡约 140 GiB 空闲显存。

候选节点不是一个无条件共享池。它们分别带有训练、LLM 训练或 LLM Serving 的 `quarantine-room` 污点，Pod 必须匹配准确的 toleration 和节点池约束。快照中最符合语义的 LLM Serving H20 96 GB 候选节点还剩约 338 CPU、1,287 GiB 内存和完整 8 GPU；该节点没有 RDMA 扩展资源，但单节点 TP=8 不要求跨机 RDMA。

观察窗口内另有一个请求 8 GPU 的 Volcano Gang 处于 Pending。它面向 H20 96 GB 训练池，不等于当前 Serving 节点不可用，但说明完整八卡容量会变化；开始任何实验前都必须重新检查 Pod requests、Queue/PodGroup 和池归属。

## 4. 推荐的首次验证拓扑

```text
OpenAI-compatible client
          │
          ▼
  vLLM API / Engine
          │
  单个 Kubernetes Pod
          │
  单台 H20 节点，8 GPU
  TP=8 + Expert Parallel
          │
  CephFS 只读模型目录
```

推荐顺序：

1. 优先使用 LLM Serving 池中的完整 `8 × H20 96 GB` 节点；H20-3e 可以提供更多上下文余量，但当前位于训练池，不应只为显存更大就跨池抢占。
2. 使用单 Pod、单节点、TP=8，避免多机网络、RDMA、Ray 和 Gang 调度同时进入问题空间。
3. 先运行 target-only，不启用 DSpark，不做 P/D 分离，也不直接追求 1M context。
4. 基线通过后再分别增加 DSpark、上下文长度和并发，每次只改变一个变量。

上游问题中曾在 H20 上用 TP=2 跑通结构相同的目标模型，但这只能证明 H20 kernel 路径存在，不能证明 TP=2 是生产最优。TP=8 能减少每卡权重和工作区压力，并利用现成完整八卡节点，因此是更保守的首次选择。

## 5. 建议资源边界

以下数字是 PoC 起点，不是容量承诺：

```yaml
resources:
  requests:
    cpu: "64"
    memory: 320Gi
    ephemeral-storage: 100Gi
    nvidia.com/gpu: "8"
  limits:
    cpu: "128"
    memory: 512Gi
    ephemeral-storage: 200Gi
    nvidia.com/gpu: "8"
```

同时提供至少 64–128 GiB 的 `/dev/shm`。Hugging Face、Torch、Triton 和编译缓存应写入容器临时盘，不能写回只读模型目录：

```yaml
env:
  - name: HF_HOME
    value: /tmp/huggingface
  - name: TRANSFORMERS_CACHE
    value: /tmp/huggingface/transformers
  - name: XDG_CACHE_HOME
    value: /tmp/.cache
```

这些 requests 在当前候选节点 CPU/内存余量内。真正的 GPU 显存水位需要以 vLLM 启动日志和 DCGM 为准，不能用 `167 GB / 8` 简单推导，因为 dense 层、expert 放置、KV Cache、CUDA Graph 和 kernel workspace 的分布并不相同。

## 6. CephFS 前置条件

现有 Namespace 已证明直接 CephFS 只读挂载模式可用，可复用它的结构，但不能假设同一 Secret 和 Ceph 网络在 H20 集群天然存在。

```yaml
volumeMounts:
  - name: model-store
    mountPath: /models
    readOnly: true

volumes:
  - name: model-store
    cephfs:
      monitors:
        - <CEPH_MONITOR_1>:<PORT>
        - <CEPH_MONITOR_2>:<PORT>
        - <CEPH_MONITOR_3>:<PORT>
      path: <READ_ONLY_MODEL_ROOT>
      readOnly: true
      secretRef:
        name: <CEPH_SECRET>
      user: <CEPH_USER>
```

在编写正式工作负载之前仍需只读确认：

1. H20 集群的目标 Namespace 已有正确的 Ceph Secret；
2. 节点网络能够访问全部 Ceph monitors；
3. `/models/DeepSeek-V4-Flash-0731` 目录存在，文件总量和 `config.json` 与上游检查点一致；
4. 容器 UID/GID 对目录有读取权限；
5. 多个 Rank 并行读取 167 GB 权重时，CephFS 吞吐不会导致启动探针误判；
6. 模型卷和 `volumeMount` 两层都保持 `readOnly: true`。

## 7. vLLM 探索参数

下面命令只用于记录建议参数，不应在生产集群直接执行。它先建立一个 32K、低并发、无推测解码的 target-only 基线：

```bash
vllm serve /models/DeepSeek-V4-Flash-0731 \
  --served-model-name deepseek-v4-flash-0731 \
  --trust-remote-code \
  --kv-cache-dtype fp8 \
  --block-size 256 \
  --enable-expert-parallel \
  --tensor-parallel-size 8 \
  --tokenizer-mode deepseek_v4 \
  --tool-call-parser deepseek_v4 \
  --enable-auto-tool-choice \
  --reasoning-parser deepseek_v4 \
  --gpu-memory-utilization 0.90 \
  --max-model-len 32768 \
  --max-num-seqs 4
```

这个命令参考 vLLM 的 0731 TP=8 recipe，但 32K 和并发 4 是本评估为了降低首次风险设置的保守值。不要在基线阶段增加 `deep_gemm_mega_moe`、CUDA Graph 调优或 P/D 分离；先确认默认 kernel 组合在 H20 上正确运行，再通过 A/B benchmark 决定是否启用。

target-only 验证通过后，才增加 0731 模型卡给出的 DSpark 参数：

```bash
--speculative-config '{"method":"dspark","num_speculative_tokens":7,"draft_sample_method":"greedy"}'
```

H20 的上游记录曾暴露 DSpark model class 缺少 `draft_id_to_target_id` 的问题，修复已经合并。镜像仍需确认包含该修复；不能因为版本号看起来足够新就跳过 DSpark 单独验收。

SGLang 也支持 0731，并在 H200、B200、GB300 等硬件上有 cookbook，但目前 H20 的直接证据少于 vLLM。因此首次 H20 PoC 优先 vLLM，SGLang 作为第二条对照路径，而不是同时引入两个引擎变量。

## 8. 验证门槛

只有以下阶段依次通过，才能把“可探索”升级为“可部署”：

| 阶段 | 验证内容 | 通过条件 |
| --- | --- | --- |
| 0. 静态检查 | 模型文件、镜像包版本、CUDA/驱动、CephFS、污点和资源请求 | 不启动模型也能证明依赖闭环，没有使用旧 vLLM 镜像 |
| 1. Target-only 启动 | TP=8、32K、并发 1–4 | 8 Rank 正常加载；`/v1/models`、健康检查和简单生成成功；无 OOM、kernel error 或重启 |
| 2. 协议正确性 | non-think、`low/high/max`、多轮对话、tool calling、异常输出 | DeepSeek V4 编码和 parser 与仓库测试向量一致 |
| 3. 上下文爬坡 | 16K → 32K → 128K → 384K | 每级记录显存、TTFT、TPOT、吞吐和错误；不直接从 32K 跳到 1M |
| 4. DSpark A/B | 相同输入分别关闭/开启 DSpark | 输出质量和工具调用不回退；吞吐增益稳定；无 draft/target 映射错误 |
| 5. 稳定性 | 冷启动、Ceph 并发读取、持续负载、Pod 重启 | 启动探针合理，持续运行无显存泄漏或重复 kernel crash |
| 6. 生产化评审 | Queue/池容量、Service、AIBrix、监控、回滚 | 明确占用的完整八卡容量和回收机制后再提交部署变更 |

若 32K target-only 都无法通过，应先停在镜像/kernel 兼容性排查，不要用增加 GPU、切多机或开启 DSpark 来掩盖基础问题。

## 9. 当前未闭环事项

本次评估后仍有四个生产前未知项：

- H20 目标集群到现有 CephFS 的网络和 Secret 是否已经打通；
- 目标模型目录的真实文件完整性和读取吞吐；
- 计划使用的 vLLM 0.26.x 内部镜像是否完整包含 DeepSeek V4、DeepGEMM、FlashInfer 与 DSpark 修复；
- 完整八卡 H20 Serving 节点能否在实验窗口被正式预留，而不是只在快照时空闲。

这些未知项不否定 H20 的硬件可行性，但决定 PoC 能否一次启动成功。下一步如果继续，应先做静态镜像与模型目录核验，再由变更流程决定是否创建实验工作负载。

## 10. 参考资料

- [DeepSeek-V4-Flash-0731 模型卡](https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash-0731)
- [vLLM DeepSeek-V4-Flash Recipe](https://recipes.vllm.ai/deepseek-ai/DeepSeek-V4-Flash)
- [SGLang DeepSeek V4 Cookbook](https://docs.sglang.io/cookbook/autoregressive/DeepSeek/DeepSeek-V4)
- [vLLM DeepSeek V4 Roadmap](https://github.com/vllm-project/vllm/issues/40902)
- [H20 上的 DeepSeek-V4-Flash-DSpark 问题记录](https://github.com/vllm-project/vllm/issues/47418)
- [DSpark `draft_id_to_target_id` 修复](https://github.com/vllm-project/vllm/pull/47429)
