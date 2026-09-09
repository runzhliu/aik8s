#!/usr/bin/env python3
"""Draw exact measured values from the published, sanitized phase summaries."""
import json
from pathlib import Path
from PIL import Image,ImageDraw
from generate_glm53_day1_assets import font

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/assets/practices/aibrix-dsv4-observability'
BG='#F4F6F8';INK='#152538';MUTED='#657387';LINE='#D7E0E9';BLUE='#2874D8';ORANGE='#D87532'

def text(d,x,y,s,size=25,color=INK,bold=False):
    f=font(size,bold=bold,latin=s.isascii());box=d.textbbox((0,0),s,font=f)
    assert x+box[2]-box[0]<1190,s
    d.text((x-box[0],y-box[1]),s,font=f,fill=color)

def base(title,subtitle):
    im=Image.new('RGB',(1200,800),BG);d=ImageDraw.Draw(im)
    text(d,48,36,title,35,bold=True);text(d,48,94,subtitle,22,MUTED)
    return im,d

def bars(d,area,values,labels,maximum,color,unit):
    left,top,right,bottom=area
    for ratio in [0,.25,.5,.75,1]:
        y=bottom-ratio*(bottom-top);d.line((left,y,right,y),fill=LINE,width=1)
        text(d,left-65,y-9,f'{maximum*ratio:.0f}',18,MUTED)
    cell=(right-left)/len(values)
    for i,(value,label) in enumerate(zip(values,labels)):
        x=left+cell*(i+.5);y=bottom-value/maximum*(bottom-top)
        d.rounded_rectangle((x-34,y,x+34,bottom),8,fill=color)
        text(d,x-38,y-32,f'{value:.1f}',20,color,True)
        text(d,x-18,bottom+20,label,22)
    text(d,left,top-43,unit,23,MUTED)

def main():
    data=json.loads((OUT/'benchmark-summary.json').read_text());phases={s['phase']:s for s in data['phases']}
    selected=[phases['gateway-c1']]+[phases['recheck-c'+str(c)] for c in [4,16,32]]
    im,d=base('双副本吞吐与首 token 延迟','DeepSeek V4 Flash · 2 × TP8 · 16 × H20-3e · vLLM + AIBrix')
    bars(d,(110,220,565,650),[s['output_tokens_per_second'] for s in selected],['C1','C4','C16','C32'],3500,BLUE,'总输出吞吐 / token/s')
    maxlat=max(s['ttft']['p95']*1000 for s in selected);scale=max(1000,((maxlat//500)+1)*500)
    bars(d,(700,220,1155,650),[s['ttft']['p95']*1000 for s in selected],['C1','C4','C16','C32'],scale,ORANGE,'客户端 TTFT P95 / ms')
    text(d,48,730,'约 538 token 输入 / 固定 256 token 输出；C4–C32 为同档复测，单档至少 60 秒。',20,MUTED)
    im.save(OUT/'throughput-latency.png')
    im,d=base('先覆盖运行形状，再判断尾延迟','相同配置与负载 · 保留首次覆盖结果 · 对照同档复测，不能只看均值')
    for x,label,color in [(725,'首次覆盖',ORANGE),(945,'同档复测',BLUE)]:
        d.rounded_rectangle((x,145,x+20,165),4,fill=color);text(d,x+30,141,label,22)
    left,top,right,bottom=150,250,1130,650;maximum=max(phases['gateway-c'+str(c)]['ttft']['p99']*1000 for c in [4,16,32]);maximum=max(4000,((maximum//1000)+1)*1000)
    for ratio in [0,.25,.5,.75,1]:
        y=bottom-ratio*(bottom-top);d.line((left,y,right,y),fill=LINE,width=1);text(d,60,y-9,f'{maximum*ratio:.0f}',20,MUTED)
    text(d,60,205,'TTFT P99 / ms',23,MUTED)
    for i,c in enumerate([4,16,32]):
        cx=left+(right-left)*(i+.5)/3
        for j,(key,color) in enumerate([('gateway-c',ORANGE),('recheck-c',BLUE)]):
            v=phases[key+str(c)]['ttft']['p99']*1000;x=cx+(-47 if j==0 else 47);y=bottom-v/maximum*(bottom-top)
            d.rounded_rectangle((x-34,y,x+34,bottom),7,fill=color);text(d,x-38,y-34,f'{v:.1f}',21,color,True)
        text(d,cx-65,bottom+20,f'并发 {c}',24)
    text(d,48,730,'前一轮日志记录推理期间 JIT；复测是追加证据，不覆盖原始尖峰。',21,MUTED)
    im.save(OUT/'warmup-recheck.png')
    print('Wrote two measured figures to',OUT)

if __name__=='__main__':main()
