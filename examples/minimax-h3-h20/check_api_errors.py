#!/usr/bin/env python3
"""Verify invalid requests reach a clear failure; retains raw API responses."""
import argparse
import copy
import json
from pathlib import Path
import time
import urllib.error
from benchmark import request, sglang_payload, vllm_fields, multipart

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--engine',required=True,choices=['sglang','vllm-omni'])
p.add_argument('--base-url',default='http://127.0.0.1:8000')
p.add_argument('--output',type=Path,required=True)
a=p.parse_args()
base=json.loads(Path(__file__).with_name('cases.json').read_text())[0]
bad=[]
c=copy.deepcopy(base);c['seconds']=99;bad.append(('duration-exceeds-limit',c))
c=copy.deepcopy(base);c['prompt']='';bad.append(('empty-prompt',c))
c=copy.deepcopy(base);c.update(task='fl2va',conditions=[dict(type='image',role='keyframe',frame_index=0,uri='data:image/png;base64,bm90LWFuLWltYWdl')]);bad.append(('invalid-image-bytes',c))
c=copy.deepcopy(base);c.update(task='ref2va',conditions=[]);bad.append(('partition-or-missing-reference',c))
results=[]
for name,case in bad:
    row={'case':name,'status':'FAIL'}
    try:
        if a.engine=='sglang':
            with request(a.base_url+'/v1/videos',sglang_payload(case),120) as r:body=json.load(r)
            row['submission']=body
            job=body.get('id')
            if job:
                end=time.monotonic()+120
                while time.monotonic()<end:
                    with request(a.base_url+'/v1/videos/'+job,timeout=30) as r:body=json.load(r)
                    if body.get('status') in ('failed','completed','cancelled'):break
                    time.sleep(1)
                row['terminal']=body
                if body.get('status')=='failed':row['status']='PASS'
        else:
            data,content_type=multipart(vllm_fields(case))
            with request(a.base_url+'/v1/videos/sync',data,120,content_type) as r:
                row['unexpected_http_status']=r.status
    except urllib.error.HTTPError as exc:
        row.update(http_status=exc.code,response_body=exc.read(65536).decode(errors='replace'))
        if exc.code in (400,413,422):row['status']='PASS'
    except Exception as exc:row['error']=str(exc)
    results.append(row)
    print(json.dumps(row),flush=True)
    if row['status']!='PASS':break
a.output.write_text(json.dumps(dict(engine=a.engine,results=results,
                                    recovery='requires subsequent valid generation'),indent=2)+'\n')
raise SystemExit(int(any(x['status']!='PASS' for x in results)))
