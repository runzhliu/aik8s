#!/usr/bin/env bash
set -euo pipefail

LAB_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

: "${NNODES:=1}"
: "${NODE_RANK:=0}"
: "${NPROC_PER_NODE:=2}"
: "${MASTER_ADDR:=127.0.0.1}"
: "${MASTER_PORT:=29500}"
: "${NCCL_IB_DISABLE:=1}"
: "${NCCL_SOCKET_IFNAME:=eth0}"
: "${NCCL_BENCH_SIZES_MB:=1,16,64,256}"
: "${NCCL_BENCH_COLLECTIVES:=all_reduce}"
: "${NCCL_BENCH_WARMUP:=5}"
: "${NCCL_BENCH_ITERATIONS:=20}"

export NCCL_IB_DISABLE NCCL_SOCKET_IFNAME
export NCCL_DEBUG="${NCCL_DEBUG:-INFO}"
export NCCL_DEBUG_SUBSYS="${NCCL_DEBUG_SUBSYS:-INIT,NET,GRAPH}"

torchrun \
  --nnodes "${NNODES}" \
  --node_rank "${NODE_RANK}" \
  --nproc_per_node "${NPROC_PER_NODE}" \
  --master_addr "${MASTER_ADDR}" \
  --master_port "${MASTER_PORT}" \
  "${LAB_ROOT}/torch-nccl-allreduce.py" \
  --sizes-mb "${NCCL_BENCH_SIZES_MB}" \
  --collectives "${NCCL_BENCH_COLLECTIVES}" \
  --warmup "${NCCL_BENCH_WARMUP}" \
  --iterations "${NCCL_BENCH_ITERATIONS}"
