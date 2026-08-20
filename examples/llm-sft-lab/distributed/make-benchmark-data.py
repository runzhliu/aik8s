#!/usr/bin/env python3
"""Build a deterministic, near-fixed-length JSONL dataset for throughput tests."""

import argparse
import hashlib
import json
import os
from pathlib import Path


PARAGRAPH = (
    "先给出结论，再列出可验证的证据。分布式训练排障需要依次检查数据、"
    "计算、显存、进程组、网络接口和集合通信日志，并固定变量进行对照实验。"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--examples", type=int, default=512)
    parser.add_argument("--repeats", type=int, default=12)
    return parser.parse_args()


def make_messages(index: int, repeats: int) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": "你是一个谨慎的 AI 基础设施助手。回答需要可验证、可复现。",
        },
        {
            "role": "user",
            "content": f"请给出分布式训练基准测试清单。样本编号：{index:04d}",
        },
        {"role": "assistant", "content": PARAGRAPH * repeats},
    ]


def main() -> None:
    args = parse_args()
    if args.examples < 1 or args.repeats < 1:
        raise ValueError("examples and repeats must be positive")

    rows = [make_messages(index, args.repeats) for index in range(args.examples)]
    character_lengths = [sum(len(item["content"]) for item in row) for row in rows]

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    with temporary_output.open("w", encoding="utf-8") as stream:
        for messages in rows:
            stream.write(json.dumps({"messages": messages}, ensure_ascii=False) + "\n")
    temporary_output.replace(output)

    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    print(
        json.dumps(
            {
                "event": "BENCH_DATASET",
                "path": str(output),
                "examples": len(rows),
                "repeats": args.repeats,
                "min_characters": min(character_lengths),
                "max_characters": max(character_lengths),
                "sha256": digest,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
