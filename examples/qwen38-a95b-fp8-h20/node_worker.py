#!/usr/bin/env python3
"""Execute bounded per-rank commands, retain NVMe evidence, publish small states."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from unattended import save, terminate


def main():
    root=Path(os.getenv('OUTPUT_ROOT','/outputs'));root.mkdir(parents=True,exist_ok=True)
    rank=int(os.environ['NODE_RANK']);end=float(os.environ.get('RUN_DEADLINE_EPOCH','0'))
    if end<=time.time():raise RuntimeError('an explicit future run deadline is required')
    hardware=subprocess.Popen([sys.executable,str(Path(__file__).with_name('hardware_metrics.py'))])
    api=None
    if os.getenv('STATE_CONFIGMAP'):
        from cluster_api import API
        api=API()
    def publish(path,state):
        save(path,state)
        if api:
            try:api.state(os.environ['STATE_CONFIGMAP'],state)
            except RuntimeError:pass  # durable file still exists; controller bounds unknown status
    def desired():return json.loads(Path('/control/phase.json').read_text())
    while time.time()<end:
        try:control=desired()
        except (OSError,ValueError):time.sleep(2);continue
        ident=control.get('id','hold')
        if not ident.replace('-','').replace('_','').isalnum():raise ValueError('invalid phase ID')
        path=root/ident;state_path=path/'state.json'
        argv=control.get('commands',{}).get(str(rank))
        if not argv or control.get('phase')=='hold':time.sleep(2);continue
        if state_path.exists():
            # Restart never replays a potentially non-idempotent phase.
            old=json.loads(state_path.read_text())
            if old.get('status')=='RUNNING':
                old.update(status='FAILED',reason='worker restarted; phase not replayed',finished_at=time.time())
            publish(state_path,old);time.sleep(5);continue
        phase_end=min(end,float(control.get('deadline_epoch',0)))
        if phase_end<=time.time():
            publish(state_path,{'id':ident,'rank':rank,'status':'NOT_EXECUTED','reason':'expired phase'});continue
        state={'id':ident,'rank':rank,'command':argv,'started_at':time.time(),
               'deadline_epoch':phase_end,'status':'RUNNING'}
        publish(state_path,state)
        with (path/'run.log').open('x') as log:
            proc=subprocess.Popen(argv,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            reason='';last_publish=0
            try:
                while proc.poll() is None:
                    now=time.time()
                    if now>=phase_end:reason='deadline';break
                    try:
                        if desired().get('id')!=ident:reason='phase changed';break
                    except (OSError,ValueError):pass
                    if now-last_publish>15:
                        state.update(heartbeat_at=now,log_bytes=(path/'run.log').stat().st_size)
                        publish(state_path,state);last_publish=now
                    time.sleep(2)
            finally:
                if proc.poll() is None:terminate(proc)
            rc=proc.wait()
        text=(path/'run.log').read_text(errors='replace')
        if ident.startswith('vllm-nccl-inter') or ident.startswith('sglang-nccl-inter'):
            if rc and ('Invalid access of peer GPU memory' in text or
                       'CUDA error: an illegal memory access' in text):
                reason='HARD_NCCL_CUDA: peer GPU/NVLink access or hardware error'
            elif rc and ('ibv_modify_qp failed' in text or
                         'unhandled system error' in text):
                reason='HARD_NCCL_RDMA: IB queue-pair setup failed'
        if (ident.startswith('vllm-nccl-inter') or ident.startswith('sglang-nccl-inter')) and rc==0:
            if 'Using network Socket' in text or not ('NET/IB' in text or 'Using network IB' in text):
                rc=1;reason='IB transport evidence missing or Socket fallback'
        state.update(status='FAILED' if reason=='deadline' or rc else 'PASS',returncode=rc,
                     reason=reason,finished_at=time.time())
        publish(state_path,state)
        print(json.dumps(state),flush=True)

if __name__=='__main__':main()
