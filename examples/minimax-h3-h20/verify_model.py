#!/usr/bin/env python3
"""Read-only metadata/header validation, optionally compare a local copy.

Reads safetensors headers, never hashes full model tensors. A supplied Hub file
manifest proves names/sizes only; report this limit rather than claiming hashes.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct


def inspect(root):
    files, errors, indexes, fingerprints = {}, [], [], {}
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root).as_posix()
        if '.cache' in path.relative_to(root).parts or relative.startswith('.aik8s'):
            continue
        if not path.is_file():
            continue
        size = path.stat().st_size
        files[relative] = size
        if path.suffix == '.safetensors':
            try:
                with path.open('rb') as stream:
                    length = struct.unpack('<Q', stream.read(8))[0]
                    if not 0 < length < min(size, 128 * 1024 * 1024):
                        raise ValueError('invalid header length')
                    header_bytes = stream.read(length)
                    header = json.loads(header_bytes)
                    fingerprints[relative] = hashlib.sha256(header_bytes).hexdigest()
                end = max(v['data_offsets'][1] for k, v in header.items() if k != '__metadata__')
                if end + 8 + length != size:
                    raise ValueError(f'tensor extent {end + 8 + length} differs from size {size}')
            except Exception as exc:
                errors.append(f'{relative}: {exc}')
        elif size < 20 * 1024 * 1024 and path.suffix not in ('.mp4', '.wav'):
            fingerprints[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        if path.name.endswith('.index.json'):
            index = json.loads(path.read_text())
            for shard in set(index.get('weight_map', {}).values()):
                if not (path.parent / shard).is_file():
                    errors.append(f'{relative}: missing shard {shard}')
            indexes.append(relative)
    return dict(files=files, bytes=sum(files.values()), errors=errors, indexes=indexes,
                metadata_sha256=fingerprints)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--target', type=Path)
    parser.add_argument('--hub-info', type=Path)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    source = inspect(args.source)
    report = dict(source=source, validation='file names/sizes, shard references, safetensors headers; no tensor payload hashes')
    errors = list(source['errors'])
    if not source['files']:
        errors.append('source is empty')
    if args.hub_info:
        hub = json.loads(args.hub_info.read_text())
        expected = {f['rfilename']: f['size'] for f in hub['siblings'] if 'size' in f}
        report['hub_revision_compared'] = hub['sha']
        report['hub_absent_files'] = sorted(set(expected) - set(source['files']))
        report['hub_size_mismatches'] = [name for name, size in source['files'].items() if name in expected and expected[name] != size]
        required_prefixes = ('FL2VA/', 'Ref2VA/', 'text_encoder/', 'transformer/',
                             'transformer_ref/', 'tokenizer/', 'processor/', 'vae/',
                             'audio_vae/', 'scheduler/', 'audio_scheduler/')
        errors.extend('Hub size mismatch: ' + name for name in report['hub_size_mismatches']
                      if name.startswith(required_prefixes))
        errors.extend('required model file missing: ' + name for name in report['hub_absent_files']
                      if name.startswith(required_prefixes))
        # Alternate official layouts need not coexist; missing paths are recorded
        # and reviewed against the selected engine's component loader.
    if args.target:
        target = inspect(args.target)
        report['target'] = target
        errors.extend(target['errors'])
        excluded = {'REVISION'}
        src = {k:v for k,v in source['files'].items() if k not in excluded}
        dst = {k:v for k,v in target['files'].items() if k not in excluded}
        report['copy_matches'] = src == dst
        if src != dst:
            errors.append('source/target file manifest mismatch')
        src_fp = {k:v for k,v in source['metadata_sha256'].items() if k not in excluded}
        dst_fp = {k:v for k,v in target['metadata_sha256'].items() if k not in excluded}
        if src_fp != dst_fp:
            errors.append('source/target metadata fingerprint mismatch')
    snapshot = {k:source[k] for k in ('files', 'metadata_sha256')}
    report['source_snapshot_id'] = 'metadata-sha256:' + hashlib.sha256(
        json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
    report['errors'] = errors
    report['status'] = 'FAIL' if errors else 'PASS'
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('source', 'target')}, indent=2))
    print(f"files={len(source['files'])} bytes={source['bytes']}")
    return int(bool(errors))


if __name__ == '__main__':
    raise SystemExit(main())
