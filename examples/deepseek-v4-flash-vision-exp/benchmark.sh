#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CASES_FILE="${CASES_FILE:-${SCRIPT_DIR}/cases.csv}"
ENGINE="${ENGINE:-sglang}"
EXECUTE="${EXECUTE:-0}"
BASE_URL="${BASE_URL:-http://127.0.0.1:30000}"
MODEL="${MODEL:-deepseek-v4-flash-vision-exp}"
TOKENIZER="${TOKENIZER:-/models-nvme/DeepSeek-V4-Flash-Vision-Exp/v1}"
DATA_ROOT="${DATA_ROOT:-/datasets/aik8s/deepseek-v4-vision}"
RESULT_ROOT="${RESULT_ROOT:-${SCRIPT_DIR}/results}"
CASE_FILTER="${CASE_FILTER:-}"
SEED="${SEED:-20260831}"

if [[ "${ENGINE}" != "sglang" && "${ENGINE}" != "vllm" ]]; then
  echo "ENGINE must be sglang or vllm" >&2
  exit 2
fi

run_benchmark() {
  local dataset_path="$1"
  local output_tokens="$2"
  local num_prompts="$3"
  local concurrency="$4"
  local result_dir="$5"
  local result_filename="$6"

  local -a command=(
    vllm bench serve
    --backend openai-chat
    --base-url "${BASE_URL}"
    --endpoint /v1/chat/completions
    --model "${MODEL}"
    --tokenizer "${TOKENIZER}"
    --dataset-name custom_image
    --dataset-path "${dataset_path}"
    --custom-output-len "${output_tokens}"
    --custom-ensure-client-side-data
    --enable-multimodal-chat
    --num-prompts "${num_prompts}"
    --max-concurrency "${concurrency}"
    --request-rate inf
    --ignore-eos
    --disable-shuffle
    --seed "${SEED}"
    --save-result
    --save-detailed
    --result-dir "${result_dir}"
    --result-filename "${result_filename}"
  )

  printf '%q ' "${command[@]}"
  printf '\n'
  if [[ "${EXECUTE}" == "1" ]]; then
    [[ -f "${dataset_path}" ]] || {
      echo "missing dataset: ${dataset_path}" >&2
      exit 1
    }
    mkdir -p "${result_dir}"
    "${command[@]}"
  fi
}

while IFS=, read -r case_id dataset_relpath output_tokens num_prompts concurrencies cache_mode description; do
  [[ "${case_id}" == "case_id" || -z "${case_id}" ]] && continue
  if [[ -n "${CASE_FILTER}" && "${case_id}" != "${CASE_FILTER}" ]]; then
    continue
  fi

  IFS=';' read -r -a concurrency_values <<< "${concurrencies}"
  dataset_base="${DATA_ROOT}/${dataset_relpath}"
  result_dir="${RESULT_ROOT}/${ENGINE}/${case_id}"

  echo "case=${case_id} engine=${ENGINE} cache=${cache_mode} description=${description}"
  run_benchmark \
    "${dataset_base}.warmup.jsonl" \
    "${output_tokens}" \
    "$((num_prompts < 16 ? num_prompts : 16))" \
    "1" \
    "${result_dir}" \
    "warmup.json"

  for concurrency in "${concurrency_values[@]}"; do
    for repeat in 1 2 3; do
      run_benchmark \
        "${dataset_base}.r${repeat}.jsonl" \
        "${output_tokens}" \
        "${num_prompts}" \
        "${concurrency}" \
        "${result_dir}" \
        "c${concurrency}-r${repeat}.json"
    done
  done
done < "${CASES_FILE}"

if [[ "${EXECUTE}" != "1" ]]; then
  echo "dry-run only; set EXECUTE=1 after reviewing the commands"
fi
