#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CASES_FILE="${CASES_FILE:-${SCRIPT_DIR}/cases.csv}"
BASE_URL="${BASE_URL:-http://127.0.0.1:30000}"
MODEL="${MODEL:-glm53-flash}"
TOKENIZER="${TOKENIZER:-/models/GLM-5.3-Flash}"
ENGINE="${ENGINE:-sglang}"
STAGE="${STAGE:-smoke}"
RESULTS_DIR="${RESULTS_DIR:-${SCRIPT_DIR}/results}"
EXECUTE="${EXECUTE:-0}"
FLUSH_CACHE="${FLUSH_CACHE:-1}"
MAX_CONTEXT="${MAX_CONTEXT:-1048576}"

die() {
  echo "error: $*" >&2
  exit 1
}

case "${ENGINE}" in
  sglang) FLUSH_PATH="${FLUSH_PATH:-/flush_cache}" ;;
  vllm) FLUSH_PATH="${FLUSH_PATH:-/reset_prefix_cache}" ;;
  *) die "ENGINE must be sglang or vllm" ;;
esac

case "${STAGE}" in
  smoke|baseline|decode|long|boundary|extreme|all) ;;
  *) die "STAGE must be smoke baseline decode long boundary extreme or all" ;;
esac

[ -f "${CASES_FILE}" ] || die "cases file not found: ${CASES_FILE}"
case "${MAX_CONTEXT}" in
  ''|*[!0-9]*) die "MAX_CONTEXT must be an integer" ;;
esac

print_command() {
  printf '  '
  printf '%q ' "$@"
  printf '\n'
}

flush_cache() {
  [ "${FLUSH_CACHE}" = "1" ] || return 0
  curl -fsS -X POST "${BASE_URL}${FLUSH_PATH}" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer EMPTY" \
    -d '{}' >/dev/null
}

if [ "${EXECUTE}" = "1" ]; then
  if [ "${ENGINE}" = "sglang" ]; then
    python3 -c 'import sglang.benchmark.serving' >/dev/null 2>&1 || \
      die "the SGLang benchmark client is required for ENGINE=sglang"
  else
    command -v vllm >/dev/null 2>&1 || \
      die "vllm CLI is required for ENGINE=vllm"
  fi
  command -v curl >/dev/null 2>&1 || die "curl is required"
  mkdir -p "${RESULTS_DIR}"
  curl -fsS "${BASE_URL}/v1/models" > "${RESULTS_DIR}/${ENGINE}-models.json"
  curl -fsS "${BASE_URL}/version" > "${RESULTS_DIR}/${ENGINE}-version.json" || true
fi

selected=0
skipped=0
executed=0

{
  IFS= read -r _header
  while IFS=, read -r case_id case_stage input_tokens output_tokens concurrency num_prompts repeats description; do
    [ -n "${case_id}" ] || continue
    if [ "${STAGE}" != "all" ] && [ "${case_stage}" != "${STAGE}" ]; then
      continue
    fi
    selected=$((selected + 1))
    required_context=$((input_tokens + output_tokens))
    if [ "${required_context}" -gt "${MAX_CONTEXT}" ]; then
      echo "SKIP_UNSUPPORTED case=${case_id} required=${required_context} max=${MAX_CONTEXT}"
      skipped=$((skipped + 1))
      continue
    fi

    repeat=1
    while [ "${repeat}" -le "${repeats}" ]; do
      filename="${ENGINE}__${case_id}__r${repeat}.json"
      if [ "${ENGINE}" = "sglang" ]; then
        filename="${filename%.json}.jsonl"
        command=(
          python3 -m sglang.benchmark.serving
          --backend sglang
          --base-url "${BASE_URL}"
          --model "${TOKENIZER}"
          --served-model-name "${MODEL}"
          --tokenizer "${TOKENIZER}"
          --dataset-name random-ids
          --random-input-len "${input_tokens}"
          --random-output-len "${output_tokens}"
          --random-range-ratio 1
          --num-prompts "${num_prompts}"
          --max-concurrency "${concurrency}"
          --request-rate inf
          --temperature 0
          --warmup-requests "${concurrency}"
          --seed "$((20260827 + repeat))"
          --disable-tqdm
          --tokenize-prompt
          --output-details
          --output-file "${RESULTS_DIR}/${filename}"
        )
      else
        command=(
          vllm bench serve
          --backend openai
          --base-url "${BASE_URL}"
          --endpoint /v1/completions
          --model "${MODEL}"
          --served-model-name "${MODEL}"
          --tokenizer "${TOKENIZER}"
          --dataset-name random
          --random-input-len "${input_tokens}"
          --random-output-len "${output_tokens}"
          --random-range-ratio 0
          --num-prompts "${num_prompts}"
          --max-concurrency "${concurrency}"
          --request-rate inf
          --temperature 0
          --ignore-eos
          --num-warmups "${concurrency}"
          --seed "$((20260827 + repeat))"
          --disable-tqdm
          --save-result
          --save-detailed
          --percentile-metrics ttft,tpot,itl,e2el
          --metric-percentiles 50,95,99
          --result-dir "${RESULTS_DIR}"
          --result-filename "${filename}"
          --request-id-prefix "glm53-${ENGINE}-${case_id}-r${repeat}-"
          --metadata
          "engine=${ENGINE}"
          "case_id=${case_id}"
          "stage=${case_stage}"
          "input_tokens=${input_tokens}"
          "output_tokens=${output_tokens}"
          "concurrency=${concurrency}"
          "repeat=${repeat}"
        )
      fi
      echo "RUN case=${case_id} repeat=${repeat}/${repeats} input=${input_tokens} output=${output_tokens} concurrency=${concurrency}"
      if [ "${EXECUTE}" = "1" ]; then
        flush_cache
        "${command[@]}"
        executed=$((executed + 1))
      else
        print_command "${command[@]}"
      fi
      repeat=$((repeat + 1))
    done
  done
} < "${CASES_FILE}"

[ "${selected}" -gt 0 ] || die "no cases matched STAGE=${STAGE}"
echo "done selected=${selected} skipped=${skipped} executed=${executed} mode=$([ "${EXECUTE}" = "1" ] && echo execute || echo dry-run)"
