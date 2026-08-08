ARG BASE_IMAGE=nvitop-exporter:source
FROM ${BASE_IMAGE}

ARG NVITOP_VERSION=1.7.1
ARG NVIDIA_ML_PY_VERSION=13.580.126

RUN /venv/bin/python -m pip install \
      --no-cache-dir \
      --upgrade \
      "nvidia-ml-py==${NVIDIA_ML_PY_VERSION}" \
      "nvitop==${NVITOP_VERSION}" \
      "nvitop-exporter==${NVITOP_VERSION}" \
    && /venv/bin/python -m pip check \
    && /venv/bin/python -m pip show nvitop nvitop-exporter nvidia-ml-py

ENTRYPOINT ["/venv/bin/python3", "-m", "nvitop_exporter"]
