#!/usr/bin/env bash
set -euo pipefail
ENGINE="${ENGINE:-sglang}"
MODEL_PATH="${MODEL_PATH:-/models-nvme/MiniMaxAI/MiniMax-H3}"
VARIANT="${VARIANT:-fl2va}"
PORT="${PORT:-8000}"
EXECUTE="${EXECUTE:-0}"
case "$VARIANT" in fl2va|ref2va) ;; *) echo 'VARIANT must be fl2va or ref2va' >&2; exit 2;; esac
case "$ENGINE" in
  sglang)
    command=(sglang serve --model-type diffusion --model-path "$MODEL_PATH" --model-variant "$VARIANT"
      --backend sglang --model-id MiniMax-H3
      --num-gpus 4 --ulysses-degree 4 --encoder-parallel auto
      --performance-mode speed --output-path /outputs/server
      --input-save-path /outputs/inputs --host 0.0.0.0 --port "$PORT") ;;
  vllm-omni)
    command=(vllm serve "$MODEL_PATH" --omni --task-type "$VARIANT"
      --num-gpus 4 --usp 4 --ring 1 --text-encoder-tp-size 4
      --vae-patch-parallel-size 4 --vae-parallel-mode tile --vae-use-tiling
      --diffusion-attention-backend FLASH_ATTN --trust-remote-code
      --host 0.0.0.0 --port "$PORT") ;;
  *) echo 'ENGINE must be sglang or vllm-omni' >&2; exit 2;;
esac
if [[ "$ENGINE" == vllm-omni && "${MODEL_STORAGE:-nvme}" == cfs ]]; then
  command+=(--init-timeout "${H3_INIT_TIMEOUT:-3600}"
    --stage-init-timeout "${H3_STAGE_INIT_TIMEOUT:-3600}")
fi
printf '%q ' "${command[@]}"; printf '\n'
if [[ "$EXECUTE" == 1 ]]; then
  case "${MODEL_STORAGE:-nvme}" in
    nvme)
      [[ -f "$MODEL_PATH/.aik8s-complete" ]] || { echo 'NVMe completion marker missing' >&2; exit 1; }
      [[ -f "$MODEL_PATH/REVISION" ]] || { echo 'model REVISION missing' >&2; exit 1; } ;;
    cfs)
      python3 - "$MODEL_PATH" "${MODEL_IDENTITY_FILE:-/outputs/model-identity.json}" <<'PY'
import json, sys
from pathlib import Path
model, report = map(Path, sys.argv[1:])
identity = json.loads(report.read_text())
assert model.is_dir(), 'CFS model directory missing'
assert identity['status'] == 'PASS' and identity['model_path'] == str(model), 'CFS identity validation missing'
assert identity['source_snapshot_id'].startswith('metadata-sha256:'), 'CFS metadata snapshot missing'
PY
      ;;
    *) echo 'MODEL_STORAGE must be nvme or cfs' >&2; exit 2 ;;
  esac
  export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
  run_id="$(date -u +%Y%m%dT%H%M%S)-$$"
  mkdir -p /outputs/logs
  mkdir -p "/outputs/runtime/${run_id}"
  cp -L /h3-launch/* "/outputs/runtime/${run_id}/"
  exec > >(tee -a "/outputs/logs/server-${run_id}.log") 2>&1
  if [[ "${H3_RUNTIME_FIXES:-0}" == 1 ]]; then
    python3 /h3-launch/apply_runtime_fixes.py --engine "$ENGINE" \
      --evidence "/outputs/runtime/${run_id}/fix-evidence"
  fi
  python3 /h3-launch/monitor_gpu.py "/outputs/logs/gpu-${run_id}.csv" &
  if [[ "$ENGINE" == sglang ]]; then
    python3 /h3-launch/preserve_outputs.py
  fi
  exec "${command[@]}"
fi
