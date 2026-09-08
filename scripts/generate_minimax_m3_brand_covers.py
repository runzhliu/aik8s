#!/usr/bin/env python3
"""Keep the original M3 cover layout; use the official M3 red/orange accents."""
from pathlib import Path
import json
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'articles/wechat/assets/minimax-m3-h20/brand-cover'
BG,INK,MUTED,RED,ORANGE,LINE='#FFF8F6','#35252A','#866A70','#CF254C','#D74C26','#F1C8CA'
FONT='/System/Library/Fonts/Hiragino Sans GB.ttc'

def text(d,xy,value,size=25,color=INK):
    f=ImageFont.truetype(FONT,size);b=d.textbbox((0,0),value,font=f)
    d.text((xy[0]-b[0],xy[1]-b[1]),value,font=f,fill=color)

def center(d,box,value,size=25,color=INK):
    f=ImageFont.truetype(FONT,size);b=d.textbbox((0,0),value,font=f)
    assert b[2]-b[0]<=box[2]-box[0]
    d.text(((box[0]+box[2]-b[2]-b[0])/2,(box[1]+box[3]-b[3]-b[1])/2),value,font=f,fill=color)

def rail(d,height,width):
    # Official minimax.io M3 hero accentGradient: #FF276F -> #FF7038.
    a=(255,39,111);b=(255,112,56)
    for y in range(height):
        t=y/(height-1);c=tuple(round(x+(z-x)*t) for x,z in zip(a,b))
        d.line((0,y,width,y),fill=c)

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    im=Image.new('RGB',(900,383),BG);d=ImageDraw.Draw(im);rail(d,383,12)
    text(d,(45,36),'AI-K8S 技术工程',18,RED)
    text(d,(45,95),'MiniMax-M3',54,RED)
    text(d,(45,173),'八张 H20，怎样部署？',35)
    text(d,(45,258),'SGLang / vLLM',26,RED)
    text(d,(45,320),'模型理解 · 实测数据 · 部署取舍',20,MUTED)
    for i in range(8):
        x=626+(i%4)*57;y=107+(i//4)*87
        d.rounded_rectangle((x,y,x+46,y+65),radius=6,fill='white',outline=LINE,width=2)
        center(d,(x,y,x+46,y+65),'H20',12,RED)
    center(d,(618,284,855,317),'BF16 · TP8',22,ORANGE)
    im.save(OUT/'cover.png',optimize=True)
    im=Image.new('RGB',(900,900),BG);d=ImageDraw.Draw(im);rail(d,900,14)
    text(d,(62,66),'AI-K8S 技术工程',25,RED)
    text(d,(62,177),'MiniMax-M3',75,RED)
    text(d,(62,310),'八张 H20-3e',64)
    text(d,(62,420),'双引擎部署与实测',42)
    for i in range(8):
        x=65+(i%4)*192;y=532+(i//4)*90
        d.rounded_rectangle((x,y,x+164,y+70),radius=10,fill='white',outline=LINE,width=2)
        center(d,(x,y,x+164,y+70),'H20-3e',24,RED)
    text(d,(62,778),'SGLang / vLLM · BF16 · TP8',30,RED)
    im.save(OUT/'cover-square.png',optimize=True)
    (OUT/'palette.json').write_text(json.dumps({'source':'https://www.minimax.io/','source_scope':'M3 hero title accentGradient, not a corporate brand manual','official_m3_gradient':['#FF276F','#FF7038'],'editorial_palette':{'background':BG,'ink':INK,'muted':MUTED,'red_text':RED,'orange_text':ORANGE},'layout':'Original M3 light cover retained; only color treatment changes','article_charts':'Keep blue/orange engine comparison colors'},ensure_ascii=False,indent=2)+'\n')
    print(OUT)

if __name__=='__main__':main()
