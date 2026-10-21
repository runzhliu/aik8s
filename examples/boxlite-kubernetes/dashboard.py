"""Render a dashboard ConfigMap; contains no private endpoints or credentials."""
import json
import argparse
from pathlib import Path

ds = {'type': 'prometheus', 'uid': 'VictoriaMetrics'}
panels = []


def panel(title, expr, kind, position, unit, legend):
    panels.append({'id': len(panels) + 1, 'type': kind, 'title': title, 'datasource': ds,
        'gridPos': dict(zip(['x', 'y', 'w', 'h'], position)),
        'targets': [{'refId': 'A', 'expr': expr, 'legendFormat': legend,
                     'instant': kind == 'stat', 'range': kind != 'stat'}],
        'fieldConfig': {'defaults': {'unit': unit, 'min': 0, 'color': {'mode': 'palette-classic'},
            'custom': {'lineWidth': 2, 'fillOpacity': 12, 'showPoints': 'never', 'spanNulls': False}}, 'overrides': []},
        'options': {'reduceOptions': {'calcs': ['lastNotNull'], 'values': False, 'fields': ''},
                    'colorMode': 'value', 'graphMode': 'none',
                    'legend': {'displayMode': 'list', 'placement': 'bottom', 'showLegend': True},
                    'tooltip': {'mode': 'multi'}}})


selector = '{job="boxlite-lab"}'
for i, (title, metric, unit) in enumerate([
    ('SDK derived running count', 'running_boxes', 'short'), ('Passed checks', 'completed_checks', 'short'),
    ('Failed checks', 'failed_checks', 'short'), ('Latest cached start', 'last_start_seconds', 's')]):
    panel(title, 'max(boxlite_lab_' + metric + selector + ')', 'stat', (i * 6, 0, 6, 3), unit, title)
panel('SDK running count / counter-derived', 'max(boxlite_lab_running_boxes' + selector + ')',
      'timeseries', (0, 3, 12, 5), 'short', 'SDK count')
panel('Runner container / CPU', 'sum(rate(boxlite_lab_container_cpu_seconds_total{job="boxlite-lab"}[30s]))',
      'timeseries', (12, 3, 12, 5), 'cores', 'Container CPU cores')
panel('Runner container / working set', 'max(boxlite_lab_container_working_set_bytes{job="boxlite-lab"})',
      'timeseries', (0, 8, 12, 5), 'bytes', 'Container memory')
panel('Checks completed / evidence records', 'max(boxlite_lab_completed_checks' + selector + ')',
      'timeseries', (12, 8, 12, 5), 'short', 'Passed checks')
dashboard = {'uid': 'boxlite-kvm-lab', 'title': 'BoxLite / KVM lifecycle lab', 'schemaVersion': 41,
    'tags': ['BoxLite', 'lab'], 'timezone': 'browser', 'refresh': '5s',
    'time': {'from': 'now-15m', 'to': 'now'}, 'panels': panels,
    'annotations': {'list': []}, 'templating': {'list': []}}
manifest = {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {
    'name': 'boxlite-lab-dashboard', 'namespace': 'victoriametrics',
    'labels': {'victoriametrics_dashboard': '1'}},
    'data': {'boxlite-lab.json': json.dumps(dashboard)}}
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--output', type=Path, required=True)
a = p.parse_args()
a.output.write_text(json.dumps(manifest))
