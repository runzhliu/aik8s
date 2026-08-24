# 分布式 SFT 与 NCCL 基准

这组脚本把网络微基准和真实 SFT 分开，支持按同一套参数比较单机多卡、多机 TCP 和多机 RDMA。脚本不包含任何集群名、节点地址、内部镜像或网络附件配置。

## 推荐测试阶梯

| 阶段 | 拓扑 | 传输 | 目的 |
| --- | --- | --- | --- |
| A | 1 节点 × 1 GPU | 无跨卡通信 | 单卡训练基线 |
| B | 1 节点 × 2/4/8 GPU | NVLink 或 PCIe | 单机 DDP 扩展效率 |
| C | 2 节点 × N GPU | TCP Socket | 多机以太网基线 |
| D | 与 C 完全相同 | RDMA | 只改变网络 Transport 的 A/B |

先运行 `run-nccl-benchmark.sh`，再运行 `run-sft-benchmark.sh`。NCCL 测试能说明通信链路，SFT 才能说明网络差异是否成为当前模型与训练方法的实际瓶颈。

`AllReduce` 接近 DDP、FSDP 和 ZeRO 的梯度或参数同步，`All-to-All` 接近 MoE Expert Parallel 的 Token Dispatch/Combine。大型 Dense 全参数训练通常更关注前者，大型 MoE 训练需要两者都测：

```bash
NCCL_BENCH_COLLECTIVES=all_reduce,all_to_all \
NCCL_BENCH_SIZES_MB=1,16,64,256 \
bash run-nccl-benchmark.sh
```

## 单机示例

两张 GPU 的 NCCL AllReduce：

```bash
CUDA_VISIBLE_DEVICES=0,1 \
NPROC_PER_NODE=2 \
NCCL_IB_DISABLE=1 \
bash run-nccl-benchmark.sh
```

固定全局 Batch 为 8 的两卡 SFT：

```bash
CUDA_VISIBLE_DEVICES=0,1 \
NPROC_PER_NODE=2 \
TRAIN_GLOBAL_BATCH=8 \
TRAIN_MAX_STEPS=20 \
TRAIN_MODEL_ID=/models/Qwen3-4B-Instruct-2507 \
bash run-sft-benchmark.sh
```

## 多机示例

ms-swift 会把 `NNODES`、`NODE_RANK`、`MASTER_ADDR`、`MASTER_PORT` 和 `NPROC_PER_NODE` 透传给 `torchrun`。每台机器执行同一命令，只改变 `NODE_RANK`：

```bash
NNODES=2 \
NODE_RANK=0 \
NPROC_PER_NODE=2 \
MASTER_ADDR=trainer-0 \
MASTER_PORT=29500 \
NCCL_IB_DISABLE=1 \
NCCL_SOCKET_IFNAME=eth0 \
TRAIN_GLOBAL_BATCH=8 \
TRAIN_MAX_STEPS=20 \
TRAIN_MODEL_ID=/models/Qwen3-4B-Instruct-2507 \
bash run-sft-benchmark.sh
```

RDMA 对照组必须保持节点、GPU 数、模型、数据 Hash、Global Batch 和训练步数不变，只切换高速网卡、RDMA 设备与 NCCL Transport。不能只把 `NCCL_IB_DISABLE` 改成 `0` 就宣称 RDMA 生效；还要从 NCCL 日志确认 `NET/IB`、HCA、GID 和接口选择。

## 两种扩展口径

- 强扩展：固定 `TRAIN_GLOBAL_BATCH`，增加 GPU 后相应降低梯度累积，观察完成同一工作量能快多少；
- 弱扩展：固定每卡 Micro Batch 和梯度累积，让 Global Batch 随 GPU 数增加，观察吞吐是否近线性增长。

本脚本默认做强扩展：Micro Batch 为 1，Global Batch 为 8。扩展效率为：

```text
N 卡扩展效率 = N 卡 samples/s ÷（单卡 samples/s × N）
```

Qwen3-4B 的 Rank-8 LoRA 只有约 1650 万个可训练参数，梯度通信量远小于全参数训练。因此 TCP 与 RDMA 在这个 SFT 上差异不大是合理结果，不代表 RDMA 对继续预训练、全参数 SFT、FSDP/ZeRO 或大型 MoE 没有收益。

## 输出与验收

- `BENCH_DATASET`：数据条数、字符长度和 SHA-256；实际 Token 长度以 ms-swift 的 `train_dataset` 日志为准；
- `NCCL_ENV`：World Size、主机列表、NCCL 版本和 Transport 开关；
- `NCCL_BENCH`：不同消息大小的 Latency、算法带宽和总线带宽；
- `SFT_BENCH_RESULT`：Runtime、samples/s、steps/s、Loss 和框架显存统计；
- NCCL INFO 日志：TCP 组应出现 Socket，RDMA 组应出现 IB/RoCE HCA。

正式报告至少重复三轮，记录中位数和离散程度；剔除镜像拉取、模型加载、Tokenize 和 Checkpoint 时间，只比较训练区间。

## 已完成的双机 MoE 对照

2026 年 8 月 25 日使用相同方法完成 `2 节点 × 8 GPU` 的 DeepSeek V4 Flash 对照。`PP=1 / EP=16 / Dense DP=16` 使 All-to-All 与 Dense DP 同步跨节点，TCP/RDMA 各三轮的稳定 Step 均值中位数分别为 `4.490 / 3.050 秒`，RDMA 对应 `32.08%` 的步耗时下降与 `47.23%` 的等价吞吐提升。

相反，`PP=2 / EP=8` 把 EP 与 DP 通信组留在单节点内，TCP/RDMA 稳定 Step 只相差 `0.35%`，没有可测收益。这个负对照说明必须先检查通信组是否跨节点，再解释网络带宽。机器可读结果见 [`h20-deepseek-v4-rdma-tcp-20260825.json`](../meaningful-sft/results/h20-deepseek-v4-rdma-tcp-20260825.json)。

参考：[ms-swift 多机环境变量](https://github.com/modelscope/ms-swift/blob/main/docs/source/Instruction/Command-line-parameters.md)、[NVIDIA NCCL Tests](https://github.com/NVIDIA/nccl-tests)
