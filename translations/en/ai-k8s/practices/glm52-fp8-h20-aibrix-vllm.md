---
title: "GLM-5.2 FP8 on H20: vLLM, SGLang, and P/D RDMA Field Measurements"
description: "Records the vLLM and SGLang baselines for GLM-5.2 FP8 on a single node with TP=8, as well as the KV transfer and end-to-end performance comparison between TCP and RDMA under two-node P/D separation"
status: exploratory
last_reviewed: 2026-08-18
---

# GLM-5.2 FP8 on H20: vLLM, SGLang, and P/D RDMA Field Measurements

This experiment answers a specific question: does GLM-5.2 FP8 have to use SGLang, or can it directly use AIBrix + vLLM to provide an OpenAI-compatible service on a single `8 × H20 141 GB` node?

The answer is yes, it can. The model has been started with the standard `vllm serve`, single-node TP=8, and has passed deterministic Chinese requests and four benchmark groups through the AIBrix Gateway, and was automatically discovered by the existing AIBrix connection in OpenWebUI. All cluster names, namespaces, node addresses, storage addresses, image registries, and credentials in this document have been removed or replaced with placeholders.

This is only a functionally correct and reproducible vLLM baseline, not a final performance conclusion. MTP/DSpark was not enabled in this round, and no independently importable DeepGEMM package was found in the generic image, so the results cannot be directly compared with official optimized configurations or speculative decoding data from previous models.

Subsequently, we also started an isolated SGLang 0.5.16b1 instance using the same FP8 checkpoint, the same nodes, and TP=8. In the third round, after limiting model loading concurrency and reserving a 60-minute window for the startup probe, it became Ready successfully, and the minimal deterministic request returned correct results. This proves that SGLang can run this FP8 checkpoint on this hardware, but it has not yet formed a performance A/B strictly aligned with vLLM parameters.

After the single-node baseline, we also added a vLLM P/D separation experiment on two `8 × H20 141 GB` nodes: Prefill and Decode each use TP=8, passing KV Cache through NIXL, and switching only the UCX TCP and RDMA data planes while keeping the model, nodes, routing, and load-test workload unchanged. The results show that RDMA increases NIXL's Rank aggregation transfer rate by approximately 21.9×, and improves output throughput by approximately 22% in the 4K Prompt scenario; however, tail latency at short prompts with concurrency 8 clearly regresses, so "KV transfers faster" cannot be directly equated with "all requests are faster."

## 1. Why a single 8-GPU node can fit the model

The [vLLM official GLM-5.2 Recipe](https://github.com/vllm-project/recipes/blob/main/models/zai-org/GLM-5.2.yaml) gives a model scale of approximately 743B total parameters and 39B activated parameters, with a minimum GPU memory requirement of approximately 893 GB for native FP8 weights, and explicitly lists the `8 × H200/H20 141GB` single-node solution.

The nominal GPU memory of eight 141 GB H20s totals approximately 1.1 TB. After TP=8, each rank not only stores approximately one-eighth of the weights, but also needs space for KV Cache, CUDA Graph, communication buffers, and framework runtime. The observations in this round are as follows:

| Item | Measured or configured |
| --- | ---: |
| GPU | 8 × NVIDIA H20 141 GB |
| TP | 8 |
| Weight shards | 141 Safetensors |
| vLLM-reported per-rank model loading memory | 89.93 GiB |
| Per-GPU memory after startup stabilization | approximately 132 GiB |
| Available KV Cache per rank | 25.37 GiB |
| GPU KV Cache capacity | 504,960 tokens |
| Estimated maximum concurrency at 131,072 context | 3.85× |

Subtracting nominal capacity can only answer "is there a chance to fit it," and cannot replace actual startup measurements. In particular, the 39B activated parameters must not be mistaken for the full weight scale; MoE inference only activates a subset of experts per token, but the full service still needs to store all expert weights required by the model.

## 2. Deployment structure and version checks

This round did not use SGLang, nor did it call the secondary wrapper `start.sh` in the image. AIBrix handles model discovery and request routing, and vLLM handles model loading, TP=8, and generation:

```text
OpenWebUI / benchmark client
              │
              ▼
        AIBrix Gateway
              │
              ▼
   HTTPRoute → DNS-safe Service
              │
              ▼
       vLLM Pod, TP=8
              │
              ▼
  8 × H20 141 GB + 共享模型目录
```

The actual container versions are vLLM `0.26.0b2.dev1` and Transformers `5.14.1`. The following three points were verified before deployment:

1. The vLLM model registry contains `GlmMoeDsaForCausalLM`;
2. The shared directory can read the model configuration, tokenizer, index, and all 141 weight shards;
3. No independently importable `deep_gemm`/`deepgemm` package was found in the image, so it is defined as a generic compatibility baseline rather than an official H20 extreme-performance image.

The standard startup command is as follows; the model path and image should be replaced with actual values in the target environment:

```bash
vllm serve /models/GLM-5.2-FP8/v1 \
  --host 0.0.0.0 \
  --port 8000 \
  --tensor-parallel-size 8 \
  --served-model-name glm-5.2-fp8-vllm \
  --kv-cache-dtype fp8 \
  --gpu-memory-utilization 0.90 \
  --max-model-len 131072 \
  --max-num-seqs 16 \
  --max-num-batched-tokens 32768 \
  --tool-call-parser glm47 \
  --reasoning-parser glm45 \
  --enable-auto-tool-choice \
  --enable-prefix-caching
```

The resource manifest also needs to explicitly request eight GPUs and configure `nodeSelector`, `affinity`, and precise `tolerations` according to the target node's isolation policy. Do not use overly broad `Exists` tolerations to bypass scheduling; they can easily place experiment Pods into unintended isolated nodes.

## 3. An easy-to-hit AIBrix routing naming issue

When the model name uses `glm-5.2-fp8-vllm`, the AIBrix Gateway Plugin looks up the HTTPRoute by `<model-name>-router`, i.e.:

```text
glm-5.2-fp8-vllm-router
```

HTTPRoute names allow periods, but Kubernetes Services use the stricter DNS-1035 label and cannot directly use a model name with periods. If automation simultaneously creates a Service using the model name, or deletes the conventionally named Route and creates an arbitrary-named Route instead, it may encounter Service creation failure or Gateway returning 503, respectively.

The naming approach verified in this round is:

```yaml
modelName: glm-5.2-fp8-vllm
httpRouteName: glm-5.2-fp8-vllm-router
serviceName: glm52-fp8-vllm-aibrix
```

The Route retains the AIBrix conventional name, and `backendRefs` points to a DNS-safe Service. For cross-namespace scenarios, `ReferenceGrant` precisely authorizes that Service. After the fix, both `Accepted` and `ResolvedRefs` of the HTTPRoute are `True`, and both `/v1/completions` and `/v1/chat/completions` return 200.

## 4. Where cold-start time goes

This was a cold start with an image cache miss and the model mounted through a shared file system. From Pod creation to model Ready took approximately 17 minutes:

| Stage | Measured |
| --- | ---: |
| First pull of approximately 13.1 GB image | 2 min 18 s |
| Loading 141 weight shards | 386.50 s |
| vLLM-reported model loading stage | 391.78 s |
| `torch.compile` | 104.56 s |
| Initial profiling / warm-up | 38.42 s |
| Pod creation to Ready | approximately 17 min |

These line items cannot be mechanically summed: there are sequential dependencies among container creation, storage mounting, process initialization, and the final 32K-token CUDA Graph warm-up, and there is also overlap in log scopes. What should actually be used for SLO is `Pod created → first correct response`, not an isolated `weights loaded`.

In this round, the compilation cache was placed in `emptyDir` and will not be reused after Pod recreation. This means an image cache hit only saves pull time; weights will still be re-read, compiled, and warmed up. To compress rolling update time later, node NVMe model caches, persistent compilation caches with compatibility fingerprints, and warm-up completion before accepting traffic should each be verified separately.

## 5. Correctness and OpenWebUI integration

Verification was performed in three layers:

1. Direct connection to the vLLM Pod: a deterministic Chinese request returns the expected text;
2. Request through the AIBrix Gateway: the response carries routing information for the actual target Pod, and the text is correct;
3. Request from the OpenWebUI Pod using its already configured AIBrix OpenAI-compatible address: the model appears in `/v1/models`, and the Chinese conversation returns the expected text.

Therefore, "registering with OpenWebUI" here does not require modifying the OpenWebUI Deployment again for each model. As long as OpenWebUI is already connected to AIBrix's `/v1` address, AIBrix can discover the new model and route correctly, and OpenWebUI will automatically see it through the model list. This round did not restart OpenWebUI, avoiding meaningless configuration perturbation.

If the model does not appear, troubleshoot in the following order:

```text
vLLM /v1/models
  → AIBrix /v1/models
  → HTTPRoute Accepted / ResolvedRefs
  → OpenWebUI 使用的 Base URL
  → OpenWebUI 持久化配置是否覆盖环境变量
```

## 6. Four benchmark groups consistent with previous runs

The load-test client is inside the model Pod, but all requests are sent to the AIBrix Gateway rather than directly to the local port. It uses `vllm bench serve`, random dataset, `temperature=0`, `ignore-eos`, and unlimited request arrival rate; each group performs an independent warm-up first, then collects official results.

`C` in the table is the client's maximum concurrent request count. It is not the total number of users, nor is it the server-side batch size.

| Scenario | Requests succeeded | req/s | Output tok/s | p50/p95/p99 TTFT | p95 TPOT | p95 ITL | p95 E2EL |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 128 in / 64 out, C=1 | 16/16 | 1.02 | 65.24 | 216 / 225 / 225 ms | 12.13 ms | 14.02 ms | 989 ms |
| 128 in / 64 out, C=4 | 32/32 | 2.44 | 156.41 | 577 / 743 / 755 ms | 22.86 ms | 17.35 ms | 1,680 ms |
| 128 in / 64 out, C=8 | 64/64 | 3.42 | 218.80 | 442 / 3,239 / 3,241 ms | 52.46 ms | 22.62 ms | 4,514 ms |
| 4096 in / 128 out, C=4 | 16/16 | 0.64 | 81.99 | 4,411 / 4,416 / 4,417 ms | 40.52 ms | 17.39 ms | 6,321 ms |

All four groups had zero failures. For short requests, increasing from C=1 to C=8 raises total output throughput by approximately 3.35×, but p95 TTFT increases from approximately 225 ms to 3.24 s, and p95 TPOT increases from 12.13 ms to 52.46 ms. At concurrency 8, the current configuration is already clearly trading single-request tail latency for total throughput. The p95 TTFT for 4K input is 4.42 s, making Prefill the dominant latency source.

The single-request scenario's output throughput is 65.24 tok/s, but p95 TPOT of 12.13 ms corresponds to approximately 82 tok/s in the stable Decode phase; the two metrics have different scopes—the former includes TTFT and the full round-trip duration—and cannot be conflated as the same number.

### 6.1 Two-node P/D: TCP vs RDMA comparison

The single-node baseline answered whether the model can fit and the performance range of ordinary colocated service. The next step is to verify: when Prefill and Decode each occupy a full eight-GPU node, can RDMA-accelerated KV Cache transfer translate into end-to-end gains?

The experimental topology is as follows. There are two complete model instances here, rather than splitting one TP=16 engine into two roles:

```text
Benchmark Client
       │
       ▼
 AIBrix P/D Router
       │
       ├─ Prefill：Node A，8 × H20 141 GB，TP=8
       │       │
       │       └─ NIXL + UCX：传输 KV Cache
       │                         │
       └─ Decode：Node B，8 × H20 141 GB，TP=8
```

The main software and parameters are as follows. The distribution method of model weights, cluster identifiers, node addresses, image registries, namespaces, and ingress configuration are outside the public scope of this document:

| Item | Configuration |
| --- | --- |
| Model | GLM-5.2 FP8, same Revision |
| GPU | Two nodes, 8 × H20 141 GB each, 16 total |
| Engine | vLLM 0.26.0, Prefill TP=8, Decode TP=8 |
| KV Connector | NIXL 1.3.2, FP8 KV Cache, Recompute allowed on failure |
| P/D routing | AIBrix 0.7.0, fixed Prefill/Decode role pairing |
| Context and batching | 131,072; `max_num_seqs=16`; `max_num_batched_tokens=32768` |
| RDMA group | `UCX_TLS=rc,cuda_copy,cuda_ipc`, 8-way ConnectX-7 |
| TCP control group | `UCX_TLS=tcp,cuda_copy,cuda_ipc` |

The control experiment changes only `UCX_TLS`, without changing nodes, GPUs, model, routing, load-test client, or vLLM parameters. Pods in the TCP group can still discover RDMA devices, but UCX is restricted to TCP; the RDMA port count before and after the test is completely unchanged, avoiding a false control where "TCP is nominally configured but RDMA is actually used."

The load test still uses `vllm bench serve`, exact random lengths, `temperature=0`, `ignore-eos`, and unlimited request arrival rate. Each group first completes warm-up at the same concurrency, then runs one round with each of two different seeds: C=1 is 16 requests per round, C=4 is 32 requests, C=8 is 64 requests, and 4K input is 16 requests. TCP and RDMA together total 512 official requests, with 0 failures.

The following is the arithmetic mean of the same metric across the two rounds. The p95 here is the "average of two independent p95 values," not a p95 recomputed from merged raw samples of both rounds; small-sample tail latency can only be used to identify trends, not to replace long-duration stability testing.

| Scenario | TCP output tok/s | RDMA output tok/s | Throughput change | TCP p95 TTFT | RDMA p95 TTFT | TTFT change | TCP p95 E2EL | RDMA p95 E2EL | E2EL change |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 128 in / 64 out, C=1 | 58.39 | 60.22 | +3.1% | 566 ms | 479 ms | -15.3% | 1,326 ms | 1,239 ms | -6.5% |
| 128 in / 64 out, C=4 | 177.55 | 177.29 | -0.1% | 1,445 ms | 1,597 ms | +10.5% | 2,375 ms | 2,530 ms | +6.5% |
| 128 in / 64 out, C=8 | 287.89 | 255.85 | -11.1% | 786 ms | 2,806 ms | +257.2% | 2,076 ms | 4,079 ms | +96.5% |
| 4096 in / 128 out, C=4 | 77.89 | 95.03 | **+22.0%** | 6,279 ms | 4,531 ms | **-27.8%** | 8,166 ms | 6,597 ms | **-19.2%** |

The two rounds of tail latency for C=1 and C=4 both show noticeable fluctuation, so stable gains cannot be claimed from them. The RDMA fallback at C=8 and the RDMA gains for 4K Prompt, however, are directionally consistent across both rounds:

- For short prompts at high concurrency, the KV data volume is small, and routing, batching, P/D synchronization, connection state, and queue jitter are enough to cover the network gains; the current C=8 result indicates this configuration still needs tuning;
- For 4K Prompt, Prefill produces more KV, making network transfer more likely to enter the critical path. RDMA reduces p95 TTFT by about 28%, ultimately yielding about 22% output throughput and about 19% p95 E2EL gains;
- TPOT mainly describes the steady-state Decode phase, and the TPOT directions from the two 4K tests in this round are not fully consistent. RDMA optimizes KV transfer after Prefill, so it cannot be expected to stably improve per-token Decode time.

### 6.2 How to Prove the Data Plane Actually Traversed RDMA

Merely seeing both the P/D Pods receive HTTP requests does not prove that KV Tensors were transferred over RDMA. This round also cross-checked NIXL metrics against hardware counters on the eight RDMA ports:

| Same-scale full round | NIXL transferred data | NIXL cumulative `xfer_time` | Rank-aggregated effective rate |
| --- | ---: | ---: | ---: |
| TCP | ~32.81 GB | 136.284 s | ~0.241 GB/s |
| RDMA | 33.25 GB | 6.295 s | ~5.28 GB/s |

By this measure, RDMA's NIXL Rank-aggregated effective transfer rate is approximately **21.9x** that of TCP. A clarification is needed: `bytes / sum(xfer_time)` aggregates all eight TP Ranks and is a framework-level metric for same-topology A/B comparison, not the physical line rate of a single NIC. In the RDMA round, the aggregate send counter across the eight ports increased by approximately 38.18 GB, consistent in direction with the NIXL metric; in the TCP round, after all requests completed, the RDMA port counters remained unchanged. Neither transport recorded any failures.

Finally, we also connected directly to the Decode instance and had it compute the Prompt locally without providing the remote `kv_transfer_params`. `128 in / 64 out，C=1` yielded 65.58 output tok/s, p95 TTFT 220 ms, p95 E2EL 981 ms, with no growth in NIXL transfer counters, essentially matching the 65.24 tok/s, 225 ms, and 989 ms from Section 6. This check confirms that the earlier single-machine baseline can still serve as a directional reference; however, this process still loaded the NIXL Connector and used the Recompute fallback, so it should not be packaged as a brand-new, fully independent pure-colocated Engine A/B.

The most important conclusion from this data set is not "RDMA is definitely faster," but rather: **RDMA has reduced large-block KV transfer from a clear bottleneck to a minor cost, but end-to-end gains depend on Prompt length, concurrency, P/D capacity ratio, and scheduling synchronization.** The next round should use a fixed RPS ladder, at least five repetitions, and phase-level traces to separate queueing time, Prefill, KV transfer, first token, and Decode; it should also separately test UCX NIC binding, connection warm-up, and Prefill/Decode-independent `max_num_seqs` and `max_num_batched_tokens`.

## 7. Static Comparison with the Existing SGLang W4AFP8 Configuration

To avoid impacting production workloads, no liveness, inference, or load-test requests were sent to the existing SGLang GLM-5.2 service, and its Deployment was not modified. The following conclusions are drawn only from sanitized image versions, resource specifications, and startup parameters, and do not represent measured performance rankings.

The main differences between the two current configurations are as follows:

| Dimension | vLLM baseline in this document | Existing SGLang W4AFP8 configuration | Parameter effect |
| --- | --- | --- | --- |
| Weight quantization | Native FP8 | W4AFP8 | W4 reduces weight GPU memory and read bandwidth, allowing the model to fit on 96 GB H20; FP8 typically retains higher quality headroom |
| KV Cache | `fp8` | `fp8_e4m3` | Both expand capacity via low-precision KV; long-context quality still needs evaluation |
| Context limit | 131,072 | 204,800 | Higher limit enables longer requests, but does not mean every concurrency level can reach the limit |
| Concurrency limit | 16 | 32 | Higher limit benefits throughput and continuous batching, but may also amplify queueing and tail latency |
| Speculative decoding | Not enabled | EAGLE, 3 steps, up to 4 draft tokens | Reduces large-model Decode steps when acceptance rate is high enough; currently the most obvious speed variable |
| Prefix / tiered cache | Prefix Cache | HiCache + in-memory KV Cache | HiCache mainly expands KV capacity and reuse scope; does not guarantee hot KV is faster than HBM |
| GPU memory ratio | 0.90 | 0.85 | SGLang reserves more runtime headroom; vLLM gives more GPU memory to KV/runtime |
| Shared Expert Fusion | Default engine implementation | Explicitly disabled | Usually a compatibility or correctness workaround; may lose some MoE fusion gains |

The most valuable takeaway from the SGLang configuration is not the single "FP4" parameter, but the following combination:

```text
W4AFP8 权重量化
  + FP8 E4M3 KV Cache
  + EAGLE 推测解码
  + 更高的运行请求上限
  + HiCache 分级 KV Cache
```

Its main advantages fall on different objectives: W4AFP8 reduces GPU memory cost and weight bandwidth, EAGLE optimizes Decode, `max-running-requests` improves scheduling concurrency, and HiCache trades host memory for larger KV capacity. They cannot all be interpreted as "faster per request." For example, raising concurrency from 16 to 32 may increase total throughput but worsen p95 TTFT; HiCache's `write_through` enhances recoverability and capacity but also adds write traffic.

### 7.1 Is FP8 Better Than FP4

A total ranking cannot be given by bit width alone:

- When quality, complex reasoning, tool calling, and quantization risk take priority, native FP8 is the safer choice;
- When single-replica GPU cost, 96 GB card fit, and replica scale take priority, W4AFP8 has the advantage;
- Per-request Decode speed mainly depends on effective kernels, speculative decoding acceptance rate, and memory bandwidth; FP4 does not automatically become faster;
- High-concurrency throughput is also affected by Scheduler, Batch, KV capacity, and business length distribution, and cannot be derived directly from weight precision.

Therefore, the vLLM FP8 in this document and the existing SGLang W4AFP8 are not a strict engine A/B, but two different quality, cost, and performance combinations. If testing is done in the future, isolated instances and separate Service/Route should be created, production services must not be used, and the experiments should be split into two groups:

1. **Engine A/B**: same FP8 Checkpoint, hardware, context, KV precision, speculative decoding, and load-test traffic, changing only vLLM/SGLang;
2. **Solution A/B**: vLLM FP8 vs. SGLang W4AFP8, reporting correctness, EAGLE acceptance rate, GPU memory, throughput, TTFT, TPOT, and per-request cost simultaneously.

The static analysis phase can only confirm that the SGLang parameters lean toward "96 GB fit, long context, tiered KV, and speculative decoding"; it cannot be used to claim it is faster than the current vLLM FP8. Measured results from the later isolated instance are in 7.2.4; since the client dataset and Engine parameters still differ, that data is still not a strict A/B changing only the inference engine.

### 7.2 SGLang Startup Experiment with the Same FP8 Checkpoint

To separate the weight quantization and inference engine variables, we also created an independent SGLang 0.5.16b1 instance, still using the native FP8 Checkpoint from this document, `8 × H20 141 GB`, TP=8, 131K context, and FP8 E4M3 KV Cache. This instance did not reuse or load-test the existing production service.

The third round was started using SGLang's built-in front-end entry point, without calling the secondary wrapper `start.sh` in the image:

```bash
python3 -m sglang.launch_server \
  --model-path /models/GLM-5.2-FP8/v1 \
  --host 0.0.0.0 \
  --port 8000 \
  --tp-size 8 \
  --served-model-name glm-5.2-fp8-sglang-test \
  --kv-cache-dtype fp8_e4m3 \
  --reasoning-parser glm45 \
  --tool-call-parser glm47 \
  --context-length 131072 \
  --mem-fraction-static 0.85 \
  --model-loader-extra-config '{"enable_multithread_load":false}' \
  --speculative-algorithm EAGLE \
  --speculative-num-steps 3 \
  --speculative-eagle-topk 1 \
  --speculative-num-draft-tokens 4 \
  --max-running-requests 32
```

The `python -m sglang.launch_server` in the image remains usable, but 0.5.16b1 already indicates that the equivalent `sglang serve` entry point is preferred. The model was recognized as `GlmMoeDsaForCausalLM` with an FP8 Checkpoint; the eight TP Ranks completed NCCL 2.28.9 initialization in about 18 seconds, and SGLang automatically selected `flashmla_kv` as the Prefill/Decode Attention Backend for DSA.

### 7.2.1 Why We Still Waited More Than Twenty Minutes After `141/141`

The `model.safetensors.index.json` records for this Checkpoint total 755,617,140,416 Bytes, approximately 703.7 GiB. The log line:

```text
Loading safetensors checkpoint shards: 141/141
```

only reflects one Rank responsible for outputting progress having traversed all 141 shards; it does not prove that all eight Ranks finished loading. This progress bar reached 100% in about 70 seconds this round, but observation via `/proc/<scheduler-pid>/io` showed that other Schedulers continued to generate actual disk reads, and the port was not yet listening.

The `read_bytes` across all processes ultimately totaled approximately 704 GiB, roughly matching the Checkpoint size. Physical I/O being attributed mainly to some Ranks is an accounting artifact of Linux page cache and concurrent disk reads, and does not mean only those GPUs were loading the model. Startup can only be judged successful when all of the following conditions are met:

```text
全部 Rank 完成权重与 Kernel 初始化
              ↓
HTTP 端口开始监听
              ↓
Pod Ready=True
              ↓
/v1/models 正确 + 一次正确生成
```

The main timeline for this round is as follows:

| Phase | Observed result |
| --- | ---: |
| Pod creation to eight Ranks starting to load | ~66 seconds |
| Single visible progress bar traversing 141 shards | ~70 seconds |
| Full weight read and load phase | ~23 minutes |
| First DeepGEMM JIT, warm-up, and service initialization | ~3 minutes |
| Pod creation to Ready | 27 min 20 s |
| Per-GPU memory after Ready | 127,688–128,168 MiB, ~124.7–125.2 GiB |
| Remaining GPU memory after Ready | ~15.5 GiB |

The node had already gone through two previous loading rounds this cycle, so the Linux page cache state was not strictly cold; therefore, 27 min 20 s cannot be treated as a general shared-storage cold-start result. However, it does show that watching only one Safetensors progress bar underestimates ready time by an order of magnitude.

### 7.2.2 Loading Concurrency, JIT, and Probes

The `sglang/srt/model_loader/loader.py` in this image defaults to allowing 8 loading threads per Rank. With TP=8, this can amplify one Pod's cold model read into roughly 64-way concurrent I/O:

```text
8 个 TP Rank × 每 Rank 8 个加载线程
                  │
                  ▼
      约 64 路共享文件系统读取
                  │
        ┌─────────┴─────────┐
        ▼                   ▼
  CFS 吞吐与元数据压力    Rank 完成时间分叉
                            │
                            ▼
                   所有 Rank 同步等待
```

The first round used the default loading method and still was not Ready after about 24 minutes; the second round disabled multithreading and was proactively stopped at about 10 minutes to control shared filesystem pressure. The third round continued with single-threaded loading and waited to completion, ultimately reaching Ready. Disabling multithreading reduced instantaneous concurrency but did not eliminate the 755.6 GB weight read volume, so it is a storage protection measure, not a cold-start acceleration conclusion.

After weight loading completed, SGLang entered DeepGEMM JIT Pre-Compile for the first time. The Runtime explicitly noted that without pre-running `sglang.compile_deep_gemm`, this phase can typically take 10–20 minutes; this round actually took about a few minutes. Future images should pre-compile with the same model, TP, and GPU architecture as the formal startup, and manage the generated cache using the following fingerprint:

```text
SGLang commit + SGL Kernel + CUDA/Driver
  + GPU compute capability + TP
  + 模型 Revision/量化方式 + Kernel 参数
```

Compilation directories must not be reused across versions or GPU types. This round also found that the image lacked the corresponding JSON configuration for Triton 3.6 on H20 FP8 MoE; the Runtime fell back to the Triton 3.5.1 configuration and warned that performance may not be optimal. Before formal load testing, this configuration should be added or verified to avoid treating fallback kernel results as the SGLang ceiling.

Probe configuration must cover weight loading, all-Rank synchronization, JIT, KV Cache, and CUDA Graph:

| Probe | This round's setting | Behavior on failure |
| --- | --- | --- |
| Startup | TCP 8000, every 10 s, `failureThreshold=360` | Restart container only after ~60 min of failure |
| Liveness | TCP 8000, every 30 s, 3 consecutive failures | Restart container |
| Readiness | TCP 8000, every 10 s, 3 consecutive failures | Remove traffic only, no restart |

Before the Startup Probe succeeds, Liveness and Readiness will not interfere with a long cold start. This round's Pod remained `RESTARTS=0` throughout. If the Startup window still used the default of a few minutes typical of ordinary web services, the process would be repeatedly killed just as a 700 GB-class model was about to finish loading, creating a "never starts" restart loop.

After service startup, we also observed cluster collection components accessing `/metrics` returning 404. This is because the test command did not enable SGLang Metrics; it does not affect the OpenAI-compatible inference interface. When integrating monitoring formally, `--enable-metrics` should be added, and the scrape interval should be confirmed so it does not generate a meaningless 404 log storm.

### 7.2.3 Correctness Results and Conclusion Boundaries

The Pod reached `1/1 Running` with 0 restarts, and `/v1/models` returned:

```json
{"id":"glm-5.2-fp8-sglang-test","owned_by":"sglang","max_model_len":131072}
```

We then sent a minimal request with `temperature=0` and Thinking disabled to the Loopback address of the isolated test Pod, requesting only `FP8_OK`, and received the exact `FP8_OK`. This proves that the standard SGLang 0.5.16b1, TP=8, native FP8 weights, and EAGLE parameter combination at least passed model loading and basic generation validation.

This round sent no liveness or load-test requests to the existing production SGLang GLM service. The isolated instance subsequently completed load tests at the same length and concurrency tiers as the vLLM baseline, but this is still not a parameter-aligned engine A/B. What the startup experiment can confirm:

- `141/141` cannot serve as the readiness condition for a multi-Rank service; the port, Ready status, and one correct inference response should all be checked;
- Large-model loading concurrency needs to be estimated by `Pod 数 × TP Rank × 每 Rank 线程数`, not just by Pod count;
- Disabling multithreading can reduce instantaneous concurrency, but may also sacrifice per-Rank throughput; it is not a final optimization;
- Startup probes should cover the slowest Rank, KV Cache initialization, compilation, and CUDA Graph, not just weight progress;
- First-time DeepGEMM JIT and H20 MoE kernel configuration affect cold start and final performance, and need separate governance at image build time;
- Strict cold-start testing must distinguish shared-storage cold reads, Linux page cache hits, and node-local cache hits.

In the same time window, another already-Ready inference replica experienced a restart, so initially we could only confirm temporal overlap between shared filesystem pressure and the failure; correlation cannot be written as causation. Subsequent host and Runtime log verification has ruled out CFS as the direct root cause; full evidence is in the next section.

A more robust next-round approach is to first warm the model to node-local NVMe by Revision, then start SGLang from NVMe; simultaneously set a global download concurrency cap, persist and pre-generate DeepGEMM/Triton caches, and record each Rank's load completion time, storage throughput, `Pod created → first correct response`, and cache state. The shared filesystem remains the authoritative source and fallback path, and multiple TP Ranks should no longer form unbounded concurrent cold reads directly at business startup.

### 7.2.4 Isolated Load Test via AIBrix Gateway

After the service is Ready, first confirm the AIBrix-side routing status: the HTTPRoute corresponding to the test model has `Accepted=True` and `ResolvedRefs=True`, and the AIBrix Gateway `/v1/models` already lists `glm-5.2-fp8-sglang-test`. A deterministic request was then sent through the Gateway and accurately returned `AIBRIX_OK`. Therefore, OpenWebUI instances already connected to this AIBrix `/v1` address will automatically discover the model through the model list, with no need to save the Pod IP or modify the OpenWebUI Deployment for each model.

The load test did not access the existing production SGLang GLM service. The client ran inside an isolated model Pod, and all requests were sent to the AIBrix Gateway. SGLang's `random` dataset implementation attempts to download the ShareGPT corpus from Hugging Face, but the test network cannot reach the external internet; therefore, this round switched to a fully offline `random-ids` and fixed `random-range-ratio=1` to ensure precise request lengths. The structure of the formal command is as follows:

```bash
python3 -m sglang.benchmark.serving \
  --backend sglang-oai \
  --base-url http://<AIBRIX_GATEWAY> \
  --model /models/GLM-5.2-FP8/v1 \
  --served-model-name glm-5.2-fp8-sglang-test \
  --tokenizer /models/GLM-5.2-FP8/v1 \
  --dataset-name random-ids \
  --num-prompts <REQUESTS> \
  --random-input-len <INPUT_TOKENS> \
  --random-output-len <OUTPUT_TOKENS> \
  --random-range-ratio 1 \
  --request-rate inf \
  --max-concurrency <CONCURRENCY> \
  --temperature 0 \
  --warmup-requests <CONCURRENCY> \
  --disable-tqdm
```

All four request groups succeeded. After the load test, the Pod remained Ready with 0 restarts, and deterministic text `BENCH_OK` was again returned through AIBrix:

| Scenario | Requests Succeeded | req/s | Output tok/s | p50/p95/p99 TTFT | p95 TPOT | p95 ITL | p95 E2EL |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 128 in / 64 out, C=1 | 16/16 | 1.47 | 94.24 | 248 / 260 / 262 ms | 10.10 ms | 17.60 ms | 895 ms |
| 128 in / 64 out, C=4 | 32/32 | 2.24 | 143.44 | 274 / 766 / 775 ms | 31.41 ms | 263.38 ms | 2,481 ms |
| 128 in / 64 out, C=8 | 64/64 | 3.24 | 207.56 | 273 / 529 / 614 ms | 49.29 ms | 265.57 ms | 3,424 ms |
| 4096 in / 128 out, C=4 | 16/16 | 0.69 | 88.66 | 1,212 / 3,665 / 3,665 ms | 44.16 ms | 888.73 ms | 7,887 ms |

Directional comparison against the vLLM baseline from Section 6:

| Scenario | SGLang change relative to vLLM | Observation |
| --- | --- | --- |
| 128/64, C=1 | Output throughput approximately `+44%`, p95 TPOT approximately `-17%`, p95 E2E approximately `-10%` | Low-concurrency Decode benefits most clearly |
| 128/64, C=4 | Output throughput approximately `-8%`, p95 TPOT approximately `+37%`, p95 E2E approximately `+48%` | Medium concurrency actually regresses under current parameters |
| 128/64, C=8 | Output throughput approximately `-5%`, p95 TTFT approximately `-84%`, p95 E2E approximately `-24%` | Total throughput is close, but tail queuing improves noticeably |
| 4096/128, C=4 | Output throughput approximately `+8%`, p95 TTFT approximately `-17%`, p95 E2E approximately `+25%` | Prefill is faster, but full-request tail latency does not improve in step |

The ITL here cannot be directly ranked numerically against the vLLM table: EAGLE may accept and stream back multiple tokens at once, so what the SGLang client observes is the interval between response chunks, which is not exactly equivalent to the per-token Decode interval. More importantly, this comparison changed multiple variables at the same time:

- vLLM uses `random`, while SGLang uses the offline `random-ids`; lengths are identical but token contents differ;
- SGLang has EAGLE enabled, while the vLLM baseline has no MTP/DSpark;
- `mem-fraction-static`, maximum number of in-flight requests, Scheduler, and Kernel paths differ;
- SGLang currently also falls back to the Triton 3.5.1 H20 FP8 MoE configuration.

Therefore, these four data groups cannot support the conclusion that "SGLang is comprehensively faster than vLLM." The more accurate conclusion at present is: SGLang shows advantages in single-request and C=8 tail latency, but C=4 and long-input scenarios still have significant room for parameter tuning. The next strict A/B round should reuse the same batch of Token IDs, send requests to two isolated backends respectively, and first disable speculative decoding on both sides; after obtaining the engine baseline, separately compare the gains and acceptance rates of EAGLE versus MTP/DSpark.

### 7.2.5 Supplementary Validation of Long Context, EAGLE, and Request Teardown

To avoid re-reading the 700 GiB of weights every time a feature is validated, subsequent tests opened the following within the same startup window:

```text
--enable-metrics
--enable-metrics-for-all-schedulers
--enable-cache-report
```

This time the Pod reached Ready in approximately 28 minutes, after which the `/health` first response waited another approximately 4 seconds. The TCP Startup/Readiness Probe can only prove that the port is open, so the production cold-start SLO should still use `Pod created → first correct response`; `Ready=True` alone cannot be treated as business-available time.

After weight loading completed, the main JIT artifacts generated by the Runtime are located at:

```text
/root/.cache/deep_gemm/cache/
/root/.cache/tvm-ffi/
```

The former includes SM90 FP8 GEMM and Paged MQA Kernels, and the latter includes SGL Kernel artifacts such as DSA TopK, quantization, RoPE, and custom AllReduce. Together they total only a few MiB, but this time `/root/.cache` uses `emptyDir`, so they will still be lost after Pod recreation; the production image should precompile or persist them after establishing a compatibility fingerprint based on SGLang, SGL Kernel, CUDA, GPU architecture, TP, and model quantization method, and must not reuse them across versions without validation.

#### Functional Correctness

The isolated instance sequentially passed the following OpenAI-compatible tests:

- Deterministic output with Thinking disabled;
- With Thinking enabled, both `reasoning_content` and the correct final answer are returned;
- JSON Schema constrained output that can be parsed by a standard JSON Parser;
- GLM47 tool-call parsing, with both function name and arguments correct;
- After the client actively cancels upon receiving the first streaming Chunk, the service still returns `/health 200`.

The Thinking use case also exposed a client parameter issue: with `max_tokens=128`, the reasoning process consumes the entire output budget and the final `content` is empty; after raising it to 512, the final answer is returned normally. Therefore, Thinking models cannot continue to use the low output cap used for ordinary short answers.

#### Long-Context Needle Retrieval

With a unique key embedded in the middle of the Prompt and only that key queried at the end, the following results were obtained:

| Server-side Prompt Tokens | Full Request Time | Result |
| ---: | ---: | --- |
| 3,766 | 12.61 s | Exact hit |
| 30,049 | 12.56 s | Exact hit |
| 60,086 | 17.17 s | Exact hit |
| 117,345 | 32.46 s | Exact hit |

This proves that 131K is not just a declared value in `/v1/models`; at least 117K actual input can complete Prefill and retrieval. However, the four test groups ran sequentially, the texts share a common prefix, and the Radix Cache was not cleared before each round, so this can only serve as capacity and correctness validation; the times cannot be treated as strict cold-Prefill performance.

#### EAGLE Acceptance Rate Under Varying Load

The Metrics actually returned the following indicators, rather than merely having command-line parameters enabled:

```text
sglang:spec_verify_calls_total
sglang:spec_accept_rate
sglang:spec_accept_length
```

`spec_accept_rate` is the ratio of accepted Draft Tokens to proposed Draft Tokens; `spec_accept_length` additionally includes the Bonus Token from each Verify round. Observations under different loads are as follows:

| Load | Acceptance Rate | Average Accepted Length |
| --- | ---: | ---: |
| Natural output such as Chinese explanations, code, math | Approximately 73%–83% | 3.20–3.48 |
| Single-Token short requests | Approximately 35% | 2.05 |
| AIBrix-path C=8 mixed requests, running approximately 2 minutes | Approximately 77% | 3.31 |

This shows that EAGLE is already effectively reducing a portion of Target Model Decode, but the benefit clearly depends on the corpus and output length. Subsequent work must bucket production requests by acceptance rate and compare against a same-corpus baseline with EAGLE disabled; a single high acceptance rate cannot be used to directly derive overall benefit.

#### Direct-Connection vs. AIBrix Path

After the streaming client encountered an anomaly, a directional comparison was first completed using non-streaming `128 in / 32 out / C=4` requests with the same Seed:

| Path | Succeeded | req/s | Output tok/s | Average E2E | p95 E2E |
| --- | ---: | ---: | ---: | ---: | ---: |
| Direct SGLang | 16/16 | 0.72 | 23.00 | 4.34 s | 5.02 s |
| AIBrix Gateway | 16/16 | 0.81 | 25.85 | 4.59 s | 5.72 s |

Non-streaming responses cannot yield real TTFT, ITL, or TPOT, so these fields should not participate in the comparison. In the small sample, the Gateway's total throughput was actually higher, but average and p95 E2E were slower, indicating that runtime jitter is already large enough that two sequential executions cannot quantify pure routing overhead.

Subsequently, the same single-Token request was alternated for 20 rounds to reduce sequential bias:

| Path | Median E2E | Average E2E | p95 E2E |
| --- | ---: | ---: | ---: |
| Direct SGLang | 3.31 s | 3.35 s | 3.98 s |
| AIBrix Gateway | 3.63 s | 3.56 s | 4.28 s |
| Gateway - Direct | +327 ms | +214 ms | +303 ms |

This increment is higher than ordinary TCP forwarding, but the client runs inside the model Pod, and the path is a loopback topology of "model Pod → Gateway → same model Pod," which simultaneously includes AIBrix routing, cross-node networking, and two rounds of business serialization. It can only show that the current experimental path has a visible cost; locating the overhead still requires interleaved runs from an independent load-test client, a larger sample, and Router Trace.

#### Streaming Teardown Handling Is the Current Blocker

This round reproduced twice that the Engine had already completed the request but the client could not exit:

```text
SGLang 原生 /generate 或 OpenAI 流式请求
                  ↓
GPU 完成生成，Metrics 显示 running=0、queue=0
                  ↓
客户端仍停在 socket poll / event loop 等待结束
```

The problem appeared both in the native `/generate` and in the `sglang-oai` `/v1/completions` streaming benchmark; switching to non-streaming completed successfully. After actively canceling the streaming request, the service remained healthy, suggesting the current evidence points more toward end-frame, connection-close, or Runtime-client protocol teardown issues rather than the GPU still computing. It cannot yet be asserted that the root cause is definitely EAGLE; controlled experiments with EAGLE disabled, full SSE frame capture, verification of `[DONE]`, client timeouts, and SGLang version-corresponding Issue checks must be completed.

The planned 5-minute C=8 mixed stability test was actively stopped at approximately 2 minutes because the node needed to be released immediately; before stopping, the Pod remained Ready with 0 restarts and queue length 0, but no complete request statistics were formed, so this cannot be written as "5-minute stability passed." The test Deployment was then scaled down to 0, the isolated Pod was deleted, and the Service, Route, and deployment materials were retained for subsequent re-testing.

### 7.3 SGLang Crash Behind `Completed / exit 0`

During the shared file system loading experiment, another group of already-Ready Qwen3.5-397B SGLang TP=8 instances repeatedly restarted. Kubernetes showed the container status as `Completed` with exit code `0`, and the end of the application standard output usually contained only `destroy_process_group() was not called before program exit`, which at first made the failure look like a normal exit triggered by external probes, node OOM, or storage pressure.

Such problems cannot be left at `kubectl logs --previous`. We entered the host Mount Namespace through the operational DaemonSet on the node and read-only verified the kernel, kubelet, and container runtime logs:

```bash
kubectl -n <NODE_AGENT_NAMESPACE> exec <NODE_AGENT_POD> -- \
  nsenter --mount=/proc/1/ns/mnt -- bash -lc '
    journalctl -k --since "<START_TIME>" --until "<END_TIME>" --no-pager |
    grep -Ei "oom|out of memory|killed process|NVRM: Xid|nfs: server|rpc.*timeout|I/O error|hung task"
  '
```

The investigation covered all nodes where the failing instances resided, with the following results:

- No OOM record matched the SGLang Pod UID;
- No NVIDIA Xid, CFS/NFS/RPC timeout, I/O error, or hung task;
- kubelet and containerd only observed the container main process ending and recorded exit code `0`; most exits had no preceding Liveness Probe failure or `StopContainer` event;
- After the shared file system loading test stopped, this group of instances continued crashing in the same pattern.

A Memory Cgroup OOM did appear on the same node, but the UID ultimately mapped to the network DaemonSet's Pod, not SGLang. That cgroup's memory limit was approximately 200 MiB, with the main consumption coming from kernel slab, and the process ultimately killed was the network proxy. In the kernel stack, `GFP_NOFS` indicates that memory allocation was not allowed to recursively enter the file system reclaim path, and `xfs_vm_readpages` indicates local XFS Page Cache reads; neither can serve as evidence that CFS caused the OOM. **Occurring on the same node at similar times does not mean they belong to the same Pod or the same failure chain.**

The real anomaly was preserved in the SGLang logs persisted via HostPath. All five replicas showed the same call stack at different times:

```text
eagle_worker_v2.verify()
  -> prepare_mamba_track_for_verify()
  -> set_mamba_track_indices_from_reqs()
  -> torch.tensor([req.mamba_next_track_idx ...])

TypeError: 'NoneType' object cannot be interpreted as an integer
```

The failure occurred in the EAGLE speculative decode and Hybrid Mamba Radix Cache path of SGLang `0.5.15b1`. When some requests entered the Verify stage, `req.mamba_next_track_idx` was still `None`, yet the code directly used it to construct the `int64` Tensor. After one Scheduler first became abnormal, all TP Schedulers exited, the Tokenizer Manager received `SIGQUIT`, and the Runtime then actively called `kill_process_tree`. Business requests sometimes had already returned HTTP 200 before the service process exited during the request teardown phase, so client success rate alone cannot prove instance health either.

```text
请求完成并返回 200
        |
        v
EAGLE Verify 读取未初始化的 Mamba Track Index
        |
        v
8 个 TP Scheduler 抛出 TypeError
        |
        v
父进程收到 SIGQUIT 并清理进程树
        |
        v
外层 Shell/tee 返回 0 -> Kubernetes 显示 Completed
```

The reason the container shows `Completed / exit 0` is compounded by the startup script masking the error code: the Engine is launched in the background by `nohup`, and the outer layer uses `start 2>&1 | tee -a ...` to collect logs but does not preserve the Engine's exit code. After the Engine process tree terminates, `tee` correctly reads EOF, and the Pipeline ultimately returns `0`. Therefore, production startup scripts should make the Runtime the foreground main process, or at minimum enable `pipefail`, explicitly `wait`, and propagate the child process exit code.

This is not an intermittent issue unique to this environment. The SGLang community has already documented the same Qwen3.5/Mamba, speculative decoding, and `NoneType` call stack, and merged protective logic in [PR #27998](https://github.com/sgl-project/sglang/pull/27998): when the Track Index has not been initialized, the first Ping-Pong Slot is used. Related reproductions can be found in [Issue #28312](https://github.com/sgl-project/sglang/issues/28312) and [Issue #28484](https://github.com/sgl-project/sglang/issues/28484). A newer image tag does not necessarily mean the fix is included; you should still verify against the source Commit or image Digest whether the target code already has the `None` Guard.

The recommended handling order is as follows:

1. During emergency recovery, disable EAGLE/NEXTN speculative decoding, remove the `--speculative-*` parameter, and first verify the stability of the normal Decode path;
2. Merge the fix corresponding to SGLang PR #27998 into the official image, and pin the source Commit, SGLang/SGL Kernel/CUDA versions, and image Digest;
3. In an isolated instance, regression-test short requests, long prompts, Prefix Cache hits, structured output, tool calls, and request cancellation, and observe the Scheduler, GPU Xid, cgroup OOM, and real process exit codes;
4. Fix the startup script and alert rules to distinguish between `Completed`, proactive process exit, Probe Kill, OOMKill, and node failures;
5. Treat the small-memory cgroup slab OOM in the network DaemonSet as a separate issue to address, and do not conflate it with this SGLang Runtime crash.

## 8. What This Data Shows

It demonstrates seven things:

- GLM-5.2 FP8 can be loaded with TP=8 on a single eight-GPU H20 141 GB node using standard vLLM;
- AIBrix does not require the backend to be SGLang; it can discover and route to a vLLM Engine;
- The AIBrix Gateway completions, chat, and OpenWebUI paths are all functionally correct;
- SGLang 0.5.16b1 can also complete loading, structured output, tool calls, and 117K long-context retrieval on the same FP8 Checkpoint with single-node TP=8;
- On the baseline without MTP/DSpark, increasing concurrency improves total throughput, but tail latency degrades quickly;
- vLLM Prefill/Decode can each occupy one eight-GPU node, with cross-node KV transfer via NIXL;
- RDMA can significantly improve the effective transfer rate of the KV data plane and improve long-Prompt performance, but the current short-Prompt high-concurrency configuration may still exhibit end-to-end regression.

It does not yet prove that vLLM is faster than SGLang, nor does it represent the optimal performance of the official GLM-5.2 on H20. The next round of strict A/B testing should change only one variable at a time:

1. Current vLLM baseline versus native MTP `num_speculative_tokens=5`;
2. Current generic image versus the official optimized build with DeepGEMM;
3. Distribute the model to node-local NVMe first, then have vLLM and SGLang use the same Revision, context, KV precision, concurrency, and speculative decoding strategy;
4. Direct vLLM versus through the AIBrix Gateway, to quantify the gateway's own overhead;
5. Three cold-start states: shared filesystem cold read, node NVMe hit, and persistent compilation cache hit;
6. Fixed RPS ramp for P/D, more repetitions, and staged traces, to locate the RDMA tail-latency regression for short requests at C=8.

Until these A/B tests are completed, the current service is suitable as a usable baseline for AIBrix + vLLM, but should not directly replace the existing production path.

Further reading:

- [Large Model Weight Distribution and Loading Acceleration](model-weight-delivery-acceleration.md)
- [From Half an Hour to Five Minutes: Full-Pipeline Optimization of Large Model Cold Start](llm-cold-start-optimization.md)
- [DeepSeek-V4-Flash-0731 H20 Deployment and Load Testing](deepseek-v4-flash-h20-evaluation.md)
- [Deploying AIBrix on an Existing Kubernetes Cluster](aibrix-existing-cluster.md)
