#!/usr/bin/env python3
"""Deterministic Sleep Mode charts; inputs contain measurements, no estimates."""
import json,math,sys
from pathlib import Path
from PIL import Image,ImageDraw,ImageOps
from generate_minimax_m3_visuals_v2 import header,footer,txt,center,INK,MUTED,LINE,BLUE,ORANGE
from generate_glm53_day1_wechat_covers import LANDSCAPE_BACKGROUND,SQUARE_BACKGROUND,add_horizontal_panel,add_square_panel
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
    WECHAT.mkdir(parents=True,exist_ok=True)
    for square,source,name in [(False,LANDSCAPE_BACKGROUND,'cover.png'),(True,SQUARE_BACKGROUND,'cover-square.png')]:
        size=(900,900) if square else (900,383)
        im=ImageOps.fit(Image.open(source).convert('RGB'),size,method=Image.Resampling.LANCZOS)
        im=add_square_panel(im) if square else add_horizontal_panel(im);d=ImageDraw.Draw(im)
        x=58 if square else 46;white='#F6FAFF';muted='#BCD2EB';accent='#FFB46A'
        txt(d,x,52 if square else 34,'L20 · TWO MODELS · SLEEP / WAKE',21 if square else 15,fill=muted,latin=True)
        txt(d,x,119 if square else 86,'vLLM Sleep',68 if square else 44,fill=white,bold=True,latin=True)
        txt(d,x,213 if square else 148,'单卡双模型实测',48 if square else 32,fill=white,bold=True)
        y=310 if square else 214;w=330 if square else 259;h=58 if square else 42
        d.rounded_rectangle((x,y,x+w,y+h),h//2,fill=accent)
        center(d,(x,y,x+w,y+h),'显存 · 恢复 · DRA',27 if square else 20,fill='#542A0F',bold=True)
        txt(d,x,407 if square else 284,'从引擎恢复到设备共享',25 if square else 17,fill=muted)
        txt(d,x,475 if square else 335,'AIK8S.RUN',20 if square else 13,fill=muted,latin=True)
        im.save(WECHAT/name,optimize=True)

if __name__=='__main__':
    if '--covers-only' not in sys.argv:measured()
    covers()
