---
title: "MiniMax-M3 H20 Deployment Failure and Fix Record"
description: "Record of image dependencies, model startup, client path failures, and abnormal input handling during MiniMax-M3 testing."
---

# MiniMax-M3 H20 Deployment Failure and Fix Record

MiniMax-M3 is an MoE model supporting text, image, and video inputs. This test was conducted on a single-node eight-card H20-3e with BF16 TP8 and a 32K window, covering both SGLang and vLLM. This document records the actual issues encountered, verified fixes, and unresolved edge cases; full performance and functional results are in the [test report](minimax-m3-h20-benchmark.md).

## Issues, Fixes, and Verification in Image Preparation

The following comes from actual checks during image preparation. Dependency checks, module entry points, CLI, and codec verification were each validated separately, avoiding the mistake of relying solely on a successful image build before moving to GPU-occupying tests. Reusable implementations are in the [image directory](https://github.com/runzhliu/aik8s/tree/main/examples/minimax-m3-h20/images), and condensed evidence is in the [CPU check record](https://github.com/runzhliu/aik8s/blob/main/examples/minimax-m3-h20/images/cpu-verification-summary.json). Full raw logs are archived separately.

### 1. SGLang: First Clarify the Difference Between CUDA 12 and CUDA 13

Initially, we checked the CUDA 12.9 image following the official SGLang Hopper recipe. The CLI could output help, but `pip check` returned 1, revealing seven dependency issues, including missing `nixl-cu13`, a CUDA Python version lower than SGLang's declared requirement, an outdated CUDA pathfinder version, and version conflicts among NumPy, Pillow, and setuptools. Therefore, a working CLI does not prove that the environment dependencies are complete.

Retries occurred again when downloading large layers of that image through a relay. We then found the official CUDA 13 build for the same SGLang commit `56e290315b8fdb4c8c10f8e31360d9bc3d878633` and an existing repository copy, and switched to verifying that route. The CUDA 12 image was kept as a troubleshooting record and was not delivered as a successfully fixed image.

We cannot trust an existing copy just because the tag is the same. This time we verified that its config digest matches the official one, and after actually pulling it, we checked all **63 decompressed layers' diffIDs are identical**. The compressed layer digests differ, indicating different compression representations, so it cannot be described as all blobs being identical. Only after verifying content identity did we use this copy as a build base; the public Dockerfile still defaults to the official amd64 digest.

The Torch architecture list in the CUDA 13 build includes `sm_90`, which is a prerequisite for subsequent Hopper verification. It does not prove that M3-specific kernels, NCCL, or H20 services have run successfully; the differences between the official CUDA 12 Hopper recipe and this CUDA 13 candidate must be further validated in the GPU phase.

### 2. SGLang: NIXL Cannot Be Fixed by Uninstalling Entry Points

The CUDA 13 base image had two remaining errors:

```text
nixl 1.2.0 requires nixl-cu12, which is not installed.
moviepy 2.2.1 has requirement pillow<12.0,>=9.2.0, but you have pillow 12.2.0.
```

The first attempt treated `nixl` as a removable dependency metapackage: after uninstalling it, `pip check` passed, but the supplementary `find_spec('nixl')` entry assertion failed, and the build was blocked and not released. Inspection of the installed files revealed that `nixl` actually contains Python entry points such as `nixl/__init__.py` and `nixl/_api.py`; one cannot simply delete based on dependency check results.

The final solution kept `nixl==1.2.0` and the existing `nixl-cu13==1.2.0`, added the declared required `nixl-cu12==1.2.0`, and pinned Pillow to `11.3.0`:

```bash
python3 -m pip install --no-cache-dir nixl-cu12==1.2.0 pillow==11.3.0
python3 -m pip check
python3 -c "import importlib.util as u; assert u.find_spec('nixl') is not None"
```

Why does the CUDA 13 image still contain a CUDA 12 NIXL package? The NIXL 1.2.0 dependency declaration we actually checked includes two backend packages that use independent `nixl_cu12` and `nixl_cu13` namespaces; the frontend selects a backend based on `torch.version.cuda`. Since this image's Torch is CUDA 13, that selection logic points to `nixl_cu13`. This verifies dependency closure and entry point preservation, but NIXL GPU data transfer has not yet been run.

After the fix, `pip check` outputs `No broken requirements found.`, and the SGLang CLI and PyAV codec checks passed. The final solution did not carry over the CUDA Python downgrade or NIXL uninstall operations from the earlier CUDA 12 attempt.

### 3. vLLM: Remove Unrelated System Dependencies and Add Video Decoder

The vLLM base image's dependency check found that `pygobject 3.42.1` was missing `pycairo`. After locating the system GI and software source management tool dependencies in the image, the fix layer removed three system packages not involved in this model service—`python3-gi`, `python3-software-properties`, and `software-properties-common`—without performing a global `autoremove`.

Another check result was that the base image did not have PyAV/Decord installed. This alone does not allow concluding that the model does not support video, but for subsequent video tests we added a pinned `av==16.1.0`:

```bash
apt-get remove -y python3-gi python3-software-properties software-properties-common
python3 -m pip install --no-cache-dir av==16.1.0
python3 -m pip check
```

After the fix, the dependency check passed. The video probe generated an 8-frame, 64×64 MPEG-4 sample in memory, encoded it as MP4, then decoded it with PyAV and asserted frame count and width, obtaining `AV_ROUNDTRIP_PASS 8`. This verifies the basic codec chain; frame sampling, Processor, vision encoder, and answer correctness for real video requests remain part of subsequent model testing.

### 4. vLLM: Distinguish CPU Client from GPU Service Initialization

Running the original `vllm serve --help=all` in a zero-GPU container produced `Failed to infer device type`. The global CLI of this pinned version initializes device-related defaults when constructing command arguments, affecting even the load-testing client entry point that only sends HTTP requests.

The handling was split into two parts: the image probe kept the original failure, then explicitly used `CpuPlatform` to check argument parsing; the standalone [bench_client.py](https://github.com/runzhliu/aik8s/blob/main/examples/minimax-m3-h20/bench_client.py) selects the CPU platform only for the HTTP load-testing client. **The actual inference service startup script does not force the CPU platform.** This client adaptation uses a pinned internal interface and must be re-validated when upgrading vLLM.

Explicit CPU argument parsing and load-testing CLI argument checks both passed; the original GPU auto-detection error remains in the report. This phase status is marked as `CPU_PASS_GPU_CLI_DEFERRED`, indicating only that CPU checks are complete; subsequent GPU model functionality and the official main matrix have passed, as detailed in the test report.

### 5. Build and Image Relay: Verify Through to the Final Pull Endpoint

The build also encountered PyPI download stalls and additional Dockerfile frontend pull hangs. Dependency downloads switched to a configurable `PIP_INDEX_URL`; directly fixed dependencies retain exact versions; simple ARG/FROM/RUN builds removed unnecessary external frontend directives and used the built-in frontend. Rebuilds checked exit codes, failed attempt logs were kept, and new images recorded independent digests without overwriting existing acceptance conclusions.

Local push once returned `unauthorized`, then we switched to an existing authorized relay push channel. Credentials were provided through existing credential files, not placed in public commands or Dockerfiles. Cross-repository copying first confirmed the staging image, then checked the production sync and target cloud copy each for their final state; `queued` only represents submission success.

Finally, on the target cluster, we ran a zero-GPU Pod with the fixed image, verified the actual `imageID` and probe results, then archived and cleaned up. Evidence from image builds, copies, and CPU checks does not replace weight loading and GPU functional acceptance. The final versions and check statuses are per the [image manifest](https://github.com/runzhliu/aik8s/blob/main/examples/minimax-m3-h20/images/images.lock.json).

### 6. CFS Mount Failure and Node Selection

The model inventory Pod was initially scheduled to a CPU node, resulting in `MountVolume.MountDevice failed`, with CSI returning `node has not turbo kernel mod`. This is due to the node missing the kernel module required for CFS Turbo; it cannot be interpreted as the model directory not existing or weights being corrupted.

The fix kept the same read-only PVC, rescheduled the inventory Pod to a target GPU resource pool node that already has that mount capability, and set explicit node selection and corresponding tolerations. After remounting, the model directory could be read. No model files, PVC, or host kernel were modified. Subsequent CPU check clients also need to confirm node storage capability; simply requesting GPU is not sufficient.

Node selection is an immutable field of a Pod. When recreating, you must first confirm the old Pod is actually deleted before submitting the new manifest; immediately after a delete request returns, the object may still be in Terminating, and an immediate apply will be treated as an illegal update.

### 7. Admission Constraints on Pod Preemption Policy

The initial GPU pre-check explicitly set `preemptionPolicy: Never` but did not specify a matching PriorityClass. The cluster admission controller computed `PreemptLowerPriority` based on the priority configuration, and the mismatch caused the Pod creation to be rejected.

After checking existing PriorityClasses, we confirmed there was no reusable non-preempting class; this time we used the default priority 0, verified that existing workloads on the specified node all have priority not lower than 0, and that all eight GPUs were indeed unallocated, then submitted a Pod with precise node selection. We did not raise priority, create a global PriorityClass, or evict other tasks. In general deployments, if strict non-preempting semantics are needed, use the `preemptionPolicy: Never` PriorityClass already configured by cluster administrators; you cannot simply override values in the Pod that conflict with admission rules.

### 8. Startup Budget Must Cover Weight Loading and Two Types of Graph Initialization

On the first SGLang startup, weight loading across eight ranks took 1,481.53–1,481.82 seconds (about 24 minutes 42 seconds), followed by successful capture of the normal decoding CUDA Graph for bs=4/2/1, taking about 84.7 seconds. Merely observing that GPU memory was allocated does not allow counting the earlier read time as the service being ready.

The engine then continued with segmented CUDA Graph initialization, covering 42 shape buckets from 4 to 2,048 tokens by default. The original Pod's startup probe budget was only 30 minutes, insufficient to cover weight loading and all graph initialization. Therefore, while the API was not yet ready, we kept logs, ended the first attempt, and retried after adjustments; this does not indicate weight corruption or OOM, and we do not record the intentional termination as a probe timeout that occurred.

The second attempt used `--disable-piecewise-cuda-graph` to disable segmented graphs, kept the normal decoding CUDA Graph, changed the startup probe budget to 60 minutes, and retained the Pod's overall runtime limit. This pinned image warns that the old parameter is deprecated and maps to `--cuda-graph-backend-prefill=disabled`; this repository's scripts use the latter, and the actual runtime configuration must verify the prefill backend is disabled. The two startup logs are saved separately, and cache states must be recorded separately; the second startup time cannot be directly treated as a performance improvement under the same cold cache conditions.

```bash
# 功能验收配置；对性能的影响须通过后续独立对照测量。
ENGINE=sglang DISABLE_PIECEWISE_CUDA_GRAPH=1 \
MAX_CONTEXT=8192 MAX_REQUESTS=4 EXECUTE=1 bash launch.sh
```

`DISABLE_PIECEWISE_CUDA_GRAPH` is an optional switch in this repository's startup script, currently enabled by default, meaning prefill segmented graphs are disabled. The second attempt actually had the API ready, and all 12 functional checks passed, covering three inference modes, tool calling and result backfill, streaming, multi-turn, image and video understanding, invalid parameters, and recovery. Weight loading took about 734–763 seconds, and normal decoding graph capture about 45 seconds; due to changed cache conditions, this cannot be directly compared with the first attempt for loading performance. The startup probe covers loading and initialization, while the readiness probe determines whether to receive traffic; neither should replace functional testing.

The logs also indicated a missing Triton MoE tuning configuration for `NVIDIA_H20-3e`, E=129/N=384, and the current run used default configuration. This is a performance tuning hint and cannot be directly interpreted as the model not supporting H20. Subsequent performance results should note whether tuning was applied; dedicated kernel configurations must be generated and verified on actual hardware, and you cannot simply rename configurations from other GPUs and claim optimization.

### 9. Unattended Client Cannot Pin the Old Version Directory of a ConfigMap

After the vLLM service was ready, the automated acceptance first startup sub-script returned `No such file or directory`. Investigation found that the controller used `Path(__file__).resolve().parent`: the ConfigMap files are projected symbolic links that resolve to a versioned temporary directory. While the controller was waiting for model loading, the ConfigMap was updated, the old version directory was reclaimed, and when `smoke.py` was subsequently started, the path no longer existed.

The fix was to retain a stable mount entry: `Path(__file__).absolute().parent`. The old attempt was archived separately, and a new attempt reran the client; the model service did not need to be restarted. We added a regression test simulating ConfigMap switching and deleting the old directory during the wait period; after the fix, the controller completed the entire simulated flow. Controller startup failures and model inference failures are recorded separately; this failure is not counted in the request error rate, and original logs are not deleted.

### 10. After the Main Load Test Passes, Semantic Acceptance Still Requires Independent Judgment

The vLLM main matrix completed 33 rounds with 3,954 requests, and all checks on completion count, error count, and token count passed. Subsequent extended acceptance found that six solid-color static image configurations failed to correctly answer colors during the warm-up phase and were therefore not included in the corresponding formal image load tests; the video color order test still passed. The original PNG RGB pixels were checked: the red image is indeed (255,0,0) and the blue image is indeed (0,0,255). JPEG retests still showed misjudgments; the red image with a border and the original chart reading were normal. Currently, this result cannot be described as "image generation file corruption," nor can passing with a bordered image override the failure of solid-color images.

The original retrieval template with about 31K of body text also returned NOT_FOUND. After shortening to a single record, the original template still failed; when explicitly asking to extract the full text after "验收密钥:" within `<document>`, the correct value was obtained in both the short text and the original ~31K document. This shows that the original template failure alone cannot determine that the model does not support 32K. Independent retests kept the original key, interference content, and insertion position, and separately recorded the prompt wrapper change; both engines each passed nine answer-containing samples at three positions and one no-answer control. Implementation is in [needle_retest.py](https://github.com/runzhliu/aik8s/blob/main/examples/minimax-m3-h20/needle_retest.py).

For the same arithmetic problem, when asked to "output only the final integer," the disabled mode repeatedly answered 264, while adaptive/enabled returned the correct 240. The three repeated requests are reproductions of the same problem, not an accuracy evaluation of three independent problems. The public report lists correctness, output tokens, and latency together, and does not use a shorter wrong answer to prove a mode is better.

The above are input and mode boundaries observed this time; we did not modify weights or inference engines to claim a model fix. Original failed requests, diagnostic requests, and retest results are saved separately. Only execution issues that were located and corrected, such as the test script's path failure, are marked as fixed and passed.

## Completed Eight-GPU Hardware Pre-check

The two fixed images ran serially on the same node, each verifying the model and capacity of all eight GPUs, finiteness of BF16 matrix computation results, and correctness of NCCL all-reduce element summation. Each size was warmed up 5 times, measured 20 times, and the algorithm bandwidth was calculated using the average time of the slowest rank.

| Image Environment | 1 MiB Correctness | 16 MiB Correctness | 128 MiB Correctness | 128 MiB Algorithm Bandwidth |
| --- | --- | --- | --- | ---: |
| SGLang / Torch 2.11.0+cu130 | PASS | PASS | PASS | 235.9 GB/s |
| vLLM / Torch 2.11.0+cu130 | PASS | PASS | PASS | 235.6 GB/s |

This is a single short-duration hardware connectivity check; the algorithm bandwidth is not NCCL bus bandwidth. It does not load M3 and is not used to compare model throughput between the two inference engines. Small-message latency is susceptible to scheduling and startup fluctuations; full communication performance evaluation requires repeated measurements and statistics. Reproduction script is in [gpu_preflight.py](https://github.com/runzhliu/aik8s/blob/main/examples/minimax-m3-h20/gpu_preflight.py), and condensed results are in the [GPU pre-check record](https://github.com/runzhliu/aik8s/blob/main/examples/minimax-m3-h20/images/gpu-preflight-summary.json).

The tested node has dual sockets and two NUMA domains. GPU 0–3 map to NUMA 0 (CPU 0–191), GPU 4–7 map to NUMA 1 (CPU 192–383), and every GPU pair topology shows NV18. NVLink connectivity between GPUs does not imply that CPU preprocessing, host memory, and GPU copies naturally satisfy NUMA locality. During deployment, GPU interconnect, Worker CPU affinity, and host memory allocation should be recorded separately; binding optimization is validated as an independent experiment, and the two NUMA domains should not be simply treated as GPUs communicating only through the CPU interconnect.

### 11. SGLang: HTTP status code for corrupted media not passed

The formal extended acceptance submits invalid PNG and MP4 content: vLLM returns 400 for both, SGLang returns 500 for both. SGLang logs show that PIL's `UnidentifiedImageError` and TorchCodec invalid-input errors are wrapped by the multimodal loader as `RuntimeError`, and the service entry point responds to them as internal errors. Afterward, the normal-request recovery check passes and the process does not exit, but the error-code acceptance still fails. This round did not modify the engine source code or redefine the pass criteria; this is an interface boundary that still needs fixing. It is recommended to convert explicit media format validation errors into client errors while preserving the 500 semantics for other runtime exceptions, and to separately verify the corrupted-media, normal-multimodal, and recovery paths after the fix.
