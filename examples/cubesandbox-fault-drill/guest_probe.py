"""In-memory progress, durable marker, and independently received HTTP probes."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
import time
import uuid
from urllib.request import build_opener, ProxyHandler, Request

cfg = json.loads(Path('/tmp/cube-fault-config.json').read_text())
identity = uuid.uuid4().hex
counter, held, lock = 0, False, threading.Lock()
opener = build_opener(ProxyHandler({}))
log = Path('/tmp/cube-fault-events.jsonl')


def state():
    return {'counter': counter, 'held': held, 'identity': identity,
            'pid': os.getpid(), 'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
            'digest': hashlib.sha256((identity + ':' + str(counter)).encode()).hexdigest()}


def work():
    global counter
    while True:
        with lock:
            paused = held
            if not paused:
                counter += 1
            seq = counter
        if paused:
            time.sleep(0.05)
            continue
        for role, target in cfg['targets'].items():
            started = time.time()
            try:
                url = target['url'] + target.get('path', '/probe') + '?case=' + cfg['case'] + '&target=' + role + '&seq=' + str(seq)
                request = Request(url, headers={'Connection': 'close', **target.get('headers', {})})
                with opener.open(request, timeout=0.8) as response:
                    value = {'ok': response.status == 200, 'status': response.status}
            except Exception as exc:
                value = {'ok': False, 'error': type(exc).__name__}
            with log.open('a') as stream:
                stream.write(json.dumps({'at': started, 'seq': seq, 'target': role, **value}) + '\n')
        Path('/tmp/cube-fault-marker').write_text(str(seq))
        time.sleep(0.35)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        with lock:
            data = json.dumps(state()).encode()
        self.send_response(200)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        global held
        with lock:
            held = self.path == '/hold'
        self.do_GET()

    def log_message(self, *_):
        pass


threading.Thread(target=work, daemon=True).start()
ThreadingHTTPServer(('127.0.0.1', 18182), Handler).serve_forever()
