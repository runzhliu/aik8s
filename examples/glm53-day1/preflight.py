#!/usr/bin/env python3
"""Zero-GPU checkpoint and runtime preflight for the full GLM-5.3 model."""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess

try:
    from importlib import metadata as importlib_metadata
except ImportError:  # Python 3.7 and earlier; checkpoint-only mode needs no package metadata.
    importlib_metadata = None


MODEL_PATH = Path(os.getenv("MODEL_PATH", "/models/GLM-5.3/v1"))
ENGINE = os.getenv("ENGINE", "checkpoint").lower()
EXPECTED_SHARDS = int(os.getenv("EXPECTED_SHARDS", "141"))
EXPECTED_INDEX_BYTES = os.getenv("EXPECTED_INDEX_BYTES")
EXPECTED_DISK_BYTES = os.getenv(
    "EXPECTED_DISK_BYTES", os.getenv("EXPECTED_WEIGHT_BYTES")
)
EXPECTED_REVISION = os.getenv("EXPECTED_REVISION")
ARCHITECTURE = "GlmMoeDsaForCausalLM"
MODEL_TYPE = "glm_moe_dsa"


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
    if importlib_metadata is None:
        return "not-installed"
    try:
        return importlib_metadata.version(package)
    except importlib_metadata.PackageNotFoundError:
        return "not-installed"


def runtime_contains(symbol: str):
    package = "sglang" if ENGINE == "sglang" else "vllm"
    spec = importlib.util.find_spec(package)
    if spec is None or not spec.submodule_search_locations:
        return False, f"Python package {package!r} not found"

    needle = symbol.encode("utf-8")
    roots = [Path(item) for item in spec.submodule_search_locations]
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
            "--context-length",
            "--max-running-requests",
            "--chunked-prefill-size",
            "--mem-fraction-static",
            "--disable-radix-cache",
            "--dsa-prefill-backend",
            "--dsa-decode-backend",
            "--speculative-algorithm",
            "--reasoning-parser",
            "--tool-call-parser",
            "--enable-metrics",
        ]
        if ENGINE == "sglang"
        else [
            "--tensor-parallel-size",
            "--kv-cache-dtype",
            "--speculative-config",
            "--max-model-len",
            "--max-num-seqs",
            "--no-enable-prefix-caching",
            "--reasoning-parser",
            "--tool-call-parser",
        ]
    )
    missing = [flag for flag in required if flag not in output]
    if missing:
        fail(f"{ENGINE} CLI is missing required flags: {missing}")
    return {"executable": executable, "required_flags": required}


def main() -> int:
    if ENGINE not in {"checkpoint", "sglang", "vllm"}:
        fail("ENGINE must be checkpoint, sglang or vllm")
    if not MODEL_PATH.is_dir():
        fail(f"model directory not found: {MODEL_PATH}")

    config = load_json(MODEL_PATH / "config.json")
    index = load_json(MODEL_PATH / "model.safetensors.index.json")
    architectures = config.get("architectures") or []
    if ARCHITECTURE not in architectures:
        fail(f"unexpected architectures: {architectures!r}")
    if config.get("model_type") != MODEL_TYPE:
        fail(f"unexpected model_type: {config.get('model_type')!r}")

    weight_map = index.get("weight_map") or {}
    shards = sorted(set(weight_map.values()))
    if len(shards) != EXPECTED_SHARDS:
        fail(f"shard count mismatch: expected={EXPECTED_SHARDS}, actual={len(shards)}")
    missing = [name for name in shards if not (MODEL_PATH / name).is_file()]
    empty = [
        name
        for name in shards
        if (MODEL_PATH / name).is_file() and (MODEL_PATH / name).stat().st_size == 0
    ]
    if missing or empty:
        fail(f"checkpoint is incomplete: missing={missing[:5]}, empty={empty[:5]}")

    actual_bytes = sum((MODEL_PATH / name).stat().st_size for name in shards)
    indexed_bytes = (index.get("metadata") or {}).get("total_size")
    if indexed_bytes is None:
        fail("weight index metadata.total_size is missing")
    if EXPECTED_INDEX_BYTES and int(EXPECTED_INDEX_BYTES) != int(indexed_bytes):
        fail(
            f"index tensor-byte mismatch: expected={EXPECTED_INDEX_BYTES}, "
            f"actual={indexed_bytes}"
        )
    if EXPECTED_DISK_BYTES and int(EXPECTED_DISK_BYTES) != actual_bytes:
        fail(
            f"on-disk shard-byte mismatch: expected={EXPECTED_DISK_BYTES}, "
            f"actual={actual_bytes}"
        )

    required_files = [
        "config.json",
        "generation_config.json",
        "model.safetensors.index.json",
        "tokenizer.json",
        "tokenizer_config.json",
    ]
    absent = [name for name in required_files if not (MODEL_PATH / name).is_file()]
    if absent:
        fail(f"required model artifacts are missing: {absent}")

    temporary = [
        str(path.relative_to(MODEL_PATH))
        for path in MODEL_PATH.rglob("*")
        if path.is_file()
        and any(token in path.name.lower() for token in (".incomplete", ".part", ".tmp"))
    ]
    if temporary:
        fail(f"temporary/incomplete files remain: {temporary[:20]}")

    revision_files = [MODEL_PATH / "REVISION", MODEL_PATH / ".revision"]
    revision = next(
        (path.read_text(encoding="utf-8").strip() for path in revision_files if path.is_file()),
        None,
    )
    if EXPECTED_REVISION and revision != EXPECTED_REVISION:
        fail(f"revision mismatch: expected={EXPECTED_REVISION!r}, actual={revision!r}")

    quantization = config.get("quantization_config") or {}
    if quantization.get("quant_method") != "fp8":
        fail(f"expected native FP8 checkpoint, got {quantization!r}")
    if config.get("num_nextn_predict_layers") != 1:
        fail("expected exactly one MTP/nextn layer")

    result = {
        "status": "PASS",
        "engine": ENGINE,
        "model_path": str(MODEL_PATH),
        "architecture": architectures,
        "model_type": config.get("model_type"),
        "quant_method": quantization.get("quant_method"),
        "max_position_embeddings": config.get("max_position_embeddings"),
        "num_hidden_layers": config.get("num_hidden_layers"),
        "num_nextn_predict_layers": config.get("num_nextn_predict_layers"),
        "weight_shards": len(shards),
        "weight_bytes_from_index": int(indexed_bytes),
        "weight_bytes_on_disk": actual_bytes,
        "weight_gib_from_index": round(int(indexed_bytes) / 1024**3, 3),
        "revision": revision,
    }
    if ENGINE != "checkpoint":
        registered, registration_source = runtime_contains(ARCHITECTURE)
        if not registered:
            fail(registration_source)
        result.update(
            {
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
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False))
        raise
