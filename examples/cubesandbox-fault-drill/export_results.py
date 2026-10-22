"""Strict allow-list export of private drill records; never copy raw manifests."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
from urllib.request import build_opener, ProxyHandler

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--evidence-dir',required=True,type=Path)
p.add_argument('--output',required=True,type=Path)
a=p.parse_args()
private=a.evidence_dir/'private'
digest='b538a14c67d082b0adaa8ff574d888513abc4863c47b486b96fde4fe6ef14e83'


def state(value):
    if not value:return None
    result={k:value[k] for k in ('counter','held','pid','digest') if k in value}
    for key in ('identity','boot_id'):
        if key in value:result[key+'_tag']=hashlib.sha256(value[key].encode()).hexdigest()[:12]
    return result


def convert(row):
    phases=row.get('phases',{})
    runtime=row.get('private_runtime_identity',[{}])[0]
    policy=row.get('policy_path','l3')
    profile=row['fault']+('-'+policy if row['fault']=='egress' else '')
    fault='fault_confirmed' in phases
    status='MEASURED' if fault else 'NOT_INJECTED'
    if not fault and 'policy_baseline_not_verified' in row.get('error_private',''):status='BLOCKED_BASELINE'
    if row.get('result')=='INCOMPLETE':status='RUNNING'
    cleanup=row.get('cleanup',{})
    attempts=[]
    for item in cleanup.get('kill_attempts',[]):
        value={k:item[k] for k in ('attempt','at','ok','error_type') if k in item}
        error=item.get('error_private','')
        if 'no such host' in error:value['error_category']='dns_name_not_found'
        elif 'redis连接失败' in error:value['error_category']='redis_connection_failed'
        elif 'bridge_error' in error:value['error_category']='observer_bridge_error'
        elif 'not found' in error:value['error_category']='sandbox_not_found'
        attempts.append(value)
    result={'case':row['case'],'profile':profile,'fault':row['fault'],'attempt':row['attempt'],
      'status':status,'controller_result':row.get('result'),'injected':fault,'policy_path':policy,
      'started':row['started'],'ended':row.get('ended'),'phases':phases,
      'configuration_variant':row.get('configuration_variant','original'),
      'source_sha256':row.get('source_sha256'),
      'runtime':{'mode':runtime.get('runtime_mode'),'executable_sha256':runtime.get('executable_sha256'),
                 'components':runtime.get('component_manifest',{}).get('components',{})},
      'receipts':row.get('receipts',{}),'samples':row.get('samples',[]),
      'initial':state(row.get('initial')),'states':{k:state(v) for k,v in row.get('states',{}).items()},
      'task_recovered':row.get('original_task_recovered'),
      'recovery_mode':'explicit_snapshot' if row.get('restored_state') else 'component_restart',
      'automatic_task_recovered':row.get('automatic_task_recovered'),
      'old_runtime_processes_surviving':sum(v['same_process_alive'] for v in row.get('old_runtime_processes_after_recreate',[])) if 'old_runtime_processes_after_recreate' in row else None,
      'witness_command_ok':row.get('witness_command_ok'),
      'snapshot_state':state(row.get('snapshot_state')),'before_vmm_kill':state(row.get('before_vmm_kill')),
      'restored_state':state(row.get('restored_state')),
      'snapshot_memory_equal':row.get('snapshot_identity_counter_restored'),
      'witness_initial':state(row.get('witness_initial')),'witness_after':state(row.get('witness_after_fault')),
      'witness_identity_same':row.get('witness_identity_same'),
      'pod_uid_changed':bool(row.get('old_pod_uid') and row.get('new_pod_uid') and row['old_pod_uid']!=row['new_pod_uid']),
      'cleanup':{'remaining_sandboxes':cleanup.get('remaining_sandboxes'),'new_sandbox_exec':cleanup.get('new_sandbox_exec'),
                 'kill_attempts':attempts,'errors':[k for k in cleanup if 'error' in k]},
      'post_restore_first_good_s':round(row['first_good_after_restore']-phases['restore_issued'],3) if row.get('first_good_after_restore') and phases.get('restore_issued') else None}
    for name in ('snapshot_completed_at','snapshot_restore_started_at','snapshot_restore_completed_at'):
        if name in row:result[name]=row[name]
    if row.get('snapshot_restore_completed_at') and row.get('snapshot_restore_started_at'):
        result['snapshot_create_and_first_read_s']=round(row['snapshot_restore_completed_at']-row['snapshot_restore_started_at'],3)
    if runtime.get('executable_sha256') and runtime['executable_sha256']!=digest and 'r073' in row['case']:
        raise ValueError('runtime hash mismatch in purported upgraded run')
    return result


rows=[json.loads(f.read_text()) for f in private.glob('cube-*.json') if '-receivers' not in f.name and '-recovery' not in f.name]
rows=[r for r in rows if 'case' in r and 'fault' in r and 'started' in r]
cases=sorted((convert(r) for r in rows),key=lambda r:r['started'])
current=[r for r in cases if 'r073' in r['attempt']]
historical=[r for r in cases if 'r073' not in r['attempt']]
settings=json.loads((private/'settings.json').read_text())
opener=build_opener(ProxyHandler({}))
events=[]
for url in (settings['observer'],settings['deny_observer']):
    with opener.open(url+'/events',timeout=5) as response:
        events+=json.load(response)['events']
allowed={r['case'] for r in cases}
events=[{k:r[k] for k in ('at','case','role','target','seq','port') if k in r}
        for r in events if r['case'] in allowed or r['case'].removesuffix('-witness') in allowed]
events.sort(key=lambda r:r['at'])
for r in cases:
    for name,counts in r['receipts'].items():
        start=r['phases'].get({'baseline':'baseline','fault':'fault_confirmed','recovery':'restore_issued'}[name])
        end=r['phases'].get({'baseline':'fault_issued','fault':'restore_issued','recovery':'complete'}[name])
        if name == 'recovery' and end is None:end=r.get('ended')
        if start is not None and end is not None:
            for target in ('allow','deny'):
                actual=sum(e['case']==r['case'] and e['target']==target and start<=e['at']<end for e in events)
                if actual!=counts[target]:raise AssertionError((r['case'],name,target,actual,counts[target]))
    if r.get('snapshot_restore_started_at'):
        before={e.get('seq') for e in events if e['case']==r['case'] and e['target']=='allow' and e['at']<r['phases'].get('fault_issued',0)}
        after={e.get('seq') for e in events if e['case']==r['case'] and e['target']=='allow' and e['at']>=r['snapshot_restore_started_at']}
        repeated=sorted(int(v) for v in before & after if v and str(v).isdigit())
        r['replayed_allowed_sequence_count']=len(repeated)
        r['replayed_allowed_sequences']=repeated
followups=[]
for filename in ('manual-pod-recovery-first.json','manual-pod-recovery.json'):
    f=private/filename
    if not f.exists():continue
    value=json.loads(f.read_text())
    error=value.get('error_private','')
    followups.append({'case':value['case'],'started':value['started'],'ended':value['ended'],
      'result':value['result'],'recovery_mode':value['recovery_mode'],
      'failure_category':'snapshot_not_found' if 'snapshot not found' in error else 'no_schedulable_resource' if 'no more resource' in error else 'other',
      'remaining_sandboxes':value.get('remaining_sandboxes'),
      'memory_equal':value.get('memory_equal'),'restored_state':state(value.get('restored_state'))})
repairs=[]
for filename in ('port-map-repair-first.json','port-map-repair.json'):
    f=private/filename
    if not f.exists():continue
    value=json.loads(f.read_text())
    repairs.append({'at':value['at'],'ended':value['ended'],'live_cube_vmm_count':len(value['live_cube_vmm_pids']),
      'removed':{k:v['removed'] for k,v in value['maps'].items()},
      'remaining':{k:len(v['after']) for k,v in value['maps'].items()}})
final={}
if (private/'final-state.json').exists():
    value=json.loads((private/'final-state.json').read_text())
    final={k:value[k] for k in ('at','configuration_restored','new_sandbox_exec','console_captured','remaining_sandboxes','unrelated_vmis_original_count','unrelated_vmis_same_uid_count','unrelated_vmis_running_ready','replica_counts_restored') if k in value}
    final['failed_snapshot_cleanup']='old_replica_endpoint_unreachable' if value.get('snapshot_cleanup_error_private') else 'requested'
report={'schema_version':1,'title':'CubeSandbox component failure and recovery',
 'backend_images':'v0.7.3','verified_runtime_sha256':digest,
 'scope':'Single compute node; Pod networking; independent observer Pods share the physical node; IPv4 HTTP fresh connections.',
 'planned_profiles':['api','master','ops','proxy','cubelet','vmm','mysql','redis','minio','egress-l3','egress-l7','pod'],
 'current':current,'historical':historical,'manual_recovery_attempts':followups,'orphan_port_repairs':repairs,'final_state':final,
 'not_run':['host power loss or reboot','cross-node or cross-zone recovery','physical storage loss','IPv6 and long TCP connections'],
 'receiver_event_count':len(events)}
a.output.mkdir(parents=True,exist_ok=True)
(a.output/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
with (a.output/'receiver-events.csv').open('w',newline='') as stream:
    writer=csv.DictWriter(stream,fieldnames=['at','case','role','target','seq','port'],lineterminator='\n')
    writer.writeheader();writer.writerows(events)
print(json.dumps({'current_cases':len(current),'historical_attempts':len(historical),'receiver_events':len(events),'counts_cross_checked':True}))
