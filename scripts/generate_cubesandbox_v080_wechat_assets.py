#!/usr/bin/env python3
"""Compose approved-layout covers, a snapshot explainer and resized evidence screenshots."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps
from generate_minimax_m3_brand_covers import text, center

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'articles/wechat/assets/cubesandbox-v080-upgrade'
SRC=ROOT/'docs/assets/rag-agent/cubesandbox-v080-upgrade'
OUT.mkdir(parents=True,exist_ok=True)
BLUE='#365DB5'; INK='#263246'; MUTED='#68778A'; BG='#F7FAFF'; LINE='#CAD8EE'
for source,dest in [('01-running-sandboxes-light.png','01-running.png'),('02-fs-snapshot-light.png','02-snapshot.png'),('03-component-versions-light.png','03-versions.png')]:
    original=Image.open(SRC/source).convert('RGB')
    preview=ImageOps.contain(original,(1200,675),method=Image.Resampling.LANCZOS)
    canvas=Image.new('RGB',(1200,675),'white');canvas.paste(preview,((1200-preview.width)//2,(675-preview.height)//2));canvas.save(OUT/dest,optimize=True)

im=Image.new('RGB',(900,383),BG);d=ImageDraw.Draw(im);d.rectangle((0,0,11,383),fill=BLUE)
text(d,(45,36),'AI-K8S 技术工程',18,BLUE)
text(d,(45,94),'CubeSandbox',48,BLUE)
text(d,(45,172),'升级后，旧模板还能用吗？',31,INK)
text(d,(45,258),'v0.7.3 → v0.8.0',25,BLUE)
text(d,(45,320),'真实升级 · 快照实测 · 故障验证',19,MUTED)
d.rounded_rectangle((666,101,822,214),radius=10,fill='white',outline=LINE,width=2)
center(d,(666,101,822,214),'v0.8.0',22,BLUE)
center(d,(624,278,850,320),'Kubernetes',22,BLUE)
im.save(OUT/'cover.png',optimize=True)
im=Image.new('RGB',(900,900),BG);d=ImageDraw.Draw(im);d.rectangle((0,0,13,900),fill=BLUE)
text(d,(62,66),'AI-K8S 技术工程',25,BLUE)
text(d,(62,177),'CubeSandbox',68,BLUE)
text(d,(62,310),'升级实战',64,INK)
text(d,(62,420),'旧模板与新快照',42,INK)
d.rounded_rectangle((65,532,250,602),radius=10,fill='white',outline=LINE,width=2)
center(d,(65,532,250,602),'v0.8.0',25,BLUE)
text(d,(62,750),'Kubernetes · 快照 · 升级验证',29,BLUE)
im.save(OUT/'cover-square.png',optimize=True)

FONT='/System/Library/Fonts/Hiragino Sans GB.ttc'; LAT='/System/Library/Fonts/HelveticaNeue.ttc'
cn=lambda n:ImageFont.truetype(FONT,n,index=0)
lat=lambda n:ImageFont.truetype(LAT,n,index=7)
im=Image.new('RGB',(1200,675),'white');d=ImageDraw.Draw(im)
d.text((62,36),'两种快照，保存的状态不同',font=cn(30),fill=INK)
d.text((62,82),'Filesystem-only vs. full snapshot',font=lat(24),fill=MUTED)
d.line((65,142,1134,142),fill='#D9E2E0',width=2)
for y,title,en,items in [(195,'文件系统快照','Filesystem-only',['根文件系统 / Root filesystem','新沙箱冷启动 / Cold start','进程与内存不保留 / No process or memory']), (417,'完整快照','Full snapshot',['根文件系统 / Root filesystem','进程与内存状态 / Process and memory','支持回滚 / Rollback supported'])]:
 d.text((65,y),title,font=cn(27),fill=INK);d.text((65,y+44),en,font=lat(21),fill=MUTED)
 d.line((354,y+3,354,y+124),fill=LINE,width=2)
 for i,item in enumerate(items):d.ellipse((398,y+9+i*40,406,y+17+i*40),fill='#78998C');d.text((424,y+i*40),item,font=cn(21),fill=INK)
d.text((65,627),'外部挂载需另行处理 / External mounts need separate handling',font=cn(16),fill=MUTED)
im.save(OUT/'snapshot-modes.png',optimize=True)
