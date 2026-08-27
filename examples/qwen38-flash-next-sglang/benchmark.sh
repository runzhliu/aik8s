#!/usr/bin/env bash
set -euo pipefail

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-30000}"
MODEL="${MODEL:-qwen38-flash-next}"
TOKENIZER="${TOKENIZER:-/models/Qwen3.8-Flash-Next-FP8}"
RESULTS_DIR="${RESULTS_DIR:-results}"
FULL="${FULL:-0}"

mkdir -p "${RESULTS_DIR}"

run_case() {
  local concurrency="$1"
  local input_len="$2"
  local output_len="$3"
  local prompts="$4"
  local output="${RESULTS_DIR}/c${concurrency}-i${input_len}-o${output_len}.jsonl"

  python3 -m sglang.benchmark.serving \
    --backend sglang \
    --host "${HOST}" \
    --port "${PORT}" \
    --model "${MODEL}" \
    --tokenizer "${TOKENIZER}" \
    --dataset-name random-ids \
    --tokenize-prompt \
    --random-input-len "${input_len}" \
    --random-output-len "${output_len}" \
    --random-range-ratio 1 \
    --num-prompts "${prompts}" \
    --max-concurrency "${concurrency}" \
    --request-rate inf \
    --warmup-requests "${concurrency}" \
    --flush-cache \
    --temperature 0 \
    --disable-tqdm \
    --output-details \
    --output-file "${output}"
}

run_case 1 128 64 16
run_case 4 128 64 32
run_case 8 128 64 64
run_case 4 4096 128 16

if [[ "${FULL}" == "1" ]]; then
  # Long-output decode throughput.
  run_case 1 128 1024 4
  run_case 8 128 1024 16

  # Native 262K context boundary. Keep concurrency at one to isolate Prefill.
  run_case 1 32768 128 4
  run_case 1 65536 128 4
  run_case 1 131072 128 2
  run_case 1 261120 128 1

  # Shared-prefix workload: 4 groups × 8 requests, each group sharing a
  # 4K-token system prompt. Compare it with a random 4,224-token baseline.
  run_case 8 4224 64 32
  python3 -m sglang.benchmark.serving \
    --backend sglang \
    --host "${HOST}" \
    --port "${PORT}" \
    --model "${MODEL}" \
    --tokenizer "${TOKENIZER}" \
    --dataset-name generated-shared-prefix \
    --gsp-num-groups 4 \
    --gsp-prompts-per-group 8 \
    --gsp-system-prompt-len 4096 \
    --gsp-question-len 128 \
    --gsp-output-len 64 \
    --gsp-range-ratio 1 \
    --gsp-ordered \
    --max-concurrency 8 \
    --request-rate inf \
    --flush-cache \
    --temperature 0 \
    --disable-tqdm \
    --cache-report \
    --output-details \
    --output-file "${RESULTS_DIR}/c8-gsp4096-q128-o64.jsonl"
fi
