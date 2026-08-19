#!/usr/bin/env python3
"""Run deterministic long-context needle retrieval against a chat endpoint."""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from transformers import AutoTokenizer


FILLER_UNIT = "背景记录：这是与最终问题无关的归档资料，请继续阅读。\n"


def parse_positions(raw: str) -> list[float]:
    positions = [float(item) for item in raw.split(",")]
    if not positions or any(position <= 0 or position >= 1 for position in positions):
        raise argparse.ArgumentTypeError("positions must be comma-separated values between 0 and 1")
    return positions


def messages_for(content: str) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": "你是长文档检索器。只根据文档回答，并且最终答案只输出检索密钥。",
        },
        {"role": "user", "content": content},
    ]


def token_count(tokenizer: Any, content: str) -> int:
    encoded = tokenizer.apply_chat_template(
        messages_for(content), tokenize=True, add_generation_prompt=True
    )
    token_ids = encoded.get("input_ids", encoded) if isinstance(encoded, Mapping) else encoded
    if token_ids and isinstance(token_ids[0], list):
        token_ids = token_ids[0]
    return len(token_ids)


def build_content(
    tokenizer: Any,
    target_tokens: int,
    position: float,
    secret: str,
) -> tuple[str, int]:
    unit_tokens = max(1, len(tokenizer.encode(FILLER_UNIT, add_special_tokens=False)))
    units = max(1, target_tokens // unit_tokens)

    def render(unit_count: int) -> str:
        split = max(1, min(unit_count - 1, round(unit_count * position)))
        return (
            "下面是一份很长的归档文档。\n"
            + FILLER_UNIT * split
            + f"\n唯一检索密钥：{secret}\n"
            + FILLER_UNIT * (unit_count - split)
            + "\n问题：文档中的唯一检索密钥是什么？只输出密钥。"
        )

    content = render(units)
    actual = token_count(tokenizer, content)
    for _ in range(8):
        delta = target_tokens - actual
        if abs(delta) <= unit_tokens:
            break
        units = max(2, units + round(delta / unit_tokens))
        content = render(units)
        actual = token_count(tokenizer, content)
    if actual > target_tokens:
        units = max(2, units - 1)
        content = render(units)
        actual = token_count(tokenizer, content)
    return content, actual


def post_json(url: str, body: dict[str, Any], headers: dict[str, str], timeout: int) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--tokenizer", required=True)
    parser.add_argument("--target-input-tokens", type=int, default=130048)
    parser.add_argument("--positions", type=parse_positions, default=parse_positions("0.1,0.5,0.9"))
    parser.add_argument("--max-tokens", type=int, default=128)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--header", action="append", default=[], metavar="KEY=VALUE")
    parser.add_argument("--trust-remote-code", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    headers: dict[str, str] = {}
    for item in args.header:
        if "=" not in item:
            parser.error("--header must use KEY=VALUE")
        key, value = item.split("=", 1)
        headers[key] = value

    tokenizer = AutoTokenizer.from_pretrained(
        args.tokenizer,
        trust_remote_code=args.trust_remote_code,
        local_files_only=True,
    )
    endpoint = args.base_url.rstrip("/") + "/v1/chat/completions"
    results: list[dict[str, Any]] = []
    for index, position in enumerate(args.positions, start=1):
        secret = f"QWEN128K-P{round(position * 100):02d}-S{index}-739184"
        content, actual_tokens = build_content(
            tokenizer, args.target_input_tokens, position, secret
        )
        body = {
            "model": args.model,
            "messages": messages_for(content),
            "temperature": 0,
            "max_tokens": args.max_tokens,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        started = time.perf_counter()
        try:
            response = post_json(endpoint, body, headers, args.timeout)
            elapsed = time.perf_counter() - started
            choice = response.get("choices", [{}])[0]
            message = choice.get("message", {})
            content_out = message.get("content") or ""
            reasoning_out = message.get("reasoning_content") or ""
            passed = secret in content_out or secret in reasoning_out
            result = {
                "position": position,
                "secret": secret,
                "target_input_tokens": args.target_input_tokens,
                "local_input_tokens": actual_tokens,
                "server_prompt_tokens": response.get("usage", {}).get("prompt_tokens"),
                "completion_tokens": response.get("usage", {}).get("completion_tokens"),
                "elapsed_seconds": elapsed,
                "passed": passed,
                "response": content_out[:500],
                "reasoning": reasoning_out[:500],
                "error": None,
            }
        except Exception as exc:  # Record every failed position instead of hiding it.
            result = {
                "position": position,
                "secret": secret,
                "target_input_tokens": args.target_input_tokens,
                "local_input_tokens": actual_tokens,
                "server_prompt_tokens": None,
                "completion_tokens": None,
                "elapsed_seconds": time.perf_counter() - started,
                "passed": False,
                "response": "",
                "reasoning": "",
                "error": str(exc),
            }
        results.append(result)
        print(json.dumps(result, ensure_ascii=False))

    report = {
        "model": args.model,
        "target_input_tokens": args.target_input_tokens,
        "passed": sum(bool(result["passed"]) for result in results),
        "total": len(results),
        "results": results,
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"passed={report['passed']}/{report['total']}")
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
