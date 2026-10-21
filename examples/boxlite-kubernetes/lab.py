"""Single-node BoxLite laboratory; HTTP access must stay behind localhost forwarding."""
import asyncio
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import signal
import threading
import time
import uuid

import boxlite
from prometheus_client import Gauge, generate_latest, CONTENT_TYPE_LATEST

ROOT = Path(os.environ.get('LAB_DATA', '/data'))
ROOT.mkdir(parents=True, exist_ok=True)
EVIDENCE = ROOT / 'evidence'
EVIDENCE.mkdir(exist_ok=True)
IMAGE = os.environ.get('GUEST_IMAGE', 'docker.io/library/python:3.12-slim')
registries = []
if os.environ.get('LAB_REGISTRY_SKIP_VERIFY') == 'true':
    registries = [boxlite.ImageRegistry(host=IMAGE.split('/')[0], skip_verify=True)]
runtime = boxlite.Boxlite(boxlite.Options(home_dir=str(ROOT / 'runtime'), image_registries=registries))
boxes = {}
ATTEMPT = os.environ.get('LAB_ATTEMPT', '02')
state = {'version': boxlite.__version__, 'attempt': ATTEMPT, 'phase': 'ready', 'records': [], 'busy': False}
for path in sorted(EVIDENCE.glob(f'record-attempt{ATTEMPT}-*.json')):
    state['records'].append(json.loads(path.read_text()))
loop = asyncio.new_event_loop()
stats = {name: Gauge('boxlite_lab_' + name, help_text) for name, help_text in {
    'running_boxes': 'SDK-reported running boxes in this runtime',
    'completed_checks': 'Successful laboratory checks, reconstructed from evidence files',
    'failed_checks': 'Failed laboratory checks, reconstructed from evidence files',
    'last_start_seconds': 'Latest client-observed start time, including initialization',
    'sdk_cpu_percent': 'Sum of available per-box SDK cpu_percent samples',
    'sdk_memory_bytes': 'Sum of available per-box SDK memory_bytes samples; SDK process accounting',
    'sdk_samples': 'Number of active boxes with available CPU and memory samples',
    'stress_active': 'One while the bounded four-box CPU workload is running',
    'container_cpu_seconds_total': 'Runner container cgroup CPU time including its VM processes',
    'container_working_set_bytes': 'Runner container cgroup usage minus inactive file cache',
}.items()}


def record(test, status, **values):
    row = {'test': test, 'status': status, 'attempt': ATTEMPT, 'at': time.time(), **values}
    path = EVIDENCE / (f'record-attempt{ATTEMPT}-' + str(time.time_ns()) + '.json')
    path.write_text(json.dumps(row, indent=2))
    state['records'].append(row)
    return row


async def create(name=None, keep=False):
    box = boxlite.SimpleBox(image=IMAGE, cpus=1, memory_mib=512,
                           runtime=runtime, name=name, auto_remove=not keep,
                           reuse_existing=bool(name and keep))
    started = time.monotonic()
    await asyncio.wait_for(box.start(), 120)
    boxes[box.id] = box
    seconds = time.monotonic() - started
    stats['last_start_seconds'].set(seconds)
    return box, seconds


async def stop(box):
    box_id = box.id
    await asyncio.wait_for(box.stop(), 30)
    boxes.pop(box_id, None)


async def execute(box, code, timeout=15):
    return await asyncio.wait_for(box.exec('python', '-c', code, timeout=timeout), timeout + 12)


async def check(test, fn):
    state['phase'] = test
    try:
        return record(test, 'passed', **await fn())
    except Exception as exc:
        return record(test, 'failed', error=repr(exc))


async def cached_start():
    measurements = []
    for _ in range(10):
        box, seconds = await create()
        try:
            first = time.monotonic()
            result = await execute(box, 'print(sum(range(101)))')
            assert result.exit_code == 0 and result.stdout.strip() == '5050'
            metrics = await box.metrics()
            measurements.append({'start_seconds': seconds,
                                 'first_exec_seconds': time.monotonic() - first,
                                 'sdk_create_ms': metrics.total_create_duration_ms})
        finally:
            await stop(box)
    return {'samples': measurements}


async def functional():
    a, _ = await create()
    b, _ = await create()
    try:
        token = uuid.uuid4().hex
        result = await execute(a, f'from pathlib import Path;Path("/root/isolation.txt").write_text("{token}");print(Path("/proc/sys/kernel/random/boot_id").read_text())')
        other = await execute(b, 'from pathlib import Path;import json;print(json.dumps({"exists":Path("/root/isolation.txt").exists(),"boot_id":Path("/proc/sys/kernel/random/boot_id").read_text().strip()}))')
        value = json.loads(other.stdout)
        assert result.exit_code == other.exit_code == 0
        assert not value['exists'] and value['boot_id'] != result.stdout.strip()
        fixture = ROOT / 'fixture.txt'
        fixture.write_text('BoxLite file round trip\n')
        await a.copy_in(str(fixture), '/root/fixture.txt')
        destination = ROOT / 'round-trip.txt'
        await a.copy_out('/root/fixture.txt', str(destination))
        assert destination.read_bytes() == fixture.read_bytes()
        return {'separate_boot_ids': True, 'file_not_visible_in_other_box': True,
                'round_trip_sha256': hashlib.sha256(destination.read_bytes()).hexdigest()}
    finally:
        await stop(a)
        await stop(b)


async def warm_exec():
    box, _ = await create()
    times = []
    try:
        for _ in range(20):
            started = time.monotonic()
            result = await execute(box, 'print(sum(range(101)))')
            assert result.exit_code == 0 and result.stdout.strip() == '5050'
            times.append(time.monotonic() - started)
        return {'samples_seconds': times}
    finally:
        await stop(box)


async def timeout_check():
    box, _ = await create()
    try:
        started = time.monotonic()
        result = await execute(box, 'import signal,time;signal.signal(signal.SIGALRM,signal.SIG_IGN);time.sleep(20)', timeout=2)
        elapsed = time.monotonic() - started
        assert result.exit_code != 0 and elapsed < 8
        probe = await execute(box, 'print("alive")')
        assert probe.exit_code == 0 and probe.stdout.strip() == 'alive'
        return {'timeout_seconds': 2, 'elapsed_seconds': elapsed,
                'exit_code': result.exit_code, 'box_still_usable': True}
    finally:
        await stop(box)


async def stress():
    active = await asyncio.gather(*(create() for _ in range(4)))
    started = time.monotonic()
    stats['stress_active'].set(1)
    try:
        results = await asyncio.gather(*(execute(box,
            'import time,hashlib;end=time.monotonic()+90;n=0\nwhile time.monotonic()<end:\n hashlib.sha256(b"boxlite"*8192).digest();n+=1\nprint(n)', timeout=105)
            for box, _ in active))
        assert all(r.exit_code == 0 and int(r.stdout.strip()) > 0 for r in results)
        return {'concurrency': 4, 'guest_cpus_each': 1, 'guest_memory_mib_each': 512,
                'elapsed_seconds': time.monotonic() - started,
                'iterations': [int(r.stdout.strip()) for r in results]}
    finally:
        stats['stress_active'].set(0)
        await asyncio.gather(*(stop(box) for box, _ in active))


async def persistence_prepare():
    name = 'persistent-' + uuid.uuid4().hex[:8]
    marker = uuid.uuid4().hex
    box, _ = await create(name, keep=True)
    result = await execute(box, f'from pathlib import Path;Path("/root/marker.txt").write_text("{marker}");print(Path("/proc/sys/kernel/random/boot_id").read_text().strip())')
    assert result.exit_code == 0
    checkpoint = {'name': name, 'box_id': box.id, 'marker': marker, 'boot_id': result.stdout.strip()}
    await stop(box)
    (ROOT / 'pending-persistence.json').write_text(json.dumps(checkpoint))
    return {'box_id': checkpoint['box_id'], 'stopped_before_pod_recreation': True}


async def persistence_verify():
    saved = json.loads((ROOT / 'pending-persistence.json').read_text())
    box, seconds = await create(saved['name'], keep=True)
    try:
        result = await execute(box, 'from pathlib import Path;import json;print(json.dumps({"marker":Path("/root/marker.txt").read_text(),"boot_id":Path("/proc/sys/kernel/random/boot_id").read_text().strip()}))')
        values = json.loads(result.stdout)
        assert result.exit_code == 0 and values['marker'] == saved['marker']
        assert box.id == saved['box_id'] and values['boot_id'] != saved['boot_id']
        return {'same_box_id': True, 'disk_marker_preserved': True,
                'new_guest_boot_id': True, 'start_seconds': seconds}
    finally:
        await stop(box)
        await runtime.remove(saved['box_id'])
        (ROOT / 'pending-persistence.json').unlink()


async def suite():
    try:
        for name, fn in [('cached_start', cached_start), ('warm_exec', warm_exec),
                         ('file_isolation', functional), ('timeout', timeout_check),
                         ('parallel_cpu', stress), ('persistence_prepare', persistence_prepare)]:
            await check(name, fn)
    finally:
        for box in list(boxes.values()):
            try:
                await stop(box)
            except Exception as exc:
                record('cleanup', 'failed', error=repr(exc))
        state.update(busy=False, phase='ready')


async def sample():
    while True:
        try:
            metric = await runtime.metrics()
            stats['running_boxes'].set(metric.num_running_boxes)
            groups = {}
            for line in Path('/proc/self/cgroup').read_text().splitlines():
                _, controllers, path = line.split(':', 2)
                for controller in controllers.split(','):
                    groups[controller] = path.lstrip('/')
            def mounted_group(controller):
                mounted = Path('/sys/fs/cgroup') / controller
                target = str(mounted.resolve())
                for line in Path('/proc/self/mountinfo').read_text().splitlines():
                    fields = line.split()
                    if fields[4] == target:
                        relative = Path('/' + groups[controller]).relative_to(fields[3])
                        return mounted / relative
                raise RuntimeError('Cannot identify own cgroup mount')
            cpu = mounted_group('cpuacct')
            memory = mounted_group('memory')
            if 'cpuacct' in groups and (cpu / 'cpuacct.usage').exists():
                stats['container_cpu_seconds_total'].set(int((cpu / 'cpuacct.usage').read_text()) / 1e9)
                usage = int((memory / 'memory.usage_in_bytes').read_text())
                detail = dict(line.split() for line in (memory / 'memory.stat').read_text().splitlines())
                stats['container_working_set_bytes'].set(max(0, usage - int(detail.get('total_inactive_file', '0'))))
            readings = await asyncio.gather(*(b.metrics() for b in list(boxes.values())), return_exceptions=True)
            valid = [m for m in readings if not isinstance(m, Exception) and m.cpu_percent is not None and m.memory_bytes is not None]
            stats['sdk_samples'].set(len(valid))
            if valid or not boxes:
                stats['sdk_cpu_percent'].set(sum(m.cpu_percent for m in valid))
                stats['sdk_memory_bytes'].set(sum(m.memory_bytes for m in valid))
            for status, name in [('passed', 'completed_checks'), ('failed', 'failed_checks')]:
                stats[name].set(sum(r['status'] == status for r in state['records']))
        except Exception as exc:
            print('Metric sampling failed:', repr(exc), flush=True)
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
        if self.path == '/metrics':
            return self.send(generate_latest(), kind=CONTENT_TYPE_LATEST)
        if self.path == '/api/state':
            return self.send(state)
        if self.path == '/':
            return self.send(Path('/app/index.html').read_bytes(), kind='text/html; charset=utf-8')
        self.send({'error': 'not found'}, 404)

    def do_POST(self):
        if self.headers.get('Origin') not in (None, 'http://127.0.0.1:18940', 'http://localhost:18940'):
            return self.send({'error': 'origin not allowed'}, 403)
        if self.path not in ('/api/suite', '/api/persistence-verify', '/api/resource-run'):
            return self.send({'error': 'not found'}, 404)
        if state['busy']:
            return self.send({'error': 'test already running'}, 409)
        state['busy'] = True

        async def run():
            try:
                if self.path == '/api/suite':
                    await suite()
                elif self.path == '/api/persistence-verify':
                    await check('persistence_verify', persistence_verify)
                else:
                    await check('parallel_cpu_repeat', stress)
            finally:
                state.update(busy=False, phase='ready')
        asyncio.run_coroutine_threadsafe(run(), loop)
        self.send({'accepted': True}, 202)

    def log_message(self, fmt, *args):
        if self.path != '/metrics':
            print(self.command, self.path, flush=True)


async def main():
    asyncio.create_task(sample())
    shutdown = asyncio.Event()
    loop.add_signal_handler(signal.SIGTERM, shutdown.set)
    loop.add_signal_handler(signal.SIGINT, shutdown.set)
    await shutdown.wait()
    await asyncio.wait_for(runtime.shutdown(), 30)


if __name__ == '__main__':
    threading.Thread(target=ThreadingHTTPServer(('0.0.0.0', 9108), Handler).serve_forever, daemon=True).start()
    loop.run_until_complete(main())
