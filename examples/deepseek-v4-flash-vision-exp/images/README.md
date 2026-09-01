# Vision-Exp 镜像状态

核对日期：2026-09-01。

## 运行时结论

| 路线 | 核对对象 | 当前状态 |
| --- | --- | --- |
| SGLang | PR `#37253` / commit `914197146f8a3407960e5c7037d0463e03c37be9` | 已包含 Vision、Aligner、图片 span attention、`bias_vl` 路由及 OpenAI `image_url`；尚未进入正式 release，必须使用专用预览镜像 |
| vLLM | Issue `#54561` | 官方 main 尚不能完整加载 Vision-Exp；外部实现未合入且视觉 span 双向注意力仍不完整，不准备正式测试镜像 |
| DeepSeek reference | 模型 Revision `e46e16bf6035c6f317eb2ac7458eb0362926d402` | 有 Vision + Aligner + TP4 参考实现；不是 Serving Engine |

HF 模型页自动生成的一行启动命令仍不能代替端到端视觉支持验证。当前只准备 SGLang 专用预览
镜像，不把普通 vLLM DeepSeek-V4 镜像标成 Vision-Exp ready。

## 固定镜像

| 项目 | 值 |
| --- | --- |
| 上游 tag | `lmsysorg/sglang:dev-dsv4-flash-vision` |
| 上游 pull digest | `sha256:94b773e21e26259c9f5baeb0feccb44ccba1e7629bbaf255ab49d2d9e1214253` |
| SGLang commit | `914197146f8a3407960e5c7037d0463e03c37be9` |
| 平台 | `linux/amd64` |
| CUDA / FlashInfer | CUDA `13.0.3` / FlashInfer `0.6.18` |
| 本地展开大小 | `35,455,639,952` B |
| 固定 amd64 manifest | `sha256:5996a154550d5a39955fd7048eb44d5f655f08063af8ac3775845fd4ac404a69` |

部署端应使用不可变内部引用，公开材料不记录真实 Registry：

```text
<INTERNAL_REGISTRY>/llm-serving-sglang@sha256:5996a154550d5a39955fd7048eb44d5f655f08063af8ac3775845fd4ac404a69
```

## 同步记录

镜像在可访问公网 Registry 的中转机完成上游拉取和 staging 打标，没有经过本地 VPN。
staging 远端 inspect 已确认 `linux/amd64`、commit 和 manifest digest。

| 目标 | 任务/执行号 | 状态 |
| --- | --- | --- |
| staging → production | Registry 侧复制 | Success |
| production → IDC 中转 | Registry 侧复制 | Success |
| IDC 中转 → 目标推理集群 | Registry 侧复制 | Success |

Harbor 三段复制均已成功。production/目标集群 manifest digest 在首次零 GPU pull/inspect 时再次
记录；正式 Deployment 不使用上游浮动 tag。

## 后续流程

1. 在目标集群做零 GPU CLI、commit、CUDA 和架构探针；
2. 在 H20-3e 先用 TP4、target-only 做单图/双图 Smoke；
3. 通过后再启用 DSpark，并扩展到性能与长上下文测试；
4. 保存实际拉取后的目标 digest，再固化 Kubernetes Manifest。

镜像验收至少要证明：

- `DeepseekV4ForCausalLM` 被识别为多模态模型；
- Vision、Aligner 和 image marker 权重全部被消费；
- OpenAI Chat 支持单图和 `text → image → text → image`；
- 坏图片返回 4xx，而不是导致模型 Rank 崩溃；
- 基准客户端能记录真实 prompt/vision token 和错误详情。
