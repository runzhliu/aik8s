#!/usr/bin/env python3
"""Deterministic MiniMax-M3 covers, topology, and charts from verified metrics."""
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'articles/wechat/assets/minimax-m3-h20'
DATA = ROOT/'docs/assets/practices/minimax-m3-h20/benchmark-summary.json'
OUT.mkdir(parents=True, exist_ok=True)
FONT = '/System/Library/Fonts/Hiragino Sans GB.ttc'
BG, INK, MUTED, BLUE, TEAL, LINE = '#f5f9fc', '#172e45', '#60758a', '#1776a0', '#278c8f', '#d9e4ed'


def text(d, xy, value, size=25, color=INK):
    f = ImageFont.truetype(FONT, size)
    b = d.textbbox((0,0), value, font=f)
    d.text((xy[0]-b[0],xy[1]-b[1]),value,font=f,fill=color)


def center(d, box, value, size=25, color=INK):
    f = ImageFont.truetype(FONT,size)
    b = d.textbbox((0,0),value,font=f)
    d.text(((box[0]+box[2]-b[2]-b[0])/2,(box[1]+box[3]-b[3]-b[1])/2),value,font=f,fill=color)


def cover():
    im=Image.new('RGB',(900,383),BG);d=ImageDraw.Draw(im)
    d.rectangle((0,0,12,383),fill=BLUE)
    text(d,(45,36),'AI-K8S 技术工程',18,BLUE)
    text(d,(45,95),'MiniMax-M3',54)
    text(d,(45,173),'八张 H20，怎样部署？',35)
    text(d,(45,258),'SGLang / vLLM',26,BLUE)
    text(d,(45,320),'模型理解 · 实测数据 · 部署取舍',20,MUTED)
    for i in range(8):
        x=626+(i%4)*57;y=107+(i//4)*87
        d.rounded_rectangle((x,y,x+46,y+65),radius=6,fill='white',outline=LINE,width=2)
        center(d,(x,y,x+46,y+65),'H20',12,TEAL)
    center(d,(618,284,855,317),'BF16 · TP8',22,TEAL)
    im.save(OUT/'cover.png')
    sq=Image.new('RGB',(900,900),BG);d=ImageDraw.Draw(sq)
    d.rectangle((0,0,14,900),fill=BLUE)
    text(d,(62,66),'AI-K8S 技术工程',25,BLUE)
    text(d,(62,177),'MiniMax-M3',75)
    text(d,(62,310),'八张 H20-3e',64)
    text(d,(62,420),'双引擎部署与实测',42)
    for i in range(8):
        x=65+(i%4)*192;y=532+(i//4)*90
        d.rounded_rectangle((x,y,x+164,y+70),radius=10,fill='white',outline=LINE,width=2)
        center(d,(x,y,x+164,y+70),'H20-3e',24,TEAL)
    text(d,(62,778),'SGLang / vLLM · BF16 · TP8',30,BLUE)
    sq.save(OUT/'cover-square.png')


def topology():
    im=Image.new('RGB',(1200,675),BG);d=ImageDraw.Draw(im)
    text(d,(50,40),'八卡互联与 CPU 的 NUMA 本地性',37)
    text(d,(52,106),'同一节点串行测试，先记录拓扑，再做绑定优化',24,MUTED)
    for numa in range(2):
        x=50+numa*565
        d.rounded_rectangle((x,192,x+535,436),radius=18,fill='white',outline=LINE,width=2)
        text(d,(x+25,218),f'NUMA {numa} · GPU {numa*4}–{numa*4+3}',27,BLUE)
        for i in range(4):
            left=x+25+i*123
            d.rounded_rectangle((left,289,left+111,372),radius=9,fill='#e6f2f8',outline=LINE)
            center(d,(left,289,left+111,372),f'GPU {numa*4+i}',22,TEAL)
        text(d,(x+25,393),'CPU 与主机内存也需要检查亲和性',21,MUTED)
    d.rounded_rectangle((50,475,1150,571),radius=14,fill='#e9f4f6')
    center(d,(50,475,1150,571),'实测 GPU 两两显示 NV18；两个 NUMA 域不等于两组孤立 GPU',25,TEAL)
    text(d,(52,616),'来源：nvidia-smi topo -m 与 CPU 拓扑；示意图，不是产品界面截图',20,MUTED)
    im.save(OUT/'topology.png')


def chart(data, name, cases, metric, title, subtitle, unit):
    rows={(r['engine'],r['case_id']):r for r in data['aggregates']}
    im=Image.new('RGB',(1200,675),BG);d=ImageDraw.Draw(im)
    text(d,(48,35),title,37)
    text(d,(50,98),subtitle,23,MUTED)
    text(d,(50,143),'SGLang',23,BLUE);text(d,(225,143),'vLLM',23,TEAL)
    high=max(rows[e,c]['metrics'][metric]['max'] for e in ['sglang','vllm'] for c,_ in cases)*1.18
    left,top,bottom,width=105,216,518,1040
    for i in range(5):
        value=high*i/4;y=bottom-(bottom-top)*i/4
        d.line((left,y,1145,y),fill=LINE,width=1)
        text(d,(20,y-10),f'{value:.0f}',18,MUTED)
    step=width/len(cases)
    for i,(case,label) in enumerate(cases):
        mid=left+step*(i+.5)
        for j,(engine,color) in enumerate([('sglang',BLUE),('vllm',TEAL)]):
            values=rows[engine,case]['metrics'][metric]
            x=mid+(j-.5)*94;y=bottom-values['median']/high*(bottom-top)
            d.rectangle((x-23,y,x+23,bottom),fill=color)
            low=bottom-values['min']/high*(bottom-top);hi=bottom-values['max']/high*(bottom-top)
            d.line((x,hi,x,low),fill=INK,width=2)
            d.line((x-7,hi,x+7,hi),fill=INK,width=2);d.line((x-7,low,x+7,low),fill=INK,width=2)
            center(d,(x-55,y-36,x+55,y-7),f"{values['median']:.1f}",24,color)
        center(d,(mid-step/2,538,mid+step/2,568),label,22)
    text(d,(50,595),f'单位：{unit}；三轮中位数，误差线为三轮范围',21,MUTED)
    text(d,(50,631),'MiniMax-M3 BF16 · 8×H20-3e · TP8 · 32K 窗口 · 最大运行请求 32',20,MUTED)
    im.save(OUT/name)


def mobile_chart(data, name, cases, metric, title, subtitle, unit):
    """Separate portrait layout so article numbers remain readable at 375 px."""
    rows={(r['engine'],r['case_id']):r for r in data['aggregates']}
    im=Image.new('RGB',(750,1040),BG);d=ImageDraw.Draw(im)
    text(d,(35,34),title,36)
    text(d,(35,95),subtitle,26,MUTED)
    text(d,(35,153),'SGLang',30,BLUE);text(d,(260,153),'vLLM',30,TEAL)
    high=max(rows[e,c]['metrics'][metric]['max'] for e in ['sglang','vllm'] for c,_ in cases)
    left,width=42,505
    step=720/len(cases)
    for i,(case,label) in enumerate(cases):
        y=218+i*step
        text(d,(left,y),label,30)
        for j,(engine,color) in enumerate([('sglang',BLUE),('vllm',TEAL)]):
            values=rows[engine,case]['metrics'][metric]
            top=y+43+j*39;right=left+values['median']/high*width
            d.rectangle((left,top,right,top+24),fill=color)
            low=left+values['min']/high*width;hi=left+values['max']/high*width
            d.line((low,top+12,hi,top+12),fill=INK,width=2)
            d.line((low,top+6,low,top+18),fill=INK,width=2)
            d.line((hi,top+6,hi,top+18),fill=INK,width=2)
            text(d,(565,top-3),f"{values['median']:.1f}",29,color)
    text(d,(35,948),f'单位：{unit} · 三轮中位数',26,MUTED)
    text(d,(35,993),'细线为三轮范围 · BF16 / TP8 / 32K',25,MUTED)
    im.save(OUT/name)


cover();topology()
if DATA.exists():
    data=json.loads(DATA.read_text());assert data['status']=='PASS' and data['counted_rounds']==66
    chart(data,'short-throughput.png',[(f'short-128-64-c{c}',f'C{c}') for c in [1,4,8,16,32]],
          'output_throughput','短请求：并发如何改变吞吐','输入 128 / 输出 64 Token；固定输出长度，不含预热','输出 Token/s')
    chart(data,'rag-ttft.png',[('rag-4k-128-c4','4K/128 C4'),('rag-4k-128-c8','4K/128 C8'),
          ('rag-16k-256-c4','16K/256 C4'),('rag-16k-256-c8','16K/256 C8')],
          'p95_ttft_ms','长输入：首 Token 要等多久','每轮 P95 的三轮统计，不是合并请求后的总体 P95','毫秒')
    mobile_chart(data,'short-throughput-mobile.png',[(f'short-128-64-c{c}',f'并发 {c}') for c in [1,4,8,16,32]],
          'output_throughput','短请求：并发与输出吞吐','输入 128 / 输出 64 Token','输出 Token/s')
    mobile_chart(data,'rag-ttft-mobile.png',[('rag-4k-128-c4','4K 输入 / 128 输出 · C4'),('rag-4k-128-c8','4K 输入 / 128 输出 · C8'),
          ('rag-16k-256-c4','16K 输入 / 256 输出 · C4'),('rag-16k-256-c8','16K 输入 / 256 输出 · C8')],
          'p95_ttft_ms','长输入：首 Token 等待','每轮 P95 的三轮统计，非总体 P95','毫秒')
print(OUT)
