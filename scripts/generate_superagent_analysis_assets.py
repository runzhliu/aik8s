#!/usr/bin/env python3
"""Public explanatory diagrams, not experiment evidence; shared English labels.

Sources: deepseek-ai/dsh-superagent-prototype at
6337fc823ce20251c8de8085948165c81aaa701e, docs/001-domain.md,
docs/003-execution.md and docs/007-architecture.md.
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'docs/assets/rag-agent/deepseek-superagent'
S = 2
INK = '#252A29'
MUTED = '#747D79'
LINE = '#D7DDDA'
GREEN = '#6A9D8C'

def font(size, light=True):
    return ImageFont.truetype('/System/Library/Fonts/HelveticaNeue.ttc', round(size*S), index=7 if light else 0)

def text(d, x, y, value, size=23, color=INK):
    f=font(size);b=d.textbbox((0,0),value,font=f)
    assert x*S+b[2]-b[0] <= 1155*S, value
    assert y*S+b[3]-b[1] <= 660*S, value
    d.text((round(x*S)-b[0],round(y*S)-b[1]),value,font=f,fill=color)

def line(d, start, end, color=LINE, width=1):
    d.line(tuple(round(v*S) for p in (start,end) for v in p), fill=color, width=round(width*S))

def arrow(d, start, end):
    line(d,start,end,GREEN,2)
    x,y=end;dx=1 if end[0]>start[0] else -1 if end[0]<start[0] else 0;dy=1 if end[1]>start[1] else -1 if end[1]<start[1] else 0
    for n in [-1,1]:
        tip=(x-dx*8+n*dy*5,y-dy*8+n*dx*5);line(d,end,tip,GREEN,2)

def base(title, sub):
    im=Image.new('RGB',(1200*S,675*S),'white');d=ImageDraw.Draw(im)
    text(d,56,44,title,36);text(d,56,103,sub,20,MUTED)
    return im,d

def box(d,x,y,title,body,green=False):
    d.rectangle((x*S,y*S,(x+296)*S,(y+128)*S),fill='#F2F7F4' if green else '#F6F7F6',outline=LINE,width=S)
    text(d,x+20,y+24,title,26)
    for i,value in enumerate(body):text(d,x+20,y+69+i*27,value,18,MUTED)

def architecture():
    im,d=base('From an event to authorized work','An event-driven team workflow, built as a DeepSeek Harness bundle')
    box(d,56,184,'Source events',['GitHub; optional Feishu','Issue, comment, CI update'])
    box(d,452,184,'Gate + Eval',['Policy checks the sender','Model assesses the request'])
    box(d,848,184,'Ticket + Mandate',['Work item and scope','Assignment selects executor'],True)
    arrow(d,(364,248),(440,248));arrow(d,(760,248),(836,248));arrow(d,(996,324),(996,380))
    box(d,848,392,'DSH Executor',['One Session per Ticket','Directory / git worktree'],True)
    box(d,452,392,'Outbox + Channel',['Persist, send, retry','Reply in original context'])
    box(d,56,392,'Reviewable result',['Pull request or answer','Human decision when needed'])
    arrow(d,(836,456),(760,456));arrow(d,(440,456),(364,456))
    line(d,(56,564),(1144,564));text(d,56,588,'SQLite records + durable effects support dispatch and recovery.',23)
    text(d,56,630,'Subscribed messages add context; they do not grant wider authority.',19,MUTED)
    return im

def recovery():
    im,d=base('Task recovery has three different boundaries','Durable state helps an agent continue; it does not freeze a running process')
    rows=[(190,'Work records','Tickets, subscriptions, pending inputs','Reload and dispatch',True),
          (326,'Working context','Session history, files, branch and PR','Resume and reconcile',True),
          (462,'Processes and writes','Shell processes, API calls, posted replies','Inspect external state',False)]
    for y,title,detail,status,green in rows:
        line(d,(56,y-18),(1144,y-18));text(d,56,y+7,title,27);text(d,56,y+55,detail,19,MUTED)
        d.rectangle((765*S,(y-2)*S,1144*S,(y+86)*S),fill='#EFF6F2' if green else '#F2F3F2')
        text(d,787,y+28,status,25,GREEN if green else MUTED)
    text(d,56,620,'Recovery must check what already happened before repeating an outside action.',20,MUTED)
    return im

def main():
    DEST.mkdir(parents=True,exist_ok=True)
    for name,im in [('architecture',architecture()),('recovery',recovery())]:
        path=DEST/(name+'.png');im.resize((1200,675),Image.Resampling.LANCZOS).save(path,optimize=True);print(path)

if __name__=='__main__':main()
