#!/usr/bin/env python3
"""Render figures from the published, sanitized read-only observation dataset."""
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/assets/practices/deepseek-v41-pro5000-h20-observation'
DATA = json.loads((OUT / 'observation.json').read_text())
FONT = '/System/Library/Fonts/Hiragino Sans GB.ttc'
BG, INK, MUTED, GRID = '#F5F7FF', '#24304B', '#7481A0', '#D4DDF4'
BLUE, PURPLE = '#4D6BFE', '#8056D9'


def text(d, xy, s, size=24, color=INK, anchor='lt'):
    font = ImageFont.truetype(FONT, size)
    box = d.textbbox(xy, s, font=font, anchor=anchor)
    assert box[0] >= 0 and box[1] >= 0 and box[2] <= 1190 and box[3] <= 665, (s, box)
    d.text(xy, s, font=font, fill=color, anchor=anchor)


def value(metric, hardware):
    return next(s['value'] for s in DATA['aggregates'][metric]['series'] if s['labels']['hardware'] == hardware)


def canvas(title, subtitle, en):
    im = Image.new('RGB', (1200, 675), BG)
    d = ImageDraw.Draw(im)
    text(d, (45, 34), title, 34)
    text(d, (45, 92), subtitle, 21, MUTED)
    return im, d


def legend(d, y, en):
    for x, color, label in [(55, BLUE, 'PRO 5000 72GB'), (530, PURPLE, 'H20-3e / 4-replica mean' if en else 'H20-3e / 4 副本均值')]:
        d.line((x, y+12, x+32, y+12), fill=color, width=5)
        text(d, (x+44, y), label, 22)


for en in (False, True):
    suffix = '-en' if en else ''
    im, d = canvas(
        'Different requests reached the two services' if en else '两组服务，实际接到的请求不一样',
        '2026-10-19 17:40–18:40 (UTC+08) · Completed-request histograms' if en else '2026-10-19 17:40–18:40 · 完成请求直方图的加权均值', en)
    for i, (metric, ymax, title, unit) in enumerate([
        ('pool_prompt_len_mean', 80000, 'Input tokens / request' if en else '每请求输入 Token', 'k'),
        ('pool_output_len_mean', 600, 'Output tokens / request' if en else '每请求输出 Token', '')]):
        left = 45 + i*570
        d.rounded_rectangle((left, 150, left+540, 550), 16, fill='white', outline=GRID, width=2)
        text(d, (left+25, 175), title, 26)
        x0, x1, y0, y1 = left+65, left+505, 245, 470
        for j in range(5 if ymax == 80000 else 4):
            v = j*(20000 if ymax == 80000 else 200)
            y = y1 - (v/ymax)*(y1-y0)
            d.line((x0, y, x1, y), fill=GRID, width=1)
            text(d, (x0-10, y), str(v//1000)+'k' if ymax == 80000 and v else str(v), 17, MUTED, 'rm')
        for j, (hardware, color, label) in enumerate([
            ('RTX PRO 5000 72GB', BLUE, 'PRO 5000'), ('H20-3e', PURPLE, 'H20-3e')]):
            v = value(metric, hardware)
            x = x0+65+j*205
            y = y1-(v/ymax)*(y1-y0)
            d.rectangle((x, y, x+90, y1), fill=color)
            text(d, (x+45, y-14), f'{v:,.0f}' if ymax == 80000 else f'{v:,.1f}', 25, color, 'mb')
            text(d, (x+45, 497), label, 22, INK, 'mt')
    text(d, (45, 583), 'PRO requests: all length-limited · Mean output budget = mean output length' if en else 'PRO 请求均以 length 结束，平均输出上限与平均实际输出均为 14.03 Token', 23)
    text(d, (45, 625), 'Observed workloads differ; these bars do not rank hardware performance.' if en else '这是不同负载下的线上观测，不能把吞吐相除当作显卡性能倍数。', 22, MUTED)
    im.save(OUT / f'workload-shape{suffix}.png', optimize=True)

    im, d = canvas(
        'A low hourly GPU mean can hide queue spikes' if en else 'GPU 低均值与排队长尾可以同时出现',
        'Same window · 60-second samples · 8 GPUs per replica' if en else '同一时间窗口 · 60 秒采样 · 每副本 8 张 GPU', en)
    legend(d, 130, en)
    for idx, (metric, ymax, label, ticks) in enumerate([
        ('gpu_util', 100, 'GPU utilization (%)' if en else 'GPU 利用率（%）', [0,50,100]),
        ('waiting', 25, 'Waiting requests / replica' if en else '每副本排队请求数', [0,10,20])]):
        y0 = 225 + idx*190
        y1 = y0 + 115
        x0, x1 = 100, 1135
        text(d, (55, y0-38), label, 23)
        for v in ticks:
            y = y1-v/ymax*(y1-y0)
            d.line((x0,y,x1,y),fill=GRID,width=1)
            text(d,(x0-14,y),str(v),17,MUTED,'rm')
        series=DATA['ranges'][metric]
        for pro, color in [(False,PURPLE),(True,BLUE)]:
            selected=[s['values'] for s in series if s['replica'].startswith('PRO') == pro]
            assert len(selected) == (1 if pro else 4)
            pts=[]
            for j in range(61):
                samples=[s[j][1] for s in selected if s[j][1] is not None]
                if not samples:
                    continue
                v=sum(samples)/len(samples)
                pts.append((x0+j/60*(x1-x0),y1-v/ymax*(y1-y0)))
            d.line(pts,fill=color,width=4)
        if idx == 1:
            for minute in [0,15,30,45,60]:
                time=datetime.fromisoformat(DATA['window']['start_utc'].replace('Z','+00:00'))+timedelta(hours=8,minutes=minute)
                text(d,(x0+minute/60*(x1-x0),y1+16),time.strftime('%H:%M'),18,MUTED,'mt')
    text(d,(45,602),'H20: mean across 4 replicas · PRO: 1 replica · Sampled peaks are not exhaustive' if en else 'H20 为 4 副本均值，PRO 为 1 副本；采样峰值不代表捕获了所有瞬时峰值。',21,MUTED)
    text(d,(45,638),'2026-10-19 17:40–18:40 (UTC+08) · Read-only production observation' if en else '2026-10-19 17:40–18:40 · 仅使用已有监控，未向服务生成流量',20,MUTED)
    im.save(OUT/f'gpu-queue-timeline{suffix}.png',optimize=True)
print('Rendered four 1200×675 figures from observation.json')
