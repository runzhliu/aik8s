"""Disposable guest workload: one identity, monotonic counter, HTTP and streams."""
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import struct
import threading
import time
import uuid

identity, counter = uuid.uuid4().hex, 0
lock = threading.Lock()


def state():
    with lock:
        return {'identity': identity, 'counter': counter, 'pid': os.getpid()}


def work():
    global counter
    while True:
        with lock:
            counter += 1
        time.sleep(0.5)


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def do_GET(self):
        if self.path.startswith('/ws'):
            key = self.headers.get('Sec-WebSocket-Key', '')
            accept = base64.b64encode(hashlib.sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
            self.send_response(101)
            self.send_header('Upgrade', 'websocket')
            self.send_header('Connection', 'Upgrade')
            self.send_header('Sec-WebSocket-Accept', accept)
            self.end_headers()
            try:
                while True:
                    data = json.dumps(state()).encode()
                    header = bytes([0x81, len(data)]) if len(data) < 126 else bytes([0x81, 126]) + struct.pack('!H', len(data))
                    self.wfile.write(header + data)
                    self.wfile.flush()
                    time.sleep(0.5)
            except (OSError, ConnectionError):
                return
        elif self.path.startswith('/stream'):
            self.send_response(200)
            self.send_header('Content-Type', 'application/x-ndjson')
            self.send_header('Transfer-Encoding', 'chunked')
            self.end_headers()
            try:
                while True:
                    data = (json.dumps(state()) + '\n').encode()
                    self.wfile.write(('%x\r\n' % len(data)).encode() + data + b'\r\n')
                    self.wfile.flush()
                    time.sleep(0.5)
            except (OSError, ConnectionError):
                return
        else:
            data = json.dumps(state()).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    def log_message(self, *_):
        pass


threading.Thread(target=work, daemon=True).start()
ThreadingHTTPServer(('0.0.0.0', 18080), Handler).serve_forever()
