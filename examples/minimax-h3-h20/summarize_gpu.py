#!/usr/bin/env python3
"""Match 1 Hz NVML samples to completed client request windows.

Publishes anonymous per-Pod GPU indices, never UUIDs, node names or paths.
Per-request windows may overlap at concurrency >1; their energy is not additive.
"""
import argparse
import csv
from datetime import datetime
import json
from pathlib import Path
import statistics


def timestamp(value):
    return datetime.fromisoformat(value).timestamp()


def summarize(stage):
    points = []
    for path in sorted((stage / 'logs').glob('gpu-*.csv')):
        with path.open() as f:
            for row in csv.DictReader(f):
                try:
                    points.append((timestamp(row['utc']), int(row['index']),
                                   float(row['memory.used']), float(row['power.draw']),
                                   float(row['utilization.gpu'])))
                except (ValueError, TypeError, KeyError):
                    continue
    points.sort()
    requests = []
    for path in sorted((stage / 'client').rglob('*.json')):
        if path.name.endswith('.request.json'):
            continue
        row = json.loads(path.read_text())
        if not isinstance(row, dict) or not isinstance(row.get('case'), dict):
            continue
        if not row.get('download_completed_at'):
            continue
        start, end = timestamp(row['started_at']), timestamp(row['download_completed_at'])
        matched = [p for p in points if start <= p[0] <= end]
        devices = []
        for index in sorted({p[1] for p in matched}):
            samples = [p for p in matched if p[1] == index]
            gaps = [b[0] - a[0] for a, b in zip(samples, samples[1:])]
            devices.append(dict(gpu_index=index, samples=len(samples),
                peak_memory_mib=max(p[2] for p in samples),
                mean_power_w=statistics.mean(p[3] for p in samples),
                peak_power_w=max(p[3] for p in samples),
                mean_utilization_percent=statistics.mean(p[4] for p in samples),
                covered_seconds=samples[-1][0]-samples[0][0],
                max_sampling_gap_seconds=max(gaps) if gaps else None))
        requests.append(dict(engine=row['engine'], case=row['case']['id'],
            configuration=path.parent.parent.name, run_id=path.parent.name, sample=path.stem,
            warmup=path.stem == 'warmup', status=row['status'], e2e_s=row.get('e2e_s'),
            server_reported_peak_memory_mb=row.get('last_job_status', {}).get('peak_memory_mb'),
            server_reported_inference_seconds=row.get('last_job_status', {}).get('inference_time_s'),
            nvml_devices=devices))
    return dict(scope='NVML samples between client start and download completion; queued windows may include other requests',
                units=dict(memory='MiB', power='W', utilization='percent'), requests=requests)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--stage', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    result = summarize(a.stage)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(dict(requests=len(result['requests']), output=str(a.output))))
