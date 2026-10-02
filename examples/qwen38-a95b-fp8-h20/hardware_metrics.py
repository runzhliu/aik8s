#!/usr/bin/env python3
"""Read sysfs IB counters; data counters use 4-octet units, not raw bytes."""
from http.server import BaseHTTPRequestHandler,HTTPServer
import os
from pathlib import Path
import time

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        if self.path!='/metrics':self.send_error(404);return
        rows=[f'qwen38_hardware_sample_seconds {time.time()}']
        for p in Path('/sys/class/infiniband').glob('mlx5_bond_*/ports/1/counters'):
            for source,name,multiplier in [('port_xmit_data','rdma_transmit_bytes',4),('port_rcv_data','rdma_receive_bytes',4),('port_xmit_wait','rdma_transmit_wait_ticks',1)]:
                try:value=int((p/source).read_text())*multiplier
                except (OSError,ValueError):continue
                label=f'node_alias="rank-{os.environ["NODE_RANK"]}",hca="{p.parents[2].name}"'
                rows.append(f'qwen38_{name}_total{{{label}}} {value}')
        body=('\n'.join(rows)+'\n').encode();self.send_response(200);self.send_header('Content-Type','text/plain; version=0.0.4');self.end_headers();self.wfile.write(body)

if __name__=='__main__':HTTPServer(('0.0.0.0',19195),Handler).serve_forever()
