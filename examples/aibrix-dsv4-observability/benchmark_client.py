import argparse, asyncio, collections, json, math, os, random, statistics, time, uuid
from pathlib import Path
import aiohttp
from prometheus_client import REGISTRY, start_http_server
from prometheus_client.core import GaugeMetricFamily, CounterMetricFamily, HistogramMetricFamily

ROOT=Path(os.environ.get('RESULT_DIR','/results')); ROOT.mkdir(parents=True,exist_ok=True)
MODEL=os.environ.get('MODEL','dsv4-flash-aibrix-perf')
GATEWAY=os.environ['GATEWAY_URL'].rstrip('/')
DIRECT=os.environ.get('SINGLE_POD_URL','http://dsv4-flash-aibrix-perf:8000')
BUCKETS=[.001,.002,.003,.004,.005,.006,.007,.008,.009,.01,.0125,.015,.02,.025,.035,.05,.075,.1,.125,.15,.175,.2,.25,.3,.4,.5,.75,1,2,5,10,20,30,60,120,300,float('inf')]

def append(name,row):
    with (ROOT/name).open('a') as f: f.write(json.dumps(row,ensure_ascii=False)+'\n');f.flush();os.fsync(f.fileno())

def rows():
    out=[]
    for path in ROOT.glob('requests-*.jsonl'):
        for line in path.read_text().splitlines():
            try: out.append(json.loads(line))
            except json.JSONDecodeError: pass
    return out

class Collector:
    def collect(self):
        groups=collections.defaultdict(list)
        for r in rows():groups[(r['phase'],str(r['concurrency']),r['route'],r['workload'])].append(r)
        labels=['phase','concurrency','route','workload']
        completed=CounterMetricFamily('aik8s_benchmark_requests','Completed client requests',labels=labels+['result'])
        tokens=CounterMetricFamily('aik8s_benchmark_output_tokens','Actual completion tokens from usage',labels=labels)
        for key,rs in groups.items():
            for status in ['ok','error']:completed.add_metric(list(key)+[status],sum(r['result']==status for r in rs))
            tokens.add_metric(list(key),sum(r.get('output_tokens',0) for r in rs if r['result']=='ok'))
        yield completed;yield tokens
        for metric,field,helptext in [('ttft','ttft','First nonempty streamed content or reasoning latency'),('tpot','tpot','Per request (last-first content time)/(completion tokens-1)'),('e2e','e2e','Full streaming response latency')]:
            h=HistogramMetricFamily('aik8s_benchmark_'+metric+'_seconds',helptext,labels=labels)
            for key,rs in groups.items():
                values=[r[field] for r in rs if r['result']=='ok' and r.get(field) is not None]
                h.add_metric(list(key),buckets=[('+'+'Inf' if math.isinf(b) else str(b),sum(v<=b for v in values)) for b in BUCKETS],sum_value=sum(values))
            yield h
        for field,helptext in [('elapsed','Measured phase duration'),('output_tokens_per_second','Aggregate generated tokens per second'),('request_rate','Completed requests per second')]:
            g=GaugeMetricFamily('aik8s_benchmark_phase_'+field,helptext,labels=['phase','route','workload','concurrency'])
            for p in ROOT.glob('summary-*.json'):
                s=json.loads(p.read_text())
                g.add_metric([s['phase'],s['route'],s['workload'],str(s['concurrency'])],s[field])
            yield g
        g=GaugeMetricFamily('aik8s_benchmark_phase_active','Currently executing phase',labels=['phase'])
        p=ROOT/'active.json'
        if p.exists():g.add_metric([json.loads(p.read_text())['phase']],1)
        yield g

async def request(session,base,prompt,phase,concurrency,route,workload,max_tokens=128):
    rid=str(uuid.uuid4());start=time.monotonic();first=last=None;usage={};fragments=0
    row=dict(id=rid,phase=phase,concurrency=concurrency,route=route,workload=workload,started_at=time.time(),result='error')
    body={'model':MODEL,'prompt':prompt,'max_tokens':max_tokens,'temperature':0,'ignore_eos':True,'stream':True,'stream_options':{'include_usage':True}}
    headers={'x-request-id':rid}
    if route not in ('direct','default'):headers['routing-strategy']=route
    try:
        async with session.post(base+'/v1/completions',json=body,headers=headers) as resp:
            row['status']=resp.status
            if resp.status!=200:raise RuntimeError((await resp.text())[:500])
            done=False
            async for raw in resp.content:
                line=raw.decode().strip()
                if not line.startswith('data:'):continue
                payload=line[5:].strip()
                if payload=='[DONE]':done=True;break
                data=json.loads(payload)
                if data.get('error'):raise RuntimeError(str(data['error']))
                if data.get('usage'):usage=data['usage']
                for choice in data.get('choices',[]):
                    delta=choice.get('delta') or {}
                    content=choice.get('text') or delta.get('content') or delta.get('reasoning_content') or delta.get('reasoning')
                    if content:
                        now=time.monotonic();first=first or now;last=now;fragments+=1
            if not done or first is None or not usage.get('completion_tokens'):raise RuntimeError('Missing DONE/content/usage')
        n=usage['completion_tokens']
        row.update(result='ok',input_tokens=usage['prompt_tokens'],output_tokens=n,ttft=first-start,tpot=(last-first)/(n-1) if n>1 else None,e2e=time.monotonic()-start,fragments=fragments)
    except Exception as e:row.update(error=str(e),e2e=time.monotonic()-start)
    append('requests-'+phase+'.jsonl',row)
    return row

def quantile(values,q):
    a=sorted(values)
    if not a:return None
    x=(len(a)-1)*q;i=int(x);return a[i]+(a[min(i+1,len(a)-1)]-a[i])*(x-i)

async def runphase(session,phase,c,n,route='least-request',workload='short',base=GATEWAY,out=256):
    if (ROOT/('summary-'+phase+'.json')).exists():print('SKIP completed '+phase,flush=True);return
    start=time.monotonic();wall=time.time();sem=asyncio.Semaphore(c)
    (ROOT/'active.json').write_text(json.dumps({'phase':phase,'start':wall}))
    # Unique leading nonce reduces accidental prefix reuse in short/long workloads.
    async def one(i,request_phase=phase):
        async with sem:
            nonce=uuid.uuid4().hex
            sentence='The service tracks request latency, token throughput, cache utilization, and healthy replicas. '
            if workload=='shared-prefix':prompt=sentence*260+'\nRequest '+nonce+': explain the operational implications.'
            else:prompt='Request '+nonce+'\n'+sentence*(260 if workload=='long' else 30)+'\nContinue with a technical explanation.'
            return await request(session,base,prompt,request_phase,c,route,workload,out)
    warm=await asyncio.gather(*(one(i,'warmup-'+phase) for i in range(c*2)))
    if any(r['result']!='ok' for r in warm):raise RuntimeError('Warmup failed')
    await asyncio.sleep(5)
    start=time.monotonic();wall=time.time()
    print(json.dumps({'event':'start','phase':phase,'concurrency':c,'requests':n,'at':wall}),flush=True)
    counter=0
    async def worker():
        nonlocal counter
        result=[]
        while counter<n or time.monotonic()-start<60:
            counter+=1
            result.append(await one(counter))
            if result[-1]['result']=='error':break
        return result
    groups=await asyncio.gather(*(worker() for _ in range(c)))
    rs=[r for group in groups for r in group];n=len(rs)
    elapsed=time.monotonic()-start;ok=[r for r in rs if r['result']=='ok']
    s=dict(phase=phase,route=route,workload=workload,concurrency=c,requests=n,success=len(ok),errors=n-len(ok),started_at=wall,finished_at=time.time(),elapsed=elapsed,output_tokens_per_second=sum(r['output_tokens'] for r in ok)/elapsed,request_rate=len(ok)/elapsed)
    for field in ['ttft','tpot','e2e','input_tokens','output_tokens']:
        vals=[r[field] for r in ok if r.get(field) is not None]
        s[field]={'p50':quantile(vals,.5),'p95':quantile(vals,.95),'p99':quantile(vals,.99),'min':min(vals) if vals else None,'max':max(vals) if vals else None}
    (ROOT/('summary-'+phase+'.json')).write_text(json.dumps(s,indent=2))
    print(json.dumps(s),flush=True)
    if s['errors']>max(1,n*.05):raise RuntimeError('Error budget exceeded; stop benchmark')
    await asyncio.sleep(15)

async def main(mode):
    timeout=aiohttp.ClientTimeout(total=240,sock_read=120)
    async with aiohttp.ClientSession(timeout=timeout,connector=aiohttp.TCPConnector(limit=80)) as session:
        if mode=='smoke':
            print(json.dumps(await request(session,GATEWAY,'Reply with READY.','smoke',1,'least-request','smoke',8)),flush=True);return
        phases=[('direct-c1',1,8,'direct','short',DIRECT),('gateway-c1',1,8,'least-request','short',GATEWAY),('gateway-c4',4,24,'least-request','short',GATEWAY),('gateway-c16',16,64,'least-request','short',GATEWAY),('gateway-c32',32,96,'least-request','short',GATEWAY),('long-c16',16,48,'least-request','long',GATEWAY),('prefix-random',16,64,'random','shared-prefix',GATEWAY),('prefix-aware',16,64,'prefix-cache','shared-prefix',GATEWAY)]
        for p in phases:await runphase(session,*p)
        (ROOT/'active.json').write_text(json.dumps({'phase':'complete'}))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['serve','smoke','run']);args=p.parse_args()
    if args.mode=='serve':
        REGISTRY.register(Collector());start_http_server(int(os.environ.get('METRICS_PORT','9095')))
        while True:time.sleep(60)
    else:asyncio.run(main(args.mode))
