# GLM-5.3-Flash Day 1 实测：我用 4×H20 跑通了 1M 上下文

> GLM-5.3-Flash 发布后的第二天，我用 4 张 141 GB H20 分别跑通了 SGLang 和 vLLM 专用镜像，并完成了 Reasoning、Tool Call、图片、OpenWebUI、短请求吞吐、1K Decode、Prefix Cache，以及接近 1M Token 的冷 Prefill 与 Needle 检索。结果不只是“模型能跑”：vLLM 的高并发 Decode 更快，SGLang 的首日支持链路更完整，而两边都暴露了不能忽略的首次 JIT 尾延迟。

2026 年 8 月 26 日，GLM-5.3-Flash 发布。

它不是一个简单缩小的 Dense 模型，而是一个约 320B 总参数、18B 激活参数的原生多模态 MoE。45 层文本网络混合 MLA、DSA 和 KDA，包含 288 个路由专家，还带一层原生 MTP Draft。官方上下文上限是 1,048,576 Token，输入支持文本、图片和视频。

这些规格很吸引人，但也让部署变得更复杂。模型能被 Transformers 识别，不等于推理引擎的 Sparse MLA、KDA State、MoE Kernel、CUDA Graph、多模态 Encoder 和 Prefix Cache 已经全部连通。

所以这次我没有把“Pod Running”当成测试结束，而是连续追问了三个问题：

1. 4×H20 到底能不能装下并稳定启动？
2. Reasoning、Tool Call、多模态和 UI 是否真的可用？
3. 短请求、长输出、1M 上下文和缓存性能如何？

先给结论：

- 官方 Native FP8 Checkpoint 可以在 4×H20 上部署；
- SGLang 和 vLLM 专用预览镜像都能完成接近 1M Token 的请求与 Needle 检索；
- SGLang 的功能闭环更完整，已经接入 OpenWebUI 完成真实对话；
- vLLM 在并发 16/32 和 1K Decode 上吞吐更高，但预览实现仍有 Backend、Warmup 和 API 边界；
- 两套引擎首次遇到新并发形状时都有明显 JIT 尾延迟，不能只摘最快的一轮；
- SGLang 在 261K、263K、289K 冷请求上均成功，本次没有复现社区报告的约 262K 边界崩溃。

## 4×H20 为什么能装下 320B MoE

“每 Token 激活 18B”描述的是计算稀疏度，不代表显存只需要容纳 18B 权重。Serving 时仍然要把约 320B 总权重放进 GPU。

这次使用的是官方 Native FP8 Checkpoint，共 62 个 Safetensors 分片，权重 Index 记录约 328.3 GB。4 张 141 GB H20 做 TP4 后，SGLang 每卡权重显存约 75.27 GiB，vLLM 约 75.65 GiB。

H20 属于 Hopper。两套引擎都采用 FP8 Weight + BF16 KV Cache，而不是把权重精度和 KV Cache 精度混为一谈。MTP 第一轮保持关闭，先得到 Target-only 基线。

核心配置可以概括为：

```text
GPU                  4 × H20 141 GB
Checkpoint           官方 Native FP8
Parallel             TP4
KV Cache             BF16
Context              1,048,576
MTP                  Off
API                   OpenAI-compatible
```

SGLang 额外使用 EP4、DSA Attention、TileLang Prefill/Decode、Triton Linear Attention 和 DeepGEMM MoE。

为什么先关 MTP？因为 MTP 会同时改变 Decode 路径、显存、Draft/Verify 和 CUDA Graph 形状。如果一开始就把它打开，性能变化很难解释。Day-1 实测最怕“所有高级选项一起开”，最后只知道数字变了，却不知道为什么。

## 启动成功，也有很多工程细节

SGLang 权重加载耗时 130.59 秒，每卡分配 19.93 GiB BF16 KV Cache，Token Pool 为 1,683,136。容器创建到真正 Ready 约 9 分 51 秒。

vLLM 的启动阶段更重：最慢 Rank 权重加载约 365.69 秒，DeepGEMM 又 Warmup 了 1,102 个 Kernel，耗时约 92 秒；CUDA Graph Capture 还有 15 秒。最终容器创建到 Ready 约 12 分钟。

这带来一个很实际的 Kubernetes 问题：默认 10 分钟的 Deployment Progress Deadline 会先报超时，但 Pod 并没有崩溃。它只是还在做 Kernel Warmup 和 Autotune，完成后就正常 Ready，整个测试期间 0 Restart。

对于这类新模型，我会把 Startup Probe 和 Progress Deadline 放宽到 20～30 分钟，用 Readiness 决定是否接流量，而不是在权重加载阶段让 Liveness 循环杀进程。

vLLM 的日志还给出两条值得保留的警告：

- 当前没有适配这个模型的 MLA Prefill Backend，Sparse MLA 退回 Top-k MQA Path；
- 镜像中没有 H20 专用的 FP8 MoE 调优配置，使用默认配置。

它们不影响“可以运行”的结论，但说明这组性能还不是 vLLM 在 H20 上的最终上限。

## API 不能只问一句“你好”

两套引擎都通过了 `/v1/models`、`reasoning_effort=low/high/max`、结构化 Tool Call 和真实图片输入。

差异在于，SGLang 能返回独立的 `reasoning_content`；vLLM 预览镜像虽然完成了 Reasoning 请求，但思考内容没有拆到独立字段。对 UI 来说，这不是小差异：HTTP 200 不等于前端能按预期展示思考过程。

SGLang 的 OpenAI 兼容接口已经接入 OpenWebUI，模型列表和真实 Chat 都验证通过。这个闭环同时检查了跨服务访问、模型名、Chat Template、Parser 和流式响应，而不只是后端单独 Curl 成功。

视频输入本轮没有测试，所以文章不会把“模型卡支持视频”直接写成“我的服务已经验证视频”。

## 短请求吞吐：只挑最快的一轮，会得出错误结论

先用固定 128 输入、64 输出 Token，逐级测试并发 1、4、8、16、32。每档跑三轮，图里使用三轮中位数，不摘最好的一轮。

![128/64 短请求三轮中位数](assets/glm53-flash-day1-short-throughput.png)

| 并发 | SGLang Output tok/s | vLLM Output tok/s | SGLang P95 TTFT | vLLM P95 TTFT |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 74.7 | 107.7 | 188 ms | 183 ms |
| 4 | 234.6 | 225.9 | 340 ms | 559 ms |
| 8 | 392.4 | 257.2 | 414 ms | 11.76 s |
| 16 | 572.2 | 735.8 | 428 ms | 565 ms |
| 32 | 847.1 | 1,156.9 | 1.10 s | 695 ms |

vLLM 在高并发下优势明显。并发 32 的三轮 Output TPS 是 1,145.4、1,156.9、1,166.4；SGLang 则是 847.1、842.4、853.5。

但如果只取 vLLM 并发 8 的最快轮，会得到 410.8 tok/s；完整三轮其实是 162.2、410.8、257.2。第一轮 P99 TTFT 达到 23.43 秒，第三轮 P95 TTFT 仍有 11.76 秒。

SGLang 也不是完全没有这个问题。第一次遇到并发 4、8、16 时，它分别出现约 10.9、12.5、13.6 秒的 P95 TTFT，随后两轮恢复稳定。两套 Runtime 的服务日志都能看到新 Kernel JIT。

这说明首发模型的 Warmup 不能只发一个短请求。需要覆盖业务真正会出现的“输入长度 × 输出长度 × 并发”矩阵，并单独观察第一轮 P95/P99。

## 1K Decode：vLLM 的优势更清晰

把输出长度提高到 1,024 Token 后，Decode 差异更稳定：

| 并发 | SGLang Output tok/s | vLLM Output tok/s | SGLang P95 TPOT | vLLM P95 TPOT |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 92.3 | 148.5 | 10.71 ms | 6.56 ms |
| 8 | 461.0 | 685.0 | 17.19 ms | 11.47 ms |

在 MTP Off 基线中，vLLM 的 Decode 路径明显更快。这也是我不会简单写成“SGLang 全面领先”或“vLLM 全面领先”的原因：SGLang 当前更适合快速组成完整服务，vLLM 则展示了更高的吞吐潜力。

## 接近 1M Token，首 Token 要等多久

长上下文每轮都先清理 Prefix Cache，固定并发 1、输出 128 Token。

![冷缓存长上下文 TTFT](assets/glm53-flash-day1-long-context.png)

| 输入 Token | SGLang TTFT | vLLM TTFT |
| ---: | ---: | ---: |
| 32,768 | 3.61 s | 3.43 s |
| 65,536 | 7.30 s | 8.29 s |
| 131,072 | 14.98 s | 13.99 s |
| 263,168 | 31.80 s | 29.57 s |
| 524,288 | 70.02 s | 65.95 s |
| 1,044,480 | 167.69 s | 160.96 s |

两套引擎都完成了接近 1M 的请求，但首 Token 要等待约 161～168 秒。也就是说，“原生 1M 可运行”和“适合 1M 在线交互”完全是两件事。

vLLM 第一次遇到 32K 新 Shape 时，TTFT 是 14.60 秒；Warmup 后才降到 3.43 秒。这个首轮数据没有从原始 CSV 删除，只是在长 Context 趋势图中明确使用 Warmup 后结果，避免把 JIT 和 Prefill 成本混在一起。

## 没有 OOM，不等于长上下文正确

随机 Token 压测只能证明容量。为了检查最低限度的信息召回，我把唯一标识分别放在上下文 10%、50%、90% 的位置，再要求模型精确返回。

结果是：

- SGLang 11/11 通过；32K、128K、257K 各测三个位置，512K 与近 1M 测中间位置；
- vLLM 8/8 通过；32K、257K 各测三个位置，512K 与近 1M 测中间位置。

所以这次可以说“请求成功且指定 Needle 可检索”，而不只是 HTTP 200。但单针仍然只是最低门槛，不能外推成复杂长文归纳、多针检索或长链推理都正确。

我还专门复测了 SGLang 的 262K 风险边界：261,120、263,168、288,768 Token 的 TTFT 分别为 31.47、31.80、35.16 秒，全部成功，测试后 Pod 仍为 0 Restart。

本次没有复现社区曾报告的边界问题，但单一 H20 配置的成功，也不能替所有硬件和 Backend 宣布问题已经消失。

## Prefix Cache：参数打开，不代表真的命中

固定约 4,400 Token Prompt，第一次冷请求后完全重复五次。

![Prefix Cache 冷热请求与服务端命中证据](assets/glm53-flash-day1-prefix-cache.png)

SGLang 的证据很完整：冷 TTFT 456.7 ms，热请求中位数 198.2 ms，下降 56.6%；服务端 Cache Hit Rate 从 0 上升到 98.55%。客户端时间和服务端 Metrics 可以互相验证。

vLLM 的服务端 Metrics 同样证明缓存有命中：Query Token 增量 26,472，Hit Token 增量 17,280，增量命中率约 65.28%；冷 E2E 651.1 ms，热 E2E 中位数 296.5 ms。

但 vLLM 预览版的 Completions API 忽略了 `echo=false`，Chat 流式测试又有部分请求没有稳定的可见首块，导致 TTFT 口径不可靠。所以我只发布它的 E2E 和服务端 Metrics，没有强行把那个 TTFT 与 SGLang 画到同一张柱状图里。

这是做 Cache 压测时很容易踩的坑：

- 配置里写了 `enable_prefix_caching`，不等于缓存真的命中；
- 客户端看起来更快，可能只是返回语义变了；
- 只有 Query/Hit Metrics 与冷热时间方向一致，结论才可信。

## 今天让我选，我会先用 SGLang

如果今天就要给团队提供一个可用的 OpenAI 兼容服务，我会先选择 SGLang。

原因不是某个单点 TPS 更高，而是它的首日支持完整度更好：官方 Cookbook 的硬件与 Backend 说明更清晰，Reasoning、Tool Call、图片、Prefix Cache 和 OpenWebUI 已经形成闭环，1M 与 262K 边界测试也没有引发重启。

vLLM 专用预览镜像并不是“不能用”。它已经跑通功能和 1M 上下文，并在并发 32 与 1K Decode 上表现出明显优势。但测试当天主仓支持仍未正式完成，H20 MoE 配置和 MLA Prefill Backend 还有缺口，预览 API 也存在边界行为。

更准确的说法是：

- SGLang 是当前更完整的首日支持落地路径；
- vLLM 是很值得继续跟踪的高吞吐预览路径；
- 等主仓支持、Kernel 和专用调优配置更新后，需要用同一组 GPU 重新做串行 A/B。

## 这次没有测试什么

本轮没有测试视频、MTP、P/D 分离、RDMA、BF16 权重和多节点。随机 Token 吞吐只衡量 Serving Path，不评价输出质量。

两套引擎虽然使用同一台 8 卡 H20 主机中互不重叠的两组 4 卡切片，vLLM 压测期间 SGLang 保持空闲，但宿主 CPU、内存和存储路径仍然共享。因此这是一组有参考价值的 Day-1 对照，不是同一组 GPU UUID 上串行复测的金标准结论。

下一轮我认为最有价值的是 MTP Off/On 单变量 A/B：记录 Acceptance Length、TTFT、TPOT、吞吐和显存，再根据真实业务形态决定是否继续做 P/D，而不是为了架构复杂度直接叠加 P/D 与 RDMA。

## 最后

这次实测最有价值的不是“1M 跑通了”这一句话，而是几条更接近生产的结论：

1. 模型能装下、API 能返回、长上下文能检索，是三个不同层次；
2. 新 Kernel 第一次遇到新 Shape 时可能带来十几秒尾延迟；
3. 高并发吞吐与完整服务能力，可能分别由不同引擎占优；
4. Prefix Cache 必须同时看客户端时间和服务端命中指标；
5. 原生 1M Context 不等于 1M 在线交互体验好；
6. 固定镜像 Digest、逐轮保存数据、公开测试边界，比发布一个最好看的 TPS 更重要。

完整启动参数、Kubernetes 示例、测试脚本、脱敏聚合 JSON、逐轮 CSV 和后续更新，可以通过“阅读原文”查看公开技术记录。
