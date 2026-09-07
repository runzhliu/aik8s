#!/usr/bin/env python3
"""Preserve rejected SGLang video files for this benchmark's evidence retention.

Pinned source-only patch: does not change validation, job failure or inference.
"""
import hashlib
from pathlib import Path

path = Path('/opt/h3-sglang/python/sglang/multimodal_gen/runtime/entrypoints/openai/video_api.py')
original = path.read_bytes()
old = b'                    os.remove(output_path)'
new = b'                    logger.warning("Retained rejected benchmark output: %s", output_path)'
expected = '446b3616c29a1b155619ff94d8460fedeeeb490a877abd0a0488b13f378d2247'
if new in original and old not in original:
    print('output-retention patch already present')
else:
    assert hashlib.sha256(original).hexdigest() == expected, 'pinned video API source changed'
    assert original.count(old) == 1, 'retention patch target must be unique'
    patched = original.replace(old, new)
    compile(patched, str(path), 'exec')
    path.write_bytes(patched)
    print('output-retention patched sha256=' + hashlib.sha256(patched).hexdigest())
