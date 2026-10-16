---
title: "DeepSeek-V4-Flash-Vision-Exp Day 0: 4×H20 Multimodal Deployment and Load Testing"
date: 2026-09-01
authors:
  - runzhliu
categories:
  - Inference
  - Multimodal
  - Hands-on
description: "Running DeepSeek-V4-Flash-Vision-Exp on a single node with 4×141GB H20 using SGLang Preview, documenting NVMe warm-up, 13m52s cold start, OpenWebUI image chat, and 79-round multimodal load testing."
status: published
last_reviewed: 2026-09-01
---

# DeepSeek-V4-Flash-Vision-Exp Day 0: 4×H20 Multimodal Deployment and Load Testing

On the evening of August 31, 2026, DeepSeek published
`DeepSeek-V4-Flash-Vision-Exp` on Hugging Face. This is not a renamed text-only DeepSeek-V4 model, but an experimental version of DeepSeek-V4-Flash with a complete vision encoding pipeline added: the repository page marks it as 305B, the checkpoint consists of 48 Safetensors shards totaling approximately 156.31 GiB; the vision side includes a 32-layer ViT, Aligner, image Marker, and image-visibility Attention, with a single image expanding to at most 384 Image Tokens, and native context still at 1,048,576.

After the model was released, I completed deployment, image correctness checks, OpenWebUI hands-on testing, and 79 rounds of multimodal performance testing on Kubernetes using a **single node with 4×141GB H20** and the SGLang dedicated Preview Runtime. In the end, all 3,856 requests succeeded with 0 failures; after testing, the Deployment automatically scaled down to 0 and all 4 GPUs were released.

Conclusions first:

- **It runs.** The raw HF checkpoint loads directly from node NVMe with TP4; SGLang OpenAI-compatible API, single-image, dual-image interleaved, and OpenWebUI image upload all pass.
- **Being able to `Ready` does not mean fast startup.** NVMe read of the 48 shards took only about 18 seconds, but first-time MHC compilation, DeepGEMM/FlashInfer Autotune, and two sets of CUDA Graph Capture pushed full cold start to 13 minutes 52 seconds.
- **720p cold images reached 175.06 Output tok/s at concurrency 16, but P99 TTFT rose to 3.86 seconds.**
  The Warm path with the same image reused reached 332.52 Output tok/s, with P99 TTFT dropping to 1.10 seconds.
- **Image count significantly reduces request throughput.** 2×720p at C8 was 1.71 req/s; 4×720p at C4 was 2.11 req/s. The two groups have different concurrency, so the latter cannot be used to directly infer that "four images is faster than two."
- **This is not an SGLang vs. vLLM A/B.** As of 2026-09-01, SGLang provides a Vision-Exp dedicated Preview implementation; vLLM's public DeepSeek Recipe is still the text-only V4, and a text service cannot masquerade as vision support.

References: [Model repository](https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash-Vision-Exp),
[SGLang DeepSeek-V4 Cookbook](https://docs.sglang.io/cookbook/autoregressive/DeepSeek/DeepSeek-V4),
[vLLM DeepSeek Recipe list](https://recipes.vllm.ai/deepseek-ai).

## Model Structure and Runtime Boundaries

| Item | Fixed value for this run |
| --- | --- |
| Model | `deepseek-ai/DeepSeek-V4-Flash-Vision-Exp` |
| Revision | `e46e16bf6035c6f317eb2ac7458eb0362926d402` |
| Outer architecture | `DeepseekV4ForCausalLM` |
| Repository parameter mark | 305B |
| Context | 1,048,576 |
| Checkpoint | 48 shards, 156.31 GiB |
| Weight format | MoE Experts FP4, remaining Dense/Attention FP8 Mixed |
| Vision module | 32-layer ViT, dim 1024, patch 14, up to 384 Image Tokens/image |
| Speculative decoding | DSpark, gamma=5, verify tokens=6 |

The checkpoint's outer `config.json` does not use the common standalone `vision_config` auto-discovery path; the complete vision parameters and reference implementation are located under the repository's `inference/` directory. This directly affects model registration, weight loading, and `image_url` handling in general-purpose serving engines, so the one-line launch command auto-generated on the Hugging Face page cannot replace end-to-end validation.

This run pinned the SGLang Runtime to commit
`914197146f8a3407960e5c7037d0463e03c37be9`, which is a dedicated Preview Build, not a stable release.
The runtime automatically selected DSV4 Attention, FlashInfer MXFP4 MoE, FlashInfer AllReduce Fusion, and FP8 KV Cache. The logs also warned that the checkpoint does not provide KV Scale, so the runtime fell back to 1.0; therefore, the image correctness Gate cannot be omitted just because throughput testing succeeded.

## Experimental Environment

| Item | Measured configuration |
| --- | --- |
| GPU | Single node 4×NVIDIA H20-3e, 143,771 MiB/card, SM90 |
| Driver | 580.126.20 |
| Runtime | SGLang `0.0.0.dev1+g914197146` |
| PyTorch / CUDA | `2.13.0+cu130` / `13.0` |
| Parallelism | TP4, single node |
| Model hot path | Host NVMe, read-only mount into container |
| API | OpenAI-compatible `/v1/chat/completions` |
| Client | Same `vllm bench serve --backend openai-chat` |

This is single-node TP4; Tensor Parallel communication does not cross nodes, so **RDMA is not used in this round**. A node having RDMA devices does not mean a single-node experiment can be written up as "RDMA verified." The H20 is also not in the current Vision-Exp official signed hardware matrix; this article can only prove that this combination of H20, Driver, CUDA, and Preview commit works in practice.

## Why Put Weights on NVMe First

The shared file system only handles distribution, not the serving hot path. After selecting the node, the full HF checkpoint was copied to local NVMe and verified before startup:

1. All 48 index-referenced shards exist and are non-empty;
2. Total shard file byte counts match between source and destination directories;
3. The destination directory's underlying block device is indeed NVMe;
4. Serving is only allowed to start after the write-completion Marker is in place.

This time, copying the 156.31 GiB of weights took 3 minutes 39 seconds. The public example retains only directory semantics and does not expose internal storage addresses:

```bash
findmnt -T /srv/model-cache
lsblk -o NAME,TYPE,SIZE,MOUNTPOINTS

rsync -a --partial --info=progress2 \
  /shared/models/DeepSeek-V4-Flash-Vision-Exp/v1/ \
  /srv/model-cache/DeepSeek-V4-Flash-Vision-Exp/v1/
```

## Kubernetes Launch Method

Core parameters are as follows. Image registry, node name, Namespace, and real host directories all use public placeholders:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: deepseek-v4-vision-sglang
spec:
  replicas: 1
  strategy:
    type: Recreate
  template:
    spec:
      nodeSelector:
        accelerator.example.com/model: h20-141g
      containers:
        - name: sglang
          image: <INTERNAL_SGLANG_VISION_PREVIEW_IMAGE>
          command: ["bash", "-lc"]
          args:
            - |
              exec sglang serve \
                --model-path /models/DeepSeek-V4-Flash-Vision-Exp/v1 \
                --served-model-name DeepSeek-V4-Flash-Vision-Exp \
                --trust-remote-code \
                --tp 4 \
                --speculative-algorithm DSPARK \
                --mem-fraction-static 0.85 \
                --reasoning-parser deepseek-v4 \
                --enable-metrics \
                --host 0.0.0.0 \
                --port 30000
          resources:
            requests:
              nvidia.com/gpu: "4"
            limits:
              nvidia.com/gpu: "4"
          startupProbe:
            httpGet:
              path: /v1/models
              port: 30000
            periodSeconds: 10
            failureThreshold: 720
          volumeMounts:
            - name: model-cache
              mountPath: /models
              readOnly: true
            - name: dshm
              mountPath: /dev/shm
      volumes:
        - name: model-cache
          hostPath:
            path: <NVME_MODEL_ROOT>
            type: Directory
        - name: dshm
          emptyDir:
            medium: Memory
            sizeLimit: 64Gi
```

The Preview Runtime's first-time compilation is very long, so `startupProbe` must cover the real cold-start window. Allowing up to 120 minutes here is not because normal startup takes two hours, but to prevent Kubelet from killing the pod mid-compilation and restarting from scratch.

## Cold Start: NVMe Is Not the Whole Answer

| Stage | Duration or timestamp | Observation |
| --- | ---: | --- |
| 48-shard NVMe read | ~18 s | Shared storage not on hot path |
| MHC first compilation | 192.8 s | First SM90 kernel generation |
| Main model load complete | ~247 s | 39.50 GB/card |
| DSpark load | 16.4 s | Additional 2.71 GB/card |
| Target CUDA Graph | 36.7 s | 51 batch sizes |
| Draft CUDA Graph | 90.2 s | 51 batch sizes |
| Process start to API Ready | **13 min 52 s** | Includes Autotune, JIT, and Graph Capture |

These numbers show: NVMe solves large weight reads, but cannot eliminate runtime first-time compilation and graph capture. If every pod recompiles in an empty cache environment during rolling releases, even a 156 GiB model will struggle to recover in minutes. Before production, compilation cache persistence, pre-compiled artifacts in images, and phased rollout strategies should be further validated.

## Functional Correctness and OpenWebUI

First, four deterministic Gates were run using the cat and dog images bundled in the Preview image: text-only returns only `TEXT_OK`, cat image returns only `CAT`, dog image returns only `DOG`, and cat-to-dog dual-image interleaved returns only `CAT,DOG`. All passed; answers change with image substitution, and dual-image order is also correct, so this is not "HTTP 200 but images ignored."

The same OpenAI-compatible API was then connected to OpenWebUI. After uploading a cat image in Light mode, the model correctly identified the cat, pink hooded leather jacket, and sunglasses, completing the loop across cluster access, model discovery, image upload, Chat Template, and multimodal response.

![DeepSeek-V4-Flash-Vision-Exp image test in OpenWebUI](../../assets/practices/deepseek-v4-flash-vision-exp-day0/openwebui-multimodal-light.png)

## Load Testing Methodology

The main test does not evaluate quality with real datasets; instead, it generates deterministic 360p, 720p, 1080p, and multi-image JPEGs specifically to measure serving performance. Cold Cases use a different image per request; Warm Cases reuse the same image. All cases fix output at 64 Tokens, with `request-rate=inf`, `ignore-eos`, and Seed fixed; each valid point records three rounds, and the table takes the median metric per round.

```bash
vllm bench serve \
  --backend openai-chat \
  --base-url http://<sglang-service>:30000 \
  --endpoint /v1/chat/completions \
  --model DeepSeek-V4-Flash-Vision-Exp \
  --dataset-name custom_image \
  --dataset-path <CASE_JSONL> \
  --custom-output-len 64 \
  --custom-ensure-client-side-data \
  --enable-multimodal-chat \
  --request-rate inf \
  --ignore-eos \
  --disable-shuffle \
  --save-result --save-detailed
```

Although the client command name is `vllm bench serve`, the service under test is still SGLang. It only sends requests through the OpenAI-compatible HTTP interface; a unified client facilitates future framework A/B testing. SGLang's built-in Benchmark Client can be used for engine-internal diagnostics, but numbers from two different clients cannot be directly combined into a fair comparison.

This round generated 79 result JSONs total: 112 warm-up requests and 3,744 official requests, for a combined **3,856 successes, 0 failures**. The full matrix took 46 minutes.

## Performance Results

### Single-Image Cold and Warm

| Case | Concurrency | Req/s | Output tok/s | P50 TTFT | P99 TTFT | P50 TPOT |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 360p Cold | 1 | 1.55 | 99.43 | 225.15 ms | 230.09 ms | 6.57 ms |
| 360p Cold | 4 | 2.71 | 173.19 | 236.48 ms | 516.07 ms | 18.94 ms |
| 360p Cold | 8 | 3.46 | 221.40 | 426.19 ms | 718.60 ms | 31.05 ms |
| 360p Cold | 16 | 4.34 | 277.66 | 463.62 ms | 1,243.54 ms | 47.91 ms |
| 360p Warm | 1 | 1.59 | 101.87 | 189.28 ms | 195.55 ms | 7.00 ms |
| 360p Warm | 4 | 3.01 | 192.90 | 201.70 ms | 371.30 ms | 17.44 ms |
| 360p Warm | 8 | 3.87 | 247.44 | 214.16 ms | 524.96 ms | 28.42 ms |
| 360p Warm | 16 | 5.30 | 339.17 | 376.11 ms | 674.81 ms | 40.92 ms |
| 720p Cold | 1 | 1.25 | 80.09 | 378.21 ms | 386.84 ms | 6.58 ms |
| 720p Cold | 4 | 1.98 | 126.96 | 401.66 ms | 1,072.97 ms | 24.14 ms |
| 720p Cold | 8 | 2.35 | 150.34 | 731.92 ms | 1,963.41 ms | 42.18 ms |
| 720p Cold | 16 | 2.74 | 175.06 | 932.64 ms | 3,861.24 ms | 69.06 ms |
| 720p Warm | 1 | 1.66 | 106.09 | 209.24 ms | 214.50 ms | 6.38 ms |
| 720p Warm | 4 | 3.10 | 198.70 | 236.05 ms | 399.69 ms | 15.38 ms |
| 720p Warm | 8 | 4.06 | 259.62 | 368.13 ms | 624.84 ms | 24.81 ms |
| 720p Warm | 16 | 5.20 | 332.52 | 426.87 ms | 1,103.43 ms | 40.17 ms |

For 720p at C16, the Warm path relative to Cold: both request throughput and output throughput improve by about 90%, P50 TTFT drops 54.2%, and P99 TTFT drops 71.4%. This is not "the model itself suddenly became twice as fast," but rather that same-image reuse reduces repeated vision preprocessing and Encoder work. If real business traffic has mostly unique images, the Cold table should be used as the capacity baseline.

### High Resolution and Multi-Image

| Case | Concurrency | Req/s | Output tok/s | P50 TTFT | P99 TTFT | P50 TPOT |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1080p Cold | 1 | 1.28 | 82.04 | 399.35 ms | 404.21 ms | 6.17 ms |
| 1080p Cold | 4 | 2.11 | 134.74 | 753.29 ms | 1,090.56 ms | 16.94 ms |
| 1080p Cold | 8 | 2.54 | 162.38 | 912.25 ms | 1,992.23 ms | 33.05 ms |
| 2×720p Cold | 1 | 1.03 | 66.22 | 571.68 ms | 580.31 ms | 6.45 ms |
| 2×720p Cold | 4 | 1.50 | 96.02 | 1,035.90 ms | 1,926.30 ms | 26.43 ms |
| 2×720p Cold | 8 | 1.71 | 109.42 | 1,431.42 ms | 3,678.51 ms | 51.90 ms |
| 4×720p Cold | 1 | 0.74 | 47.44 | 990.36 ms | 1,000.40 ms | 5.56 ms |
| 4×720p Cold | 4 | 2.11 | 134.75 | 800.79 ms | 1,192.45 ms | 16.07 ms |

For multi-image scenarios, you should look at Req/s, TTFT, and image count together, not just Token/s. 4×720p at C4 processes about 8.44 images per second, but each request itself contains four images; its scheduling pressure differs from 2×720p at C8, so you cannot rank horizontally by Req/s alone.

### First-time new-shape JIT must be recorded separately

The first officially recorded P99 TTFT for 360p at C16 was 7.91 seconds, and the following two rounds dropped to about 1.22–1.24 seconds. All raw JSON was retained; the main table follows the pre-defined rule of taking the median of three rounds, which is 1.24 seconds, without deleting the first round. For the Preview Runtime, after `/v1/models` is Ready, there may still be first-time compilation for new Batch Shapes, so Canary warm-up needs to cover the resolutions, image counts, and concurrency planned for production use, not just send a single text request.

## OpenWebUI integration

OpenWebUI only needs an OpenAI-compatible Base URL that is reachable from its own network:

```text
http://<gateway-or-service>/v1
```

Before integration, verify `/v1/models` and one `/v1/chat/completions` carrying a Data URL from the network where the OpenWebUI Pod resides. If the model appears in the selector but there is no image upload button, you also need to explicitly mark Vision in OpenWebUI's model capability settings; in this version, image upload can be completed directly from the returned model, without needing a frontend plugin.

In cross-cluster scenarios, do not write temporary Pod IPs into OpenWebUI. You can use a fixed Ingress, Gateway API, or create a Selectorless Service + EndpointSlice in the OpenWebUI cluster pointing to a stable entry point. Public configurations should remove real internal network addresses.

## Why there is no vLLM data

As of 2026-09-01, the DeepSeek-V4-Flash listed on the vLLM Recipe page is a text model, and there is no Vision-Exp under the Multimodal category either. The text V4 being able to load language weights from the same family does not mean it can load ViT/Aligner, process `image_url`, maintain image visibility masks, and correctly return visual answers.

Therefore, this article does not do the following two things:

1. It does not use the text-only vLLM image to run "image requests" and then write the errors off as poor vLLM performance;
2. It does not let images be silently ignored and then fake an SGLang/vLLM A/B comparison just because of an HTTP 200.

Once vLLM has explicit model registration, a dedicated Recipe, and image E2E tests, the same client, the same JSONL, the same H20 node, and the same NVMe Checkpoint from this article can be reused for a fair retest.

## Production recommendations

1. **Pin the Preview commit and image Digest.** Do not use a drifting `latest`.
2. **CFS is only the source; NVMe is the hot path.** Verify the Block Device and complete Marker before startup.
3. **Reserve at least 15 minutes of cold-start budget.** Also persist the compilation/Autotune Cache and verify whether it can shorten the second startup.
4. **Apply Admission Control by image count and resolution.** The same text token count does not mean four-image requests have the same cost.
5. **Build capacity baselines separately for Cold/Warm.** Do not cite Warm results when business images are unique.
6. **Keep the first-time new-shape tail latency.** Canary warm-up covers real concurrency; do not delete the "ugly" first round.
7. **Separate quality from performance.** The cat-and-dog Gate in this article proves the image pipeline works, but it cannot replace quality evaluations such as MMMU, MathVista, RealWorldQA, and OCRBench.
8. **Automatically release GPUs when the task ends.** This time, a least-privilege cleanup Job scaled the Deployment to 0 after the Benchmark `Complete` and confirmed the Serving Pod exited.

## What this article did not prove

- Did not verify the model's claimed 1M Context with images as joint input;
- Did not run standard vision quality datasets, so no model capability ranking can be given;
- Did not verify cross-node TP/EP, RDMA, or P/D separation;
- Did not obtain vLLM Vision-Exp data, so no framework winner can be declared;
- Preview Runtime, FP8 KV Scale fallback, and H20 non-officially-signed hardware remain launch risks.

But the most critical Day 0 engineering question has been answered: **DeepSeek-V4-Flash-Vision-Exp can provide real multimodal service on 4×141GB H20 via SGLang Preview with TP4; the NVMe weight hot path, OpenWebUI image pipeline, and the 3,856-request performance matrix are all closed-loop, and the GPUs were automatically released after the test ended.**

## Reproduction materials

- [`examples/deepseek-v4-flash-vision-exp/`](https://github.com/runzhliu/aik8s/tree/main/examples/deepseek-v4-flash-vision-exp)
- [DeepSeek-V4-Flash-Vision-Exp model repository](https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash-Vision-Exp)
- [SGLang DeepSeek-V4 Cookbook](https://docs.sglang.io/cookbook/autoregressive/DeepSeek/DeepSeek-V4)
- [vLLM DeepSeek Recipe list](https://recipes.vllm.ai/deepseek-ai)
