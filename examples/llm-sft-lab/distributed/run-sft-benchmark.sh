#!/usr/bin/env bash
set -euo pipefail

LAB_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

: "${TRAIN_MODEL_ID:=Qwen/Qwen3-4B-Instruct-2507}"
: "${TRAIN_DATASET_PATH:=${LAB_ROOT}/data/benchmark.jsonl}"
: "${TRAIN_OUTPUT_DIR:=${LAB_ROOT}/output}"
: "${TRAIN_MAX_LENGTH:=1024}"
: "${TRAIN_MAX_STEPS:=20}"
: "${TRAIN_GLOBAL_BATCH:=8}"
: "${TRAIN_EXAMPLES:=512}"
: "${TRAIN_DATA_REPEATS:=12}"
: "${NNODES:=1}"
: "${NODE_RANK:=0}"
: "${NPROC_PER_NODE:=1}"
: "${MASTER_ADDR:=127.0.0.1}"
: "${MASTER_PORT:=29500}"
: "${NCCL_IB_DISABLE:=1}"
: "${NCCL_SOCKET_IFNAME:=eth0}"

WORLD_SIZE=$((NNODES * NPROC_PER_NODE))
if (( TRAIN_GLOBAL_BATCH % WORLD_SIZE != 0 )); then
  echo "TRAIN_GLOBAL_BATCH must be divisible by WORLD_SIZE" >&2
  exit 1
fi
GRADIENT_ACCUMULATION_STEPS=$((TRAIN_GLOBAL_BATCH / WORLD_SIZE))

export NNODES NODE_RANK NPROC_PER_NODE MASTER_ADDR MASTER_PORT
export NCCL_IB_DISABLE NCCL_SOCKET_IFNAME
export GLOO_SOCKET_IFNAME="${GLOO_SOCKET_IFNAME:-${NCCL_SOCKET_IFNAME}}"
export NCCL_DEBUG="${NCCL_DEBUG:-INFO}"
export NCCL_DEBUG_SUBSYS="${NCCL_DEBUG_SUBSYS:-INIT,NET,GRAPH}"
export PYTORCH_CUDA_ALLOC_CONF="${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True}"

if [[ ! -s "${TRAIN_DATASET_PATH}" ]]; then
  python "${LAB_ROOT}/make-benchmark-data.py" \
    --output "${TRAIN_DATASET_PATH}" \
    --examples "${TRAIN_EXAMPLES}" \
    --repeats "${TRAIN_DATA_REPEATS}"
fi

echo "SFT_BENCH_CONFIG world_size=${WORLD_SIZE} global_batch=${TRAIN_GLOBAL_BATCH} gradient_accumulation=${GRADIENT_ACCUMULATION_STEPS}"

swift sft \
  --model "${TRAIN_MODEL_ID}" \
  --dataset "${TRAIN_DATASET_PATH}" \
  --split_dataset_ratio 0 \
  --tuner_type lora \
  --torch_dtype bfloat16 \
  --target_modules all-linear \
  --lora_rank 8 \
  --lora_alpha 32 \
  --learning_rate 1e-4 \
  --lr_scheduler_type constant \
  --per_device_train_batch_size 1 \
  --gradient_accumulation_steps "${GRADIENT_ACCUMULATION_STEPS}" \
  --gradient_checkpointing true \
  --max_length "${TRAIN_MAX_LENGTH}" \
  --max_steps "${TRAIN_MAX_STEPS}" \
  --save_strategy no \
  --eval_strategy no \
  --logging_steps 1 \
  --warmup_ratio 0 \
  --dataset_shuffle false \
  --train_dataloader_shuffle false \
  --dataset_num_proc 1 \
  --dataloader_num_workers 2 \
  --report_to none \
  --output_dir "${TRAIN_OUTPUT_DIR}"

if [[ "${NODE_RANK}" == "0" ]]; then
  python "${LAB_ROOT}/summarize-sft.py" \
    "${TRAIN_OUTPUT_DIR}" \
    --world-size "${WORLD_SIZE}" \
    --global-batch "${TRAIN_GLOBAL_BATCH}"
fi
