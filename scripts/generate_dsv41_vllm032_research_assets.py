#!/usr/bin/env python3
"""Third-edition research figures: regular/light type, flat bars, no error bars.

Stylistic reference: OpenAI's public benchmark figures. These are independent
plots of this project's measurements; no OpenAI brand assets or scores are used.
Reference: https://cdn.openai.com/pdf/23eca107-a9b1-4d2c-b156-7deb4fbc697c/GPT-5-3-Codex-System-Card-02.pdf
"""
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parents[1]
PUB=ROOT/'docs/assets/practices/deepseek-v41-vllm032-upgrade'
WC=ROOT/'articles/wechat/assets/deepseek-v41-vllm032-upgrade'
S=2
INK='#202020';MUTED='#777777';GRID='#EAEAEA';OLD='#D4D4D8';NEW='#78B5A3'

def face(value,size,light=False,mono=False):
    if mono:
        path='/System/Library/Fonts/Menlo.ttc';index=0
    elif any('\u3400'<=x<='\u9fff' for x in value):
        path='/System/Library/Fonts/Hiragino Sans GB.ttc';index=0  # W3
    else:
        path='/System/Library/Fonts/HelveticaNeue.ttc';index=7 if light else 0
    return ImageFont.truetype(path,round(size*S),index=index)

def text(d,x,y,value,size=22,color=INK,align='left',light=False,mono=False):
    f=face(value,size,light,mono);b=d.textbbox((0,0),value,font=f)
    width=b[2]-b[0];height=b[3]-b[1]
    xx=x*S-(width/2 if align=='center' else width if align=='right' else 0)
    assert 0<=xx and xx+width<=1200*S,value
    assert 0<=y*S and y*S+height<=675*S,value
    d.text((xx-b[0],y*S-b[1]),value,font=f,fill=color)

def line(d,x1,y1,x2,y2,color=GRID,width=1):
    d.line((round(x1*S),round(y1*S),round(x2*S),round(y2*S)),fill=color,width=round(width*S))

def rect(d,x,y,w,h,color):
    d.rectangle((round(x*S),round(y*S),round((x+w)*S),round((y+h)*S)),fill=color)

def header(title,cn=True,subtitle=None):
    im=Image.new('RGB',(1200*S,675*S),'white');d=ImageDraw.Draw(im)
    text(d,56,43,title,36,light=True)
    sub=subtitle or ('DeepSeek-V4.1-Flash · 8×H20-3e · TP8 + EP · 三轮中位数' if cn else 'DeepSeek-V4.1-Flash / 8 x H20-3e / TP8 + EP / 3-round median')
    text(d,56,101,sub,19,MUTED,light=True)
    return im,d

def legend(d,cn):
    for x,label,color in [(810,'原文构建' if cn else 'Article build',OLD),(1010,'0.32.0',NEW)]:
        rect(d,x,148,15,15,color);text(d,x+25,146,label,20,MUTED)

def axis(d,left,right,top,bottom,maximum,ticks):
    for v in ticks:
        y=bottom-v/maximum*(bottom-top)
        line(d,left,y,right,y,color='#C8C8C8' if v==0 else GRID)
        text(d,left-18,y-10,str(v),18,MUTED,'right')

def pair(d,center,bottom,height,maximum,values,width=52,gap=34,decimals=1):
    for j,(value,color) in enumerate(zip(values,[OLD,NEW])):
        x=center+(j-.5)*(width+gap)-width/2
        h=value/maximum*height
        rect(d,x,bottom-h,width,h,color)
        text(d,x+width/2,bottom-h-34,f'{value:.{decimals}f}',26,INK,'center',True)

def throughput(data,cn):
    im,d=header('vLLM 升级后的输出吞吐' if cn else 'Output throughput after the vLLM upgrade',cn);legend(d,cn)
    cases={c['case']:c for c in data['cases']}
    for left,right,prefix,heading,maximum,ticks in [
        (112,532,'prefill','8K 输入 / 128 输出' if cn else '8K input / 128 output',250,[0,100,200]),
        (708,1128,'decode','1K 输入 / 512 输出' if cn else '1K input / 512 output',750,[0,250,500,750])]:
        text(d,left,189,heading,25,light=True)
        text(d,left,226,f'Output token/s · 0–{maximum}',18,MUTED)
        top,bottom=264,548
        axis(d,left,right,top,bottom,maximum,ticks)
        for i,c in enumerate([1,8]):
            case=cases[f'{prefix}-c{c}'];assert case['all_requests_successful_in_both']
            vals=[case['variants'][v]['median_output_throughput'] for v in ['article','v032']]
            center=left+(i+.5)*(right-left)/2
            pair(d,center,bottom,bottom-top,maximum,vals)
            text(d,center,572,('并发 ' if cn else 'Concurrency ')+str(c),21,INK,'center')
    text(d,56,632,'左右面板纵轴刻度不同；每个面板内两版使用相同刻度。' if cn else 'Y-axis scales differ between panels; both builds share the same scale within each panel.',17,MUTED)
    return im

def latency(data,cn):
    im,d=header('8K 输入的首内容等待' if cn else 'Time to first content with 8K input',cn);legend(d,cn)
    text(d,112,191,'P95 TTFT (s)',21,MUTED)
    top,bottom=238,548
    axis(d,112,1128,top,bottom,10,[0,2,4,6,8,10])
    cases={c['case']:c for c in data['cases']}
    for center,c in [(366,1),(874,8)]:
        case=cases[f'prefill-c{c}'];assert case['all_requests_successful_in_both']
        vals=[case['variants'][v]['median_p95_ttft_ms']/1000 for v in ['article','v032']]
        pair(d,center,bottom,bottom-top,10,vals,width=110,gap=30,decimals=2)
        text(d,center,575,('并发 ' if cn else 'Concurrency ')+str(c),23,INK,'center')
    return im

def failures(data,cn):
    sub='每版 984 个正式请求 · 合计 60 轮测量' if cn else '984 formal requests per build / 60 measured rounds in total'
    im,d=header('HTTP 200 之后的空文本响应' if cn else 'Empty text after HTTP 200',cn,sub)
    text(d,56,196,'17 个失败流的共同字段' if cn else 'Fields shared by all 17 invalid streams',23)
    for y,key,value in [(264,'HTTP status','200'),(324,'SSE terminator','[DONE]'),(384,'completion_tokens','128 / 512'),(444,'choices[].text','""')]:
        text(d,56,y,key,21,MUTED,mono=True)
        text(d,522,y,value,22,INK,'right',mono=True)
        if y<444:line(d,56,y+42,522,y+42)
    text(d,56,523,'生成 Token 有计数，实际正文为空。' if cn else 'Tokens were reported, but no usable text.',19,MUTED)
    left,right,top,bottom=710,1128,247,548
    text(d,left,196,'无效请求数' if cn else 'Invalid requests',23)
    axis(d,left,right,top,bottom,12,[0,5,10])
    for center,v,name,color in [(814,'article','原文构建' if cn else 'Article build',OLD),(1024,'v032','0.32.0',NEW)]:
        n=data['totals'][v]['failed'];h=n/12*(bottom-top)
        rect(d,center-55,bottom-h,110,h,color)
        text(d,center,bottom-h-38,str(n),30,INK,'center',True)
        text(d,center,575,name,20,INK,'center')
    text(d,56,632,'合成固定长度负载的观察，不是生产故障率。' if cn else 'Synthetic fixed-length workload; not production failure rates.',17,MUTED)
    return im

def main():
    data=json.loads((PUB/'results.json').read_text())
    for cn,base in [(False,PUB),(True,WC)]:
        dest=base/'v3';dest.mkdir(parents=True,exist_ok=True)
        for name,im in [('throughput',throughput(data,cn)),('ttft',latency(data,cn)),('response-validation',failures(data,cn))]:
            path=dest/(name+'.png');im.resize((1200,675),Image.Resampling.LANCZOS).save(path,optimize=True);print(path)

if __name__=='__main__':main()
