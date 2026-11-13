#!/usr/bin/env python3
"""Plot completed three-round MiniMax H3 Image batches; no model data needed."""
import json, statistics
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
root = Path(__file__).resolve().parents[1]
folder = root / 'docs/assets/practices/minimax-h3-image-h20'
rows = [json.loads(x) for x in (folder / 'groups.jsonl').read_text().splitlines() if x.strip()]
def completed_data(task):
    result = []
    for c in (1, 2, 4, 8):
        group = [r for r in rows if r['group'].startswith(f'perf-square-{task}-c{c}-r')]
        if len(group) == 3 and all(r['success'] == r['planned'] == 12 for r in group):
            result.append((c, statistics.median(r['images_per_second'] for r in group), statistics.median(r['p50_s'] for r in group)))
    return result
helv='/System/Library/Fonts/HelveticaNeue.ttc'
han='/System/Library/Fonts/Hiragino Sans GB.ttc'
font=lambda size:ImageFont.truetype(helv,size,index=7)
font_cn=lambda size:ImageFont.truetype(han,size,index=0)
def mixed(draw, x, y, pieces, color):
    for text, chosen in pieces:
        draw.text((x, y), text, font=chosen, fill=color)
        x += draw.textlength(text, font=chosen)

def draw(lang, task):
    data = completed_data(task)
    if not data:
        return
    im=Image.new('RGB',(1200,675),'white'); d=ImageDraw.Draw(im)
    mixed(d, 60, 35, [('并发与性能',font_cn(27)), ('  /  Concurrency and performance',font(28))], '#222a2a')
    kind = '文生图' if task == 't2i' else '单图编辑'
    english = 'text to image' if task == 't2i' else 'single-image edit'
    mixed(d, 60, 88, [('2048 × 2048 ',font(18)),(kind,font_cn(17)), (' / '+english+' · 1 × H20-3e · ',font(18)), ('三轮中位数',font_cn(17)), (' / median of 3 rounds',font(18))], '#78827d')
    for panel in range(2):
        x0=75+panel*580;x1=x0+485;top=215;bottom=555
        left = '吞吐' if panel == 0 else '请求耗时 P50'
        right = ' / Throughput (images/s)' if panel == 0 else ' / Request P50 (s)'
        mixed(d, x0, 148, [(left,font_cn(20)),(right,font(20))], '#333b38')
        vals=[v[1+panel] for v in data]; cap=max(vals)*1.3
        for i in range(4):
            y=bottom-(bottom-top)*i/3;d.line((x0,y,x1,y),fill='#e8ebe9',width=1)
            tick=f'{cap*i/3:.2f}' if panel==0 else f'{cap*i/3:.0f}'
            d.text((x0-50,y-9),tick,font=font(15),fill='#959c98')
        step=(x1-x0)/len(data); bar=min(65,step*.45)
        for i,(c,t,l) in enumerate(data):
            v=t if panel==0 else l;cx=x0+step*(i+.5);y=bottom-(bottom-top)*v/cap
            d.rectangle((cx-bar/2,y,cx+bar/2,bottom),fill='#799b8c' if panel==0 else '#a4ada9')
            label=f'{v:.3f}' if panel==0 else f'{v:.1f}'
            box=d.textbbox((0,0),label,font=font(21));d.text((cx-(box[2]-box[0])/2,y-30),label,font=font(21),fill='#405a4f')
            text=f'C{c}';box=d.textbbox((0,0),text,font=font(19));d.text((cx-(box[2]-box[0])/2,bottom+15),text,font=font(19),fill='#58625d')
    mixed(d, 60, 624, [('每轮 12 次请求，两图各自使用独立纵轴',font_cn(15)), (' / 12 requests per round; independent vertical scales',font(16))], '#8a938e')
    im.save(folder/('concurrency-en.png' if task == 't2i' else 'edit-concurrency-en.png'),optimize=True)
for task in ('t2i', 'edit'):
    draw('en', task)

def draw_resolution():
    values = []
    for key, count, label in [('square', 12, '2048 × 2048'), ('4k', 6, '4096 × 4096')]:
        group = [r for r in rows if r['group'].startswith(f'perf-{key}-t2i-c1-r')]
        if len(group) != 3 or not all(r['success'] == r['planned'] == count for r in group):
            return
        values.append((label, statistics.median(r['p50_s'] for r in group)))
    im=Image.new('RGB',(1200,675),'white');d=ImageDraw.Draw(im)
    mixed(d,60,35,[('分辨率与请求耗时',font_cn(27)),('  /  Resolution and latency',font(28))],'#222a2a')
    mixed(d,60,88,[('文生图',font_cn(17)),(' / text to image · C1 · 1 × H20-3e · ',font(18)),('三轮 P50 中位数',font_cn(17)),(' / median P50 across 3 rounds',font(18))],'#78827d')
    mixed(d,80,148,[('请求耗时（秒）',font_cn(20)),(' / Request P50 (s)',font(20))],'#333b38')
    x0=110;x1=1120;top=215;bottom=555;cap=max(v for _,v in values)*1.3
    for i in range(4):
        y=bottom-(bottom-top)*i/3;d.line((x0,y,x1,y),fill='#e8ebe9',width=1)
        d.text((x0-42,y-9),f'{cap*i/3:.0f}',font=font(15),fill='#959c98')
    step=(x1-x0)/len(values)
    for i,(label,v) in enumerate(values):
        cx=x0+step*(i+.5);y=bottom-(bottom-top)*v/cap
        d.rectangle((cx-52,y,cx+52,bottom),fill='#799b8c')
        value=f'{v:.1f}';box=d.textbbox((0,0),value,font=font(21));d.text((cx-(box[2]-box[0])/2,y-30),value,font=font(21),fill='#405a4f')
        box=d.textbbox((0,0),label,font=font(19));d.text((cx-(box[2]-box[0])/2,bottom+15),label,font=font(19),fill='#58625d')
    mixed(d,60,624,[('每轮分别为 12 次、6 次请求',font_cn(15)),(' / 12 and 6 requests per round, respectively',font(16))],'#8a938e')
    im.save(folder/'resolution-performance.png',optimize=True)
draw_resolution()
