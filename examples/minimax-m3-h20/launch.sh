#!/usr/bin/env bash
# Reproduce the measured BF16 TP8 configuration; EXECUTE=1 starts the service.
set -euo pipefail
ENGINE="${ENGINE:-sglang}"
MODEL_PATH="${MODEL_PATH:-/models/MiniMax-M3/v1}"
MODEL="${MODEL:-minimax-m3}"
MAX_CONTEXT="${MAX_CONTEXT:-32768}"
MEM_FRACTION="${MEM_FRACTION:-0.85}"
MAX_REQUESTS="${MAX_REQUESTS:-32}"
case "$ENGINE" in
  sglang)
    command=(python3 -m sglang.launch_server
      --model-path "$MODEL_PATH" --served-model-name "$MODEL"
      --host 0.0.0.0 --port 8000 --tp 8 --dtype bfloat16
      --context-length "$MAX_CONTEXT" --mem-fraction-static "$MEM_FRACTION"
      --max-running-requests "$MAX_REQUESTS" --chunked-prefill-size 2048
      --reasoning-parser auto --tool-call-parser auto
      --disable-radix-cache --trust-remote-code)
    if [[ "${DISABLE_PIECEWISE_CUDA_GRAPH:-1}" == 1 ]]; then
      command+=(--cuda-graph-backend-prefill disabled)
    fi
    ;;
  vllm)
    command=(vllm serve "$MODEL_PATH" --served-model-name "$MODEL"
      --host 0.0.0.0 --port 8000 --tensor-parallel-size 8 --dtype bfloat16
      --max-model-len "$MAX_CONTEXT" --gpu-memory-utilization "$MEM_FRACTION"
      --max-num-seqs "$MAX_REQUESTS" --max-num-batched-tokens 2048
      --block-size 128 --kv-cache-dtype auto --no-enable-prefix-caching
      --reasoning-parser minimax_m3 --tool-call-parser minimax_m3
      --enable-auto-tool-choice --trust-remote-code)
    if [[ -n "${SAFETENSORS_LOAD_STRATEGY:-eager}" ]]; then
      command+=(--safetensors-load-strategy "${SAFETENSORS_LOAD_STRATEGY:-eager}")
    fi
    ;;
  *) echo 'ENGINE must be sglang or vllm' >&2; exit 2 ;;
esac
printf '%q ' "${command[@]}"; printf '\n'
if [[ "${EXECUTE:-0}" == 1 ]]; then
  [[ -d "$MODEL_PATH" ]] || { echo 'Model directory missing' >&2; exit 1; }
  exec "${command[@]}"
fi
