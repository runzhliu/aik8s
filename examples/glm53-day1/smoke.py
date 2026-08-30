#!/usr/bin/env python3
"""OpenAI-compatible correctness smoke for the text-only GLM-5.3 model."""

from __future__ import annotations

import json
import os
from typing import Optional
import urllib.error
import urllib.request


BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8000/v1").rstrip("/")
MODEL = os.getenv("MODEL", "glm-5.3")
TIMEOUT = int(os.getenv("TIMEOUT", "600"))


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
        "temperature": 1.0,
        "top_p": 0.95,
        "max_tokens": 512,
        "chat_template_kwargs": {
            "clear_thinking": True,
            "reasoning_effort": effort,
        },
    }
    payload.update(extra)
    return request("POST", "/chat/completions", payload)


def assistant_message(response: dict) -> dict:
    choices = response.get("choices") or []
    if not choices:
        raise AssertionError(f"response has no choices: {response}")
    return choices[0]["message"]


def streaming_smoke() -> dict:
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": "只回复 STREAM_OK"}],
        "stream": True,
        "temperature": 1.0,
        "max_tokens": 64,
        "chat_template_kwargs": {"clear_thinking": True, "reasoning_effort": "low"},
    }
    req = urllib.request.Request(
        f"{BASE_URL}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": "Bearer EMPTY"},
    )
    chunks = 0
    done = False
    with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
        for raw in response:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            body = line[5:].strip()
            if body == "[DONE]":
                done = True
                break
            json.loads(body)
            chunks += 1
    if not done or chunks == 0:
        raise AssertionError(f"invalid stream: chunks={chunks}, done={done}")
    return {"status": "PASS", "chunks": chunks}


def text_only_rejection() -> dict:
    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "描述这张图"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="},
                    },
                ],
            }
        ],
        "max_tokens": 32,
    }
    try:
        request("POST", "/chat/completions", payload)
    except RuntimeError as exc:
        return {"status": "PASS", "rejected": True, "error": str(exc)[:500]}
    raise AssertionError("text-only GLM-5.3 unexpectedly accepted image input")


def invalid_request_rejection() -> dict:
    try:
        request(
            "POST",
            "/chat/completions",
            {
                "model": MODEL,
                "messages": "this-must-be-a-list",
                "max_tokens": 8,
            },
        )
    except RuntimeError as exc:
        return {"status": "PASS", "rejected": True, "error": str(exc)[:500]}
    raise AssertionError("malformed messages payload was unexpectedly accepted")


def main() -> int:
    models = request("GET", "/models")
    advertised = [item.get("id") for item in models.get("data", [])]
    if MODEL not in advertised:
        raise AssertionError(f"{MODEL!r} not found in /v1/models: {advertised}")

    reasoning = {}
    for effort in ("low", "high", "max"):
        message = assistant_message(
            chat(
                [{"role": "user", "content": "计算 37×19，并给出最终算式与结果。"}],
                effort=effort,
            )
        )
        if not message.get("content"):
            raise AssertionError(f"empty final content for effort={effort}: {message}")
        reasoning_text = message.get("reasoning_content") or message.get("reasoning")
        if effort in {"high", "max"} and not reasoning_text:
            raise AssertionError(
                f"reasoning parser did not separate reasoning for effort={effort}: "
                f"{message}"
            )
        reasoning[effort] = {
            "status": "PASS",
            "reasoning_field": (
                "reasoning_content" if message.get("reasoning_content") else "reasoning"
            ) if reasoning_text else None,
            "has_reasoning": bool(reasoning_text),
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
        },
        {
            "type": "function",
            "function": {
                "name": "lookup_stock",
                "description": "查询股票价格",
                "parameters": {
                    "type": "object",
                    "properties": {"ticker": {"type": "string"}},
                    "required": ["ticker"],
                },
            },
        },
    ]
    tool_message = assistant_message(
        chat(
            [{"role": "user", "content": "调用工具查询杭州天气，不要自行编造。"}],
            tools=tools,
            tool_choice="auto",
        )
    )
    if not tool_message.get("tool_calls"):
        raise AssertionError(f"structured tool call missing: {tool_message}")
    first_call = tool_message["tool_calls"][0]
    function = first_call.get("function") or {}
    if function.get("name") != "get_weather":
        raise AssertionError(f"wrong tool selected: {tool_message}")
    raw_arguments = function.get("arguments") or "{}"
    arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
    city = str(arguments.get("city", "")).lower()
    if "杭州" not in city and "hangzhou" not in city:
        raise AssertionError(f"tool arguments do not contain Hangzhou: {tool_message}")

    first = assistant_message(chat([{"role": "user", "content": "记住数字 731。"}]))
    second = assistant_message(
        chat(
            [
                {"role": "user", "content": "记住数字 731。"},
                {"role": "assistant", "content": first.get("content") or ""},
                {"role": "user", "content": "刚才的数字是什么？只回答数字。"},
            ]
        )
    )
    if "731" not in (second.get("content") or ""):
        raise AssertionError(f"multi-turn memory failed: {second}")

    result = {
        "status": "PASS",
        "base_url": BASE_URL,
        "model": MODEL,
        "models_endpoint": "PASS",
        "streaming": streaming_smoke(),
        "reasoning_effort": reasoning,
        "tool_call": {"status": "PASS", "calls": tool_message.get("tool_calls")},
        "multi_turn": {"status": "PASS", "content": second.get("content")},
        "text_only_rejection": text_only_rejection(),
        "invalid_request_rejection": invalid_request_rejection(),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False, indent=2))
        raise
