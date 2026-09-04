#!/usr/bin/env python3
"""Zero-GPU checkpoint and runtime preflight for Qwen3.8-2.4T-A95B-FP8."""

from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess


MODEL_PATH = Path(
    os.getenv("MODEL_PATH", "/models-nvme/Qwen3.8-2.4T-A95B-FP8/v1")
)
ENGINE = os.getenv("ENGINE", "sglang").lower()
EXPECTED_REVISION = os.getenv("EXPECTED_REVISION")
CHECK_RUNTIME = os.getenv("CHECK_RUNTIME", "1") == "1"
EXPECTED_PAYLOAD_BYTES = int(os.getenv("EXPECTED_PAYLOAD_BYTES", "2496154358768"))

EXPECTED_ARCH = "Qwen3_5MoeForCausalLM"
EXPECTED_MODEL_TYPE = "qwen3_5_moe_text"
EXPECTED_LAYERS = 92
EXPECTED_LINEAR_LAYERS = 69
EXPECTED_FULL_LAYERS = 23
EXPECTED_EXPERTS = 512
EXPECTED_EXPERTS_PER_TOKEN = 10
EXPECTED_CONTEXT = 262_144
EXPECTED_SHARDS = 213


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


def find_revision() -> str | None:
    for name in ("REVISION", ".revision"):
        path = MODEL_PATH / name
        if path.is_file():
            return path.read_text(encoding="utf-8").strip()
    snapshot = MODEL_PATH.resolve()
    if snapshot.parent.name == "snapshots":
        return snapshot.name
    return None


def require_any(group_name: str, names: list[str]) -> str:
    for name in names:
        if (MODEL_PATH / name).is_file():
            return name
    fail(f"{group_name} was not found; expected one of {names}")
    raise AssertionError("unreachable")


def runtime_contains(symbol: str) -> str:
    package = "sglang" if ENGINE == "sglang" else "vllm"
    spec = importlib.util.find_spec(package)
    if spec is None or not spec.submodule_search_locations:
        fail(f"Python package {package!r} not found")
    needle = symbol.encode()
    for root_name in spec.submodule_search_locations:
        for path in Path(root_name).rglob("*.py"):
            try:
                if needle in path.read_bytes():
                    return str(path)
            except OSError:
                continue
    fail(f"symbol {symbol!r} not found in installed {package} source")
    raise AssertionError("unreachable")


def check_cli() -> dict:
    if ENGINE == "vllm":
        executable = shutil.which("vllm")
        if not executable:
            fail("vLLM CLI was not found in PATH")
        command = [executable, "serve", "--help=all"]
        required = [
            "--tensor-parallel-size",
            "--pipeline-parallel-size",
            "--nnodes",
            "--node-rank",
            "--master-addr",
            "--max-model-len",
            "--kv-cache-dtype",
            "--reasoning-parser",
            "--tool-call-parser",
        ]
    else:
        executable = shutil.which("sglang")
        command = [executable, "serve", "--help"] if executable else [
            shutil.which("python3") or "python3",
            "-m",
            "sglang.launch_server",
            "--help",
        ]
        required = [
            "--tp-size",
            "--pp-size",
            "--nnodes",
            "--node-rank",
            "--dist-init-addr",
            "--context-length",
            "--linear-attn-prefill-backend",
            "--linear-attn-decode-backend",
            "--mamba-full-memory-ratio",
            "--reasoning-parser",
            "--tool-call-parser",
        ]
    completed = subprocess.run(
        command, check=False, capture_output=True, text=True, timeout=180
    )
    output = f"{completed.stdout}\n{completed.stderr}"
    if completed.returncode:
        fail(f"CLI help failed with exit={completed.returncode}: {output[-3000:]}")
    missing = [flag for flag in required if flag not in output]
    if missing:
        fail(f"{ENGINE} CLI is missing required flags: {missing}")
    return {"command": command, "required_flags": required}


def main() -> int:
    if ENGINE not in {"sglang", "vllm"}:
        fail("ENGINE must be sglang or vllm")
    if not MODEL_PATH.is_dir():
        fail(f"model directory not found: {MODEL_PATH}")

    config = load_json(MODEL_PATH / "config.json")
    layer_types = config.get("layer_types") or []
    quant = config.get("quantization_config") or {}
    checks = [
        (config.get("architectures") == [EXPECTED_ARCH], "architectures"),
        (config.get("model_type") == EXPECTED_MODEL_TYPE, "model_type"),
        (config.get("num_hidden_layers") == EXPECTED_LAYERS, "num_hidden_layers"),
        (layer_types.count("linear_attention") == EXPECTED_LINEAR_LAYERS, "linear layers"),
        (layer_types.count("full_attention") == EXPECTED_FULL_LAYERS, "full-attention layers"),
        (config.get("num_experts") == EXPECTED_EXPERTS, "num_experts"),
        (config.get("num_experts_per_tok") == EXPECTED_EXPERTS_PER_TOKEN, "experts per token"),
        (config.get("num_attention_heads") == 64, "attention heads"),
        (config.get("num_key_value_heads") == 4, "KV heads"),
        (config.get("max_position_embeddings") == EXPECTED_CONTEXT, "context length"),
        (config.get("mtp_num_hidden_layers") == 1, "MTP head"),
        (quant.get("quant_method") == "fp8", "quant method"),
        (quant.get("weight_block_size") == [128, 128], "FP8 block size"),
    ]
    failed = [name for passed, name in checks if not passed]
    if failed:
        fail(f"unexpected model config fields: {failed}")

    index = load_json(MODEL_PATH / "model.safetensors.index.json")
    weight_map = index.get("weight_map") or {}
    shards = sorted(set(weight_map.values()))
    if len(shards) != EXPECTED_SHARDS:
        fail(f"unexpected shard count: {len(shards)} != {EXPECTED_SHARDS}")
    missing = [name for name in shards if not (MODEL_PATH / name).is_file()]
    empty = [
        name
        for name in shards
        if (MODEL_PATH / name).is_file() and not (MODEL_PATH / name).stat().st_size
    ]
    if missing or empty:
        fail(f"checkpoint incomplete: missing={missing[:10]}, empty={empty[:10]}")

    payload_bytes = int((index.get("metadata") or {}).get("total_size") or 0)
    if payload_bytes != EXPECTED_PAYLOAD_BYTES:
        fail(
            f"unexpected index payload bytes: {payload_bytes} != {EXPECTED_PAYLOAD_BYTES}"
        )
    actual_bytes = sum((MODEL_PATH / name).stat().st_size for name in shards)
    if actual_bytes < payload_bytes:
        fail(f"on-disk shards are truncated: {actual_bytes} < {payload_bytes}")

    tokenizer = require_any("tokenizer", ["tokenizer.json", "tokenizer.model"])
    require_any("tokenizer config", ["tokenizer_config.json"])
    chat_template = require_any("chat template", ["chat_template.jinja", "tokenizer_config.json"])
    generation_config = require_any("generation config", ["generation_config.json"])

    revision = find_revision()
    if EXPECTED_REVISION and revision != EXPECTED_REVISION:
        fail(f"revision mismatch: expected={EXPECTED_REVISION!r}, actual={revision!r}")

    runtime = runtime_contains(EXPECTED_ARCH) if CHECK_RUNTIME else None
    cli = check_cli() if CHECK_RUNTIME else None
    marker = MODEL_PATH / ".aik8s-complete"
    result = {
        "status": "PASS",
        "engine": ENGINE,
        "model_path": str(MODEL_PATH),
        "revision": revision,
        "complete_marker": marker.is_file(),
        "architecture": EXPECTED_ARCH,
        "layers": {"total": len(layer_types), "linear": 69, "full": 23},
        "experts": {"total": 512, "routed_per_token": 10, "shared": 1},
        "context_length": EXPECTED_CONTEXT,
        "quantization": quant,
        "shards": len(shards),
        "index_payload_bytes": payload_bytes,
        "on_disk_weight_bytes": actual_bytes,
        "tokenizer": tokenizer,
        "chat_template": chat_template,
        "generation_config": generation_config,
        "runtime_symbol": runtime,
        "runtime_version": package_version(ENGINE),
        "transformers_version": package_version("transformers"),
        "cli": cli,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
