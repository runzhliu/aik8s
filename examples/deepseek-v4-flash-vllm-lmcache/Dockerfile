ARG BASE_IMAGE=vllm/vllm-openai:v0.26.0-cu129
FROM ${BASE_IMAGE}

ARG LMCACHE_VERSION=0.5.3
ARG CUDA_TAG=cu129

# CUDA 12.9 wheels are published in a dedicated LMCache release, not on the
# default PyPI CUDA 13 path. Keep vLLM, Torch, CUDA and LMCache as one pinned
# compatibility unit and publish the resulting image by digest.
RUN uv pip install --system "lmcache==${LMCACHE_VERSION}" \
      --extra-index-url "https://download.pytorch.org/whl/${CUDA_TAG}" \
      --find-links "https://github.com/LMCache/LMCache/releases/expanded_assets/v${LMCACHE_VERSION}-cu129" \
      --index-strategy unsafe-best-match \
    && python3 -c 'import lmcache.c_ops; from importlib.metadata import version; print("vllm", version("vllm"), "lmcache", version("lmcache"))'
