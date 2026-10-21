FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl libseccomp2 libcap2 libslirp0 \
    && rm -rf /var/lib/apt/lists/*
RUN python -m pip install --no-cache-dir \
    boxlite==0.10.7 prometheus-client==0.23.1 requests==2.32.5
ENV PYTHONUNBUFFERED=1
WORKDIR /app
CMD ["python", "/app/lab.py"]
