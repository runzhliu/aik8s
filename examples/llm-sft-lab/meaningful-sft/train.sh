#!/usr/bin/env bash
set -euo pipefail

LAB_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
: "${RUN_ROOT:=${LAB_ROOT}/run}"
: "${TRAIN_MODEL_ID:=Qwen/Qwen3.5-4B}"
: "${TRAIN_OUTPUT_DIR:=${RUN_ROOT}/output}"
: "${TRAIN_MAX_LENGTH:=512}"
: "${TRAIN_MAX_STEPS:=120}"
: "${TRAIN_TORCH_DTYPE:=bfloat16}"
: "${TRAIN_GPU_ID:=0}"
: "${TRAIN_CUDA_VISIBLE_DEVICES:=${TRAIN_GPU_ID}}"
: "${TRAIN_NPROC_PER_NODE:=1}"
: "${TRAIN_GRADIENT_ACCUMULATION_STEPS:=8}"
: "${TRAIN_DEEPSPEED:=}"
: "${TRAIN_DEVICE_MAP:=}"
: "${TRAIN_SAVE_ONLY_MODEL:=false}"
: "${TRAIN_LOAD_BEST_MODEL_AT_END:=true}"
: "${TRAIN_TARGET_MODULES:=all-linear}"
: "${TRAIN_TARGET_PARAMETERS:=}"
: "${TRAIN_LORA_DROPOUT:=0.05}"
: "${TRAIN_EVAL_STEPS:=30}"
: "${TRAIN_SAVE_STEPS:=${TRAIN_EVAL_STEPS}}"
: "${TRAIN_QUANT_METHOD:=}"
: "${TRAIN_QUANT_BITS:=}"
: "${TRAIN_BNB_4BIT_COMPUTE_DTYPE:=bfloat16}"
: "${TRAIN_BNB_4BIT_QUANT_TYPE:=nf4}"
: "${TRAIN_BNB_4BIT_USE_DOUBLE_QUANT:=true}"
: "${TRAIN_EXPERTS_IMPL:=}"
: "${TRAIN_ROUTER_AUX_LOSS_COEF:=}"
: "${TRAIN_REPORT_TO:=none}"
: "${TRAIN_SWANLAB_PROJECT:=llm-sft-lab}"
: "${TRAIN_SWANLAB_EXP_NAME:=meaningful-sft}"
: "${TRAIN_ADD_NON_THINKING_PREFIX:=}"
: "${TRAIN_LOSS_SCALE:=}"

TRAIN_FILE="${RUN_ROOT}/data/train.jsonl"
VALIDATION_FILE="${RUN_ROOT}/data/validation.jsonl"
if [[ ! -s "${TRAIN_FILE}" || ! -s "${VALIDATION_FILE}" ]]; then
  echo "Training or validation dataset is missing under ${RUN_ROOT}/data" >&2
  exit 1
fi

read -r -a TARGET_MODULES <<<"${TRAIN_TARGET_MODULES}"

TARGET_PARAMETER_ARGS=()
if [[ -n "${TRAIN_TARGET_PARAMETERS}" ]]; then
  read -r -a TARGET_PARAMETERS <<<"${TRAIN_TARGET_PARAMETERS}"
  TARGET_PARAMETER_ARGS=(--target_parameters "${TARGET_PARAMETERS[@]}")
fi

QUANT_ARGS=()
if [[ -n "${TRAIN_QUANT_BITS}" ]]; then
  if [[ -z "${TRAIN_QUANT_METHOD}" ]]; then
    echo "TRAIN_QUANT_METHOD is required when TRAIN_QUANT_BITS is set" >&2
    exit 1
  fi
  QUANT_ARGS=(
    --quant_method "${TRAIN_QUANT_METHOD}"
    --quant_bits "${TRAIN_QUANT_BITS}"
  )
  if [[ "${TRAIN_QUANT_METHOD}" == "bnb" && "${TRAIN_QUANT_BITS}" == "4" ]]; then
    QUANT_ARGS+=(
      --bnb_4bit_compute_dtype "${TRAIN_BNB_4BIT_COMPUTE_DTYPE}"
      --bnb_4bit_quant_type "${TRAIN_BNB_4BIT_QUANT_TYPE}"
      --bnb_4bit_use_double_quant "${TRAIN_BNB_4BIT_USE_DOUBLE_QUANT}"
    )
  fi
fi

MOE_ARGS=()
if [[ -n "${TRAIN_EXPERTS_IMPL}" ]]; then
  MOE_ARGS+=(--experts_impl "${TRAIN_EXPERTS_IMPL}")
fi
if [[ -n "${TRAIN_ROUTER_AUX_LOSS_COEF}" ]]; then
  MOE_ARGS+=(--router_aux_loss_coef "${TRAIN_ROUTER_AUX_LOSS_COEF}")
fi

DISTRIBUTED_ARGS=()
if [[ -n "${TRAIN_DEEPSPEED}" ]]; then
  DISTRIBUTED_ARGS+=(--deepspeed "${TRAIN_DEEPSPEED}")
fi

REPORT_ARGS=(--report_to "${TRAIN_REPORT_TO}")
if [[ "${TRAIN_REPORT_TO}" == *swanlab* ]]; then
  REPORT_ARGS+=(
    --swanlab_project "${TRAIN_SWANLAB_PROJECT}"
    --swanlab_exp_name "${TRAIN_SWANLAB_EXP_NAME}"
  )
fi

TEMPLATE_ARGS=()
if [[ -n "${TRAIN_ADD_NON_THINKING_PREFIX}" ]]; then
  TEMPLATE_ARGS+=(--add_non_thinking_prefix "${TRAIN_ADD_NON_THINKING_PREFIX}")
fi
if [[ -n "${TRAIN_LOSS_SCALE}" ]]; then
  TEMPLATE_ARGS+=(--loss_scale "${TRAIN_LOSS_SCALE}")
fi
if [[ -n "${TRAIN_DEVICE_MAP}" ]]; then
  DISTRIBUTED_ARGS+=(--device_map "${TRAIN_DEVICE_MAP}")
fi

SWIFT_SFT=(swift sft)
if [[ -n "${TRAIN_DEVICE_MAP}" && "${TRAIN_NPROC_PER_NODE}" == "1" ]]; then
  # `swift sft` uses torchrun whenever NPROC_PER_NODE is set, including one
  # process. Accelerate rejects a device-mapped model in that pseudo-
  # distributed mode, so use the underlying Python entry point directly.
  SWIFT_SFT=(python -m swift.cli.sft)
fi

CUDA_VISIBLE_DEVICES="${TRAIN_CUDA_VISIBLE_DEVICES}" \
NPROC_PER_NODE="${TRAIN_NPROC_PER_NODE}" \
"${SWIFT_SFT[@]}" \
  --model "${TRAIN_MODEL_ID}" \
  --dataset "${TRAIN_FILE}" \
  --val_dataset "${VALIDATION_FILE}" \
  --split_dataset_ratio 0 \
  --tuner_type lora \
  --torch_dtype "${TRAIN_TORCH_DTYPE}" \
  --target_modules "${TARGET_MODULES[@]}" \
  --lora_rank 8 \
  --lora_alpha 32 \
  --lora_dropout "${TRAIN_LORA_DROPOUT}" \
  --learning_rate 1e-4 \
  --lr_scheduler_type cosine \
  --per_device_train_batch_size 1 \
  --per_device_eval_batch_size 1 \
  --gradient_accumulation_steps "${TRAIN_GRADIENT_ACCUMULATION_STEPS}" \
  --gradient_checkpointing true \
  --max_length "${TRAIN_MAX_LENGTH}" \
  --max_steps "${TRAIN_MAX_STEPS}" \
  --eval_strategy steps \
  --eval_steps "${TRAIN_EVAL_STEPS}" \
  --save_strategy steps \
  --save_steps "${TRAIN_SAVE_STEPS}" \
  --save_total_limit 2 \
  --save_only_model "${TRAIN_SAVE_ONLY_MODEL}" \
  --load_best_model_at_end "${TRAIN_LOAD_BEST_MODEL_AT_END}" \
  --metric_for_best_model eval_loss \
  --greater_is_better false \
  --logging_steps 5 \
  --warmup_ratio 0.05 \
  --dataset_shuffle true \
  --train_dataloader_shuffle true \
  --dataset_num_proc 1 \
  --dataloader_num_workers 2 \
  --seed 42 \
  --output_dir "${TRAIN_OUTPUT_DIR}" \
  "${REPORT_ARGS[@]}" \
  "${TEMPLATE_ARGS[@]}" \
  "${TARGET_PARAMETER_ARGS[@]}" \
  "${QUANT_ARGS[@]}" \
  "${MOE_ARGS[@]}" \
  "${DISTRIBUTED_ARGS[@]}"

echo "Training finished. Output: ${TRAIN_OUTPUT_DIR}"
