#!/usr/bin/env python3
"""Measure exact-repeat GLM-5.3 prefix-cache behavior with streaming TTFT."""

from __future__ import annotations

import json
import os
import statistics
import time
import urllib.error
import urllib.request

from transformers import AutoTokenizer


BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8000").rstrip("/")
MODEL = os.getenv("MODEL", "glm-5.3")
TOKENIZER = os.getenv("TOKENIZER", "/models/GLM-5.3/v1")
ENGINE = os.getenv("ENGINE", "vllm").lower()
PREFIX_LENGTHS = [
    int(item) for item in os.getenv("PREFIX_LENGTHS", "4096,32768").split(",")
]
REPEATS = int(os.getenv("REPEATS", "5"))
TIMEOUT = int(os.getenv("TIMEOUT", "1200"))
FLUSH_PATH = os.getenv(
    "FLUSH_PATH", "/flush_cache" if ENGINE == "sglang" else "/reset_prefix_cache"
)


def post(path: str, payload: dict) -> bytes:
    request = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": "Bearer EMPTY"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} {path}: {body}") from exc


def flush_cache() -> None:
    body = post(FLUSH_PATH, {})
    if not body:
        return
    try:
        parsed = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        return
    if parsed.get("success") is False:
        raise RuntimeError(f"cache reset was rejected: {parsed}")


def cache_metrics() -> list[str]:
    try:
        with urllib.request.urlopen(f"{BASE_URL}/metrics", timeout=30) as response:
            lines = response.read().decode("utf-8", errors="replace").splitlines()
    except Exception as exc:
        return [f"metrics unavailable: {exc}"]
    terms = ("prefix_cache", "cache_hit", "cache_query", "cache_hits", "cached_tokens")
    return [
        line
        for line in lines
        if not line.startswith("#") and any(term in line.lower() for term in terms)
    ]


def repeat_tokens(pattern: list[int], length: int) -> list[int]:
    if not pattern:
        raise ValueError("prefix token pattern is empty")
    return (pattern * ((length + len(pattern) - 1) // len(pattern)))[:length]


def build_prefix(tokenizer: AutoTokenizer, requested_tokens: int) -> tuple[str, int]:
    salt = f"PREFIX-CACHE-GLM53-{requested_tokens}-20260830\n"
    salt_ids = tokenizer.encode(salt, add_special_tokens=False)
    pattern = tokenizer.encode(
        "这是 Prefix Cache 重复实验的固定背景材料；内容本身与答案无关。\n",
        add_special_tokens=False,
    )
    ids = salt_ids + repeat_tokens(pattern, max(1, requested_tokens - len(salt_ids)))
    prompt = tokenizer.decode(
        ids[:requested_tokens],
        skip_special_tokens=True,
        clean_up_tokenization_spaces=False,
    )
    actual = len(tokenizer.encode(prompt, add_special_tokens=False))
    return prompt, actual


def stream_once(prefix: str, run: int) -> dict:
    marker = f"CACHE_OK_{run}"
    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "user",
                "content": f"{prefix}\n只回复 {marker}，不要解释。",
            }
        ],
        "stream": True,
        "temperature": 0,
        "max_tokens": 128,
        "chat_template_kwargs": {
            "clear_thinking": True,
            "reasoning_effort": "low",
        },
    }
    request = urllib.request.Request(
        f"{BASE_URL}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": "Bearer EMPTY"},
    )
    started = time.perf_counter()
    first_token = None
    chunks: list[str] = []
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        for raw_line in response:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            event = json.loads(data)
            choices = event.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            text = delta.get("reasoning_content") or delta.get("content") or ""
            if text and first_token is None:
                first_token = time.perf_counter()
            chunks.append(text)
    finished = time.perf_counter()
    output = "".join(chunks)
    return {
        "ttft_seconds": None if first_token is None else round(first_token - started, 6),
        "e2e_seconds": round(finished - started, 6),
        "expected_marker": marker,
        "marker_found": marker in output,
        "output_preview": output[:200],
        "output_chars": len(output),
    }


def main() -> int:
    if ENGINE not in {"sglang", "vllm"}:
        raise ValueError("ENGINE must be sglang or vllm")
    if not PREFIX_LENGTHS or any(length <= 0 for length in PREFIX_LENGTHS):
        raise ValueError("PREFIX_LENGTHS must contain positive integers")
    if REPEATS <= 0:
        raise ValueError("REPEATS must be positive")

    tokenizer = AutoTokenizer.from_pretrained(TOKENIZER, local_files_only=True)
    experiments = []
    for requested_tokens in PREFIX_LENGTHS:
        prefix, actual_tokens = build_prefix(tokenizer, requested_tokens)
        flush_cache()
        before = cache_metrics()
        runs = []
        for index in range(REPEATS + 1):
            result = stream_once(prefix, index)
            result["kind"] = "cold" if index == 0 else "warm"
            result["repeat"] = index
            runs.append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
        after = cache_metrics()
        warm_ttft = [
            item["ttft_seconds"]
            for item in runs[1:]
            if item["ttft_seconds"] is not None
        ]
        experiments.append(
            {
                "requested_prefix_tokens": requested_tokens,
                "actual_prefix_tokens_local": actual_tokens,
                "cold_ttft_seconds": runs[0]["ttft_seconds"],
                "warm_ttft_median_seconds": (
                    statistics.median(warm_ttft) if warm_ttft else None
                ),
                "all_markers_found": all(item["marker_found"] for item in runs),
                "runs": runs,
                "metrics_before": before,
                "metrics_after": after,
            }
        )

    summary = {
        "engine": ENGINE,
        "model": MODEL,
        "prefix_lengths": PREFIX_LENGTHS,
        "warm_repeats": REPEATS,
        "experiments": experiments,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if all(item["all_markers_found"] for item in experiments) else 1


if __name__ == "__main__":
    raise SystemExit(main())
