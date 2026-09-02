#!/usr/bin/env python3
"""OpenAI-compatible correctness smoke for moonshotai/Kimi-K3."""

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
MODEL = os.getenv("MODEL", "kimi-k3")
TIMEOUT = int(os.getenv("TIMEOUT", "900"))
REQUIRE_REASONING_CONTENT = os.getenv("REQUIRE_REASONING_CONTENT", "1") == "1"
REQUIRE_VISION = os.getenv("REQUIRE_VISION", "1") == "1"
REQUIRE_INVALID_IMAGE_4XX = os.getenv("REQUIRE_INVALID_IMAGE_4XX", "1") == "1"
IMAGE_URL = os.getenv("IMAGE_URL")
IMAGE_FILE = os.getenv("IMAGE_FILE")
IMAGE_QUESTION = os.getenv(
    "IMAGE_QUESTION", "请只用一句话描述图片中最主要的对象和颜色。"
)
IMAGE_EXPECTED_KEYWORD = os.getenv("IMAGE_EXPECTED_KEYWORD")


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


def expect_client_error(path: str, payload: dict) -> int:
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": "Bearer EMPTY"},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            body = response.read().decode("utf-8", errors="replace")
            raise AssertionError(
                f"invalid input unexpectedly returned HTTP {response.status}: {body}"
            )
    except urllib.error.HTTPError as exc:
        exc.read()
        if REQUIRE_INVALID_IMAGE_4XX and not 400 <= exc.code < 500:
            raise AssertionError(f"invalid input returned HTTP {exc.code}, expected 4xx")
        return exc.code


def stream_request(payload: dict) -> tuple[str, str]:
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
            # SGLang uses the de-facto `reasoning_content` extension while
            # vLLM's Rust frontend currently exposes the same trace as
            # `reasoning`. Accept and report both without weakening the check.
            reasoning_parts.append(
                delta.get("reasoning_content") or delta.get("reasoning") or ""
            )
    return "".join(content_parts), "".join(reasoning_parts)


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
        "max_tokens": 512,
    }
    payload.update(extra)
    return request("POST", "/chat/completions", payload)


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
    reasoning_trace = (
        math_message.get("reasoning_content") or math_message.get("reasoning") or ""
    )
    if REQUIRE_REASONING_CONTENT and not reasoning_trace:
        raise AssertionError(f"reasoning trace is missing: {math_message}")

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
            max_tokens=64,
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

    stream_content, stream_reasoning = stream_request(
        {
            "model": MODEL,
            "messages": [{"role": "user", "content": "用一句话解释什么是 Kubernetes。"}],
            "stream": True,
            "temperature": 0,
            # Kimi K3 emits the thinking trace before the final answer. 128
            # tokens can legitimately stop inside reasoning_content, so give
            # the stream the same completion budget as the non-stream checks.
            "max_tokens": 512,
        }
    )
    if not stream_content:
        raise AssertionError("streaming returned no final content")

    vision = None
    invalid_image_status = None
    if REQUIRE_VISION:
        image_url = IMAGE_URL
        if IMAGE_FILE:
            image_path = Path(IMAGE_FILE)
            mime_type = mimetypes.guess_type(image_path.name)[0] or "image/png"
            encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
            image_url = f"data:{mime_type};base64,{encoded}"
        if not image_url:
            raise RuntimeError(
                "IMAGE_URL or IMAGE_FILE is required when REQUIRE_VISION=1"
            )
        vision = assistant_message(
            chat(
                [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": IMAGE_QUESTION},
                            {"type": "image_url", "image_url": {"url": image_url}},
                        ],
                    }
                ],
                # Vision answers also emit a thinking trace first. Keep enough
                # headroom for both reasoning_content and the final sentence.
                max_tokens=512,
            )
        )
        vision_content = vision.get("content") or ""
        if not vision_content:
            raise AssertionError(f"vision returned no content: {vision}")
        if IMAGE_EXPECTED_KEYWORD and IMAGE_EXPECTED_KEYWORD.lower() not in vision_content.lower():
            raise AssertionError(
                f"vision result lacks expected keyword {IMAGE_EXPECTED_KEYWORD!r}: {vision_content}"
            )
        invalid_image_status = expect_client_error(
            "/chat/completions",
            {
                "model": MODEL,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "描述这张图片。"},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": "data:image/png;base64,not-a-valid-image"
                                },
                            },
                        ],
                    }
                ],
                "temperature": 0,
                "max_tokens": 32,
            },
        )

    invalid_image_warning = bool(invalid_image_status and invalid_image_status >= 500)
    result = {
        "status": "PASS_WITH_WARNINGS" if invalid_image_warning else "PASS",
        "model": MODEL,
        "models_endpoint": "PASS",
        "reasoning": {
            "has_reasoning_content": bool(math_message.get("reasoning_content")),
            "has_reasoning": bool(math_message.get("reasoning")),
            "reasoning_field": (
                "reasoning_content"
                if math_message.get("reasoning_content")
                else "reasoning"
            ),
            "reasoning_chars": len(reasoning_trace),
            "math_correct": True,
            "answer": math_message.get("content"),
        },
        "multi_turn": {"status": "PASS", "answer": second.get("content")},
        "tool_call": {"status": "PASS", "calls": tool_calls},
        "streaming": {
            "status": "PASS",
            "has_reasoning_content": bool(stream_reasoning),
            "answer": stream_content,
        },
        "vision": (
            {
                "status": "PASS",
                "answer": vision.get("content"),
                "invalid_image_http_status": invalid_image_status,
                "invalid_image_handling": (
                    "WARN_SERVER_ERROR" if invalid_image_warning else "PASS_CLIENT_ERROR"
                ),
            }
            if vision is not None
            else "SKIPPED"
        ),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False))
        raise
