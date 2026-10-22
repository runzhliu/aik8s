FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl libseccomp2 libcap2 libslirp0 e2fsprogs \
    && rm -rf /var/lib/apt/lists/*
RUN python -m pip install --no-cache-dir --only-binary=:all: \
    microsandbox==0.7.8 prometheus-client==0.23.1 requests==2.32.5
RUN python -c "import microsandbox; print(microsandbox.__file__)" && msb --version
RUN curl -fL --retry 2 --connect-timeout 10 --max-time 120 \
    https://github.com/superradcompany/microsandbox/releases/download/v0.7.8/msb-metrics-linux-x86_64 \
    -o /usr/local/bin/msb-metrics \
    && curl -fL --retry 2 --connect-timeout 10 --max-time 60 \
    https://github.com/superradcompany/microsandbox/releases/download/v0.7.8/checksums.sha256 \
    -o /tmp/microsandbox-checksums.sha256
RUN python -c "import hashlib; from pathlib import Path; lines=Path('/tmp/microsandbox-checksums.sha256').read_text().splitlines(); expected=next(x.split()[0] for x in lines if x.split()[-1].lstrip('*').endswith('msb-metrics-linux-x86_64')); assert hashlib.sha256(Path('/usr/local/bin/msb-metrics').read_bytes()).hexdigest()==expected" \
    && chmod 755 /usr/local/bin/msb-metrics
ENV PYTHONUNBUFFERED=1
WORKDIR /app
CMD ["python", "-c", "import time; time.sleep(86400)"]
