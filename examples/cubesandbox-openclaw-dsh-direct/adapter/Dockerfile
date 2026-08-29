FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY cube_adapter.py ./

RUN groupadd --system --gid 65532 adapter \
    && useradd --system --uid 65532 --gid adapter --home-dir /nonexistent adapter

USER 65532:65532
EXPOSE 18080
ENTRYPOINT ["python", "/app/cube_adapter.py"]
