"""State intentionally held only in RAM, used to distinguish full and disk restore."""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import uuid

nonce = uuid.uuid4().hex
counter = 41


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        global counter
        if self.path == '/increment':
            counter += 1
        body = json.dumps({'nonce': nonce, 'counter': counter, 'pid': os.getpid(),
                           'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}).encode()
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


HTTPServer(('127.0.0.1', 8088), Handler).serve_forever()
