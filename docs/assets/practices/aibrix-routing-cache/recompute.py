#!/usr/bin/env python3
"""Recompute the article's client metrics offline. Python standard library only.

Usage: python3 recompute.py requests.jsonl.gz
This reads a saved dataset; it does not contact a cluster or send model requests.
"""
import collections
import gzip
import json
import math
import sys
from pathlib import Path

def quantile(values, q):
    ordered=sorted(values)
    if not ordered:return None
    position=(len(ordered)-1)*q
    lo=math.floor(position);hi=math.ceil(position)
    return ordered[lo]+(ordered[hi]-ordered[lo])*(position-lo)

path=Path(sys.argv[1] if len(sys.argv)>1 else 'requests.jsonl.gz')
opener=gzip.open if path.suffix=='.gz' else open
groups=collections.defaultdict(list)
with opener(path,'rt') as f:
    for line in f:
        row=json.loads(line);groups[row['phase']].append(row)
print('phase,requests,complete,good,ttft_p95_s,tpot_p95_ms,replica_a,replica_b')
for phase,rows in sorted(groups.items()):
    ok=[r for r in rows if r['result']=='ok']
    assert all(r['http_status']==200 and r['output_tokens']==128 for r in ok)
    good=sum(r['ttft']<=2 and r['tpot']<=.15 and r['e2e']<=30 for r in ok)
    assert good==sum(r['good'] for r in rows)
    counts=collections.Counter(r['replica'] for r in rows)
    ttft=quantile([r['ttft'] for r in ok],.95)
    tpot=quantile([r['tpot'] for r in ok],.95)
    print(f'{phase},{len(rows)},{len(ok)},{good},{ttft:.6f},{tpot*1000:.6f},{counts["L20-A"]},{counts["L20-B"]}')
