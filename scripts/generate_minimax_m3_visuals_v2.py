#!/usr/bin/env python3
"""M3 article figures using the existing GLM-5.3 editorial visual system.

Exact-data charts are drawn in code. The cover references the existing generic
3D lab artwork; it is decorative, not a photograph or benchmark evidence.
"""
import hashlib
import json
from pathlib import Path
import statistics
import sys

from PIL import Image, ImageDraw, ImageFont, ImageOps
from generate_glm53_day1_assets import font, BG, INK, MUTED, LINE, BLUE, ORANGE, BLUE_LIGHT, ORANGE_LIGHT
from generate_glm53_day1_wechat_covers import (
    LANDSCAPE_BACKGROUND, SQUARE_BACKGROUND, add_horizontal_panel, add_square_panel,
)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'articles/wechat/assets/minimax-m3-h20/v2'
DATA = ROOT / 'docs/assets/practices/minimax-m3-h20'
OUT.mkdir(parents=True, exist_ok=True)
EVIDENCE = []


def txt(d, x, y, text, size=24, fill=INK, bold=False, latin=False):
    f = font(size, bold=bold, latin=latin)
    if bold and latin:
        f = ImageFont.truetype('/System/Library/Fonts/HelveticaNeue.ttc', size, index=1)
    b = d.textbbox((0, 0), text, font=f)
    assert x + b[2] - b[0] <= d._image.width - 12, text
    d.text((x-b[0], y-b[1]), text, font=f, fill=fill)


def center(d, box, text, size=24, fill=INK, bold=False):
    f = font(size, bold=bold, latin=text.isascii())
    if bold and text.isascii():
        f = ImageFont.truetype('/System/Library/Fonts/HelveticaNeue.ttc', size, index=1)
    b = d.textbbox((0, 0), text, font=f)
    assert b[2]-b[0] <= box[2]-box[0], text
    d.text(((box[0]+box[2]-b[2]-b[0])/2, (box[1]+box[3]-b[3]-b[1])/2), text, font=f, fill=fill)


def header(title, subtitle, with_legend=True):
    im = Image.new('RGB', (1200, 675), BG)
    d = ImageDraw.Draw(im)
    txt(d, 48, 36, title, 34, bold=True)
    txt(d, 50, 96, subtitle, 21, fill=MUTED)
    if with_legend:
        for x, name, color, bg in [(864, 'SGLang', BLUE, BLUE_LIGHT), (1020, 'vLLM', ORANGE, ORANGE_LIGHT)]:
            d.rounded_rectangle((x, 32, x+136, 76), 22, fill=bg)
            d.rounded_rectangle((x+13, 49, x+33, 60), 3, fill=color)
            txt(d, x+43, 46, name, 21, latin=True)
    return im, d


def footer(d, text):
    d.rounded_rectangle((48, 605, 1152, 656), 15, fill='white', outline=LINE, width=1)
    center(d, (57, 608, 1143, 652), text, 21, fill=MUTED)


def grouped(name, heading, subtitle, groups, maximum, ticks, decimals, footnote, delta=False):
    im, d = header(heading, subtitle)
    left, top, right, bottom = 90, 191, 1150, 510
    for value in ticks:
        y = bottom - value/maximum*(bottom-top)
        d.line((left, y, right, y), fill=LINE)
        label = f'{value:g}'
        f = font(20, latin=True); b = d.textbbox((0, 0), label, font=f)
        txt(d, left-16-(b[2]-b[0]), y-10, label, 20, fill=MUTED, latin=True)
    step = (right-left)/len(groups)
    for i, (label, values) in enumerate(groups):
        mid = left+(i+.5)*step
        for j, (engine, color) in enumerate([('sglang', BLUE), ('vllm', ORANGE)]):
            v = values[engine]; x = mid+(j-.5)*82
            y = bottom-v['median']/maximum*(bottom-top)
            d.rounded_rectangle((x-30, y, x+30, bottom), radius=7, fill=color)
            low = bottom-v['min']/maximum*(bottom-top)
            high = bottom-v['max']/maximum*(bottom-top)
            d.line((x, low, x, high), fill=INK, width=2)
            for yy in [low, high]: d.line((x-6, yy, x+6, yy), fill=INK, width=2)
            center(d, (x-42, high-37, x+42, high-6), f"{v['median']:.{decimals}f}", 25, fill=color, bold=True)
            EVIDENCE.append({'figure':name, 'group':label, 'engine':engine, **v})
        for k, line in enumerate(label.split('\n')):
            center(d, (mid-step/2, 527+k*29, mid+step/2, 555+k*29), line, 23)
        if delta:
            diff=(values['sglang']['median']/values['vllm']['median']-1)*100
            center(d, (mid-step/2, 560, mid+step/2, 588), f'S {diff:+.1f}%', 20, fill=BLUE)
    footer(d, footnote)
    im.save(OUT/name, optimize=True)


def topology():
    im,d=header('同机八卡：GPU 互联与 NUMA 分开看',
                'MiniMax-M3 · BF16 / TP8 · 两套引擎串行复用同一节点', False)
    for n in range(2):
        x=48+n*572
        d.rounded_rectangle((x,162,x+532,441),20,fill='white',outline=LINE,width=2)
        txt(d,x+26,185,f'NUMA {n}',30,bold=True)
        txt(d,x+26,233,f'CPU {n*192}–{n*192+191}',22,fill=MUTED,latin=True)
        for i in range(4):
            a=x+25+i*123
            d.rounded_rectangle((a,291,a+111,381),12,fill=BLUE_LIGHT,outline='#BDD0F8')
            center(d,(a,291,a+111,350),f'GPU {n*4+i}',23,fill=BLUE,bold=True)
            center(d,(a,348,a+111,377),'H20-3e',18,fill=MUTED)
        center(d,(x+12,395,x+520,427),'CPU 允许集合不等于实际内存驻留位置',20,fill=MUTED)
    d.rounded_rectangle((48,468,1152,564),17,fill=INK)
    center(d,(48,474,1152,520),'NV18 · 八张 GPU 两两互联',29,fill='white',bold=True)
    center(d,(48,521,1152,557),'跨 NUMA 的 CPU 与内存访问仍需单独检查',22,fill='#C5D3E7')
    footer(d,'来源：实际 GPU / CPU 拓扑快照 · 拓扑示意，不是产品界面截图')
    im.save(OUT/'topology.png',optimize=True)


def covers():
    # Reuse unmodified series artwork by reference, compose precise M3 titles.
    for square,source,name in [(False,LANDSCAPE_BACKGROUND,'cover.png'),(True,SQUARE_BACKGROUND,'cover-square.png')]:
        size=(900,900) if square else (900,383)
        im=ImageOps.fit(Image.open(source).convert('RGB'),size,method=Image.Resampling.LANCZOS)
        im=add_square_panel(im) if square else add_horizontal_panel(im)
        d=ImageDraw.Draw(im); x=58 if square else 46
        cyan='#40DCFF'; white='#F6FAFF'; muted='#A6D2FF'
        txt(d,x,52 if square else 35,'BF16  ·  8×H20-3e  ·  TP8',22 if square else 15,fill=muted,latin=True)
        txt(d,x,113 if square else 83,'MiniMax-M3',68 if square else 44,fill=white,bold=True,latin=True)
        txt(d,x,203 if square else 142,'双引擎实测',58 if square else 36,fill=white)
        y=300 if square else 204; w=314 if square else 223; h=54 if square else 39
        d.rounded_rectangle((x,y,x+w,y+h),h//2,fill=cyan)
        center(d,(x,y,x+w,y+h),'SGLang × vLLM',28 if square else 21,fill='#04253D',bold=True)
        txt(d,x,388 if square else 264,'主压测 66 轮 · 7,908 请求',25 if square else 17,fill=muted)
        d.line((x,440 if square else 309,x+(380 if square else 266),440 if square else 309),fill='#FF9E42',width=4 if square else 3)
        txt(d,x,467 if square else 336,'AIK8S.RUN',19 if square else 12,fill=muted,latin=True)
        im.convert('RGB').save(OUT/name,optimize=True)


def main():
    data=json.loads((DATA/'benchmark-summary.json').read_text())
    assert data['status']=='PASS' and data['counted_rounds']==66 and data['counted_requests']==7908
    rows={(r['engine'],r['case_id']):r for r in data['aggregates']}
    def values(case,metric,div=1):
        return {e:{k:rows[e,case]['metrics'][metric][k]/div for k in ['median','min','max']} for e in ['sglang','vllm']}
    grouped('short-throughput.png','短请求吞吐：并发提高后的表现',
            'MiniMax-M3 · 8×H20-3e · BF16 / TP8 · 输入 128 / 输出 64 Token',
            [(f'C={c}',values(f'short-128-64-c{c}','output_throughput')) for c in [1,4,8,16,32]],
            1350,[0,300,600,900,1200],1,
            '输出 tok/s，越高越好 · 三轮中位数 / 范围 · S 为相对 vLLM 的变化',True)
    cases=['rag-4k-128-c4','rag-4k-128-c8','rag-16k-256-c4','rag-16k-256-c8']
    grouped('rag-ttft.png','长输入首 Token：vLLM 等待更短',
            'MiniMax-M3 · 8×H20-3e · BF16 / TP8 · P95 TTFT',
            [(label,values(case,'p95_ttft_ms',1000)) for label,case in zip(['4K / 128\nC4','4K / 128\nC8','16K / 256\nC4','16K / 256\nC8'],cases)],
            16,[0,4,8,12,16],2,'单位：秒，越低越好 · 三轮 P95 的中位数与范围 · 32K 服务窗口')
    mm={e:json.loads((DATA/f'{e}-multimodal.json').read_text()) for e in ['sglang','vllm']}
    groups=[]
    for case,c,label in [('image-512',4,'512 单图\nC4'),('image-1024',4,'1024 单图\nC4'),('two-images-512',4,'512 双图\nC4'),('video-16frames',2,'16 帧源视频\nC2')]:
        v={}
        for e in mm:
            rs=[r for r in mm[e]['rounds'] if r['case']==case and r['concurrency']==c]
            assert len(rs)==3 and all(r['status']=='PASS' and r['passed']==16 for r in rs)
            vs=[r['request_throughput'] for r in rs]
            v[e]={'median':statistics.median(vs),'min':min(vs),'max':max(vs)}
        groups.append((label,v))
    grouped('multimodal-throughput.png','多模态吞吐：按输入类型比较',
            'MiniMax-M3 · 带边框图像 / 颜色顺序视频 · 每配置 16 请求 × 3 轮',
            groups,15,[0,3,6,9,12,15],2,'完成请求数 / 秒，越高越好 · 三轮中位数 / 范围 · 重复素材端到端测试')
    topology()
    if '--candidate-covers' in sys.argv:
        covers()
    (OUT/'chart-data.json').write_text(json.dumps(EVIDENCE,ensure_ascii=False,indent=2)+'\n')
    (OUT/'visual-plan.md').write_text('''# MiniMax-M3 配图第二版

参考 GLM-5.3 的蓝橙引擎配色、浅灰画布、分组柱图、胶囊图例与深色封面。

| 配图 | 作用与来源 | 规格 |
| --- | --- | --- |
| 封面及方形封面 | 用户选择保留上一版浅色封面；v2 不替换封面 | 900×383 / 900×900 |
| 短请求吞吐 | benchmark-summary.json，五档并发、真实三轮中位数与范围 | 1200×675 |
| RAG 首 Token | 同一数据源，四档配置、P95 TTFT 换算秒 | 1200×675 |
| 多模态吞吐 | 双引擎 multimodal.json，四档正式配置、重复素材 | 1200×675 |
| 拓扑 | 已核对的 GPU / NUMA 关系，不把装饰封面当拓扑证据 | 1200×675 |

旧版图片保留，新版正文图单独存放。精确图表点与范围保存在 chart-data.json。深色候选封面仅在显式传入 --candidate-covers 时生成，不用于当前草稿。
''')
    print(OUT)


if __name__=='__main__':main()
