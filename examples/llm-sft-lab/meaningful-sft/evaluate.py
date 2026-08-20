#!/usr/bin/env python3
"""Run deterministic Base or Adapter generation on the blind-test set."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--adapter")
    parser.add_argument("--test-file", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--max-input-tokens", type=int, default=512)
    parser.add_argument("--max-new-tokens", type=int, default=192)
    parser.add_argument("--limit", type=int)
    return parser.parse_args()


def render_prompt(tokenizer: Any, messages: list[dict[str, str]]) -> str:
    kwargs = {"tokenize": False, "add_generation_prompt": True}
    try:
        return tokenizer.apply_chat_template(messages, enable_thinking=False, **kwargs)
    except TypeError:
        return tokenizer.apply_chat_template(messages, **kwargs)


def load_model(model_path: str, adapter_path: str | None) -> tuple[Any, Any]:
    tokenizer = AutoTokenizer.from_pretrained(model_path)
    tokenizer.padding_side = "left"
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        model_path,
        dtype=torch.bfloat16,
        device_map={"": "cuda:0"},
    )
    if adapter_path:
        from peft import PeftModel

        model = PeftModel.from_pretrained(model, adapter_path)
    model.eval()
    return tokenizer, model


def main() -> None:
    args = parse_args()
    if args.batch_size < 1:
        raise ValueError("batch-size must be positive")

    rows = [json.loads(line) for line in Path(args.test_file).read_text(encoding="utf-8").splitlines() if line]
    if args.limit:
        rows = rows[: args.limit]
    tokenizer, model = load_model(args.model, args.adapter)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    completed = 0
    with temporary.open("w", encoding="utf-8") as stream, torch.inference_mode():
        for offset in range(0, len(rows), args.batch_size):
            batch = rows[offset : offset + args.batch_size]
            prompts = [render_prompt(tokenizer, row["messages"]) for row in batch]
            encoded = tokenizer(
                prompts,
                return_tensors="pt",
                padding=True,
                truncation=True,
                max_length=args.max_input_tokens,
            ).to("cuda:0")
            generated = model.generate(
                **encoded,
                do_sample=False,
                max_new_tokens=args.max_new_tokens,
                pad_token_id=tokenizer.pad_token_id,
                eos_token_id=tokenizer.eos_token_id,
            )
            prompt_width = encoded["input_ids"].shape[1]
            responses = tokenizer.batch_decode(generated[:, prompt_width:], skip_special_tokens=True)
            for row, response in zip(batch, responses):
                stream.write(
                    json.dumps(
                        {
                            "id": row["id"],
                            "gold": row["gold"],
                            "response": response.strip(),
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
