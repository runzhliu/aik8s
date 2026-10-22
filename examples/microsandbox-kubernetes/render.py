"""Render an isolated lab; an existing KVM device plugin is required."""
import argparse
from pathlib import Path
import json

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--test-node', required=True)
p.add_argument('--image', required=True, help='Laboratory image, preferably pinned by digest')
p.add_argument('--storage-class', required=True)
p.add_argument('--guest-image', default='python-lab:local')
p.add_argument('--otel-endpoint', default='', help='Full OTLP HTTP metrics receiver URL')
p.add_argument('--attempt', default='03')
p.add_argument('--output', required=True, type=Path)
a = p.parse_args()
root = Path(__file__).resolve().parent
ns = 'microsandbox-lab'
image = a.image
scripts = {f: (root / f).read_text() for f in ['lab.py', 'state_server.py', 'index.html']}
pod = {'nodeSelector': {'kubernetes.io/hostname': a.test_node},
       'automountServiceAccountToken': False, 'terminationGracePeriodSeconds': 45,
       'containers': [{'name': 'runtime', 'image': image, 'imagePullPolicy': 'IfNotPresent',
          'env': [{'name': 'MSB_HOME', 'value': '/data/runtime'}, {'name': 'PYTHONUNBUFFERED', 'value': '1'},
                  {'name': 'GUEST_IMAGE', 'value': a.guest_image},
                  {'name': 'LAB_ATTEMPT', 'value': a.attempt},
                  {'name': 'OTEL_METRICS_ENDPOINT', 'value': a.otel_endpoint}],
          'resources': {'requests': {'cpu': '1', 'memory': '2Gi', 'devices.kubevirt.io/kvm': '1'},
                        'limits': {'cpu': '4', 'memory': '8Gi', 'devices.kubevirt.io/kvm': '1'}},
          'securityContext': {'privileged': False, 'allowPrivilegeEscalation': False,
                              'seccompProfile': {'type': 'RuntimeDefault'}},
          'ports': [{'name': 'metrics', 'containerPort': 9118}],
          'volumeMounts': [{'name': 'data', 'mountPath': '/data'}, {'name': 'scripts', 'mountPath': '/app'},
                           {'name': 'shm', 'mountPath': '/dev/shm'}],
          'command': ['python', '/app/lab.py'],
          'readinessProbe': {'httpGet': {'path': '/api/state', 'port': 'metrics'}, 'initialDelaySeconds': 2}}],
       'volumes': [{'name': 'data', 'persistentVolumeClaim': {'claimName': 'microsandbox-data'}},
                   {'name': 'scripts', 'configMap': {'name': 'microsandbox-scripts'}},
                   {'name': 'shm', 'emptyDir': {'medium': 'Memory', 'sizeLimit': '256Mi'}}]}
items = [{'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': ns}},
    {'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim', 'metadata': {'name': 'microsandbox-data', 'namespace': ns},
     'spec': {'storageClassName': a.storage_class, 'accessModes': ['ReadWriteOnce'],
              'resources': {'requests': {'storage': '8Gi'}}}},
    {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': 'microsandbox-scripts', 'namespace': ns}, 'data': scripts},
    {'apiVersion': 'apps/v1', 'kind': 'Deployment', 'metadata': {'name': 'microsandbox-lab', 'namespace': ns},
     'spec': {'replicas': 1, 'strategy': {'type': 'Recreate'}, 'selector': {'matchLabels': {'app': 'microsandbox-lab'}},
              'template': {'metadata': {'labels': {'app': 'microsandbox-lab'}}, 'spec': pod}}},
    {'apiVersion': 'v1', 'kind': 'Service', 'metadata': {'name': 'microsandbox-lab', 'namespace': ns, 'labels': {'app': 'microsandbox-lab'}},
     'spec': {'selector': {'app': 'microsandbox-lab'}, 'ports': [{'name': 'metrics', 'port': 9118, 'targetPort': 'metrics'}]}}]
a.output.mkdir(parents=True, exist_ok=True)
(a.output / 'install.json').write_text(json.dumps({'apiVersion': 'v1', 'kind': 'List', 'items': items}, indent=2))
print(a.output / 'install.json')
