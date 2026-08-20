#!/usr/bin/env bash
set -euo pipefail

command -v nvidia-smi >/dev/null
command -v swift >/dev/null

nvidia-smi --query-gpu=index,name,memory.total,driver_version --format=csv

python - <<'PY'
import importlib.metadata
import torch

print(f"torch={torch.__version__}")
print(f"torch_cuda={torch.version.cuda}")
print(f"cuda_available={torch.cuda.is_available()}")
print(f"gpu_count={torch.cuda.device_count()}")
print(f"ms_swift={importlib.metadata.version('ms-swift')}")

if not torch.cuda.is_available():
    raise SystemExit("CUDA is not available to PyTorch")
PY
