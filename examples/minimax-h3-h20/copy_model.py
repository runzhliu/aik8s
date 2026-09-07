#!/usr/bin/env python3
"""Copy a model into a NEW directory; retain source and partial copies on failure."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil
import time

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('source', type=Path)
p.add_argument('destination', type=Path)
p.add_argument('--workers', type=int, default=2)
a = p.parse_args()
files = [x for x in a.source.rglob('*') if x.is_file() and '.cache' not in x.relative_to(a.source).parts]
total = sum(x.stat().st_size for x in files)
a.destination.parent.mkdir(parents=True, exist_ok=True)
if shutil.disk_usage(a.destination.parent).free < total + 50 * 1024**3:
    raise SystemExit('insufficient free space including 50 GiB headroom')
a.destination.mkdir(exist_ok=False)
for f in files:
    (a.destination / f.relative_to(a.source)).parent.mkdir(parents=True, exist_ok=True)
start = time.monotonic()

def copy(f):
    target = a.destination / f.relative_to(a.source)
    shutil.copy2(str(f), str(target))
    return f.stat().st_size

done = 0
with ThreadPoolExecutor(max_workers=a.workers) as pool:
    for count, size in enumerate(pool.map(copy, files), 1):
        done += size
        print(json.dumps(dict(files=count, total_files=len(files), bytes=done,
                              total_bytes=total, elapsed_s=round(time.monotonic()-start, 2))), flush=True)
print('COPY_FINISHED_REQUIRES_VERIFICATION', flush=True)
