#!/usr/bin/env python3
"""Render exact-data AIBrix figures using the MiniMax M3 visual baseline."""
import json,math,sys
from pathlib import Path
from PIL import Image,ImageDraw
ROOT=Path(__file__).resolve().parents[1]
R=ROOT/'docs/assets/practices/aibrix-routing-cache'
sys.path.insert(0,str(ROOT/'scripts'))
from generate_minimax_m3_visuals_v2 import txt,center,header,footer
from generate_glm53_day1_assets import BG,INK,MUTED,LINE,BLUE,ORANGE,BLUE_LIGHT
OUT=ROOT/'docs/assets/practices/aibrix-routing-cache';OUT.mkdir(parents=True,exist_ok=True)
COLORS={'random':'#7B8798','least-request':BLUE,'prefix-cache':ORANGE}

def mechanism():
    im,d=header('路由匹配，不等于引擎真实命中','AIBrix v0.7.0 · 本次使用本地字符索引，未启用 KV event sync',False)
    cards=[(48,160,568,405,'路由器的历史账本',BLUE,['这段前缀曾发往哪个副本？','128 字符分块，选定目标时更新','再结合网关在途请求数做选择']),
           (600,160,1152,405,'引擎的实际缓存',ORANGE,['本次输入真正复用了多少 Token？','缓存是否可用，由引擎实际状态决定','本次 attention block：1,568 Token'])]
    for x,y,x2,y2,title,color,lines in cards:
        d.rounded_rectangle((x,y,x2,y2),18,fill='white',outline=LINE,width=2)
        txt(d,x+24,y+25,title,30,fill=color,bold=True)
        for j,line in enumerate(lines):txt(d,x+24,y+90+j*45,line,23,fill=INK)
    d.rounded_rectangle((48,441,1152,571),18,fill=INK)
    center(d,(48,451,1152,504),'决策 → 请求分配 → 实际命中 → 等待 → TTFT / 达标率',29,fill='white',bold=True)
    center(d,(48,515,1152,555),'同一时间轴交叉验证，才能判断路由是否改善了体验',24,fill='#C5D3E7')
    footer(d,'机制示意 · 字符匹配比例、Token 命中率和请求达标率，分母各不相同')
    im.save(OUT/'mechanism.png',optimize=True)
    im=Image.new('RGB',(720,1080),BG);d=ImageDraw.Draw(im)
    txt(d,38,35,'两份不同的缓存账本',38,bold=True)
    txt(d,38,99,'AIBrix 本地索引 × vLLM KV',27,fill=MUTED)
    for j,(_,_,_,_,title,color,lines) in enumerate(cards):
        y=165+j*315;d.rounded_rectangle((32,y,688,y+285),18,fill='white',outline=LINE,width=2)
        txt(d,57,y+28,title,37,fill=color,bold=True)
        for k,line in enumerate(lines):txt(d,57,y+98+k*54,line,28)
    d.rounded_rectangle((32,815,688,1019),18,fill=INK)
    center(d,(32,835,688,890),'决策 → 分配 → 真实命中',32,fill='white',bold=True)
    center(d,(32,900,688,955),'等待 → TTFT → 达标率',32,fill='white',bold=True)
    center(d,(32,968,688,1002),'机制示意 · 本次未启用 KV event sync',24,fill='#C5D3E7')
    im.save(OUT/'mechanism-mobile.png',optimize=True)

def chart(filename,title,scenarios):
    data=json.loads((R/'results.json').read_text());assert data['complete']
    lookup={s['phase']:s for s in data['phases']}
    im,d=header(title,'Qwen3.8-27B-FP8 · 2 × 单 L20 · 每阶段 96 请求 / 1.6 RPS',False)
    for i,(name,color) in enumerate(COLORS.items()):
        x=130+i*350;d.rounded_rectangle((x,139,x+22,153),3,fill=color);txt(d,x+32,133,name,22,latin=True)
    for si,(scenario,label) in enumerate(scenarios):
        left=82+si*585;right=left+510;top=230;bottom=515
        values=[lookup[f'r{r}-{scenario}-{s}']['ttft']['p95'] for r in [1,2] for s in COLORS]
        maximum=math.ceil(max(values)*1.2*2)/2
        center(d,(left,179,right,215),label,25,bold=True)
        for j in range(5):
            v=maximum*j/4;y=bottom-(bottom-top)*j/4;d.line((left,y,right,y),fill=LINE)
            txt(d,left-50,y-10,f'{v:.1f}',18,fill=MUTED,latin=True)
        for ri,r in enumerate([1,2]):
            mid=left+125+ri*252
            for sj,(s,color) in enumerate(COLORS.items()):
                v=lookup[f'r{r}-{scenario}-{s}']['ttft']['p95'];x=mid+(sj-1)*66;y=bottom-v/maximum*(bottom-top)
                d.rectangle((x-23,y,x+23,bottom),fill=color)
                center(d,(x-45,y-33,x+45,y-5),f'{v:.2f}',23,fill=color,bold=True)
            center(d,(mid-95,535,mid+95,569),'第 '+str(r)+' 轮',24)
    footer(d,'TTFT P95，单位：秒，越低越好 · 两轮分别计算 · 左右图纵轴独立缩放')
    im.save(OUT/filename,optimize=True)
    # Separate mobile layout: exact values and bars, no tiny six-series plot.
    im=Image.new('RGB',(720,1300),BG);d=ImageDraw.Draw(im)
    txt(d,34,35,title,33,bold=True);txt(d,36,90,'TTFT P95 / 秒 · 每阶段 96 请求',27,fill=MUTED)
    for i,(name,color) in enumerate(COLORS.items()):
        x=36+i*226;d.rectangle((x,145,x+18,159),fill=color);txt(d,x+26,138,name,23,latin=True)
    for si,(scenario,label) in enumerate(scenarios):
        y0=210+si*515;txt(d,36,y0,label,33,bold=True)
        maximum=max(lookup[f'r{r}-{scenario}-{s}']['ttft']['p95'] for r in [1,2] for s in COLORS)*1.15
        for ri,r in enumerate([1,2]):
            y=y0+68+ri*193;txt(d,36,y,'第 '+str(r)+' 轮',27,fill=MUTED)
            for sj,(s,color) in enumerate(COLORS.items()):
                v=lookup[f'r{r}-{scenario}-{s}']['ttft']['p95'];yy=y+43+sj*42;x=190;w=v/maximum*365
                txt(d,36,yy,s,21,fill=color,latin=True)
                d.rectangle((x,yy,x+max(w,2),yy+27),fill=color)
                txt(d,x+w+14,yy,f'{v:.2f}',28,fill=color,bold=True,latin=True)
    center(d,(30,1235,690,1280),'两轮分别计算 · 每个场景独立缩放横轴',25,fill=MUTED)
    im.save(OUT/filename.replace('.png','-mobile.png'),optimize=True)

def covers():
    for square in [False,True]:
        h=900 if square else 383;im=Image.new('RGB',(900,h),BG);d=ImageDraw.Draw(im)
        d.rectangle((0,0,15,h),fill=BLUE)
        txt(d,47,37,'AIBRIX  /  ROUTING LAB',22,fill=BLUE,bold=True,latin=True)
        txt(d,47,98 if not square else 147,'缓存命中之后',52 if not square else 64,bold=True)
        txt(d,47,172 if not square else 246,'请求为什么还在等？',49 if not square else 62,bold=True)
        txt(d,49,264 if not square else 367,'三种路由 · 冷热对照 · 热点取舍',26 if not square else 32,fill=MUTED)
        if square:
            for i,(name,color) in enumerate(COLORS.items()):
                y=480+i*93;d.rounded_rectangle((48,y,850,y+72),14,fill='white',outline=LINE)
                d.rectangle((70,y+21,82,y+51),fill=color);txt(d,104,y+22,name,31,fill=color,latin=True)
            txt(d,49,807,'AIK8S.RUN · Qwen3.8-27B-FP8 / L20',23,fill=MUTED,latin=True)
        else:txt(d,49,335,'AIK8S.RUN · Qwen3.8-27B-FP8 / L20',19,fill=MUTED,latin=True)
        im.save(OUT/('cover-square.png' if square else 'cover.png'),optimize=True)

def allocation():
    data=json.loads((R/'results.json').read_text());s=next(x for x in data['phases'] if x['phase']=='r1-hot50-prefix-cache')
    im,d=header('前缀数量均衡，请求量仍会倾斜','50% 热点 · 第一轮 prefix-cache · 初始每个副本各持有四组测量前缀',False)
    for i,(alias,v) in enumerate(s['replicas'].items()):
        x=48+i*568;color=BLUE if i==0 else ORANGE
        d.rounded_rectangle((x,158,x+536,460),18,fill='white',outline=LINE,width=2)
        txt(d,x+24,180,alias,32,fill=color,bold=True,latin=True)
        txt(d,x+24,245,str(v['requests'])+' / 96',58,fill=color,bold=True,latin=True)
        txt(d,x+24,325,'实际分配请求',25,fill=MUTED)
        txt(d,x+24,380,'等待峰值：'+str(int(v['waiting_peak']))+' 个请求',28)
    d.rounded_rectangle((48,490,1152,575),16,fill=INK)
    center(d,(48,490,1152,533),'96 次 prefix_match，不代表 96 次低延迟',29,fill='white',bold=True)
    center(d,(48,534,1152,570),'真实命中 '+f'{s["cache_hit_ratio"]*100:.1f}% · TTFT P95 {s["ttft"]["p95"]:.2f} 秒 · 达标 {s["good"]}/96',24,fill='#C5D3E7')
    footer(d,'来源：逐请求 target-pod + 引擎计数 + 5 秒队列快照；等待峰值为采样值')
    im.save(OUT/'allocation-hot50.png',optimize=True)
    im=Image.new('RGB',(720,1110),BG);d=ImageDraw.Draw(im)
    txt(d,34,36,'前缀数均衡，请求仍会倾斜',36,bold=True)
    txt(d,36,99,'50% 热点 · 第一轮 prefix-cache',27,fill=MUTED)
    for i,(alias,v) in enumerate(s['replicas'].items()):
        y=162+i*276;color=BLUE if i==0 else ORANGE
        d.rounded_rectangle((32,y,688,y+247),18,fill='white',outline=LINE,width=2)
        txt(d,57,y+25,alias,33,fill=color,bold=True,latin=True)
        txt(d,57,y+88,str(v['requests'])+' / 96',60,fill=color,bold=True,latin=True)
        txt(d,57,y+183,'5 秒快照等待峰值：'+str(int(v['waiting_peak'])),28)
    d.rounded_rectangle((32,748,688,1018),18,fill=INK)
    center(d,(32,763,688,819),'96 次 prefix_match',35,fill='white',bold=True)
    center(d,(32,823,688,876),f'实际 Token 命中率 {s["cache_hit_ratio"]*100:.1f}%',30,fill='white')
    center(d,(32,883,688,936),f'TTFT P95 {s["ttft"]["p95"]:.2f} 秒',34,fill='white',bold=True)
    center(d,(32,944,688,992),f'达标 {s["good"]} / 96',31,fill='#C5D3E7')
    center(d,(30,1034,690,1082),'来源：实际落点、引擎计数与五秒快照',24,fill=MUTED)
    im.save(OUT/'allocation-hot50-mobile.png',optimize=True)

mechanism();covers()
allocation()
if json.loads((R/'results.json').read_text())['complete']:
    chart('cold-warm.png','冷热对照：首 Token 的等待差异',[('cold-uniform','冷缓存 · 均匀流量'),('warm-uniform','双副本均热 · 均匀流量')])
    chart('hotspots.png','热点集中后：首 Token 的等待差异',[('hot50','50% 热点'),('hot90','89.6% 热点')])
