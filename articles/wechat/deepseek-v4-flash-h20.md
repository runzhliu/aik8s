# 花两倍 H20，首 Token 快 47%：DeepSeek V4 Flash 的 P/D 分离值不值？

如果只看延迟图，我们会说这次 P/D 分离成功了。

如果只看 GPU 账单，我们又会得出完全相反的结论。

在同一组 128-token 输入、64-token 输出、并发 8 的请求上，DeepSeek-V4-Flash-0731 从普通 TP=8 切换到 AIBrix P/D 后，p95 TTFT 从 265 ms 降到了 140 ms，改善约 47%。代价是 GPU 从 8 张增加到 16 张，单位 GPU 吞吐下降约 53%。

所以真正的问题不是“P/D 有没有用”，而是：

> 业务愿意用多少 GPU，购买多少尾延迟？

这是我们在 H20 上完成基线、同机拆分和 AIBrix 双 Engine 实验后，得到的最重要结论。

![并发 8 下普通 TP=8 与 AIBrix P/D 的性能成本对比](../../docs/assets/practices/deepseek-v4-flash-h20-evaluation/03-performance-tradeoff.png)

## 先把结论放在桌面上

这次实验确认了三件事：

1. DeepSeek V4 Flash 可以在单机 `8 × H20 96 GB` 上以 TP=8 稳定运行；
2. P/D 确实可以隔离 Prefill 对 Decode 的干扰，改善并发下的尾延迟；
3. 如果没有匹配的请求分布、资源配比和路由策略，P/D 很容易成为昂贵的架构正确。

最后一句很关键。

P/D 不是一个打开后就能提高吞吐的优化参数。它把一次推理拆成两个服务，把一个调度问题变成了 Prefill 选择、Decode 选择、KV 传输、故障降级和独立扩缩容等一组新问题。

AIBrix 的价值，恰恰在这一层。

## 我们差点得出第一个错误结论

单机基线是一台八卡 H20、一个 vLLM Engine、TP=8：

```text
Client → vLLM API Server → TP=8 → 8 × H20 96 GB
```

服务进入 Ready 后，我们立即执行并发 8 压测。第一次结果是：p95 TTFT 约 33.4 秒，总输出吞吐约 92 tok/s。

如果测试停在这里，结论会是“DeepSeek V4 Flash 在 H20 上性能很差”。

但日志显示，请求期间触发了 TileLang JIT，其中一个 kernel 编译约 9 秒。使用完全相同的请求形状复跑后，p95 TTFT 恢复到约 233 ms，输出吞吐提高到约 934 tok/s。

两轮相差超过 10 倍，模型、GPU 和参数都没变。变化的只是运行时是否完成了目标形状的编译与预热。

这件事改变了我们后面的测试顺序：先用真实输入长度和并发完成预热，再谈性能。端口 Ready 只证明服务开始监听，不代表推理运行时已经进入稳态。

![首次压测与同形状预热后的结果差异](../../docs/assets/practices/deepseek-v4-flash-h20-evaluation/02-warmup-pitfall.png)

稳态下，单机 TP=8 的结果如下：

| 请求形状 | 输出吞吐 | p95 TTFT | p95 TPOT |
| --- | ---: | ---: | ---: |
| 128/64，C=1 | 250 tok/s | 49 ms | 4.84 ms |
| 128/64，C=4 | 618 tok/s | 96 ms | 8.02 ms |
| 128/64，C=8 | 934 tok/s | 233 ms | 11.53 ms |
| 4096/128，C=4 | 277 tok/s | 1391 ms | 16.00 ms |

这里的 `C` 是客户端最大并发，不是总用户数。并发从 1 增加到 8 后，总吞吐提高约 3.73 倍，p95 TTFT 也从 49 ms 上升到 233 ms。这是 continuous batching 用单请求延迟换总吞吐的正常表现。

更值得注意的是 4K 输入：TTFT 上升到约 1.39 秒。Prompt 越长，Prefill 对首 Token 延迟的影响越明显，这才是我们尝试 P/D 的起点。

## 我们也差点得出第二个错误结论

第一轮 P/D 没有增加机器，而是把同一台服务器的八张卡拆成两半：

```text
Prefill TP=4（GPU 0-3）
        │
        │ NIXL / UCX 传输 KV Cache
        ▼
Decode TP=4（GPU 4-7）
```

KV Cache 交接是成立的：NIXL compatibility check、Transfer Plan 和 Decode 外部 KV 命中都正常，确定性请求也能返回正确结果。

性能却只有 TP=8 基线的 3.7%～12.1%。并发 8 时，输出吞吐从 934 tok/s 降到了约 66 tok/s。

这是不是说明 NIXL 很慢、P/D 不适合 H20？

不是。

绕过 P/D Proxy、直接访问 TP=4 Decode，单请求性能与经过 P/D 几乎一致。主要损失来自算力切分：原来的一个 Engine 可以使用全部八张卡，现在变成了两个各自只有四张卡的 Engine；为了快速验证数据路径，这轮还关闭了 CUDA Graph 和推测解码。

这轮实验的价值不是给出性能结论，而是建立了一个负对照：

> 同机 4P+4D 可以证明 KV 传输链路正确，但不能拿来替代 TP=8 基线。

如果跳过这个对照，我们很容易把资源拓扑的代价错误归因于 P/D 协议。

## 真正可比较的一轮：AIBrix 双 TP=8

随后我们给 Prefill 和 Decode 各一套完整的 TP=8 Engine，总计使用 16 张 H20：

```text
                 AIBrix Gateway
                routingStrategy=pd
                   ╱        ╲
                  ╱          ╲
      Prefill TP=8 ── NIXL ──▶ Decode TP=8
        8 × H20                   8 × H20
```

客户端通过同一个 AIBrix Gateway 发起请求。并发 8 的结果是：

![普通 TP=8 与 AIBrix 双 TP=8 P/D 的资源拓扑](../../docs/assets/practices/deepseek-v4-flash-h20-evaluation/01-topology-comparison.png)

| 部署方式 | GPU | 输出吞吐 | p95 TTFT | p95 TPOT | p95 E2E |
| --- | ---: | ---: | ---: | ---: | ---: |
| 普通 TP=8 | 8 | 866.61 tok/s | 264.86 ms | 11.63 ms | 856.39 ms |
| AIBrix P/D，2×TP8 | 16 | 817.95 tok/s | 139.56 ms | 9.80 ms | 681.91 ms |

从延迟看，P/D 很有效：

- p95 TTFT 改善约 47.3%；
- p95 TPOT 改善约 15.7%；
- p95 E2E 改善约 20.4%。

从成本看，它并不便宜：

- 普通 TP=8：约 108.3 tok/s/GPU；
- AIBrix P/D：约 51.1 tok/s/GPU。

总吞吐只下降约 5.6%，但 GPU 增加了一倍，单位 GPU 吞吐因此下降约 52.8%。

P/D 在这里做的事情很明确：它没有凭空创造算力，而是用一套独立资源承接 Prefill，减少其对 Decode 的干扰。我们购买到的是更稳定的尾延迟，不是更高的硬件利用率。

## 为什么 AIBrix 官方文章里的结果更好

AIBrix 官方在单节点 P/D 文章中给出过更积极的结果：在 L20 上，同等 GPU 数量、P99 延迟不变时，QPS 可以提高 40% 以上；KV Cache 命中较高的多轮场景中，吞吐还能获得更明显提升。

这个结果与我们的 H20 实验并不矛盾，因为两者测试的不是同一个问题。

| 维度 | AIBrix 官方单节点方案 | 本次 H20 实验 |
| --- | --- | --- |
| 目标场景 | 多轮对话、公共前缀复用 | 随机短请求、低前缀复用 |
| 数据路径 | KVCache-centric，共享内存与专用传输 | 两个完整 Engine 间 NIXL 传输 |
| 资源约束 | 同节点、同等 GPU 预算 | 两套 TP=8，GPU 加倍 |
| 主要观察 | SLO 下的 QPS 与缓存收益 | 尾延迟与单位 GPU 吞吐 |

官方方案真正吃到的红利，不只是“把 P 和 D 分开”，还包括公共前缀复用、KV Cache 数据面和针对工作负载设计的资源比例。

而我们的随机请求几乎没有可复用前缀，又给 P 和 D 各分配了一整套 TP=8。它适合验证隔离效果，却天然不是最经济的形态。

这也说明，脱离 KV 命中率、Prompt 分布和 SLO 谈 P/D 性能，结论通常没有可迁移性。

## AIBrix 真正解决的不是“启动两个 Pod”

如果只需要启动一个 Prefill 和一个 Decode，Kubernetes YAML 就能做到。AIBrix 更重要的能力是决定：什么请求应该走哪条路径，以及某个角色不可用时怎样继续服务。

AIBrix 从 v0.6.0 开始支持 P/D 与 Combined 混合路由，v0.7.0 中已经有完整实现。同一个模型可以同时保留两类实例：

```text
                         ┌─ P/D 实例：长 Prompt、Prefill-heavy
Request → AIBrix Router ─┤
                         └─ Combined 实例：短 Prompt、交互请求、溢出兜底
```

Gateway Plugin 打开 `AIBRIX_PROMPT_LENGTH_BUCKETING=true` 后，会读取请求的 Prompt 长度，并按各 Pod `routingConfig` 中的 `promptLenBucketMinLength` 和 `promptLenBucketMaxLength` 分桶。短请求可以只匹配 Prefill/Decode 共置的 Combined Engine，长请求匹配 P/D roleset；如果对应区间找不到同时 Ready 的 Prefill 和 Decode，且存在覆盖该长度的 `combined: true` 实例，路由会跳过独立 Prefill 调用，直接把请求发给 Combined。

这不是概念图，而是 v0.7.0 `pd_disaggregation.go` 中的实际分支：`collectAndBucketPods` 先按 `roleset-name`、`role-name` 和 Prompt 区间组织候选，`filterPrefillDecodePods` 决定走完整 P/D pair 还是 Combined；当 P/D 请求率较高而 Combined 空闲时，`shouldPickCombined` 也可以把溢出流量导向 Combined。

实例内部的选择同样不是简单轮询。v0.7.0 默认的 Prefill `prefix_cache` 策略综合前缀命中率与正在执行的 Prefill 数；Decode `load_balancing` 策略综合运行请求数、生成吞吐和 KV Cache 剩余空间。当前 AIBrix 主干还新增了 `conductor` 策略，用排队时间、命中与未命中 Token 估算 TTFT，并估算新增请求后的 TBT 与 GPU Cache 惩罚；但它不属于本文部署所用的 v0.7.0 稳定版，因此这里只把它视为后续演进方向，而不是本轮已经启用的能力。

这比“所有请求强制经过 P/D”更接近生产问题。短请求没必要承担额外路由和 KV 传输，长请求又能获得资源隔离；Combined 实例同时承担正常路径和容量保险丝。

因此，我们现在不会把这轮 `2×TP8` 当作最终部署方案。它证明了 P/D 对尾延迟有效，下一步才是让路由决定这份成本花在哪些请求上。

## 下一轮测试应该怎么做

下一轮不会继续追求一个更大的 tok/s 数字，而会围绕 SLO goodput 设计。

所谓 SLO goodput，是每秒完成、并且同时满足 TTFT 与 TPOT 目标的请求数。再除以 GPU 数，才能回答生产上真正关心的问题：每张卡能交付多少合格请求。

测试矩阵至少需要包含：

- 128、4K、16K 等不同 Prompt 长度；
- 低、中、高三档并发；
- 0%、50%、90% 等不同公共前缀命中率；
- Combined、纯 P/D、按 Prompt 长度混合路由；
- 相同 GPU 预算，以及相同延迟 SLO 两种比较口径。

最终要找的不是一个固定的“最佳架构”，而是一条分界线：Prompt 多长、缓存命中多高、队列多深时，走 P/D 才比共置更划算。

## 写在最后

这次 H20 实验给了我们一个不够漂亮、但更有用的答案。

P/D 分离确实把并发 8 的 p95 TTFT 降低了约 47%，但在当前资源配比和随机短请求下，单位 GPU 吞吐也下降了约 53%。它不是失败，也不是免费的成功，而是一笔价格已经被量化的延迟交易。

AIBrix 的意义不在于让单个 vLLM Engine 神奇地变快，而在于把这笔交易变成可调度的：长请求走 P/D，短请求走共置，缓存、负载和故障状态共同参与选择，Prefill 与 Decode 再按各自压力扩缩。

下一次再问“要不要上 P/D”，我们不会先看架构图，而会先问三个数字：Prompt 分布、SLO goodput，以及每个合格请求消耗多少 GPU。

完整的脱敏部署命令、压测口径和实验记录，将放在“阅读原文”的公开技术文档中。
