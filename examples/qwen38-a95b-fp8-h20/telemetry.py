#!/usr/bin/env python3
"""Read-only hardware samples; preserve raw counters so rates can be derived."""
import json,os,subprocess,time
from pathlib import Path
ROOT=Path(os.environ.get('TELEMETRY_DIR','/outputs/telemetry'))
ROOT.mkdir(parents=True,exist_ok=True)

def command(args):
 try:
  p=subprocess.run(args,capture_output=True,text=True,timeout=15)
  return {'returncode':p.returncode,'stdout':p.stdout,'stderr':p.stderr}
 except subprocess.TimeoutExpired:return {'error':'timeout'}

with (ROOT/'gpu-dmon.log').open('a') as f:
 dmon=subprocess.Popen(['nvidia-smi','dmon','-s','pucmt','-d','5','-o','DT'],stdout=f,stderr=f)
 try:
  deadline=time.time()+86400
  with (ROOT/'samples.jsonl').open('a',buffering=1) as out:
   while time.time()<deadline and not (ROOT/'stop').exists():
    start=time.time();data={'at':start,'node_rank':os.getenv('NODE_RANK')}
    try:data['phase']=json.loads(Path('/control/phase.json').read_text())['id']
    except (OSError,ValueError):pass
    data['nvlink']=command(['nvidia-smi','nvlink','-gt','d'])
    data['rdma']={}
    for p in Path('/sys/class/infiniband').glob('mlx5_bond_*/ports/1/counters'):
     data['rdma'][str(p)]={}
     for n in ['port_xmit_data','port_rcv_data','port_xmit_packets','port_rcv_packets','port_xmit_wait']:
      try:data['rdma'][str(p)][n]=int((p/n).read_text())
      except (OSError,ValueError):pass
    data['counter_units']={'port_xmit_data':'4 octets','port_rcv_data':'4 octets','nvlink':'KiB (raw nvidia-smi output)'}
    out.write(json.dumps(data)+'\n');time.sleep(max(1,10-(time.time()-start)))
 finally:dmon.terminate();dmon.wait(timeout=15)
