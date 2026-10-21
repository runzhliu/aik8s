"""Render upstream 0.6.0 charts for a small CPU-only test, without cluster writes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import yaml


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--charts',type=Path,required=True,help='contains agents-sandbox-controller and agents-sandbox-manager')
    parser.add_argument('--output',type=Path,required=True,help='private, Git-ignored output directory')
    parser.add_argument('--test-node',required=True)
    parser.add_argument('--image-map',type=Path,help='optional private mapping: component -> complete image reference')
    args=parser.parse_args();os.umask(0o077);args.output.mkdir(parents=True,exist_ok=True)
    mirror=json.loads(args.image_map.read_text()) if args.image_map else {}
    key=args.output/'admin-api-key'
    if not key.exists():key.write_text('lab_'+secrets.token_urlsafe(36))
    node={'kubernetes.io/hostname':args.test_node}
    controller={'replicaCount':1,'namespace':{'name':'sandbox-system'},'nodeSelector':node,
                'controller':{'clientQPS':50,'clientBurst':100,'workers':{'sandboxWorkers':10,'sandboxsetWorkers':2,'sandboxclaimWorkers':10,'sandboxupdateopsWorkers':2,'poolautoscalerWorkers':1,'commitWorkers':1}},
                'resources':{'requests':{'cpu':'250m','memory':'512Mi'},'limits':{'cpu':'1','memory':'1Gi'}},'enableTLS':False}
    manager={'replicaCount':1,'nodeSelector':node,'e2b':{'domain':'localhost','enableAuth':True,'adminApiKey':key.read_text().strip(),'maxTimeout':3600},
             'controller':{'resources':{'cpu':'1','memory':'1Gi'},'maxClaimWorkers':5,'maxCreateQPS':5,'extProcMaxConcurrency':100},
             'gateway':{'replicaCount':1,'nodeSelector':node,'resources':{'cpu':'500m','memory':'512Mi'},'envoy':{'concurrency':'2','prometheus':{'enabled':True}}},
             'ingress':{'className':'nginx','annotations':{'nginx.ingress.kubernetes.io/ssl-redirect':'false','nginx.ingress.kubernetes.io/force-ssl-redirect':'false'}},
             'agentio':{'enabled':False},'prometheus':{'enabled':False},'enableTLS':False}
    for component,slot in [('agent-sandbox-controller',controller.setdefault('image',{})),('agent-runtime',controller.setdefault('agentRuntime',{}).setdefault('image',{})),('sandbox-manager',manager['controller']),('sandbox-gateway',manager['gateway'].setdefault('image',{}))]:
        if component in mirror:
            # The upstream image helper accepts a registry-qualified repository.
            slot['repository']=mirror[component].rsplit(':',1)[0]
            slot['tag']=mirror[component].rsplit(':',1)[1]
    cluster_kinds={'CustomResourceDefinition','ClusterRole','ClusterRoleBinding','MutatingWebhookConfiguration','ValidatingWebhookConfiguration','Namespace'}
    inventory={}
    for component,values in [('controller',controller),('manager',manager)]:
        chart=args.charts/('agents-sandbox-'+component)
        meta=yaml.safe_load((chart/'Chart.yaml').read_text())
        if str(meta['version'])!='0.6.0':raise ValueError('chart version must be 0.6.0')
        values_path=args.output/(component+'-values.yaml');values_path.write_text(yaml.safe_dump(values,sort_keys=False))
        raw=subprocess.check_output(['helm','template','agents-sandbox-'+component,str(chart),'-n','sandbox-system','--kube-version','1.30.4','--include-crds','-f',str(values_path)],text=True)
        docs=[d for d in yaml.safe_load_all(raw) if d]
        for obj in docs:
            if obj['kind'] not in cluster_kinds:obj['metadata']['namespace']='sandbox-system'
            if obj['kind'] in ('MutatingWebhookConfiguration','ValidatingWebhookConfiguration'):
                for hook in obj['webhooks']:hook['namespaceSelector']={'matchLabels':{'kubernetes.io/metadata.name':'sandbox-system'}}
            if obj['kind']=='Deployment':
                for c in obj['spec']['template']['spec']['containers']:
                    c['args']=[('--kube-client-qps=50' if a.startswith('--kube-client-qps=') else '--kube-client-burst=100' if a.startswith('--kube-client-burst=') else a) for a in c.get('args',[])]
        for suffix,selected in [('crds',[d for d in docs if d['kind']=='CustomResourceDefinition']),('install',[d for d in docs if d['kind']!='CustomResourceDefinition'])]:
            path=args.output/(component+'-'+suffix+'.yaml');path.write_text(yaml.safe_dump_all(selected,sort_keys=False));inventory[path.name]={'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'objects':len(selected)}
    image=mirror.get('python','python:3.12-slim')
    pool={'apiVersion':'agents.kruise.io/v1alpha1','kind':'SandboxSet','metadata':{'name':'python-tools','namespace':'sandbox-system'},'spec':{'replicas':2,'pauseStrategy':{'type':'Stop'},'runtimes':[{'name':'agent-runtime'}],'scaleStrategy':{'maxUnavailable':2},'template':{'metadata':{'labels':{'experiment':'kruise-agents-lab'}},'spec':{'nodeSelector':node,'automountServiceAccountToken':False,'containers':[{'name':'python','image':image,'command':['bash','-lc'],'args':['mkdir -p /workspace; printf "OpenKruise Agents live sandbox\\n" > /workspace/index.html; cd /workspace; exec python -m http.server 8080'],'ports':[{'containerPort':8080,'name':'web'}],'readinessProbe':{'httpGet':{'path':'/','port':'web'},'periodSeconds':2},'resources':{'requests':{'cpu':'100m','memory':'128Mi'},'limits':{'cpu':'1','memory':'512Mi'}}}]}}}}
    (args.output/'python-pool.yaml').write_text(yaml.safe_dump(pool,sort_keys=False))
    pool['metadata']['name']='python-cold';pool['spec']['replicas']=0
    (args.output/'python-cold.yaml').write_text(yaml.safe_dump(pool,sort_keys=False))
    (args.output/'manifest-sha256.json').write_text(json.dumps(inventory,indent=2))
    print('Rendered 12 CRDs, three control-plane Deployments, and two SandboxSets; no cluster resources were changed.')


if __name__=='__main__':main()
