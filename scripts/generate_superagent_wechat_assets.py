#!/usr/bin/env python3
"""Super-agent article figures and M3-layout covers; no synthetic UI evidence."""
from pathlib import Path
import json
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'articles/wechat/assets/deepseek-superagent-demo'
ZH='/System/Library/Fonts/Hiragino Sans GB.ttc'
EN='/System/Library/Fonts/HelveticaNeue.ttc'
INK,MUTED,LINE,GREEN='#252A29','#747D79','#D7DDDA','#6A9D8C'
BLUE,BG,BLUELINE='#4D63CB','#F6F8FF','#DAE1F3'

def font(size,value,scale=1):
    return ImageFont.truetype(EN if value.isascii() else ZH,round(size*scale),index=7 if value.isascii() else 0)

def text(d,x,y,value,size=23,color=INK,scale=1,max_width=None):
    f=font(size,value,scale);b=d.textbbox((0,0),value,font=f)
    w,h=b[2]-b[0],b[3]-b[1]
    assert x*scale+w<=d._image.width-30*scale,(value,w)
    assert y*scale+h<=d._image.height-18*scale,value
    if max_width is not None:assert w<=max_width*scale,(value,w,max_width)
    d.text((round(x*scale)-b[0],round(y*scale)-b[1]),value,font=f,fill=color)

def centered(d,box,value,size=23,color=INK,scale=1):
    f=font(size,value,scale);b=d.textbbox((0,0),value,font=f)
    assert b[2]-b[0]<(box[2]-box[0]-16)*scale,value
    d.text((((box[0]+box[2])*scale-b[2]-b[0])/2,((box[1]+box[3])*scale-b[3]-b[1])/2),value,font=f,fill=color)

def arrow(d,a,b,s=2):
    d.line(tuple(round(v*s)for p in(a,b)for v in p),fill=GREEN,width=2*s)
    x,y=b;dx=1 if x>a[0] else -1 if x<a[0] else 0;dy=1 if y>a[1] else -1 if y<a[1] else 0
    for n in [-1,1]:
        tip=(x-dx*8+n*dy*5,y-dy*8+n*dx*5)
        d.line((round(x*s),round(y*s),round(tip[0]*s),round(tip[1]*s)),fill=GREEN,width=2*s)

def diagram(language):
    s=2;im=Image.new('RGB',(1200*s,675*s),'white');d=ImageDraw.Draw(im)
    zh=language=='zh'
    text(d,56,43,'从一条消息，到一项可追踪的工作' if zh else 'From a message to traceable work',34,scale=s)
    text(d,56,105,'准入与授权、持久任务、独立执行、原线程交付' if zh else 'Admission, durable tasks, independent execution and contextual delivery',21,MUTED,s)
    rows=[
      (56,183,'消息与来源' if zh else 'Source events',['GitHub / 飞书（可选）','事件身份与讨论上下文'] if zh else ['GitHub / optional Feishu','Event identity and context']),
      (452,183,'准入与授权' if zh else 'Gate + Eval',['身份检查、规则与研判','确定本次工作的范围'] if zh else ['Identity, rules, assessment','Define the scope of work']),
      (848,183,'工单 Ticket' if zh else 'Ticket + Mandate',['独立的任务状态','派工、订阅与执行输入'] if zh else ['Independent task state','Assignments and inputs']),
      (848,392,'DSH 执行器' if zh else 'DSH Executor',['会话、工具与工作目录','修改、测试与报告'] if zh else ['Session, tools and folder','Edit, test and report']),
      (452,392,'持久化待发消息' if zh else 'Outbox + Channel',['保存发送意图与回执','按顺序发送，失败重试'] if zh else ['Persist intent and receipts','Ordered sends and retries']),
      (56,392,'原线程中的结果' if zh else 'Original conversation',['回复与代码 PR','需要人时再请求决策'] if zh else ['Answer or code PR','Human decisions as needed'])]
    for x,y,title,body in rows:
        d.rectangle((x*s,y*s,(x+296)*s,(y+128)*s),fill='#F2F7F4' if x==848 else '#F6F7F6',outline=LINE,width=s)
        text(d,x+20,y+24,title,26,scale=s,max_width=256)
        for i,value in enumerate(body):text(d,x+20,y+70+i*27,value,19,MUTED,s,max_width=256)
    for a,b in [((364,247),(440,247)),((760,247),(836,247)),((996,325),(996,379)),((836,456),(760,456)),((440,456),(364,456))]:arrow(d,a,b,s)
    d.line((56*s,565*s,1144*s,565*s),fill=LINE,width=s)
    text(d,56,591,'SQLite 保存任务与待执行动作；模型回合结束，不等于任务交付。' if zh else 'SQLite keeps work records and pending effects; a turn ending is not delivery.',22,scale=s)
    text(d,56,635,'依据官方原型整理的示意图；不是本次部署截图。' if zh else 'Schematic of the upstream prototype, not a deployment screenshot.',19,MUTED,s)
    im.resize((1200,675),Image.Resampling.LANCZOS).save(OUT/('principles.png' if zh else 'principles.en.png'),optimize=True)

def cover(language,square=False):
    zh=language=='zh';height=900 if square else 383
    im=Image.new('RGB',(900,height),BG);d=ImageDraw.Draw(im)
    d.rectangle((0,0,13 if square else 11,height),fill=BLUE)
    if not square:
        text(d,45,36,'AI-K8S 技术工程' if zh else 'AI-K8S ENGINEERING',18,BLUE)
        text(d,45,95,'Super-agent',54,BLUE)
        text(d,45,173,'从群聊任务到代码 PR' if zh else 'From chat tasks to code PRs',33)
        text(d,45,258,'Mattermost / Gitea',26,BLUE)
        text(d,45,320,'原理解析 · Kubernetes 实战' if zh else 'Principles / Kubernetes / Real evidence',20,MUTED)
        for y,label in [(92,'Chat'),(171,'Ticket'),(250,'PR')]:
            d.rounded_rectangle((657,y,839,y+58),radius=7,fill='white',outline=BLUELINE,width=2)
            centered(d,(657,y,839,y+58),label,25,BLUE)
            if y!=250:d.line((748,y+58,748,y+79),fill=BLUELINE,width=2)
    else:
        text(d,62,66,'AI-K8S 技术工程' if zh else 'AI-K8S ENGINEERING',25,BLUE)
        text(d,62,177,'Super-agent',75,BLUE)
        text(d,62,310,'让任务持续推进' if zh else 'From chat to PR',58)
        text(d,62,420,'把原型接入真实协作流程' if zh else 'A working team-task demo',37)
        for i,label in enumerate(['Chat','Ticket','PR']):
            x=65+i*267
            d.rounded_rectangle((x,550,x+236,681),radius=9,fill='white',outline=BLUELINE,width=2)
            centered(d,(x,550,x+236,681),label,35,BLUE)
        text(d,62,778,'原理 · 实战 · 恢复' if zh else 'Principles / Practice / Recovery',29,BLUE)
    name='cover'+('-square'if square else '')+('.en'if not zh else '')+'.png'
    im.save(OUT/'brand-cover'/name,optimize=True)

def main():
    (OUT/'brand-cover').mkdir(parents=True,exist_ok=True)
    for language in ['zh','en']:
        diagram(language)
        for square in [False,True]:cover(language,square)
    (OUT/'brand-cover/palette.json').write_text(json.dumps({
        'layout_reference':'articles/wechat/assets/minimax-m3-h20/brand-cover/',
        'editorial_palette':{'background':BG,'accent':BLUE,'ink':INK,'muted':MUTED},
        'scope':'Editorial blue for the DeepSeek topic, not an official brand specification.',
        'evidence':'Covers and principles diagram are schematics. Product screenshots are separate original evidence.',
        'fonts':{'Chinese':'Hiragino Sans GB W3, TTC face 0','English':'Helvetica Neue Light, TTC face 7'}
    },ensure_ascii=False,indent=2)+'\n')
    print(OUT)

if __name__=='__main__':main()
