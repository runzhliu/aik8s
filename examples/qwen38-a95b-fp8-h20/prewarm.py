#!/usr/bin/env python3
"""Incrementally copy stable safetensors from read-only CFS to NVMe (Python 3.6)."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import threading
import time

from nvme_probe import probe

AUX = ['config.json', 'generation_config.json', 'tokenizer.json',
       'tokenizer_config.json', 'chat_template.jinja', 'merges.txt', 'vocab.json',
       'model.safetensors.index.json', 'README.md', 'LICENSE']
RESERVE = 300000000000


def stamp(path):
    s = path.stat()
    return [s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_ino]


def atomic(path, data):
    tmp = path.with_name(path.name + '.new')
    with tmp.open('w') as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.flush()
        os.fsync(f.fileno())
    os.replace(str(tmp), str(path))


def flush_copy_cache(src, dst, offset):
    """Bound dirty pages and release consumed source/destination cache on Linux."""
    dst.flush()
    os.fsync(dst.fileno())
    if hasattr(os, 'posix_fadvise'):
        for stream in (src, dst):
            try:
                os.posix_fadvise(stream.fileno(), 0, offset, os.POSIX_FADV_DONTNEED)
            except OSError:
                # Some filesystems do not implement this advisory operation.
                pass


def inspect_shard(path, keys):
    """Read only the small header; verify complete extent and indexed tensor names."""
    before = stamp(path)
    with path.open('rb') as f:
        raw = f.read(8)
        if len(raw) != 8:
            raise ValueError('incomplete length')
        n = struct.unpack('<Q', raw)[0]
        if not 2 <= n <= 64 * 1024 * 1024:
            raise ValueError('invalid header length')
        header = f.read(n)
    obj = json.loads(header.decode('utf-8'))
    tensors = {k: v for k, v in obj.items() if k != '__metadata__'}
    if set(tensors) != set(keys):
        raise ValueError('header/index tensor mismatch')
    end = 0
    for lo, hi in sorted(v['data_offsets'] for v in tensors.values()):
        if lo != end or hi < lo:
            raise ValueError('invalid data extents')
        end = hi
    if before[0] != 8 + n + end or stamp(path) != before:
        raise ValueError('incomplete or changing shard')
    return {'stamp': before, 'payload_bytes': end,
            'header_sha256': hashlib.sha256(header).hexdigest()}


class Prewarm:
    def __init__(self, args):
        self.args = args
        self.src, self.dst = Path(args.source), Path(args.destination)
        self.meta = self.dst / '.aik8s-prewarm'
        self.meta.mkdir(parents=True, exist_ok=True)
        self.records_file = self.meta / 'copied.json'
        self.records = json.loads(self.records_file.read_text()) if self.records_file.exists() else {}
        self.lock = threading.Lock()
        self.stable = {}
        self.scan_state = {}
        self.current = None
        self.stop = threading.Event()
        self.started = time.time()
        self.current_rate = args.mib_per_second

    def scan(self):
        index_path = self.src / 'model.safetensors.index.json'
        ibefore = stamp(index_path)
        iraw = index_path.read_bytes()
        index = json.loads(iraw)
        if stamp(index_path) != ibefore:
            raise ValueError('changing index')
        grouped = {}
        for key, name in index['weight_map'].items():
            if Path(name).name != name or not name.endswith('.safetensors'):
                raise ValueError('unsafe shard name')
            grouped.setdefault(name, []).append(key)
        if len(grouped) != 213:
            raise ValueError('expected 213 unique shards')
        good, waiting = {}, {}
        for name in sorted(set(grouped) | set(AUX)):
            try:
                p = self.src / name
                if p.is_symlink() or not p.is_file():
                    raise ValueError('absent or symlink')
                if name in grouped:
                    info = inspect_shard(p, grouped[name])
                else:
                    before = stamp(p)
                    data = p.read_bytes()
                    if stamp(p) != before or not data:
                        raise ValueError('empty or changing auxiliary file')
                    if name.endswith('.json'):
                        json.loads(data)
                    info = {'stamp': before, 'sha256': hashlib.sha256(data).hexdigest()}
                now = time.time()
                previous = self.stable.get(name)
                if previous is None or previous[0] != info['stamp']:
                    previous = (info['stamp'], now)
                    self.stable[name] = previous
                if now - previous[1] < self.args.stable_seconds:
                    raise ValueError('waiting for stable observation window')
                good[name] = info
            except (OSError, ValueError, KeyError, TypeError) as e:
                waiting[name] = str(e)
                if 'stable observation' not in str(e):
                    self.stable.pop(name, None)
        pending = sorted(set(grouped) - set(good))
        return {'index_sha256': hashlib.sha256(iraw).hexdigest(),
                'index_total_size': index['metadata']['total_size'],
                'expected_shards': len(grouped), 'source_complete_shards': len(set(good) & set(grouped)),
                'source_pending_shards': pending, 'waiting': waiting, 'good': good,
                'temporary_files': sorted(p.name for p in self.src.iterdir()
                                          if p.name.endswith(('.tmp', '.part', '.incomplete'))),
                'scanned_at': time.time(), 'keys': grouped}

    def local_matches(self, name, info):
        record = self.records.get(name)
        p = self.dst / name
        return (record is not None and record.get('source') == info and p.is_file()
                and not p.is_symlink() and record.get('local_stamp') == stamp(p))

    def publish(self, phase='copying', error=None):
        with self.lock:
            s = dict(self.scan_state)
            good = s.pop('good', {})
            s.pop('keys', None)
            complete = [n for n, i in good.items() if self.local_matches(n, i)]
            s.update({'phase': phase, 'error': error, 'node': os.environ.get('NODE_NAME'),
                      'started_at': self.started, 'updated_at': time.time(),
                      'local_complete_shards': sum(n.endswith('.safetensors') for n in complete),
                      'local_complete_bytes': sum(good[n]['stamp'][0] for n in complete),
                      'current': self.current, 'free_bytes': shutil.disk_usage(str(self.dst)).free,
                      'rate_limit_mib_s': self.current_rate})
            atomic(self.meta / 'progress.json', s)
            print(json.dumps(s, sort_keys=True), flush=True)

    def monitor(self):
        while not self.stop.is_set():
            try:
                state = self.scan()
                with self.lock:
                    self.scan_state = state
                self.publish()
            except Exception as e:
                self.publish('waiting_source', str(e))
            self.stop.wait(self.args.scan_seconds)

    def copy(self, name, info):
        source = self.src / name
        if stamp(source) != info['stamp']:
            return
        partial = self.meta / (name + '.part')
        identity = self.meta / (name + '.source.json')
        resumable = (partial.exists() and identity.exists()
                     and json.loads(identity.read_text()) == info
                     and partial.stat().st_size <= info['stamp'][0])
        offset = partial.stat().st_size if resumable else 0
        atomic(identity, info)
        mode = 'ab' if resumable else 'wb'
        begin = time.monotonic()
        budget = self.current_rate * 1024 * 1024
        transferred = 0
        since_flush = 0
        last_control_read = 0
        with source.open('rb') as src, partial.open(mode) as dst:
            src.seek(offset)
            while offset < info['stamp'][0]:
                now = time.monotonic()
                if now - last_control_read >= 1 and getattr(self.args, 'control_file', None):
                    last_control_read = now
                    try:
                        control = json.loads(Path(self.args.control_file).read_text())
                        rate = float(control.get('nodes', {}).get(os.environ.get('NODE_NAME'),
                                                                  control['default_mib_s']))
                        if 0 <= rate <= 2048 and rate != self.current_rate:
                            self.current_rate = rate
                            budget = rate * 1024 * 1024
                            begin, transferred = now, 0
                    except (OSError, ValueError, KeyError, TypeError):
                        pass
                if shutil.disk_usage(str(self.dst)).free < RESERVE + 16 * 1024 * 1024:
                    raise RuntimeError('disk reserve reached; waiting for available space')
                block = src.read(min(8 * 1024 * 1024, info['stamp'][0] - offset))
                if not block:
                    return
                dst.write(block)
                offset += len(block)
                transferred += len(block)
                since_flush += len(block)
                if since_flush >= 64 * 1024 * 1024:
                    flush_copy_cache(src, dst, offset)
                    since_flush = 0
                with self.lock:
                    self.current = {'name': name, 'bytes': offset, 'total_bytes': info['stamp'][0]}
                delay = transferred / budget - (time.monotonic() - begin) if budget else 0
                if delay > 0:
                    time.sleep(delay)
            flush_copy_cache(src, dst, offset)
        if stamp(source) != info['stamp']:
            return
        if name.endswith('.safetensors'):
            with self.lock:
                keys = self.scan_state['keys'][name]
            local = inspect_shard(partial, keys)
            if local['header_sha256'] != info['header_sha256']:
                raise ValueError('local header mismatch')
        elif hashlib.sha256(partial.read_bytes()).hexdigest() != info['sha256']:
            raise ValueError('local auxiliary digest mismatch')
        os.replace(str(partial), str(self.dst / name))
        with self.lock:
            self.records[name] = {'source': info, 'local_stamp': stamp(self.dst / name)}
            atomic(self.records_file, self.records)
            self.current = None
        self.publish()

    def run(self):
        # A stale completion marker must never authorize loading a different snapshot.
        marker = self.dst / '.aik8s-complete'
        if marker.exists():
            os.replace(str(marker), str(self.meta / 'previous-complete.json'))
        thread = threading.Thread(target=self.monitor, daemon=True)
        thread.start()
        while True:
            with self.lock:
                state = dict(self.scan_state)
            good = state.get('good', {})
            complete_bytes = sum(i['stamp'][0] for n, i in good.items() if self.local_matches(n, i))
            required = state.get('index_total_size', 2496066252544) + 1000000000
            if shutil.disk_usage(str(self.dst)).free < max(0, required - complete_bytes) + RESERVE:
                self.publish('waiting_space', 'insufficient space for remaining model plus reserve')
                time.sleep(60)
                continue
            todo = [n for n, i in good.items() if not self.local_matches(n, i)]
            if todo:
                # Rotate order across nodes to avoid synchronized reads of the same CFS shard.
                order = sorted(set(state['keys']) | set(AUX))
                shift = self.args.order_offset % len(order)
                name = next(n for n in order[shift:] + order[:shift] if n in todo)
                try:
                    self.copy(name, good[name])
                except (OSError, ValueError, RuntimeError) as e:
                    self.publish('retrying', str(e))
                    time.sleep(60)
                continue
            if state and not state['waiting'] and len(good) == 213 + len(AUX):
                # Re-scan immediately before creating the load gate.
                final = self.scan()
                if final['good'] == good and not final['waiting']:
                    payload = sum(i.get('payload_bytes', 0) for i in good.values())
                    if payload != final['index_total_size']:
                        raise ValueError('index total_size differs from shard payload sum')
                    self.stop.set()
                    thread.join()
                    atomic(marker, {'completed_at': time.time(), 'index_sha256': final['index_sha256'],
                                    'shards': 213, 'payload_bytes': payload,
                                    'validation': 'stable source metadata, tensor headers, extents and small-file SHA256; no full weight hash',
                                    'files': self.records})
                    self.publish('complete')
                    return
            time.sleep(5)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--source', default='/models/Qwen3.8-2.4T-A95B-FP8/v1')
    p.add_argument('--destination', default='/host-data/model-cache/Qwen3.8-2.4T-A95B-FP8/v1')
    p.add_argument('--mib-per-second', type=float, default=256)
    p.add_argument('--stable-seconds', type=int, default=60)
    p.add_argument('--scan-seconds', type=int, default=60)
    p.add_argument('--order-offset', type=int, default=0)
    p.add_argument('--control-file', help='Optional JSON with default_mib_s and per-node overrides')
    args = p.parse_args()
    check = probe()
    print(json.dumps({'preflight': check}), flush=True)
    if not check['eligible'] or check['free_bytes'] < 2400000000000:
        raise SystemExit('NVMe/space preflight rejected; no model directory created')
    Prewarm(args).run()


if __name__ == '__main__':
    main()
