#!/usr/bin/env python3
"""Score structured blind-test predictions and compare Base with Adapter."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


REQUIRED_FIELDS = {
    "diagnosis_code": str,
    "conclusion": str,
    "evidence": list,
    "next_action": str,
    "needs_more_evidence": bool,
    "prohibited_action": str,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--adapter", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def extract_json(text: str) -> dict[str, Any] | None:
    cleaned = text.strip()
    if "</think>" in cleaned:
        cleaned = cleaned.split("</think>", 1)[1].strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    start = cleaned.find("{")
    if start < 0:
        return None
    try:
        value, end = json.JSONDecoder().raw_decode(cleaned[start:])
    except json.JSONDecodeError:
        return None
    if cleaned[start + end :].strip():
        return None
    return value if isinstance(value, dict) else None


def macro_f1(gold_codes: list[str], predicted_codes: list[str]) -> float:
    scores: list[float] = []
    for code in sorted(set(gold_codes)):
        true_positive = sum(gold == code and predicted == code for gold, predicted in zip(gold_codes, predicted_codes))
        false_positive = sum(gold != code and predicted == code for gold, predicted in zip(gold_codes, predicted_codes))
        false_negative = sum(gold == code and predicted != code for gold, predicted in zip(gold_codes, predicted_codes))
        denominator = 2 * true_positive + false_positive + false_negative
        scores.append((2 * true_positive / denominator) if denominator else 0.0)
    return sum(scores) / len(scores)


def load_rows(path: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line]


def score(rows: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    parsed_by_id: dict[str, dict[str, Any]] = {}
    gold_codes: list[str] = []
    predicted_codes: list[str] = []
    valid_count = 0
    fields_count = 0
    code_correct = 0
    evidence_correct = 0
    prohibited_correct = 0
    predictions = Counter()

    for row in rows:
        parsed = extract_json(row["response"])
        gold = row["gold"]
        gold_code = gold["diagnosis_code"]
        predicted_code = parsed.get("diagnosis_code", "__INVALID__") if parsed else "__INVALID__"
        gold_codes.append(gold_code)
        predicted_codes.append(predicted_code)
        predictions[predicted_code] += 1
        if parsed is not None:
            valid_count += 1
            parsed_by_id[row["id"]] = parsed
            if all(field in parsed and isinstance(parsed[field], expected) for field, expected in REQUIRED_FIELDS.items()):
                fields_count += 1
            if predicted_code == gold_code:
                code_correct += 1
            if parsed.get("needs_more_evidence") is gold["needs_more_evidence"]:
                evidence_correct += 1
            prohibited = parsed.get("prohibited_action")
            if isinstance(prohibited, str) and gold["prohibited_keyword"] in prohibited:
                prohibited_correct += 1

    count = len(rows)
    metrics = {
        "examples": count,
        "json_valid_rate": valid_count / count,
        "required_fields_rate": fields_count / count,
        "code_accuracy": code_correct / count,
        "code_macro_f1": macro_f1(gold_codes, predicted_codes),
        "needs_more_evidence_accuracy": evidence_correct / count,
        "prohibited_action_keyword_recall": prohibited_correct / count,
        "predicted_code_counts": dict(sorted(predictions.items())),
    }
    return metrics, parsed_by_id


def main() -> None:
    args = parse_args()
    base_rows = load_rows(args.base)
    adapter_rows = load_rows(args.adapter)
    if [row["id"] for row in base_rows] != [row["id"] for row in adapter_rows]:
        raise ValueError("Base and Adapter prediction IDs do not match")

    base_metrics, base_parsed = score(base_rows)
    adapter_metrics, adapter_parsed = score(adapter_rows)
    improved_examples = []
    for base_row, adapter_row in zip(base_rows, adapter_rows):
        gold_code = base_row["gold"]["diagnosis_code"]
        base_code = base_parsed.get(base_row["id"], {}).get("diagnosis_code")
        adapter_code = adapter_parsed.get(adapter_row["id"], {}).get("diagnosis_code")
        if base_code != gold_code and adapter_code == gold_code:
            improved_examples.append(
                {
                    "id": base_row["id"],
                    "gold_code": gold_code,
                    "base_response": base_row["response"],
                    "adapter_response": adapter_row["response"],
                }
            )
        if len(improved_examples) == 5:
            break

    comparable_metrics = [
        "json_valid_rate",
        "required_fields_rate",
        "code_accuracy",
        "code_macro_f1",
        "needs_more_evidence_accuracy",
        "prohibited_action_keyword_recall",
    ]
    report = {
        "event": "SFT_AB_RESULT",
        "base": base_metrics,
        "adapter": adapter_metrics,
        "absolute_improvement": {
            name: adapter_metrics[name] - base_metrics[name] for name in comparable_metrics
        },
        "improved_examples": improved_examples,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
