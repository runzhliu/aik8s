"""Whitelist export of measured HA results; raw configuration never published."""
import argparse
import csv
import json
from pathlib import Path

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--private-dir', required=True, type=Path)
p.add_argument('--output-dir', required=True, type=Path)
a = p.parse_args()
raw = json.loads((a.private_dir / 'run.json').read_text())
result = {k: raw[k] for k in ('started', 'ended', 'scope', 'result', 'source_sha256')}
result['tls_passthrough'] = raw.get('tls_passthrough')
result['cleanup'] = {k: v for k, v in raw['cleanup'].items() if k in ('remaining_sandboxes', 'new_exec', 'final_inventory')}
result['actual_shim_sha256'] = raw.get('runtime', [{}])[0].get('executable_sha256')
result['initial_counter'] = raw['initial_state']['counter']
result['preparation_attempts'] = [{'id': 'preflight-a01', 'injected': False,
    'outcome': 'HTTP 404 before fault injection: fixture port 18080 was not exposed by the template',
    'next_variant': 'Use the existing envd 49983 port for commands and Connect command streams; guest state server stays loopback-accessed'}]
result['preparation_attempts'].append({'id': 'template-preparation', 'injected': False,
    'outcome': 'A separate template build failed its port-49999 health probe; it was not used for measured fault injection'})
result['cases'] = []
for row in raw['cases']:
    out = {k: row[k] for k in ('case', 'component', 'started', 'phases', 'result')}
    out['samples'] = [{k: s[k] for k in ('at', 'route', 'kind', 'stage', 'ok', 'status', 'seconds', 'counter', 'identity_same', 'error') if k in s} for s in row['samples']]
    out['lifecycle'] = [{k: s[k] for k in ('at', 'stage', 'create', 'exec', 'delete', 'seconds', 'ok', 'error', 'cleanup_via_original_api', 'cleanup_error') if k in s} for s in row['lifecycle']]
    out['streams'] = [{k: s[k] for k in ('route', 'kind', 'opened', 'connected', 'frames', 'closed', 'controller_closed', 'error') if k in s} for s in row['streams']]
    out['identity_preserved'] = row['after_state']['identity'] == raw['initial_state']['identity']
    out['after_counter'] = row['after_state']['counter']
    out['summary'] = []
    for route in ('L4', 'L7'):
        for kind in ('list', 'guest'):
            samples = [s for s in out['samples'] if s['route'] == route and s['kind'] == kind and s['at'] >= row['phases'].get('fault_issued', float('inf'))]
            failures = [s for s in samples if not s['ok']]
            # This is time to the next observed success, not a continuous outage bound.
            next_success = next((s for s in samples if failures and s['ok'] and s['at'] > failures[0]['at']), None)
            out['summary'].append({'route': route, 'kind': kind, 'successes': sum(s['ok'] for s in samples), 'attempts': len(samples),
                'failed_samples': len(failures), 'first_failure_to_next_success_seconds': round(next_success['at'] - failures[0]['at'], 3) if next_success else None})
    result['cases'].append(out)
a.output_dir.mkdir(parents=True, exist_ok=True)
(a.output_dir / 'results.json').write_text(json.dumps(result, indent=2) + '\n')
with (a.output_dir / 'probes.csv').open('w') as f:
    fields = ['case', 'at', 'route', 'kind', 'stage', 'ok', 'status', 'seconds', 'counter', 'identity_same', 'error']
    writer = csv.DictWriter(f, fieldnames=fields, lineterminator='\n')
    writer.writeheader()
    for row in result['cases']:
        for sample in row['samples']:
            writer.writerow({'case': row['case'], **sample})
print(json.dumps([{k: c[k] for k in ('case', 'result', 'summary', 'identity_preserved')} for c in result['cases']], indent=2))
