#!/usr/bin/env python3
"""Append GPU measurements once per second; keep the CSV on persistent storage."""
import argparse
from datetime import datetime, timezone
import subprocess
import time
from pathlib import Path

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('output')
p.add_argument('--interval', type=float, default=1)
a = p.parse_args()
fields = 'index,uuid,name,memory.used,memory.total,utilization.gpu,power.draw,temperature.gpu'
memory_files = [Path('/sys/fs/cgroup/memory') / name for name in
                ('memory.usage_in_bytes', 'memory.max_usage_in_bytes', 'memory.limit_in_bytes')]
with open(a.output, 'x', buffering=1) as out:
    out.write('utc,' + fields + ',container_memory_bytes,container_memory_peak_bytes,container_memory_limit_bytes\n')
    while True:
        now = datetime.now(timezone.utc).isoformat()
        result = subprocess.run(['nvidia-smi', '--query-gpu=' + fields,
                                 '--format=csv,noheader,nounits'], text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
        if result.returncode:
            raise RuntimeError(result.stderr)
        memory = ','.join(path.read_text().strip() if path.exists() else '' for path in memory_files)
        for line in result.stdout.splitlines():
            out.write(now + ',' + line + ',' + memory + '\n')
        time.sleep(a.interval)
