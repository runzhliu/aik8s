ARG BASE_IMAGE=vllm/vllm-openai:v0.26.0-cu129
FROM ${BASE_IMAGE}

ARG LMCACHE_VERSION=0.5.2

# vLLM v0.26.0-cu129 already bundles LMCache 0.5.2. This Dockerfile is only a
# fallback for a validated base image that does not contain LMCache. Do not use
# it to downgrade or overwrite the version bundled by the official image.
RUN uv pip install --system "lmcache==${LMCACHE_VERSION}" \
    && python3 -c 'from importlib.metadata import version; print("vllm", version("vllm"), "lmcache", version("lmcache"))'
