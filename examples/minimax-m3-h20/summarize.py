#!/usr/bin/env python3
"""Export allowlisted public metrics from two complete baseline campaigns."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import statistics

from validate_result import validate

METRICS = ['duration', 'request_throughput', 'output_throughput', 'total_token_throughput']
METRICS += [f'{p}_{metric}_ms' for metric in ['ttft', 'tpot', 'itl', 'e2el']
            for p in ['mean', 'p50', 'p95', 'p99']]


def summarize(directories):
    cases = [c for c in csv.DictReader((Path(__file__).parent/'cases.csv').open()) if c['stage']=='baseline']
    all_rows, aggregates = [], []
    for engine, directory in directories.items():
        for c in cases:
            group = []
            for repeat in range(1, int(c['repeats'])+1):
                p = directory/'baseline'/f"{engine}__{c['case_id']}__r{repeat}.json"
                validate(p, int(c['num_prompts']), int(c['output_tokens']))
                raw = json.loads(p.read_text())
                assert raw['engine']==engine and raw['case_id']==c['case_id']
                assert int(raw['max_concurrency'])==int(c['concurrency'])
                assert all(n==int(c['input_tokens']) for n in raw['input_lens'])
                assert raw['total_input_tokens']==int(c['input_tokens'])*int(c['num_prompts'])
                row = {'engine': engine, 'case_id': c['case_id'], 'repeat': repeat,
                       'input_tokens': int(c['input_tokens']), 'output_tokens': int(c['output_tokens']),
                       'concurrency': int(c['concurrency']), 'completed': raw['completed'],
                       'failed': raw.get('failed', 0), 'total_output_tokens': raw['total_output_tokens'],
                       'source_sha256': hashlib.sha256(p.read_bytes()).hexdigest(),
                       **{k: raw[k] for k in METRICS}}
                group.append(row)
                all_rows.append(row)
            aggregates.append({'engine': engine, 'case_id': c['case_id'],
                'input_tokens': int(c['input_tokens']), 'output_tokens': int(c['output_tokens']),
                'concurrency': int(c['concurrency']), 'rounds': len(group),
                'completed': sum(r['completed'] for r in group),
                'metrics': {k: {'median': statistics.median(r[k] for r in group),
                               'min': min(r[k] for r in group), 'max': max(r[k] for r in group)}
                            for k in METRICS}})
    assert len(all_rows)==66
    return {'status':'PASS', 'model':'MiniMax-M3', 'precision':'BF16', 'hardware':'8x NVIDIA H20-3e',
            'context_window':32768, 'max_running_requests':32, 'tensor_parallel_size':8,
            'counted_rounds':66, 'counted_requests':sum(r['completed'] for r in all_rows),
            'statistics':'Each metric: median and range across three rounds. Round percentiles are not pooled percentiles.',
            'scope':'Fixed-length synthetic text via completions; excludes warmup, functional tests, multimodal tests and failed attempts.',
            'rows':all_rows, 'aggregates':aggregates}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--sglang',type=Path,required=True)
    p.add_argument('--vllm',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args = p.parse_args()
    data = summarize({'sglang':args.sglang,'vllm':args.vllm})
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:data[k] for k in ['status','counted_rounds','counted_requests']}))


if __name__=='__main__':
    main()
