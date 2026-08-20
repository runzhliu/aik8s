#!/usr/bin/env bash
set -euo pipefail

LAB_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
: "${RUN_ROOT:=${LAB_ROOT}/run}"
: "${TRAIN_MODEL_ID:=Qwen/Qwen3-4B-Instruct-2507}"
: "${TRAIN_OUTPUT_DIR:=${RUN_ROOT}/output}"
: "${TRAIN_MAX_LENGTH:=512}"
: "${TRAIN_MAX_STEPS:=120}"
: "${TRAIN_TORCH_DTYPE:=bfloat16}"
: "${TRAIN_GPU_ID:=0}"

TRAIN_FILE="${RUN_ROOT}/data/train.jsonl"
VALIDATION_FILE="${RUN_ROOT}/data/validation.jsonl"
if [[ ! -s "${TRAIN_FILE}" || ! -s "${VALIDATION_FILE}" ]]; then
  echo "Training or validation dataset is missing under ${RUN_ROOT}/data" >&2
  exit 1
fi

CUDA_VISIBLE_DEVICES="${TRAIN_GPU_ID}" \
swift sft \
  --model "${TRAIN_MODEL_ID}" \
  --dataset "${TRAIN_FILE}" \
  --val_dataset "${VALIDATION_FILE}" \
  --split_dataset_ratio 0 \
  --tuner_type lora \
  --torch_dtype "${TRAIN_TORCH_DTYPE}" \
  --target_modules all-linear \
  --lora_rank 8 \
  --lora_alpha 32 \
  --lora_dropout 0.05 \
  --learning_rate 1e-4 \
  --lr_scheduler_type cosine \
  --per_device_train_batch_size 1 \
  --per_device_eval_batch_size 1 \
  --gradient_accumulation_steps 8 \
  --gradient_checkpointing true \
  --max_length "${TRAIN_MAX_LENGTH}" \
  --max_steps "${TRAIN_MAX_STEPS}" \
  --eval_strategy steps \
  --eval_steps 30 \
  --save_strategy steps \
  --save_steps 30 \
  --save_total_limit 2 \
  --load_best_model_at_end true \
  --metric_for_best_model eval_loss \
  --greater_is_better false \
  --logging_steps 5 \
  --warmup_ratio 0.05 \
  --dataset_shuffle true \
  --train_dataloader_shuffle true \
  --dataset_num_proc 1 \
  --dataloader_num_workers 2 \
  --report_to none \
  --seed 42 \
  --output_dir "${TRAIN_OUTPUT_DIR}"

echo "Training finished. Output: ${TRAIN_OUTPUT_DIR}"
