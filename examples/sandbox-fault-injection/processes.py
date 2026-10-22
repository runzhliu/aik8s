"""Inspect or kill a verified process inside a dedicated fault Pod only."""
import json
import os
from pathlib import Path
import signal
import sys

assert 'threading.Event' in Path('/proc/1/cmdline').read_bytes().decode().replace('\0', ' '), 'Not the dedicated idle fault container'
rows = []
for proc in Path('/proc').iterdir():
    if not proc.name.isdigit() or int(proc.name) == os.getpid():
        continue
    try:
        args = (proc / 'cmdline').read_bytes().decode(errors='replace').split('\0')
        fds = []
        for fd in (proc / 'fd').iterdir():
            try:
                target = os.readlink(fd)
                if target == '/dev/kvm' or 'kvm-vm' in target or 'kvm-vcpu' in target:
                    fds.append(target)
            except OSError:
                pass
        rows.append({'pid': int(proc.name), 'executable': Path(args[0]).name,
                     'kvm_fds': fds, 'is_worker': '/app/sdk_worker.py' in args,
                     'is_proxy': 'gvproxy' in Path(args[0]).name or 'boxlite-net' in Path(args[0]).name})
    except (OSError, IndexError):
        pass
if len(sys.argv) > 1:
    kind = sys.argv[1]
    choices = [r for r in rows if r['pid'] > 1 and (
        bool(r['kvm_fds']) if kind == 'vmm' else r['is_proxy'] if kind == 'proxy' else r['is_worker'])]
    assert len(choices) == 1, (kind, choices)
    os.kill(choices[0]['pid'], signal.SIGKILL)
    print(json.dumps({'killed': choices[0], 'signal': 'SIGKILL'}))
else:
    print(json.dumps(rows))
