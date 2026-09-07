#!/usr/bin/env python3
"""Small light-theme H3 acceptance UI backed by the same benchmark adapter."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import threading
import uuid
from benchmark import run_one

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--engine',required=True,choices=['sglang','vllm-omni'])
p.add_argument('--base-url',default='http://127.0.0.1:8000')
p.add_argument('--output',type=Path,default=Path('/outputs/ui'))
p.add_argument('--port',type=int,default=8080)
p.add_argument('--variant',choices=['fl2va','ref2va'],default='fl2va')
a=p.parse_args();a.timeout=7200;a.poll_interval=1
a.output.mkdir(parents=True,exist_ok=True)
jobs={};lock=threading.Lock();pool=ThreadPoolExecutor(max_workers=1)
cases=json.loads(Path(__file__).with_name('cases.json').read_text())

def work(key,case):
    with lock:jobs[key]['status']='generating'
    result=run_one(a,case,a.output/(key+'.mp4'))
    with lock:jobs[key].update(status='completed' if result['status']=='PASS' else 'failed',result=result)

class Handler(BaseHTTPRequestHandler):
    def json_response(self,status,data):
        body=json.dumps(data,ensure_ascii=False).encode();self.send_response(status)
        self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)))
        self.end_headers();self.wfile.write(body)
    def do_GET(self):
        if self.path=='/':
            body=Path(__file__).with_name('studio.html').read_bytes();self.send_response(200)
            self.send_header('Content-Type','text/html; charset=utf-8');self.end_headers();self.wfile.write(body);return
        if self.path=='/api/info':
            self.json_response(200,dict(engine=a.engine,variant=a.variant));return
        match=re.fullmatch(r'/api/jobs/([0-9a-f]{32})',self.path)
        if match:
            with lock:data=jobs.get(match[1])
            self.json_response(200 if data else 404,data or {'error':'unknown job'});return
        match=re.fullmatch(r'/media/([0-9a-f]{32})\.mp4',self.path)
        if match:
            path=a.output/(match[1]+'.mp4')
            if path.is_file():
                self.send_response(200);self.send_header('Content-Type','video/mp4')
                self.send_header('Content-Length',str(path.stat().st_size));self.end_headers()
                with path.open('rb') as f:
                    while chunk:=f.read(1024*1024):self.wfile.write(chunk)
                return
        self.json_response(404,{'error':'not found'})
    def do_POST(self):
        if self.path!='/api/jobs':self.json_response(404,{'error':'not found'});return
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=32000:raise ValueError('invalid request size')
            data=json.loads(self.rfile.read(length));prompt=str(data['prompt']).strip()
            if not 1<=len(prompt)<=7000:raise ValueError('描述应为 1–7000 个字符')
            seconds=int(data.get('seconds',5))
            if seconds not in (5,10,15):raise ValueError('请选择 5、10 或 15 秒')
            selected='t2va-5s' if a.variant=='fl2va' else 'ref2va-image'
            case=dict(next(c for c in cases if c['id']==selected));case.update(prompt=prompt,seconds=seconds,seed=int(data.get('seed',1101)))
            key=uuid.uuid4().hex
            with lock:jobs[key]={'id':key,'status':'queued','case':case}
            pool.submit(work,key,case);self.json_response(202,jobs[key])
        except (KeyError,ValueError,TypeError) as exc:self.json_response(400,{'error':str(exc)})

ThreadingHTTPServer(('0.0.0.0',a.port),Handler).serve_forever()
