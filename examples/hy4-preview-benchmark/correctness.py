#!/usr/bin/env python3
"""Needle-in-a-haystack and multi-turn tool-agent checks for Hy4-preview."""

from __future__ import annotations

import json
import os
import time
from typing import Any, Optional
import urllib.error
import urllib.request

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:30000/v1").rstrip("/")
MODEL = os.getenv("MODEL", "hy4-preview")
ENGINE = os.getenv("ENGINE", "unknown")
TIMEOUT = int(os.getenv("TIMEOUT", "1800"))
CONTEXT_LENGTHS = [
    int(value) for value in os.getenv("CONTEXT_LENGTHS", "32768,65536,126000").split(",")
]
DEPTHS = [float(value) for value in os.getenv("DEPTHS", "0.1,0.5,0.9").split(",")]


def request(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=data,
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": "Bearer EMPTY"},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} {path}: {body[:800]}") from exc


def assistant_message(response: dict[str, Any]) -> dict[str, Any]:
    choices = response.get("choices") or []
    if not choices:
        raise AssertionError(f"response has no choices: {response}")
    return choices[0]["message"]


def chat(messages: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": MODEL,
        "messages": messages,
        "stream": False,
        "temperature": 0,
        "top_p": 1,
        "max_tokens": 128,
        "chat_template_kwargs": {"reasoning_effort": "no_think"},
    }
    payload.update(extra)
    return request("/chat/completions", payload)


def compose_needle_prompt(
    records: int,
    depth: float,
    needle: str,
) -> str:
    header = (
        "请阅读下面的长档案。绝大多数条目都与问题无关，但其中只有一条包含目标密钥。"
        "不要根据常识猜测，也不要输出解释。\n"
    )
    needle_line = f"【关键档案】本次测试唯一目标密钥是：{needle}。\n"
    question = f"\n问题：目标密钥是什么？只输出 {needle}，不得添加其他文字。"

    record_lines = [
            f"普通档案 {index:06d}：海港仓库按常规流程完成巡检，本条不含目标密钥。\n"
            for index in range(records)
    ]
    insertion = min(records, max(0, round(records * depth)))
    record_lines.insert(insertion, needle_line)
    return header + "".join(record_lines) + question


def usage_prompt_tokens(response: dict[str, Any]) -> int:
    usage = response.get("usage") or {}
    count = usage.get("prompt_tokens")
    if not isinstance(count, int) or count <= 0:
        raise AssertionError(f"server did not return prompt_tokens usage: {usage}")
    return count


def calibrate_record_cost() -> tuple[int, float]:
    needle = "HY4-CALIBRATION-NIAH"
    empty_response = chat(
        [{"role": "user", "content": compose_needle_prompt(0, 0.5, needle)}],
        max_tokens=1,
    )
    sample_records = 200
    sample_response = chat(
        [
            {
                "role": "user",
                "content": compose_needle_prompt(sample_records, 0.5, needle),
            }
        ],
        max_tokens=1,
    )
    base_tokens = usage_prompt_tokens(empty_response)
    sample_tokens = usage_prompt_tokens(sample_response)
    tokens_per_record = (sample_tokens - base_tokens) / sample_records
    if tokens_per_record <= 0:
        raise AssertionError(
            f"invalid server tokenizer calibration: base={base_tokens}, sample={sample_tokens}"
        )
    print(
        "TOKEN_CALIBRATION "
        + json.dumps(
            {
                "base_tokens": base_tokens,
                "sample_records": sample_records,
                "sample_tokens": sample_tokens,
                "tokens_per_record": round(tokens_per_record, 4),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return base_tokens, tokens_per_record


def run_needle() -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    base_tokens, tokens_per_record = calibrate_record_cost()
    for target_tokens in CONTEXT_LENGTHS:
        for depth in DEPTHS:
            depth_percent = round(depth * 100)
            needle = f"HY4-{ENGINE.upper()}-{target_tokens}-{depth_percent}-NIAH"
            records = max(
                0,
                int((target_tokens - base_tokens - 256) / tokens_per_record),
            )
            prompt = compose_needle_prompt(records, depth, needle)
            started = time.monotonic()
            response = chat([{"role": "user", "content": prompt}], max_tokens=64)
            message = assistant_message(response)
            elapsed = time.monotonic() - started
            input_tokens = usage_prompt_tokens(response)
            content = str(message.get("content") or "").strip()
            passed = needle in content
            result = {
                "target_tokens": target_tokens,
                "input_tokens": input_tokens,
                "depth_percent": depth_percent,
                "records": records,
                "needle": needle,
                "response": content[:240],
                "elapsed_seconds": round(elapsed, 3),
                "status": "PASS" if passed else "FAIL",
            }
            print("NIAH_RESULT " + json.dumps(result, ensure_ascii=False), flush=True)
            results.append(result)
    return results


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "lookup_inventory",
            "description": "查询指定 SKU 的可用库存",
            "parameters": {
                "type": "object",
                "properties": {"sku": {"type": "string"}},
                "required": ["sku"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_shipping",
            "description": "计算商品运到指定城市的运费和预计天数",
            "parameters": {
                "type": "object",
                "properties": {
                    "sku": {"type": "string"},
                    "quantity": {"type": "integer"},
                    "city": {"type": "string"},
                },
                "required": ["sku", "quantity", "city"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reserve_inventory",
            "description": "为客户预留指定数量的库存",
            "parameters": {
                "type": "object",
                "properties": {
                    "sku": {"type": "string"},
                    "quantity": {"type": "integer"},
                    "customer": {"type": "string"},
                },
                "required": ["sku", "quantity", "customer"],
            },
        },
    },
]


def tool_step(
    messages: list[dict[str, Any]],
    expected_name: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    response = assistant_message(chat(messages, tools=TOOLS, tool_choice="auto", max_tokens=256))
    calls = response.get("tool_calls") or []
    matching = [call for call in calls if (call.get("function") or {}).get("name") == expected_name]
    if not matching:
        raise AssertionError(f"expected tool {expected_name}, got: {calls}")
    call = matching[0]
    arguments = json.loads((call.get("function") or {}).get("arguments") or "{}")
    assistant_history = {
        "role": "assistant",
        "content": response.get("content"),
        "tool_calls": calls,
    }
    return call, {"arguments": arguments, "assistant": assistant_history}


def run_agent() -> dict[str, Any]:
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": "你是采购 Agent。严格按用户要求逐步调用工具，不得编造工具结果。",
        },
        {
            "role": "user",
            "content": "北京客户 north-lab 要采购 SKU HY4-NVME-A 共 3 个。先查询库存。",
        },
    ]

    inventory_call, inventory = tool_step(messages, "lookup_inventory")
    if inventory["arguments"].get("sku") != "HY4-NVME-A":
        raise AssertionError(f"inventory arguments incorrect: {inventory}")
    messages.extend(
        [
            inventory["assistant"],
            {
                "role": "tool",
                "tool_call_id": inventory_call["id"],
                "content": json.dumps({"sku": "HY4-NVME-A", "available": 7}),
            },
            {
                "role": "user",
                "content": "库存足够。继续计算 3 个商品运到北京的运费，必须调用运输工具。",
            },
        ]
    )

    shipping_call, shipping = tool_step(messages, "calculate_shipping")
    expected_shipping = {"sku": "HY4-NVME-A", "quantity": 3, "city": "北京"}
    if any(shipping["arguments"].get(key) != value for key, value in expected_shipping.items()):
        raise AssertionError(f"shipping arguments incorrect: {shipping}")
    messages.extend(
        [
            shipping["assistant"],
            {
                "role": "tool",
                "tool_call_id": shipping_call["id"],
                "content": json.dumps({"shipping_cost": 42, "eta_days": 2}),
            },
            {
                "role": "user",
                "content": "库存和运费可接受。现在为 north-lab 预留 3 个，必须调用预留工具。",
            },
        ]
    )

    reserve_call, reserve = tool_step(messages, "reserve_inventory")
    expected_reserve = {"sku": "HY4-NVME-A", "quantity": 3, "customer": "north-lab"}
    if any(reserve["arguments"].get(key) != value for key, value in expected_reserve.items()):
        raise AssertionError(f"reserve arguments incorrect: {reserve}")
    messages.extend(
        [
            reserve["assistant"],
            {
                "role": "tool",
                "tool_call_id": reserve_call["id"],
                "content": json.dumps(
                    {"reservation_id": "RSV-HY4-20260901", "status": "reserved"}
                ),
            },
            {
                "role": "user",
                "content": (
                    "给出最终摘要，必须包含 SKU、数量、客户、剩余库存、运费、到货天数和预留单号。"
                ),
            },
        ]
    )
    final = assistant_message(chat(messages, tools=TOOLS, tool_choice="none", max_tokens=256))
    content = str(final.get("content") or "")
    required = ["HY4-NVME-A", "3", "north-lab", "4", "42", "2", "RSV-HY4-20260901"]
    missing = [value for value in required if value not in content]
    if missing:
        raise AssertionError(f"agent summary missing {missing}: {content}")
    result = {
        "status": "PASS",
        "steps": ["lookup_inventory", "calculate_shipping", "reserve_inventory", "summary"],
        "summary": content[:600],
    }
    print("AGENT_RESULT " + json.dumps(result, ensure_ascii=False), flush=True)
    return result


def main() -> int:
    started = time.monotonic()
    needle_results = run_needle()
    agent_result = run_agent()
    failures = [result for result in needle_results if result["status"] != "PASS"]
    summary = {
        "engine": ENGINE,
        "status": "PASS" if not failures and agent_result["status"] == "PASS" else "FAIL",
        "needle_passed": len(needle_results) - len(failures),
        "needle_total": len(needle_results),
        "agent_status": agent_result["status"],
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }
    print("CORRECTNESS_SUMMARY " + json.dumps(summary, ensure_ascii=False), flush=True)
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
