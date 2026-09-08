#!/usr/bin/env python3
"""Bounded mixed text/image soak; preserves every response and arrival timestamp."""
import base64
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import statistics
import threading
import time
import urllib.request


def main():
    root = Path(os.environ['RESULTS_DIR'])
    root.mkdir(parents=True, exist_ok=True)
    assert not (root / 'summary.json').exists(), 'Use a fresh attempt'
    seconds = int(os.environ.get('SOAK_SECONDS', '3600'))
    interval = float(os.environ.get('SOAK_INTERVAL', '2'))
    assert seconds > 0 and interval > 0
    model, base = os.environ['MODEL'], os.environ['BASE_URL'].rstrip('/')
    image_path = Path(os.environ['IMAGE_FIXTURE'])
    image = 'data:image/png;base64,' + base64.b64encode(image_path.read_bytes()).decode()
    lock = threading.Lock()
    rows = []
    start = time.monotonic()

    def request(index, scheduled):
        kind = 'image' if index % 5 == 0 else 'text'
        content = ([{'type': 'text', 'text': '读取图中Q1、Q2、Q3的数值，只列出三个数值。'},
                    {'type': 'image_url', 'image_url': {'url': image}}]
                   if kind == 'image' else '计算6乘7，只给数字。')
        payload = {'model': model, 'messages': [{'role': 'user', 'content': content}],
                   'temperature': 0, 'max_tokens': 64,
                   'chat_template_kwargs': {'thinking_mode': 'disabled'}}
        begin = time.monotonic()
        row = {'index': index, 'kind': kind, 'at': time.time(),
               'scheduled_offset_s': scheduled-start, 'queue_delay_s': begin-scheduled}
        try:
            with urllib.request.urlopen(urllib.request.Request(base+'/v1/chat/completions',
                    data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'}), timeout=120) as response:
                body = json.load(response)
            text = body['choices'][0]['message'].get('content') or ''
            ok = all(str(n) in text for n in [120, 90, 150]) if kind == 'image' else text.strip() == '42'
            row.update(status='PASS' if ok else 'FAIL', response=body)
        except Exception as exc:
            row.update(status='FAIL', error=str(exc))
        row['elapsed_s'] = time.monotonic()-begin
        with lock:
            rows.append(row)
            with (root/'requests.jsonl').open('a') as output:
                output.write(json.dumps(row, ensure_ascii=False)+'\n')
            if len(rows) % 30 == 0:
                progress = {'elapsed_s': time.monotonic()-start, 'completed': len(rows),
                            'failed': sum(r['status'] != 'PASS' for r in rows)}
                (root/'progress.json').write_text(json.dumps(progress))
                print(json.dumps(progress), flush=True)

    with ThreadPoolExecutor(max_workers=4) as pool:
        index = 0
        pending = []
        while time.monotonic()-start < seconds:
            if (root.parent/'PAUSE').exists():
                raise RuntimeError('Paused')
            scheduled = start+index*interval
            delay = scheduled-time.monotonic()
            if delay > 0:
                time.sleep(min(delay, 1))
                continue
            # Bound outstanding work if latency or connectivity deteriorates.
            pending = [f for f in pending if not f.done()]
            if len(pending) >= 8:
                raise RuntimeError('More than eight outstanding requests; stop overload')
            pending.append(pool.submit(request, index, scheduled))
            index += 1
    duration = time.monotonic()-start
    failed = sum(r['status'] != 'PASS' for r in rows)
    summary = {'model': model, 'status': 'PASS' if failed == 0 and duration >= seconds else 'CHECK_FAILURES',
               'duration_s': duration, 'target_seconds': seconds, 'scheduled_request_interval_s': interval,
               'completed': len(rows), 'failed': failed,
               'median_e2el_ms': statistics.median(r['elapsed_s'] for r in rows)*1000,
               'max_e2el_ms': max(r['elapsed_s'] for r in rows)*1000,
               'scope': '80% text / 20% repeated image; 0.5 req/s default, up to four client workers; not saturation throughput.'}
    (root/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    main()
