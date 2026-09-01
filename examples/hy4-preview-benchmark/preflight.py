#!/usr/bin/env python3
"""Zero-GPU checkpoint and runtime preflight for Tencent Hy4-preview."""

from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess


MODEL_PATH = Path(os.getenv("MODEL_PATH", "/models-nvme/Hy4-preview/v1"))
ENGINE = os.getenv("ENGINE", "sglang").lower()
CHECKPOINT = os.getenv("CHECKPOINT", "auto").lower()
EXPECTED_REVISION = os.getenv("EXPECTED_REVISION")
ARCHITECTURE = "HYV4ForCausalLM"
MODEL_TYPE = "hy_v4"
PROFILES = {
    "fp8": {"shards": 130, "bytes": 813_766_152_348},
    "bf16": {"shards": 131, "bytes": 1_559_983_809_380},
}


def fail(message: str) -> None:
    raise RuntimeError(message)


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail(f"required file not found: {path}")
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON in {path}: {exc}")
    raise AssertionError("unreachable")


def package_version(package: str) -> str:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return "not-installed"


def runtime_contains(symbol: str) -> tuple[bool, str]:
    package = "sglang" if ENGINE == "sglang" else "vllm"
    spec = importlib.util.find_spec(package)
    if spec is None or not spec.submodule_search_locations:
        return False, f"Python package {package!r} not found"
    for root_name in spec.submodule_search_locations:
        root = Path(root_name)
        for path in root.rglob("*.py"):
            try:
                if symbol.encode() in path.read_bytes():
                    return True, str(path)
            except OSError:
                continue
    return False, f"{symbol} not found in installed {package} source"


def check_cli() -> dict:
    executable = shutil.which("sglang" if ENGINE == "sglang" else "vllm")
    if not executable:
        fail(f"{ENGINE} CLI was not found in PATH")
    command = (
        [executable, "serve", "--help=all"]
        if ENGINE == "vllm"
        else [executable, "serve", "--help"]
    )
    completed = subprocess.run(
        command, check=False, capture_output=True, text=True, timeout=120
    )
    output = f"{completed.stdout}\n{completed.stderr}"
    if completed.returncode:
        fail(f"CLI help failed with exit={completed.returncode}: {output[-2000:]}")
    required = (
        [
            "--tp-size",
            "--nnodes",
            "--node-rank",
            "--dist-init-addr",
            "--context-length",
            "--reasoning-parser",
            "--tool-call-parser",
            "--speculative-algorithm",
        ]
        if ENGINE == "sglang"
        else [
            "--tensor-parallel-size",
            "--pipeline-parallel-size",
            "--distributed-executor-backend",
            "--nnodes",
            "--node-rank",
            "--master-addr",
            "--master-port",
            "--headless",
            "--max-model-len",
            "--reasoning-parser",
            "--tool-call-parser",
            "--speculative-config",
            "--attention-backend",
        ]
    )
    missing = [flag for flag in required if flag not in output]
    if missing:
        fail(f"{ENGINE} CLI is missing required flags: {missing}")
    return {"executable": executable, "required_flags": required}


def detect_checkpoint(config: dict) -> str:
    quantization = (config.get("quantization_config") or {}).get("quantization") or {}
    quant_algo = str(quantization.get("quant_algo") or "").upper()
    return "fp8" if quant_algo == "MXFP8" else "bf16"


def main() -> int:
    if ENGINE not in {"sglang", "vllm"}:
        fail("ENGINE must be sglang or vllm")
    if CHECKPOINT not in {"auto", "fp8", "bf16"}:
        fail("CHECKPOINT must be auto, fp8 or bf16")
    if not MODEL_PATH.is_dir():
        fail(f"model directory not found: {MODEL_PATH}")

    config = load_json(MODEL_PATH / "config.json")
    index = load_json(MODEL_PATH / "model.safetensors.index.json")
    architectures = config.get("architectures") or []
    if ARCHITECTURE not in architectures:
        fail(f"unexpected architectures: {architectures!r}")
    if config.get("model_type") != MODEL_TYPE:
        fail(f"unexpected model_type: {config.get('model_type')!r}")

    detected = detect_checkpoint(config)
    selected = detected if CHECKPOINT == "auto" else CHECKPOINT
    if selected != detected:
        fail(f"checkpoint mismatch: requested={selected}, detected={detected}")

    quantization_config = config.get("quantization_config") or {}
    quantization = quantization_config.get("quantization") or {}
    if selected == "fp8":
        if str(quantization_config.get("quant_method")).lower() != "modelopt":
            fail(f"unexpected FP8 quant_method: {quantization_config.get('quant_method')!r}")
        if str(quantization.get("quant_algo")).upper() != "MXFP8":
            fail(f"unexpected FP8 quant_algo: {quantization.get('quant_algo')!r}")

    weight_map = index.get("weight_map") or {}
    shards = sorted(set(weight_map.values()))
    if not shards:
        fail("weight index contains no shards")
    missing = [name for name in shards if not (MODEL_PATH / name).is_file()]
    empty = [
        name
        for name in shards
        if (MODEL_PATH / name).is_file() and not (MODEL_PATH / name).stat().st_size
    ]
    if missing or empty:
        fail(f"checkpoint incomplete: missing={missing[:5]}, empty={empty[:5]}")

    indexed_bytes = (index.get("metadata") or {}).get("total_size")
    if indexed_bytes is not None:
        indexed_bytes = int(indexed_bytes)
    actual_bytes = sum((MODEL_PATH / name).stat().st_size for name in shards)
    expected = PROFILES[selected]
    if len(shards) != expected["shards"]:
        fail(f"shards mismatch: expected={expected['shards']}, actual={len(shards)}")
    if indexed_bytes is not None and indexed_bytes != expected["bytes"]:
        fail(f"weight bytes mismatch: expected={expected['bytes']}, index={indexed_bytes}")
    if actual_bytes != expected["bytes"]:
        fail(f"on-disk bytes mismatch: expected={expected['bytes']}, actual={actual_bytes}")

    required_files = ["tokenizer_config.json", "generation_config.json"]
    absent = [name for name in required_files if not (MODEL_PATH / name).is_file()]
    if absent:
        fail(f"required tokenizer/generation files missing: {absent}")
    if not (
        (MODEL_PATH / "chat_template.jinja").is_file()
        or (MODEL_PATH / "tokenizer_config.json").is_file()
    ):
        fail("chat template source was not found")

    revision_files = [MODEL_PATH / "REVISION", MODEL_PATH / ".revision"]
    revision = next(
        (path.read_text(encoding="utf-8").strip() for path in revision_files if path.is_file()),
        None,
    )
    if EXPECTED_REVISION and revision != EXPECTED_REVISION:
        fail(f"revision mismatch: expected={EXPECTED_REVISION!r}, actual={revision!r}")

    registered, registration_source = runtime_contains(ARCHITECTURE)
    if not registered:
        fail(registration_source)

    result = {
        "status": "PASS",
        "engine": ENGINE,
        "checkpoint": selected,
        "model_path": str(MODEL_PATH),
        "architecture": architectures,
        "model_type": config.get("model_type"),
        "max_position_embeddings": config.get("max_position_embeddings"),
        "weight_shards": len(shards),
        "weight_bytes_from_index": indexed_bytes,
        "weight_bytes": actual_bytes,
        "quant_method": quantization_config.get("quant_method"),
        "quant_algo": quantization.get("quant_algo"),
        "hardware_note": (
            "MXFP8 requires SM100+ in the official SGLang recipe; do not schedule on H20/H200"
            if selected == "fp8"
            else "BF16 Hopper path starts at two 8-GPU nodes / TP16; the official two-node recipe remains In Progress"
        ),
        "revision": revision,
        "runtime_registration": registration_source,
        "cli": check_cli(),
        "versions": {
            "sglang": package_version("sglang"),
            "vllm": package_version("vllm"),
            "transformers": package_version("transformers"),
            "torch": package_version("torch"),
        },
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False))
        raise
