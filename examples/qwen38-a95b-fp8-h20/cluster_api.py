"""Small stdlib Kubernetes client; credentials never enter saved evidence."""
import json
import os
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path

class API:
    def __init__(self, namespace=None):
        namespace=namespace or os.environ.get('POD_NAMESPACE', 'default')
        self.namespace=namespace
        self.sa=Path('/var/run/secrets/kubernetes.io/serviceaccount')
        self.context=ssl.create_default_context(cafile=str(self.sa/'ca.crt'))
        self.base='/api/v1/namespaces/'+namespace
    def call(self, path, method='GET', data=None, raw=False):
        for attempt in range(3):
            req=urllib.request.Request('https://kubernetes.default.svc'+path,method=method,
                headers={'Authorization':'Bearer '+(self.sa/'token').read_text().strip(),
                         'Content-Type':'application/merge-patch+json' if method=='PATCH' else 'application/json'},
                data=json.dumps(data).encode() if data is not None else None)
            try:
                with urllib.request.urlopen(req,context=self.context,timeout=15) as response:body=response.read()
                return body.decode(errors='replace') if raw else json.loads(body)
            except urllib.error.HTTPError as exc:
                if exc.code==404 and method in ['GET','DELETE']: return None
                if exc.code not in [429,500,502,503,504] or attempt==2:raise RuntimeError(f'Kubernetes HTTP {exc.code}: {method} {path}') from None
            except (urllib.error.URLError,TimeoutError):
                if attempt==2:raise RuntimeError('Kubernetes API unavailable') from None
            if method=='POST':raise RuntimeError('Create result uncertain; reconcile named object before retry')
            time.sleep(2**attempt)
    def get(self, kind, name):return self.call(f'{self.base}/{kind}/{name}')
    def patch(self,kind,name,data):return self.call(f'{self.base}/{kind}/{name}','PATCH',data)
    def state(self,name,value):return self.patch('configmaps',name,{'data':{'state.json':json.dumps(value)}})
    def read_state(self,name):
        obj=self.get('configmaps',name)
        return json.loads(obj.get('data',{}).get('state.json','{}')) if obj else {}
    def create(self,obj):
        kind={'Pod':'pods','ConfigMap':'configmaps'}[obj['kind']]
        existing=self.get(kind,obj['metadata']['name'])
        if existing is not None:raise RuntimeError('Refusing to reuse existing '+obj['metadata']['name'])
        try:return self.call(f'{self.base}/{kind}','POST',obj)
        except RuntimeError:
            # No second POST. A committed but unacknowledged creation is reconciled.
            found=self.get(kind,obj['metadata']['name'])
            if found and all(found['metadata'].get('labels',{}).get(k)==v for k,v in obj['metadata'].get('labels',{}).items()):return found
            raise
    def delete_owned(self,name,run):
        obj=self.get('pods',name)
        if not obj:return
        if obj['metadata'].get('labels',{}).get('aik8s-run')!=run:raise RuntimeError('Pod ownership mismatch')
        return self.call(f'{self.base}/pods/{name}','DELETE',{'preconditions':{'uid':obj['metadata']['uid']},'gracePeriodSeconds':30})
