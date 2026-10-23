"""Additive Grafana dashboard for actual controller-recorded HA measurements."""
import argparse
import json
from pathlib import Path

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--output', required=True, type=Path)
p.add_argument('--namespace', default='victoriametrics')
p.add_argument('--datasource', default='VictoriaMetrics')
p.add_argument('--view', choices=['control', 'proxy'], default='proxy')
a = p.parse_args()
ds = {'type': 'prometheus', 'uid': a.datasource}
panels = []


def panel(title, expr, x, y, legend, unit='short', maximum=None):
    defaults = {'unit': unit, 'min': 0, 'color': {'mode': 'palette-classic'},
                'custom': {'lineWidth': 2, 'fillOpacity': 7, 'showPoints': 'never', 'spanNulls': False,
                           'lineInterpolation': 'stepAfter'}}
    if maximum is not None:
        defaults['max'] = maximum
    panels.append({'id': len(panels) + 1, 'type': 'timeseries', 'title': title,
        'datasource': ds, 'gridPos': {'x': x, 'y': y, 'w': 12, 'h': 5},
        'targets': [{'refId': 'A', 'expr': expr, 'legendFormat': legend, 'range': True, 'instant': False, 'interval': '1s'}],
        'fieldConfig': {'defaults': defaults, 'overrides': []},
        'options': {'legend': {'displayMode': 'list', 'placement': 'bottom'}, 'tooltip': {'mode': 'multi'}}})


s = 'case=~"$case"'
panel('API list identity / minimum over 2s, 1 pass', 'min_over_time(cube_ha_probe_success{' + s + ',kind="list"}[2s])', 0, 0, '{{case}} {{route}}', maximum=1.1)
panel('Guest command identity / minimum over 2s', 'min_over_time(cube_ha_probe_success{' + s + ',kind="guest"}[2s])', 12, 0, '{{case}} {{route}}', maximum=1.1)
panel('New create + command + delete / all three required', 'cube_ha_lifecycle_success{' + s + '}', 0, 5, '{{case}}', maximum=1.1)
if a.view == 'proxy':
    panel('Original streaming connection / 1 open, 0 closed', 'cube_ha_stream_open{' + s + '}', 12, 5, '{{route}} {{protocol}}', maximum=1.1)
else:
    panel('API list probe duration / maximum over 2s', 'max_over_time(cube_ha_probe_latency_seconds{' + s + ',kind="list"}[2s])', 12, 5, '{{case}} {{route}}', unit='s')
panel('Same guest in-memory progress', 'cube_ha_guest_counter{' + s + '}', 0, 10, '{{case}} {{route}}')
panel('Stage / 0 baseline, 1 fault, 2 ready, 3 complete', 'cube_ha_stage{' + s + '}', 12, 10, '{{case}}', maximum=3.1)
dashboard = {'uid': 'cubesandbox-ha-drill', 'title': 'CubeSandbox / multi-replica failover experiment',
    'description': 'Actual lab-controller observations imported into VictoriaMetrics; not native product counters. Same-node replicas; no host failover claim.',
    'schemaVersion': 41, 'tags': ['Sandbox', 'fault-drill'], 'refresh': '5s', 'timezone': 'browser',
    'time': {'from': 'now-30m', 'to': 'now'}, 'panels': panels, 'annotations': {'list': []},
    'templating': {'list': [{'name': 'case', 'label': 'Case', 'type': 'query', 'datasource': ds,
        'query': {'query': 'label_values(cube_ha_stage,case)', 'refId': 'VariableQuery'},
        'refresh': 1, 'multi': True, 'includeAll': True, 'allValue': '.*', 'current': {'text': 'All', 'value': '$__all'}}]}}
if a.view == 'control':
    dashboard.update(uid='cubesandbox-ha-control', title='CubeSandbox / API and Master failover')
manifest = {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': 'cubesandbox-ha-drill-dashboard',
    'namespace': a.namespace, 'labels': {'victoriametrics_dashboard': '1'}},
    'data': {'cubesandbox-ha-drill.json': json.dumps(dashboard)}}
if a.view == 'control':
    manifest['metadata']['name'] = 'cubesandbox-ha-control-dashboard'
    manifest['data'] = {'cubesandbox-ha-control.json': json.dumps(dashboard)}
a.output.write_text(json.dumps(manifest, indent=2))
