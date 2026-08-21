#!/usr/bin/env python3
"""Evaluate newer text/multimodal models through ms-swift's inference engine."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch
from peft import PeftModel
from swift import get_model_processor, get_template
from swift.infer_engine import InferRequest, RequestConfig, TransformersEngine


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--adapter")
    parser.add_argument("--test-file", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--max-new-tokens", type=int, default=192)
    parser.add_argument("--limit", type=int)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.batch_size < 1:
        raise ValueError("batch-size must be positive")

    rows = [json.loads(line) for line in Path(args.test_file).read_text(encoding="utf-8").splitlines() if line]
    if args.limit:
        rows = rows[: args.limit]

    model, processor = get_model_processor(
        args.model,
        torch_dtype=torch.bfloat16,
        device_map={"": "cuda:0"},
    )
    if args.adapter:
        model = PeftModel.from_pretrained(model, args.adapter)
    model.eval()

    template = get_template(processor, enable_thinking=False)
    engine = TransformersEngine(model, template=template)
    request_config = RequestConfig(max_tokens=args.max_new_tokens, temperature=0)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    completed = 0
    with temporary.open("w", encoding="utf-8") as stream:
        for offset in range(0, len(rows), args.batch_size):
            batch = rows[offset : offset + args.batch_size]
            requests = [InferRequest(messages=row["messages"]) for row in batch]
            responses = engine.infer(requests, request_config, use_tqdm=False)
            for row, response in zip(batch, responses):
                stream.write(
                    json.dumps(
                        {
                            "id": row["id"],
                            "gold": row["gold"],
                            "response": response.choices[0].message.content.strip(),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
            completed += len(batch)
            print(
                json.dumps(
                    {
                        "event": "EVAL_PROGRESS",
                        "adapter": bool(args.adapter),
                        "completed": completed,
                        "total": len(rows),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
    temporary.replace(output)
    print(
        json.dumps(
            {
                "event": "EVAL_COMPLETE",
                "adapter": args.adapter,
                "examples": len(rows),
                "output": str(output),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
