#!/usr/bin/env python3
"""Minimal bilingual narration workflow; an explanatory diagram, not a screenshot."""
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont

OUT=Path(__file__).resolve().parents[1]/'docs/assets/practices/qwen3-tts-article-narration'
S=2
def draw(cn):
    im=Image.new('RGB',(1200*S,675*S),'white');d=ImageDraw.Draw(im)
    def text(x,y,t,size=22,color='#242424',center=False):
        chinese=any('\u3400'<=c<='\u9fff' for c in t)
        f=ImageFont.truetype('/System/Library/Fonts/Hiragino Sans GB.ttc' if chinese else '/System/Library/Fonts/HelveticaNeue.ttc',size*S,index=0 if chinese else 7)
        b=d.textbbox((0,0),t,font=f);xx=x*S-((b[2]-b[0])/2 if center else 0)
        assert xx>=0 and xx+b[2]-b[0]<=1200*S,t
        d.text((xx-b[0],y*S-b[1]),t,font=f,fill=color)
    text(56,48,'把技术文章变成可收听的旁白' if cn else 'From a technical article to spoken narration',34)
    text(56,110,'文本先改写，语音分段生成；读者直接在文章里试听。' if cn else 'Prepare the spoken text, synthesize short segments, then listen in the article.',20,'#777777')
    labels=[('公开文章','Markdown'),('朗读稿','Spoken text'),('语音请求','Speech API'),('语音模型','Talker + codec'),('音频文件','WAV / M4A'),('网页试听','Web player')]
    centers=[120,312,504,696,888,1080]
    for i,((zh,en),x) in enumerate(zip(labels,centers)):
        d.ellipse(((x-7)*S,263*S,(x+7)*S,277*S),fill='#78B5A3')
        text(x,211,f'{i+1:02}',21,'#777777',True)
        text(x,310,zh if cn else en,22,center=True)
        if cn:text(x,352,en,17,'#777777',True)
        if i<5:
            d.line(((x+18)*S,270*S,(centers[i+1]-22)*S,270*S),fill='#C7C7C7',width=2)
            end=centers[i+1]-22
            d.line(((end-7)*S,266*S,end*S,270*S,(end-7)*S,274*S),fill='#C7C7C7',width=2)
    d.line((56*S,445*S,1144*S,445*S),fill='#EAEAEA',width=2)
    text(56,485,'39 个串行请求' if cn else '39 sequential requests',26)
    text(450,485,'1 × L20',26)
    text(830,485,'703.5 s',26)
    text(56,535,'完整文章的实测流程' if cn else 'Measured long-article workflow',19,'#777777')
    text(450,535,'已有服务，热启动' if cn else 'Existing, warm service',19,'#777777')
    text(830,535,'包含段落间停顿' if cn else 'Including paragraph gaps',19,'#777777')
    text(56,622,'示意图；音频文件与逐段数据见正文。' if cn else 'Explanatory diagram; audio files and per-segment data are linked in the article.',17,'#777777')
    im.resize((1200,675),Image.Resampling.LANCZOS).save(OUT/('workflow-zh.png' if cn else 'workflow-en.png'))
if __name__=='__main__':
    for cn in (True,False):draw(cn)
