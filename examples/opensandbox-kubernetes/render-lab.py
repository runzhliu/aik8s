import os
import base64
import json
from pathlib import Path
import secrets
import subprocess
import yaml

root = Path(os.environ.get('OPENSANDBOX_OUTPUT', '/tmp/opensandbox-lab')).resolve()
root.mkdir(parents=True, exist_ok=True)
up = Path(os.environ['OPENSANDBOX_SOURCE']).resolve()
assert subprocess.check_output(['git', '-C', str(up), 'rev-parse', 'HEAD'], text=True).strip() == '531700ca18a7fa5fab6a2f25d6dc68a76eddab12', 'Use release-1.1.1'
ns = 'opensandbox-lab'
node = os.environ.get('OPENSANDBOX_TEST_NODE', '')
key = root / 'api-key'
if not key.exists():
    key.write_text(secrets.token_urlsafe(32))
    key.chmod(0o600)
ring = root / 'signing-key'
if not ring.exists():
    ring.write_text(base64.b64encode(secrets.token_bytes(32)).decode())
    ring.chmod(0o600)
image = lambda name: 'docker.io/opensandbox/' + name
resources = lambda c,m: {'requests': {'cpu': '100m', 'memory': '128Mi'},
                         'limits': {'cpu': c, 'memory': m}}
controller = {'namespaceOverride': ns, 'controller': {
    'image': {'repository': image('controller'), 'tag':'release-1.1.1'},
    'resources': resources('500m','256Mi'), 'nodeSelector':({'kubernetes.io/hostname':node} if node else {}),
    'metrics': {'enabled':True,'port':8080,'secure':False},
    'kubeClient': {'qps':20,'burst':40}}}
toml = '''[server]
host = "0.0.0.0"
port = 80
max_sandbox_timeout_seconds = 3600
[log]
level = "INFO"
[runtime]
type = "kubernetes"
execd_image = "docker.io/opensandbox/execd:release-1.1.1"
[kubernetes]
namespace = "opensandbox-lab"
kubeconfig_path = ""
workload_provider = "batchsandbox"
image_pull_policy = "IfNotPresent"
batchsandbox_template_file = "/etc/opensandbox/template.yaml"
informer_resync_seconds = 300
informer_watch_timeout_seconds = 60
[store]
type = "sqlite"
path = "/state/opensandbox.db"
[proxy]
resolve_internal = true
'''
server = {'namespaceOverride':ns,'configToml':toml, 'server': {
    'image': {'repository':image('server'),'tag':'release-1.1.1'},
    'resources':resources('1','512Mi'),'nodeSelector':({'kubernetes.io/hostname':node} if node else {}),
    'gateway': {'enabled':True,'host':'127.0.0.1:38089','gatewayRouteMode':'header',
                'secureAccess':{'activeKey':'a','existingSecret':'opensandbox-route-keys'}},
    'env':[{'name':'OPENSANDBOX_SERVER_API_KEY','valueFrom':{'secretKeyRef':{'name':'opensandbox-api-key','key':'api-key'}}}],
    'volumes':[{'name':'template','configMap':{'name':'opensandbox-template'}}, {'name':'state','emptyDir':{}}],
    'volumeMounts':[{'name':'template','mountPath':'/etc/opensandbox/template.yaml','subPath':'template.yaml','readOnly':True},
                    {'name':'state','mountPath':'/state'}]}}
gateway = {'namespaceOverride':ns,'gateway':{
    'image':{'repository':image('ingress'),'tag':'release-1.1.1'},
    'replicaCount':1,'dataplaneNamespace':ns, 'resources':resources('500m','256Mi'),
    'nodeSelector':({'kubernetes.io/hostname':node} if node else {}),'secureAccess':{'existingSecret':'opensandbox-route-keys'}}}
out=[]
for name, values in [('controller',controller),('server',server),('ingress-gateway',gateway)]:
    vf=root/(name+'-values.yaml'); vf.write_text(yaml.safe_dump(values))
    rendered=subprocess.check_output(['helm','template','osb-lab-'+name,str(up/'manifests/charts'/name),'-n',ns,'-f',str(vf)],text=True)
    (root/(name+'-rendered.yaml')).write_text(rendered)
    docs=list(yaml.safe_load_all(rendered))
    # Keep writes namespaced. The upstream controller has cluster-wide caches;
    # its cluster binding retains read access while a Role enables own-namespace mutations.
    for d in docs:
        if not d: continue
        if d['kind']=='ClusterRole':
            if name=='controller':
                local=json.loads(json.dumps(d)); local['kind']='Role'; local['metadata']['namespace']=ns
                local['metadata']['name']+='-lab-writer'; out.append(local)
                out.append({'apiVersion':'rbac.authorization.k8s.io/v1','kind':'RoleBinding',
                    'metadata':{'name':local['metadata']['name'],'namespace':ns},
                    'roleRef':{'apiGroup':'rbac.authorization.k8s.io','kind':'Role','name':local['metadata']['name']},
                    'subjects':[{'kind':'ServiceAccount','name':'opensandbox-controller-manager','namespace':ns}]})
                for rule in d['rules']:
                    rule['verbs']=[v for v in rule['verbs'] if v in ('get','list','watch')]
                d['rules']=[r for r in d['rules'] if r['verbs']]
            elif name != 'ingress-gateway':
                d['kind']='Role'; d['metadata']['namespace']=ns
                d['rules']=[r for r in d['rules'] if 'namespaces' not in r.get('resources',[]) and 'runtimeclasses' not in r.get('resources',[])]
        elif d['kind']=='ClusterRoleBinding' and name=='server':
            d['kind']='RoleBinding'; d['metadata']['namespace']=ns; d['roleRef']['kind']='Role'
        out.append(d)
template={'spec':{'replicas':1,'template':{'metadata':{'labels':{'experiment':'opensandbox-lab'}},'spec':{
    'restartPolicy':'Never','automountServiceAccountToken':False,
    'nodeSelector':({'kubernetes.io/hostname':node} if node else {}),
    'securityContext':{'seccompProfile':{'type':'RuntimeDefault'}},
    'containers':[{'name':'sandbox','securityContext':{'allowPrivilegeEscalation':False,'capabilities':{'drop':['ALL']}}}]}}}}
out.append({'apiVersion':'v1','kind':'ConfigMap','metadata':{'name':'opensandbox-template','namespace':ns},
    'data':{'template.yaml':yaml.safe_dump(template)}})
out.extend([{'apiVersion':'v1','kind':'Secret','metadata':{'name':'opensandbox-api-key','namespace':ns},
    'stringData':{'api-key':key.read_text()}},
    {'apiVersion':'v1','kind':'Secret','metadata':{'name':'opensandbox-route-keys','namespace':ns},
     'stringData':{'keys':'a='+ring.read_text(),'active-key':'a'}},
    {'apiVersion':'v1','kind':'LimitRange','metadata':{'name':'lab-defaults','namespace':ns},
     'spec':{'limits':[{'type':'Container','default':{'cpu':'500m','memory':'256Mi'},'defaultRequest':{'cpu':'25m','memory':'32Mi'}}]}},
    {'apiVersion':'v1','kind':'ResourceQuota','metadata':{'name':'lab-budget','namespace':ns},
     'spec':{'hard':{'requests.cpu':'6','requests.memory':'6Gi','limits.cpu':'10','limits.memory':'10Gi','pods':'16'}}}])
(root/'install.yaml').write_text(yaml.safe_dump_all(out, sort_keys=False)); (root/'install.yaml').chmod(0o600)
crds=[yaml.safe_load(p.read_text()) for p in (up/'kubernetes/config/crd/bases').glob('*.yaml')]
crds.extend(d for d in yaml.safe_load_all((up/'manifests/charts/base/files/fast-sandbox-crds.yaml').read_text()) if d)
(root/'crds.yaml').write_text(yaml.safe_dump_all(crds))
print(json.dumps({'objects':len(out),'crds':len(crds),'namespace':ns,'node':node,'source':'531700ca18a7fa5fab6a2f25d6dc68a76eddab12'}))
