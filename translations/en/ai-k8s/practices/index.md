---
title: "Practical Experience, Troubleshooting, and Selection"
description: "Answering common AI/LLM on Kubernetes questions with reproducible experiments, performance numbers, incident evidence, and decision trees"
status: evolving
last_reviewed: 2026-09-26
---

# Practical Experience, Troubleshooting, and Selection

This series no longer explains "what it is" by component, but starts from a specific problem and provides evidence chains, experimental variables, acceptance criteria, and stopping conditions. The numbers on the page should be measured on target hardware and real workloads; example values cannot replace production baselines.

## Troubleshooting and Incidents

- [Why is a Pod still Pending when GPU is idle](gpu-pending.md)
- [Why is GPU utilization so low](low-gpu-utilization.md)
- [GPU Node Failure Atlas](gpu-failure-atlas.md)
- [Seemingly NCCL failure, actually Host Memory OOM](nccl-unhandled-cuda-error-host-memory-oom.md)
- [AI Cluster Incident Retrospective Methods](incident-review.md)
- [Stability Building for Hundreds of Kubernetes Clusters](kubernetes-fleet-reliability.md)
- [Practical Optimization of a 10,000-Node Kubernetes Cluster: Control Plane, etcd, Scheduling, and Networking](large-scale-kubernetes-optimization.md)
- [Kube-apiserver Load Balancing in Practice: HTTP/2, TLS Termination, and Layer 4/Layer 7 Selection](kube-apiserver-load-balancing.md)
- [Contiv, OVS, and Cilium Chained Networking in Practice: Why kube-proxy Might Not Receive Packets](contiv-ovs-cilium-network.md)
- [Koordinator Webhook Multi-Replica Certificate Race in Practice: From 60 409s per Second to Shared CA Convergence](koordinator-webhook-multireplica-cert-race.md)
- [APF Isolation in Practice: Why Zero-Seat Reject Still Allows Requests](apf-isolation-case.md)

## Performance, Cost, and Capacity

- [DeepSeek-V4.1-Flash-1017 Day0: vLLM on Eight H20 GPUs and Million-Token Tests](deepseek-v41-flash-1017-day0.md)
- [vLLM Sleep Single-GPU Dual-Model Test: Recovery Time, GPU Memory, and DRA Design](vllm-sleep-model-switch-l20.md)
- [MiMo-V2.6-Pro-RL First Test: vLLM Deployment and Performance on Eight H20-3e GPUs](mimo-v26-pro-rl-h20-first-test.md)
- [Qwen-Image-2.1: SGLang and vLLM-Omni Test on a Single L20 GPU](qwen-image21-l20-benchmark.md)
- [Qwen3.8-2.4T-A95B-FP8 Day 0: SGLang Deployment and Stress Test on 32×H20-3e](qwen38-a95b-h20-day0.md)
- [MiniMax-M3: SGLang and vLLM Test on Eight H20 GPUs](minimax-m3-h20-benchmark.md)
- [MiniMax H3 H20-3e Test: Full Audio/Video Generation, Dual Engine, and Persistence Acceptance](minimax-h3-h20-benchmark.md)
- [DeepSeek-V4-Flash-Vision-Exp Day 0: Multimodal Deployment and Stress Test on 4×H20](deepseek-v4-flash-vision-exp-day0-h20.md)
- [GLM-5.3 First-Day Test: SGLang and vLLM Baseline Stress Test on 8×H20](glm53-h20-sglang-vllm-test-plan.md)
- [Hy4-preview BF16 Dual-Node H20 Test: How to Choose Between SGLang and vLLM](hy4-preview-hardware-benchmark-plan.md)
- [Ling-3.0-flash BF16 Single-Node 4×H20 Test: How to Choose Between SGLang, vLLM, and MTP](ling3-flash-h20-deployment-benchmark-plan.md)
- [Qwen3.8-Flash-Next Day 0 Practice: Running Native 262K on 4×H20](qwen38-flash-next-sglang-day0.md)
- [SGLang v0.5.16 / v0.5.17 / v0.5.18 Single L20 Test: Is the Upgrade Really Faster?](sglang-0518-release-analysis.md)
- [DeepSeek V4 Flash Distributed KV Cache: From P/D Direct Transfer to Global Cache Pool](distributed-kv-cache-deepseek-v4.md)
- [From Half an Hour to Five Minutes: Full-Chain Optimization of Large Model Cold Start](llm-cold-start-optimization.md)
- [Large Model Weight Distribution and Loading Acceleration: Community and Commercial Solution Selection](model-weight-delivery-acceleration.md)
- [vLLM, SGLang, and TensorRT-LLM Test on the Same Machine](inference-engine-benchmark.md)
- [Model GPU Memory and Concurrency Capacity Calculator](model-memory-calculator.md)
- [Performance Inflection Point of Prefill/Decode Separation](pd-break-even.md)
- [GPU Cloud Resource Selection at Home and Abroad](cloud-gpu-selection.md)

## Platform and Scheduling

- [NVIDIA NVCRE: GPU Cluster Readiness and Production Integration](nvidia-cluster-readiness-engine.md)
- [Large-Scale Kubernetes Monitoring Solutions: Prometheus, VictoriaMetrics, Thanos, and Mimir](large-scale-kubernetes-monitoring-tsdb.md)
- [Large-Scale Kubernetes Scheduler Optimization: Queues, Plugins, Search, and Parallel Architecture](large-scale-kubernetes-scheduler-optimization.md)
- [OpenTelemetry × Grafana: Observing Kubernetes Control Plane and Cluster State](opentelemetry-kubernetes-components-grafana.md)
- [Pitfalls of GPU Development Platforms in the Large Model Era](gpu-notebook-platform-evolution.md)
- [For a 4-GPU Task on an 8-GPU Node, How to Avoid Getting Fragmented GPUs Across NUMA](gpu-topology-fragmentation-scheduling.md)
- [GPU Resource Bank and Tidal Inference Platform Practice Blueprint](gpu-resource-bank-tidal-platform.md)
- [Kueue vs. Volcano Comparative Experiment](kueue-vs-volcano.md)
- [Volcano Has Many Features, Why Is It Still Hard to Tune in Enterprises?](volcano-scheduler-enterprise-limits.md)
- [Kubernetes or Slurm](kubernetes-vs-slurm.md)
- [Running Kubernetes on KubeVirt: Architecture Boundaries, Production Design, and AI Scenario Trade-offs](../cluster/kubevirt-guest-kubernetes.md)
- [KubeVirt Single-Node Desktop Practice: Local Disks, CDI, and Browser noVNC](kubevirt-local-desktop-lab.md)
- [Building a Persistent GPU Notebook with KubeVirt and Ceph RBD](kubevirt-rbd-notebook.md)
- [Spot GPU and Checkpoint Recovery Experiment](spot-checkpoint.md)
- [Kubernetes Practice with Domestic GPU/NPU](domestic-accelerators.md)

## End-to-End Delivery

- [Large Model SFT Introduction: Explaining Loss, LoRA, Batch, and Parallelism in One Go](../training/sft-concepts.md)
- [Large Model SFT Training Practice: From Single-GPU LoRA to DeepSeek V4](../training/sft-from-single-gpu-to-deepseek-v4.md)
- [How Much Faster Can RDMA Make Distributed Training: DeepSeek V4 Dual-Node 16-GPU Test](../training/rdma-distributed-training-benchmark.md)
- [SwanLab Self-Hosting: From Kubernetes Deployment to Real SFT Metrics](../training/swanlab-self-hosted.md)
- [From W&B Local to SwanLab: Two-Year Team Experiment Tracking Practice and Selection](../training/wandb-vs-swanlab.md)
- [Deploying MiniMax-Music3 with SGLang-Omni: From a Creative Idea to a Complete Song](minimax-music3-sglang-omni.md)
- [Qwen3.8-27B Day 0: vLLM and SGLang Test Records](qwen38-27b-day0.md)
- [From Docker to Kubernetes: DeepSeek Harness, Built-in Chromium, and DSH Plugin Practice](deepseek-harness-kubernetes.md)
- [GLM-5.2 FP8 on 8×H20 141GB: AIBrix + vLLM Test](glm52-fp8-h20-aibrix-vllm.md)
- [DeepSeek-V4-Flash-0731 H20 Deployment and Stress Test](deepseek-v4-flash-h20-evaluation.md)
- [Implementing AIBrix on an Existing Kubernetes Cluster](aibrix-existing-cluster.md)
- [AIBrix for Production: DS V4 Flash Stress Test, Dashboard, and Recovery Practice](aibrix-dsv4-observability.md)
- [AIBrix Production Practice: Capacity, Exit, and Overload Protection for Qwen3.8-27B on L20](aibrix-qwen-l20-production.md)
- [What Does AIBrix Routing Optimize: From Cache Hits to Tail Latency](aibrix-routing-cache-tradeoffs.md)
- [AIBrix Real GPU Test: From Two-Node Inference to Eight-Node Fragmented GPUs](aibrix-gpu-multinode-pd-production.md)
- [Deploying ComfyUI on Kubernetes: Offline Images, CephFS Models, and Cross-Cluster Ingress](comfyui-minimax-h3-gpu.md)
- [RBG Multi-Role Inference Orchestration and sr1 Practice](rbg-existing-cluster.md)
- [RBG with Traffic Practice: When Replicas Recover, Do Requests Recover?](rbg-qwen-l20-serving-resilience.md)
- [SGLang Model Gateway CPU Practice: Dynamic Discovery, Routing, and Fault Removal](sglang-model-gateway-cpu-lab.md)
- [From Ollama to Kubernetes Production Inference](ollama-to-production.md)
- [Distributing a 70B Model to a Hundred Nodes](model-distribution-100-nodes.md)
- [Deploying AI/LLM Platform in Offline Environment](air-gapped-ai-platform.md)
- [Agent Sandbox Attack and Defense Experiment](agent-sandbox-red-team.md)

## Reading and Reproduction Conventions

Each experiment records at least the following:

1. Kubernetes, driver, CUDA/ROCm/CANN, and component versions;
2. GPU/NPU/TPU, CPU, memory, disk, and network topology;
3. Model, precision, input/output length, and concurrency distribution;
4. Cold cache/hot cache, failure retries, and warm-up status;
5. Raw logs, events, metrics, traces, and timestamps;
6. Success criteria, failure criteria, and the scope of inapplicability of results.

When reproducing experiments, first modify Namespace, images, StorageClass, resource names, and security policies. Do not directly copy permissions, image tags, or cloud provider parameters from the examples into production.
