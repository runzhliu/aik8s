---
title: "Qwen3.8-27B Day 0: vLLM and SGLang Test Record"
description: "Records Qwen3.8-27B official FP8 artifacts, vLLM and SGLang images, single-card L20 Kubernetes testing, OpenWebUI integration, and subsequent MTP and long-context A/B"
status: draft
last_reviewed: 2026-08-19
---

# Qwen3.8-27B Day 0: vLLM and SGLang Test Record

> This article was created on the second day after the official weights were released, validating Qwen3.8-27B through two runtime paths: vLLM and SGLang. Both paths have completed FP8 deployment, correctness checks, AIBrix integration, four sets of short-duration performance baselines under identical conditions, MTP 1/2/3 A/B, and 32K/64K/128K long-context capacity curves on a single NVIDIA L20 in the test cluster; vLLM also completed real OpenWebUI conversations. Vision remains the next phase, and this article will clearly distinguish between "actually tested" and "pending testing."

My first real immersion in heavy vibe coding came after Claude Opus 4.5 was released. I had used models to write code before, but Opus 4.5's ability to handle complex requirements, cross-file modifications, and long autonomous execution gave me, for the first time, a very strong sense that "the way we develop has changed." The shock wasn't from a piece of beautiful code, but from the model's ability to continuously understand intent, call tools, spot problems, and close out tasks.

Later I started using Opus 4.6. When I saw that the official Qwen3.8-27B model card placed this 27B open-weight model on the same Coding Benchmark table as Opus 4.6, with higher scores in some entries, my first reaction was indeed shock: have 27B open models really come this far?

But "leading on some leaderboards" cannot be simplified into "comprehensively surpassing in all coding capabilities." This Day 0 experiment first records its configuration differences, interface behavior, and performance data when using vLLM and SGLang on a fixed L20 environment, then gradually expands to Coding, Agent, and long-context testing.

## 1. First, calibrate what "coding on par with Opus 4.6" means

In the coding comparison from Qwen's official model card, Qwen3.8-27B and `Opus4.6 Max` each win some and lose some:

| Benchmark | Qwen3.8-27B | Opus4.6 Max | What this table can tell us |
| --- | ---: | ---: | --- |
| SWE-bench Pro | 61.7 | 53.4 | In Qwen's official evaluation, Qwen3.8-27B leads by 8.3 points |
| Terminal-Bench 2.1 (Terminus) | 73.0 | 78.2 | Opus4.6 Max still leads by 5.2 points |
| NL2Repo-Bench | 42.3 | 47.6 | Opus4.6 Max still leads by 5.3 points |
| QwenSWEBench | 79.0 | 63.8 | Qwen3.8-27B leads, but this is a Qwen-built benchmark and must await independent reproduction |
| DeepSWE 1.1 | 42.2 | Not reported | Cannot draw horizontal conclusions |

The most reasonable interpretation of these numbers is that Qwen3.8-27B has entered the range where it deserves direct head-to-head comparison with frontier closed-source coding models, rather than already deterministically beating Opus 4.6 on every kind of coding task. Three boundaries should also be noted:

1. The table comes from Qwen's official evaluation, not from actual testing in this article, nor from independent third-party reproduction;
2. The evaluation pipeline, Effort, tools, and context configuration for `Opus4.6 Max` must be identical to the Qwen side to form a rigorous A/B;
3. The Anthropic release page emphasizes Opus 4.6's overall improvement in long-horizon Agent tasks, codebase operations, Review, and Debug; a single static benchmark cannot cover the real vibe coding experience.

Therefore, this article splits "coding capability" into four layers: short-code correctness, repo-level modification, tool calling and recovery, and long-horizon Agent tasks. High throughput does not mean good code, and high leaderboard scores do not mean stable serving.

## 2. Model facts confirmed the day after release

The official repository shows that Qwen3.8-27B is built on the Qwen3.5 architecture and is a 27B Dense model with a vision encoder:

| Item | Confirmed value |
| --- | --- |
| Hugging Face architecture | `Qwen3_5ForConditionalGeneration` |
| `model_type` | `qwen3_5` |
| Parameter count | 27B; official repository counts approximately 27.78B parameters |
| Number of layers | 64 |
| Attention | 48 layers Gated DeltaNet + 16 layers Gated Attention |
| Native context | 262,144 tokens |
| Extended context | Up to approximately 1,000,000 tokens via YaRN |
| Modalities | Text, image, video |
| Thinking | Enabled by default; supports `xhigh`, `medium`, `low` reasoning effort |
| MTP | Checkpoint includes native Multi-Token Prediction module |

The official release provides both BF16 and fine-grained FP8 weights. Artifact information read on August 15, 2026:

| Artifact | Revision | Safetensors | Weight bytes | Approx. GiB | First-round use |
| --- | --- | ---: | ---: | ---: | --- |
| `Qwen/Qwen3.8-27B-FP8` | `017b9c7af6b5689d5dd426a76e0bc077eb5ca20a` | 66 | 30,866,866,928 | 28.75 | L20 first-round baseline |
| `Qwen/Qwen3.8-27B` | `1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0` | 18 | 55,563,006,776 | 51.75 | Precision and resource comparison |

The FP8 model card declares 128×128 block E4M3 fine-grained quantization with a dynamic Activation Scheme; the vision module, Embedding, LM Head, LayerNorm, and some other modules remain at non-FP8 precision. Therefore, 28.75 GiB cannot be directly equated to final GPU memory usage; unquantized modules, KV Cache, CUDA Graph, Workspace, and framework runtime must also be added.

## 3. Why vLLM 0.26.0 CUDA 12.9 was chosen for the first round

The official vLLM Qwen3.8 Recipe marks this architecture as supported in vLLM `0.17.0+` and provides FP8, BF16, MTP, and 1M YaRN examples. The first round uses the following pinned image:

```text
vllm/vllm-openai:v0.26.0-cu129
linux/amd64 manifest:
sha256:3c5c53248febaa72823a4b7e51aafa1cd2b65d860392e3930414da4d3864f541
```

Reasons for choosing it:

- `v0.26.0` is the currently available stable version; do not use an unpinned `nightly` as the first variable;
- `cu129` matches the existing L20 CUDA 12.9 experimental environment, avoiding a simultaneous CUDA 13 upgrade;
- The model configuration is still registered as the already-supported `Qwen3_5ForConditionalGeneration`;
- If the stable version fails on Chat Template, Vision, MTP, or new configuration fields, switch to the pinned-commit `cu129-nightly-*` and record the failure evidence in the report.

After the image enters the internal registry, the upstream tag, platform, and digest mapping must be preserved. This article does not record real Registry domain names or credentials; examples are uniformly written as:

```text
<STAGING_REGISTRY>/<PROJECT>/vllm-openai:v0.26.0-cu129
```

The actual image preparation results on August 15, 2026:

| Step | Result |
| --- | --- |
| Upstream multi-architecture index | `sha256:976b4ba10e247dbe5c5ce3e2ba952a359ef641ee25c3d091811c1bec420e5a23` |
| Local pinned platform | `linux/amd64` |
| amd64 Manifest | `sha256:3c5c53248febaa72823a4b7e51aafa1cd2b65d860392e3930414da4d3864f541` |
| Staging | Single-platform Manifest push succeeded; Digest matches upstream amd64 |
| Production sync | Internal image service task returned success; specific task ID and Registry address are not written into the public article |

This time, instead of performing an unstable cross-network Registry-to-Registry long connection, we first executed `docker pull` with platform constraints, confirmed the Manifest locally, then tagged and pushed to staging, and finally had the internal image service complete the staging-to-production copy:

```bash
docker pull --platform linux/amd64 vllm/vllm-openai:v0.26.0-cu129
docker image ls --tree vllm/vllm-openai:v0.26.0-cu129
docker tag vllm/vllm-openai:v0.26.0-cu129 \
  <STAGING_REGISTRY>/<PROJECT>/vllm-openai:v0.26.0-cu129
docker push --platform linux/amd64 \
  <STAGING_REGISTRY>/<PROJECT>/vllm-openai:v0.26.0-cu129
```

This does not reduce the initial download data volume, but local Layer Cache, segmentable verification, and subsequent internal server-side copying remove home VPN instability from the staging → production path.

### 3.1 Image static pre-check

Before requesting GPU resources, first confirm the version, CUDA, model registration, and key CLI parameters:

```bash
python3 -c 'import torch, transformers, vllm; print(torch.__version__, torch.version.cuda, transformers.__version__, vllm.__version__)'

python3 -c 'from vllm.model_executor.models import ModelRegistry; print("Qwen3_5ForConditionalGeneration" in ModelRegistry.get_supported_archs())'

vllm serve --help=all | grep -E 'language-model-only|speculative-config|reasoning-parser|tool-call-parser|kv-cache-dtype'
```

If `v0.26.0-cu129` cannot read the official Revision, prioritize recording the full Traceback, Transformers version, and unknown fields before deciding whether to switch to nightly; do not temporarily `pip install -U` inside a running container, or the image digest will lose reproducibility.

## 4. L20 first-round results and subsequent tests

The first round fixes TP=1, 32K, text-only, FP8 KV, MTP Off, and records GPU memory allocation, KV Cache, and initialization data on a single 48 GB L20 as the baseline for subsequent A/B tests.

| Item | L20 measured the day after release |
| --- | --- |
| GPU | NVIDIA L20, `nvidia-smi` shows 46,068 MiB |
| Weight loading | 66 Safetensors shards, CephFS read 20.18 s |
| Model loading GPU memory | 27.64 GiB |
| Torch Compile | 62.16 s |
| Engine initialization | 156.47 s |
| KV Cache | 8.69 GiB, capacity 219,666 tokens |
| 32K theoretical max concurrency | vLLM Profile gives 6.70× |
| CUDA Graph | 0.89 GiB |
| Peak Activation | 2.62 GiB |

The first round still found two warnings that cannot be ignored: the L20 (SM89) did not hit the W8A8 Block FP8 tuning configuration for several shapes in the current image and fell back to the default kernel; the K/V/Probability Scale for FP8 KV had no calibration values from the Checkpoint, and vLLM fell back to 1.0. This means the current results are a runnable baseline, not "already tuned"; subsequent `KV Auto vs FP8` quality and performance A/B is mandatory.

Going forward, we still insist on changing only one variable at a time:

| Phase | Weights | GPU | Context | Vision | MTP | Goal |
| --- | --- | ---: | ---: | --- | --- | --- |
| P0 | Config only | 0 | No service start | Off | Off | Image, architecture, and parameter static pre-check |
| P1 | Official FP8 | 1×L20 | 32K | Off | Off | **Completed**: text, Thinking, Tool Call, AIBrix, OpenWebUI |
| P2 | Official FP8 | 1×L20 | 32K | Off | Off | KV Auto/FP8, long-run stability, and real request set |
| P3 | Official FP8 | 1×L20 | 32K | On | Off | Image understanding and Vision GPU memory delta |
| P4 | Official FP8 | 1×L20 | 32K | Per runtime baseline | 1/2/3 tokens | **Completed**: acceptance rate, throughput, TPOT, and concurrency capacity |
| P5 | Official FP8 | 1×L20 | 64K/128K | As needed | As needed | Long-context path and resource cost |
| P6 | Official BF16 | 2×L20 | 32K | Off | Off | FP8 correctness, GPU memory, and performance comparison |

Subsequent tests still use the same L20 environment as the baseline; MTP A/B is complete, and the next steps add context length, vision, and quality request sets one at a time, avoiding mixing different hardware and different runtime parameters into the same set of results.

NVFP4 community quantization can serve as a consumer-grade or Blackwell-path supplement, but it should not be conflated with this round's L20 FP8 baseline. GGUF/llama.cpp is suitable for Mac or CPU prompt and Agent interface smoke tests, but it cannot replace vLLM/SGLang throughput testing on datacenter GPUs.

## 5. Minimal vLLM startup baseline

The model should be pre-synced to a read-only PVC, shared filesystem, or node cache; do not let every Pod rebuild cold-download from Hugging Face. The first-round text baseline recommendation:

```bash
vllm serve /models/Qwen3.8-27B-FP8 \
  --host 0.0.0.0 \
  --port 8000 \
  --served-model-name qwen3-8-27b-fp8-l20 \
  --tensor-parallel-size 1 \
  --max-model-len 32768 \
  --gpu-memory-utilization 0.90 \
  --max-num-seqs 8 \
  --max-num-batched-tokens 8192 \
  --kv-cache-dtype fp8 \
  --language-model-only \
  --reasoning-parser qwen3 \
  --enable-auto-tool-choice \
  --tool-call-parser qwen3_coder \
  --enable-prefix-caching \
  --enable-chunked-prefill
```

If the target image does not have `--language-model-only`, switch to explicitly disabling image/video input according to the actual parameters of `vllm serve --help`, and record the difference. Do not copy parameters from other versions' documentation into production without validating the CLI.

MTP must be added as an independent A/B:

```bash
--speculative-config '{"method":"mtp","num_speculative_tokens":3}'
```

Test at least 1, 2, and 3 Draft Tokens. Reporting only final tokens/s is meaningless; Mean Acceptance Length, per-position acceptance rate, TTFT, TPOT, and GPU power draw must also be recorded. When the acceptance rate is insufficient, MTP may add verification overhead rather than speedup.

## 6. Kubernetes deployment and shared model storage

Actual deployment uses the existing read-only shared model storage, with the model root mounted as `/models` and the Checkpoint located at `/models/Qwen3.8-27B-FP8`. Public examples uniformly use a PVC named `qwen38-models` and do not include internal storage addresses, volume paths, or Secret names.

The `examples/qwen38-27b-l20-vllm/deployment.yaml` in the repository preserves a publicly reproducible checklist: upstream image Digest, generic PVC, 16 GiB `/dev/shm`, Compile Cache, Probes, AIBrix labels, and full vLLM parameters. The following is the same public skeleton:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: qwen38-27b-vllm
  namespace: <NAMESPACE>
spec:
  replicas: 1
  strategy:
    type: Recreate
  selector:
    matchLabels:
      app: qwen38-27b-vllm
  template:
    metadata:
      labels:
        app: qwen38-27b-vllm
    spec:
      terminationGracePeriodSeconds: 120
      nodeSelector:
        <GPU_NODE_LABEL_KEY>: <GPU_LABEL_VALUE>
      tolerations:
        - key: <GPU_TAINT_KEY>
          operator: Equal
          value: <GPU_TAINT_VALUE>
          effect: NoSchedule
      containers:
        - name: vllm
          image: <STAGING_REGISTRY>/<PROJECT>/vllm-openai:v0.26.0-cu129
          imagePullPolicy: IfNotPresent
          command: ["vllm", "serve"]
          args:
            - /models/Qwen3.8-27B-FP8
            - --host
            - "0.0.0.0"
            - --port
            - "8000"
            - --served-model-name
            - qwen3-8-27b-fp8-l20
            - --tensor-parallel-size
            - "1"
            - --max-model-len
            - "32768"
            - --gpu-memory-utilization
            - "0.90"
            - --max-num-seqs
            - "8"
            - --max-num-batched-tokens
            - "8192"
            - --kv-cache-dtype
            - fp8
            - --language-model-only
            - --reasoning-parser
            - qwen3
            - --enable-auto-tool-choice
            - --tool-call-parser
            - qwen3_coder
            - --enable-prefix-caching
            - --enable-chunked-prefill
          ports:
            - name: http
              containerPort: 8000
          resources:
            requests:
              cpu: "16"
              memory: 64Gi
              nvidia.com/gpu: "1"
            limits:
              cpu: "32"
              memory: 128Gi
              nvidia.com/gpu: "1"
          startupProbe:
            httpGet:
              path: /health
              port: http
            periodSeconds: 10
            failureThreshold: 180
          readinessProbe:
            httpGet:
              path: /health
              port: http
            periodSeconds: 5
            failureThreshold: 6
          volumeMounts:
            - name: model
              mountPath: /models/Qwen3.8-27B-FP8
              readOnly: true
            - name: shm
              mountPath: /dev/shm
      volumes:
        - name: model
          persistentVolumeClaim:
              claimName: <MODEL_VOLUME>
        - name: shm
          emptyDir:
            medium: Memory
            sizeLimit: 16Gi
---
apiVersion: v1
kind: Service
metadata:
  name: qwen38-27b-vllm
  namespace: <NAMESPACE>
spec:
  selector:
    app: qwen38-27b-vllm
  ports:
    - name: http
      port: 8000
      targetPort: http
```

The public skeleton uses PVC and does not disclose the underlying storage implementation. If the existing environment still uses in-tree CephFS, note that it was deprecated in Kubernetes v1.28, became unavailable starting v1.31, and plan migration to Ceph CSI. `failureThreshold: 180 × 10s` provides a startup window of up to 30 minutes; the real cold-start SLO is recorded in `Pod created → first correct response`.

## 7. Correctness acceptance precedes performance stress testing

### 7.1 Service and deterministic text

```bash
curl -sS http://127.0.0.1:8000/v1/models

curl -sS http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "qwen3-8-27b-fp8-l20",
    "messages": [{"role": "user", "content": "只回复 QWEN38_OK"}],
    "temperature": 0,
    "max_tokens": 32,
    "chat_template_kwargs": {
      "enable_thinking": false,
      "preserve_thinking": false
    }
  }'
```

Thinking is enabled by default; do not just check for HTTP 200. Verify separately:

- When `enable_thinking=false`, the response contains only the final answer;
- When `enable_thinking=true`, the reasoning and content field boundaries are correct;
- `reasoning_effort=low/medium/xhigh` is correctly passed through the API and Chat Template;
- In multi-turn requests, when `preserve_thinking` is preserved or disabled, historical `<think>` is not incorrectly concatenated into the final content.

On the day after release, four API acceptance checks were completed: with Thinking disabled, the API strictly returned `QWEN38_OK`; with Thinking enabled and set to Low, it correctly determined `9.9 > 9.11`, returning Reasoning and Content in separate fields; the weather function generated structured `get_weather({"city":"北京"})`; after backfilling tool results, it generated the correct natural-language answer. The AIBrix Gateway again returned `AIBRIX_QWEN38_OK`, confirming that access is not limited to Pod Loopback.

### 7.2 Tool Calling

At minimum, cover: single tool, parallel tools, recovery after tool errors, missing required parameters, tool result backfill, and multi-turn continued execution. The acceptance focus is not "XML appearing" but that the OpenAI-compatible response contains a structurally correct `tool_calls`, the parameters are parseable, and the model can continue the task after tool results are returned.

### 7.3 OpenWebUI Registration and Real Conversation

The model automatically generates a Router through the AIBrix label, after which `qwen3-8-27b-fp8-l20` is added to the AIBrix API configuration in OpenWebUI. The final test is not just checking the dropdown, but initiating a real conversation through the desensitized access entry point and receiving a model response.

![Qwen3.8-27B-FP8 registered in the OpenWebUI model selector](../../assets/practices/qwen38-27b-l20-vllm/03-openwebui-model-selector.png)

![Real invocation of Qwen3.8-27B-FP8 on a single L20 via OpenWebUI](../../assets/practices/qwen38-27b-l20-vllm/02-openwebui-qwen38-chat.png)

### 7.4 Vision and Video

After the P1 text baseline passes, remove `--language-model-only` and test separately:

1. Description of a single 1024×1024 image;
2. Chart/document Q&A;
3. Multi-image ordering and referencing;
4. Short video sampling;
5. Tool calling after visual input.

For each item, record the GPU memory added by the Vision Encoder, TTFT, and preprocessing time. Image download time must not be counted as model Prefill.

## 8. Load Test Matrix

### 8.1 Fixed Input/Output and Concurrency Steps

The first round reuses the length conventions of the existing GPU report for horizontal comparison, but is not used directly for model ranking:

| Scenario | Input/Output | Concurrency | Primary Observation |
| --- | --- | --- | --- |
| Decode baseline | 128 / 64 | 1, 4, 8, 16 | TPOT, ITL, per-GPU output tok/s |
| Balanced requests | 1024 / 1024 | 1, 4, 8 | Prefill/Decode balance, throughput inflection point |
| Prefill baseline | 4096 / 128 | 1, 4, 8 | TTFT, Chunked Prefill |
| Medium context | 32768 / 256 | 1, 2, 4 | KV usage, TTFT, stability |
| Long context | 64K/128K/262K | 1 | Needle, OOM boundary, Graph/JIT |

To preserve per-GPU concurrency on the public instance, the runtime context remains limited to 32,768 tokens in daily use. To confirm whether longer windows are actually usable, this round temporarily restarts the same service as 64K and 128K candidates in sequence, completes the C=1 capacity curves for `31K+1K`, `63K+1K`, and `127K+1K`, then restores 32K. The actual weight's `max_position_embeddings` is 262,144; the official model card for the corresponding architecture also defines 262K as the native context, and recommends maintaining at least 128K when GPU memory is insufficient, to preserve Thinking capability for complex tasks. Beyond the 128K random-token test, both engines passed Needle retrieval at the 10%/50%/90% positions; detailed results are in 9.2.2.

Example command:

```bash
vllm bench serve \
  --backend openai \
  --base-url http://127.0.0.1:8000 \
  --endpoint /v1/completions \
  --model qwen3-8-27b-fp8-l20 \
  --tokenizer /models/Qwen3.8-27B-FP8 \
  --dataset-name random \
  --num-prompts 64 \
  --num-warmups 8 \
  --random-input-len 128 \
  --random-output-len 64 \
  --ignore-eos \
  --temperature 0 \
  --request-rate inf \
  --max-concurrency 8 \
  --percentile-metrics ttft,tpot,itl,e2el \
  --metric-percentiles 50,95,99 \
  --save-result
```

Unlimited request-rate is used to find saturated throughput and does not represent real business traffic. Formal capacity experiments must also include fixed arrival-rate steps, e.g., 0.5, 1, 2, 4, 8 req/s, with each level sustained for 10–30 minutes, to identify where p95/p99 latency and error rates begin to rise sharply.

### 8.2 Mandatory A/B Tests

| A/B | Fixed Variables | Only Change | Conclusion Goal |
| --- | --- | --- | --- |
| MTP | FP8, TP, length, concurrency | Off / 1 / 2 / 3 Draft Tokens | Whether acceptance rate translates into TPOT gains |
| KV precision | FP8 weights, TP, length | Auto / FP8 KV | Capacity gains, quality and performance cost |
| Prefix Cache | Same request set | Off / On | Hot-prefix TTFT and GPU memory changes |
| TP | FP8, total request set | TP=1 / 2 / 4 | Whether latency gains justify more GPUs |
| Weight precision | Same model Revision family | FP8 / BF16 | Correctness, GPU memory, throughput differences |
| Modality | FP8, TP, text parameters | Text-only / Vision | Incremental cost of Vision |

The TP A/B must report both total tokens/s and tokens/s/GPU. Using four GPUs to double throughput does not mean resource efficiency improved.

### 8.3 Agent and Coding Tests

Beyond performance load tests, a fixed set of real workloads must also be prepared:

- Read-only repository understanding: locate cross-module call chains and provide explanations with file evidence;
- Small fix: reproduce a bug, modify code, run tests;
- Medium feature: cross frontend/backend and database migration, requiring preservation of existing behavior;
- Review: identify logic, security, concurrency, and compatibility issues;
- Long-running Agent: allow tool calls and failure recovery, with total time and token limits;
- Vibe coding: generate a runnable page from a natural-language requirement, and verify via browser or screenshot.

To form a meaningful comparison with personal Opus 4.5/4.6 experience, the evaluation flow, system prompt, tool permissions, repository Revision, time limit, maximum tokens, and acceptance tests must all be fixed. Record "whether completed, number of human interventions, test pass rate, elapsed time, input/output tokens"; the winner must not be chosen purely by subjective impression.

## 9. Observation and Result Recording Template

Each round must retain at least the following raw evidence:

```text
镜像 tag + manifest digest
模型 repo + revision + 文件校验
GPU 型号、显存、驱动、CUDA、拓扑
vLLM / PyTorch / Transformers / NCCL 版本
完整启动参数与环境变量
Pod created / weights loaded / compile done / API ready / first correct response 时间
请求长度、并发、request-rate、随机种子和结果 JSON
GPU 利用率、显存、功耗、PCIe/NVLink、CPU、内存、存储读取
错误日志、OOM、Xid、超时、重试和客户端失败
```

### 9.1 Runtime Startup

| Engine | Stage | Measured | Cache Condition | Notes |
| --- | --- | ---: | --- | --- |
| vLLM | Weight read | 20.18 s | Shared CephFS | 66 shards |
| vLLM | Engine Init | 156.47 s | Empty Compile Cache | Includes loading, Compile, Profile/Warmup |
| vLLM | Compile/JIT | 62.16 s | Empty Compile Cache | Sub-stage of Engine Init |
| SGLang | Weight read | 14.46 s | Shared CephFS | 66 shards; model itself occupies 28.47 GB |
| SGLang | Decode CUDA Graph | 30.89 s | Prefill Graph disabled | bs 1/2/4/6 |
| SGLang | API Ready | ~122 s after Pod | Runtime startup | Includes built-in warmup; health check returns 200 |

SGLang's "successful API Ready" came from the second Pod. The first Pod, after successfully allocating weights, GDN/Mamba state, and FP8 KV, hit an OOM during default prefill CUDA Graph capture. Therefore, the 122 seconds of the second startup must not be conflated with "success on first try with default configuration."

### 9.2 vLLM × SGLang Steady-State Performance

| Engine | Input/Output | Client Concurrency | Success/Total | req/s | Input tok/s | Output tok/s | p50/p95/p99 TTFT | p95 TPOT | p95 ITL | p95 E2EL | Observed GPU Memory |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: |
| vLLM | 128/64 | 1 | 64/64 | 0.27 | 34.81 | 17.41 | 112.54 / 116.81 / 121.18 | 56.58 | 59.36 | 3,680.15 | 41,315 MiB |
| SGLang | 128/64 | 1 | 64/64 | 0.30 | 38.53 | 19.26 | 179.74 / 225.45 / 226.11 | 50.57 | 51.10 | 3,366.33 | 43,521 MiB |
| vLLM | 128/64 | 4 | 64/64 | 1.11 | 141.69 | 70.84 | 263.83 / 268.06 / 272.54 | 53.18 | 55.88 | 3,617.59 | 41,315 MiB |
| SGLang | 128/64 | 4 | 64/64 | 1.25 | 160.25 | 80.12 | 215.33 / 216.67 / 217.72 | 47.35 | 48.00 | 3,198.97 | 43,521 MiB |
| vLLM | 128/64 | 8 | 64/64 | 2.10 | 268.71 | 134.35 | 406.21 / 431.89 / 432.24 | 55.62 | 56.65 | 3,830.99 | 41,315 MiB |
| SGLang | 128/64 | 8 | 64/64 | 1.75 | 224.08 | 112.04 | 290.96 / 3,631.79 / 3,632.26 | 48.44 | 49.11 | 6,681.54 | 43,521 MiB |
| vLLM | 4096/128 | 4 | 32/32 | 0.33 | 1,369.14 | 42.79 | 4,181.61 / 4,688.75 / 4,689.32 | 76.57 | 57.37 | 12,109.06 | 41,315 MiB |
| SGLang | 4096/128 | 4 | 32/32 | 0.35 | 1,445.36 | 45.17 | 5,220.82 / 5,239.00 / 5,240.64 | 58.36 | 48.77 | 11,357.74 | 43,521 MiB |

Both groups use the same vLLM 0.26.0 `vllm bench serve` client, the same Tokenizer, seed, random inputs, fixed output length, and `request-rate=inf`; SGLang is accessed via ClusterIP in the same Namespace, while vLLM is accessed via Pod Loopback, so the numbers do not include gateway or public-network RTT. All 448 measured requests succeeded.

At 128/64 with client concurrency 1 and 4, SGLang output throughput is approximately 10.7% and 13.1% higher than vLLM respectively, with lower TPOT as well; at client concurrency 8, exceeding SGLang's auto-reduced 6-slot limit, output throughput is instead about 16.6% lower, and p95 TTFT stretches from 431.89 ms to 3.63 s. At 4096/128, SGLang output throughput is about 5.6% higher, but with prefill CUDA Graph disabled, p50 TTFT is about 24.9% higher. The vLLM 4096/128 p99 ITL tail spike of 517.02 ms still requires long-run stability re-verification.

This is not a strictly isomorphic A/B of "both default parameters": vLLM uses `--language-model-only`; SGLang loads the full multimodal model, and the default prefill CUDA Graph was separately disabled due to L20 OOM. The results describe the actual behavior of the two currently runnable configurations, but cannot be used to directly infer general Engine superiority. Raw JSON is saved in `examples/qwen38-27b-l20-vllm/results/` and `examples/qwen38-27b-l20-sglang/results/` respectively.

#### 9.2.1 Unified Load Test Toolchain Usability Verification

To allow subsequent DeepSeek, GLM-5.2, Combined TP=8, P/D dual TP=8, and TCP/RDMA re-tests to use the same request definitions, a [public test suite](https://github.com/runzhliu/aik8s/tree/main/examples/llm-long-context-pd-benchmark) was added to the repository. Before formally occupying large-scale GPU resources, a low-load verification was performed against the already-running Qwen3.8-27B vLLM/SGLang interfaces: the client is uniformly vLLM 0.26.0, with fixed 128 input, 64 output, C=1, one warm-up, four formal requests, the same Tokenizer and Seed.

| Engine | Success/Total | req/s | Output tok/s | p95 TTFT | p95 TPOT | p95 ITL | p95 E2EL |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| vLLM | 4/4 | 0.27 | 17.42 | 112.75 ms | 56.56 ms | 57.05 ms | 3,675.39 ms |
| SGLang | 4/4 | 0.30 | 19.10 | 175.19 ms | 50.52 ms | 51.04 ms | 3,357.38 ms |

This data only proves that case reading, fixed-length requests, both OpenAI-compatible interfaces, metric collection, JSON saving, and A/B aggregation all work end to end. Four requests are insufficient to form stable percentiles, cannot be used to claim which engine is faster, and do not replace the formal baseline of 32–64 requests per cell in the previous section. The magnitude is close to the formal C=1 results and can be used to rule out obvious calibration drift in the toolchain.

#### 9.2.2 32K, 64K, and 128K Context Curves on a Single L20

To turn "the model supports 128K" from a configuration claim into a verifiable result, this round restarted vLLM and SGLang in sequence as 32K, 64K, and 128K on the same L20, with the same Qwen3.8-27B FP8 weights, TP=1, and FP8 KV Cache. Each level changes only the runtime maximum context and runs a C=1 case that exactly fills the window:

| Window | Input | Max Output | Total Context |
| ---: | ---: | ---: | ---: |
| 32K | 31,744 | 1,024 | 32,768 |
| 64K | 64,512 | 1,024 | 65,536 |
| 128K | 130,048 | 1,024 | 131,072 |

The specific meaning of these numbers, the difference between `128/64` and `4096/128`, and why tokens, characters, and concurrency cannot be used interchangeably, are explained in the [concrete examples](https://github.com/runzhliu/aik8s/blob/main/examples/llm-long-context-pd-benchmark/TOKENS_EXPLAINED.md) in the test suite. All three levels use the same vLLM 0.26.0 benchmark client, `/v1/completions`, fixed Seed, fixed-length random inputs, `temperature=0`, `ignore-eos`, 1 warm-up, and 3 formal requests.

Both 128K candidates started successfully on the first attempt, with no OOM. vLLM loads weights occupying approximately 27.64 GiB, leaving about 8.69 GiB for KV Cache, which can hold 263,600 KV tokens; the runtime's theoretical maximum concurrency for 131,072 tokens is 2.01×. SGLang loads weights occupying approximately 28.47 GB, additionally allocating about 4.78 GB for Mamba State and 5.54 GB for FP8 KV Cache for the hybrid linear attention, which can hold 181,320 KV tokens; the internal short-request slot limit auto-reduces from 8 to 6. These slot counts must not be interpreted as the ability to run 6 concurrent 128K requests.

The random-token capacity probe results are as follows. Time units are indicated in the table headers:

| Engine | Window / Requests | Success/Total | Actual Input Tokens | Actual Output Tokens | Output tok/s | p95 TTFT (s) | p95 TPOT (ms) | p95 E2EL (s) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| vLLM | 32K / 31K+1K | 3/3 | 95,232 | 3,072 | 15.06 | 12.68 | 58.08 | 72.09 |
| SGLang | 32K / 31K+1K | 3/3 | 95,232 | 3,066 | 16.27 | 12.44 | 52.14 | 65.68 |
| vLLM | 64K / 63K+1K | 3/3 | 193,536 | 3,072 | 12.58 | 30.58 | 59.48 | 91.40 |
| SGLang | 64K / 63K+1K | 3/3 | 193,536 | 3,066 | 13.34 | 30.45 | 53.46 | 85.03 |
| vLLM | 128K / 127K+1K | 3/3 | 390,144 | 3,072 | 8.56 | 82.79 | 62.33 | 146.55 |
| SGLang | 128K / 127K+1K | 3/3 | 390,144 | 3,066 | 8.86 | 82.72 | 56.68 | 140.49 |

Both TTFT curves are clearly not linear growth:

| Engine | 32K p95 TTFT | 64K p95 TTFT | 128K p95 TTFT | 64K / 32K | 128K / 64K | 128K / 32K |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| vLLM | 12.68 s | 30.58 s | 82.79 s | 2.41× | 2.71× | 6.53× |
| SGLang | 12.44 s | 30.45 s | 82.72 s | 2.45× | 2.72× | 6.65× |

Under the same window, SGLang's p95 TTFT is only about 0.08%–1.88% lower than vLLM's, indicating that this round of ultra-long Prefill is essentially on the same order of magnitude; p95 TPOT is about 9.07%–10.23% lower, driving p95 E2EL down by about 4.13%–8.90%. SGLang's total output throughput is about 3.50%–8.01% higher, but it actually returns 3,066 tokens per tier, while vLLM returns 3,072, so this length difference cannot be ignored.

The 128K test also performed an additional Needle retrieval. After including the Chat Template, each server-side Prompt is 130,000 tokens; the keys were placed at 10%, 50%, and 90% positions in the document, and both engines returned 3/3 exact matches. This proves that the current 128K configuration can not only allocate GPU memory, but also retrieve target information from the beginning, middle, and end of long documents. However, three artificial Needles cannot replace real long-document, RAG, and code repository quality evaluations.

This set of data has four limitations that must be retained:

1. Each cell has only 3 official requests, which is a capacity and trend probe, not enough to form production-grade p95/p99;
2. The first official request of the benchmark reused the warm-up Prompt, and the first TTFT of all three tiers clearly hit the prefix cache. The table uses p95 to represent the other two cold requests, but the output throughput still mixes cold and hot requests;
3. Both runtimes reported that FP8 KV lacked a calibrated Scale and fell back to 1.0; passing the Needle test does not mean that all tasks are lossless in quality;
4. vLLM uses text mode, while SGLang loads the full multimodal model and disables the Prefill CUDA Graph, so the results are measurements of the currently runnable configurations, not a general ranking of engines.

The conclusion is: a single L20 can indeed run Qwen3.8-27B FP8 128K C=1 requests, but a cold request with 127K input takes about 83 seconds for the first token. If most business requests are far below 32K, keeping 32K daily is more beneficial for concurrency and resource utilization; only when long documents, long sessions, or repository-level context are truly needed is it worth providing 64K/128K candidates separately via routing. After the test, both public instances were restored to the 32,768-token configuration.

### 9.3 MTP

On August 17, 2026, MTP Off/1/2/3 A/B was completed on the same L20. The request shape was fixed at 128 input, 64 output, `ignore-eos=true`, `temperature=0`, `request-rate=inf`; each row had 64 requests and 8 warmups. Off used the day0 JSON with 64 requests, while MTP used a temporary copy for serial re-testing without modifying the original service. The temporary copy only reduced the Kubernetes Host Memory Request from 64 GiB to 60 GiB to fit the node's remaining scheduling resources at the time; the 128 GiB Limit, GPU, image, and all Engine parameters remained unchanged.

vLLM uses `--speculative-config '{"method":"mtp","num_speculative_tokens":N}'`:

| Draft | Output tok/s C4 / C8 | Relative to Off C4 / C8 | p95 TTFT C4 / C8 | p95 TPOT C4 / C8 | Average Acceptance Length C4 / C8 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| Off | 70.84 / 134.35 | Baseline | 268.06 / 431.89 | 53.18 / 55.62 | N/A |
| 1 | 97.28 / 169.99 | +37.3% / +26.5% | 343.73 / 450.48 | 42.71 / 48.53 | 1.80 / 1.79 |
| 2 | 110.92 / 199.37 | +56.6% / +48.4% | 354.83 / 505.94 | 39.34 / 42.37 | 2.37 / 2.42 |
| 3 | 121.93 / 205.10 | +72.1% / +52.7% | 340.20 / 522.65 | 39.48 / 43.95 | 2.94 / 2.86 |

vLLM's per-position acceptance rates under C4 are 79.53%; 74.77% / 61.89%; 77.36% / 63.00% / 53.50%, and under C8 are 79.17%; 77.14% / 64.38%; 77.16% / 59.33% / 49.65%. All three groups achieved 64/64 success, 0 restarts, and no OOM. The cost is that the Profile's theoretical maximum concurrency for 32K drops from Off's 6.70× to 5.63×, 5.06×, and 4.61×. MTP2 is currently the more balanced default candidate: C8 throughput improves by 48.4%, while MTP3 only improves by another 2.9% relative to MTP2, and p95 TPOT, TTFT, and E2EL actually regress slightly. If requests are consistently at C4 and only maximum throughput is pursued, MTP3 is still about 9.9% faster than MTP2. The Ready idle-state power sampling is about 76 W for Off and 78 W for MTP1/2/3, which cannot replace load-period power testing.

SGLang 0.5.16 uses the EAGLE path, with MTP 1/2/3 mapped to `num_steps=1/2/3`, `topk=1`, and `num_draft_tokens=2/3/4` respectively:

| MTP Steps | Internal Concurrency Limit | Output tok/s C4 | Relative to Off | p95 TTFT | p95 TPOT | Average Acceptance Length | Acceptance Rate |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Off | 6 | 80.12 | Baseline | 216.67 | 47.35 | N/A | N/A |
| 1 | 2 | 56.39 | -29.6% | 3,194.21 | 41.21 | 1.84 | 84.42% |
| 2 | 2 | 66.07 | -17.5% | 2,739.52 | 33.93 | 2.29 | 64.29% |
| 3 | 1 | 39.28 | -51.0% | 6,896.76 | 32.16 | 2.70 | 56.67% |

All three SGLang groups also passed the correctness smoke test and completed 64/64 requests, with 0 restarts and no OOM; however, the Draft Head itself loads about 5.19 GiB, and internal concurrency drops from 6 to 2/2/1. MTP1's C8 output throughput is only 57.19 tok/s, lower than Off's 112.04 tok/s, and p95 TTFT increases from 3.63 s to 7.50 s. It has been confirmed that throughput is limited by internal concurrency, so MTP2/3 did not repeat C8. The conclusion is: the current "single L20 + full multimodal + 32K" configuration is not recommended to enable SGLang MTP; the lower single-request TPOT does not translate into system throughput gains.

## 10. SGLang 0-day Delivery and Failure Records

To avoid mixing "model performance" with "vLLM engine performance," the second route fixed the official stable image `lmsysorg/sglang:v0.5.16-cu129-runtime`. Its upstream multi-architecture index is `sha256:f9a7b74fb843cb2089320fa7f09b6bc7892e3ce5da3b284134c466ed8d897a93`, and the linux/amd64 Manifest is `sha256:29f0f645122be1799a594c15907d81da326dbbe6ccd6395710a07a4292125a5f`.

The upstream amd64 image uses an OCI Manifest; the staging Registry can read it normally, but the old sync Jobservice misreports it as "source repository does not exist." Therefore, the internal delivery additionally generated a single-architecture Docker schema v2 tag that does not change layers or config. The internal Digest is not public; its difference from the upstream Digest is a Manifest serialization format change, not a change in runtime content.

SGLang mainline already includes the implementation of `Qwen3_5ForConditionalGeneration`, and the Qwen3.8 Checkpoint still uses this architecture. However, "having Architecture in the code" does not mean all optimizations should be enabled in the first round. This round will adhere to the following boundaries:

- Initial startup of the full Qwen3.8 FP8 Checkpoint, without passing `--language-only`. SGLang currently has known compatibility discussions for Qwen3.5 text-extract/language-only Checkpoints, while the official Qwen3.8 FP8 is a full Checkpoint with Vision configuration;
- MTP/EAGLE is disabled in the first round. Hybrid GDN models still have documented GPU memory utilization issues with speculative decoding; first obtain a baseline without speculation;
- Fix TP=1, 32K, FP8 KV, and the same CephFS model directory, and set the service name to `qwen3-8-27b-fp8-l20-sglang` to avoid overwriting the vLLM service currently used by OpenWebUI;
- For comparison, continue using the same `vllm bench serve` client with the same random inputs, concurrency, and output length, keeping the load-testing toolchain unchanged and only replacing the backend URL;
- If the stable version cannot parse the next-day Checkpoint, preserve the full error before switching to a nightly with a fixed date and fixed Digest; floating `latest` must not be used to draw irreproducible conclusions.

The first startup on a single L20 verified weight and KV allocation, but the default 8192-token prefill CUDA Graph OOM'd when capturing a 3328-token shape; the model weights had already been loaded successfully. The second round only set `--cuda-graph-backend-prefill disabled`, keeping decode CUDA Graph, 32K, FP8 KV, and full multimodal. This change affects the Prefill/TTFT comparison and must be disclosed separately; the fixed numbers cannot be called a fair A/B of "both sides' default parameters."

After the fix, the service completed the same core acceptance as vLLM: when Thinking is disabled, it only returns `SGLANG_QWEN38_OK`; when Thinking is enabled, the reasoning and final `323` are correctly separated; the `qwen3_coder` Parser generates structured `get_weather({"city":"北京"})`, and after tool results are filled in, it continues to answer; AIBrix automatically generates `qwen3-8-27b-fp8-l20-sglang-router`, and the gateway's real request returns `AIBRIX_SGLANG_QWEN38_OK`.

Deployment materials, day0 baseline, and MTP raw results are located at `examples/qwen38-27b-l20-sglang/`. After the load test, the Pods are `Ready=true` and `restartCount=0`. Public materials do not include nodes, Pod UIDs, internal Registry, or production image Digests; the image delivery path only retains the reproducible process of "fixed amd64 platform → staging → internal sync."

## 11. Stop Conditions and Conclusion Boundaries

Stop the load test and preserve the scene if any of the following conditions are encountered:

- Incorrect answers, repeated output, Reasoning/Content field mixing, or Tool Call parsing failures;
- GPU Xid, NVML anomalies, CUDA Illegal Memory Access, or NCCL errors;
- Host Memory, Pinned Memory, `/dev/shm`, or Ephemeral Storage approaching limits;
- After OOM, the Pod automatically restarts, causing client retries to mask real failures;
- p99 latency continues to rise but throughput no longer increases;
- MTP acceptance rate drops and TPOT shows no benefit;
- 262K/1M experiments can only start but cannot correctly complete Needle or real long-document tasks.

This article mainly provides three types of references:

1. **Configuration specifications**: image, weights, API, and Kubernetes runtime parameters;
2. **Runtime data**: context, concurrency, GPU memory, throughput, and latency;
3. **Evaluation boundaries**: continue comparing coding/Agent quality and GPU cost under a fixed evaluation process.

It cannot claim that Qwen3.8-27B has fully replaced Opus 4.6 based solely on official Benchmarks, nor can it provide production capacity based on a single short load test. This article first leaves a set of reproducible data for vLLM and SGLang in a fixed L20 environment, and will later continue to validate the actual experience with Coding, Agent, and long-context tasks.

## 12. References

- [Qwen3.8-27B Official Model Card](https://huggingface.co/Qwen/Qwen3.8-27B)
- [Qwen3.8-27B-FP8 Official Model Card](https://huggingface.co/Qwen/Qwen3.8-27B-FP8)
- [Qwen3.5-27B Official Model Card: Native Context and Deployment Recommendations](https://huggingface.co/Qwen/Qwen3.5-27B)
- [vLLM Qwen3.8-27B Recipe](https://recipes.vllm.ai/Qwen/Qwen3.8-27B)
- [vLLM Docker Hub](https://hub.docker.com/r/vllm/vllm-openai/tags)
- [Claude Opus 4.5 Release Announcement](https://www.anthropic.com/news/claude-opus-4-5)
- [Claude Opus 4.6 Release Announcement](https://www.anthropic.com/news/claude-opus-4-6)
- [vLLM Benchmark CLI](https://docs.vllm.ai/en/latest/benchmarking/cli/)
- [SGLang Official Image Tags](https://hub.docker.com/r/lmsysorg/sglang/tags)
- [SGLang Qwen3.5 Model Implementation](https://github.com/sgl-project/sglang/blob/main/python/sglang/srt/models/qwen3_5.py)
- [SGLang Qwen3.5 language-only Checkpoint Compatibility Discussion](https://github.com/sgl-project/sglang/issues/27212)
- [SGLang Hybrid GDN + MTP GPU Memory Utilization Discussion](https://github.com/sgl-project/sglang/issues/29857)
