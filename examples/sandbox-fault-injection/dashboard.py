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


panels = []
for i, (title, expr, unit) in enumerate([
    ('Allowed requests / restricted tests', 'sum(increase(sandbox_fault_receiver_requests_total{role="allow",case=~"microsandbox-(sdk|vmm|pod)-a01|boxlite-(vmm|pod)-a01|boxlite-sdk-a02"}[$__range]))', 'short'),
    ('Denied requests / restricted tests', 'sum(increase(sandbox_fault_receiver_requests_total{role="deny",case=~"microsandbox-(sdk|vmm|pod)-a01|boxlite-(vmm|pod)-a01|boxlite-sdk-a02"}[$__range]))', 'short'),
    ('Unrestricted target-B control', 'sum(increase(sandbox_fault_receiver_requests_total{role="deny",case=~".*control.*"}[$__range]))', 'short')]):
    panel(title, expr, 'stat', (i * 8, 0, 8, 3), unit, title)
for title, expr, pos, unit in [
    ('Microsandbox / allowed requests', 'sum by(case)(rate(sandbox_fault_receiver_requests_total{role="allow",case=~"microsandbox-.*",case=~"microsandbox-(sdk|vmm|pod)-a01|boxlite-(vmm|pod)-a01|boxlite-sdk-a02"}[8s]))', (0,3,12,5), 'reqps'),
    ('BoxLite / allowed requests', 'sum by(case)(rate(sandbox_fault_receiver_requests_total{role="allow",case=~"boxlite-.*",case=~"microsandbox-(sdk|vmm|pod)-a01|boxlite-(vmm|pod)-a01|boxlite-sdk-a02"}[8s]))', (12,3,12,5), 'reqps'),
    ('Denied-target receipts / restricted cases', 'sum by(case)(sandbox_fault_receiver_requests_total{role="deny",case=~"microsandbox-(sdk|vmm|pod)-a01|boxlite-(vmm|pod)-a01|boxlite-sdk-a02"})', (0,8,12,5), 'short'),
    ('Stage: 0 baseline / 1 fault / 3 complete', 'max by(case)(sandbox_fault_case_phase{case=~"microsandbox-(sdk|vmm|pod)-a01|boxlite-(vmm|pod)-a01|boxlite-sdk-a02"})', (12,8,12,5), 'short')]:
    panel(title, expr, 'timeseries', pos, unit, '{{case}}')
dashboard={'uid':'sandbox-fault-lab','title':'Sandbox fault injection / independent receivers','schemaVersion':41,
    'tags':['Sandbox','fault-lab'],'timezone':'browser','refresh':'5s','time':{'from':'now-30m','to':'now'},
    'panels':panels,'annotations':{'list':[]},'templating':{'list':[]}}
manifest={'apiVersion':'v1','kind':'ConfigMap','metadata':{'name':'sandbox-fault-dashboard','namespace':'victoriametrics',
    'labels':{'victoriametrics_dashboard':'1'}},'data':{'sandbox-fault.json':json.dumps(dashboard)}}
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--output', type=Path, required=True)
a = p.parse_args()
a.output.write_text(json.dumps(manifest))
