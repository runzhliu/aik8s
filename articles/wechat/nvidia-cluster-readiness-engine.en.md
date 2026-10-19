# NVIDIA NVCRE Explained, with Standalone NCCL/DCGM Tests

On October 12, 2026, NVIDIA included **NVIDIA Cluster Readiness Engine, or NVCRE**, among the open-source DSX AI Factory components in its Open Compute Project OCP Global Summit announcements. This recently public Kubernetes tool addresses GPU cluster readiness after onboarding and changes.

Public records already existed in September: GitHub stable release v0.1.0 appeared on September 1, and NVIDIA published its technical introduction on September 23. The project uses Apache 2.0. October 12 was the recent coordinated announcement, not necessarily its first open-source date.

The problem is practical: nodes report Ready and GPUs show no errors, yet distributed training can remain slow. A path using the wrong NIC or one node slowing under load can make the other GPUs wait. NVCRE actively runs communication, diagnostic, and training workloads on selected nodes and uses measurements to assess whether the resources can perform the intended work.

This article separates architecture analysis from standalone readiness measurements. **We did not deploy the NVCRE controller or execute its Certification workflow.** Results and device curves come from independent NCCL Tests and DCGM workloads on two eight-GPU H20-3e nodes, using ordinary Kubernetes Jobs. NVCRE analysis uses v0.7.0 source and dependencies.

## When NVCRE is useful in production

The most direct use is admitting new nodes. Successful device discovery establishes that the platform sees GPUs; intra-node communication, cross-node networking, and real training still require separate checks. Run readiness workloads in a reserved pool before opening business scheduling under site-specific criteria.

Another use is upgrade regression. After changing drivers, firmware, NCCL, or node images, repeat the same hardware, topology, message sizes, and parameters, comparing correctness and performance. This can identify changes before expanding rollout rather than after a long training job starts.

| Scenario | Production use of results |
| --- | --- |
| New node delivery | Verify diagnostics and single-/multi-node performance before admission |
| Software-stack upgrade | Compare before/after results; continue rollout, investigate, or roll back |
| Distributed training anomaly | Retest groups to narrow nodes or topology scope |
| Device repair | Repeat failed and related checks before returning to service |
| Training or storage change | Compare training steps, checkpoints, and restore costs |

![Readiness integration with node onboarding and changes](assets/nvcre/v1/production-lifecycle.png)

If intra-node communication is normal but cross-node bandwidth is abnormal, first examine NIC selection, cross-node configuration, and fabric links. NVCRE can split failing groups and retest to narrow suspects, reducing manual grouping. Suspects are not confirmed defective machines; correlate network and device evidence.

**It performs tests and reporting; the platform owns admission, isolation, and repair.** NVCRE does not ban or evict nodes or repair hardware. Existing operations workflows can consume results, or integrate with NVSentinel's online health governance. Routine monitoring continues, while active readiness runs use reserved nodes or maintenance windows because they consume GPUs and network capacity.

Measure operational value through anomalies found before admission, post-upgrade performance changes, retests required to localize faults, and GPU-hours spent. For synchronous training, identifying a node that slows the whole job matters more than pursuing one GPU's utilization alone.

## Standalone NCCL/DCGM tests: conditions on two machines

NCCL is NVIDIA's GPU collective communication library. DCGM is Data Center GPU Manager, offering management, monitoring, and diagnostics. Existing DCGM Exporter establishes some monitoring capability; complete diagnostics require their own dependency checks.

| Item | Conditions |
| --- | --- |
| GPU | 8 H20-3e per node, each reporting 143,771 MiB |
| Kubernetes / driver | 1.30.0 / 580.126.20 |
| Communication software | CUDA 12.9, NCCL 2.27.3, NCCL Tests v2.17.9 |
| Processes | One Rank per GPU; 8 Ranks on one node, 16 on two |
| Messages | 4 KiB–1 GiB, factor-of-4 increments, 10 sizes, Float |
| Iterations and repeats | 10 warmups, 50 timed iterations, validation enabled, three rounds per scenario |
| Diagnostics | DCGM 4.5.3, Level 1 and Level 2; repaired attempts used official CUDA 13 plugins |

Before testing, we checked GPU requests, driver errors, ECC, topology, and NIC state. GPU pairs reported NV18; eight RDMA devices had PIX proximity to adjacent GPUs. Ports reported Ethernet, ACTIVE, and 200 Gb/s, so the cross-node path is **RoCE, RDMA over Converged Ethernet**.

GPUs 0–3 and 4–7 were near different Non-Uniform Memory Access (NUMA) domains. MPI used `--bind-to none`; NCCL Algorithm and Protocol remained automatic.

The image contained both system NCCL 2.27.3 and PyTorch dependency 2.28.9. We fixed the library path and verified the loaded version through logs. Both machines used an identical hash-verified test binary.

## Single-node eight-GPU results were similar

Three-round medians at 1 GiB, in GB/s, using Out-of-place Bus Bandwidth:

| Collective | Node A | Node B (additional attempt) |
| --- | ---: | ---: |
| AllReduce | 465.56 | 465.73 |
| AllGather | 341.38 | 341.85 |
| AllToAll | 293.55 | 288.66 |

AllReduce took approximately 4.03–4.04 ms, AllGather 2.75 ms, and AllToAll 3.20–3.25 ms. Node A's three AllReduce rounds ranged from 465.02–466.02 GB/s; Node B ranged from 465.63–465.77 GB/s.

Bus Bandwidth is normalized by NCCL Tests for each collective; it is not instantaneous NIC or NVLink line rate. This column alone cannot rank different collectives. Logs showed NVLS topology initialization, so algorithm context also matters.

Node B's initial executor preparation failed, leaving nine single-node runs unsuccessful. A separate repaired attempt supplied the table's results, preserving the initial record. There were 30 successful communication rounds and 300 message-size measurements, with zero numerical errors.

## Cross-node RoCE: AllReduce does not represent every collective

Two nodes, 16 Ranks, 1 GiB, Bus Bandwidth in GB/s:

| Collective | R1 | R2 | R3 |
| --- | ---: | ---: | ---: |
| AllReduce | 363.76 | 427.58 | 452.28 |
| AllGather | 172.73 | 149.15 | 187.97 |
| AllToAll | 42.26 | 37.69 | 37.87 |

AllReduce's median was **427.58 GB/s**, taking approximately **4.71 ms**. AllGather was 172.73 GB/s and 5.83 ms; AllToAll was 37.87 GB/s and 26.58 ms.

The AllReduce high-to-low difference was around 21% of the median, greater variation than the single-node observations. These records cannot attribute it to switches, CPU placement, or competing workloads. Correlate port counters, NUMA, CPU behavior, and same-topology history.

Readiness coverage should reflect the collectives training actually uses. Expert-parallel workloads need an AllToAll baseline rather than an AllReduce score alone.

RoCE forced `NCCL_NET=IB`; logs showed `NET/IB/.../GDRDMA`. Here `IB` names NCCL's backend; the physical link remained Ethernet. The log confirms GPUDirect RDMA.

## With TCP, the test completes but waiting rises sharply

The same two-node, 16-Rank, 1 GiB AllReduce:

| Path | Median BusBW | Median duration |
| --- | ---: | ---: |
| RoCE | 427.58 GB/s | 4.71 ms |
| Socket/TCP | 2.25 GB/s | 894.75 ms |

![Two-node communication across message sizes; both axes use logarithmic scales](assets/nvcre/v1/roce-tcp-comparison.png)

RoCE used eight RDMA devices; TCP used the ordinary Pod's `eth0`. The approximately 190× difference describes complete deployed paths. Studying protocol overhead alone additionally requires aligned NICs, link limits, and routes.

All three TCP rounds completed with correct numerical results. Exit-code checks alone would miss the performance difference. Site admission must also verify transport and establish hardware/topology-specific baselines.

![GPU utilization during communication; anonymized Node A and Node B](assets/nvcre/v1/gpu-nccl-observation.png)

Both nodes' eight-GPU average utilization reached 100%, including during the low-bandwidth TCP stage. Utilization must be interpreted with useful communication progress.

![Highest GPU power per node during communication](assets/nvcre/v1/gpu-nccl-power.png)

Captured peak GPU power was approximately 255 W and 161 W; temperatures peaked around 46°C and 49°C, and memory around 6.48 GiB. Metrics were scraped every 5 seconds, while the Exporter refreshed devices every 30 seconds. Short peaks may fall between samples. Curves correlate device state; scores come from original NCCL output.

## DCGM: a monitoring image may lack diagnostic dependencies

Initial Level 1 and Level 2 attempts failed on both nodes. The error reported an inaccessible `plugins/cuda13` directory. The image contained DCGM 4.5.3 core, without matching CUDA diagnostic plugins.

We obtained matching CUDA 13 plugins from NVIDIA, checked package SHA-256, 15 unpacked files, and library dependencies, and mounted them only in experiment containers. Hosts and existing monitoring Pods retained their configuration; initial failures remained separate records.

After repair, Level 1 Software reported **8/8 GPU Pass** on both nodes, taking 3 and 5 seconds. Level 2 yielded no final diagnostic result. Both runs ended after a 720-second deadline and 10-second termination grace, with exit 137.

NVVS parents waited in epoll and children in futex; Hostengine reported a missing query library and HangDetect warnings. These establish an incomplete diagnostic chain, not a hardware defect. Root-cause analysis needs individual diagnostic subtests. Complete Level 2 conclusions remain unavailable.

| Node | Initial Level 1 and Level 2 | Repaired Level 1 | Repaired Level 2 |
| --- | --- | --- | --- |
| Node A | Missing plugins, failed | 8/8 Pass, 3 s | Timeout, 730 s |
| Node B | Missing plugins, failed | 8/8 Pass, 5 s | Timeout, 730 s |

Repaired attempts captured around 138 GiB on the highest GPU, then very low usage and declining temperature. Devices were active, but the later stage mainly waited. These curves do not substitute for final Level 2 results.

![Device activity during diagnostics; original Chinese screenshot labels retained](assets/nvcre/v1/gpu-dcgm-observation.png)

![Temperature during diagnostics; original screenshot retained](assets/nvcre/v1/gpu-dcgm-temperature.png)

![Diagnostic outcomes for initial and repaired attempts, distinguishing failed, passed, and timed-out states](assets/nvcre/v1/nccl-results-dashboard.png)

Distinguish missing dependencies, passed checks, and incomplete runs. Level 3, Level 4, and training Goodput were not executed, and no H20-3e site-admission performance threshold was established beforehand.

## How NVCRE organizes these checks

The main chain is **Certification → Workflow → NVCRE Job → Kubeflow TrainJob**.

![NVCRE execution and measurement: scope, grouping, execution, workloads, then log-derived measurements and reports](assets/nvcre/v1/execution-chain.png)

Certification defines node scope and criteria, Workflow groups iterations, Job tracks one execution, and Trainer v2 launches the workload. BandwidthMeasurement parses NCCL bandwidth; GoodputMeasurement calculates useful training time; LogProfile defines parsing. Including simplified WorkloadRun, v0.7.0 has seven CRDs.

WorkloadRun's `torch`, `mpi`, and `exec` entries all generate TrainJob. An older TFJob or PyTorchJob Operator does not supply Trainer v2 dependencies. NCCL/DCGM alone can use ordinary Jobs; full NVCRE requires checking its complete dependency chain.

Goodput considers how much training time becomes useful progress, including restore, checkpoint saves, and repeated lost work. Runtime Goodput currently excludes rescheduling time from its denominator. Capacity analysis needs separate queueing and total completion measurements.

## Production integration begins with versions, catalogs, and boundaries

| Concern | Review finding |
| --- | --- |
| Kubernetes | NVCRE 0.7.0 and Trainer 2.2.1 Chart state 1.29+; JobSet 0.11.0 lists 1.32–1.34 testing, so 1.30 requires full-stack validation |
| Hardware catalog | Defaults lack H20/L20; unknown models fall back to four GPUs and zero Mellanox NICs; configure actual hardware |
| Discovery labels | Uses `gpu.present` and `gpu.product`; allocatable GPUs do not establish complete labels |
| Network judgment | v0.7.0 records transport without using it for pass/fail; site rules must detect TCP fallback |
| Attribution | Separate threshold misses, workload failure, and node-health anomalies rather than automatically declaring hardware defects |

Start with intra-node and two-node baselines on reserved capacity, then checkpointed training regression. Explicitly configure GPU/NIC allocation, NUMA placement, concurrency, and total deadlines. Zero utilization does not establish zero allocation.

Verify actual DCGM plugins, versions, dependencies, and Hostengine reachability. The default Level 4 catalog includes long power/stress tests, privileged containers, and HostNetwork; it should not be copied into routine online checks.

Some NVCRE Gauges are cleared after measurement, so retain final reports and historical curves separately. Prometheus integration must check selectors, authentication, and TLS while preserving existing GPU, control-plane, and storage collection.

These standalone tests established a small communication comparison and exposed diagnostic-environment issues. The next step toward NVCRE integration is validating controller dependencies, then capturing actual hardware, transport, site thresholds, and archival in a repeatable catalog.

References:

- NVIDIA Cluster Readiness Engine: https://github.com/NVIDIA/cluster-readiness-engine
- v0.1.0 release (September 1): https://github.com/NVIDIA/cluster-readiness-engine/releases/tag/v0.1.0
- NVIDIA technical introduction (September 23): https://developer.nvidia.com/blog/validate-gpu-cluster-readiness-before-ai-workloads-land/
- OCP/DSX announcement (October 12): https://blogs.nvidia.com/blog/ocp-global-summit-vera-rubin-scale-ai-factories/
- NVCRE v0.7.0: https://github.com/NVIDIA/cluster-readiness-engine/tree/v0.7.0
- NCCL Tests v2.17.9: https://github.com/NVIDIA/nccl-tests/tree/v2.17.9
- DCGM Diagnostics: https://docs.nvidia.com/datacenter/dcgm/latest/user-guide/dcgm-diagnostics.html
- DCGM installation and CUDA packages: https://docs.nvidia.com/datacenter/dcgm/latest/user-guide/getting-started.html
- JobSet 0.11.0: https://github.com/kubernetes-sigs/jobset/tree/v0.11.0

Read the full article: https://aik8s.run/ai-k8s/practices/nvidia-cluster-readiness-engine/
