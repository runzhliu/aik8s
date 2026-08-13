#!/usr/bin/env python3
"""Replay a long shared prefix before and after cache-pressure requests."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import statistics
import time
import urllib.request


UNIT = (
    "Kubernetes schedules GPU inference services. Prefix caching avoids repeated "
    "prefill work for long agent contexts. Keep this shared context unchanged. "
)


def request(
    endpoint: str,
    model: str,
    prompt: str,
    max_tokens: int,
    api: str,
) -> dict[str, float | int | str]:
    payload_data: dict[str, object] = {
        "model": model,
        "temperature": 0,
        "seed": 0,
        "max_tokens": max_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if api == "chat":
        payload_data["messages"] = [{"role": "user", "content": prompt}]
        api_path = "/v1/chat/completions"
    else:
        payload_data["prompt"] = prompt
        api_path = "/v1/completions"
    payload = json.dumps(payload_data).encode()
    req = urllib.request.Request(
        endpoint.rstrip("/") + api_path,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    first_token = None
    completion_parts: list[str] = []
    usage: dict[str, int] = {}
    with urllib.request.urlopen(req, timeout=900) as response:
        for raw_line in response:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line.startswith("data: ") or line == "data: [DONE]":
                continue
            item = json.loads(line[6:])
            choices = item.get("choices") or []
            choice = choices[0] if choices else {}
            if api == "chat":
                delta = choice.get("delta") or {}
                text = delta.get("content") or ""
            else:
                text = choice.get("text", "")
            if text and first_token is None:
                first_token = time.perf_counter()
            completion_parts.append(text)
            if item.get("usage"):
                usage = item["usage"]
    finished = time.perf_counter()
    return {
        "ttft_ms": ((first_token or finished) - started) * 1000,
        "e2e_ms": (finished - started) * 1000,
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
        "output_sha256": hashlib.sha256("".join(completion_parts).encode()).hexdigest(),
        "output_text": "".join(completion_parts),
    }


def summarize(name: str, rows: list[dict[str, float | int | str]]) -> None:
    ttft = sorted(float(row["ttft_ms"]) for row in rows)
    e2e = sorted(float(row["e2e_ms"]) for row in rows)
    p95_index = max(0, min(len(rows) - 1, int(len(rows) * 0.95) - 1))
    print(
        json.dumps(
            {
                "phase": name,
                "requests": len(rows),
                "prompt_tokens": rows[0]["prompt_tokens"] if rows else 0,
                "ttft_mean_ms": round(statistics.mean(ttft), 2),
                "ttft_p95_ms": round(ttft[p95_index], 2),
                "e2e_mean_ms": round(statistics.mean(e2e), 2),
                "e2e_p95_ms": round(e2e[p95_index], 2),
                "output_sha256": sorted({str(row["output_sha256"]) for row in rows}),
                "output_preview": sorted({str(row["output_text"])[:160] for row in rows}),
            },
            ensure_ascii=False,
        )
    )


def reset_local_prefix_cache(endpoint: str) -> None:
    """Reset vLLM's local prefix cache while preserving the external cache."""
    req = urllib.request.Request(
        endpoint.rstrip("/") + "/reset_prefix_cache?reset_external=false",
        data=b"",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        result = json.load(response)
    if not result.get("success"):
        raise RuntimeError(f"local prefix cache reset failed: {result}")
    print(json.dumps({"phase": "local_prefix_cache_reset", "success": True}))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", default="http://127.0.0.1:8000")
    parser.add_argument("--model", default="deepseek-v4-flash-lmcache-ab")
    parser.add_argument("--api", choices=("chat", "completions"), default="chat")
    parser.add_argument("--prefix-chars", type=int, default=64000)
    parser.add_argument("--max-tokens", type=int, default=32)
    parser.add_argument("--warm-replays", type=int, default=8)
    parser.add_argument("--eviction-prompts", type=int, default=128)
    parser.add_argument("--eviction-concurrency", type=int, default=4)
    parser.add_argument(
        "--reset-local-prefix-cache",
        action="store_true",
        help=(
            "use vLLM's development endpoint to clear only the local GPU prefix "
            "cache; requires VLLM_SERVER_DEV_MODE=1"
        ),
    )
    parser.add_argument("--cache-settle-seconds", type=float, default=2.0)
    args = parser.parse_args()

    shared_prefix = (UNIT * ((args.prefix_chars // len(UNIT)) + 1))[: args.prefix_chars]
    target_prompt = (
        shared_prefix
        + "\nIgnore the preceding context. Reply with exactly CACHE_OK and nothing else."
    )

    cold = [request(args.endpoint, args.model, target_prompt, args.max_tokens, args.api)]
    summarize("target_cold", cold)

    warm = [
        request(args.endpoint, args.model, target_prompt, args.max_tokens, args.api)
        for _ in range(args.warm_replays)
    ]
    summarize("target_gpu_warm", warm)

    if args.reset_local_prefix_cache:
        time.sleep(args.cache_settle_seconds)
        reset_local_prefix_cache(args.endpoint)
    elif args.eviction_prompts > 0:
        def fill(index: int) -> dict[str, float | int | str]:
            unique = f"Cache pressure stream {index}: "
            filler = (unique * ((args.prefix_chars // len(unique)) + 1))[: args.prefix_chars]
            return request(args.endpoint, args.model, filler, 1, args.api)

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=args.eviction_concurrency
        ) as pool:
            pressure = list(pool.map(fill, range(args.eviction_prompts)))
        summarize("cache_pressure", pressure)

    replay = [request(args.endpoint, args.model, target_prompt, args.max_tokens, args.api)]
    replay_phase = (
        "target_after_local_reset"
        if args.reset_local_prefix_cache
        else "target_after_pressure"
    )
    summarize(replay_phase, replay)

    target_hashes = {
        str(row["output_sha256"])
        for row in cold + warm + replay
    }
    if len(target_hashes) != 1:
        raise SystemExit(
            "FAIL: deterministic target output changed across cold/warm/reload phases: "
            + ", ".join(sorted(target_hashes))
        )
    print(json.dumps({"correctness": "PASS", "target_output_sha256": target_hashes.pop()}))


if __name__ == "__main__":
    main()
