#!/usr/bin/env python3
"""Synthetic regressions for HTTP 200 errors, missing terminators and empty TTFT."""
import asyncio
import http.server
import importlib.util
import json
import os
from pathlib import Path
import threading
import time
from types import SimpleNamespace
import aiohttp

ROOT=Path(__file__).resolve().parent
OUT=Path(os.environ.get('FIXTURE_OUTPUT','/outputs/protocol-fixture'))
OUT.mkdir(parents=True,exist_ok=True)
os.environ['QWEN_BENCH_RAW_DIR']=str(OUT/'raw')
os.environ['QWEN_BENCH_FIXTURE_ONLY']='1'
spec=importlib.util.spec_from_file_location('strict',ROOT/'strict_bench.py')
strict=importlib.util.module_from_spec(spec);spec.loader.exec_module(strict)
class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_POST(self):
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        mode=body['prompt'];n=body['max_tokens']
        self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Connection','close');self.end_headers()
        def send(data):
            self.wfile.write(('data: '+(data if isinstance(data,str) else json.dumps(data))+'\n\n').encode());self.wfile.flush()
        try:
            if mode=='empty-first':
                send({'choices':[{'text':''}]});time.sleep(.08)
            send({'choices':[{'text':'x'}]});time.sleep(.002)
            if mode=='error-after-content':send({'error':{'message':'synthetic EngineCore error'}});return
            send({'choices':[{'text':'y'}]})
            if mode!='missing-usage':send({'choices':[],'usage':{'prompt_tokens':4,'completion_tokens':n-1 if mode=='short-output' else n}})
            if mode=='error-after-usage':send({'error':{'message':'synthetic trailing error'}})
            if mode!='missing-done':send('[DONE]')
        except (BrokenPipeError,ConnectionResetError):pass
server=http.server.ThreadingHTTPServer(('127.0.0.1',18109),Handler)
threading.Thread(target=server.serve_forever,daemon=True).start()
async def main():
    rows=[]
    async with aiohttp.ClientSession() as session:
        for mode in ['valid','empty-first','missing-done','missing-usage','error-after-content','error-after-usage','short-output']:
            r=SimpleNamespace(model_name='qwen38-a95b-fp8',model='qwen38-a95b-fp8',prompt=mode,
                output_len=8,logprobs=None,api_url='http://127.0.0.1:18109/v1/completions',prompt_len=4,
                ignore_eos=True,extra_body={},extra_headers={},request_id=mode)
            output=await strict.strict_request(r,session)
            expected=mode in ['valid','empty-first']
            assert output.success==expected,(mode,output)
            if mode=='empty-first':assert output.ttft>=.07,output.ttft
            rows.append({'mode':mode,'success':output.success,'expected':expected,'ttft':output.ttft,'error':output.error})
    # Also exercise the actual pinned bench CLI against this synthetic server.
    import subprocess,sys
    from unattended import command
    args=SimpleNamespace(base_url='http://127.0.0.1:18109',model='qwen38-a95b-fp8',
        tokenizer=os.environ['MODEL_PATH'],engine='vllm')
    case={'input_tokens':4,'output_tokens':8,'num_prompts':2,'concurrency':1,'repeat':1,'id':'protocol-check'}
    where=OUT/'native-cli';where.mkdir(exist_ok=True)
    subprocess.run(command(args,case,where),check=True,timeout=120,
        env={**os.environ,'QWEN_BENCH_RAW_DIR':str(where/'raw')})
    result=json.loads((where/'result.json').read_text());assert result['completed']==2
    strict.POOL.shutdown(wait=True)
    for future in strict.WRITES:future.result()
    report={'status':'PASS','fixture_only':True,'cases':rows}
    (OUT/'validation.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
try:asyncio.run(main())
finally:server.shutdown()
