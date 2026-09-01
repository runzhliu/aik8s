#!/usr/bin/env python3
"""Zero-GPU integrity check for DeepSeek-V4-Flash-Vision-Exp.

The check intentionally reads metadata and file sizes only. It never hashes or
loads the 156 GiB checkpoint.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


EXPECTED_ARCH = "DeepseekV4ForCausalLM"
EXPECTED_MODEL_TYPE = "deepseek_v4"
EXPECTED_CONTEXT = 1_048_576
EXPECTED_SHARDS = 48
EXPECTED_TENSORS = 72_633
EXPECTED_TENSOR_BYTES = 167_811_372_792
EXPECTED_SHARD_BYTES = 167_819_404_368
EXPECTED_VISION_TENSORS = 259
EXPECTED_ALIGNER_TENSORS = 4
EXPECTED_IMAGE_MARKERS = {"image_start", "image_end", "image_pad", "image_newline"}


def fail(message: str) -> None:
    raise RuntimeError(message)


def load_json(path: Path) -> dict:
    if not path.is_file():
        fail(f"missing required file: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read JSON {path}: {exc}")


def main() -> int:
    raw_path = os.environ.get("MODEL_PATH")
    if not raw_path:
        fail("set MODEL_PATH to the completed CFS or NVMe model directory")
    model_path = Path(raw_path).resolve()
    if not model_path.is_dir():
        fail(f"MODEL_PATH is not a directory: {model_path}")

    required = [
        "config.json",
        "generation_config.json",
        "model.safetensors.index.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "encoding/encoding_dsv4.py",
        "inference/config.json",
        "inference/model.py",
        "inference/vision.py",
        "inference/image_processor.py",
        "inference/examples/images/carrots.jpeg",
        "inference/examples/images/corn.jpeg",
    ]
    missing = [name for name in required if not (model_path / name).is_file()]
    if missing:
        fail("missing required model files: " + ", ".join(missing))

    config = load_json(model_path / "config.json")
    inference_config = load_json(model_path / "inference/config.json")
    index = load_json(model_path / "model.safetensors.index.json")

    architectures = config.get("architectures") or []
    if EXPECTED_ARCH not in architectures:
        fail(f"unexpected architectures: {architectures!r}")
    if config.get("model_type") != EXPECTED_MODEL_TYPE:
        fail(f"unexpected model_type: {config.get('model_type')!r}")
    if config.get("max_position_embeddings") != EXPECTED_CONTEXT:
        fail(
            "unexpected max_position_embeddings: "
            f"{config.get('max_position_embeddings')!r}"
        )

    quant = config.get("quantization_config") or {}
    expected_quant = {
        "quant_method": "fp8",
        "fmt": "e4m3",
        "scale_fmt": "ue8m0",
        "weight_block_size": [128, 128],
    }
    mismatched_quant = {
        key: {"expected": value, "actual": quant.get(key)}
        for key, value in expected_quant.items()
        if quant.get(key) != value
    }
    if mismatched_quant:
        fail(f"unexpected quantization_config: {mismatched_quant}")

    expected_inference = {
        "vision_n_layers": 32,
        "vision_dim": 1024,
        "vision_n_heads": 16,
        "vision_patch_size": 14,
        "vision_max_n_token": 384,
        "dtype": "fp8",
        "scale_fmt": "ue8m0",
        "expert_dtype": "fp4",
    }
    mismatched_inference = {
        key: {"expected": value, "actual": inference_config.get(key)}
        for key, value in expected_inference.items()
        if inference_config.get(key) != value
    }
    if mismatched_inference:
        fail(f"unexpected inference/config.json: {mismatched_inference}")

    weight_map = index.get("weight_map")
    if not isinstance(weight_map, dict):
        fail("model.safetensors.index.json has no weight_map object")
    if len(weight_map) != EXPECTED_TENSORS:
        fail(f"unexpected tensor count: {len(weight_map)} != {EXPECTED_TENSORS}")

    shard_names = sorted(set(weight_map.values()))
    if len(shard_names) != EXPECTED_SHARDS:
        fail(f"unexpected shard count: {len(shard_names)} != {EXPECTED_SHARDS}")

    missing_shards: list[str] = []
    empty_shards: list[str] = []
    shard_bytes = 0
    for name in shard_names:
        shard = model_path / name
        if not shard.is_file():
            missing_shards.append(name)
            continue
        size = shard.stat().st_size
        if size <= 0:
            empty_shards.append(name)
        shard_bytes += size
    if missing_shards:
        fail("missing indexed shards: " + ", ".join(missing_shards))
    if empty_shards:
        fail("empty indexed shards: " + ", ".join(empty_shards))
    if shard_bytes != EXPECTED_SHARD_BYTES:
        fail(f"unexpected shard bytes: {shard_bytes} != {EXPECTED_SHARD_BYTES}")

    tensor_bytes = (index.get("metadata") or {}).get("total_size")
    if tensor_bytes != EXPECTED_TENSOR_BYTES:
        fail(f"unexpected metadata.total_size: {tensor_bytes} != {EXPECTED_TENSOR_BYTES}")

    keys = set(weight_map)
    vision_count = sum(name.startswith("vision.") for name in keys)
    aligner_count = sum(name.startswith("aligner.") for name in keys)
    image_markers = keys & EXPECTED_IMAGE_MARKERS
    if vision_count != EXPECTED_VISION_TENSORS:
        fail(f"unexpected vision tensor count: {vision_count}")
    if aligner_count != EXPECTED_ALIGNER_TENSORS:
        fail(f"unexpected aligner tensor count: {aligner_count}")
    if image_markers != EXPECTED_IMAGE_MARKERS:
        fail(f"missing image markers: {sorted(EXPECTED_IMAGE_MARKERS - image_markers)}")

    temporary_suffixes = (".tmp", ".part", ".partial", ".incomplete")
    temporary_files = [
        str(path.relative_to(model_path))
        for path in model_path.rglob("*")
        if path.is_file() and path.name.endswith(temporary_suffixes)
    ]
    if temporary_files:
        fail("temporary sync files remain: " + ", ".join(temporary_files[:20]))

    expected_revision = os.environ.get("EXPECTED_REVISION")
    revision = None
    for candidate in (".revision", "REVISION", ".aik8s-revision"):
        revision_file = model_path / candidate
        if revision_file.is_file():
            revision = revision_file.read_text(encoding="utf-8").strip()
            break
    if expected_revision and revision != expected_revision:
        fail(f"revision mismatch: recorded={revision!r}, expected={expected_revision!r}")

    report = {
        "status": "PASS",
        "model_path": str(model_path),
        "revision": revision or "not recorded locally",
        "architecture": EXPECTED_ARCH,
        "context_length": EXPECTED_CONTEXT,
        "shards": len(shard_names),
        "shard_bytes": shard_bytes,
        "tensor_bytes": tensor_bytes,
        "tensors": len(weight_map),
        "vision_tensors": vision_count,
        "aligner_tensors": aligner_count,
        "image_markers": sorted(image_markers),
        "hashing": "skipped by design",
        "note": (
            "config.json exposes vision_config/projector_config as null; "
            "visual parameters are verified from inference/config.json and weight names"
        ),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
