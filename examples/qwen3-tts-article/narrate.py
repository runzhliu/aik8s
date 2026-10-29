#!/usr/bin/env python3
"""Generate a resumable, sequential WAV narration from a prepared text file."""
import argparse
import array
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.request
import wave


def wav_info(data):
    with wave.open(io.BytesIO(data), 'rb') as w:
        channels, width, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
        if (channels, width, w.getcomptype()) != (1, 2, 'NONE'):
            raise ValueError('Expected mono, 16-bit PCM WAV')
        pcm = w.readframes(w.getnframes())
    samples = array.array('h', pcm)
    if sys.byteorder != 'little':
        samples.byteswap()
    rms = math.sqrt(sum(v*v for v in samples)/max(1, len(samples)))
    duration = len(samples)/rate
    if duration < .5 or rms < 3.28:
        raise ValueError('Audio is too short or effectively silent')
    return samples, rate, duration, rms


def split_text(text, limit):
    result = []
    for paragraph in re.split(r'\n\s*\n', text.strip()):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(paragraph) <= limit:
            result.append(paragraph)
            continue
        current = ''
        for sentence in re.findall(r'.+?[。！？.!?](?:\s|$)?|.+$', paragraph):
            if len(sentence) > limit:
                raise ValueError('A sentence exceeds --chunk-chars; edit the narration first')
            if current and len(current)+len(sentence) > limit:
                result.append(current.strip())
                current = ''
            current += sentence
        if current:
            result.append(current.strip())
    if not result:
        raise ValueError('The input file is empty')
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('input', type=Path)
    p.add_argument('--base-url', default='http://127.0.0.1:8000')
    p.add_argument('--model', default='/models/Qwen3-TTS-12Hz-1.7B-CustomVoice')
    p.add_argument('--voice', default='uncle_fu')
    p.add_argument('--language', default='Chinese')
    p.add_argument('--instructions', default='自然亲切地讲解技术文章，语速适中，有自然停顿，不要播音腔，不添加内容。')
    p.add_argument('--output-dir', type=Path, default=Path('narration-output'))
    p.add_argument('--chunk-chars', type=int, default=210)
    p.add_argument('--timeout', type=float, default=300)
    p.add_argument('--no-proxy', action='store_true')
    p.add_argument('--host-header', help='Optional HTTP virtual host for an IP-based URL')
    a = p.parse_args()
    a.output_dir.mkdir(parents=True, exist_ok=True)
    chunks = split_text(a.input.read_text(), a.chunk_chars)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({})) if a.no_proxy else urllib.request.build_opener()
    manifest = {'model': a.model, 'voice': a.voice, 'language': a.language, 'instructions': a.instructions,
                'input_sha256': hashlib.sha256(a.input.read_bytes()).hexdigest(), 'segments': []}
    frames, sample_rate, offset = [], None, 0.0
    for i, text in enumerate(chunks, 1):
        payload = {'model': a.model, 'input': text, 'voice': a.voice, 'language': a.language,
                   'instructions': a.instructions, 'response_format': 'wav'}
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
        digest = hashlib.sha256(body).hexdigest()
        stem = a.output_dir/f'{i:03}-{digest[:12]}'
        wav = stem.with_suffix('.wav')
        request_file = stem.with_suffix('.request.json')
        elapsed = None
        cached = False
        if wav.exists() and request_file.exists() and request_file.read_bytes() == body:
            try:
                wav_info(wav.read_bytes())
                cached = True
            except (ValueError, wave.Error, EOFError):
                pass
        request_file.write_bytes(body)
        timing_file = stem.with_suffix('.timing.json')
        if not cached:
            headers = {'Content-Type': 'application/json'}
            if a.host_header:
                headers['Host'] = a.host_header
            if os.environ.get('TTS_API_KEY'):
                headers['Authorization'] = 'Bearer '+os.environ['TTS_API_KEY']
            # Retry only transient failures, once. Keep error bodies for inspection.
            for attempt in (1, 2):
                started = time.perf_counter()
                try:
                    req = urllib.request.Request(a.base_url.rstrip('/')+'/v1/audio/speech', data=body, headers=headers)
                    with opener.open(req, timeout=a.timeout) as r:
                        data = r.read()
                    wav_info(data)
                    wav.write_bytes(data)
                    elapsed = time.perf_counter()-started
                    timing_file.write_text(json.dumps({'request_seconds': elapsed}))
                    break
                except urllib.error.HTTPError as e:
                    stem.with_suffix(f'.attempt-{attempt}.error').write_bytes(e.read())
                    if attempt == 2 or e.code not in (429, 502, 503, 504):
                        raise
                    time.sleep(2)
                except (urllib.error.URLError, TimeoutError) as e:
                    stem.with_suffix(f'.attempt-{attempt}.error').write_text(str(e))
                    if attempt == 2:
                        raise
                    time.sleep(2)
        elif timing_file.exists():
            elapsed = json.loads(timing_file.read_text())['request_seconds']
        samples, rate, seconds, rms = wav_info(wav.read_bytes())
        if sample_rate is not None and rate != sample_rate:
            raise ValueError('Sample rate changed across paragraphs')
        sample_rate = rate
        # Simple paragraph RMS leveling, not an EBU R128 loudness measurement.
        peak = max(abs(v) for v in samples)
        gain = min(10**(6/20), 10**(-23/20)*32768/rms, .9*32767/peak)
        adjusted = array.array('h', (round(v*gain) for v in samples))
        if sys.byteorder != 'little':
            adjusted.byteswap()
        frames.append(adjusted.tobytes())
        segment = {'index': i, 'text': text, 'characters': len(text), 'duration_seconds': seconds,
                   'request_seconds': elapsed, 'cached': cached, 'start_seconds': offset,
                   'raw_audio_sha256': hashlib.sha256(wav.read_bytes()).hexdigest(), 'gain_db': 20*math.log10(gain)}
        manifest['segments'].append(segment)
        offset += seconds
        if i < len(chunks):
            pause = .65 if len(text) < 35 else .35
            frames.append(b'\x00\x00'*round(rate*pause))
            offset += pause
        (a.output_dir/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
        print(f'{i}/{len(chunks)}: {seconds:.2f}s audio, cached={cached}', flush=True)
    output = a.output_dir/'narration.wav'
    with wave.open(str(output), 'wb') as w:
        w.setparams((1, 2, sample_rate, 0, 'NONE', 'not compressed'))
        for frame in frames:
            w.writeframes(frame)
    with wave.open(str(output), 'rb') as w:
        manifest['output'] = {'file': output.name, 'sample_rate': sample_rate, 'duration_seconds': w.getnframes()/sample_rate,
                              'sha256': hashlib.sha256(output.read_bytes()).hexdigest()}
    (a.output_dir/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(json.dumps(manifest['output'], ensure_ascii=False))


if __name__ == '__main__':
    main()
