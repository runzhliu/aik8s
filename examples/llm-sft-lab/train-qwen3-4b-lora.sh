#!/usr/bin/env bash
set -euo pipefail

LAB_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
TRAIN_MODEL_ID="${TRAIN_MODEL_ID:-Qwen/Qwen3-4B-Instruct-2507}"
TRAIN_DATASET_PATH="${TRAIN_DATASET_PATH:-${LAB_ROOT}/data/train.jsonl}"
TRAIN_OUTPUT_DIR="${TRAIN_OUTPUT_DIR:-${LAB_ROOT}/output/qwen3-4b-lora}"
TRAIN_MAX_LENGTH="${TRAIN_MAX_LENGTH:-1024}"
TRAIN_MAX_STEPS="${TRAIN_MAX_STEPS:-20}"
TRAIN_TORCH_DTYPE="${TRAIN_TORCH_DTYPE:-bfloat16}"
TRAIN_GPU_ID="${TRAIN_GPU_ID:-0}"

if [[ ! -f "${TRAIN_DATASET_PATH}" ]]; then
  echo "Dataset not found: ${TRAIN_DATASET_PATH}" >&2
  exit 1
fi

CUDA_VISIBLE_DEVICES="${TRAIN_GPU_ID}" \
swift sft \
  --model "${TRAIN_MODEL_ID}" \
  --dataset "${TRAIN_DATASET_PATH}" \
  --split_dataset_ratio 0.2 \
  --tuner_type lora \
  --torch_dtype "${TRAIN_TORCH_DTYPE}" \
  --target_modules all-linear \
  --lora_rank 8 \
  --lora_alpha 32 \
  --learning_rate 1e-4 \
  --per_device_train_batch_size 1 \
  --per_device_eval_batch_size 1 \
  --gradient_accumulation_steps 8 \
  --gradient_checkpointing true \
  --max_length "${TRAIN_MAX_LENGTH}" \
  --max_steps "${TRAIN_MAX_STEPS}" \
  --eval_steps 5 \
  --save_steps 10 \
  --save_total_limit 2 \
  --logging_steps 1 \
  --warmup_ratio 0.05 \
  --dataset_num_proc 1 \
  --dataloader_num_workers 1 \
  --output_dir "${TRAIN_OUTPUT_DIR}"

echo "Training finished. Output: ${TRAIN_OUTPUT_DIR}"
