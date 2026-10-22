"""Bounded, single-node Microsandbox experiment. Expose only through localhost forwarding."""
import asyncio
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.metadata
import json
import os
from pathlib import Path
import signal
import subprocess
import threading
import time
import traceback
import uuid

import microsandbox as msb
from prometheus_client import Gauge, generate_latest, CONTENT_TYPE_LATEST

ROOT = Path(os.environ.get('LAB_DATA', '/data'))
EVIDENCE = ROOT / 'evidence'
EVIDENCE.mkdir(parents=True, exist_ok=True)
ATTEMPT = os.environ.get('LAB_ATTEMPT', '02')
IMAGE = os.environ.get('GUEST_IMAGE', 'python-lab:local')
state = {'version': importlib.metadata.version('microsandbox'), 'attempt': ATTEMPT,
         'phase': 'ready', 'busy': False, 'records': []}
for path in sorted(EVIDENCE.glob('record-*.json')):
    state['records'].append(json.loads(path.read_text()))
loop = asyncio.new_event_loop()
boxes = {}
metrics = {k: Gauge('microsandbox_lab_' + k, text) for k, text in {
    'running_boxes': 'Active sandboxes tracked by the experiment, not a platform capacity gauge',
    'passed_checks': 'Passed persisted experiment records',
    'failed_checks': 'Failed persisted experiment records',
    'last_start_seconds': 'Latest client-observed create latency with a cached guest image',
    'stress_active': 'One during the bounded four-guest CPU task',
    'container_cpu_seconds_total': 'Own container cgroup CPU time, including VMM processes',
    'container_working_set_bytes': 'Own container cgroup usage minus inactive file cache',
}.items()}


def record(test, status, **values):
    row = {'test': test, 'status': status, 'at': time.time(), 'attempt': ATTEMPT,
           'code_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), **values}
    (EVIDENCE / f'record-{time.time_ns()}.json').write_text(json.dumps(row, indent=2))
    state['records'].append(row)
    print(json.dumps(row), flush=True)
    return row


async def check(test, fn):
    state['phase'] = test
    try:
        return record(test, 'passed', **await asyncio.wait_for(fn(), 300))
    except Exception as exc:
        return record(test, 'failed', error=repr(exc), traceback=traceback.format_exc())


async def create(prefix='lab'):
    name = prefix + '-' + uuid.uuid4().hex[:8]
    t = time.monotonic()
    box = await asyncio.wait_for(msb.Sandbox.create(name, image=IMAGE, cpus=1, memory=512,
        pull_policy=msb.PullPolicy.NEVER, max_duration=600), 60)
    elapsed = time.monotonic() - t
    boxes[name] = box
    metrics['last_start_seconds'].set(elapsed)
    return name, box, elapsed


async def stop(name):
    box = boxes.get(name)
    if box is not None:
        await asyncio.wait_for(box.stop(timeout=15), 25)
        await asyncio.wait_for(msb.Sandbox.remove(name), 20)
        boxes.pop(name, None)


async def execute(box, code, timeout=15):
    return await asyncio.wait_for(box.exec('python', ['-c', code], timeout=timeout), timeout + 15)


async def verified_exec(box, code):
    out = await execute(box, code)
    assert out.exit_code == 0, out.stderr_text
    return out.stdout_text.strip()


async def cached_start():
    samples = []
    for _ in range(10):
        name, box, elapsed = await create('cached')
        try:
            assert await verified_exec(box, 'print(sum(range(101)))') == '5050'
            samples.append(elapsed)
        finally:
            await stop(name)
    return {'samples_seconds': samples, 'count': len(samples)}


async def warm_exec():
    name, box, _ = await create('warm')
    samples = []
    try:
        for _ in range(20):
            t = time.monotonic()
            assert await verified_exec(box, 'print(sum(range(101)))') == '5050'
            samples.append(time.monotonic() - t)
        return {'samples_seconds': samples, 'count': len(samples)}
    finally:
        await stop(name)


async def isolation():
    a_name, a, _ = await create('isolated-a')
    b_name, b, _ = await create('isolated-b')
    try:
        token = uuid.uuid4().hex
        await a.fs.write('/root/isolated.txt', token.encode())
        assert not await b.fs.exists('/root/isolated.txt')
        code = 'from pathlib import Path;import platform,json;print(json.dumps({"boot_id":Path("/proc/sys/kernel/random/boot_id").read_text().strip(),"kernel":platform.release()}))'
        va, vb = [json.loads(await verified_exec(box, code)) for box in [a, b]]
        assert va['boot_id'] != vb['boot_id']
        src, dst = ROOT / 'fixture.txt', ROOT / 'roundtrip.txt'
        src.write_text('Microsandbox file round trip\n')
        await a.fs.copy_from_host(str(src), '/root/fixture.txt')
        await a.fs.copy_to_host('/root/fixture.txt', str(dst))
        assert src.read_bytes() == dst.read_bytes()
        return {'separate_boot_ids': True, 'separate_files': True, 'guest_kernel': va['kernel'],
                'roundtrip_sha256': hashlib.sha256(dst.read_bytes()).hexdigest()}
    finally:
        await stop(a_name)
        await stop(b_name)


async def timeout_check():
    name, box, _ = await create('timeout')
    try:
        t = time.monotonic()
        try:
            out = await execute(box, 'import time;time.sleep(20)', timeout=2)
            assert out.exit_code != 0
            behavior = 'nonzero exit: ' + str(out.exit_code)
        except msb.ExecTimeoutError:
            behavior = 'ExecTimeoutError'
        elapsed = time.monotonic() - t
        assert elapsed < 8
        assert await verified_exec(box, 'print("alive")') == 'alive'
        return {'elapsed_seconds': elapsed, 'timeout_seconds': 2, 'behavior': behavior, 'still_usable': True}
    finally:
        await stop(name)


async def stress():
    names = []
    metrics['stress_active'].set(1)
    try:
        # Launch separately; the CPU operations below run concurrently.
        for _ in range(4):
            name, box, _ = await create('cpu')
            names.append(name)
        t = time.monotonic()
        code = 'import hashlib,time;end=time.monotonic()+90;n=0\nwhile time.monotonic()<end:\n hashlib.sha256(b"x"*65536).digest();n+=1\nprint(n)'
        outs = await asyncio.gather(*(execute(boxes[n], code, timeout=105) for n in names))
        assert all(x.exit_code == 0 and int(x.stdout_text.strip()) > 0 for x in outs)
        return {'concurrency': 4, 'cpus_each': 1, 'memory_mib_each': 512,
                'duration_seconds': 90, 'elapsed_seconds': time.monotonic() - t,
                'iterations': [int(x.stdout_text.strip()) for x in outs]}
    finally:
        for name in names:
            await stop(name)
        metrics['stress_active'].set(0)


async def get_state(box, increment=False):
    path = '/increment' if increment else '/state'
    return json.loads(await verified_exec(box, 'import urllib.request;print(urllib.request.urlopen("http://127.0.0.1:8088' + path + '",timeout=3).read().decode())'))


async def start_state_server(box):
    await box.fs.write('/root/state_server.py', Path('/app/state_server.py').read_bytes())
    # Active runtime-managed jobs cannot be captured in v0.7.8. The shell
    # finishes after starting this guest daemon; its state stays inside the VM.
    out = await box.exec('sh', ['-c', 'nohup python /root/state_server.py >/tmp/state-server.log 2>&1 </dev/null &'], timeout=10)
    assert out.exit_code == 0, out.stderr_text
    for _ in range(20):
        try:
            return await get_state(box)
        except Exception:
            await asyncio.sleep(.1)
    raise RuntimeError('State server did not become ready')


async def fork_check():
    name, box, _ = await create('fork-source')
    child_name = 'fork-child-' + uuid.uuid4().hex[:8]
    try:
        before = await start_state_server(box)
        t = time.monotonic()
        child = await asyncio.wait_for(box.fork(child_name), 60)
        boxes[child_name] = child
        elapsed = time.monotonic() - t
        inherited = await get_state(child)
        assert inherited == before
        changed = await get_state(child, True)
        source = await get_state(box)
        assert changed['counter'] == 42 and source['counter'] == 41
        await child.fs.write('/root/child-only.txt', b'child')
        assert not await box.fs.exists('/root/child-only.txt')
        return {'fork_seconds': elapsed, 'same_in_memory_nonce': True, 'same_boot_id': True,
                'source_counter': source['counter'], 'child_counter': changed['counter'], 'disk_cow_isolated': True}
    finally:
        await stop(child_name)
        await stop(name)


async def snapshot_prepare():
    name, box, _ = await create('snapshot-source')
    root = ROOT / 'snapshots'
    root.mkdir(exist_ok=True)
    try:
        expected = await start_state_server(box)
        await box.fs.write('/root/persistent-marker.txt', b'snapshot disk survives\n')
        values = {}
        for mode, full in [('full', True), ('disk', False)]:
            path = root / (mode + '-' + ATTEMPT + '.msb')
            t = time.monotonic()
            await asyncio.wait_for(msb.Snapshot.create_archive(mode + '-' + ATTEMPT,
                str(path), from_sandbox=name, full=full), 90)
            values[mode] = {'path': str(path), 'capture_seconds': time.monotonic() - t,
                            'bytes': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        (EVIDENCE / ('snapshot-expected-' + ATTEMPT + '.json')).write_text(json.dumps(expected))
        return {'archives': values, 'counter': expected['counter'], 'source_stopped_after_capture': True}
    finally:
        await stop(name)


async def snapshot_verify():
    expected = json.loads((EVIDENCE / ('snapshot-expected-' + ATTEMPT + '.json')).read_text())
    values = {}
    for mode in ['full', 'disk']:
        name = mode + '-restored-' + uuid.uuid4().hex[:8]
        t = time.monotonic()
        box = await asyncio.wait_for(msb.Sandbox.restore(str(ROOT / 'snapshots' / (mode + '-' + ATTEMPT + '.msb')),
            name=name, max_duration=300), 90)
        boxes[name] = box
        elapsed = time.monotonic() - t
        try:
            assert await box.fs.read_text('/root/persistent-marker.txt') == 'snapshot disk survives\n'
            if mode == 'full':
                actual = await get_state(box)
                assert actual == expected, (actual, expected)
            else:
                out = await execute(box, 'import socket;s=socket.socket();s.settimeout(1);print(s.connect_ex(("127.0.0.1",8088)))')
                assert out.exit_code == 0 and int(out.stdout_text.strip()) != 0
                actual = await start_state_server(box)
                assert actual['nonce'] != expected['nonce'] and actual['boot_id'] != expected['boot_id']
            values[mode] = {'restore_seconds': elapsed, 'marker_preserved': True,
                'memory_nonce_preserved': actual['nonce'] == expected['nonce'],
                'boot_id_preserved': actual['boot_id'] == expected['boot_id'], 'counter': actual['counter']}
        finally:
            await stop(name)
    return values


async def suite():
    try:
        for test, fn in [('cached_start', cached_start), ('warm_exec', warm_exec),
                         ('isolation', isolation), ('timeout', timeout_check), ('parallel_cpu', stress),
                         ('live_fork', fork_check), ('snapshot_prepare', snapshot_prepare)]:
            await check(test, fn)
    finally:
        for name in list(boxes):
            try:
                await stop(name)
            except Exception as exc:
                record('cleanup', 'failed', error=repr(exc))
        state.update(busy=False, phase='ready')


def own_cgroup(controller):
    groups = {}
    for line in Path('/proc/self/cgroup').read_text().splitlines():
        _, controllers, group = line.split(':', 2)
        for key in controllers.split(','):
            groups[key] = group
    mounted = Path('/sys/fs/cgroup') / controller
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        fields = line.split()
        if fields[4] == str(mounted.resolve()):
            return mounted / Path(groups[controller]).relative_to(fields[3])
    raise RuntimeError('Own cgroup v1 mount not found')


async def sample():
    while True:
        metrics['running_boxes'].set(len(boxes))
        for status in ['passed', 'failed']:
            metrics[status + '_checks'].set(sum(x['status'] == status for x in state['records']))
        try:
            cpu, mem = own_cgroup('cpuacct'), own_cgroup('memory')
            metrics['container_cpu_seconds_total'].set(int((cpu / 'cpuacct.usage').read_text()) / 1e9)
            detail = dict(line.split() for line in (mem / 'memory.stat').read_text().splitlines())
            metrics['container_working_set_bytes'].set(max(0, int((mem / 'memory.usage_in_bytes').read_text()) - int(detail['total_inactive_file'])))
        except Exception as exc:
            print('Container cgroup sample unavailable:', repr(exc), flush=True)
        await asyncio.sleep(2)


class Handler(BaseHTTPRequestHandler):
    def send(self, body, status=200, kind='application/json'):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header('Content-Type', kind)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == '/':
            return self.send(Path('/app/index.html').read_bytes(), kind='text/html; charset=utf-8')
        if self.path == '/api/state':
            return self.send(state)
        if self.path == '/metrics':
            return self.send(generate_latest(), kind=CONTENT_TYPE_LATEST)
        self.send({'error': 'not found'}, 404)

    def do_POST(self):
        if self.headers.get('Origin') not in (None, 'http://127.0.0.1:18950', 'http://localhost:18950'):
            return self.send({'error': 'origin not allowed'}, 403)
        async def retry_capture():
            await check('live_fork', fork_check)
            await check('snapshot_prepare', snapshot_prepare)
        functions = {'/api/suite': suite, '/api/restore': lambda: check('snapshot_verify', snapshot_verify),
                     '/api/capture': retry_capture,
                     '/api/resource-run': lambda: check('parallel_cpu_repeat', stress)}
        fn = functions.get(self.path)
        if fn is None:
            return self.send({'error': 'not found'}, 404)
        if state['busy']:
            return self.send({'error': 'already running'}, 409)
        state['busy'] = True
        async def run():
            try:
                await asyncio.wait_for(fn(), 1200)
            finally:
                state.update(busy=False, phase='ready')
        asyncio.run_coroutine_threadsafe(run(), loop)
        self.send({'accepted': True}, 202)

    def log_message(self, *_):
        pass


async def main():
    collector = None
    endpoint = os.environ.get('OTEL_METRICS_ENDPOINT')
    if endpoint:
        collector = subprocess.Popen(['msb-metrics', 'otel', '--endpoint=' + endpoint,
            '--protocol=http', '--collect-interval=2s', '--flush-interval=2s',
            '--export-timeout=10s', '--resource=service.instance.id=kvm-lab'])
    asyncio.create_task(sample())
    shutdown = asyncio.Event()
    loop.add_signal_handler(signal.SIGTERM, shutdown.set)
    loop.add_signal_handler(signal.SIGINT, shutdown.set)
    await shutdown.wait()
    for name in list(boxes):
        await stop(name)
    if collector:
        collector.terminate()
        await asyncio.to_thread(collector.wait, 10)


if __name__ == '__main__':
    threading.Thread(target=ThreadingHTTPServer(('0.0.0.0', 9118), Handler).serve_forever, daemon=True).start()
    loop.run_until_complete(main())
