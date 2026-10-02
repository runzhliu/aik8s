#!/usr/bin/env python3
"""OpenAI-compatible correctness smoke for Qwen3.8-2.4T-A95B-FP8."""

from __future__ import annotations

import json
import os
from pathlib import Path
import time
from typing import Optional
import urllib.error
import urllib.request


BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:30000/v1").rstrip("/")
MODEL = os.getenv("MODEL", "qwen38-a95b-fp8")
TIMEOUT = int(os.getenv("TIMEOUT", "1800"))
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "4096"))
TRACE_FILE = os.getenv("TRACE_FILE")


def trace(value: dict) -> None:
    if TRACE_FILE:
        with Path(TRACE_FILE).open("a", encoding="utf-8") as f:
            f.write(json.dumps({"at": time.time(), **value}, ensure_ascii=False) + "\n")


def request(method: str, path: str, payload: Optional[dict] = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json", "Authorization": "Bearer EMPTY"},
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
                result = json.loads(response.read().decode("utf-8"))
                trace({"path": path, "request": payload, "attempt": attempt + 1, "response": result})
                return result
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            trace({"path": path, "request": payload, "attempt": attempt + 1,
                   "http_status": exc.code, "error_body": body})
            if exc.code not in (429, 502, 503, 504) or attempt == 2:
                raise RuntimeError(f"HTTP {exc.code} {path}: {body}") from exc
        except urllib.error.URLError as exc:
            trace({"path": path, "request": payload, "attempt": attempt + 1, "error": str(exc)})
            if attempt == 2: raise
        # No protocol remapping without a verified Qwen-specific mapping.
        time.sleep(2 ** attempt)
    raise AssertionError("unreachable")


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
        "max_tokens": MAX_TOKENS,
    }
    payload.update(extra)
    return request("POST", "/chat/completions", payload)


def reasoning_text(message: dict) -> str:
    return message.get("reasoning_content") or message.get("reasoning") or ""


def stream_chat() -> tuple[str, str]:
    payload = {"model": MODEL, "messages": [{"role": "user", "content": "计算 37×19，只回答数字。"}],
               "stream": True, "stream_options": {"include_usage": True},
               "temperature": 0, "max_tokens": MAX_TOKENS}
    req = urllib.request.Request(f"{BASE_URL}/chat/completions", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer EMPTY"})
    content, reasoning = [], []
    done = False; usage = None
    trace({"path": "/chat/completions", "request": payload, "stream_started": True})
    # A partial stream is never retried and counted as a new successful response.
    with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
        for raw in response:
            trace({"stream_raw": raw.decode("utf-8", errors="replace")})
            line = raw.decode("utf-8").strip()
            if not line.startswith("data:"): continue
            data = line[5:].strip()
            if data == "[DONE]": done = True; continue
            event = json.loads(data)
            if event.get("error"): raise AssertionError("SSE error event")
            if event.get("usage"): usage = event["usage"]
            for choice in event.get("choices", []):
                delta = choice.get("delta", {})
                content.append(delta.get("content") or "")
                reasoning.append(delta.get("reasoning_content") or delta.get("reasoning") or "")
    assert done and usage and usage.get("completion_tokens", 0) > 0, "incomplete SSE/usage"
    final = "".join(content)
    assert final.strip() == "703", "stream final answer incorrect"
    return final, "".join(reasoning)


def main() -> int:
    result = {"status": "RUNNING", "model": MODEL, "basic_gate_passed": False, "cases": {}}
    def check(name, fn):
        try:
            value = fn(); result["cases"][name] = {"status": "PASS", "result": value}; return True
        except Exception as exc:
            result["cases"][name] = {"status": "FAILED", "error": str(exc)}; return False
        finally:
            if os.getenv("RESULT_FILE"):
                path = Path(os.environ["RESULT_FILE"]); path.parent.mkdir(parents=True, exist_ok=True)
                temp = path.with_suffix(".tmp"); temp.write_text(json.dumps(result, ensure_ascii=False, indent=2)); temp.replace(path)
    def models():
        advertised = [x["id"] for x in request("GET", "/models").get("data", [])]
        assert MODEL in advertised, "model ID missing"
        return advertised
    def math():
        msg = assistant_message(chat([{ "role": "user", "content": "计算 37×19，只回答数字。"}]))
        assert (msg.get("content") or "").strip() == "703", "incorrect final answer"
        assert "<think>" not in msg["content"], "raw reasoning leaked"
        return msg
    basic = check("models", models)
    basic = check("math", math) and basic
    basic = check("complete_sse", stream_chat) and basic
    result["basic_gate_passed"] = basic
    if basic:
        def reasoning():
            msg = result["cases"]["math"]["result"]
            assert reasoning_text(msg), "reasoning trace missing"
            return {"has_reasoning": True}
        check("reasoning", reasoning)
        for effort in ["low", "medium", "xhigh"]:
            def run_effort(effort=effort):
                msg = assistant_message(chat([{ "role":"user", "content":"只回答：12 的平方是多少？"}], reasoning_effort=effort))
                assert (msg.get("content") or "").strip() == "144", "effort answer incorrect"
                return {"effort": effort, "has_reasoning": bool(reasoning_text(msg))}
            check("reasoning_effort_" + effort, run_effort)
        def multi():
            messages = [{"role":"user", "content":"记住代号 amber-417，只回复已记住。"}]
            messages += [assistant_message(chat(messages)), {"role":"user", "content":"刚才的代号是什么？只回复代号。"}]
            msg = assistant_message(chat(messages))
            assert (msg.get("content") or "").strip() == "amber-417", "multi-turn answer incorrect"
            return msg
        check("multi_turn", multi)
        def tool():
            tools = [{"type":"function", "function":{"name":"get_weather", "description":"查询城市天气",
                "parameters":{"type":"object", "properties":{"city":{"type":"string"},"unit":{"type":"string","enum":["celsius","fahrenheit"]}}, "required":["city","unit"]}}}]
            messages = [{"role":"user", "content":"调用工具查询北京天气，单位用摄氏度。"}]
            msg = assistant_message(chat(messages, tools=tools, tool_choice="auto"))
            call = msg["tool_calls"][0]
            assert call["function"]["name"] == "get_weather", "wrong tool name"
            args = call["function"]["arguments"]
            if isinstance(args, str): args = json.loads(args)
            assert args["city"] in ("北京", "Beijing") and args["unit"] == "celsius", "wrong arguments"
            final = assistant_message(chat(messages + [msg, {"role":"tool", "tool_call_id":call["id"],
                "content":json.dumps({"city":"北京", "temperature":23, "unit":"celsius"}, ensure_ascii=False)}], tools=tools))
            assert "23" in (final.get("content") or ""), "tool result not used"
            return {"tool_call":call, "mock_result_final":final}
        check("tool_round_trip", tool)
    result["status"] = "PASS" if basic and all(x["status"] == "PASS" for x in result["cases"].values()) else "PARTIAL" if basic else "FAILED"
    if os.getenv("RESULT_FILE"):
        Path(os.environ["RESULT_FILE"]).write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if basic else 1


if __name__ == "__main__":
    raise SystemExit(main())
