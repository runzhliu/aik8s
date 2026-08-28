#!/usr/bin/env python3
"""OpenAI-compatible correctness smoke for GLM-5.3-Flash."""

from __future__ import annotations

import base64
import json
import mimetypes
import os
from pathlib import Path
from typing import Optional
import urllib.error
import urllib.request


BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:30000/v1").rstrip("/")
MODEL = os.getenv("MODEL", "glm53-flash")
TIMEOUT = int(os.getenv("TIMEOUT", "600"))
IMAGE_PATH = os.getenv("IMAGE_PATH")
VIDEO_PATH = os.getenv("VIDEO_PATH")


def request(method: str, path: str, payload: Optional[dict] = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json", "Authorization": "Bearer EMPTY"},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} {path}: {body}") from exc


def chat(messages: list[dict], effort: str = "low", **extra: object) -> dict:
    payload = {
        "model": MODEL,
        "messages": messages,
        "stream": False,
        "temperature": 0,
        "max_tokens": 512,
        "reasoning_effort": effort,
    }
    payload.update(extra)
    return request("POST", "/chat/completions", payload)


def assistant_message(response: dict) -> dict:
    choices = response.get("choices") or []
    if not choices:
        raise AssertionError(f"response has no choices: {response}")
    return choices[0]["message"]


def data_url(path: str) -> str:
    media_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
    payload = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    return f"data:{media_type};base64,{payload}"


def multimodal(kind: str, path: Optional[str]) -> dict:
    if not path:
        return {"status": "SKIP"}
    item_type = f"{kind}_url"
    result = assistant_message(
        chat(
            [
                {
                    "role": "user",
                    "content": [
                        {"type": item_type, item_type: {"url": data_url(path)}},
                        {"type": "text", "text": "用一句话描述内容，不要猜测看不见的信息。"},
                    ],
                }
            ],
            max_tokens=256,
        )
    )
    if not result.get("content"):
        raise AssertionError(f"empty {kind} response: {result}")
    return {"status": "PASS", "content": result.get("content")}


def main() -> int:
    models = request("GET", "/models")
    advertised = [item.get("id") for item in models.get("data", [])]
    if MODEL not in advertised:
        raise AssertionError(f"{MODEL!r} not found in /v1/models: {advertised}")

    reasoning_results = {}
    for effort in ("low", "high", "max"):
        message = assistant_message(
            chat(
                [{"role": "user", "content": "计算 37×19，并在最终答案中给出算式和结果。"}],
                effort=effort,
            )
        )
        if not message.get("content"):
            raise AssertionError(f"empty final content for effort={effort}: {message}")
        reasoning_results[effort] = {
            "status": "PASS",
            "has_reasoning_content": bool(message.get("reasoning_content")),
            "content": message.get("content"),
        }

    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "查询指定城市的天气",
                "parameters": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                },
            },
        }
    ]
    tool_message = assistant_message(
        chat(
            [{"role": "user", "content": "请调用工具查询杭州天气，不要自行编造天气。"}],
            tools=tools,
            tool_choice="auto",
        )
    )
    if not tool_message.get("tool_calls"):
        raise AssertionError(f"structured tool call missing: {tool_message}")

    result = {
        "status": "PASS",
        "base_url": BASE_URL,
        "model": MODEL,
        "models_endpoint": "PASS",
        "reasoning_effort": reasoning_results,
        "tool_call": {"status": "PASS", "calls": tool_message.get("tool_calls")},
        "image": multimodal("image", IMAGE_PATH),
        "video": multimodal("video", VIDEO_PATH),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False, indent=2))
        raise
