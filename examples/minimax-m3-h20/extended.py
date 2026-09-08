#!/usr/bin/env python3
"""Functional edge cases and tokenizer-measured needle retrieval, no external tools."""
import json
import os
from pathlib import Path
import random
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

from transformers import AutoTokenizer


def main():
    root = Path(os.environ['RESULTS_DIR'])
    root.mkdir(parents=True, exist_ok=True)
    assert not (root / 'summary.json').exists(), 'Use a fresh attempt'
    base, model = os.environ['BASE_URL'].rstrip('/'), os.environ['MODEL']
    rows = []
    def payload(prompt, **kwargs):
        return {'model': model, 'messages': [{'role': 'user', 'content': prompt}],
                'temperature': 0, 'max_tokens': 256,
                'chat_template_kwargs': {'thinking_mode': 'disabled'}, **kwargs}
    def call(name, data, check, expected=200):
        if (root.parent / 'PAUSE').exists():
            raise RuntimeError('Paused')
        (root / f'{name}-request.json').write_text(json.dumps(data, ensure_ascii=False))
        start = time.monotonic()
        row = {'case': name}
        try:
            request = urllib.request.Request(base+'/v1/chat/completions',
                data=json.dumps(data).encode(), headers={'Content-Type': 'application/json'})
            try:
                with urllib.request.urlopen(request, timeout=300) as response:
                    status, raw = response.status, response.read().decode()
            except urllib.error.HTTPError as exc:
                status, raw = exc.code, exc.read().decode()
            (root / f'{name}-response.json').write_text(raw)
            body = json.loads(raw)
            ok = status in (expected if isinstance(expected, tuple) else (expected,)) and check(body)
            row.update(status='PASS' if ok else 'FAIL', http_status=status,
                       usage=body.get('usage'))
        except Exception as exc:
            row.update(status='FAIL', error=str(exc))
        row['elapsed_s'] = time.monotonic()-start
        rows.append(row)
        (root / 'progress.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2))
        print(json.dumps(row), flush=True)
    def content(body):
        return body['choices'][0]['message'].get('content') or ''

    weather = {'type': 'function', 'function': {'name': 'get_weather',
        'description': '查询指定城市天气', 'parameters': {'type': 'object',
        'properties': {'city': {'type': 'string'}}, 'required': ['city']}}}
    def two_cities(body):
        calls = body['choices'][0]['message'].get('tool_calls', [])
        cities = [json.loads(c['function']['arguments']).get('city', '').lower()
                  for c in calls if c['function']['name'] == 'get_weather']
        return (any('广州' in c or 'guangzhou' in c for c in cities)
                and any('北京' in c or 'beijing' in c for c in cities))
    call('parallel-tools', payload('请在本轮同时调用 get_weather 查询广州和北京的天气，不要猜测结果。',
         tools=[weather], tool_choice='auto', parallel_tool_calls=True), two_cities)
    event = {'type': 'function', 'function': {'name': 'create_event', 'description': '创建会议',
        'parameters': {'type': 'object', 'properties': {
            'start': {'type': 'string'}, 'participants': {'type': 'array', 'items': {'type': 'string'}},
            'location': {'type': 'object', 'properties': {'room': {'type': 'string'}, 'floor': {'type': 'integer'}},
                         'required': ['room', 'floor']}}, 'required': ['start', 'participants', 'location']}}}
    def nested(body):
        calls = body['choices'][0]['message'].get('tool_calls', [])
        if not calls or calls[0]['function']['name'] != 'create_event': return False
        args = json.loads(calls[0]['function']['arguments'])
        return (args['start'].startswith('2026-01-02T10:00') and set(args['participants']) == {'alice', 'bob'}
                and args['location'] == {'room': 'R2', 'floor': 3})
    call('nested-tool', payload('当前日期是2026年1月1日，时区为Asia/Shanghai。调用工具创建明天上午10点的会议，参会人为alice和bob，地点三楼R2。start使用ISO8601。',
         tools=[event], tool_choice='auto'), nested)
    call('json-output', payload('仅返回JSON对象，name为test，count为3，tags为数组a和b。',
         response_format={'type': 'json_object'}),
         lambda b: json.loads(content(b)) == {'name': 'test', 'count': 3, 'tags': ['a', 'b']})
    def verify_code(body):
        raw = content(body)
        blocks = re.findall(r'```(?:python)?\s*\n(.*?)```', raw, re.S)
        code = blocks[0] if blocks else raw
        (root/'generated-function.py').write_text(code)
        # Restricted AST plus isolated interpreter, empty environment, and resource
        # limits. No imports, attributes, file/network APIs, or arbitrary builtins.
        program = '''import ast,json,resource,sys
resource.setrlimit(resource.RLIMIT_CPU,(2,2))
resource.setrlimit(resource.RLIMIT_AS,(128*1024*1024,128*1024*1024))
code=sys.stdin.read();tree=ast.parse(code)
allowed=(ast.Module,ast.FunctionDef,ast.arguments,ast.arg,ast.Return,ast.Call,ast.Name,ast.Load,ast.Constant,ast.Expr,ast.List,ast.Tuple,ast.Subscript)
for node in ast.walk(tree):
 assert isinstance(node,allowed),type(node).__name__
 if isinstance(node,ast.Name):assert not node.id.startswith('_')
 if isinstance(node,ast.Call):assert isinstance(node.func,ast.Name) and node.func.id in ('sorted','set','list')
assert len(tree.body)==1 and isinstance(tree.body[0],ast.FunctionDef)
scope={'__builtins__':{'sorted':sorted,'set':set,'list':list,'int':int}}
exec(compile(tree,'generated','exec'),scope)
f=scope['unique_sorted']
for x,y in [([],[]),([3,1,3,2],[1,2,3]),([-2,0,-2,4],[-2,0,4])]:assert f(x)==y
print('CODE_ASSERTIONS_PASS')
'''
        result = subprocess.run([sys.executable, '-I', '-S', '-c', program], input=code,
                                capture_output=True, text=True, timeout=5, env={})
        (root/'code-verification.json').write_text(json.dumps({'returncode': result.returncode,
             'stdout': result.stdout, 'stderr': result.stderr}))
        return result.returncode == 0 and 'CODE_ASSERTIONS_PASS' in result.stdout
    call('code-sandbox', payload('编写Python函数unique_sorted(values)，输入整数列表，返回升序去重后的新列表，不修改原列表。只给一个函数的代码，不要导入模块，不要解释。'), verify_code)
    call('bad-image', payload([{'type': 'text', 'text': '描述图片'},
         {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,bm90LWFuLWltYWdl'}}]),
         lambda b: True, expected=(400, 422))
    call('bad-video', payload([{'type': 'text', 'text': '描述视频'},
         {'type': 'video_url', 'video_url': {'url': 'data:video/mp4;base64,bm90LWEtdmlkZW8='}}]),
         lambda b: True, expected=(400, 422))
    same_prompt = '一个仓库有240件货物，先发走15%，又入库36件，现在有多少件？只输出最终整数，不要解释。'
    for mode in ['disabled', 'adaptive', 'enabled']:
        for repeat in range(1, 4):
            name = f'same-prompt-{mode}-r{repeat}'
            call(name, payload(same_prompt, max_tokens=1024,
                 chat_template_kwargs={'thinking_mode': mode}), lambda b: content(b).strip() == '240')
            if rows[-1]['status'] == 'PASS':
                body = json.loads((root/f'{name}-response.json').read_text())
                message = body['choices'][0]['message']
                reasoning = message.get('reasoning') or message.get('reasoning_content') or ''
                rows[-1]['has_reasoning'] = bool(reasoning)
                if (mode == 'disabled' and reasoning) or (mode == 'enabled' and not reasoning):
                    rows[-1]['status'] = 'FAIL'
            rows[-1]['scope'] = 'Three real chat samples per mode, includes first-use effects; not the fixed-length performance baseline.'
    # Source text is deterministic synthetic material, not user documents.
    tokenizer = AutoTokenizer.from_pretrained(os.environ['TOKENIZER'], trust_remote_code=True, local_files_only=True)
    randomizer = random.Random(92731)
    filler = '\n'.join(f'资料行{i}: 仓库检查记录编号{randomizer.randrange(10000,99999)}，物料已经完成常规盘点。'
                       for i in range(6000))
    filler_ids = tokenizer.encode(filler, add_special_tokens=False)
    budget = int(os.environ.get('MAX_CONTEXT', '32768'))
    target = budget-1024
    prefix = '下面是资料。只根据资料返回验收密钥对应的值；没有该信息时，只返回NOT_FOUND。\n'
    suffix = '\n资料结束。验收密钥对应的值是什么？只输出该值，不要解释。'
    for position in (.1, .5, .9):
        for repeat in range(1, 4):
            key = f'jade-{int(position*100)}-{repeat}-{randomizer.randrange(100000,999999)}'
            cut = int(target*position)
            text = prefix+tokenizer.decode(filler_ids[:cut])+'\n验收密钥: '+key+'\n'+tokenizer.decode(filler_ids[cut:target])+suffix
            count = len(tokenizer.encode(text, add_special_tokens=False))
            assert count+256+128 < budget, (count, budget)
            name = f'needle-{budget}-p{int(position*100)}-r{repeat}'
            call(name, payload(text), lambda b, k=key: content(b).strip() == k)
            rows[-1]['input_text_tokens_without_template'] = count
    call(f'needle-{budget}-absent', payload(prefix+tokenizer.decode(filler_ids[:target])+suffix),
         lambda b: content(b).strip() == 'NOT_FOUND')
    call('over-context', payload(tokenizer.decode(filler_ids[:budget+1024])),
         lambda b: True, expected=(400, 422))
    # Observe client disconnect and recovery separately from server-side abort proof.
    try:
        data = payload('从1开始依次列出整数，持续写到10000。', max_tokens=2048, stream=True)
        req = urllib.request.Request(base+'/v1/chat/completions', data=json.dumps(data).encode(),
                                     headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=120) as response:
            lines = []
            for line in response:
                lines.append(line.decode())
                if b'content' in line and len(lines) >= 3:
                    break
        (root/'disconnect-prefix.sse').write_text(''.join(lines))
        rows.append({'case': 'client-disconnect', 'status': 'PASS',
                     'scope': 'Client closed stream; server abort and resource recovery require server telemetry.'})
    except Exception as exc:
        rows.append({'case': 'client-disconnect', 'status': 'FAIL', 'error': str(exc)})
    call('recovery-after-errors', payload('计算6乘7，只给数字。'), lambda b: content(b).strip() == '42')
    summary = {'model': model, 'status': 'PASS' if all(r['status']=='PASS' for r in rows) else 'CHECK_FAILURES',
               'cases': rows, 'context_window': budget,
               'scope': 'Small functional samples; does not establish benchmark accuracy or capacity beyond configured window.'}
    (root / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps({'status': summary['status'], 'cases': len(rows)}), flush=True)


if __name__ == '__main__':
    main()
