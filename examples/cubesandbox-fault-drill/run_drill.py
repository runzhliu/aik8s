"""Version-pinned component drill; requires a disposable, initially idle install.

Configuration and raw evidence belong in a private directory. This script does
not reboot nodes, change CNI, modify Helm values, or delete existing templates.
Use the accompanying independent watchdog before any fault mutation.
"""
import argparse
import concurrent.futures
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import threading
import time

import requests
from cubesandbox import Config, Sandbox

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--config', required=True, type=Path)
p.add_argument('--case', required=True, choices=['api', 'master', 'ops', 'proxy', 'mysql', 'redis', 'minio', 'cubelet', 'egress', 'vmm', 'pod'])
p.add_argument('--attempt', default='a01')
p.add_argument('--retain-failed-snapshot', action='store_true', help='Keep only this case snapshot after ERROR for a separately recorded recovery attempt')
p.add_argument('--policy', choices=['l3','l7'], default='l7', help='Egress case only; never equate the two enforcement paths')
a = p.parse_args()
settings = json.loads(a.config.read_text())
root = a.config.parent.parent
private = root / 'private'
context, ns = settings['context'], settings['namespace']
case = 'cube-' + a.case + '-' + a.attempt
if a.case == 'egress' and a.policy == 'l3':
    case = 'cube-egress-l3-' + a.attempt
if (private / (case + '.json')).exists():
    raise SystemExit('attempt already exists; choose a new --attempt')
source = Path(__file__).parent
cfg = Config(api_url=settings['observer'] + '/cubeapi', proxy_node_ip='127.0.0.1',
             proxy_port=settings['observer_port'], request_timeout=12)
http = requests.Session()
http.trust_env = False
events = []
row = {'case': case, 'fault': a.case, 'attempt': a.attempt, 'started': time.time(),
       'configuration_variant': settings.get('variant', 'original'),
       'policy_path': a.policy if a.case == 'egress' else 'l3',
       'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
       'samples': [], 'actions': [], 'result': 'INCOMPLETE', 'cleanup': {}}
objects, snapshot_ids = [], []
original_replicas, paused = {}, []
armed_path = private / 'armed.json'
finished = threading.Event()


def kube(*args, input=None, timeout=30):
    result = subprocess.run(['kubectl', '--context', context, *args], input=input,
                            capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(result.stderr[-1200:])
    return result.stdout


def save():
    (private / (case + '.json')).write_text(json.dumps(row, indent=2))


def arm():
    value = {'deadline': time.time() + 55,
             'scales': [{'resource': k, 'replicas': v} for k, v in original_replicas.items()],
             'processes': paused}
    temp = armed_path.with_suffix('.tmp')
    temp.write_text(json.dumps(value)); temp.replace(armed_path)


def lease():
    while not finished.wait(3):
        arm()


def post(path, value):
    response = http.post(settings['observer'] + path, json=value, timeout=3)
    response.raise_for_status()


def phase(name, value):
    row.setdefault('phases', {})[name] = time.time()
    post('/record', {'case': case, 'fault': a.case, 'phase': name, 'phase_value': value})
    save()


def receiver_events():
    values = []
    for base in (settings['observer'], settings['deny_observer']):
        response = http.get(base + '/events', timeout=3)
        response.raise_for_status()
        values.extend(e for e in response.json()['events'] if e['case'] == case)
    return sorted(values, key=lambda r: r['at'])


def run(sb, command, timeout=3):
    value = sb.commands.run(command, timeout=timeout)
    if value.exit_code:
        raise RuntimeError('guest_command_exit_' + str(value.exit_code) + ': ' + (value.stderr or '')[-600:])
    return (value.stdout or '').strip()


def guest_state(sb, action='state'):
    code = "import urllib.request; print(urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:18182/" + action + "',method=" + repr('GET' if action == 'state' else 'POST') + "),timeout=1).read().decode())"
    return json.loads(run(sb, 'python3 -c ' + shlex.quote(code), timeout=2))


def create(name, template=None, l7=False):
    if l7:
        ip = settings['ips']['allow']
        network = {'rules': [
            {'name': 'fault-allow', 'match': {'host': ip, 'path': '/probe/allow*'}, 'action': {'allow': True}},
            {'name': 'fault-deny', 'match': {'host': ip}, 'action': {'allow': False}}]}
        targets = {role: {'url': 'http://' + ip, 'path': '/probe/' + role} for role in ('allow', 'deny')}
    else:
        network = {'allow_out': [settings['ips']['allow']]}
        targets = {role: {'url': 'http://' + ip + ':8080'} for role, ip in settings['ips'].items()}
    sb = Sandbox.create(template=template or settings['template'], timeout=900,
                        allow_internet_access=False, network=network,
                        metadata={'purpose': 'cube-fault-drill', 'case': case, 'role': name}, config=cfg)
    objects.append(sb)
    row.setdefault('private_objects', []).append({'role': name, 'data': sb._data})
    save()
    if not template:
        sb.files.write('/tmp/cube-fault-config.json', json.dumps({'case': case if name == 'subject' else case + '-witness', 'targets': targets}))
        sb.files.write('/tmp/cube-fault-probe.py', (source / 'guest_probe.py').read_text())
        run(sb, 'nohup setsid python3 /tmp/cube-fault-probe.py </dev/null >/tmp/cube-fault-probe.log 2>&1 &')
    until = time.monotonic() + 15
    while True:
        try:
            state = guest_state(sb)
            if state['counter'] >= 2:
                return sb, state
        except Exception:
            if time.monotonic() > until:
                raise
        time.sleep(0.25)


def api_probe():
    try:
        response = http.get(settings['observer'] + '/cubeapi/sandboxes', timeout=1.2)
        return response.status_code == 200 and isinstance(response.json(), (list, dict))
    except Exception:
        return False


def sample(sb, identity, stage):
    current = {'at': time.time(), 'case': case, 'stage': stage, 'api_ok': 0, 'command_ok': 0,
               'counter': 0, 'identity_same': 0}
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        api = pool.submit(api_probe)
        guest = pool.submit(guest_state, sb)
        current['api_ok'] = int(api.result())
        try:
            value = guest.result()
            current.update(command_ok=1, counter=value['counter'], identity_same=int(value['identity'] == identity))
            row.setdefault('states', {})[stage] = value
        except Exception as exc:
            current['command_error_type'] = type(exc).__name__
    row['samples'].append(current)
    post('/sample', current)
    save()
    return current


def observe(sb, identity, stage, seconds):
    started = time.monotonic()
    while time.monotonic() - started < seconds:
        sample(sb, identity, stage)
        time.sleep(0.6)


def resource_scale(resource, replicas):
    if resource not in original_replicas:
        data = json.loads(kube('-n', ns, 'get', resource, '-o', 'json'))
        original_replicas[resource] = data['spec'].get('replicas', 1)
    arm()
    kube('-n', ns, 'scale', resource, '--replicas=' + str(replicas))
    row['actions'].append({'at': time.time(), 'action': 'scale', 'resource': resource, 'replicas': replicas})
    save()


def pods_for(resource):
    data = json.loads(kube('-n', ns, 'get', resource, '-o', 'json'))
    selector = ','.join(k + '=' + v for k, v in data['spec']['selector']['matchLabels'].items())
    return json.loads(kube('-n', ns, 'get', 'pods', '-l', selector, '-o', 'json'))['items']


def wait_absent(resource):
    until = time.monotonic() + 60
    while pods_for(resource):
        if time.monotonic() > until:
            raise RuntimeError('fault_not_confirmed_pods_still_present')
        time.sleep(0.5)


def process(request):
    script = (source / 'process_guard.py').read_text()
    return json.loads(kube('-n', ns, 'exec', '-i', 'ds/cube-node', '-c', 'cubelet', '--',
                           'python3', '-c', script, json.dumps(request), timeout=20))


def discover(mode, sb=None):
    req = {'action': 'discover', 'mode': mode}
    if mode == 'vmm':
        req['sandbox_id'] = sb.sandbox_id
    else:
        pod = pods_for('ds/cube-node')[0]
        name = 'cubelet' if mode == 'cubelet' else 'cube-egress'
        status = next(v for v in pod['status']['containerStatuses'] if v['name'] == name)
        req['container_id'] = status['containerID'].split('://')[-1]
    return process(req)


def restore_components():
    if paused:
        row['actions'].append({'at': time.time(), 'action': 'SIGCONT', 'result': process({'action': 'signal', 'signal': 'CONT', 'processes': list(paused)})})
        paused.clear()
    for resource, replicas in original_replicas.items():
        kube('-n', ns, 'scale', resource, '--replicas=' + str(replicas))
    arm()


def wait_recovered(sb, identity, seconds=75):
    until = time.monotonic() + seconds
    streak = 0
    while time.monotonic() < until:
        current = sample(sb, identity, 'recovery')
        if current['api_ok'] and current['command_ok'] and current['identity_same']:
            if streak == 0:
                row['first_good_after_restore'] = current['at']
            streak += 1
            if streak >= 3:
                return True
        else:
            streak = 0
        time.sleep(0.8)
    return False


def summarize():
    try:
        values = receiver_events()
        (private / (case + '-receivers.json')).write_text(json.dumps(values, indent=2))
        phases = row.get('phases', {})
        windows = [('baseline', phases.get('baseline'), phases.get('fault_issued')),
                   ('fault', phases.get('fault_confirmed'), phases.get('restore_issued')),
                   ('recovery', phases.get('restore_issued'), phases.get('complete', time.time()))]
        row['receipts'] = {}
        for name, start, end in windows:
            if start is not None and end is not None:
                row['receipts'][name] = {role: sum(e['target'] == role and start <= e['at'] < end for e in values) for role in ('allow', 'deny')}
    except Exception as exc:
        row['receiver_export_error'] = type(exc).__name__


try:
    baseline = Sandbox.list(config=cfg)
    if baseline:
        raise RuntimeError('installation_not_idle; refuse fault mutation')
    arm()
    threading.Thread(target=lease, daemon=True).start()
    sb, initial = create('subject', l7=a.case == 'egress' and a.policy == 'l7')
    row['initial'] = initial
    runtime = discover('vmm', sb)
    row['private_runtime_identity'] = runtime
    if settings.get('required_shim_sha256'):
        if runtime[0].get('executable_sha256') != settings['required_shim_sha256']:
            raise RuntimeError('actual_runtime_hash_mismatch; refuse fault')
    phase('baseline', 0)
    observe(sb, initial['identity'], 'baseline', 10)
    receipts = receiver_events()
    if sum(e['target'] == 'allow' for e in receipts) < 3 or any(e['target'] == 'deny' for e in receipts):
        raise RuntimeError('policy_baseline_not_verified; refuse fault')
    witness = None
    if a.case in ('vmm','pod'):
        witness, wi = create('witness')
        row['witness_initial'] = wi
        captured = guest_state(sb, 'hold')
        row['snapshot_state'] = captured
        sid = sb.create_snapshot().snapshot_id
        row['snapshot_completed_at'] = time.time()
        snapshot_ids.append(sid)
        row['private_snapshot_id'] = sid
        guest_state(sb, 'run')
        time.sleep(2)
        row['before_vmm_kill'] = guest_state(sb)
    phase('fault_issued', 1)
    if a.case in ('api', 'master', 'ops', 'proxy', 'mysql', 'redis', 'minio'):
        kind = 'sts' if a.case in ('mysql', 'redis', 'minio') else 'deploy'
        resource = kind + '/cube-' + a.case
        resource_scale(resource, 0)
        wait_absent(resource)
    elif a.case in ('cubelet', 'egress'):
        paused[:] = discover(a.case)
        arm()
        row['private_processes'] = list(paused)
        row['actions'].append({'at': time.time(), 'action': 'SIGSTOP', 'result': process({'action': 'signal', 'signal': 'STOP', 'processes': paused})})
    elif a.case == 'vmm':
        target = discover('vmm', sb)
        row['private_processes'] = target
        row['actions'].append({'at': time.time(), 'action': 'SIGKILL', 'result': process({'action': 'signal', 'signal': 'KILL', 'processes': target})})
    elif a.case == 'pod':
        pod = pods_for('ds/cube-node')[0]
        row['old_pod_uid'] = pod['metadata']['uid']
        row['old_pod_ip'] = pod['status']['podIP']
        row['private_processes'] = discover('vmm', sb)
        row['private_witness_processes'] = discover('vmm', witness)
        kube('-n', ns, 'delete', 'pod', pod['metadata']['name'], '--wait=false')
        until = time.monotonic() + 90
        while True:
            pods = pods_for('ds/cube-node')
            newer = [v for v in pods if v['metadata']['uid'] != row['old_pod_uid'] and v['status'].get('phase') == 'Running']
            if newer:
                row['new_pod_uid'] = newer[0]['metadata']['uid']
                row['new_pod_ip'] = newer[0]['status'].get('podIP')
                break
            if time.monotonic() > until:
                raise RuntimeError('replacement_pod_not_running')
            time.sleep(1)
    phase('fault_confirmed', 1)
    observe(sb, initial['identity'], 'fault', 14)
    if witness:
        try:
            row['witness_after_fault'] = guest_state(witness)
            row['witness_identity_same'] = row['witness_after_fault']['identity'] == wi['identity']
            row['witness_command_ok'] = True
        except Exception as exc:
            row['witness_command_ok'] = False
            row['witness_command_error_type'] = type(exc).__name__
    phase('restore_issued', 2)
    restore_components()
    if a.case == 'vmm':
        # An explicit recovery, not automatic restart or migration.
        sb.kill()
        objects.remove(sb)
        row['snapshot_restore_started_at'] = time.time()
        restored, state = create('restored', template=sid)
        row['snapshot_restore_completed_at'] = time.time()
        row['recovery_mode'] = 'explicit_snapshot_restore'
        row['restored_state'] = state
        row['snapshot_identity_counter_restored'] = all(state[k] == captured[k] for k in ('identity', 'counter', 'digest', 'pid', 'held'))
        guest_state(restored, 'run')
        sb = restored
    if a.case == 'pod':
        row['automatic_task_recovered'] = wait_recovered(sb, initial['identity'], seconds=35)
        row['old_runtime_processes_after_recreate'] = process({'action':'inspect','processes':row['private_processes']+row['private_witness_processes']})
        if not row['automatic_task_recovered']:
            phase('manual_restore_issued', 2)
            for old in (sb,witness):
                try:
                    old.kill()
                except Exception as exc:
                    row.setdefault('pre_restore_cleanup_error_types',[]).append(type(exc).__name__)
                objects.remove(old)
            row['snapshot_restore_started_at'] = time.time()
            restored, state = create('restored', template=sid)
            row['snapshot_restore_completed_at'] = time.time()
            row['private_restored_runtime_identity'] = discover('vmm',restored)
            if settings.get('required_shim_sha256') and row['private_restored_runtime_identity'][0]['executable_sha256']!=settings['required_shim_sha256']:
                raise RuntimeError('restored runtime hash mismatch')
            row['recovery_mode'] = 'explicit_snapshot_restore'
            row['restored_state'] = state
            row['snapshot_identity_counter_restored'] = all(state[k] == captured[k] for k in ('identity','counter','digest','pid','held'))
            guest_state(restored,'run')
            sb=restored
    healthy = wait_recovered(sb, initial['identity'], seconds=75)
    row['original_task_recovered'] = healthy
    if not healthy and a.case != 'pod':
        row['result'] = 'OBSERVED_UNRECOVERED'
    else:
        row['result'] = 'MEASURED'
    phase('complete', 3)
except Exception as exc:
    row['result'] = 'ERROR'
    row['error_type'] = type(exc).__name__
    row['error_private'] = str(exc)[-3000:]
    row['traceback_private'] = __import__('traceback').format_exc()
    print(case, 'ERROR', type(exc).__name__, str(exc)[-300:], flush=True)
finally:
    try:
        restore_components()
    except Exception as exc:
        row['cleanup']['restore_error_private'] = str(exc)[-1200:]
    for resource, replicas in original_replicas.items():
        try:
            kube('-n', ns, 'rollout', 'status', resource, '--timeout=100s', timeout=110)
        except Exception as exc:
            row['cleanup'][resource + '_ready_error'] = type(exc).__name__
    for sb in objects:
        try:
            # Files may be inaccessible after the exact runtime fault.
            if a.case not in ('vmm', 'pod'):
                data = sb.files.read('/tmp/cube-fault-events.jsonl')
                (private / (case + '-guest.jsonl')).write_text(data if isinstance(data, str) else data.decode())
        except Exception:
            pass
        cleanup_deadline = time.monotonic() + 60
        for attempt in range(8):
            try:
                sb.kill()
                row['cleanup'].setdefault('kill_attempts', []).append({'attempt': attempt + 1, 'at': time.time(), 'ok': True})
                break
            except Exception as exc:
                row['cleanup'].setdefault('kill_attempts', []).append({'attempt': attempt + 1, 'at': time.time(), 'ok': False,
                                                                      'error_type': type(exc).__name__, 'error_private': str(exc)[-800:]})
                if attempt < 7 and time.monotonic() < cleanup_deadline:
                    time.sleep(min(2 ** attempt, 6))
                else:
                    break
    for sid in snapshot_ids:
        if a.retain_failed_snapshot and row['result'] == 'ERROR':
            row['cleanup']['snapshot_retained_for_recovery'] = True
            continue
        try:
            Sandbox.delete_snapshot(sid, config=cfg)
        except Exception as exc:
            row['cleanup'].setdefault('snapshot_errors', []).append(type(exc).__name__)
    try:
        remaining = Sandbox.list(config=cfg)
        row['cleanup']['remaining_sandboxes'] = len(remaining)
        if not remaining:
            smoke = Sandbox.create(template=settings['template'], timeout=60, allow_internet_access=False, config=cfg,
                                   metadata={'purpose': 'cube-fault-postcheck'})
            row['cleanup']['new_sandbox_exec'] = run(smoke, 'printf recovered', timeout=4) == 'recovered'
            smoke.kill()
    except Exception as exc:
        row['cleanup']['postcheck_error_private'] = str(exc)[-1500:]
    summarize()
    row['ended'] = time.time()
    save()
    try:
        post('/record', {'case': case, 'fault': a.case, 'phase': 'complete', 'phase_value': 3,
                         'result': row['result'], 'receipts': row.get('receipts', {}),
                         'original_task_recovered': row.get('original_task_recovered'), 'cleanup': row['cleanup']})
    except Exception:
        pass
    finished.set()
    if not any(k.endswith('_ready_error') or k == 'restore_error_private' for k in row['cleanup']):
        armed_path.unlink(missing_ok=True)
    print(json.dumps({'case': case, 'result': row['result'], 'receipts': row.get('receipts'),
                      'recovered': row.get('original_task_recovered'), 'cleanup': row['cleanup']}), flush=True)
