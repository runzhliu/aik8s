#!/usr/bin/env python3
"""Keep pinned vLLM workloads/statistics; validate and archive complete SSE.

latency retains the CLI's last-generated-content definition. Complete HTTP stream
latency is separately archived as transport_e2e_s; do not conflate the two.
"""
import asyncio
import codecs
import base64
import concurrent.futures
import hashlib
import json
import os
import signal
from pathlib import Path
import time
import threading
import uuid
from vllm.benchmarks.lib import endpoint_request_func as upstream

POOL=concurrent.futures.ThreadPoolExecutor(max_workers=2)
WRITES=[]
WRITE_LOCK=threading.Lock()

def archive(path,record):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x') as f: json.dump(record,f,ensure_ascii=False)
    sample_path=os.getenv('QWEN_BENCH_SAMPLE_FILE')
    if sample_path and record['actual_model_inference']:
        sample={k:record.get(k) for k in ['id','started_at','finished_at','success','error','usage',
                 'ttft_s','token_e2e_s','request_tpot_s','transport_e2e_s','monotonic_start']}
        sample.update(engine=os.environ['QWEN_BENCH_ENGINE'],case=os.environ['QWEN_BENCH_CASE'],
                      purpose=os.environ['QWEN_BENCH_PURPOSE'] if record['bench_request'] else 'protocol_probe')
        with WRITE_LOCK:
            with open(sample_path,'a') as f:f.write(json.dumps(sample,ensure_ascii=False)+'\n')

class SSEDecoder:
    """Incremental UTF-8/event decoder; preserve split multibyte content and fields."""
    def __init__(self):
        self.decoder=codecs.getincrementaldecoder('utf-8')();self.buffer='';self.data=[]
    def add_chunk(self,chunk):
        self.buffer+=self.decoder.decode(chunk);events=[]
        while '\n' in self.buffer:
            line,self.buffer=self.buffer.split('\n',1);line=line.removesuffix('\r')
            if not line:
                if self.data:events.append('\n'.join(self.data));self.data=[]
            elif line.startswith('data:'):
                value=line[5:];self.data.append(value[1:] if value.startswith(' ') else value)
        return events

async def strict_request(request_func_input,session,pbar=None):
    r=request_func_input
    payload={'model':r.model_name or r.model,'prompt':r.prompt,'repetition_penalty':1.0,
             'max_tokens':r.output_len,'logprobs':r.logprobs,'stream':True,
             'stream_options':{'include_usage':True}}
    upstream._update_payload_common(payload,r)
    headers=upstream._get_headers()
    upstream._update_headers_common(headers,r)
    output=upstream.RequestFuncOutput()
    output.prompt_len=r.prompt_len
    start=time.perf_counter();output.start_time=start
    first=last=None;done=False;usage=None;chunks=[];text=[]
    record={'id':r.request_id or str(uuid.uuid4()),'payload':payload,
            'started_at':time.time(),'monotonic_start':start,
            'actual_model_inference':not os.getenv('QWEN_BENCH_FIXTURE_ONLY'),
            'bench_request':bool(r.request_id and r.request_id.startswith(os.getenv('QWEN_BENCH_ID_PREFIX','qwen38-')))}
    try:
        async with session.post(r.api_url,json=payload,headers=headers) as response:
            record['http_status']=response.status
            if response.status!=200:
                record['error_body']=await response.text()
                raise ValueError('HTTP '+str(response.status))
            handler=SSEDecoder()
            async for raw in response.content.iter_any():
                now=time.perf_counter()
                chunks.append({'elapsed_s':now-start,'base64':base64.b64encode(raw).decode()})
                for message in handler.add_chunk(raw):
                    if message.startswith(':'):continue
                    body=message
                    if body=='[DONE]':done=True;continue
                    data=json.loads(body)
                    if data.get('error'):
                        record['sse_error']=data['error']
                        raise ValueError('Error event inside HTTP 200 stream')
                    if data.get('usage'):usage=data['usage']
                    for choice in data.get('choices',[]):
                        content=choice.get('text') or ''
                        if content:
                            stamp=time.perf_counter()
                            if first is None:first=stamp;output.ttft=stamp-start
                            else:output.itl.append(stamp-last)
                            last=stamp;text.append(content)
            record['transport_e2e_s']=time.perf_counter()-start
            if not done or first is None or not usage or not usage.get('completion_tokens'):
                raise ValueError('Missing DONE, nonempty content, or completion usage')
            n=usage['completion_tokens']
            if r.ignore_eos and n!=r.output_len:
                raise ValueError('Fixed output length mismatch')
            output.output_tokens=n
            output.prompt_len=usage['prompt_tokens']
            output.latency=last-start
            output.tpot=(last-first)/(n-1) if n>1 else 0
            output.generated_text=''.join(text)
            output.success=True
    except Exception as exc:
        output.success=False;output.error=type(exc).__name__+': '+str(exc)
    finally:
        record.update(success=output.success,error=output.error,done=done,usage=usage,
                      finished_at=time.time(),
                      ttft_s=output.ttft if first is not None else None,
                      token_e2e_s=last-start if last is not None else None,
                      request_tpot_s=(last-first)/(usage['completion_tokens']-1)
                        if first is not None and usage and usage.get('completion_tokens',0)>1 else None,
                      transport_e2e_s=record.get('transport_e2e_s',time.perf_counter()-start),raw_chunks=chunks)
        directory=Path(os.environ['QWEN_BENCH_RAW_DIR'])
        WRITES.append(POOL.submit(archive,directory/(str(uuid.uuid4())+'.json'),record))
        if pbar:pbar.update(1)
    return output

def install():
    upstream.ASYNC_REQUEST_FUNCS['openai']=strict_request
    upstream.ASYNC_REQUEST_FUNCS['vllm']=strict_request

if __name__=='__main__':
    if not os.getenv('QWEN_BENCH_RAW_DIR'):
        raise SystemExit('QWEN_BENCH_RAW_DIR is required outside the GPU Pod')
    def interrupted(signum,frame):raise KeyboardInterrupt('benchmark phase interrupted')
    signal.signal(signal.SIGTERM,interrupted)
    install()
    from vllm.entrypoints.cli.main import main
    try:main()
    finally:
        POOL.shutdown(wait=True)
        for future in WRITES:future.result()
