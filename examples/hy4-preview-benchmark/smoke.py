#!/usr/bin/env python3
"""OpenAI-compatible correctness smoke for Tencent Hy4-preview."""

from __future__ import annotations

import json
import os
from typing import Optional
import urllib.error
import urllib.request


BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:30000/v1").rstrip("/")
MODEL = os.getenv("MODEL", "hy4-preview")
TIMEOUT = int(os.getenv("TIMEOUT", "600"))
REQUIRE_REASONING_CONTENT = os.getenv("REQUIRE_REASONING_CONTENT", "1") == "1"


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


def assistant_message(response: dict) -> dict:
    choices = response.get("choices") or []
    if not choices:
        raise AssertionError(f"response has no choices: {response}")
    return choices[0]["message"]


def preview(value: object, limit: int = 240) -> str:
    text = "" if value is None else str(value)
    return text if len(text) <= limit else f"{text[:limit]}…"


def chat(messages: list[dict], **extra: object) -> dict:
    payload = {
        "model": MODEL,
        "messages": messages,
        "stream": False,
        "temperature": 0,
        "top_p": 1.0,
        "max_tokens": 512,
    }
    payload.update(extra)
    return request("POST", "/chat/completions", payload)


def stream_chat(messages: list[dict], **extra: object) -> dict:
    payload = {
        "model": MODEL,
        "messages": messages,
        "stream": True,
        "temperature": 0,
        "top_p": 1.0,
        "max_tokens": 128,
    }
    payload.update(extra)
    req = urllib.request.Request(
        f"{BASE_URL}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": "Bearer EMPTY"},
    )
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    chunks = 0
    saw_done = False
    with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
        for raw_line in response:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                saw_done = True
                break
            event = json.loads(data)
            choices = event.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            content_parts.append(delta.get("content") or "")
            reasoning_parts.append(
                delta.get("reasoning_content") or delta.get("reasoning") or ""
            )
            chunks += 1
    content = "".join(content_parts)
    reasoning = "".join(reasoning_parts)
    if not saw_done:
        raise AssertionError("streaming response did not terminate with [DONE]")
    if not content:
        raise AssertionError(
            f"streaming response returned no final content: reasoning={preview(reasoning)}"
        )
    return {
        "chunks": chunks,
        "saw_done": saw_done,
        "content": content,
        "reasoning_content": reasoning,
    }


def expect_image_rejection() -> dict:
    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "描述这张图片。"},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
                        },
                    },
                ],
            }
        ],
        "stream": False,
        "temperature": 0,
        "max_tokens": 32,
    }
    req = urllib.request.Request(
        f"{BASE_URL}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": "Bearer EMPTY"},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {"status": "PASS", "http_status": exc.code, "body": preview(body)}
    raise AssertionError(f"text-only model unexpectedly accepted image input: {preview(body)}")


def main() -> int:
    models = request("GET", "/models")
    advertised = [item.get("id") for item in models.get("data", [])]
    if MODEL not in advertised:
        raise AssertionError(f"{MODEL!r} not found in /v1/models: {advertised}")

    high = assistant_message(
        chat(
            [{"role": "user", "content": "计算 37×19，最终只需给出算式与答案。"}],
            reasoning_effort="high",
        )
    )
    if not high.get("content"):
        raise AssertionError(f"high reasoning returned no final content: {high}")
    high_reasoning = high.get("reasoning_content") or high.get("reasoning")
    if REQUIRE_REASONING_CONTENT and not high_reasoning:
        raise AssertionError(f"reasoning field is missing: {high}")
    if "703" not in high.get("content", ""):
        raise AssertionError(f"37×19 result is incorrect: {high}")

    no_think = assistant_message(
        chat(
            [{"role": "user", "content": "用一句话说明 Kubernetes 是什么。"}],
            chat_template_kwargs={"reasoning_effort": "no_think"},
            max_tokens=128,
        )
    )
    if not no_think.get("content"):
        raise AssertionError(f"no_think returned no final content: {no_think}")
    no_think_reasoning = no_think.get("reasoning_content") or no_think.get("reasoning")

    stream = stream_chat(
        [{"role": "user", "content": "只回复 STREAM_OK。"}],
        chat_template_kwargs={"reasoning_effort": "no_think"},
    )
    if "STREAM_OK" not in stream["content"]:
        raise AssertionError(f"unexpected streaming content: {stream}")

    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "查询城市天气",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {"type": "string"},
                        "unit": {
                            "type": "string",
                            "enum": ["celsius", "fahrenheit"],
                        },
                    },
                    "required": ["city"],
                },
            },
        }
    ]
    tool_message = assistant_message(
        chat(
            [{"role": "user", "content": "调用工具查询北京天气，温度单位用摄氏度。"}],
            tools=tools,
            tool_choice="auto",
        )
    )
    if not tool_message.get("tool_calls"):
        raise AssertionError(f"structured tool call missing: {tool_message}")
    tool_call = tool_message["tool_calls"][0]
    function = tool_call.get("function") or {}
    if function.get("name") != "get_weather":
        raise AssertionError(f"wrong tool selected: {tool_message}")
    arguments = json.loads(function.get("arguments") or "{}")
    if arguments.get("city") != "北京" or arguments.get("unit") != "celsius":
        raise AssertionError(f"wrong tool arguments: {tool_message}")

    image_rejection = expect_image_rejection()

    result = {
        "status": "PASS",
        "model": MODEL,
        "models_endpoint": "PASS",
        "reasoning_high": {
            "has_reasoning_content": bool(high_reasoning),
            "reasoning_field": (
                "reasoning_content" if high.get("reasoning_content") else "reasoning"
            ),
            "has_content": bool(high.get("content")),
            "reasoning_preview": preview(high_reasoning),
            "content": preview(high.get("content")),
        },
        "no_think": {
            "has_content": bool(no_think.get("content")),
            "has_reasoning_content": bool(no_think_reasoning),
            "content": preview(no_think.get("content")),
        },
        "streaming": {
            "status": "PASS",
            "chunks": stream["chunks"],
            "saw_done": stream["saw_done"],
            "content": preview(stream["content"]),
        },
        "tool_call": {"status": "PASS", "calls": tool_message.get("tool_calls")},
        "image_input_rejection": image_rejection,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False))
        raise
