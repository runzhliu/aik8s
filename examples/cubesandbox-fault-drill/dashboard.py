"""Render additive Grafana evidence dashboards; no private endpoints."""
import argparse
import json
from pathlib import Path

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--output', required=True, type=Path)
a = p.parse_args()
panels = []
ds = {'type': 'prometheus', 'uid': 'VictoriaMetrics'}


def panel(title, expression, position, unit='short', kind='timeseries'):
    panels.append({'id': len(panels)+1, 'title': title, 'type': kind,
        'datasource': ds, 'gridPos': dict(zip(('x','y','w','h'),position)),
        'interval':'2s',
        'targets':[{'refId':'A','expr':expression,'legendFormat':'{{case}}','range':True,'instant':False,'interval':'2s'}],
        'fieldConfig':{'defaults':{'unit':unit,'min':0,'color':{'mode':'palette-classic'},
            'custom':{'lineWidth':2,'fillOpacity':8,'showPoints':'never','spanNulls':False,
                      'lineInterpolation':'stepAfter' if 'reachability' in title or 'channel' in title or 'stage' in title else 'linear'}},'overrides':[]},
        'options':{'reduceOptions':{'calcs':['lastNotNull'],'values':False,'fields':''},
                   'colorMode':'value','graphMode':'none',
                   'legend':{'displayMode':'list','placement':'bottom','showLegend':True},
                   'tooltip':{'mode':'multi'}}})


selector='case=~"$case"'
panel('Allowed target / independently received requests',f'sum by(case)(rate(cube_fault_receiver_requests_total{{{selector},target="allow"}}[8s]))',(0,0,12,5),'reqps')
panel('Denied target / actual receipts',f'sum by(case)(cube_fault_receiver_requests_total{{{selector},target="deny"}})',(12,0,12,5))
panel('API list reachability / 1 reachable, 0 failed',f'max by(case)(cube_fault_api_ok{{{selector}}})',(0,5,12,5))
panel('Guest command channel / 1 reachable, 0 failed',f'max by(case)(cube_fault_command_ok{{{selector}}})',(12,5,12,5))
panel('In-memory progress / successful command reads only',f'max by(case)(cube_fault_counter{{{selector}}} and on(case) cube_fault_command_ok{{{selector}}} == 1)',(0,10,12,5))
panel('Experiment stage / 0 baseline, 1 fault, 2 restore, 3 complete',f'max by(case)(cube_fault_phase{{{selector}}})',(12,10,12,5))
dashboard={'uid':'cubesandbox-fault-drill','title':'CubeSandbox / component failure and recovery',
 'schemaVersion':41,'tags':['Sandbox','fault-drill'],'timezone':'browser','refresh':'5s',
 'time':{'from':'now-1h','to':'now'},'panels':panels,
 'templating':{'list':[{'name':'case','label':'Case','type':'query','datasource':ds,
  'query':{'query':'label_values(cube_fault_phase,case)','refId':'VariableQuery'},
  'refresh':1,'multi':True,'includeAll':True,'allValue':'.*','current':{'text':'All','value':'$__all'}}]},
 'annotations':{'list':[]}}
manifest={'apiVersion':'v1','kind':'ConfigMap','metadata':{'name':'cubesandbox-fault-drill-dashboard',
 'namespace':'victoriametrics','labels':{'victoriametrics_dashboard':'1'}},
 'data':{'cubesandbox-fault-drill.json':json.dumps(dashboard)}}
a.output.write_text(json.dumps(manifest,indent=2))
