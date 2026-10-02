#!/usr/bin/env python3
"""Verify local checkpoint identity against a pinned upstream file manifest."""
import hashlib
import json
import os
from pathlib import Path
import time

p = Path(os.environ['MODEL_PATH'])
manifest = json.loads(Path('/scripts/upstream-manifest.json').read_text())
marker = json.loads((p / '.aik8s-complete').read_text())
index_raw = (p / 'model.safetensors.index.json').read_bytes()
index = json.loads(index_raw)
assert hashlib.sha256(index_raw).hexdigest() == marker['index_sha256']
assert len(set(index['weight_map'].values())) == 213
verified = []
for name in sorted(set(index['weight_map'].values()) | set(manifest['aux'])):
    f = p / name
    expected = manifest['files'][name]
    assert f.is_file() and not f.is_symlink(), name
    assert f.stat().st_size == expected['size'], (name, f.stat().st_size, expected['size'])
    if not name.endswith('.safetensors'):
        raw = f.read_bytes()
        if expected.get('lfs'):
            digest = hashlib.sha256(raw).hexdigest()
            assert digest == expected['lfs']['sha256'], name
        else:
            digest = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
            assert digest == expected['blobId'], name
    verified.append(name)
assert marker['shards'] == 213 and marker['payload_bytes'] == index['metadata']['total_size']
revision = p / 'REVISION'
if revision.exists():
    assert revision.read_text().strip() == manifest['revision'], 'existing revision differs'
# Revision identity comes from the pinned file manifest; keep the model mount read-only.
result = {'status':'PASS', 'at':time.time(), 'revision':manifest['revision'],
          'index_sha256':marker['index_sha256'], 'payload_bytes':index['metadata']['total_size'],
          'verified_file_count':len(verified), 'shards':213,
          'verification':'upstream auxiliary content hashes, all shard sizes, existing header/extent validation; no full weight hashing'}
Path('/outputs').mkdir(exist_ok=True)
Path('/outputs/model-identity.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result),flush=True)
