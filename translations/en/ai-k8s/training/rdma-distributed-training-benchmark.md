---
title: "How Much Faster Does RDMA Really Make Distributed Training: DeepSeek V4 Dual-Node 16-GPU Field Test"
description: "Using NCCL AllReduce/All-to-All microbenchmarks, DeepSeek V4 Flash MoE SFT positive/negative comparisons, and six SwanLab runs to explain which parallelization strategies actually benefit from RDMA"
---

# How Much Faster Does RDMA Really Make Distributed Training: DeepSeek V4 Dual-Node 16-GPU Field Test

Results first: with the same set of `2 节点 × 8 GPU`, same model, data, batch, image, and rank mapping, switching DeepSeek V4 Flash `PP=1、EP=16、Dense DP=16` training from TCP Socket to GPUDirect RDMA reduced the median of three-round stable step means from `4.490` to `3.050 秒/Step`, a **32.08%** step-time reduction, equivalent to a **47.23%** throughput improvement.

However, in another `PP=2、EP=8` comparison, RDMA was actually `0.35%` slower than TCP, which is normal noise with no measurable benefit. The two results are not contradictory: the former places both MoE All-to-All and Dense DP synchronization on the cross-node path, while the latter keeps EP/DP communication groups within each node, with only Pipeline Activation crossing machines.

![Differences of the same RDMA under two parallel topologies](../../assets/training/deepseek-v4-rdma/topology-matters.svg)

The real question this experiment aims to answer is not "how high is RDMA bandwidth," but rather: **what kind of training communication enters the critical path of a step and translates into end-to-end gains.**

## 1. Which Training Workloads Are More Likely to Benefit from RDMA

The highest-priority categories are typically:

| Training Form | Typical Cross-Node Communication | RDMA Benefit Tendency |
| --- | --- | --- |
| Expert Parallel in Large MoE | Token Dispatch/Combine, core is All-to-All | High, especially when EP groups span nodes |
| Dense Full-Parameter DDP | Large gradient sync every step, core is AllReduce | Medium to high |
| FSDP / ZeRO-3 | Reduce-Scatter, AllGather, parameter and gradient sharding | Medium to high, depends on compute-communication overlap |
| Cross-Node Tensor Parallel | Collectives in nearly every layer | High, but also most susceptible to latency and topology |
| Pipeline Parallel | Point-to-point Activation/Gradient transfer between stages | Depends on micro-batch, sequence, and activation sizes |
| Small models or very small LoRA | Small trainable gradients, compute often dominates | Often low |

A practical heuristic is:

```text
RDMA 的端到端价值
≈ 跨节点通信在稳定 Step 中的占比
× RDMA 能消除的那部分通信时间
× 不能被计算重叠隐藏的比例
```

Therefore, seeing `NET/IB` in NCCL logs only proves the link was selected; only a real training A/B with all other variables fixed can show whether it delivers value for the current workload.

## 2. Test Design: First Prove the Link, Then Measure Real Training

This round uses two layers of evidence:

1. NCCL microbenchmarks test both AllReduce and All-to-All, answering whether the high-speed network actually works;
2. DeepSeek V4 Flash MoE LoRA runs a strict TCP/RDMA A/B, answering whether the network difference translates into real step gains.

### 2.1 Fixed Items

| Item | Configuration |
| --- | --- |
| GPU | 2 nodes × 8 NVIDIA H20 141 GB, World Size 16 |
| Model | DeepSeek V4 Flash 0731, Block-FP8 base, BF16 LoRA |
| Trainable parameters | 242.456M / 24,863.382M, approximately 0.9752% |
| Parallelism | TP=1, PP=1, EP=16, Dense DP=16, Expert DP=1 |
| Data | 330 fixed training samples, SHA-256 fixed |
| Batch | Micro Batch 1, Global Batch 16 |
| Sequence | Max Length 512 |
| Timing | 20 steps per round, first 5 steps discarded, comparing Steps 6–20 |
| Repetition | TCP 3 rounds, RDMA 3 rounds |
| Exclusions | Eval and Checkpoint disabled; model loading, compilation, and tokenization excluded from the stable segment |

Each A/B pair uses the same nodes and rank layout. In the third round, the direction of which node held Rank 0 was swapped between the two nodes, and results remained consistent, reducing the risk of bias from "one machine is always faster."

### 2.2 Transport Acceptance

The TCP group explicitly disabled IB and confirmed in NCCL INFO:

```text
NET/Socket
```

The RDMA group not only requested RDMA devices but also confirmed cross-node channels using:

```text
NET/IB/.../GDRDMA/Shared
GPU Direct RDMA Enabled
```

If you only see that the node has RDMA NICs, the Pod is attached to the device, or you only set `NCCL_IB_DISABLE` to `0`, that does not count as link acceptance.

### 2.3 What GDRDMA Solves Beyond Regular RDMA

Regular TCP causes cross-node tensors to traverse multiple segments: GPU memory, host memory, kernel network stack, and NIC. RDMA bypasses the kernel network stack, but if GPU data still needs to land in host memory first, CPU, PCIe, and memory bandwidth still participate in the relay. GPUDirect RDMA (GDRDMA below) allows compatible NICs to DMA GPU memory directly over PCIe, reducing host memory bounce, CPU copies, and interrupt overhead.

```text
TCP：     GPU → Host Memory → Kernel/Socket → NIC → Network
RDMA：    GPU → Host Memory → RDMA NIC       → Network
GDRDMA：  GPU Memory      ↔ RDMA NIC          → Network
```

This path typically delivers three kinds of value: large-message collectives are more likely to approach NIC bandwidth; latency and CPU overhead for frequent communication are lower; and once CPU and host memory no longer bear the same scale of bounce buffers, step-time jitter in training converges more easily. This is especially important for the `EP=16` in this round, because MoE Token Dispatch/Combine executes All-to-All across machines every step.

GDRDMA requires both hardware capability and is affected by physical topology:

- GPU, RDMA NIC, PCIe platform, and drivers need to support peer memory; on the kernel side this is typically provided by DMA-BUF or `nvidia-peermem`;
- GPU-to-NIC should ideally be on the same NUMA and share a nearby PCIe Root Complex; `SYS` paths across CPU sockets add overhead;
- NVLink/NVSwitch handles intra-node GPU-GPU communication; GDRDMA handles cross-node GPU-NIC-GPU communication; the two are complementary rather than substitutable;
- Kubernetes allocating GPU and RDMA devices is only a prerequisite; NCCL, CUDA, NIC driver, peer memory, and container device mappings must all match together.

The `nvidia-smi topo -m` of this round's nodes shows 8 GPUs each with a one-to-one corresponding NIC: `GPU0↔NIC0`, `GPU1↔NIC1`, up to `GPU7↔NIC7`, all being `PIX`, meaning at most one PCIe bridge is traversed; GPUs 0–3 and GPUs 4–7 belong to two NUMA domains, but each local NIC remains on the same NUMA. NCCL ultimately selects the corresponding HCA for each cross-node rank according to this mapping and reports:

```text
Channel 00/0 : 0[0] -> 8[0] [send] via NET/IB/0/GDRDMA
Channel 01/0 : 1[1] -> 9[1] [send] via NET/IB/1/GDRDMA
...
Channel 07/0 : 7[7] -> 15[7] [send] via NET/IB/7/GDRDMA
```

Acceptance must therefore be done in four layers: the Pod can see the RDMA device; the GPU/NIC topology shows no obvious detours; NCCL INFO explicitly shows cross-node `NET/IB/.../GDRDMA`; and finally a TCP/RDMA A/B with the same training workload. The first three layers prove "the path is valid," and the fourth answers "how much faster the business runs."

Note that this chapter compares the overall difference between `NET/Socket` and `NET/IB + GDRDMA`, and does not add a separate third group of "IB but GDRDMA disabled," so the full 32.08% step-time reduction cannot be attributed solely to GDRDMA. To isolate its contribution, one should keep the IB transport unchanged, only control NCCL's GDR policy, and run another three-round A/B.

References: [NVIDIA GPUDirect RDMA documentation](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/gpu-operator-rdma.html), [NCCL environment variables](https://docs.nvidia.com/deeplearning/nccl/user-guide/docs/env.html).

## 3. NCCL Microbenchmarks: Large Communication Capability Gap

The microbenchmark uses 16 ranks, message size `1/16/64/256 MiB per Rank`, 5 warmup iterations and 20 formal iterations per point, taking the slowest rank's time. TCP and RDMA are each repeated for three rounds.

On `256 MiB/Rank`, the three-round medians are:

| Collective | TCP Latency | RDMA Latency | TCP Algorithm Bandwidth | RDMA Algorithm Bandwidth | RDMA / TCP |
| --- | ---: | ---: | ---: | ---: | ---: |
| AllReduce | 190.105 ms | 1.313 ms | 1.412 GB/s | 204.482 GB/s | **144.81×** |
| All-to-All | 185.601 ms | 6.851 ms | 1.446 GB/s | 39.180 GB/s | **27.09×** |

![NCCL AllReduce and All-to-All three-round medians](../../assets/training/deepseek-v4-rdma/nccl-bandwidth.svg)

The `GB/s` here is the **algorithm bandwidth** of the 16-rank collective, not single-NIC line rate. Nor should `144.81×` be written as "training is 144× faster": communication is only part of a training step; compute, memory access, kernels, data loading, and framework overhead that cannot be parallelized all still exist.

The raw data also exposes valuable jitter: the third round of RDMA All-to-All was only `18.763 GB/s`, while the first two rounds were `39.180 / 44.458 GB/s`. The report therefore uses three-round medians while also publishing raw values; selecting only the fastest round would significantly exaggerate stability.

## 4. Real SFT: Stable Steps About One-Third Faster

The `train_speed(s/it)` reported by SwanLab is the "cumulative mean from step 1 to the current step," where the first two steps include compilation and communication warmup. Directly comparing the cumulative value at step 20 would continue to amortize initialization costs into the result. Here we first back out the per-step instantaneous time:

```text
instant_n = n × cumulative_mean_n - (n - 1) × cumulative_mean_(n - 1)
```

Then we average only Steps 6–20. The three-round results are:

| Round | TCP Stable Mean | RDMA Stable Mean | Step-Time Reduction | Equivalent Throughput Gain |
| --- | ---: | ---: | ---: | ---: |
| R1 | 4.437 s | 3.028 s | 31.74% | 46.50% |
| R2 | 4.490 s | 3.095 s | 31.07% | 45.07% |
| R3 | 4.566 s | 3.050 s | 33.20% | 49.71% |
| **Three-round median** | **4.490 s** | **3.050 s** | **32.08%** | **47.23%** |

With Global Batch 16 fixed, equivalent sample throughput increased from `3.563` to `5.246 samples/s`. This throughput is training throughput derived from stable step time, excluding model loading, checkpoints, and experiment reporting teardown.

![DeepSeek V4 Flash three-round TCP and RDMA stable steps](../../assets/training/deepseek-v4-rdma/sft-step-time.svg)

All six official runs were uploaded to self-hosted SwanLab. The desensitized screenshots below retain run names, train loss, gradient norm, learning rate, MoE load balancing loss, GPU memory, and cumulative training speed; internal access addresses, accounts, and cluster information are not included in the public document.

![Six rounds of DeepSeek V4 TCP/RDMA experiments in SwanLab](../../assets/training/deepseek-v4-rdma/swanlab-runs.png)

Loss dropped from approximately `1.506` to `0.190～0.198`, with the six trajectories close but not bit-identical. Distributed floating-point reduction order is nondeterministic, and this experiment did not perform full convergence or blind testing, so we only compare performance and do not present short-run loss as a model quality conclusion.

## 5. Why the Negative Control Showed No Benefit

In the previous dual-node experiment with `PP=2、EP=8、Dense DP=8`, each pipeline stage exactly filled one 8-GPU node. EP and DP groups did not span nodes; the cross-node traffic was mainly Activation and backward Gradient between the two pipeline stages.

In the stable segment under the same criteria:

| Transport | Stable Mean |
| --- | ---: |
| TCP | 4.109 s/Step |
| RDMA | 4.124 s/Step |
| Change | RDMA 0.35% slower, no measurable benefit |

This negative control is important. If one only publishes microbenchmarks or only selects the `EP=16` positive case, readers could easily conclude that any dual-node training can be 30% faster. In practice, one should first draw the ranks of each TP, PP, EP, and DP communication group, then check which edges cross nodes.

## 6. How to Design an RDMA Training Experiment That Does Not Fool Itself

Follow this order:

1. Use `nvidia-smi topo -m`, RDMA device information, and NCCL INFO to verify GPU, NIC, NUMA, and transport;
2. Test both AllReduce and All-to-All; do not use one collective to represent all training;
3. TCP/RDMA use the same nodes, GPUs, rank mapping, model, data hash, global batch, sequence length, and software versions;
4. Compare stable steps after warmup; do not compare total job duration that includes image pull, weight loading, compilation, and checkpoints;
5. Run at least three rounds; publish median, min, max, and any anomalous rounds;
6. Add a negative control where communication does not cross nodes, to verify the test can actually distinguish "fast link" from "fast business";
7. SwanLab records loss, steps, hyperparameters, and runs; Prometheus/Grafana separately records GPU, NIC, RDMA counters, and slow ranks.

SwanLab is an experiment tracking tool, not an RDMA network monitoring system. When step-time jitter is observed, use a unified run ID to align SwanLab's step time windows with GPU utilization, NIC throughput, ECN/PFC, RDMA retries, and NCCL logs in Grafana.

## 7. Public Reproduction Entry Point

The microbenchmark script in the repository already supports AllReduce and All-to-All:

```bash
NCCL_BENCH_COLLECTIVES=all_reduce,all_to_all \
NCCL_BENCH_SIZES_MB=1,16,64,256 \
NCCL_BENCH_WARMUP=5 \
NCCL_BENCH_ITERATIONS=20 \
bash run-nccl-benchmark.sh
```

Both machines run the same command, changing only `NODE_RANK`; the TCP/RDMA groups only switch NCCL transport and RDMA devices, with all other parameters unchanged. The public script does not contain any specific cluster, node address, internal image, network attachment, storage, or ingress configuration.

- [Distributed SFT and NCCL Harness](https://github.com/runzhliu/aik8s/tree/main/examples/llm-sft-lab/distributed)
- [Full machine-readable results for this run](https://github.com/runzhliu/aik8s/blob/main/examples/llm-sft-lab/meaningful-sft/results/h20-deepseek-v4-rdma-tcp-20260825.json)
- [Chart generation script](https://github.com/runzhliu/aik8s/blob/main/scripts/generate_deepseek_rdma_training_assets.py)

## 8. Conclusion Boundaries

This empirical test supports three conclusions:

- The RDMA link can indeed improve AllReduce and All-to-All bandwidth for large messages across 16 ranks by more than an order of magnitude;
- When `EP=16 / Dense DP=16` forces critical collectives to cross nodes, the stable training throughput of DeepSeek V4 Flash LoRA improves by approximately 47%;
- When EP/DP stays within a single node and cross-node communication is not dominant, enabling RDMA yields no measurable benefit.

It does not support "all training can be 47% faster." This round involved only 20 optimizer steps, a max length of 512, synthetic domain data, and LoRA rather than full-parameter training. Longer sequences, larger global batches, different token routing, FSDP/ZeRO, network congestion, and GPU models may all change the ratio. The correct approach is not to apply this percentage directly, but to reuse this positive/negative control setup and timing methodology.

References: [NVIDIA NCCL Tests](https://github.com/NVIDIA/nccl-tests), [Megatron Core Parallelism Strategy Guide](https://docs.nvidia.com/megatron-core/developer-guide/latest/user-guide/parallelism-guide.html), [SwanLab Experiment Tracking Documentation](https://docs.swanlab.cn/)
