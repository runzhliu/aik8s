"""Restore only recorded deployment replica counts after controller expiry."""
import argparse
import json
from pathlib import Path
import subprocess
import time

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--config', required=True, type=Path)
a = p.parse_args()
cfg = json.loads(a.config.read_text())
root = a.config.parent
while not (root / 'done').exists():
    armed = root / 'armed.json'
    if armed.exists():
        try:
            value = json.loads(armed.read_text())
            if time.time() > value['deadline']:
                for name, count in value['replicas'].items():
                    subprocess.run(['kubectl', '--context', cfg['context'], '-n', cfg['namespace'],
                                    'scale', 'deployment/' + name, '--replicas=' + str(count)],
                                   check=True, capture_output=True, timeout=25)
                armed.rename(root / ('watchdog-restored-' + str(int(time.time())) + '.json'))
        except Exception as exc:
            print('watchdog retry', type(exc).__name__, flush=True)
    time.sleep(2)
