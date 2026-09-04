#!/usr/bin/env python3
"""OpenAI-compatible correctness smoke for Qwen3.8-2.4T-A95B-FP8."""

from __future__ import annotations

import json
import os
from typing import Optional
import urllib.error
import urllib.request


BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:30000/v1").rstrip("/")
MODEL = os.getenv("MODEL", "qwen38-a95b-fp8")
TIMEOUT = int(os.getenv("TIMEOUT", "1800"))


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


def chat(messages: list[dict], **extra: object) -> dict:
    payload = {
        "model": MODEL,
        "messages": messages,
        "stream": False,
        "temperature": 0,
        "max_tokens": 1024,
    }
    payload.update(extra)
    return request("POST", "/chat/completions", payload)


def reasoning_text(message: dict) -> str:
    return message.get("reasoning_content") or message.get("reasoning") or ""


def stream_chat() -> tuple[str, str]:
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": "用一句话解释什么是 Kubernetes。"}],
        "stream": True,
        "temperature": 0,
        "max_tokens": 1024,
    }
    req = urllib.request.Request(
        f"{BASE_URL}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": "Bearer EMPTY"},
    )
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
        for raw in response:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line.startswith("data: ") or line == "data: [DONE]":
                continue
            event = json.loads(line[6:])
            choices = event.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            content_parts.append(delta.get("content") or "")
            reasoning_parts.append(
                delta.get("reasoning_content") or delta.get("reasoning") or ""
            )
    return "".join(content_parts), "".join(reasoning_parts)


def main() -> int:
    models = request("GET", "/models")
    advertised = [item.get("id") for item in models.get("data", [])]
    if MODEL not in advertised:
        raise AssertionError(f"{MODEL!r} not found in /v1/models: {advertised}")

    math_message = assistant_message(
        chat([{"role": "user", "content": "计算 37×19，最终答案必须包含 703。"}])
    )
    if "703" not in (math_message.get("content") or ""):
        raise AssertionError(f"deterministic math result is wrong: {math_message}")
    if not reasoning_text(math_message):
        raise AssertionError(f"reasoning trace is missing: {math_message}")
    if "<think>" in (math_message.get("content") or ""):
        raise AssertionError(f"raw thinking leaked into final content: {math_message}")

    effort_results = {}
    for effort in ("low", "medium", "xhigh"):
        message = assistant_message(
            chat(
                [{"role": "user", "content": "只回答：12 的平方是多少？"}],
                reasoning_effort=effort,
                max_tokens=1024,
            )
        )
        if "144" not in (message.get("content") or ""):
            raise AssertionError(f"reasoning_effort={effort} returned wrong answer: {message}")
        effort_results[effort] = {
            "content": message.get("content"),
            "has_reasoning": bool(reasoning_text(message)),
        }

    first = assistant_message(
        chat([{"role": "user", "content": "记住代号 amber-417，只回复已记住。"}])
    )
    second = assistant_message(
        chat(
            [
                {"role": "user", "content": "记住代号 amber-417，只回复已记住。"},
                first,
                {"role": "user", "content": "刚才的代号是什么？只回复代号。"},
            ],
            max_tokens=256,
        )
    )
    if "amber-417" not in (second.get("content") or "").lower():
        raise AssertionError(f"multi-turn memory result is wrong: {second}")

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
                        "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]},
                    },
                    "required": ["city", "unit"],
                },
            },
        }
    ]
    tool_message = assistant_message(
        chat(
            [{"role": "user", "content": "调用工具查询北京天气，单位用摄氏度。"}],
            tools=tools,
            tool_choice="auto",
        )
    )
    tool_calls = tool_message.get("tool_calls") or []
    if not tool_calls:
        raise AssertionError(f"structured tool call missing: {tool_message}")
    arguments = tool_calls[0].get("function", {}).get("arguments")
    if isinstance(arguments, str):
        arguments = json.loads(arguments)
    if not isinstance(arguments, dict) or "北京" not in str(arguments.get("city")):
        raise AssertionError(f"tool arguments are invalid: {arguments}")

    stream_content, stream_reasoning = stream_chat()
    if not stream_content or not stream_reasoning:
        raise AssertionError("streaming did not return both reasoning and final content")

    result = {
        "status": "PASS",
        "model": MODEL,
        "models_endpoint": "PASS",
        "math": {"content": math_message.get("content"), "has_reasoning": True},
        "reasoning_effort": effort_results,
        "multi_turn": second.get("content"),
        "tool_call": tool_calls[0],
        "streaming": {
            "content_chars": len(stream_content),
            "reasoning_chars": len(stream_reasoning),
        },
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
