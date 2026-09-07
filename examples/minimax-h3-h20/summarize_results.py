#!/usr/bin/env python3
"""Summarize retained H3 client evidence without publishing internal identifiers.

Uses completed result JSON and original summary.json; incomplete batches remain
explicitly incomplete. Warmups never enter formal latency/throughput statistics.
"""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import statistics


def summarize(root):
    groups = []
    exclusions = {}
    for path in root.rglob('timing-exclusions.json'):
        note = json.loads(path.read_text())
        suffix = '/'.join(Path(note['excluded_result']).parts[-3:])
        exclusions[suffix] = note['reason']
    for directory in sorted({p.parent for p in root.rglob('*.json')
                             if p.name == 'warmup.json' or p.name.startswith('r0-c')}):
        if not re.search(r'-c\d+$', directory.parent.name):
            # UI and API recovery evidence is retained outside the named matrix.
            continue
        records = []
        for path in sorted(directory.glob('*.json')):
            if path.name.endswith('.request.json'):
                continue
            row = json.loads(path.read_text())
            if not isinstance(row, dict) or not isinstance(row.get('case'), dict):
                continue
            if row.get('status') not in ('PASS', 'FAIL'):
                continue
            case = row['case']
            video = next((s for s in row.get('media', {}).get('streams', [])
                          if s.get('codec_type') == 'video'), {})
            frames = row.get('frames') or int(video.get('nb_read_frames', 0))
            video_duration = frames / 24 if frames else None
            expected = math.ceil((case['seconds'] * 24 - 5) / 17) * 17 + 5
            excluded_reason = exclusions.get('/'.join(path.parts[-3:]))
            records.append(dict(sample=path.stem, run_id=directory.name, warmup=path.stem == 'warmup',
                status=row['status'], case=case['id'], engine=row['engine'],
                requested_seconds=case['seconds'], steps=case['steps'], seed=case['seed'],
                started_at=row['started_at'], e2e_s=row.get('e2e_s'),
                frames=frames, expected_frames=expected,
                frame_contract_pass=frames == expected if frames else False,
                video_duration_s=video_duration, container_duration_s=row.get('duration_s'),
                rtf_video=row['e2e_s'] / video_duration if video_duration and row.get('e2e_s') else None,
                file_bytes=row.get('file_bytes'), file_sha256=row.get('file_sha256'),
                http_status=row.get('http_status'), excluded=bool(excluded_reason),
                exclusion_reason=excluded_reason))
        if not records:
            continue
        summary_path = directory / 'summary.json'
        original = json.loads(summary_path.read_text()) if summary_path.exists() else {}
        formal = [r for r in records if not r['warmup']]
        passed = [r for r in formal if r['status'] == 'PASS' and r['frame_contract_pass'] and not r['excluded']]
        group = dict(engine=records[0]['engine'], case=records[0]['case'],
                     run_id=directory.name, configuration=directory.parent.name,
                     complete=bool(original), formal_samples=len(formal),
                     formal_pass=len(passed), records=records)
        if original:
            for key in ('batch_wall_s', 'throughput_scope'):
                if key in original:
                    group[key] = original[key]
            excluded_batches = {int(re.match(r'r(\d+)-c', r['sample'])[1])
                                for r in formal if r['excluded']}
            group['qualified_batch_wall_s'] = [v for i, v in enumerate(original.get('batch_wall_s', []))
                                                if i not in excluded_batches]
            if group['qualified_batch_wall_s']:
                group['validated_videos_per_hour'] = len(passed) * 3600 / sum(group['qualified_batch_wall_s'])
        if passed:
            values = [r['e2e_s'] for r in passed]
            group.update(e2e_median_s=statistics.median(values), e2e_min_s=min(values),
                         e2e_max_s=max(values), rtf_video_median=statistics.median(
                             r['rtf_video'] for r in passed))
        groups.append(group)
    configurations = {}
    for group in groups:
        canonical = group['configuration'].replace('-replacement', '')
        key = group['engine'], canonical
        row = configurations.setdefault(key, dict(engine=group['engine'], configuration=canonical,
            case=group['case'], complete=True, records=[], source_runs=[], qualified_batch_wall_s=[]))
        row['complete'] = row['complete'] and group['complete']
        row['source_runs'].append(group['run_id'])
        row['records'].extend(group['records'])
        row['qualified_batch_wall_s'].extend(group.get('qualified_batch_wall_s', []))
    for row in configurations.values():
        formal = [r for r in row['records'] if not r['warmup'] and not r['excluded']]
        passed = [r for r in formal if r['status'] == 'PASS' and r['frame_contract_pass']]
        concurrency = int(re.search(r'-c(\d+)$', row['configuration'])[1])
        expected = concurrency * (1 if row['case'] == 't2va-zh-5s' else 3)
        row.update(concurrency=concurrency, expected_formal_samples=expected,
                   qualified_formal_samples=len(formal), qualified_pass=len(passed),
                   failed_warmups=sum(r['warmup'] and r['status'] != 'PASS' for r in row['records']),
                   excluded_samples=sum(r['excluded'] for r in row['records']))
        row['status'] = ('PASS' if len(passed) == expected and len(formal) == expected
                         else 'INCOMPLETE_OR_FAILED') if row['complete'] else 'RUNNING'
        if passed:
            values = [r['e2e_s'] for r in passed]
            row.update(e2e_values_s=values, e2e_median_s=statistics.median(values),
                       e2e_min_s=min(values), e2e_max_s=max(values),
                       rtf_video_median=statistics.median(r['rtf_video'] for r in passed))
            wall = sum(row['qualified_batch_wall_s'])
            if wall:
                row.update(validated_videos_per_hour=len(passed) * 3600 / wall,
                           decoded_video_seconds_per_wall_second=sum(r['frames']/24 for r in passed) / wall)
    return dict(generated_at=datetime.now(timezone.utc).isoformat(),
                workload=dict(gpus=4, gpu_model='NVIDIA H20-3e', width=1344, height=768,
                              fps=24, sampling_points=50, precision='original BF16/FP32'),
                notes=['Warmups excluded from formal statistics.',
                       'RTF uses actual decoded video frames / 24 fps.',
                       'Throughput includes client media validation.',
                       'Missing summary.json means the batch is not yet final.'],
                groups=groups, configurations=list(configurations.values()))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    result = summarize(a.source)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(dict(groups=len(result['groups']), output=str(a.output))))
