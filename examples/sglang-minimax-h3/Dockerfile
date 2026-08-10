ARG BASE_IMAGE
FROM ${BASE_IMAGE}

# The upstream image bundles the SGLang source tree, but its optional
# diffusion dependencies are intentionally installed by the launch example.
# Install them while building so an offline production Pod never contacts
# GitHub or PyPI during startup.
RUN python -m pip install --no-cache-dir \
      -e "/sgl-workspace/sglang/python[diffusion]" \
    && python -c "import sglang.multimodal_gen.configs.pipeline_configs.minimax_h3 as h3; print(h3.__file__)"

LABEL org.opencontainers.image.title="SGLang Diffusion for MiniMax H3" \
      org.opencontainers.image.description="Offline runtime with SGLang diffusion dependencies preinstalled"
