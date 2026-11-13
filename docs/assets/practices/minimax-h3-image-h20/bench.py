#!/usr/bin/env python3
"""Bounded H3 Image functional and load cases; raw outcomes kept per request."""
import base64,concurrent.futures,datetime,io,json,os,pathlib,statistics,threading,time,urllib.error,urllib.request,uuid
from PIL import Image
ROOT=pathlib.Path(os.environ['OUT_DIR']);FIX=pathlib.Path(os.environ['FIXTURE_DIR']);BASE=os.environ.get('BASE_URL','http://127.0.0.1:8000');MODEL=os.environ['MODEL_ID']; DEADLINE=float(os.environ['RUN_DEADLINE_EPOCH'])
OUT=ROOT/'results';OUT.mkdir(parents=True,exist_ok=True);lock=threading.Lock();records=[]
cases=json.loads((FIX/'cases.json').read_text());byid={c['id']:c for c in cases}
def stamp():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def status(stage,**kw):
 data={'stage':stage,'updated_at':stamp(),**kw};tmp=ROOT/'progress.tmp';tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n');tmp.replace(ROOT/'progress.json');print('PROGRESS',json.dumps(data,ensure_ascii=False),flush=True)
def multipart(fields,files):
 boundary='----aik8s-'+uuid.uuid4().hex;out=bytearray()
 for k,v in fields.items():out+=f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
 for filename in files:
  b=(FIX/filename).read_bytes();out+=f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{filename}"\r\nContent-Type: image/png\r\n\r\n'.encode()+b+b'\r\n'
 out+=f'--{boundary}--\r\n'.encode();return bytes(out),'multipart/form-data; boundary='+boundary

def request(case,size,seed,group,index):
 request_id=f'{group}-{index:03d}';folder=OUT/request_id;folder.mkdir(exist_ok=False)
 body={'model':MODEL,'prompt':case['prompt'],'size':size,'seed':seed,'response_format':'b64_json'}
 images=case.get('images',[])
 if images:
  payload,ct=multipart(body,images);endpoint='/v1/images/edits'
 else:payload=json.dumps(body,ensure_ascii=False).encode();ct='application/json';endpoint='/v1/images/generations'
 (folder/'request.json').write_text(json.dumps({'endpoint':endpoint,'body':body,'images':images},ensure_ascii=False,indent=2)+'\n')
 info={'id':request_id,'case':case['id'],'endpoint':endpoint,'size':size,'seed':seed,'submitted_at':stamp(),'success':False};start=time.monotonic()
 try:
  req=urllib.request.Request(BASE+endpoint,data=payload,headers={'Content-Type':ct},method='POST')
  with urllib.request.urlopen(req,timeout=min(360,max(1,DEADLINE-time.time()))) as r:raw=r.read();info['http_status']=r.status
  info['http_done_monotonic']=time.monotonic();info['http_elapsed_s']=round(info['http_done_monotonic']-start,4);response=json.loads(raw)
  data=response.get('data') or [];b64=data[0].get('b64_json') if data and isinstance(data[0],dict) else None
  if not isinstance(b64,str):raise ValueError('no data[0].b64_json')
  output=base64.b64decode(b64,validate=True);dec=time.monotonic();im=Image.open(io.BytesIO(output));actual=im.size;im.load();info['decode_s']=round(time.monotonic()-dec,4);info['actual_size']=list(actual);info['format']=im.format;info['output_bytes']=len(output)
  if actual!=tuple(map(int,size.split('x'))):raise ValueError('unexpected image dimensions')
  (folder/'output.png').write_bytes(output); (folder/'response-metadata.json').write_text(json.dumps({**response,'data':[dict(x,b64_json='<saved to output.png>') if 'b64_json' in x else x for x in data]},ensure_ascii=False,indent=2)+'\n');info['success']=True
 except urllib.error.HTTPError as e:
  info['http_status']=e.code;info['error']='HTTPError';(folder/'error.txt').write_text(e.read(32768).decode('utf-8','replace'))
 except Exception as e:info['error']=type(e).__name__+': '+str(e)[:500]
 info.setdefault('http_done_monotonic',time.monotonic());info.setdefault('http_elapsed_s',round(info['http_done_monotonic']-start,4));info['finished_at']=stamp();(folder/'result.json').write_text(json.dumps(info,ensure_ascii=False,indent=2)+'\n')
 with lock:
  records.append(info)
  with (ROOT/'requests.jsonl').open('a') as f:f.write(json.dumps(info,ensure_ascii=False)+'\n')
 return info

def batch(group,case,size,concurrency,count,phase='benchmark',roundno=0):
 if time.time()>=DEADLINE:status('deadline',group=group);return None
 status(phase,group=group,concurrency=concurrency,planned=count,round=roundno)
 start=time.monotonic()
 with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
  results=list(pool.map(lambda i:request(case,size,[42,1234,2026][i%3],group,i),range(count)))
 duration=max((x['http_done_monotonic'] for x in results),default=time.monotonic())-start;ok=[x['http_elapsed_s'] for x in results if x['success']];ok.sort()
 summary={'group':group,'phase':phase,'case':case['id'],'size':size,'concurrency':concurrency,'planned':count,'completed':len(results),'success':len(ok),'failed':len(results)-len(ok),'wall_s':round(duration,4),'images_per_second':round(len(ok)/duration,5) if duration else None,'p50_s':statistics.median(ok) if ok else None,'p95_s':ok[max(0,__import__('math').ceil(len(ok)*0.95)-1)] if ok else None,'max_s':max(ok) if ok else None}
 with (ROOT/'groups.jsonl').open('a') as f:f.write(json.dumps(summary)+'\n')
 print('GROUP',json.dumps(summary),flush=True);return summary

def main():
 status('smoke_t2i');t2=batch('smoke-t2i',byid['product'],'2048x2048',1,1,'smoke')
 if not t2 or t2['success']!=1:
  status('basic_t2i_failed',reason='No valid decoded baseline image; performance skipped');return 2
 edit=batch('smoke-edit',byid['edit-recolor'],'2048x2048',1,1,'smoke');edit_ok=bool(edit and edit['success']==1)
 for case in cases:
  if case['task']=='t2i':batch('visual-'+case['id'],case,'2048x2048',1,3,'visual')
  elif edit_ok:batch('visual-'+case['id'],case,'2048x2048',1,len(case['seeds']),'visual')
 # Same workload and generation area throughout each concurrency comparison.
 for size,key,concs in [('2048x2048','square',[1,2,4,8]),('2720x1536','wide',[1,4]),('4096x4096','4k',[1,2])]:
  for task,case in [('t2i',byid['product']),('edit',byid['edit-recolor'])]:
   if task=='edit' and not edit_ok:continue
   if task=='edit' and size=='2048x2048':selected=[1,2,4]
   else:selected=concs
   warm=batch(f'warm-{key}-{task}',case,size,1,3,'warmup')
   if not warm or warm['success']<1:
    status('stage_skipped',reason='warmup failed',size=size,task=task);continue
   for c in selected:
    for r in range(1,4):
     count=6 if size=='4096x4096' else 12
     summary=batch(f'perf-{key}-{task}-c{c}-r{r}',case,size,c,count,'benchmark',r)
     if summary is None:status('deadline');return 3
     if summary['success']==0:
      status('stage_stopped',reason='zero successful requests in a round; retain failures',size=size,task=task,concurrency=c);break
 if edit_ok:
  for cid in ['edit-two-order','edit-4-reference-protocol']:
   case=byid[cid];warm=batch('warm-'+cid,case,'2048x2048',1,3,'warmup')
   if not warm or not warm['success']:continue
   for r in range(1,4):
    if not batch(f'perf-{cid}-c1-r{r}',case,'2048x2048',1,6,'benchmark',r):return 3
 success=sum(bool(x['success']) for x in records);status('complete',total=len(records),success=success,failed=len(records)-success,edit_supported=edit_ok)
 return 0 if edit_ok and success==len(records) else 4
if __name__=='__main__':raise SystemExit(main())
