#!/usr/bin/env python3
"""Count unique Karmada CRD definitions in a pinned upstream source revision.

Requires gh (GitHub CLI) and PyYAML. Does not access or modify any cluster.
Example: python inventory_karmada_crds.py --ref v1.18.0 --output inventory.json
Counts actual YAML kind=CustomResourceDefinition, deduplicated by metadata.name.
The main chart bundle and optional operator are reported separately.
"""
import argparse
import base64
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import yaml

REPO = 'karmada-io/karmada'
MAIN = 'charts/karmada/_crds/bases/'
OPERATOR = 'operator/config/crds/'

def api(endpoint):
    p = subprocess.run(['gh', 'api', endpoint], capture_output=True, text=True, timeout=90, check=True)
    return json.loads(p.stdout)

def inventory(ref):
    commit = api(f'repos/{REPO}/commits/{ref}')['sha']
    tree = api(f'repos/{REPO}/git/trees/{commit}?recursive=1')
    if tree.get('truncated'):
        raise RuntimeError('Refusing to count an incomplete Git tree')
    files = [x for x in tree['tree'] if x['type'] == 'blob' and x['path'].endswith(('.yaml', '.yml'))
             and x['path'].startswith((MAIN, OPERATOR))]
    print(f'Reading {len(files)} candidate manifests at {ref} ({commit[:12]})', flush=True)

    def parse(entry):
        blob = api(f'repos/{REPO}/git/blobs/{entry["sha"]}')
        raw = base64.b64decode(blob['content'])
        rows = []
        for doc in yaml.safe_load_all(raw):
            if not isinstance(doc, dict) or doc.get('kind') != 'CustomResourceDefinition':
                continue
            spec = doc['spec']
            rows.append({'name': doc['metadata']['name'], 'kind': spec['names']['kind'],
                         'group': spec['group'], 'scope': spec['scope'],
                         'versions': [v['name'] for v in spec['versions']],
                         'served_versions': [v['name'] for v in spec['versions'] if v.get('served')],
                         'bundle': 'main' if entry['path'].startswith(MAIN) else 'operator',
                         'source_path': entry['path'], 'git_blob_sha': entry['sha'],
                         'source_url': f'https://github.com/{REPO}/blob/{commit}/{entry["path"]}'})
        return rows

    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = [r for result in pool.map(parse, files) for r in result]
    unique = {}
    for row in rows:
        if row['name'] in unique and unique[row['name']] != row:
            raise RuntimeError('Unexpected duplicate definition: ' + row['name'])
        unique[row['name']] = row
    rows = sorted(unique.values(), key=lambda x: (x['bundle'], x['group'], x['name']))
    return {'repository': REPO, 'ref': ref, 'commit': commit, 'tree_sha': tree['sha'],
            'counting_rule': 'Unique metadata.name of kind CustomResourceDefinition in main chart bases and operator/config/crds; versions are not separate CRDs; examples, patch files and duplicate packaging copies are excluded.',
            'main_bundle_count': sum(r['bundle'] == 'main' for r in rows),
            'operator_bundle_count': sum(r['bundle'] == 'operator' for r in rows),
            'unique_union_count': len(rows),
            'main_groups': dict(sorted(Counter(r['group'] for r in rows if r['bundle'] == 'main').items())),
            'crds': rows}

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ref', default='v1.18.0')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = inventory(args.ref)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'crds'}, ensure_ascii=False))
    for row in result['crds']:
        print(row['bundle'], row['kind'], row['scope'], ','.join(row['served_versions']), row['name'])
