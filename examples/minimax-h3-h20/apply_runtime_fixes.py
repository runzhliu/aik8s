#!/usr/bin/env python3
"""Apply opt-in, source-hash-pinned H3 fixes before starting the server."""
import argparse
import hashlib
import json
from pathlib import Path


def apply(engine, root, evidence):
    manifest = json.loads(Path(__file__).with_name('runtime-fixes.json').read_text())
    rows = []
    pending = []
    for patch in manifest['patches']:
        if patch['engine'] != engine:
            continue
        target = root / patch['path']
        original = target.read_bytes()
        digest = hashlib.sha256(original).hexdigest()
        if digest == patch['after_sha256']:
            rows.append(dict(path=str(target), status='already-applied', sha256=digest))
            continue
        if digest != patch['before_sha256']:
            raise RuntimeError('Unrecognized source; refusing patch: ' + str(target))
        changed = original.decode()
        for replacement in patch['replacements']:
            assert changed.count(replacement['old']) == replacement['count']
            changed = changed.replace(replacement['old'], replacement['new'])
        assert hashlib.sha256(changed.encode()).hexdigest() == patch['after_sha256']
        compile(changed, str(target), 'exec')
        pending.append((patch, target, original, changed))
    # Validate every target before changing any file. Preserve exact originals.
    evidence.mkdir(parents=True, exist_ok=True)
    for patch, target, original, changed in pending:
        backup = evidence / 'originals' / patch['path']
        backup.parent.mkdir(parents=True, exist_ok=True)
        if backup.exists():
            assert backup.read_bytes() == original
        else:
            backup.write_bytes(original)
        target.write_text(changed)
        rows.append(dict(path=str(target), status='applied',
                         before_sha256=patch['before_sha256'], sha256=patch['after_sha256']))
    report = dict(fix_id=manifest['id'], engine=engine, files=rows)
    (evidence / 'applied.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--engine', required=True, choices=['sglang', 'vllm-omni'])
    p.add_argument('--root', type=Path)
    p.add_argument('--evidence', type=Path, required=True)
    a = p.parse_args()
    engine = 'vllm' if a.engine == 'vllm-omni' else a.engine
    root = a.root or Path('/opt/h3-vllm-omni' if engine == 'vllm' else
        '/usr/local/lib/python3.12/dist-packages/sglang/multimodal_gen/runtime')
    apply(engine, root, a.evidence)
