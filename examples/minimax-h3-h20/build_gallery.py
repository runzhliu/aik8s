#!/usr/bin/env python3
"""Build an offline gallery for already verified local H3 media, without rewriting it."""
import argparse
import html
import json
import os
from pathlib import Path
from urllib.parse import quote

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--source', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
a = p.parse_args()
rows = []
for video in sorted(a.source.rglob('*.mp4')):
    metadata = video.with_suffix('.json')
    if not metadata.exists():
        continue
    row = json.loads(metadata.read_text())
    if not isinstance(row.get('case'), dict) or row.get('status') not in ('PASS', 'FAIL'):
        continue
    rows.append(dict(engine=row['engine'], case=row['case']['id'], sample=video.stem,
        status=row['status'], e2e_s=row.get('e2e_s'), frames=row.get('frames'),
        duration_s=row.get('duration_s'), sha256=row.get('file_sha256'),
        url=quote(os.path.relpath(video, a.output.parent)),
        json_url=quote(os.path.relpath(metadata, a.output.parent)),
        configuration=video.parent.parent.name, prompt=row['case']['prompt']))
data = json.dumps(rows, ensure_ascii=False).replace('<', '\\u003c')
document = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>MiniMax H3 本地产物</title>
<style>*{box-sizing:border-box}body{margin:0;background:#f4f7fa;color:#172e45;font:15px/1.6 system-ui,sans-serif}main{max-width:1200px;margin:32px auto;padding:0 22px}h1{font-size:30px}p{color:#60758a}video{display:block;width:100%;max-height:580px;background:#e2e9ef;border-radius:12px}.panel{padding:22px;background:white;border:1px solid #d9e4ed;border-radius:16px;margin:20px 0}input{padding:12px;border:1px solid #c7d7e2;border-radius:8px;width:100%;font:inherit}table{border-collapse:collapse;width:100%;font-size:13px}th,td{text-align:left;padding:10px;border-bottom:1px solid #e5edf3}button,a{color:#1776a0}button{border:1px solid #b8cfdd;background:white;border-radius:6px;padding:6px 12px;cursor:pointer}.scroll{overflow:auto}#detail{overflow-wrap:anywhere;white-space:pre-wrap;font-size:13px}</style>
<main><h1>MiniMax H3 · 本地音视频产物</h1><p>所有视频保持原始字节。可播放、下载并查看对应请求结果。预热、正式样本和页面验收均保留；这里的耗时不是筛选后的性能结论。</p>
<section class="panel"><video id="player" controls preload="metadata"></video><p id="detail">选择一个样本开始播放。</p></section>
<section class="panel"><input id="filter" aria-label="筛选样本" placeholder="筛选引擎、用例、配置或样本"><p id="count"></p><div class="scroll"><table><thead><tr><th>引擎 / 配置</th><th>样本</th><th>状态</th><th>帧数</th><th>耗时</th><th>文件</th></tr></thead><tbody id="rows"></tbody></table></div></section></main>
<script>const data=__DATA__;const $=id=>document.getElementById(id);
function select(row){$('player').src=row.url;$('detail').textContent=`${row.engine} · ${row.configuration} · ${row.sample}\\n${row.prompt}\\nSHA-256: ${row.sha256}`;}
function render(){const q=$('filter').value.toLowerCase();const rows=data.filter(r=>[r.engine,r.case,r.configuration,r.sample].join(' ').toLowerCase().includes(q));$('count').textContent=`显示 ${rows.length} / ${data.length} 个已回传样本`;$('rows').replaceChildren();for(const row of rows){const tr=document.createElement('tr');for(const value of [row.engine+' / '+row.configuration,row.sample,row.status,row.frames??'—',row.e2e_s?row.e2e_s.toFixed(2)+' s':'—']){const td=document.createElement('td');td.textContent=value;tr.append(td);}const td=document.createElement('td'),play=document.createElement('button');play.textContent='播放';play.onclick=()=>select(row);td.append(play);for(const [label,url] of [[' 下载 ',row.url],[' JSON ',row.json_url]]){const link=document.createElement('a');link.textContent=label;link.href=url;link.download=row.engine+'-'+row.configuration+'-'+row.sample+(url.endsWith('.json')?'.json':'.mp4');td.append(link);}tr.append(td);$('rows').append(tr);}}
$('filter').oninput=render;render();if(data.length)select(data[0]);</script></html>'''.replace('__DATA__', data)
a.output.parent.mkdir(parents=True, exist_ok=True)
a.output.write_text(document)
print(json.dumps(dict(samples=len(rows), output=str(a.output))))
