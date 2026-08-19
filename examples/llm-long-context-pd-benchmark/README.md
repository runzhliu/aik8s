# 大模型长上下文与 P/D 复测套件

这套用例用于资源恢复后的统一复测，覆盖：

- DeepSeek V4 Flash：SGLang Combined TP=8、P/D 2×TP=8 TCP、P/D 2×TP=8 RDMA。
- GLM-5.2 FP8：vLLM Combined TP=8、P/D 2×TP=8 TCP、P/D 2×TP=8 RDMA。
- 可选项：DeepSeek speculative decoding、GLM-5.2 SGLang；只能在 target-only 主对比完成后运行。
- 校准项：已有 Qwen3.8 27B 单卡 L20 vLLM/SGLang，可先验证同一压测工具链的跨引擎 A/B。
- 输入长度从短请求延伸到 `127K+1K`、`199K+1K`、`255K+1K`，便于和公开的长上下文测试对齐。

目录不包含集群名、节点地址、模型挂载路径、镜像仓库或网络配置。部署层仍使用各环境已有的清单；这里仅固定公开可复现的请求与判定方法。

如果对 `128/64`、`4096/128`、`32K/64K/128K`、`127K+1K C=1` 这些写法不熟悉，先看 [TOKENS_EXPLAINED.md](./TOKENS_EXPLAINED.md)，里面用具体算式和请求例子解释 token、上下文窗口与并发的区别。

## 为什么分两轮

`capacity` 阶段沿用“每个并发约 3 个请求”的容量探测方式，目的是快速发现 OOM、上下文上限、JIT 编译或调度异常，**不能直接用于稳定的 p95/p99 结论**。通过容量探测的单元格，再用至少 5 轮和更多请求做正式复测。

| 阶段 | 目的 | 默认请求量 | 默认重复 |
|---|---|---:|---:|
| `smoke` | API、路由、结果格式检查 | 4 | 1 |
| `baseline` | 128/64 与 4K/128 的正式基线 | 64–256 | 5 |
| `capacity` | 4K–255K 上下文的并发边界探测 | 3×并发 | 1 |
| 正式长上下文 | 对通过探测的 cell 复测 | 至少 20 且不低于 5×并发 | 至少 5 |

`127K+1K` 表示输入 130,048 token、输出 1,024 token，总上下文恰好 131,072 token。相同地，`199K+1K=204,800`，`255K+1K=262,144`。脚本使用 `/v1/completions` 和固定长度随机数据，避免 Chat Template 的额外 token 破坏长度对齐。

## 测试矩阵与资源

[cases.csv](./cases.csv) 是请求矩阵，[profiles.csv](./profiles.csv) 是部署拓扑矩阵。主结论必须在同一个模型、同一个推理引擎、同一批节点和同一镜像下比较：

1. Combined TP=8 target-only。
2. P/D：Prefill TP=8 + Decode TP=8，NIXL TCP。
3. 保持第 2 步所有配置不变，只将 KV 传输改成 RDMA。
4. 主对比完成后，才测试 speculative decoding 或另一种推理引擎。

Combined 用 8 张 GPU，P/D 用 16 张 GPU。报告必须同时给出总吞吐和 `output tok/s/GPU`；P/D 总吞吐更高不等于单位资源效率更高。

推荐一次只保留一个模型、一个 profile。每阶段完成并归档结果后释放实例，再切换下一 profile，避免在资源紧张时并行占用。

长上下文并发上限按公开测试中的安全边界预置：4K 到 C=8、20K/39K 到 C=4、80K/127K 到 C=2、199K/255K 到 C=1。它是起点而不是结论；如果 KV cache 仍有明显余量，再复制 cell 向上探索，OOM 探索不要和正式 A/B 混在同一轮。

## 执行前正确性门槛

任何一项不通过，都不要开始性能压测：

- `/v1/models` 和 `/v1/completions` 返回正确，流式和非流式各通过一次。
- 中、英、代码各准备一条 `temperature=0` 固定请求，Combined、P/D TCP、P/D RDMA 输出 token/hash 一致。
- 4K、32K、64K、127K 各执行一次 needle retrieval；只有模型声明支持的长度需要通过。
- P/D 日志能关联同一个 request ID 的 Prefill、KV 传输和 Decode，Decode 没有重新计算完整 Prompt。
- TCP 基线能看到 NIXL 传输指标；RDMA 组除 NIXL 指标外，RDMA 端口字节计数必须增长。
- 正式轮次开始后若再次发生 JIT/torch.compile，丢弃该轮，预热完成后重跑。
- 记录镜像 digest、推理引擎版本、模型 revision、启动参数、GPU 型号/数量、驱动、CUDA、网络设备和 max model length。

`input_tokens + output_tokens` 超过 profile 的 `max_context` 时，脚本记录 `SKIP_UNSUPPORTED`，不将它误报为模型失败。如果服务以 262,144 上下文重新启动，可用 `--max-context 262144` 显式覆盖。

Qwen3.8 27B 校准 profile 当前按运行时的 32,768 token 上下文建模：可以执行 short、4K 和 20K cell；39K 及以上会被跳过。对应的 Qwen3.5-27B [官方模型卡](https://huggingface.co/Qwen/Qwen3.5-27B) 与实际权重配置都声明原生 262,144 token；官方还建议显存不足时尽量维持至少 128K，以保留复杂任务的 thinking 能力。因此 128K 不是 RoPE 外推，也不是无效的纯压力测试。

若要测试 128K，应启动独立的 131,072-token candidate，先只跑 `ctx-127k-1k-c1`，确认显存、正确性和首 token 时间后再探索 C=2。不要直接修改仍承担流量的 32K 基线实例。官方 262K 示例使用 TP=8；单卡 L20 是否能稳定容纳 128K 必须以启动时 KV 容量和实测为准，不能从模型上限直接推导。

Qwen 的 128K 测试用于回答长文档、RAG 和长会话下的 Prefill、TTFT、KV 容量问题；常规请求性能仍由 short 与 4K 基线回答。它必须同时通过 127K needle retrieval 或长文问答，以及随机 token 性能测试；只测随机 token 吞吐不能证明模型在 128K 有效。该校准项是 TP=1，不可直接和 DeepSeek/GLM 的 TP=8 数值比较。

若要画出单卡上下文成本曲线，使用完全一致的 C=1、1 次预热和 3 次正式请求，依次测试 `ctx-31k-1k-c1`（32K 配置）、`ctx-63k-1k-c1`（64K 配置）和 `ctx-127k-1k-c1`（128K 配置）。这组数据比较的是不同输入长度的实际成本，不应解释成只修改 `max_context` 所产生的配置开销。

128K candidate 启动并通过 API smoke 后，先运行三个 Needle 位置：

```bash
python3 needle.py \
  --base-url http://MODEL_ENDPOINT \
  --model SERVED_MODEL_NAME \
  --tokenizer /path/to/tokenizer \
  --target-input-tokens 130048 \
  --positions 0.1,0.5,0.9 \
  --output results/needle-127k.json
```

三个位置全部正确后，才执行随机 Token 性能 cell：

```bash
./run-matrix.sh ... \
  --profile qwen38-27b-vllm-tp1-l20-128k \
  --stage capacity \
  --case ctx-127k-1k-c1 \
  --execute
```

## 离线检查

脚本默认只打印命令，不会发压测流量：

```bash
cd examples/llm-long-context-pd-benchmark

./run-matrix.sh \
  --profile glm52-vllm-pd-rdma-tp8x2 \
  --base-url http://MODEL_ENDPOINT \
  --model SERVED_MODEL_NAME \
  --tokenizer /path/to/tokenizer \
  --stage capacity
```

P/D profile 会自动添加 `routing-strategy=pd`。认证或其他网关头可重复传入 `--header KEY=VALUE`。
DeepSeek 自定义 tokenizer 需要特定模式时，可额外传入 `--tokenizer-mode deepseek_v4`；具体取值以本轮固定的 benchmark 客户端版本为准。

## 资源恢复后的顺序

先对每个 profile 跑 smoke，再顺序执行 baseline 和 capacity：

```bash
./run-matrix.sh ... --stage smoke --execute
./run-matrix.sh ... --stage baseline --execute
./run-matrix.sh ... --stage capacity --execute
```

容量探测后，选择没有 OOM、失败或排队异常的 cell，增加样本和重复数。例如正式复测 `127K+1K C=2`：

```bash
./run-matrix.sh ... \
  --stage capacity \
  --case ctx-127k-1k-c2 \
  --num-prompts 20 \
  --repeats 5 \
  --execute
```

TCP/RDMA A/B 必须复用同一组 case、seed 和请求数，并按 `TCP → RDMA → TCP` 抽查一次回归，排除节点温度、后台任务和缓存随时间变化的影响。在线 SLO 测试应在确定饱和并发后追加固定 RPS 梯度，统计满足 TTFT/TPOT SLO 的 goodput。

## 结果与判定

每次运行保存 vLLM JSON，主要查看：

- 成功/失败请求数、request throughput、input/output token throughput。
- p50/p95/p99 TTFT、TPOT、ITL、E2E。
- GPU 利用率、显存、功耗、KV cache 使用率、等待队列。
- P/D KV 字节数、传输时间、有效带宽，以及 RDMA 端口硬件计数。
- Pod 创建到首个正确响应的启动时间。

汇总重复结果：

```bash
python3 summarize.py results --output results/summary.md --csv results/summary.csv
```

生成 RDMA 相对 TCP 的 A/B 表：

```bash
python3 summarize.py results \
  --baseline glm52-vllm-pd-tcp-tp8x2 \
  --candidate glm52-vllm-pd-rdma-tp8x2
```

RDMA 收益至少同时报告吞吐、TTFT/TPOT/E2E、单位 GPU 吞吐、NIXL 有效带宽和 RDMA 硬件计数。短请求退化、长请求获益也是有效结论，不能只挑最高提升的 cell。

原始 JSON、监控时间窗、服务日志和环境快照应一起归档。正文只引用聚合结果，不删除失败轮次；排除某轮时要写清原因。
