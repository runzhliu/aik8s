#!/usr/bin/env python3
"""Repeatable multimodal HTTP throughput check with semantic acceptance.

Measures the complete request, including engine preprocessing and variable-length
text output. Repeated media can hit processor caches; this is not a kernel benchmark.
"""
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import statistics
import time
import urllib.error
import urllib.request

import av
import numpy as np
from PIL import Image, ImageDraw


def main():
    root = Path(os.environ['RESULTS_DIR'])
    root.mkdir(parents=True, exist_ok=True)
    assert not (root / 'summary.json').exists(), 'Use a fresh attempt'
    base, model = os.environ['BASE_URL'].rstrip('/'), os.environ['MODEL']
    variant = os.environ.get('FIXTURE_VARIANT', 'plain')
    assert variant in ('plain', 'bordered')
    def picture(size, color, name):
        image = Image.new('RGB', (size, size), color)
        if variant == 'bordered':
            draw = ImageDraw.Draw(image)
            draw.rectangle((0, 0, size-1, size-1), outline='white', width=size//64)
            draw.rectangle((size*15//32, size*15//32, size*17//32, size*17//32), fill='black')
        image.save(root/name)
    for size in (512, 1024):
        picture(size, (255, 0, 0), f'red-{size}.png')
    picture(512, (0, 0, 255), 'blue-512.png')
    video = root / 'red-green-blue-16frames.mp4'
    with av.open(str(video), 'w') as output:
        stream = output.add_stream('mpeg4', rate=4)
        stream.width = stream.height = 256
        stream.pix_fmt = 'yuv420p'
        for i in range(16):
            array = np.empty((256, 256, 3), dtype=np.uint8)
            array[:] = [(255, 0, 0), (0, 255, 0), (0, 0, 255)][min(i // 6, 2)]
            for packet in stream.encode(av.VideoFrame.from_ndarray(array, format='rgb24')):
                output.mux(packet)
        for packet in stream.encode():
            output.mux(packet)

    def part(filename, kind='image'):
        mime = 'image/png' if kind == 'image' else 'video/mp4'
        value = 'data:' + mime + ';base64,' + base64.b64encode((root / filename).read_bytes()).decode()
        return {'type': kind + '_url', kind + '_url': {'url': value}}

    fixtures = [{'file': p.name, 'bytes': p.stat().st_size,
                 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
                for p in root.iterdir() if p.suffix in ('.png', '.mp4')]
    cases = [
        ('image-512', [part('red-512.png')], [1, 4], ['红']),
        ('image-1024', [part('red-1024.png')], [1, 4], ['红']),
        ('two-images-512', [part('red-512.png'), part('blue-512.png')], [1, 4], ['红', '蓝']),
        ('video-16frames', [part(video.name, 'video')], [1, 2], ['红', '绿', '蓝']),
    ]
    rows = []
    for name, media, concurrencies, expected in cases:
        prompt = ('按出现顺序，用中文列出视频背景的三种颜色。' if name.startswith('video')
                  else ('按图片顺序，只用中文列出每张图片的背景颜色。' if variant == 'plain'
                        else '按图片顺序，列出每张图片面积最大的颜色。只用中文回答。'))
        payload = {'model': model, 'messages': [{'role': 'user', 'content':
                   [{'type': 'text', 'text': prompt}] + media}], 'temperature': 0,
                   'max_tokens': 64, 'chat_template_kwargs': {'thinking_mode': 'disabled'}}
        (root / f'{name}-request.json').write_text(json.dumps(payload, ensure_ascii=False))

        def request(_):
            started = time.monotonic()
            try:
                req = urllib.request.Request(base + '/v1/chat/completions',
                    data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
                with urllib.request.urlopen(req, timeout=180) as response:
                    body = json.load(response)
                text = body['choices'][0]['message'].get('content') or ''
                positions = [text.find(color) for color in expected]
                ok = all(p >= 0 for p in positions) and positions == sorted(positions)
                return {'status': 'PASS' if ok else 'FAIL', 'elapsed_s': time.monotonic()-started,
                        'response': body}
            except Exception as exc:
                return {'status': 'FAIL', 'elapsed_s': time.monotonic()-started, 'error': str(exc)}

        for concurrency in concurrencies:
            warmup = request(0)
            (root / f'{name}-c{concurrency}-warmup.json').write_text(json.dumps(warmup, ensure_ascii=False))
            if warmup['status'] != 'PASS':
                rows.append({'case': name, 'concurrency': concurrency, 'status': 'WARMUP_FAILED'})
                continue
            for repeat in range(1, 4):
                if (root.parent / 'PAUSE').exists():
                    raise RuntimeError('Paused')
                start = time.monotonic()
                with ThreadPoolExecutor(max_workers=concurrency) as pool:
                    responses = list(pool.map(request, range(16)))
                elapsed = time.monotonic()-start
                passed = sum(r['status'] == 'PASS' for r in responses)
                output_tokens = sum(r.get('response', {}).get('usage', {}).get('completion_tokens', 0)
                                    for r in responses)
                row = {'case': name, 'concurrency': concurrency, 'repeat': repeat,
                       'requests': 16, 'passed': passed, 'status': 'PASS' if passed == 16 else 'FAIL',
                       'duration_s': elapsed, 'request_throughput': 16/elapsed,
                       'total_output_tokens': output_tokens, 'output_throughput': output_tokens/elapsed,
                       'median_e2el_ms': statistics.median(r['elapsed_s'] for r in responses)*1000}
                rows.append(row)
                (root / f'{name}-c{concurrency}-r{repeat}.json').write_text(
                    json.dumps({'summary': row, 'responses': responses}, ensure_ascii=False))
                print(json.dumps(row), flush=True)
                (root / 'progress.json').write_text(json.dumps(rows, indent=2))
    summary = {'model': model, 'fixture_variant': variant, 'status': 'PASS' if len(rows) == 24 and all(
        r['status'] == 'PASS' for r in rows) else 'CHECK_FAILURES', 'rounds': rows, 'fixtures': fixtures,
        'scope': 'Repeated media, variable output length, engine-default preprocessing/cache; 16 source video frames do not imply equal sampled frames or visual tokens.'}
    (root / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps({'status': summary['status'], 'rounds': len(rows)}), flush=True)


if __name__ == '__main__':
    main()
