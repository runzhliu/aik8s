from pathlib import Path
import json,os,subprocess,sys,time
from urllib.request import urlopen,Request
import argparse
parser=argparse.ArgumentParser(description='Run one bounded case in an isolated fault-runtime Pod')
parser.add_argument('engine', choices=['microsandbox','boxlite'])
parser.add_argument('fault', choices=['control','sdk','vmm','pod'])
parser.add_argument('--context', required=True)
parser.add_argument('--attempt', required=True, help='Unique identifier; never reuse a previous attempt')
parser.add_argument('--evidence-dir', required=True, type=Path)
args=parser.parse_args()
ROOT=args.evidence_dir.resolve();ROOT.mkdir(parents=True,exist_ok=True)
CTX=args.context
ENGINE,FAULT=args.engine,args.fault
CASE=ENGINE+'-'+FAULT+'-'+args.attempt
NS={'microsandbox':'microsandbox-lab','boxlite':'boxlite-lab'}[ENGINE]
BASE=['kubectl','--context',CTX,'-n',NS]
recv=json.loads(subprocess.run(['kubectl','--context',CTX,'-n','sandbox-fault-lab','get','pods','-l','fault-receiver=true','-o','json'],capture_output=True,text=True,check=True).stdout)['items']
urls={p['metadata']['labels']['role']:'http://'+p['status']['podIP']+':8080' for p in recv if p['status']['phase']=='Running'}
assert set(urls)=={'allow','deny'}
def k(args,timeout=25,check=True,input=None):
 r=subprocess.run(BASE+args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=timeout,input=input)
 if check and r.returncode:raise RuntimeError(r.stderr[-1800:])
 return r

def ex(args,**kwargs):return k(['exec','deploy/fault-runtime','--']+args,**kwargs)
def read(name):return json.loads(ex(['cat','/data/fault-evidence/'+name]).stdout)
def processes(kill=None):
 code=(Path(__file__).parent/'processes.py').read_text()
 return json.loads(k(['exec','-i','deploy/fault-runtime','--','python','-']+([kill] if kill else []),input=code).stdout)
def snapshot():
 return {role:json.load(urlopen('http://127.0.0.1:'+port+'/events',timeout=10)) for role,port in [('allow','18960'),('deny','18961')]}
def count(rows,role,start,end):return sum(x['case']==CASE and start<=x['at']<end for x in rows[role]['events'])
rootmeta=ENGINE+'-'+CASE
if ex(['test','-e','/data/fault-evidence/'+rootmeta+'.json'],check=False).returncode==0:
 raise SystemExit('Attempt already exists; choose a new identifier')
record={'engine':ENGINE,'fault':FAULT,'case':CASE,'started_at':time.time()}
worker=None
try:
 k(['rollout','status','deploy/fault-runtime','--timeout=60s'],timeout=70)
 for port in ['18960','18961']:
  data=json.dumps({'case':CASE,'phase_value':0}).encode();urlopen(Request('http://127.0.0.1:'+port+'/record',data=data,headers={'Content-Type':'application/json'}),timeout=10).read()
 env=['env','ALLOW_URL='+urls['allow'],'DENY_URL='+urls['deny']]
 if FAULT=='control':env+=['POLICY_MODE=unrestricted']
 log=(ROOT/(CASE+'-worker.log')).open('w')
 worker=subprocess.Popen(BASE+['exec','deploy/fault-runtime','--']+env+['python','/app/sdk_worker.py',ENGINE,'start',CASE],stdout=log,stderr=log)
 for _ in range(90):
  try:meta=read(rootmeta+'.json');break
  except Exception:
   if worker.poll() is not None:raise RuntimeError('Worker exited: '+(ROOT/(CASE+'-worker.log')).read_text()[-1800:])
   time.sleep(1)
 else:raise TimeoutError('Guest readiness exceeded 90 seconds')
 record['ready_at']=time.time()
 time.sleep(12)
 record['guest_before']=read(rootmeta+'-guest.json')
 record['processes_before']=processes()
 record['injected_at']=time.time()
 for port in ['18960','18961']:
  data=json.dumps({'case':CASE,'phase_value':1}).encode();urlopen(Request('http://127.0.0.1:'+port+'/record',data=data,headers={'Content-Type':'application/json'}),timeout=10).read()
 if FAULT in ['sdk','vmm']:record['injection']=processes(FAULT)
 elif FAULT=='pod':
  pod=json.loads(k(['get','pods','-l','app=fault-runtime','-o','json']).stdout)['items'][0]
  record['old_pod_uid']=pod['metadata']['uid']
  k(['delete','pod',pod['metadata']['name'],'--wait=true','--timeout=40s'],timeout=50)
  k(['rollout','status','deploy/fault-runtime','--timeout=60s'],timeout=70)
  new=json.loads(k(['get','pods','-l','app=fault-runtime','-o','json']).stdout)['items'][0]
  record['new_pod_uid']=new['metadata']['uid'];assert record['old_pod_uid']!=record['new_pod_uid']
 record['injection_completed_at']=time.time()
 time.sleep(12)
 record['observation_ended_at']=time.time()
 if FAULT=='sdk':
  r=ex(['python','/app/sdk_worker.py',ENGINE,'inspect',CASE],timeout=30,check=False)
  record['reattach_exit_code']=r.returncode
  if r.returncode==0:record['guest_after']=json.loads(r.stdout)
  else:record['reattach_error']=r.stderr[-1000:]
 elif FAULT!='pod':record['guest_after']=read(rootmeta+'-guest.json')
 record['processes_after']=processes()
 receivers=snapshot();(ROOT/(CASE+'-receivers.json')).write_text(json.dumps(receivers,indent=2))
 record['received']={}
 for phase,start,end in [('before',record['ready_at'],record['injected_at']),('after',record['injection_completed_at'],record['observation_ended_at'])]:
  record['received'][phase]={role:count(receivers,role,start,end) for role in ['allow','deny']}
 before=record['received']['before'];assert before['allow']>=4, before
 if FAULT=='control':assert before['deny']>=4, before
 else:assert before['deny']==0, before
 record['status']='measured'
except BaseException as exc:
 record.update(status='interrupted' if isinstance(exc,KeyboardInterrupt) else 'failed',error=repr(exc))
finally:
 # Evidence first. Independent cleanup happens even when assertions or injection fail.
 (ROOT/(CASE+'.json')).write_text(json.dumps(record,indent=2))
 try:
  rows=processes()
  if any(x['is_worker'] for x in rows):processes('sdk')
  r=ex(['python','/app/sdk_worker.py',ENGINE,'cleanup',CASE],timeout=30,check=False)
  record['cleanup_exit_code']=r.returncode
  record['cleanup_message']=(r.stdout+r.stderr)[-700:]
  if any(x['kvm_fds'] for x in processes()):processes('vmm')
  if any(x['is_proxy'] for x in processes()):processes('proxy')
  record['remaining_kvm_processes']=sum(bool(x['kvm_fds']) for x in processes())
 except Exception as exc:record['cleanup_error']=repr(exc)
 if worker:
  try:worker.wait(timeout=10)
  except subprocess.TimeoutExpired:worker.terminate()
 (ROOT/(CASE+'.json')).write_text(json.dumps(record,indent=2))
 public={k:v for k,v in record.items() if k not in ['guest_before','guest_after','processes_before','processes_after','cleanup_message','old_pod_uid','new_pod_uid']}
 print(json.dumps(public,indent=2),flush=True)
raise SystemExit(0 if record['status']=='measured' else 1)
