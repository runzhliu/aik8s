#!/usr/bin/env python3
"""Build deterministic multi-modal serving datasets without external downloads."""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


CASES = {
    "v1-360p": {"width": 640, "height": 360, "image_count": 1, "requests": 200},
    "v2-720p": {"width": 1280, "height": 720, "image_count": 1, "requests": 200},
    "v3-1080p": {"width": 1920, "height": 1080, "image_count": 1, "requests": 100},
    "v4-2x720p": {"width": 1280, "height": 720, "image_count": 2, "requests": 100},
    "v5-4x720p": {"width": 1280, "height": 720, "image_count": 4, "requests": 50},
}


def make_image(path: Path, width: int, height: int, seed: int, label: str) -> None:
    rng = random.Random(seed)
    background = tuple(rng.randint(24, 220) for _ in range(3))
    image = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    for index in range(12):
        x0 = rng.randint(0, max(0, width - 80))
        y0 = rng.randint(0, max(0, height - 80))
        x1 = min(width - 1, x0 + rng.randint(40, max(41, width // 5)))
        y1 = min(height - 1, y0 + rng.randint(40, max(41, height // 5)))
        color = tuple(rng.randint(0, 255) for _ in range(3))
        if index % 2:
            draw.ellipse((x0, y0, x1, y1), fill=color)
        else:
            draw.rectangle((x0, y0, x1, y1), fill=color)
    draw.rectangle((8, 8, min(width - 8, 520), 44), fill=(255, 255, 255))
    draw.text((16, 18), label, fill=(0, 0, 0), font=font)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="JPEG", quality=90, optimize=True)


def build_content(image_paths: list[Path], case_id: str, request_id: int) -> list[dict]:
    content: list[dict] = [
        {
            "type": "text",
            "text": (
                f"Case {case_id}, request {request_id}. Inspect the images in order. "
                "Briefly state the number of images and the dominant color of each image. "
            ),
        }
    ]
    for index, image_path in enumerate(image_paths, start=1):
        content.append({"type": "text", "text": f"Image {index}: "})
        content.append({"type": "image", "image": str(image_path.resolve())})
    content.append({"type": "text", "text": "Answer concisely."})
    return content


def write_round(
    output_root: Path,
    case_id: str,
    spec: dict,
    round_name: str,
    requests: int,
    cache_mode: str,
    base_seed: int,
) -> None:
    image_dir = output_root / "images" / case_id
    jsonl_path = output_root / f"{case_id}.{round_name}.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for request_id in range(requests):
            image_paths: list[Path] = []
            for image_index in range(spec["image_count"]):
                if cache_mode == "warm":
                    image_name = f"shared-{image_index}.jpg"
                    image_seed = base_seed + image_index
                    label = f"{case_id} warm image {image_index + 1}"
                else:
                    image_name = f"{round_name}-{request_id:04d}-{image_index}.jpg"
                    image_seed = (
                        base_seed
                        + sum(ord(char) for char in round_name) * 10_000
                        + request_id * 17
                        + image_index
                    )
                    label = f"{case_id} {round_name} request {request_id} image {image_index + 1}"
                image_path = image_dir / image_name
                if not image_path.exists():
                    make_image(
                        image_path,
                        spec["width"],
                        spec["height"],
                        image_seed,
                        label,
                    )
                image_paths.append(image_path)

            item = {
                "content": build_content(image_paths, case_id, request_id),
                "output_tokens": 128,
                "metadata": {
                    "case_id": case_id,
                    "round": round_name,
                    "cache_mode": cache_mode,
                    "image_count": spec["image_count"],
                    "width": spec["width"],
                    "height": spec["height"],
                },
            }
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--cache-mode", choices=("cold", "warm"), required=True)
    parser.add_argument("--seed", type=int, default=20260831)
    parser.add_argument("--case", choices=tuple(CASES), action="append")
    args = parser.parse_args()

    args.output_root.mkdir(parents=True, exist_ok=True)
    selected = args.case or list(CASES)
    manifest: dict[str, dict] = {}
    for case_id in selected:
        spec = CASES[case_id]
        warmup_requests = min(16, spec["requests"])
        write_round(
            args.output_root,
            case_id,
            spec,
            "warmup",
            warmup_requests,
            args.cache_mode,
            args.seed,
        )
        for repeat in range(1, 4):
            write_round(
                args.output_root,
                case_id,
                spec,
                f"r{repeat}",
                spec["requests"],
                args.cache_mode,
                args.seed,
            )
        manifest[case_id] = {
            **spec,
            "cache_mode": args.cache_mode,
            "warmup_requests": warmup_requests,
            "recorded_rounds": 3,
        }

    (args.output_root / "manifest.json").write_text(
        json.dumps(
            {"seed": args.seed, "cache_mode": args.cache_mode, "cases": manifest},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": "PASS", "output_root": str(args.output_root), "cases": selected}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
