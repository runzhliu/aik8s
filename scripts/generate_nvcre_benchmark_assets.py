# -*- coding: utf-8 -*-
"""Plot sanitized measured NCCL results, using the established M3 article style."""
import csv,math,statistics
from pathlib import Path
from shutil import copyfile
from PIL import Image,ImageDraw
from generate_nvcre_article_assets import canvas,text,center,font,BG,INK,MUTED,LINE,BLUE,ORANGE
ROOT=Path(__file__).resolve().parents[1];PUBLIC=ROOT/'docs/assets/nvcre';WECHAT=ROOT/'articles/wechat/assets/nvcre/v1'

def draw_comparison():
 rows=list(csv.DictReader((PUBLIC/'nccl-measurements.csv').open()));series={}
 for scenario in ['dual-roce','dual-tcp']:
  group={}
  for r in rows:
   if r['scenario']==scenario and r['collective']=='all_reduce':group.setdefault(int(r['message_bytes']),[]).append(r)
  assert len(group)==10
  series[scenario]=[(size,statistics.median(float(r['busbw_gbs']) for r in rounds),statistics.median(float(r['latency_us'])/1000 for r in rounds)) for size,rounds in sorted(group.items())]
 im,d=canvas('双机 AllReduce：RoCE 与 TCP 的差距','2 × 8 H20-3e · Float · Out-of-place · 各 3 轮中位数 · 横纵轴均为对数刻度')
 for i,(label,unit,field) in enumerate([('Bus Bandwidth','GB/s',1),('集合操作耗时','ms',2)]):
  box=(48+i*576,148,576+i*576,576);d.rounded_rectangle(box,radius=16,fill='white',outline=LINE,width=2)
  text(d,box[0]+22,170,label,26,bold=True);text(d,box[0]+22,208,unit,20,MUTED,latin=True)
  x0=box[0]+76;x1=box[2]-24;y0=260;y1=498
  def xx(size):return x0+(math.log2(size)-12)/18*(x1-x0)
  def yy(v):return y1-(math.log10(v)+2)/5*(y1-y0)
  for value in [.01,.1,1,10,100,1000]:
   y=yy(value);d.line((x0,y,x1,y),fill='#EDF0F6',width=1);f=font(18,latin=True);s=f'{value:g}';b=d.textbbox((0,0),s,font=f);d.text((x0-10-(b[2]-b[0]),y-9),s,font=f,fill=MUTED)
  for size in [4096,1048576,1073741824]:
   x=xx(size);d.line((x,y0,x,y1),fill='#F1F3F8',width=1)
   label={4096:'4 KiB',1048576:'1 MiB',1073741824:'1 GiB'}[size]
   # Keep endpoint labels inside the plot card, even at mobile width.
   center(d,(x-45,510,x+45,538),label,18,MUTED,latin=True)
  for scen,color in [('dual-roce',BLUE),('dual-tcp',ORANGE)]:
   points=[(xx(size),yy(item[field])) for item in series[scen] for size in [item[0]]];d.line(points,fill=color,width=3)
   for x,y in points:d.ellipse((x-4,y-4,x+4,y+4),fill=color)
   value=series[scen][-1][field];label=f'{value:.1f}' if value>=10 else f'{value:.2f}'
   x,y=points[-1];f=font(22,bold=True,latin=True);b=d.textbbox((0,0),label,font=f);d.text((x-(b[2]-b[0])-10,y-26),label,font=f,fill=color)
  for offset,label,color in [(0,'RoCE / GDRDMA',BLUE),(254,'Socket / TCP',ORANGE)]:
   x=box[0]+24+offset;d.line((x,555,x+24,555),fill=color,width=3);text(d,x+32,545,label,19,color,latin=True)
 d.rounded_rectangle((48,601,1152,646),radius=12,fill='white',outline=LINE)
 center(d,(58,601,1142,646),'RoCE：8 个 RDMA 设备；TCP：eth0 普通 Pod 网卡。结果是完整路径的对照。',21,MUTED)
 im.save(PUBLIC/'roce-tcp-comparison.png',optimize=True);copyfile(PUBLIC/'roce-tcp-comparison.png',WECHAT/'roce-tcp-comparison.png')


def frame_evidence():
 import hashlib,json
 from generate_nvcre_article_assets import footer,save
 for fig in json.loads((PUBLIC/'evidence/layout.json').read_text()):
  source=PUBLIC/'evidence'/fig['source'];assert hashlib.sha256(source.read_bytes()).hexdigest()==fig['source_sha256']
  im,d=canvas(fig['title'],fig['subtitle']);raw=Image.open(source).convert('RGB');scale=min(1104/raw.width,420/raw.height);raw=raw.resize((round(raw.width*scale),round(raw.height*scale)),Image.Resampling.LANCZOS);im.paste(raw,((1200-raw.width)//2,155+(420-raw.height)//2));footer(d,fig['note']);save(im,fig['dest'])

if __name__=='__main__':
 draw_comparison()
 frame_evidence()
