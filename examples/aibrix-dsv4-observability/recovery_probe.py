import asyncio,importlib.util,json,time
from pathlib import Path
import benchmark_client as b
async def main():
    root=b.ROOT;start=time.monotonic();wall=time.time();phase='eviction-c4';allrows=[]
    root.joinpath('active.json').write_text(json.dumps({'phase':phase,'start':wall}))
    async with b.aiohttp.ClientSession(timeout=b.aiohttp.ClientTimeout(total=120,sock_read=90)) as session:
        async def worker():
            while time.monotonic()-start<600 and not root.joinpath('recovery-stop').exists():
                r=await b.request(session,b.GATEWAY,'Request '+b.uuid.uuid4().hex+'\n'+('The service tracks request latency, token throughput, cache utilization, and healthy replicas. '*30)+'\nContinue with a technical explanation.',phase,4,'least-request','short',256)
                allrows.append(r)
                if sum(x['result']=='error' for x in allrows)>20:return
                await asyncio.sleep(.2)
        await asyncio.gather(*(worker() for _ in range(4)))
    elapsed=time.monotonic()-start;ok=[r for r in allrows if r['result']=='ok']
    s=dict(phase=phase,concurrency=4,route='least-request',workload='short',started_at=wall,finished_at=time.time(),requests=len(allrows),success=len(ok),errors=len(allrows)-len(ok),elapsed=elapsed,output_tokens_per_second=sum(r['output_tokens'] for r in ok)/elapsed,request_rate=len(ok)/elapsed)
    for field in ['ttft','tpot','e2e','input_tokens','output_tokens']:
        a=[r[field] for r in ok if r.get(field) is not None];s[field]={'p50':b.quantile(a,.5),'p95':b.quantile(a,.95),'p99':b.quantile(a,.99),'min':min(a) if a else None,'max':max(a) if a else None}
    root.joinpath('summary-'+phase+'.json').write_text(json.dumps(s,indent=2));print(json.dumps(s),flush=True)
    root.joinpath('active.json').write_text(json.dumps({'phase':'recovery-complete'}))
asyncio.run(main())
