"""Independent backstop for the exact resources armed by run_drill.py."""
import argparse
import json
from pathlib import Path
import subprocess
import time

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--config',required=True,type=Path)
a=p.parse_args()
settings=json.loads(a.config.read_text())
root=a.config.parent.parent
prefix=['kubectl','--context',settings['context'],'-n',settings['namespace']]
while not (root/'done').exists():
    path=root/'private'/'armed.json'
    if path.exists():
        try:
            state=json.loads(path.read_text())
            if time.time()>state['deadline']:
                for row in state.get('scales',[]):
                    subprocess.run(prefix+['scale',row['resource'],'--replicas='+str(row['replicas'])],check=True,timeout=20)
                if state.get('processes'):
                    script=Path(__file__).with_name('process_guard.py').read_text()
                    request={'action':'signal','signal':'CONT','processes':state['processes']}
                    subprocess.run(prefix+['exec','ds/cube-node','-c','cubelet','--','python3','-c',script,json.dumps(request)],check=True,timeout=20)
                path.rename(root/'private'/('watchdog-restored-'+str(int(time.time()))+'.json'))
        except Exception as exc:
            print('Recovery retry:',type(exc).__name__,flush=True)
    time.sleep(2)
