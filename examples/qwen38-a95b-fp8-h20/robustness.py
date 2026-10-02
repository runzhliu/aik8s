#!/usr/bin/env python3
"""Isolated error/stop checks. Run outside timed performance measurements."""
import json,os,urllib.request,urllib.error
BASE=os.getenv('BASE_URL','http://127.0.0.1:30000/v1').rstrip('/')
MODEL=os.getenv('MODEL','qwen38-a95b-fp8')
results=[]

def req(path,payload=None,raw=None):
 body=raw if raw is not None else json.dumps(payload).encode() if payload is not None else None
 q=urllib.request.Request(BASE+path,data=body,headers={'Content-Type':'application/json','Authorization':'Bearer EMPTY'})
 try:
  with urllib.request.urlopen(q,timeout=300) as r:status=r.status;text=r.read().decode()
 except urllib.error.HTTPError as e:status=e.code;text=e.read().decode()
 results.append({'path':path,'payload':payload,'status':status,'response':text})
 return status,text

for path,payload,raw in [('/chat/completions',{'model':MODEL},None),('/chat/completions',None,b'{'),('/chat/completions',{'model':'nonexistent-qwen-validation-model','messages':[{'role':'user','content':'hello'}]},None)]:
 status,_=req(path,payload,raw)
 assert 400<=status<500,results[-1]

p={'model':MODEL,'prompt':'The sequence of integers from one to ten is: 1, 2,','max_tokens':32,'temperature':0,'seed':123}
status,body=req('/completions',p);assert status==200
baseline=json.loads(body)['choices'][0]['text'];assert len(baseline)>=3
stop=baseline[:min(8,len(baseline))]
status,body=req('/completions',{**p,'stop':[stop]});assert status==200
x=json.loads(body);assert x['choices'][0]['finish_reason']=='stop' and stop not in x['choices'][0]['text']
status,body=req('/completions',{**p,'max_tokens':1,'ignore_eos':True});assert status==200
x=json.loads(body);assert x['usage']['completion_tokens']==1 and x['choices'][0]['finish_reason']=='length'
status,body=req('/chat/completions',{'model':MODEL,'messages':[{'role':'user','content':'计算 47 加 55，给出答案。'}],'max_tokens':2048,'temperature':0})
assert status==200 and '102' in (json.loads(body)['choices'][0]['message'].get('content') or '')
print(json.dumps({'status':'PASS','cases':results},ensure_ascii=False,indent=2))
