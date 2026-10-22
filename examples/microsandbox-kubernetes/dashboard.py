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
                     'instant': False, 'range': True}],
        'fieldConfig': {'defaults': {'unit': unit, 'min': 0, 'color': {'mode': 'palette-classic'},
            'custom': {'lineWidth': 2, 'fillOpacity': 12, 'showPoints': 'never', 'spanNulls': False}}, 'overrides': []},
        'options': {'reduceOptions': {'calcs': ['lastNotNull'], 'values': False, 'fields': ''},
                    'colorMode': 'value', 'graphMode': 'none',
                    'legend': {'displayMode': 'list', 'placement': 'bottom', 'showLegend': True},
                    'tooltip': {'mode': 'multi'}}})


selector = '{job="microsandbox-lab"}'
for i, (title, metric, unit) in enumerate([
    ('Tracked active guests', 'running_boxes', 'short'), ('Passed checks', 'passed_checks', 'short'),
    ('Failed checks', 'failed_checks', 'short'), ('Latest create', 'last_start_seconds', 's')]):
    panel(title, 'max(microsandbox_lab_' + metric + selector + ')', 'stat', (i * 6, 0, 6, 3), unit, title)
panel('Active guests / application registry', 'max(microsandbox_lab_running_boxes' + selector + ')',
      'timeseries', (0, 3, 12, 5), 'short', 'Tracked guests')
panel('Runner container / CPU', 'sum(rate(microsandbox_lab_container_cpu_seconds_total{job="microsandbox-lab"}[30s]))',
      'timeseries', (12, 3, 12, 5), 'cores', 'Container CPU cores')
panel('Runner container / working set', 'max(microsandbox_lab_container_working_set_bytes{job="microsandbox-lab"})',
      'timeseries', (0, 8, 12, 5), 'bytes', 'Container memory')
panel('Native collector / four CPU guests', 'sum({__name__="microsandbox.cpu.utilization","sandbox.name"=~"cpu-.*"})',
      'timeseries', (12, 8, 12, 5), 'cores', 'Guest vCPU cores')
panels[2]['fieldConfig']['defaults']['thresholds'] = {'mode': 'absolute', 'steps': [{'color': 'green', 'value': None}, {'color': 'red', 'value': 1}]}
panels[2]['fieldConfig']['defaults']['color'] = {'mode': 'thresholds'}
dashboard = {'uid': 'microsandbox-kvm-lab', 'title': 'Microsandbox / KVM lifecycle lab', 'schemaVersion': 41,
    'tags': ['Microsandbox', 'lab'], 'timezone': 'browser', 'refresh': '5s',
    'time': {'from': 'now-15m', 'to': 'now'}, 'panels': panels,
    'annotations': {'list': []}, 'templating': {'list': []}}
manifest = {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {
    'name': 'microsandbox-lab-dashboard', 'namespace': 'victoriametrics',
    'labels': {'victoriametrics_dashboard': '1'}},
    'data': {'microsandbox-lab.json': json.dumps(dashboard)}}
panels = []
native = '{"sandbox.name"=~"cpu-.*","service.instance.id"="kvm-lab"}'
def native_expr(suffix):
    return '{__name__="microsandbox.' + suffix + '",' + native[1:]
for i, (title, suffix, unit) in enumerate([
    ('Peak guest vCPU cores', 'cpu.utilization', 'cores'),
    ('Peak guest used memory', 'memory.usage', 'bytes'),
    ('Peak host-resident RAM', 'memory.host_resident', 'bytes'),
    ('Peak configured guest RAM', 'memory.limit', 'bytes')]):
    panel(title, 'max_over_time(sum(' + native_expr(suffix) + ')[$__range:2s])',
          'stat', (i * 6, 0, 6, 3), unit, title)
for title, suffix, pos, unit in [
    ('Native collector / per-guest CPU', 'cpu.utilization', (0, 3, 12, 5), 'cores'),
    ('Guest memory in use', 'memory.usage', (12, 3, 12, 5), 'bytes'),
    ('Host-resident guest memory', 'memory.host_resident', (0, 8, 12, 5), 'bytes'),
    ('Configured guest RAM / not actual consumption', 'memory.limit', (12, 8, 12, 5), 'bytes')]:
    panel(title, native_expr(suffix), 'timeseries', pos, unit, '{{sandbox.name}}')
native_dashboard = {**dashboard, 'uid': 'microsandbox-native-lab',
                    'title': 'Microsandbox / native OTLP metrics', 'panels': panels}
manifest['data']['microsandbox-native.json'] = json.dumps(native_dashboard)
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--output', type=Path, required=True)
a = p.parse_args()
a.output.write_text(json.dumps(manifest))
