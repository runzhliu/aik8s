#!/usr/bin/env python3
"""Reconstruct one measured prompt; print its JSON request without sending it."""
import argparse
import hashlib
import json
from pathlib import Path

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--results',type=Path,default=Path('results.json'))
p.add_argument('--phase',required=True)
p.add_argument('--family',type=int,choices=range(8),default=0)
p.add_argument('--index',type=int,default=0)
p.add_argument('--model',default='qwen38-aibrix-lab')
a=p.parse_args()
data=json.loads(a.results.read_text())
phase=next((s for s in data['phases'] if s['phase']==a.phase),None)
if phase is None:p.error('Unknown measured phase')
cfg=phase['config']
family=cfg.get('family_map',{}).get(str(a.family),a.family)
salt_key=cfg.get('prefix_salt',a.phase)
salt=''.join(hashlib.sha256(f'{salt_key}:{family}:{j}'.encode()).hexdigest() for j in range(4))
sentence='The service tracks request latency, token throughput, cache utilization, and healthy replicas. '
prompt=salt+'\nDocument '+str(family)+'\n'+sentence*cfg['repeat']+f'\nQuestion {a.index:06d}: Explain the operational tradeoffs in detail.'
print(json.dumps({'model':a.model,'prompt':prompt,'temperature':0,'max_tokens':cfg['output'],'ignore_eos':True,'stream':True,'stream_options':{'include_usage':True}},ensure_ascii=False))
