#!/usr/bin/env bash
set -euo pipefail

LAB_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
TRAIN_OUTPUT_DIR="${TRAIN_OUTPUT_DIR:-${LAB_ROOT}/output/qwen3-4b-lora}"

if [[ -n "${ADAPTER_PATH:-}" ]]; then
  SELECTED_ADAPTER="${ADAPTER_PATH}"
else
  SELECTED_ADAPTER="$(find "${TRAIN_OUTPUT_DIR}" -type d -name 'checkpoint-*' 2>/dev/null | sort -V | tail -1)"
fi

if [[ -z "${SELECTED_ADAPTER}" || ! -d "${SELECTED_ADAPTER}" ]]; then
  echo "No adapter checkpoint found under ${TRAIN_OUTPUT_DIR}" >&2
  exit 1
fi

echo "Loading adapter: ${SELECTED_ADAPTER}"
swift infer \
  --adapters "${SELECTED_ADAPTER}" \
  --infer_backend transformers \
  --temperature 0 \
  --max_new_tokens 256
