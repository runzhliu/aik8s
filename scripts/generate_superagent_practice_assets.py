#!/usr/bin/env python3
"""Deterministic deployment schematic; screenshots remain separate real evidence."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parents[1]
DEST=ROOT/'docs/assets/rag-agent/deepseek-superagent-practice'
S=2;INK='#252A29';MUTED='#747D79';LINE='#D7DDDA';GREEN='#6A9D8C'
def font(size):return ImageFont.truetype('/System/Library/Fonts/HelveticaNeue.ttc',round(size*S),index=7)
def text(d,x,y,value,size=22,color=INK):
 f=font(size);b=d.textbbox((0,0),value,font=f)
 assert x*S+b[2]-b[0]<1160*S,value
 d.text((x*S-b[0],y*S-b[1]),value,font=f,fill=color)
def line(d,a,b,color=LINE,width=1):d.line(tuple(round(v*S)for p in(a,b)for v in p),fill=color,width=width*S)
def arrow(d,a,b):
 line(d,a,b,GREEN,2);x,y=b
 if a[1]==b[1]:line(d,(x-8,y-5),b,GREEN,2);line(d,(x-8,y+5),b,GREEN,2)
 else:line(d,(x-5,y-8),b,GREEN,2);line(d,(x+5,y-8),b,GREEN,2)
def box(d,x,y,title,first,second,green=False):
 d.rectangle((x*S,y*S,(x+296)*S,(y+126)*S),fill='#EFF6F2'if green else'#F6F7F6',outline=LINE,width=S)
 text(d,x+20,y+22,title,25);text(d,x+20,y+69,first,18,MUTED);text(d,x+20,y+96,second,18,MUTED)
def main():
 im=Image.new('RGB',(1200*S,675*S),'white');d=ImageDraw.Draw(im)
 text(d,56,44,'A small Kubernetes stack for reviewable work',34)
 text(d,56,106,'Custom Gitea + Mattermost adapters around the Super-agent prototype',20,MUTED)
 box(d,56,180,'Mattermost','Allowed people and channel','A thread keeps follow-ups')
 box(d,452,180,'Super-agent','Gate, Ticket and Outbox','Source cursors and receipts',True)
 box(d,848,180,'DSH workers','Two concurrent Sessions','One folder / branch per Ticket',True)
 arrow(d,(364,243),(440,243));arrow(d,(760,243),(836,243))
 box(d,56,392,'PostgreSQL','Mattermost messages','A dedicated database')
 box(d,452,392,'SQLite + volumes','Orchestrator and Sessions','Files survive Pod recreation')
 box(d,848,392,'Gitea','Separate pull requests','Human review before merge')
 for x in [204,600,996]:arrow(d,(x,319),(x,379))
 line(d,(56,565),(1144,565));text(d,56,590,'Results return to the original chat thread through the Outbox.',23)
 text(d,56,632,'Model inference is external. Session folders are not independent security sandboxes.',19,MUTED)
 DEST.mkdir(parents=True,exist_ok=True);p=DEST/'workflow.png';im.resize((1200,675),Image.Resampling.LANCZOS).save(p,optimize=True);print(p)
if __name__=='__main__':main()
