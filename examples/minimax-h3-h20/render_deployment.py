#!/usr/bin/env python3
"""Render a zero-replica Kubernetes bundle to stdout; never contacts a cluster."""
import argparse
import json
from pathlib import Path

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--engine', choices=['sglang', 'vllm-omni'], required=True)
p.add_argument('--image', required=True, help='qualified registry/repository@sha256:digest')
p.add_argument('--node', required=True)
p.add_argument('--namespace', default='aik8s-ms')
p.add_argument('--nvme-path', required=True, help='host path already verified with findmnt/lsblk')
p.add_argument('--output-host-path', required=True, help='dedicated persistent host directory; retained after scale-down')
p.add_argument('--fixtures-host-path', help='read-only original benchmark media directory')
p.add_argument('--variant', choices=['fl2va', 'ref2va'], default='fl2va')
p.add_argument('--ingress-host')
p.add_argument('--ingress-class', default='nginx')
a = p.parse_args()
if '@sha256:' not in a.image or not a.nvme_path.startswith('/') or a.nvme_path == '/':
    p.error('pin an image Digest and an absolute, specific NVMe model path')
if not a.output_host_path.startswith('/') or a.output_host_path == '/' or a.output_host_path.rstrip('/') == a.nvme_path.rstrip('/'):
    p.error('use a dedicated absolute output host path, separate from model weights')
name = 'minimax-h3-' + a.engine
labels = {'app': name}
metadata = {'name': name, 'namespace': a.namespace}
root = '/models-nvme/MiniMaxAI/MiniMax-H3'
mounts = [{'name': 'model', 'mountPath': root, 'readOnly': True},
          {'name': 'launcher', 'mountPath': '/h3-launch', 'readOnly': True},
          {'name': 'shm', 'mountPath': '/dev/shm'},
          {'name': 'outputs', 'mountPath': '/outputs'}]
bundle = [dict(apiVersion='v1', kind='ConfigMap', metadata=metadata,
               data={name: Path(__file__).with_name(name).read_text()
                     for name in ('launch.sh', 'preserve_outputs.py', 'monitor_gpu.py',
                                  'benchmark.py', 'cases.json', 'run_suite.py',
                                  'check_api_errors.py', 'studio.py', 'studio.html',
                                  'apply_runtime_fixes.py', 'runtime-fixes.json')})]
env = dict(ENGINE=a.engine, VARIANT=a.variant, EXECUTE='1', MODEL_PATH=root, PORT='8000',
           HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
           VLLM_WORKER_MULTIPROC_METHOD='spawn', VLLM_OMNI_VIDEO_SYNC_TIMEOUT='7200')
# Ref2VA loading exceeded the original 384 GiB limit in the retained run.
memory_request, memory_limit = ('768Gi', '768Gi') if a.variant == 'ref2va' else ('192Gi', '384Gi')
container = dict(name='server', image=a.image, imagePullPolicy='IfNotPresent',
                 workingDir='/outputs',
                 command=['bash', '/h3-launch/launch.sh'],
                 env=[dict(name=k, value=v) for k, v in env.items()],
                 ports=[dict(name='http', containerPort=8000)],
                 resources=dict(requests={'cpu':'32', 'memory':memory_request, 'nvidia.com/gpu':'4'},
                                limits={'cpu':'64', 'memory':memory_limit, 'nvidia.com/gpu':'4'}),
                 volumeMounts=mounts,
                 startupProbe=dict(tcpSocket={'port':'http'}, periodSeconds=10, failureThreshold=360),
                 readinessProbe=dict(tcpSocket={'port':'http'}, periodSeconds=10, failureThreshold=6))
pod = dict(automountServiceAccountToken=False,
           nodeSelector={'kubernetes.io/hostname':a.node}, terminationGracePeriodSeconds=120,
           containers=[container],
           volumes=[dict(name='model', hostPath={'path':a.nvme_path,'type':'Directory'}),
                    dict(name='launcher', configMap={'name':name}),
                    dict(name='shm', emptyDir={'medium':'Memory','sizeLimit':'32Gi'}),
                    dict(name='outputs', hostPath={'path':a.output_host_path,'type':'DirectoryOrCreate'})])
if a.fixtures_host_path:
    if not a.fixtures_host_path.startswith('/') or a.fixtures_host_path == '/':
        p.error('fixtures must use a dedicated absolute host path')
    mounts.append(dict(name='fixtures', mountPath='/fixtures', readOnly=True))
    pod['volumes'].append(dict(name='fixtures', hostPath={'path':a.fixtures_host_path, 'type':'Directory'}))
bundle.append(dict(apiVersion='apps/v1', kind='Deployment', metadata=metadata,
                   spec=dict(replicas=0, strategy={'type':'Recreate'},
                             selector={'matchLabels':labels},
                             template={'metadata':{'labels':labels},'spec':pod})))
bundle.append(dict(apiVersion='v1', kind='Service', metadata=metadata,
                   spec=dict(selector=labels, ports=[dict(name='http',port=8000,targetPort='http')])) )
if a.ingress_host:
    bundle.append(dict(apiVersion='networking.k8s.io/v1', kind='Ingress',
                       metadata={**metadata, 'annotations':{
                           'nginx.ingress.kubernetes.io/proxy-read-timeout':'7200',
                           'nginx.ingress.kubernetes.io/proxy-send-timeout':'7200',
                           'nginx.ingress.kubernetes.io/proxy-body-size':'64m'}},
                       spec=dict(ingressClassName=a.ingress_class, rules=[{
                           'host':a.ingress_host, 'http':{'paths':[{
                               'path':'/','pathType':'Prefix','backend':{'service':{
                                   'name':name,'port':{'number':8000}}}}]}}])))
print(json.dumps(dict(apiVersion='v1',kind='List',items=bundle), indent=2))
