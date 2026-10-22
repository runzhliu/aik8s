"""Render isolated receiver resources; never modifies a CubeSandbox installation."""
import argparse
import json
from pathlib import Path

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--image',required=True,help='An approved image with Python 3 and its standard library')
p.add_argument('--namespace',default='cube-fault-lab')
p.add_argument('--cube-namespace',default='cube-system')
p.add_argument('--node',required=True)
p.add_argument('--output',required=True,type=Path)
p.add_argument('--scrape-namespace',help='Optional namespace watched by the VictoriaMetrics operator')
a=p.parse_args()
ns=a.namespace
items=[{'apiVersion':'v1','kind':'Namespace','metadata':{'name':ns}},
 {'apiVersion':'v1','kind':'ConfigMap','metadata':{'name':'cube-fault-observer','namespace':ns},
  'data':{'observer.py':Path(__file__).with_name('observer.py').read_text(),
          'index.html':'<!doctype html><title>Fault receiver</title><p>Lab receiver. Metrics: /metrics; records: /events.</p>'}}]
for role in ('allow','deny'):
    name='cube-fault-'+role
    labels={'app':name,'fault-drill':'cubesandbox'}
    items.append({'apiVersion':'apps/v1','kind':'Deployment','metadata':{'name':name,'namespace':ns},
      'spec':{'replicas':1,'selector':{'matchLabels':{'app':name}},'template':{'metadata':{'labels':labels},
       'spec':{'nodeSelector':{'kubernetes.io/hostname':a.node},
        'containers':[{'name':'observer','image':a.image,'command':['python3','/app/observer.py'],
         'env':[{'name':'ROLE','value':role},{'name':'CUBE_API','value':f'http://cube-api.{a.cube_namespace}.svc:3000'},
                {'name':'CUBE_PROXY','value':f'http://cube-proxy.{a.cube_namespace}.svc:80'}],
         'ports':[{'name':'metrics','containerPort':8080},{'name':'http','containerPort':80}],
         'resources':{'requests':{'cpu':'50m','memory':'64Mi'},'limits':{'cpu':'1','memory':'512Mi'}},
         'readinessProbe':{'httpGet':{'path':'/state','port':'metrics'}},
         'volumeMounts':[{'name':'source','mountPath':'/app','readOnly':True}]}],
        'volumes':[{'name':'source','configMap':{'name':'cube-fault-observer'}}]}}}})
    items.append({'apiVersion':'v1','kind':'Service','metadata':{'name':name,'namespace':ns,'labels':labels},
      'spec':{'selector':{'app':name},'ports':[{'name':'metrics','port':8080,'targetPort':'metrics'},{'name':'http','port':80,'targetPort':'http'}]}})
if a.scrape_namespace:
    items.append({'apiVersion':'operator.victoriametrics.com/v1beta1','kind':'VMServiceScrape',
      'metadata':{'name':'cube-fault-observers','namespace':a.scrape_namespace},
      'spec':{'namespaceSelector':{'matchNames':[ns]},'selector':{'matchLabels':{'fault-drill':'cubesandbox'}},
              'endpoints':[{'port':'metrics','interval':'2s'}]}})
a.output.parent.mkdir(parents=True,exist_ok=True)
a.output.write_text(json.dumps({'apiVersion':'v1','kind':'List','items':items},indent=2)+'\n')
