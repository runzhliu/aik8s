"""Bounded, serial multi-replica experiment. Use only an idle test installation.

Raw config/results are private. API/Master/Proxy scales are restored; no host,
compute Pod, CNI, database, Helm release, original template or volume is changed.
Start watchdog.py separately first. See README for the deliberately narrow scope.
"""
import argparse
import base64
import concurrent.futures
import hashlib
import json
from pathlib import Path
import shlex
import struct
import subprocess
import threading
import time

import requests
import websocket
from cubesandbox import Config, Sandbox
from cubesandbox._commands import _encode_connect_envelope, _parse_process_start_stream

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--config', required=True, type=Path)
a = p.parse_args()
cfg = json.loads(a.config.read_text())
root = a.config.parent
output = root / 'run.json'
if output.exists():
    raise SystemExit('Refusing to overwrite an attempt')
ns, lab = cfg['namespace'], cfg['lab_namespace']
started = time.time()
original, guests, forwards = {}, [], []
stopped, lock = threading.Event(), threading.RLock()
data = {'started': started, 'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'scope': 'same-node component and Pod failover; not host HA', 'cases': [], 'cleanup': {}}


def kube(*args, input=None, timeout=30):
    r = subprocess.run(['kubectl', '--context', cfg['context'], *args], input=input,
                       capture_output=True, text=True, timeout=timeout)
    if r.returncode:
        raise RuntimeError(r.stderr[-1000:])
    return r.stdout


def save():
    with lock:
        output.write_text(json.dumps(data, indent=2))


def session():
    s = requests.Session()
    s.trust_env = False
    return s


http = session()
base = Config(api_url=cfg['observer'] + '/cubeapi', proxy_node_ip='127.0.0.1',
              proxy_port=cfg['observer_port'], request_timeout=12)
api_l7, api_l4 = 'http://127.0.0.1:19980', 'http://127.0.0.1:19981'
proxy_l7, proxy_l4 = 'http://127.0.0.1:19982', 'http://127.0.0.1:19983'


def arm():
    temp = root / 'armed.tmp'
    temp.write_text(json.dumps({'deadline': min(time.time() + 70, started + 1200), 'replicas': original}))
    temp.replace(root / 'armed.json')


def heartbeat():
    while not stopped.wait(5):
        arm()


def metric(name, value, case, **labels):
    if not cfg.get('vm_url'):
        return
    label = {'case': case, **labels}
    keys = ','.join(k + '=' + json.dumps(str(v)) for k, v in label.items())
    line = name + '{' + keys + '} ' + str(value) + ' ' + str(int(time.time() * 1000)) + '\n'
    try:
        r = requests.post(cfg['vm_url'] + '/api/v1/import/prometheus', data=line, timeout=2)
        if r.status_code != 204:
            raise ValueError('metric import status ' + str(r.status_code))
    except Exception as exc:
        with lock:
            data.setdefault('metric_errors', []).append({'at': time.time(), 'error': type(exc).__name__})


def pods(component):
    selector = 'app.kubernetes.io/instance=cube,app.kubernetes.io/component=' + component
    return [r for r in json.loads(kube('-n', ns, 'get', 'pods', '-l', selector, '-o', 'json'))['items']
            if not r['metadata'].get('deletionTimestamp')]


def ready_two(component):
    end = time.monotonic() + 180
    while time.monotonic() < end:
        rows = pods(component)
        ready = [r for r in rows if any(c['type'] == 'Ready' and c['status'] == 'True' for c in r['status'].get('conditions', []))]
        if len(rows) == len(ready) == 2:
            return sorted(ready, key=lambda r: r['metadata']['creationTimestamp'])
        time.sleep(1)
    raise RuntimeError('two replicas not ready: ' + component)


def nginx(api, proxy):
    ap = '\n'.join('server %s:3000 max_fails=1 fail_timeout=60s;' % r['status']['podIP'] for r in api)
    pp = '\n'.join('server %s:80 max_fails=1 fail_timeout=60s%s;' % (r['status']['podIP'], ' backup' if i else '') for i, r in enumerate(proxy))
    pt = '\n'.join('server %s:443 max_fails=1 fail_timeout=60s%s;' % (r['status']['podIP'], ' backup' if i else '') for i, r in enumerate(proxy))
    return '''worker_processes 1;
pid /tmp/cube-ha.pid;
error_log /dev/stderr notice;
events { worker_connections 512; }
stream {
 log_format lab '$time_iso8601 $server_port $upstream_addr $status $session_time';
 access_log /dev/stdout lab;
 upstream api_tcp { %s }
 upstream proxy_tcp { %s }
 upstream proxy_tls { %s }
 server { listen 8081; proxy_pass api_tcp; proxy_connect_timeout 1s; proxy_timeout 60s; proxy_next_upstream off; }
 server { listen 8083; proxy_pass proxy_tcp; proxy_connect_timeout 1s; proxy_timeout 60s; proxy_next_upstream off; }
 server { listen 8443; proxy_pass proxy_tls; proxy_connect_timeout 1s; proxy_timeout 60s; proxy_next_upstream off; }
}
http {
 access_log /dev/stdout;
 client_body_temp_path /tmp/client_temp;
 proxy_temp_path /tmp/proxy_temp;
 map $http_upgrade $connection_upgrade { default upgrade; '' ''; }
 upstream api_http { %s keepalive 16; }
 upstream proxy_http { %s }
 proxy_http_version 1.1;
 proxy_set_header Host $http_host;
 proxy_set_header Connection $connection_upgrade;
 proxy_set_header Upgrade $http_upgrade;
 proxy_connect_timeout 1s;
 proxy_read_timeout 60s;
 proxy_send_timeout 60s;
 proxy_next_upstream off;
 proxy_buffering off;
 proxy_request_buffering off;
 gzip off;
 add_header X-Cube-Lab-Backend $upstream_addr always;
 server { listen 8080; location / { proxy_pass http://api_http; } }
 server { listen 8082; location / { proxy_pass http://proxy_http; } }
}
''' % (ap, pp, pt, ap, pp)


def configure_lb(api, proxy, initial=False):
    text = nginx(api, proxy)
    data.setdefault('lb_configs', []).append({'at': time.time(), 'sha256': hashlib.sha256(text.encode()).hexdigest(),
        'api': [{'name': r['metadata']['name'], 'ip': r['status']['podIP'], 'node': r['spec']['nodeName']} for r in api],
        'proxy': [{'name': r['metadata']['name'], 'ip': r['status']['podIP'], 'node': r['spec']['nodeName']} for r in proxy]})
    (root / ('nginx-' + str(len(data['lb_configs'])) + '.conf')).write_text(text)
    if initial:
        labels = {'app': 'cube-ha-lb'}
        manifest = {'apiVersion': 'v1', 'kind': 'List', 'items': [
            {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': 'cube-ha-lb', 'namespace': lab}, 'data': {'nginx.conf': text}},
            {'apiVersion': 'apps/v1', 'kind': 'Deployment', 'metadata': {'name': 'cube-ha-lb', 'namespace': lab},
             'spec': {'replicas': 1, 'selector': {'matchLabels': labels}, 'template': {'metadata': {'labels': labels}, 'spec': {
                 'nodeSelector': {'kubernetes.io/hostname': cfg['node']}, 'automountServiceAccountToken': False,
                 'containers': [{'name': 'nginx', 'image': cfg['lb_image'],
                     'command': ['sh', '-c', 'cp /app/nginx.conf /tmp/nginx.conf; exec nginx -p /tmp/ -c /tmp/nginx.conf -g "daemon off;"'],
                     'resources': {'requests': {'cpu': '50m', 'memory': '32Mi'}, 'limits': {'cpu': '500m', 'memory': '128Mi'}},
                     'readinessProbe': {'tcpSocket': {'port': 8080}, 'periodSeconds': 2},
                     'volumeMounts': [{'name': 'config', 'mountPath': '/app', 'readOnly': True}]}],
                 'volumes': [{'name': 'config', 'configMap': {'name': 'cube-ha-lb'}}]}}}}]}
        if kube('-n', lab, 'get', 'deployment', 'cube-ha-lb', '--ignore-not-found').strip():
            raise RuntimeError('lab LB already exists')
        kube('apply', '-f', '-', input=json.dumps(manifest))
        kube('-n', lab, 'rollout', 'status', 'deploy/cube-ha-lb', '--timeout=120s', timeout=130)
        stream = (root / 'port-forward.log').open('w')
        child = subprocess.Popen(['kubectl', '--context', cfg['context'], '-n', lab, 'port-forward', 'deploy/cube-ha-lb',
            '19980:8080', '19981:8081', '19982:8082', '19983:8083', '19984:8443'], stdout=stream, stderr=stream)
        forwards.append(child)
        time.sleep(2)
    else:
        kube('-n', lab, 'exec', '-i', 'deploy/cube-ha-lb', '--', 'sh', '-c',
             'cat > /tmp/nginx.conf && nginx -p /tmp/ -c /tmp/nginx.conf -t && nginx -p /tmp/ -c /tmp/nginx.conf -s reload', input=text)
        time.sleep(1)
    save()


def command(sb, text, timeout=4):
    r = sb.commands.run(text, timeout=timeout)
    if r.exit_code:
        raise RuntimeError('guest exit ' + str(r.exit_code))
    return r.stdout


def identity_read(sb):
    return json.loads(command(sb, "python3 -c 'import urllib.request; print(urllib.request.urlopen(\"http://127.0.0.1:18080/state\").read().decode())'"))


def new_guest(config, purpose):
    sb = Sandbox.create(template=cfg['template'], timeout=1200, allow_internet_access=False,
                        metadata={'purpose': purpose}, config=config)
    guests.append(sb)
    return sb


def state_ok(response, expected):
    response.raise_for_status()
    value = response.json()
    assert value['identity'] == expected and value['counter'] > 0
    return value


def read_probe(row, route, kind, sb, identity, end):
    s = session()
    endpoint = {'L7': api_l7, 'L4': api_l4}[route] if kind == 'list' else {'L7': proxy_l7, 'L4': proxy_l4}[route]
    data_config = Config(api_url=api_l7, proxy_node_ip='127.0.0.1', proxy_port=19982 if route == 'L7' else 19983, request_timeout=3)
    routed = Sandbox(sb._data, config=data_config)
    while not end.is_set():
        t = time.time()
        sample = {'at': t, 'route': route, 'kind': kind, 'stage': row['stage'], 'ok': False}
        r = None
        try:
            if kind == 'list':
                r = s.get(endpoint + '/sandboxes', headers={'Connection': 'close'}, timeout=2)
                sample['status'] = r.status_code
                sample['private_backend'] = r.headers.get('X-Cube-Lab-Backend')
                r.raise_for_status()
                value = r.json()
                # Semantic check: require the known sandbox ID inside the actual list response.
                assert isinstance(value, (dict, list)) and sb.sandbox_id in json.dumps(value)
            else:
                value = identity_read(routed)
                assert value['identity'] == identity and value['counter'] > 0
                sample.update(counter=value['counter'], identity_same=True)
            sample['ok'] = True
        except Exception as exc:
            sample['error'] = type(exc).__name__
            if r is not None:
                sample['private_body'] = r.text[:1000]
        sample['seconds'] = time.time() - t
        with lock:
            row['samples'].append(sample)
        metric('cube_ha_probe_success', int(sample['ok']), row['case'], route=route, kind=kind)
        metric('cube_ha_probe_latency_seconds', sample['seconds'], row['case'], route=route, kind=kind)
        if kind == 'guest' and sample['ok']:
            metric('cube_ha_guest_counter', sample['counter'], row['case'], route=route)
        end.wait(0.4)


def lifecycle(row, end):
    config = Config(api_url=api_l7, proxy_node_ip='127.0.0.1', proxy_port=19982, request_timeout=8)
    while not end.is_set():
        value = {'at': time.time(), 'stage': row['stage'], 'create': False, 'exec': False, 'delete': False}
        sb = None
        try:
            sb = new_guest(config, 'cube-ha-lifecycle')
            value['create'] = True
            value['private_id'] = sb.sandbox_id
            value['exec'] = command(sb, 'printf HA_LIFECYCLE', timeout=3) == 'HA_LIFECYCLE'
            sb.kill()
            value['delete'] = True
        except Exception as exc:
            value['error'] = type(exc).__name__
            value['private_error'] = str(exc)[:1000]
        finally:
            if sb and not value['delete']:
                try:
                    Sandbox.connect(sb.sandbox_id, config=base).kill()
                    value['cleanup_via_original_api'] = True
                except Exception as exc:
                    value['cleanup_error'] = type(exc).__name__
            value['seconds'] = time.time() - value['at']
            value['ok'] = all(value[k] for k in ('create', 'exec', 'delete'))
            with lock:
                row['lifecycle'].append(value)
            metric('cube_ha_lifecycle_success', int(value['ok']), row['case'])
        end.wait(3)


def receive_stream(row, route, kind, sb, identity, end):
    value = {'route': route, 'kind': kind, 'opened': time.time(), 'frames': [], 'connected': False}
    row['streams'].append(value)
    host = '49983-' + sb.sandbox_id + '.cube.app'
    port = 19982 if route == 'L7' else 19983
    handle = None
    try:
        script = 'import urllib.request,time\nfor _ in range(120):\n print(urllib.request.urlopen("http://127.0.0.1:18080/state").read().decode(),flush=True)\n time.sleep(.5)'
        payload = {'process': {'cmd': '/bin/bash', 'args': ['-lc', 'python3 -u -c ' + shlex.quote(script)], 'envs': {}, 'cwd': ''}, 'stdin': False}
        headers = {'Host': host, 'Content-Type': 'application/connect+json', 'Connect-Protocol-Version': '1',
                   'Connect-Content-Encoding': 'identity', 'Connect-Timeout-Ms': '65000',
                   'Authorization': 'Basic ' + base64.b64encode(b'root:').decode()}
        if sb._data.get('envdAccessToken'):
            headers['X-Access-Token'] = sb._data['envdAccessToken']
        handle = session().post('http://127.0.0.1:' + str(port) + '/process.Process/Start',
                    data=_encode_connect_envelope(json.dumps(payload).encode()), headers=headers, stream=True, timeout=3)
        handle.raise_for_status()
        value['connected'] = True
        metric('cube_ha_stream_open', 1, row['case'], route=route, protocol=kind)
        buffer, stdout = bytearray(), ''
        for chunk in handle.iter_content(chunk_size=1):
            if end.is_set():
                value['controller_closed'] = True
                break
            buffer.extend(chunk)
            if len(buffer) < 5:
                continue
            size = struct.unpack('!I', buffer[1:5])[0]
            if len(buffer) < size + 5:
                continue
            flags, raw = buffer[0], bytes(buffer[5:5+size])
            del buffer[:5+size]
            event = json.loads(raw)
            if flags & 2:
                if event.get('error'):
                    raise RuntimeError('Connect end-stream error')
                continue
            encoded = event.get('event', {}).get('data', {}).get('stdout')
            if not encoded:
                continue
            stdout += base64.b64decode(encoded).decode()
            while '\n' in stdout:
                frame, stdout = stdout.split('\n', 1)
                point = json.loads(frame)
                assert point['identity'] == identity
                value['frames'].append({'at': time.time(), 'counter': point['counter']})
                metric('cube_ha_stream_frames_total', len(value['frames']), row['case'], route=route, protocol=kind)
    except Exception as exc:
        value['error'] = type(exc).__name__
    finally:
        value['closed'] = time.time()
        metric('cube_ha_stream_open', 0, row['case'], route=route, protocol=kind)
        if handle:
            handle.close()


def run_case(component, sb, identity):
    api, proxy = ready_two('api'), ready_two('cube-proxy')
    configure_lb(api, proxy)
    candidates = ready_two(component)
    victim = candidates[0]
    row = {'case': 'ha-' + component + '-a01', 'component': component, 'stage': 'baseline', 'started': time.time(),
           'victim': {'name': victim['metadata']['name'], 'uid': victim['metadata']['uid'], 'ip': victim['status']['podIP']},
           'samples': [], 'lifecycle': [], 'streams': [], 'phases': {'baseline': time.time()}}
    data['cases'].append(row)
    end = threading.Event()
    threads = []
    metric('cube_ha_stage', 0, row['case'])
    for route in ('L4', 'L7'):
        for kind in ('list', 'guest'):
            threads.append(threading.Thread(target=read_probe, args=(row, route, kind, sb, identity, end)))
        if component == 'cube-proxy':
            for kind in ('connect-command',):
                threads.append(threading.Thread(target=receive_stream, args=(row, route, kind, sb, identity, end)))
    threads.append(threading.Thread(target=lifecycle, args=(row, end)))
    for thread in threads:
        thread.start()
    try:
        time.sleep(8)
        assert all(any(s['ok'] and s['route'] == route and s['kind'] == kind for s in row['samples']) for route in ('L4', 'L7') for kind in ('list', 'guest'))
        assert row['lifecycle'] and all(r['ok'] for r in row['lifecycle']), 'lifecycle baseline failed'
        if row['streams']:
            assert len(row['streams']) == 2 and all(r['connected'] and len(r['frames']) >= 6 for r in row['streams']), 'stream baseline failed'
        row['stage'] = 'fault'
        row['phases']['fault_issued'] = time.time()
        metric('cube_ha_stage', 1, row['case'])
        kube('-n', ns, 'delete', 'pod', victim['metadata']['name'], '--grace-period=1', '--wait=false')
        row['phases']['delete_returned'] = time.time()
        deadline = time.monotonic() + 45
        while kube('-n', ns, 'get', 'pod', victim['metadata']['name'], '--ignore-not-found').strip():
            if time.monotonic() > deadline:
                raise RuntimeError('victim deletion not confirmed')
            time.sleep(0.3)
        row['phases']['victim_absent'] = time.time()
        time.sleep(18)
        replacements = ready_two(component)
        row['phases']['replacement_ready'] = time.time()
        row['replacement_uids'] = [r['metadata']['uid'] for r in replacements]
        row['stage'] = 'recovered'
        row['phases']['recovered'] = time.time()
        metric('cube_ha_stage', 2, row['case'])
        time.sleep(7)
        row['result'] = 'MEASURED'
    except Exception as exc:
        row['result'] = 'ERROR'
        row['error'] = type(exc).__name__ + ': ' + str(exc)[:1000]
        raise
    finally:
        end.set()
        for thread in threads:
            thread.join(timeout=12)
        assert not any(t.is_alive() for t in threads), 'probe thread failed to stop'
        row['phases']['complete'] = time.time()
        metric('cube_ha_stage', 3, row['case'])
        row['after_state'] = identity_read(sb)
        save()
        print(row['case'], row['result'], 'samples', len(row['samples']), 'lifecycle', len(row['lifecycle']), flush=True)


try:
    assert Sandbox.list(config=base) == [], 'installation must be idle'
    for name in ('cube-api', 'cube-master', 'cube-proxy'):
        obj = json.loads(kube('-n', ns, 'get', 'deployment', name, '-o', 'json'))
        original[name] = obj['spec']['replicas']
    data['original_replicas'] = dict(original)
    arm()
    threading.Thread(target=heartbeat, daemon=True).start()
    for name in original:
        kube('-n', ns, 'scale', 'deployment/' + name, '--replicas=2')
    for component in ('api', 'master', 'cube-proxy'):
        rows = ready_two(component)
        assert all(r['spec']['nodeName'] == cfg['node'] for r in rows), 'unexpected placement'
    configure_lb(ready_two('api'), ready_two('cube-proxy'), initial=True)
    sb = new_guest(base, 'cube-ha-subject')
    sb.files.write('/tmp/cube-ha-guest.py', Path(__file__).with_name('guest.py').read_text())
    command(sb, 'nohup setsid python3 /tmp/cube-ha-guest.py </dev/null >/tmp/cube-ha.log 2>&1 &')
    time.sleep(2)
    initial = identity_read(sb)
    data['initial_state'] = initial
    data['private_subject_id'] = sb.sandbox_id
    # Pin actual runtime, not just the Deployment image tag.
    process_script = Path('examples/cubesandbox-fault-drill/process_guard.py').read_text()
    runtime = json.loads(kube('-n', ns, 'exec', 'ds/cube-node', '-c', 'cubelet', '--', 'python3', '-c', process_script,
                             json.dumps({'action': 'discover', 'mode': 'vmm', 'sandbox_id': sb.sandbox_id})))
    data['runtime'] = runtime
    assert cfg['required_shim_sha256'] in json.dumps(runtime), 'actual runtime hash mismatch'
    host = '49983-' + sb.sandbox_id + '.cube.app'
    tls_payload = {'process': {'cmd': '/bin/bash', 'args': ['-lc', 'printf TLS_PASSTHROUGH'], 'envs': {}, 'cwd': ''}, 'stdin': False}
    tls_headers = {'Host': host, 'Content-Type': 'application/connect+json', 'Connect-Protocol-Version': '1',
                   'Connect-Content-Encoding': 'identity', 'Connect-Timeout-Ms': '3000',
                   'Authorization': 'Basic ' + base64.b64encode(b'root:').decode()}
    if sb._data.get('envdAccessToken'):
        tls_headers['X-Access-Token'] = sb._data['envdAccessToken']
    response = http.post('https://127.0.0.1:19984/process.Process/Start',
                         data=_encode_connect_envelope(json.dumps(tls_payload).encode()), headers=tls_headers, verify=False, timeout=4)
    data['private_tls_response'] = {'status': response.status_code, 'body': response.text[:1000]}
    save()
    response.raise_for_status()
    tls_result = _parse_process_start_stream([response.content])
    assert tls_result.exit_code == 0 and tls_result.stdout == 'TLS_PASSTHROUGH'
    data['tls_passthrough'] = {'at': time.time(), 'ok': True, 'certificate_verification': False, 'reason': 'existing lab self-signed certificate'}
    save()
    for component in ('api', 'master', 'cube-proxy'):
        if time.time() - started > 1050:
            raise RuntimeError('total deadline')
        run_case(component, sb, initial['identity'])
        assert identity_read(sb)['identity'] == initial['identity']
    data['result'] = 'MEASURED'
except Exception as exc:
    data['result'] = 'ERROR'
    data['error'] = type(exc).__name__ + ': ' + str(exc)[:1500]
    print(data['error'], flush=True)
finally:
    for sb in reversed(guests):
        try:
            ids = {s['sandboxID'] for s in Sandbox.list(config=base)}
            if sb.sandbox_id in ids:
                Sandbox.connect(sb.sandbox_id, config=base).kill()
        except Exception as exc:
            data['cleanup'].setdefault('guest_errors', []).append(type(exc).__name__)
    for name, count in original.items():
        try:
            kube('-n', ns, 'scale', 'deployment/' + name, '--replicas=' + str(count))
            kube('-n', ns, 'rollout', 'status', 'deployment/' + name, '--timeout=90s', timeout=100)
        except Exception as exc:
            data['cleanup'].setdefault('scale_errors', []).append(name + ':' + type(exc).__name__)
    for child in forwards:
        child.terminate()
    try:
        data['lb_logs'] = kube('-n', lab, 'logs', 'deploy/cube-ha-lb', '--tail=10000')
        kube('-n', lab, 'delete', 'deployment/cube-ha-lb', 'configmap/cube-ha-lb', '--ignore-not-found')
    except Exception as exc:
        data['cleanup']['lb_error'] = type(exc).__name__
    try:
        remaining = Sandbox.list(config=base)
        for item in remaining:
            if item.get('metadata', {}).get('purpose', '').startswith('cube-ha-'):
                Sandbox.connect(item['sandboxID'], config=base).kill()
        data['cleanup']['remaining_sandboxes'] = len(Sandbox.list(config=base))
        smoke = new_guest(base, 'cube-ha-final-smoke')
        data['cleanup']['new_exec'] = command(smoke, 'printf HA_RESTORED') == 'HA_RESTORED'
        smoke.kill()
        data['cleanup']['final_inventory'] = len(Sandbox.list(config=base))
    except Exception as exc:
        data['cleanup']['smoke_error'] = type(exc).__name__ + ':' + str(exc)[:500]
    data['ended'] = time.time()
    stopped.set()
    if not data['cleanup'].get('scale_errors'):
        (root / 'done').write_text(str(time.time()))
    save()
    print('RESULT', data['result'], 'cleanup', json.dumps(data['cleanup']), flush=True)
