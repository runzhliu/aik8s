#!/usr/bin/env python3
"""Export durable completed-request samples. Histogram P95 is a rolling estimate."""
import argparse
from collections import defaultdict
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import math
from pathlib import Path
import threading
import time

BUCKETS=[.001,.002,.005,.01,.02,.03,.05,.08,.1,.2,.5,1,2,3,5,10,15,30,60,120,240,480,900,1800]
FIELDS={'ttft':'ttft_s','tpot':'request_tpot_s','e2e':'transport_e2e_s'}
class Metrics:
    def __init__(self):self.rows={};self.parse_errors=0;self.last=0;self.lock=threading.Lock()
    def add(self,r):
        key=(r['engine'],r['case'],r['purpose'])
        with self.lock:
            x=self.rows.setdefault(key,{'ok':0,'error':0,'tokens':0,**{k:[] for k in FIELDS}})
            x['ok' if r['success'] else 'error']+=1
            if r['success']:
                x['tokens']+=r['usage']['completion_tokens']
                for k,field in FIELDS.items():
                    val=r.get(field)
                    if val is not None and math.isfinite(val) and val>=0:x[k].append(val)
            self.last=max(self.last,r['finished_at'])
    def render(self):
        lines=['# TYPE qwen38_exporter_heartbeat_seconds gauge',f'qwen38_exporter_heartbeat_seconds {time.time()}',
               f'qwen38_export_parse_errors_total {self.parse_errors}',f'qwen38_last_completed_request_seconds {self.last}']
        with self.lock:
            for key,x in self.rows.items():
                label=','.join(k+'='+json.dumps(v) for k,v in zip(['engine','case','purpose'],key))
                for result in ['ok','error']:lines.append(f'qwen38_client_requests_total{{{label},result="{result}"}} {x[result]}')
                lines.append(f'qwen38_client_output_tokens_total{{{label}}} {x["tokens"]}')
                for metric in FIELDS:
                    vals=x[metric];name='qwen38_client_'+metric+'_seconds'
                    for b in BUCKETS:lines.append(f'{name}_bucket{{{label},le="{b}"}} {sum(v<=b for v in vals)}')
                    lines.extend([f'{name}_bucket{{{label},le="+Inf"}} {len(vals)}',
                                  f'{name}_count{{{label}}} {len(vals)}',f'{name}_sum{{{label}}} {sum(vals)}'])
        return '\n'.join(lines)+'\n'


def serve(samples,port):
    m=Metrics()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            if self.path!='/metrics':self.send_error(404);return
            data=m.render().encode();self.send_response(200);self.send_header('Content-Type','text/plain; version=0.0.4');self.end_headers();self.wfile.write(data)
    server=ThreadingHTTPServer(('0.0.0.0',port),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    offset=0;path=Path(samples)
    while True:
        if path.exists():
            with path.open() as f:
                f.seek(offset)
                while True:
                    pos=f.tell();line=f.readline()
                    if not line:break
                    if not line.endswith('\n'):f.seek(pos);break
                    try:m.add(json.loads(line))
                    except (ValueError,TypeError,KeyError):m.parse_errors+=1
                offset=f.tell()
        time.sleep(1)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--samples',required=True);p.add_argument('--port',type=int,default=9095)
    args=p.parse_args();serve(args.samples,args.port)
