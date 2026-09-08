#!/usr/bin/env python3
"""Summarize sampled GPU telemetry within the main-matrix stage, including warmup."""
import argparse
import csv
import io
import json
from pathlib import Path
import statistics


def extract(directory):
    events=[json.loads(line) for line in (directory/'controller.log').read_text().splitlines() if line.startswith('{')]
    start=min(e['heartbeat_at'] for e in events if e['stage']=='baseline')
    end=max(e['heartbeat_at'] for e in events if e['stage']=='COMPLETE')
    samples=[]
    for line in (directory/'gpu-telemetry.jsonl').read_text().splitlines():
        record=json.loads(line)
        if not start<=record['at']<=end or record['returncode']!=0:continue
        gpus=[[float(x.strip()) for x in row] for row in csv.reader(io.StringIO(record['gpu_csv']))]
        assert len(gpus)==8 and all(len(g)==6 for g in gpus)
        samples.append({'elapsed_s':record['at']-start,'max_gpu_memory_mib':max(g[1] for g in gpus),
                        'mean_gpu_util_pct':statistics.mean(g[3] for g in gpus),
                        'sum_gpu_power_w':sum(g[4] for g in gpus),'max_gpu_temperature_c':max(g[5] for g in gpus)})
    assert samples
    return {'matrix_stage_duration_s':end-start,'samples':samples,
            'sampled_max_gpu_memory_mib':max(s['max_gpu_memory_mib'] for s in samples),
            'sampled_max_sum_gpu_power_w':max(s['sum_gpu_power_w'] for s in samples),
            'sampled_max_gpu_temperature_c':max(s['max_gpu_temperature_c'] for s in samples)}


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--sglang',type=Path,required=True);parser.add_argument('--vllm',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    data={'scope':'30-second GPU sampling during complete main matrix, including per-case warmup and client setup; sampled peaks are not continuous maxima or precise energy measurements.',
          'sglang':extract(args.sglang),'vllm':extract(args.vllm)}
    args.output.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    print('Runtime summary exported')
