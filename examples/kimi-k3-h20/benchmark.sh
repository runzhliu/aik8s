#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CASES_FILE="${CASES_FILE:-${SCRIPT_DIR}/cases.csv}"
BASE_URL="${BASE_URL:-http://127.0.0.1:30000}"
MODEL="${MODEL:-kimi-k3}"
TOKENIZER="${TOKENIZER:-/models-nvme/Kimi-K3/v1}"
ENGINE="${ENGINE:-sglang}"
BENCH_CLIENT="${BENCH_CLIENT:-vllm}"
STAGE="${STAGE:-smoke}"
RUN_LABEL="${RUN_LABEL:-unlabelled}"
RESULTS_DIR="${RESULTS_DIR:-${SCRIPT_DIR}/results/${RUN_LABEL}}"
EXECUTE="${EXECUTE:-0}"
FLUSH_CACHE="${FLUSH_CACHE:-1}"
FLUSH_RETRIES="${FLUSH_RETRIES:-150}"
FLUSH_RETRY_DELAY="${FLUSH_RETRY_DELAY:-2}"
MAX_CONTEXT="${MAX_CONTEXT:-32768}"
ALLOW_VLLM_OVER_128K="${ALLOW_VLLM_OVER_128K:-0}"
VLLM_BENCH_FORCE_PYTHON="${VLLM_BENCH_FORCE_PYTHON:-0}"

die() {
  echo "error: $*" >&2
  exit 1
}

case "${ENGINE}" in
  sglang) FLUSH_PATH="${FLUSH_PATH:-/flush_cache}" ;;
  vllm) FLUSH_PATH="${FLUSH_PATH:-/reset_prefix_cache}" ;;
  *) die "ENGINE must be sglang or vllm" ;;
esac

case "${BENCH_CLIENT}" in
  vllm) ;;
  sglang-native)
    [ "${ENGINE}" = "sglang" ] || die "BENCH_CLIENT=sglang-native requires ENGINE=sglang"
    ;;
  *) die "BENCH_CLIENT must be vllm or sglang-native" ;;
esac

case "${STAGE}" in
  smoke|baseline|decode|saturation|long|extreme|all) ;;
  *) die "STAGE must be smoke baseline decode saturation long extreme or all" ;;
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
    echo "WAIT cache flush rejected; active requests may still be draining (attempt=${attempt}/${FLUSH_RETRIES})"
    sleep "${FLUSH_RETRY_DELAY}"
    attempt=$((attempt + 1))
  done
}

if [ "${EXECUTE}" = "1" ]; then
  if [ "${BENCH_CLIENT}" = "sglang-native" ]; then
    python3 -c 'import sglang.bench_serving' >/dev/null 2>&1 || \
      die "SGLang benchmark client is required for BENCH_CLIENT=sglang-native"
  else
    command -v vllm >/dev/null 2>&1 || die "vLLM CLI is required"
  fi
  command -v curl >/dev/null 2>&1 || die "curl is required"
  if [ "${BENCH_CLIENT}" = "vllm" ] && [ "${VLLM_BENCH_FORCE_PYTHON}" = "1" ]; then
    vllm_rust_cli="$(python3 -c 'from pathlib import Path; import vllm; print(Path(vllm.__file__).resolve().parent / "vllm-rs")')"
    if [ -f "${vllm_rust_cli}" ]; then
      mv "${vllm_rust_cli}" "${vllm_rust_cli}.disabled"
      echo "VLLM_BENCH_IMPLEMENTATION=python rust_cli_disabled=${vllm_rust_cli}"
    fi
  fi
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
    if [ "${ENGINE}" = "vllm" ] && [ "${required_context}" -gt 131072 ] && \
       [ "${ALLOW_VLLM_OVER_128K}" != "1" ]; then
      echo "SKIP_VLLM_LONG_CONTEXT_RISK case=${case_id} required=${required_context}"
      skipped=$((skipped + 1))
      continue
    fi

    repeat=1
    while [ "${repeat}" -le "${repeats}" ]; do
      filename="${ENGINE}__${case_id}__r${repeat}.json"
      if [ "${BENCH_CLIENT}" = "sglang-native" ]; then
        filename="${filename%.json}.jsonl"
        command=(
          python3 -m sglang.bench_serving
          --backend sglang
          --base-url "${BASE_URL}"
          --model "${TOKENIZER}"
          --served-model-name "${MODEL}"
          --tokenizer "${TOKENIZER}"
          --dataset-name random-ids
          --random-input-len "${input_tokens}"
          --random-output-len "${output_tokens}"
          --random-range-ratio 0
          --num-prompts "${num_prompts}"
          --max-concurrency "${concurrency}"
          --request-rate inf
          --temperature 0
          --warmup-requests "${concurrency}"
          --seed "$((20260831 + repeat))"
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
          --seed "$((20260831 + repeat))"
          --disable-tqdm
          --save-result
          --save-detailed
          --percentile-metrics ttft,tpot,itl,e2el
          --metric-percentiles 50,95,99
          --result-dir "${RESULTS_DIR}"
          --result-filename "${filename}"
          --request-id-prefix "k3-${ENGINE}-${case_id}-r${repeat}-"
          --metadata
          "run_label=${RUN_LABEL}"
          "engine=${ENGINE}"
          "case_id=${case_id}"
          "input_tokens=${input_tokens}"
          "output_tokens=${output_tokens}"
          "concurrency=${concurrency}"
          "repeat=${repeat}"
          "bench_client=${BENCH_CLIENT}"
        )
      fi
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
echo "done selected=${selected} skipped=${skipped} executed=${executed} client=${BENCH_CLIENT} mode=$([ "${EXECUTE}" = "1" ] && echo execute || echo dry-run)"
