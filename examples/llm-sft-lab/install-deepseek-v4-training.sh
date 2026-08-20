#!/usr/bin/env bash
set -euo pipefail

# Megatron-Core uses the commit recorded by the upstream DeepSeek V4 recipe.
python -m pip install --upgrade \
  'git+https://github.com/NVIDIA/Megatron-LM.git@fd1121b8ff7e3a4f83a28d35aed172d7bc0260e1'
python -m pip install --upgrade \
  'git+https://github.com/modelscope/mcore-bridge.git'
python -m pip install --upgrade \
  'git+https://github.com/modelscope/ms-swift.git'

python -m pip freeze | grep -E 'megatron|mcore|ms-swift|torch|transformers'
