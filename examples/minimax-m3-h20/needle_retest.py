#!/usr/bin/env python3
"""Retest saved needle inputs with explicit field-extraction instructions.

Original failed attempts remain unchanged. This measures prompt sensitivity, not
an engine or model repair. The key, distractors, and insertion position are retained.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.request


def main():
    source, root = Path(os.environ['SOURCE_DIR']), Path(os.environ['RESULTS_DIR'])
    root.mkdir(parents=True, exist_ok=True)
    assert not (root/'summary.json').exists(), 'Use a fresh attempt'
    rows=[]
    files=sorted(source.glob('needle-*-request.json'))
    assert len(files)==10
    for path in files:
        data=json.loads(path.read_text())
        text=data['messages'][0]['content']
        keys=re.findall(r'\n验收密钥: ([^\n]+)\n', text)
        assert len(keys)<=1
        expected=keys[0] if keys else 'NOT_FOUND'
        old_prefix='下面是资料。只根据资料返回验收密钥对应的值；没有该信息时，只返回NOT_FOUND。'
        old_suffix='资料结束。验收密钥对应的值是什么？只输出该值，不要解释。'
        assert text.startswith(old_prefix) and text.endswith(old_suffix)
        text=text.replace(old_prefix,'<document>',1).replace(old_suffix,
            '</document>\n请从document中提取唯一一行“验收密钥:”后面的完整文本，必须原样保留字母、数字和连字符。没有这一行才返回NOT_FOUND。')
        data['messages'][0]['content']=text
        data['model']=os.environ['MODEL']
        name=path.name.removesuffix('-request.json')
        (root/path.name).write_text(json.dumps(data,ensure_ascii=False))
        start=time.monotonic()
        row={'case':name,'expected':expected,'source_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
        try:
            with urllib.request.urlopen(urllib.request.Request(os.environ['BASE_URL'].rstrip('/')+'/v1/chat/completions',
                    data=json.dumps(data).encode(),headers={'Content-Type':'application/json'}),timeout=300) as response:
                body=json.load(response)
            (root/(name+'-response.json')).write_text(json.dumps(body,ensure_ascii=False))
            answer=body['choices'][0]['message'].get('content') or ''
            row.update(status='PASS' if answer.strip()==expected else 'FAIL',answer=answer,usage=body.get('usage'))
        except Exception as exc:
            row.update(status='FAIL',error=str(exc))
        row['elapsed_s']=time.monotonic()-start
        rows.append(row)
        print(json.dumps(row,ensure_ascii=False),flush=True)
        (root/'progress.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
    summary={'model':os.environ['MODEL'],'status':'PASS' if all(r['status']=='PASS' for r in rows) else 'CHECK_FAILURES',
             'scope':'Explicit field-extraction prompt retest; original template outcomes retained separately.', 'cases':rows}
    (root/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
