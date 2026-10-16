---
title: "DeepSeek-V4-Flash-0731 Deployment and Load Testing on H20"
description: "Records resource conditions, vLLM startup flow, performance baseline, same-Pod PD separation testing, and OpenWebUI integration for DeepSeek-V4-Flash-0731 on a single-node eight-card H20"
status: exploratory
last_reviewed: 2026-08-10
---

# DeepSeek-V4-Flash-0731 Deployment and Load Testing on H20

This document records a desensitized exploratory validation. All cluster names, Namespaces, node addresses, Pod names, image registries, object storage addresses, model paths, gateways, accounts, and credentials have been removed or replaced with placeholders. The performance numbers in this document are intended to illustrate order of magnitude and testing methodology, not production capacity commitments.

## 1. Conclusions

DeepSeek-V4-Flash-0731 can be started on a single node `8 × NVIDIA H20 96 GB` using vLLM. The validated topology is:

```text
OpenAI-compatible client
          │
          ▼
     vLLM API Server
          │
          ▼
  单 Pod、单节点、TP=8
  8 × H20 96 GB
```

The original baseline is an ordinary colocated Prefill/Decode deployment, not PD separation. Model weights, KV Cache, and CUDA Graphs fit on 8 cards, but GPU memory sits at approximately 93 GiB/card with little headroom. All load test requests succeeded during validation; after completing runtime warmup for the target concurrency shape, total output throughput for 128-token input, 64-token output, concurrency 8 was approximately 934 tok/s.

![Resource topology of ordinary TP=8 vs. AIBrix dual TP=8 P/D](../../assets/practices/deepseek-v4-flash-h20-evaluation/01-topology-comparison.png)

Subsequently, within the same manual Pod, the eight cards were statically partitioned into `Prefill TP=4 + Decode TP=4`, and real KV Cache handoff was completed using NIXL/UCX and a local Proxy. This topology is functionally correct, but the eager, non-DSpark 4P+4D configuration only reached approximately 3.7%–12.1% of the original TP=8 output throughput. It is therefore currently suitable only for P/D functional validation, not as a performance replacement for the original deployment.

Deployment feasibility does not mean production readiness. Before formal rollout, the following still needs to be completed: real request replay, long-duration stepped load testing, tool-call and reasoning correctness, DSpark A/B testing, failure recovery, authentication, stable ingress, and monitoring/alerting.

## 2. Resource and Software Conditions

### 2.1 Hardware Starting Point

It is recommended to start validation from the following boundaries:

```yaml
resources:
  requests:
    cpu: "64"
    memory: 320Gi
    nvidia.com/gpu: "8"
  limits:
    cpu: "128"
    memory: 512Gi
    nvidia.com/gpu: "8"
```

Additionally, provide at least 64–128 GiB of `/dev/shm`. Actual CPU and memory should be adjusted based on tokenizer, concurrent downloads, caching policy, and node limits. The model directory is approximately 155 GiB; if the experimental Pod uses `emptyDir`, node ephemeral disk capacity must also be confirmed; deleting the Pod will also lose the model and cache.

Single-node TP=8 does not depend on cross-node RDMA. Only if switching to multi-node TP/PP would RDMA, NCCL topology, failure domains, and Gang scheduling need separate validation.

### 2.2 Validated Software Combination

The software versions recorded in this document are as follows:

```text
vLLM: 0.26.0 开发版本
PyTorch: 2.11
CUDA runtime: 12.9
GPU: 8 × NVIDIA H20 96 GB
```

DeepSeek V4 requires native engine support for the `deepseek_v4` tokenizer, reasoning parser, and tool-call parser. DSpark also requires the corresponding draft model implementation and fixes. Do not judge compatibility based on image tags alone; verify the actual versions of vLLM, PyTorch, CUDA, FlashInfer, DeepGEMM, and the model implementation inside the container.

## 3. Model Preparation

### 3.1 Model Size

A full inspection yielded:

```text
总大小：约 155.43 GiB
文件数：55
Safetensors 分片：48
```

Before deployment, at minimum verify that `config.json`, tokenizer, generation config, weight index, and all Safetensors shards are complete. Do not mix the model directory with writable Hugging Face, Torch, or Triton compilation caches.

### 3.2 S3-Compatible Object Storage Download

Credentials should be injected from Secrets, workload identity, or a controlled credential system—never written into shell history, YAML, images, or Git:

```bash
export AWS_ACCESS_KEY_ID='<READ_ONLY_ACCESS_KEY>'
export AWS_SECRET_ACCESS_KEY='<READ_ONLY_SECRET_KEY>'
export AWS_DEFAULT_REGION='<REGION>'
export AWS_EC2_METADATA_DISABLED=true

mkdir -p /workspace/model/DeepSeek-V4-Flash-0731

aws \
  --endpoint-url='https://<BUCKET>.<S3_ENDPOINT>' \
  s3 sync \
  's3://<BUCKET>/<MODEL_PREFIX>/' \
  /workspace/model/DeepSeek-V4-Flash-0731
```

Some object storage systems prohibit path-style requests. If `PathStyleDomainForbidden` occurs, change the endpoint to a virtual-hosted address that includes the Bucket, i.e.:

```text
https://<BUCKET>.<S3_ENDPOINT>
```

Do not bypass certificate validation long-term via `--no-verify-ssl`. Credentials should be granted read-only access to only the target Bucket/Prefix, and rotated immediately if they leak into terminal output, chat logs, or logs.

A single 155.43 GiB download had an observed window of approximately 364 seconds, averaging approximately 437 MiB/s (3.67 Gbit/s). Another record in a similar environment was approximately 326 seconds, a difference of about 12%, which falls within reasonable short-term storage, network, and node load fluctuation.

Optimization priorities:

1. Prioritize avoiding repeated downloads: use read-only CephFS/PVC, or have a CPU-only downloader prepare the persistent volume first.
2. Then test AWS CLI `max_concurrent_requests`, e.g., 10, 20, 32, and observe throughput and throttling.
3. Decouple download from GPU allocation to reduce expensive GPU idle time during model synchronization.
4. Preserve checksum results to avoid entering the time-consuming GPU initialization phase with an incomplete model.

### 3.3 CephFS Read-Only Mount

The following shows only the general structure; all environment values must be provided by the deployer:

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

Before formal use, confirm: the target cluster can reach the monitors, the Secret is authorized, the directory is readable by the container UID/GID, multi-Rank concurrent read throughput is acceptable, and both volume and volumeMount remain read-only.

## 4. Manual Exploration Pod

A bare Pod is suitable for compatibility exploration but not for long-term service. The template below has no health probes, to avoid false failures before the model is manually started; it also contains no real node labels, taints, images, or storage information:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: deepseek-v4-flash-manual
spec:
  restartPolicy: Never
  containers:
    - name: workspace
      image: <VLLM_IMAGE>
      command: ["bash", "-lc", "sleep infinity"]
      stdin: true
      tty: true
      resources:
        limits:
          nvidia.com/gpu: "8"
      volumeMounts:
        - name: model
          mountPath: /workspace/model
        - name: shm
          mountPath: /dev/shm
  volumes:
    - name: model
      emptyDir: {}
    - name: shm
      emptyDir:
        medium: Memory
        sizeLimit: 128Gi
```

If the image truly requires privileged permissions, the specific reason should be documented and the Pod lifecycle shortened; do not enable it by default just because it is an exploration environment. Reclaim the Pod promptly after exploration.

## 5. vLLM Startup

The validated command structure is as follows:

```bash
vllm serve /workspace/model/DeepSeek-V4-Flash-0731 \
  --served-model-name DeepSeek-V4-Flash \
  --host 0.0.0.0 \
  --port 8000 \
  --trust-remote-code \
  --tensor-parallel-size 8 \
  --kv-cache-dtype fp8 \
  --block-size 256 \
  --gpu-memory-utilization 0.88 \
  --max-model-len 204800 \
  --tokenizer-mode deepseek_v4 \
  --tool-call-parser deepseek_v4 \
  --enable-auto-tool-choice \
  --reasoning-parser deepseek_v4 \
  --enable-prefix-caching \
  --speculative-config \
    '{"method":"dspark","num_speculative_tokens":5,"draft_sample_method":"greedy"}'
```

For first compatibility validation, it is recommended to first remove `--speculative-config`, establish a target-only baseline, then enable DSpark for A/B testing on identical inputs. Also explicitly set `--max-num-seqs` to match real requirements, to avoid capturing a large number of CUDA Graphs for high-concurrency shapes that will never be used.

## 6. Why the Service Cannot Accept Requests Immediately After Weight Loading

Loading weights only completes the transfer of parameters from storage to GPU. Before opening the API, vLLM also initializes TP communication, profiles peak GPU memory, allocates KV Cache, warms up DeepGEMM/TileLang/FlashInfer kernels, initializes DSpark, and captures CUDA Graphs for multiple batch shapes.

One cold-start record is as follows:

| Stage | Duration | Notes |
| --- | ---: | --- |
| Safetensors/model loading | Slowest Rank 26.9 s | Weight reading and distribution is fast |
| DeepGEMM kernel warmup | 159 s | One of the main cold-start costs |
| CUDA Graph capture | 229 s | Largest single cost item, approximately 3.17 GiB per card |
| Engine profile/KV/warmup total | 605.23 s | Includes GPU memory profiling and cache creation |
| `vllm serve` to API Ready | ~723 s | Approximately 12 min 03 s |

The engine ultimately allocates approximately 58.36 GiB of KV Cache per card, with a total theoretical capacity of approximately 1.76 million tokens. This capacity is the pool size calculated by the engine based on the current configuration, and does not mean a single request should directly use the maximum context.

Testable cold-start optimizations:

- For exploration configurations, use `--enforce-eager` to skip CUDA Graphs; the usual trade-off is reduced steady-state performance.
- Reduce and explicitly set `--max-num-seqs` to reduce the number of shapes that need capture.
- A/B test `fast_moe_cold_start`, but correctness regression testing is mandatory.
- Place compilation caches on a reusable volume and verify whether the second startup can reuse them.
- Establish separate startup-time and throughput baselines for target-only vs. DSpark.

## 7. The Original TP=8 Baseline Is Not PD Separation

The current request path is:

```text
Client
  → 一个 vLLM API/Engine
  → TP=8 执行 Prefill
  → KV Cache 留在同一 Engine
  → 同一组 TP=8 GPU 执行 Decode
  → Response
```

`TP=8` means one model computation spans 8 cards; DSpark is speculative decoding. Neither of these is PD separation.

True PD separation requires independent Prefill and Decode instances, a KV Cache transfer connector, and a Router that routes requests by stage:

```text
Client → Router → Prefill 实例
                    │
                    └── KV Cache transfer ──→ Decode 实例 → Response
```

The main value of PD is independently controlling TTFT and ITL, and reducing tail-latency interference on requests currently in Decode caused by long-Prompt Prefill. It does not inherently improve throughput; with short prompts, low QPS, or a budget of only one set of 8 GPUs, the Router and KV transfer may actually add latency and cost.

Conditions suitable for considering PD:

- Sustained high traffic where long prompts noticeably raise p95/p99 ITL;
- TTFT and ITL both have strict but different SLOs;
- Prefill/Decode need independent scaling;
- Sufficient GPUs and a high-bandwidth, low-latency KV transfer network;
- Existing Router, Connector, monitoring, retry, and failure recovery capabilities.

Fair comparison must fix the total GPU count. For example, compare two ordinary TP=8 instances against one Prefill TP=8 plus one Decode TP=8, rather than comparing an 8-GPU ordinary instance directly against a 16-GPU 1P+1D.

The follow-up experiment recorded in Section 9 still fixes the total at 8 GPUs, but changes to same-Pod 4P+4D. It is a different runtime state from the original TP=8 baseline in this section.

## 8. Exploratory Load Test Data

The load test client and service are in the same Pod, accessing the loopback OpenAI-compatible API. It uses a random dataset, fixed token lengths, `temperature=0`, and `--ignore-eos`, so it does not include ingress gateway or cross-node network overhead.

Metric definitions:

- TTFT: time to first token for a request, primarily affected by queueing and Prefill;
- TPOT: average time to generate one token, excluding the first token;
- ITL: interval between consecutive tokens in streaming output;
- E2EL: full request duration;
- Output tok/s: total output throughput of the entire instance, not per-request speed.

In the tables, `C` represents the maximum number of concurrent requests the load test client allows (Concurrency), i.e., the upper bound on requests not yet completed at the same time, not the total number of users. `C=1` means fully serial, primarily observing single-request latency under low load; `C=8` means at most 8 requests in flight at once, with the client immediately injecting the next request when one completes, until the full round of requests finishes. Increasing `C` typically allows continuous batching to utilize the GPU more fully and raises total instance throughput, but queueing and resource sharing may also increase per-request TTFT, TPOT, and E2EL.

### 8.1 Steady-State Results

| Scenario | Requests Succeeded | req/s | Output tok/s | p50/p95/p99 TTFT | p95 TPOT | p95 ITL | p95 E2EL |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 128 in / 64 out, C=1 | 16/16 | 3.91 | 250.19 | 49 / 49 / 49 ms | 4.84 ms | 9.07 ms | 352.88 ms |
| 128 in / 64 out, C=4 | 32/32 | 9.65 | 617.77 | 60 / 96 / 128 ms | 8.02 ms | 37.13 ms | 591.94 ms |
| 128 in / 64 out, C=8 | 64/64 | 14.59 | 933.70 | 71 / 233 / 233 ms | 11.53 ms | 43.63 ms | 810.29 ms |
| 4096 in / 128 out, C=4 | 16/16 | 2.16 | 277.00 | 760 / 1391 / 1423 ms | 16.00 ms | 75.07 ms | 2944.96 ms |

For short requests, going from C=1 to C=8 increased total output throughput by approximately 3.73x, while p95 TTFT rose from approximately 49 ms to 233 ms. This is the normal behavior of continuous batching trading per-request latency for total throughput. The 4K-input p95 TTFT of approximately 1.39 s indicates Prefill has become a more prominent latency component.

DSpark acceptance rates in these tests were approximately 34%–59%. Acceptance rate alone cannot prove benefit; throughput, latency, correctness, and power consumption must still be compared via A/B testing against the same requests with DSpark disabled.

### 8.2 JIT Can Still Occur After API Ready

During the first test at concurrency 8, p95 TTFT reached approximately 33.4 s. The service logs explicitly recorded TileLang JIT triggering during inference, with one kernel compiling for approximately 9 seconds. After re-running with identical parameters, p95 TTFT recovered to approximately 233 ms, and output throughput recovered from approximately 92 tok/s to approximately 934 tok/s.

![Difference between first load test and results after same-shape warmup](../../assets/practices/deepseek-v4-flash-h20-evaluation/02-warmup-pitfall.png)

This shows that `Application startup complete` does not mean all real input lengths and concurrency shapes have been compiled. Pre-production business warmup should cover at least:

1. Target concurrency levels;
2. Common input lengths;
3. Near-maximum input lengths;
4. Real request shapes such as Chat, reasoning, and tool calls.

The load test tool's warmup request count should at least cover the target concurrency, not just send a single serial request.

### 8.3 GPU Sampling

One-sample-per-second `nvidia-smi` sampling yielded:

| Scenario | Avg utilization across 8 cards in active samples | Peak | Active avg per-card power | Max per-card GPU memory |
| --- | ---: | ---: | ---: | ---: |
| 128/64, C=4 | 96.8% | 100% | 289.9 W | 93,127 MiB |
| 128/64, C=8 | 74.2% | 100% | 267.8 W | 93,169 MiB |
| 4096/128, C=4 | 97.4% | 100% | 308.7 W | 93,273 MiB |

The test duration was short, so GPU data can only be used to judge load patterns, not as precise energy-consumption conclusions. GPU memory is already close to the card's visible capacity; OOM risk must be re-validated before expanding Graphs, increasing memory utilization, or adding additional components.

### 8.4 Load Test Command

```bash
vllm bench serve \
  --backend openai \
  --base-url http://127.0.0.1:8000 \
  --endpoint /v1/completions \
  --model /workspace/model/DeepSeek-V4-Flash-0731 \
  --served-model-name DeepSeek-V4-Flash \
  --tokenizer /workspace/model/DeepSeek-V4-Flash-0731 \
  --tokenizer-mode deepseek_v4 \
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

Formal capacity testing should switch to a desensitized real request distribution, run 10–30 minute fixed request-rate stepped tests from an independent load test node through the actual service ingress, and simultaneously record failure rate, queue, GPU, memory, power, and tokens/s/GPU.

## 9. Same-Pod TP=4+TP=4 P/D Separation Test

### 9.1 Experimental Topology and Boundaries

This experiment did not create a second model Pod and did not modify any Kubernetes manifests. After stopping the original TP=8 Engine, two complete model Engines were started inside the same manual Pod that had already been allocated 8 H20 cards:

```text
Client
  → Proxy / 0.0.0.0:8000
      → Prefill / 127.0.0.1:8100 / GPU 0-3 / TP=4
      → NIXL + UCX / same Pod
      → Decode  / 127.0.0.1:8200 / GPU 4-7 / TP=4
  → Response
```

| Item | Measured value |
| --- | --- |
| GPU | Single node `8 × H20 96 GB` |
| vLLM | `0.26.0b2.dev1+g3b102b576` |
| NIXL | `1.3.1` |
| KV Connector | `NixlConnector`, `kv_producer` → `kv_consumer` |
| KV dtype / block size | FP8 / 256 |
| Context / concurrency limit | 204,800 / 16 |
| Cold-start configuration | `--enforce-eager`, DSpark disabled |

These are two complete models, not a single TP=8 Engine whose ranks are labeled as two roles. This validates TP=4 capacity, Proxy control flow, and the P→D KV data path, but does not provide cross-Pod networking, independent scaling, or failure-domain isolation.

### 9.2 Manual Commands

Public commands use placeholders to hide environment identifiers. Enter the manual Pod:

```bash
kubectl --context <KUBE_CONTEXT> \
  -n <NAMESPACE> \
  exec -it <MANUAL_POD> -- bash
```

Confirm and stop the original TP=8 Engine, and wait for the old Workers to release GPU memory:

```bash
pgrep -af '/usr/local/bin/vllm serve'

BASELINE_PID="$(pgrep -f '^/usr/bin/python3 /usr/local/bin/vllm serve' | head -n 1)"
test -n "$BASELINE_PID" && kill -TERM "$BASELINE_PID"

while [ -n "$(nvidia-smi --query-compute-apps=pid --format=csv,noheader)" ]; do
  sleep 5
done
```

Define identical model, Attention, and KV parameters on both sides:

```bash
mkdir -p /workspace/logs/pd-tp4

PD_COMMON_ARGS=(
  /workspace/model/DeepSeek-V4-Flash-0731
  --dtype auto
  --served-model-name DeepSeek-V4-Flash
  --kv-cache-dtype fp8
  --block-size 256
  --gpu-memory-utilization 0.88
  --max-model-len 204800
  --max-num-seqs 16
  --tokenizer-mode deepseek_v4
  --tool-call-parser deepseek_v4
  --enable-auto-tool-choice
  --reasoning-parser deepseek_v4
  --reasoning-config '{"reasoning_parser":"deepseek_v4","reasoning_start_str":"<think>","reasoning_end_str":"</think>"}'
  --default-chat-template-kwargs '{"thinking":true}'
  --enable-prompt-tokens-details
  --enable-prefix-caching
  --trust-remote-code
  --enforce-eager
)
```

Start Prefill:

```bash
nohup env \
  CUDA_VISIBLE_DEVICES=0,1,2,3 \
  VLLM_PORT=20000 \
  VLLM_NIXL_SIDE_CHANNEL_HOST=127.0.0.1 \
  VLLM_NIXL_SIDE_CHANNEL_PORT=5559 \
  UCX_NET_DEVICES=all \
  vllm serve "${PD_COMMON_ARGS[@]}" \
    --host 127.0.0.1 \
    --port 8100 \
    --tensor-parallel-size 4 \
    --kv-transfer-config \
      '{"kv_connector":"NixlConnector","kv_role":"kv_producer","kv_buffer_device":"cuda"}' \
  > /workspace/logs/pd-tp4/prefill.log 2>&1 &

echo $! > /workspace/logs/pd-tp4/prefill.pid
```

Start Decode:

```bash
nohup env \
  CUDA_VISIBLE_DEVICES=4,5,6,7 \
  VLLM_PORT=30000 \
  VLLM_NIXL_SIDE_CHANNEL_HOST=127.0.0.1 \
  VLLM_NIXL_SIDE_CHANNEL_PORT=5659 \
  UCX_NET_DEVICES=all \
  vllm serve "${PD_COMMON_ARGS[@]}" \
    --host 127.0.0.1 \
    --port 8200 \
    --tensor-parallel-size 4 \
    --kv-transfer-config \
      '{"kv_connector":"NixlConnector","kv_role":"kv_consumer","kv_buffer_device":"cuda"}' \
  > /workspace/logs/pd-tp4/decode.log 2>&1 &

echo $! > /workspace/logs/pd-tp4/decode.pid
```

Wait for both sides to become Ready, then have the image's built-in Proxy listen on the original service port 8000:

```bash
curl -fsS http://127.0.0.1:8100/health
curl -fsS http://127.0.0.1:8200/health

nohup python3 \
  /vllm-workspace/examples/disaggregated/disaggregated_serving/disagg_proxy_multiturn.py \
  --host 0.0.0.0 \
  --port 8000 \
  --prefiller-host 127.0.0.1 \
  --prefiller-port 8100 \
  --decoder-host 127.0.0.1 \
  --decoder-port 8200 \
  > /workspace/logs/pd-tp4/proxy.log 2>&1 &

echo $! > /workspace/logs/pd-tp4/proxy.pid
curl -fsS http://127.0.0.1:8000/health
```

Verify normal text:

```bash
curl -sS http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model":"DeepSeek-V4-Flash",
    "messages":[{"role":"user","content":"只输出：PD_OK"}],
    "max_tokens":32,
    "temperature":0,
    "stream":false,
    "chat_template_kwargs":{"thinking":false}
  }'
```

### 9.3 Startup and KV Transfer Evidence

Both Engines started simultaneously and became Ready after approximately 3 minutes 55 seconds; Engine profile, KV Cache, and warmup each took about 170 seconds. This time cannot be directly compared with the original TP=8's approximately 12 minutes, because DSpark and CUDA Graph were both disabled this time.

| Metric | Measured value |
| --- | ---: |
| Model weights per GPU | 38.08 GiB |
| Peak activation per GPU | 2.66 GiB |
| KV Cache per GPU | 42.86 GiB |
| Packed KV Cache registered by NIXL | 46,020,395,520 Bytes / Rank |
| Steady-state process GPU memory | ~88.8 GiB / GPU |

In real requests, the NIXL compatibility hash of all four Decode TP ranks passed, the Transfer Plan showed `local_tp=4`, `remote_tp=4`, `tp_ratio=1`, and the Decode External Prefix Cache hit rate was 100%. The first request recorded 4 successful transfers, averaging 7.574 ms, approximately 916 MB/s; subsequent short requests in warm state averaged 0.321 ms, approximately 24,711 MB/s. The `thinking=false` request returned `PD_OK` with HTTP 200 in approximately 0.461 seconds.

These are NIXL records from the same host, same Pod, short prompts, and each TP rank; they only prove that the KV data path works and cannot be extrapolated to cross-node throughput.

### 9.4 Performance Comparison with the Original TP=8

Using the same random workload, input/output lengths, concurrency, `temperature=0`, `--ignore-eos`, and unlimited request rate from Section 8, 4P+4D was re-measured. All requests succeeded:

| Load | Configuration | Output tok/s | p95 TTFT | p95 TPOT | p95 ITL | p95 E2E |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 128 in / 64 out, C=1 | Original TP=8 | 250.19 | 49 ms | 4.84 ms | 9.07 ms | 353 ms |
| 128 in / 64 out, C=1 | 4P+4D | 9.17 | 253 ms | 106.95 ms | 107.28 ms | 6,990 ms |
| 128 in / 64 out, C=4 | Original TP=8 | 617.77 | 96 ms | 8.02 ms | 37.13 ms | 592 ms |
| 128 in / 64 out, C=4 | 4P+4D | 34.42 | 841 ms | 107.41 ms | 108.04 ms | 7,600 ms |
| 128 in / 64 out, C=8 | Original TP=8 | 933.70 | 233 ms | 11.53 ms | 43.63 ms | 810 ms |
| 128 in / 64 out, C=8 | 4P+4D | 65.85 | 2,993 ms | 107.43 ms | 108.30 ms | 9,753 ms |
| 4096 in / 128 out, C=4 | Original TP=8 | 277.00 | 1,391 ms | 16.00 ms | 75.07 ms | 2,945 ms |
| 4096 in / 128 out, C=4 | 4P+4D | 33.63 | 1,959 ms | 107.32 ms | 108.14 ms | 15,557 ms |

4P+4D output throughput reached only 3.7%, 5.6%, 7.1%, and 12.1% of the original TP=8, i.e., approximately 27.3x, 17.9x, 14.2x, and 8.2x lower, respectively. Short-request p95 TPOT became approximately 9.3–22.1x slower; the 4K-request p95 TTFT was only approximately 1.4x slower, but p95 E2E still became approximately 5.3x slower.

A small sample of direct access to the current TP=4 Decode was 9.23 tok/s with p95 TPOT of 107.51 ms; through P/D it was 9.17 tok/s with p95 TPOT of 106.95 ms, nearly identical. Therefore the main loss is not NIXL, but rather changing from one TP=8 Engine to two TP=4 Engines on a fixed set of 8 GPUs, while also disabling DSpark and CUDA Graph. A strict A/B test should compare 4P+4D against two ordinary TP=4 instances with completely identical parameters, and re-measure after restoring the same CUDA Graph and DSpark configuration on both sides.

### 9.5 Limitations and Rollback

- The Proxy forwards `delta.reasoning` in streaming SSE as-is, but non-streaming aggregation only collects `content`, which loses reasoning; this needs to be fixed before formal integration.
- Only the P→D one-way KV from `kv_producer` → `kv_consumer` has been validated; D→P multi-turn reuse should not be claimed based on this.
- Same-Pod deployment cannot independently scale P/D and has no independent failure domain; same-host UCX/NIXL results do not cover cross-node RDMA.
- Pod IP:8000 and loopback are healthy, but accessing the ClusterIP:80 of the same backend Pod from within that Pod returns connection refused; the Service/Ingress path from an independent client has not yet been validated.

To stop, terminate only the three processes corresponding to the PID file:

```bash
kill -TERM "$(cat /workspace/logs/pd-tp4/proxy.pid)"
kill -TERM "$(cat /workspace/logs/pd-tp4/prefill.pid)"
kill -TERM "$(cat /workspace/logs/pd-tp4/decode.pid)"

while [ -n "$(nvidia-smi --query-compute-apps=pid --format=csv,noheader)" ]; do
  sleep 5
done
```

Then restore the original baseline using the full TP=8 command from Section 5. If DSpark is added to both P/D sides, compatible parameters such as speculation, model, Attention backend, and KV dtype must remain consistent.

## 10. Integrating with OpenWebUI

vLLM provides an OpenAI-compatible API that can be used by OpenWebUI. The stable path should be:

```text
OpenWebUI
   │
   ▼
内部鉴权入口或跨集群网关
   │
   ▼
Service
   │
   ▼
vLLM Pod :8000
```

Do not use Pod IP as a long-term configuration. Pod IPs change on recreation, and cross-cluster Pod CIDRs, even if currently routable, offer no service discovery, health removal, authentication, or stability guarantees. At minimum, create a Service that selects the target Pod; for cross-cluster scenarios, expose through a controlled gateway, service mesh, or other stable entry point.

First verify from the network where OpenWebUI resides:

```bash
curl -fsS 'http://<MODEL_ENDPOINT>/health'
curl -fsS 'http://<MODEL_ENDPOINT>/v1/models'
```

Then add an OpenAI-compatible connection in OpenWebUI's admin connection settings:

```text
Base URL: http://<MODEL_ENDPOINT>/v1
API Key:  <API_KEY_OR_NON_EMPTY_PLACEHOLDER>
Model:    DeepSeek-V4-Flash
```

If vLLM is not configured with `--api-key`, and the OpenWebUI version still requires a non-empty Key, a placeholder value without permission semantics can be used; formal shared services should add real authentication in vLLM or a front-end gateway. If initializing via environment variables, OpenWebUI's `OPENAI_API_BASE_URLS`, `OPENAI_API_KEYS`, and corresponding connection config can be used, but once persistent configuration is enabled, admin settings in the database may override subsequent environment variable changes.

After integration, verify in order: model list, normal chat, streaming output, reasoning content, long text, and tool calls. The UI listing a model only proves that `/v1/models` is reachable, not that the chat template and parser are correct.

In this RayClusterFleet P/D experiment, `deepseek-v4-flash-ray-pd` was also explicitly added to OpenWebUI's OpenAI-compatible connection. After the OpenWebUI Deployment became Ready, a deterministic Chinese request was sent through the AIBrix Gateway: input "你好，只回答：你好" (Hello, only answer: Hello) accurately returned "你好" (Hello). This simultaneously proves that the model is selectable from the UI and that the erroneous tokens seen during the Ray executor phase were not an OpenWebUI rendering issue.

## 11. AIBrix and RayClusterFleet P/D Measured Results

### 11.1 StormService TP=8 Baseline

In an environment where AIBrix v0.7.0 was already installed, a single `StormService` was first used to manage a single-node TP=8 Engine, verifying that AIBrix can take over the lifecycle of the original manual Pod. The initContainer uses the AWS CLI to sync 48 weight shards from S3-compatible object storage to `emptyDir`; virtual-hosted-style must be enabled when using Tencent Cloud COS:

```bash
aws configure set default.s3.addressing_style virtual
```

Otherwise `ListObjectsV2` returns `PathStyleDomainForbidden`. Credentials should be injected via Secret and must not be written into manifests. `emptyDir` is suitable for one-off experiments, but Pod recreation re-downloads approximately 156 GiB of model, and the GPU is occupied by the entire Pod during download; long-term deployment should use node cache or PVC instead.

AIBrix v0.7.0 did not automatically create an HTTPRoute for this StormService, so a Service, ReferenceGrant, and a single HTTPRoute were created additionally. Measured results through the Gateway are as follows:

| Load | Path | Success | Output tok/s | p95 TTFT | p95 TPOT | p95 ITL | p95 E2E |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 128/64, C=1 | Original manual Pod TP=8 direct | 16/16 | 250.19 | 49 ms | 4.84 ms | 9.07 ms | 353 ms |
| 128/64, C=1 | AIBrix → StormService TP=8 | 16/16 | 257.46 | 55.90 ms | 3.92 ms | 11.03 ms | 302.16 ms |
| 128/64, C=8 | Original manual Pod TP=8 direct | 64/64 | 933.70 | 233 ms | 11.53 ms | 43.63 ms | 810 ms |
| 128/64, C=8 | AIBrix → StormService TP=8 | 64/64 | 866.61 | 264.86 ms | 11.63 ms | 51.05 ms | 856.39 ms |

C=8 throughput was approximately 7.2% lower in a single round, but this cannot be entirely attributed to the Gateway; strict Gateway overhead requires alternating multiple rounds of A/B testing on the same Ready Pod, same client, and same request set.

### 11.2 Dual-Fleet Topology and Preparation Files

One `RayClusterFleet` replica represents one complete RayCluster, with no Prefill/Decode Role abstraction. Therefore P/D is split into two Fleets, rather than declaring two roles in a single Fleet:

```text
AIBrix Gateway，routingStrategy=pd
  ├─ Prefill RayClusterFleet，1 个 8-GPU Head Pod，TP=8
  └─ Decode RayClusterFleet，1 个 8-GPU Head Pod，TP=8

Prefill Head -- NIXL/UCX --> Decode Head
```

Both Heads use the same model label, `roleset-name`, model parameters, TP, KV dtype, Attention backend, and `kv_role=kv_both`, with `role-name` being `prefill` and `decode` respectively. Workers should not carry the AIBrix model discovery label. In the first phase, no Workers are created; the two Engines each occupy one complete H20 node, totaling 16 H20 GPUs.

AIBrix v0.7.0 manages HTTPRoutes based on the Fleet's top-level model label. If two Fleets share the same top-level model label, deleting either Fleet may accidentally delete the shared Route. Therefore, the experiment manifests only write model/P/D labels in the Head Pod template, and the Service, ReferenceGrant, and single HTTPRoute are managed independently.

Preparation files are split by responsibility as follows; internal environment values use placeholders, and real Secrets do not enter version control:

| File | Content |
| --- | --- |
| `01-runtime-config.yaml` | Model download verification, Ray startup, and common vLLM parameters |
| `02-prefill-rayclusterfleet.yaml` | Prefill Fleet, 8×H20, initContainer, NIXL parameters |
| `03-decode-rayclusterfleet.yaml` | Decode Fleet, 8×H20, initContainer, NIXL parameters |
| `04-head-service.yaml` | Selects only the two Ready Head/API Pods |
| `05-aibrix-pd-route.yaml` | Single HTTPRoute, ReferenceGrant, and long-request timeout |

Apply order is Secret → Runtime Config → Prefill Fleet → Decode Fleet → Service/Route → Smoke Test → Benchmark. Reverse order for deletion. Before and after every update, verify the RayCluster and 8-GPU Pod counts; on site, it was observed that after the main container briefly became NotReady, the Fleet Controller created a replacement RayCluster, and even with `maxSurge: 0` configured, the target GPU count was temporarily exceeded.

### 11.3 Image and Executor Compatibility

After the upstream `vllm/vllm-openai:v0.26.0-cu129` is pinned to `linux/amd64`, it should first be pushed to an isolated staging repository, complete image scanning and digest verification, and then be distributed to the target environment through the organization-approved image synchronization process. The single-platform manifest digest is:

```text
sha256:3c5c53248febaa72823a4b7e51aafa1cd2b65d860392e3930414da4d3864f541
```

This upstream image includes vLLM and NIXL, but does not include Ray. During the verification phase, `ray[default]==2.47.1` is installed in the startup script, and then the Ray startup command injected by KubeRay is executed; the production image should pre-install the locked version to avoid restart depending on PyPI availability.

NIXL (NVIDIA Inference Xfer Library) is an inference data transfer software library, not an independent hardware module built into the H20 chip. In P/D separation, it is responsible for passing the KV Cache generated by Prefill to Decode, avoiding Decode recomputing the entire Prompt. H20 can run NIXL; whether the image includes NIXL, whether the vLLM Connector is enabled, and whether there is usable UCX/RDMA network between nodes determine whether the data path can be established and its performance.

It is necessary to distinguish GPU capability from node network capability: H20 supporting CUDA does not mean the server it resides in is necessarily configured with RDMA. When there is RoCE/InfiniBand across nodes, NIC drivers, and correct UCX configuration, NIXL can use high-speed networks; without RDMA, other UCX/TCP paths may still be used, but latency and throughput need to be verified separately. On the same node, local paths such as CUDA IPC can also be used. Therefore, "NIXL Agent initialization successful" only means the component has started; it is necessary to further see compatibility check, successful KV Transfer, and Decode external KV hits to prove that the actual P/D data path is established.

AIBrix v0.7.0 also has two compatibility details that can easily cause "appearing to go through two Pods, but actually not P/D":

1. The model configuration must use the profiles schema, for example `{"profiles":{"default":{"routingStrategy":"pd"}}}`; the old top-level `{"routingStrategy":"pd"}` will not stably route ordinary requests without forced headers into the P/D path;
2. GPU vLLM starts `NixlConnector`, but the Gateway Plugin's `model.aibrix.ai/kv-connector-type` should select `shfs`. In the v0.7.0 source code, `SHFSAgent` is the GPU path, which injects `kv_transfer_params` into Prefill; the implementation named `NIXLAgent` targets Neuron and uses `disagg_prefill_resp`, which the current GPU vLLM does not read.

Another root cause comes from the NIXL side channel. Its default listening address is loopback, and Decode cannot connect after receiving the Prefill Pod IP, causing 8 TP Ranks to experience `handshake_setup_failed` and ZMQ timeouts. Both Engines should explicitly set `VLLM_NIXL_SIDE_CHANNEL_HOST=0.0.0.0`. At the same time, setting `kv_load_failure_policy` to `recompute` can clear remote hits and recompute locally when transfer fails, avoiding the use of invalid KV to continue generating incorrect Tokens; but requests that undergo recompute cannot be counted in the P/D success rate, nor mixed into performance data.

This investigation also proved that HTTP 200, both Pods receiving requests, and External KV hit 100% are not sufficient evidence. A valid determination must simultaneously satisfy: AIBrix selects a P/D pair, SHFS injects `kv_transfer_params`, TP Rank compatibility check passes, `Num successful transfers` grows, no handshake/recompute, and RDMA hardware port counters grow synchronously.

Initially, vLLM was made to use `--distributed-executor-backend=ray`. Both Engines could complete weight loading, NCCL initialization, NIXL Agent initialization, warm-up, and CUDA Graph capture, and health checks also returned 200, but deterministic Chinese requests would generate random Chinese/English, code, and symbols. The same error could be reproduced on the following paths:

1. Direct connection to Prefill Head;
2. Direct connection to Decode Head;
3. AIBrix P/D path and OpenWebUI connected to that Gateway.

After switching to a vLLM build that had already passed ordinary TP=8 verification, the issue could still be reproduced, so the problem converges on the current combination path of DeepSeek V4 with the vLLM Ray executor, and cannot be attributed to OpenWebUI or the AIBrix Router. The existing evidence is insufficient to further assert whether it is the Ray Compiled DAG, GPU mapping, sampling return, or a combination of specific kernels with Ray Actors.

Since each side's Engine is entirely within one 8-GPU Pod and does not need Ray to execute TP, the following layered workaround was ultimately adopted:

```text
RayClusterFleet / KubeRay：管理两个单节点 Engine 的生命周期
vLLM mp：管理每个 Engine 内部的 8 个本地 TP Rank
AIBrix P/D Router：选择 Prefill 与 Decode Engine
NIXL/UCX：在两个 Engine 之间传输 KV
```

Here, `mp` and `ray` are two distributed executor backends that vLLM uses to manage TP Workers, not two P/D protocols, and they do not replace AIBrix or NIXL:

| Comparison Item | `mp` | `ray` |
| --- | --- | --- |
| Worker form | Python multi-process within the Pod | Ray Worker Actor |
| Common scope | Single-node multi-GPU | Single-node or cross-node |
| TP=8 implementation | Locally starts 8 TP Ranks | Creates 8 Ray Actors to execute TP |
| Cross-node TP/PP | Usually not used | Supported, scheduled by Ray Actors |
| Additional dependencies | Local process management and NCCL | Ray, Actor scheduling, GPU mapping, and NCCL |
| Applicable starting point | One Engine can fit into a complete 8-GPU node | One Engine must span multiple nodes, or there is an existing execution topology that must depend on Ray |

This time, even after changing the vLLM backend to `mp`, RayClusterFleet/KubeRay is still retained to manage the lifecycle of the two groups of Pods: within each Head Pod, `mp` manages 8 TP Ranks, AIBrix selects Prefill/Decode between Pods, and NIXL transfers KV between the two Engines. In other words, "using RayClusterFleet externally" does not require "vLLM must use the Ray executor internally."

After switching to `--distributed-executor-backend=mp` and cleanly rebuilding, the resources stabilized at two Fleets, two RayClusters, and two 8-GPU Head Pods. Deterministic Chinese requests through the AIBrix Gateway accurately returned the expected text, and the previous incorrect tokens disappeared.

This result cannot be extrapolated to "the Ray executor is generally incorrect." It only proves that the current combination of DeepSeek V4, vLLM version, image, and Ray executor did not pass the correctness threshold, while the local `mp` path with the same configuration can generate correctly. If a single Engine must span nodes to use more GPUs in the future, the Ray executor should be re-verified; when each side can fully fit into one 8-GPU H20 node, the execution chain of `mp` is shorter with fewer variables.

### 11.4 RayClusterFleet P/D Stress Testing

The client is located in the Prefill Pod and calls the Completions API through the AIBrix Gateway; the random dataset fixes input/output Token counts, `temperature=0`, `--ignore-eos`, and unlimited request rate. C=1 uses 16 requests and 2 warm-ups, C=8 uses 64 requests and 8 warm-ups, and 4K input uses 16 requests and 4 warm-ups. All requests are sent without bypass or forced routing headers.

The old test saw both Prefill and Decode Pods processing requests, but Decode actually recomputed the Prompt. The root cause was a mismatch in AIBrix connector type, configuration schema, and NIXL side channel listening address, so all old tables are invalidated. After correction, deterministic requests accurately returned the expected text, and AIBrix logs clearly recorded the P/D pair and SHFS injection; all 8 TP Ranks of vLLM passed the compatibility check and continuously reported successful KV Transfers.

Each side of the node provides 4 200 Gb/s RDMA devices. During stress testing, the hardware counters for Prefill send and Decode receive on all four rails grew synchronously. Converted by the InfiniBand counter's 4-byte unit, the cumulative total was approximately 63 GB; the clean C=8 main test recorded 512 successful TP-rank transfers with no handshake failures or recomputes. This confirms that the table below is a real P/D result of AIBrix scheduling, NIXL pulling, and the RDMA data plane working together.

| Load | Success | req/s | Output tok/s | p95 TTFT | p95 TPOT | p95 ITL | p95 E2E |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 128/64, C=1 | 16/16 | 2.11 | 135.28 | 79.98 ms | 6.32 ms | 8.99 ms | 475.09 ms |
| 128/64, C=8 | 64/64 | 11.99 | 767.49 | 194.17 ms | 8.48 ms | 11.04 ms | 725.80 ms |
| 4096/128, C=4 | 16/16 | 2.21 | 282.92 | 1084.04 ms | 7.41 ms | 10.22 ms | 2024.97 ms |

Compared with the single-machine TP=8 Combined steady-state results in Section 8:

- 128/64, C=1: P/D output throughput is approximately 45.9% lower, p95 TTFT is approximately 63.2% higher, indicating that low-load short requests are not worth the additional routing and KV transfer overhead;
- 128/64, C=8: P/D output throughput is approximately 17.8% lower, p95 TTFT improves by approximately 16.7%, p95 TPOT improves by approximately 26.5%, p95 ITL improves by approximately 74.7%;
- 4096/128, C=4: P/D output throughput is approximately 2.1% higher, p95 TTFT improves by approximately 22.1%, p95 TPOT improves by approximately 53.7%, p95 E2E improves by approximately 31.2%.

This set of results shows that the value of P/D mainly appears with concurrency and long Prompts, not with low-load short requests. It also uses 16 GPUs, while Combined only uses 8; calculated by output tokens/s/GPU, P/D is approximately 73.0%, 58.9%, and 48.9% lower across the three load groups. Therefore, this is not "free speedup with the same resources," but rather using a second set of weights and a group of GPUs in exchange for Prefill/Decode isolation, better long-request tail latency, and subsequent independent scaling capabilities. Production routing should leave short requests to Combined and only route long Prompts or Prefill-heavy requests to P/D.

P/D direct transfer only handles the KV handoff from Prefill to Decode for the current request; supporting multi-user long sessions, cross-Engine Prefix reuse, and cache tiering across GPU, Host Memory, and NVMe requires additional global indexing, KV-aware Routing, and distributed Backend. Related open-source roadmap and DeepSeek V4 verification boundaries can be found at: [DeepSeek V4 Flash's Distributed KV Cache](distributed-kv-cache-deepseek-v4.md).

During stress testing, a false tail also occurred once: the previous round's client was actually still running after the terminal output was interrupted, and after the second round started, total concurrency reached 16, polluting p95 TTFT to approximately 19 seconds. After confirming there were no leftover benchmark processes in the Pod, the rerun produced the data in the table above. Automated stress testing should add a unique request-id prefix to each round and verify client processes, Gateway outstanding requests, and server-side request counts return to zero before the next round.

![Performance cost comparison between ordinary TP=8 and AIBrix P/D at concurrency 8](../../assets/practices/deepseek-v4-flash-h20-evaluation/03-performance-tradeoff.png)

### 11.5 How AIBrix Mixes P/D and Combined

Hybrid routing is not a conceptual design. The AIBrix v0.7.0 Gateway Plugin already implements P/D roleset, Prompt length bucketing, Combined fallback, and load overflow:

1. `Route` calls the Pod selector; when `(prefillPod, decodePod)` is returned, it first sends an internal request to Prefill, then sends client traffic to Decode; when `(nil, combinedPod)` is returned, it skips Prefill and directly sets Combined as the target;
2. `collectAndBucketPods` uses `roleset-name` and `role-name=prefill|decode` to organize pairing, only allowing complete rolesets where both Prefill and Decode exist to enter the candidates;
3. After enabling `AIBRIX_PROMPT_LENGTH_BUCKETING=true`, `filterPrefillDecodePods` reads the Prompt Token count and filters by `routingConfig.promptLenBucketMinLength/MaxLength`;
4. When there is no complete and matching P/D pair, only `combined: true` Pods covering that Prompt range can serve as fallback; if Combined does not cover that length, an error is returned rather than blindly crossing buckets;
5. When there is a matching P/D pair but the P/D request rate is high while Combined is idle, `shouldPickCombined` can transfer overflow requests to the Combined Pod with the lowest request rate score.

Therefore, to achieve "short requests go to Combined, long requests go to P/D, while Combined can also serve as fallback for long requests," the Combined range needs to cover short requests and the long requests intended for fallback, while the P/D roleset only covers long requests. For example, Combined uses the default full-length range, and P/D is configured with `promptLenBucketMinLength: 2049`; short requests cannot find a P/D bucket and can only go to Combined, long requests preferentially enter P/D, and when P/D is overloaded or pairing is incomplete, Combined candidates still exist.

The instance scoring boundaries in v0.7.0 also need accurate description:

- Prefill default `prefix_cache`: `(100 - prefixMatchPercent) × 0.1 + runningRequests / maxRunningRequests`; `least_request` can also be used;
- Decode default `load_balancing`: comprehensively normalized running request count, generation throughput, and remaining KV Cache space; `least_request` can also be used;
- The `conductor` newly added to the current AIBrix main branch estimates queueing, Prefill time for hit/miss Tokens, and TBT and GPU Cache penalties after new requests, but it is not in the v0.7.0 tag. Production documentation must not describe main-branch capabilities as v0.7.0 default behavior.

Corresponding source code entry points:

- [v0.7.0 P/D Router and Combined fallback](https://github.com/vllm-project/aibrix/blob/v0.7.0/pkg/plugins/gateway/algorithms/pd_disaggregation.go)
- [v0.7.0 Prefill scorer](https://github.com/vllm-project/aibrix/blob/v0.7.0/pkg/plugins/gateway/algorithms/pd/prefill_scorer.go)
- [v0.7.0 Decode scorer](https://github.com/vllm-project/aibrix/blob/v0.7.0/pkg/plugins/gateway/algorithms/pd/decode_scorer.go)
- [v0.7.0 GPU SHFS transfer agent](https://github.com/vllm-project/aibrix/blob/v0.7.0/pkg/plugins/gateway/algorithms/pd/transfer/shfs.go)
- [v0.7.0 Neuron NIXL transfer agent](https://github.com/vllm-project/aibrix/blob/v0.7.0/pkg/plugins/gateway/algorithms/pd/transfer/nixl.go)

## 12. SGLang and RBG Single-Node Validation

In addition to the vLLM and AIBrix validation, a single-node aggregated deployment was also performed using SGLang and RoleBasedGroup (RBG). The goal was not to immediately replace the already-working vLLM service, but first to answer three more fundamental questions: whether the open-source SGLang image can recognize the 0731 checkpoint on H20, whether the Hopper kernel path is correct, and whether RBG can stably manage a complete TP=8 Engine.

The deployment topology remains simple: one `RoleBasedGroup` has only one `server` Role, one Pod, and 8 H20 GPUs. RBG manages the Pod lifecycle and service discovery; inside the Pod, SGLang starts 8 TP ranks. The first phase does not introduce a Router, cross-node TP, or P/D separation, to avoid debugging multiple data planes at the same time.

```text
RoleBasedGroup
  └─ server Role，replicas=1
       └─ 1 Pod，8 × H20 96 GB
            ├─ Init Container：准备 48 个模型分片
            └─ SGLang：TP=8，Marlin，DSpark
```

The experiment used a fixed `linux/amd64` SGLang v0.5.17 CUDA 13.0 image, which was pushed to the internal image registry before being synchronized to the test cluster. The public manifest does not include object storage addresses, internal Registry, Secret names, or node addresses; these values should be injected via Secrets, ConfigMaps, and environment-specific Overlays.

### 12.1 H20 Startup Parameters

H20 belongs to the Hopper SM90 family. The routed experts of the 0731 checkpoint are recognized as FP4, and SGLang uses MXFP4 Marlin MoE on this hardware, rather than the FlashInfer MXFP4 path intended for Blackwell. The minimal startup parameters are as follows:

```bash
sglang serve \
  --trust-remote-code \
  --model-path /models/DeepSeek-V4-Flash-0731 \
  --served-model-name deepseek-v4-flash-sglang \
  --tp 8 \
  --moe-runner-backend marlin \
  --speculative-algorithm DSPARK \
  --mem-fraction-static 0.82 \
  --chunked-prefill-size 4096 \
  --swa-full-tokens-ratio 0.1 \
  --reasoning-parser deepseek-v4 \
  --tool-call-parser deepseekv4 \
  --host 0.0.0.0 \
  --port 30000
```

The startup logs confirmed the following key paths:

- The checkpoint architecture is `DeepseekV4ForCausalLM`, with all 48 weight shards fully loaded;
- 8 TP ranks and NCCL 2.29.7 initialized successfully;
- The MoE implementation is `Mxfp4MarlinMoEMethod`;
- The DSpark Head built into the checkpoint is recognized as `DeepseekV4ForCausalLMDSpark`, proposing 5 draft tokens by default;
- Both target and draft use the DeepSeek V4 dedicated attention backend.

### 12.2 Cold Start Is Not Just "Downloading the Model"

The most obvious engineering issue this time was the first-time JIT. The image can be pulled and the weights can be loaded, but that does not mean the HTTP Server will become Ready immediately. SGLang generates CUDA source code for the H20's `sm_90a`, then sequentially passes through `nvcc`, `cicc`, and `ptxas` to generate the cubin; afterward, it must separately capture the CUDA Graphs for target verify and DSpark draft verify.

```text
SGLang / DeepGEMM 生成 kernel.cu
  → nvcc / cicc 编译为 PTX
  → ptxas 汇编为 sm_90a cubin
  → 写入 SGLang JIT cache
  → target verify CUDA Graph
  → draft verify CUDA Graph
  → HTTP Server Ready
```

In this cold start round, the model was approximately 156 GiB, and the node had already cached the model synchronization image; the SGLang main image was approximately 14.29 GB, with the first pull taking about 127 seconds. NCCL initialization took about 19 seconds, and loading the 48 target weight shards took about 25 seconds. SGLang self-reported Engine startup time was about 854 seconds, of which the CUDA Graph capture for 51 batch shapes of target verify took about 394 seconds, and the draft verify capture took another about 123 seconds. The Pod took about 23 minutes from creation to Ready, including model preparation, image pull, weight loading, JIT, two rounds of Graph capture, and built-in warm-up. Most of the waiting occurs outside model download, so caching only the checkpoint is still insufficient.

| Cold start phase | Observed this round |
| --- | ---: |
| Model preparation | ~156 GiB, ~6 minutes |
| First SGLang image pull | 14.29 GB, ~127 seconds |
| NCCL initialization | ~19 seconds |
| Loading 48 target weight shards | ~25 seconds |
| Target verify CUDA Graph | ~394 seconds |
| DSpark draft verify CUDA Graph | ~123 seconds |
| SGLang Engine startup | ~854 seconds |
| Pod creation to Ready | ~23 minutes |

Productionization should address at least three layers of caching simultaneously:

1. Use a reusable read-only PVC or node cache for the model, to avoid repeated synchronization after Pod recreation;
2. Mount the SGLang JIT cache to a persistent volume, and the cache key must include the image, CUDA, driver, GPU architecture, and startup parameters;
3. A more stable approach is to complete warm-up on H20 of the same architecture, then bake the compatible kernel cache into an immutable image.

If the business peak concurrency is far below 256, `max-running-requests` and the CUDA Graph maximum batch can also be lowered to reduce the number of shapes captured on first run. This optimization changes high-concurrency capability and must be re-benchmarked with real peak concurrency; it cannot be applied directly just to shorten startup time.

From the DeepSeek-V4-Pro rolling restart of nearly half an hour in the first half of this year, to this round's complete optimization approach covering model caching, weight loading, JIT Cache, CUDA Graph, and snapshot recovery, it is organized separately in: [From Half an Hour to Five Minutes: Full-Link Cold Start Optimization for Large Models](llm-cold-start-optimization.md).

### 12.3 Correctness Bar

The startup logs also contain two types of warnings that cannot be ignored: the local checkpoint is not recognized by the Hugging Face tokenizer as having a chat template; FP8 KV cache falls back to 1.0 when scaling factors are not provided. They may not necessarily cause incorrect output, but they show that acceptance cannot stop at `/health=200`.

At minimum, the following must be verified in sequence:

1. `/v1/models` returns the expected served model name;
2. Short Chinese requests with fixed sampling parameters accurately return the expected text;
3. The structured fields of the reasoning and tool call parsers are correct;
4. DSpark and target-only use the same request set for correctness and performance A/B testing;
5. Record acceptance, TTFT, TPOT, ITL, throughput, and peak GPU memory, rather than looking only at acceptance rate.

This round's basic Smoke Test has passed: `/v1/models` returns `deepseek-v4-flash-sglang`; with fixed `temperature=0` and thinking disabled, inputting "只回答：你好" (only answer: hello) made the service accurately return "你好" (hello), without reproducing the random Chinese/English and symbol output seen in the earlier specific vLLM Ray executor combination. This only proves that short requests and the basic Chat API are correct; FP8 KV scaling, long context, thinking, tool calls, and DSpark benefits still need to be verified separately.

```bash
curl http://<service>:30000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "deepseek-v4-flash-sglang",
    "messages": [{"role": "user", "content": "只回答：你好"}],
    "temperature": 0,
    "max_tokens": 32,
    "chat_template_kwargs": {"thinking": false}
  }'
```

In addition, `RoleInstanceSet not found` briefly appeared during the initial Reconcile, after which the Controller created the RoleInstanceSet, RoleInstance, and Pod and recovered successfully. The current version of RBG should still observe controller events and final resource counts; a single transient Warning must not be directly judged as a deployment failure.

### 12.4 Generative Health Checks Pollute Load Testing

The first load test surfaced a problem that could easily be misjudged as "low model throughput": the Pod uses HTTP `GET /health` for startup, readiness, and liveness probes, but the current SGLang image has generative health checks enabled. The three probes periodically trigger a real one-token generation request; since DeepSeek V4's page size is 256, a 256-token Prefill batch appears in the service logs every 10 seconds. It both occupies the scheduling queue and pollutes TTFT, throughput, and request count metrics.

The confirmation method is not to look only at `/health=200`, but to simultaneously observe the Engine logs and metrics when idle: if Prefill still appears periodically with no business requests, the probe has entered the generation path. Invalid load test data should be discarded entirely; it cannot be masked by adding warm-up.

This round applied a two-layer fix: set `SGLANG_ENABLE_HEALTH_ENDPOINT_GENERATION=0` at runtime so that `/health` only checks process status; the deployment manifest was changed to a TCP probe, to prevent future image default value changes from turning health checks back into business traffic.

```yaml
env:
  - name: SGLANG_ENABLE_HEALTH_ENDPOINT_GENERATION
    value: "0"

startupProbe:
  tcpSocket:
    port: engine
readinessProbe:
  tcpSocket:
    port: engine
livenessProbe:
  tcpSocket:
    port: engine
```

A TCP probe can only prove that the port accepts connections; it cannot replace end-to-end correctness checks. In production, low-frequency, independent synthetic requests should also be used to verify the model name, deterministic output, and streaming path, and such requests should be excluded from formal load test statistics.

### 12.5 SGLang Steady-State Load Testing

After excluding generative health checks, the client accessed the loopback OpenAI-compatible Completions API from inside the Engine Pod. Input was constructed by the checkpoint's built-in tokenizer and re-validated, with the actual token count matching the target value; `temperature=0` and `ignore_eos=true` were fixed, and each scenario ran one round per three random seeds. Throughput and latency in the table are the medians of the three rounds; the throughput range reflects fluctuation.

| Scenario | Successful per round | req/s | Output tok/s | Three-round output tok/s range | p95 TTFT | p95 TPOT | p95 ITL | p95 E2EL |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 128 in / 64 out, C=1 | 16/16 | 3.26 | 208.52 | 206.40–210.92 | 173.99 ms | 2.33 ms | 9.01 ms | 316.91 ms |
| 128 in / 64 out, C=8 | 64/64 | 7.52 | 480.99 | 255.58–541.31 | 327.66 ms | 21.04 ms | 171.35 ms | 1500.71 ms |
| 4096 in / 128 out, C=4 | 16/16 | 4.15 | 531.47 | 354.30–537.10 | 386.57 ms | 7.82 ms | 167.74 ms | 1176.29 ms |

C=1 was very stable across the three rounds; the C=8 and 4K scenarios each had one noticeably slower round. The slow rounds had no new JIT, request failures, or health check generation traffic, and the DSpark acceptance in the Engine logs also varies with generated content. Therefore, this set of results first shows that the current combination has workload-dependent fluctuation, and the best round alone cannot be picked as the capacity conclusion. Formal selection still requires fixing the real request set and adding an A/B with DSpark disabled.

Compared with the same-machine vLLM TP=8 baseline in Section 8, the median results split into two forms:

- 128/64, C=1 output throughput is about 16.7% lower, and p95 TTFT increases from about 49 ms to 174 ms;
- 128/64, C=8 output throughput is about 48.5% lower, and p95 TTFT is about 40.6% higher; the current short-request high-concurrency configuration is not advantageous;
- 4096/128, C=4 output throughput is about 91.9% higher, and p95 TTFT is about 72.2% lower; the long-Prompt scenario shows clear potential.

This is not a strict vLLM/SGLang framework ranking: the two images, CUDA versions, kernels, load test clients, and random request sets are not identical. It only shows that it is worth continuing to split validation by Prompt length; it cannot be used as a basis for switching all traffic to SGLang.

The streaming client records ITL by SSE data chunks. A single DSpark verify may accept and return multiple tokens, so one chunk may contain multiple tokens; the ITL in the table is more accurately described as "interval between adjacent client streaming chunks," while TPOT is the average generation time converted by the final output token count. When comparing ITL across engines, the same client and streaming semantics must be used.

## 13. Productionization Checklist

- Model files have integrity checks and use reusable read-only storage;
- Image version and DeepSeek V4 kernel path have been statically verified;
- Target-only, DSpark, long context, and tool calls are each accepted separately;
- Business warm-up covers real concurrency and lengths, with no new JIT in inference logs;
- Service, authentication entry point, timeouts, rate limiting, health checks, and graceful termination are configured;
- Load testing covers p50/p95/p99 TTFT, ITL, E2EL, failure rate, and GPU metrics;
- If evaluating PD, fix the total GPU count and calculate tokens/s/GPU and tail latency benefits;
- GPU resources have clear allocation, alerting, reclamation, and rollback processes.

## 14. References

- [DeepSeek-V4-Flash-0731 Model Card](https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash-0731)
- [vLLM DeepSeek-V4-Flash Recipe](https://recipes.vllm.ai/deepseek-ai/DeepSeek-V4-Flash)
- [SGLang DeepSeek V4 Cookbook](https://docs.sglang.io/cookbook/autoregressive/DeepSeek/DeepSeek-V4)
- [vLLM Disaggregated Prefilling](https://docs.vllm.ai/en/v0.8.0/features/disagg_prefill.html)
- [vLLM Parallelism and Scaling](https://docs.vllm.ai/en/v0.17.1/serving/parallelism_scaling/)
- [vLLM Compilation Configuration](https://docs.vllm.ai/en/v0.20.0/api/vllm/config/compilation/)
- [AWS CLI S3 Configuration](https://docs.aws.amazon.com/cli/latest/topic/s3-config.html)
