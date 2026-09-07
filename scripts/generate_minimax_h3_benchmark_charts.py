#!/usr/bin/env python3
"""Create H3 charts exclusively from completed, qualified measurement records."""
import argparse
import math
from pathlib import Path
import json
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
FONT = '/System/Library/Fonts/Hiragino Sans GB.ttc'
BG = '#f5f9fc'; INK = '#172e45'; MUTED = '#60758a'; GRID = '#d9e4ed'
ENGINES = [('sglang', 'SGLang', '#1776a0'), ('vllm-omni', 'vLLM-Omni', '#278c8f')]

def label(draw, x, y, value, size=22, color=INK, centered=False):
    font = ImageFont.truetype(FONT, size)
    box = draw.textbbox((0, 0), value, font=font)
    left = x - (box[2] + box[0]) / 2 if centered else x - box[0]
    draw.text((left, y - box[1]), value, font=font, fill=color)

def chart(data, configurations, labels, metric, divisor, unit, title, subtitle, footnote, output):
    by_key = {(x['engine'], x['configuration']): x for x in data['configurations']}
    rows = []
    for configuration in configurations:
        pair = []
        for engine, _, _ in ENGINES:
            row = by_key.get((engine, configuration))
            if row is None or row['status'] != 'PASS':
                raise ValueError(f'Chart requires completed qualified data: {engine} {configuration}')
            pair.append(row)
        rows.append(pair)
    maximum = max(row[metric] / divisor for pair in rows for row in pair)
    magnitude = 10 ** math.floor(math.log10(maximum * 1.18))
    tick = next(x * magnitude / 5 for x in (1, 2, 5, 10) if x * magnitude >= maximum * 1.18)
    ceiling = tick * 5
    image = Image.new('RGB', (1200, 675), BG); draw = ImageDraw.Draw(image)
    label(draw, 56, 36, title, 37)
    label(draw, 57, 96, subtitle, 20, MUTED)
    for i, (_, name, color) in enumerate(ENGINES):
        x = 56 + i * 235
        draw.rounded_rectangle((x, 143, x + 23, 161), radius=3, fill=color)
        label(draw, x + 35, 140, name, 20)
    label(draw, 1110, 143, unit, 19, MUTED, centered=True)
    top, bottom, left, right = 205, 510, 140, 1140
    def y(value): return bottom - value / ceiling * (bottom - top)
    for i in range(6):
        value = tick * i
        draw.line((left, y(value), right, y(value)), fill=GRID, width=1)
        label(draw, 102, y(value) - 10, f'{value:g}', 18, MUTED, centered=True)
    for i, (pair, category) in enumerate(zip(rows, labels)):
        center = left + (right - left) * (i + .5) / len(rows)
        for j, row in enumerate(pair):
            value = row[metric] / divisor
            x = center + (-57 if j == 0 else 57)
            draw.rectangle((x - 40, y(value), x + 40, bottom), fill=ENGINES[j][2])
            label(draw, x, y(value) - 35, f'{value:.2f}', 22, ENGINES[j][2], centered=True)
        label(draw, center, 537, category, 23, centered=True)
    label(draw, 56, 595, footnote, 19, MUTED)
    label(draw, 56, 633, '版本与运行时段见正文；部分共享主机，不构成严格引擎速度排名。', 18, MUTED)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)
    return image

def reference_chart(data, output):
    by_key = {(x['engine'], x['configuration']): x for x in data['configurations']}
    im = Image.new('RGB', (1200, 900), BG); d = ImageDraw.Draw(im)
    label(d, 55, 38, '参考输入不同，5 秒视频要等多久', 38)
    label(d, 56, 104, 'H3 · 4 × H20-3e · 1344 × 768 · 50 个采样点 · 原始 BF16/FP32', 21, MUTED)
    for i, (_, name, color) in enumerate(ENGINES):
        x=260+i*250; d.rectangle((x,153,x+22,173),fill=color);label(d,x+35,150,name,23)
    left,right,top,bottom=260,1080,220,755
    for tick in range(0,26,5):
        x=left+(right-left)*tick/25; d.line((x,top-18,x,bottom),fill=GRID,width=1)
        label(d,x,775,str(tick),21,MUTED,centered=True)
    label(d,1100,775,'分钟',20,MUTED)
    cases=[('image','单图'),('images','三图'),('video-silent','无声视频'),('video-sound','有声视频'),('image-audio','图片 + 音频'),('mixed','图 + 视频 + 音频')]
    for i,(key,name) in enumerate(cases):
        y=top+i*90;label(d,55,y+13,name,25)
        for j,(engine,_,color) in enumerate(ENGINES):
            row=by_key[engine,'ref2va-'+key+'-c1']; assert row['status']=='PASS' and row['qualified_pass']==3
            value=row['e2e_median_s']/60; end=left+(right-left)*value/25
            yy=y+j*33;d.rectangle((left,yy,end,yy+25),fill=color);label(d,end+9,yy+1,f'{value:.2f}',22,color)
    label(d,55,826,'每配置 3 次正式请求的中位数，并发 1；预热排除。',22,MUTED)
    label(d,55,864,'部分版本、节点与运行时段不同；观测值不代表严格引擎速度排名。',20,MUTED)
    im.save(output);return im

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data', type=Path, required=True)
    a = p.parse_args()
    data = json.loads(a.data.read_text())
    out = ROOT / 'docs/assets/practices/minimax-h3-h20'
    shared = '4 × H20-3e · 1344 × 768 · 24 fps · 50 个采样点 · 原始 BF16/FP32'
    latency = chart(data, ['t2va-5s-c1', 't2va-10s-c1', 't2va-15s-c1'],
        ['请求 5 秒', '请求 10 秒', '请求 15 秒'], 'e2e_median_s', 60, '分钟',
        '单请求端到端生成耗时', shared,
        '每配置 3 个正式样本的中位数；跨时长为不同提示词用例，非纯时长消融。', out / 'latency.png')
    throughput = chart(data, ['t2va-5s-c1', 't2va-5s-c2', 't2va-5s-c4'],
        ['并发 1', '并发 2', '并发 4'], 'validated_videos_per_hour', 1, '视频/小时',
        '并发增加后，每小时能完成多少视频', shared,
        '5 秒固定用例；每配置 3 批，吞吐分母包含客户端媒体解码校验。', out / 'throughput.png')
    social = ROOT / 'articles/wechat/assets/minimax-h3-h20'
    latency.save(social / 'latency.png'); throughput.save(social / 'throughput.png')
    queue = chart(data, ['t2va-5s-c1', 't2va-5s-c2', 't2va-5s-c4'],
        ['并发 1', '并发 2', '并发 4'], 'e2e_median_s', 60, '分钟',
        '同时提交更多任务，单个请求等得更久', shared,
        '5 秒文本用例，正式请求 3 / 6 / 12 次；中位数，预热排除。', out / 'queue-latency.png')
    frames = chart(data, ['t2va-5s-c1','fl2va-first-c1','fl2va-last-c1','fl2va-both-c1'],
        ['无图文本','仅首帧','仅尾帧','首尾帧'], 'e2e_median_s', 1, '秒',
        '从文本到首尾帧控制，耗时如何变化', shared,
        '每配置 3 次正式请求的中位数；输出 5 秒，并发 1。', out / 'keyframes.png')
    reference = reference_chart(data, out / 'reference-latency.png')
    queue.save(social / 'queue-latency.png');frames.save(social / 'keyframes.png')
    reference.save(social / 'reference-latency.png')
    print(out)
