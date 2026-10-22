"""Render fault Pods alongside existing lab PVCs, without modifying existing Deployments."""
import argparse
import json
from pathlib import Path

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--node', required=True)
p.add_argument('--microsandbox-image', required=True)
p.add_argument('--boxlite-image', required=True)
p.add_argument('--guest-image', default='docker.io/library/python:3.12-slim')
p.add_argument('--registry-skip-verify', action='store_true', help='Explicit lab-only exception for guest registry TLS')
p.add_argument('--output', required=True, type=Path)
a = p.parse_args()
root = Path(__file__).parent
manifest = json.loads((root / 'manifest-template.json').read_text())
for item in manifest['items']:
    if item['kind'] == 'ConfigMap':
        files = ['receiver.py', 'index.html'] if item['metadata']['namespace'] == 'sandbox-fault-lab' else ['sdk_worker.py', 'guest_probe.py']
        item['data'] = {f: (root / f).read_text() for f in files}
    if item['kind'] == 'Deployment':
        spec = item['spec']['template']['spec']
        spec['nodeSelector']['kubernetes.io/hostname'] = a.node
        container = spec['containers'][0]
        container['image'] = a.boxlite_image if container['image'] == 'BOXLITE_IMAGE' else a.microsandbox_image
        for env in container.get('env', []):
            if env['name'] == 'GUEST_IMAGE':
                env['value'] = a.guest_image
            if env['name'] == 'REGISTRY_SKIP_VERIFY':
                env['value'] = str(a.registry_skip_verify).lower()
a.output.mkdir(parents=True, exist_ok=True)
(a.output / 'install.json').write_text(json.dumps(manifest, indent=2))
print(a.output / 'install.json')
