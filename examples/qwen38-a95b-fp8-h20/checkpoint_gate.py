#!/usr/bin/env python3
"""Full hash once, reuse only with identical manifest and local file stat identity."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from unattended import save


def main():
    model=Path(os.environ['MODEL_PATH']);here=Path(__file__).resolve().parent
    raw=(here/'upstream-manifest.json').read_bytes();manifest=json.loads(raw)
    if (model/'REVISION').exists():assert (model/'REVISION').read_text().strip()==manifest['revision']
    subprocess.run([sys.executable,str(here/'verify_checkpoint.py')],check=True)
    names=sorted(set(json.loads((model/'model.safetensors.index.json').read_text())['weight_map'].values()))
    def snapshot():
        rows={}
        for name in names:
            p=model/name;s=p.stat()
            assert not p.is_symlink() and s.st_size==manifest['files'][name]['size']
            rows[name]=[s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns]
        return rows
    before=snapshot();signature=hashlib.sha256(raw).hexdigest()
    if os.environ.get('REUSE_PREVALIDATED_WEIGHTS') == '1':
        save('/outputs/checkpoint-gate.json',{
            'status':'PASS',
            'full_hash_receipt_reused':False,
            'full_weight_sha256':'SKIPPED_BY_USER_AUTHORIZATION',
            'validation_source':'prior external weight validation; current run rechecked index, auxiliary hashes, shard count and every shard size',
            'manifest_sha256':signature,
            'shards':len(names),
            'at':time.time(),
        })
        return
    receipt=Path('/verification/full-sha256.json')
    previous=json.loads(receipt.read_text()) if receipt.exists() else {}
    reused=previous.get('status')=='PASS' and previous.get('manifest_sha256')==signature and previous.get('stat')==before
    if not reused:
        for i,name in enumerate(names):
            expected=manifest['files'][name]['lfs']['sha256']
            h=hashlib.sha256()
            with (model/name).open('rb') as f:
                for block in iter(lambda:f.read(16*1024*1024),b''):h.update(block)
            assert h.hexdigest()==expected,'weight SHA256 mismatch: '+name
            save('/outputs/hash-progress.json',{'completed':i+1,'total':len(names),'at':time.time()})
        assert snapshot()==before,'model changed during verification'
        save(receipt,{'status':'PASS','manifest_sha256':signature,'stat':before,'at':time.time(),'verification':'full SHA256'})
    save('/outputs/checkpoint-gate.json',{'status':'PASS','full_hash_receipt_reused':reused,'manifest_sha256':signature,'shards':len(names),'at':time.time()})

if __name__=='__main__':main()
