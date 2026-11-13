#!/usr/bin/env python3
"""Plot measured three-round medians for both completed runs."""
import json,statistics,sys
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
root=Path(__file__).resolve().parents[1]/'docs/assets/practices/minimax-h3-image-h20'
a=[json.loads(s) for s in (root/'groups.jsonl').read_text().splitlines() if s.strip()]
b=[json.loads(s) for s in (root/'sglang-groups.jsonl').read_text().splitlines() if s.strip()]
task=sys.argv[1] if len(sys.argv)>1 else 't2i'
if task not in ('t2i','edit'):raise ValueError('expected t2i or edit')
def read(rows,c):
 v=[r for r in rows if r['group'].startswith(f'perf-square-{task}-c{c}-r')]
 if len(v)!=3 or any(r['success']!=r['planned'] or r['planned']!=12 for r in v):raise ValueError('missing completed rounds')
 return statistics.median(r['images_per_second'] for r in v),statistics.median(r['p50_s'] for r in v)
D=[(c,read(a,c),read(b,c)) for c in ((1,2,4,8) if task=='t2i' else (1,2,4))]
H='/System/Library/Fonts/HelveticaNeue.ttc';C='/System/Library/Fonts/Hiragino Sans GB.ttc'
f=lambda n:ImageFont.truetype(H,n,index=7);cn=lambda n:ImageFont.truetype(C,n,index=0)
im=Image.new('RGB',(1200,675),'white');d=ImageDraw.Draw(im)
def mix(x,y,parts):
 for t,font,color in parts:d.text((x,y),t,font=font,fill=color);x+=d.textlength(t,font=font)
mix(60,35,[(('单卡文生图对照' if task=='t2i' else '单卡图片编辑对照'),cn(26),'#252b29'),(('  /  Text-to-image comparison' if task=='t2i' else '  /  Image-edit comparison'),f(27),'#252b29')])
mix(60,86,[('2048 × 2048 · H20-3e · ',f(18),'#78827d'),('三轮中位数',cn(17),'#78827d'),(' / median of 3 rounds',f(18),'#78827d')])
d.rectangle((810,133,824,147),fill='#a4ada9');d.text((832,128),'vLLM-Omni',font=f(19),fill='#46504b');d.rectangle((975,133,989,147),fill='#799b8c');d.text((997,128),'SGLang',font=f(19),fill='#46504b')
for panel in (0,1):
 x0=74+panel*580;x1=x0+485;top=235;bottom=555;val=max(max(row[1][panel],row[2][panel]) for row in D)*1.30
 mix(x0,165,[(('吞吐' if panel==0 else '请求耗时'),cn(20),'#333b38'),((' / images/s' if panel==0 else ' / P50 seconds'),f(20),'#333b38')])
 for tick in range(4):
  y=bottom-(bottom-top)*tick/3;d.line((x0,y,x1,y),fill='#e8ebe9');label=f'{val*tick/3:.2f}' if panel==0 else f'{val*tick/3:.0f}';d.text((x0-48,y-9),label,font=f(17),fill='#959c98')
 step=(x1-x0)/len(D)
 for i,(c,v,s) in enumerate(D):
  cx=x0+step*(i+.5)
  for j,(arr,col) in enumerate([(v,'#a4ada9'),(s,'#799b8c')]):
   value=arr[panel];x=cx+(-22 if j==0 else 22);y=bottom-(bottom-top)*value/val;d.rectangle((x-18,y,x+18,bottom),fill=col)
   label=f'{value:.3f}' if panel==0 else f'{value:.1f}';box=d.textbbox((0,0),label,font=f(18));d.text((x-(box[2]-box[0])/2,y-25),label,font=f(18),fill='#405a4f')
  label=f'C{c}';box=d.textbbox((0,0),label,font=f(18));d.text((cx-(box[2]-box[0])/2,bottom+15),label,font=f(18),fill='#58625d')
mix(60,623,[('节点与卸载策略不同；每轮 12 次请求',cn(15),'#828e87'),(' / different nodes and offload; 12 requests per round',f(16),'#828e87')])
im.save(root/('sglang-vllm-comparison.png' if task=='t2i' else 'sglang-vllm-edit-comparison.png'),optimize=True)
