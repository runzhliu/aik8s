#!/usr/bin/env python3
"""Copy immutable media from a benchmark Pod and verify local bytes and SHA-256.

Never deletes remote files or overwrites a differing local file.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--cluster',required=True)
p.add_argument('--namespace',default='aik8s-ms')
p.add_argument('--pod',required=True)
p.add_argument('--remote-root',required=True)
p.add_argument('--local-root',type=Path,required=True)
p.add_argument('--completed-only',action='store_true',help='only MP4 files with a completed client result JSON')
p.add_argument('--gallery',type=Path,help='refresh an offline local media gallery after each verified backup')
p.add_argument('--watch-seconds',type=int,default=0,help='repeat every 60s; stop on error or .stop-backup-watch in local root')
a=p.parse_args()
if a.watch_seconds:
    command=[sys.executable,__file__,'--cluster',a.cluster,'--namespace',a.namespace,
             '--pod',a.pod,'--remote-root',a.remote_root,'--local-root',str(a.local_root)]
    if a.completed_only:command.append('--completed-only')
    if a.gallery:command.extend(['--gallery',str(a.gallery)])
    deadline=time.monotonic()+a.watch_seconds
    while time.monotonic()<deadline and not (a.local_root/'.stop-backup-watch').exists():
        completed=subprocess.run(command,capture_output=True,text=True)
        print(completed.stdout,end='',flush=True)
        if completed.returncode:
            print(completed.stderr,end='',file=sys.stderr,flush=True)
            if not any(s in completed.stderr.lower() for s in
                ('no such host','i/o timeout','connection reset','operation timed out',
                 'connection refused','tls handshake timeout','context deadline exceeded',
                 'network is unreachable','unexpected eof')):
                raise SystemExit(completed.returncode)
            print('Transient transfer failure; retaining files and retrying in 60s.',flush=True)
        time.sleep(60)
    raise SystemExit(0)
base=['gmanctl','--cluster',a.cluster,'-n',a.namespace]
script='''import hashlib,json,sys
from pathlib import Path
root=Path(sys.argv[1]);rows=[];completed_only=sys.argv[2]=='1'
for p in sorted(root.rglob('*')):
 if p.is_file() and p.suffix.lower() in {'.mp4','.wav','.png','.jpg','.jpeg'}:
  result=None
  if completed_only:
   metadata=p.with_suffix('.json')
   if p.suffix.lower()!='.mp4' or not metadata.is_file():continue
   try:result=json.loads(metadata.read_text())
   except ValueError:continue
   if result.get('status') not in ('PASS','FAIL') or 'file_sha256' not in result:continue
  before=p.stat();h=hashlib.sha256()
  with p.open('rb') as f:
   while True:
    chunk=f.read(1024*1024)
    if not chunk:break
    h.update(chunk)
  after=p.stat()
  if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise RuntimeError('media still changing: '+str(p))
  row=dict(path=p.relative_to(root).as_posix(),bytes=after.st_size,sha256=h.hexdigest())
  if result is not None:
   if result['file_sha256']!=row['sha256']:raise RuntimeError('client result/media digest mismatch')
   row['result']=result
   summary=p.parent/'summary.json'
   if summary.is_file():
    try:row['summary']=json.loads(summary.read_text())
    except ValueError:pass
  rows.append(row)
print(json.dumps(rows))
'''
rows=json.loads(subprocess.check_output(base+['exec',a.pod,'--','python3','-c',script,a.remote_root,
                                             '1' if a.completed_only else '0'],text=True))
a.local_root.mkdir(parents=True,exist_ok=True)
for row in rows:
    relative=Path(row['path'])
    if relative.is_absolute() or '..' in relative.parts:raise ValueError('unsafe relative media path')
    target=a.local_root/relative
    target.parent.mkdir(parents=True,exist_ok=True)
    if not target.exists():
        partial=target.with_name(target.name+'.partial')
        if partial.exists():
            if partial.stat().st_size==row['bytes'] and hashlib.sha256(partial.read_bytes()).hexdigest()==row['sha256']:
                partial.rename(target)
            else:
                partial.rename(partial.with_name(partial.name+'.interrupted-'+str(time.time_ns())))
        if not target.exists():
            subprocess.run(base+['cp',a.pod+':'+a.remote_root.rstrip('/')+'/'+row['path'],str(partial)],check=True)
        else:
            partial=target
        if partial.stat().st_size!=row['bytes'] or hashlib.sha256(partial.read_bytes()).hexdigest()!=row['sha256']:
            raise RuntimeError('backup checksum mismatch: '+str(partial))
        if partial!=target:partial.rename(target)
    if target.stat().st_size!=row['bytes'] or hashlib.sha256(target.read_bytes()).hexdigest()!=row['sha256']:
        raise RuntimeError('existing local media differs; retained without overwrite: '+str(target))
    if 'result' in row:
        metadata=target.with_suffix('.json')
        if metadata.exists() and json.loads(metadata.read_text())!=row['result']:
            raise RuntimeError('existing result metadata differs: '+str(metadata))
        metadata.write_text(json.dumps(row['result'],indent=2)+'\n')
    if 'summary' in row:
        summary_path=target.parent/'summary.json'
        if summary_path.exists() and json.loads(summary_path.read_text())!=row['summary']:
            raise RuntimeError('existing summary differs: '+str(summary_path))
        summary_path.write_text(json.dumps(row['summary'],indent=2)+'\n')
(a.local_root/'media-backup-manifest.json').write_text(json.dumps(rows,indent=2)+'\n')
print(json.dumps(dict(status='PASS',files=len(rows),bytes=sum(x['bytes'] for x in rows),
                      local_root=str(a.local_root)),indent=2))
if a.gallery:
    subprocess.run([sys.executable,str(Path(__file__).with_name('build_gallery.py')),
                    '--source',str(a.local_root),'--output',str(a.gallery)],check=True)
