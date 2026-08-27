#!/usr/bin/env python3
"""Needle-in-a-haystack smoke for an OpenAI-compatible long-context model."""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request

from transformers import AutoTokenizer


BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:30000/v1").rstrip("/")
SERVER_URL = BASE_URL[:-3] if BASE_URL.endswith("/v1") else BASE_URL
MODEL = os.getenv("MODEL", "qwen38-flash-next")
TOKENIZER = os.getenv("TOKENIZER", "/models/Qwen3.8-Flash-Next-FP8")
LENGTHS = [int(item) for item in os.getenv("LENGTHS", "32768,131072,250000").split(",")]
POSITIONS = [float(item) for item in os.getenv("POSITIONS", "0.1,0.5,0.9").split(",")]
TIMEOUT = int(os.getenv("TIMEOUT", "900"))
FLUSH_CACHE = os.getenv("FLUSH_CACHE", "1") == "1"


def post(path: str, payload: dict) -> dict:
    request = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer EMPTY",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc


def flush_cache() -> None:
    request = urllib.request.Request(
        f"{SERVER_URL}/flush_cache",
        data=b"{}",
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        response.read()


def repeat_tokens(pattern: list[int], length: int) -> list[int]:
    if not pattern:
        raise ValueError("filler token pattern is empty")
    return (pattern * ((length + len(pattern) - 1) // len(pattern)))[:length]


def normalize(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def rendered_token_count(rendered: object) -> int:
    """Handle list, BatchEncoding/dict and tensor chat-template results."""
    if isinstance(rendered, dict):
        rendered = rendered["input_ids"]
    elif hasattr(rendered, "input_ids"):
        rendered = rendered.input_ids
    if hasattr(rendered, "shape"):
        return int(rendered.shape[-1])
    if isinstance(rendered, list) and rendered and isinstance(rendered[0], list):
        return len(rendered[0])
    return len(rendered)  # type: ignore[arg-type]


def build_messages(tokenizer: AutoTokenizer, target: int, position: float, needle: str):
    filler_text = "这是长上下文检索实验的普通背景材料，与最终答案无关。\n"
    filler_pattern = tokenizer.encode(filler_text, add_special_tokens=False)
    needle_ids = tokenizer.encode(
        f"\n重要记录：本次实验的唯一密钥是 {needle}。请记住这条记录。\n",
        add_special_tokens=False,
    )
    question = "请找出上文唯一的实验密钥，只输出密钥，不要解释。"

    # Leave room for the chat template and final question, then correct the
    # content budget against the tokenizer's actual rendered prompt length.
    filler_length = max(1, target - len(needle_ids) - 192)
    messages = []
    actual = 0
    for _ in range(4):
        split = min(filler_length, max(0, int(filler_length * position)))
        filler_ids = repeat_tokens(filler_pattern, filler_length)
        content_ids = filler_ids[:split] + needle_ids + filler_ids[split:]
        content = tokenizer.decode(content_ids, skip_special_tokens=True)
        messages = [{"role": "user", "content": f"{content}\n\n{question}"}]
        rendered = tokenizer.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=True,
            enable_thinking=False,
        )
        actual = rendered_token_count(rendered)
        filler_length = max(1, filler_length + target - actual)
        if abs(target - actual) <= 8:
            break
    return messages, actual


def main() -> int:
    tokenizer = AutoTokenizer.from_pretrained(TOKENIZER, local_files_only=True)
    results = []

    for target in LENGTHS:
        for position in POSITIONS:
            label = int(round(position * 100))
            needle = f"ORCHID-{target}-{label}"
            messages, actual_prompt_tokens = build_messages(
                tokenizer, target, position, needle
            )
            if FLUSH_CACHE:
                flush_cache()
            started = time.perf_counter()
            try:
                response = post(
                    "/chat/completions",
                    {
                        "model": MODEL,
                        "messages": messages,
                        "stream": False,
                        "temperature": 0,
                        "max_tokens": 32,
                        "chat_template_kwargs": {"enable_thinking": False},
                    },
                )
                message = response["choices"][0]["message"]
                answer = message.get("content") or ""
                passed = normalize(needle) in normalize(answer)
                error = None
                usage = response.get("usage") or {}
            except Exception as exc:  # Keep the complete matrix observable.
                answer = ""
                passed = False
                error = str(exc)
                usage = {}
            item = {
                "target_tokens": target,
                "actual_prompt_tokens_local": actual_prompt_tokens,
                "server_prompt_tokens": usage.get("prompt_tokens"),
                "needle_position_percent": label,
                "needle": needle,
                "cache_flushed": FLUSH_CACHE,
                "passed": passed,
                "elapsed_seconds": round(time.perf_counter() - started, 3),
                "answer": answer,
                "error": error,
            }
            results.append(item)
            print(json.dumps(item, ensure_ascii=False), flush=True)

    summary = {
        "model": MODEL,
        "lengths": LENGTHS,
        "positions": POSITIONS,
        "passed": sum(item["passed"] for item in results),
        "total": len(results),
        "results": results,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["passed"] == summary["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
