#!/usr/bin/env python3
"""Deterministic Sleep Mode charts; inputs contain measurements, no estimates."""
import json,math,sys
from pathlib import Path
from generate_minimax_m3_visuals_v2 import header,footer,txt,center,INK,MUTED,LINE,BLUE,ORANGE
from generate_vllm_sleep_brand_covers import main as generate_covers
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/assets/practices/vllm-sleep-l20'
WECHAT=ROOT/'articles/wechat/assets/vllm-sleep-l20'

def measured():
    data=json.loads((OUT/'benchmark-summary.json').read_text())
    im,d=header('恢复至首 Token：进程重启与休眠唤醒','单张 L20 · 每模型重启 2 次 / Level 1 5 次 / Level 2 3 次 · 中位数与范围',False)
    for i,m in enumerate(['A','B']):
        x=48+i*572;right=x+532;md=data['models'][m]
        d.rounded_rectangle((x,146,right,574),16,fill='white',outline=LINE)
        txt(d,x+24,166,md['name'],26,bold=True,latin=True)
        vals=[('进程重启',md['restart_warm'],'#78869B'),('Level 1',md['sleep']['1']['to_first_token_s'],ORANGE),('Level 2',md['sleep']['2']['to_first_token_s'],BLUE)]
        assert all(v.get('n',0)>0 for _,v,_ in vals),'A failed stage needs a separately labeled chart'
        maximum=max(v['max'] for _,v,_ in vals)*1.25;tick=10**math.floor(math.log10(maximum));step=tick/2 if maximum/tick<2 else tick;maximum=math.ceil(maximum/step)*step
        left=x+62;bottom=500;top=254
        txt(d,x+24,211,'秒 · 越低越好',20,fill=MUTED)
        for j in range(5):
            value=maximum*j/4;y=bottom-value/maximum*(bottom-top)
            d.line((left,y,right-20,y),fill=LINE)
            center(d,(x+8,y-12,left-8,y+12),f'{value:g}',18,fill=MUTED)
        for j,(label,v,color) in enumerate(vals):
            xx=left+65+j*128;y=bottom-v['median']/maximum*(bottom-top)
            d.rounded_rectangle((xx-25,y,xx+25,bottom),5,fill=color)
            lo=bottom-v['min']/maximum*(bottom-top);hi=bottom-v['max']/maximum*(bottom-top)
            d.line((xx,hi,xx,lo),fill=INK,width=2)
            for yy in [lo,hi]:d.line((xx-7,yy,xx+7,yy),fill=INK,width=2)
            center(d,(xx-55,hi-36,xx+55,hi-6),f"{v['median']:.2f}",25,fill=color,bold=True)
            center(d,(xx-60,516,xx+60,551),label,22)
    footer(d,'同一 Pod 内进程重启，已缓存镜像与编译产物；两个模型分别使用自己的纵轴')
    im.save(OUT/'restart-vs-wake.png',optimize=True)

def covers():
    generate_covers()

if __name__=='__main__':
    if '--covers-only' not in sys.argv:measured()
    covers()
