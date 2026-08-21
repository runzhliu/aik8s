#!/usr/bin/env bash
set -euo pipefail

LAB_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
: "${RUN_ROOT:=${LAB_ROOT}/run}"
: "${TRAIN_MODEL_ID:=Qwen/Qwen3.5-4B}"
: "${EVAL_BATCH_SIZE:=8}"
: "${EVAL_LIMIT:=}"
: "${TRAIN_QUANT_BITS:=}"
: "${EVAL_SCRIPT:=${LAB_ROOT}/evaluate-swift.py}"
: "${TRAIN_ADD_NON_THINKING_PREFIX:=true}"
: "${TRAIN_LOSS_SCALE:=ignore_empty_think}"

DATA_DIR="${RUN_ROOT}/data"
RESULT_DIR="${RUN_ROOT}/results"
TRAIN_OUTPUT_DIR="${TRAIN_OUTPUT_DIR:-${RUN_ROOT}/output}"
mkdir -p "${DATA_DIR}" "${RESULT_DIR}" "${TRAIN_OUTPUT_DIR}"

python "${LAB_ROOT}/make-dataset.py" --output-dir "${DATA_DIR}"

LIMIT_ARGS=()
if [[ -n "${EVAL_LIMIT}" ]]; then
  LIMIT_ARGS=(--limit "${EVAL_LIMIT}")
fi

QUANT_ARGS=()
if [[ -n "${TRAIN_QUANT_BITS}" ]]; then
  QUANT_ARGS=(--quant-bits "${TRAIN_QUANT_BITS}")
fi

echo "Running Base evaluation"
python "${EVAL_SCRIPT}" \
  --model "${TRAIN_MODEL_ID}" \
  --test-file "${DATA_DIR}/test.jsonl" \
  --output "${RESULT_DIR}/base-predictions.jsonl" \
  --batch-size "${EVAL_BATCH_SIZE}" \
  "${QUANT_ARGS[@]}" \
  "${LIMIT_ARGS[@]}"

RUN_ROOT="${RUN_ROOT}" \
TRAIN_MODEL_ID="${TRAIN_MODEL_ID}" \
TRAIN_OUTPUT_DIR="${TRAIN_OUTPUT_DIR}" \
TRAIN_ADD_NON_THINKING_PREFIX="${TRAIN_ADD_NON_THINKING_PREFIX}" \
TRAIN_LOSS_SCALE="${TRAIN_LOSS_SCALE}" \
bash "${LAB_ROOT}/train.sh"

ADAPTER_PATH="$(python "${LAB_ROOT}/find-best-adapter.py" "${TRAIN_OUTPUT_DIR}")"
echo "Running Adapter evaluation from ${ADAPTER_PATH}"
python "${EVAL_SCRIPT}" \
  --model "${TRAIN_MODEL_ID}" \
  --adapter "${ADAPTER_PATH}" \
  --test-file "${DATA_DIR}/test.jsonl" \
  --output "${RESULT_DIR}/adapter-predictions.jsonl" \
  --batch-size "${EVAL_BATCH_SIZE}" \
  "${QUANT_ARGS[@]}" \
  "${LIMIT_ARGS[@]}"

python "${LAB_ROOT}/score.py" \
  --base "${RESULT_DIR}/base-predictions.jsonl" \
  --adapter "${RESULT_DIR}/adapter-predictions.jsonl" \
  --output "${RESULT_DIR}/comparison.json"

echo "A/B experiment finished. Report: ${RESULT_DIR}/comparison.json"
