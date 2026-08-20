#!/usr/bin/env bash
set -euo pipefail

LAB_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
V4_MODEL_PATH="${V4_MODEL_PATH:-deepseek-ai/DeepSeek-V4-Flash}"
V4_DATASET_PATH="${V4_DATASET_PATH:-${LAB_ROOT}/data/train.jsonl}"
V4_OUTPUT_DIR="${V4_OUTPUT_DIR:-${LAB_ROOT}/output/deepseek-v4-flash-lora}"
V4_MAX_LENGTH="${V4_MAX_LENGTH:-4096}"

if [[ ! -f "${V4_DATASET_PATH}" ]]; then
  echo "Dataset not found: ${V4_DATASET_PATH}" >&2
  exit 1
fi

PYTORCH_CUDA_ALLOC_CONF='expandable_segments:True' \
NPROC_PER_NODE=8 \
CUDA_VISIBLE_DEVICES=0,1,2,3,4,5,6,7 \
megatron sft \
  --model "${V4_MODEL_PATH}" \
  --save_safetensors true \
  --dataset "${V4_DATASET_PATH}" \
  --merge_lora false \
  --load_from_cache_file true \
  --add_non_thinking_prefix true \
  --loss_scale ignore_empty_think \
  --split_dataset_ratio 0.2 \
  --tuner_type lora \
  --lora_rank 16 \
  --lora_alpha 32 \
  --tensor_model_parallel_size 1 \
  --expert_model_parallel_size 8 \
  --micro_batch_size 1 \
  --global_batch_size 8 \
  --padding_free false \
  --group_by_length true \
  --recompute_granularity full \
  --recompute_method uniform \
  --recompute_num_layers 1 \
  --moe_permute_fusion true \
  --moe_grouped_gemm true \
  --moe_shared_expert_overlap true \
  --moe_aux_loss_coeff 1e-3 \
  --num_train_epochs 1 \
  --finetune true \
  --cross_entropy_loss_fusion true \
  --lr 1e-4 \
  --lr_warmup_fraction 0.05 \
  --min_lr 1e-5 \
  --output_dir "${V4_OUTPUT_DIR}" \
  --eval_steps 10 \
  --save_steps 10 \
  --max_length "${V4_MAX_LENGTH}" \
  --dataloader_num_workers 2 \
  --dataset_num_proc 2 \
  --no_save_optim true \
  --no_save_rng true \
  --sequence_parallel true \
  --mtp_num_layers 1 \
  --attention_backend flash
