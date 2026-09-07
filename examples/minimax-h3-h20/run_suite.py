#!/usr/bin/env python3
"""Run the approved H3 matrix sequentially; stop after the first failed gate."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--engine',required=True,choices=['sglang','vllm-omni'])
p.add_argument('--stage',required=True,choices=['fl2va','ref2va'])
p.add_argument('--output',type=Path,required=True)
p.add_argument('--base-url',default='http://127.0.0.1:8000')
p.add_argument('--resume-after',help='last successfully completed step; retain previous output')
a=p.parse_args()
a.output.mkdir(parents=True,exist_ok=True)
if a.stage=='fl2va':
    matrix=[('t2va-5s',1,3),('t2va-zh-5s',1,1),('t2va-10s',1,3),
            ('t2va-15s',1,3),('t2va-5s',2,3),('t2va-5s',4,3),
            ('fl2va-first',1,3),('fl2va-last',1,3),('fl2va-both',1,3)]
else:
    matrix=[('ref2va-'+name,1,3) for name in
            ['image','images','video-silent','video-sound','image-audio','mixed']]
state=dict(engine=a.engine,stage=a.stage,status='RUNNING',steps=[],
           started_at=datetime.now(timezone.utc).isoformat())
state_path=a.output/'suite-state.json'
if state_path.exists():
    if not a.resume_after:raise SystemExit('existing suite state; use a fresh output or explicit resume')
    old=json.loads(state_path.read_text());state['previous_state']=old
    state_path.with_name('suite-state-before-resume-'+str(time.time_ns())+'.json').write_text(json.dumps(old,indent=2)+'\n')
resume=a.resume_after is None
for case,concurrency,repeats in matrix:
    key=f'{case}-c{concurrency}'
    if not resume:
        if key==a.resume_after:resume=True
        continue
    step=dict(key=key,started_at=datetime.now(timezone.utc).isoformat())
    state['current_step']=key
    state_path.write_text(json.dumps(state,indent=2)+'\n')
    command=[sys.executable,str(Path(__file__).with_name('benchmark.py')),
             '--engine',a.engine,'--base-url',a.base_url,'--case',case,
             '--concurrency',str(concurrency),'--repeats',str(repeats),
             '--output',str(a.output/key),'--execute']
    with (a.output/(key+'-'+str(time.time_ns())+'.log')).open('x') as log:
        result=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT)
    step.update(returncode=result.returncode,finished_at=datetime.now(timezone.utc).isoformat())
    state['steps'].append(step)
    print(json.dumps(step),flush=True)
    if result.returncode:
        state['status']='FAIL';break
else:
    state['status']='PASS' if resume else 'INVALID_RESUME'
if state['status']=='PASS' and a.stage=='fl2va':
    # These functional requests run after the timing matrix and use a separate
    # directory, so they cannot enter the formal performance statistics.
    checks=[('api-errors',[sys.executable,str(Path(__file__).with_name('check_api_errors.py')),
            '--engine',a.engine,'--base-url',a.base_url,
            '--output',str(a.output.parent/('api-errors-fl2va-'+str(time.time_ns())+'.json'))]),
            ('api-recovery',[sys.executable,str(Path(__file__).with_name('benchmark.py')),
            '--engine',a.engine,'--base-url',a.base_url,'--case','t2va-5s',
            '--concurrency','1','--repeats','1','--skip-warmup',
            '--output',str(a.output.parent/'api-recovery'),'--execute'])]
    for key,command in checks:
        state.update(status='RUNNING',current_step=key)
        state_path.write_text(json.dumps(state,indent=2)+'\n')
        step=dict(key=key,started_at=datetime.now(timezone.utc).isoformat())
        with (a.output/(key+'-'+str(time.time_ns())+'.log')).open('x') as log:
            result=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT)
        step.update(returncode=result.returncode,finished_at=datetime.now(timezone.utc).isoformat())
        state['steps'].append(step);print(json.dumps(step),flush=True)
        if result.returncode:
            state['status']='FAIL';break
    else:
        state['status']='PASS'
state['finished_at']=datetime.now(timezone.utc).isoformat()
state_path.write_text(json.dumps(state,indent=2)+'\n')
raise SystemExit(0 if state['status']=='PASS' else 1)
