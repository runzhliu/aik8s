#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MATRIX="${SCRIPT_DIR}/cases.csv"
PROFILES="${SCRIPT_DIR}/profiles.csv"
STAGE="smoke"
PROFILE=""
BASE_URL=""
MODEL=""
TOKENIZER=""
TOKENIZER_MODE=""
RESULT_DIR="${SCRIPT_DIR}/results"
MAX_CONTEXT_OVERRIDE=""
REPEATS_OVERRIDE=""
NUM_PROMPTS_OVERRIDE=""
WARMUPS_OVERRIDE=""
EXECUTE=0
TRUST_REMOTE_CODE=0
CASE_FILTER=","
HEADERS=()

# Usage:
#   ./run-matrix.sh --profile PROFILE --base-url URL --model API_MODEL \
#     --tokenizer TOKENIZER [--stage smoke|baseline|capacity|all] [--execute]
#
# The default is a dry-run. Add --execute only after correctness gates pass.
# --case CASE_ID may be repeated. --header KEY=VALUE may be repeated.

usage() {
  sed -n '/^# Usage:/,/^$/p' "$0" | sed 's/^# \{0,1\}//'
}

die() {
  echo "error: $*" >&2
  exit 1
}

need_value() {
  [ "$#" -ge 2 ] || die "$1 requires a value"
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --matrix) need_value "$@"; MATRIX="$2"; shift 2 ;;
    --profiles) need_value "$@"; PROFILES="$2"; shift 2 ;;
    --stage) need_value "$@"; STAGE="$2"; shift 2 ;;
    --profile) need_value "$@"; PROFILE="$2"; shift 2 ;;
    --base-url) need_value "$@"; BASE_URL="$2"; shift 2 ;;
    --model) need_value "$@"; MODEL="$2"; shift 2 ;;
    --tokenizer) need_value "$@"; TOKENIZER="$2"; shift 2 ;;
    --tokenizer-mode) need_value "$@"; TOKENIZER_MODE="$2"; shift 2 ;;
    --result-dir) need_value "$@"; RESULT_DIR="$2"; shift 2 ;;
    --max-context) need_value "$@"; MAX_CONTEXT_OVERRIDE="$2"; shift 2 ;;
    --repeats) need_value "$@"; REPEATS_OVERRIDE="$2"; shift 2 ;;
    --num-prompts) need_value "$@"; NUM_PROMPTS_OVERRIDE="$2"; shift 2 ;;
    --warmups) need_value "$@"; WARMUPS_OVERRIDE="$2"; shift 2 ;;
    --case) need_value "$@"; CASE_FILTER="${CASE_FILTER}${2},"; shift 2 ;;
    --header) need_value "$@"; HEADERS+=("$2"); shift 2 ;;
    --trust-remote-code) TRUST_REMOTE_CODE=1; shift ;;
    --execute) EXECUTE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

[ -f "$MATRIX" ] || die "matrix not found: $MATRIX"
[ -f "$PROFILES" ] || die "profiles not found: $PROFILES"
[ -n "$PROFILE" ] || die "--profile is required"
[ -n "$BASE_URL" ] || die "--base-url is required"
[ -n "$MODEL" ] || die "--model is required"
[ -n "$TOKENIZER" ] || die "--tokenizer is required"

case "$STAGE" in
  smoke|baseline|capacity|all) ;;
  *) die "--stage must be smoke, baseline, capacity, or all" ;;
esac

PROFILE_LINE="$(awk -F, -v profile="$PROFILE" 'NR > 1 && $1 == profile { print; exit }' "$PROFILES")"
[ -n "$PROFILE_LINE" ] || die "unknown profile: $PROFILE"

IFS=, read -r profile_id model_family engine topology transport tp_prefill tp_decode gpu_count speculative profile_max_context comparison_group profile_notes <<EOF
$PROFILE_LINE
EOF

MAX_CONTEXT="${MAX_CONTEXT_OVERRIDE:-$profile_max_context}"
case "$MAX_CONTEXT" in
  ''|*[!0-9]*) die "max context must be an integer" ;;
esac

if [ "$topology" = "pd" ]; then
  has_routing_header=0
  for header in "${HEADERS[@]:-}"; do
    case "$header" in routing-strategy=*) has_routing_header=1 ;; esac
  done
  if [ "$has_routing_header" -eq 0 ]; then
    HEADERS+=("routing-strategy=pd")
  fi
fi

if [ "$EXECUTE" -eq 1 ]; then
  command -v vllm >/dev/null 2>&1 || die "vllm CLI is not installed"
  mkdir -p "$RESULT_DIR"
fi

print_command() {
  printf '  '
  printf '%q ' "$@"
  printf '\n'
}

selected=0
skipped=0
executed=0

echo "profile=$PROFILE model_family=$model_family engine=$engine topology=$topology transport=$transport"
echo "stage=$STAGE max_context=$MAX_CONTEXT gpu_count=$gpu_count mode=$([ "$EXECUTE" -eq 1 ] && echo execute || echo dry-run)"

{
  IFS= read -r _header
  while IFS=, read -r case_id case_stage input_tokens output_tokens concurrency num_prompts repeats request_rate description; do
    [ -n "$case_id" ] || continue
    if [ "$STAGE" != "all" ] && [ "$case_stage" != "$STAGE" ]; then
      continue
    fi
    if [ "$CASE_FILTER" != "," ]; then
      case "$CASE_FILTER" in
        *",${case_id},"*) ;;
        *) continue ;;
      esac
    fi

    selected=$((selected + 1))
    required_context=$((input_tokens + output_tokens))
    if [ "$required_context" -gt "$MAX_CONTEXT" ]; then
      skipped=$((skipped + 1))
      echo "SKIP_UNSUPPORTED case=$case_id required=$required_context max_context=$MAX_CONTEXT"
      if [ "$EXECUTE" -eq 1 ]; then
        printf '{"status":"SKIP_UNSUPPORTED","profile":"%s","case_id":"%s","required_context":%s,"max_context":%s}\n' \
          "$PROFILE" "$case_id" "$required_context" "$MAX_CONTEXT" \
          > "${RESULT_DIR}/${PROFILE}__${case_id}.skip.json"
      fi
      continue
    fi

    effective_repeats="${REPEATS_OVERRIDE:-$repeats}"
    effective_prompts="${NUM_PROMPTS_OVERRIDE:-$num_prompts}"
    effective_warmups="${WARMUPS_OVERRIDE:-$concurrency}"
    rep=1
    while [ "$rep" -le "$effective_repeats" ]; do
      seed=$((20260819 + rep))
      filename="${PROFILE}__${case_id}__r${rep}.json"
      command=(
        vllm bench serve
        --backend openai
        --base-url "$BASE_URL"
        --endpoint /v1/completions
        --model "$MODEL"
        --served-model-name "$MODEL"
        --tokenizer "$TOKENIZER"
        --dataset-name random
        --random-input-len "$input_tokens"
        --random-output-len "$output_tokens"
        --random-range-ratio 0
        --num-prompts "$effective_prompts"
        --max-concurrency "$concurrency"
        --request-rate "$request_rate"
        --temperature 0
        --ignore-eos
        --num-warmups "$effective_warmups"
        --seed "$seed"
        --disable-tqdm
        --save-result
        --save-detailed
        --percentile-metrics ttft,tpot,itl,e2el
        --metric-percentiles 50,95,99
        --result-dir "$RESULT_DIR"
        --result-filename "$filename"
        --request-id-prefix "${PROFILE}-${case_id}-r${rep}-"
        --metadata
        "profile=$PROFILE"
        "case_id=$case_id"
        "stage=$case_stage"
        "input_tokens=$input_tokens"
        "output_tokens=$output_tokens"
        "concurrency=$concurrency"
        "repeat=$rep"
        "gpu_count=$gpu_count"
        "topology=$topology"
        "transport=$transport"
        "speculative=$speculative"
      )
      if [ -n "$TOKENIZER_MODE" ]; then
        command+=(--tokenizer-mode "$TOKENIZER_MODE")
      fi
      if [ "$TRUST_REMOTE_CODE" -eq 1 ]; then
        command+=(--trust-remote-code)
      fi
      for header in "${HEADERS[@]:-}"; do
        [ -n "$header" ] && command+=(--header "$header")
      done

      echo "RUN case=$case_id repeat=$rep/$effective_repeats input=$input_tokens output=$output_tokens concurrency=$concurrency prompts=$effective_prompts"
      if [ "$EXECUTE" -eq 1 ]; then
        "${command[@]}"
        executed=$((executed + 1))
      else
        print_command "${command[@]}"
      fi
      rep=$((rep + 1))
    done
  done
} < "$MATRIX"

[ "$selected" -gt 0 ] || die "no cases matched stage/case filters"
echo "done selected=$selected skipped=$skipped executed=$executed"
