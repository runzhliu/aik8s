"""Bounded functional measurements against a real OpenKruise Agents lab."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time

import requests


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--context', required=True)
    parser.add_argument('--upstream',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--lifecycle-only',action='store_true')
    args=parser.parse_args()
    sys.path.insert(0,str(args.upstream/'sdk/customized_e2b'))
    from kruise_agents.patch_e2b import patch_e2b
    patch_e2b(https=False)
    from e2b import Sandbox

    report={'started_at':time.time(),'cases':[],'warm_create_seconds':[],'cold_create_seconds':[],
            'conditions':{'warm_pool_size':2,'warm_rounds':0 if args.lifecycle_only else 5,'cold_rounds':0 if args.lifecycle_only else 3,
                          'cold_image_cache':'already present on the node','pause_strategy':'Stop',
                          'sdk':'e2b 2.24.0','code_interpreter_sdk':'2.4.1'}}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    live=[]

    def save():
        args.output.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')

    def case(name,fn):
        start=time.monotonic()
        try:
            evidence=fn()
            row={'name':name,'status':'passed','seconds':time.monotonic()-start,'evidence':evidence}
        except Exception as exc:
            row={'name':name,'status':'failed','seconds':time.monotonic()-start,'error':f'{type(exc).__name__}: {exc}'}
        report['cases'].append(row);save()
        print(json.dumps(row,ensure_ascii=False),flush=True)
        return row

    def kube(*parts):
        cmd=['kubectl','--context',args.context,'-n','sandbox-system',*parts,'-o','json']
        return json.loads(subprocess.check_output(cmd,text=True,timeout=15))

    def wait_pool(count=2,timeout=60):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            obj=kube('get','sandboxset','python-tools')
            if obj.get('status',{}).get('availableReplicas',0)>=count:
                return obj['status']
            time.sleep(1)
        raise TimeoutError('warm pool did not replenish')

    def create(template='python-tools',ttl=180):
        start=time.monotonic()
        sbx=Sandbox.create(template=template,timeout=ttl,request_timeout=60)
        elapsed=time.monotonic()-start
        live.append(sbx)
        return sbx,elapsed

    def release(sbx):
        assert sbx.kill(), 'kill API returned false'
        live.remove(sbx)

    def measured_round(template,bucket):
        if template=='python-tools':wait_pool()
        sbx,elapsed=create(template)
        bucket.append(elapsed)
        result=sbx.commands.run('python -c "print(sum(range(1, 101)))"',timeout=20)
        assert result.exit_code==0 and result.stdout.strip()=='5050',(result.exit_code,result.stdout)
        sbx.files.write('/home/user/check.txt','isolated sandbox verification')
        assert sbx.files.read('/home/user/check.txt')=='isolated sandbox verification'
        evidence={'create_seconds':elapsed,'stdout':result.stdout.strip(),'file_roundtrip':True}
        release(sbx)
        return evidence

    try:
        if not args.lifecycle_only:
            for i in range(5):case(f'warm_create_command_file_delete_{i+1}',lambda:measured_round('python-tools',report['warm_create_seconds']))
            for i in range(3):case(f'cold_create_command_file_delete_{i+1}',lambda:measured_round('python-cold',report['cold_create_seconds']))

        def isolation():
            wait_pool();a,_=create();b,_=create()
            a.files.write('/home/user/tenant-marker.txt','tenant A only')
            command=b.commands.run('python -c "from pathlib import Path; print(Path(\'/home/user/tenant-marker.txt\').exists())"',timeout=20)
            assert command.exit_code==0 and command.stdout.strip()=='False'
            evidence={'different_ids':a.sandbox_id!=b.sandbox_id,'marker_visible_in_other_sandbox':False}
            assert evidence['different_ids']
            release(a);release(b);return evidence
        if not args.lifecycle_only:case('separate_sandbox_filesystems',isolation)

        def stop_resume():
            wait_pool();sbx,_=create()
            sbx.files.write('/home/user/pause-marker.txt','must not survive Stop')
            selected=kube('get','sandbox','-l','agents.kruise.io/sandbox-id='+sbx.sandbox_id)['items']
            assert len(selected)==1
            name=selected[0]['metadata']['name']
            old_uid=kube('get','pod',name)['metadata']['uid']
            start=time.monotonic();sbx.pause();pause_seconds=time.monotonic()-start
            paused=kube('get','sandbox',name)
            assert paused['status']['phase']=='Paused',paused.get('status')
            start=time.monotonic();resumed=Sandbox.connect(sbx.sandbox_id,timeout=180,request_timeout=60)
            resume_seconds=time.monotonic()-start
            new_uid=kube('get','pod',name)['metadata']['uid']
            result=resumed.commands.run('python -c "from pathlib import Path; print(Path(\'/home/user/pause-marker.txt\').exists())"',timeout=20)
            assert new_uid!=old_uid and result.exit_code==0 and result.stdout.strip()=='False'
            release(sbx)
            return {'pause_seconds':pause_seconds,'resume_seconds':resume_seconds,'same_sandbox_id':resumed.sandbox_id==sbx.sandbox_id,
                    'pod_uid_changed':True,'rootfs_marker_survived':False,'memory_checkpoint':'not_tested'}
        case('Stop_pause_resume_changes_pod_and_loses_rootfs',stop_resume)

        def ttl():
            wait_pool();sbx,_=create(ttl=30);start=time.monotonic()
            while time.monotonic()-start<65:
                response=requests.get(os.environ['E2B_API_URL']+'/sandboxes/'+sbx.sandbox_id,
                                      headers={'X-API-Key':os.environ['E2B_API_KEY']},timeout=10)
                if response.status_code==404:
                    live.remove(sbx)
                    return {'requested_timeout_seconds':30,'observed_not_found_after_seconds':time.monotonic()-start,'http_status':404}
                response.raise_for_status();time.sleep(1)
            raise TimeoutError('sandbox was not deleted by TTL deadline')
        case('TTL_reclaims_sandbox',ttl)

        def minimum_timeout():
            response=requests.post(os.environ['E2B_API_URL']+'/sandboxes',json={'templateID':'python-tools','timeout':20},
                                   headers={'X-API-Key':os.environ['E2B_API_KEY']},timeout=10)
            assert response.status_code==400,response.status_code
            return {'requested_timeout_seconds':20,'http_status':response.status_code,'response':response.json()}
        case('timeout_below_minimum_rejected',minimum_timeout)

        def auth():
            response=requests.post(os.environ['E2B_API_URL']+'/sandboxes',json={'templateID':'python-tools','timeout':30},timeout=10)
            assert response.status_code==401,response.status_code
            return {'missing_key_status':response.status_code}
        case('unauthenticated_creation_rejected',auth)
        case('warm_pool_replenished',lambda:{'available':wait_pool()['availableReplicas']})
    finally:
        errors=[]
        for sbx in live:
            try:sbx.kill()
            except Exception as exc:errors.append(str(exc))
        report['cleanup_errors']=errors
        report['finished_at']=time.time()
        report['summary']={'passed':sum(c['status']=='passed' for c in report['cases']),'failed':sum(c['status']=='failed' for c in report['cases'])}
        for label in ('warm','cold'):
            values=report[label+'_create_seconds']
            if values:report[label+'_summary']={'n':len(values),'median_seconds':statistics.median(values),'min_seconds':min(values),'max_seconds':max(values)}
        save()
        print(json.dumps(report['summary']),flush=True)
    return int(report['summary']['failed']>0 or bool(report['cleanup_errors']))


if __name__=='__main__':
    raise SystemExit(main())
