"""Independent receivers and a stable lab-only SDK bridge. No production use."""
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
import time
from urllib.parse import urlsplit, parse_qs
from urllib.request import Request, urlopen, build_opener, ProxyHandler
from urllib.error import HTTPError

ROLE = os.environ.get('ROLE', 'allow')
API = os.environ.get('CUBE_API', 'http://cube-api.cube-system.svc:3000')
PROXY = os.environ.get('CUBE_PROXY', 'http://cube-proxy.cube-system.svc:80')
events, records, samples = [], [], []
counts, lock = Counter(), threading.RLock()
opener = build_opener(ProxyHandler({}))


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def reply(self, payload, kind='application/json', status=200):
        data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def bridge(self, upstream, path):
        size = int(self.headers.get('Content-Length', '0'))
        data = self.rfile.read(size) if size else None
        headers = {k: v for k, v in self.headers.items()
                   if k.lower() not in ('connection', 'content-length', 'accept-encoding')}
        request = Request(upstream + path, data=data, headers=headers, method=self.command)
        try:
            response = opener.open(request, timeout=8)
        except HTTPError as exc:
            response = exc
        except Exception as exc:
            return self.reply({'bridge_error': type(exc).__name__}, status=502)
        with response:
            return self.reply(response.read(), response.headers.get('Content-Type', 'application/octet-stream'), response.status)

    def route(self):
        path = urlsplit(self.path)
        if self.path.startswith('/cubeapi/'):
            return self.bridge(API, self.path[len('/cubeapi'):])
        host = self.headers.get('Host', '').split(':')[0]
        if host.endswith('.cube.app') and host not in ('allow.cube.app', 'deny.cube.app'):
            return self.bridge(PROXY, self.path)
        if path.path == '/probe' or path.path.startswith('/probe/'):
            params = parse_qs(path.query)
            case = params.get('case', ['unknown'])[0]
            target = params.get('target', [ROLE])[0]
            if len(case) > 100 or not case.replace('-', '').replace('_', '').isalnum():
                return self.reply({}, status=400)
            with lock:
                counts[(case, target)] += 1
                events.append({'at': time.time(), 'case': case, 'role': ROLE,
                               'target': target, 'seq': params.get('seq', [''])[0],
                               'port': self.server.server_port})
                del events[:-100000]
            return self.reply({'role': ROLE, 'target': target})
        if path.path == '/events':
            with lock:
                return self.reply({'role': ROLE, 'events': list(events)})
        if path.path == '/record' and self.command == 'POST':
            size = int(self.headers.get('Content-Length', '0'))
            if size > 131072:
                return self.reply({}, status=413)
            value = json.loads(self.rfile.read(size))
            with lock:
                records.append(value)
                for target in ('allow', 'deny'):
                    counts.setdefault((value['case'], target), 0)
            return self.reply({'accepted': True})
        if path.path == '/sample' and self.command == 'POST':
            value = json.loads(self.rfile.read(int(self.headers.get('Content-Length', '0'))))
            with lock:
                samples.append(value)
                del samples[:-20000]
            return self.reply({'accepted': True})
        if path.path == '/state':
            with lock:
                return self.reply({'records': list(records), 'samples': list(samples)})
        if path.path == '/metrics':
            with lock:
                lines = ['# TYPE cube_fault_receiver_requests_total counter']
                for (case, target), count in counts.items():
                    lines.append(f'cube_fault_receiver_requests_total{{case="{case}",role="{ROLE}",target="{target}"}} {count}')
                latest = {r['case']: r for r in records}
                for case, row in latest.items():
                    lines.append(f'cube_fault_phase{{case="{case}"}} {row.get("phase_value", 3)}')
                if samples:
                    for field in ('api_ok', 'command_ok', 'counter', 'identity_same'):
                        row = samples[-1]
                        lines.append(f'cube_fault_{field}{{case="{row["case"]}"}} {row.get(field, 0)}')
            return self.reply(('\n'.join(lines) + '\n').encode(), 'text/plain; version=0.0.4')
        if path.path == '/':
            return self.reply(Path('/app/index.html').read_bytes(), 'text/html; charset=utf-8')
        return self.reply({}, status=404)

    do_GET = do_POST = do_DELETE = do_PATCH = do_PUT = route

    def log_message(self, *_):
        pass


for port in (80,):
    server = ThreadingHTTPServer(('0.0.0.0', port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
ThreadingHTTPServer(('0.0.0.0', 8080), Handler).serve_forever()
