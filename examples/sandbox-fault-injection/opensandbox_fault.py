"""Control-plane outage check for an idle, dedicated OpenSandbox test installation."""
import asyncio
from datetime import timedelta
import json
import os
from pathlib import Path
import shlex
import subprocess
import time
from urllib.request import urlopen, Request

from opensandbox import Sandbox
from opensandbox.config import ConnectionConfig
from opensandbox.models import WriteEntry

CTX = os.environ['KUBE_CONTEXT']
NS = os.environ.get('OPENSANDBOX_NAMESPACE', 'opensandbox-lab')
OUT = Path(os.environ['EVIDENCE_DIR'])
OUT.mkdir(parents=True, exist_ok=True)
CASE = 'opensandbox-controlplane-' + os.environ.get('ATTEMPT', 'a02')
BASE = ['kubectl', '--context', CTX, '-n', NS]


def k(args):
    r = subprocess.run(BASE + args, capture_output=True, text=True, timeout=60)
    if r.returncode:
        raise RuntimeError(r.stderr[-1000:])
    return r.stdout


def receivers():
    return {r: json.load(urlopen('http://127.0.0.1:' + p + '/events', timeout=10))
            for r, p in [('allow', '18960'), ('deny', '18961')]}


async def main():
    tasks = json.loads(k(['get', 'batchsandboxes', '-o', 'json']))['items']
    assert not tasks, 'Use an idle, dedicated OpenSandbox installation'
    key = Path(os.environ['OPENSANDBOX_API_KEY_FILE']).read_text().strip()
    replicas = {name: json.loads(k(['get', 'deploy', name, '-o', 'json']))['spec']['replicas']
                for name in ['opensandbox-server', 'opensandbox-controller-manager']}
    record = {'case': CASE, 'engine': 'opensandbox', 'fault': 'controlplane', 'policy_enforced': False,
              'started_at': time.time()}
    sandbox = None
    forward = None
    def connect_forward():
        nonlocal forward
        forward = subprocess.Popen(BASE + ['port-forward', 'svc/opensandbox-server', '18962:80'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(30):
            try:
                urlopen('http://127.0.0.1:18962/health', timeout=2).read()
                return
            except Exception:
                time.sleep(.3)
        raise TimeoutError('Local API forwarding unavailable')
    try:
        connect_forward()
        for port in ['18960', '18961']:
            urlopen(Request('http://127.0.0.1:' + port + '/record', data=json.dumps({'case': CASE, 'phase_value': 0}).encode(), headers={'Content-Type': 'application/json'})).read()
        cfg = ConnectionConfig(domain='127.0.0.1:18962', api_key=key, protocol='http',
            use_server_proxy=True, request_timeout=timedelta(seconds=45))
        sandbox = await Sandbox.create(os.environ['GUEST_IMAGE'], connection_config=cfg,
            timeout=timedelta(minutes=8), ready_timeout=timedelta(seconds=100),
            resource={'cpu': '500m', 'memory': '512Mi'}, resource_requests={'cpu': '100m', 'memory': '128Mi'},
            secure_access=True, metadata={'experiment': 'sandbox-faults', 'case': CASE})
        workload = [p for p in json.loads(k(['get', 'pods', '-o', 'json']))['items']
                    if p['metadata']['name'].startswith(sandbox.id)]
        assert len(workload) == 1
        record['task_pod_uid_before'] = workload[0]['metadata']['uid']
        await sandbox.files.write_files([WriteEntry(path='/root/guest_probe.py', data=(Path(__file__).parent / 'guest_probe.py').read_text())])
        args = [os.environ['ALLOW_URL'], os.environ['DENY_URL'], CASE]
        result = await sandbox.commands.run('nohup python /root/guest_probe.py ' + ' '.join(map(shlex.quote, args)) + ' >/tmp/probe.log 2>&1 </dev/null &')
        assert not result.error
        record['ready_at'] = time.time()
        initial = await sandbox.commands.run('cat /proc/sys/kernel/random/boot_id')
        record['boot_before'] = ''.join(x.text for x in initial.logs.stdout).strip()
        await asyncio.sleep(12)
        record['injected_at'] = time.time()
        for name in replicas:
            k(['scale', 'deploy/' + name, '--replicas=0'])
        for name in replicas:
            deployment = json.loads(k(['get', 'deploy', name, '-o', 'json']))
            selector = ','.join(key + '=' + value for key, value in deployment['spec']['selector']['matchLabels'].items())
            k(['wait', '--for=delete', 'pod', '-l', selector, '--timeout=45s'])
            assert not json.loads(k(['get', 'pods', '-l', selector, '-o', 'json']))['items']
        record['control_pods_after_scale'] = {name: json.loads(k(['get', 'deploy', name, '-o', 'json']))['spec']['replicas'] for name in replicas}
        forward.terminate()
        forward.wait(timeout=5)
        record['injection_completed_at'] = time.time()
        await asyncio.sleep(15)
        record['observation_ended_at'] = time.time()
        data = receivers()
        record['received'] = {phase: {role: sum(x['case'] == CASE and start <= x['at'] < end for x in data[role]['events'])
            for role in ['allow', 'deny']} for phase, start, end in [
                ('before', record['ready_at'], record['injected_at']),
                ('after', record['injection_completed_at'], record['observation_ended_at'])]}
        (OUT / (CASE + '-receivers.json')).write_text(json.dumps(data, indent=2))
        assert all(record['received'][phase][role] >= 4 for phase in ['before', 'after'] for role in ['allow', 'deny'])
        record['status'] = 'measured'
    except Exception as exc:
        record.update(status='failed', error=repr(exc))
    finally:
        for name, count in replicas.items():
            k(['scale', 'deploy/' + name, '--replicas=' + str(count)])
            k(['rollout', 'status', 'deploy/' + name, '--timeout=50s'])
        if forward and forward.poll() is None:
            forward.terminate()
            forward.wait(timeout=5)
        if sandbox:
            try:
                connect_forward()
                current = await sandbox.commands.run('cat /proc/sys/kernel/random/boot_id')
                record['boot_after'] = ''.join(x.text for x in current.logs.stdout).strip()
                record['same_boot_id'] = record.get('boot_before') == record['boot_after']
                workload = [p for p in json.loads(k(['get', 'pods', '-o', 'json']))['items']
                            if p['metadata']['name'].startswith(sandbox.id)]
                record['same_task_pod_uid'] = len(workload) == 1 and workload[0]['metadata']['uid'] == record['task_pod_uid_before']
                await sandbox.kill()
                await sandbox.close()
                record['task_removed'] = True
            except Exception as exc:
                record['cleanup_error'] = repr(exc)
        if forward and forward.poll() is None:
            forward.terminate()
        (OUT / (CASE + '.json')).write_text(json.dumps(record, indent=2))
        print(json.dumps(record, indent=2))


asyncio.run(main())
