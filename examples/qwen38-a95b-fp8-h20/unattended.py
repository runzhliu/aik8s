#!/usr/bin/env python3
"""Bounded remote benchmark suite. No GPU scheduling and no result overwrites.

Run inside the pinned vLLM client image. State/raw results belong on hostPath.
Independent capability failures never suppress valid text performance results.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import urllib.request
from validate_benchmark_result import validate

HERE = Path(__file__).resolve().parent
TERMINAL = {'PASS', 'FAILED', 'SKIPPED', 'NOT_EXECUTED'}


def save(path, data):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2)); tmp.replace(path)


def terminate(proc):
    if proc.poll() is not None: return
    os.killpg(proc.pid, signal.SIGTERM)
    try: proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL); proc.wait()


def run_child(argv, output, timeout, env=None, health_check=None):
    with Path(output).open('x') as log:
        p = subprocess.Popen(argv, env=env, stdout=log, stderr=subprocess.STDOUT,
                             start_new_session=True)
        try:
            end=time.monotonic()+max(.01,timeout)
            while p.poll() is None:
                if time.monotonic()>=end:raise subprocess.TimeoutExpired(argv,timeout)
                if health_check is not None and not health_check():terminate(p);return 125
                try:return p.wait(timeout=min(5,max(.01,end-time.monotonic())))
                except subprocess.TimeoutExpired:pass
            return p.returncode
        except subprocess.TimeoutExpired: terminate(p); return 124
        except BaseException: terminate(p); raise


def cases(path, stages, context):
    rows = []
    with Path(path).open() as f:
        for row in csv.DictReader(f):
            if row['stage'] not in stages: continue
            for key in ['input_tokens', 'output_tokens', 'concurrency', 'num_prompts', 'repeats']:
                row[key] = int(row[key])
                if row[key] <= 0: raise ValueError('case values must be positive')
            for repeat in range(1, row['repeats'] + 1):
                rows.append({**row, 'repeat': repeat, 'id': row['case_id']+'-r'+str(repeat),
                    'status': 'SKIPPED' if row['input_tokens']+row['output_tokens']>context else 'NOT_EXECUTED',
                    'reason': 'context limit' if row['input_tokens']+row['output_tokens']>context else 'pending'})
    if not rows: raise ValueError('no selected cases')
    return rows


def should_stop_stage(rows, stage, consecutive=3):
    done = [r for r in rows if r['stage'] == stage and r['status'] in {'PASS','FAILED'}]
    return len(done) >= consecutive and all(r['status']=='FAILED' for r in done[-consecutive:])


def healthy(base, model):
    try:
        with urllib.request.urlopen(base+'/v1/models', timeout=10) as r:
            return model in [v['id'] for v in json.load(r).get('data', [])]
    except Exception: return False


def command(args, row, where, warmup=False):
    count = min(row['concurrency'], row['num_prompts']) if warmup else row['num_prompts']
    return [sys.executable, str(HERE/'strict_bench.py'), 'bench', 'serve', '--backend','openai',
        '--base-url',args.base_url,'--endpoint','/v1/completions','--model',args.model,
        '--served-model-name',args.model,'--tokenizer',args.tokenizer,'--trust-remote-code',
        '--dataset-name','random','--random-input-len',str(row['input_tokens']),
        '--random-output-len',str(row['output_tokens']),'--random-range-ratio','0',
        '--num-prompts',str(count),'--max-concurrency',str(row['concurrency']),
        '--request-rate','inf','--temperature','0','--ignore-eos','--num-warmups','0',
        '--seed',str(20260903+row['repeat']),'--disable-tqdm','--save-result','--save-detailed',
        '--percentile-metrics','ttft,tpot,itl,e2el','--metric-percentiles','50,95,99',
        '--result-dir',str(where),'--result-filename','result.json',
        '--request-id-prefix',args.engine+'-'+row['id']+'-']


def suite(args):
    args.base_url = args.base_url.rstrip('/')
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=False)  # fresh attempts only, never overwrite failures
    deadline = min(time.time()+args.suite_seconds, args.deadline_epoch)
    rows = cases(args.cases, args.stages.split(','), args.context)
    state = {'engine':args.engine, 'status':'RUNNING', 'started_at':time.time(),
             'deadline_epoch':deadline, 'rows':rows, 'capabilities':{},
             'client_sha256':hashlib.sha256((HERE/'strict_bench.py').read_bytes()).hexdigest()}
    def update():
        state['updated_at']=time.time()
        state['counts']={s:sum(r['status']==s for r in rows) for s in TERMINAL|{'RUNNING'}}
        save(out/'suite-status.json',state)
    update()
    try:
        env={**os.environ,'BASE_URL':args.base_url+'/v1','MODEL':args.model,
             'TRACE_FILE':str(out/'functional-trace.jsonl'), 'RESULT_FILE':str(out/'functional.json'),
             'TIMEOUT':'180','MAX_TOKENS':'4096'}
        rc=run_child([sys.executable,str(HERE/'smoke.py')],out/'functional.log',
                     min(1200,deadline-time.time()),env)
        functional=json.loads((out/'functional.json').read_text()) if (out/'functional.json').exists() else {}
        state['capabilities']=functional
        if rc==124 or not functional.get('basic_gate_passed'):
            state['reason']='basic text/model/complete SSE gate failed'
            for row in rows:
                if row['status']=='NOT_EXECUTED':row.update(status='SKIPPED',reason=state['reason'])
            return
        stage_start={}
        for row in rows:
            if row['status']=='SKIPPED':continue
            stage=row['stage']; stage_start.setdefault(stage,time.time())
            remaining=min(deadline-time.time(),args.stage_seconds-(time.time()-stage_start[stage]))
            if remaining<=0:
                row['reason']='suite deadline' if time.time()>=deadline else 'stage deadline';continue
            if should_stop_stage(rows,stage):row['reason']='three consecutive failed rounds in this stage';continue
            # Saturation is dependent on the previously measured concurrency, not an arbitrary skip.
            if stage=='saturation':
                prerequisite='short-128-128-c'+str(row['concurrency']//2)
                previous=[r for r in rows if r['case_id']==prerequisite]
                if not previous or not all(r['status']=='PASS' for r in previous):
                    row.update(status='SKIPPED',reason='lower-concurrency prerequisite failed/unmeasured');continue
            if not healthy(args.base_url,args.model):
                row['reason']='endpoint unavailable';state['reason']=row['reason'];break
            where=out/stage/row['id'];where.mkdir(parents=True)
            row.update(status='RUNNING',reason='',started_at=time.time());update()
            env={**os.environ,'QWEN_BENCH_ENGINE':args.engine,'QWEN_BENCH_CASE':row['case_id'],
                 'QWEN_BENCH_SAMPLE_FILE':str(Path(args.samples)), 'QWEN_BENCH_RAW_DIR':str(where/'warmup/raw'),
                 'QWEN_BENCH_PURPOSE':'warmup','QWEN_BENCH_ID_PREFIX':args.engine+'-'+row['id']+'-'}
            warm=where/'warmup';warm.mkdir()
            argv=command(args,row,warm,True);save(warm/'command.json',argv)
            rc=run_child(argv,warm/'client.log',min(args.round_seconds,remaining),env)
            try:
                if rc:raise ValueError('warmup process rc='+str(rc))
                validate(warm/'result.json',min(row['concurrency'],row['num_prompts']),row['output_tokens'])
            except Exception as exc:
                row.update(status='FAILED',reason='warmup: '+str(exc),formal_executed=False,finished_at=time.time());update();continue
            formal=where/'measurement';formal.mkdir()
            env.update(QWEN_BENCH_RAW_DIR=str(formal/'raw'),QWEN_BENCH_PURPOSE='measurement')
            argv=command(args,row,formal);save(formal/'command.json',argv)
            remaining=min(deadline-time.time(), args.stage_seconds-(time.time()-stage_start[stage]),args.round_seconds)
            if remaining<=0:
                row.update(status='NOT_EXECUTED',reason='deadline after warmup',formal_executed=False);update();continue
            rc=run_child(argv,formal/'client.log',remaining,env)
            row.update(formal_executed=True,returncode=rc,finished_at=time.time())
            try:
                result=json.loads((formal/'result.json').read_text())
                row.update(requests=row['num_prompts'],completed=result.get('completed',0))
                if rc:raise ValueError('benchmark process rc='+str(rc))
                validate(formal/'result.json',row['num_prompts'],row['output_tokens'])
                row['status']='PASS'
            except Exception as exc:row.update(status='FAILED',reason=str(exc))
            update()
    finally:
        for row in rows:
            if row['status']=='RUNNING':row.update(status='FAILED',reason='interrupted',finished_at=time.time())
        state.update(status='BENCHMARK_FINISHED' if all(r['status']=='PASS' for r in rows) else 'PARTIAL_RESULTS',
                     finished_at=time.time(),report_status='PENDING',grafana_status='PENDING')
        update()


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--engine',required=True,choices=['sglang','vllm'])
    p.add_argument('--base-url',required=True);p.add_argument('--output',required=True)
    p.add_argument('--model',default='qwen38-a95b-fp8')
    p.add_argument('--tokenizer',default='/models-nvme/Qwen3.8-2.4T-A95B-FP8/v1')
    p.add_argument('--cases',default=str(HERE/'cases.csv'));p.add_argument('--context',type=int,default=32768)
    p.add_argument('--stages',default='smoke,baseline,prefill,decode,saturation,long')
    p.add_argument('--suite-seconds',type=int,default=10800);p.add_argument('--stage-seconds',type=int,default=3600)
    p.add_argument('--round-seconds',type=int,default=1200);p.add_argument('--deadline-epoch',type=float,required=True)
    p.add_argument('--samples',required=True)
    def interrupted(signum,frame):raise KeyboardInterrupt('suite interrupted')
    signal.signal(signal.SIGTERM,interrupted)
    suite(p.parse_args())
