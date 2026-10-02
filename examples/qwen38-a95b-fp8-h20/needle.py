#!/usr/bin/env python3
"""Needle-in-a-haystack correctness probe using the checkpoint tokenizer."""

from __future__ import annotations

import json
import os
from pathlib import Path
import urllib.request

from transformers import AutoTokenizer


BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:30000/v1").rstrip("/")
MODEL = os.getenv("MODEL", "qwen38-a95b-fp8")
TOKENIZER = os.getenv("TOKENIZER", "/models-nvme/Qwen3.8-2.4T-A95B-FP8/v1")
MAX_CONTEXT = int(os.getenv("MAX_CONTEXT", "32768"))
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "2048"))
TARGET_TOKENS = int(os.getenv("TARGET_TOKENS", str(MAX_CONTEXT - MAX_TOKENS - 64)))
DEPTH = float(os.getenv("DEPTH", "0.5"))
TIMEOUT = int(os.getenv("TIMEOUT", "3600"))
MARKER = os.getenv("MARKER", f"jade-{TARGET_TOKENS}-{int(DEPTH * 100)}-7319")
OUTPUT_FILE = os.getenv("OUTPUT_FILE")


def token_count(encoded) -> int:
    """Count IDs across Transformers list/Tensor/BatchEncoding return shapes."""
    if hasattr(encoded, "input_ids"):
        encoded = encoded.input_ids
    elif isinstance(encoded, dict):
        encoded = encoded["input_ids"]
    if hasattr(encoded, "tolist"):
        encoded = encoded.tolist()
    if encoded and isinstance(encoded[0], (list, tuple)):
        if len(encoded) != 1:
            raise ValueError("expected one rendered chat prompt")
        encoded = encoded[0]
    return len(encoded)


def main() -> int:
    if not 0.0 < DEPTH < 1.0:
        raise ValueError("DEPTH must be between 0 and 1")
    tokenizer = AutoTokenizer.from_pretrained(TOKENIZER, local_files_only=True)
    prefix = (
        "请阅读下面的记录，忽略其中重复的背景句。阅读完成后，只返回由 jade 开头的完整代号。\n"
    )
    needle = f"\n关键记录：需要找回的唯一代号是 {MARKER}。\n"
    suffix = "\n问题：需要找回的唯一代号是什么？只返回代号，不要解释。"
    filler_unit = "这是用于长上下文检索测试的普通背景记录，不包含目标答案。\n"

    fixed_ids = tokenizer.encode(prefix + needle + suffix, add_special_tokens=False)
    if TARGET_TOKENS <= len(fixed_ids) + 32:
        raise ValueError("TARGET_TOKENS is too small for the fixed prompt")
    filler_ids = tokenizer.encode(filler_unit, add_special_tokens=False)
    required_filler = TARGET_TOKENS - len(fixed_ids)
    repeated = (filler_ids * (required_filler // len(filler_ids) + 1))[:required_filler]
    split = int(len(repeated) * DEPTH)
    prompt_ids = (
        tokenizer.encode(prefix, add_special_tokens=False)
        + repeated[:split]
        + tokenizer.encode(needle, add_special_tokens=False)
        + repeated[split:]
        + tokenizer.encode(suffix, add_special_tokens=False)
    )
    prompt = tokenizer.decode(prompt_ids, skip_special_tokens=True)
    messages = [{"role": "user", "content": prompt}]
    # Count the re-encoded text and actual chat template, including generation
    # prefix. The raw filler token count alone understates API context usage.
    rendered_ids = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True)
    rendered_token_count = token_count(rendered_ids)
    if rendered_token_count + MAX_TOKENS > MAX_CONTEXT:
        raise ValueError(f"chat tokens {rendered_token_count} + output {MAX_TOKENS} exceed context {MAX_CONTEXT}")

    payload = {
        "model": MODEL,
        "messages": messages,
        "temperature": 0,
        "max_tokens": MAX_TOKENS,
        "reasoning_effort": "low",
    }
    req = urllib.request.Request(
        f"{BASE_URL}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": "Bearer EMPTY"},
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
        result = json.loads(response.read().decode("utf-8"))
    message = result["choices"][0]["message"]
    content = message.get("content") or ""
    passed = content.strip().strip('`"\'').lower() == MARKER.lower()
    output = {
        "status": "PASS" if passed else "FAIL",
        "model": MODEL,
        "target_tokens": TARGET_TOKENS,
        "actual_prompt_tokens": rendered_token_count,
        "raw_text_tokens": len(tokenizer.encode(prompt, add_special_tokens=False)),
        "max_context": MAX_CONTEXT,
        "max_output_tokens": MAX_TOKENS,
        "depth": DEPTH,
        "marker": MARKER,
        "content": content,
        "usage": result.get("usage"),
        "response": result,
    }
    rendered = json.dumps(output, ensure_ascii=False, indent=2)
    print(rendered)
    if OUTPUT_FILE:
        Path(OUTPUT_FILE).write_text(rendered + "\n", encoding="utf-8")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
