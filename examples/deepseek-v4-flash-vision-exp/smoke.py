#!/usr/bin/env python3
"""Correctness smoke tests for an OpenAI-compatible Vision-Exp endpoint."""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


BASE_URL = os.environ.get("BASE_URL", "http://127.0.0.1:30000").rstrip("/")
MODEL = os.environ.get("MODEL", "deepseek-v4-flash-vision-exp")
TIMEOUT = float(os.environ.get("TIMEOUT", "300"))
API_KEY = os.environ.get("API_KEY", "EMPTY")


def data_url(path: Path) -> str:
    if not path.is_file():
        raise RuntimeError(f"image does not exist: {path}")
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def request_json(method: str, path: str, payload: dict | None = None) -> dict:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        BASE_URL + path,
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} for {path}: {detail}") from exc


def chat(content: str | list[dict], max_tokens: int = 128) -> str:
    response = request_json(
        "POST",
        "/v1/chat/completions",
        {
            "model": MODEL,
            "messages": [{"role": "user", "content": content}],
            "temperature": 0,
            "max_tokens": max_tokens,
            "stream": False,
        },
    )
    try:
        message = response["choices"][0]["message"]
        content_text = message.get("content") or ""
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"invalid chat response: {response}") from exc
    if not content_text.strip():
        raise RuntimeError(f"empty final content: {response}")
    return content_text.strip()


def require_tokens(name: str, text: str, expected: list[str]) -> None:
    upper = text.upper()
    missing = [token for token in expected if token not in upper]
    if missing:
        raise RuntimeError(f"{name}: missing {missing}; response={text!r}")


def main() -> int:
    image_a_path = os.environ.get("IMAGE_A") or os.environ.get("IMAGE_CARROTS")
    image_b_path = os.environ.get("IMAGE_B") or os.environ.get("IMAGE_CORN")
    expected_a = os.environ.get("EXPECTED_A", "CARROT")
    expected_b = os.environ.get("EXPECTED_B", "CORN")
    if not image_a_path or not image_b_path:
        raise RuntimeError("set IMAGE_A and IMAGE_B (or IMAGE_CARROTS and IMAGE_CORN)")

    models = request_json("GET", "/v1/models")
    model_ids = [item.get("id") for item in models.get("data", []) if isinstance(item, dict)]
    if MODEL not in model_ids:
        raise RuntimeError(f"served model {MODEL!r} not in /v1/models: {model_ids}")

    text_result = chat("Reply with exactly TEXT_OK and nothing else.", 32)
    require_tokens("text", text_result, ["TEXT_OK"])

    image_a = data_url(Path(image_a_path))
    image_b = data_url(Path(image_b_path))
    image_a_result = chat(
        [
            {"type": "text", "text": f"Identify the main subject. Reply exactly {expected_a}."},
            {"type": "image_url", "image_url": {"url": image_a}},
        ],
        64,
    )
    require_tokens("single-image-a", image_a_result, [expected_a])

    image_b_result = chat(
        [
            {"type": "text", "text": f"Identify the main subject. Reply exactly {expected_b}."},
            {"type": "image_url", "image_url": {"url": image_b}},
        ],
        64,
    )
    require_tokens("single-image-b", image_b_result, [expected_b])
    if image_a_result.upper() == image_b_result.upper():
        raise RuntimeError("image sensitivity failed: image A and B responses are identical")

    interleaved_result = chat(
        [
            {"type": "text", "text": "First image: "},
            {"type": "image_url", "image_url": {"url": image_a}},
            {"type": "text", "text": " Second image: "},
            {"type": "image_url", "image_url": {"url": image_b}},
            {
                "type": "text",
                "text": f"Name both main subjects in order. Reply exactly {expected_a},{expected_b}.",
            },
        ],
        64,
    )
    require_tokens("interleaved-two-image", interleaved_result, [expected_a, expected_b])
    if interleaved_result.upper().find(expected_a.upper()) > interleaved_result.upper().find(expected_b.upper()):
        raise RuntimeError(f"image order failed: {interleaved_result!r}")

    report = {
        "status": "PASS",
        "base_url": BASE_URL,
        "model": MODEL,
        "checks": {
            "models": model_ids,
            "text": text_result,
            "single_image_a": image_a_result,
            "single_image_b": image_b_result,
            "interleaved_two_image": interleaved_result,
        },
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
