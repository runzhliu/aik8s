#!/usr/bin/env python3
"""Zero-GPU checkpoint and runtime preflight for moonshotai/Kimi-K3."""

from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess


MODEL_PATH = Path(os.getenv("MODEL_PATH", "/models-nvme/Kimi-K3/v1"))
ENGINE = os.getenv("ENGINE", "sglang").lower()
EXPECTED_REVISION = os.getenv("EXPECTED_REVISION")
CHECK_RUNTIME = os.getenv("CHECK_RUNTIME", "1") == "1"
MIN_WEIGHT_BYTES = int(os.getenv("MIN_WEIGHT_BYTES", "1500000000000"))

OUTER_ARCH = "KimiK3ForConditionalGeneration"
TEXT_ARCH = "KimiLinearForCausalLM"
OUTER_MODEL_TYPE = "kimi_k3"
TEXT_MODEL_TYPE = "kimi_linear"
EXPECTED_LAYERS = 93
EXPECTED_KDA_LAYERS = 69
EXPECTED_FULL_ATTN_LAYERS = 24
EXPECTED_EXPERTS = 896
EXPECTED_EXPERTS_PER_TOKEN = 16
EXPECTED_CONTEXT = 1_048_576
EXPECTED_QUANT_METHOD = "compressed-tensors"
EXPECTED_QUANT_FORMAT = "mxfp4-pack-quantized"


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


def runtime_contains(symbols: list[str]) -> dict[str, str]:
    package = "sglang" if ENGINE == "sglang" else "vllm"
    spec = importlib.util.find_spec(package)
    if spec is None or not spec.submodule_search_locations:
        fail(f"Python package {package!r} not found")

    remaining = set(symbols)
    found: dict[str, str] = {}
    for root_name in spec.submodule_search_locations:
        root = Path(root_name)
        for path in root.rglob("*.py"):
            try:
                content = path.read_bytes()
            except OSError:
                continue
            for symbol in list(remaining):
                if symbol.encode() in content:
                    found[symbol] = str(path)
                    remaining.remove(symbol)
            if not remaining:
                return found
    fail(f"symbols not found in installed {package} source: {sorted(remaining)}")
    raise AssertionError("unreachable")


def check_cli() -> dict:
    if ENGINE == "vllm":
        executable = shutil.which("vllm")
        if not executable:
            fail("vLLM CLI was not found in PATH")
        command = [executable, "serve", "--help=all"]
        required = [
            "--tensor-parallel-size",
            "--nnodes",
            "--node-rank",
            "--master-addr",
            "--max-model-len",
            "--moe-backend",
            "--disable-custom-all-reduce",
            "--no-enable-flashinfer-autotune",
            "--enable-auto-tool-choice",
            "--reasoning-parser",
            "--tool-call-parser",
            "--attention-backend",
        ]
    else:
        executable = shutil.which("python3") or shutil.which("python")
        if not executable:
            fail("Python executable was not found in PATH")
        command = [executable, "-m", "sglang.launch_server", "--help"]
        required = [
            "--tp-size",
            "--nnodes",
            "--node-rank",
            "--dist-init-addr",
            "--context-length",
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


def find_revision() -> str | None:
    candidates = [MODEL_PATH / "REVISION", MODEL_PATH / ".revision"]
    for path in candidates:
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


def main() -> int:
    if ENGINE not in {"sglang", "vllm"}:
        fail("ENGINE must be sglang or vllm")
    if not MODEL_PATH.is_dir():
        fail(f"model directory not found: {MODEL_PATH}")

    config = load_json(MODEL_PATH / "config.json")
    text_config = config.get("text_config") or {}
    linear_config = text_config.get("linear_attn_config") or {}
    quant = text_config.get("quantization_config") or {}
    config_groups = quant.get("config_groups") or {}
    group_0 = config_groups.get("group_0") or {}
    weights = group_0.get("weights") or {}

    checks = [
        (config.get("architectures") == [OUTER_ARCH], "outer architectures"),
        (config.get("model_type") == OUTER_MODEL_TYPE, "outer model_type"),
        (text_config.get("architectures") == [TEXT_ARCH], "text architectures"),
        (text_config.get("model_type") == TEXT_MODEL_TYPE, "text model_type"),
        (text_config.get("num_hidden_layers") == EXPECTED_LAYERS, "num_hidden_layers"),
        (text_config.get("num_experts") == EXPECTED_EXPERTS, "num_experts"),
        (
            text_config.get("num_experts_per_token") == EXPECTED_EXPERTS_PER_TOKEN,
            "num_experts_per_token",
        ),
        (
            text_config.get("max_position_embeddings") == EXPECTED_CONTEXT,
            "max_position_embeddings",
        ),
        (
            len(linear_config.get("kda_layers") or []) == EXPECTED_KDA_LAYERS,
            "KDA layer count",
        ),
        (
            len(linear_config.get("full_attn_layers") or [])
            == EXPECTED_FULL_ATTN_LAYERS,
            "full-attention layer count",
        ),
        (quant.get("quant_method") == EXPECTED_QUANT_METHOD, "quant_method"),
        (quant.get("format") == EXPECTED_QUANT_FORMAT, "quant format"),
        (group_0.get("format") == EXPECTED_QUANT_FORMAT, "group format"),
        (weights.get("num_bits") == 4, "weight num_bits"),
        (weights.get("group_size") == 32, "weight group_size"),
    ]
    failed = [name for passed, name in checks if not passed]
    if failed:
        fail(f"unexpected Kimi K3 config fields: {failed}")

    index = load_json(MODEL_PATH / "model.safetensors.index.json")
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
        fail(f"checkpoint incomplete: missing={missing[:10]}, empty={empty[:10]}")

    actual_bytes = sum((MODEL_PATH / name).stat().st_size for name in shards)
    indexed_bytes = (index.get("metadata") or {}).get("total_size")
    index_payload_bytes = int(indexed_bytes) if indexed_bytes is not None else None
    safetensors_overhead_bytes = None
    if index_payload_bytes is not None:
        safetensors_overhead_bytes = actual_bytes - index_payload_bytes
        # Hugging Face index metadata counts tensor payload bytes, while the
        # shard file sizes also include safetensors headers. Reject truncation
        # and implausible overhead, but do not require those quantities to be
        # byte-identical.
        max_header_overhead = max(1_073_741_824, index_payload_bytes // 100)
        if not 0 <= safetensors_overhead_bytes <= max_header_overhead:
            fail(
                "weight size mismatch: "
                f"index_payload={index_payload_bytes}, on_disk={actual_bytes}, "
                f"overhead={safetensors_overhead_bytes}"
            )
    if actual_bytes < MIN_WEIGHT_BYTES:
        fail(
            f"checkpoint is unexpectedly small: {actual_bytes} < {MIN_WEIGHT_BYTES} bytes"
        )

    tokenizer = require_any(
        "tokenizer", ["tokenizer.json", "tokenizer.model", "tiktoken.model"]
    )
    require_any("tokenizer config", ["tokenizer_config.json"])
    processor = require_any(
        "multimodal processor config",
        ["processor_config.json", "preprocessor_config.json"],
    )
    require_any(
        "chat template",
        ["chat_template.jinja", "tokenizer_config.json"],
    )

    revision = find_revision()
    if EXPECTED_REVISION and revision != EXPECTED_REVISION:
        fail(
            f"revision mismatch: expected={EXPECTED_REVISION!r}, actual={revision!r}"
        )

    runtime = None
    cli = None
    if CHECK_RUNTIME:
        runtime = runtime_contains([OUTER_ARCH, TEXT_ARCH])
        cli = check_cli()

    result = {
        "status": "PASS",
        "engine": ENGINE,
        "model_path": str(MODEL_PATH),
        "revision": revision,
        "architecture": {
            "outer": OUTER_ARCH,
            "text": TEXT_ARCH,
            "layers": EXPECTED_LAYERS,
            "kda_layers": EXPECTED_KDA_LAYERS,
            "full_attention_layers": EXPECTED_FULL_ATTN_LAYERS,
            "experts": EXPECTED_EXPERTS,
            "experts_per_token": EXPECTED_EXPERTS_PER_TOKEN,
            "max_position_embeddings": EXPECTED_CONTEXT,
        },
        "weights": {
            "shards": len(shards),
            "bytes": actual_bytes,
            "bytes_from_index": indexed_bytes,
            "safetensors_overhead_bytes": safetensors_overhead_bytes,
            "quant_method": quant.get("quant_method"),
            "format": quant.get("format"),
            "num_bits": weights.get("num_bits"),
            "group_size": weights.get("group_size"),
        },
        "assets": {"tokenizer": tokenizer, "processor": processor},
        "runtime_checked": CHECK_RUNTIME,
        "runtime_registration": runtime,
        "cli": cli,
        "versions": {
            "sglang": package_version("sglang"),
            "vllm": package_version("vllm"),
            "transformers": package_version("transformers"),
            "torch": package_version("torch"),
        },
        "resource_gate": (
            "requires at least two 8x141GB H20 nodes; 8x141GB and 16x96GB are insufficient"
        ),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False))
        raise
