#!/usr/bin/env python3
"""Zero-GPU checkpoint and runtime preflight for GLM-5.3-Flash."""

from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess


MODEL_PATH = Path(os.getenv("MODEL_PATH", "/models/GLM-5.3-Flash"))
ENGINE = os.getenv("ENGINE", "sglang").lower()
EXPECTED_WEIGHT_BYTES = os.getenv("EXPECTED_WEIGHT_BYTES")
EXPECTED_SHARDS = os.getenv("EXPECTED_SHARDS")
EXPECTED_REVISION = os.getenv("EXPECTED_REVISION")
ARCHITECTURE = "Glm5NextForConditionalGeneration"
MODEL_TYPE = "glm5_next"


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

    roots = [Path(item) for item in spec.submodule_search_locations]
    needle = symbol.encode("utf-8")
    for root in roots:
        for path in root.rglob("*.py"):
            try:
                if needle in path.read_bytes():
                    return True, str(path)
            except OSError:
                continue
    return False, f"{symbol} not found below {roots}"


def check_cli() -> dict:
    executable = shutil.which("sglang" if ENGINE == "sglang" else "vllm")
    if not executable:
        fail(f"{ENGINE} CLI was not found in PATH")
    # Newer vLLM CLIs keep engine arguments behind the full help page.  The
    # short help only lists top-level serve options and causes a false FAIL.
    command = (
        [executable, "serve", "--help=all"]
        if ENGINE == "vllm"
        else [executable, "serve", "--help"]
    )
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    output = f"{completed.stdout}\n{completed.stderr}"
    if completed.returncode:
        fail(f"CLI help failed with exit={completed.returncode}: {output[-2000:]}")
    required = (
        [
            "--tp-size",
            "--ep-size",
            "--dsa-prefill-backend",
            "--dsa-decode-backend",
            "--linear-attn-backend",
            "--kv-cache-dtype",
            "--quantization",
            "--reasoning-parser",
            "--tool-call-parser",
        ]
        if ENGINE == "sglang"
        else [
            "--tensor-parallel-size",
            "--kv-cache-dtype",
            "--speculative-config",
            "--enable-prefix-caching",
            "--reasoning-parser",
            "--tool-call-parser",
        ]
    )
    missing = [flag for flag in required if flag not in output]
    if missing:
        fail(f"{ENGINE} CLI is missing required flags: {missing}")
    return {"executable": executable, "required_flags": required}


def main() -> int:
    if ENGINE not in {"sglang", "vllm"}:
        fail("ENGINE must be sglang or vllm")
    if not MODEL_PATH.is_dir():
        fail(f"model directory not found: {MODEL_PATH}")

    config = load_json(MODEL_PATH / "config.json")
    index = load_json(MODEL_PATH / "model.safetensors.index.json")
    architectures = config.get("architectures") or []
    model_type = config.get("model_type")
    if ARCHITECTURE not in architectures:
        fail(f"unexpected architectures: {architectures!r}")
    if model_type != MODEL_TYPE:
        fail(f"unexpected model_type: {model_type!r}")

    weight_map = index.get("weight_map") or {}
    shards = sorted(set(weight_map.values()))
    if not shards:
        fail("weight index contains no shards")
    missing = [name for name in shards if not (MODEL_PATH / name).is_file()]
    empty = [name for name in shards if (MODEL_PATH / name).is_file() and not (MODEL_PATH / name).stat().st_size]
    if missing or empty:
        fail(f"checkpoint is incomplete: missing={missing[:5]}, empty={empty[:5]}")

    indexed_bytes = (index.get("metadata") or {}).get("total_size")
    actual_bytes = sum((MODEL_PATH / name).stat().st_size for name in shards)
    tokenizer_candidates = [
        "tokenizer.json",
        "tokenizer.model",
        "tokenizer_config.json",
    ]
    if not any((MODEL_PATH / name).is_file() for name in tokenizer_candidates):
        fail(f"no tokenizer artifact found in {MODEL_PATH}")
    if not (
        (MODEL_PATH / "chat_template.jinja").is_file()
        or (MODEL_PATH / "tokenizer_config.json").is_file()
    ):
        fail("no chat template source found")

    if EXPECTED_WEIGHT_BYTES and int(EXPECTED_WEIGHT_BYTES) != int(indexed_bytes):
        fail(
            f"weight total mismatch: expected={EXPECTED_WEIGHT_BYTES}, "
            f"index={indexed_bytes}"
        )
    if EXPECTED_SHARDS and int(EXPECTED_SHARDS) != len(shards):
        fail(f"shard count mismatch: expected={EXPECTED_SHARDS}, actual={len(shards)}")

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

    text_config = config.get("text_config") or config
    result = {
        "status": "PASS",
        "engine": ENGINE,
        "model_path": str(MODEL_PATH),
        "architecture": architectures,
        "model_type": model_type,
        "max_position_embeddings": text_config.get("max_position_embeddings"),
        "num_hidden_layers": text_config.get("num_hidden_layers"),
        "weight_shards": len(shards),
        "weight_bytes_from_index": indexed_bytes,
        "weight_bytes_on_disk": actual_bytes,
        "revision": revision,
        "runtime_registration": registration_source,
        "cli": check_cli(),
        "versions": {
            "sglang": package_version("sglang"),
            "vllm": package_version("vllm"),
            "transformers": package_version("transformers"),
            "torch": package_version("torch"),
            "flashinfer-python": package_version("flashinfer-python"),
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
