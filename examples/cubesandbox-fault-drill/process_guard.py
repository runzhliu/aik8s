"""Run inside the privileged Cubelet container; never select by name alone.

Input is one JSON argument. Discovery is read-only. Signals require a stored
PID, Linux start-time value, and exact command hash to prevent PID reuse.
"""
import hashlib
import json
import os
from pathlib import Path
import signal
import sys

request = json.loads(sys.argv[1])


def read_process(pid):
    base = Path('/proc') / str(pid)
    raw = (base / 'cmdline').read_bytes()
    # /proc/PID/stat's comm field may contain spaces or parentheses.
    stat = (base / 'stat').read_text().rsplit(')', 1)[1].split()
    return {'pid': int(pid), 'start_time': stat[19],
            'command_sha256': hashlib.sha256(raw).hexdigest(),
            'command': raw.replace(b'\0', b' ').decode(errors='replace'),
            'cgroup': (base / 'cgroup').read_text(),
            'netns': os.readlink(base / 'ns' / 'net')}


if request['action'] == 'discover':
    result = []
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit() or int(entry.name) <= 1:
            continue
        try:
            row = read_process(entry.name)
            mode = request['mode']
            if mode == 'cubelet':
                if request['container_id'] not in row['cgroup']:
                    continue
                if not row['command'].startswith('/usr/local/services/cubetoolbox/Cubelet/bin/cubelet '):
                    continue
            elif mode == 'egress':
                if request['container_id'] not in row['cgroup']:
                    continue
                if 'nginx:' not in row['command'] and '/openresty' not in row['command']:
                    continue
            elif mode == 'vmm':
                sid = request['sandbox_id']
                if not sid or len(sid) < 12 or sid not in row['command']:
                    continue
                argv = (entry / 'cmdline').read_bytes().decode(errors='replace').split('\0')
                embedded = (argv[0].startswith('/data/cubelet/root/component_versions/cube-shim/')
                            and argv[0].endswith('/bin/containerd-shim-cube-rs')
                            and '-id' in argv and argv[argv.index('-id') + 1] == sid)
                separate = ('cube-hypervisor' in argv[0] and '/cubetoolbox/' in argv[0])
                if not embedded and not separate:
                    continue
                row['runtime_mode'] = 'embedded-rust-shim' if embedded else 'separate-hypervisor'
                fds = []
                for fd in (entry / 'fd').iterdir():
                    try:
                        fds.append(os.readlink(fd))
                    except OSError:
                        pass
                if not any('kvm-vm' in link for link in fds):
                    continue
                row['kvm_vm_handles'] = sum('kvm-vm' in link for link in fds)
                digest = hashlib.sha256()
                with open(argv[0], 'rb') as executable:
                    for chunk in iter(lambda: executable.read(1024 * 1024), b''):
                        digest.update(chunk)
                row['executable_sha256'] = digest.hexdigest()
                manifest = Path(argv[0]).parent.parent / 'version.json'
                if manifest.exists():
                    row['component_manifest'] = json.loads(manifest.read_text())
            else:
                raise ValueError('unknown process mode')
            result.append(row)
        except (FileNotFoundError, ProcessLookupError, PermissionError, OSError):
            continue
    if request['mode'] in ('cubelet', 'vmm') and len(result) != 1:
        raise RuntimeError('expected exactly one qualified process; found ' + str(len(result)))
    if not result:
        raise RuntimeError('no qualified processes')
    print(json.dumps(result))
elif request['action'] == 'inspect':
    result=[]
    for expected in request['processes']:
        try:
            current=read_process(expected['pid'])
            same=all(current[k]==expected[k] for k in ('start_time','command_sha256'))
        except (FileNotFoundError,ProcessLookupError):
            same=False
        result.append({'pid':expected['pid'],'same_process_alive':same})
    print(json.dumps(result))
elif request['action'] == 'signal':
    number = {'STOP': signal.SIGSTOP, 'CONT': signal.SIGCONT, 'KILL': signal.SIGKILL}[request['signal']]
    result = []
    for expected in request['processes']:
        if int(expected['pid']) <= 1:
            raise RuntimeError('PID 1 is forbidden')
        try:
            current = read_process(expected['pid'])
        except (FileNotFoundError, ProcessLookupError):
            if request['signal'] == 'CONT':
                result.append({'pid': expected['pid'], 'state': 'already_exited'})
                continue
            raise
        if any(current[k] != expected[k] for k in ('start_time', 'command_sha256')):
            raise RuntimeError('PID identity changed; refuse signal')
        os.kill(current['pid'], number)
        result.append({'pid': current['pid'], 'signal': request['signal']})
    print(json.dumps(result))
else:
    raise ValueError('unknown action')
