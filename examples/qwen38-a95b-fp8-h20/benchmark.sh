#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CASES_FILE="${CASES_FILE:-${SCRIPT_DIR}/cases.csv}"
BASE_URL="${BASE_URL:-http://127.0.0.1:30000}"
MODEL="${MODEL:-qwen38-a95b-fp8}"
TOKENIZER="${TOKENIZER:-/models-nvme/Qwen3.8-2.4T-A95B-FP8/v1}"
ENGINE="${ENGINE:-sglang}"
STAGE="${STAGE:-smoke}"
RUN_LABEL="${RUN_LABEL:-unlabelled}"
RESULTS_DIR="${RESULTS_DIR:-${SCRIPT_DIR}/results/${RUN_LABEL}}"
EXECUTE="${EXECUTE:-0}"
MAX_CONTEXT="${MAX_CONTEXT:-32768}"
FLUSH_CACHE="${FLUSH_CACHE:-1}"
FLUSH_RETRIES="${FLUSH_RETRIES:-180}"
FLUSH_RETRY_DELAY="${FLUSH_RETRY_DELAY:-2}"

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
  smoke|baseline|prefill|decode|saturation|long|extreme|all) ;;
  *) die "invalid STAGE=${STAGE}" ;;
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
  local attempt=1
  while ! curl -fsS -X POST "${BASE_URL}${FLUSH_PATH}" \
      -H "Content-Type: application/json" \
      -H "Authorization: Bearer EMPTY" \
      -d '{}' >/dev/null; do
    if [ "${attempt}" -ge "${FLUSH_RETRIES}" ]; then
      die "cache flush failed after ${FLUSH_RETRIES} attempts"
    fi
    sleep "${FLUSH_RETRY_DELAY}"
    attempt=$((attempt + 1))
  done
}

if [ "${EXECUTE}" = "1" ]; then
  command -v vllm >/dev/null 2>&1 || die "vLLM CLI is required for the common benchmark client"
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
      command=(
        vllm bench serve
        --backend openai
        --base-url "${BASE_URL}"
        --endpoint /v1/completions
        --model "${MODEL}"
        --served-model-name "${MODEL}"
        --tokenizer "${TOKENIZER}"
        --trust-remote-code
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
        --seed "$((20260903 + repeat))"
        --disable-tqdm
        --save-result
        --save-detailed
        --percentile-metrics ttft,tpot,itl,e2el
        --metric-percentiles 50,95,99
        --result-dir "${RESULTS_DIR}"
        --result-filename "${filename}"
        --request-id-prefix "qwen38-${ENGINE}-${case_id}-r${repeat}-"
        --metadata
        "run_label=${RUN_LABEL}"
        "engine=${ENGINE}"
        "case_id=${case_id}"
        "input_tokens=${input_tokens}"
        "output_tokens=${output_tokens}"
        "concurrency=${concurrency}"
        "repeat=${repeat}"
        "bench_client=vllm"
      )
      echo "RUN label=${RUN_LABEL} case=${case_id} repeat=${repeat}/${repeats} input=${input_tokens} output=${output_tokens} concurrency=${concurrency}"
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
echo "done selected=${selected} skipped=${skipped} executed=${executed} client=vllm mode=$([ "${EXECUTE}" = "1" ] && echo execute || echo dry-run)"
