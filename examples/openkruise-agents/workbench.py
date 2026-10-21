"""Local SDK demonstration UI. This is not an official OpenKruise Console."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

HTML='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>OpenKruise Agents · SDK 实验工作台</title>
<style>*{box-sizing:border-box}body{margin:0;background:#f4f7fc;color:#1c2941;font:16px -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif}main{max-width:1160px;margin:18px auto;padding:0 20px}header{display:flex;justify-content:space-between;align-items:center}h1{font-size:27px;margin:0 0 8px}p{color:#68788f;margin:7px 0}.tag{font-size:13px;background:#edf1ff;color:#4a5ccc;padding:7px 12px;border-radius:18px}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin:22px 0}.card,.box{background:white;border:1px solid #dfe6f2;border-radius:12px;padding:18px}.stat{font-size:30px;color:#3852da;margin-top:9px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}h2{font-size:18px;margin:0 0 14px}textarea{width:100%;height:210px;resize:vertical;border:1px solid #dde5f0;border-radius:8px;padding:13px;font:14px/1.55 ui-monospace,monospace;color:#253348;background:#fafcff}button{border:0;border-radius:7px;padding:12px 20px;background:#435de0;color:white;font-size:15px;cursor:pointer;margin-top:14px}button:disabled{opacity:.5}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f7f9fd;border:1px solid #e5eaf3;border-radius:8px;padding:14px;font:14px/1.55 ui-monospace,monospace;min-height:150px}.note{font-size:13px}.steps{display:flex;gap:12px;margin:15px 0;font-size:14px;color:#4a617d}#status{color:#28886c}.small{font-size:14px;margin:12px 0 0}.resultline{font-size:14px;line-height:1.8;color:#465d7e}</style>
<main><header><div><h1>OpenKruise Agents · SDK 实验工作台</h1><p>领取预热沙箱 → 执行 Python → 读取输出 → 删除沙箱并补池</p></div><span class="tag">v0.6.0 · Kubernetes 实测</span></header>
<div class="stats"><div class="card">预热池可用<div class="stat" id="available">—</div></div><div class="card">池目标副本<div class="stat" id="desired">—</div></div><div class="card">本页执行成功<div class="stat" id="runs">0</div></div><div class="card">最近领取耗时<div class="stat" id="latency">—</div></div></div>
<div class="grid"><section class="box"><h2>提交任务：一段真实运行的 Python</h2><textarea id="code" spellcheck="false">import csv, io, json
csv_data = "region,sales\\nEast,120\\nWest,95\\nEast,80\\nNorth,60"
totals = {}
for row in csv.DictReader(io.StringIO(csv_data)):
    totals[row["region"]] = totals.get(row["region"], 0) + int(row["sales"])
print(json.dumps({"sales_by_region": totals, "total": sum(totals.values())}, indent=2))</textarea><button id="run">领取沙箱并运行</button><p class="small" id="status">就绪：任务通过 E2B SDK 提交到实际沙箱</p></section>
<section class="box"><h2>执行结果</h2><div class="steps"><span>1. Claim</span><span>→ 2. Write file</span><span>→ 3. Execute</span><span>→ 4. Kill</span></div><pre id="output">点击左侧按钮提交任务。</pre><div class="resultline" id="detail">任务完成后显示 Sandbox ID、退出码和回收结果。</div></section></div>
<p class="note">本文配套 SDK 演示界面，非官方控制台。API Key 仅由本地后端读取；浏览器不持有管理凭据。</p></main>
<script>async function refresh(){try{let s=await(await fetch('/api/state')).json();document.getElementById('available').textContent=s.available;document.getElementById('desired').textContent=s.desired;document.getElementById('runs').textContent=s.successful_runs;if(s.last){document.getElementById('latency').textContent=s.last.create_ms.toFixed(1)+' ms'}}catch(e){document.getElementById('status').textContent='状态读取失败：'+e.message}}
document.getElementById('run').onclick=async()=>{let b=document.getElementById('run');b.disabled=true;document.getElementById('status').textContent='执行中：领取 → 写入文件 → 执行 → 回收';try{let response=await fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code:document.getElementById('code').value})});let r=await response.json();if(!response.ok)throw Error(r.error);document.getElementById('output').textContent=r.stdout+(r.stderr?'\\nSTDERR: '+r.stderr:'');document.getElementById('detail').textContent='Sandbox ID: '+r.sandbox_id+' · Exit: '+r.exit_code+'\\n领取 '+r.create_ms.toFixed(1)+' ms · 执行 '+r.execute_ms.toFixed(1)+' ms · 已回收 '+r.deleted;document.getElementById('status').textContent=r.exit_code===0?'执行成功，沙箱已回收':'任务执行失败，沙箱已回收'}catch(e){document.getElementById('status').textContent='失败：'+e.message}finally{b.disabled=false;refresh()}};refresh();setInterval(refresh,3000)</script></html>'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--upstream',type=Path,required=True)
    parser.add_argument('--context',required=True)
    parser.add_argument('--port',type=int,default=18890)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    sys.path.insert(0,str(args.upstream/'sdk/customized_e2b'))
    from kruise_agents.patch_e2b import patch_e2b
    patch_e2b(https=False)
    from e2b import Sandbox
    lock=threading.Lock();history=[]

    class Handler(BaseHTTPRequestHandler):
        def send(self,data,status=200,kind='application/json'):
            payload=data.encode() if isinstance(data,str) else json.dumps(data,ensure_ascii=False).encode()
            self.send_response(status);self.send_header('Content-Type',kind+'; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)

        def do_GET(self):
            if self.path=='/':return self.send(HTML,kind='text/html')
            if self.path=='/api/state':
                try:
                    pool=json.loads(subprocess.check_output(['kubectl','--context',args.context,'-n','sandbox-system','get','sbs','python-tools','-o','json'],text=True,timeout=10))
                    return self.send({'available':pool.get('status',{}).get('availableReplicas',0),'desired':pool['spec']['replicas'],
                                      'successful_runs':sum(r['exit_code']==0 for r in history),'last':history[-1] if history else None})
                except Exception as exc:return self.send({'error':str(exc)},503)
            return self.send({'error':'not found'},404)

        def do_POST(self):
            if self.path!='/api/run':return self.send({'error':'not found'},404)
            if self.headers.get('Origin') not in (None,f'http://127.0.0.1:{args.port}',f'http://localhost:{args.port}'):
                return self.send({'error':'origin not allowed'},403)
            size=int(self.headers.get('Content-Length','0'))
            if size>16384:return self.send({'error':'request too large'},413)
            if not lock.acquire(blocking=False):return self.send({'error':'a task is already running'},409)
            sbx=None
            try:
                code=json.loads(self.rfile.read(size))['code']
                if not isinstance(code,str) or len(code)>12000:raise ValueError('invalid code')
                start=time.monotonic();sbx=Sandbox.create(template='python-tools',timeout=120,request_timeout=40)
                create_ms=(time.monotonic()-start)*1000
                sbx.files.write('/home/user/task.py',code)
                start=time.monotonic();result=sbx.commands.run('python /home/user/task.py',timeout=20)
                row={'sandbox_id':sbx.sandbox_id,'create_ms':create_ms,'execute_ms':(time.monotonic()-start)*1000,
                     'exit_code':result.exit_code,'stdout':result.stdout[:8192],'stderr':result.stderr[:8192],'deleted':bool(sbx.kill()),'at':time.time()}
                sbx=None;history.append(row);args.output.write_text(json.dumps(history,indent=2,ensure_ascii=False));self.send(row)
            except Exception as exc:self.send({'error':f'{type(exc).__name__}: {exc}'},500)
            finally:
                if sbx is not None:
                    try:sbx.kill()
                    except Exception as exc:print('Cleanup failed:',type(exc).__name__,flush=True)
                lock.release()

        def log_message(self,format,*values):
            print(self.command,self.path,flush=True)

    print(f'Open http://127.0.0.1:{args.port}/ (SDK lab UI, not an official Console)',flush=True)
    ThreadingHTTPServer(('127.0.0.1',args.port),Handler).serve_forever()


if __name__=='__main__':main()
