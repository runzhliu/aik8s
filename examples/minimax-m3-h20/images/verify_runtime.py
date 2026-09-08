#!/usr/bin/env python3
"""Run inside an official image without GPUs; emit evidence, never infer GPU support."""
import importlib.metadata as md
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

engine = sys.argv[1]
if engine not in ("sglang", "vllm"):
    raise SystemExit("engine must be sglang or vllm")
os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                  CUDA_VISIBLE_DEVICES="", NVIDIA_VISIBLE_DEVICES="void")
report = {"engine": engine, "gpu_validation": "not_run", "checks": {}}
for package in (engine, "torch", "transformers", "flashinfer-python", "av", "decord",
                "nixl", "nixl-cu12", "nixl-cu13", "cuda-python", "cuda-bindings", "cuda-pathfinder",
                "numpy", "pillow", "setuptools"):
    try:
        report.setdefault("versions", {})[package] = md.version(package)
    except md.PackageNotFoundError:
        report.setdefault("versions", {})[package] = None

def run(name, command):
    try:
        r = subprocess.run(command, capture_output=True, text=True, timeout=180)
        report["checks"][name] = {"returncode": r.returncode,
                                   "stdout": r.stdout, "stderr": r.stderr}
    except subprocess.TimeoutExpired:
        report["checks"][name] = {"returncode": 124, "error": "CPU probe timeout"}
    except OSError as exc:
        report["checks"][name] = {"returncode": 127, "error": str(exc)}

run("dependencies", [sys.executable, "-m", "pip", "check"])
run("torch", [sys.executable, "-c",
    "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available(), getattr(torch._C, '_cuda_getArchFlags', lambda: None)())"])
run("cli", ([sys.executable, "-m", "sglang.launch_server", "--help"]
            if engine == "sglang" else ["vllm", "serve", "--help=all"]))
gpu_cli_deferred = (engine == "vllm" and report["checks"]["cli"]["returncode"] != 0
                    and "Failed to infer device type" in report["checks"]["cli"].get("stderr", ""))
cpu_parser = ("import sys; import vllm.platforms as p; "
              "from vllm.platforms.cpu import CpuPlatform; p._current_platform=CpuPlatform(); "
              "from vllm.entrypoints.cli.main import main; ")
if gpu_cli_deferred:
    # Validate argument parsing only. Preserve the real GPU-discovery error above.
    run("cli_cpu_parse_only", [sys.executable, "-c", cpu_parser +
                              "sys.argv=['vllm','serve','--help=all']; main()"])
    report["cli_scope"] = "CPU argument parsing only; GPU CLI startup remains deferred"
run("video_av_roundtrip", [sys.executable, "-c", """
import io, av, numpy as np
buf=io.BytesIO()
with av.open(buf, mode='w', format='mp4') as out:
    stream=out.add_stream('mpeg4', rate=8)
    stream.width=64; stream.height=64; stream.pix_fmt='yuv420p'
    for i in range(8):
        frame=av.VideoFrame.from_ndarray(np.full((64,64,3), i*25, dtype=np.uint8), format='rgb24')
        for packet in stream.encode(frame): out.mux(packet)
    for packet in stream.encode(): out.mux(packet)
buf.seek(0)
with av.open(buf) as source: frames=list(source.decode(video=0))
assert len(frames)==8 and frames[0].width==64
print('AV_ROUNDTRIP_PASS', len(frames))
"""])
spec = importlib.util.find_spec(engine)
matches = []
if spec and spec.submodule_search_locations:
    for directory in spec.submodule_search_locations:
        for p in Path(directory).rglob("*minimax*m3*.py"):
            matches.append(str(p.relative_to(directory)))
report["model_source_files"] = sorted(matches)
required = (["--reasoning-parser", "--tool-call-parser", "--disable-radix-cache",
             "--mem-fraction-static", "--chunked-prefill-size", "--max-running-requests"]
            if engine == "sglang" else ["--block-size", "--reasoning-parser",
             "--tool-call-parser", "--max-model-len", "--enable-auto-tool-choice"])
help_text = report["checks"].get("cli_cpu_parse_only", report["checks"]["cli"]).get("stdout", "")
report["missing_cli_flags"] = [flag for flag in required if flag not in help_text]
report["missing_benchmark_flags"] = []
if engine == "vllm":
    if gpu_cli_deferred:
        run("benchmark_cli", [sys.executable, "-c", cpu_parser +
                              "sys.argv=['vllm','bench','serve','--help=all']; main()"])
    else:
        run("benchmark_cli", ["vllm", "bench", "serve", "--help=all"])
    bench_help = report["checks"]["benchmark_cli"].get("stdout", "")
    bench_flags = ["--random-input-len", "--random-output-len", "--num-prompts",
                   "--num-warmups", "--save-detailed", "--request-id-prefix",
                   "--ignore-eos", "--metric-percentiles", "--metadata"]
    report["missing_benchmark_flags"] = [f for f in bench_flags if f not in bench_help]
passed = (bool(matches) and not report["missing_cli_flags"] and
          not report["missing_benchmark_flags"] and
          all(c["returncode"] == 0 for name, c in report["checks"].items()
              if not (gpu_cli_deferred and name == "cli")))
report["status"] = ("CPU_PASS_GPU_CLI_DEFERRED" if gpu_cli_deferred else "CPU_PASS") if passed else "CPU_CHECK_INCOMPLETE"
print(json.dumps(report, ensure_ascii=False, indent=2))
raise SystemExit(0 if passed else 1)
