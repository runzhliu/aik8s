FROM node:24.15.0-bookworm-slim

ARG CODEX_VERSION=0.150.1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        python3 \
        python3-pip \
        socat \
    && rm -rf /var/lib/apt/lists/* \
    && npm install --global "@openai/codex@${CODEX_VERSION}" \
    && python3 -m pip install --break-system-packages --no-cache-dir "mcp>=2,<3"

WORKDIR /workspace/cubesandbox-agent-adapter
COPY adapter/mcp_server.py ./cube_mcp_server.py

CMD ["sleep", "infinity"]
