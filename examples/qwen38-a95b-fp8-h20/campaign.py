#!/usr/bin/env python3
"""Cluster-resident serial campaign and independent watchdog, no laptop dependency."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.parse
from cluster_api import API
from unattended import run_child,save

HERE=Path(__file__).resolve().parent

class Campaign:
    def __init__(self,config,api=None):
        self.config=config;self.api=api or API(config['namespace'])
        self.run=config['run'];self.out=Path(config['output']);self.out.mkdir(parents=True,exist_ok=True)
        self.end=float(config['deadline_epoch']);self.stop=threading.Event()
        self.status={'run':self.run,'status':'PREPARING','engines':{},'started_at':time.time(),
                     'deadline_epoch':self.end,'delivery':{'grafana':'PENDING','openwebui':'PENDING','local_archive':'PENDING','articles':'PENDING'}}
    def update(self,phase,**values):
        self.status.update(status=phase,updated_at=time.time(),**values)
        save(self.out/'campaign-state.json',self.status)
        self.api.state(self.config['state_cm'],self.status)
    def heartbeat(self):
        while not self.stop.wait(15):
            try:
                self.api.state(self.config['heartbeat_cm'],{'run':self.run,'at':time.time(),'deadline_epoch':self.end})
                engine=self.status.get('engine');path=self.out/'results'/str(engine)/'suite-status.json'
                if path.exists():
                    suite=json.loads(path.read_text())
                    progress={'engine':engine,'counts':suite.get('counts'), 'active_rounds':[r['id'] for r in suite.get('rows',[]) if r['status']=='RUNNING'],
                              'last_result_update':suite.get('updated_at'),'deadline_epoch':suite.get('deadline_epoch')}
                    self.api.patch('configmaps',self.config['state_cm'],{'data':{'progress.json':json.dumps(progress)}})
            except (RuntimeError,OSError,ValueError):pass
    def remaining(self,reserve=180):return max(0,self.end-time.time()-reserve)
    def execution_policy(self):
        """Read engine scope between engines; never interrupt the engine in progress."""
        enabled=list(self.config.get('enabled_engines',self.config['engines']))
        name=self.config.get('policy_cm')
        if not name:return {'run':self.run,'enabled_engines':enabled,'reason':'static campaign scope'}
        policy=self.api.read_state(name)
        if policy.get('run')!=self.run:raise RuntimeError('runtime execution policy is missing or belongs to another run')
        selected=policy.get('enabled_engines')
        initial=set(enabled)
        if (not isinstance(selected,list) or len(selected)!=len(set(selected)) or
                any(e not in initial for e in selected)):
            raise RuntimeError('runtime execution policy has invalid enabled_engines')
        return policy
    def all_names(self):return [p['metadata']['name'] for e in self.config['engines'].values() for p in e['pods']]
    def release(self,engine):
        names=[p['metadata']['name'] for p in self.config['engines'][engine]['pods']]
        for name in names:self.api.delete_owned(name,self.run)
        deadline=time.time()+180
        while time.time()<deadline:
            if all(self.api.get('pods',name) is None for name in names):return
            time.sleep(3)
        raise RuntimeError('GPU release unconfirmed; cannot start next engine')
    def archive(self,engine):
        folder=self.out/'runtime'/engine;folder.mkdir(parents=True,exist_ok=True)
        errors=[]
        for pod in self.config['engines'][engine]['pods']:
            name=pod['metadata']['name']
            try:
                obj=self.api.get('pods',name)
                if not obj:continue
                save(folder/(name+'.json'),obj)
                for c in obj['spec'].get('containers',[])+obj['spec'].get('initContainers',[]):
                    try:
                        log=self.api.call(self.api.base+'/pods/'+name+'/log?timestamps=true&container='+c['name'],raw=True)
                        (folder/(name+'-'+c['name']+'.log')).write_text(log or '')
                    except Exception as exc:errors.append(str(exc))
            except Exception as exc:errors.append(str(exc))
        save(folder/'archive-status.json',{'errors':errors,'node_hostpath_retained':True})
    def phase(self,engine,ident,commands,seconds):
        deadline=min(time.time()+seconds,self.end-180)
        control={'id':ident,'phase':'execute','commands':{str(i):v for i,v in enumerate(commands)},'deadline_epoch':deadline}
        save(self.out/(ident+'-control.json'),control)
        self.api.patch('configmaps',self.config['engines'][engine]['control_cm'],{'data':{'phase.json':json.dumps(control)}})
        self.update(ident,engine=engine,phase_deadline_epoch=deadline)
        return deadline
    def states(self,engine):
        for p in self.config['engines'][engine]['pods']:
            live=self.api.get('pods',p['metadata']['name'])
            if live and live.get('status',{}).get('phase') in ['Failed','Succeeded']:
                raise RuntimeError('rank Pod exited: '+p['metadata']['name'])
        return [self.api.read_state(n) for n in self.config['engines'][engine]['state_cms']]
    def wait_phase(self,engine,ident,deadline):
        while time.time()<deadline:
            states=self.states(engine);save(self.out/(ident+'-states.json'),states)
            failed=[s for s in states if s.get('id')==ident and s.get('status') in ['FAILED','NOT_EXECUTED']]
            if failed:
                reasons='; '.join(str(s.get('reason','')) for s in failed if s.get('reason'))
                raise RuntimeError(ident+' rank failed'+(': '+reasons if reasons else ''))
            if all(s.get('id')==ident and s.get('status')=='PASS' for s in states):return
            time.sleep(5)
        raise RuntimeError(ident+' deadline')
    def stop_workers(self,engine,ident,seconds=180):
        """Change to a hold phase and wait until every rank has stopped ident."""
        deadline=min(time.time()+seconds,self.end-180)
        control={'id':ident,'phase':'hold','commands':{},'deadline_epoch':deadline}
        save(self.out/(ident+'-control.json'),control)
        self.api.patch('configmaps',self.config['engines'][engine]['control_cm'],{'data':{'phase.json':json.dumps(control)}})
        while time.time()<deadline:
            states=self.states(engine)
            if all(s.get('id')!=ident or s.get('status')!='RUNNING' for s in states):return
            time.sleep(3)
        raise RuntimeError('serving workers did not stop after phase change')
    def wait_service(self,engine,ident,deadline):
        """Wait for the API while detecting a live process with no startup progress."""
        cfg=self.config['engines'][engine]
        stall_seconds=float(cfg.get('startup_stall_seconds',720))
        last_signature=None;last_progress=time.time()
        while time.time()<deadline:
            states=self.states(engine)
            current=[s for s in states if s.get('id')==ident]
            if any(s.get('status') in ['FAILED','PASS','NOT_EXECUTED'] for s in current):
                raise RuntimeError('serving rank exited')
            if len(current)==len(states) and all(s.get('status')=='RUNNING' for s in current):
                signature=tuple((s.get('rank'),s.get('log_bytes',0)) for s in current)
                if signature!=last_signature:
                    last_signature=signature;last_progress=time.time()
                elif time.time()-last_progress>=stall_seconds:
                    raise RuntimeError('serving startup stalled: rank logs unchanged for '+str(int(stall_seconds))+'s')
                try:
                    with urllib.request.urlopen(cfg['base_url']+'/v1/models',timeout=5) as r:models=json.load(r)
                    if self.config['model'] in [m['id'] for m in models.get('data',[])]:return
                except Exception:pass
            time.sleep(10)
        raise RuntimeError('model loading deadline')
    def engine(self,engine):
        cfg=self.config['engines'][engine]
        enabled=self.execution_policy()['enabled_engines']
        pending=max(1,sum(e not in self.status['engines'] for e in enabled))
        info=self.status['engines'][engine]={'status':'STARTING','started_at':time.time(),
              'engine_deadline_epoch':min(self.end-180,time.time()+self.remaining()/pending)}
        if any(self.api.get('pods',n) for n in self.all_names()):raise RuntimeError('previous GPU Pod remains')
        allocation_attempts=int(cfg.get('allocation_attempts',3))
        allocation_seconds=float(cfg.get('allocation_seconds',120))
        for attempt in range(1,allocation_attempts+1):
            for pod in cfg['pods']:self.api.create(pod)
            allocation_end=min(time.time()+allocation_seconds,self.end-180)
            allocated=False
            while time.time()<allocation_end:
                live=[self.api.get('pods',p['metadata']['name']) for p in cfg['pods']]
                if any(p and p.get('status',{}).get('phase')=='Failed' for p in live):
                    raise RuntimeError('GPU rank Pod failed during allocation')
                if all(p and p.get('status',{}).get('phase')=='Running' for p in live):
                    allocated=True;break
                time.sleep(5)
            if allocated:break
            recovery={'phase':'allocation','attempt':attempt,'status':'FAILED',
                      'error':'four-node allocation incomplete','at':time.time()}
            info.setdefault('recoveries',[]).append(recovery)
            # A partial 8/16/24-GPU allocation is never retained while waiting
            # for the last fixed node. Release all ranks and retry as a new
            # attempt so another workload can use the cards in the meantime.
            self.update('ALLOCATION_RETRY',engine=engine,recovery=recovery)
            self.release(engine)
            if attempt<allocation_attempts:time.sleep(min(15,self.remaining()))
        else:
            raise RuntimeError('four-node allocation incomplete after '+str(allocation_attempts)+' attempts')
        for phase,commands in cfg['checks'].items():
            max_attempts=2 if phase=='nccl-inter' else 1
            for attempt in range(1,max_attempts+1):
                ident=engine+'-'+phase+('-attempt-'+str(attempt) if max_attempts>1 else '')
                deadline=self.phase(engine,ident,commands,900)
                try:
                    self.wait_phase(engine,ident,deadline)
                    break
                except Exception as exc:
                    recovery={'phase':phase,'attempt':attempt,'status':'FAILED','error':str(exc),'at':time.time()}
                    info.setdefault('recoveries',[]).append(recovery)
                    if 'HARD_NCCL_' in str(exc) or attempt>=max_attempts:raise
                    self.update('NCCL_RETRY',engine=engine,recovery=recovery)
                    time.sleep(min(30,self.remaining()))
        serve_attempts=int(cfg.get('serve_attempts',2));ident=''
        for attempt in range(1,serve_attempts+1):
            ident=engine+'-serve-attempt-'+str(attempt)
            self.phase(engine,ident,cfg['serve'],min(cfg['engine_seconds'],self.remaining()))
            deadline=min(time.time()+cfg['startup_seconds'],info['engine_deadline_epoch'],self.end-180)
            try:
                self.wait_service(engine,ident,deadline)
                break
            except Exception as exc:
                recovery={'phase':'serve','attempt':attempt,'status':'FAILED','error':str(exc),'at':time.time()}
                info.setdefault('recoveries',[]).append(recovery)
                if attempt>=serve_attempts:raise
                self.update('SERVE_RETRY',engine=engine,recovery=recovery)
                self.stop_workers(engine,ident)
                time.sleep(min(30,self.remaining()))
        info['ready_at']=time.time()
        # UI before timed performance: bounded local automation acknowledgement, not a user gate.
        capture_end=min(time.time()+600,self.end-180)
        head=cfg['pods'][0]['metadata']['name']
        self.api.patch('pods',head,{'metadata':{'labels':{'capture':'enabled'}}})
        self.update('OPENWEBUI_CAPTURE',engine=engine,capture_deadline_epoch=capture_end)
        ui={}
        while time.time()<capture_end:
            ui=self.api.read_state(self.config['capture_cm'])
            if ui.get('run')==self.run and ui.get('engine')==engine and ui.get('status') in ['PASS','FAILED']:break
            time.sleep(5)
        self.api.patch('pods',head,{'metadata':{'labels':{'capture':None}}})
        if ui.get('status')!='PASS':time.sleep(min(180,self.remaining()))
        info['openwebui']=ui if ui.get('engine')==engine else {'status':'FAILED','reason':'capture deadline'}
        self.update('PERFORMANCE',engine=engine)
        output=self.out/'results'/engine
        cmd=[sys.executable,str(HERE/'unattended.py'),'--engine',engine,'--base-url',cfg['base_url'],
             '--output',str(output),'--samples',str(self.out/'client-samples.jsonl'),
             '--deadline-epoch',str(min(self.end-180,time.time()+cfg['suite_seconds'],info['engine_deadline_epoch'])),
             '--suite-seconds',str(cfg['suite_seconds']),'--stages',','.join(self.config['stages'])]
        info['benchmark_started_at']=time.time();save(self.out/(engine+'-suite-command.json'),cmd)
        def still_alive():
            try:
                for p in cfg['pods']:
                    live=self.api.get('pods',p['metadata']['name'])
                    if not live or live.get('status',{}).get('phase') in ['Failed','Succeeded']:return False
                return not any(s.get('id')==ident and s.get('status') in ['FAILED','PASS','NOT_EXECUTED'] for s in self.states(engine))
            except RuntimeError:return True  # unknown API state is bounded by deadlines, not proof of engine failure
        rc=run_child(cmd,self.out/(engine+'-suite.log'),min(cfg['suite_seconds']+30,self.remaining(),info['engine_deadline_epoch']-time.time()),health_check=still_alive)
        result=json.loads((output/'suite-status.json').read_text()) if (output/'suite-status.json').exists() else {}
        info.update(status=result.get('status','FAILED') if rc==0 else 'FAILED',suite_returncode=rc,benchmark_finished_at=time.time())
        info['context_ladder']=[]
        # Preserve the original native-context scope, with explicit budget outcomes.
        # Extended 512K/1M and soak are never added by this controller.
        for context in self.config.get('contexts',[65536,131072,262144]):
            row={'context':context,'status':'NOT_EXECUTED','reason':'remaining time budget'}
            info['context_ladder'].append(row)
            left=min(self.remaining(),info['engine_deadline_epoch']-time.time())
            if left<1800 or not result.get('capabilities',{}).get('basic_gate_passed'):continue
            context_id=engine+'-context-'+str(context)
            commands=json.loads(json.dumps(cfg['serve']))
            for command in commands:
                flag='--context-length' if engine=='sglang' else '--max-model-len'
                command[command.index(flag)+1]=str(context)
            self.phase(engine,context_id,commands,left)
            row.update(started_at=time.time(),reason='')
            try:
                until=min(time.time()+cfg['startup_seconds'],info['engine_deadline_epoch']-300,self.end-480)
                # Observe the NEW serving phase on every rank before accepting /models.
                while time.time()<until:
                    states=self.states(engine)
                    if any(s.get('id')==context_id and s.get('status') in ['FAILED','PASS','NOT_EXECUTED'] for s in states):raise RuntimeError('context serving exited')
                    if all(s.get('id')==context_id and s.get('status')=='RUNNING' for s in states):
                        try:
                            with urllib.request.urlopen(cfg['base_url']+'/v1/models',timeout=5) as r:models=json.load(r)
                            if self.config['model'] in [m['id'] for m in models.get('data',[])]:break
                        except Exception:pass
                    time.sleep(10)
                else:raise RuntimeError('context loading deadline')
                folder=self.out/'contexts'/engine/str(context);folder.mkdir(parents=True)
                env={**os.environ,'BASE_URL':cfg['base_url']+'/v1','MAX_CONTEXT':str(context),
                     'MAX_TOKENS':'2048','TIMEOUT':'600','OUTPUT_FILE':str(folder/'needle.json')}
                rc=run_child([sys.executable,str(HERE/'needle.py')],folder/'needle.log',min(900,self.remaining(),info['engine_deadline_epoch']-time.time()),env)
                needle=json.loads((folder/'needle.json').read_text()) if (folder/'needle.json').exists() else {}
                row.update(status='PASS' if rc==0 and needle.get('status')=='PASS' else 'FAILED',returncode=rc,finished_at=time.time())
                if rc:row['reason']='needle failure (not a performance comparison)'
            except Exception as exc:
                row.update(status='FAILED',reason=str(exc),finished_at=time.time())
                # A broken serving process cannot be silently reused at another context size.
                seen={r['context'] for r in info['context_ladder']}
                info['context_ladder'] += [{'context':c,'status':'NOT_EXECUTED','reason':'previous context serving failure'} for c in self.config.get('contexts',[65536,131072,262144]) if c not in seen]
                break
            finally:self.update('CONTEXT_LADDER',engine=engine)
        if any(r['status']!='PASS' for r in info['context_ladder']):info['status']='PARTIAL_RESULTS'
    def run_campaign(self):
        if self.remaining()<900:raise RuntimeError('insufficient explicit deadline')
        # No old campaign/fixture receipt may authorize this run's GPU allocation.
        validation=self.api.read_state(self.config['preflight_cm'])
        if validation.get('run')!=self.run or validation.get('status')!='PASS' or validation.get('bundle_sha256')!=self.config['bundle_sha256']:
            raise RuntimeError('fresh zero-GPU runtime/model/monitoring preflight required')
        thread=threading.Thread(target=self.heartbeat,daemon=True);thread.start()
        self.api.state(self.config['heartbeat_cm'],{'run':self.run,'at':time.time(),'deadline_epoch':self.end})
        exporter=subprocess.Popen([sys.executable,str(HERE/'metrics.py'),'--samples',str(self.out/'client-samples.jsonl')])
        try:
            if self.config.get('prometheus_url'):
                until=min(time.time()+120,self.end-180)
                while time.time()<until:
                    watched=self.api.read_state(self.config['watchdog_cm'])
                    try:
                        query='up{job="'+self.run+'-client"}'
                        with urllib.request.urlopen(self.config['prometheus_url']+'/api/v1/query?'+urllib.parse.urlencode({'query':query}),timeout=5) as r:values=json.load(r)['data']['result']
                        if watched.get('run')==self.run and watched.get('status')=='WATCHING' and time.time()-watched.get('at',0)<60 and values and all(float(v['value'][1])==1 for v in values):break
                    except Exception:pass
                    time.sleep(5)
                else:raise RuntimeError('watchdog/client metrics are not ready; no GPU start')
            for engine in self.config['engines']:
                try:policy=self.execution_policy()
                except Exception as exc:
                    self.status['engines'][engine]={'status':'NOT_EXECUTED','reason':'runtime execution policy unavailable: '+str(exc)}
                    self.update('ENGINE_SKIPPED',engine=engine,execution_policy='unavailable')
                    continue
                if engine not in policy['enabled_engines']:
                    self.status['engines'][engine]={'status':'NOT_EXECUTED','reason':policy.get('reason','disabled by runtime execution policy'),
                                                   'execution_policy':policy}
                    self.update('ENGINE_SKIPPED',engine=engine,execution_policy=policy)
                    continue
                if self.remaining()<900:
                    self.status['engines'][engine]={'status':'NOT_EXECUTED','reason':'global deadline'};continue
                try:self.engine(engine)
                except Exception as exc:
                    self.status['engines'].setdefault(engine,{}).update(status='FAILED',error=str(exc))
                finally:
                    # Archive failure cannot suppress cleanup. Unconfirmed cleanup blocks handover.
                    try:self.archive(engine)
                    finally:self.release(engine)
                    self.status['engines'][engine]['finished_at']=time.time()
                    self.update('ENGINE_RELEASED',engine=engine)
            self.update('GPU_PHASES_FINISHED',editorial_status='PENDING')
        finally:
            failures=[]
            for engine in self.config['engines']:
                try:self.release(engine)
                except Exception as exc:failures.append({'engine':engine,'error':str(exc)})
            self.status.update(cleanup_errors=failures,finished_at=time.time())
            self.update('PARTIAL_RESULTS' if failures or any(v['status']!='BENCHMARK_FINISHED' for v in self.status['engines'].values()) else 'MEASUREMENTS_FINISHED')
            self.stop.set()
            if not failures:self.api.state(self.config['cleanup_cm'],{'run':self.run,'status':'PASS','at':time.time()})
            # Keep metrics and hostPath accessible for bounded CPU-only collection after GPU release.
            try:time.sleep(min(600,max(0,self.end-time.time())))
            finally:exporter.terminate();exporter.wait(timeout=15)


def watchdog(config):
    api=API(config['namespace']);end=config['deadline_epoch'];start=time.time()
    while True:
        try:
            done=api.read_state(config['cleanup_cm'])
            if done.get('run')==config['run'] and done.get('status')=='PASS':return
            beat=api.read_state(config['heartbeat_cm'])
            now=time.time()
            if now<end and now-max(start,beat.get('at',0))<=600:
                api.state(config['watchdog_cm'],{'run':config['run'],'at':now,'status':'WATCHING'})
            if now>=end or now-max(start,beat.get('at',0))>600:
                errors=[]
                for cfg in config['engines'].values():
                    for pod in cfg['pods']:
                        try:api.delete_owned(pod['metadata']['name'],config['run'])
                        except Exception as exc:errors.append(str(exc))
                api.state(config['watchdog_cm'],{'run':config['run'],'at':now,'status':'RELEASE_REQUESTED','errors':errors})
                if not errors and all(api.get('pods',p['metadata']['name']) is None for e in config['engines'].values() for p in e['pods']):return
        except RuntimeError as exc:
            print(json.dumps({'at':time.time(),'watchdog_api_error':str(exc)}),flush=True)
        time.sleep(15)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('mode',choices=['controller','watchdog']);ap.add_argument('--config',default='/scripts/campaign.json')
    args=ap.parse_args();cfg=json.loads(Path(args.config).read_text())
    if args.mode=='watchdog':watchdog(cfg)
    else:
        def interrupted(signum,frame):raise KeyboardInterrupt('controller interrupted')
        signal.signal(signal.SIGTERM,interrupted)
        Campaign(cfg).run_campaign()
