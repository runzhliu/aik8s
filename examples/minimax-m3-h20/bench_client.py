#!/usr/bin/env python3
"""CPU-only benchmark client for the pinned vLLM image; never starts a model server."""
import os
import sys

os.environ["CUDA_VISIBLE_DEVICES"] = ""
import vllm.platforms as platforms
from vllm.platforms.cpu import CpuPlatform

# This build initializes serve defaults while constructing the global CLI.
# Explicit CPU selection lets a zero-GPU HTTP load generator parse its arguments.
platforms._current_platform = CpuPlatform()
from vllm.entrypoints.cli.main import main

sys.argv = ["vllm", "bench", "serve", *sys.argv[1:]]
main()
