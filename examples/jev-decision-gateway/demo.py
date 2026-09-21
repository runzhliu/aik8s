#!/usr/bin/env python3
"""Evaluate a narrow decision gateway with rules, official Jev, or a community scorer."""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROUTES = ["billing", "technical", "sales", "other"]
ROUTE_QUESTION = (
    "Which team should handle this customer request? "
    "billing = charges, payments, invoices, payouts or refunds; "
    "technical = bugs, outages, integrations, login or account security; "
    "sales = pricing, plans, upgrades, trials or new accounts; "
    "other = greetings, feedback, careers, press or unrelated requests."
)
URGENT_QUESTION = (
    "Does this require handling today because of an explicit deadline, service outage, "
    "account compromise, active financial loss, or blocked production work? "
    "Mere frustration without time pressure is not urgent."
)


def curl_json(url: str, payload: dict[str, Any], headers: list[str] | None = None,
              timeout: int = 120) -> tuple[dict[str, Any], int]:
    command = [
        "curl", "-sS", "--max-time", str(timeout), "-X", "POST", url,
        "-H", "Content-Type: application/json",
    ]
    if os.environ.get("JEV_CURL_RESOLVE"):
        command[1:1] = ["--resolve", os.environ["JEV_CURL_RESOLVE"]]
    for header in headers or []:
        command.extend(["-H", header])
    command.extend(["--data-binary", "@-", "-w", "\n__HTTP_CODE__:%{http_code}"])
    result = subprocess.run(
        command,
        input=json.dumps(payload, ensure_ascii=False),
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"curl exited {result.returncode}")
    marker = "\n__HTTP_CODE__:"
    if marker not in result.stdout:
        raise RuntimeError("response did not include an HTTP status")
    body, status_text = result.stdout.rsplit(marker, 1)
    status = int(status_text.strip())
    try:
        decoded = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"non-JSON response with HTTP {status}: {body[:300]}") from exc
    return decoded, status


def curl_text(url: str, timeout: int = 180) -> str:
    command = ["curl", "-sS", "-N", "--max-time", str(timeout), url]
    if os.environ.get("JEV_CURL_RESOLVE"):
        command[1:1] = ["--resolve", os.environ["JEV_CURL_RESOLVE"]]
    result = subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"curl exited {result.returncode}")
    return result.stdout


class HFCommunityProvider:
    name = "hf-community"

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def predict(self, text: str) -> dict[str, Any]:
        questions = [
            {"type": "choice", "question": ROUTE_QUESTION, "options": ROUTES},
            {"type": "noul", "question": URGENT_QUESTION, "options": []},
        ]
        start = time.perf_counter()
        queued, status = curl_json(
            f"{self.base_url}/gradio_api/call/score",
            {"data": [text, questions, False]},
        )
        if status != 200 or "event_id" not in queued:
            raise RuntimeError(f"Space enqueue failed: HTTP {status}: {queued}")
        stream = curl_text(
            f"{self.base_url}/gradio_api/call/score/{queued['event_id']}"
        )
        data_lines = [line[6:] for line in stream.splitlines() if line.startswith("data: ")]
        if not data_lines:
            raise RuntimeError(f"Space returned no data event: {stream[:500]}")
        envelope = json.loads(data_lines[-1])
        output = envelope[0] if isinstance(envelope, list) else envelope
        if not isinstance(output, dict):
            raise RuntimeError(f"unexpected Space response: {output!r}")
        if "error" in output:
            raise RuntimeError(str(output["error"]))
        scorer = output["scorer"]
        route, urgent = scorer["questions"]
        route_probs = dict(zip(route["options"], route["probs"]))
        urgent_probs = dict(zip(urgent["options"], urgent["probs"]))
        return {
            "model": scorer["model"],
            "route": route["chosen"],
            "route_probabilities": route_probs,
            "route_confidence": route["conf"],
            "urgent_probability": urgent_probs["yes"],
            "latency_ms": round((time.perf_counter() - start) * 1000, 1),
            "provider_latency_ms": scorer.get("total_ms"),
            "disclosure": output.get("disclosure"),
        }


class LayaCommunityProvider:
    name = "laya-community"

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def predict(self, text: str) -> dict[str, Any]:
        questions = {
            "route": {
                "type": "choice",
                "instructions": "Which team should handle this customer request?",
                "criteria": {
                    "billing": "Charges, payments, invoices, payouts or refunds",
                    "technical": "Bugs, outages, integrations, login or account security",
                    "sales": "Pricing, plans, upgrades, trials or new accounts",
                    "other": "Greetings, feedback, careers, press or unrelated requests",
                },
            },
            "urgent": {"type": "noul", "instructions": URGENT_QUESTION},
        }
        start = time.perf_counter()
        queued, status = curl_json(
            f"{self.base_url}/gradio_api/call/run_playground",
            {"data": [text, json.dumps(questions, ensure_ascii=False)]},
        )
        if status != 200 or "event_id" not in queued:
            raise RuntimeError(f"Space enqueue failed: HTTP {status}: {queued}")
        stream = curl_text(
            f"{self.base_url}/gradio_api/call/run_playground/{queued['event_id']}"
        )
        data_lines = [line[6:] for line in stream.splitlines() if line.startswith("data: ")]
        if not data_lines:
            raise RuntimeError(f"Space returned no data event: {stream[:500]}")
        envelope = json.loads(data_lines[-1])
        if not isinstance(envelope, list) or len(envelope) < 2:
            raise RuntimeError(f"unexpected Space response: {envelope!r}")
        raw = json.loads(envelope[1])
        route = raw["answers"]["route"]
        urgent = raw["answers"]["urgent"]
        return {
            "model": raw["model"],
            "route": route["choice"],
            "route_probabilities": route["probabilities"],
            "route_confidence": route["confidence"],
            "urgent_probability": urgent["noul"],
            "latency_ms": round((time.perf_counter() - start) * 1000, 1),
            "provider_latency_ms": raw.get("latency_ms"),
            "usage": raw.get("usage"),
        }


class OfficialJevProvider:
    name = "official"

    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    def predict(self, text: str) -> dict[str, Any]:
        payload = {
            "state": text,
            "model": self.model,
            "questions": {
                "route": {
                    "type": "choice",
                    "instructions": "Which team should handle this customer request?",
                    "criteria": {
                        "billing": "Charges, payments, invoices, payouts or refunds",
                        "technical": "Bugs, outages, integrations, login or account security",
                        "sales": "Pricing, plans, upgrades, trials or new accounts",
                        "other": "Greetings, feedback, careers, press or unrelated requests",
                    },
                },
                "urgent": {
                    "type": "noul",
                    "instructions": URGENT_QUESTION,
                    "criteria": {
                        "true": "Needs handling today under the conditions in the question",
                        "false": "Can follow the normal support queue",
                    },
                },
            },
        }
        start = time.perf_counter()
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                body, status = curl_json(
                    "https://api.typesafe.ai/v1/systemone",
                    payload,
                    headers=[f"Authorization: Bearer {self.api_key}"],
                )
                if status == 200:
                    route = body["answers"]["route"]
                    urgent = body["answers"]["urgent"]
                    return {
                        "model": body["model"],
                        "route": route["choice"],
                        "route_probabilities": route["probabilities"],
                        "route_confidence": route["confidence"],
                        "urgent_probability": urgent["noul"],
                        "latency_ms": round((time.perf_counter() - start) * 1000, 1),
                        "usage": body.get("usage"),
                    }
                if status not in (429, 529):
                    raise RuntimeError(f"official API HTTP {status}: {body}")
                last_error = RuntimeError(f"official API HTTP {status}: {body}")
            except Exception as exc:  # bounded retry for transient failures only
                last_error = exc
            if attempt < 2:
                time.sleep(0.5 * (2 ** attempt))
        raise RuntimeError(str(last_error))


class RuleProvider:
    name = "rules"
    KEYWORDS = {
        "billing": ["扣款", "退款", "发票", "到账", "付款", "charge", "refund", "invoice", "payout"],
        "technical": ["503", "登录", "被盗", "webhook", "报错", "接口", "outage", "login", "bug"],
        "sales": ["采购", "报价", "套餐", "试用", "演示", "contract", "price", "seats", "sso"],
    }
    URGENT = ["今天", "立即", "马上", "今晚", "明天", "被盗", "503", "today", "5 pm", "tonight"]

    def predict(self, text: str) -> dict[str, Any]:
        started = time.perf_counter()
        lower = text.lower()
        scores = {route: sum(1 for word in words if word in lower) for route, words in self.KEYWORDS.items()}
        top = max(scores, key=scores.get)
        route = top if scores[top] else "other"
        probs = {item: 0.05 for item in ROUTES}
        probs[route] = 0.85
        urgent = 0.9 if any(word in lower for word in self.URGENT) else 0.1
        return {
            "model": "keyword-rules-v1",
            "route": route,
            "route_probabilities": probs,
            "route_confidence": probs[route],
            "urgent_probability": urgent,
            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
        }


def load_cases(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return math.nan
    rank = (len(ordered) - 1) * quantile
    low, high = math.floor(rank), math.ceil(rank)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def expected_calibration_error(rows: list[dict[str, Any]], bins: int = 10) -> float:
    total = len(rows)
    error = 0.0
    for index in range(bins):
        lower, upper = index / bins, (index + 1) / bins
        bucket = [
            row for row in rows
            if lower <= row["prediction"]["route_top_probability"] <= upper
            and (index == bins - 1 or row["prediction"]["route_top_probability"] < upper)
        ]
        if not bucket:
            continue
        accuracy = sum(row["route_correct"] for row in bucket) / len(bucket)
        confidence = statistics.mean(row["prediction"]["route_top_probability"] for row in bucket)
        error += len(bucket) / total * abs(accuracy - confidence)
    return error


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    successful = [row for row in rows if "prediction" in row]
    if not successful:
        return {"attempted": len(rows), "successful": 0}
    route_brier = []
    urgent_brier = []
    for row in successful:
        expected_route = row["expected_route"]
        probs = row["prediction"]["route_probabilities"]
        row["prediction"]["route_top_probability"] = float(probs[row["prediction"]["route"]])
        route_brier.append(sum((float(probs.get(label, 0)) - (label == expected_route)) ** 2 for label in ROUTES))
        urgent_brier.append((row["prediction"]["urgent_probability"] - int(row["expected_urgent"])) ** 2)
    selective = []
    selective_probability = []
    for threshold in (0.50, 0.70, 0.80, 0.85, 0.90, 0.95):
        accepted = [row for row in successful if row["prediction"]["route_confidence"] >= threshold]
        selective.append({
            "threshold": threshold,
            "coverage": round(len(accepted) / len(successful), 4),
            "route_accuracy": round(sum(row["route_correct"] for row in accepted) / len(accepted), 4) if accepted else None,
        })
        accepted_probability = [row for row in successful if row["prediction"]["route_top_probability"] >= threshold]
        selective_probability.append({
            "threshold": threshold,
            "coverage": round(len(accepted_probability) / len(successful), 4),
            "route_accuracy": round(sum(row["route_correct"] for row in accepted_probability) / len(accepted_probability), 4) if accepted_probability else None,
        })
    latencies = [row["prediction"]["latency_ms"] for row in successful]
    by_language = {}
    for language in sorted({row["language"] for row in successful}):
        group = [row for row in successful if row["language"] == language]
        by_language[language] = {
            "n": len(group),
            "route_accuracy": round(sum(row["route_correct"] for row in group) / len(group), 4),
            "urgent_accuracy": round(sum(row["urgent_correct"] for row in group) / len(group), 4),
        }
    provider_latencies = [
        row["prediction"]["provider_latency_ms"] for row in successful
        if row["prediction"].get("provider_latency_ms") is not None
    ]
    summary = {
        "attempted": len(rows),
        "successful": len(successful),
        "route_accuracy": round(sum(row["route_correct"] for row in successful) / len(successful), 4),
        "urgent_accuracy": round(sum(row["urgent_correct"] for row in successful) / len(successful), 4),
        "route_brier": round(statistics.mean(route_brier), 4),
        "urgent_brier": round(statistics.mean(urgent_brier), 4),
        "route_ece_10_bins": round(expected_calibration_error(successful), 4),
        "latency_ms": {
            "mean": round(statistics.mean(latencies), 1),
            "p50": round(percentile(latencies, 0.50), 1),
            "p95": round(percentile(latencies, 0.95), 1),
            "max": round(max(latencies), 1),
        },
        "by_language": by_language,
        "selective_route_confidence": selective,
        "selective_route_probability": selective_probability,
    }
    if provider_latencies:
        summary["provider_latency_ms"] = {
            "mean": round(statistics.mean(provider_latencies), 1),
            "p50": round(percentile(provider_latencies, 0.50), 1),
            "p95": round(percentile(provider_latencies, 0.95), 1),
            "max": round(max(provider_latencies), 1),
        }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=("rules", "hf-community", "laya-community", "official"), required=True)
    parser.add_argument("--cases", type=Path, default=Path(__file__).parent / "fixtures" / "tickets.jsonl")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--model", default="jev-1.13.0")
    parser.add_argument("--hf-space", default="https://pngwn-system-one-demo.hf.space")
    parser.add_argument("--laya-space", default="https://convaiinnovations-laya-demo.hf.space")
    args = parser.parse_args()

    if args.provider == "rules":
        provider: Any = RuleProvider()
    elif args.provider == "hf-community":
        provider = HFCommunityProvider(args.hf_space)
    elif args.provider == "laya-community":
        provider = LayaCommunityProvider(args.laya_space)
    else:
        api_key = os.environ.get("TYPESAFE_API_KEY")
        if not api_key:
            parser.error("TYPESAFE_API_KEY is required for --provider official")
        provider = OfficialJevProvider(api_key, args.model)

    cases = load_cases(args.cases)
    if args.limit:
        cases = cases[: args.limit]
    rows = []
    for index, case in enumerate(cases, 1):
        row = dict(case)
        try:
            prediction = provider.predict(case["text"])
            row["prediction"] = prediction
            row["route_correct"] = prediction["route"] == case["expected_route"]
            row["urgent_correct"] = (prediction["urgent_probability"] >= 0.5) == case["expected_urgent"]
            print(
                f"[{index:02d}/{len(cases):02d}] {case['id']}: "
                f"route={prediction['route']} p={prediction['route_confidence']:.3f} "
                f"urgent={prediction['urgent_probability']:.3f} {prediction['latency_ms']:.1f}ms"
            )
        except Exception as exc:
            row["error"] = str(exc)
            print(f"[{index:02d}/{len(cases):02d}] {case['id']}: ERROR {exc}", file=sys.stderr)
        rows.append(row)

    report = {
        "schema_version": 1,
        "provider": args.provider,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "dataset": str(args.cases),
        "summary": summarize(rows),
        "cases": rows,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
        print(f"wrote {args.output}")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0 if report["summary"].get("successful") == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
