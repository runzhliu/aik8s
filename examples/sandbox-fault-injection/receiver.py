"""Controlled HTTP receiver and evidence viewer, for an isolated test network only."""
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
import time
from urllib.parse import urlsplit, parse_qs

ROLE = os.environ.get('ROLE', 'allow')
events = []
records = []
counts = Counter()
lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def send(self, value, kind='application/json'):
        data = value if isinstance(value, bytes) else json.dumps(value).encode()
        self.send_response(200)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlsplit(self.path)
        if url.path == '/probe':
            case = parse_qs(url.query).get('case', ['unknown'])[0]
            if not case.replace('-', '').replace('_', '').isalnum() or len(case) > 100:
                self.send_error(400)
                return
            with lock:
                counts[case] += 1
                events.append({'at': time.time(), 'case': case, 'role': ROLE})
                del events[:-20000]
            return self.send({'role': ROLE})
        if url.path == '/events':
            with lock:
                return self.send({'role': ROLE, 'events': list(events), 'counts': dict(counts)})
        if url.path == '/state':
            with lock:
                return self.send({'records': list(records)})
        if url.path == '/metrics':
            with lock:
                lines = ['# TYPE sandbox_fault_receiver_requests_total counter']
                lines += ['sandbox_fault_receiver_requests_total{case="' + k + '",role="' + ROLE + '"} ' + str(v) for k, v in counts.items()]
                lines += ['# TYPE sandbox_fault_case_phase gauge']
                latest = {r['case']: r for r in records if 'case' in r}
                lines += ['sandbox_fault_case_phase{case="' + k + '"} ' + str(v.get('phase_value', 3)) for k, v in latest.items()]
            return self.send(('\n'.join(lines) + '\n').encode(), 'text/plain; version=0.0.4')
        if url.path == '/':
            return self.send(Path('/app/index.html').read_bytes(), 'text/html; charset=utf-8')
        self.send_error(404)

    def do_POST(self):
        if self.path != '/record':
            self.send_error(404)
            return
        size = int(self.headers.get('Content-Length', '0'))
        if size > 65536:
            self.send_error(413)
            return
        row = json.loads(self.rfile.read(size))
        with lock:
            records.append(row)
            if 'case' in row:
                counts.setdefault(row['case'], 0)
        self.send({'accepted': True})

    def log_message(self, *_):
        pass


ThreadingHTTPServer(('0.0.0.0', 8080), Handler).serve_forever()
