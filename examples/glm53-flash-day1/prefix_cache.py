#!/usr/bin/env python3
"""Measure exact-repeat prefix-cache behavior with streaming TTFT."""

from __future__ import annotations

import json
import os
import statistics
import time
import urllib.request

from transformers import AutoTokenizer


BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:30000").rstrip("/")
MODEL = os.getenv("MODEL", "glm53-flash")
TOKENIZER = os.getenv("TOKENIZER", "/models/GLM-5.3-Flash")
ENGINE = os.getenv("ENGINE", "sglang").lower()
PROMPT_TOKENS = int(os.getenv("PROMPT_TOKENS", "4400"))
REPEATS = int(os.getenv("REPEATS", "5"))
TIMEOUT = int(os.getenv("TIMEOUT", "900"))
CACHE_SALT = os.getenv("CACHE_SALT")
FLUSH_PATH = os.getenv(
    "FLUSH_PATH", "/flush_cache" if ENGINE == "sglang" else "/reset_prefix_cache"
)


def request(path: str, payload: dict) -> bytes:
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": "Bearer EMPTY"},
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
        return response.read()


def flush_cache() -> None:
    body = request(FLUSH_PATH, {})
    if body:
        try:
            parsed = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            # SGLang may acknowledge cache reset with plain text.
            return
        if parsed.get("success") is False:
            raise RuntimeError(f"cache reset was rejected: {parsed}")


def metrics() -> list[str]:
    try:
        with urllib.request.urlopen(f"{BASE_URL}/metrics", timeout=30) as response:
            lines = response.read().decode("utf-8", errors="replace").splitlines()
    except Exception as exc:
        return [f"metrics unavailable: {exc}"]
    terms = ("prefix_cache", "cache_hit", "cache_query", "cache_hits")
    return [line for line in lines if not line.startswith("#") and any(term in line for term in terms)]


def build_prompt() -> tuple[str, int]:
    tokenizer = AutoTokenizer.from_pretrained(TOKENIZER, local_files_only=True)
    pattern = tokenizer.encode(
        "这是用于 Prefix Cache 精确重复实验的固定背景文本。\n",
        add_special_tokens=False,
    )
    ids = (pattern * ((PROMPT_TOKENS + len(pattern) - 1) // len(pattern)))[:PROMPT_TOKENS]
    prompt = tokenizer.decode(ids, skip_special_tokens=True, clean_up_tokenization_spaces=False)
    actual = len(tokenizer.encode(prompt, add_special_tokens=False))
    return prompt, actual


def stream_once(prompt: str) -> dict:
    if ENGINE == "vllm":
        # The GLM-5.3 preview build currently echoes the full prompt from the
        # Completions endpoint even when echo=false.  Chat streaming avoids
        # counting that prompt echo as the first generated token.
        endpoint = "/v1/chat/completions"
        payload = {
            "model": MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
            "temperature": 0,
            "max_tokens": 16,
            "reasoning_effort": "low",
        }
    else:
        endpoint = "/v1/completions"
        payload = {
            "model": MODEL,
            "prompt": prompt,
            "stream": True,
            "echo": False,
            "temperature": 0,
            "max_tokens": 16,
        }
    if CACHE_SALT:
        payload["cache_salt"] = CACHE_SALT
    req = urllib.request.Request(
        f"{BASE_URL}{endpoint}",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": "Bearer EMPTY"},
    )
    started = time.perf_counter()
    first_token = None
    chunks = []
    with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
        for raw_line in response:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            event = json.loads(data)
            choices = event.get("choices") or []
            if ENGINE == "vllm" and choices:
                delta = choices[0].get("delta") or {}
                text = delta.get("content") or delta.get("reasoning_content") or ""
            else:
                text = choices[0].get("text", "") if choices else ""
            if text and first_token is None:
                first_token = time.perf_counter()
            chunks.append(text)
    finished = time.perf_counter()
    output = "".join(chunks)
    return {
        "ttft_seconds": None if first_token is None else round(first_token - started, 6),
        "e2e_seconds": round(finished - started, 6),
        "output_preview": output[:200],
        "output_chars": len(output),
    }


def main() -> int:
    if ENGINE not in {"sglang", "vllm"}:
        raise ValueError("ENGINE must be sglang or vllm")
    prompt, actual_tokens = build_prompt()
    flush_cache()
    metrics_before = metrics()
    runs = []
    for index in range(REPEATS + 1):
        result = stream_once(prompt)
        result["kind"] = "cold" if index == 0 else "warm"
        result["repeat"] = index
        runs.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    metrics_after = metrics()
    cold = runs[0]["ttft_seconds"]
    warm_values = [item["ttft_seconds"] for item in runs[1:] if item["ttft_seconds"] is not None]
    summary = {
        "engine": ENGINE,
        "model": MODEL,
        "requested_prompt_tokens": PROMPT_TOKENS,
        "actual_prompt_tokens_local": actual_tokens,
        "cache_salt": CACHE_SALT,
        "cold_ttft_seconds": cold,
        "warm_ttft_median_seconds": statistics.median(warm_values) if warm_values else None,
        "runs": runs,
        "metrics_before": metrics_before,
        "metrics_after": metrics_after,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
