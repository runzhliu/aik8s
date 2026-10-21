"""Render private Kubernetes manifests without changing an existing runtime or CNI."""
import argparse
import json
from pathlib import Path

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--test-node', required=True)
p.add_argument('--image', required=True, help='The locally built laboratory image, preferably by digest')
p.add_argument('--guest-image', default='docker.io/library/python:3.12-slim')
p.add_argument('--storage-class', required=True)
p.add_argument('--output', type=Path, required=True)
p.add_argument('--registry-skip-verify', action='store_true', help='Explicit laboratory exception for a known self-signed registry')
p.add_argument('--attempt', default='02')
a = p.parse_args()
source = Path(__file__).resolve().parent
ns = 'boxlite-lab'
metadata = lambda name: {'name': name, 'namespace': ns}
devices = [('kvm', '/dev/kvm'), ('fuse', '/dev/fuse'), ('vsock', '/dev/vhost-vsock')]
env = {'GUEST_IMAGE': a.guest_image, 'LAB_ATTEMPT': a.attempt,
       'LAB_REGISTRY_SKIP_VERIFY': str(a.registry_skip_verify).lower(), 'PYTHONUNBUFFERED': '1'}
pod = {'nodeSelector': {'kubernetes.io/hostname': a.test_node},
       'automountServiceAccountToken': False, 'terminationGracePeriodSeconds': 60,
       'containers': [{'name': 'runtime', 'image': a.image, 'imagePullPolicy': 'IfNotPresent',
          'securityContext': {'privileged': True}, 'command': ['python', '/app/lab.py'],
          'env': [{'name': k, 'value': v} for k, v in env.items()],
          'resources': {'requests': {'cpu': '1', 'memory': '2Gi'}, 'limits': {'cpu': '4', 'memory': '8Gi'}},
          'ports': [{'name': 'metrics', 'containerPort': 9108}],
          'readinessProbe': {'httpGet': {'path': '/api/state', 'port': 'metrics'}, 'initialDelaySeconds': 3},
          'volumeMounts': [{'name': 'data', 'mountPath': '/data'}, {'name': 'scripts', 'mountPath': '/app'}]
            + [{'name': name, 'mountPath': path} for name, path in devices]}],
       'volumes': [{'name': 'data', 'persistentVolumeClaim': {'claimName': 'boxlite-data'}},
          {'name': 'scripts', 'configMap': {'name': 'boxlite-lab-scripts'}}]
            + [{'name': name, 'hostPath': {'path': path, 'type': 'CharDevice'}} for name, path in devices]}
items = [{'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': ns}},
    {'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim', 'metadata': metadata('boxlite-data'),
     'spec': {'accessModes': ['ReadWriteOnce'], 'storageClassName': a.storage_class,
              'resources': {'requests': {'storage': '10Gi'}}}},
    {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': metadata('boxlite-lab-scripts'),
     'data': {f: (source / f).read_text() for f in ['lab.py', 'index.html']}},
    {'apiVersion': 'apps/v1', 'kind': 'Deployment', 'metadata': metadata('boxlite-lab'),
     'spec': {'replicas': 1, 'strategy': {'type': 'Recreate'},
              'selector': {'matchLabels': {'app': 'boxlite-lab'}},
              'template': {'metadata': {'labels': {'app': 'boxlite-lab'}}, 'spec': pod}}},
    {'apiVersion': 'v1', 'kind': 'Service', 'metadata': {**metadata('boxlite-lab'), 'labels': {'app': 'boxlite-lab'}},
     'spec': {'selector': {'app': 'boxlite-lab'}, 'ports': [{'name': 'metrics', 'port': 9108, 'targetPort': 'metrics'}]}}]
a.output.mkdir(parents=True, exist_ok=True)
(a.output / 'install.json').write_text(json.dumps({'apiVersion': 'v1', 'kind': 'List', 'items': items}, indent=2))
print(a.output / 'install.json')
