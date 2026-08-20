#!/usr/bin/env bash
set -euo pipefail

LAB_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
LAB_VENV="${LAB_VENV:-${LAB_ROOT}/.venv}"

# Reuse the CUDA-enabled PyTorch from an existing GPU image when available.
python3 -m venv --system-site-packages "${LAB_VENV}"
"${LAB_VENV}/bin/python" -m pip install --upgrade pip
"${LAB_VENV}/bin/python" -m pip install --upgrade ms-swift

echo "ms-swift installed in ${LAB_VENV}"
echo "Activate it with: source ${LAB_VENV}/bin/activate"
