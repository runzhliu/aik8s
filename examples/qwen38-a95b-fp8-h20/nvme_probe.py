#!/usr/bin/env python3
"""Read-only NVMe capacity probe; supports the cached image's Python 3.6."""
import json
import os
import pathlib
import shutil
import subprocess


def probe(root='/host-data', required_bytes=2496066252544 + 1000000000,
          reserve_bytes=300000000000):
    path = pathlib.Path(root) / 'model-cache'
    if not path.exists():
        path = pathlib.Path(root)
    st = path.stat()
    device = '{}:{}'.format(os.major(st.st_dev), os.minor(st.st_dev))
    leaves = []

    def walk(p):
        p = p.resolve()
        children = list((p / 'slaves').iterdir()) if (p / 'slaves').exists() else []
        if children:
            for child in children:
                walk(child)
        else:
            leaves.append(p.name)
    walk(pathlib.Path('/sys/dev/block') / device)
    nvme = bool(leaves) and all(x.startswith('nvme') for x in leaves)
    usage = shutil.disk_usage(str(path))
    dest = pathlib.Path(root) / 'model-cache/Qwen3.8-2.4T-A95B-FP8/v1'
    # Existing bytes are reported, not credited without validation.
    existing = sum(p.stat().st_size for p in dest.glob('*') if p.is_file()) if dest.exists() else 0
    mount = subprocess.check_output(['findmnt', '-J', '-T', str(path)], universal_newlines=True)
    return {'node': os.environ.get('NODE_NAME'), 'path': str(path), 'device': device,
            'backing_devices': leaves, 'nvme': nvme, 'total_bytes': usage.total,
            'free_bytes': usage.free, 'required_model_bytes': required_bytes,
            'reserve_bytes': reserve_bytes, 'existing_model_bytes': existing,
            'eligible': nvme and usage.free >= required_bytes + reserve_bytes,
            'mount': json.loads(mount)}


if __name__ == '__main__':
    print(json.dumps(probe(), sort_keys=True))
