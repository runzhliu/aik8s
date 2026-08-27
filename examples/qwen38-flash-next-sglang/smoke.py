#!/usr/bin/env python3
"""OpenAI-compatible correctness smoke for Qwen3.8-Flash-Next."""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import sys
from typing import Optional
import urllib.error
import urllib.request


BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:30000/v1").rstrip("/")
MODEL = os.getenv("MODEL", "qwen38-flash-next")
TIMEOUT = int(os.getenv("TIMEOUT", "300"))
IMAGE_PATH = os.getenv("IMAGE_PATH")


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


def chat(messages: list[dict], **extra: object) -> dict:
    payload = {
        "model": MODEL,
        "messages": messages,
        "stream": False,
        "max_tokens": 512,
    }
    payload.update(extra)
    return request("POST", "/chat/completions", payload)


def assistant_message(response: dict) -> dict:
    choices = response.get("choices") or []
    if not choices:
        raise AssertionError(f"response has no choices: {response}")
    return choices[0]["message"]


def main() -> int:
    models = request("GET", "/models")
    advertised = [item.get("id") for item in models.get("data", [])]
    if MODEL not in advertised:
        raise AssertionError(f"{MODEL!r} not found in /v1/models: {advertised}")

    reasoning = assistant_message(
        chat(
            [{"role": "user", "content": "计算 37×19，并只在最终答案中写出算式和结果。"}],
            reasoning_effort="low",
        )
    )
    if not reasoning.get("content"):
        raise AssertionError(f"empty final content: {reasoning}")

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

    vision_result = {"status": "SKIP", "content": None}
    if IMAGE_PATH:
        media_type = mimetypes.guess_type(IMAGE_PATH)[0] or "image/png"
        with open(IMAGE_PATH, "rb") as image_file:
            image_data = base64.b64encode(image_file.read()).decode("ascii")
        vision = assistant_message(
            chat(
                [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{media_type};base64,{image_data}"
                                },
                            },
                            {"type": "text", "text": "简要描述图片中的主体。"},
                        ],
                    }
                ],
                max_tokens=256,
                chat_template_kwargs={"enable_thinking": False},
            )
        )
        if not vision.get("content"):
            raise AssertionError(f"empty vision response: {vision}")
        vision_result = {"status": "PASS", "content": vision.get("content")}

    result = {
        "base_url": BASE_URL,
        "model": MODEL,
        "models_endpoint": "PASS",
        "reasoning": {
            "status": "PASS",
            "has_reasoning_content": bool(reasoning.get("reasoning_content")),
            "content": reasoning.get("content"),
        },
        "tool_call": {
            "status": "PASS",
            "calls": tool_message.get("tool_calls"),
        },
        "vision": vision_result,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # The smoke output should remain readable in CI.
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False, indent=2))
        raise
